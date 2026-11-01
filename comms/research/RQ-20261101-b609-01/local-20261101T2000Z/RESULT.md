# RQ-20261101-b609-01 (lane ML-RECIPE): the ONE W1 read of ENTRY v2 (2026-10-01..31) - FAIL

Rule registered before the b608-01 result and before any W1 outcome was read (commit on claude/ml-v2-stack). One model, one read: lock lines ENTRY-v2-S3_R2_gate_24 and ENTRY-v1-frozen-ref-b609 in comms/research/holdout_reads.jsonl; variants on the window: 2. No other variant was scored on W1.

**Verdict: FAIL.** (a) n >= 300 and >= 10 symbols: yes (n=320, 45 symbols). (b) mean net R >= 0: NO (-0.1161). (c) mean >= frozen v1 reference: NO (v1 -0.0405).

| | n | symbols | net | gross | cost | CI95 (reported) | long | short | exits |
|---|---|---|---|---|---|---|---|---|---|
| v2 stack (R2 + gate 0.06 + 2/4) | 320 | 45 | -0.1161 | -0.0714 | 0.0447 | [-0.231, +0.005] | 15: +0.180 | 305: -0.131 | SL 167, time 102, TP 51 |
| frozen v1 reference (as live) | 894 | 49 | -0.0405 | +0.0262 | 0.0667 | [-0.119, +0.031] | 144: -0.401 | 750: +0.029 | SL 431, TP 277, time 186 |
| traded-5, v2 | 8 | 3 | -0.1931 | | | [-0.78, +0.54] | | | |
| traded-5, v1 reference | 62 | 5 | +0.0417 | | | [-0.22, +0.33] | | | |

Baselines on the stack's mechanics (2/4 bracket): no trade 0; always-long -0.2370 (n 2,009); always-short +0.1515 (n 1,917); random matched to the stack's take rate and side mix +0.1004 (p95 +0.1525). October 2026 favoured SHORTS strongly; v2's shorts earned -0.131 where random shorts earned +0.100, i.e. the selection was worse than chance on this window (not just unlucky beta). v2 took 15.9% of free slots (320 of 2,009) against about 36% for v1 on dev: the 0.06 cost gate removed most calm-market decisions.

Reading (descriptive, no new W1 scoring): the dev stack (+0.0478, 8 of 8 folds, 4 of 4 years) did not hold on the first unseen month; a dev-selected stack of three dev winners (12+ arms searched) is optimistic by construction. n=320 is thin (SE about 0.06), so the result is -1.9 SE below zero, not proof the stack has no edge, but it fails the registered bar and is worse than the live v1. W1 is now SPENT for this stack. Do not swap; v1 stays. A re-test needs a FRESH window.

Sizing (modelled, risk f of equity per trade, entry order; concurrency not modelled; see sizing.json): W1 v2 pooled at 0.5%: -17.4% (max DD -19.4%); at 1.5%: -45.4% (-48.9%). Dev traded-5, v2 stack seed 7 (n 2,117, +0.0139 on this seed): at 0.5% +12.1% total (+3.1%/yr), max DD -26.4%; at 1.5% +15.8% (+4.0%/yr), max DD -63.6%. The same population on v1 is negative on dev (-0.0405).
