#!/usr/bin/env python3
# wiring: manual-only - run by DESK-EDGE-PROGRAM dev-batch lanes and the research/queue units RQ-20261027-ed9e-*; no schedule consumes it.
"""DESK-EDGE-PROGRAM parts 3-4 -- the CHEAP DEV LOOP, the LOCKED HOLDOUT and the promotion rule.

Design and every constant: docs/research/desk-edge-program-2026-10-27.md section 5 (registered before any dev run).
Reuses the driver (scripts/research/desk_gen_replay_driver.py) for packets, the engine, the random-entry baseline,
the folds, weeks and cluster_stats; reuses desk_edge_ceiling for the per-action S3 label. Never re-implements S1/S2/S3.

WHY FORCED-RANK ELICITATION. A judge that proposes on ~0.5 of packets gives ~50 scored fills per 100 packets: an S3
standard error near 0.3 R, too wide to screen anything. In the dev loop the judge instead SCORES every (asset, side)
cell of a packet (12 per packet) with its expected excess R over a random entry of the fixed dev bracket GJ, and may
still name proposals. Each cell has a label (the ceiling's y for GJ), so 100 packets give 1,200 labelled judgements:
the screen statistic is the weekly rank IC of the judge's scores, the same statistic the ceiling reports, so a judge
variant is compared directly with what a fitted model extracts from the same packets.

  sample   --out DIR --candles DIR [--n 100]              the stratified dev sample (from judged-1 packets) + protocol
  score    --out DIR --candles DIR --ranks F [--looks]    IC, top-pick S3, sequential decision for one variant
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
DEV_GEOM = ("GJ", 1.25, 2.0, 48)  # the fixed bracket every cell score is about
IC_USEFUL = 0.03                  # the weekly rank IC below which a variant is not worth a holdout (doc section 5.2)
KILL_ALPHA = 0.05                 # one-sided, split evenly over the looks (Bonferroni)
PROMOTE_ALPHA = 0.20              # one-sided screen at the last look (dev is a screen, the holdout is the test)
PROMOTE_MAX_PER_BATCH = 2
HOLDOUT_N = 300                   # packets per promoted variant
HOLDOUT_ALPHA = 0.05              # one-sided, divided by the number of variants EVER sent to the holdout
HOLDOUT_MIN_PICK_S3 = 0.05
CELL_KEYS = ("alias", "side", "score")


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
                window: Tuple[datetime, datetime] = DEV) -> Dict[Tuple[str, str], dict]:
    """{(packet_id, real_symbol+side): {y, net_r, days, week, fold}} for the dev bracket, via the driver's engine and
    random baseline (same symbol, side, fold; the ceiling's construction)."""
    rng = np.random.default_rng(seed)
    base: Dict[Tuple, Optional[float]] = {}
    out: Dict[Tuple[str, str], dict] = {}
    _, sl, tp_r, h = DEV_GEOM
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


def ic_rows(ranks: Dict[str, Dict[str, float]], labels: Dict[Tuple[str, str], dict]) -> List[dict]:
    """One row per (packet, cell) with a score and a label."""
    return [{"packet_id": pid, "cell": cell, "score": v, **labels[(pid, cell)]}
            for pid, sc in ranks.items() for cell, v in sc.items() if (pid, cell) in labels]


def weekly_ic(rows: List[dict]) -> List[float]:
    """Per-week Spearman of score vs y (weeks with >= 12 cells and some score variation)."""
    from scipy.stats import spearmanr
    wk: Dict[str, List[dict]] = {}
    for r in rows:
        wk.setdefault(r["week"], []).append(r)
    out = []
    for w in sorted(wk):
        rr = wk[w]
        s = np.array([r["score"] for r in rr])
        if len(rr) < 12 or np.ptp(s) == 0:
            continue
        rho = spearmanr(s, [r["y"] for r in rr]).statistic
        if np.isfinite(rho):
            out.append(float(rho))
    return out


def one_sided_bounds(v: Sequence[float], alpha: float, seed: int = DEV_SEED, draws: int = 10_000) -> Tuple[float, float]:
    """(lower, upper) one-sided bootstrap bounds of the mean at level alpha (weeks are the resampling unit)."""
    v = np.asarray(v, dtype=float)
    if len(v) < 2:
        return (float("nan"), float("nan"))
    b = np.random.default_rng(seed).choice(v, size=(draws, len(v)), replace=True).mean(axis=1)
    return float(np.percentile(b, 100 * alpha)), float(np.percentile(b, 100 * (1 - alpha)))


def top_pick_rows(rows: List[dict]) -> List[dict]:
    """The policy the dev loop scores alongside IC: per packet, the single highest-scored cell, taken only if its
    score > 0. Rows in cluster_stats' shape {week, net_r, days, diff}: their mean diff is S3 for the dev bracket."""
    by: Dict[str, dict] = {}
    for r in rows:
        if r["packet_id"] not in by or r["score"] > by[r["packet_id"]]["score"]:
            by[r["packet_id"]] = r
    return [{"week": r["week"], "net_r": r["net_r"], "days": r["days"], "diff": r["y"]} for r in by.values() if r["score"] > 0]


def sequential_decision(ics_at_looks: List[List[float]], looks: Sequence[int] = DEV_LOOKS) -> Tuple[str, List[str]]:
    """The registered sequential rule. `ics_at_looks[j]` = the weekly ICs using the first looks[j] packets.
    kill    at any look: the one-sided upper bound (alpha KILL_ALPHA / len(looks)) of mean IC < IC_USEFUL.
    promote at the last look: mean IC >= IC_USEFUL and its one-sided lower bound (PROMOTE_ALPHA) > 0.
    screen_fail at the last look otherwise; continue between looks."""
    a_kill = KILL_ALPHA / len(looks)
    for j, v in enumerate(ics_at_looks):
        if len(v) < 2:
            continue
        _, hi = one_sided_bounds(v, a_kill)
        if hi < IC_USEFUL:
            return "kill", [f"look {j + 1} ({looks[j]} packets): IC upper bound {hi:+.4f} < IC_USEFUL {IC_USEFUL}"]
    if len(ics_at_looks) < len(looks):
        return "continue", [f"{len(ics_at_looks)} of {len(looks)} looks taken"]
    v = ics_at_looks[-1]
    m = float(np.mean(v)) if v else float("nan")
    lo, _ = one_sided_bounds(v, PROMOTE_ALPHA)
    if np.isfinite(m) and m >= IC_USEFUL and lo > 0:
        return "promote", [f"mean IC {m:+.4f} >= {IC_USEFUL}, one-sided {1 - PROMOTE_ALPHA:.0%} lower bound {lo:+.4f} > 0"]
    return "screen_fail", [f"mean IC {m:+.4f}, lower bound {lo:+.4f}: not both (>= {IC_USEFUL}, > 0)"]


def promote_batch(results: Dict[str, Tuple[str, float]]) -> List[str]:
    """Of a batch's variants {name: (decision, mean IC)}, at most PROMOTE_MAX_PER_BATCH `promote`s go on, best IC first."""
    ok = sorted([(ic, n) for n, (dec, ic) in results.items() if dec == "promote"], reverse=True)
    return [n for _, n in ok[:PROMOTE_MAX_PER_BATCH]]


def holdout_verdict(ics: List[float], pick_rows: List[dict], n_ever_promoted: int) -> Tuple[str, List[str], Dict[str, Any]]:
    """The registered holdout rule for ONE variant on HOLDOUT_N packets."""
    a = HOLDOUT_ALPHA / max(1, n_ever_promoted)
    lo, _ = one_sided_bounds(ics, a)
    st = d.cluster_stats(pick_rows) if pick_rows else {"n": 0}
    s3 = st.get("paired_diff_vs_random")
    info = {"mean_ic": float(np.mean(ics)) if ics else None, "ic_lower": lo, "alpha": a, "pick_stats": st}
    if lo > 0 and s3 is not None and s3 >= HOLDOUT_MIN_PICK_S3:
        return "pass", [f"IC lower bound {lo:+.4f} > 0 at one-sided {a:.4f}; top-pick S3 {s3:+.3f} >= {HOLDOUT_MIN_PICK_S3}"], info
    return "fail", [f"IC lower bound {lo:+.4f} (needs > 0 at {a:.4f}); top-pick S3 {s3} (needs >= {HOLDOUT_MIN_PICK_S3})"], info


# ----------------------------------------------------------------------------- CLI
def _market(a):
    uni, _ = d.parse_universe()
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
                                                              "minrisk": d.MIN_RISK_ATR} + RANK_ADDENDUM)
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
    labels = cell_labels(mkt, keys, [p for p in order if p in ranks])
    rows_all = ic_rows(ranks, labels)
    looks, ics_at = [], []
    for L in DEV_LOOKS:
        have = set(order[:L])
        if not have <= set(ranks):
            break
        looks.append(L)
        ics_at.append(weekly_ic([r for r in rows_all if r["packet_id"] in have]))
    dec, why = sequential_decision(ics_at)
    picks = top_pick_rows(rows_all)
    st = d.cluster_stats(picks) if picks else {"n": 0}
    res = {"variant": a.variant, "decision": dec, "reasons": why, "intake": acc, "looks_taken": looks,
           "mean_ic_by_look": [float(np.mean(v)) if v else None for v in ics_at], "weeks_by_look": [len(v) for v in ics_at],
           "cells_scored": len(rows_all), "top_pick": {k: st.get(k) for k in ("n", "mean_net_r", "paired_diff_vs_random", "paired_diff_ci95")},
           "constants": {"IC_USEFUL": IC_USEFUL, "DEV_LOOKS": DEV_LOOKS, "KILL_ALPHA": KILL_ALPHA, "PROMOTE_ALPHA": PROMOTE_ALPHA, "DEV_GEOM": DEV_GEOM}}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"dev-{a.variant}.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({k: res[k] for k in ("variant", "decision", "looks_taken", "mean_ic_by_look", "cells_scored")}))
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
        s.set_defaults(fn=fn)
    sub.choices["sample"].add_argument("--n", type=int, default=DEV_N)
    sub.choices["sample"].add_argument("--seed", type=int, default=DEV_SEED)
    sub.choices["score"].add_argument("--ranks", required=True)
    sub.choices["score"].add_argument("--sample", required=True)
    sub.choices["score"].add_argument("--variant", required=True)
    sub.choices["holdout"].add_argument("--promotion", required=True)
    sub.choices["holdout"].add_argument("--n", type=int, default=HOLDOUT_N)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
