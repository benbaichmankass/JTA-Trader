#!/usr/bin/env python3
"""Per-leg continuous VOL-TARGET SIZING verdict (row IR-VOL-TARGET-SIZING-STAGE0; programme node P2-R5-voltarget-sizing).

The question the on/off regime SKIP units cannot answer: does scaling a leg's exposure to a constant realized-vol
budget (``scripts/backtest_vol_target.py``, the one overlay implementation) improve its net Sharpe, without a worse
drawdown, consistently over time?

Steps (one leg per run):
1. Candles. The trainer's BYBIT linear file (``m20_fleet_exit_sweep.resolve_data`` on ``--data-dir``), aggregated
   OPEN-stamped to the leg's timeframe. Bybit is the venue the real-money legs trade: the fleet venue-gap measurement
   (PI-20261120-7ITMUEB1-0005, relays #27588/#27603/#27615) found Binance-fed Stage-0 evidence overstates the Bybit
   book by a trade-weighted 0.0185 R/trade (95% CI 0.010..0.028, 21 legs), so this grader reads the live venue
   (manager 2026-11-20 03:50Z). ``--trades`` skips steps 1-2 (tests / a pre-emitted ledger).
2. Trades. The leg's exact Stage-0 evidence argv (``regime_debt_matrix.build_harness_cmd``) with ``--emit-trades``.
3. Overlay. ``backtest_vol_target.build_book`` -> ``run_vol_target(..., return_series=True)`` with the venue-aware
   cost policy for the leg's symbol (turnover + funding; never a silent zero).
4. Rule (registered on the unit, thresholds passed as flags, never defaults chosen here):
   INDETERMINATE if n_trades < --n-floor. Otherwise PASS iff
     (a) dSharpe = Sharpe(targeted) - Sharpe(baseline) >= --dsharpe-bar   (net of the overlay's costs), AND
     (b) maxDD(targeted) <= maxDD(baseline)                               (drawdowns are positive R magnitudes), AND
     (c) dSharpe > 0 in >= --block-majority of --blocks equal calendar blocks of the daily series;
   FAIL otherwise.
Writes ``<out>/verdict.json`` in the ``script_run.py`` contract.

Research only (Tier 1): reads candles, runs a harness, writes under ``--out`` and ``--work``. No config write.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "scripts" / "research")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RULE_FIELDS = ("dsharpe_bar", "n_floor", "blocks", "block_majority")


def block_sharpes(dates: Sequence[str], base: Sequence[float], scaled: Sequence[float], blocks: int) -> list[dict[str, Any]]:
    """Split the daily series into ``blocks`` equal CALENDAR spans (by date, not by count) and Sharpe each arm."""
    import pandas as pd

    from scripts.portfolio_combine import sharpe_annualized
    if not dates:
        return []
    ts = pd.to_datetime(list(dates))
    lo, hi = ts.min(), ts.max()
    edges = [lo + (hi - lo) * k / blocks for k in range(blocks + 1)]
    out = []
    for k in range(blocks):
        a, b = edges[k], edges[k + 1]
        idx = [i for i, t in enumerate(ts) if (t >= a and (t < b or (k == blocks - 1 and t <= b)))]
        sb = sharpe_annualized([base[i] for i in idx]) if len(idx) > 1 else None
        ss = sharpe_annualized([scaled[i] for i in idx]) if len(idx) > 1 else None
        d = round(ss - sb, 4) if (sb is not None and ss is not None) else None
        out.append({"block": k, "start": str(a.date()), "end": str(b.date()), "n_days": len(idx),
                    "sharpe_baseline": sb, "sharpe_targeted": ss, "dsharpe": d})
    return out


def decide(n_trades: int, overlay: dict[str, Any], blocks: list[dict[str, Any]], *, dsharpe_bar: float, n_floor: int,
           block_majority: int) -> dict[str, Any]:
    ds = overlay.get("sharpe_delta")
    dd_b = (overlay.get("baseline") or {}).get("max_drawdown_r")
    dd_t = (overlay.get("vol_targeted") or {}).get("max_drawdown_r")
    pos = sum(1 for b in blocks if b.get("dsharpe") is not None and b["dsharpe"] > 0)
    m = {"n_trades": n_trades, "dsharpe": ds, "maxdd_baseline_r": dd_b, "maxdd_targeted_r": dd_t,
         "blocks_dsharpe_positive": pos, "blocks": len(blocks)}
    if n_trades < n_floor:
        return {"verdict": "indeterminate", "label": "underpowered", **m}
    if ds is None or dd_b is None or dd_t is None:
        return {"verdict": "indeterminate", "label": "unmeasurable", **m}
    a, b, c = ds >= dsharpe_bar, dd_t <= dd_b, pos >= block_majority
    m.update({"clause_a_dsharpe": a, "clause_b_maxdd": b, "clause_c_blocks": c})
    if a and b and c:
        return {"verdict": "pass", "label": "vol_target_improves", **m}
    return {"verdict": "fail", "label": "vol_target_does_not_clear", **m}


def emit_trades(leg: str, data_dir: Path, work: Path, start: str | None, end: str | None) -> dict[str, Any]:
    import pandas as pd
    import regime_debt_matrix as rdm
    import yaml
    from m20_fleet_exit_sweep import resolve_data

    from scripts.ops.backtest_data_source import resample_open_stamped
    cfg = (yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()) or {})["strategies"][leg]
    sym, tf = cfg["symbols"][0], str(cfg["timeframe"])
    h = rdm.classify(cfg)
    if h is None:
        raise SystemExit(f"vol_target_verdict: {leg} has no Stage-0 harness (classify() is None)")
    path, proxy, resample = resolve_data(sym, tf, data_dir)
    if not path:
        raise SystemExit(f"vol_target_verdict: no candle file for {sym} {tf} under {data_dir}")
    work.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(path)
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    d = d.dropna(subset=["timestamp"]).sort_values("timestamp")
    d = resample_open_stamped(d, tf if resample else None)
    csv = work / f"{leg}__bybit_{tf}.csv"
    d.to_csv(csv, index=False)
    emit, jout = work / f"{leg}__trades.jsonl", work / f"{leg}__bt.json"
    argv, faithful, omitted = rdm.build_harness_cmd(leg, cfg, h, str(csv), tf, str(emit), str(jout))
    if start:
        argv += ["--start", start]
    if end:
        argv += ["--end", end]
    env = {k: v for k, v in os.environ.items() if k != "BACKTEST_DATA_PATH"}
    p = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(REPO), check=False)
    if p.returncode != 0:
        raise SystemExit(f"vol_target_verdict: harness rc={p.returncode}: {(p.stderr or p.stdout)[-400:]}")
    return {"trades": str(emit), "symbol": sym, "timeframe": tf, "harness": h, "faithful": faithful,
            "omitted_levers": omitted, "candle_source": {"path": str(path), "venue": "bybit_linear (trainer data/)",
            "proxy": bool(proxy), "resampled_to": tf if resample else None, "bars": len(d),
            "first": str(d["timestamp"].min()) if len(d) else None, "last": str(d["timestamp"].max()) if len(d) else None}}


def run(a: argparse.Namespace) -> dict[str, Any]:
    import scripts.backtest_vol_target as vt
    src: dict[str, Any] = {}
    if a.trades:
        trades = a.trades
        sym = a.cost_symbol
    else:
        src = emit_trades(a.leg, Path(a.data_dir), Path(a.work), a.start, a.end)
        trades, sym = src["trades"], src["symbol"]
    with open(trades) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    n_trades = sum(1 for r in rows if r.get("net_r") is not None)
    daily, _summary = vt.build_book([trades], basis=a.basis)
    costs = vt.resolve_overlay_costs(sym or vt.DEFAULT_COST_SYMBOL)
    overlay = vt.run_vol_target(daily, target_vol=a.target_vol, short=a.short, long=a.long, blend=a.blend,
                                cap_lo=a.cap_lo, cap_hi=a.cap_hi, retarget=a.retarget, costs=costs, return_series=True)
    series = overlay.pop("series")
    blocks = block_sharpes(series["dates"], series["baseline_r"], series["scaled_r"], a.blocks)
    v = decide(n_trades, overlay, blocks, dsharpe_bar=a.dsharpe_bar, n_floor=a.n_floor, block_majority=a.block_majority)
    pop = (f"{a.leg}: {n_trades} Stage-0 trades on {src.get('candle_source', {}).get('venue', 'a supplied ledger')}, "
           f"{overlay.get('data_start')}..{overlay.get('data_end')} ({len(daily)} book days)")
    return {"verdict": v.pop("verdict"), "read_state": "measured", "population": pop, "n": n_trades,
            "measurement": {**v, "overlay": overlay, "block_detail": blocks, "source": src,
                            "rule_thresholds": {k: getattr(a, k) for k in RULE_FIELDS}}}


def _self_test() -> int:
    import random
    fails = []

    def chk(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ov = {"sharpe_delta": 0.2, "baseline": {"max_drawdown_r": 5.0}, "vol_targeted": {"max_drawdown_r": 4.0}}
    blocks = [{"dsharpe": x} for x in (0.1, 0.2, -0.1, 0.3)]
    chk("all clauses -> pass", decide(150, ov, blocks, dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "pass")
    chk("underpowered -> indeterminate", decide(50, ov, blocks, dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "indeterminate")
    chk("dsharpe below bar -> fail", decide(150, {**ov, "sharpe_delta": 0.05}, blocks, dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "fail")
    chk("worse drawdown -> fail", decide(150, {**ov, "vol_targeted": {"max_drawdown_r": 6.0}}, blocks, dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "fail")
    chk("2 of 4 blocks -> fail", decide(150, ov, [{"dsharpe": x} for x in (0.1, -0.2, -0.1, 0.3)], dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "fail")
    chk("missing sharpe -> indeterminate", decide(150, {**ov, "sharpe_delta": None}, blocks, dsharpe_bar=0.1, n_floor=100, block_majority=3)["verdict"] == "indeterminate")
    rnd = random.Random(1)
    dates = [f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(336)]
    base = [rnd.gauss(0.01, 0.1) for _ in dates]
    bl = block_sharpes(dates, base, [x * 1.0 for x in base], 4)
    chk("4 calendar blocks cover every day", sum(b["n_days"] for b in bl) == len(dates))
    chk("identical arms -> dsharpe 0 in every block", all(b["dsharpe"] == 0 for b in bl))
    print("vol_target_verdict self-test:", "OK" if not fails else f"FAILED {fails}")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--leg")
    ap.add_argument("--data-dir", default=str(REPO / "data"), help="trainer data/ (Bybit linear files)")
    ap.add_argument("--work", default="/tmp/vol_target_verdict")
    ap.add_argument("--trades", default=None, help="a pre-emitted trades JSONL (skips the candle + harness steps)")
    ap.add_argument("--cost-symbol", default=None, help="with --trades: the symbol whose cost policy applies")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--basis", choices=["entry", "exit", "auto"], default="auto")
    ap.add_argument("--target-vol", type=float, default=0.10)
    ap.add_argument("--short", type=int, default=20)
    ap.add_argument("--long", type=int, default=60)
    ap.add_argument("--blend", type=float, default=0.5)
    ap.add_argument("--cap-lo", type=float, default=0.5)
    ap.add_argument("--cap-hi", type=float, default=1.5)
    ap.add_argument("--retarget", choices=["daily", "weekly", "monthly"], default="weekly")
    ap.add_argument("--dsharpe-bar", type=float)
    ap.add_argument("--n-floor", type=int)
    ap.add_argument("--blocks", type=int, default=4)
    ap.add_argument("--block-majority", type=int)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    missing = [f for f in ("leg", "dsharpe_bar", "n_floor", "block_majority", "out") if getattr(a, f) is None]
    if missing:
        ap.error("required: " + ", ".join("--" + m.replace("_", "-") for m in missing) + " (the unit's rule thresholds are flags, never defaults)")
    try:
        v = run(a)
    except SystemExit as exc:
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "population": str(a.leg), "n": None,
             "note": str(exc)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "population", "n")}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
