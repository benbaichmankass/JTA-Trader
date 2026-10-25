# Live trade review — a routine that reviews OPEN trades against the market (design, 2026-10-25)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**State: DESIGN ONLY. Nothing below is built, and no checklist row or mandate exists for it yet.**
The operator reviews this first; § 7 lists the rows to file once it is approved.
Checklist row: `LIVE-TRADE-REVIEW-DESIGN` · roadmap `L-ATM` · Tier 1 (a doc).

## 0. The request, and the precedent

The operator, 2026-10-25, verbatim (quoted on row `LIVE-TRADE-REVIEW-DESIGN`):

> *"I also want us to create a routine for having a Claude session that reviews live trades. We recently had an ADAUSDT trade that looked like the sl was too far and we needed to start banking R - Claude suggested to tighten and we did, and helped lock in gains. I want a routine that checks live trades to check the strategies real time performance against market conditions so that we can improve performance - it seems like we're somewhat limited in that we only review results and not real-time performance, which could be a strong lever for improving strategy and ml performance."*

The precedent is `ADA-LIVE-EXIT-REVIEW-1024` ([`docs/research/ada-live-exit-review-2026-10-24.md`](../research/ada-live-exit-review-2026-10-24.md)). It is worth reading closely, because it sets the shape of this design:

1. **The lane checked the mechanics first.** The live stop matched the 5.0 × ATR trail "to the tick". That settled the question "is this a bug?" before anything else.
2. **It found a structural fact the backtest knew and nobody had looked at.** The trail sits 5.0 / 1.5 = 3.33 R behind the best price and the target is 4 R. So on that leg **the trail can never lock more than +0.67 R before the target fills.**
3. **It priced every option against the leg's own history, conditional on the live state.** On the A arm, n=32 trades reached MFE ≥ 3.4 R. Holding gave mean +3.19 R, worst +0.28 R. Tightening gave mean +2.96 R, worst +2.32 R.
4. **The data said "leave it"; the operator chose to tighten for lower variance.** Tightening cost about 0.23 R expected and removed the giveback tail. The stop moved to 0.2053 through `amend-position-sl` (#19913) and locked about +2.5 R.
5. **The repeating part became research, not a habit.** That is PR #19891, with units 4ef5-01 (a profit-lock step) and 4ef5-02 (base trail width).

Two lessons follow, and the rest of this design rests on them:

- **A live review is a pricing exercise, not a hunch.** Its core is *"what did this leg's own history do from this exact state?"* That needs a tool; today a lane did it by hand for about $8.
- **The ADA tighten was a risk preference, not an edge call.** Automating it means the operator states that preference **once, with a price on it** (§ 6, Q1). A session must never decide, trade by trade, that variance matters more than EV.

## 1. Trigger — run only when there are open trades AND something changed

### Constraint that decides the shape

**Nothing on the VM or in CI can wake a Claude session.** The only wake hop is `create_trigger` + `fire_trigger`, which are MCP tools CI does not hold. The operator ruled out minted credentials for CI on 2026-09-02 (*"no minted tokens, ever"*); see `scripts/ops/blocked_lane_watch.py` § "WHAT THIS DOES NOT DO". So the design cannot be "the VM wakes Claude when a trade opens". The cheapest correct shape is a **token-free condition computed on the VM, plus a cheap scheduled check that reads it.**

A second fact, MEASURED from `/api/diag/position_telemetry?limit=300` at about 13:27Z today (300 rows: 7 open · 136 closed · 157 never filled): **7 packages are open across 3 accounts** (bybit_2: 2; alpaca_paper: 3; ib_paper: 2). INFERRED from that and from the daily and 2h rosters: the book is rarely empty. So *"only when trades are open"* will save little on its own. **The saving has to come from "only when something about an open trade changed"**, which is the event layer in § 2.

### Proposal (three layers)

| layer | what | runs where | cost |
|---|---|---|---|
| **L0 — due computation** | `GET /api/diag/live_review_due`, a **pure read**. It joins `position_telemetry` (open rows), the open `order_packages` and closed candles. It subtracts what the last review already covered, read from `comms/live_review/reviews.jsonl` on `main`, which `ict-git-sync` pulls every ~5 min. It returns the due packages with the event that made each due (§ 2). It writes nothing and adds no writer to the exit loop. | live VM, FastAPI | $0 |
| **L1 — gate routine** | A recurring routine: `create_trigger`, `create_new_session_on_fire: true`, **Haiku**, hourly at :04. That minute is after the 2h, 4h and 1d Bybit closes on the hour and after the 20:00/21:00Z US-equity close. Its whole job: `scripts/ops/diag_fetch.sh live_review_due`. **Empty → it ends its turn at once.** Non-empty → it calls `create_session` for one reviewer (L2), passing the due list, and ends. | Claude routine | one short Haiku session an hour |
| **L2 — reviewer** | One session reviews **the whole due set together**, because correlated open positions are part of the input. Model per the manager's model table: **Opus** when any due package is on a real-money or prop account; Sonnet when only paper is due (if paper is in scope at all, Q2). | Claude session | § 2 estimate |

Also, at no cost: the hourly `ict-work-digest` carrier gains one line, `🔎 live review due: N packages (oldest Xh)`, when L0 has been non-empty for 2 hours or more with no review recorded. That is the backstop if the routine dies. It is one more `attention_watch` probe, in the existing ok / breached / unknown shape.

### Alternatives considered

| alternative | why not (or not first) |
|---|---|
| The VM wakes a session when a trade opens | Impossible under "no minted tokens". This is the constraint above, not a preference. |
| A GitHub Action running Claude Code (`claude-code-action`) | Needs an API credential in CI, which is the same rule. |
| The manager polls the book | It couples a real-time duty to the manager being alive and in context, and it spends the most expensive context on a `[]` read. Rejected. |
| A VM-side Messages API call with the M13 insights key (`src/runtime/insights/generator.py`) | Truly event-driven and cheap per call, but it has no repo, no tools and cannot verify its own inputs. The key's current validity is **UNVERIFIED** this session. Kept as a possible later "triage" layer, never as the reviewer. |
| The gate session runs Opus and exits early | A no-op costs about the same tokens on any model (session-start context dominates), so the price difference is pure waste. Haiku gates; Opus reviews. |
| Only the operator triggers reviews | That is what happened with ADA. It depends on someone looking at the chart. |

**Latency, stated plainly:** an event is seen within about 60 minutes (the routine floor is hourly). **The reviewer is not the protection.** Every position's venue SL/TP and the order monitor's trail run every ~30 s on the VM whatever the reviewer does. The reviewer improves exits on a bar-to-hours horizon; it never catches a crash.

## 2. Frequency — closed-bar timer plus event triggers, deduped

### Timer

**At most one review per package per closed bar of that leg's timeframe**, and only when the bar changed something. A closed 2h bar alone does not make a package due; it opens the window in which an event can. Today's real-money roster runs on 2h / 4h / 1d (read from `config/accounts.yaml` rosters of bybit_2, bybit_portfolio, alpaca_live and the prop accounts). So the natural ceiling is 12 reviews a day per 2h package, and far fewer in practice.

**Floor:** every open real-money or prop package is reviewed at least once a day, even if quiet (`event: daily_floor`). A trade nobody looks at for days is how *"the stop moved, but way not enough"* went unnoticed.

### Events (L0 computes them; every threshold is a proposed default, registered in config before the first run)

| event | fires when (proposed default) | why |
|---|---|---|
| `r_milestone` | `open_r` first crosses +1 R, +2 R, +3 R, then every +1 R | The ADA moment: the trail geometry stops matching the trade. |
| `new_peak` | `peak_r` ≥ last reviewed peak + 0.5 R | MFE is what every exit lever is tuned on. |
| `giveback` | `peak_r` ≥ 1 R and `giveback_r` ≥ max(0.5 R, 30% of peak) | The tail the ADA tighten removed. |
| `near_target` | `r_to_target` ≤ 0.5 R | TP doctrine clause 3: extend or hold the target? |
| `swing` | close-to-close move ≥ 2 × ATR within one bar of the leg | "Big price swings", in the leg's own units. |
| `vol_regime` | current ATR / entry ATR ≥ 1.5 or ≤ 0.67, or the `(trend, vol)` cell changed since entry | The trade is now in a market the entry did not see. |
| `funding` | perp funding beyond the leg's backtest assumption by ≥ 3× (Bybit) | A cost the backtest priced at a constant. |
| `calendar` | a high-impact event within the next bar, from the feed the news veto already reads (verify the source at build) | Known volatility ahead of an open trade. |
| `mechanics` | live SL or TP differs from what the leg's code would place, or venue and journal disagree | ADA's first check. This is a **bug**, so it routes to the order-path owner, not to exit judgment. |
| `daily_floor` | no review of this package in 24 h | The floor above. |

**Dedupe:** key each event on `(order_package_id, event, level)`. One `r_milestone` fires once per level, and a `giveback` fires again only after a new peak. **Cooldown:** one closed bar per package, except `giveback` and `mechanics`. **Batching:** everything due in one L1 tick goes to one reviewer session.

### Volume and spend — INFERRED estimates, with the method stated

- Gate: 24 Haiku sessions a day. Most end after one tool call.
- Reviewer: with about 7 open packages (today's count) and the event filter, I expect **3–8 reviewer sessions a day**. No measurement exists; L0's due log will give the real number within days.
- Plan bar, using `spend_meter.py --capacity`'s own unit: it read *weekly 34%, sustainable rate 20.7 pp/day, 1.00 pp per lane-hour* at 12:30Z today (MEASURED). A reviewer session should take 10–15 min, so about 0.2 pp. That gives **0.6–1.6 pp a day**, plus about 0.3 pp a day for the gate: **roughly 4–9% of the sustainable daily rate**. The real check is reading the meter after the first week.
- Dollars, INFERRED by scaling from the ADA lane: about $8 for a full review **plus** five backtest arms. A routine review uses a precomputed pricing tool (§ 3), so I expect about $1–2 on Opus. With the gate at about $0.05–0.15 a run, that is **about $25–110 a week**. This is an estimate to be replaced by the meter, not a budget.
- **No cap that stops reviewing.** If reviewer sessions exceed 15 in a day, that is one red flag to the manager (a threshold mis-set, or a market event), and the routine keeps running (Prime Directive rule 7).

## 3. What the session does

### Inputs, per due package (all readable today unless marked BUILD)

| input | source |
|---|---|
| entry, risk per unit, SL, TP, trail state, levers declared | `order_packages` (+ `signal_logic`, meta), `config/strategies.yaml` |
| `open_r`, `peak_r` (ESTIMATED from bar extremes), `giveback_r`, `bars_held`, `bars_since_peak`, `r_to_stop`, `r_to_target`, `rr_from_here` | `/api/diag/position_telemetry` |
| venue truth: resting SL/TP, size, mark, and every mirror leg | `/api/diag/bybit_open_orders`, `exchange_positions`, `alpaca_open_orders`; prop tickets |
| ATR now vs at entry, HTF trend, `(trend, vol)` cell now vs at entry | candles, `config/regime_policy.yaml` cell definitions |
| **the leg's conditional outcome table from this state** | **BUILD (LTR-0):** `scripts/ops/live_review/conditional_outcomes.py`. It reads the leg's Stage-0 evidence trade list (`comms/strategy_evidence/<leg>.json` source_run). It conditions on MFE reached ≥ the live peak and on bars held (± regime cell), and replays the candidate actions — hold, tighten to k × ATR from the extreme, a breakeven or profit-lock floor (`--be-floor-lock-r` from #19891), close half. It reports n, mean, sd, worst, P(giveback > 50% of peak), **net of the full cost stack** (`execution_costs.resolve_cost_policy()`). This is the ADA table, as a tool. |
| the leg's live-vs-backtest verdict and cost-fidelity verdict | the existing soak / cost-fidelity records |
| ML heads, if any are served for the leg (exit heads, the vol-regime head) | registry / shadow predictions. **Advisory input only**, at the stage the ladder gives them. |
| correlated open exposure | every other open package: same direction and correlated symbols (e.g. ADA + XRP both short, which is crypto beta), on the same and on other accounts |
| what the previous review said and whether it was applied | `comms/live_review/reviews.jsonl` |

### Decision framework (in order; the skill makes it binding)

1. **Mechanics first.** Does the live SL/TP equal what the leg's code would place? Do venue, journal and mirror agree? If not, the output is `flag_mechanics` and it goes to the order-path owner. No exit judgment is made on a broken trade.
2. **Price the options from history** (LTR-0). If n from this state is below a floor (proposed: 20), the verdict is `hold` + `insufficient_n`. The skill files the data question instead of guessing. That is the 2026-09-29 rule: *"either we have enough data to decide, or we don't and then getting that data becomes a task."*
3. **Overlay what the backtest could not see**, each item with its evidence: a regime or vol cell change since entry, funding outside the assumption, a calendar event, correlated exposure, and a live-vs-backtest verdict showing that this leg's live exits differ from the harness.
4. **Classify the recommendation:**
   - `hold` — the default.
   - `tighten_sl(level)`
   - `tp_revise(level)` — Tier 3 today; the TP doctrine path.
   - `partial_close` / `close` — always the operator's call.
   - `flag_mechanics`
   - `file_hypothesis` — a repeating pattern, for § 5.
5. **Separate EV from preference.** Every `tighten_sl` states its **EV cost or gain** and its **worst-case improvement** from the table, e.g. ADA: *"−0.23 R expected, worst case +0.28 → +2.32 R"*. It is auto-applicable **only** inside the bound the operator sets in Q1.

### Output schema (one row per package per review; `comms/schema/live_review.schema.json`, BUILD LTR-2)

```json
{
  "review_id": "LR-20261025T1404Z-<pkg>",
  "order_package_id": "pkg-…", "trade_id": 6726, "leg": "ada_pullback_2h",
  "accounts": ["bybit_2", "bybit_portfolio", "bybit_1"],
  "trigger": {"event": "r_milestone", "level": 3, "l0_snapshot_at": "…"},
  "state": {"open_r": 3.44, "peak_r": 3.51, "peak_provenance": "estimated",
            "giveback_r": 0.07, "bars_held": 17, "sl": 0.2154, "tp": 0.1988,
            "atr_now_over_entry": 1.0, "regime_cell_now": "…", "regime_cell_entry": "…"},
  "mechanics": {"verdict": "match", "evidence": "trail 5.0×ATR from extreme = venue SL"},
  "options": [
    {"action": "hold", "n": 32, "mean_r": 3.19, "sd_r": 1.35, "worst_r": 0.28},
    {"action": "tighten_sl", "level": 0.2053, "n": 32, "mean_r": 2.96, "sd_r": 0.56, "worst_r": 2.32}
  ],
  "outcome_table_source": "comms/live_review/tables/<review_id>.json",
  "recommendation": {"action": "tighten_sl", "level": 0.2053,
                     "ev_delta_r": -0.23, "worst_case_delta_r": 2.04,
                     "basis": "preference_within_bound | ev_positive | operator_ask",
                     "confidence": "measured | suggestive | anecdote"},
  "context_flags": ["correlated: xrp_pullback_2h short open"],
  "disposition": {"route": "auto_applied | recommended | operator_ask | none",
                  "mandate": "MD-LIVE-TIGHTEN-SL", "action_issue": 19913,
                  "applied_at": "…", "verified_readback": true},
  "model": "<serving model>", "session": "session_…"
}
```

(The values are the ADA case, to show the shape; they are not new measurements.)

### Guardrails (in code where possible; the prompt is the last line, never the only one)

- **Tighten only, never widen.** `amend_position_sl.py` already refuses a looser stop against the package stop, every leg's `trades.stop_loss` and every resting venue stop (exit 2).
- **Never add risk:** no size change, no new entry, no re-entry, no TP move farther away under a mandate.
- **A noise floor:** the new stop must sit at least `min_buffer_atr` (proposed 1.0 × the leg's ATR) beyond the mark, and at most one amend per package per closed bar. **BUILD (LTR-6), enforced inside the script**, not only in the prompt.
- **Never on a read that could not look** (exit 3), and never when venue and journal disagree; that is `flag_mechanics`.
- **Mirror identical by construction:** the amend moves the shared `order_packages.sl` and every leg of the package (live + mirror + soak). That is what the script does today.
- **Prime Directive:** the reviewer never writes `mode:`, never sets `execution: shadow`, never halts anything, and never closes a position on its own.

## 4. Auto-apply — what must be built

| piece | build | tier |
|---|---|---|
| **The apply path (Bybit):** a mandate-tagged run of the existing `amend-position-sl` system-action, as a dry-run issue then an apply issue (its current pattern). New flags `--mandate <id> --evidence <path>`. The provenance becomes `live_review_mandate` instead of `manual_amend_operator`. The `min_buffer_atr` and once-per-bar bounds are enforced in the script. The workflow refuses an apply whose evidence file is not on `main`. | LTR-6 | 2 (it moves live stops) |
| **The authorization:** proposed mandate `MD-LIVE-TIGHTEN-SL`, `direction: derisk_only` (it only shrinks open risk), no `autoland` (it is a system-action, not a PR). `fires_when`: a committed review row whose LTR-0 table has n ≥ 20 from this state, `ev_delta_r ≥ −<Q1 bound>`, `worst_case_delta_r > 0`, mechanics `match`, and the level within the guardrails above. `never`: widening, TP, size, close, a read that could not look, or n below the floor. **Only the operator grants it.** This doc proposes it; it does not write it. | LTR-7 | 3 (an operator grant) |
| **The switch:** `config/live_trade_review.yaml::apply_mode: off \| recommend \| apply`, a sanctioned `*_MODE` selector, global with a per-account override. **It is not a halting latch:** no runtime condition writes it, only a commit does. It never stops trading and never stops reviewing; it only decides whether a recommendation applies. Proposed default: `recommend`. | LTR-6 | 2 |
| **Prop, VM-executor accounts** (tradeify_1, velotrade_1): give the prop trail a **tighten floor** on the ticket (`meta.sl_floor`). `prop_trail.plan_trail` then never plans a stop looser than the floor. Today an amend outside the trail would be fought by the next trail pass, which is the same failure `amend_position_sl.py` was built to avoid on Bybit. | LTR-8 | 3 (prop order path) |
| **Prop, phone account** (breakout_2): `phone_trail.request_sl_tighten()`, publishing the tighter stop through the existing one-slot amend channel, as `request_tp_amend` does. The phone's pre-click check and the `human_moved` rules apply unchanged. | LTR-8 | 3 |
| **Alpaca** (alpaca_live, 1 leg): there is no amend action yet. Add an Alpaca branch that reaches `execute.modify_open_order`. This is the lowest priority, since one leg runs on daily bars. | LTR-9 | 2/3 |

**Stays with the operator (Tier 3), always:** TP changes, until the TP-doctrine revision path is armed for that leg; partial or full closes; anything that widens a stop; anything outside the Q1 bound; any action on a prop account until LTR-8 lands. These reach the operator as a manager popup carrying the priced options table, the ADA format.

**Notification contract:** every apply sends the trade-update ping the amend script already sends, tagged with the mandate. It also gets a line in section 1 of the next brief ("taken under mandate") with the review row and table path. Every recommendation that did not apply goes in brief section 3 ("what moved"). Recommendations are not pinged one by one (Q3).

**Why a mandate, not the general data-backed authorization:** that authorization says *"ask first when the action cannot be cleanly reverted"*. A tightened stop that gets hit cannot be undone, because you are out of the trade. So the bound has to be granted once, explicitly, in `config/mandates.yaml`.

## 5. Weekly review flow — the reviewer is graded too

### Records (append-only JSONL in `comms/live_review/`; canonical source = `order_packages` / `trades`, joined on `order_package_id`)

- `reviews.jsonl` — one row per package per review (§ 3 schema).
- `outcomes.jsonl` — one row per reviewed package **when its trade closes**. It holds the actual exit R, plus a **counterfactual for each recommendation**: what the untouched bracket and trail would have done from the review time, replayed on the real candles by the leg's own monitor logic (BUILD LTR-5, `live_review_counterfactual.py`). It is written by the next review or performance pass after the close; it is computed, not declared.

### Who consumes them

**`/performance-review`** gets a new section, "Live review", over the window.

- **Per action class:** n, applied vs recommended-only, mean and worst Δ R (actual − counterfactual), and the hit rate.
- **The reviewer's own grade:** calibration of its `confidence`, plus the A–F rubric applied to the review row, keyed by `review_id` in `comms/claude_strategy_scores.jsonl`.
- **Live-vs-backtest verdicts split *touched* from *untouched* trades.** A mandate-tightened exit is no longer the exit Stage 0 validated. Mixing the two would bias every Gate-2 demotion read.

**`/perf-followup`:**

- **Track 2 (lessons):** reads the reviews as a population.
- **Promotion to research:** **a pattern that repeats** (the same leg, the same state bucket and the same action, 3 or more times) is no longer a live judgment. It is an exit rule. It becomes a pre-registered `exit-refinement` unit, as 4ef5-01 did, so the strategy's own `monitor()` does it at no cost on every trade, in backtest and live alike. **The reviewer's success measure is making itself unnecessary for each pattern it finds.**
- **Track 3 (extrapolation):** carries a pattern found on one leg to its siblings.

**ML:** `reviews.jsonl` + `outcomes.jsonl` form a labelled dataset (state at review → realized vs counterfactual R). That is the input an E0/E1 exit head in `exit-refinement` trains on. It is filed to the ML plan, not built here.

**The loop's own alarm:** if applied actions net Δ R < 0 over the last 20 or more applies, the next performance review proposes `apply_mode: recommend`. That is a proposal through the normal path, never an automatic flip.

## 6. Open questions for the operator (preferences only; no data settles these)

**Q1 — Variance vs EV: how much expected R may an automatic tighten give up to cut the worst case?** ADA cost about −0.23 R for worst case +0.28 → +2.32 R.
- (a) **0**: auto-apply only when history says tightening is EV-neutral or better. Every ADA-type case is then still asked.
- (b) **≤ 0.25 R**, with the worst case improving by ≥ 1 R. This would have auto-applied ADA. **This is my recommendation**, because it matches the choice you made on ADA.
- (c) **≤ 0.5 R.**

**Q2 — Scope: real-money + prop only, or paper (Stage-1) books as well?**
- Recommended: **real-money + prop for review and apply**, plus **paper record-only on Sonnet**. Paper rows add data for § 5 at about a third of the cost, and nothing is applied there.
- Alternatives: real-money + prop only, or everything.

**Q3 — Pings: applies and asks only, or every recommendation?** Recommended: **applies and asks only**. Everything else goes in the brief, so Telegram stays one hourly message plus real events.

**Q4 — First applies: should the first few mandate applies go out as a one-click popup** ("apply this tighten?") before full auto, to check the plumbing on real money? Recommended: **the first 2 applies by popup, then auto.** That mirrors the mechanical soak rule: 1–2 clean executions, no calendar.

## 7. Build plan (rows to file after approval; NOT filed by this PR)

| order | id | what | tier | model | ceiling |
|---|---|---|---|---|---|
| 1 | `LTR-0-CONDITIONAL-OUTCOMES` | The pricing tool (§ 3): conditional outcome table per leg and state, net of the full cost stack, from the Stage-0 evidence trade list. Tests against the ADA numbers (n=32, +3.19 / +2.96). | 1 | Sonnet | $8 |
| 2 | `LTR-2-RECORDS` | `comms/live_review/{reviews,outcomes}.jsonl` + schema + a validator guard | 1 | Sonnet | $4 |
| 3 | `LTR-1-DUE-WATCH` | `GET /api/diag/live_review_due` (pure read) + `scripts/ops/live_review_due.py` + the `attention_watch` backstop probe; thresholds in `config/live_trade_review.yaml` | 1 (read path) | Sonnet | $8 |
| 4 | `LTR-3-SKILL` | `.claude/skills/live-trade-review/SKILL.md`: the § 3 procedure, binding | 1 | Opus | $6 |
| 5 | `LTR-4-ROUTINE` | The manager creates the hourly Haiku gate routine; reviewers spawn per § 1; **`apply_mode: recommend`** | 1 | Haiku (gate) / Opus (reviewer) | $3 to set up |
| 6 | `LTR-5-GRADING` | Counterfactual replay + the "Live review" section in `/performance-review` + `/perf-followup` Track 2 hooks | 1 | Sonnet | $8 |
| 7 | `LTR-6-APPLY-PATH` | `amend_position_sl.py` `--mandate/--evidence`, provenance `live_review_mandate`, `min_buffer_atr` + once-per-bar bounds in code, the evidence-on-main check in the workflow, the `apply_mode` switch | 2 | Opus | $10 |
| 8 | `LTR-7-MANDATE` | Propose `MD-LIVE-TIGHTEN-SL` with the Q1 bound; **the operator grants it** | 3 (grant) | — | — |
| 9 | `LTR-8-PROP-TIGHTEN` | `sl_floor` in `prop_trail.plan_trail`; `phone_trail.request_sl_tighten` | 3 | Opus | $12 |
| 10 | `LTR-9-ALPACA-AMEND` | An Alpaca branch for the amend action | 2/3 | Opus | $8 |

Rows 1–6 produce a working **recommend-only** reviewer, entirely Tier 1. Auto-apply begins at rows 7–8. Every row carries `roadmap: [L-ATM]` and a `writeback` to the L-ATM milestone and to `ARCHITECTURE-CANONICAL.md` (order monitor / TP doctrine neighbourhood).

## 8. Risks

| risk | mitigation |
|---|---|
| **The reviewer second-guesses validated exits.** Live results drift from Stage 0, and the Gate-2 demotion read is contaminated. | Applies only inside the Q1 bound. Touched and untouched trades are split in every verdict. Repeats become exit rules, which are backtested like any other (§ 5). |
| **Noise stop-outs from a tight stop** | `min_buffer_atr` and once-per-bar, enforced in code. The ADA history showed the harness fills a stop at the stop price, so the real cost of tightening is, if anything, larger than the table says. LTR-0 must state that bias, not hide it. |
| **Thin history** (most leg × state cells have small n) | An n floor gives `hold` + `insufficient_n`, and the data question is filed. No verdict is invented. |
| **Stale or estimated inputs** (`peak_r` comes from bar extremes; L0 lags `main` by about 5 min) | Every apply re-reads the venue first (the script already does). A peak marked `estimated` is never treated as measured. |
| **Fighting the monitor's own trail** | Solved on Bybit by moving `order_packages.sl`. Prop needs LTR-8 before any prop apply. |
| **Spend creep** | A Haiku gate, events plus cooldown, one batched session per tick, a red flag at 15 sessions a day (never a stop), and the meter read after week 1. |
| **The routine dies silently** | The `attention_watch` "review due ≥ 2 h, none recorded" line in the hourly digest. |
| **Confident wrong recommendations** | Mechanics-first, a table-backed price on every option, calibration graded weekly, and a `confidence` field that may say `anecdote`. |
| **Coverage gap** | `position_telemetry` is written for the donchian/pullback family (its own docstring). Today's real-money roster is entirely that family (INFERRED from the leg names), but a new family needs telemetry before it can be reviewed. L0 must report "not covered", never treat it as "nothing due". |

## 9. What this lane did and did not do

- **Did:** read the rules, tiers, mandates, the amend and trail paths, the telemetry record and the ADA precedent. Took one read-only diag pull (`position_telemetry`), whose population is stated above, and one `spend_meter.py --capacity` reading.
- **Did not:** place or amend anything, edit any config, file any row or mandate, or measure reviewer cost (§ 2's figures are INFERRED).
