#!/usr/bin/env python3
# wiring: manual-only — LTR-5 counterfactual replay; run by /performance-review (Live review section) and the weekly perf pass via scripts/ops/live_review_grade.py, which imports it. No timer.
"""Counterfactual replay: price every live-review call against holding, net of the full cost stack.

    python3 scripts/research/live_review_counterfactual.py --live            # price from the VM journal + exchange candles
    python3 scripts/research/live_review_counterfactual.py --live --write    # + append computed rows to comms/live_review/outcomes.jsonl

LTR-5 of docs/plans/live-trade-review-DESIGN.md (sections 5 and 8). For each row of
``comms/live_review/reviews.jsonl`` the question is: *what did following this call add over holding?*

METHOD
------
* The **review time** is ``reviewed_at``. The replay starts at the first bar that OPENS at or after it
  (the bar in progress is skipped: its path is partly in the past).
* **HOLD path** = the untouched bracket: the stop the review saw (``state.sl``), the package TP, and the
  leg's own trail (``trail_mult x atr`` behind the running extreme, never loosening) when the package
  declares one. The extreme is seeded from ``state.peak_r`` (an ESTIMATED lower bound).
* **REC path** = the same bracket with the recommended ``tighten_sl`` level in force from the review bar on
  (the tighter stop wins; the trail keeps ratcheting).
* **Order inside a bar: stop first** (pessimistic), a gap fills at the open, TP fills at its price.
* **Costs.** A replayed exit is ``gross R - fee - funding(held fraction) - slippage``. Fee and funding are the
  trade's own recorded legs when it has them (``cost_source`` broker/estimate), else
  ``execution_costs`` defaults; slippage is ``execution_costs.resolve_cost_policy`` on the symbol. The
  realised side is ``src.runtime.net_r_label.net_r_for_trade`` on the package's INITIAL stop.
* **Which side is the replay.**
  - call NOT applied: the realised trade IS the hold path. The hold replay is run too, as a FIDELITY check
    (``replay_matches_realised`` within ``FIDELITY_TOL_R``), and the replay of the call is ``rec_r``. A replay
    that cannot reproduce the trade's own exit (``replay_mismatch``), or that never exits while the trade did
    and the call would have (``hold_replay_unresolved``), is NOT priced: it is counted as could_not_price.
    MEASURED 2026-10-26 on live closed crypto trades (untouched bracket replayed from entry): of 22 that
    resolved, 16 matched the realised net R within 0.15 R and 6 did not; 47 more had no replay exit.
    The leg's own ``monitor()`` is not re-run (design says it should be): filed as a follow-up.
  - call applied: the realised trade IS the call. ``cf_r`` is the hold replay; fidelity is ``unvalidated``.
* ``delta_r = rec_r - cf_r`` (positive = the call helped). A call that changes no path (hold,
  no_recommendation, flag_mechanics) has ``delta_r = 0.0`` by construction, not a measurement.
* ``cf_r_shadow_0_5`` = R under the SHADOW 0.5 R policy (the call if it is within the shadow bound, else hold).

* **Every other action class (LTR-ALL-ACTIONS)** is priced by ``trade_action_delta`` as a PAIR of replays
  from the review bar, method ``paired_replay_v1``, so ``delta_r`` = action replay - hold replay (both net):
  - ``close``: the whole position exits at the OPEN of the first bar at/after the review;
  - ``partial_close`` (``size_fraction`` f): f of the size exits there, 1 - f rides the hold path;
  - ``move_tp`` / ``tp_revise`` (``level``): the hold bracket with the TP at ``level``;
  - ``widen_sl`` (``level``): the hold bracket with the stop at ``level`` (the trail still ratchets);
  - ``change_size`` (``size_multiplier`` m) / ``add_entry`` (``size_fraction`` f, i.e. m = 1 + f): the size
    difference enters or exits at the review-bar open and rides the hold path; an ADDED slice pays one extra
    round trip (fee + slippage) on its size. All R figures are in units of the ORIGINAL size's initial risk.
  When the call was NOT applied the realised trade anchors ``cf_r`` (fidelity-checked as above) and
  ``rec_r = cf_r + delta``; when it WAS applied, ``cf_r`` is the hold replay and fidelity is ``unvalidated``.
STATED BIASES: a stop fills AT its price, which flatters every tighten; the entry is the package entry;
bars are exchange candles; the pre-review path is not replayed (its state is the review's own record).
``null`` always means "could not look", never 0.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.runtime.execution_costs import DEFAULT_FEE_BPS_ROUNDTRIP, resolve_cost_policy  # noqa: E402
from src.runtime.net_r_label import net_r_for_trade  # noqa: E402

REVIEWS = REPO / "comms" / "live_review" / "reviews.jsonl"
OUTCOMES = REPO / "comms" / "live_review" / "outcomes.jsonl"
FIDELITY_TOL_R = 0.15
ALTERING = ("tighten_sl", "tp_revise", "partial_close", "close", "move_tp", "widen_sl", "change_size", "add_entry")
#: LTR-ALL-ACTIONS (MD-TRADE-DESK, operator 2026-10-26): every class except tighten_sl is priced as a
#: PAIR of replays from the same review bar (hold vs the action), so its delta is replay-vs-replay; see
#: ``trade_action_delta``. tighten_sl keeps its original method (``replay_v1:stop_first+trail``) unchanged.
PAIRED = tuple(a for a in ALTERING if a != "tighten_sl")
NO_PATH_CHANGE = ("hold", "no_recommendation", "flag_mechanics", "file_hypothesis")
_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _ts(v: Any) -> Optional[float]:
    """Epoch seconds from an ISO string / epoch number; None when unparseable."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- replay primitive

def replay(bars: List[dict], *, side: str, entry: float, r_dist: float, start_ts: float, stop: float,
           tp: Optional[float], extreme_r0: float, trail_dist: Optional[float],
           tighten_to: Optional[float] = None) -> Optional[dict]:
    """Walk bars opening at/after ``start_ts``. Returns ``{gross_r, ts, reason}`` or None (still open).

    ``stop``/``tp``/``tighten_to`` are PRICES. ``trail_dist`` is a price distance behind the running
    extreme (None = no trail). The stop only ever tightens. Stop is checked before TP inside a bar.
    """
    long_ = side == "long"
    sign = 1.0 if long_ else -1.0
    ext = entry + sign * extreme_r0 * r_dist                      # running favourable extreme (price)
    cur = stop
    if tighten_to is not None and ((tighten_to > cur) if long_ else (tighten_to < cur)):
        cur = tighten_to
    r_of = lambda px: sign * (px - entry) / r_dist                # noqa: E731
    for b in bars:
        if b["time"] < start_ts:
            continue
        o, h, lo = b["open"], b["high"], b["low"]
        hit_stop = (lo <= cur) if long_ else (h >= cur)
        if hit_stop:
            fill = min(cur, o) if long_ else max(cur, o)          # a gap through the stop fills at the open
            return {"gross_r": r_of(fill), "ts": b["time"], "reason": "stop"}
        if tp is not None and ((h >= tp) if long_ else (lo <= tp)):
            fill = max(tp, o) if long_ else min(tp, o)
            return {"gross_r": r_of(fill), "ts": b["time"], "reason": "tp"}
        ext = max(ext, h) if long_ else min(ext, lo)
        if trail_dist is not None:
            t = ext - sign * trail_dist
            if (t > cur) if long_ else (t < cur):
                cur = t
    return None


# --------------------------------------------------------------------------- costs

def cost_legs(trade: dict, symbol: str, entry: float, r_dist: float, risk_usd: Optional[float]) -> Tuple[float, float, float, str]:
    """(fee_r, funding_r_total, slippage_r, source): the trade's own recorded legs, else policy defaults."""
    slip_bps, fund_bps = resolve_cost_policy(symbol)
    per_unit = entry / r_dist / 1e4
    slip_r = slip_bps * per_unit
    src = str(trade.get("cost_source") or "").lower()
    if src in ("broker", "estimate") and risk_usd:
        fee_r = ((_num(trade.get("fee_taker_usd")) or 0.0) + (_num(trade.get("fee_maker_usd")) or 0.0)) / risk_usd
        fund_r = (_num(trade.get("funding_paid_usd")) or 0.0) / risk_usd
        return fee_r, fund_r, slip_r, f"recorded_legs[{src}]+policy_slippage"
    return DEFAULT_FEE_BPS_ROUNDTRIP * per_unit, 0.0, slip_r, "policy_defaults"


def net_of_costs(gross_r: float, fee_r: float, fund_total_r: float, slip_r: float, held_frac: float) -> float:
    return gross_r - fee_r - slip_r - fund_total_r * min(1.0, max(0.0, held_frac))


# --------------------------------------------------------------------------- one review

def _result(review: dict, **kw: Any) -> dict:
    base = {"review_id": review["review_id"], "order_package_id": review["order_package_id"],
            "trade_id": review.get("trade_id"), "leg": review.get("leg"),
            "action": (review.get("recommendation") or {}).get("action"), "applied": bool(review.get("applied")),
            "state": None, "reason": None, "outcome": None, "to_date": None}
    base.update(kw)
    return base


def price_review(review: dict, pkg: Optional[dict], trade: Optional[dict], bars: Optional[List[dict]],
                 computed_at: Optional[str] = None) -> dict:
    """Price one review. ``state`` is ``priced`` | ``not_a_call`` | ``could_not_price`` (+ ``reason``).

    ``outcome`` is a schema-valid outcomes row only for a CLOSED trade; ``to_date`` is a diagnostic replay to
    the last candle for an open trade (never persisted).
    """
    rec = review.get("recommendation") or {}
    action = rec.get("action")
    if action in NO_PATH_CHANGE:
        sl0 = _num((pkg or {}).get("sl"))
        lab = net_r_for_trade(dict(trade, stop_loss=sl0)) if (trade and sl0 is not None) else None
        out = _outcome_row(review, trade, delta=0.0, rec_r=None, cf_r=None, cf_shadow=None,
                           method="no_path_change", fidelity=None, stack=None, computed_at=computed_at,
                           net_r=lab["net_R"] if lab else None)
        if out is None:
            return _result(review, state="not_a_call", reason="no_path_change_trade_open_or_unjoined")
        return _result(review, state="not_a_call", reason="no_path_change", outcome=out)
    if action not in ALTERING:
        return _result(review, state="could_not_price", reason=f"unknown_action:{action}")
    level = _num(rec.get("level"))
    if action == "tighten_sl" and level is None:
        return _result(review, state="could_not_price", reason="tighten_level_missing")
    target_missing = _paired_target_missing(action, rec)
    if target_missing:
        return _result(review, state="could_not_price", reason=target_missing)
    if pkg is None:
        return _result(review, state="could_not_price", reason="no_package_row")
    if trade is None:
        return _result(review, state="could_not_price", reason="no_trade_row")
    if not bars:
        return _result(review, state="could_not_price", reason="no_candles")
    side = str(pkg.get("direction") or "").lower()
    entry, sl0 = _num(pkg.get("entry")), _num(pkg.get("sl"))
    if side not in ("long", "short") or entry is None or sl0 is None or abs(entry - sl0) <= 0:
        return _result(review, state="could_not_price", reason="package_geometry_missing")
    r_dist = abs(entry - sl0)
    meta = _meta(pkg)
    atr, trail_mult = _num(meta.get("atr")), _num(meta.get("trail_mult"))
    trail_dist = atr * trail_mult if atr and trail_mult else None
    st = review.get("state") or {}
    stop_now, tp = _num(st.get("sl")), _num(st.get("tp")) or _num(pkg.get("tp"))
    peak_r = _num(st.get("peak_r")) or 0.0
    t0 = _ts(review.get("reviewed_at"))
    if stop_now is None or t0 is None:
        return _result(review, state="could_not_price", reason="review_state_missing")
    hold = replay(bars, side=side, entry=entry, r_dist=r_dist, start_ts=t0, stop=stop_now, tp=tp,
                  extreme_r0=peak_r, trail_dist=trail_dist)
    if action in PAIRED:
        return _price_paired(review, rec, action, pkg, trade, bars, hold, side=side, entry=entry, r_dist=r_dist,
                             sl0=sl0, t0=t0, stop_now=stop_now, tp=tp, peak_r=peak_r, trail_dist=trail_dist,
                             meta=meta, computed_at=computed_at)
    recp = replay(bars, side=side, entry=entry, r_dist=r_dist, start_ts=t0, stop=stop_now, tp=tp,
                  extreme_r0=peak_r, trail_dist=trail_dist, tighten_to=level)
    closed = str(trade.get("status") or "").lower() == "closed"
    if not closed:
        to_date = {"hold_exit": hold, "rec_exit": recp,
                   "note": "trade still open: delta needs the realised exit; this is a replay to the last candle"}
        return _result(review, state="could_not_price", reason="trade_open", to_date=to_date)
    basis = dict(trade, stop_loss=sl0)                                   # R basis = the package's INITIAL stop
    lab = net_r_for_trade(basis)
    if lab is None:
        return _result(review, state="could_not_price", reason="realised_net_r_uncomputable")
    net_r = lab["net_R"]
    t_entry = _ts(pkg.get("created_at")) or _ts(meta.get("entry_time")) or _ts(trade.get("timestamp"))
    t_close = _ts(trade.get("closed_at"))
    fee_r, fund_r, slip_r, stack = cost_legs(trade, str(pkg.get("symbol")), entry, r_dist, lab["risk_usd"])

    def net_of(x: Optional[dict]) -> Optional[float]:
        if x is None:
            return None
        span = (t_close - t_entry) if (t_close and t_entry and t_close > t_entry) else None
        frac = ((x["ts"] - t_entry) / span) if span else 1.0
        return round(net_of_costs(x["gross_r"], fee_r, fund_r, slip_r, frac), 8)

    hold_net, rec_net = net_of(hold), net_of(recp)
    applied = bool(review.get("applied"))
    if applied:
        cf_r, rec_r = hold_net, net_r
        if hold is None:
            return _result(review, state="could_not_price", reason="hold_replay_unresolved_before_close")
        fidelity = "unvalidated"
    else:
        cf_r = net_r
        fidelity = _fidelity(hold_net, net_r)
        if fidelity == "replay_mismatch":                               # the replay cannot reproduce this trade's own exit
            return _result(review, state="could_not_price", reason="replay_mismatch")
        if fidelity == "unvalidated" and recp is not None:              # realised exit came by a path the replay does not model
            return _result(review, state="could_not_price", reason="hold_replay_unresolved")
        rec_r = rec_net if recp is not None else net_r                  # tighten never reached => the hold exit stands
    delta = round(rec_r - cf_r, 8)
    pol = review.get("shadow_policy") or {}
    cf_shadow = rec_r if pol.get("within_bound") is True else cf_r
    out = _outcome_row(review, trade, delta=delta, rec_r=round(rec_r, 8), cf_r=round(cf_r, 8),
                       cf_shadow=round(cf_shadow, 8), method="replay_v1:stop_first+trail", fidelity=fidelity,
                       stack=stack, computed_at=computed_at, net_r=net_r)
    return _result(review, state="priced", outcome=out)


def _paired_target_missing(action: str, rec: dict) -> Optional[str]:
    """The reason a paired action cannot be priced for want of its own target, else None."""
    if action in ("move_tp", "tp_revise", "widen_sl") and _num(rec.get("level")) is None:
        return f"{action}_level_missing"
    if action == "partial_close":
        f = _num(rec.get("size_fraction"))
        if f is None or not 0 < f < 1:
            return "partial_close_size_fraction_missing"
    if action == "add_entry" and _num(rec.get("size_fraction")) is None:
        return "add_entry_size_fraction_missing"
    if action == "change_size" and _num(rec.get("size_multiplier")) is None:
        return "change_size_size_multiplier_missing"
    return None


def exit_at_open(bars: List[dict], *, side: str, entry: float, r_dist: float, start_ts: float) -> Optional[dict]:
    """A market exit at the OPEN of the first bar opening at/after ``start_ts`` (None = no such bar)."""
    sign = 1.0 if side == "long" else -1.0
    for b in bars:
        if b["time"] >= start_ts:
            return {"gross_r": sign * (b["open"] - entry) / r_dist, "ts": b["time"], "reason": "close"}
    return None


def trade_action_delta(action: str, rec: dict, *, hold_net: float, act_net: Optional[float],
                       close_net: Optional[float], fee_r: float, slip_r: float) -> Optional[float]:
    """Net R the action adds over holding, in units of the ORIGINAL size. Pure. None = not priceable.

    ``hold_net`` / ``act_net`` / ``close_net`` are the hold replay, the action's own bracket replay
    (move_tp / widen_sl) and the exit-at-review-open, each net of cost."""
    if action in ("move_tp", "tp_revise", "widen_sl"):
        return None if act_net is None else act_net - hold_net
    if close_net is None:
        return None
    if action == "close":
        return close_net - hold_net
    if action == "partial_close":
        f = float(rec["size_fraction"])
        return f * (close_net - hold_net)
    m = (1.0 + float(rec["size_fraction"])) if action == "add_entry" else float(rec["size_multiplier"])
    # the size difference rides the hold path from the review-bar open; an ADDED slice pays a round trip
    extra_cost = (m - 1.0) * (fee_r + slip_r) if m > 1.0 else 0.0
    return (m - 1.0) * (hold_net - close_net) - extra_cost


def _price_paired(review: dict, rec: dict, action: str, pkg: dict, trade: dict, bars: List[dict],
                  hold: Optional[dict], *, side: str, entry: float, r_dist: float, sl0: float, t0: float,
                  stop_now: float, tp: Optional[float], peak_r: float, trail_dist: Optional[float], meta: dict,
                  computed_at: Optional[str]) -> dict:
    level = _num(rec.get("level"))
    act = None
    if action in ("move_tp", "tp_revise"):
        act = replay(bars, side=side, entry=entry, r_dist=r_dist, start_ts=t0, stop=stop_now, tp=level,
                     extreme_r0=peak_r, trail_dist=trail_dist)
    elif action == "widen_sl":
        act = replay(bars, side=side, entry=entry, r_dist=r_dist, start_ts=t0, stop=level, tp=tp,
                     extreme_r0=peak_r, trail_dist=trail_dist)
    shut = exit_at_open(bars, side=side, entry=entry, r_dist=r_dist, start_ts=t0)
    if str(trade.get("status") or "").lower() != "closed":
        return _result(review, state="could_not_price", reason="trade_open",
                       to_date={"hold_exit": hold, "action_exit": act, "close_at_open": shut,
                                "note": "trade still open: delta needs the realised exit; this is a replay to the last candle"})
    lab = net_r_for_trade(dict(trade, stop_loss=sl0))
    if lab is None:
        return _result(review, state="could_not_price", reason="realised_net_r_uncomputable")
    net_r = lab["net_R"]
    t_entry = _ts(pkg.get("created_at")) or _ts(meta.get("entry_time")) or _ts(trade.get("timestamp"))
    t_close = _ts(trade.get("closed_at"))
    fee_r, fund_r, slip_r, stack = cost_legs(trade, str(pkg.get("symbol")), entry, r_dist, lab["risk_usd"])

    def net_of(x: Optional[dict]) -> Optional[float]:
        if x is None:
            return None
        span = (t_close - t_entry) if (t_close and t_entry and t_close > t_entry) else None
        frac = ((x["ts"] - t_entry) / span) if span else 1.0
        return net_of_costs(x["gross_r"], fee_r, fund_r, slip_r, frac)

    hold_net = net_of(hold)
    if hold_net is None:
        return _result(review, state="could_not_price", reason="hold_replay_unresolved_before_close")
    delta = trade_action_delta(action, rec, hold_net=hold_net, act_net=net_of(act), close_net=net_of(shut),
                               fee_r=fee_r, slip_r=slip_r)
    if delta is None:
        return _result(review, state="could_not_price", reason=f"{action}_replay_unresolved")
    if review.get("applied"):
        cf_r, fidelity = hold_net, "unvalidated"
    else:
        fidelity = _fidelity(hold_net, net_r)
        if fidelity == "replay_mismatch":
            return _result(review, state="could_not_price", reason="replay_mismatch")
        cf_r = net_r
    rec_r = cf_r + delta
    out = _outcome_row(review, trade, delta=round(delta, 8), rec_r=round(rec_r, 8), cf_r=round(cf_r, 8),
                       cf_shadow=round(cf_r, 8), method=f"paired_replay_v1:{action}", fidelity=fidelity,
                       stack=stack, computed_at=computed_at, net_r=net_r)
    return _result(review, state="priced", outcome=out)


def _fidelity(replayed_hold: Optional[float], realised: float) -> str:
    if replayed_hold is None:
        return "unvalidated"          # replay never exited before the data ended: nothing to compare
    return "replay_matches_realised" if abs(replayed_hold - realised) <= FIDELITY_TOL_R else "replay_mismatch"


def _meta(pkg: dict) -> dict:
    m = pkg.get("meta")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = {}
    return m if isinstance(m, dict) else {}


def _outcome_row(review: dict, trade: Optional[dict], *, delta: Optional[float], rec_r: Optional[float],
                 cf_r: Optional[float], cf_shadow: Optional[float], method: str, fidelity: Optional[str],
                 stack: Optional[str], computed_at: Optional[str], net_r: Optional[float] = None) -> Optional[dict]:
    """A schema-valid outcomes row, or None when the trade has not closed (nothing to grade yet)."""
    if trade is None or str(trade.get("status") or "").lower() != "closed" or not trade.get("closed_at"):
        return None
    if net_r is None:                      # R basis is the package's INITIAL stop; trades.stop_loss is the trailed one
        return None
    if method == "no_path_change":
        cf_r, cf_shadow = net_r, net_r                                   # the realised path IS the hold path
    closed = _ts(trade.get("closed_at"))
    return {
        "schema_version": 1, "review_id": review["review_id"], "order_package_id": review["order_package_id"],
        "trade_id": review.get("trade_id"), "closed_at": _iso(closed) if closed else None,
        "computed_at": computed_at or _iso(datetime.now(timezone.utc).timestamp()),
        "net_r": round(net_r, 8), "pnl_provenance": "measured" if str(trade.get("cost_source") or "").lower() == "broker" else "estimated",
        "cf_r": cf_r, "cf_r_shadow_0_5": cf_shadow, "cf_method": method, "cf_provenance": "computed",
        "exit_reason": trade.get("exit_reason"),
        "action": (review.get("recommendation") or {}).get("action"), "applied": bool(review.get("applied")),
        "rec_r": rec_r, "delta_r": delta, "cf_cost_stack": stack, "replay_fidelity": fidelity,
    }


# --------------------------------------------------------------------------- batch + sources

def read_jsonl(p: Path) -> List[dict]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('{"_meta"'):
            out.append(json.loads(ln))
    return out


def price_all(reviews: Iterable[dict], packages: Dict[str, dict], trades: Dict[int, dict],
              candle_fn: Callable[[str, str], Optional[List[dict]]], computed_at: Optional[str] = None) -> List[dict]:
    """Price every review. ``candle_fn(symbol, interval)`` returns bars (``time`` epoch s, OHLC) or None."""
    cache: Dict[Tuple[str, str], Optional[List[dict]]] = {}
    res = []
    for rv in reviews:
        pkg = packages.get(rv["order_package_id"])
        tr = trades.get(int(rv["trade_id"])) if rv.get("trade_id") is not None else None
        bars = None
        if pkg is not None and (rv.get("recommendation") or {}).get("action") in ALTERING:
            tf = _meta(pkg).get("timeframe") or "1h"
            key = (str(pkg.get("symbol")), str(tf))
            if key not in cache:
                cache[key] = candle_fn(*key)
            bars = cache[key]
        res.append(price_review(rv, pkg, tr, bars, computed_at))
    return res


def fetch_diag(path: str) -> Any:
    """GET a /api/diag path through scripts/ops/diag_fetch.sh (exit 3 = use the relay: not handled here)."""
    p = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"diag_fetch {path}: exit {p.returncode}: {p.stderr.strip()[:200]}")
    return json.loads(p.stdout)


def fetch_candles_live(symbol: str, interval: str, limit: int = 1000) -> Optional[List[dict]]:
    if interval not in _TF_SECONDS:
        return None
    url = "https://ict-bot.duckdns.org/api/bot/candles?" + urllib.parse.urlencode(
        {"symbol": symbol, "interval": interval, "limit": limit})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.loads(r.read())
    except (OSError, ValueError) as exc:        # URLError/timeout are OSError; bad JSON is ValueError
        print(f"live_review_counterfactual: candles {symbol}/{interval} unavailable: {exc!r}", file=sys.stderr)
        return None
    bars = d.get("candles") or []
    return [b for b in bars if all(k in b for k in ("time", "open", "high", "low"))] or None


def load_live_sources(reviews: List[dict]) -> Tuple[Dict[str, dict], Dict[int, dict]]:
    pk = fetch_diag("journal?table=order_packages&limit=150")
    pk = pk.get("rows", pk) if isinstance(pk, dict) else pk
    packages = {p["order_package_id"]: p for p in pk}
    trades: Dict[int, dict] = {}
    for off in (0, 1000, 2000):
        page = fetch_diag(f"journal?table=trades&limit=1000&offset={off}")
        page = page.get("rows", page) if isinstance(page, dict) else page
        trades.update({int(t["id"]): t for t in page})
        if len(page) < 1000 or {int(r["trade_id"]) for r in reviews if r.get("trade_id") is not None} <= set(trades):
            break
    return packages, trades


def append_outcomes(results: List[dict], path: Path = OUTCOMES) -> int:
    have = {r["review_id"] for r in read_jsonl(path)}
    new = [r["outcome"] for r in results if r.get("outcome") and r["review_id"] not in have]
    if new:
        with path.open("a") as f:
            for o in new:
                f.write(json.dumps(o, sort_keys=True) + "\n")
    return len(new)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="read packages/trades via diag_fetch.sh and candles from the public API")
    ap.add_argument("--reviews", default=str(REVIEWS))
    ap.add_argument("--write", action="store_true", help="append computed outcome rows for CLOSED trades (idempotent by review_id)")
    a = ap.parse_args(argv)
    if not a.live:
        ap.error("only --live is wired on the CLI; tests and the grader call price_all() with their own sources")
    reviews = read_jsonl(Path(a.reviews))
    packages, trades = load_live_sources(reviews)
    res = price_all(reviews, packages, trades, fetch_candles_live)
    from collections import Counter
    print(json.dumps({"n_reviews": len(res), "by_state": Counter(r["state"] for r in res),
                      "by_reason": Counter(r["reason"] for r in res if r["reason"])}, indent=1))
    if a.write:
        print(f"appended {append_outcomes(res)} outcome row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
