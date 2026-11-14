# Manager handoff — 2026-11-14 ~06:00Z

> **Doc status:** `historical` · category `history` · last verified `2026-11-14` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md)

## ⇢ ROTATION 2 — 2026-11-14 ~22:15Z (supersedes §§ 0-1 below where they differ)

Outgoing manager: `session_01AFoLuKXonDBdED7cNK7FhN` ("Manager Session 2026-11-13a"), context ~676k of 1M. **You** are the next
manager: title yourself `Manager Session 2026-11-14b` (or per the manager skill § "Start of session" step 1). You are a rotation
manager: read the manager skill's rotation sections plus this section. The morning sections below still hold where not changed here.

### First actions, in order
1. Invoke the `manager` skill. Then `set_session_title` to your Manager Session title (the lane stop hook #26097 skips a titled manager).
2. **Re-bind the 3 routines bound to the outgoing session** (`get_trigger` each, create a copy with the same name/cron/prompt and
   `persistent_session_id` = you, delete the old one, verify with `list_triggers`):
   - `trig_01MMBxEixhWuGEAfK56tkr1F` "Manager lane check-in (every 3h)" `17 */3 * * *`. **Edit its prompt's lane line:** ML = **ML-PRIMARY**
     `session_01AFoLuKuu4bMh6SG5oyAC9h` (replaces FRONTIER, archived), GENERAL = **AM-OPS** `session_01AFoLuJUGfpon2bNgwFbFmx`.
   - `trig_01UBxqicQ69CAfqYXooSzDsy` "Manager review (once daily 05:52Z)" `52 5 * * *`.
   - `trig_01M3fyN8n8wfxzqutfPq6y6R` "Refresh the decisions page" `10 5,17 * * *`. Its builders lived in the OUTGOING session's scratchpad,
     so rebuild them per its step 1 on first run; step 6 relays plan edits to the ML lane: change the target to ML-PRIMARY.
   The Assistant Manager's routines (weekly reset Wed 18:05Z, Thursday planning, research-ops 14:47Z, 12h lane check-in) find the manager
   by title: no change needed once you are titled.
3. `subscribe_pr_activity` on the ops-flags PR **#17895** (LTR wakes, desk wakes and alerts arrive there; never merge or close it).
   The outgoing session unsubscribes as its last act.
4. Send ML-PRIMARY and AM-OPS one trigger each naming you (`Manager Session ... (session_<you>)`) as their manager.
5. Tell the operator in one line that you are in control.

### Operator rules set or changed today (binding)
- **The ML lane is TOP priority and never stands down** (operator ~22:10Z, verbatim: "ML research is the top priority, and that is the lane
  that doesn't get stood down. Everything else gets paused before that. If we're down to one lane, other things can come into the work
  queue, but it should mostly be prioritized for ML."). Two lanes: **ML-PRIMARY** + **AM-OPS**. The outgoing manager wrongly stood FRONTIER
  down for usage at ~19:10Z (FRONTIER is archived; its open items are below). Do not repeat that.
- **ML plan for this week** (operator ~22:10Z): (A) the ML infra items queued and worked first; (B) a baseline ML **live on real money for
  most decision slots this week**, each at least not losing net of the full cost stack in a pre-registered Stage-0 backtest, with **D5
  (position aggregation) and D6 (bracket at entry)** the priority, D1 not important. ML-PRIMARY carries both; its brief has the detail.
- **Advice-only ended** (#25988): LTR rows that recommend an in-trade action apply automatically (rows watcher -> dispatch -> RiskManager ->
  venue read-back -> ping). First table-basis apply OBSERVED 18:07Z (pkg-d8838f, ETH prop SL -> 1934.5 breakeven).
- **tradeify_1 static-DD cushion stays REPORT-ONLY** (operator popup ~21:23Z, verbatim "Keep as is"; recorded #26135). Equity ~$9,613,
  floor $9,400; the open ETH short has SL at breakeven.
- **Trend alignment** (operator ~22:03Z): track it, don't gate on it. AM-OPS is dispatching RQ-20261112-8d20-02 (equity split) and building
  row TREND-ALIGN-LABEL-ALL (meta.trend_align on every order package, label only; a Tier-2 hold). The earlier studies (63af-01, 8d20-01,
  487c-01) all FAILED or were indeterminate: no evidence yet that counter-trend entries lose.
- **Pipeline map** (operator ~21:50Z): a map of the trading pipeline, technical side and trading side, GENERATED from sources of truth
  (config, the journal, the evidence records, the ML registry), shown on the UI Work tab, plus a weekly doc-freshness check (no new guard).
  Lane PIPELINE-MAP (`session_01AFoLuJEArj5fnhkwehXFPU`) was paused for the 2-lane cap: its WIP and state are on checklist row PIPELINE-MAP
  (owner AM-OPS). AM-OPS picks it up after its current items.
- Unchanged: usage is tight (weekly ~56% at 22:04Z, resets Wed 19:59; "run out Tuesday" at this pace). No Fable resets, never raise the
  usage-credits toggle, nothing spends API credits, no new gates, no orders by hand, demotions to the operator first.

### State at handover
- **Real money:** ml_entry (bybit_2) closed 7 longs at their SLs today (about -20.4 net) plus 1 TP (ADA short +2.94R); no ml_entry crypto
  position open. Evidence: +0.037 R/decision held-out (n 907, t ~1); not a demotion signal (reported to the operator ~21:10Z).
  **tlt_pullback_1h PROMOTED** to alpaca_live + alpaca_portfolio, long only, tp_r 3.5 (#26094, deployed + config observed 19:16Z). Its first
  live fill is pipeline item PI-20261114-TFZXAKEK-0003 (due Mon 11-16).
- **Deployed today and observed:** #25270 (venue net P&L is trades.pnl), #26098 (sweep stall fix + gap notes), #26118 (own-order-id match;
  7054 resolved), #26120 (mirror exclusions emptied), #26058 (close-alert est), #26078 (conflict alert R from initial risk), #26108
  (parity_ml flake fixed: main 29421/0), #26119/#26121 (mirror-orphan-watch green), #26097/#26099 (stop hook).
- **Open PRs for you:** #26137 (comms/gates excluded from trader restarts; Tier-2 hold, no trader restart; read the diff, check the decision
  line, merge on green). A one-shot reminder `trig_01Gn6ZYq36XiXX2PRmSq8KzD` (22:29Z) fires into the OUTGOING session; redo it yourself.
- **AM-OPS queue:** 8d20-02 dispatch -> TREND-ALIGN-LABEL-ALL (hold) -> PIPELINE-MAP -> MHG breaker watch (IB read failed after the 20:50Z IB
  blip) -> VENUE-PNL-ORDERID-MATCH (b) observation -> DIAG-EXCHANGE-POSITIONS-SLOW (due 11-19) -> LTR-PROP-PACKET-OPEN-R (due 11-20) ->
  ENTRY-FILL-WRITEBACK + ENTRY-FILL-BIAS-30D (due 11-18).
- **Ex-FRONTIER open items (now ML-PRIMARY's):** RM-AM-ETH4H-ENTRYTP (the powered prop-EV unit); qqq T1 dropped (db1a-11 weak PASS < the
  live config); db1a-12 retired; the eth_4h tp_r 4 line FAILED (db1a-09/13).
- **Live review:** dispatch ONE Sonnet catch-up lane per real-money/prop LTR wake (batch packages); the lane must COPY packet_sha verbatim
  (#26107). Prop packets are degraded (open_r null) until LTR-PROP-PACKET-OPEN-R. Desk wakes every 4h per the trading-desk skill § 6b.
- **Lessons from today:** (1) check a path's restart impact with `trader_import_closure.py decide` before asking a lane to commit (a
  comms/gates record restarted the trader, fixed by #26137); (2) never stand down the ML lane.


Outgoing manager: `session_01AFoLuKXonDBdED7cNK7FhN` ("Manager Session 2026-11-13a"). It is retiring because its context is past
the rotation point (~660k of 1M; skill threshold ~650k) and it sits at lineage depth 7/8, so lanes it creates cannot message it back.
**You** are the next manager: title yourself per the manager skill § "Start of session" step 1. Contract: `.claude/skills/manager/SKILL.md`.
You are a **rotation manager**; read per the skill's step 2. The previous handoff (`MANAGER-HANDOFF-2026-11-13.md`) still holds for
everything not changed below.

## 0. First actions, in order

1. Invoke the `manager` skill and read this file in full.
2. **Re-bind the routines** (§ 4) to your session: create a new trigger with the same name, cron and prompt, `persistent_session_id` = you,
   delete the old one, and verify with `list_triggers`. Read each prompt with `get_trigger` first.
3. `subscribe_pr_activity` on the ops-flags PR #17895 (never merge or close it).
4. Send AM-OPS and FRONTIER one trigger each naming you as their manager.
5. Record `last_review` for the 2026-11-14 05:52Z review (report `WR-20261114-0530Z`, present, no errored sections, no incidents; the
   outgoing manager did not land it).
6. Tell the operator, in one line, that you are in control.

## 1. Standing operator rules (all binding; unchanged unless noted)

- **TWO lanes total** (operator 2026-11-13, re-affirmed ~22:10Z with a usage screenshot: weekly 39%, "run out Tuesday"): ML =
  **FRONTIER-RESEARCH** (`session_01AFoLuMfGoUaVmVtfzXaKEK`, owns the whole ML queue) and GENERAL = **AM-OPS**
  (`session_01AFoLuJUGfpon2bNgwFbFmx`; ops, trading, devops, security, UI observation, backlog). AM-ML and AM-UI were archived 22:41Z.
  Spawn nothing else except a catch-up LIVE-REVIEW lane or a desk wake.
- **Desk wakes every 4h** (operator verbatim "Move desk wakes to every 4 hours"; #25861; observed: markers at 00:00Z and 04:00Z only).
- **Live-review routine PAUSED** (operator popup "1, but you pause it"): `LIVE_REVIEW_ROUTINE_ID` unset on the VM (#25869, 23:13Z), observed
  04:01Z. Every real-money/prop ltr-wake now says "Manager: dispatch": dispatch ONE Sonnet catch-up lane per wake (batch packages; send a
  follow-up event for the same package to the lane already on it). Resume = `set-env LIVE_REVIEW_ROUTINE_ID` once the operator attaches
  the repo to the routine.
- Read back and commit every Decisions-inbox answer; check the transit log every check-in. Tier-2 PR bodies carry
  `decision: 2026-11-12 operator-popup "Merge + deploy on green"`. Read every Tier-2/3 diff; merge at the reviewed head; wait for the full
  pytest-run (the `test_live_replay_parity_ml` flake is known, PI-20261113-B38CQPVI-0003).
- **Batch merges that restart the trader. Any merge touching `src/`, `config/`, `deploy/` or `scripts/ops/` restarts it via git-sync**
  (learned 2026-11-13: #25861 config-only and #25901 scripts/ops each restarted it).
- Demotions and retirements go to the operator first. Wake the operator only for money at risk. No orders by hand. Nothing spends API
  credits. No new gates. Never raise the usage-credits toggle. No secrets, IPs, account ids, balances or emails in the repo.
- Phone app retired. breakout_2 on ice (its armed DD switch reads could_not_look: ACCEPTED, gates nothing). Fable resets not used this week.

## 2. Tooling notes

- Merge with `mcp__github__merge_pull_request` (lowercase server); `mcp__Github__*` returned 403. Procedure: touch the claim file, POST
  `pulls/<n>/ccr/ready_for_review`, squash with `expectedHeadSha`.
- Lane self-land PRs that are already clean will not arm auto-merge; lanes send the head sha and you merge.
- Lanes you create sit at depth 8 and cannot `create_trigger` back to you: read their `post_turn_summary` instead.
- Desk wake: `create_session` per trading-desk SKILL § 6b (source_revision/outcome_branch `desk/decisions`, clone_depth 1, sparse
  `.claude/skills/trading-desk`, Sonnet, the verbatim WAKE PROMPT). Archive when done.

## 3. Open threads

**Waiting on the operator (morning):** 4 checklist rows flagged waiting-on-operator, incl. GATE-REMOVE-RUNTIME (tier-3, past due_by).
Stale "unanswerable operator edges" (E75, ANDROID-8001-HTTPS, RQ-NEW-UNIT-SELF-LAND, VELOTRADE-API-EXEC, CI-AUTOMERGE, DEMOTE-T3) are already
decided or obsolete: clear their tags.

**Operator decisions answered overnight (committed on their items):** live-review routine pause (done); DESK-18D-JUDGE-2 "Build universe
next" (#25873 + #25882 merged; unit RQ-20261113-d18c-01 screening ~4h on the runner; AM-OPS grades); bybit_2 wallet truth "Keep trying
later" (RECON after the reset).

**Deployed, awaiting observation (AM-OPS owns):** #25856 Alpaca amend race (next Alpaca trail modify, ~Monday); #25924 DB-lock async
dual-write + #25935 LTR candle files (deployed 04:54Z; 24h lock read 11-15 05:10Z, next crypto review). **Observed and closed:** #25855
10006 backoff, #25853 eth/sol 4h closed bar (FORMING-VS-CLOSED-ETH4H-SOL4H closed done), #25869 routine pause.

**FRONTIER research (no live change from any of it):**
- Rounds 1-3 of DEMO-FLOOR-ITER: every lever FAILED net of cost on the record window. Diagnosis db1a-01: `decision_bar: closed` is NOT the
  lever; the inversion is the WINDOW (5/10 lever deltas flip sign year on year), so no more per-leg single levers on htf / eth_prop /
  avax_pullback_2h / avax_4h on this window.
- **RQ-20261114-db1a-02** (regime-level, 15 crypto legs, Part A common-loss + Part B walk-forward ADX x direction cell) dispatched 05:35Z,
  ~30-45 min. A pass is a pointer to the 2-D walk-forward, not Tier 3.
- **#25944 (HELD, Tier 3): avax_pullback_2h retirement.** Goes to the operator ONLY if db1a-02 does not rescue the leg (Part B pass AND
  ex-cell net > 0 on both windows). Do not merge without the operator.
- turtle_soup: latent re-entry defect (re-emits the stale package for 4 bars; PI-20261114-TFZXAKEK-0002 open, no fix proposed; the leg has
  never filled live). tlt / ada_4h parked; htf (c) on hold.

**Mirror-orphan-watch:** the 11-13 21:35Z red predates #25857; AM-OPS checks the next run (~21:30Z 11-14).

## 4. Routines bound to the outgoing session (re-bind these)

| Name | Trigger | Schedule |
|---|---|---|
| Manager lane check-in (every 3h) | `trig_01MMBxEixhWuGEAfK56tkr1F` | `17 */3 * * *` |
| Manager review (once daily 05:52Z) | `trig_01UBxqicQ69CAfqYXooSzDsy` | `52 5 * * *` |
| Refresh the decisions page (twice daily) | `trig_01M3fyN8n8wfxzqutfPq6y6R` | `10 5,17 * * *` (builders live in the outgoing session's scratchpad; in a new container rebuild per its prompt) |

The check-in prompt's watch list (d) still names AM-ML as owner of several post-deploy watches: those belong to FRONTIER now; rewrite it
when you re-bind.
