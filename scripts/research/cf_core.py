#!/usr/bin/env python3
# wiring: library — the ONE counterfactual replay engine (CF-B0-ENGINE-LIFT); imported by counterfactual_grader.py (live, hourly via
# .github/workflows/counterfactual-grade-closed.yml) and scripts/research/tm_bench.py. No other consumer may carry a copy.
"""cf_core: the counterfactual engine, lifted out of counterfactual_grader.py so every consumer shares ONE copy.

Pure and OFFLINE: nothing here fetches at import or call time (bars, journal rows and equity come IN as arguments; the
live fetchers stay in counterfactual_grader.py, and historical bars come from cf_bars.py). Exports ``stitch_bars``,
``simulate``, ``cost_model``, ``net_of``, ``resolve_horizon``, ``post_exit_block``, ``grade_package`` and the constants.
Behaviour is byte-identical to the pre-lift grader (tests/test_cf_core.py golden). Schema and biases: see the docstring of
counterfactual_grader.py (kept there so existing readers of that doc still find it).
"""
from __future__ import annotations

import hashlib
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import live_review_counterfactual as lrc  # noqa: E402  (_num/_ts/_iso/initial_stop/_meta: pure helpers; its fetch_diag is not called here)
from src.runtime import provenance as prov  # noqa: E402
from src.runtime.execution_costs import DEFAULT_FEE_BPS_ROUNDTRIP, resolve_cost_policy  # noqa: E402

SCHEMA_VERSION = 2
# POST-EXIT HORIZON (GRADER-POST-EXIT-HORIZON): how long after the real close an arm may keep running before it is
# marked unresolved. The leg's own config max-hold (max_hold_hours / max_hold_bars / max_hold_min) wins; else this
# explicit per-timeframe default, recorded in every record as ``post_exit.horizon``.
DEFAULT_HORIZON_H = {"1m": 6.0, "5m": 24.0, "15m": 48.0, "30m": 72.0, "1h": 96.0, "2h": 144.0, "4h": 240.0}
FALLBACK_HORIZON_H = 48.0
VERDICT_TOL_R = 0.25      # |R difference| below this is "neutral" (stated here, not tuned per trade)
N_RANDOM = 300
SL_MULTS = (0.75, 1.0, 1.25, 1.5)
TP_RS = (2.0, 3.0, 4.0, 5.0, 6.0)
ATR_K = (1.5, 2.0, 3.0, 4.0)
TF_SEC = {"1m": 60, "5m": 300, "15m": 900}
BIASES = [
    "stop fills at its price (+ half round-trip slippage); a gap fills at the open",
    "a touch is not a fill: stop / TP need price to trade THROUGH the level (calibrated on one stop fill, n=1)",
    "intrabar order unknown: stop checked before TP; rule triggers and trails take effect from the next bar",
    "path stitched from the finest candles served (1m ~16h, 5m ~3.5d, 15m ~10d); older parts use coarser bars",
    "entry is the actual fill, shared by every arm; R unit = INITIAL risk (exit_plan.stop)",
    "an unresolved arm is marked at the last close and costed as closed there (resolved=false)",
    "post-exit bars end at t_close + horizon (leg max-hold, else a per-timeframe default); an arm open there is unresolved and never in a verdict",
    "post-exit excursions start at the first bar opening after the close; the bar containing the exit is excluded",
    "funding = policy default x windows held (ESTIMATED); account % = current equity less actual P&L (ESTIMATED)",
    "alt-bracket arms hold the risk budget constant (wider stop => smaller size); margin and lot size not modelled",
]

def stitch_bars(series: Dict[str, List[dict]], t0: float) -> List[dict]:
    """One non-overlapping bar path from t0 using the FINEST series available for each stretch.

    ``series`` maps '1m'/'5m'/'15m' to bars. Coarse bars end where the next finer series starts, rounded UP to a
    coarse boundary so no coarse bar straddles the seam. Each bar gains ``dur`` (seconds)."""
    order = [tf for tf in ("15m", "5m", "1m") if series.get(tf)]
    out: List[dict] = []
    for i, tf in enumerate(order):
        sec = TF_SEC[tf]
        bars = [b for b in series[tf] if b["time"] + sec > t0]
        if i + 1 < len(order):
            fine_start = min(b["time"] for b in series[order[i + 1]])
            cut = -(-fine_start // sec) * sec                         # ceil to this series' boundary
            bars = [b for b in bars if b["time"] + sec <= cut]
        else:
            cut = None
        lo = max([b["time"] + b["dur"] for b in out], default=t0)
        for b in bars:
            if b["time"] >= lo - 1e-9 or not out:
                out.append(dict(b, dur=sec))
    out.sort(key=lambda b: b["time"])
    # drop a coarse bar overlapped by the finer series that follows it
    clean: List[dict] = []
    for b in out:
        if clean and b["time"] < clean[-1]["time"] + clean[-1]["dur"] - 1e-9:
            continue
        clean.append(b)
    return clean


def simulate(bars: Sequence[dict], *, side: str, entry_ref: float, r_dist: float, t_entry: float,
             stop0: float, tp: Optional[float], actions: Sequence[dict] = (), rules: Sequence[dict] = (),
             trail_dist: Optional[float] = None) -> dict:
    """Replay one arm. Prices in, fills out. Pure.

    ``actions``  timed: ``{ts, kind: set_stop|set_tp|close, level|frac}``; effective on the first bar OPENING at/after ts.
                 ``set_stop`` only ever tightens; ``close`` exits ``frac`` of the position at that bar's open.
    ``rules``    conditional on the favourable extreme: ``{kind:'stop_at', trigger_r, level_r}`` (stop to entry_ref +
                 level_r in R once the extreme has reached trigger_r), effective from the next bar.
    ``trail_dist`` price distance behind the running extreme; the stop never loosens.
    Returns ``{fills:[{frac, px, ts, reason}], resolved, last_ts}``; an unresolved arm gets a final ``open_at_data_end``
    fill at the last close.
    """
    sign = 1.0 if side == "long" else -1.0
    stop, cur_tp = stop0, tp
    ext = entry_ref
    remaining = 1.0
    fills: List[dict] = []
    todo = sorted((dict(a) for a in actions), key=lambda a: a["ts"])
    fired = set()
    pending_stop: Optional[float] = None
    ext_r = 0.0
    tight = lambda new, old: (new > old) if sign > 0 else (new < old)   # noqa: E731
    last = None
    for b in bars:
        if b["time"] < t_entry:
            continue
        last = b
        o, h, lo = b["open"], b["high"], b["low"]
        if pending_stop is not None:
            if tight(pending_stop, stop):
                stop = pending_stop
            pending_stop = None
        while todo and todo[0]["ts"] <= b["time"]:
            a = todo.pop(0)
            if a["kind"] == "set_stop" and tight(a["level"], stop):
                stop = a["level"]
            elif a["kind"] == "set_tp":
                cur_tp = a["level"]
            elif a["kind"] == "close":
                f = min(remaining, float(a.get("frac", 1.0)))
                fills.append({"frac": f, "px": o, "ts": b["time"], "reason": "close"})
                remaining -= f
        if remaining <= 1e-12:
            break
        if (lo < stop) if sign > 0 else (h > stop):            # a touch is not a fill: price must trade THROUGH the stop
            px = min(stop, o) if sign > 0 else max(stop, o)
            fills.append({"frac": remaining, "px": px, "ts": b["time"], "reason": "stop"})
            remaining = 0.0
            break
        if cur_tp is not None and ((h > cur_tp) if sign > 0 else (lo < cur_tp)):
            px = max(cur_tp, o) if sign > 0 else min(cur_tp, o)
            fills.append({"frac": remaining, "px": px, "ts": b["time"], "reason": "tp"})
            remaining = 0.0
            break
        ext = max(ext, h) if sign > 0 else min(ext, lo)
        ext_r = sign * (ext - entry_ref) / r_dist
        if trail_dist is not None:
            t = ext - sign * trail_dist
            if tight(t, stop):
                stop = t
        for i, r in enumerate(rules):
            if i not in fired and ext_r >= r["trigger_r"]:
                fired.add(i)
                lvl = entry_ref + sign * r["level_r"] * r_dist
                if tight(lvl, stop if pending_stop is None else pending_stop):
                    pending_stop = lvl
    if remaining > 1e-12 and last is not None:
        fills.append({"frac": remaining, "px": last["close"], "ts": last["time"] + last["dur"], "reason": "open_at_data_end"})
    return {"fills": fills, "resolved": all(f["reason"] != "open_at_data_end" for f in fills) and bool(fills),
            "last_ts": fills[-1]["ts"] if fills else None}


def cost_model(trade: dict, symbol: str, entry_fill: float, qty: float) -> dict:
    """Cost stack in bps of entry price: fee (the trade's own recorded legs, else the policy default),
    exit slippage (half the policy round trip: the entry slippage is already in the fill) and funding per 8h."""
    slip_rt, fund_win = resolve_cost_policy(symbol)
    fee_usd = (lrc._num(trade.get("fee_taker_usd")) or 0.0) + (lrc._num(trade.get("fee_maker_usd")) or 0.0)
    src = str(trade.get("cost_source") or "").lower()
    if src in ("broker", "estimate") and fee_usd > 0 and qty and entry_fill:
        fee_bps, fsrc = fee_usd / (qty * entry_fill) * 1e4, f"recorded[{src}]"
    else:
        fee_bps, fsrc = DEFAULT_FEE_BPS_ROUNDTRIP, "policy_default"
    return {"fee_bps": fee_bps, "slip_exit_bps": slip_rt / 2.0, "fund_bps_window": fund_win, "fee_source": fsrc}


def net_of(sim: dict, *, side: str, entry_fill: float, r_dist: float, t_entry: float, cm: dict) -> dict:
    """Gross / cost / net R of a simulated arm (R unit = ``r_dist`` of THAT arm at the constant risk budget)."""
    sign = 1.0 if side == "long" else -1.0
    per_bp = entry_fill / r_dist / 1e4                              # 1 bp of entry price, in R
    gross = fund = slip = 0.0
    for f in sim["fills"]:
        gross += f["frac"] * sign * (f["px"] - entry_fill) / r_dist
        fund += f["frac"] * cm["fund_bps_window"] * per_bp * max(0.0, f["ts"] - t_entry) / 28800.0
        if f["reason"] != "tp":                                     # a TP rests as a limit: no taker slippage
            slip += f["frac"] * cm["slip_exit_bps"] * per_bp
    fee = cm["fee_bps"] * per_bp
    return {"gross_r": gross, "cost_r": {"fee": fee, "slip": slip, "funding": fund}, "net_r": gross - fee - slip - fund}


def resolve_horizon(pkg: dict, strategy_cfg: Optional[dict] = None) -> dict:
    """Seconds an arm may run past the real close. The leg's own max-hold wins, else the per-timeframe default."""
    cfg = strategy_cfg or {}
    tf = str(cfg.get("timeframe") or pkg.get("timeframe") or "")
    for key, mult in (("max_hold_hours", 3600.0), ("max_hold_min", 60.0)):
        v = lrc._num(cfg.get(key))
        if v and v > 0:
            return {"seconds": v * mult, "hours": round(v * mult / 3600.0, 3), "source": f"config.{key}", "timeframe": tf or None}
    v = lrc._num(cfg.get("max_hold_bars"))
    if v and v > 0 and tf in TF_SEC:
        return {"seconds": v * TF_SEC[tf], "hours": round(v * TF_SEC[tf] / 3600.0, 3), "source": "config.max_hold_bars", "timeframe": tf}
    if tf in DEFAULT_HORIZON_H:
        h = DEFAULT_HORIZON_H[tf]
        return {"seconds": h * 3600.0, "hours": h, "source": "default_by_timeframe", "timeframe": tf}
    return {"seconds": FALLBACK_HORIZON_H * 3600.0, "hours": FALLBACK_HORIZON_H, "source": "default_unknown_timeframe", "timeframe": tf or None}


def post_exit_block(arms: List[dict], bars: Sequence[dict], *, side: str, exit_px: Optional[float], tp0: Optional[float],
                    r_dist: float, t_close: float, horizon: dict, actual_r: Optional[float]) -> dict:
    """Pure: what happened AFTER the real exit, all from the committed replayed arms and the post-close path."""
    sign = 1.0 if side == "long" else -1.0
    h_end = t_close + horizon["seconds"]
    after = [b for b in bars if b["time"] >= t_close]
    reached = bool(bars) and (bars[-1]["time"] + bars[-1]["dur"]) >= h_end - 1e-6
    mfe = mae = None
    tp_reach = {"reached": None, "bars": None, "seconds": None}
    if after and exit_px is not None:
        mfe = round(max(sign * ((b["high"] if sign > 0 else b["low"]) - exit_px) for b in after) / r_dist, 4)
        mae = round(min(sign * ((b["low"] if sign > 0 else b["high"]) - exit_px) for b in after) / r_dist, 4)
    if tp0 is not None and after:
        hit = next((i for i, b in enumerate(after) if ((b["high"] > tp0) if sign > 0 else (b["low"] < tp0))), None)
        if hit is not None:
            tp_reach = {"reached": True, "bars": hit + 1, "seconds": round(after[hit]["time"] - t_close, 1)}
        else:      # "never" is only a finding when the whole horizon was observed; otherwise we could not look
            tp_reach = {"reached": False if reached else None, "bars": None, "seconds": None}
    wider = []
    held: List[dict] = []
    for a in arms:
        if a["family"] not in ("alt_brackets", "entry_brackets") or not a.get("exit"):
            continue
        last = a["exit"]
        ex_ts = lrc._ts(last["ts"])
        if ex_ts is None or ex_ts <= t_close:
            continue                                  # decided before the real exit: not a post-exit question
        held.append(a)
        mult = (a.get("params") or {}).get("sl_mult")
        if mult and mult > 1.0:
            wider.append({"arm_id": a["arm_id"], "sl_mult": mult, "tp_r": a["params"].get("tp_r"),
                          "survived": None if not a["resolved"] and last["reason"] == "open_at_data_end" else last["reason"] != "stop",
                          "resolved": a["resolved"], "net_r": a["net_r"] if a["resolved"] else None,
                          "marked_net_r_unresolved": None if a["resolved"] else a["net_r"], "exit_reason": last["reason"],
                          "delta_vs_actual_r": None if (actual_r is None or not a["resolved"]) else round(a["net_r"] - actual_r, 4),
                          "provenance": prov.ESTIMATED if a["resolved"] else prov.UNVERIFIED})
    res = [a for a in held if a["resolved"]]
    unres = [a for a in held if not a["resolved"]]
    verdict = {"verdict": None, "r_diff": None, "resolved": False, "n_held_arms": len(held), "n_unresolved": len(unres),
               "basis_arm": None, "provenance": prov.UNVERIFIED}
    if actual_r is not None and res:
        best = max(res, key=lambda a: a["net_r"])
        diff = round(best["net_r"] - actual_r, 4)
        v = "exited_early" if diff >= VERDICT_TOL_R else ("exit_saved_r" if diff <= -VERDICT_TOL_R else "neutral")
        # exited_early is established by a resolved arm alone; the other two need every held arm resolved
        verdict.update(verdict=v, r_diff=diff, basis_arm=best["arm_id"], provenance=prov.ESTIMATED,
                       resolved=(v == "exited_early") or not unres)
    return {"horizon": dict(horizon, end=lrc._iso(h_end)), "horizon_reached": reached, "mfe_r": mfe, "mae_r": mae,
            "tp_reach": tp_reach, "wider_sl_arms": wider, "verdict": verdict}


def _arm(arm_id: str, family: str, label: str, params: dict, sim: dict, legs: List[dict], cm_fn, side: str,
         entry_fill: float, r_dist: float, t_entry: float, equity: Dict[str, Optional[float]]) -> dict:
    n = net_of(sim, side=side, entry_fill=entry_fill, r_dist=r_dist, t_entry=t_entry, cm=cm_fn)
    last = sim["fills"][-1] if sim["fills"] else None
    per = {}
    for lg in legs:
        pnl = n["net_r"] * lg["risk_usd"] if lg["risk_usd"] else None
        eq = equity.get(lg["account_id"])
        per[lg["account_id"]] = {"pnl_usd": None if pnl is None else round(pnl, 4),
                                 "pct_of_account": None if (pnl is None or not eq) else round(pnl / eq * 100, 4),
                                 "account_class": lg["account_class"]}
    return {"arm_id": arm_id, "family": family, "label": label, "params": params, "resolved": sim["resolved"],
            "exit": None if last is None else {"ts": lrc._iso(last["ts"]), "px": round(last["px"], 8), "reason": last["reason"],
                                               "fills": [{"frac": round(f["frac"], 4), "px": round(f["px"], 8), "reason": f["reason"]}
                                                         for f in sim["fills"]]},
            "gross_r": round(n["gross_r"], 4), "cost_r": {k: round(v, 4) for k, v in n["cost_r"].items()},
            "net_r": round(n["net_r"], 4), "per_account": per, "provenance": "ESTIMATED"}


def _delta(arm: dict, base: Optional[dict], key: str) -> None:
    arm[key] = None if base is None else round(arm["net_r"] - base["net_r"], 4)


RANDOM_MODES = ("legacy_own_length", "causal")


def random_usable_bars(bars: Sequence[dict], *, t_entry: float, t_close: float, horizon_s: float, mode: str) -> List[dict]:
    """The bars a matched random intervention may be drawn on. ``causal`` never reads ``t_close``: the window is
    [t_entry, t_entry + horizon_s), one constant per leg, so the draw cannot know how long the trade will live."""
    if mode == "causal":
        return [b for b in bars if t_entry <= b["time"] < t_entry + horizon_s]
    if mode == "legacy_own_length":
        return [b for b in bars if t_entry <= b["time"] < t_close]
    raise ValueError(f"random_mode must be one of {RANDOM_MODES}, got {mode!r}")


def grade_package(pkg: dict, legs_in: List[dict], bars: List[dict], reviews: List[dict], actions: List[dict],
                  equity_now: Dict[str, Optional[float]], venue: Dict[str, dict],
                  graded_at: Optional[str] = None, n_random: int = N_RANDOM, horizon: Optional[dict] = None,
                  random_mode: str = "legacy_own_length") -> dict:
    """Pure: one graded record for one closed package. See counterfactual_grader.py's docstring for the schema.

    ``random_mode``: ``legacy_own_length`` (default: the pre-lift live behaviour, byte-identical) draws the random
    intervention times from [t_entry, t_close) -- the trade's OWN realised length, known only at its exit (lookahead).
    ``causal`` draws them from [t_entry, t_entry + horizon), a per-leg constant; an action landing after the trade has
    closed simply never applies. Bulk consumers pass ``causal`` (see ``random_usable_bars``)."""
    base = {"schema_version": SCHEMA_VERSION, "order_package_id": pkg["order_package_id"],
            "strategy": pkg.get("strategy_name"), "symbol": pkg.get("symbol"), "side": str(pkg.get("direction") or "").lower(),
            "graded_at": graded_at or lrc._iso(datetime.now(timezone.utc).timestamp()), "biases": BIASES}

    def no(reason: str) -> dict:
        return dict(base, status="could_not_grade", reason=reason)

    side = base["side"]
    meta = lrc._meta(pkg)
    entry_ref, stop0 = lrc._num(pkg.get("entry")), lrc.initial_stop(pkg)
    if side not in ("long", "short") or entry_ref is None or stop0 is None or abs(entry_ref - stop0) <= 0:
        return no("package_geometry_missing")
    r_dist = abs(entry_ref - stop0)
    tp0 = lrc._num(pkg.get("tp"))
    atr, trail_mult = lrc._num(meta.get("atr")), lrc._num(meta.get("trail_mult"))
    own_trail = atr * trail_mult if atr and trail_mult else None
    closed = [t for t in legs_in if str(t.get("status") or "").lower() == "closed" and t.get("closed_at")]
    if not legs_in or len(closed) != len(legs_in):
        return no("not_all_legs_closed")
    # the decision leg: the earliest real-money leg, else the earliest leg (its fill is the shared entry)
    legs_in = sorted(legs_in, key=lambda t: (t.get("account_class") != "real_money", t.get("timestamp") or ""))
    lead = legs_in[0]
    entry_fill = lrc._num(lead.get("entry_price")) or entry_ref
    t_entry = lrc._ts(lead.get("timestamp"))
    t_close = max(lrc._ts(t.get("closed_at")) for t in legs_in)
    if not bars or t_entry is None:
        return no("no_candles")
    horizon = horizon or resolve_horizon(pkg)
    bars = [b for b in bars if b["time"] < t_close + horizon["seconds"]]       # the path ends at the post-exit horizon
    if not bars:
        return no("no_candles")
    symbol = str(pkg.get("symbol"))
    cm_lead = cost_model(lead, symbol, entry_fill, lrc._num(lead.get("position_size")) or 0.0)

    legs: List[dict] = []
    for t in legs_in:
        acct, qty = t.get("account_id"), lrc._num(t.get("position_size")) or 0.0
        risk_usd = r_dist * qty
        pnl_j = lrc._num(t.get("pnl"))
        v = venue.get(acct) or {}
        legs.append({"account_id": acct, "trade_id": t.get("id"), "account_class": t.get("account_class"), "qty": qty,
                     "entry_fill": lrc._num(t.get("entry_price")), "exit_price": lrc._num(t.get("exit_price")) or v.get("avg_exit_price"),
                     "exit_reason": t.get("exit_reason"), "risk_usd": round(risk_usd, 6), "pnl_usd_journal": pnl_j,
                     "pnl_usd_venue": v.get("closed_pnl"), "closed_at": t.get("closed_at"),
                     "provenance": "MEASURED" if v.get("closed_pnl") is not None else ("ESTIMATED" if pnl_j is None else "MEASURED")})
    equity: Dict[str, Optional[float]] = {}
    for lg in legs:
        eq = equity_now.get(lg["account_id"])
        got = lg["pnl_usd_venue"] if lg["pnl_usd_venue"] is not None else lg["pnl_usd_journal"]
        equity[lg["account_id"]] = (eq - (got or 0.0)) if eq else None
        lg["equity_pre_usd"] = None if not equity[lg["account_id"]] else round(equity[lg["account_id"]], 2)

    arms: List[dict] = []

    def run(arm_id, family, label, params, *, stop=stop0, tp=tp0, acts=(), rules=(), trail=own_trail, r=r_dist):
        sim = simulate(bars, side=side, entry_ref=entry_ref, r_dist=r_dist, t_entry=t_entry,
                       stop0=stop, tp=tp, actions=acts, rules=rules, trail_dist=trail)
        a = _arm(arm_id, family, label, params, sim, legs, cm_lead, side, entry_fill, r, t_entry, equity)
        arms.append(a)
        return a

    sign = 1.0 if side == "long" else -1.0
    timed = [{"ts": a["ts_epoch"], "kind": "set_stop", "level": a["level"]} for a in actions]

    # ---- (a) actual: measured outcome, the venue pnl where it priced it
    actual_per = {}
    for lg in legs:
        usd = lg["pnl_usd_venue"] if lg["pnl_usd_venue"] is not None else lg["pnl_usd_journal"]
        eq = equity.get(lg["account_id"])
        actual_per[lg["account_id"]] = {"pnl_usd": None if usd is None else round(usd, 4),
                                        "pct_of_account": None if (usd is None or not eq) else round(usd / eq * 100, 4),
                                        "account_class": lg["account_class"]}
    lead_usd = actual_per[lead["account_id"]]["pnl_usd"]
    actual_r = None if lead_usd is None or not legs[0]["risk_usd"] else lead_usd / legs[0]["risk_usd"]
    actual = {"arm_id": "actual", "family": "actual", "label": "ACTUAL (journal / venue closed-pnl)", "params": {},
              "resolved": True, "exit": {"ts": legs[0].get("closed_at"), "px": legs[0]["exit_price"], "reason": legs[0]["exit_reason"]},
              "gross_r": None, "cost_r": None, "net_r": None if actual_r is None else round(actual_r, 4),
              "per_account": actual_per, "provenance": "MEASURED" if legs[0]["pnl_usd_venue"] is not None else "ESTIMATED",
              "note": "venue closed_pnl is booked net of the OPEN fee only; the simulated arms use the full recorded round trip"}
    arms.append(actual)

    # ---- baseline: the actual management replayed
    rep = run("replayed_actual", "baseline", "Actual management replayed (like-for-like baseline)", {"actions": len(timed)}, acts=timed)
    run("original_brackets", "entry_brackets", "Original SL/TP, no in-trade action (own trail only)", {})

    # ---- (c) alternative entry brackets, constant risk
    for m in SL_MULTS:
        for tr in TP_RS:
            if m == 1.0 and abs(tr - (abs(tp0 - entry_ref) / r_dist if tp0 else 4.0)) < 1e-6:
                continue
            rd = r_dist * m
            run(f"alt_sl{m:g}x_tp{tr:g}R", "alt_brackets", f"SL {m:g}x original distance, TP {tr:g}R", {"sl_mult": m, "tp_r": tr},
                stop=entry_ref + sign * -1.0 * rd, tp=entry_ref + sign * tr * rd, trail=None if own_trail is None else own_trail, r=rd)

    # ---- (d) less management: each applied action removed one at a time
    for i, a in enumerate(timed):
        rest = [x for j, x in enumerate(timed) if j != i]
        lbl = f"Without action {i + 1} ({lrc._iso(a['ts'])} stop->{a['level']:.5g}); kept: " + (", ".join(f"{x['level']:.5g}" for x in rest) or "none")
        run(f"less_without_action_{i + 1}", "less_management", lbl, {"removed": i + 1, "kept": len(rest)}, acts=rest)

    # ---- (e) more / different management
    for trig, lvl, lab in ((1.0, 0.0, "stop to break-even at +1R"), (1.5, 0.0, "stop to break-even at +1.5R"),
                           (2.0, 1.0, "lock +1R at +2R")):
        run(f"more_rule_{trig:g}R_to_{lvl:g}R", "more_management", lab, {"trigger_r": trig, "level_r": lvl},
            rules=[{"kind": "stop_at", "trigger_r": trig, "level_r": lvl}])
    run("more_rule_ladder_be1_lock2", "more_management", "ladder: BE at +1R, then lock +1R at +2R", {},
        rules=[{"kind": "stop_at", "trigger_r": 1.0, "level_r": 0.0}, {"kind": "stop_at", "trigger_r": 2.0, "level_r": 1.0}])
    if atr:
        for k in ATR_K:
            run(f"more_atr_trail_{k:g}x", "more_management", f"ATR trail {k:g} x ATR(entry) behind the extreme", {"k": k},
                trail=k * atr)
    for lg in legs[1:]:                                    # a sibling leg that was managed differently is a real alternative
        tc, tl = lrc._ts(lg.get("closed_at")), lrc._ts(legs[0].get("closed_at"))
        if tc and tl and tc < tl - 120 and lg.get("exit_reason") not in ("sl", "tp"):
            run(f"more_peer_{lg['account_id']}_{lg['exit_reason']}", "more_management",
                f"Close 100% at {lrc._iso(tc)} (what {lg['account_id']} did: {lg['exit_reason']})",
                {"account": lg["account_id"], "ts": lrc._iso(tc)}, acts=timed + [{"ts": tc, "kind": "close", "frac": 1.0}])
    for rv in reviews:
        rec = rv.get("recommendation") or {}
        act, lvl, t0 = rec.get("action"), lrc._num(rec.get("level")), lrc._ts(rv.get("reviewed_at"))
        if rv.get("applied") or t0 is None or act not in lrc.ALTERING:
            continue
        ac: Optional[dict] = None
        if act in ("tighten_sl", "widen_sl") and lvl is not None:
            ac = {"ts": t0, "kind": "set_stop", "level": lvl}
        elif act in ("move_tp", "tp_revise") and lvl is not None:
            ac = {"ts": t0, "kind": "set_tp", "level": lvl}
        elif act == "close":
            ac = {"ts": t0, "kind": "close", "frac": 1.0}
        elif act == "partial_close" and lrc._num(rec.get("size_fraction")):
            ac = {"ts": t0, "kind": "close", "frac": lrc._num(rec.get("size_fraction"))}
        if ac:
            run(f"more_unapplied_{rv['review_id'][-30:]}", "more_management", f"Unapplied review call {act} @ {rv.get('reviewed_at')}",
                {"review_id": rv["review_id"], "action": act, "level": lvl}, acts=timed + [ac])

    # ---- (f) matched random intervention (same class: stop-tighten, same count)
    rc = None
    if timed:
        seed = int(hashlib.sha256(base["order_package_id"].encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        usable = random_usable_bars(bars, t_entry=t_entry, t_close=t_close, horizon_s=horizon["seconds"], mode=random_mode)
        nets: List[float] = []
        for _ in range(n_random):
            acts = []
            if usable:
                cur_stop = stop0
                for b in sorted(rng.sample(usable, min(len(timed), len(usable))), key=lambda x: x["time"]):
                    px = b["open"]
                    lo_p, hi_p = (cur_stop, px) if sign > 0 else (px, cur_stop)   # a valid tighter stop lies between the live stop and the market
                    if hi_p - lo_p <= 1e-12:
                        continue
                    lvl = rng.uniform(lo_p, hi_p)
                    acts.append({"ts": b["time"], "kind": "set_stop", "level": lvl})
                    cur_stop = lvl if ((lvl > cur_stop) if sign > 0 else (lvl < cur_stop)) else cur_stop
            sim = simulate(bars, side=side, entry_ref=entry_ref, r_dist=r_dist, t_entry=t_entry,
                           stop0=stop0, tp=tp0, actions=acts, trail_dist=own_trail)
            nets.append(net_of(sim, side=side, entry_fill=entry_fill, r_dist=r_dist, t_entry=t_entry, cm=cm_lead)["net_r"])
        nets.sort()
        q = lambda p: round(nets[min(len(nets) - 1, int(p * len(nets)))], 4)    # noqa: E731
        rc = {"n": len(nets), "class": f"stop_tighten x{len(timed)}", "mean_r": round(sum(nets) / len(nets), 4),
              "p10_r": q(0.10), "p50_r": q(0.50), "p90_r": q(0.90),
              "p_random_ge_replayed_actual": round(sum(1 for x in nets if x >= rep["net_r"]) / len(nets), 4),
              "note": "random control uses unresolved marks where the path ends open (see resolved flags)"}
        if random_mode == "causal":
            rc["mode"] = "causal"

    for a in arms:
        if a["arm_id"] == "actual":
            a["delta_vs_replayed_actual_r"] = None if a["net_r"] is None else round(a["net_r"] - rep["net_r"], 4)
            a["delta_vs_actual_r"] = 0.0
            continue
        _delta(a, rep, "delta_vs_replayed_actual_r")
        a["delta_vs_actual_r"] = None if actual_r is None else round(a["net_r"] - actual_r, 4)
        a["delta_vs_replayed_actual_usd"] = {k: (None if v["pnl_usd"] is None or rep["per_account"][k]["pnl_usd"] is None
                                                 else round(v["pnl_usd"] - rep["per_account"][k]["pnl_usd"], 4))
                                             for k, v in a["per_account"].items()}
    rx = rep["exit"] or {}
    fid = {"replayed_exit": {"ts": rx.get("ts"), "px": rx.get("px")}, "actual_exit": {"ts": legs[0].get("closed_at"), "px": legs[0]["exit_price"]},
           "replayed_actual_net_r": rep["net_r"], "actual_net_r": None if actual_r is None else round(actual_r, 4),
           "abs_gap_r": None if actual_r is None else round(abs(rep["net_r"] - actual_r), 4)}
    po = post_exit_block(arms, bars, side=side, exit_px=legs[0]["exit_price"], tp0=tp0, r_dist=r_dist, t_close=t_close,
                         horizon=horizon, actual_r=actual_r)
    n_b = {tf: len([b for b in bars if b["dur"] == s]) for tf, s in TF_SEC.items()}
    return dict(base, status="graded", reason=None,
                bracket={"entry_pkg": entry_ref, "stop0": stop0, "stop0_source": "exit_plan.stop|risk_per_unit",
                         "tp": tp0, "tp_r": round(abs(tp0 - entry_ref) / r_dist, 3) if tp0 else None, "r_dist": r_dist,
                         "atr": atr, "trail_mult": trail_mult},
                legs=legs,
                path={"bars": len(bars), "bars_by_tf": n_b, "first_bar": lrc._iso(bars[0]["time"]),
                      "last_bar": lrc._iso(bars[-1]["time"] + bars[-1]["dur"]), "t_entry": lrc._iso(t_entry), "t_close": lrc._iso(t_close)},
                actions=[{k: v for k, v in a.items() if k != "ts_epoch"} | {"ts": lrc._iso(a["ts_epoch"])} for a in actions],
                arms=arms, random_control=rc, fidelity=fid, post_exit=po)
