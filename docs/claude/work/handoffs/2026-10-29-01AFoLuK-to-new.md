# Manager handoff 2026-10-29: session_01AFoLuKwNMzjtn2CH2kVd86 (Manager Session 2026-10-29c) → new (2026-10-29d)

> **Doc status:** `unknown` · category `unknown` · written 2026-10-29 ~21:50Z by the outgoing manager. The reason for the rotation is context: 725k of 1M tokens, past the ~650k rule.

## 1. Capacity
- **Weekly usage:** 35% at 21:37Z. It resets Wed 2026-11-04 18:00Z. The reading was recorded with spend_meter in PR #21412, which has automerge armed.
- **Rate:** about 12 pp/day measured, against 11.1 pp/day sustainable gross. Net of the live-review reserve (28.5 pp) the rate is 6.2 pp/day, so the meter says **KEEP 1 LANE**.
- **Refill routine cap:** 2 build lanes.
- **Model:** prefer Sonnet; use Opus only on an order path.
- ⚠️ **Never raise the claude.ai "usage credits" toggle.** It is not a concern (operator, 2026-10-29; now in CLAUDE.md and canonical).

## 2. Live lanes (id → row → doing → owes)

**Build lanes**
- **session_01AFoLuLpoWiu1SEu6vTJpKk**, row COUNTERFACTUAL-EVERYWHERE.
  - Doing: the phase A design doc, docs/plans/counterfactual-everywhere-DESIGN-2026-10-29.md, plus the phase rows.
  - Owes: a self-land PR.
- **session_01AFoLuK8b2wcpwKiEDA6Xrc**, row RESEARCH-AUTHOR-FLOOR-20261029.
  - Doing: authoring 12+ queue units for the runnable_floor breach (38 < 49 at 21:26Z).
  - Owes: a HOLD PR on branch claude/research-author-floor-20261029. The **manager merges it**.

**Short-lived**
- Four LTR reviewers dispatched 21:20Z for the bybit_1 shorts (AVAX/BTC/ETH/ETH-prop at -0.5R):
  - session_01AFoLuJEiMR6GEfwg9KTzwS
  - session_01AFoLuLf8aqt2G4BPmPzQ7E
  - session_01AFoLuLmVpuRkAgUhPnkyUP
  - session_01AFoLuKXNjeCBhusFtKvsgW
  - Archive each once its row is committed.
- **Overlay canary lane session_01AFoLuKnxrXwUfkxME2GXW7.** Its last check is trig_01BYsumC31Xyrxa9iM7Ee5Xa at 2026-10-30 00:20Z. It wakes the manager ONCE (observed or unobserved), then stops. ⚠️ Its prompt names the OLD manager id, so update the prompt to the new id.

## 3. PRs needing the manager
- **#21412:** register, usage reading. Automerge armed.
- **The floor-authoring HOLD PR** (when it appears): the manager merges.
- Nothing else is open that waits on the manager. The ops-flags PR is **#17895**: never merge it, always keep it subscribed.

## 4. Landed today: merged, deployed, observed

| PR | What | Merged | Deployed | Observed / closing observation |
|---|---|---|---|---|
| #21322 | SINCE-ENTRY-WINDOW-FIX | ac427caa | CURRENT 16:06Z | Next new trade's first-bar telemetry. |
| #21373 | NON-TPSL-CLOSES | 766a5fd0 | CURRENT 21:07Z | NOT yet: the 3 pkgs d752b509 / 29c8e90b / 11c1100f should read close_reason=sl after the sweep (one-off trig_01GkjuTZ fires 21:53Z). |
| #21384 | PAPER-TESTING-DD-OFF (operator Tier-3, verbatim in PR) | 0e998e35 | CURRENT 20:31Z | /api/bot/config shows armed=false on bybit_1 / ib_paper / alpaca_paper / alpaca_options_paper / oanda_practice and true on both portfolio mirrors. bybit_1 entered ETH at 20:45:57Z. |
| #21402 | REAL-TP-COMPRESSED-ETH4H | 1e6e743f | CURRENT 21:44:54Z | Next forming-bar ETH-4h entry keeps its resting TP until the entry bar closes. |
| #21386 | GRADER-POST-EXIT-HORIZON | merged 20:32Z | — | XRP verdict re-grades after 2026-10-31 18:33Z. |
| #21339 | NO-NEW-GATES-RULE | — | — | — |
| #21328 | Usage-credits note | — | — | — |
| #21356 | Timeframes units | — | — | SLO recovered 19:21Z. |

**#21402 root cause:** the tp_revision donchian_measured_move rule anchored on the pre-breakout bar when the entry bar was still forming. Real-money pkg-a04b68a1 got a 0.26R TP and closed in 90s at +$0.74.

## 5. Register work owed (one register PR)
- NON-TPSL-CLOSES-20261029 → done, once the labels are verified.
- PAPER-TESTING-DD-OFF → done. Observed: the bybit_1 entry at 20:45:57Z.
- RESEARCH-AUTHOR-TIMEFRAMES-20261029 → done (SLO 0.57 at 19:21Z).
- REAL-TP-COMPRESSED-ETH4H → landed_unproven, with the observation above.
- GRADER-POST-EXIT-HORIZON → landed_unproven (XRP re-grade after 10-31 18:33Z).
- NEW ROW MIRROR-PNL-NULL-6787 (tier 2, rank 2):
  - trade 6787 on bybit_portfolio closed tp with realizedPnl null and journalTrust no_record;
  - the real-money leg 6786 was measured at +0.7408;
  - #21402 did NOT cover this.
- NEW ROW RESEARCH-AUTHOR-FLOOR-20261029, when its PR lands.

## 6. Operator asks: open, exact wording or decision pending
1. **Gates list** (from #21339's audit). Four gates have no operator record. Asked ~17:21Z; no answer yet:
   - E57 research-queue human-merge hold;
   - ML-consumer intake refusal;
   - lane $ ceiling / capacity rate;
   - research dispatcher caps (3 inflight / 10 queued / 1 GPU).
2. **trend_donchian_eth_prop prop survival record:** p_breach 0.934 vs EV +$75.74 on breakout_2. The leg is live on 3 prop accounts. The manager promised to put the exact Tier-3 change in front of the operator. Not done yet.
3. **uPnL live check:** the operator asked to be pinged when a real-money or prop trade is open, to watch uPnL tick. Recurring trig_01UuY58V64dQoetPPVieCSLV (8 * * * *) does this. It disables itself after asking once.
4. **Counterfactual everywhere (operator ~19:15Z):**
   - run the grader on ALL past trades and backtest corpora on non-Claude compute;
   - build it into the backtest harness, ML labels, desk/LTR, AM rule and perf review.
   - Row COUNTERFACTUAL-EVERYWHERE; phase A is in flight.
5. **Post-exit review (operator ~19:05Z):** every trade review must also look past the exit, to catch exiting too early. Delivered in #21386.
6. **The two walk-forward passes PI-20261028-FFTW4JNY-0001/0002** (eth_prop, sol) are classified NEEDS_DATA: the 365d window was negative, the prop survival is untested, and sol has no Stage-1 trade. They are not put to the operator.

## 7. Scheduled tasks targeting the OLD session
Recreate each on the new session, then disable the old one.

**Recurring**

| Trigger | Name | Schedule |
|---|---|---|
| trig_01T5UKCQ2D4SX8wqrwCZe7vY | Manager lane check-in | `17 */3 * * *` |
| trig_016SkphcnnYg7SGXuzB3DL4Y | Manager hourly refill | `28 */3 * * *` |
| trig_01XKjKvdyPDnp1v7yJwcLhxD | Manager review | `52 5,17 * * *` |
| trig_01HVMPo62mY2UF32JXCec6CX | Thursday walk-through + planning | `17 6 * * 4` |
| trig_01YL2pQqB7MAMmwiRrr7Jg5W | Weekly audit | `31 18 * * 3` |
| trig_01CjxinYbZFfZsqnnCxDWieT | Weekly review prep | `53 18 * * 3` |
| trig_01VzhpT4xbgoQLhn4U6ioS2w | Weekly programme review | `29 19 * * 3` |
| trig_015E4HbBs3JB8yzCSRzDbfPB | Weekly CJ-7 grading | `13 20 * * 3` |
| trig_01UuY58V64dQoetPPVieCSLV | uPnL live-check reminder | `8 * * * *` |

**One-shot**
- trig_01GkjuTZYifEiiEuVN7RTBaY, 21:53Z: verify the NON-TPSL labels and close 3 rows.
- trig_01W9xDxPQovw7i6GGWm448Yq, 22:09Z: land the floor authoring PR.

**Fired fire-only report triggers** (no schedule) still show enabled. Disable them; they never fire again.

**Assistant manager:** session_011c3qoaBvGBioDWkPVToQSb. Its routines resolve the manager dynamically, so it needs no change:
- research-ops 14:47Z;
- daily authoring 05:53Z;
- LTR backstop every 4h;
- health review Wed 19:11Z;
- lane check-in every 6h.

## 8. New manager's first actions
1. **V1:** the diff against this doc.
2. **Subscribe to the ops-flags PR #17895.**
3. **Run the register PR in § 5.**
4. **Answer LTR / desk wake markers per the manager SKILL.** The REVIEWER-BRIEF path is .claude/skills/live-trade-review/REVIEWER-BRIEF.md. The packet sha is the sha256 of json.dumps(packet, sort_keys=True, separators=(',',':')).
5. **Desk wake** per trading-desk SKILL § 6b. Sonnet, on desk/decisions, depth 1, WAKE PROMPT verbatim.
6. **Bring the operator** the eth_prop Tier-3 change and the gates question as popups.

## 9. Handover checklist
- [ ] Handoff doc merged (PR #__).
- [ ] New session created by a shallow session (the assistant manager): Opus, tags manager + predecessor:session_01AFoLuKwNMzjtn2CH2kVd86, depth __/8.
- [ ] Triggers recreated (n = __ of 11), old ones disabled.
- [ ] Prompts naming the old id updated (the overlay canary trigger).
- [ ] New manager subscribed, ops-flags included.
- [ ] V1 diff.
- [ ] V2 audit: 0 enabled on the old id, the check-in `17 */3 * * *` included.
- [ ] V3 sweep with a positive control.
- [ ] V4 round-trips.
- [ ] V5 operator told.
- [ ] STAND DOWN.
