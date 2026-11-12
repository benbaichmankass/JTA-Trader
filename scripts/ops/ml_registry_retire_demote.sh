#!/usr/bin/env bash
# wiring: manual-only - run ON THE TRAINER through the trainer-diag relay (docs/claude/trainer-vm-mode.md section 9.a2)
# by row ML-RETIRE-WAVES-20261111; no schedule consumes it.
#
# Demote retired models from `shadow` to `candidate` in the trainer registry.
# Model ids come ONLY from a committed list file (never free text). Default is a DRY RUN; pass --apply to write.
# Trainer-scope registry writes are autonomous (trainer-vm-mode.md section 3.a); precedent: JC-SA-02 demotion, 2026-09-29.
#
#   bash scripts/ops/ml_registry_retire_demote.sh [--apply] [--list ml/configs/retired/registry-demote-2026-11-11.txt]
#
# Prints, per id: the stage before, the action, and the stage after. A model missing from the registry, or not at
# shadow, is reported and skipped; it is never an error that hides the others. Revert one id with:
#   python3 -m ml promote-stage <id> --new-stage shadow --by claude-trainer --reason "revert retirement"
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
APPLY=0
LIST="ml/configs/retired/registry-demote-2026-11-11.txt"
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --list) shift; LIST="$1" ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
REGISTRY_ROOT="${REGISTRY_ROOT:-./ml/registry-store}"
PY="${PY:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
echo "registry_root=${REGISTRY_ROOT} list=${LIST} apply=${APPLY} git_head=$(git rev-parse --short HEAD 2>/dev/null)"
[ -f "$LIST" ] || { echo "list file missing: $LIST"; exit 3; }
APPLY="$APPLY" REGISTRY_ROOT="$REGISTRY_ROOT" LIST="$LIST" "$PY" - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from ml.manifest import canonical_stage
from ml.registry.model_registry import ModelRegistry
reg = ModelRegistry(Path(os.environ["REGISTRY_ROOT"]))
apply = os.environ["APPLY"] == "1"
ids = [l.strip() for l in open(os.environ["LIST"]) if l.strip() and not l.lstrip().startswith("#")]
counts = {"demoted": 0, "would_demote": 0, "skipped": 0, "missing": 0, "failed": 0}
for mid in ids:
    try:
        cur = canonical_stage(reg.get(mid).target_deployment_stage)
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"{mid}: MISSING ({exc})"); counts["missing"] += 1; continue
    if cur != "shadow":
        print(f"{mid}: stage {cur} -> skip (only shadow is demoted)"); counts["skipped"] += 1; continue
    if not apply:
        print(f"{mid}: stage shadow -> WOULD demote to candidate (dry run)"); counts["would_demote"] += 1; continue
    try:
        e = reg.promote_stage(mid, "candidate", by="claude-trainer",
                              reason="ML-RETIRE-WAVES-20261111: operator 2026-11-11 Thursday-planning a2 "
                                     "'Accept as proposed' retires this model (manifest in ml/configs/retired/)")
        print(f"{mid}: shadow -> {e.target_deployment_stage} DONE"); counts["demoted"] += 1
    except Exception as exc:  # noqa: BLE001
        print(f"{mid}: FAILED ({exc})"); counts["failed"] += 1
print("summary:", counts, "of", len(ids))
sys.exit(1 if counts["failed"] else 0)
PY
