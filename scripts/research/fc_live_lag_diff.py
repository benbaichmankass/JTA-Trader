#!/usr/bin/env python3
"""D2 follow-on to RQ-20261119-a10d-01: WHICH offline bar does the live fc_* block equal?

PI-20261119-K7ZSW5Z7-0005, unit RQ-20261119-ef40-02.

a10d-01 FAILED: after the stride-1 rebuild removed the 75% fc_* staleness, the served fc-pcv-v2 heads still label the
rebuilt row and the live row alike on only 0.9736 (BTC) / 0.9307 (SOL) of matched bars, and the forecast_fc block
reproduces 100% of the flips. fc_ret_med differs by > 1e-3 relative on 44.9% of matched BTC bars although every
non-forecast column (returns, vol estimators, calendar) agrees. So the CLOSES agree and the FORECAST differs.

Named candidate cause (src/runtime/forecast_live.py MAX_FORECAST_LAG_BARS = 1): the per-bar scorer serves the most
recent PUBLISHED forecast, and "the previous bar's forecast is the normal in-flight case". If so, a live row's fc_*
equals the offline fc_* of an EARLIER bar, not of its own bar.

WHAT IT DOES, per head (BTCUSDT, SOLUSDT, 15m), over the committed live snapshot comms/live_parity/vol_serve_rows_20261118
(the rows a10d-01 graded): match each live row to its own rebuilt bar exactly as vol_serve_path_diff.diff_head does
(same_bar on calendar + log_return at offsets 0/-1/+1), then compare its six fc_* values with the rebuilt stride-1
fc_* at bar offsets k in {-2,-1,0,+1,+2} relative to that matched bar. Each matched row is classed:
  exact_k0      all six fc_* within EXACT_TOL of the own bar;
  exact_k<k>    not k0, but within EXACT_TOL of exactly one other offset (the lag);
  near_only     no exact offset; the best offset is within NEAR_TOL on every column;
  none          nothing within NEAR_TOL (a different window, model or input).
Reported: the class shares, the lag distribution, the run length of lag-1 streaks, the scoring second-into-bar per
class (does a late score get the fresh forecast?), and per-column |diff| quantiles for near_only / none.

Registered rule (RULE-RQ20261119-ef40-02-FC-LIVE-LAG), per head:
  INDETERMINATE  matched rows < 200, or the rebuilt dataset is missing (could_not_look);
  LAG_EXPLAINS   share(exact_k0) + share(exact at the single most common nonzero k) >= 0.98;
  RESIDUAL       otherwise (the none / near_only rows name what else differs).
Unit verdict: LAG_EXPLAINS only if both heads are; RESIDUAL if any head is; else INDETERMINATE.

Tier-1 research tooling: reads the trainer's rebuilt dataset and the committed snapshot; writes only --out.
Serves, trains, stages and promotes nothing; edits no config; places no order.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

RULE_ID = "RULE-RQ20261119-ef40-02-FC-LIVE-LAG"
FC_COLS = ["fc_ret_med", "fc_range_rel", "fc_up_prob", "fc_skew", "fc_q10_rel", "fc_q90_rel"]
OFFSETS = [-2, -1, 0, 1, 2]
EXACT_TOL = 1e-6      # relative-or-absolute: float round-trip noise only
NEAR_TOL = 1e-3       # a10d-01's "differing" threshold
MIN_MATCHED = 200
LAG_OK = 0.98
TF_S = 900
DEFAULT_SNAPSHOT = REPO / "comms/live_parity/vol_serve_rows_20261118"
DEFAULT_REBUILT = "runtime_logs/research/fc_stride1/datasets/market_features/{sym}/15m/v002/data.jsonl"


def _close(a: Any, b: Any, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    if math.isnan(x) or math.isnan(y):
        return math.isnan(x) and math.isnan(y)
    return abs(x - y) <= tol + tol * abs(y)


def fc_match(live: Mapping[str, Any], rep: Optional[Mapping[str, Any]], tol: float) -> bool:
    return rep is not None and all(_close(live.get(c), rep.get(c), tol) for c in FC_COLS)


def _key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def classify(live_fc: Mapping[str, Any], own: datetime, rep_by_ts: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Class of one matched live row against the rebuilt fc_* at OFFSETS around its own bar."""
    reps = {k: rep_by_ts.get(_key(own + timedelta(seconds=TF_S * k))) for k in OFFSETS}
    if fc_match(live_fc, reps[0], EXACT_TOL):
        return {"cls": "exact_k0", "k": 0}
    hits = [k for k in OFFSETS if k != 0 and fc_match(live_fc, reps[k], EXACT_TOL)]
    if len(hits) == 1:
        return {"cls": f"exact_k{hits[0]:+d}", "k": hits[0]}
    if len(hits) > 1:
        return {"cls": "exact_ambiguous", "k": None}
    best, best_err = None, None
    for k, r in reps.items():
        if r is None:
            continue
        errs = []
        for c in FC_COLS:
            try:
                errs.append(abs(float(live_fc.get(c)) - float(r.get(c))) / (abs(float(r.get(c))) + 1e-12))
            except (TypeError, ValueError):
                errs.append(float("inf"))
        e = max(errs)
        if best_err is None or e < best_err:
            best, best_err = k, e
    diffs = {}
    if best is not None:
        r = reps[best]
        for c in FC_COLS:
            try:
                diffs[c] = abs(float(live_fc.get(c)) - float(r.get(c)))
            except (TypeError, ValueError):
                diffs[c] = None
    if best is not None and fc_match(live_fc, reps[best], NEAR_TOL):
        return {"cls": "near_only", "k": best, "diffs": diffs}
    return {"cls": "none", "k": best, "diffs": diffs}


def grade(m: Dict[str, Any]) -> tuple[str, str]:
    if m.get("read_state") != "measured":
        return "INDETERMINATE", f"read_state {m.get('read_state')}"
    n = m["n_matched"]
    if n < MIN_MATCHED:
        return "INDETERMINATE", f"matched {n} < {MIN_MATCHED}"
    sh = m["class_share"]
    nz = {c: v for c, v in sh.items() if c.startswith("exact_k") and c != "exact_k0"}
    top = max(nz, key=nz.get) if nz else None
    expl = sh.get("exact_k0", 0.0) + (nz[top] if top else 0.0)
    m["lag_explained_share"] = round(expl, 4)
    m["dominant_lag_class"] = top
    if expl >= LAG_OK:
        return "LAG_EXPLAINS", f"exact_k0 + {top} = {expl:.4f} >= {LAG_OK}"
    return "RESIDUAL", f"exact_k0 + {top} = {expl:.4f} < {LAG_OK}"


def _q(v: List[float], p: float) -> Optional[float]:
    v = sorted(x for x in v if x is not None and not math.isnan(x))
    return round(v[min(len(v) - 1, int(p * len(v)))], 8) if v else None


def diff_symbol(sym: str, rebuilt: Path, snapshot: Path) -> Dict[str, Any]:
    import vol_serve_path_diff as D
    from ml_vol_label_replay import iter_projected_rows

    res: Dict[str, Any] = {"symbol": sym, "rebuilt": str(rebuilt), "snapshot": str(snapshot)}
    if not rebuilt.is_file():
        res["read_state"] = "could_not_look"
        res["error"] = f"rebuilt dataset missing: {rebuilt}"
        return res
    live = [json.loads(x) for x in snapshot.read_text().splitlines() if x.strip()]
    live = [r for r in live if r.get("feature_row")]
    want = set()
    for r in live:
        for off in range(-4, 4):
            want.add(_key(D.bar_open(r["predicted_at_utc"], "15m", off)))
    keep = FC_COLS + ["log_return", "hour_of_day", "dayofweek"]
    rep_by_ts: Dict[str, Dict[str, Any]] = {}
    for row in iter_projected_rows(rebuilt, keep):
        k = D._ts_key(row.get("ts"))
        if k in want:
            rep_by_ts[k] = row
    classes: Counter = Counter()
    sec_by_cls: Dict[str, List[int]] = {}
    col_diffs: Dict[str, List[float]] = {c: [] for c in FC_COLS}
    seq: List[tuple[int, Optional[int]]] = []
    unmatched = 0
    for r in sorted(live, key=lambda x: x["predicted_at_utc"]):
        fr = r["feature_row"]
        own = None
        for off in (0, -1, 1):
            dt = D.bar_open(r["predicted_at_utc"], "15m", off)
            rep = rep_by_ts.get(_key(dt))
            if rep is not None and D.same_bar(fr, rep):
                own = dt
                break
        if own is None:
            unmatched += 1
            continue
        c = classify(fr, own, rep_by_ts)
        classes[c["cls"]] += 1
        t = datetime.fromisoformat(r["predicted_at_utc"].replace("Z", "+00:00"))
        sec_by_cls.setdefault(c["cls"], []).append(int(t.timestamp()) % TF_S)
        seq.append((int(own.timestamp()) // TF_S, c["k"]))
        for col, v in (c.get("diffs") or {}).items():
            if v is not None:
                col_diffs[col].append(v)
    n = sum(classes.values())
    streaks: Counter = Counter()
    cur, prev_bar = 0, None
    for b, k in seq:
        if k == -1 and cur and prev_bar is not None and b - prev_bar == 1:
            cur += 1
        else:
            if cur:
                streaks[cur] += 1
            cur = 1 if k == -1 else 0
        prev_bar = b
    if cur:
        streaks[cur] += 1
    res.update({
        "read_state": "measured", "n_live": len(live), "n_matched": n, "n_unmatched": unmatched,
        "class_counts": dict(classes),
        "class_share": {c: round(v / n, 4) for c, v in classes.items()} if n else {},
        "score_second_into_bar_p50_by_class": {c: _q(v, 0.5) for c, v in sec_by_cls.items()},
        "lag_minus1_streak_lengths": dict(sorted(streaks.items())),
        "unexplained_abs_diff_quantiles": {c: {"p50": _q(v, 0.5), "p90": _q(v, 0.9), "n": len(v)}
                                           for c, v in col_diffs.items()},
        "dataset_last_bar": max(rep_by_ts) if rep_by_ts else None,
    })
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", default="RQ-20261119-ef40-02")
    ap.add_argument("--out-dir")
    ap.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT))
    ap.add_argument("--rebuilt-template", default=DEFAULT_REBUILT,
                    help="repo-relative path with {sym}; a10d-01 wrote it under its --root")
    ap.add_argument("--symbols", default="BTCUSDT,SOLUSDT")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.out_dir:
        ap.error('--out-dir is required')
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    heads: Dict[str, Dict[str, Any]] = {}
    for sym in [s.strip() for s in a.symbols.split(",") if s.strip()]:
        try:
            m = diff_symbol(sym, REPO / a.rebuilt_template.format(sym=sym), Path(a.snapshot_dir) / f"{sym}.jsonl")
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded per head -> INDETERMINATE
            m = {"symbol": sym, "read_state": "producer_failed", "error": f"{type(e).__name__}: {e}"}
        m["verdict"], m["reason"] = grade(m)
        heads[sym] = m
    vs = [h["verdict"] for h in heads.values()]
    unit_v = ("RESIDUAL" if "RESIDUAL" in vs else "LAG_EXPLAINS" if vs and all(v == "LAG_EXPLAINS" for v in vs)
              else "INDETERMINATE")
    rs = "measured" if all(h.get("read_state") == "measured" for h in heads.values()) else (
        "could_not_look" if any(h.get("read_state") == "could_not_look" for h in heads.values()) else "producer_failed")
    verdict = {"unit": a.unit, "rule_id": RULE_ID, "verdict": unit_v.lower(), "verdict_label": unit_v,
               "read_state": rs, "heads": heads,
               "data_inputs": [a.rebuilt_template, str(Path(a.snapshot_dir).relative_to(REPO))
                               if Path(a.snapshot_dir).is_relative_to(REPO) else a.snapshot_dir],
               "generated_at": datetime.now(timezone.utc).isoformat()}
    (out / "measurement.json").write_text(json.dumps(heads, indent=2, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n")
    print(json.dumps({"verdict": unit_v, "read_state": rs,
                      "heads": {s: (h["verdict"], h.get("class_share")) for s, h in heads.items()}}))
    return 0


def _self_test() -> int:
    base = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
    reps = {}
    for i in range(-3, 4):
        reps[_key(base + timedelta(seconds=TF_S * i))] = {c: 0.001 * (i + 10) + j * 0.1 for j, c in enumerate(FC_COLS)}
    own_fc = dict(reps[_key(base)])
    lag_fc = dict(reps[_key(base - timedelta(seconds=TF_S))])
    near_fc = {c: v * (1 + 5e-4) for c, v in own_fc.items()}
    far_fc = {c: v * 3 for c, v in own_fc.items()}
    assert classify(own_fc, base, reps)["cls"] == "exact_k0"
    assert classify(lag_fc, base, reps)["cls"] == "exact_k-1"
    assert classify(near_fc, base, reps)["cls"] == "near_only"
    assert classify(far_fc, base, reps)["cls"] == "none"
    m = {"read_state": "measured", "n_matched": 1000, "class_share": {"exact_k0": 0.55, "exact_k-1": 0.44, "none": 0.01}}
    assert grade(m)[0] == "LAG_EXPLAINS", grade(m)
    m = {"read_state": "measured", "n_matched": 1000, "class_share": {"exact_k0": 0.55, "exact_k-1": 0.40, "none": 0.05}}
    assert grade(m)[0] == "RESIDUAL"
    assert grade({"read_state": "measured", "n_matched": 150, "class_share": {}})[0] == "INDETERMINATE"
    assert grade({"read_state": "could_not_look"})[0] == "INDETERMINATE"
    print("self-test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
