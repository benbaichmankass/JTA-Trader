#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-03 (DEMO-FLOOR direction-regime unit) dispatches it as its last command
"""Does ONE higher-timeframe trend filter on LONGS separate the common record-year loss of the crypto demo-floor
pullback/trend legs?

Row DEMO-FLOOR-ITER-20261113, manager ruling 2026-11-14 06:08Z, after RQ-20261114-db1a-02: the 2025-11..2026-11 loss
is common (12/15 legs negative, pooled -142.3R vs +106.1R the year before) and sits on the LONG side in every ADX cell
(longs -131.7R vs +30.7R), while no ADX cell separates it. This grader reads ONE ``exit_lever_ablation`` run per leg per
window (``<out>/rec_<leg>``, ``<out>/pre_<leg>``, arm ``A`` = the leg config-exact on its LIVE decision bar, full cost
stack) and applies the unit's registered rule to a FIXED filter (no parameter is chosen from the data):

  filter   a LONG entry is GATED when the symbol's last COMPLETED daily close before the entry (Binance daily, the
           leg's own symbol) is below the 200-day simple moving average of daily closes ending at that bar. Shorts
           are never gated. A long whose SMA cannot be computed is ``unknown`` and is not gated.
  cell     G = the gated longs, pooled across legs.
  passes   (1) G's pooled record-window net_r < 0 with n >= 30; (2) on the PRIOR window G has n >= 10 and pooled
           net_r < 0; (3) over both windows pooled, regime_cell_walkforward.cell_verdict on FOLD_PANEL reads
           ``long_verdict == stable_drag``.
  verdict  pass iff all three; fail iff G is graded and a clause fails; indeterminate iff fewer than 12 legs are
           graded, G has n < 30 on the record window, more than 5% of longs are ``unknown``, or a daily feed could
           not be fetched for a leg with longs.

The hypothesis came FROM the record year's long-side loss, so clause (2) -- the year before, which no selection read --
is the real test. It is a POST-HOC trade filter on the emitted ledgers: dropping a trade does not re-open the capacity it
used (path effects are ignored), so a PASS is a POINTER to a harness-native Tier-3 proposal, never a change.
Descriptive: filtered pooled net per window, per-leg filtered net on both windows, and the legs positive on both.
Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from bisect import bisect_left
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "research"), str(ROOT / "scripts"), str(ROOT)]

import regime_common_loss_grade as rcl  # noqa: E402

UNIT = "RQ-20261114-db1a-03"
RULE = "RULE-DFR-HTF-LONG-FILTER-20261114"
SMA_DAYS = 200
MIN_LEGS = 12
MIN_N_RECORD = 30
MIN_N_PRIOR = 10
MAX_UNKNOWN_SHARE = 0.05


def daily_sma_table(daily_csv: str) -> List[Tuple[str, float, Optional[float]]]:
    """[(date 'YYYY-MM-DD' of the completed daily bar, close, SMA200 ending at it or None)], oldest first."""
    from candle_io import load_candles
    df = load_candles(daily_csv)
    import pandas as pd
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    closes = [float(x) for x in df["close"]]
    out = []
    run = 0.0
    for i, (t, c) in enumerate(zip(ts, closes)):
        run += c
        if i >= SMA_DAYS:
            run -= closes[i - SMA_DAYS]
        sma = run / SMA_DAYS if i >= SMA_DAYS - 1 else None
        out.append((t.strftime("%Y-%m-%d"), c, sma))
    return out


def gate_state(table: List[Tuple[str, float, Optional[float]]], entry_time: Any) -> str:
    """below | above | unknown, from the last daily bar whose DATE is strictly before the entry's UTC date."""
    d = str(entry_time)[:10]
    dates = [r[0] for r in table]
    i = bisect_left(dates, d) - 1
    if i < 0:
        return "unknown"
    _, c, sma = table[i]
    if sma is None:
        return "unknown"
    return "below" if c < sma else "above"


def annotate(trades: List[Dict[str, Any]], table) -> List[Dict[str, Any]]:
    out = []
    for t in trades:
        x = dict(t)
        x["htf"] = gate_state(table, t.get("entry_time")) if rcl._dir(t) == "long" else "short"
        out.append(x)
    return out


def _sum(ts: List[Dict[str, Any]]) -> float:
    return round(sum(float(t.get("net_r") or 0) for t in ts), 4)


def grade_cells(rec: List[Dict[str, Any]], pre: List[Dict[str, Any]], wf=rcl.walkforward) -> Dict[str, Any]:
    g_rec = [t for t in rec if t["htf"] == "below"]
    g_pre = [t for t in pre if t["htf"] == "below"]
    longs = [t for t in rec + pre if t["htf"] != "short"]
    unknown = [t for t in longs if t["htf"] == "unknown"]
    share = round(len(unknown) / len(longs), 4) if longs else None
    base = {"gated_record": {"n": len(g_rec), "net_r": _sum(g_rec)}, "gated_prior": {"n": len(g_pre), "net_r": _sum(g_pre)},
            "kept_record_net_r": round(_sum(rec) - _sum(g_rec), 4), "kept_prior_net_r": round(_sum(pre) - _sum(g_pre), 4),
            "ungated_record_net_r": _sum(rec), "ungated_prior_net_r": _sum(pre),
            "longs": len(longs), "unknown_longs": len(unknown), "unknown_share": share}
    if share is not None and share > MAX_UNKNOWN_SHARE:
        return dict(base, verdict="indeterminate", note=f"{share:.1%} of longs have no SMA{SMA_DAYS} (> {MAX_UNKNOWN_SHARE:.0%})")
    if len(g_rec) < MIN_N_RECORD:
        return dict(base, verdict="indeterminate", note=f"gated longs n {len(g_rec)} < {MIN_N_RECORD} on the record window")
    c1 = _sum(g_rec) < 0
    c2 = len(g_pre) >= MIN_N_PRIOR and _sum(g_pre) < 0
    v = wf(g_rec + g_pre, "htf_below_sma200") if (g_rec + g_pre) else {}
    c3 = v.get("long_verdict") == "stable_drag"
    ok = bool(c1 and c2 and c3)
    return dict(base, record_negative=c1, prior_holds=c2, walkforward=v, walkforward_stable_drag=c3,
                verdict="pass" if ok else "fail",
                note=(f"gated longs: record {_sum(g_rec)} n{len(g_rec)}; prior {_sum(g_pre)} n{len(g_pre)}; "
                      f"walk-forward {v.get('long_verdict')}"))


def _daily_for(sym: str, cache: Dict[str, str], td: str) -> Optional[str]:
    import regime_debt_matrix as rdm
    if sym not in cache:
        feed = rdm.resolve_feed(sym, "1d")
        p = str(Path(td) / f"{sym}_1d.csv")
        try:
            rdm._fetch_csv(feed, 1100, p)
        except Exception as exc:  # noqa: BLE001  # allow-silent: a fetch failure is reported and makes the unit indeterminate
            print(f"[daily] {sym}: fetch failed {type(exc).__name__}: {exc}", file=sys.stderr)
            return None
        cache[sym] = p
    return cache[sym]


def grade(out: Path, legs: List[str], daily_override: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())
    cfg = cfg.get("strategies", cfg)
    runs = {leg: {"rec": rcl.read_run(out / f"rec_{leg}"), "pre": rcl.read_run(out / f"pre_{leg}")} for leg in legs}
    graded = [leg for leg, v in runs.items() if v["rec"] and v["pre"]]
    per_leg: Dict[str, Any] = {}
    all_rec: List[Dict[str, Any]] = []
    all_pre: List[Dict[str, Any]] = []
    fetch_fail = []
    with tempfile.TemporaryDirectory(prefix="dfr_daily_") as td:
        cache: Dict[str, str] = {}
        for leg in graded:
            sym = str(cfg[leg]["symbols"][0])
            csv = (daily_override or {}).get(sym) or _daily_for(sym, cache, td)
            r, p = runs[leg]["rec"]["trades"], runs[leg]["pre"]["trades"]
            if csv is None:
                if any(rcl._dir(t) == "long" for t in r + p):
                    fetch_fail.append(leg)
                continue
            table = daily_sma_table(csv)
            ar, ap = annotate(r, table), annotate(p, table)
            all_rec += ar
            all_pre += ap
            kr = [t for t in ar if t["htf"] != "below"]
            kp = [t for t in ap if t["htf"] != "below"]
            per_leg[leg] = {"record_net_r": _sum(ar), "record_n": len(ar), "prior_net_r": _sum(ap), "prior_n": len(ap),
                            "filtered_record_net_r": _sum(kr), "filtered_record_n": len(kr),
                            "filtered_prior_net_r": _sum(kp), "filtered_prior_n": len(kp)}
    cells = grade_cells(all_rec, all_pre)
    if len(graded) < MIN_LEGS or fetch_fail:
        cells = dict(cells, verdict="indeterminate",
                     note=(f"graded legs {len(graded)} < {MIN_LEGS}" if len(graded) < MIN_LEGS else f"daily feed failed for {fetch_fail}"))
    both_pos = sorted(k for k, r in per_leg.items() if r["filtered_record_net_r"] > 0 and r["filtered_prior_net_r"] > 0)
    n = (len(all_rec) + len(all_pre)) if cells["verdict"] != "indeterminate" else None
    rs = "measured" if cells["verdict"] != "indeterminate" else "producer_failed"
    return {"verdict": cells["verdict"], "read_state": rs, "n": n, "research_unit": UNIT, "rule": RULE,
            "population": (f"{len(legs)} crypto demo-floor pullback/trend legs (testing, bybit_1), each config-exact on its live "
                           "decision bar; record 2025-11-13..2026-11-12 and prior 2024-11-13..2025-11-12; full cost stack; "
                           f"longs gated when the prior daily close < SMA{SMA_DAYS} (own symbol, Binance daily)"),
            "filter": {"sma_days": SMA_DAYS, "symbol": "own", "bar": "last completed UTC daily bar before entry"},
            "cells": cells, "per_leg": per_leg, "legs_filtered_positive_both_windows": both_pos,
            "records": [{"leg": "HTF_LONG_FILTER:below_sma200_longs", "verdict": cells["verdict"], "read_state": rs, "n": n,
                         "population": f"gated longs of {len(per_leg)} legs, record + prior windows", "note": cells.get("note")}],
            "pointer_only": "post-hoc trade filter; a PASS points at a harness-native Tier-3 proposal, not a change"}


def _self_test() -> int:
    table = [(f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}", 100.0 + i, None) for i in range(250)]
    closes = [r[1] for r in table]
    table = [(d, c, (sum(closes[max(0, i - 199):i + 1]) / 200 if i >= 199 else None)) for i, (d, c, _) in enumerate(table)]
    assert gate_state(table, "2024-01-05 03:00:00+00:00") == "unknown"
    assert gate_state(table, "2024-09-01 00:00:00+00:00") == "above"
    down = [(d, 300.0 - i, None) for i, (d, _, _) in enumerate(table)]
    dc = [r[1] for r in down]
    down = [(d, c, (sum(dc[max(0, i - 199):i + 1]) / 200 if i >= 199 else None)) for i, (d, c, _) in enumerate(down)]
    assert gate_state(down, "2024-09-01 00:00:00+00:00") == "below"
    assert gate_state(down, "2023-12-31 00:00:00+00:00") == "unknown"

    def tr(t, d, r, h):
        return {"entry_time": t, "direction": d, "net_r": r, "htf": h}
    rec = [tr(f"2026-{1 + i % 12:02d}-{1 + i % 27:02d} 00:00:00+00:00", "long", -0.4, "below") for i in range(40)]
    rec += [tr(f"2026-{1 + i % 12:02d}-{1 + i % 27:02d} 01:00:00+00:00", "long", 0.1, "above") for i in range(40)]
    pre = [tr(f"2025-{1 + i % 12:02d}-{1 + i % 27:02d} 00:00:00+00:00", "long", -0.2, "below") for i in range(15)]
    stub = lambda trades, reg: {"long_verdict": "stable_drag"}  # noqa: E731
    g = grade_cells(rec, pre, wf=stub)
    assert g["verdict"] == "pass" and g["gated_record"]["n"] == 40 and g["kept_record_net_r"] == 4.0, g
    assert grade_cells(rec, [dict(t, net_r=0.3) for t in pre], wf=stub)["verdict"] == "fail"
    assert grade_cells(rec, pre, wf=lambda a, b: {"long_verdict": "no_stable_drag"})["verdict"] == "fail"
    assert grade_cells(rec[:20] + rec[40:], pre, wf=stub)["verdict"] == "indeterminate"
    unk = rec + [tr("2026-01-01 00:00:00+00:00", "long", 0.0, "unknown")] * 10
    assert grade_cells(unk, pre, wf=stub)["verdict"] == "indeterminate"
    v = rcl.walkforward(rec[:40] + pre, "htf")
    assert v["long_verdict"] == "stable_drag", v
    a = annotate([{"entry_time": "2024-09-01 00:00:00+00:00", "direction": "short", "net_r": 1}], down)
    assert a[0]["htf"] == "short"
    print("htf_long_filter_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out")
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not a.leg:
        ap.error("--out and at least one --leg are required")
    out = Path(a.out)
    v = grade(out, a.leg)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    c = v["cells"]
    print(f"gated longs: record {c['gated_record']} prior {c['gated_prior']}; kept record {c['kept_record_net_r']} (ungated "
          f"{c['ungated_record_net_r']}), kept prior {c['kept_prior_net_r']} (ungated {c['ungated_prior_net_r']})")
    print(f"legs filtered-positive on both windows: {v['legs_filtered_positive_both_windows']}")
    print(f"unit: {v['verdict']} (n {v['n']}) {c.get('note')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
