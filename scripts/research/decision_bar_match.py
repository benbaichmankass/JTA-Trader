#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261113-* (FORMING-VS-CLOSED-ETH4H-SOL4H) dispatches it; RQ-20261022-4de5-01/-02 ran it session-local
"""Decision-bar MATCH: which bar should a leg decide on, and does its evidence describe that bar?

RQ-20261022-4de5-01 / RULE-RQ-20261022-4de5-01 (checklist DECISION-BAR-MATCH). Also builds the
tp_r ledgers RQ-20261022-4de5-02 feeds to prop_ev_grid (``--tp-variant``).

WHY. Operator 2026-10-22: a closed-bar backtest does NOT count as evidence for a forming-bar leg
("No — match the bar"). Operator 2026-10-18: treat closed-vs-forming as an IMPROVEMENT test (a
paired per-fold delta with a materiality floor, fold-majority robustness); switch to closed if it
wins; demote only if NEITHER bar clears RULE-D1. RULE-RQ-20261018-2a10-01
(decision_bar_holdout.py) asked whether closed robustly beats the incumbent; this asks which bar,
then whether the record can describe it.

WHAT IT RUNS (nothing re-implemented): forming_bar_pooled_regrade.leg_run (the two arms, full
cost stack, config-exact) and .restate (RULE-D1 per arm on the record window);
decision_bar_holdout.calendar_edges for the folds.

THE RULE (registered in the unit BEFORE the run; this module only applies it):
  folds      6 equal calendar folds of [first_decision_bar, last bar]; dR_k = net R(closed) -
             net R(forming); floor m_k = max(1.0R, 0.02R x max(n_closed_k, n_forming_k)).
             Fold is CLOSED if dR_k >= m_k, FORMING if dR_k <= -m_k, else TIE.
  better     CLOSED_BETTER iff >= 4 CLOSED folds, <= 1 FORMING fold, dR_full > 0;
             FORMING_BETTER symmetric; else NO_MATERIAL_DIFFERENCE.
  preferred  the better bar; on NO_MATERIAL_DIFFERENCE, closed (the committed record already
             describes it — a tie-break, not an edge claim).
  verdict    preferred passes RULE-D1 on the record window -> SWITCH_TO_CLOSED /
             KEEP_FORMING_REBASE_RECORD; else the other bar, only when nothing was materially
             better; else DEMOTE_CANDIDATE.

Edits no config, roster or record; places no order. Writes <out>/verdict.json and
<out>/arms/<leg>[__tp<x>]__{A_closed,B_forming}__trades.jsonl.

E5 (row FORMING-VS-CLOSED-ETH4H-SOL4H, 2026-11-13). ``verdict.json`` also carries the E5 result fields the
research-script-run collector reads (``verdict``/``read_state``/``population``/``n`` + one ``records`` row per leg run),
DERIVED from the grades above -- the grading is unchanged. Per leg: ``pass`` = the outcome maps to "closed >= forming
within the band" (verdict SWITCH_TO_CLOSED, or better NO_MATERIAL_DIFFERENCE); ``fail`` = better FORMING_BETTER;
``indeterminate`` = the leg could not be graded. Unit: indeterminate if any leg is; else pass if every leg passes; else
fail (each leg's own call is in ``records``). ``--rule`` names the unit's rule id (default the 2026-10-22 one).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "research"), str(ROOT / "scripts"), str(ROOT)]

UNIT = "RQ-20261022-4de5-01"
RULE = "RULE-RQ-20261022-4de5-01"
DATA_SOURCE = ("Binance USD-M perp 1m klines (data.binance.vision); a LABELLED PROXY for "
               "Bybit (api.bybit.com is geo-blocked from the research containers)")

#: Pre-registered parameters (the unit's decision_rule quotes these values).
PARAMS: Dict[str, Any] = {"folds": 6, "fold_majority": 4, "max_opposite": 1,
                          "floor_r": 1.0, "floor_per_trade_r": 0.02}


# ── pure grading ────────────────────────────────────────────────────────────
def fold_calls(folds: List[dict], params: Optional[Dict[str, Any]] = None) -> List[dict]:
    """Annotate decision_bar_holdout.fold_table rows with the floor and the call."""
    p = dict(PARAMS, **(params or {}))
    out = []
    for f in folds:
        n = max(f["closed"]["n"], f["forming"]["n"])
        m = round(max(p["floor_r"], p["floor_per_trade_r"] * n), 4)
        d = f["delta_r"]
        call = "CLOSED" if d >= m else ("FORMING" if d <= -m else "TIE")
        out.append(dict(f, floor_r=m, call=call))
    return out


def better_bar(folds: List[dict], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p = dict(PARAMS, **(params or {}))
    c = sum(1 for f in folds if f["call"] == "CLOSED")
    fm = sum(1 for f in folds if f["call"] == "FORMING")
    d = round(sum(f["delta_r"] for f in folds), 4)
    if c >= p["fold_majority"] and fm <= p["max_opposite"] and d > 0:
        v = "CLOSED_BETTER"
    elif fm >= p["fold_majority"] and c <= p["max_opposite"] and d < 0:
        v = "FORMING_BETTER"
    else:
        v = "NO_MATERIAL_DIFFERENCE"
    return {"better": v, "folds_closed": c, "folds_forming": fm,
            "folds_tie": len(folds) - c - fm, "delta_r_full": d}


def match_verdict(better: str, d1_closed: Optional[bool], d1_forming: Optional[bool]) -> Dict[str, Any]:
    """Map the better-bar call and RULE-D1 per arm (record window) to the verdict. Pure."""
    if d1_closed is None or d1_forming is None:
        return {"preferred": None, "adopted": None, "verdict": "INDETERMINATE",
                "reason": "record_window_unreadable"}
    preferred = "forming" if better == "FORMING_BETTER" else "closed"
    other = "closed" if preferred == "forming" else "forming"
    d1 = {"closed": d1_closed, "forming": d1_forming}
    if d1[preferred]:
        adopted, reason = preferred, "preferred_passes_d1"
    elif better == "NO_MATERIAL_DIFFERENCE" and d1[other]:
        adopted, reason = other, "tie_other_passes_d1"
    else:
        return {"preferred": preferred, "adopted": None, "verdict": "DEMOTE_CANDIDATE",
                "reason": "no_admissible_bar_clears_d1"}
    verdict = "SWITCH_TO_CLOSED" if adopted == "closed" else "KEEP_FORMING_REBASE_RECORD"
    return {"preferred": preferred, "adopted": adopted, "verdict": verdict, "reason": reason}


def grade_leg(a_closed: List[dict], b_forming: List[dict], lo: Any, hi: Any,
              restated: Optional[Dict[str, Any]], *, incumbent: str = "forming",
              params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import decision_bar_holdout as dbh
    p = dict(PARAMS, **(params or {}))
    edges = dbh.calendar_edges(lo, hi, int(p["folds"]))
    folds = fold_calls(dbh.fold_table(a_closed, b_forming, edges), p)
    bb = better_bar(folds, p)
    d1c = d1f = None
    if restated and "proxy_closed" in restated:
        d1c = restated["proxy_closed"]["net_r"] > 0
        d1f = restated["proxy_forming"]["net_r"] > 0
    mv = match_verdict(bb["better"], d1c, d1f)
    if incumbent == "closed" and mv["verdict"] == "SWITCH_TO_CLOSED":
        mv = dict(mv, verdict="MATCHED_KEEP_CLOSED")
    return {"rule": RULE, "params": p, "incumbent": incumbent, "window": [str(lo), str(hi)],
            "folds": folds, **bb,
            "rule_d1_record_window": {"closed": d1c, "forming": d1f,
                                      "window": (restated or {}).get("window")},
            **mv}


# ── runner ──────────────────────────────────────────────────────────────────
def _write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def _tp_variants(specs: List[str]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for s in specs:
        leg, v = s.split("=", 1)
        out.setdefault(leg, []).append(float(v))
    return out


def run(args: argparse.Namespace) -> Dict[str, Any]:
    import pandas as pd
    import yaml
    import decision_bar_holdout as dbh
    import forming_bar_pooled_regrade as fbr
    vs = fbr.vs
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())
    cfg = cfg.get("strategies", cfg)
    legs = sorted(args.leg, key=lambda lg: str(cfg[lg]["symbols"][0]))  # one 1m load per symbol
    tpv = _tp_variants(args.tp_variant or [])
    out_dir = Path(args.out)
    tmp = out_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(args.end, tz="UTC") if args.end else None
    m1_cache: Dict[str, Any] = {}
    results: Dict[str, Any] = {}
    for leg in legs:
        block = cfg[leg]
        if not block.get("enabled"):
            raise SystemExit(f"{leg} is not enabled — population drifted; re-register")
        sym = str(block["symbols"][0])
        if sym not in m1_cache:
            if args.fetch:
                vs.fetch_1m(args.klines_dir, sym)
            m1 = vs.load_1m(args.klines_dir, sym)
            if end is not None:
                m1 = m1[m1["ts"] <= end].reset_index(drop=True)
            m1_cache = {sym: m1}
        fam = dbh._family(leg)
        incumbent = str(block.get("decision_bar") or "forming").lower()
        variants = [(None, block)] + [(tp, dict(block, tp_r=tp)) for tp in tpv.get(leg, [])]
        for tp, blk in variants:
            key = leg if tp is None else f"{leg}__tp{tp:g}"
            r = fbr.leg_run(leg, fam, blk, m1_cache[sym], tmp, args.workers)
            rest = fbr.restate(r)
            g = grade_leg(r["_A"], r["_B"], r["first_decision_bar"], r["last_bar"], rest,
                          incumbent=incumbent)
            res = {k: v for k, v in r.items() if not k.startswith("_")}
            res.update({"tp_r": blk.get("tp_r"), "tp_variant": tp is not None,
                        "routings": dbh._routings(leg), "record_restatement": rest, "grade": g})
            results[key] = res
            _write_jsonl(out_dir / "arms" / f"{key}__A_closed__trades.jsonl", r["_A"])
            _write_jsonl(out_dir / "arms" / f"{key}__B_forming__trades.jsonl", r["_B"])
            _write_verdict(out_dir, args, results, partial=True)
            print(f"{key:30s} closed n={r['A_closed']['n']:4d} {r['A_closed']['net_r']:+8.2f}R | "
                  f"forming n={r['B_forming']['n']:4d} {r['B_forming']['net_r']:+8.2f}R | folds "
                  f"C{g['folds_closed']}/F{g['folds_forming']}/T{g['folds_tie']} dR={g['delta_r_full']:+.2f} "
                  f"| D1 rec c={g['rule_d1_record_window']['closed']} f={g['rule_d1_record_window']['forming']} "
                  f"-> {g['better']} / {g['verdict']}", flush=True)
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()
    return _write_verdict(out_dir, args, results, partial=False)


def e5_fields(results: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    """The E5 result fields, derived from each leg run's ``grade`` (pure; the grading itself is untouched)."""
    records = []
    for key in sorted(results):
        r = results[key]
        g = r.get("grade") or {}
        better, verdict = g.get("better"), g.get("verdict")
        if verdict in (None, "INDETERMINATE"):
            v, rs, n = "indeterminate", "producer_failed", None
        else:
            v = "fail" if better == "FORMING_BETTER" else "pass"
            rs = "measured"
            n = (r.get("A_closed") or {}).get("n", 0) + (r.get("B_forming") or {}).get("n", 0)
        d1 = g.get("rule_d1_record_window") or {}
        records.append({
            "leg": key, "verdict": v, "read_state": rs, "n": n,
            "population": (f"{key}: closed vs forming decision bar, Binance USD-M 1m proxy, full cost stack, "
                           f"improvement folds over {g.get('window')}, RULE-D1 on the record window {d1.get('window')}"),
            "better": better, "match_verdict": verdict, "reason": g.get("reason"),
            "folds_closed": g.get("folds_closed"), "folds_forming": g.get("folds_forming"),
            "folds_tie": g.get("folds_tie"), "delta_r_full": g.get("delta_r_full"),
            "closed": {k: (r.get("A_closed") or {}).get(k) for k in ("n", "net_r")},
            "forming": {k: (r.get("B_forming") or {}).get(k) for k in ("n", "net_r")},
            "rule_d1_record_window": {"closed": d1.get("closed"), "forming": d1.get("forming")},
            "note": (f"better={better}, verdict={verdict}: "
                     + ("closed >= forming within the band -> propose decision_bar: closed (Tier 3, manager)"
                        if v == "pass" else "forming materially better -> keep forming; propose an entry-hold fix"
                        if v == "fail" else "not graded")),
        })
    measured = [x for x in records if x["read_state"] == "measured"]
    if partial or not records:
        top, rs, why = "not_applicable", "producer_failed", "the run did not complete (partial verdict.json)"
    elif len(measured) < len(records):
        top, rs, why = "indeterminate", "measured", "a leg could not be graded"
    elif all(x["verdict"] == "pass" for x in measured):
        top, rs, why = "pass", "measured", "every leg: closed >= forming within the band"
    else:
        top, rs, why = "fail", "measured", ("forming materially better on: "
                                            + ", ".join(x["leg"] for x in measured if x["verdict"] == "fail"))
    return {"verdict": top, "read_state": rs, "n": sum(x["n"] for x in measured) if measured else None,
            "note": why, "records": records}


def _write_verdict(out_dir: Path, args: argparse.Namespace, results: Dict[str, Any], *,
                   partial: bool) -> Dict[str, Any]:
    out = {
        "unit": args.research_unit, "rule": getattr(args, "rule", None) or RULE, "params": dict(PARAMS),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": DATA_SOURCE, "window_end_pin": args.end,
        "population": (f"{len(results)} leg runs ({', '.join(sorted(results))}); every (account, leg) "
                       f"routing under legs[].routings; arms config-exact to config/strategies.yaml "
                       f"(a __tp<x> run overrides tp_r only); entries on bars with a 200-bar live frame"),
        "complete": not partial, "legs": results,
        **e5_fields(results, partial=partial),
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--klines-dir", required=True)
    ap.add_argument("--out", required=True, help="directory: verdict.json + arms/*.jsonl")
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--tp-variant", action="append", default=[], metavar="LEG=TP_R",
                    help="also run LEG with tp_r overridden (RQ-20261022-4de5-02 ledgers)")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--end", default=None, help="pin the window end (UTC, e.g. '2026-10-20 23:59')")
    ap.add_argument("--research-unit", default=UNIT)
    ap.add_argument("--rule", default=RULE, help="the unit's decision-rule id, recorded in verdict.json")
    args = ap.parse_args(argv)
    out = run(args)
    print(json.dumps({k: r["grade"]["verdict"] for k, r in out["legs"].items()}))
    print(f"wrote {Path(args.out) / 'verdict.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
