#!/usr/bin/env python3
# wiring: research/queue/RQ-20261116-089f-01.yaml (run.workflow research-script-run-trainer.yml); row CML-HARNESS; design docs/plans/ml-claude-distillation-DESIGN.md 3.3
# wiring: research/queue/RQ-20261118-089f-04.yaml (`--min-risk-atr 1.0`: the risk_atr<1-excluded sensitivity read, row CJ-LABEL-ALTERNATIVE)
"""CJ-4 blind-source label validation (RQ-20261116-089f-01).

Does the blind post-trade grade (comms/claude_judgments/blind_grades.jsonl, mask-v1) rank-predict realised NET R on the journal-joined closed
trades, and does it beat the strategy's own decision-time confidence on the same trades?

RUN HOST: the TRAINER VM. Net R comes from trade_journal.db (not in the repo); the trainer holds the synced copy at
data/trade_journal.db (MEASURED 2026-11-16: 2.9 GB, written 08:03Z) and its checkout holds comms/claude_judgments/*.jsonl. The unit routes through
research-script-run-trainer.yml. Locally (no journal) the run lands read_state could_not_look / INDETERMINATE, never a fake number.

REGISTERED RULE (copied from the unit, none is a tuning knob; changing any is a different unit):
  population  distinct closed trades with a blind grade, journal net R computable (src.runtime.net_r_label, PACKAGE initial stop), blind row T0
              (info cutoff before the close), pre_cutoff handling = ONE date rule: keep iff decision_ts > 2026-06-30 and pre_cutoff is not true.
  pooling     within (author_kind, model_id, mask_version) -- DECLARED deviation from design 3.3 (prompt_sha is reported as strata only).
  statistic   Spearman rho(grade_score, net R); rho(confidence, net R); paired diff on the trades that have both.
  CI          analytic Fisher z with se 1/sqrt(n-3), AND a 2000-draw leg-week cluster bootstrap (percentile); the PASS/FAIL test uses the WIDER.
  PASS        n >= 150 AND rho > 0 AND wider-CI lower > 0 AND paired-diff lower 95% bound > 0 AND paired-diff CI half-width <= 0.12.
  FAIL        n >= 150 AND (rho <= 0 OR wider-CI upper < 0.05 OR paired-diff point <= 0).        INDETERMINATE otherwise (incl. n < 150).
Secondary, reported and never gating: expected_r as the judgment; per-prompt_sha strata; revealed (T1) revised_grade_score against the mean net R of the
NEXT K_NEXT same-leg graded trades (ordered by decision_ts; declared: the control set is the graded trades, not the whole leg history).

    python3 scripts/research/cj4_blind_validation.py --unit RQ-... --out DIR [--db data/trade_journal.db] [--comms comms]
    python3 scripts/research/cj4_blind_validation.py --self-test

--min-risk-atr X (RQ-20261118-089f-04, row CJ-LABEL-ALTERNATIVE): additionally exclude every trade whose package stop distance is under X ATR,
risk_atr = |order_packages.entry - order_packages.sl| / signal_logic.atr -- the SAME quantity scripts/ops/blind_grade.py puts in the packet's
bracket.risk_atr. A trade whose risk_atr cannot be computed is excluded and counted (risk_atr_unknown). Default None = 089f-01 unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MIN_N = 150
DATE_RULE_AFTER = "2026-06-30"       # keep iff decision_ts is strictly after this date (judge's stated knowledge cutoff, ESTIMATED)
FAIL_UPPER = 0.05
PAIRED_HALF_WIDTH_MAX = 0.12
BOOT_DRAWS = 2000
SEED = 20261116
K_NEXT = 3
Z95 = 1.959963984540054


# ----------------------------------------------------------------------------------------------- statistics
def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan")
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def fisher_ci(rho: float, n: int) -> tuple[float, float]:
    """Analytic 95% CI, se = 1/sqrt(n-3) (the basis the unit's power note registers)."""
    if not np.isfinite(rho) or n <= 3:
        return float("nan"), float("nan")
    z, se = math.atanh(max(min(rho, 0.999999), -0.999999)), 1.0 / math.sqrt(n - 3)
    return math.tanh(z - Z95 * se), math.tanh(z + Z95 * se)


def cluster_bootstrap(df: pd.DataFrame, cols: dict[str, str], draws: int = BOOT_DRAWS, seed: int = SEED) -> dict[str, np.ndarray]:
    """Resample leg-week clusters with replacement. cols maps output name -> column vs net_r; 'diff' = first minus second when both given."""
    codes, _ = pd.factorize(df["cluster"])
    order = np.argsort(codes, kind="stable")
    codes = codes[order]
    cuts = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1], True])
    groups = [order[a:b] for a, b in zip(cuts[:-1], cuts[1:])]
    y = df["net_r"].to_numpy()
    arrs = {k: df[c].to_numpy() for k, c in cols.items()}
    rng = np.random.default_rng(seed)
    out = {k: [] for k in arrs}
    out["diff"] = []
    names = list(arrs)
    for _ in range(draws):
        ix = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        rs = {k: spearman(arrs[k][ix], y[ix]) for k in names}
        for k in names:
            out[k].append(rs[k])
        out["diff"].append(rs[names[0]] - rs[names[1]] if len(names) > 1 else float("nan"))
    return {k: np.asarray(v, float) for k, v in out.items()}


def pct(a: np.ndarray) -> tuple[float, float]:
    a = a[np.isfinite(a)]
    return (float(np.quantile(a, 0.025)), float(np.quantile(a, 0.975))) if len(a) > 20 else (float("nan"), float("nan"))


def decide(n: int, rho: float, wide_lo: float, wide_hi: float, d_point: float, d_lo: float, d_hi: float) -> tuple[str, str]:
    if n < MIN_N:
        return "indeterminate", f"n {n} < {MIN_N} distinct trades after the journal join"
    if not np.isfinite(rho):
        return "indeterminate", "rho not computable (constant column)"
    half = (d_hi - d_lo) / 2 if np.isfinite(d_lo) and np.isfinite(d_hi) else float("nan")
    if rho <= 0 or wide_hi < FAIL_UPPER or (np.isfinite(d_point) and d_point <= 0):
        return "fail", (f"rho {rho:+.4f} (wider CI [{wide_lo:+.4f}, {wide_hi:+.4f}]), paired diff point {d_point:+.4f}"
                        if np.isfinite(d_point) else f"rho {rho:+.4f} (wider CI [{wide_lo:+.4f}, {wide_hi:+.4f}])")
    if wide_lo > 0 and np.isfinite(d_lo) and d_lo > 0 and half <= PAIRED_HALF_WIDTH_MAX:
        return "pass", f"rho {rho:+.4f} lower {wide_lo:+.4f} > 0, paired diff {d_point:+.4f} lower {d_lo:+.4f} > 0 (half-width {half:.3f})"
    return "indeterminate", (f"rho {rho:+.4f} wider CI [{wide_lo:+.4f}, {wide_hi:+.4f}], paired diff {d_point:+.4f} CI [{d_lo:+.4f}, {d_hi:+.4f}] "
                             f"(half-width {half:.3f}, cap {PAIRED_HALF_WIDTH_MAX})")


def evaluate(df: pd.DataFrame, judgment_col: str = "grade_score") -> dict:
    """df: one row per distinct trade with net_r, cluster, <judgment_col>, confidence (nullable)."""
    n = len(df)
    res: dict = {"n": n}
    rho = spearman(df[judgment_col], df.net_r)
    a_lo, a_hi = fisher_ci(rho, n)
    both = df.dropna(subset=["confidence"])
    cols = {"j": judgment_col}
    res.update(rho=rho, analytic_ci=[a_lo, a_hi])
    if n < MIN_N:       # nothing is graded below the floor; skip the bootstrap
        res.update(wider_ci=[a_lo, a_hi], bootstrap_ci=[None, None], n_paired=len(both), rho_confidence=None, paired_diff=None)
        res["verdict"], res["why"] = decide(n, rho, a_lo, a_hi, float("nan"), float("nan"), float("nan"))
        return res
    bj = cluster_bootstrap(df, cols)
    b_lo, b_hi = pct(bj["j"])
    wide_lo, wide_hi = np.nanmin([a_lo, b_lo]), np.nanmax([a_hi, b_hi])
    d_point = d_lo = d_hi = float("nan")
    rho_c = float("nan")
    if len(both) >= MIN_N and both.confidence.nunique() > 1:
        rho_c = spearman(both.confidence, both.net_r)
        rho_j_pair = spearman(both[judgment_col], both.net_r)
        d_point = rho_j_pair - rho_c
        bd = cluster_bootstrap(both, {"j": judgment_col, "c": "confidence"})
        d_lo, d_hi = pct(bd["diff"])
    res.update(wider_ci=[float(wide_lo), float(wide_hi)], bootstrap_ci=[b_lo, b_hi], n_clusters=int(df.cluster.nunique()),
               n_paired=len(both), rho_confidence=rho_c, paired_diff={"point": d_point, "ci95": [d_lo, d_hi]})
    res["verdict"], res["why"] = decide(n, rho, float(wide_lo), float(wide_hi), d_point, d_lo, d_hi)
    return res


# ----------------------------------------------------------------------------------------------- data
def _read_jsonl(p: Path) -> list[dict]:
    out = []
    if not p.is_file():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _ts(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def load_journal(db: Path, trade_ids: set[int]) -> tuple[dict[int, dict] | None, dict[int, float]]:
    """(net R / closed facts by trade id via the family builder's own reader, decision-time package confidence by trade id)."""
    if not db.is_file():
        return None, {}
    from ml.datasets.families.claude_judgments import _journal_outcomes
    out = _journal_outcomes(db, trade_ids)
    conf: dict[int, float] = {}
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        ids = sorted(trade_ids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = (f"SELECT t.id, op.confidence FROM trades t LEFT JOIN order_packages op ON op.order_package_id = t.order_package_id "
                 f"WHERE t.id IN ({','.join('?' * len(chunk))})")
            for tid, c in conn.execute(q, chunk):
                if c is not None:
                    conf[int(tid)] = float(c)
    finally:
        conn.close()
    return out, conf


def load_risk_atr(db: Path, trade_ids: set[int]) -> dict[int, float]:
    """risk_atr by trade id = |package entry - package sl| / signal_logic.atr (blind_grade.build_blind_packet's bracket.risk_atr)."""
    out: dict[int, float] = {}
    if not db.is_file():
        return out
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        ids = sorted(trade_ids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = (f"SELECT t.id, op.entry, op.sl, op.signal_logic FROM trades t LEFT JOIN order_packages op "
                 f"ON op.order_package_id = t.order_package_id WHERE t.id IN ({','.join('?' * len(chunk))})")
            for tid, entry, sl, logic in conn.execute(q, chunk):
                v = risk_atr_of(entry, sl, logic)
                if v is not None:
                    out[int(tid)] = v
    finally:
        conn.close()
    return out


def risk_atr_of(entry, sl, logic) -> float | None:
    try:
        d = json.loads(logic) if isinstance(logic, str) else dict(logic or {})
        e, s, atr = float(entry), float(sl), float(d.get("atr"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not (math.isfinite(e) and math.isfinite(s) and math.isfinite(atr)) or atr <= 0 or e == s:
        return None
    return abs(e - s) / atr


def build_frame(blind: list[dict], journal: dict[int, dict] | None, conf: dict[int, float],
                risk_atr: dict[int, float] | None = None, min_risk_atr: float | None = None) -> tuple[pd.DataFrame, dict]:
    """The registered population, with every exclusion counted so n_in == n_out + sum(excluded)."""
    ex: dict[str, int] = {}

    def bump(k):
        ex[k] = ex.get(k, 0) + 1

    cutoff = _ts(DATE_RULE_AFTER + "T23:59:59Z")
    rows, seen = [], set()
    for r in blind:
        tid = r.get("trade_id")
        if not isinstance(tid, int):
            bump("no_trade_id")
            continue
        if tid in seen:
            bump("duplicate_trade")
            continue
        seen.add(tid)
        dts = _ts(r.get("decision_ts"))
        if r.get("pre_cutoff") is True or dts is None or dts <= cutoff:
            bump("date_rule_pre_cutoff")
            continue
        gs = r.get("grade_score")
        if not isinstance(gs, int) or isinstance(gs, bool):
            bump("no_grade_score")
            continue
        if journal is None:
            bump("outcome_unjoined_no_journal")
            continue
        jr = journal.get(tid)
        if jr is None:
            bump("outcome_unjoined_trade_not_in_journal")
            continue
        if not jr["closed"]:
            bump("outcome_pending")
            continue
        if jr["net_r"] is None:
            bump("outcome_no_net_r")
            continue
        closed, info = _ts(jr["closed_at"]), _ts(r.get("info_cutoff_at"))
        if closed is not None and info is not None and not info < closed:
            bump("blind_grade_not_t0")
            continue
        if min_risk_atr is not None:
            ra = (risk_atr or {}).get(tid)
            if ra is None:
                bump("risk_atr_unknown")
                continue
            if ra < min_risk_atr:
                bump("risk_atr_below_min")
                continue
        wk = dts.isocalendar()
        rows.append({"trade_id": tid, "leg": r.get("leg"), "decision_ts": dts, "net_r": float(jr["net_r"]), "grade_score": gs,
                     "expected_r": r.get("expected_r"), "confidence": conf.get(tid), "prompt_sha": r.get("prompt_sha"),
                     "pool": (r.get("author_kind"), r.get("model_id"), r.get("mask_version")),
                     "cluster": f"{r.get('leg')}|{wk[0]}-W{wk[1]:02d}"})
    df = pd.DataFrame(rows, columns=["trade_id", "leg", "decision_ts", "net_r", "grade_score", "expected_r", "confidence", "prompt_sha", "pool", "cluster"])
    df["expected_r"] = pd.to_numeric(df["expected_r"], errors="coerce")
    return df, {"n_source_rows": len(blind), "n_included": len(df), "excluded_by_reason": ex,
                "partition_ok": len(blind) == len(df) + sum(ex.values())}


def t1_control(revealed: list[dict], df: pd.DataFrame, k: int = K_NEXT) -> dict:
    """Revealed (T1) revised_grade_score vs the mean net R of the NEXT k same-leg graded trades. Non-gating."""
    rg = {r.get("trade_id"): r.get("revised_grade_score") for r in revealed
          if isinstance(r.get("trade_id"), int) and isinstance(r.get("revised_grade_score"), int)}
    xs, ys = [], []
    for _, g in df.sort_values("decision_ts").groupby("leg", sort=False):
        ids, nets = g.trade_id.to_list(), g.net_r.to_numpy()
        for i, tid in enumerate(ids):
            if tid in rg and i + k < len(ids) + 0 and len(ids) - i - 1 >= k:
                xs.append(rg[tid])
                ys.append(float(nets[i + 1:i + 1 + k].mean()))
    n = len(xs)
    rho = spearman(xs, ys) if n >= 3 else float("nan")
    lo, hi = fisher_ci(rho, n)
    return {"k": k, "n": n, "rho": rho, "analytic_ci": [lo, hi], "gating": False}


def strata(df: pd.DataFrame) -> dict:
    out = {}
    for sha, g in df.groupby(df.prompt_sha.fillna("none")):
        rho = spearman(g.grade_score, g.net_r)
        out[str(sha)[:8]] = {"n": len(g), "rho": rho, "analytic_ci": list(fisher_ci(rho, len(g)))}
    return out


# ----------------------------------------------------------------------------------------------- run
def run(a) -> int:
    t0 = datetime.now(timezone.utc)
    comms, db = Path(a.comms), Path(a.db)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    blind = _read_jsonl(comms / "claude_judgments" / "blind_grades.jsonl")
    revealed = _read_jsonl(comms / "claude_judgments" / "revealed_grades.jsonl")
    tids = {r["trade_id"] for r in blind + revealed if isinstance(r.get("trade_id"), int)}
    journal, conf = load_journal(db, tids)
    ratr = load_risk_atr(db, tids) if a.min_risk_atr is not None else None
    df, pop = build_frame(blind, journal, conf, ratr, a.min_risk_atr)
    pop["min_risk_atr"] = a.min_risk_atr
    pop["journal"] = "absent" if journal is None else "present"
    pop["n_with_confidence"] = int(df.confidence.notna().sum()) if len(df) else 0
    pools = {}
    for key, g in df.groupby("pool"):
        pools["|".join(map(str, key))] = {"primary": evaluate(g.reset_index(drop=True), "grade_score"),
                                          "expected_r_secondary": evaluate(g.dropna(subset=["expected_r"]).reset_index(drop=True), "expected_r"),
                                          "prompt_sha_strata": strata(g)}
    head_key = max(pools, key=lambda k: pools[k]["primary"]["n"]) if pools else None
    head = pools[head_key]["primary"] if head_key else None
    if journal is None:
        verdict, read_state, why = "indeterminate", "could_not_look", "journal absent on this host: net R not computable, nothing graded"
    elif head is None:
        verdict, read_state, why = "indeterminate", "measured", f"n 0 after the join ({pop['excluded_by_reason']})"
    else:
        verdict, read_state, why = head["verdict"], "measured", head["why"]
    note = f"cj4 blind validation: {verdict.upper()} | {why} | n {head['n'] if head else 0} | excluded {pop['excluded_by_reason']}"
    row = {"verdict": verdict, "read_state": read_state, "n": head["n"] if head else 0,
           "population": (f"distinct closed crypto trades with a mask-v1 blind grade and a journal net R (package initial stop, full cost stack), "
                          f"decision_ts > {DATE_RULE_AFTER}"
                          f"{'' if a.min_risk_atr is None else f', package risk_atr >= {a.min_risk_atr}'}, pooled within (author_kind, model_id, mask_version) = {head_key}; "
                          f"{pop['n_source_rows']} blind rows read, journal {pop['journal']}"),
           "note": note, "generated_at": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "population_report": pop, "pools": pools, "headline_pool": head_key,
           "t1_control_next_k": t1_control(revealed, df) if len(df) else None,
           "decision_rule": {"id": a.rule_id, "registered_at": a.rule_registered_at, "registered_before_run": True},
           "thresholds": {"min_n": MIN_N, "date_rule_after": DATE_RULE_AFTER, "fail_upper": FAIL_UPPER, "paired_half_width_max": PAIRED_HALF_WIDTH_MAX,
                          "boot_draws": BOOT_DRAWS, "seed": SEED},
           "produced_by": {"tool": "python3 scripts/research/cj4_blind_validation.py", "where": a.where}}
    if verdict == "pass" and head_key:
        ak, mid, mv = head_key.split("|")
        row["qualified_candidate"] = {"author_kind": ak, "model_id": mid, "mask_version": mv, "verdict": "pass", "unit": a.unit}
        (out / "qualified.json").write_text(json.dumps(row["qualified_candidate"], indent=1) + "\n")
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=lambda o: None if o != o else str(o)) + "\n")
    print(note, flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- self-test
def _synthetic(n: int, signal: float, seed: int, conf_signal: float = 0.0, n_sha: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    legs = [f"leg{i}" for i in range(6)]
    net = rng.normal(0, 1, n)
    grade = np.clip(np.round(2.5 + signal * 2.0 * net + rng.normal(0, 1.2, n)), 1, 5).astype(int)
    conf = 0.5 + conf_signal * net + rng.normal(0, 1, n)
    ts = pd.Timestamp("2026-07-02", tz="UTC") + pd.to_timedelta(rng.integers(0, 120 * 24, n), unit="h")
    wk = ts.isocalendar()
    return pd.DataFrame({"trade_id": np.arange(n), "leg": rng.choice(legs, n), "decision_ts": ts, "net_r": net, "grade_score": grade,
                         "expected_r": grade * 0.1, "confidence": conf, "prompt_sha": [f"s{i % n_sha}" for i in range(n)],
                         "pool": [("llm", "m", "mask-v1")] * n}).assign(
        cluster=lambda d: d.leg + "|" + wk.year.astype(str).to_numpy() + "-W" + wk.week.astype(str).to_numpy())


def self_test() -> int:
    # planted positive: strong judgment signal, confidence uninformative -> PASS
    pos = evaluate(_synthetic(707, 0.5, 1, conf_signal=0.0))
    assert pos["verdict"] == "pass" and pos["rho"] > 0.3 and pos["paired_diff"]["ci95"][0] > 0, pos
    # planted null: no signal -> never PASS; rho CI straddles 0 so the registered rule gives FAIL on rho<=0 or INDETERMINATE, and wider CI >= analytic
    null = evaluate(_synthetic(707, 0.0, 2, conf_signal=0.0))
    assert null["verdict"] in ("fail", "indeterminate") and abs(null["rho"]) < 0.12, null
    assert null["wider_ci"][0] <= null["analytic_ci"][0] + 1e-12 and null["wider_ci"][1] >= null["analytic_ci"][1] - 1e-12
    # a judgment that is real but no better than confidence must not PASS (beat-confidence clause)
    tie = evaluate(_synthetic(707, 0.5, 3, conf_signal=1.6))
    assert tie["verdict"] != "pass", tie
    # negative signal (like the n=50 pilot's sign) -> FAIL
    neg = evaluate(_synthetic(707, -0.5, 4, conf_signal=0.0))
    assert neg["verdict"] == "fail" and neg["rho"] < 0, neg
    # n < 150 -> INDETERMINATE even with a huge effect
    thin = evaluate(_synthetic(149, 0.9, 5))
    assert thin["verdict"] == "indeterminate" and "149" in thin["why"], thin
    assert "bootstrap_ci" in evaluate(_synthetic(150, 0.9, 5)) and evaluate(_synthetic(150, 0.9, 5))["bootstrap_ci"][0] is not None   # floor inclusive
    # population partition + date rule + T0 exclusion on a tiny synthetic journal
    blind = [{"trade_id": i, "decision_ts": "2026-07-0%dT10:00:00Z" % (i + 1) if i < 8 else "2026-06-20T10:00:00Z", "info_cutoff_at": "2026-07-01T10:00:00Z",
              "grade_score": 3, "leg": "L", "model_id": "m", "mask_version": "mask-v1", "author_kind": "llm", "pre_cutoff": None, "prompt_sha": "x"}
             for i in range(10)]
    blind[8]["pre_cutoff"] = True
    journal = {i: {"closed": True, "closed_at": "2026-08-01T00:00:00Z", "net_r": 0.1 * i} for i in range(10)}
    journal[1]["closed"] = False
    journal[2]["closed_at"] = "2026-06-30T00:00:00Z"        # closed before the cutoff -> not T0
    journal.pop(3)
    df, pop = build_frame(blind, journal, {i: 0.5 for i in range(10)})
    assert pop["partition_ok"] and len(df) == 5, (pop, len(df))
    assert pop["excluded_by_reason"] == {"outcome_pending": 1, "blind_grade_not_t0": 1, "outcome_unjoined_trade_not_in_journal": 1,
                                         "date_rule_pre_cutoff": 2}, pop
    assert build_frame(blind, None, {})[1]["excluded_by_reason"].get("outcome_unjoined_no_journal") == 8
    # --min-risk-atr (089f-04): of the 5 included, one below the floor, one with no risk_atr; partition still exact
    ra = {0: 2.0, 4: 0.6, 5: 1.0, 6: 1.5}
    df2, pop2 = build_frame(blind, journal, {}, ra, 1.0)
    assert pop2["partition_ok"] and len(df2) == 3 and pop2["excluded_by_reason"]["risk_atr_below_min"] == 1, pop2
    assert pop2["excluded_by_reason"]["risk_atr_unknown"] == 1, pop2          # trade 7 has no risk_atr
    assert len(build_frame(blind, journal, {}, ra, None)[0]) == 5            # default: 089f-01 unchanged
    assert abs(risk_atr_of(100.0, 98.0, '{"atr": 4.0}') - 0.5) < 1e-12 and risk_atr_of(100.0, 100.0, '{"atr": 1}') is None
    assert risk_atr_of(100.0, 98.0, "{}") is None and risk_atr_of(None, 98.0, '{"atr": 1}') is None
    # T1 control needs k later same-leg trades
    d = pd.DataFrame({"trade_id": range(20), "leg": "L", "decision_ts": pd.date_range("2026-08-01", periods=20, tz="UTC"), "net_r": np.arange(20.0)})
    tc = t1_control([{"trade_id": i, "revised_grade_score": i} for i in range(20)], d)
    assert tc["n"] == 20 - K_NEXT and tc["rho"] > 0.99 and tc["gating"] is False, tc
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--unit", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--db", default="data/trade_journal.db")
    ap.add_argument("--comms", default="comms")
    ap.add_argument("--where", default="trainer")
    ap.add_argument("--rule-id", dest="rule_id", default="RULE-RQ20261116-089f-01-BLIND-VALIDATION")
    ap.add_argument("--rule-registered-at", dest="rule_registered_at", default="2026-11-16")
    ap.add_argument("--min-risk-atr", dest="min_risk_atr", type=float, default=None,
                    help="exclude trades whose package stop distance is under this many ATR (RQ-20261118-089f-04)")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.unit or not a.out:
        ap.error("--unit and --out are required (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
