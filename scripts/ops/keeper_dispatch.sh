#!/usr/bin/env bash
# wiring: systemd - deploy/trainer/ict-keeper-dispatch.{service,timer} (trainer VM, hourly).
# scripts/ops/keeper_dispatch.sh — KEEPER-VM-FLOOR (2026-11-01).
#
# WHY: GitHub drops ~77% of this repo's scheduled runs (measured 2026-11-01: 13 of ~56
# schedule events for schedule-keeper.yml in 48h). schedule-keeper.yml is the backstop that
# re-dispatches every dropped schedule, and today it is kept alive only by the stream of bot
# pushes to main, a feedback loop that stalls on a quiet main. This script gives the keeper a
# clock that does not depend on GitHub's scheduler: once an hour the trainer VM asks GitHub
# to run schedule-keeper.yml (workflow_dispatch). The keeper dedupes itself, so an extra run
# is harmless.
#
# TOKEN: GH_DISPATCH_TOKEN, read from /etc/ict/gh-dispatch.env (root:root 0600), installed by
# vm-git-credential-bootstrap.yml (target: trainer, credential: dispatch) from the Actions
# secret BRANCH_PROTECTION_TOKEN (operator 2026-11-01, verbatim "Yes, BRANCH_PROTECTION_TOKEN").
# systemd passes it via EnvironmentFile=. The token is never printed, logged, or put on a
# command line: curl reads its auth header from stdin.
#
# BEHAVIOUR (never halts a pipeline; one flag, not a loop):
#   * env file / token missing -> one log line, exit 0 (inert until installed).
#   * HTTP 204                 -> one log line, exit 0.
#   * HTTP 401/403             -> "token lacks Actions write", writes a latch, exit 1 ONCE
#                                 (the unit's OnFailure= raises one flag). While the latch is
#                                 newer than the env file it logs and exits 0 without calling.
#   * anything else            -> one log line with the status, exit 0 (next hour retries).
set -uo pipefail

ENV_FILE="${KEEPER_DISPATCH_ENV_FILE:-/etc/ict/gh-dispatch.env}"
LATCH="${KEEPER_DISPATCH_LATCH:-/var/lib/ict/keeper-dispatch.denied}"
REPO="${KEEPER_DISPATCH_REPO:-benbaichmankass/JTA-Trader}"
WORKFLOW="${KEEPER_DISPATCH_WORKFLOW:-schedule-keeper.yml}"
API="${KEEPER_DISPATCH_API:-https://api.github.com}"
log() { echo "keeper-dispatch: $*"; }

# When run by hand (not via systemd), source the env file if readable.
if [ -z "${GH_DISPATCH_TOKEN:-}" ] && [ -r "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi
if [ -z "${GH_DISPATCH_TOKEN:-}" ]; then
  log "inert: no GH_DISPATCH_TOKEN ($ENV_FILE not installed); nothing dispatched"
  exit 0
fi

if [ -f "$LATCH" ] && { [ ! -e "$ENV_FILE" ] || [ "$LATCH" -nt "$ENV_FILE" ]; }; then
  log "latched: an earlier call was refused (401/403); replace $ENV_FILE to retry"
  exit 0
fi

status="$(
  printf 'Authorization: Bearer %s\n' "$GH_DISPATCH_TOKEN" | curl -sS -o /dev/null -w '%{http_code}' \
    --max-time 30 -X POST \
    -H @- \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "$API/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
    -d '{"ref":"main"}' 2>/dev/null
)" || status="${status:-000}"
unset GH_DISPATCH_TOKEN

case "$status" in
  204) log "dispatched $WORKFLOW (HTTP 204)"; rm -f "$LATCH"; exit 0 ;;
  401|403)
    log "HTTP $status: token lacks Actions write on $REPO; latched, will not retry until $ENV_FILE is replaced"
    mkdir -p "$(dirname "$LATCH")" 2>/dev/null && : > "$LATCH"
    exit 1 ;;
  *) log "dispatch not confirmed (HTTP ${status:-none}); next hour retries"; exit 0 ;;
esac
