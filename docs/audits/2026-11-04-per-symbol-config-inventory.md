# Per-symbol configuration inventory against "an account configures strategies, never symbols" (2026-11-04)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Gates this adds or changes: none.** This is a measurement. It proposes changes and applies none.

Row `ML-UNIVERSE-RULE`. Lane dispatched by Manager Session 2026-11-04a. The rule is in
[`docs/CLAUDE-RULES-CANONICAL.md`](../CLAUDE-RULES-CANONICAL.md) § "An account configures strategies, never symbols",
with the operator's words verbatim.

**Population.** Everything below was MEASURED at `origin/main` 924aeee35 (2026-11-04) over:
- `config/accounts.yaml`: 14 accounts;
- `config/strategies.yaml`: 60 legs, 2 of them carrying `model:` (`ml_entry`, `ml_entry_v2`);
- the other `config/*.yaml` files, scanned for account-keyed symbol lists;
- the `symbol_sets` callers, found by grep for `leg_symbols` and `account_symbols` over `src/ scripts/ tests/`.

The scan was checked against a known positive: it finds `claude_desk.account_symbols` and
`prop_platforms.yaml::enabled_venue_symbols`.

## 1. Inventory: what decides what trades per symbol or per account

| # | Site | What it decides | Violates the rule? | Fix |
|---|---|---|---|---|
| 1 | `config/accounts.yaml::<acct>.strategies` | The roster: which legs and MLs are active | **No.** This is the one thing an account may configure | — |
| 2 | `config/accounts.yaml::<acct>.symbols` | Data-pull list. The tick fetch set is `UNION(roster-implied, declared)` (`src/main.py::_resolve_tick_symbols`) | **No.** It is additive data, never a trade decision (2026-09-22) | — |
| 3 | `config/accounts.yaml::alpaca_live.side_filter: long` | Sides on one account | **No.** It is a venue capability (cash book, no shorting), not a symbol choice | — |
| 4 | `config/strategies.yaml::<leg>.symbols` on 56 single-symbol legs | The leg's one symbol | **No.** The strategy defines it, and it is the symbol its evidence measured | — |
| 5 | `config/strategies.yaml::e4_oi_shock_1h.symbols` (6 perps) | A rule-based multi-symbol leg's universe | **No in shape.** It is the frozen rule's own replay population (RQ-20261030-e18g-02/03). Its Stage-0 absolute read FAILED; it trades on bybit_1 by a stated operator exception | — |
| 6 | **`config/strategies.yaml::ml_entry.account_symbols`** (bybit_2, bybit_portfolio: 5 perps; alpaca_paper: 13 ETFs) | Which symbols the ML trades on each account | **YES.** Account-keyed symbol configuration for an ML | Delete the map. The ML's universe = the symbols in its per-symbol pass record (§ 2) ∩ the venue's tradeable instruments, resolved at trade time; with no record, the current set |
| 7 | **`config/strategies.yaml::ml_entry.symbols`** (18: 5 perps + 13 ETFs) | The union the builder evaluates (`strategy_signal_builders.py` ~L6524) | **YES.** It is hand-written, not read from the evidence record. The 13 ETFs FAILED or were never tested (§ 2) | Derive from the per-symbol pass record; with no record, the current set stays |
| 8 | **`config/strategies.yaml::ml_entry_v2.symbols`** (5 perps) | v2's universe on bybit_1 | **YES.** It is hand-written. v2 has no PASS (§ 2) | Derive from a per-symbol pass record; with none (today), the current set stays |
| 9 | **`config/strategies.yaml::claude_desk.account_symbols`** (bybit_1: 6, alpaca_paper: 5, ib_paper: 3) | The desk's symbols on each account | **YES in shape.** Account-keyed symbol lists | The desk's own proposal picks the symbol. Limit it at trade time by venue tradeability (`config/instruments.yaml` profile × the account's exchange), not a per-account list. Paper only, Tier 3 |
| 10 | `src/config/symbol_sets.py::leg_symbols` / `roster_symbols` / `ACCOUNT_SYMBOLS_KEY` | Reads #6 and #9. Narrows a leg's union per account | **Mechanism for a violation** | Replace with a resolver: (ML → per-symbol pass record, else current set; desk → proposal symbol) ∩ venue-tradeable(account). The data-path union (fetch set, position cross-check, fill/funding sweep) must keep working, so it then reads the resolver instead of `account_symbols` |
| 11 | `src/core/coordinator.py::_leg_account_scope` → refusal `leg_account_scope` | Refuses a package whose symbol is outside the leg's `account_symbols[account]` | **Mechanism for a violation**, though it also catches real venue mis-routes (SPY to bybit_1) | Keep a refusal, but key it on venue tradeability (`symbol_exchange_routing` already separates IB; extend it to Bybit vs Alpaca), not on a hand list |
| 12 | `scripts/ci/check_roster_symbol_reachability.py` | Rostered symbol ⊆ pull list, reading `leg_symbols(scfg, acct)` | **Assumes per-account rostering** (reads #6/#9) | Point it at the new resolver. The check itself (data-path reachability) stays |
| 13 | `scripts/ci/check_same_symbol_allocation.py` | Legs sharing (account, symbol) need a known allocation; reads `leg_symbols(…, acct)` | **Assumes per-account rostering** | Point it at the resolver. An ML universe that widens by evidence can create new shared (account, symbol) groups. The guard must see that, which needs the resolver, not the hand list |
| 14 | `scripts/ci/check_roster_promotion_evidence.py` | Leg added to a real-money roster ⇒ C1–C5 evidence | **Gap, not a violation.** It keys on leg names. Under the rule, an ML's universe widening on a real-money account is not a roster edit, so this guard cannot see it | Add a check that an ML leg's resolved universe on a real-money account ⊆ the symbols in its committed per-symbol pass record (or its current set while none exists). This is the same bar applied at symbol grain, not a new gate. Needs the operator's say under "No new gates" if read as one |
| 15 | `scripts/ci/check_strategy_status.py::DUAL_BOOK_EXCEPTIONS["ml_entry"]` | Lets ml_entry sit on bybit_2 (production) and alpaca_paper (paper), justified by "a different symbol set: account_symbols" | **Rests on #6** | Re-justify on the resolver: the two books still never share a symbol (crypto perps vs ETFs). It falls away if alpaca_paper's per-symbol test leaves no ETF |
| 16 | `config/prop_platforms.yaml::<acct>.executor.enabled_venue_symbols` (+ env `PROP_EXECUTOR_SYMBOLS*`) | Symbols the prop browser/phone executor may act on per account | **Borderline. It is a venue-mechanics list** (symbol switching / lot specs measured per symbol), which the rule allows ("what the venue can physically trade") | Keep the purpose. Derive it from the measured mechanics record (`config/mechanics_paths.yaml`) instead of a hand list plus env override. Filed, not urgent |
| 17 | `config/slice_allocation.yaml::declared_slices` (`bybit_1: {claude_desk, e4_oi_shock_1h}`) | Risk budget per (account, leg) | **No.** It sizes risk; it does not pick symbols | — |
| 18 | `scripts/research/ml_entry_alpaca_score.py::_account_symbols` and the c692-06 unit ("the bybit_2 symbols re-read from config/accounts.yaml at run time") | The TEST population, read from account config | **YES, inverted** (rule point 4): the account picked the ML's tested universe | Future universe tests choose the population from the ML's candidate universe and a pre-registered liquidity rule. RQ-20261101-a24c-01 is already shaped this way |
| 19 | `src/runtime/entry_head_pwin.py`, `src/runtime/exit_head_shadow.py` (`artifact.get("symbols")`) | Advisory/shadow heads' universe | **No.** It is already internal to the model artifact. This is the precedent for the resolver | — |
| 20 | `src/runtime/ml_decision_shadow.py` (`cfg.symbols`) | The shadow scorer's traded set (no orders) | **No trades.** It follows #7 | Follows the resolver |

**Count check.** 20 rows: 9 compliant (1–5, 17, 19 plus 20, which places no trades, and 16, borderline but kept), 5 violations (6, 7, 8, 9, 18), 5 mechanisms or guards that read a violation (10–13, 15) and 1 guard gap (14). 9 + 5 + 5 + 1 = 20.

## 2. Per ML: evidence, per-symbol pass record, configured set, delta

### `ml_entry` (served `ml/served/ml_decision_entry_v1`, evidence `comms/strategy_evidence/ml_entry.json`)

| Test (registered before the run) | Population | Result | Source |
|---|---|---|---|
| RQ-20261101-c692-01 `RULE-…-c692-01-ENTRY` | 53 perps with decisions (60-perp Binance universe), held-out 2025-10-01..2026-09-30, fee 11 + slip 3 bps + funding | **PASS, pooled** +0.0073 R/decision, n=11,240 | `research/results/RQ-20261101-c692-01/local-20261101T0835Z.jsonl` |
| RQ-20261101-c692-06 `RULE-…-c692-06-TRADED-SUBSET` | The 5 bybit_2 perps (BTC, ETH, XRP, ADA, SOL), same window. **The population was re-read from accounts.yaml** (inventory #18) | **PASS, pooled** +0.0263 fixed TP / +0.0271 extend-only, n=907 | `research/results/RQ-20261101-c692-06/local-20261101T0840Z.jsonl` |
| RQ-20261101-bdc2-01 `RULE-…-bdc2-01-ENTRY-ON-ALPACA` | 11 alpaca_live ETFs (GDX GLD IAUM IEF IWM QQQ SLV SPY SPYM TLT USO), long-only | **FAIL** −0.308 R, n=128. Both sides, reported: −0.330, n=383 | `research/results/RQ-20261101-bdc2-01/local-20261101T1205Z.jsonl` |
| (reported, not a gate) re-cost of c692-01 at measured Bybit spreads | 51 Bybit-listed perps | −0.0050 (vs +0.0065 at flat 3 bps) | `comms/research/ML-ENTRY-UNIVERSE/local-20261101T1830Z/summary.json` |
| (reported, not a gate) frozen-v1 reference in RQ-20261101-b609-01 | W1 2026-10, 49 symbols | −0.0405, n=894 | `comms/research/RQ-20261101-b609-01/local-20261101T2000Z/result.json` |
| RQ-20261101-a24c-01 (blocked: harness + 2026-10 data) | Dev-chosen universe U(C) over the perps, re-costed per symbol-month | not run | `research/queue/blocked/RQ-20261101-a24c-01.yaml` |
| RQ-20261104-a41f-01 (PR #22900, queued) | The alpaca_live ETFs under an Alpaca profile | not run | PR #22900 |

**No per-symbol pass record exists for ml_entry.** Every PASS above is pooled over many symbols, and the operator's
2026-11-04 decision ("Per-symbol passes") requires a per-symbol test registered before the run and net of each symbol's
measured cost. Per-symbol numbers do exist: the 53 point estimates in `ML-ENTRY-UNIVERSE/…/summary.json` (31 of 53
≥ 0) and bdc2-01's per-ETF points (n 3–22 each). But they come from windows that were already read, under a pooled
rule. Picking symbols from them would be post-hoc selection, not a pass record.

**So, under the rule, the current set stays on every account until a per-symbol test reports.**

| Account (status) | Venue can trade | Configured today | Per-symbol pass record | Delta today | What would change it |
|---|---|---|---|---|---|
| bybit_2 (real money) | Bybit USDT perps | BTC ETH XRP ADA SOL | none | **none** | A per-symbol test, net of each symbol's measured cost, over a registered perp population. Symbols that pass are in, symbols that fail are out (Tier 3, data-backed) |
| bybit_portfolio (real-money mirror) | Bybit USDT perps | BTC ETH XRP ADA SOL | none | **none** | Same; the mirror follows live |
| alpaca_paper (paper) | US equities/ETFs (no Alpaca crypto instrument profile in `config/instruments.yaml`) | SPY QQQ IWM TLT IEF SLV USO GDX TQQQ QLD SPYM IAUM SCHA (13) | none (bdc2-01 is a pooled FAIL, not a per-symbol record) | **none under rule point 3** | Rule point 4 (an off-training venue is tested per symbol and only passes trade): a per-symbol test of the ETFs on a registered population |

**What the queued units would and would not produce.** RQ-20261101-a24c-01 (crypto universe, blocked) and
RQ-20261104-a41f-01 (Alpaca, PR #22900) are both registered with **pooled** rules: a24c-01 reads a dev-chosen universe
U(C); a41f-01 requires mean net R ≥ 0 at n ≥ 30 over the alpaca_live symbols. As written, **neither yields a per-symbol
pass record.** Re-registering them, or adding sibling units with per-symbol rules (a per-symbol n floor, net of that
symbol's measured cost), is the step that lets the universe change at all. That step belongs to the lane that owns the
ml_entry resolver (ML-ENTRY-ALL-ACCOUNTS, PR B).

### `ml_entry_v2` (served `ml/served/ml_decision_entry_v2`, testing leg on bybit_1 only)

| Test | Result | Source |
|---|---|---|
| RQ-20261101-b609-01 (W1 2026-10, 45 symbols) | **FAIL** −0.1161 R, n=320 (pooled). Traded-5 slice −0.193, n=8 | `comms/research/RQ-20261101-b609-01/local-20261101T2000Z/result.json` |
| RQ-20261101-b610-01 (forward read from 2026-11-01, pooled frozen-60) | blocked, accruing (the window closes on a computed count) | `research/queue/blocked/RQ-20261101-b610-01.yaml` |

No evidence record exists (`comms/strategy_evidence/ml_entry_v2.json` is absent) and no per-symbol test is registered.

| Account (status) | Configured today | Per-symbol pass record | Delta today |
|---|---|---|---|
| bybit_1 (demo, Stage 1) | BTC ETH XRP ADA SOL | none | **none.** The current set stays (rule point 3); a testing leg keeps trading the demo floor |

### Other model-driven legs

`claude_desk` (an LLM desk, not a trained ML) is inventory #9. `ml_entry`'s moving TP (`ml_entry_tp_revision_v1`) is an
exit head on ml_entry's own trades and has no universe of its own. `entry_head_pwin`, `exit_head_shadow` and
`ml_decision_shadow` place no orders. No other leg carries `model:` (MEASURED: 2 of 60).

## 3. What follows (nothing here is applied by this document)

1. **No account changes symbols today.** No ML has a per-symbol pass record, so every current set stays (operator
   decisions 2026-11-04 ~19:08Z: "Split", "Per-symbol passes", "Per-symbol tests").
2. **Per-symbol test units** for ml_entry: crypto perps net of each symbol's measured cost, plus the Alpaca ETFs on a
   registered population. ml_entry_v2 needs the same once it has a candidate worth testing. The ml_entry units and the
   resolver (inventory #6, #7, #10–13, #15) belong to lane ML-ENTRY-ALL-ACCOUNTS (PR B). The resolver is Tier 2, with
   a landing hold and parity tests.
3. **Not owned by that lane:** `claude_desk.account_symbols` (#9, paper/demo, Tier 3) and the
   roster-promotion-evidence guard gap (#14). Both stay on row `ML-UNIVERSE-RULE`. #14 may read as a new gate, so it
   needs the operator's say under "No new gates" before it is built.

## 4. Alignment with PR #22900 (lane ML-ENTRY-ALL-ACCOUNTS)

The operator chose "Split": #22900's parametrisation (`account_profiles`: anchor, reference venue, sides, session,
cost basis) stays separate from any universe change. Rule point 5 states this. The profiles describe the **venue**,
which the rule allows. But `ml_entry_profile.py` resolves the profile "per symbol through `account_symbols`", the map
this rule retires. In PR B, the profile should key on the account's venue, and the symbol → account mapping should come
from the per-symbol pass record (else the current set) ∩ venue, not from `account_symbols`. This was sent to that lane.
