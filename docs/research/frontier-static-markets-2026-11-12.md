# Frontier scan: strategies that profit from static, range-bound markets (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Row `FRONTIER-STATIC-MARKETS` (operator, 2026-11-11, retiring the M22 pairs sleeve: *"I want us to do some frontier
research on strategies or MLs that are geared towards profiting from static markets"*). Author: ML standing lane,
part 3, dispatched by Manager Session 2026-11-11a. This is the first pass. It is a targeted strategy scan, not the
weekly model scan, and it does not replace `frontier-research` Steps 0-2 for the week.

## What the repo already tried (checked on main, 2026-11-12)

- **Range-gated fade on crypto perps.** The Donchian-pierce fade with an ADX range gate has FAILED nine registered units:
  RQ-20261022-4b82-04, RQ-20261023-1d5c-12/-13, RQ-20261026-f679-01, RQ-20261028-2a2e-05/-08, plus ef5d-09, 326f-09 and
  4b82-18. Daily fade on 12 perps (RQ-20261103-b3c9-11) came back INDETERMINATE. Another ADX-threshold variant on crypto
  would repeat a closed question, so none is filed.
- **Pairs (M22).** Net-negative on the honest fixed-beta R scale (-0.112 to -0.526 R/trade, n 254-271, per the roadmap
  entry). Retired by record (#24991).
- **Funding carry**, the market-neutral static-market idea, is already in the queue: RQ-20260929-104 is queued and
  RQ-20261111-9b09-03 (two-venue differential carry) is blocked on a two-venue harness. It is not filed again here.

## Sources checked

| source | item | primary or secondary |
|---|---|---|
| arXiv | Pandey & Joshi, *Using Internal Bar Strength as a Key Indicator for Trading Country ETFs*, [arXiv:2306.12434](https://arxiv.org/abs/2306.12434) | primary |
| practitioner | Pagonidis 2013, *The IBS Effect: Mean Reversion in Equity ETFs* (cited via [Kinlay](https://jonathankinlay.com/?p=2199)) | secondary; the original was not read |
| journal | Zaremba et al. 2021, *Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets*, IRFA ([record](https://aminer.org/pub/628d19b35aee126c0f369100/up-or-down-short-term-reversal-momentum-and-liquidity-effects-in-cryptocurrency)) | primary (abstract) |
| working paper | Bianchi, Babiak & Dickerson, *Trading Volume and Liquidity Provision in Cryptocurrency Markets* ([Riksbank WP 413](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)) | primary |
| journal | Ensemble-HMM regime voting, DSFE 2025 ([doi 10.3934/DSFE.2025019](https://aimspress.com/article/doi/10.3934/DSFE.2025019)) | primary (abstract) |

Not checked in this pass: the Hugging Face Hub (no static-market model family is expected there), GitHub, and
competitions. Those belong to the weekly model scan.

## Triage

| # | idea | data | compute | serving | leakage / licence | business question | power | call |
|---|---|---|---|---|---|---|---|---|
| K1 | **IBS daily mean reversion on liquid ETFs** | daily OHLC (yfinance) | trivial | a daily signal at the close | none; public method | a new equities leg on the alpaca_paper floor | about 1,500 trades pooled (estimate) | **KEEP**, as RQ-20261112-a7e8-01 with a new instrument, `scripts/research/ibs_reversion_stage0.py`. p(PASS) about 0.3 |
| K2 | **The repo's fade family at 1d on the same ETFs** | the same | the same | the same | none | the same | about 300 trades (estimate) | **KEEP**, as RQ-20261112-a7e8-02 with zero build cost. p(PASS) about 0.25 |
| D1 | Cross-sectional 1-day reversal on crypto perps (market-neutral) | yes | yes | yes | none | yes | yes | **DROP, gate 5 (probability).** The primary evidence puts the reversal in illiquid coins, while the largest, tradeable coins show daily momentum. Our perps are that large-cap set. Revisit only if the book adds a small-cap perp universe. |
| D2 | Options premium selling / volatility risk premium | no point-in-time options chains, no options venue on any roster | | | | | | **DROP, gate 1 (data)** |
| D3 | Grid or market-making on ranges | needs L2 data and a queue-position fill model; `desk_maker_fills.py` is unvalidated for this use | | needs a sub-second loop | | | | **DROP, gates 1 and 3** |
| D4 | An HMM range detector as a gate on a mean-reversion leg | yes | yes | mirror-publish | none | **no consumer yet.** It would gate a leg that does not exist. | | **DEFERRED.** File it as the next iteration only if K1 or K2 passes; it is a regime-family variant, and the ADX gate has failed nine times on crypto. |
| D5 | Funding carry (market-neutral) | | | | | | | **ALREADY QUEUED** (RQ-20260929-104 and RQ-20261111-9b09-03); not filed again |

## Calls (graded by next week's Step 0)

- **K1:** `p = 0.30`. Check: the auto-graded verdict of RQ-20261112-a7e8-01. A powered PASS or FAIL is a hit for the
  keep call; an underpowered result or a run that never happens is a miss.
- **K2:** `p = 0.25`. Check: the verdict of RQ-20261112-a7e8-02, graded the same way.
- **D1 drop:** a miss if a liquid-perp reversal test elsewhere in the repo later shows a powered PASS.

If either unit passes, the next step is one confirmation unit on a symbol-disjoint basket (the sector SPDRs) with the
passing arm frozen. That is followed by D4 as the iteration and MD-PROMOTE-S0-S1 for a Stage-1 paper leg. A FAIL closes
only the exact arms tested.
