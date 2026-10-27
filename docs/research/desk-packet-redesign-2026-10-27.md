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

## 4. Results

*(appended after judging)*
