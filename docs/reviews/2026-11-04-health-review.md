# Health review 2026-11-04 — an over-covered TLT position on ib_paper, and the trainer disk will fill by about 11-06

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-04` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `HEALTH-REVIEW-20261104` (session_01AFoLuJuS137LaGTV3KwRtZ, dispatched by manager session_01AFoLuHgZaSYnm9avjeZE33 under RESET-JOBS-20261104) · window 2026-10-28 19:40Z → 2026-11-04 19:35Z · record [`comms/reviews/health/2026-11-04-health-review.json`](../../comms/reviews/health/2026-11-04-health-review.json)

**Grade: investigate.** 4 concerns (H4, H10, H12, H15), 7 watches, 1 could_not_look (H16), 2 stalled calls. Real money looks clean: 9 real-money closes, all TP, SL or a strategy or operator exit; 0 reconciler, watchdog or orphan closes. The problems are on the demo floor, on the trainer VM, and in follow-through. Already covered elsewhere, and only cited here: alert routing, prop visibility, tick duration and restart churn (#22905); bybit_1 shared bracket (#22894); paper mechanics (#22908).

## 0. Prior calls (10-28 record, 6 calls)

4 hit · 1 miss · 1 unresolved · 0 void. Brier: INDETERMINATE (n < 10).

- **Hit:**
  - C2: SPLG→SPYM. The leg now evaluates on SPYM, so row HEALTH-20261028-SPLG-DELISTED is set `done`.
  - C3: live disk is 64.4% used, under the 85% rule.
  - C5: TP doctrine has 1 of 7 real-money routings compliant.
  - C6: invariant self-test passes 66/66.
- **STALLED:**
  - **C4 routing owner (miss).** Unrouted items went 59 → 166, the oldest is 156 d, and the row has sat `queued` for 7 d. Lane BACKLOG-DRAIN-20261104 is working the register today. If that lane names no standing owner, the manager kills or re-scopes the row on Thursday.
  - **C1 GLD wedge (unresolved, 5th review).** At 19:08Z today Alpaca still accepted the cancel without effect (`cancel_accepted_ineffective`). It needs a venue action; it stays with the operator as `ask_operator`.

## 1. CHECKS

| id | status | value (population) · prior |
|---|---|---|
| H1 | watch | Units active; heartbeat 24–33 s. Snapshots: 888 of 917 ok. **Max gap 172 min on 11-02 at 11:46Z.** · 10-28: max gap 15.5 min |
| H2 | ok | Running b129d38c5, which equals main; 0 src/config drift |
| H3 | ok | 8 of 8 broker-API accounts ok. ib_paper was not-ok for about 3 h on 11-03 (00:10–03:01Z). Manual-bridge prop accounts: `could_not_look` |
| H4 | **concern** | 2 FAIL, 3 not-measured, 6 pass. **TLT: 12,743 shares of stop rest against a 7,443 long, across 2 OCA groups.** MGC: journal 14 vs broker 11 (was 14 vs 12) |
| H5 | watch | 128 opens, 62 closes. Audit tail covers only 24 min (partial); 0 failures in it. 68 Bybit leverage-preflight failures appeared in 27 min |
| H6 | watch | SL 29 · TP 14 · sl_cross 4 · tp_cross 1 · strategy exits 10 · operator flatten 3 · netting_attributed 1 (#22894). 0 orphans; the positive control is readable |
| H7 | ok | 0 closed rows missing exit fields; 0 rows with inverted times. db_integrity log: `could_not_look` |
| H8 | watch | 5 of 5 ledgers fresh. news_decisions: `could_not_look` (same as 10-28) |
| H9 | ok | 39 of 39 research-health alerts delivered |
| H10 | **concern** | SLO breaches per day: 1, 0, 1, 0, 4, 7, 7, 7. survivors_per_month is 0. trials_per_survivor is 2,832 against a limit of 500 |
| H11 | watch | Timer active; last cycle rc 0; 122 builds, 0 failed. **Trainer disk 80.3% used** (10-28: 52%) |
| H12 | **concern** | Live VM 64.4% used, falling: the prune held. **Trainer VM: free space went from 41 to 20.5 GB between 11-03 and 11-04, so it reaches the 90% alarm around 11-05/06** |
| H13 | watch | 503 of 504 ssh windows read; 87 non-trainer accepts, all from one key (Xoek). Accepts were not matched to workflow runs; secret scanning was not run |
| H14 | ok | 127 of 1,599 commits touched Tier-2/3 paths. 62 are titled held or operator-approved; 3 of the untitled ones were sampled, and all 3 carry an operator record |
| H15 | **concern** | Gate 274 (prior 87); 577 due; **166 unrouted, alarm breached** |
| H16 | could_not_look | SOAKS.json (as_of 11-01) has no per-soak state; soaks were not graded |

## 2. ANALYSIS

**Trends:**
- Trainer disk is **accelerating**.
- Due items rose 110 → 577 across 5 reviews.
- Unrouted items tripled.
- Research breaches went from 1 to 7 per day starting 11-02.
- The MGC journal gap widened by 1 lot.

**Q1. TLT over-cover.**
- *H-instrument* (a double-count, as with MGC on 10-28) is eliminated. IB shows 4 distinct order ids in 2 OCA ids, all GTC:
  - group `1712634399`: LMT 7443 @87.57 and STP 5300 @79.41;
  - group `oca-protect-t6879`: STP 7443 @79.41 and LMT 7443 @83.59.
- If the 83.59 target fills, group 1712634399 is still resting and can sell into a naked short.
- Survivor (p 0.6, INFERRED): the naked sweep re-armed a full keyed group over a partial (5,300) bracket group and did not cancel it.
- `over_cover_proposal.py` returns `cancel_group`: keep `oca-protect-t6879` (it matches `trades.stop_loss`) and cancel orders 1232 and 1233.

**Q2. Trainer disk.**
- Noise is eliminated: journald holds only 342 MB.
- Trainer-diag #22919 shows `data` at 25 G and `datasets-out` at 12 G. That fits #22571, which made the trainer the ETF 1m store of record with HF lake publishing off.
- Two related items, PI-20261102-PTDVAI3R-0006 and PI-20261102-ARSESYNC-0001, are both queued with no owner. p 0.7.

**Q3. Leverage preflight.**
- A Bybit outage is eliminated: only equity and futures symbols fail.
- Cause, at code level (p 0.95): `src/main.py::_symbols_for_account` unions the symbols of multi-venue `ml_entry` and `claude_desk`. Each boot therefore makes 17 invalid calls, and restart churn multiplies that.

**Correlation:** one cause, restart churn, explains both the preflight noise and INV-EXIT-INTERVAL never accruing n (only 5 intervals since the last boot).

**Hunt:** I compared ERROR/WARNING signatures with 10-28; I read the newest 1,000 of 50,300 matches. New this week:
- the preflight failures;
- the TLT disjoint-OCA error;
- 1 bybit_1 SOL journal/broker divergence line. It was transient, and ADMISSION-JOURNAL-LAG-RACE owns it.

## 3. Decisions (ranked by money at risk)

| call | decision | tier | check | ending · due_by |
|---|---|---|---|---|
| C1 TLT over-cover (demo floor) | Manager: send `cancel-ib-order` for ib_paper orders 1232 and 1233, dry-run first, then root-cause the re-arm | 2 | INV-PROTECT-OVERCOVER passes | HEALTH-20261104-TLT-OVERCOVER · 11-05 |
| C2 trainer disk to 90% around 11-06 | Add retention on the ETF 1m store and `datasets-out`, or turn lake publishing back on | 2 | used_pct < 90 on 11-06, plus a retention change merged | HEALTH-20261104-TRAINER-DISK · 11-06 |
| C3 MGC journal drift | Root-cause from IB executions; repair through the sanctioned path | 2 | INV-JOURNAL-EXCHANGE passes | HEALTH-20261104-MGC-JOURNAL-DRIFT · 11-11 |
| C4 leverage preflight | Skip venue-foreign symbols in the preflight | 2 | 0 "symbol invalid" lines per boot | HEALTH-20261104-LEVERAGE-PREFLIGHT-EQUITY · 11-13 |
| C5 snapshot gap and ib_paper 3 h | Read the timer and gateway journals | 1 | max snapshot gap < 30 min | HEALTH-20261104-OBS-GAPS · 11-11 |
| C6 GLD wedge | Operator venue action (stalled) | 2 | GLD orders gone | PI-20260930-ZPDIPMDA-0001 · next review |
| C7 research SLOs red | Existing row; programme review today | 1 | breaches ≤ 3 | AUD-20261019-RESEARCH-SLO-RED · its due_by |
| C8 unrouted rising | Stalled; decided Thursday | 1 | unrouted alarm clear | HEALTH-20261028-PIPELINE-ROUTING-OWNER · 11-11 |

**Premortem.**
- C1: the cancel could hit the wrong group, which is the failure the 2026-08-20 incident recorded. That is why the selection comes from `over_cover_decision.py` and the dry-run comes first.
- C2: a retention change could delete a store-of-record partition that the backtests need. Compact or offload; do not delete.

## 4. Not done

- The open-set walk (§3c) was not run; 274 gate items are untriaged. BACKLOG-DRAIN-20261104 owns the register.
- H16 soak grading was not done.
- `run_secret_scanning` was not run, and collaborators and deploy keys were not re-read.
- Non-trainer ssh accepts were not matched to workflow runs one by one.
- The audit tail covers 24 min; the journalctl error sample covers 27 min of the window.
- The db_integrity log name was not found via diag.
