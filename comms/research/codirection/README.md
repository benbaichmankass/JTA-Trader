# Co-direction live-journal export (RQ-20261119-f2a4-08)

`2026-11-19.jsonl`: every closed non-backtest trade on every book, 2026-09-01..2026-11-19, from the read-only diag journal,
in the `--journal` schema of `scripts/research/codirection_drawdown.py` (leg, entry_time, exit_time, direction, net_r).

**`net_r` here is NOT R.** It carries the journal's per-trade `pnl_percent` (return on notional), stamped on every row as
`y_kind: ret_pct_on_notional_not_R`. The journal's `stop_loss` is the current, possibly trailed, stop, so an R computed from
it would be biased; the unit's rule says so. No sizes, dollars, balances or account ids; `account_class` is paper / live only.
