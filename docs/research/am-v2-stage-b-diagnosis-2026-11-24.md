# AM v2 Stage B: why the head-timed actions lose to random timing, and the action-value redesign (2026-11-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PRIMARY (dispatched by Manager Session 2026-11-22a), row `AM-V2-STAGE-B-POLICY-ARM`

**Gates this adds or changes: none.** Research diagnosis and the units it authored. Nothing here touches a bracket, a config or the trade path.
**MEASURED** = computed from a named file or run in this session; **ESTIMATE** = stated as such.

## 1. What failed (MEASURED, `research/results/RQ-20261124-b5a1-0{1..5}/`)
Dev segment, 312,008 replayed trades, net R (HOLD = `replayed_actual`, full cost stack):

| class | policy | mean of 100 random re-timings | HOLD |
|---|---|---|---|
| target | -8,534 | -8,527 | -8,526 |
| tighten | -8,694 | **-7,615** | -8,526 |
| loosen | -8,700 | -8,713 | -8,526 |
| bank | -12,268 | **-5,229** | -8,526 |
| combined | -12,721 | -4,955 | -8,526 |

Every class FAILED R4 (0 of 100 controls beaten). Random tightening and random banking BEAT HOLD. Stage A had passed (all heads beat the state baseline).

## 2. Diagnosis (MEASURED, `scripts/research/am_policy_diag.py` + `am_policy_diag_report.py`)
Population: **4,557 dev trades** (entry 2022-01-01..2025-12-31), up to 120 per shard from 24 of the 363 cf_bulk shards (every 5th shard from offset 1, and every 10th from offsets 3 and 8), crypto legs with Binance Vision bars, the same heads (artifact `am-heads-45384292963`), the same replay and the same policy code as Stage B, 10 controls per trade; plus 24,006 single-action ex-post prices (up to 6 sampled rows per trade, each action placed once at the row's close and never re-placed, minus HOLD). Sample HOLD mean +0.075 R/trade (the sample is not the full book; the deltas, not the level, are what is read).

1. **Any exposure cut pays in this corpus, at any time.** A 50% market close at a uniformly drawn open row: **+0.106 R** mean, positive in **75%** of rows, and FLAT across every head-score and state quintile (0.097-0.112 by P(stop_first), 0.078-0.136 by open_r). Decomposition on a separate 616-trade sample: with funding and slippage zeroed the same action is still **+0.117 R** (positive in 79%), so the effect is the legs' own giveback after the initial move (Stage B dev HOLD giveback mean **1.63 R**), not a cost artefact. This is why random banking and random tightening beat HOLD: they collect structural value with no timing skill at all.
2. **The Stage B rules mapped head probabilities to actions with fixed cuts and never asked what the action is worth.**
   - *Tighten* fired only at P(stop_first) ≥ the fold p90 AND P(dip_recovers) ≤ p50: 3.3% of trades, **100% of fires under water** (mean open_r -0.57 vs -0.12 for random), first move at bar **~38 vs ~17** for random. Per fired trade: policy **-0.042 R** vs random **+0.085 R**.
   - *Bank* placed a resting limit at close + Q50 and re-placed it on every 0.10 R move: **16.9 orders per trade**, chasing price down. Same fill rate as random (36%) but filled at **1.22 R vs 1.48 R**, and **10.6% vs 4.9%** of fills below entry. Per trade: policy +0.014 R vs random +0.049 R.
   - *Loosen* ≈ random (+0.024 vs +0.023 per fired trade): the dip head adds nothing at the p90 cut on this sample.
3. **The value of each action varies strongly, and with the state the heads see.** Single-action means by quintile:
   - breakeven (open_r ≥ 0.25): **+0.148** (lowest open_r quintile) → **-0.004** (highest); by P(stop_first) **-0.014 → +0.169** (4th quintile).
   - bank 50% at +1 R: **+0.087** (lowest P(stop_first)) → **-0.007** (4th); by open_r +0.000 → +0.095.
   - tighten half-way: +0.018 (lowest P(stop_first)) → +0.134 (middle); falls with open_r (+0.141 → +0.038).
   - by family (per-row means differ 2-5x): breakout and scalp gain most from breakeven (+0.19 / +0.21), breakout least from banking (+0.004-0.007).

**Conclusion.** Skill exists (Stage A) and value is learnable (3), but the policy must be chosen on the action's own expected value, and beating R4 means picking better-than-average states, because random timing already earns (1).

## 3. The redesign (units RQ-20261124-c7e3-01..04, rule `RULE-AM-ACTION-VALUE-20261124`, registered before any run)
`scripts/research/am_action_value.py` / `.github/workflows/am-action-value.yml`:
- **label**: every dev trade, up to 8 seeded rows × 8 actions (bank now / at close+Q50 / at +1R / at +2R; tighten half-way / breakeven / lock half the profit; loosen to structure), each replayed alone; label = net R − HOLD net R.
- **fit**: a LightGBM huber regressor per (purged fold, action) on the 9 head features + 6 head outputs + 2 level gaps; the `av_family` class one per (family, action).
- **policy**: act once, at the first row where an action's predicted value clears max(0, that action's training p75), choosing the best such action.
- **control (R4)**: the same action kind placed once at a uniformly drawn eligible row, 100 draws.

| unit | class | what it tests |
|---|---|---|
| c7e3-01 | av_bank | which bank (market / Q50 limit / +1R / +2R) or none, by value (variant b) |
| c7e3-02 | av_tighten | where a tighter stop pays (variant a) |
| c7e3-03 | av_loosen | loosen only where the dip head says recover AND value says pay (variant d) |
| c7e3-04 | av_family | per-family value models over the union menu (variant c) |

Holdout: family AM-HEADS, read 6 times before these (n_tries 7-10). The four units carry `not_before` one hour apart so their result jobs never append `comms/research/holdout_reads.jsonl` at the same time (PI-20261124-RQFAILS-0001).

## 4. What I did not check
- Whether the sampled 24 shards are representative of the 312k-trade book by strategy mix (they are every 5th/10th shard by plan order, not stratified).
- The intrabar convention (stop checked before bank/TP in one bar) is conservative for exposure-reducing actions and identical for policy and control; I did not size its effect.
