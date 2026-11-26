#!/usr/bin/env python3
# wiring: run by the 13:00Z DESK-MACRO-DAILY brief lane before it drafts the day's brief (.claude/skills/trading-desk/SKILL.md section 7b); row DESK-MACRO-DAILY
"""DESK-MACRO-DAILY grading adapter: every shadow trade in a `desk_macro_brief/1` brief becomes a graded outcome row.

Spec docs/research/desk-macro-daily-SPEC-2026-11-25.md section 5 ("Trades: replayed from info_cutoff_at on real daily candles by
the desk outcome replayer, daily timeframe, net of the full cost stack"). The replay is `desk_outcomes.replay` UNCHANGED (forward
bars open at or after info_cutoff_at; limit / stop / market fills within good_till_bars; a bar touching both stop and target is the
stop; horizon exit at the close; R = the proposal's own |entry - stop|; net of `execution_costs.roundtrip_cost_r` with the
venue-aware `desk_scan_packet.cost_policy`). Only closed 1d bars are read.

Rows append to comms/desk/macro/outcomes.jsonl (schema desk_macro_outcome/1), one per (brief_id, trade index), never edited.
Each row also carries ``handoff``: every management item (watch_for / tighten_if / exit_early_if) of the trade, with its machine
``check`` evaluated on the trade's replay window (the first good_till_bars + horizon_bars closed daily bars after info_cutoff_at;
the replay does not expose its fill bar, so the window is the whole period the trade could have been live) -> fired true/false and
the first bar it fired on; an item without a check is logged ``not_machine_checkable``. This is how the operator's LTR handoff
(2026-11-26) is graded: did the conditions the brief told the reviewer to watch actually occur, and did the trade's result differ.

FORECASTS (operator 2026-11-26: the brief develops its own forecasts) are graded into comms/desk/macro/forecast_outcomes.jsonl
(schema desk_macro_forecast_outcome/1), one row per (brief_id, forecast_id), once the target has resolved: a ``release`` forecast
whose target names its FRED series / transform / period is scored against the realised value AND against the naive point and the
consensus it carried (|error| each, inside-interval, own beats naive / consensus); an ``asset_return`` forecast against the realised
close-to-close return over its horizon; an ``asset_p_tp`` forecast is the trade's judge_prior and is scored by the trade rows' Brier.
Unresolvable is retried, then ``not_computable`` with the reason, never a zero.

A trade whose horizon has not elapsed, or whose candles could not be read, gets NO row this run (could-not-look is retried, never
written as zero); one still unreadable 2 days past its horizon gets a `not_computable` row naming why.

  python3 scripts/ops/desk_macro_outcomes.py [--briefs comms/desk/macro] [--outcomes comms/desk/macro/outcomes.jsonl]
  python3 scripts/ops/desk_macro_outcomes.py --summary      # n, hit rate, mean net R, Brier of judge_prior / tp.p_hit
  python3 scripts/ops/desk_macro_outcomes.py --self-test

Exit: 0 ok · 2 could not look (briefs directory missing).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "scripts" / "ci", ROOT / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_outcomes as do  # noqa: E402
import desk_scan_packet as dsp  # noqa: E402

BRIEFS = ROOT / "comms" / "desk" / "macro"
OUTCOMES = BRIEFS / "outcomes.jsonl"
SCHEMA = "desk_macro_outcome/1"
DAY = 86400


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def _briefs(d: Path) -> list[dict]:
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            b = json.loads(p.read_text())
        except (OSError, ValueError):  # allow-silent: an unreadable file is not a brief; desk_macro_write refuses malformed briefs at write time
            continue
        if isinstance(b, dict) and b.get("schema") == "desk_macro_brief/1":
            out.append(b)
    return out


def _done(outcomes: Path) -> set[str]:
    if not outcomes.exists():
        return set()
    ids = set()
    for line in outcomes.read_text().splitlines():
        if line.strip():
            try:
                ids.add(json.loads(line)["outcome_id"])
            except (ValueError, KeyError):  # allow-silent: a damaged line keeps its id unknown, so that trade is re-graded, never dropped
                continue
    return ids


HANDOFF_GROUPS = ("watch_for", "tighten_if", "exit_early_if")


def handoff_checks(t: dict, cutoff: datetime, closed: list | None) -> dict:
    p = t.get("proposal") or {}
    m = t.get("management")
    if not isinstance(m, dict):
        return {"read_state": "not_applicable", "reason": "trade has no management block (pre-2026-11-26 brief)", "items": []}
    window = None
    if closed:
        n = int((p.get("entry") or {}).get("good_till_bars") or 0) + int(p.get("horizon_bars") or 0)
        window = [x for x in sorted(closed, key=lambda x: x["time"]) if x["time"] >= cutoff.timestamp()][:n]
    items = []
    for g in HANDOFF_GROUPS:
        for j, it in enumerate(m.get(g) or []):
            ck = (it or {}).get("check") if isinstance(it, dict) else None
            rec = {"group": g, "index": j, "signal": (it or {}).get("signal") if isinstance(it, dict) else str(it)}
            if not ck:
                rec["state"] = "not_machine_checkable"
            elif not window:
                rec["state"] = "could_not_look"
            else:
                kind, lvl = ck.get("kind"), float(ck.get("level"))
                field, above = {"close_above": ("close", True), "close_below": ("close", False),
                                "high_above": ("high", True), "low_below": ("low", False)}.get(kind, (None, None))
                if field is None:
                    rec["state"] = "invalid_check"
                else:
                    hit = next((k for k, x in enumerate(window) if (float(x[field]) > lvl if above else float(x[field]) < lvl)), None)
                    rec.update({"state": "evaluated", "check": {"kind": kind, "level": lvl}, "fired": hit is not None,
                                "fired_bar": hit, "fired_at": do._iso(datetime.fromtimestamp(window[hit]["time"], timezone.utc)) if hit is not None else None,
                                "window_bars": len(window)})
            items.append(rec)
    ev = [x for x in items if x["state"] == "evaluated"]
    return {"read_state": "measured" if ev else ("could_not_look" if any(x["state"] == "could_not_look" for x in items) else "measured"),
            "n_items": len(items), "n_evaluated": len(ev), "n_fired": sum(1 for x in ev if x["fired"]), "items": items}


def _fmap(b: dict) -> dict:
    return {f.get("forecast_id"): f for f in (b.get("forecasts") or []) if isinstance(f, dict)}


def row(b: dict, i: int, t: dict, res: dict, now: datetime, policy: str | None, handoff: dict | None = None) -> dict:
    p = t["proposal"]
    nums = {k: do._r4(res.get(k)) for k in ("net_r", "mae_r", "mfe_r", "giveback_r")}
    return {"schema": SCHEMA, "outcome_id": f"{b['brief_id']}-T{i}", "brief_id": b["brief_id"], "trade_index": i,
            "judged_at": b["judged_at"], "info_cutoff_at": b["info_cutoff_at"], "symbol": p.get("symbol"), "side": p.get("side"),
            "horizon_bars": p.get("horizon_bars"), "catalyst": t.get("catalyst"), "judge_prior": t.get("judge_prior"),
            "tp_p_hit": (p.get("tp") or {}).get("p_hit"), "expected_r_net": p.get("expected_r_net"), "kind": res["kind"], **nums,
            "bars_held": res.get("bars_held"), "close_reason": res.get("close_reason"), "computed_at": do._iso(now),
            "provenance": "computed", "net_of_full_cost_stack": res["kind"] == "replayed",
            "cost_policy": policy if res["kind"] == "replayed" else None, "reason": res.get("reason"),
            "handoff": handoff if handoff is not None else {"read_state": "not_applicable", "items": []},
            "forecast_ids": t.get("forecast_ids") or [],
            # the operator's edge question (2026-11-26): did a trade resting on an own-vs-consensus GAP pay, net of cost
            "gap_trade": any((fc or {}).get("consensus_read_state") == "measured"
                             for fc in (_fmap(b).get(x) for x in (t.get("forecast_ids") or [])))}


def run(briefs: Path, outcomes: Path, candles: Callable[[str, str], list | None], now: datetime | None = None) -> dict:
    if not briefs.is_dir():
        return {"state": "could_not_look", "reason": f"{briefs} missing"}
    now = now or datetime.now(timezone.utc)
    done, new, waiting, cache = _done(outcomes), [], [], {}
    for b in _briefs(briefs):
        cutoff = _ts(b["info_cutoff_at"])
        for i, t in enumerate(b.get("trades") or []):
            oid = f"{b['brief_id']}-T{i}"
            if oid in done:
                continue
            p = t.get("proposal") or {}
            if p.get("timeframe") != "1d":
                new.append(row(b, i, t, {"kind": "not_computable", "reason": f"timeframe {p.get('timeframe')!r} is not 1d"}, now, None))
                continue
            span = timedelta(seconds=DAY * (int(p["entry"]["good_till_bars"]) + int(p["horizon_bars"])))
            if now < cutoff + timedelta(seconds=DAY):
                waiting.append(oid)
                continue
            sym = p["symbol"]
            if sym not in cache:
                cache[sym] = candles(sym, "1d")
            bars = cache[sym]
            res = None
            if bars:
                closed = [x for x in bars if x["time"] + DAY <= now.timestamp()]
                res = do.replay(p, cutoff, closed, do._cost_fn(sym))
            if res is None:
                if now > cutoff + span + timedelta(days=2):
                    why = "forward daily candles missing past the horizon + 2 days" if bars else "daily candles unreadable past the horizon + 2 days"
                    res = {"kind": "not_computable", "reason": why}
                else:
                    waiting.append(oid)
                    continue
            policy = ("execution_costs.roundtrip_cost_r with desk_scan_packet.cost_policy(%s): fee %.2f + slippage %.2f bps rt, funding %.2f bps/window"
                      % ((sym,) + tuple(dsp.cost_policy(sym))))
            closed_all = [x for x in (bars or []) if x["time"] + DAY <= now.timestamp()]
            new.append(row(b, i, t, res, now, policy, handoff_checks(t, cutoff, closed_all)))
    if new:
        text = outcomes.read_text() if outcomes.exists() else ""
        sep = "" if (not text or text.endswith("\n")) else "\n"
        outcomes.parent.mkdir(parents=True, exist_ok=True)
        outcomes.write_text(text + sep + "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in new))
    return {"state": "ok", "written": len(new), "outcome_ids": [r["outcome_id"] for r in new], "waiting": waiting}


FC_SCHEMA = "desk_macro_forecast_outcome/1"
FC_OUT = BRIEFS / "forecast_outcomes.jsonl"


def _fred_value(series: str, how: str, period: str, fred: Callable[[str], list]) -> float | None:
    import desk_macro_analysis as dma
    ser = dict(dma.transform(fred(series), how))
    return ser.get(period)


def grade_forecasts(briefs: Path, out: Path, fred: Callable[[str], list], candles: Callable[[str, str], list | None],
                    now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    done = _done(out)
    rows, waiting = [], []
    for b in _briefs(briefs):
        for f in b.get("forecasts") or []:
            oid = f"{b['brief_id']}-{f.get('forecast_id')}"
            if oid in done:
                continue
            tg = f.get("target") or {}
            try:
                res_at = _ts(tg["resolves_at"])
            except (KeyError, ValueError):
                continue
            if now < res_at + timedelta(days=1):
                waiting.append(oid)
                continue
            base = {"schema": FC_SCHEMA, "outcome_id": oid, "brief_id": b["brief_id"], "forecast_id": f.get("forecast_id"),
                    "target": tg, "own_point": f.get("own_point"), "interval": f.get("interval"), "consensus": f.get("consensus"),
                    "computed_at": do._iso(now)}
            kind, realised, naive = tg.get("kind"), None, None
            try:
                if kind == "release" and tg.get("series") and tg.get("period"):
                    realised = _fred_value(tg["series"], tg.get("transform", "level"), tg["period"], fred)
                    naive = tg.get("naive_point")
                elif kind == "asset_return" and tg.get("base_close"):
                    bars = [x for x in (candles(tg["key"], "1d") or []) if x["time"] >= res_at.timestamp() - DAY]
                    if bars:
                        realised = (float(bars[0]["close"]) / float(tg["base_close"]) - 1) * 100
                        naive = 0.0
                elif kind == "asset_p_tp":
                    rows.append({**base, "kind": "graded_via_trade_outcome", "reason": "scored as judge_prior Brier on the trade rows"})
                    continue
                else:
                    rows.append({**base, "kind": "not_computable", "reason": "target names no gradable series/period or base_close"})
                    continue
            except Exception as exc:  # noqa: BLE001  # allow-silent: an unreadable source is retried, then not_computable
                if now > res_at + timedelta(days=7):
                    rows.append({**base, "kind": "not_computable", "reason": f"{type(exc).__name__}: {exc}"[:200]})
                else:
                    waiting.append(oid)
                continue
            if realised is None:
                if now > res_at + timedelta(days=7):
                    rows.append({**base, "kind": "not_computable", "reason": "realised value not published 7 days after resolution"})
                else:
                    waiting.append(oid)
                continue
            own = float(f["own_point"])
            iv = f.get("interval") or {}
            e_own = abs(realised - own)
            e_naive = abs(realised - float(naive)) if naive is not None else None
            e_cons = abs(realised - float(f["consensus"])) if f.get("consensus") is not None else None
            rows.append({**base, "kind": "graded", "realised": round(realised, 6), "abs_err_own": round(e_own, 6),
                         "abs_err_naive": round(e_naive, 6) if e_naive is not None else None,
                         "abs_err_consensus": round(e_cons, 6) if e_cons is not None else None,
                         "inside_interval": (iv.get("lo") is not None and float(iv["lo"]) <= realised <= float(iv["hi"])),
                         "own_beats_naive": (e_own < e_naive) if e_naive is not None else None,
                         "own_beats_consensus": (e_own < e_cons) if e_cons is not None else None})
    if rows:
        text = out.read_text() if out.exists() else ""
        sep = "" if (not text or text.endswith("\n")) else "\n"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + sep + "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    return {"state": "ok", "written": len(rows), "waiting": waiting}


def forecast_summary(out: Path) -> dict:
    rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()] if out.exists() else []
    g = [r for r in rows if r["kind"] == "graded"]

    def rate(k):
        xs = [r[k] for r in g if r.get(k) is not None]
        return {"n": len(xs), "rate": round(sum(1 for x in xs if x) / len(xs), 4) if xs else None}
    by_class = {}
    for r in g:
        cls = f"{(r.get('target') or {}).get('kind')}:{(r.get('target') or {}).get('series') or (r.get('target') or {}).get('key')}"
        c = by_class.setdefault(cls, {"n": 0, "own_beats_consensus": [], "own_beats_naive": []})
        c["n"] += 1
        for k in ("own_beats_consensus", "own_beats_naive"):
            if r.get(k) is not None:
                c[k].append(bool(r[k]))
    for c in by_class.values():
        for k in ("own_beats_consensus", "own_beats_naive"):
            xs = c[k]
            c[k] = {"n": len(xs), "rate": round(sum(xs) / len(xs), 4) if xs else None}
    return {"read_state": "measured" if out.exists() else "no_forecast_outcomes_file", "n_rows": len(rows), "n_graded": len(g),
            "own_beats_naive": rate("own_beats_naive"), "own_beats_consensus": rate("own_beats_consensus"),
            "interval_coverage": rate("inside_interval"), "by_class": by_class}


def summary(outcomes: Path) -> dict:
    """Population = replayed rows only (expired / not_computable are counted, never scored as 0 R)."""
    rows = [json.loads(x) for x in outcomes.read_text().splitlines() if x.strip()] if outcomes.exists() else []
    rep = [r for r in rows if r["kind"] == "replayed"]
    kinds = {k: sum(1 for r in rows if r["kind"] == k) for k in sorted({r["kind"] for r in rows})}
    if not rep:
        return {"read_state": "measured" if outcomes.exists() else "no_outcomes_file", "n_rows": len(rows), "kinds": kinds, "n_replayed": 0,
                "hit_rate": None, "mean_net_r": None, "brier_judge_prior": None, "brier_tp_p_hit": None}
    hit = [1.0 if r["close_reason"] == "tp_hit" else 0.0 for r in rep]

    def brier(key: str):
        xs = [(float(r[key]), h) for r, h in zip(rep, hit) if r.get(key) is not None]
        return round(sum((p - h) ** 2 for p, h in xs) / len(xs), 4) if xs else None
    gap = [r for r in rep if r.get("gap_trade")]
    gap_stat = {"n": len(gap), "mean_net_r": round(sum(r["net_r"] for r in gap) / len(gap), 4) if gap else None,
                "population": "replayed trades citing a forecast with a measured consensus (the own-vs-consensus gap)"}
    return {"read_state": "measured", "n_rows": len(rows), "kinds": kinds, "n_replayed": len(rep), "gap_trades": gap_stat,
            "hit_rate": round(sum(hit) / len(hit), 4),
            "mean_net_r": round(sum(r["net_r"] for r in rep) / len(rep), 4), "brier_judge_prior": brier("judge_prior"), "brier_tp_p_hit": brier("tp_p_hit")}


def _self_test() -> int:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + name)
    t0 = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    day0 = int(datetime(2026, 11, 3, tzinfo=timezone.utc).timestamp())          # first daily bar opening after the cutoff
    bars = [{"time": day0 + k * DAY, "open": 100.0 + k, "high": 101.5 + k, "low": 99.5 + k, "close": 100.5 + k} for k in range(10)]
    early = [{"time": day0 - DAY, "open": 50.0, "high": 500.0, "low": 1.0, "close": 50.0}]  # a pre-cutoff bar that would hit everything
    prop = {"symbol": "BTCUSDT", "side": "long", "timeframe": "1d", "horizon_bars": 5, "entry": {"type": "market", "level": 100.0, "good_till_bars": 1},
            "stop": {"level": 97.0, "basis": "S1"}, "tp": {"level": 103.0, "basis": "S1", "p_hit": 0.4}, "expected_r_net": 0.2}
    mgmt = {"watch_for": [{"signal": "close above 102", "check": {"kind": "close_above", "level": 102.0}}, {"signal": "Fed speakers"}],
            "tighten_if": [], "exit_early_if": [{"signal": "low under 90", "check": {"kind": "low_below", "level": 90.0}}]}
    brief = {"schema": "desk_macro_brief/1", "brief_id": "DMB-20261102T1300Z", "judged_at": "2026-11-02T13:00:00Z", "info_cutoff_at": "2026-11-02T13:00:00Z",
             "trades": [{"proposal": prop, "judge_prior": 0.5, "catalyst": "regime", "management": mgmt},
                        {"proposal": dict(prop, symbol="ETHUSDT"), "judge_prior": 0.3, "catalyst": "regime"}]}
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "2026-11-02.json").write_text(json.dumps(brief))
        out = d / "outcomes.jsonl"
        feed = {"BTCUSDT": early + bars, "ETHUSDT": None}
        r0 = run(d, out, lambda s, tf: feed[s], now=t0 + timedelta(hours=5))
        check("nothing is graded before one daily bar has closed after the cutoff", r0["written"] == 0 and len(r0["waiting"]) == 2)
        r1 = run(d, out, lambda s, tf: feed[s], now=t0 + timedelta(days=5))
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        btc = next(x for x in rows if x["symbol"] == "BTCUSDT")
        check("the trade replays on post-cutoff daily bars only (market fill at the first forward open, TP at 103)",
              r1["written"] == 1 and btc["kind"] == "replayed" and btc["close_reason"] == "tp_hit" and btc["net_of_full_cost_stack"])
        check("net R is the planned 1 R target minus a positive cost", 0.9 < btc["net_r"] < 1.0)
        h = {(x["group"], x["index"]): x for x in btc["handoff"]["items"]}
        check("handoff: a machine check that occurred fires on its first bar (close 102.5 on bar 2)",
              h[("watch_for", 0)]["fired"] is True and h[("watch_for", 0)]["fired_bar"] == 2)
        check("handoff: a check that never occurred is fired=false, not missing", h[("exit_early_if", 0)]["fired"] is False)
        check("handoff: free text is logged not_machine_checkable", h[("watch_for", 1)]["state"] == "not_machine_checkable"
              and btc["handoff"]["n_fired"] == 1 and btc["handoff"]["n_evaluated"] == 2)
        check("handoff: the pre-cutoff bar never counts (its low of 1.0 would fire low_below 90)", not h[("exit_early_if", 0)]["fired"])
        check("unreadable candles inside horizon + 2 days are retried, never written", "DMB-20261102T1300Z-T1" in r1["waiting"])
        r2 = run(d, out, lambda s, tf: feed[s], now=t0 + timedelta(days=6))
        check("a re-run writes nothing new (one row per brief x trade)", r2["written"] == 0)
        r3 = run(d, out, lambda s, tf: feed[s], now=t0 + timedelta(days=20))
        eth = [json.loads(x) for x in out.read_text().splitlines()][-1]
        check("still unreadable past horizon + 2 days -> one not_computable row naming why",
              r3["written"] == 1 and eth["kind"] == "not_computable" and "unreadable" in eth["reason"] and eth["net_r"] is None)
        s = summary(out)
        check("summary scores replayed rows only and counts the rest", s["n_replayed"] == 1 and s["kinds"]["not_computable"] == 1
              and s["hit_rate"] == 1.0 and s["brier_judge_prior"] == 0.25)
        fb = {"schema": "desk_macro_brief/1", "brief_id": "DMB-20261102T1301Z", "judged_at": "2026-11-02T13:01:00Z",
              "info_cutoff_at": "2026-11-02T13:00:00Z", "trades": [], "forecasts": [
                  {"forecast_id": "F1", "own_point": 50.0, "interval": {"lo": 20.0, "hi": 80.0, "level": 0.8}, "consensus": 90.0,
                   "target": {"kind": "release", "key": "nfp", "resolves_at": "2026-11-06T13:30:00Z", "series": "PAYEMS",
                              "transform": "diff", "period": "2026-10-01", "naive_point": 120.0}},
                  {"forecast_id": "F2", "own_point": 0.4, "interval": {"lo": 0.3, "hi": 0.5, "level": 0.8}, "consensus": None,
                   "target": {"kind": "asset_p_tp", "key": "BTCUSDT", "resolves_at": "2026-11-06T00:00:00Z"}}]}
        (d / "2026-11-02b.json").write_text(json.dumps(fb))
        fco = d / "fc.jsonl"
        payems = [("2026-09-01", 1000.0), ("2026-10-01", 1060.0)]
        g0 = grade_forecasts(d, fco, lambda sid: payems, lambda s, tf: None, now=t0 + timedelta(days=2))
        check("forecasts wait until their target resolves", g0["written"] == 0 and len(g0["waiting"]) == 2)
        g1 = grade_forecasts(d, fco, lambda sid: payems, lambda s, tf: None, now=t0 + timedelta(days=6))
        fr = {r["forecast_id"]: r for r in (json.loads(x) for x in fco.read_text().splitlines())}
        check("release forecast graded vs realised, naive and consensus (realised 60: own 50 beats naive 120 and consensus 90)",
              fr["F1"]["realised"] == 60.0 and fr["F1"]["own_beats_naive"] and fr["F1"]["own_beats_consensus"] and fr["F1"]["inside_interval"])
        check("a p_tp forecast is routed to the trade Brier, not double-scored", fr["F2"]["kind"] == "graded_via_trade_outcome")
        fs = forecast_summary(fco)
        check("forecast summary counts beats-naive / beats-consensus / coverage", fs["own_beats_naive"] == {"n": 1, "rate": 1.0}
              and g1["written"] == 2)
        check("missing briefs directory is could-not-look, not zero", run(d / "nope", out, lambda s, tf: None)["state"] == "could_not_look")
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--briefs", type=Path, default=BRIEFS)
    ap.add_argument("--outcomes", type=Path, default=OUTCOMES)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.summary:
        print(json.dumps({"trades": summary(a.outcomes), "forecasts": forecast_summary(a.outcomes.parent / FC_OUT.name)}, indent=2))
        return 0
    import desk_macro_analysis as dma
    res = run(a.briefs, a.outcomes, lambda s, tf: dsp.candles_from_api([s], tf).get(s))
    res["forecasts"] = grade_forecasts(a.briefs, a.outcomes.parent / FC_OUT.name, dma.fred_series,
                                       lambda s, tf: dsp.candles_from_api([s], tf).get(s))
    print(json.dumps(res, indent=2))
    return 0 if res["state"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
