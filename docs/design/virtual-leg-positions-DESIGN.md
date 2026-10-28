# DESIGN (Tier-1 doc; build is Tier-2): virtual per-leg positions for intents held by the one-way book

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
>
> ## ⚠️ THIS IS A DESIGN. NOTHING HERE IS BUILT.
> Owning row: `VIRTUAL-LEG-POSITIONS` (`docs/claude/work/checklist/VIRTUAL-LEG-POSITIONS.json`). The operator approves the
> build at Thursday planning. No `src/`, config or order-path change ships with this document.

Lane `VIRTUAL-LEG-POSITIONS-DESIGN`, 2026-10-28, dispatched by the manager (`session_01AFoLuJi1vLTnYv9LbP6539`).

## 0. The decision this implements

Operator popup, 2026-10-28 ~20:15Z: **"Keep holding + record virtual trades".**

- The real book stays **one-way**. `FLIP_POLICY=hold` (`src/runtime/intents.py::_DEFAULT_FLIP_POLICY`) is unchanged.
- A leg whose intent is held because another leg owns the contract must still produce data: a **virtual per-leg position**.

The trigger case (manager dispatch): on `ib_paper`, the `mgc_pullback_1d` SHORT (trade 6673) holds the MGC contract, so the longs of
`ict_scalp_mgc_15m` and `mgc_trend_1h` are journalled `intent_noop:flip_suppressed_hold_policy` and leave no outcome. The same happens
on the Bybit crypto legs. The PRACTICE-REFRESH lane flagged the gap: *"the one-way book drops the opposing leg's intent and keeps no
virtual per-leg record"*.

This is the rule in [`docs/CLAUDE-RULES-CANONICAL.md`](../CLAUDE-RULES-CANONICAL.md) § "Off the trade path is not off the data path"
applied to a held intent. Holding keeps the intent off the trade path. Nothing decided to take it off the data path too.

## 1. What happens today (MEASURED from code on `main` @ `6e541866`)

1. `Coordinator.multi_account_execute` logs the package to `order_packages` with status `open` before dispatch
   (`src/core/coordinator.py`, `_log_new_order_package`, ~L1209). The row carries entry, SL, TP, strategy, symbol, direction and `meta`.
2. Per account, `compute_execution_delta` sees the desired side oppose the held side. Under `hold` it returns `action="noop"`,
   reason `flip_suppressed_hold_policy: desired <side> opposes current <side> (qty=…); holding for owner exit`
   (`src/runtime/intents.py` ~L2085).
3. The coordinator journals that noop with `log_rejection_to_journal(...)` (`src/core/coordinator.py` ~L2790). This writes a `trades` row
   with `status='rejected'`, `position_size=0`, `order_package_id`, the package's `entry_price` / `stop_loss` / `take_profit_1`, and
   `entry_reason = "REJECTED: intent_noop:flip_suppressed_hold_policy: … | <base entry_reason>"`
   (`src/units/accounts/execute.py::_log_trade_to_journal`).
4. It also appends an observe-only row to `runtime_logs/conflict_taxonomy_soak.jsonl` (`src/runtime/conflict_taxonomy.py`, the retired
   M26 P1 soak).
5. With no trade placed, the BUG-049 backstop terminalises the package: `order_packages.status='rejected'`,
   `close_reason='all_accounts_noop'` (`src/core/coordinator.py` ~L3470).

**So the inputs of a virtual position are ALREADY durable in the canonical store.** The package row has the bracket. The `trades`
rejection row names the account and the hold reason, and links to the package. What is missing is an **outcome**: nothing walks
that bracket forward on bars, and nothing grades it.

## 2. Practitioner precedent (R1 of `docs/reference/trading-and-model-practice-principles.md`)

- **Carver, subsystem positions** [S7, S9 in `docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md`; PRAC]. In *Systematic
  Trading* and on qoppac, each trading rule/instrument "subsystem" keeps its **own notional position**. The portfolio nets them into
  one traded position. Performance, forecast diagnostics and rule weights are computed on the **subsystem** series, never on the
  netted book. That way a rule that is netted out still has a track record. Our case is the discrete version: a leg's held intent is a
  subsystem position the book did not take.
- **Netting vs. hedging accounts** (MT5 / FX practice; PRAC). A *netting* account keeps one position per symbol. Strategy-level P&L on
  a netting account is reconstructed from **virtual (strategy-attributed) positions**, because the venue cannot report it.
- **Shadow/paper trading of a model** (shadow-mode literature, cited by `scripts/ml/fc_geometry_resolve.py`). A counterfactual exit is
  only **partially identified**. An unresolved one is reported **censored**, never marked-to-close. We adopt that rule as-is.

Declared **not novel**: the projection, the barrier walk and the cost stack all reuse existing repo primitives (§ 4).

## 3. Lifecycle of a virtual position

### 3.1 Opening

A virtual position opens for `(account_id, strategy_name, symbol)` when ALL of these hold:

1. A `trades` row has `status='rejected'` and `entry_reason LIKE '%intent_noop:flip_suppressed_hold_policy%'`, and its
   `order_package_id` resolves to an `order_packages` row with finite `entry`, `sl`, `tp`.
2. That leg has **no open virtual position** on that account. One position per leg, the same rule the leg follows when it trades.
3. That leg has **no open real trade** on that account (`trades.status='open'` for the same strategy/symbol/account).

- **Entry price**: the package's `entry`. If the package is a market-entry package, entry = the **open of the next bar after the hold
  timestamp**. This is the same convention the backtest harnesses use, so a virtual fill is never better than a real one could have
  been. `entry_basis` (`package_entry` | `next_bar_open`) is stamped on the row.
- **Entry time**: the `trades` row `timestamp` (the hold decision).
- **Dedupe**: a leg re-emits the same signal on later ticks while it is held (the package is terminalised every round). Every later
  held row with the same `signal_key` (`src/runtime/order_bridge.py::signal_key_for_package`: strategy + symbol + direction + entry/sl/tp
  + `meta.entry_time`), or any held row of the same leg while its virtual position is open, is **absorbed**. It is counted
  (`n_hold_rows`) but opens nothing. This is how §5's counts separate rows from positions.

### 3.2 The bracket comes from the leg's own package

- `virtual_sl = order_packages.sl`, `virtual_tp = order_packages.tp` at the hold time. These are the levels the leg WOULD have sent.
  No re-derivation, no fleet default.
- **TP doctrine** ([`docs/ARCHITECTURE-CANONICAL.md`](../ARCHITECTURE-CANONICAL.md) § "TP doctrine"). If the leg's TP is a sentinel
  (`tp_r` ≥ 50 or the venue cap), the virtual row is stamped `tp_compliance: sentinel` and resolves on SL / time only. Its grade
  carries the same non-compliance the real leg carries in `scripts/ci/check_tp_doctrine.py`. The virtual layer does NOT invent a
  "real" TP the leg does not have.
- **Time stop**: the leg's own `timeout_bars` / `max_hold` from `config/strategies.yaml` when it has one. Otherwise a resolution
  horizon of `max(96 bars, 3 × the leg's median real hold)`, after which the row is `censored: horizon`.

### 3.3 Exit, simulated on bars

- Bars: the leg's own timeframe from the canonical candle source the trainer already uses (`datasets-out/market_raw` shards; the
  live fetch path `src.runtime.market_data.fetch_candles` as fallback). The **first bar strictly after entry** starts the walk.
- Walk: `src/analysis/trade_reconstruction.py::first_touch_outcome` (pure, stdlib, tested). A bar that straddles SL and TP resolves
  **SL-first** (`pessimistic=True`) and is flagged `ambiguous=true`.
- **v1 exit model = `bracket_only`**: SL / TP / time stop. The leg's own `monitor()` verdicts (trail, giveback, TP revision) are NOT
  replayed in v1. Every row carries `exit_model: bracket_only`, and the grade states that it understates a trailing leg's management.
  **v2 = `monitor_replay`**: run the leg unit's `monitor()` over the bar path offline. This needs the unit's monitor state to be
  replayable from candles. That is a build question for the row, not assumed here.
- **Censoring** (fc_geometry_resolve precedent): a row that has not touched either level by the horizon or the data edge is
  `censored: horizon | data_edge`. A row closed by a real fill of the same leg is `censored: converted_to_real` (§ 3.4). **A censored
  row is never marked-to-close and never enters a mean.** The censoring rate is reported next to every aggregate.

### 3.4 Interaction with the real book (one rule)

The virtual position is independent of what the owning leg does. Carver's subsystem position does not care what the netted book did.
The single exception: if the held leg itself gets a **real** fill on the same account/symbol while its virtual position is open (the
owner exited and the leg re-signalled), the virtual row closes at that moment `censored: converted_to_real`. This keeps the per-leg
series (real ∪ virtual) from counting one leg twice.

### 3.5 The full cost stack

R is computed **net** with the shared venue-correct cost model the ML labels already use: `ml/datasets/labeling/cost_policy.py`
(`resolve_barrier_costs` / `apply_cost_policy`), which sits over `src/runtime/execution_costs.py` (fee via `resolve_fee_bps_roundtrip`,
slippage + funding via `resolve_cost_policy`, funding windows via `roundtrip_cost_r`). Each row stores `gross_r`, `fee_r`,
`slippage_r`, `funding_r`, `net_r` and `cost_basis` (the policy id). `scripts/backtest_orb.py` (fee only) and
`src/backtest/backtester.py` (own cost dict) are NOT used (CLAUDE.md § daily sync).

## 4. Storage: a projection over the canonical source, no new table

**Canonical source**: `trade_journal.db::trades` (the hold rows) JOIN `order_packages` (the bracket) ON `order_package_id`.

**Projection**: a pure resolver, proposed as `src/analysis/virtual_positions.py`:

- `select_held_intents(con, since, until)` → hold rows joined to packages.
- `open_virtual_positions(rows)` → the § 3.1 lifecycle (dedupe, one per leg, real-trade exclusion).
- `resolve(position, bars, cost_policy)` → the § 3.3 / 3.5 outcome.

It has no DB writes. Every consumer recomputes from the canonical source, so a backfill is just a run over an older window. The
whole 30-day history in § 5 is recoverable on day one.

**Derived artifact** (cache, not a store): the trainer writes `comms/virtual_positions/<YYYY-MM-DD>.jsonl`, regenerated from the
canonical source on each run. It carries the § 6 fields and the source row ids, so any row can be re-derived. Deleting it loses
nothing. This is the `comms/live_review/outcomes.jsonl` / `fc_geometry_soak` pattern, and it adds no table, so
`new-table-wiring-guard` does not apply. **If the build finds the per-request recompute too slow for the API** (§ 7), it asks the
operator for a table plus a backfill (CLAUDE.md § Generation Discipline Rule 3) and does not add one on its own.

## 5. How much this recovers: held intents per leg, last 30 days

MEASURED via trainer-VM diag relay [#21002](https://github.com/benbaichmankass/Metis-Insights/issues/21002) over the trainer's synced
`trade_journal.db`. Population, window and freshness: see below.

<!-- MEASUREMENT -->

## 6. Grading and labelling: VIRTUAL, ESTIMATED, never in measured P&L

Every virtual row carries:

| field | value |
|---|---|
| `record_kind` | `virtual` (real trades are `real`; there is no third value) |
| `provenance` | `ESTIMATED` from `src/runtime/provenance.py`. Never `MEASURED`; a reader that folds it into measured P&L is a bug |
| `virtual_reason` | `flip_suppressed_hold_policy` (the selector is one string, so the same projection can later take `execution: shadow` packages, see § 10) |
| `held_by` | the owning leg and trade id read from `conflict_taxonomy_soak.jsonl` / the open real trade at hold time; `null` when unread, never guessed |
| `exit_model` | `bracket_only` (v1) / `monitor_replay` (v2) |
| `outcome` | `tp` / `sl` / `time` / `censored` + `censor_reason` |
| `ambiguous` | the SL-first tie-break was used |
| `gross_r`, cost terms, `net_r` | § 3.5; `null` when censored |
| `entry_basis`, `tp_compliance`, `n_hold_rows`, `signal_key`, source ids | § 3 |

**Consumers**:

- **/performance-review**. A per-leg block shows `real` and `virtual` side by side, never summed. The virtual block covers n,
  resolved n, censoring rate, mean net R and the ambiguous share. The review's "live vs backtest band" check gains an input: a leg
  that is mostly held has a virtual series to compare against its Stage-0 band. **A virtual series never establishes edge** (R3:
  a live/paper/virtual book establishes mechanics, not edge). It is a monitoring signal and a question for research.
- **Research / perf-followup**. The held-vs-owner question becomes measurable per conflict: what the held leg would have made vs
  what the owner made over the same window. This is the successor input to the retired M26 P0 bleed study
  (`scripts/research/m26_p0_conflict_bleed.py`), which priced the owner's tail but never the held leg.
- **ML datasets**. Virtual rows can join the `setup_candidates` family as **labelled decision points** with
  `record_kind=virtual`. The label is the M1-compliant cost-net, path-dependent barrier outcome of the leg's own bracket. Training
  manifests must opt in explicitly (`include_virtual: true`), and the cost gate (`ml/promotion/cost_gate.py`) reports real-only and
  real+virtual separately. Default is **excluded** until an ML-review call says otherwise.
- **Never**: `/api/bot/pnl*`, broker truth, the daily-DD switch, prop survival, soak mechanics, or any promotion corpus.

## 7. Surfacing on `/api/bot`

`GET /api/bot/virtual_positions` in a new read-only router, `src/web/api/routers/virtual_positions.py`, using the
`shadow.py` envelope pattern (S-061: nulls as `null`, `log_present` / `read_state`):

- Params: `since`, `until`, `account`, `strategy`, `symbol`, `status=open|closed|censored|all`, `limit`.
- Envelope: `{read_state: looked|could_not_look, record_kind: "virtual", provenance: "ESTIMATED", population: {held_rows, positions,
  absorbed_rows, resolved, censored}, rows: [...]}`. The population block always comes back, so an empty `rows` reads as "looked,
  none" and not as zero.
- Source: the trainer-built artifact, mirrored to the VM like other `comms/` outputs. When it is missing or stale (>24 h), it falls back
  to `read_state: could_not_look` with the reason. It **never** returns an empty list as if it had looked.
- `GET /api/bot/virtual_positions/summary`: per (account, leg) n / resolved / censored / mean net R / ambiguous share, the same
  numbers the performance review uses.
- The SPA renders them under a separate "Virtual (held intents)" heading, never inside P&L tiles (a follow-up row in
  `ict-trader-dashboard`, not built here).

## 8. Tests (the build lane writes these first)

1. **Lifecycle**: a held row opens a virtual position. A second held row of the same `signal_key` is absorbed. A held row of the
   same leg while open is absorbed. A held row for a leg with an open real trade opens nothing.
2. **Barrier walk**: long/short TP-first, SL-first, straddle → SL + `ambiguous`, horizon → `censored: horizon`, data edge →
   `censored: data_edge`, real fill → `censored: converted_to_real`.
3. **Cost**: `net_r = gross_r − (fee+slip+funding)`. A Bybit perp crossing two funding windows charges two windows. An IB future
   charges no funding. The cost basis matches `cost_policy.apply_cost_policy` on the same inputs (a parity test, not a copy).
4. **Provenance**: every emitted row is `ESTIMATED` / `virtual`. A planted test asserts that `/api/bot/pnl` and the performance
   review's real-P&L sum are unchanged by adding virtual rows (a negative control).
5. **Sentinel TP**: a `tp_r: 50` package resolves on SL/time only and stamps `tp_compliance: sentinel`.
6. **API**: `could_not_look` when the artifact is missing (never `rows: []` with `looked`). The population adds up:
   `held_rows == positions + absorbed_rows`.
7. **Live-data verification** (Rule 3, not a unit test): run the resolver on the trainer journal and confirm the trade-6673 case
   produces virtual rows for `ict_scalp_mgc_15m` / `mgc_trend_1h` on `ib_paper` whose source ids are real `trades` rows.

## 9. Rollout (Tier-2 steps; each is one revertible PR)

| step | tier | what | closing observation |
|---|---|---|---|
| 1 | 1 | `src/analysis/virtual_positions.py` + tests (pure; no runtime import) | tests green; a trainer run over 30 d reproduces § 5's position count ± the documented dedupe |
| 2 | 1 | trainer job `scripts/research/virtual_positions_build.py` writes `comms/virtual_positions/*.jsonl`; 30-day backfill run | artifact present; the population adds up; the trade-6673 rows appear |
| 3 | **2** | read-only `/api/bot/virtual_positions` router on the live web API + artifact mirror to the VM | `diag_fetch.sh` / curl returns `read_state: looked` with rows matching step 2 |
| 4 | 1 | performance-review CHECKS add the virtual block; perf-followup reads it | the next review shows real and virtual separately |
| 5 | **2** | schedule the trainer job (daily, after `sync_trainer_data.sh`) + freshness check on the CONSUMED artifact (`check_producer_liveness.py`) + a `shadowed-features.yaml` entry for held intents | first scheduled run observed; the freshness check reads `fresh` |
| 6 | 1→ML-review | `include_virtual` manifest flag (default off) | an ML-review call decides whether to turn it on |
| v2 | 1 | `monitor_replay` exit model, if a unit's monitor proves replayable | parity: replayed real trades reproduce their real exits within a registered tolerance |

There is no step that touches `compute_execution_delta`, `FLIP_POLICY`, the coordinator's dispatch, or any order. The real book is
byte-identical before and after. Revert = delete the router / stop the job. The canonical rows are untouched.

## 10. Out of scope / follow-ons (named, not built)

- `execution: shadow` legs' packages are the same shape (a package with a bracket and no fill). The same projection with a different
  selector (`virtual_reason: execution_shadow`) would give every shadow leg a graded series. File it as its own row once step 2 lands.
  Do not fold it into this build.
- Other held reasons (`reentry_suppressed_netting_guard`, `slice_hold_to_bracket_*`, `at_target`) are not opposite-side holds and are
  excluded. `at_target` and reinforcements of the SAME side are already in the real position.
- `ict-trader-dashboard` rendering (separate repo).

## 11. Open questions for Thursday planning

1. **Entry convention** for market-entry packages: next-bar open (proposed) or the package entry price?
2. **Horizon for legs without a time stop**: `max(96 bars, 3 × median real hold)` (proposed) or per-leg registered values?
3. **ML default**: virtual rows excluded from training until an ML-review call (proposed), or included from day one with the flag?
