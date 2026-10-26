# Claude trading desk — Claude drives the trading; the system's models learn from it (design v1, 2026-10-26)

> **Doc status:** `unknown` · category `architecture` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**State: DESIGN v1.** It supersedes v0 (#20140, 2026-10-25). Nothing below is built by this PR.
Checklist rows: `DESK-15-ENTRY-GENERATION` (this rewrite) and `DESK-DESIGN` · roadmap `L-DESK` (G4), beside
`L-ATM` · Tier 1 (a doc).

**How to read the marks** (`docs/CLAUDE-RULES-CANONICAL.md` § MEASURED / INFERRED / DECIDED):
every number is **MEASURED** (with where it lives), **INFERRED** (from named inputs; check it), or
**UNMEASURED** (nobody has the number; the row that gets it is named). **DECIDED** marks an operator
choice already on record.

---

## 0. The request, and the short answer

### 0.1 What the operator said (verbatim, 2026-10-26, rows `DESK-DESIGN` and `DESK-15-ENTRY-GENERATION`)

> ~06:50Z: *"the goal isn't for Claude to be reviewing the entries. That's, I mean, we can have that
> also, that's nice, but when I say the trading desk does entries, I mean that they find trades that
> the system isn't finding. So, like, I don't even know what that restriction on should Claude be able
> to deny an entry, like, where that even came from. That's just, like, not the design at all.
> Completely wrong direction."*

> ~06:55Z: *"the whole idea here with the trading desk is that we're trying to build a system where
> Claude isn't just weighing in on the system's trades. Claude is, the Claude trading desk is driving
> the trading, and the MLs, the systems MLs that we're building are learning from that Claude
> decision-making how to do it themselves so that we can eventually remove Claude from the flow and
> have only our own AIs doing the trading. But the whole point is to have Claude pushing the whole
> trading operation so that we can use that as the basis for teaching the MLs."*

Also **DECIDED** on 2026-10-26: the design is approved as the build plan (popup *"Approve as the build
plan"*); there is no VM-side model call for now (*"Not now"*); and the live trade review applies its
judgement when the outcome table is thin (lane `LTR-JUDGEMENT-APPLY`, in flight). The 2026-10-25
decisions still stand: feeds are the repo packet plus a logged exception, and the sandbox is the
`bybit_1` soak book (§ 3.6).

### 0.2 What v0 got wrong, and where it came from

v0 was written by a lane on 2026-10-25. It framed the desk as an **advisor over the strategies'
trades**:

- its entry role was *entry review* (`take / skip / delay`) over strategy packages;
- market watch could only raise `delay_candidate` / `veto_candidate`;
- § 2.3 said *"Never in any enum: … a new entry"*;
- § 11 Q2 asked whether a skip should ever apply, and DESK-13 proposed an `MD-DESK-SKIP` mandate.

No operator input asked for any of that. The operator's 2026-10-25 request (v0 § 0 point 1) listed
"market watch / when to enter" as a desk lane. v0 read "entries" as "review the system's entries". That
reading is withdrawn. **v1 deletes the clause, the veto framing, Q2 and `MD-DESK-SKIP`.**

### 0.3 The short answer

- **The desk is a trader, not a reviewer.** It runs the whole trade lifecycle on its own trades: it
  **finds** trades the strategies are not taking, **enters** them, **manages** them and **exits** them.
  It also manages the strategies' open trades (the live trade review, already live in `apply` for
  stop tightens). Reviewing a strategy's entry is optional and record-only. § 2.
- **The desk trades as a leg.** Its entries become ordinary order packages on a rostered leg,
  `claude_desk`. They pass through each account's existing `RiskManager.approve()`, are sized by that
  account, and carry a real predictive TP (TP doctrine). There is no new order path and no third gate:
  the two execution gates (`mode:`, `execution:`) and roster membership decide where it trades, exactly
  as for any leg. § 3.
- **Every desk decision is a teacher label**: the packet it saw, what it decided, and the outcome
  realised on the real price path, net of the full cost stack. That includes the trades it chose not to
  take. These labels feed CJ-2 / DESK-11 and the distillation design. For each role there is a stated
  hand-off: **student shadow → student advisory → student drives**, each step gated on out-of-sample
  net R per capital-day, net of the full cost stack. Agreement with Claude is reported but never gates
  a step. § 4.
- **Safety is unchanged.** The order of evidence is: D-S0 blind replay net of the full cost stack →
  a mechanical 1–2-trade paper soak → real money under operator-granted mandates. Each account's
  RiskManager refuses per trade. Nothing halts (Prime Directive rule 7). § 8, § 9.
- **The desk is a training-data generator first** (§ 4A): every decision, no-action included, is
  recorded point in time with its priced alternatives and joined to its outcome. The plan for the second
  half (pipeline health, one desk-vs-student scorecard) is § 4B, and the plan for label volume beyond
  what live markets produce (historical backfill, offline training sessions) is § 4C.
- **The first thing to build is the label stream.** Shadow-recorded entry proposals on live markets
  cost no risk. Each one is graded on the real path after the fact, so teacher labels start to accrue
  from the day the shadow pilot runs, long before the desk trades a dollar. § 10.

### 0.4 Where the desk starts, and why every restriction is a stage

The operator, ~06:58Z (verbatim, row `DESK-15-ENTRY-GENERATION`): *"we should start with the live
review. It just needs to, like, the restrictions and the design doc shouldn't be based around keeping
it at that level. It should be based around moving towards the full-fledged cloud trading desk, which
again is the basis for training our MLs, which means that the design doc also needs to ensure that we're
using the desk in the correct way in order to generate data that trains the models and not just
executing the trades and then forgetting about them."*

**Phase 1 of the desk is the live trade review**, already live in `apply` for stop tightens (§ 1.1). It
is the desk's first role, not a standalone tool. Every limit on the desk today is a **stage** with a
named lift condition. None of them is the design's resting state.

| restriction today | stage it belongs to | what lifts it, on what evidence | row |
|---|---|---|---|
| in-trade applies are tighten-only on strategy trades | phase 1 | strategy-trade `close` / `partial_close`: the D-S0 exit unit passes, then an operator-granted exit mandate (§ 8.3) | DESK-7, DESK-13 |
| no desk entries | phase 1 | phase 2 shadow proposals start once the scan packet and the skill land; real orders start once D-S0 entry generation passes and the leg soaks 1–2 clean trades on paper (§ 8) | DESK-0B, DESK-16, DESK-6, DESK-18, DESK-17 |
| desk entries only on paper | phase 3 | `MD-PROMOTE-S1-S2` moves `claude_desk` onto `bybit_2` + mirror (a human-merge PR) | DESK-17, manager |
| no desk on prop accounts | phase 3 | the prop superset gate: the prop EV/survival gate against the firm's DD limits | DESK-17 + prop gate |
| 15-min floor on cadence | phases 1–3 | 5 min: VM packets + VM intake (DESK-1, DESK-4b). Below 5 min: a student, not Claude (§ 5.1) | DESK-1, DESK-4, DESK-19 |
| Claude decides every role | phases 1–3 | per role, a student passes S-shadow → S-advisory → S-drives (§ 4.3); Claude drops to a ρ audit | DESK-19 |
| packet is the only feed | phase 1 | live web context per decision, logged (`external_context`), as the next milestone after the prototype | DESK-14 |

The phases are: **1** in-trade on the strategies' trades (live) · **2** + entry generation in shadow,
every proposal a graded label · **3** the desk trades its own leg on paper, then real money · **4** the
system's own students take over role by role.

---

## 1. What exists today

### 1.1 Live state (read 2026-10-26 from the checklist; not re-observed on the VM by this lane)

| piece | state | source |
|---|---|---|
| In-trade management (live trade review) | **merged + deployed**: `apply_mode: apply` on every account, `MD-LIVE-TIGHTEN-SL` granted (#20199, merged ~06:00Z). A dry-run (#20241, 06:11Z) **observed** Bybit 6/6 `approve`, `alpaca_paper` 3 `approve` + 1 `refuse would_loosen`, and `ib_paper` `refuse no_amend_path`. **No real apply is observed yet**, so the row is `landed_unproven` | row `LTR-6R-APPLY-PATH` |
| Judgement applies when the outcome table is thin | in flight | lane `LTR-JUDGEMENT-APPLY` |
| Desk packet v3 + decision schemas + guard | `landed_unproven`. **They encode v0's veto framing**: the `market_watch` enum is `no_action / watch_note / delay_candidate / veto_candidate`, and `check_desk_records.py` refuses any applied action on any role except in-trade `tighten_sl`. Re-scoped by `DESK-0B` (§ 10) | row `DESK-0-SCHEMA`; `comms/schema/desk_decision.schema.json` |
| Entry generation | **does not exist.** No code path takes an entry from outside a strategy's signal builder (searched `src/` for an external-intent intake; none found) | this lane |
| Distillation design | merged, operator-approved | `docs/plans/ml-claude-distillation-DESIGN.md` |

### 1.2 Inputs carried from v0 § 1 (MEASURED 2026-10-25 unless marked)

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

## 2. Roles — the desk runs the trade lifecycle

### 2.1 The four roles, and the optional fifth

| role | what it decides | on whose trades | applied? | model |
|---|---|---|---|---|
| **1. Market watch + entry generation** | From a **scan packet** over the tradable universe (§ 2.3): `propose_entry` (a full trade spec, § 2.4) or `no_trade`. It looks for trades **the strategies are not taking**: the scan packet lists the system's open packages and near-signals, so a proposal that duplicates one is visible and graded as a duplicate. | the desk's own | yes, as the `claude_desk` leg, at that leg's ladder stage (§ 8): shadow → paper soak → real money | Sonnet decides; Opus confirms any proposal bound for a real-money or prop account |
| **2. In-trade management** | `hold / tighten_sl / tp_revise / flag_mechanics / …` on the in-trade packet. This is the live trade review. | **both**: the desk's own trades and the strategies' trades | **yes, today**, for `tighten_sl` within `MD-LIVE-TIGHTEN-SL` on every account (§ 1.1). On desk-leg trades, every in-trade action is the leg's own management (§ 3.8) | Sonnet; Opus on real-money and prop non-`hold` (LTR rule) |
| **3. Exit** | `hold / partial_close(frac) / close` | the desk's own: applied as the leg's own exit logic. The strategies': recommend only, until a mandate (§ 8.3) | desk leg yes; strategy legs no | Sonnet; Opus on real money |
| **4. Post-trade grade** | blind grade, then revealed grade (CJ-3) | both | n/a (a label) | per CJ-3 |
| *(optional)* **Strategy-entry review** | `take / skip / delay / no_recommendation` on a new strategy package | the strategies' | **never.** Record-only and optional; it feeds the `claude-blind-grade-student` line. It is never a veto, and no mandate is proposed for it | Sonnet, only when spare capacity exists |

**Why the desk owns roles 1–3 on its own trades.** A teacher label is worth most when the same mind
decided the entry, the management and the exit. Then a student can learn a whole policy, not three
disconnected opinions. On the strategies' trades the desk manages and exits (roles 2–3), but the
entry belongs to the strategy.

### 2.2 Layers (v0 § 2.1, re-pointed)

| layer | what | where | model |
|---|---|---|---|
| **L0 — desk plumbing** | Builds packets (scan, entry, in-trade, exit), computes due events, takes desk intents in, hands entries to the `claude_desk` leg and amends to the per-account gate, reads back, checks divergence, **replays every proposal and every decision on the real path** for its outcome label. No judgment. | live VM (session-side builders first, as LTR-11 did) | none |
| **Desk manager** | The standing loop session (v0 § 5.2–5.3). Each wake reads L0's `due` list, routes each packet to its role, writes decisions, spawns escalations, rotates itself. A wake with nothing due ends after one call. | Claude session | Sonnet |
| **Escalation** | Any real-money or prop proposal or non-default action; any `flag_mechanics`. | spawned session | Opus |
| **Blind teacher sample** | A fraction ρ of decisions re-judged by Opus from the same packet without seeing Sonnet's answer (§ 4.5). Entry generation is sampled first: it is where the label is newest. | daily batch | Opus |

v0's reasoning that roles are **not** separate sessions still holds: one session pays the base context
once per wake (v0 § 2.1, retained in § 5.3).

### 2.3 Packets — one envelope, four kinds, shared by Claude and ML

Packet v3 (`comms/schema/desk_packet.schema.json`, DESK-0) has `entry`, `in_trade` and `exit`. v1 adds
**`scan`** (DESK-0B):

| block | scan (new) |
|---|---|
| `meta` | as v3, with `info_cutoff_at` |
| `universe[]` | per symbol: venue, tradable-by-account-class, last close, ATR, HTF trend, regime cell, funding, distance to recent swing levels, session / calendar window, spread read **with a read state**. **The universe is anything the venues list** (DECIDED, § 11). It has two tiers. Symbols that some account already pulls (`_resolve_tick_symbols`'s union) get the full block. Every other venue-listed symbol gets a lightweight row (ticker, 24 h volume, spread) so the desk can nominate it. A nominated symbol is onboarded (§ 3.9) before a proposal on it can be priced or traded |
| `system_book[]` | the strategies' open packages and **near-signals** (legs within one bar of a signal), so "a trade the system isn't finding" is checkable |
| `desk_book[]` | the desk's own open trades and pending proposals |
| `history` | per symbol, the base rates the desk needs to price a bracket: the distribution of forward R at the declared horizon, net of the full cost stack, from the same Stage-0 data (`execution_costs.resolve_cost_policy()`) |
| `ml[]` | the served heads' predictions, with an explicit `absent` state |

The binding rules of v0 carry over unchanged: could-not-look is `null` plus `missing_inputs`, never zero;
`info_cutoff_at` on every packet; **the ML feature view is a projection of the packet**, so the student
trains on exactly what the teacher saw; the dataset schema **is** the packet schema.

### 2.4 Decision schemas (closed enums; prose is bookkeeping, never a label)

The common envelope is v0's (`decision_id, packet_sha, role, model, prompt_sha, skill_sha,
label_version, action, params, judge_prior, confidence, basis, rationale, external_context, …`).

**`propose_entry` — the entry-generation action.** Every field is required. A proposal missing one is
refused by the guard, not defaulted.

```
symbol, venue_class, side ∈ {long, short},
horizon_bars, timeframe,                       # the bar the thesis lives on
entry {type ∈ {market, limit, stop}, level, good_till_bars},
stop  {level, basis},                          # where the thesis is wrong
tp    {level, basis, p_hit},                   # a REAL predictive target (TP doctrine, below)
expected_r_net,                                # the desk's own net-of-cost estimate, at entry
thesis,                                        # text; bookkeeping, never a feature
confidence ∈ {measured, suggestive, anecdote},
judge_prior,                                   # P(TP before SL)
novelty ∈ {new, duplicates_system_package, duplicates_near_signal},
info_cutoff_at
```

- **No size field.** Size is the account's: each account's RiskManager sizes a `claude_desk` package
  the same way it sizes any leg's (§ 3.7). The desk names where the trade is wrong and where it is
  expected to end; each account decides how much of it to hold.
- **The TP doctrine binds at proposal time** (`docs/ARCHITECTURE-CANONICAL.md` § "TP doctrine"). `tp`
  is a level the desk predicts price will reach, with a stated `basis` and `p_hit`. A sentinel
  distance, a venue-cap level or "trail decides" is refused by the guard. The prediction then moves
  through the trade by `tp_revise` (role 2), which is the doctrine's second clause.
- **`no_trade` is a decision, and it is recorded** whenever a scan wake has something due. The label
  for a `no_trade` is the best bracket a baseline would have taken from the same packet (§ 8.1). That is
  how a student learns when *not* to trade, which is most of trading.

| role | action enum | default |
|---|---|---|
| market watch + entry generation | `no_trade`, `propose_entry`, `watch_note` | `no_trade` |
| in-trade | `hold`, `tighten_sl(level)`, `tp_revise(level)`, `flag_mechanics`, `no_recommendation`, `file_hypothesis` | `hold` |
| exit | `hold`, `partial_close(frac)`, `close` | `hold` |
| post-trade | blind grade, then revealed grade (CJ-3) | — |
| strategy-entry review (optional) | `take`, `skip`, `delay(bars)`, `no_recommendation` | `take`; never applied |

**What is still never in an enum, and why each is excluded:**

- a size or risk change: per-account risk is each account's (operator, 2026-10-25);
- a widened stop on a strategy's trade: the tighten-only mandate;
- a `mode:` / `execution:` / roster change: those are the two gates, and only their own paths write them;
- any halt (Prime Directive rule 7).

**v0's *"Never in any enum: … a new entry"* is deleted.**

### 2.5 Due events (L0)

| kind | events |
|---|---|
| scan | `bar_close` on each timeframe the desk trades (§ 5: 15 min floor), plus `calendar`, `vol_regime`, `funding` and `swing` events on any universe symbol |
| in_trade | LTR's list (`r_milestone`, `new_peak`, `giveback`, `near_target`, `swing`, `vol_regime`, `funding`, `calendar`, `mechanics`, `daily_floor`) on every open package, the desk's own included |
| exit | `trade_closed` (queues the post-trade grade and the outcome replay) |
| entry (optional) | `package_created`, for the optional strategy-entry review |

Dedupe, cooldown and batching stay as in LTR § 2. **A cadence wake with nothing due costs one call and
records nothing** (operator, 2026-10-25 point 4).

---

## 3. Execution — two paths, both through each account's own risk manager

**This is the amend path** — how a package-level in-trade decision (role 2) reaches each account. It
is carried from v0 and is now live for `tighten_sl` (§ 1.1). Entries take the path in § 3.7. It
re-scopes LTR-6, LTR-8 and LTR-9 (operator point 2; the manager's finding on `LTR-6-APPLY-PATH`).

### 3.0 The adopted interface (lane `LTR-6R-APPLY-PATH`, manager relay 2026-10-25 17:37Z)

The design uses LTR-6R's names and does not define a parallel set:

- **`LiveReviewIntent`**, at package level. `action ∈ {tighten_sl, flag, no_action}`, plus level,
  evidence and mandate. The desk's in-trade enum (§ 2.4) maps onto it as follows: `tighten_sl` →
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

**v0's `approve_entry(intent)` is dropped.** It existed only for the withdrawn `skip` / `delay` veto.
Desk entries do not need a new gate: they are order packages on the `claude_desk` leg and pass the
existing `RiskManager.approve()` (§ 3.7).

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
   - Desk grading (§ 4.7) uses touched trades for the applied effect and untouched ones as the control.
   - The Gate-2 demotion read on `bybit_2` + `bybit_portfolio` is unaffected while they stay in
     `recommend`, and is split the same way once they apply (LTR § 5).
4. **Untouched trades stay the default.** INFERRED: most `bybit_1` trades are never touched, because
   most reviews are `hold` (1 of 2 real-money LTR rows in the first run). So the soak keeps its
   population.
5. **The `bybit_1` mechanics evidence** for the desk is the first 1–2 clean applies: verdict, readback
   and divergence check all clean (the operator later chose *"All accounts"* for tighten applies, 2026-10-25, row `DESK-13-MANDATE`).

### 3.7 Entries — the desk trades as the `claude_desk` leg (new in v1)

```
desk decision: propose_entry (package level, decision_id, packet_sha)
   │  validated by L0: schema, TP doctrine, symbol in the universe, not expired, evidence on record
   ▼
desk intake (DESK-4: the system-action route first, a VM endpoint later)
   ▼
claude_desk strategy adapter (DESK-17)        reads unexpired accepted proposals each tick; emits ONE
   │                                           order package per proposal, signal_logic = desk, carrying
   │                                           decision_id; entry / SL / TP exactly as proposed
   ▼
Coordinator.multi_account_execute             the existing path: the account's mode: and the leg's
   │                                           execution: fold into effective_dry as for any leg
   ├──► account A: RiskManager_A.approve(package) → size → executor_A
   ├──► mirror B:  RiskManager_B.approve(package) → size → executor_B
   └──► …                                       (a refusal is a logged, per-trade outcome)
```

- **One leg, one roster entry per account.** `claude_desk` sits in `config/strategies.yaml` and on
  account rosters like any leg. Where it trades is decided by the same two gates and roster membership,
  so CI's existing asymmetry rules apply to it unchanged. Adding it to a real-money roster is a roster
  edit under `MD-PROMOTE-S1-S2`, which opens a human-merge PR (§ 8).
- **Each account sizes the trade.** `RiskManager.approve()` applies that account's per-trade risk, its
  concurrency and exposure limits, and its daily-DD switch (*"keep open, block new"*): a tripped
  switch refuses the desk's new entries exactly as it refuses any leg's.
- **The desk's bracket is the package's bracket.** It is not re-derived by a class default, so
  `check_tp_doctrine.py` measures the desk leg on the proposals' `tp.basis`, not on a `tp_r`.
- **The mirror carries the leg.** When `claude_desk` is on `bybit_2` it is on `bybit_portfolio`, by
  the existing strict-equality tests. No exception is proposed.
- **Expiry.** A proposal that has not filled by `good_till_bars` is cancelled and recorded as
  `expired_unfilled`. That is an outcome, not an error.
- **Prop accounts** get the leg only through the prop superset gate (CLAUDE.md § promotion ladder):
  everything above plus the prop EV/survival gate against the firm's DD limits.

**Why a leg, and not a new desk order path.** A leg inherits every guard the repo already has: risk
sizing, the two gates, roster CI, the mirror tests, TP-doctrine measurement, the soak contract, Gate-2
demotion and per-trade refusals. A desk-specific path would have to rebuild each of them, and the ones
it forgot would be the bugs. This is the "no third gate" rule applied to the desk.

### 3.8 The desk's own trades after entry

On a `claude_desk` trade, the desk's in-trade and exit decisions **are the leg's management logic**:

- `tighten_sl` and `tp_revise` go through the amend path (§ 3.0–3.3). They are per-account and
  readback-checked. On a desk trade a `tp_revise` may move the target either way, because it is the
  leg's own prediction; widening the **stop** is still never allowed.
- `close` / `partial_close` go through the account's existing close path, per account, with the
  close reason `strategy_close` (desk). That is a first-class close reason, not a reconciler close.
- **The venue SL/TP and the monitor still protect every position**, whatever the desk does (LTR § 1).
  If the desk session is down, a desk trade runs to its bracket. That is not a halt and it is not
  unmanaged: the bracket is the plan.

### 3.9 Onboarding a venue-listed symbol (Q1 DECIDED: *"Anything the venues list"*)

A desk proposal on a symbol is **priced and traded only once all five hold**. Until then it is recorded
as `propose_entry` with `onboarding: pending`, and it is graded by replay once candles exist:

1. **Candles are pulled.** The symbol is added to the account's `config/accounts.yaml::symbols` list.
   That list is a purely additive data-pull list, not a gate (CLAUDE.md § two execution gates), and
   history is backfilled far enough for the scan packet's forward-R base rates.
2. **A cost policy resolves.** `execution_costs.resolve_cost_policy()` returns fee, slippage and
   (perps) funding for the symbol. A venue-aware default is enough to replay; a symbol-specific
   measured slippage is preferred before real money, and `MD-PROMOTE-S1-S2`'s cost check applies.
3. **It has a roster home.** An account carrying `claude_desk` can trade the instrument: venue
   metadata (tick size, minimum size, contract type) reads cleanly, and for prop, the firm's instrument
   list allows it.
4. **The TP doctrine can be met.** The packet's `history` block has enough bars for a predictive
   target with a stated `basis`.
5. **The scan packet carries the full block for it** from the next build.

Row `DESK-26-SYMBOL-ONBOARD` (later phase) makes this automatic for a nominated symbol: it opens the
pull-list PR, backfills, resolves and records the cost policy, and checks venue metadata. A failure
on any step is a per-symbol refusal with a reason, retried, with one flag if it persists. It never
blocks the desk.

---

## 4. Teacher → student: how the system's models replace Claude

### 4.1 Every desk decision is a teacher label

A label is the triple **(packet, decision, realised outcome)**, joined on `packet_sha` and
`decision_id`:

| role | the decision | the outcome label | provenance |
|---|---|---|---|
| entry generation | `propose_entry` spec, or `no_trade` | the proposal's bracket **replayed on the real path** from `info_cutoff_at`, net of the full cost stack, whether or not it was executed; for executed trades also the realised fill outcome | `computed` (replay), `measured` (fills) |
| in-trade | the action and level | paired ΔR: managed − untouched bracket (LTR-5's replay) | `computed` |
| exit | close / partial / hold | ΔR versus holding to the bracket | `computed` |
| post-trade | blind grade | realised net R of the next trades (CJ-4's test) | `judgment` vs `measured` |

- **Shadow decisions are labels too.** A shadow `propose_entry` is replayed exactly like an executed
  one. So the label stream starts with DESK-6, before the leg trades anything.
- **Claude is a teacher, never ground truth.** Each row keeps the Claude label, the outcome and the
  counterfactual, with `label_provenance`. A student is trained on outcome-weighted targets, and every
  source re-qualifies through CJ-4 before any manifest trains on it (distillation § 3.3).
- **The feed.** Desk rows are a `claude_judgments` source (`kind: desk_<role>`, DESK-11 into CJ-2), so
  the students see exactly the projected `features_at_review` the teacher saw.
- **Exception rows** (`external_context.used = true`) are excluded from training sets by default and
  graded separately (v0 rule, unchanged).

### 4.2 The hand-off path per role

Each role moves through three steps independently. A step is a manifest's `target_deployment_stage` on
the existing `candidate → shadow → advisory` ladder; "drives" is the new top step for a role.

| step | what the student does | what Claude does |
|---|---|---|
| **S-shadow** | decides on every packet the desk sees; recorded, never applied | decides and drives |
| **S-advisory** | its decision is shown to the desk in the packet (`ml[]`, three-state) and recorded | still decides; its rate of disagreeing with the student is measured |
| **S-drives** | it is the decider for that role. Its decisions go through the same intake, leg and gates as Claude's did | drops to the ρ blind-teacher audit (§ 4.5) on a sample of the student's packets |

The student that drives entries trades as **its own leg** (`ml_desk_<role>`), not as `claude_desk`.
So it climbs the promotion ladder itself (§ 8): its D-S0 replay, its 1–2-trade mechanical soak, then
`MD-PROMOTE-S1-S2`. Claude's leg is demoted by the existing Gate-2 path only when the student's leg is
live on the same accounts. **Removing Claude from a role is therefore a roster change**, with every
guard a roster change already has.

### 4.3 The measured criteria for each step (registered before the run)

The deciding metric is **net R per capital-day**: Σ net R ÷ Σ (risk-units × days held). It is net of
the full cost stack (`execution_costs.resolve_cost_policy()`), measured out of sample on packets the
student never trained on (purged walk-forward, the distillation § 3.5 leakage tests). It is used
instead of R per trade so a policy cannot look better by holding longer or trading more.

| step | gate (all must hold) | agreement's role |
|---|---|---|
| **candidate → S-shadow** | the manifest trains; § 3.5 leakage tests pass; the source is CJ-4 qualified | reported only |
| **S-shadow → S-advisory** | over n ≥ 150 out-of-sample decisions (the CJ-4 floor; INFERRED adequate for a sign test, not for a size estimate): student net R per capital-day **> 0**, CI excluding 0, **and** not worse than the role's baseline (entry: no-trade and the strategies' own signals on the same windows; in-trade: always-hold and the leg's best static trail) | reported. A student that agrees with Claude but loses money fails; one that disagrees and wins passes |
| **S-advisory → S-drives** | over at least the ML-D2 label wall (n ≥ 300) and in practice the n the precision floor below implies, with the student's leg having passed its own D-S0 and mechanical soak: student net R per capital-day **≥ Claude's on the same packets: margin 0, the student must match or beat Claude** (DECIDED, § 11 Q2). Concretely: the point estimate of the paired difference (student − Claude) is ≥ 0 overall and in ≥ 2/3 folds, **and** the difference is measured precisely enough that "match" means something: a 95% CI half-width ≤ 0.02 R. INFERRED n: at a paired per-decision sd of ~0.4 R (v0's in-trade assumption), half-width 1.96 · 0.4 / √n ≤ 0.02 gives **n ≈ 1,540 paired out-of-sample decisions** per role, about 5× the 300-label wall. That is why § 4C's offline labels matter; and live cost fidelity on the student's soak trades within the armed `cost_tolerance_bps` | reported. If agreement is high and the margin passes, the hand-off costs nothing; if agreement is low and the student still passes, the student has found something Claude does not |
| **S-drives → (Claude retired from the role)** | none beyond S-drives: Claude stays as the ρ audit until the operator says otherwise | the audit's agreement and outcome gap are the **drift** monitor; a student whose audited outcome gap turns negative over the last 50 audited packets is proposed for demotion back to S-advisory (a proposal, never a self-flip) |

**Why "match or beat" is not a superiority test.** The operator set the margin at zero: the student
must match or beat Claude. It is not required to *prove* it beats Claude (a CI lower bound > 0), because a
student that truly matches would then fail forever and Claude would never leave the loop. The precision
floor (half-width ≤ 0.02 R) stops a noisy student from "matching" by luck.

**Order of hand-off (INFERRED from label volume).** In-trade first: LTR rows accrue on every open
package and the label is computed, not judged. Entry generation second: it needs n ≥ 300 proposals
*with* outcomes, and at the § 7 rates (≈ 4–8 proposals a day, UNMEASURED until DESK-6) that is
about 6–12 weeks of shadow proposals, or less with the D-S0 replay set (§ 8.1). Exit last: it has the
fewest decisions.

### 4.4 Model tiering (v0 § 4.1, re-pointed)


| tier | what | why this model |
|---|---|---|
| **L0** | packets, due events, gate, executor, divergence, counterfactual replay | deterministic; $0 in usage |
| **Haiku** | only the cheap watcher, if one is needed, that spawns short-hold lanes when the desk session itself is idle (§ 6.3) | a yes/no on an L0 field |
| **Sonnet** | every live decision, in the standing desk session | warm cache, 1.82× cheaper than Opus (§ 1), and judgment is bounded by the packet and the closed enum |
| **Opus** | (a) escalations: real-money / prop non-default actions and `flag_mechanics`; (b) the blind teacher sample; (c) the weekly grading sample | where we learn, and where real money moves. This is the model table's rule *"anything on a real-money order path: Opus"* (manager SKILL) and the operator's *"Opus doing the review and not the actual live management"* |

**An unattended real-money apply always has Opus in its chain.** A Sonnet `tighten_sl` on a real-money
or prop package is an escalation candidate by definition. Opus confirms it before the intent is issued,
which is LTR § 6.6's rule carried over. Paper and shadow records never escalate.

### 4.5 The dial: teacher sampling rate ρ

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

### 4.6 Measuring the tiers

Sonnet–Opus **agreement** per role is a diagnostic, never a promotion metric (distillation § 3.6). The
outcome metric is **ΔR versus counterfactual, net**, per role and per model, over the same packets. If
the Opus teacher and the Sonnet decider disagree and outcomes favour Opus on a role, that role's live
tier moves to Opus. That is a proposal on evidence through the normal path, not a reflex.

### 4.7 Grading (folds in LTR-5)

The weekly grading is LTR-5's counterfactual replay, generalised per role:

- **In-trade:** actual minus untouched-bracket replay, with touched and untouched trades split.
- **Strategy-entry review (optional, record-only):** take/skip selection lift versus take-all and
  versus the strategy's own `confidence` (the ML-M5 rule shape).
- **Entry generation (first):** net R per capital-day of proposals, replayed and realised, against no-trade, the random-entry baseline and the strategies' own signals on the same windows; split by `novelty`; `expected_r_net` and `p_hit` calibration.
- **Post-trade:** blind-vs-revealed gap (CJ-3).

Calibration of `judge_prior` and `confidence` per role and per model. An A–F grade on a sample of
decision rows, keyed by `decision_id`.

---

## 4A. The desk as a training-data generator (a hard requirement)

The desk is only worth its usage if what it does is **learnable**. A desk that trades and forgets is
the failure the operator named. Each item below is a requirement on the build, with the row that builds
it.

| requirement | rule | row |
|---|---|---|
| **Point-in-time inputs** | the full packet as seen, `packet_sha`, `info_cutoff_at`; no field later than the cutoff (distillation § 3.5 test 1) | DESK-0 (built), DESK-0B, DESK-16 |
| **Every decision, including no-action** | `hold`, `no_trade` and `no_recommendation` are rows whenever something was due. A wake with nothing due records nothing (§ 2.5); that is cost control, and the due log says what was not looked at | DESK-0B, DESK-6 |
| **The alternatives, priced** | each row carries `alternatives[]`: the actions the role could have taken, each with its counterfactual from the packet's history block (LTR-0 table for in-trade; the forward-R base rate for entry). The student learns from the choice *and* the options | DESK-0B (field), DESK-7 (pricing) |
| **Per-account verdicts and fills** | each account's gate verdict, the fill, the readback and the close reason, keyed by `decision_id` | LTR-6R (built for amends), DESK-17 (entries) |
| **The realised outcome, joined back after close** | net R (full cost stack), MAE, MFE, giveback from peak, bars held, close reason; and the replayed outcome for shadow or untaken actions | DESK-20 (new) |
| **Stable ids** | `decision_id → intent_id → order_package_id → trade_id(per account) → outcome_id`, one join, no fuzzy match | DESK-0B, DESK-20 |
| **Schema versioning** | `schema_version` on packets and rows; `label_version` = (model, skill_sha, prompt_sha) on decisions | DESK-0 (built), DESK-0B |
| **Canonical store** | records project over existing stores: `comms/desk/` and `comms/live_review/` (append-only, guarded), `order_packages` meta, the trade journal for fills and outcomes. A new table only with the operator's OK and a backfill (Generation Discipline Rule 3) | DESK-20 |
| **Label quality** | no post-hoc relabel (append-only; a correction is a new row that cites the old one); the post-trade grade is blind first (CJ-3); exception rows are separable (`external_context.used`) | DESK-0 guard, CJ-3 |
| **Coverage, not just volume** | targets per (role × regime cell × symbol class × state bucket). Where a cell is under-covered, the teacher sample ρ and **shadow-only exploration** (a share of scan wakes forced to price a proposal the desk would not make) fill it, so the dataset is not only the states Claude likes. Exploration never reaches an order | DESK-23 (new) |
| **The consumer path, proven** | desk rows → `claude_judgments` (CJ-2, `kind: desk_<role>`) → manifests (CJ-5, DESK-19) → registry. A **"recorded but never trained on" detector** fails when a decision row older than 14 days is in no dataset build's consumed-id list | DESK-11, CJ-2, DESK-21 (new) |

---

## 4B. The second half: from desk data to models that replace the desk (a PLAN)

The operator, ~07:02Z (verbatim): *"it's not like we end up having this great trading desk that is
pushing structured data into a void … we can have the trading desk and measure the trading desk, and
that we can measure the MLs and measure how much they're improving and measure them against the cloud
trading desk, so that we have, like, a benchmark."* This section is the plan; its rows queue as later
phases.

### 4B.1 The pipeline, hop by hop — what exists (MEASURED by reading the repo, 2026-10-26)

| hop | today | missing | row |
|---|---|---|---|
| desk record | `comms/desk/` schema + guard exist; **0 rows** in `decisions.jsonl`. `comms/live_review/reviews.jsonl` has **15 rows** | the desk session writing rows (DESK-6); LTR rows reaching the desk shape | DESK-6, DESK-11 |
| dataset | dataset families live in `ml/datasets/families/`. **There is no `claude_judgments` family**; the nearest is `review_journal.py`, and its manifest `baseline-post-trade-review.yaml` is `.disabled` | the family, its leakage tests, the desk sources | CJ-2, DESK-11 |
| training | `scripts/ops/run_training_cycle.sh` on the trainer VM trains every enabled `ml/configs/` manifest. **No enabled manifest reads Claude or desk labels** | student manifests | CJ-5, DESK-19 |
| registry | `ml/registry/model_registry.py`, with the `candidate → shadow → advisory` ladder | a per-role hand-off status beside the ladder stage | DESK-19 |
| liveness | `scripts/ops/ml_plan_status.py --plumbing` checks the ML plan's plumbing | a check per hop for desk data, and the never-trained-on detector | DESK-21 |

### 4B.2 One scorecard (DESK-22)

One generated table, the same population for desk and students:

| block | per role | measured over |
|---|---|---|
| **(a) the desk** | net R per capital-day (full cost stack); hit rate; calibration of `judge_prior` / `p_hit` / `confidence`; giveback from peak; latency bar-close → decision; $ per decision | every desk decision with an outcome in the window, live and shadow split |
| **(b) each student** | agreement with the desk (diagnostic); its own counterfactual net R per capital-day | **the same decisions**, out of sample to the student |
| **(c) student vs desk** | the gap in net R per capital-day with its CI; the **improvement curve**: the gap at each retrain, plotted against labels seen | rolling, by retrain |
| **(d) hand-off state** | the step each student is at, the § 4.3 threshold for the next step, the demotion rule back | — |

**Reporting homes:** the `/ml-review` step-9 block (the ML plan loop, which CJ-6 already plans to
extend), a "Desk" section in `/performance-review` (DESK-9), and one line in the brief's "what moved".
DESK-22 extends CJ-6 rather than building a second hook.

---

## 4C. Label volume: not waiting on the market (a PLAN)

The operator, ~07:08Z (verbatim): *"what's my fear is that the trading desk will work well, but it'll
just generate too few trades for the MLs to be able to learn from at, like, a reasonable pace … I want
to see if we can also set up a flow, doing sort of, like, you know, more historical trading or, like,
other training sessions so that we can up the pace of the ML learning and not only be dependent on how
quickly trades are actually developing in the market."*

### 4C.1 The gap at live pace alone (INFERRED)

The floors come from the distillation design: CJ-4 validation n ≥ **150** distinct trades; the label
wall n ≥ **300** (ML-D2), which § 4.3 uses for S-drives. **Distinct trades** count, not decisions: 23
in-trade decisions a day on the same few trades are correlated.

| role | live label rate | time to n = 150 | time to n = 300 |
|---|---|---|---|
| in-trade, real money only | **0.82** new positions a day (MEASURED, real-money accounts, LTR design § 6.1) | ≈ 6 months | ≈ 12 months |
| in-trade, all books (paper and prop added) | UNMEASURED; INFERRED ≈ 2–3× real money | ≈ 2–3 months | ≈ 4–6 months |
| entry generation (shadow proposals) | **assumed** 4–8 a day (DESK-6 measures it) | ≈ 3–5 weeks | ≈ 6–11 weeks |
| exit | a subset of in-trade | longer than in-trade | longer than in-trade |

So at live pace the in-trade and exit students wait months. Entry generation is quicker because a
shadow proposal is labelled whether or not it trades. Offline labels close the gap.

### 4C.2 Historical backfill (reconciles with CJ-7)

- **Run the desk roles on masked, point-in-time packets** for the **1,823** historical closed trades
  (the distillation design's count of distinct `linked_trade_id`) and on the Stage-0 backtest trade
  lists, using DESK-7's harness and masking. Outcomes are computed on the real candles.
- ⚠️ **The memory trap.** Most of those trades predate the judge model's knowledge cutoff, so they carry
  `pre_cutoff: true` and are **excluded from validation and from every gate** by default (distillation
  § 3.5.5). They may train a student; they may not prove one. The gates run on post-cutoff history and
  on forward shadow rows.
- CJ-7 (backfill scope) owns the sizing. This design asks that its scope cover in-trade, exit and
  post-trade on those trades, not post-trade grades alone.

### 4C.3 A standing offline training-session flow (DESK-24)

- **Desk sessions that walk history bar by bar as if live**: scan → propose → manage → exit, on masked
  candles and the strategies' backtest ledgers, through the same skill, schemas and enums. Each session
  is a batch over a declared window, so its labels are reproducible.
- **Synthetic or perturbed episodes are optional** (block-bootstrapped or regime-spliced paths). They
  carry `label_provenance: synthetic`, are **never mixed into live-performance numbers or any gate**,
  and get zero training weight until the ablation (§ 4C.4) shows they help.
- **Weighting:** live and forward-shadow labels weight 1.0. Masked historical labels weight 1.0 for
  training and 0 for gates. Synthetic labels start at 0. The source is kept as a stratum, so the
  ablation can re-weight.

### 4C.4 Cost, budget dial, proof

- **Cost per label** is measured on a pilot through `get_session().usage` deltas and `spend_meter`.
  INFERRED starting point: ≈ $0.04 a decision for a Sonnet working wake (§ 5.3). 1,000 offline labels
  ≈ $40. **UNMEASURED** until the DESK-24 pilot runs.
- **The budget dial** is offline labels per week, set by the operator, scheduled inside the weekly
  reserve (§ 7). It is the first thing cut in a breach, before ρ.
- **The proof is an ablation** (DESK-25): the same student trained with and without offline labels,
  out of sample on post-cutoff and forward-shadow rows, net R per capital-day. If offline labels do not
  help, the dial goes to zero and that is the answer.

---

## 5. Short-timeframe feasibility — latency, cost, rotation (carried from v0)

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

## 6. Can a short-hold (10 min – 1 h) lane be profitable? (carried from v0)

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

## 7. Capacity plan (carried from v0, with the scan wake added)

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
| **2 — + entry generation (shadow scan wakes) + paper record-only** | a scan wake at each 15-min bar close: ASSUMED every bar is due, ≈ 96 working wakes/day × $0.041 (§ 5.3 Sonnet working wake) ≈ **$4**; Opus confirms on real-money-bound proposals; paper packages roughly double n̄ (+~$2). Proposals per day are UNMEASURED (assumed 4–8) | ≈ $10.5 | 0.9–2.1 | 6–13% |
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
  1. offline training sessions (§ 4C) → 0;
  2. teacher ρ → 0;
  3. drop the optional strategy-entry review, then lengthen the scan cadence to 1 h (entry generation
     keeps running, at a lower label rate);
  4. paper → L0-only;
  5. the in-trade role keeps running, degraded to recommend-only on Sonnet.

---

## 8. The promotion ladder for the desk (it sits INSIDE the ladder)

A live or paper book never establishes edge (CLAUDE.md). The desk's judgment cannot be backtested like
a strategy, so its Stage 0 is a **blind replay**, registered before the run. Each role climbs on its own.

### 8.1 D-S0 — offline, per role, net of the full cost stack

| role | the replay | the rule (registered in a `research/queue/` unit before the run) |
|---|---|---|
| **entry generation** (DESK-18) | Historical **scan packets** rebuilt point in time at sampled bar closes, **masked** (no symbol names, no dates, prices ATR-normalised; distillation § 3.5.5). The desk proposes or passes; each proposal's bracket is replayed on the real path with the full cost stack. | Net R per capital-day **> 0** with the 95% CI excluding 0; **beats a random-entry baseline** that uses the desk's own bracket geometry at random times on the same symbols (so the edge is in the *timing*, not the bracket); **and is not a re-labelling of the strategies**: the subset with `novelty = new` must pass on its own. ≥ 2/3 folds positive. INFERRED n: with a per-trade net-R sd of ~1.0 R, detecting +0.10 R needs n ≈ (2.8 · 1.0 / 0.10)² ≈ **780 proposals**, and +0.20 R needs ≈ **200**. |
| **in-trade** (DESK-7) | v0's paired-counterfactual replay, unchanged | paired ΔR > 0 net of amend slippage, CI excluding 0 (≈ 125 trades for +0.10 R at a paired sd of 0.4 R) |
| **exit** (DESK-7) | the same harness, `close` / `partial_close` actions | ΔR versus holding to the bracket > 0, CI excluding 0 |

**Two OOS sets, one rule (proposed).** The masked replay gives n quickly but can leak hindsight through
model memory despite masking. **Forward shadow proposals** (DESK-6, from live packets) cannot leak: the
outcome did not exist when Claude decided. The D-S0 entry-generation rule is registered over **both**:
pass on the replay at the stated n, **and** the forward-shadow set must not contradict it (its point
estimate > 0 once it reaches n ≥ 100). The forward set is not a paper book establishing edge: it is the
same blind, pre-registered, cost-stacked replay run on packets that were built before their outcomes.

**Version pinning.** A desk leg is `(model, skill_sha, prompt_sha)` = its `label_version`. A change of
model family re-runs the entry-generation replay on a confirm set (n ≥ 200, the same rule) before the
changed desk trades. A skill text edit is recorded and graded; it does not re-run Stage 0.

### 8.2 D-S1 — mechanical soak on paper, 1–2 trades

- **Mechanics, never a sample size, never a date** (OPERATING-PLAN § 2 "The soak is MECHANICAL").
- `claude_desk` goes on `bybit_1` (the DECIDED sandbox) and `alpaca_paper` once D-S0 entry generation
  passes. The soak is **1–2 clean desk trades**: proposal → intake → package → each account's `approve()`
  → fill → bracket on the venue → in-trade decisions applied and read back → close with a correct
  close reason → graded.
- Until D-S0 passes the leg is rostered `execution: shadow`: it builds and logs packages everywhere and
  sends nothing. That is the shadow stage, and it is where the label stream starts.
- The touched/untouched split of v0 § 3.6 still applies to strategy trades on `bybit_1`. A `claude_desk`
  trade is the desk's own, so it is not "touched": it is its own leg's record.

### 8.3 D-S2 — real money under operator-granted mandates

| what | mandate | state |
|---|---|---|
| `claude_desk` onto `bybit_2` + `bybit_portfolio` (and Alpaca live + mirror) | `MD-PROMOTE-S1-S2`, as for any leg: a fire opens a **human-merge** PR after the portfolio-overlap check, with cost checked against the measured Bybit cost | granted and armed (`config/mandates.yaml`); no new mandate needed |
| tighten-only stops on any trade | `MD-LIVE-TIGHTEN-SL` | granted; live |
| desk exits (`close` / `partial_close`) on **strategy** trades | **new**, proposed by DESK-13 after the D-S0 exit unit passes; the operator grants | not proposed yet |
| desk on prop accounts | the prop superset gate (prop EV/survival vs the firm's DD limits) on top of the above | — |
| a student driving a role on real money | its own leg through `MD-PROMOTE-S1-S2` (§ 4.2) | — |

**Demotion** is the existing Gate-2 signal: the live + mirror net-of-cost window. `MD-DEMOTE-S2-S1` is
armed for auto-land and applies to `claude_desk` like any leg.

---

## 9. Safety — unchanged, and how each rule binds the desk

| rule | how it binds the desk |
|---|---|
| **Each account's RiskManager** | Entries pass `approve()` (§ 3.7); amends pass `approve_amend()` (§ 3.2). The desk has no size field and never sees an account's bounds |
| **Per-trade refusals** | A refused desk entry or amend is a logged, per-account outcome, retried while unexpired, one flag if it keeps failing |
| **The two execution gates, no third** | `mode:` and `execution:` plus roster membership decide where `claude_desk` trades. No `DESK_ENABLED` flag exists or may be added |
| **The promotion ladder** | § 8: D-S0 blind replay net of the full cost stack → mechanical paper soak (1–2 trades) → real money under `MD-PROMOTE-S1-S2` |
| **TP doctrine** | Every proposal carries a predictive TP with a basis; `tp_revise` moves the prediction; the guard measures the leg |
| **No halting (Prime Directive rule 7)** | A dead desk session leaves desk trades on their venue brackets and strategy trades on theirs; nothing turns itself off. A stale heartbeat raises one flag (§ 12). The daily-DD switch is the one sanctioned off switch, and it blocks new desk entries like any leg's |
| **Live P&L never promotes** | The desk's live record feeds grading and the label set; promotion rests on D-S0 |

---

## 10. Build plan — re-sequenced to "Claude drives, the models learn"

Every row carries `roadmap: [L-DESK]` and a `writeback` to `L-DESK` and to
`docs/ARCHITECTURE-CANONICAL.md`. The manager files the new rows; this PR re-scopes existing ones only
by note (§ 13).

### 10.1 The critical path

```
DESK-0B → DESK-16 → DESK-6 ─────────────► labels accrue (shadow proposals, graded on the real path)
                 └→ DESK-18 (D-S0 entry generation) ─┐
DESK-0B → DESK-4a → DESK-17 (claude_desk leg, shadow) ┴→ bybit_1 / alpaca_paper soak (1–2 trades)
                                                        → MD-PROMOTE-S1-S2 → bybit_2 + mirror
DESK-11 → CJ-2 → CJ-4 → DESK-19 (students: shadow → advisory → drives)
later: DESK-20 (outcome join) · DESK-21 (never-trained detector) · DESK-22 (scorecard) ·
       DESK-23 (coverage) · DESK-24 → DESK-25 (offline sessions, then the ablation that proves them) ·
       DESK-26 (venue-symbol onboarding)
```

### 10.2 All rows, in order

| order | id | what | tier | model | ceiling | depends on | change |
|---|---|---|---|---|---|---|---|
| 1 | `DESK-0B-SCHEMA-V2` | **new.** Schema v2: `scan` packet kind; role `entry_generation` with `no_trade / propose_entry / watch_note` and the § 2.4 fields; `alternatives[]` (priced) and the stable-id chain (§ 4A); TP-doctrine and no-size checks in `desk-records-guard`; desk-leg in-trade/exit actions applicable; the optional `entry_review` stays record-only; `veto_candidate` / `delay_candidate` removed | 1 | Sonnet | $6 | DESK-0 | fixes DESK-0's v0 enums |
| 2 | `DESK-16-SCAN-PACKETS` | **new.** Scan-packet builder (§ 2.3): universe from the pull lists, `system_book` with near-signals, per-symbol net-of-cost forward-R base rates; a **historical mode** (point in time, masked) for DESK-18; session-side first, VM route in DESK-1 | 1 | Sonnet | $8 | DESK-0B | — |
| 3 | `DESK-5-SKILL` | `.claude/skills/trading-desk/SKILL.md`: the loop, **entry generation first**, then in-trade (extends `live-trade-review`), exit; enums; escalation; ρ; rotation | 1 | Opus | $6 | DESK-0B | **re-scoped**: entry generation is the lead role |
| 4 | `DESK-6-SHADOW-PILOT` | standing 15-min Sonnet desk, record-only for entry generation (**shadow proposals, every one replayed for its label**) and live in-trade per LTR; measures latency, $/wake, `C0`, `Δ`, `f`, proposals/day | 1 | Sonnet (+ Opus sample) | $25 | DESK-5, DESK-16 | **re-scoped**: entry generation added; supersedes LTR-4 |
| 5 | `DESK-18-GEN-REPLAY-S0` | **new.** D-S0 for entry generation (§ 8.1): pre-registered `research/queue/` units, masked historical scan packets, random-entry and strategy baselines, `novelty = new` subset, both OOS sets | 1 | Sonnet + Opus sample | $30 | DESK-16, DESK-7 harness | — |
| 6 | `DESK-7-BLIND-REPLAY-S0` | the shared replay harness, plus D-S0 for in-trade and exit | 1 | Sonnet + Opus sample | $30 | DESK-0B, LTR-0, EXIT-PATH emits | **re-scoped**: entry review dropped; harness shared with DESK-18 |
| 7 | `DESK-4-INTAKE` | (a) `desk-intent` system-action carrying proposals and amends, latency recorded; (b) a VM intake endpoint (Tier 2) for 5 min | 2 | Opus | $10 | DESK-0B | **re-scoped**: carries entries |
| 8 | `DESK-17-DESK-LEG` | **new.** The `claude_desk` strategy adapter (§ 3.7): reads accepted proposals, emits one package each through `Coordinator.multi_account_execute`; `strategies.yaml` entry at `execution: shadow`; `bybit_1` + `alpaca_paper` rosters; expiry; close reason; TP-doctrine ratchet entry; tests | **3** (strategy logic + order path) | Opus | $16 | DESK-0B, DESK-4a | — |
| 9 | `DESK-12-SANDBOX` | `bybit_1` touch splits for strategy trades (v0 § 3.6) | 1 | Sonnet | $6 | LTR-6R records | unchanged |
| 10 | `DESK-2-RISK-GATE` | `approve_amend` remainder + `PropRiskManager.approve_amend` | 3 | Opus | $12 | — | **re-scoped**: `approve_entry` dropped |
| 11 | `DESK-3-EXECUTORS` | per-account executors behind the gate; **plus** per-account `close` / `partial_close` for desk-leg trades | 3 | Opus | $16 | DESK-2, PHONE-AMEND-REFUSED-1025 | **re-scoped**: desk-leg exits |
| 12 | `DESK-9-GRADING` | per-role grading (§ 4.7): **entry generation first** (net R per capital-day, novelty split, vs baselines), in-trade, exit, post-trade | 1 | Sonnet | $8 | DESK-6 records | **re-scoped** |
| 13 | `DESK-11-ML-FEED` | desk decisions as `claude_judgments` sources `kind: desk_entry_generation / desk_in_trade / desk_exit`, with § 4.1's outcome labels | 1 | Opus | $10 | DESK-0B, CJ-2 | **re-scoped**: entry-generation labels first |
| 14 | `DESK-19-STUDENT-HANDOFF` | **new.** Student manifests per role at `candidate`; the § 4.3 step criteria as pre-registered units (S-drives at margin 0, half-width ≤ 0.02 R, n ≈ 1,540 paired decisions per role); a per-role hand-off status in `ml_plan_status.py`; the `ml_desk_<role>` leg template | 1 | Sonnet | $8 | DESK-11, CJ-4 | — |
| 15 | `DESK-1-VM-PACKETS` | packet builds and due events (scan included) as VM read routes | 1 (read path) | Sonnet | $10 | DESK-0B | **re-scoped**: scan packets |
| 16 | `DESK-10-CAPACITY` | `k` ($/pp) and per-tier costs, including the scan wake | 1 | Sonnet | $4 | DESK-6 | unchanged |
| 17 | `DESK-13-MANDATE` | propose a strategy-trade exit mandate after the D-S0 exit unit passes; `claude_desk` promotes under `MD-PROMOTE-S1-S2` | 3 (grant) | — | — | DESK-7 exit PASS | **re-scoped**: `MD-DESK-SKIP` dropped |
| 18 | `DESK-8-SHORT-HOLD-S0` | unchanged (v0 § 6) | 1 | Sonnet | $10 | DESK-7 harness | unchanged |
| 19 | `DESK-14-LIVE-WEB-CONTEXT` | unchanged: the next milestone once the prototype is up | 1 | Opus | $10 | DESK-6 | unchanged |
| 20 | `DESK-20-OUTCOME-JOIN` | **new, later phase.** The outcome joiner (§ 4A): `decision_id → intent_id → order_package_id → trade_id → outcome`, net R (full cost stack), MAE / MFE / giveback / bars held / close reason, and replayed outcomes for shadow and untaken actions; projected over the existing stores | 1 | Sonnet | $8 | DESK-0B, DESK-6 records (DESK-17 for fills) | — |
| 21 | `DESK-21-NEVER-TRAINED-DETECTOR` | **new, later phase.** Per-hop liveness (record → dataset → training → registry) in `ml_plan_status.py --plumbing`, and the "recorded but never trained on" detector (§ 4A) as a guard or probe | 1 | Sonnet | $6 | DESK-11, CJ-2 | — |
| 22 | `DESK-22-SCORECARD` | **new, later phase.** The one scorecard (§ 4B.2): desk per role, students on the same decisions, student-vs-desk gap and improvement curve, hand-off state; homes in `/ml-review` step 9, `/performance-review`, the brief | 1 | Sonnet | $8 | DESK-9, DESK-19 | **extends CJ-6** |
| 23 | `DESK-23-COVERAGE` | **new, later phase.** Coverage targets per (role × regime cell × symbol class × state) and shadow-only exploration sampling (§ 4A) | 1 | Sonnet | $4 | DESK-6 | — |
| 24 | `DESK-24-OFFLINE-SESSIONS` | **new, later phase.** The standing offline training-session flow (§ 4C.3): bar-by-bar masked historical walks through the desk skill; a pilot that measures cost per label; the operator's budget dial | 1 | Sonnet (+ Opus sample) | $15 (pilot) | DESK-7 harness, DESK-16 historical mode, DESK-5 | reconciles with **CJ-7** (sizing) |
| 26 | `DESK-26-SYMBOL-ONBOARD` | **new, later phase.** Automatic onboarding of a venue-listed symbol the desk nominates (§ 3.9): pull-list PR to `accounts.yaml::symbols`, history backfill, `resolve_cost_policy()` recorded, venue metadata and prop instrument-list checks; per-symbol refusal with a reason, never a block | 2 (runtime config: the pull list) | Opus | $8 | DESK-16, DESK-17 | — |
| 25 | `DESK-25-OFFLINE-ABLATION` | **new, later phase.** Pre-registered ablation: student with vs without offline labels, OOS on post-cutoff + forward-shadow rows (§ 4C.4) | 1 | Sonnet | $6 | DESK-19, DESK-24 | — |

**New ceilings:** first phase DESK-0B $6 + DESK-16 $8 + DESK-18 $30 + DESK-17 $16 + DESK-19 $8 = **$68**;
later phases DESK-20 $8 + DESK-21 $6 + DESK-22 $8 + DESK-23 $4 + DESK-24 $15 + DESK-25 $6 + DESK-26 $8 = **$55**.
The operator asked to pace the budget (~07:02Z), so rows 20–25 queue behind the first phase rather than
now.

### 10.3 Rows that are now wrong

| row | what is wrong | fix |
|---|---|---|
| `DESK-0-SCHEMA` (`landed_unproven`) | the `market_watch` enum is veto-shaped; the guard refuses every applied non-tighten action | DESK-0B |
| `DESK-2-RISK-GATE` | `approve_entry` for skip/delay | dropped (§ 3.2) |
| `DESK-13-MANDATE` | proposes `MD-DESK-SKIP` | dropped |
| `DESK-7` / `DESK-9` | entry-*review* replay and grading as the entry stage | re-scoped to generation (DESK-18, DESK-9) |
| `L-DESK` milestone text | describes the v0 desk (roles "entry review"; "Claude never does…" framing; "awaiting operator review") | text proposed in the PR body; lane `LTR-JUDGEMENT-APPLY` owns today's edit |

---

## 11. Open questions (only where no data settles them)

**Settled 2026-10-26 ~07:12Z (operator popups, verbatim, relayed by the manager):**

- **Q1 universe: *"Anything the venues list"*** — DECIDED. This is not the data-pull-only option this
  design recommended. The onboarding steps are in § 3.9 and the row is DESK-26.
- **Q2 hand-off margin: *"Zero: must match or beat Claude"*** — DECIDED. § 4.3 is updated: n ≈ 1,540
  paired decisions per role (INFERRED).
- **Q3 final real-money hand-off: *"Yes, always my merge (Recommended)"*** — DECIDED. A student's leg
  reaches a real-money roster only through a human-merge PR.

**Settled earlier:** v0 Q1 (VM-side model call): *"Not now"*, 2026-10-26. v0 Q2 (should a skip
apply): **withdrawn**, it asked about the wrong design (§ 0.2). Feeds and sandbox: DECIDED 2026-10-25.

Things data will settle are **not** asked here, and their row gets the data instead: the cadence (DESK-6
measures it), the live model tier (§ 4.6), ρ (§ 4.5's rule), whether the desk has an edge (DESK-18),
and whether a student is good enough (§ 4.3).

No open questions remain.

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
| The desk proposes the strategies' own trades back to us | `system_book` + near-signals in the scan packet; `novelty` on every proposal; D-S0 passes on the `novelty = new` subset alone (§ 8.1) |
| Hindsight from model memory in the entry replay | masking, `pre_cutoff` exclusion, and the forward-shadow set as a leakage-free check (§ 8.1) |
| The desk sizes by the back door (wide stops, many proposals) | each account's `approve()` sizes on risk per trade and caps concurrency/exposure; net R per capital-day penalises capital tied up |
| A desk session dies with desk trades open | the venue bracket is the plan (§ 3.8); heartbeat flag; never a halt |
| Claude's behaviour changes under the leg (model or skill edits) | `label_version` pinning; a model-family change re-runs a D-S0 confirm set (§ 8.1) |
| Students learn to imitate Claude rather than to make money | every step gates on net R per capital-day; agreement never gates (§ 4.3) |

---

## 13. What this lane did and did not do

**Did:**

- read this design's v0 in full, the distillation design's guardrails, ladder and build plan, the
  DESK-*, LTR-6R, LTR-7, LTR-4/5 and CJ-2 rows, the DESK-15 and DESK-DESIGN rows on the register
  branch `mgr/reg-desk-decisions-1026` (PR #20256, open at the time), and `comms/schema/desk_decision.schema.json`;
- searched `src/` for an existing external-entry intake (none found) and checked `RiskManager.approve`
  (`src/units/accounts/risk.py:883`);
- rewrote §§ 0–4 and 8–13 and added §§ 0.4, 4A, 4B, 4C from the manager's three relays of the
  operator's 06:58Z, 07:02Z and 07:08Z words; carried §§ 3.0–3.6 and 5–7 from v0 with the veto
  references removed;
- counted `comms/desk/decisions.jsonl` (0 rows) and `comms/live_review/reviews.jsonl` (15 rows), and
  listed `ml/datasets/families/` (no `claude_judgments` family) and `ml/configs/` (no enabled manifest
  reads Claude or desk labels).

**Did not:**

- measure anything new. Every figure carried from v0 keeps its v0 mark; § 7's scan-wake line and
  § 4.3's proposals-per-day are **assumptions** until DESK-6 measures them;
- read the VM, any live diag, or any trade;
- file the new rows (the manager files them) or edit `docs/roadmap/milestones.yaml` (lane
  `LTR-JUDGEMENT-APPLY` owns `L-DESK` today).
