#!/usr/bin/env python3
# wiring: manual-only — the "Desk" section generator for /performance-review (CLAUDE-GRADE-LOOP); the skill runs it each review, /perf-followup Track 2 reads its --json, the weekly-audit C13 check reads its population. No timer.
"""Grade the Claude trading desk: the "Desk" section of /performance-review (CLAUDE-GRADE-LOOP).

    python3 scripts/ops/desk_grade.py                      # markdown section over the records on main
    python3 scripts/ops/desk_grade.py --json               # machine form (perf-followup Track 2 reads this)
    python3 scripts/ops/desk_grade.py --live               # + what the SYSTEM traded in the same windows (diag journal)
    python3 scripts/ops/desk_grade.py --since 2026-10-26

Projects over the canonical desk records -- ``comms/desk/decisions.jsonl`` joined to
``comms/desk/outcomes.jsonl`` on ``decision_id`` (written by ``scripts/ops/desk_outcomes.py`` from the
desk-decisions-mirror) and to the decision's own scan packet ``comms/desk/packets/<packet_id>.json``. It keeps
no store of its own. Every figure carries its population; ``None`` means "could not look", never 0.

WHAT IS COMPARED (rules registered here, before any run reads them; tests pin them)
* DESK = each ``propose_entry`` decision's outcome row of kind ``replayed`` (its own bracket on the real
  path from ``info_cutoff_at``, net of the full cost stack) or ``realised`` (an account's fill). An
  ``expired_unfilled`` proposal is a decision with no trade (counted, R = 0 is NOT imputed). A ``no_trade``
  decision has no own outcome until DESK-20 prices its baseline bracket; it is counted ``not_computable``.
* RANDOM-ENTRY BASELINE = the packet's own ``history.rows`` cell for the proposal's (symbol, side,
  timeframe) at the nearest ``horizon_bars``: the mean net R of entering on every closed bar before the
  cutoff, net of the full cost stack. ``edge_vs_random = net_r - baseline.mean_r``, paired per proposal.
  Stated limit: the baseline's R unit is ``atr_stop_1x`` and the proposal's is its own planned risk.
* SYSTEM = (``--live`` only) the strategy legs' packages created inside the desk's grading window on the
  packet's universe symbols, joined to their closed trades, net R on the package's INITIAL stop
  (``src.runtime.net_r_label``). Unpaired: the desk and the system did not take the same trades.
* CALIBRATION: ``proposal.tp.p_hit`` vs ``close_reason == tp_hit`` (``claude_calibration.probability``);
  the categorical ``confidence`` vs net R (``claude_calibration.ordinal``); and the optimism gap
  ``mean(expected_r_net - net_r)``.
* EDGE verdicts (``vs_random``, ``vs_system``, ``absolute``): ``EDGE`` / ``NEGATIVE`` only when the
  population is >= ``EDGE_MIN_N`` AND the 95% interval of the mean excludes 0; else ``INDETERMINATE``
  with the reason. Only ``pre_cutoff: false`` and ``training.gate_eligible: true`` decisions count
  toward a verdict (out of sample for the judging model); the rest are reported, not graded.
* PROMOTION GATE (the graded-shadow path of proposed use rule (b),
  docs/plans/ml-claude-distillation-DESIGN.md § 3.7): ``ELIGIBLE_TO_PROPOSE`` only when ``absolute``,
  ``vs_random`` AND ``vs_system`` all read ``EDGE``; else ``NOT_YET`` naming the failing clause. The D-S0
  replay (DESK-7/18) is the primary, offline path; this is the sufficient alternative, never a wait. It is a
  proposal surface; the operator grants the stage. Once live, ``NEGATIVE`` here is the demotion signal.
* Every figure is also split by ``skill_sha`` (the DESK-BRIEF.md blob the wake read), never pooled.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import claude_calibration as cal  # noqa: E402

DESK = REPO / "comms" / "desk"
DECISIONS = DESK / "decisions.jsonl"
OUTCOMES = DESK / "outcomes.jsonl"
PACKETS = DESK / "packets"
EDGE_MIN_N = 30
_TF_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "30m": 0.5, "1h": 1, "2h": 2, "4h": 4, "1d": 24}
NO_TRADE_WINDOW_BARS = 48          # the window a no_trade decision is compared over (the scan's longest history horizon)
_Z95 = 1.96
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042}


def _t95(df: int) -> float:
    """Two-sided 95% Student-t critical value, rounded UP to the next tabled df (conservative)."""
    for k in sorted(_T95):
        if df <= k:
            return _T95[k]
    return _Z95


def read_jsonl(p: Path) -> List[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _stats(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "mean": None, "worst": None, "hit_rate": None, "ci95": None}
    ci = None
    if len(xs) >= 2:
        m, sd = statistics.fmean(xs), statistics.stdev(xs)
        half = _t95(len(xs) - 1) * sd / math.sqrt(len(xs))
        ci = [round(m - half, 4), round(m + half, 4)]
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 4), "worst": round(min(xs), 4),
            "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3), "ci95": ci}


def edge_verdict(s: Dict[str, Any]) -> str:
    if s["n"] < EDGE_MIN_N or s["ci95"] is None:
        return f"INDETERMINATE (n={s['n']} < {EDGE_MIN_N})"
    lo, hi = s["ci95"]
    if lo > 0:
        return "EDGE"
    if hi < 0:
        return "NEGATIVE"
    return "INDETERMINATE (interval includes 0)"


def welch(a: List[float], b: List[float]) -> Dict[str, Any]:
    """Unpaired mean(a) - mean(b) with a normal-approximation 95% interval (n counted as min of the two)."""
    if len(a) < 2 or len(b) < 2:
        return {"n": min(len(a), len(b)), "n_desk": len(a), "n_system": len(b), "mean": None, "ci95": None}
    d = statistics.fmean(a) - statistics.fmean(b)
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    return {"n": min(len(a), len(b)), "n_desk": len(a), "n_system": len(b), "mean": round(d, 4),
            "ci95": [round(d - _Z95 * se, 4), round(d + _Z95 * se, 4)]}


def load_packet(packet_id: Optional[str], packets: Path = PACKETS) -> Optional[dict]:
    if not packet_id:
        return None
    p = packets / f"{packet_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def random_baseline(packet: Optional[dict], proposal: dict) -> Optional[dict]:
    rows = ((packet or {}).get("history") or {}).get("rows") or []
    cand = [r for r in rows if r.get("symbol") == proposal.get("symbol") and r.get("side") == proposal.get("side")
            and r.get("timeframe") == proposal.get("timeframe") and r.get("mean_r") is not None]
    if not cand:
        return None
    hb = proposal.get("horizon_bars") or 0
    best = min(cand, key=lambda r: (abs((r.get("horizon_bars") or 0) - hb), r.get("horizon_bars") or 0))
    return {"mean_r": best["mean_r"], "n": best.get("n"), "horizon_bars": best.get("horizon_bars"),
            "r_unit": (packet.get("history") or {}).get("r_unit")}


def grading_window(d: dict) -> Optional[tuple]:
    start = _ts(d.get("info_cutoff_at"))
    if start is None:
        return None
    pr = d.get("proposal") or {}
    tf = pr.get("timeframe") or (d.get("packet_id") or "").rsplit("-", 1)[-1]
    hours = _TF_HOURS.get(tf, 1)
    bars = (pr.get("horizon_bars") or 0) + ((pr.get("entry") or {}).get("good_till_bars") or 0) or NO_TRADE_WINDOW_BARS
    return start, start + timedelta(hours=hours * bars)


def join(decisions: List[dict], outcomes: List[dict]) -> List[dict]:
    by: Dict[str, List[dict]] = defaultdict(list)
    for o in outcomes:
        by[o["decision_id"]].append(o)
    rows = []
    for d in decisions:
        os_ = by.get(d["decision_id"], [])
        priced = [o for o in os_ if o.get("kind") in ("replayed", "realised") and o.get("net_r") is not None]
        # one figure per decision: a realised fill outranks the replay (it is the measurement); several
        # accounts' realised fills of one decision are averaged so a fan-out does not weight it twice
        real = [o for o in priced if o["kind"] == "realised"]
        use = real or [o for o in priced if o["kind"] == "replayed"]
        kinds = sorted({o.get("kind") for o in os_})
        rows.append({"decision": d, "outcomes": os_, "kinds": kinds,
                     "net_r": round(statistics.fmean(o["net_r"] for o in use), 6) if use else None,
                     "net_source": (use[0]["kind"] if use else None),
                     "tp_hit": (None if not use or use[0].get("close_reason") is None
                                else 1.0 if use[0].get("close_reason") == "tp_hit" else 0.0)})
    return rows


def _gradeable(d: dict) -> bool:
    return d.get("pre_cutoff") is False and bool((d.get("training") or {}).get("gate_eligible"))


def grade(decisions: List[dict], outcomes: List[dict], packets: Path = PACKETS,
          system_trades: Optional[Callable[[datetime, datetime, List[str]], Optional[List[float]]]] = None) -> Dict[str, Any]:
    rows = join(decisions, outcomes)
    pop: Dict[str, Any] = {
        "n_decisions": len(decisions),
        "by_role_action": dict(Counter(f"{d.get('role')}/{d.get('action')}" for d in decisions)),
        "by_outcome_kind": dict(Counter("+".join(r["kinds"]) or "awaiting_outcome_row" for r in rows)),
        "not_computable_reasons": dict(Counter(o.get("reason") for r in rows for o in r["outcomes"] if o.get("kind") == "not_computable")),
        "n_pre_cutoff_or_gate_ineligible": sum(1 for d in decisions if not _gradeable(d)),
    }
    props = [r for r in rows if r["decision"].get("action") == "propose_entry"]
    priced = [r for r in props if r["net_r"] is not None]
    graded = [r for r in priced if _gradeable(r["decision"])]
    pop.update({"n_proposals": len(props), "n_proposals_priced": len(priced),
                "n_proposals_expired_unfilled": sum(1 for r in props if "expired_unfilled" in r["kinds"]),
                "n_proposals_awaiting": sum(1 for r in props if not r["outcomes"]),
                "n_priced_gradeable": len(graded), "n_no_trade": sum(1 for d in decisions if d.get("action") == "no_trade")})
    pairs, base_missing = [], 0
    for r in graded:
        b = random_baseline(load_packet(r["decision"].get("packet_id"), packets), r["decision"]["proposal"])
        if b is None:
            base_missing += 1
        else:
            pairs.append(r["net_r"] - b["mean_r"])
    absolute = _stats([r["net_r"] for r in graded])
    vs_random = {**_stats(pairs), "baseline_missing": base_missing,
                 "r_unit_note": "baseline R is atr_stop_1x; the proposal's R is its own planned risk"}
    absolute["verdict"], vs_random["verdict"] = edge_verdict(absolute), edge_verdict(vs_random)

    system: Dict[str, Any] = {"state": "not_requested (run with --live)"}
    if system_trades is not None:
        windows = [w for w in (grading_window(r["decision"]) for r in rows) if w]
        syms = sorted({u.get("symbol") for r in rows for u in
                       ((load_packet(r["decision"].get("packet_id"), packets) or {}).get("universe") or []) if u.get("symbol")})
        if windows and syms:
            sys_r = system_trades(min(w[0] for w in windows), max(w[1] for w in windows), syms)
            if sys_r is None:
                system = {"state": "could_not_look"}
            else:
                system = {"state": "read", "window": [min(w[0] for w in windows).isoformat(), max(w[1] for w in windows).isoformat()],
                          "symbols": syms, "system_closed": _stats(sys_r), "vs_system": welch([r["net_r"] for r in graded], sys_r)}
                vs = system["vs_system"]
                vs["verdict"] = edge_verdict({"n": vs["n"], "ci95": vs["ci95"]})
        else:
            system = {"state": "no_window_or_universe"}

    p_hit = cal.probability(((r["decision"]["proposal"].get("tp") or {}).get("p_hit"), r["tp_hit"]) for r in priced)
    conf = cal.ordinal((r["decision"].get("confidence"), r["net_r"]) for r in priced)
    opt = [(r["decision"]["proposal"].get("expected_r_net") - r["net_r"]) for r in priced
           if r["decision"]["proposal"].get("expected_r_net") is not None]
    by_conf = {c: _stats([r["net_r"] for r in priced if r["decision"].get("confidence") == c])
               for c in sorted({r["decision"].get("confidence") for r in props if r["decision"].get("confidence")})}
    by_sha: Dict[str, Any] = {}
    for sha in sorted({d.get("skill_sha") or "unrecorded" for d in decisions}):
        ds = [r for r in rows if (r["decision"].get("skill_sha") or "unrecorded") == sha]
        by_sha[sha] = {"n_decisions": len(ds), "first_judged_at": min(r["decision"].get("judged_at") or "" for r in ds),
                       "by_action": dict(Counter(r["decision"].get("action") for r in ds)),
                       "proposals_priced": _stats([r["net_r"] for r in ds if r["net_r"] is not None])}
    gate_fail = [k for k, v in (("absolute", absolute), ("vs_random", vs_random),
                                ("vs_system", system.get("vs_system") or {"verdict": "not_read"})) if v["verdict"] != "EDGE"]
    gate = {"verdict": "ELIGIBLE_TO_PROPOSE" if not gate_fail else "NOT_YET",
            "failing": gate_fail, "rule": "absolute, vs_random and vs_system all EDGE (n >= %d, 95%% CI excludes 0, out of sample)" % EDGE_MIN_N}
    return {"population": pop, "absolute": absolute, "vs_random": vs_random, "system": system,
            "calibration": {"p_hit": p_hit, "confidence_vs_net_r": conf,
                            "optimism_expected_minus_realised": _stats(opt)},
            "by_confidence": by_conf, "by_skill_sha": by_sha, "promotion_gate": gate}


def render(g: Dict[str, Any], window: str) -> str:
    p, a, v, s, c = g["population"], g["absolute"], g["vs_random"], g["system"], g["calibration"]
    L = [f"## Desk ({window})", "",
         f"**Population:** {p['n_decisions']} desk decision(s) {p['by_role_action']}; outcome rows {p['by_outcome_kind']}"
         f" (not computable: {p['not_computable_reasons'] or '{}'}). {p['n_proposals']} proposal(s): "
         f"**{p['n_proposals_priced']} priced**, {p['n_proposals_expired_unfilled']} expired unfilled, "
         f"{p['n_proposals_awaiting']} awaiting their horizon; {p['n_priced_gradeable']} out-of-sample and gate-eligible. "
         f"{p['n_no_trade']} no_trade decision(s) (priced only once DESK-20 builds the baseline bracket). "
         f"{p['n_pre_cutoff_or_gate_ineligible']} pre-cutoff or gate-ineligible (reported, never graded).", "",
         "| comparison | n | mean R | CI95 | hit | verdict |", "|---|---|---|---|---|---|",
         f"| desk proposals, net of cost | {a['n']} | {a['mean']} | {a['ci95']} | {a['hit_rate']} | {a['verdict']} |",
         f"| desk minus random entry (paired) | {v['n']} | {v['mean']} | {v['ci95']} | {v['hit_rate']} | {v['verdict']} |"]
    if s.get("state") == "read":
        ss, vs = s["system_closed"], s["vs_system"]
        L += [f"| system legs, same window + universe | {ss['n']} | {ss['mean']} | {ss['ci95']} | {ss['hit_rate']} | — |",
              f"| desk minus system (unpaired) | {vs['n']} | {vs['mean']} | {vs['ci95']} | — | {vs['verdict']} |"]
    else:
        L.append(f"| system legs, same window + universe | — | — | — | — | {s.get('state')} |")
    L += ["", f"Random baseline missing for {v['baseline_missing']} proposal(s); {v['r_unit_note']}.", "",
          f"**Calibration.** `p_hit` vs TP hit: n={c['p_hit']['n']}, Brier {c['p_hit']['brier']} vs ref {c['p_hit']['brier_ref']}, "
          f"gap {c['p_hit']['overconfidence_gap']} -> **{c['p_hit']['verdict']}**. Confidence category vs net R: "
          f"{c['confidence_vs_net_r']['by_category']} -> **{c['confidence_vs_net_r']['verdict']}**. Optimism "
          f"(expected_r_net - realised): n={c['optimism_expected_minus_realised']['n']}, mean {c['optimism_expected_minus_realised']['mean']}.",
          "", "**By brief version** (`skill_sha` of DESK-BRIEF.md; never pooled):"]
    for sha, b in g["by_skill_sha"].items():
        L.append(f"- `{sha[:8]}` (from {b['first_judged_at'][:16]}): {b['n_decisions']} decision(s) {b['by_action']}, "
                 f"priced n={b['proposals_priced']['n']} mean {b['proposals_priced']['mean']}")
    gt = g["promotion_gate"]
    L += ["", f"**Promotion gate (proposed rule (b)):** {gt['verdict']}" + (f" (failing: {gt['failing']})" if gt["failing"] else "")
          + f". Rule: {gt['rule']}."]
    return "\n".join(L)


def live_system_trades(start: datetime, end: datetime, symbols: List[str]) -> Optional[List[float]]:
    """Net R of the strategy legs' closed trades whose package was created in [start, end] on ``symbols``."""
    import live_review_counterfactual as cf
    from src.runtime.net_r_label import net_r_for_trade
    try:
        pk = cf.fetch_diag("journal?table=order_packages&limit=500")
        pk = pk.get("rows", pk) if isinstance(pk, dict) else pk
        tr = cf.fetch_diag("journal?table=trades&limit=1000")
        tr = tr.get("rows", tr) if isinstance(tr, dict) else tr
    except (RuntimeError, ValueError) as exc:
        print(f"desk_grade: system journal unavailable: {exc}", file=sys.stderr)
        return None
    pkgs = {p["order_package_id"]: p for p in pk if p.get("symbol") in symbols
            and (p.get("strategy_name") or p.get("strategy")) != "claude_desk"
            and (t := _ts(p.get("created_at"))) is not None and start <= t <= end}
    out = []
    for t in tr:
        p = pkgs.get(t.get("order_package_id"))
        if p is None or str(t.get("status") or "").lower() != "closed" or p.get("sl") is None:
            continue
        lab = net_r_for_trade(dict(t, stop_loss=p["sl"]))
        if lab is not None:
            out.append(lab["net_R"])
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decisions", default=str(DECISIONS))
    ap.add_argument("--outcomes", default=str(OUTCOMES))
    ap.add_argument("--since", help="ISO date: only decisions judged at/after it")
    ap.add_argument("--live", action="store_true", help="also read what the system traded in the same windows")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ds = read_jsonl(Path(a.decisions))
    if a.since:
        ds = [d for d in ds if (d.get("judged_at") or "") >= a.since]
    g = grade(ds, read_jsonl(Path(a.outcomes)), system_trades=live_system_trades if a.live else None)
    window = f"since {a.since}" if a.since else "all decisions on main"
    print(json.dumps(g, indent=1, default=str) if a.json else render(g, window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
