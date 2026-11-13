# eth_4h tp_r 4 — ledger-fidelity re-run (2026-11-13)

Ordered by Manager Session 2026-11-11a, 08:01Z: run T4 through the gap-fixed harness with the standing record's prop-stack
arm and window, then re-grade under V3. It decides whether any honest eth_4h tp_r PR exists. Gates this adds or changes: none.

**Verdict: FAIL (v3 edge clause) on all three prop accounts.** No eth_4h tp_r 4 prop PR is supported.
This supersedes the unit's PASS (`../verdict.json`, graded on the RQ-20261028-a7c3-04 run-40826186111 ledger) for any promotion use.

## Ledgers
`exit_lever_ablation.py` at main (1d925844), the record's reproduce line (`docs/research/prop-replacement-2026-10-30/RESULT.md`):
arm P = `--fee-bps-roundtrip=8;--slippage-bps-roundtrip=3;--funding-bps-per-window=5;--funding-window-hours=24`, arm
PT4 = P + `tp_r=4`, `--days 1110 --start 2023-10-13 --end "2026-10-11 20:00" --grade stage0`. Candles: the committed Binance
ETHUSDT 4h file `comms/research/RQ-20261026-bf56-03/40733370814/candles/ETHUSDT_4h_1134d.csv` (2023-09-20..2026-10-27),
because Binance/Bybit are unreachable from the session container. 365d = entry_time >= 2025-10-11 20:00.

| check (population: the 3y ledger, 132 trades) | result |
|---|---|
| P vs the standing record's ledger (`prop-replacement-2026-10-30/ledgers/eth4h_3y.jsonl`) | 131/132 identical (entry, side, exit time, gross_r); one boundary trade each side at the window start |
| PT4 vs P | 1 trade differs (+1.92 R gross); 0 in the 365d tail |
| PT4 vs the unit's T4 ledger | 22 trades differ in gross_r (51.69 vs 66.20 R) |

## Grade (RULE-RQ20261113e44a01-ETH4H-TP4-PROP-V3, unchanged; current-stack arm, 5 seeds x 1000 lives)
| leg | window | v2 (all 3 accounts) | edge mean R [95% CI] | v3 |
|---|---|---|---|---|
| PT4 (primary) | 3y | PASS | +0.311 [-0.049, +0.672] | **FAIL_EDGE** x3 |
| P (paired) | 3y | PASS | +0.296 [-0.061, +0.654] | FAIL_EDGE x3 |
| PT4 | 365d | INDETERMINATE (n 51), EV negative on all 3 | -0.156 [-0.625, +0.312] | INDETERMINATE |

## Open question (not settled here)
Why the a7c3-04 ledger (2020-07 window, venue cost arm, commit fa6845d6) differs from this one in gross_r on 22 trades. That run
committed no candles, so the two inputs cannot be diffed from here. Either way the standing prop record stands on THIS ledger,
and the rule fails on it.

Reproduce: the ablation line above with `--data-csv <the file above>`, slice, then `bash run_cells.sh <leg> <win> <acct> cur <seed>`
for leg eth4hP|eth4hPT4, win 3y|365d, the three accounts, seeds 1-5, then `python3 docs/research/prop-eth4h-tp4-2026-11-13/fidelity/aggregate.py`.
