#!/usr/bin/env python3
"""Re-measure an `approximate` Stage-0 evidence record FAITHFULLY.

RQ-20261011-6707-01 (GUARD-FIDELITY, operator decision 2026-10-11). A record in
`comms/strategy_evidence/<leg>.json` graded `fidelity: approximate` names the
config levers its harness run omitted. For the pullback family the omission is
`trail_decay_stall_bars` / `trail_decay_tight_mult`: `scripts/backtest_pullback.py`
accepts both flags, but `regime_debt_matrix._PB_LEVER_FLAG` never maps them,
so the evidence producer ran without them.

Per leg this runs TWO arms over the SAME candles — the record's own
[data_start, data_end], re-fetched and trimmed — through the record's own
harness argv (`regime_debt_matrix.build_harness_cmd`):

  approximate  the argv exactly as the producer built it (INSTRUMENT CONTROL:
               it must reproduce the committed record, or the leg grades
               could_not_measure — never pass/fail on a window we cannot tie
               back to the record)
  faithful     the same argv plus every omitted lever this script can pass,
               at the leg's live config/strategies.yaml value

and grades the faithful arm against RULE-D1 (net_r_oos > 0, net of the full
cost stack) — the SAME bar the original record cleared.

Writes `<out>/verdict.json` (the research-script-run contract) and
`<out>/<leg>__{approximate,faithful}__bt.json`. Tier-1 research tooling: reads
config + records, writes only under --out. Never edits a roster or a record.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regime_debt_matrix as rdm  # type: ignore  # noqa: E402

REPO = Path(rdm.REPO)
EVIDENCE_DIR = REPO / "comms" / "strategy_evidence"
RULE_ID = "RULE-RQ1011-001-FAITHFUL-STAGE0"

#: Omitted config key -> harness flag this script CAN pass (pullback family).
#: Only keys the harness genuinely models; anything else stays omitted and the
#: faithful arm is reported as still-approximate rather than silently faithful.
PASSABLE = {
    "pullback": {
        "trail_decay_arm_r": "--trail-decay-arm-r",
        "trail_decay_stall_bars": "--trail-decay-stall-bars",
        "trail_decay_tight_mult": "--trail-decay-tight-mult",
    },
}

#: Instrument-control tolerance on the approximate arm vs the committed record.
CONTROL_TOL_R = 0.10
FETCH_DAYS = 900  # covers every record window in scope (<= ~540d) with margin


def _trim(csv: str, start: str, end: str) -> int:
    import pandas as pd
    df = pd.read_csv(csv)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    lo, hi = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
    df = df[(ts >= lo) & (ts <= hi)]
    df.to_csv(csv, index=False)
    return len(df)


def _run(argv: List[str]) -> Optional[str]:
    try:
        subprocess.run(argv, check=True, cwd=REPO, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)
        return None
    except subprocess.CalledProcessError as e:
        return (e.stderr or b"").decode()[-400:]


def measure(leg: str, cfg: Dict[str, Any], record: Dict[str, Any], out: Path) -> Dict[str, Any]:
    row: Dict[str, Any] = {"leg": leg, "rule_id": RULE_ID,
                           "record_fidelity": record.get("fidelity"),
                           "record_omitted_levers": record.get("omitted_levers"),
                           "record_n": record.get("n_trades_oos"),
                           "record_net_r_oos": record.get("net_r_oos")}
    src = record.get("source_run") or ""
    bt_path = REPO / src.replace("__trades.jsonl", "__bt.json")
    try:
        src_bt = json.loads(bt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        row.update(verdict="indeterminate", read_state="not_attempted",
                   note=f"cannot read the record's source run {bt_path}: {e}")
        return row
    start, end = src_bt.get("data_start"), src_bt.get("data_end")
    row["window"] = [start, end]

    harness = rdm.classify(cfg)
    sym, tf = cfg["symbols"][0], cfg["timeframe"]
    feed = rdm.resolve_feed(sym, tf)
    csv = str(out / f"{leg}__data.csv")
    try:
        rdm._fetch_csv(feed, FETCH_DAYS, csv)
        row["bars"] = _trim(csv, start, end)
    except Exception as e:  # noqa: BLE001  # allow-silent: not silent — the leg grades read_state=no_data with the exception text, never pass/fail
        row.update(verdict="indeterminate", read_state="no_data",
                   note=f"fetch failed: {type(e).__name__}: {e}")
        return row

    arms: Dict[str, Dict[str, Any]] = {}
    passable = PASSABLE.get(harness or "", {})
    for arm in ("approximate", "faithful"):
        emit = str(out / f"{leg}__{arm}__trades.jsonl")
        jout = str(out / f"{leg}__{arm}__bt.json")
        argv, _faithful, omitted = rdm.build_harness_cmd(
            leg, cfg, harness, csv, feed["resample"], emit, jout)
        still_omitted = list(omitted)
        if arm == "faithful":
            for key in omitted:
                if key in passable and cfg.get(key) is not None:
                    argv += [passable[key], str(cfg[key])]
                    still_omitted.remove(key)
        err = _run(argv)
        if err:
            arms[arm] = {"error": err}
            continue
        bt = json.loads(Path(jout).read_text(encoding="utf-8"))
        arms[arm] = {
            "n": bt.get("total_trades"), "net_r": bt.get("net_total_r"),
            "net_r_fee_only": bt.get("net_total_r_fee_only"),
            "cost_stack": {"fees": bt.get("fee_bps_roundtrip"),
                           "slippage": bt.get("slippage_bps_roundtrip"),
                           "funding": bt.get("funding_bps_per_window")},
            "still_omitted": still_omitted,
            "by_outcome": bt.get("by_outcome"),
        }
    row["arms"] = arms
    a, f = arms.get("approximate", {}), arms.get("faithful", {})
    if "error" in a or "error" in f:
        row.update(verdict="indeterminate", read_state="producer_failed",
                   note=f"harness failed: {a.get('error') or f.get('error')}")
        return row

    ctrl_ok = (a["n"] == record.get("n_trades_oos")
               and isinstance(record.get("net_r_oos"), (int, float))
               and abs(a["net_r"] - record["net_r_oos"]) <= CONTROL_TOL_R)
    row["control_reproduces_record"] = ctrl_ok
    row["delta_r"] = round(f["net_r"] - a["net_r"], 4)
    if not ctrl_ok:
        row.update(verdict="indeterminate", read_state="measured",
                   note=(f"could_not_measure: approximate arm n={a['n']} net_r={a['net_r']} does "
                         f"not reproduce record n={record.get('n_trades_oos')} "
                         f"net_r_oos={record.get('net_r_oos')} (tol {CONTROL_TOL_R}R); faithful "
                         f"net_r={f['net_r']} reported, NOT graded"))
        return row
    if f["still_omitted"]:
        row.update(verdict="indeterminate", read_state="measured",
                   note=f"faithful arm still omits {f['still_omitted']} — not faithful, not graded")
        return row
    passed = f["net_r"] is not None and f["net_r"] > 0
    row.update(verdict="pass" if passed else "fail", read_state="measured",
               note=(f"faithful net_r_oos={f['net_r']} over n={f['n']} (approximate "
                     f"{a['net_r']} over n={a['n']}; delta {row['delta_r']:+}R); cost_stack "
                     f"{f['cost_stack']}; RULE-D1 net_r_oos > 0 -> {'PASS' if passed else 'FAIL'}"))
    return row


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import yaml
    strategies = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())["strategies"]
    rows = []
    for leg in a.leg:
        cfg = strategies[leg]
        rec = json.loads((EVIDENCE_DIR / f"{leg}.json").read_text(encoding="utf-8"))
        row = measure(leg, cfg, rec, out)
        rows.append(row)
        print(f"{leg}: {row['verdict']} — {row.get('note')}")
    verdicts = [r["verdict"] for r in rows]
    overall = ("fail" if "fail" in verdicts else
               "indeterminate" if "indeterminate" in verdicts else "pass")
    verdict = {
        "verdict": overall, "read_state": "measured",
        "population": ("faithful (trail_decay simulated) vs approximate re-run of each "
                       "record's own harness over its own window: " + ", ".join(a.leg)),
        "n": sum((r.get("arms", {}).get("faithful", {}) or {}).get("n") or 0 for r in rows),
        "note": "; ".join(f"{r['leg']}={r['verdict']}" for r in rows),
        "records": rows,
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
