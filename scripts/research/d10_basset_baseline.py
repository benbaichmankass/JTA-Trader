#!/usr/bin/env python3
# wiring: research/queue/RQ-20261117-aadc-05.yaml (row ML-D10-BASSET-BASELINE); session-local first read over diag-relay pulls,
#         then the same command on the VM journal (--journal-db) when a VM-side run is routed
"""D10 Basset BASELINE: how well does a plain decay detector on realised net R anticipate a leg going bad, and does the blind
post-trade grade (CJ-4) do any better? (row ML-D10-BASSET-BASELINE; Tier-1 research, reads only.)

D10 (review & grading) has no model. Before any learned grade is built, the bar it must beat is set here:

  BASELINE  per leg, in closed_at order, a one-sided Page CUSUM on winsorised net R below the leg's OWN Stage-0 expectancy
            (comms/strategy_evidence/<leg>.json `expectancy_r_oos`, coverage_state measured):
                S_i = max(0, S_{i-1} + (mu0 - K - clip(R_i, -CLIP, +CLIP)))
            S_i uses trades <= i only.
  OUTCOME   decay(i) = 1 iff the mean net R of the leg's NEXT N trades (i+1 .. i+N) is < 0. Points without N future trades
            are not labelled (counted).
  SCORE     AUC of S_i for decay(i), pooled over (leg, i); 95% CI by a LEG-cluster bootstrap (legs resampled, 2000 draws).
            Also the alarm view at S_i >= H: alarm share, decay rate when alarmed vs not.
  COMPARATOR (reported, part of the rule) the blind grade: g_i = -(mean grade_score of the leg's last W graded trades <= i)
            (low grades -> higher decay score), AUC on the points where it exists. 089f-01 found grade ANTI-correlated with net R
            (rho -0.18), so the comparator's registered direction is stated before the run and not flipped after it.

Net R = net USD / initial risk USD, net USD = pnl - taker fee - maker fee - funding, initial risk = |entry - PACKAGE sl| x qty
(the package's sl is the initial stop; trades.stop_loss is mirrored from trailing amends, ml.datasets.families.claude_judgments).

    python3 scripts/research/d10_basset_baseline.py --trades 'P/trades_*.json' --packages 'P/op_*.json' --out O
    python3 scripts/research/d10_basset_baseline.py --journal-db trade_journal.db --out O
    python3 scripts/research/d10_basset_baseline.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[2]
UNIT = "RQ-20261117-aadc-05"
RULE_ID = "RULE-RQ20261117-aadc-05-D10-BASELINE"
K, CLIP, H = 0.25, 3.0, 3.0      # CUSUM slack (R), winsor (R), alarm level (R): fixed by the unit before the run
N_NEXT, W_GRADE = 20, 10
MIN_POINTS, MIN_LEGS = 200, 3
BOOT, SEED = 2000, 20261117


# ── data ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _f(v) -> Optional[float]:
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def net_r(t: dict, pkg_sl: Optional[float]) -> Optional[float]:
    pnl, e, q = _f(t.get("pnl")), _f(t.get("entry_price")), _f(t.get("position_size"))
    if pnl is None or e is None or q is None or pkg_sl is None:
        return None
    risk = abs(e - pkg_sl) * abs(q)
    if risk <= 0:
        return None
    net = pnl - (_f(t.get("fee_taker_usd")) or 0.0) - (_f(t.get("fee_maker_usd")) or 0.0) - (_f(t.get("funding_paid_usd")) or 0.0)
    return net / risk


def load_pages(trades_glob: str, packages_glob: str) -> List[dict]:
    T: Dict[int, dict] = {}
    for f in sorted(glob.glob(trades_glob)):
        for t in json.loads(Path(f).read_text()):
            T[int(t["id"])] = t
    P: Dict[str, dict] = {}
    for f in sorted(glob.glob(packages_glob)):
        for p in json.loads(Path(f).read_text()):
            P[str(p["order_package_id"])] = p
    out = []
    for t in T.values():
        p = P.get(str(t.get("order_package_id") or ""))
        out.append({**t, "pkg_sl": _f(p.get("sl")) if p else None})
    return out


def load_db(db: Path) -> List[dict]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT t.*, op.sl AS pkg_sl FROM trades t LEFT JOIN order_packages op "
                            "ON op.order_package_id = t.order_package_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stage0(evidence_dir: Path) -> Dict[str, float]:
    out = {}
    for f in evidence_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if d.get("coverage_state") == "measured" and _f(d.get("expectancy_r_oos")) is not None:
            out[f.stem] = float(d["expectancy_r_oos"])
    return out


def leg_series(trades: List[dict], mu: Dict[str, float]) -> tuple[Dict[str, List[dict]], dict]:
    ex = {"not_closed": 0, "no_leg_record": 0, "no_net_r": 0, "backtest": 0}
    by: Dict[str, List[dict]] = {}
    for t in trades:
        if t.get("is_backtest"):
            ex["backtest"] += 1
            continue
        if str(t.get("status")) != "closed" or not t.get("closed_at"):
            ex["not_closed"] += 1
            continue
        leg = str(t.get("strategy_name") or "")
        if leg not in mu:
            ex["no_leg_record"] += 1
            continue
        r = net_r(t, t.get("pkg_sl"))
        if r is None:
            ex["no_net_r"] += 1
            continue
        by.setdefault(leg, []).append({"trade_id": int(t["id"]), "closed_at": str(t["closed_at"]), "r": r})
    for v in by.values():
        v.sort(key=lambda x: (x["closed_at"], x["trade_id"]))
    return by, ex


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def cusum_path(rs: List[float], mu0: float) -> List[float]:
    s, out = 0.0, []
    for r in rs:
        s = max(0.0, s + (mu0 - K - float(np.clip(r, -CLIP, CLIP))))
        out.append(s)
    return out


def points(by: Dict[str, List[dict]], mu: Dict[str, float], grades: Dict[int, int]) -> List[dict]:
    pts = []
    for leg, seq in by.items():
        rs = [x["r"] for x in seq]
        S = cusum_path(rs, mu[leg])
        graded: List[int] = []
        for i, x in enumerate(seq):
            if x["trade_id"] in grades:
                graded.append(grades[x["trade_id"]])
            if i + N_NEXT >= len(seq):
                continue
            fut = float(np.mean(rs[i + 1:i + 1 + N_NEXT]))
            g = -float(np.mean(graded[-W_GRADE:])) if graded else None
            pts.append({"leg": leg, "i": i, "cusum": S[i], "grade_score_signal": g, "decay": int(fut < 0)})
    return pts


def auc(score: np.ndarray, y: np.ndarray) -> Optional[float]:
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return None
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort().astype(float) + 1
    # average ranks for ties
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=ranks)
    ranks = (sums / cnt)[inv]
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def leg_boot(pts: List[dict], key: str) -> dict:
    sel = [p for p in pts if p[key] is not None]
    legs = sorted({p["leg"] for p in sel})
    if not sel:
        return {"n": 0, "legs": 0, "auc": None, "ci95": None}
    s, y = np.array([p[key] for p in sel], float), np.array([p["decay"] for p in sel])
    a = auc(s, y)
    by = {lg: [k for k, p in enumerate(sel) if p["leg"] == lg] for lg in legs}
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(BOOT):
        idx = np.concatenate([by[legs[j]] for j in rng.integers(0, len(legs), len(legs))])
        v = auc(s[idx], y[idx])
        if v is not None:
            bs.append(v)
    ci = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)] if bs else None
    return {"n": len(sel), "legs": len(legs), "decay_rate": round(float(y.mean()), 4), "auc": None if a is None else round(a, 4),
            "ci95": ci}


def verdict(base: dict) -> tuple[str, str]:
    if base["n"] < MIN_POINTS or base["legs"] < MIN_LEGS or base["ci95"] is None:
        return "indeterminate", f"labelled points {base['n']} / legs {base['legs']} below {MIN_POINTS} / {MIN_LEGS}"
    if base["auc"] > 0.5 and base["ci95"][0] > 0.5:
        return "pass", f"CUSUM baseline AUC {base['auc']} (leg-cluster CI95 {base['ci95']}) > 0.5: a working decay detector"
    return "fail", f"CUSUM baseline AUC {base['auc']} (CI95 {base['ci95']}) does not clear 0.5: no baseline skill"


# ── ACTION replay (RQ-20261117-aadc-06): does acting on the alarm add net R? ─────────────────────────────────────────
ACTION_UNIT = "RQ-20261117-aadc-06"
ACTION_RULE_ID = "RULE-RQ20261117-aadc-06-D10-ALARM-ACTION"
MIN_ALARMED = 50


def action_replay(by: Dict[str, List[dict]], mu: Dict[str, float], draws: int = BOOT, seed: int = SEED) -> dict:
    """Policy DEMOTE-ON-ALARM: trade i of a leg is NOT taken on the real-money book when the leg's CUSUM through trade i-1 is
    >= H (the alarm is known before trade i is entered). The leg keeps trading on the demo floor, so the CUSUM keeps updating on
    every trade (alarmed ones included) and the alarm clears when S falls below H. added_r = -(sum net R of the skipped trades).
    Control: per leg, skip the SAME number of trades at uniformly random positions (draws, seed); control_p = share of draws
    whose added_r >= actual (+1 smoothing). Per-leg added_r reported."""
    rng = np.random.default_rng(seed)
    skipped_r, per_leg, legs_r = [], {}, []
    for leg, seq in by.items():
        rs = np.array([x["r"] for x in seq], float)
        S = cusum_path(list(rs), mu[leg])
        alarmed = np.array([i > 0 and S[i - 1] >= H for i in range(len(rs))])
        k = int(alarmed.sum())
        legs_r.append((rs, k))
        if k:
            per_leg[leg] = {"n": len(rs), "skipped": k, "added_r": round(float(-rs[alarmed].sum()), 3)}
            skipped_r.extend(rs[alarmed].tolist())
    actual = float(-np.sum(skipped_r)) if skipped_r else 0.0
    ctrl = np.empty(draws)
    for d in range(draws):
        tot = 0.0
        for rs, k in legs_r:
            if k:
                tot -= rs[rng.choice(len(rs), k, replace=False)].sum()
        ctrl[d] = tot
    p = float((np.sum(ctrl >= actual) + 1) / (draws + 1))
    return {"n_alarmed": len(skipped_r), "legs_with_alarm": len(per_leg), "added_r": round(actual, 3),
            "mean_r_skipped": round(float(np.mean(skipped_r)), 4) if skipped_r else None,
            "control_mean_added_r": round(float(ctrl.mean()), 3), "control_p95_added_r": round(float(np.percentile(ctrl, 95)), 3),
            "control_p": round(p, 4), "legs_positive": sum(1 for v in per_leg.values() if v["added_r"] > 0), "per_leg": per_leg}


def action_verdict(r: dict) -> tuple[str, str]:
    if r["n_alarmed"] < MIN_ALARMED:
        return "indeterminate", f"alarmed trades {r['n_alarmed']} < {MIN_ALARMED}"
    if r["added_r"] > 0 and r["control_p"] <= 0.05:
        return "pass", f"demote-on-alarm adds {r['added_r']:+.2f} R over {r['n_alarmed']} skipped trades, control_p {r['control_p']}"
    return "fail", f"demote-on-alarm added_r {r['added_r']:+.2f} R, control_p {r['control_p']} (needs > 0 and <= 0.05)"


def run(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    trades = load_db(Path(a.journal_db)) if a.journal_db else load_pages(a.trades, a.packages)
    mu = stage0(Path(a.evidence_dir))
    grades = {}
    for line in Path(a.judgments).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if isinstance(r.get("trade_id"), int) and isinstance(r.get("grade_score"), int):
                grades[r["trade_id"]] = r["grade_score"]
    by, ex = leg_series(trades, mu)
    if a.action_replay:
        ar = action_replay(by, mu)
        v, why = action_verdict(ar)
        res = {"verdict": v, "read_state": "measured", "n": ar["n_alarmed"],
               "population": (f"closed live/paper journal trades on {len(by)} legs with a measured Stage-0 record, net R on the package "
                              "initial stop, in closed_at order; skipped = trades entered while the leg's CUSUM through the previous "
                              f"trade was >= {H}"),
               "note": why, "measurement": {"rule": ACTION_RULE_ID, "replay": ar, "params": {"K": K, "CLIP": CLIP, "H": H},
                                            "trades_in": len(trades), "excluded": ex, "stage0_records": len(mu)}}
        out.joinpath("verdict.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({"verdict": v, "note": why}, indent=1))
        return 0
    pts = points(by, mu, grades)
    base, comp = leg_boot(pts, "cusum"), leg_boot(pts, "grade_score_signal")
    al = [p for p in pts if p["cusum"] >= H]
    na = [p for p in pts if p["cusum"] < H]
    alarm = {"h": H, "alarm_share": round(len(al) / len(pts), 4) if pts else None,
             "decay_rate_alarmed": round(float(np.mean([p["decay"] for p in al])), 4) if al else None,
             "decay_rate_not_alarmed": round(float(np.mean([p["decay"] for p in na])), 4) if na else None}
    v, why = verdict(base)
    res = {"verdict": v, "read_state": "measured", "n": base["n"],
           "population": (f"(leg, trade) points of closed live/paper trades on legs with a measured Stage-0 record, net R on the "
                          f"package initial stop, each with {N_NEXT} later trades on the same leg; {len(by)} legs"),
           "note": f"{why}; comparator (blind grade, low = decay) AUC {comp['auc']} CI95 {comp['ci95']} on n {comp['n']}",
           "measurement": {"rule": RULE_ID, "baseline_cusum": base, "comparator_blind_grade": comp, "alarm": alarm,
                           "params": {"K": K, "CLIP": CLIP, "H": H, "N_NEXT": N_NEXT, "W_GRADE": W_GRADE},
                           "trades_in": len(trades), "excluded": ex, "legs": {lg: len(s) for lg, s in by.items()},
                           "stage0_records": len(mu), "grades_in": len(grades)}}
    (out / "verdict.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({"verdict": v, "note": res["note"]}, indent=1))
    return 0


# ── self-test ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _self_test() -> int:
    assert cusum_path([0.5, -1.0, -1.0, 2.0], 0.25) == [0.0, 1.0, 2.0, 0.0]
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2, "fee_taker_usd": 1, "fee_maker_usd": 0,
                  "funding_paid_usd": 1}, 95.0) == 0.8
    assert net_r({"pnl": 10, "entry_price": 100, "position_size": 2}, None) is None
    assert auc(np.array([1, 2, 3, 4.0]), np.array([0, 0, 1, 1])) == 1.0
    assert auc(np.array([1, 1, 1, 1.0]), np.array([0, 1, 0, 1])) == 0.5
    # synthetic: legs that turn bad mid-series -> CUSUM must detect (AUC > 0.5); a grade unrelated to decay ~0.5
    rng = np.random.default_rng(3)
    by, mu, grades = {}, {}, {}
    tid = 0
    for k in range(6):
        leg = f"L{k}"
        mu[leg] = 0.2
        seq = []
        for i in range(120):
            bad = i >= 60 and k % 2 == 0
            seq.append({"trade_id": tid, "closed_at": f"2026-01-01T{i:04d}", "r": float(rng.normal(-0.6 if bad else 0.3, 1.0))})
            grades[tid] = int(rng.integers(0, 5))
            tid += 1
        by[leg] = seq
    pts = points(by, mu, grades)
    b, c = leg_boot(pts, "cusum"), leg_boot(pts, "grade_score_signal")
    assert b["auc"] > 0.6 and b["legs"] == 6, b
    assert abs(c["auc"] - 0.5) < 0.1, c
    assert verdict({"n": 50, "legs": 6, "auc": 0.7, "ci95": [0.6, 0.8]})[0] == "indeterminate"
    assert verdict({"n": 500, "legs": 6, "auc": 0.7, "ci95": [0.6, 0.8]})[0] == "pass"
    assert verdict({"n": 500, "legs": 6, "auc": 0.55, "ci95": [0.45, 0.65]})[0] == "fail"
    by2, ex = leg_series([{"id": 1, "status": "open"}, {"id": 2, "status": "closed", "closed_at": "x", "strategy_name": "nope"}], mu)
    assert ex["not_closed"] == 1 and ex["no_leg_record"] == 1 and not by2
    # action replay: a leg that turns bad -> skipping alarmed trades adds R and beats random skips
    ar = action_replay(by, mu, draws=300)
    assert ar["n_alarmed"] > 0 and ar["added_r"] > 0 and ar["control_p"] < 0.05, ar
    assert action_verdict({"n_alarmed": 10, "added_r": 5, "control_p": 0.01})[0] == "indeterminate"
    assert action_verdict({"n_alarmed": 80, "added_r": 5, "control_p": 0.2})[0] == "fail"
    # the alarm uses S through trade i-1 only: a single huge loss at the last trade is never itself skipped
    one = {"L": [{"trade_id": 0, "closed_at": "a", "r": 0.3}, {"trade_id": 1, "closed_at": "b", "r": -3.0}]}
    assert action_replay(one, {"L": 0.2}, draws=10)["n_alarmed"] == 0
    print("d10_basset_baseline self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trades", help="glob of /api/diag/journal?table=trades JSON pages")
    ap.add_argument("--packages", help="glob of /api/diag/journal?table=order_packages JSON pages")
    ap.add_argument("--journal-db", help="trade_journal.db (read-only) instead of the page globs")
    ap.add_argument("--evidence-dir", default=str(REPO / "comms" / "strategy_evidence"))
    ap.add_argument("--judgments", default=str(REPO / "comms" / "claude_judgments" / "blind_grades.jsonl"))
    ap.add_argument("--out")
    ap.add_argument("--action-replay", action="store_true", help="RQ-20261117-aadc-06: demote-on-alarm replay instead of the AUC read")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out or not (a.journal_db or (a.trades and a.packages)):
        ap.error("--out and either --journal-db or (--trades and --packages) are required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
