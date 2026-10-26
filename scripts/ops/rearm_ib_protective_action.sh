#!/usr/bin/env bash
# system-action wrapper: re-arm BOTH brackets (stop + TP, one OCA group) on a
# FULLY NAKED IB position, at the journal row's declared levels, sized to the
# live broker qty. Refuses if ANY order rests on the symbol.
#
# DRY-RUN unless ACTION_APPLY is true.
#
# Env (passed by system-actions.yml):
#   ACCOUNT_ID    - account_id in accounts.yaml (e.g. ib_paper)  [required]
#   ACTION_SYMBOL - bot symbol (e.g. MGC)                        [required]
#   ACTION_ROW    - the open journal trade id                    [required]
#   ACTION_APPLY  - "true" to execute; anything else = dry-run   [optional]
#   ACTION_ALLOW_UNVERIFIED_MARK - "true" waives the mark-straddle read [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

cd "${REPO_DIR}"
load_runtime_secrets
export IB_PROBE_TIMEOUT_S="${IB_PROBE_TIMEOUT_S:-0}"

ACCOUNT_ID="${ACCOUNT_ID:?ACCOUNT_ID required}"
ACTION_SYMBOL="${ACTION_SYMBOL:?ACTION_SYMBOL required}"
ACTION_ROW="${ACTION_ROW:?ACTION_ROW required (the open journal trade id)}"
ACTION_APPLY="${ACTION_APPLY:-}"

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--account "${ACCOUNT_ID}" --symbol "${ACTION_SYMBOL}" --row "${ACTION_ROW}")
case "${ACTION_ALLOW_UNVERIFIED_MARK:-}" in
  true|True)
    echo ">>> rearm-ib-protective: allow_unverified_mark WAIVED (mark-straddle check skipped if the mark is unreadable)"
    ARGS+=(--allow-unverified-mark) ;;
esac
case "${ACTION_APPLY}" in
  true|True)
    echo ">>> rearm-ib-protective: APPLY — arming journal SL+TP on ${ACCOUNT_ID}/${ACTION_SYMBOL} row ${ACTION_ROW}"
    ARGS+=(--apply) ;;
  *)
    echo ">>> rearm-ib-protective: DRY-RUN (set apply: true to execute) for ${ACCOUNT_ID}/${ACTION_SYMBOL} row ${ACTION_ROW}" ;;
esac

exec "${PY}" scripts/ops/rearm_ib_protective.py "${ARGS[@]}"
