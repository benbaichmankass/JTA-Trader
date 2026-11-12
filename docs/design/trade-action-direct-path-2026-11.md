# DESIGN: direct trade-action path, from review trigger to account with no repo/PR/Actions hop

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md)
>
> Row: `TRADE-ACTION-DIRECT-PATH` (Tier 2). Lane session_01AFoLuJRcgEM7nWVNbrYHgx, dispatched by Manager Session 2026-11-11a.
> This is a design. Phase 1 is being built in a separate Tier-2 PR. Every other phase is unbuilt until its own PR merges, deploys and is observed.

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
VM due event ──(3) wake──► standing review lane ──(2) HTTPS POST row──► VM /api/bot/live-review/rows
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
mandate route already executes on the VM today with no repo hop once the row is on the VM; (2) removes the remaining git hop in front of it.

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

### 2.3 Phase 2: direct submit endpoint for review lanes

`POST /api/bot/live-review/rows` takes one row (schema `comms/schema/live_review.schema.json`), validated exactly as the watcher validates a
branch row (`live_review_rows.py`), then handed to the same `run_pass` logic in-process: mandate → dispatch; operator → phase-1 ask. The row
is journaled at `runtime_logs/live_review/direct_rows/<review_id>.json`; a create-only duplicate review_id returns 409.

- **Auth**: a dedicated bearer `LIVE_REVIEW_SUBMIT_TOKEN` in the VM `.env`, checked fail-closed in the router (503 unset, 401 wrong), listed in
  `SITE_PUBLIC_POST_PATHS` like the other service-token POSTs. Cloud review lanes reach `ict-bot.duckdns.org` through the session proxy, which
  injects the environment's credential for that host, so **no token ever appears in a prompt, a row or the repo**. The operator originates the
  value (credentials skill); a workflow writes it to the VM `.env`.
- **The packet stays byte-exact**: the wake poster already writes the packet on the VM. A direct row cites `packet_sha`; the VM checks the sha
  against its local copy (no git read on the hot path).
- **Git keeps a LOG copy**: the existing rows-branch push stays valid as a fallback, and an exporter (phase 4) copies direct rows onto
  `live-review/rows` afterwards; the watcher seeds them as seen, so the copy never replays.

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
- **Budget**: 30/h per routine. The 2026-11-11 evening ran ~7 packages per ~10-min round (≈ 40/h at peak), so the fire batches every package
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
| the review lane submitting directly | phase 2 bearer, schema + `packet_sha` check, then the SAME mandate check as a branch row; a lane cannot widen what a mandate grants |
| a wake storm / spend | routine caps (30/h, 100/h) + VM dedupe; runs on the plan; no Messages API, no API key anywhere |
| secrets in git | none: tokens live in the VM `.env` and the session proxy; records name accounts by their existing config ids only (already in the repo) |

## 4. What this reuses (no second order path)

- `scripts/ops/live_review_apply.py::run()`: every execution, all executors, `RiskManager.approve_amend` / `approve_action`, read-back.
- `src/runtime/directed_actions.py` + `scripts/ops/directed_action.py::vm_pass`: the operator-authority record, idempotency, retries, deferral, the ping.
- `src/runtime/live_review_rows_watch.py`: the row classification (`dispatchable`, advice-only, auto mandate) and the directed thread.
- The Telegram two-way pattern from `src/runtime/telegram_decisions.py` (the 64-byte callback, fail-closed chat auth, answerable-route-by-poll-evidence),
  `src/runtime/telegram_poll_registry.py`, `src/bot/claude_decision_bot.py`, `src/bot/telegram_query_bot.py`.
- `src/runtime/notify.send_telegram_direct` (reply_markup) and `src/runtime/telegram_channels` (the result ping already goes to TRADES).
- `/api/bot/work/decision`'s service-token pattern (`_require_decision_write_token`, `SITE_PUBLIC_POST_PATHS`) for the phase-2 bearer.

## 5. Phases, each its own Tier-2 PR

| # | PR | observation that closes it |
|---|---|---|
| 1 | Telegram Approve/Reject + spool execution (`trade_approvals.py`, watcher hook, both bots, `spool-pass`, diag `trade_approvals`) | the first `operator_ask` row after deploy produces ONE Telegram ask (`trade_approvals` journal `sent: true`); a tap produces a `directed_actions` receipt with `verdict: applied` (or a named refusal) and `tap_to_done_s` < 15 |
| 1b | SPA routes `GET/POST /api/bot/trade-approvals` + dashboard button | one approval from the console, read back in the journal with `source: spa` |
| 2 | `POST /api/bot/live-review/rows` + submit token + lane brief | one review lane row lands via HTTPS and appears in `rows_watch.jsonl` with `source: direct` and `reviewed_to_seen_s` < 5 |
| 3 | routine fire from `live_review_due` + dedupe + fallback | a due event → `fires.jsonl` 2xx → a row from that session; trigger → row measured against today's ~7 min |
| 4 | exporter of the journals to a git log branch | the log branch carries the day's receipts; no action read from it |

## 6. Ten-line summary for the manager's decision page

1. 2026-11-11: the VM had both ETH/SOL close calls within 45 s; the 22-27 min until the stops hit were lost waiting for the operator's yes and the Actions queue.
2. Phase 1 (built now): every `operator_ask` / advice-only recommendation with an executor becomes a Telegram message with **Approve / Reject**.
3. Approve executes in the live trader in seconds, through the existing directed-action path and the same executors + RiskManager gates. No PR, no Actions, no broker login.
4. Phase 1b adds the same Approve on the SPA console; Phase 2 lets review lanes POST rows straight to the VM; Phase 3 wakes a reviewer via the routine API trigger.
5. Gates added or changed: **none**. Nothing spends API credits (routines run on the plan; no API key anywhere).
6. **Decision: approval expiry.** Default 15 min (matches the directed-action staleness bound). Alternative: 5 min or 30 min.
7. **Decision: which classes get buttons.** Default: close, partial_close, move_tp, tighten_sl, widen_sl (every class with an executor). Alternative: close + partial_close only.
8. **Decision: advice-only `recommended` rows.** Default: they get a button too (they also need the operator to execute). Alternative: only `route: operator_ask`.
9. **Decision (phase 3): create a routine + API token** in the claude.ai web UI for the reviewer (operator-only act; ~2 min), within 30 fires/h per routine.
10. **Decision (phase 2): originate `LIVE_REVIEW_SUBMIT_TOKEN`** (any random 32+ byte value) and save it as the environment credential for `ict-bot.duckdns.org`.
