# Next-week focus — planning for the week of 2026-11-26

> **Doc status:** `live` · category `plan` · produced 2026-11-23 by lane `ROADMAP-REVIEW-20261123` (dispatched by Manager Session 2026-11-22a) · a memo for Thursday's sync; it authorizes nothing.

**Gates this adds or changes: none.**

How to read it: every number names its population and where it was read. "—" means I could not read it. Where the manager's brief gave a number I did not re-measure, it is marked *(manager-supplied, not re-read)*. Reads were made 2026-11-23 ~09:00Z: the console `performance` and `ml_roadmap` reads, `scripts/ops/roadmap_map.py --report`, the checklist store (2,038 row files), `scripts/ops/pipeline.py --due --all`, `research/programmes/*.yaml`, and `git log origin/main` since 2026-11-17 (the local clone was shallow; I deepened it to 1,463 commits, of which 556 are not queue-stamp / batch-land / receipt / forecast-grade / desk-mirror chores).

---

## 0. Two things to know before the rest

1. **I could not reproduce the manager's real-money headline.** The brief says −45.8%, n=556, PF 0.67. The console `performance` read (book `real_money`, all-time window, n=532 closed trades, every one with R) shows **ΣR −162.0 (expectancy −0.30 R/trade)**; last 30d **n=69, ΣR −5.5 (−0.08 R/trade)**; last 7d **n=18, ΣR −4.2**. The console returns no profit factor and I did not read a percent-return figure, so −45.8% and PF 0.67 are *unverified here*, not contradicted. The populations differ (n=556 vs n=532), so the two should be reconciled before either goes to the operator as a headline.
2. **One leg explains the lifetime loss; a different leg explains the recent one.** Real-money, all-time, per leg (same read): `vwap` n=318, ΣR −145.8 (that is ~90% of the −162.0, and it has no trades in the 30d window — it is out of the real-money flow now; its soak row reads `dead`). The 30d bleed is `ml_entry` n=51, ΣR −7.1 (all 51 inside 30d), then `xrp_pullback_2h` n=20, ΣR −12.1 lifetime (n=2 in 30d). The positive real-money legs: `trend_donchian` +7.6 (n=15), `ict_scalp_5m` +4.9 (n=35), `trend_donchian_eth_4h` +4.7 (n=19), `ada_pullback_2h` +1.6 (n=20; 30d +8.2 over n=4). So "the book is negative since inception" is true, but it is mostly a closed chapter (vwap); the live question is `ml_entry` and `xrp_pullback_2h`.

Context populations (same read, all-time): paper book n=1,991 ΣR −70.9; paper-portfolio mirror n=225 ΣR +3.8; paper 30d n=361 ΣR +63.4; mirror 30d n=80 ΣR +41.8.

---

## 1. WHERE WE ARE — per milestone

Source for status and counts: `roadmap_map.py --report` (36 milestones: 23 active, 13 closed / retired / backlog / dormant). Source for status text: `docs/roadmap/milestones.yaml` `next` fields and the checklist rows named. **Every one of the 36 milestones is flagged `OVERDUE` for review** (last reviewed 2026-10-14 … 2026-11-11), so each "next" field below is at least 12 days old; I judged on-track / stalled / blocked from the rows, not from that text. "Rows" = live checklist rows / open queue units from the map.

### G1 Real-money edge, decided offline
- **L-AM-STANDARD** (target 2026-11-04, past) — rows 17 / units 10. **Stalled**: `AM-RISK-ADJUSTED-RULE` blocked on `BOOK-SIM-REAL-SIZER` and `HARNESS-BE-RANDOM-CONTROL`; the stop-tightening lever map (`ltr-tighten-sl`) has all three action_bounds iterations failed (d4a9-01/02/03, #28328).
- **L-ATM** — 82 / 37. **Partly blocked**: `TPX-XRP-DECLARE` waits on live closed-bar xrp trades; in flight: `MARKOUT-HARNESS`, `DESK-TRIGGER-SCAN-TIMEOUT`, `LTR-ROWS-BRANCH-STALE-VALIDATOR`. Open design defect PI-20261118-EFILLW47-0001 (ltr-close trigger).
- **L-LADDER** — 58 / 114. **On track mechanically, blocked on a public-repo hygiene item**: `ACCOUNT-SNAPSHOT-BALANCE-HISTORY` blocked on `BALANCE-TIP-PRESCRUB`; `DIAG-RELAY-EQUITY-LEAK` and `CF-GRADES-EQUITY-COMMITTED` in flight. Soak report: 5 ready, 1 dead, 1 could-not-look, 44 accruing of 51 tracked.
- **M22** pairs — 5 / 0. **Stalled**: no open unit; the P3 programme closed the stale M22 roster node (#27538).
- **M27** scalp — 2 / 0. **Moving, no unit**: ict_scalp_5m / sol_5m `S_ASIA` session-filter proposals landed HELD (Tier-3, demo floor only: #27624 and the 2026-11-19 sol_5m one; #27415 merged 11-19).
- **M18** allocator — 6 / 0. **Stalled / dormant in effect** (next field: observe `arbitration_fanout_soak` writing; not read).
- **L-TIMEFRAMES** — 3 / 0. **Stalled**: programme 07 has 13 of 16 nodes needing authoring and only 2 with units.
- Closed/retired, no action: M20 (→L-ATM), M21, M24, M16, M15.

### G2 Prop-account income
- **L-PROP** — 36 / 15. **Blocked on operator/phone steps**: `PHONE-CLOSED-ORDERS-NEW-LAYOUT`, `PROP-PHONE-AMEND-REPORT` (operator reaction), `PROP-FORMING-BAR-REEMIT` (re-measure pending), `LTR-PROP-CLOSE-FALSE-APPLIED` in flight (a close reported APPLIED that did not hold). Prop research moving: sol_prop vol-target PASS has a disjoint-span confirmation unit queued (c3a7-01, #27798).

### G3 Trustworthy plumbing
- **M39** — 24 / 0. **Stalled on observation**: the next field says drive `landed_unproven` rows to observation; 378 of 2,043 checklist rows (store read) are `landed_unproven`.
- **L-ALERT-INTEGRATION** — 3 / 0. **On track** (`WORK-GAP-ALERTS` in flight).
- Closed: M31 (→L-ATM).

### G4 AI trader
- **L-ML-LIVE** (target 2026-11-11, past) — 99 / 52. **Moving, not at its done-condition**: ml_entry new model promoted to real money 11-23 (#28130, HELD); `ML-LIVE-PARITY-ML-LEGS`, `ML-EXITHEAD-ROWS-KAGGLE`, `ML-WEEK-PLAN-1119` in flight. Console ML plan status: 175 plan items, 111 flagged (STALE / CLOSED-OPEN / OPEN-DONE).
- **L-DESK-V1** (target 2026-11-11, past) — 1 / 0. **Unclear**: desk decision mirrors land daily (commits titled "desk: mirror decisions" on 11-19 through 11-22, count not taken), but the milestone has one live row and the done-condition is not restated; I did not read `comms/desk/`. Unverified.
- **L-DESK** — 63 / 7. **Blocked**: seven later-phase DESK-19..26 rows blocked on DESK-11 / DESK-16 / DESK-17 / CJ-2 / CJ-4.
- **L-REGIME** — 14 / 7. **Stalled**: next field (2026-11-04) asked for REGIME-UNITS-W45; plan items ML-R1, R5, R6 are STALE or dropped.
- **M25** — 37 / 8. **Moving**: producers for demoted heads outstanding; `CJ-5-STUDENT-MANIFESTS` waits on `CJ-LABEL-ALTERNATIVE`.
- **M23** meta-labeling — 7 / 2. **Moving**: P1 setup meta-label paper-book eval built (#27430), 2780-04 graded PASS (#27559), 3e98-01 INDETERMINATE.
- **L-DATA** — 15 / 0. **Blocked**: `DATA-INTRADE-LABEL-STORE` on EXIT-PATH-EMIT-OFFLINE, DATA-KLINE-ARCHIVE, DATA-LABEL-TIES. `EVENT-SPAN-HISTORY` in flight.
- **L-ML-MECE** — 29 / 1. **Moving** (slots: manager brief says 7 of 10 have a next unit; D1 blocked by rule, D3 needs a point-in-time macro feature builder, D7 family review 11-27, D10 needs n≥150 graded closes *(manager-supplied, not re-read)*).
- **M41** local LLM — backlog, 0 / 0. **Parked on a record**: killed as scoped (frontier scan 2026-11-11 § 4).
- **L-ML-AGGREGATOR** — backlog, 0 / 0. **Parked on evidence**: D5 re-entry test RQ-20261115-a474-02 FAILED (PI-20261117-ZFRREVN5-0001).
- Closed/retired: M26, M14, M9.

### G5 Learning machine
- **L-PROGRAMMES** — 55 / 7. **Moving but starved of authoring**: across the 8 programme files, 130 of 473 nodes `needs_authoring`, 42 are `authoring_closed`.
- **M40** — 11 / 0. **Degraded**: PI-20261118-JFWRQYOV-0001 (runner ~5% utilised), EFILLW47-0002/0003 (runtime estimate overstated ~8×; kaggle_cpu route lands `producer_failed`).
- **L-OPS** — 210 / 17. **Overloaded**: 10 in-flight/blocked rows; the pipeline reads **806 due items with a ROUTING ALARM** (oldest unrouted 8d, PI-20261115-LRP-A6B86637).

### G6 Macro and value sleeve
- **M28** — 9 / 8. **Waiting on data**: `NEWS-VETO-ARMB-READ` clears 2027-02-08; `WEPE-BUILDOUT` gated behind it.
- **M29** — dormant, 1 / 0. **Dormant by record.** Closed: M36.

### G7 Operator surfaces
- **M6** — 27 / 0. **Blocked on a held PR**: `UI-SPA-BACKEND-ROUTES` waits on #25231.

---

## 2. WHAT MOVED since 11-18

Source: `git log origin/main --first-parent` since 2026-11-17 (1,463 commits; ~900 are automation chores) plus the writebacks on the rows above.

- **ML entry:** graded candidate PASS → new `ml_entry` model served and repointed, HELD (#28130, 11-23).
- **Stop tightening:** `ltr-tighten-sl` action_bounds d4a9-01/02/03 all FAIL; lever map updated (#28328). The 11-18 ltr-close iteration (43b6-02) raised a trigger-design defect (PI-20261118-EFILLW47-0001).
- **Live leads:** `abab-17` SOL symbol-disjoint confirmation unit authored (#28337); `ict_scalp_5m` / `sol_5m` S_ASIA session filters proposed HELD (#27624, 11-19) with a filter frame-shape fix; sol_prop vol-target PASS + disjoint-span confirmation unit (#27768, #27798); venue-gap evidence record with Bybit-native re-tests (#27630).
- **Order-path fixes (HELD):** Alpaca trail/amend leg scoping by entry order id (#27494, Tier-2); live-review packet fixes (#27496); partial-close P&L journaling and demo-exit attribution fix (#25261, still held).
- **Research tooling:** exit-head builder anchors to live fills + corpus rebuild (#27676); ML-EXIT-ACTIONGRID-LABELS (#27377); mechanical grade pass of 81 units (#28331); prop-gate verdict contract (#28228); desk replay record (#28236).
- **Parked by operator 11-17 "until after the reset":** xsec-crypto, movement-capture (PI-20261117-NIVCJP7T-0004/-0005).
- **Not moved:** every milestone's `reviewed` date (none after 2026-11-11); `L-ML-LIVE` and `L-DESK-V1` targets passed unmet.

---

## 3. GAPS

**Milestones with no live row or no open unit** (map, population: 36 milestones):
- 0 live rows and 0 units, with a stated reason: M24, M15, M26, M9, M36 (retired/closed), M41, L-ML-AGGREGATOR (backlog). No action beyond the reasons on file.
- Live rows but **0 open units** (nothing queued to move them): M22 (5), M27 (2), M18 (6), L-TIMEFRAMES (3), M39 (24), M40 (11), M6 (27), L-DATA (15), L-DESK-V1 (1), L-ALERT-INTEGRATION (3). L-TIMEFRAMES and M22 are the ones with a stated testable next step and no unit.

**Rows or units with no roadmap ref:** the map reports **0 orphan live rows, 0 orphan open units, 0 dangling refs.** But 9 of the 49 in-flight/blocked rows carry the explicit token `unmapped` (PHONE-DRILL-TP-CLOSE, CAP-PROP-LIVE-DRILL, ML-ENTRY-POPULATION-TEST, WEPE-BUILDOUT, FREE-CAPACITY-PLAN, SEC-GITLEAKS-BASELINE-1116, CI-SPARSE-BOOTSTRAP-FLAKE, AUTOMATION-DATACOMMIT-CONFLICT, LTR-PROP-CLOSE-FALSE-APPLIED). Two of those are live-money-adjacent (ML-ENTRY-POPULATION-TEST, LTR-PROP-CLOSE-FALSE-APPLIED). The "0 orphans" figure is true by the token, not by a milestone.

**Programme nodes:** all 473 nodes carry a roadmap ref; 130 await authoring. P2 (AI trader) is the worst: 30 of 49.

**ML plan hygiene:** 111 of 175 plan items flagged (console `ml_roadmap`); the 15 ML rows I read were all overdue by their own `due_by`.

**Follow-through backlog:** 806 pipeline items due, routing alarm raised; one filing (PI-20261118-JFWRQYOV-0001) says research runner throughput is ~5% utilised, so the cause is not a lack of capacity.

---

## 4. RECOMMENDED FOCUS FOR NEXT WEEK (ranked by expected money impact)

1. **Triage the two real-money legs that are losing now: `ml_entry` and `xrp_pullback_2h`.**
   *Why:* real-money n=532 ΣR −162.0, but vwap (n=318, −145.8) is already out of the flow; excluding it the other legs sum to −16.2 over n=214, and `ml_entry` (−7.1/51) and `xrp_pullback_2h` (−12.1/20) are the two largest negatives still trading. The new ml_entry model went to real money today on offline evidence; the live bar (≥20 live trades, ΣR>0, ~80% lower bound >0) is the answer to whether it holds.
   *First step:* a lane registers, before the data arrives, the read for the new model's first 20 live closes (and the demotion trigger from the mirror's net-of-cost window), and re-measures the xrp leg's live-vs-backtest band (TPX-XRP-DECLARE already waits on its closed-bar trades). Also reconcile the manager's −45.8% / n=556 with the console's n=532.
   *Owner:* lane. *Size:* S (1 lane-day) plus observation time.

2. **Make the journal and deploy order trustworthy for real-money legs.**
   *Why:* R is the metric every decision above rests on. Partial-close P&L is not journaled and the demo-exit fill attribution is wrong (`PARTIAL-CLOSE-PNL-NOT-JOURNALED`, `DEMO-EXIT-FIRST-FILL-ATTRIBUTION`, both blocked only on PR #25261 held for merge). Config read live each tick can land before the code that needs it (PI-20261119-FILLW47B-0008, marked HIGH for real-money legs). `LTR-PROP-CLOSE-FALSE-APPLIED` shows a close reported APPLIED that did not happen.
   *First step:* manager decides #25261 (Tier 2) and #27494; a lane specifies the config-before-code guard from FILLW47B-0008.
   *Owner:* manager merge + lane. *Size:* S–M.

3. **Close the live leads and the stop-tightening question with decisions.**
   *Why:* `fade_breakout_4h` S_ASIA (abab-17) is the one live lead with a pending confirmation (RQ-20261123-b4c1-01); `ltr-tighten-sl` has every lever tested and failed, so Thursday's lever-exhaustion review is a retire-or-redesign call. ict_scalp_5m is a real-money winner (+4.9R, n=35) whose S_ASIA proposal is HELD.
   *First step:* read b4c1-01 when it lands; run the lever-exhaustion review with the d4a9 results as the record.
   *Owner:* research unit + lane. *Size:* S.

4. **ML (operator priority, 2026-11-14): unblock D3 and keep ml_entry's population test moving.**
   *Why:* ML is the stated second priority and the only slots with a path to a new live edge; D3 needs a point-in-time macro feature builder, D7 reviews 11-27, D10 needs n≥150 graded closes. `ML-ENTRY-POPULATION-TEST` is `unmapped` and unattended.
   *First step:* author the D3 builder as one row/unit with its leakage test (the `EVENT-SPAN-HISTORY` in-flight row is the likely input); map `ML-ENTRY-POPULATION-TEST` to L-ML-LIVE; clear the 111 flagged plan items by closing the CLOSED-OPEN / OPEN-DONE ones.
   *Owner:* ML lane. *Size:* M.

5. **Clear the routing backlog and the public-repo equity leaks.**
   *Why:* 806 due pipeline items with a routing alarm means follow-ups are being lost; `DIAG-RELAY-EQUITY-LEAK`, `CF-GRADES-EQUITY-COMMITTED` and `BALANCE-TIP-SCRUB-2` are in flight because account equity has been written into a public repo. Lower direct money impact, but it is the debt that keeps growing.
   *First step:* one routing pass that kills or routes the oldest 50 and measures the alarm age; finish the three scrub rows.
   *Owner:* manager + lane. *Size:* M.

Not recommended for the week: new roadmap milestones, new gates, any M41/M29/M22 work (parked or dormant on record).

---

## 5. DECISIONS THE OPERATOR WILL NEED next week

1. After the lever-exhaustion review: **retire `ltr-tighten-sl`**, or redesign it with a new lever? (pick one)
2. `xrp_pullback_2h` (real money, n=20, ΣR −12.1): **demote to the demo floor now**, or hold until the live bar's n is reached? (pick one)
3. The new `ml_entry` model: **accept a pre-registered demotion trigger** (first 20 live closes, ΣR and ~80% lower bound)? yes / no
4. Merge the held Tier-2 order-path / journal PRs (#25261, #27494)? yes / no, each
5. Approve the `ict_scalp_5m` / `ict_scalp_sol_5m` S_ASIA session-filter proposals (Tier-3, demo floor only: #27624, the 11-19 sol_5m PR)? yes / no, each
6. `mgc_trend_1h`: **keep on the roster** or remove? (pick one)
7. xsec-crypto and movement-capture were parked "until after the reset" (Wed 11-25 ~20:00Z): **unpark both**, or retire? (pick one each)
8. The five design-needing orphans (qqq/spy pullback 1h, xsec-crypto, ml-exit-head-donchian-1h, ml-btc-router-cells): **commission design for how many, and which**, or retire? (pick the subset)
9. The grade/rule agreement proposal (PI-20261123-SME5WDGR-0003) and the baseline-moves-with-config proposal (-0005): approve? yes / no, each
10. Is a **daily or weekly milestone-review cadence** wanted, given all 36 are overdue? yes (name the cadence) / no, treat the `reviewed` field as dead

Not asked: the claude.ai usage-credits toggle (out of scope per CLAUDE.md).
