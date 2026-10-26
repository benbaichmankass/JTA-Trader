---
name: trading-desk
description: The Claude trading desk's operating procedure. The desk DRIVES the trading: it finds trades the strategies are not taking (entry_generation on a SCAN packet), and in later stages enters, manages and exits them as the claude_desk leg, while the system's ML students learn from every recorded decision and outcome until they replace Claude role by role. Owns the loop, the roles, the closed enums of desk schema v2, escalation, the teacher-sampling dial rho, rotation, and the stage table with each stage's lift condition. Phase 1 is RECORD-ONLY. A wake runs as a fresh REPO-LESS session from DESK-BRIEF.md plus the newest scan packet on the `desk/decisions` branch and writes ONE validated decision row by compare-and-swap. Extends live-trade-review (the in-trade role) rather than duplicating it. Use when the desk routine fires a wake, when the manager dispatches a DESK lane, or the operator says "run the desk", "/trading-desk", "what would the desk trade". NOT the live trade review's procedure (live-trade-review), NOT closed-trade grading (performance-review), NOT an order path (the desk never places, sizes or moves an order in phase 1).
---

> **Doc status:** `live` · category `instruction` · last verified `2026-10-26` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md)

# /trading-desk — the desk drives; the models learn from it

> **Operator, 2026-10-26 ~06:55Z (verbatim, row `DESK-15-ENTRY-GENERATION`):** *"the Claude trading desk is driving the trading, and the MLs, the systems MLs that we're building are learning from that Claude decision-making how to do it themselves so that we can eventually remove Claude from the flow and have only our own AIs doing the trading."*

Design of record: [`docs/plans/claude-trading-desk-DESIGN.md`](../../../docs/plans/claude-trading-desk-DESIGN.md) (v1, operator-approved as the build plan 2026-10-26; § 11 all DECIDED). Checklist rows `DESK-5-SKILL` (this file) and `DESK-6-SHADOW-PILOT` (the routine it runs under). Roadmap `L-DESK`.

**The wake contract a repo-less session runs is [`DESK-BRIEF.md`](DESK-BRIEF.md).** It is self-contained: input, judgement, the exact row, the schema, the write. This SKILL.md is the operating context around it, for the manager and for any lane that changes the desk. When the two disagree, fix the disagreement in the same PR; `tests/test_trading_desk_brief.py` pins the brief's embedded schema and example row to the real validator.

**Entry review or veto of the strategies' signals is NOT the design** (design § 0.2). The desk is a trader, not a reviewer.

---

## 0. Binding limits (read first)

1. **Phase 1 is record-only.** Every desk row is `label_source: shadow`, `disposition.route: none`, `intent_id: null`. The desk **never** places, sizes, amends or cancels an order; never writes `config/`; never opens an issue. `desk-records-guard` refuses a shadow row that carries an intent or a submitted/applied route.
2. **No size, ever.** A proposal names where the trade is wrong (`stop`) and where it is expected to end (`tp`). Each account's `RiskManager.approve()` sizes it once the leg exists (design § 3.7). The guard refuses any size-shaped key anywhere in a row.
3. **The TP doctrine binds at proposal time.** `tp` is a real predictive target with a `basis` and `p_hit` in [0.10, 1). A sentinel distance, a venue-cap level or "the trail decides" is refused (`docs/ARCHITECTURE-CANONICAL.md` § "TP doctrine").
4. **The packet is the only feed.** No web, no repo reads, no diag. A big-event pull is a logged exception (`external_context`, design § 2.4) and is out of scope for the phase-1 routine.
5. **No halting.** A dead desk session leaves every position on its venue bracket. A stale desk is one flag (§ 6), never a stop of anything (Prime Directive rule 7).
6. **The model field is a TIER** (`sonnet-tier`), never a model identifier: the repo is public.

---

## 1. The loop

```
VM/runner (L0, no model)                         desk wake (fresh repo-less session)            main (record)
desk-scan-packet.yml, hourly at :03  ─► packet ─► reads latest_scan.json + packet + rows  ─►  ONE row by CAS ─► desk-decisions-mirror.yml
  scripts/ops/desk_scan_packet.py       on desk/decisions   (DESK-BRIEF.md § 1-2)              on desk/decisions    ─► comms/desk/decisions.jsonl
  (validated by desk-records-guard                                                                                   ─► desk_outcomes.py replays the
   before it is pushed)                                                                                                  bracket on real candles, net of
                                                                                                                         the full cost stack ─► outcomes.jsonl
```

- **Due.** A scan is due when the newest packet's `packet_id` has no row yet. A wake with nothing due records nothing and ends (design § 2.5: *"a cadence wake with nothing due costs one call and records nothing"*).
- **One wake, one packet, one row.** `no_trade` is a decision and is recorded whenever a scan was due: it is how a student learns when not to trade.
- **The label.** Every `propose_entry` is replayed on the real path from `info_cutoff_at`, whether or not anything traded, by `scripts/ops/desk_outcomes.py` (a `replayed` outcome, or `expired_unfilled`). A `no_trade` gets a `not_computable` placeholder naming DESK-20, which prices its baseline bracket. Rows are train-eligible and never-trained-on until a dataset build lists them in `comms/desk/consumed.jsonl` (`check_desk_records.never_trained_on()`; DESK-21 alarms on it).

## 2. Roles (design § 2.1)

| role | packet | enum (closed, schema v2) | default | phase 1 |
|---|---|---|---|---|
| **entry_generation** (lead) | `scan` | `no_trade` · `propose_entry` · `watch_note` | `no_trade` | **runs**: shadow proposals, every one graded |
| **in_trade** | `in_trade` | `hold` · `tighten_sl` · `tp_revise` · `flag_mechanics` · `no_recommendation` · `file_hypothesis` | `hold` | runs **as the live trade review** (below) |
| **exit** | `in_trade` | `hold` · `partial_close` · `close` | `hold` | not yet: needs the claude_desk leg (DESK-17) |
| **post_trade** | `exit` | `blind_grade` · `revealed_grade` | — | CJ-3 |
| entry_review (optional) | `entry` | `take` · `skip` · `delay` · `no_recommendation` | `take` | **never applied, never a veto**; only with spare capacity |

**In-trade extends live-trade-review; it is not duplicated here.** The in-trade role on the strategies' trades IS `.claude/skills/live-trade-review/SKILL.md` (and its repo-less `REVIEWER-BRIEF.md` once #20319 lands): its rows go to `live-review/rows` → `comms/live_review/reviews.jsonl`, its tightens apply under `MD-LIVE-TIGHTEN-SL`, and DESK-11 maps those rows into the desk's training feed as `kind: desk_in_trade`. A desk wake does not re-review a package the live review already covers. On the desk's OWN trades (after DESK-17) the in-trade and exit decisions are the leg's own management and are written here, as desk rows on an `in_trade` packet.

What is never in any enum: a size or risk change, a widened stop on a strategy's trade, a `mode:` / `execution:` / roster change, any halt.

## 3. Escalation and models (design § 4.4)

| decision | model |
|---|---|
| every phase-1 wake (shadow, record-only) | **Sonnet**. Shadow and paper records never escalate |
| a `propose_entry` bound for a real-money or prop account (phase 3+) | Sonnet proposes; **Opus confirms** before the intent is issued |
| a non-`hold` in-trade action on real money / prop, any `flag_mechanics` | Opus (the live-review rule) |
| the blind teacher sample (rho) | Opus, daily batch, same packet, without Sonnet's answer |

## 4. The dial rho (design § 4.5)

The fraction of desk decisions an Opus teacher re-judges blind. Start **0.25**; **0.5** for a role while its teacher n < 150; **0.10** once the role passes CJ-4; **0** first in a capacity breach, before any live tier degrades. The teacher batch is not built yet (it rides DESK-9 / CJ-3); until it is, rho is declared, not running, and this sentence says so.

## 5. Rotation and cost

- **Phase 1 runs one fresh repo-less session per wake**, so there is no context growth to rotate: each wake starts from the brief and one packet. The design's standing-session rotation (K* ≈ 22 wakes, never past 50% of the window, state handed forward through the repo) applies when a standing session replaces the per-wake spawn (DESK-1 + DESK-4b, the 5-min stage).
- **The cost per wake is MEASURED by DESK-6** and stated on its checklist row and in the routine's install note; re-measure it from `get_session(<wake session>).usage` before changing the cadence. The breach order is design § 7.3: offline sessions → rho → optional entry review → lengthen the scan cadence → paper L0-only → in-trade degrades to recommend-only on Sonnet.

## 6. The stage table (each restriction is a stage; design § 0.4)

| stage | what runs | restriction today | lifts when (evidence) | row |
|---|---|---|---|---|
| **1a** (live) | in-trade on the strategies' trades = the live trade review, tighten-only applies | in-trade applies are tighten-only on strategy trades | the D-S0 exit unit passes, then an operator-granted exit mandate | DESK-7, DESK-13 |
| **1b** (this skill, DESK-6) | entry_generation **shadow**: hourly scan wake, one row per packet, every proposal replayed | record-only; Sonnet only; packet is the only feed | the D-S0 entry-generation unit passes (masked replay + the forward-shadow set from THIS stage not contradicting it, n ≥ 100) | DESK-18 |
| **2** | `claude_desk` leg rostered `execution: shadow` on `bybit_1` + `alpaca_paper`; proposals reach it through intake | no orders | D-S0 passes → the leg goes `execution: live` on paper; the mechanical soak is 1–2 clean desk trades ([`OPERATING-PLAN` § 2 "The soak is MECHANICAL"](../../../docs/plans/OPERATING-PLAN-2026-09-21.md)) | DESK-4a, DESK-17 |
| **3** | the leg on real money + mirror; prop via the prop superset gate | desk entries only on paper; no prop | `MD-PROMOTE-S1-S2` (human-merge PR); prop EV/survival vs the firm's DD limits | DESK-17, manager |
| **cadence** | hourly scan (phase 1) | 1 h scan; 15-min floor in the design | a 15m/5m scan packet + VM packets and intake (DESK-1, DESK-4b); below 5 min a student, not Claude | DESK-1, DESK-4 |
| **feed** | the packet only | no live web context | DESK-14 (logged `external_context`, excluded from training by default) | DESK-14 |
| **4** | students take over role by role | Claude decides every role | per role: S-shadow → S-advisory → S-drives on net R per capital-day, out of sample, margin 0 vs Claude (DECIDED) | DESK-19 |

**Desk heartbeat (design § 12).** The desk branch's newest row `judged_at` vs the newest packet `built_at`: more than 2 packets without a row while the routine is installed is one flag to the manager (the routine's own report says so; a probe in `attention_watch` is DESK-6's follow-up, filed in the pipeline).

## 7. Changing the desk

- A skill or brief text edit changes `skill_sha`: record it; it does not re-run Stage 0. A model-family change re-runs a D-S0 confirm set (n ≥ 200) before the changed desk trades (design § 8.1).
- Edit the brief and `tests/test_trading_desk_brief.py` together; the test fails if the brief's embedded schema drifts from `comms/schema/desk_decision.schema.json` or its example row stops validating.

## 8. Composes with

`live-trade-review` (the in-trade role) · `manager` (installs the routine, reads the reports) · `backtesting` / `research-ops` (DESK-18's D-S0 units) · `ml-review` (DESK-19 students, step 9) · `performance-review` (DESK-9 "Desk" section) · `close-out`.
