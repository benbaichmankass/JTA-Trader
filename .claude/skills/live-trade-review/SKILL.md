---
name: live-trade-review
description: The binding procedure for reviewing OPEN order packages against the market in real time. Mechanics first, then price every option from the leg's own Stage-0 history with scripts/research/live_review_outcomes.py, then overlay what the backtest could not see, then record ONE package-level recommendation per package in comms/live_review/reviews.jsonl. Each account carrying the package gets its own would-apply / refused / unknown read. The review works at the ORDER-PACKAGE level and never does per-account risk management. Scope (operator Q2): real-money and prop packages get review + recommend; paper books are record-only. Pings (Q3): applies and asks only. Use when the manager dispatches a live-review lane, when the LTR-4 routine spawns a reviewer, or the operator says "review the open trades", "/live-trade-review", "should we tighten X". NOT for closed-trade grading (/performance-review), NOT for designing exit rules (exit-refinement), and NOT an apply path (apply_mode is recommend until LTR-6/LTR-7 land).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-25` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /live-trade-review — review open packages against the market

> **Operator, 2026-10-25 (verbatim, row `LIVE-TRADE-REVIEW-DESIGN`):** *"I want a routine that checks live trades to check the strategies real time performance against market conditions so that we can improve performance - it seems like we're somewhat limited in that we only review results and not real-time performance, which could be a strong lever for improving strategy and ml performance."*

Design of record: [`docs/plans/live-trade-review-DESIGN.md`](../../../docs/plans/live-trade-review-DESIGN.md) (merged c5d8d225, operator-approved 2026-10-25). This skill is its § 3 procedure, made binding. Checklist row `LTR-3-SKILL`, roadmap `L-ATM`. The precedent is `ADA-LIVE-EXIT-REVIEW-1024` ([`docs/research/ada-live-exit-review-2026-10-24.md`](../../../docs/research/ada-live-exit-review-2026-10-24.md)).

**A live review is a pricing exercise, not a hunch.** Its core question is: *"what did this leg's own history do from this exact state?"* A tool answers it. Your judgment is the overlay and the classification.

---

## 0. Binding limits of this skill (read first)

### 0.1 apply_mode is RECOMMEND

Until `LTR-6-APPLY-PATH` and `LTR-7-MANDATE` land and `config/live_trade_review.yaml::apply_mode` says `apply`, a reviewer:

- **never** moves a stop;
- **never** places, amends or cancels an order;
- **never** writes `config/` (no `mode:`, no `execution:`, no roster);
- **never** opens a `system-action` issue.

It reads, prices, records and reports. That holds even when the recommendation is obviously right and the data is unambiguous. When apply arrives, it comes only through the mandate's own clauses (design § 4), never through this skill's prose.

### 0.2 The review is PACKAGE-level; risk is ACCOUNT-level (operator structural directive, 2026-10-25, binding)

The operator, relayed by the manager on 2026-10-25 at about 16:15Z, said that the review works at the **strategy ticket / order package** level: the trade itself and the market conditions around it. **It never does per-account risk management.**

1. **The output is a package-level intent.** One recommendation per `order_package_id` (hold / tighten_sl(level) / tp_revise / …), argued from the trade and the market, never from one account's balance, drawdown or rules.
2. **Each account applies the intent only through its own risk layer and executor, within its own bounds.** That covers bybit_2, the bybit_portfolio mirror, each prop account, the soak books, and any account that carries the package. Each account checks its own drawdown limits and prop rules. **Each prop account can therefore reach its own decision** on the same package intent. A reviewer never resolves that decision for them, and never sizes, filters or skips a recommendation because of one account's state.
3. **The review row records the package intent plus a per-account read** (`account_reads`, § 4). For every account carrying the package it records one of these states:

   | read | meaning |
   |---|---|
   | `would_apply` | this account has an apply path for this action, and nothing you can read refuses it |
   | `refused_by_account_risk` | a read-only check of this account's own rules refuses it (e.g. the new stop is beyond a prop daily-loss distance, or the executor refused the amend) |
   | `unknown` | we could not look, or the account has no apply path for this action yet. Prop accounts are `unknown` until LTR-8, Alpaca until LTR-9 |
   | `no_action` | the package intent changes nothing (hold / no_recommendation), so there is nothing to apply |

   Compute it read-only, or write `unknown` and say why. Never fabricate `would_apply`.
4. **Known gap. Do not paper over it.** The design's § 4 apply path, `scripts/ops/amend_position_sl.py`, moves the shared package SL on **every** leg at once. It does **not** go through `RiskManager`. `RiskManager.approve()` (`src/units/accounts/risk.py`, `def approve`) evaluates **new** packages only. So today nothing applies an open-trade amend per account through its own risk layer. That is a finding for `LTR-6` / `LTR-8` / `LTR-9`, recorded on row `LTR-6-APPLY-PATH`. Until it is closed, a per-account read of `would_apply` on Bybit means "the shared amend would reach this leg". It does **not** mean "this account's risk layer approved it", and the row's evidence string says so.

### 0.3 Scope by account class (operator Q2) and pings (Q3)

| book | what the reviewer does |
|---|---|
| **real money** (`account_class: real_money`) and **prop** | full review → recommendation → `route` per § 3 step 5 |
| **paper / soak** (`bybit_1`, `alpaca_paper`, `ib_paper`, mirrors with no real-money twin) | **record-only**: mechanics, state and the priced table if cheap. `recommendation.action: no_recommendation`, `basis: record_only`, `route: none`. Never escalated. It is dataset-building for design § 5 |

A package that sits on a real-money account **and** paper accounts (e.g. bybit_2 + bybit_portfolio + bybit_1) is reviewed **once**, at the real-money scope. The paper legs appear in `account_reads`.

**Pings (Q3):** only an **apply** (after LTR-6/7) and an **operator ask** reach the operator in real time. Everything else goes in the next brief: recommended-not-applied in section 3, applied in section 1. A `flag_mechanics` on a real-money or prop package is an operator ask: wake the manager, and the manager decides the popup.

---

## 1. Population: which packages to review

**Name the population and prove the read could see a positive.** "Nothing open" is a claim. It needs the reads below, each with a non-error response.

| read (all `scripts/ops/diag_fetch.sh '<path>'`, relay fallback per `diag-data`) | gives |
|---|---|
| `position_telemetry?limit=300` | open rows (`lifecycle: open`) with `open_r`, `peak_r`, `giveback_r`, `bars_held`, `r_to_stop`, `r_to_target` |
| `journal?table=order_packages&limit=150` | package `entry/sl/tp`, `status`, `meta` (atr, trail_mult, regime cell at entry), `exit_plan_state` |
| `journal?table=trades&limit=1000` (+ `&offset=1000…` for older opens) | every open `trades` row per account, joined on `order_package_id` |
| `bybit_open_orders`, `exchange_positions`, `alpaca_open_orders`, `ib_open_orders` | venue truth: positions and resting SL/TP per account |
| `https://ict-bot.duckdns.org/api/bot/prop/tickets` and `/api/bot/prop/status?account_id=<acct>` | prop tickets (status, `phone_trail` amend state) and each prop account's reported positions |
| `config/accounts.yaml` (`account_class`, rosters) and `config/strategies.yaml` (leg params) | scope and leg geometry |

Union **telemetry-open ∪ journal-open ∪ venue-open ∪ prop-reported-open**. Then reconcile them. **A package that appears in one source and not another is itself a finding:**

- open at the venue, but the package is closed or the trade row is missing → `flag_mechanics` (an orphan, or a strategy exit that never reached the account);
- open in the journal, but no telemetry row → coverage gap. Telemetry covers the donchian/pullback family (design § 9). Record it with `mechanics.verdict: could_not_look` and say "not covered". **Never treat it as "nothing to review".**
- a prop account whose status carries no `positions` field → its positions are `unknown`, **not** flat.

If the union is empty, write that with the reads' timestamps and row counts ("we looked: telemetry 300 rows, 0 open; …"). Then run the procedure on the most recent closed package as a **dry rehearsal**, labelled `trigger.event: dry_rehearsal`.

---

## 2. Inputs per package

| input | source |
|---|---|
| entry, risk per unit, package SL/TP, trail state, declared levers | `order_packages` (+ `meta`, `exit_plan_state`), `config/strategies.yaml` |
| `open_r`, `peak_r` (**ESTIMATED** from bar extremes, a lower bound), `giveback_r`, `bars_held`, `bars_since_peak`, `r_to_stop`, `r_to_target` | `position_telemetry` |
| resting SL/TP, size and side on **every** account carrying the package | the venue reads above |
| ATR now vs at entry, the `(trend, vol)` cell now vs at entry | candles, `meta.regime`/`vol_regime`, `config/regime_policy.yaml` |
| **the conditional outcome table** | `python3 scripts/research/live_review_outcomes.py --leg <leg> --side <long\|short> --open-r <x> --peak-r <y> --bars-held <n> --atr-stop-mult <leg atr_stop_mult> --json` |
| correlated open exposure | every other open package: same direction, correlated symbols (e.g. ADA + XRP both short is one crypto-beta bet) |
| the previous review of this package | `comms/live_review/reviews.jsonl` |

---

## 3. The procedure (in order; do not skip or reorder)

### Step 1. Mechanics first

Check three things:

- Does the venue SL/TP on **every** account equal the package's SL/TP (to the tick)?
- Does the leg's own trail geometry explain the current stop?
- Do venue, journal, telemetry and prop tickets agree that the trade is open?

If any of these fails, the recommendation is `flag_mechanics` (basis `mechanics`, route `operator_ask` for real-money or prop), with the evidence in `mechanics.evidence`. **No exit judgment is made on a broken trade.** `options` may be left empty. A mechanics flag goes to the order-path owner through the manager. It is a bug, not an exit call.

### Step 2. Price the options from history: quote the tool, never a hand calculation

Run `live_review_outcomes.py` for the leg at the live state, and copy its numbers into `options` as they are, with the tool's own `n`, `mean_r`, `sd_r` and `worst_r`.

- **Quote the pricing tool, never the design's or a precedent's hand calculations.** This was settled on 2026-10-25 (row `LTR-0-CONDITIONAL-OUTCOMES`, PR #20114). The tool reproduces the ADA HOLD case (n=32, mean +3.19 R), but the design's original "tighten +2.96 R, worst +2.32 R" was an unreproducible hand calculation. At that level the tool gives `atr:1.5` = +2.87 and `r:2.5` = +2.94, worst +1.31. A number you did not get from the tool this session does not go in a row.
- **`insufficient_n` means NO recommendation, never "hold".** If the HOLD cell or the candidate cell is below the n floor (default 20), the recommendation is `action: no_recommendation`, `basis: insufficient_n`. Then **file the data question** (design § 3 step 2; CLAUDE.md, 2026-09-29: *"either we have enough data to decide, or we don't and then getting that data becomes a task"*). A null cell is "could not look"; never write it as 0.
- Read `population` (comparable / never_reached_peak / no_candles) and the tool's `biases` list. A tighten is flattered: stops fill at the stop price. Say so in `context_flags` when a tighten is in play.

### Step 3. Overlay what the backtest could not see

Each overlay item needs evidence:

- a regime or vol cell change since entry;
- an ATR ratio of ≥ 1.5 or ≤ 0.67;
- funding beyond the leg's assumption;
- a high-impact calendar event within the next bar;
- correlated open exposure;
- a live-vs-backtest verdict showing this leg's live exits differ from the harness.

Each one goes in `context_flags` as `"<kind>: <evidence>"`. An overlay may **downgrade** confidence or turn a tighten into an operator ask. It never manufactures a tighten the table does not support.

### Step 4. Classify, at the PACKAGE level

The actions are `hold` · `tighten_sl(level)` · `tp_revise(level)` (Tier 3, the TP-doctrine path) · `partial_close` / `close` (always the operator's call) · `flag_mechanics` · `file_hypothesis` · `no_recommendation`.

- `hold` requires a **measured** HOLD cell (n ≥ floor) whose EV is at least that of every measured alternative. Then `basis: ev_positive`.
- `tighten_sl` requires a measured cell, and states:
  - `ev_delta_r` = tighten mean − hold mean (negative is a cost);
  - `worst_case_delta_r` = tighten worst − hold worst;
  - `level` as a price and as `level_atr`.

### Step 5. Separate EV from preference, and set the route

- **Apply bound (operator Q1):** a tighten whose EV cost is ≤ **0.25 R**, with the worst case improving, is `within_bound` on `apply_policy`. Record the **shadow 0.5 R arm** on `shadow_policy` on **every** review, so the two policies can be compared.
- **While apply_mode is recommend:**
  - a within-bound tighten is `route: recommended`;
  - an out-of-bound tighten, a `tp_revise`, a `close` and a `flag_mechanics` are `route: operator_ask`;
  - `hold`, `no_recommendation` and paper rows are `route: none`.

  `applied` is always `false`.
- An operator ask carries the priced options table in the ADA format: *"−0.23 R expected, worst case +0.28 → +2.32 R"*, with the tool's numbers. **Never decide, trade by trade, that variance matters more than EV.** That preference is the operator's, stated once in Q1.

### Step 6. Record, validate, report

1. Append one row per package to `comms/live_review/reviews.jsonl` (schema `comms/schema/live_review.schema.json`).
2. Run `python3 scripts/ci/check_live_review_records.py`. It must exit 0 **on the real rows**.
3. Land the rows in a PR (self-landing: automerge file + merge-slot claim, per the manager skill).
4. Report to the manager. For each package give:
   - leg, accounts, state;
   - the recommendation, with its priced options (n, mean, worst);
   - the per-account read.

   Wake the manager **at once** for any operator ask or mechanics flag on real money or prop. Do not batch it.

---

## 4. Row fields this skill adds or pins

These are on top of the LTR-2 schema:

- `recommendation.action: no_recommendation` + `basis: insufficient_n`. The validator refuses `insufficient_n` with any other action, so the "insufficient → hold" collapse cannot be written.
- `basis: record_only` for paper rows.
- `account_reads`: `[{"account_id", "account_class", "read": would_apply|refused_by_account_risk|unknown|no_action, "evidence"}]`. There is one entry per account carrying the package, and it is required on every review.
- `trigger.event`: an L0 event name (design § 2). When run by hand, use `manual`. For the first live run of a skill version, use `first_live_run`. For a closed package priced as practice, use `dry_rehearsal`.
- `model`: the model TIER from the manager's model table (e.g. `opus-tier`), never a model identifier: the repo is public and identifiers stay out of pushed artifacts. `session`: your session id.

## 5. What this skill is not

- Not the protection. Venue SL/TP and the VM trail protect every position every ~30 s, whatever the reviewer does.
- Not an exit-rule designer. A pattern that repeats 3 or more times (same leg, same state bucket, same action) becomes an `exit-refinement` unit (design § 5). The reviewer's success measure is making itself unnecessary for each pattern it finds.
- Not a grader of closed trades. That is `/performance-review` (LTR-5 adds its "Live review" section).

## 6. Composes with

`diag-data` (reads) · `exit-refinement` (patterns → units) · `performance-review` / `perf-followup` (grading, lessons) · `manager` (dispatch, wake, popups) · `close-out` (end of every review lane).
