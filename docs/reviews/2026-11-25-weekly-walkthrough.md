# Weekly walkthrough 2026-11-25

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH**. A section another lane has not landed yet is simply absent. On a collision, the later lane merges `main` first.

<!-- PRACTICE-REFRESH:START -->
# PRACTICE REFRESH: the system learns regime but not trades, a cost gap is now measured, and two MGC legs on IB paper are rejected by the venue today

> Lane `PRACTICE-REFRESH-20261125` (Tier 1, read-only). Full record: [`docs/research/practice-review-2026-11-25.md`](../research/practice-review-2026-11-25.md).
> Canonical list revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
> Live reads 2026-11-25 ~18:20–18:30Z, direct HTTPS to the read-only API. **Nothing was queued or changed; every gap is a proposal.**

**TRADING:** 5 sources read (abstract or summary level), plus our own 3 graded units.
- **T3** is strengthened by our own measurement: the recorded cost understates the +1 h markout cost by **+3.78 bps/fill**, CI [+0.36, +7.34],
  n = 2,375 fills (paper and real money pooled; the real-money slice alone is indeterminate).
- **T15** is qualified by our own registered results: a pre-release book flatten **FAILED** (0/6 folds, 0/200 random controls), and decision > minutes
  on 5/5 symbols.
- **T2/T9** noted: practice picks the exit family by holding period.

**MODEL:** 4 new sources (abstract level).
- **M3** strengthened: leakage is a degree measured one switch at a time. Centered features and same-bar-open execution are the big
  inflators, and LLMs carry parametric look-ahead.
- **M5** strengthened: run the whole workflow on a synthetic null first.
- **M14** noted: one more self-reported LLM-trading gain.

**(a) Demo-floor data generation.**
- Population: 58 rostered leg × floor-account cells, journal fills 11-18T18:26Z → 11-25T18:26Z.
- **29/58 cells filled, 97 fills in all**: `bybit_1` 25/29 cells, `alpaca_paper` 3/18, `ib_paper` 1/11.
- The 29 quiet cells:
  - **4 blocked**: `ib_paper` MGC rejected by IBKR (`status=Inactive`, 73 today); `ml_entry_eq` sizing; the desk not trading either paper venue.
  - **3 quiet by design**: holding a position.
  - **22 cannot tell**: no eval line.
- 491 refusals, of which 347 are `bybit_1` slice-budget policy holds.

**(b) Is it learning?**
- Population: 100 trainer-registry rows (mirror 32 s old), the 11-25 build cycle, and the 7-day learning ledger.
- **24/100 models trained and scored, all of them regime or setup heads; 0 trade-decision models.**
- Teacher data: desk and live-review rows are produced and labelled, and the 1,511-row `claude_judgments` set is built daily. **Consumed: 0 all-time.**
- `review_journal`, `cross_asset`, `forecasts` and `macro` build 0 rows. `exit-policy-v1` has been untrained for 121 days.

## Gaps for Thursday

| # | Track | Gap | Proposal | due_by / decision |
|---|---|---|---|---|
| TG1 | TRADING | Harness cost stacks omit the measured markout term (T3) | Row `COST-STACK-MARKOUT-TERM`, report-only beside the current net. Close `MARKOUT-HARNESS` and `EVENT-SPAN-HISTORY` | 12-02; **operator** on making it the grading basis |
| TG2 | TRADING | The calendar weights FOMC minutes like a decision, and the 12-09 decision is timed 30 min late (T15; evidence now in) | `CALENDAR-FOMC-RELEASE-SPLIT` (Tier 2) | **operator OK before 12-08** |
| TG3 | TRADING | `ib_paper` MGC: 73 IBKR `status=Inactive` rejects today; 2 legs make no floor data | Owned by row `IB-MGC-INACTIVE-1125` (lane dispatched 18:35Z); evidence: 73 rejects | in flight |
| TG4 | TRADING | 22/58 floor cells cannot be classified | Raise `FLOOR-LIVENESS-CHECK` + `AUD-20261028-DEMO-FLOOR-NO-EVAL` | manager |
| TG5 | TRADING | 286 slice-budget re-emissions for 79 `bybit_1` fills | Note on `NETTED-SLICES`: log once per held slice per bar | 12-02 |
| TG6 | TRADING | `DESK-PAPER-ACCOUNTS` unproven for five refreshes; `VERDICT-LEFT-TAIL`, `DESK-REPEATABILITY` idle | Raise | manager |
| MG1 | MODEL | No one-switch execution-convention audit (t+1 open vs current) on the daily harnesses (M3) | Unit, rule registered first | 12-02 |
| MG2 | MODEL | `ml_bakeoff` never runs on a null (M5) | Row `ML-BAKEOFF-NULL-ARM` | 12-09 |
| MG3 | MODEL | Pre-cutoff teacher labels may train a student on memorized outcomes (M3, S91) | Note on `CJ-7-BACKFILL-SCOPE` + a pre/post-cutoff teacher-skill unit | 12-09 |
| MG4 | MODEL | Learning chain broken at H3/H4 for every trade-decision source, unchanged since 11-13; 4 zero-row families; `exit-policy-v1` | Raise `DESK-LABEL-JOIN`, `ML-LEDGER-COULD-NOT-LOOK`; row `ML-ZERO-ROW-FAMILIES` | 12-02 |
| MG5 | MODEL | `RESEARCH-TRIAL-CENSUS`, `PERF-FOLLOWUP-DEFLATION` idle since filing | Raise | manager |
<!-- PRACTICE-REFRESH:END -->

<!-- ML-FRONTIER-PREP:START -->
# MODEL track — /ml-review 2026-11-25: the real-money ML entry model `ml_entry` lost 9.8 R over its first 59 live trades, and the only number that put it on real money was measured on the same window that graded it

Lane `ML-FRONTIER-PREP-20261125` (dispatched by Manager Session 2026-11-25a). It runs `/ml-review` and `/frontier-research`.
It queues no new units: every proposal below is labelled **MODEL** or **TRADING** and mapped to a row, a unit or a named decision
(§ 3). The practice refresh is the sibling lane's job and is not repeated here.
Records: `comms/reviews/ml-review-20261125-200000.json` · `comms/ml-plan/20261125T2000Z-ML-FRONTIER-PREP.json` ·
[`docs/research/frontier-scan-2026-11-25.md`](../research/frontier-scan-2026-11-25.md).
Gates this adds or changes: none.

**Assessment: `investigate`.** The trainer cannot gate-check any of the 8 models that change orders, because none of them has a
trainer registry entry (C1). Serve parity for the real-money ML legs could not be read (C5).

## S. Scoreboard

Source: `GET /api/bot/performance?window=7d|30d|all`, read about 18:40Z. R is on the declared signal-time risk (`rCoverage` 1.0 on
every block below). $ figures are left to the PERFORMANCE section, which owns the book scoreboard.

| book | 7d trades · ΣR | 30d trades · ΣR | lifetime trades · ΣR |
|---|---|---|---|
| real money | 26 · **−7.68** | 77 · −11.11 | 542 · −166.38 |
| mirror (`paperPortfolio`) | 35 · +33.09 | 90 · +33.45 | 237 · −3.19 |
| paper (all) | 144 · +31.89 | 418 · +54.02 | 2,054 · −78.05 |

**The ML legs inside those books** (same source):

| leg | book | trades · ΣR · R/trade | would a sceptical quant believe this leg has edge? |
|---|---|---|---|
| `ml_entry` (Foxhound-1, D3 + Labrador-1b TP revision, D7) | real money (`bybit_2`) | 7d **23 · −8.21** · −0.357; lifetime 59 · **−9.84** · −0.167 | **No.** Stage-0 is +0.0371 R/trade over n=907 (iid t ≈ 1.03; no clustered se; DSR cannot be computed because no per-trade series is readable). It was measured on the held-out window that also graded it. See § 2 Q1. |
| `ml_entry` | mirror | 59 · −9.33 | same model as above |
| `ml_entry_eq_struct` (Foxhound-4, D3) | real money (`alpaca_live`) | 1 · −0.11 | **Marginal.** Stage-0 is +0.492 R/trade over n=207 with day-clustered t 2.06. The trial ledger has `param_selection_provenance: null`, so the same window question applies. |
| `ml_entry_v2` (Foxhound-2) | paper (`bybit_1`) | 30d 24 · −8.59 | No. It already failed W1 (−0.116 vs −0.041). |
| `ml_entry_eq` (Foxhound-3) | paper (`alpaca_paper`) | 30d 6 · −4.77 | No (the struct model beat it). |
| `trend_donchian_xrp_4h` under Beagle-1 reduce (D4) | real money | overlay resized 1 trade in the joined window | Yes on its record (V2 rule; blind holdout n 105, dR +0.033 per `config/overlay_policy.yaml`). The live read is n=1, which is mechanics only. |

This week `ml_entry` lost **8.21 R, more than the whole real-money book's 7.68 R**: the other real-money legs netted +0.53 R.

## 0. Prior calls (Layer 0)

Follow-through (`review_followthrough.py`, 3,059 pipeline items + 2,079 checklist rows): **ml-review**: 2 filed in the 7d cohort, 0
closed; backlog 14 open, 86% due, median age 36 d, 0 with no owner. **frontier**: 9 filed, 1 done; backlog 42 open, 93% due,
median 13 d, **6 with no owner**.

| call (2026-11-18) | p | check, re-run as written | grade | did the action happen |
|---|---|---|---|---|
| 1. RQ-20261118-dbf8-01 (CatBoost vs LightGBM on D3) PASSES | 0.30 | `research/results/RQ-20261118-dbf8-01/44382439615.jsonl`: **fail**. CatBoost paired vs raw −0.032 R, CI [−0.099, +0.035], k=13 folds; ens3 −0.0008. | **miss** | yes (unit ran) |
| 2. FRONTIER-LEVER-TABULAR is still `queued` | 0.55 | checklist row state = **`dropped`** (since 2026-10-23) | **void**: last week's call misread the row state | — |
| 3. ≥ 70% of ml_bakeoff results in the window target regime/direction labels | 0.65 | 3 of 3 results whose unit has an `ml_bakeoff` block (2a2e-11, b3c9-19, a10d-05) | **hit** (n=3, a thin denominator) | no capacity was re-pointed |
| 4. BTC fc-pcv-v2 still drifts (KS ≥ 0.20) | 0.65 | `/shadow/drift`: **KS 0.504, PSI 0.528**, ref n 3,336 / cur n 696 | **hit** | DRIFT-REMEDIATE row still `queued`, due today |
| 5. Serve-path diff names `fc_*` first | 0.50 | PI-20261118-ZZUFKM1F-0001 still `queued`, no diff landed | unresolved (void if none by 12-02) | no |
| 6. A D8 aadc-12 downstream read by 12-02 | 0.35 | none yet | unresolved | — |
| 7 (carried from 11-04). `ml_entry` bybit_2 mean realised pnl% ≤ 0 at n ≥ 30 | 0.55 | `/trades/closed?account_id=bybit_2&since=2026-11-01` (2 pages): **59 ml_entry closes, mean −0.488%/trade**; every row `measured`, and the account is `journalTrust: known_divergent` | **hit** | — |

Footer: 3 hit · 1 miss · 1 void · 2 unresolved. Brier over the 4 resolved calls is 0.134, which is `INDETERMINATE` below 10 resolved calls.

**Frontier calls (2026-11-18 scan):**
- **CatBoost** (kept): **hit**. It ran and gave an informative FAIL at a powered design.
- **TabICL** (kept): **miss**. dbf8-02 is still blocked, and its lever row is `dropped`, not queued.
- **Dropped heterogeneous stack**: hit. The ens3 arm landed −0.0008, CI spans 0.
- **Dropped TSFM-for-D2**: hit. The gate still holds, because the D2 parity PI is still open.
- **Dropped offline RL for exits**: hit. 4 more action-value FAILs this week (c7e3-01..04).
- **Moirai, licence-dropped**: hit.
- Mitra, distributional head, Kronos and TabPFN serving: unresolved.

## 1. CHECKS (numbers only)

**Headline numbers:** ML changes **12 of 85** rostered account-legs and **3 of 9** real-money legs (`ml_entry`, `ml_entry_eq_struct`,
`trend_donchian_xrp_4h` under D4 reduce; source: `config/accounts.yaml` × feed consumers × `config/overlay_policy.yaml`). **First broken C4
hop:** desk decisions **H2→H3**. 5 were labelled and 0 entered a dataset; for `live_review`, H3 is `could_not_look` (no consumed-ids ledger).

| # | state | numbers (population) |
|---|---|---|
| C1 trainer + registry | **finding** | trainer-vm-diag [#28843](https://github.com/benbaichmankass/JTA-Trader/issues/28843): timer active; last `cycle_end` 2026-11-25T08:08Z, rc 0; the 01:24Z cycle trained 2 models (conviction-meta-v1, setup-candidates-metalabel-p2pool-v2); 0 `manifest_oom_red_flag`; build rc 0. Stages advisory 3 / shadow 16 / candidate 80 / research_only 1, against a plan of 3 / 21 / 72 / 1 (unchanged for 3 weeks). Stage-guard: demote `btc-regime-15m-lgbm-fc-pcv-v2`, hold 99 of 100. **`gate-check` returns "no registry entry" for all 8 served models with a consumer**, so no gate packet or cost-gate exists for any order-changing model. Trainer disk 86% (83 of 97 G). |
| C2 freshness | finding | `ml_plan_status.py --plumbing` rc 1: 115 flags of 85 plan items, most of them `UNPLANNED` rows. TRAINING-STALENESS: 2 stale and 2 never-trained of 5 scanned (exit-policy-v1 121.9 d, setup-candidates-metalabel-paper-v1 121 d, both `dataset_absent`; mes-execution-quality waits for a source by design). |
| C3 business use | ok (lines below) | `ml_order_changers.py`: 8 models with a consumer, 7 with `order_effect=yes`. Foxhound-1 mean_net_r 0.0371, n 907, t 1.03, 3,453 trades to confirm. **Foxhound-1 refit v1r20261122 has NO POWER RECORD**, yet it is the served pointer. Foxhound-4 0.492, n 207, clustered se 0.239. Labrador-1b 0.0081, n 868, se —. Beagle-1 n 1,830, mean —. Labrador-2 (exit head) changes no order. Foxhound-2 −0.116. Foxhound-3 0.039. The D2 router heads are missing from the consumer feed (PI-20261118-EUWZZMDP-0002, still open). |
| C4 learning chain | finding | `ml_learning_ledger.py` (7 d): H1 desk 9 / live-review 45 · H2 5 / 83 · H3 **0** / — · H5 scored 163 · H6 promoted 0 · H7 order-changing legs 6 (3 real-money/prop; ESTIMATED). |
| C5 serve parity | **could-not-look** | gate-check `live_parity` can't run with no registry entries. The live-vs-replay parity job reported `could_not_check` for `ml_entry_eq_struct` in 6 daily LRP pipeline rows dated 11-09..11-15. The owner row ML-LIVE-PARITY-ML-LEGS is `in_flight`, due 11-14 (overdue). |
| C6 champion/challenger | finding | No trainer gate-check is possible (see C1). In-unit comparisons used the same folds, rows and costs: dbf8-01, f1a0-33 (Δ −0.0115 R, week-clustered t −1.22, **INDETERMINATE**), c7e3-01..06. **Every AM random control so far drew its placement with exit-time knowledge** (c7e3-06 controls mean +4,310 R against a HOLD book of −10,282 R on the same trades). The R4 "beats 95% of controls" clause is invalid on every earlier AM result. |
| C7 drift | finding | (a) Plan-only scan: success, 19 rows in the last hour, **0 drifted**. `/shadow/drift` reads BTC fc-pcv-v2 KS 0.504 for the **3rd consecutive weekly read** (11-11, 11-18, 11-25). The two instruments disagree (PI-20261118-EUWZZMDP-0003, re-confirmed). (b) LIVE-DECAY CUSUM (`live_decay_cusum.py`): `ml_entry` **no trip, S 4.25, peak 5.99, h 8.02, n 59**; `ml_entry_eq_struct` n 1, indeterminate. |
| C8 concentration | finding | `--diversity`: **CONCENTRATION gbdt 14 of 19 open family-tagged items (74%)**; manifests 79 of 108 gbdt; 8 served models `UNMAPPED` to a family. |
| C9 research landed | ok | 195 ML-tagged result records since 11-18T20Z (units with `iteration.subject_kind: ml_model`, `ml_bakeoff` or `ml_consumer`): fail 88 · indeterminate 54 · pass 32 · not_applicable 19 · no_action 2. ml_entry levers f1a0-01..33: 0 PASS. AM v2 c7e3-01..04 FAIL, 05 PASS (**invalid**, leak), 06 FAIL; c7e3-07/08/09 queued. |
| C10 DSR | finding | `dsr_probation.py`: `ml_entry` and `ml_entry_eq_struct` are both `not_computed` (no readable per-trade series); 7 of 9 production legs are on probation. |
| C11 overlay CUSUM | ok | `overlay_cusum_join.py --cusum` (overlay_shadow 121 rows × 177 closed trades since 11-17): `bybit_2` joined 5, reduced 1, S 0 / H 2.0, no alarm; `tradeify_1` `no_reduced_trades` (n=0, not a pass). |

**Weekly progress lines:**
1. Data coverage: `could_not_look`; no per-family share instrument was run this session.
2. Features in use: `could_not_look`.
3. Retrain freshness: the served ENTRY pointer is v1r20261122, 3 d old (INFERRED from its id; the trainer has no registry entry for it).
4. Live vs held-out: `ml_entry` live −0.167 R/trade (n 59, 5 symbols) against a held-out +0.0371 R/trade.

**D-slot coverage** (MEASURED; population: queued `research/queue/*.yaml` with an ML subject or consumer):
- D3 entry: 10 units (`ml_entry` 6, equity-native 2, struct 1, all-accounts 1).
- AM brackets: 5.
- D2 regime gate: 6. All are classifier-metric variants; the cost-net consumer test 78fc-08 is blocked.
- D4 overlay: 2.
- **D7 TP revision: 0.**
- **D8 exit head: 0.**
- D1: 3, but these are strategy-leg re-measures, not ML.

Research-ops' 11-24 alarm still stands for D7 and D8.

## 2. ANALYSIS

### Q1: The ml_entry evidence picture under the promotion-rule fix *(real money; −9.84 R lifetime)*

**What put it on real money.** RQ-20261103-5e04-01 / c692-06 (`comms/strategy_evidence/ml_entry.json`, `basis: heldout_window`):
- tau 0.10 was chosen on 8 purged dev folds (2022-01..2025-09).
- The model was frozen, then the held-out window **2025-10-01..2026-09-30** was scored once: **+0.0371 R/trade, n 907, ΣR +33.7**.
- iid se 0.0362 gives t 1.03. No clustered se exists, and the DSR is not computable (C10).

**What has happened to that window since.** f1a0-33's author records **27 ENTRY reads of the 2025-10 window** (INFERRED: I did not
recount them). The dev-fold base recipe earns only **+0.0030 R/decision over 71,334 decisions** (f1a0-33, MEASURED). That is an order of
magnitude below the held-out figure.

**Live.**
- 59 real-money trades, ΣR −9.84, −0.167 R/trade.
- At an assumed sd of 1.09 (the power record's figure), se ≈ 0.142. Live is then t ≈ −1.2 against zero, and z ≈ −1.4 against the
  Stage-0 mean (ESTIMATED).
- The live bar (≥ 20 trades, ΣR > 0, ~80% lower bound > 0) is **not met**.
- The registered demotion read (t ≤ −2 at n ≥ 100) is **not triggered**, and neither is the CUSUM (S 4.25 < h 8.02).

**Two hypotheses.**
- **(a) Noise around a small true edge.** The live loss is within 1.4 se of +0.037. On this alone, the CUSUM would stay quiet for
  months.
- **(b) The +0.037 is a selected number.** The held-out read was the window the pass was graded on, and the dev base sits at ≈ 0.
- **The discriminating test is a fresh window.** It replays decisions from 2026-10-01 onward through the frozen v1 recipe; the
  Binance Vision archives are public. It needs no new live trades.
- **Power is the catch.** 3,453 trades are needed to confirm at t = 2. A ~8-week fresh window gives about 150–250 decisions on 5
  symbols, so it can refute a large edge but cannot confirm +0.037.

**Under the operator's 11-25 rule ("a number measured only over the grading window must not promote"):**
- `ml_entry`'s only promoting number is that held-out read, so **it has no qualifying promotion evidence under either reading of the
  rule**: the held-out was the grading window, and the live bar fails.
- **It is the operator's call (Tier 3)** whether that means demote-to-floor, or keep as the D3 live baseline while a challenger is
  run. The 11-16 rule says a live baseline keeps trading until a challenger beats it.
- I propose the re-grade and its fresh-window read, not the action (P-1, P-2).
- **Rejected alternative:** waiting for live n ≥ 100. That is a future-month read where an in-hand window exists (research-ops
  "iterates on in-hand data").

**`ml_entry_eq_struct` has the same structure** (one held-out read, `param_selection_provenance: null`), but it is stronger
(clustered t 2.06) and has n=1 live. It goes into the same re-grade.

### Q2: What do this week's ML tests show, and what don't they show? *(D3, AM)*

**ml_entry.** 33 lever units (execution, sizing, funding, OI/taker inputs, timeframe, target) gave 0 PASS. The target lever f1a0-33
came back INDETERMINATE in the wrong direction (Δ −0.0115, t −1.22, 2 of 8 folds better).

Every arm sits on a recipe whose dev-fold base is +0.003 R. **A 33-unit null over one base is a statement about the base, not the
levers.** The levers can only move a near-zero mean by a few thousandths, and the registered MDE (+0.0068) is at that scale.

**AM v2.** Four action-value classes FAILED (c7e3-01..04). The c7e3-05 PASS is void: its random control placed actions at bars
chosen with knowledge of when the trade exits.

**c7e3-06 is the clean read.** The fixed age-5 tighten, vs HOLD on 275,378 dev trades:
- net R −11,613 vs −10,282 (worse by 0.0048 R/trade);
- CVaR5 cut 13.8%, below the 15% bar;
- max drawdown worse by 9.9%;
- 0 of 6 folds held.

It **fails R2 and R3 on its own**, independent of the leaky R4. So the FAIL stands. The leak does not rescue any earlier AM FAIL;
it only voids PASSes and the R4 clause.

ML-PRIMARY authored c7e3-08/09 (causal draws), and they are queued. I do not duplicate them.

**Is it learning?** H3 = 0 for desk labels while H2 = 5. Labels are produced but no dataset reads them, which is the same shape as
last week.

### Q3: Why do D7 and D8 have no next unit? *(Labrador-1b changes real-money exits; Labrador-2 changes none)*

**D7 (Labrador-1b).** Its power record has mean 0.0081 at n 868 with no se, so it cannot be read. Its owner row ML-ENTRY-TP-REVISION
is `landed_unproven` (due 12-01). Nobody owns the question "is the TP revision adding value on the same trades?"

**D8 (Labrador-2).**
- Its owner row ML-EXITHEAD-VALUE is `landed_unproven`, due 11-12 (overdue).
- 14 exit-head units graded this week (latest verdict per unit): 1 pass, 11 indeterminate, 1 fail, 1 not_applicable.
- No ETH out-of-sample read exists, and ETH is the one leg it could act on.

**Two hypotheses.**
- (a) The iteration loop only authors from a FAIL, and these slots produce INDETERMINATEs and `landed_unproven`s.
- (b) Capacity went to D3/AM.

The queue shows both: 15 queued units on D3+AM, 0 on D7/D8. **Proposals P-3 and P-4.**

### Q4: The trainer can't see the models that trade *(every order-changing model)*

All 8 served models fail `gate-check` with "no registry entry". So stage-guard, cost-gate and `live_parity` cover only the 100
housekeeping heads. Of those, 3 advisory D2 heads route nothing that the consumer feed can see.

Row ML-REGISTRY-SERVED-MODELS-NO-STAGE has been `queued` since its 11-14 due date. This is the single largest blind spot in C1/C5/C6.
**P-5.**

### Q5: Concentration and frontier *(capacity)*

gbdt holds 74% of open items. This week's 33 ml_entry levers and 6 AM units were all LightGBM.

The scan (`docs/research/frontier-scan-2026-11-25.md`) **keeps two methodology ideas, not models**:
- a reusable-holdout / held-out-read ledger (Dwork et al. 2015) for the promotion-rule fix;
- PBO/CSCV (Bailey et al.) as the deflation for configuration selection.

It drops the new TSFM/TFM releases (TabAbax, Kumo Tabular, TabPFN-3.5, TiRex-2, Toto 2.0, TimesFM-3), each with a named gate. Their
D3 benefit is capped by the near-zero base (Q2), and the tabular lever row is `dropped`.

**Surprises:**
1. The Foxhound-1 refit pointer has no power record.
2. `FRONTIER-LEVER-TABULAR` has been `dropped` since 10-23 while two reviews called it queued.
3. 15 open ML pipeline items point at owner rows that are `done` (10 of them at ML-HYGIENE).

## 3. Decisions (ranked by money; each carries a pre-registered check)

**Audit-outcome contract:** each proposal maps to a row, unit or named decision, with a `due_by`. No units are queued by this lane.

| # | proposal | label | maps to → due_by | p | check (resolves when) |
|---|---|---|---|---|---|
| P-1 | **Re-grade `ml_entry` and `ml_entry_eq_struct` under the operator's 11-25 promotion-rule fix.** Record whether each leg's promoting number was measured only over its grading window, and state the outcome as qualifying / not qualifying. | TRADING | **named operator decision**: the promotion-rule-fix row the manager opens (operator 11-25) → 2026-11-30 | 0.85 (that ml_entry is "not qualifying") | a committed re-grade record naming both legs (by 11-30) |
| P-2 | **Fresh-window read of frozen ml_entry v1** on 2026-10-01..latest Binance Vision decisions, 5 bybit_2 symbols, full cost stack. Register before the run: PASS iff mean net R > 0 at day-clustered t ≥ 2; FAIL iff mean < 0 at t ≤ −2; else INDETERMINATE, stated as underpowered for +0.037 (~200 decisions vs 3,453 to confirm). | MODEL | unit, to be authored by ML-PRIMARY on manager go → due 2026-12-02, roadmap L-ML-LIVE | 0.25 PASS · 0.20 FAIL · 0.55 INDET | result record exists by 12-02 |
| P-3 | **D7 next unit:** Labrador-1b revised-vs-held TP on the same trades, delta net R with day-clustered se, on the mirror and the replay. This fills the empty slot and the missing se. | MODEL | row ML-ENTRY-TP-REVISION (due 2026-12-01, L-ML-LIVE) → unit by 12-01 | 0.35 that delta > 0 at t ≥ 2 | a unit with `iteration.subject` D7 queued by 12-01 |
| P-4 | **D8 next unit:** ETH out-of-sample delta net R for Labrador-2, the declared read ("< 0 at n ≥ 30 → annotate"). | MODEL | row ML-EXITHEAD-VALUE (M25; due 11-12, overdue; re-date to 12-02) → unit by 12-02 | 0.30 positive | the unit or result exists by 12-02 |
| P-5 | **Register served models in the trainer registry** (or give gate-check a served-model path) so C1/C5/C6 can look at the 8 order-changing models. | MODEL | row ML-REGISTRY-SERVED-MODELS-NO-STAGE (queued, due 11-14; re-date 12-03) | 0.40 done by 12-03 | `gate-check ml-decision-entry-v1r20261122` returns a packet |
| P-6 | **Held-out read ledger:** count reads per (subject, window) from the research results so "spent window" is a number, not a claim. This is the instrument for the 11-25 rule (frontier keep #1). | MODEL | **named operator decision**: fold into the promotion-rule-fix row (P-1) → 2026-11-30 | 0.6 adopted | the rule text cites a read count |
| P-7 | **Re-route 15 ML pipeline items whose owner row is `done`** (10 at ML-HYGIENE, ML-ENTRY-RETRAIN-CADENCE ×2, ML-REGISTRY-LADDER-GAPS, ML-ADVISORY-SCOPE-GUARD, ML-QUEUE-DIVERSIFY). Each is either killed with a reason or re-pointed to a live row. | MODEL | manager (Thursday planning) → 2026-11-27 | 0.7 | `review_followthrough` ml-review backlog has no item on a `done` owner (by 11-27) |
| P-8 | **Void the R4 control clause on every AM result before c7e3-08/09.** This is a grading note, not a re-run, and it changes no FAIL. | MODEL | owner ML-PRIMARY (c7e3-08/09 already in flight) → 2026-11-27 | 0.8 | the AM programme plan or iteration block notes R4-void |
| P-9 | **DRIFT-REMEDIATE-btc-regime-15m-lgbm-fc-pcv-v2:** 3rd consecutive drift read. Apply `drift-remediation` (labelled macro-F1 held last week, so the regime-mix hypothesis comes first). | MODEL | existing row (due 2026-11-25) → re-date 2026-12-02 | 0.65 still KS ≥ 0.20 on 12-02 | `/shadow/drift` KS on 12-02 |

**Calls for next week's Layer 0:**
- P-2's verdict split as stated.
- `ml_entry` real-money ΣR stays < 0 at the 12-02 read (p 0.7; check `/performance?window=all` perStrategy).
- The CUSUM does not trip by 12-02 (p 0.85; check `live_decay_cusum.py --leg ml_entry`).

**Backlog drain** (hard gate): 55 open ML items (population: origin ml-review, routed_to ML*, or `[ml]`/`[refinement]`). All 55 are triaged
in the JSON: 0 resolved · 0 fixed_now · 15 owner-done (re-route P-7) · 40 kept_open with this run's re-validation. **count_untriaged
0.** Redated with this run's observation: ZZUFKM1F-0001, EUWZZMDP-0003, TX7TX2ZN-0002, DGUBH8UA-0002.

## 4. Not done

- C5 feature-row parity diff (no served registry entry; P-5).
- Weekly progress lines 1–2 (no instrument run).
- The practice refresh (sibling lane).
- No `send-ping` system-action was dispatched. The manager receives this report instead.
<!-- ML-FRONTIER-PREP:END -->
