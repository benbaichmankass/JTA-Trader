# Journal `pnl` vs venue `closed_pnl`, per Bybit account (PNL-GROSS-VS-VENUE-6817)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `JOURNAL-TRUTH` (row `docs/claude/work/checklist/PNL-GROSS-VS-VENUE-6817.json`, roadmap `L-OPS`) · measured 2026-11-12
> Gates this adds or changes: none. This is a measurement and a Tier-3 proposal. Nothing here changes what is stored.

## Population

- **Journal:** `/api/diag/journal?table=trades&limit=600` (ids 6501–7100, read 2026-11-12 ~09:30Z). Closed, non-backtest rows on
  `bybit_1`, `bybit_2` and `bybit_portfolio` whose `closed_at` falls in [2026-10-28T00:00Z, 2026-11-12T09:00Z): **157 rows**.
  The window starts three weeks after the oldest row read (id 6501, opened 2026-10-07), so no row that closed in the window is cut off by the 600 limit.
- **Venue:** `/api/diag/bybit_raw_closed_pnl` (the raw `/v5/position/closed-pnl` records), per account × symbol
  (ETH, BTC, SOL, XRP, BNB, AVAX, ADA, which are all the symbols in the journal population), in 7-day chunks over the same window. Every chunk
  read `rows_returned` or `no_rows`. None read `could_not_look`, and none was page-truncated.
- **Match:** same account and symbol, venue `qty` == journal `position_size`, venue `updated_time` within 15 min of the journal `closed_at`,
  nearest first, one-to-one.
- **Venue fees + funding** are not served per record. They are derived as gross-from-the-record's-own-average-prices − `closed_pnl`.

## Result (MEASURED)

| account | journal closed | venue records | matched (journal pnl set) | Σ journal pnl | Σ venue closed_pnl | gap | venue-implied fees+funding | journal fee+funding columns | per-pair: journal == venue net / == venue gross / neither |
|---|---|---|---|---|---|---|---|---|---|
| `bybit_2` (real money) | 24 | 25 | 24 | −2.92 | −2.94 | +0.02 | 3.65 | 3.77 | **23** / 1 / 0 |
| `bybit_1` (demo) | 109 | 104 | 104 | 2682.82 | −2544.16 | +5226.98 | 4544.97 | 4500.26 | 0 / 25 / **79** |
| `bybit_portfolio` (demo mirror) | 24 | 24 | 23 | −1094.72 | −1822.70 | +727.98 | 1120.22 | 1139.02 | 0 / 11 / 12 |

Of the 91 "neither" pairs on the demo books (79 + 12), 90 have the journal `entry_price` differing from the venue `avg_entry_price`.
The other one is a row that already nets its close fee (`pnl_net_of_close_fees`). Of the demo gaps, fees + funding explain 4544.97 of 5226.98 (bybit_1). The remainder
(+682.01 on bybit_1, −392.24 on bybit_portfolio) is that entry-basis difference. **INFERRED:** the demo accounts net same-symbol
positions, so the venue's `avg_entry_price`, and with it `closed_pnl`, is a position average across sibling rows, not this row's entry.

## What this answers

1. **Is journal `pnl` gross or net? Both, depending on the account.** On `bybit_2` it is the venue's NET `closed_pnl`
   (23 of 24 rows carry `exit_price_source: bybit_closed_pnl`, `cost_source: broker`). On the demo books it is GROSS local compute from the
   row's own fills (`exit_price_source: exchange_fill`), with costs held separately in `fee_*_usd` / `funding_paid_usd`. Trade 6817 is a
   demo row, so its gross figure is the demo convention, not an outlier.
2. **Should every close take venue `closed_pnl`? No, not on a netting account.** On the demo books the record is position-averaged,
   and on 90 of 127 matched demo rows its entry is not this row's entry. The journal's own cost columns already agree with the venue-implied
   fees+funding to within 1–2% on all three accounts (4500.26 vs 4544.97, 3.77 vs 3.65, 1139.02 vs 1120.22). So per-row
   gross minus the row's own costs reconstructs the net without borrowing a sibling's entry.
3. **Which figure graders read: `net_r_label.net_r_for_trade` treats `pnl` as GROSS** and subtracts the fee and funding columns.
   On `bybit_2`, where `pnl` is already net, **costs are subtracted twice.** MEASURED over the 15 `bybit_2` `ml_entry` closes priced
   from `bybit_closed_pnl` (newest 600 rows): mean net R as computed today is **0.2193**, and with costs counted once it is **0.2994**, about
   0.08 R per trade understated. `src/runtime/ml_entry_live_monitor.py::assess` consumes exactly this, against a dev band of −0.041 R.

## DECIDED 2026-11-12 (operator decisions page w11)

The operator chose **"Yes: store the venue's net closed P&L where trusted"**, with the binding note *"Store the venue's always, it is the single source of truth and if we have a gap we need to understand why"*. That is NOT the own-fill-net recommendation below. `pnl` becomes the venue's net figure on every account (demo books included), our computed figure is kept beside it, and every gap is a diagnosis item. Built in PR #25270. The section below is kept as the proposal the decision answered.

## Proposal (Tier 3: the operator decides; nothing is changed by this document)

**Store `pnl` as NET on every account, computed per row as gross from the row's own fills − the row's own `fee_taker_usd` + `fee_maker_usd`
+ `funding_paid_usd`, and stamp `notes.pnl_basis: "net"`.** Keep the venue `closed_pnl` as a reconciliation check (`notes.venue_closed_pnl`)
on non-netting accounts, never as the stored figure on a netting one. Make `net_r_label.net_r_for_trade` read `pnl_basis` and add the costs back
before subtracting them, so a net row is never costed twice. The operator reads `pnl` as money, and real money already stores net. This makes
every account mean the same thing and removes the double count in one change.

Alternative, if the operator prefers: store GROSS everywhere (convert `bybit_2`'s `bybit_closed_pnl` path to gross = `closed_pnl` + its costs).
That matches `net_r_label` as written, but it changes the real-money figure the dashboard shows.

**Until one is chosen, the double count on `bybit_2` in `net_r_label` is live.** A `bybit_2` `ml_entry` net-R reading (for example an
`ENTRY_LIVE_NEGATIVE` flag) is about 0.08 R/trade too pessimistic, so it must not be read as a demotion signal.

## Re-run

Pull the journal, then the closed-pnl records per account × symbol × 7-day chunk, then match as in "Population":
`scripts/ops/diag_fetch.sh 'journal?table=trades&limit=600'` and
`scripts/ops/diag_fetch.sh 'bybit_raw_closed_pnl?account_id=<acct>&symbol=<SYM>&start_ms=<ms>&end_ms=<ms>'` (≤ 7 days per call).
