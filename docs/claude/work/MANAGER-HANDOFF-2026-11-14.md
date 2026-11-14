# Manager handoff — 2026-11-14 ~06:00Z

> **Doc status:** `historical` · category `history` · last verified `2026-11-14` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md)

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
