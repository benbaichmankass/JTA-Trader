# DESK-PACKET-REDESIGN — does the judge find edge when the packet stops pre-digesting the market?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-PACKET-REDESIGN` (Tier 1, research), dispatched by Manager Session 2026-10-27a. Checklist row `docs/claude/work/checklist/DESK-PACKET-REDESIGN.json` (roadmap `L-DESK`).

Operator, chat 2026-10-27 ~17:00Z, verbatim: *"it seems like there's an issue with the packets, because if he's just reading back statistics, then it means that the way that the information is being presented is deterministic ... we need to make sure that we're giving raw information that Claude can actually analyze, and not just an output that we're expecting to get ... We need to think about how exactly to structure it so that we're actually getting the edge of having LLM and analyze large amounts of data and patterns, and not just reading a small statistical summary and then spitting that back out."* Popup: **"Yes, all 4 arms (Recommended)"**; ~17:05Z: *"option D is basically the research routine that we have today ... we need to make sure that we're not just rebuilding something that already exists."* So arm D (an agentic researcher) is dropped; this lane tests arms A, B and C.

**Sections 1–3 were committed before any B or C packet was judged.** Results are in § 4 and were appended after.

## 1. Why

DESK-EDGE-PROGRAM (PR #20672, `docs/research/desk-edge-program-2026-10-27.md` § 4.3) measured that the judge's cell scores are a linear function of the packet's base-rate rows (R² 0.90–1.00 per batch), 731 of 732 judged-1 theses cite them, and a free emulator of that rule scores about 0 (S3 −0.05). The judge is anchoring on the pre-digested summary. The question here: **if the summary is removed (B), or replaced by the raw market data it was computed from (C), does the judge's behaviour change, and does it earn S3?**

## 2. Design

### 2.1 The packets (all on the same 100 packets)

The dev sample of DESK-EDGE-PROGRAM § 5.1 (`desk_edge_devloop.py sample`, 100 judged-1 packets in the DEV window, 32 strata of fold × session × BTC 168h regime). Every packet is rebuilt from the candles and its id asserted. The same aliases, the same price rebasing (each alias's last 1h close = 100) and the same mask key serve all three arms. Nothing in the edge program's locked HOLDOUT (2025-05-01 .. 2025-10-25) or FULL RUN window is read: `desk_edge_devloop.assert_not_locked` runs on every cutoff.

| arm | what the judge sees | median size (MEASURED, chars) | est. tokens |
|---|---|--:|--:|
| **A** control | today's masked scan packet: ATR, swing high/low and distances, `htf_trend`, session, and the net-of-cost forward-R **base-rate rows** (`history`, mirrored in `features_at_review`) | about 17,000 | about 6,000 |
| **B** no anchor | A with every base-rate / history quantity **removed** (`history`, every `features_at_review` key ending `_r`). Nothing else changes | 7,500 | about 2,500 |
| **C** raw | **raw data only**, per alias: OHLC bars before the cutoff, 1m × 90 (90 min), 5m × 96 (8 h), 1h × 96 (4 days), 4h × 60 (10 days), 1d × 30 (30 days); per bar relative volume (100 = the table's median bar) and taker-buy share; the last 9 funding prints known at the cutoff. Prices in bps from the last 1h close. Kept from A because the bracket and the masking need them: alias, 1h ATR(14), session label. No summary, no swing, no trend label, no base rate | 50,287 (max 57,157) | about 17,000 (chars / 3; § 4 gives the MEASURED subagent token counts) |

Builder: `scripts/research/desk_packet_modes.py`, called through the replay builder `desk_gen_replay_driver.build_masked_packet(..., mode="B"|"C")` (default `"A"` is unchanged). Mode C is built from Binance Vision **USD-M perp 1m klines** (taker-buy volume included) and USD-M funding. **Point in time:** a 1m bar is used only if it closed at or before the cutoff, a funding print only if it was computed at or before it (tested: perturbing every bar after the cutoff leaves the packet identical). **Consistency check (refuses a packet otherwise):** every alias's newest 1m-built 1h close equals the replay's own 1h close within 1 bp; 100 of 100 packets pass.

**Stated limits of C.** No equity index: a calendar-hours series would un-mask the calendar every arm withholds; the cross-asset context is the six aliased series (BTC and ETH among them, unnamed, as in A). No news: the replay's packet history has none (`news: could_not_look`). Funding is information A and B do not have (A: `could_not_look`), so C vs A changes representation AND adds funding and flow; that is the design the dispatch asked for, and the contrast cannot separate the two.

**Found while building (RULE ONE):** the replay driver's docstring says its candles are Binance Vision SPOT; they are USD-M PERP (`fetch_backtest_candles.py` `_BINANCE_VISION_BASE = .../futures/um`). A spot-built mode C failed the consistency check on every packet (4–18 bps off), which is how this surfaced. Fixed in this PR (the driver docstring now says USD-M PERP).

### 2.2 The judge, the protocol and isolation

- **Same protocol, only the packet description changed.** Every arm uses the driver's `JUDGE_PROTOCOL` plus the dev-loop `RANK_ADDENDUM` (score all 12 asset × side cells for the fixed bracket GJ: market, stop 1.25 ATR, target 2.0 R, 48 bars; then optionally propose). Arm A's protocol is byte-identical to V1's committed `JUDGE-PROTOCOL.md` (tested). B drops the sentence that names the base-rate rows; C describes the raw tables (`desk_packet_arms.protocol`).
- **Arm A is the V1 pilot, reused, not re-judged.** V1 judged exactly these 100 packets with exactly this protocol in Sonnet plan subagents (`comms/research/desk_edge/dev-1/V1/ranks.jsonl`, audited, 100/100 valid). Re-scored here with the arm runner it reproduces V1's committed numbers (SEL +0.0443, top-pick S3 +0.161, n 100). Re-judging A would buy nothing but a second sample of the control; the budget goes to B and C.
- **B and C: Sonnet plan subagents (no API credits, ever)**, 10 packets per batch for B (V1's grain), 5 per batch for C (packet size). Each subagent may only Read its one batch file and Write its one output file; no Bash, Grep, Glob, script or code. **Audit from the subagent transcripts:** a batch that used any other tool, opened any other path, or produced scores with code is **rejected** (kept under `rejected/`) and re-judged once with the same instruction; a second break leaves those packets missing, counted.
- **Budget rule (registered; depends on cost only, never on a result):** the first C batch's MEASURED tokens set the projection. If 100 C packets project above $15 API-equivalent, C stops at the first 50 packets of the sample order (near-balanced by construction) and reports at n = 50 with that stated.

### 2.3 Scoring (reused, never re-implemented)

The edge program's labels (`desk_edge_devloop.cell_labels`: the driver's engine and random-entry baseline, same symbol, side and fold, full cost stack), SEL and the sequential decision (`SEL_USEFUL` +0.25), the top-pick policy and the driver's `cluster_stats` (S3 = `paired_diff_vs_random`, 95% weekly-cluster CI); proposals through the driver's own `read_proposals` (against the A packet: same aliases, levels and ATR) and `score` loop.

## 3. The pre-registered rule (constants in `scripts/research/desk_packet_arms.py`)

### 3.1 Per-arm S3 and the useful bar
- **Primary:** top-pick S3 (per packet the single highest-scored cell, taken if its score > 0; the driver's `cluster_stats`), with its 95% weekly-cluster CI.
- **USEFUL** iff **S3 ≥ +0.25 R** AND the 95% CI lower bound **> 0** (the operator's bar, DESK-EDGE-PROGRAM § 6.1).
- Reported beside it: SEL (mean, 95% CI) and the program's sequential decision (`kill` / `screen_fail` / `promote`); the program's promote rule, not this lane, decides whether anything goes to its holdout.
- Proposal-level S3 (the judge's own `propose_entry` rows through the driver's `score`) is reported with its n and CI; at about 5–50 fills per arm it is **descriptive, not decisive**.

### 3.2 Arm-vs-A contrasts
- **B − A and C − A, paired by packet:** per packet the arm's SEL minus A's SEL; weeks resampled (10,000 draws, seed 20261027); two-sided CI at alpha **0.05 / 2** (two contrasts). "Differs" iff the CI excludes 0.

### 3.3 Behavioural check: anchoring
- **Base-rate linearity:** OLS R² of the judge's cell score on that cell's own A-packet base-rate means (h4, h12, h48, same side), with an intercept, **pooled** over all cells and **per group of 10 packets** in sample order (V1's batch grain). Computed for every arm on the A-packet base rates, whether or not the arm saw them.
- **"Breaks the base-rate linearity"** iff pooled R² **< 0.50** AND the median per-group R² **< 0.50**.
- Arm A's values (computed before this registration from V1's already-published ranks): pooled R² **0.79**, median per-group R² **0.99**.

### 3.4 Direction balance
- Long share of the top-scored cell per packet; **B − A and C − A paired by packet** as in § 3.2; "changes direction balance" iff that CI excludes 0. Arm A (V1, already published): top-cell long share **0.11**.
- Also reported: long / short counts of valid proposals, and the share of all cells scored > 0.

### 3.5 Proposal rate
- Packets with ≥ 1 valid `propose_entry` / 100, and the long / short mix. Arm A (V1): **0.05** (5 packets, 7 proposals, all short).

### 3.6 Recommendation (registered)
- The live desk should adopt the packet design of an arm only if that arm is **USEFUL** (§ 3.1). If more than one is, the higher S3. Otherwise the recommendation is **"none yet"**.
- An arm that breaks anchoring (§ 3.3) without being USEFUL changes no live design: it is evidence for which packet the next judge variant should be built on, and it is reported as such.
- A USEFUL arm whose SEL decision is not `promote` is recommended **only to the edge program's holdout**, not to live: the program's holdout and full registered run (DESK-EDGE-PROGRAM § 5.4–5.5) are what real money needs; nothing here shortens Gate 1.

### 3.7 Amendment 1 — arm C's size and batch (committed 2026-10-27 before any further C judging; no C outcome label had been computed)

The first C batch (5 packets, Sonnet subagent, isolation-compliant) MEASURED **286k cache-creation + 2.43M cache-read input tokens, about $1.94 API-equivalent**. A C packet is therefore about **50k real tokens**, not the 17k estimated from chars / 3, because numeric tables tokenise near one token per character. That prices 100 C packets at about $39 against a judging budget of $20. The judge's own hand-back also said it **did not analyse packets 2–5** of the batch, and their cell scores are near-flat (|score| ≤ 0.06). Under § 2.2 that batch is **rejected**: its file is kept under `rejected/`, it is never scored, and no label was computed for it.

Changes (the arm's question is unchanged: raw bars, no summaries):
- Rows per alias: 1m × 30 (30 min), 5m × 48 (4 h), 1h × 48 (2 days), 4h × 30 (5 days), 1d × 20 (20 days), down from 90 / 96 / 96 / 60 / 30. The open column is dropped, since it is the previous close. **MEASURED median 20,274 chars (max 22,725)**; tokens are given in § 4 from the subagents' own counts.
- **2 packets per batch.** The protocol now requires each packet's own bars to be analysed before it is scored; a batch scored without reading its bars is rejected.
- **Registered budget rule invoked (§ 2.2):** C runs on the first **50** packets of the sample order (near-balanced: the first 50 cover every stratum). A and B are scored on all 100. Every C-vs-A contrast is paired on those 50 packets, and A's and B's numbers are also reported on the same 50.
- Arms now differ in batch size (A 10, B 10, C 2). This is a stated confound: smaller batches may draw more attention per packet.

### 3.8 Amendment 2 — C on packets 51–100, and a fixed size cap (manager decision ~17:58Z; committed before any of packets 51–100 was judged)

Manager, verbatim: *"DECISION: yes, judge arm C on the remaining 50 packets ... Lane ceiling raised to $42 total, judging up to $30. Run it under the registered 4-look rule, unchanged ... cap C's size so every batch is judged. That is a fixed rule, not a per-packet choice, so register the cap before judging."*

- **C runs on all 100 packets.** Packets 51–100 are judged with the same amended packet, protocol, batch size (2) and isolation audit. The registered dev rule (DESK-EDGE-PROGRAM § 5.3: looks at 25 / 50 / 75 / 100, `SEL_USEFUL` +0.25) is unchanged, and so are §§ 3.1–3.6 here. The C − A and C − B contrasts are recomputed on 100.
- **Fixed size cap:** a judge-facing C packet over **`MAX_C_CHARS` = 24,000** characters is **refused** (never judged, counted). Packets are never trimmed one by one. MEASURED on the amended build: 100 of 100 packets fit (median 20,274, max 22,725). The rebuild under the cap is byte-identical to the batches already judged (50 of 50 batch files hash-equal).
- **Budget:** judging cap $30 (spent $18.34 before this amendment); about $11 projected for packets 51–100.

## 4. Results

Evidence: `comms/research/desk_packet_redesign/` (`B/ranks.jsonl`, `C/ranks.jsonl`, the protocols, `build.json` sizes, `scores-100/`, `scores-50/` with `compare.json`, `isolation-audit.txt`, `C/example-packet.txt`). Arm A's ranks are V1's committed `comms/research/desk_edge/dev-1/V1/ranks.jsonl`. Every number below is MEASURED by `scripts/research/desk_packet_arms.py score|compare` on the DEV window. Population: the dev sample, all 100 packets for A vs B, and the first 50 packets of the sample order (33 ISO weeks, all 32 strata) for any comparison involving C.

**Intake and isolation (MEASURED from the subagent transcripts, `scripts/research/desk_packet_isolation_audit.py`).**
- B: 10 batches × 10 packets, 100/100 packets ranked, 0 refused cells.
- C: 25 batches × 2 packets, 50/50 ranked.
- Every batch used only `Read` on its own batch file and `Write` on its own output file: **35 of 35 compliant, 0 rejected for isolation.**
- One C batch was rejected under Amendment 1 (oversized, unanalysed; § 3.7). It was never scored.

### 4.1 The registered table

| | A (control) | B (no base rates) | C (raw bars) |
|---|--:|--:|--:|
| **top-pick S3, n = 50** (95% weekly CI) | −0.072 [−0.44, +0.33] | **−0.343 [−0.65, −0.02]** | **+0.148 [−0.21, +0.53]** |
| top-pick S3, n = 100 | +0.161 [−0.18, +0.48] | +0.016 [−0.24, +0.28] | — (not judged) |
| **USEFUL** (S3 ≥ +0.25 and CI lower > 0) | no | no | no |
| SEL, n = 50 (95% CI) | −0.015 [−0.33, +0.31] | +0.085 [−0.20, +0.36] | +0.154 [−0.17, +0.50] |
| SEL, n = 100 / program decision | +0.044, `screen_fail` | +0.117 [−0.13, +0.35], `screen_fail` | — (n = 50: only 2 of 4 looks; no decision) |
| **base-rate R², pooled / median per 10 packets (n = 50)** | **0.87 / 0.95** | **0.07 / 0.09** | **0.17 / 0.26** |
| base-rate R², n = 100 | 0.79 / 0.99 | 0.015 / 0.08 | — |
| **breaks linearity** (both < 0.50) | — | **yes** | **yes** |
| top-cell long share, n = 50 | 0.04 | 0.48 | 0.72 |
| share of cells scored > 0 (n = 50) | 0.35 | 0.52 | 0.55 |
| **proposal rate**, n = 50 (packets with ≥ 1 valid proposal) | 0.10 (7 proposals, 0 long / 7 short) | 0.04 (1 long / 1 short) | **0.18 (9 long / 1 short)** |
| proposal rate, n = 100 | 0.05 (0 / 7) | 0.03 (2 / 1) | — |
| proposal S3 (driver `score`, descriptive), n = 50 | +0.88 [−0.53, +1.78], 7 fills | +0.62 [−0.95, +2.18], 2 fills | +0.50 [−0.29, +1.17], 10 fills |

**Contrasts vs A (§ 3.2, § 3.4; paired by packet, weeks resampled, two-sided alpha 0.025):**

| | SEL difference | differs? | top-cell long share difference | changes direction balance? |
|---|--:|:-:|--:|:-:|
| B − A, n = 100 | +0.007 [−0.35, +0.38] | no | +0.46 [+0.29, +0.61] | **yes** |
| B − A, n = 50 | +0.21 [−0.19, +0.57] | no | +0.44 [+0.26, +0.62] | **yes** |
| C − A, n = 50 | +0.28 [−0.30, +0.84] | no | +0.68 [+0.54, +0.81] | **yes** |

### 4.2 What it says

1. **The anchor is real and it is the packet.** Remove the base-rate rows and the judge stops reproducing them: R² goes from 0.87 to 0.07 (B) on the same 50 packets, from the same model, under the same rank protocol. So V1's "linear base-rate rule" was the judge reading the summary back, as the operator suspected. It was not an intrinsic property of the judge.
2. **Breaking the anchor does not, on this evidence, create edge.**
   - No arm is USEFUL. The best point estimate is C: top-pick S3 +0.15 and SEL +0.15, on 50 packets. The CI spans 0, and the C − A contrast (+0.28) is not distinguishable from 0 at this n.
   - B is the only arm whose top-pick S3 CI excludes 0, and it excludes it on the **negative** side (−0.34, n = 50; +0.02 on the full 100). With the summary gone and no bars to read, the judge has only ATR, swing distances, a trend label and the session. It chooses worse than random on that half of the sample.
3. **Direction flips once the anchor is gone, in both B and C.**
   - The DEV window's base rates point short (V1 put 96% of its top cells on shorts on these 50 packets, 89% on all 100, and every proposal).
   - Without them the judge leans long: B 48% of top cells, C 72% of top cells and 9 of 10 proposals.
   - S3 is side-neutral by construction (each cell is measured against a random entry on the same side), so the tilt is not itself a cost.
   - It does mean the judge's direction was borrowed from the summary in A, and in C it comes from somewhere else: the bars, or a long prior.
4. **C engages more.** C has the highest proposal rate (18% vs 10% for A and 4% for B on the same 50 packets), and every C packet has 12 distinct cell scores. But the per-packet score spread (max minus min) runs 0.11 to a median of 0.19. The low end overlaps the spreads of the rejected batch's unanalysed packets (≤ 0.12), so this check cannot show that every packet was analysed in depth. And 10 fills cannot price the proposals.

### 4.3 Sizes and spend (MEASURED from the subagent transcripts; API-equivalent dollars at Sonnet list price, on the plan, no API credits)

| | packets | median chars / packet | input tokens per batch (cache-creation) | spend |
|---|--:|--:|--:|--:|
| A (V1, reused) | 100 | about 17,000 | about 172k total per 10-packet run (V1's record) | $0 here (V1: about $7) |
| B | 100 | 7,500 | about 120k per 10 packets | **$5.47** |
| C (amended) | 50 | 20,274 (max 22,725) | about 66k per 2 packets | **$10.93** |
| C batch rejected under Amendment 1 | 5 | 50,287 | 286k per 5 packets | $1.94 |
| **judging total at the n = 50 stage** (final: § 4.4) | | | | **$18.34** (budget then $20) |

A C packet is therefore roughly **20–25k tokens**. This is INFERRED from those per-batch counts, which include the subagent's own system prompt; the packet's share cannot be separated exactly.

### 4.4 The 100-packet dev verdict (Amendment 2; MEASURED, all three arms on all 100 packets, 44 weeks)

Evidence: `comms/research/desk_packet_redesign/scores-100/` (`arm-A.json`, `arm-B.json`, `arm-C.json`, `compare.json`). C packets 51–100 were judged in 25 batches of 2. The isolation audit found **all 25 compliant**, so arm C totals 50 of 50 batches compliant and B 10 of 10. All 100 C packets were under the 24,000-char cap; none was refused.

| n = 100 | A | B | C |
|---|--:|--:|--:|
| **top-pick S3** (95% weekly CI) | +0.161 [−0.18, +0.48] | +0.016 [−0.24, +0.28] | **+0.015 [−0.24, +0.29]** |
| USEFUL (S3 ≥ +0.25, CI lower > 0) | no | no | **no** |
| SEL, the program's week-weighted mean (95% CI) | +0.044 [−0.20, +0.29] | +0.117 [−0.13, +0.35] | +0.101 [−0.15, +0.37] |
| **registered dev decision** (4 looks, `SEL_USEFUL` +0.25) | `screen_fail` | `screen_fail` | **`screen_fail`** (mean +0.101 < +0.25; one-sided 80% lower bound −0.013) |
| SEL, packet-weighted mean (the contrast's statistic) | +0.101 | +0.109 | −0.027 |
| base-rate R², pooled / median per 10 packets | 0.79 / 0.99 | 0.015 / 0.08 | 0.22 / 0.30 |
| breaks linearity | — | yes | **yes** |
| top-cell long share | 0.11 | 0.57 | 0.79 |
| proposal rate (long / short) | 0.05 (0 / 7) | 0.03 (2 / 1) | **0.13 (13 / 1)** |
| proposal S3 (descriptive) | +0.88 [−0.53, +1.78], 7 fills | +0.11 [−0.95, +2.18], 3 fills | +0.27 [−0.39, +0.84], 14 fills |

Contrasts (paired by packet, two-sided alpha 0.025):

| | SEL difference | top-cell long share difference |
|---|--:|--:|
| B − A | +0.007 [−0.35, +0.38], no | +0.46 [+0.29, +0.61], **yes** |
| C − A | −0.129 [−0.60, +0.36], no | +0.68 [+0.54, +0.80], **yes** |

**Reading.**
1. **C is `screen_fail` under the program's registered rule.** No packet design reaches the holdout, and nothing here asks to open it.
2. **The first 50 packets' C estimate (+0.15) did not hold.** C's packet-weighted SEL is +0.165 on packets 1–50 and **−0.219 on packets 51–100** (descriptive split, not a registered test). Its top-pick S3 over all 100 is +0.015.
3. **The two SEL weightings disagree in sign for C** (week-weighted +0.101, packet-weighted −0.027). C's mean SEL is not robust to how packets are weighted within a week. 44 weeks do not resolve an effect this size, as the edge program's § 4.1 predicted.
4. **The behavioural findings held at 100.**
   - The base-rate anchor is gone in B and C (R² 0.015 and 0.22, against 0.79 for A).
   - The direction flips long (C: 79% of top cells and 13 of 14 proposals).
   - C proposes more than either other arm (13%, against 5% for A and 3% for B).
   - None of this turned into S3.

**Spend, all judging (MEASURED, Sonnet list price, plan subagents, no API credits):**
- B, 100 packets: $5.47.
- C, 100 packets in 50 batches: $22.48.
- The C batch rejected under Amendment 1: $1.94.
- **Total: $29.89, against the $30 judging cap.** The lane's other work was CPU-only.

## 5. Recommendation (by the § 3.6 rule) — final, on 100 packets

- **Live desk packet: "none yet".** No arm is USEFUL, and C's registered dev decision is `screen_fail`. The live desk keeps today's packet. No holdout is requested.
- **Never build on B** (manager, agreed): it removes information and earns nothing (S3 +0.02).
- **C is still the better base than A for any future judge variant, but not for the information it carries.**
  - It is the design whose answers are not the summary read back (R² 0.22, against 0.79).
  - Its information content is the same raw data the edge program's token-free ceiling already priced at about zero at these horizons: P+ with returns, range, volatility, taker flow, BTC cross-asset and funding gave policy S3 −0.03 to +0.08, every interval spanning 0 (DESK-EDGE-PROGRAM § 4.1).
  - The judge reading the bars does no better than a fitted model reading the same bars.

**What I would change in C next, ranked by expected information per dollar** (each run is a NEW registered dev variant; nothing below is run here):

| rank | change | why it buys information | cost |
|---|---|---|---|
| 1 | **Horizon: match the bracket to the data.** Re-ask C's judge for a short bracket (the era run's `H1b` 1-bar or `H4` 4-bar geometry, both already in `desk_edge_ceiling`) instead of GJ's 48 bars. **First** run the token-free ceiling on C's information at those horizons (the era run's per-horizon table, DESK-EDGE-PROGRAM § 4.2, or `fe57-02`'s 1m ceiling). Judge only a horizon the ceiling does not exclude. | C's 1m / 5m tables say almost nothing about a 48-hour outcome; the mismatch is the most likely reason fine-grained data added nothing. The ceiling step is free and can kill the idea before any spend. | ceiling $0 (CPU); then about $22 per 100 packets |
| 2 | **Data window: buy weeks, not packets.** Spread the next 100 packets over the era folds (2021-01 .. 2023-10, about 140 weeks) instead of 100 packets in 44 DEV weeks. | The weeks set the CI (§ 4.4 item 3; edge program § 4.1). The same spend gives an interval about 40% narrower (INFERRED from √(140 / 44)). Lowest risk per dollar. | about $22 per 100 packets |
| 3 | **Timeframe mix: put the tokens where the horizon is.** For a short bracket, drop the 1d and 4h tables and lengthen 1m (for example 120 rows) and 5m. | Within the same 24,000-char cap, more rows at the scale the bracket is decided on. Worth doing together with rank 1, not alone. | $0 extra (same cap) |
| 4 | **Symbol set: narrow to BTC + ETH, named.** | Fewer cells, more rows per asset, and cross-asset context the judge can name (masking keeps dates hidden). Smallest expected gain: the ceiling's symbol-identity ablation was −0.03. | about $15 per 100 packets |

**Not recommended:** another C run on the same 100 DEV packets at the GJ bracket. Its question is answered (`screen_fail`).

**Manager decision (2026-10-27 ~18:07Z): none of the four now; lane closed, no further spend.**
- Rank 1's token-free short-horizon ceiling already exists: DESK-EDGE-PROGRAM `RQ-20261027-fe57-02`, PR #20672 § 4.5 (verified on that branch). It finds S3 +0.37 to +0.61 at 5–15 minutes but **S1 < 0 at every hold** under the MEASURED taker cost (row `COST-STACK-BYBIT-TAKER-FEE`).
- A short-horizon judge therefore cannot be profitable until a maker-execution path exists, and judge spend before that is not justified.
- **Standing recommendation for any future judge run: rank 2, buy weeks, not packets.** Spread the dev sample over many weeks (for example the era folds), because the weeks, not the packets, set the interval (§ 4.4 item 3).
- **Closing observation for this row:** a future judge run on short-horizon raw packets (mode C at a matched bracket), after a maker-execution path exists.

## 6. What was not verified, and stated confounds

- **n.** § 4.1–4.3 report C at n = 50 (Amendment 1's budget rule); § 4.4 reports it at n = 100 (Amendment 2). At 100 packets in 44 weeks every interval is about ±0.25–0.5 R wide, and the week-weighted and packet-weighted SEL disagree in sign for C.
- **Protocol wording:** C's intro says "OHLC bars" while each row carries h, l, c, rel_vol, taker_buy_pct. The column header itself is correct (and the intro's next sentence says the open is the previous close). One judge flagged the mismatch and read the rows correctly; no batch shows a misread, but this was not checked for every batch.
- **Batch size differs:** A and B 10 per batch, C 2. Smaller batches may give each packet more attention. B vs A (same batch size) is the clean anchor test; C vs A is not clean on attention.
- **C changes representation and information at once:** it adds funding and taker flow, which A and B lack.
- **One model:** Sonnet subagents only, with file tools. They are audited, but they are not the tool-less live judge.
- **The judges' own claims of analysis** are model output. The only mechanical check is score spread per packet, and it is weak (§ 4.2 item 4).
- **Found and fixed in this PR:** the replay driver's docstring said its candles were spot; they are USD-M perp. The same claim appears in DESK-EDGE-PROGRAM's doc (§ 4.1, "candles Binance Vision spot 1h fetched ... through the driver's `fetch_market`"). That file is on PR #20672 and is not edited here; it is flagged to the manager.
