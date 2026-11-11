# Weekly walkthrough 2026-11-11

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Three lanes write this one brief: **PERFORMANCE** (lane `PERF-REVIEW-PREP`), **ML + FRONTIER** (lane `ML-FRONTIER-PREP`) and
> **PRACTICE REFRESH** (lane `PRACTICE-REFRESH-20261111`). A section that another lane has not landed yet is simply absent.
> On a collision, the later lane merges `main` first.

<!-- PRACTICE-REFRESH:START -->
## TRADING + MODEL — weekly practice refresh (lane `PRACTICE-REFRESH-20261111`)

Tier 1, read-only on production. Nothing was queued and no config changed. Full evidence:
[`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § 12](../research/practice-review-trade-mgmt-and-ai-2026-10-28.md).
The canonical list was revised in place: [`docs/reference/trading-and-model-practice-principles.md`](../reference/trading-and-model-practice-principles.md).
Direct `/api/diag/*` reads return 401 this week, so diag reads went through the relays (#24905, #24906, #24910, #24911) and the read-only
console data source; § 12.6 names the route behind each number.

**First, the feedback loop.** Thursday 11-05 decided 2 of last week's 12 proposals. Then the ML-entry focus and the one-lane throttle
(operator, 11-06) left the rest with no decision. Proposal #12 below gives the refresh a fixed slot in Thursday planning.

**TRADING:** 4 sources checked (1 read in full). **Deltas:**
- **T3 strengthened.** Measure execution cost as a **markout** (fill vs the mid later, net of fees), and count order size against depth and
  forced exits as cost channels [S74, AFT 2026: on Hyperliquid's full record, algorithmic takers only broke even on a 2 h markout].
- **T8 strengthened (cautionary).** An exit replay on a leg's own trades stays chronological and deflates its grid [S75: a 900-trade replay
  switched to a random split].

**MODEL:** 4 sources checked (abstracts or summary). **Deltas:**
- **M14 added.** An LLM's own trading returns are a claim, not evidence. Prefer the LLM upstream of deterministic sizing, risk and
  execution, with six validity tests before any deployment claim [S78].
- **M12 strengthened.** Also check forecast amplitude and cross-series ranking; per-series loss hides "forecast collapse" [S76, S77].
  **Scope note:** under the operator rule of 11-04, per-asset scores are reported, not gating.
- **M11 note.** Repeatability is necessary, but it is not skill [S59 re-read].

### Demo-floor data generation

Population: 58 rostered leg × floor cells. Data: trades with entry time ≥ 2026-11-04T19:00Z. The console journal snapshot covers up to
~08:00Z 11-11, and relay #24906 reads ids 7056–7070. Ids 7052–7055 are unread (comment truncation).

| Account | Cells | Cells with ≥1 row | Fills | Rejected | Fills / rejected a week ago |
|---|---|---|---|---|---|
| bybit_1 | 30 | 23 | 58 | 32 | 42 / 30 |
| alpaca_paper | 17 | 6 | 13 | 6 (incl. 1 exchange) | 5 / 2 |
| ib_paper | 11 | 3 | 1 | 25 | 2 / 25 |

- **Blocked:**
  - ib_paper `mgc_trend_1h`: 16 `risk_refused sized_qty=0` since 11-09 01:11Z, cause not established, plus netting against the MGC short.
  - bybit_1: the slice budget refused 24 signals, mostly on the 5m scalps and the SOL legs.
  - alpaca_paper `ml_entry`: zero buying power on 11-05, and a USO hard-to-borrow short sent with a non-day TIF (a mechanics bug).
  - `claude_desk` on alpaca_paper / ib_paper: no row for the **third week**, and no audit row since 11-10.
  - **New:** bybit_1 `htf_pullback_trend_2h` logs a complete sell setup but has no journal row in 7 days.
- **Quiet by design:** 16 cells ("no breakout / no setup / no squeeze release"). **Quiet in position:** 3 ib_paper cells, including an
  MHG short open since 09-17. **Could not look:** 4 cells (relay timeouts).
- 41 of 63 floor rejections are netting/slice refusals with no priced outcome (last week 47 of 57).

### Is it learning?

Population: 98 registry files and 24 datasets (`trainer-vm-diag` #24905), and the shadow log 10-24 → 11-11 (75,831 records, 27 heads).

- **market_features:** works end to end. 52 models were retrained (364 runs), 22 heads score, and 3 are advisory.
- **Trade-level families** (setup_candidates, conviction_meta, trade_outcomes): 13 models retrained (91 runs), **0 score live**. The
  setup_candidates dataset is **frozen again** at 48,445 rows (newest 10-29).
- **LTR:** `review_journal` = 0 rows (third week). **Desk:** `claude_judgments` 883 → 1,203 rows, but no trainer uses them. **Exit heads:**
  dataset frozen since 09-07; the heads are outside the registry.
- **Trainer:** cycle 11-11 trained 67 models with 3 refusals. **New:** a dataset audit refuses `setup-candidates-metalabel-xsym-yz-v1`
  (dead feature or degenerate label). `exit-policy-v1` has never trained (107.6 d).

### Gaps for Thursday (12 in § 12.7; proposals, nothing queued). Top of the list:

1. **MODEL:** `trend_donchian_eth` (bybit_1) still **closes trades** on an exit head with only an in-sample read. Its real-money sibling's
   head **failed** a matched-random control on 11-04. Dispatch the queued OOS walk-forward (`PI-20261029-IFMPNGJK-0004`) with that
   control added; until then, propose `annotate` (Tier 3) (T1, M10).
2. **TRADING:** 41 of 63 floor rejections leave no outcome. **Again:** a `VIRTUAL-LEG-LEDGER` build row (T12, R3).
3. **TRADING:** four floor mechanics faults (ib MGC sizing refusals, USO TIF, Bybit min-notional, the `htf_pullback_trend_2h` setups with
   no row) → the soak-fault intake.
4. **MODEL:** the desk on alpaca_paper / ib_paper is silent for the third week. Diagnose `DESK-PAPER-ACCOUNTS` first.
5. **TRADING:** markout measurement of execution cost on every fill (T3, S74).
6. **MODEL:** name the first trade-level family to reach shadow scoring; fix or kill `exit-policy-v1` and the audit-refused manifest (M1, M10).
7. **BOTH:** a per-leg × floor liveness CHECK in health-review (R6), still hand-classified for the third week.
8. **MODEL:** `ML-LEARNING-LEDGER` has been queued through three refreshes; **raised**.
<!-- PRACTICE-REFRESH:END -->
