#!/usr/bin/env python3
# wiring: manual-only - CF-D1-LABELS: label table for ML training from cf_bulk shard records: python3 scripts/research/cf_labels.py --shards <dir> --out labels.jsonl.gz
"""cf_labels: per-trade counterfactual LABELS for ML training (CF-D1-LABELS), built from ``cf_bulk`` shard records (cf_trade/1).

One row per graded job. Nothing is hidden: a low-fidelity row is EMITTED with ``fidelity_ok=false`` and its ``abs_gap_r`` so the
trainer decides (weights, filters, or ignores) with the number in hand. Labels are HINDSIGHT by construction: targets, never features.

Row fields
  trade_key, strategy, symbol, timeframe, direction, entry_time, exit_time_label_end (the post-exit horizon end: the moment the
  label stops depending on the future), harness_net_r (the recorded outcome)
  arm_net_r        {arm_id: net R} for original_brackets, every alt_sl*_tp*, every less/more_management arm (resolved arms only;
                   an unresolved arm is absent, never 0)
  delta_vs_replay  {arm_id: arm net R - replayed_actual net R}: the label an exit/bracket chooser learns
  post_exit        {verdict, r_diff, mfe_r, mae_r}: did exiting when it did leave or save R
  fidelity_ok / abs_gap_r   replay-vs-harness gap on this row, and whether it is within the registered 0.10 R
  provenance       ESTIMATED

``purged_folds`` is the purge/embargo helper: time-ordered folds where every TRAIN row whose label window ``[entry, label_end]``
overlaps a TEST fold's span (plus ``embargo_s``) is dropped, so a training label never sees the future of a test trade.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_labels/1"
FIDELITY_TOL_R = 0.10


def label_row(rec: dict) -> Optional[dict]:
    """The label row for one cf_bulk shard record, or None when the job was not graded (those are counted by the caller)."""
    cf = rec.get("cf") or {}
    if cf.get("status") != "graded":
        return None
    a = cf["arms"]
    arm: Dict[str, float] = {}
    if (a.get("original_brackets") or {}).get("net_r") is not None and a["original_brackets"].get("resolved", True):
        arm["original_brackets"] = a["original_brackets"]["net_r"]
    for x in a.get("alt_brackets") or []:
        if x.get("net_r") is not None and x.get("resolved", True) and x.get("sl_mult") is not None:
            arm[f"alt_sl{x['sl_mult']:g}x_tp{x['tp_r']:g}R"] = x["net_r"]
    for fam in ("less_management", "more_management"):
        for x in a.get(fam) or []:
            if x.get("net_r") is not None and x.get("resolved", True):
                arm[x["arm_id"]] = x["net_r"]
    base = a.get("replayed_actual_net_r")
    po = cf.get("post_exit") or {}
    v = po.get("verdict") or {}
    gap = (cf.get("fidelity") or {}).get("abs_gap_r")
    return {"schema": SCHEMA, "trade_key": rec["trade_key"], "strategy": rec.get("strategy"), "symbol": rec.get("symbol"),
            "timeframe": rec.get("timeframe"), "direction": rec.get("direction"), "entry_time": rec.get("entry_time"),
            "label_end": (cf.get("path") or {}).get("horizon_end"), "harness_net_r": rec.get("net_r"),
            "replayed_actual_net_r": base, "arm_net_r": arm,
            "delta_vs_replay": {k: round(x - base, 6) for k, x in arm.items()} if base is not None else {},
            "post_exit": {"verdict": v.get("verdict"), "r_diff": v.get("r_diff"), "mfe_r": po.get("mfe_r"), "mae_r": po.get("mae_r")},
            "abs_gap_r": gap, "fidelity_ok": gap is not None and gap <= FIDELITY_TOL_R, "provenance": "ESTIMATED"}


def iter_records(shards_dir: str) -> Iterator[dict]:
    for f in sorted(glob.glob(str(Path(shards_dir) / "*.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for ln in fh:
                if ln.strip():
                    yield json.loads(ln)


def build(records: Iterable[dict]) -> Tuple[List[dict], Dict[str, Any]]:
    rows, n, n_ok = [], 0, 0
    for r in records:
        n += 1
        lr = label_row(r)
        if lr:
            rows.append(lr)
            n_ok += lr["fidelity_ok"]
    return rows, {"schema": SCHEMA, "n_records": n, "n_labelled": len(rows), "n_not_graded": n - len(rows), "n_fidelity_ok": n_ok,
                  "frac_fidelity_ok": None if not rows else round(n_ok / len(rows), 4), "fidelity_tol_r": FIDELITY_TOL_R,
                  "note": "low-fidelity rows are emitted with fidelity_ok=false, never dropped"}


def purged_folds(rows: Sequence[dict], n_folds: int = 5, embargo_s: float = 0.0) -> List[Dict[str, List[int]]]:
    """Time-ordered folds over ``rows`` (by entry_time). Returns ``[{test: [idx...], train: [idx...]}]`` of row indices; a train row
    is DROPPED when its label window [entry, label_end] intersects the test fold's [first entry, last label_end + embargo_s]."""
    ts = []
    for i, r in enumerate(rows):
        t0, t1 = lrc._ts(r.get("entry_time")), lrc._ts(r.get("label_end"))
        if t0 is not None:
            ts.append((t0, t1 if t1 is not None else t0, i))
    ts.sort()
    out: List[Dict[str, List[int]]] = []
    if not ts or n_folds < 2:
        return out
    size = max(1, len(ts) // n_folds)
    for f in range(n_folds):
        chunk = ts[f * size:(f + 1) * size] if f < n_folds - 1 else ts[f * size:]
        if not chunk:
            continue
        lo, hi = min(c[0] for c in chunk), max(c[1] for c in chunk) + embargo_s
        test = [c[2] for c in chunk]
        tset = set(test)
        train = [c[2] for c in ts if c[2] not in tset and not (c[0] <= hi and c[1] >= lo)]
        out.append({"test": test, "train": train})
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shards", required=True, help="dir of cf_bulk shard *.jsonl.gz")
    ap.add_argument("--out", required=True, help="labels.jsonl.gz")
    a = ap.parse_args(argv)
    rows, meta = build(iter_records(a.shards))
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    Path(a.out + ".meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
