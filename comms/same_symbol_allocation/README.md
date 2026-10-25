# comms/same_symbol_allocation/

Allocation-weights records for `same-symbol-allocation-guard` (`scripts/ci/check_same_symbol_allocation.py`). One `*.json`
per shared (account, symbol) leg set. Empty until the first is written.

```json
{"kind": "allocation_weights", "covers": [{"account": "bybit_1", "symbol": "XRPUSDT"}],
 "legs": ["trend_donchian_xrp_4h", "xrp_pullback_2h"], "weights": {"trend_donchian_xrp_4h": 0.5, "xrp_pullback_2h": 0.5},
 "inputs": ["src/runtime/allocator_ev.py EV_R", "allocator_soak contest rate", "head_to_head RQ-20261015-1631-02"]}
```

Weights are non-negative and sum to 1; `inputs` must name at least one existing allocator factor (`allocator_ev`,
`allocator_corr`, `allocator_soak`, `conviction_*`). Backtest quality (`scripts/research/same_symbol_head_to_head.py`) is one
input, never the whole basis. Accounts with per-strategy slice support (lane NETTED-SLICES) are exempt via
`SLICE_SUPPORT_ACCOUNTS` in the script, filled from that lane's real config field once it is on main.
