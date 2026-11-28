#!/usr/bin/env python3
# wiring: research/queue/RQ-20261128-7e69-03.yaml (run.command; research-script-run.yml); tests/test_m16_longhistory.py. Row NO-WAIT-HAND-BUILDS (lane INFRA-BUILD-20261128).
"""M16 within-leg confidence vs full-cost R on a LONGER-HISTORY, INDEPENDENT eval set: the harness ledgers BEFORE the committed window.

WHY (row NO-WAIT-HAND-BUILDS, unit RQ-20260930-602 waits until 2026-12-23 for +500 ledger trades). The committed ledgers
(``comms/strategy_evidence/<leg>.json`` + their ``source_run``) are rolling 365-day harness windows (about 15 months for equities), so
a later re-run shares most trades with the first read and only the new trades are independent (602's own caveat). The harness does
not need to wait: ``scripts/ops/build_strategy_evidence.py --days N`` replays the SAME config over a longer history. This wrapper

  1. takes every leg whose committed summary is ``coverage_state: measured`` with a harness,
  2. rebuilds it over ``--days`` (default 1095) with the CURRENT committed config into ``<out>/evidence`` (never the committed dir),
  3. keeps a leg only if its rebuilt ``config_fingerprint`` equals the committed summary's (config-exact; the rest are LISTED, not graded),
  4. keeps, per leg, only trades with entry time BEFORE the committed window's ``reproduce.data_start``: the part of the new history
     that is NOT in the ledgers 601 read, so the eval set is independent of 601 (and past-only percentiles still use only earlier trades),
  5. grades with the UNCHANGED registered statistic and rule of ``m16_within_leg_confidence.grade`` (RULE-RQ0930-602-M16-CONFIRMATORY).

Tier-1 research; reads public Binance Vision / keyless bars through the harness, writes only ``--out``; no config, no order.

    python3 scripts/research/m16_longhistory.py --out O [--days 1095] [--workdir W] [--legs a,b] [--no-build --evidence-dir D]
    python3 scripts/research/m16_longhistory.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "ops"), str(REPO / "scripts" / "research")]
import m16_within_leg_confidence as M16  # noqa: E402

COMMITTED = REPO / "comms" / "strategy_evidence"
DEFAULT_DAYS = 1095


def committed_summaries(src: Path, only: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for f in sorted(src.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("coverage_state") != "measured" or not d.get("harness") or not d.get("source_run"):
            continue
        if only and f.stem not in only:
            continue
        out[f.stem] = d
    return out


def window_start(summary: Dict[str, Any]) -> Optional[pd.Timestamp]:
    """Start of the committed window (what 601 read): reproduce.data_start; None when absent (the leg is then not gradable)."""
    ds = (summary.get("reproduce") or {}).get("data_start")
    if not ds:
        return None
    t = pd.to_datetime(str(ds), utc=True, errors="coerce")
    return None if pd.isna(t) else t


def keep_before(legs: Dict[str, List[dict]], cutoffs: Dict[str, pd.Timestamp]) -> Dict[str, List[dict]]:
    """Per leg keep only trades with entry time strictly before that leg's committed window start (rows carry key 't')."""
    return {leg: [x for x in rows if x["t"] < cutoffs[leg]] for leg, rows in legs.items() if leg in cutoffs}


def select_config_exact(committed: Dict[str, Dict[str, Any]], rebuilt_dir: Path) -> tuple[List[str], Dict[str, str]]:
    """(legs whose rebuilt fingerprint == committed, {leg: why not})."""
    ok: List[str] = []
    why: Dict[str, str] = {}
    for leg, c in committed.items():
        f = rebuilt_dir / f"{leg}.json"
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            why[leg] = "rebuilt summary absent or unreadable"
            continue
        if r.get("coverage_state") != "measured":
            why[leg] = f"rebuilt coverage_state={r.get('coverage_state')!r}"
        elif r.get("config_fingerprint") != c.get("config_fingerprint"):
            why[leg] = "config fingerprint differs from the committed record (config changed since the committed window)"
        elif window_start(c) is None:
            why[leg] = "committed summary has no reproduce.data_start (cannot place the independent window)"
        else:
            ok.append(leg)
    return ok, why


def build(legs: List[str], days: int, evidence_out: Path, workdir: Path) -> int:
    import build_strategy_evidence as B  # noqa: PLC0415 (scripts/ops)
    argv = ["--days", str(days), "--out", str(evidence_out), "--workdir", str(workdir)]
    for leg in legs:
        argv += ["--strategy", leg]
    return int(B.main(argv) or 0)


def run(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    only = [x.strip() for x in a.legs.split(",") if x.strip()] or None
    committed = committed_summaries(COMMITTED, only)
    ev = Path(a.evidence_dir) if a.no_build else out / "evidence"
    if not a.no_build:
        work = Path(a.workdir) if a.workdir else out / "work"
        ev.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        rc = build(sorted(committed), a.days, ev, work)
        print(f"build_strategy_evidence rc={rc} for {len(committed)} legs", flush=True)
    ok, why = select_config_exact(committed, ev)
    legs, census = M16.load_legs(ev)
    legs = {k: v for k, v in legs.items() if k in ok}
    cut = {leg: window_start(committed[leg]) for leg in ok}
    pre = {k: len(v) for k, v in legs.items()}
    legs = keep_before(legs, cut)
    verdict = M16.grade(legs, census)
    verdict.update({
        "harness": "scripts/research/m16_longhistory.py", "days": a.days, "committed_dir": str(COMMITTED.relative_to(REPO)),
        "population_note": ("INDEPENDENT eval set: harness trades BEFORE each leg's committed window start (reproduce.data_start), rebuilt "
                            f"over {a.days} days with the current config; only legs whose config fingerprint equals the committed record's"),
        "legs_requested": sorted(committed), "legs_config_exact": sorted(ok), "legs_not_graded": why,
        "trades_rebuilt_per_leg": pre, "trades_before_window_per_leg": {k: len(v) for k, v in legs.items()},
        "window_start_by_leg": {k: str(v) for k, v in cut.items()},
    })
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=float) + "\n")
    print(json.dumps({k: verdict.get(k) for k in ("verdict", "read_state", "n", "population")}, indent=1, default=str))
    return 0


def _self_test() -> None:
    def row(day: int, c: float = 0.5, r: float = 0.1) -> dict:
        return {"c": c, "r": r, "t": pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(days=day)}
    legs = {"a": [row(d) for d in range(0, 60, 10)], "b": [row(d) for d in range(0, 60, 10)]}
    cut = {"a": pd.Timestamp("2025-01-31", tz="UTC")}
    kept = keep_before(legs, cut)
    assert set(kept) == {"a"} and [x["t"].day for x in kept["a"]] == [1, 11, 21], kept          # strictly before; b has no cutoff -> dropped
    assert all(x["t"] < cut["a"] for x in kept["a"])
    assert window_start({"reproduce": {"data_start": "2025-11-06 00:00:00+00:00"}}) == pd.Timestamp("2025-11-06", tz="UTC")
    assert window_start({"reproduce": {}}) is None and window_start({}) is None
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        committed = {"x": {"config_fingerprint": "f1", "reproduce": {"data_start": "2025-01-01"}},
                     "y": {"config_fingerprint": "f1", "reproduce": {"data_start": "2025-01-01"}},
                     "z": {"config_fingerprint": "f1", "reproduce": {}},
                     "w": {"config_fingerprint": "f1", "reproduce": {"data_start": "2025-01-01"}}}
        (d / "x.json").write_text(json.dumps({"coverage_state": "measured", "config_fingerprint": "f1"}))
        (d / "y.json").write_text(json.dumps({"coverage_state": "measured", "config_fingerprint": "OTHER"}))
        (d / "z.json").write_text(json.dumps({"coverage_state": "measured", "config_fingerprint": "f1"}))
        ok, why = select_config_exact(committed, d)
        assert ok == ["x"], (ok, why)
        assert "fingerprint differs" in why["y"] and "data_start" in why["z"] and "absent" in why["w"], why
    print("m16_longhistory self-test OK")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--workdir", default="")
    ap.add_argument("--legs", default="", help="comma list; default every committed measured leg with a harness")
    ap.add_argument("--no-build", action="store_true", help="grade an existing --evidence-dir instead of rebuilding")
    ap.add_argument("--evidence-dir", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if not a.out:
        ap.error("--out is required")
    if a.no_build and not a.evidence_dir:
        ap.error("--no-build needs --evidence-dir")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
