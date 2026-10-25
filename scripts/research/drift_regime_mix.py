#!/usr/bin/env python3
# wiring: research/queue units declaring run.command ["python3","scripts/research/drift_regime_mix.py",...]
#         via the research-queue dispatcher (compute: needs_vm_data -> research-script-run-trainer.yml); the shadow log is trainer-resident
"""Is a head's persistent score drift an INSTRUMENT artifact, an input-mix shift, or model decay? (ML-DRIFT-SPLIT-INSTRUMENT)

WHY (lane ML-HEALTH-BUILDS-1027, 2026-10-25). `ml stage-guard` proposes a demote on drift `significant` and the hourly
`ict-drift-retrain` scan flags the same 9 heads on every pass, while the drift-remediation skill says to separate
transient / mix drift from capability loss BEFORE demoting. Nothing in the repo computed that split, so each review
re-argued it. Two blocked units wait on this one script: RQ-20261011-6e85-01 (`--mode split`) and RQ-20261016-65ff-27
(`--mode by-version`).

MODES
  --mode split        per head, reference vs current window: volatile_label_share, AUC of the SERVED score against the
                      realised forward-vol label, delta_share / delta_auc, plus the API's own KS/PSI over the same two
                      score sets (`ml.shadow.drift.compute_drift`, so a run can be checked against
                      GET /api/bot/shadow/drift). Verdict per head by RULE-RQ1011-6E85-DRIFT-SPLIT (thresholds are flags).
  --mode by-version   per head, ADWIN (`ml.shadow.adwin.scan_stream`, the scan's own detector) on (a) every score in the
                      scan window, (b) only scores from the NEWEST model version, (c) the newest version re-sampled to
                      the head's longer-run symbol x session mix. Verdict per head ARTIFACT / MIX / DECAY /
                      INDETERMINATE and a unit verdict by RULE-RQ2026101665ff27-DRIFT-ARTIFACT.

HONEST LIMITS, STATED IN THE RECORD (read these before trusting a verdict)
  * The shadow log carries NO model-version field (`ml/predictors/shadow.py` writes model_id/stage/score/row_keys/
    feature_row). A "version" here is a registry RunRecord (`ModelRegistry` appends one per retrain under a stable
    model_id); a row belongs to the latest run whose `at` <= its timestamp. That assumes the live loader picks up a
    retrain at registration time -- an ASSUMPTION, recorded as `version_assignment`.
  * For a multiclass regime head the served `score` is max(class probability) (`scripts/ml/_regime_score_semantics.py`),
    not P(volatile). The AUC the 6e85-01 rule asks for is the AUC of THAT served score vs the volatile label, so it
    measures the head's confidence-vs-label relation, not its volatile ranking. Reported as `score_semantics`.
  * (c) re-weights to the head's own longer-run mix because the TRAINING window's mix is not stored with the log.
    Where that reference has < --min-mix-ref rows, (c) is unavailable and a head that needs it reads INDETERMINATE.
  * "Flagged" for (a)/(b)/(c) = ADWIN found at least one cut in the stream (`scan_stream.drift_detected`); the age of
    the latest cut is reported beside it (the scan dispatches only when that cut is within 3 days).

Read-only; never retrains, demotes, promotes or edits a stage, timer or config. Tier-1 research code.
Writes `<out>/verdict.json` in the shape script_run.py --derive-record consumes ({verdict, read_state, population, n,
measurement, note}); the rule's own labels ride in `measurement.rule_verdict`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ml.shadow.adwin import scan_stream  # noqa: E402
from ml.shadow.drift import compute_drift  # noqa: E402
from ml.shadow.inspector import iter_records_with_archives  # noqa: E402

# Thresholds are the registered ones (RULE-RQ1011-6E85-DRIFT-SPLIT / RULE-RQ2026101665ff27-DRIFT-ARTIFACT); they are
# CLI-visible so a test can exercise both sides, and the unit commands never override them.
SHARE_MOVE = 0.05
AUC_DROP = -0.03
MIN_LABELLED = 200
MIN_NEWEST_ROWS = 500
PASS_MIN_HEADS = 6
FAIL_MIN_DECAY = 4
SCAN_DAYS = 14.0
RECENT_DAYS = 3.0
LOOKBACK_DAYS = 60.0
MIN_MIX_REF = 200
MIN_REWEIGHTED = 200

SCORE_SEMANTICS = ("served score = max class probability for multiclass heads "
                   "(scripts/ml/_regime_score_semantics.py): the split-mode AUC is a confidence-vs-label relation, "
                   "not a P(volatile) ranking")
VERSION_ASSIGNMENT = ("INFERRED: the shadow log has no model-version field; a row is assigned to the latest registry "
                      "RunRecord with at <= its timestamp (assumes the live loader picks up a retrain at registration)")

_TF_SECONDS = {"1m": 60.0, "5m": 300.0, "15m": 900.0, "30m": 1800.0, "1h": 3600.0, "2h": 7200.0, "4h": 14400.0, "1d": 86400.0}


@dataclass(frozen=True)
class Row:
    ts: datetime
    score: float
    feature_row: Dict[str, Any]


# ── reading ───────────────────────────────────────────────────────────────────
def _utc(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def read_rows(shadow_log: Path, model_id: str, *, since: datetime, until: datetime) -> List[Row]:
    """Real-time rows for one head in [since, until], chronological. Backfill rows are excluded (synthetic timestamps
    -- the same exclusion the scan itself makes); non-finite scores are dropped (ADWIN skips them too)."""
    out: List[Row] = []
    for r in iter_records_with_archives(shadow_log, since=since):
        if r.model_id != model_id or r.backfill_kind is not None or r.predicted_at_utc > until:
            continue
        if not math.isfinite(r.score):
            continue
        out.append(Row(r.predicted_at_utc, float(r.score), dict(r.feature_row or {})))
    out.sort(key=lambda x: x.ts)
    return out


# ── mode: split ───────────────────────────────────────────────────────────────
def window_stats(rows: Sequence[Row], label_of: Callable[[datetime], Optional[int]]) -> Dict[str, Any]:
    """n_scored, n_labelled, volatile_label_share and the AUC of the served score vs the realised label."""
    from scripts.ml.replay_pregate import _auc
    scores: List[float] = []
    labels: List[int] = []
    for r in rows:
        y = label_of(r.ts)
        if y is None:
            continue
        scores.append(r.score)
        labels.append(int(y))
    n = len(labels)
    auc = _auc(scores, labels) if n else None
    return {"n_scored": len(rows), "n_labelled": n,
            "volatile_label_share": (sum(labels) / n) if n else None,
            "auc": auc,
            "mean_score": (sum(r.score for r in rows) / len(rows)) if rows else None}


def split_verdict(ref: Dict[str, Any], cur: Dict[str, Any]) -> Tuple[str, str]:
    """RULE-RQ1011-6E85-DRIFT-SPLIT -> (rule_verdict, why)."""
    if ref["n_labelled"] < MIN_LABELLED or cur["n_labelled"] < MIN_LABELLED:
        return "underpowered", f"labelled rows ref={ref['n_labelled']} cur={cur['n_labelled']} (< {MIN_LABELLED})"
    if ref["auc"] is None or cur["auc"] is None:
        return "underpowered", "one window has a single label class, AUC undefined"
    d_share = cur["volatile_label_share"] - ref["volatile_label_share"]
    d_auc = cur["auc"] - ref["auc"]
    if abs(d_share) >= SHARE_MOVE and d_auc >= AUC_DROP:
        return "regime_mix", f"delta_share={d_share:+.3f} (>= {SHARE_MOVE}) and delta_auc={d_auc:+.3f} (>= {AUC_DROP})"
    if d_auc < AUC_DROP:
        return "capability_loss", f"delta_auc={d_auc:+.3f} < {AUC_DROP}"
    return "no_explanation", f"delta_share={d_share:+.3f}, delta_auc={d_auc:+.3f}: mix and AUC both flat"


def split_head(rows_ref: Sequence[Row], rows_cur: Sequence[Row], label_of: Callable[[datetime], Optional[int]]) -> Dict[str, Any]:
    ref, cur = window_stats(rows_ref, label_of), window_stats(rows_cur, label_of)
    verdict, why = split_verdict(ref, cur)
    out: Dict[str, Any] = {"reference": ref, "current": cur, "rule_verdict": verdict, "why": why}
    if ref["volatile_label_share"] is not None and cur["volatile_label_share"] is not None:
        out["delta_share"] = cur["volatile_label_share"] - ref["volatile_label_share"]
    if ref["auc"] is not None and cur["auc"] is not None:
        out["delta_auc"] = cur["auc"] - ref["auc"]
    if rows_ref and rows_cur:
        rep = compute_drift([r.score for r in rows_ref], [r.score for r in rows_cur])
        out["score_drift"] = {"ks": rep.ks, "psi": rep.psi, "overall": rep.overall_verdict,
                              "ref_mean": rep.reference.mean, "cur_mean": rep.current.mean}
    return out


def unit_verdict_split(per_head: Dict[str, Dict[str, Any]]) -> Tuple[str, str]:
    """Unit-level read of the per-head rule verdicts -> (script_run verdict, rule label)."""
    labels = [h["rule_verdict"] for h in per_head.values()]
    if any(x == "capability_loss" for x in labels):
        return "fail", "capability_loss"
    if any(x == "underpowered" for x in labels):
        return "indeterminate", "underpowered"
    if any(x == "regime_mix" for x in labels):
        return "no_action_warranted", "regime_mix"
    return "no_action_warranted", "no_explanation"


def build_label_fn(candles: Path, *, forward_m: int, vol_threshold: Optional[float], bar_seconds: float):
    """realised-label lookup reusing RG4's rule (forward_vol > vol_threshold), so the label is the head's own definition."""
    from scripts.ml import replay_pregate_live as rg4
    from scripts.ml.replay_pregate_fleet import _load_jsonl
    rows = _load_jsonl(candles)
    vt, source = rg4._resolve_vol_threshold(rows, str(candles), rg4._VT_UNSET if vol_threshold is None else vol_threshold)
    lmap = rg4._forward_label_map(rows, forward_m=forward_m, vol_threshold=vt, positive_class="volatile")
    keys = sorted(lmap)
    tol = max(bar_seconds, 1.0)
    return (lambda when: rg4._nearest_label(lmap, when, keys, tol)), {"vol_threshold": vt, "vol_threshold_source": source,
                                                                      "n_label_bars": len(lmap)}


# ── mode: by-version ──────────────────────────────────────────────────────────
def version_starts(registry_root: Path, model_id: str) -> Optional[List[Tuple[str, datetime]]]:
    """[(run_id, at)] ascending, or None when the head is not in the registry."""
    from ml.registry.model_registry import ModelRegistry
    reg = ModelRegistry(registry_root)
    if not reg.exists(model_id):
        return None
    return sorted(((r.run_id, r.at if r.at.tzinfo else r.at.replace(tzinfo=timezone.utc)) for r in reg.get(model_id).runs),
                  key=lambda x: x[1])


def session_bucket(ts: datetime) -> int:
    return ts.astimezone(timezone.utc).hour // 6


def stratum(r: Row) -> Tuple[str, int]:
    return (str(r.feature_row.get("symbol") or "?"), session_bucket(r.ts))


def reweight_to_mix(rows: Sequence[Row], target: Dict[Tuple[str, int], float]) -> List[Row]:
    """Deterministic stratified subsample of `rows` whose stratum shares equal `target`.

    Strata absent from the target are dropped; the sample size is the largest the scarcest stratum allows. The kept
    rows are ordered by fractional progress through their own stratum (not by wall-clock), so a stratum that was only
    present in part of the window cannot masquerade as a level shift: a score that is a function of the stratum alone
    reads stationary here, while a trend INSIDE every stratum still reads as drift."""
    by: Dict[Tuple[str, int], List[Row]] = {}
    for r in rows:
        if stratum(r) in target:
            by.setdefault(stratum(r), []).append(r)
    if not by or any(k not in by for k, w in target.items() if w > 0):
        return []
    total = min(len(by[k]) / w for k, w in target.items() if w > 0)
    keyed: List[Tuple[float, Tuple[str, int], Row]] = []
    for k, w in target.items():
        take = int(total * w)
        pool = by.get(k, [])
        if take <= 0 or not pool:
            continue
        step = len(pool) / take
        keyed.extend((i / take, k, pool[int(i * step)]) for i in range(take))
    keyed.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in keyed]


def adwin_flag(rows: Sequence[Row], model_id: str, now: datetime) -> Dict[str, Any]:
    ev = scan_stream((r.score for r in rows), model_id=model_id)
    last_age = None
    if ev.drift_detected and 0 < ev.last_drift_index <= len(rows):
        last_age = round((now - rows[ev.last_drift_index - 1].ts).total_seconds() / 86400.0, 3)
    return {"n": ev.n_observations, "flagged": bool(ev.drift_detected), "last_cut_age_days": last_age,
            "mean_after_cut": ev.mean_window_after}


def version_head(model_id: str, rows_all: Sequence[Row], starts: Optional[List[Tuple[str, datetime]]], *, now: datetime,
                 scan_days: float = SCAN_DAYS) -> Dict[str, Any]:
    """rows_all = every real-time row of the head over the look-back (chronological)."""
    scan_from = now - timedelta(days=scan_days)
    scan_rows = [r for r in rows_all if r.ts >= scan_from]
    out: Dict[str, Any] = {"model_id": model_id, "n_rows_lookback": len(rows_all), "scan_window_days": scan_days}
    if not starts:
        out.update(head_verdict="INDETERMINATE", why="head not in the registry (no version boundaries)")
        return out
    run_id, newest_at = starts[-1]
    out.update(newest_run_id=run_id, newest_run_at=newest_at.isoformat(), n_versions_registered=len(starts),
               n_runs_inside_scan_window=sum(1 for _, at in starts if at >= scan_from))
    a = adwin_flag(scan_rows, model_id, now)
    newest_rows = [r for r in scan_rows if r.ts >= newest_at]
    b = adwin_flag(newest_rows, model_id, now) if newest_rows else {"n": 0, "flagged": False, "last_cut_age_days": None}
    out["a_scan_input"], out["b_newest_version"] = a, b
    out["n_newest_version_rows"] = len(newest_rows)
    if len(newest_rows) < MIN_NEWEST_ROWS:
        out.update(head_verdict="INDETERMINATE", why=f"{len(newest_rows)} scored rows on the newest version (< {MIN_NEWEST_ROWS})")
        return out
    if not a["flagged"]:
        out.update(head_verdict="INDETERMINATE", why="the scan's own flag (a) is not reproduced in this window")
        return out
    if not b["flagged"]:
        out.update(head_verdict="ARTIFACT", why="(a) flags but the newest version alone does not: the flag is the pooled stream")
        return out
    # (b) flags: is it the input mix?
    mix_rows = [r for r in rows_all if r.ts < scan_from]
    if len(mix_rows) < MIN_MIX_REF:
        out.update(head_verdict="INDETERMINATE", why=f"mix reference has {len(mix_rows)} rows (< {MIN_MIX_REF}); (c) unavailable",
                   c_mix_reweighted=None)
        return out
    counts: Dict[Tuple[str, int], int] = {}
    for r in mix_rows:
        counts[stratum(r)] = counts.get(stratum(r), 0) + 1
    target = {k: v / len(mix_rows) for k, v in counts.items()}
    re_rows = reweight_to_mix(newest_rows, target)
    if len(re_rows) < MIN_REWEIGHTED:
        out.update(head_verdict="INDETERMINATE", why=f"reweighted newest-version sample has {len(re_rows)} rows (< {MIN_REWEIGHTED})",
                   c_mix_reweighted=None)
        return out
    c = adwin_flag(re_rows, model_id, now)
    out["c_mix_reweighted"] = c
    if c["flagged"]:
        out.update(head_verdict="DECAY", why="(c) still flags on the newest version at the longer-run input mix")
    else:
        out.update(head_verdict="MIX", why="(b) flags, (c) does not: the input mix explains it")
    return out


def unit_verdict_versions(per_head: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, int]]:
    tally = {k: 0 for k in ("ARTIFACT", "MIX", "DECAY", "INDETERMINATE")}
    for h in per_head.values():
        tally[h["head_verdict"]] += 1
    if tally["DECAY"] >= FAIL_MIN_DECAY:
        return "fail", tally
    if tally["ARTIFACT"] + tally["MIX"] >= PASS_MIN_HEADS:
        return "pass", tally
    return "indeterminate", tally


# ── record + CLI ──────────────────────────────────────────────────────────────
def write_verdict(out: Path, verdict: Dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str) + "\n", encoding="utf-8")


def _parse_heads(specs: Sequence[str]) -> Dict[str, Optional[Tuple[str, str]]]:
    heads: Dict[str, Optional[Tuple[str, str]]] = {}
    for s in specs:
        mid, _, st = s.partition("=")
        heads[mid] = tuple(st.split("/", 1)) if st else None  # type: ignore[assignment]
    return heads


def _default_paths() -> Tuple[Path, Path]:
    from src.utils.paths import runtime_logs_dir
    from ml.shadow import factory
    return runtime_logs_dir() / "shadow_predictions.jsonl", Path(factory._resolve_default_registry_root())


def _latest_candles(symbol: str, tf: str, version: Optional[str] = None) -> Optional[Path]:
    """Declared dataset version when given; otherwise the alphabetically-last one, printed so the pick is never silent."""
    import glob
    base = REPO / "datasets-out" / "market_raw" / symbol / tf
    if version:
        pinned = base / version / "data.jsonl"
        print(f"[input] {symbol}/{tf}: {pinned} (declared --dataset-version)", file=sys.stderr)
        return pinned if pinned.is_file() else None
    c = sorted(glob.glob(str(base / "*" / "data.jsonl")))
    print(f"[input] {symbol}/{tf}: {c[-1] if c else '(none)'} (alphabetically last of {len(c)}; pin with --dataset-version)", file=sys.stderr)
    return Path(c[-1]) if c else None


def run(args: argparse.Namespace) -> Dict[str, Any]:
    d_log, d_reg = _default_paths() if (not args.shadow_log or not args.registry_root) else (None, None)
    log = Path(args.shadow_log) if args.shadow_log else d_log
    reg = Path(args.registry_root) if args.registry_root else d_reg
    now = _utc(args.as_of) if args.as_of else datetime.now(timezone.utc)
    heads = _parse_heads(args.head)
    if not heads:
        raise SystemExit("--head is required (repeat it; MODEL_ID[=SYMBOL/tf] in split mode)")
    base: Dict[str, Any] = {"mode": args.mode, "as_of": now.isoformat(), "heads": list(heads)}
    if not log.is_file():
        return {"verdict": "not_applicable", "read_state": "no_data", "n": 0,
                "population": f"no shadow log at {log}", "measurement": base,
                "note": "shadow log absent: NOTHING MEASURED (not 'no drift')"}
    per_head: Dict[str, Dict[str, Any]] = {}
    n_total = 0
    if args.mode == "split":
        cur_start = now - timedelta(days=args.cur_days)
        ref_start, ref_end = _utc(args.ref_start), _utc(args.ref_end)
        for mid, sym_tf in heads.items():
            rows = read_rows(log, mid, since=ref_start, until=now)
            n_total += len(rows)
            if sym_tf is None:
                per_head[mid] = {"rule_verdict": "underpowered", "why": "no SYMBOL/tf given: cannot resolve the label candles"}
                continue
            candles = _latest_candles(*sym_tf, version=args.dataset_version)
            if candles is None:
                per_head[mid] = {"rule_verdict": "underpowered", "why": f"no market_raw candles for {sym_tf[0]}/{sym_tf[1]}"}
                continue
            label_of, label_meta = build_label_fn(candles, forward_m=args.forward_m, vol_threshold=args.vol_threshold,
                                                  bar_seconds=_TF_SECONDS.get(sym_tf[1], 3600.0))
            ref_rows = [r for r in rows if ref_start <= r.ts < ref_end]
            cur_rows = [r for r in rows if r.ts >= cur_start]
            per_head[mid] = {**split_head(ref_rows, cur_rows, label_of), "label": {**label_meta, "candles": str(candles.relative_to(REPO)) if REPO in candles.parents else str(candles)}}
        verdict, rule_label = unit_verdict_split(per_head)
        measured = any(h.get("current", {}).get("n_labelled") for h in per_head.values())
        meas = {**base, "reference_window": [ref_start.isoformat(), ref_end.isoformat()], "current_window_start": cur_start.isoformat(),
                "rule_verdict": rule_label, "per_head": per_head, "score_semantics": SCORE_SEMANTICS,
                "thresholds": {"share_move": SHARE_MOVE, "auc_drop": AUC_DROP, "min_labelled": MIN_LABELLED}}
        pop = (f"{len(heads)} head(s), shadow-log real-time rows {ref_start.date()}..{now.date()} joined to realised forward-vol labels "
               f"from market_raw; {n_total} rows read")
    else:
        for mid in heads:
            rows = read_rows(log, mid, since=now - timedelta(days=args.lookback_days), until=now)
            n_total += len(rows)
            starts = version_starts(reg, mid) if reg.is_dir() else None
            per_head[mid] = version_head(mid, rows, starts, now=now, scan_days=args.scan_days)
        verdict, tally = unit_verdict_versions(per_head)
        rule_label = verdict
        measured = any(h["head_verdict"] != "INDETERMINATE" or h.get("n_newest_version_rows") for h in per_head.values())
        meas = {**base, "tally": tally, "per_head": per_head, "version_assignment": VERSION_ASSIGNMENT,
                "thresholds": {"pass_min_heads": PASS_MIN_HEADS, "fail_min_decay": FAIL_MIN_DECAY, "min_newest_rows": MIN_NEWEST_ROWS}}
        pop = (f"{len(heads)} head(s), real-time shadow rows over the last {args.lookback_days:g}d "
               f"(scan window {args.scan_days:g}d), version boundaries from the registry; {n_total} rows read")
        rule_label = f"{verdict} ({tally})"
    meas["rule_verdict"] = rule_label
    return {"verdict": verdict if measured else "not_applicable",
            "read_state": "measured" if measured else "no_data", "n": n_total, "population": pop, "measurement": meas,
            "note": (SCORE_SEMANTICS if args.mode == "split" else VERSION_ASSIGNMENT) +
                    ". Recomputes statistics only; demotes/promotes/retrains nothing (every stage change is a Tier-3 proposal)."}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("split", "by-version"))
    ap.add_argument("--head", action="append", default=[], help="MODEL_ID[=SYMBOL/tf] (repeatable)")
    ap.add_argument("--out")
    ap.add_argument("--shadow-log")
    ap.add_argument("--registry-root")
    ap.add_argument("--as-of", help="ISO time the windows are anchored to (default now); pin it to reproduce an earlier read")
    ap.add_argument("--ref-start", default="2026-09-04T00:00:00Z")
    ap.add_argument("--ref-end", default="2026-10-04T00:00:00Z")
    ap.add_argument("--cur-days", type=float, default=7.0)
    ap.add_argument("--dataset-version", help="market_raw version directory to pin (default: alphabetically last, printed)")
    ap.add_argument("--forward-m", type=int, default=5)
    ap.add_argument("--vol-threshold", type=float, default=None)
    ap.add_argument("--scan-days", type=float, default=SCAN_DAYS)
    ap.add_argument("--lookback-days", type=float, default=LOOKBACK_DAYS)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.mode or not a.out:
        ap.error("--mode and --out are required")
    rec = run(a)
    write_verdict(Path(a.out), rec)
    print(f"drift_regime_mix {a.mode}: verdict={rec['verdict']} read_state={rec['read_state']} n={rec['n']}")
    return 0


def _self_test() -> int:
    """Planted cases through the real functions: a mix shift, a capability loss, a pooled-version artifact."""
    import random
    ok = True
    rng = random.Random(7)
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def rows(n, start, mean, sd=0.03):
        return [Row(start + timedelta(minutes=15 * i), min(1.0, max(0.0, rng.gauss(mean, sd))), {"symbol": "SOLUSDT"}) for i in range(n)]

    # a stable pooled stream of two versions at different means: pooled flags, newest alone does not
    old, new = rows(600, t0, 0.55), rows(700, t0 + timedelta(days=7), 0.85)
    starts = [("r1", t0 - timedelta(days=1)), ("r2", t0 + timedelta(days=7))]
    now = t0 + timedelta(days=7) + timedelta(minutes=15 * 700)
    h = version_head("planted", old + new, starts, now=now, scan_days=30.0)
    if h["head_verdict"] == "ARTIFACT":
        print("  PASS  pooled two-version stream reads ARTIFACT")
    else:
        print(f"  FAIL  expected ARTIFACT, got {h['head_verdict']} ({h['why']})")
        ok = False
    drift = rows(350, t0, 0.5) + rows(350, t0 + timedelta(days=4), 0.9)
    h2 = version_head("planted2", drift, [("r1", t0 - timedelta(days=1))], now=t0 + timedelta(days=9), scan_days=30.0)
    if h2["head_verdict"] in ("INDETERMINATE", "MIX", "DECAY"):
        print(f"  PASS  within-version drift is NOT called an artifact ({h2['head_verdict']})")
    else:
        print(f"  FAIL  within-version drift read {h2['head_verdict']}")
        ok = False
    labels = {r.ts: (1 if i % 2 else 0) for i, r in enumerate(rows(900, t0, 0.5))}
    ref = window_stats(rows(300, t0, 0.5), lambda w: labels.get(w))
    if split_verdict(ref, ref)[0] == "no_explanation":
        print("  PASS  identical windows read no_explanation")
    else:
        print("  FAIL  identical windows should read no_explanation")
        ok = False
    with tempfile.TemporaryDirectory() as td:
        write_verdict(Path(td), {"verdict": "indeterminate", "read_state": "no_data", "n": 0, "population": "self-test"})
        if json.loads((Path(td) / "verdict.json").read_text())["read_state"] == "no_data":
            print("  PASS  verdict.json round-trips")
    print("drift_regime_mix self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
