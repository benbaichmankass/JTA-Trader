#!/usr/bin/env python3
# wiring: manual-only - CF-B1 bulk counterfactual runner; driven by .github/workflows/cf-bulk-backtest.yml (plan -> shard matrix -> reduce)
"""cf_bulk: the sharded, resumable bulk counterfactual run over every distinct backtest replay job (CF-B1-BULK-BACKTEST).

Three verbs, all OFFLINE except the bar fetch (Binance Vision archive, keyless, no Claude, no API credits):

* ``plan``   - discover the trade files, count the population, split it into shards, write ``plan.json``.
* ``shard``  - grade ONE shard (a (symbol, timeframe) slice, <= ``--max-jobs``) with ``cf_harness.cf_fields`` and write
               ``<out>/shards/<shard_id>.jsonl.gz`` + ``<shard_id>.meta.json``. IDEMPOTENT: the shard id is a hash of its
               job keys + the engine ``SCHEMA_VERSION``; a finished shard (meta present, same id) is a no-op.
* ``reduce`` - read every shard, write ``manifest.json`` (counts, ``could_not_grade`` by reason, input hash) and
               ``summary.json`` (CF-BULK-BT and CF-BULK-POSTEXIT per leg, rules registered BEFORE the run, below).

A shard that fails is a recorded state (``failed``), never a halt; re-running retries it.

Registered rules (design docs/plans/counterfactual-everywhere-DESIGN-2026-10-29.md § 3.4), per leg = (strategy, symbol)
with n >= MIN_N graded jobs:
* CF-BULK-BT: an arm cell (alt-bracket cell or management arm) is a PASS when its mean (arm net R - original_brackets net R)
  >= +0.05 in >= 4 of 6 equal-count time folds AND the bootstrap-by-trade 95% CI of the whole-sample mean delta excludes 0.
  Leg verdict PASS (any arm passes) / FAIL (none) / INDETERMINATE (n < MIN_N). The best cell is selected over the whole
  sample, so a PASS is a CANDIDATE for out-of-sample replication, not an edge (the Holm-adjusted one-sided p is reported
  across legs; the multiplicity over arm cells within a leg is NOT corrected - stated, not hidden). Not a promotion case.
* CF-BULK-POSTEXIT: share of resolved ``post_exit.verdict`` that is ``exited_early``: >= 0.40 LEAVES_R, <= 0.15 SAVES_R,
  else MIXED; n resolved < MIN_N INDETERMINATE.
Provenance of every number is ESTIMATED (engine replay with the engine's cost policy), never MEASURED.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import random
import re
import sys
import time
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bars  # noqa: E402
import cf_core  # noqa: E402
import cf_harness  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

BULK_SCHEMA = "cf_bulk/1"
MIN_N = 100
MIN_DELTA_R = 0.05
FOLDS = 6
FOLDS_NEEDED = 4
POSTEXIT_HI, POSTEXIT_LO = 0.40, 0.15
DEFAULT_MAX_JOBS = 20_000
TRADE_GLOBS = ("comms/research/**/*trades*.jsonl*", "comms/strategy_evidence/**/*trades*.jsonl*")
_TF_IN_NAME = re.compile(r"(?:^|[_/-])(\d+[mhdw])(?:[_.]|$)")
_SUPPORTED_TF = set(cf_bars.TF_SECONDS)


def _open(p: str):
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, "r", encoding="utf-8")


def discover(root: Path = REPO) -> List[str]:
    return sorted({str(Path(f).relative_to(root)) for g in TRADE_GLOBS for f in glob.glob(str(root / g), recursive=True)})


def resolve_timeframe(path: str, strategy: Any) -> Tuple[Optional[str], Optional[str]]:
    """``(tf, None)`` or ``(None, reason)``. File name token wins, then a ``_<tf>`` suffix on the strategy label."""
    for cand in (Path(path).name, str(strategy or "")):
        m = _TF_IN_NAME.search(cand if cand != str(strategy or "") else "_" + cand)
        if m:
            tf = m.group(1)
            return (tf, None) if tf in _SUPPORTED_TF else (None, "timeframe_unsupported")
    return None, "timeframe_unresolved"


def is_crypto(symbol: str) -> bool:
    return str(symbol).endswith("USDT")


def load_jobs(files: Iterable[str], root: Path = REPO) -> Tuple[Dict[str, dict], Dict[str, Any]]:
    """Distinct replay jobs keyed by ``trade_key`` (strategy|symbol|entry_time|direction|sl); the first occurrence wins.
    Rows without replayable geometry are counted, not dropped silently. Returns ``(jobs, counts)``."""
    jobs: Dict[str, dict] = {}
    c = Counter()
    for rel in files:
        try:
            fh = _open(str(root / rel))
        except OSError:
            c["files_unreadable"] += 1
            continue
        with fh:
            n_file = 0
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    c["parse_errors"] += 1
                    continue
                n_file += 1
                c["rows"] += 1
                if not all(r.get(k) is not None for k in ("entry", "sl", "direction", "exit_time", "entry_time")):
                    c["rows_not_replayable"] += 1
                    continue
                c["rows_replayable"] += 1
                if r.get("symbol") is None:
                    r["symbol"] = "UNKNOWN"      # file carries no symbol: counted as could_not_grade symbol_unresolved, never dropped
                k = cf_harness.trade_key(r.get("strategy"), r.get("symbol"), r.get("entry_time"), r.get("direction"), r.get("sl"))
                if k in jobs:
                    continue
                r["_file"] = rel
                jobs[k] = r
            c["files_empty" if n_file == 0 else "files_nonempty"] += 1
    c["files"] = c["files_empty"] + c["files_nonempty"] + c["files_unreadable"]
    c["distinct_jobs"] = len(jobs)
    return jobs, dict(c)


def plan_shards(jobs: Dict[str, dict], max_jobs: int = DEFAULT_MAX_JOBS) -> Tuple[List[dict], Dict[str, List[str]]]:
    """Group jobs by (symbol, timeframe) and chunk each group. Jobs with no resolvable timeframe get their own
    ``tf=None`` shards so they are COUNTED as ``could_not_grade`` in the manifest, never lost."""
    groups: Dict[Tuple[str, Optional[str], Optional[str]], List[str]] = defaultdict(list)
    for k, r in sorted(jobs.items()):
        tf, why = resolve_timeframe(r["_file"], r.get("strategy"))
        groups[(str(r["symbol"]), tf, why)].append(k)
    shards: List[dict] = []
    chunks: Dict[str, List[str]] = {}
    for (sym, tf, why), keys in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        for i in range(0, len(keys), max_jobs):
            chunk = keys[i:i + max_jobs]
            sid = shard_id(sym, tf, chunk)
            shards.append({"shard_id": sid, "symbol": sym, "timeframe": tf, "tf_reason": why, "n_jobs": len(chunk),
                           "keys_hash": hashlib.sha1("\n".join(chunk).encode()).hexdigest()})
            chunks[sid] = chunk
    return shards, chunks


def shard_id(symbol: str, tf: Optional[str], keys: List[str]) -> str:
    h = hashlib.sha1((f"{symbol}|{tf}|v{cf_core.SCHEMA_VERSION}|{cf_harness.SCHEMA}|" + "\n".join(keys)).encode()).hexdigest()[:12]
    return f"{symbol}_{tf or 'notf'}_{h}"


class BarStore:
    """One fetch per shard; each job slices its window with bisect (O(log n))."""

    def __init__(self, bars: List[dict]):
        self.bars, self.t = bars, [b["time"] for b in bars]

    def window(self, t0: float, t1: float) -> List[dict]:
        return self.bars[bisect_left(self.t, t0):bisect_left(self.t, t1)]


def grade_job(job: dict, store: Optional[BarStore], tf: Optional[str], n_random: int) -> dict:
    row = {k: v for k, v in job.items() if k != "_file"}
    if row.get("symbol") == "UNKNOWN":
        cf = cf_harness._could_not(row, "symbol_unresolved")
    elif tf is None:
        cf = cf_harness._could_not(row, "timeframe_unresolved")
    elif not is_crypto(row["symbol"]):
        cf = cf_harness._could_not(row, "no_bar_source")
    elif store is None:
        cf = cf_harness._could_not(row, "no_bars")
    else:
        cfg = {"timeframe": tf}
        t_entry, t_exit = lrc._ts(row.get("entry_time")), lrc._ts(row.get("exit_time"))
        if t_entry is None or t_exit is None:
            cf = cf_harness._could_not(row, "row_incomplete")
        else:
            h = cf_core.resolve_horizon({"timeframe": tf}, cfg)["seconds"]
            cf = cf_harness.cf_fields(row, store.window(t_entry, t_exit + h), None, cfg, n_random=n_random)
    return {"trade_key": cf["trade_key"], "strategy": row.get("strategy"), "symbol": row.get("symbol"), "timeframe": tf,
            "direction": row.get("direction"), "entry_time": row.get("entry_time"), "net_r": row.get("net_r"),
            "source_file": job["_file"], "cf": cf}


def run_shard(shard: dict, chunks: Dict[str, List[str]], jobs: Dict[str, dict], out: Path, *, n_random: int = cf_core.N_RANDOM, fetcher=None, force: bool = False) -> dict:
    sdir = out / "shards"
    sdir.mkdir(parents=True, exist_ok=True)
    meta_p, data_p = sdir / f"{shard['shard_id']}.meta.json", sdir / f"{shard['shard_id']}.jsonl.gz"
    if not force and meta_p.exists() and data_p.exists():
        meta = json.loads(meta_p.read_text())
        if meta.get("shard_id") == shard["shard_id"] and meta.get("state") == "done":
            return {**meta, "skipped": True}
    chosen = chunks[shard["shard_id"]]
    t0 = time.time()
    tf, state, err = shard["timeframe"], "done", None
    store: Optional[BarStore] = None
    if tf is not None:
        if not is_crypto(shard["symbol"]):
            store = None                                   # no keyless historical source wired: counted as no_bar_source
        else:
            try:
                lo = min(lrc._ts(jobs[k]["entry_time"]) for k in chosen)
                hi = max(lrc._ts(jobs[k]["exit_time"]) for k in chosen) + cf_core.resolve_horizon({"timeframe": tf}, {"timeframe": tf})["seconds"]
                bars = cf_bars.historical_bars(shard["symbol"], tf, lo, hi, fetcher)
                store = BarStore(bars) if bars else None
            except Exception as e:                           # allow-silent: a failed fetch is a recorded state (state=fetch_failed, error kept in meta, no 'done' meta so a re-run retries), never a halt
                state, err = "fetch_failed", f"{type(e).__name__}: {e}"[:300]
    reasons, n_graded = Counter(), 0
    tmp = data_p.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for k in chosen:
            rec = grade_job(jobs[k], store, tf, n_random)
            if rec["cf"].get("status") == "graded":
                n_graded += 1
            else:
                reasons[str(rec["cf"].get("reason"))] += 1
            fh.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
    tmp.replace(data_p)
    meta = {**shard, "schema": BULK_SCHEMA, "engine_schema_version": cf_core.SCHEMA_VERSION, "state": state, "error": err,
            "n_jobs": len(chosen), "n_graded": n_graded, "could_not_grade": dict(reasons), "seconds": round(time.time() - t0, 2),
            "n_random": n_random, "bars": 0 if store is None else len(store.bars)}
    if state == "done":
        meta_p.write_text(json.dumps(meta, indent=1) + "\n")
    return meta


# ---- reduce ---------------------------------------------------------------------------------------------------------
def _boot_p_le0(vals: List[float], n_boot: int = 1000, seed: int = 11) -> Tuple[Optional[List[float]], float]:
    """Bootstrap-by-trade (each value is one trade): percentile 95% CI of the mean and the one-sided p(mean <= 0)."""
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot) - 1], 4)], sum(1 for m in means if m <= 0) / n_boot


def _arm_cells(cf: dict) -> Dict[str, Optional[float]]:
    a = cf["arms"]
    out: Dict[str, Optional[float]] = {}
    for x in a.get("alt_brackets") or []:
        out[f"alt_sl{x.get('sl_mult'):g}x_tp{x.get('tp_r'):g}R"] = x.get("net_r")
    for fam in ("less_management", "more_management"):
        for x in a.get(fam) or []:
            out[f"{fam}:{x['arm_id']}"] = x.get("net_r")
    return out


def leg_verdicts(records: List[dict]) -> Dict[str, Any]:
    by_leg: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        by_leg[f"{r['strategy']}|{r['symbol']}"].append(r)
    legs: Dict[str, Any] = {}
    for leg, rs in sorted(by_leg.items()):
        graded = sorted((r for r in rs if r["cf"].get("status") == "graded"), key=lambda r: str(r["entry_time"]))
        out: Dict[str, Any] = {"n_jobs": len(rs), "n_graded": len(graded)}
        # --- POSTEXIT
        vs = [(r["cf"]["post_exit"].get("verdict") or {}) for r in graded]
        res = [v["verdict"] for v in vs if v.get("resolved") and v.get("verdict")]
        pe: Dict[str, Any] = {"n_resolved": len(res), "n_unresolved": len(graded) - len(res)}
        if len(res) >= MIN_N:
            share = res.count("exited_early") / len(res)
            pe.update(share_exited_early=round(share, 4), verdict="LEAVES_R" if share >= POSTEXIT_HI else "SAVES_R" if share <= POSTEXIT_LO else "MIXED")
        else:
            pe["verdict"] = "INDETERMINATE"
        out["postexit"] = pe
        # --- BT
        if len(graded) < MIN_N:
            out["bt"] = {"verdict": "INDETERMINATE", "why": f"n_graded {len(graded)} < {MIN_N}"}
            legs[leg] = out
            continue
        cells: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        for i, r in enumerate(graded):
            base = (r["cf"]["arms"].get("original_brackets") or {}).get("net_r")
            if base is None:
                continue
            for name, v in _arm_cells(r["cf"]).items():
                if v is not None:
                    cells[name].append((i, v - base))
        n = len(graded)
        best = None
        for name, dv in cells.items():
            if len(dv) < MIN_N:
                continue
            folds_ok = 0
            for f in range(FOLDS):
                lo, hi = f * n // FOLDS, (f + 1) * n // FOLDS
                fv = [d for i, d in dv if lo <= i < hi]
                if fv and sum(fv) / len(fv) >= MIN_DELTA_R:
                    folds_ok += 1
            mean = sum(d for _, d in dv) / len(dv)
            if best is None or mean > best["mean_delta_r"]:
                best = {"arm": name, "n": len(dv), "mean_delta_r": round(mean, 4), "folds_ge_threshold": folds_ok, "_vals": [d for _, d in dv]}
        if best is None:
            out["bt"] = {"verdict": "INDETERMINATE", "why": "no arm cell with n >= MIN_N"}
        else:
            ci, p = _boot_p_le0(best.pop("_vals"))
            ok = best["folds_ge_threshold"] >= FOLDS_NEEDED and ci[0] > 0
            out["bt"] = {"verdict": "PASS" if ok else "FAIL", **best, "ci95_mean_delta": ci, "p_one_sided": round(p, 4),
                         "n_arm_cells": len(cells), "selection": "best cell over whole sample (candidate, not edge)"}
        legs[leg] = out
    # Holm across the legs that have a BT p
    ps = sorted(((v["bt"]["p_one_sided"], k) for k, v in legs.items() if "p_one_sided" in v.get("bt", {})))
    m, running = len(ps), 0.0
    for i, (p, k) in enumerate(ps):
        running = max(running, min(1.0, (m - i) * p))
        legs[k]["bt"]["p_holm"] = round(running, 4)
    return legs


def reduce_run(out: Path, plan: dict) -> dict:
    sdir = out / "shards"
    metas, records, missing = [], [], []
    for s in plan["shards"]:
        mp, dp = sdir / f"{s['shard_id']}.meta.json", sdir / f"{s['shard_id']}.jsonl.gz"
        if not (mp.exists() and dp.exists()):
            missing.append(s["shard_id"])
            continue
        metas.append(json.loads(mp.read_text()))
        with gzip.open(dp, "rt", encoding="utf-8") as fh:
            records.extend(json.loads(line) for line in fh if line.strip())
    reasons = Counter()
    for m in metas:
        reasons.update(m.get("could_not_grade") or {})
    graded = sum(m["n_graded"] for m in metas)
    legs = leg_verdicts(records)
    bt = Counter(v["bt"]["verdict"] for v in legs.values())
    pe = Counter(v["postexit"]["verdict"] for v in legs.values())
    fid = sorted(abs(r["cf"]["fidelity"]["abs_gap_r"]) for r in records if r["cf"].get("status") == "graded" and r["cf"].get("fidelity", {}).get("abs_gap_r") is not None)
    manifest = {"schema": BULK_SCHEMA, "run_id": plan["run_id"], "engine_schema_version": cf_core.SCHEMA_VERSION, "input": plan["input"],
                "n_shards_planned": len(plan["shards"]), "n_shards_done": len(metas), "shards_missing": missing,
                "n_jobs_planned": sum(s["n_jobs"] for s in plan["shards"]), "n_jobs_in_done_shards": sum(m["n_jobs"] for m in metas),
                "n_graded": graded, "could_not_grade_by_reason": dict(reasons), "provenance": "ESTIMATED"}
    summary = {"schema": BULK_SCHEMA, "run_id": plan["run_id"], "population": f"{manifest['n_jobs_in_done_shards']} distinct replay jobs in {len(metas)} shards; {graded} graded",
               "rules": {"min_n": MIN_N, "bt": f"best arm cell mean delta vs original_brackets >= +{MIN_DELTA_R} R in >= {FOLDS_NEEDED}/{FOLDS} time folds and bootstrap-by-trade 95% CI > 0",
                         "postexit": f"exited_early share >= {POSTEXIT_HI} LEAVES_R, <= {POSTEXIT_LO} SAVES_R"},
               "bt_verdicts": dict(bt), "postexit_verdicts": dict(pe),
               "fidelity_abs_gap_r": None if not fid else {"n": len(fid), "median": round(fid[len(fid) // 2], 4), "p90": round(fid[int(0.9 * len(fid))], 4), "max": round(fid[-1], 4),
                                                           "share_le_0.10": round(sum(1 for x in fid if x <= 0.10) / len(fid), 4)},
               "legs": legs, "provenance": "ESTIMATED"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return {"manifest": manifest, "summary": summary}


# ---- cli ------------------------------------------------------------------------------------------------------------
def build_plan(run_id: str, max_jobs: int, root: Path = REPO) -> Tuple[dict, Dict[str, dict], Dict[str, List[str]]]:
    files = discover(root)
    jobs, counts = load_jobs(files, root)
    shards, chunks = plan_shards(jobs, max_jobs)
    return {"schema": BULK_SCHEMA, "run_id": run_id, "engine_schema_version": cf_core.SCHEMA_VERSION,
            "input": {**counts, "file_list_sha1": hashlib.sha1("\n".join(files).encode()).hexdigest()},
            "shards": shards}, jobs, chunks


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--run-id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-jobs", type=int, default=DEFAULT_MAX_JOBS)
    p.add_argument("--batches", type=int, default=24, help="balance the shards into this many matrix batches (batches.json)")
    s = sub.add_parser("shard")
    s.add_argument("--run-id", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--index", type=int, nargs="+", required=True, help="shard indices into plan.json (space separated)")
    s.add_argument("--plan")
    s.add_argument("--n-random", type=int, default=cf_core.N_RANDOM)
    s.add_argument("--max-jobs", type=int, default=DEFAULT_MAX_JOBS)
    s.add_argument("--force", action="store_true")
    r = sub.add_parser("reduce")
    r.add_argument("--out", required=True)
    r.add_argument("--plan")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "plan":
        plan, _, _ = build_plan(a.run_id, a.max_jobs)
        (out / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
        bins: List[Dict[str, Any]] = [{"batch": i, "index": [], "n_jobs": 0} for i in range(max(1, a.batches))]
        for i, sh in sorted(enumerate(plan["shards"]), key=lambda x: -x[1]["n_jobs"]):    # greedy longest-first
            b = min(bins, key=lambda x: x["n_jobs"])
            b["index"].append(i)
            b["n_jobs"] += sh["n_jobs"]
        bins = [b for b in bins if b["index"]]
        (out / "batches.json").write_text(json.dumps(bins) + "\n")
        print(json.dumps({"run_id": a.run_id, **plan["input"], "n_shards": len(plan["shards"]), "n_batches": len(bins)}))
        return 0
    plan = json.loads(Path(a.plan or out / "plan.json").read_text())
    if a.cmd == "reduce":
        res = reduce_run(out, plan)
        print(json.dumps({k: v for k, v in res["manifest"].items() if k != "input"}))
        return 0
    fresh, jobs, chunks = build_plan(a.run_id, a.max_jobs)
    if [x["shard_id"] for x in fresh["shards"]] != [x["shard_id"] for x in plan["shards"]]:
        print("plan.json does not match the checked-out corpus; re-plan", file=sys.stderr)
        return 2
    rc = 0
    for i in a.index:
        shard = plan["shards"][i]
        try:
            meta = run_shard(shard, chunks, jobs, out, n_random=a.n_random, force=a.force)
        except Exception as e:                                # allow-silent: recorded as state=failed with the error and a non-zero exit; a re-run retries it, never a halt
            meta = {"shard_id": shard["shard_id"], "state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
            rc = 1
        print(json.dumps({k: meta.get(k) for k in ("shard_id", "state", "n_jobs", "n_graded", "could_not_grade", "seconds", "skipped", "error")}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
