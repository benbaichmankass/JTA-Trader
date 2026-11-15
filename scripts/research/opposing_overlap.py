#!/usr/bin/env python3
"""When do opposite-direction legs on ONE symbol both keep positive expectancy? (row CONFLICTING-EXPOSURE-ALERT)

The live-trade review's rule of thumb for a conflicting-exposure alert ("keep both" vs "close one side") comes
from here. Operator, 2026-11-11: *"we should understand what circumstances justify doing that"*.

METHOD (registered in the research unit before any run; thresholds live in the unit's decision_rule)
------
* Corpus: every leg in ``config/strategies.yaml`` whose committed Stage-0 per-trade rows load through
  ``live_review_outcomes.load_trades`` (``--corpus auto``: the full-history LTR corpus, else the evidence
  record's ``source_run``). ``net_r`` is already net of the full cost stack (fee + slippage + funding).
* An OPPOSED PAIR: two trades from DIFFERENT legs on the same symbol, opposite directions, whose
  [entry_time, exit_time) intervals overlap. The NEWCOMER is the later entry; the INCUMBENT was already open.
* The decision point is the newcomer's entry (that is when the alert fires). The newcomer's whole-trade
  ``net_r`` is therefore free of look-ahead. The incumbent's whole-trade ``net_r`` includes R it had already
  accrued before the newcomer opened: it is reported, labelled ``incumbent_whole_trade_biased``, and is NOT
  used by the rule.
* Buckets: timeframe gap = longer-TF / shorter-TF leg (``same`` = 1, ``2-4x``, ``>4x``), and which side is the
  newcomer (``newcomer_shorter_tf`` / ``newcomer_longer_tf`` / ``same_tf``); vol regime = the newcomer's stop
  width |entry - sl| / entry against its own leg's median (stops are ATR multiples, so this is an ATR% proxy
  known at entry): ``high_vol`` / ``low_vol``.
* Unit of analysis: unique newcomer trades per bucket (a trade opposed by several incumbents counts once).
  Statistic: mean newcomer net_r with a 95% normal CI; baseline = the same legs' trades that were never
  opposed (context only).

Verdict per bucket (n floor and thresholds from ``--n-floor``; the unit fixes them):
  KEEP_BOTH_OK      newcomer CI95 lower bound > 0 (opening against an open opposite leg still has edge)
  CLOSE_NEWCOMER    newcomer CI95 upper bound < 0 (the opposed newcomer loses money: close / skip that side)
  INDETERMINATE     otherwise, or unique newcomers < n floor

Pure read of committed files; writes only ``--out``. No order, config or roster is read for action.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

_TF_S = {"m": 60, "h": 3600, "d": 86400}


def tf_seconds(tf: Any) -> int | None:
    s = str(tf or "").strip().lower()
    if len(s) >= 2 and s[:-1].isdigit() and s[-1] in _TF_S:
        return int(s[:-1]) * _TF_S[s[-1]]
    return None


def _ts(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T", 1)).timestamp()
    except ValueError:
        return None


def load_universe(strategies_path: Path = REPO / "config" / "strategies.yaml",
                  legs: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import live_review_outcomes as lro
    import yaml
    cfg = (yaml.safe_load(strategies_path.read_text()) or {}).get("strategies") or {}
    names = legs or [k for k, v in cfg.items() if isinstance(v, dict)]
    trades: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    for leg in names:
        tf = tf_seconds((cfg.get(leg) or {}).get("timeframe"))
        try:
            rows, src = lro.load_trades(leg, corpus="auto")
        except Exception as exc:  # noqa: BLE001  # allow-silent: listed as could_not_load with the reason
            sources[leg] = {"state": "could_not_load", "reason": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        kept = 0
        for t in rows:
            e, x = _ts(t.get("entry_time")), _ts(t.get("exit_time"))
            if e is None or x is None or t.get("net_r") is None or t.get("direction") not in ("long", "short"):
                continue
            trades.append({"leg": leg, "symbol": str(t.get("symbol") or "").upper(), "direction": t["direction"],
                           "entry_ts": e, "exit_ts": x, "net_r": float(t["net_r"]), "tf_s": tf,
                           "stop_pct": (abs(float(t["entry"]) - float(t["sl"])) / float(t["entry"])
                                        if t.get("entry") and t.get("sl") else None)})
            kept += 1
        sources[leg] = {"state": "loaded", "source": src, "trades": kept, "timeframe_s": tf}
    return trades, sources


def gap_bucket(a: int | None, b: int | None) -> str:
    if not a or not b:
        return "unknown_tf"
    r = max(a, b) / min(a, b)
    return "same" if r == 1 else "2-4x" if r <= 4 else ">4x"


def find_pairs(trades: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(incumbent, newcomer) for every overlapping opposite-direction pair from different legs."""
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)
    out = []
    for rows in by_sym.values():
        rows.sort(key=lambda t: t["entry_ts"])
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if b["entry_ts"] >= a["exit_ts"]:
                    break
                if a["leg"] != b["leg"] and a["direction"] != b["direction"] and b["entry_ts"] > a["entry_ts"]:
                    out.append((a, b))
    return out


def _stats(xs: list[float]) -> dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean_r": None, "ci95": None}
    m = statistics.fmean(xs)
    if n < 2:
        return {"n": n, "mean_r": round(m, 4), "ci95": None}
    se = statistics.stdev(xs) / math.sqrt(n)
    return {"n": n, "mean_r": round(m, 4), "sd_r": round(statistics.stdev(xs), 4),
            "ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)], "p_pos": round(sum(x > 0 for x in xs) / n, 3)}


def verdict(st: dict[str, Any], n_floor: int) -> str:
    if st["n"] < n_floor or not st.get("ci95"):
        return "INDETERMINATE"
    lo, hi = st["ci95"]
    return "KEEP_BOTH_OK" if lo > 0 else "CLOSE_NEWCOMER" if hi < 0 else "INDETERMINATE"


def analyse(trades: list[dict[str, Any]], n_floor: int = 30) -> dict[str, Any]:
    pairs = find_pairs(trades)
    med: dict[str, float] = {}
    by_leg: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        if t["stop_pct"]:
            by_leg[t["leg"]].append(t["stop_pct"])
    med = {k: statistics.median(v) for k, v in by_leg.items() if v}
    buckets: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    inc: dict[str, dict[int, float]] = defaultdict(dict)
    opposed = set()
    for a, b in pairs:
        opposed.add(id(a))
        opposed.add(id(b))
        g = gap_bucket(a["tf_s"], b["tf_s"])
        role = ("same_tf" if g == "same" else "newcomer_shorter_tf" if (b["tf_s"] or 0) < (a["tf_s"] or 0)
                else "newcomer_longer_tf")
        vol = ("vol_unknown" if not b["stop_pct"] or b["leg"] not in med
               else "high_vol" if b["stop_pct"] > med[b["leg"]] else "low_vol")
        for key in ("ALL", f"gap={g}", f"gap={g}|{role}", f"gap={g}|{role}|{vol}", f"vol={vol}"):
            buckets[key][id(b)] = b["net_r"]
            inc[key][id(a)] = a["net_r"]
    res = {}
    for key in sorted(buckets):
        st = _stats(list(buckets[key].values()))
        res[key] = {"newcomer": st, "verdict": verdict(st, n_floor),
                    "incumbent_whole_trade_biased": _stats(list(inc[key].values()))}
    base = _stats([t["net_r"] for t in trades if id(t) not in opposed])
    return {"pairs": len(pairs), "trades": len(trades), "never_opposed_baseline": base,
            "n_floor": n_floor, "buckets": res}


RULE_ID = "RULE-CE-OPPOSED-NEWCOMER-01"
RULE_REGISTERED_AT = "2026-11-11"
#: The unit asks "does the opposed NEWCOMER keep positive expectancy?"; the unit-level verdict is the ALL bucket's
#: (what this script has always printed), mapped onto the E5 vocabulary. Per-bucket verdicts stay in measurement.
E5_VERDICT = {"KEEP_BOTH_OK": "pass", "CLOSE_NEWCOMER": "fail", "INDETERMINATE": "indeterminate"}
#: The level the live-review rule of thumb is written from (the unit's rule); deeper keys are discoveries.
RULE_LEVEL_KEYS = ("gap=2-4x|newcomer_shorter_tf", "gap=2-4x|newcomer_longer_tf", "gap=>4x|newcomer_shorter_tf",
                   "gap=>4x|newcomer_longer_tf", "gap=same|same_tf")


def verdict_record(res: dict[str, Any], unit: str | None) -> dict[str, Any]:
    """The E5 verdict.json for this run (ce01-01 landed producer_failed for want of one)."""
    allb = res["buckets"].get("ALL")
    if not allb or not allb["newcomer"]["n"]:
        return {"schema_version": 1, "research_unit": unit, "read_state": "no_data", "verdict": "not_applicable",
                "n": None, "population": {"n": None, "description": "no opposed newcomer trade in the corpus"},
                "note": "no_data: looked, found no opposed pair", "decision_rule": {"id": RULE_ID,
                "registered_at": RULE_REGISTERED_AT, "registered_before_run": True}, "measurement": res}
    allv = allb["verdict"]
    rule_level = {k: res["buckets"][k]["verdict"] for k in RULE_LEVEL_KEYS if k in res["buckets"]}
    decided = {k: v for k, v in rule_level.items() if v != "INDETERMINATE"}
    n = int(allb["newcomer"]["n"])
    return {
        "schema_version": 1, "research_unit": unit, "read_state": "measured", "verdict": E5_VERDICT[allv], "n": n,
        "population": {"n": n, "description": (
            f"unique NEWCOMER trades opposed by an open opposite-direction trade of a different leg on the same symbol, "
            f"{res['pairs']} opposed pairs over {res['trades']} committed Stage-0 trades ({sum(1 for v in (res.get('sources') or {}).values() if isinstance(v, dict) and v.get('state') == 'loaded')} legs loaded); "
            "net_r net of each corpus's full cost stack")},
        "note": (f"ALL bucket {allv} (newcomer mean {allb['newcomer']['mean_r']:+.4f} R, CI95 {allb['newcomer']['ci95']}, "
                 f"n {n}) -> E5 {E5_VERDICT[allv]} (the question: does the opposed newcomer keep positive expectancy?). "
                 f"Rule-level (gap|role) decided buckets: {decided or 'none'}; every other rule-level bucket INDETERMINATE "
                 "(reviewer's priced judgement). gap|role|vol verdicts are discoveries pending a disjoint window."),
        "decision_rule": {"id": RULE_ID, "registered_at": RULE_REGISTERED_AT, "registered_before_run": True},
        "rule_level_verdicts": rule_level,
        "data_inputs": sorted({str(v["source"]) for v in (res.get("sources") or {}).values()
                               if isinstance(v, dict) and v.get("state") == "loaded" and v.get("source")}),
        "measurement": res,
    }


def self_test() -> int:
    H = 3600
    tr = [
        {"leg": "a_4h", "symbol": "S", "direction": "short", "entry_ts": 0, "exit_ts": 100 * H, "net_r": 2.0,
         "tf_s": 4 * H, "stop_pct": 0.02},
        {"leg": "b_1h", "symbol": "S", "direction": "long", "entry_ts": 10 * H, "exit_ts": 20 * H, "net_r": -1.0,
         "tf_s": H, "stop_pct": 0.01},
        {"leg": "b_1h", "symbol": "S", "direction": "long", "entry_ts": 200 * H, "exit_ts": 210 * H, "net_r": 1.0,
         "tf_s": H, "stop_pct": 0.01},
        {"leg": "a_4h", "symbol": "S", "direction": "short", "entry_ts": 15 * H, "exit_ts": 30 * H, "net_r": 0.5,
         "tf_s": 4 * H, "stop_pct": 0.02},   # same leg as the incumbent: never a pair with it
        {"leg": "c_1h", "symbol": "T", "direction": "long", "entry_ts": 10 * H, "exit_ts": 20 * H, "net_r": 1.0,
         "tf_s": H, "stop_pct": 0.01},
    ]
    pairs = find_pairs(tr)
    ok = len(pairs) == 2 and all(a["leg"] != b["leg"] for a, b in pairs)
    r = analyse(tr, n_floor=1)
    ok &= r["buckets"]["gap=2-4x|newcomer_shorter_tf"]["newcomer"]["n"] == 1
    ok &= r["never_opposed_baseline"]["n"] == 2
    ok &= verdict({"n": 40, "ci95": [0.1, 0.3]}, 30) == "KEEP_BOTH_OK"
    ok &= verdict({"n": 40, "ci95": [-0.4, -0.1]}, 30) == "CLOSE_NEWCOMER"
    ok &= verdict({"n": 10, "ci95": [0.1, 0.3]}, 30) == "INDETERMINATE"
    v = verdict_record(r, "RQ-TEST")
    ok &= v["read_state"] == "measured" and v["verdict"] in ("pass", "fail", "indeterminate") and v["n"] >= 1
    ok &= verdict_record({"pairs": 0, "trades": 0, "buckets": {}}, "RQ-TEST")["read_state"] == "no_data"
    ok &= E5_VERDICT["CLOSE_NEWCOMER"] == "fail" and E5_VERDICT["KEEP_BOTH_OK"] == "pass"
    json.dumps(v, default=str)
    print("self-test", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit")
    ap.add_argument("--out")
    ap.add_argument("--n-floor", type=int, default=30)
    ap.add_argument("--legs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    trades, sources = load_universe(legs=a.legs)
    res = analyse(trades, a.n_floor)
    res.update(unit=a.unit, sources=sources, harness="scripts/research/opposing_overlap.py",
               cost_basis="net_r from each committed Stage-0 corpus (fee + slippage + funding)")
    allv = res["buckets"].get("ALL", {}).get("verdict", "INDETERMINATE")
    res["verdict"] = allv
    text = json.dumps(res, indent=1, sort_keys=True, default=str)
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(text)
        # the E5 record the collector grades (RQ-20261111-ce01-01 run 43172978800 landed producer_failed without it)
        (out / "verdict.json").write_text(json.dumps(verdict_record(res, a.unit), indent=1, sort_keys=True, default=str))
    print(f"RESULT verdict={allv} pairs={res['pairs']} trades={res['trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
