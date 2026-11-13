# Ops token rotation (`WORK_STORE_TOKEN`)

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Gates this adds or changes: none.** Rotation is a procedure; nothing in it blocks a job, a trade or a deploy.

Lane VM-CHANGE-LEDGER, item 4b (operator grant 2026-11-12, popup "Build it"). This procedure rotates the one
credential that opens the direct ops channel (`/api/bot/ops/*`), the work-store writes, the direct row submit and
the read-only diag routes. It never breaks the live channel: the old and new tokens are both accepted during the
switch.

## Where the token lives (measured 2026-11-12 from the code and workflows on `main`)

| Holder | Where | Who can change it |
|---|---|---|
| The VM, `ict-web-api` | the trader `.env` (`WORK_STORE_TOKEN`), loaded by `deploy/ict-web-api.service` | an ops job (`stage-token-rotation`), or the `sync-vm-secrets` workflow, which writes the GitHub secret's value into that file |
| GitHub Actions | the repository secret `WORK_STORE_TOKEN`, read by `sync-vm-secrets`, `work-store-outbox`, `desk-decisions-mirror`, `live-replay-parity` and `soak-book-grade-weekly` | **the operator only** (no session holds a credential that can write repository secrets) |
| Claude sessions | the claude.ai environment's network secret for `ict-bot.duckdns.org`, injected by the proxy as `X-Work-Store-Token` | **the operator only**, through the `request_credential` form (a session never sees the value) |

## Honest answer: full automation is not possible

Two of the three holders can only be changed by the operator. So a rotation always costs the operator one sitting.
What this design keeps down to a single prompt is everything else: the VM side runs as a job, and the dual-accept
window means the order in which the three holders change does not matter.

## The dual-accept (shipped with this runbook)

`src/web/api/routers/work_items.py::accepted_work_store_tokens` accepts `WORK_STORE_TOKEN`. It also accepts
`WORK_STORE_TOKEN_PREV`, but only while `WORK_STORE_TOKEN_PREV_UNTIL` (ISO-8601 UTC) is in the future. A PREV with
no parseable UNTIL is never accepted, so an open-ended second token cannot exist. When the window ends, nothing
needs cleaning up: the old value just stops working.

## The procedure (one operator prompt)

1. **Stage on the VM (a job, no operator step).** A session submits
   `{"action": "stage-token-rotation", "params": {}, "operator_quote": "<the rotation grant>"}` to
   `POST /api/bot/ops/actions`. The runner copies the current value to `WORK_STORE_TOKEN_PREV`, sets
   `WORK_STORE_TOKEN_PREV_UNTIL` to now + 72 h, backs up `.env` and restarts `ict-web-api`. The job prints
   fingerprints only. Both tokens now work. The job is a VM change ledger entry with `durable_in_repo: not_needed`.
2. **THE prompt (operator).** The session calls `request_credential` for host `ict-bot.duckdns.org`, header
   `X-Work-Store-Token`. Its message tells the operator to generate one fresh random value (for example
   `openssl rand -hex 32` or a password manager) and to paste the SAME value into:
   (a) the form, and (b) GitHub → Settings → Secrets → Actions → `WORK_STORE_TOKEN`.
   It is one prompt, but two places get the paste.
3. **Push the new value to the VM (a workflow, no operator step).** The session dispatches `sync-vm-secrets`
   (skill `git-actions`). The workflow writes the new value into the VM's `WORK_STORE_TOKEN`. Because only a
   web-api-only key changed (`WEB_API_ONLY_KEYS`), it restarts `ict-web-api` alone. `WORK_STORE_TOKEN_PREV` keeps
   the old value until the window ends.
4. **Verify (the session).** `GET /api/bot/ops/ledger` must answer 200 with the new credential the proxy now
   injects. Then dispatch any one workflow that uses the secret (e.g. `work-store-outbox`) and check it gets 2xx.
   Record the outcome with a `ledger-backfill` entry for the GitHub and claude.ai changes
   (`durable_in_repo: not_needed`).

If step 2 or 3 does not happen, nothing breaks. The old token stays valid for 72 h and keeps the current value
working as `WORK_STORE_TOKEN`. To undo before step 3, do nothing: PREV expires.

## Cadence: every 90 days (operator decision)

**The operator chose by popup at ~21:44Z on 2026-11-12, verbatim: *"Every 90 days"*.** The Manager Session
2026-11-11a relayed it. It also applies at once after any suspected exposure.

The schedule is the pipeline item **`PI-20261112-B8YKRFCY-0001`**: `due_when.check_every_days: 90`,
`last_checked: 2026-11-12`, `next_action: dispatch_lane`, routed to VM-CHANGE-LEDGER. Its due date is computed, not
declared. It surfaces in the daily brief §0, and the manager dispatches ONE lane to run steps 1–4 above; step 2 is
the operator's one prompt. When a rotation completes, the lane re-dates the item
(`python3 scripts/ops/pipeline.py --redate PI-20261112-B8YKRFCY-0001 --observation ... --next-due <+90 d>`). It
never closes the item. **There is no cron, by design** (manager instruction 2026-11-12).
