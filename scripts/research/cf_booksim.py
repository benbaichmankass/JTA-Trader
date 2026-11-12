#!/usr/bin/env python3
# wiring: manual-only - CF-D3-BOOKSIM book-level USD simulation (imports RiskManager.position_size) + AM-REGRADE-BOOKSIM grade; no scheduler
"""cf_booksim: the book-level $ simulation with the REAL sizer, and the RULE-AM-RISK-ADJUSTED-V1 re-grade on it.

    python3 scripts/research/cf_booksim.py run --out comms/research/cf_booksim/<run_id> [--cache DIR] [--controls 60]

CF-D3-BOOKSIM / BOOK-SIM-REAL-SIZER + AM-REGRADE-BOOKSIM. Operator 2026-10-29: the measurement of record for an in-trade action
class is a per-account $ book at real size, not a per-trade R screen. This simulator:

  * IMPORTS ``RiskManager.position_size`` (``src/units/accounts/risk.py``): size is whatever the production sizer says at the
    simulated balance (risk_pct, confidence scalar, lot step, margin pre-flight against ``available_usd``). No ``_risk_qty`` copy.
  * runs one book per (account, arm): packages in entry-time order, balance compounding on the arm's own realised P&L,
    ``$ = net_r x qty x r_dist`` (arms are linear in size at constant risk; the grader's convention).
  * models the account's ``risk.daily_dd_switch`` when armed (keep open, block new: a package arriving after the UTC day's
    REALISED loss reached ``limit_pct`` x the day-start balance is not taken) - so a class that cuts losses changes which
    trades the book takes, which is the point of a book-level grade.
  * does NOT model: margin pledged by open positions (``available_usd`` = balance), venue lot rounding beyond the sizer's own,
    unrealised P&L in the switch, the exchange's own refusals. Stated biases, not hidden.

Population: every package ``cf_bulk_live`` can grade (closed, non-pairs, crypto ``*USDT``, bars available, horizon passed) -
the counterfactual population, NOT the live book: the books run each account's packages as they actually traded, with the arm's
P&L replacing the actual.

Arms (registered BEFORE the run; one representative per class, never the best-in-sample):
  hold          original brackets + the leg's own trail, no in-trade action (= grader ``original_brackets``)
  Each class fires ONCE at a fixed causal time ``ta`` = first bar opening at/after ``t_entry + 0.25 x horizon`` (a trade already
  out by ``ta`` is unchanged: the lever never fired for it), from the market at ``ta`` (``mark`` = that bar's open):
  tighten_sl    stop -> mark -/+ 1R (tighter than the stop in force only)
  widen_sl      stop -> initial stop -/+ 0.5R further out
  move_tp       take-profit -> mark +/- 1R when that is nearer than the one in force and beyond the mark
  partial_close 50% out at the open of ``ta``, the rest rides the hold path
  close         100% out at the open of ``ta``
Controls (R4, causal matched-random, same class and same levels, ``K`` draws): identical action but ``ta`` drawn uniformly over
the bars of ``[t_entry, t_entry + horizon)`` - the draw never sees the trade's exit (``cf_core`` causal mode). One control book
per draw, graded by ``am_risk_adjusted.grade_risk_adjusted(basis='book_usd_sim')``.

Registered decision (per class): PASS requires RULE-AM-RISK-ADJUSTED-V1 PASS on EVERY Stage-2 account that carries the
population (``bybit_2`` real money AND its mirror ``bybit_portfolio``; Stage-2 equality, OPERATING-PLAN § 2); the Stage-1 paper
book ``bybit_1`` is reported, not required. Anything else is not a pass. A PASS is a Tier-3 PROPOSAL input (one PR per class),
never an apply; nothing here edits config or a mandate.

Public repo: balances are NEVER written. The books are simulated in USD, then graded in ACCOUNT-R (net $ / (start balance x
risk_pct)), because R1's threshold (0.05 R per trade) is in R and a raw-$ book would apply it as $0.05. Only account-R metrics
and ratios are written; USD totals are printed for the report and not committed (a $ and an account-R together reveal the
balance). The simulated start balance is an ESTIMATE (median of the account's own sized legs / its risk_pct), in process memory.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import random
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import am_risk_adjusted as ara  # noqa: E402
import cf_bars  # noqa: E402
import cf_bulk_live  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_booksim/1"
CLASSES = ("tighten_sl", "widen_sl", "move_tp", "partial_close", "close")
TRIGGER_FRAC = 0.25
ACCOUNTS = ("bybit_2", "bybit_portfolio", "bybit_1")
REQUIRED = ("bybit_2", "bybit_portfolio")
DEFAULT_K = 60


# --------------------------------------------------------------------------- package contexts
def build_contexts(packages: List[dict], trades: List[dict], bars_fn=None, now: Optional[float] = None) -> List[dict]:
    """One context per gradable closed package: geometry, bars, costs, per-account legs. Same population as ``cf_bulk_live``."""
    now = now or datetime.now(timezone.utc).timestamp()
    by_pkg: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        if t.get("order_package_id"):
            by_pkg[t["order_package_id"]].append(t)
    pre: List[Tuple[dict, List[dict], dict, float, float]] = []
    span: Dict[str, List[float]] = {}
    for p in sorted((p for p in packages if str(p.get("status")).lower() == "closed"), key=lambda p: p.get("created_at") or ""):
        legs, why = cf_bulk_live.classify(p, by_pkg.get(p["order_package_id"], []))
        if why:
            continue
        t_entry = min(lrc._ts(t.get("timestamp")) or 1e18 for t in legs)
        t_close = max(lrc._ts(t.get("closed_at")) or 0 for t in legs)
        hz = cf_core.resolve_horizon(p, cf_bulk_live._strategy_config(p.get("strategy_name")))
        if now < t_close + hz["seconds"]:
            continue
        s = span.setdefault(p["symbol"], [t_entry, t_close + hz["seconds"]])
        s[0], s[1] = min(s[0], t_entry), max(s[1], t_close + hz["seconds"])
        pre.append((p, legs, hz, t_entry, t_close))
    fetcher = cf_bulk_live.make_fetcher({k: (v[0], v[1]) for k, v in span.items()}, bars_fn or (lambda s, tf, a, b: cf_bars.historical_bars(s, tf, a, b)))
    out: List[dict] = []
    for p, legs, hz, t_entry, t_close in pre:
        bars = cf_bars.historical_bars(p["symbol"], cf_bulk_live.TF, t_entry, t_close + hz["seconds"], fetcher)
        side = str(p.get("direction") or "").lower()
        entry_ref, stop0 = lrc._num(p.get("entry")), lrc.initial_stop(p)
        if not bars or side not in ("long", "short") or entry_ref is None or stop0 is None or abs(entry_ref - stop0) <= 0:
            continue
        legs = sorted(legs, key=lambda t: (t.get("account_class") != "real_money", t.get("timestamp") or ""))
        lead = legs[0]
        entry_fill = lrc._num(lead.get("entry_price")) or entry_ref
        meta = lrc._meta(p)
        atr, tm = lrc._num(meta.get("atr")), lrc._num(meta.get("trail_mult"))
        out.append({"id": p["order_package_id"], "strategy": p.get("strategy_name"), "symbol": p["symbol"], "side": side, "entry_ref": entry_ref,
                    "stop0": stop0, "tp0": lrc._num(p.get("tp")), "r": abs(entry_ref - stop0), "trail": atr * tm if atr and tm else None,
                    "entry_fill": entry_fill, "t_entry": t_entry, "t_close": t_close, "H": float(hz["seconds"]), "bars": bars,
                    "cm": cf_core.cost_model(lead, p["symbol"], entry_fill, lrc._num(lead.get("position_size")) or 0.0),
                    "confidence": float(lrc._num(p.get("confidence")) or 1.0),
                    "accounts": {t["account_id"]: lrc._num(t.get("position_size")) or 0.0 for t in legs}})
    return out


# --------------------------------------------------------------------------- arms
def _bar_at(bars: Sequence[dict], ts: float) -> Optional[dict]:
    for b in bars:
        if b["time"] >= ts:
            return b
    return None


def action_for(cls: str, c: dict, ta: float) -> Optional[dict]:
    """The class's one registered action at ``ta`` (or None: no bar / not applicable). Pure, causal: reads bars at/before ``ta``."""
    b = _bar_at(c["bars"], ta)
    if b is None:
        return None
    sg = 1.0 if c["side"] == "long" else -1.0
    mark, r = b["open"], c["r"]
    if cls == "close":
        return {"ts": ta, "kind": "close", "frac": 1.0}
    if cls == "partial_close":
        return {"ts": ta, "kind": "close", "frac": 0.5}
    if cls == "tighten_sl":
        return {"ts": ta, "kind": "set_stop", "level": mark - sg * r}
    if cls == "widen_sl":
        return {"ts": ta, "kind": "widen_stop", "level": c["stop0"] - sg * 0.5 * r}
    if cls == "move_tp":
        lvl = mark + sg * r
        tp0 = c["tp0"]
        if tp0 is not None and (tp0 - lvl) * sg > 1e-12:           # only a pull-in: the new TP is nearer than the one in force
            return {"ts": ta, "kind": "set_tp", "level": lvl}
        return None
    raise ValueError(cls)


def arm_outcome(c: dict, act: Optional[dict]) -> Tuple[float, float]:
    """``(net_r, exit_ts)`` for the hold path with one optional in-trade action."""
    sim = cf_core.simulate(c["bars"], side=c["side"], entry_ref=c["entry_ref"], r_dist=c["r"], t_entry=c["t_entry"], stop0=c["stop0"],
                           tp=c["tp0"], actions=[act] if act else [], trail_dist=c["trail"])
    n = cf_core.net_of(sim, side=c["side"], entry_fill=c["entry_fill"], r_dist=c["r"], t_entry=c["t_entry"], cm=c["cm"])
    return n["net_r"], float(sim["last_ts"])


def trigger_time(c: dict) -> float:
    return c["t_entry"] + TRIGGER_FRAC * c["H"]


def random_trigger(c: dict, rng: random.Random) -> Optional[float]:
    usable = cf_core.random_usable_bars(c["bars"], t_entry=c["t_entry"], t_close=c["t_close"], horizon_s=c["H"], mode="causal")
    return rng.choice(usable)["time"] if usable else None


def package_outcomes(ctxs: List[dict], k: int) -> Dict[str, Dict[str, Tuple[float, float]]]:
    """``{package_id: {label: (net_r, exit_ts)}}`` for hold, each class, and ``<class>#c<j>`` controls (same action, random causal time)."""
    out: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for c in ctxs:
        o: Dict[str, Tuple[float, float]] = {"hold": arm_outcome(c, None)}
        for cls in CLASSES:
            o[cls] = arm_outcome(c, action_for(cls, c, trigger_time(c)))
            for j in range(k):
                rng = random.Random(int(hashlib.sha256(f"{c['id']}|{cls}|{j}".encode()).hexdigest()[:12], 16))
                ta = random_trigger(c, rng)
                o[f"{cls}#c{j}"] = arm_outcome(c, action_for(cls, c, ta) if ta is not None else None)
        out[c["id"]] = o
    return out


# --------------------------------------------------------------------------- the book
def make_sizer(account_id: str):
    from src.config.accounts_loader import load_accounts_dict
    from src.units.accounts.risk import RiskManager
    a = load_accounts_dict()[account_id]
    risk = a.get("risk") or {}
    return RiskManager(risk, dry_run=False, account_id=account_id), str(a.get("market_type") or "linear"), risk


def implied_start_balance(rm, ctxs: List[dict], account_id: str) -> float:
    """ESTIMATED start equity: median of (the account's recorded qty x r) / (risk_pct x confidence scalar) over its own legs."""
    xs = []
    for c in ctxs:
        q = c["accounts"].get(account_id)
        if q:
            sc = rm._confidence_scalar(c["confidence"]) or 1.0
            xs.append(q * c["r"] / (rm.risk_pct * sc))
    return statistics.median(xs) if xs else 0.0


def run_book(ctxs: List[dict], outcomes: Dict[str, Dict[str, Tuple[float, float]]], label: str, *, rm, market_type: str, start: float,
             dd_limit_pct: Optional[float]) -> List[dict]:
    """One account x one arm. Returns trade dicts for ``am_risk_adjusted`` with ``net_r`` carrying net USD."""
    from src.core.coordinator import OrderPackage
    done: List[Tuple[float, float]] = []                            # heap of (exit_ts, pnl)
    realised = 0.0
    book: List[dict] = []
    day_key, day_start = None, start
    realised_events: List[Tuple[float, float]] = []                 # (exit_ts, pnl) for the daily switch
    for c in sorted(ctxs, key=lambda c: c["t_entry"]):                 # ``ctxs`` is already this account's packages
        while done and done[0][0] <= c["t_entry"]:
            _, pnl = heapq.heappop(done)
            realised += pnl
        bal = start + realised
        if bal <= 0:
            continue
        dk = datetime.fromtimestamp(c["t_entry"], timezone.utc).date()
        if dk != day_key:
            day_key, day_start = dk, bal
        if dd_limit_pct:
            today = sum(p for ts, p in realised_events if datetime.fromtimestamp(ts, timezone.utc).date() == dk and ts <= c["t_entry"])
            if today <= -dd_limit_pct * day_start:
                continue                                               # keep open, block new
        net_r, exit_ts = outcomes[c["id"]][label]
        pkg = OrderPackage(strategy=str(c["strategy"]), symbol=c["symbol"], direction=c["side"], entry=c["entry_fill"], sl=c["stop0"],
                           tp=c["tp0"] or c["entry_fill"], confidence=c["confidence"])
        qty = rm.position_size(pkg, bal, market_type=market_type, available_usd=bal, total_account_usd=bal)
        if not qty:
            continue
        pnl = net_r * qty * c["r"]
        heapq.heappush(done, (exit_ts, pnl))
        realised_events.append((exit_ts, pnl))
        book.append({"entry_time": datetime.fromtimestamp(c["t_entry"], timezone.utc).isoformat(), "exit_time": datetime.fromtimestamp(exit_ts, timezone.utc).isoformat(),
                     "net_r": pnl, "mfe_r": None, "order_package_id": c["id"]})
    return book


def account_job(args: Tuple[str, List[dict], Dict[str, Dict[str, Tuple[float, float]]], int]) -> Dict[str, Any]:
    account_id, ctxs, outcomes, k = args
    rm, mt, risk = make_sizer(account_id)
    sw = risk.get("daily_dd_switch") or {}
    dd = float(sw.get("limit_pct")) if sw.get("armed") is True and sw.get("limit_pct") else None
    on = [c for c in ctxs if account_id in c["accounts"]]
    start = implied_start_balance(rm, on, account_id)
    labels = ["hold"] + [cl for cl in CLASSES] + [f"{cl}#c{j}" for cl in CLASSES for j in range(k)]
    books = {lb: run_book(on, outcomes, lb, rm=rm, market_type=mt, start=start, dd_limit_pct=dd) for lb in labels}
    # UNITS: the rule's R1 threshold (0.05 R per trade) is in R. A $ book is therefore graded in ACCOUNT-R: net $ divided by one
    # risk unit of the account at the start (start balance x risk_pct), the unit a 1R trade costs the account. That keeps R1 meaningful
    # on a $300 account and a $60k one alike, and it keeps the balance out of anything committed (the $ stay in this process).
    unit = start * rm.risk_pct
    usd = {lb: round(sum(x["net_r"] for x in books[lb]), 2) for lb in ["hold"] + list(CLASSES)}
    books = {lb: [dict(x, net_r=x["net_r"] / unit) for x in bk] for lb, bk in books.items()}
    controls = {cl: [f"{cl}#c{j}" for j in range(k)] for cl in CLASSES}
    grade = ara.grade_risk_adjusted(books, baseline="hold", candidates=list(CLASSES), controls=controls, basis="book_usd_sim")
    # the verdict is in account-R; the per-account % views are dropped (they would multiply back to a balance)
    for cand in grade.get("candidates", {}).values():
        cand.pop("pnl_by_account", None)
        for ctl in (cand.get("controls") or {}).values():
            ctl.pop("pnl_by_account", None)
    return {"account": account_id, "n_packages": len(on), "daily_dd_switch_modelled": dd is not None, "grade": grade,
            "book_n": {lb: len(books[lb]) for lb in ("hold",) + CLASSES}, "unit": "account_R = net USD / (start balance x risk_pct)",
            "_net_usd_private": usd}


def decide(per_account: Dict[str, Any]) -> Dict[str, Any]:
    """Registered per-class decision: PASS on every REQUIRED Stage-2 account, else not a pass."""
    out = {}
    for cl in CLASSES:
        v = {a: (((per_account.get(a) or {}).get("grade") or {}).get("candidates") or {}).get(cl, {}).get("verdict") for a in ACCOUNTS}
        labs = {a: (((per_account.get(a) or {}).get("grade") or {}).get("candidates") or {}).get(cl, {}).get("label") for a in ACCOUNTS}
        if all(v.get(a) == "pass" for a in REQUIRED):
            dec = "PASS"
        elif any(v.get(a) == "fail" for a in REQUIRED):
            dec = "FAIL"
        else:
            dec = "INDETERMINATE"
        out[cl] = {"decision": dec, "verdict_by_account": v, "label_by_account": labs}
    return out


def run(out: Path, cache: Optional[Path], k: int) -> int:
    out.mkdir(parents=True, exist_ok=True)
    if cache and (cache / "order_packages.json").exists():
        packages, trades = json.loads((cache / "order_packages.json").read_text()), json.loads((cache / "trades.json").read_text())
    else:
        packages, _ = cf_bulk_live.fetch_pages("order_packages", 150)
        trades, _ = cf_bulk_live.fetch_pages("trades", 1000)
    ctxs = build_contexts(packages, trades)
    outcomes = package_outcomes(ctxs, k)
    with ProcessPoolExecutor(len(ACCOUNTS)) as ex:
        res = list(ex.map(account_job, [(a, ctxs, outcomes, k) for a in ACCOUNTS]))
    per = {r["account"]: r for r in res}
    private = {a: per[a].pop("_net_usd_private") for a in per}        # printed for the report, never written to the repo
    dec = decide(per)
    summary = {"schema": SCHEMA, "run_at": datetime.now(timezone.utc).isoformat(), "rule": ara.RULE_ID if hasattr(ara, "RULE_ID") else "RULE-AM-RISK-ADJUSTED-V1",
               "measurement_basis": "book_usd_sim", "book_unit": "account_R (net USD / (start balance x risk_pct)); USD and balances are not written", "controls_per_class": k, "trigger_frac_of_horizon": TRIGGER_FRAC,
               "population_packages": len(ctxs), "packages_by_account": {a: per[a]["n_packages"] for a in ACCOUNTS},
               "required_accounts": list(REQUIRED), "decision": dec, "provenance": "ESTIMATED",
               "stated_biases": ["margin pledged not modelled (available_usd = balance)", "start balance is an estimate", "daily switch uses realised P&L only",
                                 "population is the cf_bulk_live gradable set (crypto, non-pairs, closed, horizon passed), not the full live book",
                                 "one registered action per class at a fixed causal time; not a lever sweep", "stop fills at its price (flatters tightens)"]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    (out / "verdicts.json").write_text(json.dumps(per, indent=1, default=str) + "\n")
    print("NET_USD_PRIVATE (not written):", json.dumps(private))
    print(json.dumps({"population": len(ctxs), "per_account_n": summary["packages_by_account"], "decision": {k2: v["decision"] for k2, v in dec.items()},
                      "detail": {k2: v["label_by_account"] for k2, v in dec.items()}}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--cache")
    r.add_argument("--controls", type=int, default=DEFAULT_K)
    a = ap.parse_args(argv)
    return run(Path(a.out), Path(a.cache) if a.cache else None, a.controls)


if __name__ == "__main__":
    sys.exit(main())
