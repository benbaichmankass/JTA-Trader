# Programme 05 — Prop: evaluations as an expected-value question

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · lane `P5-PROP-PROGRAMME` (manager dispatch, weekly planning 2026-10-14) · map: [`RESEARCH-MAP.md`](RESEARCH-MAP.md) · roadmap `L-PROP` · **Tier-1 document: it proposes tests; every roster, sizing or switch change it leads to is Tier-3 with an evidence record.**

## Programme review 2026-10-21 (lane RESEARCH-PROGRAMME-REVIEW-1021)

Population: units whose `grading.graded_at` is 2026-10-14..2026-10-21 and whose file names this programme (`programme:` or `programme_node.programme`), read from `research/queue/*.yaml` on main at 2026-10-21 ~18Z. Units with no programme field (486 of the 657 graded in the window) are counted in the research map, not here.

**Graded in the window: 10** — 2 pass, 8 fail.

**What was learned**
- The prop EV/survival gate PASSED on breakout_2 (RQ-20261016-026) and FAILED on tradeify_1 (-027) and velotrade_1 (-028).
- breakout_2 sizing (RQ-20261016-029 PASS, means over 5 seeds): configured 0.5% ev $85 / p_alive 0.008; **0.35% ev $111 /
  p_alive 0.147** (dominates); 0.25% $74 / 0.53; room sizing at 0.5% $67 / 0.96. **breakout_2 still trades 0.5%**
  (`config/accounts.yaml`, read 2026-10-21) — the rung-1 result has not been applied.
- Breadth and add-ons failed: ADA 1h on breakout_2 (-032), eth_4h alone on velotrade_1 (-024/-025), the 4h pair on breakout_2
  and tradeify_1 (e2db-05/-06), maker ict_scalp on the causal harness (1fa6-07). velotrade_1 rung-2 sizing (-030) and
  tradeify_1 per-leg $ risk (-031) FAILED: their configured sizing stands.

**Answered / unlocked / retired**
- Closed: Q5's 4h line on breakout_2 and tradeify_1 (nodes P5-Q5-4H-BRK-fail / -TRAD-fail removed: the matched-risk head-to-head
  failed at 0.005, and a lower-level control is not justified when the 1h book itself fails the gate on tradeify_1).
  Q1 and Q4 recorded closed in the tree's `questions:` map.
- Unlocked: P5-Q2 rung 2 on breakout_2 -> RQ-20261021-7c2b-12.

**Next 3–4 weeks (pre-registered this review)**
- RQ-20261021-7c2b-12: rung 2 around 0.35% (0.30 / 0.40 / room at 0.35) on the same ledgers.
- RQ-20261021-7c2b-11: squeeze time stop 6/12/24 vs 48 bars on DOGE/ADA/LINK 1h (pace), superseding blocked RQ-20261007-241
  now that `harness_stage0.py` can pass `timeout_bars` and write a verdict.
- P5-GATE-BRK-read (write `comms/prop_survival/` records for breakout_2's passing legs) is a session task for the manager.

**Cross-programme feeds**
- ← P3: 7c2b-10 (eth_prop config on six new perps) supplies candidate symbols for P5-Q6.
- ← P1: trail 4.5 on eth_prop is priced on all three books.

## 1. End goal and measure

**Goal.** The prop accounts execute, protect themselves and clear evaluations, and every decision about them — which legs, what size, what buffer, keep or buy fresh — is read off **the expected dollars banked before the account dies**, not off how far it is from a drawdown line. B6's finding is the frame: *the prop bar is an expected-value question, not a drawdown-avoidance one*, and the decision that moves money is the **sizing rule and the book**, not whether to keep a given account (B6, MEASURED 2026-09-27: continuing a damaged account was worth +$3..+$6; a fresh account at cushion-fit sizing +$112/life vs −$12 at flat 1.5%).

**Measure (headline).** **E[net $ banked per account life]** (`ev_net_usd_per_life`, path mode), per live prop account, as configured, with P(net > 0), P(pass by 30/90/180 d) and P(breach daily / static) beside it. Every number is a backtest re-priced under the firm's own rules by `scripts/research/prop_ev_sim.py`, net of the full cost stack: the committed trade rows carry the harness's fee + slippage + funding (`execution_costs.resolve_cost_policy()`, D1-cleared trend harness), and the sim charges the venue's commission, slippage, swap and the account fee on top. **A live prop book never establishes edge** — the live measure is mechanics and realised cost (Q6).

| measure | population | instrument | baseline |
|---|---|---|---|
| E[profit per life] per account, as configured | the account's roster legs' committed 730 d trades, 5 seeds × 4,000 lives, the account's `backtest_ruleset`, its configured sizing, daily-DD switch armed at 0.8 | `prop_ev_grid.py` units `RQ-20261014-f516-01/02/03` | landed 2026-10-15 (f516-01..03, all `indeterminate`); seed-EV ranges and the velotrade_1 re-size are in § 7 |
| gradable prop closes | automated closes on velotrade_1 / tradeify_1 / breakout_2 with exit price, P&L and a TP/SL reason | `prop_fills` via the diag relay | **0** gradable: the REST reconcile still writes `closed_on_terminal` with null exit price/P&L (PROP-EXIT-READ re-scoped to queued 2026-10-11); breakout_2 has no observed close |
| TP-doctrine compliance on prop routings | the 6 prop (account, leg) routings | `python3 scripts/ci/check_tp_doctrine.py --json` | all 6 `declared` / `rule_undeclared` (RESEARCH-MAP, 07:28Z 2026-10-14; re-run, do not quote) |

**What is live today** (MEASURED from `config/accounts.yaml` on `main`, re-read 2026-10-16): three live evaluation accounts, each trading `trend_donchian_eth_prop` + `trend_donchian_sol_prop` (1h): **velotrade_1** ($5k, Velotrade Classic 1-Step, `risk_pct` 0.005 since VELOTRADE-RISK-050 / #18157, 2026-10-15; 0.01 when this plan was written), **tradeify_1** ($10k, Tradeify 24/7 1-Step, 0.005), **breakout_2** ($5k, Breakout 1-Step Turbo, 0.005, phone executor — stays open indefinitely, standing). `breakout_1` is retired (`dry_run`, empty roster). The daily-DD switch is `armed: true` on all three (row DAILY-DD-SWITCH; prop limit = 0.8 × the firm's daily limit, keep open / block new).

## 2. What is already known (do not re-run)

| finding | record |
|---|---|
| No single crypto leg clears the Tradeify bar (P(net>0) ≥ 0.70) | RQ-20261005-801..810; `trend_donchian_sol_prop` 0.5 % EV −$72..−$75/life (807). SOL was later re-added to tradeify_1 on a book-level result (#16647) |
| ETH+SOL at 0.5 % beats ETH alone on Tradeify (P 0.372 vs 0.284, EV +$179 vs +$58); a negative-edge leg LOWERS EV, so the gain is not generic | PROP-ROSTER-EXPAND, #16624 |
| SOL's single-leg Breakout Turbo fit: NULL at both flat arms; $50 beats $25 on EV | RQ-20261005-853/854 (single-leg, indeterminate — the reason PROP-PER-LEG-EV-GRID exists) |
| The SOL bracket change (tp_r 2.0 / atr_stop 3.5) is a selection-window artifact | RQ-20261004-652, FAIL 4 of 5 clauses; proposal closed |
| Breadth books (batch 2): `trend6` PASS under Velotrade at 0.5 % (seed EV $366–380/life, P(pass by 90 d) 0.56–0.59), FAIL Tradeify, FAIL Turbo; `mixed6` PASS Velotrade/Turbo (Turbo EV ~$17–23, negligible); `fast6` FAIL everywhere; every ict_scalp 15m pace fit FAIL | RQ-20261007-201..223 (MEASURED from `research/results/RQ-20261007-215/37940126955.jsonl` and siblings). **Never priced against the incumbent on the same seeds; no roster change followed** |
| 5m/15m legs die on the cost stack with these harnesses; pace has to come from breadth at 1h–4h | PROP-STRATEGY-SEARCH batch 1 (RQ-20261006-005..031) |
| The policy model's label is degenerate (0 of 267 missions taken) | PROP-MISSION-MODEL (queued, not this programme's research until the label is defined) |

## 3. Questions, in dependency order

```
Q1 baseline per account (as configured) ──┬──▶ Q2 sizing challengers ──┐
                                            ├──▶ Q3 per-leg $ risk ──────┤──▶ Tier-3 data-backed sizing/roster change
                                            ├──▶ Q4 daily-DD switch cost ┤    (manager, standing authorization; the
                                            └──▶ Q5 breadth: pool → head-to-head ┘ switch buffer goes to the operator)
Q6 live-vs-sim fidelity ◀── PROP-EXIT-READ (gradable closes)  ── gates acting on Q1..Q5 if the venue stack is off
Q7 = P1-Q7 TP amend on dxtrade / phone ◀── Q6 + Programme 01 Q6 (a confirmed revision rule)
```

| Q | question | why now | units |
|---|---|---|---|
| **Q1** | What is E[profit per life] of each live account **as configured today** (roster, sizing, switch armed)? | No record prices any live account as it trades now; every later rung needs a dated number to beat | `f516-01` velotrade_1, `f516-02` tradeify_1, `f516-03` breakout_2 |
| **Q2** | Does a challenger sizing (smaller/larger flat %, cushion-fit room) beat the configured one on EV with no worse survival? | B6: sizing is the lever that moves money; never run on these books | `f516-05` velotrade_1, `f516-06` tradeify_1 |
| **Q3** | Does per-leg $ risk (breakout_2: ETH $25 / SOL $50) clear the bar when priced as a book? | PROP-PER-LEG-EV-GRID: mechanism merged (#16958), config held on single-leg indeterminate records | `f516-04` (needs `prop_ev_sim.py --leg-risk-usd`, added in this PR) |
| **Q4** | What does the armed switch (0.8 × firm limit) cost or buy in EV and P(breach)? | The one sanctioned auto-off is armed everywhere and unpriced; velotrade_1 (1 % risk vs a 3.2 % trip) is where it binds most | `f516-07` (needs `--dd-switch-frac`, added in this PR) |
| **Q5** | Which breadth books beat the incumbent, and which admitted legs enter the candidate pool? | `trend6` passed Velotrade at ~2× the incumbent's EV in separate runs but was never head-to-head; the 1095 d 4h admissions (PROP-BOOK-SEARCH-1095D) had no dispatchable unit | `f516-08` head-to-head (velotrade_1), `f516-09` / `f516-10` pool admission (tradeify / velotrade) |
| **Q6** | Does realised prop cost and R match what the sim charges? | Stage 1's question for the prop books; every Q1..Q5 number assumes the venue stack | `blocked/f516-11` (blocked on PROP-EXIT-READ) |
| **Q7** | Can the prop paths carry a revised TP (dxtrade REST amend plumbed; phone via server-computed amend ticket)? | TP doctrine applies to prop; RQ-20261007-002 found 0/24 extension cells on the 6R near-sentinel | Programme 01 Q7; re-run `RQ-20261007-002` only after Q6 has gradable closes (not duplicated here) |

## 4. Test ladders

Each unit's `decision_rule` is registered in the unit before the run; the grids grade mechanically (`prop_ev_grid.py` writes `verdict.json`). "Data-backed" below means the 2026-09-27 standing authorization: the manager decides on the committed record, ships, verifies and notifies the operator with the revert.

### Q1 — baseline per account (`f516-01/02/03`, W1)
1. **As configured, one arm, 5 seeds.** Rule: PASS = EV > 0 and P(net>0) ≥ 0.70 on all seeds (B6 V2); FAIL = EV ≤ 0 on any seed → that account's Q2 and Q5 units go to priority 1 and the manager is told the same day (a data task; never a popup, never a retire on this alone); NULL/PASS → configured book stands and is the number Q2..Q5 must beat. The record's seed-median EV goes into § 1's table.
2. **Re-run on any roster, sizing or ruleset change** (same unit shape, new id). The baseline is dated, not permanent.

### Q2 — sizing (`f516-05/06`, W1)
1. **Challengers vs configured**, `--grade cushion_vs_flat`: PASS when the best challenger beats the configured arm on EV with ≥ survival on every seed → data-backed sizing change **only if** its P(breach_max_dd) is also ≤ the configured arm's on every seed; otherwise the operator decides with the record. FAIL → configured sizing stands for this book.
2. **Expensive rung:** a continuous risk grid or a balance-conditioned rule (cushion-fit at evaluation, flat when funded) — only if rung 1 passes on one account, so the grid is refining a real effect.

### Q3 — per-leg $ risk (`f516-04`, W1)
1. **The row's own rule**: the mixed arm clears the B6 V2 bar → data-backed apply of `per_leg_risk_usd {trend_donchian_sol_prop: 50}` on breakout_2; anything else kills the held proposal with this record as the terminal reason (its EV beside `f516-03` still feeds Q2's ranking).

### Q4 — daily-DD switch (`f516-07`, W1–W2)
1. **velotrade_1: armed 0.8 vs disarmed vs 0.9.** PASS (a looser/disarmed arm dominates) → an operator **decision** with the record (the setting is the operator's directive — never changed under the standing authorization). FAIL → the setting is confirmed; the other two accounts close Q4 unless their Q1 sims show `dd_switch_blocked` > 0.5 per life.

### Q5 — breadth (`f516-08/09/10`, W1–W2)
1. **Pool admission** (`f516-09/10`): the 1095 d 4h ETH+SOL pair under Tradeify and Velotrade, `p_floor 0.0` (clause R of the 2026-10-06 go-live gate). PASS = admitted to that account's pool, nothing more. `trend_donchian_xrp_4h` (1460 d, n=46 < 88, different window) is **not** pooled; it waits for accrual.
2. **Head-to-head on the same seeds** (`f516-08`): incumbent vs incumbent + `p2_trend_xrpusdt` (the only trend6 leg with measured lots) vs trend6. PASS on an XRP arm → Tier-3 roster+sizing proposal, after that leg passes its own Stage-0 record at configured params; PASS only on trend6 → no roster change, a build row to measure LINK/ZEC/UNI lots on Velotrade.
3. **Every admitted pool book gets rung 2** against its account's Q1 baseline (W2+: the 4h pair, if admitted).

### Q6 — live vs sim (`blocked/f516-11`)
1. **Blocked on PROP-EXIT-READ.** When closes are gradable: per-close delta R (live − harness for the same signal), n ≥ 30. PASS = CI within ±0.10 R of 0 on every account with n ≥ 10; FAIL = recalibrate that firm's stack in the sim and re-run its Q1 before acting on any Q2..Q5 proposal. Any close whose reason is not TP / SL / strategy is a bug filed the same day.

## 5. Backlog — the next 3–4 weeks

| week | research (units) | builds (rows) | decision points |
|---|---|---|---|
| **W1** (to 2026-10-21) | `f516-01..08` dispatch (runnable now, `research-script-run.yml`); read RQ-20261014-002..005 as they land (see § 6) | PROP-EXIT-READ (REST path; the one build that unblocks Q6/Q7); this PR's two sim flags | per-account baselines land; Q3 closes PROP-PER-LEG-EV-GRID either way |
| **W2** (to 10-28) | `f516-09/10` pool admission; Q2/Q4 read-outs; head-to-head for any admitted pool book vs its Q1 baseline | lot measurement on Velotrade for LINK/ZEC/UNI if `f516-08` points there | first data-backed sizing or roster change, or an honest "the configured book stands" per account |
| **W3** (to 11-04) | Q2 rung 2 on the account where rung 1 passed; Q1 re-run on any changed account | PROP-MISSION-MODEL label definition (engineering, not research) | switch buffer decision to the operator if `f516-07` passed |
| **W4** (to 11-11) | Q6 if PROP-EXIT-READ is observed; RQ-20261007-002 re-run (P1-Q7) after Q6 | P1-Q7 dxtrade TP amend soak (Programme 01) | re-cut W5+ from the measured state |

## 6. Findings raised while writing this plan

- **The generated Breakout prop-fit template targets a retired account.** `research/templates/prop-fit-breakout.yaml` generated RQ-20261014-002..005 today, each saying "a PASS is a Tier-3 roster proposal for **breakout_1**" — but `breakout_1` is retired (`dry_run`, empty roster) and the live Breakout account is `breakout_2` on the **Turbo** ruleset, while the template prices `config/prop_rulesets/breakout.yaml` (Classic). A PASS from those units cannot be acted on as written. Filed to the pipeline (see the PR); the units themselves still produce valid Classic-ruleset numbers. **Fixed 2026-10-16** (lane P5-PROP-BACKLOG-1016): the template now prices `breakout_turbo_1step.yaml` for breakout_2; RQ-20261016-002/003 (generated the same morning) had already run, so they are graded as Classic prices, not retired.

**What this plan does not do.** It changes no config, roster, sizing or switch setting (all such moves are Tier-3 proposals with records). It does not re-open single-leg Tradeify fits (801..810), the SOL bracket (652), or 5m/15m pace legs (batch 1). It does not treat a live prop P&L as edge. Figures marked MEASURED were read this session from the files named; the per-account baselines are deliberately not quoted until `f516-01..03` land.

## 7. The machine tree and the state on 2026-10-16 (lane P5-PROP-BACKLOG-1016)

**This plan's questions now live in [`research/programmes/05-prop.yaml`](../../../research/programmes/05-prop.yaml)** — the
programme source `scripts/research/queue_replenish.py` reads (`--programme-state`, `--authoring-queue`). Until this
date 05 had no tree, so none of its open questions reached the authoring queue. A `unit:` node is a fully
pre-registered unit (the ready ones are materialised in the same PR, ids minted at merge time by the replenisher's band); a `needs_authoring:` node is a branch
registered before its prerequisite's verdict exists. **Edit the tree, not this table, when the plan learns.**

| Q | state (MEASURED from `research/queue` grading + `research/results`, 2026-10-16) | tree nodes |
|---|---|---|
| Q1 | f516-01/02/03 closed `indeterminate` (EV > 0 every seed, P(net>0) < 0.70). Seed EV: velotrade_1 $116–140 at 0.01 (then re-sized to 0.005 by VELOTRADE-RISK-050; f516-05 arm C050 $159–175), tradeify_1 $174–198, breakout_2 $32–36 (survival 0.003). Every node below re-measures its account's A arm on the window-matched ledgers. | — (answered) |
| Q2 | velotrade_1 PASS (f516-05) → rung 2; tradeify_1 FAIL (closed); **breakout_2 never run** | `P5-Q2-SIZING-BRK` (+ pass branch), `P5-Q2R2-SIZING-VELO` |
| Q3 | f516-04 NULL → the breakout_2 $25/$50 proposal is killed by its own rule; the SOL-down direction on tradeify_1 never priced | `P5-Q3-PERLEG-TRAD` |
| Q4 | **closed.** velotrade_1 FAIL (f516-07, 0.8 confirmed). ⚠️ The 2026-10-15 note closed tradeify_1 / breakout_2 using **velotrade_1's** blocked count; their own Q1 sims record `dd_switch_trips` = `dd_switch_blocked` = 0 (counter absent = never incremented, `prop_ev_sim.py:837/:877`), so the "< 0.5 blocked per life" exit holds **on their own numbers** — same disposition, now verified. | — |
| Q5 | pool admission PASS (f516-09/-10); every head-to-head so far priced 730 d incumbents against 1095 d 4h rows. The window-matched matched-risk head-to-heads at 0.005 for all three accounts are lane RESEARCH-FOLLOWUP-1016's RQ-20261016-e2db-05/-06/-07 (not duplicated); breakout_2 has no breadth test beyond the 4h pair | branches on e2db-05..07: `P5-Q5-4H-*-pass/-fail`; **eth_4h alone** on velotrade_1 at matched 0.005 / 0.0035 (`P5-Q5-E4H-VELO-005/-0035`: `sol_4h` is `execution` = shadow and on no roster, so eth_4h is the only gate-eligible 4h leg, manager audit 2026-10-16 § 4.2); `P5-Q5-ADA-BRK`; `P5-Q5-BRK-product` |
| Gate | `comms/prop_survival/` is empty; no unit produced a per-leg record; the incumbents' exemptions lapse 2026-11-07 / 2026-12-11 | `P5-GATE-VELO/TRAD/BRK` (+ `-read` branches) |
| Exits | **owned by Programme 01** (`research/programmes/01-active-trade-management.yaml`), not duplicated here: `P1-Q2-ethprop-derive` / `-solprop-derive` (predictive TP), `P1-Q4-ethprop-exit-confirm`, `P1-Q4-ethprop-ev`, `P1-Q4-solprop-propcost`, `P1-Q7-sol-tp3-prop`. eth_4h's fixed predictive TP already FAILED (RQ-20261015-cab7-04), so its TP-doctrine route is the stop (`P1-Q6-eth4h-stop-declare`) | — |
| Q6/Q7 | blocked/f516-11 on PROP-EXIT-READ | `P5-Q6-fail`, `P5-Q7-tp-amend` (branches on f516-11) |

**Noise.** `prop_ev_grid` compares `p_alive` per seed with a strict ≥ (no MC-SE tolerance; audit § 4.1). Every dominance rule in the tree carries a registered STRICT-SEED CAVEAT (a within-noise survival FAIL is reported as such, never re-graded post hoc); the tolerance fix is build row PROP-GRID-SURVIVAL-TOL.

**Window-matched ledgers.** Every new prop_ev_grid unit prices the 1095 d prop-venue-stack Stage-0 arms of
RQ-20261015-1bf3-03..06 (eth_prop 517, sol_prop 203, eth_4h 116, sol_4h 116 trades, 2023-10-13..2026-10-11).
The sim re-prices `gross_r` under `--costs breakout`, so the harness stack is not charged twice.

**Not encoded here, on purpose:** Tradeify non-crypto search (e2db-01..04) and the per-account matched-risk
head-to-heads (e2db-05..07), lane RESEARCH-FOLLOWUP-1016; RQ-20261015-24ca-05 / ca42-01 (Tradeify non-crypto, queued); `trend_donchian_xrp_4h`
(n 46 < 88 at 1460 d — nothing can answer it until it accrues); PROP-MISSION-MODEL (a build).
