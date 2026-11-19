#!/usr/bin/env python3
"""Donchian min_confidence re-test: is the CURRENT 0.70 depth gate still better than 0.60 on the window
AFTER it was chosen?  (operator decision D5, 2026-11-18; unit RQ-20261118-04a5-01)

PR #6322 (M21 E-2 round 1, merged 2026-07-13) moved trend_donchian (BTC 1h) min_confidence 0.6 -> 0.7 on
an IS/OOS + yearly walk-forward pass whose windows all END before 2026-07-14.  trend_donchian_avax_4h also
sits at 0.70 (origin not traced).  This producer replays each named leg CONFIG-EXACT through the same
harness, resolvers and TP cap the M21 sweep used (imported from m20_fleet_exit_sweep, nothing re-derived),
twice per window: at the leg's configured min_confidence (the incumbent) and at incumbent - 0.10.

Decision window = the FRESH window (--split onward, default 2026-07-14): data the 07-13 decision never saw.
The pre-split IS window and the six yearly folds are reported as CONTEXT and decide nothing.

Registered rule (RULE-RQ20261118-04a5-01-DONCHIAN-DEPTH-RETEST), per leg, on the fresh window:
  INDETERMINATE  if either arm has < MIN_TRADES trades, or the arms differ by < MIN_DIFF trades (the lever
                 is inert on this window), or one arm wins net R and the other wins max drawdown;
  FAIL           (the incumbent loses; revert to the lower threshold) iff the lower arm has net_total_r
                 STRICTLY greater AND max_drawdown_r no greater than the incumbent;
  PASS           (keep the incumbent) iff the incumbent has net_total_r >= the lower arm's AND
                 max_drawdown_r no greater.
The unit verdict is per leg; the top-level verdict is FAIL if any leg FAILs, else PASS if every leg PASSes,
else INDETERMINATE.  This is the M21 gate's own two-metric criterion, applied symmetrically.

Tier-1 research tooling: reads config, writes only --json.  Places no order, edits no config.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))

RULE_ID = "RULE-RQ20261118-04a5-01-DONCHIAN-DEPTH-RETEST"
MIN_TRADES = 15
MIN_DIFF = 3
DELTA = -0.10


def grade_leg(inc: dict, low: dict) -> tuple[str, str]:
    """inc / low = harness summaries (total_trades, net_total_r, max_drawdown_r) on the fresh window."""
    for tag, r in (("incumbent", inc), ("lower", low)):
        if "error" in r:
            return "INDETERMINATE", f"{tag} arm harness error: {str(r['error'])[:120]}"
    ni, nl = int(inc.get("total_trades") or 0), int(low.get("total_trades") or 0)
    if min(ni, nl) < MIN_TRADES:
        return "INDETERMINATE", f"thin: incumbent n={ni}, lower n={nl} (< {MIN_TRADES})"
    if abs(nl - ni) < MIN_DIFF:
        return "INDETERMINATE", f"inert: arms differ by {abs(nl - ni)} trades (< {MIN_DIFF})"
    ri, rl = float(inc["net_total_r"]), float(low["net_total_r"])
    di, dl = float(inc["max_drawdown_r"]), float(low["max_drawdown_r"])
    if rl > ri and dl <= di:
        return "FAIL", f"lower beats incumbent: net R {rl:+.2f} vs {ri:+.2f}, maxDD {dl:.2f} vs {di:.2f}"
    if ri >= rl and di <= dl:
        return "PASS", f"incumbent holds: net R {ri:+.2f} vs {rl:+.2f}, maxDD {di:.2f} vs {dl:.2f}"
    return "INDETERMINATE", f"mixed: net R inc {ri:+.2f} / low {rl:+.2f}, maxDD inc {di:.2f} / low {dl:.2f}"


def _last_bar(path) -> str | None:
    """First field of the file's last non-empty line: how far the fresh window really reaches (None if unreadable)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 4096))
            lines = [x for x in fh.read().decode("utf-8", "replace").splitlines() if x.strip()]
        return lines[-1].split(",")[0] if lines else None
    except OSError:
        return None


def roll_up(per_leg: dict) -> str:
    vs = [v["verdict"] for v in per_leg.values()]
    if "FAIL" in vs:
        return "FAIL"
    if vs and all(v == "PASS" for v in vs):
        return "PASS"
    return "INDETERMINATE"


def verdict_row(per_leg: dict, unit: str, split: str, legs: list[str]) -> dict:
    top = roll_up(per_leg)
    measured = any("fresh" in v and "error" not in v["fresh"].get("incumbent", {}) for v in per_leg.values())
    n = sum(int(v.get("fresh", {}).get("incumbent", {}).get("total_trades") or 0) for v in per_leg.values())
    return {"schema_version": 1, "research_unit": unit, "rule_id": RULE_ID,
            "verdict": top.lower(),
            "read_state": "measured" if measured else (
                "no_data" if per_leg and all(v.get("read_state") == "no_data" for v in per_leg.values())
                else "producer_failed"),
            "note": f"{top}: " + "; ".join(f"{k} {v['verdict']} ({v['reason']})" for k, v in per_leg.items()),
            "population": f"config-exact harness replay of {', '.join(legs)}, fresh window {split}..latest bar, "
                          f"incumbent min_confidence vs incumbent{DELTA:+.2f}, TP cap 0.099",
            "n": n,
            "measurement": {"split": split, "delta": DELTA, "min_trades": MIN_TRADES, "min_diff": MIN_DIFF,
                            "per_leg": per_leg,
                            "generated_at": datetime.now(timezone.utc).isoformat()}}


def run(legs: list[str], data_dir: Path, split: str, tp_cap: float) -> dict:
    from m20_fleet_exit_sweep import FAMILY_HARNESS, FOLDS, base_args, classify, resolve_data, run_cell
    strategies = (yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()) or {}).get("strategies") or {}
    out: dict = {}
    for leg in legs:
        cfg = strategies.get(leg)
        if not isinstance(cfg, dict) or classify(leg) != "donchian":
            out[leg] = {"verdict": "INDETERMINATE", "reason": "not a donchian leg in strategies.yaml"}
            continue
        inc_conf = float(cfg.get("min_confidence") or 0.0)
        low_conf = round(inc_conf + DELTA, 2)
        sym = (cfg.get("symbols") or [None])[0]
        tf = str(cfg.get("timeframe") or "1h")
        data, proxy, resample = resolve_data(str(sym), tf, data_dir)
        if data is None:
            out[leg] = {"verdict": "INDETERMINATE", "reason": f"data_missing:{sym}"}
            continue
        last = _last_bar(data)
        if last and str(last)[:10] <= split:
            # PI-20261119-R3TMBVGF-0001: run 44383743409 read data ending 07-10 / 06-18 and reported "thin: n=0" --
            # a zero that meant "we could not look". A fresh window the data never reaches is could_not_look.
            out[leg] = {"verdict": "INDETERMINATE", "reason": f"could_not_look: data ends {last}, before split {split}",
                        "read_state": "no_data", "symbol": sym, "tf": tf, "data": str(data),
                        "data_last_bar": last}
            print(f"{leg}: INDETERMINATE - {out[leg]['reason']}", flush=True)
            continue
        harness = FAMILY_HARNESS["donchian"]
        base = base_args(leg, cfg, "donchian", data, resample, tp_cap)
        arm = {"incumbent": base + ["--min-confidence", str(inc_conf)],
               "lower": base + ["--min-confidence", str(low_conf)]}
        keep = ("total_trades", "net_total_r", "net_expectancy_r", "max_drawdown_r", "error")
        pick = lambda r: {k: r[k] for k in keep if k in r}  # noqa: E731
        fresh = {k: pick(run_cell(harness, a, start=split)) for k, a in arm.items()}
        is_ = {k: pick(run_cell(harness, a, end=split)) for k, a in arm.items()}
        folds = {f: {k: pick(run_cell(harness, a, start=s, end=e)) for k, a in arm.items()} for f, s, e in FOLDS}
        v, why = grade_leg(fresh["incumbent"], fresh["lower"])
        out[leg] = {"verdict": v, "reason": why, "symbol": sym, "tf": tf, "proxy": proxy,
                    "incumbent_min_confidence": inc_conf, "lower_min_confidence": low_conf,
                    "data": str(data), "data_last_bar": last,
                    "fresh": fresh, "context_is": is_, "context_folds": folds}
        print(f"{leg}: {v} - {why}", flush=True)
    return out


def _self_test() -> int:
    ok = True

    def check(msg, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    s = lambda n, r, d: {"total_trades": n, "net_total_r": r, "max_drawdown_r": d}  # noqa: E731
    check("FAIL when lower wins both", grade_leg(s(30, 5.0, 4.0), s(40, 7.0, 4.0))[0] == "FAIL")
    check("PASS when incumbent wins both", grade_leg(s(30, 7.0, 3.0), s(40, 5.0, 4.0))[0] == "PASS")
    check("PASS on a net-R tie with no worse DD", grade_leg(s(30, 5.0, 3.0), s(40, 5.0, 3.0))[0] == "PASS")
    check("INDETERMINATE when mixed", grade_leg(s(30, 7.0, 5.0), s(40, 5.0, 3.0))[0] == "INDETERMINATE")
    check("INDETERMINATE when thin", grade_leg(s(10, 1.0, 1.0), s(14, 9.0, 0.5))[0] == "INDETERMINATE")
    check("INDETERMINATE when inert", grade_leg(s(30, 5.0, 3.0), s(31, 9.0, 1.0))[0] == "INDETERMINATE")
    check("INDETERMINATE on harness error", grade_leg({"error": "x"}, s(31, 9.0, 1.0))[0] == "INDETERMINATE")
    check("roll-up: any FAIL is FAIL", roll_up({"a": {"verdict": "PASS"}, "b": {"verdict": "FAIL"}}) == "FAIL")
    check("roll-up: all PASS is PASS", roll_up({"a": {"verdict": "PASS"}, "b": {"verdict": "PASS"}}) == "PASS")
    check("roll-up: PASS + INDETERMINATE is INDETERMINATE",
          roll_up({"a": {"verdict": "PASS"}, "b": {"verdict": "INDETERMINATE"}}) == "INDETERMINATE")
    import script_run as SR
    pl = {"trend_donchian": {"verdict": "PASS", "reason": "x",
                             "fresh": {"incumbent": s(30, 7.0, 3.0), "lower": s(40, 5.0, 4.0)}}}
    row = verdict_row(pl, "U", "2026-07-14", ["trend_donchian"])
    check("verdict row: vocabularies match the harness", row["verdict"] in SR.VERDICTS and row["read_state"] in SR.READ_STATES)
    check("verdict row: population is a string and n present", isinstance(row["population"], str) and row["n"] == 30)
    bad = verdict_row({"x": {"verdict": "INDETERMINATE", "reason": "data_missing"}}, "U", "2026-07-14", ["x"])
    check("verdict row: nothing measured is producer_failed", bad["read_state"] == "producer_failed")
    cnl = verdict_row({"x": {"verdict": "INDETERMINATE", "reason": "could_not_look: data ends 2026-07-10",
                             "read_state": "no_data"}}, "U", "2026-07-14", ["x"])
    check("verdict row: data ending before the split is no_data (could not look), never a measured n=0",
          cnl["read_state"] == "no_data" and cnl["read_state"] in SR.READ_STATES)
    print("donchian_depth_retest self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--legs", default="trend_donchian,trend_donchian_avax_4h")
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    ap.add_argument("--split", default="2026-07-14")
    ap.add_argument("--tp-cap-pct", type=float, default=0.099)
    ap.add_argument("--unit", default="RQ-20261118-04a5-01")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    legs = [x for x in a.legs.split(",") if x]
    row = verdict_row(run(legs, Path(a.data_dir).expanduser(), a.split, a.tp_cap_pct), a.unit, a.split, legs)
    text = json.dumps(row, indent=1)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(text + "\n")
    print(row["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
