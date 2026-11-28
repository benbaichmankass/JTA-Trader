#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261113-e44a-04.yaml (its blocked_on names this grader); tests/test_event_follow_read.py. Row NO-WAIT-HAND-BUILDS (lane INFRA-BUILD-20261128).
"""Post-release FOLLOW trade on hourly bars: enter at the close of the first bar after a release in the direction of that bar's move, hold 24 h.

The statistic of RQ-20261113-e44a-04 (rule RULE-RQ20261113e44a04-GDX-CPI-FOLLOW), generalised from ``ppi_event_read.py`` so ONE symbol and ONE
release list can be graded without that script's 15-symbol sweep. For each release time t (floored to the hour):
  j        = first bar whose START >= t
  reaction = close[j] / close[j-1] - 1                    (prior close -> close of the first post-release bar)
  trade    = sign(reaction) x (close[k] / close[j] - 1) - cost,   k = first bar whose START >= start[j] + 24 h
Statistic: mean and one-sample t (ddof 1) of ``trade`` over the releases whose bars cover the window.
Verdict (the unit's registered rule): PASS iff n >= MIN_N and mean > 0 and t >= T_BAR; FAIL iff n >= MIN_N and not PASS; INDETERMINATE iff n < MIN_N.

``--self-test`` re-grades the PPI releases on the committed GDX bars and must reproduce the PPI read (+145.0 bps, t 2.28, n 23): the
instrument check the unit asks for before it is trusted on CPI.

    python3 scripts/research/event_follow_read.py --bars GDX_60.csv --events releases.json --cost-bps 4 --out O
    python3 scripts/research/event_follow_read.py --self-test
Events file: ``{"events": [{"t": "2024-10-11T12:30:00Z"}, ...]}`` (extra fields ignored). Bars csv: ``timestamp,open,high,low,close,...``.
Tier-1 research; reads two files, writes ``--out``/verdict.json.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
MIN_N = 31
T_BAR = 1.96
RULE_ID = "RULE-RQ20261113e44a04-GDX-CPI-FOLLOW"
HOLD_H = 24


def load_bars(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["timestamp"], utc=True)
    return d.set_index("ts").sort_index()


def trades(bars: pd.DataFrame, release_times: List[str], cost_bps: float, hold_h: int = HOLD_H) -> pd.DataFrame:
    idx, c = bars.index, bars["close"]
    lo, hi = idx[0], idx[-1]
    rows = []
    for rt in release_times:
        t = pd.Timestamp(rt)
        t = (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).floor("h")
        if t < lo or t > hi:
            continue
        j = int(idx.searchsorted(t))
        if j >= len(idx) or j == 0:
            continue
        end = idx[j] + pd.Timedelta(hours=hold_h)
        if end > hi:                       # the 24 h window is not covered by bars: not graded, never clipped to the last bar
            continue
        k = int(idx.searchsorted(end))
        react = c.iloc[j] / c.iloc[j - 1] - 1.0
        cont = c.iloc[k] / c.iloc[j] - 1.0
        rows.append({"t": str(t), "reaction": float(react), "cont": float(cont),
                     "trade": float(np.sign(react) * cont - cost_bps / 1e4), "gap_h": (idx[j] - t).total_seconds() / 3600.0})
    return pd.DataFrame(rows, columns=["t", "reaction", "cont", "trade", "gap_h"])


def grade(tr: pd.DataFrame, n_requested: int) -> Dict[str, Any]:
    n = len(tr)
    base = {"rule_id": RULE_ID, "n": n, "n_releases_requested": n_requested, "min_n": MIN_N, "t_bar": T_BAR}
    if n < 2:
        return dict(base, verdict="indeterminate", read_state="no_data" if n == 0 else "measured", mean_bps=None, t=None,
                    note=f"n={n} < {MIN_N}")
    m = float(tr["trade"].mean())
    sd = float(tr["trade"].std(ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    if n < MIN_N:
        verdict = "indeterminate"
    elif m > 0 and t >= T_BAR:
        verdict = "pass"
    else:
        verdict = "fail"
    return dict(base, verdict=verdict, read_state="measured", mean_bps=round(m * 1e4, 1), t=round(t, 2), sd_bps=round(sd * 1e4, 1),
                hit=round(float((tr["trade"] > 0).mean()), 2), first_bar_gap_h_median=(float(tr["gap_h"].median()) if "gap_h" in tr else None),
                note=("UNDERPOWERED: n below the registered floor" if n < MIN_N else
                      "registered rule applied; a PASS must be re-graded on the repo cost stack before any promotion step"))


def run(bars_path: Path, events_path: Path, cost_bps: float, out: Optional[Path]) -> Dict[str, Any]:
    bars = load_bars(bars_path)
    ev = [e["t"] for e in json.loads(events_path.read_text(encoding="utf-8"))["events"] if e.get("t")]
    tr = trades(bars, ev, cost_bps)
    v = grade(tr, len(ev))
    v.update({"bars": str(bars_path), "bars_span": [str(bars.index[0]), str(bars.index[-1])], "cost_bps": cost_bps})
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "verdict.json").write_text(json.dumps(v, indent=1, default=float) + "\n")
        tr.to_csv(out / "trades.csv", index=False)
    return v


def _self_test() -> None:
    # 1) synthetic, hand-checkable: a release at 13:00 whose first bar (13:00) rose 1% from the 12:00 close, then +2% by +24 h
    idx = pd.date_range("2025-01-02 12:00", periods=60, freq="h", tz="UTC")
    close = pd.Series(100.0, index=idx)
    close.loc[idx[1]:] = 101.0
    close.loc[idx[1] + pd.Timedelta(hours=24):] = 101.0 * 1.02
    b = pd.DataFrame({"close": close.values}, index=idx)
    tr = trades(b, ["2025-01-02T13:20:00Z"], cost_bps=4)
    assert len(tr) == 1 and abs(tr["trade"].iloc[0] - (0.02 - 0.0004)) < 1e-12, tr          # long (reaction +), +2% - 4 bps
    b2 = b.copy()
    b2["close"] = [100.0] + [99.0] * 59                                                      # reaction -1%, price flat after: short earns 0 - cost
    assert abs(trades(b2, ["2025-01-02T13:00:00Z"], 4)["trade"].iloc[0] + 0.0004) < 1e-12
    assert len(trades(b, ["2025-01-02T13:00:00Z", "2030-01-01T00:00:00Z", "2025-01-04T20:00:00Z"], 4)) == 1  # out of range / window not covered: not graded
    # 2) the verdict rule's three arms
    flat = pd.DataFrame({"trade": [0.01] * 40 + [0.03] * 5})
    assert grade(flat, 45)["verdict"] == "pass"
    assert grade(pd.DataFrame({"trade": [-0.01, 0.015] * 20}), 40)["verdict"] == "fail"
    assert grade(flat.iloc[:20], 20)["verdict"] == "indeterminate"
    assert grade(pd.DataFrame({"trade": []}), 0)["read_state"] == "no_data"
    # 3) the instrument check: the PPI read's GDX arm on the committed bars, +145.0 bps / t 2.28 / n 23
    ppi = REPO / "comms" / "macro" / "ppi_event_read_20261113" / "ppi_surprises.json"
    bars = list((REPO / "comms" / "research" / "RQ-20261018-ef5d-01").glob("*/data/GDX_60.csv"))
    if ppi.is_file() and len(bars) == 1:
        v = run(bars[0], ppi, 4.0, None)
        assert v["n"] == 23 and v["mean_bps"] == 145.0 and v["t"] == 2.28, v
        print("event_follow_read self-test OK (incl. the PPI GDX reproduction: n 23, +145.0 bps, t 2.28)")
    else:
        print("event_follow_read self-test OK (synthetic only: the committed PPI files are not in this checkout)")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--bars")
    ap.add_argument("--events")
    ap.add_argument("--cost-bps", type=float, default=4.0)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if not (a.bars and a.events and a.out):
        ap.error("--bars, --events and --out are required")
    v = run(Path(a.bars), Path(a.events), a.cost_bps, Path(a.out))
    print(json.dumps({k: v.get(k) for k in ("verdict", "read_state", "n", "mean_bps", "t")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
