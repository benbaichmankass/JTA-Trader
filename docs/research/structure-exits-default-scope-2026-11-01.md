# Structure-based exits as the default: scope, inventory, reuse map, plan

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md)

> Lane `STRUCTURE-EXITS-DEFAULT` (scope + queue only), 2026-11-01.
> Gates this adds or changes: **none.** Rule text: `docs/ARCHITECTURE-CANONICAL.md` § "Active management", "The default exit".

Population: `config/accounts.yaml` and `config/strategies.yaml` at `origin/main` 02596e501; `python3 scripts/ci/check_tp_doctrine.py` re-run this session
(74 routings / 54 legs; real_money 7, prop 3, mirror 7). Counts move; re-run, never quote.

## 1. Inventory: real money first

"Structure exit exists?" means: a structure-anchored SL/TP wired in the live monitor or a harness arm for that leg. **No leg has one**
(measured: `research/levers/ltr-sl-to-structure.yaml` reads `levers: {}`, `no_arm_records_yet`; no harness has a structure-exit flag).

| Leg | Money / accounts | Current SL / TP | TP doctrine (entry_tp / revision) | Structure exit? | Unit |
|---|---|---|---|---|---|
| iaum_pullback_1d | real: alpaca_live | ATR 2.0 stop + trail 4.0; TP 3.5R declared | declared / FAIL (rule_undeclared) | no | 5e01-01 |
| ada_pullback_2h | real: bybit_2; mirror bybit_portfolio | ATR 1.5 + trail 5.0; TP 4R (reach 0.241) | declared / FAIL | no | 5e01-02 |
| xrp_pullback_2h | real: bybit_2; mirror | ATR 2.5 + trail 6.0; TP 3R (reach 0.246) | declared / FAIL | no | 5e01-03 |
| trend_donchian_eth_4h | real: bybit_2; mirror | ATR 1.5 + trail 6.0; **sentinel TP 50R**, `donchian_measured_move` declared | **FAIL entry_tp** (sentinel) | no | 5e01-04 |
| trend_donchian_xrp_4h | real: bybit_2; mirror | ATR 2 + trail 5.0 + stale exit; TP 3R (reach 0.158) | declared / FAIL | no | 5e01-05 |
| trend_donchian_sol_prop | real: bybit_2; mirror | ATR 2.5 + trail 3.5; TP 6R (reach 0.019) | **FAIL entry_tp (unreachable)** + revision | no | 5e01-06 |
| trend_donchian_eth_prop | prop: breakout_2, tradeify_1, velotrade_1 | ATR 2.5 + trail 3.5; TP 6R (reach 0.009) | **FAIL entry_tp (unreachable)** + revision | no | 5e01-07 |
| gld_pullback_1d | mirror only: alpaca_portfolio | ATR 2.0 + trail 4.0; TP 3.5R | declared / FAIL | no | 5e01-08 |
| ml_entry (v1) | real: bybit_2; mirror | ATR 2.0 stop; TP 1.5R; no TP verdict (`no_tp_verdict`) | declared / FAIL | no | 5e01-09 |
| ml_entry_v2 | demo floor: bybit_1 (served) | ATR 2.0 stop; TP 2.0R | not a real-money routing | no | 5e01-10 |
| ML per-symbol heads | served heads | not enumerable from committed config in this clone | unknown | no | 5e01-11 (enumerates the registry at run time) |

Priority 2 (testing legs, demo floor / paper), one unit per family, legs re-parsed at run time: trend_donchian family (5e01-12), pullback family (5e01-13),
ict_scalp family (5e01-14), remaining testing legs (5e01-15). Paper-book TP-doctrine debt is larger (paper routings 57, entry_tp FAIL 28, revision FAIL 57).

## 2. Reuse map and gaps

| Exists | State | Use |
|---|---|---|
| `research/levers/ltr-sl-to-structure.yaml` | `not_live`, zero arm records, awaiting LTR-CLASS-GRADE | the advisory class this default promotes; its first record is a by-product of these units |
| Exit-refinement coverage matrix (`docs/research/exit-refinement-coverage.json`) | lever columns: trail_geometry, stale_stop, giveback_stop, exit_ladder, exit_head_ml. **No structure column.** | add `structure_exit` column when the first unit lands (gap) |
| `src/runtime/tp_revision.py` | `tp_extend` and `donchian_measured_move` rules, extend-only, through-price refusal, venue-cap clamp; mechanism for moving a TP live | the TP side of the live apply path |
| Stop move path (`monitor()` verdict `{"sl"}` / `{"tp"}` via `order_monitor._apply_update`) | exists | the SL side of the apply path |
| `src/ict_detection/swing_points.py`, `liquidity.py`, `order_blocks.py`; `src/runtime/liquidity_state.py` | **centered-window pivot detector: uses right bars, so a swing is "known" only N bars late; as written it has lookahead if called on the full frame.** `liquidity_state` is a live-only disk handoff | not safe to share as is |
| Checklist row `ML-ENTRY-DYNAMIC-SL` (arms a-e, e = structure SL) | on main, `queued`, "author after the 2026-11-04 18:00Z reset" | owns the ML SL-move arms; units 5e01-09..11 are blocked on its walker |
| ML trade walker (`RQ-20261101-383f-*`) and #22093 extend-only TP | **not on `origin/main` 10886252a** (zero hits in queue, scripts, checklist). `scripts/research/ml_entry_levers.py` labels fixed sl/tp brackets (`label_cell`) and has no SL-move walker | UNVERIFIED whether on an open PR; a structure SL arm for the ML cannot run until it lands |
| `backtest_trend.py` / `backtest_pullback.py` `--trail-level swing\|fvg\|round` (+ `--trail-level-pivot-k`, `--trail-level-tight-mult`) | **exists**: ONE structure level fixed at entry; the trail tightens on first touch (latched). Not ratcheting, no structure TP | the runnable existing-harness test: units `RQ-20261101-5e02-01..08` (smoke-run end to end on `ada_pullback_2h`, 200 days) |

**Gaps.** (1) **There is no shared causal structure-level detector.** Live uses `liquidity_state`; research uses its own ad hoc pivots. This is the FIRST BUILD:
one pure, index-based, no-lookahead module (confirmed swings, unfilled FVG edges, liquidity levels as of bar t) imported by both the live monitor and
the harnesses, with a lookahead-negative test. (2) No harness has a RATCHETING structure-exit arm or a random-exit control. (3) Coverage matrix has no structure column.
(4) The book-level $ simulator (`BOOK-SIM-REAL-SIZER`) is still not built, so every verdict here is a screen until it exists (canonical clause 4).

## 2b. Runnable now vs blocked (counts)

| Leg | Runnable now (existing `--trail-level` harness; `5e02`) | Blocked (full dynamic SL+TP; `5e01`) |
|---|---|---|
| iaum, ada, xrp pullback, eth_4h, xrp_4h, sol_prop, eth_prop, gld | 8 units (5e02-01..08), arms A / SW3 / SW5 / FVG, `--grade replace` | 8 (5e01-01..08): shared detector + ratcheting arm |
| ml_entry, ml_entry_v2, ML heads | 0 | 3 (5e01-09..11): SL-move walker not on main; row ML-ENTRY-DYNAMIC-SL authors after the reset |
| Priority 2 families | 0 | 4 (5e01-12..15) |

Total: 8 runnable, 15 blocked. A 5e02 PASS is a discovery on the static form only; a FAIL does not close the dynamic form.

## 3. Registered rule (the 5e01 units share `RULE-STRUCTURE-EXITS-V1`; the 5e02 units carry their own harness `replace` rule, ed1c-17's parameters)

Written before any run; full text in each unit's `decision_rule`. One factor (the source of SL/TP levels), entries fixed, net of the full cost stack, leave-one-fold-out
dev selection of the pivot N in {3,5,8} (the only tuned parameter), 100 matched random-exit controls, per-leg verdict PASS_BETTER / PASS_NONINFERIOR / FAIL /
INDETERMINATE (n < 39). A PASS is a discovery needing one confirmation run, then a per-leg Tier-3 apply PR.

## 4. Project STRUCTURE-EXITS-DEFAULT (Tier 3 for live; due 2026-11-05; roadmap L-AM-STANDARD)

| Step | Work | Estimate |
|---|---|---|
| 1 | Shared causal structure-level detector + lookahead test + live adapter | 1 lane, about 1 day, about $8 |
| 2 | Harness subcommand: `--structure-exit pivot=N` on backtest_trend / backtest_pullback / ML harness, random-exit control, exit_lever_ablation arms, coverage column | 1 lane, 1-2 days, about $12 |
| 3 | Run the P1 units (5e01-01..11) on Kaggle first; then P2 families | compute only, about 2-4 h per unit, no Claude cost |
| 4 | Read results, confirmation run for PASS legs | 1 lane, about $6 |
| 5 | Per-leg Tier-3 apply PRs (operator merge) for PASS legs; a FAIL leg keeps its exit and records the lever closed | about $3 per leg, operator approval each |

Steps 1-2 may start immediately ("start queuing now"); the project kicks off in earnest after the 2026-11-04 usage reset. Due 2026-11-05 is for steps 1-3 started and the
first P1 results read, not for live application.

## 5. BUILD SCOPE: live monitors must see new structure and act on it (operator 2026-11-01 ~23:05Z)

Operator, verbatim: *"The scoping is also a building scope - ensuring the live trade monitors know how to identify new structure levels in real time and act on them correctly"*.
Measured from the code at `origin/main` 10886252a (grep only; no live data pulled):

### 5.1 Live detection today, per monitor

| Monitor | Structure detection today | Same detector as research? |
|---|---|---|
| 15 strategy `monitor()` paths (`src/units/strategies/`: trend_donchian, htf_pullback_trend_2h, ml_entry, ml_entry_v2, ict_scalp, squeeze, fade, fvg_range, e4, turtle_soup, vwap, hf_*, claude_desk, pairs) | **None.** Zero swing / FVG / liquidity references in `trend_donchian.py`, `htf_pullback_trend_2h.py`, `ml_entry*.py` monitors. Their verdicts are ATR trails, stale exits and `tp_revision` rules (`donchian_measured_move`, `tp_extend`) | n/a |
| `order_monitor.run_monitor_tick` + `monitor_verdict.interpret_verdict` / `_apply_update` | Applies `{"sl"}` / `{"tp"}` / close verdicts; detects no structure itself | n/a |
| `src/runtime/tp_revision.py` | Bar-replayed pure rules (`tp_extend_path`, `measured_move_path`); no swing/FVG/sweep | n/a |
| Live-review packet (`scripts/ops/live_review_packet.py`) | **Has its own** `swings()` pivot detector (k=`SWING_K`, centered window over the last closed bars) shown to the reviewer; advisory only | NO: a third implementation, distinct from `src/ict_detection/swing_points.py` and the harness `--trail-level` pivots |
| `src/runtime/liquidity_state.py` | Writes liquidity zones for `/api/bot/liquidity`; not read by any monitor | NO |

So there are at least FOUR swing implementations (`swing_points.py`, `live_review_packet.swings`, the harness trail-level pivots, `liquidity.py`) and no live monitor consumes any of them to move a bracket.
**Not measured here (needs a diag pull, UNVERIFIED):** the bar timeframe each monitor sees (leg timeframe by design: 2h/4h/1d, 1h for ML and prop) and the latency from bar close to verdict (`run_monitor_tick` cadence and candle-fetch lag). Step 2 below measures both from `/api/diag/*` before any wiring.

### 5.2 The live action contract (to be built; nothing below exists as a structure rule yet)

1. **Trigger:** a NEW confirmed level as of the just-closed bar (swing confirmed after N bars, FVG formed or filled, liquidity sweep) from the ONE shared detector; evaluated once per closed bar per open package.
2. **Move:** SL and TP move to the level through the existing verdict path: `monitor()` returns `{"sl":..,"tp":..,"sl_reason","tp_reason"}`, `tp_revision.merge_verdict` merges it, `_apply_update` amends on the venue (Bybit trading-stop amend; Alpaca bracket/OCO replace; IB re-arm; prop via `prop_trail`).
3. **Rules:** the SL never loosens past the entry stop unless a tested rule says so (ratchet toward price only); a close verdict wins over a move; a move is idempotent per (package, bar); a venue amend failure is retried and journalled, never dropped; both brackets always exist (Active management clause 3); the TP doctrine's through-price refusal and venue-cap clamp (`plan_tp_revision`) apply; each account's own RiskManager and the fresh-entry check on a widen apply.
4. **Journal:** every move records the level (type, price, formed-at bar), the reason, before/after SL and TP, the bar id, and the venue read-back, so it can be graded (schema to be added with the first wiring PR; grading reuses the live-review `reviews.jsonl` conventions).

### 5.3 Verification

- **Replay parity test:** recorded bars (a committed fixture per timeframe) produce the SAME level list and the SAME move sequence from the live monitor and from the harness arm; a lookahead-negative test (a level is never returned before its confirmation bar).
- **Deploy proof:** the first observed structure move per venue is the mechanics proof, one small trade per new code path (OPERATING-PLAN § 2); not a soak, not a sample size.

### 5.4 Build plan (in order; all after the 2026-11-04 18:00Z reset; no code before)

| # | Step | Estimate | Gaps / risk |
|---|---|---|---|
| 1 | Shared causal detector (pure, index-based): swings with confirmation lag, unfilled FVG edges, sweeps; lookahead-negative test; replace `live_review_packet.swings` and the harness pivots by importing it | ~1 day, ~$8 | four existing implementations to reconcile; decide the confirmation-lag convention once |
| 2 | Measure per-monitor bar timeframe and bar-close-to-verdict latency from diag; monitor wiring: a `structure_exit` verdict source in `monitor()` (default off, byte-identical) for trend_donchian, htf_pullback, ml_entry* | ~1-2 days, ~$12 | latency unmeasured; 15 monitors, wire only the legs with a passing unit |
| 3 | Venue amend paths: confirm SL+TP amend on Bybit, Alpaca OCO replace, IB re-arm, prop (`TP_AMEND_SUPPORTED`; browser dxtrade declares False); retry + journal | ~1 day, ~$8 | Alpaca OCO replace and prop browser path are the known weak spots |
| 4 | Replay parity test and journal schema | ~0.5 day, ~$4 | needs recorded-bar fixtures per timeframe |
| 5 | Per-leg Tier-3 enable for legs whose unit passed (operator merge each); first live move per venue = mechanics proof | ~$3 per leg | clause 4 (RULE-AM-RISK-ADJUSTED-V1) still gates execution |
