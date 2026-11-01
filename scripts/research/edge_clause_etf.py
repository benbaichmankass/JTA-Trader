#!/usr/bin/env python3
# wiring: manual-only - POST-HOC regime-robustness clause on unit RQ-20261101-58e4-05 (E5). Informational; verdict unchanged.
import json, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D, regime_robustness as RR

UNIVERSE = ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SLV", "GDX", "USO", "XLE", "MHG"]
cols = {}
for s in UNIVERSE:
    c = sorted(Path("comms/research").glob(f"**/data/{s}_D.csv"), key=lambda q: -q.stat().st_size)[0]
    d = pd.read_csv(c, parse_dates=["timestamp"], index_col="timestamp"); d.index = d.index.tz_convert("UTC") if d.index.tz is not None else d.index.tz_localize("UTC")
    cols[s] = d["close"][~d.index.duplicated()]
close = pd.DataFrame(cols).sort_index(); close = close[(close.index <= D.END_DISCOVERY) & close["SPY"].notna()]
D.DAYS = 252; ret = close.pct_change(); zero = pd.DataFrame(0.0, index=close.index, columns=close.columns)
cfg = dict(lb=[63, 126, 252], tv=0.10, lo=False)
W = D.tsmom_weights(close, zero.notna().astype(float), cfg, n_univ=len(UNIVERSE), rebalance=5, max_lev=3.0, vol_window=63, universe_fixed=UNIVERSE)
net, _, _ = D.net_from_weights(W, ret, zero, 1.0, 0.0, per_side_bps=2.0); l, s = RR.split_sides(W, ret, zero, 2.0)
m = net.index >= pd.Timestamp("2008-01-01", tz="UTC")
o = RR.clause(net[m], l[m], s[m], two_sided=True); o["label"] = "POST-HOC (clause registered after the run); E5"
Path(sys.argv[1]).write_text(json.dumps(o, indent=1, default=str))
print(json.dumps({k: o[k] for k in ("clause_pass", "years_positive", "years_ok", "top_year_share_of_total", "concentration_ok", "long_net_sum", "short_net_sum", "sides_ok", "subperiod_sums", "subperiods_ok")}, indent=1))
print(o["per_year"])
