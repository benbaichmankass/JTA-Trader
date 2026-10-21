# Weekly walkthrough 2026-10-21 — ML + frontier section

> Lane `ML-FRONTIER-PREP-20261021` (Tier 1, read-only). Reads: `ml_plan_status.py --diversity/--plumbing`,
> live API `/api/bot/ml/{status,registry}` + `shadow/{stats,drift}` (pulled 2026-10-21 ~19:00Z),
> `research/results/`, Hugging Face Hub + web search. **Not run:** the trainer-VM pull
> (`stage-guard`, `gate-check`, `training_cycle.jsonl`) — so no promote/demote verdicts below are gate-checked.
> **No units queued, nothing promoted, no config/src touched.** Merged / deployed / observed are labelled throughout.

## 1. Model status — population: 97 registered models (registry mirror, age 31 s)

| stage | n | note |
|---|---|---|
| advisory | 3 | `btc-regime-15m-lgbm-fc-pcv-v2`, `sol-regime-15m-lgbm-fc-pcv-v2`, `mes-regime-5m-lgbm-v2` |
| shadow | 21 | 24 shadow+advisory heads all emitting; last prediction 16:01–19:03Z today (observed) |
| candidate / research_only | 72 / 1 | offline |

- **Trainer (observed):** timer enabled, last cycle 2026-10-21 08:47Z `overall_rc=0`, `failed=0`, `trained=0`
  (73 already done), outcome `complete_with_refusals` (3 manifests refusing: `baseline-prop-mission-policy`,
  `btc-regime-15m-lgbm-base-vt003-pcv-v1`, `setup-candidates-metalabel-xsym-yz-v1` — each already tracked by a plan row).
  Disk 48.5 % used. Datasets: **120 ok / 0 failed in 24 h** (was 5 failed on 10-18).
- **Merged ≠ observed:** #18891 (Bybit 10016 retry + no truncated shards) is **merged**. One clean build cycle
  is **observed** (0 failed). That it fixed the *shards* (whole, ~5 yr of bars) is **not observed** —
  needs the trainer-VM row count (PI-20261018-WH81NW96-0001) and `labels_accruing` on the 1h heads (-0002).
- **Drift (KS/PSI, 14 d vs 30 d window; shadow log):** advisory heads are `minor` (BTC 15m fc-pcv-v2 ks 0.075,
  SOL 15m ks 0.079, MES 5m ks 0.086). `significant` only on baselines/constant-ish scorers
  (`btc-regime-15m-baseline-v1`, `mes-regime-{15m,5m}-baseline-v1`, `mes-regime-1d-lgbm-v2` psi 0.94, `setup-quality-baseline-v0`).
  `moderate` on BTC/ETH 1h and 5m LGBM heads. `execution-quality-baseline-v0` scores `constant` (known, tracked).
- **Advisory watch — MES (PI-20261004-AHCVAAF5-0001, last checked 10-11, overdue):** `mes-regime-5m-lgbm-v2`
  macro_f1 0.7128 vs `mes-regime-5m-baseline-v1` 0.6702 → margin **4.26 pts** on n_eval 9,353 (latest run
  20261021T015100Z). One reading, between the 4.0 (refine) and 5.0 (clear) thresholds → **kept open**; re-date it.
- **Promotion/demotion:** none proposed. No gate packet read this run, and last week's packets were `ready: false`
  for every head. The nearest candidates remain `btc-regime-15m-lgbm-yz-v1` / `-fc` (PI-…-0003) — re-check needs a trainer
  `gate-check` ~20 h after a cycle (today's cycle was 00:39Z).

## 2. Results read since 2026-10-18 (population per unit)

| unit | family | verdict | population | reading |
|---|---|---|---|---|
| RQ-20261016-65ff-25 | conformal_calibration | **FAIL** | 3 groups (BTC/ETH/SOL 1h), n 72,000 OOS | gain/validity fails on ETH 1h and SOL 1h. Closes *this* config (LGBM, Mondrian by predicted class, 1h) only. |
| RQ-20261018-ff8f-01 | gbdt (yz vs fc) | INDETERMINATE | BTC+SOL, n 72,000 | yz-vs-fc deltas straddle zero (BTC cv CIs include 0). |
| RQ-20261018-ff8f-02 | tabular_foundation_model | INDETERMINATE | BTC/ETH/SOL 15m, n 21,600 | TabICL ≈ LightGBM (BTC +0.0001, ETH −0.0005 macro_f1, CIs span 0). **TabPFN arm `error`**: CPU refuses >5,000 samples. |
| RQ-20261018-ff8f-03 | linear_logit | **FAIL** | 3 groups 1h, n 72,000 | calibrated logit worse than LightGBM by 0.043 log-loss (BTC 1h cv, CI −0.058..−0.028, sign-consistent). |

These four sit in the checker as `CLOSED-OPEN` (ML-F3P, F19, F20, F21): rows still `open` though their
units are `done`. Their `families.<family>.history` entries are not yet written. → handoff, §5.

## 3. Diversity — `ml_plan_status.py --diversity` (population: 97 models; 54 of 76 plan items open)

- `MANIFEST-CONCENTRATION` (reported, not failed): **gbdt 76 / 97 = 78 %** registered models. Unchanged vs 10-11 (75/96).
- No `CONCENTRATION` / `FAIL-STREAK` flag; checker exit 1 is that reported-not-failed line. 3 open items lack a `family:` tag (ML-N1, ML-V1, ML-D3).
- Untested/zero-model families: linear_logit, ts_foundation_model, tabular_foundation_model, rl_bandit, conformal_calibration, ensemble_stack
  (0 models, none live). Graded history: linear_logit FAIL,FAIL,PASS,IND,IND (+ff8f-03 FAIL pending write); conformal IND,PASS (+65ff-25 FAIL pending);
  ts/tabular FM: INDETERMINATE only. **Two weeks in, every non-gbdt family is still at "indeterminate or fail" and none has an eval arm
  that has produced a decisive positive** — the bottleneck is instruments (TSFM backends, TabPFN CPU limit, torch GRU kind), not ideas.
- `--plumbing`: exit 0; 4 `CLOSED-OPEN`; `TRAINING-STALENESS stale 5 / never_trained 2 of 73 scanned`; remaining SILENT/CONSTANT notes all carry an owning row.

## 4. Frontier scan (this lane: partial, ~3 sources — HF trending, HF search, 2 web searches)

Step 0: last scan's units read above (65ff-25 FAIL, ff8f-01/02 IND, ff8f-03 FAIL; ff8f-04 GRU still blocked on `FRONTIER-LEVER-SEQUENCE-LEARNER`; 9da8-01 TSFM bake-off still blocked on `FRONTIER-LEVER-TSFM` — third scan with the lever unbuilt, so per the skill this is **raised to the manager as the blocker**, not re-filed).

| candidate | family | evidence | licence | gate | proposal (not queued) |
|---|---|---|---|---|---|
| `mistralai/Timestral-209M` | ts_foundation_model | HF Hub model page: 209.3 M params, task time-series-forecasting, updated 2026-10-15, 257 likes, 5.5 K downloads (**primary**) | Hub tag `license:other` — terms **not read** | licence unresolved; offline eval only until read; serve = operator decision | Add as a learner arm to the *existing* `RQ-20261011-9da8-01` bake-off once `FRONTIER-LEVER-TSFM` lands (no new unit). Baseline: incumbent fc + HAR-RV; kill: no lift on any symbol vs HAR-RV on identical folds. |
| TabICLv2 | tabular_foundation_model | arXiv 2602.11139, Feb 2026 (via alphaxiv — **secondary**) | not verified | none known | ff8f-02 already ran `tabicl`; trainer venv recorded `tabicl 2.2.0` on 10-18 — **unverified** whether that is v2. Check before reading ff8f-02 as a TabICLv2 result. |
| TabPFN-3 (May 2026) | tabular_foundation_model | one secondary source (Qlik blog / wiki); not confirmed | restrictive (secondary) | licence + token not stored; CPU limit | Tier-2: set `TABPFN_ALLOW_CPU_LARGE_DATASET=1` (or equivalent) on the trainer so the control arm evaluates, then re-queue ff8f-02's variant as one extension unit. Research-only; never serves. |

Dropped, with reason: "TimesFM Sept/June 2026" claims (aitoolly.com aggregator, dates conflict, no primary — rumour per the skill); the Qlik list of other 2026 tabular models (LimiX, Mitra-v2…) — single secondary source, not triaged. Trending HF list otherwise LLM/image only. No strategy-frontier ideas this run (none, because: no pass on the strategy half was scoped for this lane).

## 5. Proposals and handoff for the manager (nothing queued)

1. **Book-keeping (Tier 1, ml-review writeback):** close ML-F3P/F19/F20/F21 with the verdicts above and write `families.*.history`
   (conformal FAIL: 65ff-25 config only; linear_logit FAIL: ff8f-03, 1h BTC/ETH/SOL, calibrated multinomial logit only; tabular FM IND; gbdt IND).
2. **Blocker to raise:** `FRONTIER-LEVER-TSFM` (and `FRONTIER-LEVER-SEQUENCE-LEARNER`) have gated their units across ≥2 scans — dispatch or kill; 9da8-01 and ff8f-04 cannot move without them.
3. **Tier-2 ask:** TabPFN CPU-large-dataset env on the trainer (control arm currently `error`), plus the token owed under ML-TABPFN-LICENCE.
4. **Due, trainer-VM relay needed:** shard whole-ness + 1h `labels_accruing` (PI-…-0001/-0002) now that #18891 is merged and a clean build cycle ran; `gate-check` re-run for the yz/fc 15m heads ~20 h post-cycle; MES advisory margin re-date.
5. **Decision still open:** PI-20261018-WH81NW96-0004 (`PROMOREADY_OOS_EDGE` flip, Tier-2) was due 2026-10-21 and is unanswered.

Honesty notes: no trainer-relay pull this run; drift windows come from the live mirror, not from `gate-check`; no figure here is net-of-cost edge — all are classifier metrics (macro_f1 / log-loss) on regime labels.
