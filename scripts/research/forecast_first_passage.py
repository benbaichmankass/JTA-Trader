#!/usr/bin/env python3
# wiring: .github/workflows/forecast-grade.yml (hourly cron :41); manual: python3 scripts/research/forecast_first_passage.py --live --write
"""Grade EVERY price forecast by FIRST PASSAGE (lane FORECAST-GRADE-FIRST-PASSAGE, operator 2026-11-01).

A forecast is a target level, an invalidation level, a horizon (``horizon_bars`` x ``timeframe``) and a probability
``p_target``. Its outcome is which level price reaches FIRST inside the horizon, three classes:

* ``target_first``       - the target traded before the invalidation
* ``invalidation_first`` - the invalidation traded before the target
* ``expired``            - neither traded by the horizon (its own class; never folded into a miss)

Plus the states that are not outcomes: ``pending`` (horizon not elapsed and no level traded; carries
``time_remaining_s`` and is never dropped), ``tie_unresolved`` (one bar touched both levels and the 1m candles could
not order them; counted and reported, never assigned) and ``no_data`` (could not look: symbol or candles missing; a
null, never a 0).

A forecast is gradable the moment EITHER level trades or the horizon has elapsed, whether or not the trade it
belongs to is still open. Same-bar double touches are ordered from 1m candles (``resolve_same_bar``: the shared
tie resolver; the first 1m bar that touches either level decides, a 1m bar touching both stays unresolved).

SOURCES (each carries levels + horizon + probability): live-review rows with a ``forecast`` (comms/live_review/
reviews.jsonl on main UNION the per-review files on the ``live-review/rows`` branch) and desk entry proposals
(``proposal.tp.level`` target, ``proposal.stop.level`` invalidation, ``tp.p_hit``, ``horizon_bars`` x ``timeframe``;
comms/desk/decisions.jsonl UNION the ``desk/decisions`` branch). Desk ``no_trade`` rows carry no forecast: counted in
the inventory denominator, not graded. The net-of-cost ``d_hold``/``d_mech`` package grade (RULE-DESK-AM-JUDGEMENT-V1,
desk_am_judgement_grade.py) is a different question and is untouched.

Final outcomes are FROZEN in the ledger (comms/desk/forecast_ledger.jsonl): 1m candles only reach back ~16h, so a
resolved tie must not be re-derived later. Only pending / tie_unresolved / no_data rows are re-evaluated each run.
Nothing here gates, applies or edits a trade.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

import live_review_counterfactual as cf  # noqa: E402

TF_S = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
FINAL = ("target_first", "invalidation_first", "expired")
OUT = REPO / "comms" / "desk" / "forecast_grade.json"
LEDGER = REPO / "comms" / "desk" / "forecast_ledger.jsonl"
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0000001)]
SCHEMA = 1


# --------------------------------------------------------------------------- the resolver

def _touch(b: dict, up: bool, tgt: float, inv: float) -> Tuple[bool, bool]:
    """(invalidation touched, target touched) by one bar."""
    i = (b["low"] <= inv) if up else (b["high"] >= inv)
    t = (b["high"] >= tgt) if up else (b["low"] <= tgt)
    return i, t


def resolve_same_bar(bar: dict, bar_s: int, bars_1m: Optional[List[dict]], up: bool, tgt: float, inv: float
                     ) -> Optional[str]:
    """Order a bar that touched BOTH levels from the 1m candles inside it: ``target_first`` / ``invalidation_first``,
    or None when the 1m data does not cover the bar or a single 1m bar touches both (unresolvable)."""
    if not bars_1m:
        return None
    lo, hi = bar["time"], bar["time"] + bar_s
    sub = [m for m in bars_1m if lo <= m["time"] < hi]
    if not sub or sub[0]["time"] > lo or len(sub) < bar_s // 60:      # require full 1m coverage of the bar
        return None
    for m in sub:
        i, t = _touch(m, up, tgt, inv)
        if i and t:
            return None
        if i:
            return "invalidation_first"
        if t:
            return "target_first"
    return None


def first_passage(fc: dict, t0: float, bars: Optional[List[dict]], bars_1m: Optional[List[dict]], now: float) -> dict:
    """Grade one forecast. ``fc`` needs target_px, invalidation_px, horizon_bars (int), timeframe. Pure."""
    tf = TF_S.get(str(fc.get("timeframe")))
    tgt, inv, hb = cf._num(fc.get("target_px")), cf._num(fc.get("invalidation_px")), fc.get("horizon_bars")
    if tf is None or tgt is None or inv is None or tgt == inv or not isinstance(hb, int) or isinstance(hb, bool) or hb < 1:
        return {"class": "no_data", "reason": "forecast_fields_unusable"}
    end = t0 + hb * tf
    base: Dict[str, Any] = {"horizon_end": cf._iso(end), "horizon_s": hb * tf}
    if not bars:
        return {**base, "class": "no_data", "reason": "no_candles"}
    up = tgt > inv
    lead = None                                               # t0 falls inside a bar: the 1m candles score its tail
    lead_scanned = False
    if bars_1m:
        tail = [m for m in bars_1m if t0 - 60 < m["time"] < end]
        nxt = min((b["time"] for b in bars if b["time"] >= t0), default=end)
        lead = [m for m in tail if m["time"] + 60 > t0 and m["time"] < nxt]
        lead_scanned = bool(lead) and lead[0]["time"] <= t0
    ref = None
    seq: List[Tuple[dict, int, bool]] = []                     # (bar, seconds, is_1m)
    if lead_scanned:
        seq += [(m, 60, True) for m in lead]
        ref = lead[0]["open"] if lead[0]["time"] == t0 else lead[0]["close"]
    seq += [(b, tf, False) for b in bars if t0 <= b["time"] < end]
    if ref is None and seq:
        ref = seq[0][0]["open"]
    last_close = None
    for b, secs, is_m in seq:
        i, t = _touch(b, up, tgt, inv)
        last_close = b["close"] if "close" in b else last_close
        if not (i or t):
            continue
        if i and t:
            how = "1m" if is_m else "1m_tie"
            res = None if is_m else resolve_same_bar(b, secs, bars_1m, up, tgt, inv)
            if res is None:
                return {**base, "class": "tie_unresolved", "first_touch_bar": cf._iso(b["time"]),
                        "lead_scanned": lead_scanned, "reason": "one bar touched both levels; 1m could not order"}
            return {**base, "class": res, "resolved_at": cf._iso(b["time"]), "tie_resolved_by": how,
                    "direction_hit": res == "target_first", "lead_scanned": lead_scanned}
        cls = "invalidation_first" if i else "target_first"
        at, prec = b["time"], ("1m" if is_m else "bar")
        if not is_m and bars_1m:                              # refine the touch time to the first 1m bar that reached it
            m1 = next((m for m in bars_1m if b["time"] <= m["time"] < b["time"] + secs
                       and _touch(m, up, tgt, inv)[0 if i else 1]), None)
            if m1 is not None:
                at, prec = m1["time"], "1m"
        return {**base, "class": cls, "resolved_at": cf._iso(at), "resolved_at_precision": prec,
                "tie_resolved_by": None, "direction_hit": cls == "target_first", "lead_scanned": lead_scanned}
    if now < end:
        return {**base, "class": "pending", "time_remaining_s": int(end - now), "lead_scanned": lead_scanned}
    if bars[-1]["time"] + tf < end:
        return {**base, "class": "no_data", "reason": "candles_end_before_horizon (market closed or data gap; re-checked every run)", "lead_scanned": lead_scanned}
    dh = None
    if ref is not None and last_close is not None:
        dh = (last_close > ref) if up else (last_close < ref)
    return {**base, "class": "expired", "resolved_at": cf._iso(end), "tie_resolved_by": None,
            "direction_hit": dh, "lead_scanned": lead_scanned}


# --------------------------------------------------------------------------- sources

def _git_show(ref: str, path: str) -> Optional[str]:
    p = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def _jsonl(text: Optional[str]) -> List[dict]:
    out = []
    for ln in (text or "").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def load_live_review(rows_ref: str = "origin/live-review/rows") -> Tuple[List[dict], dict]:
    """Union of reviews.jsonl on main and the per-review row files on the rows branch, de-duplicated by review_id."""
    reviews = {r["review_id"]: r for r in cf.read_jsonl(cf.REVIEWS) if r.get("review_id")}
    n_main = len(reviews)
    state = {"main_reviews": n_main, "rows_branch": "unreadable"}
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", rows_ref, "comms/live_review/rows/"], cwd=REPO,
                        capture_output=True, text=True)
    if ls.returncode == 0:
        files = [f for f in ls.stdout.split() if f.endswith(".json")]
        n_branch = 0
        for f in files:
            try:
                r = json.loads(_git_show(rows_ref, f) or "")
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("review_id"):
                n_branch += 1
                reviews.setdefault(r["review_id"], r)
        state.update(rows_branch=n_branch, union=len(reviews))
    else:
        state["union"] = len(reviews)
    return list(reviews.values()), state


def load_desk(ref: str = "origin/desk/decisions") -> Tuple[List[dict], dict]:
    dec = {d["decision_id"]: d for d in cf.read_jsonl(REPO / "comms" / "desk" / "decisions.jsonl") if d.get("decision_id")}
    st = {"main_decisions": len(dec), "branch": "unreadable"}
    txt = _git_show(ref, "comms/desk/decisions.jsonl")
    if txt is not None:
        b = _jsonl(txt)
        st["branch"] = len(b)
        for d in b:
            if d.get("decision_id"):
                dec.setdefault(d["decision_id"], d)
    st["union"] = len(dec)
    return list(dec.values()), st


def forecast_records(reviews: List[dict], desk: List[dict], packages: Dict[str, dict]) -> Tuple[List[dict], dict]:
    """Normalise every forecast-carrying record to {fid, source, symbol, t0, fc{...}, p_target, ...} + inventory."""
    recs: List[dict] = []
    for r in reviews:
        fc = r.get("forecast")
        if not isinstance(fc, dict):
            continue
        pkg = packages.get(r.get("order_package_id")) or {}
        recs.append({"fid": r["review_id"], "source": "live_review", "package": r.get("order_package_id"),
                     "symbol": pkg.get("symbol"), "made_at": r.get("reviewed_at"), "fc": fc,
                     "p_target": cf._num(fc.get("p_target"))})
    desk_prop = 0
    for d in desk:
        p = d.get("proposal")
        if not isinstance(p, dict):
            continue
        desk_prop += 1
        tp, sl = p.get("tp") or {}, p.get("stop") or {}
        fc = {"target_px": tp.get("level"), "invalidation_px": sl.get("level"), "horizon_bars": p.get("horizon_bars"),
              "timeframe": p.get("timeframe"), "p_target": tp.get("p_hit")}
        recs.append({"fid": d["decision_id"], "source": "desk_entry", "package": d.get("order_package_id"),
                     "symbol": p.get("symbol"), "made_at": d.get("judged_at"), "fc": fc,
                     "p_target": cf._num(tp.get("p_hit"))})
    inv = {"live_review": {"records": len(reviews), "with_forecast": sum(isinstance(r.get("forecast"), dict) for r in reviews)},
           "desk_entry": {"records": len(desk), "with_forecast": desk_prop,
                          "no_trade_without_forecast": sum(d.get("proposal") is None for d in desk)},
           "ml_prediction_logs": "none found carrying target/invalidation/horizon (grep invalidation_px|target_px over "
                                 "*.py, *.jsonl, *.yaml outside docs/tests: only the review, desk and ML-family readers)"}
    return recs, inv


# --------------------------------------------------------------------------- summary

def _brier(xs: List[Tuple[float, int]]) -> Optional[float]:
    return round(sum((p - y) ** 2 for p, y in xs) / len(xs), 4) if xs else None


def summarise(rows: List[dict]) -> dict:
    cnt = {k: sum(r["class"] == k for r in rows) for k in FINAL + ("pending", "tie_unresolved", "no_data")}
    graded = [r for r in rows if r["class"] in FINAL]
    scored = [(r["p_target"], int(r["class"] == "target_first")) for r in graded if isinstance(r.get("p_target"), (int, float))]
    by_class = {k: {"n": cnt[k], "brier": _brier([(p, y) for r, (p, y) in zip(
        [g for g in graded if isinstance(g.get("p_target"), (int, float))], scored) if r["class"] == k])} for k in FINAL}
    bins = []
    for lo, hi in BINS:
        b = [(p, y) for p, y in scored if lo <= p < hi]
        bins.append({"p_lo": lo, "p_hi": min(hi, 1.0), "n": len(b),
                     "mean_p": round(sum(p for p, _ in b) / len(b), 4) if b else None,
                     "target_first_rate": round(sum(y for _, y in b) / len(b), 4) if b else None})
    dh = [r["direction_hit"] for r in graded if isinstance(r.get("direction_hit"), bool)]
    return {"n": len(rows), "n_packages": len({r["package"] for r in rows if r.get("package")}), "classes": cnt,
            "n_graded": len(graded), "n_scored_with_p": len(scored),
            "brier_overall": _brier(scored), "brier_ref_constant_0_5": 0.25, "brier_by_class": by_class,
            "calibration_bins": bins,
            "direction_hit_rate": {"n": len(dh), "rate": round(sum(dh) / len(dh), 4) if dh else None},
            "unresolved_ties": cnt["tie_unresolved"]}


# --------------------------------------------------------------------------- run

def run(reviews: List[dict], desk: List[dict], packages: Dict[str, dict],
        candle_fn: Callable[[str, str], Optional[List[dict]]], prior: Dict[str, dict], now: float) -> dict:
    recs, inventory = forecast_records(reviews, desk, packages)
    cache: Dict[Tuple[str, str], Optional[List[dict]]] = {}

    def bars(sym: str, tf: str) -> Optional[List[dict]]:
        if (sym, tf) not in cache:
            cache[(sym, tf)] = candle_fn(sym, tf)
        return cache[(sym, tf)]

    out: List[dict] = []
    for r in recs:
        old = prior.get(r["fid"])
        if old and old.get("class") in FINAL:                  # frozen: 1m ties cannot be re-derived later
            out.append(old)
            continue
        t0 = cf._ts(r["made_at"])
        base = {"fid": r["fid"], "source": r["source"], "package": r["package"], "symbol": r["symbol"],
                "made_at": r["made_at"], "p_target": r["p_target"], "target_px": cf._num(r["fc"].get("target_px")),
                "invalidation_px": cf._num(r["fc"].get("invalidation_px")), "horizon_bars": r["fc"].get("horizon_bars"),
                "timeframe": r["fc"].get("timeframe")}
        if t0 is None or not r["symbol"]:
            g = {"class": "no_data", "reason": "symbol_unknown" if t0 else "made_at_unparseable"}
        else:
            tf = str(r["fc"].get("timeframe"))
            g = first_passage(r["fc"], t0, bars(r["symbol"], tf), bars(r["symbol"], "1m"), now)
        out.append({**base, **g})
    by_src = {s: summarise([x for x in out if x["source"] == s]) for s in ("live_review", "desk_entry")}
    return {"schema_version": SCHEMA, "computed_at": cf._iso(now), "rule": "FORECAST-GRADE-FIRST-PASSAGE",
            "population": f"{len(out)} forecasts: " + ", ".join(
                f"{s}={by_src[s]['n']}" for s in by_src) + " (every record carrying target+invalidation+horizon+probability)",
            "pending": [{"fid": x["fid"], "source": x["source"], "symbol": x["symbol"], "horizon_end": x.get("horizon_end"),
                         "time_remaining_s": x.get("time_remaining_s")} for x in out if x["class"] == "pending"],
            "inventory": inventory, "pooled": summarise(out), "by_source": by_src,
            "read_state": {"candles": "live /api/bot/candles (tf + 1m)", "ledger": str(LEDGER.relative_to(REPO)),
                           "null_means": "could-not-look (no_data / tie_unresolved), never 0"},
            "_ledger": out}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="packages + candles from the live API")
    ap.add_argument("--write", action="store_true", help="write forecast_grade.json + forecast_ledger.jsonl")
    ap.add_argument("--rows-ref", default="origin/live-review/rows")
    ap.add_argument("--desk-ref", default="origin/desk/decisions")
    a = ap.parse_args(argv)
    if not a.live:
        print("forecast_first_passage: --live is required")
        return 2
    reviews, rs = load_live_review(a.rows_ref)
    desk, ds = load_desk(a.desk_ref)
    pk = cf.fetch_diag("journal?table=order_packages&limit=1000")
    pk = pk.get("rows", pk) if isinstance(pk, dict) else pk
    packages = {p["order_package_id"]: p for p in pk}
    prior = {r["fid"]: r for r in cf.read_jsonl(LEDGER) if r.get("fid")}
    now = datetime.now(timezone.utc).timestamp()
    res = run(reviews, desk, packages, cf.fetch_candles_live, prior, now)
    res["read_state"].update(live_review=rs, desk=ds, packages_read=len(packages))
    ledger = res.pop("_ledger")
    for r in ledger:                                          # volatile fields live in forecast_grade.json only, so the
        r.pop("time_remaining_s", None)                       # ledger changes (and commits) only when a state changes
    print(json.dumps({k: res[k] for k in ("population", "inventory", "pooled", "by_source")}, indent=1))
    if a.write:
        OUT.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
        LEDGER.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in sorted(ledger, key=lambda r: r["fid"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
