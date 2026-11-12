# DESK-18H: does the desk's judgement add to an open-interest-shock trigger?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane of row DESK-18D-JUDGE-2 (Tier 1, research tooling only)

Operator 2026-11-12 decisions page w6, verbatim: *"Event-driven entries; lane keeps its defaults on the 4 small questions"*. Unit
`RQ-20261112-e4a7-01` (rule `RULE-RQ20261112-E4A7-01-DESK-EVENT-PACKET-ARM`), registered and pushed 11:19Z **before any packet was judged**. A
correction was pushed 11:23Z, also before judging, and is recorded in the unit: the packet did not show the last bar's direction. Harness:
`scripts/research/desk_event_packet_replay.py`. Evidence: `comms/research/RQ-20261112-e4a7-01/local-2026-11-12/{verdict.json,records.jsonl}`,
with judged inputs in `comms/research/desk_event_packet/judged/`.

**Gates this adds or changes: none.** No config, roster, order or mode was touched. The judging ran on the plan (no API credits).

## Verdict: S3_NOT_CLEARED. The judge does not add to the trigger.

DESK-18G already scored the **mechanical** E4 rule: DEV S3 +0.157 R, short of the +0.25 R bar. This run is the option its report left open:
the desk's own judgement, woken only by E4. Each event opened one masked single-asset packet. The packet carried an `event` block (open-interest
change, its z-score, the last closed bar's return, the continuation side). The protocol carried the same trigger's outcomes per structure from the
holdout window 2024-11-01..2025-10-25, which ends before DEV starts.

Population: all 763 DEV E4 events (2025-11-01..2026-09-15, six crypto USDT perps, Binance 1h). One packet was withheld by the mask-leak scan, so
**762 were judged**. Judges were 24 Sonnet-tier plan subagents, about 32 packets each, using Read and Write only.

| measure | value |
|---|---|
| proposals | **113 of 762 packets (14.8%)**, 0 refused by the guard, all filled |
| side | **110 short, 3 long** |
| **S3** (proposal net R minus its own geometry at random same-symbol, same-ATR-decile DEV cutoffs outside E4 windows) | **+0.128 R**, 95% weekly-cluster CI **[−0.258, +0.553]**, n 113, 29 weeks |
| S1 (mean net R of the proposals) | +0.104 R [−0.297, +0.530] |
| sd of the paired difference; MDE (iid) | 1.53 R; 0.40 R |
| the mechanical E4 rule on the SAME 762 events (reported, not decisive) | S3 **+0.149** [+0.049, +0.252]; S1 −0.009 |
| judge minus rule per event (a pass = 0 R) | **+0.024 R** [−0.066, +0.116] |
| exits | 67 stop, 35 target, 11 time |
| controls (planted, same scorer path) | oracle +0.798 [+0.684, +0.912] clears; anti-oracle −0.656 |

**Cross-checks (RULE ONE).** The rule-on-same-events S3 of +0.149 reproduces DESK-18G's +0.157. The difference comes from one withheld event,
a 95% CI instead of 97.5%, and the baseline engine (the driver's `random_baseline` counts only fills, DESK-18G's slot counts a refusal as 0).
The oracle and anti-oracle (+0.80 / −0.66) match DESK-18G's (+0.786 / −0.648). The holdout trigger_history row for E4's own bracket (n 856,
+0.022 R) equals DESK-18G's held-out S1. The instrument agrees with itself.

## What this means

1. **The bar is missed by a wide margin, and the judge's increment is about zero.** The point estimate of +0.13 R sits below the rule's own +0.15 on
   the same events. Judge minus rule is +0.02 R with an interval centred on 0. Selection from the packet added nothing measurable to the trigger.
2. **The short bias came back.** 110 of 113 proposals are short, as in judged-1 (723 of 732). The trigger_history said "continuation". The judge
   took the continuation side mostly when that side was short, and passed on most long continuations. The packet's own base-rate rows over the
   DEV-era look-back lean short, which fits the earlier finding that the judge is close to a linear function of the base-rate rows.
3. **Underpowered, stated in advance.** n 113 at sd 1.53 gives an MDE of 0.40 R. A true +0.25 R had about a 40% chance of clearing (iid; less once weeks cluster). Even so, the
   result cannot be read as "the judge helps but the sample was small": its increment over the rule is +0.02 R on 762 paired events.
4. **Per symbol** (n 10–36, noise level, looked at after the score): BTC +0.57, SOL +0.33, AVAX +0.19, ADA +0.18, XRP −0.12, ETH −0.38. Not a finding.

## Consequence for DESK-18D-JUDGE-2

The row re-opens only when a packet arm or model clears S3 ≥ +0.25 R with the CI lower bound above 0 on DEV. This arm did not, so judged-2 (C1)
stays unrun. Three structural levers are now tested: maker fills (DESK-18F, +0.007), event entries mechanically (DESK-18G, +0.157) and event
entries judged (this run, +0.128, with +0.02 over the rule). The value in the event lever sits in the **trigger**, which already trades as the
mechanical `e4_oi_shock_1h` leg on `bybit_1`. The desk's packet judgement adds nothing to it. **The one lever left on the row is a universe
change**, still the operator's to choose.

## Spend

25 judging runs (24 batches plus 1 rejected and re-judged: batch b02's first judge made a no-op Bash call, so it was rejected and kept in the
lane's scratch). About 4.0M subagent tokens in total, MEASURED by the harness. API-equivalent cost about 6–10 USD at Sonnet list price,
INFERRED (the cache split is unknown). Within the 15 USD ceiling, on the plan. The tool-use audit read every transcript: each accepted run used
only Read (the protocol and its own batch) and Write (its own output). None read the mask key.

## Stated limits

* Binance candles stand in for Bybit. Entry is at least one 1h bar after the event is known.
* One judge family (Sonnet tier) and one packet design (mode A features, no raw bars). A raw-bar packet or a different judge would be a new registration.
* Part or all of the DEV window may precede the judge's knowledge cutoff (not verified). Masking is the leak control.
* The four `desk_triggers` detectors with 0 of 72 entries were not scored here. Per the lane's default on design § 6 Q4 they stay as labelled negatives.
