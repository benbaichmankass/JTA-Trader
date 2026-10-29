#!/usr/bin/env python3
"""Probe: do setup_candidates LIVE rows use a bar whose close is AFTER the trade's entry?

PI-20261029-Q17QWHDZ-0001 (INFERRED from code): a live row is located at the last bar with
ts <= entry_ts (`_bar_index_at_or_before`) and takes its features, including close[e], from
that bar. If market_raw ts is the bar OPEN time, bar e is still forming at entry and close[e]
is future information. This measures it on real data: where the trade's actual entry price
sits relative to open[e], close[e] and close[e-1], and whether entry_ts falls inside bar e.

# wiring: manual-only - run by the ML-P1-COSTNET-REBUILD lane on the trainer.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.datasets.families.setup_candidates import (  # noqa: E402
    _bar_index_at_or_before, _load_live_trades, _live_realized_r,
)


def _dt(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets-out", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        rows = [json.loads(l) for l in open(Path(a.datasets_out) / "market_raw" / sym / "1h" / "v002" / "data.jsonl") if l.strip()]
        rows.sort(key=lambda r: r["ts"])
        ts = [str(r["ts"]) for r in rows]
        d_open, d_close, d_prev, inside, n = [], [], [], 0, 0
        for tr in _load_live_trades(a.journal, sym):
            if tr.get("entry_price") is None:
                continue
            e = _bar_index_at_or_before(ts, tr["entry_ts"])
            if e is None or e < 1:
                continue
            px = float(tr["entry_price"])
            o, c, pc = float(rows[e]["open"]), float(rows[e]["close"]), float(rows[e - 1]["close"])
            d_open.append(abs(px - o) / px * 1e4)
            d_close.append(abs(px - c) / px * 1e4)
            d_prev.append(abs(px - pc) / px * 1e4)
            t0 = _dt(rows[e]["ts"])
            inside += 1 if t0 <= _dt(tr["entry_ts"]) < t0 + timedelta(hours=1) else 0
            n += 1
        med = lambda x: round(st.median(x), 2) if x else None
        res[sym] = {"n": n, "entry_inside_bar_e": inside, "median_bps_|entry-open[e]|": med(d_open),
                    "median_bps_|entry-close[e]|": med(d_close), "median_bps_|entry-close[e-1]|": med(d_prev),
                    "sample_bar_ts": ts[-2:], "first_bar_ts": ts[:1]}
    Path(a.out).write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
