# Authoring-queue triage, 2026-11-17 (51 nodes)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-ITERATION-REFILL-20261117` (Manager Session 2026-11-15a order 3); measured 2026-11-17

**Gates this adds or changes: none.**

## What this covers

- **Source.** The 51 nodes come from `python3 scripts/research/queue_replenish.py --authoring-queue`, run on 2026-11-17 on the `#26634` branch tree (origin/main `dff81efc8` + this lane). Each node has a computed state of `ready`, a `needs_authoring` field and no materialised unit. Denominator: **51**.
- **Basis for each disposition:** the node's own text, the verdicts in its `after` list (computed by the tool), and, where it is named below, the result row I read.
- **Not edited here.** Every disposition is a **proposal** for `research/programmes/*.yaml`. Programme-tree edits HOLD for the manager's merge (programme-review skill § Scope), so this PR does not touch those files.
- **Slot mapping.** P1 / P3 / P4 / P5 / P7 / P8 are the TRADING track. Only P2 and the P5 ML gates map to ML slots, and **no node maps to D10.**

## Counts (denominator 51)

| disposition | n |
|---|---|
| authored as a unit (this lane) | **0** |
| already authored elsewhere: node closes or routes to its owner | 4 |
| blocked on a named row, unit result or data | 13 |
| killed: answered, superseded, or configuration closed FAIL | 20 |
| a Tier-3 / manager action, not a research unit | 8 |
| trading-track authoring left for a research-ops / programme-review lane | 6 |
| **total** | **51** |

**Why none was authored here.** Every node with a passing parent is either a Tier-3 declaration, or a trading-track follow-up that needs that lane's harness context. Every ML node is answered, blocked or superseded by units on `#26634`.

## Per node

| node | slot | disposition | basis |
|---|---|---|---|
| P2-MECE-D6-pointer-v0 | D6 | **kill**: answered | RQ-20261114-82fd-01 and RQ-20261115-a474-01, both FAIL; D6 next step is RQ-20261117-c21d-02 |
| P2-MECE-D5-aggregator-voi | D5 | **kill**: answered | RQ-20261114-82fd-02 census PASS, then RQ-20261115-a474-02 FAIL; rule-exhausted (PI-20261117-ZFRREVN5-0001) |
| P2-MECE-D2-regime-real-money | D2 | **kill**: answered | RQ-20261112-bcd2-01 consumer test on the TD family FAIL; the yz variant waits on c21d-03 |
| P2-desk-checkin-exit-head | D8 | **kill**: superseded | RQ-20261114-1ae8-01 (exit-now v0), then the tm-action-value line, now c21d-04 |
| P2-Q2-costnet-metalabel-regate | D4 | **blocked** on `ML-P1-COSTNET-REBUILD` | the node says BUILD-GATED |
| P2-R5-voltarget-sizing | constraint, not a slot | **blocked** on `IR-VOL-TARGET-SIZING-STAGE0` | per-trade sizing is the RiskManager's (MECE § 2.1) |
| P2-R3.c03-pass | D2 | **Tier-3 action** (`REGIME-PROGRAM`) | eth_pullback_2h regime gate confirmed on a disjoint window: write the packet |
| P2-R3.c04-pass | D2 | **Tier-3 action** (`REGIME-PROGRAM`) | trend_donchian_sol, same |
| P2-Q4-cross-asset-features | D2/D3 | **blocked** on `unit_result:RQ-20261117-c21d-01` | D2 cross-asset already tested (c4f1-01..06). For D3, a feature family on an entry model that loses its cost waits until the model is non-negative |
| P5-MLV-GATE-DYNSL | D3/D7 | **blocked** on a passing ML-ENTRY-DYNAMIC-SL arm | a standing node; c692-11..15 all FAIL, so nothing to gate |
| P5-MLV-GATE-NEXT | D3 | **blocked** on `unit_result:RQ-20261117-c21d-01` | a standing node; fires on an ENTRY variant PASS |
| P5-MLV-GATE-STRUCT | D3 | **blocked** on a passing structure-exit arm | a standing node |
| P5-MLPROP-ENTRY-ETHSOL | D3 | **already authored**: close node | RQ-20261105-d256-01; arm C = fd68-01 |
| P3-M18-same-symbol-read | D5 | **kill**: superseded | same-symbol allocation is the D5 question; answered by 82fd-02 / a474-02 |
| P7-Q2-frontier-pass | D9 | **kill**: configuration closed FAIL | f679-04 (perfect-fill maker upper bound) FAIL, decisive for maker entry; consistent with RQ-20261112-1c4e-01 FAIL. D9's next lever is the maker EXIT (`ML-D9-MAKER-EXIT-HARNESS`) |
| P3-Q1-live-bt-stage-b | D1 (book) | **trading authoring** | highest-money node (xrp/ada pullback BELOW_BACKTEST); not checked whether a later live-vs-backtest unit already answered it |
| P3-Q8-new-symbols | D1 (universe) | **trading authoring** | 7c2b-06 PASS, so Stage B |
| P8-Q7-rotation | D1 (new family) | **trading authoring** | new strategy family with no diagnosis behind it: needs the new-strategy lane |
| P7-Q5-confirm | D1 | **trading authoring** | f679-05 PASS, so a disjoint-symbol confirmation |
| P7-Q6-weekly-etf | D1 | **trading authoring** | ef5d-05 PASS, so an overlap read against the live alpaca_live legs and the paper 1d trend legs (the node's own next step) |
| P4-Q2-ppi-rty-econ | — (macro) | **trading authoring** | 7769-02 PASS, placebo clean: register the economic rung (macro-research skill) |
| P1-Q6-eth4h-measured-move-w05-declare | D7 (rule) | **Tier-3 action** | confirm PASS: doctrine read, then a declaration |
| P1-Q6-eth4h-stop-declare | D7 (rule) | **Tier-3 action** | RQ-20261016-005 confirmed; not checked whether it was already applied |
| P1-Q6-slv1d-declare | D7 (rule) | **Tier-3 action** | RQ-20261016-016 confirmed; not checked whether it was already applied |
| P3-M22-pairs-roster | D1 | **Tier-3 action** | 470a-12 FAIL, so the retire case goes per pair through the manager |
| P3-L-xrp4h-prewindow-underpowered | D1 | **Tier-3 action** (L-LADDER note) | c56e-13 INDETERMINATE, n-bound |
| P3-M27-htf-pass | D1 | **Tier-3 action** | HTF filter ON beats OFF, but stays net-negative on 5/6 legs: a roster decision |
| P1-Q6-xrp4h-declare | D7 (rule) | **kill**: corroboration FAIL | e5b1-15 FAIL and e5b1-16 FAIL (read here: incumbent exit stands) |
| P1-Q7-gtd-timeclose-prop | D8 (rule) | **kill**: configuration closed FAIL | 4ceb-01 FAIL and 4ceb-02 FAIL (read here) |
| P1-Q7-sol-tp3-prop | D6 (rule) | **kill**: configuration closed | d789-01 FAIL; the node names its own next test |
| P1-Q13-pathstate-prop | D8 | **kill** | b7e1-03 closed FAIL; the PASS branch was not taken |
| P1-Q13-pathstate-transfer | D8 | **kill** | b7e1-01 closed FAIL |
| P1-Q13-pathstate-w12 | D8 | **kill** | b7e1-02 closed FAIL |
| P1-ATM-pooled-tighten-gate-read | D7 | **kill** | d7e6-01 closed FAIL |
| P1-RG1025-giveback-trigger-variant | D7 | **kill** | d7e6-07 closed FAIL |
| P1-DESK-no-tighten-policy | D7 | **kill**: answered | d1f5-02 FAIL (981 of 1,155 non-hold actions were stop tightens, worth −0.097 R); the finding is recorded, and no unit adds to it |
| P1-Q15-c7-partial | D7 | **kill**: superseded | partial_close_50 is in the tm-action-value line (c21d-04); RQ-20261029-a7e1-01 ML-gated partial FAIL |
| P1-Q15-c8-full-close | D8 | **kill**: superseded | close is in c21d-04; 1ae8-01 INDET |
| P3-L-slv-trend-1h-outlier | D1 | **kill**: answered elsewhere | 78fc-18 confirmed (the node says so) |
| P3-VOLWIN-A2-longer-hold | — | **kill**: already authored and parent FAIL | a4e7-15 authored; 28bf-01 FAIL |
| P5-RG1025-fade-pullback-1h | — | **kill** | f679-01 FAIL closes the fade 4h range-gate configuration (not the family) |
| P1-Q15-c2-sl-widen | D7 | **already authored as a class**: route | a live-review class question with no diagnosis; belongs to the LTR orphans in research-ops (iteration_orphans `ltr_class`, 5 orphan) |
| P1-Q15-c3-sl-structure | D7 | **already authored as a class**: route | same; lever map `ltr-sl-to-structure.yaml` |
| P1-Q15-c5-tp-pullin | D7 | **already authored as a class**: route | same; tp_pull_in did not pass Stage A (3144-02) |
| P1-Q8-paths-rerun | D8 | **blocked** on `FIRST-PASSAGE-ON-PATHS` | the node says so |
| P1-ATM-sol4h-b-overlap | D1 | **blocked** on the manager's roster read | 1b57-08 PASS on basket B; next step is an overlap / roster decision |
| P3-RG1025-lever-pooled | — | **blocked** on a trading-lane harness read | pooled re-read of thin single-leg levers; needs the harness_stage0 owner |
| P5-RG1025-trend-pooled | — | **blocked** on a trading-lane harness read | pooled paired read over f679-02 / -03 / 4b82-05 |
| P5-Q2-SIZING-BRK-pass | constraint | **blocked** on a prop-sizing decision | 7c2b-12 INDETERMINATE; per the node, 0.35% is the default proposal |
| P8-Q9-options | — | **blocked** on a broker diag field | `/api/diag/broker_account_status` does not expose the options level (per the node; not re-checked) |
| P4-Q4-g2-rerun | — | **blocked** on `data_n` (PM collector paired n) | n-bound by its own text |

