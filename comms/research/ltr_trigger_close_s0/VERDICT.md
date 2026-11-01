# LTR-TRIGGER-CLOSE-S0 — verdict (2026-11-01)

Rule registered before the run: [`PREREGISTRATION.md`](PREREGISTRATION.md) (`ca6f91af2`). Machine record: [`verdict.json`](verdict.json).
Per-package rows: [`packages.jsonl`](packages.jsonl). Harness: `scripts/research/ltr_trigger_close_s0.py`.

Gates this adds or changes: none.

## Population
- 1,103 closed crypto trades of rostered legs; one per package gives **880 packages**. **552 priced**, from 2026-05-26 to 2026-11-01.
  - Excluded 328: geometry or times missing 177, realised net R uncomputable 77, no closed bar before the close 74.
- Accounts: bybit_1 511, bybit_2 36, bybit_portfolio 5.
- Timeframes: 5m 214, 15m 103, 1h 55, 2h 107, 4h 73.
- Unconditional figures:
  - Mean HOLD is **−0.152 R per package**.
  - Closing at a uniformly random bar instead adds **+0.131 R**, CI95 [−0.014, +0.274], which includes 0.

## Results
ΔT is close-at-first-T minus the realised hold. "Edge" is ΔT minus a random-time close in the same trade. All figures are in R, net of the cost stack. CIs marked "Bonf." are 99.5%.

| trigger | n pkgs | ΔT vs hold | Bonf. CI ΔT | random vs hold | edge vs random | Bonf. CI edge | clauses held | verdict |
|---|---|---|---|---|---|---|---|---|
| adverse_r −0.5 | 281 | −0.026 | [−0.356, +0.285] | +0.381 | **−0.407** | [−0.535, −0.298] | P1 | **FAIL** |
| adverse_r −0.75 | 163 | −0.065 | [−0.561, +0.405] | +0.494 | **−0.558** | [−0.763, −0.385] | P1 | **FAIL** |
| giveback | 81 | +0.119 | [−0.712, +0.997] | +0.063 | +0.056 | [−0.203, +0.317] | P1 | INDETERMINATE |
| new_peak | 280 | +0.057 | [−0.294, +0.420] | −0.154 | +0.211 | [+0.095, +0.321] | P1 P3 | INDETERMINATE |
| r_milestone | 172 | +0.115 | [−0.384, +0.679] | −0.425 | +0.540 | [+0.365, +0.706] | P1 P3 P5 | INDETERMINATE |
| near_target | 126 | +0.291 | [−0.274, +0.943] | −0.459 | +0.750 | [+0.521, +0.956] | P1 P3 P5 | INDETERMINATE |
| swing | 145 | +0.097 | [−0.351, +0.588] | −0.089 | +0.186 | [−0.099, +0.453] | P1 | INDETERMINATE |
| **stall** | 152 | **+0.359** | **[+0.028, +0.733]** | +0.455 | −0.096 | [−0.254, +0.038] | P1 P2 P4 P5 | INDETERMINATE (P3) |
| momentum_flip | 295 | +0.086 | [−0.210, +0.382] | +0.289 | −0.203 | [−0.327, −0.074] | P1 P5 | INDETERMINATE |
| structure_break | 332 | +0.097 | [−0.149, +0.358] | +0.357 | −0.259 | [−0.361, −0.172] | P1 P5 | INDETERMINATE |

**No trigger passes, so there is no mechanical close rule to take to the operator.**

## What it says
1. **The live week does not generalise.** On the live review record, holds lost −0.60 R to closing at the review. Over six
   months of the same legs, closing at the first adverse_r −0.5 crossing is **−0.03 R vs hold** (n=281), and it is **0.41 R
   worse than closing at a random time** in the same trade. The adverse triggers pick bad moments to close: the drop tends to
   revert. That supports reading (b) of the LTR-CLASS-GRADE verdict: the live hold result was one week (W44), not a property
   of the triggers. **Do not mechanise or brief "close on adverse".**
2. **stall is the one trigger that beats hold** (+0.36 R, Bonferroni CI > 0). It is positive in all 5 months with ≥5
   packages, but the effect is decaying: June +0.60, July +1.22, Aug +0.13, Sep +0.01, Oct +0.04. It **does not beat a random-time
   close** (edge −0.10). What it carries is "these trades bleed with time", not anything about the stall moment. That makes it a
   time-stop / max-hold question for the exit-refinement pipeline, not a live-review trigger.
3. **The profit-side triggers** (r_milestone, near_target, new_peak) beat a random close only because a random close cuts
   winners. None of them beats hold. Banking at +1 R or near the target is not supported net of cost (ΔT CIs straddle 0).
4. **The trigger events, with the reviewer removed, do not carry the close-at-review edge.** Every trigger fails P3 or P2.
   The live close result (+0.79 R/package on 4 packages) is not explained by the triggers either. It stays INDETERMINATE.

## Stated biases
- Spot candles (binance.vision) are priced against perp fills. The basis hits the trigger and random arms equally, so P3 is
  robust to it and P2 is not fully robust.
- Triggers are evaluated on bar closes, while live evaluation uses telemetry passes.
- The close arm pays policy slippage again on exit, which is conservative against closing.
- Real money is n=41 of 552 packages; the result is mostly bybit_1.
- Equity and futures legs are out of scope.

## Next iteration (rows)
- **LTR-STALL-TIMESTOP-S0**: per-leg max-hold time stop vs hold vs random, in the exit-refinement harness, with a
  pre-registered rule and month folds. It should explain the Aug–Oct decay.
- **LTR-HOLD-BIAS-BRIEF** (amended): the brief must NOT push close-on-adverse. This record says adverse closes are worse
  than random.
