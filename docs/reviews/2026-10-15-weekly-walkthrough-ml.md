# Weekly walk-through brief — ML review + frontier scan (prep, 2026-10-14)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Lane `ML-FRONTIER-PREP-20261014` (Tier 1, docs only). Propose-only: no units queued, no stage changes, nothing past shadow.
> Merged ≠ deployed ≠ observed is stated per line. Every figure names its population. Not run: `stage-guard` / `gate-check` (need the trainer relay — not dispatched this lane), so **no promotion packet exists** and nothing below is a promotion recommendation.

## 1. ML review — model status (observed, live mirror read 2026-10-14 ~18:55Z)

- **Trainer** (`/api/bot/ml/status`, mirror age ~72 s): timer active, last trigger 2026-10-14 00:26Z, next 2026-10-15 00:09Z. Last cycle `complete_with_refusals`, rc 0, 0 failed; 3 manifests refuse (all already tracked: `ML-STAGE-DECISIONS`, `ML-HYGIENE`, `ML-LABEL-WALL`). Disk 42.4% used. Dataset builds 24h: 94 ok / 2 failed (last_overall_rc 1) — family not identified here (`/ml/builds` not read); one transient is a note, a repeat is a row.
- **Registry, 96 models:** advisory 3 · shadow 21 · candidate 71 · research_only 1 (by `target_deployment_stage`). All 3 advisory heads are GBDT volatility-regime heads.
- **Advisory heads, shadow-log counts and drift (KS/PSI, 30d ref vs 7d current window):**

| head | predictions (all-time log) | drift |
|---|---|---|
| btc-regime-15m-lgbm-fc-pcv-v2 | 2,086 | **moderate** (KS 0.183, PSI 0.076) |
| mes-regime-5m-lgbm-v2 | 3,746 | minor (KS 0.063, PSI 0.034) |
| sol-regime-15m-lgbm-fc-pcv-v2 | 2,073 | minor (KS 0.057, PSI 0.005) |

  BTC `moderate` is the one to watch; per `drift-remediation` a single window is not a demotion trigger. Proposal: re-read next week; if `significant` or persistent, open a `[refinement]` row. **No promotion or demotion proposed this week.**
- **Plumbing** (`ml_plan_status.py --plumbing`, exit 0, 50 plan items / 39 open / 15 flagged):
  - `REGISTRY-STAGES-CHANGED`: now shadow 21 / candidate 71 vs plan-expected shadow 25 / candidate 67 → **4 shadow→candidate with no recorded decision found by this lane.** Needs an owner (likely the 2026-09-29 demotions, unverified).
  - `SILENT(UNTRACKED)`: `mes-regime-15m-lgbm-v2` (last seen 2026-10-11T20:46Z) and `mes-regime-1d-lgbm-v2` (last seen 2026-10-14T12:47Z — a daily head, may be normal cadence). Each needs a tracking row or a `plumbing.tracked` entry.
  - Plan hygiene flags: `CLOSED-OPEN` ML-R3, N2, F7, F8, F10, F12 (result landed, plan item still open); `OPEN-DONE` ML-F11, M1–M3; 5 `UNPLANNED` rows. The plan has not caught up with last week's result landings.

## 2. Results read since the 2026-10-11 record (units ran; verdicts from `research/results/*`; research-ops owns grading)

| unit | question (short) | verdict |
|---|---|---|
| 0ac8-01 | trainer runner smoke | pass → ML-RQ-RUNNER trainer path now has a landed record (still verify research-ops listed it before calling it observed) |
| 1414-01 | logit vs LightGBM, 15m regime (BTC/ETH/SOL; n=108,000 OOS rows) | indeterminate (BTC Δmacro-F1 +0.009, CI crosses 0) |
| 1414-02, -03, -04 | logloss vs prior · non-boosted direction · fc_* vs HAR-RV control | indeterminate |
| 1414-05 | MES 1d small-n, ExtraTrees (n=1,764) | **pass** (ET within 0.01 of LightGBM; Δ +0.002, CI spans 0) — "as good as", not "better" |
| 1414-06 | TabICL/TabPFN small-n | indeterminate; **TabPFN arm unavailable (licence acceptance for weights)** |
| 1414-07, 9d20-05 | ExtraTrees/MLP vs LightGBM 15m / 1h | indeterminate |
| 1414-10/11/12 | EIA gas / crude / CPI surprise → returns (macro) | fail (no horizon reached the t-bar) |
| 9d20-01 | peak-to-exit census | pass (pullback giveback 1.54 R/trade; mfe_r is a lagged lower bound) — a census, not edge |
| 9d20-02, -03 | meta-label / giveback predictability within leg (ledger decision-time columns) | fail (AUC CI contains prior on every leg) |

Reading: the family-diversity result so far is **"nothing beats LightGBM, and several things match it"** — mostly *indeterminate*, which is not a FAIL for any family. Two negative information results (macro surprise; ledger-column meta-labels) close only the exact configurations tested.

## 3. Frontier scan (sources checked: HF Hub model/repo details + trending papers via MCP; web search. **Not checked:** GitHub trending, Kaggle, SSRN — gap carried from scan #1.)

**Family diversity** (`--diversity`, registry 96 models): gbdt 75 (78%) manifests / 18 live-shadow / 8 open items. Zero registered models in linear_logit, ts_foundation_model, tabular_foundation_model, rl_bandit, conformal_calibration, ensemble_stack. No `CONCENTRATION` or `FAIL-STREAK` finding; `MANIFEST-CONCENTRATION` reported (not failed). 20 open plan items carry no `family:` tag, so the open-item shares are understated.

**New finding (secondary → primary check):** arXiv 2607.05291 (Brini, Jul 2026; [pdf](https://arxiv.org/pdf/2607.05291)) — 9 zero-shot TSFMs vs 8 econometric specs (HAR family) on 50 assets / 3 horizons: no uniform gain; only the small **Tiny Time Mixers (TTM)** beat Log-HAR at every horizon, narrowly; a TTM+Log-HAR equal-weight average ≈ best single. Read via search summary, **paper body not opened** — treat as unverified until opened. Hub card `ibm-granite/granite-timeseries-ttm-r2`: 805K params, apache-2.0, updated 2025-02 (primary). Same-lane HF check: `amazon/chronos-2` 119.5M, apache-2.0, updated 2026-06-05; `Prior-Labs/tabpfn_3` `license:other` (research-eval only, per skill). A "VolaTTM" Hub model claims HAR-beating RMSE/QLIKE — self-described research experiment, not a backtest; not carried.
Dropped: trending-papers list had nothing finance/time-series relevant.

## 4. Proposals for the walk-through (none queued)

1. **Add TTM (+ a TTM+HAR-RV average arm) to the blocked TSFM bake-off `RQ-20261011-9da8-01`.** Not a new unit: the runner exists (ML-RQ-RUNNER), the HAR-RV control is already the headline, TTM is tiny (CPU-friendly, mirror-publish compatible). Open it only after the paper body confirms the claim. Kill: no arm beats HAR-RV by the registered margin on BTC/ETH/SOL 15m. Info-per-dollar highest of the week.
2. **Unblock the TSFM and tabular units' lever rows or raise them** — `9da8-01..04` are all still `blocked`; per the skill a lever row `queued` after two scans is raised to the manager as the blocker. Specific: TabPFN weights need a one-time licence acceptance (operator licence decision; TabICL/CatBoost arms are unaffected).
3. **Conformal abstention (`9da8-03`) depends on probability quality**; `1414-02` (log-loss vs prior) came back indeterminate, so the prerequisite is not met — re-run with more rows before any conformal work.
4. **Plan housekeeping (Tier 1, next lane):** close the 6 `CLOSED-OPEN` / 4 `OPEN-DONE` plan items with their result locators, add `family:` to the 20 untagged items, give the two `mes-regime-*-v2` silences an owner, explain the 4-stage drift.
5. **Strategy half:** nothing new this week — the strategy-ideas list from scan #1 (`RQ-20261011-9da8-05..07`) is unchanged; no unit read here graded it.

## 5. Limits of this brief
Trainer-side stage-guard/gate-check and the batched trainer diag were not run (no promotion packet). Builds failure family, per-head realized track record (`trades/scores`) and soak parity/label-coverage audit were **not** assessed this lane — the `soak_audit` block is owed to the Sunday `/ml-review`. Merged/deployed/observed: this PR is docs only; nothing was deployed.
