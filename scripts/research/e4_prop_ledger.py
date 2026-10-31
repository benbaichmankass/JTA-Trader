#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-18G-EVENT-ENTRIES (E4-PROP-SIM follow-up) to build the E4 trade ledger that prop_ev_sim prices; no schedule consumes it.
"""Build the E4 trade ledger (prop_ev_sim schema (a): entry_time, exit_time, gross_r, entry, sl, mfe_r) from the FROZEN E4 arm.

Same events, same engine as desk_event_entry_replay.py (``detect`` and ``gr.transplant``/``simulate`` unchanged): DEV window events
from the DEV cache, held-out window events from the held-out cache. gross_r is BEFORE cost (the simulator re-prices cost per firm).
mfe_r = max favourable excursion in R between the fill bar and the exit bar (gross), so the simulator's path model has its input.
Also writes the driver's own net R per trade so the ledger can be tied back to the scored S1 (DEV -0.006, held-out +0.022).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import desk_event_entry_replay as m  # noqa: E402
import desk_gen_replay_driver as gr  # noqa: E402


def rows_for(root: Path, window) -> list:
    mkt, missing = gr.load_market(root / "candles", list(m.SYMS))
    if missing:
        raise SystemExit(f"candles missing {missing}")
    lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
    out = []
    for ev in sorted(m.detect(root, mkt)["E4"], key=lambda e: (e["cutoff"], e["sym"])):
        if not (lo <= ev["cutoff"] < hi):
            continue
        s = mkt[ev["sym"]]
        i = s.last_closed(ev["cutoff"])
        if i < 0 or s.t[i] + gr.SEC != ev["cutoff"]:
            continue
        side = float(ev["side"])
        t = gr.transplant(s, i, dict(m.GEOM, side=side))
        if t is None or t.state != "filled":
            continue                                   # refused/unresolved are no-trade, as in the score
        a = float(s.atr[i])
        stop = float(s.c[i]) - side * m.SL_ATR * a
        seg_h, seg_l = s.h[t.fill_i:t.exit_i + 1], s.l[t.fill_i:t.exit_i + 1]
        fav = (seg_h.max() - t.fill_px) if side > 0 else (t.fill_px - seg_l.min())
        out.append({"strategy": "e4_oi_shock", "symbol": ev["sym"], "direction": "long" if side > 0 else "short",
                    "entry_time": datetime.fromtimestamp(int(s.t[t.fill_i]), tz=timezone.utc).isoformat(),
                    "exit_time": datetime.fromtimestamp(int(s.t[t.exit_i]) + gr.SEC, tz=timezone.utc).isoformat(),
                    "entry": t.fill_px, "sl": stop, "exit_reason": t.reason, "gross_r": round(t.gross_r, 6),
                    "mfe_r": round(max(0.0, float(fav) / t.risk), 6), "driver_net_r": round(t.net_r, 6),
                    "window": "dev" if window is m.DEV else "holdout"})
    return out


def main() -> int:
    dev_root, ho_root, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rows = rows_for(ho_root, m.HOLDOUT) + rows_for(dev_root, m.DEV)
    rows.sort(key=lambda r: r["entry_time"])
    out.mkdir(parents=True, exist_ok=True)
    end = max(r["entry_time"] for r in rows)
    cut365 = datetime.fromisoformat(end) - __import__("datetime").timedelta(days=365)
    full = rows
    t365 = [r for r in rows if datetime.fromisoformat(r["entry_time"]) >= cut365]
    for name, rs in (("full", full), ("365d", t365)):
        with open(out / f"e4_{name}.jsonl", "w") as fh:
            for r in rs:
                fh.write(json.dumps(r) + "\n")
    for name, rs in (("full", full), ("365d", t365)):
        d = [r for r in rs if r["window"] == "dev"]
        h = [r for r in rs if r["window"] == "holdout"]
        print(name, len(rs), "dev", len(d), round(float(np.mean([r["driver_net_r"] for r in d])), 4) if d else None,
              "holdout", len(h), round(float(np.mean([r["driver_net_r"] for r in h])), 4) if h else None,
              rs[0]["entry_time"], rs[-1]["entry_time"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
