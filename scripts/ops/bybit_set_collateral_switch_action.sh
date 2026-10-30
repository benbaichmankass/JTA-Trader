#!/usr/bin/env bash
# system-action wrapper: read — and with apply, SET — a coin's collateral switch on a
# Bybit DEMO account. Report-only (dry-run) by default.
#
# Runs scripts/ops/bybit_set_collateral_switch.py on the live VM. The script refuses
# any account that is not exchange: bybit + demo: true + account_class: paper.
# Prints no dollar figures (the issue comment is public) — read the before/after
# margin via diag_fetch 'broker_account_status?account_id=<id>'.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID              - account_id in accounts.yaml (e.g. bybit_1)   [required]
#   ACTION_COIN             - BTC | ETH                                     [required]
#   ACTION_COLLATERAL_SWITCH- ON | OFF                                      [required]
#   ACTION_CONFIRM_ACCOUNT  - must equal ACCOUNT_ID for apply               [apply only]
#   ACTION_APPLY            - "true" to execute; anything else = dry-run    [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"  # sets REPO_DIR

cd "${REPO_DIR}"
load_runtime_secrets

ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required}"
ACTION_COIN="${ACTION_COIN:?ACTION_COIN required}"
ACTION_COLLATERAL_SWITCH="${ACTION_COLLATERAL_SWITCH:?ACTION_COLLATERAL_SWITCH required}"
ACTION_CONFIRM_ACCOUNT="${ACTION_CONFIRM_ACCOUNT:-}"
ACTION_APPLY="${ACTION_APPLY:-}"

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--account "${ACCOUNT_ID}" --coin "${ACTION_COIN}" --switch "${ACTION_COLLATERAL_SWITCH}")
[ -n "${ACTION_CONFIRM_ACCOUNT}" ] && ARGS+=(--confirm-account "${ACTION_CONFIRM_ACCOUNT}")

case "${ACTION_APPLY}" in
  true|True)
    echo ">>> set-bybit-collateral-switch: APPLY — ${ACCOUNT_ID} ${ACTION_COIN} -> ${ACTION_COLLATERAL_SWITCH}"
    ARGS+=(--apply)
    ;;
  *)
    echo ">>> set-bybit-collateral-switch: DRY-RUN for ${ACCOUNT_ID} ${ACTION_COIN} (set apply: true to execute)"
    ;;
esac

exec "${PY}" scripts/ops/bybit_set_collateral_switch.py "${ARGS[@]}"
