#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-PACKET-REDESIGN (packet arms A/B/C on the DESK-EDGE-PROGRAM dev sample); no schedule consumes it.
"""DESK-PACKET-REDESIGN -- the arm runner: does the judge behave differently, and earn S3, when the packet stops
pre-digesting the market?

Design, arms and the pre-registered rule: docs/research/desk-packet-redesign-2026-10-27.md (committed before any
B or C packet was judged). Reuses, never re-implements:
  * the dev sample, the forced-rank cell protocol, SEL, the sequential decision and the top-pick policy:
    scripts/research/desk_edge_devloop.py (DESK-EDGE-PROGRAM section 5);
  * the engine, the random-entry baseline, weekly-cluster statistics (S3 = paired_diff_vs_random) and the
    proposal reader/scorer: scripts/research/desk_gen_replay_driver.py (units RQ-20261026-e535-*);
  * the packet modes: scripts/research/desk_packet_modes.py (A = today's packet, B = base rates removed, C = raw).

  build    --arm B|C --out DIR --candles DIR [--raw DIR] [--batch-size N]   packets + judge batches + protocol
  score    --arm A|B|C --out DIR --candles DIR --ranks F --sample F          per-arm measurements (registered set)
  compare  --out DIR --arm-dirs A=DIR,B=DIR,C=DIR                            contrasts vs A + the registered verdicts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_edge_devloop as dl  # noqa: E402
from scripts.research import desk_packet_modes as pm  # noqa: E402

# ----------------------------------------------------------------------------- registered constants (doc section 3)
S3_USEFUL = 0.25            # R: the operator's bar (DESK-EDGE-PROGRAM section 6.1): S3 >= +0.25 with the 95% CI lower > 0
CONTRAST_ALPHA = 0.05 / 2   # two contrasts (B-A, C-A), two-sided, Bonferroni
R2_BREAK = 0.50             # "breaks base-rate linearity": pooled R^2 < 0.50 AND median per-group R^2 < 0.50
R2_GROUP = 10               # packets per R^2 group, in sample order (V1's batch grain)
SEED = 20261027
DRAWS = 10_000
BATCH_B = 10
# Amendment 2 (2026-10-27, manager decision, registered before judging packets 51-100): a fixed size cap for arm C.
# A judge-facing C packet over MAX_C_CHARS is REFUSED (never judged, counted), never trimmed packet by packet. 24,000
# chars is about 1.2x the amended median (20,274) and above its max (22,725); with BATCH_C packets per batch it keeps
# every batch near the ~66k-token batches that were all analysed, far from the 286k-token batch that was not.
MAX_C_CHARS = 24_000
BATCH_C = 2                 # amendment 1: 5 large packets per batch invited skipped analysis

SUBAGENT_RULES = """
## Isolation (binding; a batch that breaks it is rejected and re-judged)
Use ONLY the Read tool on this one file and the Write tool on your one output file. Do not use Bash, Grep, Glob, any
script, calculator or code: read the data and reason over it yourself; a computed score is a rejected batch. Do not
open any other path. Analyse EVERY packet's own data before scoring it: a packet scored without reading its bars is a
rejected batch. Write every reply line for every packet in this file to the output file, then stop.
"""

PROTO_B_INTRO = ("You see ONE masked market scan packet. Symbols are aliases (re-drawn per packet), prices are rebased so each\n"
                 "alias's last close is 100, time is anchored in year 2000, volume and calendar are withheld. The strategies' book is\n"
                 "NOT shown, and this packet carries NO base-rate / forward-R history rows. Decide whether any alias offers a trade\n"
                 "worth taking over the next hours, net of costs.")
PROTO_C_INTRO = ("You see ONE masked RAW market packet: six aliases (re-drawn per packet; two of them are the two largest crypto\n"
                 "assets, unnamed), each with multi-timeframe OHLC bars before the decision time (1m, 5m, 1h, 4h, 1d), relative\n"
                 "volume and taker-buy share per bar, and the perpetual funding prints known at the decision time. There are NO\n"
                 "summaries and NO precomputed statistics or base rates: read the bars (high, low, close; the open is the previous close).\n"
                 "Prices are basis points from the alias's\n"
                 "last 1h close; a price LEVEL in your reply is on the rebased scale 100 x (1 + bps/10000), so the last close is\n"
                 "100. `atr_1h` is the 1h ATR(14) on that scale (the bracket below is defined in it). Calendar dates are withheld;\n"
                 "the session label is given. The strategies' book is NOT shown. Decide whether any alias offers a trade worth\n"
                 "taking over the next hours, net of costs.")
_A_INTRO = ("You see ONE masked market scan packet. Symbols are aliases\n(re-drawn per packet), prices are rebased so each alias's last close is 100, time is anchored in year 2000,\n"
            "volume and calendar are withheld. The strategies' book is NOT shown. Decide whether any alias offers a trade\nworth taking over the next hours, net of costs (the packet's `history` rows are net-of-cost forward-R base rates).")


def protocol(arm: str) -> str:
    """The judge protocol for an arm: the driver's protocol + the dev-loop rank addendum, with only the packet
    description changed (B: no base rates; C: raw bars). A is byte-identical to the V1 protocol."""
    base = d.JUDGE_PROTOCOL % {"cap": d.MAX_PER_PACKET, "sent": d.cdr.SENTINEL_R_FLOOR, "cap_pct": d.cdr.TP_VENUE_CAP_PCT * 100,
                               "reach": d.cdr.REACH_FLOOR, "minrisk": d.MIN_RISK_ATR} + dl.rank_addendum(dl.DEV_GEOM)
    if _A_INTRO not in base:
        raise AssertionError("the driver's protocol text changed; re-derive the arm intros")
    if arm == "A":
        return base
    out = base.replace(_A_INTRO, PROTO_B_INTRO if arm == "B" else PROTO_C_INTRO)
    if arm == "C":
        out = out.replace('"packet_id": "<meta.packet_id>"', '"packet_id": "<the PACKET id>"')
    return out


# ----------------------------------------------------------------------------- build
def build_arm(arm: str, mkt: Dict[str, d.Series], classes: Dict[str, List[str]], sample: List[dict],
              raw: Optional[pm.RawStore]) -> Tuple[List[dict], List[str], Dict[str, Any]]:
    """[{packet_id, packet, text}] in sample order, the refusals, and size stats. Every packet is rebuilt from the
    candles, its id asserted against the sample, its mode applied by the driver's builder; a packet that leaks, keeps
    a base-rate quantity (B, C) or fails the 1h consistency check (C) is refused, never judged."""
    out, refused, chars = [], [], []
    for s in sample:
        m, key = d.build_masked_packet(mkt, classes, s["cutoff_epoch"], s["index"], d.SEED, mode=arm, raw=raw)
        pid = m["meta"]["packet_id"] if arm != "C" else m["packet_id"]
        if pid != s["packet_id"]:
            raise SystemExit(f"packet drift on {s['packet_id']}")
        txt = json.dumps(m, sort_keys=True)
        why = []
        if arm in ("B", "C") and pm.base_rate_keys_left(m):
            why.append(f"base-rate quantity left: {pm.base_rate_keys_left(m)[:3]}")
        if arm == "C":
            why += pm.check_against_1h(m)
            why += [f"leak: {x}" for x in d.leak_scan(txt, key, sorted(mkt))]
            text = pm.render_raw_text(m)
            if len(text) > MAX_C_CHARS:
                why.append(f"size cap: {len(text)} chars > MAX_C_CHARS {MAX_C_CHARS}")
        else:
            why += [f"leak: {x}" for x in d.leak_scan(txt, key, sorted(mkt))]
            text = f"### PACKET {pid}\n" + json.dumps(m, sort_keys=True) + "\n"
        if why:
            refused.append(f"{pid}: {why[:3]}")
            continue
        chars.append(len(text))
        out.append({"packet_id": pid, "packet": m, "text": text})
    st = {"packets": len(out), "refused": len(refused), "median_chars": int(np.median(chars)) if chars else None,
          "max_chars": int(max(chars)) if chars else None}
    return out, refused, st


def write_batches(out: Path, arm: str, built: List[dict], size: int) -> List[str]:
    """batches/bNN.md = the protocol + the isolation rule + `size` packets; one judge subagent per batch."""
    bdir = out / "batches"
    bdir.mkdir(parents=True, exist_ok=True)
    names = []
    head = protocol(arm) + SUBAGENT_RULES
    for j in range(0, len(built), size):
        nm = f"b{j // size + 1:02d}"
        body = "".join(b["text"] + "\n" for b in built[j:j + size])
        (bdir / f"{nm}.md").write_text(head + f"\n# Packets in this batch: {len(built[j:j + size])}\n\n" + body)
        names.append(nm)
    return names


# ----------------------------------------------------------------------------- measurements
def _ols_r2(y: np.ndarray, x: np.ndarray) -> Optional[float]:
    if len(y) < x.shape[1] + 3 or float(np.var(y)) == 0.0:
        return None
    X = np.c_[np.ones(len(y)), x]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    return float(1.0 - res.var() / y.var())


def base_rate_r2(ranks: Dict[str, Dict[str, float]], base: Dict[str, Dict[str, Tuple[float, float, float]]],
                 order: Sequence[str], group: int = R2_GROUP) -> Dict[str, Any]:
    """R^2 of the judge's cell score on that cell's own A-packet base-rate means (h4, h12, h48, same side), pooled and
    per group of `group` packets in sample order (V1's measurement, generalised). base: {pid: {sym:side: (h4,h12,h48)}}."""
    def rows(pids):
        ys, xs = [], []
        for p in pids:
            for cell, v in ranks.get(p, {}).items():
                if cell in base.get(p, {}):
                    ys.append(v)
                    xs.append(base[p][cell])
        return np.array(ys, dtype=float), np.array(xs, dtype=float).reshape(-1, 3)
    y, x = rows([p for p in order if p in ranks])
    groups = []
    for j in range(0, len(order), group):
        gy, gx = rows([p for p in order[j:j + group] if p in ranks])
        r = _ols_r2(gy, gx)
        if r is not None:
            groups.append(r)
    return {"pooled_r2": _ols_r2(y, x), "group_r2": groups, "median_group_r2": float(np.median(groups)) if groups else None,
            "cells": int(len(y)), "n_constant_or_short_groups": len(range(0, len(order), group)) - len(groups)}


def base_rates_of(packet_a: dict, key: dict) -> Dict[str, Tuple[float, float, float]]:
    """{real_symbol:side: (h4, h12, h48 mean_r)} from an A packet's features_at_review."""
    f = packet_a["features_at_review"]
    out = {}
    for alias, sym in key["alias"].items():
        for side in ("long", "short"):
            v = tuple(f.get(f"{alias}.1h.{side}.h{h}.mean_r") for h in d.HORIZONS)
            if all(isinstance(x, (int, float)) for x in v):
                out[f"{sym}:{side}"] = tuple(float(x) for x in v)
    return out


def _week_boot(per_week: Dict[str, List[float]], alpha: float, seed: int = SEED, draws: int = DRAWS) -> Tuple[float, float, float]:
    """(mean over items, lower, upper) with weeks resampled; the item mean is recomputed in each draw."""
    wk = sorted(per_week)
    if len(wk) < 2:
        return (float("nan"),) * 3
    s = np.array([sum(per_week[w]) for w in wk])
    n = np.array([len(per_week[w]) for w in wk])
    idx = np.random.default_rng(seed).integers(0, len(wk), size=(draws, len(wk)))
    b = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    return float(s.sum() / n.sum()), float(np.percentile(b, 100 * alpha / 2)), float(np.percentile(b, 100 * (1 - alpha / 2)))


def top_cells(ranks: Dict[str, Dict[str, float]]) -> Dict[str, str]:
    """{pid: real_symbol:side of the highest-scored cell} (first in sorted order on a tie)."""
    return {p: sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for p, sc in ranks.items() if sc}


def read_proposal_rows(path: Path, pids: Sequence[str]) -> List[dict]:
    """The propose_entry / no_trade rows of a judge output (rank rows dropped), for the driver's read_proposals."""
    out = []
    for ln in path.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("action") in ("propose_entry", "no_trade") and r.get("packet_id") in pids:
                out.append(r)
    return out


def score_arm(arm: str, mkt: Dict[str, d.Series], classes: Dict[str, List[str]], keys: Dict[str, dict], sample: List[dict],
              ranks_path: Path) -> Dict[str, Any]:
    """Every registered per-arm measurement (doc section 3.2-3.5)."""
    order = [s["packet_id"] for s in sample]
    ranks, intake = dl.read_ranks(ranks_path, keys)
    ranks = {p: v for p, v in ranks.items() if p in set(order)}   # the population is the sample, never the whole file
    labels = dl.cell_labels(mkt, keys, [p for p in order if p in ranks])
    rows = dl.cell_rows(ranks, labels)
    sel = dl.packet_sel(rows)
    wk = dl.weekly_means(sel)
    wk_at, looks = [], []
    for L in dl.DEV_LOOKS:
        if L <= len(order) and set(order[:L]) <= set(ranks):      # a look needs L packets: n=50 takes 2 of 4
            looks.append(L)
            wk_at.append(dl.weekly_means([r for r in sel if r["packet_id"] in set(order[:L])]))
    decision, why = dl.sequential_decision(wk_at, useful=dl.SEL_USEFUL)
    lo, hi = dl.one_sided_bounds(wk, 0.025)
    picks = dl.top_pick_rows(rows)
    st = d.cluster_stats(picks) if picks else {"n": 0}
    s3, ci = st.get("paired_diff_vs_random"), st.get("paired_diff_ci95")
    useful = bool(s3 is not None and ci and s3 >= S3_USEFUL and ci[0] > 0)
    # behaviour: base-rate linearity (A-packet base rates, whatever the arm saw) and direction balance
    packets_a, base = {}, {}
    for s in sample:
        m, k = d.build_masked_packet(mkt, classes, s["cutoff_epoch"], s["index"], d.SEED)
        packets_a[s["packet_id"]] = m
        base[s["packet_id"]] = base_rates_of(m, k)
    r2 = base_rate_r2(ranks, base, order)
    tc = top_cells(ranks)
    top_long = {p: 1.0 if c.endswith(":long") else 0.0 for p, c in tc.items()}
    pos = [sc for sc in ranks.values()]
    # proposals: the driver's reader against the A packet (same aliases, levels, ATR), the driver's score loop
    prop_rows = read_proposal_rows(ranks_path, order)
    tmp = ranks_path.parent / f".{arm}-proposals.jsonl"
    tmp.write_text("".join(json.dumps(r) + "\n" for r in prop_rows))
    by, pacc = d.read_proposals(tmp, packets_a)
    tmp.unlink()
    valid = [r for rr in by.values() for r in rr]
    sc = d.score(mkt, keys, {p: v for p, v in by.items() if v}, [], {}, subset="all", cutoff=None, selfcheck=None)
    pst = sc["stats"]
    return {
        "arm": arm, "intake": intake, "packets_ranked": len(ranks), "cells_scored": len(rows),
        "s3_top_pick": {"n": st.get("n"), "weeks": st.get("weeks"), "s3": s3, "ci95": ci, "mean_net_r": st.get("mean_net_r"),
                        "mean_net_r_ci95": st.get("mean_ci95"), "useful": useful},
        "sel": {"mean": float(np.mean(wk)) if wk else None, "ci95": [lo, hi], "weeks": len(wk), "packets": len(sel),
                "decision": decision, "reasons": why, "looks": looks},
        "behaviour": {"base_rate_r2": r2,
                      "breaks_linearity": bool(r2["pooled_r2"] is not None and r2["pooled_r2"] < R2_BREAK
                                               and r2["median_group_r2"] is not None and r2["median_group_r2"] < R2_BREAK),
                      "top_cell_long_share": float(np.mean(list(top_long.values()))) if top_long else None,
                      "share_cells_scored_positive": float(np.mean([v > 0 for s_ in pos for v in s_.values()])) if pos else None},
        "proposals": {"intake": pacc, "packets_with_valid_proposal": sum(1 for v in by.values() if v),
                      "proposal_rate": sum(1 for v in by.values() if v) / len(order),
                      "valid": len(valid), "long": sum(1 for r in valid if r["proposal"]["side"] == "long"),
                      "short": sum(1 for r in valid if r["proposal"]["side"] == "short"),
                      "filled": pst.get("n"), "s3": pst.get("paired_diff_vs_random"), "s3_ci95": pst.get("paired_diff_ci95"),
                      "mean_net_r": pst.get("mean_net_r"), "mean_net_r_ci95": pst.get("mean_ci95")},
        "_per_packet": {"sel": {r["packet_id"]: (r["week"], r["sel"]) for r in sel}, "top_long": top_long,
                        "week": {p: d.iso_week(int(keys[p]["cutoff_epoch"])) for p in order}},
    }


def contrast(a: Dict[str, Any], x: Dict[str, Any], alpha: float = CONTRAST_ALPHA) -> Dict[str, Any]:
    """Paired by packet (the same 100 packets): arm-minus-A per packet, weeks resampled, two-sided at alpha."""
    out = {}
    for name, fa, fx in (("sel", a["_per_packet"]["sel"], x["_per_packet"]["sel"]),
                         ("top_cell_long_share", a["_per_packet"]["top_long"], x["_per_packet"]["top_long"])):
        per: Dict[str, List[float]] = {}
        for p in sorted(set(fa) & set(fx)):
            va = fa[p][1] if isinstance(fa[p], tuple) else fa[p]
            vx = fx[p][1] if isinstance(fx[p], tuple) else fx[p]
            per.setdefault(a["_per_packet"]["week"][p], []).append(vx - va)
        m, lo, hi = _week_boot(per, alpha)
        out[name] = {"diff": m, "ci": [lo, hi], "alpha": alpha, "packets": sum(len(v) for v in per.values()),
                     "differs": bool(np.isfinite(lo) and (lo > 0 or hi < 0))}
    return out


def recommend(arms: Dict[str, Dict[str, Any]]) -> Tuple[str, List[str]]:
    """The registered recommendation rule (doc section 3.6)."""
    ok = sorted([(v["s3_top_pick"]["s3"], k) for k, v in arms.items() if v["s3_top_pick"]["useful"]], reverse=True)
    if ok:
        k = ok[0][1]
        why = [f"arm {k}: top-pick S3 {arms[k]['s3_top_pick']['s3']:+.3f} >= {S3_USEFUL} with CI lower > 0"]
        if arms[k]["sel"]["decision"] != "promote":
            why.append(f"but its dev-loop SEL decision is {arms[k]['sel']['decision']}: the program's holdout rule decides before live")
        return k, why
    return "none_yet", [f"no arm has top-pick S3 >= {S3_USEFUL} with its 95% CI lower bound > 0"]


# ----------------------------------------------------------------------------- CLI
def _market(a):
    return dl._market(a)


def cmd_build(a: argparse.Namespace) -> int:
    mkt, classes = _market(a)
    sample = json.loads(Path(a.sample).read_text())["packets"]
    dl.assert_not_locked([s["cutoff_epoch"] for s in sample])
    raw = pm.load_raw(Path(a.raw), sorted(mkt)) if a.arm == "C" else None
    built, refused, st = build_arm(a.arm, mkt, classes, sample, raw)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "packets.jsonl").open("w") as fh:
        for b in built:
            fh.write(json.dumps({"packet_id": b["packet_id"], "packet": b["packet"]}, sort_keys=True) + "\n")
    (out / "JUDGE-PROTOCOL.md").write_text(protocol(a.arm))
    names = write_batches(out, a.arm, built, a.batch_size or (BATCH_C if a.arm == "C" else BATCH_B))
    st.update(arm=a.arm, batches=len(names), refused_detail=refused,
              est_tokens_per_packet=int(st["median_chars"] / 3.0) if st["median_chars"] else None)
    (out / "build.json").write_text(json.dumps(st, indent=1) + "\n")
    print(json.dumps({k: v for k, v in st.items() if k != "refused_detail"}))
    return 0 if not refused else 3


def cmd_score(a: argparse.Namespace) -> int:
    mkt, classes = _market(a)
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    sample = json.loads(Path(a.sample).read_text())["packets"]
    res = score_arm(a.arm, mkt, classes, keys, sample, Path(a.ranks))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"arm-{a.arm}.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({"arm": a.arm, "s3": res["s3_top_pick"], "sel": {k: res["sel"][k] for k in ("mean", "ci95", "decision")},
                      "r2": {k: res["behaviour"]["base_rate_r2"][k] for k in ("pooled_r2", "median_group_r2")},
                      "proposal_rate": res["proposals"]["proposal_rate"], "long": res["proposals"]["long"],
                      "short": res["proposals"]["short"]}, default=float))
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    arms = {}
    for kv in a.arm_dirs.split(","):
        k, v = kv.split("=")
        arms[k] = json.loads((Path(v) / f"arm-{k}.json").read_text())
    for v in arms.values():                      # json turned the (week, sel) tuples into lists
        v["_per_packet"]["sel"] = {p: tuple(x) for p, x in v["_per_packet"]["sel"].items()}
    res = {"contrasts": {f"{k}-A": contrast(arms["A"], arms[k]) for k in arms if k != "A"}}
    rec, why = recommend(arms)
    res["recommendation"], res["recommendation_reasons"] = rec, why
    res["arms"] = {k: {kk: vv for kk, vv in v.items() if kk != "_per_packet"} for k, v in arms.items()}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({"contrasts": res["contrasts"], "recommendation": rec, "why": why}, default=float))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("build", cmd_build), ("score", cmd_score)):
        s = sub.add_parser(name)
        s.add_argument("--arm", required=True, choices=pm.MODES if name == "score" else ("B", "C"))
        s.add_argument("--out", required=True)
        s.add_argument("--candles", required=True)
        s.add_argument("--sample", required=True)
        s.add_argument("--mask-key", default=str(dl.JUDGED1_KEY))
        s.add_argument("--fetch", action="store_true")
        s.add_argument("--candles-since", default="2025-05-01")
        s.set_defaults(fn=fn)
    sub.choices["build"].add_argument("--raw", help="desk_packet_modes.fetch_raw cache (arm C)")
    sub.choices["build"].add_argument("--batch-size", type=int, default=0)
    sub.choices["score"].add_argument("--ranks", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--out", required=True)
    c.add_argument("--arm-dirs", required=True, help="A=DIR,B=DIR,C=DIR (each holding arm-<X>.json)")
    c.set_defaults(fn=cmd_compare)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
