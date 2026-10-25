#!/usr/bin/env python3
"""NEWS-VETO-EVAL (WEPE gate G1, research unit RQ-20261009-902) -- does the live news layer add net R?

Rule REGISTERED BEFORE THIS RAN: ``RULE-RQ1009-902-NEWS-VETO-NET-R`` in
``research/queue/RQ-20261009-902.yaml``. This script implements it as written and
never edits it.

ARM A -- rank IC (Spearman) between the signed news ``adjustment`` and net R over
DISTINCT TAKEN trades. The adjustment is read from the order package's
``meta.news`` stamp (``src/runtime/pipeline.py`` writes it onto every actionable
signal before sizing), joined to the closed trade by ``order_package_id``. That is
an EXACT key; the log-file join the unit sketched (strategy + symbol + side + ts
within one tick) is only needed for rows that never became a package, i.e. Arm B.
Net R = journal gross pnl - fee_taker - fee_maker - funding, minus the modelled
round-trip slippage (``execution_costs.slippage_bps_roundtrip_for``) because the
journal carries no slippage column, divided by the SL-distance risk basis
(``net_r_label.risk_usd_for_trade``). Only trades with ``cost_source`` in
{broker, estimate} are graded; un-costed rows are counted and excluded.

ARM B -- the veto. A vetoed signal never becomes a package or a trade, and the
news log carries no entry/sl/tp, so a counterfactual needs a harness replay that
is OUT OF SCOPE here. This script only COUNTS veto rows (``log_aggregate``) and
reports the arm as UNDERPOWERED with the date the floor is reachable. It never
grades it (rule: below distinct-vetoed n 25 -> UNDERPOWERED, never pass/kill).

Not a calibration: no base probability is logged, so no Brier/ECE is claimed.

Tier-1 research tooling: reads the journal + diag log via ``scripts/ops/diag_fetch.sh``
(or a directory of pre-pulled jsonl), writes only the --out JSON. No config write.

# wiring: manual-only - one-shot research run for RQ-20261009-902.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.execution_costs import slippage_bps_roundtrip_for  # noqa: E402
from src.runtime.net_r_label import net_r_for_trade, risk_usd_for_trade  # noqa: E402

RULE_ID = "RULE-RQ1009-902-NEWS-VETO-NET-R"
ARM_A_FLOOR = 49          # PASS/FAIL graded at or above
ARM_A_LEAD_FLOOR = 25     # 25..48: IC reported as a lead; below: INSUFFICIENT_BASE
ARM_B_FLOOR = 25
PERMUTATIONS = 20000
SEED = 20261012
PAGE = 1000
# Data-quality guard, not a result filter: a stop-loss trade cannot lose thousands of R. Rows beyond this
# are a broken risk basis (e.g. a futures row journaled without its contract multiplier, so qty*1 understates
# risk by orders of magnitude -- mhg_pullback_1d shows -2666R on 2026-10-12). Reported both ways.
IMPLAUSIBLE_ABS_R = 20.0


# --------------------------------------------------------------------------- stats
def _avg_ranks(values: List[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sxx * syy) ** 0.5


def spearman_one_sided(x: List[float], y: List[float], perms: int = PERMUTATIONS,
                       seed: int = SEED) -> Dict[str, Any]:
    """Spearman rho with a one-sided (rho > 0) permutation p-value.

    Permutation, not a t-approximation, because the adjustment is ~95% exact ties
    at 0.0 and the t-approximation assumes continuous ranks. p uses the +1
    correction so it is never reported as 0.
    """
    n = len(x)
    if n < 3:
        return {"n": n, "rho": None, "p_one_sided": None}
    rx, ry = _avg_ranks(list(x)), _avg_ranks(list(y))
    rho = _pearson(rx, ry)
    if rho is None:
        return {"n": n, "rho": None, "p_one_sided": None, "note": "constant input"}
    rng = random.Random(seed)
    ge = 0
    shuffled = list(ry)
    for _ in range(perms):
        rng.shuffle(shuffled)
        r = _pearson(rx, shuffled)
        if r is not None and r >= rho - 1e-12:
            ge += 1
    return {"n": n, "rho": round(rho, 6), "p_one_sided": round((ge + 1) / (perms + 1), 6)}


# ----------------------------------------------------------------------- data join
def _json_field(v: Any) -> Optional[dict]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else None
        except ValueError:
            return None
    return None


def full_cost_net_r(trade: dict) -> Optional[Dict[str, Any]]:
    """Journal-cost net R, then minus modelled round-trip slippage. None if uncomputable."""
    base = net_r_for_trade(trade)
    risk = risk_usd_for_trade(trade)
    if base is None or risk is None:
        return None
    try:
        notional = abs(float(trade["entry_price"])) * abs(float(trade["position_size"]))
    except (KeyError, TypeError, ValueError):
        return None
    cv = 1.0
    for k in ("contract_value_usd", "contract_value"):
        try:
            if trade.get(k) is not None and float(trade[k]) > 0:
                cv = float(trade[k])
                break
        except (TypeError, ValueError):
            pass
    slip_usd = notional * cv * slippage_bps_roundtrip_for(trade.get("symbol")) / 1e4
    return {
        "net_R_journal_cost": base["net_R"],
        "net_R": round(base["net_R"] - slip_usd / risk, 8),
        "costed": base["costed"],
        "cost_source": base["cost_source"],
    }


def build_taken_rows(packages: Iterable[dict], trades: Iterable[dict]) -> Dict[str, Any]:
    """One row per package that (a) carries meta.news and (b) has a closed, non-backtest trade."""
    pk: Dict[str, dict] = {}
    for p in packages:
        pid = p.get("order_package_id")
        if pid:
            pk[pid] = p
    n_pkg = len(pk)
    n_news = 0
    rows: List[dict] = []
    drop = {"no_trade": 0, "not_closed": 0, "backtest": 0, "r_uncomputable": 0, "uncosted": 0}
    seen: set = set()
    for t in trades:
        pid = t.get("order_package_id")
        if pid not in pk or pid in seen:
            continue
        meta = _json_field(pk[pid].get("meta")) or {}
        news = meta.get("news")
        if not isinstance(news, dict) or news.get("adjustment") is None:
            continue
        seen.add(pid)
        if t.get("is_backtest"):
            drop["backtest"] += 1
            continue
        if t.get("status") != "closed":
            drop["not_closed"] += 1
            continue
        r = full_cost_net_r(t)
        if r is None:
            drop["r_uncomputable"] += 1
            continue
        if not r["costed"]:
            drop["uncosted"] += 1
            continue
        rows.append({
            "order_package_id": pid,
            "strategy": t.get("strategy_name") or pk[pid].get("strategy_name"),
            "symbol": t.get("symbol"),
            "direction": t.get("direction"),
            "account_id": t.get("account_id"),
            "account_class": t.get("account_class"),
            "created_at": pk[pid].get("created_at"),
            "adjustment": float(news["adjustment"]),
            "decision": news.get("decision"),
            "item_count": news.get("item_count"),
            "net_R": r["net_R"],
            "net_R_journal_cost": r["net_R_journal_cost"],
        })
    n_news = sum(1 for p in pk.values()
                 if isinstance((_json_field(p.get("meta")) or {}).get("news"), dict))
    return {"rows": rows, "packages_total": n_pkg, "packages_with_news_stamp": n_news, "dropped": drop}


def signal_clusters(rows: List[dict]) -> List[dict]:
    """Collapse packages from the SAME signal across accounts (strategy, symbol, direction, minute).

    The rule grades one row per package; this is the sensitivity that says how
    many INDEPENDENT signals those packages really are (same news stamp, highly
    correlated outcome). Net R is averaged within a cluster.
    """
    groups: Dict[tuple, List[dict]] = {}
    for r in rows:
        key = (r["strategy"], r["symbol"], r["direction"], (r["created_at"] or "")[:16])
        groups.setdefault(key, []).append(r)
    return [{"adjustment": g[0]["adjustment"], "decision": g[0]["decision"],
             "net_R": sum(x["net_R"] for x in g) / len(g), "k": len(g)} for g in groups.values()]


def _bucket_stats(rows: List[dict]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in ("boost", "reduce", "neutral"):
        v = [r["net_R"] for r in rows if r["decision"] == name]
        out[name] = {"n": len(v), "mean_net_R": round(sum(v) / len(v), 6) if v else None}
    return out


def _stat_view(rows: List[dict]) -> Dict[str, Any]:
    return {"n": len(rows), "spearman": spearman_one_sided([r["adjustment"] for r in rows],
                                                           [r["net_R"] for r in rows]),
            "buckets_mean_net_R": _bucket_stats(rows)}


def grade_arm_a(all_rows: List[dict]) -> Dict[str, Any]:
    rows = [r for r in all_rows if abs(r["net_R"]) <= IMPLAUSIBLE_ABS_R]
    excluded = [r for r in all_rows if abs(r["net_R"]) > IMPLAUSIBLE_ABS_R]
    n = len(rows)
    stat = spearman_one_sided([r["adjustment"] for r in rows], [r["net_R"] for r in rows])
    buckets = _bucket_stats(rows)
    clusters = signal_clusters(rows)
    cstat = spearman_one_sided([c["adjustment"] for c in clusters], [c["net_R"] for c in clusters])
    rho, p = stat.get("rho"), stat.get("p_one_sided")
    reduce_gt_boost = (buckets["reduce"]["mean_net_R"] is not None
                       and buckets["boost"]["mean_net_R"] is not None
                       and buckets["reduce"]["mean_net_R"] > buckets["boost"]["mean_net_R"])
    if n < ARM_A_LEAD_FLOOR:
        verdict = "INSUFFICIENT_BASE"
    elif n < ARM_A_FLOOR:
        verdict = "LEAD_ONLY"  # 25..48: IC reported as a lead, not graded
    elif rho is None:
        verdict = "INSUFFICIENT_BASE"
    elif (rho > 0 and p is not None and p < 0.05) and not reduce_gt_boost:
        verdict = "PASS"
    elif rho <= 0 or reduce_gt_boost:
        verdict = "FAIL"
    else:
        # rho>0 but p>=0.05 at n>=49: the rule defines PASS and FAIL only; do not invent a third.
        verdict = "NOT_PASS_NOT_FAIL"
    return {
        "verdict": verdict,
        "n_distinct_taken_packages": n,
        "implausible_risk_basis_excluded": {
            "threshold_abs_R": IMPLAUSIBLE_ABS_R, "n": len(excluded),
            "strategies": sorted({str(r["strategy"]) for r in excluded}),
            "sensitivity_unfiltered": _stat_view(all_rows)},
        "spearman": stat,
        "buckets_mean_net_R": buckets,
        "reduce_mean_exceeds_boost_mean": reduce_gt_boost,
        "sensitivity_signal_clusters": {"n": len(clusters), "spearman": cstat,
                                        "note": "same-signal packages across accounts collapsed; "
                                                "not the registered statistic"},
        "by_account_class": {k: sum(1 for r in rows if r["account_class"] == k)
                             for k in sorted({r["account_class"] for r in rows if r["account_class"]})},
        "nonzero_adjustment_rows": sum(1 for r in rows if r["adjustment"] != 0.0),
    }


def grade_arm_b(veto_rows: Optional[int], first_day: Optional[str], last_day: Optional[str],
                days_with_veto: Optional[int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "verdict": "UNDERPOWERED", "grade_attempted": False,
        "reason": "veto signals never become packages; the news log carries no entry/sl/tp, so the "
                  "counterfactual needs a harness replay (out of scope). Counted only.",
        "veto_log_rows": veto_rows, "days_with_veto": days_with_veto,
        "floor": ARM_B_FLOOR,
    }
    if veto_rows is None or not first_day or not last_day:
        out["read_state"] = "could_not_look"
        return out
    d0, d1 = date.fromisoformat(first_day), date.fromisoformat(last_day)
    span = (d1 - d0).days + 1
    rate = veto_rows / span if span else 0.0
    out.update({"read_state": "complete", "log_span_days": span, "rows_per_day": round(rate, 4)})
    if rate > 0 and veto_rows < ARM_B_FLOOR:
        out["floor_reachable_upper_bound_date"] = (
            d1 + timedelta(days=int((ARM_B_FLOOR - veto_rows) / rate + 0.999))).isoformat()
        out["floor_basis"] = ("rows, not distinct signals: the log writes one row per signal "
                              "evaluation per tick, so this is an UPPER BOUND on accrual speed")
    return out


def g1_read(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    """Unit-level G1 read, copied from the registered rule."""
    if a["verdict"] == "FAIL" or b["verdict"] == "FAIL":
        return "RETIRE_OR_REPLACE"
    if a["verdict"] == "PASS" and b["verdict"] == "PASS":
        return "PASS"
    return "OPEN"


# --------------------------------------------------------------------------- I/O
def _fetch_pages(table: str) -> List[dict]:
    out: List[dict] = []
    off = 0
    while True:
        res = subprocess.run(
            [str(REPO / "scripts/ops/diag_fetch.sh"), f"journal?table={table}&limit={PAGE}&offset={off}"],
            capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"diag_fetch failed for {table}@{off}: exit {res.returncode}")
        page = json.loads(res.stdout)
        if isinstance(page, dict):
            page = page.get("rows", [])
        out.extend(page)
        if len(page) < PAGE:
            return out
        off += PAGE


def _fetch_veto_aggregate() -> Optional[dict]:
    res = subprocess.run(
        [str(REPO / "scripts/ops/diag_fetch.sh"),
         "log_aggregate?name=news_decisions&fields=decision&count_true=veto"],
        capture_output=True, text=True, check=False)
    return json.loads(res.stdout) if res.returncode == 0 else None


def summarize_veto(agg: Optional[dict]) -> Dict[str, Any]:
    if not agg or agg.get("read_state") != "complete":
        return {"veto_rows": None, "first_day": None, "last_day": None, "days_with_veto": None}
    days = agg.get("days", {})
    v = {d: x.get("true_counts", {}).get("veto", 0) for d, x in days.items()}
    return {"veto_rows": sum(v.values()), "first_day": agg.get("first_day"),
            "last_day": agg.get("last_day"), "days_with_veto": sum(1 for c in v.values() if c),
            "log_rows": agg.get("scanned_lines")}


def _read_jsonl(p: Path) -> List[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input-dir", help="dir with order_packages.jsonl, trades.jsonl, "
                                        "[veto_aggregate.json]; omit to pull live via diag_fetch.sh")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pulled-at", default=None)
    a = ap.parse_args(argv)

    if a.input_dir:
        d = Path(a.input_dir)
        packages, trades = _read_jsonl(d / "order_packages.jsonl"), _read_jsonl(d / "trades.jsonl")
        vp = d / "veto_aggregate.json"
        agg = json.loads(vp.read_text()) if vp.exists() else None
    else:
        packages, trades, agg = _fetch_pages("order_packages"), _fetch_pages("trades"), _fetch_veto_aggregate()

    built = build_taken_rows(packages, trades)
    arm_a = grade_arm_a(built["rows"])
    vs = summarize_veto(agg)
    arm_b = grade_arm_b(vs["veto_rows"], vs["first_day"], vs["last_day"], vs["days_with_veto"])
    rec = {
        "unit": "RQ-20261009-902", "rule": RULE_ID,
        "read_state": "complete",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "population": ("closed, non-backtest trades in trade_journal.db whose order package carries a "
                       "meta.news stamp and cost_source in {broker, estimate}; one row per package; "
                       "paper + real_money pooled (split reported)"),
        "inputs": {"order_packages": len(packages), "trades": len(trades),
                   "packages_with_news_stamp": built["packages_with_news_stamp"],
                   "dropped_after_join": built["dropped"], "pulled_at": a.pulled_at},
        "cost_stack": "journal fee_taker + fee_maker + funding_paid (null funding = 0) + modelled "
                      "round-trip slippage (execution_costs.slippage_bps_roundtrip_for)",
        "arm_a": arm_a, "arm_b": arm_b, "veto_log": vs,
        "g1": g1_read(arm_a, arm_b),
        "not_claimed": "no Brier/ECE: no base probability is logged; Arm A is a rank/sign test",
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: rec[k] for k in ("g1",)} | {"arm_a": arm_a["verdict"], "n": arm_a["n_distinct_taken_packages"],
                                                      "arm_b": arm_b["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
