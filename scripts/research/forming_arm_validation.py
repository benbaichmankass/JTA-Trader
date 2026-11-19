#!/usr/bin/env python3
# wiring: manual-only - run by queue unit RQ-20261119-f1a7-01 (research-script-run.yml, once #27207 is on main and the manager un-blocks it); no schedule consumes it.
"""VALIDATION of the ict_scalp forming-bar harness arm (row ICT-SCALP-FORMING-BAR-ARM), before any forming-bar RESULT is read.

Registered BEFORE any run: unit RQ-20261119-f1a7-01 decision_rule RULE-RQ20261119F1A7-01-FORMING-ARM-VALIDATION (lane QUEUE-FILL-STANDING-W47b, manager
2026-11-19: "author it as a registered VALIDATION unit, on a runner with real 1m data, using the row's own tolerance as the rule"). RQ-20261119-e11f-01
(the as-traded Stage-0 run) depends on this unit's PASS.

WHAT IT CHECKS (mechanics, never edge):
  1  run      scripts/research/exit_lever_ablation.py --leg ict_scalp_eth_15m with two arms over the pinned window: CLOSED (the leg as declared, the
              committed record's arm) and FORMING (`--decision-bar=forming`, fed the Binance-vision 1m CSV by `--forming-1m-fetch`).
  2  control  the CLOSED arm reproduces the committed record: |n - 76| / 76 <= TOL_N (2 trades of 76) AND |net_r - (-2.925)| <= TOL_R (0.5 R). Same
              function the ablation uses (exit_lever_ablation.check_control), applied here to the arm's own __bt.json against the committed run's __bt.json.
  3  forming  the FORMING arm is non-empty AND every one of its entries is stamped on a decision tick: minutes into its 15m bar in
              forming_bar_entries.session_ticks(None, 15) (2,4,...,12), on a whole minute. A closed-bar entry (offset 0) in the forming arm means the
              flag did nothing.
PASS iff 2 AND 3. FAIL otherwise, with a named label: `control_failed`, `forming_empty`, `bad_tick_stamp`. A harness / fetch failure is a producer
failure (non-zero exit), never a FAIL. Reported, NOT graded: n and net R of the FORMING arm, the share of CLOSED entries at offset 0.

WINDOW. 2025-10-28 .. 2026-10-27 23:59 UTC, the committed record's own window (comms/strategy_evidence/runs/2026-10-28/ict_scalp_eth_15m__bt.json:
data_start 2025-10-28, data_end 2026-10-27 23:45). NOT the 2025-10-04..2026-10-01 window of RQ-20261119-e11f-01: the committed closed run on THAT window
is the 2026-10-02 run (n 78, net_r +1.318), so a control against n 76 / -2.925 cannot reproduce there. `--days 460` so the fetch still covers the pinned start
when the unit runs weeks later (a `--days 400` fetch from 2026-11-19 starts about 2025-10-15).

A control failure means the pinned window / feed / cost stack differ from the record's: investigate those before concluding the flag is wrong.
Tier-1 research tooling: public candles + Binance-vision 1m, writes only under --out, no config, no order. Gates this adds or changes: none.
Provenance: n and net R are MEASURED when a run lands; nothing in this file is a result.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LEG = "ict_scalp_eth_15m"
TF_MIN = 15
RECORD_BT = "comms/strategy_evidence/runs/2026-10-28/ict_scalp_eth_15m__bt.json"
START, END, DAYS = "2025-10-28", "2026-10-27 23:59", 460
TOL_N = 2.0 / 76.0 + 1e-4        # 2 trades of the record's 76 (check_control takes a FRACTION of n)
TOL_R = 0.5
TICKS = (2, 4, 6, 8, 10, 12)     # forming_bar_entries.session_ticks(None, 15, 2); asserted equal in the self-test


def control(arm_bt: Dict[str, Any], record_bt: Dict[str, Any]) -> Dict[str, Any]:
    """The ablation's own check_control, on the arm's __bt.json against the committed run's."""
    import exit_lever_ablation as ela
    return ela.check_control({"n": int(arm_bt["total_trades"]), "net_r": float(arm_bt["net_total_r"])}, record_bt, TOL_N, TOL_R)


def tick_offsets(trades: List[Dict[str, Any]]) -> List[Optional[float]]:
    """Minutes into the entry's own 15m bar, or None for an unreadable timestamp. Whole minutes only count as ticks."""
    import pandas as pd
    out: List[Optional[float]] = []
    for t in trades:
        try:
            ts = pd.Timestamp(t["entry_time"])
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            out.append((ts - ts.floor(f"{TF_MIN}min")).total_seconds() / 60.0)
        except (KeyError, TypeError, ValueError):
            out.append(None)
    return out


def evaluate(closed_bt: Dict[str, Any], record_bt: Dict[str, Any], forming_trades: List[Dict[str, Any]],
             closed_trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    ctl = control(closed_bt, record_bt)
    offs = tick_offsets(forming_trades)
    bad = [o for o in offs if o is None or o not in TICKS]
    res: Dict[str, Any] = {
        "control": ctl, "n_forming": len(forming_trades), "n_bad_tick_stamp": len(bad),
        "forming_offsets_seen": sorted({o for o in offs if o is not None}),
        "closed_share_at_offset_0": None, "ticks": list(TICKS),
    }
    if closed_trades:
        co = tick_offsets(closed_trades)
        res["closed_share_at_offset_0"] = round(sum(1 for o in co if o == 0.0) / len(co), 4)
    if not ctl["ok"]:
        res.update(verdict="FAIL", label="control_failed",
                   why=f"CLOSED arm n {ctl['arm_n']} / net_r {ctl['arm_net_r']} vs the record n {ctl['record_n']} / {ctl['record_net_r']} "
                       f"(n diff {ctl['n_frac_diff']} > {ctl['tol_n']:.4f} or net_r diff {ctl['net_r_abs_diff']} > {ctl['tol_r']})")
    elif not forming_trades:
        res.update(verdict="FAIL", label="forming_empty", why="the FORMING arm produced no trade")
    elif bad:
        res.update(verdict="FAIL", label="bad_tick_stamp",
                   why=f"{len(bad)} of {len(forming_trades)} FORMING entries are not on a decision tick {list(TICKS)} min into the bar")
    else:
        res.update(verdict="PASS", label="validated",
                   why=f"CLOSED control reproduces the record (n {ctl['arm_n']} vs {ctl['record_n']}, net_r {ctl['arm_net_r']} vs "
                       f"{ctl['record_net_r']}); all {len(forming_trades)} FORMING entries are tick-stamped")
    return res


def run_ablation(out: Path) -> Dict[str, Any]:
    """Step 1. Raises on a failed fetch or harness (a producer failure, never a partial read)."""
    abl = out / "ablation"
    abl.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", LEG, "--arm", "CLOSED=", "--arm", "FORMING=--decision-bar=forming",
         "--forming-1m-fetch", "--days", str(DAYS), "--start", START, "--end", END, "--grade", "stage0", "--baseline", "CLOSED", "--delta-r", "0",
         "--folds", "4", "--fold-majority", "3", "--n-floor", "1", "--control", f"CLOSED={REPO / RECORD_BT}", "--control-tol-n", str(TOL_N),
         "--control-tol-r", str(TOL_R), "--research-unit", "RQ-20261119-f1a7-01", "--out", str(abl)],
        cwd=str(REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"exit_lever_ablation exit {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
    rd = lambda p: [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]       # noqa: E731
    return {"closed_bt": json.loads((abl / "arms" / "CLOSED__bt.json").read_text()),
            "forming_trades": rd(abl / "arms" / "FORMING__trades.jsonl"),
            "closed_trades": rd(abl / "arms" / "CLOSED__trades.jsonl")}


def self_test() -> int:
    import forming_bar_entries as fbe
    assert tuple(fbe.session_ticks(None, TF_MIN, fbe.TICK_STEP)) == TICKS, "TICKS drifted from forming_bar_entries.session_ticks"
    assert abs(TOL_N * 76 - 2.0) < 0.01 and abs((2 / 76) - TOL_N) < 1e-3
    rec = {"total_trades": 76, "net_total_r": -2.9247}

    def tr(ts: str) -> Dict[str, Any]:
        return {"entry_time": ts}

    good = [tr("2026-01-05T10:02:00+00:00"), tr("2026-01-05T11:12:00+00:00"), tr("2026-01-06T00:04:00+00:00")]
    e = evaluate({"total_trades": 76, "net_total_r": -2.9247}, rec, good, [tr("2026-01-05T10:00:00+00:00")])
    assert e["verdict"] == "PASS" and e["closed_share_at_offset_0"] == 1.0, e
    assert evaluate({"total_trades": 74, "net_total_r": -2.5}, rec, good)["verdict"] == "PASS"           # 2 trades off: inside
    assert evaluate({"total_trades": 73, "net_total_r": -2.9}, rec, good)["label"] == "control_failed"   # 3 trades off: outside
    assert evaluate({"total_trades": 76, "net_total_r": -2.1}, rec, good)["label"] == "control_failed"   # 0.82 R off: outside
    assert evaluate({"total_trades": 76, "net_total_r": -2.5}, rec, good)["verdict"] == "PASS"           # 0.42 R off: inside
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, [])["label"] == "forming_empty"
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, good + [tr("2026-01-07T09:00:00+00:00")])["label"] == "bad_tick_stamp"   # offset 0
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, good + [tr("2026-01-07T09:13:00+00:00")])["label"] == "bad_tick_stamp"  # offset 13
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, good + [tr("2026-01-07T09:03:00+00:00")])["label"] == "bad_tick_stamp"  # odd minute
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, good + [tr("2026-01-07T09:04:30+00:00")])["label"] == "bad_tick_stamp"  # not whole
    assert evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, [{"x": 1}])["label"] == "bad_tick_stamp"                                  # unreadable
    naive = evaluate({"total_trades": 76, "net_total_r": -2.9}, rec, [tr("2026-01-05 10:02:00")])
    assert naive["verdict"] == "PASS", "a naive timestamp is read as UTC, the harness convention"
    print("forming_arm_validation self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", nargs="?", choices=("run",))
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.mode or not a.out:
        ap.error("`run --out DIR` or --self-test required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    got = run_ablation(out)
    record = json.loads((REPO / RECORD_BT).read_text())
    res = evaluate(got["closed_bt"], record, got["forming_trades"], got["closed_trades"])
    (out / "forming_arm_validation.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({
        "verdict": {"PASS": "pass", "FAIL": "fail"}[res["verdict"]], "read_state": "measured",
        "population": f"{LEG} CLOSED arm ({res['control']['arm_n']} trades) vs the committed record, and {res['n_forming']} FORMING-arm entries, "
                      f"window {START}..{END}",
        "n": res["n_forming"], "measurement": res, "note": f"{res['label']}: {res['why']}",
        "data_inputs": ["Binance 15m candles (rdm.resolve_feed)", "Binance-vision 1m (--forming-1m-fetch)"]}, indent=2, default=str) + "\n")
    print(json.dumps({k: res[k] for k in ("verdict", "label", "why", "n_forming", "n_bad_tick_stamp")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
