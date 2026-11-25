#!/usr/bin/env python3
# wiring: manual-only - AM v2 unit 1 driver: runs cf_bar_labels over the cf_bulk corpus (same plan/shards/bar fetch as cf_bulk, no replay): python3 scripts/research/cf_bar_labels_run.py shard --out DIR --index 0 1
"""cf_bar_labels_run: the driver that applies ``cf_bar_labels.build_rows`` to the cf_bulk job corpus (AM v2 unit 1).

Read-only on cf_bulk: it imports ``cf_bulk.build_plan`` (so the plan, shard ids and job keys are cf_bulk's own), fetches each shard's bars the
way ``cf_bulk.run_shard`` does (crypto only, same horizon window), and writes ``<out>/bar_labels/<shard_id>.jsonl.gz`` (one line per trade:
the per-bar rows) plus ``<shard_id>.meta.json`` with that shard's census. It does NOT replay brackets and does not touch cf_bulk output.
Entry convention: the signal bar's CLOSE (``cf_bar_labels``); the replayed-actual exit bar comes from the job's own ``exit_time``.

  python3 scripts/research/cf_bar_labels_run.py shard --out DIR --index 0 1 [--run-id ID]
  python3 scripts/research/cf_bar_labels_run.py census --out DIR
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bar_labels as L  # noqa: E402
import cf_bars  # noqa: E402
import cf_bulk  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402


def label_job(job: dict, bars: List[dict], tf: str, *, max_fwd_bars: int = 48, context: bool = False,
              times: Optional[List[float]] = None) -> Optional[List[dict]]:
    """Per-bar rows for one cf_bulk job over ``bars`` (ascending, bar dicts with time/open/high/low/close), or None when the job has no usable
    geometry. ``exit_idx`` = the first bar after the fill whose close is at or after the job's exit_time."""
    sec = float(cf_bars.TF_SECONDS[tf])
    t_entry, t_exit = lrc._ts(job.get("entry_time")), lrc._ts(job.get("exit_time"))
    entry, sl = lrc._num(job.get("entry")), lrc._num(job.get("sl"))
    side = {"long": "long", "buy": "long", "short": "short", "sell": "short"}.get(str(job.get("direction")).lower())
    if None in (t_entry, t_exit, entry, sl) or side is None:
        return None
    if context:
        # AM-V2-RICHER-FEATURES: the trade's window plus CTX_LOOKBACK bars of history (bars ascending; a slice, so the rows are what the full list gives)
        import bisect
        tt = times if times is not None else [b["time"] for b in bars]
        i0 = max(bisect.bisect_left(tt, t_entry + sec) - L.CTX_LOOKBACK, 0)
        bars = bars[i0:]
    after = [b for b in bars if b["time"] >= t_entry + sec]
    exit_idx = next((k for k, b in enumerate(after, start=1) if b["time"] + sec >= t_exit), None)
    if context:
        return L.build_rows(side=side, entry=entry, sl=sl, bars=bars, entry_time=t_entry, bar_seconds=sec, max_fwd_bars=max_fwd_bars,
                            exit_idx=exit_idx, context=True)
    return L.build_rows(side=side, entry=entry, sl=sl, bars=bars, entry_time=t_entry, bar_seconds=sec, max_fwd_bars=max_fwd_bars,
                        exit_idx=exit_idx)


def run_shard(shard: dict, chunks: Dict[str, List[str]], jobs: Dict[str, dict], out: Path, *, fetcher=None, max_fwd_bars: int = 48,
              context: bool = False) -> dict:
    sdir = out / "bar_labels"
    sdir.mkdir(parents=True, exist_ok=True)
    tf, sym = shard["timeframe"], shard["symbol"]
    chosen = chunks[shard["shard_id"]]
    t0, state, err, bars = time.time(), "done", None, []
    reasons = Counter()
    if tf is None:
        reasons["timeframe_unresolved"] = len(chosen)
    elif not cf_bulk.is_crypto(sym):
        reasons["no_bar_source"] = len(chosen)
    else:
        try:
            lo = min(lrc._ts(jobs[k]["entry_time"]) for k in chosen) - (L.CTX_LOOKBACK + 1) * cf_bars.TF_SECONDS[tf] * (1 if context else 0)
            hi = max(lrc._ts(jobs[k]["exit_time"]) for k in chosen) + max_fwd_bars * cf_bars.TF_SECONDS[tf]
            bars = cf_bars.historical_bars(sym, tf, lo, hi, fetcher)
        except Exception as e:   # allow-silent: a failed fetch is a recorded state (no 'done' meta, so a re-run retries), never a halt
            state, err = "fetch_failed", f"{type(e).__name__}: {e}"[:300]
    per_trade: Dict[str, List[dict]] = {}
    tmp = sdir / f"{shard['shard_id']}.jsonl.gz.tmp"
    times = [b["time"] for b in bars] if context else None
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for k in chosen if (bars and state == "done") else []:
            rows = label_job(jobs[k], bars, tf, max_fwd_bars=max_fwd_bars, context=context, times=times)
            if rows is None:
                reasons["row_incomplete"] += 1
                continue
            per_trade[k] = rows
            fh.write(json.dumps({"trade_key": k, "strategy": jobs[k].get("strategy"), "symbol": sym, "timeframe": tf,
                                 "direction": jobs[k].get("direction"), "rows": rows}, separators=(",", ":"), default=str) + "\n")
    tmp.replace(sdir / f"{shard['shard_id']}.jsonl.gz")
    meta = {**shard, "schema": L.SCHEMA, "state": state, "error": err, "n_jobs": len(chosen), "n_labelled_trades": len(per_trade),
            "could_not_label": dict(reasons), "census": L.census(per_trade), "bars": len(bars), "seconds": round(time.time() - t0, 2),
            "max_fwd_bars": max_fwd_bars, "context": context, "provenance": "ESTIMATED"}
    if state == "done":
        (sdir / f"{shard['shard_id']}.meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


def reduce_census(out: Path) -> dict:
    n_tr = n_rows = n_cens = n_stop = n_dip = n_unc = 0
    reasons: Counter = Counter()
    for mp in sorted((out / "bar_labels").glob("*.meta.json")):
        m = json.loads(mp.read_text())
        reasons.update(m.get("could_not_label") or {})
        c = m.get("census") or {}
        n_tr += c.get("n_trades", 0)
        n_rows += c.get("n_rows", 0)
        n_cens += c.get("n_censored", 0)
        unc = c.get("n_rows", 0) - c.get("n_censored", 0)
        n_unc += unc
        n_stop += round((c.get("share_stop_first_uncensored") or 0) * unc)
        n_dip += round((c.get("share_dip_recovers_uncensored") or 0) * unc)
    return {"schema": L.SCHEMA, "n_trades": n_tr, "n_rows": n_rows, "n_censored": n_cens,
            "share_censored": round(n_cens / n_rows, 4) if n_rows else None,
            "share_stop_first_uncensored": round(n_stop / n_unc, 4) if n_unc else None,
            "share_dip_recovers_uncensored": round(n_dip / n_unc, 4) if n_unc else None,
            "could_not_label": dict(reasons), "provenance": "ESTIMATED",
            "population": "all shards with a done meta under bar_labels/; shares are over uncensored rows (a row is one trade at one open bar)"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--out", required=True)
    s.add_argument("--index", type=int, nargs="+", required=True)
    s.add_argument("--run-id", default="cf-bar-labels")
    s.add_argument("--max-jobs", type=int, default=cf_bulk.DEFAULT_MAX_JOBS)
    s.add_argument("--max-fwd-bars", type=int, default=48)
    s.add_argument("--context", action="store_true", help="AM-V2-RICHER-FEATURES: add the ctx block (fetches CTX_LOOKBACK bars of history)")
    c = sub.add_parser("census")
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "census":
        res = reduce_census(out)
        (out / "census.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps(res))
        return 0
    plan, jobs, chunks = cf_bulk.build_plan(a.run_id, a.max_jobs)
    rc = 0
    for i in a.index:
        meta = run_shard(plan["shards"][i], chunks, jobs, out, max_fwd_bars=a.max_fwd_bars, context=a.context)
        print(json.dumps({k: meta[k] for k in ("shard_id", "state", "n_jobs", "n_labelled_trades")}), flush=True)
        rc = rc or (0 if meta["state"] == "done" else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
