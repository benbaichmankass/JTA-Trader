#!/usr/bin/env python3
# wiring: manual-only - run by the research queue unit on node P1-Q11-path-metric-giveback (research-script-run.yml, emitted by queue_replenish once chain_verdict lands); otherwise a session runs it by hand.
"""P1-Q11 rung 1: do in-trade PATH metrics at bar k predict later giveback? (a LABEL study, never a lever)

Operator idea (IDEAS.md 2026-10-21; the motivating case was the live ADA trade's swings): chop, the
Kaufman efficiency ratio and the MAE/MFE path shape, measured k bars after entry, may say which trades
will hand back their open profit -- beyond what bars-in-trade and current R already say.

What it does, per ``--leg`` (config-exact, the same argv the evidence builder and
``exit_lever_ablation.py`` run, via ``regime_debt_matrix.build_harness_cmd``):

1. Fetch the leg's public candles for the pinned window (``exit_lever_ablation.fetch_candles``) and run
   its harness once with ``--emit-paths`` (``scripts/research/harness_emit.PathRecorder``): one row per
   (trade, bar), direction-signed R, the leg's own trail/TP/levers.
2. For every trade STILL OPEN after bar ``k`` (k is fixed by the unit before the run), compute from bars
   1..k only (nothing after bar k is read into a feature):

   * baseline  ``open_r_k``, ``peak_r_k``, ``bars_since_peak_k`` (k itself is constant);
   * ``chop_k``   -- Choppiness index over bars 1..k in signed-R space:
                     ``log10(sum TR_i / (max fav - min adv)) / log10(k)``, TR_i on (fav_i, adv_i, c_{i-1}),
                     c_0 = 0 (the entry);
   * ``er_k``     -- Kaufman efficiency ratio ``|c_k| / sum |c_i - c_{i-1}|``;
   * ``shape_k``  -- MFE share ``peak_r_k / (peak_r_k + mae_r_k)`` (1 = never went against; 0 = only did).
   * ``early_k``  -- where the peak sits: ``1 - bars_since_peak_k / k`` (1 = peaked on bar k, 0 = on bar 1).

3. Label (truncation-honest -- the harness's own exit, never a re-simulated barrier):
   ``giveback = peak_r_final - exit_r`` (peak-to-exit R on the trade's own final path row), and the
   binary ``big = giveback >= q``, q the ``--big-quantile`` of the TRAINING folds' giveback (re-derived per
   fold, so the threshold never sees the held-out fold; a fixed R bar degenerates -- on a 6-ATR trail
   nearly every trade gives back >= 1 R, MEASURED on the smoke run).
4. Grade out-of-sample by CALENDAR fold (``--folds``, a trade binned by its entry bar's timestamp):
   fit on the other folds, score the held-out fold. Models are closed-form ridge (continuous label) and a
   Newton-step logistic (binary label), both numpy only, both on standardised features; the BASELINE model
   uses the three baseline features, the FULL model adds the four path metrics. Statistics:
   ``r2_gain = R2_oos(full) - R2_oos(base)`` and ``ll_gain = logloss_oos(base) - logloss_oos(full)``,
   pooled over every held-out prediction and per fold.

Decision (the unit's, passed as flags, never defaults chosen here) -- per leg and pooled over legs:
  INDETERMINATE if n (trades open at k) < ``--n-floor``;
  PASS iff ``r2_gain >= --min-r2-gain`` OR ``ll_gain >= --min-ll-gain``, AND the same statistic is > 0 in
       at least ``--fold-majority`` of ``--folds`` folds;
  FAIL otherwise. A PASS opens rung 2 (the lever arm); it is never a config change.

Honesty notes: harness paths are not live paths (P2-Q3.1's live-ledger read was INDETERMINATE on n, which
is why rung 1 runs here). Features are computed on bars 1..k only and the label on the trade's own exit;
a trade that exits at or before bar k is outside the population and counted as ``n_exited_by_k``. Nothing
here edits config or places an order. Tier-1 research tooling; writes only under ``--out``.

    python3 scripts/research/path_metric_giveback.py --leg trend_donchian_eth_4h --leg ada_pullback_2h \\
        --k 6 --days 2330 --start 2020-07-01 --end "2026-10-15 23:59" --folds 6 --fold-majority 4 \\
        --n-floor 100 --min-r2-gain 0.02 --min-ll-gain 0.01 --big-quantile 0.5 --out /tmp/out

``--self-test`` plants a giveback signal in synthetic paths and checks both directions.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "scripts" / "research", REPO / "scripts" / "ops", REPO / "scripts", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BASE_FEATURES = ("open_r_k", "peak_r_k", "bars_since_peak_k")
PATH_FEATURES = ("chop_k", "er_k", "shape_k", "early_k")
VERDICTS = ("pass", "fail", "indeterminate")


# ── features ────────────────────────────────────────────────────────────────
def path_features(rows: list[dict[str, Any]], k: int) -> dict[str, Any] | None:
    """Features from bars 1..k of ONE trade's ordered path rows, or None if it exited by bar k.

    ``rows`` are harness_path_v1 rows for one trade sorted by bar_offset. The trade is in the population
    only when bar k exists and is NOT its exit bar (a decision at bar k's close must still have a trade)."""
    head = [r for r in rows if 1 <= int(r["bar_offset"]) <= k]
    if len(head) < k or any(r.get("is_exit") for r in head):
        return None
    last = head[-1]
    prev_c, tr_sum, moves = 0.0, 0.0, 0.0
    hi, lo = -math.inf, math.inf
    for r in head:
        fav, adv, c = float(r["fav_r"]), float(r["adv_r"]), float(r["c_r"])
        tr_sum += max(fav, prev_c) - min(adv, prev_c)
        moves += abs(c - prev_c)
        hi, lo = max(hi, fav, 0.0), min(lo, adv, 0.0)
        prev_c = c
    rng = hi - lo
    chop = (math.log10(tr_sum / rng) / math.log10(k)) if (k > 1 and rng > 0 and tr_sum > 0) else 0.0
    er = abs(prev_c) / moves if moves > 0 else 0.0
    peak, mae = float(last["peak_r"]), float(last["mae_r"])
    shape = peak / (peak + mae) if (peak + mae) > 0 else 0.5
    bsp = int(last["bars_since_peak"])
    return {"open_r_k": float(last["open_r"]), "peak_r_k": peak, "bars_since_peak_k": float(bsp),
            "chop_k": chop, "er_k": er, "shape_k": shape, "early_k": 1.0 - min(bsp, k) / k}


def giveback_label(rows: list[dict[str, Any]]) -> float:
    """peak-to-exit R on the trade's own final row (the harness's exit, never re-simulated)."""
    end = rows[-1]
    return max(0.0, float(end["peak_r"]) - float(end["open_r"]))


def build_table(path_rows: list[dict[str, Any]], k: int) -> tuple[list[dict[str, Any]], int, int]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in path_rows:
        by.setdefault(r["trade_key"], []).append(r)
    table, exited, total = [], 0, 0
    for key, rows in by.items():
        rows.sort(key=lambda r: int(r["bar_offset"]))
        total += 1
        f = path_features(rows, k)
        if f is None:
            exited += 1
            continue
        table.append({"trade_key": key, "entry_ts": key.split("|")[2], **f, "giveback": giveback_label(rows)})
    return table, exited, total


# ── models (numpy only: the runner installs numpy/pandas, no sklearn) ───────
def _std(xtr, xte):
    mu, sd = xtr.mean(axis=0), xtr.std(axis=0)
    sd[sd == 0] = 1.0
    return (xtr - mu) / sd, (xte - mu) / sd


def _ridge(xtr, ytr, xte, lam: float = 1.0):
    import numpy as np
    a = np.c_[np.ones(len(xtr)), xtr]
    reg = lam * np.eye(a.shape[1])
    reg[0, 0] = 0.0
    w = np.linalg.solve(a.T @ a + reg, a.T @ ytr)
    return np.c_[np.ones(len(xte)), xte] @ w


def _logit(xtr, ytr, xte, lam: float = 1.0, iters: int = 50):
    import numpy as np
    a = np.c_[np.ones(len(xtr)), xtr]
    w = np.zeros(a.shape[1])
    reg = lam * np.eye(a.shape[1])
    reg[0, 0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(a @ w, -30, 30)))
        g = a.T @ (p - ytr) + reg @ w
        h = (a * (p * (1 - p))[:, None]).T @ a + reg + 1e-9 * np.eye(a.shape[1])
        step = np.linalg.solve(h, g)
        w -= step
        if float(np.abs(step).max()) < 1e-8:
            break
    return 1.0 / (1.0 + np.exp(-np.clip(np.c_[np.ones(len(xte)), xte] @ w, -30, 30)))


def _r2(y, yhat, ybar):
    ss = float(((y - ybar) ** 2).sum())
    return 1.0 - float(((y - yhat) ** 2).sum()) / ss if ss > 0 else 0.0


def _ll(y, p):
    import numpy as np
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def fold_of(entry_ts: list[Any], folds: int) -> list[int]:
    import pandas as pd
    t = pd.to_datetime(pd.Series(entry_ts), utc=True)
    lo, hi = t.min(), t.max()
    if lo == hi:
        return [0] * len(t)
    span = (hi - lo) / folds
    return [min(folds - 1, int((x - lo) / span)) for x in t]


def grade_table(table: list[dict[str, Any]], *, folds: int, fold_majority: int, n_floor: int,
                min_r2_gain: float, min_ll_gain: float, big_quantile: float) -> dict[str, Any]:
    import numpy as np
    n = len(table)
    out: dict[str, Any] = {"n": n, "n_floor": n_floor, "folds": folds, "fold_majority": fold_majority,
                           "min_r2_gain": min_r2_gain, "min_ll_gain": min_ll_gain, "big_quantile": big_quantile}
    if n < n_floor:
        return {**out, "verdict": "indeterminate", "label": "underpowered",
                "why": f"{n} trades open at k < n_floor {n_floor}"}
    y = np.array([t["giveback"] for t in table], dtype=float)
    yb = np.full(n, np.nan)
    xb = np.array([[t[f] for f in BASE_FEATURES] for t in table], dtype=float)
    xf = np.array([[t[f] for f in BASE_FEATURES + PATH_FEATURES] for t in table], dtype=float)
    fid = np.array(fold_of([t["entry_ts"] for t in table], folds))
    pb, pf = np.full(n, np.nan), np.full(n, np.nan)
    qb, qf = np.full(n, np.nan), np.full(n, np.nan)
    per_fold = []
    for f in range(folds):
        te, tr = fid == f, fid != f
        if te.sum() == 0 or tr.sum() < 10:
            per_fold.append({"fold": f, "n": int(te.sum()), "usable": False})
            continue
        a, b = _std(xb[tr], xb[te])
        pb[te] = _ridge(a, y[tr], b)
        c, d = _std(xf[tr], xf[te])
        pf[te] = _ridge(c, y[tr], d)
        thr = float(np.quantile(y[tr], big_quantile))
        ytr_b = (y[tr] >= thr).astype(float)
        yb[te] = (y[te] >= thr).astype(float)
        two = len(set(ytr_b.tolist())) == 2
        qb[te] = _logit(a, ytr_b, b) if two else ytr_b.mean()
        qf[te] = _logit(c, ytr_b, d) if two else ytr_b.mean()
        ybar = float(y[tr].mean())
        per_fold.append({"fold": f, "n": int(te.sum()), "usable": True,
                         "r2_base": round(_r2(y[te], pb[te], ybar), 4), "r2_full": round(_r2(y[te], pf[te], ybar), 4),
                         "ll_base": round(_ll(yb[te], qb[te]), 4), "ll_full": round(_ll(yb[te], qf[te]), 4)})
    ok = ~np.isnan(pb)
    ybar_all = float(y[ok].mean())
    r2b, r2f = _r2(y[ok], pb[ok], ybar_all), _r2(y[ok], pf[ok], ybar_all)
    llb, llf = _ll(yb[ok], qb[ok]), _ll(yb[ok], qf[ok])   # yb is defined exactly where pb is
    usable = [p for p in per_fold if p["usable"]]
    r2_wins = sum(1 for p in usable if p["r2_full"] - p["r2_base"] > 0)
    ll_wins = sum(1 for p in usable if p["ll_base"] - p["ll_full"] > 0)
    r2_gain, ll_gain = r2f - r2b, llb - llf
    passes_r2 = r2_gain >= min_r2_gain and r2_wins >= fold_majority
    passes_ll = ll_gain >= min_ll_gain and ll_wins >= fold_majority
    verdict = "pass" if (passes_r2 or passes_ll) else "fail"
    return {**out, "verdict": verdict, "label": ("path_metrics_predict_giveback" if verdict == "pass"
                                                 else "no_gain_over_bars_and_r"),
            "why": (f"OOS R2 base {r2b:.4f} full {r2f:.4f} (gain {r2_gain:+.4f}, {r2_wins}/{len(usable)} folds); "
                    f"log-loss base {llb:.4f} full {llf:.4f} (gain {ll_gain:+.4f}, {ll_wins}/{len(usable)} folds)"),
            "r2_base": round(r2b, 4), "r2_full": round(r2f, 4), "r2_gain": round(r2_gain, 4),
            "ll_base": round(llb, 4), "ll_full": round(llf, 4), "ll_gain": round(ll_gain, 4),
            "r2_fold_wins": r2_wins, "ll_fold_wins": ll_wins, "usable_folds": len(usable),
            "big_share": round(float(np.nanmean(yb)), 4), "giveback_mean": round(float(y.mean()), 4),
            "per_fold": per_fold}


# ── harness run ─────────────────────────────────────────────────────────────
def run_leg_paths(leg: str, base: dict[str, Any], *, days: int, start: str | None, end: str | None,
                  wd: Path, data_csv: str | None, non_crypto_source: str) -> tuple[list[dict[str, Any]], dict]:
    import exit_lever_ablation as ela
    csv = data_csv or str(wd / f"{leg}__data.csv")
    feed: dict[str, Any] = {"resample": base.get("timeframe"), "source": "explicit --data-csv"}
    if not data_csv:
        feed = ela.fetch_candles(leg, base, days, csv, non_crypto_source=non_crypto_source)
    emit, jout, paths = (str(wd / f"{leg}__trades.jsonl"), str(wd / f"{leg}__bt.json"),
                         str(wd / f"{leg}__paths.jsonl"))
    argv, _omitted = ela.build_arm_argv(leg, base, csv, str(feed["resample"]), emit, jout, [], start, end)
    argv += ["--emit-paths", paths]
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{leg}: harness exit {r.returncode}: {r.stderr[-1500:]}")
    rows = [json.loads(ln) for ln in open(paths, encoding="utf-8") if ln.strip()]
    shown = [("<data>" if t == csv else t) for t in argv]
    return rows, {"feed": feed, "argv": shown, "bt": json.loads(Path(jout).read_text())}


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", action="append", required=True)
    ap.add_argument("--k", type=int, required=True, help="bars after entry at which features are read")
    ap.add_argument("--days", type=int, default=2330)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--data-csv", default=None, help="one candle CSV for every leg (tests)")
    ap.add_argument("--non-crypto-source", choices=("auto", "dukascopy"), default="auto")
    ap.add_argument("--folds", type=int, required=True)
    ap.add_argument("--fold-majority", type=int, required=True)
    ap.add_argument("--n-floor", type=int, required=True)
    ap.add_argument("--min-r2-gain", type=float, required=True)
    ap.add_argument("--min-ll-gain", type=float, required=True)
    ap.add_argument("--big-quantile", type=float, required=True,
                    help="binary label: giveback >= this quantile of the TRAINING folds' giveback")
    ap.add_argument("--out", required=True)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.k < 2 or a.folds < 2 or not 1 <= a.fold_majority <= a.folds or not 0.0 < a.big_quantile < 1.0:
        print("ERROR: need --k >= 2, --folds >= 2, 1 <= --fold-majority <= --folds, 0 < --big-quantile < 1",
              file=sys.stderr)
        return 2
    import yaml
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    legs = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    legs = legs.get("strategies", legs)
    kw = dict(folds=a.folds, fold_majority=a.fold_majority, n_floor=a.n_floor, min_r2_gain=a.min_r2_gain,
              min_ll_gain=a.min_ll_gain, big_quantile=a.big_quantile)
    wd = Path(tempfile.mkdtemp(prefix="path_metric_giveback_"))
    per_leg, pooled, runs = {}, [], {}
    for leg in a.leg:
        base = legs.get(leg)
        if not isinstance(base, dict):
            print(f"ERROR: leg {leg!r} not in config/strategies.yaml", file=sys.stderr)
            (out / "failure.json").write_text(json.dumps({"stage": "config", "leg": leg}) + "\n")
            return 2
        try:
            rows, meta = run_leg_paths(leg, base, days=a.days, start=a.start, end=a.end, wd=wd,
                                       data_csv=a.data_csv, non_crypto_source=a.non_crypto_source)
        except Exception as exc:  # noqa: BLE001  # allow-silent: not silent -- the cause is printed, written to failure.json and the run exits 1
            print(f"ERROR: {exc}", file=sys.stderr)
            (out / "failure.json").write_text(json.dumps({"stage": "harness", "leg": leg, "error": str(exc)},
                                                         indent=2) + "\n")
            return 1
        table, exited, total = build_table(rows, a.k)
        g = grade_table(table, **kw)
        per_leg[leg] = {**g, "n_trades": total, "n_exited_by_k": exited, "cost_policy":
                        {f: meta["bt"].get(f) for f in ("fee_bps_roundtrip", "slippage_bps_roundtrip",
                                                        "funding_bps_per_window")}}
        runs[leg] = {"argv": meta["argv"], "feed": meta["feed"]}
        pooled += [{**t, "leg": leg} for t in table]
        (out / f"{leg}__table.jsonl").write_text("".join(json.dumps(t) + "\n" for t in table), encoding="utf-8")
    gp = grade_table(pooled, **kw)
    verdict = gp["verdict"]
    pop = (f"{len(pooled)} harness trades still open after bar {a.k} across {a.leg} "
           f"({sum(p['n_trades'] for p in per_leg.values())} trades in all), window {a.start} .. {a.end}, "
           "config-exact, net of the harness's venue-aware cost stack; features from bars 1..k only, label = "
           "the trade's own peak-to-exit R")
    rec = {"verdict": verdict, "read_state": "measured", "population": pop, "n": len(pooled),
           "measurement": {"k": a.k, "pooled": gp, "per_leg": per_leg, "runs": runs,
                           "features": {"base": BASE_FEATURES, "path": PATH_FEATURES}},
           "note": f"{verdict.upper()} / {gp.get('label')}: {gp.get('why')}"}
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "why": gp.get("why"),
                      "per_leg": {k: (v["verdict"], v.get("why")) for k, v in per_leg.items()}}, indent=1))
    return 0


# ── self-test: planted signal both ways, no network ─────────────────────────
def _synthetic(n_trades: int, planted: bool, seed: int = 3) -> list[dict[str, Any]]:
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    rows = []
    t0 = pd.Timestamp("2021-01-01", tz="UTC")
    for i in range(n_trades):
        choppy = rng.random() < 0.5
        c, peak, mae = 0.0, 0.0, 0.0
        key = f"leg|SYM|{t0 + pd.Timedelta(days=3 * i)}|long"
        nb = 20
        for b in range(1, nb + 1):
            step = rng.normal(0.0, 0.6 if choppy else 0.15) + (0.0 if choppy else 0.12)
            c += step
            fav, adv = c + abs(rng.normal(0, 0.1)), c - abs(rng.normal(0, 0.1))
            peak, mae = max(peak, fav), max(mae, -min(adv, 0.0))
            is_exit = b == nb
            open_r = c
            if is_exit:
                # planted: choppy paths hand back far more of their peak; null: the giveback is drawn
                # independently of the path, so no feature can carry it
                open_r = peak - ((rng.uniform(1.5, 2.5) if choppy else rng.uniform(0.0, 0.4)) if planted
                                 else rng.uniform(0.0, 2.5))
            rows.append({"trade_key": key, "bar_offset": b, "c_r": c, "fav_r": fav, "adv_r": adv,
                         "open_r": open_r, "peak_r": peak, "mae_r": mae, "bars_since_peak": 0,
                         "is_exit": is_exit})
    return rows


def _self_test() -> int:
    fails = []

    def check(label: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    kw = dict(folds=4, fold_majority=3, n_floor=50, min_r2_gain=0.02, min_ll_gain=0.01, big_quantile=0.5)
    t, ex, tot = build_table(_synthetic(240, planted=True), k=6)
    g = grade_table(t, **kw)
    check(f"planted signal -> pass ({g['why']})", g["verdict"] == "pass")
    t2, _, _ = build_table(_synthetic(240, planted=False), k=6)
    g2 = grade_table(t2, **kw)
    check(f"no signal -> fail ({g2['why']})", g2["verdict"] == "fail")
    g3 = grade_table(t[:20], **kw)
    check("thin -> indeterminate", g3["verdict"] == "indeterminate")
    rows = [{"trade_key": "x|S|2021-01-01 00:00:00+00:00|long", "bar_offset": b, "c_r": 0.1 * b, "fav_r": 0.1 * b,
             "adv_r": 0.1 * b - 0.05, "open_r": 0.1 * b, "peak_r": 0.1 * b, "mae_r": 0.0, "bars_since_peak": 0,
             "is_exit": b == 4} for b in range(1, 5)]
    check("a trade that exits by bar k is outside the population", path_features(rows, 4) is None)
    f = path_features(rows, 3)
    check("a straight path has ER 1 and shape 1", f is not None and abs(f["er_k"] - 1.0) < 1e-9
          and abs(f["shape_k"] - 1.0) < 1e-9)
    print("self-test:", "FAIL" if fails else "ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
