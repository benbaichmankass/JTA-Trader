#!/usr/bin/env python3
# wiring: manual-only — LTR-CLOSE-AUDIT (2026-11-16): hold-vs-close for every APPLIED live-review close, including holds still open. Research tool; no timer.
"""Close audit: for each APPLIED live-review ``close``, what would holding have done, net of cost?

    python3 scripts/research/ltr_close_audit.py --live --since 2026-11-05 --out comms/research/ltr_close_audit/2026-11-16/audit.json

Why this exists next to ``live_review_counterfactual.py``: that harness prices a close only when the hold replay
RESOLVES (stop/TP) before the data ends, and refuses otherwise (``hold_replay_unresolved_before_close``). Most of
the recent ml_entry closes sit in exactly that state: the hold is still open (or hit its 24 h ``max_hold_min``
time exit), so the harness grades none of them. This script re-uses the harness's own primitives (``replay``,
``cost_legs``, ``net_of_costs``, ``initial_stop``, ``net_r_for_trade``) and adds:
  * the package's ``max_hold_min`` time exit (exit at the OPEN of the first bar at/after entry + max_hold);
  * a MARK-TO-MARKET of a still-open hold at the last candle's close (provenance ESTIMATED);
  * every outcome class: ``tp`` | ``stop`` | ``time_exit`` | ``open_mtm``.
Applied = the journal trade's ``exit_reason == live_review_close`` within 900 s of a ``close`` review (the same
inference the harness uses; ``reviews.jsonl`` carries ``applied: false`` for executed closes).
STATED BIASES (as the harness): stop fills AT its price (flatters a stop); the hold path uses the stop the review
SAW (later swing-ratchet stop moves and ml_first_passage TP extensions are not replayed); candles are exchange
bars; an ``open_mtm`` hold is not a realised exit. Prop (tradeify_1 / velotrade_1) fills are NOT in the journal
``trades`` table, so a prop close has no realised R: it is listed with ``could_not_price`` and a reason.
``null`` means "could not look", never 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import live_review_counterfactual as L  # noqa: E402
from src.runtime.net_r_label import net_r_for_trade  # noqa: E402

TRIGGER_CLASS_NOTE = "trigger.event copied from the review row"


def _class_of(trade: dict) -> str:
    acct = str(trade.get("account_id") or "")
    if acct.endswith("_portfolio"):
        return "mirror_paper"
    if str(trade.get("account_class") or "") == "real_money":
        return "real_money"
    return "paper"


def audit_one(rv: dict, pkg: dict, trades: List[dict], bars: Optional[List[dict]]) -> List[dict]:
    """One row per journal trade carrying the closed package. Pure given its inputs."""
    meta = L._meta(pkg)
    side = str(pkg.get("direction") or "").lower()
    entry, sl0 = L._num(pkg.get("entry")), L.initial_stop(pkg)
    out = []
    if not bars or entry is None or sl0 is None or side not in ("long", "short") or abs(entry - sl0) <= 0:
        reason = "no_candles" if not bars else "package_geometry_missing"
        return [{"review_id": rv["review_id"], "trade_id": t["id"], "state": "could_not_price", "reason": reason} for t in trades]
    r_dist = abs(entry - sl0)
    st = rv.get("state") or {}
    stop_now, tp = L._num(st.get("sl")), L._num(st.get("tp")) or L._num(pkg.get("tp"))
    peak_r = L._num(st.get("peak_r")) or 0.0
    t0 = L._ts(rv.get("reviewed_at"))
    tf_s = L._TF_SECONDS.get(str(meta.get("timeframe") or "1h"), 3600)
    if stop_now is None or t0 is None:
        return [{"review_id": rv["review_id"], "trade_id": t["id"], "state": "could_not_price", "reason": "review_state_missing"} for t in trades]
    if bars[0]["time"] > t0 + tf_s:
        return [{"review_id": rv["review_id"], "trade_id": t["id"], "state": "could_not_price", "reason": "candles_start_after_review"} for t in trades]
    atr, trail_mult = L._num(meta.get("atr")), L._num(meta.get("trail_mult"))
    trail_dist = atr * trail_mult if atr and trail_mult else None
    t_entry = L._ts(pkg.get("created_at")) or L._ts(meta.get("entry_time"))
    max_hold_s = (L._num(meta.get("max_hold_min")) or 0) * 60 or None
    t_limit = (t_entry + max_hold_s) if (t_entry and max_hold_s) else None
    # hold path: bars strictly before the max-hold boundary, then a time exit at that boundary's open
    seg = [b for b in bars if t_limit is None or b["time"] < t_limit]
    hold = L.replay(seg, side=side, entry=entry, r_dist=r_dist, start_ts=t0, stop=stop_now, tp=tp,
                    extreme_r0=peak_r, trail_dist=trail_dist)
    sign = 1.0 if side == "long" else -1.0
    outcome, hold_gross, hold_ts, provenance = None, None, None, "computed"
    if hold is not None:
        outcome = {"stop": "stop", "tp": "tp"}[hold["reason"]]
        hold_gross, hold_ts = hold["gross_r"], hold["ts"]
    else:
        tx = next((b for b in bars if t_limit is not None and b["time"] >= t_limit), None)
        if tx is not None:
            outcome, hold_gross, hold_ts = "time_exit", sign * (tx["open"] - entry) / r_dist, tx["time"]
        else:
            last = bars[-1]
            outcome, hold_gross, hold_ts, provenance = "open_mtm", sign * (last["close"] - entry) / r_dist, last["time"], "estimated"
    for t in trades:
        lab = net_r_for_trade(dict(t, stop_loss=sl0))
        base = {"review_id": rv["review_id"], "order_package_id": rv["order_package_id"], "trade_id": t["id"],
                "account_id": t.get("account_id"), "account_class": _class_of(t), "symbol": pkg.get("symbol"),
                "leg": rv.get("leg"), "side": side, "trigger": (rv.get("trigger") or {}).get("event"),
                "reviewed_at": rv.get("reviewed_at"), "closed_at": t.get("closed_at"),
                "open_r_at_review": st.get("open_r"), "peak_r_at_review": st.get("peak_r")}
        if lab is None:
            out.append(dict(base, state="could_not_price", reason="realised_net_r_uncomputable"))
            continue
        fee_r, fund_r, slip_r, stack = L.cost_legs(t, str(pkg.get("symbol")), entry, r_dist, lab["risk_usd"])
        t_close = L._ts(t.get("closed_at"))
        span = (t_close - t_entry) if (t_close and t_entry and t_close > t_entry) else None
        frac = ((hold_ts - t_entry) / span) if span else 1.0
        hold_net = L.net_of_costs(hold_gross, fee_r, fund_r, slip_r, frac)
        out.append(dict(base, state="priced", close_net_r=round(lab["net_R"], 4), hold_outcome=outcome,
                        hold_net_r=round(hold_net, 4), hold_resolved=outcome != "open_mtm",
                        delta_r=round(lab["net_R"] - hold_net, 4), hold_provenance=provenance,
                        hold_exit_at=L._iso(hold_ts), cost_stack=stack))
    return out


def summarise(rows: List[dict]) -> dict:
    priced = [r for r in rows if r.get("state") == "priced"]
    res: Dict[str, Any] = {"n_rows": len(rows), "n_priced": len(priced),
                           "could_not_price": defaultdict(int)}
    for r in rows:
        if r.get("state") != "priced":
            res["could_not_price"][r.get("reason")] += 1
    res["could_not_price"] = dict(res["could_not_price"])
    by: Dict[str, List[dict]] = defaultdict(list)
    for r in priced:
        by[r["account_class"]].append(r)
        by["ALL"].append(r)
    res["by_class"] = {}
    for k, v in by.items():
        d = [x["delta_r"] for x in v]
        res["by_class"][k] = {
            "n": len(v), "sum_delta_r": round(sum(d), 3), "mean_delta_r": round(sum(d) / len(d), 3),
            "n_close_better": sum(1 for x in d if x > 0), "sum_close_r": round(sum(x["close_net_r"] for x in v), 3),
            "sum_hold_r": round(sum(x["hold_net_r"] for x in v), 3),
            "hold_outcomes": {o: sum(1 for x in v if x["hold_outcome"] == o) for o in ("tp", "stop", "time_exit", "open_mtm")}}
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--reviews", required=True, help="merged reviews jsonl (main reviews.jsonl + live-review/rows rows)")
    ap.add_argument("--since", default="2026-11-05")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not a.live:
        ap.error("only --live is wired")
    reviews = L.read_jsonl(Path(a.reviews))
    pk: Dict[str, dict] = {}
    for off in range(0, 3000, 150):
        page = L.fetch_diag(f"journal?table=order_packages&limit=150&offset={off}")
        page = page.get("rows", page) if isinstance(page, dict) else page
        if not page:
            break
        pk.update({p["order_package_id"]: p for p in page})
    trades: List[dict] = []
    for off in range(0, 6000, 1000):
        page = L.fetch_diag(f"journal?table=trades&limit=1000&offset={off}")
        page = page.get("rows", page) if isinstance(page, dict) else page
        trades += page
        if len(page) < 1000:
            break
    by_pkg: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        by_pkg[str(t.get("order_package_id"))].append(t)
    cache: Dict[Any, Any] = {}
    rows: List[dict] = []
    recommended_only: List[dict] = []
    unmatched: List[dict] = []
    # one review per applied trade: the close review for that package nearest in time to the journal close,
    # within 900 s EITHER side (a row's reviewed_at is sometimes stamped minutes AFTER the apply it records).
    close_revs = [rv for rv in sorted(reviews, key=lambda r: r["reviewed_at"])
                  if rv["reviewed_at"][:10] >= a.since and (rv.get("recommendation") or {}).get("action") == "close"]
    chosen: Dict[str, dict] = {}                       # trade_id -> review
    for t in trades:
        if str(t.get("exit_reason") or "") != "live_review_close" or str(t.get("closed_at") or "")[:10] < a.since:
            continue
        cands = [(abs(L._ts(rv["reviewed_at"]) - L._ts(t["closed_at"])), rv) for rv in close_revs
                 if rv["order_package_id"] == t.get("order_package_id")]
        cands = [c for c in cands if c[0] <= L.CLOSE_ATTRIBUTION_S]
        if cands:
            chosen[str(t["id"])] = min(cands, key=lambda c: c[0])[1]
        else:
            unmatched.append({"trade_id": t["id"], "account_id": t.get("account_id"), "symbol": t.get("symbol"),
                              "strategy": t.get("strategy_name"), "closed_at": t.get("closed_at"),
                              "reason": "exit_reason=live_review_close but no close review row within 900 s"})
    by_rev: Dict[str, List[dict]] = defaultdict(list)
    for t in trades:
        if str(t["id"]) in chosen:
            by_rev[chosen[str(t["id"])]["review_id"]].append(t)
    applied_ids = set(by_rev)
    for rv in close_revs:
        pkg = pk.get(rv["order_package_id"])
        if rv["review_id"] not in applied_ids:
            recommended_only.append({"review_id": rv["review_id"], "leg": rv.get("leg"), "accounts": rv.get("accounts"),
                                     "trigger": (rv.get("trigger") or {}).get("event"),
                                     "reason": "no_package_row" if pkg is None else (
                                         "no_journal_trade_row(prop_or_unfilled)" if not by_pkg.get(rv["order_package_id"]) else "close_not_evidenced_as_applied")})
            continue
        if pkg is None:
            rows += [{"review_id": rv["review_id"], "trade_id": t["id"], "state": "could_not_price", "reason": "no_package_row"} for t in by_rev[rv["review_id"]]]
            continue
        key = (str(pkg.get("symbol")), str(L._meta(pkg).get("timeframe") or "1h"))
        if key not in cache:
            cache[key] = L.fetch_candles_live(*key)
        # replay starts at the EARLIER of the review stamp and the journal close (the hold question is "from the close")
        t_cl = min(L._ts(t["closed_at"]) for t in by_rev[rv["review_id"]])
        rv2 = dict(rv, reviewed_at=L._iso(t_cl)) if L._ts(rv["reviewed_at"]) > t_cl else rv
        rows += audit_one(rv2, pkg, by_rev[rv["review_id"]], cache[key])
    doc = {"since": a.since, "population": "journal trades with exit_reason=live_review_close within 900 s of a close review",
           "summary": summarise(rows), "rows": rows, "recommended_close_not_evidenced_applied": recommended_only,
           "applied_close_without_review_row": unmatched}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps(doc["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
