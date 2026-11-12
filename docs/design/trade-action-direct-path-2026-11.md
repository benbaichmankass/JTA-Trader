# DESIGN: direct trade-action path, from review trigger to account with no repo/PR/Actions hop

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md)
>
> Row: `TRADE-ACTION-DIRECT-PATH` (Tier 2). Lane session_01AFoLuJRcgEM7nWVNbrYHgx, dispatched by Manager Session 2026-11-11a.
> This is a design. Built so far, each as its own Tier-2 PR held for the manager's merge: phase 1 (#25039), phase 2's row submit (#25045) and phase 1b (#25046). Every other phase is unbuilt until its own PR merges, deploys and is observed.

## Gates this adds or changes

**None.** No trading gate is added, changed or removed. The two execution gates (`accounts.yaml::mode`, `strategies.yaml::execution`) and
every per-account `RiskManager` check (`approve_amend` / `approve_action`: mode, shadow, tighten-only + noise floor, TP doctrine, both brackets,
a widen's fresh-entry check, venue read-back) stay exactly as they are. This design changes the **pipe** an approved action travels through,
not what may execute.

Two validity rules on the new surfaces are **not** trading gates, and are stated so nobody reads them as one:

- **An Approve button expires** after `TRADE_APPROVAL_EXPIRY_MIN` minutes (default 15, an operator choice, see the summary). An expired tap
  executes nothing and says so. This mirrors the existing `directed_actions.STALE_S` (900 s): a stale tap must be re-issued, never replayed.
- **Only the operator's chat can approve** (`TELEGRAM_CHAT_ID`, fail-closed when it is unset). The same rule already guards the `wdec` decision
  buttons (`src/bot/claude_decision_bot.py::_is_authorised`).

## The operator's instruction (verbatim, row note, 2026-11-12 ~00:00Z)

> "those decisions shouldn't, preferably not even going through the repo, like there might be logged there, but the action needs to be, it
> doesn't need a PR, that can't be the flow here. We need something that's much more direct so that actions can be taken while they're
> relevant [...] when the review makes a decision that is approved by a mandate, then that decision needs to be implemented on the account
> immediately, not through the repo. And if it needs me, then it needs to ping me so that I can immediately do that, right? But also through
> the system, not like going into the broker account. So there needs to be a button that I press to accept a recommendation, and that
> directly executes that action."

## 1. The current path, with the 2026-11-11 timing (MEASURED)

Sources: `live-review/rows` commit log, row files, `/api/diag/log_file?name=live_review_rows_watch`, `/api/diag/journal?table=trades`.
Population: the two `ml_entry` close recommendations the row names, on `bybit_2` + `bybit_portfolio`.

| step | SOL `pkg-6df5f9dfb83e47b8` | ETH `pkg-462cfc59b2a1469b` |
|---|---|---|
| trigger (L0 snapshot) | `manual` | `adverse_r -0.5R` at 22:42:19Z |
| reviewer info cutoff | 22:36:00Z | 22:43:27Z |
| row pushed to `live-review/rows` | 22:40:10Z (`3b4ebca54`) | 22:49:28Z (`b6c589305`) |
| VM rows watcher saw it | 22:40:12Z (**2 s**) | 22:50:13Z (**45 s**, one poll) |
| watcher verdict | `advice_only` (close is advice-only, route `operator_ask`) | `advice_only` |
| recommendation | close, +0.347R vs hold (table, n=102, net of full cost) | close, +0.357R vs hold (table, n=75) |
| stop hit, both accounts | 23:07:11Z | 23:12:43Z |
| **window the operator had** | **27 min** | **22.5 min** |

What the table shows: **the VM had both recommendations within a minute.** The 22-27 minutes were lost on the **operator half**. An
`operator_ask` close reached the operator as a manager message in chat. The approved action then had to travel as a `system-action` GitHub
issue through an Actions queue that was ~460 runs deep that night, and both stops hit first. The review half is slower than it needs to be
(trigger → row ≈ 7 min for ETH, of which the wake is ~1 min and the review ~6 min), but it was not the binding delay on 2026-11-11.

The current hops, in order:

1. `live_review_due.py` (VM) detects a due event → `live_review_wake_post.py` commits the packet to `live-review/rows` and posts an
   `ltr-wake` **comment on PR #17895**.
2. The manager session is woken by that GitHub event, reads it, spawns a review lane.
3. The lane writes its row and pushes it to `live-review/rows` (git).
4. The VM rows watcher (`live_review_rows_watch.py`, 45 s poll) fetches it:
   - `recommended` + a granted mandate (`MD-TRADE-DESK`, or an `ltr_auto_apply` entry) → `live_review_dispatch.py` → `live_review_apply.py`
     executes on the account. **No PR or Actions hop here already.**
   - `operator_ask`, or any advice-only class → logged, **not sent**. The operator's yes then needs chat + a `system-action` issue (Actions
     queue), or a `directed_action.py submit` push to `directed/actions` (20 s VM poll; built 2026-10-29, TRADE-ACTION-FAST-PATH), which
     still needs a Claude session to type it.

## 2. The new path

```
VM due event ──(3) wake──► standing review lane ──(2) HTTPS ops call──► VM /api/bot/ops/actions
                                                                          │
                       ┌──────────────────────────────────────────────────┤
                       ▼                                                  ▼
       mandate covers it (recommended + MD-*)               needs the operator (operator_ask / advice-only)
       live_review_dispatch → live_review_apply              Telegram message + [Approve] [Reject]   (1)
       per-account executors + RiskManager                   SPA console: same Approve              (1b)
                       │                                          │ tap (operator chat only, not expired, once)
                       │                                          ▼
                       │                         directed_action/v1 record → local spool
                       │                         live trader's directed thread (≤ 2 s) → live_review_apply
                       ▼                                          ▼
                 journal (runtime_logs) ───────(5) export──► git LOG copy (audit only, never the action path)
```

Numbered as the dispatch numbers the target: (1) the button, (2) the direct submit, (3) the immediate wake, (5) the journal and export. (4) the
mandate route already executes on the VM today with no repo hop once the row is on the VM; (2) removes the remaining git hop in front of it, and also carries every non-code operational action (MANAGER-VM-DIRECT-OPS).

### 2.1 Phase 1: Telegram Approve / Reject for operator-needed recommendations (built first; biggest win)

- **When a button is offered.** The rows watcher already classifies every new row. A row that the VM will **not** execute itself and that has
  a direct executor gets an ask: route `operator_ask`, or verdict `advice_only` on a non-`none` route, with an action in the map below, and
  mechanics `match` (or `could_not_look`, stated in the message). `mismatch` / `flag_mechanics` never get a button: that is an order-path bug,
  not an exit call (skill § 3 Step 1). `hold` / `no_recommendation` never ping (Q3: applies and asks only).
- **Action map** (row → `directed_action/v1`): `close`→`close`; `partial_close`→`partial_close` (`size_fraction`); `move_tp`→`move_tp`
  (`level`); `tighten_sl`→`tighten_sl` (`level`); `widen_sl`→`move_sl` (`level`, resolved per package to a widen). `change_size` / `add_entry`
  have no executor anywhere (LTR-ACTION-EXECUTOR-GAPS), so they get no button and are logged `no_direct_executor`.
- **The message**: symbol, strategy, accounts, the action, the row's EV line (`ev_delta_r`, basis, confidence), the first 2-3 lines of its
  reason, the mechanics verdict, and the expiry time. Buttons: **✅ Approve** / **✖ Reject**.
- **callback_data** `tapv:<a|r>:<10 hex token>` (≤ 64 B). The token keys a pending entry in `runtime_logs/trade_approvals/pending.json`
  (review_id, package, the mapped action, created / expires, state). One ask per review_id (idempotent across restarts).
- **The tap** (either polled bot: the Claude decision bot or the trader bot both register `tapv`): authorised chat only → under a file lock,
  `pending` → `approved` / `rejected` / `expired`; a second tap reads `already_<state>`. Approve writes ONE `directed_action/v1` record
  (`directed_by: operator:telegram`, `operator_quote`: the exact approval the operator tapped, naming the review and the ask token) into the
  local spool `runtime_logs/trade_approvals/spool/comms/directed_actions/<id>.json`.
- **The execution** happens in the **live trader** (its memory limits, its env), not in the bot process. The existing `directed-actions-watch`
  thread checks the spool every 2 s and runs `directed_action.py spool-pass`. That is the same `vm_pass` code, reading the spool instead of git,
  with the same state file, receipts, retries, venue deferral and per-record ping. So a record is handled at most once on either path, and
  exporting it to `directed/actions` later cannot replay it.
- **Why the directed path and not a reviewer apply**: an Approve tap is the operator's own act. `directed_actions` already carries the
  operator's authority (the verbatim-quote rule), is exempt from the advice-only rule for reviewer recommendations, needs no mandate, and goes
  through `live_review_apply.run()`: the SAME executors and `RiskManager` gates, both brackets, read-back. Its scope is the package. Each
  account still decides for itself.
- **Expected latency**: tap → spool ≤ 0.1 s → thread ≤ 2 s → subprocess start ~2-4 s → venue call + read-back. Target: **under 15 s** from tap
  to `APPLIED`, against 22-27 min lost on 2026-11-11.

### 2.2 Phase 1b: the SPA Approve button (second surface)

`GET /api/bot/trade-approvals` (pending asks) and `POST /api/bot/trade-approvals/{token}` `{"choice": "approve"|"reject"}`, behind the SPA's
operator session (`require_session`, default-deny, never a carve-out). Both call the same `trade_approvals.decide()`, so a tap in Telegram and a
click in the console are one state machine: whichever comes first wins, and the other reads `already_approved`. The SPA change itself lives in
`ict-trader-dashboard` (its own row).

### 2.3 Phase 2: the direct ops channel (MANAGER-VM-DIRECT-OPS) and the direct row submit

Scope added 2026-11-12 00:06Z by the manager, carrying the operator's words (verbatim, ~00:05Z): *"the Claude sessions should already be
able to interact directly with the VM without needing to go through GitHub ... for things like this, which is not a code change, it's just
an action on the system, that shouldn't have to go through GitHub. It should go through the system though ... we're not looking for a
workaround that has Claude directly interacting with the brokers ... it should go directly from Claude to the VM and skip like a merge as
part of that process."* This is row `MANAGER-VM-DIRECT-OPS`, operator-approved 2026-11-05 (popup "Direct ops = Approve (Recommended)";
"Config path = Keep via git"; "Deploy = Keep git-sync" plus a direct "sync now"; "Alert wake = Tiny GitHub doorbell"). It is now owned by
this lane. It is ONE channel: the review lanes' row submit is one action on it.

**The channel.** `POST /api/bot/ops/actions` with `{"action", "params", "session", "reason", "operator_quote"?}` returns `{"job_id", "tier",
"state"}`, and `GET /api/bot/ops/jobs/{job_id}` returns the journaled result (exit, stdout tail, `read_state`). The actions are the
**existing system-actions allowlist** (`docs/claude/system-actions.md` § 2; the `case` arms of `.github/workflows/system-actions.yml`).
They are the same names, the same parameter validation and the same scripts, run **on the VM** instead of over SSH from an Actions runner.
Nothing reaches a broker except through those scripts and the per-account executors, exactly as today.

- **Tiers and approvals do not change.**
  - **Tier 1** (read-only / hygiene) runs at once.
  - **Tier 2** runs when the call carries the operator's verbatim OK (`operator_quote`, the same rule as `directed_actions`). Without one, the
    VM sends the operator the phase-1 Telegram **Approve / Reject** card for that job and runs it on Approve.
  - **Tier 3** (strategy logic, params, risk caps, account-mode promotion) and every **config or code edit** stay in git (operator
    2026-11-05, "Keep via git"). The channel refuses them by name and points at the PR route.
  - A **trade action** goes through the same `directed_actions` / `live_review_apply` path as phase 1. A reviewer row under a granted mandate
    goes through the same `dispatchable()` check as a branch row.
- **Execution is out of process.** The web API validates the call and writes a job file to `runtime_logs/ops/queue/`. A small
  path-activated unit (`ict-ops-runner.path` → `.service`, user `ubuntu`, the VM `.env`) runs it at once and writes
  `runtime_logs/ops/jobs/<id>.json`. So a `restart ict-web-api` job cannot kill the process that is serving it, and a long job never blocks
  the API.
- **Auth.** The env proxy already injects the ICT environment's credential on every request a session makes to `ict-bot.duckdns.org`, in
  `X-Work-Store-Token` (row WSD-S1-PROXY-AUTH-COLLISION, done and observed 2026-11-05: a request carrying only that header is accepted by
  the work store). The ops router checks that header fail-closed (503 when unset, 401 when wrong), the same as
  `work_items._require_work_store_token`, and is listed in `SITE_PUBLIC_POST_PATHS` like the other service-token POSTs. **So no new secret is
  needed and no token ever appears in a prompt, a row or the repo.** Every job records the calling `session`. The token authenticates the
  environment; the tier rules above decide what it may do.
- **The row submit shipped first, as its own route** `POST /api/bot/live-review/rows` (PR #25045; same token, same create-only file, `GET /api/bot/live-review/rows/{id}` for the receipt). The ops channel wraps it as the action `live-review-row`. The VM validates the row exactly as the watcher validates a branch row
  (`live_review_rows.py`, `packet_sha` against the wake poster's local packet), then runs the same `run_pass` classification in process:
  mandate → dispatch, operator → phase-1 ask. A duplicate review_id returns 409. The rows-branch push stays valid as the fallback, and
  phase 4 copies direct rows onto the branch as a log; the watcher seeds them as seen, so the copy never replays.
- **Porting in waves, with parity enforced.** A VM-side registry (`src/runtime/ops_actions.py`: action → tier, parameter validator, argv)
  is filled one action at a time. A CI test requires every registered action to exist in the `system-actions.md` allowlist **with the same
  tier**, so the channel can never grant more than the workflow does. The workflow stays as the fallback for every action not yet ported.
  - **Wave 1** is the trade path and deploy: `live-review-row`, `directed-action`, `amend-prop-bracket` (PROP-BRACKET-APPLY), `sync-now`
    (one ict-git-sync pull) and `restart-service`.
  - Later waves follow the order in which the manager files system-action issues today (the most-used actions first).
- **Alerts towards the manager** stay as decided on 11-05: the manager reads `/api/bot/alerts` directly on every wake, and GitHub carries
  only the content-free doorbell (ALERT-LEDGER-TO-MANAGER #23033, `landed_unproven`; its observation is on that row).

### 2.4 Phase 3: the immediate review wake

What a VM can use to start or wake a Claude session, per the Claude Code docs (fetched 2026-11-12; each line cites
code.claude.com / platform.claude.com):

| mechanism | starts | auth from the VM | limits | billing |
|---|---|---|---|---|
| **Routine API trigger** `POST https://api.anthropic.com/v1/claude_code/routines/{id}/fire` | a **new** cloud session per fire, prompt + `{"text": ...}` payload | per-routine bearer token made in the web UI (not an API key) | 30 fires/h per routine, 100/h per account, 429 + Retry-After past it; no idempotency key; "experimental API" | **subscription usage** (docs, billing row) |
| GitHub-event routine (PR / issue / release events) | a new session | the GitHub App | per-task + per-account hourly caps; events past them are **dropped** | subscription |
| PR-comment wake of a subscribed session (today) | wakes the manager, who then spawns | GitHub token | rides GitHub webhook delivery; competes with the Actions backlog only on the spawn side | subscription |
| `claude -p "..." --cloud <session-id>` | queues a message into an **existing** session | requires `claude auth login` / `setup-token` on the VM | needs `allow_remote_sessions`; ANTHROPIC_API_KEY must be unset or it bills the API | subscription when OAuth (implied, not stated for `-p`) |

**Recommendation: the routine API trigger.** The VM posts the due event (package, trigger, `packet_sha`) as the fire `text`. The routine's
saved prompt is the live-review lane brief: read the packet from the VM, review, submit via phase 2. One fire = one fresh reviewer session,
which matches today's one-lane-per-review model and removes the manager hop. It runs on the plan, not API credits.

- **The token** is a per-routine credential: the operator creates it in the web UI (it is shown once) and it is written to the VM `.env` by
  the env workflow. It is never committed.
- **Dedupe on the VM** (no idempotency key): one fire per `(package, due level)`, recorded in `runtime_logs/live_review/fires.jsonl`.
- **Budget**: 30/h per routine. The 2026-11-11 evening ran up to 7 packages per round, about every 10 min (ESTIMATED from the `live-review/rows` commit subjects 23:15-23:58Z, not from a fire count: ≈ 40/h at peak), so the fire batches every package
  due in one minute into one fire, and two routines (real-money+prop / paper) split the load.
- **Fallback**: the PR-comment wake stays as the fallback on a 429 or a failed fire. One red flag goes out per incident. There is no halting.
- **Not recommended**: `claude -p` on the VM. It puts a long-lived claude.ai login on the live trader's box, the docs leave subscription
  billing for `-p` implicit, and an `ANTHROPIC_API_KEY` in the env would silently bill the API (the binding "nothing spends API credits" rule).
  The SDK overview also says claude.ai login is not for third-party agent products. Whether an operator's own VM counts as that is not
  addressed, so this stays off the table unless Anthropic confirms it.

### 2.5 Phase 4: journal and export

Every event is already journaled on the VM: `trade_approvals/journal.jsonl` (offered / sent / tapped / approved / rejected / expired / spooled),
`directed_actions/receipts.jsonl` (the apply, per account, with `venue_after`), and later `live_review/direct_rows/`. These are exposed as diag
`log_file` names. A VM exporter (git-sync's own push credential, a create-only append to a `log/trade-actions` branch, every ~5 min) copies them
to git for audit. Git is **never** read on the action path.

## 3. Auth and safety

| risk | control |
|---|---|
| a stranger taps Approve | `TELEGRAM_CHAT_ID` match, fail-closed; the bot is private; the token is an opaque digest, not an instruction |
| a double tap / two surfaces | file lock + state machine; a non-`pending` ask reads `already_<state>`; the directed record id is unique and handled once |
| a stale approval | expiry (default 15 min) + `directed_actions.STALE_S`; the package must still be `open` at apply |
| an approval that loosens risk | none possible outside today's rules: `RiskManager` per account (tighten-only unless the operator directs a widen, which then passes the fresh-entry check), TP doctrine, both brackets always, read-back |
| the review lane submitting directly | the proxy-injected environment credential, schema + `packet_sha` check, then the SAME mandate check as a branch row; a lane cannot widen what a mandate grants |
| a session running an ops action | the channel serves only actions already on the system-actions allowlist, at the same tier (CI parity test); Tier 2 needs the operator's verbatim OK or an Approve tap; Tier 3 and config/code edits are refused and stay in git |
| a wake storm / spend | routine caps (30/h, 100/h) + VM dedupe; runs on the plan; no Messages API, no API key anywhere |
| secrets in git | none: tokens live in the VM `.env` and the session proxy; records name accounts by their existing config ids only (already in the repo) |

## 4. What this reuses (no second order path)

- `scripts/ops/live_review_apply.py::run()`: every execution, all executors, `RiskManager.approve_amend` / `approve_action`, read-back.
- `src/runtime/directed_actions.py` + `scripts/ops/directed_action.py::vm_pass`: the operator-authority record, idempotency, retries, deferral, the ping.
- `src/runtime/live_review_rows_watch.py`: the row classification (`dispatchable`, advice-only, auto mandate) and the directed thread.
- The Telegram two-way pattern from `src/runtime/telegram_decisions.py` (the 64-byte callback, fail-closed chat auth, answerable-route-by-poll-evidence),
  `src/runtime/telegram_poll_registry.py`, `src/bot/claude_decision_bot.py`, `src/bot/telegram_query_bot.py`.
- `src/runtime/notify.send_telegram_direct` (reply_markup) and `src/runtime/telegram_channels` (the result ping already goes to TRADES).
- The work store's service-token check (`work_items._require_work_store_token`, `X-Work-Store-Token`, `SITE_PUBLIC_POST_PATHS`) for the phase-2 auth.
- The system-actions allowlist and its scripts (`docs/claude/system-actions.md`, `.github/workflows/system-actions.yml`) for every phase-2 action.

## 5. Phases, each its own Tier-2 PR

| # | PR | observation that closes it |
|---|---|---|
| 1 | Telegram Approve/Reject + spool execution (`trade_approvals.py`, watcher hook, both bots, `spool-pass`, diag `trade_approvals`) | the first `operator_ask` row after deploy produces ONE Telegram ask (`trade_approvals` journal `sent: true`); a tap produces a `directed_actions` receipt with `verdict: applied` (or a named refusal) and `tap_to_done_s` < 15 |
| 1b | SPA routes `GET/POST /api/bot/trade-approvals` (PR #25046) + dashboard button (dashboard repo) | one approval from the console, read back in the journal with `source: spa` |
| 2 | the direct ops channel (`/api/bot/ops/actions` + `ict-ops-runner` + `ops_actions.py` wave 1 incl. `live-review-row`) + lane brief | (a) a Tier-1 job from a session returns `done` in `/api/bot/ops/jobs/<id>` with no GitHub issue; (b) one review row lands via `live-review-row` and appears in `rows_watch.jsonl` with `source: direct`, `reviewed_to_seen_s` < 5; (c) a Tier-2 job without a quote produces a Telegram card, and Approve runs it |
| 3 | routine fire from `live_review_due` + dedupe + fallback | a due event → `fires.jsonl` 2xx → a row from that session; trigger → row measured against today's ~7 min |
| 4 | exporter of the journals to a git log branch | the log branch carries the day's receipts; no action read from it |

## 6. Ten-line summary for the manager's decision page

1. 2026-11-11: the VM had both ETH/SOL close calls within 45 s; the 22-27 min until the stops hit were lost waiting for the operator's yes and the Actions queue.
2. Phase 1 (built now): every `operator_ask` / advice-only recommendation with an executor becomes a Telegram message with **Approve / Reject**.
3. Approve executes in the live trader in seconds, through the existing directed-action path and the same executors + RiskManager gates. No PR, no Actions, no broker login.
4. Phase 1b adds Approve to the SPA console. Phase 2 is the direct ops channel (MANAGER-VM-DIRECT-OPS): the system-actions allowlist as HTTPS calls from a session to the VM, same tiers, with review rows as one action. Phase 3 wakes a reviewer via the routine API trigger.
5. Gates added or changed: **none**. Nothing spends API credits (routines run on the plan; no API key anywhere).
6. **Decision: approval expiry.** Default 15 min (matches the directed-action staleness bound). Alternative: 5 min or 30 min.
7. **Decision: which classes get buttons.** Default: close, partial_close, move_tp, tighten_sl, widen_sl (every class with an executor). Alternative: close + partial_close only.
8. **Decision: advice-only `recommended` rows.** Default: they get a button too (they also need the operator to execute). Alternative: only `route: operator_ask`.
9. **Decision (phase 3): create a routine + API token** in the claude.ai web UI for the reviewer (operator-only act; ~2 min), within 30 fires/h per routine.
10. **Phase 2 needs no new secret**: it authenticates with the credential the env proxy already injects (`X-Work-Store-Token`). Decision: OK that this one environment credential authorises Tier-1 ops at once, with Tier 2 still needing your quote or an Approve tap.
