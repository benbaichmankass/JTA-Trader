#!/usr/bin/env python3
# wiring: called by .github/workflows/desk-decisions-mirror.yml (hourly, writes comms/desk/role_grade.json) and
#   .github/workflows/live-review-rows-mirror.yml (hourly, prices closed live reviews); read by /performance-review.
"""DESK-9-GRADING -- how good are Claude's recorded decisions, per role, and how much evidence is there?

    python3 scripts/ops/claude_role_grade.py                     # markdown, records on main, no network
    python3 scripts/ops/claude_role_grade.py --live              # + forward candles (no_trade counterfactual), LTR journal
    python3 scripts/ops/claude_role_grade.py --live --write comms/desk/role_grade.json
    python3 scripts/ops/claude_role_grade.py --self-test

The roll-up over the graders CLAUDE-GRADE-LOOP / LTR-5 already built (``desk_grade.py``, ``live_review_grade.py``,
``claude_calibration.py``). It keeps no store of its own beyond the optional ``--write`` snapshot; it adds the two
things those graders lack:

1. THE no_trade COUNTERFACTUAL. ``desk_outcomes.py`` leaves a ``no_trade`` decision ``not_computable`` (DESK-20). Here a
   ``no_trade`` is priced against what ENTERING WOULD HAVE DONE, on the real forward path, net of the full cost stack,
   in the packet's own units (``atr_stop_1x`` R, hold to ``HORIZON_BARS`` closes -- the same definition as the packet's
   ``history.rows`` random-entry baseline, so the two are comparable):
     * ``random_entry`` = mean net R over every (universe symbol, side) cell entered at the last closed bar's close;
     * ``near_signal``  = the strategies' own near-signals in that packet (mean, and the strongest = fewest
       ``bars_to_signal``); None when the packet listed none (n=0, never 0 R);
     * ``top_alternative`` = the best ``propose_entry`` the desk ITSELF listed in ``alternatives[]`` and declined (highest
       ex-ante ``mean_r``), priced on the real forward path;
     * ``hindsight_best_cell`` = the best cell in hindsight -- an UPPER BOUND shown for scale, never graded.
   VERDICT BASIS = ``abstain_value = 0 - top_alternative`` (positive: declining the desk's own best candidate was right).
   It is the basis because it can FAIL: the random-entry mean over both sides is ~ -cost by symmetry, so
   ``abstain_value_vs_random`` is positive by construction and is reported as context only. A cell whose forward bars
   do not exist yet (market closed) is waited for up to GRACE_DAYS, then excluded and counted; a decision with fewer
   than half its cells priced is ``could_not_look``, never a grade.
   STATED LIMITS: consecutive hourly decisions share forward bars, so the verdict runs on an INDEPENDENT subset (greedy,
   spaced >= HORIZON_BARS); a no_trade is graded against the cell average, not against the one trade the desk would
   have picked, so it measures "was abstaining right on average", not "did it miss the best trade" (the hindsight
   bound shows that scale).
2. THE n LEDGER. Per (role, action class): recorded / graded / not-yet-graded with the reason, the n the rule needs, an
   explicit state (``graded`` | ``insufficient_n`` | ``no_data`` | ``not_gradeable_by_design``) -- ``could not grade`` is
   never folded into a grade -- and the earliest date the class can reach that n at the trailing-7-day accrual rate.

RULES (registered here before any run reads them; tests pin them)
* ``N_NEEDED`` 20 per LTR action class (the operator's ADOPTED CLAUDE-GRADE-LOOP rule: CI95 of delta_r < 0 -> propose
  recommend-only; > 0 and not OVERCONFIDENT -> propose the next scope step; OVERCONFIDENT at n >= 10 -> propose a
  confidence floor -- proposals only); 30 for desk proposals vs random (``desk_grade.EDGE_MIN_N``); 20 independent
  no_trade windows.
* ETA = now + (N_NEEDED - graded - pending) / recorded-per-day + lag (no_trade: ``pending`` counts only the already-recorded
  decisions that would be INDEPENDENT windows, and the rate is capped at one per horizon, 2/day). It assumes every new call prices, so it is the
  EARLIEST date, labelled ``eta_earliest``; None (named) when the class had no recorded call in 7 days.

Exit 0 always for a readable record (a thin class is a state, not a failure) · 2 records unreadable.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research", REPO / "scripts" / "ci"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import desk_grade as dg  # noqa: E402

HORIZON_BARS = 12
N_NEEDED_LTR = 20
N_NEEDED_NO_TRADE = 20
ACCRUAL_DAYS = 7
MIN_CELL_SHARE = 0.5
GRACE_DAYS = 3        # cells whose market was closed get this long to accrue horizon bars before they are excluded and counted
Bar = Dict[str, float]
ALTERING = ("tighten_sl", "tp_revise", "partial_close", "close", "move_tp", "widen_sl", "change_size", "add_entry")
BY_DESIGN = ("flag_mechanics", "no_recommendation", "file_hypothesis", "watch_note")


# ----------------------------------------------------------------------------- the no_trade counterfactual
def _cost(symbol: str, entry: float, exit_px: float, risk: float, hold_hours: float) -> float:
    import desk_scan_packet as dsp
    from src.runtime import execution_costs as xc
    fee, slip, fund = dsp.cost_policy(symbol)
    return xc.roundtrip_cost_r(entry=entry, exit_price=exit_px, risk=risk, hold_hours=hold_hours, fee_bps_roundtrip=fee,
                               slippage_bps_roundtrip=slip, funding_bps_per_window=fund)["total_cost_r"]


def price_no_trade(decision: dict, packet: Optional[dict], candles: Callable[[str, str], Optional[List[Bar]]],
                   now: datetime, horizon: int = HORIZON_BARS,
                   cost: Callable[..., float] = _cost) -> Dict[str, Any]:
    """Price one ``no_trade`` against entering. Returns a dict with ``state``: priced | awaiting | could_not_look."""
    import desk_scan_packet as dsp
    if packet is None:
        return {"state": "could_not_look", "reason": "packet missing from comms/desk/packets"}
    cutoff = dg._ts(decision.get("info_cutoff_at"))
    if cutoff is None:
        return {"state": "could_not_look", "reason": "info_cutoff_at unreadable"}
    cells = [(u["symbol"], u["timeframe"]) for u in packet.get("universe") or [] if u.get("symbol") and u.get("timeframe") in dsp.TF_SECONDS]
    if not cells:
        return {"state": "could_not_look", "reason": "packet universe empty or untimed"}
    sec = dsp.TF_SECONDS[cells[0][1]]
    if now < cutoff + timedelta(seconds=sec * horizon):
        return {"state": "awaiting", "ready_at": (cutoff + timedelta(seconds=sec * horizon)).isoformat()}
    near = {(i["symbol"], i["side"]): i.get("bars_to_signal")
            for i in (packet.get("system_book") or {}).get("items") or [] if i.get("status") == "near_signal" and i.get("symbol") and i.get("side")}
    cell_r: Dict[tuple, float] = {}
    n_missing = 0
    for sym, tf in cells:
        bars = candles(sym, tf)
        if not bars:
            n_missing += 1
            continue
        hist = dsp.closed_before(bars, tf, cutoff)
        atr = dsp.atr_series(hist)[-1] if len(hist) > dsp.ATR_PERIOD else None
        fwd = [b for b in dsp.closed_before(bars, tf, now) if b["time"] >= hist[-1]["time"] + dsp.TF_SECONDS[tf]] if hist else []
        if not atr or len(fwd) < horizon:
            n_missing += 1        # market closed / not enough forward bars: excluded and counted, never zero
            continue
        c0, c1 = hist[-1]["close"], fwd[horizon - 1]["close"]
        k = cost(sym, c0, c1, atr, horizon * dsp.TF_SECONDS[tf] / 3600.0)
        for side, sgn in (("long", 1.0), ("short", -1.0)):
            cell_r[(sym, side)] = sgn * (c1 - c0) / atr - k
    if n_missing and now < cutoff + timedelta(days=GRACE_DAYS):
        # a closed market (or a transient candle miss) is not a reason to price on a crypto-only subset: wait for the grace
        return {"state": "awaiting", "ready_at": (cutoff + timedelta(days=GRACE_DAYS)).isoformat(),
                "waiting_on": f"{n_missing} of {len(cells)} symbols lack {horizon} forward bars"}
    if len(cell_r) < MIN_CELL_SHARE * 2 * len(cells):
        return {"state": "could_not_look", "reason": f"{len(cell_r) // 2} of {len(cells)} symbols had {horizon} forward bars"}
    rnd = statistics.fmean(cell_r.values())
    alts = [a for a in decision.get("alternatives") or [] if a.get("action") == "propose_entry" and a.get("symbol") and a.get("side")
            and a.get("mean_r") is not None and (a["symbol"], a["side"]) in cell_r]
    top = max(alts, key=lambda a: a["mean_r"]) if alts else None   # the best candidate the desk itself listed and declined
    ns = [(near[k], cell_r[k]) for k in near if k in cell_r]
    strongest = min(ns, key=lambda t: (t[0] is None, t[0] if t[0] is not None else 0))[1] if ns else None
    return {"state": "priced", "horizon_bars": horizon, "n_cells": len(cell_r), "n_symbols_unavailable": n_missing,
            "random_entry": round(rnd, 4), "near_signal_n": len(ns),
            "near_signal_mean": round(statistics.fmean(r for _, r in ns), 4) if ns else None,
            "near_signal_strongest": None if strongest is None else round(strongest, 4),
            "hindsight_best_cell": round(max(cell_r.values()), 4), "abstain_value_vs_random": round(-rnd, 4),
            "top_alternative": None if top is None else {"symbol": top["symbol"], "side": top["side"], "r": round(cell_r[(top["symbol"], top["side"])], 4)},
            "abstain_value": None if top is None else round(-cell_r[(top["symbol"], top["side"])], 4)}


def independent(priced: List[Dict[str, Any]], horizon: int = HORIZON_BARS, tf_hours: float = 1.0) -> List[Dict[str, Any]]:
    """Greedy subset of priced windows spaced >= the horizon (they share no forward bar)."""
    out, last = [], None
    for p in sorted(priced, key=lambda p: p["cutoff"]):
        if last is None or p["cutoff"] - last >= timedelta(hours=horizon * tf_hours):
            out.append(p)
            last = p["cutoff"]
    return out


def grade_no_trade(decisions: List[dict], packets: Callable[[str], Optional[dict]],
                   candles: Optional[Callable[[str, str], Optional[List[Bar]]]], now: datetime) -> Dict[str, Any]:
    nts = [d for d in decisions if d.get("role") == "entry_generation" and d.get("action") == "no_trade"]
    priced, awaiting, cnl = [], [], Counter()
    for d in nts:
        if candles is None:
            cnl["candles not read (run with --live)"] += 1
            continue
        r = price_no_trade(d, packets(d.get("packet_id")), candles, now)
        if r["state"] == "priced":
            priced.append(dict(r, cutoff=dg._ts(d["info_cutoff_at"]), decision_id=d["decision_id"]))
        elif r["state"] == "awaiting":
            awaiting.append(r["ready_at"])
        else:
            cnl[r["reason"]] += 1
    ind_recorded = independent([{"cutoff": dg._ts(d.get("info_cutoff_at"))} for d in nts if dg._ts(d.get("info_cutoff_at"))])
    ind = independent([p for p in priced if p["abstain_value"] is not None])
    n_no_alt = len(priced) - sum(1 for p in priced if p["abstain_value"] is not None)
    av = [p["abstain_value"] for p in ind]
    st = dg._stats(av)
    if len(av) < N_NEEDED_NO_TRADE or st["ci95"] is None:
        verdict, state = f"INSUFFICIENT_N ({len(av)} independent < {N_NEEDED_NO_TRADE})", "insufficient_n"
    else:
        lo, hi = st["ci95"]
        verdict = "NO_TRADE_ADDS_VALUE" if lo > 0 else "NO_TRADE_COSTS_VALUE" if hi < 0 else "INDETERMINATE (interval includes 0)"
        state = "graded"
    near_all = [p["near_signal_mean"] for p in priced if p["near_signal_mean"] is not None]
    return {"state": state, "verdict": verdict, "horizon_bars": HORIZON_BARS,
            "n_recorded": len(nts), "n_priced": len(priced), "n_independent": len(ind), "n_independent_recorded": len(ind_recorded), "n_awaiting": len(awaiting),
            "n_could_not_look": sum(cnl.values()), "could_not_look_reasons": dict(cnl),
            "abstain_value_independent": st, "n_priced_without_listed_alternative": n_no_alt,
            "abstain_value_all_overlapping": dg._stats([p["abstain_value"] for p in priced if p["abstain_value"] is not None]),
            "abstain_vs_random_mean": round(statistics.fmean(p["abstain_value_vs_random"] for p in priced), 4) if priced else None,
            "near_signal_mean_r_independent": dg._stats(near_all), "n_without_near_signals": len(priced) - len(near_all),
            "hindsight_best_cell_mean": round(statistics.fmean(p["hindsight_best_cell"] for p in priced), 4) if priced else None,
            "awaiting_ready_at": sorted(awaiting),
            "limits": "overlapping hourly windows (verdict uses the independent subset); cell-average baseline, not the best trade; "
                      "hindsight_best_cell is an upper bound, never graded; abstain vs random is ~ the round-trip cost by symmetry (context only)"}


# ----------------------------------------------------------------------------- the n ledger
def _rate_per_day(times: List[Optional[datetime]], now: datetime) -> Optional[float]:
    ts = [t for t in times if t is not None and t >= now - timedelta(days=ACCRUAL_DAYS)]
    if not ts:
        return None
    span = max(1 / 24, min(ACCRUAL_DAYS, (now - min(ts)).total_seconds() / 86400))
    return round(len(ts) / span, 3)


def eta(graded: int, pending: int, needed: int, rate: Optional[float], lag_days: float, now: datetime,
        ready_ats: Optional[List[str]] = None) -> Dict[str, Any]:
    """Earliest date a class reaches ``needed`` graded rows, assuming every new call prices."""
    short = needed - graded
    if short <= 0:
        return {"eta_earliest": None, "eta_note": "already at n_needed"}
    ready = sorted(t for t in (dg._ts(x) for x in ready_ats or []) if t)
    if pending >= short and ready:
        return {"eta_earliest": ready[min(short, len(ready)) - 1].date().isoformat(), "eta_note": "from rows already recorded"}
    if not rate:
        return {"eta_earliest": None, "eta_note": f"no recorded call in the last {ACCRUAL_DAYS} days: no accrual to extrapolate"}
    need_new = short - pending
    t = now + timedelta(days=need_new / rate + lag_days)
    return {"eta_earliest": t.date().isoformat(),
            "eta_note": f"{need_new} more call(s) at {rate}/day + {round(lag_days, 2)}d to price; earliest, assumes each prices"}


def _row(role: str, klass: str, *, recorded: int, graded: int, not_yet: int, why: Dict[str, int], needed: Optional[int],
         pending: Optional[int] = None,
         verdict: Optional[str], rate: Optional[float], lag_days: float, now: datetime, state: Optional[str] = None,
         ready_ats: Optional[List[str]] = None, extra: Optional[dict] = None) -> Dict[str, Any]:
    if state is None:
        state = "no_data" if recorded == 0 else "insufficient_n" if needed and graded < needed else "graded"
    row = {"role": role, "class": klass, "n_recorded": recorded, "n_graded": graded, "n_not_yet_graded": not_yet,
           "not_yet_graded_breakdown": why, "n_needed": needed, "state": state, "verdict": verdict,
           "recorded_per_day_7d": rate}
    row.update(eta(graded, not_yet if pending is None else pending, needed, rate, lag_days, now, ready_ats) if needed and state != "not_gradeable_by_design" else {"eta_earliest": None, "eta_note": "n/a"})
    row.update(extra or {})
    return row


def role_table(desk_g: Dict[str, Any], ltr_g: Optional[Dict[str, Any]], nt_g: Dict[str, Any], decisions: List[dict],
               reviews: List[dict], now: datetime) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    dpop = desk_g["population"]
    props = [d for d in decisions if d.get("role") == "entry_generation" and d.get("action") == "propose_entry"]
    rows.append(_row("entry_generation", "propose_entry vs random entry", recorded=len(props),
                     graded=desk_g["vs_random"]["n"], not_yet=len(props) - desk_g["vs_random"]["n"],
                     why={"awaiting_horizon": dpop["n_proposals_awaiting"], "expired_unfilled": dpop["n_proposals_expired_unfilled"],
                          "pre_cutoff_or_gate_ineligible": dpop["n_pre_cutoff_or_gate_ineligible"]},
                     needed=dg.EDGE_MIN_N, verdict=desk_g["vs_random"]["verdict"],
                     rate=_rate_per_day([dg._ts(d.get("judged_at")) for d in props], now), lag_days=1.0, now=now))
    nts = [d for d in decisions if d.get("role") == "entry_generation" and d.get("action") == "no_trade"]
    why = dict(nt_g["could_not_look_reasons"])
    if nt_g["n_awaiting"]:
        why["awaiting_horizon"] = nt_g["n_awaiting"]
    if nt_g["n_priced"] - nt_g["n_independent"]:
        why["priced_but_overlapping_not_independent"] = nt_g["n_priced"] - nt_g["n_independent"]
    rows.append(_row("entry_generation", "no_trade vs entering (counterfactual)", recorded=nt_g["n_recorded"],
                     graded=nt_g["n_independent"], not_yet=nt_g["n_recorded"] - nt_g["n_independent"], why=why,
                     pending=nt_g["n_independent_recorded"] - nt_g["n_independent"],
                     needed=N_NEEDED_NO_TRADE, verdict=nt_g["verdict"],
                     rate=min(_rate_per_day([dg._ts(d.get("judged_at")) for d in nts], now) or 0, 24 / HORIZON_BARS) or None,
                     lag_days=GRACE_DAYS, now=now,
                     extra={"abstain_value_mean_r": nt_g["abstain_value_independent"]["mean"],
                            "n_priced_overlapping": nt_g["n_priced"]}))
    for act in BY_DESIGN:
        n = sum(1 for d in decisions if d.get("action") == act)
        if n:
            rows.append(_row("entry_generation", act, recorded=n, graded=0, not_yet=0, why={}, needed=None, verdict=None,
                             rate=None, lag_days=0, now=now, state="not_gradeable_by_design"))
    if ltr_g is None:
        rows.append(_row("in_trade (live review)", "all", recorded=len(reviews), graded=0, not_yet=len(reviews),
                         why={"could_not_look: journal not read (run with --live)": len(reviews)}, needed=N_NEEDED_LTR,
                         verdict=None, rate=None, lag_days=1, now=now, state="could_not_look"))
        return rows
    acts: Dict[str, List[dict]] = {}
    for r in reviews:
        acts.setdefault((r.get("recommendation") or {}).get("action") or "unknown", []).append(r)
    ur = ltr_g["use_rules"]
    for act in ALTERING:
        rs = acts.get(act, [])
        u = ur.get(act, {})
        rows.append(_row("in_trade (live review)", act, recorded=len(rs), graded=u.get("n", 0), not_yet=len(rs) - u.get("n", 0),
                         why=dict(ltr_g["population"]["could_not_price_reasons"]) if rs else {}, needed=N_NEEDED_LTR,
                         verdict=u.get("verdict"), rate=_rate_per_day([dg._ts(r.get("reviewed_at")) for r in rs], now),
                         lag_days=1.0, now=now,
                         extra={"n_applied": u.get("n_applied", 0), "mean_delta_r": u.get("mean_dr"), "ci95_delta_r": u.get("ci95")}))
    holds = acts.get("hold", [])
    hv = ltr_g["hold_vs_close"]
    cal = ltr_g["calibration"].get("hold") or {}
    rows.append(_row("in_trade (live review)", "hold (vs close-at-review, ESTIMATED)", recorded=len(holds), graded=hv["n"],
                     not_yet=len(holds) - hv["n"], why={"trade_still_open_or_not_joined": len(holds) - hv["n"]} if holds else {},
                     needed=N_NEEDED_LTR, verdict=cal.get("verdict"), rate=_rate_per_day([dg._ts(r.get("reviewed_at")) for r in holds], now),
                     lag_days=2.0, now=now, extra={"mean_delta_r": hv.get("mean_dr"), "calibration_n": cal.get("n")}))
    for act in BY_DESIGN:
        rs = acts.get(act, [])
        if rs:
            rows.append(_row("in_trade (live review)", act, recorded=len(rs), graded=0, not_yet=0, why={}, needed=None,
                             verdict=None, rate=None, lag_days=0, now=now, state="not_gradeable_by_design"))
    return rows


def build(decisions: List[dict], outcomes: List[dict], reviews: List[dict], packets: Callable[[str], Optional[dict]],
          candles: Optional[Callable[[str, str], Optional[List[Bar]]]], ltr_g: Optional[Dict[str, Any]], now: datetime,
          system_trades=None) -> Dict[str, Any]:
    desk_g = dg.grade(decisions, outcomes, system_trades=system_trades)
    nt_g = grade_no_trade(decisions, packets, candles, now)
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "rule_sources": "CLAUDE-GRADE-LOOP (adopted), LTR-5, desk design § 4.7",
            "rows": role_table(desk_g, ltr_g, nt_g, decisions, reviews, now), "no_trade": nt_g,
            "desk": {"population": desk_g["population"], "vs_random": desk_g["vs_random"], "calibration": desk_g["calibration"]},
            "live_review_calibration": None if ltr_g is None else ltr_g["calibration"],
            "live_review_use_rules": None if ltr_g is None else ltr_g["use_rules"]}


def render(g: Dict[str, Any]) -> str:
    L = [f"## Claude decisions, per role (DESK-9-GRADING; {g['generated_at']})", "",
         "`n_graded` counts only rows the rule can grade; everything else is `n_not_yet_graded` with its reason. A thin class is a "
         "state (`insufficient_n`), never a grade; `eta_earliest` assumes every new call prices.", "",
         "| role | class | recorded | graded | not yet | needed | state | verdict | rate/day (7d) | eta earliest |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in g["rows"]:
        L.append(f"| {r['role']} | {r['class']} | {r['n_recorded']} | {r['n_graded']} | {r['n_not_yet_graded']} | {r['n_needed'] or '—'} "
                 f"| {r['state']} | {r['verdict'] or '—'} | {r['recorded_per_day_7d'] if r['recorded_per_day_7d'] is not None else '—'} "
                 f"| {r['eta_earliest'] or '—'} |")
    nt = g["no_trade"]
    L += ["", f"**no_trade counterfactual** (h={nt['horizon_bars']} bars, net of cost; {nt['n_recorded']} recorded, {nt['n_priced']} priced, "
          f"{nt['n_independent']} independent, {nt['n_awaiting']} awaiting, {nt['n_could_not_look']} could not look {nt['could_not_look_reasons'] or ''}): "
          f"declining the desk's own best listed candidate was worth {nt['abstain_value_independent']['mean']} R on average (CI95 {nt['abstain_value_independent']['ci95']}, "
          f"n={nt['abstain_value_independent']['n']} independent; {nt['n_priced_without_listed_alternative']} priced decisions listed no alternative); all-overlapping mean "
          f"{nt['abstain_value_all_overlapping']['mean']}; vs a random entry {nt['abstain_vs_random_mean']} (~ the cost, positive by symmetry: context only); the strategies' near-signals averaged "
          f"{nt['near_signal_mean_r_independent']['mean']} R (n={nt['near_signal_mean_r_independent']['n']}); hindsight best cell averaged "
          f"{nt['hindsight_best_cell_mean']} R (upper bound, not a grade). **{nt['verdict']}**. Limits: {nt['limits']}."]
    return "\n".join(L)


# ----------------------------------------------------------------------------- CLI
def _live_ltr(reviews: List[dict]) -> Optional[Dict[str, Any]]:
    import live_review_counterfactual as cf
    import live_review_grade as lg
    try:
        packages, trades = cf.load_live_sources(reviews)
        return lg.grade(reviews, cf.price_all(reviews, packages, trades, cf.fetch_candles_live))
    except Exception as exc:  # allow-silent: reported as could_not_look in the ledger, never a grade
        print(f"claude_role_grade: LTR journal unreadable: {type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr)
        return None


SNAPSHOT_MAX_AGE_H = 20


def _stable(g: Dict[str, Any]) -> list:
    return [[r["role"], r["class"], r["n_recorded"], r["n_graded"], r["n_not_yet_graded"], r["state"], r["verdict"]] for r in g["rows"]]


def write_snapshot(g: Dict[str, Any], path: Path, now: datetime) -> bool:
    """Write the JSON snapshot unless it would only change a timestamp/rate: rewritten when an n, state or verdict moved or the
    file is >= SNAPSHOT_MAX_AGE_H old (one landing PR a day at most when nothing moved). Returns True when written."""
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            age = now - datetime.fromisoformat(old["generated_at"].replace("Z", "+00:00"))
            if _stable(old) == _stable(g) and age < timedelta(hours=SNAPSHOT_MAX_AGE_H):
                return False
        except (OSError, ValueError, KeyError):
            pass  # unreadable snapshot: replace it
    path.write_text(json.dumps(g, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="read forward candles and the VM journal")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", help="write the JSON snapshot here (e.g. comms/desk/role_grade.json)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    now = datetime.now(timezone.utc)
    try:
        decisions = dg.read_jsonl(dg.DECISIONS)
        outcomes = dg.read_jsonl(dg.OUTCOMES)
        import live_review_counterfactual as cf
        reviews = cf.read_jsonl(cf.REVIEWS)
    except (OSError, ValueError) as exc:
        print(f"claude_role_grade: records unreadable: {exc}", file=sys.stderr)
        return 2
    candles = None
    cache: Dict[tuple, Optional[List[Bar]]] = {}
    if a.live:
        import desk_scan_packet as dsp

        def candles(sym: str, tf: str) -> Optional[List[Bar]]:
            if (sym, tf) not in cache:
                cache[(sym, tf)] = dsp.candles_from_api([sym], tf).get(sym)
            return cache[(sym, tf)]
    g = build(decisions, outcomes, reviews, dg.load_packet, candles, _live_ltr(reviews) if a.live else None, now)
    if a.write:
        print(f"claude_role_grade: snapshot {'written' if write_snapshot(g, Path(a.write), now) else 'unchanged'}: {a.write}", file=sys.stderr)
    print(json.dumps(g, indent=1, default=str) if a.json else render(g))
    return 0


def _self_test() -> int:
    t0 = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    sec = 3600

    def bars(drift: float) -> List[Bar]:
        out, px = [], 100.0
        for i in range(60):
            px += drift + (0.5 if i % 2 else -0.5)
            out.append({"time": int(t0.timestamp()) + (i - 30) * sec, "open": px, "high": px + 0.4, "low": px - 0.4, "close": px})
        return out
    cut = t0
    d = {"decision_id": "DD-20261026T0000Z-scan-1h-1", "packet_id": "P", "role": "entry_generation", "action": "no_trade",
         "info_cutoff_at": cut.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "alternatives": [{"action": "no_trade", "symbol": None, "side": None, "mean_r": 0.0},
                          {"action": "propose_entry", "symbol": "AAA", "side": "long", "mean_r": 0.3},
                          {"action": "propose_entry", "symbol": "BBB", "side": "short", "mean_r": 0.1}]}
    pk = {"universe": [{"symbol": "AAA", "timeframe": "1h"}, {"symbol": "BBB", "timeframe": "1h"}],
          "system_book": {"items": [{"status": "near_signal", "symbol": "AAA", "side": "long", "bars_to_signal": 1}]}}
    free = lambda s, e, x, r, h: 0.0  # noqa: E731
    r = price_no_trade(d, pk, lambda s, tf: bars(0.0 if s == "AAA" else 0.0), t0 + timedelta(hours=1), cost=free)
    assert r["state"] == "awaiting", r
    r = price_no_trade(d, pk, lambda s, tf: bars(0.0), t0 + timedelta(hours=14), cost=free)
    assert r["state"] == "priced" and abs(r["random_entry"]) < 1e-9 and r["near_signal_n"] == 1, r
    r = price_no_trade(d, pk, lambda s, tf: bars(0.2), t0 + timedelta(hours=14), cost=free)
    assert r["abstain_value"] < 0 < r["hindsight_best_cell"] and r["top_alternative"]["symbol"] == "AAA", r   # rising market: declining the long cost value
    assert abs(r["abstain_value_vs_random"]) < 1e-9, r   # long/short symmetric: random entry ~ 0 before cost
    part = lambda s, tf: bars(0.0) if s == "AAA" else None  # noqa: E731
    assert price_no_trade(d, pk, part, t0 + timedelta(hours=14), cost=free)["state"] == "awaiting"  # BBB missing, inside grace
    assert price_no_trade(d, pk, part, t0 + timedelta(days=4), cost=free)["state"] == "priced"       # 1 of 2 symbols >= half
    assert price_no_trade(d, pk, lambda s, tf: None, t0 + timedelta(days=4), cost=free)["state"] == "could_not_look"
    assert price_no_trade(d, None, lambda s, tf: bars(0), t0 + timedelta(hours=14))["state"] == "could_not_look"
    ps = [{"cutoff": t0 + timedelta(hours=i), "abstain_value": 0.1} for i in range(30)]
    assert len(independent(ps)) == 3, len(independent(ps))   # 0,12,24
    import tempfile
    snap = Path(tempfile.mkdtemp()) / "s.json"
    g0 = {"generated_at": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": [{"role": "r", "class": "c", "n_recorded": 1, "n_graded": 0,
          "n_not_yet_graded": 1, "state": "insufficient_n", "verdict": None}]}
    assert write_snapshot(g0, snap, t0) and not write_snapshot(g0, snap, t0 + timedelta(hours=3))
    g1 = json.loads(json.dumps(g0)); g1["rows"][0]["n_graded"] = 1
    assert write_snapshot(g1, snap, t0 + timedelta(hours=3)) and write_snapshot(g1, snap, t0 + timedelta(hours=30))
    e = eta(0, 0, 20, 2.0, 0.5, t0)
    assert e["eta_earliest"] == (t0 + timedelta(days=10.5)).date().isoformat(), e
    assert eta(0, 0, 20, None, 0.5, t0)["eta_earliest"] is None
    assert eta(25, 0, 20, 1.0, 0, t0)["eta_note"] == "already at n_needed"
    print("claude_role_grade self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
