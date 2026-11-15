# PROP-ML-NEW-DATA: non-price data inventory, family ranking, and where the route stands (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

> Gates this adds or changes: none. Lane PROP-ML-NEW-DATA (Tier 1), dispatched by the ML assistant manager 2026-11-12 after "prop MLs are surge".
> Every claim carries its basis: **MEASURED** (read by me this session or a graded record on `main`), **UNVERIFIED** (a claim I did not check).

## 1. Inventory: non-price data held for ETHUSDT / SOLUSDT

The brief's step 1 had already been executed on 2026-11-08/09 by earlier lanes (units below, all graded on `main`); the row note was stale. This
section re-verifies it rather than repeating it.

| series | source | ETH | SOL | evidence |
|---|---|---|---|---|
| 1m klines (+ derived 5m..1d) | lake `crypto/um_perp/1m`, `derived` | present | present | MEASURED: directory listing 2026-11-12 (file names/sizes only) |
| fundingRate (every event) | lake `um_perp/funding` | 2020 -> 2026-10 | 2020 -> 2026-10 | MEASURED: listing. Census `98e3-30` graded **funding NOT usable for SOL**, premium-index usable for both |
| metrics 5m (OI, long/short, taker ratio) | lake `um_perp/metrics_5m` | 2021 (≈Dec) -> 2026-10 | same | MEASURED: listing (the 2021 file is 0.53 MB vs ~0.4 MB/month later = about 1.3 months). Census `98e3-28` PASS usable |
| premiumIndexKlines 1m (basis proxy) | lake `um_perp/premium_1m` | 2020 -> 2026-10 | 2020 (SOL perp starts 2020-09-13) -> 2026-10 | MEASURED: listing; `98e3-30` PASS, the only family reaching 2020-07..2021-12 |
| bookDepth | **not in the lake as of 2026-11-12** (MEASURED: `um_perp` lists exactly 5 directories: `1m`, `derived`, `funding`, `metrics_5m`, `premium_1m`; a `find` for `*bookDepth*` returned 0 entries, but that glob was not proven against a positive, so the directory listing is the evidence) | built point-in-time from the public archive by unit `98e3-36` (PASS) | same | graded record |
| aggTrades 1m order-flow bars | **not in the lake** (same 5-directory listing; `find *aggTrades*` 0 entries, same caveat); census listed ETH/SOL raw files 2019-12-31/2020-09-01 .. 2026-11-07, graded=false | not downloaded | not downloaded | `98e3-28` `listed_only` |
| liquidations | Binance Vision `liquidationSnapshot` | **404** monthly and daily (BTCUSDT 2023-06, control URL `klines/ETHUSDT/1h/2023-06` returned 200, 2026-11-12) | same | MEASURED probe with a positive control; matches `docs/research/desk-edge-program-2026-10-27.md:149` (404 in 2023 and 2026). Bybit's public site has none. Candidate: a paid vendor (Coinglass) = an operator spend decision, not taken here |

⚠️ **Limit of what I verified.** The lake's file contents are not readable from this container (HTTP 403 on `cat`; `98e3-28` records the same 403 and the
storage cap since 2026-11-05), so "present" above means the files are listed, not that rows were parsed. The row-level coverage evidence is the census
records, which read the public Binance archive directly: `research/results/RQ-20261108-98e3-28`, `-29`, `RQ-20261109-98e3-30`, `-36`.

## 2. The three families, ranked, and what each carries that price does not

Literature is cited **from memory, not retrieved this session (UNVERIFIED)**: check before quoting externally.

1. **Funding / basis (premium index).** Carries the perp's crowding and financing state, a slow variable (hours to days). Schmeling, Schrimpf and Todorov,
   *Crypto carry* (BIS WP 1087, 2022-23): carry predicts crypto returns and crash risk; Liu and Tsyvinski, *Risks and Returns of Cryptocurrency* (RFS 2021).
   Horizon match with 8h bars: good. History reaches 2020. **Rank 1.**
2. **OI + long/short + taker flow.** Carries leverage and positioning (forced-liquidation fuel, one-sided crowding); Brunnermeier and Pedersen, *Market
   Liquidity and Funding Liquidity* (RFS 2009) is the mechanism (funding stress feeds price spirals). Medium horizon; history from 2021-12. **Rank 2.**
3. **Book depth imbalance / aggressor flow.** Carries the immediate supply/demand imbalance. Cont, Kukanov and Stoikov, *The Price Impact of Order Book
   Events* (J. Financial Econometrics 2014) and Kolm, Turiel and Westray, *Deep Order Flow Imbalance* (Math. Finance 2023): the edge lives at seconds to minutes
   and is mostly gone by a 4h-8h bar. Horizon mismatch with every bar this prop line can trade at. **Rank 3.**

## 3. What has already been run (graded on `main`; population ETH+SOL pooled, bv and tradeify_es cost profiles)

| family | units | arms | result |
|---|---|---|---|
| oi_flow, forward 2025-01..09, 4h | `98e3-31` (bv), `-32` (tradeify_es) | F0, F0+OI x 5 taus | FAIL: no discovery-eligible arm, held-out unread |
| funding/basis, backward 2020-07..2021-12, 8h | `98e3-34` (bv), `-35` (tradeify_es) | F0, F0+BASIS x 5 taus | `-34` FAIL no eligible arm. `-35` had an eligible arm, held-out read once, **n=235, mean -0.048 R, CI [-0.172, +0.047], E1 FAIL** |
| book depth, 2023-03..12, 4h | `98e3-37` (bv), `-38` (tradeify_es) | F0, F0+BOOK x 5 taus | FAIL: no discovery-eligible arm |

Read: all three free Binance non-price families, offered to the registered **LightGBM head**, produced no arm that survives discovery on 5 of 6 units and a
negative held-out on the sixth. Together with the closed price-only lines (`ml_entry` v1, pooled ~40 arms, d256-02 filter, d256-01), the prop line has
no candidate. This is evidence, not retirement.

## 4. The lever those six units did not vary: model capacity

A 200-tree LightGBM on about 10k rows, a noisy +0.5 R label and 11+ features can overfit a slow state variable. The unvaried lever is capacity, so two
units are registered (before any run) with a regularised logistic head and one constant TP per side, **everything else unchanged**:

- `RQ-20261112-7d41-01`: basis, bv, 8h, sealed backward held-out 2020-07-01..2021-12-21 (same split as `98e3-34`).
- `RQ-20261112-7d41-02`: oi_flow, bv, 4h, forward held-out 2025-01-01..2025-09-30 (same split as `98e3-31`).

Book depth is not re-run (rank 3, horizon mismatch, three-way no-eligible-arm already). The driver gains `--model {lgbm,logit}`, default `lgbm`, so every
earlier unit's command is unchanged (`prop_ml_leg.py --self-test` passes, including a new NaN-safe/constant-TP check).

**Exit paths.** FAIL on discovery with the held-out unread at both capacities closes the free-Binance non-price route for the pooled prop entry ML; the
recommendation to the programme review is then to retire that line for these families, with the next information source being one that needs spend or new
collection (liquidations from a paid vendor; cross-venue funding/basis differentials, a new collection job, Tier 2 if it writes to the lake).
A PASS authorises one forward-window unit and a held Tier-3 roster proposal for the manager, never a self-merge.

## 5. Data-pull rows

None filed: every family the inventory shows usable is already readable by the driver from the public archive. Liquidations are not obtainable free
(verified); a paid pull is an operator decision and is raised to the manager in the lane report rather than filed as work nobody can start.
