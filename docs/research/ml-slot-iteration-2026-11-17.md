# ML slot iteration table, D1–D10 (2026-11-17)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `ML-ITERATION-REFILL-20261117` (Manager Session 2026-11-15a dispatch, operator-ordered); measured 2026-11-17

**Gates this adds or changes: none.** This lists units, rows and pipeline items. Each owns its own rule.

## Why this exists

At 09:00Z the operator found the research dispatcher had fired nothing since 00:24Z. **MEASURED** (dry run of `scripts/research/dispatch_queue.py --json` at 2026-11-17, over all 2,262 unit files): `would_dispatch 0`, `not_due 2262`. Of those, 1,906 were done, 71 retired and 15 blocked; every other file was a recurring unit not yet due or a once-unit that had already run. `check_research_queue_health.py`: H1-REFILL runnable 14 < 25, and H2 last dispatch 9.1 h ago.

The cause: floor-driven generation was stopped (STOP-GENERATED-AUTHORING, 2026-11-01), and nothing replaced it with diagnosis-driven ML iteration authoring between the weekly programme reviews. This lane authored six units. The standing fix is filed as `PI-20261117-ZFRREVN5-0004`.

After this PR, the same dry run reads **`would_dispatch 5` + 1 GPU deferred locally**: c21d-01, -02, -04 and -06 go to `github_runner` (cpu_long), c21d-03 goes to `kaggle_cpu` (auto, published data), and c21d-05 goes to the Kaggle GPU (`compute: gpu`; the local dry run reads `deferred` only because it is not given the quota file).

## Method (and what was not done)

- **Source of each slot's state:** the MECE map ([`docs/plans/ML-ROADMAP-MECE-2026-11.md`](../plans/ML-ROADMAP-MECE-2026-11.md) § 2–3), plus the last row of `research/results/<unit>/*.jsonl` for every recent ML unit (verdict, n, note, read here), plus `scripts/research/iteration_orphans.py --json`. On 2026-11-17 that tool reported 13 ML subjects: 7 covered, 3 overdue, 3 orphan.
- **No floor-filler.** A slot gets a new unit only when a graded result names an untested lever and an existing harness can run it now. Otherwise the slot's block is filed as a row or a PIPELINE item.
- **Not done:** no VM reads (live baselines are as recorded in the MECE map § 1.2 and `config/`, not re-measured); no unit was run locally; per-backend 2–3-day saturation was **not** reached (see "Backend coverage").

## Slot table

| slot | family | live baseline / challenger | latest graded (verdict, why) | open units (due / not_before) | NEXT step (this lane) |
|---|---|---|---|---|---|
| **D1** Universe & book | none, on purpose (a rule: the promotion ladder) | rule | — | — | **Kept as a rule** (map § 3 D1): no learned leg-selector at ~51 legs. Re-entry test: ≥ 30 legs with Stage-0 records on one cost basis, producer row `ML-LINE-S1-CORPUS` (state `landed_unproven`). No unit: a scoping unit would be floor-filler until that panel exists. |
| **D2** Regime gate | Collie | 3 advisory vol heads (BTC trend_vol off-cells, bybit_1 only); challenger `btc-regime-1h-lgbm-yz-v1` | `RQ-20261112-ef4c-02` **PASS**: yz beats v2 ≥ +0.002 nats, BTC 1h. `ef4c-01` BTC 15m **INDET**. `bcd2-01` **FAIL**: BTC cells on SOL TD lost 11.69 R. `b819-01` **FAIL** by money. | `RQ-20261103-b3c9-19` weekly monitor (recurring). `RQ-20261112-0f87-01` blocked on `ML-VOL-LABEL-LIVE-VERIFY`. | **NEW `RQ-20261117-c21d-03`**: does the yz challenger beat v2 on ETH 1h AND SOL 1h? It has been read on one symbol only, and the population rule needs pooled evidence. PASS → the money consumer test with yz-labelled cells. Due now; Kaggle CPU. **NEW `RQ-20261117-c21d-05`**: powered follow-up of the ML-F29 GRU pilot (the only non-GBDT family tried on D2, never given a verdict). GRU vs the yz LightGBM on BTC, ETH and SOL 1h log-loss. Kaggle GPU. |
| **D3** Entry generation | Foxhound | **Foxhound-1** real money (tau 0.10); Foxhound-2 demo | `2e3b-01` **FAIL**: −0.068 R/decision at per-symbol cost (n 12,746, 51 symbols). `a474-04` **FAIL**. `7e18-02` gross-decomposed arm **INDET** (+0.0097, CI ±0.038). `4654-07` ensemble **INDET**. **`4654-02` PASS on dev: tau 0.30 WON, +0.0366 R over base, 6/8 folds. Its held-out read was never authored.** | `RQ-20261108-98e3-13` (not_before 2027-04-01). `RQ-20260930-602` (not_before 2026-12-23). `fs06-01` and `15c9-01` blocked. | **NEW `RQ-20261117-c21d-01`**: the same frozen boosters at tau 0.30, on the held-out year at per-symbol cost, graded on the deflated ledger bar. PASS → data-backed Tier-3 challenger proposal (tau 0.10 → 0.30). Due now; runner. **Foxhound-4 (equity, live):** `207f-02` FAIL (tau is not the lever) and `207f-03` FAIL with diagnostic *ranks cost per R* (IC vs cost −0.527) → **NEW `c21d-06`** (cost-neutral target / direction head). `98e3-15` INCONCLUSIVE (Alpaca bars throttle, row RUNNER-ALPACA-BARS-THROTTLE). |
| **D4** Signal filter | Beagle | **Beagle-1** (`overlay_td.json`, reduce ×0.5, TD family) live; challenger EV-threshold (`ml/overlay/challengers/overlay_td_ev.json`, shadow-logged by `src/runtime/overlay_shadow.py`, log-only) | `cc86-01` challenger vs live **NOT A WIN** (paired +0.0241, LB95 +0.0053, deflated −0.0002; n 1,587). `5785-05` diagnosis: the reduce halves trades averaging +0.21 R vs +0.31 R take-all. Pre-2020-07 TD windows are read 3× (M13). | `cc86-02` forward read, **live** and session-local by design (deployed via #26513 per ML-PRIMARY-4; read once at n = 60 disagreement packages, ~2.5 years). `0f87-02` blocked on `ML-SLOT-BASELINES-DECLARE`. `78fc-02` blocked on `ML-P1-COSTNET-REBUILD`. | **No new unit this PR.** Do NOT author another historical holdout read on Beagle-1. A faster D4 lever needs a challenger that disagrees with Beagle-1 more often (different features or a net-R target, not a threshold). Harness ready: `ml_overlay_noninferior --holdout-challenger / --export-challenger / --holdout-market spot`. Owner: ML lane (row `ML-DEV-PLAN`). *(Correction: an earlier draft filed cc86-02 as undispatchable. Wrong premise; `PI-20261117-ZFRREVN5-0002` killed.)* |
| **D5** Position aggregation | Mastiff (restated) | rule: slices / election (`allocator_ev.py` + `slice_allocation.yaml`) | `82fd-02` census **PASS**: material concurrency on the bybit_2+portfolio pairs. **`a474-02` FAIL**: no rule arm beats A0 in both windows. | none | **Closed by its registered fail mapping**: rule-exhausted until a roster change adds a leg on a census pair. Re-entry is tracked as **`PI-20261117-ZFRREVN5-0001`**. Any unit before then is floor-filler. |
| **D6** Bracket at entry | Pointer (restated) | none at any stage; ml_entry fixed SL 2 / TP 3 ATR | Pointer v0 `82fd-01` **FAIL** and defect re-run `a474-01` **FAIL** (moves ~11.5k trades for delta ≈ 0). `089f-03` bracket-by-cell **FAIL** (+0.0094 vs bar +0.03). `c692-02`: learned bracket +0.0143 = best static [2, 4] +0.0144. | `78fc-01` (ml-brackets, **overdue**) blocked on the `brackets-forward` subcommand (`ML-DECISION-MODELS`) | **NEW `RQ-20261117-c21d-02` (baseline unit)**: the static TP 4 ATR (the dev-chosen best static) on the same frozen held-out decisions at per-symbol cost. It sets the bar any Pointer must beat; PASS → Tier-3 TP proposal. Due now; runner. |
| **D7** In-trade management | Labrador | **Labrador-1b** (TP extend-only, ml_entry) live | `383f-01` **PASS** forward (+0.0081 R, n 868). `c692-15` ML SL revision **FAIL** (+0.0005). tm-action-value iterations 1–5 **all FAIL** S-OFFLINE at every_bar (7e18-01: +0.0033, CI [−0.007, +0.013]). Stage A on corpus_v2 (`3144-02`) **PASS** for close and partial. | `0f87-03` Labrador-1b re-validation blocked on accrual (≥ 300 closed live trades after 2026-11-12) | **NEW `RQ-20261117-c21d-04`** (shared with D8): the untested **check-in cadence** family (every_4+triggers, triggers_only), one factor vs 7e18-01. Clears the orphan `ml-tm-action-value`. Due now; runner. |
| **D8** Exit now | Labrador (separate head) | exit head closes 1 demo leg (trend_donchian_eth) | `1ae8-01` exit-now v0 **INDET** (delta −0.0017 / −0.0038, CI ±0.015). `a474-03` pooled 4h exit head **FAIL**. `d5a7-06/-07` volcomp **FAIL**. | none | Covered by **c21d-04** (the `close` action is D8). Orphan `ml-exit-head-donchian-1h` is **named, not authored**: features, universe and pooling are tested, label and learner are not, so it needs the programme review's lever-coverage call. Filed as **`PI-20261117-ZFRREVN5-0003`**. |
| **D9** Execution | Whippet | baseline only (Mutt-Execution-1a, shadow) | `1c4e-01` maker ENTRY **FAIL**: −0.0041 R/decision, CI [−0.0087, +0.0002], n 9,210. Diagnosis: a directional pick runs away from a resting limit. | none | **Blocked on a build**: maker EXIT on the 24 h time-stop (non-directional, so no run-away selection). Filed as checklist row **`ML-D9-MAKER-EXIT-HARNESS`** (Tier 1). Value is bounded by the cost stack (map § 3 D9). |
| **D10** Review & grading | Basset | none; Claude grades and forecast-grade are tools, not models | `089f-01` CJ-4 blind-grade validation **FAIL**: rho **−0.1834**, wider CI [−0.258, −0.101], n 707. The grade is *anti*-correlated with net R. | none | **Blocked on a build**: the D10 join and CUSUM baseline harness (the map marks it "(build)"), plus an orientation audit of the negative rho. Filed as checklist row **`ML-D10-BASSET-BASELINE`**. |

## Units added by this PR

| id | slot | question (short) | harness | backend | registered rule |
|---|---|---|---|---|---|
| `RQ-20261117-c21d-01` | D3 | frozen Foxhound-1 at tau 0.30, held-out year, per-symbol cost | `ml_entry_population_test.py run --tau 0.30` | github_runner, cpu_long, 6 GB, ~60 min | PASS iff pooled mean ≥ deflated ledger bar; 2e3b-01 floors |
| `RQ-20261117-c21d-02` | D6 | static TP 4 ATR on the same frozen decisions, held-out, per-symbol cost | `ml_entry_population_test.py run --tp-atr 4.0` | github_runner, cpu_long, 6 GB, ~60 min | same |
| `RQ-20261117-c21d-03` | D2 | yz challenger vs v2 on ETH 1h + SOL 1h | `ml_bakeoff.py` (unit-driven) | kaggle_cpu (published `metis-market-data`), 3 GB, ~30 min | PASS iff ≥ +0.002 nats on both |
| `RQ-20261117-c21d-04` | D7/D8 | tm-action-value at check-in cadences every_4+triggers / triggers_only | `tm_bench.py score --checkins …` | github_runner, cpu_long, 12 GB, ~90 min | S-OFFLINE (7e18-01's rule, one factor changed) |
| `RQ-20261117-c21d-05` | D2 | GRU vs yz LightGBM regime head on BTC/ETH/SOL 1h (diversity challenger) | `ml_bakeoff.py` (unit-driven, `torch_gru`, device auto) | **Kaggle GPU** (published data), 5 GB, ~90 min (estimate) | PASS iff ≥ +0.002 nats on ETH and SOL and ≥ 0 on BTC |
| `RQ-20261117-c21d-06` | D3 (Foxhound-4) | ATR-neutral net-R target (A1) and gross-R direction head minus known cost (A2) vs the live net-R recipe at tau 0.25, count-matched (from the graded 207f-03 diagnostic: the model ranks cost per R) | `alpaca_live_book.py foxhound --section neutral` (new section, self-tested) | github_runner, cpu_long, 6 GB, ~240 min | PASS iff an arm ≥ baseline + 0.03 R, t ≥ bar_for(2), ≥ 3/5 folds |

**Harness change (Tier 1, research only):** `scripts/research/ml_entry_population_test.py` gains `--tau`, `--tp-atr` and `--rule-id`. Defaults reproduce 2e3b-01 exactly, and `self-test` passes.

The read is now claimed under the **calling** unit. Before this change it was claimed under the hard-coded 2e3b-01 id, which would have mis-attributed the ledger line.

The claim is also now made against an **out-dir copy** of the holdout ledger (the `ml_decision_manage.claim_read` pattern). This is the `PI-20261115-PWMQY8LM-0001` fix for this script: a runner read claimed in the repo ledger never landed. **The grading lane must append each unit's `holdout_reads.jsonl` line to `comms/research/holdout_reads.jsonl`.**

c21d-01 and c21d-02 both read the ENTRY held-out window. Whichever lands second must be graded on the n_tries that includes the first.

**Power, stated honestly:** the router labels all four `accruing` ("declared data-acquisition"). For c21d-01, the expected n of about 3,500 sits below the router floor of 3,974 at the declared MDE of 0.04 R. A FAIL there is informative; a near-miss is underpowered by construction (no more data exists for that window).

## Backend coverage (honest)

- **github_runner:** 4 units, ~7.5 runner-hours. **kaggle_cpu:** 1 unit, ~0.5 h. **Kaggle GPU:** 1 unit, ~1.5 h (estimate). That became possible once `ml_bakeoff`'s `torch_gru` gained cuda→cpu device selection in this PR (row `ML-BAKEOFF-TORCH-DEVICE`; the device is logged and recorded as `measurement.torch_devices`). **trainer:** **no new work.**
- **The target was not met:** "every backend has 2–3 days of work" would have needed units with no diagnosis behind them, and the operator ruled those out ("we shouldn't just fill the queue with things that are useless"). The real fix for supply is `PI-20261117-ZFRREVN5-0004`: an owner who authors from each graded result within 24 h. On today's pass rate, that is what keeps the runners fed.

## Filed, so no block is silent

| ref | kind | what |
|---|---|---|
| `ML-D9-MAKER-EXIT-HARNESS` | checklist row (work store) | D9 maker-exit replay harness |
| `ML-D10-BASSET-BASELINE` | checklist row (work store) | D10 join + CUSUM baseline + rho-orientation audit |
| `PI-20261117-ZFRREVN5-0001` | pipeline | D5 re-entry trigger (roster change on a census pair) |
| `PI-20261117-ZFRREVN5-0002` | pipeline | **killed** (wrong premise: cc86-02 is session-local by design and live) |
| `PI-20261117-ZFRREVN5-0003` | pipeline | orphans ml-exit-head-donchian-1h and ml-btc-router-cells, with reasons |
| `PI-20261117-ZFRREVN5-0004` | pipeline | root cause: no owner for diagnosis-driven ML authoring |
| existing | rows | `ML-DECISION-MODELS` (D6 brackets-forward), `ML-VOL-LABEL-LIVE-VERIFY` (D2), `ML-SLOT-BASELINES-DECLARE` (D4), `ML-P1-COSTNET-REBUILD` (D4), `ML-EXIT-ACTIONGRID-LABELS` (D7 holdbias), `ML-LINE-S1-CORPUS` (D1) |
