#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-02 (DEMO-FLOOR regime-level unit) dispatches it as its last command
"""Is the demo-floor record-year loss COMMON across the crypto pullback/trend legs, and does a trend-regime
cell separate it?

Row DEMO-FLOOR-ITER-20261113, manager ruling 2026-11-14 05:10Z, after RQ-20261114-db1a-01 found the round-3
lever failures were the WINDOW, not the decision bar. This grader reads ONE ``exit_lever_ablation`` run per
leg per window (``<out>/rec_<leg>``, ``<out>/pre_<leg>``, arm ``A`` = the leg config-exact on its LIVE
decision bar, full cost stack) and applies the unit's registered rule.

PART A -- COMMON LOSS (its own record):
  common   >= 12 legs graded on both windows, AND >= 2/3 of graded legs have net_r < 0 on the record window,
           AND the pooled record-window net_r < 0.
  descriptive: per-leg record vs prior net_r; pooled monthly record-window net_r; mean pairwise correlation
           of the legs' monthly net_r.

PART B -- REGIME SEPARATION (the unit's verdict), 1-D trend cell, pooled across legs:
  tag      every trade with the ADX regime of its entry bar (regime_matrix: chop < 20, transitional 20-25,
           trending >= 25) on the leg's OWN feed (regime_debt_matrix.resolve_feed / _fetch_csv, resampled to
           the leg's timeframe) -- the same tagging regime_tag_emitted applies.
  select   on the RECORD window only: the (regime, direction) cell with the most negative pooled net_r among
           cells with n >= 30.
  passes   (1) its pooled record net_r < 0; (2) on the PRIOR window (not read by the selection) the same cell
           has n >= 10 and pooled net_r < 0; (3) over both windows pooled, regime_cell_walkforward.cell_verdict
           on the fixed FOLD_PANEL reads ``<direction>_verdict == stable_drag`` (pooled < 0, strict majority of
           folds negative under every panel member, >= MIN_DIRECTION_TRADES).
  verdict  pass iff the selected cell passes; fail iff a cell was selected and fails; indeterminate iff
           fewer than 12 legs are graded, no cell reaches n >= 30, or a feed could not be fetched for a leg
           that has trades.

A PASS is a POINTER, not a Tier-3 packet (regime-selectivity Rules 2 and 3): the router gates on 2-D
(trend, vol) cells keyed on the per-symbol advisory vol head, so a pass makes the 2-D walk-forward with
trainer-side ``ml_vol_label_replay`` labels the next unit. Edits no config, roster or record; places no order.
Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "research"), str(ROOT / "scripts"), str(ROOT)]

UNIT = "RQ-20261114-db1a-02"
RULE = "RULE-DFR-COMMON-LOSS-REGIME-20261114"
REGIMES = ("trending", "transitional", "chop")
DIRS = ("long", "short")
MIN_LEGS = 12
MIN_CELL_N_RECORD = 30
MIN_CELL_N_PRIOR = 10


def _dir(t: Dict[str, Any]) -> str:
    return "long" if str(t.get("direction") or t.get("side") or "").lower().startswith("l") else "short"


def read_run(run_dir: Path, arm: str = "A") -> Optional[Dict[str, Any]]:
    p = run_dir / "verdict.json"
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
    a = (((v.get("measurement") or {}).get("arms")) or {}).get(arm)
    if not isinstance(a, dict) or not isinstance(a.get("n"), int):
        return None
    tp = run_dir / "arms" / f"{arm}__trades.jsonl"
    trades: List[Dict[str, Any]] = []
    if tp.exists():
        for line in tp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except ValueError:
                    continue
    return {"n": a["n"], "net_r": a.get("net_r"), "trades": trades}


def part_a(legs: Dict[str, Dict[str, Optional[Dict[str, Any]]]]) -> Dict[str, Any]:
    graded = {k: v for k, v in legs.items() if v.get("rec") and v.get("pre")}
    rows = {k: {"record_net_r": v["rec"]["net_r"], "record_n": v["rec"]["n"], "prior_net_r": v["pre"]["net_r"],
                "prior_n": v["pre"]["n"]} for k, v in graded.items()}
    neg = [k for k, r in rows.items() if r["record_net_r"] < 0]
    pooled = round(sum(r["record_net_r"] for r in rows.values()), 4)
    pooled_prior = round(sum(r["prior_net_r"] for r in rows.values()), 4)
    need = math.ceil(2 * len(graded) / 3) if graded else None
    common = bool(len(graded) >= MIN_LEGS and len(neg) >= (need or 0) and pooled < 0)
    months: Dict[str, Dict[str, float]] = {}
    for k, v in graded.items():
        for t in v["rec"]["trades"]:
            m = str(t.get("entry_time"))[:7]
            months.setdefault(k, {})
            months[k][m] = months[k].get(m, 0.0) + float(t.get("net_r") or 0.0)
    all_m = sorted({m for d in months.values() for m in d})
    pooled_monthly = {m: round(sum(d.get(m, 0.0) for d in months.values()), 4) for m in all_m}
    corr = _mean_pairwise_corr([[months.get(k, {}).get(m, 0.0) for m in all_m] for k in sorted(months)])
    return {"graded_legs": len(graded), "legs_negative_record": len(neg), "needed_negative": need,
            "pooled_record_net_r": pooled, "pooled_prior_net_r": pooled_prior, "common": common,
            "legs_record_below_prior": sum(1 for r in rows.values() if r["record_net_r"] < r["prior_net_r"]),
            "per_leg": rows, "pooled_monthly_record_net_r": pooled_monthly,
            "months_negative": sum(1 for x in pooled_monthly.values() if x < 0), "months": len(pooled_monthly),
            "mean_pairwise_monthly_corr": corr}


def _mean_pairwise_corr(series: List[List[float]]) -> Optional[float]:
    import statistics as st
    cs = []
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            a, b = series[i], series[j]
            if len(a) < 3 or st.pstdev(a) == 0 or st.pstdev(b) == 0:
                continue
            ma, mb = st.mean(a), st.mean(b)
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
            cs.append(cov / (st.pstdev(a) * st.pstdev(b)))
    return round(sum(cs) / len(cs), 4) if cs else None


def tag(trades: List[Dict[str, Any]], bars_csv: str, resample: str) -> List[Dict[str, Any]]:
    """The ADX regime of each trade's entry bar, exactly as regime_tag_emitted tags it."""
    from candle_io import load_candles, resample_ohlcv
    from regime_matrix import _adx
    import regime_tag_emitted as rte
    df = load_candles(bars_csv)
    if resample:
        df = resample_ohlcv(df, resample)
    return rte.annotate_trades_with_regime(trades, _adx(df, 14), df)


def cell_table(tagged: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for reg in REGIMES:
        for d in DIRS:
            ts = [t for t in tagged if t.get("regime") == reg and _dir(t) == d]
            out[f"{reg}/{d}"] = {"n": len(ts), "net_r": round(sum(float(t.get("net_r") or 0) for t in ts), 4)}
    return out


def walkforward(cell_trades: List[Dict[str, Any]], regime: str) -> Dict[str, Any]:
    import direction_walkforward as dwf
    import regime_cell_walkforward as rcw
    with tempfile.TemporaryDirectory(prefix="dfr_wf_") as td:
        p = Path(td) / "cell.jsonl"
        p.write_text("".join(json.dumps(t, default=str) + "\n" for t in cell_trades), encoding="utf-8")
        panel = {k: dwf.analyze([str(p)], k, regime) for k in rcw.FOLD_PANEL}
    return rcw.cell_verdict(panel, regime)


def part_b(tagged_rec: List[Dict[str, Any]], tagged_pre: List[Dict[str, Any]],
           wf=walkforward) -> Dict[str, Any]:
    rec, pre = cell_table(tagged_rec), cell_table(tagged_pre)
    eligible = {c: r for c, r in rec.items() if r["n"] >= MIN_CELL_N_RECORD}
    base = {"record_cells": rec, "prior_cells": pre, "min_cell_n_record": MIN_CELL_N_RECORD,
            "min_cell_n_prior": MIN_CELL_N_PRIOR}
    if not eligible:
        return dict(base, verdict="indeterminate", note=f"no (regime, direction) cell reaches n >= {MIN_CELL_N_RECORD} on the record window")
    cell = min(eligible, key=lambda c: eligible[c]["net_r"])
    reg, d = cell.split("/")
    c1 = rec[cell]["net_r"] < 0
    c2 = pre[cell]["n"] >= MIN_CELL_N_PRIOR and pre[cell]["net_r"] < 0
    both = [t for t in tagged_rec + tagged_pre if t.get("regime") == reg and _dir(t) == d]
    v = wf(both, reg) if both else {}
    c3 = v.get(f"{d}_verdict") == "stable_drag"
    ok = bool(c1 and c2 and c3)
    return dict(base, selected_cell=cell, record_net_r_negative=c1, prior_holds=c2, walkforward=v,
                walkforward_stable_drag=c3, verdict="pass" if ok else "fail",
                note=(f"{cell}: record {rec[cell]['net_r']} n{rec[cell]['n']}; prior {pre[cell]['net_r']} n{pre[cell]['n']}; "
                      f"walk-forward {v.get(f'{d}_verdict')}"))


def ex_cell(legs_tagged: Dict[str, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]], cell: str) -> Dict[str, Any]:
    reg, d = cell.split("/")
    out = {}
    for leg, (r, p) in legs_tagged.items():
        keep_r = [t for t in r if not (t.get("regime") == reg and _dir(t) == d)]
        keep_p = [t for t in p if not (t.get("regime") == reg and _dir(t) == d)]
        out[leg] = {"record_ex_cell_net_r": round(sum(float(t.get("net_r") or 0) for t in keep_r), 4), "record_ex_cell_n": len(keep_r),
                    "prior_ex_cell_net_r": round(sum(float(t.get("net_r") or 0) for t in keep_p), 4), "prior_ex_cell_n": len(keep_p)}
    return out


def _bars_for(leg: str, cfg: Dict[str, Any], days: int, cache: Dict[Tuple[str, str], str], td: str) -> Tuple[Optional[str], str]:
    import regime_debt_matrix as rdm
    sym, tf = str(cfg["symbols"][0]), str(cfg["timeframe"])
    feed = rdm.resolve_feed(sym, tf)
    key = (feed["ticker"], feed["interval"])
    if key not in cache:
        p = str(Path(td) / f"{feed['ticker']}_{feed['interval']}.csv")
        try:
            rdm._fetch_csv(feed, days, p)
        except Exception as exc:  # noqa: BLE001 -- a fetch failure is recorded per leg, never silently skipped  # allow-silent: reported as indeterminate
            print(f"[bars] {leg}: fetch failed {type(exc).__name__}: {exc}", file=sys.stderr)
            return None, feed["resample"]
        cache[key] = p
    return cache[key], feed["resample"]


def grade(out: Path, legs: List[str], days: int, bars_override: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())
    cfg = cfg.get("strategies", cfg)
    runs = {leg: {"rec": read_run(out / f"rec_{leg}"), "pre": read_run(out / f"pre_{leg}")} for leg in legs}
    a = part_a(runs)
    records = [{"leg": "PART_A:common_loss", "verdict": "pass" if a["common"] else "fail",
                "read_state": "measured" if a["graded_legs"] >= MIN_LEGS else "producer_failed",
                "n": sum(r["record_n"] for r in a["per_leg"].values()) if a["graded_legs"] else None,
                "population": f"{a['graded_legs']} crypto demo-floor pullback/trend legs, record window, live decision bar, full cost stack",
                "note": f"{a['legs_negative_record']}/{a['graded_legs']} legs negative on the record window (need {a['needed_negative']}); pooled {a['pooled_record_net_r']}R"}]
    legs_tagged: Dict[str, Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]] = {}
    fetch_fail = []
    with tempfile.TemporaryDirectory(prefix="dfr_bars_") as td:
        cache: Dict[Tuple[str, str], str] = {}
        for leg, v in runs.items():
            if not (v["rec"] and v["pre"]):
                continue
            if bars_override and leg in bars_override:
                csv, rs = bars_override[leg], ""
            else:
                csv, rs = _bars_for(leg, cfg[leg], days, cache, td)
            if csv is None:
                if v["rec"]["trades"] or v["pre"]["trades"]:
                    fetch_fail.append(leg)
                continue
            legs_tagged[leg] = (tag(v["rec"]["trades"], csv, rs), tag(v["pre"]["trades"], csv, rs))
    tr = [t for r, _ in legs_tagged.values() for t in r]
    tp = [t for _, p in legs_tagged.values() for t in p]
    b = part_b(tr, tp)
    if a["graded_legs"] < MIN_LEGS or fetch_fail:
        b = dict(b, verdict="indeterminate", note=(f"graded legs {a['graded_legs']} < {MIN_LEGS}" if a["graded_legs"] < MIN_LEGS
                                                   else f"bars could not be fetched for {fetch_fail}"))
    if b.get("selected_cell"):
        b["ex_cell_per_leg"] = ex_cell(legs_tagged, b["selected_cell"])
    records.append({"leg": f"PART_B:{b.get('selected_cell') or 'no_cell'}", "verdict": b["verdict"],
                    "read_state": "measured" if b["verdict"] != "indeterminate" else "producer_failed",
                    "n": (len(tr) + len(tp)) if b["verdict"] != "indeterminate" else None,
                    "population": f"trades of {len(legs_tagged)} legs, record + prior windows, 1-D ADX trend cell x direction",
                    "note": b.get("note")})
    return {"verdict": b["verdict"], "read_state": "measured" if b["verdict"] != "indeterminate" else "producer_failed",
            "n": (len(tr) + len(tp)) if b["verdict"] != "indeterminate" else None, "research_unit": UNIT, "rule": RULE,
            "population": (f"{len(legs)} crypto demo-floor pullback/trend legs (testing, bybit_1), each config-exact on its live "
                           "decision bar; record 2025-11-13..2026-11-12 and prior 2024-11-13..2025-11-12; full cost stack"),
            "part_a": a, "part_b": b, "records": records,
            "pointer_only": "a PASS points at a 2-D (trend, vol) walk-forward with trainer vol labels; it is not a Tier-3 packet"}


def _self_test() -> int:
    def tr(t, d, r, reg):
        return {"entry_time": t, "direction": d, "net_r": r, "regime": reg}
    legs = {f"l{i}": {"rec": {"n": 10, "net_r": -2.0 if i < 10 else 1.0,
                              "trades": [tr(f"2026-0{1 + i % 9}-01 00:00:00+00:00", "long", -0.2, "chop")] * 2},
                      "pre": {"n": 10, "net_r": 1.0, "trades": []}} for i in range(13)}
    a = part_a(legs)
    assert a["graded_legs"] == 13 and a["legs_negative_record"] == 10 and a["needed_negative"] == 9 and a["common"], a
    legs2 = dict(legs, **{f"l{i}": dict(legs[f"l{i}"], rec=dict(legs[f"l{i}"]["rec"], net_r=1.0)) for i in range(5)})
    assert not part_a(legs2)["common"]
    assert not part_a({k: legs[k] for k in list(legs)[:11]})["common"]
    # Part B: a chop/long cell losing on both windows with a stable walk-forward passes
    rec = [tr(f"2026-{1 + i % 12:02d}-{1 + i % 27:02d} 00:00:00+00:00", "long", -0.3, "chop") for i in range(40)]
    rec += [tr(f"2026-{1 + i % 12:02d}-{1 + i % 27:02d} 01:00:00+00:00", "short", 0.2, "trending") for i in range(40)]
    pre = [tr(f"2025-{1 + i % 12:02d}-{1 + i % 27:02d} 00:00:00+00:00", "long", -0.1, "chop") for i in range(15)]
    stub = lambda trades, reg: {"long_verdict": "stable_drag", "short_verdict": "no_trades"}  # noqa: E731
    b = part_b(rec, pre, wf=stub)
    assert b["selected_cell"] == "chop/long" and b["verdict"] == "pass", b
    pre_pos = [dict(t, net_r=0.2) for t in pre]
    assert part_b(rec, pre_pos, wf=stub)["verdict"] == "fail"
    stub_no = lambda trades, reg: {"long_verdict": "no_stable_drag"}  # noqa: E731
    assert part_b(rec, pre, wf=stub_no)["verdict"] == "fail"
    assert part_b(rec[:20], pre, wf=stub)["verdict"] == "indeterminate"
    # the real walk-forward on the synthetic cell (pooled < 0, every fold negative) reads stable_drag
    v = walkforward([t for t in rec + pre if t["regime"] == "chop"], "chop")
    assert v["long_verdict"] == "stable_drag", v
    ex = ex_cell({"l": (rec, pre)}, "chop/long")
    assert ex["l"]["record_ex_cell_n"] == 40 and ex["l"]["prior_ex_cell_n"] == 0
    assert _mean_pairwise_corr([[1, 2, 3], [2, 4, 6]]) == 1.0
    print("regime_common_loss_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out")
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--days", type=int, default=800, help="feed fetch depth for the regime tagging bars")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not a.leg:
        ap.error("--out and at least one --leg are required")
    out = Path(a.out)
    v = grade(out, a.leg, a.days)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    pa, pb = v["part_a"], v["part_b"]
    print(f"PART A common={pa['common']} ({pa['legs_negative_record']}/{pa['graded_legs']} negative; pooled {pa['pooled_record_net_r']}R, prior {pa['pooled_prior_net_r']}R; corr {pa['mean_pairwise_monthly_corr']})")
    print(f"PART B {pb['verdict']}: {pb.get('note')}")
    print(f"unit: {v['verdict']} (n {v['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
