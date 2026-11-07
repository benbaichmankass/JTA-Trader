#!/usr/bin/env bash
# scripts/ops/install_trainer_lifecycle_units.sh — install + enable the per-model lifecycle scheduler timer on the trainer VM.
# Operator OK 2026-11-07 (relayed by Manager Session 2026-11-07a; work row ML-LIFECYCLE-SCHEDULE).
# Dispatch (trainer-vm-diag relay):  cd /home/ubuntu/ict-trading-bot && git pull --ff-only origin main && sudo bash scripts/ops/install_trainer_lifecycle_units.sh
# Idempotent. REVERT: sudo systemctl disable --now ict-trainer-lifecycle.timer && sudo rm /etc/systemd/system/ict-trainer-lifecycle.{service,timer} && sudo systemctl daemon-reload
# Does not touch ict-trainer.service/.timer, any strategy, config or order path.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "ERROR: must run as root (use sudo)" >&2; exit 2; }
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/ict-trading-bot}"
for u in service timer; do
  install -m 0644 "$REPO_ROOT/deploy/trainer/ict-trainer-lifecycle.$u" "/etc/systemd/system/ict-trainer-lifecycle.$u"
done
systemctl daemon-reload || exit 1
systemctl enable --now ict-trainer-lifecycle.timer
echo "timer: $(systemctl is-enabled ict-trainer-lifecycle.timer) / $(systemctl is-active ict-trainer-lifecycle.timer)"
systemctl list-timers ict-trainer-lifecycle.timer --no-pager | head -3
