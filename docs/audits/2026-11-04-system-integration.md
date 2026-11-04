# System integration audit — how the parts connect, and where alerts, data and state miss the manager

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
>
> Written 2026-11-04 by lane `SYSTEM-AUDIT-INTEGRATION` (session_01AFoLuLCbQTSU5jK9dbmcvU, dispatched by Manager Session 2026-11-04a). Its measurements are dated 2026-11-04 18:18–18:30Z; re-read, never quote forward.

**Question (one):** how do the system's components actually connect, and where do alerts, data and state fail
to reach the manager (Claude), or reach it late?

**Method.** Every number below was read in this session, 2026-11-04 between 18:18Z and 18:30Z, from the live
trader through `scripts/ops/diag_fetch.sh` (direct HTTPS, Transport A) and the browser-direct `/api/bot/*`
routes, from GitHub (ops-flags PR #17895) and from code on `main` @ `8287535f8`. Each finding states its
population. MEASURED means read from a live surface; CODE means read from source; INFERRED says so.

**Scope boundaries.** Repo/CI flows and the deploy path belong to `SYSTEM-AUDIT-REPO-FLOWS`; deploy-path
evidence found here was written onto that row (F9) rather than analysed. The monthly DEEP-AUDIT lane is not
duplicated. Nothing on the order path was changed: those findings are filed.

**Input checked, not trusted: the schema artifact** (claude.ai/artifact/6kUJ5pa8HoQHNvpYXVj59f, "as
documented 08:30Z"). Two of its claims are wrong against live data, and one is incomplete:

| Artifact claim | Verdict | Evidence |
|---|---|---|
| "A 5-minute pull … may be why the work-queue card looks stale" | **Refuted** | VM served 1273 rows vs 1274 on `main`; brief `treeState: synced` (F7) |
| `TRADER ==> PROP` (the trader drives the prop venues) | **Wrong shape** | The trader only emits tickets. `ict-prop-executor@{tradeify_1,velotrade_1}.timer` (every 5 min at :03) drive DXtrade; breakout_2 is driven by the phone executor, which posts `/api/bot/prop/report` (F5, F6) |
| "Wake comments … that's how the manager hears about trade events" | **Incomplete** | #17895 carries live-review-due, short-hold, research watchdog and SLO comments. It carries no trade open/close/reject events and none of the VM operator alerts (F1, F3) |
| (missing) VM → trainer journal pull | **Added** | the trainer pulls `trade_journal.db` (2.44 GB backup) and the JSONL logs over SSH from the VM (F11) |

---

## Findings

### F1 — VM operator alerts persist on the VM, but no manager surface carries them (MEASURED)

- `src/runtime/execution_diagnostics.py::_append_operator_alert` writes 14 alert kinds (14 call sites, counted by grep) to
  `runtime_logs/operator_alerts.jsonl`: all_accounts_failed, execution_failure, stuck_strategy,
  orphan_reconciliation, orphan_created, orphan_rollup, naked_position, close_failure, daily_dd_switch,
  bybit_protection_refused, prop_sizing_refusal, stuck_package_sweep, exchange_orphan_adoption and
  monitor_blindness. Each kind is also enqueued to `pending_pings/` and sent to Telegram.
- **Population:** `GET /api/diag/log_file?name=operator_alerts&lines=600`. The read was complete: 539 rows
  from 2026-10-02T01:05Z to 2026-11-04T18:07Z, not truncated.
  - **2026-11-04, 00:00–18:07Z: 30 alerts.** 14 all_accounts_failed, 10 stuck_strategy, 4
    orphan_reconciliation and 2 close_failure.
  - Three of the all_accounts_failed rows are the operator's pasted case:
    `ict_scalp_sol_5m SOLUSDT … bybit_1: slice_budget_exhausted` at 09:53:42, 10:06:58 and 10:12:05Z.
- **Manager surfaces, same window: 0 of the 30.**
  - `GET /api/bot/work/report?since=2026-11-04T00:00:00Z` holds 19 hourly `digestLog` entries
    (00:01–18:01Z). None contains "ALL accounts", "slice_budget" or "operator_alert" (grep count 0).
  - `GET /api/bot/work/brief` also returns grep count 0.
  - `GET /api/bot/notifications` shows only the current banner per kind (2 banners). It keeps no history.
- **Why:** the digest (`attention_watch.py`) is built from the work registers: pipeline, soaks, research and
  checklist. `operator_alerts` appears 0 times in `attention_watch.py`, `work_digest_now.py` or
  `work_report.py`. The ring is readable, but nothing tells the manager to
  read it, so the operator becomes the transport (PI-20261104-BCZDXJNR-0002).

### F2 — Most Telegram producers have no durable sink at all (CODE, probe stated)

- **Population:** `src/runtime/telegram_channels.SENDERS`, the repo-wide table that
  `tests/test_telegram_channels.py` keeps complete. It lists **82 sending files**.
- **Probe:** a grep of each file for a durable-sink marker: `operator_alerts`, `.jsonl`, an outcome record, a
  `red_flags` write, a pipeline write, a GitHub issue or comment write, or an `/api/bot/` post.
  - Positive control: `execution_diagnostics.py` is detected.
  - Upper bound: a file can persist through a helper the grep cannot see. Re-verify file by file in the build.
- **Result: 37 of the 82 files have no marker.** By kind:
  - **Alert-class:** `check_heartbeat.py`, `check_ib_gateway.py`, `db_integrity_alert.py`,
    `account_reachability_alert.py`, `exit_loop_health.py` and `startup_env_check.py`.
  - **Restarts and red flags:** `boot_audit.py` (restart), `telegram_split.red_flag_broken` and
    `prop_executor_tick.sh` (both red_flag, the no-halt flags).
  - **Prop:** `prop_fills_staleness.py` and `phone_trail.py` (prop_alert).
  - **Other ops alerts:** `secret_scan.py`, `trainer_disk_alarm.py`, `phone_hb_alert.py` and
    `system_action_cancel_guard.py`.
  - **GitHub-side:** the workflows `guards.yml`, `claude-run-failure-alert.yml`,
    `research-loss-detector.yml` and `external-{issue,comment}-alert.yml`.
- `send_telegram_direct` (`src/runtime/notify.py`) is the one chokepoint every helper funnels through. It
  mirrors each message to FCM (the operator's phone) but **writes no ledger**. These alerts therefore reach a
  human's phone and nowhere Claude can read.

### F3 — The only push into the manager is ops-flags PR #17895, and the VM alerts never use it (MEASURED)

- PR #17895 was opened 2026-10-13 and is still a draft. It has **632 comments** (last 17:56:06Z today).
- **Population:** the newest 12 comments (14:41–17:56Z). Ten are LTR wakes (`live-review-wake.yml`, a
  GitHub cron `*/5 * * * *`), one is short-hold-closed and two are research watchdog.
  - The code also posts from `research_slo.py` and `desk_wake_marker.py`.
  - **None comes from the VM's alert producers.**
- Comment bodies run **490 to 35,485 characters**. Every LTR wake carries its full packet into the
  manager's context.
- **Subscription is per session.** A rotated or new manager must re-subscribe, and a PR's events go to one
  session at a time.
  - **UNVERIFIED:** whether Manager Session 2026-11-04a is subscribed. I cannot read another session's
    subscriptions.
- Producers on GitHub cron inherit its documented lateness. `work-digest.yml` records a `20 5 * * *` cron
  that ran about 4h50m late.

### F4 — Inbound: operator text in Telegram never reaches Claude (CODE)

- `src/bot/claude_bridge.py:234-265` handles the operator's free text in the bridge bot. It parses the text
  as a prop report command, or answers *"Not a prop command … (For Claude/ops, use GitHub or a new
  session.)"*.
- Decision **buttons** do arrive: `claude_decision_bot` writes the answer into the work object.
- So the operator can answer a typed question, but cannot ask the manager anything through Telegram. A
  typed message is dropped, with a hint sent back.

### F5 — Prop position visibility: the DXtrade executor reads positions and leaves them out of its status report (CODE + MEASURED)

- **Root cause.** `src/prop/prop_executor.py` reads positions every cycle (`adapter.read_positions`, :1106).
  - `DXtrade.read_positions` raises `LookupError` when it finds no table (`dxtrade.py:5614-5619`), so a
    returned list is a clean read.
  - The `account_status` report at **:1259-1263** sends only `balance`, `equity`, `unrealized`,
    `realized_today` and `day_start_balance`.
  - `positions` and `positions_state` are never added. Every reader keys on `positions_state == "read"`:
    `system_invariants.py:952`, `prop_overview.py:234` and `phone_reconcile`.
- **Live, 18:18Z** (`/api/bot/prop/status?account_id=…`):
  - **tradeify_1:** `raw` = `{balance 9674.62, equity 9680.13, unrealized 5.51, source prop_executor}` and
    no positions field. At the same moment fill **221** (ETHUSDT long 0.72, entry 2426.28) has been open
    since 17:03:31Z.
  - **velotrade_1:** `unrealized: null`, so the overview falls back to `mark_estimate` 3.06 (ESTIMATED).
    Fill 220 (0.36) is open.
- **Prop trades are placed.**
  - **Both accounts:** ticket `trend_donchian_eth_prop` at 16:01:25Z, placed at 16:03:39Z (velotrade_1)
    and 16:04:04Z (tradeify_1), open at 17:03:06Z and 17:03:31Z.
  - **Earlier closed round trips** (last 8 tickets per account): 10-28 SOL, 10-29 ETH and 11-02 ETH.
  - `/api/bot/prop/reconcile` reports `unacted_count 0`.
- **Unexplained:** placed → open took **about 59 minutes on both accounts**. Either the entry rested, or
  the fill read lags by up to an hour. To be measured in the fix PR.
- **Fix (Tier 2, report path):** add `positions_state: "read"` and `positions: [p.as_dict() …]` to that
  dict, the same shape `phone_executor.py:431-442` posts. Filed on the existing row
  `AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE` with the exact change.

### F6 — breakout_2 "0 open" is a true read; the trade's fate is what goes unrecorded (MEASURED)

- The phone posts `positions_state: "read"` with `positions: []`, a real venue read showing 0.
- **The open question is ticket `prop-manual-8468ab1f682f`** (15:00:28Z, ETHUSDT long 0.29, SL 2366.79).
  - It reads `placed` / `op_status open`, with fill 215 `placed` at 15:05:34Z and no open or close fill
    after it.
  - `closed_orders_state: "not_reported"`. `phone_events` show `positions_miss closed_empty_unconfirmed`
    (13:36Z, 14:09Z, …).
- Whether the order never filled, or filled and stopped out, is **unrecorded**, because the phone executor
  reports no closed orders.
- The ticket text itself warned: risk $17.50 against $11.94 left to the drawdown floor.
- Filed on `BREAKOUT-UNRECORDED`.

### F7 — The Overview work-queue card is stale because the register is (MEASURED)

- **The card is faithful to its source.** `GET /api/bot/work/snapshot` served 1273 rows; `main` had 1274.
  The work brief's freshness block reads `treeState: synced`. The 5-minute VM pull is not the cause.
- **The register is stale:**
  - **in_flight:** 38 rows. **33 were last updated more than 48h ago** (median 79h; 4 more than 7 days).
    Examples: PACE-W40 (10-28), COST-STACK-HARNESS-RESOLVER (10-28), RESEARCH-OPS-20261028-0848.
  - **Newest terminal row:** ML-ENTRY-RISK-META, 2026-11-02T21:22Z, about 45h ago.
  - **Recent updates:** 9 of 1274 rows changed in the last 24h.
- **The dispatch step was skipped.** This lane's own row read `state: queued, lane: null` at 18:18Z while
  the lane was running. Manager SKILL step 3 ("set in_flight with its lane") was not applied. The card's
  "next" list therefore shows work that has already been dispatched.
- **This recurs.** `AUD-20261019-STALE-INFLIGHT` counted 32 stale rows on 10-28, and that row was dropped in
  the 10-29 bulk reset.
- **Also:** `/work/checklist` is **4.19 MB**. The comment in `work.py` still says "~435 KB".
- Filed: `CHECKLIST-STATE-TRUTH`.

### F8 — The trader's tick is about 115 s, which sets signal latency (MEASURED)

- **Population:** `GET /api/diag/tick_cost` at 18:22Z, 13 ticks since process start (17:45:06Z).
- **Tick duration:** mean 115.0 s, last 119.1 s, max 139.2 s.
- **Where the time goes:**

  | Hook | Mean | Share of tick time |
  |---|---|---|
  | `run_one_tick` | 79.3 s | — |
  | `pipeline.signal_build` (299 calls) | 2.45 s per call | 49.0% |
  | `order_monitor` | 31.9 s per tick | 27.8% |
  | broker naked-position sweep (equity) | 8.0 s | — |
  | `reconcile_open_trades` | 6.8 s | — |
  | orphan reconcile | 6.3 s | — |

- **Effect on signal timing.** For 1h closed-bar legs, `order_packages.created_at` lands **17–226 s after
  the bar close** (n=8, journal tail 2026-11-04). A 5m scalp is therefore evaluated at most about every 2
  minutes, which is up to 40% of its bar.
- **Package → trade row is fast:** n=40, median 2.5 s, max 7.6 s.
- No open row covered this. Filed: `TICK-DURATION-115S` (Tier 2, not fixed here).

### F9 — 21 trader restarts in about 18 hours (MEASURED; belongs to REPO-FLOWS)

- **Population:** `journalctl ict-trader-live` from 00:00 to 18:18Z, a complete scan of 236,703 lines.
- It shows 21 `Started ICT Trader Live` entries. One, at 17:01:23Z, came a minute after an hourly bar close.
- Running sha `156f1b1a8` vs on-disk `2c37e7330`.
- Written onto `SYSTEM-AUDIT-REPO-FLOWS` (deploy path); not analysed here.

### F10 — Read-path latency (MEASURED, from this container)

| Route | Measured |
|---|---|
| `/work/brief` | **60.85 s** cold (1 of 3 calls); 0.47 s and 0.74 s warm |
| `/prop/overview?window=7d` | 3.1–5.1 s for 2.6 KB |
| `/work/snapshot` | 0.97–3.57 s |
| `/work/checklist` | 1.2–1.5 s for 4.19 MB |
| `/config` | 1.42 s |
| `/notifications` | 0.47–0.60 s |

The API shares the VM with the 115 s tick (F8). Written onto `UI-LIVE-STACK-REDESIGN`, the live-UI design
row.

### F11 — Trainer ↔ VM ↔ repo (MEASURED; no defect)

- **Trainer → VM mirror** (`ict-trainer-publish.timer`, every 2 min): `mirror_age_seconds` 114–118 at 18:25Z.
  Fresh.
- **VM → trainer journal pull** (`/api/bot/ml/db_pulls`, last 50 rows): `trade_journal.db` ok at 00:55,
  04:18 and 08:05Z, none in the 10h20m after.
- **Training cadence:** `cycles_24h` 2; the trainer timer is `OnCalendar=daily`.
- So training data runs up to about a day behind the journal. That is the design for a daily retrain, not a
  defect. **Disposition: no row.** Revisit only if something starts consuming trainer outputs intraday.
- Repo → VM is git-sync every 5 min (REPO-FLOWS). Trainer → repo goes through research results PRs
  (REPO-FLOWS).

### Checked and clean (the denominator)

- **All 28 trader-VM timers** read (`/api/diag/timers`, `could_not_look` 0). The one inactive timer,
  `ict-ib-gateway-watchdog.timer`, is expected: it runs on the IB Gateway VM since the 2026-06-10 split.
- **Prop status freshness:** under 3 min on all 3 live prop accounts.
- **Prop reconcile, breakout_2 only:** 0 unacted tickets out of 50 (`/api/bot/prop/reconcile`). The other two prop accounts were not read here.
- **System-action results** come back as comments on the issue the session opened, so the requester can
  read them. Their Telegram copy (`notify_run.sh`) is a duplicate, not the only copy.

---

## Design: pending DEEP-AUDIT-20261104

On hold by manager direction (2026-11-04 18:35Z, relaying the operator, 18:33Z): the audit results come in
before any restructuring design is written. The routing design for alerts → manager is written once the
DEEP-AUDIT-20261104 PR lands, using both audits. The findings above, and the rows they map to below, are final
for this pass.

---

## Finding → row / item → due_by (audit-outcome contract)

| Finding | Row / item | due_by | Tier | State after this lane |
|---|---|---|---|---|
| F1 VM alerts invisible to the manager | `ALERT-LEDGER-TO-MANAGER` (new) · existing `PI-20261104-BCZDXJNR-0002` (the slice refusal itself) | 2026-11-11 · 2026-11-06 | 2 | queued |
| F2 37 of 82 senders with no durable sink | `ALERT-LEDGER-TO-MANAGER` (design pending) | 2026-11-11 | 2 | queued |
| F3 ops-flags is the only push; oversized comments; subscription assumed | `ALERT-LEDGER-TO-MANAGER` (design pending) | 2026-11-11 | 2 | queued |
| F4 operator Telegram text never reaches Claude | `ALERT-LEDGER-TO-MANAGER` (design pending) | 2026-11-11 | 2 | queued |
| F5 DXtrade executor omits positions; placed → open about 59 min | `AUD-PROP-VENUE-POSITIONS-TRADEIFY-VELOTRADE` (existing; root cause and exact fix added) | 2026-11-07 | 2 | queued |
| F6 breakout_2 placed ticket with no recorded fate | `BREAKOUT-UNRECORDED` (existing; evidence added) | 2026-11-11 | 2 | queued |
| F7 stale register drives the stale card | `CHECKLIST-STATE-TRUTH` (new) | 2026-11-06 | 1 | queued |
| F8 115 s tick | `TICK-DURATION-115S` (new) | 2026-11-10 | 2 | queued |
| F9 21 restarts per day | `SYSTEM-AUDIT-REPO-FLOWS` (existing; evidence added) | 2026-11-07 | 1 | queued |
| F10 read latency | `UI-LIVE-STACK-REDESIGN` (existing; evidence added) | 2026-11-10 | 1 | queued |
| F11 trainer data about 1 day behind | none: by design (daily retrain), stated above | — | — | killed with reason |
| Schema artifact errors | this doc's input table (corrections) | — | — | done |
