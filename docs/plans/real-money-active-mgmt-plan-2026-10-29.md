# Real-money active management: the week's milestone, leg by leg (plan, 2026-10-29)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `ACTIVE-MGMT-REAL-MONEY-PLAN` (Tier 1 planning), dispatched by Manager Session `session_01AFoLuJi1vLTnYv9LbP6539`.
Parent row: `RM-ACTIVE-MGMT-MILESTONE` (roadmap `L-ATM`). Written 2026-10-28 21:00–22:00Z; no config was changed.

**Operator priority #3, 2026-10-28 ~20:55Z (verbatim, relayed by the manager):** *"Other active management R&D - we need
to ensure that the infra for active management is mature and stable enough (triggers, reviews, updates, etc), and
continue to research and test active Management features for the strategies. One milestone for this week - every real
money strategy had some basic logic and mechanics for active management in production (e g trailing stop after X R), so
that we can start implementing it as a standard for real money strategies".*

## 0. The answer in five lines

1. **The example mechanic already exists on every real-money leg.** All 7 distinct legs routed to a real-money or prop
   account declare a ratcheting ATR chandelier trail (`trail_mult`, never loosens). That trail starts moving the stop once
   favourable excursion passes `(trail_mult − atr_stop_mult) / atr_stop_mult` R: it is a "trailing stop after X R".
   It is also the exit each leg's Stage-0 evidence was measured with, because the harness is config-exact.
2. **The evidence says do not add tightening.** The desk's 981 tightens cost −0.097 R each. 0 of 61 pre-registered
   tighten rules beat hold out of sample, and breakeven at +1 R lost on a fresh window (−0.041 R). About 129 of 140
   tightening/exit units graded this week failed (programme review, PR #20994, not yet merged). A new "trail after X R" default on top of the declared trail would be a
   known-losing default, so this plan proposes none.
3. **What is missing is proof and one mechanic.** The trail is observed amending on Bybit real money. It is **not
   observed on any prop account**, and Alpaca's amend has no venue read-back. The second mechanic the doctrine requires,
   a TP that revises with the thesis, runs on 1 of 7 legs (`trend_donchian_eth_4h`).
4. **The milestone is reached by:** (a) proving the declared trail on every account class; (b) adding a detector so it
   cannot stop silently; (c) a CI standard so every future real-money leg carries one; (d) TP-revision declares where a
   pre-registered unit shows them cost-neutral. Six units are registered tonight, each about 25–35 minutes of runner
   CPU. **Primary path since the operator's ~21:05Z message: a conservative hold-biased exit model (§ 0b).**
5. **One leg has no measurable candidate:** `iaum_pullback_1d`, with n 35 on its own history. Its basic mechanic is the
   declared trail plus trail decay. That is cost-neutral by construction (it *is* the Stage-0 book). The operator chooses
   between keeping it as is and a GLD-proxy unit.

## 0b. The PRIMARY path: a conservative, hold-biased exit model (operator, 2026-10-28 ~21:05Z)

**Operator, verbatim (relayed by the manager):**
- *"regarding the active management milestone - I'll settle for a conservative production ML that will mostly recommend
  holding outside of edge cases"*.
- And ~21:06Z: *"active management isn't only tightening - it can be any movement in either bracket triggered by
  developments in the live market data"*.

**How the work is split (agreed with lane `ML-LIVE-PROMOTION-PLAN`, session_01AFoLuNJWA5pu5sGQqcm5s3, ~21:10Z).**
- **That lane owns the MODEL.** Its spec is P6 in `docs/plans/ml-live-promotion-plan-2026-10-29.md`: the action space,
  the label pricing table and the pre-registered gate. Its build rows are `ML-EXIT-ACTIONGRID-LABELS` and
  `ML-HOLDBIAS-EXIT-MODEL`. This plan cites P6 and does not re-specify it.
- **This plan owns the MILESTONE and the WIRING** (row `RM-AM-EXIT-ML-WIRING`). The model's output is hold by default,
  or one action from the full bracket action space. It becomes a `LiveReviewIntent` row and goes through
  `live_review_apply.py` under `MD-TRADE-DESK`, then each account's own `RiskManager`. Both brackets are always present.
- **Rollout order:**
  1. shadow and advice-only on the demo floor (`bybit_1`, `alpaca_paper`), recording advice plus the priced outcome;
  2. a class is executed only after it passes DESK plan § 5b's graduation test (PR #21023), with per-class `apply_mode`
     on row `DESK-V1-CLASS-GATES`;
  3. real money only on the operator's OK.
- `tighten_sl` stays advice-only (operator popup ~20:35Z, *"Advice-only tightens"*).

**A measured caution from the model lane (labels.jsonl, 12,500 rows).** At `now_r ≤ −0.5`, hold beat close by +0.089 R
[−0.08, +0.28] (n 160). The loss-cut "edge case" is not shown to pay. The model must earn every non-hold action on its
own gate.

**What the primary path changes about § 0.** The declared trail (§ 1) stays every leg's floor mechanic: it is what the
backtests measured. The hold-biased model sits on top of it as the live, market-triggered layer. The declared-rule units
(§ 1, § 1b) remain the cheap way to give each leg a TP-revision mechanic this week, whether or not the model passes its
gate in time.

## 1. Per-leg table (real money: `bybit_2`, `alpaca_live`; prop: `breakout_2`, `tradeify_1`, `velotrade_1`)

**Roster.** Re-parsed from `config/accounts.yaml` on `origin/main` 3995aa60, 2026-10-28; no counts are quoted elsewhere.
- `bybit_2`: `xrp_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `ada_pullback_2h`, `trend_donchian_sol_prop`.
- `bybit_portfolio` mirrors `bybit_2`, with strict equality.
- `alpaca_live`: `iaum_pullback_1d`. Its mirror is empty by the sanctioned affordability-proxy divergence.
- The three prop accounts each carry `trend_donchian_eth_prop` and `trend_donchian_sol_prop`.
- `ib_live`: 0 legs. `breakout_1`: `dry_run`, 0 legs.

**Column sources.**
- **Activation**: INFERRED arithmetic from `trend_donchian.monitor()` / `htf_pullback_trend_2h.monitor()`. The stop
  ratchets to `extreme ∓ trail_mult × ATR(entry)`, and the entry stop sits at `atr_stop_mult × ATR`. So the trail first
  beats the entry stop at `(trail_mult − atr_stop_mult)/atr_stop_mult` R of MFE and locks breakeven at
  `trail_mult/atr_stop_mult` R.
- **Live SL / TP amended**: MEASURED 2026-10-28 from diag `journal?table=trades` (4,000 most recent rows) joined to
  `journal?table=order_packages` (3,000 most recent). The population is closed `bybit_2` / `alpaca_live` rows with
  `timestamp ≥ 2026-09-01`. An amend is `sl`/`tp` differing from `exit_plan.stop.price`/`.final.price` by > 0.05%, the
  same comparator as `research/queue/PLANNING.md` 2026-10-07.
- **TP grade**: `python3 scripts/ci/check_tp_doctrine.py --json`, re-run 2026-10-28. 0 of 77 routings are compliant;
  among real money and prop, 0 of 6 and 0 of 6.
- **Unit counts**: MEASURED from the `grading.verdict` of `research/queue/*.yaml` (status `done`), for units whose
  title or question names the leg first and mentions an exit lever. The lever-family split is a keyword classification
  (INFERRED), so read it as an order of magnitude.

| leg (accounts) | current exit + management state | candidate mechanic(s) · Stage-0 evidence · n · net R vs hold-to-bracket | recommended mechanic · gap to production | tier / approval |
|---|---|---|---|---|
| **`xrp_pullback_2h`** (bybit_2, mirror) | Trail 6× ATR, stop 2.5× ATR, so activation **+1.4 R** and breakeven locked at +2.4 R. TP 3R (reach 0.246, n 268); `tp_revision` FAILS (rule undeclared). Live SL amended on **1 of 11** closes. | **tp_extend X6**: family read FIRED 3 of 3 siblings (eth −3.61 vs −9.09 R n 374; sol 11.82 vs 11.70 R n 148; avax 26.56 vs 26.45 R n 422; `bea9-01/02/04`). On xrp's own spent window +1.75 R, 6 of 6 folds (n 394). Cost-neutral to slightly positive. Tightening: 0 of 9 gated-trail and 0 of 12 partial units pass. | **Declare tp_extend X6.** The producer is now on main. Row `TPX-XRP-DECLARE` waits on the operator's own condition: ≥ 2 closed live trades after 2026-10-22T11:51Z. **1 so far** (closed 10-27 at SL). | 3 · operator (condition already set by them) |
| **`ada_pullback_2h`** (bybit_2, mirror) | Trail 5×, stop 1.5×, so activation **+2.33 R**. TP 4R (reach 0.241, n 253); `tp_revision` FAILS. Live SL amended on **3 of 11** closes. | **tp_extend X6 anchored at 4R**: never run; it is the bea9 rule's named follow-on. **Unit `RQ-20261028-a7c3-01`** (S4 vs X6 plus a negative control, n ≈ 402). vol_trail `vt_hot90_t2.5` is `passed_unshipped`, but it is a tighten: its fresh-holdout unit `RQ-20260930-901` is queued. Loss-cut at −0.5 R: unit `P1-Q4-desk-losscut-ada-pb` (#20994). Tightening: 2 of 13 gated-trail, 0 of 10 partial. | **TP revision if a7c3-01 passes.** The trail stays. | 3 · data-backed on PASS (manager may ship and notify), else operator |
| **`trend_donchian_eth_4h`** (bybit_2, mirror) | Trail 6×, stop 1.5×, so activation **+3.0 R**; `trail_decay` (stall 10 → 1.8×) shipped. **Measured-move TP revision declared and live**: TP amended on **2 of 9** closes, SL on 1 of 9. Entry TP is the **50R sentinel**. | Measured move width 0.5: 115.95 vs 99.23 R (n 275 vs 290, RQ-20261018-007), already declared. **Finite entry TP 3R/4R on top of it: unit `RQ-20261028-a7c3-04`.** The ADX trail is superseded (fails against the incumbent). | **The most complete leg.** Only the entry sentinel remains; a7c3-04 settles it. | 3 · data-backed on PASS |
| **`trend_donchian_xrp_4h`** (bybit_2, mirror; short-only) | Trail 5×, stop 2×, so activation **+1.5 R**. `trail_decay` arms at +2 R → 2.5×. **Stale exit 8 bars below 0 R** shipped (a time stop). TP 3R (reach 0.158, n 146); `tp_revision` FAILS. Live: 0 of 1 amended (n 1). | **Measured-move revision (producer live on the sibling): unit `RQ-20261028-a7c3-02`** (n 68, thin). Stall-pull-in retarget R1: 16.55 vs 14.30 R, n 68 (RQ-20261019-017), but no producer exists for `stall_pull_in`. ER-gate tighten: 15.88 vs 14.30 R, n 68 (0142-04), a one-leg discovery. ADX trail failed its sibling corroboration (511e-01). | **Already has trail + decay + time stop.** Add the measured move if a7c3-02 passes. | 3 · data-backed on PASS |
| **`trend_donchian_sol_prop`** (bybit_2, mirror, breakout_2, tradeify_1, velotrade_1) | Trail 3.5×, stop 2.5×, so activation **+0.4 R**. TP 6R is **unreachable** (reach 0.019, n 370). Live (bybit_2): SL amended on **2 of 3** closes. Prop: trail **not observed** (§ 2). | **Entry TP 2.5R**: screen PASS_NONINFERIOR, OOS +0.041 R/trade, CI95 [−0.025, +0.111], n_oos 126, reach 0.23 (RQ-20261016-004). **Harness confirmation: unit `RQ-20261028-a7c3-03`** (n 403). 3R plus measured move FAILED (bea9-03). The FVG level trail cut drawdown at a cost of ≤ 2 R (F30 55.25 vs 53.46 R, f08c-06), a prop-drawdown option, not proposed. | **TP 2.5R after a7c3-03 plus a prop EV re-run.** Prop TP revision is BUILD-gated (`prop_trail` passes `take_profit=None`). | 3 · operator (prop superset) |
| **`trend_donchian_eth_prop`** (breakout_2, tradeify_1, velotrade_1) | Trail 3.5×, stop 2.5×, so activation **+0.4 R**; `trail_decay` arms at 2.99 R. TP 6R unreachable (reach 0.009, n 1004). **Prop trail not observed amending** (§ 2). | **Trail 4.5× (looser)**: 122.04 vs 76.02 R over ~1,070 trades, 6 of 6 folds, maxDD 21.68 vs 21.16 (RQ-20261016-010); prop EV gate PASS on all three firms (RQ-20261018-028/-040/-041). Caveat: the 2026-08-13 shorter-window walk-forward read 3 of 6. K* 2.5R is INDETERMINATE (CI [−0.066, +0.006], n 870). | **First prove the prop trail runs** (`RM-AM-PROP-TRAIL-OBSERVE`). Then a Tier-3 packet: trail_mult 3.5 → 4.5. | 3 · operator |
| **`iaum_pullback_1d`** (alpaca_live) | Trail 4×, stop 2×, so activation **+1.0 R**; `trail_decay` (stall 10 → 2.0×) shipped. TP 3.5R (calibrated pooled K*; reach unmeasured); `tp_revision` FAILS. Live: 0 of 1 amended (paper sibling 1 of 1). The Alpaca amend has **no venue read-back**. | **None measurable**: coverage `insufficient_base` (IS n 31, OOS n 4). No unit settles it in 1–2 days. | **Cost-neutral: keep the declared trail + decay**, and land `AMEND-PARITY-ALPACA-TRAIL-READBACK`. An optional GLD-proxy tp_extend unit is the operator's call (`RM-AM-IAUM-COSTNEUTRAL`). | 3 · operator |

**On the candidate list in the dispatch.**

- **Real predictive TP and TP revision.** Adopted per leg above.
- **Partial take-profit.** Not proposed. Graded passes among partial/bank units: xrp_pb 0 of 12, ada 0 of 10, eth_4h
  0 of 6, xrp_4h 0 of 5, sol_prop 0 of 6. The 8 eth_prop "partial" passes are prop-fit units on other symbols,
  misclassified by the keyword split. Principle T10 says partials are arms, never defaults.
- **Loss-cut at ≤ −0.5 R.** One unit is already registered on ada (#20994), with xrp_pb confirmation in its rule. The
  desk pocket and the LTR rule are both indeterminate, so it is not a default.
- **Time stops.** Already shipped where they passed (xrp_4h stale exit). eth_prop / sol_prop holdouts were not
  replicated (`d37f-11/12`).
- **CHOP-gated trail (`ed1c-10`).** Passed on **BTC 1h**, which is not a real-money leg; its confirmation is authored in
  #20994.
- **Breakeven floor (`ed1c-17`).** Passed on `trend_donchian_eth` (1h paper sibling: BE075 80.26 vs 54.13 R), lost on
  the LTR fresh window (−0.041 R), and failed once on each real-money leg. It conflicts, so it is not shipped.
  Confirmation is in #20994.
- **The 6 surviving passes.** `0142-04` is the xrp_4h ER-gate (thin). `0142-16` is eth_pullback_2h, not a money leg.
  `f08c-06` is the sol_prop level trail. `f08c-13` is ada_4h, not a money leg. `ed1c-10` is BTC. `ed1c-17` is the paper
  ETH 1h leg.
- **Direction filter.** An entry gate, not active management. It goes to the owning row per the programme review.

## 1b. The full bracket action space on the real-money legs, mapped to DESK plan § 5b classes

DESK plan § 5b (PR #21023) is **the single per-class registry**, and this section extends it to the real-money legs
rather than defining a parallel one. Two kinds of evidence answer two different questions:
- **A declared rule.** This is a leg's YAML exit param, which changes the Stage-0 book itself. It is gated by the
  `exit-refinement` gate on the leg's own config-exact history: Path A/B plus walk-forward, or, for TP-doctrine
  compliance, the zero-materiality bar. It is Tier 3.
- **A live, market-triggered intervention** on top of that book (LTR, desk, or the P6 model). It is gated by § 5b's
  template: fresh OOS, n ≥ 126, a CI lower bound > 0 vs hold AND vs a matched random intervention, net of cost, per leg ×
  regime.

**Where § 5b's bar is stricter than this plan's TP units.** The TP units here use the doctrine's compliance
(non-inferiority) bar. That is deliberate: the TP doctrine is binding, and it makes a P&L-neutral prediction the
required answer. It is raised here, not resolved by editing either side (principles doc "What this is not").

**Population.** Graded units per class are counted over the 7 real-money legs, from `research/queue` grading blocks on
2026-10-28, with the keyword classification of § 1.

| § 5b class | mechanic on the real-money legs | what is measured (Stage 0, declared rule) | gap → cheap test (1–2 days) |
|---|---|---|---|
| `tighten_sl` (rule) | declared ATR trail with X-R activation (all 7 legs); `trail_decay` (eth_4h, xrp_4h, iaum, eth_prop) | The trail IS the Stage-0 book. Tighter variants: gated-trail units 7 of 58 graded pass, some of them label studies rather than levers, the rest thin or uncorroborated; BE floor fails once per leg. | none: tighten is lowest priority (§ 0); the live class stays advice-only |
| `widen_sl` (static) | a looser trail | eth_prop trail 4.5: 122.04 vs 76.02 R, 6 of 6 folds, prop EV ×3 PASS; xrp_pb trail6 wf_fail; most m20 trail_geometry cells honest_negative | Tier-3 packet `RM-AM-ETHPROP-TRAIL45` |
| `widen_sl` (conditional: ATR expansion / sweep) | none | **No harness lever exists** (`trail_vol` takes `min`, so it can only tighten); S0 enum has no widen | build `RM-AM-WIDEN-HARNESS` (~1 day), then one unit per family |
| `move_tp` extend | `donchian_measured_move` (eth_4h, declared and live); `tp_extend` (producer merged, undeclared) | eth_4h MM 115.95 vs 99.23 R; tp_extend X6 family read 3 of 3 | units **a7c3-01** (ada), **-02** (xrp_4h), **-04** (eth_4h entry TP); `TPX-XRP-DECLARE` |
| `move_tp` pull in | none live; `stall_pull_in` is harness-only | xrp_4h R1 16.55 vs 14.30 R (n 68) PASS; `tp_retarget` pending on the other legs | units **a7c3-05** (xrp_pb), **-06** (ada); producer `RM-AM-TP-PULLIN-PRODUCER` |
| `move_tp` to a level (entry target) | `tp_r` per leg | sol_prop K* 2.5R screen PASS_NONINFERIOR; eth_prop K* 2.5R INDETERMINATE | unit **a7c3-03** (sol_prop) |
| `partial_close` | none | 0 graded passes on the 5 legs with partial units (§ 1) | none (T10; § 5b lowest priority) |
| `close` (time / loss-cut) | xrp_4h stale exit 8 bars below 0 R (shipped) | the loss-cut is not shown (labels: hold beats close at ≤ −0.5 R by +0.089 R); time-stop holdouts not replicated | `P1-Q4-desk-losscut-ada-pb` (#20994); § 5b E1 |

## 2. Infra maturity checklist for active management (measured 2026-10-28 ~21:05Z)

| area | item | read | state | row |
|---|---|---|---|---|
| **The mechanic itself** | Bybit monitor trail → `modify_open_order` | SL amended on 7 of 35 real-money closes across 5 legs; TP amended on 2 of 9 (eth_4h) | **OK** (observed) | — |
| | Alpaca trail amend | 0 of 1 real-money closes amended; 2xx is treated as ok, with no read-back | **gap** | `AMEND-PARITY-ALPACA-TRAIL-READBACK` (T3, queued with operator) |
| | Prop VM trail (tradeify_1, velotrade_1) | per-tick `{"trail": {"mode": "live", "deps": "importable"}}` in 143/154 lines; 0 amend lines in the readable window | **unproven** | `RM-AM-PROP-TRAIL-OBSERVE` |
| | Prop phone trail (breakout_2) | 0 of 13 closed tickets carry `phone_trail.amend`; `PROP-TRAIL-PHONE` landed_unproven since 2026-10-08 | **unproven** | `RM-AM-PROP-TRAIL-OBSERVE` |
| | TP revision producers | `donchian_measured_move` declared on 1 leg and live; `tp_extend` producer merged, declared on 0 legs; `stall_pull_in` not built; prop TP path absent | **gap** | per-leg rows above; `TP-DOCTRINE` B2 |
| **Triggers and wakes** | VM `live_review_due` route | `read_state: looked`; 8 open, 3 due, oldest due bar 2026-10-28T00:00Z; `packages_with_events_could_not_look` **7 of 8** | **gap** | `RM-AM-DUE-COULDNOTLOOK` |
| | Market-driven due events | `LTR-1B-MARKET-TRIGGERS` in_flight; practice redesign landed (operator: *"Turn wake-ups on today"*) | **building** | existing |
| | Manager routines (hourly refill, 3h check-in, twice-daily review, weekly reviews) | all enabled; last fired 20:28Z / 18:18Z / 17:52Z (`list_triggers`) | **OK** | — |
| **Reviews and packets** | `comms/live_review/reviews.jsonl` | 124 rows from 2026-10-25T16:30Z to 10-28T17:15Z: hold 53, no_recommendation 46, flag_mechanics 23, close 2 | **OK** (running) | — |
| | Mechanics read in the packet | 23 of 124 flag mechanics; order reads intermittently unreachable | **gap** | `LTR-PACKET-READ-REACH`, `LTR-MECHANICS-SIBLING-SLICE-FALSE-MISMATCH` |
| | "Trail should have moved" check | nothing computes it | **gap** | `RM-AM-TRAIL-EXPECTED-DETECTOR` |
| **Apply path and mandate** | `config/live_trade_review.yaml::apply_mode` | `apply`; `MD-TRADE-DESK` and `MD-LIVE-TIGHTEN-SL` are under `mandates:` | as declared | — |
| | Applies to date | `applied: false` on 124 of 124 rows on main and 27 of 27 on `live-review/rows` | **never exercised** | — |
| | Tighten advice-only (operator popup ~20:35Z, *"Advice-only tightens"*) | being built: one HOLD PR from lane LTR-TIGHTEN-OPTIMIZE (VM rows watcher never executes `tighten_sl`) | **building** | `LTR-TIGHTEN-OPTIMIZE` |
| | Per-account apply | Bybit dry-run 6 of 6 approve (LTR-6R note); prop `LTR-8` queued; Alpaca `LTR-9` in_flight | **gap** | existing |
| **Grading and feedback** | Reviewer grading into `/performance-review` (C6, § Live review) | wired (`LTR-5` landed_unproven); `outcomes.jsonl` 11 rows | **thin** (accruing) | existing |
| | Exit-mechanic grading | coverage matrix plus `exit-refinement` P7 first-decision check; real-money giveback census n 7 (`insufficient_n`) | **thin** (accruing) | census weekly |
| **Alerts** | Daily DD switch | `armed: true` on bybit_2, bybit_portfolio, alpaca_live, breakout_2, tradeify_1, velotrade_1 (config read) | **OK** as declared; firing not observed | `DAILY-DD-SWITCH` |
| | Silent trail failure | no alert exists | **gap** | `RM-AM-TRAIL-EXPECTED-DETECTOR` |
| | Per-amend Telegram ping | not checked this session | **unverified** | — |
| **Standard** | A new real-money leg without a trail / TP grade | nothing refuses it | **gap** | `RM-AM-STANDARD-GUARD` |

## 3. Day-by-day to the week-end milestone

"Week end" means **Tue 2026-11-03 23:59Z**, before the Wednesday reset. Costs are plan-session estimates; nothing
spends API credits. Units run on GitHub runners.

| day | work | owner | cost | operator approval needed |
|---|---|---|---|---|
| **Wed 10-28 (tonight)** | This PR lands: 4 units, 11 rows. The research dispatcher can fire a7c3-01..04 (cpu_light, ~25–35 min each). | this lane → dispatcher | ~$10 (this lane); runner time | none |
| **Thu 10-29** | Thursday planning adopts the milestone (§ 0). Dispatch `RM-AM-PROP-TRAIL-OBSERVE` (Sonnet) and `RM-AM-DUE-COULDNOTLOOK` (Sonnet). Read a7c3 results as they land. Merge the advice-only tighten PR. | manager; 2 lanes | ~$8 | **(1)** milestone scope as stated in § 0 (popup). **(2)** iaum option (a) vs (b). |
| **Thu–Fri** | **Primary path:** `ML-LIVE-PROMOTION-PLAN` builds P6 (labels, then the hold-biased model and its gate). This plan's `RM-AM-EXIT-ML-WIRING` (Opus) builds the intent → LTR apply wiring against a constant-hold stub, in shadow on `bybit_1` / `alpaca_paper`. `RM-AM-WIDEN-HARNESS` (Opus, ~1 day) and `RM-AM-TP-PULLIN-PRODUCER` (Opus, Tier 2, inert) build. Units a7c3-05/-06 run. | model lane; 3 build lanes | ~$30 | **(10)** Tier-2 merge of the pull-in producer (inert by config). |
| **Fri 10-30** | `RM-AM-TRAIL-EXPECTED-DETECTOR` (Opus) and `RM-AM-STANDARD-GUARD` (Opus) build. For each a7c3 PASS (doctrine read clean), draft the one-line declare PR (HOLD). If the prop trail reads BROKEN, file the Tier-2 fix. | 2 lanes; manager | ~$16 | **(3)** each data-backed declare: the manager may ship and notify under § Data-backed Tier-2/3; a popup only if the read is ambiguous. **(4)** Tier-2 prop trail fix, if needed. |
| **Sat–Sun 10-31..11-01** | Declares deploy (git-sync), with a deployed-SHA check. The first live TP amend per newly declared leg is the mechanical soak (1–2 trades). xrp_pb: the second closed trade unlocks `TPX-XRP-DECLARE`. | manager | ~$3 | **(5)** `TPX-XRP-DECLARE` (operator's own condition). |
| **Mon 11-02** | eth_prop trail 4.5 packet once the prop trail is observed; sol_prop prop EV re-run at TP 2.5 if a7c3-03 passed. Alpaca read-back (`AMEND-PARITY-ALPACA-TRAIL-READBACK`). | lane; manager | ~$6 | **(6)** eth_prop trail 3.5 → 4.5. **(7)** sol_prop TP 6 → 2.5 (prop superset). **(8)** the Alpaca read-back (T3, queued). |
| **Mon–Tue** | If P6 passes its gate: shadow model advice on the demo floor shows ≥ 1 priced non-hold call per class it emits; ask the operator about real-money advice-only. If P6 has not passed: the milestone stands on the declared mechanics (trail + TP revision), and the model carries into next week. | manager | ~$3 | **(11)** model advice on real money (advice-only; execution per class only after § 5b). |
| **Tue 11-03** | Milestone readout: per leg, mechanic declared / observed / evidence ref, detector and guard live. The standard guard baselines any remaining debt as visible lines (adding a real-money line is the operator's act). | manager | ~$3 | **(9)** the guard's baseline lines for real-money and prop debt. |

Total ≈ $79 plan spend over the week, plus runner time and the model lane's own budget.

**Done when (row `RM-ACTIVE-MGMT-MILESTONE`):**
- every real-money leg has its trail OBSERVED amending on every account class that carries it, or a filed break;
- the detector and the guard are live;
- every TP-revision candidate is declared, refused with its verdict, or put to the operator.

Merged ≠ deployed ≠ observed is reported separately per leg.

## 4. What this plan does not do

- It changes no config, mandate or roster.
- It proposes no tightening default; the evidence above refuses one.
- It does not treat a live or paper book as edge evidence. The live amend counts are **mechanics** reads, with n ≤ 11
  per leg.
- It does not quote the roster or the TP-guard counts as fixed: re-run `check_tp_doctrine.py` and re-parse
  `config/accounts.yaml`.

**Not verified in this session:**
- the VM deployed SHA for `TPX-PULLBACK-PRODUCER`;
- per-amend Telegram pings;
- whether any prop position reached its 0.4 R activation in the journal window I could read (2,000-line cap).
