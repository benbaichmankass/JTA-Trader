#!/usr/bin/env bash
# system-action wrapper (Tier 2): prune OLD trade_journal.db backups.
#
# PI-20261017-VSMHZYHF-0001: about ten Tier-2 writeback helpers copy the whole
# journal (2.09 GB on 2026-10-17) to <db>.bak-<what>-<stamp> before writing,
# and nothing ever removes them; on a 45 G root disk shared with the live DB
# that is how the disk reached 96%.
#
# Candidates: files next to the live DB named <db>.bak-* or <db>.*-bak-*,
# older than RETAIN_DAYS (mtime), excluding the newest KEEP of them. NEVER the
# live DB, its -wal/-shm, or anything newer than RETAIN_DAYS. DRY-RUN by
# default: prints the plan and the bytes it would free; ACTION_APPLY=true
# deletes exactly the planned list and prints df before/after.
#
# Env (passed by system-actions.yml):
#   ACTION_APPLY  - "true" to delete; else dry-run
#   ACTION_DAYS   - retention in days (default 7; 0 = age is no protection, keep still applies)
#   ACTION_KEEP   - always keep this many newest backups (default 2, minimum 1)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

DB_PATH="$(runtime_db_path)"
RETAIN_DAYS="${ACTION_DAYS:-7}"
KEEP="${ACTION_KEEP:-2}"
case "${KEEP}" in ''|*[!0-9]*) echo "ERROR: keep must be a whole number (got '${KEEP}')"; exit 2 ;; esac
if [ "${KEEP}" -lt 1 ]; then echo "ERROR: keep must be >= 1 (the newest backup is never pruned)"; exit 2; fi
case "${RETAIN_DAYS}" in ''|*[!0-9]*) echo "ERROR: days must be a whole number (got '${RETAIN_DAYS}')"; exit 2 ;; esac

echo ">>> live DB: ${DB_PATH} (never touched)"
echo ">>> retention: older than ${RETAIN_DAYS} day(s), always keep the newest ${KEEP} backups"
df -h "$(dirname "${DB_PATH}")" || true

shopt -s nullglob
mapfile -t all < <(for f in "${DB_PATH}".bak-* "${DB_PATH}".*-bak-*; do
    case "${f}" in "${DB_PATH}"|"${DB_PATH}-wal"|"${DB_PATH}-shm") continue ;; esac
    [ -f "${f}" ] && printf '%s\t%s\n' "$(stat -c %Y "${f}")" "${f}"
done | sort -rn | awk -F'\t' '!seen[$2]++')

cutoff=$(( $(date +%s) - RETAIN_DAYS * 86400 ))
plan=()
i=0
for line in "${all[@]}"; do
    mtime="${line%%$'\t'*}"; f="${line#*$'\t'}"
    i=$((i + 1))
    age_d=$(( ($(date +%s) - mtime) / 86400 ))
    if [ "${i}" -le "${KEEP}" ] || [ "${mtime}" -ge "${cutoff}" ]; then
        printf '  KEEP   %3sd  %s\n' "${age_d}" "${f}"
    else
        printf '  DELETE %3sd  %s\n' "${age_d}" "${f}"
        plan+=( "${f}" )
    fi
done
echo "backups found: ${#all[@]}; planned deletions: ${#plan[@]}"
if [ "${#plan[@]}" -gt 0 ]; then
    printf 'would free: '; du -ch "${plan[@]}" | tail -1
fi

case "${ACTION_APPLY:-}" in
  true|True) ;;
  *) echo ">>> DRY-RUN (set apply: true to delete the DELETE lines above)."; exit 0 ;;
esac
for f in "${plan[@]}"; do
    case "${f}" in "${DB_PATH}"|"${DB_PATH}-wal"|"${DB_PATH}-shm") echo "REFUSED: ${f}"; exit 3 ;; esac
    rm -f -- "${f}" && echo "  deleted ${f}"
done
record_audit "prune-db-backups" "ok" "{\"deleted\": ${#plan[@]}, \"retain_days\": ${RETAIN_DAYS}}" >/dev/null || true
df -h "$(dirname "${DB_PATH}")" || true
