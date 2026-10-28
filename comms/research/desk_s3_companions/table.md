# S3 companions on the edge program's committed evidence (DESK-S3-VOL-MATCHED-BASELINE)

Re-scored by `scripts/research/desk_s3_companion_table.py` (token-free; Binance Vision USD-M 1h candles re-fetched). Every re-derived S3 equals the committed value to 1e-9 (`matches_committed`). 95% weekly-cluster CIs; n = filled proposals / picks.

| record | n | S3 | gross excess | S3_matched | gross excess (matched) |
|---|---|---|---|---|---|
| judged-1 (all filled proposals) | 732 | +0.006 [-0.192,+0.194] | +0.003 [-0.195,+0.191] | -0.001 [-0.195,+0.185] | -0.002 [-0.196,+0.184] |
| packet-redesign arm A (top-pick policy, dev sample) | 100 | +0.161 [-0.176,+0.482] | +0.158 [-0.181,+0.480] | +0.162 [-0.175,+0.480] | +0.163 [-0.173,+0.480] |
| packet-redesign arm A (proposals, dev sample) | 7 | +0.878 [-0.535,+1.777] | +0.855 [-0.543,+1.739] | +0.859 [-0.245,+1.696] | +0.855 [-0.242,+1.700] |
| packet-redesign arm B (top-pick policy, dev sample) | 100 | +0.016 [-0.242,+0.284] | +0.010 [-0.246,+0.276] | +0.011 [-0.239,+0.267] | +0.008 [-0.243,+0.263] |
| packet-redesign arm B (proposals, dev sample) | 3 | +0.115 [-0.947,+2.184] | +0.063 [-0.953,+2.060] | -0.046 [-0.993,+1.811] | -0.055 [-0.994,+1.793] |
| packet-redesign arm C (top-pick policy, dev sample) | 100 | +0.015 [-0.243,+0.291] | +0.006 [-0.248,+0.278] | +0.027 [-0.251,+0.322] | +0.027 [-0.251,+0.322] |
| packet-redesign arm C (proposals, dev sample) | 14 | +0.268 [-0.387,+0.842] | +0.239 [-0.426,+0.823] | +0.268 [-0.436,+0.865] | +0.266 [-0.442,+0.864] |

Reading: in all 7 rows, S3_matched and gross excess agree with S3 to within ~0.03 R and every 95% CI includes 0 -- none of these S3 values came from volatility selection (their selectors are not vol-rules), and none is evidence of timing either.

NOT re-scored: the 1m ceiling (`ceiling-1m`) and `ceiling-era`/`ceiling-dev`: their `actions.pkl`/`features.pkl` are not on main and a 1m rebuild was out of this lane's scope. The committed `ceiling-1m/vol-rule-mechanism.json` (n = 480816 test actions) already shows the flaw (vol-rule S3 +0.285, gross +0.016); re-run `desk_edge_1m.py mechanism` on a rebuilt directory to get its `companions` block (the code is in place, covered by the synthetic fixture test).
