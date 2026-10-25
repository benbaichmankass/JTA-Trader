#!/usr/bin/env bash
# system-action wrapper: TIGHTEN one live Bybit position's stop-loss — venue
# stop AND journal (order_packages.sl + trades.stop_loss) together, so the
# order monitor's trail keeps it (AMEND-SL-ACTION, operator 2026-10-24).
#
# Runs scripts/ops/amend_position_sl.py on the live VM. DRY-RUN by default;
# only amends when ACTION_APPLY is true. Refuses a looser stop, a stop on the
# wrong side of the mark (unless ACTION_ALLOW_IMMEDIATE=true), a missing
# trade/package/position, and a non-live or non-Bybit account.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID             - account_id in accounts.yaml (e.g. bybit_2)       [required]
#   ACTION_NEW_SL          - the new (tighter) stop price                      [required]
#   ACTION_REASON          - why (written to trades.notes as provenance)       [required]
#   TRADE_ID               - journal trade id                                  [this, or SYMBOL+SIDE]
#   ACTION_SYMBOL          - bot symbol (e.g. ADAUSDT)                         [with ACTION_SIDE]
#   ACTION_SIDE            - long | short                                      [with ACTION_SYMBOL]
#   ACTION_APPLY           - "true" to execute; anything else = dry-run        [optional]
#   ACTION_ALLOW_IMMEDIATE - "true" to allow a stop through the mark           [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"  # sets REPO_DIR (canonical /home/ubuntu/ict-trading-bot)

cd "${REPO_DIR}"

# Inherit the live trader's runtime env (.env): Bybit creds so this one-shot
# ops client authenticates exactly like ict-trader-live.service does.
load_runtime_secrets

ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required}"
ACTION_NEW_SL="${ACTION_NEW_SL:?ACTION_NEW_SL required}"
ACTION_REASON="${ACTION_REASON:?ACTION_REASON required}"
TRADE_ID="${TRADE_ID:-}"
ACTION_SYMBOL="${ACTION_SYMBOL:-}"
ACTION_SIDE="${ACTION_SIDE:-}"
ACTION_APPLY="${ACTION_APPLY:-}"
ACTION_ALLOW_IMMEDIATE="${ACTION_ALLOW_IMMEDIATE:-}"

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--account "${ACCOUNT_ID}" --new-sl "${ACTION_NEW_SL}" --reason "${ACTION_REASON}")
if [ -n "${TRADE_ID}" ]; then
  ARGS+=(--trade-id "${TRADE_ID}")
else
  ARGS+=(--symbol "${ACTION_SYMBOL}" --side "${ACTION_SIDE}")
fi
case "${ACTION_ALLOW_IMMEDIATE}" in
  true|True) ARGS+=(--allow-immediate) ;;
esac
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> amend-position-sl: APPLY mode — tightening ${ACCOUNT_ID} stop to ${ACTION_NEW_SL}"
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> amend-position-sl: DRY-RUN (set apply: true to execute) for ${ACCOUNT_ID} → ${ACTION_NEW_SL}"
    ;;
esac

exec "${PY}" scripts/ops/amend_position_sl.py "${ARGS[@]}"
