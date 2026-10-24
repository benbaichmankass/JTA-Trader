# MGC sizing oversize — ict_scalp_mgc_15m on ib_paper (2026-10-24)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane MGC-SIZING-OVERSIZE; measured 2026-10-24 via `scripts/ops/diag_fetch.sh 'journal?table=trades&limit=400'`.

## Answer
The sizer did **not** misprice MGC. The INFERRED hypothesis (wrong point value / stop) is **refuted**:
`config/instruments.yaml::MGC.contract_value_usd = 10.0` (correct: 10 oz), resolved by `contract_value_usd_for()` in `RiskManager.position_size`.
96 and 150 are the correct output of "risk 1.5% of equity per trade" on a **very tight stop**, with **no notional / leverage ceiling anywhere** on `ib_paper`.

## Replay (journal rows, population: ib_paper `ict_scalp_mgc_15m`, rows 6603 and 6610)
qty = floor( equity × risk_pct / (|entry − sl| × 10) ), risk_pct = 0.015 (flat: `confidence_sizing` is unset → `off`).

| row | entry | sl | stop dist | $/contract at risk (×10) | qty | risk = qty × that | stop as % of price | notional (qty × entry × 10) |
|---|---|---|---|---|---|---|---|---|
| 6603 (13 Oct) | 4182.40 | 4171.554 | 10.846 | 108.46 | 150 | 16,269 | 0.26% | 6.27M |
| 6610 (14 Oct) | 4173.80 | 4157.093 | 16.707 | 167.07 | 96 | 16,039 | 0.40% | 4.01M |

Both rows risk ≈ the same dollars (16.3k / 16.0k) although confidence differed (0.465 vs 0.829) — confirming flat 1.5% basis. Implied equity ratio eq(6610)/eq(6603) = 0.986; the intervening -18,300 loss on 6603 is 1.7% of equity — consistent within the ±1-contract floor (±0.01%) plus other open P&L. The sizer is internally consistent. Absolute balance deliberately not printed (public repo).

So: stop 0.26–0.40% of price × ×10 multiplier → 1.5% risk budget buys notional ≈ 1.5%/0.26% = 5.8x and 1.5%/0.40% = 3.7x equity. That is the arithmetic of a tight-stop scalp with risk-based sizing, not a units bug. The -22,368 / -18,300 losses are exactly 1.5% × equity risked (+ slippage past the stop on `sl_cross`).

## Why nothing stopped it
1. `risk.py` module docstring: "There is NO position-notional ceiling" (operator directive 2026-06-24) — risk budget, margin ceiling, gross-exposure ceiling, lot size are the only bounds.
2. The gross-exposure ceiling (`max_gross_exposure_pct`, built 2026-08-07) is **unset on every account** in `config/accounts.yaml` (checked by parsing all 14 accounts).
3. **Latent second defect:** even if a ceiling were declared, it could not bind on futures. `_open_gross_notional_from_db` / `_open_notional_for_symbol` sum `qty × entry` (no multiplier) and the clamp is `headroom / entry` (no multiplier). MGC would be counted at 1/10 of true notional (MES 1/5). A "3x equity" ceiling would let ~30x through on MGC.

## Population check — other legs/accounts
Method: last 400 journal trades (ids 6334–6733), excluding rejected/exchange_rejected and rows without account; per account, implied equity = median(qty × |entry−sl| × cvu) / risk_pct; reported max(notional / implied equity). Rough (median-based, window-limited), but the contrast is large.

| account | class / mode | n | max notional ÷ implied equity |
|---|---|---|---|
| ib_paper | paper / live | 7 | **5.78** (ict_scalp_mgc_15m; 4 rows > 2x) |
| bybit_1 | paper / live | 193 | 2.38 (ict_scalp_sol_15m; 2 rows > 2x) |
| alpaca_paper | paper / live | 5 | 1.13 |
| bybit_2 | **real_money** / live | 18 | 0.87 |
| bybit_portfolio | paper / live | 19 | 0.82 |

Config reach: `ict_scalp*` legs are routed only to `ib_paper` among `*scalp*` strategies (parsed from `accounts.yaml`). Real-money (bybit_2, alpaca_live, ib_live [dry_run]) and prop (breakout_1/2, tradeify_1, velotrade_1) carry **no** `*scalp*` leg. **No real-money or prop account was measured exposed** (bybit_2 max 0.87x in this window; alpaca_live and the prop accounts had no rows in the 400-row window — "no rows" is *we did not measure*, not "safe"). **Structurally**, however, every account has the same absence of a ceiling and the same multiplier-blind exposure code, so the defect *class* is reachable by any future tight-stop leg routed to a futures account (ib_live is the real-money futures account, parked dry_run).

## Proposed change
**A. Code (held PR #19926, Tier-3):** multiply by `contract_value_usd_for(symbol)` in both notional measures and in the clamp. Byte-identical for no-ceiling accounts and for cvu=1.0 instruments. Test added.
**B. Config (operator decision, NOT drafted as a diff here):** declare `risk.max_gross_exposure_pct` on `ib_paper` (and, by the same logic, ib_live before it is ever armed). Evidence-based sizing: the gold backtest used ungated, per-contract economics; a ceiling of ~1.0–1.5x equity would cap ict_scalp_mgc_15m at ~25–40 contracts at today's price/stop. The value is a preference the data do not settle (this is a paper soak whose stated purpose is mechanics, 1–2 clean trades per the soak doctrine) — raise it as a decision, not a data task.
**Observation to close the row:** after deploy, `/api/bot/…` exposure block for ib_paper shows `max_gross_exposure_pct` set and the next ict_scalp_mgc_15m fill has `qty × entry × 10 ≤ ceiling × equity`.
