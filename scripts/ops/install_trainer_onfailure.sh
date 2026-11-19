#!/usr/bin/env bash
# wiring: manual-only - run once on the TRAINER VM through trainer-vm-diag (sudo); idempotent.
# scripts/ops/install_trainer_onfailure.sh: give every timer-driven trainer oneshot an OnFailure alert.
#
# PI-20261004-GCFA5DOR-0010 (a): trainer-diag #27026 found 13 of 14 trainer units with no OnFailure. The
# 14th (ict-keeper-dispatch) named a template that was not installed. This installs:
#   * deploy/trainer/ict-notify-failure@.service -> /etc/systemd/system/ict-notify-failure@.service
#     (the trainer template forwards the ping to the live VM's queue);
#   * deploy/dropins/onfailure.conf -> /etc/systemd/system/<unit>.service.d/onfailure.conf for each
#     deploy/trainer/<unit>.timer whose <unit>.service is Type=oneshot and installed on this host.
# It changes no ExecStart and restarts nothing; units pick up the drop-in on daemon-reload.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "ERROR: must run as root (use sudo)" >&2; exit 2; }
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
install -m 0644 -o root -g root "$REPO/deploy/trainer/ict-notify-failure@.service" "$SYSTEMD_DIR/ict-notify-failure@.service"
covered=0; skipped=0
for t in "$REPO"/deploy/trainer/*.timer; do
  base="$(basename "$t" .timer)"
  svc="$SYSTEMD_DIR/${base}.service"
  if [ ! -f "$svc" ]; then echo "skip ${base}: service not installed on this host"; skipped=$((skipped+1)); continue; fi
  if ! grep -qE '^Type=oneshot' "$svc"; then echo "skip ${base}: not Type=oneshot"; skipped=$((skipped+1)); continue; fi
  install -d -m 0755 "$SYSTEMD_DIR/${base}.service.d"
  install -m 0644 -o root -g root "$REPO/deploy/dropins/onfailure.conf" "$SYSTEMD_DIR/${base}.service.d/onfailure.conf"
  echo "dropin ${base}.service.d/onfailure.conf"; covered=$((covered+1))
done
systemctl daemon-reload
echo "== coverage: ${covered} unit(s) covered, ${skipped} skipped"
for t in "$REPO"/deploy/trainer/*.timer; do
  u="$(basename "$t" .timer).service"; printf '%s OnFailure=%s\n' "$u" "$(systemctl show -p OnFailure --value "$u" 2>/dev/null)"
done
