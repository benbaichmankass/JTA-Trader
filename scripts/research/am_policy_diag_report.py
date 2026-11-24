#!/usr/bin/env python3
# wiring: manual-only - a session runs it over the diag.jsonl scripts/research/am_policy_diag.py writes (the Stage B diagnosis, docs/research/am-v2-stage-b-diagnosis-2026-11-24.md); tests/test_am_action_value.py
"""Summarise am_policy_diag.py output: where the policy's actions fire vs the random controls', per-trade deltas by HOLD outcome, bank fills, and
the single-action ex-post value against state and head scores (deciles). Read-only; prints JSON."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from statistics import mean


def _m(xs):
    return round(mean(xs), 4) if xs else None


def _dec(pairs, n=5):
    """pairs (score, value) -> per-quantile-bin mean value."""
    if not pairs:
        return []
    pairs = sorted(pairs)
    out = []
    for b in range(n):
        seg = pairs[b * len(pairs) // n:(b + 1) * len(pairs) // n]
        if seg:
            out.append({"score_lo": round(seg[0][0], 4), "score_hi": round(seg[-1][0], 4), "n": len(seg), "mean_value": _m([v for _, v in seg])})
    return out


def report(path: str) -> dict:
    with open(path) as fh:
        recs = [json.loads(ln) for ln in fh if ln.strip()]
    res = {"n_trades": len(recs), "hold_mean_net_r": _m([r["base"] for r in recs])}
    for cls in ("tighten", "bank", "loosen"):
        cells = [(r, r["cls"].get(cls, {"n": 0})) for r in recs]
        fired = [(r, c) for r, c in cells if c["n"]]
        if not fired:
            continue
        by_reason = defaultdict(lambda: {"pol": [], "ctl": []})
        for r, c in fired:
            g = by_reason[r["base_reason"]]
            g["pol"].append(c["pol"])
            g["ctl"].append(mean(c["ctl"]))
        pf = [f["open_r"] for _, c in fired for f in c["fire"]]
        cf = [f["open_r"] for _, c in fired for f in c["ctl_fire"]]
        pl = [f["lvl_r"] for _, c in fired for f in c["fire"]]
        cl = [f["lvl_r"] for _, c in fired for f in c["ctl_fire"]]
        first_k_p = [c["fire"][0]["k"] for _, c in fired]
        first_k_c = [min(f["k"] for f in c["ctl_fire"]) for _, c in fired if c["ctl_fire"]]
        d = {"n_fired": len(fired), "share_fired": round(len(fired) / len(recs), 4), "mean_actions": _m([c["n"] for _, c in fired]),
             "sum_pol_delta_r": round(sum(c["pol"] for _, c in fired), 3), "sum_ctl_delta_r": round(sum(mean(c["ctl"]) for _, c in fired), 3),
             "mean_pol_delta": _m([c["pol"] for _, c in fired]), "mean_ctl_delta": _m([mean(c["ctl"]) for _, c in fired]),
             "fire_open_r": {"policy_mean": _m(pf), "control_mean": _m(cf), "policy_share_below_0": _m([x < 0 for x in pf]), "control_share_below_0": _m([x < 0 for x in cf])},
             "level_r": {"policy_mean": _m(pl), "control_mean": _m(cl), "policy_share_below_entry": _m([x < 0 for x in pl]), "control_share_below_entry": _m([x < 0 for x in cl])},
             "first_action_k": {"policy_mean": _m(first_k_p), "control_mean": _m(first_k_c)},
             "by_hold_exit_reason": {k: {"n": len(v["pol"]), "mean_pol": _m(v["pol"]), "mean_ctl": _m(v["ctl"])} for k, v in by_reason.items()}}
        if cls == "bank":
            pb = [c["bank_fill_r"] for _, c in fired]
            cb = [x for _, c in fired for x in c["ctl_bank_fill_r"]]
            d["bank_fill"] = {"policy_fill_rate": _m([x is not None for x in pb]), "control_fill_rate": _m([x is not None for x in cb]),
                              "policy_mean_fill_r": _m([x for x in pb if x is not None]), "control_mean_fill_r": _m([x for x in cb if x is not None]),
                              "policy_fill_below_entry": _m([x < 0 for x in pb if x is not None]), "control_fill_below_entry": _m([x < 0 for x in cb if x is not None])}
        res[cls] = d
    singles = [(r, s) for r in recs for s in r.get("single", [])]
    sa = {"n_rows": len(singles)}
    names = sorted({n for _, s in singles for n in s["d"]})
    for n in names:
        vals = [(r, s) for r, s in singles if n in s["d"]]
        sa[n] = {"n": len(vals), "mean_delta": _m([s["d"][n] for _, s in vals]),
                 "share_positive": _m([s["d"][n] > 0 for _, s in vals]),
                 "by_open_r": _dec([(s["open_r"], s["d"][n]) for _, s in vals]),
                 "by_p_stop": _dec([(s["p_stop"], s["d"][n]) for _, s in vals]),
                 "by_q50": _dec([(s["q50"], s["d"][n]) for _, s in vals]),
                 "by_bars_open": _dec([(s["bars_open"], s["d"][n]) for _, s in vals]),
                 "by_p_dip": _dec([(s["p_dip"], s["d"][n]) for _, s in vals])}
    res["single_action_ex_post"] = sa
    fam = defaultdict(lambda: defaultdict(list))
    for r, s in singles:
        f = family(r["st"])
        for n, v in s["d"].items():
            fam[f][n].append(v)
    res["single_by_family"] = {f: {n: {"n": len(v), "mean": _m(v)} for n, v in d.items()} for f, d in fam.items()}
    return res


def family(strategy: str) -> str:
    s = str(strategy)
    if "scalp" in s:
        return "scalp"
    if "pullback" in s:
        return "pullback"
    if "donchian" in s or "trend" in s:
        return "trend"
    if "breakout" in s or "squeeze" in s:
        return "breakout"
    return "other"


if __name__ == "__main__":
    print(json.dumps(report(sys.argv[1]), indent=1))
