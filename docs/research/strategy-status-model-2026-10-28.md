# Strategy status model — measured effect of moving production legs off general paper (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `STRATEGY-STATUS-MODEL` (self-measured 2026-10-28; nobody else has verified it) · rule: [`OPERATING-PLAN` § 2 "Three strategy statuses"](../plans/OPERATING-PLAN-2026-09-21.md)

## What was measured

**Source (MEASURED):** `scripts/ops/diag_fetch.sh 'journal?table=trades&limit=5000'`, served by `https://ict-bot.duckdns.org`
at 2026-10-28 ~21:10Z. The route returned its 1000-row cap, the newest 1000 rows, spanning 2026-09-14 21:02Z to 2026-10-28 20:18Z.
So every row in the window below is inside the pull.

**Population:** `trades` rows with `is_backtest` false and `timestamp` in [2026-09-30 21:00Z, 2026-10-28 21:00Z), 28 days, **n = 439**.
"Production legs" are the legs on a real-money roster on this branch, re-parsed from `config/accounts.yaml`. They are the five
`bybit_2` legs (`xrp_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `ada_pullback_2h`, `trend_donchian_sol_prop`)
and the one `alpaca_live` leg (`iaum_pullback_1d`). Current rosters were applied to the whole window, which is what the move
removes going forward.

## Duplicate trades removed

| account | leg | trades (28 d) |
|---|---|---|
| bybit_1 | ada_pullback_2h | 7 |
| bybit_1 | trend_donchian_eth_4h | 5 |
| bybit_1 | xrp_pullback_2h | 5 |
| bybit_1 | trend_donchian_sol_prop | 4 |
| bybit_1 | trend_donchian_xrp_4h | 1 |
| alpaca_paper | iaum_pullback_1d | 1 |
| **total** | | **23 ≈ 5.75 / week** |

Cross-check: 7+5+5+4+1+1 = 23. These 23 are 23 of the 349 general-paper trades in the window (bybit_1 250, ib_paper 65,
alpaca_paper 34), about 6.6%. The same legs made 22 trades on `bybit_2` and 22 on `bybit_portfolio` over the window, plus 3 on
`alpaca_live`.

## Data lost by the move

The test: a general-paper production-leg trade whose `order_package_id` has **no real-money sibling** is a trade that only the paper
book recorded. **2 of the 23** fail it:

- `bybit_1 trend_donchian_sol_prop` SOLUSDT long, 2026-10-20 15:01Z, package `pkg-505d4f56b87440c8`, SL exit. `bybit_2` and
  `bybit_portfolio` already held the 14:12Z package `pkg-6b47758541e247a5`.
- `bybit_1 xrp_pullback_2h` XRPUSDT short, 2026-10-19 00:20Z, package `pkg-de411e2dd4a245ea`, SL exit. Real money held the 10-18
  11:57Z package `pkg-f9b4dcef5b3741fd`. The bybit_1 close was journaled `closed_by: monitor_reconciler`, a reconciler close; the
  orphan-close incident record is `.github/pr-landing/xrp-orphan-close-1018.json`.

**INFERRED cause:** `bybit_1` runs `position_model: slices`, so it can hold a second package on a symbol. `bybit_2` and its mirror do
not (pick-one). The lost data is **re-entry while the real-money book is already in the symbol**, about 0.5 trades/week across the five
legs. It is **not** a sizing loss. No production leg in the window had a trade that real money was too small to place while paper took
it. The reverse happened 4 times: 2 `bybit_2` `xrp_pullback_2h` trades and 2 `alpaca_live` `iaum_pullback_1d` trades had no
general-paper sibling. Once `bybit_2` + `bybit_portfolio` move to slices (row `NETTED-SLICES`), the gap closes.

`iaum_pullback_1d`: `alpaca_live` traded it 3 times and `alpaca_paper` once. The mirror excludes it by the affordability carve-out, so
after the move its only record is real money (operator question 2 in the plan).

## Method (reproducible)

```python
# rows = json.load(open(<diag pull>)); window = 28 d to 2026-10-28T21:00Z; is_backtest false
# dup = trades on {bybit_1, alpaca_paper, ib_paper} whose strategy_name is a production leg
# lost = dup rows whose order_package_id has no row on {bybit_2, alpaca_live}
```
