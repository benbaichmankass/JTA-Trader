#!/usr/bin/env python3
"""Seed ml/lifecycle/plans/<stem>.yaml from ml/configs manifests (idempotent; --force rewrites).

Plans are the source of truth once seeded: edit them by hand; re-seeding never overwrites an
existing plan unless --force. Cadence rules (provenance stated per field):
  * MEASURED  1d  — shadow-stage head on the nightly-rebuilt dataset (ict-trainer.timer OnCalendar=daily).
  * ESTIMATED 30d — dataset version pinned (not rebuilt nightly): daily retrain is a byte-identical no-op
    (MB-20260720-FCPCV-RETRAIN-NOOP), so the cadence is a guess.
  * ESTIMATED 7d  — candidate / research_only head (not live-influencing), weekly to match /ml-review.
Retest cadences are ESTIMATED except drift_check on shadow heads (1d, MEASURED: matches the retrain cadence).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "ml" / "lifecycle" / "plans"
PY = "{py}"
CHALLENGERS = {  # challenger -> champion (same head, fresher-data sibling; see manifest headers)
    "btc-regime-15m-lgbm-fc-pcv-v2": "btc-regime-15m-lgbm-fc-pcv-v1",
    "sol-regime-15m-lgbm-fc-pcv-v2": "sol-regime-15m-lgbm-fc-pcv-v1",
}
PIT = {
    "market_features": "bar-close features only; labels use the declared forward horizon; train/eval split is chronological (no shuffling); forecast side-stream rebuilt nightly",
    "conviction_meta": "features at decision time from journal + backtest panels; label from realised outcome net of the full cost stack (config/ml_training.yaml cost_net_labels)",
    "trade_outcomes": "decision-time features; outcome label realised later; backtest augmentation per config/training_population.yaml",
}
WINDOW = {"market_features": "full available history, recency-weighted by the manifest sample_weight",
          "execution_quality": "live closed-trade fills only (backtests do not model slippage)"}


def build(path: Path) -> dict:
    m = yaml.safe_load(path.read_text(encoding="utf-8"))
    stem = path.stem
    d = m["dataset"]
    stage = m.get("target_deployment_stage", "candidate")
    pinned = d["version"] != "v002" and d["family"] == "market_features"
    if stage == "shadow" and not pinned:
        cad, prov = 1, "MEASURED"
    elif pinned:
        cad, prov = 30, "ESTIMATED"
    else:
        cad, prov = 7, "ESTIMATED"
    man = f"ml/configs/{path.name}"
    mdl = ["--model-id", "{model_id}"]
    retest = []
    if stage == "shadow":
        retest.append({"id": "drift_check", "cadence_days": 1, "cadence_provenance": "MEASURED",
                       "what": "score drift (KS+PSI, reference vs current window) -- score drift only, NOT labelled decay",
                       "command": [PY, "-m", "ml", "shadow-drift", *mdl]})
    else:
        retest.append({"id": "drift_check", "cadence_days": 7, "cadence_provenance": "ESTIMATED",
                       "what": "score drift on the shadow log (insufficient_data until the head scores live)",
                       "command": [PY, "-m", "ml", "shadow-drift", *mdl]})
    retest.append({"id": "labelled_decay", "cadence_days": 7, "cadence_provenance": "ESTIMATED",
                   "what": "shadow scores joined to realised outcomes (AUC/Brier vs base rate) -- labelled decay",
                   "command": [PY, "-m", "ml", "model-attribution", "--db", "{journal_db}", *mdl]})
    if d["family"] == "market_features":
        retest.append({"id": "serve_parity", "cadence_days": 7, "cadence_provenance": "ESTIMATED",
                       "what": "training-row vs live-row feature distribution parity",
                       "command": [PY, "scripts/ml/_feature_parity_probe.py", *mdl,
                                   "--symbol", "{symbol}", "--timeframe", "{timeframe}"]})
    if stem in CHALLENGERS:
        retest.append({"id": "champion_challenger", "cadence_days": 7, "cadence_provenance": "ESTIMATED",
                       "what": "registry metric comparison vs the champion sibling (cost-net gate is enforced at registration; a replay-based champion/challenger is a research unit, not this job)",
                       "command": [PY, "-m", "ml", "compare", CHALLENGERS[stem], "{model_id}",
                                   "--registry-root", "{registry_root}"]})
    triggers = [{"kind": "calendar"}]
    if not pinned:
        triggers.append({"kind": "drift", "source_job": "drift_check", "when": "overall_verdict == significant"})
    return {
        "plan_version": 1, "plan_id": stem, "model_id": m["model_id"], "manifest": man,
        "population_basis": "every top-level ml/configs manifest (the nightly-cycle roster; registry stage lives on the trainer VM and can exceed the manifest's declared stage)",
        "manifest_stage_at_seed": stage,
        "datasets": [{"family": d["family"], "symbol_scope": d.get("symbol_scope", "all"),
                      "timeframe": d.get("timeframe", "all"), "version": d["version"],
                      "source": "scripts/ops/build_trainer_datasets.sh (trainer VM, nightly in ict-trainer.service; datasets-out/)",
                      "window": WINDOW.get(d["family"], "full available history"),
                      "point_in_time": PIT.get(d["family"], "decision-time features only; labels realised strictly after the decision")}],
        "retrain": {"cadence_days": cad, "cadence_provenance": prov, "triggers": triggers, "timeout_s": 1800,
                    "command": [PY, "-m", "ml", "train", "{manifest}", "--datasets-root", "{datasets_root}",
                                "--experiments-root", "{experiments_root}", "--registry-root", "{registry_root}"],
                    "note": "backstop to the nightly cycle: due only if neither this scheduler nor a cycle manifest_ok row is inside the cadence"},
        "retest": retest,
        "update": {"cadence_days": 7, "cadence_provenance": "ESTIMATED", "promote_past_shadow": "operator_tier3",
                   "rule": "PROPOSE only: gate-check writes the go/no-go packet; hold if gates fail or data is insufficient; flag for /ml-review when a result changes the verdict. Never calls promote-stage.",
                   "command": [PY, "-m", "ml", "gate-check", "{model_id}", "--registry-root", "{registry_root}"]},
        "reporting": {"results": "runtime_logs/trainer/lifecycle_results.jsonl (one MEASURED record per job)",
                      "state": "runtime_logs/trainer/lifecycle_state.json",
                      "red_flag": "lifecycle_red_flag event in runtime_logs/training_cycle.jsonl after 3 consecutive failures (once per episode; retries continue)",
                      "reviewed_by": "/ml-review layer 1 (python scripts/ops/lifecycle_report.py)"},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted((REPO / "ml" / "configs").glob("*.yaml")):
        o = OUT / p.name
        if o.exists() and not a.force:
            continue
        o.write_text("# Lifecycle plan -- see ml/lifecycle/plan.py for the schema; seeded by scripts/ops/seed_lifecycle_plans.py (2026-11-07).\n"
                     + yaml.safe_dump(build(p), sort_keys=False, width=140), encoding="utf-8")
        n += 1
    print(f"seeded {n} plans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
