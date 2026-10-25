#!/usr/bin/env python3
"""Giveback census — peak R vs realised R, and net R per capital-day, per strategy.

Programme 01 (docs/research/programmes/01-ACTIVE-TRADE-MANAGEMENT.md) question Q1.
The operator's top pain point (weekly planning 2026-10-14): trades go deep into
profit, pull back before the TP, churn, then stop out. Before any lever is
swept, the SIZE of that giveback has to be a measured number per leg, from the
live journal, with the population stated.

INPUTS — two tables of the trade journal, joined on ``order_package_id``:

* ``position_telemetry`` (M31): one row per package, UPSERTed on every exit
  pass; ``peak_r`` is the favourable extreme since entry, ``giveback_r`` is
  ``peak_r - open_r`` at the last write, ``terminal_state='final'`` when the
  close path stamped the terminal row. A row whose ``peak_state`` is set has
  NO peak (never collapse it to 0).
* ``trades``: the close record (``status``, ``pnl``, ``timestamp``,
  ``closed_at``, ``account_class``, ``strategy_name``, ``exit_reason``).

Read from a journal DB (``--db``, the trainer's synced copy) or from two JSON
dumps (``--telemetry-file`` / ``--trades-file``, the diag relay's
``/api/diag/position_telemetry`` and ``journal?table=trades``).

WHAT IT REPORTS, per (account_class, strategy) and pooled per account_class:

* ``n_closed``        closed trades with a telemetry row and a readable peak
* ``peak_r_p50/p75``  how far the trade ever got
* ``realised_r_p50``  where it closed (``open_r`` on a ``final`` row; else
                      ``pnl / risk_usd`` with ``risk_usd = risk_per_unit *
                      position_size`` — provenance recorded per row)
* ``giveback_r_mean`` peak minus realised, the number this census exists for
* ``giveback_share_of_peak`` sum(giveback) / sum(peak) over trades with peak>0
* ``deep_then_loss``  share of trades with peak_r >= 1.0 that closed <= 0
* ``net_r_per_capital_day`` sum(realised_r) / sum(hold_days) — the headline
                      measure of the weekly plan; hold_days from
                      ``timestamp``..``closed_at`` (size-unweighted; stated)

HONESTY RULES (each one a defect this refuses to commit):

1. Open trades are never graded: a telemetry row with no closed ``trades`` row
   is a PARTIAL peak, not an MFE (m31_mfe_parity rule 1). Counted as
   ``n_open_excluded``.
2. ``peak_r`` is a LOWER BOUND on MFE when ``peak_provenance`` is not
   ``measured`` (the exit pass samples the path at tick cadence). Reported.
3. Real / mirror / paper / prop are never pooled across ``account_class``.
4. A strategy with ``n_closed < --min-n`` is listed but carries
   ``read_state: insufficient_n``; the pooled class row is what is graded.
5. ``rejected`` / ``cancelled`` / reduce-leg rows are excluded (status filter).

The result is one research_result record per run (``--unit`` / ``--out``), with
``measurement.strategies`` carrying every row, so the decision rule reads the
landed record and never a stdout table.
"""
# wiring: dispatched by research/queue unit RQ-20261014-9807-01 (compute needs_vm_data) via
# research-script-run-trainer.yml; also runnable from a session on two diag pulls.
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research_result  # noqa: E402

RULE_ID = "RULE-RQ20261014-9807-01-GIVEBACK-CENSUS"
RULE_REGISTERED_AT = "2026-10-14"
CLOSED_STATUSES = {"closed", "filled_closed", "tp", "sl", "exit"}
EXCLUDED_STATUSES = {"rejected", "cancelled", "canceled", "superseded", "pending", "open"}


def _f(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def _ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pct(vals: List[float], q: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 4)


def load_db(path: str, since_days: Optional[int]) -> tuple[List[dict], List[dict]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    tel = [dict(r) for r in con.execute("SELECT * FROM position_telemetry")]
    q = "SELECT * FROM trades WHERE order_package_id IS NOT NULL"
    args: tuple = ()
    if since_days:
        q += " AND timestamp >= datetime('now', ?)"
        args = (f"-{int(since_days)} days",)
    tr = [dict(r) for r in con.execute(q, args)]
    con.close()
    return tel, tr


def load_json(telemetry_file: str, trades_file: str) -> tuple[List[dict], List[dict]]:
    def rows(p: str) -> List[dict]:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            for k in ("rows", "items", "data", "telemetry", "trades"):
                if isinstance(d.get(k), list):
                    return d[k]
        return d if isinstance(d, list) else []
    return rows(telemetry_file), rows(trades_file)


def census(tel: Iterable[dict], trades: Iterable[dict], min_n: int = 20) -> Dict[str, Any]:
    by_pkg: Dict[str, dict] = {}
    for t in trades:
        pid = t.get("order_package_id")
        st = str(t.get("status") or "").lower()
        if not pid or st in EXCLUDED_STATUSES:
            continue
        if t.get("closed_at") or t.get("exit_price") is not None or st in CLOSED_STATUSES:
            by_pkg[str(pid)] = t
    per: Dict[tuple, List[dict]] = {}
    n_open_excluded = n_no_peak = n_no_realised = 0
    for r in tel:
        pid = str(r.get("order_package_id") or "")
        t = by_pkg.get(pid)
        if t is None:
            n_open_excluded += 1
            continue
        peak = _f(r.get("peak_r"))
        # peak_state is the REASON a peak is absent ("thin_window", "unanchored", "no_risk"); a row whose peak
        # WAS measured carries the literal "measured" (src/runtime/trail_decay.py PEAK_MEASURED). Treating any
        # truthy state as "no peak" excluded every measured row -> read_state=no_data on a 591-row table.
        if peak is None or str(r.get("peak_state") or "").strip() not in ("", "measured"):
            n_no_peak += 1
            continue
        realised, prov = None, None
        if str(r.get("terminal_state") or "").lower() == "final" and _f(r.get("open_r")) is not None:
            realised, prov = _f(r.get("open_r")), "telemetry_final"
        else:
            rpu, size, pnl = _f(r.get("risk_per_unit")), _f(t.get("position_size")), _f(t.get("pnl"))
            if rpu and size and pnl is not None and rpu * size > 0:
                realised, prov = pnl / (rpu * size), "pnl_over_risk_usd"
        if realised is None:
            n_no_realised += 1
            continue
        t0, t1 = _ts(t.get("timestamp")), _ts(t.get("closed_at"))
        hold_days = (t1 - t0).total_seconds() / 86400.0 if (t0 and t1 and t1 > t0) else None
        key = (str(t.get("account_class") or r.get("account_id") or "unattributed"),
               str(t.get("strategy_name") or r.get("strategy") or "unattributed"))
        per.setdefault(key, []).append({
            "peak": peak, "realised": realised, "hold_days": hold_days, "prov": prov,
            "peak_lower_bound": str(r.get("peak_provenance") or "") != "measured",
            "exit_reason": t.get("exit_reason"),
        })

    def agg(rows: List[dict]) -> Dict[str, Any]:
        peaks = [x["peak"] for x in rows]
        real = [x["realised"] for x in rows]
        gb = [x["peak"] - x["realised"] for x in rows]
        deep = [x for x in rows if x["peak"] >= 1.0]
        held = [x for x in rows if x["hold_days"]]
        sum_hold = sum(x["hold_days"] for x in held)
        sum_peak = sum(p for p in peaks if p > 0)
        return {
            "n_closed": len(rows),
            "peak_r_p50": _pct(peaks, 0.5), "peak_r_p75": _pct(peaks, 0.75),
            "realised_r_p50": _pct(real, 0.5),
            "realised_r_mean": round(statistics.fmean(real), 4),
            "giveback_r_mean": round(statistics.fmean(gb), 4),
            "giveback_r_p50": _pct(gb, 0.5),
            "giveback_share_of_peak": round(sum(max(g, 0.0) for g in gb) / sum_peak, 4) if sum_peak > 0 else None,
            "deep_then_loss": round(sum(1 for x in deep if x["realised"] <= 0) / len(deep), 4) if deep else None,
            "n_deep": len(deep),
            "net_r_per_capital_day": round(sum(x["realised"] for x in held) / sum_hold, 4) if sum_hold > 0 else None,
            "n_with_hold": len(held),
            "peak_lower_bound_share": round(sum(1 for x in rows if x["peak_lower_bound"]) / len(rows), 4),
            "realised_provenance": {p: sum(1 for x in rows if x["prov"] == p) for p in sorted({x["prov"] for x in rows})},
        }

    strategies = []
    classes: Dict[str, List[dict]] = {}
    for (cls, strat), rows in sorted(per.items()):
        a = agg(rows)
        a.update({"account_class": cls, "strategy": strat,
                  "read_state": "measured" if len(rows) >= min_n else "insufficient_n"})
        strategies.append(a)
        classes.setdefault(cls, []).extend(rows)
    pooled = []
    for cls, rows in sorted(classes.items()):
        a = agg(rows)
        a.update({"account_class": cls, "read_state": "measured" if len(rows) >= min_n else "insufficient_n"})
        pooled.append(a)
    return {
        "strategies": strategies, "pooled_by_class": pooled, "min_n": min_n,
        "excluded": {"open_or_unmatched": n_open_excluded, "no_peak": n_no_peak, "no_realised_r": n_no_realised},
        "n_graded": sum(len(v) for v in per.values()),
        "definitions": {
            "giveback_r": "peak_r - realised_r per closed trade (R units, risk_per_unit basis)",
            "net_r_per_capital_day": "sum(realised_r)/sum(hold_days), hold from trades.timestamp to closed_at; size-UNWEIGHTED (stated, not fabricated)",
            "deep_then_loss": "share of trades with peak_r >= 1.0 whose realised_r <= 0",
        },
    }


def selftest() -> int:
    tel = [
        {"order_package_id": "a", "peak_r": 2.0, "peak_state": "measured", "open_r": 0.5, "terminal_state": "final", "peak_provenance": "measured", "risk_per_unit": 1},
        {"order_package_id": "b", "peak_r": 1.5, "open_r": -1.0, "terminal_state": "final", "peak_provenance": "estimated", "risk_per_unit": 1},
        {"order_package_id": "c", "peak_r": 0.4, "open_r": 0.1, "terminal_state": None, "peak_provenance": "estimated", "risk_per_unit": 2.0},
        {"order_package_id": "open", "peak_r": 3.0, "open_r": 2.0, "terminal_state": None, "peak_provenance": "estimated"},
        {"order_package_id": "nopeak", "peak_r": None, "peak_state": "thin_window"},
    ]
    tr = [
        {"order_package_id": "a", "status": "closed", "account_class": "real_money", "strategy_name": "s1", "timestamp": "2026-10-01T00:00:00Z", "closed_at": "2026-10-03T00:00:00Z", "pnl": 5.0, "position_size": 10},
        {"order_package_id": "b", "status": "closed", "account_class": "real_money", "strategy_name": "s1", "timestamp": "2026-10-01T00:00:00Z", "closed_at": "2026-10-02T00:00:00Z", "pnl": -10.0, "position_size": 10},
        {"order_package_id": "c", "status": "closed", "account_class": "paper", "strategy_name": "s2", "timestamp": "2026-10-01T00:00:00Z", "closed_at": "2026-10-01T12:00:00Z", "pnl": -4.0, "position_size": 10},
        {"order_package_id": "nopeak", "status": "closed", "account_class": "paper", "strategy_name": "s2", "timestamp": "2026-10-01T00:00:00Z", "closed_at": "2026-10-01T12:00:00Z", "pnl": 1.0, "position_size": 1},
        {"order_package_id": "rej", "status": "rejected", "account_class": "prop", "strategy_name": "s3"},
    ]
    c = census(tel, tr, min_n=2)
    s1 = next(s for s in c["strategies"] if s["strategy"] == "s1")
    assert s1["n_closed"] == 2 and s1["read_state"] == "measured", s1
    assert abs(s1["giveback_r_mean"] - 2.0) < 1e-9, s1          # (2-0.5 + 1.5-(-1)) / 2
    assert s1["deep_then_loss"] == 0.5 and s1["n_deep"] == 2, s1
    assert abs(s1["net_r_per_capital_day"] - (-0.5 / 3.0)) < 1e-3, s1  # (0.5 + -1.0) / (2 + 1) days, rounded to 4 dp
    assert s1["peak_lower_bound_share"] == 0.5, s1
    s2 = next(s for s in c["strategies"] if s["strategy"] == "s2")
    assert s2["read_state"] == "insufficient_n" and s2["realised_provenance"] == {"pnl_over_risk_usd": 1}, s2
    assert abs(s2["realised_r_p50"] - (-4.0 / 20.0)) < 1e-9, s2
    assert c["excluded"] == {"open_or_unmatched": 1, "no_peak": 1, "no_realised_r": 0}, c["excluded"]
    assert [p["account_class"] for p in c["pooled_by_class"]] == ["paper", "real_money"]
    # planted negative: a pooled-across-classes number must not exist
    assert not any(s.get("account_class") == "all" for s in c["pooled_by_class"])
    print("giveback_census selftest OK")
    return 0


def _sha() -> str:
    sha = os.environ.get("GITHUB_SHA", "")
    if sha:
        return sha
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=str(HERE), timeout=10).stdout.strip() or "sha_unavailable"
    except (OSError, subprocess.SubprocessError):
        return "sha_unavailable"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="trade journal DB (trainer synced copy); read-only")
    ap.add_argument("--telemetry-file", help="JSON dump of /api/diag/position_telemetry")
    ap.add_argument("--trades-file", help="JSON dump of journal?table=trades")
    ap.add_argument("--since-days", type=int, default=90)
    ap.add_argument("--min-n", type=int, default=20)
    ap.add_argument("--unit", default=os.environ.get("RESEARCH_UNIT") or None)
    ap.add_argument("--out", help="result dir; a research_result record is written under it")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    read_state, note = "measured", ""
    if a.db:
        tel, tr = load_db(a.db, a.since_days)  # a missing DB/table raises: the runner derives a producer_failed
    elif a.telemetry_file and a.trades_file:   # record from the non-zero exit (research-script-run*.yml), so a
        tel, tr = load_json(a.telemetry_file, a.trades_file)  # route fault is never swallowed into a verdict
    else:
        ap.error("give --db, or --telemetry-file with --trades-file")
    m = census(tel, tr, a.min_n)
    if not m.get("n_graded"):
        read_state, note = "no_data", "0 closed trades with a readable peak in the window"
    desc = (f"closed trades since {a.since_days}d with a position_telemetry row and a readable peak_r, "
            f"joined on order_package_id; per account_class x strategy, never pooled across classes")
    print(json.dumps({"read_state": read_state, "note": note, "n_graded": m.get("n_graded"),
                      "excluded": m.get("excluded"),
                      "pooled_by_class": m.get("pooled_by_class"), "strategies": m.get("strategies")}, indent=1))
    if a.out:
        rec = research_result.build(
            research_unit=a.unit, decision_rule_id=RULE_ID, decision_rule_registered_at=RULE_REGISTERED_AT,
            verdict="not_applicable" if read_state != "measured" else "pass",
            # a non-measured read_state REQUIRES population.n None (research_result.write refuses 0): "we did not
            # measure" must not be spelled as a measured-empty sample. The crash that made run 38540458035 exit 1.
            read_state=read_state, population_description=desc,
            n=m.get("n_graded") if read_state == "measured" else None,
            workflow=os.environ.get("GITHUB_WORKFLOW", "local"), run_id=os.environ.get("GITHUB_RUN_ID", "local"),
            commit_sha=_sha(), tool="scripts/research/giveback_census.py",
            # collapsed-state: not_applicable — kind: deterministic census; the power gate's seven states are
            # the dispatcher's to grade, this producer only stamps the one state a deterministic unit can carry
            power_state="not_applicable", measurement=m, artifact_store="research/results/",
            artifact_locator="this record: measurement.strategies / measurement.pooled_by_class",
            rows_landed=len(m.get("strategies", [])), note=note or "deterministic census; the rule reads pooled_by_class")
        p = research_result.write([rec], research_unit=a.unit, run_id=rec["produced_by"]["run_id"], root=Path(a.out))
        print(f"wrote {p}")
        # script_run.py's contract (docs there, "WHAT LANDS"): the landed record is derived from
        # <out_dir>/verdict.json. A green script that writes none lands as producer_failed ("outputs landed,
        # NOTHING GRADED") -- run 38630247072 did exactly that, exit 0 in 0.6 s, with this census correct.
        verdict = {
            "verdict": rec["verdict"], "read_state": read_state, "population": desc,
            "n": m.get("n_graded") if read_state == "measured" else None,
            "measurement": m,
            "note": note or "deterministic census; the rule reads pooled_by_class",
        }
        vp = Path(a.out) / "verdict.json"
        vp.write_text(json.dumps(verdict, indent=1, default=str) + "\n", encoding="utf-8")
        print(f"wrote {vp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
