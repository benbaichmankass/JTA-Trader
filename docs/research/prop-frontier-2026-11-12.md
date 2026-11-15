# Prop frontier: futures, ETF, stock and FX prop firms our server can trade without an operator device (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · row **PROP-FRONTIER-RESEARCH** · lane session_01AFoLuKEZCj8H39D6uc5yt4 · dispatched by Manager Session 2026-11-11a via AM-TRADING · public sources only; no account, sign-up, credential, order or config touched.

**Gates this adds or changes: none.**

The operator asked on 2026-11-12 at about 12:02Z (verbatim): *"lets create a new prop-frontier-research lane to look for other prop firms that offer accounts for trading futures/etfs/stocks/fx that fit our strategies/mls and offer at least a web-session signin that doesn't require it operate from a live device".*

Machine-readable companion: [`comms/research/prop_frontier/firms.json`](../../comms/research/prop_frontier/firms.json). It holds 51 entries: 47 firm entries (one groups seven stock firms) plus 4 platform rows (ProjectX, Tradovate API, Rithmic, CQG). Every quote is verbatim, with its URL and fetch date. It builds on [`tradeify-futures-frontier-2026-11-12.md`](tradeify-futures-frontier-2026-11-12.md) (PR #25203, open at the time of writing) and refreshes the 2026-09-30 and 2026-10-04 scans, which covered crypto-perp firms.

## 0. The answer

1. **Futures: no CME-micro firm both passes the device filter and fits a leg today.**
   - The futures firms that allow a bot from a server all force positions flat every day. The best of them is FundedNext Futures, flat by 3:10 PM CT.
   - Every Stage-0-PASS futures and ETF leg we have holds overnight to weeks. The shortest p10 hold among them is 6 h.
   - The Tradeify memo found no session-flat leg that passes (§ 2a and § 3 there). The futures route waits on the same two queued units, RQ-20261112-09d2-04 and -05.
2. **The firms everyone thinks of are out on their own words.**
   - Topstep (re-read today, 1P): *"All trading activity must originate from your personal device."*
   - Alpha Futures, Aqua, Apex, Take Profit Trader, Phidias, Elite Trader Funding, Funded Futures Family and Tradeify futures: each bans bots or VPS, or requires the operator's own device (§ 2).
3. **Velotrade's CFD side is the one fit, and it is a firm we already trade at.**
   - It has DXtrade REST *"Open to all accounts from evaluation through funded … No additional fee or approval required"* (1P).
   - `velotrade_1` already executes through exactly that API.
   - It lists CFDs on SPY, QQQ, IWM, gold, silver and WTI, and allows overnight and weekend holds (1P, re-fetched by this lane).
   - Nine of our Stage-0-PASS ETF legs map onto those underlyings.
4. **EV screen:** RULE-PROP-FRONTIER-EV6M-20261112 was registered in commit ae5f99203 and pushed before the run. It says **BUYABLE on both Velotrade $5k plans** for the 9-leg book:
   - CLASSIC 1-Step ($54): 6-month EV **+$44.83** per purchase, against a zero-edge null of −$41.13.
   - PRO 1-Step ($32): **+$21.40**, against a null of −$27.37.
   - **The pass is marginal.** The book edge CI lower bound is +0.004R. Dropping any one of five legs turns it negative, and the edge sits entirely in the commodity legs. The rule's own proxy caveat applies: the ledgers are on the ETFs, not on Velotrade's CFDs.
5. **Update, same day: Velotrade is NOT BUYABLE.** The Stage-0 re-run on the CFD underlyings (VELO-CFD-STAGE0, RULE-VELO-CFD-STAGE0-20261112, registered in 1f4d346a7 before the run) **failed all 4 commodity legs** over 2019-01..2026-10 on spot silver, WTI and gold (§ 5b).
   - The 2025-26 window behind the EV pass was a favourable stretch. Over 8 years, the overnight fee of 0.05% of notional per night (about 18% a year) eats 0.15–0.47R per trade.
   - Without that fee, `gld_pullback_1h` (+0.36R per trade, 7 of 8 years positive) and `slv_trend_1h` (+0.21R, 7/8) hold up over the full 8 years.
   - **So the edge is real, but Velotrade's financing kills it.** A venue that charges no per-night financing on gold and silver (CME futures: MGC, SIL) is where these legs belong, and that is a real-money/IB question, not a prop one.
   - **No Velotrade purchase.**
6. **Real-stock firms: none passes.** Trade The Pool, the main one, says *"A human person must personally place and authorize every single trade."* No stock prop firm with an Alpaca, DAS or IBKR API was found. That is a search result, not proof of absence.

## 1. Method

- **Population.** 51 entries across four clusters, each read by a research sub-agent against one shared brief. Fetch date for all: 2026-11-12.
  - futures on ProjectX/API platforms: 12 entries, one of them the ProjectX platform row;
  - futures on Rithmic/CQG/Tradovate: 17 entries, three of them platform rows (Rithmic, Tradovate API, CQG);
  - FX/CFD: 16;
  - real stocks and ETFs: 6 entries, one grouping seven firms.
- **Re-checks by this lane.** The decisive clauses for the two firms that rank were re-fetched directly: Velotrade `/blog/velotrade-review` and `/forex`, and FundedNext Futures help article 17225788. The quotes below come from those reads.
- **Hard filter.**
  - Orders must be able to originate from our cloud server with no operator device: through a firm-permitted API, a headless web session on the VM (the `tradeify_1` DXtrade precedent), or an EA on a VPS.
  - The firm must have no own-PC, personal-device, no-VPS, enable-on-video or no-fully-automated clause.
- **Status marks.**
  - **1P**: the firm's own page.
  - **3P**: a third-party page.
  - **UNVERIFIED**: could not read the page. Never treated as permission.
  - Many first-party pages returned 403 or 404 to scripted fetches (Apex, Bulenox, TPT, Alpha Capital, FundingPips, help.ftmo.com, help.e8markets.com, propshoptrader.com). Those firms are UNVERIFIED unless a 1P quote elsewhere settles them.

## 2. The hard filter, firm by firm

### 2a. Futures

| Firm | Verdict | Decisive text (source, fetched 2026-11-12) |
|---|---|---|
| **Topstep / TopstepX** (ProjectX API, $29/mo) | **FAIL** | *"All trading activity must originate from your personal device."* *"The use of VPS, VPNs, and remote servers is prohibited by Topstep's Terms of Use."* *"Live funded accounts are not allowed to trade through the ProjectX API."* (1P help.topstep.com/en/articles/11187768; unchanged from the 2026-09-30 read) |
| ProjectX Gateway (platform) | **FAIL as a route** | 3P (NexusFi): Topstep-exclusive after 2026-02-28. The firms that used it moved to Tradovate or Rithmic. |
| **FundedNext Futures** | **PASS on rules; route UNVERIFIED** | *"you are allowed to use automated trading systems such as Expert Advisors (EAs) and trading bots"*; *"You may use a VPS (Virtual Private Server) or VPN (Virtual Private Network) while trading"*; *"All positions must be closed by 3:10 PM CT each trading day."*; *"Overnight and weekend holding is not permitted."* Platforms: Tradovate, NinjaTrader. No API mentioned. (1P helpfutures.fundednext.com/en/articles/17225788, dateModified 2026-11-04, lane re-fetch) |
| Tradeify futures | FAIL | Live video of enabling the bot "on your own PC"; no VPS login; no Tradovate API on eval or sim (Tradeify memo § 1) |
| Alpha Futures | FAIL | *"AI, bots, and other automated trading mechanisms is strictly prohibited across all account types"* (1P text, quoted 3P) |
| Aqua Futures | FAIL | Bans *"fully automated systems, unattended algorithms, trading bots, AI-driven execution software"* (1P help article) |
| Apex | FAIL (3P) | *"No Automation or Algorithm Usage allowed"*; cloud servers used to disguise location banned (1P page 403; 3P Propvator, Aug 2026) |
| Take Profit Trader | FAIL (3P) | UTP: all trades manual on Test, PRO and PRO+ (1P zendesk 403) |
| Phidias | FAIL | 1P /regles: no fully automated bots; only supervised semi-automatic use. (Its Premium plan does allow overnight holds, irrelevant to a bot.) |
| Elite Trader Funding | FAIL | 1P ToS (l): VPS/VPN banned; (ac): bots banned without written authorization |
| Funded Futures Family | FAIL (3P) | Automation officially prohibited |
| MyFundedFutures | UNVERIFIED | 1P fair-play page: *"Traders may make use of automated trading strategies tailored to their own specific settings"*. 3P: fully autonomous bots without oversight prohibited. No 1P VPS text. |
| Lucid Trading | UNVERIFIED | 3P only: automation and copiers permitted, HFT banned. No 1P VPS quote. |
| Top One Futures | UNVERIFIED | 1P: VPS allowed with a static IP, notified in advance. Automation text conflicts in 3P. |
| Bulenox, DayTraders.com, Earn2Trade, OneUp, Tick Tick Trader, Leeloo, The Trading Pit, FundingTicks, Blue Guardian Futures, The Futures Desk (reported closed) | UNVERIFIED | 3P only or conflicting. **All flat daily** where a rule was found, except Leeloo (3 micros overnight on Performance, 3P) and The Trading Pit (Prime overnight, not weekends, 3P). |
| *Tradovate API* | not a route | Prop and eval accounts are not eligible. Needs a live account with at least $1k plus a ~$25/mo add-on (support-article snippet; community threads). |
| *Rithmic R\|Protocol* | UNVERIFIED | Dev kit, then test system, then conformance, then production. Whether a prop-firm Rithmic login may use it is unanswered (no 1P readable). |

### 2b. FX / CFD

| Firm | Verdict | Decisive text |
|---|---|---|
| **Velotrade** (DXtrade) | **PASS** | API: *"Open to all accounts from evaluation through funded. Connect any system in any language via the DXtrade REST and WebSocket API. No additional fee or approval required."* VPS: *"Permitted for legitimate routing and execution purposes."* EAs: *"Permitted within defined risk parameters."* (1P velotrade.com/blog/velotrade-review, "Last verified Nov 3, 2026", lane re-fetch). Terms 8.3: *"Use of Expert Advisors (automated trading software) is permitted"*, with (c) *"We reserve the right to restrict or prohibit specific EAs."* (1P velotrade.com/terms). **Caveat:** the API and VPS permissions are on 1P blog and marketing pages, not in the Terms. |
| **Blue Guardian** (MT5, Match-Trader, TradeLocker) | **PASS by route (c), EA on VPS** | *"EAs are allowed. You may use EAs (Expert Advisors) that you setup to suit your own strategy or trading style."* VPS/VPN are barred only to bypass copy, group or signal rules. *"We have no restrictions on holding trades over night or the weekend on all account types."* (1P help.blueguardian.com/en/articles/14062186) No API route confirmed. |
| FTMO | UNVERIFIED | *"The use of VPN/VPS is also generally allowed."* Algo trading allowed. Hyperactivity: *"more than 2,000 server requests per day"*. Overnight and weekend restrictions apply *"only to the Standard account type"*. (1P ftmo.com FAQ and trading rules.) Whether our own cTrader Open API client is allowed is not stated. |
| FundedNext (CFD) | FAIL | *"Accounts of $50,000 and above: VPS use is not permitted. Trades must be placed from your own device."* (1P help centre) |
| Alpha Capital | FAIL | Unsupervised EAs banned (prior 1P; re-fetch 404) |
| Instant Funding (Prime) | FAIL (3P) | EAs and copiers prohibited |
| The5ers, E8, FunderPro, FXIFY, FundingPips, Maven, Goat, Hola Prime, Fintokei, Seacrest | UNVERIFIED | EA clauses are mostly permissive where read. VPS and own-API text missing or 3P-only. No first-party confirmation that any firm allows a trader's **own** cTrader or TradeLocker API client. |

### 2c. Real stocks / ETFs

| Firm | Verdict | Decisive text |
|---|---|---|
| Trade The Pool | FAIL | *"prohibits automated bots, Expert Advisors, and copy-trading tools"*; *"A human person must personally place and authorize every single trade."* (1P) |
| PropShopTrader (Stocks Swing) | UNVERIFIED, closed | Overnight and weekend holds allowed, but Tickblaze is Windows-only with no API found. The help centre says new purchases ended 2026-08-18. |
| Lux (stock CFDs, MT5), SabioTrade, Maverick, others | UNVERIFIED | Lux allows its own EAs but caps at 2,500 server messages/day and has no VPS text. The rest are 3P or silent. |

## 3. Rules of the firms that pass

**Velotrade** (1P, `/forex` and `/blog/velotrade-review`, 2026-11-12; the deep-dive of 2026-10-04 for Terms detail):
- **Plans ($5k prices with code BOTS20):**
  - CLASSIC 1-Step: $54 (list $67). 10% target, **4% daily, 7% static**.
  - CLASSIC 2-Step: $43 (list $54). 10% then 5% target, 5% daily, 10% static.
  - PRO 1-Step: $32 (list $40). 10% target, **3% daily, 3% static**.
  - Sizes run up to $200k; their prices were not read.
- **Payouts and qualifying days:** 80% split, 90% with an add-on. **5 qualifying days of at least 0.8% profit** per phase. No consistency rule. News allowed.
- **Holding:** overnight and weekend holding permitted.
- **Costs:** commission per side on notional of 0.004% FX majors, 0.01% commodities, 0.03% index ETFs and single stocks, with no spread markup. **Overnight fee 0.05% of notional at 00:30 UTC on indices, commodities and stocks, weekends included.**
- **Leverage (challenge/funded):** index ETFs 6x/5x, commodities 6x/5x.
- **Single stocks:** close at least 24 h before earnings or ex-dividend.

**FundedNext Futures** (1P art. 17225788): EAs and bots allowed, VPS allowed, flat by 3:10 PM CT, no overnight or weekend holds, Tradovate or NinjaTrader. The drawdown type, prices and micro list were not on the page read. They are UNVERIFIED.

**Blue Guardian 1-Step Standard** (1P art. 14062186): **6% trailing on the highest closed-trade watermark**, locking at the start balance once +6% (+1% buffer) is reached. 4% daily, reset 5 pm EST. 9% target. **2-minute minimum hold.** On funded accounts, no trades within ±5 min of red-folder news. Prices not read.

## 4. Fit: which of our legs could trade there

**Population.**
- Source: `config/strategies.yaml`, re-parsed 2026-11-12, 62 legs.
- Kept: legs on non-crypto symbols with a `comms/strategy_evidence/<leg>.json` record whose `decision_rule.verdict` is `pass`.
- Hold times come from each record's committed trade ledger.

**Futures firms (all session-flat).** No fit.
- Every PASS futures and ETF leg holds overnight. Medians run from 32 h (`mgc_trend_1h`) to 1,032 h (`mes_trend_long_1d`). The shortest p10 is 6 h (`slv_trend_1h`).
- Nothing intraday has passed: Tradeify memo § 2–3, with `ict_scalp_mgc_15m`'s record at `harness_failed`.
- The ML side has the same problem. `ml_entry`'s ETF and crypto population and `ml_entry_eq_struct` are 1h holds on venue symbols, not CME micros, and the futures ML (RQ-20261112-09d2-03) failed its holdout.

**Velotrade CFDs.** Underlyings listed 1P: SPY, QQQ, IWM, gold, silver, WTI, TSLA/NVDA/AAPL. Mapping, one leg per (underlying, strategy family):

| Velotrade CFD | Leg(s) | Stage-0 record | Median hold | Net R/trade at Velotrade costs (window 2025-06-01..2026-10-19) |
|---|---|---|---|---|
| SPY | `spy_trend_long_1d` | pass (n=11) | 336 h | −0.43 (n=11) |
| QQQ | `qqq_trend_long_1d`, `qqq_pullback_1h` | pass, pass | 264 h, 91 h | +0.55 (n=5), −0.19 (n=49) |
| IWM | `iwm_trend_long_1d` | pass | 636 h | −0.19 (n=8) |
| gold | `gld_pullback_1d`, `gld_pullback_1h` | pass, pass | 672 h, 74 h | +0.89 (n=8), +0.11 (n=85) |
| silver | `slv_trend_1h`, `slv_pullback_1d` | pass, pass | 58 h, 312 h | +0.68 (n=64), +0.17 (n=10) |
| WTI | `uso_trend_1h` | pass | 48.5 h | +0.45 (n=51) |

**Excluded.**
- Duplicate gold-pullback-1d family: `iaum_pullback_1d`, `mgc_pullback_1d`.
- Not listed by Velotrade: TQQQ, QLD, GDX, TLT, IEF, SCHA.
- Record verdict `fail`: `mes_trend_long_1d`. The Tradeify memo cites a newer PASS unit, 78fc-57; the evidence record has not been refreshed. This is noted, not resolved here.
- `spy_pullback_1h`, `tlt_pullback_1h`: fail.

The overnight fee is why the equity legs go negative. With no swap, the same 9-leg book averages +0.456R per trade; with Velotrade's 0.05%/night it averages +0.248R.

**Blue Guardian.** It has SPX500 and XAUUSD (1P), so the S&P and gold legs map. US100, silver and oil are unconfirmed.

**FTMO.** Not mapped, because the symbol list is unread.

## 5. EV screen (RULE-PROP-FRONTIER-EV6M-20261112)

**Registration.** [`comms/research/prop_frontier/ev6m_rule.json`](../../comms/research/prop_frontier/ev6m_rule.json), committed in ae5f99203 and pushed before the first run. The runner is [`scripts/research/prop_frontier_ev6m.py`](../../scripts/research/prop_frontier_ev6m.py); it refuses to run without the rule file.

**Engine.** `scripts/research/prop_ev_sim.py` path mode at `--horizon-days 182`, the same engine as RQ-20261112-09d2-06. 3 seeds × 1,000 lives. Settings: risk 0.5% of start, daily-DD switch 0.8, leverage cap 5, fresh funded start.

**Costs** (Velotrade 1P):
- commission 6 bps round trip: 0.03%/side, which overcharges the commodity legs;
- slippage 3 bps;
- overnight fee 0.05% of notional per rollover, weekends included.

**Predicate** (primary book `VELO_ALL`, primary risk). BUYABLE iff all three hold:
- the minimum seed EV > 0;
- the mean EV > the zero-edge-null mean;
- the book's net-R 95% CI lower bound > 0.

**Scope.** Only Velotrade could be screened. FundedNext Futures has no fitting leg. Blue Guardian (trailing DD) is `not_attempted`, pending PI-20261112-D6UC5YT4-0003. CLASSIC 2-Step is `not_attempted`, because the simulator has no two-phase support.

| Plan | Book | Fee | EV 6m mean / worst seed | Zero-edge null | With rebuy, 6m | P(pass eval) | P(breach) | Verdict |
|---|---|---|---|---|---|---|---|---|
| **CLASSIC 1-Step $5k** | VELO_ALL (9 legs) | $54 | **+$44.83 / +$41.80** | −$41.13 | +$48.16 | 0.620 | 0.143 | **BUYABLE** |
| **PRO 1-Step $5k** | VELO_ALL | $32 | **+$21.40 / +$18.75** | −$27.37 | +$40.50 | 0.416 | 0.633 | **BUYABLE** |
| CLASSIC 1-Step | VELO_1H (4 legs) | $54 | +$62.77 / +$57.00 | −$38.79 | +$66.52 | 0.636 | 0.120 | descriptive |
| PRO 1-Step | VELO_1H | $32 | +$39.39 / +$36.63 | −$26.86 | +$69.67 | 0.469 | 0.618 | descriptive |
| CLASSIC 1-Step | VELO_1D (5 legs) | $54 | −$54.00 | −$54.00 | −$54.21 | 0.000 | 0.006 | descriptive |
| PRO 1-Step | VELO_1D | $32 | −$32.00 | −$32.00 | −$36.04 | 0.000 | 0.251 | descriptive |

At 1% risk (descriptive only), CLASSIC on VELO_ALL is +$15.40. PRO turns negative at −$26.59, because the 3% static floor dies faster. Full table: [`comms/research/prop_frontier/ev6m-20261112/verdict.json`](../../comms/research/prop_frontier/ev6m-20261112/verdict.json).

**Cross-checks.**
- The book's mean net R equals the trade-weighted per-leg means: (7.10 + 9.29 − 1.51 − 9.22 + 2.77 + 1.71 + 43.47 − 4.69 + 23.12) / 291 = 72.04 / 291 = 0.2476. This matches `book_edges.VELO_ALL.mean_r`.
- Every VELO_1D cell sits exactly at −fee. 42 trades over about 500 days never reach the 10% target inside 182 days at 0.5% risk.

**Why the pass is fragile (descriptive, not part of the rule).**
- **The CI lower bound is +0.0037R.** Recomputing without one leg at a time turns it negative for each of `slv_trend_1h` (−0.117), `uso_trend_1h` (−0.074), `gld_pullback_1d` (−0.019), `qqq_trend_long_1d` (−0.004) and `slv_pullback_1d` (−0.001).
- **The edge is in the commodity legs.** Their pooled CI is [+0.096, +0.681], n=218. The equity-ETF legs' CI is [−0.592, +0.245], n=73.
- **The nine legs were selected for passing Stage 0 on overlapping windows.** A 3-book Bonferroni z of 2.394 puts the book's lower bound at −0.050.
- **The ledgers are ETF proxies.** USO is not the WTI CFD, because of roll and contango, and GLD/SLV track spot only approximately. R-multiples transfer; the price paths are not identical.
- **Not modelled:** Velotrade Terms 5.3(b), *"An offer of a Funded Account is not guaranteed"*.

The descriptive reading of the 1h-only book is the stronger one. It has higher EV and a lower P(breach), but its own CI lower bound is −0.007, so it does not change the verdict.

**Prop SUPERSET.** This screen is the 6-month EV question. It is not the per-leg prop survival gate. Any leg added to a prop book still needs everything a real-money leg clears, **plus** `comms/prop_survival/<leg>.json` against the firm's drawdown limits (`prop-roster-gate-guard`).

## 5b. VELO-CFD-STAGE0: the commodity legs on the CFD underlying's own series (RULE-VELO-CFD-STAGE0-20261112)

**Registration.** [`comms/research/prop_frontier/velo_cfd_stage0_rule.json`](../../comms/research/prop_frontier/velo_cfd_stage0_rule.json), committed in 1f4d346a7 and pushed before the fetch and the run. Runner: [`scripts/research/velo_cfd_stage0.py`](../../scripts/research/velo_cfd_stage0.py). Verdict: [`comms/research/prop_frontier/velo-cfd-stage0-20261112/verdict.json`](../../comms/research/prop_frontier/velo-cfd-stage0-20261112/verdict.json).

**Population.**
- Four legs, with config fingerprints pinned in the rule and parameters unchanged from `config/strategies.yaml`:
  - `slv_trend_1h` on spot XAG/USD;
  - `uso_trend_1h` on Dukascopy E_LIGHT (WTI);
  - `gld_pullback_1h` and `gld_pullback_1d` on spot XAU/USD.
- Data: Dukascopy 1h bid bars, filtered to the US cash session to match each leg's ETF bar grid. Window 2019-01-02..2026-10-30, about 1,530 bars a year for each instrument (checked per year).
- Harness: the evidence producer's own argv (`regime_debt_matrix.build_harness_cmd`, all four `faithful`, no omitted levers) at fee 0.

**Costs** (per leg, stated in the rule):
- commission 2 bps RT (Velotrade 0.01%/side on commodities, 1P);
- slippage 3 bps RT;
- spread 3 bps RT on gold and 5 bps on silver and WTI (an **assumption**: the bars are bid-only and Velotrade's quoted spread was not read);
- overnight fee 0.05% of notional per 00:30 UTC rollover, weekends included (1P).

**Per-leg bar.** PASS needs all of:
- n ≥ 30;
- net R > 0;
- at least 60% of trading years positive;
- per-trade CI lower bound > 0 at z 2.241 (one-sided Bonferroni over 4 legs).

| Leg | n | Gross R | Cost R | Net R | Mean net R | CI lo (z 2.241) | Years positive | Verdict |
|---|---|---|---|---|---|---|---|---|
| `slv_trend_1h` | 321 | +97.56 | 95.27 | +2.29 | +0.007 | −0.346 | 4/8 | **FAIL** |
| `uso_trend_1h` | 244 | +15.79 | 36.16 | −20.38 | −0.084 | −0.320 | 2/8 | **FAIL** |
| `gld_pullback_1h` | 441 | +229.19 | 206.06 | +23.14 | +0.053 | −0.176 | 4/8 | **FAIL** |
| `gld_pullback_1d` | 62 | +34.17 | 37.72 | −3.56 | −0.057 | −0.517 | 3/8 | **FAIL** |

The book step and the drop-one check are NOT_APPLICABLE, because no leg passed. Cross-check: gross − cost = net in every row (for example, 229.19 − 206.06 = 23.14 for `gld_pullback_1h`).

**Descriptive reads (not part of the rule, run after the verdict).**
- **The proxy holds.** The same spot ledgers clipped to 2025-06+ at Velotrade costs give +0.39R per trade on `slv_trend_1h` (n=66), +0.62R on `gld_pullback_1h` (n=79), +0.25R on `uso_trend_1h` (n=50) and +0.67R on `gld_pullback_1d` (n=10). That is close to the ETF-ledger figures behind the EV pass, so the ETF ledgers were a fair proxy. **The problem is the window, not the instrument.**
- **The cost is mostly the overnight fee.**

  | Leg | Net R per trade, 2019-26, with no overnight fee | Years positive |
  |---|---|---|
  | `gld_pullback_1h` | +0.358 | 7/8 |
  | `slv_trend_1h` | +0.206 | 7/8 |
  | `gld_pullback_1d` | +0.514 | 6/8 |
  | `uso_trend_1h` | +0.009 | 4/8 |

  With a 0.74% median stop (`gld_pullback_1h`) and holds of about 3 nights, 0.05% per night is about 0.2R per trade on its own.
- **Lead, filed rather than claimed.** The gold and silver legs look robust where financing is zero or small, as on CME futures (MGC, SIL), but that has not been tested on a futures series at futures costs. Filed as PI-20261112-D6UC5YT4-0004. It belongs to the IB/real-money ladder, not to a prop firm: every futures prop forces positions flat daily (§ 2a).

## 6. Ranked shortlist and buy-points

| # | Firm · plan | Why here | Buy-point: buy when ALL hold |
|---|---|---|---|
| ~~1~~ **closed: NOT BUYABLE (§ 5b)** | **Velotrade CLASSIC 1-Step $5k ($54)**, CFD book: commodity legs first (`slv_trend_1h`, `uso_trend_1h`, `gld_pullback_1h`, `gld_pullback_1d`), equity-ETF legs only if they clear their own CFD re-test | Passes the device filter on 1P text; **integration already live** (`velotrade_1`, DXtrade REST); overnight and weekend holds; static DD; the registered EV rule says BUYABLE. PRO ($32) also passes, but with P(breach) 0.63 | (1) **VELO-CFD-STAGE0** (PI-20261112-D6UC5YT4-0001): each commodity leg PASSes Stage 0 on the spot or CFD series at Velotrade costs including the overnight fee. (2) **VELO-INSTR-READ** (PI-…-0002): the read-only probe shows the gold, silver and WTI symbols exist on our Velotrade login, with lot and multiplier. (3) Re-run RULE-PROP-FRONTIER-EV6M on the book that survives (1); it still says BUYABLE. (4) Each leg has its `comms/prop_survival/<leg>.json` PASS (SUPERSET). Then the operator chooses: a second Velotrade account for the CFD book, or adding the legs to `velotrade_1` (Tier 3). The first trade is the one-small-trade mechanical check (OPERATING-PLAN § 2; DXtrade REST mechanics are already proven on `velotrade_1`, the new instrument class is not). |
| **2** | **FundedNext Futures** (CME micros), plan to be chosen | The only futures firm whose own help centre allows bots **and** a VPS. It fits the operator's CME-micro priority once a session-flat leg exists. | (1) A session-flat leg PASSes Stage 0 at Tradovate-class costs **flat by 15:10 CT**: RQ-20261112-09d2-05 (MNQ_OR15 on real CME) or -04 (`ict_scalp_mgc_15m`), re-cut to the earlier cutoff. (2) Its prices, DD type and micro list are read 1P. (3) The EOD-trailing survival rule (09d2-02's) PASSes on that plan. (4) A headless Tradovate-web executor passes a dry run from the VM: fill, read back, no submit, flat before 15:10 CT. (5) The operator's written question to FundedNext ("a sole-owned bot deciding on a cloud server and placing orders through a headless browser on Tradovate web — allowed?") is answered yes. **Today: 0 legs meet (1).** |
| **3** | **Blue Guardian 1-Step** (SPX500, XAUUSD; MT5) | 1P allows EAs and VPS, and overnight and weekend holds. But the route is an MT5 EA, which we have no path for, and the drawdown is trailing. | (1) PROP-TRAILING-DD-SIM (PI-…-0003) lands, and RULE-PROP-FRONTIER-EV6M re-run on Blue Guardian says BUYABLE. (2) An MT5 runner exists on a VM (Wine or a Windows VPS; build not scoped). (3) Prices read 1P. Velotrade (the old rank 1) failed on its overnight fee, and Blue Guardian also charges CFD swaps, so read its swap table before any simulator work. |
| 4 | FTMO Swing (cTrader / MT5) | EA and VPS allowed 1P. | Hard filter first: a 1P statement that a trader's own cTrader Open API client is allowed, plus the symbol list. No work queued. |

**After § 5b the shortlist has no buyable plan today.** FundedNext Futures (row 2) is the live candidate. Its gate is a session-flat futures leg passing Stage 0, which is the same critical path as the Tradeify futures memo: FUT-INTRADAY-DUKA-LANE and FUT-CME-INTRADAY-HIST, then RQ-20261112-09d2-04/-05. AM-TRADING relays their verdicts. Blue Guardian and FTMO charge swaps on CFDs too. Until their swap tables are read, the § 5b cost finding is a reason to expect the same outcome there.

Not shortlisted: MyFundedFutures, Lucid and Top One Futures (UNVERIFIED and session-flat anyway). They are worth a 1P re-read only if the FundedNext route fails.

## 7. What this lane did not establish

- Velotrade's DXtrade symbol names, lot sizes and session hours for its CFDs. That is PI-…-0002; nothing is readable before a login.
- Any firm's rules **measured** from our own egress. Every PASS is a sentence on a page. Velotrade's API and VPS permissions are on 1P blog and marketing pages, and its Terms 8.3(c) reserves the right to ban specific EAs.
- Prices for Velotrade sizes above $5k, FundedNext Futures' prices and drawdown type, and Blue Guardian's prices.
- Rithmic R|Protocol eligibility for prop logins. Whether MFFU or Lucid allow an unsupervised server bot.
- Coverage. About 190 searches and fetches were made across the four clusters (the sub-agents' tool-call counts), and many first-party pages were blocked (§ 1). An UNVERIFIED row is a coverage statement, never a permission.

## Follow-ups filed (pipeline, live work store)

| Id | What | clears_when (machine-checkable) | Owner |
|---|---|---|---|
| PI-20261112-D6UC5YT4-0001 | **done 2026-11-12: FAIL, 0/4** (§ 5b). VELO-CFD-STAGE0: CFD-series Stage 0 for `slv_trend_1h`, `uso_trend_1h`, `gld_pullback_1h`, `gld_pullback_1d` at Velotrade costs | a `research/results` row exists for a registered Stage-0 unit naming each of the four legs on a spot/CFD series at Velotrade costs (any verdict) | manager → research lane |
| PI-20261112-D6UC5YT4-0002 | **killed 2026-11-12**: its only purpose was buy-point condition 2 for a Velotrade CFD account, and § 5b closed that buy. The draft diff is kept in Appendix A. VELO-INSTR-READ: add the gold/silver/WTI/SPY/QQQ/IWM spellings to the read-only `velotrade-api-probe` and dispatch once while flat (Tier 2) | a probe run log shows `symbols_present` true or false for a gold, a silver and a WTI symbol on `velotrade_1` | manager → Tier-2 build lane (operator OK in chat) |
| PI-20261112-D6UC5YT4-0004 | GOLD-SILVER-FUT-STAGE0: Stage 0 for the `gld_pullback_1h` / `slv_trend_1h` logic on CME MGC / SIL continuous series at IB futures costs (no overnight financing); lead from § 5b | a `research/results` row exists for a registered unit naming MGC or SIL with either leg's logic (any verdict) | manager → research lane (IB/real-money ladder) |
| PI-20261112-D6UC5YT4-0003 | PROP-TRAILING-DD-SIM: give `prop_ev_sim.py` an EOD/intraday-trailing drawdown (generalise 09d2-02's simulator) | `prop_ev_sim.py` accepts `drawdown_type` `eod_trailing` without raising | manager → research-tooling lane |

**Operator external actions (optional, no credentials needed).** These are written questions to firm support:
- Velotrade: does the API/VPS permission cover CFD accounts, and is it binding beyond the blog?
- FundedNext Futures: is the headless-browser route allowed (§ 6 row 2)?

## Appendix A. VELO-INSTR-READ draft diff (not applied; PI-…-0002 killed after § 5b)

AM-TRADING asked for the exact diff so it would be ready once an operator OK arrived. It is kept here in case a later unit revives the Velotrade CFD route. It is a read-only change to an allowlisted Tier-2 system action (`velotrade-api-probe`): REST GETs only, as before.

```diff
--- a/scripts/prop/velotrade_api_probe.py
+++ b/scripts/prop/velotrade_api_probe.py
@@
 SYMBOLS = ["ETHUSD", "SOLUSD", "XRPUSD", "BTCUSD", "ETH/USD", "SOL/USD", "XRP/USD"]
 WANTED = ("ETH", "SOL", "XRP")
+# VELO-INSTR-READ (PI-20261112-D6UC5YT4-0002): the CFD underlyings Velotrade lists 1P
+# (velotrade.com/blog/velotrade-review: gold, silver, WTI, SPY/QQQ/IWM). The DXtrade spelling
+# is unknown, so each is tried slashed and unslashed; ETHUSD stays the positive control.
+VELO_CFD_SYMBOLS = ["ETHUSD", "XAUUSD", "XAU/USD", "GOLD", "XAGUSD", "XAG/USD", "SILVER",
+                    "USOIL", "USOIL/USD", "WTI", "SPY", "SPY.US", "QQQ", "QQQ.US", "IWM", "IWM.US"]
+VELO_CFD_WANTED = ("ETH", "XAU", "XAG", "OIL", "SPY", "QQQ", "IWM")
@@ def main(...):
-        symbols = TRADEIFY_SYMBOLS if account == "tradeify_1" else SYMBOLS
-        wanted = TRADEIFY_WANTED if account == "tradeify_1" else WANTED
+        cfd = os.environ.get("ACTION_SYMBOL_SET") == "velo_cfd" and account == "velotrade_1"
+        symbols = TRADEIFY_SYMBOLS if account == "tradeify_1" else (VELO_CFD_SYMBOLS if cfd else SYMBOLS)
+        wanted = TRADEIFY_WANTED if account == "tradeify_1" else (VELO_CFD_WANTED if cfd else WANTED)
```

It also needs:
- a fixed-choice `symbol_set: default | velo_cfd` input on the `velotrade-api-probe` branch of `.github/workflows/system-actions.yml`, rejecting any other value, the same way `account_id` is handled;
- the row in `docs/claude/system-actions.md` updated.
