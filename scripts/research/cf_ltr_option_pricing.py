#!/usr/bin/env python3
# wiring: manual-only - CF-D2-LTR-PRICING: prices every live-review option class at every review (not only the call made); no scheduler
"""cf_ltr_option_pricing: price EVERY in-trade option class at EVERY live-review row, from replayed paths (CF-D2-LTR-PRICING).

    python3 scripts/research/cf_ltr_option_pricing.py run --out comms/live_review/option_pricing.jsonl [--cache DIR]

Why: ``outcomes.jsonl`` prices only the class a reviewer RECOMMENDED (416 of 537 rows are ``hold`` with ``delta_r`` 0 "by
construction"), so a class's priced n accrues only from the few calls made. Graduation (RULE-AM-RISK-ADJUSTED-V1) needs
every class priced on the same reviews, applied or not. This prices a FIXED, registered grid of options at each review
bar, so each class has one row per review it can be priced at.

Option grid (registered before the run; levels are functions of the review's own state, never of the outcome):
  hold                       delta 0 by construction (the baseline; ``no_path_change``)
  close                      whole position out at the open of the first bar at/after the review
  partial_close_50           half out there, half rides the hold path
  tighten_trail_1r           stop to (mark - 1R) for a long (mirror short), when that is tighter than the stop in force
  tighten_be                 stop to the entry, when the review is in profit and the entry is tighter than the stop
  move_tp_extend_1r          take-profit 1R further than the one in force
  move_tp_pullin_half        take-profit halfway between the mark and the one in force (only when that stays beyond the mark)
  widen_sl_half_r            stop 0.5R further from the entry than the stop in force

Engine: ``live_review_counterfactual.price_review`` (the LTR-5 pricing, unchanged: ``replay`` + ``trade_action_delta``, net of
the full cost stack, fidelity-checked against the realised exit). Bars: the Binance Vision archive at 5m (``cf_bars``), so a
review older than the live candle window is priceable. A synthetic review row (``<review_id>::<class>``) carries the option;
nothing is written to ``reviews.jsonl`` and no option is applied.

Output: one JSON row per (review, class): the engine's outcome row plus ``option_class``, ``option_level``,
``option_state`` (priced | could_not_price | not_applicable) and ``reason``. Sibling file, NOT ``outcomes.jsonl``: those rows
are graded CALLS joined to ``reviews.jsonl`` (the grade loop dedupes on review_id), and option prices are not calls.
Provenance: ESTIMATED (replay). A stop fills at its price (flatters every tighten); stated biases are the engine's.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bars  # noqa: E402
import cf_bulk_live  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "cf_ltr_option_pricing/1"
CLASSES = ("hold", "close", "partial_close_50", "tighten_trail_1r", "tighten_be", "move_tp_extend_1r", "move_tp_pullin_half", "widen_sl_half_r")
ACTION_OF = {"close": "close", "partial_close_50": "partial_close", "tighten_trail_1r": "tighten_sl", "tighten_be": "tighten_sl",
             "move_tp_extend_1r": "move_tp", "move_tp_pullin_half": "move_tp", "widen_sl_half_r": "widen_sl"}
TF = "5m"
MIN_N = 20                          # the repo's per-class priced-call floor (MD-LTR-PAPER-AUTO promotion path)


def option_for(cls: str, review: dict, pkg: dict) -> Tuple[Optional[dict], Optional[str]]:
    """``(recommendation dict, None)`` or ``(None, reason)`` where the reason is ``not_applicable:*`` for a state the class
    cannot take (a trail stop that is not tighter, a TP pull-in that crosses the mark) - never a missing-data failure."""
    if cls == "hold":
        return {"action": "hold"}, None
    side = str(pkg.get("direction") or "").lower()
    entry, sl0 = lrc._num(pkg.get("entry")), lrc.initial_stop(pkg)
    st = review.get("state") or {}
    stop_now, tp, open_r = lrc._num(st.get("sl")), lrc._num(st.get("tp")) or lrc._num(pkg.get("tp")), lrc._num(st.get("open_r"))
    if side not in ("long", "short") or entry is None or sl0 is None or stop_now is None or open_r is None or abs(entry - sl0) <= 0:
        return None, "review_state_missing"
    r = abs(entry - sl0)
    sg = 1.0 if side == "long" else -1.0
    mark = entry + sg * open_r * r
    tighter = lambda new: (new - stop_now) * sg > 1e-12            # noqa: E731  a stop that moves toward the market
    below_mark = lambda new: (mark - new) * sg > 1e-12             # noqa: E731  a valid stop is on the loss side of the mark
    if cls == "close":
        return {"action": "close"}, None
    if cls == "partial_close_50":
        return {"action": "partial_close", "size_fraction": 0.5}, None
    if cls == "tighten_trail_1r":
        lvl = mark - sg * r
        ok = tighter(lvl) and below_mark(lvl)
        return ({"action": "tighten_sl", "level": lvl}, None) if ok else (None, "not_applicable:trail_not_tighter")
    if cls == "tighten_be":
        ok = open_r > 0 and tighter(entry) and below_mark(entry)
        return ({"action": "tighten_sl", "level": entry}, None) if ok else (None, "not_applicable:be_not_tighter_or_not_in_profit")
    if tp is None:
        return (None, "review_state_missing") if cls.startswith("move_tp") else (None, None)
    if cls == "move_tp_extend_1r":
        return {"action": "move_tp", "level": tp + sg * r}, None
    if cls == "move_tp_pullin_half":
        lvl = mark + (tp - mark) / 2.0
        ok = (lvl - mark) * sg > 1e-12 and (tp - lvl) * sg > 1e-12
        return ({"action": "move_tp", "level": lvl}, None) if ok else (None, "not_applicable:tp_not_beyond_mark")
    if cls == "widen_sl_half_r":
        return {"action": "widen_sl", "level": stop_now - sg * 0.5 * r}, None
    raise ValueError(cls)


def price_class(cls: str, review: dict, pkg: Optional[dict], trade: Optional[dict], bars: Optional[List[dict]]) -> dict:
    base = {"schema": SCHEMA, "review_id": review["review_id"], "order_package_id": review["order_package_id"], "option_class": cls,
            "leg": review.get("leg"), "reviewed_at": review.get("reviewed_at"), "provenance": "ESTIMATED"}
    if pkg is None:
        return dict(base, option_state="could_not_price", reason="no_package_row")
    rec, why = option_for(cls, review, pkg)
    if rec is None:
        state = "not_applicable" if (why or "").startswith("not_applicable") else "could_not_price"
        return dict(base, option_state=state, reason=why)
    syn = dict(review, review_id=f"{review['review_id']}::{cls}", recommendation=dict(review.get("recommendation") or {}, **{
        "action": rec["action"], "level": rec.get("level"), "size_fraction": rec.get("size_fraction"), "size_multiplier": None}),
        applied=False)
    syn.pop("applied_inferred", None)
    res = lrc.price_review(syn, pkg, trade, bars)
    out = res.get("outcome")
    if res.get("state") in ("priced", "not_a_call") and out:
        return dict(base, option_state="priced", reason=None, option_level=rec.get("level"), size_fraction=rec.get("size_fraction"),
                    delta_r=out.get("delta_r"), rec_r=out.get("rec_r"), cf_r=out.get("cf_r"), net_r=out.get("net_r"), cf_method=out.get("cf_method"),
                    replay_fidelity=out.get("replay_fidelity"), cf_cost_stack=out.get("cf_cost_stack"), exit_reason=out.get("exit_reason"))
    return dict(base, option_state="could_not_price", reason=res.get("reason") or res.get("state"), option_level=rec.get("level"))


def price_reviews(reviews: List[dict], packages: Dict[str, dict], trades: Dict[int, dict], bars_fn=None) -> List[dict]:
    """One row per (review, class) for every review whose package is a crypto (``*USDT``) package; the denominator is
    reviews x classes and every cell is in exactly one state."""
    bars_fn = bars_fn or (lambda s, tf, a, b: cf_bars.historical_bars(s, tf, a, b))
    need: Dict[str, List[float]] = {}
    for rv in reviews:
        p = packages.get(rv["order_package_id"])
        if p and str(p.get("symbol", "")).endswith("USDT"):
            t = lrc._ts(rv.get("reviewed_at")) or 0
            s = need.setdefault(p["symbol"], [t, t])
            s[0], s[1] = min(s[0], t), max(s[1], t)
    span = {k: (v[0] - 3600, v[1] + 3 * 86400) for k, v in need.items()}
    fetcher = cf_bulk_live.make_fetcher(span, bars_fn)
    rows: List[dict] = []
    for rv in reviews:
        pkg = packages.get(rv["order_package_id"])
        tid = rv.get("trade_id") if rv.get("trade_id") is not None else (pkg or {}).get("linked_trade_id")
        tr = trades.get(int(tid)) if tid is not None else None
        if pkg is not None and tid is not None and rv.get("trade_id") is None:
            rv = dict(rv, trade_id=tid)
        if pkg is None or not str(pkg.get("symbol", "")).endswith("USDT"):
            for c in CLASSES:
                rows.append({"schema": SCHEMA, "review_id": rv["review_id"], "order_package_id": rv["order_package_id"], "option_class": c,
                             "leg": rv.get("leg"), "reviewed_at": rv.get("reviewed_at"), "provenance": "ESTIMATED", "option_state": "could_not_price",
                             "reason": "no_package_row" if pkg is None else "no_bars_non_crypto"})
            continue
        t0 = lrc._ts(rv.get("reviewed_at")) or 0
        bars = cf_bars.historical_bars(pkg["symbol"], TF, t0 - 3600, t0 + 3 * 86400, fetcher)
        for c in CLASSES:
            rows.append(price_class(c, rv, pkg, tr, bars))
    return rows


def _boot_ci(vals: List[float], n_boot: int = 2000, seed: int = 11) -> Tuple[float, float]:
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def summarize(rows: List[dict]) -> Dict[str, Any]:
    """Per class: state counts (the denominator), priced n, mean delta_r with a bootstrap-by-PACKAGE 95% CI, share of
    priced rows with delta > 0, and the same split by replay fidelity (``match`` only = the trustworthy subset)."""
    out: Dict[str, Any] = {"min_n": MIN_N, "classes": {}}
    for c in CLASSES:
        rs = [r for r in rows if r["option_class"] == c]
        states = Counter(r["option_state"] for r in rs)
        reasons = Counter(r.get("reason") for r in rs if r["option_state"] != "priced")
        priced = [r for r in rs if r["option_state"] == "priced" and r.get("delta_r") is not None]

        def agg(sel: List[dict]) -> Dict[str, Any]:
            if not sel:
                return {"n": 0, "n_packages": 0, "mean_delta_r": None, "ci95": None, "share_positive": None}
            by_pkg: Dict[str, List[float]] = defaultdict(list)
            for r in sel:
                by_pkg[r["order_package_id"]].append(float(r["delta_r"]))
            pk_means = [sum(v) / len(v) for v in by_pkg.values()]
            ci = _boot_ci(pk_means) if len(pk_means) >= 5 else None
            # the point estimate is the mean of per-PACKAGE means (the bootstrap's unit), so it sits inside its own CI;
            # reviews of one package are one path and are not independent. ``mean_delta_r_per_review`` is the pooled read.
            return {"n": len(sel), "n_packages": len(by_pkg), "mean_delta_r": round(sum(pk_means) / len(pk_means), 5),
                    "mean_delta_r_per_review": round(sum(float(r["delta_r"]) for r in sel) / len(sel), 5),
                    "ci95": [round(ci[0], 5), round(ci[1], 5)] if ci else None,
                    "share_positive": round(sum(float(r["delta_r"]) > 0 for r in sel) / len(sel), 4)}
        out["classes"][c] = {"states": dict(states), "not_priced_reasons": dict(reasons), "priced": agg(priced),
                             "priced_fidelity_match": agg([r for r in priced if r.get("replay_fidelity") in ("replay_matches_realised", "match")]),
                             "fidelity_values": dict(Counter(r.get("replay_fidelity") for r in priced)),
                             "reaches_min_n": len(priced) >= MIN_N}
    return out


def run(out: Path, cache: Optional[Path]) -> int:
    if cache and (cache / "order_packages.json").exists():
        pk, tr = json.loads((cache / "order_packages.json").read_text()), json.loads((cache / "trades.json").read_text())
    else:
        pk, _ = cf_bulk_live.fetch_pages("order_packages", 150)
        tr, _ = cf_bulk_live.fetch_pages("trades", 1000)
    packages = {p["order_package_id"]: p for p in pk}
    trades = {int(t["id"]): t for t in tr}
    reviews = lrc.read_jsonl(lrc.REVIEWS)
    rows = price_reviews(reviews, packages, trades)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    summ = summarize(rows)
    summ.update({"schema": SCHEMA, "run_at": datetime.now(timezone.utc).isoformat(), "reviews": len(reviews), "rows": len(rows), "classes_grid": list(CLASSES)})
    out.with_suffix(".summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    print(json.dumps({c: {"priced_n": v["priced"]["n"], "mean": v["priced"]["mean_delta_r"], "ci": v["priced"]["ci95"], "states": v["states"]} for c, v in summ["classes"].items()}, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--cache")
    a = ap.parse_args(argv)
    return run(Path(a.out), Path(a.cache) if a.cache else None)


if __name__ == "__main__":
    sys.exit(main())
