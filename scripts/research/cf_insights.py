#!/usr/bin/env python3
# wiring: manual-only - CF-INSIGHTS: mines per-job counterfactual shards (cf_bulk, arm_set extended): python3 scripts/research/cf_insights.py --shards <dir> --out <dir>
"""cf_insights: what the per-job counterfactual outputs say, beyond the per-leg best arm.

Input: a directory of ``cf_bulk`` shard ``*.jsonl.gz`` (``--arm-set extended`` for the entry-side / management / context sections).
Everything is IN-SAMPLE discovery; every number carries its unique-trade n; CIs are WEEK-BLOCK bootstraps over UNIQUE trades
(symbol, timeframe, entry time, side) so overlapping sweep jobs cannot inflate n and cross-symbol clustering in time is respected.
R of an arm is in ITS OWN stop distance at a constant money risk (``cf_core.net_of``), so a wider stop is not more risk.

Sections (``analyze``): units/dedupe, stop curve, management/trail, LEAVES_R decomposition, entry-side, slices, per-family best robust arm.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import gzip
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

N_BOOT = 300
SEED = 5
MIN_N = 500


def family(strategy: Any) -> str:
    s = str(strategy)
    return "trend_donchian" if s.startswith("trend_donchian") else s


def load(shards_dir: str) -> List[dict]:
    rows: List[dict] = []
    for f in sorted(glob.glob(str(Path(shards_dir) / "*.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                c = r.get("cf") or {}
                if c.get("status") != "graded":
                    continue
                a = c["arms"]
                arm: Dict[str, Optional[float]] = {}
                for x in a.get("alt_brackets") or []:
                    if x.get("net_r") is not None:
                        arm[f"sl{x['sl_mult']:g}_tp{x['tp_r']:g}"] = x["net_r"]
                for fam in ("less_management", "more_management"):
                    for x in a.get(fam) or []:
                        if x.get("net_r") is not None:
                            arm[x["arm_id"]] = x["net_r"]
                arm.update(c.get("extended") or {})
                po = c.get("post_exit") or {}
                rows.append({"k": r["trade_key"], "strat": r.get("strategy"), "fam": family(r.get("strategy")), "sym": r.get("symbol"),
                             "tf": r.get("timeframe"), "dir": r.get("direction"), "et": r.get("entry_time"), "rep": a.get("replayed_actual_net_r"),
                             "arm": arm, "ctx": c.get("context") or {}, "post_mfe": po.get("mfe_r"), "post_mae": po.get("mae_r"),
                             "pv": (po.get("verdict") or {}).get("verdict"), "rdiff": (po.get("verdict") or {}).get("r_diff"), "gap": (c.get("fidelity") or {}).get("abs_gap_r")})
    return rows


def dedupe(rows: Iterable[dict]) -> List[dict]:
    """One job per unique trade (symbol, timeframe, entry time, side); the lowest trade_key wins, deterministically."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["k"]):
        key = (r["sym"], r["tf"], r["et"], r["dir"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _week(et: Any) -> int:
    y, w, _ = dt.datetime.fromisoformat(str(et)[:19]).isocalendar()
    return y * 100 + w


def block_ci(values: np.ndarray, weeks: np.ndarray, n_boot: int = N_BOOT) -> Tuple[float, float, float, int]:
    """(mean, lo95, hi95, n) of the non-NaN ``values``, resampling whole ISO weeks."""
    m = ~np.isnan(values)
    n = int(m.sum())
    if n == 0:
        return float("nan"), float("nan"), float("nan"), 0
    uw, inv = np.unique(weeks, return_inverse=True)
    s = np.bincount(inv, weights=np.where(m, values, 0.0), minlength=len(uw))
    c = np.bincount(inv, weights=m.astype(float), minlength=len(uw))
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(n_boot):
        p = rng.integers(0, len(uw), len(uw))
        tot = c[p].sum()
        bs.append(s[p].sum() / tot if tot else np.nan)
    return float(s.sum() / c.sum()), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), n


def delta(rows: Sequence[dict], arm: str) -> np.ndarray:
    return np.array([(r["arm"][arm] - r["rep"]) if (arm in r["arm"] and r["arm"][arm] is not None and r["rep"] is not None) else np.nan for r in rows])


def arm_table(rows: Sequence[dict], arms: Sequence[str], min_n: int = MIN_N) -> List[dict]:
    wk = np.array([_week(r["et"]) for r in rows])
    out = []
    for a in arms:
        d = delta(rows, a)
        mu, lo, hi, n = block_ci(d, wk)
        if n >= min_n:
            out.append({"arm": a, "n_unique": n, "mean_delta_r": round(mu, 4), "ci95": [round(lo, 4), round(hi, 4)],
                        "share_improved": round(float(np.nanmean(d > 0)), 4)})
    return sorted(out, key=lambda x: -x["mean_delta_r"])


def all_arms(rows: Sequence[dict]) -> List[str]:
    return sorted({k for r in rows for k in r["arm"]})


def stop_curve(rows: Sequence[dict]) -> Dict[str, Any]:
    """Mean delta vs the replayed harness trade by stop multiple (averaged over the TP cells and the no-TP variant)."""
    tab = {t["arm"]: t for t in arm_table(rows, [a for a in all_arms(rows) if "sl" in a and ("tp" in a or "notp" in a)])}
    by: Dict[str, List[float]] = collections.defaultdict(list)
    notp: Dict[str, float] = {}
    for a, t in tab.items():
        core = a.replace("ext_", "")
        m = core.split("_")[0][2:].rstrip("x")
        (notp.__setitem__(m, t["mean_delta_r"]) if "notp" in a else by[m].append(t["mean_delta_r"]))
    return {"with_tp_mean_by_stop_mult": {k: round(float(np.mean(v)), 4) for k, v in sorted(by.items(), key=lambda kv: float(kv[0]))},
            "no_tp_by_stop_mult": dict(sorted(notp.items(), key=lambda kv: float(kv[0])))}


def decompose_leaves_r(rows: Sequence[dict]) -> List[dict]:
    """Where the post-exit R sits: by replayed exit reason x pre-exit MFE bucket x post-exit verdict (needs arm_set extended)."""
    g: Dict[Tuple[str, str], List[dict]] = collections.defaultdict(list)
    for r in rows:
        mfe = r["ctx"].get("mfe_pre_r")
        if mfe is None:
            continue
        b = "<0.5R" if mfe < 0.5 else "0.5-1R" if mfe < 1 else "1-2R" if mfe < 2 else ">=2R"
        g[(str(r["ctx"].get("replay_exit")), b)].append(r)
    out = []
    for (ex, b), rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        pm = [x["rdiff"] for x in rs if x["rdiff"] is not None]       # post-exit r_diff: R left on the table (post-exit MFE is not populated in cf_trade/1)
        pv = collections.Counter(x["pv"] for x in rs)
        out.append({"exit": ex, "mfe_pre_bucket": b, "n_unique": len(rs), "mean_rep_r": round(float(np.mean([x["rep"] for x in rs if x["rep"] is not None])), 4),
                    "mean_post_exit_r_diff": None if not pm else round(float(np.mean(pm)), 4),
                    "share_exited_early": round(pv.get("exited_early", 0) / max(1, sum(v for k, v in pv.items() if k)), 4)})
    return out


def entry_side(rows: Sequence[dict]) -> List[dict]:
    """Entry arms: delta on FILLED trades, the fill rate, and what the unfilled trades would have made (the cost of skipping them)."""
    out = []
    for a in sorted({k for r in rows for k in r["arm"] if k.startswith("ext_delay") or k.startswith("ext_limit")} | {k for r in rows for k in r["ctx"].get("_x", [])}):
        have = [r for r in rows if a in r["arm"]]
        if not have:
            continue
        filled = [r for r in have if r["arm"][a] is not None and r["rep"] is not None]
        unfilled = [r for r in have if r["arm"][a] is None and r["rep"] is not None]
        wk = np.array([_week(r["et"]) for r in filled])
        d = np.array([r["arm"][a] - r["rep"] for r in filled])
        mu, lo, hi, n = block_ci(d, wk) if len(filled) else (float("nan"),) * 3 + (0,)
        out.append({"arm": a, "n_trades": len(have), "fill_rate": round(len(filled) / len(have), 4), "n_filled": len(filled),
                    "mean_delta_filled_r": round(mu, 4), "ci95": [round(lo, 4), round(hi, 4)],
                    "mean_r_of_unfilled_trades": None if not unfilled else round(float(np.mean([r["rep"] for r in unfilled])), 4),
                    "net_effect_per_signal_r": None if not filled else round((float(np.sum(d)) - float(np.sum([r["rep"] for r in unfilled]))) / len(have), 4)})
    return out


def slices(rows: Sequence[dict], arm: str) -> Dict[str, List[dict]]:
    """Delta of ``arm`` by side, volatility tercile (ATR% within symbol), hour block, weekday and holding time."""
    sl: Dict[str, List[dict]] = {}
    atr_by_sym: Dict[str, List[float]] = collections.defaultdict(list)
    for r in rows:
        if r["ctx"].get("atr_pct") is not None:
            atr_by_sym[r["sym"]].append(r["ctx"]["atr_pct"])
    cuts = {s: (np.percentile(v, 33.3), np.percentile(v, 66.7)) for s, v in atr_by_sym.items() if len(v) > 30}

    def vol(r):
        a, c = r["ctx"].get("atr_pct"), cuts.get(r["sym"])
        return None if a is None or c is None else ("low_vol" if a <= c[0] else "mid_vol" if a <= c[1] else "high_vol")
    keyers = {"side": lambda r: r["dir"], "volatility": vol,
              "hour_block": lambda r: None if r["ctx"].get("hour_utc") is None else f"{r['ctx']['hour_utc'] // 6 * 6:02d}-{r['ctx']['hour_utc'] // 6 * 6 + 5:02d}h",
              "weekday": lambda r: r["ctx"].get("dow"),
              "holding": lambda r: None if r["ctx"].get("bars_held") is None else ("<=3 bars" if r["ctx"]["bars_held"] <= 3 else "4-12" if r["ctx"]["bars_held"] <= 12 else ">12")}
    for name, fn in keyers.items():
        groups: Dict[Any, List[dict]] = collections.defaultdict(list)
        for r in rows:
            k = fn(r)
            if k is not None:
                groups[k].append(r)
        tab = []
        for k, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
            wk = np.array([_week(r["et"]) for r in rs])
            mu, lo, hi, n = block_ci(delta(rs, arm), wk)
            if n >= 200:
                tab.append({"slice": k, "n_unique": n, "mean_delta_r": round(mu, 4), "ci95": [round(lo, 4), round(hi, 4)]})
        sl[name] = tab
    return sl


def analyze(shards_dir: str, min_n: int = MIN_N) -> Dict[str, Any]:
    raw = load(shards_dir)
    uniq = dedupe(raw)
    res: Dict[str, Any] = {"schema": "cf_insights/1", "n_jobs_graded": len(raw), "n_unique_trades": len(uniq),
                           "units": "arm R is in the arm's own stop distance at constant money risk (cf_core.net_of): a wider stop is not more risk",
                           "provenance": "ESTIMATED", "families": {}}
    by = collections.defaultdict(list)
    for r in uniq:
        by[r["fam"]].append(r)
    for fam, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < min_n:
            continue
        arms = all_arms(rs)
        tab = arm_table(rs, arms, min_n)
        best = tab[0] if tab else None
        res["families"][fam] = {"n_unique_trades": len(rs), "mean_replay_r": round(float(np.mean([r["rep"] for r in rs if r["rep"] is not None])), 4),
                                "stop_curve": stop_curve(rs), "top_arms": tab[:8], "worst_arms": tab[-4:],
                                "entry_side": entry_side(rs), "leaves_r": decompose_leaves_r(rs)[:12],
                                "slices_of_best": None if not best else {"arm": best["arm"], **slices(rs, best["arm"])}}
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shards", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    a = ap.parse_args(argv)
    res = analyze(a.shards, a.min_n)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "insights.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({"n_jobs_graded": res["n_jobs_graded"], "n_unique_trades": res["n_unique_trades"], "families": list(res["families"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
