#!/usr/bin/env python3
# wiring: research/queue units declaring run.command ["python3","scripts/research/macro_event_study_run.py",...]
#         via .github/workflows/research-script-run.yml (the runner has internet; the sandbox does not)
"""Queue-dispatchable economic-surprise -> forward-return event study, graded by a REGISTERED rule.

WHY (QUEUE-FILL-1013B, 2026-10-13)
----------------------------------
``scripts/macro/econ_event_study.py`` measures IC(surprise, forward return) but is wired only to
``econ-event-study.yml``: one snapshot file, a hard-coded scorecard path, no ``verdict.json``. Its forward
scorecards sit at n=13-17 releases because they read the daily forward feed only, while the survey and
model-expectation backfills already hold 550-3000 point-in-time releases per kind (macro-research
invariant 4: establish what bounds n before waiting for accrual). This wrapper:

  1. reads SEVERAL snapshot files at once (``load_resolved_events_multi``: one row per release date, the
     defined-surprise / earliest-``observed_at`` row wins -- never a later revised consensus),
  2. fetches the daily-close panel off-VM (yfinance then Stooq, the shared fetcher),
  3. runs the existing ``event_study`` + ``summarize``,
  4. applies the unit's pre-registered rule to the PRE-REGISTERED horizons only and writes ``verdict.json``
     in the shape ``script_run.py`` lands as an E5 record.

Rule (the machine form of the unit's ``decision_rule.rule``; both are committed before any run)::

    PASS            some primary horizon has n_eff-corrected |ic_t_eff| >= --t-bar with n >= --min-n AND
                    sign(ic) matches --expected-sign
    FAIL            every primary horizon has n >= --min-n and none reaches --t-bar in the expected sign
                    (a significant WRONG-sign horizon is reported in the note; it is not a pass)
    INDETERMINATE   any primary horizon has n < --min-n (the source, not the hypothesis, bounded the test)
    producer_failed / no_data   no price bars, or no joined releases -- never a verdict

Tier-1 research tooling. Reads committed snapshots + public prices, writes only ``--out``. No order path.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts" / "macro")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _csv(s: Optional[str]) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def grade(rows: List[Dict[str, Any]], *, primary: List[int], min_n: int, t_bar: float,
          expected_sign: str) -> Dict[str, Any]:
    """Apply the registered rule to ``event_study`` rows. Pure; unit-tested."""
    by_h = {int(r["horizon_days"]): r for r in rows}
    per: List[Dict[str, Any]] = []
    for h in primary:
        r = by_h.get(h)
        n = int(r["n"]) if r and r.get("n") is not None else 0
        t = r.get("ic_t_eff") if r else None
        ic = r.get("ic") if r else None
        sign_ok = (ic is not None and (expected_sign == "either"
                                       or (expected_sign == "negative" and ic < 0)
                                       or (expected_sign == "positive" and ic > 0)))
        reached = bool(t is not None and abs(t) >= t_bar)
        per.append({"horizon_days": h, "n": n, "ic": ic, "ic_t_eff": t, "n_ok": n >= min_n,
                    "t_reached": reached, "sign_ok": bool(sign_ok)})
    if not any(p["n"] for p in per):
        return {"verdict": "not_applicable", "read_state": "no_data", "per_horizon": per,
                "note": "no joined releases at any primary horizon (price join or snapshot filter empty)"}
    if any(not p["n_ok"] for p in per):
        return {"verdict": "indeterminate", "read_state": "measured", "per_horizon": per,
                "note": f"a primary horizon has n < {min_n}: the source bounded the test, not the hypothesis"}
    if any(p["t_reached"] and p["sign_ok"] for p in per):
        return {"verdict": "pass", "read_state": "measured", "per_horizon": per,
                "note": "a pre-registered horizon reached the t-bar in the expected sign (evidence for a build row, "
                        "not a leg: costs, tradeable timing and a placebo are still owed)"}
    wrong = [p["horizon_days"] for p in per if p["t_reached"] and not p["sign_ok"]]
    return {"verdict": "fail", "read_state": "measured", "per_horizon": per,
            "note": "no pre-registered horizon reached the t-bar in the expected sign"
                    + (f"; WRONG-sign significance at horizons {wrong} (not registered, not a pass)" if wrong else "")}


def _ensure_yfinance() -> None:
    try:
        importlib.import_module("yfinance")
    except ImportError:  # the runner image installs numpy/pandas/pyyaml/requests only
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yfinance>=0.2.40"], check=False)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--kind", required=True)
    ap.add_argument("--snapshots", required=True, help="CSV of comms/macro/*.jsonl paths (merged PIT)")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--candles-dir", default=None, help="tests / offline: dir of <SYMBOL>.csv; default off-VM fetch")
    ap.add_argument("--horizons", default="1,3,5")
    ap.add_argument("--primary-horizons", default=None, help="default: all --horizons")
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--t-bar", type=float, default=2.4)
    ap.add_argument("--expected-sign", choices=["negative", "positive", "either"], default="either")
    ap.add_argument("--value-key", default="surprise")
    ap.add_argument("--population", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    ees = importlib.import_module("econ_event_study")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    horizons = [int(x) for x in _csv(a.horizons)]
    primary = [int(x) for x in _csv(a.primary_horizons)] or horizons
    symbol = a.symbol or ees.KIND_DEFAULT_SYMBOL.get(a.kind)
    snaps = _csv(a.snapshots)

    def _emit(v: Dict[str, Any]) -> int:
        (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n")}))
        return 0

    pop = a.population or f"{a.kind} releases joined to {symbol} daily closes"
    if not symbol:
        return _emit({"verdict": "not_applicable", "read_state": "producer_failed", "population": pop, "n": 0,
                      "note": f"no price symbol for kind={a.kind}; pass --symbol"})
    events = ees.load_resolved_events_multi(snaps, a.kind)
    with_value = [e for e in events if e.get(a.value_key) is not None]
    if a.candles_dir:
        panel = ees._resolve_panel(symbol, a.candles_dir)
    else:
        os.environ.setdefault("ICT_OFFVM_BUILD_HOST", "1")
        _ensure_yfinance()
        fmc = importlib.import_module("fetch_macro_candles")
        download, stooq = fmc._resolve_fetchers(None, None, "2005-01-01")
        panel = fmc.symbol_close_pairs(symbol, download=download, stooq_urlopen=stooq)
    meas: Dict[str, Any] = {"kind": a.kind, "symbol": symbol, "snapshot_files": snaps, "releases": len(events),
                            "releases_with_value": len(with_value), "price_bars": len(panel),
                            "first_release": events[0]["date"] if events else None,
                            "last_release": events[-1]["date"] if events else None}
    if not panel or not with_value:
        return _emit({"verdict": "not_applicable", "read_state": "no_data", "population": pop, "n": len(with_value),
                      "measurement": meas, "note": "empty price panel or zero releases with a defined surprise: "
                      "the join measured NOTHING (vacuous, not thin)"})
    rows = ees.event_study(events, panel, horizons=horizons, value_key=a.value_key)
    summary = ees.summarize(rows, t_flag=2.0, min_honest_n=12)
    g = grade(rows, primary=primary, min_n=a.min_n, t_bar=a.t_bar, expected_sign=a.expected_sign)
    n_max = max((int(r["n"]) for r in rows if r.get("n") is not None), default=0)
    meas.update({"rows": rows, "summary": summary, "rule": {"primary": primary, "min_n": a.min_n, "t_bar": a.t_bar,
                                                            "expected_sign": a.expected_sign},
                 "per_horizon": g["per_horizon"]})
    (out / "scorecard.json").write_text(json.dumps({"rows": rows, "summary": summary, "meta": meas}, indent=2,
                                                   default=str) + "\n", encoding="utf-8")
    return _emit({"verdict": g["verdict"], "read_state": g["read_state"], "population": pop, "n": n_max,
                  "measurement": meas, "note": g["note"]})


if __name__ == "__main__":
    raise SystemExit(main())
