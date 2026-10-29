#!/usr/bin/env python3
# wiring: scripts/research/exit_lever_ablation.py --grade risk_adjusted (import); research/queue/RQ-20261029-1f39-01 via research-script-run.yml (run-legs); manual re-grade of landed records (regrade-records)
"""RULE-AM-RISK-ADJUSTED-V1: the risk-adjusted graduation rule for an active-management action class.

WHY (operator decision 2026-10-29, popup, verbatim on checklist row AM-RISK-ADJUSTED-RULE): *"Small R cost for
big risk cut (Recommended)"*, and *"if we've gotten to a place where we can still find ourselves getting reward
while zeroing out the risk of the trade, then that seems to me like it's a better trading decision overall than
to keep on time and time again just giving back all of the gains."* Doctrine:
docs/ARCHITECTURE-CANONICAL.md § "Active management" clause 4 (the rule is stated there once; this module is its
mechanical form and adds nothing to it).

THE RULE (parameters are explicit and travel in every verdict; V1's values are the operator-shown defaults):

  Population: the whole BOOK of an arm -- every trade it took, so a stop that frees risk budget and lets the arm
  take extra trades is counted. Baseline A = hold (the declared exit). Candidate C = the action class.

  R1 cost       r_cost = (net_r(A) - net_r(C)) / n(A)  <=  max_r_cost_per_trade (0.05 R).
                A negative r_cost is a gain. Per BASELINE trade, so extra trades C takes count for C. The cost is
                NET P&L given up, never a ratio (operator 2026-10-29: the objective is absolute net P&L, $ and %
                return per account; R is the per-trade unit). With ``risk_pct_by_account`` (each account's
                accounts.yaml ``risk.risk_pct``) the verdict also reports the same cost and both books' net return
                as % of account equity per account (uncompounded: R x risk_pct). Grading stays in R.
  R2 risk cut   dd_cut   = (maxDD(A) - maxDD(C)) / maxDD(A)        >= min_dd_cut_pct (0.15), OR
                cvar_cut = (CVaR5(C) - CVaR5(A)) / |CVaR5(A)|      >= min_cvar5_cut_pct (0.15).
                maxDD is the peak-to-trough of cumulative net R in exit-time order (same-time outcomes summed
                first). CVaR5 is the mean of the worst 5% (ceil) of the book's calendar-WEEK net R (ISO week of
                exit; weeks with no exit are not invented). Per-trade CVaR5 is reported, never graded.
  R3 folds      in >= fold_majority of the calendar folds (trades binned by entry time, the same edges for every
                arm), the fold holds: fold r_cost <= max_r_cost_per_trade AND the fold's cut on a metric that
                passed R2 is >= fold_min_risk_cut_pct (0.0: risk not made worse in that fold).
  R4 control    C beats a declared matched random-intervention control K when net_r(C) >= net_r(K) AND C's cut on
                an R2-passing metric >= K's cut on it, at least one strictly. C must beat >= min_control_beat_frac
                (0.95) of the declared controls: with ONE control it must beat it; with N seeded random draws it
                must beat 95% of them. No declared control -> R4 cannot be read.
  Floors        n(A) >= n_floor (39, the repo's standing floor); C must differ from A (the lever fired).

  Verdict: INDETERMINATE when a floor fails or the input is missing; FAIL when R1, R2 or R3 is read and fails (a
  failed necessary clause decides, whatever R4 would say); INDETERMINATE (`no_random_control`) when R1-R3 pass and
  no control is declared; FAIL when a declared control is not beaten; PASS only when R1-R4 all hold.

  A PASS is a proposal input for a Tier-3 / mandate change to that class's status, never an apply (§ Active
  management "What this does NOT change"). Each class is graded on its own test, net of the full cost stack the
  harness charged, under a rule registered before the run. Nothing here edits config or a mandate.

MODES
  grade          --arms-dir DIR [--arms-dir DIR ...] (pooled when several: same arm labels in each, trades merged)
                 reads <DIR>/<label>__trades.jsonl (exit_lever_ablation / harness emit: entry_time, exit_time,
                 net_r). Writes a verdict JSON.
  run-legs       runs exit_lever_ablation.py --grade risk_adjusted per leg (each leg's own Stage-0 harness via
                 regime_debt_matrix.build_harness_cmd), then grades the POOLED book over the per-leg arms dirs.
  regrade-records  re-reads (never re-runs) the landed exit/AM records named in REGRADE_RECORDS and writes what
                 each class would read under this rule. A re-grade is a reading, not a graduation.
  --self-test    planted positive and negative controls.

Tier-1 research tooling: reads committed records, writes only --out. No live path, no config write.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]

RULE_ID = "RULE-AM-RISK-ADJUSTED-V1"
RULE_V1: dict[str, Any] = {
    "id": RULE_ID,
    "registered_at": "2026-10-29",
    "doctrine": "docs/ARCHITECTURE-CANONICAL.md § Active management, clause 4",
    "max_r_cost_per_trade": 0.05,
    "min_dd_cut_pct": 0.15,
    "min_cvar5_cut_pct": 0.15,
    "cvar_tail": 0.05,
    "cvar_basis": "book_iso_week_of_exit",
    "folds": 6,
    "fold_majority": 4,
    "fold_min_risk_cut_pct": 0.0,
    "n_floor": 39,
    "random_control": "required",
    "min_control_beat_frac": 0.95,
    # operator 2026-10-29 ~07:20Z: the measurement of record is a book-level $ simulation per account at its real size
    # (production sizer + caps + daily_dd_switch). Until that simulator exists (row BOOK-SIM-REAL-SIZER) a grade over
    # per-trade-R books is a SCREEN: it ranks candidates and never graduates a class.
    "measurement_of_record": "book_usd_sim_per_account (row BOOK-SIM-REAL-SIZER)",
}


# ── book metrics (pure) ─────────────────────────────────────────────────────
def _dt(s: Any) -> datetime:
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def max_drawdown(trades: list[dict[str, Any]]) -> float:
    """Peak-to-trough of cumulative net R, exit-time order, same-time outcomes summed first (>= 0)."""
    by_t: dict[datetime, float] = {}
    for t in trades:
        k = _dt(t["exit_time"])
        by_t[k] = by_t.get(k, 0.0) + float(t["net_r"])
    eq = peak = dd = 0.0
    for k in sorted(by_t):
        eq += by_t[k]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return round(dd, 6)


def _tail_mean(xs: list[float], tail: float) -> float | None:
    if not xs:
        return None
    k = max(1, math.ceil(tail * len(xs)))
    return round(sum(sorted(xs)[:k]) / k, 6)


def weekly_book(trades: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        y, w, _ = _dt(t["exit_time"]).isocalendar()
        key = f"{y}-W{w:02d}"
        out[key] = out.get(key, 0.0) + float(t["net_r"])
    return out


def book_metrics(trades: list[dict[str, Any]], tail: float = 0.05) -> dict[str, Any]:
    rs = [float(t["net_r"]) for t in trades]
    return {"n": len(rs), "net_r": round(sum(rs), 6), "max_drawdown_r": max_drawdown(trades) if trades else 0.0,
            "cvar5_week_r": _tail_mean(list(weekly_book(trades).values()), tail),
            "cvar5_trade_r": _tail_mean(rs, tail), "weeks": len(weekly_book(trades))}


def _cut_dd(a: dict[str, Any], c: dict[str, Any]) -> float | None:
    return None if a["max_drawdown_r"] <= 0 else round((a["max_drawdown_r"] - c["max_drawdown_r"]) / a["max_drawdown_r"], 6)


def _cut_cvar(a: dict[str, Any], c: dict[str, Any]) -> float | None:
    if a["cvar5_week_r"] is None or c["cvar5_week_r"] is None or a["cvar5_week_r"] >= 0:
        return None
    return round((c["cvar5_week_r"] - a["cvar5_week_r"]) / abs(a["cvar5_week_r"]), 6)


def calendar_edges(trades: list[dict[str, Any]], folds: int) -> list[datetime]:
    ts = [_dt(t["entry_time"]) for t in trades]
    lo, hi = min(ts), max(ts)
    step = (hi - lo) / folds
    return [lo + step * i for i in range(folds)] + [hi]


def _in_fold(t: dict[str, Any], edges: list[datetime], i: int) -> bool:
    e = _dt(t["entry_time"])
    last = i == len(edges) - 2
    return edges[i] <= e < edges[i + 1] or (last and e == edges[i + 1])


def pnl_view(a_book: dict[str, Any], c_book: dict[str, Any], r_cost: float,
             risk_pct_by_account: dict[str, float] | None) -> dict[str, Any] | None:
    """The cost leg and both books in % return per account: R x the account's risk fraction per trade (uncompounded,
    so a comparison of the two arms on one account, not a forecast of its equity curve)."""
    if not risk_pct_by_account:
        return None
    return {acct: {"risk_pct_per_trade": rp, "cost_pct_return_per_trade": round(r_cost * rp * 100, 6),
                   "baseline_net_return_pct": round(a_book["net_r"] * rp * 100, 4),
                   "candidate_net_return_pct": round(c_book["net_r"] * rp * 100, 4),
                   "baseline_max_dd_pct": round(a_book["max_drawdown_r"] * rp * 100, 4),
                   "candidate_max_dd_pct": round(c_book["max_drawdown_r"] * rp * 100, 4)}
            for acct, rp in risk_pct_by_account.items()}


def risk_pcts(accounts: list[str]) -> dict[str, float]:
    """accounts.yaml ``risk.risk_pct`` per account, read now (an account without one is left out)."""
    import yaml
    doc = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text(encoding="utf-8"))
    accs = doc.get("accounts", doc)
    return {a: float(accs[a]["risk"]["risk_pct"]) for a in accounts
            if isinstance((accs.get(a) or {}).get("risk"), dict) and accs[a]["risk"].get("risk_pct") is not None}


# ── the grade (pure) ────────────────────────────────────────────────────────
def grade_risk_adjusted(books: dict[str, list[dict[str, Any]]], *, baseline: str, candidates: list[str],
                        controls: dict[str, list[str]] | None = None, params: dict[str, Any] | None = None,
                        edges: list[datetime] | None = None,
                        risk_pct_by_account: dict[str, float] | None = None,
                        basis: str = "per_trade_r_screen") -> dict[str, Any]:
    """``basis`` names what the books hold: ``per_trade_r_screen`` (harness R books, the default; never a graduation)
    or ``book_usd_sim`` (a per-account $ simulation at real size, whose ``net_r`` field then carries net $)."""
    p = {**RULE_V1, **(params or {})}
    tail = float(p["cvar_tail"])
    a_tr = books[baseline]
    A = book_metrics(a_tr, tail)
    out: dict[str, Any] = {"rule": {k: p[k] for k in RULE_V1}, "baseline": baseline, "baseline_book": A,
                           "measurement_basis": basis, "graduation_eligible": basis == "book_usd_sim",
                           "candidates": {}}
    if A["n"] < int(p["n_floor"]):
        return {"verdict": "indeterminate", "label": "underpowered", **out,
                "why": f"baseline n={A['n']} < n_floor {p['n_floor']}"}
    edges = edges or calendar_edges(a_tr, int(p["folds"]))
    nf = len(edges) - 1
    best, best_label = None, None
    order = {"pass": 0, "indeterminate": 1, "fail": 2}
    for cl in candidates:
        c_tr = books[cl]
        C = book_metrics(c_tr, tail)
        row: dict[str, Any] = {"book": C}
        fired = not (C["n"] == A["n"] and abs(C["net_r"] - A["net_r"]) < 1e-9
                     and abs(C["max_drawdown_r"] - A["max_drawdown_r"]) < 1e-9)
        r_cost = round((A["net_r"] - C["net_r"]) / A["n"], 6)
        dd_cut, cv_cut = _cut_dd(A, C), _cut_cvar(A, C)
        r1 = r_cost <= float(p["max_r_cost_per_trade"])
        passing = [m for m, v, bar in (("dd", dd_cut, p["min_dd_cut_pct"]), ("cvar5", cv_cut, p["min_cvar5_cut_pct"]))
                   if v is not None and v >= float(bar)]
        r2 = bool(passing)
        folds = []
        for i in range(nf):
            fa = [t for t in a_tr if _in_fold(t, edges, i)]
            fc = [t for t in c_tr if _in_fold(t, edges, i)]
            FA, FC = book_metrics(fa, tail), book_metrics(fc, tail)
            f_cost = round((FA["net_r"] - FC["net_r"]) / FA["n"], 6) if FA["n"] else None
            cuts = {"dd": _cut_dd(FA, FC) if FA["n"] else None, "cvar5": _cut_cvar(FA, FC) if FA["n"] else None}
            # a fold with zero baseline drawdown cannot be cut; "not made worse" is then read as FC's dd == 0
            if FA["n"] and FA["max_drawdown_r"] <= 0:
                cuts["dd"] = 0.0 if FC["max_drawdown_r"] <= 0 else -1.0
            ok = (f_cost is not None and f_cost <= float(p["max_r_cost_per_trade"])
                  and any(cuts[m] is not None and cuts[m] >= float(p["fold_min_risk_cut_pct"]) for m in passing))
            folds.append({"fold": i + 1, "n_baseline": FA["n"], "n_candidate": FC["n"], "r_cost": f_cost,
                          "cuts": cuts, "holds": ok})
        held = sum(1 for f in folds if f["holds"])
        r3 = held >= int(p["fold_majority"])
        ctl_rows = {}
        for k in (controls or {}).get(cl, []):
            K = book_metrics(books[k], tail)
            k_cuts = {"dd": _cut_dd(A, K), "cvar5": _cut_cvar(A, K)}
            c_cuts = {"dd": dd_cut, "cvar5": cv_cut}
            beats = False
            for m in passing:
                kc = k_cuts[m] if k_cuts[m] is not None else float("-inf")
                if C["net_r"] >= K["net_r"] and c_cuts[m] >= kc and (C["net_r"] > K["net_r"] or c_cuts[m] > kc):
                    beats = True
            ctl_rows[k] = {"book": K, "cuts": k_cuts, "beats": beats}
        row.update({"lever_fired": fired, "r_cost_per_trade": r_cost, "dd_cut_pct": dd_cut, "cvar5_cut_pct": cv_cut,
                    "pnl_by_account": pnl_view(A, C, r_cost, risk_pct_by_account),
                    "risk_metrics_passing": passing, "folds": folds, "folds_held": held, "n_folds": nf,
                    "clauses": {"R1_cost": r1, "R2_risk_cut": r2, "R3_folds": r3,
                                "R4_control": ((sum(v["beats"] for v in ctl_rows.values()) / len(ctl_rows)
                                                >= float(p["min_control_beat_frac"])) if ctl_rows else None)},
                    "controls": ctl_rows})
        if not fired:
            v, lab = "indeterminate", "lever_never_fired"
        elif not (r1 and r2 and r3):
            v, lab = "fail", "fails_" + "_".join(n for n, ok in (("R1", r1), ("R2", r2), ("R3", r3)) if not ok)
        elif not ctl_rows:
            v, lab = "indeterminate", "no_random_control"
        elif not row["clauses"]["R4_control"]:
            v, lab = "fail", "fails_R4"
        else:
            v, lab = "pass", "risk_adjusted_pass"
        row.update({"verdict": v, "label": lab})
        out["candidates"][cl] = row
        if best is None or order[v] < order[best]:
            best, best_label = v, cl
    if best is None:
        return {"verdict": "indeterminate", "label": "no_candidates", **out, "why": "no candidate arm declared"}
    passes = [c for c, r in out["candidates"].items() if r["verdict"] == "pass"]
    lab = {"pass": "class_passes", "fail": "no_candidate_passes", "indeterminate": "unresolved"}[best]
    why = {"pass": f"{passes} clear R1-R4 under {RULE_ID}: a Tier-3 PROPOSAL input for the class, never an apply",
           "fail": "every candidate fails a necessary clause (R1 cost, R2 risk cut, R3 folds or R4 control)",
           "indeterminate": f"best candidate {best_label} reads {out['candidates'][best_label]['label']}"}[best]
    return {"verdict": best, "label": lab, "passing": passes, **out, "why": why}


# ── IO ──────────────────────────────────────────────────────────────────────
def load_trades(path: Path) -> list[dict[str, Any]]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("net_r") is not None and r.get("exit_time") and r.get("entry_time"):
                rows.append(r)
    return rows


def books_from_dirs(dirs: Iterable[Path], labels: list[str]) -> dict[str, list[dict[str, Any]]]:
    books: dict[str, list[dict[str, Any]]] = {lab: [] for lab in labels}
    for d in dirs:
        for lab in labels:
            f = Path(d) / f"{lab}__trades.jsonl"
            if not f.exists():
                raise FileNotFoundError(f"{f} missing: every pooled dir must carry every arm")
            books[lab].extend(load_trades(f))
    return books


def roster_legs(accounts: list[str]) -> list[str]:
    """Union of the `strategies:` rosters of these accounts, read from config/accounts.yaml now."""
    import yaml
    doc = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text(encoding="utf-8"))
    accs = doc.get("accounts", doc)
    out: list[str] = []
    for acct in accounts:
        if acct not in accs:
            raise KeyError(f"account {acct!r} not in config/accounts.yaml")
        for s in accs[acct].get("strategies") or []:
            name = s if isinstance(s, str) else (s.get("name") or s.get("id"))
            if name and name not in out:
                out.append(name)
    return out


# ── re-grade of landed records (reading, not graduation) ──────────────────────
# unit -> (arms dir, baseline, candidates, {candidate: [random controls]}). Controls are only the arms the unit
# itself registered as MATCHED RANDOM draws; an "every trade" (unconditional) arm is not a random control.
REGRADE_RECORDS: dict[str, dict[str, Any]] = {
    "RQ-20261022-b7e1-08": {"dir": "comms/research/RQ-20261022-b7e1-08/40018602847/arms", "baseline": "A",
                            "candidates": ["BG25", "BG33", "BG50", "UB25", "UB33", "UB50"], "controls": {},
                            "class": "partial close (bank 25/33/50% at +2R; gated BG and unconditional UB)"},
    "RQ-20261024-f08c-01": {"dir": "comms/research/RQ-20261024-f08c-01/40117905169/arms", "baseline": "A",
                            "candidates": ["L25", "L30", "L30W"], "controls": {},
                            "class": "SL tighten (R-armed tight trail)"},
    "RQ-20261024-9a7e-01": {"dir": "comms/research/RQ-20261024-9a7e-01/40199881910/arms", "baseline": "A",
                            "candidates": ["MT", "UT"], "controls": {"MT": ["RT"]},
                            "class": "SL tighten (giveback-predictor-gated tight trail; RT = matched-rate random)"},
    "RQ-20261026-ed1c-17": {"dir": "comms/research/RQ-20261026-ed1c-17/40516369998/arms", "baseline": "A",
                            "candidates": ["BE075", "BE10", "BE15"], "controls": {},
                            "class": "SL to break-even once peak >= 0.75/1.0/1.5R (trend_donchian_eth)"},
}


def _regrade_desk_pairs(path: Path, folds: int) -> dict[str, Any]:
    """#20967 DESK-LIFECYCLE-S0: per pair C_h (Claude entry, hold) vs C_m (Claude-managed); R_* on random entries.
    The record carries the ISO week, not a timestamp: every outcome of a week is placed at that week's Monday
    (exit and entry), so maxDD runs on the weekly book -- an ordering approximation, stated in the output."""
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: dict[str, Any] = {"record": str(path), "pr": 20967, "class": "Claude whole-trade management (all actions)",
                           "ordering": "ISO-week granularity (no timestamps in pairs.jsonl)", "by_entry_source": {}}
    for src in ("C", "R"):
        keep = [r for r in rows if r.get(f"{src}_h") is not None and r.get(f"{src}_m") is not None]

        def tr(r: dict[str, Any], col: str) -> dict[str, Any]:
            y, w = r["week"].split("-W")
            t = datetime.fromisocalendar(int(y), int(w), 1).replace(tzinfo=timezone.utc).isoformat()
            return {"entry_time": t, "exit_time": t, "net_r": float(r[col])}
        books = {"hold": [tr(r, f"{src}_h") for r in keep], "managed": [tr(r, f"{src}_m") for r in keep]}
        # 4 folds, 3 must hold: the record's own fold convention (RULE-RQ20261028-D1F5-02 "< 3 folds positive")
        g = grade_risk_adjusted(books, baseline="hold", candidates=["managed"],
                                params={"folds": folds, "fold_majority": folds - 1})
        out["by_entry_source"]["claude_entry" if src == "C" else "random_entry"] = {
            "n_pairs": len(keep), "verdict": g["verdict"], "label": g["candidates"].get("managed", {}).get("label"),
            "grade": g}
    vs = {v["verdict"] for v in out["by_entry_source"].values()}
    out["verdict"] = "fail" if vs == {"fail"} else ("pass" if vs == {"pass"} else "indeterminate")
    out["label"] = ",".join(f"{k}:{v['label']}" for k, v in out["by_entry_source"].items())
    return out


def _regrade_tighten_optimize(path: Path) -> dict[str, Any]:
    """#21003 LTR-TIGHTEN-OPTIMIZE: per-rule aggregates only (n, net_r_rule/hold per trade, maxdd_rule/hold).
    R1 and the maxDD half of R2 are readable; CVaR5, R3 folds and R4 are not in the record."""
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = {}
    for rule, r in (d.get("table") or {}).items():
        if not isinstance(r, dict) or r.get("net_r_hold") is None or r.get("maxdd_hold") in (None, 0):
            continue
        r_cost = round(float(r["net_r_hold"]) - float(r["net_r_rule"]), 6)
        dd_cut = round((float(r["maxdd_hold"]) - float(r["maxdd_rule"])) / float(r["maxdd_hold"]), 6)
        r1 = r_cost <= RULE_V1["max_r_cost_per_trade"]
        dd_ok = dd_cut >= RULE_V1["min_dd_cut_pct"]
        v = "fail" if not r1 else ("indeterminate")
        lab = "fails_R1" if not r1 else ("R1_R2dd_pass_rest_unreadable" if dd_ok else "R1_pass_R2dd_short_cvar_unreadable")
        rows[rule] = {"n": r.get("n"), "r_cost_per_trade": r_cost, "dd_cut_pct": dd_cut, "verdict": v, "label": lab}
    vs = {x["verdict"] for x in rows.values()}
    return {"verdict": "fail" if vs == {"fail"} else "indeterminate",
            "label": "aggregates_only_R3_R4_cvar_unreadable", "record": str(path), "pr": 21003, "split": d.get("split"), "population": d.get("population"),
            "class": "SL tighten (61 registered rules)", "readable_clauses": ["R1", "R2 maxDD half"],
            "unreadable": ["R2 CVaR5 half", "R3 folds", "R4 random control"], "rules": rows,
            "summary": {"n_rules": len(rows), "fail_R1": sum(1 for x in rows.values() if x["verdict"] == "fail"),
                        "r1_and_dd_pass": sorted(k for k, x in rows.items() if x["label"] == "R1_R2dd_pass_rest_unreadable")}}


def regrade_records() -> dict[str, Any]:
    res: dict[str, Any] = {"rule": RULE_V1, "kind": "re-grade (reading, not graduation)", "provenance": "MEASURED",
                           "method": "re-reads the committed per-trade / per-pair / per-rule records; nothing re-run",
                           "records": {}}
    for unit, spec in REGRADE_RECORDS.items():
        d = REPO / spec["dir"]
        books = books_from_dirs([d], [spec["baseline"], *spec["candidates"],
                                      *{k for ks in spec["controls"].values() for k in ks}])
        edges = calendar_edges(books[spec["baseline"]], RULE_V1["folds"])
        g = grade_risk_adjusted(books, baseline=spec["baseline"], candidates=spec["candidates"],
                                controls=spec["controls"], edges=edges)
        res["records"][unit] = {"class": spec["class"], "arms_dir": spec["dir"], "verdict": g["verdict"],
                                "label": g["label"], "per_candidate": {c: {k: r[k] for k in (
                                    "verdict", "label", "r_cost_per_trade", "dd_cut_pct", "cvar5_cut_pct",
                                    "folds_held", "n_folds", "clauses")} for c, r in g["candidates"].items()},
                                "grade": g}
    pairs = REPO / "comms/research/desk_lifecycle/full-c4e/pairs.jsonl"
    if pairs.exists():
        res["records"]["DESK-LIFECYCLE-S0 (#20967)"] = _regrade_desk_pairs(pairs, 4)
    for split in ("test", "fresh"):
        f = REPO / f"comms/research/ltr_tighten_optimize/{split}-allgrid.json"
        if f.exists():
            res["records"][f"LTR-TIGHTEN-OPTIMIZE (#21003) {split}"] = _regrade_tighten_optimize(f)
    res["classes_passing"] = sorted(f"{u}:{c}" for u, r in res["records"].items()
                                    for c, v in (r.get("per_candidate") or {}).items() if v["verdict"] == "pass")
    return res


# ── self-test ───────────────────────────────────────────────────────────────
def _synth(n: int, *, giveback: bool, seed: int = 7) -> list[dict[str, Any]]:
    """A book of n trades over ~3 years; every 4th trade peaks at +2R. giveback=True: those reverse to -1R (hold);
    giveback=False: they exit at 0 (break-even). Everything else identical."""
    import random
    rnd = random.Random(seed)
    out = []
    t0 = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
    for i in range(n):
        e = t0 + i * 2.5 * 86400
        if i % 4 == 0:
            r = -1.05 if giveback else -0.05
        else:
            r = rnd.choice([-1.05, -1.05, 1.9, 2.9])
        out.append({"entry_time": datetime.fromtimestamp(e, timezone.utc).isoformat(),
                    "exit_time": datetime.fromtimestamp(e + 86400, timezone.utc).isoformat(), "net_r": r})
    return out


def _self_test() -> int:
    bad = 0

    def check(label: str, cond: bool) -> None:
        nonlocal bad
        print(("ok   " if cond else "FAIL ") + label)
        bad += 0 if cond else 1
    hold = _synth(400, giveback=True)
    be = _synth(400, giveback=False)
    # positive control: BE removes the giveback losses -> gains R, cuts DD; a random control that does worse
    rnd = [dict(t, net_r=(t["net_r"] - 0.3 if i % 4 == 0 else t["net_r"])) for i, t in enumerate(hold)]
    g = grade_risk_adjusted({"A": hold, "BE": be, "RND": rnd}, baseline="A", candidates=["BE"],
                            controls={"BE": ["RND"]})
    check("positive control passes", g["verdict"] == "pass")
    # same, no control declared -> indeterminate, not pass
    g = grade_risk_adjusted({"A": hold, "BE": be}, baseline="A", candidates=["BE"])
    check("no random control -> indeterminate", g["candidates"]["BE"]["label"] == "no_random_control")
    # negative control: a lever that costs 0.2R/trade and cuts nothing -> fail on R1+R2
    costly = [dict(t, net_r=t["net_r"] - 0.2) for t in hold]
    g = grade_risk_adjusted({"A": hold, "X": costly, "RND": rnd}, baseline="A", candidates=["X"],
                            controls={"X": ["RND"]})
    check("negative control fails", g["verdict"] == "fail" and "R1" in g["candidates"]["X"]["label"])
    # cheap but no risk cut -> fail R2
    g = grade_risk_adjusted({"A": hold, "Y": [dict(t) for t in hold[:-1]] + [dict(hold[-1], net_r=hold[-1]["net_r"] - 1)]},
                            baseline="A", candidates=["Y"])
    check("cheap, no risk cut -> fails R2", g["candidates"]["Y"]["label"].startswith("fails_") and
          "R2" in g["candidates"]["Y"]["label"])
    # identical arm -> lever never fired
    g = grade_risk_adjusted({"A": hold, "Z": [dict(t) for t in hold]}, baseline="A", candidates=["Z"])
    check("identical arm -> lever_never_fired", g["candidates"]["Z"]["label"] == "lever_never_fired")
    # control that beats the candidate -> fail R4
    better = [dict(t, net_r=t["net_r"] + 0.1) for t in be]
    g = grade_risk_adjusted({"A": hold, "BE": be, "K": better}, baseline="A", candidates=["BE"], controls={"BE": ["K"]})
    check("beaten by its random control -> fails_R4", g["candidates"]["BE"]["label"] == "fails_R4")
    # underpowered
    g = grade_risk_adjusted({"A": hold[:20], "BE": be[:20]}, baseline="A", candidates=["BE"])
    check("n < floor -> underpowered", g["label"] == "underpowered")
    # freed risk budget counts: candidate takes EXTRA trades -> r_cost per BASELINE trade includes them
    extra = be + [dict(be[-1], net_r=0.5)]
    g = grade_risk_adjusted({"A": hold, "BE": extra}, baseline="A", candidates=["BE"])
    check("extra trades counted in r_cost", g["candidates"]["BE"]["book"]["n"] == 401)
    # maxDD arithmetic
    check("maxDD arithmetic", max_drawdown([{"exit_time": "2024-01-0%dT00:00:00+00:00" % i, "net_r": r}
                                           for i, r in enumerate([1, -2, -1, 3, -0.5], start=1)]) == 3.0)
    print("self-test", "PASSED" if not bad else f"FAILED ({bad})")
    return 1 if bad else 0


# ── CLI ─────────────────────────────────────────────────────────────────────
def _params_from(a: argparse.Namespace) -> dict[str, Any]:
    p = {}
    for k in ("max_r_cost_per_trade", "min_dd_cut_pct", "min_cvar5_cut_pct", "folds", "fold_majority", "n_floor"):
        v = getattr(a, k, None)
        if v is not None:
            p[k] = v
    return p


def _controls_from(specs: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in specs:
        c, _, k = s.partition("=")
        out.setdefault(c, []).append(k)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("grade", "run-legs"):
        s = sub.add_parser(name)
        s.add_argument("--baseline", required=True)
        s.add_argument("--candidate", action="append", required=True)
        s.add_argument("--random-control", action="append", default=[], metavar="CAND=CTRL")
        s.add_argument("--max-r-cost-per-trade", type=float)
        s.add_argument("--min-dd-cut-pct", type=float)
        s.add_argument("--min-cvar5-cut-pct", type=float)
        s.add_argument("--folds", type=int)
        s.add_argument("--fold-majority", type=int)
        s.add_argument("--n-floor", type=int)
        s.add_argument("--out", required=True)
    sub.choices["grade"].add_argument("--arms-dir", action="append", required=True)
    rl = sub.choices["run-legs"]
    rl.add_argument("--leg", action="append", default=[], help="config/strategies.yaml key (repeat)")
    rl.add_argument("--accounts", default="", help="comma list: ALSO take every leg on these accounts' strategies: "
                    "rosters, re-parsed from config/accounts.yaml at run time (never quoted)")
    rl.add_argument("--arm", action="append", required=True, help="passed through to exit_lever_ablation.py")
    rl.add_argument("--leg-args", action="append", default=[], metavar="LEG=--flag=v;--flag=v",
                    help="extra exit_lever_ablation flags for one leg (e.g. its window or non-crypto source)")
    rl.add_argument("--common", default="", help="';'-separated exit_lever_ablation flags for every leg")
    rg = sub.add_parser("regrade-records")
    rg.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.mode == "regrade-records":
        res = regrade_records()
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
        for u, r in res["records"].items():
            print(u, r.get("verdict"), r.get("label"))
        return 0
    params, controls = _params_from(a), _controls_from(a.random_control)
    labels = [a.baseline, *a.candidate, *{k for ks in controls.values() for k in ks}]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.mode == "run-legs":
        legs = list(dict.fromkeys(a.leg + roster_legs([x for x in a.accounts.split(",") if x])))
        if not legs:
            print("ERROR: no legs (give --leg or --accounts)", file=sys.stderr)
            return 2
        a.leg = legs
        per_leg: dict[str, Any] = {}
        extra = {s.partition("=")[0]: [x for x in s.partition("=")[2].split(";") if x] for s in a.leg_args}
        dirs = []
        for leg in a.leg:
            lo = out / leg
            cmd = [sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--leg", leg]
            for arm in a.arm:
                cmd += ["--arm", arm]
            cmd += [x for x in a.common.split(";") if x] + extra.get(leg, [])
            cmd += ["--grade", "risk_adjusted", "--baseline", a.baseline, "--delta-r", "0", "--out", str(lo)]
            for k, flag in (("folds", "--folds"), ("fold_majority", "--fold-majority"), ("n_floor", "--n-floor")):
                cmd += [flag, str(params.get(k, RULE_V1[k]))]
            for s in a.random_control:
                cmd += ["--vs-control", s]
            print("[run-legs]", " ".join(cmd), flush=True)
            r = subprocess.run(cmd, cwd=str(REPO), check=False)
            per_leg[leg] = {"exit_code": r.returncode, "out": str(lo)}
            if r.returncode == 0:
                per_leg[leg]["verdict"] = json.loads((lo / "summary.json").read_text())["grade"]
                dirs.append(lo / "arms")
        if not dirs:
            (out / "verdict.json").write_text(json.dumps({"verdict": "indeterminate", "label": "producer_failed",
                                                          "per_leg": per_leg}, indent=1) + "\n")
            return 1
        pooled = grade_risk_adjusted(books_from_dirs(dirs, labels), baseline=a.baseline, candidates=a.candidate,
                                     controls=controls, params=params,
                                     risk_pct_by_account=risk_pcts([x for x in a.accounts.split(",") if x]))
        failed = [k for k, v in per_leg.items() if v["exit_code"] != 0]
        if failed:
            pooled = {**pooled, "verdict": "indeterminate", "label": "pooled_incomplete", "legs_failed": failed}
        legs_read = {k: {kk: (v.get("verdict") or {}).get(kk) for kk in ("verdict", "label", "passing")}
                     | {"exit_code": v["exit_code"]} for k, v in per_leg.items()}
        rec = {"decision_rule": {"id": RULE_ID, "registered_before_run": True}, "verdict": pooled["verdict"],
               "read_state": "measured", "n": pooled["baseline_book"]["n"], "pooled": pooled, "per_leg": legs_read,
               "measurement": {"label": pooled["label"], "pooled": pooled, "per_leg": legs_read},
               "population": (f"pooled book of legs {a.leg} (each leg's own Stage-0 harness via exit_lever_ablation), "
                              f"arms {labels}; legs whose producer failed: {failed or 'none'}"),
               "note": f"{pooled['verdict'].upper()} / {pooled['label']}: {pooled.get('why')}"}
        (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"verdict": rec["verdict"], "pooled_label": pooled["label"]}))
        return 0
    g = grade_risk_adjusted(books_from_dirs([Path(d) for d in a.arms_dir], labels), baseline=a.baseline,
                            candidates=a.candidate, controls=controls, params=params)
    (out / "verdict.json").write_text(json.dumps(g, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": g["verdict"], "label": g["label"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
