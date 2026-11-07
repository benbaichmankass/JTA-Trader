# ml_entry_eq with the live structure exit — grade and Tier-3 proposal (2026-11-07)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · Tier 3 (HELD, operator decides) · lane ML-ENTRY-EQ-STRUCTURE-RETEST
> Gates this adds or changes: none.

## 1. Grade (rule applied from the record, not from the runner's verdict)

Record: `research/results/RQ-20261106-98e3-01/42315121734.jsonl` (run 42315121734). Rule: `RULE-RQ20261106-98e3-01-ENTRY-EQ-STRUCTURE`.

| Clause | Required | Measured | Met |
|---|---|---|---|
| n >= 30 | 30 | n = 570 trades / 140 symbols (pool 173) | yes |
| (a) confirm mean net R >= t_min(N=2) x iid se | 0.5198 x 0.0462 = 0.024 | +0.2123 net R (gross +0.2618, cost 0.0495) | yes |
| (b) dev OOF mean at selected tau > 0 | > 0 | +0.1222 (tau 0.20, n=3004, 157 symbols) | yes |
| (c) confirm mean >= 0 | >= 0 | +0.2123 | yes |

**PASS, confirmed.** Ledger N=2 (second read of the 2025-07-15..2026-10-31 window), booster sha256 `90329845d55d7dfa...`, 368,757 training rows, config B, structure exit `pivot=5;sl_only`, TP fixed 3 ATR, SL 2 ATR.
Compare: the fixed 2/3 ATR bracket model read +0.0392 (n=858), so the structure-trained model reads +0.17 R higher on a different trade set.

## 2. Honest read (what the PASS does and does not say)

- **Significance:** iid t = 4.6, but trades cluster in time. Month-clustered se 0.105, so t = 2.02. The N=2 deflated *point* bar is cleared. The deflated CI bar (z 2.239) is NOT cleared on the clustered se: 0.2123 - 2.239 x 0.105 = -0.023. It is a holdout pass under the registered point rule, not a statistically proven edge. DSR is probation (OPERATING-PLAN § 2).
- **Concentration (computed from `by_month`):** 11 of 16 months positive. Dropping 2026-03 (n=166) leaves n=404, mean +0.192; dropping 2026-03 and 2026-01 (n=116) leaves n=288, mean +0.223; dropping those two plus 2025-08 leaves n=226, mean +0.200. The result does not depend on any single month. Sparse months with n<=11 are noisy (2025-07 -1.12 n=5, 2025-12 -0.72 n=11, 2026-06/07 n=1).
- **Per symbol:** the 10 most-traded symbols each have n 7-12 (top-10 means -0.15..+0.56; 8 of 10 positive). Per-symbol results never gate (CLAUDE.md, "An account configures strategies, never symbols").
- **Dev folds are not uniformly positive:** 5 dev folds read +0.197, +0.245, -0.051, -0.222, +0.332 (pooled +0.122). The tau grid is monotone up to its edge (0.05 -> +0.054 ... 0.20 -> +0.122): the selected tau is the grid boundary, so a higher tau was never tested.
- **Declared limits of the arm:** TP fixed at 3 ATR (live `ml_entry` also has an `ml_first_passage` tp_revision; `ml_entry_eq` does not); slippage is PROVISIONAL (5 bps); structure levels use each ETF's own 1h RTH bar sequence.

## 3. The proposal (Tier 3, NOT merged by this lane)

**Pre-requisite found while writing this — the served model is not the graded model.** `ml_entry_eq` on `alpaca_paper` serves the fixed-bracket booster `af4835e29fe83c86` (config/strategies.yaml `ml_entry_eq`, `ml/candidates/ml_entry_eq_v1`). The PASS above is for a *re-trained* booster (`90329845d55d7dfa`). Setting `structure_exit` on the existing leg would put the live exit on a model trained for a different exit. Order of work:

1. **Export** (Tier 1, queued here as `RQ-20261107-98e3-02`): deterministic refit with `--structure`, expected sha `90329845d55d7dfa`, writes `model.json` + `parity_fixture.json` for the serve-parity step (`docs/research/ml-entry-eq-serve-spec-2026-11-06.md`).
2. **Serve** the structure model as a NEW candidate id (do not overwrite `ml_entry_eq_v1`) and pass the serve-parity fixture.
3. **Config** (Tier 3), after 1-2:
   - `config/strategies.yaml::ml_entry_eq`: add `structure_exit: "pivot=5;sl_only"`; keep `atr_stop_mult: 2.0`, `tp_r: 1.5`, `model` -> the structure model id, tau 0.20, restricted long.
   - `config/accounts.yaml`: add `ml_entry_eq` to `alpaca_live.strategies` (real money, `side_filter: long` already matches the long-only model) and to `alpaca_portfolio.strategies` (Stage 2 is one stage; the mirror is a superset, `tests/test_paper_portfolio_accounts.py`). `alpaca_paper` keeps the leg as the Stage-1 mechanics floor.
   - **Symbols:** an account configures strategies, never symbols. The leg's population is the tested 173-ETF pool limited to what Alpaca can trade. The currently-rostered 10 (SPY QQQ IWM TLT IEF SLV USO GDX TQQQ QLD) are a tick-cost rollout stage, not the tested population; widening to the whole pool needs the tick-duration measurement already named in the leg's comments.
   - **Affordability / per-symbol cost: NOT MEASURED here.** `alpaca_live` risk is `risk_pct 0.02`, `daily_usd 200`, `daily_dd_switch armed 0.03`; the account balance is not in the journal snapshots (ALPACA-LIVE-ACTIVITY-ML note: snapshots carry no balance) and I did not read it live. Whole-share sizing means a symbol is affordable only if 2% risk / (2 ATR14 stop distance) buys >= 1 share; the existing affordability-proxy mechanism (full-size underlying, sub-$100 proxies SPYM/IAUM/SCHA) covers the expensive ones. The cost basis tested is slippage 5 bps (PROVISIONAL) + 0.5 bps regulatory, fee 0, per symbol identical. A real per-symbol slippage read comes only from the first fills.
4. **Verification watch (first 1-2 live trades, mechanics only, not edge):** entry fills at the next RTH open within the bracket; SL 2 ATR and TP 3 ATR rest at the venue; the structure verdict tightens the stop only (never looser than the entry stop, `structure_sl_cross` closes at price); no zombie OCO; journal row carries `ml_entry_eq` and the model id; realized slippage vs the 5 bps assumption.

**Revert:** delete `ml_entry_eq` from `alpaca_live.strategies` and `alpaca_portfolio.strategies` (one line each); remove `structure_exit:` from the leg; the fixed-bracket model stays on `alpaca_paper`.

## 4. Why this holds under the rules

Holdout governs real money (OPERATING-PLAN § 2, 2026-11-06): the configuration chosen on dev cleared its registered rule on held-out data net of the full cost stack (committed record above); DSR is probation; paper is not a gate. Mechanics are proven for Alpaca equities by `tqqq_trend_long_1d` on `alpaca_live`; the ML leg's own mechanics are proven on `alpaca_paper`. Not claimed: statistical significance on the clustered se, or a measured affordable symbol set.
