#!/usr/bin/env python3
# wiring: scheduled — .github/workflows/counterfactual-grade-closed.yml (hourly :17) grades every newly closed order package; also run by hand per package.
"""Counterfactual grader for a CLOSED order package (TRADE-COUNTERFACTUAL-GRADER).

    python3 scripts/research/counterfactual_grader.py --live --package pkg-465a5d7d27644027 --write
    python3 scripts/research/counterfactual_grader.py --live --all-closed --write      # the per-close job

Operator, 2026-10-29: *"a mechanism for grading both entry brackets and active management against different
counterfactuals ... come back to this trade to see how much better/worse it would have been using the original
brackets, more/less active management, etc."* OBJECTIVE: absolute net P&L ($ and % of account) first, R is the
unit, risk reduction is the tie-breaker.

ONE decision = ONE trade: the record is per ORDER PACKAGE; each account's leg is reported beside it (the arms are
linear in size, so a leg's $ is ``net_R x its risk_usd``). Paper and real-money legs are never summed together.

ARMS (every one replayed over the same committed price path, net of fee + slippage + funding)
  actual            the journal / venue outcome (MEASURED where the venue priced it).
  replayed_actual   the actual management replayed through the SAME engine: the like-for-like baseline every delta
                    is quoted against (``delta_vs_replayed_actual``); ``delta_vs_actual`` is quoted beside it.
  original_brackets initial SL/TP untouched, the strategy's own trail only (no in-trade action).
  alt_brackets      SL distance x {0.75, 1.0, 1.25, 1.5} crossed with TP at {2, 3, 4, 5, 6} R. CONSTANT RISK: a wider
                    stop means a smaller position, so R and $ are per unit of the original risk budget.
  less_management   each applied in-trade action removed, one at a time (and all removed = original_brackets).
  more_management   rule-based: stop to break-even at +1R / +1.5R; lock +1R at +2R; the BE+lock ladder; ATR trails
                    k x ATR(entry) with k in {1.5, 2, 3, 4}; plus every recorded-but-not-applied review call.
  random_control    N=300 matched random interventions of the SAME class as the applied actions (same count of
                    stop-tightens, drawn uniformly in time and level between the live stop and the market). Reports
                    mean / p10 / p50 / p90 and ``p_random_ge_replayed_actual``.

STATED BIASES (also written into every record)
  * A stop fills AT its price (plus half the round-trip slippage); a gap fills at the open. Flatters every stop.
  * A touch is not a fill: a stop / TP needs price to trade THROUGH it (CALIBRATION n=1, ADA 6735: the 1m bar that
    only touched 0.2015 did not fill; the next bar's high of 0.2016 did).
  * Order inside a bar is unknown: the stop is checked first, then the TP (pessimistic). A rule trigger or a
    ratcheted stop takes effect from the NEXT bar. A timed action takes effect on the first bar OPENING at/after it.
  * The path is stitched from the finest committed candles the API serves (1m for ~16h, 5m ~3.5d, 15m ~10d): the
    pre-1m part of a long trade is replayed on coarser bars, so a rule near a level can be hit or missed there.
  * Entry is the ACTUAL fill (shared by every arm); R's unit is the package's INITIAL risk (exit_plan.stop), never
    the amended ``order_packages.sl``.
  * An arm that has not hit a bracket by the end of the data is ``resolved: false``, marked at the last close and
    costed as if closed there. It is NOT a realised exit; compare it with that in mind.
  * Funding is the policy default x windows held (ESTIMATED) unless the trade recorded its own. Account % uses the
    CURRENT equity less this trade's actual P&L (ESTIMATED; bybit_1 is a margin-borrowing paper account whose
    equity is not comparable and is reported null).
  * Management actions are the declared / derived ones with their time provenance; a wrong time moves an arm.

SCHEMA of ``comms/research/counterfactual_grades/<order_package_id>.json``  (``schema_version`` 1)
  order_package_id, strategy, symbol, side, graded_at, status ("graded" | "could_not_grade"), reason
  bracket   {entry_pkg, stop0, stop0_source, tp, tp_r, r_dist, atr, trail_mult}
  legs      [{account_id, trade_id, account_class, qty, entry_fill, exit_price, exit_reason, risk_usd, pnl_usd_journal,
              pnl_usd_venue, equity_pre_usd, provenance}]
  path      {bars, resolution_by_tf, first_bar, last_bar, t_entry, t_close}
  actions   [{ts, kind, level, source, time_provenance}]    the applied in-trade actions the baseline replays
  arms      [{arm_id, family, label, params, resolved, exit{ts,px,reason}, gross_r, cost_r{fee,slip,funding}, net_r,
              per_account{acct:{pnl_usd, pct_of_account}}, delta_vs_replayed_actual_r, delta_vs_actual_r,
              delta_vs_replayed_actual_usd{acct}, provenance}]
  random_control  {n, class, mean_r, p10_r, p50_r, p90_r, p_random_ge_replayed_actual}
  fidelity  {replayed_actual_net_r, actual_net_r, abs_gap_r}
  post_exit {horizon{seconds, hours, source, timeframe, end}, horizon_reached, mfe_r, mae_r, tp_reach{reached, bars, seconds},
             wider_sl_arms[{arm_id, sl_mult, tp_r, survived, resolved, net_r, exit_reason, delta_vs_actual_r}],
             verdict{verdict: exit_saved_r|exited_early|neutral|null, r_diff, resolved, n_held_arms, n_unresolved, basis_arm, provenance}}
            Bars stop at the horizon end (t_close + horizon); an arm still open there is ``resolved: false`` and never
            counted in a verdict number. ``mfe_r`` / ``mae_r`` are price excursions after the exit in units of the initial
            risk (not P&L); every arm net_r is net of the full cost stack.
  biases    [str]
Provenance values: MEASURED | ESTIMATED (src/runtime/provenance.py vocabulary). ``null`` = could not look, never 0.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import live_review_counterfactual as lrc  # noqa: E402  (extend, do not duplicate: _num/_ts/_iso/initial_stop/_meta/fetch_diag)
from cf_core import (ATR_K, BIASES, DEFAULT_HORIZON_H, FALLBACK_HORIZON_H, N_RANDOM, SCHEMA_VERSION, SL_MULTS, TF_SEC, TP_RS,  # noqa: E402,F401
                     VERDICT_TOL_R, _arm, _delta, cost_model, grade_package, net_of, post_exit_block, resolve_horizon, simulate,
                     stitch_bars)  # ONE ENGINE (CF-B0): lifted to scripts/research/cf_core.py; re-exported so every caller is unchanged

OUT_DIR = REPO / "comms" / "research" / "counterfactual_grades"
ACTIONS_DIR = OUT_DIR / "actions"
# POST-EXIT HORIZON (GRADER-POST-EXIT-HORIZON): how long after the real close an arm may keep running before it is
# marked unresolved. The leg's own config max-hold (max_hold_hours / max_hold_bars / max_hold_min) wins; else this
# explicit per-timeframe default, recorded in every record as ``post_exit.horizon``.


# --------------------------------------------------------------------------- path



# --------------------------------------------------------------------------- replay engine



# --------------------------------------------------------------------------- costs and money






# --------------------------------------------------------------------------- post-exit horizon



def strategy_config(name: Optional[str]) -> dict:
    import yaml
    try:
        d = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()) or {}
        return dict((d.get("strategies") or d).get(name) or {})
    except (OSError, yaml.YAMLError, AttributeError, TypeError) as exc:
        print(f"counterfactual_grader: strategies.yaml unreadable ({exc!r}); using the default horizon", file=sys.stderr)
        return {}



# --------------------------------------------------------------------------- the grader







# --------------------------------------------------------------------------- inputs

def derive_actions(pkg: dict, path_rows: List[dict], declared: Optional[dict]) -> List[dict]:
    """Applied in-trade stop moves. ``declared`` (``actions/<pkg>.json``) wins; else the first bar whose recorded
    stop differs from the previous one (bar-bounded: time = END of that bar, ESTIMATED)."""
    out: List[dict] = []
    if declared:
        for a in declared.get("actions", []):
            out.append({"ts_epoch": lrc._ts(a["ts"]), "kind": a.get("kind", "set_stop"), "level": float(a["level"]),
                        "source": a.get("source", "declared"), "time_provenance": a.get("time_provenance", "ESTIMATED")})
        return sorted(out, key=lambda a: a["ts_epoch"])
    prev = lrc.initial_stop(pkg)
    for r in sorted(path_rows, key=lambda r: r.get("bar_ts") or ""):
        sl = lrc._num(r.get("sl_price"))
        if sl is not None and prev is not None and abs(sl - prev) > 1e-12:
            t = lrc._ts(r["bar_ts"])
            out.append({"ts_epoch": t + 7200, "kind": "set_stop", "level": sl, "source": "path_history_sl_change",
                        "time_provenance": "ESTIMATED(bar_bounded)"})
        if sl is not None:
            prev = sl
    return out


def fetch_candles(symbol: str, interval: str) -> List[dict]:
    url = "https://ict-bot.duckdns.org/api/bot/candles?" + urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": 1000})
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            d = json.loads(r.read())
    except (OSError, ValueError) as exc:
        print(f"counterfactual_grader: candles {symbol}/{interval} unavailable: {exc!r}", file=sys.stderr)
        return []
    return [b for b in (d.get("candles") or []) if all(k in b for k in ("time", "open", "high", "low", "close"))]


def _venue_closes(account_id: str, symbol: str, t0: float, t1: float) -> Optional[dict]:
    try:
        d = lrc.fetch_diag(f"bybit_raw_closed_pnl?account_id={account_id}&symbol={symbol}"
                           f"&start_ms={int((t0 - 3600) * 1000)}&end_ms={int((t1 + 3600) * 1000)}")
    except RuntimeError:
        return None
    recs = ((d.get("result") or {}).get("records")) or []
    if not recs:
        return None
    return {"closed_pnl": sum(float(r["closed_pnl"]) for r in recs), "avg_exit_price": float(recs[-1]["avg_exit_price"])}


def load_equity() -> Dict[str, Optional[float]]:
    try:
        d = lrc.fetch_diag("broker_account_status")
    except RuntimeError:
        return {}
    out: Dict[str, Optional[float]] = {}
    for a in d.get("accounts", []):
        mf = a.get("margin_fields") or {}
        eq = lrc._num(mf.get("totalEquity"))
        # bybit_1 nets a negative USDT borrow against BTC/ETH collateral: its equity is not a P&L denominator
        out[a["account_id"]] = None if a["account_id"] == "bybit_1" else eq
    return out


def read_reviews() -> List[dict]:
    rows = lrc.read_jsonl(lrc.REVIEWS)
    rdir = REPO / "comms" / "live_review" / "rows"
    have = {r["review_id"] for r in rows}
    if rdir.is_dir():
        for p in sorted(rdir.glob("*.json")):
            r = json.loads(p.read_text())
            if r.get("review_id") not in have:
                rows.append(r)
    return rows


def grade_live(pkg_id: str, packages: Dict[str, dict], trades: Dict[int, dict], reviews: List[dict],
               equity: Dict[str, Optional[float]]) -> dict:
    pkg = packages[pkg_id]
    legs = [t for t in trades.values() if t.get("order_package_id") == pkg_id]
    if not legs:
        return {"schema_version": SCHEMA_VERSION, "order_package_id": pkg_id, "status": "could_not_grade", "reason": "no_trade_rows",
                "graded_at": lrc._iso(datetime.now(timezone.utc).timestamp())}
    t0 = min(lrc._ts(t.get("timestamp")) or 1e18 for t in legs)
    t1 = max(lrc._ts(t.get("closed_at")) or 0 for t in legs)
    series = {tf: fetch_candles(str(pkg.get("symbol")), tf) for tf in TF_SEC}
    bars = stitch_bars(series, t0)
    try:
        d = lrc.fetch_diag(f"position_path_history?order_package_id={pkg_id}&limit=500")
        path_rows = d.get("rows", [])
    except RuntimeError:
        path_rows = []
    af = ACTIONS_DIR / f"{pkg_id}.json"
    actions = derive_actions(pkg, path_rows, json.loads(af.read_text()) if af.exists() else None)
    venue = {}
    for t in legs:
        if str(t.get("account_id", "")).startswith("bybit"):
            v = _venue_closes(t["account_id"], str(pkg.get("symbol")), lrc._ts(t.get("timestamp")) or t0, lrc._ts(t.get("closed_at")) or t1)
            if v:
                venue[t["account_id"]] = v
    rvs = [r for r in reviews if r.get("order_package_id") == pkg_id]
    return grade_package(pkg, legs, bars, rvs, actions, equity, venue, horizon=resolve_horizon(pkg, strategy_config(pkg.get("strategy_name"))))


def load_sources() -> Tuple[Dict[str, dict], Dict[int, dict]]:
    pk = lrc.fetch_diag("journal?table=order_packages&limit=150")
    pk = pk.get("rows", pk) if isinstance(pk, dict) else pk
    trades: Dict[int, dict] = {}
    for off in (0, 1000):
        page = lrc.fetch_diag(f"journal?table=trades&limit=1000&offset={off}")
        page = page.get("rows", page) if isinstance(page, dict) else page
        trades.update({int(t["id"]): t for t in page})
        if len(page) < 1000:
            break
    return {p["order_package_id"]: p for p in pk}, trades


def due_for_grading(rec_path: Path, pkg: dict, legs: List[dict], now: float) -> bool:
    """A closed package is graded once its post-exit horizon has passed (grading earlier leaves every arm that holds
    past the real exit unresolved), and re-graded when its record predates the horizon or the current schema."""
    t_close = max((lrc._ts(t.get("closed_at")) or 0.0) for t in legs)
    h_end = t_close + resolve_horizon(pkg, strategy_config(pkg.get("strategy_name")))["seconds"]
    if now < h_end:
        return False
    if not rec_path.exists():
        return True
    try:
        rec = json.loads(rec_path.read_text())
    except ValueError:
        return True
    if int(rec.get("schema_version") or 0) < SCHEMA_VERSION:
        return True
    return (lrc._ts(rec.get("graded_at")) or 0.0) < h_end


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", required=True)
    ap.add_argument("--package", help="grade one order_package_id (re-grades if a record exists)")
    ap.add_argument("--all-closed", action="store_true", help="grade every closed package whose horizon has passed and that has no (current) record")
    ap.add_argument("--max", type=int, default=20, help="cap per run for --all-closed")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if not (a.package or a.all_closed):
        ap.error("give --package or --all-closed")
    packages, trades = load_sources()
    reviews, equity = read_reviews(), load_equity()
    if a.package:
        ids = [a.package]
    else:
        ids = []
        now = datetime.now(timezone.utc).timestamp()
        for pid, p in packages.items():
            legs = [t for t in trades.values() if t.get("order_package_id") == pid]
            if (str(p.get("status")).lower() == "closed" and legs and all(str(t.get("status")).lower() == "closed" and t.get("closed_at") for t in legs)
                    and due_for_grading(OUT_DIR / f"{pid}.json", p, legs, now)):
                ids.append(pid)
        ids = sorted(ids)[: a.max]
    n_ok = 0
    for pid in ids:
        if pid not in packages:
            print(f"{pid}: not in the latest 150 packages", file=sys.stderr)
            continue
        rec = grade_live(pid, packages, trades, reviews, equity)
        print(f"{pid}: {rec['status']} {rec.get('reason') or ''}")
        if a.write and rec["status"] == "graded":
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            (OUT_DIR / f"{pid}.json").write_text(json.dumps(rec, indent=1, sort_keys=False) + "\n")
            n_ok += 1
    print(f"graded {n_ok}/{len(ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
