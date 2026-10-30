# DESK-18F — do judged-1's entries clear S3 when entered as maker fills?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane `DESK-18F-MAKER-FILLS` (Tier 1, `landing: hold`)

Operator 2026-10-30 ~20:45Z, popup answer verbatim "Maker fills". Rule `RULE-RQ20261030-F18F-01-DESK-MAKER-ENTRY` in
`research/queue/blocked/RQ-20261030-f18f-01.yaml` was committed (`61e0943`, 21:18Z) **before** the first maker score. Harness
`scripts/research/desk_maker_entry_replay.py`; evidence `comms/research/RQ-20261030-f18f-01/local-2026-10-30/maker_entry_result.json`.

**Gates this adds or changes: none.** No config, roster, order or mode touched.

## Verdict: S3_NOT_CLEARED. Neither arm is anywhere near the bar. DESK-18D stays blocked.

Population: the 732 valid judged-1 proposals (723 short, 9 long), six crypto USDT perps, 2025-11-01..2026-09-15, candles Binance Vision
spot 1h. S3 per slot = mean of (slot net R − same-model random-entry slot mean), non-fills = no-trade = 0 R on both sides,
weekly-cluster bootstrap, 10,000 draws. Bar: S3 ≥ +0.25 R and 97.5% CI lower bound > 0. MEASURED observed sd 1.55–1.66 R, MDE 0.16–0.17 R iid.

| Arm (W = 4 bars, maker 2.0 bps entry leg, entry slip 0) | fill rate (random baseline) | desk mean net R | random null | **S3 per slot** | 97.5% CI | clears |
|---|---|---|---|---|---|---|
| control: market entry, taker | 1.000 | +0.132 | +0.124 | +0.007 | [−0.22, +0.22] | — |
| A: limit at the proposal's entry | 0.985 (0.987) | +0.157 | +0.150 | **+0.007** | [−0.22, +0.22] | no |
| B: limit 0.25 ATR inside the entry | 0.807 (0.808) | +0.104 | +0.114 | **−0.010** | [−0.23, +0.20] | no |

Sensitivities (not decisive), all S3 within ±0.03 R of 0: maker fee 3.5 and 5.5 bps; entry slippage kept; window 1 and 12 bars
(B window 1: fill 0.627, S3 +0.015, CI [−0.16, +0.19]); offset 0.50 (fill 0.642, S3 −0.027). Per fold (A): −0.07, +0.03, +0.32, −0.45 (noise). Longs (n 9): −0.33.

## What this means

1. **The control reproduced judged-1** (S3 +0.007 vs recorded +0.006): all 732 exit reasons and days match the committed records.
2. **A cost lever cannot move a paired S3.** The maker fee/slippage saving is worth about +0.025 R of absolute net R (desk +0.132 → +0.157)
   but it lifts the random baseline by the same amount (+0.124 → +0.150), so S3 is unchanged by construction. The only way a fill model moves
   S3 is by interacting with the desk's selection (fills when price comes back to the entry); there is none: A's S3 equals the control's to 0.001 R.
   Even if it had worked, a ~5 bps/entry saving against a 0.25 R bar was always out of reach (prior stated in the unit: below 5%).
3. **The desk's +0.13..+0.16 R absolute is short-side drift, not timing**: random entries with the same geometry earn +0.12..+0.15 R (723 of 732 are shorts).
4. **Adverse selection is real but small here**: arm B's non-fills (19%) are the entries price ran away from; B's desk mean (+0.104) is below A's (+0.157) while its null fell by the same amount.

## Stated limits and deviations (RULE ONE)

* **Packet-sha drift.** All 1,498 re-derived judged-1 packets keep their id but not their sha (tried candles from 2025-05-01 and 2024-05-01, same result); the cause is not established (git history is shallow). The driver's own guard aborts on this; the harness counts it and instead requires the control to reproduce the committed records on the path (it did).
* **Cost-policy gap.** Committed judged-1 net R is a constant 3.5 bps round trip cheaper than today's policy (mean −3.5000, sd 1.8e-14 bps). Cause not established; all arms here use today's policy for desk and baseline alike. It does not affect S3.
* Maker fee 2.0 bps is the published schedule, UNVERIFIED on our account. Not modelled: latency, queue, post-only rejects, partial fills; 1h bars give no intrabar order (stop first on the fill bar, no target credited, pessimistic). Take-profit stays a taker exit (a resting TP is a separate, unmeasured lever, again a cost lever).
* Population is the DEV sample the arms were not tuned on (two arms registered, Bonferroni 97.5%); a pass would have been a discovery only.

## Best next lever

Execution levers move absolute P&L, not the relative bar. The desk equals a random short entry (S3 ≈ 0 across six variants), so what is missing is **information at the entry**, not cheaper fills. In order: (1) **event-driven entries** (a trigger the 1h price packet cannot see: scheduled macro/funding/liquidation events, `docs/research/` event-calendar work), judged on a fresh window; (2) a **universe** with more dispersion than six correlated perps. Only a lever that changes what the judge can know can lift S3. Resting-TP maker exits are worth doing for absolute cost if the desk ever trades, but will not re-open DESK-18D.
