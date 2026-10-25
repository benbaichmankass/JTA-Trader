# Weekly walkthrough 2026-10-21 — ML + frontier section

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

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

---

# PERFORMANCE — grading and numbers only

> **Not run:** `/perf-followup` (it happens after the walk-through). **Not done:** per-decision A–F grading, M13 insights cross-check, backlog drain, paper-book tracker append, real-money allocation benchmark. This is the numbers half only.

## 0. How to read this

- **Merged ≠ deployed ≠ observed.** Every performance figure is **OBSERVED** on the live read-only API/diag on 2026-10-21 (~17:00Z). The TP-doctrine table is **OBSERVED on repo config at `main` `591ed14a`** (merged state), not a live-VM read. Nothing in this PR changes code or config.
- **Classes are never pooled across real-money and paper.** `real_money` = `bybit_2` + `alpaca_live`. `mirror` = `bybit_portfolio` + `alpaca_portfolio`. `paper` = everything else (incl. prop-named legs run on paper accounts; the prop accounts themselves have no closed rows in these pulls). **R / giveback come from the journal `account_class`, which files the mirrors under `paper`, so every R / giveback figure is `paper+mirror` pooled.** $ figures are shown split.
- **Provenance:** $ split MEASURED vs not-measured (ESTIMATED + UNVERIFIED + null) from `pnlProvenance` on `/api/bot/trades/closed`. **R is ESTIMATED**: realised R is telemetry `open_r` on a `final` row, else `pnl ÷ (risk_per_unit × size)`; **peak R is an ESTIMATED lower bound on MFE for 100% of rows**, so true giveback is ≥ the figures here.
- **Pulls:** `GET /api/diag/position_telemetry?limit=5000`; `GET /api/diag/journal?table=trades` (3 pages × 1000, back to 2026-07-20); `GET /api/bot/trades/closed?since=2026-09-14&include_paper=true` (594 rows); `scripts/research/giveback_census.py` on those dumps (trade rows filtered to each window by `closed_at`); `python3 scripts/ci/check_tp_doctrine.py`; `python3 scripts/research/live_vs_backtest.py`.
- **Cross-check:** the journal-side closed rows (428 in W30) equal the API-side closed rows (428 in W30) — same population on both reads.

## 1. Populations

| window | definition | closed trades |
|---|---|--:|
| **W30** (primary) | `closed_at` ≥ 2026-09-21 | real_money **23** · mirror **29** · paper **376** (total 428) |
| **W7** (since last prep brief, 2026-10-14) | `closed_at` ≥ 2026-10-14 | real_money **3** · mirror **6** · paper **46** (total 55) |
| **90-day** (giveback only) | `closed_at` ≥ 2026-07-23; telemetry only exists from 2026-08-17 | R-graded: paper+mirror 328 · real_money 11 |

**R-graded coverage is a minority of closes:** W30 paper+mirror **131 of 405** (32%), real_money **5 of 23**; W7 paper+mirror 15 of 52, real_money 2 of 3. Telemetry rows with no matching closed trade in window (open or older) are excluded by design (a partial peak is not an MFE). **R and giveback speak for the joined minority; $ speaks for all closes.**

## 2. Net P&L per capital-day — the headline

`$/day` = Σ net pnl ÷ Σ hold-days (size-**unweighted**). `bps/notional-day` = Σ pnl ÷ Σ(|qty × entry| × hold-days). `R/cap-day` = Σ realised R ÷ Σ hold-days over R-graded rows. **No account balances are stated (public repo); $ is absolute P&L only.**

### Class level

| window | class | n | net P&L $ | measured-only $ | not-measured $ | **$/day** | bps/notional-day | R-graded n | **R / cap-day** |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| W30 | real_money | 23 | −48 | −47 (20 of 23 measured) | −1 | **−1.21** | −138 | 5 | **−0.073** |
| W30 | mirror | 29 | −14,875 | −12,252 | −2,623 | −72.7 | −27 | (in paper+mirror) | (in paper+mirror) |
| W30 | paper (non-mirror) | 376 | −58,057 | −15,780 | −42,276 | −157.1 | −63 | (in paper+mirror) | (in paper+mirror) |
| W30 | paper+mirror (R basis) | 405 | −72,931 | −28,032 | −44,899 | −127.0 | −50 | 131 | **+0.061** |
| W7 | real_money | 3 | −9.5 | −9.5 | 0 | **−3.43** | −279 | 2 | **−0.386** |
| W7 | mirror | 6 | −1,483 | −1,483 | 0 | −12.7 | −5 | — | — |
| W7 | paper (non-mirror) | 46 | −48,122 | −7,431 | −40,691 | −274.7 | −109 | — | — |
| W7 | paper+mirror (R basis) | 52 | −49,605 | −8,914 | −40,691 | −169.9 | −69 | 15 | **+0.029** |
| 90-day | real_money | — | — | — | — | — | — | 11 | **+0.010** |
| 90-day | paper+mirror | — | — | — | — | — | — | 328 | **+0.094** |

⚠️ **Paper $ is not a decision number.** One leg (`ict_scalp_mgc_15m` on `ib_paper`) carries **−40,668 of −72,931 (56%)** in W30 and **−40,668 of −49,605 (82%)** in W7; both losses (trades 6610 and 6603, 2026-10-14) are **ESTIMATED**, from 96 and 150 micro-contracts per ticket (§6-1). Read the R column and measured-only $, not the headline.
⚠️ **Real_money R-graded n = 5 (W30) / 2 (W7) — `insufficient_n`** (`--min-n 10`); the sign is a description, not a verdict. Real-money $ is ~USD 50 over 23 trades, so $/day is dominated by sizing, not by edge.
⚠️ **R/cap-day on short holds is inflated** by tiny Σhold-days (e.g. `trend_donchian_sol_prop` reads −33.1 on one 1-hour trade). Compare within a hold-length class, never across.

### Per strategy (paper+mirror pooled per strategy; real_money listed separately)

Shown: |$| ≥ 1,000, every real_money leg, and n ≥ 10. Sorted by |$|. `R-n` < 10 is `insufficient_n` — listed, not graded.

**W30 (closed_at ≥ 2026-09-21)**

| class | strategy | n | net $ | not-measured $ | $/day | R-n | ΣR | **R/cap-day** | giveback R / share | read |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| paper+mirror | ict_scalp_mgc_15m | 9 | −40,668 | −40,668 | −6,927 | 8 | −4.2 | −0.72 | 1.27 / 172% | insufficient_n |
| paper+mirror | ict_scalp_avax_5m | 19 | +9,550 | +1,189 | +7,760 | 19 | +7.3 | **+5.94** | 0.68 / 64% | measured |
| paper+mirror | trend_donchian_eth_4h | 8 | −5,977 | +985 | −473 | 4 | −1.9 | −0.30 | 1.61 / 142% | insufficient_n |
| paper+mirror | ict_scalp_sol_5m | 9 | −5,264 | −3,072 | −2,476 | 8 | −2.4 | −1.01 | 1.05 / 140% | insufficient_n |
| paper+mirror | xrp_pullback_2h | 14 | −4,933 | −848 | −158 | 7 | +3.6 | +0.14 | 0.87 / 63% | insufficient_n |
| paper+mirror | ada_pullback_2h | 18 | −4,469 | −2,310 | −281 | 9 | +1.9 | +0.43 | 1.15 / 84% | insufficient_n |
| paper+mirror | gdx_pullback_1d | 2 | −4,052 | 0 | −78 | 1 | −0.7 | −0.03 | 1.16 / 235% | insufficient_n |
| paper+mirror | trend_donchian_eth_prop | 4 | −3,399 | 0 | −4,331 | 4 | −2.4 | −3.00 | 1.05 / 227% | insufficient_n |
| paper+mirror | slv_pullback_1d | 2 | −3,021 | 0 | −137 | 1 | −0.3 | −0.03 | 0.74 / 165% | insufficient_n |
| paper+mirror | ict_scalp_sol_15m | 6 | −3,002 | +1,255 | −1,651 | 6 | −2.9 | −1.58 | 1.16 / 170% | insufficient_n |
| paper+mirror | tlt_pullback_1d | 2 | +2,597 | 0 | +36 | 2 | +3.8 | +0.05 | 1.44 / 43% | insufficient_n |
| paper+mirror | trend_donchian_sol | 5 | −2,353 | −566 | −818 | 5 | −1.6 | −0.55 | 1.49 / 127% | insufficient_n |
| paper+mirror | ict_scalp_eth_15m | 9 | −2,327 | +569 | −411 | 9 | +1.3 | +0.22 | 0.61 / 81% | insufficient_n |
| paper+mirror | ict_scalp_xrp_5m | 8 | −2,150 | +534 | −4,892 | 8 | +1.9 | +4.21 | 0.75 / 76% | insufficient_n |
| paper+mirror | ict_scalp_xrp_15m | 8 | −1,994 | −156 | −552 | 7 | −1.0 | −0.28 | 0.81 / 121% | insufficient_n |
| paper+mirror | trend_donchian_sol_prop | 2 | −1,932 | 0 | −36,231 | 1 | −0.3 | −33.13 | 0.52 / 254% | insufficient_n (1-hour hold) |
| paper+mirror | eth_pullback_2h | 3 | +1,424 | −240 | +492 | 3 | +2.4 | +0.82 | 0.96 / 55% | insufficient_n |
| paper+mirror | trend_donchian_xrp_4h | 2 | −1,389 | −1,389 | −1,137 | 1 | −1.0 | −1.62 | 1.49 / 299% | insufficient_n |
| paper+mirror | tqqq_trend_long_1d | 1 | −1,066 | 0 | −88 | 1 | −1.0 | −0.08 | 1.53 / 285% | insufficient_n |
| paper+mirror | pairs_sol_eth_a / _b | 53 / 53 | +90 / −42 | +42 / −87 | +8.6 / −4.0 | — | — | — | — | no telemetry R |
| paper+mirror | pairs_bnb_btc_a / _b | 68 / 68 | −38 / +34 | −32 / +26 | −4.2 / +3.8 | — | — | — | — | no telemetry R |
| real_money | ada_pullback_2h | 9 | −15 | 0 | −2.1 | 1 | −1.0 | −1.22 | 1.19 / 515% | insufficient_n |
| real_money | xrp_pullback_2h | 5 | −11 | −4 | −2.1 | 1 | −0.8 | −0.37 | 2.14 / 156% | insufficient_n |
| real_money | trend_donchian_eth_4h | 4 | −8 | +2 | −1.2 | 0 | — | — | — | no R |
| real_money | iaum_pullback_1d | 1 | −4 | 0 | −0.9 | 1 | −0.5 | −0.10 | 0.52 / 1300% | insufficient_n |
| real_money | slv_pullback_1d | 1 | −4 | 0 | −0.4 | 0 | — | — | — | no R |
| real_money | trend_donchian_xrp_4h | 1 | −3 | 0 | −5.3 | 0 | — | — | — | no R |
| real_money | trend_donchian_sol_prop | 1 | −3 | 0 | −64.7 | 1 | −0.1 | −1.22 | 0.56 / 110% | insufficient_n (1-hour hold) |
| real_money | tlt_pullback_1h | 1 | +1 | +1 | +0.1 | 1 | +1.4 | +0.34 | 0.68 / 33% | insufficient_n |

**W7 (closed_at ≥ 2026-10-14)** — every row is `insufficient_n`; listed for movement only.

| class | strategy | n | net $ | $/day | R-n | ΣR | R/cap-day |
|---|---|--:|--:|--:|--:|--:|--:|
| paper+mirror | ict_scalp_mgc_15m | 2 | −40,668 | −134,939 | 1 | −0.5 | −1.81 |
| paper+mirror | trend_donchian_eth_prop | 4 | −3,399 | −4,331 | 4 | −2.4 | −3.00 |
| paper+mirror | trend_donchian_eth_4h | 2 | −2,944 | −2,376 | 1 | −0.9 | −1.49 |
| paper+mirror | xrp_pullback_2h | 4 | −2,819 | −125 | 3 | +3.0 | +0.15 |
| paper+mirror | tlt_pullback_1d | 2 | +2,597 | +36 | 2 | +3.8 | +0.05 |
| paper+mirror | trend_donchian_sol_prop | 2 | −1,932 | −36,231 | 1 | −0.3 | −33.13 |
| paper+mirror | tqqq_trend_long_1d | 1 | −1,066 | −88 | 1 | −1.0 | −0.08 |
| paper+mirror | pairs_bnb_btc_a / _b | 10 / 10 | −22 / +31 | −18.7 / +25.9 | — | — | — |
| paper+mirror | pairs_sol_eth_a / _b | 6 / 6 | +22 / −23 | +23.8 / −24.6 | — | — | — |
| real_money | xrp_pullback_2h | 1 | −3.4 | −1.7 | 1 | −0.8 | −0.37 |
| real_money | trend_donchian_eth_4h | 1 | −3.2 | −5.1 | 0 | — | — |
| real_money | trend_donchian_sol_prop | 1 | −2.8 | −64.7 | 1 | −0.1 | −1.22 |

Other legs (|$| < 1,000, ≤ 9 trades) are omitted; the generating script was run in a scratch directory and is not committed.

### Live-vs-backtest (skill Step 0) — whole-history live R per book, NOT windowed

`python3 scripts/research/live_vs_backtest.py` (bootstrap of each leg's committed Stage-0 per-trade net R; p5–p95; i.i.d.). Population: every closed trade with an R basis on each book, **all history**, so n differs from the windows above. Real-money rows:

| leg | n | live ΣR | backtest band p5 … p95 | verdict |
|---|--:|--:|---|---|
| bybit_2 `xrp_pullback_2h` | 17 | **−9.92** | −7.83 … +13.18 (live at pct 2.2) | **BELOW_BACKTEST** (backtest fidelity: faithful) |
| bybit_2 `ada_pullback_2h` | 15 | **−6.91** | −5.93 … +20.26 (pct 3.3) | **BELOW_BACKTEST** (faithful) |
| bybit_2 `trend_donchian_eth_4h` | 14 | +8.36 | −7.25 … +19.47 (pct 67.6) | CONSISTENT |
| bybit_2 `trend_donchian_xrp_4h` | 7 | −0.94 | −4.25 … +7.33 (pct 29.0) | CONSISTENT |
| bybit_2 `trend_donchian_sol_prop` | 1 | −0.90 | — | INSUFFICIENT_N |
| alpaca_live `ief_/slv_/iaum_pullback_1d` | 1 each | −0.48 / −1.03 / −1.47 | — | INSUFFICIENT_N (slv and iaum: live trade worse than every backtest trade) |

The mirror books read `CONSISTENT` for the same legs (`xrp_pullback_2h` −6.21R, pct 7.5; `ada_pullback_2h` −4.13R, pct 10.9). Per the skill, `BELOW_BACKTEST` means a **fidelity/regime investigation unit** — not a demote.

## 3. Giveback — peak R vs realised R (`position_telemetry` joined to closed trades)

Giveback = peak_r − realised_r. Share = Σ giveback ÷ Σ peak. **Peak is an ESTIMATED lower bound** for 100% of rows, so true giveback is ≥ these. Share > 100% means the average trade peaked and then closed below entry. <!-- population-ok: the population (R-graded closed trades per class and window) is given in the table directly below -->

| class | window | R-graded n | mean giveback R | share of peak | deep (peak ≥ 1R) → closed ≤ 0 |
|---|---|--:|--:|--:|--:|
| paper+mirror | W30 | 131 | 0.99 | **85.5%** | 15.3% of 59 |
| paper+mirror | W7 | 15 | 1.09 | 73.0% | 16.7% of 6 |
| paper+mirror | 90-day | 328 | 0.99 | **87.3%** | 14.1% of 149 |
| real_money | W30 | 5 | 1.02 | 120.8% | 50% of 2 |
| real_money | W7 | 2 | 1.35 | 143.8% | 1 of 1 |
| real_money | 90-day | 11 | 0.96 | 97.9% | 33% of 3 |

Reading: on the paper+mirror book, trades keep roughly **13–15% of their peak R** (90-day, n=328; stable vs the 10-14 brief's 85%/89%). Per-leg W30, only one leg reaches R-n ≥ 10: `ict_scalp_avax_5m` (n=19, 0.68R, 64% share). Among the thinner legs the largest givebacks are `ict_scalp_mgc_15m` (1.27R / 172%, n=8) and `trend_donchian_eth_4h` (1.61R / 142%, n=4). Real-money numbers are n=5 / 11 — descriptive only. The share is effectively unchanged week over week, so this is a structural property of the exit path, not a bad-week effect.

## 4. TP-rule compliance — `python3 scripts/ci/check_tp_doctrine.py` (re-run 2026-10-21, `main` `591ed14a`)

Population: **54 routings / 26 distinct legs**, every account in `config/accounts.yaml`. OBSERVED on repo config (merged state), not a live-VM read. Exit code 0 (the guard is a ratchet over a 54-line baseline).

| class | routings | entry_tp FAIL | tp_revision FAIL | compliant |
|---|--:|--:|--:|--:|
| real_money | 8 | 5 | 7 | **0** |
| prop | 6 | **6** | 6 | **0** |
| mirror | 7 | 4 | 6 | **0** |
| paper | 33 | 21 | 32 | **0** |
| **all** | **54** | **36** | **51** | **0** |

(`all` is the sum of the four class rows; the guard prints per-class lines only.) Versus the 10-14 brief (50 routings; real_money 7 / prop 6 / mirror 6 / paper 31; prop entry_tp FAIL 0): **+4 routings** (+1 real_money, +1 mirror, +2 paper) and **prop entry_tp FAIL moved 0 → 6**. The moved cell is not a roster change: all six prop routings (`trend_donchian_eth_prop` / `trend_donchian_sol_prop` on `breakout_2`, `tradeify_1`, `velotrade_1`) now read `entry_tp: unreachable` with a declared `tp_r: 6` and a measured reach of **0.9% (eth) / 1.9% (sol)** — i.e. the guard's new TP-REACH-FLOOR (10%) check, which prints `below_floor=10 · reachable=9 · unmeasured=9` over 28 declared-target routings. Real-money entry_tp failures: `alpaca_live` `iaum_pullback_1d`, `ief_pullback_1d`, `slv_pullback_1d` (sentinel `tp_r: 50`), `bybit_2` `trend_donchian_eth_4h` (sentinel), and `bybit_2` `trend_donchian_sol_prop` (unreachable). Zero of 54 routings are compliant.

## 5. Gaps in this brief (said plainly)

- **Not graded:** per-decision A–F, M13 insights, backlog drain, paper-book tracker append, real-money allocation benchmark, `trade_quality_review.py` (prop) — outside "grading and numbers only". The prop accounts have no closed rows in these pulls.
- **Mirror and paper share R:** the journal `account_class` is `paper` for mirrors, so R and giveback are `paper+mirror`; the $ tables split them. I did not recompute R by account.
- **Pairs legs** carry $ but no telemetry R.
- **Telemetry coverage** is 32% of W30 closes; `giveback_census.py` excluded 491 telemetry rows (open or no closed match) in W30. Giveback is a view of the joined minority.
- **`--since-days` is ignored on the JSON-dump path** of `giveback_census.py` (it printed identical n for 7/30/90 until I filtered the trade dump by `closed_at` myself); the windows above are my filter. Filed in §7.
- Journal `pnl` fee / funding treatment was not independently verified this session.

## 6. Anomalies observed (said, not fixed — no src/config edits in this lane)

1. **`ict_scalp_mgc_15m` (`ib_paper`) paper $ is mis-sized or mis-valued — still open from 10-14.** Trades 6610 (96 contracts, entry 4173.8 → exit 4150.5) and 6603 (150 contracts, 4182.4 → 4170.2) post −22,368 and −18,300, both ESTIMATED, against a realised R of only −0.53 on the one R-graded trade. **Seven earlier closed MGC trades (6450, 6389, 6345, 6170, 6058, 6022, 5995) carry `realizedPnl = 0.0` with `pnlProvenance: unverified` and real entry/exit prices** — a `0` that means "we could not value it", the collapsed-state pattern. 
2. **Trade 6131 (`spy_pullback_1h`) has `closed_at` stored as the epoch-millisecond string `1790835474843`** (= 2026-10-01T06:17Z) while the other 1,544 non-null `closed_at` values are ISO strings. A lexical date filter silently drops it; I normalised it before windowing. One row of 3,000 pulled.
3. **`journalTrust` for the bybit_2 `trend_donchian_sol_prop` close (trade 6692) reads `known_divergent`**, and its mirror (6693, `bybit_portfolio`) reads `no_record`. I did not resolve what divergence it records; the figures above use the API `realizedPnl` as stored.

## 7. Candidate follow-ups (for the walk-through; NOT run — items 1, 4 and 8 are filed in the pipeline)

1. **Two real-money legs are `BELOW_BACKTEST` (Step 0):** `bybit_2` `xrp_pullback_2h` (n=17, −9.92R, pct 2.2) and `ada_pullback_2h` (n=15, −6.91R, pct 3.3). Per the skill, this is a fidelity/regime investigation unit, **not a demote**: attribute regime / cost / execution / overfit first. Highest-priority follow-up in this brief. **Filed:** `PI-20261021-4ZLRFEV1-0001` (related open item `PI-20261021-LRP-8CA903B8`, an `ada_pullback_2h` candle-mismatch finding on the same real-money leg).
2. **Giveback is the dominant leak on paper+mirror and is stable:** ~85–87% of peak R given back in W30 and 90-day; ~14–15% of ≥1R trades close ≤ 0. Input for exit-refinement / Programme 01 levers (the census unit `RQ-20261014-9807-01` has three landed result files on `main`; not read this session beyond that fact).
3. **TP doctrine: 0/54 compliant.** Real-money-first: the 5 real-money entry_tp failures, then the 6 prop `unreachable` TPs (declared `tp_r: 6`, measured reach 0.9–1.9%).
4. **`ict_scalp_mgc_15m` valuation/sizing check (§6-1)** before any `ib_paper` $ is used to grade IB legs; the seven `unverified` zeros should be backfilled or marked, not left at `0`. **Filed:** `PI-20261021-4ZLRFEV1-0002`.
5. **Negative-R measured scalps:** `ict_scalp_sol_5m` (−1.01 R/cap-day, R-n=8), `ict_scalp_sol_15m` (−1.58, n=6), `ict_scalp_mgc_15m` (−0.72, n=8) — all `insufficient_n`; diagnose before any demote.
6. **Positive-R legs to understand, not promote:** `ict_scalp_avax_5m` (R-n=19, +5.94 R/cap-day, 64% giveback share, the only measured positive leg), `ict_scalp_xrp_5m` (+4.21, n=8). Paper only.
7. **Real-money is n ≤ 5 per leg in W30** — no leg is gradeable in-window; the question is accrual, not a verdict.
8. **Tooling:** `giveback_census.py` ignores `--since-days` on the JSON-dump path (§5); epoch-ms `closed_at` on trade 6131 (§6-2). Both are small Tier-1 follow-ups. **Filed:** `PI-20261021-4ZLRFEV1-0003`.
