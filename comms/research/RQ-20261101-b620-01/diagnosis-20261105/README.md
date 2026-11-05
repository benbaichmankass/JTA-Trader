# b620-01 DOES_NOT_REPRODUCE: diagnosis (lane ML-FS-RECIPE, 2026-11-05) -- CORRECTED

Dev folds only; no sealed window read. The registered rule and tolerance of b620-01 are NOT changed.

## CORRECTION (same day)
The first version of this file (commit 946d2ed79) said the timeframe harness was not at fault and that the input data had moved since round 1.
BOTH WERE WRONG. (a) It compared per-symbol builders on 6 symbols and the full-60 `E.build_table` against `T.build_table`, both on UNMASKED bars,
so they agreed with each other and with neither round 1. (b) `head_scan_last_modified.py.txt` shows the archive did not move: all 3,729 dev-window
monthly files were last modified on or before 2025-10-02, none after round 1's table was built; the 51 404s equal b620's 51 missing months.

## Cause (MEASURED)
Round 1's table came from `ml_entry_v2.build_table`, which applies an explicit delisting mask: frozen bars (volume 0 and high == low) are dropped
BEFORE features and labels. The timeframe harness (`fetch_symbol` -> `build_table`) had no such mask.
- `frozen_bar_mask_check.py.txt`: 36,330 frozen dev-window bars over the 60 symbols (WAVESUSDT 11,439; BLZUSDT 6,761; FTMUSDT 6,423; OMGUSDT 5,823);
  the unmasked dev table has 665,527 rows, the masked one 665,104, a difference of 423 rows; the measured test-row difference b620 vs round 1 was 417.
- `round1_code_on_masked_table.json`: round 1's own code (ml_entry_recipe.run_cell R0/T0/S0, tau 0.10, seeds 7/11/13, lightgbm 4.6.0) on the MASKED table:
  seed-mean +0.0089485665675495, n 71,950 / 71,886 / 72,063, range 0.00185 = round 1 (b607-01 base) to the last digit.
- `round1_code_on_current_data.json` (UNMASKED, same code): +0.01256, seeds +0.0166/+0.0110/+0.0101. So the whole gap (+0.0036 to +0.0018) is the mask.
So b620-01's fail was a MECHANICAL HARNESS FAULT, exactly what its rule anticipates ("fixed before any other timeframe unit is read"), and with the
mask a single-seed 1h result is exactly reproducible, so its 0.0005 tolerance is meetable. Seed-to-seed range is real (0.0019 to 0.0136 by table) but
it is not what failed b620.

Residual not explained: the masked E table has 665,104 dev rows against the 664,786 quoted for round 1's table (318 rows; the streams-based v2 path
differs in other ways); it does not move the reproduction, which is exact.

Method scripts are kept as `*.py.txt` (one-off diagnostics, not repo code; they read scratchpad caches they built).
