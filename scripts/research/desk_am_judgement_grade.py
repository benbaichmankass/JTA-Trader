#!/usr/bin/env python3
# wiring: .github/workflows/forecast-grade.yml (hourly :41, --live --write; GRADE-EVERYTHING-CONTINUOUSLY 2026-11-01); also by hand or the weekly /performance-review "Live review" section.
"""Grade the judgement desk's in-trade calls, pre-registered as RULE-DESK-AM-JUDGEMENT-V1.

    python3 scripts/research/desk_am_judgement_grade.py --live           # journal + candles from the live API
    python3 scripts/research/desk_am_judgement_grade.py --live --write   # + comms/desk/am_judgement_grade.json

The rule is stated ONCE, in docs/research/desk-am-refocus-diagnosis-2026-10-30.md section 3. This file computes it.

POPULATION: live-review rows carrying a ``forecast`` (the DESK-AM-REFOCUS brief, from 2026-10-31T00:00Z) on CLOSED
packages. The unit is the PACKAGE: its judged rows are averaged first, so a trade reviewed twenty times counts once
(the 2026-10-29 xrp 15m short-hold trade carried 13 of the 14 graded live closes).

THREE NUMBERS PER ROW, all net of the full cost stack through ``live_review_counterfactual.price_review`` (LTR-5):
* ``d_hold``  = the call vs HOLD (the strategy's own bracket and trail, untouched). A hold call is 0 by construction.
* ``d_mech``  = the call vs the MECHANICAL rule: the same review re-priced as ``tighten_sl`` to breakeven (entry)
  when the trade is in profit and its stop is still beyond entry, otherwise hold. Breakeven is the rule bf56-02's
  leave-one-fold-out best-static (B3) chose in all 4 folds (comms/research/RQ-20261026-bf56-02/40710666532/verdict.json).
* the FORECAST: ``hit`` = the forecast's ``target_px`` trades before its ``invalidation_px`` within
  ``horizon_bars`` x ``timeframe`` (stop-first inside a bar, as everywhere in LTR-5), ``miss`` = invalidation first,
  ``expired`` = neither. Brier = mean (p_target - 1[hit])^2 over hit/miss/expired (expired scores 0).

``null`` is could-not-look, never 0. Nothing here applies, graduates or edits anything.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

import live_review_counterfactual as cf  # noqa: E402

RULE_ID = "RULE-DESK-AM-JUDGEMENT-V1"
FORECAST_RULE_FROM = "2026-10-31T00:00:00Z"
MIN_PACKAGES = 30
DRAWS = 10_000
SEED = 20261031
OUT = REPO / "comms" / "desk" / "am_judgement_grade.json"
TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def mechanical_review(review: dict, pkg: dict) -> dict:
    """The review re-stated as the mechanical rule's call (tighten to breakeven, else hold)."""
    st = review.get("state") or {}
    side, entry, sl = str(pkg.get("direction") or "").lower(), cf._num(pkg.get("entry")), cf._num(st.get("sl"))
    open_r = cf._num(st.get("open_r"))
    behind = sl is not None and entry is not None and ((sl < entry) if side == "long" else (sl > entry))
    act = "tighten_sl" if (open_r is not None and open_r > 0 and behind) else "hold"
    rec = {"action": act, "level": entry if act == "tighten_sl" else None, "basis": "ev_positive"}
    return dict(review, recommendation=rec, applied=False)


def forecast_outcome(fc: dict, bars: List[dict], t0: float) -> Optional[str]:
    """hit | miss | expired from bars opening at/after t0; None when the bars do not cover the horizon yet."""
    tf = TF_S.get(str(fc.get("timeframe")))
    tgt, inv, hb = cf._num(fc.get("target_px")), cf._num(fc.get("invalidation_px")), fc.get("horizon_bars")
    if tf is None or tgt is None or inv is None or not isinstance(hb, int):
        return None
    end = t0 + hb * tf
    up = tgt > inv                                   # target above invalidation: price must rise to hit
    covered = False
    for b in bars:
        if b["time"] < t0:
            continue
        if b["time"] >= end:
            covered = True
            break
        if (b["low"] <= inv) if up else (b["high"] >= inv):
            return "miss"                            # invalidation first inside a bar (pessimistic, like LTR-5)
        if (b["high"] >= tgt) if up else (b["low"] <= tgt):
            return "hit"
    return "expired" if covered else None


def _boot(xs: List[float], draws: int = DRAWS, seed: int = SEED) -> Tuple[float, float]:
    rng = random.Random(seed)
    n = len(xs)
    ms = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws))
    return round(ms[int(0.025 * draws)], 4), round(ms[int(0.975 * draws) - 1], 4)


def verdict(per_pkg: Dict[str, Dict[str, float]]) -> dict:
    """The registered rule over package-level means (section 3 of the diagnosis doc)."""
    hold = [v["d_hold"] for v in per_pkg.values() if v.get("d_hold") is not None]
    mech = [v["d_mech"] for v in per_pkg.values() if v.get("d_mech") is not None]
    n = len(hold)
    out: Dict[str, Any] = {"rule": RULE_ID, "n_packages": n, "min_packages": MIN_PACKAGES}
    if n == 0:
        return {**out, "verdict": "accruing", "mean_d_hold": None, "ci95_d_hold": None, "mean_d_mech": None}
    m = round(sum(hold) / n, 4)
    lo, hi = _boot(hold)
    mm = round(sum(mech) / len(mech), 4) if mech else None
    out.update(mean_d_hold=m, ci95_d_hold=[lo, hi], mean_d_mech=mm, n_packages_mech=len(mech))
    if n < MIN_PACKAGES:
        out["verdict"] = "accruing"
    elif lo > 0 and mm is not None and mm > 0:
        out["verdict"] = "pass"
    elif m <= 0 or hi < 0:
        out["verdict"] = "fail"
    else:
        out["verdict"] = "indeterminate"
    return out


def grade(reviews: List[dict], packages: Dict[str, dict], trades: Dict[int, dict],
          candle_fn: Callable[[str, str], Optional[List[dict]]]) -> dict:
    rows = [r for r in reviews if isinstance(r.get("forecast"), dict)
            and str(r.get("reviewed_at") or "") >= FORECAST_RULE_FROM]
    per_row: List[dict] = []
    cache: Dict[Tuple[str, str], Optional[List[dict]]] = {}

    def bars_for(sym: str, tf: str) -> Optional[List[dict]]:
        if (sym, tf) not in cache:
            cache[(sym, tf)] = candle_fn(sym, tf)
        return cache[(sym, tf)]

    priced = {p["review_id"]: p for p in cf.price_all(rows, packages, trades, candle_fn)}
    for r in rows:
        pkg = packages.get(r["order_package_id"])
        rec = r.get("recommendation") or {}
        res = priced.get(r["review_id"]) or {}
        d_hold = ((res.get("outcome") or {}).get("delta_r"))
        d_mech = None
        if pkg is not None and d_hold is not None:
            tid = r.get("trade_id") if r.get("trade_id") is not None else pkg.get("linked_trade_id")
            tf = cf._meta(pkg).get("timeframe") or "1h"
            mres = cf.price_review(mechanical_review(r, pkg), pkg, trades.get(int(tid)) if tid is not None else None,
                                   bars_for(str(pkg.get("symbol")), str(tf)))
            m_delta = (mres.get("outcome") or {}).get("delta_r")
            if m_delta is not None:
                d_mech = round(d_hold - m_delta, 8)
        fc = r["forecast"]
        fbars = bars_for(str((pkg or {}).get("symbol")), str(fc.get("timeframe"))) if pkg else None
        t0 = cf._ts(r.get("reviewed_at"))
        fo = forecast_outcome(fc, fbars or [], t0) if (fbars and t0) else None
        per_row.append({"review_id": r["review_id"], "order_package_id": r["order_package_id"],
                        "action": rec.get("action"), "trigger": (r.get("trigger") or {}).get("event"),
                        "d_hold": d_hold, "d_mech": d_mech, "price_state": res.get("state"),
                        "price_reason": res.get("reason"), "forecast_outcome": fo, "p_target": fc.get("p_target")})
    per_pkg: Dict[str, Dict[str, List[float]]] = {}
    for x in per_row:
        g = per_pkg.setdefault(x["order_package_id"], {"d_hold": [], "d_mech": []})
        for k in ("d_hold", "d_mech"):
            if x[k] is not None:
                g[k].append(x[k])
    pkg_means = {k: {c: (sum(v[c]) / len(v[c]) if v[c] else None) for c in ("d_hold", "d_mech")}
                 for k, v in per_pkg.items()}
    scored = [x for x in per_row if x["forecast_outcome"] in ("hit", "miss", "expired")
              and isinstance(x["p_target"], (int, float))]
    brier = (round(sum((x["p_target"] - (x["forecast_outcome"] == "hit")) ** 2 for x in scored) / len(scored), 4)
             if scored else None)
    by_action: Dict[str, dict] = {}
    for a in sorted({x["action"] for x in per_row if x["action"]}):
        xs = [x["d_hold"] for x in per_row if x["action"] == a and x["d_hold"] is not None]
        by_action[a] = {"n_rows": len(xs), "mean_d_hold": round(sum(xs) / len(xs), 4) if xs else None}
    return {"rule": RULE_ID, "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "population": f"live-review rows with a forecast reviewed from {FORECAST_RULE_FROM}: {len(rows)} rows, "
                          f"{len(per_pkg)} packages",
            "verdict": verdict({k: v for k, v in pkg_means.items() if v["d_hold"] is not None}),
            "forecast": {"n_scored": len(scored), "brier": brier, "brier_ref_constant_0_5": 0.25,
                         "hits": sum(x["forecast_outcome"] == "hit" for x in scored),
                         "unresolved": sum(x["forecast_outcome"] is None for x in per_row)},
            "by_action": by_action, "rows": per_row}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="read the journal + candles from the live API")
    ap.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(REPO)}")
    a = ap.parse_args(argv)
    reviews = cf.read_jsonl(cf.REVIEWS)
    if not a.live:
        print("desk_am_judgement_grade: --live is required (packages, trades and candles come from the live API)")
        return 2
    packages, trades = cf.load_live_sources([r for r in reviews if isinstance(r.get("forecast"), dict)])
    out = grade(reviews, packages, trades, cf.fetch_candles_live)
    print(json.dumps({k: out[k] for k in ("population", "verdict", "forecast", "by_action")}, indent=1))
    if a.write:
        OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
