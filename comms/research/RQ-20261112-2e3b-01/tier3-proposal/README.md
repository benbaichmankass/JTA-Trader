# Tier-3 proposal: ml_entry `account_symbols` → population record (row ML-ENTRY-POPULATION-TEST)

**Not applied. AM-ML decides and merges.** Patch: `remove-bybit-account-symbols.patch`. It applies cleanly to this
branch at `cefd2fa`, after merging `main` (`git apply --check`). Regenerated after #25306 put breakout_2 on ice.

Gates this adds or changes: none. It leaves the traded set of every rostered account unchanged. It removes per-account
configuration; it adds no switch and no refusal.

## Evidence

[`RQ-20261112-2e3b-01`](../../../../research/queue/RQ-20261112-2e3b-01.yaml) registered its rule
`RULE-RQ20261112-2e3b-01-ENTRY-POPULATION` before any run. The population was frozen from the Bybit V5 snapshot
in [`../freeze/`](../freeze/). The graded run is `research-script-run` 43302779170, with output in
[`../43302779170/`](../43302779170/) and the record in `research/results/RQ-20261112-2e3b-01/43302779170.jsonl`.

| measure | value (MEASURED, frozen ml_decision_entry_v1, tau 0.10, decisions 2025-10-01..2026-10-31) |
|---|---|
| population | 51 Bybit USDT perps, out of 822 snapshot rows; filters F1–F5 fixed before the run |
| pooled mean net R / decision | **−0.0680** (SE 0.0098), n = 12,746, all 51 symbols traded |
| gross / cost per decision | +0.071 R / 0.139 R; each symbol charged its own fee + spread + impact + funding |
| bar | deflated holdout bar, n_tries 12: mean ≥ 1.66 × SE. **FAIL** |
| fresh symbols (never in training) | −0.0758, n 7,926, 30 symbols (reported) |
| reference symbols (in training) | −0.0551, n 4,820, 21 symbols (reported) |
| 5 bybit_2 coins | +0.0103, n 971, SE 0.036 (reported, never gating) |
| same decisions, flat c692 stack (11 + 3 + 1 bps/8h) | +0.0124 (reported). The flat stack is what made earlier reads look positive |
| baselines, same mechanics | always-long −0.162, always-short −0.139, matched random −0.142 (p95 −0.134) |

What this means: the model ranks better than random, but its gross selection edge is smaller than these symbols' real
costs. Rule point 4 applies: nothing widens, and the population that already passed stays. That population is the
c692-06 pooled pass, BTC/ETH/XRP/ADA/SOL.

## What the patch does

1. **`comms/ml_universe/ml_entry.json`** is written through `src/config/ml_universe.write_population`, the only writer.
   It holds two populations:
   - `RQ-20261101-c692-06`: pass, the 5 coins on venue bybit. This is the population that already passed.
   - `RQ-20261112-2e3b-01`: fail, 51 symbols. It adds nothing and removes nothing.
2. **`config/strategies.yaml`** loses the `bybit_2` and `bybit_portfolio` lines of `ml_entry.account_symbols`. A comment
   says why.
3. **The real-money safety fix, which is required.**
   - `src/core/coordinator._leg_account_scope` only built a scope for accounts named in the map, then did
     `_scope.get(account, [])`. Deleting the two lines alone would drop **every ml_entry package on bybit_2 and
     bybit_portfolio** with reason `leg_account_scope`.
   - `src/runtime/ml_entry_profile._accounts_for` had the same flaw.
   - The fix is a new `symbol_sets.scoped_leg_accounts(leg, scope)`: the map's accounts plus every account that rosters
     the leg. Both scope builders now use it.
   - The coordinator's scope cache also keys on the population records' mtimes.
   - For a leg with no record this changes nothing, because an extra account still resolves to `[]`.
4. **Guards move to the runtime view.** `check_roster_symbol_reachability` and `check_same_symbol_allocation` now call
   `leg_symbols(..., leg=<name>)`, so a record counts the way it does at run time.
5. **Tests.**
   - The old "no record exists" pin becomes "only ml_entry has a record, and it leaves every rostered account's set
     unchanged".
   - A new coordinator test proves `leg_account_scope('ml_entry')` still contains bybit_2 and bybit_portfolio with the
     5 coins.
   - Two tests move to the record-aware runtime call. One of them also had a stale `breakout_2` expectation from #25306, which is red on `main` too; it is corrected.

## How it was verified (scratch worktree with the patch applied)

- **Traded sets:** for every account that rosters ml_entry (bybit_2, bybit_portfolio, breakout_2, tradeify_1,
  velotrade_1, alpaca_paper; breakout_2 is on ice since #25306 with an empty roster), the set from `leg_symbols(cfg, acct, leg="ml_entry")` is identical before and after.
  bybit_1 now resolves to the 5 coins, but ml_entry is not on its roster, so the roster still decides.
- **Tests:** `pytest` on `test_ml_universe_record`, `test_ml_entry_all_accounts`, `test_ml_entry_adapter`,
  `test_ml_entry_alpaca_pool`, `test_paper_portfolio_accounts`, `test_coordinator_flow`,
  `test_coordinator_rejection_journal`, `test_desk_paper_accounts`, `test_same_symbol_head_to_head`,
  `test_slice_coordinator_dispatch` and `test_s008_coordinator` all passed.
  - **Not run locally:** `test_roster_symbol_union`, because the sandbox has no `ccxt`. CI runs it.
- **Guards:** `check_roster_symbol_reachability` OK, `check_same_symbol_allocation` clean (24 groups, same as main),
  `check_symbol_resolver` PASS, `check_strategy_status` OK.

## Not covered by this patch (still on the map, and still against the 11-04 rule)

- **Prop books** (`tradeify_1`, `velotrade_1`: ETH+SOL; `breakout_2` is on ice). The prop superset gate scored only that slice
  (`comms/prop_survival/ml_entry.json`). Their venue is `breakout`, so a Bybit-venue record would not reach them anyway.
  Removing their lines needs a prop-venue population record that the prop survival gate has scored. Owner row:
  `ML-UNIVERSE-RULE`.
- **`alpaca_paper`** (13 ETFs). The ETF population failed (a41f-01). Rule point 5 says a testing ML on the paper floor
  trades its pending test's population. The disposition is owned by dev-plan line `MLP-D3-ENTRY-ETF-ON-CRYPTO`, in W48.

## Revert

`git revert <merge>`. The map lines come back and the record goes. The traded set is the same either way.
