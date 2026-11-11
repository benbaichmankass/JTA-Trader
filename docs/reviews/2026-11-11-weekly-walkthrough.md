# Weekly walkthrough 2026-11-11

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP-20261111`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH`). A section another lane has not landed yet is simply absent.
> On a collision, the later lane merges `main` first and keeps every other lane's section verbatim.

<!-- ML-FRONTIER-PREP:START -->
# MODEL track — /ml-review 2026-11-11 — the live ENTRY model has no established edge: its served replay loses −0.13 R per decision, every bit of it on the long side, while this week's 27 ML bake-off units again tested heads that change no real-money order

> Lane `ML-FRONTIER-PREP-20261111` (Tier 1, read-only, dispatched by Manager Session 2026-11-11a). It ran `.claude/skills/ml-review/SKILL.md` and
> `.claude/skills/frontier-research/SKILL.md` in full (four layers each). **Nothing was promoted, queued, deployed or demoted, and no `config/`, `src/` or
> `ml/configs/` file was touched.** New work is **proposed** in § 3, each item labelled MODEL or TRADING.
> Records: `comms/reviews/ml-review-20261111-200000.json` · `comms/ml-plan/20261111T2000Z-ML-FRONTIER-PREP.json` · `docs/research/frontier-scan-2026-11-11.md`.
> **Cited, not re-measured:** ML-CONSOLIDATION (#24897, `docs/plans/ML-CONSOLIDATION-2026-11-11.md`) inventories the 106 registry rows by slot: 15 KEEP, 19 REVIEW, 72 RETIRE proposed.
> **Practice refresh:** owned by the sibling lane PRACTICE-REFRESH this week, so it is not repeated here.

## S · Scoreboard (money first)

Source: `GET /api/bot/performance` (2026-11-11 ~19:00Z), lifetime window. **The route ignores `since=`** (it returned identical numbers for 7 d and 30 d), so
the 90 d / 30 d / 7 d windows are **could_not_look** on this route; the PERF-REVIEW-PREP section owns the windowed book view. R is net of the journal's
recorded costs. `$` is the measured P&L, not a balance.

| book | population | net R | exp R / trade | PF | read state |
|---|---|---|---|---|---|
| Real money + prop (journal top level) | 487 closed | **−152.1 R** | −0.31 | 0.63 | read. `bybit_2` known-divergent; `alpaca_live` unrecorded |
| Mirror (`paperPortfolio`) | 168 closed | **−32.6 R** | −0.19 | 0.63 | read. Mirror books partly unrecorded |
| Paper / demo floor | 1,786 closed | **−144.2 R** | −0.08 | 0.91 | read. 128 fabricated-P&L rows; 6 paper accounts unrecorded |

**Would a sceptical quant believe the ML legs have edge? The answer is about the decision each model changes, net of cost.**

- **`ml_entry` (Foxhound-1, refit r20261106; real money on `bybit_2`, plus 5 books): no.**
  - The registered held-out figure is +0.0073 R per decision (c692-01, n = 11,240).
  - Frozen v1 over its clean held-out year reads a mean of **+0.0085 R per decision across 13 windows of 28 days, window sd 0.127, t ≈ 0.24** (`RQ-20261108-98e3-26`).
  - The served replay of 10-25..11-07 reads **−0.13 R per decision, n = 317, CI [−0.25, −0.01]** (`RQ-20261108-98e3-23`).
  - DSR: `not_computed`.
  - Live: 12 closes on `bybit_2` since 11-01 (+4.96 R on the route's mixed R basis). n = 12 is no evidence either way.
- **`ml_entry_eq_struct` (Foxhound-4; real money on `alpaca_live`): plausible, unproven.**
  - Its evidence is one confirm window: +0.49 R per decision, se 0.076, n = 207, deflated bar met at N = 2 (`RQ-20261107-98e3-06`).
  - DSR: `not_computed`. Its only open unit is a forward read that cannot run before 2027-04-01 (`RQ-20261108-98e3-13`), and the iteration census cannot link it (filed, § 3 P3).
  - PR #24889 (operator Tier-3 approval, 11-11) widens this leg to the 173-ETF pool its test passed on.
- **Beagle-1 overlay** (TD `reduce` on `trend_donchian_xrp_4h` and `_sol_prop`, real money): **no standalone record was read this run.** Both legs it trims are on DSR probation (xrp_4h 0.023, sol_prop 0.332).

## 0 · Prior calls

**Follow-through** (`review_followthrough.py --window-days 7`):
- ml-review: cohort 3 filed, 2 done, 0 killed, 1 open. Backlog 12 open, 75 % due, median age 31.5 d, 0 with no owner.
- frontier: cohort 6 filed, 3 done, 0 killed, 3 open. Backlog 16 open, 69 % due, 1 with no owner.

| call (11-04) | p | re-run check | grade |
|---|---|---|---|
| 1 · no ENTRY artifact with data through ≥ 10-28 is served by 11-11 | 0.60 | The check as written reads `ml/served/ml_decision_entry_v1`: `train_end_exclusive` 2025-09-22. The artifact actually served (`ENTRY_SERVED.json` → `v1r20261106`) has `train_end_exclusive` 2026-10-14. Both are < 10-28 | **hit**. A refit *was* served on 11-06, which the call did not foresee. Its training data still ends before the bar |
| 2 · the 11-02 MES baseline collapse is a data/label construction change | 0.75 | No trainer per-day read yet. The baselines are degenerate on all 8 cycles 11-04..11-11, and the volatile-label share keeps climbing (5m 41.2 % → 44.9 %) | **unresolved** (`PI-20261104-DGUBH8UA-0001`) |
| 3 · ≥ 70 % of ML units graded in 7 d still target regime/direction | 0.80 | 38 of 38 `ml_bakeoff` result records generated since 11-04 20:00Z (27 units): 25 regime, 13 direction | **hit** (100 %) |
| 4 · live ENTRY mean ≤ 0 once n ≥ 30 | 0.55 | n = 12 on `bybit_2` | **unresolved** (carried) |
| 5 · yz-v1 drift is the dead `vol_bucket`, not regime (yz moves, fc-pcv-v2 does not) | 0.70 | yz-v1 KS 0.182 moderate; **fc-pcv-v2 KS 0.236 significant** (was 0.029 no_change) | **miss**. Both moved, and so did SOL-15m, MES-5m and fc-pcv-v1. A common input shift, not a yz-only defect |
| 6 · Q-TM1 next iteration (`78fc-04`) still blocked | 0.60 | still under `research/queue/blocked/` | **hit** |

- Frontier keeps graded: taker-flow ENTRY variant (P3), **unresolved**, not registered. LambdaRank ENTRY (P4), **unresolved**, not registered. Drops: TSFM forecasters and regime variants are **hits**, borne out by C3/C8. The LOB FM and LLM-trader drops are **void** (no new evidence).
- **What changes because of the grades:** any call about drift now names a cross-head control, because call 5 assumed the siblings were stable. Calls whose check reads a served artifact read `ENTRY_SERVED.json`, not a fixed directory.
- *Housekeeping:* 3 hit · 1 miss · 2 unresolved. Brier INDETERMINATE (< 10 resolved).

## 1 · CHECKS

**Headline numbers:**
- **ML can change 24 of 82 live-rostered (account, leg) pairs.** That is **4 of 6 real-money pairs** and **6 of 9 prop pairs**.
  - Population: `config/accounts.yaml` re-parsed at `main@9d6112782`, accounts in `mode: live`, joined to each model's consumer map (registry `consuming_strategies`/`accounts`, plus the BTC `trend_vol` cells).
  - The 2 BTC cell pairs (`bybit_1` `ict_scalp_5m`, `squeeze_breakout_4h`) count only if `REGIME_ML_VERDICT_MODE=use` on the VM, which this lane cannot read this week (diag token rotated). They are INFERRED from last week's read.
  - The real-money pairs ML does not touch: `bybit_2` `ada_pullback_2h` and `alpaca_live` `tqqq_trend_long_1d`.
- **First broken hop of the learning chain: H6 → H7 for registry models**, unchanged. The order-changing models are still served artifacts that bypass H6.

| # | check | population | state | reading |
|---|---|---|---|---|
| C1 | trainer + registry | 98 registry rows + 8 served inventory rows (`/api/bot/ml/registry`, mirror 107 s old); the last cycle | **finding** | Registry stages {advisory 3, shadow 20, candidate 74, research_only 1}. `--plumbing` `REGISTRY-STAGES-CHANGED` vs the plan's {shadow 21, candidate 72}: the same gap as last week, owned by `ML-REGISTRY-LADDER-GAPS`, not re-filed. The D2 rows read here (the MES baselines, MES-5m and BTC fc-pcv-v2) each show an 11-11 ~01:00Z run in registry `runs[]`. **Trainer pull #24903** (run 43082654333): timer active, service idle between runs, ExecMainStatus 0. Cycle 11-11 01:53Z: rc 0, trained 67, skipped 6 (3 enforced audit skips), failed 0, `trained_with_refusals`; the 08:05Z resume found all 73 done. **0 `manifest_oom_red_flag`.** Builds rc 0, augmentation not degraded. **Stage-guard: 97 hold, 1 DEMOTE, `btc-regime-15m-lgbm-fc-pcv-v2` (Collie-5a, the advisory BTC-15m head)**; its reasons are pulled in #24947. Trainer resources (#24938): disk 82 % (80 / 97 G; 80.2 % last week), RAM 5.9 GB, 1 vCPU. **4 `lifecycle_red_flag` lines: the `serve_parity` lifecycle job has failed 3 times running** for the BTC-5m shadow heads (`btc-regime-5m-lgbm-v2`, `-yz-v1`, `-flow-v1`, and plan `btc-regime-5m`). Retries continue (no halt); the heads change 0 legs |
| C2 | data + label freshness | 73 manifests (`--plumbing`); the served ENTRY artifacts | **finding** | `TRAINING-STALENESS`: 5 stale, 2 never trained (threshold 7 d). The served ENTRY refit has `train_end_exclusive` 2026-10-14 and `data_through` 2026-11-05. MES labels still drifting (C1 / `DGUBH8UA-0001`). 3 manifests built 0 rows (`exit-policy-v1`, `mes-execution-quality`, `setup-candidates-metalabel-paper-v1`). `exit-policy-v1` still has 0 registered runs (the C4 "absent from the registry" class, long-standing). |
| C3 | business-use map | 82 live pairs (6 real money, 9 prop); every model a consumer reads | **finding** | **24 / 82 · real money 4 / 6 · prop 6 / 9.** Consumers: Foxhound-1r + Labrador-1b (`ml_entry`, 6 books) · Foxhound-4 (`ml_entry_eq_struct`, `alpaca_live` + `alpaca_portfolio`) · Beagle-1 overlay (4 TD legs across 6 books, 9 pairs) · Foxhound-2 and -3 and Labrador-2 (demo) · BTC fc-pcv-v2 (2 `bybit_1` cell pairs). **The SOL-15m and MES-5m "live" regime heads still change 0 pairs** (registry `consuming_strategies` = []), for the 4th week |
| C4 | learning chain H1→H7 | the ML-PROGRAMME § 7 sources, since 11-04 | **finding** | H1–H3 accruing (12 real-money ENTRY closes, desk decisions). H4 ✅ (D2 heads retrain daily; the ENTRY refit). H5 ✅. **H6: 0 registry stage changes.** H7 is reached only by served artifacts. `ML-LEARNING-LEDGER` is still queued, so these are computed by hand, not by an instrument |
| C5 | serve parity + soak | shadow/advisory heads (trainer gate-check) | **finding** | Gate-check (pull #24903) was readable for 19 of 23 heads; the comment truncated the last 4; the advisory ones are re-pulled in #24947. `ready: true` on BTC-15m v2, fc-pcv-v1, **yz-v1**, SOL-15m fc-pcv-v1 and the ETH self-only control. For yz-v1 that means last week's dead-`vol_bucket` parity failure no longer blocks (INFERRED from `ready`; the parity line is outside the tail). `drift_clean` fails on 8 heads. The BTC-5m `serve_parity` lifecycle job is red-flagged (C1). The served ENTRY artifacts have **no parity check yet**. `ML-FS-SERVE-PARITY` and `ML-PROMO-PARITY` are queued, and `ML-LIVE-PARITY-ML-LEGS` was filed 11-11, after the weekly live-vs-replay parity run could not check `ml_entry` or `ml_entry_eq_struct`. Soak is mechanical (OPERATING-PLAN § 2) |
| C6 | champion vs challenger + cost gate | cost-gated heads; same-replay results this window | **finding** | The cost-gate packets for the advisory heads were in the truncated part of pull #24903; they are re-pulled in #24947. Same-replay comparisons this window: the c4f1 / 98e3 `ml_bakeoff` units used one fold file and cost stack per unit, with the prior as a control. **The ENTRY comparisons that matter (98e3-23/25/26) are on one replay and one cost stack, and none reaches a decision-grade verdict.** Foxhound-1r has no cost-gate packet because it is not a registry head |
| C7 | drift, split | the 3 advisory heads + the nearest shadow | **finding (watch)** | (a) KS, `/api/bot/shadow/drift` (2026-11-11 ~19:05Z): **BTC-15m fc-pcv-v2 (advisory) significant 0.236 / PSI 0.206** (no_change 0.029 last week; score mean 0.976 → 0.936, sd 0.057 → 0.106) · SOL-15m fc-pcv-v2 moderate 0.102 (no_change 0.045) · MES-5m moderate 0.110 (minor 0.095) · fc-pcv-v1 moderate 0.156 (minor 0.079) · yz-v1 moderate 0.182 (3rd moderate read). **Every head moved the same way at once.** That is a common input shift, not a per-head defect (call 5 missed). **Plan-only drift scan** (#24938): Result=success, rc 0, 46 rows, **0 `dispatch` / `skip_no_manifest`, so 0 drifted, 0 persistent, and no `DRIFT-REMEDIATE` row.** The KS moves above are *watch*. (b) Labelled decay: **could_not_look, no instrument** (`LIVE-DECAY-MONITOR` queued 26 d). For ENTRY, 98e3-23 reads DECAY (the last 7 d mean is ≥ 0.10 R below the first 7 d) |
| C8 | concentration | registry; open plan items; this week's ML units | **finding** | `MANIFEST-CONCENTRATION` gbdt 77/106. Open family-tagged items: gbdt 14/24 = 58 % (bar 60 %). **ML bake-off questions: 38/38 regime or direction, the third week at 100 %.** ML-CONSOLIDATION proposes retiring 41 of the 63 D2 regime manifests |
| C9 | research landed + backlog | 447 result records generated since 11-04 20:00Z (307 units); 38 `ml_bakeoff` records (27 units) | **finding** | `ml_bakeoff` verdicts per record: regime 6 pass / 10 fail / 7 indet / 2 n/a; direction 0 pass / 10 fail / 1 indet / 2 n/a. **Order-changing ML work ran outside `ml_bakeoff`:** ENTRY-EQ structure confirm PASS (98e3-06, which put Foxhound-4 live); crypto ENTRY on structure labels FAIL (98e3-22, −0.05 R, n = 212); ML SL revision v2 passed dev (c692-12) and **failed every confirming / held-out read** (c692-13/14/15: +0.0005 R/trade, CI [−0.0007, +0.0018], n = 10,641); MANAGE pooled model FAIL (c692-03); exit head held-out FAIL (e4a1-01); prop ML legs FAIL or INDETERMINATE (fd68-01..06, d256-01/02); ENTRY timeframe levers 5m / 15m / 4h FAIL or INDETERMINATE (b621..b626). Backlog: § 4 |
| C10 | DSR probation | 6 production legs (`dsr_probation.py`) | **could_not_look** for ML | `ml_entry`: dsr `not_computed` · `ml_entry_eq_struct`: `not_computed`, **NO LIVE UNIT** (its forward read 98e3-13 is not linked). Non-ML probation: ada_pullback_2h 0.254, tqqq 0.533, td_sol_prop 0.332, td_xrp_4h 0.023 |

**Iteration census** (`scripts/research/iteration_orphans.py`, 2026-11-11):
- ml_model subjects: 9. Covered 1, **overdue 8**, orphan 0.
- All 8 overdue units (`RQ-20261101-78fc-02..08`) sit in `blocked/`, each on a named work item: `ML-P1-COSTNET-REBUILD` · `ML-VOLGATE-EXITHEAD-REPLAY` · `TMBENCH-QTM1B-BUILD` · `ML-EXIT-ACTIONGRID-LABELS` · `ML-P4-CONVICTION-REGATE` · `ML-REGIME-15M-DRIFT` (×2).
- **Foxhound-4 is not a subject at all, so the census cannot see it** (filed, § 3 P3).

**Weekly progress lines** (row ML-WEEKLY-REVIEW-LINES; the live ENTRY artifact is Foxhound-1r):
1. **Data coverage** per feature family per symbol: **could_not_look**. No instrument reads the live decision log by family.
2. **Feature count in use:** live 20 columns (the v1 recipe, refit) vs 20 admitted (fs01). Not below the admitted count.
3. **Retrain freshness:** `train_end_exclusive` 2026-10-14, **28 days** at 11-11. `data_through` 2026-11-05, 6 days. **AMBER:** the weekly cadence's 8-day bar is met on data-through and missed on training end. It was 408 days RED last week.
4. **Live vs held-out:** 12 closed `ml_entry` trades on `bybit_2` since 11-01.
   - Mean pnl % +0.12. Longs 0 of 3 winners (mean −1.60 %). Shorts 6 of 9 winners (mean +0.70 %).
   - The registered held-out figure is +0.0073 R per decision.
   - The side split matches the replay's SIDE-DRIVER verdict, but n = 12 is no evidence.

## 2 · ANALYSIS

**2.1 The live ENTRY model is pricing market direction, not asset selection (the material finding; real money).**
- **What we know (MEASURED):**
  - Over the replay window the long side loses −0.90 R per decision (n = 51, 8 % winners) and the short side is flat (+0.017, n = 266).
  - Over the clean held-out year, frozen v1's 28-day windows swing from −0.18 to +0.23 R per decision around a mean of +0.0085.
  - A monthly refit does not help (98e3-26: NOT-AGE, NO-LEVER). Neither does a short-only gate (98e3-25: NO-LEVER, window-specific).
- **Competing hypotheses:**
  - (H1) The model's realised edge is the common crypto factor. Its long/short choice is a bet on the market's direction, so its result flips with the tape.
  - (H2) The model has real per-asset skill, and the last fortnight was a bad draw (98e3-23 also reads NOISE-COMPATIBLE).
  - (H3) Serve-time drift: the live feature row differs from training. Not testable, because no ENTRY parity check exists.
- **What discriminates them:**
  - H1 predicts that a **market-residual target** (asset return minus β × BTC) loses the window-to-window swing and keeps any per-asset skill. H2 predicts no change.
  - The year-window sd (0.127) against a mean of 0.0085 is what H1 predicts and H2 explains only as noise.
  - **I have not run that test.** It is proposed as P2, at a powered design (13 paired windows, MDE +0.058 R).
- **Rejected alternatives:**
  - Demoting `ml_entry` on this evidence. The ladder's demotion signal is the mirror's net-of-cost window (OPERATING-PLAN § 2), not an offline replay. P1 asks for that read.
  - Another learner on the same target. fs01 showed the recipe overfits any extra column.

**2.2 The research capacity is still pointed at heads that change nothing.**
- **MEASURED:**
  - 27 ML bake-off units this week. Every one targets a regime or direction label.
  - The regime heads they feed change 2 demo pairs at most (C3).
  - The units are well built: purged folds, the prior as a control, one cost stack each. So their FAILs and PASSes are informative about the regime head.
  - But the business-use map says no answer changes a real-money order.
- **Competing hypotheses:**
  - (i) The iteration loop (programme-review / research-ops) keeps authoring the next lever for every subject that has one, and the regime heads have the most levers.
  - (ii) Order-changing ML questions are blocked on infrastructure (the 8 overdue units all wait on builds), so capacity flows to what can run.
  - Both fit. (ii) is the root: the queue runs what is dispatchable.
- **Rejected alternative:** a rule that refuses regime units. That would be a new gate.
- **The fix proposed is on the supply side:** clear the builds blocking the order-changing units (P5), and accept ML-CONSOLIDATION's retire wave so the regime iteration subjects shrink (P4).

**2.3 Trade-management ML failed its confirming reads.**
- ML SL revision v2 passed its dev stage (c692-12). Three confirming reads then failed: cross-sectional, v1 config, and held-out. The held-out delta is +0.0005 R per trade with CI [−0.0007, +0.0018] over 10,641 trades.
- That is a powered null: the CI is ±0.0013 R, so any effect worth trading would have shown.
- With Q-TM1 and Q-TM1b (last week), MANAGE c692-03 and the exit head e4a1-01, this is the **fifth trade-management ML null on R1-type state features.**
- This closes the tested configurations: BE/BE1/TRAIL/TRAIL15 heads, margin 0.40, the R1 state. It does not close trade management.
- The diagnosis already written into `78fc-04` (the path state is missing) is the right next iteration, and it is blocked on `TMBENCH-QTM1B-BUILD`. **That build is the highest value per cost on the ML board** (P5).

**2.4 Drift: every head moved at once.**
- Five heads on three symbols and two timeframes moved from no_change/minor to moderate/significant in one week.
- The advisory BTC head's mean max-probability fell from 0.976 to 0.936, and its sd nearly doubled. The head is **less sure**, not wrong. Labelled macro-F1 held at 0.582 on 11-11 (registry `runs[]`).
- **Mechanism I believe:** a regime-mix shift in the inputs. The volatile-label share is rising on MES too (C1).
- **Refuting observation:** labelled macro-F1 or recall_volatile on the advisory head falling past its registered tolerance next week.
- First-time drift is *watch* (skill § C7). The trainer's stage-guard independently reads the advisory BTC-15m head as a **demote**. Under the refine-not-abandon rule that becomes a soft-off proposal plus a `[refinement]` row, not a demotion by this lane (§ 3 P8).

**2.5 Frontier (F1–F4)** — full triage in `docs/research/frontier-scan-2026-11-11.md`.
- **F1:** last scan's two keeps (taker-flow and LambdaRank ENTRY variants) were never registered.
- **F2:** gbdt 77/106 manifests. 14/24 open items (58 %, 2 points under the bar). Question concentration 100 % (C8).
- **F3:** 4 of 4 required rows checked. Lab releases are secondary-only, for the 2nd week. No TSFM released in November 2026 was found.
- **F4:** `FRONTIER-LEVER-TABULAR` and `-HARNESS-COSTS` are in their 4th scan queued, `-LEADLAG` its 4th, `-TSFM-TIMESTRAL` its 3rd. Raised again with a recommendation each (§ 4).
- **Kept 1 of 7 (proposed, not queued):** **K1, the market-residual target for ENTRY** (2611.13572's factor-conditioning argument plus 98e3-23's SIDE-DRIVER).
- **Dropped:** MC-JEPA encoder (compute) · TabFM / EXAONE-Tabular (compute, `license:other`) · Granite ensemble-r1 quantiles for the TP head (leakage: released 10-27, so 15 days of clean bars; re-open 2027-02-01) · a short-only gate (already answered) · more regime/direction learners (business, 3rd week) · FINCOSMOS desk evaluation (business).
- **M41 (local LLM) answered: kill as scoped.** It fails compute on both VMs and has no consumer. The pipeline item is closed `killed` and the milestone records the re-entry test.

**Surprises:**
- (a) A real-money model (Foxhound-4) is invisible to the iteration census. Its forward read exists but carries no `iteration:` block.
- (b) The performance route silently ignores `since=`, so every window but lifetime reads the same.
- (c) 7 of 12 real-money `ml_entry` closes carry closeReason `other`, the same as last week.

## 3 · Decisions — proposals (none queued; each labelled)

Ranked by money × decision impact ÷ cost. Each has `p` and a pre-registered check in the review JSON `calls[]`.

| # | track | proposal | why now | cost to a verdict | rejected alternative |
|---|---|---|---|---|---|
| **P1** | **MODEL → Tier-3 read, operator** | **Run the Stage-2 demotion read for `ml_entry` now:** the `bybit_portfolio` mirror's net-of-cost window over the live period, plus a computed DSR for `ml_entry` (C10 reads `not_computed`) | the offline evidence for edge is a t ≈ 0.24 year mean and a −0.13 R replay. The doctrine's demotion signal is the mirror, and nobody has read it | the manager or a Sonnet lane, about $3 | demoting on the replay (wrong signal); waiting for n ≥ 30 live (the live book never establishes edge) |
| **P2** | **MODEL** | **Register K1: market-residual target for ENTRY.** The same v1 recipe on the 24 h net return minus β × BTC (causal rolling β), market-neutral at each timestamp. 13 paired 28-day windows over the clean held-out year; PASS needs ≥ +0.06 R per decision, a CI lower bound > 0, and a shuffled-β placebo that does not pass | it is the one test that separates H1 from H2 in § 2.1, on the real-money model | runner, about $4 | the taker-flow and LambdaRank variants (unregistered for 2 weeks; neither addresses the side effect) |
| **P3** | **MODEL** | **Give Foxhound-4 an iteration subject and an in-hand-data unit:** add `ml-entry-eq-struct` to `iteration_subjects.yaml` and link the forward read `98e3-13` to it. Add a unit that reads in-hand data now (for example a second disjoint pre-2026-10 confirm window), not only after 2027-04-01. **Filed** as `PI-20261111-TX7TX2ZN-0001` (manager) | a real-money model, being widened to 173 ETFs (#24889), sits outside the census with one confirm window behind it | about $2 to author | none: the operating plan requires it |
| **P4** | **MODEL** | **Accept ML-CONSOLIDATION wave 1** (retire 72 rows: 41 D2 regime manifests plus 31 unassigned) and **retire the matching regime iteration subjects by record**, so the loop stops authoring learner arms for heads with no consumer | C8 at 100 % for 3 weeks; 27 units this week fed no order | a Tier-1 PR plus one Tier-2 archive action (#24897 § 52) | a rule refusing regime units (a new gate) |
| **P5** | **MODEL** | **Dispatch `TMBENCH-QTM1B-BUILD` first**, then `ML-EXIT-ACTIONGRID-LABELS`. These unblock `78fc-04` and `78fc-05`, the path-state trade-management iteration on the six money legs | five trade-management nulls on R1 state; the hindsight ceiling is 0.86 R per trade (ML-AM-NEXT-LIVE), so value exists | Sonnet, about $6 | another trade-management variant on the R1 state |
| **P6** | **MODEL** | **Lever rows:** KILL `FRONTIER-LEVER-TABULAR` and `-TSFM-TIMESTRAL`; DISPATCH `-HARNESS-COSTS`; the manager decides `-LEADLAG` | 3–4 scans queued; this week's gates now fail for the newest tabular FMs too | $0 to kill | re-filing them |
| **P7** | **TRADING → `/performance-review`** | `ml_entry` on `bybit_2`: 7 of 12 closes carry closeReason `other` (unchanged from last week's P7), and longs are 0 of 3 | close-reason grading on the real-money ML leg | handed off | — |
| **P8** | **MODEL → Tier-3 (operator)** | **BTC-15m fc-pcv-v2 (advisory) stage-guard demote → soft-off proposal** (advisory → shadow) plus a `[refinement]` row, applying the `drift-remediation` skill. **My recommendation: HOLD advisory one more weekly read.** The drift is first-time, every head moved together (common input shift), labelled macro-F1 held at 0.582, and the head changes at most 2 demo cell pairs | the trainer's stage-guard proposes it, and the refine-not-abandon rule needs a disposition | $0 to decide | an immediate soft-off (it removes the vol axis from 3 `trend_vol` cells on demo, on first-time drift) |

**Stages:** no promote and no demote this week. The one stage signal is the trainer stage-guard's **demote on BTC-15m fc-pcv-v2** (P8). `ready: true` on 5 shadow heads is not a promotion argument, because none of them changes an order (C3).

## 4 · Backlog drain, handoff and not done

**Population:** 16 open ML pipeline items (`origin.ref` names ml-review, `routed_to` starts with `ML`, or `what` starts with `[ml]`/`[refinement]`).
**All 16 triaged; `count_untriaged` = 0.**

| disposition | n | items |
|---|---|---|
| kept open, re-read this run (`work.py observe`, with an observation) | 9 | `3WM5HADW-0004` (max-proba still served: the drift payload's means are about 0.94–0.98) · `DGUBH8UA-0001` (MES still degenerate, 8 cycles) · `DGUBH8UA-0002` (refit served, 23 days train-end to publish, not cleared) · `DGUBH8UA-0003` (no beats-prior clause yet) · `GNVUF1ES-0001` (MES margin void; 0 legs) · `GNVUF1ES-0002` (larger: the money models have no registry cost gate) · `MVBJLVJ3-0001` (0 provenance calls) · `CAZHXZNE-0001` (5 GPU units, none landed through the trainer route) · `MB-…-SHADOW-LOG-HISTORY` (no reader change) |
| kept open, re-read via the trainer | 5 | `3WM5HADW-0005` (yz-v1 now `ready: true`; still needs the code fix) · `UAOAYGBB-0001` (3 enforced skips, 5 stale) · `PROMOREADY-OOSEDGE-OOM` (0 OOM flags; RSS not measured) · `01FXMMUG-0001` (constant by construction, tracked by ML-HYGIENE) · the drift-gate BL (`drift_clean` fails on 8 heads and now drives a demote) |
| kept open, not re-read (needs a trainer measurement this batch did not carry) | 2 | `AHCVAAF5-0002` (calibrators ran twice on 11-11; holdout fields not read) · `SBAQDDVQ-0001` (heavy lock not in this batch) |

**Filed this run:**
- `PI-20261111-TX7TX2ZN-0001`: Foxhound-4 has no iteration subject or live unit.
- `PI-20261111-TX7TX2ZN-0002`: `[refinement]` for the BTC-15m advisory stage-guard demote (P8), with restore / soft-off / retire criteria.
- Closed: `PI-20261022-J9X7ACR3-0001` (M41), `killed` with the scoping verdict.

**Handoff to the manager (not re-filed):**
- the lever rows (P6);
- the 8 overdue ml_model iterations, each blocked on a build (P5 names the order);
- `LIVE-DECAY-MONITOR` (queued 26 d);
- `ML-LEARNING-LEDGER` (queued; C4 is still hand-computed);
- the `/api/bot/performance` `since=` no-op (§ S). This belongs to `/health-review`.

**Not done:**
- practice refresh (sibling lane);
- C7(b) labelled decay (no instrument);
- weekly line 1 (no instrument);
- the MES per-day label-share read (not in this trainer batch; `DGUBH8UA-0001` keeps it);
- a primary-card check of lab releases (secondary only);
- the `REGIME_ML_VERDICT_MODE` env read (diag token rotated 11-11; C3's 2 cell pairs are INFERRED);
- send-ping (the lane reports to the manager).
<!-- ML-FRONTIER-PREP:END -->
