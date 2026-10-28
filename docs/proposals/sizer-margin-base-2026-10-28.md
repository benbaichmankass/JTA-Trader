# Tier-3 proposal — size Bybit linear risk on the margin balance, not on total equity

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current** (a proposal; the operator decides on Thursday planning)

**Status:** PROPOSED — **no code changed.** Tier 3 (sizing). The operator decides on Thursday planning.
**Lane:** `BYBIT1-AVAILABLE-USD-ZERO` (2026-10-28). Row: `SIZER-MARGIN-BASE`.
**Numbers are deliberately absent from this public file.** The per-account figures were reported to the manager only. Re-measure with the commands under "Evidence".

## The question

For every account: what base does the coordinator size and budget against, what is the venue's real margin base, how far apart are they, and what leverage does the sizer assume against what the venue applies?

## What the code does today (read from the code, 2026-10-28)

| Account family | Risk-sizing base (`balance_usd`) | Margin cap base (`available_usd`) | Source |
|---|---|---|---|
| Bybit linear (`bybit_1`, `bybit_2`, `bybit_portfolio`) | **sum of `usdValue` over every coin in the UNIFIED wallet** (so total equity, incl. coins that are not margin collateral, net of borrow) | venue `totalAvailableBalance` (state `venue_available`), else coin-derived / deprecated fallback | `data_loaders.account_balance_with_diagnostic` (bybit branch), `execute.read_linear_available_balance` |
| Bybit gate / budget (`total_account_usd`) | `totalEquity` | — | `execute._fetch_linear_total_equity` |
| Alpaca (`alpaca_paper`, `alpaca_portfolio`, `alpaca_live`, `alpaca_options_paper`) | account **equity** (`client.balance()`) | Reg-T buying power (`client.buying_power()`), leverage left unset on purpose | `data_loaders._m15_client_balance_diagnostic`, `alpaca_client.buying_power` |
| IB (`ib_paper`, `ib_live`) | `net_liquidation` (else `available_funds`) | none (futures path, whole contracts) | `data_loaders` IB branch |
| Prop (`breakout_*`, `tradeify_1`, `velotrade_1`) | the operator-reported account snapshot (`prop_sizing_balance`); no venue margin concept | none | `coordinator._prop_sizing_balance_or_refuse` |

Risk per trade is `risk_pct × balance_usd ÷ stop distance`. The margin cap only ever REDUCES that quantity; it never raises it. The `gate_balance` (`total_account_usd`) is used in `position_size` only for the non-positive check.

## Measured gap, per account (2026-10-28 ~20:40Z; figures omitted)

| Account | Sizing base vs venue margin base | Gap | Config leverage vs venue |
|---|---|---|---|
| `bybit_1` (demo) | total equity vs `totalMarginBalance` | **large**: BTC and ETH sit in the wallet with `collateralSwitch=false`, USDT is net-negative (borrow), so margin balance is roughly a third of equity | config 10 (raised from 3 on 2026-10-27 ~22:10Z, row `BYBIT1-MARGIN-STARVED`); venue 10 on the open positions |
| `bybit_2` (real money) | equity vs `totalMarginBalance`: **the venue returns the field EMPTY** (read state `coin_derived`) | **unmeasurable from the field**; the coin block shows USDT with collateral on and a dust BTC balance | config 3 |
| `bybit_portfolio` (demo) | equity equals `totalMarginBalance` | **none** | config 3 |
| `alpaca_*` | equity vs Reg-T buying power | not a like-for-like gap (buying power is a leveraged capacity, deliberately fed to the cap) | n/a, leverage unset by design |
| `ib_paper` / `ib_live` | `net_liquidation` | **no venue margin figure is exposed on any diag route**: UNMEASURED, not zero | n/a |
| prop (4) | operator snapshot | no venue margin base exists | n/a |

Only `bybit_1` has a measured gap, and its cause is a wallet configuration (collateral switch off), which the `set-bybit-collateral-switch` action is built to correct.

## Why `bybit_1` refused at 0.00 (revised)

At the time of all eight refusals the config and venue leverage were 3. The open book's notional was above 115k in every case, so initial margin at 3× (about a third of that) exceeded the margin balance, and available read 0. The leverage change to 10 on 2026-10-27 cut that margin requirement by 3.3×. **This replaces my earlier "sizer assumes 3× vs venue 10×" statement, which was wrong for `bybit_1` once the config changed.** The margin balance at the eight historic instants was not read, so the match is inference from notional and the config of the day, not a measurement.

## Proposed fix (Tier 3, for the operator to approve or decline)

1. **Field:** for `market_type: linear` Bybit accounts, size on `min(totalEquity, totalMarginBalance)` when `totalMarginBalance` is a non-empty number; otherwise keep today's behaviour.
2. **Where:**
   - the sizing balance: `src/units/ui/data_loaders.py` bybit branch (`total = sum(usdValue)`), but applied only on the coordinator's sizing path so dashboards keep showing equity — i.e. in `src/core/coordinator.py` where `balance` and `total_account_usd` are set for linear accounts (about lines 1931–1990), using `read_linear_margin_fields` (already in `execute.py`);
   - `execute._fetch_linear_total_equity` (reads `totalEquity` first).
3. **Effect on position size, per account:**
   - `bybit_1`: risk per trade falls in proportion to margin balance ÷ equity while the collateral switch stays off; once BTC and ETH collateral is ON the two figures converge and the change is close to a no-op. It protects against the switch drifting back.
   - `bybit_2`: no change (field empty → fallback). **Do not rely on this for real money**; the empty field is its own finding.
   - `bybit_portfolio`: no change (margin balance equals equity).
   - Alpaca, IB, prop: no change.
4. **Evidence required before approval:** a replay over `bybit_1`'s last 30 days of intents comparing sized qty on the current base against `min(equity, margin balance)`, net of the cost stack; and a read of `bybit_2`'s margin fields to explain the empty value. Neither has been run.
5. **Revert:** restore `balance` to the `usdValue` sum and `total_account_usd` to `totalEquity` in the coordinator; one commit, no data migration.

## Recommendation

Do the collateral action first (PR for `set-bybit-collateral-switch`), re-read `margin_fields`, and decide this proposal only if the gap persists or recurs. If the gap is closed by the account action, this change has nothing to fix on the measured accounts; the remaining reason to build it is a guard against collateral drift.

## Evidence (re-run these)

- `scripts/ops/diag_fetch.sh 'broker_account_status'` — every account, with `margin_fields` (Bybit) and `status_flags.capacity` (Alpaca).
- `scripts/ops/diag_fetch.sh 'bybit_raw_positions?account_id=bybit_1'` — per-position leverage and `position_im`.
- `config/accounts.yaml` — `risk.leverage`, `risk.risk_pct` per account.
