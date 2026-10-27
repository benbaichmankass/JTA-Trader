#!/usr/bin/env python3
# wiring: manual-only - run by the DESK-EDGE-PROGRAM lane (operator redirect 2026-10-27 ~16:40Z); no schedule consumes it.
"""DESK-EDGE-PROGRAM -- lever magnitudes and the per-horizon cost table (token-free).

  costs   --klines DIR --out F                   cost as a fraction of the 1-sd move per hold (Binance USD-M 1m klines)
  levers  --ceiling DIR --learner ridge --out F  measured S1/S3 of each lever on a desk_edge_ceiling build's test folds

Selectivity (top-q of out-of-sample predictions), geometry, session window of the top picks, and a direction-neutral
pair (best long + best short on different symbols). Everything is scored with the driver's cluster_stats via
desk_edge_ceiling.s_rows. POST-HOC SLICES: every line is one of the looks counted in the doc; none is evidence.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_edge_ceiling as ce  # noqa: E402
from scripts.research import desk_gen_replay_driver as d  # noqa: E402

HOLDS_MIN = (1, 5, 15, 30, 60, 240, 720, 2880)
# round-trip bps. The repo stack is execution_costs' DEFAULT_FEE_BPS_ROUNDTRIP + PERP_SLIPPAGE_BPS_ROUNDTRIP. The MEASURED
# row is our own Bybit fills: 1,411 fills, all taker at 5.5 bps per side (comms/research/desk_edge/levers/
# bybit-fee-measured-2026-10-27.json) plus R3's measured market slippage, 1.29 bps round trip (2026-10-25). The maker rows
# use Bybit's published maker fee (0.02% per side: INFERRED from the public schedule; we have no maker fill to measure).
SCENARIOS = {"repo stack (7.5 fee + 3 slip)": 10.5, "MEASURED Bybit taker (11.0 fee + 1.3 slip)": 12.3,
             "maker entry, taker exit (2+5.5 fee + 1.5 slip)": 9.0, "maker both sides (2+2 fee, 0 slip)": 4.0}
FUNDING_BPS_PER_8H = 1.0


def _only_member(z: zipfile.ZipFile) -> str:
    """A Binance Vision monthly zip holds exactly one CSV; refuse anything else rather than pick one."""
    (name,) = z.namelist()
    return name


def cost_table(klines: Path) -> list:
    closes = collections.defaultdict(list)
    files = sorted(glob.glob(str(klines / "*-1m-*.zip")))      # every file is read; none is chosen over another
    print(f"cost_table: reading all {len(files)} 1m kline files under {klines}: {[Path(f).name for f in files]}", file=sys.stderr)
    for f in files:
        s = Path(f).name.split("-")[0]
        z = zipfile.ZipFile(f)
        txt = z.read(_only_member(z)).decode().splitlines()
        closes[s] += [float(ln.split(",")[4]) for ln in txt if ln and not ln.startswith("open_time")]
    rows = []
    for h in HOLDS_MIN:
        sds, meds = [], []
        for c in closes.values():
            r = np.diff(np.log(np.array(c)[::h])) * 1e4
            sds.append(float(r.std()))
            meds.append(float(np.median(np.abs(r))))
        sd = float(np.median(sds))
        fund = FUNDING_BPS_PER_8H * (h // 480)
        rows.append({"hold_min": h, "sd_bps": sd, "sd_range_bps": [min(sds), max(sds)], "median_abs_move_bps": float(np.median(meds)),
                     "cost_over_sd": {k: (v + fund) / sd for k, v in SCENARIOS.items()}})
    return rows


def _st(rows, ix):
    s = d.cluster_stats(ce.s_rows(rows, ix), draws=2000)
    return {"n": s["n"], "S1": s["mean_net_r"], "S3": s.get("paired_diff_vs_random"), "S3_ci95": s.get("paired_diff_ci95")}


def lever_table(cutoffs, acts, learner: str) -> dict:
    X, _ = ce.feature_rows(cutoffs, acts, "P+")
    p = ce.walk_forward(acts, X, learner)
    te = np.array([r["fold"] in ce.TEST_FOLDS for r in acts])
    rows = [acts[j] for j in np.nonzero(te)[0]]
    pt = p[te]
    out = {}
    for q in (0.20, 0.05, 0.01, 0.002):
        out[f"selectivity top {q:.1%}"] = _st(rows, np.nonzero(pt >= np.quantile(pt, 1 - q))[0])
    g = np.array([r["geom"] for r in rows])
    for gg in sorted(set(g)):
        m = np.nonzero(g == gg)[0]
        out[f"geometry {gg} unselected"] = _st(rows, m)
        out[f"geometry {gg} top 5%"] = _st(rows, m[pt[m] >= np.quantile(pt[m], 0.95)])
    hr = np.array([(r["cutoff"] // 3600) % 24 for r in rows])
    thr = np.quantile(pt, 0.95)
    for a, b in ((0, 7), (7, 13), (13, 21), (21, 24)):
        out[f"session {a:02d}-{b:02d}h, top 5%"] = _st(rows, np.nonzero((hr >= a) & (hr < b) & (pt >= thr))[0])
    grp = collections.defaultdict(list)
    for j, r in enumerate(rows):
        grp[(r["cutoff"], r["geom"])].append(j)
    pairs = []
    for ix in grp.values():
        L = [j for j in ix if rows[j]["side"] == "long"]
        S = [j for j in ix if rows[j]["side"] == "short"]
        if not L or not S:
            continue
        a = max(L, key=lambda j: pt[j])
        b = max([j for j in S if rows[j]["symbol"] != rows[a]["symbol"]] or S, key=lambda j: pt[j])
        pairs.append((pt[a] + pt[b], {"week": rows[a]["week"], "net_r": (rows[a]["net_r"] + rows[b]["net_r"]) / 2,
                                      "days": rows[a]["days"], "diff": (rows[a]["y"] + rows[b]["y"]) / 2}))
    pairs.sort(key=lambda x: -x[0])
    for q in (1.0, 0.05):
        s = d.cluster_stats([x[1] for x in pairs[: max(1, int(q * len(pairs)))]], draws=2000)
        out[f"direction-neutral pair, top {q:.0%}"] = {"n": s["n"], "S1": s["mean_net_r"], "S3": s["paired_diff_vs_random"], "S3_ci95": s["paired_diff_ci95"]}
    return out


# ----------------------------------------------------------------------------- RQ-20261027-fe57-03 (registered before the look)
FADE_FOLDS = (3, 4, 5, 6)          # the era's pre-DEV test folds: the DEV-found tail was never scored there
FADE_QS = (0.01, 0.002)            # the two tails seen on DEV; Bonferroni over them
FADE_BAR = 0.25


def fade_rows(rows: list, pt: np.ndarray, q: float) -> list:
    """The top-q actions by prediction, each REPLACED by the opposite-side action at the same cutoff, symbol and
    geometry (the fade), in cluster_stats' shape."""
    opp = {(r["cutoff"], r["symbol"], r["geom"], r["side"]): r for r in rows}
    out = []
    for j in np.nonzero(pt >= np.quantile(pt, 1 - q))[0]:
        r = rows[j]
        o = opp.get((r["cutoff"], r["symbol"], r["geom"], "short" if r["side"] == "long" else "long"))
        if o is not None:
            out.append({"week": o["week"], "net_r": o["net_r"], "days": o["days"], "diff": o["y"]})
    return out


def fade_test(cutoffs, acts) -> dict:
    X, _ = ce.feature_rows(cutoffs, acts, "P+")
    p = ce.walk_forward(acts, X, "ridge")
    te = np.array([r["fold"] in FADE_FOLDS for r in acts])
    rows = [acts[j] for j in np.nonzero(te)[0]]
    pt = p[te]
    a = ce.ALPHA / len(FADE_QS)
    res, ok = {}, []
    for q in FADE_QS:
        fr = fade_rows(rows, pt, q)
        st = d.cluster_stats(fr)
        lo, hi = ce.cluster_ci(fr, "diff", a)
        s3 = st.get("paired_diff_vs_random")
        passed = bool(s3 is not None and s3 >= FADE_BAR and lo > 0 and st["mean_net_r"] > 0)
        ok.append(passed)
        res[f"fade top {q:.1%}"] = {"n": st["n"], "S1": st["mean_net_r"], "S3": s3, "S3_ci95": st.get("paired_diff_ci95"),
                                    "S3_ci_corrected": [lo, hi], "pass": passed}
    res["verdict"] = "pass" if any(ok) else "fail"
    res["read_state"] = "measured" if rows else "no_data"
    return res


def main(argv=None) -> int:
    import pickle
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("costs")
    c.add_argument("--klines", required=True)
    c.add_argument("--out", required=True)
    lv = sub.add_parser("levers")
    lv.add_argument("--ceiling", required=True)
    lv.add_argument("--learner", default="ridge")
    lv.add_argument("--out", required=True)
    fd = sub.add_parser("fade", help="RQ-20261027-fe57-03: build the era (if absent) and run the registered fade test")
    fd.add_argument("--ceiling", required=True, help="an era build directory; built here when it has no actions.pkl")
    fd.add_argument("--candles", required=True)
    fd.add_argument("--funding", required=True)
    fd.add_argument("--fetch", action="store_true")
    fd.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.mode == "fade":
        src = Path(a.ceiling)
        if not (src / "actions.pkl").exists():
            from datetime import datetime, timezone
            if a.fetch:
                d.CANDLE_SINCE = datetime(2020, 8, 1, tzinfo=timezone.utc)
                syms = [u["symbol"] for u in d.parse_universe()[0]]
                Path(a.candles).mkdir(parents=True, exist_ok=True)
                d.fetch_market(Path(a.candles), syms)
                ce.fetch_funding(Path(a.funding), syms, datetime(2020, 8, 1, tzinfo=timezone.utc), d.WINDOW_END)
            ce.main(["build", "--era", "--out", str(src), "--candles", a.candles, "--funding", a.funding])
        meta = json.loads((src / "meta.json").read_text())
        if meta["mode"] != "era":
            raise SystemExit("fade needs an --era build")
        ce.TEST_FOLDS = tuple(meta["test_folds"])
        res = fade_test(pickle.loads((src / "cutoffs.pkl").read_bytes()), pickle.loads((src / "actions.pkl").read_bytes()))
        d._write_verdict(Path(a.out), res, "era folds 3-6 (2022-01-01..2023-10-25): ridge P+ walk-forward, top-q actions faded",
                         res[f"fade top {FADE_QS[0]:.1%}"]["n"], "registered RQ-20261027-fe57-03", None, None)
        print(json.dumps({"verdict": res["verdict"]}))
        return 0
    if a.mode == "costs":
        res = {"population": "Binance Vision USD-M perp 1m klines in --klines; non-overlapping returns per hold; median over symbols",
               "scenarios_bps_roundtrip": SCENARIOS, "funding_bps_per_8h": FUNDING_BPS_PER_8H, "rows": cost_table(Path(a.klines))}
    else:
        src = Path(a.ceiling)
        meta = json.loads((src / "meta.json").read_text()) if (src / "meta.json").exists() else {"mode": "dev"}
        if meta["mode"] == "era":
            ce.TEST_FOLDS = tuple(meta["test_folds"])
        res = {"learner": a.learner, "mode": meta["mode"], "test_folds": list(ce.TEST_FOLDS),
               "levers": lever_table(pickle.loads((src / "cutoffs.pkl").read_bytes()), pickle.loads((src / "actions.pkl").read_bytes()), a.learner)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({"wrote": a.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
