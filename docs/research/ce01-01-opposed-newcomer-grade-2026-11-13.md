# RQ-20261111-ce01-01: hand-grade of the opposed-newcomer study (2026-11-13)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `FRONTIER-RESEARCH` for AM-ML · row `CONFLICTING-EXPOSURE-ALERT` · Tier 1. Gates this adds or changes: none.

**Lane:** FRONTIER-RESEARCH, working AM-ML's 03:17Z queue (item 2, PI-20261113-6YRT1RMK-0001).

**Rule:** `RULE-CE-OPPOSED-NEWCOMER-01`, registered 2026-11-11, before the run.

**Graded run:** 43172978800, commit a677d736. The raw outputs are on main at `comms/research/RQ-20261111-ce01-01/43172978800/result.json`.

## Why this needed a hand grade

The run exited 0 and wrote `result.json` with a verdict for every bucket. It wrote no `verdict.json`, so the collector landed `read_state: producer_failed` (`research/results/RQ-20261111-ce01-01/43172978800.jsonl`).

The same PR fixes the producer. `scripts/research/opposing_overlap.py` now writes the E5 `verdict.json`, so the unit, still `queued`, grades itself on its next dispatch.

## The grade

**Population:** unique NEWCOMER trades, meaning trades opened against an already-open, opposite-direction trade of a different leg on the same symbol.
- 1,495 opposed pairs over 6,958 committed Stage-0 trades.
- `net_r` is each corpus's own, net of fee, slippage and funding.
- Statistic: mean newcomer `net_r`, 95% normal CI, n floor 30 (as registered).

**Arithmetic check (ALL bucket):** −0.1642 ± 1.96 × 1.2300 / √1112 = −0.1642 ± 0.0723 = [−0.2365, −0.0919]. This matches `result.json`.

| bucket (rule level = gap\|role) | n | newcomer mean R | CI95 | verdict |
|---|---|---|---|---|
| **ALL** | 1112 | −0.164 | [−0.237, −0.092] | **CLOSE_NEWCOMER** |
| gap=2-4x \| newcomer_shorter_tf | 492 | −0.212 | [−0.313, −0.111] | **CLOSE_NEWCOMER** |
| gap=>4x \| newcomer_shorter_tf | 405 | −0.209 | [−0.321, −0.097] | **CLOSE_NEWCOMER** |
| gap=2-4x \| newcomer_longer_tf | 126 | −0.214 | [−0.453, +0.025] | INDETERMINATE |
| gap=>4x \| newcomer_longer_tf | 21 | +0.472 | [−0.265, +1.210] | INDETERMINATE (n < 30) |
| gap=same \| same_tf | 179 | +0.024 | [−0.184, +0.231] | INDETERMINATE |

**Unit verdict (E5):** `measured`, **`fail`**.

The question was "does the opposed newcomer keep positive expectancy net of the full cost stack?" The ALL bucket's CI95 lies entirely below zero. The E5 mapping is the ALL bucket's verdict: CLOSE_NEWCOMER → fail, KEEP_BOTH_OK → pass, INDETERMINATE → indeterminate. That is the overall verdict the script has always printed, and the per-bucket thresholds are unchanged.

**Never-opposed baseline (context only, not graded):** see `never_opposed_baseline` in `result.json`.

**Rule-level reading.** The live-review rule of thumb may be written only from decided gap|role buckets:
- **A shorter-timeframe leg opening against an open longer-timeframe leg loses money**, at both a 2–4× and a >4× gap: about −0.21 R per trade (n 492 and n 405). The registered rule's action is CLOSE_NEWCOMER, i.e. close or skip the newcomer side.
- **Longer-timeframe newcomers and same-timeframe pairs are INDETERMINATE.** These stay with the reviewer's priced judgement (`live_review_outcomes` per leg).

**Discoveries, not rules.** The gap|role|vol buckets are discoveries; a disjoint window must confirm them before they become rules. For example, gap=2-4x | newcomer_longer_tf | high_vol is CLOSE_NEWCOMER at n 66.

## Reproduction on today's corpora

I ran the fixed producer at main 94553146b8 on 2026-11-13. The corpora have since grown by 12 trades and 1 pair: 1,496 pairs over 6,970 trades, ALL n 1,113, mean −0.157 R, CI95 [−0.230, −0.084].

The outcome is the same:
- unit verdict `fail`;
- the same two rule-level buckets are decided, both CLOSE_NEWCOMER;
- every other rule-level bucket is INDETERMINATE.

## What this does not do

It changes no config, gate, roster or order. The conflicting-exposure alert stays an alert.

The INCUMBENT side is not graded, because its whole-trade R includes R accrued before the newcomer opened. The unit names a candle replay of the incumbent's remaining path as the follow-up "if this one finds an effect". It did find an effect, so that follow-up and the live-review wording are filed on row CONFLICTING-EXPOSURE-ALERT (owner AM-TRADING).
