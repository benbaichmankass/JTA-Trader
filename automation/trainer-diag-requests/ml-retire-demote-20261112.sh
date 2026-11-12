#!/usr/bin/env bash
# ML-RETIRE-WAVES-20261111 step 2 (operator 2026-11-11 Thursday-planning a2 "Accept as proposed"; manager all-clear 01:52Z).
# Trainer-scope registry write (docs/claude/trainer-vm-mode.md 3.a): demote the 4 wave-2 retirees shadow -> candidate.
set -uo pipefail
cd /home/ubuntu/ict-trading-bot || exit 4
echo "checkout_head: $(git log -1 --oneline)"
S=scripts/ops/ml_registry_retire_demote.sh
L=ml/configs/retired/registry-demote-2026-11-11.txt
if [ ! -f "$S" ] || [ ! -f "$L" ]; then
  echo "script not yet synced to this checkout; fetching origin/main copies (run takes seconds, inside one sync window)"
  git fetch -q origin main && git checkout origin/main -- "$S" "$L" || { echo "could not fetch the script"; exit 5; }
fi
echo "=== DRY RUN ==="
bash "$S" || exit 6
echo "=== APPLY ==="
bash "$S" --apply
rc=$?
echo "=== RE-READ (expect all skipped: not at shadow) ==="
bash "$S"
exit $rc
