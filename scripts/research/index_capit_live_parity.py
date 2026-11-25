#!/usr/bin/env python3
# wiring: manual-only - re-run by a session whenever src/units/strategies/index_capitulation_1x.py changes; tests/test_index_capitulation_1x.py fails until it is (the record pins the module sha1)
"""Live-path parity for ``index_capitulation_1x`` against the harness fixture (row INDEX-CAPIT-1X-LEG).

WHAT IT PROVES
--------------
For every ticker in ``comms/research/INDEX-CAPIT-1X-LEG/spec.json`` it rebuilds, from the same daily bars the harness reads
(yfinance ``auto_adjust=False``; ``--bars-dir`` substitutes another feed), the frame the LIVE leg sees on the first tick of each
session: the last ``--window`` (default 200, the live fetch limit) bars, the final row being the entry session's forming bar
with ``open = high = low = close = that session's open`` (the first tick). It then calls the live
``src.units.strategies.index_capitulation_1x.order_package`` on EVERY session and checks:

1. every fixture trade (``parity_fixture.json``, the 1e06-06/-08 trades) is emitted by the live path on its entry session with
   the same signal date, entry, stop, take-profit and risk (to 1e-6 relative);
2. every harness signal the harness SKIPPED for geometry (``stop_wrong_side_at_entry`` / ``risk_degenerate``) is refused by the
   live path with the same reason;
3. the live path emits NOTHING on any other session (no live-only signal), except harness signals skipped ``in_position``
   (the runtime's per-account open-package gate is what holds those; counted, listed);
4. the live hold-cap count: for every fixture ``timeout`` trade, ``sessions_held`` on the frame ending at the exit session is
   exactly the hold cap (the session ``monitor()`` closes in), and for every stop / take-profit trade it is below the cap.

Exit 0 when every check passes, 1 when any fails, 2 when the bars could not be read. Writes ``--out`` (JSON) either way.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

sys.path.insert(0, str(REPO / "scripts" / "research"))
import index_signal_etf_harness as H  # noqa: E402
from src.units.strategies import index_capitulation_1x as L  # noqa: E402

LEG_DIR = REPO / "comms" / "research" / "INDEX-CAPIT-1X-LEG"
REL_TOL = 1e-6


def _close(a: float, b: float, tol: float = REL_TOL) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _bars(ticker: str, bars_dir: Path | None, cache: Path | None) -> pd.DataFrame:
    if bars_dir is not None:
        df = pd.read_csv(bars_dir / f"{ticker}.csv", index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        return df[["open", "high", "low", "close"]].sort_index()
    return H.fetch_daily(ticker, H.WINDOW_START, H.WINDOW_END, cache)   # the harness reads from WINDOW_START (no earlier warm-up)


def _live_frame(etf: pd.DataFrame, j: int, window: int) -> pd.DataFrame:
    """The frame the live leg sees on the first tick of session j: closed bars < j, then j as a forming bar at its open."""
    lo = max(0, j - window + 1)
    f = etf.iloc[lo:j + 1][["open", "high", "low", "close"]].copy()
    o = float(f["open"].iloc[-1])
    f.iloc[-1, f.columns.get_indexer(["high", "low", "close"])] = [o, o, o]
    f = f.reset_index().rename(columns={f.index.name or "index": "date"})
    # midnight ET as epoch ms, the shape fetch_candles hands the builder
    f["timestamp"] = (pd.DatetimeIndex(f["date"]).tz_localize("America/New_York").tz_convert("UTC").as_unit("ms").asi8)
    return f[["timestamp", "open", "high", "low", "close"]]


def run_ticker(t: str, k: float, fixture: Dict[str, Any], etf_full: pd.DataFrame, window: int) -> Dict[str, Any]:
    # the harness frame: index proxy == execution ETF at 1x, bars from WINDOW_START (its warm-up sits inside the window)
    ev = H.build_frame(etf_full, etf_full)
    ev = ev[(ev.index >= pd.Timestamp(H.WINDOW_START)) & (ev.index <= pd.Timestamp(H.WINDOW_END))]
    sigs = H.index_signals(ev, "capitulation_wide")
    sim = H.simulate(ev, sigs, 1.0, H.HOLD_CAP["capitulation_wide"], H.SLIP_BPS_SIDE, k)
    harness_trades = sim["trades"]
    fx_trades = fixture["trades"]
    reproduces = (len(harness_trades) == len(fx_trades)
                  and all(a["entry_date"] == b["entry_date"] and _close(a["entry"], b["entry"], 1e-4)
                          and _close(a["net_r"], b["net_r"], 1e-3) for a, b in zip(harness_trades, fx_trades)))

    etf = ev[["e_o", "e_h", "e_l", "e_c"]].rename(columns={"e_o": "open", "e_h": "high", "e_l": "low", "e_c": "close"})
    ix = etf.index
    sig_by_entry = {}
    for s in sigs:
        if s["i"] + 1 < len(ix):
            sig_by_entry[s["i"] + 1] = s
    fx_by_entry = {tr["entry_date"]: tr for tr in fx_trades}
    cfg = {"symbol": t, "k_star": {t: k}}
    out: Dict[str, Any] = {"k_star": k, "n_fixture": len(fx_trades), "fixture_reproduced_by_harness_now": reproduces,
                           "matched": 0, "mismatched": [], "missing": [], "live_only": [], "skip_reason_match": 0,
                           "skip_reason_mismatch": [], "in_position_emits": 0, "hold_cap_ok": 0, "hold_cap_bad": []}
    for j in range(1, len(ix)):
        d = str(ix[j].date())
        lf = _live_frame(etf, j, window)
        try:
            pkg = L.order_package(cfg, lf)
            err = None
        except ValueError as exc:
            pkg, err = None, str(exc)
        fx = fx_by_entry.get(d)
        s = sig_by_entry.get(j)
        if fx is not None:
            if pkg is None:
                out["missing"].append({"entry_date": d, "live_refusal": err})
                continue
            m = pkg["meta"]
            ok = (m["signal_date"] == fx["signal_date"] and _close(pkg["entry"], fx["entry"], 1e-4)
                  and _close(pkg["sl"], fx["stop"], 1e-4) and _close(pkg["tp"], fx["tp"], 1e-4)
                  and _close(m["risk_per_unit"], fx["risk"], 1e-3))
            if ok:
                out["matched"] += 1
            else:
                out["mismatched"].append({"entry_date": d, "live": {"signal_date": m["signal_date"], "entry": pkg["entry"],
                                          "sl": pkg["sl"], "tp": pkg["tp"], "risk": m["risk_per_unit"]},
                                          "fixture": {k2: fx[k2] for k2 in ("signal_date", "entry", "stop", "tp", "risk")}})
            continue
        if pkg is None:
            if s is not None and err:
                # a harness signal with no fixture trade: geometry skip or in_position skip
                entry = float(etf["open"].iloc[j])
                harness_reason = ("stop_wrong_side_at_entry" if not s["stop_idx"] < entry else
                                  "risk_degenerate" if (entry - s["stop_idx"]) / entry < H.MIN_RISK_FRAC else "in_position")
                if harness_reason != "in_position":
                    if err.startswith(harness_reason):
                        out["skip_reason_match"] += 1
                    else:
                        out["skip_reason_mismatch"].append({"entry_date": d, "harness": harness_reason, "live": err})
            continue
        # live emitted a package on a session with no fixture trade
        if s is not None:
            out["in_position_emits"] += 1          # the harness skipped it in_position; the runtime open-package gate holds it
        else:
            out["live_only"].append({"entry_date": d, "signal_date": pkg["meta"]["signal_date"]})
    # hold cap: count sessions on the frame ending at the exit session
    for tr in fx_trades:
        jx = ix.get_loc(pd.Timestamp(tr["exit_date"]))
        f = _live_frame(etf, jx, window)
        held = L.sessions_held(f, tr["entry_date"])
        want_cap = tr["why"] == "timeout"
        ok = (held == L.HOLD_CAP_SESSIONS) if want_cap else (held is not None and held <= L.HOLD_CAP_SESSIONS)
        if held != tr["bars"]:
            ok = False
        if ok:
            out["hold_cap_ok"] += 1
        else:
            out["hold_cap_bad"].append({"entry_date": tr["entry_date"], "exit_date": tr["exit_date"], "why": tr["why"],
                                        "bars": tr["bars"], "sessions_held": held})
    out["pass"] = (reproduces and out["matched"] == len(fx_trades) and not out["mismatched"] and not out["missing"]
                   and not out["live_only"] and not out["skip_reason_mismatch"] and out["hold_cap_ok"] == len(fx_trades))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(LEG_DIR / "live_parity.json"))
    ap.add_argument("--bars-dir", default=None, help="CSV per ticker (date index, open/high/low/close) instead of yfinance")
    ap.add_argument("--cache", default=None, help="yfinance cache dir")
    ap.add_argument("--window", type=int, default=200)
    ap.add_argument("--tickers", default=None)
    a = ap.parse_args(argv)
    spec = json.loads((LEG_DIR / "spec.json").read_text())
    fx = json.loads((LEG_DIR / "parity_fixture.json").read_text())
    tickers = a.tickers.split(",") if a.tickers else spec["population"]
    res: Dict[str, Any] = {"schema": "index_capit_live_parity/1", "leg": L.NAME,
                           "live_module": "src/units/strategies/index_capitulation_1x.py",
                           "live_module_sha1": hashlib.sha1((REPO / "src/units/strategies/index_capitulation_1x.py").read_bytes()).hexdigest(),
                           "fixture_sha1": hashlib.sha1((LEG_DIR / "parity_fixture.json").read_bytes()).hexdigest(),
                           "bars": a.bars_dir or "yfinance daily auto_adjust=False (the harness feed)",
                           "window_bars": a.window, "evidence_window": [H.WINDOW_START, H.WINDOW_END], "tickers": {}}
    rc = 0
    for t in tickers:
        try:
            etf = _bars(t, Path(a.bars_dir) if a.bars_dir else None, Path(a.cache) if a.cache else None)
        except Exception as exc:  # noqa: BLE001
            res["tickers"][t] = {"read_state": "could_not_read", "error": str(exc)}
            rc = max(rc, 2)
            continue
        r = run_ticker(t, float(spec["k_star"][t]), fx["tickers"][t], etf, a.window)
        res["tickers"][t] = r
        if not r["pass"]:
            rc = max(rc, 1)
        print(f"{t}: n {r['n_fixture']} matched {r['matched']} missing {len(r['missing'])} mismatched {len(r['mismatched'])} "
              f"live_only {len(r['live_only'])} skip_match {r['skip_reason_match']} skip_mismatch {len(r['skip_reason_mismatch'])} "
              f"in_position {r['in_position_emits']} hold_cap {r['hold_cap_ok']}/{r['n_fixture']} harness_now_reproduces "
              f"{r['fixture_reproduced_by_harness_now']} -> {'PASS' if r['pass'] else 'FAIL'}")
    rows = [v for v in res["tickers"].values() if "pass" in v]
    res["summary"] = {"tickers": len(tickers), "tickers_pass": sum(1 for v in rows if v["pass"]),
                      "fixture_trades": sum(v["n_fixture"] for v in rows), "matched": sum(v["matched"] for v in rows),
                      "live_only": sum(len(v["live_only"]) for v in rows),
                      "skip_reason_match": sum(v["skip_reason_match"] for v in rows),
                      "in_position_emits": sum(v["in_position_emits"] for v in rows),
                      "hold_cap_ok": sum(v["hold_cap_ok"] for v in rows), "pass": rc == 0}
    Path(a.out).write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res["summary"]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
