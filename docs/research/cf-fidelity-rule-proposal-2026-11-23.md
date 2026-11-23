# Counterfactual fidelity rule: a proposal for the NEXT read (2026-11-23)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · rows `CF-FIDELITY-RULE-DECISION`, `CF-FIDELITY-ACTION-REPLAY`, `CF-BACKTEST-FIDELITY` (Tier 1 research; a proposal for the manager's Thursday decision, nothing here is applied)

## Gates this adds or changes

None. This is a PROPOSAL. The registered rule (`abs_gap_r <= 0.10` on >= 80% of graded, per leg, n >= 10; `cf_bulk_live.py`, design § 3.4) is NOT changed retroactively; every number below was measured under it and stays published under it. A revised rule would apply only to a read registered BEFORE its run.

## What the data says about the registered rule (population stated per line)

| population | within 0.10 R | note |
|---|---|---|
| live + paper closed packages, 992 graded of 2,733 (journal as of 2026-11-23) | 29.2% -> 41.3% after action replay | independent bracket exits n=618: 45.2%; circular journal-close n=374: 35.0% |
| ... of which exit type matched (sl->stop, tp->tp), n=566 | 48.1%, median gap 0.105 R | the gap is fill slippage + cost-model difference, not management |
| backtest corpus, 400-job same-jobs sample (before / after the sidecar fix / after the timeout replay) | 46.8% -> 80.7% -> 87.3%; median 0.187 -> 0.003 R; p90 2.22 -> 0.27 R | trail_stop 8% -> 86%, timeout 10% -> 100% (n=29); stop exits unchanged ~90%; stale/tp/be (n=9) not modelled |

Reading: on the backtest corpus the rule is meaningful and, after the fix, near its bar. On live packages the 0.10 R tolerance sits at the cost floor (median 0.105 R for exit-type-matched packages), so the rule there measures slippage, not engine fidelity.

## Proposal (for the NEXT registered read; thresholds are suggestions to be fixed BEFORE it runs)

1. **Split the question in two, keep both numbers.** (a) *Mechanics fidelity*: the replay's exit REASON class (stop / target / managed) and exit BAR match the recorded exit, >= 80% per leg; price-free, so slippage cannot fail it. (b) *Price fidelity*: gap NET of the leg's measured slippage, i.e. `|replayed_net_r - (actual_net_r + measured_slippage_r)| <= 0.10`, where `measured_slippage_r` comes from `realized_slippage.py` per venue (MEASURED). Live packages need (b), backtest rows already carry their slippage in `net_r`. <!-- population-ok: the 80% is the registered rule's threshold over graded rows per leg (n >= 10), not a measurement -->
2. **Per-exit-type tolerance on live packages.** Bracket exits: 0.10 R + the leg's p50 measured slippage R. Non-bracket exits (reconciler fill, reduce, review close) are reported SEPARATELY and never pooled into the pass rate, because replaying them is circular (the replay is told when the trade ended); they stay in the table with their own count.
3. **Report the unreplayable share.** A package or job whose exit the engine cannot model (stale/break-even/giveback levers, partial reduces) is counted `exit_not_modelled` and shown beside the rate, so a high pass rate over a small modelled slice cannot read as fidelity of the whole.
4. **Keep the denominator honest.** Rate over graded rows; `could_not_grade` by reason printed with it (symbol/timeframe/bar-source). A leg is `INDETERMINATE` below n = 10 as now.
5. **Baseline for BT arms.** Read arms against the replayed harness trade (`bt_vs_replay`, now emitted beside the registered `bt` verdict by `cf_bulk.py`); `original_brackets` stays as the registered comparison until the revised rule is registered.

## What is NOT proposed

Lowering the 0.10 R tolerance or the 80% share to make today's data pass. The numbers above are the baseline a revised rule is registered against. <!-- population-ok: the 80% is the registered rule's threshold over graded rows per leg (n >= 10), not a measurement -->
