# ml_entry: the next lever is a new information class, not a new learner (plan, 2026-11-27)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · written 2026-11-27 by ML-PRIMARY for Manager 26a (14:53Z ask) · drives the units named in § 4

**Gates this adds or changes:** none.

## 1. Why now

The decomposition c4e2-01 found that served v1 lost money after 2026-11-01. Population: 867 decisions, mean −0.085 R. Longs lost −0.46 R and shorts made +0.21 R, while on the model's own dev folds both sides sat near zero.

Every retrain-side lever on the registered recipe has since been read on the same 8 dev folds, net of the full cost stack:

| Lever | Units | Verdict |
|---|---|---|
| Recency weights and rolling windows | c4e2-02 | INDETERMINATE: no arm beats base |
| Bigger learners | c4e2-03 | FAIL: they overfit |
| Tabular foundation model | 7ab1-02 | FAIL |
| Recurrent net | 9e73-01/-02, 2819-01 | FAIL |

So the recipe is at its ceiling on the 20 features it can see. The operator's order is "get it working". What remains is to give the model information it does not have.

## 2. What the data already says (re-read, not re-run)

Two independent results point the same way.

**fs01-01 (2026-11-01, dev folds, 60 perps).** The ablation added each feature family to the 20 baseline features and compared it with the bare baseline. It also ran a control that adds 9 pure-noise columns (N9), and that control alone costs −0.0167 R per decision.

| Family | Columns | Δ vs baseline | Δ vs N9 noise control |
|---|---|---|---|
| F2 funding / basis | 8 | +0.0008 | **+0.0175** |
| F5 shape / calendar | 11 | +0.0035 | **+0.0202** |
| F1 taker flow | 8 | −0.0034 | +0.0133 |
| F3 positioning (OI, long/short) | 10 | −0.0291 | −0.0124 |
| F4 cross-section | 9 | −0.0570 | −0.0403 |

**c4e2-04 (2026-11-27, frozen Chronos encoder, PCA 8).** The arm was +0.0097 R vs base (t 1.27) and +0.013 vs its matched noise placebo (t 1.66).

Read together: the recipe pays a fixed cost for every extra column. That cost hides information that may be real, so comparing with the bare baseline under-reads it.

**The vs-N9 column is post hoc.** fs01-01's registered rule compared each family with the baseline, and five families were read. These numbers motivate a test; they are not evidence for promotion. The test has to be registered fresh with the matched-size placebo as its control and a multiplicity-adjusted bar.

## 3. Candidate input classes, scored

All candidates use the same universe, decision grid, labels, cost stack and dev folds as c692-01 / c4e2. Every one is compared with a matched-size noise placebo.

| # | Class | Data: point-in-time, no lookahead | Expected value | Compute | Verdict |
|---|---|---|---|---|---|
| 1 | **Compact derivatives state.** F2 funding/basis reduced to 4 columns (premium z, funding z, premium-minus-funding, hours to funding) and F5 shape reduced to 4 (semivariance ratio, efficiency ratio, since-high, since-low). Plus one combined arm. | In hand: Binance Vision `fundingRate`, `premiumIndex` 1h klines and 12-column klines. These are built by `vision_streams.py` → `ml_entry_v2.py build-table`; the leakage self-test refuses forward-shifted columns. Coverage 2020+ on the frozen 60 perps. | Highest. Two independent near-misses share one mechanism, and a compact form attacks the column cost directly. Upper bound from §2: about +0.01 to +0.02 R per decision. | CPU. fs01 arms took 5–8 min each on 4 cores; 3 arms plus 3 placebos plus A/A2 is about 1 h. It needs internet to fetch Binance Vision, so github runner or trainer. | **Author now** |
| 2 | **Crypto implied volatility.** Deribit DVOL for BTC and ETH, hourly, market-wide: level, 24h change, z-score over 168h. | Public, printed in real time (the index has no revision). History via Deribit `get_volatility_index_data` from 2021-03, so dev coverage 2022+ is above 90%. Joined at the last print at or before the bar close. | Medium. It addresses the "market shift the model cannot see" diagnosis directly: an implied-vol regime the realised features lag. Risk: F8 (cross-asset equities, market-wide) failed at −0.072, so market-wide joins have a poor record here. | CPU, light (two series). Needs internet. | **Author second** (a new fetcher, about 60 lines, plus a family builder) |
| 3 | Order-book depth (`bookDepth` ±1–5% depth imbalance) | Binance Vision from 2023-01 only, so about 55% dev coverage. That clears the 40% rule but loses the 2022 folds. | Medium-low. It is a micro signal on a 1h, 24h-horizon decision. | Heavy: about 0.56 MB/day/symbol is roughly 33 GB for 60 symbols, runner-only. | **Defer.** Re-entry: if #1 PASSes and the 6-symbol traded slice is the binding population, test depth on those 6 only. |
| — | Liquidations / forced flow | No free point-in-time archive (Binance discontinued `liquidationSnapshot`; a third-party vendor would be paid and not point-in-time). | — | — | Not available; not authored |
| — | Positioning (F3) and cross-section (F4) | In hand | Negative even against the noise control | — | Not re-tested in this plan |

## 4. Units (registered before any run; dev folds only; the held-out window from 2025-10-01 is not read)

1. **Unit A: compact derivatives state vs matched placebo** (class 1).
   - Arms: `F2c` (4 columns), `F5c` (4 columns) and `F2c+F5c` (8 columns). Each arm has a seeded N(0,1) placebo of the same width.
   - Rule: an arm PASSES iff its delta vs its matched placebo ≥ +0.010 R per decision, positive in ≥ 6 of 8 folds, the one-sided t on the 8 per-fold deltas ≥ 3.1215 (Šidák, k = 3, one-sided 0.025: the house level), and it is net positive in ≥ 3 of 4 calendar years. It FAILS only when the upper bound (mean + 3.1215 × se) is below +0.010; otherwise it is INDETERMINATE.
   - Power, stated honestly: per-fold deltas in fs01-01 spread about 0.02–0.05 R, so a true +0.010 effect passes only about 3–12% of the time. The likely outcome for a real effect of that size is INDETERMINATE, not PASS.
   - Pass → ONE confirming read on the out-of-time window (2025-10-01 onward, `holdout_lock` claimed, deflated bar) in its own unit. That read decides.
   - Fail → compact derivatives state is closed for crypto ENTRY on `research/levers/ml-entry.yaml`.
2. **Unit B: implied-vol regime vs matched placebo** (class 2). One arm (3 columns) against a 3-column placebo, with the same rule at k = 1: t ≥ 2.3646 (one-sided 0.025, df 7), FAIL only when mean + 2.3646 × se < +0.010. A true +0.010 effect passes about 7–23% of the time. Authored after Unit A's builder lands, since it shares the harness change.

Neither unit promotes anything. A confirmed pass becomes the next `ml_entry_retrain` challenger through a data-backed Tier-3 packet applied by the manager.
