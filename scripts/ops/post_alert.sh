#!/usr/bin/env bash
# wiring: called by the workflow steps that curl Telegram directly (guards.yml,
# claude-run-failure-alert.yml, external-*-alert.yml, research-loss-detector.yml)
#
# ALERT-LEDGER-TO-MANAGER: record ONE alert in the VM's alert ledger via the
# authenticated POST /api/bot/alerts (DASHBOARD_API_TOKEN, the exec-js-signature
# pattern). BEST-EFFORT and NEVER a gate: every failure is swallowed and the exit
# code is always 0, so the Telegram send that precedes it is unaffected.
#
# Usage: post_alert.sh <kind> <channel> <priority> <delivered> <body> [dedup_key]
#   delivered: telegram_ok | skipped_no_creds | raised | unknown
set -u
KIND="${1:-alert}"; CHANNEL="${2:-system}"; PRIORITY="${3:-high}"
DELIVERED="${4:-unknown}"; BODY="${5:-}"; DEDUP="${6:-}"
[ -n "${DASHBOARD_API_TOKEN:-}" ] || { echo "post_alert: DASHBOARD_API_TOKEN unset — ledger not written (send unaffected)"; exit 0; }
BASE="${BOT_API_BASE:-https://ict-bot.duckdns.org}"
JSON=$(KIND="$KIND" CHANNEL="$CHANNEL" PRIORITY="$PRIORITY" DELIVERED="$DELIVERED" BODY="$BODY" DEDUP="$DEDUP" python3 -c '
import json, os
d = {"kind": os.environ["KIND"], "channel": os.environ["CHANNEL"], "priority": os.environ["PRIORITY"],
     "delivered": os.environ["DELIVERED"], "body": os.environ["BODY"]}
if os.environ.get("DEDUP"): d["dedup_key"] = os.environ["DEDUP"]
print(json.dumps(d))' 2>/dev/null) || { echo "post_alert: could not build body (ignored)"; exit 0; }
curl -sS --max-time 15 --retry 2 --retry-delay 3 -o /dev/null \
  -H "Authorization: Bearer ${DASHBOARD_API_TOKEN}" -H 'Content-Type: application/json' \
  -X POST "${BASE}/api/bot/alerts" -d "$JSON" >/dev/null 2>&1 \
  || echo "post_alert: POST failed (ignored — send unaffected)"
exit 0
