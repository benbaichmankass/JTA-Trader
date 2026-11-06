# sol_4h on the prop books: does pulling it lower EV or p(pass)? (2026-11-06)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-06` · lane `SOAK-BACKLOG-REVIEW` (Manager Session 2026-11-06a)

**Gates this adds or changes: none.**

**Why this was run:** the operator decided *"Pull sol_4h, keep eth_4h (Recommended)"*, then added the caveat *"Keep in mind that a some of the prop
accounts might have minimum trading days requirements"*. The manager's rule was to pull `trend_donchian_sol_4h` from breakout_2 and tradeify_1,
which have no minimum-days rule, regardless. For velotrade_1, keep it **if removing it lowers EV or p(pass)**.

**velotrade_1's ruleset is CLASSIC 1-Step** (`config/accounts.yaml::velotrade_1.backtest_ruleset: prop_rulesets/velotrade_classic_1step.yaml`).
A **qualifying day** is a trading day whose *realised* P&L is ≥ +0.8% of the initial balance ($40 on $5k), measured 00:30–00:30 UTC. Five
are needed in the evaluation, and five more on the funded account before the first payout (the count resets when funded). The simulator
models both (`prop_ev_sim.py`: `qual_day_profit_pct`, `qual_day_min_days`, `funded_qual_days_before_payout`).

**Setup:** `prop_ev_sim.py` path mode, 5 seeds × 1000 lives. Ledgers are the 3y re-test ledgers (2023-11-05 .. 2026-11-05; `../ledgers/`).
Current-stack costs (commission 11 / slippage 3 bps rt, swap 0.03 %/day), dd switch 0.8, fresh funded start.

## At LIVE sizing: $10 per leg (`sizing.flat.per_leg_risk_usd`, the 11-05 min-size baseline). `summary_min10.json`

| account | book | EV $/life | p(pass eval) | days to pass p50 | p(max-DD breach) |
|---|---|---:|---:|---:|---:|
| velotrade_1 | eth_4h alone | −53.92 | 0.076 | 619 | 0.005 |
| velotrade_1 | eth_4h + sol_4h | **−52.68** | **0.138** | 596 | 0.011 |
| breakout_2 | eth_4h alone | −15.51 | 0.114 | 590 | 0.146 |
| breakout_2 | eth_4h + sol_4h | −8.02 | 0.200 | 565 | 0.184 |
| tradeify_1 | eth_4h alone | −120.00 | 0.000 | — | 0.000 |
| tradeify_1 | eth_4h + sol_4h | −120.00 | 0.000 | — | 0.000 |

## At the registered protocol's `risk_pct` sizing (`summary.json` and the `<acct>__*` files): the same direction, larger numbers

| account | EV $/life alone → with sol | p(pass) alone → with sol | p(max-DD breach) alone → with sol |
|---|---|---|---|
| velotrade_1 | 74.79 → 144.45 | 0.579 → 0.657 | 0.236 → 0.323 |
| breakout_2 | 35.81 → 62.16 | 0.416 → 0.486 | 0.502 → 0.630 |
| tradeify_1 | 112.57 → 195.57 | 0.495 → 0.582 | 0.331 → 0.438 |

## Reading

1. **velotrade_1: KEEP sol_4h**, by the manager's rule. Removing it lowers p(pass) from 0.138 to 0.076 at live sizing, and EV by about $1.2 per
   life. At protocol sizing, EV falls from +$144 to +$75 and p(pass) from 0.657 to 0.579.
2. **The minimum-days rule is NOT what binds.** The share of lives that reached the +10% target but were not passed for want of qualifying
   days is ≈ 0 in both books. sol_4h helps because the book reaches the target more often: more trades, with a small positive mean.
3. **⚠️ The same holds on breakout_2 and tradeify_1.** On breakout_2, adding sol_4h raises EV (−$15.5 → −$8.0) and p(pass) (0.114 → 0.200) at
   live sizing. The "each attempt burns the fee" reading comes from sol_4h simulated **alone** (`../RESULT.md`); inside a book it adds. It is
   pulled from both as instructed, and this is flagged to the manager before merge.
4. **At live min size, every book on every account has negative EV per life.** The firms' targets are rarely reached within the horizon at
   $10 per leg; tradeify_1 never passes. This is consistent with the operator's framing of these accounts as a measured baseline, where a
   breach is acceptable.

## Decision (supersedes the ~19:40Z pull)

Operator ~20:18Z, after this simulation was shown, verbatim: *"Keep sol_4h on all prop books (Recommended)"*. The option read: "Reverse the pull: it
improves every book's pass odds and EV; it stays on probation in the iteration loop." trend_donchian_sol_4h stays on breakout_2, tradeify_1 and velotrade_1,
on probation (iteration unit RQ-20261106-031). The ~19:40Z "Pull sol_4h, keep eth_4h" decision is superseded, and reading item 3 above no longer applies.
