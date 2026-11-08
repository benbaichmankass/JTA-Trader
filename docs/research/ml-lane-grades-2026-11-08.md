# ML lane grades, 2026-11-08 (units 16, 18, 19, 20, 22; unit 12 config fix)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none. Each grade applies the rule registered in the unit before its run. Results: `research/results/<unit>/`.

| unit | question | result (population) | grade |
|---|---|---|---|
| 98e3-16 | equity structure ensemble with exit pivot=8: OOF at tau 0.25 >= 0.1623? | B_ens at tau 0.25 reads +0.1090, n=1833 (pooled OOF, rows <= 2025-06-30); folds +0.18 +0.21 -0.07 -0.27 +0.44 | **NOT ADMITTED** (0.1090 < 0.1623). The live pivot=5 exit stays the only one |
| 98e3-18 | 15m direction head, BTC cross-asset on ETH+SOL, beats prior by >= +0.002 on both? | engine: no candidate reaches the floor on any clause | **FAIL** |
| 98e3-19 | 15m regime head, BTC cross-asset (lgbm_xa) vs same-asset lgbm on ETH+SOL, >= +0.002 on both? | lgbm_xa minus lgbm, mean CV logloss delta: ETH +0.0008, SOL -0.0018 (each vs the prior: ETH 0.04721 vs 0.04644, SOL 0.06035 vs 0.06210) | **FAIL** (SOL below 0). Engine printed INDETERMINATE: config error below |
| 98e3-20 | same at 1h | ETH -0.0024, SOL -0.0019 (1h: ETH 0.09161 vs 0.09401, SOL 0.11843 vs 0.12032) | **FAIL** (both below 0). Engine printed INDETERMINATE: config error below |
| 98e3-22 | crypto structure-label ENTRY (5-seed ensemble): dev OOF then ONE confirm 2025-10-01..2026-09-30 | dev picked B at tau 0.30 (grid edge), OOF +0.0608 n=2892 (ETH+SOL subset -0.0437 n=103); confirm mean net R **-0.0487** (se 0.0751) at n=212, 52 symbols; months swing -0.82 to +0.97 | **FAIL** (margin floor +0.05 not met; the confirm is negative). No prop candidate |

**Why units 19 and 20 read INDETERMINATE and 12 would have:** the bake-off engine pairs each learner only with the config's `baseline` and `controls`. These units set `baseline: prior` and wrote `vs: lgbm`, so the lgbm-reference clause had no measured folds. Prior art (RQ-20261012-75b2-22) uses `baseline: lgbm`, `controls: [prior]`, `vs: baseline`. The grades above compute the registered statistic by hand: the mean of a paired difference equals the difference of the two means vs the prior (same folds), so the mean criterion is exact; the paired CI is not available. Unit 12 (not yet run) is corrected before its run (thresholds unchanged).

**Unit 22 caveats:** the confirm window was read by other model families (declared in the unit); the dev selection landed on the largest tau of the grid, so a higher grid was never tried (an iteration, not a rescue of this read); 2025-10 alone is -0.80 at n=25.

**Unit 17 id collision:** the ENTRY-EQ export lane used `RQ-20261108-98e3-17` for its export unit on its own branch; my 15m direction-head unit under that id never produced a manifest. It is re-queued unchanged as `RQ-20261108-98e3-24`; 17 is closed as superseded.
