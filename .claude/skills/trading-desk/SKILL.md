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

What is never in any enum: a `mode:` / `execution:` / roster change, any halt.

**All trade actions (operator 2026-10-26, verbatim: *"we also need to expand the desks mandate so include all trade actions, as long as they have reasoning and confidence attached"*; which book: *"Both"*).** On the strategies' trades the in-trade role is the live trade review, which now makes `close` · `partial_close` · `move_tp` · `widen_sl` · `change_size` · `add_entry` calls under `MD-LIVE-TRADE-ACTIONS` (live-trade-review SKILL § 3b), each with a reason and a confidence, applied per account through that account's own risk manager. The desk's OWN rows get the same scope under `MD-DESK-TRADE-ACTIONS`, which is `blocked_until` the DESK-13 gate (operator: *"Beat random entries only"*: OOS edge vs the random-entry baseline, net of the full cost stack, n >= 30). Until it clears, the desk is phase-1 shadow: it may record these actions with reason and confidence (schema v2 gains them with DESK-17's in-trade/exit rows), and nothing is sent.

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
- **The cost per wake is MEASURED by DESK-6** and stated on its checklist row; re-measure it from `get_session(<wake session>).usage` before changing the cadence. The breach order is design § 7.3: offline sessions → rho → optional entry review → lengthen the scan cadence → paper L0-only → in-trade degrades to recommend-only on Sonnet.

## 6. The stage table (each restriction is a stage; design § 0.4)

| stage | what runs | restriction today | lifts when (evidence) | row |
|---|---|---|---|---|
| **1a** (live) | in-trade on the strategies' trades = the live trade review: tighten under `MD-LIVE-TIGHTEN-SL`, every other trade action under `MD-LIVE-TRADE-ACTIONS` (operator 2026-10-26) | each account's own risk manager; an account with no executor for an action refuses it, named | the desk's OWN rows: the DESK-13 gate (beat random entries, OOS, net of cost, n >= 30) clears `MD-DESK-TRADE-ACTIONS` | DESK-7, DESK-13, LTR-ALL-ACTIONS |
| **1b** (this skill, DESK-6) | entry_generation **shadow**: hourly scan wake (VM posts, manager spawns), one row per packet, every proposal replayed | record-only; Sonnet only; packet is the only feed | the D-S0 entry-generation unit passes (masked replay + the forward-shadow set from THIS stage not contradicting it, n ≥ 100) | DESK-18 |
| **2** | `claude_desk` leg rostered `execution: shadow` on `bybit_1` + `alpaca_paper`; proposals reach it through intake | no orders | D-S0 passes → the leg goes `execution: live` on paper; the mechanical soak is 1–2 clean desk trades ([`OPERATING-PLAN` § 2 "The soak is MECHANICAL"](../../../docs/plans/OPERATING-PLAN-2026-09-21.md)) | DESK-4a, DESK-17 |
| **3** | the leg on real money + mirror; prop via the prop superset gate | desk entries only on paper; no prop | `MD-PROMOTE-S1-S2` (human-merge PR); prop EV/survival vs the firm's DD limits | DESK-17, manager |
| **cadence** | hourly scan (phase 1) | 1 h scan; 15-min floor in the design | a 15m/5m scan packet + VM packets and intake (DESK-1, DESK-4b); below 5 min a student, not Claude | DESK-1, DESK-4 |
| **feed** | the packet only | no live web context | DESK-14 (logged `external_context`, excluded from training by default) | DESK-14 |
| **4** | students take over role by role | Claude decides every role | per role: S-shadow → S-advisory → S-drives on net R per capital-day, out of sample, margin 0 vs Claude (DECIDED) | DESK-19 |

**Desk heartbeat (design § 12).** The desk branch's newest row `judged_at` vs the newest packet `built_at`: more than 2 packets without a row while the routine is installed is one flag to the manager (the routine's own report says so; a probe in `attention_watch` is DESK-6's follow-up, filed in the pipeline).

## 6b. The trigger: the VM gate posts, the manager spawns (the hourly routine is retired)

**The trigger (DESK-6B, operator 2026-10-26: *"the system landing the packet [is] what triggers the session ... the session shouldn't be starting before the packet lands"*).** The step that LANDS the packet posts the wake, and nothing else does. The **live trader is the primary producer** (`src/runtime/desk_packet_wake.py`, kicked from the tick loop about every 2 min): when the current UTC hour has no packet (at least 1 min into it, at most 3 tries per bar) it runs the workflow's own builder (`scripts/ops/desk_scan_packet.py`, desk book read from the branch's decisions, public candle route on the local API), stages it with `desk_branch.py publish`, lands the packet and the pointer on `desk/decisions` as ONE fast-forward commit through the GitHub git-data API (never forced), and in the same pass posts ONE `desk-wake` marker on the ops-flags PR carrying `packet_id`, `packet_sha` and the packet `commit`. The manager is subscribed to that PR and, on the marker, does exactly the `create_session` below (`manager` SKILL § "Desk wake"). The hourly spawner routine (trig_01NMCJ5LHARkp6vWgTmQ8BC9) is **retired**.

**Why the VM is primary (MEASURED by the manager 2026-10-26):** GitHub's cron NEVER fired `desk-scan-packet.yml` on schedule (only `workflow_dispatch` runs), and a packet built by a backed-up runner landed ~30 min late. `desk-scan-packet.yml` is the **fallback**: `schedule-keeper` dispatches it for a missed hour; its first step (`desk_wake_marker.py gate`) does nothing when the bar already has a packet, and its last steps post the same marker, deduped on the packet id **and the bar**, so the two producers can never both wake for one bar. ⚠️ **UNVERIFIED at merge:** whether the VM's git credential may write `desk/decisions`, and whether the VM has the diag token for the system-book read (without it the packet is still valid, with `system_book` honestly `could_not_look`). A refused write reads `could_not_commit` (http code) in the receipt and the fallback covers the hour.

**There is no market-hours or activity gate** (operator: crypto is 24/7, so every hour wakes). The only conditions:

- a failed build or commit -> **no wake** (receipt `could_not_build` / `could_not_commit`, named; the fallback workflow posts a `could_not_build` incident marker for its own failures);
- a `desk-wake` marker for that packet id or that bar is already on the PR -> not re-posted;
- otherwise the marker is posted. It also carries the packet's `context` as information only (open positions, open desk proposals, near-signal count, calendar events, unread books; an unread book is `null`, never 0).

**Receipt and liveness.** `/api/diag/log_file?name=desk_wake_post_receipt`, rewritten every pass: `posted` (`producer` `vm` or `packet-job`, `latency_s`) · `already_recorded` · `awaiting_wake` (< 10 min) · `wake_missing` (packet older, no marker, no row) · `could_not_build` · `could_not_commit` · `could_not_post` · `could_not_look` (`reason`, incl. `stale_packet`). The `desk_wake_post` probe in `attention_watch` raises one flag when the receipt is more than 3 h old or reads `wake_missing` / `could_not_*`.

**What a wake must be started with (MEASURED 2026-10-26, four wakes, lane DESK-6).** A wake writes only if its session is started ON `desk/decisions`: `create_session` with `source_url` = this repo, `source_revision` = `desk/decisions`, `outcome_branch` = `desk/decisions`, `clone_depth: 1`, `sparse_checkout_paths: [".claude/skills/trading-desk"]`, model Sonnet. With no repository (even after `add_repo` with `access: push`) the write was refused (403), and on another branch it never landed.

`create_session` arguments for a `desk-wake` marker:

```
  model: <the Sonnet model id from the manager's model table>
  title: desk-wake <the marker's bar, YYYY-MM-DDTHH:MMZ>
  tags: ["manager:session_01HAysMLfF9dYpi92YMqYxEq", "desk-wake", "DESK-6-SHADOW-PILOT"]
  permission_mode: auto
  source_url: https://github.com/benbaichmankass/Metis-Insights
  source_revision: desk/decisions
  outcome_branch: desk/decisions
  clone_depth: 1
  sparse_checkout_paths: [".claude/skills/trading-desk"]
  prompt: (the WAKE PROMPT below, verbatim)

WAKE PROMPT:
You are one wake of the Claude trading desk (phase 1: shadow, record-only), started by the Metis-Insights manager's routine. The manager acts with the operator's authority. Your session's branch IS desk/decisions, the desk's append-only record branch: writing ONE row there is your whole job.
1. Read your whole contract: get_file_contents on repo benbaichmankass/Metis-Insights, path .claude/skills/trading-desk/DESK-BRIEF.md, ref refs/heads/main. skill_sha = the blob sha it returns.
2. Follow that brief EXACTLY and only it. Read nothing else in the repo, no diag, no web.
3. If you cannot read your session id, write session = "desk-wake".
4. End with the brief's § 6 report block, plus which write path worked. Do not open a PR or an issue, and do not message anyone.
```

**Cadence: hourly, not the design's 15 min, decided on data (design § 11 leaves cadence to DESK-6's measurement).**

- **MEASURED cost per working wake** (`get_session().usage.cost_usd`, 2026-10-26, Sonnet, fresh session, one 1h scan packet ≈ 53 KB): **$0.45, $0.34, $0.45, $0.47** (n = 4; context 119–134 k tokens; 65–85 s wall). INFERRED: hourly ≈ 24 wakes ≈ **$11/day** (the spawner routine it assumed is retired; the packet landing wakes every hour); the design assumed $0.041 a working wake (§ 5.3), so a fresh-session wake costs ~10× the standing-session estimate, because each wake re-pays the session's base context.
- The packet is a **1h** scan: its base rates and ATR are on 1h bars, so 3 of every 4 15-minute wakes would find nothing due and still pay a fresh session's start. The 15-min stage needs a 15m scan packet and a standing session (§ 6, `cadence`).
- Cheaper per label, in order: a slimmer packet (drop untradable universe rows), a standing session at K* ≈ 22 wakes (design § 5.3), batching several symbols per wake. DESK-10 owns the $/pp conversion.

## 7. Changing the desk

- A skill or brief text edit changes `skill_sha`: record it; it does not re-run Stage 0. A model-family change re-runs a D-S0 confirm set (n ≥ 200) before the changed desk trades (design § 8.1).
- Edit the brief and `tests/test_trading_desk_brief.py` together; the test fails if the brief's embedded schema drifts from `comms/schema/desk_decision.schema.json` or its example row stops validating.

## 8. Composes with

`live-trade-review` (the in-trade role) · `manager` (spawns the wake on the `desk-wake` marker, reads the reports) · `backtesting` / `research-ops` (DESK-18's D-S0 units) · `ml-review` (DESK-19 students, step 9) · `performance-review` (DESK-9 "Desk" section) · `close-out`.
