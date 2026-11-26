# wiring: manual-only - one-off dev-fold diagnostic for row ML-ENTRY-BOOK-FEATURES; run: python3 scripts/research/ml_entry_book_state.py <klines_cache> <out.json>
"""Diagnostic (not a registered read): on the 8 dev folds, does ml_entry's net R depend on its OWN book state at entry?
Buckets: same-side ml_entry positions already open across symbols at entry (0 / 1-2 / 3+), and whether a same-side STOP-OUT
happened in the prior 24 h. Registered recipe refit per fold, tau 0.10, full cost stack (label_symbol net R)."""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_decision_entry as M

cache = Path(sys.argv[1])
out = Path(sys.argv[2])
tab = M.build_table(cache, M.universe())
bounds = [pd.Timestamp(x, tz="UTC") for x in M.DEV_FOLDS] + [pd.Timestamp(M.HOLDOUT_START, tz="UTC")]
dev = tab[tab.ts < bounds[-1]]
rows = []
for a, b in itertools.pairwise(bounds):
    test = dev[(dev.ts >= a) & (dev.ts < b - pd.Timedelta(hours=M.HORIZON_H + 1))]
    pl, ps = M.fit_predict(M.purge_train(dev, a), test)
    t = test.assign(p_long=pl, p_short=ps).sort_values(["symbol", "i"])
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for r in g.itertuples(index=False):
            if r.i <= busy:
                continue
            side = "long" if r.p_long >= r.p_short else "short"
            p = r.p_long if side == "long" else r.p_short
            if p > 0.10:
                bars = int(getattr(r, f"bars_{side}"))
                rows.append((sym, r.ts, r.ts + pd.Timedelta(hours=bars), side, float(getattr(r, f"net_{side}")),
                             int(getattr(r, f"reason_{side}"))))
                busy = r.i + bars
d = pd.DataFrame(rows, columns=["symbol", "ts", "exit_ts", "side", "net_r", "reason"]).sort_values("ts").reset_index(drop=True)
open_same, stop_24h = [], []
for side in ("long", "short"):
    s = d[d.side == side]
    ts, ex, rs = s.ts.to_numpy(), s.exit_ts.to_numpy(), s.reason.to_numpy()
    for idx, t0 in zip(s.index, ts):
        open_same.append((idx, int(((ts < t0) & (ex > t0)).sum())))
        stop_24h.append((idx, bool(((rs == 1) & (ex <= t0) & (ex > t0 - np.timedelta64(24, "h"))).any())))
d["open_same"] = pd.Series(dict(open_same))
d["stop_24h"] = pd.Series(dict(stop_24h))
d["open_bucket"] = pd.cut(d.open_same, [-1, 0, 2, 1000], labels=["0", "1-2", "3+"])

def stat(x):
    r = x.net_r.to_numpy()
    m = r.mean()
    wk = pd.to_datetime(x.ts, utc=True).dt.strftime("%G-%V").to_numpy()
    se = np.sqrt((pd.Series(r - m).groupby(wk).sum() ** 2).sum()) / len(r)
    return {"n": len(r), "mean_net_r": round(float(m), 4), "se_week_clustered": round(float(se), 4)}

res = {"population": f"registered recipe refit per dev fold {M.DEV_FOLDS[0]}..{M.HOLDOUT_START}, 60 perps, tau 0.10, net R fee {M.FEE_BPS}+slip 3+funding 1 bps/8h",
       "all": stat(d),
       "by_open_same_side": {str(k): stat(g) for k, g in d.groupby("open_bucket", observed=True)},
       "by_same_side_stop_prior_24h": {str(k): stat(g) for k, g in d.groupby("stop_24h")},
       "provenance": "MEASURED (dev OOS, diagnostic; not a registered read)"}
out.write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
