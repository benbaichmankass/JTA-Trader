#!/usr/bin/env python3
# wiring: research/queue/RQ-20261102-5e1a-01.yaml (lane ML-ENTRY-PROP-GATE)
"""Build the ml_entry v1 graded ledger (served ENTRY, extend-only TP) for the prop gate.

Same population as comms/strategy_evidence/ml_entry.json (served ENTRY trades 2025-10-01..2026-09-30, 5 bybit_2 symbols);
the 5-symbol replay must reproduce the record's extend_only mean (0.0271299...) before the ETH+SOL restriction is applied.
Rows carry gross_r so prop_ev_sim --costs breakout re-prices them under each firm stack.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E
import ml_entry_tp_revision as T

cache, out = Path("/tmp/ml_decision_klines"), Path(sys.argv[1])
dev = json.loads((REPO / "comms/research/RQ-20261101-383f-01/local-20261101T1030Z/dev.json").read_text())
art = json.loads(T.SERVED.read_text())
syms = E.universe()
tab = E.build_table(cache, syms)
bars = T.load_bars(cache, syms)
panel = T.feature_panel(bars)
a = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
cut = a - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=T.H + 1)
tm = T.fit_tp_model(T.training_rows(tab, bars, panel, cut, T.SEED))
traded = E.traded_symbols()
trades = T.served_trades(tab, E.HOLDOUT_START, T.DEV_END, art)
trades = trades[trades.symbol.isin(traded)].reset_index(drop=True)
rows = T.trade_checkins(trades, bars, panel)
probs = T.probs_by_trade(rows, T.predict_probs(tm, rows))
sc = T.Scorer(trades, bars, probs, tm["class_mean_net_r"])
rec = []
orig = T.walk
def spy(*a, **k):
    r = orig(*a, **k); rec.append(r[:3]); return r
T.walk = spy
pol = sc.policy(float(dev["margin_star"]), extend_only=True)
T.walk = orig
assert len(rec) == len(pol) == len(trades)
mean5 = float(np.mean([x[0] for x in pol]))
print("5-symbol extend-only mean", mean5, "n", len(pol))
assert abs(mean5 - 0.02712995887700275) < 1e-6 and len(pol) == 907, "does not reproduce the evidence record"
# ML-PROP-ITERATE enrichment (2026-11-02): extra per-trade columns for the ETH/SOL diagnostics. Appended fields only; the
# 5-symbol reproduction assert above and every existing field are untouched (prop_ev_sim ignores unknown keys).
_feat = tab.set_index(["symbol", "ts"])[["ret_168", "vol_ratio", "atr_pct"]]
led = []
for k, t in trades.iterrows():
    px, j, reason = rec[k]
    s = 1 if t.side == "long" else -1
    Ob, Hh, L, C = sc.win[k]
    entry = float(Ob[0]); risk = E.SL_ATR * float(t.atr)
    ts = bars[t.symbol]["ts"]
    et = ts.iloc[int(t.i) + 1]
    xt = ts.iloc[int(t.i) + j] + pd.Timedelta(hours=1)
    fav = (Hh[:j].max() - entry) if s > 0 else (entry - L[:j].min())
    gross = s * (px - entry) / risk
    led.append({"leg": "ml_entry", "strategy": "ml_entry", "symbol": t.symbol, "direction": t.side,
                "entry_time": str(et), "exit_time": str(xt), "entry": entry, "sl": entry - s * risk,
                "exit_reason": {0: "time", 1: "sl", 2: "take_profit"}[reason],
                "gross_r": round(gross, 6), "mfe_r": round(max(fav / risk, gross), 6), "net_r_evidence": round(pol[k][0], 6),
                "pred_net_r": round(float(t.p_long if t.side == "long" else t.p_short), 6),
                **{c: round(float(_feat.loc[(t.symbol, t.ts), c]), 6) for c in ("ret_168", "vol_ratio", "atr_pct")}})
df = pd.DataFrame(led)
out.mkdir(parents=True, exist_ok=True)
for name, sub in (("ml_entry_5sym", df), ("ml_entry_ethsol", df[df.symbol.isin(["ETHUSDT", "SOLUSDT"])])):
    sub = sub.sort_values("entry_time")
    (out / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in sub.to_dict("records")) + "\n")
    print(name, len(sub), "evidence-stack mean net R", sub.net_r_evidence.mean())
