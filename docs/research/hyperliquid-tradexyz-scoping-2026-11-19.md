# Hyperliquid and trade[XYZ]: scoping memo (2026-11-19)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane AM-OPS-3 (GENERAL), operator decision D10 (week plan 2026-11-19 § 5: *"Yes, this week (Recommended)"*)
>
> **Gates this adds or changes:** none. A scoping memo; it builds nothing, wires nothing and asks for no credential. Every number below is from public secondary sources read 2026-11-18/19 unless marked MEASURED, and must be re-checked against the venue's own docs before any build.

## 1. What the two venues are

- **Hyperliquid:**
  - an on-chain, non-custodial order-book exchange (its own L1, "HyperCore") for perpetual futures and spot;
  - collateral is USDC; accounts are wallets, and there is no KYC account;
  - it has a public REST + WebSocket API, an official Python SDK, and a **testnet**.
- **trade[XYZ]:**
  - the largest **HIP-3** venue on Hyperliquid. HIP-3 lets a third party ("deployer") list its own perp markets on HyperCore.
  - Launched 2025-10-13 by the Hyperunit team.
  - Lists perps on **US equities, indices and commodities** (e.g. `XYZ100`, a Nasdaq-100 perp, reported at up to 30× leverage with 8 h funding). S&P DJI licensed it an S&P 500 perp on 2026-03-18 (secondary source).
  - It trades through the same Hyperliquid API and wallet as any other market.

## 2. What it would unlock for us

| Unlock | Why it matters here | Evidence state |
|---|---|---|
| **Equity and index exposure 24/7, including weekends and US holidays** | Our 1h/1d equity legs (`slv_trend_1h`, `tlt_pullback_1h`, `qqq_*`) can only act in the Alpaca session; D9 now even waits for the first full regular hour. An equity perp can act on a signal when it fires. | hypothesis: no Stage-0 test yet |
| **A second crypto-perp venue with lower base fees** | Base perp fees are reported at 0.015% maker / 0.045% taker vs Bybit's standard non-VIP 0.02% / 0.055% (Bybit schedule from memory, not re-read this pass). Real-money crypto legs are taker-heavy, so the cost stack could fall. | fee schedule secondary; our realized-cost model per venue is not built |
| **A true demo floor for the venue** (testnet) | Stage 1 is mechanical; a testnet gives 1–2 clean trades without real money. | testnet existence secondary |
| **Shorting and leverage on equities without a margin account** | `alpaca_live` is long-only today; a perp shorts natively. | — |

## 3. What it costs and what can go wrong

1. **Jurisdiction (blocker, operator-only fact).** Hyperliquid's Terms of Use (and trade[XYZ]'s disclaimer) restrict "Restricted Persons", reported to include persons resident, located or incorporated in the **United States** (and US citizens anywhere), Ontario, and sanctioned countries. **Whether the operator and the trading entity are eligible is a fact only the operator can confirm.** No build should start before that is stated in writing. Our servers are in an EU region; that is not the test, the person is.
2. **Fees on HIP-3 markets are higher:** reported at about 2× the base perp rate (≈0.07–0.09% taker), half to the deployer, with some markets in a reduced-fee "growth mode". **Funding** applies on every perp. The full cost stack must be modelled per market before Stage 0.
3. **Deployer risk (HIP-3):** a deployer defines the market's oracle and parameters and can halt or settle a market. That is a counterparty risk Alpaca and Bybit do not have.
4. **Oracle and basis outside US hours:** when the underlying market is closed, the perp's mark comes from the deployer's oracle method. Weekend prices can gap against the Monday open. A strategy backtested on cash-session bars does not transfer one-to-one.
5. **Custody and keys:**
   - trading needs a wallet key on the VM;
   - Hyperliquid supports an **API ("agent") wallet** that can trade but not withdraw, which is the only acceptable shape (reported, to verify);
   - funding the account means bridging USDC (Arbitrum), which is an operator action.
6. **Liquidity:** depth on single-stock HIP-3 markets is unmeasured. Index perps (`XYZ100`, S&P) are the likely-liquid starting set.
7. **Data history is short:** the xyz markets exist from 2025-10, so about 13 months. A Stage-0 test on the perp itself is thin; the test would run on the underlying's history plus a measured basis and funding model, and be graded as such.
8. **Free-tier fit (M2):** an adapter is code plus one more websocket and REST poll on the live VM. No new OCI resource is needed, but the live VM has no CPU headroom today (audit 2026-11-19, `LIVE-TICK-NEAR-BUDGET`).

## 4. Effort (the `new-broker` skill's path)

| Step | Size | Tier |
|---|---|---|
| Read-only data adapter (public candles, funding, mark/oracle prices) into the lake, for research | ~1 day | 1 |
| Stage-0 units: (a) crypto legs re-costed on Hyperliquid fees vs Bybit; (b) one equity index leg on XYZ100/S&P with weekend bars and the basis and funding model | ~1–2 days + runner time | 1 |
| Broker adapter (`EXCHANGE_MAP` entry, order + bracket placement, position and fill reads, reconciliation), testnet account as its demo floor | ~3–5 days | 2 |
| Operator: jurisdiction confirmation; create the wallet + API wallet; bridge USDC (only if a Stage-0 passes) | — | operator |

## 5. Recommendation

1. **Ask the operator one question first:** are you (and the account holder) outside Hyperliquid's restricted persons? If not, stop here and record the verdict.
2. **If eligible:** build only the **read-only data adapter** and the two Stage-0 units (§ 4 rows 1–2). That needs no key, no money and no VM change beyond a research job.
3. **Build the broker adapter only after a Stage-0 PASS** net of the HIP-3 fee and funding stack. Use the testnet as its demo floor. Real money follows the normal ladder.

Filed as follow-up: one pipeline item, "Hyperliquid/trade[XYZ]: operator eligibility answer, then data adapter + Stage-0 units", waiting on the operator's answer (week plan § 6: questions for the operator go in the daily email).

## Sources (read 2026-11-18/19; secondary unless stated)

- trade[XYZ] on DefiLlama: <https://defillama.com/protocol/tradexyz>; <https://defillama.com/rwa/perps/venue/trade-xyz?view=information>
- trade[XYZ] general disclaimer (restricted persons): <https://docs.trade.xyz/legal-and-disclaimers/general-disclaimer>
- FalconX, "The Transformational Potential of Hyperliquid's HIP-3": <https://www.falconx.io/newsroom/the-transformational-potential-of-hyperliquids-hip-3>
- KuCoin news, trade[XYZ] 92 markets / HIP-3 share: <https://www.kucoin.com/news/flash/trade-xyz-builds-92-markets-and-98-hip-3-volume-on-hyperliquid-in-8-months>
- Hyperliquid fee docs: <https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees>
- Datawallet, Hyperliquid availability in the USA: <https://www.datawallet.com/crypto/is-hyperliquid-available-in-the-usa>
- Dwellir, Hyperliquid fees explained: <https://www.dwellir.com/blog/hyperliquid-fees-explained>
