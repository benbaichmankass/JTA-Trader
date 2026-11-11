# Thursday planning 2026-11-11: read-backs for the manager's decision docs

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-11` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes: none.** Read-only evidence for decisions the operator asked to see before deciding.

The operator answered the 2026-11-11 Thursday-planning decision doc between 21:28Z and 21:41Z. Four answers asked for evidence before deciding,
and one asked for a root cause. Lane thursday-planning (session_01AFoLuKfMTNHddXSQPZkuGh) gathered each one. Each section ends with the question
for the manager's next decision doc. Numbers are MEASURED where a read is named, and INFERRED otherwise. Populations are stated in each section.
Rows: a5 ML-ENTRY-LIVE-MONITOR · b5 TPX-XRP-DECLARE · e6 MIRROR-QTY-DIVERGE · b1 PROPOSAL-ALERT-ROUTING · e2 (per-item notes).

## a5 — Live ml_entry on bybit_2: mirror demotion read and DSR (Tier-3 read)

Operator choice, verbatim: "Run the mirror demotion read and DSR first (Tier-3 read), decide after".


### Tooling found
- Demotion gate: `scripts/ops/r4_demotion_gate.py` (MD-DEMOTE-S2-S1; rule "T3 AND net<0": last 40 closed trades as two 20-trade windows, both below the leg's Stage-0 bootstrap p10 AND below 0; abstains under 40 trades or with no committed Stage-0 source). Operating plan § 2 says the mirror "demotes when net-negative net-of-cost over a declared window" and that DSR alone never demotes (HOLDOUT governs; DSR = probation, 2026-11-06).
- DSR: `scripts/research/trial_ledger.py::dsr/haircut`, `scripts/research/dsr_probation.py`.
- Strategy: `ml_entry` (config/strategies.yaml, execution live); rostered on bybit_2 + bybit_portfolio (accounts.yaml:483, 891); also alpaca_paper, breakout_2/tradeify_1/velotrade_1 (ETH+SOL). account_symbols for bybit_2/bybit_portfolio: BTC, ETH, XRP, ADA, SOL. Kept live by the operator exception 2026-11-06 ("Move all but ml_entry (Rec.)").

### Commands run
- `curl https://ict-bot.duckdns.org/api/bot/performance/recent?n=40` (no token needed; HTTP 200) -> recent2.json
- `curl .../api/bot/trades/closed?limit=200&account_id=bybit_2|bybit_portfolio&include_paper=true` (200)
- `python3 scripts/ops/r4_demotion_gate.py --recent-json recent2.json` (dry run, writes nothing)
- `python3 scripts/research/dsr_probation.py`; `trial_ledger.dsr()` on `comms/research/PROD-LEGS-DSR-DECISION/ml_entry_armF_trades.jsonl`
- Read `comms/research/ml_entry_grade/42473814600/grade_evidence.json`, docs/research/ml-lane-grades-2026-11-08.md

### Mirror net-of-cost window (MEASURED)
Population: `ml_entry`, bybit_portfolio (mirror), all 12 closed trades available, 2026-11-02..2026-11-11 19:00Z, ledger-measured pnl (coverage 1.0), R coverage 1.0 (7 of 12 R bases "unverified").
- Mirror: n=12, 6 wins, **net +5.87 R (+0.489 R/trade)**, PF 2.27, 3 TP exits.
- Real money bybit_2: n=12, net +4.96 R (+0.414 R/trade), PF 2.04, 4 TP / 6 max_hold. bybit_2 journal is `known_divergent` vs wallet (R and pnl are journal-side, not wallet truth).
- Same 12 trades on both books; R is net of the harness cost stack as recorded in the journal. Mirror $ not quoted.
- Concentration (mirror, per-symbol trades): ADA 4 (3 wins), SOL 3 (1), ETH 2, XRP 2 (0), BTC 1. 3 TPs came within 11-08 21:47-21:54Z (one move, as the decision doc says).
- Sides (mirror, MEASURED, pnl% only, no per-trade R exposed): longs n=3, 0 wins, -4.73% summed; shorts n=9, 6 wins, +7.40% summed.
- Registered rule result: R4 gate ABSTAINS (abstain_thin, n=12 < 40; and "NO USABLE STAGE-0 EVIDENCE": comms/strategy_evidence/ml_entry.json cites source_run research/results/RQ-20261103-5e04-01/41823438321.jsonl, which is not a committed file, so the p10 threshold is never guessed). No demote. Even a 40-trade read would need both 20-trade windows < p10 and < 0; the window is currently positive. Mirror is NOT net-negative: the registered demotion trigger has not fired (MEASURED). Gate defect to fix regardless: the evidence record points at a non-committed file, so this leg can never be demoted by the gate (INFERRED consequence).

### DSR (MEASURED, held-out year, frozen model, arm F live exit)
Population: n=907 served entry trades, 5 bybit_2 symbols, 2025-10-01..2026-09-30; mean +0.0371 R, SD 1.143, skew 0.87; re-measured series committed at PROD-LEGS-DSR-DECISION.
| N trials | DSR |
|---|---|
| 1 (ledger rule) | 0.839 |
| 2 | 0.679 |
| 3 | 0.550 |
| 5 | 0.414 |
| 11 (window reads) | 0.257 |
t=0.98, p_single=0.328; BHY haircut expectancy +0.037 R. Fails 0.95 at every N; PSR with no deflation is also only 0.839. `dsr_probation.py` lists ml_entry as `not_computed` (ledger has no series), so the standing C13 view is blind to it (gap). Per policy DSR is probation only and never demotes.
Note: the "held-out +0.0085 R (t~0.24)" in the decision doc is a different population (frozen v1, all-symbol, 14-day windows, n=11,253 both-side +0.0071 se 0.0104, t~0.7 per ml-lane-grades 98e3-25), not this 907-trade series; I did not reproduce +0.0085/t 0.24.

### Longs vs shorts
- Replay (14d to 2026-11-07, served v1r20261106, tau 0.10, 48 symbols; MEASURED from grade_evidence.json): n=317, mean -0.1316 R (SE 0.060, CI95 [-0.258,-0.007]); mean cost 0.070 R; **long n=51 -0.904 R; short n=266 +0.017 R**. Ex the top symbol -0.113.
- Held-out year, same frozen v1 (98e3-25, n=11,253 decisions, 60 symbols): long +0.032 R (n=3,500), short -0.004 R (n=7,753); long-only +0.0318, short-only -0.0034. Verdict "side-window-specific"; no side filter opened. So the -0.90 long loss is one 14-day window (n=51).
- Live (mirror): longs 0/3, shorts 6/9 (above).

### Overall (INFERRED)
No registered demotion rule has fired: mirror window positive but thin (n=12, one move drives the TPs), gate abstains, DSR fails but is not a demotion rule, replay is negative but a replay alone never demotes. Edge is statistically indistinguishable from 0 (t 0.98 over 907; replay -0.13 R mostly from 51 longs). The evidence cannot support "keep because it earns" or "remove because it loses"; only fixing the gate evidence and a 40-trade read will.

### DECISION-DOC QUESTION
**Title: Live ml_entry on bybit_2: keep, narrow, or step down to paper?**
Evidence:
- Mirror (bybit_portfolio), 12 closes since 11-02: +5.87 R net of costs, 6 wins; three TPs came from one 11-08 move. The registered demotion rule has not fired (gate abstains at n=12 of 40; its evidence file is not committed).
- Frozen-model held-out year (n=907): +0.037 R/trade, t=0.98, DSR 0.84 at N=1 (0.26 at N=11). Statistically zero; probation, not a demotion trigger.
- Latest 14-day replay (n=317): -0.13 R/decision, all of it from 51 longs (-0.90 R); shorts +0.017 R. Over the full year longs were slightly positive (+0.032 R), so this looks like one bad window.
- Live longs: 0 of 3 won; shorts 6 of 9.
Options:
1. (Recommended) Keep both sides live; fix the gate evidence and set a 40-trade checkpoint. Reason: no registered rule has fired and the doctrine says replay alone never demotes; the year-long side study found no persistent long weakness; the fix (commit the evidence file so the gate can run) is Tier 1, and the gate then decides at 40 closes.
2. Keep live, shorts only until the checkpoint. Reason: caps the exposure to the side that lost in the replay, but the year-long side test said no lever (short-only -0.003 vs both +0.007), so it removes the part that was positive over the year; this is a Tier-3 change on a one-window signal.
3. Step down to bybit_1 (paper floor) now. Reason: cleanest if you read t=0.98 / DSR 0.84 as no proven edge, but it overrides the operator's 2026-11-06 baseline exception and the demotion rule, with the mirror positive.


## b5 — xrp_pullback_2h take-profit declaration (X31): the evidence

Operator choice, verbatim: "Ask for the evidence first".


Gathered 2026-11-11, read-only. Operator said "Ask for the evidence first". This is the evidence.

### Headline

- The X31 declare is **already in `config/strategies.yaml` on main** (line `tp_revision: {rule: tp_extend, extend_r: 1.0, approach_frac: 0.85, max_extends: 3}`, MEASURED by reading the file). The checklist row `TPX-XRP-DECLARE` still says "blocked" and was last updated 2026-11-06, so the row is stale on that point.
- I did not check whether the running trader has it loaded now. The row's own note says a 2026-11-05 read showed the loaded config held the declare.
- The leg no longer trades real money. On 2026-11-06 (decision PROD-LEGS-DSR-DECISION) it was removed from `bybit_2` and `bybit_portfolio` and now trades only on the `bybit_1` demo floor. So the original reason (real-money compliance) has changed.

### What the leg declares now

- Entry take-profit: fixed 3R (`tp_r: 3.0`), venue cap 9.9 percent. The guard reads it as "declared" and reachable (reach 0.246, so about 25 percent of backtest trades touch 3R; floor is 10 percent).
- Moving take-profit: the tp_extend rule above. When price gets within 85 percent of the target, the target moves out by 1R, up to 3 times.
- Guard output today for xrp_pullback_2h (only routing left is `bybit_1`): entry_tp declared, producer `produces_tp_verdict`, path `plumbed`, verdict PASS. Its "intent" column still prints `undeclared`; I did not trace why. Flag for the guard owner.

### What the proposal would declare

Exactly the same line. X31 means: anchor 3R, extend 1R, approach 0.85, max 3 extends. It is the same cell the earlier family read called X6. Revert is to delete the one line.

### What evidence exists

1. **Held-out test, RQ-20261104-c6f1-02** (queue file `research/queue/RQ-20261104-c6f1-02.yaml`, results `research/results/RQ-20261104-c6f1-02/local-20261104.jsonl`).
   - Harness: `scripts/research/exit_lever_ablation.py --grade holdout`, XRPUSDT 2h, 2020-07-01 to 2026-11-03.
   - Cost stack: fee 11 bps round trip, slippage 3 bps, funding 1 bps per window. This is net of the full stack.
   - Rule registered before the run (2026-11-04): pick the best arm on the early span only, read the later 25 percent once, pass only if it beats the current 3R exit on that later span.
   - Result: PASS. X31 won discovery (12.47 R vs 11.10 R for the current exit, n 303). On the held-out span X31 made **14.65 R vs 14.28 R**, n 94, tp_share 0.33.
   - Negative control (extension switched off) matched the baseline exactly. Harness label: confirmed.
2. **Family read, RQ-20261022-bea9-01/02/04** (record `docs/research/evidence/tpx-xrp-family-read-2026-10-22.json`): the same cell passed on 3 of 3 sibling legs (eth, sol, avax). That says the idea transfers; it is not xrp evidence.
3. Whole-window numbers, n 397: X31 27.13 R vs current exit 25.38 R.

### Honest reading of how strong it is

- The gain is small: +0.37 R over 94 held-out trades (about 0.004 R per trade) and +1.74 R over 397 trades whole-window.
- Only a handful of trades change at all (take-profit exits 154 vs 155, stops 206 vs 205). One arm, X305 (extend 0.5R), scored the identical held-out 14.65 R.
- The unit's power design (38.8 trades for a 0.45 sd effect) is for a large effect. It was not built to prove a 0.37 R difference. I found no significance test on the paired gain. Treat it as "does not hurt, may help slightly", not as proven edge.
- The harness itself warns that the raw flags are not in the config fingerprint, so the record cannot be bound to a config hash.
- The leg's own entry rules were tuned on windows that overlap both spans (stated in the unit).

### What is missing

- Any live read of the extension: first package carrying `tp_revision`, first trade update with reason `tp_extend`. The row's monitor step. I did not find this observed.
- Live closed-bar trades: the operator wanted at least 2 after 2026-10-22. The row counted 1 as of 2026-10-28; I did not recount.
- Confidence interval or paired test on the +0.37 R.
- A fresh DSR read: the leg failed DSR on 2026-11-06, which is why it left real money.
- Confirmation of the deployed state today (merged is not deployed is not observed).

### DECISION-DOC QUESTION

**Title:** Keep the xrp_pullback_2h take-profit extension (X31) on the demo floor?

**Evidence:**
- X31 passed a pre-registered held-out test net of full costs: 14.65 R vs 14.28 R for the current exit, n 94 (RQ-20261104-c6f1-02).
- The edge is tiny (+0.37 R, about 1 trade changes outcome) and has no significance test; the same cell passed on 3 of 3 sibling legs.
- The line is already in main; the leg left real money on 2026-11-06 and trades only on `bybit_1` demo.
- No live trade has yet shown a `tp_extend` update.

**Options:**
1. Keep the declare as is, watch the first live extend, close the row once one is seen. (Recommended.)
2. Keep it, but first run a paired significance test on the 397 trades and decide only if the gain is clear.
3. Remove the line and go back to a plain 3R target until the leg re-qualifies for real money.

**Recommendation: option 1.** It is a demo-floor leg now, so the money at risk is nil, the revert is one line, and the guard already reads the leg as compliant. The live observation is the evidence still missing, and only running it produces it.


## e6 — PR #24892 (mirror top-up size-up): plain summary for review

Operator choice, verbatim: "Review it with me first". The PR is NOT merged.


Branch `general/topup-size-up`, read from `git diff origin/main...origin/general/topup-size-up`. Nothing merged or commented.

### What it changes, in plain words

- When the system wants to add a little to a position and the add is smaller than the exchange's smallest allowed order, it used to throw the add away (logged as `intent_sub_min_qty_delta` or `intent_sub_min_notional_delta`).
- Now it rounds the order up to the smallest legal size and places it. The combined position then slightly overshoots the target.
- Case that triggered it: 2026-11-10 04:02Z, a `bybit_2` ml_entry ADA short top-up was dropped. The mirror then did not match.
- It follows the 2026-11-09 entry rule "size up, that's what trading at minimum size means" (#24596). Operator approved this extension by popup 2026-11-10 ~06:45Z "Size up top-ups too".

### What is not changed

- Reduce, close and flip orders are untouched. A too-small reduce stays a no-op, so a close is never rounded up to cut more than asked (there is a test for this).
- Pairs legs are untouched.
- The code change is one block, 38 lines, in `src/core/coordinator.py`. It uses the existing `legalize_qty(..., size_up=True)` helper, which is already on main.

### Accounts and books affected

- Any account on the intent-mode path where an opening top-up comes out below the venue minimum. The PR names `bybit_2` and `bybit_portfolio` (the mirror, which now follows the primary instead of being left behind).
- I did not trace which other accounts (Alpaca, IB, prop) use this path, nor their minimums. Not verified.
- Landing is marked Tier 3, hold: "the merge/deploy is the manager's on that approval". Operator said builds should wait until after the reset.

### Money risk

- Worst case when the size-up is wrong: each affected top-up places a bigger order than the target asked for.
- The overshoot is capped by the venue minimum itself: the bump goes to the smallest step-aligned size that meets the minimum quantity and the minimum order value. The PR's own test says "overshoot is bounded to one lot". Typical minimums in the tests are 0.001 BTC, 0.01 ETH and about 5 dollars of order value on XRP.
- There is **no separate multiplier cap or dollar cap** in the new code. The bound is the venue minimum, not a rule of the bot. If a venue's minimum is large for an expensive symbol, the overshoot is large. I did not check the live minimum per rostered symbol.
- If the venue maximum is below the needed minimum, the helper refuses (`venue_max_below_min_qty`) and the old path continues.
- If the lookup fails the code falls back to the old behaviour (try/except), so a failure drops the top-up as before.
- Repeat risk: the next tick compares the position with the target, and the position now exceeds it, so a reduce delta would follow; sub-minimum reduces are no-ops. I did not run this loop live. Per-trade `RiskManager` checks downstream were not reviewed in this read.
- The change is recorded in the package: `execution_delta.qty_resize` holds from, to, binding and outcome `qty_sized_up_to_venue_min`, and a warning is logged.

### Tests

Changed or added tests, 3 files:
- `tests/test_intent_delta_dispatch.py`: the old "dust is a no-op" tests for BTC and ETH now expect a sized-up order (0.001 and 0.01); a new test shows a sub-min reduce is still a no-op and never resized.
- `tests/test_mirror_pairs.py`: the 0.4 XRP top-up worth under 5 dollars is sized up to at least 5 dollars of value, and the mirror now follows.
- I did not run the tests or look at CI status (the GraphQL route is blocked in this session).

### DECISION-DOC QUESTION

**Title:** Approve PR #24892, sizing up sub-minimum top-ups?

**Evidence:**
- Operator popup 2026-11-10 "Size up top-ups too" already approved the behaviour.
- Overshoot is bounded by the venue's own minimum order; reduce, close and flip are untouched and tested.
- Triggering case: bybit_2 ADA top-up dropped and the mirror left behind.
- No separate dollar or multiple cap exists in the code.

**Options:**
1. Approve and merge as is, after the reset. (Recommended.)
2. Approve with a cap: skip the size-up (old drop) if the bumped order is more than a stated multiple of the wanted delta, or above a dollar amount.
3. Reject and keep dropping sub-minimum top-ups, accepting mirror divergence.

**Recommendation: option 1.** It matches an operator approval already given, the bump is no larger than the exchange minimum, and it fixes the mirror divergence. Choose option 2 only if you want a hard bound; to set it we first need the live minimum order value per rostered symbol.


## b1 — Why the ready promotion proposals sat unacted since 11-04 with no alert

Operator note, verbatim: "We need to make sure these proposals don't stay una Ted on, why aren't you getting an alert when the proposal is ready to send me the decision?" The fix is row PROPOSAL-ALERT-ROUTING.


Population: row PROMOTE-1H-SURVIVORS-20261104 read from the live work store 2026-11-11. Code read at local HEAD 279aee225.

### What the row actually is
- kind `build`, state `queued`, **owner `manager`**, **tier 3**, due 2026-11-06 (5 days overdue), no `next_action`, no `blocked_on`.
- It is NOT a pipeline `observation` item and has no `ask_operator` field. Its note says "any that do not come back to the operator" and lane result "NO leg cleared every check". The hand-back to the operator is prose in a `note`, not a structured routing field.
- (Substantive status: all three legs fail tp-doctrine-guard; USO closed by operator; SLV/QQQ wait on units RQ-20261104-7fdb-01/-02, SLV `not_before 2027-03-16`. So nothing was "ready to send" in the gating sense. The failure is that nothing routed or flagged it either way.)

### The exact break (three independent holes, all on the same path)
1. **Push path keys only on pipeline `ask_operator`.** `scripts/ops/attention_watch.py:1` docstring, `open_ask_operator` (line ~192: `next_action == "ask_operator"`), edge push at `plan_messages` (line ~965 "new decision(s) for you (ask_operator)"). A checklist/build row can never match it.
2. **Brief section 2 lists only owner containing "operator".** `scripts/ops/render_daily_brief.py:376-377` (`_is_operator_owned`) and `:380-388` (`decisions_for_you`). Row owner is `manager` (checklist DEFAULT_OWNER, `src/runtime/checklist_store.py:40`), so a Tier-3 row waiting on the operator is excluded by construction.
3. **Section 0 counts overdue build rows but never names them.** `render_daily_brief.py:245-250` prints "N overdue build row(s)" only; the list below it (`ranked_items`, :218-222) is built from observations only. `src/runtime/work_read.py:105-118` carries `due_now_builds` as ids that no renderer prints.

No promotion-specific producer exists either: `scripts/ops/run_promotion_readiness.sh` is the ML-model sweep (pings via pending_pings, default-DISABLED service) and is unrelated to strategy-leg promotions; `mandate_resolver.py` (MD-PROMOTE-S1-S2, NEEDS_DATA) only evaluates on invocation. No scheduled job turns "lane finished, operator must decide" into a record the three readers above can see.

Secondary (UNVERIFIED on the VM): `attention_watch.build` (line ~861) reads `pipeline.load(REPO_ROOT/pipeline.STORE)`, the file export, while the brief reads the work store. Health PR #24963 reports the export frozen since 11-06 (4,098 files vs 4,211 store items). If the VM tree's export is equally stale, even a correctly filed `ask_operator` item written through `work.py` after 11-06 would not alert. Check before relying on it.

### Fix (routes and alerts only; blocks nothing; no new gate)
Define one derived predicate, `awaits_operator(item)`, structured fields only (no prose matching), true when the item is non-terminal AND any of:
- `next_action == "ask_operator"` (existing);
- owner names the operator (existing);
- `tier >= 3` and (`is_overdue` or `blocked_on` has kind `operator`);
- `blocked_on` contains `{kind: operator}`.

Then use it in three places, all read-only projections:
1. `scripts/ops/render_daily_brief.py::decisions_for_you` and section 0: include rows matching the predicate; print overdue build rows by id (top N, rest counted) instead of a bare count.
2. `scripts/ops/attention_watch.py`: replace `open_ask_operator` source with the predicate over BOTH stores (read the work store via `src/runtime/work_read.py`, fall back to files and say which), keep edge-triggering (`seen_ask_operator`) so each newly awaiting item pings once, and add a re-alert every `REALERT_HOURS` for an item still awaiting after 48 h (an alert, not a block).
3. `src/runtime/checklist_store.py`: add the shared `awaits_operator` helper so both readers import one definition (`checklist-readers-guard` already forces readers through this module).
Producer side (no gate): in the lane close-out skill text (`.claude/skills/close-out/SKILL.md`) and `scripts/ops/checklist.py note`, a lane that hands a decision back sets `blocked_on` kind `operator` (a structured edge) rather than prose.

### Test
`tests/test_render_daily_brief.py` (+ a case in `attention_watch --self-test`): fixture rows (a) tier-3 `manager` row overdue, (b) tier-1 `manager` row overdue, (c) done tier-3 row, (d) `blocked_on operator` row. Assert (a),(d) appear in `decisions_for_you` and in `plan_messages` output exactly once across two passes (edge-trigger), (b),(c) do not; assert an overdue build row id is printed in section 0; assert nothing in the module raises or returns a non-zero exit (non-blocking). Positive control: the real PROMOTE-1H row must be selected from a snapshot of its JSON (`docs/claude/work/checklist/PROMOTE-1H-SURVIVORS-20261104.json`).

Gates this adds or changes: None (alert/render only).


## e2 — Triage of the 15 unowned backlog items (done; reported here)

Operator choice, verbatim: "Manager triages: own or kill each, report back". Applied in the work store on 2026-11-11: 8 owned and 6 killed, each with a terminal_reason.


### Where 15 comes from
`python3 scripts/ops/review_followthrough.py --source performance-review` prints `backlog ... no-owner 15` (MEASURED here 2026-11-11 over 2700 pipeline items + 1398 checklist rows in the local export). In that script (`review_followthrough.py:40-42,148,187`) "no owner" means an open pipeline item that is `queued` (never routed) or routed to an unresolvable owner. The work-store `owner` label on those items is NOT what is tested, so 12 of the 15 carry a label (manager / perf-followup / ml-review ...) and are still counted. It is a routing gap, not a blank field. Population is the performance-review source bucket only; the work store also holds ~24 genuinely `unassigned` BUILD rows (separate, not triaged here, e.g. TP-PREDICT-GRADER, ML-HYGIENE, CI-PLAYWRIGHT).

Today is 2026-11-11; "next 2 weeks" = due by 2026-11-25. Ages are days since filing per the tool.

| # | id | age | what it would take | action |
|---|---|---|---|---|
| 1 | SRQ-20260715-REALMONEY-ALLOC-BENCHMARK | 119d | benchmark script must emit a read-state ("not computable: N alpaca_live closes") each review instead of nothing; recurring watch afterwards | OWN perf-followup (Track 4), 11-25 |
| 2 | PRB-20260720-OPTIONS-PORTFOLIO-GRADUATION | 114d | alpaca_options_paper has 0 open positions, no options leg closed in 30d; nothing to assess | KILL (re-file when a closed options trade exists) |
| 3 | PB-20260906-R-CONTAMINATION-QUANTIFIED | 66d | superseded: reviews now quote the API's `declaredInitial` R basis (perf review 11-11, Q2 H-measurement) | KILL |
| 4 | BL-20260908-THE-GLD-COMPAT-MATRIX-GRADES-RISK-PCT | 64d | compat matrix verdict ignores account size (alpaca_live ~$200 cannot buy 1 GLD); add affordability term + test | OWN build lane, 11-25 |
| 5 | BL-20260911-LOSING-STREAK-SIZE-GATE | 61d | per-account relative floor for the losing-streak detector (alert only, Tier 1) | OWN build lane, 11-25 |
| 6 | BL-20260912-NETTING-ATTRIBUTED-PATH | 60d | netting_attributed is now 1 of 101 real-money decision closes (perf review C4, 11-11), no longer the largest share | KILL |
| 7 | BL-20260913-NETTING-ATTRIBUTION-REWRITES-POSITION-SIZE | 59d | confirm on main that the PARTIAL branch still rewrites size on an open row; if so persist a marker + test (Tier 2 if it touches the close path) | OWN build lane, 11-25 |
| 8 | BL-20260913-EVERY-PROFITABLE-LEG-SIZED-SMALLER | 59d | re-measure dollars-of-risk per R on the current six real-money legs (roster changed 11-06); attribution only, no resize | OWN perf-followup Track 4, 11-25 |
| 9 | PI-20261028-PVRNY2JI-0001 | 14d | already `dropped` in the store at read time | none (closed) |
| 10 | PI-20261028-PVRNY2JI-0004 | 14d | already `done` | none (closed) |
| 11 | PI-20261028-PVRNY2JI-0005 | 14d | already `dropped` | none (closed) |
| 12 | PI-20261104-PREP1104-0001 | 7d | per-trade net_r rows for ml_entry/ml_entry_eq_struct harnesses; already carried by PI-20261111-PREP1111-0001 | OWN perf-followup, 11-18 |
| 13 | PI-20261104-PREP1104-0002 | 7d | action already landed as AUD-20261104-FLATTEN-LABEL (d74a17429) + invariant | KILL |
| 14 | PI-20261104-PREP1104-0003 | 7d | live_review_grade.py calibration strata count packages not reviews | OWN build lane, 11-25 |
| 15 | PI-20261104-PREP1104-0004 | 7d | realized_slippage.py `analyze` KeyError net_r (C5 void) plus the bearer-in-traceback leak (PI-20261111-PREP1111-0002); one fix | OWN build lane, 11-18 |
| + | RESET-JOBS-20261104 (checklist, in_flight) | 7d | COMPLETE receipt written 2026-11-04 20:02Z; all 9 jobs dispatched, their outputs landed (11-11 PRs #24953/#24954/#24963/#24940 are the next cycle) | KILL as done |
| + | PERF-REVIEW-W41 (checklist, landed_unproven) | 32d | PR 17442 is MERGED (2026-10-10); the graded-ticket observation cannot resolve (ticket not in /prop/fills, PI-20261011-MJ5KSFIO-0001); three later reviews supersede it | KILL as done |

Counts: 14 actions = 8 OWN, 6 KILL, plus 3 already closed (rows 9-11) that need nothing. The 12 live items of the 15 plus the 2 named checklist rows.

