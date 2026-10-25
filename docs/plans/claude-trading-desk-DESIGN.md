# Claude trading desk — a desk-manager session over specialist lanes (design, 2026-10-25)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**State: DESIGN v0.** Nothing below is built by this PR. The operator reviews it, and § 10 lists the
rows the manager files after that.

**Monday comes first** (operator deadline ~17:45Z, relayed by the manager): the desk must be
live-capable when markets open Monday. **§ 0a is the Monday slice.** Everything marked *phase 2* is
scoped but is not on the Monday path. The per-account apply path is being built in parallel by lane
`LTR-6R-APPLY-PATH`, and this design adopts its interface (§ 3.0).
Checklist row: `DESK-DESIGN` · roadmap `L-DESK` (new, G4) beside `L-ATM` · Tier 1 (a doc).

**How to read the marks** (`docs/CLAUDE-RULES-CANONICAL.md` § MEASURED / INFERRED / DECIDED):
every number is **MEASURED** (with where it lives), **INFERRED** (from named inputs; check it), or
**UNMEASURED** (nobody has the number; the row that gets it is named). **DECIDED** marks an operator
choice already on record.

---

## 0. The request, and the short answer

The operator asked for this in chat on 2026-10-25, ~16:12–16:30Z. The full record is on the
`DESK-DESIGN` row (register PR #20116); the manager quoted it as a close paraphrase, not verbatim:

1. **The desk.** A desk-manager session runs specialist lanes: market watch / when to enter, entry
   review, in-trade management (the live trade review, LTR), and adjustments and exits. It runs in a
   sandbox, and every decision is recorded so that the system and the models can execute on it.
2. **Structure.** Claude acts at the strategy-ticket / order-package level, on the trade and market
   conditions. **Every action is routed through EACH account's own risk manager.** Claude never does
   per-account risk management.
3. **The repo builds the context.** Decision packets let Claude spend its usage only on judgment. That
   keeps the pattern consistent and makes the outputs fit the training datasets.
4. **Usage balance.** No usage wasted on routine decisions, powerful models where we learn. *"maybe
   it's enough if Opus is doing the review and not the actual live management."*
5. **Timeframe.** As small as feasible; *"15 minutes is feasible in any case"*. Scope a lane that stays
   live for 10 min – 1 h holds: its cost, whether it can be profitable, which timeframes work.
6. **Same feed for Claude and ML.** Claude's inference becomes training data, and Claude's
   recommendations are an input to the ML live-management pipeline.

**The short answer:**

- **Build it as one standing Sonnet desk session plus spawned lanes, not as one session per role.** A
  lane is a *role*: a packet kind, a decision schema and a skill section. Running each role in its own
  session would pay the session-start context once per role per wake. Separate sessions are spawned for
  only three things: Opus escalations, the Opus blind-teacher batch, and a short-hold lane that lives
  exactly as long as its trade. § 2.
- **The path is fixed: package intent → each account's risk gate → each account's executor.** The gate
  is new: `RiskManager.approve_amend` / `approve_entry`, plus the prop versions. LTR-6, LTR-8 and LTR-9
  are re-scoped into it. A refusal or a silent no-op on any one account is a first-class, alarmed
  outcome. That is the lesson of `PHONE-AMEND-REFUSED-1025`. § 3.
- **Pilot first at 15 min, in shadow, on the open real-money and prop swing trades.** INFERRED: at that
  cadence the session-plus-issue latency is 17–33% of the bar, and the cost is about $4–5 a day (§ 5,
  § 7). **5 min needs two Tier-2 builds first.** Packets must be built on the VM, and intents must reach
  the VM without a GitHub-Actions hop. **1 min is not feasible** with a model in the loop: the latency
  exceeds the bar.
- **No short-hold (10 min – 1 h) leg has a Stage-0 edge today.** MEASURED from
  `comms/strategy_evidence/`: every 5m `ict_scalp` cell is net-negative in 0 of 4 folds, and the best 15m
  cells are +0.017 and +0.054 R/trade with 2 of 4 folds positive. So a short-hold desk lane is **not
  piloted live**. It gets its own Stage 0 first: a confirm run of the two 15m cells, plus a blind replay
  of Claude managing those trade lists. § 6.
- **The desk sits inside the promotion ladder.** It cannot be backtested, so its Stage 0 is a **blind
  replay with paired counterfactuals**. Its Stage 1 is a mechanical soak of 1–2 clean intents per account
  class. Its Stage 2 is mandate-bounded, derisk-only actions on real money. § 8.

---

## 0a. The Monday slice — live-capable by market open (phase 1)

| piece | Monday state | owner / row |
|---|---|---|
| **In-trade role, live** | The standing desk session runs the `live-trade-review` skill on in-trade packets for every open real-money, prop and `bybit_1` package. Cadence: **15 min**, or LTR-4's hourly gate as the fallback if the standing session is not up. **Sonnet** decides; an **Opus** escalation confirms any non-`hold` on real money or prop. | DESK-5 (skill delta), DESK-6 (session), LTR-3 skill as is |
| **Packets** | `scripts/ops/live_review_packet.py --all-open` (PR #20127), run from the session over the relays. It takes 36 s (MEASURED), which is fine at 15 min. A VM endpoint is phase 2. | LTR-11 |
| **Intent → per-account gate → executor** | The LTR-6R interface (§ 3.0): a package-level `LiveReviewIntent` → `RiskManager.approve_amend(intent, account)` per account → that account's existing executor, **account-scoped**. Tighten-only. | LTR-6R (Opus, in flight) |
| **The switch** | `config/live_trade_review.yaml::apply_mode: off \| recommend \| apply`. **Default `recommend`**, with a per-account override. Only a commit writes it; no runtime condition does. It is not a halt latch (Prime Directive rule 7), and it never stops reviewing. | LTR-6R |
| **Evidence to apply** | Each intent cites a committed decision row: `packet_sha`, the LTR-0 option table with n ≥ 20 from this state, `ev_delta_r ≥ −0.25 R`, `worst_case_delta_r > 0`, and mechanics `match`. The account's gate verdict and the venue readback are recorded per account. | LTR-2 records + LTR-6R |
| **Mandate to apply on real money and prop** | `MD-LIVE-TIGHTEN-SL`, `derisk_only`, bound **0.25 R** with a **0.5 R shadow arm**, rollout *"Auto from day one"*. These terms are **DECIDED** by the operator 2026-10-25 ~13:58Z (row `LTR-7-MANDATE`). It must be **written into `config/mandates.yaml`** before any account flips to `apply`. | LTR-7 (manager writes the operator's recorded grant) |
| **Flip order** | 1. `bybit_1` → `apply` first, the sandbox (DECIDED, § 3.6). <br>2. After **1–2 clean applies** there (verdict, venue readback and divergence check all clean), `bybit_2` + `bybit_portfolio` → `apply`. This is the mechanical-soak rule; there is no calendar wait. <br>3. Prop accounts follow only when their executor path (LTR-8, plus the PHONE-AMEND fix for `breakout_2`) has had its own 1–2 clean applies. Until then they stay `recommend`. <br>Alpaca stays `recommend` until LTR-9 lands. | manager, on the evidence |

**Phase 2: scoped below, not on the Monday path.**

- entry review and market watch, both shadow (§ 2.1, § 2.3);
- the short-timeframe standing lane and the short-hold work (§ 5, § 6);
- packets built on the VM, and a VM intent intake (DESK-1, DESK-4b);
- the blind teacher dial (§ 4.2), which can start Monday at ρ = 0.25 in recommend mode at no risk, but is not required;
- D-S0 blind replay (DESK-7);
- grading (DESK-9) and the ML feed (DESK-11).

⚠️ **What "live-capable" does and does not mean on Monday.**

- Real-money applies happen only once three things hold: `MD-LIVE-TIGHTEN-SL` is in `config/mandates.yaml`, LTR-6R has merged (a Tier-3 order-path change), and `bybit_1` has shown 1–2 clean applies.
- Until then the desk is live in `recommend`: decisions are recorded, and asks go to the operator per the LTR Q3 ping rule ("applies and asks only").
- The desk's own Stage 0 (D-S0, § 8) is **not** a precondition for tighten-only applies inside the operator-granted bound. That bound is the operator's priced risk preference (LTR Q1), and the LTR-0 table prices each apply against the leg's history. D-S0 gates everything **beyond** tighten-only.

---

## 1. What exists today (the inputs), measured

| input | state | where |
|---|---|---|
| Live-trade-review design | merged, operator-approved ~13:58Z | `docs/plans/live-trade-review-DESIGN.md` (#20088) |
| LTR decisions on record | Q1 tighten bound **0.25 R**, with a **0.5 R shadow arm**; rollout *"Auto from day one"*; scope *"Real money + prop, paper logged"*; pings *"Applies and asks only"* — **DECIDED** 2026-10-25 | row `LTR-7-MANDATE` note |
| Distillation design | merged, operator-approved | `docs/plans/ml-claude-distillation-DESIGN.md` |
| Distillation decision on record | Q2: Claude as a live decision-time feature is *"Allow as a feature later"*, only after a model proves net-R edge out of sample; teacher use first — **DECIDED** 2026-10-25 | rows `CJ-3`, `CJ-5` notes |
| First live LTR run | 9 open packages, 9 schema-valid rows: 2 real-money, 1 prop, 6 paper. Verdicts: 1 `hold`, 2 `flag_mechanics`, 6 `no_recommendation` — MEASURED | `comms/live_review/reviews.jsonl`, PR #20121 |
| LTR-3 lane cost (skill + 9 reviews + records + PR) | **$13.04** API-equivalent, Opus, 65 min wall; 41.95 M cache-read, 0.38 M cache-write, 81.6 k output tokens; 433 k context at the end — MEASURED | `get_session(session_01R3JNyuLvWTXNqU8HKspiHP).usage`, read 2026-10-25 ~17:50Z |
| LTR-11 packet-generator lane | **$4.33**, Sonnet; 25.29 M cache-read, 68.2 k output; 335 k context — MEASURED | `get_session(session_017YfAAmprJiMhCa8BrwED6k).usage`, same read |
| Packet build time | **36 s** for `--all-open` over 9 packages, run from a session through the diag relay + public routes — MEASURED | row `LTR-11-PACKET` note (PR #20127) |
| Packet size | 9 packets, **1,508–4,966 bytes**, median 4,500 — MEASURED. INFERRED ≈ 0.4–1.4 k tokens at ~3.5 bytes/token | `comms/live_review/packets/` (PR #20121) |
| Decision-row size | 9 rows, **2,207–3,505 bytes** — MEASURED | `comms/live_review/reviews.jsonl` (PR #20121) |
| Inputs the packet still lacks | perp funding, live vol bucket / regime cell, a fresh calendar (the newest event in `config/economic_calendar.yaml` is 2026-07-30), tradeify_1 / velotrade_1 venue positions, a per-account amend risk read, live-vs-backtest verdict — MEASURED (listed with reasons in `packet.missing_inputs`) | row `LTR-11-PACKET` note |
| The per-account gap | `amend_position_sl.py` moves the shared package SL on every leg and **does not pass through `RiskManager`**. `RiskManager.approve()` covers new packages only (`src/units/accounts/risk.py:876`) — MEASURED by the manager | row `LTR-6-APPLY-PATH` note |
| The silent-failure precedent | breakout_2 kept an ETH short on its original stop after the package closed `sl_cross` (2026-10-24); the phone amend was refused 6× and nothing surfaced it until LTR-3 looked — MEASURED | row `PHONE-AMEND-REFUSED-1025`, PR #20122 |
| Exposure | real money: **0.82 positions opened a day**, at least one open **72.9%** of hours, mean concurrency **1.31**, max **4** (912 hours, `bybit_2` + `alpaca_live`, from 2026-09-17) — MEASURED by LTR design § 6.1. Prop concurrency: **UNMEASURED** | LTR design § 6.1 |
| Weekly allowance | **36%** used at 2026-10-25 16:02Z; reset Wed 2026-10-28 18:00Z — MEASURED (operator reading) | `docs/claude/work/USAGE-READINGS.jsonl` |
| Trader tick | `TICK_INTERVAL_SECONDS` defaults to 60 s in code (`src/main.py:1026`); the VM's env value was not read this session | code |
| Repo → VM sync | `ict-git-sync` every **5 min** (`OnUnitActiveSec=5min`) — MEASURED from the unit file | `deploy/ict-git-sync.timer` |

Two derived rates are used throughout. They are INFERRED from the two MEASURED lanes above: total cost
divided by all tokens processed, and dominated by cache reads.

- **Opus ≈ $0.31 per million tokens processed** ($13.04 / 42.41 M).
- **Sonnet ≈ $0.17 per million** ($4.33 / 25.63 M). The ratio is **1.82**.
- **Haiku: UNMEASURED.** It is taken as ⅓ of Sonnet, which is an assumption.

These rates price *re-reading a context*. That is the dominant cost of any standing session.

---

## 2. Architecture — lanes, the desk manager, packets, decisions

### 2.1 Layers

| layer | what | where | model |
|---|---|---|---|
| **L0 — desk plumbing** | Builds packets, computes due events (LTR-1 events plus entry/exit events, § 2.3), takes intents in, gates them per account, executes them, reads them back, checks divergence. **No judgment.** | live VM | none |
| **Desk manager** | A standing loop session. Each wake reads L0's `due` list, routes each due packet to its role, writes decisions, spawns escalations and short-hold lanes, rotates itself (§ 5.3). A wake with nothing due ends after one call. | Claude session, `ScheduleWakeup` / `/loop` | **Sonnet** |
| **Role: market watch** | Over the next-bar candidate set (legs near a signal, calendar, funding, regime): watch notes plus `delay` / `veto_candidate` intents. **Shadow only** until § 8 Stage 2. | inside the desk session | Sonnet |
| **Role: entry review** | On every new order package before or at entry: `take / skip / delay(bars)`. **Shadow only**: entries execute exactly as today. The counterfactual is free, because every package's outcome is observed whatever Claude said. | inside the desk session | Sonnet |
| **Role: in-trade (LTR)** | Today's `live-trade-review` skill on the in-trade packet, at the desk's cadence instead of the hourly gate. | inside the desk session | Sonnet |
| **Role: exit / post-trade** | `close / partial_close` recommendations while open (always the operator's call today, LTR § 4). After the close, the blind-then-reveal grade (CJ-3). | desk session; grade in a daily batch | Sonnet; grade per CJ-3 |
| **Escalation** | A real-money or prop decision whose candidate is not `hold` / `take`, or any `flag_mechanics`. This is the LTR L2b rule, unchanged. | spawned session | **Opus** |
| **Blind teacher** | A random fraction **ρ** of the desk's decisions, re-judged by Opus from the **same packet**, without seeing Sonnet's answer. Batched daily. § 4. | spawned session, daily | **Opus** |
| **Weekly grading** | Counterfactual replay (LTR-5) and calibration of each role. Opus grades a sample. | `/performance-review` section | Sonnet + Opus sample |
| **Short-hold lane** | Spawned by the desk manager when a short-hold trade opens. It stays live at 1–5 min cadence and ends on the close. **Not piloted until § 6 passes.** | spawned session | Sonnet |

**Why roles are not separate sessions (INFERRED, from § 1's rates):** each session re-reads its own base
context, the system prompt plus repo instructions plus skill, on every API call. That base, `C0`, is
INFERRED at ~60–100 k tokens; `CLAUDE.md` alone is 42,712 bytes, MEASURED. Five role sessions each waking
every 15 min would pay `C0` five times per wake. One desk session pays it once. The specialist lanes
the operator asked for keep their identity through three things: their packet kind, their closed
decision enum, and their skill section. Grading is per role (§ 4.4).

### 2.2 One packet schema for Claude and ML (operator point 6)

**One envelope, three kinds.** It extends the LTR-11 packet v2 (`scripts/ops/live_review_packet.py`,
`PACKET_VERSION = 2`) to **v3**. The `packet_sha` is the sha256 of the canonical JSON, exactly as today.

| block | entry | in_trade | exit (post) |
|---|---|---|---|
| `meta`: `packet_kind`, `packet_version`, `built_at`, **`info_cutoff_at`**, `generator`, `missing_inputs[]` | ✓ | ✓ | ✓ |
| `package`: id, leg, symbol, side, timeframe, signal_logic, entry / SL / TP as built, risk per unit, `accounts[]` with account class | ✓ | ✓ | ✓ |
| `state`: open_r, peak_r (+provenance), giveback_r, bars_held, bars_since_peak, r_to_stop, r_to_target, live SL/TP | — | ✓ | final |
| `market`: ATR now/entry, HTF trend, regime cell now/entry, funding vs assumption, calendar window, news decision | ✓ | ✓ | at entry/exit |
| `history`: LTR-0 conditional outcome table, net of the full cost stack; for entry, the leg's Stage-0 expectancy and its selection-lift table | ✓ | ✓ | — |
| `book`: correlated open packages, same and other accounts | ✓ | ✓ | — |
| `per_account`: per account, mode, venue SL/TP/size read **with its read state**, and the gate's read-only preview (§ 3.3) | ✓ | ✓ | — |
| `mechanics`: verdict + evidence | — | ✓ | ✓ |
| `ml`: served heads' predictions at their ladder stage, **with an explicit `absent` state** | ✓ | ✓ | — |
| `prior_decisions`: earlier desk decisions on this package and whether they were applied | — | ✓ | ✓ |
| `outcome` (only after `info_cutoff_at`; T1) | — | — | ✓ |

**Binding rules, carried from the distillation design § 3 into the schema:**

- **Could-not-look ≠ zero.** Every unreadable field is `null` and is named in `missing_inputs`. LTR-11
  already does this.
- **`info_cutoff_at` on every packet.** A packet containing `outcome` is T1, and is never a feature.
- **The ML feature view is a projection of the packet.** It is the flat numeric `features_at_review`
  block, generated from the same packet, so the `claude_judgments` family (CJ-2) and any desk student
  train on exactly what the teacher saw.
- **The dataset schema IS the desk packet schema.** That is why CJ-2 waits on DESK-0 (§ 10).

### 2.3 Decision schemas (closed enums; prose is bookkeeping, never a label)

The common envelope extends `comms/schema/live_review.schema.json`:

```
decision_id, packet_sha, packet_kind, role, judged_at, info_cutoff_at,
model, prompt_sha, skill_sha, label_version,
action ∈ <role enum>, params {level, level_atr, frac, bars},
judge_prior (P that the default action ends worse), confidence ∈ {measured, suggestive, anecdote},
basis ∈ {ev_positive, preference_within_bound, insufficient_n, mechanics, operator_ask},
rationale (text; never a feature), escalated_to (decision_id | null),
intent_id (null when record-only), disposition {route, per_account[] (§ 3.4)},
external_context {used: bool, trigger: <event>, sources: [{url_or_id, title, fetched_at}],
                  summary, reproducible: false}   — DECIDED feeds rule, below
```

**External context (DECIDED 2026-10-25 ~17:58Z, operator popup verbatim: *"Repo feeds + logged exception (Recommended)"*).**

- **The packet is the default and only feed.** A decision may pull live web/news context only on a
  big-event exception: a `calendar` or `swing` due event, or an escalation.
- **Every pull is logged** in `external_context`: the sources, their fetch time and a summary. The
  pulled text is never folded into the packet, so `packet_sha` stays the reproducible input.
- **Replays tell exception rows apart** by `external_context.used = true`. The `claude_judgments`
  builder sets `reproducible: false` on them. D-S0 replays and the student training sets **exclude**
  those rows by default. They are graded separately, so the value of the exception is measured
  instead of mixed in.
- The validator guard refuses a row with `used: true` and an empty `sources`.

| role | action enum | default | applied today? |
|---|---|---|---|
| market watch | `no_action`, `watch_note`, `delay_candidate(bars)`, `veto_candidate` | `no_action` | **never** (shadow) |
| entry review | `take`, `skip`, `delay(bars)`, `no_recommendation` | `take` (the status quo) | **never** (shadow) |
| in-trade | `hold`, `tighten_sl(level)`, `tp_revise(level)`, `flag_mechanics`, `no_recommendation`, `file_hypothesis` | `hold` | `tighten_sl` within the LTR-7 bound, after DESK-2/3 (§ 8) |
| exit | `hold`, `partial_close(frac)`, `close` | `hold` | **never**: the operator's call (LTR § 4) |
| post-trade | blind grade, then revealed grade (CJ-3's schema) | — | n/a |

**Never in any enum:** a size change, a new entry, a widened stop, a TP moved farther away under a
mandate, a `mode:` or `execution:` change, or any halt. That is Prime Directive rules 2 and 7.

### 2.4 Due events (L0) — LTR-1's list plus three

| kind | events |
|---|---|
| in_trade | LTR design § 2: `r_milestone`, `new_peak`, `giveback`, `near_target`, `swing`, `vol_regime`, `funding`, `calendar`, `mechanics`, plus `daily_floor` |
| entry | `package_created` (the trader built an order package), plus `candidate_near` (a leg's signal is within one bar, for market watch) |
| exit | `trade_closed` (queues the post-trade grade) |

**Dedupe, cooldown and batching** stay exactly as in LTR § 2. The desk adds one rule: **a cadence wake
with nothing due costs one call and records nothing.** This is how the 15-min cadence avoids paying for
routine decisions (operator point 4).

---

## 3. Package-level intent → per-account risk gate → per-account executor

This re-scopes LTR-6, LTR-8 and LTR-9 (operator point 2; the manager's finding on `LTR-6-APPLY-PATH`).

### 3.0 The adopted interface (lane `LTR-6R-APPLY-PATH`, manager relay 2026-10-25 17:37Z)

The design uses LTR-6R's names and does not define a parallel set:

- **`LiveReviewIntent`**, at package level. `action ∈ {tighten_sl, flag, no_action}`, plus level,
  evidence and mandate. The desk's in-trade enum (§ 2.3) maps onto it as follows: `tighten_sl` →
  `tighten_sl`; `flag_mechanics` → `flag`; everything else → `no_action`, which is a record only.
- **`RiskManager.approve_amend(intent, account)`** → `approve` / `clip` / `refuse`, each with a reason.
- **The account's existing executor:** `amend_position_sl` for Bybit, the prop trail `sl_floor` or the
  phone amend for prop, and Alpaca later.
- **Tighten-only**, gated by `config/live_trade_review.yaml::apply_mode`.

**Four points this design requires of it.** They were sent to the manager at 18:02Z.

1. **A fourth verdict, `could_not_look(reason)`.** A failed venue, mark, ATR or position read is
   neither approve nor refuse. It means no apply, a retry next cycle, and one flag after 3 consecutive
   cycles. This is the collapsed-states rule plus Prime Directive rule 7.
2. **Account-scoped execution.** Today `amend_position_sl.py` writes the shared `order_packages.sl`
   and amends every leg. After a per-account `clip` or `refuse`, that would push one account's level
   onto accounts whose gate did not approve it. The executor must amend **only** the approved account's
   position and record a per-account applied level. That account's trail then uses
   max(own stop, applied level), so it never loosens back.
3. **Mandatory readback.** A mismatch is `apply_failed`, and the first refuse, no-op or mismatch on a
   real-money or prop account sends one ping. That is the `PHONE-AMEND-REFUSED-1025` class.
4. **The daily-DD switch never refuses a tighten** (`evaluate(..., opening=False)` semantics).

### 3.1 The shape

```
desk decision (package level)                          one record, decision_id
   │  intent = {intent_id, order_package_id, action, level, mandate, evidence: packet_sha + decision_id,
   │            issued_at, expires_at (= next bar close of the leg)}
   ▼
L0 intent intake (VM)                                  validates: evidence on record, action in the
   │                                                   mandate's enum, not expired, once per bar
   ├──► account A: RiskManager_A.approve_amend(intent, position_A) ──► verdict_A ──► executor_A ──► readback_A
   ├──► account B (mirror): RiskManager_B.approve_amend(...)        ──► verdict_B ──► executor_B ──► readback_B
   └──► prop P: PropRiskManager_P.approve_amend(...)                 ──► verdict_P ──► executor_P ──► readback_P
                                                                       │
divergence check (after every intent) ◄──────────────────────────────┘  one flag on any refuse / no-op / mismatch
```

- **Claude never sees, sets or reasons about an account's risk bounds.** The intent says *where the
  package's stop should be*. Each account decides whether it may move its own position there.
- **The package keeps a package-level `intent_sl`.** Each account keeps its own `applied_sl`. The
  monitor's trail on each account treats `applied_sl` as a floor, so an amend can never be fought by the
  next trail pass. This generalises the LTR-8 `sl_floor` idea to every account.
  ⚠️ This replaces "move the shared `order_packages.sl`" (today's `amend_position_sl.py`). That change
  is **Tier 3** (the order path) and is the core of DESK-3.

### 3.2 The gate (DESK-2: pure functions, Tier 3 by path, `src/units/accounts/risk.py`)

**`RiskManager.approve_amend(intent, account) -> Verdict{approve | clip(level, reason) | refuse(reason) | could_not_look(reason)}`**

This is the LTR-6R signature (§ 3.0). `clip` moves the level to the tightest one this account allows,
which is still tighter than its current stop. `could_not_look` is this design's addition (§ 3.0).

1. **Tighten only.** The new stop is strictly inside the account's current stop, compared against the
   **venue** stop read. Otherwise `refuse(widen)`.
2. **Noise floor.** At least `min_buffer_atr` × ATR beyond the mark, and at most one amend per package
   per closed bar (LTR § 3 guardrails, now in code).
3. **The account's own state.** If `mode: dry_run`, refuse with `account_mode_dry_run`, as `evaluate()`
   does today. The daily-DD switch **does not refuse a tighten**: a tighten reduces risk, the same as
   `evaluate(..., opening=False)` today (operator: *"keep open, block new"*).
4. **A read it could not make** (venue position, mark, ATR) is `could_not_look`, **never `approve`**.

**`PropRiskManager.approve_amend`** adds the firm's rules, which live in `src/prop/account_rulesets.py`
and `prop_rule_guards.py`:

- the minimum stop distance the firm allows;
- any modification restriction around news, if the ruleset has one;
- the trailing-drawdown cushion (`prop_risk_gate.py`);
- for the phone account, `human_moved` and the one-slot amend channel being free.

**`approve_entry(intent)`** exists for `skip` / `delay` only, and is **not called in the pilot** (§ 2.3,
shadow). A skip or delay reduces risk, so the gate checks only that the package is still pending and the
intent is unexpired. **No intent may cause an entry**, so there is no "take" intent.

**Every verdict is a record.** It carries the account, the verdict, the reason and the inputs read, with
their read states. The four-state shape (approve / refuse / could_not_look / error) is registered with
`collapsed-state-guard`.

### 3.3 Executors (DESK-3: Tier 3, the order path)

| account class | executor | today |
|---|---|---|
| Bybit (`bybit_2`, `bybit_portfolio`, `bybit_1`) | the amend core of `amend_position_sl.py`, refactored into a per-account call behind the gate | the script moves the shared package SL on every leg (LTR-6 finding) |
| Prop, VM executor (`tradeify_1`, `velotrade_1`) | `prop_trail.plan_trail` honours the account's `applied_sl` floor; the executor places the amend | LTR-8 |
| Prop, phone (`breakout_2`) | `phone_trail.request_sl_tighten()` through the one-slot channel. **A refusal is read back and surfaced on the first occurrence** | the six silent refusals (PHONE-AMEND-REFUSED-1025, PR #20122) |
| Alpaca (`alpaca_live`, `alpaca_portfolio`) | a branch to `execute.modify_open_order` | LTR-9 |

**Readback is mandatory.** After an executor reports success, the venue stop is re-read, and a mismatch
is `apply_failed`, not `applied`. **The divergence check runs after every intent.** It reuses
`scripts/ops/check_ticket_package_divergence.py` (PR #20122), extended to compare `intent_sl` against
each account's `applied_sl` and venue stop. Any refuse, no-op or mismatch on a real-money or prop account
is **one** flag: a ping, plus one line in the hourly digest. The intent is retried while unexpired,
under Prime Directive rule 7: retry with diagnosis, one red flag, never halt.

### 3.4 Mirror identity

The operator's rule is that **each** account decides, the mirror included (`bybit_portfolio`). The
mirror tests pin **roster and trade-shaping config equality**
(`tests/test_paper_portfolio_accounts.py`); they do not pin per-trade stop equality. So a gate that
approves on `bybit_2` and refuses on the mirror is allowed. The divergence flag reports it, and the
Gate-2 demotion read marks that package **touched/divergent**, the same way LTR § 5 splits
touched from untouched trades. INFERRED: with identical config and a shared package this should be
rare. The first occurrence is worth reading, not suppressing.

### 3.5 How intents reach the VM (DESK-4) — the latency hinge

| route | latency | status |
|---|---|---|
| decision committed to `main` → `ict-git-sync` | PR + CI (~9 min CI per the rules doc) + up to 5 min of sync | **too slow for live intents.** Fine for shadow records, batched |
| **system-action issue** (`desk-intent`, the `amend-position-sl` pattern) | GitHub Actions job start + SSH: **UNMEASURED**, INFERRED 0.5–2 min | **the pilot route**; DESK-6 measures it |
| a VM intake endpoint the desk session calls directly | INFERRED < 5 s | Tier 2, with an auth design; needed for 5 min (§ 5) |

**Records store.** Shadow decisions are batched into `comms/desk/decisions.jsonl` through a landing PR
every few hours. This is the `comms/live_review/` pattern, and its validator guard extends
`live-review-records-guard`. Live intents and verdicts need a VM-side store. **DESK-4 must first try to
project over an existing store**: `order_packages` meta, or the system-action audit log. A new table
needs the operator's OK and a backfill (Rule 3). That is a rule, not a preference, so it is not asked
in § 11.

### 3.6 The sandbox — DECIDED: shadow the `bybit_1` soak book

**DECIDED 2026-10-25 ~17:58Z, operator popup verbatim: *"Shadow the bybit_1 soak book"*.** There is no
new account. The desk's sandbox applies land on `bybit_1`, which is the Stage-1 soak book and carries
the same packages as `bybit_2`.

**Keeping desk effects separable from the strategy soak.** Both readings share one book, so neither may
contaminate the other.

1. **Account-scoped applies are a precondition** (§ 3.0, point 2). A sandbox apply on `bybit_1` must
   never move `bybit_2`'s stop. Without account scoping, the sandbox would be real money.
2. **A touch record on every desk effect.** It has `{order_package_id, account, intent_id,
   decision_id, applied_at, level_before, level_after, verdict}`, kept in the per-account verdict and
   apply records. It is projected over those records, not held in a new store (§ 3.5). A package-account
   pair is **desk-touched** from its first applied intent onward.
3. **Every grader splits touched from untouched:**
   - `scripts/ops/soak_report.py`: a leg's mechanical soak PASS counts **untouched** trades only. A
     desk-touched trade is reported, but it is never one of the leg's "1–2 clean trades", because its
     exit is no longer the leg's own.
   - Live-vs-backtest and cost-fidelity verdicts are computed on untouched trades, with touched ones
     shown beside them.
   - Desk grading (§ 4.4) uses touched trades for the applied effect and untouched ones as the control.
   - The Gate-2 demotion read on `bybit_2` + `bybit_portfolio` is unaffected while they stay in
     `recommend`, and is split the same way once they apply (LTR § 5).
4. **Untouched trades stay the default.** INFERRED: most `bybit_1` trades are never touched, because
   most reviews are `hold` (1 of 2 real-money LTR rows in the first run). So the soak keeps its
   population.
5. **The `bybit_1` mechanics evidence** for the desk is the first 1–2 clean applies: verdict, readback
   and divergence check all clean (§ 0a flip order).

---

## 4. Model tiering, and the teacher-sampling dial

### 4.1 Tiers (operator point 4; the manager's proposal on the DESK-DESIGN row)

| tier | what | why this model |
|---|---|---|
| **L0** | packets, due events, gate, executor, divergence, counterfactual replay | deterministic; $0 in usage |
| **Haiku** | only the cheap watcher, if one is needed, that spawns short-hold lanes when the desk session itself is idle (§ 6.3) | a yes/no on an L0 field |
| **Sonnet** | every live decision, in the standing desk session | warm cache, 1.82× cheaper than Opus (§ 1), and judgment is bounded by the packet and the closed enum |
| **Opus** | (a) escalations: real-money / prop non-default actions and `flag_mechanics`; (b) the blind teacher sample; (c) the weekly grading sample | where we learn, and where real money moves. This is the model table's rule *"anything on a real-money order path: Opus"* (manager SKILL) and the operator's *"Opus doing the review and not the actual live management"* |

**An unattended real-money apply always has Opus in its chain.** A Sonnet `tighten_sl` on a real-money
or prop package is an escalation candidate by definition. Opus confirms it before the intent is issued,
which is LTR § 6.6's rule carried over. Paper and shadow records never escalate.

### 4.2 The dial: teacher sampling rate ρ

```
C_day  =  W · c_wake(f)  +  N_e · c_esc  +  ρ · N_d · c_teach  +  c_teach_session  +  c_grade/7

  W      wakes a day          = (1440 / cadence_min) × open_fraction
  f      fraction of wakes with something due                       (UNMEASURED; L0's due log gives it)
  N_d    decisions a day      = W · f · n̄    (n̄ = open packages per wake)
  N_e    escalations a day                                           (UNMEASURED)
  c_wake = calls_per_wake · ctx_avg · p_model     (§ 5.3)
  c_teach ≈ 2 calls · ~100 k ctx · p_opus ≈ $0.06   (INFERRED; batched, packet-only)
  ρ      teacher sampling rate — THE DIAL
```

| ρ | blind teacher labels a week at N_d = 23/day | weeks to n = 150 (the CJ-4 floor) | added cost a day |
|---|---|---|---|
| 0.10 | 16 | 9.3 | ≈ $0.15 + the session ≈ $0.65 |
| **0.25 (proposed default)** | 40 | **3.7** | ≈ $0.35 + the session ≈ $0.85 |
| 0.50 | 80 | 1.9 | ≈ $0.70 + the session ≈ $1.20 |
| 1.00 | 161 | 0.9 | ≈ $1.40 + the session ≈ $1.90 |

N_d = 23 is INFERRED for Scale 1 in § 7. The session cost is INFERRED at about $0.5 a day for one
batched Opus start.

**How ρ is set (proposed; not a preference the operator needs to rule on unless they want to):**

- Start at **0.25**.
- Raise it to 0.5 for a role while that role's teacher n is below 150. The label wall is reached faster,
  and teacher labels are cheap next to escalations.
- Once a role passes CJ-4, drop it to **0.10**. That keeps the agreement and drift diagnostic alive.
- If the capacity reserve is breached (LTR § 6.6), set ρ to 0 **before** any live tier degrades. The
  teacher sample is the first thing dropped and never a reason to skip a live review.

### 4.3 Measuring the tiers

Sonnet–Opus **agreement** per role is a diagnostic, never a promotion metric (distillation § 3.6). The
outcome metric is **ΔR versus counterfactual, net**, per role and per model, over the same packets. If
the Opus teacher and the Sonnet decider disagree and outcomes favour Opus on a role, that role's live
tier moves to Opus. That is a proposal on evidence through the normal path, not a reflex.

### 4.4 Grading (folds in LTR-5)

The weekly grading is LTR-5's counterfactual replay, generalised per role:

- **In-trade:** actual minus untouched-bracket replay, with touched and untouched trades split.
- **Entry:** take/skip selection lift versus take-all and versus the strategy's own `confidence`. This
  is the ML-M5 rule shape.
- **Market watch:** delay/veto lift on the candidates it flagged.
- **Post-trade:** blind-vs-revealed gap (CJ-3).

Calibration of `judge_prior` and `confidence` per role and per model. An A–F grade on a sample of
decision rows, keyed by `decision_id`.

---

## 5. Short-timeframe feasibility — latency, cost, rotation

### 5.1 Latency floor per stage

| stage | today | MEASURED / INFERRED |
|---|---|---|
| bar close → candles on the VM, signal / package | 0–60 s (tick default 60 s) | code default; VM env not read |
| L0 packet build | **36 s for 9 packages from a session** over relays | MEASURED (LTR-11) |
| | on the VM as a read endpoint: 1–5 s | INFERRED |
| session wake granularity | `ScheduleWakeup` minimum 60 s; `send_later` 1-min granularity | platform tool limits, as documented to sessions |
| model decision (packet in, ~0.5–1 k tokens of decision out) | Sonnet 15–40 s; Opus 30–90 s | INFERRED; **UNMEASURED** on this workload |
| intent → VM | issue route 0.5–2 min; VM intake < 5 s | INFERRED; **UNMEASURED** |
| gate + executor + readback | Bybit ~1–3 s | INFERRED |
| | phone account: one-slot channel, minutes | INFERRED; **UNMEASURED** |

**End to end, bar close → applied:**

| cadence (bar) | today's route (relay packets + issue intents) | with VM packets + VM intake (DESK-1 + DESK-4b) | verdict |
|---|---|---|---|
| **1 h** | ~2.5–5 min → 4–8% of the bar | ~1–2 min → 2–3% | feasible |
| **15 min** | ~2.5–5 min → **17–33%** | ~1–2 min → 7–13% | **feasible for in-trade management; pilot here** |
| **5 min** | ~2.5–5 min → **50–100%** | ~1–2 min → 20–40% | feasible **only** after DESK-1 + DESK-4b, and then only for management |
| **1 min** | > 100% | > 100% (the 60 s wake floor alone) | **not feasible** with a model in the loop; L0 rules or a distilled student only |

**The reviewer is not the protection at any cadence** (LTR § 1). Venue SL/TP and the monitor's trail
protect every position whatever the desk does.

### 5.2 What "stays live" means

A standing desk session is a `/loop`-style session that sleeps with `ScheduleWakeup` between wakes. Two
documented facts drive its cost:

- **The prompt cache lives 1 hour** in this harness. A wake within the hour re-reads the context cheaply.
  A wake after more than an hour pays a full cache write.
- **The wake delay is clamped to 60–3,600 s.** INFERRED: any cadence of 55 minutes or less keeps the
  cache warm.

**For hourly-or-slower work, spawn per event** (LTR-4's shape). Do not keep a standing session for it.

### 5.3 Standing-lane cost, context growth and rotation

Notation:

- `C0` is the base context: INFERRED 60–100 k, use 80 k.
- `Δ` is the growth per working wake: packet ~1.3 k + decision ~0.8 k + tool I/O. INFERRED 3–5 k, use 4 k.
- A cache write costs ~12.5× a cache read. That comes from the published cache pricing structure
  (write 1.25× base input, read 0.1×), which was **not re-verified this session**.

Rotation means ending the session and starting a fresh one. It pays one cache write of `C0` and resets
the growth. Minimising the average per-wake cost gives the optimal number of wakes per session:

```
K*  =  sqrt( 2 · (write/read) · C0 / Δ )  =  sqrt( 2 · 12.5 · 80 k / 4 k )  ≈  22 wakes
average context per wake at K*  =  C0 + Δ·(K*−1)/2  ≈  122 k tokens
```

So the desk session rotates about every 22 working wakes. At 15 min that is ~5.5 h; at 5 min, ~1.8 h.
It hands its state forward through the repo, not through chat: the last decisions, the open intents and
the due cursor. It **never** passes 50% of the context window. That is an INFERRED safety margin
against compaction mid-decision, because a compaction is a lossy re-derivation (rules doc §
Session-length).

**Per-wake cost** (INFERRED: ctx_avg 122 k × the § 1 rate):

| model | one call | quiet wake (1 call) | working wake (2 calls) |
|---|---|---|---|
| Sonnet | $0.021 | $0.021 | $0.041 |
| Opus | $0.038 | $0.038 | $0.075 |

**Standing-lane cost per hour**, at f = 0.25 working wakes, while something is open:

| cadence | wakes / h | Sonnet $/h | Sonnet $/day if always open | Opus $/day |
|---|---|---|---|---|
| 1 min | 60 | $1.55 | $37 | $67 |
| 5 min | 12 | $0.31 | $7.4 | $13.5 |
| **15 min** | 4 | $0.10 | **$2.5** | $4.5 |
| 1 h | 1 (cache cold) | ≈ $0.26 (INFERRED: a full rewrite per wake) | $6.2 | — |

**These figures carry ±2× uncertainty.** The calls per wake, `C0` and `Δ` are all UNMEASURED. DESK-6
measures each of them in the first 24 h of the shadow pilot, through `get_session().usage` deltas per
wake. LTR-10B carries the per-session cost records that feed it.

---

## 6. Can a short-hold (10 min – 1 h) lane be profitable?

### 6.1 Edge net of the full cost stack — MEASURED

**Source:** `comms/strategy_evidence/<leg>.json`, `basis: harness_timefolds`. The window is 365 days, 4
time folds, generated 2026-10-02. The cost stack is fee 7.5 + slippage 3.0 bps round trip + funding, via
`execution_costs.resolve_cost_policy()`.

| leg | tf | n OOS | net R/trade | fee-only R/trade | folds > 0 | trades/day |
|---|---|--:|--:|--:|:-:|--:|
| ict_scalp_5m (BTC) | 5m | 145 | **−0.205** | −0.137 | 0/4 | 0.40 |
| ict_scalp_avax_5m | 5m | 177 | **−0.210** | −0.170 | 0/4 | 0.48 |
| ict_scalp_sol_5m | 5m | 190 | **−0.120** | −0.077 | 0/4 | 0.52 |
| ict_scalp_xrp_5m (fidelity `approximate`) | 5m | 169 | **−0.160** | −0.112 | 0/4 | 0.46 |
| ict_scalp_sol_15m | 15m | 84 | −0.066 | −0.042 | 2/4 | 0.23 |
| ict_scalp_eth_15m | 15m | 78 | **+0.017** | +0.045 | 2/4 | 0.21 |
| ict_scalp_xrp_15m | 15m | 76 | **+0.054** | +0.090 | 2/4 | 0.21 |
| fvg_range_15m (BTC) | 15m | 17 | −0.570 | — | 0/4 | 0.05 |
| ict_scalp_mgc_15m | 15m | — | `harness_failed` | — | — | — |
| chop_scalp BTC 15m (1,095 d) | 15m | 45 | **−0.309**, first-pass FAIL | — | — | — |
| chop_scalp BNB 5m | 5m | < 39 | `indeterminate` | — | — | — |

The chop_scalp rows come from different records. BTC 15m is `RQ-20260929-107`, record
`research/results/RQ-20260929-107/37213645066.jsonl`. BNB 5m is `RQ-20261006-016`. The broader "any
profitable ≤ 1 h crypto-perp strategy" sweep (`RQ-20260930-504`, status `done`) has only a **smoke-run**
verdict on file (`comms/research/RQ-20260930-504/36691408944/verdict.json`: `fail`, *"not the registered
design"*). I did not find a registered-design result this session, so it is reported as **not
established either way**.

**What this says (INFERRED from the table):**

- **At 5 min, slippage + funding alone cost 0.04–0.07 R a trade** (fee-only minus net), on top of a
  negative edge. Every 5m cell loses in every fold.
- **At 15 min, two cells are marginally positive and unconfirmed.** Two of four folds are positive, and
  the mean is within one fold's noise.
- So **no short-hold leg clears Stage 0 today.** M27's scalp soaks were killed on 2026-10-05 (the
  roadmap), and M22's small-TF question is dormant.

### 6.2 Break-even arithmetic

Write `R$` for the dollar risk per trade. It is a per-account sizing output, so this doc does not state
it: the repo is public, and it is the risk manager's number, not the desk's.

**Standing short-hold lane** (5 min cadence, always live, Sonnet, § 5.3): ≈ $7.4 a day.

- Over the two 15m cells it would trade ≈ 0.42 trades a day.
- So the desk must add **ΔR ≥ 7.4 / (0.42 · R$) ≈ 17.6 / R$ per trade**: +0.35 R at R$ = $50, or +0.09 R
  at R$ = $200.
- That is on top of a base of +0.02 to +0.05 R. **Not profitable on today's evidence** unless R$ is
  large and Claude management is worth a lot. Nothing measures that yet.

**Per-trade spawned lane** (spawned on entry, 5 min cadence, ends at exit; 1 h hold):

- About 12 wakes ≈ $0.35, plus one spawn (a `C0` cache write ≈ $0.15) ≈ **$0.5 a trade**. INFERRED.
- Break-even ΔR = 0.5 / R$: **+0.01 R at R$ = $50**.
- **Affordable**, and the right shape if § 6.3 passes.
- **Marginal cost per extra package in an already-live session** is only Δ × rate ≈ $0.0007 a wake.
  So once a desk session is live, adding packages is nearly free. Keeping it live is what costs.

### 6.3 The flow that works, and what gates it

1. **Stage 0 for the leg** (DESK-8a): a registered confirm run of `ict_scalp_eth_15m` and
   `ict_scalp_xrp_15m` on a fresh window. A short-hold leg only exists after a PASS.
2. **Stage 0 for Claude-on-the-leg** (DESK-8b): blind replay (§ 8 D-S0) of in-trade decisions on those
   two trade lists. The candles are masked and ATR-normalised. The candidate actions are replayed on the
   real paths.
3. **Then** the per-trade spawned lane: the desk manager, or a Haiku watcher if the desk session is
   rotated out, sees `package_created` on a short-hold leg and spawns a Sonnet lane at the leg's cadence.
   The lane runs until `trade_closed`.

---

## 7. Capacity plan

### 7.1 Today's budget — MEASURED inputs, INFERRED arithmetic

- **Weekly:** 36% used at 2026-10-25 16:02Z; reset Wed 2026-10-28 18:00Z, **3.08 days** away.
  64 pp remain, a gross rate of **20.8 pp/day**.
- **Live-review reserve (operator, 15 pp):** the net rate for everything else is
  (64 − 15) / 3.08 = **15.9 pp/day**.
- **Fleet burn today:** 31% at 06:09Z → 36% at 16:02Z is 5 pp in 9.9 h, **≈ 12.1 pp/day** across every
  lane running, mixed models. MEASURED from the two readings; the population is the whole fleet.

### 7.2 $ → pp: the missing conversion

The weekly bar is percent of allowance and model-weighted. `cost_usd` is API-equivalent dollars, and
the spend meter refuses to fold one into the other on purpose (`scripts/ops/spend_meter.py` docstring).
**The $/pp conversion `k` is UNMEASURED.**

It is bracketed, INFERRED, from two numbers:

- LTR-3: an Opus lane, $13.04 over 1.08 h.
- LTR-11: a Sonnet lane, $4.33 over 0.88 h.

Both are set against the meter's MEASURED **1.0 pp per lane-hour**, which is blended across models
(2026-10-18). That gives `k` ≈ **$5–12 per pp**. Below, "pp/day" means $/day ÷ k across that range.
DESK-10 measures `k` directly from per-session cost deltas against two operator readings.

### 7.3 Usage per day at each scale (INFERRED)

| scale | what runs | $/day | pp/day (k = 12 … 5) | share of the 15.9 pp/day net |
|---|---|---|---|---|
| **0 — build** | the DESK rows (§ 10), $155 in total ceilings over ~2 weeks | ≈ $11 | 0.9–2.2 | 6–14% |
| **1 — shadow pilot, 15 min** | standing Sonnet desk while anything real-money or prop is open (72.9% of hours); in-trade + exit roles; **f = 0.25 → N_d ≈ 23**; ~1 Opus escalation/day at ~$1.0 (INFERRED; LTR-3's whole lane divided by its 9 reviews gives an upper bound of $1.45); ρ = 0.25 teacher ($0.85); weekly grading (~$5/week) | **≈ $4.5** | **0.4–0.9** | 2.5–6% |
| **2 — + entry review and market watch (shadow) + paper record-only** | + 0.82 real-money entries/day (negligible); hourly market-watch sweep (~$0.7); paper packages roughly double n̄ (+~$2) | ≈ $7.5 | 0.6–1.5 | 4–9% |
| **3 — + per-trade short-hold lanes** (only after § 6.3) | ~0.4–1 short trades/day × $0.5 | ≈ $8–8.5 | 0.7–1.7 | 4–11% |
| **3′ — the same as a STANDING 5 min lane** | instead of per-trade spawns | ≈ $15 | 1.3–3.0 | 8–19% |
| **4 — 1 min cadence** | standing | ≈ $40+ | 3.3–8 | 21–50% (and infeasible on latency anyway, § 5.1) |
| **ALT — Opus as the live decider** | Scale 1 with Opus on every wake | ≈ $6 | 0.5–1.2 | 3–7.5% |

**How the desk sits in the reserve:**

- **Scale 1 does the work of LTR-4's routine, at INFERRED similar cost.** LTR § 6.3 put LTR-4's typical
  load at ~1.5 pp/day.
- So the desk's in-trade role **draws from the 15 pp live-review reserve** rather than adding to it, if
  DESK-6 supersedes LTR-4 (§ 10).
- Scales 2–3 come out of the 15.9 pp/day net.
- **The breach order of LTR § 6.6 extends:**
  1. teacher ρ → 0;
  2. drop market watch and entry review (shadow);
  3. paper → L0-only;
  4. the in-trade role keeps running, degraded to recommend-only on Sonnet.

---

## 8. Promotion path for the desk itself (it sits INSIDE the ladder)

The desk cannot be backtested the way a strategy can: its judgment is the thing being tested. It earns
each step as follows.

| step | what | evidence that moves it on (registered BEFORE the run) |
|---|---|---|
| **D-S0 — blind replay (offline)** | Per role, historical packets are rebuilt point in time from the Stage-0 trade lists plus path emits (`--emit-paths`, EXIT-PATH-EMIT-OFFLINE), **masked** (no symbol, no dates, prices ATR-normalised; distillation § 3.5.5). Sonnet decides, an Opus sample re-judges, and each action is replayed on the real path. | **In-trade:** paired ΔR (desk-managed − untouched bracket) > 0, net of the extra amend slippage, with the 95% CI excluding 0. INFERRED n: with a paired sd of the difference ~0.4 R, detecting +0.05 R needs n ≈ (2.8 · 0.4 / 0.05)² ≈ **500 trades**, and +0.10 R needs ≈ **125**. **Entry review:** skip-selection lift > take-all and > `confidence`-only, net R and max DD, in ≥ 2/3 folds (ML-M5 shape). |
| **D-S1a — live shadow** | The standing desk on live packets, record-only, every role. | **Mechanical, not a sample:** packets build with `info_cutoff_at`; decisions validate against the schema; the due → decision latency is recorded per stage; cost per wake is measured. **24 h of clean operation, or the first 2 clean decisions per role, whichever comes first.** It is not a calendar soak: the soak rule (OPERATING-PLAN § 2) caps it at mechanics. |
| **D-S1b — sandbox mechanics** | Intents through gate → executor → readback on the sandbox (§ 3.6), per account class: Bybit, prop VM, phone, Alpaca. | **1–2 clean intents per class**, verdict and readback recorded. A refused or silent no-op is a fail to fix, not a sample. |
| **D-S2 — mandate-bounded live** | `tighten_sl` on real money and prop, within `MD-LIVE-TIGHTEN-SL` (LTR-7: 0.25 R bound, 0.5 R shadow arm, operator-DECIDED). Live entry skips need a **new mandate**: changing what permits trading is Tier 3, and only the operator grants it. | D-S0 PASS for that role, D-S1b PASS for those account classes, and the mandate granted. **Demotion signal:** applied net ΔR < 0 over the last 20 applies proposes `apply_mode: recommend` (LTR § 5), as a proposal, never an automatic flip. |

**Live P&L never promotes the desk.** A live book checks mechanics and cost (CLAUDE.md). The desk's live
record feeds the **grading** and the **teacher dataset**. Promotion rests on D-S0.

---

## 9. How desk decisions reach the ML pipeline (operator point 6)

1. **Same packet, same features.** Every decision row carries `packet_sha`. The `claude_judgments`
   family (CJ-2) joins on it and projects `features_at_review` from the packet. So the student trains
   on exactly what the teacher saw. The CJ-2 dataset schema **is** the v3 packet schema (DESK-0).
2. **Claude is a teacher, never ground truth.** Each row keeps both the Claude label and the realized
   outcome, plus the computed counterfactual, with `label_provenance ∈ {judgment, computed, measured}`.
   Every source re-qualifies through CJ-4 before any manifest trains on it.
3. **The distilled students are the route to sub-15-min management.** A student such as
   `ltr-tighten-head-v1` or a desk entry-selection head runs with no Claude in the loop, so it can act
   at 1–5 min where a session cannot (§ 5.1). It climbs the normal `candidate → shadow → advisory`
   ladder on net-R evidence.
4. **Claude as an input to ML live management** is **DECIDED as "allow as a feature later"** (CJ Q2):
   only after a model proves out-of-sample net-R edge with it.
   - When it does, the feature carries a three-state value: `claude_present`, `claude_absent`
     (no decision this bar) and `claude_stale` (older than one bar). **Absent is never imputed as
     `hold`.** That is the collapsed-states rule.
   - The model must be trained with the absence pattern it will see live.

---

## 10. Build plan — rows for the manager to file after operator review (NOT filed by this PR)

Every row carries `roadmap: [L-DESK]` (plus `L-ATM` where marked) and a `writeback` to `L-DESK` and to
`docs/ARCHITECTURE-CANONICAL.md` (the order-path / risk-manager neighbourhood for DESK-2/3).

| order | id | what | tier | model | ceiling | depends on | supersedes / reshapes |
|---|---|---|---|---|---|---|---|
| 1 | `DESK-0-SCHEMA` | Packet v3 (entry / in_trade / exit) and the decision schemas of § 2.2–2.3; `comms/schema/desk_*.schema.json`; validator guard (extends `live-review-records-guard`); `features_at_review` projection | 1 | Sonnet | $6 | LTR-11 (#20127) | **reshapes CJ-1/CJ-2**: CJ-2 builds on this schema |
| 2 | `DESK-1-VM-PACKETS` | The packet build and due events as VM read routes (`/api/diag/desk_due`, `/api/diag/desk_packet`); LTR-1's events plus § 2.4's three; **the 36 s measured as a VM figure** | 1 (read path) | Sonnet | $10 | DESK-0 | **absorbs LTR-1-DUE-WATCH** (in flight: merge, don't duplicate) and the LTR-11 open-packages route |
| 3 | `DESK-2-RISK-GATE` | `RiskManager.approve_amend` / `approve_entry`, `PropRiskManager.approve_amend`; the four-state verdict record; `collapsed-state-guard` contract; tests. Pure functions, no caller | **3** (risk.py) | Opus | $12 | — | **gate half of LTR-6** |
| 4 | `DESK-3-EXECUTORS` | Per-account executors behind the gate (§ 3.3); package `intent_sl` vs per-account `applied_sl`, floors in every trail; mandatory readback; the divergence check after every intent | **3** (order path) | Opus | $16 | DESK-2, PHONE-AMEND-REFUSED-1025 | **executor halves of LTR-6, LTR-8, LTR-9** |
| 5 | `DESK-4-INTAKE` | (a) a `desk-intent` system-action (issue route) with its latency recorded; (b) a VM intake endpoint, auth-designed (Tier 2), needed for 5 min; the intent/verdict store projected over an existing store first | 2 | Opus | $10 | DESK-2 | LTR-6's evidence-on-main check |
| 6 | `DESK-5-SKILL` | `.claude/skills/trading-desk/SKILL.md`: the loop, roles, enums, escalation, ρ, rotation and handoff state; it **extends** `live-trade-review` rather than replacing it | 1 | Opus | $6 | DESK-0 | reshapes LTR-3's skill into the in-trade role |
| 7 | `DESK-6-SHADOW-PILOT` | Scale 1, record-only, 15 min standing Sonnet desk over real money + prop. **Measures:** latency per stage, $ per wake, `C0`, `Δ`, calls per wake, `f`, rotation | 1 | Sonnet (+ Opus sample) | $25 | DESK-0, DESK-5 (DESK-1 optional: relay packets work at 15 min) | **supersedes LTR-4-ROUTINE** if approved; until then LTR-4 stands |
| 8 | `DESK-7-BLIND-REPLAY-S0` | D-S0 for in-trade and entry review on the real-money 2h/4h legs: point-in-time masked packets, paired counterfactual, pre-registered `research/queue/` units | 1 | Sonnet + Opus sample | $30 | DESK-0, LTR-0 tool, EXIT-PATH emits | — |
| 9 | `DESK-8-SHORT-HOLD-S0` | (a) a confirm run of `ict_scalp_eth_15m` / `xrp_15m` on a fresh window; (b) a blind replay of Claude management on those lists (§ 6.3) | 1 | Sonnet | $10 | DESK-7's harness | links M27 / M22 |
| 10 | `DESK-9-GRADING` | Per-role grading (§ 4.4) in `/performance-review`, the counterfactual replay, calibration | 1 | Sonnet | $8 | DESK-6 records | **folds in LTR-5-GRADING** |
| 11 | `DESK-10-CAPACITY` | Measure `k` ($/pp) and the per-tier costs; desk scale lines and the extended breach order in `spend_meter.py --capacity` | 1 | Sonnet | $4 | DESK-6 | **extends LTR-10B** |
| 12 | `DESK-11-ML-FEED` | Desk decisions as a `claude_judgments` source (`kind: desk_*`); the three-state Claude feature for later (§ 9.4), behind CJ-4 | 1 | Opus | $10 | DESK-0, CJ-2 | **reshapes CJ-2 / CJ-5 / CJ-6**; CJ-3 (blind grade) becomes the post-trade role; CJ-7 (backfill scope) reuses DESK-7's replay harness |
| 13 | `DESK-12-SANDBOX` | **Monday-critical.** The `bybit_1` sandbox per the DECIDED answer: the touch record and touched/untouched splits in `soak_report.py`, live-vs-backtest, cost fidelity and desk grading (§ 3.6) | 1 (graders) | Sonnet | $6 | LTR-6R records | — |
| 14 | `DESK-13-MANDATE` | Extend `MD-LIVE-TIGHTEN-SL` (LTR-7) to name the desk intent route; **propose** a separate `MD-DESK-SKIP` for live entry skips. **The operator grants**; the row only proposes | 3 (grant) | — | — | DESK-7 PASS | **reshapes LTR-7** |

**Totals:** about $155 across 13 build rows; the mandate row carries no ceiling. **Nothing applies on real
money before rows 3, 4, 5, 13 and 14 have landed and D-S0/D-S1b have passed.**

**Phases.**

- **Monday (phase 1):**
  - LTR-6R, the in-flight Opus lane, delivers the Monday halves of DESK-2 and DESK-3 (Bybit), plus the `apply_mode` switch.
  - LTR-7 writes the mandate.
  - DESK-12 adds the `bybit_1` touch splits.
  - DESK-5 and DESK-6 put the standing in-trade session up in `recommend`.
- **Phase 2:** everything else. That includes:
  - the prop and Alpaca executors (DESK-3 remainder, plus LTR-8/9);
  - VM packets and intake (DESK-1, DESK-4b);
  - entry review and market watch;
  - D-S0 (DESK-7) and short-hold (DESK-8);
  - grading (DESK-9) and the ML feed (DESK-11).

**Order on the critical path:**

```
0 → 6 → 7    shadow pilot, Tier 1: the first measured numbers in days
0 → 8        Stage 0
3 → 4 → 5    the Tier-3 apply path, in parallel
```

**What is NOT superseded:**

- **LTR-0** (the pricing tool): the in-trade role uses it.
- **LTR-2** (records): the desk records extend it.
- **LTR-7** (the mandate): the desk applies through it.
- **LTR-10/10B** (the reserve): the desk sits inside it.
- **PHONE-AMEND-REFUSED-1025**: DESK-3 depends on its fix.

---

## 11. Open questions for the operator (preferences only; no data settles these)

**Decided 2026-10-25 ~17:58Z (removed from the open list):**

- **Feeds:** *"Repo feeds + logged exception (Recommended)"* (§ 2.3, `external_context`).
- **Sandbox:** *"Shadow the bybit_1 soak book"* (§ 3.6).

**Q1 — may the sub-15 min path use a VM-side model call** (the M13 insights key in
`src/runtime/insights/generator.py`) instead of a session?

- **Why it matters:** it removes the 60 s wake floor and the session context entirely, at ~1–2 k tokens a
  call.
- **What it costs:**
  - The call is billed to the API key, not the weekly bar.
  - It has no repo and no tools, though the packet now supplies the context.
  - It is a paid external call on the VM, upstream of a decision.
  - The key's validity is UNVERIFIED this session.
- **Recommended: not now.** Revisit only if DESK-8 passes and a 5 min short-hold leg is wanted. Until
  then, the distilled student (§ 9.3) is the sub-15 min route.

**Q2 — live entry review: should `skip` ever apply on real money** (a new `MD-DESK-SKIP` mandate after
D-S0 passes), or should entry review stay a shadow teacher permanently?

- **Recommended: stay shadow until the D-S0 entry-review unit passes,** then decide on its numbers.

*(The teacher rate ρ is not asked; § 4.2 sets a default with a rule. Raise it if you want to.)*

---

## 12. Risks

| risk | mitigation |
|---|---|
| A standing session dies silently | Desk heartbeat: every wake writes `last_wake_at`; an `attention_watch` probe fires if stale for more than 2 cadences while anything is open. LTR-4's hourly gate stays as the backstop until DESK-6 has a week clean |
| Context compaction mid-decision (lossy) | Rotation at K* ≈ 22 wakes and a hard cap at 50% of the window; state handed forward through the repo (§ 5.3) |
| Cost estimates wrong by 2× (they are INFERRED) | DESK-6 measures in 24 h; the dial ρ and the breach order (§ 7.3) absorb it; Scale 1 is ~3–6% of the net rate even at 2× |
| One account refuses silently (the PHONE-AMEND class) | Mandatory readback; divergence check after every intent; one flag on the first occurrence (§ 3.3) |
| Claude acts on an account's risk by the back door | The enums contain no size field; the intent names a package-level level only; the per-account gate is the only path to a venue |
| Desk-touched trades contaminate the Gate-2 demotion read | Touched/untouched split on every verdict (LTR § 5); mirror divergence marked (§ 3.4) |
| The teacher is no better than the strategy's own confidence | CJ-4 requires beating `confidence`; a failed source stops distillation for that source, and the desk keeps running as a recorder |
| LLM memory leaks hindsight into the replay | Masking plus `pre_cutoff` exclusion (distillation § 3.5.5) on every D-S0 packet |
| Short-hold enthusiasm outruns evidence | § 6: no live short-hold lane before DESK-8 passes; 5m cells are 0/4 folds today |

---

## 13. What this lane did and did not do

**Did:**

- read the rules, the LTR design (#20121 head), the distillation design, the LTR first-run rows and
  packets, the packet generator (#20127), and the LTR-3/4/5/6/7/8/9/10B/11, CJ-2…7 and PHONE-AMEND rows
  (register branch `mgr/reg-01ukbxoz-2`);
- read `src/units/accounts/risk.py` (`RiskManager`, `approve`, `evaluate`) and the `prop_risk_gate`
  header;
- read the scalp evidence records and the chop_scalp queue units;
- read the usage readings and two sessions' `usage` via `get_session`.

**Did not:**

- measure any latency or per-wake cost. **Every § 5 and § 7 figure not marked MEASURED is INFERRED**,
  and DESK-6 replaces it;
- read the VM's `TICK_INTERVAL_SECONDS` or any live diag;
- read prop concurrency;
- verify cache pricing against the API reference;
- file any row, mandate or queue unit.
