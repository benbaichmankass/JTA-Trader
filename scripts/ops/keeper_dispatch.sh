#!/usr/bin/env bash
# wiring: systemd - deploy/trainer/ict-keeper-dispatch.{service,timer} (trainer VM, hourly) and deploy/trainer/ict-ltr-wake-dispatch.{service,timer} (15 min, live-review-wake.yml, skip-if-active).
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

# PAT RATE SAMPLE (ACTIONS-QUEUE-BACKLOG, PAT 5,000/h consumer hunt): one journal line per run with the shared
# PAT's core budget, read from GET /rate_limit, which GitHub documents as NOT counting against the limit. This
# script runs every 15 min (ict-ltr-wake-dispatch) and hourly (ict-keeper-dispatch) with the same token, so the
# journal becomes a used/remaining time series whose slope can be lined up against the per-workflow run census:
# the consumer is named by measurement, not inference. Read-only and best-effort: a failed read logs
# "could not read" and the dispatch below is unaffected. Only numbers are logged, never the token.
pat_line="$(
  printf 'Authorization: Bearer %s\n' "$GH_DISPATCH_TOKEN" | curl -sS --max-time 20 -H @- \
      -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' \
      "$API/rate_limit" 2>/dev/null \
    | python3 -c '
import json, sys, datetime
try:
    c = json.load(sys.stdin)["resources"]["core"]
    r = datetime.datetime.fromtimestamp(int(c["reset"]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("core used=%d remaining=%d limit=%d reset=%s" % (int(c["used"]), int(c["remaining"]), int(c["limit"]), r))
except Exception:
    pass
' 2>/dev/null
)" || pat_line=""
if [ -n "$pat_line" ]; then
  log "pat_rate $pat_line"
else
  log "pat_rate could not read GET /rate_limit (sample skipped; dispatch unaffected)"
fi

# SKIP-IF-ACTIVE (ict-ltr-wake-dispatch, manager 2026-11-19): with KEEPER_DISPATCH_SKIP_IF_ACTIVE=1, do not
# dispatch while a RECENT run of $WORKFLOW is queued or in progress, so a 15-min clock never stacks runs into a
# deep queue. Only runs created in the last KEEPER_DISPATCH_ACTIVE_WINDOW_MIN (default 45) minutes count: this repo
# keeps zombie queued runs that never start (395 from <= 2026-11-11, some from May; ACTIONS-QUEUE-BACKLOG), and one
# stuck run must never silence the wake forever. An older active run is ignored and LOGGED, so it stays visible.
# An unreadable count is logged and the dispatch goes ahead (one extra run beats a silent skip).
# Off by default: the hourly schedule-keeper floor is unchanged.
_runs_count() {  # $1 = status, $2 = optional created>= ISO stamp; prints total_count or nothing
  local q="status=$1&per_page=1"
  [ -n "${2:-}" ] && q="$q&created=%3E%3D$2"
  printf 'Authorization: Bearer %s\n' "$GH_DISPATCH_TOKEN" | curl -sS --max-time 30 \
      -H @- \
      -H 'Accept: application/vnd.github+json' \
      -H 'X-GitHub-Api-Version: 2022-11-28' \
      "$API/repos/$REPO/actions/workflows/$WORKFLOW/runs?$q" 2>/dev/null \
    | sed -n 's/.*"total_count"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -n 1
}
if [ "${KEEPER_DISPATCH_SKIP_IF_ACTIVE:-0}" = "1" ]; then
  window="${KEEPER_DISPATCH_ACTIVE_WINDOW_MIN:-45}"
  since="$(date -u -d "-${window} minutes" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true)"
  active=0
  for st in queued in_progress; do
    if [ -z "$since" ]; then
      log "could not compute the ${window}-min window; dispatching anyway"
      break
    fi
    recent="$(_runs_count "$st" "$since" || true)"
    if [ -z "$recent" ]; then
      log "could not read $st runs of $WORKFLOW; dispatching anyway"
      continue
    fi
    active=$((active + recent))
    all="$(_runs_count "$st" || true)"
    if [ -n "$all" ] && [ "$all" -gt "$recent" ]; then
      log "ignoring $((all - recent)) $st run(s) of $WORKFLOW created before $since (older than ${window} min: stuck?)"
    fi
  done
  if [ "$active" -gt 0 ]; then
    unset GH_DISPATCH_TOKEN
    log "skip: $active run(s) of $WORKFLOW created in the last ${window} min are queued or in progress; nothing dispatched"
    exit 0
  fi
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
