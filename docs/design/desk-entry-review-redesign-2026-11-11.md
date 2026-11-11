# Desk v1 as an ENTRY review: system-detected setups trigger a desk call (design proposal)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · row `DESK-ENTRY-REVIEW-REDESIGN` · GENERAL lane · 2026-11-11 · PROPOSAL for the operator's planning discussion; no live change, nothing filed as build work until the operator settles the questions in § 6.

**Gates this adds or changes:** none proposed. The entry review is ADVICE until it passes its own Stage-0 test (§ 4), the same rule as every live-review action class.

## 1. The ask (operator 2026-11-10 ~11:50Z, condensed faithfully on the row)
Move the *signalling* onto the system: learn which patterns lead Claude to decide to trade, build triggers on those patterns, and open a desk call only when one fires, instead of periodic desk reviews of everything. Keep v1 close to how the live trade review (LTR) works, but for ENTRIES: does this setup give a good trade, what is the structure (side, size, both brackets), and what return over what horizon?

## 2. What the desk has produced so far (MEASURED 2026-11-11 from `origin/desk/decisions`)
| fact | value |
|---|---|
| desk decisions recorded (`comms/desk/decisions.jsonl`) | **188**, judged 2026-10-26 13:50Z to 2026-11-06 20:30Z (none since) |
| `propose_entry` | **17 (9.0 %)**, every one on a periodic `bar_close` scan (17 of 116 bar-close packets) |
| event-triggered wakes (`config/desk_triggers.yaml` detectors) | **72**: `atr_burst` 28, `liquidity_sweep` 23, `level_break` 14, `momentum_burst` 7 → **0** `propose_entry` |
| decisions with a graded outcome (`comms/desk/outcomes.jsonl`) | **0**: the file is empty, so no desk call has ever been scored |
| cost per wake | $0.30 to $0.47, MEASURED (config/desk_triggers.yaml header, n=4 plus the 10-30 wakes) |
| the row's DESK-18E figure (0 propose_entry in 29 live packets vs 0.49 per packet for the masked judge) | NOT re-verified here: rows DESK-18E / DESK-16B are not in the work store (404) |

**What this says for the design.** (a) The existing pattern triggers do not pick the moments Claude wants to trade: 0 of 72. (b) "Learn which patterns lead Claude to trade" has only 17 positive labels, all from scans. (c) There are no outcome labels at all, so nothing yet says whether those 17 were good. A trigger learned from the desk's own choices would learn its taste, not its edge.

## 3. Proposal: the entry review mirrors the LTR loop
| LTR piece (exists) | entry-review counterpart (proposed) |
|---|---|
| wake: telemetry events on open positions (`src/runtime/live_review_due.py`) | **setup triggers**: the strategies' own near-signals plus detectors CHOSEN BY OUTCOME (§ 3.1), each a declared entry in `config/desk_triggers.yaml` |
| packet: position state + options priced from the leg's Stage-0 history (`scripts/research/live_review_outcomes.py`) | **entry packet**: the setup, the structures to choose from (side; stop and target in ATR; size by the leg's risk rule) and EACH structure's base rate from replay of the same trigger, net of the full cost stack |
| reviewer: one recommendation per order package | **reviewer**: one call per setup: `enter(structure)` / `pass`, an expected R and horizon, a forecast to grade |
| apply under `MD-TRADE-DESK`, per-account RiskManager | **apply** through the desk's own leg (`claude_desk`) and the normal account RiskManager, Stage 1 only until § 4 passes |
| grading (`LTR-5`, `live_review_outcomes`) | **grading**: every call (enter AND pass) scored on the replayed outcome of the structure it chose vs the best alternative; this file is what `comms/desk/outcomes.jsonl` has never had |

### 3.1 How triggers are chosen: from outcomes, not from the desk's taste
1. Replay the candidate detectors (today's five plus near-signal variants) over history on the desk symbols. For each firing, record the forward return distribution of the best structure, net of cost.
2. Keep a detector only if its firings beat the unconditional base rate by a registered margin, net of cost, out of sample (a pre-registered queue unit per detector family).
3. Use the desk's 188 decisions only as a SECOND signal ("does Claude agree"), never as the label.

## 4. The ladder
Stage 0: the trigger replay of § 3.1, and a replay of the entry review on those firings with a masked judge (the DESK-15/16 masked-judge harness, if it still runs). It passes on net R per call vs the unconditional entry of the same structure. Stage 1: demo floor (`bybit_1`), one or two clean trades, mechanics only (OPERATING-PLAN § 2). Real money: only through the existing desk real-money gate (DESK-13).

## 5. Capacity (arithmetic, not a forecast)
At today's caps (`max_per_day: 4` triggered plus a 2-hourly scan) the desk can wake about 16 times a day, about $6.9/day at $0.43. A trigger set that fires on 1 in 10 of today's packets would cut that by about 90 % while waking on the setups the replay says matter. The actual rate is what § 3.1 measures.

## 6. Questions for the operator (planning)
1. **Label source.** Grade by OUTCOME (proposed) or learn from the desk's own decisions (the row's phrasing)? With 17 positives and 0 outcomes, the second has nothing to learn from yet.
2. **Keep the periodic scan meanwhile?** All 17 entries came from it. Proposed: keep it at the 2-hourly cadence until a trigger set passes Stage 0, then drop it.
3. **Scope of v1.** Crypto desk symbols only (today's six), or include equities on Alpaca paper?
4. **The 0-of-72 triggers.** Retire the four detectors that never produced an entry now, or keep them as labelled negatives until § 3.1 grades them?

## 7. Build rows and queue units this would become (after § 6 is settled)
- unit: trigger-detector replay (§ 3.1), net of cost, per detector family, pre-registered.
- build: the entry packet (structures and their replayed base rates; reuse `live_review_outcomes` pricing).
- build: the desk outcome grader (fills `comms/desk/outcomes.jsonl` for every past and future call).
- unit: masked-judge replay of the entry review on the kept triggers (§ 4).
- build: the trigger set in `config/desk_triggers.yaml` from the units' verdicts.
