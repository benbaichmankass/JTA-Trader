#!/usr/bin/env bash
# system-action wrapper: DESK-18B judging run (action: run-desk-judge). TIER 2 -- SPENDS ANTHROPIC API MONEY.
#
# Runs scripts/ops/desk_judge_run.py on the live VM, the only place ANTHROPIC_API_KEY exists (.env, the same key
# src/runtime/insights/generator.py reads). It builds the masked packets of the REGISTERED schedule (seed 20261026),
# judges them with scripts/research/desk_judge_api.py (one stateless API call per packet, hard --max-usd), merges and
# runs the driver's `intake`, and prints the per-call ledger, the dollars spent and the intake summary.
#
# DRY-RUN by default: builds packets, prints the worst-case estimate, exits before any API call. Spends only when
# ACTION_APPLY is true. Refuses to start without ACTION_JUDGE_MAX_USD. Touches no service, config or order path.
#
# Env (passed by system-actions.yml):
#   ACTION_JUDGE_N        - packets to judge in this dispatch                       [required]
#   ACTION_JUDGE_OFFSET   - schedule index of the first packet (0, 200, ...)        [required]
#   ACTION_JUDGE_MAX_USD  - hard dollar cap for THIS dispatch                       [required]
#   ACTION_APPLY          - "true" to spend; anything else = dry-run                [optional]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"  # sets REPO_DIR (canonical /home/ubuntu/ict-trading-bot)

cd "${REPO_DIR}"

# The key rides in the environment only; it is never echoed (no `set -x`, no env dump).
load_runtime_secrets

ACTION_JUDGE_N="${ACTION_JUDGE_N:?ACTION_JUDGE_N required}"
ACTION_JUDGE_OFFSET="${ACTION_JUDGE_OFFSET:?ACTION_JUDGE_OFFSET required}"
ACTION_JUDGE_MAX_USD="${ACTION_JUDGE_MAX_USD:?ACTION_JUDGE_MAX_USD required (a judging run never starts without a cap)}"
ACTION_APPLY="${ACTION_APPLY:-}"

PY="${REPO_DIR}/.venv/bin/python3"
[ -x "${PY}" ] || PY="python3"

ARGS=(--n "${ACTION_JUDGE_N}" --offset "${ACTION_JUDGE_OFFSET}" --max-usd "${ACTION_JUDGE_MAX_USD}" --repo-dir "${REPO_DIR}" --python "${PY}")
case "${ACTION_APPLY}" in
  true|True) ARGS+=(--apply) ;;
  *) echo ">>> run-desk-judge: DRY-RUN (set apply: true to spend up to the cap)" ;;
esac

export PYTHONUNBUFFERED=1
exec "${PY}" "${REPO_DIR}/scripts/ops/desk_judge_run.py" "${ARGS[@]}"
