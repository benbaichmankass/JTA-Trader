# DRAFT for operator sign-off: holdout floor scaled to trade frequency (2026-11-19)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane AM-OPS-3 (GENERAL), row PI-20261117-LSFHBH4A-0007
>
> **Gates this adds or changes:** it CHANGES an existing bar: `holdout_min_n` in `config/mandates.yaml` (MD-PROMOTE-S1-S2 and the prop entry), resolver clause R-HOLDOUT. It **lowers** the floor for slow legs and adds no new gate. Because it changes a bar, it is **drafted, not applied**, until the operator signs off.

## The decision being implemented

Operator, 2026-11-17, on promotion packet #26719 (relayed by the manager), verbatim popup: *"Scale it to trade frequency (Recommended)"*. The recorded intent: keep a holdout check, but size it so that a slow strategy clears it in weeks, not years (a time window or a lower n for low-frequency legs).

## Why the current floor is years for slow legs (measured)

- R-HOLDOUT needs `holdout_confirmation`: the configuration selected on the earliest span, evaluated once on a pre-registered, never-seen latest span holding **≥ 25 trades** (`holdout_min_n: 25`).
- The only holdout unit for the 4h trend legs, `RQ-20261106-5b7a-02` (`trend_donchian_eth_4h`), carries `not_before: 2027-06-07`. Its power basis: held-back trades entered 2026-10-19..2027-06-06 at **0.1307 trades/day (0.91/week)**, the rate measured on the earlier unit RQ-20261016-077e-02, so ~30 trades take ~230 days.
- A daily or 4h leg can therefore never be promoted on Stage-0 evidence in 2026, however strong its record.

## Proposed rule (one rule for every leg)

1. **Floor:** `holdout_min_n_effective = clamp(ceil(r × 8), 10, 25)`.
   - `r` = the leg's trades per week on its own in-sample (selection) span, read from the same Stage-0 record.
   - So the floor is about **8 weeks of that leg's own trades**, never fewer than **10** and never more than today's **25**.
2. **Pass condition unchanged:** the same registered rule, the full cost stack, net of cost positive. It is evaluated once.
3. **A fast leg is unaffected:** at ≥ 3.1 trades a week the floor stays 25.
4. **Where it is stored:** `bar.holdout_floor_rule: "clamp(ceil(r*8),10,25)"` beside `holdout_min_n` in the two mandate entries. R-HOLDOUT computes the effective floor from the record and prints `r`, the floor and the record's held-back n in its verdict. A record without `r` falls back to 25. Unknown is not lenient.

| Leg trade rate (in-sample) | Effective floor | Weeks of accrual for a never-seen span |
|---|---|---|
| ≥ 3.1 / week (15m–1h scalps, many 1h legs) | 25 | ≤ 8 |
| 1.5 / week | 12 | ~8 |
| 0.91 / week (`trend_donchian_eth_4h`, measured above) | 10 | ~11 |
| 0.3 / week (slow 1d legs) | 10 | ~33 |

**Effect on RQ-20261106-5b7a-02:** its floor falls from 25 to 10. At 0.1307 trades/day the span reaches 10 trades ~77 days after its 2026-10-19 start, so `not_before` moves from 2027-06-07 to about **2027-01-04**.

## What signing off would change (and what it would not)

- **Changes:**
  - one field per mandate entry, plus the resolver's floor computation (Tier 1 tooling plus a mandate-file edit; the operator's sign-off is the authority for the mandate edit);
  - holdout units' `not_before` dates are recomputed with a dated amendment.
- **Does not change:**
  - the holdout pass rule;
  - the cost stack;
  - demotion (still the mirror's net-of-cost window and the live bar);
  - the live-performance promotion path (operator 2026-11-17), which is a separate way up.

## Alternatives offered with it

- **(a) A time window only** (e.g. "the latest 90 days, whatever n"). Rejected as the default: a 90-day span with 3 trades gives a holdout that cannot fail.
- **(b) A lower fixed floor for every leg** (e.g. 15). Simpler, but it weakens the check on fast legs for no reason.
