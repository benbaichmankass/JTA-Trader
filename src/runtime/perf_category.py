"""Per-category performance metrics (PERF-PAGE-CATEGORY-TABLE) -- ONE pure definition shared by the route.

Categories are DERIVED from ``config/accounts.yaml`` (never hard-coded account lists):
``prop`` (``type: prop``, not retired) · ``live`` (``account_class: real_money``) · ``paper_portfolio`` (paper with
``paper_role: portfolio`` -- the real-money mirror) · ``paper_testing`` (every other paper account). Anything else
(retired prop, unknown class) is returned in ``excluded`` BY NAME, never silently dropped.

Every metric returns ``None`` (rendered "—") when it cannot be computed; ``read_state`` / ``n_*`` say why. The provenance
split follows ``src.runtime.provenance`` (UNVERIFIED is never folded into measured).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from src.core.profile_loader import contract_value_usd_for
from src.runtime.provenance import MEASURED, classify_pnl
from src.runtime.r_provenance import r_multiple_provenanced

CATEGORIES = ("live", "prop", "paper_portfolio", "paper_testing")
MIN_N_R = 10          # the perf-review --min-n: fewer R-graded rows than this is flagged insufficient_n
MIN_SNAPSHOTS = 24    # hourly balance snapshots needed before capital_utilisation is computed
PROP_PNL_BUCKET = "ESTIMATED"  # prop pnl is phone/sheet-reported, not a venue-API close: never MEASURED


def category_of(cfg: Mapping[str, Any]) -> Optional[str]:
    if not isinstance(cfg, Mapping):
        return None
    if str(cfg.get("type") or "").lower() == "prop" or str(cfg.get("account_class") or "").lower() == "prop":
        return None if cfg.get("retired") else "prop"
    cls = str(cfg.get("account_class") or "").lower()
    if cls == "real_money":
        return "live"
    if cls == "paper":
        return "paper_portfolio" if str(cfg.get("paper_role") or "").lower() == "portfolio" else "paper_testing"
    return None


def categorize(accounts: Mapping[str, Any]) -> Tuple[Dict[str, List[str]], List[Dict[str, str]]]:
    """-> ({category: [account_id]}, excluded=[{account_id, reason}])."""
    out: Dict[str, List[str]] = {c: [] for c in CATEGORIES}
    excluded: List[Dict[str, str]] = []
    for aid, cfg in (accounts or {}).items():
        cat = category_of(cfg)
        if cat:
            out[cat].append(aid)
        else:
            why = "retired" if isinstance(cfg, Mapping) and cfg.get("retired") else "no_category"
            excluded.append({"account_id": aid, "reason": why})
    return out, excluded


def _f(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _round(v: Optional[float], n: int = 6) -> Optional[float]:
    return None if v is None else round(v, n)


def category_metrics(rows: Iterable[Mapping[str, Any]], *, category: str, window_days: Optional[float],
                     snapshots: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Metrics for one category over CLOSED rows already filtered to the window (no backtest/superseded/null-pnl).

    Row keys: ``pnl, entry_price, stop_loss, take_profit_1, direction, qty, symbol, opened_at, closed_at, notes,
    package_meta`` (+ optional ``fee_taker_usd, fee_maker_usd, funding_paid_usd``). ``snapshots`` is
    ``{account_id: {"n": snapshot count, "mean_balance": float|None}}`` for the category's accounts."""
    rows = sorted(rows, key=lambda r: str(r.get("closed_at") or ""))
    n = len(rows)
    meas = unmeas = 0.0
    n_meas = n_unmeas = 0
    wins = priced = 0
    gp = gl = 0.0
    r_vals: List[float] = []
    notional_days = notional_days_meas = 0.0
    pnl_meas_nd = 0.0
    holds: List[float] = []
    n_no_hold = 0
    fees = funding = 0.0
    n_fees = n_funding = 0
    cum = peak = max_dd = 0.0
    for r in rows:
        pnl = _f(r.get("pnl"))
        if pnl is None:
            continue
        bucket = PROP_PNL_BUCKET if category == "prop" else classify_pnl(r)[0]
        if bucket == MEASURED:
            meas += pnl
            n_meas += 1
            priced += 1
            wins += pnl > 0
            gp += max(pnl, 0.0)
            gl += max(-pnl, 0.0)
        else:
            unmeas += pnl
            n_unmeas += 1
        cum += pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        rr, _basis = r_multiple_provenanced(r, contract_value_usd_for(r.get("symbol")))
        if rr is not None:
            r_vals.append(rr)
        o, c = _dt(r.get("opened_at")), _dt(r.get("closed_at"))
        qty, entry = _f(r.get("qty")), _f(r.get("entry_price"))
        if o and c and c >= o:
            hd = (c - o).total_seconds() / 86400.0
            holds.append(hd)
            if qty is not None and entry is not None:
                nd = abs(qty * entry) * float(contract_value_usd_for(r.get("symbol")) or 1.0) * hd
                notional_days += nd
                pnl_meas_nd += pnl if bucket == MEASURED else 0.0
                notional_days_meas += nd if bucket == MEASURED else 0.0
        else:
            n_no_hold += 1
        for key, acc in (("fee_taker_usd", "f"), ("fee_maker_usd", "f"), ("funding_paid_usd", "u")):
            v = _f(r.get(key))
            if v is not None:
                if acc == "f":
                    fees += v
                    n_fees += 1
                else:
                    funding += v
                    n_funding += 1
    net = meas + unmeas
    # return on time in trade (bps per notional-day): cell = measured-only, all-rows value alongside
    rot_all = (net / notional_days * 1e4) if notional_days > 0 and n_no_hold == 0 else None
    rot_meas = (pnl_meas_nd / notional_days_meas * 1e4) if notional_days_meas > 0 and n_no_hold == 0 else None
    # capital utilisation: gross notional-days / equity-days; null without enough snapshots on EVERY account
    util = None
    util_state = "no_equity_record"
    snaps = snapshots or {}
    if snaps and window_days and all((s.get("n") or 0) >= MIN_SNAPSHOTS and s.get("mean_balance") for s in snaps.values()):
        equity_days = sum(float(s["mean_balance"]) for s in snaps.values()) * window_days
        util = notional_days / equity_days if equity_days > 0 else None
        util_state = "estimated" if util is not None else "no_equity_record"
    return {
        "category": category, "n_closed": n,
        "net_pnl_usd": _round(net, 4) if n else None,
        "measured_usd": _round(meas, 4) if n_meas else None, "n_measured": n_meas,
        "not_measured_usd": _round(unmeas, 4) if n_unmeas else None, "n_not_measured": n_unmeas,
        "win_rate": _round(wins / priced, 4) if priced else None, "n_priced": priced,
        "avg_realised_r": _round(sum(r_vals) / len(r_vals), 4) if r_vals else None, "n_r_graded": len(r_vals),
        "r_insufficient_n": len(r_vals) < MIN_N_R,
        "profit_factor": _round(gp / gl, 4) if gl > 0 else None,
        "avg_hold_days": _round(sum(holds) / len(holds), 4) if holds else None, "n_no_hold": n_no_hold,
        "return_on_time_in_trade_bps_per_notional_day": _round(rot_meas, 4),
        "return_on_time_in_trade_all_rows_bps_per_notional_day": _round(rot_all, 4),
        "capital_utilisation": _round(util, 6), "capital_utilisation_read_state": util_state,
        "max_drawdown_usd": _round(max_dd, 4) if n else None,
        "fees_usd": _round(fees, 4) if n_fees else None, "n_fees": n_fees,
        "funding_usd": _round(funding, 4) if n_funding else None, "n_funding": n_funding,
        "provenance": {"net_pnl_usd": "MEASURED+not_measured split (never folded)",
                       "capital_utilisation": "ESTIMATED (sampled balance_snapshots; open positions excluded)",
                       "return_on_time_in_trade": "ESTIMATED when any row's pnl is not MEASURED",
                       "max_drawdown_usd": "closed-trade basis, all rows with pnl, close order"},
    }


def _row_bucket(r: Mapping[str, Any], category: str) -> str:
    return PROP_PNL_BUCKET if category == "prop" else classify_pnl(r)[0]


def pnl_series(rows: Iterable[Mapping[str, Any]], *, category: str, per_trade: bool, measured_only: bool,
               start_capital: Optional[float]) -> List[Dict[str, Any]]:
    """Cumulative P&L points for one category (PERF-PAGE-PNL-CHART).

    Points are per trade (``per_trade``) or per UTC day. ``pnl_usd`` / ``cum_pnl_usd`` follow ``measured_only`` (rows whose
    pnl is not MEASURED are skipped); ``cum_pnl_all_rows_usd`` is ALWAYS the all-rows curve so the gap is visible.
    ``cum_pct`` = cum / ``start_capital`` and is ``None`` (never 0) when the capital base is unknown or non-positive.
    ``n`` counts the rows behind the point on the same basis as ``pnl_usd``."""
    pts: List[Dict[str, Any]] = []
    cum = cum_all = 0.0
    for r in sorted(rows, key=lambda x: str(x.get("closed_at") or "")):
        pnl = _f(r.get("pnl"))
        c = _dt(r.get("closed_at"))
        if pnl is None or c is None:
            continue
        counted = (not measured_only) or _row_bucket(r, category) == MEASURED
        cum_all += pnl
        if counted:
            cum += pnl
        key = c.isoformat() if per_trade else c.astimezone(timezone.utc).date().isoformat()
        if not per_trade and pts and pts[-1]["date"] == key:
            p = pts[-1]
        else:
            p = {"date": key, "pnl_usd": 0.0, "n": 0}
            pts.append(p)
        if counted:
            p["pnl_usd"] += pnl
            p["n"] += 1
        p["cum_pnl_usd"] = cum
        p["cum_pnl_all_rows_usd"] = cum_all
    ok = start_capital is not None and start_capital > 0
    for p in pts:
        p["pnl_usd"] = round(p["pnl_usd"], 4)
        p["cum_pnl_usd"] = round(p["cum_pnl_usd"], 4)
        p["cum_pnl_all_rows_usd"] = round(p["cum_pnl_all_rows_usd"], 4)
        p["cum_pct"] = round(p["cum_pnl_usd"] / start_capital * 100.0, 4) if ok else None
        p["cum_pct_all_rows"] = round(p["cum_pnl_all_rows_usd"] / start_capital * 100.0, 4) if ok else None
    return pts
