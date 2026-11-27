#!/usr/bin/env python3
# wiring: manual-only - run via the trainer-vm-diag relay; report-only by default, --apply only after the manager reviews the dry-run list (row TRAINER-REGISTRY-RETENTION)
"""Bounded retention for training-run ARTIFACT dirs under ml/experiments-runs/ (row TRAINER-REGISTRY-RETENTION).

WHY. Every daily retrain writes ``experiments-runs/<model_id>/<run_id>/`` (~1.4 MB) and nothing ever removed one: on the 1 OCPU /
6 GB trainer the tree reached 10.5 GB in 10,950 dirs, and the disk lost ~0.31 GB/day (MEASURED 19G free 2026-11-11 -> 14G 2026-11-27,
which tripped the etf-history 15 GB start floor). Re-measure, never quote: this tool prints its own byte totals.

WHAT IS READ (code read 2026-11-27, recorded on the row). The registry's per-run METADATA (``registry-store/<id>.json runs[]``) is read
by the promotion gates, live_parity and training_center; it is small and this tool NEVER touches it. Only ARTIFACT dirs are pruned.
Loaders of an artifact: the shadow factory and backfill (``entry.model_state_path``, the served/incumbent state, which can be OLDER
than the newest run when a cost-gated retrain was refused), the runner's cost gate (the incumbent), m23_ev_gate (the newest run).
The live-VM mirror rsync has no ``--delete``, so pruning here never removes the mirror's copies.

A run dir is KEPT, with every reason printed, when ANY of:
  - ``served``  -- it holds the registry entry's top-level ``model_state_path`` (whatever its age);
  - ``newest``  -- it is one of the model's newest ``--keep-last`` run dirs (run ids are sortable UTC timestamps);
  - ``young``   -- its newest file is younger than ``--min-age-days``;
  - ``ref``     -- ``<model_id>/<run_id>`` appears in a text file under ``--ref-roots`` (evidence records, configs, research);
  - ``unknown`` -- its run id does not parse as a timestamp (never guessed at).
Everything else is a ``gc_candidate`` with its measured size. Default is REPORT-ONLY; ``--apply`` deletes, and only inside the
experiments root. Unreadable registry -> nothing is a candidate (fail closed). Gates this adds or changes: none.

    python3 scripts/ops/trainer_run_retention.py [--experiments-root ml/experiments-runs] [--registry-root ml/registry-store]
        [--keep-last 14] [--min-age-days 14] [--list-kept] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

_RUN_RE = re.compile(r"^\d{8}T\d{6}Z$")
_REF_RE = re.compile(r"([A-Za-z0-9_.-]+)/(\d{8}T\d{6}Z)")
_DEFAULT_REF_ROOTS = ("ml/configs", "research", "docs", "comms", "config", "scripts")
_SKIP_DIRS = {".git", "__pycache__", ".venv", "experiments-runs", "registry-store", "runtime_logs", "datasets-out", "data"}
_TEXT_EXT = (".py", ".sh", ".yaml", ".yml", ".json", ".jsonl", ".md", ".txt", ".toml", ".csv")
_MAX_REF_FILE_BYTES = 5_000_000


def served_runs(registry_root: Path) -> tuple[dict[str, str] | None, int]:
    """model_id -> run_id of its top-level ``model_state_path``; None when the registry cannot be read (fail closed)."""
    if not registry_root.is_dir():
        return None, 0
    out: dict[str, str] = {}
    n = 0
    for p in sorted(registry_root.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, n                       # one unreadable entry -> refuse to judge anything
        n += 1
        msp = str(d.get("model_state_path") or "")
        mid = str(d.get("model_id") or "")
        if "experiments-runs/" in msp:
            parts = msp.split("experiments-runs/", 1)[1].split("/")
            if len(parts) >= 2:
                out[parts[0] or mid] = parts[1]
    return out, n


def text_refs(roots: list[Path]) -> set[tuple[str, str]]:
    """(model_id, run_id) pairs named anywhere in text files under *roots*."""
    refs: set[tuple[str, str]] = set()
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for f in files:
                if not f.endswith(_TEXT_EXT):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if os.path.getsize(p) > _MAX_REF_FILE_BYTES:
                        continue
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        refs.update(_REF_RE.findall(fh.read()))
                except OSError:
                    continue
    return refs


def _newest_mtime(d: Path) -> float:
    best = d.stat().st_mtime
    for dirpath, _dirs, files in os.walk(d):
        for f in files:
            try:
                best = max(best, os.path.getmtime(os.path.join(dirpath, f)))
            except OSError:
                continue
    return best


def _bytes(d: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total


def plan(experiments_root: Path, registry_root: Path, ref_roots: list[Path], keep_last: int = 14,
         min_age_days: float = 14.0, now: float | None = None) -> tuple[list[dict], dict]:
    """Every run dir with its status and reasons, plus a summary. Pure apart from reading the filesystem."""
    now = time.time() if now is None else now
    served, n_entries = served_runs(registry_root)
    refs = text_refs(ref_roots)
    rows: list[dict] = []
    for mdir in sorted(p for p in experiments_root.iterdir() if p.is_dir()) if experiments_root.is_dir() else []:
        runs = sorted(p for p in mdir.iterdir() if p.is_dir())
        newest = {p.name for p in [r for r in runs if _RUN_RE.match(r.name)][-keep_last:]} if keep_last > 0 else set()
        for r in runs:
            reasons = []
            if served is None:
                reasons.append("registry_unreadable")
            elif served.get(mdir.name) == r.name:
                reasons.append("served")
            if not _RUN_RE.match(r.name):
                reasons.append("unknown")
            if r.name in newest:
                reasons.append("newest")
            if (now - _newest_mtime(r)) < min_age_days * 86400:
                reasons.append("young")
            if (mdir.name, r.name) in refs:
                reasons.append("ref")
            rows.append({"status": "kept" if reasons else "gc_candidate", "path": str(r), "model_id": mdir.name,
                         "run_id": r.name, "reasons": reasons, "bytes": _bytes(r)})
    cand = [x for x in rows if x["status"] == "gc_candidate"]
    summary = {"status": "retention_summary", "scanned": len(rows), "kept": len(rows) - len(cand), "candidates": len(cand),
               "reclaim_gb": round(sum(x["bytes"] for x in cand) / 1e9, 3),
               "kept_gb": round(sum(x["bytes"] for x in rows if x["status"] == "kept") / 1e9, 3),
               "registry_entries": n_entries, "registry_read": served is not None, "served_models": len(served or {}),
               "ref_pairs": len(refs), "keep_last": keep_last, "min_age_days": min_age_days}
    return rows, summary


def apply(rows: list[dict], experiments_root: Path) -> int:
    """Delete gc_candidate dirs, only inside *experiments_root*. Returns how many were removed."""
    root = experiments_root.resolve()
    n = 0
    for x in rows:
        if x["status"] != "gc_candidate":
            continue
        p = Path(x["path"]).resolve()
        if root not in p.parents or p.parent.parent != root:   # exactly <root>/<model>/<run>
            continue
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--experiments-root", default="ml/experiments-runs")
    ap.add_argument("--registry-root", default="ml/registry-store")
    ap.add_argument("--ref-roots", nargs="*", default=list(_DEFAULT_REF_ROOTS))
    ap.add_argument("--keep-last", type=int, default=14)
    ap.add_argument("--min-age-days", type=float, default=14.0)
    ap.add_argument("--list-kept", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    rows, summary = plan(Path(a.experiments_root), Path(a.registry_root), [Path(r) for r in a.ref_roots], a.keep_last, a.min_age_days)
    for x in rows:
        if x["status"] == "gc_candidate" or a.list_kept:
            print(json.dumps(x))
    summary["mode"] = "APPLIED" if a.apply else "report-only"
    if a.apply and summary["registry_read"]:
        summary["deleted"] = apply(rows, Path(a.experiments_root))
    print(json.dumps(summary))
    return 0 if summary["registry_read"] else 2


if __name__ == "__main__":
    sys.exit(main())
