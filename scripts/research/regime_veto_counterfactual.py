#!/usr/bin/env python3
"""Grade the LIVE regime vetoes on money (row REGIME-LIVE-VETO-COUNTERFACTUAL; the ml-btc-router-cells orphan's next iteration).

Every ``regime_hard_gate`` audit row is an intent the live trader DROPPED before routing (src/runtime/intents.py, Phase 3). This tool asks
whether those drops saved money, without depending on offline label parity: it replays each dropped signal on its own candles exactly as the
strategy emitted it (entry = the signal bar's close level, SL / TP as emitted; market fill at the next bar's open) and compares the dropped
signals' net R with matched random signals of the SAME strategies that the gate let through.

  fetch     pull the drop rows + the ``<strategy>_eval`` signal rows (side buy/sell only) through the read-only diag relay
            (scripts/ops/diag_fetch.sh) into one compact snapshot JSONL. Run where the relay is reachable; commit the snapshot.
  grade     snapshot -> unique signals -> replay (desk_outcomes.replay UNCHANGED, net of execution_costs.roundtrip_cost_r via
            desk_scan_packet.cost_policy) -> per-axis verdict. Reads Binance Vision USD-M futures klines (keyless); a symbol it cannot
            read is counted in ``could_not_replay``, never dropped silently.

A signal is the unique (strategy, symbol, bar_open_ts); the trader re-evaluates every tick, so one signal has many eval rows. A tick is
DROPPED when a gate row for the same strategy+symbol is logged within MATCH_S seconds after it. Signal status: ``dropped`` (every tick
dropped), ``kept`` (no tick dropped), ``mixed`` (label flipped inside the bar; excluded from the dropped set, kept in the control pool).
Axis: ``ml_vol`` when the drop row has vol_enforced=true (the ADVISORY ML vol label drove it), else ``trend`` (the ML-independent ADX axis).

Approximation, shared by both arms: a fixed HORIZON_BARS bracket replay, not the strategy's own trail. Gates this adds or changes: none.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import subprocess
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ops"))

SCHEMA = "regime_veto_counterfactual/1"
RULE_ID = "RULE-REGIME-LIVE-VETO-CF-20261126"
MATCH_S = 10.0
HORIZON_BARS = 48
N_DRAWS = 2000
SEED = 20261126
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
KLINES = "https://data.binance.vision/data/futures/um/{period}/klines/{s}/{tf}/{s}-{tf}-{d}.zip"


# ---- fetch ----------------------------------------------------------------------------------------------------------------
def _diag(path: str) -> list[dict]:
    out = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=120).stdout
    return json.loads(out.split("diag_fetch:")[0])["rows"]


def _pull(query: str, since: datetime, until: datetime, limit: int = 1000) -> list[dict]:
    """Window [since, until) halved until each page is under ``limit`` (the relay caps a page; a full page may be truncated)."""
    rows = _diag(f"audit_query?{query}&since={since:%Y-%m-%dT%H:%M:%SZ}&until={until:%Y-%m-%dT%H:%M:%SZ}&limit={limit}")
    if len(rows) >= limit and until - since > timedelta(minutes=30):
        mid = since + (until - since) / 2
        return _pull(query, since, mid, limit) + _pull(query, mid, until, limit)
    return rows


def compact(r: dict) -> dict:
    keep = ("event", "strategy", "symbol", "side", "logged_at_utc", "timeframe", "entry", "stop_loss", "take_profit", "bar_open_ts",
            "gated", "vol_enforced", "vol_regime", "p_volatile", "regime", "cell", "vol_cell", "reason", "vol_reason")
    return {k: r.get(k) for k in keep if r.get(k) is not None}


def fetch(since: datetime, until: datetime, out: Path, step_days: int = 4) -> dict:
    drops, d = [], since
    while d < until:
        e = min(d + timedelta(days=step_days), until)
        drops += _pull("event=regime_hard_gate", d, e)
        d = e
    evals = []
    for st in sorted({r["strategy"] for r in drops}):
        for side in ("buy", "sell"):
            d = since
            while d < until:
                e = min(d + timedelta(days=step_days), until)
                evals += _pull(f"event={st}_eval&side={side}", d, e)
                d = e
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for r in drops + evals:
            fh.write(json.dumps(compact(r), sort_keys=True) + "\n")
    return {"drops": len(drops), "evals": len(evals), "since": f"{since:%Y-%m-%dT%H:%M:%SZ}", "until": f"{until:%Y-%m-%dT%H:%M:%SZ}"}


# ---- signals --------------------------------------------------------------------------------------------------------------
def _t(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def signals(rows: list[dict]) -> list[dict]:
    drops = defaultdict(list)
    for r in rows:
        if r.get("event") == "regime_hard_gate":
            drops[(r["strategy"], r["symbol"])].append((_t(r["logged_at_utc"]), "ml_vol" if r.get("vol_enforced") else "trend"))
    for v in drops.values():
        v.sort()
    sig: dict[tuple, dict] = {}
    for r in rows:
        ev = r.get("event") or ""
        if not ev.endswith("_eval") or r.get("side") not in ("buy", "sell") or r.get("entry") is None or r.get("bar_open_ts") is None:
            continue
        if r.get("stop_loss") is None or r.get("take_profit") is None or r.get("timeframe") not in TF_SECONDS:
            continue
        k = (r["strategy"], r["symbol"], float(r["bar_open_ts"]))
        s = sig.setdefault(k, {"strategy": r["strategy"], "symbol": r["symbol"], "bar_open_ts": float(r["bar_open_ts"]),
                               "timeframe": r["timeframe"], "side": "long" if r["side"] == "buy" else "short", "entry": float(r["entry"]),
                               "sl": float(r["stop_loss"]), "tp": float(r["take_profit"]), "ticks": 0, "dropped_ticks": 0, "axes": set()})
        s["ticks"] += 1
        t = _t(r["logged_at_utc"])
        hit = next((ax for (td, ax) in drops.get((r["strategy"], r["symbol"]), []) if 0.0 <= td - t <= MATCH_S), None)
        if hit:
            s["dropped_ticks"] += 1
            s["axes"].add(hit)
    out = []
    for s in sig.values():
        s["status"] = "dropped" if s["dropped_ticks"] == s["ticks"] else ("kept" if s["dropped_ticks"] == 0 else "mixed")
        s["axis"] = ("ml_vol" if "ml_vol" in s["axes"] else "trend") if s["axes"] else None
        s["axes"] = sorted(s["axes"])
        out.append(s)
    return sorted(out, key=lambda s: (s["strategy"], s["symbol"], s["bar_open_ts"]))


# ---- bars + replay --------------------------------------------------------------------------------------------------------
def _zip_rows(url: str) -> list[dict] | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": "research-script"}), timeout=60) as resp:
            data = resp.read()
    except Exception:  # noqa: BLE001 -- a missing day/month is "could not look", counted by the caller
        return None
    bars = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for ln in z.read(z.namelist()[0]).decode().splitlines():
            p = ln.split(",")
            if not p or not p[0].isdigit():
                continue
            bars.append({"time": int(p[0]) / 1000.0, "open": float(p[1]), "high": float(p[2]), "low": float(p[3]), "close": float(p[4])})
    return bars


def binance_bars(symbol: str, tf: str, start: datetime, end: datetime) -> list[dict] | None:
    """USD-M futures klines from the keyless Binance Vision archive: monthly files for whole past months, daily files otherwise."""
    bars, d, got = [], start.replace(day=1, hour=0, minute=0, second=0, microsecond=0), False
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        rows = _zip_rows(KLINES.format(period="monthly", s=symbol, tf=tf, d=f"{d:%Y-%m}")) if nxt <= today else None
        if rows is None:
            day = d
            while day < min(nxt, end + timedelta(days=1)):
                r = _zip_rows(KLINES.format(period="daily", s=symbol, tf=tf, d=f"{day:%Y-%m-%d}"))
                if r:
                    bars += r
                    got = True
                day += timedelta(days=1)
        else:
            bars += rows
            got = True
        d = nxt
    return sorted({b["time"]: b for b in bars}.values(), key=lambda b: b["time"]) if got else None


def replay_signal(s: dict, bars: list[dict], horizon: int = HORIZON_BARS) -> dict | None:
    import desk_outcomes as do
    pr = {"timeframe": s["timeframe"], "side": s["side"], "entry": {"level": s["entry"], "type": "market", "good_till_bars": 1},
          "stop": {"level": s["sl"]}, "tp": {"level": s["tp"]}, "horizon_bars": horizon}
    cutoff = datetime.fromtimestamp(s["bar_open_ts"] + TF_SECONDS[s["timeframe"]], tz=timezone.utc)
    return do.replay(pr, cutoff, bars, do._cost_fn(s["symbol"]))


# ---- grade ----------------------------------------------------------------------------------------------------------------
def _boot_ci(x: list[float], rng: random.Random, n: int = N_DRAWS, lo: float = 0.05, hi: float = 0.95) -> tuple[float, float]:
    ms = sorted(statistics.fmean(rng.choices(x, k=len(x))) for _ in range(n))
    return ms[int(lo * n)], ms[min(n - 1, int(hi * n))]


def axis_verdict(dropped: list[dict], pool: dict[str, list[float]], rng: random.Random, min_n: int = 5) -> dict:
    """RULE (registered before the run): PASS = the veto saved money: mean dropped net R < 0, its 90% bootstrap CI upper bound < 0, AND it is
    at or below the 10th percentile of matched random draws (one same-strategy signal per dropped signal, from all replayed signals of that
    strategy). FAIL = the veto cost money: 90% CI lower bound > 0. Else INDETERMINATE (n < min_n is INDETERMINATE, 'underpowered')."""
    r = [d["net_r"] for d in dropped]
    if len(r) < min_n:
        return {"verdict": "indeterminate", "label": "underpowered", "n": len(r), "mean_r": statistics.fmean(r) if r else None}
    mean = statistics.fmean(r)
    lo, hi = _boot_ci(r, rng)
    draws = []
    for _ in range(N_DRAWS):
        draws.append(statistics.fmean(rng.choice(pool[d["strategy"]]) for d in dropped))
    p_ctrl = sum(1 for m in draws if m <= mean) / len(draws)
    if mean < 0 and hi < 0 and p_ctrl <= 0.10:
        v, lab = "pass", "veto_saved_money"
    elif lo > 0:
        v, lab = "fail", "veto_cost_money"
    else:
        v, lab = "indeterminate", "not_separable"
    return {"verdict": v, "label": lab, "n": len(r), "mean_r": round(mean, 4), "sum_r_avoided": round(-sum(r), 3), "ci90": [round(lo, 4), round(hi, 4)],
            "control_mean_r": round(statistics.fmean(draws), 4), "p_control_le": round(p_ctrl, 4),
            "by_strategy": {st: {"n": sum(1 for d in dropped if d["strategy"] == st),
                                 "mean_r": round(statistics.fmean(d["net_r"] for d in dropped if d["strategy"] == st), 4)}
                            for st in sorted({d["strategy"] for d in dropped})}}


def grade(snapshot: Path, out_dir: Path, bars_fn=binance_bars, horizon: int = HORIZON_BARS) -> dict:
    rows = [json.loads(ln) for ln in snapshot.read_text().splitlines() if ln.strip()]
    sigs = signals(rows)
    could = defaultdict(int)
    cache: dict[tuple, list | None] = {}
    replayed = []
    for s in sigs:
        k = (s["symbol"], s["timeframe"])
        if k not in cache:
            ts = [x["bar_open_ts"] for x in sigs if (x["symbol"], x["timeframe"]) == k]
            span = TF_SECONDS[s["timeframe"]] * (horizon + 2)
            cache[k] = bars_fn(s["symbol"], s["timeframe"], datetime.fromtimestamp(min(ts), tz=timezone.utc),
                               datetime.fromtimestamp(max(ts) + span, tz=timezone.utc))
        bars = cache[k]
        if not bars:
            could["no_bars:" + s["symbol"]] += 1
            continue
        res = replay_signal(s, bars, horizon)
        if res is None:
            could["horizon_not_elapsed"] += 1
            continue
        if res.get("kind") != "replayed":
            could[res.get("kind") or "not_replayed"] += 1
            continue
        replayed.append({**s, "net_r": res["net_r"], "close_reason": res["close_reason"]})
    rng = random.Random(SEED)
    pool = defaultdict(list)
    for s in replayed:
        pool[s["strategy"]].append(s["net_r"])
    axes = {}
    for ax in ("ml_vol", "trend"):
        dropped = [s for s in replayed if s["status"] == "dropped" and s["axis"] == ax]
        axes[ax] = axis_verdict(dropped, pool, rng)
        axes[ax]["n_mixed_signals"] = sum(1 for s in sigs if s["status"] == "mixed" and s["axis"] == ax)
    status = defaultdict(int)
    for s in sigs:
        status[s["status"]] += 1
    span = [r["logged_at_utc"] for r in rows if r.get("logged_at_utc")]
    rep = {"schema": SCHEMA, "rule_id": RULE_ID, "read_state": "measured" if replayed else "unreadable",
           "population": (f"{len(sigs)} unique live signals (strategy, symbol, bar) of the strategies the live regime_hard_gate dropped, "
                          f"{min(span) if span else None}..{max(span) if span else None}; {len(replayed)} replayed on Binance Vision USD-M klines, "
                          f"market fill at the next bar open, emitted SL/TP, {horizon}-bar horizon, net of the full cost stack"),
           "signals_by_status": dict(status), "n_replayed": len(replayed), "could_not_replay": dict(could), "axes": axes,
           "verdict": axes["trend"]["verdict"], "provenance": "ESTIMATED",
           "note": ("verdict = the trend (ADX) axis, re-designated before any outcome was computed: the snapshot holds 1 ML-vol signal dropped on "
                    "every tick (n < 5, underpowered by count), so the ml_vol axis is reported beside it with its mixed-bar count.")}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "signals.jsonl").write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in replayed))
    (out_dir / "grade.json").write_text(json.dumps(rep, indent=1) + "\n")
    (out_dir / "verdict.json").write_text(json.dumps({k: rep[k] for k in ("schema", "rule_id", "verdict", "read_state", "population",
                                                                            "n_replayed", "axes")}, indent=1) + "\n")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--since", required=True)
    f.add_argument("--until", required=True)
    f.add_argument("--out", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--snapshot", required=True)
    g.add_argument("--out-dir", required=True)
    g.add_argument("--horizon-bars", type=int, default=HORIZON_BARS)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        p = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)  # noqa: E731
        print(json.dumps(fetch(p(a.since), p(a.until), Path(a.out))))
        return 0
    rep = grade(Path(a.snapshot), Path(a.out_dir), horizon=a.horizon_bars)
    print(json.dumps({k: rep[k] for k in ("verdict", "read_state", "n_replayed", "signals_by_status")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
