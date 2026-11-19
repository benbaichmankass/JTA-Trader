#!/usr/bin/env python3
"""P1 iteration 3, step 1: read the meta-label head's DECISION THRESHOLD on its TRAINING side only.

WHY (RQ-20261119-3e98-01 INDETERMINATE, PI-20261119-RIMARY12-0006). On the measured paper book the head kept its
selection signal (it beats take-all and take-none) but took only 30 of 698 rows, under the P1 take-rate floor of 0.05,
at the manifest's threshold 0.5, which was never read on any data. Choosing the threshold on the paper book itself
would leak the eval rows into the decision. So the threshold is read here on WALK-FORWARD OUT-OF-FOLD scores of the
TRAINING population only (the manifest's live_holdout train side: every row whose live flag is not the eval value),
and the eval book is touched once, later, at the threshold this picks.

WHAT IT DOES
  * train side = ``ml.experiments.splitters.split_live_holdout`` train rows (the exact split ``ml train`` used);
  * ``split_walk_forward`` folds on them (n_folds, min_train_fraction; time-ordered, expanding);
  * per fold: the manifest's trainer fit on the fold's train block (``trainer_config`` unchanged), scored on the next
    block with the evaluator's own predictor resolution (``Evaluator._resolve_predictor``), so a score here is what
    the served head would emit;
  * for every threshold on the grid: OOF take rate and value_r = sum(R of taken rows) / n (R = the manifest's value
    column, ``cost_gate.value_column_for``), exactly the P1 (a) statistic;
  * SELECTION RULE (registered in the unit before the run): among grid thresholds whose OOF take rate is within
    [take_min, take_max], the one with the highest OOF value_r; a tie goes to the threshold closest to the manifest's
    current one. No eligible threshold -> ``selected: null`` (the caller must not grade).

Writes one JSON record. No model is saved, registered or served; no config is written.

    python3 scripts/ml/p1_threshold_oof.py --manifest M.yaml --dataset data.jsonl --out thr.json
    python3 scripts/ml/p1_threshold_oof.py --self-test
"""
# wiring: manual-only — the P1 iteration-3 trainer relay (RQ-20261119-2780-04) runs it before p1_costnet_grade.py.
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_GRID = [round(0.30 + 0.02 * i, 2) for i in range(21)]   # 0.30 .. 0.70


def grid_table(oof: list[tuple[float, float]], grid: list[float]) -> list[dict[str, Any]]:
    """Per threshold: n, n_taken, take_rate, value_r (sum taken R / n), take_all_r, matched_random_r."""
    n = len(oof)
    take_all = (sum(r for _, r in oof) / n) if n else None
    out = []
    for t in grid:
        taken = [r for s, r in oof if s >= t]
        tr = len(taken) / n if n else None
        out.append({"threshold": t, "n": n, "n_taken": len(taken), "take_rate": tr,
                    "value_r": (sum(taken) / n) if n else None, "take_all_r": take_all,
                    "matched_random_r": (tr * take_all) if (n and take_all is not None) else None})
    return out


def select(table: list[dict[str, Any]], take_min: float, take_max: float, current: float) -> dict[str, Any] | None:
    """The registered rule: highest OOF value_r among thresholds with take_min <= take_rate <= take_max;
    ties -> closest to ``current``. None when no threshold is eligible."""
    ok = [r for r in table if r["take_rate"] is not None and take_min <= r["take_rate"] <= take_max
          and r["value_r"] is not None]
    if not ok:
        return None
    best = max(r["value_r"] for r in ok)
    tied = [r for r in ok if abs(r["value_r"] - best) <= 1e-12]
    return min(tied, key=lambda r: (abs(r["threshold"] - current), r["threshold"]))


def oof_scores(train_rows: list[dict], trainer_cls, trainer_config: dict, value_col: str,
               wf_config: dict) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    from ml.evaluators.base import Evaluator
    from ml.experiments.splitters import split_walk_forward
    folds = split_walk_forward(train_rows, wf_config)
    oof: list[tuple[float, float]] = []
    meta = []
    for i, (tr, te) in enumerate(folds):
        state = trainer_cls().fit(tr, trainer_config)
        pred = Evaluator._resolve_predictor(state)
        k = 0
        for row in te:
            v = row.get(value_col)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            # provenance: predict — the head's score on an out-of-fold training row
            oof.append((float(pred.predict(row)), float(v)))
            k += 1
        meta.append({"fold": i, "n_train": len(tr), "n_test": len(te), "n_scored": k})
    return oof, meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest")
    ap.add_argument("--dataset", help="data.jsonl the manifest trains on")
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--min-train-fraction", type=float, default=0.5)
    ap.add_argument("--take-min", type=float, default=0.05)
    ap.add_argument("--take-max", type=float, default=0.60)
    ap.add_argument("--grid", default=",".join(str(x) for x in DEFAULT_GRID))
    ap.add_argument("--unit", default=None)
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.manifest and a.dataset and a.out):
        ap.error("--manifest, --dataset and --out are required")
    import importlib

    import yaml
    from ml.experiments.splitters import split_live_holdout
    from ml.promotion import cost_gate as cg

    man = yaml.safe_load(Path(a.manifest).read_text())

    class _M:  # minimal duck for cg.value_column_for / decision_threshold (as p1_costnet_grade.py)
        evaluator_config = man.get("evaluator_config") or {}
        trainer_config = man.get("trainer_config") or {}

        class dataset:  # noqa: N801
            family = (man.get("dataset") or {}).get("family")

    vcol = cg.value_column_for(_M)
    current = cg.decision_threshold(_M, vcol)
    mod, _, attr = str(man["trainer"]).rpartition(".")
    trainer_cls = getattr(importlib.import_module(mod), attr)
    rows = [json.loads(ln) for ln in open(a.dataset, encoding="utf-8") if ln.strip()]
    ecfg = dict(man.get("evaluator_config") or {})
    train, evaluation = split_live_holdout(rows, ecfg)
    wf = {"n_folds": a.n_folds, "min_train_fraction": a.min_train_fraction,
          "time_column": ecfg.get("time_column", "created_at")}
    oof, meta = oof_scores(train, trainer_cls, dict(man.get("trainer_config") or {}), vcol, wf)
    grid = [float(x) for x in a.grid.split(",") if x.strip()]
    table = grid_table(oof, grid)
    sel = select(table, a.take_min, a.take_max, current)
    rec = {
        "schema_version": 1, "research_unit": a.unit, "tool": "scripts/ml/p1_threshold_oof.py",
        "model_id": man.get("model_id"), "dataset": a.dataset, "dataset_rows": len(rows),
        "population": (f"TRAINING side only (live_holdout train: {len(train)} rows; the {len(evaluation)} eval rows are never "
                       f"read), {a.n_folds}-fold expanding walk-forward from {a.min_train_fraction:.2f}, OOF scores on {len(oof)} rows"),
        "read_state": "measured" if oof else "producer_failed",
        "value_column": vcol, "current_threshold": current,
        "rule": {"take_min": a.take_min, "take_max": a.take_max,
                 "select": "max OOF value_r among eligible thresholds; tie -> closest to current_threshold"},
        "folds": meta, "grid": table, "selected": sel,
        "selected_threshold": None if sel is None else sel["threshold"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    Path(a.out).write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("read_state", "current_threshold", "selected_threshold", "population")}))
    return 0 if oof else 2


def _self_test() -> int:
    oof = [(0.9, 1.0), (0.8, 0.5), (0.6, -0.2), (0.4, -1.0), (0.2, -1.0), (0.7, 0.3), (0.55, -0.5), (0.35, 0.1)]
    t = grid_table(oof, [0.3, 0.5, 0.65, 0.85])
    assert [r["n_taken"] for r in t] == [7, 5, 3, 1], t
    assert abs(t[2]["value_r"] - (1.0 + 0.5 + 0.3) / 8) < 1e-12
    s = select(t, 0.05, 0.60, 0.5)
    assert s is not None and s["threshold"] == 0.65, s   # 0.85 takes 1/8 (eligible), value 0.125 < 0.225
    assert select(t, 0.95, 1.0, 0.5) is None, "no threshold in the take band -> None"
    tie = [{"threshold": 0.4, "take_rate": 0.3, "value_r": 0.1}, {"threshold": 0.56, "take_rate": 0.2, "value_r": 0.1}]
    assert select(tie, 0.05, 0.6, 0.5)["threshold"] == 0.56, "tie goes to the threshold closest to the current one"
    print("p1_threshold_oof self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
