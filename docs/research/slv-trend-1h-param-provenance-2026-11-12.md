# slv_trend_1h — parameter-selection provenance

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

**Lane:** SLV-ITERATION (am:TRADING), 2026-11-12. **Gates this adds or changes:** none.
**Question (dispatch task b):** where did `donchian 24` / `atr_stop_mult 1.5` / `trail_mult 4.0` come from, and were they chosen on the
2025-26 window? The promotion record (`comms/strategy_evidence/slv_trend_1h.json`) carries `param_selection_provenance: not_established`.

## Answer

**They were not chosen on the 2025-26 window alone. Each was chosen on a window that covers most of 2019-2026, so no full-history
backtest of this leg is out-of-sample for any of them.** The only data after every choice is the stretch after 2026-10-15, about four
weeks. Its registered fresh-span read is `RQ-20261104-7fdb-02`, due 2027-03-16.

| key | live value | where it was chosen | data it was chosen on | how it was chosen | verified from |
|---|---|---|---|---|---|
| `donchian` | 24 | 2026-06-20 intraday ETF sweep, study `etf_intraday_trend_SLV` (`config/research/studies/etf_intraday_trend.yaml` @ `da3b036dbf`) | Dukascopy **SLV CFD 1h RTH**, ~2017 → `wf_end 2026-06-18`, 5-fold k-fold, train_frac 0.4, 7.5 bps/side | **best of 5 variants** by net R: `both_donch24` +85.45 R beat `both_sides` +81.72 R, `donch24` (long-only) +61.21 R, base (donchian 48, long-only) +52.27 R and `trail6` +46.80 R (`automation/results/etf-intraday-sweep.txt` @ `da3b036dbf`). No deflation for the 5 tried. | the study spec + sweep output at that commit; wired 2026-06-21 in `b25b05f685` |
| `trail_mult` | 4.0 | the same study | same | **not tuned for SLV**: 4.0 is the study's `base` value, a template written for SPY. One alternative, `trail6`, was tried and scored lower. | same files; present unchanged since the first wiring `b25b05f685` |
| `atr_period` | 14 | the same study | — | template default, never varied for this leg | same |
| `atr_stop_mult` | 1.5 (was 2.5) | E35 bracket-geometry corpus, run `32975514836` (2026-08-26), cell `sm1.5`, verdict `path_b_wf_pass`, wf 5/6; declared by M20 B4 on 2026-08-29 (`91de68b9cc`, Tier-3, operator-approved) | the E35 harness's trailing `days=1830` window ending at run time (~2021-08 → 2026-08; `docs/research/e35-matrix-recheck-2026-08-29.md`) | grid cell selected on **path B** (capital efficiency), not path A: the IS and OOS gates both failed on `maxdd_worse`, and it is `leverage_contingent` (notional per risk budget 46.9 → 78.9) (`docs/research/e35-bracket-corpus.jsonl`; `docs/research/bracket-geometry-decision-packet-2026-08-26.md`) | corpus row + packet |
| `min_confidence` | 0.3 (was 0.0) | 2026-08-01, `0093d2ba13` (Tier-3, operator-approved) | **paper-book** reviews: 5 graded entries, all losses, confidence 0.04-0.15 | a floor set from live-book grading, **not a backtest** (a book never establishes edge) | the config comment + commit |
| `tp_r` | 6.0 (was the 50 R sentinel), pending PR #25267 | `RQ-20261112-5ab1-03` | Dukascopy SLV CFD 1h, discovery 2018-06 → 2024-09-17, held-back 2024-09-17 → 2026-10-15 | best of 4 (`tp_r` 2/3/4/6) on discovery, then read once on the held-back span: PASS, n 108, +33.37 R. That unit discloses that the held-back span had already been read for arm A (`RQ-20261101-78fc-18`) and contains the data the other params were chosen on. | the unit's grading block (branch `lane/slv1h-promote`) |

## What this means for the evidence

1. **The promotion record (~2025-04 → 2026-09) is in-sample for all of the above.** Its +0.78 R/trade (n 68) was read over data the
   parameters were chosen on.
2. **A full-history replay (2019 → 2026) is also in-sample.** `RQ-20261112-cdb2-01` grades it, and that unit says so in its
   `what_it_does_not_do`. A PASS there is a consistency reading, not an edge confirmation.
3. **Multiplicity is understated.** donchian is best of 5, `atr_stop_mult` came from a multi-cell grid on path B, and `tp_r` is best
   of 4. None of these was deflated.
4. **The real out-of-sample checks are:**
   - `RQ-20261104-7fdb-02`, the fresh span after 2026-08-30, due 2027-03-16;
   - the live mirror's net-of-cost window (`alpaca_portfolio`), which is the Gate-2 demotion signal and belongs to AM-TRADING.
5. The lever units `RQ-20261112-cdb2-02..05` cover session, channel length, regime filter and cost. They check whether the chosen values sit
   on a smooth response or on a spike.

## Record follow-up

`param_selection_provenance` lives in the evidence record, which PR #25267 rewrites. That PR is a held Tier-3 PR and this lane does not
edit it. When it merges, this file is the source to fill that field from (pipeline item filed by SLV-ITERATION).
