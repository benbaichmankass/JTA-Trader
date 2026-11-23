# Tradeify Perps: scoping memo (2026-11-23)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-23` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane TRADEIFY-PERPS-SCOPE-20261123, pipeline item `PI-20261123-PDEC1123-0003` (operator 2026-11-23: *"see if there's anything there that's worth trading, and if it's worth opening an account there"*)
>
> **Gates this adds or changes: none.** A read-only scoping memo. No account opened, no credential used, nothing built, no roster or config edit.
>
> **Update 2026-11-23 (manager relay of operator facts + Terms read).** Added: **[OPS]** = operator screenshot from the app, verified in-app; **[TOS]** = first-party Perps Terms of Use (`tradeifyperps.co/terms`, last updated 2026-11-20, read via WebFetch, a small-model summary: re-read before relying). The Terms point the trading rules (bots, holds, news, prohibited strategies, commission/swap, drawdown definitions, inactivity) to a **Trading Rules** document and the **Funded Trader Agreement (FTA)** that is not on that page. Those remain unread. Sections 1-3 and 6 below are updated; text from the first pass that conflicts is superseded by § 7.
>
> **Evidence quality (first pass), read this first.** Tradeify has published **no** Perps rules, fees or API terms that a public fetch could reach. `tradeifyperps.co` is a waitlist form; `app.tradeifyperps.co` is a JS app that returns only "Loading" to a fetch; the Tradeify 247 help centre (`help.tradeify247.co`) has no Perps article (all three read 2026-11-23). **Everything about Perps rules below is therefore UNVERIFIED**, and the operator, who has access, can read the real rules in the app in a few minutes (§ 6 questions). Every claim carries a source tag: **[1P]** first-party page read this pass · **[2P]** third-party / affiliate page read or summarised by the fetch tool (a small-model summary; re-read before relying) · **[REPO]** a measured or recorded fact already in this repo · **[UNV]** not verified. Some third-party search hits were not opened (propfirmcircle returned HTTP 429), so their content is only as quoted by the search summary.

## 1. What it is

| Fact | Value | Source / state |
|---|---|---|
| Brand | "Tradeify Perps", described as Tradeify 247 (crypto) **evolving into** Perps. Tradeify futures (tradeify.co) is separate and unaffected. | [2P] proptraderz.com/prop-firms-switching-to-perps (as of Oct 2026) |
| Status | Waitlist / beta key; no new 247 accounts sold, existing 247 accounts keep operating under their terms. | [2P] same; operator now has access, which fits |
| Legal entity | Tradeify 247 contracts with Tradeify Ventures LTD (Saint Lucia). Perps operator entity not confirmed (one search summary says "Tradeify FX LLC"). | [2P] alexfirdaus.com/tradeify247 (247 only); Perps [UNV] |
| Platform | Operator screenshot: `app.tradeifyperps.co`, BTC/USD perp, up to 10x, Market/Limit, footer "arcnine". I could not find any company called "arcnine". The nearest public match is **ArcaTrader** (FDCTech), a white-label broker/prop-firm platform that on 2026-11-19 announced 24/7 Hyperliquid-powered perps for prop firms, ">10 firms preparing to launch". **Whether "arcnine" = ArcaTrader is unverified**, a possible (not established) link. | screenshot = operator-relayed; ArcaTrader [2P] financemagnates.com (company press release, no independent check) |
| Is it a real exchange? | **Probably not.** The sibling product (Tradeify 247) prices tokenized stocks/commodities **from** Hyperliquid but orders are filled on DXTrade/MT5 **in a simulated account; they do not reach Hyperliquid**. Tradeify's own FAQ reportedly says the crypto product is not exchange trading and not a perpetual-futures product. A white-label prop "perps" terminal is most likely the same model: simulated fills against a Hyperliquid-derived price. | [2P] alexfirdaus.com, tapbit.com summary; Perps-specific [UNV] |
| Instruments | BTC/USD seen (screenshot). Reported lists elsewhere: crypto perps, plus (for 247) PAXG and Hyperliquid synthetic perps for SILVER, XYZ100 (Nasdaq-100), SP500, USOIL, UKOIL and single stocks. Full Perps list [UNV]. | [REPO] `docs/research/tradeify-platforms-2026-10-15.md` § 1 (measured on tradeify_1's terminal, a lower bound) |
| Hours | Crypto 24/7. Equity/commodity synthetics 24/7 but price off a deployer oracle when the cash market is shut (weekend gap risk). | [2P] alexfirdaus.com; hyperliquid scoping memo (§ 3.4) |
| Leverage | "Up to 10x" (screenshot). 247 caps were BTC/ETH/PAXG 5:1, altcoins and stocks 2:1; "Double Leverage" add-on doubles them. So 10x on BTC may be the doubled cap or a new tier. | screenshot; 247 caps [2P]/[REPO] ruleset header |
| Order types | Market and Limit (screenshot). Stop, bracket (SL/TP attached to the entry), trailing and modify support [UNV]. Our legs need a bracket at entry (TP doctrine). | screenshot |

## 2. Costs, compared with Bybit for our crypto legs

| Item | Tradeify 247 (what we run on `tradeify_1`) | Tradeify Perps | Bybit (our live books) |
|---|---|---|---|
| Commission | 0.04% per trade, 8 bps round trip; strictest reading per fill, **unconfirmed** [REPO] ruleset header | **UNV** | Standard non-VIP perp 0.02% maker / 0.055% taker, from memory, not re-read this pass (the Hyperliquid memo of 2026-11-19 uses the same figures) |
| Swap / funding | 0.033% of position value per day, flat, no real funding rate [REPO]; Tradeify FAQ reportedly "no overnight / swap / funding" on 247 [2P] (sources conflict) | **UNV** | Variable funding every 8 h; typically about 0.01% per 8 h ≈ 0.03%/day, either sign (a typical level, not measured here) |
| Spread / slippage | Not measured on the terminal (`TRADEIFY-INSTR-SPECS` gap) | **UNV** | Measured in our own cost model |
| Account fee | 1-Step $10k list $120; $100k $700; 2-Step $100 / $580; Instant $200 / $1,000 (one-time) [2P]. Perps pricing **not published**. | **UNV** | n/a (own capital) |
| Profit split | 80% standard (95% +25% add-on) [2P]/[REPO] | **UNV** | n/a |

Reading: a flat 4 bps per side on a *simulated* fill is **cheaper than Bybit taker (5.5 bps)** and about the same as Bybit maker-plus-taker mix; the flat 3.3 bps/day swap is similar in size to typical Bybit funding but never pays us when funding is negative. For our 4h trend legs, which hold days, swap is the cost that matters: 3.3 bps/night × a few nights is the same order as the round-trip commission. **Net effect on edge: UNVERIFIED**; it needs the Perps fee page and one re-cost run (§ 5).

## 3. Prop rules, and whether they break our current crypto legs

**None of the Perps rules is published.** The rows below give the Tradeify 247 rule as the nearest known baseline (what `tradeify_1` runs under, [REPO] `config/prop_rulesets/tradeify_247_1step.yaml`, first-party read 2026-09-30, still marked `unconfirmed: true`) and the Perps answer as UNV. One third-party summary says a "6% static drawdown locked to the starting balance" for a Perps 10k 2-Step page, but the same summary says the rules are not final, so treat it as unconfirmed.

| Rule | 247 baseline | Perps | Does it break our legs? |
|---|---|---|---|
| Profit target | 1-Step 12%; 2-Step 2 phases | UNV | n/a |
| Daily loss | 3% of account size, hard breach on live equity incl. unrealized, resets 22:00 UTC; "Daily Soft Breach" add-on makes it a 1-day lock (eval only) | UNV | Our daily-DD switch is armed on `tradeify_1` and keeps open, blocks new. Compatible if Perps is the same. |
| Max drawdown | 6% static (1-Step/2-Step); **trailing** on Instant Funding | UNV | Static is fine for our legs; a trailing max loss would be a different survival problem (needs a re-run of the prop EV sim). |
| Consistency | None on 1-Step/2-Step; 20% on Instant Funding | UNV | Our trend legs are lumpy winners (a few big days), so a consistency rule would hurt them. Ask. |
| News | No restriction found for 247 | UNV | Our legs do not trade news windows specifically. |
| Weekend / overnight | Allowed, "hold as long as you want" | UNV | **Critical:** the 4h Donchian trend legs hold multi-day through weekends. A no-weekend or no-overnight Perps rule would break them. Ask. |
| Min hold | 20 seconds [REPO] | UNV | Our holds are hours-days; fine. |
| Hedging | No simultaneous long+short in the same instrument, no cross-account hedge [REPO] | UNV | Same-symbol opposite legs across our book are already a known constraint on `tradeify_1`. |
| Min days | 3 profitable days at 0.5% on 1-Step/2-Step (one source) | UNV | Slow 4h legs trade a few times a week; could be tight. |
| Inactivity | 30 days without a trade = breach [REPO] | UNV | Fine. |
| Leverage cap | BTC/ETH 5:1, alts 2:1 | "up to 10x" | Position-size cap interacts with our risk sizing ($10/ticket baseline on `tradeify_1`); 10x loosens it. |
| Payout | On demand, 80% split, min $100, one request open at a time [REPO] | UNV | n/a |
| **Bots / API** | Allowed only if you own the strategy; shared bots/signal services and HFT are not [REPO]; ownership note `docs/ops/tradeify-bot-ownership-note.md` | **UNV, and the biggest question** | Our whole path is automated. |

## 4. Automation: API or web UI only?

- **Perps API: none found.** No public Perps API or docs located. ArcaTrader (if it is the platform) advertises a web terminal now, mobile apps "soon"; no API docs found in this pass. [2P] A different firm (My Funded Perps) says automation is allowed only via its own official API, which is a reminder the policy varies by firm.
- **Our existing path (`tradeify_1`)** is a **browser-driven DXTrade terminal** adapter (the `breakout` exchange family: Playwright login, ticket emitter `src/prop/breakout_executor.py`, symbol/lot map `config/prop_rulesets/tradeify_routing.yaml`, reconcile via `src/prop/*`). [REPO] It is slow and fragile (feed-trip and unknown-page incidents, `docs/research/tradeify-feed-trip-2026-10-07.md`).
- **If Perps is a different front end (ArcaTrader or similar):** it needs its own selectors, login-flow and order-form adapter; the reusable parts are ticket emission, sizing, the prop guards and reconcile. Rough effort: comparable to the original `TRADEIFY-WIRE` (several days plus a Stage-1 soak), and at least one live drill of bracket attach, modify and close. **If the platform also exposes a REST or FIX endpoint, that is strictly better** than the browser path; ask Tradeify (§ 6). If Perps is the *same* DXTrade terminal re-skinned, the existing adapter may work with a new routing map; the operator's screenshot (BTC/USD, "arcnine" footer) suggests it is **not** DXTrade, so assume a new adapter.

## 5. Strategy fit (existing legs), re-costed

Population: our live crypto legs on `bybit_1/2/portfolio` and prop roster of `tradeify_1` (re-parsed from `config/accounts.yaml` 2026-11-23; counts not quoted). Nothing here is a new backtest; "re-costed" means "what changes in the cost stack", and the number is **UNVERIFIED** until the Perps fee/swap schedule exists and one run of `src/research/run_costs.py` with `prop_declared_costs` is made.

| Leg | Fit | What it needs | Re-cost / gate |
|---|---|---|---|
| `trend_donchian_eth_4h`, `trend_donchian_sol_4h` (already on `tradeify_1`, `velotrade_1`) | Best candidates: crypto, 4h, low frequency, weekend holds | Perps must allow weekend/overnight and bots; a bracket-capable order form; SOL/ETH listed | UNVERIFIED. Prop gate: `comms/prop_survival/trend_donchian_{eth,sol}_prop.json` exist but are graded under a **different** ruleset (`breakout_turbo_1step`; eth record: EV +$75.74, p_breach 0.934, n=517, rule `RULE-P5-GATE-BRK-PER-LEG`, [REPO] file read). No Perps ruleset exists yet, so the superset gate has not been computed (the harness `scripts/research/prop_ev_sim.py` can run it once one is written; checked: scripts/research/prop_ev_sim.py); **do not reuse those records**. Note p_breach 0.934 on that book is itself a warning that eval survival under a 6% static DD is weak at the configured size. |
| `ml_entry` (1h, pooled) | Crypto symbols (BTC/ETH/SOL/XRP/ADA) possible; equity symbols not unless Perps lists synthetics | New venue means its own cost model per symbol (population rule: "an ML trades the whole population its registered pooled test passed on, limited to what the venue can trade") | UNVERIFIED; a new net-of-cost pooled replay for the venue's cost stack is required before a roster add |
| `*_pullback_2h`, `ict_scalp_*`, `fvg_range_15m`, `squeeze_breakout_4h`, `fade_breakout_4h` | **Poor fit on a prop book**: shorter horizons, more trades, spread/slippage dominated, and the min-hold / news / consistency rules bite | Spread and slippage measured on the Perps terminal first | UNVERIFIED; not recommended before the cost data exists |
| Equity / index legs (`slv_*`, `tlt_*`, `qqq_*`, `spy`) | Only if Perps lists synthetic perps like 247 does (SILVER, XYZ100, SP500, USOIL) | Hyperliquid memo's weekend-gap and oracle caveats; own leg evidence on the perp basis | UNVERIFIED; no Stage-0 on the synthetic series |

**Bottom line of the table:** the only credible fit is a **second prop book** for the same slow crypto trend legs we already run on `tradeify_1`, under the same philosophy, not a new strategy source. It adds capital-at-risk for fees (the prop account fee is the cost of an option on profit), not a new edge.

## 6. Advantages, disadvantages, risks, recommendation

**Advantages**
- A fresh evaluation lottery ticket for the same already-gated slow legs; 24/7 crypto, probably weekend-friendly.
- Higher leverage (10x) gives more sizing room than the 5x/2x caps we work under on 247. Costs may be lower than Bybit taker (4 bps/side).
- Same operator as `tradeify_1`, so payout and verification flow are known; our ruleset, guards, ticket emitter and daily-DD switch are reusable.

**Disadvantages and risks**
- **No published rules**; today's decision would be made blind on bots/API policy, weekend holds, drawdown type (static vs trailing), consistency, fees.
- **Likely simulated**: no real fills. The profit is a promise from the firm, not our execution result; counterparty risk is the firm's (an offshore Saint Lucia contracting entity for 247, [2P]) and the fee is sunk. The firm can change rules (247 itself was withdrawn from sale and "evolved").
- **Automation path risk**: no API found; another browser adapter on a live VM that already has no CPU headroom (audit 2026-11-19, `LIVE-TICK-NEAR-BUDGET`).
- **Bot-ownership clause**: if the Perps rules carry the same "you must own the bot" language, our ownership statement applies; it needs re-checking, not assuming.
- **Eval survival**: our own prop records show high breach probability (p_breach 0.934 on a related ruleset); a new account fee mostly buys a short option unless the survival gate passes under the actual Perps rules.
- **Counted twice**: opening Perps does not diversify the underlying edge; it is the same trend legs on another sim.

**Recommendation: OPEN ONLY IF X, and do not build before X.**
X = the operator (who has access) reads the Perps terms in the app and confirms, in this order: (1) automation/bots allowed for an owned strategy, or an API exists; (2) weekend/overnight holds allowed; (3) max-loss type is static, and the daily/max percentages are no tighter than 3%/6%; (4) the fee and any swap/funding schedule, and what the account fee is. If all four hold, buy the **cheapest** evaluation only (it is the cost of the option), run the prop EV/survival gate under a new `prop_rulesets/tradeify_perps_*.yaml` built from the real terms (the superset bar), and wire a new adapter only after that gate passes and the platform is confirmed not to be DXTrade. If (1) or (2) fails, **don't open**: the slow trend legs cannot run there, and nothing else fits. Filing action: one pipeline item for the operator's four answers (§ below), no build row yet.

**Exact questions only the operator can answer** (everything else is already covered above)
1. In the app / its help or terms: are bots, scripts or EAs allowed, only an owned bot, only via an official API, or forbidden? Is there a REST / FIX / API key screen?
2. Are weekend and overnight holds allowed? Any max holding time? Any news restriction?
3. What are the daily-loss and max-loss percentages, is max loss static or trailing, and is there a consistency or minimum-profitable-days rule?
<!-- population-ok: percentages here are quoted rule values or open questions about the venue's rules, not measured results -->
4. What are the account fees per size, the commission per side and any swap / funding charge? Is the profit split 80% or other, and what is the payout cadence/minimum?
5. Which instruments are listed beyond BTC/USD (ETH, SOL, XRP, equity or commodity synthetics), and does the order form let you attach a stop and a take-profit at entry and modify them later?
6. Is it a real exchange account or a simulated account (do funded profits come from the firm), and who is the legal entity on the sign-up terms?
7. Is "arcnine" in the footer a link or an "About" text that names the platform vendor? A screenshot of the footer and the terms page is enough.
8. Willingness: how much account fee are you willing to spend as the cost of the option, given our own prop records show high eval-breach probabilities?

## Sources (read 2026-11-23; tags per § header)

- Tradeify Perps waitlist: <https://tradeifyperps.co> ([1P], form only) · web app <https://app.tradeifyperps.co> ([1P], "Loading") · 247 help centre <https://help.tradeify247.co> ([1P], no Perps article).
- <https://www.proptraderz.com/prop-firms-switching-to-perps/> ([2P], Oct 2026: waitlist; rules, leverage, fees, payout "not announced").
- <https://alexfirdaus.com/tradeify247/> ([2P]: 247 entity, pricing, caps, simulated fills on DXTrade/MT5, HIP-3 price source).
- ArcaTrader perps launch, 2026-11-19: <https://www.financemagnates.com/thought-leadership/arcatrader-launches-247-perpetuals-for-brokers-and-prop-firms-powered-by-hyperliquid/> ([2P], promotional release; no leverage, fees or API stated).
- Search summaries only (pages not opened; propfirmcircle gave 429): <https://propfirmcircle.com/blog/tradeify-perps-hyperliquid-review-and-rules> · <https://propfirmcircle.com/challenges/tradeify-crypto-10k-2-step> · <https://www.tapbit.com/en/learn/article/what-is-tradeify-crypto-funded-trading-platform-legit-20260818> ([2P], weak).
- Repo ([REPO]): `config/accounts.yaml` (tradeify_1 roster, re-parsed), `config/prop_rulesets/tradeify_247_1step.yaml`, `config/prop_rulesets/tradeify_routing.yaml`, `comms/prop_survival/trend_donchian_eth_prop.json`, `docs/research/tradeify-platforms-2026-10-15.md`, `docs/research/hyperliquid-tradexyz-scoping-2026-11-19.md` (format template).

## 7. Update: operator-verified app facts + the Terms of Use (supersedes first-pass guesses)

**Verified facts.**

| Fact | Value | Source |
|---|---|---|
| Sizes / one-time fees | 5K $60 · 10K $117 · 25K $286 · 50K $581 (no refunds once purchased, ToS § 9.5; fees are programme fees, not deposits, § 4.7; prices can change, § 9.1) | [OPS]; [TOS] |
| 5K Evaluation | target $500 (10%); max loss **static** $250 (5%); daily loss selectable 3% ($150) **or None**; consistency selectable 50% **or None** | [OPS] |
| 5K Funded | split 75%; "Live Fund" = 10% of each gross payout; payouts on demand; min payout $200; processing within 24 h; activation instant; identity verification (Sumsub) before payouts | [OPS]; [TOS] §§ 3.2, 26 |
| "Live Fund" | collateral built from 10% of each gross payout; becomes the drawdown of a **Live Account** under a separate Live Trader Agreement; "never the trader's money", cannot be withdrawn, no cash value, not refunded on termination | [TOS] §§ 2.14, 19.4 |
| Execution | **All trading is simulated; you never own the underlying** (§ 4.2). The company may place its own hedge trades at its discretion; this does not affect your account or payouts (§ 4.3). Confirms the first-pass "probably simulated" guess. | [TOS] |
| Legal entity | Tradeify FX LLC, a Florida LLC, Boca Raton FL; part of Tradeify Holdings, Corp.; Novaflame LTD (Cyprus) processes some payments; payout processors Rise and Plane; payouts only to an account in the trader's own name. Differs from the 247 entity (Saint Lucia). | [TOS] §§ 1.1, 24.3, 9.2, 26.2, 7.6 |
| Eligibility | **US persons are eligible** (§ 3.4); individuals only, 18+, one login per household (§ 7.5); restricted-jurisdiction list lives in the help centre (not read). | [TOS] |
| Costs | Commission, swap, funding: **not stated** in the Terms (Trading Rules). | [TOS] § 5.3 |

<!-- population-ok: percentages here are quoted rule values or open questions about the venue's rules, not measured results -->
**Still not answered by anything read (the Trading Rules / FTA are the source):** bots/EAs/API (the Terms only bar using bots to scrape or copy *content*, § 14.1, and bar VPS/virtualised environments that obscure verification, § 14.2, which touches a VM-hosted executor: see Trading Rules A.20); overnight/weekend holds; max hold; news rule (named, not detailed); prohibited strategies (HFT, latency, copy trading, cross-account hedging; "Fair-Play Violations", § 5.5); inactivity; commission/swap; whether the funded account keeps the 5% static / 3% daily limits; the "50% consistency" meaning for funded.

**Drawdown fit (5% static max loss; 3% daily or None).** UNVERIFIED for our legs: the only readable evidence is `comms/prop_survival/trend_donchian_eth_prop.json`, graded under a different ruleset (`breakout_turbo_1step`: EV +$75.74, p_breach 0.934, n=517); no Perps-shaped harness run exists. Direction only: 5% static is **tighter than the 6% static** `tradeify_1` runs under, and the daily limit can be chosen **None** (removes the 3% daily breach that our armed daily-DD switch otherwise guards), so choosing **daily None + consistency None** is the least restrictive evaluation. Whether our slow trend legs survive a 5% static floor at 10x is the one number to compute (prop_ev_sim with a new `prop_rulesets/tradeify_perps_5k.yaml`, a Tier-1 research task).

**Break-even math (5K, fee $60).** Population: one evaluation attempt, funded rules assumed equal to the evaluation limits, no rebuy. Payout on a $500 gain at 75% split = $375 gross payout; Live Fund 10% of gross payout = $37.50 → **$337.50 net** (if the 10% is taken off profit instead, $325; assumption, [OPS] wording is "10% of payouts"). Min payout $200 means the first payout needs profit ≥ ~$267 at 75%. Break-even pass-and-first-payout probability = $60 / $337.50 ≈ **18%** per evaluation (10K: $117 / $675 ≈ 17%; 25K: $286 / $1,688 ≈ 17%; the ratio is flat across sizes). The cost of failure is only the fee. Our graded record shows p_breach 0.934 on a related ruleset, i.e. pass ≈ 7% there, **below the 18% break-even**: on that evidence the EV is negative; it flips only if a Perps-specific gate shows pass probability > ~18% net of costs (UNVERIFIED either way). Arithmetic cross-check: 337.50 × 0.178 = 60.1.

**Revised recommendation: DON'T BUY YET; compute first (cheap, Tier 1), then buy the 5K only if the gate clears.**
1. Read the **Trading Rules / FTA** (help centre or in-app, the operator has access) for bots/automation, VM use (A.20), weekend/overnight, news, prohibited strategies, commission/swap. If automation is barred or restricted to an official API, don't open.
2. Run the survival harness under the real Perps limits (5% static; daily None vs 3%; consistency None) for `trend_donchian_eth_4h`, `trend_donchian_sol_4h`, `ml_entry`; require pass probability above the ~18% break-even net of the (still unknown) commission and swap.
3. If both clear: buy the **5K ($60)** with daily None and consistency None, wire only after a Stage-1-style mechanical check, and a new adapter (no API seen).
The ToS also removes the main first-pass worry about the platform being a real exchange: it is a simulation, so the economics are a fee-for-an-option, nothing about execution quality.

**Remaining operator questions (the Terms do not answer them):**
1. In the Trading Rules / FTA: are automated strategies allowed, may they run from a VM (A.20), and is an API offered? Any ban on HFT, copy trading, cross-account hedging?
2. Overnight and weekend holds, maximum hold time, and the news rule: allowed or restricted?
<!-- population-ok: percentages here are quoted rule values or open questions about the venue's rules, not measured results -->
3. Commission and swap/funding rates, and whether the funded stage keeps the same 5% static / daily None choices?
<!-- population-ok: percentages here are quoted rule values or open questions about the venue's rules, not measured results -->
4. What does the selectable "consistency 50%" test (best day share of profit?), and does it apply to funded accounts?
5. Is the restricted-jurisdiction list in the help centre clean for the entity that would buy?
