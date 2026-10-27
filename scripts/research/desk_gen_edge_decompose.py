#!/usr/bin/env python3
# wiring: manual-only - run by the DESK-18C-EDGE-OPT lane (and its re-run); no schedule consumes it.
"""DESK-18C-EDGE-OPT -- decompose a judged entry-generation file into per-proposal records and slice them.

EXPLORATION ONLY. It imports the registered scorer (scripts/research/desk_gen_replay_driver.py) and does NOT edit
it: the per-proposal engine, cost stack, random-entry baseline (200 draws, same symbol, same fold, the proposal's own
geometry) and weekly-cluster bootstrap are the driver's own functions, called in the driver's own order with the
driver's own RNG stream, so the overall numbers reproduce `score()` exactly (asserted). What is added is covariates
per proposal, all known AT THE CUTOFF (from the masked packet the judge saw, or from candles at or before the cutoff),
and a slice table. Nothing here is evidence: judged-1 is an exploration set once a filter is chosen from it
(research/queue/RQ-20261027-e72b-*.yaml confirm any filter on data it never saw).

  decompose --out DIR --candles DIR --mask-key K --proposals F         the exploration table on judged-1
  packets   --out DIR --candles DIR [--fetch] --n N [--offset K]      masked US-session packets for the confirm run (judged-2)
  confirm   --out DIR --candles DIR --mask-key K --proposals F          the registered C1 rule on a judged-2 file
  forward   --out DIR --candles DIR [--fetch] --decisions F             the desk's recorded proposals, replayed, S1/S2/S3
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.research import desk_gen_replay_driver as d  # noqa: E402

SUSPECT_LO, SUSPECT_HI = 1332, 1365          # packet indices judged from base-rate rows only (manager's flag)


def _vol_pct(s: d.Series, i: int, look: int = 720) -> float | None:
    lo = max(0, i - look)
    r = s.atr[lo:i + 1] / s.c[lo:i + 1]
    r = r[np.isfinite(r)]
    return None if len(r) < 100 else float((r < r[-1]).mean())


def _pool(s: d.Series, start: datetime, end: datetime, fold: int) -> np.ndarray:
    """d.eligible_cutoffs for an explicit window: the driver's fold_of default is bound to ITS window at def time, so a
    different window needs the fold cut explicit. For the driver's window this is identical (asserted in `decompose`)."""
    close = s.t + d.SEC
    m = (close >= d._epoch(start)) & (close < d._epoch(end)) & np.isfinite(s.atr) & (np.arange(len(s.t)) < len(s.t) - 2)
    return np.array([j for j in np.nonzero(m)[0] if d.fold_of(int(close[j]), start, end) == fold], dtype=int)


def records(mkt, keys, by, legs, rost, cutoff, seed=d.SEED, draws=d.B_R_DRAWS, packets=None,
            start: datetime = d.WINDOW_START, end: datetime = d.WINDOW_END) -> list[dict]:
    """The driver's score() loop, field for field, plus covariates. Filled proposals only (as score())."""
    rng = np.random.default_rng(seed + 7)
    pools: dict[Any, np.ndarray] = {}
    out: list[dict] = []
    for pid, rows in by.items():
        key = keys[pid]
        ce = key["cutoff_epoch"]
        pkt = packets[pid]
        uni = {u["symbol"]: u for u in pkt["universe"]}
        hist = {(h["symbol"], h["side"], h["horizon_bars"]): h for h in pkt["history"]["rows"]}
        for row in rows:
            pr = row["proposal"]
            alias = pr["symbol"]
            sym = key["alias"][alias]
            sc = float(key["price_scale"][alias])
            s = mkt[sym]
            i = s.last_closed(ce)
            side = 1.0 if pr["side"] == "long" else -1.0
            lvl, stp, tpl = pr["entry"]["level"] / sc, pr["stop"]["level"] / sc, pr["tp"]["level"] / sc
            nov = d.classify_novelty(sym, side, ce, legs, rost)
            t = d.simulate(s, i, side, pr["entry"]["type"], lvl, stp, tpl, pr["entry"]["good_till_bars"], pr["horizon_bars"])
            if t.state != "filled":
                continue
            g = d.geometry_of(s, i, side, pr["entry"]["type"], lvl, stp, tpl, pr["entry"]["good_till_bars"], pr["horizon_bars"])
            br = None
            if g is not None:
                pk = (sym, key["fold"])
                if pk not in pools:
                    pools[pk] = _pool(s, start, end, key["fold"])
                br = d.random_baseline(s, g, pools[pk], rng, draws)
            diff = None if br is None or br["mean"] is None else t.net_r - br["mean"]
            u = uni[alias]
            h_same = hist.get((alias, pr["side"], pr["horizon_bars"]))
            h_opp = hist.get((alias, "long" if pr["side"] == "short" else "short", pr["horizon_bars"]))
            sw = u.get("swing") or {}
            close_dt = datetime.fromtimestamp(ce, tz=timezone.utc)
            ret24 = float((s.c[i] - s.c[i - 24]) / s.atr[i]) if i >= 24 and s.atr[i] > 0 else None
            ret168 = float((s.c[i] - s.c[i - 168]) / s.atr[i]) if i >= 168 and s.atr[i] > 0 else None
            out.append({
                "packet_id": pid, "index": int(key["index"]), "symbol": sym, "side": pr["side"], "week": d.iso_week(ce),
                "fold": key["fold"], "net_r": t.net_r, "days": t.days, "diff": diff, "exit": t.reason, "novelty": nov,
                "pre_cutoff": bool(ce < d._epoch(cutoff)), "b_r_mean": None if br is None else br["mean"],
                # judge's own declared numbers
                "judge_prior": row.get("judge_prior"), "p_hit": pr["tp"]["p_hit"], "expected_r_net": pr["expected_r_net"],
                "tp_basis": pr["tp"]["basis"], "stop_basis": pr["stop"]["basis"], "confidence": pr.get("confidence"),
                "horizon": pr["horizon_bars"], "etype": pr["entry"]["type"], "n_in_packet": len(rows),
                # geometry in ATR at the cutoff
                "sl_atr": g["sl_atr"] if g else None, "tp_atr": g["tp_atr"] if g else None,
                "rr": (g["tp_atr"] / g["sl_atr"]) if g and g["sl_atr"] > 0 else None,
                # packet regime fields (what the judge saw)
                "htf_trend": u.get("htf_trend"), "session": u.get("session"),
                "dist_low_atr": sw.get("dist_low_atr"), "dist_high_atr": sw.get("dist_high_atr"),
                "base_mean_r": h_same["mean_r"] if h_same else None, "base_n": h_same["n"] if h_same else None,
                "base_opp_mean_r": h_opp["mean_r"] if h_opp else None,
                # point-in-time candle features (all <= cutoff)
                "vol_pct": _vol_pct(s, i), "ret24_atr": ret24, "ret168_atr": ret168, "hour_utc": close_dt.hour,
                "dow": close_dt.weekday(),
            })
    return out


def _tercile(vals: list[float | None]) -> tuple | None:
    v = np.array([x for x in vals if x is not None and np.isfinite(x)])
    return None if len(v) < 30 else (float(np.quantile(v, 1 / 3)), float(np.quantile(v, 2 / 3)))


def slice_defs(recs: list[dict]) -> dict[str, dict[str, Any]]:
    """{dimension: {level: predicate}}. Terciles are cut on THIS file; every (dimension, level) is one examined slice."""
    defs: dict[str, dict[str, Any]] = {}

    def cat(name, f):
        lv = sorted({f(r) for r in recs if f(r) is not None}, key=str)
        defs[name] = {str(x): (lambda r, x=x, f=f: f(r) == x) for x in lv}

    def terc(name, f):
        q = _tercile([f(r) for r in recs])
        if q is None:
            return
        defs[name] = {
            f"lo(<{q[0]:.3g})": lambda r, f=f, q=q: f(r) is not None and f(r) <= q[0],
            "mid": lambda r, f=f, q=q: f(r) is not None and q[0] < f(r) <= q[1],
            f"hi(>{q[1]:.3g})": lambda r, f=f, q=q: f(r) is not None and f(r) > q[1],
        }

    terc("judge_prior", lambda r: r["judge_prior"])
    terc("p_hit", lambda r: r["p_hit"])
    terc("expected_r_net", lambda r: r["expected_r_net"])
    cat("tp_basis", lambda r: r["tp_basis"])
    cat("symbol", lambda r: r["symbol"])
    cat("side", lambda r: r["side"])
    cat("horizon", lambda r: r["horizon"])
    cat("entry_type", lambda r: r["etype"])
    terc("sl_atr", lambda r: r["sl_atr"])
    terc("tp_atr", lambda r: r["tp_atr"])
    terc("rr", lambda r: r["rr"])
    cat("htf_trend", lambda r: r["htf_trend"])
    terc("vol_pct", lambda r: r["vol_pct"])
    terc("ret24_atr", lambda r: r["ret24_atr"])
    terc("ret168_atr", lambda r: r["ret168_atr"])
    terc("base_mean_r(h48,side)", lambda r: r["base_mean_r"])
    terc("dist_low_atr", lambda r: r["dist_low_atr"])
    cat("session", lambda r: r["session"])
    defs["hour_utc_bucket"] = {f"{a:02d}-{a + 6:02d}": (lambda r, a=a: a <= r["hour_utc"] < a + 6) for a in (0, 6, 12, 18)}
    cat("novelty", lambda r: "new" if r["novelty"] in ("new", "new_no_leg") else r["novelty"])
    cat("n_in_packet", lambda r: r["n_in_packet"])
    cat("fold", lambda r: r["fold"])
    cat("post_cutoff", lambda r: "post" if not r["pre_cutoff"] else "pre")
    cat("suspect_batch", lambda r: "suspect(1332-1365)" if SUSPECT_LO <= r["index"] <= SUSPECT_HI else "rest")
    return defs


def stat(rows: list[dict], draws: int = 3000) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    st = d.cluster_stats(rows, draws=draws)
    keep = ("n", "weeks", "mean_net_r", "mean_ci95", "net_r_per_capital_day", "per_capital_day_ci95",
            "paired_diff_vs_random", "paired_diff_ci95", "n_paired", "sd_net_r")
    return {k: st[k] for k in keep if k in st}


def cmd_decompose(a: argparse.Namespace) -> int:
    import pickle
    uni, _ = d.parse_universe()
    syms = [u["symbol"] for u in uni]
    mkt, missing = d.load_market(Path(a.candles), syms)
    if missing:
        raise SystemExit(f"candles missing {missing}")
    classes = {u["symbol"]: u["classes"] for u in uni}
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    want = [json.loads(ln)["packet_id"] for ln in Path(a.proposals).read_text().splitlines() if ln.strip()]
    packets: dict[str, dict] = {}
    cp = Path(a.cache) if a.cache else None
    if cp and cp.exists():
        packets = pickle.loads(cp.read_bytes())
    for pid in sorted(set(want) - set(packets)):
        k = keys[pid]
        m, _ = d.build_masked_packet(mkt, classes, k["cutoff_epoch"], k["index"], d.SEED)
        if m["meta"]["packet_id"] != pid or (k.get("packet_sha") and d.cdr.packet_sha(m) != k["packet_sha"]):
            raise SystemExit(f"packet drift on {pid}")
        packets[pid] = m
    if cp:
        cp.write_bytes(pickle.dumps(packets))
    by, intake = d.read_proposals(Path(a.proposals), packets)
    rost = d.rostered_legs(sorted(mkt))
    legs, _gaps = d.load_strategy_lists(rost)
    cutoff = datetime.fromisoformat(a.model_cutoff).replace(tzinfo=timezone.utc)
    recs = records(mkt, keys, by, legs, rost, cutoff, packets=packets)
    # the reproduction assertion: the driver's own score() on the same inputs
    ref = d.score(mkt, keys, by, legs, rost, subset="all", cutoff=cutoff, selfcheck=None)
    assert ref["stats"]["n"] == len(recs), (ref["stats"]["n"], len(recs))
    assert abs(ref["stats"]["mean_net_r"] - float(np.mean([r["net_r"] for r in recs]))) < 1e-12
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "records.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in recs) + "\n")

    def with_without(rows):
        no_s = [r for r in rows if not (SUSPECT_LO <= r["index"] <= SUSPECT_HI)]
        return {"with_suspect": stat(rows), "without_suspect": stat(no_s)}

    res: dict[str, Any] = {
        "driver_score_overall": {k: ref["stats"].get(k) for k in ("n", "mean_net_r", "mean_ci95", "net_r_per_capital_day",
                                                                  "per_capital_day_ci95", "paired_diff_vs_random",
                                                                  "paired_diff_ci95", "folds", "folds_positive", "post_cutoff", "sd_net_r")},
        "driver_verdict": ref["verdict"], "intake": intake, "novelty_counts": ref["counts"]["novelty"],
        "overall": with_without(recs),
        "new_subset_overall": with_without([r for r in recs if r["novelty"] in ("new", "new_no_leg")]),
    }
    sl: dict[str, Any] = {}
    n_slices = 0
    for dim, lv in slice_defs(recs).items():
        sl[dim] = {}
        for name, pred in lv.items():
            rows = [r for r in recs if pred(r)]
            n_slices += 1
            sl[dim][name] = stat(rows) | {"n_without_suspect": sum(1 for r in rows if not (SUSPECT_LO <= r["index"] <= SUSPECT_HI))}
    res["slices"] = sl
    res["n_slices_examined"] = n_slices
    res["n_dimensions"] = len(sl)
    (out / "decomposition.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=float))
    print(json.dumps({"n": len(recs), "slices": n_slices, "mean": res["overall"]["with_suspect"]["mean_net_r"],
                      "driver_verdict": ref["verdict"]}))
    return 0


# ----------------------------------------------------------------------------- the registered confirm configuration C1
# Registered in research/queue/RQ-20261027-e72b-01.yaml BEFORE any judged-2 packet exists. Not tunable after a result.
US_HOURS = tuple(range(13, 21))            # cutoff hour (UTC) of the packets whose universe `session` is `us` in judged-1
STOP_FLOOR_ATR = 1.0                       # C1: the stop is at least 1.0 ATR14 from entry
CONFIRM_MIN_GAP_H = 2
CONFIRM_SCHEDULE_LEN = 1500
CONFIRM_BATCH = 250
CONFIRM_STOP_FILLED = 600                  # stop at a batch boundary once this many VALID proposals exist (counted before replay)
CONFIRM_N_MIN = 300
CONFIRM_FOLDS_NEEDED = 3
CONFIRM_DROP_WEEKS = 3

C1_ADDENDUM = """

## Additional rules for this run (configuration C1; they bind your row)
* Propose only if your stop is at least 1.0 x the `atr` of the symbol away from your entry. A row with a nearer stop is
  excluded by the scorer and counted; it is not scored as a trade.
* This packet is from the 13:00-21:00 UTC window only; every packet you receive is in it. Everything else in the protocol stands.
"""


def us_schedule(start: datetime, end: datetime, n: int, seed: int, min_gap_h: int = CONFIRM_MIN_GAP_H,
                hours: tuple = US_HOURS) -> list[int]:
    """d.make_schedule restricted to cutoff hours `hours`: hourly closes shuffled by `seed`, kept when >= min_gap_h from every
    kept one. Greedy in a fixed order, so the first k of a length-n schedule ARE the length-k schedule."""
    import bisect
    s0, e0 = d._epoch(start), d._epoch(end)
    cands = np.array([c for c in range(s0, e0, d.SEC) if datetime.fromtimestamp(c, tz=timezone.utc).hour in hours], dtype=np.int64)
    order = np.random.default_rng(seed).permutation(len(cands))
    kept: list[int] = []
    srt: list[int] = []
    gap = min_gap_h * d.SEC
    for ix in order:
        c = int(cands[ix])
        j = bisect.bisect_left(srt, c)
        if (j > 0 and c - srt[j - 1] < gap) or (j < len(srt) and srt[j] - c < gap):
            continue
        srt.insert(j, c)
        kept.append(c)
        if len(kept) >= n:
            break
    return kept


def c1_pass(r: dict) -> bool:
    return r["hour_utc"] in US_HOURS and r["sl_atr"] is not None and r["sl_atr"] >= STOP_FLOOR_ATR


def grade_c1(st: dict[str, Any], weeks_dropped_mean: float | None) -> tuple:
    """The rule of RQ-20261027-e72b-01, deciding from numbers already computed (verbatim in the unit)."""
    n = st["n"]
    if n < CONFIRM_N_MIN:
        return "indeterminate", [f"n_filled {n} < {CONFIRM_N_MIN}"]
    s3 = st.get("paired_diff_vs_random")
    if st["mean_net_r"] <= 0 or s3 is None or s3 <= 0:
        return "fail", [f"S1 {st['mean_net_r']:+.4f} or S3 {s3} not > 0 at n {n}: no better than a random entry with the same bracket"]
    checks = [
        (st["mean_ci95"][0] > 0, "S1 CI lower bound > 0"),
        (st["net_r_per_capital_day"] > 0 and st["per_capital_day_ci95"][0] > 0, "S2 > 0 with CI lower bound > 0"),
        (st["paired_diff_ci95"][0] > 0, "S3 CI lower bound > 0"),
        (st["folds_positive"] >= CONFIRM_FOLDS_NEEDED, f"net R > 0 in >= {CONFIRM_FOLDS_NEEDED} of 4 folds (each n >= {d.FOLD_MIN_N})"),
        (weeks_dropped_mean is not None and weeks_dropped_mean > 0, f"mean net R > 0 after dropping the {CONFIRM_DROP_WEEKS} best weeks"),
    ]
    failed = [m for ok, m in checks if not ok]
    if failed:
        return "indeterminate", ["not met: " + "; ".join(failed)]
    return "pass", ["window is before the judge's knowledge cutoff: a PASS here is 'masked-replay only, forward-shadow confirmation required'"]


def _market(a: argparse.Namespace):
    uni, _ = d.parse_universe()
    syms = [u["symbol"] for u in uni]
    cdir = Path(a.candles)
    if getattr(a, "fetch", False):
        d.CANDLE_SINCE = datetime.fromisoformat(a.candles_since).replace(tzinfo=timezone.utc)
        cdir.mkdir(parents=True, exist_ok=True)
        d.fetch_market(cdir, syms)
    mkt, missing = d.load_market(cdir, syms)
    if missing:
        raise SystemExit(f"candles missing {missing}")
    return mkt, {u["symbol"]: u["classes"] for u in uni}


def _win(a):
    return (datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc), datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc))


def cmd_packets(a: argparse.Namespace) -> int:
    """Masked packets for the confirm run: US-session cutoffs of a window, fresh seed. Same builder, mask and leak scan as the
    driver; the key's fold is cut on THIS window (the driver's build_masked_packet cuts it on its own)."""
    mkt, classes = _market(a)
    start, end = _win(a)
    sched = us_schedule(start, end, CONFIRM_SCHEDULE_LEN, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys, leaked = [], 0
    with (out / "packets.jsonl").open("w") as fh:
        for off, ce in enumerate(sched[a.offset: a.offset + a.n]):
            k = a.offset + off
            m, key = d.build_masked_packet(mkt, classes, ce, k, a.seed)
            if d.leak_scan(json.dumps(m, sort_keys=True), key, sorted(mkt)):
                leaked += 1
                continue
            key["fold"] = d.fold_of(ce, start, end)
            key["packet_sha"] = d.cdr.packet_sha(m)
            fh.write(json.dumps({"packet_id": m["meta"]["packet_id"], "packet": m}, sort_keys=True) + "\n")
            keys.append(key)
    (out / "mask-key.json").write_text(json.dumps({"seed": a.seed, "note": "NEVER given to the judging session", "keys": keys}, indent=1) + "\n")
    (out / "JUDGE-PROTOCOL.md").write_text(d.JUDGE_PROTOCOL % {"cap": d.MAX_PER_PACKET, "sent": d.cdr.SENTINEL_R_FLOOR,
                                                              "cap_pct": d.cdr.TP_VENUE_CAP_PCT * 100, "reach": d.cdr.REACH_FLOOR,
                                                              "minrisk": d.MIN_RISK_ATR} + C1_ADDENDUM)
    print(json.dumps({"packets": len(keys), "withheld_for_leak": leaked, "schedule_len": len(sched)}))
    return 0


def cmd_confirm(a: argparse.Namespace) -> int:
    mkt, classes = _market(a)
    start, end = _win(a)
    keys = {k["packet_id"]: k for k in json.loads(Path(a.mask_key).read_text())["keys"]}
    want = {json.loads(ln)["packet_id"] for ln in Path(a.proposals).read_text().splitlines() if ln.strip()}
    packets = {}
    for pid in sorted(want):
        k = keys[pid]
        m, _ = d.build_masked_packet(mkt, classes, k["cutoff_epoch"], k["index"], a.seed)
        if m["meta"]["packet_id"] != pid or (k.get("packet_sha") and d.cdr.packet_sha(m) != k["packet_sha"]):
            raise SystemExit(f"packet drift on {pid}")
        packets[pid] = m
    by, intake = d.read_proposals(Path(a.proposals), packets)
    idx = sorted(int(keys[p]["index"]) for p in by)
    last_start = ((len(idx) - 1) // CONFIRM_BATCH) * CONFIRM_BATCH if idx else 0
    before = sum(len(v) for p, v in by.items() if int(keys[p]["index"]) < last_start)
    stop_ok = idx == list(range(len(idx))) and before < CONFIRM_STOP_FILLED
    rost = d.rostered_legs(sorted(mkt))
    legs, _ = d.load_strategy_lists(rost)
    cutoff = datetime.fromisoformat(a.model_cutoff).replace(tzinfo=timezone.utc)
    allr = records(mkt, keys, by, legs, rost, cutoff, seed=a.seed, packets=packets, start=start, end=end)
    recs = [r for r in allr if c1_pass(r)]
    st = d.cluster_stats(recs, seed=a.seed) if recs else {"n": 0}
    st["n"] = len(recs)
    top = sorted({r["week"] for r in recs}, key=lambda w: -sum(r["net_r"] for r in recs if r["week"] == w))[:CONFIRM_DROP_WEEKS]
    rest = [r["net_r"] for r in recs if r["week"] not in top]
    wdm = float(np.mean(rest)) if rest else None
    if recs:
        st["folds"] = {str(f): {"n": sum(1 for r in recs if r["fold"] == f),
                                "mean_net_r": float(np.mean([r["net_r"] for r in recs if r["fold"] == f])) if any(r["fold"] == f for r in recs) else None}
                       for f in range(1, d.N_FOLDS + 1)}
        st["folds_positive"] = sum(1 for v in st["folds"].values() if v["n"] >= d.FOLD_MIN_N and v["mean_net_r"] and v["mean_net_r"] > 0)
        st["mean_after_dropping_best_weeks"] = wdm
        st["best_weeks_dropped"] = top
    verdict, why = grade_c1(st, wdm) if recs else ("indeterminate", ["no filled proposals"])
    if not stop_ok:
        verdict, why = "indeterminate", [("judged packets break the registered stopping rule (not a schedule prefix, or judging continued past "
                                          f"{CONFIRM_STOP_FILLED} valid proposals before the last batch)")] + why
    res = {"verdict": verdict, "reasons": why, "stats": st,
           "design": {"packets_judged": len(idx), "stopping_rule_respected": stop_ok, "valid_proposals_before_last_batch": before,
                      "filled_all_configs": len(allr), "filled_c1": len(recs),
                      "excluded_by_c1": len(allr) - len(recs)}, "intake": intake}
    notes = "; ".join(why)
    d._write_verdict(Path(a.out), res, f"C1 entry generation on {a.start}..{a.end}: {len(recs)} filled proposals from {len(idx)} judged packets",
                     len(recs), notes, None, d.candle_manifest(mkt))
    print(json.dumps({"verdict": verdict, "n_filled_c1": len(recs), "mean_net_r": st.get("mean_net_r"), "S3": st.get("paired_diff_vs_random")}))
    return 0


def forward_records(mkt, rows: list[dict], start: datetime, end: datetime, seed: int = d.SEED, draws: int = d.B_R_DRAWS) -> tuple:
    """Replay the desk's recorded REAL-symbol propose_entry rows (comms/desk/decisions.jsonl) with the driver's engine and
    the same S1/S2/S3 definitions. The random-entry pool is every eligible hourly cutoff of the same symbol in [start, end)."""
    rng = np.random.default_rng(seed + 7)
    out, skipped = [], {"not_a_proposal": 0, "symbol_without_candles": 0, "unresolved_or_unfilled": 0, "refused": 0}
    pools: dict[str, np.ndarray] = {}
    for row in rows:
        pr = row.get("proposal")
        if row.get("action") != "propose_entry" or not isinstance(pr, dict):
            skipped["not_a_proposal"] += 1
            continue
        sym = pr["symbol"]
        if sym not in mkt:
            skipped["symbol_without_candles"] += 1
            continue
        s = mkt[sym]
        ce = d._epoch(datetime.fromisoformat(row["info_cutoff_at"].replace("Z", "+00:00")))
        i = s.last_closed(ce)
        side = 1.0 if pr["side"] == "long" else -1.0
        e = pr["entry"]
        t = d.simulate(s, i, side, e["type"], e["level"], pr["stop"]["level"], pr["tp"]["level"], e["good_till_bars"], pr["horizon_bars"])
        if t.state != "filled":
            skipped["refused" if t.state == "refused" else "unresolved_or_unfilled"] += 1
            continue
        g = d.geometry_of(s, i, side, e["type"], e["level"], pr["stop"]["level"], pr["tp"]["level"], e["good_till_bars"], pr["horizon_bars"])
        br = None
        if g is not None:
            if sym not in pools:
                pools[sym] = d.eligible_cutoffs(s, start, end)
            br = d.random_baseline(s, g, pools[sym], rng, draws)
        hour = datetime.fromtimestamp(ce, tz=timezone.utc).hour
        out.append({"decision_id": row.get("decision_id"), "symbol": sym, "side": pr["side"], "week": d.iso_week(ce), "net_r": t.net_r,
                    "days": t.days, "diff": None if br is None or br["mean"] is None else t.net_r - br["mean"], "exit": t.reason,
                    "hour_utc": hour, "sl_atr": g["sl_atr"] if g else None, "fold": 1})
    return out, skipped


def cmd_forward(a: argparse.Namespace) -> int:
    mkt, _ = _market(a)
    rows = [json.loads(ln) for ln in Path(a.decisions).read_text().splitlines() if ln.strip()]
    ts = [d._epoch(datetime.fromisoformat(r["info_cutoff_at"].replace("Z", "+00:00"))) for r in rows]
    start = datetime.fromtimestamp(min(ts), tz=timezone.utc) if ts else datetime(2026, 10, 26, tzinfo=timezone.utc)
    # random entries need >= 100 bars of forward room, so the pool ends 5 days before the last candle
    end = datetime.fromtimestamp(max(int(s.t[-1]) for s in mkt.values()) - 5 * 86400, tz=timezone.utc)
    end = max(start, end)
    recs, skipped = forward_records(mkt, rows, start, end)
    c1 = [r for r in recs if c1_pass(r)]
    res = {"verdict": "not_applicable", "read_state": "measured" if recs else "no_data", "rows_read": len(rows), "skipped": skipped,
           "all_filled": stat(recs, 10000), "c1_filled": stat(c1, 10000), "pool_window": [start.isoformat(), end.isoformat()],
           "n_all": len(recs), "n_c1": len(c1),
           "read": ("n_c1 >= 100: S1 and S3 point estimates reported; n < 100: reported as could-not-conclude (the unit's rule)"
                    if len(c1) < 100 else "n_c1 >= 100")}
    d._write_verdict(Path(a.out), res, f"forward desk proposals replayed: {len(recs)} filled ({len(c1)} in C1) of {len(rows)} decision rows",
                     len(recs), json.dumps(skipped), None, d.candle_manifest(mkt))
    print(json.dumps({"rows": len(rows), "n_all": len(recs), "n_c1": len(c1), "skipped": skipped}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("decompose", cmd_decompose), ("packets", cmd_packets), ("confirm", cmd_confirm), ("forward", cmd_forward)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--candles", required=True)
        s.add_argument("--fetch", action="store_true")
        s.add_argument("--candles-since", default="2024-05-01")
        s.set_defaults(fn=fn)
        if name in ("decompose", "confirm"):
            s.add_argument("--mask-key", required=True)
            s.add_argument("--proposals", required=True)
            s.add_argument("--model-cutoff", default="2026-06-01")
        if name == "decompose":
            s.add_argument("--cache", default=None, help="pickle path for re-derived packets")
        if name in ("packets", "confirm"):
            s.add_argument("--start", default="2024-11-01")
            s.add_argument("--end", default="2025-10-25")
            s.add_argument("--seed", type=int, default=20261028)
        if name == "packets":
            s.add_argument("--n", type=int, required=True)
            s.add_argument("--offset", type=int, default=0)
        if name == "forward":
            s.add_argument("--decisions", required=True)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
