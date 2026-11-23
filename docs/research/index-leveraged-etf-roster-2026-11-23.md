# Index leveraged + inverse ETF roster proposal — 2026-11-23

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `INDEX-LEVERAGED-ETF-ROSTER-20261123` (manager Session 2026-11-22a)
>
> **Gates this adds or changes:** none. Proposal only; no config edited. The config change in § 5 is **Tier 3** and waits on a Stage-0 pass.

Operator ask (2026-11-23, verbatim excerpts): *"we don't trade short on that account ... we're supposed to be trading different types of leveraged ETFs ... if the S&P 500 or Nasdaq go down, then those stocks will go up ... trade them through buy orders, in both directions of the market."*

## 1. State (read-only; provenance in brackets)

| Finding | Value |
|---|---|
| Owner of the ~200-symbol list at `config/strategies.yaml` ~line 1604 | `ml_entry_eq_struct` (`pool_scored: true`, `execution: live`, side **long**). [MEASURED: file read] |
| Is the inverse set inside its registered pooled population? | **Yes.** The artifact's `pool_symbols` (173 ETFs, `ml/candidates/ml_entry_eq_v3_struct_ens5/model.json`) contains SQQQ, SPXU, SPXS, SH, SDS, PSQ, QID, SDOW, TZA, SOXS, DUST and UPRO, SSO, SPXL, UDOW, TNA, QLD, TQQQ. It does **not** contain DOG, DXD, RWM, TWM, DDM, UWM (fail the pool's ≥ 50 M USD median daily dollar volume rule, 2019-20). [MEASURED: json read] |
| Pass record | RQ-20261107-98e3-06: n 207, net +0.4922 R at the confirm read (whole pool). No subset read exists. |
| Has an ML leg ever TRADED an inverse ETF? | Only **TZA** (1 trade, `alpaca_portfolio`, closed −41.99 USD; its `alpaca_live` twin was rejected). Population: last 1000 journal trade rows via `diag_fetch journal?table=trades`, 2026-11-15..2026-11-23 (cap of the endpoint; an older window was NOT read, so "never" is not claimed). [MEASURED] |
| Other leveraged index ETF rows in that window | UPRO, SPXL, SSO (`ml_entry_eq_struct`, 2026-11-16, live+mirror): all **rejected**. TQQQ and QLD traded on `alpaca_paper` via `ml_entry` / `ml_entry_eq`. [MEASURED] |
| Why live rejects | `risk_refused: sized_qty=0` with a small live balance (~USD 195, 54 available): a 3x ETF share price rounds the risk-sized quantity to 0. Affordability, not a gate and not a missing symbol. UPRO/TZA/SPXL/SSO live rows all carry it. [MEASURED: rejection reason text] |
| Dedicated inverse legs | None. `tqqq_trend_long_1d` (alpaca_live, alpaca_portfolio, alpaca_paper) and `qld_trend_long_1d` (paper) are the only dedicated leveraged index legs; no `spy`/`iwm`/`dia` leveraged leg. [MEASURED: config read] |
| Data pull | `alpaca_live` / `alpaca_portfolio` / `alpaca_paper` `symbols:` lists carry none of SQQQ, SPXU, SPXS, SH, SDS, PSQ, QID, SDOW, TZA, UPRO, SSO, TNA, UDOW (additive pull list, **not** a gate). `pool_scored` reads the whole pool from the snapshot, which is why ML packages exist for them; a dedicated daily leg would need its symbol pulled. [MEASURED: set difference] |
| Does `alpaca_paper` run `ml_entry_eq_struct`? | Not in the roster rows read (paper trades the older `ml_entry` / `ml_entry_eq`). Re-parse `config/accounts.yaml` before the config change; counts are not quoted here. |

**Consequence.** The ML can already buy inverse ETFs, and did once, but (a) the live account is too small to size a 3x ETF at current risk-per-trade, and (b) no rule-tested dedicated leg exists. The "we don't have SQQQ" impression is correct for dedicated strategies and for the pull list, not for the ML pool.

## 2. Instrument map

Pool column = membership in the 173-ETF registered pool (**MEASURED**, passes the ≥ 50 M USD median daily dollar volume rule over 2019-20). Inception years are from memory (**UNVERIFIED**; the twins' fetch reports the true first bar and the units' windows start 2010-06-01, so 2010-02 and earlier listings all cover the window).

| Index | 1x long | 2x long | 3x long | 1x inverse | 2x inverse | 3x inverse |
|---|---|---|---|---|---|---|
| S&P 500 | SPY (pool) | SSO (pool) | UPRO, SPXL (pool) | SH (pool) | SDS (pool) | SPXU, SPXS (pool) |
| Nasdaq-100 | QQQ (pool) | QLD (pool) | TQQQ (pool; owned by `tqqq_trend_long_1d`) | PSQ (pool) | QID (pool) | SQQQ (pool) |
| Dow | DIA (pool) | DDM (not in pool) | UDOW (pool) | DOG (not in pool) | DXD (not in pool) | SDOW (pool) |
| Russell 2000 | IWM (pool) | UWM (not in pool) | TNA (pool) | RWM (not in pool) | TWM (not in pool) | TZA (pool) |

Caveats that apply to every leveraged/inverse row:
- **Daily reset decay.** 2x/3x funds rebalance daily; in choppy sideways markets they lose more than the underlying's drift ("volatility drag" ≈ ½·L(L−1)·σ² per year for L× long; inverse funds are worse: L(L+1)). A multi-week hold in chop is a structural loser; the TQQQ evidence (Donchian filter sidesteps chop) is *trend-only*.
- **Holding period.** These are tactical instruments: the existing twins hold days to weeks and use a daily ATR stop; nothing here is a buy-and-hold candidate. Inverse ETFs have a negative long-run drift (the index's long-run rise), so a no-regime long-and-wait is a mathematically decaying position.
- **Expense ratios** ≈ 0.9–1.0 %/yr, in addition to the harness's 5 bps slippage; embedded in the real price series the backtests use.
- **Reverse splits / delisting risk** on the 3x inverse funds (frequent reverse splits). The data source must be split-adjusted; the twins' fetch uses adjusted candles. UNVERIFIED for SQQQ reverse-split handling: the first twin read must report it.
- **No fossil-fuel instruments** are proposed (`config/values_exclusions.yaml`): UCO, GUSH, DUST-adjacent energy are out of scope here.

## 3. Candidate roster set (not too wide; liquidity first)

Long leveraged (down-market-irrelevant but the "with the index" half): **TQQQ** (exists), **UPRO**, **UDOW**, **TNA** (QLD stays a paper soak). SPXL/SSO dropped as duplicates of UPRO's exposure.

Inverse (the "against the index" half, bought as longs): **SQQQ** (Nasdaq 3x), **SPXU** (S&P 3x), **SDOW** (Dow 3x), **TZA** (Russell 3x), plus **SH** and **PSQ** (1x) as the low-decay comparators. Dropped: SPXS/SDS/QID (duplicates), DOG/DXD/RWM/TWM (below the pool's liquidity rule).

That is 10 instruments over 4 indexes. The 1x inverse pair exists because on a small account the 3x lot-sizing may not size (see § 1); a pass on SQQQ with a fail on PSQ (or the reverse) is informative about decay vs trend capture.

## 4. Research units (rules written before any run; none run yet)

| Unit | Status | What |
|---|---|---|
| RQ-20261123-1e01-01 | queued | `tqqq_trend_long_1d` twin on **SQQQ** |
| RQ-20261123-1e01-02 | queued | `spy_trend_long_1d` twin on **SPXU** |
| RQ-20261123-1e01-03 | queued | `spy_trend_long_1d` twin on **SDOW** |
| RQ-20261123-1e01-04 | queued | `iwm_trend_long_1d` twin on **TZA** |
| RQ-20261123-1e01-05 | queued | `spy_trend_long_1d` twin on **SH** (1x) |
| RQ-20261123-1e01-06 | queued | `qqq_trend_long_1d` twin on **PSQ** (1x) |
| RQ-20261123-1e02-01 | blocked on checklist row `IELE-DIRSWITCH-HARNESS` | direction-switch (bull ETF in up-regime, inverse ETF in down-regime, one position, flat on neutral) vs long-only bull ETF |
| RQ-20261123-1e03-01 | blocked on checklist row `IELE-ML-SUBSET-HARNESS` | `ml_entry_eq_struct` confirm-read restricted to the leveraged + inverse subset vs rest of pool |

Design notes and honest gaps:
- Twin rule (1e01-*): PASS iff n ≥ 25, net R > 0, ≥ 3 of 4 folds > 0, and net R still > 0 under 2x slippage; flat is the baseline, the bull twin's R is context. Power is declared as an ESTIMATE (~75 trades; floor 25).
- **Pullback twins (spy/qqq_pullback_1h on SH/PSQ) are not registered**: the 1h harness needs Alpaca 1h history for the inverse ETFs and I did not verify it exists for them; filing them blind would register a rule I cannot show can run. The trend twins use the daily keyless fetch the TQQQ twin already uses. Add them once one 1h SH fetch is shown to succeed.
- **The twins were authored but not executed here** (no runner dispatch in this lane); `exit_lever_ablation --leg <leg> --symbol <S>` is the exact shape of the passed RQ-20261113-4654-01, but whether a single-arm sweep grades cleanly (vs two arms) is **unverified**; if the harness refuses a one-arm sweep, add a `B=` arm equal to the baseline and the rule is unchanged.
- 1e03-01 is probably **UNDERPOWERED** (~20-60 subset trades expected); it reports a sign and a point estimate and states so. Per-symbol results never gate; only the pre-declared subset is read.
- 1e03-01 removes the need for a separate pooled test of a population "including the inverse ETFs": that pooled population already includes them and passed (98e3-06). The remaining question is whether the subset carries edge, which is what the unit asks.

## 5. Config change that would follow a pass (Tier 3 — NOT made; operator/manager approval; evidence record first)

1. **Per twin that PASSES** (Stage-0 pass goes to real money per OPERATING-PLAN § 2; the leg is also put on the demo floor): add a strategy `sqqq_trend_long_1d` (etc.) to `config/strategies.yaml` as a copy of its parent leg with `symbols: [SQQQ]` and `long_only: true`, a TP per the TP doctrine (re-run `scripts/ci/check_tp_doctrine.py`), and put it on `alpaca_paper` first as the demo-floor leg; real-money (`alpaca_live` + `alpaca_portfolio`, strict-equality mirror rule, `alpaca_portfolio ⊇ alpaca_live`) only after a committed evidence record. A same-index same-symbol-allocation guard is needed so a bull leg and an inverse leg on one index cannot both size full risk (`same-symbol-allocation-guard` pattern; instruments differ, so it will not fire by itself).
2. **If 1e03-01 reads SUBSET-NEGATIVE:** add the negative-reading inverse/leveraged symbols to `ml_entry_eq_struct.pool_exclude` (a population rule fixed before the rerun, not a per-symbol pick). If SUBSET-HOLDS: no change, the downside coverage is already live in the ML pool.
3. **Affordability on `alpaca_live`:** three live rejections show `sized_qty=0` at the current live balance. That is a sizing/balance question, not a roster one; flagged to the manager, no change proposed here.

### Additive data-pull proposal (separate; not a gate)
Add SQQQ, SPXU, SDOW, TZA, SH, PSQ, UPRO, UDOW, TNA to the `symbols:` pull list of `alpaca_paper` (data exists the moment a twin graduates; zero order-path effect). Reason: the dedicated daily legs read their own symbol, and the pull list is the only path that guarantees the bars. Not done here (config file).

## 6. Not done / open
- Twins and ML subset unit have not run; no edge claim is made about any inverse ETF.
- Liquidity beyond pool membership (spread, dollar volume today) was not measured.
- Journal population limited to the last 1000 trade rows; older inverse-ETF trades were not looked for.
