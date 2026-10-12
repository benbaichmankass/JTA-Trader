# REDUCE-FILL-QTY — why intent-reduce legs filled short, and what PR #17691 changes (2026-10-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Written 2026-10-12 by lane `REDUCE-FILL-QTY` (session_013PGJqGxzyzKVSSFydXA9U5,
dispatched by manager session_01G16FfyYSmDPQuuW55BuTmK). Pipeline item
`PI-20261011-YJAYF7GD-0001`; checklist row `REDUCE-FILL-QTY`; fix PR #17691.

## Sources and population

- Journal: the diag relay's `journal?table=trades`, every page. That is
  **6,576 rows**, pulled 2026-10-12 at about 06:00Z.
- Venue fills: `/api/bot/pnl/exchange/fills?days=90`, pulled separately for
  each account × symbol. The five pulls (bybit_1 SOL, ETH, BTC, XRP and
  bybit_portfolio XRP) **all came back `truncated: false`**, so each is
  complete for its 90-day window.
- Venue positions: `/api/diag/exchange_positions`, taken at
  2026-10-12T06:01:30Z.

Of the **114** `exit_reason='intent_reduce_executed'` legs, **71** could be
matched by orderId (`notes.trade_id`) to a fill I pulled. Of those 71:

- **57** filled the full request;
- **9** filled short;
- **5** had no fill in the store.

The other 43 legs either predate the window or are on account × symbol pairs I
did not pull. All 9 short fills date from 2026-07-24 to 2026-08-08. All 35
matched legs after 2026-08-08 filled the full request.

## Root cause: the venue cut the order, so there was no partial fill and no unit mismatch

For each case I rebuilt the venue position from the live position, subtracting
the signed fills since the reduce. In **9 of 9** cases, the position just
before the reduce equalled the filled qty, and just after it was **exactly
0.0**. Each case has exactly one fill.

A Bybit reduce-only order is cut down to the size of the position it reduces.
These orders were cut because the journal was already holding units the venue
had already closed. Example: in bybit_1 4358 the bot asked for 0.839 BTC and got
0.01. Parent 4324 (3.199 BTC) had been closed at the venue 33 h earlier, by an
unattributed sell on 2026-08-02 at 13:39:53 at 62971.6. Its journal row stayed
open and was later booked as `tp` at +1024.55.

| row | account | symbol | requested | filled | venue before → after | journal net before |
|---|---|---|---|---|---|---|
| 4518 | bybit_1 | SOLUSDT | 1543.2 | 4.6 | 4.6 → 0 | 2075.2 |
| 4418 | bybit_1 | ETHUSDT | 71.75 | 0.32 | −0.32 → 0 | −78.46 |
| 4358 | bybit_1 | BTCUSDT | 0.839 | 0.01 | 0.01 → 0 | 3.209 |
| 4311 | bybit_1 | ETHUSDT | 70.75 | 3.16 | −3.16 → 0 | −117.62 |
| 4192 | bybit_1 | SOLUSDT | 133.7 | 11.7 | 11.7 → 0 | 1368.7 |
| 4153 | bybit_1 | XRPUSDT | 35861 | 32059.8 | −32059.8 → 0 | −136280.9 |
| 4133 | bybit_1 | ETHUSDT | 60.53 | 16.5 | −16.5 → 0 | −97.8 |
| 4102 | bybit_portfolio | XRPUSDT | 56210.9 | 40530 | −40530 → 0 | −108824.4 |
| 3995 | bybit_1 | XRPUSDT | 25609.2 | 6438.7 | 6438.7 → 0 | 142432.8 |

All 9 are on paper accounts (`account_class=paper`). None are on bybit_2.

## No divergence now

I compared the journal's open rows (`status='open'`, `is_backtest=0`, signed net
per account × symbol) with `exchange_positions`, both taken at about 06:00Z on
2026-10-12. **7 of 7** open account × symbol pairs on the three Bybit linear
accounts **match exactly**:

- bybit_1 ADAUSDT, BNBUSDT, BTCUSDT, XRPUSDT;
- bybit_2 ADAUSDT;
- bybit_portfolio ADAUSDT, XRPUSDT.

No open position is affected today.

## The change (PR #17691, `src/units/accounts/execute.py`)

**Reading the fill.** After placing a reduce-only order, `execute_pkg` calls
`read_reduce_fill`. It is read-only: it asks `get_open_orders` and then
`get_order_history` for the order by orderId. If the order is not yet terminal
it tries again, up to 3 reads at 0.25 s apart. It returns one of three states:
`filled`, `short_fill` or `unknown`.

**Sizing the shrink.**

- On `filled` or `short_fill`, the parents shrink FIFO by the **filled** qty.
  The audit row's `position_size` is set to the filled qty.
- On `unknown`, the parents shrink by the **requested** qty, which is the
  behaviour before this change. A reduce-only fill can never exceed its request,
  so the request is an upper bound. Skipping the shrink instead would re-send
  the same reduce on the next tick (the #5101 churn loop).

**Reporting a short fill.** It logs a WARN and reports a `reduce_short_fill`
outcome.

**New fields in the audit-row notes:**

- `reduce_fill_state`
- `reduce_requested_qty`
- `reduce_filled_qty`
- `reduce_unfilled_qty`
- `reduce_fill_avg_price`
- `reduce_fill_reason`

Orders that are not reduce-only are unchanged, and the change makes no extra
venue call for them.

**A consequence to weigh.** After a short fill, the journal keeps the phantom
units until the monitor closes those rows. In the measured cases that took
about 8 minutes. In that gap the intent layer may send another reduce. The venue
is flat on that book, so Bybit refuses it and no units move, but each refusal
writes an `exchange_rejected` row.

**Revert:** `git revert` the PR's commits. No config, schema or stored state
depends on the change.

## Backfill

No backfill is needed for positions: the divergence is 0 and every affected
parent is closed. The 9 reduce rows already carry
`reduce_settlement=unverified` with the reason `fill_qty_mismatch`, and their
`pnl` is NULL. That record is accurate, so it stays as it is.

The P&L that is actually wrong is on the 9 phantom parents. They were later
closed with prices from `candle_at_close` / `local_markprice`, on units the
venue had already closed, and together they booked +538.30. That is filed as
`PI-20261012-FYDXA9U5-0001`.
