# comms/same_symbol_allocation/

Committed head-to-head evidence records for `same-symbol-allocation-guard`
(`scripts/ci/check_same_symbol_allocation.py`). One `*.json` per measured leg set. Empty on purpose until the first
unit (`RQ-20261015-1631-0x`) lands.

A record is the `head_to_head.json` that `scripts/research/same_symbol_head_to_head.py` writes, plus:
`harness` (must name `backtest_system`), `covers: [{account, symbol}, ...]`, `legs`, `verdict: pass`, `winner`.
Commit the one the unit's landed result produced; do not hand-write one. Operator rule, 2026-10-15: measure the
allocation, never let it fall through to the strategy name.
