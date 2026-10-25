# Weekly audit — 2026-10-19 (run 2026-10-21)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-21` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `WEEKLY-AUDIT-2026-10-19` (session_014UeddhjFnc6fSA41bo5V65, dispatched by manager session_01VduHYzdaXe27wTDBLSu8ao) · window 2026-10-14 → 2026-10-21 · live reads captured 2026-10-21 18:13–18:20Z
>
> Monday run skipped during the usage wind-down; run Wednesday. Deep pass = **3 DESIGN CRITICISM** (ISO week 43 mod 4 = 3). First weekly audit under the skill — there is no previous report, so C9 reads closed rows instead.

## 1. Verdict

- **Instruments:** self-tests green — system_invariants 50/50 (48 + 2 added here), checklist, pipeline, research_slo, guard_selftests `--all` rc=0.
- **Invariants:** live payloads pulled directly (diag_fetch.sh): **9 invariants → 8 pass / 0 fail / 1 not-measured.** The one not-measured is INV-NETTED-DUP-UPNL at n=0, which is vacuous. Populations: 3 IB positions, 18 Bybit (trade, protective leg) pairs, 18 journal⇄exchange (account, symbol) pairs, 17 package legs, 657 exit-loop intervals. **Could not look:** ib_live and oanda_practice (dry), plus all 4 prop accounts → finding F2. INV-EXIT-INTERVAL read not-measured before the F1 fix.
- **Placed or refused:** every live account had trade rows in the window, or (for prop) tickets. Every refusal carries a cause. alpaca_live placed 0 of 6 because every signal was a short and `side_filter:long` refused it.
- **Non-TP/SL closes:** 3 of 52 closed rows (2026-10-14→21). The pairs half-open pair 6633/6634 is already filed (BL-20260821-PAIRS-SOL-ETH-STRANDS-ON-EVERY-OPEN). Row 6545 was an operator flatten, filed under MIRROR-QTY-DIVERGE.
- **Trace (bybit_2 row 6692, SOL long):** package → trade → SL/TP ids → `sl` close → pnl (`cost_source=estimate`). Every hop held. The package says `close_reason=sl_cross`, the trade says `sl`.
- **TP doctrine:** compliant **0 of 54 routings** (real-money 0/8, prop 0/6, mirror 0/7, paper 0/33). Already owned by TP-DOCTRINE / TP-DECLARE-ALPACA-PB1D / TP-PREDICT-HEAD.
- **Live = mirror:** config tests 5/5 pass. Positive control: dropping one bybit_portfolio leg fails `test_bybit_portfolio_mirrors_bybit_2_exactly`. At trade level, 1 of 15 mirror trades (2026-10-07→21) had no bybit_2 twin: the 10-09 XRP order was sent at 0.5 qty and hit the 5 USDT minimum (MIRROR-QTY-DIVERGE).
- **Cost stack:** 3 leg evidence records changed since 10-12 (trend_donchian_eth_4h, ada_pullback_2h, trend_donchian_sol_prop). All 3 carry fees, slippage and funding; 0 are fee-only. `check_cost_model_single_owner`: clean.
- **Populations:** guard OK over the week's docs diff. Positive control: a planted bare "62%" line is flagged.
- **Overdue:** 253 due pipeline items (the same items read 63 due as of 10-14), 23 unrouted (alarm: oldest 24d). 72 of 188 `landed_unproven` rows are past `due_by`. I dispositioned **2 items + 7 rows** by hand; everything else is carried by F3/F4.
- **Spend:** last weekly reading 90.0% at 10-18 18:20Z (reset 10-21 18:00Z). Per-lane spend is recorded on 166 of 411 laned rows (F8).
- **Health #2:** trader active; heartbeat 70 s old; health snapshot 8/8 ok, with 6 accounts not checked (4 manual-bridge, 2 dry). No src/ or config/ change between the running SHA and main. Two surfaces disagree on the on-disk SHA (F9).
- **Research SLO:** red in every run for 6 of 6 days on grade latency, theme share and research-ops-not-run (n=72 runs). Gaps over 4 h on 3 days (F7). Self-test OK.

## 2. Findings

| id | axis | blast | tier | disposition | detector |
|---|---|---|---|---|---|
| F1 INV-EXIT-INTERVAL reads the `lines` shape of `/api/diag/log_file` as not-measured | C1 instrument | money-at-risk | 1 | **fixed in this PR** | self-test cases e3 (breach FAILS, within PASSES) |
| F2 prop accounts invisible to the invariants suite | C1 | money-at-risk | 1 | row AUD-20261019-PROP-INVARIANT-BLIND | the new invariant's self-test |
| F3 62 due items routed to done/dropped rows; same routing alarm back after ROUTING-ALARM-20261014 | C6/C9 | observability | 1 | row AUD-20261019-ROUTED-TO-CLOSED-ROW | `pipeline.py --check` target-closed rule |
| F4 72 overdue `landed_unproven` observations; nothing pulls them | C6 | observability | 1 | row AUD-20261019-LU-OBSERVATION-PULL | brief self-test, section 0 |
| F5 17 soak items teach a ≥10-fill exit; two soak graders disagree | C6/deep | docs/accounting | 1 | row AUD-20261019-SOAK-ITEMS-LONG-EXIT | soak-doctrine-guard extended to cover the pipeline |
| F6 6 rows stayed `in_flight` after their lanes were archived | C6 | observability | 1 | 6 corrected + row AUD-20261019-STALE-INFLIGHT | manager-loop step (no CI detector possible: runners cannot call get_session) |
| F7 research SLOs red all week with no same-day disposition | C8b | observability | 1 | row AUD-20261019-RESEARCH-SLO-RED | research-slo.yml (exists) |
| F8 per-lane spend not recorded; SOAK-REDEFINE spent $42.65 with no ceiling | C7 | observability | 1 | row AUD-20261019-SPEND-UNRECORDED | `checklist.py --check` warning |
| F9 status and health disagree on the on-disk git SHA | C8 | observability | 1 | PI-20261021-41BO5V65-0001 | rerun named on the item |
| F10 signal accounting cannot be measured from a session (no diag route) | C1 | money-at-risk | 1 | row AUD-20261019-SIGNAL-ACCOUNTING-READ | INV-SIGNAL-ACCOUNTING self-test |
| D1 work-system liveness is not joined (deep pass) | deep 3 | observability | 1 | row AUD-20261019-DESIGN-WORK-LIVENESS | throughput metric on that row |

## 3. Deep pass — DESIGN CRITICISM (follow-through system)

I chose the follow-through system (pipeline + checklist) because it had the most incidents this week. The question: is "is this still live?" answered by one mechanism?

**Answer: no.** Liveness is spread across three layers that are never joined: the item's state, the state of the row it is routed to, and the status of that row's lane session. Each layer goes on reporting `routed`, `in_flight` or `landed_unproven` after the thing it points at has ended.

- That is the parking lot CLAUDE.md warns about, rebuilt one level down. The due count went from 63 to 253 in a week over the same items.
- Soak verdicts have two graders, and they disagree.
- **What I would build today:** one derived due() used by `--check`, the brief and the Workflow page. Routed items would inherit their target's closure.
- **Not measured at all:** throughput (closed vs filed per week).
- **Delete:** the retired soak-state grader and the 17 legacy-contract soak items.

Full trade-off: row D1.

## 4. Closed since last audit (C9)

- 50 rows reached `done` between 10-14 and 10-21. 23 of them name no test, guard or alert; most are process lanes (RESEARCH-OPS-*, reviews, scans) that need none.
- **Recurrence:** ROUTING-ALARM-20261014 closed on "unrouted 0" without a root-cause detector, and the alarm is breached again → F3.
- ML-DATA-RUNNER-FETCH closed via a workaround route; the runner 404 itself is recorded as not fixed.

## 5. Coverage

- **Behavioural:** 9 invariants and 1 trace (real-money Bybit) were run on live data.
- **Signal-accounting** (signals → packages) was **not measured**. There is no diag route for `leg_flow_detector`, so only the "placed or refused" half ran. This gap is filed as row AUD-20261019-SIGNAL-ACCOUNTING-READ.
- **Read only:** cost records, SLO files, checklist and pipeline stores.
- **Not done by hand:** 251 due items and 8 `in_flight` rows. They are routed to F3, F4 and F6.

## 6. For the operator

- D1: should section 0 grow by derivation (about +130 items on day one, my recommendation), or should the sweeps run first? Row AUD-20261019-DESIGN-WORK-LIVENESS.

Fixed items are **merged ≠ deployed ≠ observed**: F1 is a repo-side instrument fix and needs no deploy. The 7 row corrections show on the Workflow page once this PR is merged.
