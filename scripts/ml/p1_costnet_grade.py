#!/usr/bin/env python3
"""Grade a setup meta-label head against the pre-registered P1 rule.

Rule: docs/plans/ml-live-promotion-plan-2026-10-29.md section 3 P1 (registered
before any run; graded here unchanged). Inputs are the trained model state, the
dataset's data.jsonl and (for rule (e)) the journal the eval rows came from.

    PASS  iff (a) cost_gate passed AND (b) trade-bootstrap 95% LB of
          value_r - matched_random_r > 0 (10,000 resamples, seed 42) AND
          (c) take_rate in [0.05, 0.60] AND (d) value > 0 in >= 2 of 3 symbols
          (a symbol with < 30 eval rows is not counted) AND (e) <= 20% of live
          closed trades excluded for lacking an initial-risk basis.
    FAIL  if (a) or (b) fails with >= 200 eval rows.
    INDETERMINATE if eval rows < 200, (d) cannot be computed, > 20% excluded,
          or unit_fallback share of the pre-exclusion eval book > 10%.

"""
# wiring: manual-only — the ML-P1-COSTNET-REBUILD lane runs it on the trainer after `ml train`.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _bootstrap_lb(pairs: list[tuple[bool, float]], n_boot: int = 10_000, seed: int = 42,
                  lb_pct: float = 2.5) -> dict:
    import numpy as np

    taken = np.array([t for t, _ in pairs], dtype=float)
    r = np.array([x for _, x in pairs], dtype=float)
    n = len(r)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        tk, rr = taken[idx], r[idx]
        value = float((tk * rr).sum() / n)
        matched = float(tk.mean() * rr.mean())
        diffs[i] = value - matched
    return {
        "n_resamples": n_boot, "seed": seed,
        "point": float((taken * r).sum() / n - taken.mean() * r.mean()),
        "lb95": float(np.percentile(diffs, lb_pct)), "ub95": float(np.percentile(diffs, 100.0 - lb_pct)),
        "lb_pct": lb_pct,
    }


def _recompute_cost_gate(rows_pairs: list[tuple[dict, tuple[bool, float]]]) -> dict:
    """(a) on an arbitrary eval population, exactly as ml/promotion/cost_gate.py:
    value_r = sum(taken R) / n must exceed max(take_all, take_none 0, matched_random),
    and every row must carry a net cost basis (``realized`` for live / paper rows)."""
    n = len(rows_pairs)
    if not n:
        return {"passed": False, "reason": "no_scored_eval_rows", "value_r": None,
                "take_all_r": None, "matched_random_r": None, "eval_cost_bases": {}}
    bases: dict = {}
    for r, _ in rows_pairs:
        b = r.get("label_cost_basis")
        bases[b] = bases.get(b, 0) + 1
    taken = [x for _, (t, x) in rows_pairs if t]
    value = sum(taken) / n
    take_all = sum(x for _, (_, x) in rows_pairs) / n
    matched = (len(taken) / n) * take_all
    out = {"value_r": value, "take_all_r": take_all, "matched_random_r": matched,
           "take_none_r": 0.0, "n_taken": len(taken), "eval_cost_bases": bases,
           "recomputed": True}
    gross = {b: c for b, c in bases.items() if b not in ("realized", "net", "harness")}
    if gross:
        out.update(passed=False, reason=f"eval_not_cost_net: {gross}")
        return out
    comps = {"take_all": take_all, "take_none": 0.0, "matched_random": matched}
    best_name, best = max(comps.items(), key=lambda kv: kv[1])
    out["passed"] = value > best
    out["reason"] = (f"beats all comparators: value {value:+.4f}R/opp > best {best_name} {best:+.4f}R/opp"
                     if out["passed"] else
                     f"does_not_beat_{best_name}: value {value:+.4f}R/opp <= {best:+.4f}R/opp")
    out["reason"] += f" (n={n}, taken={len(taken)})"
    return out


def _load_strategies(path: str | None) -> set[str] | None:
    """A frozen strategy list: JSON/YAML list, or one name per line (# comments)."""
    if not path:
        return None
    text = Path(path).read_text()
    try:
        import yaml

        data = yaml.safe_load(text)
        if isinstance(data, list):
            return {str(x).strip() for x in data if str(x).strip()}
    except Exception:  # noqa: BLE001 - fall through to one-per-line
        pass
    return {ln.split("#", 1)[0].strip() for ln in text.splitlines() if ln.split("#", 1)[0].strip()}


def _journal_basis_counts(journal: Path, symbols: list[str], *, paper: bool = False,
                          strategies: set[str] | None = None) -> dict:
    from ml.datasets.families.setup_candidates import _live_realized_r, _load_live_trades

    out: dict = {}
    for sym in symbols:
        c = {"initial_risk": 0, "initial_risk_signal": 0, "stop_distance": 0, "unit_fallback": 0}
        for tr in _load_live_trades(journal, sym, include_paper=paper):
            if bool(tr.get("is_paper")) != paper:
                continue
            if strategies is not None and tr.get("strategy") not in strategies:
                continue
            won = 1 if (tr["pnl"] is not None and float(tr["pnl"]) > 0) else 0
            c[_live_realized_r(tr, won)[1]] += 1
        out[sym] = c
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--model-state", required=True)
    ap.add_argument("--dataset", required=True, help="data.jsonl of the dataset the model was evaluated on")
    ap.add_argument("--cost-gate", required=True, help="cost_gate.json from the experiment dir")
    ap.add_argument("--journal", required=True)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--out", required=True)
    ap.add_argument("--eval-source", choices=("live", "live_paper"), default="live",
                    help="live = real-money rows (is_live_trade); live_paper = the paper-book cohort")
    ap.add_argument("--strategies-file", default=None,
                    help="frozen strategy list; eval rows whose `strategy` is not in it are excluded and counted")
    ap.add_argument("--lb-pct", type=float, default=2.5,
                    help="lower percentile of the (b) bootstrap (2.5 = the registered 95%%; deflate for re-reads)")
    a = ap.parse_args(argv)

    import yaml
    from ml.experiments.runner import score_decisions
    from ml.manifest import TrainingManifest  # noqa: F401  (import check only)
    from ml.promotion import cost_gate as cg

    man = yaml.safe_load(Path(a.manifest).read_text())

    class _M:  # minimal duck for cg.decision_threshold / value_column_for
        evaluator_config = man.get("evaluator_config") or {}
        trainer_config = man.get("trainer_config") or {}

        class dataset:  # noqa: N801
            family = (man.get("dataset") or {}).get("family")

    vcol = cg.value_column_for(_M)
    thr = cg.decision_threshold(_M, vcol)
    state = json.loads(Path(a.model_state).read_text())
    gate = json.loads(Path(a.cost_gate).read_text())

    rows = [json.loads(ln) for ln in open(a.dataset) if ln.strip()]
    if a.eval_source == "live":
        ev = [r for r in rows if r.get("is_live_trade")]
    else:
        ev = [r for r in rows if r.get("event_source") == "live_paper"]
    strategies = _load_strategies(a.strategies_file)
    filt = None
    if strategies is not None:
        no_strategy = sum(1 for r in ev if not r.get("strategy"))
        off_list = sum(1 for r in ev if r.get("strategy") and r["strategy"] not in strategies)
        filt = {"strategies_n": len(strategies), "before": len(ev),
                "excluded_no_strategy": no_strategy, "excluded_off_list": off_list}
        ev = [r for r in ev if r.get("strategy") in strategies]
        filt["after"] = len(ev)
    srcs: dict = {}
    for r in ev:
        srcs[r.get("r_multiple_source")] = srcs.get(r.get("r_multiple_source"), 0) + 1
    scored = []
    rows_pairs = []
    for r in ev:
        p = score_decisions(state, [r], vcol, thr)
        if p:
            scored.append((r.get("symbol"), p[0]))
            rows_pairs.append((r, p[0]))
    pairs = [p for _, p in scored]
    n = len(pairs)
    boot = _bootstrap_lb(pairs, lb_pct=a.lb_pct) if n >= 3 else None
    # (a): the experiment's cost_gate.json was computed on its own eval split; a
    # different population (paper book, a strategy filter) is re-graded here.
    if a.eval_source != "live" or strategies is not None:
        gate = _recompute_cost_gate(rows_pairs)
        gate["candidate_value_r"] = gate["value_r"]

    per_sym = {}
    for s in sorted({s for s, _ in scored}):
        sp = [p for x, p in scored if x == s]
        val = sum(r for t, r in sp if t) / len(sp)
        per_sym[s] = {"n": len(sp), "n_taken": sum(1 for t, _ in sp if t), "value_r": val,
                      "take_all_r": sum(r for _, r in sp) / len(sp)}
    counted = {s: v for s, v in per_sym.items() if v["n"] >= 30}
    pos = [s for s, v in counted.items() if v["value_r"] > 0]

    basis = _journal_basis_counts(Path(a.journal), a.symbols.split(","),
                                  paper=a.eval_source == "live_paper", strategies=strategies)
    tot = {k: sum(b[k] for b in basis.values())
           for k in ("initial_risk", "initial_risk_signal", "stop_distance", "unit_fallback")}
    pop = sum(tot.values())
    excl = (tot["stop_distance"] + tot["unit_fallback"]) / pop if pop else None
    fallback_share = tot["unit_fallback"] / pop if pop else None

    take_rate = (sum(1 for t, _ in pairs if t) / n) if n else None
    a_ok = bool(gate.get("passed"))
    b_ok = bool(boot and boot["lb95"] > 0)
    c_ok = take_rate is not None and 0.05 <= take_rate <= 0.60
    d_ok = len(counted) >= 2 and len(pos) >= 2
    d_computable = len(counted) >= 2
    e_ok = excl is not None and excl <= 0.20

    if n < 200 or not d_computable or not e_ok or (fallback_share or 0) > 0.10:
        verdict = "INDETERMINATE"
    elif not a_ok or not b_ok:
        verdict = "FAIL"
    elif c_ok and d_ok:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    rec = {
        "rule": "docs/plans/ml-live-promotion-plan-2026-10-29.md section 3 P1",
        "verdict": verdict,
        "population": (
            f"{n} real closed trades (is_live_trade) in the live_holdout book of the dataset; symbols {sorted(per_sym)}"
            if a.eval_source == "live" else
            f"{n} PAPER-book closed trades (event_source live_paper) of the dataset; symbols {sorted(per_sym)}"
        ) + (f"; strategy filter {a.strategies_file} ({len(strategies)} names)" if strategies is not None else ""),
        "eval_source": a.eval_source, "strategy_filter": filt,
        "n_eval": n, "take_rate": take_rate, "threshold": thr,
        "a_cost_gate": {"passed": a_ok, "reason": gate.get("reason"), "value_r": gate.get("candidate_value_r"),
                        "take_all_r": gate.get("take_all_r"), "matched_random_r": gate.get("matched_random_r"),
                        "eval_cost_bases": gate.get("eval_cost_bases")},
        "b_bootstrap": boot, "b_ok": b_ok, "c_ok": c_ok,
        "d_per_symbol": per_sym, "d_counted_symbols": sorted(counted), "d_positive_symbols": pos, "d_ok": d_ok,
        "e_journal_basis_counts": basis, "e_totals": tot, "e_excluded_share": excl,
        "unit_fallback_share_pre_exclusion": fallback_share,
        "eval_r_multiple_source": srcs,
    }
    Path(a.out).write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: rec[k] for k in ("verdict", "n_eval", "take_rate", "b_ok", "c_ok", "d_ok", "e_excluded_share")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
