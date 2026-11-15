# Frontier scan — 2026-11-12 surge pass 1 (lane FRONTIER-RESEARCH)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Gates this adds or changes:** none.

Lane FRONTIER-RESEARCH is a standing surge lane of Manager Session 2026-11-11a, reporting to AM-ML. The operator asked for it at 13:46Z: *"We
need to make sure we have frontier research running as well (at least for the surge I want another lane just working on frontier research,
create a seperate sub-que so I can watch and add/edit it"*. This pass follows
[`.claude/skills/frontier-research/SKILL.md`](../../.claude/skills/frontier-research/SKILL.md). It builds on the weekly scan from the day before,
[`frontier-scan-2026-11-11.md`](frontier-scan-2026-11-11.md), and does not repeat it. The machine record is
`comms/ml-plan/20261112T1700Z-FRONTIER-SURGE.json` § `frontier`.

## 1. The sub-queue

Every idea is an item in the work store with an id starting `FRONTIER-Q-`, owned by "lane FRONTIER-RESEARCH (AM-ML)" (`GET /api/bot/work/items`).
The structured fields sit in `extra.frontier`: state, family, source, why, consumer, baseline, est_cost, next_step, unit and p_pass. The store's
own `state` maps idea/triaged → `queued`, authored/running → `in_flight`, graded → `done`, dropped → `dropped`, and sequenced-behind-another-unit → `blocked`.

The table below was read 2026-11-12 ~16:45Z (MEASURED).

| item | frontier state | consumer / slot | disposition |
|---|---|---|---|
| `FRONTIER-Q-RESID-ENTRY` | authored | D3 `ml_entry` (bybit_2 real money, mirror, 3 prop) | unit **RQ-20261112-4654-01** registered on PR #25344 (self-land); not run yet |
| `FRONTIER-Q-RESID-ENTRY-EQ` | idea | `ml_entry_eq_struct` on alpaca_live | waits on the crypto verdict |
| `FRONTIER-Q-SIGNATURE-INTRADE` | triaged (store: blocked) | ml-tm-action-value → `live_review_apply.py` on the six money legs | sequenced behind RQ-20261112-3144-02 (see § 3) |
| `FRONTIER-Q-LEADLAG` | triaged | none named | the existing lever row; recommend park (4 scans, no consumer) — manager decides |
| `FRONTIER-Q-METALABEL-SIZE` | dropped | D3 sizing | power, and already covered (§ 3) |
| `FRONTIER-Q-TSFM-GRANITE-TP` | dropped | D7 | leakage/power: a clean post-release holdout is weeks long; re-open 2027-02-01 |
| `FRONTIER-Q-FUNDING-XSEC` | dropped | — | already the `funding-carry` subject (RQ-20261101-d1f3-07 PASS); the new datapoint is secondary and null |

## 2. Sources checked (F3)

| source | state | what was read |
|---|---|---|
| Hugging Face Hub | checked | `hf://papers/daily/latest` (2026-11-12; no finance or time-series papers that day); paper searches for "crypto perpetual futures prediction", "trade exit optimal stopping learning" and "cross-sectional return prediction market factor residual". New relevant items: KiT (arXiv 2609.34507, a financial TSFM built on diffusion transformers, 2026-09-28; title and summary only); CryptoGAT (2606.27670, "are time-series models effective for crypto forecasting?"; title only); 2512.12924 (walk-forward validation framework; title only) |
| arXiv | checked via HF | the above, and 2611.13572 re-read for K1 (PRIMARY, abstract and introduction) |
| Lab releases | checked, secondary | web search: no TSFM release in November 2026. The latest are Timestral (2026-10-15), Granite PatchTST-FM-r2 (2026-09-09) and TimesFM-3 (2026-08-31) |
| Quant practitioner literature | checked, thin | web search on 2026 cross-sectional funding / open-interest predictability. No 2026 arXiv primary found. One secondary page (bryanvine.github.io/alpha-research/paper2) reports pooled funding rank-IC −0.005 (t −0.89) and carry decaying in 2026 — **not carried** as a finding |
| GitHub, competitions | could-not-look this pass | time-boxed out; both are every-other-week rows and were checked 2026-11-04 |
| Practice & methodology refresh | not run this pass | it is the weekly lane's job (Wed); the surge lane does not duplicate it |

## 3. Triage notes (gates 5–6)

- **RESID-ENTRY (K1).** This passes all six gates, as triaged on 2026-11-11. The registered design follows the 98e3-26 design: 13 × 28-day windows, paired.
  The baseline is the raw-target refit at the same origins, so refit cadence is not confounded. The placebo permutes the BTC forward return across
  timestamps. Power (QUOTED from the 11-11 scan): window sd 0.074 R gives an MDE ≈ 0.063 R. The result re-measures the sd. p_pass 0.15.
- **SIGNATURE-INTRADE.** The consumer is TM-BENCH / `ml-tm-action-value`, the subject the audit calls "five negatives on one state representation".
  It is **not** D7: D7 TP-revision already PASSED (RQ-20261101-383f-01). Since 11-11 the subject ran iteration 1 (path-state block, 78fc-04, FAIL)
  and iteration 2 (12-bar horizon label, 3144-01, FAIL). Its registered FAIL branch says iteration 3 widens the **training population** (corpus v2,
  RQ-20261112-3144-02, blocked on `TMBENCH-V2-TRAIN-INPUT`) *before any further state or label change*. A path-signature state is a state change,
  so it is the iteration-4 candidate, filed now and authored only if 3144-02 FAILs. The build is small: a `signature` block in
  `tm_bench.add_feature_block`, with time-augmented fav/adv/c_r truncated at depth 3, reusing the truncation-causality self-test and the leaky
  positive control. Coordinate with lane ML-AM-NEXT-LIVE, which owns the subject.
- **METALABEL-SIZE: dropped on gate 6.** Per-trade sd is 1.09 R (audit § 0.4). Concentrating the 907 held-out decisions into a top half
  (n ≈ 450) gives se ≈ 0.051 R, so the 80 %-power MDE is ≈ 0.14 R. The top half would need ≈ +0.18 R against the pooled +0.037 R. The
  `ml_decision_entry` tau sweep (TAU_GRID 0–0.30, chosen on dev folds) already asks "trade only the high-confidence decisions". Re-open if
  RESID-ENTRY passes, or on a pooled population of at least ~3,000 decisions.

## 4. Grades of prior calls (Layer 0)

The 11-11 scan's K1 keep call is **unresolved**: the unit is registered and not yet run. Its six dropped calls have no new contrary evidence,
so they stay **unresolved**.

## 5. Next pass

Grade RQ-20261112-4654-01 when it lands. Watch 3144-02 for the SIGNATURE trigger. Check GitHub and competitions. Apply operator edits from the
manager within the hour.
