---
name: live-trade-review
description: The binding procedure for reviewing OPEN order packages against the market in real time. Mechanics first, then make the BEST TRADING DECISION NOW (operator 2026-10-27; not fidelity to the strategy), with every option priced from the leg's own Stage-0 history by scripts/research/live_review_outcomes.py as evidence, then overlay what the backtest could not see, then record ONE package-level recommendation per package in comms/live_review/reviews.jsonl. Each account carrying the package gets its own would-apply / refused / unknown read. The review works at the ORDER-PACKAGE level and never does per-account risk management. Scope: every account, paper included (operator 2026-10-26 "All accounts now", superseding Q2's paper record-only rule under MD-TRADE-DESK). Pings (Q3): applies and asks only. Use when the manager dispatches a live-review lane, when the LTR-4 routine spawns a reviewer, or the operator says "review the open trades", "/live-trade-review", "should we tighten X". NOT for closed-trade grading (/performance-review), NOT for designing exit rules (exit-refinement), and NOT itself an apply path (applies go through scripts/ops/live_review_apply.py under MD-TRADE-DESK, the one trade-desk mandate (this review is the desk's in-trade function; MD-LIVE-TIGHTEN-SL is its superseded alias for a tighten), since 2026-10-26; a thin LTR-0 cell is decided by the reviewer's judgement, basis judgement).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-26` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /live-trade-review — review open packages against the market

> **Practice principles (pointer):** the design and evaluation choices this skill makes follow [`docs/reference/trading-and-model-practice-principles.md`](../../../docs/reference/trading-and-model-practice-principles.md) (TRADING T1–T10 · MODEL M1–M10 · RESEARCH-OPS R1–R6), refreshed weekly by `frontier-research`; a principle never overrides a binding rule.


> **The question is the BEST TRADING DECISION NOW** (operator 2026-10-27 ~07:05Z, relayed by the manager; supersedes "price every option from the leg's own Stage-0 history" as the frame): keep holding, let go, change the brackets, partial close, add quantity? In-trade management is **not** judged by fidelity to the strategy. The leg's outcome tables (`live_review_outcomes.py`) stay as EVIDENCE, quoted with their n, never as a constraint on the call. Rows `LTR-BEST-DECISION-FRAMING`, `DESK-SHORT-HOLD-LANE`.

> **Operator, 2026-10-25 (verbatim, row `LIVE-TRADE-REVIEW-DESIGN`):** *"I want a routine that checks live trades to check the strategies real time performance against market conditions so that we can improve performance - it seems like we're somewhat limited in that we only review results and not real-time performance, which could be a strong lever for improving strategy and ml performance."*

Design of record: [`docs/plans/live-trade-review-DESIGN.md`](../../../docs/plans/live-trade-review-DESIGN.md) (merged c5d8d225, operator-approved 2026-10-25). This skill is its § 3 procedure, made binding. Checklist row `LTR-3-SKILL`, roadmap `L-ATM`. The precedent is `ADA-LIVE-EXIT-REVIEW-1024` ([`docs/research/ada-live-exit-review-2026-10-24.md`](../../../docs/research/ada-live-exit-review-2026-10-24.md)).

**A live review is a pricing exercise, not a hunch.** Its core question is: *"what did this leg's own history do from this exact state?"* A tool answers it. Your judgment is the overlay and the classification.

---

## 0. Binding limits of this skill (read first)

### 0.1 The reviewer never acts by hand

`config/live_trade_review.yaml::apply_mode` reads `apply` since 2026-10-25 (row `LTR-6R-APPLY-PATH`), and `MD-LIVE-TIGHTEN-SL` is granted. A tighten is applied ONLY by `scripts/ops/live_review_apply.py --apply` under that mandate, through each account's own `RiskManager.approve_amend`. The reviewer itself:

- **never** moves a stop;
- **never** places, amends or cancels an order;
- **never** writes `config/` (no `mode:`, no `execution:`, no roster);
- **never** opens a `system-action` issue, with ONE exception: `live-review-apply` for its own landed `tighten_sl` row, or (since 2026-10-26, § 3b) its own landed trade-action row (§ 3 Step 7). That is the only way a reviewed action reaches a venue.

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
| **paper / soak** (`bybit_1`, `alpaca_paper`, `ib_paper`, mirrors with no real-money twin) | **full review → call → `route`, the same as real money, since 2026-10-26** (Operator 2026-10-26 ~18:56-19:00Z, popup answer to the manager, verbatim: "All accounts now" (option text: "Real-money, prop and paper at once"); this supersedes Q2's paper record-only rule for `MD-TRADE-DESK`). Never escalated to the operator: a paper refusal or apply goes in the brief, not a ping. `basis: record_only` stays valid for a paper package you could not price or judge |

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

> **STOPGAP (manager, 2026-10-26; drop this note once the gate surfaces telemetry-less open packages as their own state, pipeline item `PI-20261026-2U1HUCXC-0002`):** the due gate (`live_review_due.py`) skips open packages that have no telemetry. For any open package the gate skipped, build its packet anyway and judge it per this skill (paper packages are record-only). Found 2026-10-26 11:18Z: the gate said 7 open, the packet listing had 8; the missing one was the paper package `gld_pullback_1h`.

If the union is empty, write that with the reads' timestamps and row counts ("we looked: telemetry 300 rows, 0 open; …"). Then run the procedure on the most recent closed package as a **dry rehearsal**, labelled `trigger.event: dry_rehearsal`.

---

## 1b. The decision packet: the repo builds the context, Claude judges (operator, 2026-10-25, binding)

The operator, relayed by the manager on 2026-10-25 at about 16:20Z: the **repo**, not Claude, should build the context for each decision. Claude spends its usage only on the judgment. The context comes out in a fixed shape, so every decision lands in the datasets the models train on.

**The decision packet is the one input contract.** It has one packet per package per review, stored at `comms/live_review/packets/<review_id>.json`, with these fields:

| field | content |
|---|---|
| `state` | open_r, peak_r (+ provenance), giveback_r, bars_held, sl, tp, atr_now_over_entry, regime cells |
| `features_at_review` | the numeric features the ML datasets join on |
| `priced_options` | the LTR-0 table: source path, read_state, population, corpus, n_floor, options, biases |
| `regime` | the `(trend, vol)` cell at entry and now, and the ATR ratio |
| `mechanics` | venue vs journal vs package for every account, with a verdict and evidence |
| `cost` | the cost basis behind the priced options |
| `account_bounds` | the per-account read (§ 0.2) |
| `info_cutoff_at` | when the newest input was read |

- **The reviewer reads the packet and judges. It does not go and research.** The row carries `packet_sha`, the sha256 of the packet's canonical JSON (`sort_keys`, compact separators). The validator refuses a `packet_sha` that does not match the committed packet. That makes every decision joinable to exactly what was seen.
- **Until the generator `scripts/ops/live_review_packet.py` exists**, the reviewer assembles the packet by hand from the § 1 reads and § 2 inputs, in this exact shape, and writes `assembled_by: hand`.
- A field it could not fill is `null`, with the reason in `mechanics.evidence` or `context_flags`. It is never guessed. When the generator lands, the reviewer stops reading diag routes itself.

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
- **A thin cell is decided by judgement, never by a default "hold"** (operator, 2026-10-26, popup verbatim *"Claude's judgement applies (Recommended)"* — *"Drop the n>=20 clause. When the table is thin, Claude's call applies, logged as 'judgement' with a confidence; the table is used when it's there. Every call is graded against the actual outcome so models can learn how much weight to give Claude."*; row `LTR-JUDGEMENT-APPLY`). If the HOLD cell or the candidate cell is below the n floor (default 20), make the call from the packet and the overlay: `basis: judgement`, `evidence_source: judgement`, `judgement_confidence` in [0, 1] (your calibrated probability the call beats holding) and a one-line `reason`. Quote whatever the thin cells show (n, mean) in `context_flags`; never present them as measured. **A real-money or prop package with mechanics `match` ALWAYS gets a call** (manager 2026-10-26 ~12:37Z, closing the escape found in #20322: every real-money review that day ended `no_recommendation` + `insufficient_n`, so the operator's 06:30Z "Claude's judgement applies" produced no graded calls at all). On a thin cell record `hold` **or** `tighten_sl`, each with `basis: judgement`, `evidence_source: judgement`, a `judgement_confidence` in [0, 1] and a one-line `reason`. `hold` + `judgement` is a legitimate graded call; only the SILENT collapse (a hold with no confidence and reason) stays banned. `no_recommendation` on a real-money/prop package is allowed only with `basis: could_not_look` and a `reason` (the packet could not be read, a required input is null); `insufficient_n` and `default_hold` are refused there by the validator for rows reviewed from 2026-10-26T12:40Z. Paper-only packages get the same calls since 2026-10-26 (§ 0.3); `record_only` remains allowed there. Every trade action applies under `MD-TRADE-DESK` (§ 3b; a tighten's gates unchanged). A null cell is "could not look"; never write it as 0. The n floor is no longer an apply gate: it decides only whether the basis is `table` or `judgement`.
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

- `hold` on a **measured** HOLD cell (n ≥ floor) whose EV is at least that of every measured alternative: `basis: ev_positive`. On a thin cell, `hold` is a judgement call (`basis: judgement` + confidence + reason), never a default.
- `tighten_sl` states `evidence_source` and `level` as a price and as `level_atr`, and then either:
  - **table** (measured cell): `ev_delta_r` = tighten mean − hold mean (negative is a cost) and `worst_case_delta_r` = tighten worst − hold worst; or
  - **judgement** (thin cell): `basis: judgement`, `judgement_confidence`, `reason`; `ev_delta_r` / `worst_case_delta_r` and both policies' `tighten_r` are `null` (there is no table EV to bound).
- The guardrails do not move with the basis: tighten-only, the `min_buffer_atr` (1× ATR) noise floor, one amend per package per bar, `mechanics.verdict == match`, each account's own `approve_amend`, and `could_not_look` never applies. A tighten never widens, moves a TP, resizes, closes or adds an entry; those are the separate trade actions of § 3b, each its own call.
- `close` · `partial_close` · `move_tp` · `widen_sl` · `change_size` · `add_entry`: § 3b.

### Step 5. Separate EV from preference, and set the route

- **Apply bound (operator Q1):** a tighten whose EV cost is ≤ **0.25 R**, with the worst case improving, is `within_bound` on `apply_policy`. Record the **shadow 0.5 R arm** on `shadow_policy` on **every** review, so the two policies can be compared.
- **Under apply_mode apply:** a `tighten_sl` with mechanics `match` that is table-backed within the bound, or judgement-backed with a confidence and reason, is applied by `live_review_apply.py --apply --mandate MD-LIVE-TIGHTEN-SL --mechanics match --basis table|judgement` (`--expected-cost-r` / `--worst-case-delta-r` for table; `--confidence` / `--reason` for judgement); its row is `route: auto_applied`, `applied: true`, with the per-account reads from the apply output. Anything else follows the recommend routes below.
- **While apply_mode is recommend:**
  - a within-bound tighten is `route: recommended`;
  - an out-of-bound tighten, a `tp_revise`, a `close` and a `flag_mechanics` are `route: operator_ask`;
  - `hold` and `no_recommendation` are `route: none` (a paper row routes like any other since 2026-10-26).

  `applied` is always `false`.
- An operator ask carries the priced options table in the ADA format: *"−0.23 R expected, worst case +0.28 → +2.32 R"*, with the tool's numbers. **Never decide, trade by trade, that variance matters more than EV.** That preference is the operator's, stated once in Q1.

### Step 6. Record, validate, report

1. **The packet and its outcome table are written by machine, never by you** (LTR-PACKET-ECHO, 2026-10-27: a reviewer re-typed a 5,316 B packet, dropped `"sd_r":null`, and the mirror refused the row on `packet_sha`). From an `ltr-wake` marker they are already on `live-review/rows`, committed byte-exact by the wake poster (`evidence_state` `committed` / `exists`): write only the row, carrying the block's `packet_sha`. With no marker (a repo lane), generate them with `python3 scripts/ops/live_review_packet.py <pkg> --write` and commit those generated files unchanged; never type, paste or re-serialise a packet or table. Then append one row per package, carrying its `packet_sha`, to `comms/live_review/reviews.jsonl` (schema `comms/schema/live_review.schema.json`).
2. Run `python3 scripts/ci/check_live_review_records.py`. It must exit 0 **on the real rows**. This is the gate before the rows-branch push in step 3: a row that fails must never be pushed (the branch is append-only). `live_review_rows_mirror.py` re-runs the same rules and skips a failing row as `schema: …`.
3. **Land the rows on the rows branch, not through a main PR** (operator 2026-10-26, popup verbatim *"Approve: rows branch + pinned commit (Recommended)"*). Commit the new rows **plus every cited file not already on the branch** (from a wake marker the packet and table are already there; a repo lane commits the generator's own files from step 1). A repo-less reviewer writes ONLY its row, as ONE create-only file `comms/live_review/rows/<review_id>.json`, after reading that its packet exists on the branch, and never writes `packets/` or `tables/` (REVIEWER-BRIEF.md § 4, LTR-ROWS-SWAP-TRUNCATION, LTR-PACKET-ECHO); a scripted git append to `reviews.jsonl` stays valid because it never re-generates the file, and every reader reads both. Never re-send the whole `reviews.jsonl`: a tip on which it lost a row is refused by the VM watcher and the mirror (the packet, and the outcome table named in `outcome_table_source`) on top of `origin/live-review/rows` and push straight to it; it is protected append-only (no force-push, no deletion) with no PR or check gate. Record the pushed commit's full 40-hex sha: it is the `ref` for Step 7. A mirror PR later copies the rows onto `main`'s `reviews.jsonl` by review_id, so `main` keeps the full record. **Fallback:** if the push is refused, or the branch does not exist yet, land the rows in a self-landing PR to `main` as before (automerge file + merge-slot claim) and use Step 7 without `ref`.
4. Report to the manager. For each package give:
   - leg, accounts, state;
   - the recommendation, with its priced options (n, mean, worst);
   - the per-account read.

   Wake the manager **at once** for any operator ask or mechanics flag on real money or prop. Do not batch it.

### Step 7. Dispatch the apply (LTR-APPLY-DISPATCH, operator 2026-10-26)

> **Operator, 2026-10-26 ~07:12Z, popup (verbatim):** *"Yes, top of the queue (Recommended)"*. The option text was: *"A Tier-2 lane wires the reviewed tighten_sl decisions into an apply run (an apply system-action or the review routine itself), with a VM check."* Row `LTR-APPLY-DISPATCH`.

> **Since LTR C1 (operator 2026-10-26 ~11:40Z, "VM applies from rows branch"):** a row pushed to `live-review/rows` is applied by the live trader's watcher (`src/runtime/live_review_rows_watch.py`, ~45 s) with `--ref <tip>`. The steps below are the **manual fallback**: file them only when the watcher's receipt (`log_file?name=live_review_rows_watch`) shows the row was not taken, or the row landed on `main` instead. A repo-less reviewer follows [`REVIEWER-BRIEF.md`](REVIEWER-BRIEF.md) instead of this skill.

`apply_mode: apply` and a granted `MD-LIVE-TIGHTEN-SL` do nothing on their own. A reviewed tighten reaches a venue only when the reviewer **files the `live-review-apply` system-action** for it.

1. **Which rows qualify.** Every row you landed in Step 6 where all of these hold:
   - `recommendation.action == tighten_sl`;
   - `mechanics.verdict == match`;
   - `disposition.route` is `recommended` or `auto_applied`;
   - the basis is either `table` (a measured cell, within the 0.25 R bound, worst case improved) or `judgement` (a confidence and a reason).

   Never file it for `hold`, `no_recommendation`, `flag_mechanics`, an `operator_ask`, or a `record_only` row.
2. **When.** **Immediately after the rows-branch push** (Step 6.3), with `ref: <that sha>`. The dispatcher fetches `main` and `live-review/rows` itself and reads the row and its outcome table with `git show <sha>:path`, so nothing waits for a main PR or for ict-git-sync. A sha reachable from neither branch is refused (exit 2); a row missing at the sha is exit 3. This path is valid under `MD-LIVE-TIGHTEN-SL` once its `fires_when` admits a pinned rows-branch commit (manager PR #20299); until that merges, use the fallback. **Fallback (row landed on `main` instead):** file only after the PR has merged, without `ref`; the VM reads its committed `main`, and a row not there yet is exit 3 (git-sync lags ~5 min), so re-file once after a few minutes.
3. **How.** One issue per row, labelled `system-action`, with this body:
   ```
   action: live-review-apply
   review_id: LR-…
   ref: <40-hex sha of the rows-branch commit>
   apply: true
   reason: live-review <review_id> tighten_sl under MD-LIVE-TIGHTEN-SL (<leg>, <basis>)
   ```
   Then write the issue number into the next row you append for the package (`disposition.action_issue`). Rows are append-only, so never edit the landed row.
4. **What you do not do.** You never pass a level, an account or a flag by hand. The VM side does all of that:
   - `scripts/ops/live_review_dispatch.py` re-checks the mandate's package-level clauses on the committed row;
   - `scripts/ops/live_review_apply.py` decides EACH account through its own `RiskManager.approve_amend` and executor, then reads the venue back;
   - the apply pings every applied leg, and sends ONE ping per refusal on a real-money or prop account.

   The dispatch is idempotent per `review_id`: a review_id whose apply sent anything is refused as a duplicate. A new decision needs a new review row.
5. **Report.** Read the issue's result comment and pass the per-account verdicts and the venue read-back to the manager:
   - exit 0: applied, or a dry run;
   - exit 1: `apply_failed` (the venue did not read back). Wake the manager at once;
   - exit 2: refused, with the clause named;
   - exit 3: could not look. Re-file once.

   An applied tighten belongs in the next brief's section 1, with the review row and the table path.

---

## 3b. Trade actions beyond a tighten (MD-TRADE-DESK, operator 2026-10-26)

> **Operator, 2026-10-26 ~18:56-19:00Z (popup answers to the manager, verbatim):** *"we also need to expand the desks mandate so include all trade actions, as long as they have reasoning and confidence attached"*. Actions: *"Close / partial-close", "Move take-profit", "Widen a stop", "Change size / add entry"*. Accounts: *"All accounts now"*. Row `LTR-ALL-ACTIONS`; mandate `MD-TRADE-DESK` in `config/mandates.yaml` (read it, not this paragraph, for what is granted).

**This review is the trade desk's in-trade function** (operator 2026-10-26, verbatim: *also, the desk is just a more advanced version of the ltr, they should both rely on the same mandate - ltr is just one funciton of the trade desk*). One mandate (`MD-TRADE-DESK`), one schema, one apply path, one grading (per action class and per function) with the desk's entry generation (`.claude/skills/trading-desk/SKILL.md`).

**Both brackets, always** (operator 2026-10-26, verbatim: *in general, every trade always must have BOTH brackets, not related to this skill. Claude can move the brackets, but nothing is supposed to remove brackets*). `move_tp` / `tighten_sl` / `widen_sl` MOVE a bracket; nothing removes one. A `partial_close` / `change_size` leaves the remaining position with both brackets; a `close` removes the position, not its brackets. The apply path refuses, per account and named (`both_brackets_required:<sl|tp>`), any action whose result would leave a leg without a stop or a take-profit, and checks both on the venue read-back.

**Each action is ONE package-level call with a reason and a confidence.** Write it only when the packet supports it better than holding; `hold` stays a call in its own right. Every one carries `reason` (one line, what in the packet makes this better than holding), `evidence_source` (`table` with `ev_delta_r` when the LTR-0 table priced this option at n ≥ floor; otherwise `judgement` with `judgement_confidence` = your calibrated probability the action beats holding) and its own target. The validator refuses a trade action missing any of them.

| action | target field | when to make the call | what each account still checks (never you) |
|---|---|---|---|
| `close` | none (`level: null`) | the thesis has failed while the stop has not been hit: e.g. regime/vol cell flipped against the leg since entry, a high-impact event inside the next bar on a crowded correlated book, a giveback pattern the leg's own history prices worse than exiting | tradeable now; one action per package per bar |
| `partial_close` | `size_fraction` in (0, 1) | the expected path is still positive but its worst case is not, e.g. a large open R into a known event; or concentration across correlated open packages | the venue can reduce by that size; else `no_action_path` |
| `move_tp` | `level` (price) | the prediction moved (TP doctrine: *the prediction moves through the trade*), e.g. ATR expanded ≥ 1.5× so the original target is now inside one bar's noise, or structure broke beyond it. Either direction | a REAL TP stays: beyond the mark and on the profit side of the entry; never removed, never a sentinel |
| `widen_sl` | `level` (price) | the stop sits inside current noise after a vol expansion (ATR ratio ≥ 1.5) and the leg's own history shows noise stop-outs from this state | the SAME check a fresh entry at that stop would pass: account live, leg not shadow, daily-DD switch not blocking new risk, gross-exposure cap, and open size ≤ the size a fresh entry at the new stop would be given |
| `change_size` | `size_multiplier` > 0, ≠ 1 | < 1: as `partial_close`. > 1: the table (or a stated judgement) prices adding at this state as positive net of an extra round-trip cost | > 1 passes the fresh-entry check above at the current stop; < 1 is a reduce |
| `add_entry` | `size_fraction` > 0 (of the open size) | same as `change_size` > 1 | the fresh-entry check above |

- **Overlays may manufacture these calls; they still need evidence.** Unlike a tighten (Step 3), a close, a TP move or a widen is often driven by what the backtest could not see. Name the overlay in `context_flags` and in the `reason`.
- **Mechanics first still binds.** No trade action on a `mismatch` or `could_not_look` row: that is `flag_mechanics`.
- **Package-level, never per-account** (§ 0.2). You never pick accounts, never size by one account's balance, never skip an account. Each account's `RiskManager.approve_action` decides inside its own limits; an account with no executor for the action refuses it as `no_action_path:<action>` and says so in `account_reads`.
- **Route.** Under `apply_mode: apply` and a granted `MD-TRADE-DESK`, a trade action with mechanics `match` and its reason + confidence (or table basis) is applied exactly like a tighten (§ 3 Step 7, `live-review-apply` with the row's `review_id`), `route: auto_applied`. A widen or an add is not special-cased by you: the accounts' own checks are what bounds it.
- **Grading.** LTR-5 prices every class hold-vs-action (`scripts/research/live_review_counterfactual.py`, method `paired_replay_v1:<action>`), and `live_review_grade.py` calibrates and gives each class its own use rule (operator-adopted review rule on `MD-LIVE-TIGHTEN-SL`). Your confidence is graded; state the one you hold.
- **Paper-only packages are in scope** (Operator 2026-10-26 ~18:56-19:00Z, popup answer to the manager, verbatim: "All accounts now" (option text: "Real-money, prop and paper at once")): the same calls, routed and applied the same way; only the operator pings are skipped for paper.

## 4. Row fields this skill adds or pins

These are on top of the LTR-2 schema:

- `recommendation.action: no_recommendation` + `basis: insufficient_n` is valid on **paper** packages only (the validator refuses `insufficient_n` with any other action, so the "insufficient → hold" collapse cannot be written). On a real-money/prop package reviewed from 2026-10-26T12:40Z the validator refuses `insufficient_n` and `default_hold` outright, and `no_recommendation` needs `basis: could_not_look` + a `reason`.
- `recommendation.evidence_source`: `table` | `judgement` | `none` — required on every `tighten_sl`, written on every new row. `basis: judgement` requires `evidence_source: judgement`, a numeric `judgement_confidence` in [0, 1] and a non-empty `reason` (validator-enforced). These are the fields LTR-5 grades against the realised outcome (joined on `review_id` in `outcomes.jsonl`), so the models can learn how much weight Claude's calls deserve.
- `basis: record_only` for paper rows.
- `recommendation.size_fraction` / `size_multiplier` (§ 3b): `partial_close` and `add_entry` carry `size_fraction`, `change_size` carries `size_multiplier`; every trade action carries `reason` and either `judgement_confidence` (judgement) or `ev_delta_r` (table).
- `account_reads`: `[{"account_id", "account_class", "read": would_apply|refused_by_account_risk|unknown|no_action, "evidence"}]`. There is one entry per account carrying the package, and it is required on every review.
- `trigger.event` + `trigger.level`: the due trigger the row answers, **exactly as the due packet / wake entry gave them** (e.g. `mechanics` / `venue_sl_diverges`); level is a number or a string, never null on a due event (validator-enforced from 2026-10-27, because the due dedupe keys on the pair). The due gate also treats a package whose latest review is `flag_mechanics` as having answered the mechanics level(s) it carried until the venue/package prices change, so a standing mismatch is reviewed once, not every bar. When run by hand, use `manual` (no level). For the first live run of a skill version, use `first_live_run`. For a closed package priced as practice, use `dry_rehearsal`.
- `packet_sha`: sha256 of the decision packet (§ 1b); the validator checks it against `comms/live_review/packets/<review_id>.json`.
- `skill_sha`: the git blob sha of the contract you followed: this `SKILL.md` for a repo reviewer (`git rev-parse HEAD:.claude/skills/live-trade-review/SKILL.md`), `REVIEWER-BRIEF.md` for a repo-less one. `/performance-review` splits every grade by it so a contract amendment's effect is measurable (CLAUDE-GRADE-LOOP); a change to either file is logged in [`AMENDMENTS.md`](AMENDMENTS.md) with its graded basis.
- `model`: the model TIER from the manager's model table (e.g. `opus-tier`), never a model identifier: the repo is public and identifiers stay out of pushed artifacts. `session`: your session id.

## 5. What this skill is not

- Not the protection. Venue SL/TP and the VM trail protect every position every ~30 s, whatever the reviewer does.
- Not an exit-rule designer. A pattern that repeats 3 or more times (same leg, same state bucket, same action) becomes an `exit-refinement` unit (design § 5). The reviewer's success measure is making itself unnecessary for each pattern it finds.
- Not a grader of closed trades. That is `/performance-review`, whose "Live review" section (LTR-5) prices every review against holding with `scripts/research/live_review_counterfactual.py` and grades the reviewer's calibration by `evidence_source` via `scripts/ops/live_review_grade.py`.

## 6. Composes with

`diag-data` (reads) · `exit-refinement` (patterns → units) · `performance-review` / `perf-followup` (grading, lessons) · `manager` (dispatch, wake, popups) · `close-out` (end of every review lane).
