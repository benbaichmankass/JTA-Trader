# Account capability matrix — can the system itself manage a position, with no human?

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — it was authored 2026-11-11 (row CAPABILITY-MATRIX-LIVE) from code read at `f0b9698bbf`.**
>
> Row `CAPABILITY-MATRIX-LIVE` (operator, 2026-11-11). Read-only analysis, Tier 1. **Gates this adds or changes: none.** The guard in § 6 is a
> PROPOSAL only; nothing in this file is enforced.

**Population.** Every account in `config/accounts.yaml` with a non-empty `strategies:` roster, re-parsed 2026-11-11 from the checkout at
`origin/main` `f0b9698bbf` (11 accounts; `ib_live`, `oanda_practice`, `breakout_1` have empty rosters and are out). Re-parse, never quote.

**How a cell is graded.** `yes` = code does it AND a named test proves the code (a test proves code, not the venue). `yes (live)` = also a
recorded live event in a checklist note. `code` = code + test, no live event found. `gap` = no code path reaches it. `n/a` = the system never
creates the thing (stated with its reason). **`UNVERIFIED`** = could not look. **Diag reads are 401 until the operator resets the token, so no
journal/alert event was read this session**: every "live" proof below is a quote from a checklist note, not a fresh observation, and the
VM env switches (`PROP_EXECUTOR_MODE_<ACCT>`, `PROP_PHONE_MODE_BREAKOUT_2`) are UNVERIFIED. Merged ≠ deployed ≠ observed.

## 1. The five execution paths (what the 11 accounts actually run on)

| Account | class | path | Notes |
|---|---|---|---|
| `bybit_2` | real_money | **bybit** (`execute.py`, `order_monitor`) | |
| `bybit_1`, `bybit_portfolio` | paper (demo) | bybit | same code as `bybit_2` |
| `alpaca_live` | real_money | **alpaca** (`alpaca_client.py`, `alpaca_amend.py`) | |
| `alpaca_paper`, `alpaca_portfolio` | paper | alpaca | same code |
| `alpaca_options_paper` | paper | **alpaca options** (`alpaca_options_exec.py`, `options_lifecycle.py`) | a different, thinner client |
| `ib_paper` | paper | **IB** (`ib_client.py`) | |
| `tradeify_1` | prop | **prop VM, browser DXtrade** (`prop_executor.py`, `platform/dxtrade.py`) | `PROP_EXECUTOR_MODE_TRADEIFY_1` |
| `velotrade_1` | prop | **prop VM, DXtrade REST** (`platform/dxtrade_api.py`) | `PROP_EXECUTOR_MODE_VELOTRADE_1` |
| `breakout_2` | prop | **phone** (`phone_executor.py`, `phone_trail.py`, `phone_cancel.py`) | needs the phone on, powered, logged in |

All three prop accounts carry `exchange: breakout` in `accounts.yaml`, which in `clients.EXCHANGE_MANAGEMENT_CAPS` is `frozenset()`; their
management does not go through that registry at all (§ 5).

## 2. The matrix

Test file prefixes: `T/` = `tests/`. "LR" = `scripts/ops/live_review_apply.py` (`ACTION_PATHS`). "trail" = the account's own trail/monitor.

| Capability | bybit_2 (real) · bybit_1/portfolio (paper) | alpaca_live (real) · alpaca_paper/portfolio | alpaca_options_paper | ib_paper | tradeify_1 | velotrade_1 | breakout_2 |
|---|---|---|---|---|---|---|---|
| **open** | yes — `execute.py` order path; bracket at entry | yes — `AlpacaClient.place` (Market, day/gtc bracket, `alpaca_client.py:660`) | yes — `place_spread` / `place_single_option` (limit, day) | yes — `IBClient.place` (`MarketOrder` parent, `ib_client.py:1658`) | **yes (live)** — `prop_executor` → `place_bracket(arm=True)`; `T/test_prop_executor.py::test_place_bracket_armed_clicks_submit_exactly_once`; PROP-CANCEL-FIX note: LIMIT sell ticket `prop-manual-e6badec7ae10`, 2026-10-08 | **yes (live)** — `dxtrade_api.py::place_bracket`; `T/test_prop_platform_dxtrade_api.py::test_armed_place_is_exactly_one_post`; VELOTRADE-API-EXEC note: ticket `prop-manual-609ce9dd6f4f` filled 2026-10-11 | **yes (live)** — `phone_executor`; `T/test_phone_executor.py::test_live_go_without_report_is_journaled_placed_not_skipped`; PROP-TRAIL-PHONE note: ticket `prop-manual-29067b29bbad` |
| **amend SL** (tighten) | yes — `execute.modify_open_order` → `set_trading_stop` / `amend_order`; `T/test_ltmgmt_modify_wiring.py::test_modify_open_order_bybit_unchanged`; LR `bybit` | yes — `AlpacaClient.modify_protective`, `alpaca_amend.exec_trade_leg`; `T/test_ltmgmt_modify_wiring.py::test_modify_open_order_routes_alpaca`, `T/test_alpaca_amend.py::test_tighten_only_refuses_looser_and_equal` | **gap** — no SL exists (defined-risk debit structure); nothing to amend | yes — `IBClient.modify_protective` (cancel OCA + re-place); `T/test_ltmgmt_modify_wiring.py::test_ib_modify_cancels_resting_then_rearms_both_legs`; **LR: none (`other`)** | **code, unproven** — `prop_trail.run_trail_step` → `modify_bracket`, SL-only, ≤25% of stop distance (`ROLLOUT_GUARD`); `T/test_prop_trail.py::test_live_amends_one_bounded_sl_step_confirms_and_reports`. Every armed step refused from 2026-10-15 03:43Z (panel text `ETH/USD`); fix `228bb073` **deploy not observed** (row TRADEIFY-MODIFY-PANEL `landed_unproven`) | **yes, inferred** — `dxtrade_api.py::modify_bracket` (PUT + If-Match); `T/test_prop_platform_dxtrade_api.py::test_modify_sends_if_match_from_the_open_orders_read`; ticket 609ce9dd6f4f closed at a stop above its original SL (inference; no `trail_amend` line read). **No supported apply path from live review** (LR `prop_vm`: empty) | **yes (live)** — `phone_trail.request_sl_tighten`; `T/test_prop_phone_trail.py::test_amended_moves_resting_sl_and_next_plan_starts_from_it`; PROP-TRAIL-PHONE note: ticket 29067b29bbad SL 2281.25→2257.26, 2026-10-30 |
| **amend SL** (widen) | yes — LR `widen_sl` (monitor's modify seam) | **gap** — LR `alpaca` = `{close, move_tp}` only | gap (n/a) | **gap** (LR `other`) | **gap, deliberate** — adapter tighten-only by construction (`ModifyRollout`) | **gap, deliberate** — same | code (new 2026-11-09) — `request_sl_widen`; `T/test_prop_phone_trail.py::test_live_review_widen_reaches_the_phone`; no live use |
| **amend TP** | yes — LR `move_tp`; `T/test_live_review_trade_actions.py::test_move_tp_reaches_bybit_alpaca_and_phone` | yes — `alpaca_amend` TP leg; `T/test_alpaca_amend.py::test_tp_amend_moves_only_the_target_leg` | gap (no TP; closed by `close_structure`) | yes — `modify_protective` carries SL+TP; **LR: none** | **gap** — `TP_AMEND_SUPPORTED = False`, "the rollout guard refuses any TP change" (`dxtrade.py:8533`); `prop_trail._tp_step` skipped for the browser adapter (`prop_trail.py:31`) | **code** — `prop_trail._tp_step` → `modify_bracket(None, tp)`; `T/test_tp_revision_contract.py::test_prop_tp_capable_adapter_amends_tp_only_confirms_and_reports`; no live TP amend found. **No live-review path**; PROP-BRACKET-APPLY owns it | code — `request_tp_amend`; `T/test_prop_phone_trail.py::test_tp_amend_through_the_same_slot`; no live use |
| **close** | yes — `execute.close_open_position`; `T/test_flatten_bybit_position.py::test_apply_flattens_and_verifies`; LR `close`/`reduce` | yes — `AlpacaClient.close` (DELETE position, `qty` scoped); `T/test_flatten_alpaca_position.py::test_apply_flattens_and_verifies`; LR `close` only when the leg is the symbol's only open trade | yes — `close_structure` (`alpaca_options_exec.py:302`), used by the lifecycle close; `T/test_alpaca_options_exec.py` | yes — `IBClient.close`; `T/test_flatten_ib_position.py::test_apply_flattens_and_verifies`; **LR: none** | **gap for any automatic trigger** — `adapter.flatten` exists but is reached only by containment (`_repair_or_flatten`: naked/unbracketed position), the round-trip test and the operator-dispatched `breakout-login-check close-position-live`. Live review refuses `no_action_path:close` (`T/test_live_review_trade_actions.py::test_close_on_every_account_class`) | **gap** — same as tradeify (`flatten` = Bulk Close; `T/test_prop_platform_dxtrade_api.py::test_flatten_is_one_instrument_bulk_close`; roundtrip action only) | code — `phone_cancel.request_close`; `T/test_phone_cancel.py::test_live_review_close_reaches_the_phone_like_a_vm_account`; no live close found; a **reduce is not built** (reports `failed`) |
| **cancel an unfilled entry** | **n/a** — every Bybit entry is a Market order (`maker_entry.py` docstring, 1,411 fills); the post-only probe is demo + `claude_desk` only and has its own sweep/cancel (`sweep_maker_entries`) | **n/a** — entries are Market (`alpaca_client.py:660`); the extended-hours *limit* is a close, not an entry | **gap** — entries are day *limit* orders; no cancel method on `AlpacaOptionsExec`; relies on `day` expiry | **n/a** — parent is `MarketOrder` | **yes (live)** — `cancel_expired_resting`, `_supersede_resting`; `T/test_prop_executor.py::test_a_resting_entry_past_valid_until_is_cancelled_and_confirmed_by_reread`; PROP-CANCEL-FIX observed 2026-10-08 | **code** — same executor via REST `cancel_order` (DELETE); `T/test_prop_platform_dxtrade_api.py::test_cancel_retries_once_on_412`; no live VT cancel found | code — `phone_cancel.plan_cancels` (PHONE-ENTRY-CANCEL, 2026-11-09); `T/test_phone_cancel.py::test_expired_placed_entry_is_planned_with_its_four_facts`; no live use |
| **read positions** | yes — `account_open_positions` bybit branch; `T/test_bybit_raw_positions_accessor.py`, `T/test_bybit_position_book.py` | yes — `AlpacaClient.positions`, `account_open_positions`; shared-login scope filter | yes — `option_positions()` | yes — `IBClient.positions` | yes — `read_positions`; `T/test_prop_platform_dxtrade.py::test_positions_from_tables` | yes — REST `read_positions`; `test_reads_parse_the_spec_shapes` | yes — `positionsRead` in `account_status` → `phone_reconcile` |
| **read open orders** | yes — `account_bybit_open_orders`; `T/test_bybit_open_orders_accessor.py::test_full_mode_position_stop_is_captured` | yes — `account_alpaca_open_orders`; `T/test_diag_alpaca_open_orders.py` | **gap** — no open-orders accessor on `AlpacaOptionsExec` (grep: `account_alpaca_open_orders` is the equity client's) | yes — `account_ib_open_orders`; `T/test_diag_ib_open_orders.py` | yes (live) — `read_orders`; PROP-CANCEL-FIX journal "orders 1 / orders 0" | yes — REST `read_orders`; `test_reads_parse_the_spec_shapes` | **gap, server-side** — open orders read on-device only inside the cancel flow (`MainActivity.kt:1493`); the server posts positions + closed orders only. **Owned by PHONE-SELF-DIAGNOSE; not re-filed** |

Gating that can make a `yes` read `off` in practice (all UNVERIFIED — VM env/config not readable this session): `PROP_EXECUTOR_MODE_<ACCT>`
defaults to `read_only` and a typo also gives `read_only` (`prop_executor.py:78-96`); `PROP_PHONE_MODE_BREAKOUT_2`; per-account `apply_mode` in
`config/live_trade_review.yaml` (file default `apply`, `accounts: {}` — no per-account override at this commit) plus the mandate.

## 3. What the matrix says

1. **Real money (`bybit_2`, `alpaca_live`) has every capability that applies.** Their holes are (a) live-review `widen_sl` / partial on Alpaca
   (tracked: `LTR-ACTION-EXECUTOR-GAPS`) and (b) nothing measured here at the venue — every proof for these two is a unit test, no live event was
   re-read (diag 401).
2. **The prop accounts are where "basic" capabilities are missing or unproven.** No prop-VM account can be closed by the system except by
   containment or an operator-dispatched action; `tradeify_1` cannot move a TP; `tradeify_1`'s stop-trail steps were all refused from 2026-10-15 03:43Z until the fix merged (~11 h; fail_streak 11) and the fix
   is not observed in production; `velotrade_1` and `breakout_2` have cancel / TP / close code with **no live event** behind it.
3. **A `code` cell is not a capability** until a drill has run it once on the venue (OPERATING-PLAN § 2: "new mechanics prove themselves on ONE
   small trade"). Count of prop cells that are `code`/`unproven` and not `yes (live)`: tradeify SL, velotrade TP/cancel/close(gap), breakout_2
   widen/TP/close/cancel. That is the largest gap by money at risk.
4. **Paper accounts** (IB, options, Alpaca paper, Bybit demo): gaps exist (IB has no live-review path; options have no open-orders read,
   cancel or SL) but carry no real money.

## 4. History of each gap (git, full history fetched; 15,402 commits)

| Gap | Went live without it | Deliberate or never built? |
|---|---|---|
| **Prop VM: no automatic close; no live-review action** | `tradeify_1` wired 2026-10-01 (`24266cb0db`, dry_run) and live ticketing from ~2026-10-06; `velotrade_1` wired 2026-10-05 (`9ddf1ee042`), `VELOTRADE-GOLIVE` 2026-10-06. Prop executor first landed 2026-09-27/28 (`cd8a03d279`, `948adcc8ce`) with `place_bracket` + containment flatten only | **Deferred, in writing, 3 weeks after go-live.** `7968bc403a` (2026-10-26, LTR-ALL-ACTIONS) wrote `prop_vm: none yet (the VM executor reads only meta.sl_floor)` and filed row `LTR-ACTION-EXECUTOR-GAPS` (queued, no owner/due). Before that nothing recorded the decision — **it was never designed in, then named a gap when the live-review actions were built** |
| **Prop VM: widen SL** | same dates | **Deliberate.** `0b0ef36e91` (2026-10-03, #15693) rollout guard "tighten-only"; `49753acc69` (2026-10-03) prop trail "A stop is never loosened". A safety choice made *at* go-live, not a miss |
| **tradeify_1: no TP amend** | live ~2026-10-06 | **Deliberate and conditional.** `dxtrade.py` `TP_AMEND_SUPPORTED = False` ("flip only together with a measured TP-amend rollout step"); the TP-revision mechanism `9501bb5650` (2026-10-08, TP-doctrine B1) built the REST and phone paths and left the browser path off. No row owns the flip |
| **Phone (`breakout_2`): close / reduce / cancel / widen** | live ~2026-10-05/06 (`bf6e28cea6`, 2026-10-05, dry_run → live) | **Never built at go-live**; built 2026-11-09 (`7ecd2efaf5`, PHONE-ENTRY-CANCEL) *after* a stale limit sell rested following a strategy exit. Reactive, not designed in |
| **Alpaca live-review `widen_sl` / partial** | `alpaca_live` wired 2026-06-24 (`2b605a38c4`) | Alpaca tighten executor only landed 2026-10-25 (`62bda782ba`, AMEND-PARITY-ALL-ACCOUNTS). Partial close: **deliberately** not declared, with a measured reason (`clients.py` caps comment, corrected 2026-09-08) |
| **IB: no live-review path, no `order_status`** | `ib_paper` wired 2026-05-22 | Close + modify built 2026-06-16 (P3/S2). IB live-review is item (4) of `LTR-ACTION-EXECUTOR-GAPS`; paper only |
| **Alpaca options: no cancel / open-orders read / SL** | `alpaca_options_paper` wired 2026-06-27 (`bb86787c94`) | **Never built, never recorded** (no deferral line found; searched `cancel`, `open_orders`, `order` in `alpaca_options_exec.py` and `options_lifecycle.py`). Paper |
| **`breakout` caps declared empty** | `breakout` was already an `EXCHANGE_MAP` integration (a stub) by 2026-06-16 — the P5 audit calls it the undeclared gap | **Deliberate and papered over.** `c31e00567f` (P5, 2026-06-16) made CI demand a *declaration* and set `"breakout": frozenset()` to make the guard pass; the audit doc (`docs/audits/live-trade-management-contract-2026-06-16.md` § P5) records "`breakout` was the undeclared gap, now `frozenset()`". Prop trading went live 3.5 months later on a different executor that the registry never sees |

## 5. How we went live without knowing — the answer

There *is* a capability contract and a CI guard, from 2026-06-16 (`tests/test_ltmgmt_p5_contract_ci.py`, audit
`docs/audits/live-trade-management-contract-2026-06-16.md`). It failed to protect the prop accounts for four measured reasons:

1. **It checks that a declaration exists, not that the capability does.** `test_every_exchange_map_integration_declares_management_caps` is
   satisfied by `frozenset()` ("declares everything unsupported"); that is exactly what was done for `breakout`.
2. **The prop accounts never use the registry.** They run on `src/prop/*` executors outside `EXCHANGE_MAP` management, so a prop account can be
   `mode: live` with a registry that says it supports nothing, and nothing joins the two.
3. **The vocabulary is too coarse.** Ops are `modify, close, partial_close, order_status, open_positions`. There is no `amend_sl` vs `amend_tp`,
   no `cancel_entry`, no `open_orders`, and no *proof* column — so "TP cannot be set on velotrade" and "tradeify cannot move a TP" are not
   expressible.
4. **Nothing on the go-live path asks the question.** `accounts.yaml::mode: live` is flipped by the `set-account-mode` system-action;
   the promotion ladder's gates (OPERATING-PLAN § 2) test edge and mechanics-of-the-*trade*, and a prop leg's "mechanics proven" is satisfied by
   an entry + a fill. No record asked "can the system move or close this position with no human".

I found **no decision record in which anyone chose to go live without these capabilities.** The evidence is of omission plus one deliberate
safety choice (tighten-only). I am not asserting more than that: I did not read the operator's chat history.

## 6. PROPOSAL (not built): a rostered account must have the basic capabilities

**Gates this adds or changes:** adds one CI check (a gate). **Needs the operator's explicit OK; not built.**

* **What.** A new `scripts/ci/check_account_capabilities.py` + a declared file `config/account_capabilities.yaml`: for every account with a
  non-empty `strategies:` roster and `mode: live`, each of `open, amend_sl, amend_tp, close, cancel_entry, read_positions, read_open_orders`
  must be one of `{code: <file:function>, proof: <test id or system-action run id>}`, `{n/a: <reason>}`, or
  `{deferred: <checklist row id>, due: <date>}` where the row is live (not done/dropped) and unexpired.
* **What it refuses.** An empty `breakout`-style declaration; a cell with no proof and no row; a cell pointing at a missing test; a deferral
  whose row is dropped or past due.
* **What it does not do.** It never blocks turning a leg *off*, never touches `mode:` / `execution:`, never halts a pipeline, and a gap with a
  live row passes. It is a *declaration-must-be-honest* check, not an execution gate. `n/a` and `deferred` are first-class.
* **Cost / risk.** One YAML (~11 accounts × 7 cells), one script reusing `checklist_store` readers, one test; Tier-1. First run would fail on
  every `code`-only prop cell until each has a row — which this lane files — so it would land green.
* **Alternative with no new gate:** only extend `EXCHANGE_MANAGEMENT_CAPS` ops + generate this matrix from it (a report, not a check).
  Cheaper; still rots, as the registry did.

**Question for the operator:** *Do you want the capability-declaration check in § 6 added to CI (it would refuse a `mode: live` rostered account
with an undeclared or unproven basic capability), or the report-only alternative?*
