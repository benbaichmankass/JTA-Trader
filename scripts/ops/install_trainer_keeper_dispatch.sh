#!/usr/bin/env bash
# wiring: manual-only - run by vm-git-credential-bootstrap.yml (target: trainer, credential: dispatch)
# right after it installs /etc/ict/gh-dispatch.env; a one-shot installer, not a recurring job.
# scripts/ops/install_trainer_keeper_dispatch.sh — install the hourly keeper-dispatch timer on the
# trainer VM (KEEPER-VM-FLOOR). Units are copied from THIS checkout (deploy/trainer/). Idempotent.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "ERROR: must run as root (use sudo)" >&2; exit 2; }
SRC="$(cd "$(dirname "$0")/../.." && pwd)/deploy/trainer"
for u in ict-keeper-dispatch.service ict-keeper-dispatch.timer; do
  [ -f "$SRC/$u" ] || { echo "ERROR: missing $SRC/$u" >&2; exit 1; }
  install -m 0644 -o root -g root "$SRC/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable --now ict-keeper-dispatch.timer
systemctl list-timers ict-keeper-dispatch.timer --no-pager || true
echo "ict-keeper-dispatch timer installed. Run once now: sudo systemctl start ict-keeper-dispatch.service"
