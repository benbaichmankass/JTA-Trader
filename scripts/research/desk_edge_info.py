#!/usr/bin/env python3
# wiring: manual-only - run by the DESK-EDGE-PROGRAM lane (manager 2026-10-27 18:09Z, doc section 4.7); no schedule consumes it.
"""DESK-EDGE-PROGRAM section 4.7 -- does NEW information (positioning, basis, order-book depth, cross-market) carry GROSS
timing at 5-60 minute holds that survives a 1-5 bar decision delay? Token-free; free Binance Vision USD-M data only.

Rule, constants and the data inventory: docs/research/desk-edge-program-2026-10-27.md section 4.7 (registered before this
file ran). Labels and base features come from a `desk_edge_1m.py build --delay D --holds 5,15,30,60` directory (the
driver's engine, the measured 12.3 bps taker stack); this module adds feature groups and the two statistics of checklist
row DESK-S3-VOL-MATCHED-BASELINE as PRIMARY:

  VM-S3        net R minus the mean net R of every action in the same (symbol, side, hold, driver fold, ATR%-decile)
               cell: the hourly grid IS the random-time population, so this is a volatility-matched random baseline
  gross excess gross R (before cost) minus that cell's mean gross R

  run --build DIR --metrics DIR --premium DIR --depth DIR --evidence DIR
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import json
import math
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_edge_ceiling as ce  # noqa: E402
from scripts.research import desk_edge_1m as m1  # noqa: E402

INFO_MIN_GROSS = 0.10
USEFUL_VM_S3 = 0.25
FEATURE_SETS = ("BASE", "BASE+metrics", "BASE+basis", "BASE+depth", "BASE+all")
LEARNERS = ("ridge", "gbdt")
N_FAMILY = 4 * len(LEARNERS) * len(FEATURE_SETS)          # holds x learners x sets = 40
N_DECILES = 10


# ----------------------------------------------------------------------------- data (every series sorted by time)
def _zip_csv_lines(f: str) -> List[str]:
    z = zipfile.ZipFile(f)
    (name,) = z.namelist()
    return z.read(name).decode().splitlines()


def _ts(s: str) -> int:
    return int(datetime.strptime(s.strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def load_metrics(src: Path, sym: str) -> Optional[Dict[str, np.ndarray]]:
    files = sorted(glob.glob(str(src / f"{sym}-metrics-*.zip")))
    print(f"load_metrics: {sym}: reading all {len(files)} daily files", file=sys.stderr)
    rows = []
    for f in files:
        for ln in _zip_csv_lines(f)[1:]:
            p = ln.split(",")
            try:
                rows.append((_ts(p[0]), float(p[2]), float(p[4]), float(p[5]), float(p[6]), float(p[7])))
            except (ValueError, IndexError):
                continue                                    # a blank field in the vendor file: the row is skipped, counted below
    if not rows:
        return None
    a = np.array(sorted(rows))
    return {"t": a[:, 0].astype(np.int64), "oi": a[:, 1], "top_acct": a[:, 2], "top_pos": a[:, 3], "ls_acct": a[:, 4], "taker": a[:, 5]}


def load_premium(src: Path, sym: str) -> Optional[Dict[str, np.ndarray]]:
    files = sorted(glob.glob(str(src / f"{sym}-1m-*.zip")))
    print(f"load_premium: {sym}: reading all {len(files)} monthly files", file=sys.stderr)
    rows = []
    for f in files:
        for ln in _zip_csv_lines(f):
            if ln and not ln.startswith("open_time"):
                p = ln.split(",")
                rows.append((int(p[0]) // 1000 + 60, float(p[4])))     # stamped at the bar CLOSE: usable at or after it
    if not rows:
        return None
    a = np.array(sorted(rows))
    return {"t": a[:, 0].astype(np.int64), "prem": a[:, 1]}


def load_depth(src: Path, sym: str) -> Optional[Dict[str, np.ndarray]]:
    """Per snapshot: bid and ask notional within 1/2/5% of mid (bookDepth `percentage` < 0 = bid side)."""
    files = sorted(glob.glob(str(src / f"{sym}-bookDepth-*.zip")))
    print(f"load_depth: {sym}: reading all {len(files)} daily files", file=sys.stderr)
    snap: Dict[int, Dict[float, float]] = collections.defaultdict(dict)
    for f in files:
        for ln in _zip_csv_lines(f)[1:]:
            p = ln.split(",")
            try:
                snap[_ts(p[0])][float(p[1])] = float(p[3])
            except (ValueError, IndexError):
                continue
    if not snap:
        return None
    t = np.array(sorted(snap), dtype=np.int64)
    out = {"t": t}
    for b in (1.0, 2.0, 5.0):
        bid = np.array([snap[x].get(-b, np.nan) for x in t])
        ask = np.array([snap[x].get(b, np.nan) for x in t])
        out[f"imb{int(b)}"] = (bid - ask) / (bid + ask)
        out[f"dep{int(b)}"] = np.log(bid + ask)
    return out


def _at(series: Dict[str, np.ndarray], t: int, key: str, lag_s: int = 0) -> float:
    """The last value at or before t - lag_s (point in time); NaN when none."""
    j = int(np.searchsorted(series["t"], t - lag_s, side="right")) - 1
    return float(series[key][j]) if j >= 0 else float("nan")


def info_features(c: int, sym: str, met, prem, dep) -> Dict[str, float]:
    o: Dict[str, float] = {}
    if met is not None:
        oi = _at(met, c, "oi")
        o["oi_chg60"] = math.log(oi / _at(met, c, "oi", 3600)) if oi > 0 and _at(met, c, "oi", 3600) > 0 else float("nan")
        o["oi_chg240"] = math.log(oi / _at(met, c, "oi", 14400)) if oi > 0 and _at(met, c, "oi", 14400) > 0 else float("nan")
        for k in ("top_acct", "top_pos", "ls_acct", "taker"):
            v, v1 = _at(met, c, k), _at(met, c, k, 3600)
            o[f"m_{k}"] = math.log(v) if v > 0 else float("nan")
            o[f"m_{k}_chg60"] = math.log(v / v1) if v > 0 and v1 > 0 else float("nan")
    if prem is not None:
        p0 = _at(prem, c, "prem")
        o["prem_bps"] = p0 * 1e4
        o["prem_chg15"] = (p0 - _at(prem, c, "prem", 900)) * 1e4
        o["prem_chg60"] = (p0 - _at(prem, c, "prem", 3600)) * 1e4
    if dep is not None:
        for b in (1, 2, 5):
            o[f"imb{b}"] = _at(dep, c, f"imb{b}")
        o["imb1_chg15"] = o["imb1"] - _at(dep, c, "imb1", 900)
        j = int(np.searchsorted(dep["t"], c, side="right"))
        w = dep["dep1"][max(0, j - 2600): j]
        o["dep1_rel"] = float(dep["dep1"][j - 1] - np.nanmean(w)) if j > 0 and np.isfinite(w).any() else float("nan")
    return o


GROUPS = {
    "metrics": ("oi_chg60", "oi_chg240", "m_top_acct", "m_top_pos", "m_ls_acct", "m_taker", "m_top_acct_chg60", "m_top_pos_chg60",
                "m_ls_acct_chg60", "m_taker_chg60"),
    "basis": ("prem_bps", "prem_chg15", "prem_chg60"),
    "depth": ("imb1", "imb2", "imb5", "imb1_chg15", "dep1_rel"),
}
SIGNED = ("m_top_acct", "m_top_pos", "m_ls_acct", "m_taker", "m_top_acct_chg60", "m_top_pos_chg60", "m_ls_acct_chg60", "m_taker_chg60",
          "prem_bps", "prem_chg15", "prem_chg60", "imb1", "imb2", "imb5", "imb1_chg15")
CROSS = ("prem_chg60", "imb1", "oi_chg60", "m_taker")


# ----------------------------------------------------------------------------- the volatility-matched statistics
def vm_labels(acts: List[dict], ex: Dict[int, Dict[str, Dict[str, float]]]) -> None:
    """Adds y_vm (net minus the cell mean net) and g_vm (gross minus the cell mean gross) to every action, in place.
    Cell = (symbol, side, hold, driver fold, ATR%-decile of that symbol over the build's cutoffs)."""
    edges = {}
    for s in {r["symbol"] for r in acts}:
        v = np.array([ex[c][s]["atr_pct"] for c in ex if s in ex[c]])
        edges[s] = np.quantile(v[np.isfinite(v)], np.linspace(0, 1, N_DECILES + 1)[1:-1])
    cell = collections.defaultdict(list)
    for j, r in enumerate(acts):
        dec = int(np.searchsorted(edges[r["symbol"]], ex[r["cutoff"]][r["symbol"]]["atr_pct"]))
        r["vol_dec"] = dec
        cell[(r["symbol"], r["side"], r["hold"], r["fold"], dec)].append(j)
    for ix in cell.values():
        mn = float(np.mean([acts[j]["net_r"] for j in ix]))
        mg = float(np.mean([acts[j]["net_r"] + acts[j]["cost_r"] for j in ix]))
        for j in ix:
            acts[j]["y_vm"] = acts[j]["net_r"] - mn
            acts[j]["g_vm"] = acts[j]["net_r"] + acts[j]["cost_r"] - mg


def matrix(acts, ex, extra: Dict[Tuple[int, str], Dict[str, float]], groups: Tuple[str, ...]) -> np.ndarray:
    keys, idx, vecs, names = {}, [], [], None
    want = [k for g in groups for k in GROUPS[g]]
    for r in acts:
        k = (r["cutoff"], r["symbol"], r["side"])
        if k not in keys:
            f = m1.action_features(ex[r["cutoff"]], r["symbol"], r["side"], r["cutoff"], m1.HOLDS_MIN[0])
            f.pop("hold"), f.pop("log_hold")
            sg = 1.0 if r["side"] == "long" else -1.0
            e = extra.get((r["cutoff"], r["symbol"]), {})
            for n in want:
                v = e.get(n, float("nan"))
                f[f"x_{n}"] = sg * v if n in SIGNED else v
            if "all" in groups or len(groups) == 3:
                b = extra.get((r["cutoff"], "BTCUSDT"), {})
                for n in CROSS:
                    v = b.get(n, float("nan"))
                    f[f"btc_x_{n}"] = sg * v if n in SIGNED else v
            if names is None:
                names = sorted(f)
            keys[k] = len(vecs)
            vecs.append([f.get(n, float("nan")) for n in names])
        idx.append(keys[k])
    base = np.array(vecs, dtype=float)[np.array(idx)]
    h = np.array([r["hold"] for r in acts], dtype=float)
    return np.column_stack([base, h, np.log(h)])


def evaluate_hold(rows: List[dict], pred: np.ndarray, alpha: float) -> Dict[str, Any]:
    picks = ce.policy_picks(rows, pred)
    out: Dict[str, Any] = {"n": len(picks)}
    for name, key in (("VM_S3", "y_vm"), ("gross_excess", "g_vm"), ("e535_S3", "y")):
        sr = [{"week": rows[j]["week"], "net_r": rows[j]["net_r"], "days": rows[j]["days"], "diff": rows[j][key]} for j in picks]
        st = d.cluster_stats(sr, draws=2000)
        out[name] = st.get("paired_diff_vs_random")
        if name != "e535_S3":
            out[f"{name}_ci_corrected"] = list(ce.cluster_ci(sr, "diff", alpha, draws=3000))
        out["S1"] = st["mean_net_r"]
    out["verdict"] = ("useful" if out["gross_excess_ci_corrected"][0] > 0 and out["gross_excess"] >= INFO_MIN_GROSS and out["VM_S3"] >= USEFUL_VM_S3
                      and out["VM_S3_ci_corrected"][0] > 0 and out["S1"] > 0 else
                      "information" if out["gross_excess"] >= INFO_MIN_GROSS and out["gross_excess_ci_corrected"][0] > 0 else "none")
    return out


def run_build(build: Path, met, prem, dep, alpha: float, controls: bool) -> Dict[str, Any]:
    import pickle
    acts = pickle.loads((build / "actions.pkl").read_bytes())
    ex = pickle.loads((build / "features.pkl").read_bytes())
    vm_labels(acts, ex)
    extra = {}
    for c in ex:
        for s in ex[c]:
            extra[(c, s)] = info_features(c, s, met.get(s), prem.get(s), dep.get(s))
    vm_rows = [dict(r, y=r["y_vm"], y_e535=r["y"]) for r in acts]          # learners train on VM-S3
    te = np.array([r["fold"] in ce.TEST_FOLDS for r in acts])
    test = [dict(acts[j]) for j in np.nonzero(te)[0]]
    hold = np.array([r["hold"] for r in test])
    res: Dict[str, Any] = {}
    sets = {"BASE": (), "BASE+metrics": ("metrics",), "BASE+basis": ("basis",), "BASE+depth": ("depth",), "BASE+all": ("metrics", "basis", "depth")}
    Xall = None
    for name, groups in sets.items():
        X = matrix(acts, ex, extra, groups)
        if name == "BASE+all":
            Xall = X
        for lr in LEARNERS:
            p = ce.walk_forward(vm_rows, X, lr)[te]
            for h in sorted(set(hold.tolist())):
                m = np.nonzero(hold == h)[0]
                res.setdefault(str(h), {})[f"{name}/{lr}"] = evaluate_hold([test[j] for j in m], p[m], alpha)
            print(json.dumps({"set": name, "learner": lr, "gross_excess": {h: round(v[f'{name}/{lr}']['gross_excess'], 4) for h, v in res.items()}}), flush=True)
    ctl = {}
    if controls:
        y = np.array([r["y_vm"] for r in acts])
        planted = y + np.random.default_rng(m1.SEED + 3).normal(0, 2.0 * y.std(), len(y))
        g = np.array([r["g_vm"] for r in acts])
        for cname, kw in (("planted_signal", {"extra_col": planted}), ("shuffled_labels", {"label_noise": "shuffle"})):
            p = ce.walk_forward(vm_rows, Xall, "gbdt", **kw)[te]
            ctl[cname] = {str(h): evaluate_hold([test[j] for j in np.nonzero(hold == h)[0]], p[hold == h], alpha)["verdict"] for h in sorted(set(hold.tolist()))}
        _ = g
    return {"per_hold": res, "controls": ctl, "actions": len(acts), "test_actions": len(test),
            "coverage": {k: int(sum(1 for v in extra.values() if np.isfinite(v.get(f, float("nan"))))) for k, f in
                         (("metrics", "oi_chg60"), ("basis", "prem_bps"), ("depth", "imb1"))}, "cells_total": len(extra)}


def cmd_run(a: argparse.Namespace) -> int:
    d.SEC = m1.BAR_SEC
    ce.EMBARGO_H = m1.EMBARGO_BARS
    syms = list(d.REGISTERED_SYMBOLS)
    met = {s: load_metrics(Path(a.metrics), s) for s in syms}
    prem = {s: load_premium(Path(a.premium), s) for s in syms}
    dep = {s: load_depth(Path(a.depth), s) for s in syms}
    alpha = ce.ALPHA / N_FAMILY
    out: Dict[str, Any] = {"read_state": "measured", "design": {"family": N_FAMILY, "alpha_corrected": alpha, "info_min_gross": INFO_MIN_GROSS,
                                                                "useful_vm_s3": USEFUL_VM_S3, "sets": FEATURE_SETS, "learners": LEARNERS},
                           "data": {k: {s: (None if v[s] is None else int(len(v[s]["t"]))) for s in syms} for k, v in (("metrics", met), ("premium", prem), ("depth", dep))}}
    for b in a.build:
        meta = json.loads((Path(b) / "meta.json").read_text())
        out[f"delay{meta['delay_bars']}"] = run_build(Path(b), met, prem, dep, alpha, controls=(meta["delay_bars"] == 1))
    d1 = out.get("delay1", {}).get("per_hold", {})
    useful = [(h, k) for h, v in d1.items() for k, e in v.items() if e["verdict"] == "useful"]
    info = [(h, k) for h, v in d1.items() for k, e in v.items() if e["verdict"] == "information"]
    valid = bool(out.get("delay1", {}).get("controls")) and any(v == "information" or v == "useful" for v in out["delay1"]["controls"]["planted_signal"].values()) \
        and not any(v in ("information", "useful") for v in out["delay1"]["controls"]["shuffled_labels"].values())
    out["instrument_valid"] = valid
    out["verdict"] = "instrument_invalid" if not valid else ("useful" if useful else "information" if info else "none")
    out["useful"], out["information"] = useful, info
    d._write_verdict(Path(a.evidence), out, "new-information short-hold ceiling (doc 4.7)", out.get("delay1", {}).get("test_actions"),
                     f"verdict {out['verdict']}", None, None)
    print(json.dumps({"verdict": out["verdict"], "valid": valid, "useful": useful, "information": info}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--build", action="append", required=True, help="a desk_edge_1m build dir (repeat for delay 1 and 5)")
    r.add_argument("--metrics", required=True)
    r.add_argument("--premium", required=True)
    r.add_argument("--depth", required=True)
    r.add_argument("--evidence", required=True)
    r.set_defaults(fn=cmd_run)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
