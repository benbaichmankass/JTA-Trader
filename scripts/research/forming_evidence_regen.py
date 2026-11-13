#!/usr/bin/env python3
"""Regenerate forming-decision legs' Stage-0 evidence records on the FORMING bar -- rows CRYPTO-FORMING-RDM-FORWARD and
CRYPTO-FORMING-EQUITY-REGEN.

WHY. Since #25228 regime_debt_matrix lists ``decision_bar`` as an omitted lever for every trend/pullback leg whose live
decision bar is forming (explicit or absent = the runtime default). Records written before that read ``faithful`` without
ever modelling the forming bar, so their next regeneration flips them ``approximate`` -- exactly what happened to
tqqq_trend_long_1d (fixed by RQ-20261113-1449-01). #25710 added ``build_harness_cmd(forming_1m=...)``; this PR extends
it to the pullback harness and this script regenerates the records with it.

TWO SOURCES (any other leg is refused with a stated reason, never silently skipped):
  * ``binance``  -- crypto: leg-timeframe candles through regime_debt_matrix's own fetch (the evidence builder's), 1m from
    Binance-vision over the same window (``scripts/ops/fetch_backtest_candles.py --interval 1``).
  * ``us_equity_daily`` -- a Yahoo-fed 1d US ETF leg: 1Day AND 1Min from ONE source, Alpaca iex (the live feed), through
    ``equity_1m_source.build`` (the RQ-20261113-1449-01 path), replayed with ``--decision-session us_equity``. Alpaca iex
    history starts 2020-07, so a record window reaching further back is CUT to what the source returned; the window used is
    read off the data and reported per leg, never assumed.
  * ``us_equity_intraday`` -- a Yahoo-fed 1h US equity leg: Alpaca iex ``1Hour`` (clock-aligned, extended hours kept --
    the bars live reads; NOT the Yahoo RTH :30-aligned bars behind the closed-bar record) + 1Min, replayed with
    ``--decision-session us_equity_intraday`` (ticks masked to the cash session; forming_bar_entries US-INTRADAY MODE).
  Refused with a reason: a futures leg (Yahoo ``=F`` ticker; no 1m source the runner can read) and any other intraday
  timeframe.

PER LEG:
  1. the window = the committed record's own reproduce.data_start..data_end (else its window_days back from ``--end``);
  2. the leg-timeframe CSV and the 1m CSV into a temp dir -- never under ``--out``;
  3. ``scripts/ops/build_strategy_evidence.py --strategy LEG --data-csv --minutes-1m-csv [--decision-session us_equity]
     --folds <record's>`` into ``<out>/evidence/`` (records) and ``<out>/evidence_runs/`` (trades + bt.json, the records'
     source_run);
  4. RULE-D1 on the regenerated record (net_r_oos > 0, net of the full cost stack), beside the committed record's
     closed-bar number.

``<out>/verdict.json`` (E5) fans out one record per leg (``records``). Unit verdict: indeterminate if any leg could not be
measured or did not regenerate faithful; else fail if any leg fails RULE-D1 on the forming bar; else pass. The rule is the
unit's, registered before the run. The records land in comms/strategy_evidence/ only through a later PR a session opens
after reading them.

Tier 1: research tooling; writes only under --out (and a temp dir).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "scripts" / "research"
for _p in (REPO, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

EVIDENCE = REPO / "comms" / "strategy_evidence"


def _run(argv: List[str], log: Path) -> int:
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(REPO)})
    with log.open("a", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(argv) + "\n" + (r.stdout or "")[-50_000:] + "\n--- stderr ---\n"
                 + (r.stderr or "")[-50_000:] + "\n")
    return r.returncode


def leg_window(rec: Dict[str, Any]) -> Dict[str, Any]:
    rp = rec.get("reproduce") or {}
    return {"data_start": rp.get("data_start"), "data_end": rp.get("data_end"),
            "window_days": rp.get("window_days") or rec.get("window_days") or 365,
            "folds": rp.get("folds") or rec.get("folds") or 8}


def source_mode(feed: Dict[str, Any], timeframe: str) -> str:
    """"binance" | "us_equity_daily" | "skip:<reason>" -- which 1m source can replay this leg's forming bar."""
    src = feed.get("source")
    if src == "binance":
        return "binance"
    if src == "yahoo":
        if str(feed.get("ticker", "")).endswith("=F"):
            return f"skip:futures ticker {feed.get('ticker')!r}: no 1m source the research runner can read"
        if timeframe == "1d":
            return "us_equity_daily"
        if timeframe == "1h":
            return "us_equity_intraday"
        return (f"skip:{timeframe} US equity leg: the intraday forming mode covers Alpaca 1Hour only "
                "(row CRYPTO-FORMING-EQUITY-REGEN)")
    return f"skip:feed {src!r}: no forming-bar 1m source"


def plan(legs: List[str]) -> List[Dict[str, Any]]:
    import yaml
    import regime_debt_matrix as rdm
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    cfgs = cfgs.get("strategies", cfgs)
    out = []
    for leg in legs:
        cfg = cfgs.get(leg)
        row: Dict[str, Any] = {"leg": leg}
        if not isinstance(cfg, dict) or not cfg.get("symbols") or not cfg.get("timeframe"):
            row["skip"] = "not a config/strategies.yaml leg with symbols + timeframe"
        else:
            feed = rdm.resolve_feed(cfg["symbols"][0], cfg["timeframe"])
            harness = rdm.classify(cfg)
            forming = str(cfg.get("decision_bar") or "forming").lower() != "closed"
            rec_p = EVIDENCE / f"{leg}.json"
            rec = json.loads(rec_p.read_text()) if rec_p.exists() else {}
            row.update(symbol=cfg["symbols"][0], timeframe=cfg["timeframe"], feed=feed, harness=harness,
                       committed={k: rec.get(k) for k in ("fidelity", "omitted_levers", "net_r_oos", "n_trades_oos")},
                       **leg_window(rec))
            row["mode"] = source_mode(feed, cfg["timeframe"])
            if row["mode"].startswith("skip:"):
                row["skip"] = row["mode"][5:]
            elif harness not in ("trend", "pullback"):
                row["skip"] = f"harness {harness!r}: forming_1m is forwarded for trend + pullback only"
            elif not forming:
                row["skip"] = "decision_bar: closed -- nothing forming to model"
        out.append(row)
    return out


def _window(row: Dict[str, Any], end_pin: Optional[str]):
    import pandas as pd
    now = pd.to_datetime(end_pin, utc=True) if end_pin else pd.Timestamp.now(tz="UTC")
    start = pd.to_datetime(row["data_start"], utc=True) if row.get("data_start") else now - pd.Timedelta(days=int(row["window_days"]))
    end = pd.to_datetime(row["data_end"], utc=True) if row.get("data_end") else now
    return start, end


def _window_read(csv: Path) -> Optional[List[str]]:
    """The window the trimmed leg CSV actually holds -- read off the data, never the request."""
    import pandas as pd
    try:
        ts = pd.to_datetime(pd.read_csv(csv, usecols=["timestamp"])["timestamp"], utc=True)
    except Exception:  # noqa: BLE001  # allow-silent: None is reported as an unreadable window, and the leg then fails measured
        return None
    return [str(ts.min()), str(ts.max())] if len(ts) else None


def fetch(row: Dict[str, Any], tmp: Path, log: Path, m1_cache: Dict[str, Path], end_pin: Optional[str] = None,
          client_factory=None) -> Optional[str]:
    """Write <tmp>/<leg>__data.csv (leg tf) and a 1m CSV covering the window from the leg's source. None or an error.

    A record without reproduce.data_start/data_end is windowed as window_days back from ``end_pin`` (the unit pins it, so a
    re-run reads the same bars), else from now."""
    if row.get("mode") in ("us_equity_daily", "us_equity_intraday"):
        return _fetch_us_equity(row, tmp, log, m1_cache, end_pin, client_factory)
    return _fetch_binance(row, tmp, log, m1_cache, end_pin)


def _fetch_binance(row, tmp, log, m1_cache, end_pin) -> Optional[str]:
    import pandas as pd
    import regime_debt_matrix as rdm
    start, end = _window(row, end_pin)
    days = int((pd.Timestamp.now(tz="UTC") - start).days) + 3
    data = tmp / f"{row['leg']}__data.csv"
    try:
        rdm._fetch_csv(row["feed"], days, str(data))
    except Exception as exc:  # noqa: BLE001  # allow-silent: returned as the leg's error and landed in verdict.json
        return f"leg candles: {type(exc).__name__}: {exc}"
    rdm.trim_csv_to_window(str(data), str(start), str(end), row["timeframe"])
    row["window_used"] = _window_read(data)
    sym = row["symbol"]
    s1, e1 = (start - pd.Timedelta(days=2)).strftime("%Y-%m-%d"), (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    key = f"{sym}__{s1}__{e1}"  # per window: legs on one symbol carry different windows (sol 365d vs sol_prop 2170d)
    have = m1_cache.get(key)
    if have is None or not have.exists():
        m1 = tmp / f"{key}__1m.csv"
        rc = _run([sys.executable, str(REPO / "scripts/ops/fetch_backtest_candles.py"), "--symbol", sym, "--interval", "1",
                   "--start-date", s1, "--end-date", e1, "--output", str(m1), "--source", "binance_vision"], log)
        if rc != 0 or not m1.exists():
            return f"1m fetch for {sym} {s1}..{e1} exited {rc}"
        m1_cache[key] = m1
    row["m1_csv"] = str(m1_cache[key])
    row["data_csv"] = str(data)
    return None


def _fetch_us_equity(row, tmp, log, m1_cache, end_pin, client_factory) -> Optional[str]:
    """Alpaca iex bars + 1Min through equity_1m_source.build (one source for both CSVs, the live feed): 1Day for a
    daily leg (session-DATE stamps), 1Hour for an intraday leg (clock-aligned, extended hours kept -- what live reads)."""
    import pandas as pd
    import equity_1m_source as eqs
    import regime_debt_matrix as rdm
    start, end = _window(row, end_pin)
    sym = row["symbol"]
    s1, e1 = (start - pd.Timedelta(days=2)).strftime("%Y-%m-%d"), (end + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    intraday = row.get("mode") == "us_equity_intraday"
    bar_tf, tag = ("1Hour", "1h") if intraday else ("1Day", "1d")
    key = f"eq{tag}__{sym}__{s1}__{e1}"
    d = tmp / key
    if key not in m1_cache:
        if client_factory is None:
            from alpaca_readonly import AlpacaReadOnly
            client_factory = AlpacaReadOnly.from_env
        try:
            meta = eqs.build(client_factory(), sym, s1, e1, "iex", d, bar_tf=bar_tf)
        except Exception as exc:  # noqa: BLE001  # allow-silent: returned as the leg's error and landed in verdict.json
            return f"alpaca {bar_tf}/1Min for {sym}: {type(exc).__name__}: {exc}"
        m1_cache[key] = d / f"{sym}_1m.csv"
        with log.open("a", encoding="utf-8") as fh:  # the build's own record, beside the harness runs' argv
            fh.write(f"equity_1m_source.build {sym} {bar_tf} iex {s1}..{e1}: returned {meta.get('returned')} "
                     f"rows {meta.get('rows')} alignment chosen={(meta.get('alignment') or {}).get('chosen')}\n")
    data = tmp / f"{row['leg']}__data.csv"
    shutil.copyfile(d / f"{sym}_{tag}.csv", data)
    rdm.trim_csv_to_window(str(data), str(start), str(end), row["timeframe"])
    row["window_used"] = _window_read(data)
    row["decision_session"] = "us_equity_intraday" if intraday else "us_equity"
    row["source"] = f"alpaca iex {bar_tf} + 1Min (equity_1m_source.build)"
    try:
        sm = json.loads((d / "source.json").read_text())
        row["source_meta"] = {k: sm.get(k) for k in ("feed", "bar_tf", "returned", "rows", "alignment")}
    except (OSError, ValueError):
        row["source_meta"] = None  # reported as missing provenance beside the leg, never as a clean source
    row["m1_csv"] = str(m1_cache[key])
    row["data_csv"] = str(data)
    return None


def regen(row: Dict[str, Any], out: Path, log: Path) -> Dict[str, Any]:
    argv = [sys.executable, str(REPO / "scripts/ops/build_strategy_evidence.py"), "--strategy", row["leg"],
            "--data-csv", row["data_csv"], "--minutes-1m-csv", row["m1_csv"], "--folds", str(row["folds"]),
            "--out", str(out / "evidence"), "--workdir", str(out / "evidence_runs")]
    if row.get("decision_session"):
        argv += ["--decision-session", row["decision_session"]]
    rc = _run(argv, log)
    rec_p = out / "evidence" / f"{row['leg']}.json"
    if rc != 0 or not rec_p.exists():
        return {"error": f"build_strategy_evidence exited {rc}"}
    return json.loads(rec_p.read_text())


def leg_record(row: Dict[str, Any], rec: Optional[Dict[str, Any]], err: Optional[str], n_floor: int = 0) -> Dict[str, Any]:
    leg = row["leg"]
    base = {"leg": leg, "committed": row.get("committed"), "window": row.get("window_used"),
            "requested_window": [row.get("data_start"), row.get("data_end"), row.get("window_days")],
            "source": row.get("source") or ("binance-vision 1m" if row.get("mode") == "binance" else None),
            "source_meta": row.get("source_meta")}
    if row.get("skip"):
        return {**base, "verdict": "not_applicable", "read_state": "not_attempted", "n": None,
                "population": f"{leg}: not regenerated -- {row['skip']}", "note": row["skip"]}
    if err or rec is None or rec.get("error") or rec.get("coverage_state") != "measured":
        why = err or (rec or {}).get("error") or f"coverage_state {(rec or {}).get('coverage_state')}"
        return {**base, "verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                "population": f"{leg}: regeneration failed -- nothing measured", "note": str(why)[:400]}
    faithful = rec.get("fidelity") == "faithful" and not rec.get("omitted_levers")
    net = rec.get("net_r_oos")
    n = rec.get("n_trades_oos")
    below = None
    if not faithful:
        v, note = "indeterminate", f"regenerated record is {rec.get('fidelity')} (omits {rec.get('omitted_levers')})"
    elif n_floor and not (isinstance(n, int) and n >= n_floor):
        below = True
        v, note = "indeterminate", (f"record regenerated faithful, but n {n} < the unit's n floor {n_floor}: no RULE-D1 claim "
                                    f"(forming-bar net_r_oos {net}; committed closed-bar {row['committed'].get('net_r_oos')} "
                                    f"over n {row['committed'].get('n_trades_oos')})")
    else:
        v = "pass" if isinstance(net, (int, float)) and net > 0 else "fail"
        note = (f"forming-bar net_r_oos {net} over n {n} (committed closed-bar record: {row['committed'].get('net_r_oos')} "
                f"over n {row['committed'].get('n_trades_oos')}); RULE-D1 -> {v.upper()}")
    return {**base, "verdict": v, "read_state": "measured", "n": n, "below_n_floor": below,
            "population": f"{leg}: Stage-0 re-measure on the FORMING bar ({row.get('source') or 'Binance-vision 1m'}), "
                          f"window read off the data {row.get('window_used')}, net of the harness cost stack",
            "measurement": {k: rec.get(k) for k in ("fidelity", "omitted_levers", "net_r_oos", "n_trades_oos", "folds",
                                                     "folds_positive", "cost_stack", "path_stats")},
            "note": note}


def assemble(records: List[Dict[str, Any]], legs: List[str]) -> Dict[str, Any]:
    tried = [r for r in records if r["read_state"] != "not_attempted"]
    measured = [r for r in tried if r["read_state"] == "measured"]
    if not tried:
        top, why = "not_applicable", "no leg in scope"
    elif len(measured) < len(tried) or any(r["verdict"] == "indeterminate" and not r.get("below_n_floor") for r in measured):
        top, why = "indeterminate", "a leg could not be measured or did not regenerate faithful"
    elif all(r.get("below_n_floor") for r in measured):
        top, why = "indeterminate", "every leg regenerated faithful but none reaches the n floor -- no RULE-D1 claim"
    elif any(r["verdict"] == "fail" for r in measured):
        top, why = "fail", "a leg fails RULE-D1 on the forming bar: " + ", ".join(r["leg"] for r in measured if r["verdict"] == "fail")
    else:
        top, why = "pass", "every leg clears RULE-D1 on the forming bar"
    return {"verdict": top, "read_state": "measured" if measured else "producer_failed",
            "population": f"forming-decision legs {legs}, each re-measured on the forming bar over its record's window "
                          f"(cut to the source's history where shorter, reported per leg)",
            "n": sum(int(r["n"]) for r in measured if isinstance(r.get("n"), int)) if measured else None,
            "note": why, "records": records}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", action="append", default=[])
    ap.add_argument("--out")
    ap.add_argument("--n-floor", type=int, default=0,
                    help="a faithful leg with n_trades_oos below this reads indeterminate (no RULE-D1 claim) and does not "
                         "drive the unit verdict; its record still regenerates (default 0 = no floor)")
    ap.add_argument("--end", help="pin the window end for records without reproduce.data_end (YYYY-MM-DD)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not (a.leg and a.out):
        ap.error("--leg (repeat) and --out are required")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = out / "regen.log"
    tmp = Path(tempfile.mkdtemp(prefix="forming_regen_"))
    rows = plan(a.leg)
    (out / "plan.json").write_text(json.dumps(rows, indent=1, default=str))
    m1_cache: Dict[str, Path] = {}
    records = []
    for row in rows:
        rec = err = None
        if not row.get("skip"):
            err = fetch(row, tmp, log, m1_cache, a.end)
            if err is None:
                rec = regen(row, out, log)
        records.append(leg_record(row, rec, err, a.n_floor))
        print(f"{row['leg']}: {records[-1]['verdict']} / {records[-1]['read_state']} -- {records[-1]['note'][:160]}", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    v = assemble(records, a.leg)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str))
    return 0 if v["read_state"] == "measured" else 1


def _self_test() -> int:
    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            raise SystemExit(1)

    row = {"leg": "L", "committed": {"net_r_oos": 5.0, "n_trades_oos": 50}, "window_used": ["a", "b"]}
    ok = {"coverage_state": "measured", "fidelity": "faithful", "omitted_levers": [], "net_r_oos": 3.2, "n_trades_oos": 48}
    check("faithful + positive -> pass", leg_record(row, ok, None)["verdict"] == "pass")
    check("faithful + negative -> fail", leg_record(row, {**ok, "net_r_oos": -1.0}, None)["verdict"] == "fail")
    check("still approximate -> indeterminate",
          leg_record(row, {**ok, "fidelity": "approximate", "omitted_levers": ["x"]}, None)["verdict"] == "indeterminate")
    check("a fetch error -> producer_failed, n null", leg_record(row, None, "boom")["read_state"] == "producer_failed")
    check("a skipped leg -> not_attempted", leg_record({**row, "skip": "feed yahoo"}, None, None)["read_state"] == "not_attempted")
    recs = [leg_record(row, ok, None), leg_record({**row, "leg": "M"}, {**ok, "net_r_oos": -0.5}, None),
            leg_record({**row, "leg": "S", "skip": "x"}, None, None)]
    v = assemble(recs, ["L", "M", "S"])
    check("a skipped leg does not block; one fail -> fail", v["verdict"] == "fail" and v["n"] == 96)
    check("one producer failure -> indeterminate", assemble(recs[:1] + [leg_record(row, None, "e")], ["L", "L"])["verdict"] == "indeterminate")
    check("all pass -> pass", assemble(recs[:1], ["L"])["verdict"] == "pass")
    lo = leg_record(row, {**ok, "n_trades_oos": 4}, None, n_floor=10)
    check("below the n floor -> indeterminate, flagged", lo["verdict"] == "indeterminate" and lo["below_n_floor"])
    check("a below-floor leg does not make the unit indeterminate",
          assemble([lo, leg_record(row, ok, None, n_floor=10)], ["L", "L"])["verdict"] == "pass")
    check("all legs below the floor -> indeterminate", assemble([lo], ["L"])["verdict"] == "indeterminate")
    check("source_mode: futures refused", source_mode({"source": "yahoo", "ticker": "GC=F"}, "1d").startswith("skip:"))
    check("source_mode: 1h equity -> us_equity_intraday", source_mode({"source": "yahoo", "ticker": "SLV"}, "1h") == "us_equity_intraday")
    check("source_mode: 2h equity refused", source_mode({"source": "yahoo", "ticker": "SLV"}, "2h").startswith("skip:"))
    check("source_mode: 1d ETF -> us_equity_daily", source_mode({"source": "yahoo", "ticker": "SPY"}, "1d") == "us_equity_daily")
    check("source_mode: binance", source_mode({"source": "binance", "ticker": "SOLUSDT"}, "1h") == "binance")
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
