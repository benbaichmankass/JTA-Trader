#!/usr/bin/env python3
"""Registry-wide feature-presence pre-flight of every SERVED ML head (stage shadow / advisory), weekly on the trainer.

Row TRAINER-LIGHT-READS (manager 2026-11-26: the trainer does not stay idle; standing light work). For each registry entry at
a served stage, the head's predictor is instantiated exactly as the shadow scorer does (ml.shadow.backfill._instantiate_predictor),
its dataset is the manifest's ``datasets-out/<family>/<symbol>/<tf>/<version>/data.jsonl``, and the LAST ``--tail-rows`` rows
(streamed, projected to the head's own feature columns, so memory stays flat) go through
``ml_vol_label_replay.audit_feature_rows`` -- the pre-flight that catches the two SILENT degradations of
``ml/predictors/lightgbm.py::_encode_row`` (a missing numeric becomes NaN, an unseen categorical becomes -1) plus, for regime
heads, vol_bucket parity against the head's frozen edges.

Per head: ``features_ok`` = no feature column missing/null in the tail AND no unseen categorical value; ``parity`` is reported
separately (only regime heads have one). A head that cannot be checked (no dataset, unreadable entry, instantiate error) is
``could_not_check`` with the reason -- never counted clean, never stopping the sweep (per-item containment, no halting).

Verdict (script_run contract): fail = >= 1 checked head has features_ok false (named); pass = every head checked and
features_ok; indeterminate = no head could be checked. Read-only: reads the registry + datasets, writes only under --out.
"""
from __future__ import annotations

import argparse
import collections
import gc
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "scripts" / "research"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SERVED_STAGES = ("shadow", "advisory")


def dataset_path_for(manifest: Dict[str, Any], root: Path = REPO) -> Optional[Path]:
    ds = (manifest or {}).get("dataset") or {}
    parts = [ds.get(k) for k in ("family", "symbol_scope", "timeframe", "version")]
    if not all(parts):
        return None
    return root / "datasets-out" / "/".join(str(x) for x in parts) / "data.jsonl"


def tail_rows(path: Path, keep: List[str], n: int) -> List[Dict[str, Any]]:
    """The last ``n`` rows of a JSONL dataset, streamed and projected to ``keep`` (+ ts); memory = n projected rows."""
    import ml_vol_label_replay as R  # noqa: PLC0415
    buf: collections.deque = collections.deque(maxlen=max(1, int(n)))
    for row in R.iter_projected_rows(path, keep):
        buf.append(row)
    return list(buf)


def head_record(entry: Any, *, registry_root: Path, tail: int, data_root: Path = REPO) -> Dict[str, Any]:
    import ml_vol_label_replay as R  # noqa: PLC0415
    from ml.manifest import canonical_stage  # noqa: PLC0415
    rec: Dict[str, Any] = {"model_id": entry.model_id, "stage": canonical_stage(entry.target_deployment_stage)}
    path = dataset_path_for(dict(entry.manifest or {}), data_root)
    rec["dataset"] = str(path.relative_to(data_root)) if path else None
    if path is None:
        return {**rec, "state": "could_not_check", "reason": "manifest names no complete dataset block"}
    if not path.is_file():
        return {**rec, "state": "could_not_check", "reason": f"dataset not present: {rec['dataset']}"}
    try:
        from ml.shadow.backfill import _instantiate_predictor  # noqa: PLC0415,PLC2701
        predictor = _instantiate_predictor(entry, registry_root=registry_root)
        base = R._unwrap(predictor)  # noqa: SLF001
        cols = list(getattr(base, "_feature_columns", []) or [])
        spec = getattr(predictor, "regime_spec", None) or getattr(base, "regime_spec", None) or {}
        keep = cols + [c for c in (spec.get("vol_feature_column"), spec.get("feature_column") or "vol_bucket") if c]
        rows = tail_rows(path, keep, tail)
        rep = R.audit_feature_rows(predictor, rows)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded per head as could_not_check, the sweep continues
        return {**rec, "state": "could_not_check", "reason": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        gc.collect()
    missing = rep.get("missing_or_null_by_column") or {}
    unseen = rep.get("unseen_categorical_values") or rep.get("unseen_categorical") or {}
    parity = rep.get("vol_bucket_parity") or rep.get("parity") or {}
    return {**rec, "state": "checked", "features_ok": not missing and not unseen, "n_features": len(cols),
            "rows_checked": rep.get("rows_checked"), "missing_or_null_by_column": missing, "unseen_categorical": unseen,
            "parity_status": parity.get("status"), "parity_mismatch_pct": parity.get("mismatch_pct"),
            "last_ts": (rows[-1].get("ts") if rows else None)}


def grade(recs: List[Dict[str, Any]], registry_root: str) -> Dict[str, Any]:
    checked = [r for r in recs if r["state"] == "checked"]
    bad = [r["model_id"] for r in checked if not r["features_ok"]]
    skipped = [r["model_id"] for r in recs if r["state"] != "checked"]
    if not checked:
        v, note = "indeterminate", "no served head could be checked"
    elif bad:
        v, note = "fail", f"{len(bad)} served head(s) would be scored on a degraded row: {bad}"
    else:
        v, note = "pass", f"all {len(checked)} checked served heads see every feature column, no unseen categorical"
    if skipped:
        note += f" | could_not_check {len(skipped)}: {skipped}"
    return {"verdict": v, "read_state": "measured" if checked else "no_data", "n": len(checked),
            "population": f"registry {registry_root}: {len(recs)} entries at stage {'/'.join(SERVED_STAGES)}; "
                          f"{len(checked)} checked on their manifest dataset's tail rows",
            "note": note, "records": recs}


def self_test() -> None:
    m = {"dataset": {"family": "market_features", "symbol_scope": "BTCUSDT", "timeframe": "15m", "version": "v002"}}
    assert dataset_path_for(m, Path("/r")) == Path("/r/datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl")
    assert dataset_path_for({"dataset": {"family": "x"}}) is None
    ok = {"model_id": "a", "state": "checked", "features_ok": True}
    badr = {"model_id": "b", "state": "checked", "features_ok": False}
    skip = {"model_id": "c", "state": "could_not_check", "reason": "x"}
    assert grade([ok, skip], "r")["verdict"] == "pass"
    g = grade([ok, badr], "r")
    assert g["verdict"] == "fail" and "b" in g["note"]
    assert grade([skip], "r")["verdict"] == "indeterminate"
    print("SELF-TEST PASS")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--registry-root", default=None)
    ap.add_argument("--tail-rows", type=int, default=2000)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        from ml.manifest import canonical_stage  # noqa: PLC0415
        from ml.registry.model_registry import ModelRegistry  # noqa: PLC0415
        from ml.shadow.factory import DEFAULT_REGISTRY_ROOT  # noqa: PLC0415
        root = Path(a.registry_root or DEFAULT_REGISTRY_ROOT)
        entries = [e for e in ModelRegistry(root).list() if canonical_stage(e.target_deployment_stage) in SERVED_STAGES]
    except Exception as exc:  # noqa: BLE001  # allow-silent: written as a producer_failed verdict
        v = {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
             "population": "registry feature pre-flight: NEVER MEASURED", "note": f"registry unreadable: {type(exc).__name__}: {exc}"}
        (out / "verdict.json").write_text(json.dumps(v, indent=2) + "\n")
        return 0
    recs = []
    for e in entries:
        recs.append(head_record(e, registry_root=root, tail=a.tail_rows))
        print(json.dumps({k: recs[-1].get(k) for k in ("model_id", "stage", "state", "features_ok", "reason")}), flush=True)
    v = grade(recs, str(root))
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str, allow_nan=False) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
