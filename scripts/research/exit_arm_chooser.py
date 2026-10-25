#!/usr/bin/env python3
# wiring: research/queue/RQ-20261024-09a6-04 (AI-ATM rung C1) via .github/workflows/research-script-run.yml
"""EXIT-ARM-CHOICE-CORPUS: per-arm trade emits JOINED on entry, and a state-conditioned chooser graded over them.

WHY (checklist row EXIT-ARM-CHOICE-CORPUS; Programme 01 section 'AI active trade management -- the merged programme',
rung C1, unit RQ-20261024-09a6-04). The exit levers that confirmed (stall trail decay, ADX trail, momentum-stale,
stall pull-in TP) each won on some legs and lost on others. That is what a policy layer is for: per trade, pick the
rule that fits. Offline every arm's outcome is OBSERVABLE -- re-run the harness once per arm and the same entry has a
net R under each rule -- so this is full-information cost-sensitive classification: no propensity model, no
doubly-robust OPE (RQ-20261011-9da8-04 keeps the live-logged case).

WHAT IT DOES
  1. Runs each ``--leg`` once per ``--arm`` through the SAME argv the evidence builder runs
     (``exit_lever_ablation.build_arm_argv``) with ``--emit-trades --emit-features`` and KEEPS every arm's emit
     under ``<out>/arms/<leg>__<arm>__trades.jsonl``. (``--from-emits DIR`` reads previously kept emits instead.)
  2. JOINS the arms on (leg, entry_ts, side) and reports ENTRY-SET AGREEMENT: per leg and arm, how many entries the
     arm shares with arm A, and the share of the union that is NOT in every arm (the 'excluded' share). A lever that
     changes re-entry changes the entry set; those trades are excluded, never imputed.
  3. Grades a cost-sensitive MULTINOMIAL LOGISTIC chooser on ENTRY-BAR state only (ATR percentile, ADX-14, its 3-bar
     change, vol-regime bucket, leg fixed effects -- all known at the entry bar's close, nothing from in-trade),
     fit on the other calendar folds: the softmax policy maximising expected net R over the arms
     (loss = -sum_a pi_a(x) * netR_a, L2). 6 calendar folds by entry; a training trade whose [entry, latest exit over
     the arms] overlaps the test fold's span is PURGED. Out of sample it is compared to (i) arm A and (ii) the
     TRAIN-FOLD best fixed arm. The oracle (best arm per trade in hindsight) is the ceiling, reported, never graded.
  4. Net R per capital-day for each policy from ``scripts/capital_efficiency.py`` (the single home); bars held come
     from the emit's entry/exit times and the leg's timeframe. Cost: every net R is the harness's own
     ``execution_costs.resolve_cost_policy`` stack (fee + slippage + funding); ``cost_policy_check`` re-resolves it
     per symbol and compares it with the slippage the harness recorded.

THE REGISTERED RULE (unit RQ-20261024-09a6-04 ``decision_rule``; the thresholds are flags whose defaults ARE the
registered values and are never changed after a result):
  INDETERMINATE if > 10% of the union of entries is excluded by the join, or < 600 joined trades;
  PASS   if (chooser - best fixed) >= +0.03 R/trade AND bootstrap CI lower > 0 AND >= 4 of 6 folds positive AND
         chooser net R per capital-day >= best fixed's AND maxDD <= 1.35x best fixed's on every leg;
  FAIL   if the CI upper bound of (chooser - best fixed) < 0.03 R;
  otherwise INDETERMINATE ('unresolved': not a pass, not a fail -- the rule has no third outcome, so none is invented).

Harness paths, not live paths. Chooses at the ENTRY bar only (per-bar switching is rung C2, earned by a PASS).
Changes no config, places no order. Tier-1 research tooling.

    python3 scripts/research/exit_arm_chooser.py --self-test
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]


def _pin_paths() -> None:
    """REPO first: ``scripts/ml`` must not shadow the repo's ``ml`` package (importing exit_lever_ablation re-prepends scripts/)."""
    for p in (REPO / "scripts" / "research", REPO / "scripts", REPO):
        if str(p) in sys.path:
            sys.path.remove(str(p))
        sys.path.insert(0, str(p))


_pin_paths()
import capital_efficiency  # noqa: E402  (the ONE definition of net R per capital-day)

TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
STATE_COLS = ["atr_pctl", "adx", "adx_slope3", "vol_high", "vol_mid"]
SLIP_TOL_BPS = 0.5
ADX_MATCH_TOL = 5e-4
DD_FACTOR = 1.35


# --------------------------------------------------------------------------- arms and the join
def _ts(s: Any) -> pd.Timestamp:
    t = pd.Timestamp(str(s))
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _load_jsonl(path: Path) -> List[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def adx_slope3_for_entries(csv: str, rows: List[dict]) -> Tuple[Dict[Any, float], float]:
    """3-bar ADX change at the entry bar, computed from the candles with the harness's own ADX.

    The emit carries ``f_adx_14`` (the entry bar's ADX) but not its slope, so the slope is re-derived: locate the bar
    whose ADX equals the emitted ``f_adx_14`` among {j-1, j, j+1} around the bar stamped at entry_time (j), and
    take adx[i] - adx[i-3]. Returns ({entry_time: slope}, share of entries that matched) -- the match share is the
    instrument's positive control; an entry that does not match gets NaN (train median), never a guess."""
    from harness_emit import _wilder_adx
    df = pd.read_csv(csv)
    ts = df["timestamp"]
    df["timestamp"] = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) else pd.to_datetime(ts, utc=True)
    adx = _wilder_adx(df, 14).to_numpy(dtype=float)
    idx = {t.value: i for i, t in enumerate(df["timestamp"])}
    out: Dict[Any, float] = {}
    hit = 0
    for r in rows:
        j = idx.get(_ts(r["entry_time"]).value)
        f = r.get("f_adx_14")
        out[r["entry_time"]] = float("nan")
        if j is None or f is None:
            continue
        for i in (j, j - 1, j + 1):
            if 3 <= i < len(adx) and np.isfinite(adx[i]) and abs(adx[i] - float(f)) <= ADX_MATCH_TOL:
                out[r["entry_time"]] = float(adx[i] - adx[i - 3])
                hit += 1
                break
    return out, (hit / len(rows) if rows else 0.0)


def entry_state(row: dict, slope: float) -> Dict[str, float]:
    """The decision-time state: ONLY the f_* entry-bar columns the emit wrote at the decision bar, plus the slope."""
    bucket = row.get("f_atr_pctl_bucket")
    nan = float("nan")
    return {"atr_pctl": nan if row.get("f_atr_pctl") is None else float(row["f_atr_pctl"]),
            "adx": nan if row.get("f_adx_14") is None else float(row["f_adx_14"]),
            "adx_slope3": slope,
            "vol_high": nan if bucket is None else float(bucket == "high"),
            "vol_mid": nan if bucket is None else float(bucket == "mid")}


def _key(leg: str, row: dict) -> Tuple[str, str, str]:
    return (leg, str(_ts(row["entry_time"])), str(row.get("direction") or row.get("side")))


def join_arms(per_leg: Dict[str, Dict[str, List[dict]]], arms: List[str], baseline: str) -> Tuple[List[dict], Dict[str, Any]]:
    """Join on (leg, entry_ts, side). Returns (joined trades, entry-set agreement report).

    A joined trade is present in EVERY arm. Duplicate keys inside one arm are counted and the first kept (the join key
    is the identity; a duplicate would double-weight a trade)."""
    joined: List[dict] = []
    rep: Dict[str, Any] = {"legs": {}, "arms": arms, "baseline": baseline}
    n_union = n_joined = 0
    for leg, by_arm in per_leg.items():
        maps: Dict[str, Dict[tuple, dict]] = {}
        dups: Dict[str, int] = {}
        for a in arms:
            m: Dict[tuple, dict] = {}
            for r in by_arm.get(a, []):
                k = _key(leg, r)
                if k in m:
                    dups[a] = dups.get(a, 0) + 1
                    continue
                m[k] = r
            maps[a] = m
        union = set().union(*[set(m) for m in maps.values()]) if maps else set()
        common = set.intersection(*[set(m) for m in maps.values()]) if maps else set()
        base = set(maps.get(baseline, {}))
        rep["legs"][leg] = {
            "n_union": len(union), "n_in_every_arm": len(common), "excluded_share": round(1 - len(common) / len(union), 4) if union else None,
            "n_by_arm": {a: len(maps[a]) for a in arms},
            "share_of_baseline_entries_in_arm": {a: (round(len(base & set(maps[a])) / len(base), 4) if base else None) for a in arms},
            "duplicate_keys_by_arm": dups}
        n_union += len(union)
        n_joined += len(common)
        for k in sorted(common, key=lambda k: k[1]):
            joined.append({"leg": leg, "key": k, "entry_time": _ts(k[1]), "side": k[2],
                           "exit_time": max(_ts(maps[a][k]["exit_time"]) for a in arms),
                           "rows": {a: maps[a][k] for a in arms}})
    rep.update(n_union=n_union, n_joined=n_joined, excluded_share=round(1 - n_joined / n_union, 4) if n_union else None)
    return joined, rep


# --------------------------------------------------------------------------- the chooser
class SoftmaxPolicy:
    """Cost-sensitive multinomial logistic: pi(a|x) = softmax(Z b)_a, minimising -mean_i sum_a pi_ia * R_ia + l2 |b|^2.

    Full-information: every arm's R is observed for every training trade. Standardised features, NaN -> train
    median. Adam on a smooth objective; the intercept row lets it reproduce any fixed arm, so the chooser's capacity
    contains the best-fixed policy and a state effect has to be real to beat it out of sample."""

    def __init__(self, l2: float = 0.05, iters: int = 500, lr: float = 0.05):
        self.l2, self.iters, self.lr = l2, iters, lr

    def _z(self, X: np.ndarray) -> np.ndarray:
        X = np.where(np.isfinite(X), X, self.med)
        return np.c_[np.ones(len(X)), (X - self.mu) / self.sd]

    def fit(self, X: np.ndarray, R: np.ndarray) -> "SoftmaxPolicy":
        self.med = np.where(np.isfinite(np.nanmedian(X, axis=0)), np.nanmedian(X, axis=0), 0.0)
        Xf = np.where(np.isfinite(X), X, self.med)
        self.mu, self.sd = Xf.mean(0), Xf.std(0) + 1e-9
        self.scale = float(R.std()) + 1e-9
        Z, Rs = self._z(X), R / self.scale
        n, d = Z.shape
        B = np.zeros((d, R.shape[1]))
        m, v = np.zeros_like(B), np.zeros_like(B)
        reg = np.ones((d, 1)) * self.l2
        reg[0] = 0.0
        for t in range(1, self.iters + 1):
            S = Z @ B
            S -= S.max(1, keepdims=True)
            P = np.exp(S)
            P /= P.sum(1, keepdims=True)
            adv = Rs - (P * Rs).sum(1, keepdims=True)
            G = -(Z.T @ (P * adv)) / n + 2 * reg * B
            m = 0.9 * m + 0.1 * G
            v = 0.999 * v + 0.001 * G * G
            B -= self.lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
        self.B = B
        return self

    def choose(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self._z(X) @ self.B, axis=1)


def calendar_folds(joined: List[dict], k: int) -> List[Tuple[List[int], List[int]]]:
    """k equal calendar spans of the pooled entry range; train drops any trade overlapping the test span (purged)."""
    ent = np.array([j["entry_time"].value for j in joined], dtype=np.int64)
    ext = np.array([j["exit_time"].value for j in joined], dtype=np.int64)
    edges = np.linspace(ent.min(), ent.max() + 1, k + 1)
    fid = np.clip(np.searchsorted(edges, ent, side="right") - 1, 0, k - 1)
    out = []
    for f in range(k):
        te = [int(i) for i in np.nonzero(fid == f)[0]]
        tr = [int(i) for i in np.nonzero(fid != f)[0] if not (ent[i] < edges[f + 1] and ext[i] >= edges[f])]
        out.append((tr, te))
    return out


def _max_dd(x: List[float]) -> float:
    c = np.r_[0.0, np.cumsum(x)]
    return float(np.max(np.maximum.accumulate(c) - c))


def _ce(rs: List[dict], pick: str) -> Dict[str, Any]:
    days = sum(capital_efficiency.days_from_bars(r[f"{pick}_bars"], r["tfm"]) or 0.0 for r in rs)
    net = sum(r[f"{pick}_net"] for r in rs)
    return {"capital_days": round(days, 4), "net_r": round(float(net), 4),
            "net_r_per_capital_day": round(net / days, 4) if days > 0 else None}


def grade_chooser(joined: List[dict], X: np.ndarray, R: np.ndarray, Bars: np.ndarray, arms: List[str], baseline: str, *,
                  n_folds: int = 6, n_boot: int = 2000, seed: int = 7, l2: float = 0.05) -> Dict[str, Any]:
    """Out-of-sample chooser vs A and vs the train-fold best fixed arm. R, Bars: (n_trades, n_arms)."""
    a0 = arms.index(baseline)
    folds = calendar_folds(joined, n_folds)
    recs: List[dict] = []
    for f, (tr, te) in enumerate(folds):
        if len(tr) < 20 or not te:
            continue
        fixed = int(np.argmax(R[tr].mean(0)))
        pol = SoftmaxPolicy(l2=l2).fit(X[tr], R[tr])
        pick = pol.choose(X[te])
        for r_i, p in zip(te, pick):
            j = joined[r_i]
            recs.append({"fold": f + 1, "leg": j["leg"], "entry_time": j["entry_time"], "tfm": j["tfm"],
                         "chooser_net": float(R[r_i, p]), "chooser_bars": float(Bars[r_i, p]), "chooser_arm": arms[int(p)],
                         "A_net": float(R[r_i, a0]), "A_bars": float(Bars[r_i, a0]),
                         "fixed_net": float(R[r_i, fixed]), "fixed_bars": float(Bars[r_i, fixed]), "fixed_arm": arms[fixed],
                         "oracle_net": float(R[r_i].max())})
    if not recs:
        return {"n_oos": 0}
    rng = np.random.default_rng(seed)

    def cmp(vs: str) -> Dict[str, Any]:
        d = np.array([r["chooser_net"] - r[f"{vs}_net"] for r in recs])
        boot = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)])
        by_f = {str(f): round(float(np.mean([r["chooser_net"] - r[f"{vs}_net"] for r in recs if r["fold"] == f])), 4)
                for f in sorted({r["fold"] for r in recs})}
        return {"diff_r_per_trade": round(float(d.mean()), 4), "ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
                "folds_diff": by_f, "folds_positive": sum(1 for v in by_f.values() if v > 0)}

    legs_dd = {}
    for lg in sorted({r["leg"] for r in recs}):
        lr = sorted([r for r in recs if r["leg"] == lg], key=lambda r: r["entry_time"])
        c, b = _max_dd([r["chooser_net"] for r in lr]), _max_dd([r["fixed_net"] for r in lr])
        legs_dd[lg] = {"n": len(lr), "chooser_maxdd_r": round(c, 3), "fixed_maxdd_r": round(b, 3), "ok": bool(c <= DD_FACTOR * b + 1e-9)}
    share = {a: round(sum(r["chooser_arm"] == a for r in recs) / len(recs), 4) for a in arms}
    return {"n_oos": len(recs), "vs_best_fixed": cmp("fixed"), "vs_A": cmp("A"),
            "mean_net_r": {k: round(float(np.mean([r[f"{k}_net"] for r in recs])), 4) for k in ("chooser", "A", "fixed", "oracle")},
            "capital_efficiency": {k: _ce(recs, k) for k in ("chooser", "A", "fixed")},
            "maxdd_per_leg": legs_dd, "chooser_arm_share": share,
            "best_fixed_arm_by_fold": {str(f): sorted({r["fixed_arm"] for r in recs if r["fold"] == f}) for f in sorted({r["fold"] for r in recs})},
            "oracle_note": "best arm per trade in hindsight: the ceiling, never graded"}


def verdict(rep: Dict[str, Any], g: Dict[str, Any], *, min_n: int, max_excluded: float, min_gain: float, min_folds: int) -> Tuple[str, str, str]:
    """The registered rule. Returns (verdict, label, why)."""
    if rep.get("n_joined", 0) < min_n:
        return "indeterminate", "n_floor", f"{rep.get('n_joined', 0)} joined trades < {min_n}"
    if (rep.get("excluded_share") or 0.0) > max_excluded:
        return "indeterminate", "entry_set_differs", f"{rep['excluded_share']:.1%} of entries excluded by the join > {max_excluded:.0%}"
    if not g.get("n_oos"):
        return "indeterminate", "no_oos", "no out-of-sample trades"
    bf, ce = g["vs_best_fixed"], g["capital_efficiency"]
    lo, hi, d = bf["ci95"][0], bf["ci95"][1], bf["diff_r_per_trade"]
    c_cd, f_cd = ce["chooser"]["net_r_per_capital_day"], ce["fixed"]["net_r_per_capital_day"]
    dd_ok = all(v["ok"] for v in g["maxdd_per_leg"].values())
    if hi < min_gain:
        return "fail", "state_does_not_pick_rule", f"CI upper {hi:+.4f} < {min_gain} R (diff {d:+.4f})"
    clauses = {"diff": d >= min_gain, "ci_lower": lo > 0, "folds": bf["folds_positive"] >= min_folds,
               "per_capital_day": c_cd is not None and f_cd is not None and c_cd >= f_cd, "maxdd": dd_ok}
    if all(clauses.values()):
        return "pass", "chooser_beats_best_fixed", f"diff {d:+.4f} R/trade CI [{lo:+.4f}, {hi:+.4f}], {bf['folds_positive']} folds positive"
    return "indeterminate", "unresolved", "CI upper >= bar but a PASS clause failed: " + ", ".join(k for k, v in clauses.items() if not v)


# --------------------------------------------------------------------------- run
def build_matrices(joined: List[dict], arms: List[str], legs: List[str], states: Dict[tuple, Dict[str, float]],
                   tfm_by_leg: Dict[str, int]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    fe = legs[1:]
    X, R, Bars = [], [], []
    for j in joined:
        s = states[j["key"]]
        j["tfm"] = tfm_by_leg[j["leg"]]
        X.append([s[c] for c in STATE_COLS] + [1.0 if j["leg"] == lg else 0.0 for lg in fe])
        R.append([float(j["rows"][a]["net_r"]) for a in arms])
        Bars.append([max((_ts(j["rows"][a]["exit_time"]) - j["entry_time"]).total_seconds() / 60.0 / j["tfm"], 1.0) for a in arms])
    return np.array(X, dtype=float), np.array(R, dtype=float), np.array(Bars, dtype=float)


def cost_policy_check(per_leg: Dict[str, Dict[str, List[dict]]]) -> Dict[str, Any]:
    """Re-resolve the venue slippage per symbol (execution_costs.resolve_cost_policy) and compare with what the harness
    charged: the emit's cost_slippage_r x risk / entry, in bps."""
    from src.runtime.execution_costs import resolve_cost_policy
    out: Dict[str, Any] = {}
    for leg, by_arm in per_leg.items():
        rows = next(iter(by_arm.values()), [])
        gaps = []
        sym = None
        for r in rows:
            sym = r.get("symbol") or sym
            risk = abs(float(r["entry"]) - float(r["sl"]))
            if risk > 0 and r.get("cost_slippage_r") is not None:
                gaps.append(float(r["cost_slippage_r"]) * risk / float(r["entry"]) * 1e4)
        if not gaps or not sym:
            out[leg] = {"state": "unmeasured"}
            continue
        want = float(resolve_cost_policy(sym)[0])
        med = float(np.median(gaps))
        out[leg] = {"symbol": sym, "resolve_cost_policy_slippage_bps": round(want, 3), "harness_median_bps": round(med, 3),
                    "state": "match" if abs(med - want) <= SLIP_TOL_BPS else "mismatch"}
    return out


def run_grade(per_leg: Dict[str, Dict[str, List[dict]]], states_by_leg: Dict[str, Dict[Any, float]], tfm_by_leg: Dict[str, int],
              a: argparse.Namespace, *, arms: List[str], omitted: Dict[str, List[str]], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    joined, rep = join_arms(per_leg, arms, a.baseline)
    legs = sorted(per_leg)
    states = {}
    for j in joined:
        row = j["rows"][a.baseline]
        states[j["key"]] = entry_state(row, states_by_leg.get(j["leg"], {}).get(row["entry_time"], float("nan")))
    meas: Dict[str, Any] = {"arms": arms, "omitted_arms": omitted, "entry_set_agreement": rep, "legs": legs}
    if joined:
        X, R, Bars = build_matrices(joined, arms, legs, states, tfm_by_leg)
        g = grade_chooser(joined, X, R, Bars, arms, a.baseline, n_folds=a.n_folds, n_boot=a.n_boot, l2=a.l2)
        meas["chooser"] = g
        meas["state_columns"] = STATE_COLS + [f"leg_fe:{lg}" for lg in legs[1:]]
        meas["state_missing_share"] = {c: round(float(np.mean(~np.isfinite(X[:, i]))), 4) for i, c in enumerate(STATE_COLS)}
        meas["arm_mean_net_r_joined"] = {ar: round(float(R[:, i].mean()), 4) for i, ar in enumerate(arms)}
    else:
        g = {"n_oos": 0}
    v, label, why = verdict(rep, g, min_n=a.min_n, max_excluded=a.max_excluded, min_gain=a.min_gain_r, min_folds=a.min_folds)
    if extra:
        meas.update(extra)
    pop = (f"{rep['n_joined']} trades present in every arm of {arms} (of {rep['n_union']} entries in the union) on {legs}; "
           f"entry-bar state only; net of the harness's venue-aware cost stack; {a.n_folds} purged calendar folds by entry; "
           f"{g.get('n_oos', 0)} out-of-sample trades graded")
    rec = {"verdict": v, "read_state": "measured" if rep["n_joined"] else "unmeasured", "population": pop, "n": rep["n_joined"],
           "measurement": meas, "note": f"C1/{label}: {why}"}
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    if joined:
        (out / "joined.jsonl").write_text("".join(json.dumps({"leg": j["leg"], "entry_time": str(j["entry_time"]), "side": j["side"],
                                                              "net_r": {x: j["rows"][x]["net_r"] for x in arms}, "state": states[j["key"]]},
                                                             default=str) + "\n" for j in joined), encoding="utf-8")
    return rec


def run_harness(a: argparse.Namespace) -> Dict[str, Any]:
    import yaml
    import exit_lever_ablation as ela
    _pin_paths()
    cfgs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    cfgs = cfgs.get("strategies", cfgs)
    specs = [ela.parse_arm(s) for s in a.arm]
    labels = [s[0] for s in specs]
    out = Path(a.out)
    arms_dir = out / "arms"
    arms_dir.mkdir(parents=True, exist_ok=True)
    wd = Path(tempfile.mkdtemp(prefix="exit_arm_chooser_"))
    per_leg: Dict[str, Dict[str, List[dict]]] = {}
    slopes: Dict[str, Dict[Any, float]] = {}
    tfm: Dict[str, int] = {}
    unavailable: Dict[str, List[str]] = {}
    adx_match: Dict[str, float] = {}
    argvs: Dict[str, Any] = {}
    for leg in a.leg:
        base = cfgs[leg]
        tfm[leg] = TF_MIN[str(base.get("timeframe"))]
        csv = str(wd / f"{leg}__data.csv")
        if a.data_csv:
            csv, feed = a.data_csv, {"resample": base.get("timeframe"), "source": "explicit --data-csv"}
        else:
            feed = ela.fetch_candles(leg, base, a.days, csv, non_crypto_source=a.non_crypto_source)
        per_leg[leg] = {}
        for label, sets, unsets, extra in specs:
            # a GEOM-B1 TP lever on a leg that declares tp_revision REPLACES the declared mover (two movers abort the harness)
            if base.get("tp_revision") and any(x in ela._GEOM_TP_FLAGS for x in extra) and "tp_revision" not in unsets:
                unsets = unsets + ["tp_revision"]
            cfg = ela.arm_cfg(base, sets, unsets)
            emit = str(arms_dir / f"{leg}__{label}__trades.jsonl")
            jout = str(wd / f"{leg}__{label}__bt.json")
            argv, omitted = ela.build_arm_argv(leg, cfg, csv, str(feed["resample"]), emit, jout, extra, a.start, a.end)
            argv += ["--emit-features"]
            argvs[f"{leg}:{label}"] = {"argv": [("<data>" if t == csv else t) for t in argv], "omitted_levers_per_builder": omitted}
            r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False)
            if r.returncode != 0:
                unavailable.setdefault(label, []).append(leg)
                (arms_dir / f"{leg}__{label}__stderr.log").write_text(r.stderr[-8000:], encoding="utf-8")
                print(f"[{leg}:{label}] harness exit {r.returncode}: {r.stderr[-300:]}", file=sys.stderr)
                continue
            per_leg[leg][label] = _load_jsonl(Path(emit))
        if a.baseline in per_leg[leg]:
            slopes[leg], adx_match[leg] = adx_slope3_for_entries(csv, per_leg[leg][a.baseline])
    return finish(a, per_leg, slopes, tfm, labels, unavailable, {"adx_slope_match_share": adx_match, "argv": argvs})


def run_from_emits(a: argparse.Namespace) -> Dict[str, Any]:
    d = Path(a.from_emits)
    per_leg: Dict[str, Dict[str, List[dict]]] = {}
    for leg in a.leg:
        per_leg[leg] = {}
        for p in sorted(d.glob(f"{leg}__*__trades.jsonl")):
            per_leg[leg][p.name[len(leg) + 2:-len("__trades.jsonl")]] = _load_jsonl(p)
    labels = sorted({x for v in per_leg.values() for x in v})
    slopes = {leg: {r["entry_time"]: float(r.get("adx_slope3", float("nan"))) for r in rows.get(a.baseline, [])} for leg, rows in per_leg.items()}
    tfm = {leg: TF_MIN[a.tf] for leg in a.leg}
    return finish(a, per_leg, slopes, tfm, labels, {}, {"source": f"--from-emits {a.from_emits}"})


def finish(a: argparse.Namespace, per_leg, slopes, tfm, labels, unavailable, extra) -> Dict[str, Any]:
    if any(a.baseline not in per_leg[leg] for leg in per_leg):
        extra["baseline_missing_on"] = [leg for leg in per_leg if a.baseline not in per_leg[leg]]
        per_leg = {leg: v for leg, v in per_leg.items() if a.baseline in v}
    # an arm the harness refused on any leg is dropped everywhere and NAMED (the unit: 'else omitted and named')
    arms = [x for x in labels if x not in unavailable and all(x in v for v in per_leg.values())]
    omitted = {x: unavailable.get(x, sorted(leg for leg, v in per_leg.items() if x not in v)) for x in labels if x not in arms}
    extra["cost_policy_check"] = cost_policy_check({lg: {x: v[x] for x in arms if x in v} for lg, v in per_leg.items() if v})
    if not per_leg or a.baseline not in arms:
        raise SystemExit("no leg produced the baseline arm; nothing to grade")
    rec = run_grade(per_leg, slopes, tfm, a, arms=arms, omitted=omitted, extra=extra)
    print(json.dumps({"verdict": rec["verdict"], "note": rec["note"]}, indent=1))
    return rec


def add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--leg", action="append", required=False, default=[])
    ap.add_argument("--arm", action="append", default=[], help='LABEL=tok;tok (exit_lever_ablation syntax); "A=" is the leg as declared')
    ap.add_argument("--baseline", default="A")
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--non-crypto-source", choices=("auto", "dukascopy"), default="auto")
    ap.add_argument("--data-csv", default=None, help="skip the fetch and use this candle CSV for every leg (tests)")
    ap.add_argument("--from-emits", default=None, help="DIR of <leg>__<arm>__trades.jsonl (kept emits / tests)")
    ap.add_argument("--tf", default="4h", help="--from-emits only: the legs' timeframe")
    ap.add_argument("--n-folds", type=int, default=6)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--l2", type=float, default=0.05)
    ap.add_argument("--min-n", type=int, default=600, help="registered: joined trades floor")
    ap.add_argument("--max-excluded", type=float, default=0.10, help="registered: excluded-by-join share ceiling")
    ap.add_argument("--min-gain-r", type=float, default=0.03, help="registered: chooser - best fixed, R/trade")
    ap.add_argument("--min-folds", type=int, default=4, help="registered: folds positive")
    ap.add_argument("--out", required=True)


# --------------------------------------------------------------------------- self-test
def synthetic(n: int, *, planted: bool, shuffle: bool, seed: int = 3, drop_frac: float = 0.0) -> Tuple[Dict[str, Dict[str, List[dict]]], Dict[str, Dict[Any, float]]]:
    """Two legs, arms A/B/C. Planted: B beats A where ADX is high, C beats A where it is low, so NO fixed arm wins and
    only a state-conditioned choice does. Shuffled: the same rewards with the state rows permuted across trades."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2020-07-01", tz="UTC")
    per_leg: Dict[str, Dict[str, List[dict]]] = {}
    slopes: Dict[str, Dict[Any, float]] = {}
    for li, leg in enumerate(("leg_x", "leg_y")):
        m = n // 2
        ent = [t0 + pd.Timedelta(hours=4 * int(i)) for i in np.sort(rng.choice(14000, m, replace=False))]
        adx = rng.normal(25, 8, m)
        slope = rng.normal(0, 3, m)
        pctl = rng.uniform(0, 1, m)
        eff = np.sign(adx - 25) * 0.5 if planted else np.zeros(m)
        noise = rng.normal(0, 0.8, (3, m))
        net = {"A": noise[0] + 0.05, "B": noise[1] + 0.05 + eff, "C": noise[2] + 0.05 - eff}
        if shuffle:
            perm = rng.permutation(m)
            adx, slope, pctl = adx[perm], slope[perm], pctl[perm]
        per_leg[leg] = {a: [] for a in net}
        slopes[leg] = {}
        for i, e in enumerate(ent):
            et = str(e)
            slopes[leg][et] = float(slope[i])
            for a in net:
                if drop_frac and a == "C" and rng.random() < drop_frac:
                    continue
                per_leg[leg][a].append({"entry_time": et, "exit_time": str(e + pd.Timedelta(hours=4 * int(3 + i % 9))), "direction": "long", "symbol": "X",
                                        "net_r": float(net[a][i]), "f_adx_14": float(adx[i]), "f_atr_pctl": float(pctl[i]),
                                        "f_atr_pctl_bucket": "high" if pctl[i] > 2 / 3 else ("mid" if pctl[i] > 1 / 3 else "low")})
    return per_leg, slopes


def _self_args(out: str, **kw: Any) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    add_args(ap)
    a = ap.parse_args(["--out", out, "--n-boot", "400"])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def _self_test() -> int:
    ok = True

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'} {label} {detail}")
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as td:
        tfm = {"leg_x": 240, "leg_y": 240}
        res = {}
        for name, kw in (("planted", dict(planted=True, shuffle=False)), ("shuffled", dict(planted=True, shuffle=True)),
                         ("null", dict(planted=False, shuffle=False))):
            per_leg, slopes = synthetic(1400, **kw)
            res[name] = run_grade(per_leg, slopes, tfm, _self_args(str(Path(td) / name)), arms=["A", "B", "C"], omitted={})
            print(f"  [{name}] {res[name]['note']}")
        check("planted arm x state interaction is recovered (PASS)", res["planted"]["verdict"] == "pass")
        sh = res["shuffled"]["measurement"]["chooser"]["vs_best_fixed"]
        check("shuffled state finds nothing (not PASS, CI lower <= 0)", res["shuffled"]["verdict"] != "pass" and sh["ci95"][0] <= 0.0, str(sh["ci95"]))
        check("no interaction at all finds nothing", res["null"]["verdict"] != "pass")
        pl = res["planted"]["measurement"]["chooser"]
        check("planted: chooser uses both B and C (state-keyed, not a fixed arm)", pl["chooser_arm_share"]["B"] > 0.2 and pl["chooser_arm_share"]["C"] > 0.2, str(pl["chooser_arm_share"]))
        per_leg, slopes = synthetic(1400, planted=True, shuffle=False, drop_frac=0.5)
        r = run_grade(per_leg, slopes, tfm, _self_args(str(Path(td) / "drop")), arms=["A", "B", "C"], omitted={})
        check("a lever that drops entries -> excluded share reported and INDETERMINATE", r["verdict"] == "indeterminate" and r["measurement"]["entry_set_agreement"]["excluded_share"] > 0.10)
        per_leg, slopes = synthetic(400, planted=True, shuffle=False)
        r = run_grade(per_leg, slopes, tfm, _self_args(str(Path(td) / "small")), arms=["A", "B", "C"], omitted={})
        check("< 600 joined trades -> INDETERMINATE", r["verdict"] == "indeterminate" and "n_floor" in r["note"])
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_args(ap)
    a = ap.parse_args(argv)
    if not a.leg:
        ap.error("--leg is required")
    if a.from_emits:
        run_from_emits(a)
    else:
        if not a.arm:
            ap.error("--arm is required (or --from-emits)")
        run_harness(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
