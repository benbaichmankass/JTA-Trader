#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-10 (tlt_pullback_1h tp_r 3.5 re-measure) dispatches it as its last command
"""Short-side carry add-on + pre-registered both-sides vs long-only grade for ONE equity leg, read from an
``exit_lever_ablation.py`` output directory.

Why (manager 2026-11-14 15:21Z, tlt_pullback_1h real-money promotion check): the harness cost stack for a US ETF is
fee 0 + slippage 5 bps round trip + funding 0. A SHORT also pays (a) stock borrow and (b) the dividends the ETF goes
ex on while the short is open. The bars are Alpaca ``adjustment=split`` (scripts/research/equity_1m_source.py), so an
ex-date price drop shows up as a gain to the short that the short then owes back as the dividend -- unmodelled.

THE ADD-ON (ESTIMATED provenance, never MEASURED; parameters fixed in the calling unit before the run), per short
trade with calendar hold h days (exit_time - entry_time), entry price E and stop distance |E - sl|:
    cost_frac = (div_pa + borrow_pa) * h / 365          (expected dividend + borrow over the hold, pro rata)
    cost_r    = cost_frac * E / |E - sl|                (in the trade's own R)
Long trades carry no add-on (a long RECEIVES the dividend the split-adjusted bars also omit, so long net is a
conservative read). A worst case -- every short pays one full monthly dividend, div_pa/12 of notional -- is
REPORTED, NOT GRADED.

THE RULE (registered in the calling unit; this module only applies it):
  INDETERMINATE  the ablation's control arm did not reproduce the committed record, an arm ledger is missing,
                 or an arm holds fewer than n_floor trades.
  both clause    PASS iff the both-sides arm's net R AFTER the add-on > 0.
  long clause    PASS iff the long-only arm's net R > 0.
  proposal arm   the both-sides arm if its clause passes AND its adjusted net >= the long-only arm's net; else the
                 long-only arm if its clause passes; else none.
  unit           PASS iff a proposal arm exists; FAIL otherwise.
Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def short_cost_r(t: Dict[str, Any], div_pa: float, borrow_pa: float, monthly_worst: bool = False) -> float:
    if str(t.get("direction")) != "short":
        return 0.0
    e, sl = float(t["entry"]), float(t["sl"])
    risk = abs(e - sl)
    if risk <= 0:
        return 0.0
    if monthly_worst:
        frac = div_pa / 12.0
    else:
        h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 86400.0
        frac = (div_pa + borrow_pa) * max(h, 0.0) / 365.0
    return frac * e / risk


def arm_stats(trades: List[Dict[str, Any]], div_pa: float, borrow_pa: float) -> Dict[str, Any]:
    net = sum(float(t.get("net_r") or 0.0) for t in trades)
    shorts = [t for t in trades if str(t.get("direction")) == "short"]
    add = sum(short_cost_r(t, div_pa, borrow_pa) for t in shorts)
    worst = sum(short_cost_r(t, div_pa, borrow_pa, monthly_worst=True) for t in shorts)
    by = {d: round(sum(float(t.get("net_r") or 0.0) for t in trades if str(t.get("direction")) == d), 4)
          for d in ("long", "short")}
    return {"n": len(trades), "n_short": len(shorts), "net_r": round(net, 4), "short_addon_r": round(add, 4),
            "net_r_adj": round(net - add, 4), "net_r_worst_monthly_div": round(net - worst, 4), "net_r_by_side": by}


def _read(p: Path) -> Optional[List[Dict[str, Any]]]:
    if not p.exists():
        return None
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _control_ok(abl: Path) -> Optional[bool]:
    try:
        v = json.loads((abl / "verdict.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if v.get("label") == "control_failed":
        return False
    m = v.get("measurement") or {}
    g = m.get("grade") if isinstance(m.get("grade"), dict) else m
    c = (g or {}).get("control") if isinstance(g, dict) else None
    if c is None:
        c = v.get("control")
    if isinstance(c, dict) and "ok" in c:
        return bool(c["ok"])
    return None


def grade(stats: Dict[str, Dict[str, Any]], both: str, long_: str, n_floor: int, control_ok: Optional[bool]) -> Dict[str, Any]:
    if control_ok is not True:
        return {"verdict": "indeterminate", "label": "control_not_reproduced" if control_ok is False else "control_unread",
                "proposal_arm": None}
    if any(s is None for s in stats.values()):
        return {"verdict": "indeterminate", "label": "arm_missing", "proposal_arm": None}
    if min(stats[both]["n"], stats[long_]["n"]) < n_floor:
        return {"verdict": "indeterminate", "label": "underpowered", "proposal_arm": None}
    b_ok = stats[both]["net_r_adj"] > 0.0
    l_ok = stats[long_]["net_r"] > 0.0
    if b_ok and stats[both]["net_r_adj"] >= stats[long_]["net_r"]:
        arm = both
    elif l_ok:
        arm = long_
    else:
        arm = None
    return {"verdict": "pass" if arm else "fail", "label": f"proposal_{arm}" if arm else "no_arm_clears",
            "both_clause": "pass" if b_ok else "fail", "long_clause": "pass" if l_ok else "fail", "proposal_arm": arm}


def run(abl: Path, both: str, long_: str, also: List[str], div_pa: float, borrow_pa: float, n_floor: int, leg: str,
        unit: str, rule: str) -> Dict[str, Any]:
    labels = [both, long_] + [x for x in also if x not in (both, long_)]
    raw = {k: _read(abl / "arms" / f"{k}__trades.jsonl") for k in labels}
    stats = {k: (arm_stats(v, div_pa, borrow_pa) if v is not None else None) for k, v in raw.items()}
    ctrl = _control_ok(abl)
    g = grade({both: stats[both], long_: stats[long_]}, both, long_, n_floor, ctrl)
    n = sum(s["n"] for s in stats.values() if s)
    pop = (f"{leg}: arms {labels} from {abl}; per-trade net_r from the harness (fee+slippage+funding), short add-on "
           f"(div {div_pa:.3f} + borrow {borrow_pa:.3f} per annum, pro rata over the calendar hold; ESTIMATED)")
    note = "; ".join(f"{k} n {s['n']} net {s['net_r']} adj {s['net_r_adj']} (shorts {s['n_short']}, add-on {s['short_addon_r']})"
                     for k, s in stats.items() if s) + f"; control_ok {ctrl}; proposal_arm {g['proposal_arm']}"
    v = {"verdict": g["verdict"], "read_state": "measured" if g["verdict"] != "indeterminate" else "producer_failed",
         "n": n, "research_unit": unit, "rule": rule, "population": pop, "grade": g, "arms": stats,
         "addon": {"div_pa": div_pa, "borrow_pa": borrow_pa, "provenance": "ESTIMATED"}, "note": note}
    v["records"] = [{"leg": leg, "verdict": v["verdict"], "read_state": v["read_state"], "n": n, "population": pop,
                     "note": note}]
    return v


def _self_test() -> int:
    import tempfile

    def tr(d, net, e=100.0, sl=101.0, h=2.0):
        t0 = pd.Timestamp("2026-01-05 15:00", tz="UTC")
        return {"direction": d, "net_r": net, "entry": e, "sl": sl if d == "short" else 2 * e - sl,
                "entry_time": str(t0), "exit_time": str(t0 + pd.Timedelta(days=h))}
    # 2-day short, entry 100, risk 1: (0.05+0.01)*2/365*100/1 = 0.03288 R
    assert abs(short_cost_r(tr("short", 0), 0.05, 0.01) - 0.032877) < 1e-5
    assert short_cost_r(tr("long", 0), 0.05, 0.01) == 0.0
    assert abs(short_cost_r(tr("short", 0), 0.05, 0.01, monthly_worst=True) - 0.05 / 12 * 100) < 1e-9
    with tempfile.TemporaryDirectory() as d:
        abl = Path(d)
        (abl / "arms").mkdir()

        def put(label, rows):
            (abl / "arms" / f"{label}__trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

        def ctrl(ok):
            (abl / "verdict.json").write_text(json.dumps({"measurement": {"control": {"ok": ok}}}))
        put("B", [tr("long", 0.5)] * 10 + [tr("short", 0.1)] * 10)     # net 6.0, add-on 0.33 -> adj 5.67
        put("L", [tr("long", 0.5)] * 10)                                 # net 5.0
        ctrl(True)
        g = run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")
        assert g["verdict"] == "pass" and g["grade"]["proposal_arm"] == "B", g["grade"]
        put("L", [tr("long", 0.7)] * 10)                                 # long-only 7.0 beats adj 5.67
        assert run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")["grade"]["proposal_arm"] == "L"
        put("B", [tr("long", -0.1)] * 10 + [tr("short", 0.05)] * 10)    # net -0.5 -> both fails
        put("L", [tr("long", -0.1)] * 10)
        assert run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")["verdict"] == "fail"
        ctrl(False)
        assert run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")["verdict"] == "indeterminate"
        (abl / "verdict.json").unlink()
        assert run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")["grade"]["label"] == "control_unread"
        ctrl(True)
        put("L", [tr("long", 1.0)] * 3)
        assert run(abl, "B", "L", [], 0.05, 0.01, 10, "x", "U", "R")["grade"]["label"] == "underpowered"
    print("short_cost_addon_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--ablation-out", help="the exit_lever_ablation --out directory (arms/<LABEL>__trades.jsonl, verdict.json)")
    ap.add_argument("--both-arm", help="the both-sides arm label")
    ap.add_argument("--long-arm", help="the long-only arm label")
    ap.add_argument("--report-arm", action="append", default=[], help="further arms reported, not graded")
    ap.add_argument("--div-pa", type=float, default=None, help="dividend yield per annum charged to shorts (fraction)")
    ap.add_argument("--borrow-pa", type=float, default=None, help="borrow fee per annum charged to shorts (fraction)")
    ap.add_argument("--n-floor", type=int, default=10)
    ap.add_argument("--leg")
    ap.add_argument("--unit")
    ap.add_argument("--rule")
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    need = (a.ablation_out, a.both_arm, a.long_arm, a.div_pa, a.borrow_pa, a.leg, a.unit, a.rule, a.out)
    if any(x is None for x in need):
        ap.error("--ablation-out --both-arm --long-arm --div-pa --borrow-pa --leg --unit --rule --out are required")
    v = run(Path(a.ablation_out), a.both_arm, a.long_arm, a.report_arm, a.div_pa, a.borrow_pa, a.n_floor, a.leg,
            a.unit, a.rule)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"unit: {v['verdict']} (n {v['n']}) {v['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
