# Operating plan — decide offline, prove on the book

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
> **Supersedes:** the operating-layer model of 2026-09-01 (design phases A–H) in full.
> **Carrier chain:** [`CLAUDE.md`](../../CLAUDE.md) → this file → rows in
> [`docs/claude/work/MANAGER-CHECKLIST.json`](../claude/work/MANAGER-CHECKLIST.json)
> → the Workflow page on the SPA.
> A plan that no checklist row points at is a memo. Every item below has a row.

Companion page (same content, rendered):
<https://claude.ai/artifact/Fki6cnA5dbyHXSsdSKcVLv>

---

## 1. What this is fixing

Four measured facts, each with its population stated.

| figure | what it is |
|---|---|
| **−0.3231R** | lifetime expectancy, real money. `/api/bot/performance` `realMoney` all-window, 2026-09-21: n=431, 27.1% win, totalPnl −$88.64, profitFactor 0.68. 430 of 431 trades crypto; `vwap` alone is 318 of them at −0.4586R. |
| **0** | actionable verdicts from the daily strategy review. `comms/strategy_reviews/2026-09-20/INDEX.json`: 52 legs graded, 71 closes in the window, floor `min_closed_for_action: 20`, `by_action {"hold": 41, "no_offline_evidence": 11}`. Its own `days_to_grade_all_reachable_point: 140.0`, with `unbounded_no_closes: 23`. |
| **7.1 : 1** | commits to `docs/claude/work/` vs commits to `src/`, over 30 days: 1,005 against 141. `config/strategies.yaml` got 9. |
| **1** | research dispositions ever marked `actioned`, of 117. 404 research memos exist, 106 of them this month. None actioned since 2026-08-31. |

**Three things are true at once, and only the third is a process problem.**

1. **The fleet cannot grade itself.** 55 strategies across 11 accounts produce
   ~71 closes a week against a 20-per-leg floor. The review machinery is
   correct and structurally incapable of emitting a decision.
2. **Research terminates in a memo.** The memos are rigorous and honest. They
   end with "PROPOSE ONLY" and wait for a Tier-3 decision that arrives at a
   rate of roughly one per 117.
3. **The manager had nothing decidable to manage.** It was given eight
   registers — work store, lease, checklist, merge queue, session registry,
   coordination board, due-list, constraint readout — and forbidden from doing
   items. Register maintenance was the only output available to it.

### The one mechanical fact that explains the drift

`scripts/check_dry_run_in_diff.py` fails any PR that sets a strategy to
`execution: shadow` or an account to `mode: dry_run` without an inline operator
marker. Across all 78 guards there is **no counterpart**: nothing blocks adding
`execution: live`, and nothing requires evidence before a leg reaches a
real-money roster.

CI makes switching a strategy **off** need the operator's signature and
switching one **on** free. That is why the roster went 36 → 55 while every memo
said cut.

⚠️ **REFINED 2026-09-21, and the refinement changes what B1 must key on.** There
are **two** ways to take a leg off a book and the guard only sees one of them.
`check_dry_run_in_diff.py` matches on added `mode: dry_run` and
`execution: shadow` **lines** — so setting a leg to `shadow` is guarded, while
**removing it from an account's `strategies:` roster is not.** Verified by
running the guard against the A6 diff, which removes two legs from
`alpaca_live`: it reports `clean`.

So the asymmetry is sharper than "off is guarded, on is free". It is: **one
spelling of *off* is guarded, the other spelling of *off* is free, and *on* is
free by both spellings.** B1 must therefore key on **roster membership**, not on
the `mode`/`execution` fields — a guard that watches only the fields can be
walked around by editing the list, in either direction.

The rule this plan enforces already exists, in
[`docs/CLAUDE-RULES-CANONICAL.md`](../CLAUDE-RULES-CANONICAL.md) § "Promotion
evidence — offline edge, live mechanics". It is correct and it keeps losing,
because it is prose and the counter-pressure is CI.

> **Design principle for everything below:** the rules that matter are the ones
> CI enforces, and there must be very few of them.

---

## 2. The ladder

Three stages, two gates, one continuous falsifier. Each stage answers exactly
one question, and a leg moves only when that question is answered on evidence.

**The objective every decision rule serves: net P&L first, risk second** (operator, 2026-10-29). When P&L is even, the
lower-risk choice wins, and a large risk cut for a small, pre-stated R cost also wins. It is stated once, with the
operator's words, in [`docs/ARCHITECTURE-CANONICAL.md`](../ARCHITECTURE-CANONICAL.md) § "Active management". Its
in-trade form is `RULE-AM-RISK-ADJUSTED-V1`. Point at it; never restate it.

```
  STAGE 0   Backtest                     offline harness
            Is there an edge, net of the full cost stack?
            Leaves when — the result clears the rule REGISTERED BEFORE THE RUN,
            at the declared power. Nothing reaches a book without a committed
            evidence record.
                              ▼  GATE 1  ▼
  STAGE 1   Soak                         bybit_1 · alpaca_paper
            Do the MECHANICS work? (edge was already proven at Stage 0)
            Passes when — the first 1–2 CLEAN trades: the signal fires, the
            order is placed with the right size and side, a real SL and TP
            rest at the venue, management (trail/amend) works, the exit is
            journaled with a reason, and the fill and fees are recorded.
            Fails when — a mechanical fault; it is fixed, then re-soaked.
            It never waits on a sample size and has no calendar: a leg with
            no signal yet is "awaiting first trade", not failing.
            Realized cost and live-vs-backtest are ONGOING MONITORING here
            (the Gate-2 demotion signal, the underperformer first step) —
            NOT exit criteria.
            This stage may be WIDE. It is an instrument, not a decision surface.
                              ▼  GATE 2  ▼
  STAGE 2   Live + mirror   bybit_2 + bybit_portfolio · alpaca_live + alpaca_portfolio
            Real money. The mirror carries the IDENTICAL roster and the
            IDENTICAL trades, at honest size.
            Demotes when — the mirror goes net-negative net-of-cost over a
            declared window.
```

### Three strategy statuses: testing, production, inactive (operator, 2026-10-28, binding once merged)

<!-- STRATEGY-STATUS-CANONICAL: the ONE statement of the status model. Other docs point here. -->

**The rule.** Operator decision *"Adopt; build it this week"* (2026-10-28 ~21:05Z, relayed by the manager), in the operator's words:
*"All the real money strategies are trading on paper portfolio. Everything is trading on the general paper account. The idea is that
even poor strategies are generating data for us to learn from. But everything on real money is logging trades anyway, so we can take
them off of the general paper account."* and *"strategies have 3 statuses - in testing (live on general paper), in production (live on
real money and paper portfolio), and inactive (if several rounds of research had proven it's not worth pursuing). I think this will
help by cleaning up duplicate trades in the books and creating a more integrated status structure."*

| status | where the leg trades | ladder | how it is recorded |
|---|---|---|---|
| **testing** | general paper: `bybit_1` (crypto) · `alpaca_paper` / `ib_paper` (equities, futures) | Stage 1 | on a general paper roster |
| **production** | real money + its paper-portfolio mirror (`bybit_2` + `bybit_portfolio` · `alpaca_live` + `alpaca_portfolio`), **not** general paper | Stage 2 | on a real-money roster (the mirror equality tests pin the mirror) |
| **inactive** | nowhere | retired | a retirement record: `enabled: false` in `config/strategies.yaml` with the reason; on no roster |

- **The status is DERIVED, never declared** (`scripts/ops/strategy_status.py`): inactive = retired by record; production = on a real-money
  roster; testing = otherwise. A `status:` field would be a third gate (CLAUDE.md § "The two execution gates") and a second copy of the
  roster, free to drift from it.
- **Promotion MOVES a leg.** Gate 2 (`MD-PROMOTE-S1-S2`, human-merge PR) adds it to real money **and** the mirror and removes it from its
  general paper account in the same PR (`mandate_resolver._delta` proposes all three edits). Production legs keep logging every trade on
  real money and the mirror, so general paper loses no record a production leg would have made — except where real money cannot size a
  trade the paper book would (measured below).
- **Demotion MOVES it back.** `MD-DEMOTE-S2-S1` removes it from real money + mirror and puts it back on its general paper account
  (unchanged: `_delta` already adds the soak account). **Demotion still stops at the floor:** a leg leaves the books only by a retirement
  record (`R-DEMO-FLOOR` stands for S1 -> OFF).
- **Inactive = several rounds of research say stop.** Retirement is a decision on a committed research record, never a demotion's side
  effect. **Inactive legs do NOT run in shadow** (operator, 2026-10-28, Q5 below): the retirement already
  concluded the question, the leg's inputs (candles, funding, news) keep being collected for the live legs on the same symbols, and any
  re-test regenerates the leg's signals offline from that data at zero runtime cost. A shadow leg would cost a tick slot, and would add
  journal rows with no decision attached. The off-trade-path rule (canonical § "Off the trade path is not off the data path") binds
  **features** taken off a trade path that is still being pursued. It does not bind a retired strategy. So the retirement record must
  name (a) the research it rests on and (b) the re-entry test that would revive the leg. A leg kept for its *data* is not inactive: it
  stays testing.
- **Enforced** by `strategy-status-guard` (`scripts/ci/check_strategy_status.py`, whole tree, roster-membership keyed — CI does not
  otherwise guard a roster REMOVAL): `R-DUAL-BOOK` (production leg also on general paper) · `R-NO-MIRROR` (production leg its mirror lacks,
  minus the declared affordability carve-out; or real money with no mirror account) · `R-INACTIVE-ROSTERED` (retired leg on any roster) ·
  `R-UNHOMED` (non-retired leg on neither book, unless named with its reason).
- **Measured effect** (`docs/research/strategy-status-model-2026-10-28.md`, journal `trades` table via the diag relay, 28 days to
  2026-10-28 21:00Z): 23 duplicate production-leg trades on general paper (22 on `bybit_1`, 1 on `alpaca_paper`). The move removes the
  22 (≈ 5.5/week); the `alpaca_paper` one stays by the Q2 exception. 2 of the 22 had no real-money sibling in their order package (the
  data the move loses).

**Decided — operator popup answers, 2026-10-28 ~22:35Z, relayed by the manager (verbatim option labels):**
1. **Prop legs** — *"Stay 'testing' on bybit_1 (Recommended)"*. Prop membership sets no status. A prop-only leg
   (`trend_donchian_eth_prop`) stays testing on `bybit_1`, its only paper read. A leg on prop and real money is production.
2. **`alpaca_live` affordability proxy** — *"Keep on alpaca_paper as exception (Recommended)"*. The mirror excludes `iaum_pullback_1d`
   by the proxy carve-out, so the leg keeps a paper record on `alpaca_paper` beside real money until it has a mirror. It is the one named
   exception (`DUAL_BOOK_EXCEPTIONS` in the guard, per account). The guard refuses the entry once it no longer applies.
3. **`ib_live`** — *"Yes, mirror when it gets a leg (Recommended)"*. An `ib_portfolio` mirror arrives in the same PR as `ib_live`'s
   first leg. The guard refuses an `ib_live` leg without one.
4. **Unhomed legs** — *"Retire gld, re-home 3 later (Recommended)"*, consistent with the same day's GLD decision *"GLD: kill and
   exclude"* (commit `75fa182dd`, #21009). `gld_pullback_1h` is retired by record (`enabled: false`; the record
   and its re-entry test are in its `config/strategies.yaml` comment). `spy_pullback_1h`, `qqq_pullback_1h` and `tlt_pullback_1h` go back
   on `alpaca_paper` once it takes slices for them (a 1d leg trades the same symbols there). Until then they are named in the guard's
   `UNHOMED` and owned by row `ALPACA-SLICES-REHOME-1H`, so none is silently unhomed.
5. **Inactive legs** — *"No shadow logging (Recommended)"*. Market-data collection continues under "Off the trade path is not off the
   data path".

### Stage 1 is the DEMO FLOOR: every non-retired leg trades there (operator, 2026-10-27, binding)

⚠️ **AMENDED 2026-10-28 by "Three strategy statuses" above:** the floor is the home of every TESTING leg. A PRODUCTION leg
trades on real money + the mirror INSTEAD of the floor, and returns to the floor on demotion. Everything else below stands.

**The rule.** The operator confirmed it in a popup in manager session `session_01C1ooo4kqBbng7vytdG1UVs`,
2026-10-27 ~07:10Z; the answer, verbatim, was *"Yes, that's the rule"*:

> Every strategy and ML-driven leg that isn't fully retired TRADES on the demo floor: bybit_1 for crypto,
> alpaca_paper / ib_paper for equities and futures. Shadow (logging only, no orders) is not used for
> non-retired legs. The mirror is the portfolio test; real money is promotion only.

The operator's own words, from chat: *"the lowest level of anything, of any strategy or ML, is trading on Bybit 1 ... so that
it can generate data about all of the things that we're running. The mirror account is where we do ...
the testing of the portfolio level ... Nothing should be just watching, and especially all of these
mechanisms that we're in the process of building need to be on Bybit 1 already, so that we can catch
mechanical bugs while we're still improving the actual function."*

**What follows from it:**
- **The floor is the default home.** A leg trades on its demo floor from the moment it exists until a retirement record removes it. A missing Stage-0 pass does not keep a leg off the floor. It keeps the leg off **real money and the mirror** (Gate 2), and nothing else.
- **`execution: shadow` is not a holding stage.** Shadow is no longer used for non-retired legs. A mechanism still being built (the desk leg, the short-hold lane, a new ML head) goes on the floor early, so mechanical bugs show up while the function is still improving.
- **Demotion stops at the floor** (and, since 2026-10-28, a demoted production leg is put back ON it). The operator's popup answer, 2026-10-27, verbatim, was *"Demote stops at the floor (Recommended)"*. A leg that fails Stage 0 or underperforms is demoted out of real money and the mirror and stays on its demo floor. `MD-S1-CUT-ON-STAGE0-FAIL` and `MD-DEMOTE-S1-OFF` are rewritten to match. **Only an explicit retirement record removes a leg from its floor.**
- **Real money is promotion only.** Gate 2 (`MD-PROMOTE-S1-S2`, human-merge PR) and the prop superset gate are unchanged.
- **Exceptions are named, never silent.** A leg no demo venue can serve (e.g. `xauusd_trend_1h`: OANDA practice is `dry_run` and OANDA US cannot trade XAU_USD) or one blocked by a guard (same-symbol allocation without slices on alpaca_paper) is listed with the reason on its checklist row until the blocker is fixed.

### The soak is MECHANICAL — 1–2 clean trades, no calendar (operator, 2026-10-15, binding)

<!-- SOAK-RULE-CANONICAL: the ONE statement of the soak rule. Every other doc points here
     (soak-doctrine-guard CHECK E refuses a live doc or skill that restates a long soak). -->

Verbatim: *"A soak is a mechanical verification that was already proven in backtesting, and nothing
needs to soak for more than one or two trades."*

- **What a soak asks:** do the mechanics work for this leg? Edge was settled offline at Stage 0.
- **PASS** = the first `n_needed` (1 or 2) CLEAN trades. Clean = the signal fires · the order is placed
  with the right size and side · a real SL and a real TP rest at the venue · management (trail/amend)
  does not fault · the exit is journaled with a TP / SL / strategy reason and a price · the fill and
  fees are recorded.
- **FAIL** = a mechanical fault (a reconciler / watchdog / orphan close, a naked or unstamped bracket, a
  sentinel TP, an unrecorded fill or fee). Fix it, then re-soak; the next clean trades pass it.
- **No sample size, no calendar.** A soak has no end date, no duration, no expected rate and no power
  calculation. A leg with no trade yet is `awaiting_first_trade` — waiting, not failing.
- **Realized cost and live-vs-backtest are ONGOING MONITORING** (R3, R5, `live_vs_backtest.py`) — the
  Gate-2 demotion signal and the underperformer first step. They are never soak exit criteria.
- **Shadow** legs prove what shadow can (a complete package, sized and recorded dry on every rostered
  account); a passed shadow soak is not a Stage-1 soak. **Live prop trades count** as soak trades.
- **Where it lives:** contracts `docs/claude/work/SOAKS.json` (a mechanical `checklist`, `n_needed` ≤ 2);
  state `scripts/ops/soak_state.py::soak_states()` (`passed` · `mechanical_fail` · `in_progress` ·
  `awaiting_first_trade` · `unknown`); guards `soak-contract-guard` (the contracts) and
  `soak-doctrine-guard` (the docs, skills and generators).
- **Open:** the granted `MD-PROMOTE-S1-S2` still reads a per-leg R3 `consistent` verdict (a cost sample).
  Its amendment is PROPOSED in `config/mandates.yaml` (`MD-PROMOTE-S1-S2-SOAK-AMEND`); granting it is the
  operator's.
- **Exception — a config-only improvement to an existing, already-live strategy (operator, 2026-10-18,
  binding).** Verbatim: *"in general, yes, things need to pass a mechanical test on paper, but if it's an
  improvement like this to an existing strategy, and it's just configuration that's already based on, like,
  the theory that's proven itself, then we should move forward with that and just monitor the first trades
  to make sure that they execute correctly."* So a change that is **configuration only** on a leg that is
  **already live**, backed by a **committed, pre-registered evidence record** (net of the full cost stack,
  clearing a rule registered before the run), goes live directly — no soak alias, no separate soak stage —
  and its **first 1–2 live trades are monitored** for correct execution. The monitoring is a named closing
  observation on the change's PR and checklist row (what executes, what it is compared against); a fault
  there is a mechanical fault like any other (fix it, or revert the config). **New strategies and new code
  paths still soak** as above; so does anything that needs code to run. This relaxes the *placement* of the
  mechanical check (live, watched), not the evidence bar, and it does not touch the prop superset below.
- **The Claude desk (`claude_desk`): one passed paper/demo soak covers later packet, brief and symbol changes
  (operator, chat 2026-10-27 ~16:00Z, binding).** Verbatim: *"once the demo soak is placed now, that on the paper
  accounts, that's good enough. That's the same as passing a soak once there's an edge, because the mechanics are
  the same. ... the format of the packets or the information or the symbols, like all those things don't matter. So
  once the paper soak passes, that part is ready."* So after `claude_desk` passes its soak on the paper/demo
  accounts, a later change to the scan packet (its format or the information in it), to the desk brief, or to the
  symbols it covers does not need a new soak: the order path those trades take is the same. It does not relax Stage 0:
  every such change still reaches a real-money book only on its own committed, pre-registered evidence record
  (`docs/research/desk-edge-program-2026-10-27.md`). Other docs point here and do not restate it.

**Stage 2 is one stage, not two.** The mirror and the live account carry the
same strategies and take the same trades at all times (operator, 2026-09-21).
The mirror is the honest-size read of the live book, not a separate rung.

**Consequence: R4 becomes a DEMOTION gate, not a promotion gate.** A mirror
that carries identical strategies only ever holds data for legs already live,
so it cannot gate entry. It gates exit. This is the falsifier the system has
never had — nothing currently demotes anything, and 21 retirement candidates
have produced zero retirements.

### Prop legs clear a SUPERSET of the ladder (operator, 2026-10-15, binding)

A leg that reaches a **prop** roster (`account_class: prop`: breakout_2 · tradeify_1 · velotrade_1)
must clear **everything a real-money leg must clear, PLUS prop DD survival**: Stage 0 net of the full
cost stack · a PASSED mechanical Stage-1 soak (on `bybit_1` / `alpaca_paper`, or from the leg's live prop
trades — amendment below) · the Gate-2 criteria · **and** the prop EV/survival gate against the firm's DD limits
(`comms/prop_survival/<leg>.json`). Verbatim principle: *"if anything, the prop accounts should have a
higher bar to clear because of the DD limits."* The prop gate is a **superset**, never a lower bar (this
formalises the 2026-08-27 correction). Mechanical half: `prop-roster-gate-guard`
(`scripts/ci/check_prop_roster_gate.py`) refuses a PR that adds a leg to a prop roster without a Stage-1
soak (roster presence or a `SOAK-stage1-*` contract) and a survival record; `roster-promotion-evidence-guard`
keeps demanding the Stage-0 record. **Grandfathered by name, with an exemption lapse date:**
`trend_donchian_eth_prop` (2026-11-07) and `trend_donchian_sol_prop` (2026-12-11) — both went live on
prop before this rule, soak on `bybit_1` and from their live prop trades (contracts in
`docs/claude/work/SOAKS.json`) while they **stay live on the prop books**; if either FAILS the soak
mechanically, the fault is fixed and the leg re-soaked, and a data-backed Tier-3 pull from the prop rosters
is proposed only if it cannot be. (The lapse dates were the end dates of the retired accrual contracts; the
mechanical soak has none.) Row: `PROP-GATE-PARITY`.

**Amendment (operator, 2026-10-15): live prop trading counts as Stage-1 soak evidence.** *"If they've passed
a soak test trading live on the prop accounts, that should count as a pass and they can go live on bybit 2 as
well."* Under the mechanical soak (above) this is checkable per leg on its first 1–2 DISTINCT prop signals
(one per order package, however many prop accounts it filled on): a signal is clean when at least one
account's fill clears the prop checklist — order with side and size, a venue-read SL and TP, management,
an exit journaled with an sl/tp/strategy reason and a price (`soak_state.grade_prop_signal`; the prop journal
has no fee column, so the fee item is proven on the Bybit path). An operator's manual close is neither clean
nor a fault. **Live-vs-backtest (`scripts/research/live_vs_backtest.py`, PR #18382) and realized cost are
ongoing monitoring, not soak clauses** — a promotion to bybit_2 still checks cost against **Bybit's own
MEASURED cost for that symbol**, and today the granted `MD-PROMOTE-S1-S2` still asks for a PER-LEG R3
`consistent` verdict (see the proposed amendment above). A PASS feeds `MD-PROMOTE-S1-S2`:
a PR adding the leg to bybit_2 **and** bybit_portfolio together (mirror equality tests, human merge, not auto-land),
and the evidence record must first carry a **portfolio-overlap check** (e.g. `trend_donchian_eth_prop` 1h beside
`trend_donchian_eth_4h`: signal/return correlation and combined drawdown). The bybit_1 soak stays as a parallel
source; contracts carry both (`sources` in `SOAKS.json`). This PR promotes nothing.

### Two structural facts about the roster

- **The Bybit mirror invariant exists and is enforced** —
  `tests/test_paper_portfolio_accounts.py::test_bybit_portfolio_mirrors_bybit_2_exactly`
  pins the rosters together. `bybit_2`: 6 strategies, `bybit_portfolio`: 6.
- **The Alpaca mirror is a SUBSET invariant, not an equality one.**
  ⚠️ **RESOLVED BY B2, 2026-09-21** — the operator chose strict equality and the
  invariant now reads
  `test_alpaca_portfolio_mirrors_alpaca_live_exactly_minus_proxies`. The
  diagnosis below stands as the record of why; the leg counts in it predate
  **A6** (#12673), which cut `alpaca_live` from 5 legs to 3 the same day, so the
  mirror surplus is **12**, not 9.
  ⚠️ **CORRECTED 2026-09-21, same day.** This row first read *"No invariant
  exists"* — **that is false, and I inferred it instead of grepping `tests/`,
  which is a RULE ONE failure in the exact shape RULE ONE names.**
  `tests/test_paper_portfolio_accounts.py::test_alpaca_portfolio_mirrors_alpaca_live_minus_proxies`
  exists and asserts `set(live legs − affordability proxies) ⊆ set(portfolio
  legs)`, in **every** state including the empty one.

  What is true is narrower and is still the problem: it guarantees the
  direction that **protects real money** — no live leg trades without a paper
  counterpart accruing beside it — and it **deliberately does not** assert the
  converse. The test says so in terms, with the reasoning: asserting equality
  during a staged go-live *"would force `alpaca_portfolio` down from 14 legs to
  1, destroying the paper research book that the eventual roster selection
  depends on."*

  Measured 2026-09-21: `alpaca_live` 5 legs, `alpaca_portfolio` 14. So the
  mirror is **not** a like-for-like honest-size read of the live book the way
  `bybit_portfolio` is, and **Gate 2's demotion signal cannot be read off its
  aggregate** — nine of its fourteen legs are not on the live book at all.

  → **B2, and B2's scope changes with this.** It is not "add an invariant."
  It is: decide what the Alpaca mirror is FOR, then make the invariant say
  that. The test's own argument against blind equality is good and must be
  answered, not overwritten.

---

## 3. The research loop

The fix for "propose only" is to **decide before you measure**. Every queued
question carries its decision rule up front, so the result **is** the decision
and the interpretation step — where everything currently dies — is removed.

```yaml
# research/queue/<id>.yaml — extends the schema that already exists
hypothesis:     one falsifiable sentence
population:     what data, minimum n, how power was computed
instrument:     which harness — and whether it runs the LIVE order path
decision_rule:  IF <result> THEN advance to stage N
                IF <result> THEN kill
cost:           runner-hours
tier:           approval the resulting change needs
```

The dispatcher already exists and fires daily at 06:20 UTC. It has had
**nothing due since 2026-08-31** — the queue holds five units, three on monthly
cadences. The machine is running against an empty input.

**What happens to a result**

- **Advance, Tier-1 or 2** → applies itself. No human in the path.
- **Advance, Tier-3** → arrives at the next daily sync as one line: the rule
  already agreed, and the number that met it.
- **Kill** → closes the question and lands in the ledger. A null is an asset,
  not a memo.

⚠️ **The default is refinement, not a one-strike kill** (operator, 2026-09-27):
*"our default is never to just kill ideas because of one bad pass, we should
always strive for refinement/testing/more research. Only kill things when
we're certain they are no longer worth our time."*

**Shadowing is part of the loop, not a parking lot.** The soak book
(`bybit_1`, `alpaca_paper`) is where legs that have not passed make decisions
on real-time data so we can see the outcomes and learn how to tweak them.
Reviewing those legs is a standing research input (operator, 2026-09-21).

### The queue replaces the roadmap

`ROADMAP.md` is 668 KB, reads 191 ✅ to 24 📋, was last updated 23 days ago and
carries its own header: *"nobody has verified this document's status — do not
act on it as current."* Milestones measure construction. A question queue
measures learning, which is the thing that is not happening.

### Three mechanical faults stop results landing

1. **19 of 23 research workflows produce an artifact and an issue comment and
   nothing else** — no durable record anyone can query later. → **C2**
2. **`replay-pregate-nightly` has never landed a report on `main`, ever** —
   `runtime_logs/**` is not in `TIER1_SURFACE`, so `pr-landing-guard` R5
   rejects the commit. Separately the trainer is swap-thrashing, so 6 of 6
   nightly runs die at 10 of 22 heads and **no non-BTC head has ever been
   graded**. → **C3**
3. **9 of 13 backtest harnesses are wired to no workflow**, and the default
   candle file is a 5,001-row smoke fixture spanning 3.5 days. → **C4**

---

## 3b. The follow-through pipeline — why things get dropped

> Added 2026-09-21 on operator direction: *"there's too many things here that
> get just dropped halfway through, and that was definitely one of the problems
> we were trying to solve and that still doesn't seem to have been resolved…
> not just more CI guards or whatever, not just building up the CLAUDE.md —
> actually creating infra that has a pipeline that pulls things through to the
> finish."*

⚠️ **This is an honest gap in what § 1 and § 4 propose.** Archiving the
registers removes the place where work rotted; it does not build the thing that
pulls work through. **Until this section is built, follow-through is WORSE than
before the reset, not better** — the rows are in git history and nothing reads
them at all.

**What was archived, measured 2026-09-21:**

| register | rows | unresolved |
|---|---|---|
| `health-review-backlog.json` | 1,663 | 756 `open` + 195 `kept_open` |
| `performance-review-backlog.json` | 146 | 42 + 29 |
| `ml-review-backlog.json` | 111 | 7 + 20 |
| `research-review-backlog.json` | 22 | 16 + 0 |
| `OPEN-ITEMS.json` | **91** | all 91 — every one carries a `clears_when`, 76 marked `loud` |

**1,065 unresolved backlog rows and 91 live monitoring rows.** The health
backlog's own completion rate is **683 resolved against 951 still open** — 42%,
accumulated over months.

### Five reasons the old system dropped things

Stated so the replacement can be checked against them rather than hoped at.

1. **Filing was free; picking up was voluntary.** A row entered a backlog and
   nothing was obligated to read it.
2. **Most rows carried no due condition.** `OPEN-ITEMS.json` was the exception
   and got this RIGHT — 91 of 91 carry `clears_when`. That part is worth
   keeping.
3. **No link back to the generator.** A row from an audit could not re-run that
   audit to ask whether it still applied.
4. **No forced terminal state.** A row could sit at `open` indefinitely. Nothing
   made it either complete or die.
5. **The surface nobody read.** `DUE.md` was rendered, read by the `duty`
   skill, which a session had to *choose* to run. **A reminder is not a
   mechanism.** The operator never saw it.

### The replacement — one intake, a due condition, and an automatic pull

```jsonc
// docs/claude/work/PIPELINE.jsonl — APPEND-ONLY. A JSONL file, not a JSON
// array, because a shared array is what produced the register merge conflicts.
{
  "id": "PI-20260921-0001",
  "what": "one line",
  "origin": {                      // (3): it knows where it came from
    "kind": "audit|review|session|deploy|research|operator",
    "ref":  "the audit/PR/session that produced it",
    "rerun": "the command or workflow that REGENERATES this finding"
  },
  "due_when": {                    // (2): it knows when it needs attention
    "kind": "observation|date|event",
    "clears_when": "what would have to be TRUE — carried over from OPEN-ITEMS",
    "check_every_days": 7
  },
  "next_action": "dispatch_lane|check_observation|apply_mandate|ask_operator",
  "state": "queued|due|routed|done|killed",
  "routed_to": "checklist row id, lane id, or mandate id",
  "terminal_reason": null          // (4): required to leave the pipeline
}
```

**The pull is the part that matters, and it is not a guard.** A scheduled job
renders every `due` item into the daily brief as **section 0 — what came due**.
The manager must give each one a disposition the same day: dispatched to a lane,
applied under a mandate, killed with a reason, or escalated to the operator.

⚠️ **The forcing function is the OPERATOR'S OWN PAGE.** An unrouted due item
appears in the brief every day until it is routed, and the **count of unrouted
items is reported as a number in section 5.** That is the single structural
difference from `DUE.md`: the old due-list was read by machinery that was read
by nobody, so a backing-up queue was invisible to the one person who could
reprioritize it. A rising count on a page the operator opens daily cannot rot
quietly.

**Terminal states are forced, and `killed` is a first-class outcome.** An item
leaves the pipeline by being done or by being killed *with a stated reason*. It
may not simply stop being mentioned. Most of the 1,065 archived rows should be
killed, explicitly — a row nobody worked for months is dead, and recording that
is worth more than carrying it.

### Where the checklist, the queue and the pipeline meet

Three files, one flow — and the **transitions** are what the brief reports.

```
  generator (audit / review / deploy / session / operator)
        │
        ▼
  PIPELINE.jsonl          everything that will ever need a follow-up.
        │                 Carries origin + due condition. May be large.
        │  comes due  ──▶  section 0 of the brief  ──▶  MUST be routed
        ▼
   ┌────┴─────────────────┬──────────────────┬──────────────┐
   ▼                      ▼                  ▼              ▼
 MANAGER-CHECKLIST    research/queue/    a mandate fires   killed
 (a build, in flight) (a question)       (no human)        (with a reason)
```

**This does not reintroduce the eight registers, and the test of that is
specific:** in the old model an item could sit in a register forever without
anyone noticing — 951 rows prove it could. Here, coming due puts an item on the
operator's page and it stays there until it is routed. **If that property is
ever removed, this is the eight registers again.**

---

## 4. The manager, restructured

Keep it. The model was not wrong; the job description was.

**What the manager does**

1. Reads the queue and picks what runs next, against the cycle priority the
   operator set at the last sync.
2. Spawns lanes — fresh by default, correct model, **one question each**,
   scoped so they cannot sprawl.
3. Reads what comes back and applies the pre-registered outcome.
4. Kills or re-scopes a lane that is burning without producing.
5. Prepares the daily brief, and **pushes it before the sync**.

**What the manager may not do**

- Take an item. Unchanged, and already CI-enforced by
  `scripts/ci/check_manager_scope.py`.
- Maintain more than one register. **The checklist is the only one that
  survives.** The lease, work store, session registry, merge queue,
  coordination board, due-list and constraint readout are retired.
- Write narrative observations about its own state. Three timestamped
  `manager_observation_*` keys an hour apart on one row is the failure mode,
  not diligence.
- Exceed the sustainable rate (amended 2026-10-18, § "The budget decision") without saying so.

### Why one register and not eight

Measured over 30 days: 1,005 commits to `docs/claude/work/`, 697 to one backlog
file, 254 to `OPEN-ITEMS.json` — against 141 to the entire `src/` tree. Roughly
one register write per merged PR, across 2,010 merged PRs.

The build plan for that operating model warned, in writing, that *"August ran
45 governance sprints against 2 deployments"* and that a plan whose value
arrives in phase four would reproduce that ratio. It shipped 1 of its 8 phases
and reproduced it.

---

## 5. The daily sync, and standing authorizations

Once a day, same time. The manager pushes the brief **before** the sync, so the
Workflow page and the conversation never disagree.

> ⚠️ **CORRECTED TWICE ON 2026-09-21, both times by the operator.** The first
> draft capped the sync at 30 minutes and the operator at **three decisions**.
> The second draft made 30 minutes a floor instead. **Both are wrong and the
> time framing is now gone entirely** — see 5.1. The superseded text is kept at
> the end of this section, because a session reading a quietly-rewritten
> section cannot tell which version the machinery was built against.

### 5.1 The sync is not measured in time

Operator, 2026-09-21: *"The daily session shouldn't be measured in time. It
takes however long it takes to go through the work I need to do — I don't want
us tracking an arbitrary time limit to measure performance."*

**There is no target duration, no floor and no ceiling.** The sync runs until
the work in it is done. A clock is a proxy, and a proxy that gets tracked
becomes a thing to optimise: a manager measured on session length has a reason
to compress a real decision or pad a thin one, and neither serves anything.

What the manager owes is **the work being ready** — every item prepared to the
point where the operator can act on it without going and finding something.
Whether that takes eight minutes or ninety is an output of the work, not a
target.

### 5.2 The cap is removed, and standing authorizations replace it

Operator, 2026-09-21: *"We need to think of a better way to give more
decision-making power, more things automated — not create less decisions and
limit how much work we can actually do… how can I give blanket permissions up
front that allow for more decisions to be automated so that we can keep things
running."*

**The cap treated the operator's attention as the scarce resource and rationed
it. The actual scarce resource is throughput, and rationing decisions throttles
it.** The fix is not a bigger cap. It is to stop most decisions from needing a
person at all.

A **mandate** is an operator decision granted ONCE, in advance, that lets the
system act inside stated bounds without asking again. It is the pre-registered
`decision_rule` of § 3, lifted from the single question to the CLASS of
question. It is declared the way the execution gates are — visible in YAML,
bounded, revocable — and lives in `config/mandates.yaml`.

⚠️ **A mandate is NOT a third execution gate.** § "The two execution gates"
says in terms that there is no third gate, and that is untouched:
`accounts.yaml::mode` and `strategies.yaml::execution` remain the only two
things deciding whether a strategy trades, and neither is default-off. A
mandate sits on a **different axis** — it does not decide what RUNS, it decides
what may be **CHANGED without asking**.

Four properties stop one rotting into a forgotten blanket yes: **bounded**,
**evidence-conditional** (it fires on a stated rule, never on judgement),
**expiring**, and **attributed** (every action records which mandate authorized
it).

### 5.3 THE LADDER IS FULLY AUTOMATED — granted 2026-09-21

Operator, 2026-09-21, verbatim: *"All the ladder decisions can be automated —
that is a standing mandate. Strategies can be promoted to live money without
explicit operator approval if the evidence supports the decision. I should just
get a ping in realtime of the update and an evidence review in the next daily
briefing."*

**This is the strongest grant in the plan and it is recorded here as made.**
Every transition on the ladder — both gates, both directions — fires on
evidence without a human in the path.

| mandate | grants | direction |
|---|---|---|
| `MD-PROMOTE-S0-S1` | add a leg to the soak book (`bybit_1`, `alpaca_paper`) on a passing Stage-0 record — **since 2026-10-16 (operator, "Require holdout") the record must also carry a passing `holdout_confirmation`: the selected configuration tested once on a held-back latest span; `config/mandates.yaml` is the source** | `add_risk` (paper) |
| `MD-PROMOTE-S1-S2` | **add a leg to a REAL-MONEY roster** on a passing Stage-0 record plus Stage-1 cost fidelity — **plus the same holdout confirmation since 2026-10-16** | `add_risk` (real) |
| `MD-DEMOTE-S2-S1` | demote a Stage-2 leg when the mirror goes net-negative net-of-cost over the declared window — **since 2026-09-29 (operator, "Last 20 + strict test (Recommended)") the T3 ∧ net<0 rule: both of the last two 20-trade windows below the leg's Stage-0 p10 and below 0; `config/mandates.yaml` is the source** | `derisk_only` |
| `MD-DEMOTE-S1-OFF` | drop a Stage-1 leg whose realized cost diverges from its harness assumption | `derisk_only` |
| `MD-KILL-QUESTION` | close a research question that failed its own pre-registered rule | `derisk_only` |

**Reporting, as the grant specifies it** — a promotion to real money is not
silent:

1. **A realtime ping** when it fires, naming the leg, the direction, the
   mandate, and the number that met the rule.
2. **An evidence review in the next brief**, in section 1 — the record it fired
   on, shown so the operator can check the machine's reasoning after the fact
   rather than before it.

⚠️ **WHAT NOW CARRIES ALL THE WEIGHT IS THE PHRASE "IF THE EVIDENCE SUPPORTS
THE DECISION".** With no human in the path, the bar's *content* is the entire
safety property. It must be: a **committed evidence record**, produced by a
named harness, at a stated n, **net of the full cost stack**, clearing a rule
registered BEFORE the run. A claim in a PR body is not a record. **B1 is what
makes this checkable** — until the guard that requires an evidence record
exists, "the evidence supports it" cannot be enforced, only asserted.

⚠️ **AND THE PROMOTION MANDATE MUST NOT ARM UNTIL D1 LANDS. THIS IS NOT
CAUTION, IT IS ARITHMETIC.** The harnesses default slippage and funding to
`0.0`, so **every "passed the backtest" verdict in the corpus today is fee-only
and optimistic by an unknown amount** — measured once at **+0.57R** on the one
leg anyone checked. Arming auto-promotion against that corpus would
automatically route real money on numbers we already know are wrong in the
favourable direction. The grant stands; its arming is blocked on the instrument
being trustworthy. The `derisk_only` mandates carry no such block — they act on
live measurement, not on the backtest corpus, and their worst case removes
exposure.

### The bar and the cap — DECIDED 2026-09-21

**THE BAR.** A leg is auto-promoted to a real-money roster only on a **committed
evidence record** — named harness, stated population, rule registered before the
run — showing **all three**:

1. **Expectancy > 0 net of the FULL cost stack** at **n ≥ 30 closed**.
2. **Positive in a majority of walk-forward folds.**
3. **Stage-1 realized cost within a stated tolerance of the modelled cost.**

⚠️ **Clause 3 is a PROMOTION clause, not a soak exit** (§ 2 "The soak is
MECHANICAL"): a soak passes on 1–2 clean trades and never waits for a cost
sample. How clause 3 is measured — per leg (R3's fill floor, as granted) or
against the venue's measured cost for the symbol — is the proposed amendment
`MD-PROMOTE-S1-S2-SOAK-AMEND` in `config/mandates.yaml`, the operator's to grant.

**THE CAP.** Total declared risk across **auto-promoted** legs may not exceed
<!-- population-ok: a configured ceiling or threshold the operator chose, not a measurement -->
**25% of the account's configured risk budget**. That is the only ceiling:
**there is no rate limit** (operator decision — a leg-per-week cap was offered
and declined).

⚠️ **State the consequence plainly, because it was chosen knowingly:** if R1
promotes a batch, **several legs can arrive on the same day**, bounded only by
the 25% share. That is the intended behaviour — the bar is the gate, and a rate
limit would throttle a correct decision for no reason other than nerves. What
<!-- population-ok: a configured ceiling the operator chose, not a measurement -->
it means operationally is that **the 25% share is load-bearing on its own**,
with nothing behind it.
<!-- population-ok: a configured ceiling chosen by the operator, not a measurement -->

⚠️ **The cap counts AUTO-PROMOTED legs only.** A leg the operator put on a
roster by hand does not consume the mandate's budget — otherwise a manual
decision would silently shrink the automation's headroom, and the two would
become impossible to reason about separately.

### 5.4 What the brief contains

Five sections, fixed order. Section 1 is a **report**, not a request.

| # | Section | Contents |
|---|---|---|
| 0 | **What came due** | From the follow-through pipeline (§ 3b). Each must be routed. |
| 1 | **Taken under mandate** | What fired on its own, which mandate authorized it, and the evidence record it fired on. **No approval sought.** |
| 2 | **Decisions for you** | Only what no mandate covers. **No cap.** |
| 3 | **What moved** | Lanes completed, what they concluded, what was killed. |
| 4 | **What is running** | Live lanes, spend so far, expected completion, anything blocked and on what. |
| 5 | **Spend** | Yesterday, month-to-date, against budget, cost per unit delivered, and the unrouted-item count. |

**A decision that reaches the operator twice in the same shape is an agenda
item**: *should this become a mandate, and at what bounds?* That is how
section 2 shrinks and section 1 grows without anyone rationing anything.

**The metric that matters is the share of decisions taken under mandate, and it
should rise.** Flat month over month means the loop is not learning.

**Monthly, one question:** how many legs advanced a stage, how many were
killed, and what did we learn? If that is zero two months running, the answer
is not more process.

<details>
<summary>The two superseded versions, kept as the record of what was proposed</summary>

> **v1, rejected same day.** Four sections, hard cap of 3 decisions. *"If it
> does not fit in 30 minutes, the manager has failed to prepare… a fourth
> decision means the queue is producing faster than the operator can
> adjudicate."*
>
> **v2, rejected same day.** *"Thirty minutes is a FLOOR, not a ceiling. A
> short sync is the failure signal."*

v1 rationed the operator's attention, which throttles throughput. v2 fixed the
direction and kept the clock. The operator rejected the clock itself: *"I don't
want us tracking an arbitrary time limit to measure performance."*

</details>

---

## 6. Cost and model discipline

There is no cost ledger today. 263 session rows across ~90 keys carry **zero**
cost or token fields. The load-bearing measurement, from CLAUDE.md's own record
(2026-09-17, one resumed lane, ~10 minutes): `cache_read` 78,988,432 →
95,867,825 (+16.9M), `cost_usd` 53.38 → 65.26 (**+$11.88**) — almost entirely a
resumed session re-reading its own accumulated context every turn. A fresh
session starts near 40k.

### Model by task class

| Task | Model | Why |
|---|---|---|
| Manager | `opus` | Must hold the whole picture and judge what to spawn. |
| Research lane | `sonnet` | Well-specified question, mechanical execution, result checked against a rule it did not write. A weak model cannot fake a pass. |
| Build lane | `sonnet` | `opus` if it touches an order path. |
| Sweep dispatch, log reads, extraction | `haiku` | No judgement involved. |
| Anything on a real-money order path | `opus` | Recoverability is the criterion, not difficulty. |

`create_session`'s `model` parameter **defaults to the calling session's
model** — omit it and a lane silently inherits the manager's `opus`.

### Session hygiene

- **fresh by default** — resume only when the next unit needs context the
  previous session built *in its head*, never context that is on disk. Subject
  overlap is not benefit.
- **one question** — a lane that must answer two questions is two lanes. This
  is the context-overload control.
- **ceiling** — a per-lane dollar ceiling. On breach the manager *reads what
  the lane has produced*, then kills or re-scopes. Never interrupt blind: an
  interrupt forfeits everything not yet landed.
- **record the choice** — model and fresh/resume, with the reason, on the
  lane's checklist row.

**The meter's job is not accounting, it is scoping.** A number the manager must
report daily forces it to ask what a lane is worth before spawning it.

---

## 7. The work plan

Every item names the session that runs it and carries a row in
`MANAGER-CHECKLIST.json` with the same id. Phases A and B are almost entirely
deletion and rewiring; nothing new gets built until C.

### PHASE A — make the daily loop possible (week 1)

| id | item | who |
|---|---|---|
| **A1** | **Cost meter.** Capture cost and tokens per session into one register; render in the brief. Per-lane ceiling + a daily total. | build lane |
| **A2** | **Cut `CLAUDE.md` to ~15K tokens.** Was 547 KB ≈ 136K tokens, of which the generated SESSION BRIEF was 39.4% — 215 KB of overdue monitoring rows injected before every session's first tool call. Keep: orientation, the two execution gates, the tier table, the ladder, pointers. Everything else → `docs/reference/`, read on demand. | this session |
| **A3** | **Daily brief generator.** The four fixed sections, rendered from the queue + lane state + cost meter. Pushed before the sync, served on the existing Workflow page. | build lane |
| **A4** | **Manager contract.** One page: what it does, what it may not do, spawn rules, the model table, the budget. Replaces ~6,200 lines of process skills. | this session |
| **A5** | **Stand down the governance layer.** Disable the governance crons; archive the registers (951 open backlog rows); retire the lease, work store, session registry, merge queue, coordination board, and the `duty` / `backlog-drain` / `full-system-audit` skills. | this session + build lane |
| **A6** | **Pull the two negative-OOS Alpaca legs.** `tlt_pullback_1h` (−4.41R, n=94) and `tlt_pullback_1d` (−3.92R, n=8, 0 of 4 folds positive) off `alpaca_live`. One-line config change, reversible, does not wait on D1. **Tier-3 — needs explicit operator approval.** | operator |
| **A7** | **The follow-through pipeline** (§ 3b). `PIPELINE.jsonl` + the renderer that puts due items into the brief as section 0 + the required-disposition rule. **This is the unsolved problem the reset has so far only relocated** — until it lands, follow-through is worse than before, because the registers are archived and nothing reads them. Pairs with A3. | build lane |
| **A8** | **Rescue the 91 monitoring rows; triage the 1,065 backlog rows.** The 91 all carry a `clears_when` and are the live deployed-but-unproven state — import them. The 1,065 are NOT bulk-imported: each is promoted with a due condition or **killed with a reason**, one bounded pass. A row nobody worked for months is dead, and saying so beats carrying it. | build lane |

### PHASE B — make the ladder mechanical (week 1–2)

| id | item | who |
|---|---|---|
| **B1** | **Invert the execution-gate guard.** Demotion becomes free. A new guard blocks any leg reaching a Stage-2 roster without a fresh evidence record that clears its declared bar. **This is the load-bearing change.** | operator + build lane |
| **B2** | **Decide what the Alpaca mirror is FOR, then make its invariant say that.** ⚠️ Re-scoped 2026-09-21: the first draft said *"extend the Bybit roster-sync test"* on the false premise that no invariant existed. One does — a deliberate SUBSET assertion (`test_alpaca_portfolio_mirrors_alpaca_live_minus_proxies`) that protects real money and does not make the mirror representative. Live 5 legs vs mirror 14, so Gate 2's demotion signal cannot be read off the mirror's aggregate. The test argues against blind equality during a staged go-live and that argument must be answered, not overwritten. | operator + build lane |
| **B3** | **R4 as the demotion gate.** Flip to enforcing, pointed at demotion rather than promotion. Recommended 2026-07-30, built, shipped observe-only, never armed. | operator + build lane |
| **B4** | **Re-scope the review packet.** Grade Stage 2 on money and Stage 1 on mechanics (§ 2 "The soak is MECHANICAL"; cost fidelity is monitoring). Without this it keeps grading 52 legs against a 20-trade floor and emitting nothing, forever. | build lane |
| **B5** | **The mandate mechanism** (`config/mandates.yaml` + a resolver + a guard). A standing authorization the operator grants ONCE that lets the system act inside stated bounds without asking again. `direction: derisk_only` mandates carry no rate ceiling because their worst case is trading less than we could; `add_risk` mandates carry a hard cap on total risk added, a per-leg size bound and a count. Every action records which mandate authorized it. **Pairs with B1** — the guard that requires evidence before a Stage-2 roster is the same guard that reads what is already authorized. | operator + build lane |

### PHASE C — unblock the research loop (week 2)

| id | item | who |
|---|---|---|
| **C1** | `decision_rule` in the queue schema, plus a guard that refuses a queued unit without one. | build lane |
| **C2** | Make the 19 artifact-only workflows commit to a corpus. A result nobody can query later is not evidence. | build lane |
| **C3** | Let `replay-pregate` land: add `runtime_logs/**` to `TIER1_SURFACE`; cut the head count to fit trainer memory or raise the memory. | build lane |
| **C4** | Wire the 9 orphan harnesses; replace the smoke fixture with a real corpus. | build lane |
| **C5** | **Write the first ten pre-registered questions.** The only item that builds nothing — and the only one that produces knowledge. | operator + manager |

### PHASE E — the research programme and its infra (runs alongside B/C)

Full statements: [`RESEARCH-PLAN-2026-09-21.md`](RESEARCH-PLAN-2026-09-21.md) ·
[`ENGINEERING-PLAN-2026-09-21.md`](ENGINEERING-PLAN-2026-09-21.md).

| id | item | who |
|---|---|---|
| **E3** | **Make the cost model reach every harness.** The highest-value engineering item in the repo: R1 depends on it, and R1 gates the arming of `MD-PROMOTE-S1-S2`. | build lane |
| **E4** | A real corpus; `--data` mandatory; a row-count floor. The 3.5-day fixture stays as a smoke path but stops being reachable by default. | build lane |
| **E5** | Every research workflow lands a durable, queryable result. **This is what makes the promotion mandate possible at all** — without it there is no evidence record to read. | build lane |
| **E6** | Unblock `replay-pregate`: the `TIER1_SURFACE` entry *and* the trainer memory. Fixing only the first grades a third of the fleet and looks green. | build lane |
| **E7** | Wire the 9 orphan harnesses. | build lane |
| **E8** | The testing queue. **Last on purpose** — a queue running against a fee-only corpus manufactures wrong answers faster. | build lane |
| **E9** | Retire the 67 orphaned guard scripts. Low priority; the reference sweep is the job. | build lane |
| **R1** | **Re-run the corpus with costs on.** Nothing real depends on anything else until this is done. | research lane |
| **R2** | Cut the fleet to what passes — an observation that `MD-DEMOTE-S1-OFF` fired correctly, not a separate decision. | manager |
| **R3** | Cost fidelity as a standing MONITOR of every Stage-1/2 book (feeds the demotion mandates). It is not a soak exit — § 2 "The soak is MECHANICAL". | build lane |
| **R4** | The first ten pre-registered questions. | operator + manager |
| **R5** | **Read the soak book on a cadence.** Operator-named, never built. | build lane |
| **R6** | Decide whether to trade at all right now. An empty live roster is an acceptable outcome. | operator |

### PHASE D — repair the evidence base (deferred, operator's call on timing)

| id | item | who |
|---|---|---|
| **D1** | **Flip the cost defaults on, and re-run.** `src/runtime/execution_costs.py` models fee + slippage + funding correctly; the harnesses set slippage and funding to `0.0` by default, deliberately, for backward compatibility. So every "passed the backtest" verdict in the corpus is fee-only and optimistic by an unknown amount — measured once at +0.57R on the one leg anyone checked. 6 of 13 harnesses have no cost terms at all, including the `vwap` harness. | research lane |
| **D2** | **Cut Stage 2 to what actually passes.** Depends on D1 — until the re-run we do not know which legs clear Stage 0. Today 3 of 44 meet the `live_money_ready` bar and none is on `bybit_2`. | operator + build lane |
| **D3** | **Cost-fidelity job.** Weekly: compare each Stage-1 leg's realized cost against its harness assumption — ongoing monitoring, not a soak exit (§ 2). Build only once D1 has given it something to compare to. | build lane |

> **What deferring Phase D costs, stated rather than buried:** until D2, real
> money keeps running legs that fail their current evidence bar. **A6 pulls the
> two worst without waiting for the re-run.**

---

## 7b. The work schedule — what happens when, on the Pages UI

> Operator-requested 2026-09-21: *"A work schedule, visible on the gitpages UI
> site — when different sessions need to happen, when decisions are due,
> monitoring items, etc."*
> Built as **A9**. Two halves in two repos.

**It renders what already exists. It is not a new register**, and that
constraint is the whole design — a schedule maintained by hand is the ninth
register wearing a calendar.

| row kind | where it comes from |
|---|---|
| **Cadenced sessions** | the daily sync; `/health-review`, `/performance-review`, `/ml-review` on their own cadences — **weekly reviews run first after the weekly reset, planning follows** (below) |
| **Decisions due** | pipeline rows whose `next_action` is `ask_operator` (§ 3b) |
| **Monitoring due** | pipeline `due_when.check_every_days` coming up |
| **Automated jobs** | cron cadences **read from the workflow files**, never retyped |
| **Lanes running** | the checklist's `in_flight` rows with their spend |

⚠️ **Weekly order: reviews right after the reset, planning Thursday morning** (operator, 2026-10-19, binding). Verbatim in substance: *"right after the reset, we kick off all of the weekly reviews — performance, ML, the audit, a regular system review — make sure especially the research and training pipelines are healthy, and then we go on to the planning session on Thursday morning based on those insights and knowing how much capacity we actually have left for the week."* The reset is Wed ~18:00Z; planning (Thursday morning) is built on the review outputs plus a post-review capacity reading (`spend_meter.py --capacity`). Contract and the trigger re-timing: [`.claude/skills/manager/SKILL.md`](../../.claude/skills/manager/SKILL.md) § "Weekly planning … and the weekly cycle".

⚠️ **The cron column is derived, not declared.** A schedule that states a
cadence a second time is free to drift from the workflow that actually carries
it, and this repo has already measured that exact failure: `work-digest`
declared `20 * * * *` and fired five times in a day, at :19, :10, :33 and :47.
**So the page shows the declared cadence beside the LAST OBSERVED FIRING**, and
where those disagree it says so rather than picking one.

⚠️ **If the schedule needs a fact nobody records, that is a finding about the
pipeline — not a reason to start typing it into a new file.**

**The two halves are in different repos and the second is the one that makes it
visible:** a route here (`GET /api/bot/work/schedule`, reading the VM's working
tree like the checklist route) and the render in
`benbaichmankass/ict-trader-dashboard`. The page is exactly as fresh as the last
push **to `main`** plus `ict-git-sync`'s ~5-minute pull.

---

## 8. Decisions — four taken 2026-09-21, the rest open

### Taken

| # | Question | **Decision** |
|---|---|---|
| **5** | What must an evidence record show to auto-promote to real money? | **Expectancy > 0 net of full costs at n ≥ 30, AND a majority of walk-forward folds positive, AND Stage-1 realized cost within tolerance of modelled cost.** All three. |
| **6** | What caps real-money exposure added without a human? | **25% of the account's configured risk budget across auto-promoted legs. No rate limit** — a leg-per-week cap was offered and declined, so a batch can land in one day. |
| **3** | The spend budget | **10% of the weekly plan allowance per day** — see below; this is a *fraction of an allowance*, not a dollar line, and it changes what A1 measures. |
| **3d** | Default disposition for the 1,065 archived backlog rows | **Kill by default, promote by exception.** No observation in 60 days and no named owner → killed with a stated reason. The 91 `OPEN-ITEMS` monitoring rows come across whole. |

#### The budget decision, and what it changes

Operator, 2026-09-21: *"We need to pace ourselves based on the weekly budget for
the $200 Max plan — I want the budget to be 10% of the weekly budget a day, so
that we leave ourselves a wide margin for error or unexpected needs."*

**10% per day × 7 days = 70% of the weekly allowance, leaving 30% margin.**
That is the rule, and it is deliberately a *share*, not a number of dollars.

⚠️ **Amended 2026-10-18 (operator):** *"We want to get as much work as possible out of our budget
without blowing through it before a reset."* The pace is now the **sustainable rate**, `(100 −
weekly%) / days to reset`, turned into 1–5 lanes by judgment with no hard cap. It is step 2 of the
manager skill's § "The operating loop" (`spend_meter.py --capacity`). The 10%-a-day share above is the
history, not the rule. It is still a share of the allowance, never dollars.

⚠️ **THIS CHANGES WHAT A1 MEASURES, and the change is not cosmetic.** A
subscription plan's constraint is a **weekly usage allowance**, not a dollar
spend. The `cost_usd` figures quoted throughout this plan — the $125 across two
resumed lanes, the $11.88 in ten minutes — are **API-equivalent pricing read off
session metadata**. They are the right signal for *comparing* lanes and the
wrong denominator for *pacing* against a plan. A1 must report **usage against
the weekly allowance** as the budget line, with the dollar figure kept beside it
as the per-lane comparison.

⚠️ **The denominator is not established and I did not invent one.** The exact
weekly allowance of the $200 Max plan is not readable from this repo, and
guessing it would put a fabricated number under a real rule. **A1's first job is
to establish it** — from whatever surface reports plan usage, or from the
operator — and to say `unknown` rather than substitute a figure until it has.

### Open

| # | Question | Recommendation |
|---|---|---|
| 1 | Does the soak book stay at 26 legs, or get curated? | **Keep it wide.** It is an instrument, not a decision surface, and R5's cadence read will say which legs are worth keeping — a measurement rather than a guess. |
| 2 | Cut real money now, or go flat during the transition? | **Cut rather than stop**, and R1 will do most of the cutting automatically. A6 already pulls the two worst. |
| 4 | How aggressive is the Phase-A deletion? | **Aggressive.** Partial removal leaves the treadmill running — which it has been, visibly: four cron commits landed on `main` during this PR, each recreating a register it archives. |

---

*Every figure on this page carries its population. Where a number could not be
established from the repo, it is absent rather than estimated. Live figures read
from `/api/bot/performance` and the committed registers on 2026-09-21.*
