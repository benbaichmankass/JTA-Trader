# Gate audit — every gate in the system (2026-11-12)

> **Doc status:** `live` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Gates this adds or changes: none.** This audit is read-only: it removes, loosens and tightens nothing. The operator decides each row. Lane `GATE-AUDIT`, Tier 1, dispatched by Manager Session 2026-11-11a.

**Decision this serves.** Operator, 2026-11-12 ~11:45Z, verbatim: *"audit all the gates in the system, anything that can stop the system from performing an action, and we're going to decide which ones we need to keep and which ones we're getting rid of, and no more gates that I don't explicitly give you permission for. It is not your job to add limitations that I did not ask for."*

**Machine-readable copy:** [`comms/gates/gate_inventory.json`](../../comms/gates/gate_inventory.json) has every field of every row, including each row's `question` and `options` (KEEP / REMOVE / MAKE REPORT-ONLY) for the decisions page.

## How this was measured

- **What counts as a gate.** Anything in code that can stop, refuse, hold, block, delay or narrow an action the system would otherwise take: trading, closing, amending, merging, deploying, writing, research or data.
- **Method.** Gates were found by reading code at `origin/main` `fc2461809` (2026-11-12), not docs. The searches were grep over refuse/reject/deny/block/skip/hold/guard/gate/tighten-only/advice-only/dry/shadow/never/require/forbidden/raise/`_ENABLED`.
- **How the CI guards were read.** The 132 `run_guards.py` guards were listed mechanically from the `GUARDS` registry. Blocking is read from each step's `allow_fail` flag. The origin is the commit that added the guard's script.
- **Who read what.** Four parallel readers covered the other categories (runtime, active management, landing, writers/VM). Their headline real-money rows were re-checked at the cited lines by the lane. Those rows are `live_review_rows.py:35`, `phone_trail.py:540`, `prop_trail.py:359`, `live_review_apply.py:704`, `prop_amend_gate.py:102` and `MainActivity.kt:1669`.
- **Origin dates.** Each `added` comes from `git log -S` on the **full** history (15,582 commits). The session clone started shallow (51 commits) and was unshallowed before any date was taken.
- **Authorization classes.** `VERBATIM` means an operator quote in context. `PARAPHRASE` means a session or manager wording, or a quote about the underlying problem that does not explicitly OK a blocking check. `NONE` means nothing was found by the search recorded in the row's `auth_search`. **A `NONE` row has no operator authorization on record; the operator's default stance on those is removal.**
- **Sort order.** Rows are sorted real-money-blocking first, then no-authorization first.
- **Limits, stated rather than hidden.**
  - `hits_14d` is mostly *not measured*. Refusals are logged on the VM journal and in GitHub Actions run history, not in the repo.
  - The measured exceptions are named in each row. Examples: 524 live-review rows, 3,243 landed PR declarations, 24 holdout reads.
  - Line numbers inside `scripts/ci/check_pr_landing.py` may be a few lines off.
  - The stale-signal/dedupe probe on the entry path is incomplete: `intent_multiplexer.py` and `order_bridge.py` were not read. It is listed under "Probes" below.

## Count

| Category | Rows | Can block real money | No operator authorization | KEEP | REMOVE | MAKE-REPORT-ONLY | OPERATOR-PREFERENCE |
|---|---|---|---|---|---|---|---|
| Runtime order path | 46 | 38 | 10 | 24 | 2 | 8 | 12 |
| Active management (close / reduce / amend) | 36 | 34 | 10 | 18 | 5 | 7 | 6 |
| VM and services | 11 | 7 | 5 | 7 | 0 | 1 | 3 |
| Writers, research queue, soak/status | 19 | 3 | 3 | 13 | 0 | 4 | 2 |
| CI landing machinery | 32 | 21 | 13 | 13 | 6 | 3 | 10 |
| run_guards.py guards (one blocking `guards` check) | 132 | 30 | 102 | 10 | 0 | 111 | 11 |
| Proposed by the w9 lane (report-only, unmerged) | 4 | 3 | 0 | 0 | 0 | 4 | 0 |
| Platform (not repo code) | 7 | 2 | 0 | 0 | 0 | 0 | 7 |
| **Total** | **287** | **138** | **143** | 85 | 13 | 138 | 51 |

**46 rows can block real money AND have no operator authorization on record.** They head the inventory below.

**All 132 `run_guards.py` guards are merge-blocking.** They run inside the one required `guards` check. Only one guard, `infra-workflows-single-owner`, runs its detector as a report; even there, its self-test blocks. Branch protection requires `pytest-collect`, `pytest-run` and `guards` with `enforce_admins: true`. That is set in `.github/workflows/branch-protection-sync.yml:153,208`; the live GitHub state was not read by this lane.

## The trigger case: why breakout_2 could not close two losing positions

Each cause maps to a row below; every one of them can refuse or prevent a **close** on a prop account.

1. **Close is advice-only everywhere without an auto mandate** (`AM-ADVICE-ONLY-ALL-CLASSES`, `src/runtime/live_review_rows.py:35`).
   - `ADVICE_ONLY_ACTIONS` covers every in-trade class: `close`, `partial_close`, `tighten_sl`, and the rest.
   - The operator's popups ("Advice-only tightens (Recommended)", "Advice-only until tested", 2026-10-28) were given on *tighten* evidence. They were extended to close without a close-specific test.
   - Measured over 524 review rows, 2026-10-29..11-12: 56 carried an in-trade action (31 of them `close`), and **0 of 56 were applied**.
   - No real-money or prop account has an auto path. `MD-LTR-PAPER-AUTO` covers `bybit_1`, `alpaca_paper` and `ib_paper` only.
   - The breakout_2 close fell back to an operator Telegram tap (`AM-OPERATOR-TAP-FALLBACK`).
2. **Neither prop trail ever closes** (`AM-PHONE-TRAIL-NEVER-CLOSES` `src/prop/phone_trail.py:540`, `AM-PROP-VM-TRAIL-NEVER-CLOSES` `src/prop/prop_trail.py:359`).
   - When the strategy's own harness has exited, the trail moves the stop to price + buffer: *"Tighten-only; no close"*.
   - Close levers (`stale_exit_bars`, `giveback_*`) only alert.
   - The only authorization on file is "Build the trail instead" (2026-10-01), which authorizes the trail, not "never close".
3. **The phone executor refused or could not act.**
   - A reduce is refused at claim unless the app declares `reduce` (`AM-PHONE-REDUCE-CAPABILITY`, #25227, merged 2026-11-12, no operator quote).
   - The app fails a reduce with `sheet_not_open` when the position sheet will not open (`AM-PHONE-APP-CLOSE-REFUSALS`, `MainActivity.kt:1595` `executeClose`, `sheet_not_open` at `:1830`). That is a read-before-click mechanic, not a policy, and the fix is the sheet reader.
   - The ticket's `human_hold` is checked **before** the reduce-only shortcut, so it can refuse a de-risking close (`AM-PROP-HUMAN-HOLD`, `src/prop/prop_amend_gate.py:102`, NONE FOUND, recommended REMOVE).
4. **Prop VM accounts cannot be closed through live review at all** (`AM-PROP-VM-ACTION-MATRIX`, `scripts/ops/live_review_apply.py:704`).
   - `prop_vm` maps to `{move_tp}` only.
   - A watched close exists (`prop_executor.run_close_position`), but only the Tier-2 `close-position` system-action reaches it.
5. **Live-review row writes need a Claude session, and the platform classifier refuses them** (`PLAT-CLASSIFIER-REAL-WORLD-TRANSACTIONS`).
   - This is the Claude Code classifier: **platform-owned, not repo code.**
   - The operator configures it through permission rules in `.claude/settings.json` (`permissions.allow`, 30 entries today).
   - A session cannot write that rule itself; editing `.claude/settings.json` is refused as Self-Modification.
6. **Landing holds and CI made the fixes wait** (`PRL-R4`, `PRL-R7`, `PRL-R8-R9-R14`, `PRL-R10`, `PRL-R15`, `BP-REQUIRED-CHECKS-MAIN`, and the 132 guards).
   - Over 2026-10-29..11-12 there were 3,243 landing declarations on main (reader count; the lane's re-count of unique added paths is 3,242). The reader classed 432 as `hold`.
   - 106 of those holds were Tier-1 PRs held only because a path was outside the Tier-1 allowlist (R5, `unvouchable_paths`).

A contrary operator quote is on file in the phone app (`MainActivity.kt:1668`, 2026-11-09 ~08:22Z): *"I never directed there to be a forbidden actions list, nor do I want one - the system must be able to take whatever actions necessary to ensure smooth autonomous operation."*

## Inventory

Each row ends with the decisions-page question. `RM` = can block or narrow a real-money action. Auth: `VERBATIM` / `PARAPHRASE` / **`NONE`**.

### Runtime order path (46)

#### `GATE-BAR-DEBOUNCE` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/strategy_monocle.py:466,476; pipeline.py:~830 (bar_debounce_blocked); env STRATEGY_BAR_DEBOUNCE_DISABLED`
- **Blocks:** One entry attempt per strategy+symbol per closed timeframe bar; a second actionable dispatch in the same bar is skipped.
- **Added:** 2026-06-01 bd3c1c8c44 fix(pipeline): bar-close debounce [Tier-2] (#2548)
- **Operator authorization (NONE):** NONE FOUND (PERF-20260601-001 in comment; no operator quote)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** It was added for PERF-20260601-001 (2026-06-01, #2548): repeat entry dispatches within one bar stacked positions. The reader judged that the open-package gate and the netting guard now cover that case; the lane did not re-verify it.
- **Recommendation: REMOVE.** Duplicate of open-package + netting guards, unauthorized; risk of stacking is covered by those.
- **Question:** No operator authorization found. Keep this gate? One entry attempt per strategy+symbol per closed timeframe bar; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-EMPTY-SIZING-BRAKE` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/strategy_monocle.py:565-575; pipeline.py:927 (empty_sizing_refused); env STRATEGY_EMPTY_SIZING_BRAKE_DISABLED`
- **Blocks:** A signal that already sized to an empty map is not re-dispatched (refused once with a named cause).
- **Added:** 2026-09-05 38a50671bf fix(sizing): refuse an empty sizing map ONCE (#11035)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Anti-spam; the re-emission is harmless once refusals are journalled.
- **Question:** No operator authorization found. Keep this gate? A signal that already sized to an empty map is not re-dispatched (refused once with a named cause). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-EXECUTE-ZEROQTY-WHOLEUNIT` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/units/accounts/execute.py:394 (qty=0 refusal), :411 whole_unit_qty; _submit_order BelowVenueMinQtyRefusal ~1521`
- **Blocks:** Last-line refusals: qty<=0 on a live order; sub-lot-minimum pre-flight refusal (benign, quiet) when legalization cannot resolve.
- **Added:** ZEROQTY 2026-05-07 491b4341e1 (#441); BelowVenueMinQtyRefusal 2026-07-26 86e2cc79a0 (#7653)
- **Operator authorization (NONE):** NONE FOUND as quote; physics
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Venue/physics limits, not policy.
- **Question:** No operator authorization found. Keep this gate? Last-line refusals: qty<=0 on a live order; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-MARKET-HOURS` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/market_hours.py:is_market_open; src/runtime/strategy_signal_builders.py (19 us_market_closed + 1 fx_market_closed return sites, e.g. :2919)`
- **Blocks:** Signal builders for us_equity/fx/cme symbols return side=none when the market is closed (US 14:30-21:00 UTC, no holiday calendar); entries only. Crypto always open.
- **Added:** 2026-06-11 a2886296e2 M15 Phase 0+1 ... market-hours gate (#3303)
- **Operator authorization (NONE):** NONE FOUND as quote (M15 comment); venue closed anyway
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Mirrors venue physics; approximation can err conservative at DST edges (comment).
- **Question:** No operator authorization found. Keep this gate? Signal builders for us_equity/fx/cme symbols return side=none when the market is closed (US 14:30-21:00 UTC, no holiday calendar); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-MULTI-ACCOUNT-DISPATCH-ENV` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/pipeline.py:382 _multi_account_dispatch_enabled; refusal reason at pipeline.py:1474` · also `src/runtime/pipeline.py:1474`
- **Blocks:** If env MULTI_ACCOUNT_DISPATCH is false (default true), actionable signals are refused (multi_account_dispatch_disabled) instead of dispatching. Also refuses a signal missing entry/sl/tp (actionable_signal_missing_sltp).
- **Added:** 2026-07-09 e4528db5c1 orderpath: remove legacy naked-order bypass -- refuse instead (E1-F1) (#6042)
- **Operator authorization (NONE):** NONE FOUND (a default-ON env switch; 'third gate' pattern in kind, though default permissive)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** E1-F1 audit 2026-07-09: legacy path could send naked un-sized orders; the sltp refusal (not the env flag) guards that
- **Recommendation: MAKE-REPORT-ONLY.** Default-on env switch that can disable all trading is exactly the forbidden shape; delete the flag, keep the missing-SL/TP refusal (naked-order incident E1-F1).
- **Question:** No operator authorization found. Keep this gate? If env MULTI_ACCOUNT_DISPATCH is false (default true), actionable signals are refused (multi_account_dispatch_disabled) instead of dispatching. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-PROP-RISK-CUSHION` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/prop/prop_risk_gate.py (grade_ticket_risk, enforce_ticket_cap, mode()); used by src/units/accounts/prop_risk.py:350, src/prop/breakout_executor.py:510` · also `src/units/accounts/risk.py:140 breach_guards_mode`
- **Blocks:** Prop ticket whose risk_usd exceeds remaining drawdown cushion (or cushion unknown) is capped/refused per breach_guards mode (enforce\|report).
- **Added:** NOT dated: introduced after 2026-08-25 (docstring incident); not isolated with git log -S
- **Operator authorization (NONE):** NONE FOUND as quote; docstring cites measured incident 2026-08-25 only. Note risk.py has breach_guards_mode (enforce/accept) -- accounts can already set it to report.
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Strong money evidence (terminal prop breach); but flag operator to confirm since no quote found. Owned partly by another auditor (prop lane).
- **Question:** No operator authorization found. Keep this gate? Prop ticket whose risk_usd exceeds remaining drawdown cushion (or cushion unknown) is capped/refused per breach_guards mode (enforce\|report). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-REFUSAL-COOLDOWN` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/strategy_monocle.py:34,321; pipeline.py:867 (recent_refusal_cooldown); env STRATEGY_REFUSAL_COOLDOWN_SECONDS (default 300s)`
- **Blocks:** After a strategy's package was refused, further dispatches for that strategy are skipped for 300 seconds.
- **Added:** 2026-05-14 e95900cb2b D1 extract strategy_monocle (#1109) (earlier origin not isolated)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: REMOVE.** Unauthorized time-delay gate that can drop a valid real-money entry; refusals are already journalled.
- **Question:** No operator authorization found. Keep this gate? After a strategy's package was refused, further dispatches for that strategy are skipped for 300 seconds. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-STRATEGY-PAUSED-FLAG` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/pipeline.py:604 (multiplexed_signal_builder) + src/runtime/runtime_flags.py:85 is_strategy_paused`
- **Blocks:** A strategy with a runtime pause flag file is skipped at signal-build time (no new entry; exits unaffected).
- **Added:** 2026-05-14 6fa415537b D11: runtime_flags module + multiplexer pause check (#1112)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Manual pause by a human act, not automatic; useful but unauthorized by a quote.
- **Question:** No operator authorization found. Keep this gate? A strategy with a runtime pause flag file is skipped at signal-build time (no new entry; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-ACCOUNT-MODE` (RM)

- **Where:** `src/units/accounts/risk.py:991 (RiskManager.evaluate) + config/accounts.yaml mode:` · also `config/accounts.yaml:2011 (breakout_1)`, `config/accounts.yaml:1200 (ib_live)`
- **Blocks:** Account-level execution gate: mode: dry_run turns every package for that account into a dry would-be row (no order). Entries only in effect, but a dry account also places no close. Currently dry_run: ib_live (real money), breakout_1 (prop), oanda_practice (paper).
- **Added:** 2026-05-03 1c5a8d0065 arch(BUG-039): per-account RiskManager.dry_run is the only mode toggle (#353)
- **Operator authorization (PARAPHRASE):** OPERATOR-DECLARED GATE (task: list, rec KEEP). Code comment risk.py/coordinator.py: 'operator directive 2026-05-03' (paraphrase); accounts.yaml:2011 breakout_1: verbatim 'Set it to dry_run (Recommended)' 2026-10-05 popup; CLAUDE.md 'The two execution gates'.
- **Hits, last 14 days:** not measured; static config read 2026-11-12: 3 of 14 accounts mode=dry_run (ib_live, oanda_practice, breakout_1)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Operator-declared execution gate; only the set-account-mode system action writes it.
- **Question:** Keep this gate? Account-level execution gate: mode: dry_run turns every package for that account into a dry would-be row (no order). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-ACCOUNT-SIDE-FILTER` (RM)

- **Where:** `src/runtime/account_side_filter.py; src/core/coordinator.py:1784; config/accounts.yaml:1540 alpaca_live side_filter: long` · also `src/core/coordinator.py:1790`
- **Blocks:** Per-account direction suppression: a suppressed short is demoted to dry (journalled as would-be). Only alpaca_live declares it (long).
- **Added:** 2026-08-24 ad70907d7d alpaca_live is long-only, scoped to that account alone (Tier-3, operator-directed) (#10206)
- **Operator authorization (VERBATIM):** VERBATIM: 'alpaca long only for real money, everything else stays the same.' operator 2026-08-23 (src/runtime/account_side_filter.py docstring; accounts.yaml:1540). Recorded in file, not in a checklist row.
- **Hits, last 14 days:** not measured; static: 1 of 14 accounts declares side_filter
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Operator quote on record, scoped to alpaca_live; operator may still revisit.
- **Question:** Keep this gate? Per-account direction suppression: a suppressed short is demoted to dry (journalled as would-be). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-BROKER-SHORTING` (RM)

- **Where:** `src/runtime/broker_shorting_gate.py; src/core/coordinator.py:1784-1850`
- **Blocks:** Refuses (with journal row broker_shorting_disabled) a short that would open/add short exposure on an account whose broker reports shorting_enabled false (cached 600s, fail-permissive). A short that closes a long is never refused.
- **Added:** 2026-09-28 959e8ad298 feat(coordinator): refuse shorts on any account whose broker reports shorting disabled (#13603)
- **Operator authorization (VERBATIM):** VERBATIM: 'Build the gate now', 2026-09-28, with 'Refuse short signals, with a logged reason, on any account whose broker reports shorting disabled' (coordinator.py comment ~1760, attributed to operator).
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Authorized, but the venue rejects anyway so it adds nothing but a cleaner reason; operator approved it so KEEP is defensible.
- **Question:** Keep this gate? Refuses (with journal row broker_shorting_disabled) a short that would open/add short exposure on an account whose broker reports shorting_enabled false (cached 600s, fail-permissi *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-DAILY-DD-SWITCH` (RM)

- **Where:** `src/units/accounts/daily_dd_switch.py; src/units/accounts/risk.py:998 (evaluate) / check_dd_switch:972; config/accounts.yaml risk.daily_dd_switch` · also `config/accounts.yaml:428,850,989,1219,1491`
- **Blocks:** Armed account: once day loss >= limit (3% or 0.8x firm limit), NEW entries refused until next day boundary. Reduce-only/close passes (evaluate opening=False). Armed: bybit_2, bybit_portfolio, ib_live, alpaca_portfolio, alpaca_live, breakout_2, tradeify_1, velotrade_1; disarmed: bybit_1, ib_paper, oanda_practice, alpaca_paper, alpaca_options_paper, breakout_1(absent).
- **Added:** 2026-10-09 ebc17e6aa6 DAILY-DD-SWITCH (1/2) (#17281)
- **Operator authorization (VERBATIM):** VERBATIM (2026-10-09, daily_dd_switch.py docstring + CLAUDE.md): 'the daily drawdown on at the account level. That's the only place I want there to be like a automatic off switch ... We'll arm all of them' ; popup 'Keep open, block new'. Disarm of paper accounts: accounts.yaml 'DISARMED 2026-10-29 (operator)'.
- **Hits, last 14 days:** not measured; static: 8 of 14 accounts armed (accounts.yaml 2026-11-12)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** The ONE sanctioned exception, verbatim operator quote.
- **Question:** Keep this gate? Armed account: once day loss >= limit (3% or 0.8x firm limit), NEW entries refused until next day boundary. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-EXCLUSION-PRELOOP` (RM)

- **Where:** `src/core/coordinator.py:1307 _dispatch_exclusion_reason` · also `src/core/coordinator.py:1364-1386`
- **Blocks:** Per-account pre-sizing eligibility: not_configured; symbol_exchange_routing (crypto never reaches IB and MES never reaches bybit); outside_account_scope (per-account election round); strategies_declared_empty; strategy_not_assigned (account roster); leg_account_scope. Entry only; closes go via order_monitor.
- **Added:** strategy_not_assigned/roster: 2026-05 era (not isolated); named-reason refactor 2026-09-05 38a50671bf (#11035); leg_account_scope 2026-10-27 d5c47f6007 (#20668)
- **Operator authorization (PARAPHRASE):** Roster rule is operator doctrine: CLAUDE.md 'the strategies: roster decides what trades' (operator, 2026-09-22) and 'An account configures strategies, never symbols' (operator, 2026-11-04, binding). Symbol->exchange routing: PARAPHRASE ONLY (code comment multi-symbol M11).
- **Hits, last 14 days:** not measured; excluded_by_account is stamped in pkg.meta.dispatch_exclusions_by_account (journal, VM)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Roster routing is the operator's declared mechanism, not a limitation added on top.
- **Question:** Keep this gate? Per-account pre-sizing eligibility: not_configured; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-EXECUTE-SLTP-REQUIRED` (RM)

- **Where:** `src/units/accounts/execute.py:517 (ValueError refusing live open without valid SL/TP); src/runtime/pipeline.py:1474 actionable_signal_missing_sltp`
- **Blocks:** A live OPEN order without positive SL and TP is refused. Reduce-only legs exempt.
- **Added:** 2026-05-15 50a7d88d18 fix(executor+monitor): block live orders without SL/TP; detect naked positions (#1159)
- **Operator authorization (PARAPHRASE):** PARTIAL: TP doctrine 'Every leg's bracket carries a REAL predictive take-profit at entry' (operator, 2026-10-06, binding, CLAUDE.md) supports it; the refusal itself has no quote.
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Prevents unprotected real-money positions; consistent with binding TP doctrine.
- **Question:** Keep this gate? A live OPEN order without positive SL and TP is refused. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-FLIP-POLICY-HOLD` (RM)

- **Where:** `src/runtime/intents.py:507 resolve_flip_policy, :1990-2060 compute_execution_delta (flip_suppressed_hold_policy); env FLIP_POLICY (default hold); FLIP_CONFIDENCE_THRESHOLD`
- **Blocks:** Under default hold policy an opposite-direction signal on a held position is a NOOP (no close, no reverse) unless a confidence override fires; policy flat closes without reopening.
- **Added:** 2026-05-31 1b650d264a Cross Zero: flip-policy knob (#2441)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'The DEFAULT IS hold (2026-05-31, operator-approved)'; walk-forward evidence docs/audits/walkforward-flip-policy-2026-05-30.md
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Evidence-backed default, journalled; blocks opposing entry/reversal only.
- **Question:** Keep this gate? Under default hold policy an opposite-direction signal on a held position is a NOOP (no close, no reverse) unless a confidence override fires; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-GROSS-EXPOSURE-CAP` (RM)

- **Where:** `src/units/accounts/risk.py:1016 (evaluate REFUSE GROSS_EXPOSURE_CAP) + position_size headroom clamp ~1426; src/units/accounts/exposure.py; config max_gross_exposure_pct`
- **Blocks:** Refuses new entries when account gross notional is already at/over declared multiple of equity; clamps size into remaining headroom. Declared only on ib_paper and ib_live (1.5x).
- **Added:** 2026-08-07 bb5203aeee fix(news+risk): ... RiskManager owns per-account exposure (#8600)
- **Operator authorization (VERBATIM):** VERBATIM (accounts.yaml:1173,1218): 'operator 2026-10-24 "1.5× equity (Recommended)"', MGC-SIZING-OVERSIZE. No quote for the mechanism before that.
- **Hits, last 14 days:** not measured; static: 2 of 14 accounts declare a ceiling
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Value chosen by operator popup; only 2 accounts, one real-money-but-dry.
- **Question:** Keep this gate? Refuses new entries when account gross notional is already at/over declared multiple of equity; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-HALT-FLAG` (RM)

- **Where:** `src/runtime/runtime_flags.py:75 is_halted; src/core/coordinator.py:1068 (refuse all dispatch); src/runtime/pipeline.py:1196 (status halted)`
- **Blocks:** If the halt flag file exists, every ENTRY package is refused for all accounts (returns []). Exits (order_monitor) are not halted.
- **Added:** 2026-10-02 a4fa0c6b73 fix(order-path): ORDER-AUDIT-2 halt ... (#15306) for the coordinator layer; pipeline check older (not searched)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: Prime Directive rule 7 'There is no halting' exists; the manual halt flag is a human-created file, whose authorization I did not find as a quote. Searched halt flag/halt_flag/'/halt' in docs/CLAUDE-RULES-CANONICAL.md (0 hits for an operator quote)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Manual operator stop switch, not an automatic gate; keep/remove is his call.
- **Question:** Keep this gate? If the halt flag file exists, every ENTRY package is refused for all accounts (returns []). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-HOLD-TO-BRACKET` (RM)

- **Where:** `src/core/coordinator.py:2900-3010 (intent_noop:hold_to_bracket_*)`
- **Blocks:** On non-derivative accounts (alpaca/ib) a reduce/close/flip delta is held (no order); the broker bracket is the exit. Only a flip_flat_policy close is executed. THIS CAN REFUSE A REDUCE/CLOSE.
- **Added:** 2026-06-22 9466791c49 fix(intent): hold-to-bracket (#4207)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'BL-20260622-ALPACA-REDUCE-HOLD; operator-approved 2026-06-22' (comment); no quote
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Blocks strategy-driven reduce/close on equity/futures accounts; operator should confirm his view of 'a strategy can't resize a bracketed position'.
- **Question:** Keep this gate? On non-derivative accounts (alpaca/ib) a reduce/close/flip delta is held (no order); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-IB-EXIT-BREAKER` (RM)

- **Where:** `src/main.py:486 ib_breaker_armed, :775-860 _fetch breaker; env EXIT_LOOP_IB_BREAKER_DISABLED`
- **Blocks:** In the exit-evaluation pass, after one IB queue timeout the remaining IB-routed packages are skipped for that pass (candles=None, retried next pass). THIS DELAYS exit evaluation (monitor/close) for IB positions.
- **Added:** 2026-09-12 c5fe9c35b2 Arm R2 -- per-pass IB circuit breaker (MI-240, Tier-2, operator-approved) (#11738)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: commit subject 'operator-approved'; code comment 'R2, Tier-2, 2026-09-10'; no verbatim quote found in canonical docs
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Delays closes on IB; protects exit loop latency; operator-approved by commit subject only.
- **Question:** Keep this gate? In the exit-evaluation pass, after one IB queue timeout the remaining IB-routed packages are skipped for that pass (candles=None, retried next pass). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-INTENT-SUBMIN-DELTA` (RM)

- **Where:** `src/core/coordinator.py:3100-3190 (intent_sub_min_qty_delta, intent_sub_min_notional_delta)`
- **Blocks:** A netting delta smaller than the venue min lot (or opening delta under min notional, e.g. Bybit $5) is dropped as a noop. Sub-min qty check can also swallow a reduce/close dust delta.
- **Added:** intent_sub_min_qty_delta 2026-05-14 778dbf513d (#1129); sub_min_notional 2026-10-12 1ba751bfc7 (#17696)
- **Operator authorization (PARAPHRASE):** PARTIAL: opening top-ups now sized up by operator popups 2026-11-10 / 11-11 (see GATE-TOPUP-SIZEUP-CAP); the residual drop is physics (venue rejects 110094).
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Venue-minimum physics.
- **Question:** Keep this gate? A netting delta smaller than the venue min lot (or opening delta under min notional, e.g. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-ML-ENTRY-REFUSALS` (RM)

- **Where:** `src/units/strategies/ml_entry.py:order_package (insufficient_bars, not_a_decision_bar, profile_conflict, session_refusal market_closed / market_closes_before_max_hold, reference_symbols<40, cost_gate est_cost_r>max, below_tau, bracket_unformable); src/runtime/ml_entry_profile.py:131` · also `src/units/strategies/ml_entry_v2.py`, `src/units/strategies/ml_entry_eq.py`
- **Blocks:** The ML entry leg refuses to emit a package: cost gate (est cost R above artifact max), decision threshold tau, session/close-before-hold, too few reference symbols, side_filter profile. Some are model mechanics (tau), some policy (cost_gate, session).
- **Added:** cost_gate 2026-11-02 f1362996c7 (#22259); session 2026-11-04 1b7dd75869 (#22900)
- **Operator authorization (PARAPHRASE):** PARTIAL: 2026-10-29 operator approved 'ML-consumer refusal' to stay (NO-NEW-GATES-RULE row note: 'the 4 gates that had no operator record are all APPROVED TO STAY: ... ML-consumer refusal ...'). Unclear whether that names these ml_entry refusals; cost_gate/session were added AFTER 2026-10-29.
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** cost_gate and session refusal postdate the 2026-10-29 approval; ask whether it covers them; tau/insufficient_bars are mechanics.
- **Question:** Keep this gate? The ML entry leg refuses to emit a package: cost gate (est cost R above artifact max), decision threshold tau, session/close-before-hold, too few reference symbols, side_filter pro *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-NET-POSITION-UNREADABLE` (RM)

- **Where:** `src/core/coordinator.py:2639,2782 ; legacy path :3015 (open_position_exists)`
- **Blocks:** If the journal net position cannot be read the package is refused for that account (not treated as flat); legacy non-intent path also refuses when a position already exists.
- **Added:** 2026-09-27 3f60a7e539 CA-07 (#13244); legacy open_position_exists 2026-05-14 3492da766f (#1100)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: FIX-CA-07 comment; Prime Directive 'could not look is not flat' (canonical)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Fail-closed on unreadable money state; one red flag after 3 consecutive (NO-HALT).
- **Question:** Keep this gate? If the journal net position cannot be read the package is refused for that account (not treated as flat); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-NETTING-GUARD` (RM)

- **Where:** `src/core/coordinator.py:2745-2830 (reentry_suppressed_netting_guard) + src/runtime/positions.py has_open_trade_for_strategy`
- **Blocks:** Blocks a same-direction ADD (open/increase) for a strategy/account/symbol that already holds an open trade (no pyramiding); unreadable read refuses (net_position_unreadable). Reduce/close/flip never blocked.
- **Added:** 2026-06-08 eb43fdfaf9 feat(orders): position-netting + per-trade SL/TP guard (Option A) (#3023)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: comment BL-20260608-DEMOPNL, 'Prime Directive: a required correctness fix'; no quote
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Documented correctness hazard (SL/TP overwrite); entry-only.
- **Question:** Keep this gate? Blocks a same-direction ADD (open/increase) for a strategy/account/symbol that already holds an open trade (no pyramiding); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-NEWS-VETO` (RM)

- **Where:** `src/runtime/pipeline.py:1248; src/news/news_score.py:99 _get_veto_enabled (NEWS_VETO_ENABLED default true)`
- **Blocks:** Refuses the whole signal for EVERY account incl. real money when an instrument-specific news item has sentiment < -0.6 and impact > 0.7; armed whenever NEWS_SOURCE is active (rss).
- **Added:** 2026-04-28 c1d3947233 feat(pipeline): add news veto hook to run_pipeline (M9 PR5)
- **Operator authorization (PARAPHRASE):** PARTIAL: docs/reference/env-vars.md:74 records 'operator-confirmed intended, 2026-06-28: "selecting rss is the deliberate activation"' -- that authorizes arming by activation, not the veto thresholds. Also docs/CLAUDE-RULES-CANONICAL.md:1293 allows default-ON blocking gates by name.
- **Hits, last 14 days:** not measured: news_decisions log is VM-side; env-vars.md says inert unless source active
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Quote covers activation only; a taste/risk call whether a news refusal should block money.
- **Question:** Keep this gate? Refuses the whole signal for EVERY account incl. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-OPEN-PACKAGE-ONE-PER-STRATEGY` (RM)

- **Where:** `src/runtime/pipeline.py:713 _monocle_gate (open_package_exists) and 968 _open_package_round; src/runtime/strategy_monocle.py:50 _has_open_package_for_strategy`
- **Blocks:** One open order package per strategy (per account since E35, with pair-coupled narrowing): a new entry for a strategy that already has an open package is skipped; an unreadable journal fails closed (open_package_read_failed).
- **Added:** 2026-05-04 1ef66bd118 feat(pipeline): one-open-package-per-strategy gate [strategy-monocle PR 1/3] (#387)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: pipeline.py:731 'Per the operator directive 2026-05-03: a strategy that already has an open package focuses on monitoring + updating that package' (no verbatim quote)
- **Hits, last 14 days:** comms/live_parity/latest.json (window 2026-11-05..11-12) contains 123 textual 'open_package_blocked' matches -- text count, not a verified distinct hit count; 2026-09-30 comment cites 92 of 121 live-leg emissions blocked (outside window)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Operator directive paraphrase with an incident; but confirm if operator wants it kept; blocks entries only (closes unaffected).
- **Question:** Keep this gate? One open order package per strategy (per account since E35, with pair-coupled narrowing): a new entry for a strategy that already has an open package is skipped; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-POSITION-SIZE-MARGIN-CAP` (RM)

- **Where:** `src/units/accounts/risk.py:1300-1420 (margin pre-flight cap), 1426 exposure headroom clamp`
- **Blocks:** Qty is clamped to available margin x leverage x safety buffer; returns 0 (refusal) when even min qty exceeds the ceiling.
- **Added:** 2026-05-12 045a392d92 risk: pre-flight margin cap in position_size (fixes 110007 dispatch loop) (#1001)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: none; justified by Bybit 110007 refusals ('9 refusals across 3 strategies, 30%' in comment)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** Bybit 110007 refusals cited in risk.py comments
- **Recommendation: MAKE-REPORT-ONLY.** Venue enforces the same limit; our own buffer (_MARGIN_SAFETY_BUFFER) is extra narrowing.
- **Question:** Keep this gate? Qty is clamped to available margin x leverage x safety buffer; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-PRIMARY-ELECTION-ARBITRATION` (RM)

- **Where:** `src/runtime/intents.py:1719 elect_from_gated; src/runtime/arbitration_fanout.py plan_per_account_election; pipeline._dispatch_rounds :72`
- **Blocks:** One winner per symbol per account: losing strategies' intents produce no package on that account for the tick; double_round_accounts / malformed_round refusals; allocator typed path default-off.
- **Added:** 2026-09-25 E35 per-account election (Tier-3 landing hold); original aggregate_intents earlier
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: ARCHITECTURE-CANONICAL row 2026-09-25 E35; priority tuning comments cite 'operator's stated risk preference'
- **Hits, last 14 days:** not measured; conviction_arbitration soak rows on VM
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Which signal wins when two collide is a design call; loser is simply not traded.
- **Question:** Keep this gate? One winner per symbol per account: losing strategies' intents produce no package on that account for the tick; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-PROP-STALE-BALANCE` (RM)

- **Where:** `src/core/coordinator.py:1164 _prop_sizing_balance_or_refuse, used ~1972`
- **Blocks:** Refuses sizing/dispatch for a declared prop account when its balance snapshot is stale/absent/error (phone-flow bridge exempt: still pages but emits).
- **Added:** 2026-09-28 34832828cf fix(coordinator): every declared prop account checks the prop balance snapshot on every sizing path (#13601)
- **Operator authorization (VERBATIM):** VERBATIM: 'Fix it', operator 2026-09-28 (coordinator.py comment ~1941, PI-20260921-E16...). Narrow: authorizes applying the existing refusal on every path.
- **Hits, last 14 days:** not measured; prop_balance_absent measured 7 refusals 2026-10-07..08 on breakout_2 (coordinator comment, outside window)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Prop floor breach is terminal; operator quote on record.
- **Question:** Keep this gate? Refuses sizing/dispatch for a declared prop account when its balance snapshot is stale/absent/error (phone-flow bridge exempt: still pages but emits). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-REGIME-HARD-GATE` (RM)

- **Where:** `src/runtime/intents.py:1194 _regime_router_active, :1240 _hard_regime_gate, :1648 gate_intents; config/regime_policy.yaml off-cells; env REGIME_ROUTER_DISABLED` · also `config/regime_policy.yaml`
- **Blocks:** Drops candidate intents whose (trend, vol) regime cell is off before arbitration: 20 trend off-cells and 8 trend_vol off-cells in config/regime_policy.yaml (parsed 2026-11-12). Entries only.
- **Added:** 2026-06-28 0023cde4f9 intents: regime router baseline-on + REGIME_ROUTER_DISABLED kill-switch (Tier-3) (#4920)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'Design-A vol-gate go-live, 2026-06-28' and 'Editing a cell is Tier-3, operator-gated' (regime_policy.yaml header); cell rec #5 2026-07-29 cites docs/research/regime-cell-walkforward-2026-07-29.md; no verbatim quote found. Skill regime-selectivity governs cell authoring.
- **Hits, last 14 days:** not measured: regime_hard_gate rows live in signals log on VM (no copy in repo)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Evidence per cell exists but no verbatim authorization; a walk-forward-backed filter is a risk-appetite call.
- **Question:** Keep this gate? Drops candidate intents whose (trend, vol) regime cell is off before arbitration: 20 trend off-cells and 8 trend_vol off-cells in config/regime_policy.yaml (parsed 2026-11-12). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SIZING-MULTIPLIER-REQUANT` (RM)

- **Where:** `src/core/coordinator.py:2281-2340 (downsized_to_zero)`
- **Blocks:** After reductive multipliers (conviction/advisory/news/overlay), on whole-unit venues the qty is floored to whole units; floor to zero is refused (downsized_to_zero).
- **Added:** 2026-10-15 0f7921fdb0 ORDER-AUDIT-3 (2/3) (#18192, Tier 3)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'PI-20260927-ECILBBVH-0007, ORDER-AUDIT-3 -- TIER 3' in comment; no quote
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Narrows entries below one share after a reducer; taste call whether to round up instead.
- **Question:** Keep this gate? After reductive multipliers (conviction/advisory/news/overlay), on whole-unit venues the qty is floored to whole units; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SIZING-MULTIPLIERS` (RM)

- **Where:** `src/core/coordinator.py:2230-2290; src/runtime/conviction_sizing.py, advisory_sizing.py, news_sizing.py, overlay_shadow.py apply_overlay_reduce; runtime_flags.py:221 CONVICTION_SIZING_MODE, :138 NEWS_INFLUENCE_MODE`
- **Blocks:** Reductive/narrowing size multipliers applied before the risk gate: conviction apply (mode off default), advisory downsize (model stage advisory+), overlay reduce (mode: reduce per config/overlay_policy.yaml), news downsize (mode off default). Never enlarge (except conviction symmetric).
- **Added:** advisory 2026-05-25 2b316d052f (#2014); conviction 2026-06-27 113b8522aa (#4748); news 2026-06-09 4b2fe7d2d9 (#3109); overlay 2026-10-29 d2a4ae11b6 (#21213)
- **Operator authorization (PARAPHRASE):** Overlay: Tier-3 packet evidence RQ-20261029-5785-02 (code comment) -- no quote. Conviction: 'operator-blessed 2026-06-27' (paraphrase, runtime_flags.py:215). Others none.
- **Hits, last 14 days:** not measured (annotate/apply decisions in runtime_logs on VM)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Size narrowing is a risk-appetite call; the tri-state *_MODE flags are default-off so inert unless operator flips.
- **Question:** Keep this gate? Reductive/narrowing size multipliers applied before the risk gate: conviction apply (mode off default), advisory downsize (model stage advisory+), overlay reduce (mode: reduce per *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SIZING-SUBMIN-RISK` (RM)

- **Where:** `src/units/accounts/risk.py:1228-1265; src/core/coordinator.py:2350-2431 (below_venue_min_qty)`
- **Blocks:** Risk-based qty below venue lot minimum: crypto is now SIZED UP to min (operator 2026-11-09); equity rounds up to 1 share if within a budget multiple else refuses; futures refuse sub-1-contract; a max<min contradiction still refuses.
- **Added:** below_venue_min_qty: 2026-06-21 62209a6230 (#4057); size-up reversal 2026-11-09
- **Operator authorization (VERBATIM):** VERBATIM: 'size up - that's what trading at minimum size means' operator 2026-11-09 (risk.py comment ~1247, Tier 3); 'Size up top-ups too' popup 2026-11-10; refuse-sub-1-contract: PARAPHRASE ONLY 'operator-approved refuse 2026-06-28 (#3910 Item 3)'
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Mostly physics; the remaining refusals follow venue limits.
- **Question:** Keep this gate? Risk-based qty below venue lot minimum: crypto is now SIZED UP to min (operator 2026-11-09); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SIZING-ZERO-BALANCE` (RM)

- **Where:** `src/units/accounts/risk.py:1126 (position_size gate_balance<=0); src/core/coordinator.py:2455 sized_qty<=0 refusal`
- **Blocks:** Non-positive balance sizes to 0 and the order is refused (zero_balance / sizing_failed). Also any position_size 0.0 return becomes a refusal row.
- **Added:** 2026-06-24 febb5e9476 Tier-3 risk sizing PR2/2: remove the arbitrary min_balance_usd floor (#4452)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: risk.py comment 'operator directive 2026-06-24' (this one REMOVED the floor; zero balance is 'physics')
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Physics, not policy.
- **Question:** Keep this gate? Non-positive balance sizes to 0 and the order is refused (zero_balance / sizing_failed). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SLICE-ADMISSION` (RM)

- **Where:** `src/runtime/positions.py:704 admit_slice; src/core/coordinator.py:2585 (slice refused)`
- **Blocks:** On position_model: slices accounts (bybit_1, bybit_2, bybit_portfolio) refuses an add the slice ledger cannot carry: ledger unreadable/divergent, opposite slice on one-way book, requires partial tpsl, risk unmeasurable, budget exhausted; also holds reduce/close/flip deltas to own bracket.
- **Added:** 2026-10-18 9ec7281059 NETTED-SLICES (#18455, Tier 2 HOLD)
- **Operator authorization (PARAPHRASE):** PARTIAL: accounts.yaml/coordinator cite 'NETTED-SLICES (operator 2026-10-15)' -- paraphrase, no verbatim quote found
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Several distinct refusals incl. slice_budget_exhausted narrows a real-money entry; budget policy is a risk call.
- **Question:** Keep this gate? On position_model: slices accounts (bybit_1, bybit_2, bybit_portfolio) refuses an add the slice ledger cannot carry: ledger unreadable/divergent, opposite slice on one-way book, re *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-STRATEGY-ENABLED-AND-SIDEFILTER` (RM)

- **Where:** `src/runtime/strategy_signal_builders.py:161-205 _resolve_side_filter/_side_filter_suppresses; 34 'disabled_in_yaml' return sites; config strategies.yaml enabled: and side_filter:/long_only:`
- **Blocks:** Builder-level: enabled:false returns side=none; side_filter long\|short suppresses the other direction on ALL accounts (18 short_suppressed_long_only sites). Static read 2026-11-12: 59 live+enabled, 2 live+disabled, 1 shadow+disabled of 62 strategies.
- **Added:** 2026-07-30 97aae2fb5b side_filter capability (Tier-1) + crypto short-only fine-tune (Tier-3, real-money B -- operator approval) (#7966)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: commit subject says 'operator approval'; docs/research/crypto-finetune-proposals-2026-07-30.md; 'enabled' is permissive per-strategy config (no quote needed).
- **Hits, last 14 days:** not measured; static config counts above
- **Cost of removing it:** no evidence found
- **Recommendation: OPERATOR-PREFERENCE.** Per-leg risk-appetite config; evidence in research doc.
- **Question:** Keep this gate? Builder-level: enabled:false returns side=none; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-STRATEGY-EXECUTION-SHADOW` (RM)

- **Where:** `src/core/coordinator.py:1653 (multi_account_execute) + src/strategy_registry.py execution_mode`
- **Blocks:** Strategy-level gate: execution: shadow runs and logs packages but never sends a live order on any account (demotes to dry).
- **Added:** 2026-05-24 479310f092 Merge #1862: S9 per-strategy execution gate (vwap -> shadow)
- **Operator authorization (PARAPHRASE):** OPERATOR-DECLARED GATE (rec KEEP). Code comment: 'Strategy-level execution gate (S9, operator-approved 2026-05-24)' (paraphrase, no quote); CLAUDE.md 'The two execution gates'.
- **Hits, last 14 days:** not measured; static config: 1 shadow leg of 62
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Operator-declared execution gate.
- **Question:** Keep this gate? Strategy-level gate: execution: shadow runs and logs packages but never sends a live order on any account (demotes to dry). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-SUPPORTED-SYMBOLS` (RM)

- **Where:** `src/runtime/intents.py:152 supported_symbols, :705 StrategyIntent validation`
- **Blocks:** An intent for a symbol not in the static base set unioned with accounts' symbols and rostered strategies' symbols is rejected at construction.
- **Added:** 2026-06-11 663492917f Config-driven symbol support: intent whitelist (#3358)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: CLAUDE.md 'accounts.yaml::symbols is NOT a gate' (operator, 2026-09-22) cuts against narrowing; the union is built to widen, not narrow.
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Whitelist union is fail-safe, but a symbol whitelist is a gate by the operator's 2026-09-22 rule; log instead.
- **Question:** Keep this gate? An intent for a symbol not in the static base set unioned with accounts' symbols and rostered strategies' symbols is rejected at construction. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-TOPUP-SIZEUP-CAP` (RM)

- **Where:** `src/core/coordinator.py:3050-3095 (qty_size_up_capped)`
- **Blocks:** A raised opening top-up may not exceed the target by more than one venue minimum lot; past that the top-up is dropped (intent_sub_min_qty_delta).
- **Added:** 2026-11-10/11 (cap added after 2026-11-10 popup; PR not isolated)
- **Operator authorization (VERBATIM):** VERBATIM: 'Approve with a cap (Recommended)', operator popup 2026-11-11 ~22:25Z (coordinator.py comment).
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Authorized cap with quote.
- **Question:** Keep this gate? A raised opening top-up may not exceed the target by more than one venue minimum lot; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-OPTIONS-EXPRESSION-REFUSAL` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/units/accounts/execute.py:~540 place_options_expression refused`
- **Blocks:** On accounts with an options: block, an open with no chain/no fit/over budget places nothing (options_expression:<reason>).
- **Added:** 2026-06-27 bb86787c94 Alpaca options Slice-3b (#4848)
- **Operator authorization (NONE):** NONE FOUND (paper account)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** alpaca_options_paper only.
- **Question:** No operator authorization found. Keep this gate? On accounts with an options: block, an open with no chain/no fit/over budget places nothing (options_expression:<reason>). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-REGIME-ML-VERDICT-MODE` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/runtime_flags.py:154; intents.py:969,1240; env REGIME_ML_VERDICT_MODE (default off)`
- **Blocks:** Default-off mode letting an ML vol verdict drive regime gating; off = no effect.
- **Added:** 2026-06-27 113b8522aa A + B: regime-ML -> live order influence (#4748)
- **Operator authorization (NONE):** NONE FOUND (comment 'operator-gated PR' for Phase 2)
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Default-off env mode is inert; remove or keep as shadow, no live effect today.
- **Question:** No operator authorization found. Keep this gate? Default-off mode letting an ML vol verdict drive regime gating; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-DESK-EXCLUSIVE-HOLD`

- **Where:** `src/core/coordinator.py:2655-2700; src/units/strategies/claude_desk.py exclusive_hold_refusal / EXCLUSIVE_HOLD_LEGS`
- **Blocks:** On a non-slice account rostering claude_desk or other exclusive-hold legs (ml_entry on alpaca_paper), a strategy leg and the exclusive leg never share one symbol's net position; refused (journalled).
- **Added:** 2026-10-27 d5c47f6007 DESK-PAPER-ACCOUNTS (#20668, Tier 3)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: comments DESK-PAPER-ACCOUNTS, ALPACA-LIVE-ACTIVITY-ML 2026-11-01; no quote found
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Paper accounts only; has mechanical reason.
- **Question:** Keep this gate? On a non-slice account rostering claude_desk or other exclusive-hold legs (ml_entry on alpaca_paper), a strategy leg and the exclusive leg never share one symbol's net position; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-ENABLED-FLAG-GREP`

- **Where:** `grep -rn _ENABLED src scripts config (runtime files)` · also `src/runtime/intents.py:1233`, `src/runtime/insights/generator.py:117`, `src/bot/comms_handler.py:699`
- **Blocks:** Result of the 'third gate' probe: no default-off *_ENABLED env gate found on the entry path. Only hits are comments saying it was removed (POSITION_NETTING_GUARD_ENABLED, MULTI_SYMBOL_ENABLED, ADVISORY_MODE), INSIGHTS_ENABLED (analyst process), COMMS_PUSH_ENABLED (push, default 0), REGIME_ROUTER_ENABLED (legacy falsy value = off), NEWS_VETO_ENABLED (default true).
- **Added:** n/a
- **Operator authorization (PARAPHRASE):** n/a (probe finding)
- **Hits, last 14 days:** n/a
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Informational; legacy REGIME_ROUTER_ENABLED=0 still disables regime router (intents.py:1233) -- the only live-path default-permissive flag; positive control: grep found NEWS_VETO_ENABLED and COMMS_PUSH_ENABLED.
- **Question:** Keep this gate? Result of the 'third gate' probe: no default-off *_ENABLED env gate found on the entry path. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-ENV-DISABLED-KILLSWITCHES`

- **Where:** `src/main.py:580,1166 (EXIT_LOOP_FINAL_PASS_DISABLED, EXIT_LOOP_DECOUPLE_DISABLED); src/runtime/reconcile_loop.py:89 RECONCILE_OFFTICK_DISABLED; src/runtime/strategy_monocle.py (two above); src/core/coordinator.py:4277 ACCOUNT_CONTEXT_SNAPSHOTS_DISABLED; forecast_live/cross_asset_live/regime_bar_scoring *_DISABLED`
- **Blocks:** Default-ON capabilities each with a *_DISABLED env rollback; they only narrow when someone sets them. Listed so 'third gate' grep for _DISABLED has a disposition.
- **Added:** various 2026-06..09 (not individually isolated)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: code comments 'operator-approved rollback kill-switch 2026-08-12' (main.py:1166)
- **Hits, last 14 days:** not measured; env values live on VM only
- **Cost of removing it:** no evidence found
- **Recommendation: MAKE-REPORT-ONLY.** Inert unless set; observe-only ones gate nothing that trades.
- **Question:** Keep this gate? Default-ON capabilities each with a *_DISABLED env rollback; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-MIRROR-FOLLOW`

- **Where:** `src/runtime/mirror_pairs.py follow_decision; src/core/coordinator.py:1508`
- **Blocks:** A Stage-2 mirror (bybit_portfolio etc.) places a package only if its real-money primary placed it in the same call; otherwise logs mirror_skipped_primary_not_placed.
- **Added:** 2026-10-12 1ba751bfc7 MIRROR-QTY-DIVERGE (#17696, Tier 3 HOLD)
- **Operator authorization (PARAPHRASE):** Derived from operator rule 'Stage 2 is one stage' (operator, 2026-09-21; CLAUDE.md, OPERATING-PLAN s2 line 308 'mirror and live carry the IDENTICAL trades'). No verbatim quote on the gate itself.
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** Incident pkg-63b56da53bfe4d64: bybit_2 top-up refused by venue while bybit_portfolio filled 160.9
- **Recommendation: KEEP.** Enforces operator-declared identical-trades rule with incident evidence; affects paper mirror, and Alpaca superset rule noted.
- **Question:** Keep this gate? A Stage-2 mirror (bybit_portfolio etc.) places a package only if its real-money primary placed it in the same call; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-PAIRS-DDSWITCH-HALT`

- **Where:** `src/units/strategies/pairs_executor.py:2161-2181`
- **Blocks:** Refuses NEW pair opens (not closes) when the account daily-DD switch is tripped or the trader halt flag is present.
- **Added:** 2026-10-02 a4fa0c6b73 (halt, #15306); 2026-10-12 a1965ba55a (dd switch, #17747)
- **Operator authorization (PARAPHRASE):** Covered by DD-switch operator quote (see GATE-DAILY-DD-SWITCH) for the dd part; halt part: PARAPHRASE ONLY: comment 'AUD-20260927-CA-A02, ORDER-AUDIT-2 item 1' in file
- **Hits, last 14 days:** not measured: trade_journal.db / signals ledger live on the VM only; repo has no ledger covering 2026-10-29..11-12 (probed comms/*.jsonl, runtime_logs/, find *.db -> only a research backtest db)
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Mirrors the authorized entry-side DD switch; closes unaffected.
- **Question:** Keep this gate? Refuses NEW pair opens (not closes) when the account daily-DD switch is tripped or the trader halt flag is present. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `GATE-PAIRS-EXECUTION`

- **Where:** `config/pairs.yaml per-pair execution: shadow\|live; src/units/strategies/pairs_executor.py:run_pairs_tick (skip_non_paper_account ~1515, skip_cooldown 2008, skip_size 2137)`
- **Blocks:** M22 pairs sleeve gate: per pair execution shadow places nothing; also refuses a pair routed to a non-paper account, per-pair cooldown_bars, both-legs-or-nothing size check.
- **Added:** 2026-10-12 a1965ba55a PAIRS-ALPACA-BUILD (#17747) for skip_non_paper_account; sleeve itself earlier
- **Operator authorization (PARAPHRASE):** OPERATOR-DECLARED (task: M22 gate config/pairs.yaml, rec KEEP). Header: 'PAPER-ONLY, edge-gated (operator directive 2026-07-16): "if it's not negative, trade it on paper, but not on real money."' (config/pairs.yaml header)
- **Hits, last 14 days:** not measured; static read: config/pairs.yaml pairs list is EMPTY (pairs: []) on 2026-11-12, so the gate currently has nothing to gate
- **Cost of removing it:** no evidence found
- **Recommendation: KEEP.** Declared sleeve gate, quote on record; naked-leg protection has incident evidence.
- **Question:** Keep this gate? M22 pairs sleeve gate: per pair execution shadow places nothing; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### Active management (close / reduce / amend) (36)

#### `AM-ALPACA-CLOSE-SIBLING-REFUSE` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/live_review_apply.py:1005` · also `scripts/ops/live_review_apply.py:944`
- **Blocks:** An Alpaca close is refused when another open trade exists on the same symbol (the venue flatten would close it too); bybit reduce is refused when qty is not legal at the venue lot step.
- **Added:** 2026-10-26 7968bc403a LTR-ALL-ACTIONS part 2
- **Operator authorization (NONE):** NONE FOUND (executor correctness)
- **Hits, last 14 days:** Evidence: bybit_portfolio refused off-step reduce qty 16239.25 on 2026-11-09 (mandates.yaml expired_reason, issue #24484). Counts otherwise not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** A whole-symbol flatten would close a leg the review did not target.
- **Recommendation: KEEP.** Prevents closing the wrong leg; fix by scoped close not by removal.
- **Question:** No operator authorization found. Keep this gate? An Alpaca close is refused when another open trade exists on the same symbol (the venue flatten would close it too); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-AMEND-POSITION-SL-BYBIT-ONLY` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/amend_position_sl.py:267` · also `scripts/ops/amend_position_sl.py:325-371`
- **Blocks:** The operator's manual amend system-action refuses non-Bybit, non-live accounts, ambiguous or non-open trades, a looser stop, wrong-side stop; so it can never act on prop or Alpaca accounts.
- **Added:** 2026-10-24 171c733a41 amend-position-sl (#19902)
- **Operator authorization (NONE):** NONE FOUND for the Bybit-only scope (row AMEND-SL-ACTION); operator ask for the capability is the 2026-10-29 note about #21186/#21193 ADA moves.
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** none found beyond mechanics
- **Recommendation: MAKE-REPORT-ONLY.** Prop amends already go through bracket_request / phone_trail; this just narrows a tool to the account it was built for.
- **Question:** No operator authorization found. Keep this gate? The operator's manual amend system-action refuses non-Bybit, non-live accounts, ambiguous or non-open trades, a looser stop, wrong-side stop; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PACKAGE-LIVE-STATE` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/live_review_apply.py:248` · also `scripts/ops/live_review_apply.py:242-246`, `scripts/ops/live_review_apply.py:1195`
- **Blocks:** Whole apply is refused 'package not open' unless status open, or emitted with a placed/filled prop ticket; unreadable tickets -> could_not_look.
- **Added:** 2026-11-12 3335a0aa41 prop apply: live prop-only package no longer refused as 'not open' (#24881)
- **Operator authorization (NONE):** NONE FOUND (a correctness filter; its history is the bug fix)
- **Hits, last 14 days:** Evidence of prior hits: SOL short pkg-50f5eed272f64197 refused three directed tightens (2026-11-09 20:15Z, 11-10 15:51Z/15:52Z) before the fix (comment at line 242). Post-fix count not measured.
- **Cost of removing it:** Prevents applying to a closed package.
- **Recommendation: KEEP.** Mechanical; the prop false-negative was fixed 2026-11-12.
- **Question:** No operator authorization found. Keep this gate? Whole apply is refused 'package not open' unless status open, or emitted with a placed/filled prop ticket; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-APP-CLOSE-REFUSALS` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1595` · also `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1617-1634`, `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1830`
- **Blocks:** App-side executeClose fails/refuses before any click on: ledger already holds the request id, no venue symbol, Positions unread, 0 or >1 position rows, dry submit mode, reduce when the position sheet will not open ('reduce: sheet not open (sheet_not_open)') or the reduce dialog's quantity input is unmeasured. This is the trigger case's 'phone could not act'.
- **Added:** 2026-11-09 7ecd2efaf5 PHONE-ENTRY-CANCEL (#24469)
- **Operator authorization (NONE):** NONE FOUND for these refusals. Contrary quote: 2026-11-09 ~08:22Z 'I never directed there to be a forbidden actions list, nor do I want one - the system must be able to take whatever actions necessary to ensure smooth autonomous operation' (MainActivity.kt:1669 comment).
- **Hits, last 14 days:** Window not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo. In-repo pre-window evidence: checklist BREAKOUT-POS-UNPARSED, PHONE-AMEND-REFUSED-1025 (sheet_not_open) and 4 pipeline items dated 2026-10-15..26.
- **Cost of removing it:** Each check guards a misclick on a live venue UI (wrong row, multi-row). They are fail-closed read guards, not policy.
- **Recommendation: KEEP.** These are mechanical read-before-click guards; fix the sheet reader/reduce dialog (PHONE-CLOSE-CARDS) instead of loosening them. Dry-mode refusal is the only policy-like one.
- **Question:** No operator authorization found. Keep this gate? App-side executeClose fails/refuses before any click on: ledger already holds the request id, no venue symbol, Positions unread, 0 or >1 position rows, dry submit mode, reduce when *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-REDUCE-CAPABILITY` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/prop/phone_cancel.py:654` · also `src/web/api/routers/prop.py:327`, `src/prop/phone_executor.py:391`, `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1621-1634`
- **Blocks:** A phone REDUCE (partial close) is refused at claim, with one ping, unless the app declares 'reduce' in its claim; builds up to 1b.380 never execute one (a full close is unaffected).
- **Added:** 2026-11-12 f85ed296bb phone: serve a reduce only to an app that declares it (#25227)
- **Operator authorization (NONE):** NONE FOUND (session-authored capability negotiation, commit f85ed296bb; no quote)
- **Hits, last 14 days:** 2026-11-12 only (change merged that day): count of refused reduces not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Commit message: on a one-tap-Close venue a reduce would close the WHOLE position while reporting failed. Real mechanism, evidence in the commit.
- **Recommendation: KEEP.** Prevents a partial close becoming an unintended full close; the cause is the app not executing reduce, so build that rather than remove the check.
- **Question:** No operator authorization found. Keep this gate? A phone REDUCE (partial close) is refused at claim, with one ping, unless the app declares 'reduce' in its claim; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-TRAIL-PLAN-GUARDS` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/prop/phone_trail.py:397` · also `src/prop/phone_trail.py:80`, `src/prop/phone_trail.py:424-432`, `src/prop/phone_trail.py:464-476`
- **Blocks:** Phone trail planning skips a ticket: older than 14 days, test ticket, no declared leg, a human_hold (a human's stop is 'never fought'), one amend already outstanding, in backoff (up to 8 bars) after failures, new stop within max(2 steps, 0.1 ATR) of price, last_bar already planned.
- **Added:** 2026-10-08 1763b675bb phone trail server half (#16959)
- **Operator authorization (NONE):** NONE FOUND for the quoted limits; no-halting quote 2026-10-09 'There is no halting.' is why failures back off instead of latching (phone_trail.py docstring).
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** human_hold prevents the system fighting a stop a human set by hand; backoff prevents click loops.
- **Recommendation: MAKE-REPORT-ONLY.** Keep as warnings; the 14-day age cut and human_hold should not silently stop protection of an open position.
- **Question:** No operator authorization found. Keep this gate? Phone trail planning skips a ticket: older than 14 days, test ticket, no declared leg, a human_hold (a human's stop is 'never fought'), one amend already outstanding, in backoff (u *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-CLAIM-TIME-BLOCKS` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/prop/phone_executor.py:353` · also `src/prop/phone_cancel.py:73`, `src/prop/breakout_executor.py`
- **Blocks:** At claim a phone ticket is refused if it opposes a symbol the account now holds (opposite_direction_blocked), and an exec_test ticket is refused when its bounds fail; close/cancel validity expires after 6 h (CANCEL_VALID_S) and a claim after 180 s with no report.
- **Added:** 2026-11-09 0d2e3441ed opposite-direction block (#24402); CANCEL_VALID_S 2026-11-09 7ecd2efaf5
- **Operator authorization (NONE):** NONE FOUND (manager 2026-11-09 comment only).
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Prevents an opposite-side ticket netting a position at an exchange.
- **Recommendation: OPERATOR-PREFERENCE.** Entry-side but affects what the phone serves; unquoted design choice.
- **Question:** No operator authorization found. Keep this gate? At claim a phone ticket is refused if it opposes a symbol the account now holds (opposite_direction_blocked), and an exec_test ticket is refused when its bounds fail; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-HUMAN-HOLD` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/prop/prop_amend_gate.py:102` · also `src/prop/phone_trail.py:578-581`, `src/prop/phone_trail.py:716`
- **Blocks:** A live-review/desk amend of a phone prop ticket is refused (prop_human_hold) when a human_hold is on the ticket; request_tp_amend/sl_tighten/sl_widen also refuse 'a human's stop is held'.
- **Added:** 2026-10-27 ee0d2893a8 DESK-2-RISK-GATE; phone_trail hold earlier
- **Operator authorization (NONE):** NONE FOUND (manager/lane design, DESK-2-RISK-GATE row 'phone human_hold refused at the gate')
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo; 0 prop_human_hold reasons visible in reviews.jsonl account_reads (reasons are null there).
- **Cost of removing it:** Stops the system overwriting a stop a human placed; but the same hold blocks a CLOSE amend? Close is not blocked by base verdict, yet decide_prop returns refuse before the reduce-only check.
- **Recommendation: REMOVE.** The hold sits ahead of the reduce-only check, so it can refuse a close of a losing position; a human's stop is not a reason to refuse a de-risking action.
- **Question:** No operator authorization found. Keep this gate? A live-review/desk amend of a phone prop ticket is refused (prop_human_hold) when a human_hold is on the ticket; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-TICKET-EXPIRE-REFUSALS` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/prop_ticket_expire.py:100` · also `scripts/ops/prop_ticket_expire.py:17-31`
- **Blocks:** prop-ticket-expire refuses any ticket not on a REST account, not expiry_prompted/emitted-past-validity, or referenced by a prop_fills row.
- **Added:** 2026-10-07 0fcba3dc77 prop-ticket-expire (#16977)
- **Operator authorization (NONE):** NONE FOUND (fail-closed data-integrity guard on a Tier-2 action)
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** A ticket with fills may be a live position; expiring it would hide it.
- **Recommendation: KEEP.** Data-integrity guard; does not affect closing.
- **Question:** No operator authorization found. Keep this gate? prop-ticket-expire refuses any ticket not on a REST account, not expiry_prompted/emitted-past-validity, or referenced by a prop_fills row. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-VM-ACTION-MATRIX` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/live_review_apply.py:704` · also `scripts/ops/live_review_apply.py:755-765`, `docs/claude/work/checklist/LTR-ACTION-EXECUTOR-GAPS.json`
- **Blocks:** Executor matrix: a prop_vm account (tradeify_1, velotrade_1) can only move_tp; close, reduce, widen_sl, add refuse no_action_path:<action>. Alpaca only close (sole leg) and move_tp; IB and other none; add_size nowhere.
- **Added:** 2026-10-26 7968bc403a LTR-ALL-ACTIONS part 2
- **Operator authorization (NONE):** NONE FOUND (a missing executor, not a quoted limit). Row LTR-ACTION-EXECUTOR-GAPS says 'Not built ... blocked CLIENT-SIDE'; related operator quote 2026-11-09 ~08:22Z against forbidden-action lists is in MainActivity.kt:1669.
- **Hits, last 14 days:** 2026-10-29..2026-11-12: 4 tighten_sl rows on tradeify_1+velotrade_1 (pkg-50f5eed272f64197); tighten maps to a different path (meta.sl_floor). Closes on prop_vm: VM close_position exists (run_close_position) but live_review_apply never calls it. Refusal counts: not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** None for the matrix itself (it reflects absent executors); VM prop already has run_close_position (prop_executor.py:1902) that is not wired.
- **Recommendation: REMOVE.** A refusal for a missing executor is a gap, not a safety rule: wire close/reduce for prop_vm to run_close_position and drop the refusal.
- **Question:** No operator authorization found. Keep this gate? Executor matrix: a prop_vm account (tradeify_1, velotrade_1) can only move_tp; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-ADVICE-ONLY-ALL-CLASSES` (RM) · trigger case

- **Where:** `src/runtime/live_review_rows.py:35` · also `src/runtime/live_review_rows_watch.py:186`, `scripts/ops/live_review_dispatch.py:531`, `scripts/ops/desk_intake.py:213`, `config/mandates.yaml:1275`
- **Blocks:** Every in-trade class (tighten_sl, widen_sl, move_tp, partial_close, close, change_size, add_entry) from the reviewer or desk is recorded and graded but never executed, on every account including prop, unless a per-package/per-account auto mandate scopes it.
- **Added:** 2026-10-29 8615a8f0bb LTR: tighten_sl is ADVICE ONLY (#21024); extended to every class 2026-10-28 per mandate comment (row DESK-V1-MGMT-ADVICE-ONLY, PR 21026)
- **Operator authorization (VERBATIM):** VERBATIM 'Advice-only tightens (Recommended)' (popup 2026-10-28 ~20:35Z) and 'Advice-only until tested' (popup ~21:07Z), config/mandates.yaml:1262-1275 comments, row DESK-V1-MGMT-ADVICE-ONLY. Both are popup option picks following manager-proposed options; operator also said 2026-10-28 'SL tightening is just one lever' (ARCHITECTURE-CANONICAL.md:736) and 2026-11-12 ~00:00Z 'if it needs me, then it needs to ping me so that I can immediately do that' (trade_approvals.py:3).
- **Hits, last 14 days:** 2026-10-29..2026-11-12, population = 524 rows in comms/live_review/reviews.jsonl: 56 carry an in-trade action (31 close, 23 tighten_sl, 2 partial_close); 0 of 56 have disposition.applied_at set; 53 route=recommended, 2 operator_ask, 1 none. 8 of the 56 sit on a package carried by a real-money/prop account (bybit_2, bybit_portfolio, breakout_2, tradeify_1, velotrade_1), 5 of those on prop. Rows written by directed actions or the paper auto mandate are not in this ledger, so 0 applied is a floor on blocking, not on executions.
- **Cost of removing it:** Reviewer evidence on file: DESK-LIFECYCLE-S0 (#20967) 981 tightens -0.097R net; whole-trade management -0.159/-0.124R vs hold; RQ-20261029-1f39-02 no class passes RULE-AM-RISK-ADJUSTED-V1. No evidence covers a CLOSE of a position already deep in loss on prop: the evidence is per-trade mean R, not book drawdown. Trigger case: two losing breakout_2 positions could not be closed because close is advice-only.
- **Recommendation: OPERATOR-PREFERENCE.** Authorized by popup picks, but the picks were made on tighten evidence and extended to close/partial_close/move_tp without a close-specific test; the operator should decide whether a close with a stated reason and confidence on a LOSING prop position stays advice-only.
- **Question:** Keep this gate? Every in-trade class (tighten_sl, widen_sl, move_tp, partial_close, close, change_size, add_entry) from the reviewer or desk is recorded and graded but never executed, on every acc *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-APK-AMEND-REFUSALS` (RM)

- **Where:** `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1674` · also `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:2034-2060`
- **Blocks:** App refuses an amend before any click: loosening the stop unless the server declares widen_sl, TP change on the sheet path ('a TP revision is not built'), non-foreground view, new stop not tighter, sheet side/volume mismatch, stop within max(2 steps,0.1%) of price, Stop row n != 1, unread stop trigger.
- **Added:** 2026-10-08 048822347f (#16980); sheet path 2026-10-15 381c0cea7c (#18114)
- **Operator authorization (VERBATIM):** VERBATIM 2026-11-09 ~08:22Z 'I never directed there to be a forbidden actions list, nor do I want one - the system must be able to take whatever actions necessary to ensure smooth autonomous operation' (MainActivity.kt:1669) loosened the widen refusal to intent-bound. Others: no quote.
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Read guards stop a click on a misread row.
- **Recommendation: KEEP.** Mechanical misclick guards; the widen/forbidden-list part already relaxed per operator quote.
- **Question:** Keep this gate? App refuses an amend before any click: loosening the stop unless the server declares widen_sl, TP change on the sheet path ('a TP revision is not built'), non-foreground view, new *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-AUTO-MANDATE-BOUNDS` (RM)

- **Where:** `scripts/ops/live_review_apply.py:628` · also `config/mandates.yaml:1441-1449`, `src/runtime/ltr_auto_mandate.py`
- **Blocks:** Under a per-package auto mandate: refuse a repeated review_id, a package with no TP (both_brackets), a TP not beyond the mark (tp_live_target), and a widen beyond -1R or with entry/risk unread.
- **Added:** 2026-10-29 cfb15c257a MD-LTR-ADA-AUTO (#21203)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: mandate bounds list in mandates.yaml:1440-1450 written by lane; operator quote only for the grant ('Every action').
- **Hits, last 14 days:** Window: mandates expired; 0 active-grant applies after 2026-11-09T09:51Z (mandates.yaml). XRP partial: bybit_portfolio refused off-step qty 16239.25 (mandates.yaml expired_reason).
- **Cost of removing it:** The widen-within-1R bound limits added loss on an automatic widen.
- **Recommendation: OPERATOR-PREFERENCE.** Risk-appetite bounds on a grant; only the operator should size them.
- **Question:** Keep this gate? Under a per-package auto mandate: refuse a repeated review_id, a package with no TP (both_brackets), a TP not beyond the mark (tp_live_target), and a widen beyond -1R or with entry *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-AUTO-MANDATE-SCOPE` (RM)

- **Where:** `config/mandates.yaml:1376` · also `src/runtime/ltr_auto_mandate.py`, `config/mandates.yaml:1518-1540`
- **Blocks:** Auto-apply exists only for ONE package (MD-LTR-ADA-AUTO, expired), a single-use XRP partial (expired) and the paper demo-floor accounts (MD-LTR-PAPER-AUTO: bybit_1, alpaca_paper, ib_paper). Real money, mirrors and prop have NO auto path; every other package is advice-only.
- **Added:** 2026-10-29 cfb15c257a MD-LTR-ADA-AUTO (#21203); paper scope 2026-11-01
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-29 ~07:40Z 'I want to put a standing mandate for ltr lanes recommendations on this trade to be applied automatically'; MD-LTR-PAPER-AUTO source 2026-11-01 popup (mandates.yaml ~1520). Scoping to that one package/paper is the lane's design, not a quoted limit.
- **Hits, last 14 days:** Population: mandates.yaml at HEAD; MD-LTR-ADA-AUTO expired 2026-10-29T10:47:53Z, MD-LTR-XRP-PC-20261109 expired 2026-11-09T09:51:52Z; so 0 real-money or prop packages had an active auto grant for most of 2026-10-30..2026-11-12.
- **Cost of removing it:** Auto-applying every class on real money would execute classes the evidence says lose (-0.1R/trade) without a per-class pass.
- **Recommendation: OPERATOR-PREFERENCE.** A standing real-money/prop mandate for CLOSE only is a grant only the operator can make; propose it.
- **Question:** Keep this gate? Auto-apply exists only for ONE package (MD-LTR-ADA-AUTO, expired), a single-use XRP partial (expired) and the paper demo-floor accounts (MD-LTR-PAPER-AUTO: bybit_1, alpaca_paper, i *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-BOTH-BRACKETS-TP-DOCTRINE` (RM)

- **Where:** `src/runtime/live_review_intent.py:391` · also `src/runtime/live_review_intent.py:405-414`, `scripts/ops/live_review_apply.py:628`
- **Blocks:** Refuses move_tp/widen/reduce/size actions that would leave a leg without BOTH brackets (both_brackets_required:sl\|tp) or a TP through the mark, not beyond entry, or the 50R sentinel (tp_doctrine); close is exempt.
- **Added:** 2026-10-26 7968bc403a LTR-ALL-ACTIONS part 2
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-26 ~19:02Z 'in general, every trade always must have BOTH brackets, not related to this skill. Claude can move the brackets, but nothing is supposed to remove brackets' (mandates.yaml:1244, rows LTR-ALL-ACTIONS, BRACKETS-ALWAYS).
- **Hits, last 14 days:** not measured: reasons absent from reviews.jsonl; not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Operator rule; a missing bracket leaves unprotected exposure.
- **Recommendation: KEEP.** Directly authorized by the operator's verbatim bracket rule.
- **Question:** Keep this gate? Refuses move_tp/widen/reduce/size actions that would leave a leg without BOTH brackets (both_brackets_required:sl\|tp) or a TP through the mark, not beyond entry, or the 50R sentine *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-BRACKET-REQUEST-NEVER-LOOSEN` (RM)

- **Where:** `src/prop/bracket_request.py:70` · also `src/prop/bracket_request.py:30-66`
- **Blocks:** request_bracket (amend_prop_bracket.py) refuses a VM-prop TP amend for an adapter that cannot amend a TP, an SL looser than the ticket's ('a prop executor never loosens a stop'), TP on the wrong side, a non placed/filled ticket, or both tp and clear_tp.
- **Added:** 2026-11-12 6412616377 PROP-BRACKET-APPLY (#25016)
- **Operator authorization (VERBATIM):** VERBATIM 2026-11-11 'PROP-BRACKET-APPLY, operator 2026-11-11' asks for the capability (amend_prop_bracket.py:2); the never-loosen rule: no quote; contrary 2026-11-09 'I never directed there to be a forbidden actions list' (MainActivity.kt:1669).
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Executors are tighten-only by construction (dxtrade ModifyRollout).
- **Recommendation: OPERATOR-PREFERENCE.** A prop widen is a risk-appetite call and the executors would need changing.
- **Question:** Keep this gate? request_bracket (amend_prop_bracket.py) refuses a VM-prop TP amend for an adapter that cannot amend a TP, an SL looser than the ticket's ('a prop executor never loosens a stop'), T *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-DECIDE-AMEND-TIGHTEN-RULES` (RM)

- **Where:** `src/runtime/live_review_intent.py:258` · also `config/live_trade_review.yaml:204`, `src/runtime/live_review_intent.py:304-324`
- **Blocks:** A tighten is refused when: wrong side of mark, would loosen against the journal OR venue stop, already at/tighter, inside the min_buffer_atr noise floor (clipped when still a real tighten), duplicate review_id, ATR/mark/leg read missing (could_not_look, retried, one flag after 3).
- **Added:** 2026-10-25 81a0b83602 LTR-6R (#20139)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'operator-approved 2026-10-25' design docs/plans/live-trade-review-DESIGN.md; operator 2026-10-29 verbatim kept the noise floor ('a distance, not a count', ARCHITECTURE-CANONICAL.md:1741 describing REMOVE-PER-BAR-CAP) .
- **Hits, last 14 days:** Window: 23 tighten_sl rows; account_reads show 0 explicit refusal reasons stored; would_apply 2/2/2/35 for bybit_2/portfolio/alpaca_paper/bybit_1 across all reads.
- **Cost of removing it:** Wrong-side stop fires at once; loosen would reverse a tighten.
- **Recommendation: KEEP.** Mechanical correctness of a stop move; the noise floor is operator-sanctioned as a distance.
- **Question:** Keep this gate? A tighten is refused when: wrong side of mark, would loosen against the journal OR venue stop, already at/tighter, inside the min_buffer_atr noise floor (clipped when still a real *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-DIRECTED-ACTION-VALIDATION` (RM)

- **Where:** `src/runtime/directed_actions.py:102` · also `src/runtime/directed_actions.py:56`, `src/runtime/directed_actions.py:60`
- **Blocks:** A directed operator action is refused without a verbatim operator_quote, directed_by, schema, id, valid action in {tighten_sl, move_sl, move_tp, close, partial_close} (no change_size/add), level/fraction fields; a record first seen over 900 s after created_at is refused stale_record; could_not_look retried 600 s then expired.
- **Added:** 2026-10-29 e87e311552 TRADE-ACTION-FAST-PATH (#21216)
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-29 ~08:20Z 'the action needs to be immediate' (directed_actions.py:3-5, row TRADE-ACTION-FAST-PATH); the quote requirement and the 900 s stale rule: lane design, no quote.
- **Hits, last 14 days:** comms/directed_actions/ is not on main (lives on branch directed/actions): not measured. Pre-window: 3 directed tightens refused 'not open' 2026-11-09/10 (live_review_apply.py:242).
- **Cost of removing it:** Stale rule stops a replayed close at a changed price.
- **Recommendation: MAKE-REPORT-ONLY.** Quote requirement is cheap provenance; the stale-expiry should warn and let the operator re-confirm, not discard.
- **Question:** Keep this gate? A directed operator action is refused without a verbatim operator_quote, directed_by, schema, id, valid action in {tighten_sl, move_sl, move_tp, close, partial_close} (no change_si *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-EXIT-HEAD-ADVISORY-STAGE` (RM)

- **Where:** `src/runtime/exit_head_apply.py:76` · also `src/runtime/exit_head_apply.py:45`
- **Blocks:** The ML exit head closes a trade only when exit_head_action: close is declared, the artifact stage is advisory, an optional model pin matches and the policy fires; any missing/malformed input returns None (no close).
- **Added:** 2026-09-07 86e059cc93 MI-150 ict_scalp exit head; donchian since 2026-07-12 (#6211)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'the operator promotion gate' (module docstring); promotion to advisory is a Tier-3 operator act.
- **Hits, last 14 days:** not measured: exit_head decisions are in VM logs; prop legs do not consume the exit head.
- **Cost of removing it:** docstring: 'A spurious close is the expensive failure here'.
- **Recommendation: KEEP.** Standard promotion ladder for an ML decision; not a refusal of a human close.
- **Question:** Keep this gate? The ML exit head closes a trade only when exit_head_action: close is declared, the artifact stage is advisory, an optional model pin matches and the policy fires; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-FRESH-ENTRY-ON-RISK-ADD` (RM)

- **Where:** `src/units/accounts/risk.py:909` · also `src/units/accounts/prop_risk.py:294`, `scripts/ops/live_review_apply.py:786`
- **Blocks:** widen_sl / add / size-up must pass the account's own fresh-entry check (mode, daily-DD switch block on new risk, gross exposure cap, and the size a fresh entry would get); PropRiskManager adds SKIP_WEEKEND_RESTRICTED, SKIP_OVERNIGHT_RESTRICTED, SKIP_MISSION_MET.
- **Added:** 2026-10-26 7968bc403a LTR-ALL-ACTIONS part 2; prop restrictions 2026-05-03 393d0fec6c
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-26 (mandates.yaml:1300 via lane relay) 'every trade action ... as long as they have reasoning and confidence attached' plus the guardrail clause that a widened stop 'must pass the same risk check a fresh entry would' is the lane's reading; operator's own sentence for the second half: not found.
- **Hits, last 14 days:** Window: no widen/add rows in the 56 in-trade rows, so 0 hits measured in reviews.jsonl.
- **Cost of removing it:** Prevents a widen from being an entry that bypasses caps.
- **Recommendation: KEEP.** Applies only to risk-adding actions and mirrors the entry path.
- **Question:** Keep this gate? widen_sl / add / size-up must pass the account's own fresh-entry check (mode, daily-DD switch block on new risk, gross exposure cap, and the size a fresh entry would get); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-MANDATE-ID-AND-APPLY-MODE` (RM)

- **Where:** `scripts/ops/live_review_apply.py:1195` · also `config/live_trade_review.yaml:196-205`
- **Blocks:** An apply is refused unless the intent names MD-TRADE-DESK (trade actions) or a tighten-granted id, the mandate is in mandates.yaml, and config/live_trade_review.yaml apply_mode is apply for the account (off/recommend only record). A directed record replaces the mandate with an operator quote.
- **Added:** 2026-10-26 4299cd338b grant MD-LIVE-TIGHTEN-SL + apply_mode: apply (#20199)
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-26 operator popups relayed in mandates.yaml:1235 ('as long as they have reasoning and confidence attached'); apply_mode 'ONLY A COMMIT CHANGES THIS ... the operator's act (Tier 3)' (live_trade_review.yaml:194).
- **Hits, last 14 days:** apply_mode is apply globally with accounts: {} (no per-account off) at HEAD; no refusals attributable. Window not measured.
- **Cost of removing it:** Prevents unauthorized order paths; mandate is the authorization record.
- **Recommendation: KEEP.** Authorized structure; but it is the layer that makes every advice-only class need a separate grant.
- **Question:** Keep this gate? An apply is refused unless the intent names MD-TRADE-DESK (trade actions) or a tighten-granted id, the mandate is in mandates.yaml, and config/live_trade_review.yaml apply_mode is *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-MANDATE-PRECONDITION` (RM)

- **Where:** `src/runtime/live_review_intent.py:449` · also `scripts/ops/live_review_apply.py:1244-1252`, `config/mandates.yaml:1307`
- **Blocks:** Before any execute: mechanics_verdict must be match, a non-empty reason, basis judgement with confidence in [0,1] or table with EV, and the action's own target; else mandate_precondition:<clause> refused on every account. A tighten under table basis also needs EV >= -0.25R and worst-case improved.
- **Added:** 2026-10-26 7968bc403a LTR-ALL-ACTIONS part 2; tighten clause 2026-10-25
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-26 'we also need to expand the desks mandate so include all trade actions, as long as they have reasoning and confidence attached' (mandates.yaml:1235 source, row LTR-ALL-ACTIONS); mechanics=match clause: no quote found. 2026-10-26 operator dropped the n>=20 clause (LTR-JUDGEMENT-APPLY).
- **Hits, last 14 days:** Window: 48 flag_mechanics rows in reviews.jsonl 2026-10-29..11-12 (population 524); mechanics mismatch refusal count for in-trade rows not separable.
- **Cost of removing it:** A mismatch means journal and venue disagree; acting on it could close the wrong leg.
- **Recommendation: KEEP.** Reasoning+confidence is operator-authorized; mechanics=match is a data-integrity check, but a mismatch should not stop a DE-RISKING close.
- **Question:** Keep this gate? Before any execute: mechanics_verdict must be match, a non-empty reason, basis judgement with confidence in [0,1] or table with EV, and the action's own target; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-OPERATOR-TAP-FALLBACK` (RM) · trigger case

- **Where:** `src/runtime/trade_approvals.py:102` · also `src/runtime/trade_approvals.py:52`, `src/runtime/trade_approvals.py:49`
- **Blocks:** When a recommendation is advice-only or operator_ask, the only way to execute it is the operator tapping Approve in Telegram within 15 min; the button exists only for mechanics match/could_not_look and for actions in ACTION_MAP (no change_size, add_entry), with level/size_fraction present.
- **Added:** 2026-11-12 b861f682da trade approvals (#25039)
- **Operator authorization (VERBATIM):** VERBATIM 2026-11-12 ~00:00Z 'if it needs me, then it needs to ping me so that I can immediately do that, right? ... a button that I press to accept a recommendation, and that directly executes that action.' src/runtime/trade_approvals.py:3-6, row TRADE-ACTION-DIRECT-PATH. File states 'GATES: none added'; the 15-min expiry and chat check are the unquoted parts.
- **Hits, last 14 days:** 2026-10-29..2026-11-12: 2 rows with route=operator_ask carried an in-trade action (reviews.jsonl); how many buttons were sent or tapped is not measured: runtime_logs/trade_approvals/journal.jsonl is on the VM. Operator-ask close LR-20261111T2235Z-pkg-6df5f9dfb83e47b8 covered breakout_2.
- **Cost of removing it:** The expiry stops a stale button executing a close at a changed price (comment cites ETH/SOL stops that hit 22.5/27 min after an advice_only row).
- **Recommendation: MAKE-REPORT-ONLY.** Keep the button; the 15-min expiry and 'mechanics must be match/could_not_look' should degrade to a warning on the button, not remove it, so a late tap still works.
- **Question:** Keep this gate? When a recommendation is advice-only or operator_ask, the only way to execute it is the operator tapping Approve in Telegram within 15 min; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-KILL-SWITCH-OFF` (RM)

- **Where:** `src/prop/phone_executor.py:322` · also `src/prop/phone_executor.py:179-194`, `src/prop/phone_cancel.py:643`
- **Blocks:** PROP_PHONE_MODE_<ACCOUNT>=off makes claim_next, claim_close, pending_count return nothing, so no entry, amend, cancel or close is served; any unparseable value or 'dry' makes every submit dry (fail closed).
- **Added:** 2026-10-05 bf6e28cea6 phone executor phase 1b (#16638)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: design doc docs/integrations/breakout-phone-executor-DESIGN.md calls it the executor kill switch; no verbatim quote found. Sits close to the 2026-10-09 'There is no halting' rule (an off switch that also stops CLOSES).
- **Hits, last 14 days:** Current value not measured: env on VM (default live).
- **Cost of removing it:** Off stops a runaway executor clicking; but it also stops closes and stop amends, leaving positions unmanaged.
- **Recommendation: MAKE-REPORT-ONLY.** Let 'off' stop ENTRIES only; closes and protective amends should stay served.
- **Question:** Keep this gate? PROP_PHONE_MODE_<ACCOUNT>=off makes claim_next, claim_close, pending_count return nothing, so no entry, amend, cancel or close is served; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-RECONCILE-MISS-READS` (RM)

- **Where:** `src/prop/phone_reconcile.py:61` · also `src/prop/phone_reconcile.py:357`
- **Blocks:** The journal marks a phone prop position closed only after it is absent from 2 clean Positions reads at least 60 s apart; mode report_only writes nothing; unclean read changes nothing.
- **Added:** 2026-10-12 d337422dd4 PROP-TRACKING (#17745)
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-15 'Yes' to option (ii) of PI-20261015-JWMGXOTH-0004 for reconcile: write (config/prop_platforms.yaml:332-338); the 2-read rule: no quote.
- **Hits, last 14 days:** breakout_2 declares reconcile: write; counts not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** A single glitched read must not close a live row (comment).
- **Recommendation: KEEP.** Journal accuracy, delays only bookkeeping not the venue close.
- **Question:** Keep this gate? The journal marks a phone prop position closed only after it is absent from 2 clean Positions reads at least 60 s apart; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-SHEET-EDIT-GATE` (RM)

- **Where:** `src/prop/phone_trail.py:414` · also `src/prop/phone_drill.py:147`, `tools/phone-executor/app/src/main/java/com/metis/phoneexec/MainActivity.kt:1666`
- **Blocks:** No stop amend is emitted to a phone account until phone_accounts.<acct>.sheet_edit is pinned true or 3 consecutive rehearsal drills passed; the app also refuses the pencil click when the gate is false.
- **Added:** 2026-10-18 c5c58e0cf2 (exec.js 2026-10-18.4) / row PHONE-EXEC-OBSERVABLE-1018 PRs 19010,19029,19072
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'operator decision 2026-10-18' in the row note and title; no verbatim quote (checklist/PHONE-EXEC-OBSERVABLE-1018.json). Observed armed 2026-10-18 20:53:59Z.
- **Hits, last 14 days:** breakout_2 gate state now not measured: drill history is server state on the VM. config/prop_platforms.yaml has no sheet_edit pin for breakout_2 (grep returns no sheet_edit key), so it relies on drills >= 3.
- **Cost of removing it:** Before the gate the app refused every amend and each refusal burned the ticket's backoff (measured 2026-10-18).
- **Recommendation: MAKE-REPORT-ONLY.** Emit the amend regardless and report the drill state; a gate that blocks a protective stop move on a losing position is the wrong default.
- **Question:** Keep this gate? No stop amend is emitted to a phone account until phone_accounts.<acct>.sheet_edit is pinned true or 3 consecutive rehearsal drills passed; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PHONE-TRAIL-NEVER-CLOSES` (RM) · trigger case

- **Where:** `src/prop/phone_trail.py:540` · also `src/prop/phone_trail.py:520-545`, `src/prop/phone_trail.py:483-488`
- **Blocks:** The phone trail only TIGHTENS the stop; when the strategy's harness has exited (trail crossed) the stop goes to price+buffer 'Tighten-only; no close'. A declared close lever (stale_exit_bars, giveback_*) that WOULD exit now only raises one alert 'the phone trail does NOT apply it'. Nothing in the trail issues request_close, so a losing prop position is exited only by a stop fill or a human.
- **Added:** 2026-10-15 9f401d81cf prop trail: a crossed trail EXITS (stop to price +/- buffer, tighten-only) (PI-20261015-JWMGXOTH-0002)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: operator 2026-10-01 popup 'Build the trail instead' (docs/claude/work/checklist/PROP-TRAIL.json) authorizes building the trail; the manager's note says 'tighten-only'; no verbatim quote for 'never close'. PHONE-AMEND-REFUSED-1025 note says 'no close control on the phone path'.
- **Hits, last 14 days:** Evidence in repo: breakout_2 ETH short left open after strategy exit (row PHONE-AMEND-REFUSED-1025, 2026-10-25, six refusals). Window count not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** A resting-SL amend cannot reproduce a bar-close exit; the author chose alert over approximating. Cost of removal: closing via the phone is the riskiest click path (reduce/close unmeasured).
- **Recommendation: REMOVE.** The trail already knows when the strategy has exited; it should emit request_close (the existing server-issued close channel) instead of only alerting.
- **Question:** Keep this gate? The phone trail only TIGHTENS the stop; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-DD-CUSHION-LEVERAGE` (RM)

- **Where:** `src/prop/prop_amend_gate.py:78` · also `src/units/accounts/prop_risk.py:340-370`, `src/prop/prop_risk_gate.py`
- **Blocks:** On a prop account an action that ADDS risk (widen_sl, add_entry, change_size>1) must fit the firm's static-DD/daily-loss cushion (exceeds -> refuse; stale status -> could_not_look) and the firm's leverage cap. Actions that reduce risk (tighten, close, reduce, move_tp) are never refused for the cushion.
- **Added:** 2026-10-27 ee0d2893a8 DESK-2-RISK-GATE (#20460)
- **Operator authorization (VERBATIM):** VERBATIM 'in general, every trade always must have BOTH brackets...' is a different gate; for the cushion: mandates.yaml MD-TRADE-DESK never: 'bypass an account's per-trade risk limit / sizing cap / exposure cap / daily-DD switch' (mandates.yaml:1313) from lane transcription of the 2026-10-26 popup; operator's own words on the cushion not found. Operator 2026-10-09 daily DD switch 'keep open, block new' (CLAUDE.md).
- **Hits, last 14 days:** Window: 0 prop widen/add rows recommended (56 in-trade rows, none widen/add); the gate is also unreachable today because prop_vm and phone have no add executor.
- **Cost of removing it:** A widened stop on a prop account can breach the firm's drawdown and void the account (prop survival tests).
- **Recommendation: KEEP.** It only binds actions that add risk, protects a hard external limit, and never blocks a reduce.
- **Question:** Keep this gate? On a prop account an action that ADDS risk (widen_sl, add_entry, change_size>1) must fit the firm's static-DD/daily-loss cushion (exceeds -> refuse; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-ROLLOUT-STEP-CAP` (RM)

- **Where:** `src/prop/platform/dxtrade.py:5209` · also `src/prop/prop_trail.py:431-450`, `src/prop/platform/dxtrade.py:5212-5245`, `src/prop/platform/base.py:144`
- **Blocks:** Each armed VM stop amend moves at most 25% of the stop's distance from the venue price (ModifyRollout / rollout_tighten_mismatch), SL-only, tighten-only, must be re-read; browser dxtrade adapter cannot move a TP (TP_AMEND_SUPPORTED false); venue quote buffer (QUOTE_BUFFER_ATR 0.1) refuses a stop too near price.
- **Added:** 2026-10-03 0b0ef36e91 prop: modify rollout guard (#15693)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'manager 2026-10-02 23:30Z, DIALOG-MEASURE #15693/#15705' (prop_trail.py docstring); the latch was retired on the operator's 2026-10-09 'There is no halting.' The step cap stayed.
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Bounded steps limit a bad modify to 25% of the stop distance during early rollout; a wrong price on a live prop account is unrecoverable.
- **Recommendation: OPERATOR-PREFERENCE.** A pure rollout-caution cap by the manager; a stale rollout limit that slows tightening toward a stop on a losing leg is the operator's call to keep or lift.
- **Question:** Keep this gate? Each armed VM stop amend moves at most 25% of the stop's distance from the venue price (ModifyRollout / rollout_tighten_mismatch), SL-only, tighten-only, must be re-read; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-ROSTER-SURVIVAL-GATE` (RM)

- **Where:** `scripts/ci/check_prop_roster_gate.py` · also `comms/prop_survival/README.md`
- **Blocks:** CI refuses a PR that adds a leg to a prop roster without comms/prop_survival/<leg>.json passing the EV/survival rule (V3 edge clause). Entry/roster side only; it does not stop closing or amending an open position.
- **Added:** 2026-10-15 49fa65e4b2 PROP-GATE-PARITY (#18394)
- **Operator authorization (VERBATIM):** VERBATIM 2026-10-15 operator rule 'prop clears everything real money clears, PLUS this' (comms/prop_survival/README.md:5; CLAUDE.md 'Prop legs clear a SUPERSET').
- **Hits, last 14 days:** Not an exit gate; 2 records exist (ml_entry, mlv_movingtp) plus 4 grandfathered legs; refusal counts not measured.
- **Cost of removing it:** Prevents unproven legs on funded accounts.
- **Recommendation: KEEP.** Authorized by the operator's 2026-10-15 rule and outside the exit path.
- **Question:** Keep this gate? CI refuses a PR that adds a leg to a prop roster without comms/prop_survival/<leg>.json passing the EV/survival rule (V3 edge clause). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-SILENCE-ALERTS` (RM)

- **Where:** `scripts/ops/prop_silence.py` · also `scripts/ops/prop_trail_watch.py:1`
- **Blocks:** Report-only probes (ok/breached/unknown) for prop silence and trail pause (prop_trail_watch.py); they ping, never block or close.
- **Added:** 2026-10-06..09 PROP-SILENCE-ALERTS / TRAIL-PAUSE-PULSE (PI-20261006-KX6ZKFNA-0003)
- **Operator authorization (VERBATIM):** VERBATIM 2026-11-06 'Yes, non-blocking OK' for non-blocking report detectors (brief); not a gate.
- **Hits, last 14 days:** not measured: alert deliveries are on Telegram/VM.
- **Cost of removing it:** none; observation only
- **Recommendation: KEEP.** Non-blocking detector, covered by the 2026-11-06 approval.
- **Question:** Keep this gate? Report-only probes (ok/breached/unknown) for prop silence and trail pause (prop_trail_watch.py); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-VM-CLOSE-POSITION-ARMING` (RM)

- **Where:** `src/prop/prop_executor.py:1902` · also `scripts/prop/prop_executor_tick.py:195`, `scripts/prop/prop_executor_tick.py:814`
- **Blocks:** The VM prop watched close refuses unless the symbol is in enabled_venue_symbols, exactly ONE position matches, side/size parse, close confirmed flat with no orphan order; live also requires PROP_EXECUTOR_MODE=live, else not_armed. Reachable only via the Tier-2 breakout-login-check close-position system-action, never by the trail or review.
- **Added:** 2026-09-29 f7e9084d98 PROP-EXEC watched close
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'manager 2026-09-29' (docstring); 'close_position_* ... closing a position is never deferred' (prop_executor_tick.py:97).
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** Exactly-one-position rule prevents closing the wrong row.
- **Recommendation: KEEP.** Correctness checks; the gap is that nothing calls it for strategy exits or reviews.
- **Question:** Keep this gate? The VM prop watched close refuses unless the symbol is in enabled_venue_symbols, exactly ONE position matches, side/size parse, close confirmed flat with no orphan order; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-PROP-VM-TRAIL-NEVER-CLOSES` (RM) · trigger case

- **Where:** `src/prop/prop_trail.py:359` · also `src/prop/prop_trail.py:25`, `src/prop/prop_trail.py:56-62`, `src/prop/prop_trail.py:604-612`, `src/prop/prop_trail.py:361`
- **Blocks:** VM prop trail (tradeify_1, velotrade_1, breakout_1): stop never loosened, never removed, 'no close control is clicked'; trail-crossed becomes a stop at price+buffer; close levers (stale_exit_bars, giveback) raise ONE alert and do nothing; legs with trail_vol_*/be_floor_r are skipped.
- **Added:** 2026-10-03 49753acc69 PROP-TRAIL (#15316); trail-crossed 2026-10-15 9f401d81cf
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 2026-10-01 popup 'Build the trail instead' (PROP-TRAIL.json) + manager note 'tighten-only'. The close-lever alert text 'operator decides' is the author's.
- **Hits, last 14 days:** not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo (alerts via Telegram, not in repo)
- **Cost of removing it:** Same as the phone trail; run_close_position exists on this path (prop_executor.py:1902) so a close is mechanically available.
- **Recommendation: REMOVE.** Same as phone: when the harness exit fires, close through the existing watched close instead of alerting.
- **Question:** Keep this gate? VM prop trail (tradeify_1, velotrade_1, breakout_1): stop never loosened, never removed, 'no close control is clicked'; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-SHADOW-DRY-REFUSE-CLOSE` (RM)

- **Where:** `src/runtime/live_review_intent.py:377` · also `src/runtime/live_review_intent.py:295-297`, `src/runtime/live_review_intent.py:379`
- **Blocks:** decide_action refuses ANY action, including close/reduce of an already open position, when the leg's strategy is execution: shadow (R_SHADOW) or the account mode is dry_run (R_DRY); same in decide_amend line 295/297. breakout_1 and ib_live are dry_run.
- **Added:** 2026-10-25 81a0b83602 LTR-6R (#20139)
- **Operator authorization (VERBATIM):** VERBATIM: CLAUDE.md 'The two execution gates' (operator rule that shadow never sends an order). Applying it to closing an existing position is not quoted. Search: mandates.yaml never lists.
- **Hits, last 14 days:** Window: reasons not recorded in reviews.jsonl (account_reads.reason null for all 650+ reads); not measured: not measured: runtime_logs/live_review/applied.jsonl, prop_tickets meta and phone logs live on the VM, not in the repo
- **Cost of removing it:** If a strategy is flipped to shadow while holding a live position, the position can no longer be reduced by the review.
- **Recommendation: MAKE-REPORT-ONLY.** A shadow/dry flag should stop new orders, not the closing of an existing real position.
- **Question:** Keep this gate? decide_action refuses ANY action, including close/reduce of an already open position, when the leg's strategy is execution: shadow (R_SHADOW) or the account mode is dry_run (R_DRY) *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-CLOSE-WEDGE-STANDING`

- **Where:** `src/runtime/close_wedge_standing.py` · also `config/venue_wedged_orders.yaml`
- **Blocks:** Downgrades the PAGE (not the close) for an Alpaca close failure proven unclearable (share_hold broker_cancel_wedged) to the daily digest; closes keep retrying. Also config/venue_wedged_orders.yaml hides wedged orders from open-order reads only when the symbol is flat.
- **Added:** 2026-09-02 (operator decision, per module docstring)
- **Operator authorization (VERBATIM):** VERBATIM-adjacent: 'Operator decision 2026-09-02: downgrade that one class to the daily digest' (close_wedge_standing.py:20) and OPERATOR-DECISIONS-20261028 item 4.
- **Hits, last 14 days:** alpaca_paper GLD only; count not measured.
- **Cost of removing it:** Silence on a provably unclearable wedge; evidence-keyed, not repetition-keyed.
- **Recommendation: KEEP.** Authorized and affects alerts only, not any action.
- **Question:** Keep this gate? Downgrades the PAGE (not the close) for an Alpaca close failure proven unclearable (share_hold broker_cancel_wedged) to the daily digest; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AM-DESK-LEG-NEVER`

- **Where:** `scripts/ops/live_review_apply.py:761` · also `scripts/ops/live_review_apply.py:98`
- **Blocks:** widen_sl and size adds on a claude_desk trade are refused desk_leg_never:<action> before any read.
- **Added:** 2026-10-27 c7dd8c72cd DESK-3-EXECUTORS (#20487)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'design § 2.4: a wider stop and a size change are in no desk enum' (trading-desk design); no verbatim quote found.
- **Hits, last 14 days:** Desk leg trades only demo accounts (mandates.yaml entry_generation demo_accounts); count not measured.
- **Cost of removing it:** none found
- **Recommendation: REMOVE.** Unquoted never-list on a demo-only leg; keep only if the operator wants it.
- **Question:** Keep this gate? widen_sl and size adds on a claude_desk trade are refused desk_leg_never:<action> before any read. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### VM and services (11)

#### `SYSTEM-ACTION-ACTOR-AND-LABEL-GUARD` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/system-actions.yml:369-373 (job `if`: repo owner or github-actions[bot] opened an issue carrying label `system-action`)` · also `.github/workflows/system-actions.yml:324-328 (same condition on the route job)`
- **Blocks:** Issue-driven system actions only run when the issue author is the repo owner or automation AND it has the `system-action` label and is `opened` (not `labeled`); anyone else's issue is ignored.
- **Added:** 2026-06-28 3d7cdda40e security: actor-guard issue-triggered workflows + intrusion-surface audit (#4965)
- **Operator authorization (NONE):** NONE FOUND as an operator quote; justification cited is docs/security/intrusion-surface-audit-2026-06-28.md (session-authored security audit)
- **Hits, last 14 days:** not measured: ignored issues leave no trace
- **Cost of removing it:** A triager or external user could be induced to apply the label and make the live VM run an allowlisted action (the 2026-06-03 #2688 probe cited at system-actions.yml:366).
- **Recommendation: KEEP.** Authentication of who may mutate the live VM; removal is a security hole, not a friction cut.
- **Question:** No operator authorization found. Keep this gate? Issue-driven system actions only run when the issue author is the repo owner or automation AND it has the `system-action` label and is `opened` (not `labeled`); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `SYSTEM-ACTION-CONCURRENCY-LANES` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/system_action_route.py:36 (READ_ONLY allowlist; concurrency_group)` · also `scripts/ops/system_action_cancel_guard.py (comments 'CANCELLED, NOT RUN' + one Telegram alert; never re-queues)`, `.github/workflows/system-actions-cancel-guard.yml`, `.github/workflows/system-actions.yml:296-318 (one shared mutating lane, cancel-in-progress false)`
- **Blocks:** All non-read-only system-actions serialize in ONE group so two VM mutations never overlap; GitHub keeps only one pending run in that group, so a newer request silently cancels an older pending one (the guard reports but never re-queues).
- **Added:** 2026-10-04 1bbb0569c9 ci(system-actions): no queued request is lost silently (OA-17) [route.py READ_ONLY and cancel_guard]
- **Operator authorization (NONE):** NONE FOUND (session-authored after losing #16251 and #16263; manager review of #16289 chose never to re-queue)
- **Hits, last 14 days:** not measured: cancelled runs/issue comments not in repo
- **Cost of removing it:** Two concurrent VM mutations (e.g. set-env and restart) could race; the measured cost of the present design is that two de-risk steps (#16251, #16263) were dropped silently on 2026-10-04.
- **Recommendation: OPERATOR-PREFERENCE.** Serialization prevents VM-state races but its one-pending limit drops requests; whether to queue them instead is a design call.
- **Question:** No operator authorization found. Keep this gate? All non-read-only system-actions serialize in ONE group so two VM mutations never overlap; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `DEPLOY-HOLDS-AND-DEFERRALS` (RM)

- **Where:** `scripts/deploy_pull_restart.sh:591-596 (defer service restart while a claude-vm-runner@ unit is active)` · also `scripts/deploy_pull_restart.sh:860-880 (operator stop marker holds the trader down; fresh marker on an active trader = skip restart)`, `scripts/deploy_pull_restart.sh:214-232 (gateway VM: refresh units only, no pip, no trader restart)`, `scripts/deploy_pull_restart.sh:84-85 (DEFAULT_SKIP unit list: ict-git-sync, prop-executor, prop-feed, ops-runner, etc. never restarted by deploy)`, `scripts/deploy_pull_restart.sh:68-72 (exit 1 when systemctl cannot be invoked)`
- **Blocks:** A deploy is postponed to the next 5-min tick while an in-flight /vm session runs, never starts a trader the operator stopped via stop-bot-service, never restarts the listed units, and does a reduced deploy on the gateway VM.
- **Added:** stop-marker 2026-09-27 e3af98f9b6 fix(ops): git-sync never starts an operator-stopped trader; claude-vm-runner deferral 2026-04-30 cb4029d76f deploy: only restart services when HEAD advanced (#188)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'the ONLY hold is an explicit operator signal: TRADER_STOP_MARKER ... written by stop-bot-service' (scripts/deploy_pull_restart.sh:744-747); the operator stop itself is the operator's act. Runner-deferral and DEFAULT_SKIP have no operator quote.
- **Hits, last 14 days:** not measured: deferral/hold lines are in the VM ict-git-sync journal
- **Cost of removing it:** Stop marker: a revive would undo an operator's explicit stop-bot-service (the race noted at :870). Runner deferral: killing an in-flight /vm invocation.
- **Recommendation: KEEP.** Stop-marker hold only honours an explicit operator stop; the other deferrals protect running work and delay by one tick.
- **Question:** Keep this gate? A deploy is postponed to the next 5-min tick while an in-flight /vm session runs, never starts a trader the operator stopped via stop-bot-service, never restarts the listed units, *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `DEPLOY-NON-RUNTIME-RESTART-SKIP` (RM)

- **Where:** `scripts/deploy_pull_restart.sh:487-505 (skip dependency install, unit refresh and service restart when only safe-set paths changed)` · also `scripts/deploy_pull_restart.sh:336-347 (nothing to deploy when running processes already at HEAD)`, `scripts/deploy_pull_restart.sh:493 (in-process scripts/research modules added back)`
- **Blocks:** ict-git-sync pulls code but restarts NO services when every changed path is in the safe set (docs/, tests/, .github/, research/, scripts/research\|ci, listed comms/ trees, deploy/trainer ...); runtime code only goes live on the next runtime commit.
- **Added:** 2026-06-01 4a8594d7cf fix(deploy) skip trader restart for docs-only commits (#2595) [git log -S'BL-20260529-002' scripts/deploy_pull_restart.sh]; only-restart-when-HEAD-advanced 2026-04-30 cb4029d76f (#188)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: BL-20260529-002 and RESTART-SAFE PI-20261003-OJTPWGCC-0001 comments (scripts/deploy_pull_restart.sh:351,374). It narrows restarts (never blocks a deploy of runtime code); no operator verbatim found for the safe-set itself. Fail-safe: any unreadable/unknown path restarts.
- **Hits, last 14 days:** not measured: ict-git-sync journal is on the VM; the row TRADER-RESTART-GATE measured 879 merges 2026-10-08..10-15 (711 non-runtime) as a replay, not a 14d count
- **Cost of removing it:** Every docs/CI merge would restart the live trader (21 restarts on 11-04 after data-only merges per deploy_pull_restart.sh:407), each landing inside an open-position window.
- **Recommendation: KEEP.** It REDUCES interruptions to the live trader and is fail-safe toward restart.
- **Question:** Keep this gate? ict-git-sync pulls code but restarts NO services when every changed path is in the safe set (docs/, tests/, .github/, research/, scripts/research\|ci, listed comms/ trees, deploy/tr *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `SYSTEM-ACTION-ALLOWLIST-AND-TIERS` (RM)

- **Where:** `.github/workflows/system-actions.yml:927-946 (Validate action and tier policy: tier-1 list, tier-2 list, unknown action exit 2)` · also `.github/workflows/system-actions.yml:937 (Tier-2 requires a non-empty `reason`)`, `.github/workflows/system-actions.yml:20-41 (header: fixed allowlist, one wrapper per action)`
- **Blocks:** Any action not on a hard-coded allowlist is refused (exit 2); every Tier-2 action (restarts, deploy, set-env, set-account-mode, flatten-*, amend-*, backfills ...) refuses to run without a non-empty reason. The 'operator OK in chat' for Tier-2 is a doc rule, not enforced in code.
- **Added:** 2026-05-24 5ff8c3e396 Phase 2a rename operator-actions -> system-actions (#1922) [git log -S"requires a non-empty 'reason'"; earliest hit is a rename, rule predates under the old name]
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY / DOC RULE: CLAUDE.md Permission tiers table ('Tier 2 ... get one operator OK in chat') and docs/CLAUDE-RULES-CANONICAL.md Permission Tiers; the `reason` requirement is session-authored for the audit trail (system-actions.yml:25-28).
- **Hits, last 14 days:** not measured: workflow run logs not in repo; no ledger of refused actions found
- **Cost of removing it:** Allowlist is the safety boundary for shelling into the live VM from a GitHub issue/label (security audit 2026-06-28 cited at system-actions.yml:364); a reason-less run would just lose the audit text.
- **Recommendation: OPERATOR-PREFERENCE.** The allowlist is a security boundary (keep); the mandatory `reason` is a small friction the operator could drop since reasons are free text.
- **Question:** Keep this gate? Any action not on a hard-coded allowlist is refused (exit 2); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `SYSTEM-ACTION-PARAM-VALIDATION-AND-DRY-DEFAULT` (RM)

- **Where:** `.github/workflows/system-actions.yml:946-1300 (per-action required params, charset checks, apply true/false, confirm_account echo)` · also `.github/workflows/system-actions.yml:1254,1293,2652 (switch-bybit-position-mode / set-bybit-collateral-switch / velotrade-api-roundtrip need confirm_account)`, `.github/workflows/system-actions.yml:1586 (breakout-login-check apply must be a subset of a fixed verb list)`, `scripts/ops/unset_env.sh:72,95 (RETIRABLE_KEYS allowlist: unset-env only for ARBITRATION_FANOUT_*)`, `scripts/ops/flatten_*_position.py, amend_*.py, live_review_apply.py (dry-run unless apply:true; venue-specific refusals)`
- **Blocks:** Flatten/amend/cancel/backfill wrappers default to dry-run unless apply:true; some require confirm_account to echo the target; params with bad charset or missing fields are refused; unset-env only works for two retirable keys.
- **Added:** per-action; unset-env allowlist 2026-09-25 468d6c23ef Add unset-env Tier-2 system-action (#12943); other validators not individually dated
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'apply gates dry-run-vs-execute' design in workflow comments (:1181,1300,2314); confirm_account echo is session-designed. unset-env allowlist: 'reviewed one-line edit, the same doctrine' (scripts/ops/unset_env.sh:36). No operator verbatim found.
- **Hits, last 14 days:** not measured: no refusal ledger; only visible in Actions logs
- **Cost of removing it:** Typos in a flatten/cancel on a live account (wrong account/symbol) with no dry-run preview; confirm_account echo prevents venue position-mode switch on the wrong account.
- **Recommendation: OPERATOR-PREFERENCE.** Dry-run-by-default and charset checks are safety (keep); confirm_account echoes and the verb-list allowlists are extra friction the operator may not want on his own actions.
- **Question:** Keep this gate? Flatten/amend/cancel/backfill wrappers default to dry-run unless apply:true; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `TRADER-RESTART-GATE` (RM)

- **Where:** `scripts/deploy_pull_restart.sh:540-566 (TRADER_GATE: skip trader restart unless a changed path is in the trader's static import closure)` · also `scripts/ops/trader_import_closure.py:378 (decide) / :545`, `scripts/deploy_pull_restart.sh:855-866 (restart-loop honours the gate only if the trader unit is active)`, `DEPLOY_FORCE_RESTART=1 bypass (:477,543)`
- **Blocks:** A runtime diff restarts every unit except ict-trader-live when none of the changed files is in src.main's import closure, no non-.py runtime path changed and no .py outside src/scripts changed.
- **Added:** 2026-10-15 1aade6c238 deploy: per-unit trader restart gate (TRADER-RESTART-GATE Phase 1) [git log -S'TRADER_GATE_NOTE']
- **Operator authorization (VERBATIM):** VERBATIM: operator popup ~2026-10-15T10:10Z "Build it (Recommended)" (docs/claude/work/checklist/TRADER-RESTART-GATE.json note), SPEC = Phase 1 exactly as in TELEGRAM-RESTART-MSG.
- **Hits, last 14 days:** not measured: gate lines are in the VM ict-git-sync journal ('Trader restart gate:'); row note says first gate run was NOT yet observed at last write
- **Cost of removing it:** Trader would restart on every runtime commit that does not touch its code (e.g. web-api only), interrupting real-money management; the gate's own fail-safe restarts when unsure, so removal only adds restarts.
- **Recommendation: KEEP.** Operator-approved and fail-safe toward restart; it narrows restarts, not trading.
- **Question:** Keep this gate? A runtime diff restarts every unit except ict-trader-live when none of the changed files is in src.main's import closure, no non-.py runtime path changed and no .py outside src/scr *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `ALERT-COOLDOWN` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/alert_cooldown.py:105 (cooldown_admits: one operator page per window per key; a strictly higher severity breaks it)` · also `src/runtime/pipeline.py:250,327`, `src/runtime/order_monitor.py`, `src/runtime/losing_streak_alert.py`, `src/runtime/starved_account_alert.py`
- **Blocks:** Repeat alerts for the same standing condition are suppressed for a cooldown window (an unreadable latch alerts rather than suppresses); it never blocks an order or action.
- **Added:** 2026-08-26 46d204afd8 IB protection + breaker, Alpaca capacity read ... (#10292) [git log -S'def cooldown_admits' src/runtime/alert_cooldown.py; may have been moved from order_monitor]
- **Operator authorization (NONE):** NONE FOUND as an operator quote (evidence-driven: target_naked alert was 202 of 376 rows = 53.7% of the operator ERROR+/CRITICAL feed, alert_cooldown.py:11-14)
- **Hits, last 14 days:** not measured: runtime_logs/*_alert_state.json latch files are on the VM, not in the repo
- **Cost of removing it:** Alert flood (53.7% of the feed in the measured incident) desensitizing the operator; no trade effect.
- **Recommendation: MAKE-REPORT-ONLY.** It only throttles notifications; keep it but it is an operator-taste call about page volume (severity-escalation already lets worsening through).
- **Question:** No operator authorization found. Keep this gate? Repeat alerts for the same standing condition are suppressed for a cooldown window (an unreadable latch alerts rather than suppresses); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `ICT-GIT-SYNC-CADENCE-AND-FETCH` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `deploy/ict-git-sync.timer (OnUnitActiveSec=5min, RandomizedDelaySec=30) -> scripts/deploy_pull_restart.sh` · also `scripts/deploy_pull_restart.sh:128-135 (stuck gc.log prune; bounded, never blocks the pull)`, `deploy/ict-git-sync.service (oneshot)`
- **Blocks:** Code reaches the VMs only on a 5-minute poll of origin/main; runtime changes wait for the next tick (deploys are otherwise automatic).
- **Added:** 2026-04-27 643a2b638f Add systemd timer for ict-git-sync.service
- **Operator authorization (NONE):** NONE FOUND (infrastructure cadence; CLAUDE.md states 'ict-git-sync pulls main every ~5 min' as fact; green Tier-1/2 deploys 'are automatic' per the 2026-10-29 rule)
- **Hits, last 14 days:** not measured: VM journal not in repo
- **Cost of removing it:** No gate in the blocking sense; shortening the interval only speeds deploys.
- **Recommendation: KEEP.** A polling interval is a latency, not a refusal; listed for completeness.
- **Question:** No operator authorization found. Keep this gate? Code reaches the VMs only on a 5-minute poll of origin/main; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `INSIGHTS-ENABLED-KILL-SWITCH` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/run_insights_cycle.sh:42 (INSIGHTS_ENABLED=0/false/no -> skip cycle)` · also `scripts/ops/run_insights_strategies_cycle.sh:40`, `deploy/ict-insights-generator.service:16 ('Killable: set INSIGHTS_ENABLED=0')`, `scripts/ops/disable_insights_generator.sh / enable_insights_generator.sh (tier-2 system-actions)`
- **Blocks:** An opt-out env flag (default ON) that makes the insights generator timer exit without work; the system-actions enable/disable-insights-generator actions toggle it.
- **Added:** 2026-05-26 2a2e01fb65 feat(insights): systemd timer + cycle wrapper + runbook (M13 S1 / PR D) (#2083)
- **Operator authorization (NONE):** NONE FOUND (default-on soft kill switch; does not violate 'never hide a capability behind a default-off flag')
- **Hits, last 14 days:** not measured: needs VM .env
- **Cost of removing it:** Operator loses the soft kill for a cost-bearing LLM generator ('monthly cost gate' referenced in the script header); no trade-path effect.
- **Recommendation: KEEP.** Default-on, operator-controlled off switch for a non-trade, cost-bearing timer.
- **Question:** No operator authorization found. Keep this gate? An opt-out env flag (default ON) that makes the insights generator timer exit without work; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `VESTIGIAL-ENABLED-FLAGS-AND-ENV-GATE-GUARDS`

- **Where:** `deploy/ict-trader-live.service:38 (Environment=MONITOR_RECONCILE_ENABLED=true; code comments at src/runtime/order_monitor.py:2661 say it runs unconditionally now)` · also `scripts/ops/enable_closed_flat_invariant.sh / disable_closed_flat_invariant.sh (flag retired per src/runtime/_closed_flat_wiring.py:19,138)`, `scripts/ops/get_env.py:262 and src NEWS_VETO_ENABLED (read by another agent's scope)`, `scripts/check_env_gate_in_diff.py:162 (CI refuses ADDED os.environ reads matching *_ENABLED/*_DRY_*/MONITOR_*/DISPATCH_* in src/runtime\|units\|web)`, `scripts/ci/check_no_action_rate_cap.py:175 (CI refuses any per-bar/per-window in-trade action cap)`
- **Blocks:** Two retired *_ENABLED flags linger (set but unread) and two CI guards refuse NEW env-flag gates and NEW in-trade action caps.
- **Added:** env-gate guard 2026-05-10 9e81fa0852 refactor(runtime): purge process-wide env-gates (#659); rate-cap guard 2026-10-29 64cccff639 REMOVE-PER-BAR-CAP
- **Operator authorization (VERBATIM):** VERBATIM (rate-cap guard): operator 2026-10-29 ~10:45Z "Why is there a cap for the reviewer? ... we need to make sure this isn't being implemented anywhere" (scripts/ci/check_no_action_rate_cap.py:4-7). Env-gate guard: operator directive 2026-05-03 BUG-039 'per-account RiskManager.dry_run is the only live/dry switch' (scripts/check_env_gate_in_diff.py header) -- paraphrase.
- **Hits, last 14 days:** not measured: CI-only; no flag blocks anything at runtime (both flags are ignored by code)
- **Cost of removing it:** These guards REMOVE gates; dropping them would let default-off flags (the MES-stranding pattern) back in.
- **Recommendation: KEEP.** They enforce the operator's anti-gate rules; the two vestigial flags are dead config worth deleting (no behaviour change).
- **Question:** Keep this gate? Two retired *_ENABLED flags linger (set but unread) and two CI guards refuse NEW env-flag gates and NEW in-trade action caps. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### Writers, research queue, soak/status (19)

#### `MANDATE-RESOLVER-CLAUSES` (RM)

- **Where:** `scripts/ops/mandate_resolver.py:930 (resolve) -> FIRE / REFUSE / NEEDS-DATA` · also `scripts/ops/mandate_resolver.py:1065-1069 (mechanics_proven skips the paper soak)`, `scripts/ops/mandate_resolver.py:305-610 (R-AFFORD: account must be able to size the leg)`, `scripts/ops/mandate_resolver.py (R-HOLDOUT, R-N, R-NOT-SOAKED, R-EXECUTION-SHADOW, R-RECORD-MISSING)`, `config/mandates.yaml:126-770 (granted mandates)`
- **Blocks:** Decides whether a ladder transition (promote S0->S1, S1->S2, demote) may fire WITHOUT asking the operator; any failed clause or missing evidence means it does not fire and a human is asked.
- **Added:** NEEDS_DATA 2026-09-29 0826c7748e (#14091); R-AFFORD 2026-09-30 43e844e3cd (#14543); R-HOLDOUT 2026-10-16 1a2633ef4a [HOLD]; resolver base not separately dated
- **Operator authorization (VERBATIM):** VERBATIM: operator grants in config/mandates.yaml ('granted_by: operator (Ben)', e.g. lines 139,163,189,280,330) and "either we have enough data to decide, or we don't and then getting that data becomes a task" (mandate_resolver.py:30-32, 2026-09-29); R-HOLDOUT 'operator decision 2026-10-16, "Require holdout"' (mandate_resolver.py:69); mechanics_proven 'Yes, merge it (Rec.)' (row PROMOTION-NO-SOAK).
- **Hits, last 14 days:** not measured: resolver verdicts live in comms/mandate_evidence/ but I did not enumerate them for the window
- **Cost of removing it:** The resolver is what makes automated promotion possible at all; removing REFUSE clauses would let a real-money promotion fire without an evidence record. It adds no gate on running trades.
- **Recommendation: KEEP.** Each clause maps to a recorded operator rule and the resolver only restricts auto-action, never manual operator decisions.
- **Question:** Keep this gate? Decides whether a ladder transition (promote S0->S1, S1->S2, demote) may fire WITHOUT asking the operator; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `ROSTER-PROMOTION-EVIDENCE-AND-PROP-GATES` (RM)

- **Where:** `scripts/ci/check_roster_promotion_evidence.py:909 (main) / run_guards.py:2185` · also `scripts/ci/check_prop_roster_gate.py:351 (prop leg = real-money bar PLUS prop survival)`, `run_guards.py:2257`, `scripts/ci/check_mandate_autoland.py (the one self-landing route for mandate-authorized roster edits; NOT wired in run_guards.py by that name)`
- **Blocks:** CI refuses a diff that puts a strategy leg on a real-money or prop roster without a committed evidence record (named harness, n, net of full cost stack, pre-registered rule, faithful fidelity) and, for prop, a survival record.
- **Added:** prop gate 2026-10-15 49fa65e4b2 PROP-GATE-PARITY (#18394); roster-promotion C5 2026-10-11 6b5731edce (earliest hit for 'five-clause' in that file; the base guard predates -- 2026-09-21 per its header, not git-verified)
- **Operator authorization (VERBATIM):** VERBATIM: C5 popup "Add it, re-measure the 3 now" 2026-10-11; prop gate chat "Yes, 1, 2 and 3a" 2026-10-15 with "if anything, the prop accounts should have a higher bar to clear because of the DD limits" (scripts/ci/check_roster_promotion_evidence.py:35-41; check_prop_roster_gate.py:3-6); five-clause bar 'DECIDED BY THE OPERATOR 2026-09-21' (no verbatim for C1-C4).
- **Hits, last 14 days:** not measured: CI results not in repo
- **Cost of removing it:** Real-money leg promoted on fee-only or unfaithful evidence (guard cites the roster growing 36->55 while memos said cut).
- **Recommendation: KEEP.** Operator-decided and recorded in CLAUDE.md as binding for real-money promotion.
- **Question:** Keep this gate? CI refuses a diff that puts a strategy leg on a real-money or prop roster without a committed evidence record (named harness, n, net of full cost stack, pre-registered rule, faithf *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `STRATEGY-STATUS-GUARD` (RM)

- **Where:** `scripts/ci/check_strategy_status.py:177 (main) / scripts/ops/strategy_status.py:68 (status_of) / scripts/ci/run_guards.py:2280` · also `scripts/ci/check_soak_registered.py (dead)`
- **Blocks:** CI refuses a PR that leaves a strategy leg on both general paper and a real-money+mirror roster at once (or violates the three-status derivation).
- **Added:** 2026-10-29 97dde7e5ba STRATEGY-STATUS-MODEL: three strategy statuses [Tier 3, operator-answered] (#21038)
- **Operator authorization (VERBATIM):** VERBATIM-LABELLED: operator 2026-10-28 decision "Adopt; build it this week" (scripts/ci/check_strategy_status.py:3-4; CLAUDE.md 'THREE STRATEGY STATUSES'); popup 2026-10-27 "Yes, that's the rule" for the demo-floor rule.
- **Hits, last 14 days:** not measured: CI results not in repo
- **Cost of removing it:** A leg could sit on both books, double-counting positions across paper and real money; guard exists because CI is asymmetric on roster edits (check_strategy_status.py:8-12).
- **Recommendation: KEEP.** Operator adopted the three-status rule that this guard mechanically enforces.
- **Question:** Keep this gate? CI refuses a PR that leaves a strategy leg on both general paper and a real-money+mirror roster at once (or violates the three-status derivation). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CHECKLIST-STORE-FILENAME-SAFETY` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/checklist_store.py:169 (id must be filename-safe [A-Za-z0-9._-])` · also `src/runtime/checklist_store.py:180 (row id must match its filename; read refuses a mismatched file)`, `src/runtime/checklist_store.py:338,352 (monolith writer refuses 'items' and duplicate ids)`
- **Blocks:** Refuses to write or read a checklist row whose id is path-shaped or disagrees with its filename.
- **Added:** 2026-10-08 253af2399a CHECKLIST (b1): path-aware loader in src/runtime (#17013) [git log -S'is not filename-safe']
- **Operator authorization (NONE):** NONE FOUND (security/integrity hygiene, not an operator-decided gate)
- **Hits, last 14 days:** not measured: no refusal ledger
- **Cost of removing it:** Path-traversal write (a row id like ../../x) from a script argument; self-test ck 'a path-shaped id is refused' scripts/ops/checklist.py:262.
- **Recommendation: KEEP.** Cheap path-traversal/data-integrity protection on a file writer, blocks nothing the operator wants done.
- **Question:** No operator authorization found. Keep this gate? Refuses to write or read a checklist row whose id is path-shaped or disagrees with its filename. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PIPELINE-APPEND-STALE-AND-IDENTITY` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/pipeline.py:638-690 (append: intent new/update, based_on, STALE SNAPSHOT, identity mismatch, routed_to-on-non-routed)` · also `scripts/ops/pipeline.py:918-951 (redate_problems: a later next-due needs a >=N-char redate.observation that differs from the last)`, `scripts/ops/pipeline.py:965-969 (redate refuses terminal item / date not after today)`
- **Blocks:** Refuses a second filing under an existing id, an update with no/stale based_on version, an update that is a different finding, routed_to on a non-routed state, and a bare re-date with no new observation.
- **Added:** 2026-10-08 2a70d36753 REGISTER-TOOLING: pipeline stale-snapshot guard, redate guard (#16973) [git log -S'STALE SNAPSHOT' and -S'def redate_problems']
- **Operator authorization (NONE):** NONE FOUND (session-authored concurrency + anti-rubber-stamp rules; cites incidents PI-20261004-4GA8WQPA-0002, PI-20260921-0002, ROUTE-20261012, not an operator quote)
- **Hits, last 14 days:** not measured: no refusal ledger
- **Cost of removing it:** Evidence in code comments: BACKLOG-BURNDOWN-2 took 358 due items to 19 by moving dates only and left 553 open (pipeline.py:921-924); stale read reverted a newer update (PI-20261004-4GA8WQPA-0002). The redate rule specifically blocks 'moving a date' unless an observation is typed.
- **Recommendation: OPERATOR-PREFERENCE.** Stale-snapshot/identity checks protect append-only data integrity (keep), but the redate-needs-observation refusal is friction the operator never authorized and could become a warning.
- **Question:** No operator authorization found. Keep this gate? Refuses a second filing under an existing id, an update with no/stale based_on version, an update that is a different finding, routed_to on a non-routed state, and a bare re-date w *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `WORK-STORE-VALIDATION` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `src/runtime/work_store.py:231-263 (kind/state/title/next_action/extra validation, clear-refusal, per-key patch refusal)` · also `src/runtime/work_store.py:67 (patch naming an unknown key refused)`, `src/runtime/work_store.py:380 (refused by a store constraint)`, `src/runtime/work_store.py:437`
- **Blocks:** work_store.db (the post-freeze canonical store for pipeline observations / checklist rows) refuses writes with an invalid kind/state/next_action, a missing title, a patch with a non-computed unknown key, or a clear of owner/due_by/roadmap.
- **Added:** 2026-11-05 bca28d33b0 WSD-S1-STORE-API: work_store.db ... [Tier 2, hold] [git log -S'WorkStoreValidationError' src/runtime/work_store.py]
- **Operator authorization (NONE):** NONE FOUND (mirrors checklist.py/pipeline.py validators; 'fill, never refuse' comments at work_store.py:23,270,293 show intent to narrow refusals)
- **Hits, last 14 days:** not measured: refusals return an HTTP/API error, not stored
- **Cost of removing it:** Invalid rows in the live API store would break renderers (the 2026-11-05 500 IntegrityError referenced at work_store.py:270). Bookkeeping only.
- **Recommendation: MAKE-REPORT-ONLY.** Duplicate of the CLI validators; schema constraints are fine but the vocabulary refusals should fill/normalize per the file's own 'fill, never refuse' stance.
- **Question:** No operator authorization found. Keep this gate? work_store.db (the post-freeze canonical store for pipeline observations / checklist rows) refuses writes with an invalid kind/state/next_action, a missing title, a patch with a no *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CHECKLIST-ROW-VOCAB-REFUSAL`

- **Where:** `scripts/ops/checklist.py:100 (_commit_row -> _vocab_problems at :70)` · also `src/runtime/checklist_store.py:140 (rank_problem)`, `scripts/ops/checklist.py:48-53 (_require_seeded: refuses writes until the per-row store is seeded)`
- **Blocks:** Refuses to write a checklist row whose `state` is missing, not in the file's declared `states`, disagrees with the legacy `status` field, or whose priority_rank is not a positive number/null.
- **Added:** 2026-10-08 9e49bf5208 CHECKLIST (d1): write CLI add\|set\|note\|archive-lane\|header (#17017) [git log -S'_vocab_problems' scripts/ops/checklist.py]
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'a bad row is refused at the keyboard instead of at CI' (scripts/ops/checklist.py:71-72); vocabulary guard MI-257 'checklist the operator reads may not carry two competing status fields' (scripts/ci/check_manager_checklist_vocabulary.py:1-3). No operator verbatim found.
- **Hits, last 14 days:** not measured: a refusal exits non-zero and writes nothing; no ledger of refused checklist writes in the repo
- **Cost of removing it:** Data-integrity only: an out-of-vocabulary state would render wrong on /api/bot/work/checklist (collapsed-state class). Evidence: self-test planted cases scripts/ops/checklist.py:285-308. No money path.
- **Recommendation: MAKE-REPORT-ONLY.** It is a self-service typo catch on a bookkeeping file; warn-and-write (or let the existing CI vocabulary check report) rather than refuse.
- **Question:** Keep this gate? Refuses to write a checklist row whose `state` is missing, not in the file's declared `states`, disagrees with the legacy `status` field, or whose priority_rank is not a positive n *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CHECKLIST-SET-REFUSES-CLEARING`

- **Where:** `scripts/ops/checklist.py:134-138 (op_set)` · also `src/runtime/work_store.py:255-259 (same refusal on the work-store path)`, `scripts/ops/checklist.py:135 (a row's id cannot change)`, `scripts/ops/checklist.py:121-122 (add needs --title)`, `scripts/ops/checklist.py:114 (add refuses duplicate id)`
- **Blocks:** `checklist.py set` refuses to blank an existing owner / due_by / roadmap (must re-date instead); also refuses id change, duplicate id, add without title.
- **Added:** 2026-11-02 9a0105aaaf checklist: process not gates -- defaults fill owner/due_by/roadmap (#22110) [git log -S'refuses to clear' scripts/ops/checklist.py; the clear-refusal arrived in the same commit as the fill-defaults]
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY of an operator-binding line: 'Process, not gates (operator, 2026-11-01, binding; lane CHECKLIST-OWNER-DUE). ... Only a DELIBERATE clearing errors' (docs/plans/manager-runbooks.md:83; code comment scripts/ops/checklist.py:118,134). The lane chose to ERROR on deliberate clearing; the verbatim operator words on that specific refusal were not found.
- **Hits, last 14 days:** not measured: refusals leave no record
- **Cost of removing it:** A session could silently blank due_by/owner, losing the manager's follow-up date; no evidence of an incident, the rule was designed alongside fill-defaults.
- **Recommendation: MAKE-REPORT-ONLY.** The operator's own stance for this file is 'process, not gates'; clearing could just be allowed and re-filled by fill_defaults.
- **Question:** Keep this gate? `checklist.py set` refuses to blank an existing owner / due_by / roadmap (must re-date instead); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `HEALTH-REVIEW-DRAIN-GATE`

- **Where:** `scripts/ops/pipeline.py:1106 (gate_set) / :1862 (--gate)` · also `scripts/ops/pipeline.py:1077-1090 (GATE_CLOSED_ROW_STATES, owner_of)`
- **Blocks:** Defines the set of due pipeline items (unrouted, owner-row-closed, high-severity) the weekly /health-review must triage before it counts as complete.
- **Added:** 2026-10-24 022ae05e5e health-review: narrow per-item drain gate (HEALTH-GATE-NARROW) (#19882) [git log -S'HEALTH-GATE-NARROW' scripts/ops/pipeline.py]; the pre-narrowing gate predates this and was not dated
- **Operator authorization (VERBATIM):** VERBATIM: operator popup answer 'Narrow the gate (Recommended)' 2026-10-24T14:45Z (docs/claude/work/checklist/HEALTH-GATE-NARROW.json note; code comment scripts/ops/pipeline.py:1077). It NARROWED an existing gate; the original per-item gate itself has no separate verbatim.
- **Hits, last 14 days:** MEASURED today on the current tree (not a 14d count): `python3 scripts/ops/pipeline.py --gate` -> gate 449 of 737 due (excluded 288); the row note recorded 306 of 604 on 2026-11-05
- **Cost of removing it:** No money path; the gate only decides whether a review's backlog_coverage is satisfied. Row note says 'a review cannot meet it' at 306, i.e. it is a gate that is currently unmeetable.
- **Recommendation: MAKE-REPORT-ONLY.** Authorized only as a narrowing; at 449 items it cannot be met, so report the number rather than hold the review on it.
- **Question:** Keep this gate? Defines the set of due pipeline items (unrouted, owner-row-closed, high-severity) the weekly /health-review must triage before it counts as complete. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `LANE-CEILINGS-REPORT-ONLY`

- **Where:** `scripts/ops/lane_reconcile.py:308-325 (over_ceiling) and :492 (exit code 1)` · also `scripts/ops/spend_meter.py:319,467,495 (LANES_MIN=1, LANES_MAX=5; 'a target, not a cap')`, `.claude/skills/manager/SKILL.md:257 ('Every lane has a dollar ceiling on its row')`, `scripts/ci/check_wip_ceiling.py:74 (CEILING=8 work objects; DEAD: removed from run_guards.py:348, docs/claude/work/objects/ no longer exists, script now errors)`
- **Blocks:** Lane $ ceilings are only REPORTED by lane_reconcile (over-ceiling lanes flagged, exit 1); spend_meter advice is explicitly not a cap. No code enforces a 2-build-lane cap (grep for build_lanes/max_lanes in scripts/src/config found none).
- **Added:** 2026-09-22 308b75b6c4 E20 part 2: the three cost leaks (#12742) [git log -S'over_ceiling' lane_reconcile.py]; wip-ceiling script 2026-09-01 31508d918b (#10657)
- **Operator authorization (VERBATIM):** VERBATIM-LABELLED: operator popup 2026-10-29 ~22:10Z approved 'lane $ ceilings + 2-build-lane cap' to stay (row NO-NEW-GATES-RULE). The 2-build-lane cap is a manager-skill/doc rule only; I found it in no code.
- **Hits, last 14 days:** not measured: lane_reconcile output is not committed
- **Cost of removing it:** Spend overrun: E20 measured a ~$1,142 day against ~$250 of ceilings (lane_reconcile.py:46) -- but that was with ceilings NOT read, i.e. the 'gate' is a human-read report.
- **Recommendation: KEEP.** Operator-approved to stay, and in code it is only a report so it blocks nothing.
- **Question:** Keep this gate? Lane $ ceilings are only REPORTED by lane_reconcile (over-ceiling lanes flagged, exit 1); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PIPELINE-VALIDATE-REFUSALS`

- **Where:** `scripts/ops/pipeline.py:295 (validate)` · also `scripts/ops/pipeline.py:314-327 (origin.ref/origin.rerun required)`, `scripts/ops/pipeline.py:329-352 (due_when kind / clears_when / soak subject / check_every_days)`, `scripts/ops/pipeline.py:371-390 (terminal_reason REQUIRED to close; forbidden while open)`, `scripts/ops/pipeline.py:388 (state=routed needs routed_to)`
- **Blocks:** `pipeline.py append` refuses any follow-through item missing due_when (or clears_when), origin.rerun, a valid next_action/state, a terminal_reason on done/killed, or routed_to on routed.
- **Added:** 2026-09-21 53436a1749 A7 part one, the close-out contract... (#12676) [git log -S'terminal_reason: REQUIRED' scripts/ops/pipeline.py]
- **Operator authorization (VERBATIM):** VERBATIM-ADJACENT: operator 2026-09-21 'there's too many things here that get just dropped halfway through ... actually creating infra that has a pipeline that pulls things through to the finish' (scripts/ops/pipeline.py:6-12, docs/plans/OPERATING-PLAN-2026-09-21.md 3b). The specific refusals are in CLAUDE.md ('Refused without due_when, origin.rerun and (to close) terminal_reason', checked-in operator-instruction file).
- **Hits, last 14 days:** not measured: a refusal prints 'pipeline: refused --' and writes nothing; no refusal ledger (PIPELINE store has 7326 files incl. accepted only)
- **Cost of removing it:** Items could be filed with no due condition (the measured 'filing was free, pick-up voluntary' failure). The refusal is the operator's stated acceptance criterion.
- **Recommendation: KEEP.** Directly implements the operator's 2026-09-21 ask and is recorded in CLAUDE.md; it gates only the writer's own bookkeeping.
- **Question:** Keep this gate? `pipeline.py append` refuses any follow-through item missing due_when (or clears_when), origin.rerun, a valid next_action/state, a terminal_reason on done/killed, or routed_to on r *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `QUEUE-REPLENISH-PREREG-VERIFY`

- **Where:** `scripts/research/queue_replenish.py:871 (verify) and :925-937 ('generated.params is not a point ... pre-registered, refused')` · also `scripts/research/queue_replenish.py:988 (a node not unlocked on the merge-base is refused)`, `.github/workflows/research-queue-replenish.yml:12 (merge-base verify gates self-landing)`
- **Blocks:** A generated research unit lands itself only if it re-renders byte-for-byte from a committed template point and an unlocked programme node; any hand edit or unregistered point is refused.
- **Added:** 2026-09-29 ecca21e0e1 research-queue: the queue refills, dispatches and grades itself without a session (HOLD) [git log -S'not pre-registered, refused']
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'E58 vouches pre-registered points, never whatever a branch says' (queue_replenish.py:1137); pre-registration is CLAUDE.md doctrine ('clearing a rule REGISTERED BEFORE THE RUN')
- **Hits, last 14 days:** not measured: workflow verify results not in repo
- **Cost of removing it:** Generated units could embed unregistered parameters, defeating the pre-registration property that promotion evidence relies on.
- **Recommendation: KEEP.** Mechanical enforcement of the standing 'registered before the run' rule; only affects auto-landing, a human can still land.
- **Question:** Keep this gate? A generated research unit lands itself only if it re-renders byte-for-byte from a committed template point and an unlocked programme node; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-DISPATCH-PER-TICK-CAPS`

- **Where:** `scripts/research/dispatch_queue.py:1826-1834 (research compute cap + --max-fires-per-workflow, default 1)` · also `scripts/research/dispatch_queue.py:1084-1180 (backpressure: in-flight cap, repo-queued cap, infra-yield)`, `scripts/research/dispatch_queue.py:1801 (per-run GPU dispatch cap, default 1)`, `scripts/research/research_compute.yaml:132-143 (max_total_inflight 8, max_repo_queued 10, starvation_hours 0.75, infra_yield_at 2)`, `scripts/research/dispatch_queue.py:1193 (STARVATION_HOURS lifts the cap for one fire/cycle)`
- **Blocks:** Each dispatcher cycle fires at most N units (in-flight cap 8, 1 per workflow file, 1 GPU burst per run) and defers everything while infra runs are queued or repo-queued runs exceed 10.
- **Added:** per-workflow cap 2026-09-29 c96649e3dc dispatch_queue: fire at most one unit per colliding workflow per cycle; max_total_inflight 2026-10-13 6c84f38bd5 RESEARCH-ROUTER (#17857); infra_yield_at 2026-11-03 cd9897eafc RESEARCH-FLOW (#22486)
- **Operator authorization (VERBATIM):** VERBATIM-LABELLED: operator popup 2026-10-29 ~22:10Z approved 'research dispatcher per-tick caps' to stay (checklist row NO-NEW-GATES-RULE note); plus 'OPERATOR 2026-11-03 D5-A' on the 8-run cap and 'operator 2026-10-15' on infra yield (scripts/research/research_compute.yaml:132,135) -- those two carry no verbatim text.
- **Hits, last 14 days:** not measured: 'deferred' outcomes are in Actions run logs, not the repo (utilization record is written to an artifact dir, dispatch_queue.py:1497)
- **Cost of removing it:** Runner pool starvation of infra workflows (CI, deploy) -- measured 2026-11-12: 8 research runs in flight blocked dispatch ~7h (dispatch_queue.py:1062-1067).
- **Recommendation: KEEP.** Explicitly operator-approved on 2026-10-29 to stay.
- **Question:** Keep this gate? Each dispatcher cycle fires at most N units (in-flight cap 8, 1 per workflow file, 1 GPU burst per run) and defers everything while infra runs are queued or repo-queued runs exceed *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-HOLDOUT-WINDOW-REFUSAL-AND-DEFLATED-BAR`

- **Where:** `scripts/research/holdout_lock.py:76 (check_window_disjoint -> WindowOverlapsTraining)` · also `scripts/research/holdout_lock.py:86 (bar_for: N-th read of a family needs a deflated bar)`, `scripts/research/holdout_lock.py:129 (claim_read)`, `scripts/research/prop_gate.py, scripts/research/ml_decision_entry.py, scripts/research/ml_entry_v2.py (graders wired to it)`
- **Blocks:** Refuses to record a holdout read whose window starts on/before the training end; and makes each re-read of a family on an overlapping window clear a stricter significance bar (never refuses a re-read).
- **Added:** 2026-11-05 3cab0a941f HOLDOUT-DEFLATED-REUSE: holdout re-reads allowed on a deflated bar (#23461) [git log -S'check_window_disjoint' holdout_lock.py]
- **Operator authorization (VERBATIM):** VERBATIM: operator 2026-11-05 ~19:05Z: "We can't just, like, give up on a certain line of research because we've already trained a model on all the data that we have. That's ridiculous." popup 'Adopt (Rec.)' (scripts/research/holdout_lock.py:3-5; row HOLDOUT-DEFLATED-REUSE). The row note says 'Gates added: none; this REMOVES the one-read block'. Overlap refusal: PI-20261105-GEXSLEAK-0001, no separate verbatim.
- **Hits, last 14 days:** MEASURED: comms/research/holdout_reads.jsonl has 24 recorded reads, all with read_at in 2026-11-05..2026-11-12 (population: that ledger, all rows); refusals append nothing so refusal count is NOT measurable
- **Cost of removing it:** Overlap refusal is a leakage check (train/holdout date overlap invalidates the test; PI-20261105-GEXSLEAK-0001); deflation is the multiple-testing correction. Removal weakens the promotion evidence behind real-money legs.
- **Recommendation: KEEP.** Operator adopted the deflated-bar design by name; the overlap check is a validity (not preference) check.
- **Question:** Keep this gate? Refuses to record a holdout read whose window starts on/before the training end; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-INTAKE-CI-GUARDS`

- **Where:** `scripts/ci/check_research_queue_decision_rule.py:352 (NEW unit must pre-register decision_rule)` · also `scripts/ci/check_research_queue_design_fields.py (NEW unit needs practice_precedent; hand-written intervention tests need controls)`, `scripts/ci/check_research_queue_ml_consumer.py:261 (NEW ML unit must name ml_consumer + the decision it changes)`, `scripts/ci/check_research_queue_id_bands.py (id collision / band)`, `scripts/ci/run_guards.py:2071,2093,2111,1458 (wiring)`
- **Blocks:** A PR that adds a research/queue unit without decision_rule / practice_precedent / ml_consumer (or in the wrong id band) fails CI; existing units are grandfathered.
- **Added:** decision_rule 2026-09-25 6dc23d0b93 (#12921); id-bands 2026-10-08 90eca9908b (#16968); design_fields 2026-10-28 e3c6f9a6c3 (#20863); ml_consumer 2026-10-29 82442520be (#21178)
- **Operator authorization (VERBATIM):** VERBATIM (decision_rule): C1 operator note "Decide before you measure: the result IS the decision, removing the interpretation step where everything currently dies" (scripts/ci/check_research_queue_decision_rule.py:6). ML-consumer refusal: operator popup 2026-10-29 ~22:10Z approved to stay (NO-NEW-GATES-RULE). design_fields: 'Operator 2026-10-28: designs must rest on real-world practice' (check_research_queue_design_fields.py header) -- paraphrase. id_bands: none.
- **Hits, last 14 days:** not measured: PR-time CI results are not in the repo (population would be research/queue-touching PRs 2026-10-29..11-12)
- **Cost of removing it:** Units authored without a pre-registered rule land and wait for interpretation (404 'dead' dispositions measured per the guard header); ML units proliferate as learner variants (43 of 50 in the week of 2026-10-22).
- **Recommendation: KEEP.** decision_rule and ml_consumer carry operator quotes/approval; design_fields and id_bands are lighter and could be report-only but are grandfather-graded.
- **Question:** Keep this gate? A PR that adds a research/queue unit without decision_rule / practice_precedent / ml_consumer (or in the wrong id band) fails CI; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-NOT-BEFORE-AND-RETRY-CAP`

- **Where:** `scripts/research/dispatch_queue.py:456-461 (not_before: fresh-window confirmation waits; unparseable value refuses)` · also `scripts/research/dispatch_queue.py:141-142 and :509-514 (MAX_NONVERDICT_RETRIES=2 -> 'retry cap reached ... needs a human')`, `scripts/research/dispatch_queue.py:526-535 (unparseable/undated stamp refuses to fire)`
- **Blocks:** A queue unit with a future `not_before` is not fired until that time; a unit that produced non-verdict results twice is parked for a human; an unparseable last_dispatched_at refuses to re-fire.
- **Added:** not_before 2026-10-16 5a415623a1 research: template-cell PASS opens one fresh-window confirmation (#18593); retry cap 2026-10-13 0edfd7a142 fix(research): re-arm producer_failed-only once-units (#17829) [git log -S on dispatch_queue.py; earliest commit touching the string, cap may predate]
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'RESEARCH-CONFIRM-FRESH-WINDOW (operator 2026-10-16)' (scripts/research/dispatch_queue.py:452) -- no verbatim quote there. Retry cap: no operator reference.
- **Hits, last 14 days:** not measured: dispatcher decisions not committed
- **Cost of removing it:** not_before: a confirmation unit would run on the same data its PASS saw (invalid confirmation). Retry cap: an always-failing unit would loop and consume runners (the b62x producer_failed x3 case, dispatch_queue.py:491).
- **Recommendation: KEEP.** Both protect compute/validity of research, are not on the trade path, and the retry cap is annotated 'needs a human' rather than a halt.
- **Question:** Keep this gate? A queue unit with a future `not_before` is not fired until that time; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-POWER-GATE`

- **Where:** `scripts/research/research_queue.py:363 (grade_power)` · also `scripts/research/dispatch_queue.py:1777-1780 (BLOCKED_POWER: a unit whose power is not runnable is never fired)`, `scripts/research/research_queue.py:415-470 (feasibility: declared n must be grounded in data, not asserted)`
- **Blocks:** Dispatcher will not fire a queue unit with no `power:` block, missing expected_n / min_detectable_effect, empty basis, infeasible declared n, or a deterministic-kind exemption with no why_not_inferential.
- **Added:** 2026-08-27 28e47d97c4 T2: a standing research queue with a blocking power gate and a dispatcher (#10365) [git log -S'def grade_power']
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'This module is R4 (pre-registration with a BLOCKING power gate) ... Operator-decided 2026-08-27: the queue is one file per job' (scripts/research/research_queue.py:6-10). The 'blocking power gate' wording is the session's; no operator verbatim found.
- **Hits, last 14 days:** not measured: dispatcher decisions (blocked_power) are emitted to the Actions run output, not committed to the repo
- **Cost of removing it:** Underpowered experiments would run and burn compute; evidence cited in-code: RQ-20260830-002 declared n=50 vs floor 49.06 with 5 legs achieving 4-8 OOS trades (research_queue.py:420-430).
- **Recommendation: OPERATOR-PREFERENCE.** Prevents wasted compute but is a blocking gate with no verbatim operator authorization found; could be a report-only 'underpowered' flag on the result.
- **Question:** Keep this gate? Dispatcher will not fire a queue unit with no `power:` block, missing expected_n / min_detectable_effect, empty basis, infeasible declared n, or a deterministic-kind exemption with *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `RESEARCH-ROUTE-AND-CONFIG-GATE`

- **Where:** `scripts/research/research_queue.py:611 (grade_route: no `routing:` block = unroutable)` · also `scripts/research/dispatch_queue.py:321 (config_problem)`, `scripts/research/dispatch_queue.py:297-317 (_e35_scope_problem: unit naming an out-of-scope e35 family is doomed, not fired)`, `scripts/research/dispatch_queue.py:1411-1419 (research-script-run preflight refusal)`, `scripts/research/dispatch_queue.py:1436-1440 (undeclared workflow input -> refused before gh)`
- **Blocks:** Dispatcher will not fire a unit with no routing block, a malformed config, a workflow input GitHub would 422, a failing preflight, or a leg the e35 planner refuses.
- **Added:** 2026-08-27 28e47d97c4 T2: a standing research queue with a blocking power gate (#10365) [git log -S'def grade_route'] (dispatch_queue config_problem/e35 scope checks added later, not individually dated)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: 'the dispatcher does not infer where a job can run' (research_queue.py:615); R5 'scheduler's routing' operator-decided 2026-08-27 (research_queue.py:7)
- **Hits, last 14 days:** not measured: outcomes in Actions logs only
- **Cost of removing it:** A malformed unit would fail at dispatch (HTTP 422) or die in `plan`; it would burn a retry (MAX_NONVERDICT_RETRIES=2) and one runner slot. No money path.
- **Recommendation: KEEP.** Refuses only units that provably cannot run; no operator-wanted work is blocked.
- **Question:** Keep this gate? Dispatcher will not fire a unit with no routing block, a malformed config, a workflow input GitHub would 422, a failing preflight, or a leg the e35 planner refuses. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `SOAK-CONTRACT-GUARD`

- **Where:** `scripts/ci/check_soak_contracts.py:291 (main) / scripts/ci/run_guards.py:367` · also `scripts/ops/soak_state.py (contract_problems: n_needed >2 or <1, calendar fields refused)`, `scripts/ci/check_soak_registered.py (not wired: removed from run_guards.py:348)`, `soak-doctrine-guard (run_guards.py)`
- **Blocks:** CI refuses a new Stage-1 roster leg or shadow strategy with no soak contract in SOAKS.json, a contract with n_needed >2 or an end date, a checklist row entering landed_unproven with no definition of done.
- **Added:** 2026-10-04 2c6c701539 fix(soak): ... soak-contract-guard (SOAK-WATCH) (#16398) [git log -S'definition of done']; 2026-10-15 tightening not separately dated
- **Operator authorization (VERBATIM):** VERBATIM: operator 2026-10-04 "we can't set something to soak if we don't know when it's done. It has to have a definition of done so that it knows to create an alert … that is basic." and 2026-10-15 "A soak is a mechanical verification that was already proven in backtesting, and nothing needs to soak for more than one or two trades." (scripts/ci/check_soak_contracts.py:3-6; scripts/ops/soak_state.py:10-12)
- **Hits, last 14 days:** not measured: CI results not in repo
- **Cost of removing it:** Legs could sit in soak with no exit condition (the operator's stated worry) or be given long calendar soaks the operator banned.
- **Recommendation: KEEP.** Backed by two verbatim operator statements.
- **Question:** Keep this gate? CI refuses a new Stage-1 roster leg or shadow strategy with no soak contract in SOAKS.json, a contract with n_needed >2 or an end date, a checklist row entering landed_unproven wit *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### CI landing machinery (32)

#### `AUTOMERGE-ARMING-CHECK-ATTACHED` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ci/automerge_arming.py:85` · also `scripts/ci/automerge_arming.py:81 WAIT_BUDGET_S=240`, `.github/workflows/claude-pr-automerge.yml:694`
- **Blocks:** Auto-merge is not armed until at least one check run other than the workflow's own job exists on the head (waits up to 240 s for a PAT-opened PR).
- **Added:** 2026-09-12 4833cc4211 U2 prevention: never arm auto-merge on a head no check is measuring (MI-280) (#11889)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: only in workflow run logs.
- **Cost of removing it:** Six instances 2026-09-08 and one 2026-09-12 dropped a commit carrying a live lane's registry row (file docstring).
- **Recommendation: KEEP.** Prevents arming a merge no check measures; delays by up to 4 min only.
- **Question:** No operator authorization found. Keep this gate? Auto-merge is not armed until at least one check run other than the workflow's own job exists on the head (waits up to 240 s for a PAT-opened PR). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AUTOMERGE-REQUEST-GATE` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/claude-pr-automerge.yml:294` · also `.github/workflows/claude-pr-automerge.yml:302`, `.github/workflows/claude-pr-automerge.yml:194 (concurrency group per ref, cancel false)`
- **Blocks:** The auto-merge workflow does nothing unless the pushed branch's OWN .github/pr-automerge-requests/<slug>.txt is added/changed since the merge-base (a merge of main or stale carry-over arms nothing).
- **Added:** 2026-09-02 2816698ac4 automerge: gate the relay on the branch's OWN request, and stop it un-drafting (#10810); merge-base version 2026-09-24 (E63)
- **Operator authorization (NONE):** NONE FOUND (incident-derived: #10788 un-drafted by a merge of main)
- **Hits, last 14 days:** measured: 3243 new .github/pr-landing/*.json declarations were added on origin/main 2026-10-29..2026-11-12 (population: files added under .github/pr-landing in 3250 main commits; `git log --diff-filter=A`): 2810 self/tier1, 432 hold (160 t2 needs_approval, 106 t1 unvouchable_paths, 75 t3 needs_approval, 52 operator_asked_to_hold, 15 t1 changes_landing_machinery, 11 t1 tier_2_3, 7 awaiting_evidence, 6 depends_on_unmerged). 2813 arming files added in window.
- **Cost of removing it:** Incident 2026-08-22 (README armed itself) and 2026-09-02 (#10788 un-drafted and armed having asked for nothing).
- **Recommendation: KEEP.** It only prevents arming a merge nobody requested.
- **Question:** No operator authorization found. Keep this gate? The auto-merge workflow does nothing unless the pushed branch's OWN .github/pr-automerge-requests/<slug>.txt is added/changed since the merge-base (a merge of main or stale carry-o *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `BP-ENFORCE-ADMINS` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/branch-protection-sync.yml:208`
- **Blocks:** enforce_admins=true: repo admins and admin-token API merges cannot bypass the required checks (set unconditionally, overriding any live value).
- **Added:** 2026-05-21 72a5e8ab96 ci: enforce required checks on admins + promote 4 guards to required (#1645)
- **Operator authorization (NONE):** NONE FOUND (comment only describes an 'emergency-merge escape hatch: temporarily set this to false')
- **Hits, last 14 days:** not measured: CI check outcomes are in GitHub Actions run history, not committed to the repo; see LANDING-DECLARATION-VOLUME row for declaration counts
- **Cost of removing it:** Without it every merge in this repo (all via admin-scoped API) bypasses required checks, per the file's own comment.
- **Recommendation: OPERATOR-PREFERENCE.** Makes the required checks real; flipping it off is a one-line change but removes the only hard merge gate, so the operator should choose.
- **Question:** No operator authorization found. Keep this gate? enforce_admins=true: repo admins and admin-token API merges cannot bypass the required checks (set unconditionally, overriding any live value). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R10-ARMED-BUT-HOLD` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ci/check_pr_landing.py:1737` · also `scripts/ci/check_pr_landing.py:1512 (armed, no declaration)`
- **Blocks:** Arming auto-merge (request file) while declaring landing:hold, or while having no declaration at all, fails guards (not grandfathered by branch age).
- **Added:** 2026-09-03 832523d0a5 (#10894)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** measured: 3243 new .github/pr-landing/*.json declarations were added on origin/main 2026-10-29..2026-11-12 (population: files added under .github/pr-landing in 3250 main commits; `git log --diff-filter=A`): 2810 self/tier1, 432 hold (160 t2 needs_approval, 106 t1 unvouchable_paths, 75 t3 needs_approval, 52 operator_asked_to_hold, 15 t1 changes_landing_machinery, 11 t1 tier_2_3, 7 awaiting_evidence, 6 depends_on_unmerged). Per-rule refusal counts are NOT in any repo ledger (CI run results live in GitHub Actions, not committed). 203 of 3250 main-commit subjects since 2026-10-29 contain the word HOLD (all are PR titles declaring a deliberate hold, not refusals).
- **Cost of removing it:** Real incident: PR #12858 armed + merged despite declaring hold (E63) -- but that is now also stopped by AUTOMERGE-LANDING-GATE.
- **Recommendation: KEEP.** Prevents a held PR being auto-merged against its own declaration (E63 incident).
- **Question:** No operator authorization found. Keep this gate? Arming auto-merge (request file) while declaring landing:hold, or while having no declaration at all, fails guards (not grandfathered by branch age). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R6-ARMING-REQUIRED` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ci/check_pr_landing.py:1665`
- **Blocks:** landing:self without an added/modified .github/pr-automerge-requests/<slug>.txt fails (declaring ready lands nothing).
- **Added:** 2026-09-03 832523d0a5 (#10894)
- **Operator authorization (NONE):** NONE FOUND (mechanism requirement, derived from 2026-09-03 stranded PRs)
- **Hits, last 14 days:** measured (proxy): 2813 arming request files added 2026-10-29..11-12 (population: files added under .github/pr-automerge-requests).
- **Cost of removing it:** Without arming, self-land PRs sit open; it is a consistency check, not a restriction on landing.
- **Recommendation: MAKE-REPORT-ONLY.** It only checks that the author asked for the thing they declared; failing the PR over a missing arming file adds friction.
- **Question:** No operator authorization found. Keep this gate? landing:self without an added/modified .github/pr-automerge-requests/<slug>.txt fails (declaring ready lands nothing). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R7-HOLD-VOCAB` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ci/check_pr_landing.py:1746` · also `scripts/ci/check_pr_landing.py:850 HOLD_REASONS`, `scripts/ci/check_pr_landing.py:1755`
- **Blocks:** landing:hold must carry hold_reason from a closed 6-word vocabulary and hold_text >= 20 chars, else guards fails.
- **Added:** 2026-09-03 832523d0a5 (#10894); unvouchable_paths reason added 2026-09-09 (MI-226)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** measured (proxy): 432 hold declarations added 2026-10-29..11-12 all passed this shape (they exist on main).
- **Cost of removing it:** No evidence found.
- **Recommendation: REMOVE.** A typed-vocabulary check on a free-text field is bookkeeping friction on PRs that are already held.
- **Question:** No operator authorization found. Keep this gate? landing:hold must carry hold_reason from a closed 6-word vocabulary and hold_text >= 20 chars, else guards fails. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R8-R9-R14-HOLD-VERIFY` (RM) · trigger case — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ci/check_pr_landing.py:1764` · also `scripts/ci/check_pr_landing.py:1783 R14`, `scripts/ci/check_pr_landing.py:1800 R9`
- **Blocks:** A hold's stated reason must be TRUE against the diff: changes_landing_machinery needs a machinery path in the diff (R8); unvouchable_paths needs a path outside TIER1_SURFACE and tier 1 (R14); depends_on_unmerged_pr must name #N (R9). Fails guards otherwise.
- **Added:** 2026-09-03 832523d0a5 (#10894); R14 2026-09-09
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured per rule; 15 changes_landing_machinery + 106 unvouchable_paths + 6 depends_on holds declared 2026-10-29..11-12 (new pr-landing files).
- **Cost of removing it:** No evidence found; it was added so a hold reason cannot be an unverified excuse (a self-imposed anti-lying check).
- **Recommendation: REMOVE.** It polices the wording of an optional hold; a false reason on a hold harms nothing because a human merges it anyway.
- **Question:** No operator authorization found. Keep this gate? A hold's stated reason must be TRUE against the diff: changes_landing_machinery needs a machinery path in the diff (R8); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PYTEST-COLLECT-REQUIRED` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/pytest-collect.yml:91`
- **Blocks:** Test tree must import/collect cleanly before merge.
- **Added:** 2026-05-07 bb83914183 S-044 COMPLETE: M4 CI suite
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: CI check outcomes are in GitHub Actions run history, not committed to the repo; see LANDING-DECLARATION-VOLUME row for declaration counts
- **Cost of removing it:** Subsumed largely by pytest-run (which imports everything it runs); low independent value.
- **Recommendation: REMOVE.** pytest-run already imports the whole tree, so the separate required collect-only context adds delay without extra protection.
- **Question:** No operator authorization found. Keep this gate? Test tree must import/collect cleanly before merge. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PYTEST-RUN-REQUIRED` (RM) — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/pytest-run.yml:126` · also `.github/workflows/pytest-run.yml:383-434 (steps skip when no python/test file changed)`
- **Blocks:** Full test suite must pass (tests/ minus test_main_loop.py) before any PR merges; PRs that change no python/test files skip the expensive steps and pass.
- **Added:** 2026-05-21 da541b68e4 ci: add pytest-run to actually execute the test suite (advisory) (#1644); required 2026-05-22
- **Operator authorization (NONE):** NONE FOUND (history comment only)
- **Hits, last 14 days:** not measured: CI check outcomes are in GitHub Actions run history, not committed to the repo; see LANDING-DECLARATION-VOLUME row for declaration counts
- **Cost of removing it:** Header cites regressions that passed collect-only (allowlist drift 14/30, shadow wiring gap) that only execution caught.
- **Recommendation: OPERATOR-PREFERENCE.** Ordinary test CI; blocks every PR on any test failure including unrelated flakes, operator has not explicitly ruled on it.
- **Question:** No operator authorization found. Keep this gate? Full test suite must pass (tests/ minus test_main_loop.py) before any PR merges; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AUTOMERGE-DRAFT-REFUSAL` (RM)

- **Where:** `.github/workflows/claude-pr-automerge.yml:468`
- **Blocks:** Workflow refuses to un-draft or arm a draft PR it did not itself open.
- **Added:** 2026-09-02 2816698ac4 (#10810)
- **Operator authorization (PARAPHRASE):** PARTIAL: related operator quote loosens drafts: "Going into github to marke drafts ready is not something we can include in the workflow" 2026-09-03, .github/workflows/pr-opener.yml:20. The refusal itself: NONE FOUND
- **Hits, last 14 days:** not measured: refusals appear as workflow notices 'REFUSING -- ... is a DRAFT' in run logs only.
- **Cost of removing it:** Incident: #10788 and #10764 un-drafted despite being held draft on explicit operator instruction (2026-09-02).
- **Recommendation: OPERATOR-PREFERENCE.** Operator said un-drafting by hand cannot be part of the workflow, yet the refusal keeps drafts as holds; hold-by-declaration already exists (R7/R10).
- **Question:** Keep this gate? Workflow refuses to un-draft or arm a draft PR it did not itself open. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AUTOMERGE-LANDING-GATE` (RM)

- **Where:** `scripts/ci/automerge_landing_gate.py:116` · also `scripts/ci/automerge_landing_gate.py:186 grade_premerge (pre-merge re-read)`, `.github/workflows/claude-pr-automerge.yml:492`, `.github/workflows/claude-pr-automerge.yml:636-748`
- **Blocks:** Never arm (and never direct-merge) a PR whose declaration reads anything but self (hold, unreadable, mandate unchecked); the fallback pulls.merge re-reads PR open/head/request/landing at the current head and refuses on any change.
- **Added:** 2026-09-24 c7cae3f4dd E63; pre-merge re-read 2026-10-08 8a4184ab13 (#17124)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: commit c7cae3f4dd subject "(R12 read delegated to manager by operator 2026-09-...)" authorizes the manager read, not the refusal
- **Hits, last 14 days:** not measured: refusals only in workflow run logs ('NOT ARMING #N').
- **Cost of removing it:** Incidents: #12858 (armed+merged while hold, 2026-09-24) and #17038 (hold, deleted request, disabled auto-merge ignored, merged 2026-10-08).
- **Recommendation: KEEP.** Honors a PR's own hold; two incidents merged held PRs.
- **Question:** Keep this gate? Never arm (and never direct-merge) a PR whose declaration reads anything but self (hold, unreadable, mandate unchecked); *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `BP-REQUIRED-CHECKS-MAIN` (RM) · trigger case

- **Where:** `.github/workflows/branch-protection-sync.yml:153` · also `.github/workflows/branch-protection-report.yml (read-only reporter of live protection)`, `docs/claude/ci-status-checks.md (UNVERIFIED: its own header says 'nobody has verified this document's status'; not used as a source)`
- **Blocks:** GitHub refuses to merge any PR (including admin API merges) to main until pytest-collect, pytest-run and guards are all green. Source of truth is the hardcoded REQUIRED_CONTEXTS list in branch-protection-sync.yml, PUT to GitHub daily 05:23Z and on edit of that file; no committed ledger of the live state (live read needs a [bp-report] issue).
- **Added:** 2026-05-07 d5b6318972 ci: auto-sync branch protection on every push to main (#439); current 3-context list 2026-08-07 910e3163da (#8539); pytest-run made required 2026-05-22 (#1721 per comment)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: docs/CLAUDE-RULES-CANONICAL.md:2404-2406 "The hard safety net is GitHub branch-protection -- required status checks (pytest-collect / pytest-run / guards) with enforce_admins, so no merge lands red" (describes, no operator quote)
- **Hits, last 14 days:** not measured: required-check failures live in GitHub Actions run history; `guards` also runs on push to main. No committed ledger.
- **Cost of removing it:** Removing would let red code merge to main, which deploys to the live trader within ~5 min via ict-git-sync (CLAUDE.md). Evidence: comment in branch-protection-sync.yml 2026-05-21 that without enforcement 'checks gate merges' was cosmetic.
- **Recommendation: OPERATOR-PREFERENCE.** This is the core CI safety net for a live-money repo and is operator-described as the safety net, but no verbatim authorization of the specific list exists; the operator should confirm which of the 3 contexts stay required.
- **Question:** Keep this gate? GitHub refuses to merge any PR (including admin API merges) to main until pytest-collect, pytest-run and guards are all green. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CLAIM-MERGE-SLOT-HOOK` (RM)

- **Where:** `.claude/settings.json:55-60` · also `tests/test_merge_slot_guard.py`
- **Blocks:** PreToolUse hook DENIES mcp__github__merge_pull_request / enable_pr_auto_merge until the session makes the merge-slot claim and touches a fresh (<20 min) /tmp marker. Never loads on Claude Code on the web (settings comment: 1,379 'Found 0 total hooks').
- **Added:** 2026-07-27 e3b7aaace5 coordination: hard-enforce the per-merge slot claim (PreToolUse guard) (#7768)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: settings.json:58 "MERGE-SLOT GUARD (operator-directed 2026-07-27)"; canonical:2400 "operator decision, 2026-06-28" ("not a new CI gate")
- **Hits, last 14 days:** not measured: hook denials are not logged in repo; settings comment says it fires nowhere on web sessions.
- **Cost of removing it:** Comment cites a session auto-merging without protocol causing behind-rebase churn; strict is now off so that churn cause is gone.
- **Recommendation: REMOVE.** Speed-bump with a marker file, serializes nothing (R13 doc), and does not run on the web runtime.
- **Question:** Keep this gate? PreToolUse hook DENIES mcp__github__merge_pull_request / enable_pr_auto_merge until the session makes the merge-slot claim and touches a fresh (<20 min) /tmp marker. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R0-R3-DECL-SHAPE` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1542` · also `scripts/ci/check_pr_landing.py:1552-1560`
- **Blocks:** Landing declaration .github/pr-landing/<slug>.json must parse as an object (R0), tier must be 1/2/3 (R1), landing must be self\|hold\|mandate (R2), and `why` must be >= 20 chars (R3, MIN_TEXT). Fails the required `guards` check otherwise (only once a declaration file exists).
- **Added:** 2026-09-03 832523d0a5 MI-88: Tier-1 work lands itself, and a guard that bites (#10894)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: docs/CLAUDE-RULES-CANONICAL.md Permission Tiers + check_pr_landing.py docstring "Every PR declares its TIER and how it intends to LAND"; no verbatim operator quote
- **Hits, last 14 days:** measured: 3243 new .github/pr-landing/*.json declarations were added on origin/main 2026-10-29..2026-11-12 (population: files added under .github/pr-landing in 3250 main commits; `git log --diff-filter=A`): 2810 self/tier1, 432 hold (160 t2 needs_approval, 106 t1 unvouchable_paths, 75 t3 needs_approval, 52 operator_asked_to_hold, 15 t1 changes_landing_machinery, 11 t1 tier_2_3, 7 awaiting_evidence, 6 depends_on_unmerged). Per-rule refusal counts are NOT in any repo ledger (CI run results live in GitHub Actions, not committed). 203 of 3250 main-commit subjects since 2026-10-29 contain the word HOLD (all are PR titles declaring a deliberate hold, not refusals).
- **Cost of removing it:** No evidence found; the declaration is the input that later rules and auto-merge read.
- **Recommendation: OPERATOR-PREFERENCE.** Schema validation of paperwork the system itself requires; a typo blocks merge, but the paperwork drives landing.
- **Question:** Keep this gate? Landing declaration .github/pr-landing/<slug>.json must parse as an object (R0), tier must be 1/2/3 (R1), landing must be self\|hold\|mandate (R2), and `why` must be >= 20 chars (R3, *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R11-NO-DECLARATION` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1531` · also `scripts/ci/check_pr_landing.py:991 guard_existed_at_merge_base`
- **Blocks:** A PR branch cut after 2026-09-03 with NO .github/pr-landing/<slug>.json fails guards (filename must equal branch slug exactly). Pre-guard branches pass loudly as undeclared_predates_guard.
- **Added:** 2026-09-03 832523d0a5 (#10894)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: check_pr_landing.py docstring 'Every PR declares its TIER' -- no verbatim quote
- **Hits, last 14 days:** measured: 3243 new .github/pr-landing/*.json declarations were added on origin/main 2026-10-29..2026-11-12 (population: files added under .github/pr-landing in 3250 main commits; `git log --diff-filter=A`): 2810 self/tier1, 432 hold (160 t2 needs_approval, 106 t1 unvouchable_paths, 75 t3 needs_approval, 52 operator_asked_to_hold, 15 t1 changes_landing_machinery, 11 t1 tier_2_3, 7 awaiting_evidence, 6 depends_on_unmerged). Per-rule refusal counts are NOT in any repo ledger (CI run results live in GitHub Actions, not committed). 203 of 3250 main-commit subjects since 2026-10-29 contain the word HOLD (all are PR titles declaring a deliberate hold, not refusals).
- **Cost of removing it:** No evidence found; without declarations R5/R12 and auto-merge arming cannot grade anything.
- **Recommendation: MAKE-REPORT-ONLY.** Failing a PR for lacking paperwork is friction; the declaration could be auto-generated or the check made informational.
- **Question:** Keep this gate? A PR branch cut after 2026-09-03 with NO .github/pr-landing/<slug>.json fails guards (filename must equal branch slug exactly). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R12-MACHINERY-NO-SELF-LAND` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1652` · also `scripts/ci/check_pr_landing.py:772 LANDING_MACHINERY (20 paths/globs incl. claude-pr-automerge.yml, check_pr_landing.py, commit-to-main, claim_merge_slot.py, research/templates/**, research/programmes/**, approvals dir)`
- **Blocks:** A landing:self PR whose diff edits the landing machinery (listed workflows/scripts, templates, programmes, approvals) fails; it must declare hold/changes_landing_machinery and wait for a human read.
- **Added:** 2026-09-03 832523d0a5 (#10894); list grown 2026-09-09, 09-24, 09-28, 09-29, 10-15
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: check_pr_landing.py docstring "This file's own PR is the first instance"; E63 delegated read: automerge_landing_gate commit message "R12 read delegated to manager by operator 2026-09-..."
- **Hits, last 14 days:** measured (proxy): 15 tier-1 + 3 tier-2/3 changes_landing_machinery holds declared 2026-10-29..11-12 (new pr-landing files).
- **Cost of removing it:** Guards the merge machinery that can land real-money changes; a bad edit can disarm every other landing check. Treated as design principle in docstring; no incident of removal.
- **Recommendation: OPERATOR-PREFERENCE.** Protects the landing route from self-edit but forces a human on every edit of 20 files incl. research templates; operator should say whether that is wanted.
- **Question:** Keep this gate? A landing:self PR whose diff edits the landing machinery (listed workflows/scripts, templates, programmes, approvals) fails; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R13-MERGE-SLOT-CLAIM` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1677` · also `scripts/ci/check_pr_landing.py:1016 _branch_claim_state`, `scripts/ci/check_pr_landing.py:1042 slot_claim_state`, `scripts/ops/claim_merge_slot.py`, `scripts/ops/merge_slot_state.py`
- **Blocks:** An armed landing:self branch must add/modify its own .github/merge-slots/<slug>.json (branch, held_by, claimed_at) or the legacy merge_slot field, else guards fails. The code says it does NOT serialize anything: only records an attributable claim.
- **Added:** 2026-09-08 a0ec22ce17 pr-landing R13: put the merge slot on the arming route (#11344)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: settings.json:58 "MERGE-SLOT GUARD (operator-directed 2026-07-27)" for the hook; no operator quote for the CI rule R13
- **Hits, last 14 days:** measured (proxy): 3121 per-branch merge-slot claim files added 2026-10-29..11-12 (population: files added under .github/merge-slots in main). Refusals not recorded.
- **Cost of removing it:** Its own docstring: 'R13 DOES NOT SERIALIZE' -- concurrent-merge safety rests on required checks. Cost of removal: none beyond losing attribution.
- **Recommendation: REMOVE.** A check that by its own docstring serializes nothing and costs a file per PR (3121 in 14 days).
- **Question:** Keep this gate? An armed landing:self branch must add/modify its own .github/merge-slots/<slug>.json (branch, held_by, claimed_at) or the legacy merge_slot field, else guards fails. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R15-TIER2-APPROVAL-RECORD` (RM) · trigger case

- **Where:** `scripts/ci/check_pr_landing.py:1228` · also `scripts/ci/check_pr_landing.py:1169 approval_separation`, `scripts/ci/check_pr_landing.py:1223 paths_outside_scope`, `docs/claude/work/approvals/ (credential dir)`
- **Blocks:** A Tier-2 landing:self PR is refused unless a committed approval record (docs/claude/work/approvals/<slug>.json) exists at the merge-base, byte-identical at HEAD, names this branch, tier 2, typed verdict/channel/decision_id/work_object/text>=N chars, scope_paths covering the diff, no Tier-3 path. Tier-3 never.
- **Added:** 2026-09-12 2cd829991d R15: let an operator-approved Tier-2 PR land, without letting a branch approve itself (#11817)
- **Operator authorization (VERBATIM):** VERBATIM (loosening, which created the route): "the operator does not click things." 2026-09-11, check_pr_landing.py:100. The restriction itself: PARAPHRASE ONLY (tier table)
- **Hits, last 14 days:** not measured: no per-rule ledger; 160 tier-2 hold declarations added 2026-10-29..11-12 (these chose hold, not R15).
- **Cost of removing it:** Without it a session could self-approve Tier-2 runtime changes; Tier-2 touches runtime/deploy/order-path. Docstring documents the two-PR forgery chain.
- **Recommendation: OPERATOR-PREFERENCE.** Mechanism that lets Tier-2 land on a recorded approval; separation-of-approval is the operator's tier policy but the strictness (10 clauses) was not specified by him.
- **Question:** Keep this gate? A Tier-2 landing:self PR is refused unless a committed approval record (docs/claude/work/approvals/<slug>.json) exists at the merge-base, byte-identical at HEAD, names this branch, *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R16-MANDATE-AUTOLAND` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1712` · also `scripts/ci/check_mandate_autoland.py (8 clauses A1-A8)`
- **Blocks:** landing:mandate (Tier-3 Stage-2 roster removal only) is admitted only if every clause of check_mandate_autoland holds, incl. a granted mandate entry carrying autoland:true; and may not also arm the ordinary route. Built, not armed (no mandate carries autoland).
- **Added:** 2026-09-26 b9d7116df7 R16: the mandate auto-land route (#12974)
- **Operator authorization (VERBATIM):** VERBATIM: operator decision 2026-09-25 "Build auto-land route" (check_pr_landing.py:158)
- **Hits, last 14 days:** not measured: route unarmed; 0 mandate-landing declarations among the 3243 added in window (counter above shows none).
- **Cost of removing it:** Route can only REMOVE legs from real-money rosters; removing the check would remove the only guard on that route (it is unarmed so nothing lands today).
- **Recommendation: KEEP.** Operator-requested route whose clauses protect a real-money roster edit; currently inert.
- **Question:** Keep this gate? landing:mandate (Tier-3 Stage-2 roster removal only) is admitted only if every clause of check_mandate_autoland holds, incl. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R4-TIER3-NEVER-SELF-LAND` (RM) · trigger case

- **Where:** `scripts/ci/check_pr_landing.py:1612`
- **Blocks:** A declaration of tier 3 with landing:self fails; Tier-3 PRs (strategy logic, risk caps, sizing, accounts.yaml mode, live promotion) can only be landed by a human (or the R16 mandate route).
- **Added:** 2026-09-03 832523d0a5 (#10894)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY (the tier table that defines it is an operator-set permission policy): docs/CLAUDE-RULES-CANONICAL.md:1820-1822 "Tier 3 ... Explicit product approval required before merge" -- but no verbatim operator quote naming this check; also operator 2026-09-27 verbatim at canonical:1826 only loosens: "make tier 2 and 3 decisions autonomously as long as they are backed by data"
- **Hits, last 14 days:** measured (proxy): 75 tier-3 hold declarations + 2 tier-3 depends_on added 2026-10-29..11-12 (population: new pr-landing files); refusals of landing:self at tier 3 not recorded.
- **Cost of removing it:** Tier-3 paths are order/risk code on the live trader; deploy follows merge in ~5 minutes. Operator-defined tier table exists.
- **Recommendation: KEEP.** Tier-3 human merge is the operator's own tier definition and protects live strategy/risk code.
- **Question:** Keep this gate? A declaration of tier 3 with landing:self fails; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-R5-TIER1-SURFACE-ALLOWLIST` (RM)

- **Where:** `scripts/ci/check_pr_landing.py:1640` · also `scripts/ci/check_pr_landing.py:310 TIER1_SURFACE`, `scripts/ci/check_pr_landing.py:672 TIER3_PATHS`, `scripts/ci/check_pr_landing.py:687 TIER2_PATHS`, `scripts/ci/check_pr_landing.py:546 unvouched_paths`
- **Blocks:** A tier-1 landing:self PR fails if its diff touches any path outside the TIER1_SURFACE allowlist (docs, tests, comms, .github, scripts/ci\|ops\|research\|reports, scripts/backtest_*.py, src/console_connector, research/results, runtime_logs/replay_pregate, two ml review scripts, *.md, lint config) or any Tier-2/3 path; the PR must then hold for a human merge. Unknown paths fail closed.
- **Added:** 2026-09-03 832523d0a5 (#10894); widened by MI-242 (2026-09-10), E57 (2026-09-24), 2026-09-28 triage, console connector 2026-11-07
- **Operator authorization (VERBATIM):** VERBATIM widenings only: "You shouldn't need me to merge a change on the dashboard" (2026-11-07, check_pr_landing.py:~331 comment) and "Apply my recommendations (Recommended)" (2026-09-28 popup, ~:347 comment). The restriction itself: PARAPHRASE ONLY (canonical tier table :1820)
- **Hits, last 14 days:** measured (proxy): 106 tier-1 'unvouchable_paths' holds + 11 tier-1 tier_2_3 holds + 38 tier-1 operator_asked_to_hold declared 2026-10-29..11-12 (population: new pr-landing files); each unvouchable_paths hold is a PR whose only blocker was R5 and waited for a manager merge.
- **Cost of removing it:** Allowlist keeps src/**, config/**, deploy/** (live runtime, Tier-2/3) from auto-merging. For paths like scripts/*.py outside src, cost of removal is low; 106 PRs in 14 days needed a human only because of path polarity.
- **Recommendation: OPERATOR-PREFERENCE.** Protects runtime paths (keep for src/config/deploy) but its fail-closed polarity forced ~106 hold PRs in 14 days for paths that are not live code; narrowing to a Tier-2/3 denylist is a taste call.
- **Question:** Keep this gate? A tier-1 landing:self PR fails if its diff touches any path outside the TIER1_SURFACE allowlist (docs, tests, comms, .github, scripts/ci\|ops\|research\|reports, scripts/backtest_*.py *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `ACTIONS-BUDGET-CAPS` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `docs/claude/actions-budget.md (standing rules only)` · also `scripts/research/dispatch_queue.py:1399 (max_minutes default 90 in dispatched units)`
- **Blocks:** No code enforces an Actions-minutes budget cap that I could find: docs/claude/actions-budget.md lists conventions (7-day artifact retention, no forever-cron, dedupe triggers). The only numeric limit in code is research dispatch max_minutes (default 90), outside this lane.
- **Added:** doc rules from 2026-06-10 incident (file text)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: no enforcing code
- **Cost of removing it:** n/a
- **Recommendation: OPERATOR-PREFERENCE.** Convention-level only; the dispatcher per-tick caps are operator-approved (2026-10-29).
- **Question:** No operator authorization found. Keep this gate? No code enforces an Actions-minutes budget cap that I could find: docs/claude/actions-budget.md lists conventions (7-day artifact retention, no forever-cron, dedupe triggers). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CI-CONCURRENCY-CANCEL` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/workflows/pytest-run.yml:126-130` · also `.github/workflows/pytest-collect.yml:91-92`, `.github/workflows/guards.yml:121-122`, `.github/workflows/branch-sync.yml:58-59`, `.github/workflows/pytest-rerun.yml:33-34`
- **Blocks:** 8 workflows (grep 'cancel-in-progress: true' = 8 of 168) cancel an older in-flight run when a newer one for the same PR/ref starts; required checks on a superseded sha are cancelled, not completed. pytest-run/collect/guards cancel only on PR/merge_group, never on push to main (a past incident where every merge cancelled the main run).
- **Added:** not isolated to one commit (several workflows); pytest-run group rewrite cited in file comment 2026-08
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: CI check outcomes are in GitHub Actions run history, not committed to the repo; see LANDING-DECLARATION-VOLUME row for declaration counts
- **Cost of removing it:** Cost only: duplicate ~9-minute pytest runs per push (comment: GH-CAPACITY-INFRA-FIRST). Does not refuse anything, just supersedes.
- **Recommendation: KEEP.** Pure efficiency; refuses nothing a human wants and losing it wastes runner minutes.
- **Question:** No operator authorization found. Keep this gate? 8 workflows (grep 'cancel-in-progress: true' = 8 of 168) cancel an older in-flight run when a newer one for the same PR/ref starts; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `CLAIM-MERGE-SLOT-SCRIPTS` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `scripts/ops/claim_merge_slot.py:234` · also `scripts/ops/merge_slot_state.py`, `scripts/ops/claim_merge_slot.py:326 REFUSED (empty --held-by, missing merge_slot)`
- **Blocks:** Writes the claim; refuses an empty --branch/--held-by and a board without merge_slot. Incumbent-claim grading (merge_slot_state) prints a report and NEVER blocks the write.
- **Added:** 2026-09-09 11fda4b7c2 MI-208 (#11494); merge_slot_state 2026-09-12 5672b40c1e (#11881)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** measured (proxy): 3121 per-branch claim files added in window.
- **Cost of removing it:** Only R13 consumes them.
- **Recommendation: REMOVE.** Tooling for R13, which serializes nothing; refusals are of malformed input only.
- **Question:** No operator authorization found. Keep this gate? Writes the claim; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `COMMIT-TO-MAIN-REFUSALS` — ⚠️ **NO OPERATOR AUTHORIZATION FOUND**

- **Where:** `.github/actions/commit-to-main/action.yml:208` · also `.github/actions/commit-to-main/action.yml:370`, `.github/actions/commit-to-main/action.yml:408`, `.github/actions/commit-to-main/action.yml:533`, `.github/actions/commit-to-main/action.yml:599`
- **Blocks:** Fails the calling data workflow when: PAT token empty, claim_merge_slot.py missing, no R13 claim written, PR cannot be opened in 3 attempts, PR closed unmerged, or PR not merged within verify-timeout (default 50 min; optionally closes the PR). Silently opens no PR if nothing changed.
- **Added:** 2026-07-23 acffd851ee fix(ci): land workflow data commits on protected main via PAT auto-merge PR (#7472); R13 claim refusal 2026-09-09 (MI-208)
- **Operator authorization (NONE):** NONE FOUND
- **Hits, last 14 days:** not measured: step failures in Actions history; 27 workflows call this action.
- **Cost of removing it:** These refuse to open PRs that would fail their own required guard; they surface rather than create stranded PRs.
- **Recommendation: KEEP.** Fail-loud checks on the data-landing path; removal hides stranded data.
- **Question:** No operator authorization found. Keep this gate? Fails the calling data workflow when: PAT token empty, claim_merge_slot.py missing, no R13 claim written, PR cannot be opened in 3 attempts, PR closed unmerged, or PR not merged wi *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `AUTOMERGE-RESEARCH-WORKFLOW-LANDING-GUARD`

- **Where:** `scripts/ci/check_research_workflow_landing.py:121`
- **Blocks:** CI (guards) fails if any workflow that uploads an artifact neither calls research-result, nor carries # landed-by:, nor # no-durable-result: <reason>, nor is in a shrink-only BASELINE dict.
- **Added:** 2026-09-27 816dc482e7 C2: land dukascopy-span-probe through research-result; guard the rest (#13185)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: E57 quote in TIER1 comment: "this is a serious gap that needs to be fully resolved - not only rerunning tests whose results were lost, but ensuring we have a mechanism in place to prevent research from being lost" (2026-09-24, check_pr_landing.py ~:340) -- fits the intent, not this guard by name
- **Hits, last 14 days:** not measured: guard outcomes in Actions history.
- **Cost of removing it:** Prevents research results existing only in 90-day-expiring artifacts.
- **Recommendation: MAKE-REPORT-ONLY.** Protects data not money; a report listing unwired workflows would serve without failing PRs that add an artifact upload.
- **Question:** Keep this gate? CI (guards) fails if any workflow that uploads an artifact neither calls research-result, nor carries # landed-by:, nor # no-durable-result: <reason>, nor is in a shrink-only BASEL *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `BP-STRICT-OFF-RECORD`

- **Where:** `.github/workflows/branch-protection-sync.yml:245`
- **Blocks:** Not a gate: STRICT=false means PRs need NOT be up to date with main (require-up-to-date is OFF). Listed so the audit shows the one protection knob the operator already loosened.
- **Added:** 2026-08-10 f0c909c06a Untick require-up-to-date, and file the stacking fix that missed the expensive job (#8711)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: branch-protection-sync.yml:211 "Set to FALSE on 2026-08-10 (operator-directed)"; canonical doc:2410-2420 "Correction 2026-08-10 ... strict: false, operator-directed"
- **Hits, last 14 days:** not measured: CI check outcomes are in GitHub Actions run history, not committed to the repo; see LANDING-DECLARATION-VOLUME row for declaration counts
- **Cost of removing it:** n/a (it is already loosened; re-enabling caused CI livelock per comment, 3 re-syncs on #8698).
- **Recommendation: KEEP.** It is the loosened state; keep it off.
- **Question:** Keep this gate? Not a gate: STRICT=false means PRs need NOT be up to date with main (require-up-to-date is OFF). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `BRANCH-SYNC-ELIGIBILITY`

- **Where:** `scripts/ci/branch_sync.py:44`
- **Blocks:** Auto-update of behind PRs is skipped for drafts, forks, non-claude/* branches, landing:hold label, non-tier1-self declarations and any Tier-2/3 path touched.
- **Added:** 2026-10-13 d74d040f48 AUTO-BRANCH-SYNC (#17846)
- **Operator authorization (PARAPHRASE):** PARAPHRASE ONLY: plan docs/plans/OPS-AUTOMATION-INVENTORY-2026-10-13.md act M-a (not checked for a verbatim quote)
- **Hits, last 14 days:** not measured: only in workflow logs ('#N skip: why').
- **Cost of removing it:** Updating a hold or Tier-2/3 PR restarts its CI and may mutate a branch a human is reviewing.
- **Recommendation: KEEP.** Narrows an optional convenience automation, never blocks a merge.
- **Question:** Keep this gate? Auto-update of behind PRs is skipped for drafts, forks, non-claude/* branches, landing:hold label, non-tier1-self declarations and any Tier-2/3 path touched. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `HOLD-MERGE-ALARM`

- **Where:** `scripts/ops/pr_landing_hold_alarm.py:1` · also `.github/workflows/pr-landing-hold-merge-alarm.yml (push to main; fails the job red when its reads fail)`
- **Blocks:** Nothing blocked: post-merge page when a tier 2/3 hold PR merged with no APPROVED review, resolving recorded_decision, PR-body citation or operator-approved label. Detector only.
- **Added:** 2026-09-28 78d00c8904 JC-CA-04 (#13507)
- **Operator authorization (VERBATIM):** VERBATIM: operator decision 2026-09-28 "Post-merge alarm", option B only (pr_landing_hold_alarm.py:3); "Accept recorded decisions" 2026-10-09 (:20-ish)
- **Hits, last 14 days:** not measured: the alarm issues are GitHub issues, not committed; runs once per push to main (1,610 runs/wk per workflow comment).
- **Cost of removing it:** Detector, so none; operator chose option B over blocking.
- **Recommendation: KEEP.** Non-blocking detector the operator explicitly chose; report-only already.
- **Question:** Keep this gate? Nothing blocked: post-merge page when a tier 2/3 hold PR merged with no APPROVED review, resolving recorded_decision, PR-body citation or operator-approved label. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `LANDING-DECLARATION-VOLUME`

- **Where:** `.github/pr-landing/ (11394 files on main)`
- **Blocks:** Not a gate: population record. Declarations on main: 11394 total; 9801 self/tier-1, 582 hold t2, 394 hold t1 unvouchable_paths, 204 hold t3, 196 hold t1 operator_asked_to_hold, 83 changes_landing_machinery, rest other.
- **Added:** 2026-09-03 832523d0a5
- **Operator authorization (PARAPHRASE):** n/a
- **Hits, last 14 days:** measured: 3243 new .github/pr-landing/*.json declarations were added on origin/main 2026-10-29..2026-11-12 (population: files added under .github/pr-landing in 3250 main commits; `git log --diff-filter=A`): 2810 self/tier1, 432 hold (160 t2 needs_approval, 106 t1 unvouchable_paths, 75 t3 needs_approval, 52 operator_asked_to_hold, 15 t1 changes_landing_machinery, 11 t1 tier_2_3, 7 awaiting_evidence, 6 depends_on_unmerged). Per-rule refusal counts are NOT in any repo ledger (CI run results live in GitHub Actions, not committed). 203 of 3250 main-commit subjects since 2026-10-29 contain the word HOLD (all are PR titles declaring a deliberate hold, not refusals).
- **Cost of removing it:** n/a
- **Recommendation: OPERATOR-PREFERENCE.** Context for deciding how much of the R-rule friction is still wanted.
- **Question:** Keep this gate? Not a gate: population record. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PR-OPENER-AND-DISABLE`

- **Where:** `.github/workflows/pr-opener.yml:144` · also `.github/workflows/pr-automerge-disable.yml`
- **Blocks:** Not a gate on merging: pr-opener opens draft only if request says draft:true (default false since 2026-09-03). pr-automerge-disable is the off switch.
- **Added:** pr-opener 2026-06-18 85a44ae7d8; draft default flip 2026-09-03
- **Operator authorization (VERBATIM):** VERBATIM (loosening): "Going into github to marke drafts ready is not something we can include in the workflow" 2026-09-03 (pr-opener.yml:20)
- **Hits, last 14 days:** not measured
- **Cost of removing it:** none
- **Recommendation: KEEP.** Records that the draft default was loosened by the operator; nothing to remove.
- **Question:** Keep this gate? Not a gate on merging: pr-opener opens draft only if request says draft:true (default false since 2026-09-03). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PRL-UNVOUCH-STAMP-E57-QUEUE-HOLD`

- **Where:** `scripts/ci/check_pr_landing.py:426` · also `scripts/ci/check_pr_landing.py:432 stamp_only_violation`, `scripts/ci/check_pr_landing.py:517 new_unit_registration_violation`, `scripts/ci/check_pr_landing.py:588 e58_generated_queue_vouch`, `scripts/ci/check_pr_landing.py:640 econ_calendar_vouch`
- **Blocks:** research/queue/*.yaml may self-land only as a last_dispatched_at stamp, a new pre-run unit registration, or a producer-verified (E58 replenish/grade) edit; any other edit (status, decision_rule, blocked_on) is refused under R5 and holds for a human. config/economic_calendar.yaml self-lands only if the producer --verify reproduces it.
- **Added:** 2026-09-24 787564b517 E57 (#12857); new-unit self-land 2026-11-07 16e36c405a (#24028); E58 producers 2026-09-29 ecca21e0e1
- **Operator authorization (VERBATIM):** VERBATIM: operator 2026-10-29 ~22:10Z popup, "the 4 gates that had no operator record are all APPROVED TO STAY: E57 research-queue merge hold ..." -- docs/claude/work/checklist/NO-NEW-GATES-RULE.json note (that wording is the checklist row's transcription of the popup)
- **Hits, last 14 days:** not measured: queue-edit PRs refused by this rule are not logged; research-queue PRs exist (e.g. main subjects 'research queue: disposition 14 done-but-ungraded ... [Tier 1, hold]' #25186).
- **Cost of removing it:** Docstring: a rewritable decision_rule defeats pre-registration, the promotion ladder's safety property; also unstamped dispatch re-fires and bills GPU spend.
- **Recommendation: KEEP.** Explicitly approved to stay by the operator on 2026-10-29.
- **Question:** Keep this gate? research/queue/*.yaml may self-land only as a last_dispatched_at stamp, a new pre-run unit registration, or a producer-verified (E58 replenish/grade) edit; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### run_guards.py guards (one blocking `guards` check) (132)

Every guard here blocks a merge through the required `guards` check unless stated. `Scope` says which PRs it runs on. The full `blocks`, `removal_cost` and `auth` text for each guard is in the JSON.

| id | RM | Auth | Rec | Added | What it blocks | Scope |
|---|---|---|---|---|---|---|
| `account-class-guard` (133) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-06-15 91ba5c658f Add account_class paper/real-money axi | CI guard: every account in config/accounts.yaml carries a valid ``account_class``, consistent with the Bybit-only ``demo`` transport flag. | only PRs touching: config/accounts.yaml, scripts/check_account_class.py |
| `canonical-config-loaders` (1033) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-05-16 776d9f36b2 refactor(config): single canonical rea | CI guard: forbid new hand-rolled parsers for ``config/accounts.yaml``. | only PRs touching: \.py$\|config/accounts\.yaml$ |
| `cost-model-single-owner` (1643) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-20 da8713f914 One home for the round-trip fee: alias | cost-model-single-owner — a fee constant must ALIAS the owner, not restate it. | only PRs touching: scripts/backtest_*.py, scripts/research/*.py, scripts/ml/*.py, src/back |
| `env-gate-guard` (1337) | yes | **NONE** | KEEP | 2026-05-10 9e81fa0852 refactor(runtime): purge process-wide  | S-067 follow-up #4 — env-gate guard for the diff-scan layer. | only PRs touching: \.py$\|\.sh$ |
| `exit-coverage-matrix-guard` (1050) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-13 bf398d51a4 Compute the M20 coverage headline inst | M20 exit-refinement coverage roll-up — the ONE place the milestone's done-condition is computed. | only PRs touching: docs/research/exit-refinement-coverage.json, config/strategies.yaml, sc |
| `matrix-bracket-values` (1131) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-30 f4e750ab3a guard: bracket_geometry value agreemen | matrix-bracket-values — a `shipped` bracket_geometry cell must match the DECLARE. | only PRs touching: docs/research/exit-refinement-coverage.json, config/strategies.yaml, sc |
| `matrix-config-agreement` (1102) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-14 2091d57fc2 M20: the lever-OFF arm finally ran — a | matrix-config-agreement — the coverage matrix must not contradict live config. | only PRs touching: docs/research/exit-refinement-coverage.json, config/strategies.yaml, sc |
| `pairs-sizing-basis-guard` (1581) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-07-16 075e62681f fix(pairs): derive risk budget from ac | pairs-sizing-basis guard — the pairs sleeve must size off the canonical risk basis. | only PRs touching: config/pairs.yaml, src/units/strategies/pairs_executor.py, scripts/ci/c |
| `prop-identity-guard` (1595) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-07-09 88ae4fcf95 prop-identity: CI guard keeping is_pro | prop-identity guard — keep the "is this account prop?" predicate single-homed. | only PRs touching: src/**/*.py, scripts/ci/check_prop_identity_single_home.py |
| `qty-legalization-guard` (2480) | yes | **NONE** | OPERATOR-PREFERENCE | 2026-07-06 c04d70b853 feat(ci): Phase 4 — qty-legalization g | qty-legalization guard — the machine that keeps the venue minimum single-homed. | only PRs touching: **/*.py |
| `risk-basis-agreement` (1625) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-20 1ce85e6984 risk basis: one definition, an explici | Guard: a backtest harness must not silently size at a risk basis that disagrees with live. | only PRs touching: scripts/backtest_*.py, scripts/walkforward_*.py, scripts/research/*.py, |
| `roster-promotion-evidence-guard` (2185) | yes | **NONE** | OPERATOR-PREFERENCE | 2026-09-22 c08c60b13f B1: invert the execution-gate guard —  | Does this diff put a strategy leg onto a RISK-BEARING roster, and if so does a committed evidence record clear the operator's five-clause bar? | only PRs touching: config/accounts.yaml, config/strategies.yaml, config/pairs.yaml, comms/ |
| `roster-symbol-reachability` (160) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 012bccf966 roster-symbol-reachability (E42, Tier- | roster-symbol-reachability — a rostered leg's symbol must be reachable. | only PRs touching: config/accounts.yaml, config/strategies.yaml, config/instruments.yaml,  |
| `strategy-coverage-guard` (2531) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-07-17 9c174abbe7 review(system): daily 2026-07-16 — reg | strategy-coverage guard — the "no new loose ends when you add a strategy" gate. | always (every PR) |
| `strategy-decision-record` (2146) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-09-08 eafafae44d C4: compare the strategy decision reco | strategy-decision-record guard — C4 of the operating-layer build (Phase F). | only PRs touching: config/strategies.yaml, config/strategy_changelog.json, scripts/ci/chec |
| `strategy-risk-guard` (2544) | yes | **NONE** | OPERATOR-PREFERENCE | 2026-06-29 55342f5493 Unit B: uniform 1.5% account-basis siz | Strategy-risk guard — diff-scan layer (per-strategy risk removal, 2026-06-29). | only PRs touching: **/*.py, config/strategies.yaml |
| `tp-venue-cap-single-owner` (1672) | yes | **NONE** | MAKE-REPORT-ONLY | 2026-08-25 eebb8ebec8 tp cap: one owner for the venue TP cla | tp-venue-cap-single-owner — the TP clamp must ALIAS the owner, not restate it. | only PRs touching: src/runtime/tp_venue_cap.py, src/units/strategies/*.py, src/runtime/pos |
| `dry-run-guard` (1322) | yes | PARAPHRASE | KEEP | 2026-05-01 3096342214 feat(trading-mode): unify dry/live fla | Scan a unified diff for new trading-mode DEMOTIONS (dry-run / shadow). | only PRs touching: \.py$\|config/accounts\.yaml$\|config/strategies\.yaml$ |
| `no-action-rate-cap-guard` (1727) | yes | PARAPHRASE | KEEP | 2026-10-29 64cccff639 REMOVE-PER-BAR-CAP: remove the per-bar | no-action-rate-cap-guard: no in-trade action is capped per bar or per time window. | only PRs touching: src/runtime/live_review*.py, scripts/ops/live_review*.py, src/runtime/l |
| `priority-fallback-distribution` (182) | yes | PARAPHRASE | MAKE-REPORT-ONLY | 2026-09-13 d509ad5c34 guards(m20): U40 — the arbitration fal | Is the arbitration fallback still BELOW the legs it was chosen to lose to? | only PRs touching: src/runtime/intents.py, config/strategies.yaml, config/accounts.yaml, d |
| `prop-harness-full-costs-guard` (1750) | yes | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-16 f8b247bf52 PROP-EVAL-COSTS: prop/portfolio evalua | prop-harness-full-costs-guard -- no caller of the portfolio engine runs fee-only. | only PRs touching: scripts/backtest_system.py, scripts/prop/*.py, scripts/walkforward_*.py |
| `prop-roster-gate-guard` (2257) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-10-15 49fa65e4b2 PROP-GATE-PARITY: prop legs clear a su | prop-roster-gate-guard — a prop leg clears EVERYTHING a real-money leg clears, PLUS prop survival. | only PRs touching: config/accounts.yaml, docs/claude/work/SOAKS.json, comms/prop_survival/ |
| `research-queue-ml-consumer-guard` (2111) | yes | VERBATIM | OPERATOR-PREFERENCE | 2026-10-29 82442520be ML pipeline as a standing assembly lin | Every NEW research-queue ML unit names its consumer and the live or demo decision it would change. | only PRs touching: research/queue/**, research/templates/**, research/programmes/**, confi |
| `same-symbol-allocation-guard` (2239) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-10-16 e57055302d SAME-SYMBOL-ALLOCATION: inventory + pe | same-symbol-allocation-guard — legs sharing one (account, symbol) need a KNOWN allocation, not a name tiebreak. | only PRs touching: config/accounts.yaml, config/strategies.yaml, comms/same_symbol_allocat |
| `shadowed-features-guard` (1328) | yes | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-26 ce9e916908 Rule: off the trade path is not off th | shadowed-features-guard: a feature taken off the trade path must stay on the data path. | only PRs touching: docs/reference/shadowed-features.yaml, config/strategies.yaml, docs/cla |
| `soak-contract-guard` (367) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-10-04 2c6c701539 fix(soak): land the weekly grade, soak | soak-contract-guard — nothing enters a soak without a MECHANICAL definition of done. | always (every PR) |
| `soak-doctrine-guard` (2522) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-07-28 4ed94e7b61 Fix the soak doctrine ONCE AND FOR ALL | Guard: the soak doctrine (offline edge, live mechanics) must stay intact. | always (every PR) |
| `strategy-status-guard` (2280) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-10-29 97dde7e5ba STRATEGY-STATUS-MODEL: three strategy  | strategy-status-guard — every leg is on exactly ONE of {general paper} or {real money + mirror}. | only PRs touching: config/accounts.yaml, config/strategies.yaml, scripts/ops/strategy_stat |
| `tp-doctrine-guard` (1702) | yes | PARAPHRASE | OPERATOR-PREFERENCE | 2026-10-06 528eea7beb TP doctrine: canonicalise, measure (tp | tp-doctrine-guard — every rostered leg carries a REAL, REVISABLE take-profit (ratchet). | only PRs touching: config/accounts.yaml, config/strategies.yaml, src/units/strategies/*.py |
| `trader-import-closure` (104) | yes | PARAPHRASE | KEEP | 2026-10-15 1aade6c238 deploy: per-unit trader restart gate — | Guard ``trader-import-closure`` (TRADER-RESTART-GATE). | only PRs touching: **/*.py, config/trader_import_closure.txt |
| `action-input-wiring` (241) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-26 61cab1cfd9 chore(land): tier-1 self-land declarat | CI guard: every `with:` key a workflow passes to a LOCAL composite action must be an input that action actually DECLARES. | only PRs touching: .github/workflows/*.yml, .github/actions/** |
| `api-tier-policy-guard` (645) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | always (every PR) |
| `arch-doc-guard` (784) |  | **NONE** | MAKE-REPORT-ONLY | 2026-05-11 9481ab911a feat(ws10): architecture-doc enforceme | Architecture-doc guard (S-AI-WS10). | only PRs touching: src/pipeline/**, src/core/coordinator.py, src/core/dispatcher*.py, src/ |
| `artifact-caveat-guard` (1600) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-27 b058724234 System review: correct the prop-gate f | A defect filed against a PRODUCER must reach the ARTIFACTS it produced. | only PRs touching: docs/research/exit-refinement-coverage.json, docs/claude/*-backlog.json |
| `async-route-blocking-guard` (1028) |  | **NONE** | MAKE-REPORT-ONLY | 2026-07-09 9c3987d0c5 web-api: eliminate event-loop-blocking | async-route blocking guard — keep synchronous work OFF uvicorn's event loop. | only PRs touching: src/web/api/**/*.py, scripts/ci/check_async_route_blocking.py |
| `attention-watch` (293) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-04 1fa57f0ab8 feat(ops): WORK-SYSTEM — attention blo | THE ATTENTION WATCH — the VM tells people when something needs them. | only PRs touching: scripts/ops/attention_watch.py, scripts/ops/work_report.py, scripts/ops |
| `automerge-trigger-guard` (1763) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-02 2816698ac4 automerge: gate the relay on the branc | `claude-pr-automerge` must never arm a PR that did not ask. | always (every PR) |
| `blocker-watch` (305) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-10 508c62674e BLOCKER-WATCH: detect stale blocks, un | BLOCKER-WATCH — does a row that SAYS it is blocked, or running, actually hold? | only PRs touching: scripts/ops/blocker_watch.py, scripts/ops/attention_watch.py, scripts/o |
| `cadence-liveness` (1959) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 308b75b6c4 E20 part 2: the three cost leaks, meas | FRESHNESS BELONGS IN CI, NOT ON A TIMER — because a timer can be the thing that did not fire. | always (every PR) |
| `candle-fixture-variance-guard` (1388) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-07 29820f9748 MI-157: the committed candle fixtures  | CI guard: no COMMITTED candle file may carry a degenerate price series. | always (every PR) |
| `canonical-db-resolver` (1038) |  | **NONE** | OPERATOR-PREFERENCE | 2026-05-16 69f07a6ff9 refactor(ops): canonical runtime_db_pa | CI guard: forbid new hand-rolled DB-path resolution in operator wrappers. | only PRs touching: \.py$\|\.sh$ |
| `canonical-doc-coherence` (1142) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | only PRs touching: CLAUDE.md, docs/**, .claude/**, .github/workflows/branch-protection-syn |
| `checklist-readers-guard` (379) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-08 fc60d3e90c CHECKLIST (b2 + c'): history/text read | checklist-readers-guard -- nothing reads the checklist monolith path directly. | only PRs touching: scripts/**/*.py, src/**/*.py, scripts/ci/check_checklist_readers.py |
| `checklist-store-guard` (437) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-07 171925b6ed CHECKLIST (a): per-row store loader +  | THE CHECKLIST STORE: one file per row, one loader, one generator. | only PRs touching: scripts/ops/checklist.py, scripts/ops/checklist_daily_measure.py, tests |
| `claim-basis-guard` (504) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-01 f0a4ac97d1 W2 (enforcement coherence): merge_grou | claim-basis-guard: a NEW backlog row asserting quantitative evidence must carry a parseable denominator (P2.5 of the 2026-07-31 full-system-audit plan; `BL-20260731-CLAIM-SURFACE-UNGUARDED` preventer P2). | always (every PR) |
| `collapsed-state-guard` (2128) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | only PRs touching: \.py$ |
| `corpus-row-floor-guard` (1419) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-25 5ef70fd42f feat(e4): one way to get candles, a re | CI guard: no COMMITTED candle file backing a rostered (symbol, timeframe) leg may be too thin to measure anything. | always (every PR) |
| `cron-failure-watch` (998) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-31 ed3e9ceb44 Workflow audit: make two hand-maintain | CI guard: every cron'd workflow must be watched by claude-run-failure-alert. | always (every PR) |
| `daily-brief-guard` (564) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-02 4f664aab8e MI-75: the DAILY BRIEF — generated, an | THE DAILY BRIEF — six fixed sections, per `.claude/skills/manager/SKILL.md` § "The daily brief" and `docs/plans/OPERATING-PLAN-2026-09-21.md` § 5.4: | always (every PR) |
| `diag-relay-render-guard` (2341) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-13 a45d36035e U15: a guard that is truncated away is | Render one diag-relay section so TRUNCATION CANNOT REMOVE THE FIELDS THAT CERTIFY THE RESPONSE. | only PRs touching: scripts/ops/diag_relay_render.py, .github/workflows/vm-diag-snapshot.ym |
| `diag-unit-allowlist-guard` (1183) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-01 f0a4ac97d1 W2 (enforcement coherence): merge_grou | Guard: every deploy/ systemd unit is diag-queryable or explicitly exempted. | always (every PR) |
| `diagnostic-provenance-guard` (1289) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | always (every PR) |
| `document-index-guard` (693) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-07 a6229afe90 document-index: drop an unused import  | document-index-guard — the register cannot silently stop being true. | always (every PR) |
| `exit-lever-map-guard` (834) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-13 3c4ea9052b research: record and CHECK the exit-le | Does every exit-relevant harness flag have a recorded verdict? | only PRs touching: scripts/backtest_*.py, docs/research/exit-lever-map.json, docs/research |
| `exit-mechanism-coverage-guard` (2362) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-16 41f9f0467b Does a leg's own module implement the  | Which exit MECHANISMS can each live leg actually use? | only PRs touching: config/strategies.yaml, src/units/strategies/*.py, src/runtime/*.py, sc |
| `grader-freshness` (1985) |  | **NONE** | MAKE-REPORT-ONLY | 2026-11-01 0a0fa4f294 grade-everything: grader registry + al | Is every grader's grade FRESH, and does it drive an action? (row GRADE-EVERYTHING-CONTINUOUSLY, 2026-11-01) | always (every PR) |
| `guard-liveness` (1993) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 308b75b6c4 E20 part 2: the three cost leaks, meas | A CHECK MUST BE ABLE TO SAY WHEN IT CANNOT SEE ITS SUBJECT, AND THAT MUST BE LOUD. | always (every PR) |
| `guard-selftest-coverage` (2442) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-10 92f44a226a MI-226: give four required guards a pr | Measure guard SELF-TEST COVERAGE over the guard POPULATION, not the registry. | always (every PR) |
| `harness-dispatch-no-fixture-default-guard` (1515) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-27 e618530e2c E7: wire the 10 orphan backtest harnes | CI guard: no E7 orphan-harness dispatch may invoke the 5,001-row smoke fixture. | always (every PR) |
| `harness-lever-coupling-guard` (1348) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-02 f3cbf1f799 ci(guard): harness-lever-map coupling  | Harness-lever-map coupling guard (BL-20260730-HARNESS-LEVER-MAP-COUPLING-GUARD). | always (every PR) |
| `impossibility-claim-guard` (1168) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 796aaf1650 P2 exit-verdict seam + impossibility-c | impossibility-claim guard — an "X cannot be done" claim must name what it checked. | always (every PR) |
| `json-extract-guard` (1524) |  | **NONE** | MAKE-REPORT-ONLY | 2026-07-31 9fa118778b Provenance: IB broker truth, close-tim | CI guard: every SQL ``json_extract`` must be ``json_valid``-guarded. | only PRs touching: \.py$\|\.sh$ |
| `json-notes-cap-guard` (1529) |  | **NONE** | MAKE-REPORT-ONLY | 2026-07-09 9a410c81ad notes-integrity: migrate 5 char-slice  | json-notes-cap guard — forbid the char-slice truncation of json.dumps(). | only PRs touching: src/**/*.py, scripts/ci/check_json_notes_cap.py |
| `lane-reconcile-guard` (2498) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 308b75b6c4 E20 part 2: the three cost leaks, meas | Reconcile MANAGER-CHECKLIST rows against the lanes that are actually alive. | only PRs touching: ^scripts/ops/lane_reconcile\.py$ |
| `layer-guard` (1534) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | layer-guard | only PRs touching: \.py$\|\.importlinter$\|requirements-dev\.txt$ |
| `lever-evidence-flag-guard` (2422) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 3d46f3a460 Settled-evidence flag on every reachab | Settled-evidence flag for `config/lever_reachability.json` — is a reach-share verdict SETTLED, or is it a point estimate over a sample too small to grade? | only PRs touching: config/lever_reachability.json, scripts/ops/lever_evidence_flag.py |
| `lever-reachability-guard` (2407) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-16 ca81c51251 M31 P1+P2: position telemetry, and a g | M31 P1 — a declared R-threshold exit lever must be REACHABLE under its own TP cap. | only PRs touching: config/strategies.yaml, config/lever_reachability.json, scripts/ci/chec |
| `lever-wiring-guard` (1364) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-20 5f9fddc709 Exit-path coverage, and the market-sid | Can every shipped exit lever be RUN, GRADED, and SEEN? | only PRs touching: src/units/strategies/*.py, src/runtime/exit_levers.py, scripts/research |
| `lifecycle-plan-guard` (874) |  | **NONE** | MAKE-REPORT-ONLY | 2026-11-07 f8c809d269 ml: per-model lifecycle plans + zero-C | lifecycle-plan-guard: every in-population model has a plan; every plan's commands resolve. | only PRs touching: ml/**, scripts/ci/check_lifecycle_plans.py, scripts/ops/seed_lifecycle_ |
| `manager-scope-guard` (1911) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-03 1822a30f12 MI-95: the manager session only manage | A manager commit that does a worker's item FAILS — named by commit and path. | always (every PR) |
| `manifest-scope-constants` (2298) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | only PRs touching: ml/configs/*.yaml, ml/datasets/**, ml/trainers/**, scripts/ci/check_man |
| `matrix-corpus-agreement` (1081) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-14 2091d57fc2 M20: the lever-OFF arm finally ran — a | matrix-corpus-agreement — a coverage cell must not silently contradict the corpus. | only PRs touching: docs/research/exit-refinement-coverage.json, docs/research/m20-sweep-co |
| `mfe-parity-instrument-guard` (2594) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-17 50ceed41da M31 P4: ship + run the backtest↔live M | M31 P4 — backtest<->live MFE parity. | only PRs touching: scripts/research/m31_mfe_parity.py, scripts/research/m31_harness_mfe_di |
| `ml-registry-consistency-guard` (1688) |  | **NONE** | MAKE-REPORT-ONLY | 2026-11-09 43d993d7f3 ML registry: served/candidate/overlay  | ml-registry-consistency-guard (lane ML-REGISTRY-CONSOLIDATE, 2026-11-09). A repo-consistency check, NOT a trading gate. | only PRs touching: config/strategies.yaml, config/overlay_policy.yaml, config/accounts.yam |
| `new-table-wiring-guard` (1575) |  | **NONE** | MAKE-REPORT-ONLY | 2026-06-21 29b9bc64e7 rules: make the canonical-compliance g | Guard against new persistent tables that aren't wired to a source of truth. | only PRs touching: **/*.py, **/*.sql |
| `news-feed-coverage-guard` (1539) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 bb5203aeee fix(news+risk): derive news feeds from | news-feed-coverage-guard: every traded symbol must resolve to a DECLARED news-feed disposition — never a silent fallthrough to macro-only. | only PRs touching: config/instruments.yaml, config/news_feeds.yaml, config/accounts.yaml,  |
| `operator-owed-guard` (521) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-26 7603112722 Operator-owed work gets a register, an | operator-owed guard — a question handed to the operator may not be CARRIED FOREVER. | always (every PR) |
| `pipeline-guard` (474) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-21 53436a1749 A7 part one, the close-out contract, t | THE FOLLOW-THROUGH PIPELINE — the thing that pulls work to a finish. | always (every PR) |
| `provenance-consumer-guard` (2456) |  | **NONE** | MAKE-REPORT-ONLY | 2026-07-30 08affd71d3 provenance: root-cause the Bybit scalp | CI guard: a provenance signal must have a CONSUMER, not just writers. | only PRs touching: \.py$ |
| `push-back-trigger` (270) |  | **NONE** | KEEP | 2026-09-29 57e2e80aa2 ci: training-rerun-5m push trigger mai | Fail a workflow that pushes back to its triggering ref while triggered on an unfiltered `push`. | only PRs touching: .github/workflows/*.yml, .github/workflows/*.yaml, scripts/ci/check_pus |
| `pytest-skip-attribution-guard` (755) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-12 4636c27aaf MI-280: pytest-run says WHICH tests sk | A green `pytest-run` reports `N skipped` and NOTHING about which N. | always (every PR) |
| `redate-guard` (428) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-08 2a70d36753 REGISTER-TOOLING: pipeline stale-snaps | redate-guard -- a re-dated pipeline item must carry a NEW OBSERVATION. | only PRs touching: docs/claude/work/pipeline/**, scripts/ci/check_redate.py, scripts/ops/p |
| `research-queue-autonomy-selftests` (1494) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-29 ecca21e0e1 research-queue: the queue refills, dis | Keep the research queue full WITHOUT a session: expand pre-registered template families into concrete queue units, deduped, deterministic. | always (every PR) |
| `research-queue-decision-rule-guard` (2071) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-25 6dc23d0b93 C1 + E6: decision_rule guard for the r | Every NEW research-queue unit pre-registers a `decision_rule` — or it holds. | only PRs touching: research/queue/** |
| `research-queue-design-fields-guard` (2093) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-28 e3c6f9a6c3 Research: shared intervention control  | Every NEW research-queue unit declares its practice precedent; every NEW intervention test its controls. | only PRs touching: research/queue/**, research/templates/**, research/programmes/**, scrip |
| `research-queue-dispatch-liveness` (2008) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-28 61b97cd024 RQ-OPS-2: root-cause + fix research-qu | research-queue-dispatch's OWN liveness, graded from a committed receipt. | always (every PR) |
| `research-queue-id-bands` (1458) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-08 90eca9908b feat(research): disjoint RQ id bands + | research-queue-id-bands -- a unit a PR ADDS must have a free id, in the right band. | only PRs touching: research/queue/**, scripts/ci/check_research_queue_id_bands.py, scripts |
| `research-results-guard` (2024) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 73cb5f57e9 E5: one result schema, one committed l | ONE result record, in ONE schema, in ONE committed location — R1 made executable. | only PRs touching: research/results/**, scripts/research/research_result.py, scripts/resea |
| `research-script-run-guard` (1436) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-28 f93762b8ee research: token-free runner (research- | The brain of ``research-script-run.yml`` — run ONE queue unit's declared command(s) on a GitHub runner and derive the result record from what it wrote. | always (every PR) |
| `research-tooling-selftests` (589) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-02 b9fbf95aab notify: the ping body was silently dro | Every row in the ping queue must render to more than its event label. | always (every PR) |
| `research-workflow-landing-guard` (2055) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-27 816dc482e7 C2: land dukascopy-span-probe through  | Every research-PRODUCING workflow either lands durably, or says why not. | always (every PR) |
| `reset-protocol-guard` (447) |  | **NONE** | MAKE-REPORT-ONLY | 2026-11-02 0f97323695 feat(ops): weekly reset protocol (conf | The weekly reset protocol's machinery (operator, 2026-11-02). | always (every PR) |
| `retired-backlog-paths` (327) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-29 c602f7a65c FIX-SA-09: correct stale pipeline para | retired-backlog-paths — no live `.claude/` instruction may name a retired register. | only PRs touching: .claude/**, scripts/ci/check_retired_backlog_paths.py |
| `roadmap-status-glyph-guard` (1191) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-01 c42f5f6c49 roadmap-backlog 2026-08-01: ready-now  | Guard: every ``## Milestone Roadmap`` status cell leads with a canonical glyph. | only PRs touching: ^ROADMAP.*\.md$ |
| `ruff-lint` (2485) |  | **NONE** | KEEP | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | ruff-lint | only PRs touching: \.py$\|ruff\.toml$\|requirements-dev\.txt$ |
| `secret-scan` (2490) |  | **NONE** | KEEP | 2026-04-27 3c82d8aec6 docs(claude): add lean Claude Code wor | CI-THROUGHPUT-20261029: 379 s whole-tree (MEASURED). On a PR scan the files the diff touches; push / merge_group / dispatch / schedule / --all keep the FULL tree scan. | always (every PR) |
| `selftest-wiring-guard` (2332) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-17 752f8866f9 Guard the guards, keep probes out of t | Every registered guard self-test must actually RUN in CI — proven by resolving the covering path, never by finding a name somewhere. | always (every PR) |
| `signal-catalog-guard` (118) |  | **NONE** | MAKE-REPORT-ONLY | 2026-10-08 ad777b888d SIGNAL-CATALOG: input catalog + signal | signal-catalog-guard — every input the system reads must have a catalog entry. | only PRs touching: docs/reference/signal-catalog.yaml, scripts/ci/check_signal_catalog.py, |
| `silent-empty-guard` (2516) |  | **NONE** | MAKE-REPORT-ONLY | 2026-05-10 e37aa4bffa S-067 CP-4 — silent-empty CI guard for | S-067 CP-4 — guard against new silent-empty error paths in diffs. | only PRs touching: \.py$\|\.ya?ml$\|\.sh$ |
| `skills-index` (1013) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-31 ed3e9ceb44 Workflow audit: make two hand-maintain | CI guard: docs/claude/INDEX.md must name every skill, and invent none. | always (every PR) |
| `soak-registered-guard` (513) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-02 eaef9821de MI-61: a soak must alarm — a threshold | Every soak log must be REGISTERED with an alarm, or named in a dated debt list. | always (every PR) |
| `spend-meter-guard` (544) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-22 9e9fb3a818 A1: the spend meter — and it refuses t | A1 — THE SPEND METER: usage against the WEEKLY PLAN ALLOWANCE, plus per-lane dollars. | always (every PR) |
| `stale-in-flight` (281) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-11 6d5556101f MI-236: grade whether the register sup | MI-236 — refuse a diff that adds an ``in_flight`` row the register cannot support. | only PRs touching: docs/claude/work/MANAGER-CHECKLIST.json, docs/claude/work/checklist/**, |
| `symbol-resolver-guard` (208) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-24 efb150cf3a E42: ONE shared symbol resolver — five | symbol-resolver-guard — the controls for ``src.config.symbol_sets``. | only PRs touching: src/config/symbol_sets.py, scripts/ci/check_symbol_resolver.py, src/mai |
| `test-schema-fidelity-guard` (1206) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-20 b9adb01154 Audit the audit: rewrite full-system-a | A test fixture may not declare a money-table column production does not have. | always (every PR) |
| `timestamp-comparison-guard` (2550) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-07 910e3163da ci: consolidate 30 per-guard workflows | Failure-path self-tests for the CI guards that carry one. | always (every PR) |
| `trainer-capture-watch-guard` (916) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-03 5d95739840 MI-81: an alarm on the trainer's forwa | IS THE TRAINER CAPTURE WATCHER ACTUALLY RUNNING? | always (every PR) |
| `trainer-heavy-lock-guard` (2467) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-16 7aa293daca M20 exit-refinement coverage: close th | Every heavy trainer entrypoint must acquire the shared heavy-job queue. | only PRs touching: ^scripts/(ml\|research)/.*\.py$ |
| `training-population-guard` (2558) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-04 bb7ef3b8ad docs(roadmap): full roadmap review + p | training-population guard — the "no decision head silently trains live-only" gate. | always (every PR) |
| `trend-engine-convergence-guard` (2576) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-08 1b7a717c2f Two backtest_trend.py are two ENGINES: | Convergence GUARD: there must be exactly ONE trend-harness engine. | always (every PR) |
| `workflow-actor-guard` (260) |  | **NONE** | KEEP | 2026-09-27 9a9f9e7d76 fix: CA-A10-402 failed-unit gate, CA-A | CI guard: an `issues:`-triggered, secret-holding workflow must gate on WHO opened the issue, not on the label alone (FIX-CA-16 / `CA-A13-gpu-burst-actor-guard`). | only PRs touching: .github/workflows/*.yml, .github/workflows/*.yaml, scripts/ci/check_wor |
| `workflow-catalog` (762) |  | **NONE** | MAKE-REPORT-ONLY | 2026-08-21 e6327f7797 ci: make the workflow catalog's comple | CI guard: the workflow catalog must be complete, and must not invent files. | always (every PR) |
| `workflow-push-target-guard` (1251) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-13 d9d2c0c109 guard: a workflow must not push straig | workflow-push-target-guard — a workflow must not push straight at a protected branch. | always (every PR) |
| `workflow-trigger-reachability` (863) |  | **NONE** | MAKE-REPORT-ONLY | 2026-09-02 f6740744a6 MI-66: enact the operating-layer inven | CI guard: a workflow's ``on.push.branches`` must name branches that EXIST. | always (every PR) |
| `writer-conformance-guard` (2610) |  | **NONE** | MAKE-REPORT-ONLY | 2026-06-17 22a292befc WC-6: writer-conformance CI guard (no  | WC-6 — guard against new non-canonical canonical-store writers in diffs. | only PRs touching: **/*.py, **/*.sql |
| `claude-judgments-guard` (407) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-26 daf3bdb6d1 CJ-2-DATASET: claude_judgments point-i | claude-judgments-guard: manifest lint for the `claude_judgments` family (CJ-2). | only PRs touching: ml/configs/**, ml/datasets/families/claude_judgments.py, scripts/ci/che |
| `desk-records-guard` (397) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-25 ae7eef93ed feat(desk): DESK-0-SCHEMA packet v3 +  | desk-records-guard -- validates the trading-desk records against comms/schema/desk_*.schema.json. | only PRs touching: comms/desk/**, comms/schema/desk_*.schema.json, scripts/ci/check_desk_r |
| `family-retirement-guard` (1469) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-25 b8d1d5517c research: family retirement needs a re | family-retirement-guard -- a FAMILY (an idea) cannot be retired without a review record. | only PRs touching: research/**, docs/plans/ml-plan-items.yaml, docs/research/programmes/** |
| `grading-freshness` (1975) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-09-29 680265816b JC-SA-01: resume closed-trade grading  | The GRADED hop of the trade pipeline must not go quiet — JC-SA-01 (2026-09-29). | always (every PR) |
| `guard-glob-coverage-detector` (982) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-08-23 9544ced3e1 Retune the stop instead of refusing th | Is each guard TRIGGERED by every file its check actually READS? | always (every PR) |
| `infra-workflows-single-owner` (1661) |  | VERBATIM | KEEP | 2026-11-05 4154bd3bff ci: B6 dispatcher lands without holdin | The detector is report-only; its --self-test step blocks a merge if the detector stops firing on its planted controls. infra-workflows-single-owner: REPORT-ONLY. "Which workflows are money-path ops" has ONE owner. | only PRs touching: .github/workflows/*.yml, scripts/research/research_compute.yaml, script |
| `live-review-records-guard` (387) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-25 e46c8f0a5e LTR-3 (+LTR-2): live-trade-review skil | live-review-records-guard -- validates comms/live_review/{reviews,outcomes}.jsonl. | only PRs touching: comms/live_review/**, comms/schema/live_review.schema.json, scripts/ci/ |
| `manager-pacing-guard` (2506) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-18 fd078e95f7 feat(manager): one operating loop ever | Guard: the manager's pacing doctrine stays the operating loop, not the one it replaced. | always (every PR) |
| `mandate-autoland-guard` (1841) |  | PARAPHRASE | KEEP | 2026-09-26 b9d7116df7 R16: the mandate auto-land route for a | The ONE route by which a PR lands ITSELF while touching a real-money roster. | always (every PR) |
| `pr-landing-guard` (1794) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-09-03 832523d0a5 MI-88: Tier-1 work lands itself, and a | Every PR declares its TIER and how it intends to LAND — and the declaration is checked. | always (every PR) |
| `programme-coverage` (1482) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-16 2e7b6c3392 research: programme coverage guard, th | Programme coverage: does every question a research programme PLAN asks have a node in its machine-read tree (research/programmes/<NN>-*.yaml)? | only PRs touching: docs/research/programmes/**, research/programmes/**, scripts/research/p |
| `review-followthrough` (317) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-28 936326d7cb REVIEW-FOLLOWTHROUGH: per-review follo | REVIEW FOLLOW-THROUGH — does what a review files actually get DONE? | only PRs touching: scripts/ops/review_followthrough.py, scripts/ops/pipeline.py, src/runti |
| `roadmap-map-guard` (417) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-11 fc906cdbe0 Roadmap loop: live roadmap, roadmap_ma | THE ROADMAP LOOP'S CHECKABLE ARTEFACT: milestone <-> checklist row <-> queue unit. | only PRs touching: docs/roadmap/**, ROADMAP.md, docs/claude/work/checklist/**, research/qu |
| `schedule-guard` (581) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-09-22 429c3eb623 A9: the work schedule, served live fro | THE WORK SCHEDULE — renders what already exists, on the operator's page. | always (every PR) |
| `stated-population-guard` (888) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-08-26 da5a7d6d90 Session-start mechanism, the vwap live | A quantitative claim in a doc must state its population. | always (every PR) |
| `unwired-artifact-guard` (1224) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-08-20 b9adb01154 Audit the audit: rewrite full-system-a | Find CAPABILITIES that were built and never wired to anything that runs them. | always (every PR) |
| `workflow-vm-literal-guard` (1448) |  | PARAPHRASE | MAKE-REPORT-ONLY | 2026-10-15 235d506395 HOLD (Tier 2, canary-gated): VM addres | workflow-vm-literal-guard -- no literal VM address in .github/workflows/**. | always (every PR) |

### Proposed by the w9 lane (report-only, unmerged) (4)

#### `W9-ML-ADVISORY-SCOPE-GUARD` (RM)

- **Where:** `scripts/ci/report_w9_gates.py (branch claude/w9-gate-reports, PR #25289; NOT on main at audit time)` · also `docs/reviews/2026-11-12-w9-gate-breakdown.md`
- **Blocks:** PROPOSED, built as a REPORT ONLY (never exits 1). Would flag: ML influence (advisory downsize, exit_head close, or a trend_vol cell) on a real-money/prop roster leg without a Gate-2 evidence record.
- **Added:** 2026-11-12 341a2671ae (branch, unmerged)
- **Operator authorization (VERBATIM):** VERBATIM (report form only): operator, decisions page w9, 2026-11-12: "Build them as reports only (no gate)"; "I want a break down of each one so that I can decide on each gate if its necessary or not." No authorization to make it blocking.
- **Hits, last 14 days:** 0 of 9 risk-bearing legs at HEAD; 0 of 33 config commits 2026-10-29..11-12 (measured by the w9 lane, report_w9_gates.py --history 60)
- **Cost of removing it:** As a report it blocks nothing; per-check false-block cost is in the w9 breakdown doc.
- **Recommendation: MAKE-REPORT-ONLY.** It is already a report; the operator decides only whether it should ever become blocking (w9 lane owns the breakdown).
- **Question:** Keep this gate? PROPOSED, built as a REPORT ONLY (never exits 1). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `W9-PROP-GATE-RECOST-AND-FLOOR` (RM)

- **Where:** `scripts/ci/report_w9_gates.py (branch claude/w9-gate-reports, PR #25289; NOT on main at audit time)` · also `docs/reviews/2026-11-12-w9-gate-breakdown.md`
- **Blocks:** PROPOSED, built as a REPORT ONLY (never exits 1). Would flag: A prop (account, leg) routing that fails the registered breach floor / worst-seed EV (RULE-P5-GATE-BRK-PER-LEG-V2).
- **Added:** 2026-11-12 341a2671ae (branch, unmerged)
- **Operator authorization (VERBATIM):** VERBATIM (report form only): operator, decisions page w9, 2026-11-12: "Build them as reports only (no gate)"; "I want a break down of each one so that I can decide on each gate if its necessary or not." No authorization to make it blocking.
- **Hits, last 14 days:** 3 of 9 prop routings at HEAD (all ml_entry, all carry the operator baseline exception 2026-11-08); 24 of 33 commits had >=1 hit (measured by the w9 lane, report_w9_gates.py --history 60)
- **Cost of removing it:** As a report it blocks nothing; per-check false-block cost is in the w9 breakdown doc.
- **Recommendation: MAKE-REPORT-ONLY.** It is already a report; the operator decides only whether it should ever become blocking (w9 lane owns the breakdown).
- **Question:** Keep this gate? PROPOSED, built as a REPORT ONLY (never exits 1). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `W9-RM-AM-STANDARD-GUARD` (RM)

- **Where:** `scripts/ci/report_w9_gates.py (branch claude/w9-gate-reports, PR #25289; NOT on main at audit time)` · also `docs/reviews/2026-11-12-w9-gate-breakdown.md`
- **Blocks:** PROPOSED, built as a REPORT ONLY (never exits 1). Would flag: A real-money leg added without a trail and an exit-coverage matrix row.
- **Added:** 2026-11-12 341a2671ae (branch, unmerged)
- **Operator authorization (VERBATIM):** VERBATIM (report form only): operator, decisions page w9, 2026-11-12: "Build them as reports only (no gate)"; "I want a break down of each one so that I can decide on each gate if its necessary or not." No authorization to make it blocking.
- **Hits, last 14 days:** 2 of 9 legs at HEAD (ml_entry, ml_entry_eq_struct: no trail by design); 25 of 33 commits had >=1 hit (measured by the w9 lane, report_w9_gates.py --history 60)
- **Cost of removing it:** As a report it blocks nothing; per-check false-block cost is in the w9 breakdown doc.
- **Recommendation: MAKE-REPORT-ONLY.** It is already a report; the operator decides only whether it should ever become blocking (w9 lane owns the breakdown).
- **Question:** Keep this gate? PROPOSED, built as a REPORT ONLY (never exits 1). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `W9-LEVER-LIVE-CONSUMER-PARITY`

- **Where:** `scripts/ci/report_w9_gates.py (branch claude/w9-gate-reports, PR #25289; NOT on main at audit time)` · also `docs/reviews/2026-11-12-w9-gate-breakdown.md`
- **Blocks:** PROPOSED, built as a REPORT ONLY (never exits 1). Would flag: A harness-tested exit lever key that nothing on the live path reads.
- **Added:** 2026-11-12 341a2671ae (branch, unmerged)
- **Operator authorization (VERBATIM):** VERBATIM (report form only): operator, decisions page w9, 2026-11-12: "Build them as reports only (no gate)"; "I want a break down of each one so that I can decide on each gate if its necessary or not." No authorization to make it blocking.
- **Hits, last 14 days:** 3 of 30 lever keys at HEAD (2 probably false positives); history not replayed (measured by the w9 lane, report_w9_gates.py --history 60)
- **Cost of removing it:** As a report it blocks nothing; per-check false-block cost is in the w9 breakdown doc.
- **Recommendation: MAKE-REPORT-ONLY.** It is already a report; the operator decides only whether it should ever become blocking (w9 lane owns the breakdown).
- **Question:** Keep this gate? PROPOSED, built as a REPORT ONLY (never exits 1). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

### Platform (not repo code) (7)

#### `PLAT-CLASSIFIER-INTERFERE-WITH-WORKLOADS` (RM)

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Interfere With Workloads": refuses restarting, stopping or altering running services/jobs.
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** hit on 2026-11-12 per the manager dispatch; not otherwise measured
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Interfere With Workloads": refuses restarting, stopping or altering running services/jobs. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-CLASSIFIER-REAL-WORLD-TRANSACTIONS` (RM) · trigger case

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Real-World Transactions": refuses tool calls a session makes that place, change or close real trades or write live-review rows that drive them (hit in the trigger case: live-review row writes for breakout_2).
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** at least 1 on 2026-11-12 (trigger case, manager report); not otherwise measured: refusals are not logged to the repo
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Real-World Transactions": refuses tool calls a session makes that place, change or close real trad *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-CLASSIFIER-EXTERNAL-SYSTEM-WRITES`

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "External System Writes": refuses writes to external services (APIs, other repos, messaging).
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** hit on 2026-11-12 per the manager dispatch; not otherwise measured
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "External System Writes": refuses writes to external services (APIs, other repos, messaging). *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-CLASSIFIER-IRREVERSIBLE-DELETION`

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Irreversible Deletion": refuses deleting data, branches or files that cannot be recovered.
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** hit on 2026-11-12 per the manager dispatch; not otherwise measured
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Irreversible Deletion": refuses deleting data, branches or files that cannot be recovered. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-CLASSIFIER-MERGE-WITHOUT-REVIEW`

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Merge Without Review": refuses a session squash-merging a PR it did not have reviewed; the operator added allow rules for the manager (2026-10-27, 2026-11-08).
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** not measured; already narrowed by operator allow rules
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Merge Without Review": refuses a session squash-merging a PR it did not have reviewed; *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-CLASSIFIER-SELF-MODIFICATION`

- **Where:** `Claude Code harness (Anthropic). Configured by the operator through permission rules in .claude/settings.json (permissions.allow; currently 30 entries)` · also `.claude/settings.json`
- **Blocks:** Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Self-Modification": refuses a session editing its own permissions/settings/hooks (e.g. .claude/settings.json) or bypassing a guard.
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned. Earlier operator-added allow rules exist for related refusals: merge-claim touch (2026-10-26 ~19:40Z), gh api merge/ready_for_review ("Make sure it's in the general settings, not just for this session", 2026-10-27 ~11:40Z), manager merges ("Allow manager merges (Recommended)", 2026-11-08); recorded in .claude/settings.json permissions._comment.
- **Hits, last 14 days:** hit on 2026-11-12 per the manager dispatch; not otherwise measured
- **Cost of removing it:** Not removable from the repo. Narrowing it is done by an operator-written allow rule for the exact command; a session cannot write that rule itself (editing .claude/settings.json is itself refused as Self-Modification).
- **Recommendation: OPERATOR-PREFERENCE.** The operator decides which exact commands get an allow rule in .claude/settings.json; no repo change can remove the classifier.
- **Question:** Keep this gate? Claude Code auto-mode safety classifier (PLATFORM-OWNED, not repo code) category "Self-Modification": refuses a session editing its own permissions/settings/hooks (e.g. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

#### `PLAT-SCHEDULED-TASK-HOURLY-MIN`

- **Where:** `claude.ai scheduled tasks (create_trigger): "Minimum interval is normally hourly (some projects allow shorter)"`
- **Blocks:** A recurring scheduled task cannot fire more often than hourly, so a wake/poll loop (e.g. a desk or live-review wake) is limited to once an hour per task.
- **Added:** platform behaviour; not added by any repo commit
- **Operator authorization (PLATFORM):** n/a -- platform-owned
- **Hits, last 14 days:** not measured
- **Cost of removing it:** Not removable from the repo; the platform names a per-project override ("some projects allow shorter").
- **Recommendation: OPERATOR-PREFERENCE.** Only the operator can ask for a shorter per-project minimum.
- **Question:** Keep this gate? A recurring scheduled task cannot fire more often than hourly, so a wake/poll loop (e.g. *(KEEP / REMOVE / MAKE REPORT-ONLY)*

## Probes recorded, not gates

These were looked for and are recorded so that a negative has a denominator. They are not in the JSON inventory.

- `GATE-TEST-ORDER-BYPASS-NOTE`: (Not a refusal) packages with meta.is_test bypass risk gates and sizing; listed for completeness since it is the only gate bypass.
- `GATE-STALE-SIGNAL-DEDUPE-NOTE`: Probe result: no separate stale-signal-age drop on the entry path found in pipeline.py/coordinator beyond bar-close debounce, closed-bar decision frames (builders use closed bars) and market-closed gating; I did not exhaustively read intent_multiplexer.py / order_bridge.py. NOT FINISHED.
- `HEALTH-AND-RECOVERY-TIMERS`: Watchdog timers restart a dead trader/web-api/gateway; I found no ExecCondition/Condition* skip on them (only deploy/ict-ib-gateway-reset.service:26 has a ConditionPathExists). They DO NOT refuse trading; unit details not read line by line.
- `ACTIONS-HOURLY-FIRE-LIMIT-NOT-IN-CODE`: No code enforcing an Actions cron 'hourly fire limit' was found; the only hourly-granularity code is digest_due.py (a digest rate limiter) and update_trigger/create_trigger tool docs (outside the repo, harness-level).

## Coordination

- **w9 lane.** The w9 lane (`session_01AFoLuMA86vehmpLpDfR3LP`, PR #25289, branch `claude/w9-gate-reports`) built its four candidate gates as reports.
  - They are rows `W9-*` here, pointing at its breakdown `docs/reviews/2026-11-12-w9-gate-breakdown.md` rather than repeating it.
  - Neither lane duplicates the other's numbers.
- **Gates approved earlier.** On 2026-10-29 the operator approved four gates to stay (row `NO-NEW-GATES-RULE`): the E57 research-queue merge hold, the ML-consumer refusal, lane $ ceilings with the 2-build-lane cap, and the research dispatcher's per-tick caps. Their rows carry that record.
  - The writers/VM reader found **no code** enforcing the 2-build-lane cap; lane ceilings exist only as a report (`lane_reconcile.py`).
