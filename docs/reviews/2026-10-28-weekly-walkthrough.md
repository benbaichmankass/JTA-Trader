# Weekly walkthrough 2026-10-28

> **Doc status:** `live` · category `evidence` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

One brief, three sections, each written by its own lane: **ML + frontier** (`ML-FRONTIER-PREP-20261028`),
**performance** (`PERF-REVIEW-PREP-20261028`) and **practice refresh** (`PRACTICE-REFRESH-20261028`).

<!-- ML-FRONTIER-PREP:BEGIN -->
## MODEL track — ML review + frontier scan (lane `ML-FRONTIER-PREP-20261028`)

_Work in progress — checks running (trainer pull #20968)._
<!-- ML-FRONTIER-PREP:END -->

<!-- PRACTICE-REFRESH:BEGIN -->
## TRADING + MODEL — weekly practice refresh (lane `PRACTICE-REFRESH-20261028`, session_01AFoLuJpe2bJTErX7QGAmaS)

Tier 1, read-only on production; nothing queued, no config changes. Full evidence:
[`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § 10](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md).
Canonical list revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).

**TRADING:** 6 sources (2 read in full); **deltas:** T11 added (vol-scaled sizing helps tails everywhere, but Sharpe only for risk assets [S56]),
T12 added (no-trade buffer [S57]), T2 and T3 strengthened (crypto stop-loss momentum [S62]; funding is part of the exit's cost [S61]).
**Gaps filed:** `IB-PAPER-ETF-LEGS-NO-ROWS`, `SPLG-TICKER-DEAD`.

**MODEL:** 4 sources (abstract level); **deltas:** M11 added (measure an LLM decision's repeatability before grading its edge [S58, S59]),
M6 strengthened [S53], R3 tension noted [S63]. **Gaps filed:** none new; the exit-head registry gap (queued since 2026-09-08) is **escalated**.

### Demo-floor data generation — population: 57 rostered leg × floor cells, trades created 2026-10-21T19Z → 10-28T19Z (`/api/diag/journal`, 3 × 1000 rows paged)

| Account | Cells | Cells with ≥1 row | Fills | Rejected |
|---|---|---|---|---|
| bybit_1 | 31 | 19 | 20 | 7 |
| alpaca_paper | 15 | 1 | **0** | 3 |
| ib_paper | 11 | 2 | **1** | 14 |

- **Blocked:**
  - ib_paper spy, qqq and iwm `_trend_long_1d` plus tlt_pullback_1d: **no ib_paper row ever** (2026-07-21 onward), while the same legs journal on Alpaca. Row filed.
  - `splg_trend_long_1d`: **SPLG became SPYM on 2025-10-31**. Empty bars and a raise every tick, and no audit row. Row filed with the exact Tier-3 change.
  - `mgc_trend_1h`: 13/13 rejected (7 shadow, then 6 flip-suppressed by mgc_pullback_1d's short).
  - The bybit_1 margin refusals (`available_usd=0.00`, 10-20 and 10-27) have **cleared**: none since 10-27 18:07Z, and 7 entries on 10-28. The sizing basis stays open on `BYBIT1-SIZING-COLLATERAL-BASIS`.
- **Quiet by design:** the daily equity and futures legs, the 4h donchians and the chop-only legs. Every eval reason is "no setup / no breakout / regime not chop".
- `trend_donchian_1h` is retired by record but still listed on bybit_1, so it is quiet by retirement.

### Is it learning? — population: 97 registry rows (mirror, 72 s old) + 23 trainer dataset dirs + the shadow log 10-24→10-28

- **market_features:** the chain works end to end (52 models retrained in 7 d, 22 heads scoring, 3 advisory).
- **Trade-level families** (setup_candidates, conviction_meta, trade_outcomes): they retrain, but **0 score live**. `setup_candidates` retrains on a dataset **frozen since 08-04**.
- **Desk judgments:** in a dataset (627 rows), but no family trains on them.
- **LTR review rows:** `review_journal` = **0 rows**.
- **Exit heads:** they can close trades, but sit **outside the registry**, with their dataset frozen since 09-07.
- **Last trainer cycle:** trained 0 models (72 already done).

### Gaps for Thursday (proposals; 13 in § 10.7). Top of the list:

1. **TRADING:** ib_paper ETF legs silently produce no rows (filed, Tier 2).
2. **TRADING:** SPLG → SPYM (filed, Tier 3: operator yes/no).
3. **MODEL:** exit heads close trades from outside the registry, with a frozen dataset (escalated, M10).
4. **MODEL:** trade-level families never score, and `review_journal` is empty (M1/M10).
5. **TRADING:** a suppressed opposing intent leaves no outcome record; propose a virtual per-leg ledger (T12/R3).
6. **MODEL:** desk/LTR recommendations are never re-run for repeatability (M11).
7. **TRADING:** LTR in-trade triggers are R-denominated only, with no ATR twin arm (T4).
8. **BOTH:** health-review has no per-leg × floor liveness check, and a raising builder leaves no audit row (R6).
<!-- PRACTICE-REFRESH:END -->
