#!/usr/bin/env python3
# wiring: manual-only - CF-B2-BULK-LIVE: counterfactual backfill over every closed live+paper order package (paged journal reads, historical bars); no scheduler
"""cf_bulk_live: the counterfactual engine over EVERY closed live + paper order package (CF-B2-BULK-LIVE), not the latest 150.

    python3 scripts/research/cf_bulk_live.py run --out comms/research/cf_bulk_live/<run_id> [--cache DIR] [--limit N]

What it does (no Claude, no API credits; reads the VM's read-only diag journal + the keyless Binance Vision archive):
  1. PAGE the journal (``order_packages`` 150/page, ``trades`` 1000/page, ``offset`` until a short page): the live grader's
     ``load_sources`` reads ``limit=150`` once and cannot backfill (design § 3.3). A page that cannot be read is a recorded
     failure and the run says so; a truncated history never reads as a complete one.
  2. CLASSIFY every package (the denominator). ``closed_n`` is the count of packages with status ``closed``; each is graded,
     or carries exactly one ``could_not_grade`` reason (``pairs_two_leg``, ``no_filled_leg``, ``legs_not_closed``,
     ``no_bars`` ...). Orphaned / rejected / shadow / emitted / open packages are counted, never graded.
  3. GRADE with the one engine (``cf_core.grade_package``) over bars from ``cf_bars.historical_bars`` (Binance Vision, 5m).
     Only fully-closed legs of a package enter the grade. Management actions are NOT replayed (``position_path_history``
     is not read per package here), so ``replayed_actual`` is the declared brackets + the leg's own trail only: the
     fidelity gap below is measured against the JOURNAL outcome and carries that bias.
  4. FIDELITY (CF-BULK-LIVE, rule registered BEFORE the run, design § 3.4): ``abs_gap_r`` <= 0.10 on >= 80% of graded
     packages, per leg (strategy). A failing leg's arms are marked ESTIMATED_LOW_FIDELITY. Not a P&L claim.

Output: ``records.jsonl.gz`` (one engine record per graded package, arms kept), ``manifest.json`` (population by status and
account, ``could_not_grade`` by reason, input hash), ``fidelity.json`` (overall and per leg), ``summary.md``.
Provenance of every number: ESTIMATED (engine replay, stated biases in each record), never MEASURED.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bars  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_bulk_live/1"
TF = "5m"
FIDELITY_TOL_R = 0.10
FIDELITY_FRAC = 0.80
MIN_LEG_N = 10                      # a per-leg fidelity verdict needs n >= 10 graded packages, else INDETERMINATE
FILLED_STATUS = {"closed"}
PAIRS_PREFIX = "pairs_"
GRADE_RESERVE_S = 0


def fetch_pages(table: str, page: int, *, retries: int = 5, fetch: Optional[Callable[[str], Any]] = None) -> Tuple[List[dict], List[int]]:
    """Every row of ``journal?table=<table>`` by offset. Returns ``(rows, failed_offsets)``; a failed page is retried and
    then recorded, and paging continues past it only while the next page reads (so a transient failure is visible)."""
    fetch = fetch or _diag
    rows: List[dict] = []
    failed: List[int] = []
    off = 0
    while True:
        got = None
        for k in range(retries):
            try:
                d = fetch(f"journal?table={table}&limit={page}&offset={off}")
                got = d.get("rows", d) if isinstance(d, dict) else d
                break
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):   # a bad page is a recorded state (``failed``), retried
                time.sleep(1 + 2 * k)
        if got is None:
            failed.append(off)
            off += page
            if len(failed) >= 3:
                break
            continue
        rows += got
        if len(got) < page:
            break
        off += page
    return rows, failed


def _diag(path: str) -> Any:
    o = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=180, check=False)
    if o.returncode != 0:
        raise RuntimeError(f"diag_fetch {path}: exit {o.returncode}")
    return json.loads(o.stdout)


def classify(pkg: dict, legs: List[dict]) -> Tuple[Optional[List[dict]], Optional[str]]:
    """(filled closed legs, None) or (None, reason). Only a ``closed`` package is in the population."""
    if str(pkg.get("strategy_name") or "").startswith(PAIRS_PREFIX):
        return None, "pairs_two_leg"
    filled = [t for t in legs if str(t.get("status") or "").lower() in FILLED_STATUS]
    if not filled:
        return None, "no_filled_leg"
    ok = [t for t in filled if t.get("closed_at") and t.get("entry_price") is not None and t.get("exit_price") is not None]
    if len(ok) != len(filled):
        return None, "legs_not_closed"
    if not str(pkg.get("symbol") or "").endswith("USDT"):
        return None, "no_bars_non_crypto"
    return ok, None


def make_fetcher(span: Dict[str, Tuple[float, float]], bars_fn: Callable[[str, str, float, float], List[dict]]):
    """Fetch each symbol's whole span ONCE, then slice per package (a network fetch per package would take hours)."""
    cache: Dict[str, List[dict]] = {}

    def fetcher(symbol: str, tf: str, t0: float, t1: float):
        if symbol not in cache:
            lo, hi = span[symbol]
            cache[symbol] = bars_fn(symbol, tf, lo, hi)
        return [b for b in cache[symbol] if b["time"] + b["dur"] > t0 and b["time"] < t1]
    return fetcher


def grade_all(packages: List[dict], trades: List[dict], *, bars_fn=None, now: Optional[float] = None, limit: Optional[int] = None,
              n_random: int = cf_core.N_RANDOM) -> Tuple[List[dict], List[dict]]:
    """``(records, skips)``: records are graded packages, skips are ``{order_package_id, reason}`` for every closed package
    that was not graded. Every closed package is in exactly one of the two."""
    now = now or datetime.now(timezone.utc).timestamp()
    bars_fn = bars_fn or (lambda s, tf, a, b: cf_bars.historical_bars(s, tf, a, b))
    by_pkg: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        if t.get("order_package_id"):
            by_pkg[t["order_package_id"]].append(t)
    closed = sorted((p for p in packages if str(p.get("status")).lower() == "closed"), key=lambda p: p.get("created_at") or "")
    if limit:
        closed = closed[-limit:]
    todo: List[Tuple[dict, List[dict], dict, float, float]] = []
    skips: List[dict] = []
    span: Dict[str, List[float]] = {}
    for p in closed:
        legs, why = classify(p, by_pkg.get(p["order_package_id"], []))
        if why:
            skips.append({"order_package_id": p["order_package_id"], "reason": why, "strategy": p.get("strategy_name")})
            continue
        t_entry = min(lrc._ts(t.get("timestamp")) or 1e18 for t in legs)
        t_close = max(lrc._ts(t.get("closed_at")) or 0 for t in legs)
        hz = cf_core.resolve_horizon(p, _strategy_config(p.get("strategy_name")))
        if now < t_close + hz["seconds"]:
            skips.append({"order_package_id": p["order_package_id"], "reason": "horizon_not_passed", "strategy": p.get("strategy_name")})
            continue
        s = span.setdefault(p["symbol"], [t_entry, t_close + hz["seconds"]])
        s[0], s[1] = min(s[0], t_entry), max(s[1], t_close + hz["seconds"])
        todo.append((p, legs, hz, t_entry, t_close))
    fetcher = make_fetcher({k: (v[0], v[1]) for k, v in span.items()}, bars_fn)
    records: List[dict] = []
    for p, legs, hz, t_entry, t_close in todo:
        bars = cf_bars.historical_bars(p["symbol"], TF, t_entry, t_close + hz["seconds"], fetcher)
        if not bars:
            skips.append({"order_package_id": p["order_package_id"], "reason": "no_bars", "strategy": p.get("strategy_name")})
            continue
        rec = cf_core.grade_package(p, legs, bars, [], [], {}, {}, horizon=hz, n_random=n_random)
        if rec.get("status") != "graded":
            skips.append({"order_package_id": p["order_package_id"], "reason": rec.get("reason") or "not_graded", "strategy": p.get("strategy_name")})
            continue
        rec["accounts"] = sorted({t.get("account_id") for t in legs})
        rec["resolution"] = TF
        records.append(rec)
    return records, skips


_STRAT_CACHE: Dict[str, dict] = {}


def _strategy_config(name: Optional[str]) -> dict:
    import yaml
    if not _STRAT_CACHE:
        d = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()) or {}
        _STRAT_CACHE.update(d.get("strategies") or d)
    return dict(_STRAT_CACHE.get(name) or {})


def fidelity(records: List[dict]) -> Dict[str, Any]:
    """CF-BULK-LIVE rule: abs_gap_r <= TOL on >= FRAC of graded; per leg with n >= MIN_LEG_N, else INDETERMINATE."""
    def block(rs: List[dict]) -> Dict[str, Any]:
        gaps = [r["fidelity"]["abs_gap_r"] for r in rs if (r.get("fidelity") or {}).get("abs_gap_r") is not None]
        if not gaps:
            return {"n": len(rs), "n_with_gap": 0, "frac_within_tol": None, "median_abs_gap_r": None, "verdict": "INDETERMINATE"}
        gaps_s = sorted(gaps)
        frac = sum(g <= FIDELITY_TOL_R for g in gaps) / len(gaps)
        verdict = "INDETERMINATE" if len(gaps) < MIN_LEG_N else ("PASS" if frac >= FIDELITY_FRAC else "FAIL")
        return {"n": len(rs), "n_with_gap": len(gaps), "frac_within_tol": round(frac, 4), "median_abs_gap_r": round(gaps_s[len(gaps_s) // 2], 4),
                "p90_abs_gap_r": round(gaps_s[int(0.9 * (len(gaps_s) - 1))], 4), "verdict": verdict}
    legs: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        legs[str(r.get("strategy"))].append(r)
    return {"rule": {"tol_r": FIDELITY_TOL_R, "frac": FIDELITY_FRAC, "min_leg_n": MIN_LEG_N}, "overall": block(records),
            "per_leg": {k: block(v) for k, v in sorted(legs.items())}}


def population(packages: List[dict], trades: List[dict]) -> Dict[str, Any]:
    st = Counter(str(p.get("status")) for p in packages)
    by_pkg: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        if t.get("order_package_id"):
            by_pkg[t["order_package_id"]].append(t)
    acct = Counter()
    for p in packages:
        if str(p.get("status")).lower() != "closed":
            continue
        for a in {t.get("account_id") for t in by_pkg.get(p["order_package_id"], []) if str(t.get("status")).lower() == "closed"}:
            acct[a] += 1
    return {"packages_total": len(packages), "by_status": dict(st), "closed_n": st.get("closed", 0),
            "closed_packages_by_account_with_a_closed_leg": dict(acct),
            "note": "a package on several accounts counts once per account here and once in closed_n"}


def run(out: Path, cache: Optional[Path], limit: Optional[int]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    if cache and (cache / "order_packages.json").exists() and (cache / "trades.json").exists():
        packages, trades, failed = json.loads((cache / "order_packages.json").read_text()), json.loads((cache / "trades.json").read_text()), {"order_packages": [], "trades": []}
    else:
        packages, fp = fetch_pages("order_packages", 150)
        trades, ft = fetch_pages("trades", 1000)
        failed = {"order_packages": fp, "trades": ft}
    t0 = time.time()
    records, skips = grade_all(packages, trades, limit=limit)
    fid = fidelity(records)
    pop = population(packages, trades)
    reasons = Counter(s["reason"] for s in skips)
    manifest = {"schema": SCHEMA, "run_at": datetime.now(timezone.utc).isoformat(), "engine_schema_version": cf_core.SCHEMA_VERSION, "resolution": TF,
                "population": pop, "failed_pages": failed, "input_sha1": hashlib.sha1(json.dumps([sorted(p["order_package_id"] for p in packages)]).encode()).hexdigest(),
                "closed_packages_graded": len(records), "closed_packages_not_graded": len(skips), "could_not_grade_by_reason": dict(reasons),
                "closed_accounted_for": len(records) + len(skips), "seconds": round(time.time() - t0, 1), "provenance": "ESTIMATED"}
    with gzip.open(out / "records.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    (out / "skips.json").write_text(json.dumps(skips, indent=0) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (out / "fidelity.json").write_text(json.dumps(fid, indent=1) + "\n")
    print(json.dumps({"closed_n": pop["closed_n"], "graded": len(records), "not_graded": dict(reasons), "fidelity_overall": fid["overall"]}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--cache", help="dir holding order_packages.json + trades.json (skips the paged VM read)")
    r.add_argument("--limit", type=int, help="grade only the newest N closed packages (smoke)")
    a = ap.parse_args(argv)
    return run(Path(a.out), Path(a.cache) if a.cache else None, a.limit)


if __name__ == "__main__":
    sys.exit(main())
