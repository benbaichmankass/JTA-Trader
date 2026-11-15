#!/usr/bin/env python3
"""RULE-EQ-FORMING-TQQQ-20261113: tqqq_trend_long_1d D20 vs D30 on the FORMING daily bar -- row EQ-FORMING-BAR-REPLAY.

WHY. Live ``tqqq_trend_long_1d`` (real money, alpaca_live + alpaca_portfolio) decides on the FORMING daily bar (no
``decision_bar`` key = the runtime default), but every Stage-0 number for it measured CLOSED-bar decisions, and since
#25228 its evidence record grades ``approximate`` for exactly that omitted lever. Operator 2026-11-13 08:02Z
(build_replay): "Keep forming; build an equity forming-bar replay first (days)".

WHAT ONE RUN DOES (one command, so the 1m data never leaves the runner's temp dir and never lands on main):
  1. ``equity_1m_source.py``: TQQQ 1Day + 1Min from Alpaca, the LIVE feed (``--feed``, default iex), the window DECLARED
     from what the source returned. The data lives in a temp dir.
  2. ``exit_lever_ablation.py --grade sweep``: arms D30 (donchian=30) and D20 (the shipped config, donchian=20), both
     through ``regime_debt_matrix.build_harness_cmd`` with ``--decision-bar forming --minutes-1m-csv --decision-session
     us_equity`` -- the evidence builder's own argv plus the forming replay -- over the whole source window, 4 folds,
     venue cost stack (fee 0 + 5 bps slippage, no funding), n floor 25.
  3. ``scripts/ops/build_strategy_evidence.py --data-csv --minutes-1m-csv --decision-session us_equity --folds 8``: the
     leg's record regenerated on the forming bar into ``<out>/evidence/`` (a session copies it to
     ``comms/strategy_evidence/`` after reading it; this script writes nothing outside ``--out``).
  4. Grades the rule below, unchanged, into ``<out>/verdict.json`` (E5).

THE RULE (registered 2026-11-13 ~09:35Z on the row, before any forming run; copied, not edited):
  (a) STAGE 0: net_r_oos(D20, forming) > 0, net of the full cost stack.  FAIL -> the closed-bar fallback #25691 goes
      to the operator.
  (b) D20 vs D30 on forming: PASS iff net_r(D20) - net_r(D30) >= 0 AND maxDD(D20) <= maxDD(D30) AND D20 wins >= 3 of
      4 folds.  FAIL -> a revert-to-30 proposal to the operator. Never automatic.
  (c) The regenerated record is faithful (closes the main-red exception).
  INDETERMINATE if n(D30) < 25.
Unit verdict (E5): indeterminate if n(D30) < 25; else fail if (a) fails; else fail if (b) fails; else pass.
(c) is reported beside it: it grades the record, not the edge.

``--sensitivity-feed sip`` (optional) re-runs step 2 on SIP bars and reports it beside the verdict. It is never graded.

Tier 1: research, offline. It changes no config, roster or order. ``--self-test`` runs offline on synthetic data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "scripts" / "research"
LEG = "tqqq_trend_long_1d"
SYMBOL = "TQQQ"
RULE_ID = "RULE-EQ-FORMING-TQQQ-20261113"
N_FLOOR, FOLDS, FOLD_MAJORITY, EVIDENCE_FOLDS = 25, 4, 3, 8


def _run(argv: List[str], log: Path) -> int:
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False,
                       env={**__import__("os").environ, "PYTHONPATH": str(REPO)})
    log.write_text((r.stdout or "")[-100_000:] + "\n--- stderr ---\n" + (r.stderr or "")[-100_000:], encoding="utf-8")
    return r.returncode


def sweep_argv(data_dir: Path, out: Path) -> List[str]:
    return [sys.executable, str(HERE / "exit_lever_ablation.py"), "--leg", LEG,
            "--data-csv", str(data_dir / f"{SYMBOL}_1d.csv"), "--minutes-1m-csv", str(data_dir / f"{SYMBOL}_1m.csv"),
            "--decision-session", "us_equity", "--arm", "D30=donchian=30", "--arm", "D20=",
            "--grade", "sweep", "--baseline", "D30", "--delta-r", "0", "--folds", str(FOLDS),
            "--fold-majority", str(FOLD_MAJORITY), "--n-floor", str(N_FLOOR), "--out", str(out)]


def evidence_argv(data_dir: Path, out: Path, workdir: Path) -> List[str]:
    return [sys.executable, str(REPO / "scripts" / "ops" / "build_strategy_evidence.py"), "--strategy", LEG,
            "--data-csv", str(data_dir / f"{SYMBOL}_1d.csv"), "--minutes-1m-csv", str(data_dir / f"{SYMBOL}_1m.csv"),
            "--decision-session", "us_equity", "--folds", str(EVIDENCE_FOLDS), "--out", str(out), "--workdir", str(workdir)]


def grade(sweep_summary: Optional[Dict[str, Any]], record: Optional[Dict[str, Any]], leg_donchian: Any) -> Dict[str, Any]:
    """The registered rule over the sweep summary (exit_lever_ablation summary.json) and the regenerated record."""
    out: Dict[str, Any] = {"rule": RULE_ID, "clauses": {}}
    arms = (sweep_summary or {}).get("arms") or {}
    d30, d20 = arms.get("D30"), arms.get("D20")
    if not d30 or not d20 or record is None:
        out.update(verdict="indeterminate", read_state="producer_failed",
                   why="a step produced no output (see the logs beside this verdict)")
        return out
    if str(leg_donchian) != "20":
        out.update(verdict="indeterminate", read_state="measured",
                   why=f"config/strategies.yaml {LEG}.donchian is {leg_donchian!r}, not 20: the rule's D20 arm is the "
                       "shipped config and the record would grade a different config")
        return out
    n30 = int(d30.get("n") or 0)
    out["n"] = {"D30": n30, "D20": int(d20.get("n") or 0)}
    if n30 < N_FLOOR:
        out.update(verdict="indeterminate", read_state="measured", why=f"n(D30)={n30} < {N_FLOOR}")
        return out
    net_oos = record.get("net_r_oos")
    a_pass = isinstance(net_oos, (int, float)) and net_oos > 0
    out["clauses"]["a_stage0"] = {"net_r_oos_D20_forming": net_oos, "pass": a_pass,
                                  "cross_check_sweep_D20_net_r": d20.get("net_r"),
                                  "on_fail": "the closed-bar fallback #25691 goes to the operator"}
    g = (sweep_summary or {}).get("grade") or {}
    cand = (g.get("candidates") or {}).get("D20") or {}
    b_pass = bool(cand.get("passes")) if cand else None
    out["clauses"]["b_d20_vs_d30"] = {
        "delta_net_r": round(float(d20["net_r"]) - float(d30["net_r"]), 4),
        "maxdd_D20": d20.get("max_drawdown_r"), "maxdd_D30": d30.get("max_drawdown_r"),
        "folds_D20": d20.get("folds"), "folds_D30": d30.get("folds"),
        "fold_wins_D20": cand.get("fold_wins"), "harness_grade": {k: g.get(k) for k in ("verdict", "label", "why")},
        "pass": b_pass,
        "on_fail": "a revert-to-30 proposal to the operator; never automatic"}
    out["clauses"]["c_record_faithful"] = {"fidelity": record.get("fidelity"),
                                           "omitted_levers": record.get("omitted_levers"),
                                           "pass": record.get("fidelity") == "faithful"}
    if not a_pass:
        out.update(verdict="fail", read_state="measured", why="(a) Stage 0 fails: net_r_oos(D20, forming) <= 0")
    elif b_pass is not True:
        out.update(verdict="fail", read_state="measured",
                   why=f"(b) D20 does not clear D30 on the forming bar (harness sweep grade {g.get('verdict')}: {g.get('label')})")
    else:
        out.update(verdict="pass", read_state="measured", why="(a) and (b) pass")
    return out


def _load(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run(out: Path, *, end: str, start: str, feed: str, sensitivity_feed: Optional[str],
        client_factory=None, keep_data: Optional[Path] = None) -> int:
    import yaml
    import equity_1m_source as src
    out.mkdir(parents=True, exist_ok=True)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    if client_factory is None:
        from alpaca_readonly import AlpacaReadOnly
        client_factory = AlpacaReadOnly.from_env
    tmp = Path(keep_data) if keep_data else Path(tempfile.mkdtemp(prefix="eq_forming_"))
    sources: Dict[str, Any] = {}
    data_dirs: Dict[str, Path] = {}
    for f in [feed] + ([sensitivity_feed] if sensitivity_feed and sensitivity_feed != feed else []):
        d = tmp / f
        try:
            sources[f] = src.build(client_factory(), SYMBOL, start, end, f, d)
            data_dirs[f] = d
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- recorded in source.json and the verdict says producer_failed
            sources[f] = {"error": f"{type(exc).__name__}: {exc}"}
    (out / "source.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    leg_donchian = (yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()).get("strategies", {})
                    .get(LEG, {}) or {}).get("donchian")
    summary = record = None
    exits: Dict[str, Any] = {}
    if feed in data_dirs:
        exits["sweep"] = _run(sweep_argv(data_dirs[feed], out / "sweep"), logs / "sweep.log")
        summary = _load(out / "sweep" / "summary.json")
        exits["evidence"] = _run(evidence_argv(data_dirs[feed], out / "evidence", out / "evidence_runs"),
                                 logs / "evidence.log")
        record = _load(out / "evidence" / f"{LEG}.json")
    sens = None
    if sensitivity_feed in data_dirs and sensitivity_feed != feed:
        exits["sweep_" + sensitivity_feed] = _run(sweep_argv(data_dirs[sensitivity_feed], out / f"sweep_{sensitivity_feed}"),
                                                  logs / f"sweep_{sensitivity_feed}.log")
        s = _load(out / f"sweep_{sensitivity_feed}" / "summary.json") or {}
        sens = {"feed": sensitivity_feed, "graded": False,
                "arms": {k: {kk: v.get(kk) for kk in ("n", "net_r", "max_drawdown_r", "folds")}
                         for k, v in (s.get("arms") or {}).items()}}
    g = grade(summary, record, leg_donchian)
    meta = sources.get(feed) or {}
    win = meta.get("returned") or {}
    verdict = {
        "verdict": g["verdict"], "read_state": g["read_state"],
        "population": (f"{LEG} on {SYMBOL}: decisions replayed on the FORMING daily bar from Alpaca {feed} 1m bars "
                       f"(cash-session ticks every 2 min), daily {win.get('daily_first')}..{win.get('daily_last')}, "
                       f"1m {win.get('m1_first')}..{win.get('m1_last')}; trades net of fee 0 + 5 bps slippage, no funding"),
        "n": (g.get("n") or {}).get("D30"),
        "measurement": {**g, "exit_codes": exits, "source_alignment": meta.get("alignment"),
                        "coverage_by_year": meta.get("coverage_by_year"), "sensitivity": sens},
        "note": g.get("why"),
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: verdict[k] for k in ("verdict", "read_state", "n", "note")}, indent=2))
    return 0 if g["read_state"] == "measured" else 1


def _self_test() -> int:
    import equity_1m_source as src
    import pandas as pd
    import numpy as np

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    # grade(): the rule's branches, with no subprocess.
    def arm(n, r, dd, f):
        return {"n": n, "net_r": r, "max_drawdown_r": dd, "folds": f}
    s_ok = {"arms": {"D30": arm(30, 5.0, 3.0, [1, 1, 1, 2]), "D20": arm(32, 6.0, 2.0, [2, 2, 2, 0])},
            "grade": {"verdict": "pass", "candidates": {"D20": {"passes": True, "fold_wins": 3}}}}
    rec = {"net_r_oos": 6.0, "fidelity": "faithful", "omitted_levers": []}
    check("pass when (a) and (b) pass", grade(s_ok, rec, 20)["verdict"] == "pass")
    check("fail when Stage 0 fails", grade(s_ok, {**rec, "net_r_oos": -0.1}, 20)["verdict"] == "fail")
    s_bfail = {**s_ok, "grade": {"verdict": "fail", "candidates": {"D20": {"passes": False, "fold_wins": 1}}}}
    check("fail when (b) fails", grade(s_bfail, rec, 20)["verdict"] == "fail")
    s_low = {**s_ok, "arms": {**s_ok["arms"], "D30": arm(24, 5.0, 3.0, [1, 1, 1, 2])}}
    check("indeterminate when n(D30) < 25", grade(s_low, rec, 20)["verdict"] == "indeterminate")
    check("indeterminate when the shipped donchian is not 20", grade(s_ok, rec, 30)["verdict"] == "indeterminate")
    check("producer_failed when a step wrote nothing", grade(None, rec, 20)["read_state"] == "producer_failed")
    check("(c) reported, not graded into the verdict",
          grade(s_ok, {**rec, "fidelity": "approximate"}, 20)["verdict"] == "pass")

    # run(): end to end on a synthetic fake Alpaca source (real subprocesses, offline).
    rng = np.random.default_rng(3)
    daily, minutes, p = [], [], 50.0
    for d in pd.bdate_range("2022-01-03", "2023-06-30"):
        t0 = pd.Timestamp(f"{d.date()} 09:30", tz=src.US_TZ).tz_convert("UTC")
        o, hs, ls = p, [], []
        for k in range(0, 390, 5):
            c = p * (1 + rng.normal(0.00004, 0.002))
            h, lo = max(p, c) * 1.0004, min(p, c) * 0.9996
            minutes.append({"t": (t0 + pd.Timedelta(minutes=k)).isoformat(), "o": p, "h": h, "l": lo, "c": c, "v": 1})
            hs.append(h)
            ls.append(lo)
            p = c
        daily.append({"t": pd.Timestamp(str(d.date()), tz=src.US_TZ).tz_convert("UTC").isoformat(),
                      "o": o, "h": max(hs), "l": min(ls), "c": p, "v": 78})
    with tempfile.TemporaryDirectory() as td:
        rc = run(Path(td) / "out", end="2023-07-01", start="2022-01-01", feed="iex", sensitivity_feed=None,
                 client_factory=lambda: src._FakeClient(daily, minutes))
        v = json.loads((Path(td) / "out" / "verdict.json").read_text())
        check("end-to-end run measured (exit 0) and wrote an E5 verdict", rc == 0 and v["read_state"] == "measured")
        check("the source window is declared in the population", "2022-01-03" in v["population"])
        ev = json.loads((Path(td) / "out" / "evidence" / f"{LEG}.json").read_text())
        check("the regenerated record models the forming bar and is faithful",
              ev.get("fidelity") == "faithful" and (ev.get("reproduce") or {}).get("inputs", {}).get("decision_bar_modelled") == "forming")
        check("no 1m data under --out", not list((Path(td) / "out").rglob("*_1m.csv")))
    print("self-test passed")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--end", help="ISO date: the source window's upper bound (fixed in the unit before the run)")
    ap.add_argument("--start", default="2015-01-01", help="ISO date; the source returns what it has from here")
    ap.add_argument("--feed", choices=("iex", "sip"), default="iex")
    ap.add_argument("--sensitivity-feed", choices=("iex", "sip"), default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    if a.self_test:
        return _self_test()
    if not (a.out and a.end):
        ap.error("--out and --end are required")
    return run(Path(a.out), end=a.end, start=a.start, feed=a.feed, sensitivity_feed=a.sensitivity_feed)


if __name__ == "__main__":
    sys.exit(main())
