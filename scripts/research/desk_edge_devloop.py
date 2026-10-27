#!/usr/bin/env python3
# wiring: manual-only - run by DESK-EDGE-PROGRAM dev-batch lanes and the research/queue units RQ-20261027-fe57-*; no schedule consumes it.
"""DESK-EDGE-PROGRAM parts 3-4 -- the CHEAP DEV LOOP, the LOCKED HOLDOUT and the promotion rule.

Design and every constant: docs/research/desk-edge-program-2026-10-27.md section 5 (registered before any dev run).
Reuses the driver (scripts/research/desk_gen_replay_driver.py) for packets, the engine, the random-entry baseline,
the folds, weeks and cluster_stats; reuses desk_edge_ceiling for the per-action S3 label. Never re-implements S1/S2/S3.

WHY FORCED-RANK ELICITATION. A judge that proposes on ~0.5 of packets gives ~50 scored fills per 100 packets: an S3
standard error near 0.3 R, too wide to screen anything. In the dev loop the judge instead SCORES every (asset, side)
cell of a packet (12 per packet) with its expected excess R over a random entry of the fixed dev bracket GJ, and may
still name proposals. Every cell has a label (the ceiling's y for GJ), so every packet is scored, not only the ~half
the judge would trade.

THE SCREEN STATISTIC IS A MEAN, NOT A RANK CORRELATION. SEL_i = mean y of the packet's 2 highest-scored cells minus
mean y of all its labelled cells: the S3 a top-2 desk earns over picking cells at random IN THE SAME PACKET. Its
expectation is the policy's S3 (the packet mean of y is ~0 by construction) and the subtraction removes the shock the
packet's cells share, so it is less noisy than S3 itself. Rank IC was rejected after the DEV-window ceiling: ridge on
packet fields had IC +0.10 with a flat mean-y-by-decile curve (doc section 4.1), i.e. IC tracked the shape of y, not
money.

  sample   --out DIR --candles DIR [--n 100]              the stratified dev sample (from judged-1 packets) + protocol
  score    --out DIR --candles DIR --ranks F             SEL, top-pick S3, sequential decision for one variant
  holdout  --out DIR --candles DIR --promotion F --n N    holdout packets; REFUSES without a dev promotion record
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402
from scripts.research import desk_edge_ceiling as ce  # noqa: E402

# ----------------------------------------------------------------------------- registered windows (doc section 2)
DEV = (datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2026, 9, 15, tzinfo=timezone.utc))
HOLDOUT = (datetime(2025, 5, 1, tzinfo=timezone.utc), datetime(2025, 10, 25, tzinfo=timezone.utc))
FULL_RUN = (datetime(2023, 11, 1, tzinfo=timezone.utc), datetime(2025, 4, 30, tzinfo=timezone.utc))
HOLDOUT_SEED = 20261101
JUDGED1_KEY = REPO / "comms/research/desk_gen_replay/judged-1/mask-key.json"

# ----------------------------------------------------------------------------- registered dev-loop constants (doc section 5)
DEV_N = 100                       # packets per variant
DEV_LOOKS = (25, 50, 75, 100)     # sequential looks, in packets of the variant's sample order
DEV_SEED = 20261027
DEV_GEOM = ("GJ", 1.25, 2.0, 48)  # the fixed bracket every cell score is about (V1)
DEV_GEOMS = {g[0]: g for g in ce.GEOMETRIES + ce.SHORT_GEOMETRIES}   # a variant may name another registered bracket
# R: the selection value below which a variant is not worth a holdout. +0.10 for V1 (RQ-20261027-fe57-01, registered
# and run at 0.10); raised to +0.25 for every LATER variant by the operator's direction of 2026-10-27 ~16:40Z ("an edge
# that needs more than 35 weeks to prove ... isn't a strong enough edge"): the bar is one the DEV window resolves alone.
SEL_USEFUL_V1 = 0.10
SEL_USEFUL = 0.25
TOP_K = 2                         # cells per packet the SEL statistic takes (judged-1's cap)
KILL_ALPHA = 0.05                 # one-sided, split evenly over the looks (Bonferroni)
PROMOTE_ALPHA = 0.20              # one-sided screen at the last look (dev is a screen, the holdout is the test)
PROMOTE_MAX_PER_BATCH = 2
HOLDOUT_N = 300                   # packets per promoted variant
HOLDOUT_ALPHA = 0.05              # one-sided, divided by the number of variants EVER sent to the holdout
HOLDOUT_MIN_PICK_S3 = 0.05


def _in(ts: int, w: Tuple[datetime, datetime]) -> bool:
    return d._epoch(w[0]) <= ts < d._epoch(w[1])


def assert_not_locked(cutoffs: Sequence[int], promotion: Optional[dict] = None) -> None:
    """The holdout lock: a cutoff inside HOLDOUT (or FULL_RUN) is refused unless a promotion record unlocks it."""
    hold = [c for c in cutoffs if _in(c, HOLDOUT)]
    full = [c for c in cutoffs if _in(c, FULL_RUN)]
    if full and not (promotion and promotion.get("stage") == "full_run" and promotion.get("holdout_verdict") == "pass"):
        raise PermissionError(f"{len(full)} cutoffs fall in the FULL-RUN window; only a holdout PASS unlocks it")
    if hold and not (promotion and promotion.get("dev_decision") == "promote"):
        raise PermissionError(f"{len(hold)} cutoffs fall in the LOCKED HOLDOUT; only a dev promotion record unlocks it")


# ----------------------------------------------------------------------------- the stratified dev sample
def regime_of(mkt: Dict[str, d.Series], cutoff: int) -> str:
    """'up' / 'down': the sign of BTC's 168-bar return at the cutoff (point in time)."""
    s = mkt["BTCUSDT"]
    i = s.last_closed(cutoff)
    return "up" if i >= 168 and s.c[i] >= s.c[i - 168] else "down"


def stratified_sample(keys: List[dict], mkt: Dict[str, d.Series], n: int = DEV_N, seed: int = DEV_SEED) -> List[dict]:
    """n judged-1 packets balanced over fold (4) x session (4) x BTC 168h regime (2) = 32 cells, in a seeded
    round-robin order: the first k of the list are themselves near-balanced, so a sequential look at k packets
    sees every stratum. Deterministic in (keys, seed)."""
    rng = np.random.default_rng(seed)
    cells: Dict[Tuple, List[dict]] = {}
    for k in keys:
        c = int(k["cutoff_epoch"])
        if not _in(c, DEV):
            continue
        st = (int(k["fold"]), _session(c), regime_of(mkt, c))
        cells.setdefault(st, []).append(k)
    order = sorted(cells)
    for st in order:
        cells[st] = [cells[st][j] for j in rng.permutation(len(cells[st]))]
    out: List[dict] = []
    rnd = 0
    while len(out) < n and any(len(cells[s]) > rnd for s in order):
        for st in [order[j] for j in rng.permutation(len(order))]:
            if len(cells[st]) > rnd and len(out) < n:
                k = cells[st][rnd]
                out.append({"packet_id": k["packet_id"], "index": int(k["index"]), "cutoff_epoch": int(k["cutoff_epoch"]),
                            "fold": int(k["fold"]), "stratum": list(st)})
        rnd += 1
    return out


def _session(cutoff: int) -> str:
    h = datetime.fromtimestamp(cutoff, tz=timezone.utc).hour
    return "asia" if h < 7 else "europe" if h < 13 else "us" if h < 21 else "late_us"


def rank_addendum(geom: Tuple = DEV_GEOM) -> str:
    _, sl, tp_r, h = geom
    return RANK_ADDENDUM.replace("stop 1.25 x atr, target 2.0 x the stop distance, exit at 48 bars",
                                 f"stop {sl:g} x atr, target {tp_r:.1f} x the stop distance, exit at {h} bar{'s' if h != 1 else ''}")


RANK_ADDENDUM = """

## Dev-loop scoring (DESK-EDGE-PROGRAM; this block binds your reply)
Before any proposal, SCORE EVERY (asset, side) cell of the packet: 6 assets x {long, short} = 12 cells. A cell's
score is your expected net R, in excess of a RANDOM-TIME entry on the same asset and side, of this fixed bracket:
market entry now, stop 1.25 x atr, target 2.0 x the stop distance, exit at 48 bars. 0 = no better than random.
Reply with ONE JSON line first:
{"packet_id": "<id>", "action": "rank", "cells": [{"alias": "ASSET_01", "side": "long", "score": 0.00}, ... 12 cells]}
then, optionally, your usual propose_entry / no_trade line(s). Scores are judged by their ORDER across packets and
cells, so use the full range your evidence supports; identical scores carry no information.
"""


# ----------------------------------------------------------------------------- scoring a variant
def cell_labels(mkt: Dict[str, d.Series], keys: Dict[str, dict], pids: Sequence[str], seed: int = DEV_SEED,
                window: Tuple[datetime, datetime] = DEV, geom: Tuple = DEV_GEOM) -> Dict[Tuple[str, str], dict]:
    """{(packet_id, real_symbol+side): {y, net_r, days, week, fold}} for the dev bracket, via the driver's engine and
    random baseline (same symbol, side, fold; the ceiling's construction)."""
    rng = np.random.default_rng(seed)
    base: Dict[Tuple, Optional[float]] = {}
    out: Dict[Tuple[str, str], dict] = {}
    _, sl, tp_r, h = geom
    for pid in pids:
        k = keys[pid]
        c, fold = int(k["cutoff_epoch"]), int(k["fold"])
        for sym, s in mkt.items():
            i = s.last_closed(c)
            for side, sg in ce.SIDES:
                g = {"side": sg, "etype": "market", "offset_atr": 0.0, "sl_atr": sl, "tp_atr": sl * tp_r, "good_till": 1, "horizon": h}
                t = d.transplant(s, i, g)
                if t is None or t.state != "filled":
                    continue
                bk = (sym, fold, side)
                if bk not in base:
                    pool = ce_pool(s, window, fold)
                    base[bk] = d.random_baseline(s, g, pool, rng, ce.BASELINE_DRAWS)["mean"]
                if base[bk] is None:
                    continue
                out[(pid, f"{sym}:{side}")] = {"y": t.net_r - base[bk], "net_r": t.net_r, "days": t.days, "week": d.iso_week(c), "fold": fold}
    return out


def ce_pool(s: d.Series, window: Tuple[datetime, datetime], fold: int) -> np.ndarray:
    """d.eligible_cutoffs for an explicit window (the driver's fold_of default is bound to ITS window)."""
    close = s.t + d.SEC
    m = (close >= d._epoch(window[0])) & (close < d._epoch(window[1])) & np.isfinite(s.atr) & (np.arange(len(s.t)) < len(s.t) - 2)
    return np.array([j for j in np.nonzero(m)[0] if d.fold_of(int(close[j]), *window) == fold], dtype=int)


def read_ranks(path: Path, keys: Dict[str, dict]) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Any]]:
    """{packet_id: {real_symbol:side: score}} from the judge's `rank` rows; malformed rows are counted, never guessed."""
    out: Dict[str, Dict[str, float]] = {}
    acc = {"rows": 0, "rank_rows": 0, "refused": 0, "reasons": {}}
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        acc["rows"] += 1
        if row.get("action") != "rank":
            continue
        pid = row.get("packet_id")
        why = None
        if pid not in keys:
            why = "unknown packet_id"
        else:
            cells = row.get("cells")
            if not isinstance(cells, list) or len(cells) != 12:
                why = "cells must be a list of 12"
            else:
                sc: Dict[str, float] = {}
                for c in cells:
                    # provenance: read_ranks — `score` here is the JUDGE's own reply field (its expected excess R for the cell), not a predictor's output
                    a, side, v = c.get("alias"), c.get("side"), c.get("score")
                    if a not in keys[pid]["alias"] or side not in ("long", "short") or not isinstance(v, (int, float)) or not math.isfinite(v):
                        why = "bad cell"
                        break
                    sc[f"{keys[pid]['alias'][a]}:{side}"] = float(v)
                if why is None and len(sc) != 12:
                    why = "duplicate cells"
        if why:
            acc["refused"] += 1
            acc["reasons"][why] = acc["reasons"].get(why, 0) + 1
            continue
        acc["rank_rows"] += 1
        out[pid] = sc
    return out, acc


def cell_rows(ranks: Dict[str, Dict[str, float]], labels: Dict[Tuple[str, str], dict]) -> List[dict]:
    """One row per (packet, cell) with a score and a label."""
    return [{"packet_id": pid, "cell": cell, "cell_score": v, **labels[(pid, cell)]}
            for pid, sc in ranks.items() for cell, v in sc.items() if (pid, cell) in labels]


def packet_sel(rows: List[dict], k: int = TOP_K) -> List[dict]:
    """Per packet: {week, sel} with sel = mean y of the k highest-scored cells - mean y of all labelled cells."""
    by: Dict[str, List[dict]] = {}
    for r in rows:
        by.setdefault(r["packet_id"], []).append(r)
    out = []
    for pid, rr in by.items():
        if len(rr) < k + 1:
            continue
        rr = sorted(rr, key=lambda r: -r["cell_score"])
        out.append({"packet_id": pid, "week": rr[0]["week"], "sel": float(np.mean([r["y"] for r in rr[:k]]) - np.mean([r["y"] for r in rr]))})
    return out


def weekly_means(sel: List[dict]) -> List[float]:
    """The week is the resampling unit (packets in one week share a market): one mean per week."""
    wk: Dict[str, List[float]] = {}
    for r in sel:
        wk.setdefault(r["week"], []).append(r["sel"])
    return [float(np.mean(v)) for _, v in sorted(wk.items())]


def one_sided_bounds(v: Sequence[float], alpha: float, seed: int = DEV_SEED, draws: int = 10_000) -> Tuple[float, float]:
    """(lower, upper) one-sided bootstrap bounds of the mean at level alpha (weeks are the resampling unit)."""
    v = np.asarray(v, dtype=float)
    if len(v) < 2:
        return (float("nan"), float("nan"))
    b = np.random.default_rng(seed).choice(v, size=(draws, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(b, 100 * alpha)), float(np.percentile(b, 100 * (1 - alpha)))


def top_pick_rows(rows: List[dict]) -> List[dict]:
    """The policy the dev loop scores alongside SEL: per packet, the single highest-scored cell, taken only if its
    score > 0. Rows in cluster_stats' shape {week, net_r, days, diff}: their mean diff is S3 for the dev bracket."""
    by: Dict[str, dict] = {}
    for r in rows:
        if r["packet_id"] not in by or r["cell_score"] > by[r["packet_id"]]["cell_score"]:
            by[r["packet_id"]] = r
    return [{"week": r["week"], "net_r": r["net_r"], "days": r["days"], "diff": r["y"]} for r in by.values() if r["cell_score"] > 0]


def sequential_decision(weeks_at_looks: List[List[float]], looks: Sequence[int] = DEV_LOOKS, useful: float = SEL_USEFUL) -> Tuple[str, List[str]]:
    """The registered sequential rule. `weeks_at_looks[j]` = the weekly mean SELs using the first looks[j] packets.
    kill    at any look: the one-sided upper bound (alpha KILL_ALPHA / len(looks)) of mean SEL < SEL_USEFUL.
    promote at the last look: mean SEL >= SEL_USEFUL and its one-sided lower bound (PROMOTE_ALPHA) > 0.
    screen_fail at the last look otherwise; continue between looks."""
    a_kill = KILL_ALPHA / len(looks)
    for j, v in enumerate(weeks_at_looks):
        if len(v) < 2:
            continue
        _, hi = one_sided_bounds(v, a_kill)
        if hi < useful:
            return "kill", [f"look {j + 1} ({looks[j]} packets): SEL upper bound {hi:+.4f} < the bar {useful}"]
    if len(weeks_at_looks) < len(looks):
        return "continue", [f"{len(weeks_at_looks)} of {len(looks)} looks taken"]
    v = weeks_at_looks[-1]
    m = float(np.mean(v)) if v else float("nan")
    lo, _ = one_sided_bounds(v, PROMOTE_ALPHA)
    if np.isfinite(m) and m >= useful and lo > 0:
        return "promote", [f"mean SEL {m:+.4f} >= {useful}, one-sided {1 - PROMOTE_ALPHA:.0%} lower bound {lo:+.4f} > 0"]
    return "screen_fail", [f"mean SEL {m:+.4f}, lower bound {lo:+.4f}: not both (>= {useful}, > 0)"]


def promote_batch(results: Dict[str, Tuple[str, float]]) -> List[str]:
    """Of a batch's variants {name: (decision, mean SEL)}, at most PROMOTE_MAX_PER_BATCH `promote`s go on, best first."""
    ok = sorted([(ic, n) for n, (dec, ic) in results.items() if dec == "promote"], reverse=True)
    return [n for _, n in ok[:PROMOTE_MAX_PER_BATCH]]


def holdout_verdict(sel_weeks: List[float], pick_rows: List[dict], n_ever_promoted: int) -> Tuple[str, List[str], Dict[str, Any]]:
    """The registered holdout rule for ONE variant on HOLDOUT_N packets: the weekly mean SEL's one-sided lower bound
    (alpha HOLDOUT_ALPHA / every variant ever sent to the holdout) > 0 AND the top-pick S3 (driver statistic) >=
    HOLDOUT_MIN_PICK_S3."""
    a = HOLDOUT_ALPHA / max(1, n_ever_promoted)
    lo, _ = one_sided_bounds(sel_weeks, a)
    st = d.cluster_stats(pick_rows) if pick_rows else {"n": 0}
    s3 = st.get("paired_diff_vs_random")
    info = {"mean_sel": float(np.mean(sel_weeks)) if sel_weeks else None, "sel_lower": lo, "alpha": a, "pick_stats": st}
    if lo > 0 and s3 is not None and s3 >= HOLDOUT_MIN_PICK_S3:
        return "pass", [f"SEL lower bound {lo:+.4f} > 0 at one-sided {a:.4f}; top-pick S3 {s3:+.3f} >= {HOLDOUT_MIN_PICK_S3}"], info
    return "fail", [f"SEL lower bound {lo:+.4f} (needs > 0 at {a:.4f}); top-pick S3 {s3} (needs >= {HOLDOUT_MIN_PICK_S3})"], info


# ----------------------------------------------------------------------------- CLI
def _market(a):
    uni, _ = d.parse_universe()
    if getattr(a, "fetch", False):
        d.CANDLE_SINCE = datetime.fromisoformat(a.candles_since).replace(tzinfo=timezone.utc)
        Path(a.candles).mkdir(parents=True, exist_ok=True)
        d.fetch_market(Path(a.candles), [u["symbol"] for u in uni])
    mkt, miss = d.load_market(Path(a.candles), [u["symbol"] for u in uni])
    if miss:
        raise SystemExit(f"candles missing {miss}")
    return mkt, {u["symbol"]: u["classes"] for u in uni}


def cmd_sample(a: argparse.Namespace) -> int:
    mkt, classes = _market(a)
    keys = json.loads(Path(a.mask_key).read_text())["keys"]
    smp = stratified_sample(keys, mkt, a.n, a.seed)
    assert_not_locked([s["cutoff_epoch"] for s in smp])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "packets.jsonl").open("w") as fh:
        for s in smp:
            m, key = d.build_masked_packet(mkt, classes, s["cutoff_epoch"], s["index"], d.SEED)
            if m["meta"]["packet_id"] != s["packet_id"]:
                raise SystemExit(f"packet drift on {s['packet_id']}")
            fh.write(json.dumps({"packet_id": s["packet_id"], "packet": m}, sort_keys=True) + "\n")
    (out / "sample.json").write_text(json.dumps({"seed": a.seed, "n": len(smp), "source": str(Path(a.mask_key)), "packets": smp}, indent=1) + "\n")
    (out / "JUDGE-PROTOCOL.md").write_text(d.JUDGE_PROTOCOL % {"cap": d.MAX_PER_PACKET, "sent": d.cdr.SENTINEL_R_FLOOR,
                                                              "cap_pct": d.cdr.TP_VENUE_CAP_PCT * 100, "reach": d.cdr.REACH_FLOOR,
                                                              "minrisk": d.MIN_RISK_ATR} + rank_addendum(DEV_GEOMS[a.geom]))
    strata: Dict[str, int] = {}
    for s in smp:
        strata[str(tuple(s["stratum"]))] = strata.get(str(tuple(s["stratum"])), 0) + 1
    print(json.dumps({"packets": len(smp), "strata": len(strata), "min_per_stratum": min(strata.values()), "max_per_stratum": max(strata.values())}))
    return 0


def cmd_score(a: argparse.Namespace) -> int:
    mkt, _ = _market(a)
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    smp = json.loads(Path(a.sample).read_text())["packets"]
    order = [s["packet_id"] for s in smp]
    ranks, acc = read_ranks(Path(a.ranks), keys)
    labels = cell_labels(mkt, keys, [p for p in order if p in ranks], geom=DEV_GEOMS[a.geom])
    rows_all = cell_rows(ranks, labels)
    looks, wk_at = [], []
    sel = packet_sel(rows_all)
    for L in DEV_LOOKS:
        have = set(order[:L])
        if not have <= set(ranks):
            break
        looks.append(L)
        wk_at.append(weekly_means([r for r in sel if r["packet_id"] in have]))
    useful = SEL_USEFUL_V1 if a.variant == "V1" else SEL_USEFUL      # V1 was registered and run at +0.10
    dec, why = sequential_decision(wk_at, useful=useful)
    picks = top_pick_rows(rows_all)
    st = d.cluster_stats(picks) if picks else {"n": 0}
    res = {"variant": a.variant, "decision": dec, "reasons": why, "intake": acc, "looks_taken": looks,
           "mean_sel_by_look": [float(np.mean(v)) if v else None for v in wk_at], "weeks_by_look": [len(v) for v in wk_at],
           "packets_with_sel": len(sel),
           "cells_scored": len(rows_all), "top_pick": {k: st.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")},
           "constants": {"SEL_USEFUL": useful, "TOP_K": TOP_K, "DEV_LOOKS": DEV_LOOKS, "KILL_ALPHA": KILL_ALPHA, "PROMOTE_ALPHA": PROMOTE_ALPHA, "DEV_GEOM": DEV_GEOMS[a.geom]}}
    res["verdict"] = {"promote": "pass", "kill": "fail", "screen_fail": "fail"}.get(dec, "indeterminate")
    if acc["rank_rows"] < 0.9 * len(order):
        res["verdict"], res["reasons"] = "indeterminate", [f"intake: {acc['rank_rows']} valid rank rows of {len(order)} packets (< 90%)"] + why
    res["read_state"] = "measured" if rows_all else "no_data"
    d._write_verdict(Path(a.out), res, f"dev variant {a.variant}: {acc['rank_rows']} ranked packets of the {len(order)}-packet dev sample, "
                     f"{len(rows_all)} labelled cells", len(sel), "; ".join(why), None, d.candle_manifest(mkt))
    print(json.dumps({k: res[k] for k in ("variant", "decision", "verdict", "looks_taken", "mean_sel_by_look", "cells_scored")}))
    return 0


BASE_RATE_RULES = {"h12+h48": (0, 1, 1), "h48": (0, 0, 1), "h4+h12+h48": (1, 1, 1)}


def emulate_base_rate_rule(cutoffs: List[dict], acts: List[dict], weights: Tuple[int, int, int]) -> Tuple[List[dict], List[dict]]:
    """The judge EMULATOR: score each GJ cell by a weighted sum of the packet's own base-rate means for that cell's side
    (h4, h12, h48). V1's scores were 90-100% explained by such a sum (doc section 4.3), so this prices the current judge
    on every built packet for free. Returns (cell rows for packet_sel, top-pick rows for cluster_stats)."""
    cut = {c["cutoff"]: c for c in cutoffs}
    rows = []
    for a in acts:
        if a["geom"] != DEV_GEOM[0]:
            continue
        pf = cut[a["cutoff"]]["pf"][a["symbol"]]
        sc = sum(w * (pf[f"br_{a['side']}_h{h}_mean_r"] or 0.0) for w, h in zip(weights, ce.HORIZONS))
        rows.append({"packet_id": a["cutoff"], "week": a["week"], "cell_score": sc, "y": a["y"], "net_r": a["net_r"], "days": a["days"]})
    return rows, top_pick_rows(rows)


def cmd_emulate(a: argparse.Namespace) -> int:
    import pickle
    cutoffs = pickle.loads((Path(a.ceiling) / "cutoffs.pkl").read_bytes())
    acts = pickle.loads((Path(a.ceiling) / "actions.pkl").read_bytes())
    res = {}
    for name, w in BASE_RATE_RULES.items():
        rows, tp = emulate_base_rate_rule(cutoffs, acts, w)
        sel = packet_sel(rows)
        wk = weekly_means(sel)
        lo, hi = one_sided_bounds(wk, 0.025)
        st = d.cluster_stats(tp)
        res[name] = {"packets": len(sel), "weeks": len(wk), "mean_sel": float(np.mean(wk)), "sel_ci95": [lo, hi],
                     "sd_sel_per_packet": float(np.std([s["sel"] for s in sel], ddof=1)),
                     "top_pick": {k: st.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")},
                     "excluded_as_useful": bool(hi < SEL_USEFUL)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "base-rate-emulator.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({k: (v["mean_sel"], v["sel_ci95"]) for k, v in res.items()}))
    return 0


def cmd_holdout(a: argparse.Namespace) -> int:
    promo = json.loads(Path(a.promotion).read_text())
    mkt, classes = _market(a)
    sched = d.make_schedule(HOLDOUT[0], HOLDOUT[1], a.n, HOLDOUT_SEED, d.MIN_GAP_H)
    assert_not_locked(sched, promo)            # refuses unless the record says dev_decision == promote
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = []
    with (out / "packets.jsonl").open("w") as fh:
        for k, c in enumerate(sched):
            m, key = d.build_masked_packet(mkt, classes, c, k, HOLDOUT_SEED)
            if d.leak_scan(json.dumps(m, sort_keys=True), key, sorted(mkt)):
                continue
            key["fold"] = d.fold_of(c, *HOLDOUT)
            fh.write(json.dumps({"packet_id": m["meta"]["packet_id"], "packet": m}, sort_keys=True) + "\n")
            keys.append(key)
    (out / "mask-key.json").write_text(json.dumps({"seed": HOLDOUT_SEED, "variant": promo.get("variant"), "keys": keys}, indent=1) + "\n")
    print(json.dumps({"packets": len(keys), "variant": promo.get("variant")}))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("sample", cmd_sample), ("score", cmd_score), ("holdout", cmd_holdout)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--candles", required=True)
        s.add_argument("--mask-key", default=str(JUDGED1_KEY))
        s.add_argument("--fetch", action="store_true")
        s.add_argument("--candles-since", default="2025-05-01")
        s.set_defaults(fn=fn)
    for nm in ("sample", "score"):
        sub.choices[nm].add_argument("--geom", default=DEV_GEOM[0], choices=sorted(DEV_GEOMS))
    sub.choices["sample"].add_argument("--n", type=int, default=DEV_N)
    sub.choices["sample"].add_argument("--seed", type=int, default=DEV_SEED)
    # provenance: cmd_score — the `score` subcommand GRADES a variant's judged ranks; it reads no predictor
    sub.choices["score"].add_argument("--ranks", required=True)
    sub.choices["score"].add_argument("--sample", required=True)
    sub.choices["score"].add_argument("--variant", required=True)
    sub.choices["holdout"].add_argument("--promotion", required=True)
    em = sub.add_parser("emulate", help="the base-rate judge emulator over a ceiling build (token-free)")
    em.add_argument("--out", required=True)
    em.add_argument("--ceiling", required=True, help="a desk_edge_ceiling.py build --out directory")
    em.set_defaults(fn=cmd_emulate)
    sub.choices["holdout"].add_argument("--n", type=int, default=HOLDOUT_N)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
