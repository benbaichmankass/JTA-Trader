# ML-P1 cost-net rebuild: setup meta-label verdict (2026-10-29)

> **Doc status:** `unknown` · category `research` · last verified `2026-10-29` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> Lane `ML-P1-COSTNET-REBUILD`, step B1 of [`ml-live-promotion-plan-2026-10-29.md`](../plans/ml-live-promotion-plan-2026-10-29.md). Machine record: [`comms/ml-plan/p1_costnet_verdict.json`](../../comms/ml-plan/p1_costnet_verdict.json).

## Verdict: INDETERMINATE (P1 rule, graded unchanged)

The § 3 P1 rule says INDETERMINATE if eval rows < 200, or if more than 20 % of live eval rows are excluded for lacking an initial-risk basis. **Both hold:**

| | value | limit |
|---|---|---|
| eval rows (real closed trades with declared initial risk) | **144** | ≥ 200 |
| live closed trades of BTC/ETH/SOL excluded for no declared initial risk | **262 of 362 = 72.4 %** (BTC 245 stored-stop + 17 unit-fallback; ETH 0; SOL 0) | ≤ 20 % |

Everything else the rule asks for was computed on the 144 rows, **and passes**, but a pass on these rows is not a PASS under the rule:

| rule leg | result (population: 144 real closed trades, `label_cost_basis = realized`, `r_multiple_source = initial_risk` on all 144) |
|---|---|
| (a) cost gate | passed. Value **+0.2122 R/opp** vs take-all −0.0482, take-none 0, matched-random −0.0097 (29 taken, take rate 0.201), PSR 0.99999, n_trials 1 |
| (b) trade bootstrap, 10,000 resamples, seed 42, value − matched-random | point +0.222, **95 % LB +0.128 > 0** |
| (c) take rate in [0.05, 0.60] | 0.201, ok |
| (d) ≥ 2 of 3 symbols positive, n ≥ 30 | BTC +0.188 (n 62, 11 taken), ETH +0.224 (n 35, 6 taken). SOL n = 3, not counted. ok |
| (e) initial-risk R | holds by construction for the 144; fails on exclusion share (above) |

**Do not read (a)–(d) as "close to a PASS".** The eval book is 97 BTC/ETH rows plus 47 rows on ADA, XRP, SOL and equities, taken from a book where the head was trained on BTC/ETH/SOL harness rows only; the taken sets are 11 and 6 trades on the two counted symbols. The point estimate is encouraging and the sample is small. The registered rule says INDETERMINATE for exactly this reason, and it is not loosened here.

## What was built (all on the trainer, off the trade path)

- **`setup_candidates/all/all/v022`**: v020's build params (3-symbol 1h harness replay train, widened eval shards, `include_paper=true`), the current cost-net builder, and `live_r_basis=initial_only`. v020/v021 untouched. 6,117 rows: 5,166 backtest train, 144 live eval, 807 paper (tagged, never eval).
- **Label provenance fix (PI-20261014-MVBJLVJ3-0001).** Live-row R is now `pnl / initial_risk_usd` using the order package's entry-time `risk_per_unit` (`r_provenance.initial_risk_usd`), tagged `initial_risk`; the old trail-overwritten `trades.stop_loss` read is tagged `stop_distance` and dropped from the P1 eval.
- **Model** `setup-candidates-metalabel-p2pool-v2`, `research_only`, registered, trained with the code of PR #21176, so its `model_state` carries `serve_spec` (B2's requirement for 10/10 serve parity). `experiment_dir` is in the JSON record.

## The lookahead question from B2 (PI-20261029-Q17QWHDZ-0001): it HOLDS

Probe `scripts/ml/p1_lookahead_probe.py` on the trainer (relay #21179): `market_raw` `ts` is the bar **open** (`close[e-1] == open[e]` in the 1h BTC file), and the live trade's `entry_ts` was inside bar *e* on every probed trade (ETH 35 of 35, SOL 3 of 3). A live row therefore took its features and `entry_price` from the bar still forming at the fill. Fixed in this PR for live rows (last closed bar, e−1), with a test. Effect on this run: value +0.135 → +0.212 R/opp, take rate 0.181 → 0.201, bootstrap LB +0.054 → +0.128, verdict unchanged. **The lookahead cost the head nothing; it changed the features the head sees.** The pre-fix run is kept in the JSON record.
**Not probed, so not fixed:** the same bar-location call places the harness-backtest rows and signal-log rows. Whether those use the forming bar depends on what timestamp the recorder stores. Filed as PI-20261029-MLP1-0002.

## Per-leg note (manager relay)

Not computed. Live dataset rows carry no strategy name, so the book pools every strategy on its symbol. B2 serves only the three `trend_donchian` 1h legs faithfully (`squeeze_breakout_4h`, `htf_pullback_trend_2h` serve `timeframe_mismatch`, PI-20261029-Q17QWHDZ-0002), so a P1 PASS would promote for those three only.

## What unlocks a verdict

PI-20261029-MLP1-0001: 245 of 307 BTC live closed trades have no declared initial risk. Establish why (unlinked `order_package_id`, pre-dates `risk_per_unit`, or recoverable from the package), backfill the read if recoverable, rebuild v022, retrain, regrade with the same helper. The rule is unchanged.

## Not done in this lane (stated, not dropped)

- Re-gate of the other 8 setup heads on v022, `exit_candidates` for the 1h Donchian legs, and P4 `conviction_meta` restamp/regate: see the lane's closing note on the checklist row for what ran.
