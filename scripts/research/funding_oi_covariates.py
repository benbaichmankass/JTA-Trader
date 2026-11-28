#!/usr/bin/env python3
# wiring: manual-only - the covariate builder of row FUNDING-OI-DATASETS-ETH-SOL (lane INFRA-BUILD-20261128); imported by time-series-model / regime research units; no schedule consumes it.
"""Causal funding-rate / open-interest covariates aligned to a bar index. (Tier-1 research tooling; reads files, writes one file.)

Input : a ``funding_oi/<SYM>/v001/data.jsonl`` side-stream (``scripts.ml.fetch_funding_oi``; rows ``{ts, symbol, funding_rate, open_interest}``,
        one of the two fields set per row) and a bar table (CSV with a ``ts`` column of bar OPEN times, UTC, ISO or epoch seconds).
Output: one row per bar with PAST-KNOWN covariates only, so a time-series model can take them as covariates without leakage:

    funding_rate        last funding settlement at or before the bar's CLOSE (bar_open + bar_seconds), carried forward
    funding_z168        z-score of funding_rate over the last 168 settlements (including this one; min 3), 0.0-free: None when undefined
    funding_age_h       hours since that settlement (a stale value is visible, never silently carried)
    oi                  last open-interest snapshot at or before the bar's close
    oi_logchg_1 / _24   log change of oi vs the snapshot 1 / 24 bars earlier (None when the earlier snapshot is missing)
    oi_age_h            hours since that snapshot

CAUSALITY: a value stamped t is used by a bar only if t <= bar_open + bar_seconds - lag_seconds (default lag 0: the bar has closed, so
everything stamped by its close is known). ``--self-test`` perturbs every row stamped AFTER a bar's close and asserts that bar's output is
unchanged. A missing side-stream leaves the columns None with ``read_state`` = no_side_stream; it never emits 0 for "could not look"
(CLAUDE.md rule 2: a null renders as a dash, never 0).

    python3 scripts/research/funding_oi_covariates.py build --funding-oi DIR/data.jsonl --bars bars.csv --bar-seconds 3600 --out cov.csv
    python3 scripts/research/funding_oi_covariates.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

FUNDING_WINDOW = 168
COLUMNS = ("ts", "funding_rate", "funding_z168", "funding_age_h", "oi", "oi_logchg_1", "oi_logchg_24", "oi_age_h")


def _to_epoch(v) -> float:
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def load_side_stream(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(funding_ts, funding_rate, oi_ts, oi), each ascending by ts."""
    f_t, f_v, o_t, o_v = [], [], [], []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        t = _to_epoch(r["ts"])
        if r.get("funding_rate") is not None:
            f_t.append(t)
            f_v.append(float(r["funding_rate"]))
        if r.get("open_interest") is not None:
            o_t.append(t)
            o_v.append(float(r["open_interest"]))
    fo, oo = np.argsort(f_t, kind="stable"), np.argsort(o_t, kind="stable")
    return (np.asarray(f_t, dtype=float)[fo], np.asarray(f_v, dtype=float)[fo],
            np.asarray(o_t, dtype=float)[oo], np.asarray(o_v, dtype=float)[oo])


def _asof(ts: np.ndarray, known_at: float) -> int:
    """Index of the last stream row stamped at or before known_at; -1 if none."""
    return int(np.searchsorted(ts, known_at, side="right")) - 1


def covariates(bar_open: Sequence[float], bar_seconds: int, stream, lag_seconds: int = 0) -> list[dict]:
    f_t, f_v, o_t, o_v = stream
    out = []
    for t0 in bar_open:
        known = float(t0) + bar_seconds - lag_seconds
        row = {"ts": datetime.fromtimestamp(float(t0), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "funding_rate": None, "funding_z168": None, "funding_age_h": None,
               "oi": None, "oi_logchg_1": None, "oi_logchg_24": None, "oi_age_h": None}
        i = _asof(f_t, known)
        if i >= 0:
            row["funding_rate"] = float(f_v[i])
            row["funding_age_h"] = (known - float(f_t[i])) / 3600.0
            w = f_v[max(0, i - FUNDING_WINDOW + 1): i + 1]
            if len(w) >= 3 and float(np.std(w)) > 1e-12:
                row["funding_z168"] = float((w[-1] - np.mean(w)) / np.std(w))
        j = _asof(o_t, known)
        if j >= 0:
            row["oi"] = float(o_v[j])
            row["oi_age_h"] = (known - float(o_t[j])) / 3600.0
            for lag, key in ((1, "oi_logchg_1"), (24, "oi_logchg_24")):
                k = _asof(o_t, known - lag * bar_seconds)
                if k >= 0 and o_v[k] > 0 and o_v[j] > 0:
                    row[key] = float(math.log(o_v[j] / o_v[k]))
        out.append(row)
    return out


def build(a) -> int:
    with open(a.bars, newline="") as bf:
        bars = [_to_epoch(r["ts"]) for r in csv.DictReader(bf)]
    p = Path(a.funding_oi)
    if not p.exists():
        rows = [{"ts": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **{c: None for c in COLUMNS[1:]}} for t in bars]
        state = "no_side_stream"
    else:
        rows = covariates(bars, a.bar_seconds, load_side_stream(p), a.lag_seconds)
        state = "measured"
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    nn = {c: sum(1 for r in rows if r[c] is not None) for c in COLUMNS[1:]}
    print(json.dumps({"read_state": state, "bars": len(rows), "non_null": nn, "side_stream": str(p)}))
    return 0 if state == "measured" else 2


def _self_test() -> None:
    H = 3600
    base = 1_700_000_000 - (1_700_000_000 % H)
    f = [(base + 8 * H * k, 1e-4 * (k % 5 - 2)) for k in range(30)]          # settlements every 8h
    o = [(base + H * k, 1000.0 + 10 * k) for k in range(240)]                  # hourly OI
    def stream(fp, op):
        return (np.array([x[0] for x in fp], float), np.array([x[1] for x in fp], float), np.array([x[0] for x in op], float), np.array([x[1] for x in op], float))
    bars = [base + H * k for k in range(60, 200)]
    ref = covariates(bars, H, stream(f, o))
    # 1) a settlement stamped exactly at the bar close is known; one stamped a second later is not
    t0 = base + 20 * H
    r = covariates([t0], H, stream([(t0 + H, 5e-4)], [(t0 + H, 2000.0)]))[0]
    assert r["funding_rate"] == 5e-4 and r["funding_age_h"] == 0.0 and r["oi"] == 2000.0
    r = covariates([t0], H, stream([(t0 + H + 1, 5e-4)], [(t0 + H + 1, 2000.0)]))[0]
    assert r["funding_rate"] is None and r["oi"] is None and r["funding_z168"] is None   # nothing known: None, never 0
    # 2) no lookahead: rewriting every row stamped after a bar's close leaves that bar unchanged
    for idx in (0, 37, 90, 139):
        close = bars[idx] + H
        f2 = [(t, v if t <= close else v + 9.0) for t, v in f]
        o2 = [(t, x if t <= close else x * 7.0) for t, x in o]
        got = covariates([bars[idx]], H, stream(f2, o2))[0]
        assert got == ref[idx], (idx, got, ref[idx])
    # 3) lag shifts availability: with lag one bar, the bar sees what the previous bar saw
    lagged = covariates(bars[1:], H, stream(f, o), lag_seconds=H)
    assert [x["oi"] for x in lagged] == [x["oi"] for x in ref[:-1]]
    # 4) log change and age are what they say
    row = ref[50]
    j = int((bars[50] + H - base) // H)                                        # snapshot stamped at the bar close
    assert abs(row["oi"] - (1000.0 + 10 * j)) < 1e-9 and abs(row["oi_logchg_1"] - math.log((1000.0 + 10 * j) / (1000.0 + 10 * (j - 1)))) < 1e-12
    assert row["oi_age_h"] == 0.0 and 0.0 <= row["funding_age_h"] < 8.0
    assert ref[0]["funding_z168"] is not None and covariates([base + 8 * H], H, stream(f, o))[0]["funding_z168"] is None   # < 3 settlements
    print("funding_oi_covariates self-test OK")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("--funding-oi", required=True)
    b.add_argument("--bars", required=True)
    b.add_argument("--bar-seconds", type=int, default=3600)
    b.add_argument("--lag-seconds", type=int, default=0)
    b.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "build":
        return build(a)
    ap.error("a command or --self-test is required")


if __name__ == "__main__":
    sys.exit(main())
