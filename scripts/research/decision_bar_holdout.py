#!/usr/bin/env python3
"""Closed-bar vs forming-bar ENTRY decision, per leg, graded by the holdout standard.

RQ-20261018-2a10-01 / RULE-RQ-20261018-2a10-01 (checklist DECISION-BAR-CLOSED-1018).

WHY. The live pullback / donchian VARIANT builders decide on the still-FORMING bar
every ~2 min tick (``decision_bar`` default ``forming``); every Stage-0 harness
scores the CLOSED bar. PR #18870 (scripts/research/live_bt_trade_join.py) found the
real-money decay on bybit_2 is mostly ENTRY divergence: xrp_pullback_2h live -7.15R
vs closed-bar backtest -2.36R (entry -5.79R), ada_pullback_2h -6.49R vs -2.75R
(entry -3.89R). RQ-20260929-301/302 measured the same gap with a 90% CI rule and
were underpowered on every leg (MDE 31-62R per leg), so no decision came out of
them. This unit grades the SAME two arms with the operator's holdout standard
(PROMOTION-BAR-MULTIPLICITY, 2026-10-16: select on the earliest span, test the one
selected configuration ONCE on the held-back latest span) — the repo's current rule
for choosing between two configurations of a live leg.

WHAT IT RUNS (nothing re-implemented):
  * arms   scripts/research/forming_bar_pooled_regrade.leg_run — Stage-0 harness
           (scripts/backtest_pullback.py / backtest_trend.py) config-exact to the
           leg's config/strategies.yaml block, full cost stack from execution_costs,
           ``decision_bar="closed"`` (arm A) and ``decision_bar="forming"`` (arm B,
           scripts/research/forming_bar_entries.py — the live decision at the 2-min
           tick cadence from 1m data).
  * data   Binance USD-M perp 1m klines (data.binance.vision), a LABELLED PROXY for
           Bybit; pinned with ``--end`` so a re-run reproduces the record.
  * split  scripts/research/exit_lever_ablation.holdout_boundary / discovery_trades /
           holdout_trades — the same boundary rule the holdout re-runs use.

THE RULE (registered in the unit BEFORE the run; this module only applies it):
  boundary   latest ``holdout_frac`` of the calendar window, grown in 1% steps until
             it holds ``holdout_min_trades`` of arm A's entries, capped at
             ``holdout_max_frac`` (A = closed, the Stage-0 configuration, as the
             other holdout units place it on the declared arm).
  discovery  trades entered AND exited before the boundary; ``folds`` equal calendar
             folds of the discovery span. dR_disc = net R(closed) - net R(forming).
  selection  CLOSED is selected iff both arms hold >= ``n_floor`` discovery trades
             AND dR_disc >= ``select_delta_r`` AND closed is ahead in >=
             ``fold_majority`` of the folds. Otherwise the INCUMBENT (what the leg
             trades live today) stays selected.
  holdout    read ONCE: dR_hold = net R(closed) - net R(forming) on trades entered on
             or after the boundary.
  verdicts   (incumbent forming)  CLOSED_WINS if closed selected and dR_hold > 0 ->
             the evidence for a Tier-3 ``decision_bar: closed`` proposal;
             CLOSED_NOT_REPLICATED if selected and dR_hold <= 0 (no change);
             FORMING_STANDS if closed not selected (no change; forming_better_both_spans
             is reported when forming is ahead on both spans);
             INDETERMINATE when either arm holds < n_floor discovery trades or the
             boundary hit its cap short of holdout_min_trades (underpowered, no change).
             (incumbent closed) the same statistics, mapped KEEP_CLOSED /
             KEEP_CLOSED_UNCONFIRMED / RESEARCH_FLAG_FORMING_AHEAD / INDETERMINATE —
             never a proposal to revert (a permissive change needs its own evidence).
  reported, never gating: trade-set Jaccard, month-block bootstrap 90% interval and
             MDE of the full-history dR (forming_bar_pooled_regrade.pooled_stats), and
             each leg's committed evidence record restated under both arms over the
             record's own window (forming_bar_pooled_regrade.restate).

Edits no config, roster or record; places no order. Writes <out>/verdict.json and
<out>/arms/<leg>__{A_closed,B_forming}__trades.jsonl (the closed arm is the
``--bt-trades`` input live_bt_trade_join.py needs).
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

UNIT = "RQ-20261018-2a10-01"
RULE = "RULE-RQ-20261018-2a10-01"
DATA_SOURCE = ("Binance USD-M perp 1m klines (data.binance.vision); a LABELLED PROXY for "
               "Bybit (api.bybit.com is geo-blocked from the research containers)")

#: Pre-registered parameters (the unit's decision_rule quotes these values).
PARAMS: Dict[str, Any] = {
    "holdout_frac": 0.25, "holdout_min_trades": 25, "holdout_max_frac": 0.40,
    "n_floor": 25, "folds": 4, "fold_majority": 3, "select_delta_r": 5.0,
}

PROPOSAL = "CLOSED_WINS"


# ── pure grading ────────────────────────────────────────────────────────────
def _ts(s: Any):
    import pandas as pd
    t = pd.Timestamp(str(s))
    return t.tz_localize("UTC") if t.tzinfo is None else t


def calendar_edges(lo: Any, hi: Any, n: int) -> list:
    """n+1 equal calendar boundaries over [lo, hi]."""
    lo, hi = _ts(lo), _ts(hi)
    if n < 1 or hi <= lo:
        raise ValueError(f"need n >= 1 and lo < hi (got n={n}, {lo} .. {hi})")
    step = (hi - lo) / n
    return [lo + step * i for i in range(n)] + [hi]


def _net(trades: List[dict]) -> float:
    return round(sum(float(t.get("net_r") or 0.0) for t in trades), 4)


def _span(trades: List[dict], lo: Any, hi: Any, *, last: bool = False) -> List[dict]:
    lo, hi = _ts(lo), _ts(hi)
    return [t for t in trades if lo <= _ts(t["entry_time"]) < hi
            or (last and _ts(t["entry_time"]) == hi)]


def fold_table(a: List[dict], b: List[dict], edges: list) -> List[dict]:
    """Per calendar fold: n / net R of each arm and dR = closed - forming."""
    out = []
    for i in range(len(edges) - 1):
        last = i == len(edges) - 2
        fa, fb = _span(a, edges[i], edges[i + 1], last=last), _span(b, edges[i], edges[i + 1], last=last)
        out.append({"fold": i + 1, "start": str(edges[i]), "end": str(edges[i + 1]),
                    "closed": {"n": len(fa), "net_r": _net(fa)},
                    "forming": {"n": len(fb), "net_r": _net(fb)},
                    "delta_r": round(_net(fa) - _net(fb), 4)})
    return out


def _stats(trades: List[dict]) -> Dict[str, Any]:
    n = len(trades)
    net = _net(trades)
    return {"n": n, "net_r": net, "expectancy_r": round(net / n, 4) if n else None}


def grade_leg(a_closed: List[dict], b_forming: List[dict], lo: Any, hi: Any, *,
              incumbent: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply RULE-RQ-20261018-2a10-01 to one leg's two arms. Pure."""
    import exit_lever_ablation as ela
    p = dict(PARAMS, **(params or {}))
    incumbent = str(incumbent or "forming").lower()
    if incumbent not in ("forming", "closed"):
        raise ValueError(f"incumbent must be forming|closed, got {incumbent!r}")
    lo, hi = _ts(lo), _ts(hi)
    plan = ela.holdout_boundary([t["entry_time"] for t in a_closed], lo, hi,
                                frac=p["holdout_frac"], min_trades=p["holdout_min_trades"],
                                max_frac=p["holdout_max_frac"])
    boundary = plan["boundary"]
    da, db = ela.discovery_trades(a_closed, boundary), ela.discovery_trades(b_forming, boundary)
    ha, hb = ela.holdout_trades(a_closed, boundary, hi), ela.holdout_trades(b_forming, boundary, hi)
    edges = calendar_edges(lo, boundary, int(p["folds"]))
    folds = fold_table(da, db, edges)
    closed_ahead = sum(1 for f in folds if f["delta_r"] > 0)
    d_disc = round(_net(da) - _net(db), 4)
    d_hold = round(_net(ha) - _net(hb), 4)
    enough_disc = len(da) >= p["n_floor"] and len(db) >= p["n_floor"]
    closed_selected = bool(enough_disc and d_disc >= p["select_delta_r"]
                           and closed_ahead >= p["fold_majority"])
    forming_both = d_disc < 0 and d_hold < 0

    if not enough_disc:
        verdict, reason = "INDETERMINATE", "insufficient_discovery"
    elif plan["short_at_cap"]:
        verdict, reason = "INDETERMINATE", "underpowered_holdout"
    elif closed_selected:
        verdict = "CLOSED_WINS" if d_hold > 0 else "CLOSED_NOT_REPLICATED"
        reason = "confirmed" if d_hold > 0 else "not_replicated"
    else:
        verdict, reason = "FORMING_STANDS", ("forming_ahead" if d_disc < 0 else "closed_not_robust")
    if incumbent == "closed":
        # Labelling only (the statistics and thresholds are the same): a leg already on
        # the closed bar keeps it; the label says what the rule found. FORMING_STANDS
        # splits by its reason — forming ahead on discovery is a research flag, closed
        # ahead but not robust across folds is not a finding against the incumbent.
        verdict = {"CLOSED_WINS": "KEEP_CLOSED", "CLOSED_NOT_REPLICATED": "KEEP_CLOSED_UNCONFIRMED",
                   "FORMING_STANDS": ("RESEARCH_FLAG_FORMING_AHEAD" if reason == "forming_ahead"
                                      else "KEEP_CLOSED_NOT_SELECTED")}.get(verdict, verdict)
    proposal = ("decision_bar: closed (Tier-3, operator approval)" if verdict == PROPOSAL
                else None)
    return {
        "rule": RULE, "params": p, "incumbent": incumbent,
        "window": [str(lo), str(hi)],
        "boundary": {"at": str(boundary), "share": plan["share"], "grown": plan["grown"],
                     "short_at_cap": plan["short_at_cap"],
                     "closed_entries_in_holdout": plan["baseline_n_holdout"]},
        "discovery": {"closed": _stats(da), "forming": _stats(db), "delta_r": d_disc,
                      "folds": folds, "folds_closed_ahead": closed_ahead,
                      "closed_selected": closed_selected},
        "holdout": {"closed": _stats(ha), "forming": _stats(hb), "delta_r": d_hold},
        "forming_better_both_spans": bool(forming_both),
        "verdict": verdict, "reason": reason, "proposal": proposal,
    }


# ── runner ──────────────────────────────────────────────────────────────────
def _family(leg: str) -> str:
    import forming_bar_pooled_regrade as fbr
    fam = dict(fbr.POPULATION).get(leg)
    if fam:
        return fam
    rec = ROOT / "comms/strategy_evidence" / f"{leg}.json"
    if rec.exists():
        h = json.loads(rec.read_text()).get("harness")
        if h in ("pullback", "trend"):
            return h
    raise SystemExit(f"{leg}: not in forming_bar_pooled_regrade.POPULATION and no evidence "
                     f"record names its harness — register it first")


def _routings(leg: str) -> List[Dict[str, str]]:
    from src.config.accounts_loader import load_accounts_dict
    acc = load_accounts_dict()
    if not acc:
        raise SystemExit("accounts.yaml unreadable — refusing to report no routings")
    out = []
    for name, a in acc.items():
        legs = {s if isinstance(s, str) else s.get("name") for s in (a.get("strategies") or [])}
        if leg in legs:
            out.append({"account": name, "account_class": str(a.get("account_class")),
                        "mode": str(a.get("mode"))})
    return out


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def run(args: argparse.Namespace) -> Dict[str, Any]:
    import pandas as pd
    import yaml
    import forming_bar_pooled_regrade as fbr
    vs = fbr.vs
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())
    cfg = cfg.get("strategies", cfg)
    legs = list(args.leg)
    legs.sort(key=lambda lg: str(cfg[lg]["symbols"][0]))  # one 1m load per symbol
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
        fam = _family(leg)
        r = fbr.leg_run(leg, fam, block, m1_cache[sym], tmp, args.workers)
        incumbent = str(block.get("decision_bar") or "forming").lower()
        g = grade_leg(r["_A"], r["_B"], r["first_decision_bar"], r["last_bar"],
                      incumbent=incumbent, params=vars(args).get("params"))
        stats = fbr.pooled_stats([r])
        res = {k: v for k, v in r.items() if not k.startswith("_")}
        res.update({
            "routings": _routings(leg),
            "full_history": {"closed": r["A_closed"], "forming": r["B_forming"],
                             "delta_r_closed_minus_forming": round(-r["delta_net_r"], 4),
                             "jaccard": r["jaccard"],
                             "month_block_ci90_forming_minus_closed": stats["ci90"],
                             "mde_80pct_power": stats["mde_80pct_power"],
                             "per_year_delta_forming_minus_closed": stats["per_year_delta"]},
            "record_restatement": fbr.restate(r),
            "grade": g,
        })
        results[leg] = res
        _write_jsonl(out_dir / "arms" / f"{leg}__A_closed__trades.jsonl", r["_A"])
        _write_jsonl(out_dir / "arms" / f"{leg}__B_forming__trades.jsonl", r["_B"])
        _write_verdict(out_dir, args, legs, results, partial=True)  # a later crash keeps this leg
        print(f"{leg:26s} closed n={r['A_closed']['n']:4d} {r['A_closed']['net_r']:+8.2f}R | "
              f"forming n={r['B_forming']['n']:4d} {r['B_forming']['net_r']:+8.2f}R | "
              f"disc dR={g['discovery']['delta_r']:+.2f} folds {g['discovery']['folds_closed_ahead']}/"
              f"{g['params']['folds']} | hold dR={g['holdout']['delta_r']:+.2f} "
              f"(closed n={g['holdout']['closed']['n']}) -> {g['verdict']}", flush=True)
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()
    return _write_verdict(out_dir, args, legs, results, partial=False)


def _write_verdict(out_dir: Path, args: argparse.Namespace, legs: List[str],
                   results: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out = {
        "unit": args.research_unit or UNIT, "rule": RULE, "params": dict(PARAMS),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": DATA_SOURCE, "window_end_pin": args.end,
        "population": (f"{len(legs)} legs ({', '.join(legs)}): every (account, leg) routing of each is "
                       f"listed under legs[].routings; arms config-exact to config/strategies.yaml; "
                       f"entries on bars with a 200-bar live frame"),
        "complete": not partial, "legs_graded": sorted(results),
        "legs": results,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--klines-dir", required=True)
    ap.add_argument("--out", required=True, help="directory: verdict.json + arms/*.jsonl")
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--end", default=None, help="pin the window end (UTC, e.g. '2026-10-16 23:59')")
    ap.add_argument("--research-unit", default=UNIT)
    args = ap.parse_args(argv)
    out = run(args)
    print(json.dumps({lg: r["grade"]["verdict"] for lg, r in out["legs"].items()}))
    print(f"wrote {Path(args.out) / 'verdict.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
