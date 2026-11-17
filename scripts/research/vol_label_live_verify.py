#!/usr/bin/env python3
"""Verify replayed ML vol labels against the LIVE gate's own labels, per head (row ML-VOL-LABEL-LIVE-VERIFY).

``ml_vol_label_replay.py replay`` reproduces the live ML vol axis offline from the
trainer's built ``market_features`` dataset. Every D2 consumer test that grades a
(trend, vol) cell on those labels (bcd2-01, b819-01, the blocked 0f87-01) carries
the caveat "labels NOT verified against the live gate". This harness closes it:

1. replay each head on the trainer (``run_replay``; a failure is recorded for that
   head and the next head still runs: one missing dataset is not every head's FAIL);
2. match the live ``regime_ml_vol_shadow`` audit rows of THAT head (filtered on
   ``model_id``; a symbol's rows from an earlier head are a different label) to a
   replayed bar under two pre-declared alignments:
     * ``asof``     -- the bar at/just before the audit stamp (``_bar_key``; what the
                       downstream harnesses use today),
     * ``prev_bar`` -- one bar earlier (the last CLOSED bar at the audit stamp);
3. de-duplicate to one comparison per (bar) (several strategies log the same bar);
4. grade each head on the rule registered in the calling unit (thresholds are the
   CLI defaults below and are echoed into the verdict).

Why kappa and not agreement alone: BTC's head labels ~7.5% of bars volatile, so an
always-calm replay would "agree" ~92%. Cohen's kappa is chance-corrected.

Research only (Tier 1). Reads the trainer registry + datasets and a committed audit
snapshot; writes labels + verdict.json under --out-dir. Never touches config or
live state.

Usage (the unit's run block)::

    python3 scripts/research/vol_label_live_verify.py \
        --head BTCUSDT:btc-regime-15m-lgbm-fc-pcv-v2:datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl:comms/live_parity/vol_label_audit_20261117/BTCUSDT.jsonl \
        --head ETHUSDT:eth-regime-1h-lgbm-xasset-v1:datasets-out/market_features/ETHUSDT/1h/v002/data.jsonl \
        --primary BTCUSDT --out-dir {out_dir}

    python3 scripts/research/vol_label_live_verify.py --self-test
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent))

CALM, VOLATILE = "calm", "volatile"
ALIGNMENTS = ("asof", "prev_bar")

DEFAULTS = {
    "min_bars": 100,          # distinct comparable bars; below -> INDETERMINATE
    "min_agreement": 0.90,
    "min_kappa": 0.60,
    "max_median_dp": 0.10,    # median |live p_volatile - replayed p_volatile|
}


# ── matching ─────────────────────────────────────────────────────────────────
def _vr():
    import ml_vol_label_replay as vr  # noqa: WPS433 (lazy: the replay pulls the registry stack)
    return vr


def match(labels: Dict[str, Dict[str, Any]], audit: Sequence[Dict[str, Any]], model_id: Optional[str],
          alignment: str) -> Dict[str, Any]:
    """Pair each live-labelled audit row of ``model_id`` with a replayed bar; one pair per bar."""
    vr = _vr()
    keys = sorted(labels)
    bar_s = vr._infer_bar_seconds(keys) or vr._DEFAULT_BAR_SECONDS
    max_stale = 2.0 * bar_s
    end = vr._parse_ts(keys[-1]) if keys else None
    counts = {"audit_rows": 0, "other_model": 0, "no_live_label": 0, "no_bar": 0,
              "after_labels_end": 0, "stale": 0, "replayed_unknown": 0, "matched_rows": 0}
    by_bar: Dict[str, Tuple[str, str, Optional[float], Optional[float]]] = {}
    conflicts = 0
    for rec in audit:
        counts["audit_rows"] += 1
        if model_id and rec.get("model_id") != model_id:
            counts["other_model"] += 1
            continue
        live = rec.get("vol_regime_ml")
        if live not in (CALM, VOLATILE):
            counts["no_live_label"] += 1
            continue
        dt = vr._parse_ts(rec.get("logged_at_utc") or rec.get("ts"))
        if dt is None:
            counts["no_bar"] += 1
            continue
        if end is not None and dt > end + timedelta(seconds=max_stale):
            counts["after_labels_end"] += 1
            continue
        probe = dt if alignment == "asof" else dt - timedelta(seconds=bar_s)
        bar = vr._bar_key(probe.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"), keys)
        if bar is None:
            counts["no_bar"] += 1
            continue
        bdt = vr._parse_ts(bar)
        if bdt is None or (probe - bdt).total_seconds() > max_stale:
            counts["stale"] += 1
            continue
        mine = labels[bar].get("vol_regime")
        if mine not in (CALM, VOLATILE):
            counts["replayed_unknown"] += 1
            continue
        counts["matched_rows"] += 1
        lp = rec.get("p_volatile")
        mp = labels[bar].get("p_volatile")
        if bar in by_bar and by_bar[bar][0] != live:
            conflicts += 1  # the live gate gave one bar two labels (cache refresh mid-bar)
        by_bar.setdefault(bar, (live, mine, lp, mp))
    pairs = list(by_bar.values())
    return {"alignment": alignment, "bar_seconds": bar_s, "counts": counts,
            "live_label_conflicts_within_bar": conflicts, **score(pairs)}


def score(pairs: Sequence[Tuple[str, str, Optional[float], Optional[float]]]) -> Dict[str, Any]:
    n = len(pairs)
    if not n:
        return {"bars": 0, "agreement": None, "kappa": None, "median_dp": None}
    tp = sum(1 for live, mine, *_ in pairs if live == VOLATILE and mine == VOLATILE)
    tn = sum(1 for live, mine, *_ in pairs if live == CALM and mine == CALM)
    fp = sum(1 for live, mine, *_ in pairs if live == CALM and mine == VOLATILE)
    fn = sum(1 for live, mine, *_ in pairs if live == VOLATILE and mine == CALM)
    po = (tp + tn) / n
    live_v, mine_v = (tp + fn) / n, (tp + fp) / n
    pe = live_v * mine_v + (1 - live_v) * (1 - mine_v)
    kappa = None if pe >= 1.0 else (po - pe) / (1 - pe)
    dps = [abs(float(lp) - float(mp)) for *_, lp, mp in pairs if lp is not None and mp is not None]
    return {
        "bars": n, "confusion": {"live_vol_replay_vol": tp, "live_calm_replay_calm": tn,
                                 "live_calm_replay_vol": fp, "live_vol_replay_calm": fn},
        "live_volatile_share": round(live_v, 4), "replay_volatile_share": round(mine_v, 4),
        "agreement": round(po, 4), "kappa": None if kappa is None else round(kappa, 4),
        "median_dp": round(statistics.median(dps), 6) if dps else None,
        "p90_dp": round(sorted(dps)[min(len(dps) - 1, int(0.9 * len(dps)))], 6) if dps else None,
        "dp_n": len(dps),
    }


def grade(m: Dict[str, Any], th: Dict[str, float]) -> str:
    if not m.get("bars") or m["bars"] < th["min_bars"]:
        return "indeterminate"
    ok = (m["agreement"] is not None and m["agreement"] >= th["min_agreement"]
          and m["kappa"] is not None and m["kappa"] >= th["min_kappa"]
          and m["median_dp"] is not None and m["median_dp"] <= th["max_median_dp"])
    return "pass" if ok else "fail"


def grade_head(per_alignment: Dict[str, Dict[str, Any]], th: Dict[str, float]) -> Tuple[str, Optional[str]]:
    """PASS iff either declared alignment passes (that alignment is the one consumers must use);
    FAIL iff any alignment has >= min_bars and none passes; else INDETERMINATE."""
    grades = {a: grade(m, th) for a, m in per_alignment.items()}
    passing = [a for a in ALIGNMENTS if grades.get(a) == "pass"]
    if passing:
        best = max(passing, key=lambda a: per_alignment[a]["kappa"])
        return "pass", best
    if any(g == "fail" for g in grades.values()):
        return "fail", None
    return "indeterminate", None


# ── driver ───────────────────────────────────────────────────────────────────
def parse_head(spec: str) -> Dict[str, Optional[str]]:
    parts = spec.split(":")
    if len(parts) not in (3, 4):
        raise SystemExit(f"--head wants SYMBOL:MODEL_ID:DATASET[:AUDIT], got {spec!r}")
    return {"symbol": parts[0], "model_id": parts[1], "dataset": parts[2],
            "audit": parts[3] if len(parts) == 4 else None}


def run_head(h: Dict[str, Optional[str]], out_dir: Path, th: Dict[str, float],
             replay_fn=None, labels_loader=None) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"symbol": h["symbol"], "model_id": h["model_id"], "dataset": h["dataset"],
                           "audit": h["audit"]}
    out = out_dir / f"{h['symbol']}_labels.jsonl"
    try:
        replay = replay_fn or _vr().run_replay
        man = replay(dataset=Path(h["dataset"]), symbol=h["symbol"], out_path=out, model_id=h["model_id"])
        rec["replay"] = {k: man.get(k) for k in ("labelled", "counts", "volatile_pct", "ts_first", "ts_last",
                                                 "threshold", "head")}
        rec["replay"]["feature_audit_ok"] = (man.get("feature_audit") or {}).get("ok")
    except Exception as exc:  # noqa: BLE001  # allow-silent: per-head containment; the failure is recorded as producer_failed with its traceback in verdict.json, never a pass
        rec.update(verdict="not_applicable", read_state="producer_failed",
                   note=f"replay failed: {type(exc).__name__}: {exc}",
                   traceback=traceback.format_exc()[-2000:])
        return rec
    if not h["audit"]:
        # read_state no_data: there is no live label to verify against, so nothing was measured. research_result.py --emit
        # refuses measured + not_applicable and measured without an integer n (RQ-20261117-aadc-01 run 44080314119 was LOST on
        # this record, the replay-only ETH head). The replay counts stay in measurement.heads.
        rec.update(verdict="not_applicable", read_state="no_data", n=None,
                   note="replay only: no live labelled audit rows exist for this head (shadow stage), so nothing to verify against")
        return rec
    labels = (labels_loader or _vr().load_labels)(out)
    audit = [json.loads(line) for line in Path(h["audit"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    per = {a: match(labels, audit, h["model_id"], a) for a in ALIGNMENTS}
    verdict, alignment = grade_head(per, th)
    rec.update(verdict=verdict, read_state="measured", alignment_used=alignment, alignments=per,
               n=max(per[a]["bars"] for a in ALIGNMENTS))
    return rec


def record_n(r: Dict[str, Any]) -> Optional[int]:
    """A measured record always carries an integer n (the emitter refuses null); a producer_failed one carries None."""
    if r.get("read_state", "measured") != "measured":
        return None
    return int(r.get("n") or 0)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--head", action="append", default=[])
    ap.add_argument("--primary", help="symbol whose head decides the unit verdict")
    ap.add_argument("--out-dir")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.head or not a.out_dir or not a.primary:
        ap.error("--head, --primary and --out-dir are required")
    th = {k: getattr(a, k) for k in DEFAULTS}
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = [run_head(parse_head(s), out_dir, th) for s in a.head]
    prim = next((r for r in records if r["symbol"] == a.primary), None)
    top = prim["verdict"] if prim else "not_applicable"
    rs = prim.get("read_state", "producer_failed") if prim else "producer_failed"
    summary = "; ".join(
        f"{r['symbol']} {r['model_id']}: {r['verdict']}"
        + (f" (bars {r.get('n')}, alignment {r.get('alignment_used')})" if r.get("alignments") else "")
        for r in records)
    verdict = {
        "verdict": top, "read_state": rs, "n": prim.get("n") if prim else None,
        "population": ("distinct bars where the live regime_ml_vol_shadow row of the head's own model_id "
                       "carried a calm/volatile label and matched a replayed bar within 2 bars; primary "
                       f"{a.primary}"),
        "note": summary,
        "thresholds": th,
        "measurement": {"heads": records, "thresholds": th},
        "records": [{"verdict": r["verdict"], "read_state": r.get("read_state", "measured"),
                     "population": f"{r['symbol']} {r['model_id']} live-vs-replay bars",
                     "n": record_n(r), "note": r.get("note") or f"alignment {r.get('alignment_used')}",
                     "symbol": r["symbol"], "model_id": r["model_id"]} for r in records],
        "data_inputs": [r["audit"] for r in records if r.get("audit")],
    }
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": top, "summary": summary}, indent=1))
    return 0


# ── self-test ────────────────────────────────────────────────────────────────
def _self_test() -> int:
    import tempfile

    th = dict(DEFAULTS)
    # synthetic 15m labels over 300 bars, 20% volatile; live rows logged 7 min into bar k+1 and
    # labelled from bar k (the last closed bar) -> prev_bar must pass, asof must not.
    from datetime import datetime, timezone
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    labels = {}
    for i in range(300):
        ts = (t0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        vol = VOLATILE if (i * 7) % 5 == 0 else CALM
        labels[ts] = {"ts": ts, "vol_regime": vol, "p_volatile": 0.9 if vol == VOLATILE else 0.1}
    keys = sorted(labels)
    audit = []
    for i in range(1, 300):
        prev = labels[keys[i - 1]]
        at = t0 + timedelta(minutes=15 * i + 7)
        for strat in ("a", "b"):  # duplicate per bar -> de-duplicated
            audit.append({"logged_at_utc": at.isoformat(), "model_id": "m", "vol_regime_ml": prev["vol_regime"],
                          "p_volatile": prev["p_volatile"]})
    audit.append({"logged_at_utc": (t0 + timedelta(minutes=20)).isoformat(), "model_id": "other",
                  "vol_regime_ml": VOLATILE, "p_volatile": 0.99})
    per = {a: match(labels, audit, "m", a) for a in ALIGNMENTS}
    assert per["prev_bar"]["bars"] == 299 and per["prev_bar"]["agreement"] == 1.0, per["prev_bar"]
    assert per["prev_bar"]["counts"]["other_model"] == 1
    assert per["asof"]["kappa"] < 0.6, per["asof"]
    v, al = grade_head(per, th)
    assert (v, al) == ("pass", "prev_bar"), (v, al)
    # always-calm replay must FAIL on kappa even with high raw agreement
    calm = {k: {**r, "vol_regime": CALM, "p_volatile": 0.1} for k, r in labels.items()}
    m = match(calm, audit, "m", "prev_bar")
    assert m["agreement"] >= 0.75 and m["kappa"] == 0.0 and grade(m, th) == "fail", m
    # too few bars -> indeterminate
    assert grade({"bars": 23, "agreement": 1.0, "kappa": 1.0, "median_dp": 0.0}, th) == "indeterminate"
    # a replay failure is contained per head
    with tempfile.TemporaryDirectory() as td:
        def boom(**_):
            raise FileNotFoundError("no dataset")
        r = run_head({"symbol": "X", "model_id": "m", "dataset": "nope", "audit": None}, Path(td), th, replay_fn=boom)
        assert r["read_state"] == "producer_failed" and "no dataset" in r["note"], r
        # end to end with a stub replay
        aud = Path(td) / "aud.jsonl"
        aud.write_text("\n".join(json.dumps(x) for x in audit) + "\n")

        def stub(dataset, symbol, out_path, model_id):
            assert (str(dataset), symbol, model_id) == ("d", "X", "m")
            out_path.write_text("\n".join(json.dumps(r) for r in labels.values()) + "\n")
            return {"labelled": 300, "counts": {}, "feature_audit": {"ok": True}}
        r = run_head({"symbol": "X", "model_id": "m", "dataset": "d", "audit": str(aud)}, Path(td), th, replay_fn=stub)
        assert r["verdict"] == "pass" and r["alignment_used"] == "prev_bar", r
    # every measured record carries an integer n (the replay-only head included); producer_failed carries None
    with tempfile.TemporaryDirectory() as td:
        def stub2(dataset, symbol, out_path, model_id):
            assert (str(dataset), symbol, model_id) == ("d2", "E", "e")
            out_path.write_text(json.dumps({"ts": "2026-01-01T00:00:00Z", "vol_regime": CALM, "p_volatile": 0.1}) + "\n")
            return {"labelled": 1234, "counts": {}, "feature_audit": {"ok": True}}
        ro = run_head({"symbol": "E", "model_id": "e", "dataset": "d2", "audit": None}, Path(td), th, replay_fn=stub2)
        assert ro["read_state"] == "no_data" and ro["verdict"] == "not_applicable" and record_n(ro) is None, ro
        assert ro["replay"]["labelled"] == 1234
        assert record_n({"read_state": "producer_failed"}) is None
        assert isinstance(record_n({"read_state": "measured", "n": None}), int)
    print("vol_label_live_verify self-test: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
