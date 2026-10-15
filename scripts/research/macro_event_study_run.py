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

CONFIRMATION ARMS (P4-MACRO-PROGRAMME, 2026-10-14; docs/research/programmes/04-MACRO-SLEEVE.md)
---------------------------------------------------------------------------------------------
A single PASS out of a family of kinds is a lead, not a result. Three optional arms let a confirmation unit
run on the same runner without a new script (all default OFF, so every existing unit is byte-identical):

  * ``--release-start`` / ``--release-end`` (``start <= date < end``): a sub-period stability split.
  * ``--anchor-shift-td K``: a PLACEBO. Each release's base bar moves K trading days in the price panel
    (K < 0 = earlier). With ``K <= -(max horizon)`` every forward window ends before the release, so an
    "edge" there is an artifact of the sample, not information.
  * ``--trade-horizon H --cost-symbol SYM``: a net-of-cost SIGN BOOK. Per release with a non-zero surprise,
    position = sign(surprise) (flipped when ``--expected-sign negative``), entered at the release-day close
    (the same base bar the IC uses, so it is tradeable after the print), held H trading days, charged the
    full round-trip cost stack of SYM: fee from ``profile_loader.roundtrip_fee_bps_for`` (None -> the
    estimator default ``execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP``) plus slippage and funding from
    ``execution_costs.resolve_cost_policy``. The NAIVE FLOOR (macro-research invariant 5) is the all-long
    book on the same windows at the same cost. When this arm is on, the VERDICT is the trade grade
    (``grade_trade``), and the IC grade is still reported beside it.

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


def filter_window(events: List[Dict[str, Any]], start: Optional[str], end: Optional[str]) -> List[Dict[str, Any]]:
    """``start <= date < end`` on the release date (ISO strings compare lexically). Pure."""
    return [e for e in events if (not start or str(e["date"])[:10] >= start) and (not end or str(e["date"])[:10] < end)]


def shift_anchor(events: List[Dict[str, Any]], panel_dates: List[str], k: int) -> List[Dict[str, Any]]:
    """Move each release's base bar ``k`` trading days in ``panel_dates`` (the placebo). A release whose
    shifted bar falls outside the panel is dropped, never clamped. ``k == 0`` returns the input. Pure."""
    import bisect
    if not k:
        return list(events)
    out: List[Dict[str, Any]] = []
    for e in events:
        pos = bisect.bisect_right(panel_dates, str(e["date"])[:10]) - 1
        q = pos + int(k)
        if pos < 0 or q < 0 or q >= len(panel_dates):
            continue
        out.append(dict(e, date=panel_dates[q], placebo_original_date=e["date"]))
    return out


def _mean_t(xs: List[float]) -> Dict[str, Any]:
    n = len(xs)
    if n < 2:
        return {"n": n, "mean": (xs[0] if xs else None), "t": None}
    mu = sum(xs) / n
    sd = (sum((x - mu) ** 2 for x in xs) / (n - 1)) ** 0.5
    return {"n": n, "mean": round(mu, 8), "t": (round(mu / (sd / n ** 0.5), 3) if sd > 0 else None)}


def sign_book(events: List[Dict[str, Any]], fwd, *, horizon: int, cost_frac: float, expected_sign: str,
              value_key: str = "surprise") -> Dict[str, Any]:
    """Net-of-cost sign book vs the all-long naive floor on the SAME windows. Pure (``fwd(date, h)``)."""
    flip = -1.0 if expected_sign == "negative" else 1.0
    book: List[float] = []
    floor: List[float] = []
    for e in events:
        v = e.get(value_key)
        r = fwd(e["date"], horizon)
        if v is None or r is None or float(v) == 0.0:
            continue
        pos = flip * (1.0 if float(v) > 0 else -1.0)
        book.append(pos * float(r) - cost_frac)
        floor.append(float(r) - cost_frac)
    diff = [b - f for b, f in zip(book, floor)]
    hits = sum(1 for b in book if b > 0)
    return {"horizon_days": horizon, "cost_frac_roundtrip": cost_frac, "book_net": _mean_t(book),
            "floor_all_long_net": _mean_t(floor), "book_minus_floor": _mean_t(diff),
            "book_hit_rate": (round(hits / len(book), 4) if book else None)}


def grade_trade(sb: Dict[str, Any], *, min_n: int, t_bar: float) -> Dict[str, Any]:
    """The registered trade rule. Pure, unit-tested.

    PASS           n >= min_n AND book mean net > 0 with t >= t_bar AND book mean net > floor mean net
    FAIL           n >= min_n and not PASS
    INDETERMINATE  n < min_n (the source bounded the test)
    no_data        no tradeable release"""
    b, f = sb["book_net"], sb["floor_all_long_net"]
    n = int(b["n"] or 0)
    if not n:
        return {"verdict": "not_applicable", "read_state": "no_data", "note": "no tradeable release (zero joined)"}
    if n < min_n:
        return {"verdict": "indeterminate", "read_state": "measured",
                "note": f"sign book n={n} < {min_n}: the source bounded the test, not the hypothesis"}
    ok = (b["mean"] is not None and b["mean"] > 0 and b["t"] is not None and b["t"] >= t_bar
          and f["mean"] is not None and b["mean"] > f["mean"])
    if ok:
        return {"verdict": "pass", "read_state": "measured",
                "note": f"net-of-cost sign book mean {b['mean']} (t {b['t']}) > 0 and > all-long floor {f['mean']}"}
    return {"verdict": "fail", "read_state": "measured",
            "note": f"sign book mean {b['mean']} (t {b['t']}) vs t-bar {t_bar}; all-long floor {f['mean']}"}


def cost_frac_for(symbol: str) -> Dict[str, Any]:
    """The full round-trip cost stack for ``symbol`` as a fraction of notional, with its derivation."""
    from src.core.profile_loader import roundtrip_fee_bps_for
    from src.runtime import execution_costs as ec
    fee = roundtrip_fee_bps_for(symbol)
    fee_src = "profile_loader.roundtrip_fee_bps_for"
    if fee is None:
        fee, fee_src = ec.DEFAULT_FEE_BPS_ROUNDTRIP, "execution_costs.DEFAULT_FEE_BPS_ROUNDTRIP (venue rate unset)"
    slip, fund = ec.resolve_cost_policy(symbol)
    # funding is per 8h window for perps only (0.0 for futures/ETFs); daily-hold sign books are not perps.
    total_bps = float(fee) + float(slip)
    return {"cost_symbol": symbol, "fee_bps_roundtrip": float(fee), "fee_source": fee_src,
            "slippage_bps_roundtrip": float(slip), "funding_bps_per_window": float(fund),
            "funding_applied": False if not fund else "UNSUPPORTED_PERP",
            "total_bps_roundtrip": total_bps, "cost_frac": total_bps / 1e4}


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
    ap.add_argument("--release-start", default=None, help="keep releases with date >= this (YYYY-MM-DD)")
    ap.add_argument("--release-end", default=None, help="keep releases with date < this (YYYY-MM-DD)")
    ap.add_argument("--anchor-shift-td", type=int, default=0, help="placebo: move each base bar K trading days")
    ap.add_argument("--trade-horizon", type=int, default=None, help="enable the net-of-cost sign book at H days")
    ap.add_argument("--cost-symbol", default=None, help="instrument whose cost stack the sign book pays")
    ap.add_argument("--trade-t-bar", type=float, default=2.0)
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
    events = filter_window(ees.load_resolved_events_multi(snaps, a.kind), a.release_start, a.release_end)
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
    if a.anchor_shift_td and panel:
        events = shift_anchor(events, [d for d, _ in panel], a.anchor_shift_td)
        with_value = [e for e in events if e.get(a.value_key) is not None]
    meas.update({"release_start": a.release_start, "release_end": a.release_end,
                 "anchor_shift_td": a.anchor_shift_td, "releases_after_window": len(events)})
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
    if a.trade_horizon:
        if not a.cost_symbol:
            return _emit({"verdict": "not_applicable", "read_state": "producer_failed", "population": pop, "n": 0,
                          "measurement": meas, "note": "--trade-horizon needs --cost-symbol (no cost stack, no verdict)"})
        cost = cost_frac_for(a.cost_symbol)
        sb = sign_book(events, ees.make_forward_return(panel), horizon=a.trade_horizon, cost_frac=cost["cost_frac"],
                       expected_sign=a.expected_sign, value_key=a.value_key)
        sb["cost_stack"] = cost
        gt = grade_trade(sb, min_n=a.min_n, t_bar=a.trade_t_bar)
        meas.update({"sign_book": sb, "ic_grade": {"verdict": g["verdict"], "note": g["note"]},
                     "trade_rule": {"horizon": a.trade_horizon, "min_n": a.min_n, "t_bar": a.trade_t_bar}})
        g = dict(g, verdict=gt["verdict"], read_state=gt["read_state"], note=gt["note"])
        n_max = int(sb["book_net"]["n"] or 0)
    (out / "scorecard.json").write_text(json.dumps({"rows": rows, "summary": summary, "meta": meas}, indent=2,
                                                   default=str) + "\n", encoding="utf-8")
    return _emit({"verdict": g["verdict"], "read_state": g["read_state"], "population": pop, "n": n_max,
                  "measurement": meas, "note": g["note"]})


if __name__ == "__main__":
    raise SystemExit(main())
