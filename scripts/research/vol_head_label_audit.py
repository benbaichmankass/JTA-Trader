#!/usr/bin/env python3
"""Weekly label audit of every SERVED vol-regime head: does the label the live gate would use predict REALIZED volatility on the
latest window? Streamed, one head at a time, <= 1 GB (row TRAINER-LIGHT-READS; manager 2026-11-26).

For each registry entry at stage shadow / advisory whose predictor carries a 2-class (range / volatile) regime spec, the rows of
its manifest dataset dated within the last ``--days`` (streamed, projected to the head's feature columns + ts + regime_label) are
scored with ``ml_vol_label_replay._score_rows`` (batched, verified against the canonical per-row predict_proba) to P(volatile).
The live label is ``volatile`` iff P >= the live threshold (ml_vol_label_replay.live_threshold, the router's own resolver).
The truth is the dataset's ``regime_label``, the FORWARD realized-vol class the head was trained to predict
(ml/datasets/families/market_features.py). Rows whose forward window is not complete (no regime_label) are excluded and counted.

Per head: n, realized volatile share, predicted volatile share, precision / recall of the volatile call, Cohen's kappa against
chance agreement from the two marginals, Brier score vs the base-rate Brier (Brier skill). This is the (c) out-of-time re-score
of the served regime heads as well: run after the FC-STRIDE-PHASE side-stream rebuild it reads the rows the heads are then
served on. Caveat stamped on every record: a head trained through the window is IN-SAMPLE on it (train_end is reported).

Verdict (script_run contract): fail = >= 1 head with n >= 200 has kappa < 0.2 OR Brier skill <= 0 (named); pass = every head with
n >= 200 clears both; indeterminate = no head reached n 200. Read-only; writes only under --out.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "scripts" / "research"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SERVED_STAGES = ("shadow", "advisory")
MIN_N = 200
KAPPA_MIN = 0.2


def label_metrics(p: Sequence[float], truth: Sequence[str], threshold: float) -> Dict[str, Any]:
    pairs = [(float(x), str(t)) for x, t in zip(p, truth) if x is not None and t in ("range", "volatile")]
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    y = [1 if t == "volatile" else 0 for _, t in pairs]
    yhat = [1 if x >= threshold else 0 for x, _ in pairs]
    tp = sum(1 for a, b in zip(y, yhat) if a and b)
    fp = sum(1 for a, b in zip(y, yhat) if not a and b)
    fn = sum(1 for a, b in zip(y, yhat) if a and not b)
    base, pred = sum(y) / n, sum(yhat) / n
    po = sum(1 for a, b in zip(y, yhat) if a == b) / n
    pe = base * pred + (1 - base) * (1 - pred)
    kappa = (po - pe) / (1 - pe) if pe < 1 else None
    brier = sum((x - a) ** 2 for (x, _), a in zip(pairs, y)) / n
    brier_base = base * (1 - base)
    return {"n": n, "realized_volatile_share": round(base, 4), "predicted_volatile_share": round(pred, 4),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "agreement": round(po, 4), "kappa": None if kappa is None else round(kappa, 4),
            "brier": round(brier, 5), "brier_base_rate": round(brier_base, 5),
            "brier_skill": round(1 - brier / brier_base, 4) if brier_base > 0 else None}


def _ts(v: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def head_record(entry: Any, *, registry_root: Path, days: int, threshold: float, data_root: Path = REPO) -> Dict[str, Any]:
    import ml_vol_label_replay as R  # noqa: PLC0415
    from registry_feature_preflight import dataset_path_for  # noqa: PLC0415
    from ml.manifest import canonical_stage  # noqa: PLC0415
    rec: Dict[str, Any] = {"model_id": entry.model_id, "stage": canonical_stage(entry.target_deployment_stage)}
    path = dataset_path_for(dict(entry.manifest or {}), data_root)
    if path is None or not path.is_file():
        return {**rec, "state": "could_not_check", "reason": f"dataset not present: {path}"}
    try:
        from ml.shadow.backfill import _instantiate_predictor  # noqa: PLC0415,PLC2701
        predictor = _instantiate_predictor(entry, registry_root=registry_root)
        base = R._unwrap(predictor)  # noqa: SLF001
        labels = [str(c) for c in (getattr(base, "class_labels", None) or ())]
        if "volatile" not in labels:
            return {**rec, "state": "not_a_vol_head", "reason": f"class labels {labels}"}
        cols = list(getattr(base, "_feature_columns", []) or [])
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows, no_label = [], 0
        for row in R.iter_projected_rows(path, cols + ["regime_label"]):
            t = _ts(row.get("ts"))
            if t is None or t < since:
                continue
            if row.get("regime_label") not in ("range", "volatile"):
                no_label += 1
                continue
            rows.append(row)
        if not rows:
            return {**rec, "state": "checked", "n": 0, "rows_without_label": no_label}
        scores, diag = R._score_rows(predictor, rows)  # noqa: SLF001
        m = label_metrics(scores, [r["regime_label"] for r in rows], threshold)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded per head as could_not_check, the sweep continues
        return {**rec, "state": "could_not_check", "reason": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        gc.collect()
    train_end = (getattr(entry, "metrics", {}) or {}).get("train_end") or (entry.manifest or {}).get("train_end")
    return {**rec, "state": "checked", **m, "rows_without_label": no_label, "window_days": days, "threshold": threshold,
            "first_ts": rows[0].get("ts"), "last_ts": rows[-1].get("ts"), "score_path": diag.get("path"),
            "train_end": train_end, "in_sample_caveat": "a head fit through this window is in-sample on it"}


def grade(recs: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    graded = [r for r in recs if r.get("state") == "checked" and (r.get("n") or 0) >= MIN_N]
    bad = [r["model_id"] for r in graded
           if (r.get("kappa") is None or r["kappa"] < KAPPA_MIN) or (r.get("brier_skill") is None or r["brier_skill"] <= 0)]
    if not graded:
        v, note = "indeterminate", f"no served vol head reached n {MIN_N} labelled rows in the last {days} days"
    elif bad:
        v, note = "fail", f"live vol label does not predict realized volatility (kappa < {KAPPA_MIN} or Brier skill <= 0): {bad}"
    else:
        v, note = "pass", f"all {len(graded)} graded served vol heads: kappa >= {KAPPA_MIN} and positive Brier skill"
    other = [f"{r['model_id']}:{r.get('state')}" for r in recs if r not in graded]
    if other:
        note += f" | not graded: {other}"
    return {"verdict": v, "read_state": "measured" if graded else "no_data", "n": int(sum(r["n"] for r in graded)),
            "population": f"served (shadow/advisory) 2-class vol-regime heads; their manifest dataset rows of the last {days} days "
                          f"with a complete forward regime_label; {len(graded)} head(s) graded at n >= {MIN_N}",
            "note": note, "records": recs}


def self_test() -> None:
    m = label_metrics([0.9, 0.8, 0.1, 0.2, 0.7, 0.3], ["volatile", "volatile", "range", "range", "range", "volatile"], 0.5)
    assert m["n"] == 6 and m["precision"] == round(2 / 3, 4) and m["recall"] == round(2 / 3, 4) and m["kappa"] is not None
    perfect = label_metrics([0.9, 0.1] * 150, ["volatile", "range"] * 150, 0.5)
    assert perfect["kappa"] == 1.0 and perfect["brier_skill"] > 0.9
    junk = label_metrics([0.5] * 300, ["volatile", "range", "range"] * 100, 0.6)
    assert junk["kappa"] == 0.0 and junk["brier_skill"] <= 0
    g = grade([{"model_id": "a", "state": "checked", **perfect}, {"model_id": "b", "state": "checked", **junk}], 30)
    assert g["verdict"] == "fail" and "b" in g["note"]
    assert grade([{"model_id": "a", "state": "checked", **perfect}], 30)["verdict"] == "pass"
    assert grade([{"model_id": "a", "state": "checked", "n": 10}], 30)["verdict"] == "indeterminate"
    print("SELF-TEST PASS")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--registry-root", default=None)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        import ml_vol_label_replay as R  # noqa: PLC0415
        from ml.manifest import canonical_stage  # noqa: PLC0415
        from ml.registry.model_registry import ModelRegistry  # noqa: PLC0415
        from ml.shadow.factory import DEFAULT_REGISTRY_ROOT  # noqa: PLC0415
        root = Path(a.registry_root or DEFAULT_REGISTRY_ROOT)
        entries = [e for e in ModelRegistry(root).list() if canonical_stage(e.target_deployment_stage) in SERVED_STAGES
                   and "regime" in str(e.model_id)]
        threshold = R.live_threshold()
    except Exception as exc:  # noqa: BLE001  # allow-silent: written as a producer_failed verdict
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
             "population": "vol-head label audit: NEVER MEASURED", "note": f"setup failed: {type(exc).__name__}: {exc}"}
        (out / "verdict.json").write_text(json.dumps(v, indent=2) + "\n")
        return 0
    recs = []
    for e in entries:
        recs.append(head_record(e, registry_root=root, days=a.days, threshold=threshold))
        print(json.dumps({k: recs[-1].get(k) for k in ("model_id", "state", "n", "kappa", "brier_skill", "reason")}), flush=True)
    v = grade(recs, a.days)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str, allow_nan=False) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
