# Tradeify FUTURES: account facts, fit, ML, execution path, buy-point (2026-11-12)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · rows **TRADEIFY-FUTURES-EVAL** (the operator's 2026-11-10 row; TRADEIFY-FUTURES-FRONTIER folded into it as a duplicate) and **PROP-PLAN-EV-6M** · lane session_01AFoLuLwRU7eg9KzpMcxWu · dispatched by Manager Session 2026-11-11a · read-only research; no account, credential, order or config touched.

**Gates this adds or changes: none.**

The operator asked on 2026-11-12 at about 08:05Z (verbatim): *"let me know when we're queued up to do the frontier research for the Tradeify Futures account. I would like to get that up and running sooner rather than later. So let's see if we have things, if we can trade things there within the parameters of the account that suit anything we have, or if we can build an ML that can do that. And let me know when I should start looking into purchasing another account there."*

**Subject.** This is the Tradeify **futures** brand: CME futures, held on Tradovate, Rithmic or WealthCharts. It is not `tradeify_1`, which is Tradeify 247's DXtrade crypto-CFD account. [`tradeify-platforms-2026-10-15.md`](tradeify-platforms-2026-10-15.md) did not examine the futures brand.

## 0. The answer

1. **None of our existing legs can trade there.** Tradeify futures forces every position flat by **4:45 PM ET**, with no overnight or weekend holds.
   - Our two futures legs that pass Stage 0 hold for days. `mgc_pullback_1d` has a median hold of 14.5 days, and `mes_trend_long_1d` has a median of 45 days.
   - The third, `mhg_pullback_1d`, trades a product Tradeify does not list (MHG).
   - `mgc_trend_1h` fails Stage 0, and `ict_scalp_mgc_15m` has never been measured.
2. **A new session-flat leg tested today did not pass.** RQ-20261112-09d2-01 tested an opening-range breakout on MES, MNQ and MGC at Tradeify costs: 0 of 6 cells PASS.
   - MNQ is the closest: +0.06R per trade, positive in 5 of 6 years, and positive on the holdout. It misses only the multiplicity-deflated edge clause.
   - MES and MGC lose most of their gross edge to commission plus slippage.
3. **The first ML attempt did not pass.** A gbdt meta-label filter (RQ-20261112-09d2-03) improved every walk-forward year from 2021 to 2024, then gave nothing on the frozen 2025-26 holdout.
4. **Automated trading is allowed, but the compliant execution path is narrow.** Bots must be your own, not HFT, used at Tradeify only, and enabled on video "on your own PC". Two further limits:
   - **No Tradovate API on evaluation or sim-funded accounts.**
   - **No login through a VPS.**

   The compliant shape is our phone/PC executor pattern (the `breakout_2` precedent) on the operator's device. A TradersPost webhook bridge is the other option, but it is supported only by third-party sources.
5. **Six-month EV across every prop plan the repo models: none is positive** (§ 6, RQ-20261112-09d2-06, 0/27 cells buyable). The least-negative are the cheap turbo 1-steps, around −$9 per purchase.
6. **Buy-point: not yet.** Do not buy an account now. § 5 lists the conditions. The earliest realistic date is set by the two data/infra rows below, not by the calendar.

## 1. Account facts (public sources, fetched 2026-11-12)

`help.tradeify.co` returns 403 to scripted fetches, so the same Intercom help centre was read at `https://intercom.help/tradeify/en/articles/<id>`. Its index links to help.tradeify.co, so these are first-party pages. Citations below give the article id under that prefix. The pages carry only relative dates (for example "updated over 3 weeks ago").

Status key:
- **C**: confirmed on a first-party page.
- **S**: secondary (third-party source only).
- **U**: unverified.

Two clauses were checked against the raw page text a second time: the 4:45 PM cutoff, and the bot rule's "live video … on your own PC". So was the FTA, at `https://tradeify.co/funded-trader-agreement` (fetched directly).

| Fact | Value | Source | Status |
|---|---|---|---|
| **Plans and prices** (one-time payment; no activation fee; promotions ignored) | **Growth** evaluation: 25K/50K/100K/150K at $99/$145/$255/$369; resets $60/$95/$169/$229. **Select** evaluation: $109/$165/$265/$369; 300K is $570. **Lightning** (instant funded, no evaluation): $345/$492/$660/$796. Profit target $1.5k/$3k/$6k/$9k. Minimum days: Growth 1, Select 3. | 14369021, 10468246 | C |
| **Drawdown type** | **End-of-day trailing**. The floor updates at the end of the day, but it is **enforced in real time against net liquidation, unrealized P&L included**. Touching it fails the account. Funded accounts lock the floor at start + $100 once the EOD balance reaches start + DD + $100, or at the first payout request. Evaluations never lock. | 10495897 | C |
| **Drawdown level** | 25K $1,000; 50K $2,000; Growth 100K $3,500 and 150K $5,000; Select 100K $3,000 and 150K $4,500; Lightning 100K $4,000 and 150K $5,250. | 10495897, 10495915, 12853921, 10495938 | C |
| **Daily loss limit** | **Soft**: trading pauses until 6 PM ET and the account does not fail. Growth: $600/$1,250/$2,500/$3,750. Lightning: 50K $1,250. Select evaluation and Select Flex: none. | 10468321 | C |
| **Consistency rule** | Largest day's profit ÷ total profit; gates payouts only. Growth: none in evaluation, 35% funded. Select: 40% in evaluation (50% with the add-on), none funded. Lightning: 20%, 25%, then 30%. | 10468320 | C |
| **Maximum contracts** | 10 micros = 1 mini. Growth and Lightning: 1/4/8/12 minis from day one, so **50K = 40 micros**. Select funded accounts scale up from 2–3 minis. | 10495915, 10495938, 12853921 | C (the Select 25K evaluation is shown as both 1 and 2 minis in different articles) |
| **Products** | CME, CBOT, NYMEX and COMEX (EUREX on Tradovate only). Micros: MES, MNQ, MYM, M2K, MCL, MGC, M6E, M6A. **Not offered: MHG, SIL or any crypto derivative (MBT, MET).** | 10468222 | C |
| **Holding** | **Flat by 4:45 PM ET** (12:59 PM ET on half days). No holding past the close, overnight or over a weekend. Open positions are auto-closed without failing the account. | 10495876 | C |
| **News** | "We do not have any rules against or guidelines around trading news events." | 10495874 | C |
| **Platforms** | Tradovate (with NinjaTrader and TradingView), Rithmic (Tradesea, Quantower, Sierra Chart, R\|Trader) or WealthCharts. No ProjectX. | 10468221 | C |
| **Automation** | "we allow the use of bots and algorithms under certain conditions". Conditions: you are the sole owner; Tradeify scans other accounts for similar orders; "a live video of you enabling the code on your own PC"; exclusive to Tradeify ("using it across multiple firms is against Tradeify's policy"); no HFT bots. The FTA has the same text (FTA § 6.6). | 10468318 | C |
| **Data-feed clause** | FTA § 6.3: "Trading based on an external or delayed data feed is not allowed." | tradeify.co/funded-trader-agreement | C |
| **VPS / VPN** | A VPS may be used for trading after a normal login. **Logging in through a VPN or VPS is not allowed.** | 12268494 | C |
| **Tradovate API** | "The Tradovate API is only available for LIVE funded accounts. It is not available for evaluation or sim funded accounts." | 10468222 | C |
| **Tradovate API terms** | Your own LIVE Tradovate account with more than $1,000, plus an API add-on at about $25/month. Real-time data over the API reportedly needs a CME sub-vendor licence (about $290–390/month). | community.tradovate.com/t/api-access/12819, /t/api-access-requirements/7769, /t/is-cme-sub-vendor-requirement-for-api-access-is-290-per-month/6215 | S |
| **Webhook bridge** | TradersPost automates Tradeify through Tradovate logins. | blog.traderspost.io/article/automate-tradeify-with-traderspost | S; TradersPost pricing U |
| **Payouts** | 90/10 split on sim-funded accounts. Growth 50K: 5 days above $150 profit; minimum balance $53k; minimum payout $500; cap $1.5k on the first payout, rising to $3k. Lightning 50K: first-payout goal $3k, then $2k; minimum $1k; cap $2k, then $2.5k. Select Flex: payout every 5 winning days, up to 50% of profit, cap $2,500. | 11083796, 10495932, 12853966 | C |
| **Commissions (round turn, all-in)** | **MES/MNQ/MYM/M2K $1.82; MGC/MCL $2.12**; ES/NQ $5.76. Level 1 CME data is free with the non-professional agreement. | 10468315 | C |
| **Other** | Microscalping: a payout needs more than 50% of trades and more than 50% of profit from trades held over 10 s. Opposite directions in one product group across your accounts are prohibited. At least 1 trade a week. At most 5 sim-funded accounts per person. | 10468318, 10495868, 10468251 | C |

## 2. Fit: our legs against these rules

**Population.** The futures legs on `ib_paper`'s roster in `config/accounts.yaml` (re-parsed 2026-11-12) are `mes_trend_long_1d`, `mgc_pullback_1d`, `mhg_pullback_1d`, `mgc_trend_1h` and `ict_scalp_mgc_15m`, plus the multi-symbol `claude_desk`.

| Leg | Stage 0 (graded unit) | Tradeify fit |
|---|---|---|
| `mgc_pullback_1d` | PASS: RQ-20261101-78fc-38 (n=68, GC=F 1d 2018-06..2026-10, +17.7R, 5/6 folds) | **No.** Median hold 14.5 days (min 1, max 125). Median stop $766 per micro, p90 $2,419: one p90 stop exceeds the 50K drawdown. Computed from the unit's trade ledger. |
| `mes_trend_long_1d` | PASS: 78fc-57 (n=31, ES=F 1d, +16.9R, 4/6) | **No.** Median hold 45 days (min 9). Median stop $895 per micro. It also uses `tp_r: 50`, which the TP doctrine counts as non-compliant. |
| `mhg_pullback_1d` | FAIL: 78fc-39 | **No.** MHG is not offered. |
| `mgc_trend_1h` | FAIL twice: 78fc-26, RQ-20261104-001 | **No.** |
| `ict_scalp_mgc_15m` | Never measured. 78fc-13 is blocked because no 15m feed is wired. | **Unknown.** It is the only intraday candidate; RQ-20261112-09d2-04 (blocked) tests it session-flat. |

**Prior prop survival records.** `comms/prop_survival/` has none for a futures leg. Its simulator, `scripts/research/prop_ev_sim.py`, raises an error on any drawdown that is not static, so it cannot model Tradeify. An EOD-trailing simulator was written for this lane.

### 2a. A new session-flat leg: RQ-20261112-09d2-01 (registered before the run, commit 249cd4c7d)

**Data.** Dukascopy 5m bid **proxies**: E_SANDP_500 CFD for MES, E_NQ_100 CFD for MNQ, and XAU/USD spot for MGC. Window 2019-01-01 to 2026-10-31. The yearly CSV fingerprints are in the result row.

**Costs.** Per contract: $1.82 (MES, MNQ) or $2.12 (MGC), plus 1 tick on every market or stop fill.

**Rules.** Opening range of 15 or 30 minutes from 09:30 ET. Stop at the far side of the range, TP at 2R, one decision per day, no entry from 15:00 ET, flat at 16:40 ET.

**Bar.** Per cell, all of:
- discovery 2019-2024 with n ≥ 100;
- net R > 0, with at least 4 of 6 years positive;
- the per-trade CI lower bound > 0 at a Bonferroni z of 2.638;
- holdout 2025-26 with n ≥ 30 and net R > 0.

| Cell | Discovery n | Net R | Gross R | Cost R | Positive folds | Mean R | CI lower | Holdout n | Holdout R | Median $ risk per micro | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MES_OR15 | 1490 | +13.95 | 114.29 | 100.34 | 3/6 | +0.009 | −0.077 | 455 | +9.97 | $79 | FAIL |
| MES_OR30 | 1474 | −16.70 | 64.82 | 81.52 | 2/6 | −0.011 | −0.086 | 453 | −2.44 | $100 | FAIL |
| **MNQ_OR15** | 1488 | **+89.26** | 123.13 | 33.87 | **5/6** | **+0.060** | **−0.020** | 456 | **+11.33** | $171 | FAIL (edge clause only) |
| MNQ_OR30 | 1455 | +49.87 | 77.02 | 27.15 | 5/6 | +0.034 | −0.034 | 443 | −1.01 | $212 | FAIL |
| MGC_OR15 | 1510 | −62.98 | 62.38 | 125.36 | 2/6 | −0.042 | −0.119 | 466 | +1.28 | $70 | FAIL |
| MGC_OR30 | 1459 | −51.92 | 43.87 | 95.79 | 0/6 | −0.036 | −0.101 | 452 | +16.36 | $88 | FAIL |

**Cross-checks.**
- Net = gross − cost in every row (for example, MNQ_OR15: 123.13 − 33.87 = 89.26).
- MNQ_OR15's yearly folds sum to +89.26.
- Exit reasons sum to the population (850 + 312 + 782 = 1944).

**Diagnosis.** The cost stack decides MES and MGC. Their ranges are tight, so $1.82–2.12 plus two ticks is 5–9% of the risk on every trade, and that is about the size of the gross edge. MNQ has the widest stop in dollars per micro, so costs are 27% of gross. Its edge is visible but cannot be separated from zero at the deflated bar on a proxy feed.

Proxy caveat: the CFD session ends around 16:15 ET, so forced-flat exits take the last proxy bar. That is a difference from the futures, not a bias in a known direction.

### 2b. Survival: RQ-20261112-09d2-02

The new simulator models Growth, Select and Lightning 50K:
- an EOD-trailing $2,000 drawdown, enforced intraday through each trade's MAE;
- the soft daily loss limit;
- the payout rules and caps above;
- at most 40 micros, list fees, and the 90% split.

It runs 5 seeds × 2,000 paths, sampling trading days i.i.d. from 2019 to 2026. It reports EV against the **zero-edge null**: the same ledger re-centred to mean 0, with costs, stops and MAE unchanged.

**Verdict: NOT_APPLICABLE**, because no Stage-0 cell passed.

The descriptive run on MNQ_OR15 is in `comms/research/RQ-20261112-09d2-02/local-20261112/verdict.json`. It is not a verdict. It shows two things:
- At $300 risk per trade, the **null alone is +EV**: Lightning +$325, Growth +$22. The payout structure rewards variance, so "EV > 0" by itself would pass a coin-flip. This is the same failure class as PI-20261030-9KC5G3FG-0007, and the rule requires EV above the null for that reason.
- At the primary $200 risk, Lightning shows EV +$276 against a null of −$101, with P(breach) 0.52. This is on a cell that failed Stage 0, so it says only that a real edge of this size *would* clear the gate. That is why the buy-point keys on Stage 0.

## 3. ML: can a model trade it?

**Data we have for futures.**
- Daily continuous series (GC=F, ES=F, HG=F) back to 2018 via yfinance.
- yfinance 1h at about 720 days, and 15m at about 60 days.
- Dukascopy proxies for S&P, Nasdaq and gold at 1m–1d back to at least 2019. These were fetched in seconds per year from this sandbox with `dukascopy-python==4.0.1`.
- No real CME intraday history is in the repo: [`programmes/06-DATA-INFRA.md`](programmes/06-DATA-INFRA.md) § 2.1 records Databento and IB tick/depth as verified absent.
- Point-in-time: the proxies are bar-close OHLC with no revisions. The futures roll is absent because the proxies do not roll.

**Smallest question that answers "does a model clear the bar on these instruments at these costs".** That is RQ-20261112-09d2-03:
- a gbdt meta-label over the same session-flat ORB candidates, 8 pre-bar features;
- trained strictly before it scores;
- a frozen holdout for 2025-26;
- PASS iff the uplift in kept-vs-all net R has a paired-bootstrap 95% CI lower bound above 0, kept n ≥ 60, and kept net R > 0.

**Result: FAIL.**
- Holdout: kept trades (n=1437) average −0.0008R; all trades (n=2725) average +0.0130R. The uplift CI lower bound is −0.052.
- Walk-forward: the filter beat taking every trade in each year from 2021 to 2024 (for example, 2022 kept +0.086R against +0.027R for all).

That gain did not carry into the holdout. This closes the exact configuration (these features, gbdt, median threshold), not the family. A different family, such as a sequence model or a regime-conditioned direction model on MNQ, would be a new unit in the frontier scan. It needs the real-contract history row first.

## 4. Execution path

Three paths exist. Two are ruled out or not yet usable, and one is the compliant default.

| Path | Mechanics | Tradeify compliance | Effort (estimate) |
|---|---|---|---|
| **Tradovate API** (new-broker skill: package, factory, integrator, executor) | REST/WebSocket from the VM | **Not available** on evaluation or sim-funded accounts (10468222). Usable only on a LIVE funded ("Elite Live") account, which also needs a LIVE Tradovate account with more than $1k and the about-$25/month add-on (S). | 1–2 weeks once allowed. Not a path for the first account. |
| **Phone/PC executor** (`breakout_2` precedent: `src/prop/phone_executor.py`; the VM emits tickets, a device on the operator's network claims and places them) | The Tradovate mobile/web UI is driven on the operator's own device. It runs under the operator's login, IP and device. | **Best fit for the clauses we could read.** "Live video of you enabling the code on your own PC" and "no login via VPS" both point to the operator's device. Ownership and exclusivity hold if the leg runs at no other firm. **Risk:** FTA § 6.3, external data feed. Signals computed on our feed (IB or Dukascopy) could be read as "trading based on an external feed". The mitigation is to price signals from the Tradovate quote on the device, or to get written confirmation. | 2–4 weeks. New UI scripts for the Tradovate ticket and bracket, plus the session-flat close before 16:45 ET. The claim, ticket, kill-switch and trail plumbing exists. |
| **TradersPost webhook** | The VM posts a signal; TradersPost places it through the Tradovate login | Tradeify does not list it. Only TradersPost's own blog says it works (S). A third party holds account access, which sits awkwardly with "no one else has access". | Days, plus a subscription (price U). Use only with written Tradeify approval. |

**Risk.** There is ToS risk in all three: our 24/7 server-side decision engine is not "your own PC". Before anything trades, the operator should get a **written answer from Tradeify support**: is a sole-owned bot that decides on a cloud server and executes through the operator's device allowed, and does § 6.3 cover our own market-data feed? That is the operator's external action. No credentials and no orders are needed to ask.

## 5. Buy-point

**Conditions.** Buy a Tradeify futures account when ALL of these hold:

1. **Edge.** At least one session-flat leg PASSes Stage 0 at Tradeify costs **on the real CME contract**. Candidates:
   - RQ-20261112-09d2-05: MNQ_OR15 on real MNQ, at the deflated bar.
   - RQ-20261112-09d2-04: `ict_scalp_mgc_15m` transferred.
   - A new family.

   A proxy-only PASS is not enough.
2. **Survival.** That leg PASSes RULE-RQ-20261112-09d2-02 at $200 risk per trade on the plan you would buy: EV > 0 at every seed and above the zero-edge null. The result is recorded as `comms/prop_survival/<leg>.json`.
3. **Execution.** The executor path (§ 4, the phone/PC executor) is built and passes a dry run: it fills the ticket form, reads it back, does not submit, and closes before 16:45 ET.
4. **Permission.** Tradeify confirms in writing that the automation setup is allowed (§ 4).

Then buy the cheapest plan the survival result favours. Today's descriptive numbers hint at Lightning or Select, but the rule decides. The first trade is the mechanical soak: one small trade (OPERATING-PLAN § 2).

**When.** Today 0 legs meet condition 1, so there is no date. The critical path is two queued rows:
- **FUT-INTRADAY-DUKA-LANE** (tier 1). This wires 5m/15m into `exit_lever_ablation` and unblocks 09d2-04 and 78fc-13. It is small: likely a day of a lane's work.
- **FUT-CME-INTRADAY-HIST.** This adds real CME intraday history and unblocks 09d2-05. If IB's gateway serves it, that is a few days. If it needs Databento, it is a spend decision for the operator.

If one of those units then passes, conditions 2–4 take about 2–4 more weeks, mostly the executor. **The earliest plausible buy is therefore early-to-mid December 2026.** That is an estimate that holds only if a leg passes. The current promotion (code "NOV", ending 13 Nov) is not a reason to buy before condition 1.

## 6. Which prop plan has the highest expected return over 6 months? (PROP-PLAN-EV-6M, RQ-20261112-09d2-06)

**Answer: none is positive.**
- Over a 182-day horizon, buying any prop plan the repo models loses money in expectation. That holds both for the book our three live prop accounts run (`trend_donchian_eth_4h` + `trend_donchian_sol_4h` + `ml_entry`) and for each leg alone.
- 0 of 27 cells (9 rulesets × 3 books) clear the rule. The rule needs all three: EV > 0 at every seed, EV above the zero-edge null, and the book's edge CI lower bound > 0.
- The least-negative plans are the cheap 3%-drawdown "turbo" 1-steps: Propr Turbo (−$9.06) and Breakout Turbo (−$9.79).
- Tradeify futures plans sit at −fee, because no leg is eligible for them.

**Model.**
- Engine: `scripts/research/prop_ev_sim.py` account lives at `--horizon-days 182`: 3 seeds × 1,000 lives per cell, path mode.
- Settings: risk 0.5% of start balance, daily-drawdown switch at 0.8, and the conservative current cost stack (11 bps commission, 3 bps slippage, 0.0003/day swap), applied the same way at every firm.
- Null and edge clause: from `scripts/research/prop_gate.py`.
- Runner: `scripts/research/prop_plan_ev_6m.py`.
- Registration commit: f7bfc08da, pushed before the run.

**Book (ROSTER) edge, cur arm:** n=620, mean +0.059R, 95% CI [−0.050, +0.168].

| Plan (ruleset) | Fee | EV over 6 months, per purchase (mean / worst seed) | Zero-edge null | With rebuy, 6-month share | P(pass eval) | P(breach) | Verdict |
|---|---|---|---|---|---|---|---|
| Propr Turbo 1-step | $25 | −$9.06 / −$9.70 | −$18.78 | −$13.50 | 0.198 | 0.565 | NOT BUYABLE |
| Breakout Turbo 1-step (`breakout_2`'s plan) | $20 | −$9.79 / −$10.83 | −$16.03 | −$14.80 | 0.194 | 0.544 | NOT BUYABLE |
| Velotrade Pro 1-step | $32 | −$29.83 / −$30.95 | −$31.37 | −$45.27 | 0.138 | 0.480 | NOT BUYABLE |
| Breakout 2-step | $45 | −$35.01 / −$36.12 | −$41.67 | −$39.27 | 0.163 | 0.227 | NOT BUYABLE |
| Propr Classic 1-step | $60 | −$47.06 / −$47.91 | −$55.45 | −$53.04 | 0.159 | 0.234 | NOT BUYABLE |
| HyroTrader (lenient) | $59 | −$50.42 / −$52.07 | −$55.85 | −$56.42 | 0.169 | 0.232 | NOT BUYABLE |
| HyroTrader (strict) | $59 | −$50.49 / −$52.91 | −$56.42 | −$60.25 | 0.162 | 0.305 | NOT BUYABLE |
| Velotrade Classic 1-step (`velotrade_1`'s plan) | $54 | −$50.74 / −$50.98 | −$52.94 | −$54.54 | 0.175 | 0.153 | NOT BUYABLE |
| Tradeify 247 1-step 10K (`tradeify_1`'s plan) | $120 | −$108.80 / −$110.37 | −$116.63 | −$121.70 | 0.092 | 0.214 | NOT BUYABLE |
| Tradeify futures Growth / Select / Lightning 50K | $145 / $165 / $492 | −fee (nothing eligible to trade) | — | — | — | — | NOT BUYABLE |

The ETH4H-only and ML-only books rank the same way and are all negative. Full table: `comms/research/RQ-20261112-09d2-06/local-20261112/verdict.json`.

**Why every plan loses over 6 months.**
- The book is low-frequency: 136 ETH and 103 SOL trades in 3 years.
- Inside 182 days it reaches the evaluation target only 9–20% of the time, so most lives end at the horizon still in evaluation, with the fee spent.
- The earlier per-life results have no horizon, and a life can run for years. `trend_donchian_eth_4h` on `tradeify_1` showed +$112 per life in the 2026-11-06 re-test, and it still FAILed the V3 edge clause. The 6-month framing the operator asked for removes that tail.

**Caveats.**
- The ML ledger covers 1 year (2025-10..2026-09), while the trend ledgers cover 3 years.
- Breakout's live risk is 0.35%, not the uniform 0.5% used here.
- Commission is the current stack at every firm, not each firm's own.

The unit has `cadence: weekly`, so the same rule re-applies to refreshed ledgers. A standing weekly re-run needs a queue template; that is noted on PROP-PLAN-EV-6M.

## 7. The operator's four questions (row TRADEIFY-FUTURES-EVAL, 2026-11-10)

1. **Is anything we already trade usable on the other Tradeify accounts?** No.
   - The futures accounts force positions flat by 16:45 ET. Our futures legs hold for days, and MHG is not offered (§ 2).
   - The crypto legs have no futures equivalent at Tradeify: there are no crypto futures.
2. **What avenues does it open, such as a futures ML that could also run on IB?**
   - The first futures ML (RQ-20261112-09d2-03) failed its holdout.
   - An ML on CME micros would serve both IB (`ib_paper` already trades MES and MGC) and Tradeify, if it is session-flat.
   - The next model needs real-contract intraday history: row FUT-CME-INTRADAY-HIST.
   - No forex: Tradeify lists only the M6E and M6A micro FX futures, and we have no FX leg.
3. **What builds are needed to add it to the roster, reusing the crypto Tradeify integration?** `TRADEIFY-WIRE` is DXtrade REST and does **not** carry over to Tradovate. The builds are:
   - **TRADEIFY-FUT-EXECUTOR** (Tier 2, blocked): a Tradovate ticket/bracket executor on the operator's device, using the `breakout_2` phone-executor plumbing.
   - **FUT-INTRADAY-DUKA-LANE**: the 15m/5m data lane.
   - **FUT-CME-INTRADAY-HIST**: real CME history.
   - A `config/prop_rulesets/tradeify_futures_*.yaml` with EOD-trailing drawdown support in `prop_ev_sim.py`. Today it raises on non-static drawdowns; this lane's simulator is the stand-in.
4. **Which account option has the highest expected return over about 6 months?** None is positive (§ 6). The least-negative are the cheap turbo plans. Every Tradeify plan we modelled loses most of its fee in 6 months with the book we run.

## Units and rows

| Id | What | Status |
|---|---|---|
| RQ-20261112-09d2-01 | ORB Stage 0, 6 cells, Tradeify costs | done: **fail** |
| RQ-20261112-09d2-02 | EOD-trailing survival, Growth/Select/Lightning 50K | done: **no_action_warranted** (the rule's NOT_APPLICABLE branch) |
| RQ-20261112-09d2-03 | gbdt meta-label ML filter | done: **fail** |
| RQ-20261112-09d2-04 | `ict_scalp_mgc_15m` session-flat transfer | blocked on FUT-INTRADAY-DUKA-LANE |
| RQ-20261112-09d2-05 | Iteration: MNQ_OR15 on real CME MNQ | blocked on FUT-CME-INTRADAY-HIST |
| RQ-20261112-09d2-06 | PROP-PLAN-EV-6M: 6-month EV per firm/plan | done: **fail** (0/27 buyable); weekly |

**Harness:** `scripts/research/tradeify_futures_fit.py`. It is offline, imports nothing from `src/`, and fetches its own corpus.

**Results:**
- `research/results/RQ-20261112-09d2-0{1,2,3}/local-20261112.jsonl`
- `comms/research/RQ-20261112-09d2-0{1,2,3}/local-20261112/verdict.json`

The trade ledgers can be regenerated and were not committed (6.8 MB).

**Fixed along the way.** RQ-20261101-78fc-13 was blocked on ICT-SCALP-EVIDENCE, which is **dropped**, so the unit could never clear. It now points at FUT-INTRADAY-DUKA-LANE.
