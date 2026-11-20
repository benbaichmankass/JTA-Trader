"""Rebuilds record.json from legs.jsonl (relay outputs) + comms/strategy_evidence/<leg>.json margins. Deterministic (seed 42)."""
import json
from math import comb
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
legs = [json.loads(line) for line in (HERE / "legs.jsonl").read_text().splitlines() if line.strip()]
meas = [r for r in legs if r["state"] == "measured" and r["n_binance"] >= 20]
d = np.array([r["dr_per_trade"] for r in meas])
w = np.array([r["n_binance"] for r in meas], float)
neg, pos = int((d < 0).sum()), int((d > 0).sum())
m = neg + pos
p_two = min(1.0, 2 * sum(comb(m, k) for k in range(min(neg, pos) + 1)) / 2 ** m)
rng = np.random.default_rng(42)
idx = [rng.integers(0, len(d), len(d)) for _ in range(10000)]
b_unw = [d[i].mean() for i in idx]
b_tw = [(d[i] * w[i]).sum() / w[i].sum() for i in idx]
tw = float((d * w).sum() / w.sum())
pooled = {
    "population": f"{len(meas)} legs of {len(legs)} run (every leg with n_binance >= 20), {int(w.sum())} Binance-side trades, window 2023-02-01..2026-11-15",
    "legs_bybit_worse": neg, "legs_bybit_better": pos, "sign_test_p_two_sided": round(p_two, 4),
    "trade_weighted_dr_per_trade": round(tw, 4),
    "trade_weighted_bootstrap95": [round(float(np.quantile(b_tw, q)), 4) for q in (.025, .975)],
    "unweighted_mean_dr_per_trade": round(float(d.mean()), 4),
    "unweighted_bootstrap95": [round(float(np.quantile(b_unw, q)), 4) for q in (.025, .975)],
    "median_dr_per_trade": round(float(np.median(d)), 4),
    "bootstrap": "10,000 leg-level resamples, seed 42",
}
POOLED = abs(tw)
margins = []
for r in [x for x in meas if x["real_money"]] + [{"leg": "ml_entry", "dr_per_trade": None}]:
    ev = json.loads((REPO / "comms" / "strategy_evidence" / f"{r['leg']}.json").read_text())
    ho = ev.get("holdout_confirmation") or {}
    pen = r["dr_per_trade"]
    pen_used = -pen if pen is not None else POOLED
    bind = min(x for x in (ev.get("expectancy_r_oos"), ho.get("expectancy_r_holdout")) if x is not None)
    margins.append({
        "leg": r["leg"], "evidence_record": f"comms/strategy_evidence/{r['leg']}.json",
        "expectancy_r_oos": ev.get("expectancy_r_oos"), "n_trades_oos": ev.get("n_trades_oos"),
        "expectancy_r_holdout": ho.get("expectancy_r_holdout"), "n_holdout": ho.get("n_holdout"),
        "measured_dr_per_trade": pen,
        "penalty_basis": "measured (this record)" if pen is not None else "pooled trade-weighted (ML leg: no harness argv to re-run)",
        "binding_margin_r": bind,
        "margin_over_penalty_x": (round(bind / pen_used, 2) if pen_used > 0 else None),
        "flag": None,
    })
for x in margins:
    if x["margin_over_penalty_x"] is not None and x["margin_over_penalty_x"] < 2.5:
        x["flag"] = "thin: binding margin within 2.5x the Bybit penalty -> Bybit-native re-test"
rec = {
    "record": "VENUE-GAP-20261120",
    "question": "Does Stage-0 evidence built on Binance-vision USD-M candles overstate what the same leg earns on the Bybit linear bars it trades?",
    "method": "Each leg's exact Stage-0 evidence argv (regime_debt_matrix.build_harness_cmd) run twice on the trainer, same window, once on the trainer's Bybit linear file and once on the Binance-vision USD-M native file, both aggregated OPEN-stamped to the leg timeframe (venue_gap_measure.py.txt in this directory: the script exactly as the three relays ran it, kept as text so it is never imported or linted as repo code). dR/trade = (sum_r_bybit - sum_r_binance) / n_binance.",
    "relays": [{"issue": 27588, "run": 44663389824}, {"issue": 27603, "run": 44666388564}, {"issue": 27615, "run": 44669544524}],
    "read_state": "measured",
    "measured_vs_estimated": "21 of 21 legs measured; ml_entry's penalty is ESTIMATED (the pooled figure), never measured",
    "pooled": pooled, "real_money_margins": margins,
    "not_measured": "5m/15m legs (ict_scalp, fvg_range, turtle_soup) and every ML leg; Binance per-trade rows were not kept (only per-leg sums)",
    "decision": "manager 2026-11-20 03:52Z: new crypto Stage-0 units for Bybit-traded legs use the trainer's Bybit files as primary corpus (Binance = robustness arm). No existing evidence, promotion bar, config or live state changed. Making it binding doctrine is put to the operator as a proposal.",
    "follow_ups": ["PI-20261120-7ITMUEB1-0005", "PI-20261120-7ITMUEB1-0007", "RQ-20261120-4f03-01 (trend_donchian_sol_prop Bybit-native Stage-0 re-run)", "RQ-20261120-4f03-02 (ml_entry measured venue penalty)"],
}
(HERE / "record.json").write_text(json.dumps(rec, indent=1) + "\n")
print(json.dumps(pooled, indent=1))
for x in margins:
    print(json.dumps(x))
