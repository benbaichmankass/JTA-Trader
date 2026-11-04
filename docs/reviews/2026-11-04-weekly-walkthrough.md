# Weekly walkthrough 2026-11-04

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-04` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · one brief, three lanes (PERF-REVIEW-PREP, ML-FRONTIER-PREP, PRACTICE-REFRESH), each writing between its own markers; feeds Thursday planning.

<!-- ML-FRONTIER-PREP:BEGIN -->
# MODEL track — /ml-review 2026-11-04 — ML now changes real-money orders, but only through models the registry does not hold, and the one on real money is trained on data that ends 2025-09-22

> Lane `ML-FRONTIER-PREP-20261104` (Tier 1, read-only, dispatched by Manager Session 2026-11-04a). It runs `.claude/skills/ml-review/SKILL.md` and
> `.claude/skills/frontier-research/SKILL.md` (both two-layer). **Nothing was promoted, queued or deployed, and no `config/`, `src/` or `ml/configs/` file was touched.**
> New work is **proposed** in § 3, each item labelled MODEL or TRADING. Records: `comms/reviews/ml-review-20261104-200000.json` · `comms/ml-plan/20261104T2000Z-ML-FRONTIER-PREP.json`.
> **Context, cited and not duplicated:** ML-ROADMAP-MECE draft PR #22892 (`docs/plans/ML-ROADMAP-MECE-2026-11.md`) maps the models to ten lifecycle decisions and inventories the registry: 98 rows = advisory 3 · shadow 20 · candidate 74 · research_only 1. The three models that change real-money or prop orders are served outside the registry. This section is written to feed that synthesis.
> **Practice refresh:** owned this week by the sibling lane PRACTICE-REFRESH, so it is not repeated here.

**Headline numbers (MEASURED; I re-parsed `config/accounts.yaml`, `regime_policy.yaml::trend_vol`, `overlay_policy.yaml`, and `strategies.yaml` `exit_head_action` and `ml_entry*` at `main@0dfee7b5b`):**
- **ML changes 14 of 75 rostered (account, leg) pairs.** That includes **2 of 7 real-money pairs** and **3 of 3 prop pairs**:
  - real money: `bybit_2` `ml_entry` (Foxhound-1, since PR #22261, 11-01) and `bybit_2` `trend_donchian_xrp_4h` (TD overlay `reduce`, PR #21213, 10-29);
  - prop: `trend_donchian_eth_prop` (overlay `reduce`) on `breakout_2`, `tradeify_1` and `velotrade_1`.
  - Last week's denominator was 51 legs, and the roster has grown since. On 10-28 the real-money count was 0/7. The change is real, not a re-count: both PRs landed after that review.
- **Not one of those order-changing models is a registry row.** The 3 advisory registry heads change only `bybit_1` demo legs (BTC `trend_vol` cells).
- **The first broken hop of the learning chain is still H6→H7 for registry models.** For the order-changing models the ladder is bypassed altogether: they reach H7 with no H6 (C4).

## 0 · Prior calls

**Follow-through** (`review_followthrough.py`, 7 d):

| source | cohort: filed / done / killed / open | backlog: open, % due, median age, no owner |
|---|---|---|
| ml-review | 6 / 0 / 2 / 4 | 14 open, 57 % due, median 17 d, 0 with no owner |
| frontier | 18 / 6 / 6 / 6 | 16 open |

The manager's **bulk reset (2026-10-29, "value unknown (operator)")** killed P6 (`PI-20261028-GNVUF1ES-0003`) and the power audit (`LFC7HPXG-0001`).

| call (10-28) | p | outcome (re-run check) | grade |
|---|---|---|---|
| 1 · no metalabel head passes the cost gate after the cost-net rebuild | 0.75 | the rebuild (`V8KBRR5H-0004`) is still `routed`, due 11-06 | **unresolved** |
| 2 · ≤ 1 of the next 10 regime/direction variants PASS | 0.80 | 17 variant-vs-incumbent units (baseline ≠ prior) have results since 10-28: **7 PASS**, 4 FAIL, 6 producer_failed. That is 7 PASS of 11 graded (7 + 4 + 6 = 17). The registered bars were +0.001 or −0.001 (non-inferiority), and the 3 direction PASSes beat a LightGBM that is itself worse than the prior (§ 2.2) | **miss** as written. The spirit held: there is no material gain |
| 3 · ML still changes 0/7 real-money legs | 0.85 | 2/7: the overlay and Foxhound-1, both served outside the registry | **miss**. Breadth arrived through a path the call did not model |
| 4 · MES-5m margin stays in 3.7–4.3 over 6 cycles | 0.70 | 4.03 / 3.71 / 3.77 / 3.91, then 30.9 / 30.7: the baseline went degenerate on 11-02 | **void**. The comparator broke (§ 2.3) |
| 5 · BTC/SOL advisory drift is transient (minor or none next read) | 0.55 | both `no_change` (KS 0.029, 0.045) | **hit** |
| 6 · TTM + Log-HAR beats the vol head (if P3 is registered) | 0.25 | P3 not registered | **unresolved** (void if still unregistered at 11-25) |

- **Of last week's proposals, P2 (Q-TM1) was registered and ran:**
  - `RQ-20261029-7294-02` **FAIL**, powered: 2,627 trades, 6 purged folds, full cost stack. The action-value policy vs hold is −0.059 to −0.079 R/trade, and every CI is below 0.
  - `RQ-20261030-c7a1-01` (Q-TM1b) **FAIL**: no action class has out-of-fold rank skill above the permutation p95.
  - That is the informative outcome the call asked for.
- **Score: 1 hit, 2 miss, 2 unresolved, 1 void.** Brier is INDETERMINATE (n < 10 resolved).
- **What changes because of it:**
  - Breadth calls now count served artifacts. That is C3 below, and MECE § 1.2.
  - Any call that rests on a baseline comparator names the comparator's own health check.

## 1 · CHECKS

| # | check | population | state | reading |
|---|---|---|---|---|
| C1 | trainer + registry | 98 rows (`/api/bot/ml/status` + `/registry`, mirror ≈ 2 min old, ~19:00Z); last cycle | **finding** | Last cycle `cycle_end` 2026-11-04 08:47Z: rc 0, `complete_with_refusals`, 67 ok, 6 refusals. `refusing_manifests_24h` is 3 (all tracked). **Trainer disk 80.2 % (83.3 / 103.9 GB). It was 52 % on 10-28: +28 points in 7 days.** That is a health-review item, flagged in § 4. `--plumbing` `REGISTRY-STAGES-CHANGED`: shadow 20 / candidate 74 against a plan of 21 / 72. That gap is one unexplained shadow→candidate move plus one new candidate (`setup-candidates-metalabel-p2pool-v2`, 10-29), owned by `ML-REGISTRY-LADDER-GAPS` (MECE: `stage_history` is empty on 68 rows). Not re-filed. **Trainer pull #22899 (19:11Z):** timer active, next run 11-05 00:10Z. Daily cycles 11-01..11-04 each trained 67 with 3 enforced audit skips, rc 0. No `oom` line in the 400-line tail. **Stage-guard: 98/98 `hold`**, no promote or demote. RAM 5.9 GB, 1 vCPU, disk 81 % |
| C2 | data + label freshness | 73 manifests; builds 24 h | **finding** | Builds: 122 ok, 0 failed, 2 skipped. `TRAINING-STALENESS`: 4 stale, 2 never trained. **market_raw shards are whole** (BTC 1h 43,824 · 5m 525,888 · ETH 1h 43,824 · ADA 15m 175,296), so `WH81NW96-0001` and ML-D6 are closed. `claude_judgments` is 883 rows (627 on 10-28). **Served ENTRY artifacts:** Foxhound-1 (real money) has data through **2025-09-22**; Foxhound-2 and Labrador-1b through 2026-09-22 |
| C3 | business-use map | 75 rostered pairs (7 real, 3 prop); every model a consumer reads | **finding** | **14 / 75 · real money 2 / 7 · prop 3 / 3.** Order-changing models: Foxhound-1, Labrador-1b (moves Foxhound-1's TP), the TD overlay, the exit head (`close` on `trend_donchian_eth`, demo), Foxhound-2 (demo), and the 3 advisory vol heads (BTC demo cells). The SOL-15m and MES-5m advisory heads change **0** legs, as they did last week. Detail: MECE § 1.2 |
| C4 | learning chain H1→H7 | the sources in ML-PROGRAMME § 7, since 10-28 | **finding** | H1–H3 ✅ (judgments +256 rows, closes and the paths corpus accruing). H4 ✅ for market features (67 trained); ❌ for teacher data (0 manifests). H5 ✅. **H6: 0 stage changes this week.** **H7 is reached by served artifacts with no H6.** Foxhound-1, Labrador-1b and the overlay were promoted by Tier-3 PRs (#22261, #22278, #21213), not by the registry ladder. So the cost gate, stage-guard and drift endpoint never see them. `ML-LEARNING-LEDGER` is still queued (no instrument) |
| C5 | serve parity + soak | 6 heads gate-checked (pull #22899): 3 advisory + the 3 nearest shadow | **finding** | `live_parity` passes on BTC fc-pcv-v2 (27/27), fc-pcv-v1 (27/27), SOL fc-pcv-v2 (24/24) and **MES-5m (50/50, so the served MES head still matches its training rows after 11-02)**. **btc-15m yz-v1 still fails: `vol_bucket` is dead live** (`3WM5HADW-0005`, unchanged). btc-1h v2 is `insufficient_data` (9 rows since the 01:54Z retrain reset). Soak is mechanical, 1 clean prediction needed and 1,826–7,741 present (OPERATING-PLAN § 2). `beats_baseline` (Brier lift) is negative on every BTC/SOL head because the served score is max-probability, not P(class) (`3WM5HADW-0004`). For the served ENTRY artifacts there is **no parity check at all**. Rows `ML-FS-SERVE-PARITY` and `ML-PROMO-PARITY` are both queued |
| C6 | champion vs challenger + cost gate | cost-gated heads; same-replay results | **finding** | Every registry head still reads `cost_gate_passed 0` or `not_applicable` (MES-5m 11-04: applicable 0, enforced 1). Same-replay comparisons this window are the `ml_bakeoff` units; § 2.2 shows the direction-label rule is mis-specified. **Foxhound-1's live comparison** is the registered held-out figure, +0.0073 R per decision, beside its own W1 window read of −0.0405 R (n = 320). It has no cost-gate packet because it is not a registry head |
| C7 | drift, split | advisory + nearest shadow | **watch** | (a) KS, from `/api/bot/shadow/drift`, 30 d vs prior 30 d: BTC-15m fc-pcv-v2 **no_change** 0.029 · SOL-15m **no_change** 0.045 · MES-5m minor 0.095 · btc-15m fc-pcv-v1 minor 0.079 · btc-1h v2 minor 0.085 · **btc-15m yz-v1 moderate 0.122** (moderate 0.139 on 10-28: a second consecutive moderate read on a *shadow* head whose `vol_bucket` is dead live, so INFERRED to be the same defect, not regime). **Plan-only drift scan (pull #22899): Result=success, rc 0, 23 rows, 0 `dispatch`/`skip_no_manifest`. 0 drifted, 0 persistent, so no `DRIFT-REMEDIATE` row.** (b) Labelled decay: **could-not-look, no instrument** (`LIVE-DECAY-MONITOR` queued since 10-16). The served ENTRY model has no monitor either (`ML-ENTRY-LIVE-MONITOR` queued) |
| C8 | concentration | registry; open plan items | **finding** | `MANIFEST-CONCENTRATION`: gbdt 77/98. **All 33 ML research units graded this week target `regime_label` (22) or `direction_label` (11).** That is 100 %, against 50 of 50 last week. No `FAIL-STREAK` |
| C9 | research landed + backlog | 443 units with results committed since 10-28 20:00Z; 33 of them `ml_bakeoff` | **finding** | Latest verdict per ML unit: 17 PASS · 5 INDETERMINATE · 4 FAIL · **7 producer_failed** (`a4e7-12/13/14`, `e5b1-04..07`). Outside `ml_bakeoff`: Q-TM1 FAIL, Q-TM1b FAIL, TM-BENCH v1 PASS (selfcheck). Backlog: § 4 |

**Weekly progress lines** (row ML-WEEKLY-REVIEW-LINES; for the live ENTRY artifact, Foxhound-1):
1. **Data coverage** per feature family per symbol, last 7 d of decision rows: **could_not_look**. No instrument reads the live decision log by family; the row landed only the skill text.
2. **Feature count in use:** live 20 columns (`ml/served/ml_decision_entry_v1/model.json`) vs 20 admitted (fs01: no family cleared +0.010 R). Not below the admitted count. The `market_features` schema holds 108 per-symbol columns, which ENTRY does not read.
3. **Retrain freshness: 408 days** (data through 2025-09-22, read 2026-11-04) vs the weekly cadence. **RED.** `ML-ENTRY-RETRAIN-CADENCE` promised a held PR by 11-02 18:00Z and is still `queued`.
4. **Live vs held-out:** n = 4 closed `ml_entry` trades on `bybit_2` since 11-01, PnL % +1.60, +1.97, −0.23, −1.79; the R basis is not on the route. The held-out figure is +0.0073 R per decision. **n = 4 is no evidence either way.**

## 2 · ANALYSIS

**2.1 The models that move money sit outside the ML lifecycle (the material finding).**
- The registry ladder (candidate→shadow→advisory, gate-check, stage-guard, drift, cost gate) governs 98 rows. Of those, 3 advisory heads change BTC demo cells.
- The models that change real-money and prop orders went live by Tier-3 PR. Each carries its own evidence record (c692-06 for Foxhound-1, 383f-01 for Labrador-1b, the overlay's CUSUM). That is the evidence standard the operating plan asks for, so **this is not an unauthorised promotion.**
- What is missing is every *standing* control the ladder supplies:
  - no parity check between the served feature row and the training row;
  - no drift read;
  - no labelled-decay monitor (`ML-ENTRY-LIVE-MONITOR` queued);
  - no retrain schedule (`ML-ENTRY-RETRAIN-CADENCE` queued and past its own deadline).
- **Competing hypotheses for why the controls are missing:**
  - (i) Nobody owns them: the rows exist but were never dispatched.
  - (ii) They are blocked on infrastructure: the feature store and the serving inventory.
  - Both rows are `queued` with no lane, and MECE P1 (ML-SERVING-INVENTORY, about $6) is the precondition for keying monitors on served models. That fits (i) first and (ii) second.
- **Rejected alternative:** registering Foxhound-1 into the trainer registry so the existing gates see it. The registry's gates are classification gates built for regime heads. The cost gate would read `not_applicable` and give false comfort (`GNVUF1ES-0002`).

**2.2 What this week's 33 ML units show, and what they do not.**
- **They are the same question again.** Every unit targets a regime or direction label, and none names a consumer that changes a real-money order. The 7 producer_failed are a runner-route failure. They are not verdicts, and research-ops owns them (§ A).
- **The direction-label PASSes are learners that reach the class prior.** In `b3c9-14/15/16`, CatBoost, HGB and ExtraTrees "beat LightGBM" by +0.006–0.007 log-loss, but in the same records **LightGBM is worse than the class prior by 0.006–0.007**, and CatBoost vs the prior is −0.0001 to −0.0006 (CI spans 0). The rule compared only to the incumbent.
  - Hypothesis: real skill. Refuted by the prior arm in the same record.
  - Hypothesis: a rule with no prior floor. Fits.
  - Filed: `PI-20261104-DGUBH8UA-0003`, a beats-prior clause in the rule-drafting standard.
- **One PASS points the right way:** `d5dd-17` (LightGBM + HAR features vs LightGBM, 1h) gives +0.004 / +0.010 / +0.008 log-loss on BTC / ETH / SOL. It is sign-consistent on ETH only, at 5 folds. That agrees with the frontier evidence (2607.05291: HAR-type inputs carry RV forecasts). But no 1h head feeds a router cell, so it changes no order today (C3). Its value runs through last week's P3 (Q-REG1), which is still unregistered.
- **Trade management, the question that changes orders, got an informative null.**
  - Q-TM1: a GBDT action-value exit or tighten policy *loses* 0.06–0.08 R/trade vs hold on the six money legs, net of cost, over 2,627 trades in 6 purged folds.
  - Q-TM1b: the per-action advantage is not predictable out of fold at all.
  - This closes *that configuration*: R1 state features and corpus v1. It does not close the family. The next iteration (`78fc-04`, path-state features) is blocked on a truncation-invariance self-test, and Q-SEL1-BROAD and DATA-TRANSFER are blocked on corpus v2.

**2.3 The MES regime family changed under us on 11-02.**
- **What happened (MEASURED):** both MES baselines collapsed to "range on every row" (recall_volatile 0.00), and the MES-5m advisory head lost 3.3 macro-F1 points. In the same cycle the volatile-label support rose by 285 while n grew by only 157, so **the labels moved, not the sample.** BTC and SOL are unchanged, which acts as the control.
- **Competing hypotheses:**
  - (H1) US DST ended on 11-01, and MES session-bound bars or labels shifted 1 h in UTC.
  - (H2) A code or source change in the 224 commits `0cf82cc3e..d1ed0a830` (none touches `ml/configs/mes*` by path).
  - (H3) A real MES regime shift.
  - The timing (the first cycle after DST, a step change rather than a drift, MES only) favours H1 or H2 over H3. **I have not tested this. It is INFERRED.**
- The discriminating read is the per-day volatile-label share on the trainer: `PI-20261104-DGUBH8UA-0001`.
- **Money impact is low:** the MES-5m head changes 0 legs. It does void the MES `[refinement]` margin series (`GNVUF1ES-0001`, re-dated).

**2.4 Frontier scan (F1–F4).**
- **F1:** last scan's units. P2 ran (an informative FAIL). P3 and P4 are not registered. Q-SEL1 survives only as Q-SEL1-BROAD, which is blocked.
- **F2:** `--diversity` reports MANIFEST-CONCENTRATION gbdt 77/98, no FAIL-STREAK, and 3 open items with no family.
- **F4 lever rows queued across ≥ 2 scans:** `FRONTIER-LEVER-HARNESS-COSTS`, `-LEADLAG` and `-TABULAR` since 10-23, `-TSFM-TIMESTRAL` since 10-25, and `-XSEC-RUNNER` in_flight with no update since 10-28. These are **raised to the manager** (§ 4), not re-filed.
- **F3 sources (4 of 4 required rows, plus the every-other-week rows):**

| source | state | read (PRIMARY / secondary) |
|---|---|---|
| Hugging Face Hub (papers trending + searches; model search) | checked | Trending: Kronos (2508.02739, K-line FM, 2025), TradingAgents (2412.20138). Abstracts read: **2512.08124** (crypto *ranking* NN, long-only, Sharpe 1.01 2020–23, "robust to fees", PRIMARY abstract); **2606.27670** CryptoGAT (cross-asset graph beats temporal models on pure-price crypto; code on GitHub; PRIMARY abstract); **2602.00776** (Bieganowski & Ślepaczuk: the same order-book/trade features carry stable SHAP shapes across BTC…ROSE perps, CatBoost, 1 s data, PRIMARY abstract); **2510.13654** (TSFM evaluation leakage: train/test overlap and temporal overlap, PRIMARY abstract); 2610.28753 (LOB state-space FM, title only). The model search for time-series returned nothing new above last week |
| arXiv | checked (via HF papers + web) | the above, plus 2607.09426 *Quarter-Hour Effect* (Binance perps, periodic algorithmic flow; title and snippet only) |
| Lab releases | checked, **secondary only** | aggregators list Toto 2.0 (Apache-2.0), TiRex-2, TimesFM-3 (~330 M, 2026-08), t0-gamma, Timestral (revenue-capped licence), and **TimeH2O-v1** (H2O.ai, 108 M, announced 10-26; claims fev-bench #1, **unverified rumour**). None confirmed on a primary card this week |
| Quant practitioner literature | checked, thin | no 2026 SSRN primary on taker-flow cross-sectional predictability. Market commentary only (taker buy/sell ratio), not carried |
| Competitions / GitHub | checked (required this week) | G-Research Crypto Forecasting recap (secondary, gresearch.com): **all top 3 used LightGBM; the winners credit feature engineering over model choice.** CryptoGAT code link (above) |

- **Triage (six gates).** Every candidate is scored against the C3 consumers. The money consumer this week is Foxhound-1/2 (D3 entry), and trade management (D7/D8) has just failed on its R1 state.

| candidate | family | gates | kept? | p_pass | power |
|---|---|---|---|---|---|
| **Taker-flow + premium features for ENTRY** (2602.00776 portability; G-Research "features > models"; ml-feature-inventory § 2: taker-buy volume, trade count and quote volume are already downloaded and discarded at zero cost) | gbdt (feature lever) | data ✅ (in the klines) · compute ✅ · serve ✅ (inline OHLCV path) · leakage ✅ (bar-close) · business ✅ Foxhound-1/2 on `bybit_2` + `bybit_1` · power ⚠️ fs01 measured that any added column costs −0.017 (noise control) | **proposed as a variant of the existing increment row `ML-FS-ENTRY-V2`**, not a new unit (§ 3, P3) | 0.2 | decision-days on the W2 forward window; a replace-not-add design so the noise penalty does not mask it |
| **Cross-sectional ranking objective for ENTRY** (2512.08124; CryptoGAT's cross-asset framing) | gbdt (LambdaRank) / graph | ✅ data · ✅ CPU · ✅ serve · ✅ leakage · business ✅ D3, and MECE's D5 aggregator · power: decision timestamps across 60 perps | **proposed** (P4, MODEL) | 0.2 | ~777 k decision rows, but the test unit is the timestamp cross-section; folds = 6 purged |
| TSFM forecasters as raw signals (TimesFM-3 / Toto 2.0 / TiRex-2 / TimeH2O) | ts_foundation_model | gate 5: no consumer reads a point forecast; 2606.27100 found sparse gains; gate 4: 2510.13654 leakage on pre-2026 test windows | **dropped** | — | — |
| LOB state-space foundation model (2610.28753) | ssl_representation | gate 1: we have no LOB stream | **dropped** | — | — |
| Multi-agent LLM traders (TradingAgents) | — | gate 4: contamination (2605.16895, last week). The desk is already benchmark B3 | **dropped** | — | — |
| More learners on `regime_label` / `direction_label` | various | gate 5 plus C8 (33/33 this week) | **dropped** (second week) | — | — |

- **Graded last scan (Layer 0, frontier):**
  - TTM + Log-HAR (kept): **unresolved**, not registered.
  - TradeLens desk attribution (kept, P4): **unresolved**, not registered.
  - Conformal wrapper inside Q-SEL1 (kept): **miss**, its unit is blocked on corpus v2.
  - Regime-variant drop: **hit**, the 33 units bear it out.
  - TiRex-2 drop: **unresolved**.
- **What changes because of the grade:** I propose no TSFM unit. The keeps go to the one model that trades real money.

## 3 · Decisions — proposals (none queued; each labelled)

Ranked by expected value per cost. Each carries `p` and a pre-registered check in the review JSON `calls[]`.

| # | track | proposal | why now | cost to a verdict | rejected alternative |
|---|---|---|---|---|---|
| **P1** | **MODEL** | **Dispatch the two queued ENTRY rows as one lane:** `ML-ENTRY-RETRAIN-CADENCE` (a scheduled refit with the registered recipe, publishing data-through and sha, no halting) plus `ML-ENTRY-LIVE-MONITOR` (realised net R per closed ENTRY decision, flags at n ≥ 100). Filed as `PI-20261104-DGUBH8UA-0002` | the only ML model on real money has data 408 days stale and nothing reads its live R | Sonnet about $8, plus runner time | demoting ENTRY on n = 4 (no evidence; the operator ruled 11-01 that a failed Oct test does not block it) |
| **P2** | **MODEL** | **Endorse MECE P1 `ML-SERVING-INVENTORY`** (one table: model → slot → books → demotion signal). Make it C3's instrument from next week | C3/C4 cannot be computed from the registry any more | Sonnet about $6 (MECE's estimate) | registering served models as registry rows (§ 2.1) |
| **P3** | **MODEL** | **Taker-flow variant of the `ML-FS-ENTRY-V2` increment:** replace 3 of the 20 OHLCV columns with taker-buy share, trade-count z and premium, so the column count stays fixed (fs01 noise penalty). Same W2 forward window and rule (+0.010 R net, positive in ≥ 6/8 folds), plus a 3-noise-column control | the frontier's strongest data-ready lever for the live model, at zero download cost | runner, about $3 (it rides an existing row) | adding the columns (fs01: any add costs about 0.017) |
| **P4** | **MODEL** | **Ranking objective for ENTRY:** LambdaRank on the cross-sectional rank of the 24 h net return vs the current regression head, on the same 60-perp decision rows, 6 purged folds, net R of the top-k vs the incumbent's τ rule | a genuinely different question (D3 / D5), not a learner variant | runner, about $4 | a GAT model (no torch on the money box; ranking first) |
| **P5** | **MODEL** | **Rule-drafting standard: a beats-prior clause on every classification bake-off** (`PI-20261104-DGUBH8UA-0003`). Re-read b3c9-14..16 as no skill | 3 false PASSes this week | $0 (research-ops) | leaving the verdicts as they stand |
| **P6** | **MODEL** | **MES 11-02 root cause:** one trainer read of the per-day volatile-label share (`PI-20261104-DGUBH8UA-0001`) | an advisory head moved 3.3 points and its comparator broke | one trainer pull, about $1 | waiting for 3 more cycles |
| **P7** | **TRADING → `/performance-review` and `/health-review`** | `ml_entry` real-money closes carry closeReason `reconciler` (SOL, 11-03) and `other` (ADA, XRP). Under the session contract a reconciler close is a bug. The `other` labels may be Labrador-1b TP revisions written as `other` instead of `tp` (INFERRED) | the TP doctrine and close-reason grading on the real-money ML leg | handed off, not worked here | — |

**Stages:** no promote and no demote this week.
- The SOL-15m and MES-5m advisory heads still change 0 legs, so they remain a wiring-or-retire question.
- MES is under investigation (P6).
- **Gate packets (pull #22899):**
  - `ready: true`: BTC fc-pcv-v2 (advisory), MES-5m (advisory), BTC fc-pcv-v1 (shadow).
  - `ready: false`: SOL-15m (sample_sufficiency, 4 trades); yz-v1 (live_parity); 1h-v2 (live_parity insufficient after the reset).
  - Every gate is a classification gate (`cost_net` reads `insufficient_data` on all 6), so no `ready: true` is a promotion argument (as on 10-28).

## 4 · Backlog drain and not done

**Population:** 14 open ML pipeline rows (`origin.ref` names ml-review, `routed_to` starts with `ML`, or `what` starts with `[ml]`/`[refinement]`). **All 14 triaged; `count_untriaged` = 0** (1 resolved, 8 re-read, 5 kept open with a named blocker).

| disposition | n | items |
|---|---|---|
| resolved (done) | 1 | `PI-20261018-WH81NW96-0001` (shards whole, 0 failed builds) |
| kept open, re-read this run (`--redate`, with an observation) | 7 | `GNVUF1ES-0001` (MES margin voided by the 11-02 baseline break) · `GNVUF1ES-0002` (larger now: no money model is in the registry) · `3WM5HADW-0004` (max-proba still served) · `MVBJLVJ3-0001` (0 provenance calls) · the drift-gate BL (archives read; no covered-span field) · `UAOAYGBB-0001` (3 refusing manifests) · `01FXMMUG-0001` (constant scorer) |
| kept open, re-read via the trainer | 1 | `3WM5HADW-0005` (yz `vol_bucket` dead live, gate-check #22899) |
| kept open, not re-read (each needs the trainer or is not due) | 5 | `MB-20260719-PROMOREADY-OOSEDGE-OOM` (trainer RSS) · `PI-20261004-AHCVAAF5-0002` (calibrator holdout) · `MB-20260712-SHADOW-LOG-HISTORY` (SA-DATA test) · `PI-20261013-CAZHXZNE-0001` (GPU route) · `PI-20261015-SBAQDDVQ-0001` (not due until 11-11) |

**Filed this run:**
- `PI-20261104-DGUBH8UA-0001`: MES baselines degenerate since 11-02.
- `PI-20261104-DGUBH8UA-0002`: the ENTRY retrain and monitor are overdue (to the manager).
- `PI-20261104-DGUBH8UA-0003`: the beats-prior rule clause.
- **Plan loop:** 10 `CLOSED-OPEN` plan items closed in `docs/plans/ml-plan-items.yaml` (ML-D2, D3, D6, F0, F2T, F14, F27, F22L, M0, L1). After that, `--plumbing` shows plan items 80, open 39, 0 `CLOSED-OPEN`.
- **Not folded:** 63 `UNPLANNED` ML checklist rows. MECE's slot report (its P3, `ML-SLOT-REPORT`) is the structural fix, so this lane does not hand-fold them.

**Raised to the manager (not re-filed):**
- Lever rows queued across ≥ 2 scans: `FRONTIER-LEVER-HARNESS-COSTS`, `-LEADLAG`, `-TABULAR` and `-TSFM-TIMESTRAL`. Dispatch or kill each.
- `-XSEC-RUNNER`: in_flight, silent since 10-28.
- `LIVE-DECAY-MONITOR`: queued 19 d. P1's ENTRY monitor is the first concrete instance.
- **Trainer disk 80.2 %, up 28 points in a week.** This belongs to `/health-review`. The ML-D5 close bar is < 85 %.

**Not done:**
- Practice refresh (sibling lane).
- C7(b), labelled decay (no instrument).
- Weekly line 1, data coverage (no instrument).
- No send-ping: the lane reports to the manager, who relays the brief.
- A primary-card check of this week's lab releases (secondary only, so nothing is carried).
<!-- ML-FRONTIER-PREP:END -->
