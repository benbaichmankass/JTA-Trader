#!/usr/bin/env python3
"""D2 SERVE-PATH DIFF: why do the trainer-replayed vol labels not reproduce the live gate's?
(PI-20261118-ZZUFKM1F-0001, the fail_action of RQ-20261117-aadc-01; unit RQ-20261118-04a5-03)

aadc-01 FAILED: BTC fc-pcv-v2 kappa 0.24 (n 1,111), SOL kappa 0.51 (n 676), both better at prev_bar. It compared the
replayed label against the signal-audit p_volatile, which logs NO feature row, so it could not say WHY.

The live per-bar scorer (src/runtime/regime_bar_scoring.py) logs every score with its full feature row to
runtime_logs/shadow_predictions.jsonl (ml/predictors/shadow.py). This producer takes a committed snapshot of those rows
(comms/live_parity/vol_serve_rows_20261118/<SYMBOL>.jsonl) and, per live bar:

1. matches the trainer's market_features v002 row for the same closed bar (bar open = floor(predicted_at, tf) - tf;
   checked on hour_of_day / dayofweek / log_return; the +-1-bar neighbours are tried and the offset is reported);
2. scores BOTH rows with the head's own predictor (P(volatile) via predict_proba, vol_bucket recomputed live-faithfully
   from the head's frozen edges, exactly as ml_vol_label_replay.run_replay does);
3. diffs every feature column and attributes the p delta by BLOCK: each block of the live row is replaced by the replay
   row's values alone, and the swap's p change and label flips are recorded.

Registered rule (RULE-RQ20261118-04a5-03-VOL-SERVE-DIFF), per head, over matched bars:
  INDETERMINATE  if matched bars < 200, or the head/dataset cannot be loaded;
  NO_ACTION      (verdict no_action_warranted) if live and replay labels agree on >= 98% of matched bars AND kappa >= 0.8
                 at offset 0: the feature path is clean on this window, so aadc-01's disagreement is in the signal-audit
                 alignment (offset) or outside this window - reported with the offset table;
  PASS (named)   if some single block's swap alone reproduces >= 80% of the label disagreements: that block is the cause;
  FAIL (unnamed) otherwise: disagreements exist and no single block explains 80% (an interaction, reported).
Top-level: the worst of the heads in the order FAIL > INDETERMINATE > PASS > NO_ACTION.

Tier-1 research tooling: reads committed snapshots + trainer datasets/registry; writes only --json and --out-dir.
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

RULE_ID = "RULE-RQ20261118-04a5-03-VOL-SERVE-DIFF"
MIN_MATCHED = 200
AGREE_CLEAN, KAPPA_CLEAN, BLOCK_SHARE = 0.98, 0.8, 0.80
TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def block_of(col: str) -> str:
    if col.startswith("fc_"):
        return "forecast_fc"
    if col.startswith("xa_"):
        return "cross_asset_xa"
    if col.endswith("_vol"):
        return "vol_estimators"
    if col.startswith("log_return"):
        return "returns"
    if col in ("hour_of_day", "dayofweek"):
        return "calendar"
    if col == "vol_bucket":
        return "vol_bucket"
    return "other"


def kappa(a: List[str], b: List[str]) -> Optional[float]:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return None if pe >= 1.0 else round((po - pe) / (1 - pe), 4)


def bar_open(predicted_at: str, tf: str, offset: int = 0) -> datetime:
    t = datetime.fromisoformat(predicted_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    s = TF_SECONDS[tf]
    floor = datetime.fromtimestamp(int(t.timestamp()) // s * s, tz=timezone.utc)
    return floor - timedelta(seconds=s * (1 - offset))


def _ts_key(v: Any) -> Optional[str]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def same_bar(live: Mapping[str, Any], rep: Mapping[str, Any]) -> bool:
    """A replay row is the live bar iff calendar fields agree and log_return agrees to 1e-6 (relative-or-absolute)."""
    for k in ("hour_of_day", "dayofweek"):
        if k in live and k in rep and rep[k] is not None and int(live[k]) != int(rep[k]):
            return False
    a, b = live.get("log_return"), rep.get("log_return")
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= 1e-6 + 1e-4 * abs(float(a))


def grade_head(m: Dict[str, Any]) -> tuple[str, str]:
    n = m.get("n_matched", 0)
    if n < MIN_MATCHED:
        return "INDETERMINATE", f"matched bars {n} < {MIN_MATCHED}"
    agree, k = m["agreement"], m["kappa"]
    if agree >= AGREE_CLEAN and (k is None or k >= KAPPA_CLEAN):
        return "NO_ACTION", f"feature path clean on this window: agreement {agree:.3f}, kappa {k}"
    nd = m["n_disagree"]
    best = max(m["blocks"].items(), key=lambda kv: kv[1]["flips_reproduced"], default=(None, {"flips_reproduced": 0}))
    share = best[1]["flips_reproduced"] / nd if nd else 0.0
    if best[0] and share >= BLOCK_SHARE:
        return "PASS", f"block {best[0]} alone reproduces {share:.0%} of {nd} label disagreements"
    return "FAIL", f"no single block explains >= {BLOCK_SHARE:.0%} of {nd} disagreements (best {best[0]} {share:.0%})"


def roll_up(vs: List[str]) -> str:
    for v in ("FAIL", "INDETERMINATE", "PASS", "NO_ACTION"):
        if v in vs:
            return v
    return "INDETERMINATE"


def diff_head(symbol: str, model_id: str, dataset: Path, live_path: Path, tf: str, registry_root: Optional[str]) -> Dict[str, Any]:
    import ml_vol_label_replay as R
    head = R.resolve_advisory_head(symbol, model_id=model_id, registry_root=registry_root)
    base = R._unwrap(head["predictor"])
    spec = getattr(base, "regime_spec", None) or {}
    cols = list(getattr(base, "_feature_columns", []) or [])
    cats = set(getattr(base, "_categorical_columns", []) or [])
    tau = R.live_threshold()
    bucket_col = str(spec.get("feature_column") or "vol_bucket")
    proba = getattr(base, "predict_proba")

    def p_of(row: Mapping[str, Any]) -> Optional[float]:
        return R._p_from_proba(proba, row)

    live = [json.loads(x) for x in live_path.read_text().splitlines() if x.strip()]
    live = [r for r in live if r.get("model_id") in (None, model_id) and r.get("feature_row")]
    want = set()
    for r in live:
        for off in (-1, 0, 1):
            want.add(bar_open(r["predicted_at_utc"], tf, off).strftime("%Y-%m-%dT%H:%M"))
    keep = list(set(cols) | {str(spec.get("vol_feature_column") or "rolling_log_return_vol"), "log_return",
                             "hour_of_day", "dayofweek"})
    rep_by_ts: Dict[str, Dict[str, Any]] = {}
    for row in R.iter_projected_rows(dataset, keep):
        k = _ts_key(row.get("ts"))
        if k in want:
            rep_by_ts[k] = row
    ds_last = None
    matched, offsets, unmatched = [], Counter(), 0
    for r in live:
        fr = r["feature_row"]
        hit = None
        for off in (0, -1, 1):
            k = bar_open(r["predicted_at_utc"], tf, off).strftime("%Y-%m-%dT%H:%M")
            rep = rep_by_ts.get(k)
            if rep is not None and same_bar(fr, rep):
                hit = (off, k, rep)
                break
        if hit is None:
            unmatched += 1
            continue
        off, k, rep = hit
        offsets[off] += 1
        rep = dict(rep)
        lb = R.live_vol_bucket(rep, spec)
        if lb is not None:
            rep[bucket_col] = lb
        matched.append((k, fr, rep, r.get("score")))
    if rep_by_ts:
        ds_last = max(rep_by_ts)
    res: Dict[str, Any] = {"symbol": symbol, "model_id": model_id, "threshold": tau, "n_live": len(live),
                           "n_matched": len(matched), "n_unmatched": unmatched, "match_offsets": dict(offsets),
                           "dataset": str(dataset), "dataset_last_matched_bar": ds_last, "feature_columns": cols}
    if not matched:
        return res
    lab_l, lab_r, score_vs_p, col_diff = [], [], [], {c: [] for c in cols}
    blocks: Dict[str, Dict[str, Any]] = {}
    cols_by_block: Dict[str, List[str]] = {}
    for c in cols:
        cols_by_block.setdefault(block_of(c), []).append(c)
    for b in cols_by_block:
        blocks[b] = {"columns": cols_by_block[b], "flips_reproduced": 0, "mean_abs_dp": 0.0, "n": 0}
    disagree_rows = []
    for k, fr, rep, score in matched:
        pl, pr = p_of(fr), p_of(rep)
        if pl is None or pr is None:
            continue
        ll, lr = ("volatile" if pl >= tau else "calm"), ("volatile" if pr >= tau else "calm")
        lab_l.append(ll)
        lab_r.append(lr)
        if isinstance(score, (int, float)):
            score_vs_p.append((float(score), pl))
        for c in cols:
            a, b = fr.get(c), rep.get(c)
            if c in cats:
                col_diff[c].append(0.0 if str(a) == str(b) else 1.0)
            elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not (math.isnan(a) or math.isnan(b)):
                col_diff[c].append(abs(float(a) - float(b)) / (abs(float(b)) + 1e-12))
            else:
                col_diff[c].append(float("nan") if (a is None) != (b is None) else 0.0)
        for bname, bcols in cols_by_block.items():
            sw = dict(fr)
            for c in bcols:
                sw[c] = rep.get(c)
            ps = p_of(sw)
            if ps is None:
                continue
            blocks[bname]["n"] += 1
            blocks[bname]["mean_abs_dp"] += abs(ps - pl)
            if ll != lr and (("volatile" if ps >= tau else "calm") == lr):
                blocks[bname]["flips_reproduced"] += 1
        if ll != lr and len(disagree_rows) < 25:
            disagree_rows.append({"bar": k, "p_live": round(pl, 4), "p_replay": round(pr, 4),
                                  "diffs": {c: [fr.get(c), rep.get(c)] for c in cols if fr.get(c) != rep.get(c)}})
    for b in blocks.values():
        b["mean_abs_dp"] = round(b["mean_abs_dp"] / b["n"], 5) if b["n"] else None
    n = len(lab_l)
    res.update({"n_scored": n, "agreement": round(sum(a == b for a, b in zip(lab_l, lab_r)) / n, 4) if n else None,
                "kappa": kappa(lab_l, lab_r), "n_disagree": sum(a != b for a, b in zip(lab_l, lab_r)),
                "share_volatile_live": round(lab_l.count("volatile") / n, 4) if n else None,
                "share_volatile_replay": round(lab_r.count("volatile") / n, 4) if n else None,
                "logged_score_vs_recomputed_p": {
                    "n": len(score_vs_p),
                    "max_abs_score_minus_p": round(max((abs(s - p) for s, p in score_vs_p), default=float("nan")), 6),
                    "max_abs_score_minus_1mp": round(max((abs(s - (1 - p)) for s, p in score_vs_p), default=float("nan")), 6)},
                "column_rel_diff_median": {c: (round(sorted(v)[len(v) // 2], 6) if v else None) for c, v in col_diff.items()},
                "column_share_differing_1e-3": {c: round(sum(x > 1e-3 for x in v if not math.isnan(x)) / len(v), 4) if v else None
                                                for c, v in col_diff.items()},
                "blocks": blocks, "disagreeing_examples": disagree_rows})
    return res


def verdict_row(heads: Dict[str, Dict[str, Any]], unit: str) -> dict:
    vs = []
    for h in heads.values():
        if "error" in h:
            h["verdict"], h["reason"] = "INDETERMINATE", f"producer error: {h['error'][:200]}"
        else:
            h["verdict"], h["reason"] = grade_head(h)
        vs.append(h["verdict"])
    top = roll_up(vs)
    measured = any(h.get("n_matched", 0) > 0 for h in heads.values())
    vmap = {"PASS": "pass", "FAIL": "fail", "INDETERMINATE": "indeterminate", "NO_ACTION": "no_action_warranted"}
    return {"schema_version": 1, "research_unit": unit, "rule_id": RULE_ID, "verdict": vmap[top],
            "read_state": "measured" if measured else "producer_failed",
            "note": f"{top}: " + "; ".join(f"{s} {h['verdict']} ({h['reason']})" for s, h in heads.items()),
            "population": "live per-bar shadow_predictions feature rows (snapshot comms/live_parity/vol_serve_rows_20261118, "
                          "2026-11-09..2026-11-18) matched bar-for-bar to trainer market_features v002 rows, heads "
                          + ", ".join(f"{s}:{h.get('model_id')}" for s, h in heads.items()),
            "n": int(sum(h.get("n_scored", 0) or 0 for h in heads.values())),
            "measurement": {"heads": heads, "generated_at": datetime.now(timezone.utc).isoformat()}}


def _self_test() -> int:
    ok = True

    def check(msg, cond):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    check("bar_open: 19:08 on 15m is the 18:45 bar", bar_open("2026-11-18T19:08:21+00:00", "15m").strftime("%H:%M") == "18:45")
    check("bar_open: offset -1 is one bar earlier", bar_open("2026-11-18T19:08:21+00:00", "15m", -1).strftime("%H:%M") == "18:30")
    check("block_of fc/vol/returns/calendar/bucket",
          [block_of(c) for c in ("fc_skew", "parkinson_vol", "log_return_lag_1", "hour_of_day", "vol_bucket")]
          == ["forecast_fc", "vol_estimators", "returns", "calendar", "vol_bucket"])
    check("kappa: identical labels = 1", kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0)
    check("same_bar: log_return within tolerance", same_bar({"log_return": 0.001, "hour_of_day": 3}, {"log_return": 0.0010000001, "hour_of_day": 3}))
    check("same_bar: different hour rejected", not same_bar({"log_return": 0.001, "hour_of_day": 3}, {"log_return": 0.001, "hour_of_day": 4}))
    base = {"n_matched": 500, "agreement": 0.9, "kappa": 0.4, "n_disagree": 50}
    check("grade: thin is INDETERMINATE", grade_head({"n_matched": 10})[0] == "INDETERMINATE")
    check("grade: clean is NO_ACTION", grade_head({"n_matched": 500, "agreement": 0.99, "kappa": 0.9, "n_disagree": 5, "blocks": {}})[0] == "NO_ACTION")
    check("grade: one block explains 90% is PASS",
          grade_head(dict(base, blocks={"forecast_fc": {"flips_reproduced": 45}, "returns": {"flips_reproduced": 3}}))[0] == "PASS")
    check("grade: spread is FAIL",
          grade_head(dict(base, blocks={"forecast_fc": {"flips_reproduced": 20}, "returns": {"flips_reproduced": 20}}))[0] == "FAIL")
    check("roll_up order", roll_up(["NO_ACTION", "PASS"]) == "PASS" and roll_up(["PASS", "FAIL"]) == "FAIL")
    import script_run as SR
    row = verdict_row({"BTCUSDT": dict(base, model_id="m", n_scored=500,
                                       blocks={"forecast_fc": {"flips_reproduced": 45}})}, "U")
    check("verdict row vocabularies", row["verdict"] in SR.VERDICTS and row["read_state"] in SR.READ_STATES and row["n"] == 500)
    bad = verdict_row({"X": {"error": "no dataset"}}, "U")
    check("nothing matched is producer_failed", bad["read_state"] == "producer_failed")
    print("vol_serve_path_diff self-test " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--head", action="append", default=[],
                    help="SYMBOL:MODEL_ID:DATASET_JSONL:LIVE_SNAPSHOT_JSONL[:TF] (TF default 15m)")
    ap.add_argument("--registry-root", default=None)
    ap.add_argument("--unit", default="RQ-20261118-04a5-03")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    heads: Dict[str, Dict[str, Any]] = {}
    for spec in a.head:
        parts = spec.split(":")
        sym, mid, ds, lv = parts[:4]
        tf = parts[4] if len(parts) > 4 else "15m"
        try:
            heads[sym] = diff_head(sym, mid, Path(ds), Path(lv), tf, a.registry_root)
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded per head as producer error -> INDETERMINATE
            heads[sym] = {"model_id": mid, "error": f"{type(e).__name__}: {e}"}
        print(sym, json.dumps({k: heads[sym].get(k) for k in ("n_matched", "agreement", "kappa", "n_disagree", "error")}), flush=True)
    row = verdict_row(heads, a.unit)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(row["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
