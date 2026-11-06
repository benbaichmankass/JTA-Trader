# Real-money legs on the trial ledger's DSR + BHY bar (2026-11-06)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-06` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `PROD-LEGS-DSR-DECISION` (row `docs/claude/work/checklist/PROD-LEGS-DSR-DECISION.json`, roadmap `L-LADDER`)

Gates this adds or changes: none. It applies the operator's decision below to the rosters. No bar, guard or mandate changes.

## The decision this applies

Operator, 2026-11-06 ~00:30Z, popup answer verbatim: **"Re-measure, then move (Rec.)"**. It answered: *"A lane re-runs the trial
ledger's DSR/BHY correction on today's real-money roster. Any leg that fails moves to the demo floor (paper), recorded as your
decision. A leg that survives stays. You get the list before it merges."* Source: `docs/audits/2026-11-01-from-scratch/AUDIT.md`
§ 1c and § 8 (`PROD-LEGS-DSR-DECISION`).

## Population

- **Real-money roster, re-parsed from `config/accounts.yaml` at `origin/main` 62bc82f01 (2026-11-06):** `bybit_2` =
  `xrp_pullback_2h, trend_donchian_eth_4h, trend_donchian_xrp_4h, ada_pullback_2h, trend_donchian_sol_prop, ml_entry`;
  `alpaca_live` = `iaum_pullback_1d`. Stage-2 mirrors: `bybit_portfolio` (strict equality with `bybit_2`) and `alpaca_portfolio`
  = `gld_pullback_1d` (iaum's full-size underlying, superset rule). Prop accounts (`breakout_2`, `tradeify_1`, `velotrade_1`) are
  out of scope, as the operator's min-size baseline exception.
- **Statistic:** `scripts/research/trial_ledger.py` re-run 2026-11-06 (output committed as `comms/research/trial_ledger.json`,
  `generated_at 2026-11-06T00:24:02Z`; 57 evidence records, 84 (leg, family) keys, 29 Stage-0 PASS, **0** survive). Same family
  and effective-N rules as the 2026-10-30 ledger (unchanged code). Each leg's per-trade series is its committed Stage-0 record's
  `source_run` (OOS trades, net of the full cost stack). **Survival = DSR > 0.95 AND BHY-haircut net expectancy > 0.**

## Per leg (MEASURED)

| leg | account | OOS n | configs | family N | DSR | t | BHY p_adj | BHY-haircut exp (R) | verdict |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| xrp_pullback_2h | bybit_2 + bybit_portfolio | 53 | 221 | 40 | 0.046 | 0.56 | 1.000 | 0 | **FAIL → bybit_1** |
| trend_donchian_eth_4h | bybit_2 + bybit_portfolio | 135 | 194 | 47 | 0.289 | 1.77 | 1.000 | 0 | **FAIL → bybit_1** |
| trend_donchian_xrp_4h | bybit_2 + bybit_portfolio | 46 | 185 | 52 | 0.062 | 0.85 | 1.000 | 0 | **FAIL → bybit_1** |
| ada_pullback_2h | bybit_2 + bybit_portfolio | 61 | 276 | 41 | 0.375 | 1.92 | 1.000 | 0 | **FAIL → bybit_1** |
| trend_donchian_sol_prop | bybit_2 + bybit_portfolio | 395 | 163 | 36 | 0.355 | 1.80 | 1.000 | 0 | **FAIL → bybit_1** |
| ml_entry | bybit_2 + bybit_portfolio | 907 | 1 | 1 | 0.839 | 0.98 | 0.328 | +0.037 | **FAIL → bybit_1** (DSR) |
| iaum_pullback_1d | alpaca_live | 8 | 62 | 35 | 0.394 | 2.02 | 1.000 | 0 | **FAIL → alpaca_paper** (already there) |
| gld_pullback_1d | alpaca_portfolio (mirror of iaum) | 8 | 85 | 49 | 0.337 | 2.02 | 1.000 | 0 | **FAIL → ib_paper** (already there) |

Machine-readable: `comms/research/PROD-LEGS-DSR-DECISION/per_leg.json`. No leg survives.

### `ml_entry`: how it was measured

The ledger lists `ml_entry` as `state: no_series`. Its evidence (`research/results/RQ-20261103-5e04-01/41823438321.jsonl`, arm F,
the live exit) commits a mean and no per-trade series, so the ledger cannot compute its DSR. This lane re-ran the same harness
(`scripts/research/ml_entry_tp_revision.py`, `evidence-extend-only --structure-sl pivot=5` logic, lightgbm 4.6.0 as pinned in
`requirements.txt`), on the same population (served ENTRY trades 2025-10-01..2026-09-30, the 5 bybit_2 symbols), and saved each
trade: `comms/research/PROD-LEGS-DSR-DECISION/ml_entry_armF_trades.jsonl`. **It reproduces the committed record exactly:**
n 907, arm F mean +0.03713 R, arm A +0.02713 R (record 0.0271). Per-trade SD 1.143 R, skew 0.87.
This repeats an arm that was already read on the held-out window. It is not a new variant. It was not logged through `holdout_lock`.

Family N: the ledger's own rule counts 1 config for `ml_entry`. **At N = 1, DSR = 0.839 < 0.95, so it fails.** Sensitivity:
N 2 → 0.679, N 3 → 0.550 (BHY haircut 0), N 5 → 0.414, N 11 → 0.257. Population for the larger N: `comms/research/holdout_reads.jsonl`
logs 2 ENTRY variants read on this same window, plus 11 reads of the window in total. No choice of N makes it survive.

## Open positions left as-is (MEASURED, `GET /api/bot/positions?include_paper=true`, 2026-11-06 ~00:35Z, journal status='open')

On the four accounts this changes, the only open positions are `ml_entry` BTCUSDT short on `bybit_2` (qty 0.002) and
`bybit_portfolio` (qty 0.694), both opened 2026-11-05 16:04Z. They are left to run to their venue brackets. No order is placed,
amended or cancelled. None of the other seven legs has an open position on these accounts.

## What changes

`config/accounts.yaml`: `bybit_2` and `bybit_portfolio` become `[]`. So do `alpaca_live` and `alpaca_portfolio`. The six crypto
legs are added to `bybit_1`. `config/strategies.yaml::ml_entry.account_symbols` gains `bybit_1` (the same 5 crypto symbols). Without
it, a scoped leg trades nothing on an account its map does not name. `scripts/ci/check_strategy_status.py`: its two
`DUAL_BOOK_EXCEPTIONS` entries (iaum_pullback_1d, ml_entry) go stale and are dropped, because the guard refuses stale entries. This
narrows the guard. It adds nothing to it. Accounts stay `mode: live`. No mode flip.

**Inferred, and to be decided:** after this lands no leg trades real money (0 production legs). This matches the audit's finding
that 0 of 28 Stage-0 passes survive the bar. It is a book-level outcome the operator should see stated.

Revert: `git revert` of the PR.
