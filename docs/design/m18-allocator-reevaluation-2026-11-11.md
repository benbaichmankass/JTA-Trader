# M18 allocator — re-evaluation (proposal)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · row `M18-ALLOCATOR-REEVALUATE` · GENERAL lane · 2026-11-11 · PROPOSAL: decides nothing; the operator or the manager chooses.

**Gates this adds or changes:** none (proposal). The one code change shipped with it is a grading fix in an observe-only record (below).

## The question (operator, 2026-11-11 12:50Z)
The operator does not recognise "arbitration soak", thinks it is legacy, and wants the item re-evaluated. Milestone M18's `next` reads: *"Observe arbitration_fanout_soak writing again (E50); only then reopen the allocator proposal."*

## What was measured (2026-11-11, ~19:05Z)
| fact | value | source |
|---|---|---|
| `arbitration_fanout_soak.jsonl` still written? | **Yes.** 1,869 lines (2.19 MB); 42 rows on 2026-11-11, the newest at 18:58:51Z | `/api/diag/log_file` via the `vm-diag-snapshot` relay (issues #24909, #24912) |
| What it is now | **Not a soak.** Since E35 (2026-09-25) it is the per-tick record of each account's own strategy election, and the input of `starved_account_alert`: the live tripwire for "no account that elected a winner is left without a round" | `src/runtime/arbitration_fanout_soak.py` docstring |
| Can the tripwire see? | **Mostly not.** On 2026-11-11, 44 of 48 per-account gradings read `unknown` (4 `routed`, 0 `starved`). 2026-11-09 15:00Z to 11-10 15:45Z (48 rows visible of the last 100): 55 `unknown` of 65 | same rows |
| Why | NETTED-SLICES slice accounts carry plan state `allocated` (`arbitration_fanout._plan_slice_account`), which the grader's map did not know, so it fell to `unknown`. All 44 of today's `unknown` gradings were accounts that **were** in a planned round. That they were `allocated` rows is INFERRED from the code path: the logged row does not carry the raw plan state | code + the 42 rows |
| Starved alerts ever fired | 0 rows of kind or body `starved` in the alert ledger (whole ledger: 2,341 rows scanned, not truncated) | `GET /api/bot/alerts` |
| Allocator shadow soak (`allocator_soak.jsonl`) | **Live.** 680 decision rows with ≥ 2 candidates on one symbol. The allocator's top pick differs from what was routed on **195 (28.7 %)**, mean regret 0.40. On the newest 100 rows (2026-10-26 to 2026-11-11): 29 disagree, median regret 0.93, max 3.83. Top pairs: BTCUSDT `trend_donchian_1h`→`trend_donchian` 7, MGC `mgc_pullback_1d`→`mgc_trend_1h` 6, ETHUSDT `eth_pullback_prop_2h`→`eth_pullback_2h` 4, ETHUSDT `trend_donchian_eth`→`trend_donchian_eth_4h` 4 | `GET /api/bot/allocator/soak` |
| What "regret" is | The allocator's **own** `ev_net_r` score of its pick minus the score of the routed one. It is self-referential: it says the scorer prefers another candidate, **not** that the other candidate would have made more money | `src/runtime/allocator_soak.py` |

## Proposal: RE-SCOPE (keep the record, retire the gate, test the allocator on outcomes)
1. **Keep the election record, rename it in prose.** It is not legacy. It is the only durable per-tick trace of what each account elected, and the starved tripwire's input. Call it the **account-election record** in docs and on the milestone. File and module names stay, like every other runtime identifier.
2. **Fix the blind spot (shipped in this PR).** `allocated` now grades `routed`. A slice account that is `allocated` but in no round grades `starved`, the defect the tripwire exists for. Re-graded over today's 42 rows, this changes 44 `unknown` to `routed` and 0 to `starved`, so no alert would have fired.
3. **Retire the gate.** M18's `next` ("observe … writing again (E50)") is met: it writes every few hours. Proposed `next`: *"Grade the allocator's disagreements on outcomes."* Changing the milestone text is the manager's roadmap act; this doc only proposes it.
4. **Re-scope the allocator question to an outcome test.** Pre-register a research unit over the 195 disagreements. For each, price both the routed candidate and the allocator's pick on the same replay and the full cost stack, then ask whether the allocator's picks would have made more net R, by enough and across folds. This is where M18 meets perf-followup Track 4 (overlap, concentration, sizing vs contribution) and `L-ML-AGGREGATOR` (the position aggregator). The unit is the next build, not part of this PR.
5. **Do not** turn the allocator on for routing on the strength of the 28.7 % / 0.40 regret. That number comes from the scorer grading itself.

## Alternatives considered
- **Retire M18 entirely.** That would drop the only shadow evidence of how often strategies contend for one symbol (680 decisions), and the tripwire the routing relies on. Not recommended.
- **Keep as is.** It leaves a gate that is already met and a tripwire that is blind on slice accounts. Not recommended.
