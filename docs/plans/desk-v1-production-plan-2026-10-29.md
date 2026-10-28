# Trading desk — production-ready V1: definition, measured gaps, Thu–Sun build plan

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `DESK-V1-PRODUCTION-PLAN` (session_01AFoLuKietgEgZagdrtFF18, dispatched by Manager session_01AFoLuJi1vLTnYv9LbP6539)

**Why this exists.** Operator priority #2, 2026-10-28 ~20:55Z, verbatim: *"Trading desk - continuing to research and optimize the
flow, I want this project to be fully in production by the end of the week (at least a production ready V1, we will continue to
iterate and improve)."* This plan defines V1, measures today's gaps against it, and gives a Thu 10-29 → Sun 11-01 build plan. Each
item has an owner lane, a cost ceiling, a Tier, and the observation that proves it. It authorizes nothing. Each change is landed
by its own row at its own Tier. Rows: `DESK-V1` (umbrella, the done test) and `DESK-V1-*` (build items), all in
`docs/claude/work/checklist/`.

Contract of record: [`.claude/skills/trading-desk/SKILL.md`](../../.claude/skills/trading-desk/SKILL.md),
[`DESK-BRIEF.md`](../../.claude/skills/trading-desk/DESK-BRIEF.md), `config/mandates.yaml::MD-TRADE-DESK`,
[`OPERATING-PLAN` § 2](OPERATING-PLAN-2026-09-21.md) (the ladder, the demo floor, the mechanical soak). Practice principles cited
as T#/M#/R# are from [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
That doc's own status line reads `unknown / never verified`. It is used here as the dispatch asked: as the stated rationale, never as a gate.

---

## 0. What the S0 FAIL changes (read first)

The DESK-LIFECYCLE-S0 full run (#20967) used option C4E, 520 pairs, 938 trades walked. Evidence:
`comms/research/desk_lifecycle/full-c4e/`, [doc § 7.5](../research/desk-lifecycle-factorial-2026-10-28.md). Its registered verdict
is **FAIL**:

| contrast (mean [95% CI]) | Claude entries (n 473) | random entries (n 465) |
|---|---|---|
| Claude whole-trade management vs HOLD | **−0.159 [−0.261, −0.041]** | **−0.124 [−0.197, −0.043]** |
| vs matched random intervention | −0.013 (n.s.) | −0.046 (sig.) |
| entry value under HOLD (Claude − random) | −0.090 [−0.277, +0.097], indeterminate | |

The loss sits in the non-hold actions (n 1,155): `tighten_sl` (n 981) costs −0.097 per action and `move_tp` −0.155 (both CIs exclude 0).
The 2,001 holds were worth +0.142 versus closing. The only positive pocket is a close at ≤ −0.5 R, and it is not significant. DESK-MGMT-S0 found the
same direction: a single +1 R intervention on the 4 real-money 2h/4h legs did not beat holding (n 176).

**So V1 is built on these four decisions:**

1. **Management default = hold to the bracket, plus a mechanical time exit.** The action space is every bracket move, not only tightening (operator 2026-10-28 ~21:08Z; § 5b). Each class graduates to executed separately, on its own test. No Claude in-trade action is *applied* on any desk or strategy
   trade until that action class clears its own registered OOS test against hold AND a matched random intervention, net of cost (T1, T8,
   M6, M10). `tighten_sl` → advice-only was decided by the operator tonight. The data-backed extension to every other in-trade class is item
   **Thu-1**. The desk keeps *recording* in-trade advice, because every recorded call is a priced label (M1), but nothing applies.
2. **Claude's role in V1 is entry generation on the demo floor, plus labels.** Entry value is indeterminate, not negative. The demo floor
   is a mechanics stage, not an edge stage (R3; OPERATING-PLAN § 2 "Stage 1 is the DEMO FLOOR"). Every non-retired leg trades there, so
   desk entries trade on `bybit_1` / `alpaca_paper` / `ib_paper` and are graded against random entries (the DESK-13 gate).
3. **No per-bar management sessions on desk trades.** The short-hold lane spawns one session per trade and decides every 5 m bar. That is
   the "frequent small tweaks" pattern (T5) which S0 measured as the loss, and it costs capacity (item Fri-2).
4. **Experiments run in parallel, offline, and never on the trade path** (§ 5). They are the loss-cut hypothesis, entry value at the live
   contract, and a supervised act-vs-hold student on the 12,500 S0 labels.

---

## 1. Definition: production-ready V1

V1 is a desk that **runs unattended on the demo floor, trades with both brackets and no Claude hand on the open position, alerts when
any step stops, grades every decision, and feeds every graded decision into a dataset build.** No real money.

### 1.1 What runs automatically, on what cadence and trigger

| step | runs on | cadence / trigger | exists today? |
|---|---|---|---|
| scan packet (1 h) | VM `src/runtime/desk_packet_wake.py` → `desk/decisions` | each UTC hour (fallback `desk-scan-packet.yml`) | **yes**: every hour on 10-28 had a packet (git log `origin/desk/decisions`) |
| event packets (5 m) | VM `src/runtime/desk_event_trigger.py`, `config/desk_triggers.yaml` | ATR burst, level break/sweep, momentum burst; rate-limited | **yes**: 24 trigger rows since 10-26 |
| wake (decision) | fresh repo-less Sonnet session, `DESK-BRIEF.md` + `desk_write.py` | one per packet | **partial**: spawned by the manager session. If no manager runs, no wake (§ 2 G1) |
| intake → order | VM `scripts/ops/desk_intake.py` → `Coordinator.multi_account_execute` → each account's `RiskManager` | per live row (~2 min watch) | **yes** (2 accepted, 0 filled; § 2 G4) |
| exit | venue SL/TP bracket; time exit at `max_hold_min` | venue / leg | brackets yes; **time exit unobserved** (no fill yet) |
| grading | `desk-decisions-mirror.yml` → `desk_outcomes.py`, `claude_role_grade.py` → `comms/desk/role_grade.json` | hourly | **yes** but `no_trade` unpriced (DESK-20) |
| learning feed | `ml/datasets/families/claude_judgments.py` → `comms/desk/consumed.jsonl` | each dataset build | **no**: `consumed.jsonl` has 0 lines |

Principles: T5 (the check-in clock is separate from the action rate; "no action" is a recorded decision), M8 (cadence and trigger set
are factors to evaluate, so trigger labels are kept).

### 1.2 What it may do

- **Entries:** `propose_entry` on the leg's `account_symbols` only: `bybit_1` (6 perps), `alpaca_paper` (5 ETFs), `ib_paper` (3 CME
  micros). Real money, mirrors and prop stay **closed** behind `MD-TRADE-DESK.functions.entry_generation.blocked_until` (DESK-13: OOS
  edge vs random entries, net of the full cost stack, n ≥ 30). The intake entry gate closes the floor for all accounts if any real-money
  account rosters the leg (`desk_intake.entry_gate`).
- **Management:** none applied (§ 0.1). Exits are the venue bracket and the time exit only. Every `close` of a desk trade records
  `strategy_close` (#20487, merged 10-27). Any other close reason is a bug.
- **Never:** size, a `mode:`/`execution:`/roster write, removing a bracket, a halt (SKILL § 0).

### 1.3 Safety rails (all exist; V1 *verifies* them on a real fill)

Both brackets at entry (intake refuses without) and a real TP (TP doctrine, `p_hit` in [0.10, 1)). Sizing only through each account's
`RiskManager.approve()`. The declared slice on `bybit_1` (0.5, own budget). `daily_dd_switch` armed at 3 % on all three demo books
(read from `config/accounts.yaml` 10-28). `exclusive_hold_refusal` on the non-slice books. The market-hours gate. `max_hold_min` ≤ 60.
Revert = `execution: shadow` (never a halt). Mandate: `MD-TRADE-DESK` (granted). V1 asks for no new mandate.

T4 (stops from volatility; the desk's `stop.basis` is `atr_multiple`/`swing_level`), T3 (net of full cost), T7 (giveback lives at the
account/day level, i.e. the DD switch, not per trade).

### 1.4 Monitoring and alerts (V1 = each failure class reaches ONE flag within 15 min)

| failure | alert today | V1 |
|---|---|---|
| producer stops / packet build/commit fails | `attention_watch.probe_desk_wake_post` (> 3 h or `could_not_*`) | keep |
| **packet landed, no decision row** | **none**: the receipt reads `posted` even when no wake ran | new probe `desk_row_missing` (> 15 min) — Thu-2 |
| **desk entry refused / rejected / unfilled** | **none**: both rejections on 10-27 were found by sessions | one ping per refused desk package — Thu-2 |
| desk fill / close | generic trade-update ping (UNVERIFIED that it covers `claude_desk`) | verify on the soak trade — Fri-3 |
| feed gap (web used) | `desk_feed_gaps.py` → pipeline item | keep |
| grading stale | `check_claude_grade_loop.py` `role_grade_fresh` | keep |

### 1.5 Grading and the learning loop

Every decision gets a priced label: a `propose_entry` is replayed on real candles from `info_cutoff_at`, and a `no_trade` is priced as its
best baseline bracket by DESK-20 (M1: path-dependent, cost-net). A live fill also gets its actual realized R next to its replay
(a live/backtest mechanics check, not edge; R3). The desk's DESK-13 score is vs random entries at the same decision points, net of
cost (M6). The learning loop: one `claude_judgments` dataset build lists desk rows in `consumed.jsonl`. The S0 per-check-in labels
(12,500) are the first training set for a supervised act-vs-hold student (M9; never imitation of Claude's choice as the target).

### 1.6 "Done" is measured by (the `DESK-V1` row's observation)

All of these must hold **on the VM / `main`, observed, not merged**:

1. **Liveness:** 48 consecutive hourly packets each have a row, OR every miss raised the `desk_row_missing` flag within 15 min.
2. **Latency:** p95 of `judged_at − info_cutoff_at` ≤ 300 s over those 48 rows (today: median 163 s, max 774 s, n 62 since 10-27).
3. **Mechanics soak (1–2 clean trades, OPERATING-PLAN § 2):** ≥ 1 `claude_desk` trade on `bybit_1` shows the full chain. That chain is:
   row → intake `accepted` → venue fill → both brackets read back at the venue → exit by `take_profit` / `stop_loss` / time
   (`strategy_close`) → `outcomes.jsonl` row → `role_grade.json` priced. `alpaca_paper` and `ib_paper` follow on their first open market
   (ETFs: Mon 11-02; CME micros: Sun 11-01 ≥ 23:00Z). They are not V1 blockers, and the plan says so rather than calling V1 complete for them.
4. **No applied in-trade action** on any class without a passed test: `live_review_rows_watch` shows 0 `dispatched` non-close actions after Thu-1.
   (Closes: per the operator's decision on Thu-1's ask A1.)
5. **Grading:** `role_grade.json` updates hourly with `no_trade.n_priced` growing ~24/day.
6. **Learning:** `comms/desk/consumed.jsonl` has ≥ 1 build line.
7. **Alerts:** each V1 alert class in § 1.4 has fired once (observed, or by a recorded test fire on the VM).

---

## 2. Gap list — MEASURED 2026-10-28 20:56–21:20Z

Sources: direct diag (`scripts/ops/diag_fetch.sh`, served by `ict-bot.duckdns.org`) and `git log origin/desk/decisions`. Populations stated.

| # | gap | measurement | V1 item |
|---|---|---|---|
| G1 | **Wake spawn depends on a live manager session.** No independent spawner. | 10-27T00Z→10-28T20Z (45 h): 7 hours had a packet and no row (08, 09, 13–17Z on 10-28). Cause recorded on DESK-6: an operator-directed usage throttle at a weekly plan usage of 94–98 %. The producer receipt read `posted` throughout. No alert fired. | Thu-2, Thu-3 |
| G2 | **Capacity is the binding constraint.** | Measured per-wake cost: $0.34–0.47 (n 4, DESK-6). Hourly ≈ $11/day plus trigger wakes: 24 trigger rows in ~2 days. The weekly plan limit reached 94–98 % on 10-28. | Thu-3 (ask A3) |
| G3 | **Wake latency** | `judged_at − info_cutoff_at`, n 62 rows since 10-27: median 163 s, max 774 s. | measure only; target in § 1.6 |
| G4 | **Zero desk demo fills ever.** | 71 rows total (66 `no_trade`, 2 live `propose_entry`, 3 shadow). Both live proposals were accepted by intake and rejected by risk. 10-27 17:19Z AVAX was rejected `opposite_slice_one_way_book`. 10-27 18:07Z BTC was rejected `risk_refused: available_usd=0.00` (bybit_1 margin starvation, fixed by leverage 10 on 10-27 23:55Z, row BYBIT1-MARGIN-STARVED). | Fri-3 (ask A2) |
| G5 | **The desk does not propose at the live contract.** | 0 leg-symbol proposals in the ~27 h since the margin fix. DESK-18E: live ≤ 60 min holds versus 4/12/48-bar priced rows, where all fitting rows are net negative. Live was 0/29 and the shadow lane 7/29. This is honest behaviour, not a fault. But it means V1's soak never happens by itself. | ask A2 |
| G6 | **`opposite_slice_one_way_book`** | 1 of 2 desk rejections. On a one-way Bybit book a desk long cannot open while a strategy slice holds the symbol short. Of 6 desk symbols, 4 had strategy shorts open on 10-27 23:49Z (BYBIT1-MARGIN-STARVED note). | Fri-3: the wake must know the book; packet `system_book` carries open positions. Brief check, Tier 1 |
| G7 | **In-trade actions still apply** | `config/live_trade_review.yaml apply_mode: apply`. The operator decided tighten → advice-only tonight; not yet in config on `main` at 71ead79f. `live_review_rows_watch`: 2 dispatched of 25 rows since 10-26 (closes). `reviews.jsonl` (124 rows): hold 53, no_recommendation 46, flag_mechanics 23, close 2. | Thu-1 |
| G8 | **`no_trade` unpriced** | `role_grade.json` 19:11Z: 70 decisions, 67 `not_computable` (65 = DESK-20 not built); `vs_random` n 1. | Fri-1 |
| G9 | **Learning loop not closed** | `comms/desk/consumed.jsonl` 0 lines; DESK-11 blocked on CJ-2-DATASET. | Sat-1 |
| G10 | **Producer receipt `latency_s` is negative** | receipt 20:54Z: `posted_at` 20:02:33Z, `built_at` 20:03:33Z, `latency_s` −59.8. Either `built_at` is stamped after the post or the fields are swapped. The liveness number is meaningless as published. | Thu-2 (Tier 1 fix) |
| G11 | **Per-trade short-hold sessions** | 1 managed package ever (pkg-613daaec5b7e4a88, $0.59, 3 rows, closed −0.88 R before the stop). S0 says that pattern costs R. | Fri-2 |
| G12 | **No desk scorecard line in the daily brief** | DESK-22 blocked; the operator sees desk state only via sessions. | Sat-2 |
| G13 | **Stale rows** | DESK-3-EXECUTORS reads `in_flight` but #20487 merged 10-27 06:07Z; DESK-17 says `execution: shadow` but `config/strategies.yaml` reads `execution: live`. | noted on `DESK-V1`; the manager re-states them |

---

## 3. Build plan, Thu 10-29 → Sun 11-01

Cost = dollar ceiling on the lane's row (plan usage, no API credits). Tier per CLAUDE.md. "Proof" = the observation that closes the item.

### Thursday 10-29

| id | item | owner | ceiling | Tier | proof |
|---|---|---|---|---|---|
| **Thu-1** `DESK-V1-MGMT-ADVICE-ONLY` | `config/live_trade_review.yaml`: every in-trade class except `close` → recommend-only on every account (tighten by operator decision tonight; `move_tp`/`partial_close`/`widen_sl`/size by the S0 record, data-backed: decide, ship, notify). `close` follows ask **A1**. | manager | $3 | 3 (data-backed) | VM `live_review_rows_watch`: next non-close row reads `not_dispatchable`/recommend; `/api/bot/config` shows apply_mode per class |
| **Thu-2** `DESK-V1-ALERTS` | (a) `attention_watch` probe `desk_row_missing`: newest packet on `desk/decisions` with no row after 15 min → one flag; (b) one ping per `claude_desk` package rejected / refused / `expired_unfilled`; (c) fix receipt `latency_s` sign/semantics (G10); tests for each | lane, Sonnet | $5 | 1 (observability) | each alert fired once on the VM (a test fire recorded in `runtime_logs`), receipt `latency_s` ≥ 0 |
| **Thu-3** `DESK-V1-SPAWN` | Make the wake spawn independent of manager liveness. The recommended design: one scheduled task at :07 each hour (fresh session per fire) runs the wake prompt. The wake already exits when nothing is due. The event-trigger wakes keep the manager path. Plus a stated weekly desk budget and the § 7.3 degrade order (ask **A3**) | manager | $2 | 2 (new scheduled job) | 24/24 rows in a day with no manager session running; budget written on `DESK-10-CAPACITY` |

### Friday 10-30

| id | item | owner | ceiling | Tier | proof |
|---|---|---|---|---|---|
| **Fri-1** DESK-20 (existing row) | price every `no_trade` as its best baseline bracket on the DESK-7 harness | lane, Sonnet | $6 | 1 | `role_grade.json` `no_trade.n_priced` ≥ 24 and rising hourly |
| **Fri-2** `DESK-V1-NO-PERBAR` | desk trades get no per-bar short-hold session. The manager stops spawning `short-hold-wake` for `claude_desk`. The packet keeps landing as data. Strategy legs in `config/short_hold.yaml` follow Thu-1 (advice-only rows still written if capacity allows) | manager | $1 | 2 | next desk fill: no short-hold session in `list_sessions`; exit by bracket/time |
| **Fri-3** `DESK-V1-SOAK` | the first clean `claude_desk` trade on `bybit_1` (ask **A2**). The wake checks `system_book` for an opposite strategy slice before proposing (G6, brief text, Tier 1) | manager + one wake | $2 | 3 via A2 | journal `trades` row `strategy_name=claude_desk`, `account_id=bybit_1`, venue order id, both brackets read back, exit reason ∈ {take_profit, stop_loss, strategy_close}, `outcomes.jsonl` row |

### Saturday 10-31

| id | item | owner | ceiling | Tier | proof |
|---|---|---|---|---|---|
| **Sat-1** DESK-11 (existing row; unblock) | the `claude_judgments` build consumes desk rows + S0 labels on the trainer VM | lane, Sonnet (model-training skill) | $6 | 1 | `comms/desk/consumed.jsonl` ≥ 1 line on `main` |
| **Sat-2** `DESK-V1-SCORECARD` (slim DESK-22) | one desk line in the daily brief: packets, rows, misses, proposals, intake verdicts, fills, closes by reason, graded n, vs random | lane, Sonnet | $4 | 1 | brief section "what is running" shows the line with stated populations, nulls as "—" |
| **Sat-3** experiments registered | the § 5 units authored and pre-registered in `research/queue/` | research-ops | $4 | 1 | three unit yamls on `main`, each with a rule registered before its run |

### Sunday 11-01

| id | item | owner | ceiling | Tier | proof |
|---|---|---|---|---|---|
| **Sun-1** `DESK-V1` acceptance | Run § 1.6 checks 1–7 and write `comms/desk/v1_acceptance.json` with each check's reading and population. Anything failing becomes a row. Report V1 in the Monday sync brief | manager-dispatched lane, Sonnet | $3 | 1 | the record on `main`; brief section "what moved" |
| **Sun-2** `ib_paper` first desk trade | CME micros reopen Sun ≥ 23:00Z (US DST ends 11-01) | wake | — | covered by A2 | as Fri-3 on `ib_paper`; `alpaca_paper` slips to Mon 11-02 (stated, not hidden) |

**Plan total: ~$36 of lane ceilings**, plus ~$11/day of hourly wakes (measured). Trigger wakes come on top of that.

---

## 4. Operator asks (exact)

- **A1 — `close` on strategy trades: apply or advice-only?** `MD-TRADE-DESK` `close` is currently applied (2 dispatched since 10-26).
  S0: `close` +0.078 [−0.18, +0.28], n 72, n.s.; the pocket "act at ≤ −0.5 R" +0.129, n 56, n.s. **Recommended: advice-only until the
  loss-cut unit (§ 5 E1) passes.** No test has shown a gain from it, and the hold-vs-act evidence favours holding. Alternative: keep
  applying `close`, as the one class without a significant negative.
- **A2 — one mechanics probe per demo venue.** The desk honestly proposes ~0 entries at the ≤ 60 min contract (G5), so the mechanical soak
  cannot complete by itself. **Recommended: authorize one `mechanics_probe: true` desk entry on `bybit_1` now (margin fixed), and on
  `ib_paper` / `alpaca_paper` at their first open market.** Each is demo-only, both brackets, sized by the account's RiskManager, and
  excluded from edge grading (as the two 10-27 probes were). Alternative: wait for an organic proposal (no date can be given).
- **A3 — the desk's weekly capacity budget.** The desk already competes with everything else: the weekly limit hit 94–98 % on 10-28 and 7 wakes
  were dropped. **Recommended: hourly wakes stay (~$11/day); trigger wakes capped at 12/day; no per-bar management sessions (Fri-2).
  Under a breach the order is design § 7.3: offline sessions → rho → triggers → lengthen the hourly cadence to 2 h.** Never stop the
  producer or the grading.

V1 needs no other ask. Real-money entries stay behind DESK-13 and are not requested.

**ANSWERED 2026-10-28 ~21:07Z** (operator popups, relayed by Manager session_01AFoLuJi1vLTnYv9LbP6539):
- **A1:** *"Advice-only until tested"*. Built as PR #21026 (Tier 3, hold): global `apply_mode: recommend`.
- **A2:** *"Yes, one probe on bybit_1"*. PR #21028 (Tier 3, hold) raises `desk_write.PROBE_MAX` from 2 to 3, because both 10-27 probes used the cap
  without filling. "Minimal size" is not supported (no size field by design), so `bybit_1`'s RiskManager sizes the probe like any entry.
- **A3:** *"Hourly + ≤12 triggers/day"*.

---

## 5. Experiments running in parallel (offline; never on the trade path)

| unit | question | rule to register before the run | practice |
|---|---|---|---|
| **E1 loss-cut** | Does a Claude `close` at ≤ −0.5 R on new information beat hold AND a matched random close, net of cost, on a fresh window? | n ≥ 126 pairs, weekly-cluster 95 % CI lower bound > 0 vs both; Holm over 1 | T1, T6, M5 (fresh window) |
| **E2 entry value at the live contract** | Do desk entries at a fitting horizon beat random entries at the same decision points? (the DESK-13 gate path; uses DESK-18E's shadow-lane pricing) | `desk_grade.promotion_gate`: OOS vs random, net of full cost, n ≥ 30 | M6, T8 |
| **E3 act-vs-hold student** | Can a supervised meta-model on the 12,500 S0 check-in labels pick the rare positive actions? | Purged walk-forward grouped by trade. Must beat hold, the best rule and random OOS net of cost; agreement with Claude never counts | M1, M2, M9, M10 |
| parked | the LIFECYCLE strategy arm (Claude managing existing legs) | parked, not killed: two negatives (S0, DESK-MGMT-S0). Re-entry = E1 or E3 passes | R5 (more backtests per idea widens the live gap) |

---

## 5b. The full bracket action space: one graduation test per class

**Operator principle, ~21:08Z 2026-10-28 (relayed by the manager), verbatim:** *"active management isn't only tightening - it can be any
movement in either bracket triggered by developments in the live market data"* … *"SL tightening is just one lever"*.

**The action space.** Any move of either bracket, or a reduction, triggered by a live-market development: structure (swing level,
break/sweep), volatility/ATR change, momentum, regime, a scheduled event, or a liquidity level. Both brackets stay in place after
every action (`MD-TRADE-DESK` `never` list). A1 is applied **per class**. Every class starts advice-only: recorded, priced and graded.
A class is **executed** only after its own test passes. The gate is the manager's PR flipping that class alone, which needs per-class
`apply_mode` (build note below).

**What S0 priced** (MEASURED, `comms/research/desk_lifecycle/full-c4e/score.json`; Claude-judged check-ins, C48 contract):
- `tighten_sl`: n 981, −0.097 [−0.140, −0.047].
- `move_tp`: n 45, −0.155 [−0.302, −0.037]. The direction is not split.
- `partial_close`: n 57, −0.001 [−0.112, +0.121].
- `close`: n 72, +0.078 [−0.18, +0.28].
- `widen_sl`: not in the S0 enum, n 0.
- The static `partial_at_1r` rule: −0.018 [−0.045, +0.012] on Claude entries.

`labels.jsonl` (12,500 rows) prices only hold vs close at each check-in. TP extend, TP pull-in, widen and stop-to-structure are
**unpriced**.

**The graduation test (the same template for every class; registered before its run; M4, M5, T1, T3).** A class graduates when all of these hold:
- the action's dR is above BOTH hold AND a matched random intervention of the same class (same count, same direction, random check-in);
- it is net of the full cost stack, with both brackets present after the action;
- it is measured on a fresh window not used to choose the trigger (OOS);
- there are n ≥ 126 trades with the action, the weekly-cluster 95 % CI lower bound is > 0 against both comparators, and Holm runs over the classes tested together;
- it is stratified by leg and regime (T2, M7): a class can graduate for a leg/regime cell only, never pooled across one where it hurts;
- the live advice-only record for that class (`live_review_grade.py` use_rules, ≥ 20 priced calls) does not contradict it.

| class (direction) | trigger families to test | S0 status | Stage A: cheap test, no judging cost | Stage B: Claude-judged confirm |
|---|---|---|---|---|
| `tighten_sl` (incl. to structure) | structure break with the trade, ATR contraction, momentum fade | **negative** (n 981) | done: LTR-TIGHTEN-OPTIMIZE #21003 (61-rule grid; best rule indeterminate on TEST/FRESH) | `RQ-20261028-e1a7-02` (registered, needs GO, ~$140) |
| `widen_sl` (to structure) | liquidity sweep beyond the stop, ATR expansion with the thesis intact | **unpriced** | rule replay on the 1,040 S0 trade paths: widen to the next swing/ATR level on a sweep, with the size cut so risk stays the same (T4). Hindsight-oracle headroom first; stop if the oracle bound is ≤ 0 | only if Stage A's rule beats hold and random |
| `move_tp` **extend** | momentum with the trade, a regime trending, a level broken in favour | **unpriced** (S0 did not split direction) | rule replay: extend to the next structure/ATR target on momentum-with tags (T9: trend legs) | as above |
| `move_tp` **pull in** | momentum against, approaching opposite liquidity, an event inside the hold | **unpriced** | rule replay: pull the TP to the nearest opposing level on momentum-against tags (T9: mean-reversion legs) | as above |
| `partial_close` | at a structure level, an event ahead | ≈ 0 (n 57), the rule ≈ 0 | none new: T10 says partials reshape the distribution and do not add expectancy, so this is lowest priority | E-class only if the operator wants it |
| `close` (loss-cut, thesis invalidated) | ≤ −0.5 R plus new information, a structure break against | n.s. positive pocket | done by § 5 E1 | E1 |

**Why Stage A is cheap.** It replays fixed rules over paths we already have (`comms/research/desk_lifecycle/full-c4e/` pairs plus the
1h candles). That costs plan compute only, with no judge calls. The hindsight oracle bounds the headroom: if even the oracle cannot
beat hold, the class is retired for that leg/regime without paying for judging. That is how 8b01-01 was read (DESK-MGMT-S0). A rule that
beats both comparators then earns a Claude-judged Stage B, at ~$0.05/check-in MEASURED.

**Build note (Tier 3, follows A1).** `apply_mode` today is per account, not per class (`src/runtime/live_review_intent.apply_mode_for`).
Graduating ONE class needs a per-class `apply_mode` map in `config/live_trade_review.yaml`, read in `live_review_apply.run()`. This is
a small change filed on row `DESK-V1-CLASS-GATES`. It is needed only when the first class passes, and nothing graduates this week.

**Coordination.** Lanes `ACTIVE-MGMT-REAL-MONEY-PLAN` and `ML-LIVE-PROMOTION-PLAN` were given the same instruction. This table is the
proposed **single per-class registry**. Those lanes should cite and extend it (real-money legs, model-driven management) rather than
register parallel per-class tests. The manager reconciles the three plans. One unit per class and direction is authored by
research-ops (row `DESK-V1-EXPERIMENTS`).

## 6. Not verified here

- That the generic trade-update ping covers `claude_desk` fills/closes (Fri-3 proves or files it).
- The time exit at `max_hold_min` on a real fill and its close reason (no desk fill exists).
- The cause of the negative `latency_s` (G10). Only the symptom is measured.
- Row cost per trigger wake. Only hourly-wake cost was measured (n 4).
