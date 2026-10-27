# DESK-18E — why the live desk proposes ~0, and what the brief fix does and does not change

> **Doc status:** `unknown` · category `evidence` · last verified `never` · lane `DESK-18E-LIVE-PROPOSAL-RATE` (Tier 2, `landing: hold`)

## Root cause (MEASURED over the 29 packets on `desk/decisions` at 2026-10-27 ~16:00Z: 24 one-hour scans, 5 five-minute event scans; 29 decision rows, all `no_trade`)

1. **The live hold cannot be priced by any row that is positive.** A `claude_desk` proposal must be `market` and closed at `max_hold_min` <= 60. The 1h scan's history rows are 4 / 12 / 48 bars (4 h and up): none fits a 60-minute hold. On the six desk-leg crypto symbols every 4-bar and 12-bar row is net negative (e.g. 1502Z packet: 24 of 24 rows at h4/h12 except AVAX long h12 +0.03, n 973). The only positive crypto rows are 48-bar (AVAX long +0.89, BTC long +0.36, ETH short +0.20, ADA long +0.15; sd 5-7.5 R): the drift of a two-day hold, which the 60-minute leg cannot hold. The 5m event scans carry 3 / 6 / 12 bars (15-60 min) and are all negative (best -0.22 .. -0.28 R; mean cost 0.52 R of a 5m ATR). So the brief's rule ("beat the row's net mean") was applied correctly to rows that are all negative: **(b)+(e) in the dispatch list**.
2. **The brief also told the desk "most hours the right answer is `no_trade`"** and applied the beat-the-base-rate bar to shadow-lane symbols as well (a): the judge protocol only asks for "a trade worth taking", does not show the strategies' book, and had no hold cap (judged-1: all market, all horizon 48, 723 of 732 shorts, i.e. exactly the 48-bar drift rows).
3. Ruled out: (c) `desk_write.py` refused nothing (0 refusals in the rows I read; all 29 are accepted `no_trade`); (d) the 5m packets carry 5m rows, not 1h base rates.
4. Not a defect: 0 live proposals is what an honest desk should write while the only fitting rows are negative. The judge's 0.49/packet is not comparable (48 h hold, no cap).

## The fix (this PR: `DESK-BRIEF.md` only)

Price a hold on a row whose horizon fits it; two lanes: live (fitting row + a timing argument; a 48-bar row is not evidence for a 60-minute hold) and shadow (record-only symbols: a positive-net row with n >= n_floor is admissible evidence, `expected_r_net` <= the row's `mean_r`, confidence capped at `suggestive`). The neutral wording replaces "most hours no_trade". No change to an order path, sizing, risk, the 60-minute cap, `desk_write.py` or any packet builder.

## Before / after on the same 29 packets

| | propose_entry | live | shadow | refused by `desk_write` compile+row checks |
|---|---|---|---|---|
| before (the real live sessions, old brief) | 0 / 29 | 0 | 0 | n/a |
| after (one dry-run session, edited brief, drafts only, nothing written) | 7 / 29 (24%) | **0** | 7 | 0 of 29 (validated in-process with `compile_row` + `row_problems`, current `strategies.yaml` scope) |

All 7 are the same trade: SLV short, 48 bars, shadow, `suggestive` (packets 1339, 1631, 1743, 1835, 1938 on 10-26; 1401, 1502 on 10-27).

**Expected rates after the fix (INFERRED from this one run): live ~0 per packet (unchanged; honest), shadow ~0.2 per 1h packet during US hours, and one symbol.**

## What this does not give you — decisions for the manager/operator

- **The mechanical soak still cannot start**: the fix produces no live row, by design (not loosened). Options: (i) wait for a 5m event wake to find structure (unlikely at cost 0.5 R, 0/5 so far); (ii) add short-horizon (h1 on 1h) rows to the packet builder: more honest, but all negative, so it changes the pricing not the rate; (iii) an operator-decided, explicitly labelled *mechanics probe* row (a Tier-3 call: it is a trade without an EV claim); (iv) lift the 60-min hold cap (order path/leg behaviour: out of scope here). Recommend (iii) be put to the operator as the only route to a soak this week.
- The shadow proposals are SLV 48-bar drift (+4.6..+5.2 R, sd ~5): the judged-1 decomposition says drift, not timing. They feed the forward set; they claim no edge. The off-hours ETF closes were frozen 20:02Z-13:03Z, so shadow rows on equities are meaningful only in US hours.
- Limits: 29 packets exist, not the 50 requested; one judge session, no repeat (judge variance unmeasured); the "before" is the 29 real sessions, not a re-run of the old brief.

## Addendum — mechanics probe (operator 2026-10-27 ~16:10Z, verbatim "Mechanics probe (Recommended)")

Built in this PR (Tier 3, `landing: hold`): basis `mechanics` on a live `entry_generation` `propose_entry` marks a probe row.
- **No EV claim:** `expected_r_net` and `judge_prior` null (schema + both validators).
- **Cap 2, in code:** `desk_write.py` counts existing probe rows and refuses a third; `desk-records-guard` fails a decisions file with more than 2. (Counted across the file, i.e. per the one account that rosters the leg today; `bybit_1`.)
- **Demo accounts only:** desk intake refuses a probe while any account other than `bybit_1` / `alpaca_paper` / `ib_paper` rosters `claude_desk`.
- **Excluded everywhere:** `training = {train_eligible:false, gate_eligible:false, exclusion_reasons:["mechanics_probe"]}` (the `claude_judgments` dataset and `desk_grade` already key on those flags; the consumed-leak check refuses consuming it); `desk_outcomes` writes `not_computable` for a probe so the forward-shadow set never replays it. Tests: `tests/test_desk_mechanics_probe.py`.
- **Trigger:** manual only: the manager sends a wake whose prompt says "mechanics probe wake" (brief § 3a). Reversible by not sending it; revert the PR to remove it.
- **Minimum size:** the accepted-proposal queue carries `mechanics_probe`, and the `claude_desk` package confidence is capped at 0.05 (the documented scalar that only sizes DOWN). **UNVERIFIED:** whether the RiskManager's scalar floors that, i.e. whether the result is the venue minimum. I did not touch the RiskManager or sizing; read the first probe's fill size before the second.
- **Soak:** `soak_state` counts clean closed `bybit_1`/`claude_desk` journal trades by leg and account, so a clean probe trade counts as the mechanical soak trade without a SOAKS.json change.
- Not verified: no probe was written; no live intake/order run (no VM access here).
