## Programme 01: Active Trade Management. Audit as of 2026-10-16

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-16` · registered in [`../../../../DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md) · manager programme audit 2026-10-16 (input to the backlog lanes and the 2026-10-20 programme review) · **Tier-1: nothing here changes a config, a roster or an order path.**

### 1. Intent
- **Q1–Q2:** measure how much R each leg gives back between its peak and its close (giveback, Q1). Set the entry take-profit (TP) from the leg's own maximum favourable excursion (MFE) distribution, conditioned on volatility and regime, instead of a sentinel (Q2).
- **Q3–Q4:** revise the TP every bar (extend, retarget, pull in on a stall) (Q3). Add a "stop waiting" stop-loss rule keyed to the measured giveback or to momentum decay (Q4).
- **Q5–Q7:** a momentum-turn label study (Q5). Producer/harness parity, then a Tier-3 flip (Q6). Carry the same bracket on the prop paths (Q7).
- **Q8, the destination:** P(SL before TP | state now) on every bar, and an exit-now rule that beats the fixed bracket net of cost.
- **What it serves:** goal G1, milestone L-ATM (closed M20/M31 merged into it). Headline measure is net R per capital-day per leg, real money first. Real money today is bybit_2 (5 legs) and alpaca_live (3 legs).

### 2. What has been done
| Q | Units, date, verdict, headline (n) | State |
|---|---|---|
| Q1 | `9807-01` 10-15 PASS. Population: closed trades in the last 90d with telemetry, n=326. Paper: giveback share of peak 0.93, deep-then-loss 0.15 (n=319). **Real money n=7, `insufficient_n`.** Harness proxy `9d20-01` 10-14: pullback headroom 1.54 R/trade (4,900 ledger trades, 54 legs). | Answered for paper and harness; **open for real money** |
| Q2 | eth_4h: `419b-01` FAIL (10 finite cells all fail out of sample, base OOS 49) and `cab7-04` FAIL (K*=2.5, −0.166 R/trade OOS, n_oos 59). `cab7-01/02/03` INDETERMINATE (n=222/225/60). `061` INDETERMINATE (OOS 5/8/9). `cab7-06` pooled alpaca 1d INDETERMINATE (n=155). `cab7-05` conditioned TP INDETERMINATE (+0.029 R vs unconditioned, CI [−0.054, 0.105], n_oos 262). | Open; **negative on eth_4h** |
| Q3 | `001`/`003` landed 10-08, no verdict. `9807-03` 10-14: the **same 6 TP-extension cells pass on xrp_pullback_2h on a new partition** (base OOS 103). ada_pullback_2h 8/33 pass (OOS 83). xrp_4h 1/33 (OOS 24, below the 39 floor). `080` re-run (comms only): Donchian measured-move PASS, +24.35 R pooled (n=1,439 trades), eth_4h 27.3→51.5 R with maxDD 12.2→8.4, 46% of revisions cap-bound. `004` scalps no_action on 7 legs. | Open; **strongest candidates in the programme** |
| Q4 | `042`/`043` landed 10-08 with provisional passes on the Donchian legs, no verdict. `9807-04` blocked. | Open |
| Q5 | `9807-05` blocked on the per-bar path emit. | **Never run** |
| Q6 | TP-DOCTRINE B1 merged; no leg declares a revision rule. `check_tp_doctrine.py` (07:07Z today): **0 of 54** routings compliant. Real money 8 routings: 5 fail entry_tp, 8 fail tp_revision. | Open |
| Q7 | No new units. | Idle |
| Q8 | `d6e7-01` PASS: 3,926 trades on 27 USDT legs, oracle saving 0.656 R/trade at K=2 (n_sl_first 2,089). `d6e7-02` FAIL: gain −0.00077 nats, CI [−0.00174, 0.00021], n_oos 2,389. `d6e7-03` retired. `d6e7-04` INDETERMINATE: +0.00054 nats, CI [−0.00118, 0.00245], 4/4 folds positive. Entry-time `9d20-03` FAIL. All crypto-only: 22 non-crypto legs skipped; about 370 scalp trades excluded by the re-walk control. | Rungs 2 and 4 show no information beyond the distance reference |

### 3. Queue state
How units were attributed: roadmap in {L-ATM, M20, M31}, or title/theme matching exit, giveback, TP, bracket, trail, stale, first-passage, M20 or E35. Re-entry cooldown units (Programme 03) and L-DATA units (Programme 06) are excluded. That gives **142 units**:

- **Queued: 74.** 62 are generated monthly sweeps (37 M20 exit-lever, 25 E35 bracket-geometry); 12 are hand-written.
- **Blocked: 11.** Done: 48. Retired: 9.
- **Oldest queued hand units:** `RQ-20260927-003` (dispatched 09-27), `20260830-002` (09-29), `20260831-002` (09-30).
- **7 of the 12 hand-written queued units have landed results but no verdict:** `001`, `003`, `024`, `042`, `043`, `080`, `9807-03`.

Blocked units and why:
- **Unblock condition already met, still in `blocked/`:**
  - `9807-04`: it waited on the census, which passed 10-15.
  - `RQ-20261009-900`: it waited on the corpus `736c-01`, which passed 10-15.
- **Waiting on the unbuilt `EXIT-PATH-EMIT-OFFLINE`** (queued, unassigned): `d6e7-06`, `9807-05`, `9da8-04`.
- **Missing tooling:** `9807-02` (needs entry-ATR reader), `1bf3-01` (no pooled e35 gate), `RQ-20261007-044` (no dispatchable route for the flip lever), `RQ-20261008-901` (no pullback head driver).
- **Waiting on data accrual:** `RQ-20260930-901` (expected around 2027-06).

### 4. Misalignments and problems
1. **The harness does not measure what the rules require.** The m20 sweep emits only the generic gate. TP calibration (`tp_cal_*`) and walk-forward fold counts are absent, so `001/003/042/043/9807-03` cannot be graded as registered (RESEARCH-GRADE-PILE). The best Q3 evidence is stuck behind this.
2. **`080`'s PASS was never graded.** It is in `comms/research/RQ-20261007-080/38747768830/` but not in `research/results/`. The grader read the stale `producer_failed` row (verdict null, 10-16).
3. **`d6e7-05` will never fire.** It is queued, but it requires `d6e7-04` to pass and `04` is INDETERMINATE. The P1-Q8.2-fail refinement node is listed in the authoring queue but no unit has been written for it.
4. **The priority build is unstarted.** `EXIT-PATH-EMIT-OFFLINE` is the W1 build due by 10-21 and it gates 3 units plus the scalp-control fix.
5. **9807-04 cannot use the live census.** Its cells key on real-money per-leg giveback, which has n=7. It should key on the harness-ledger giveback from `9d20-01` instead.
6. **`9807-02` is now a near-duplicate** of `cab7-05`.
7. **The monthly sweeps are mostly noise:**
   - E35 rows in October: 4,200. 4,035 carry no gate verdict, 147 fail out of sample, 12 fail walk-forward, 6 pass. All 6 passes are on 1d equity legs at base OOS 6–9, far below the 39 floor.
   - 25 of 26 queued E35 units have no `research/results` row.
   - M20: 8 legs have duplicate units (for example `RQ-20261009-005` and `RQ-20261010-003`).
   - 16 M20 units graded PASS against the generic gate and nobody reads them. Repeated runs of the same partition are being counted as if they were confirmation.
8. **Stale text:**
   - The plan and RESEARCH-MAP say "0 of 50"; the current count is 0 of 54.
   - The plan lists `419b-01`/`061` as queued; both have closed.
   - L-ATM `next` asks to resolve `060/061/419b-01`; all three are closed.
   - Doctrine conflict: two FAILs say a finite entry TP on eth_4h costs money, while the doctrine requires one.

### 5. Recommended next 5 days (to the Tue 2026-10-20 review)
1. **[research unit] Grade the TP-extension and revision candidates on real-money legs** (xrp_pullback_2h 6 cells, ada_pullback_2h 8 cells; Donchian ADX trail `adx20_k0_t2.5`). First step: re-run `9807-03`'s cells with `--tp-report` and the yearly walk-forward, or add `tp_cal_*`/`wf_*` output to the m20 sweep, so the registered rule can be applied. A pass leads to a Tier-3 declare proposal.
2. **[build row] Get `080`'s result into `research/results`.** First step: write the record from `comms/research/RQ-20261007-080/38747768830/verdict.json` and re-run `queue_grade.py`. Then register a per-leg out-of-sample confirmation for eth_4h and xrp_4h.
3. **[build row] Assign `EXIT-PATH-EMIT-OFFLINE`.** First step: add `--emit-paths` to `scripts/backtest_trend.py` and `scripts/backtest_pullback.py`, with the parity test (max peak_r over path rows == mfe_r).
4. **[research unit] Queue housekeeping:**
   - `git mv` `9807-04` and `RQ-20261009-900` out of `blocked/`.
   - Re-key `9807-04` on the `9d20-01` per-family giveback.
   - Retire `d6e7-05` with a stated reason and write the Q8.2/Q8.4 refinement unit (for example a per-class split, or state from the path emit).
   - Retire `9807-02` as superseded by `cab7-05`.
5. **[decision for operator] eth_4h TP doctrine.** Accept a doctrine exception, or require a revised TP rather than a fixed one? `080` points to the revised TP.
6. **STOP:** retire the per-leg E35 monthly units on 1d equity legs in favour of the pooled `1bf3-01` lever, and dedupe the 8 M20 duplicate pairs.

CONFIDENCE: I read these directly: unit YAMLs, result JSONLs, the `080` comms verdict, checklist rows, the e35 corpus, and a fresh `check_tp_doctrine.py` run. The programme attribution is a keyword heuristic. I inferred that the M20 cells repeat on the same partition rather than independent data, and I ranked the items by money impact without measuring it.