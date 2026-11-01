#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261101-c692-02.yaml (BRACKETS decision model, lane ML-DECISION-MODELS); spec docs/research/ml-decision-models-2026-11-01/DESIGN.md section 3
"""BRACKETS decision model: choose SL x TP at each ENTRY decision, pooled across symbols, scored COMPOSED (Tier-1 research).

Spec: docs/research/ml-decision-models-2026-11-01/DESIGN.md section 3 (rule RULE-RQ20261101-c692-02-BRACKETS, registered
before any run). Reuses ``ml_decision_entry`` for data, features, the first-passage / tie / gap / cost rules, the frozen
ENTRY model recipe and its dev-chosen tau (read from the ENTRY run's summary.json; never re-chosen here).

* Cells: SL in ``SL_GRID`` x ATR14, TP in ``TP_GRID`` x ATR14, 24 h time stop (24 cells). Net R is per unit of the CHOSEN
  stop; the RiskManager sizes to the stop distance, so cells are comparable in R (no sizing here).
* Model: one LightGBM regressor on (features, side, sl, tp) -> net R, trained on a fixed 1-in-``TRAIN_STRIDE``
  subsample of the dev decision rows x 24 cells x 2 sides; argmax over cells for the ENTRY side.
* Composed policy: at each free decision bar ENTRY picks the side (prediction > tau); BRACKETS picks the cell; the
  symbol is busy until that cell's exit bar.
* Comparators (reported, never gating): the 2/3 reference bracket on the same mechanics, the best single static cell
  chosen on the DEV walk-forward only, and a random cell per decision (200 draws).

    python3 scripts/research/ml_decision_brackets.py run --entry-summary <entry out>/summary.json --cache /tmp/k --out /tmp/o
    python3 scripts/research/ml_decision_brackets.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402

SCHEMA = "ml_decision_brackets/1"
SL_GRID = [1.0, 1.5, 2.0, 3.0]
TP_GRID = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
CELLS = [(s, t) for s in SL_GRID for t in TP_GRID]
REF_CELL = (2.0, 3.0)
TRAIN_STRIDE = 4
RANDOM_DRAWS = 200


def cell_labels(df: pd.DataFrame, lab: pd.DataFrame) -> dict:
    """net R and bars for every (side, cell) on the decision rows ``lab`` of one symbol."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
    cand = lab["i"].to_numpy()
    win = cand[:, None] + np.arange(1, E.HORIZON_H + 1)[None, :]
    O, Hh, L, C = o[win], h[win], l[win], c[win]
    entry, a = O[:, 0], lab["atr"].to_numpy()
    t_entry_s = t_ns[cand + 1] / 1e9
    out = {}
    for side, sname in ((1, "long"), (-1, "short")):
        for k, (sl, tp) in enumerate(CELLS):
            px, j, _ = E.bracket_outcome(O, Hh, L, C, entry, a, side, sl_atr=sl, tp_atr=tp)
            risk = sl * a
            gross = side * (px - entry) / risk
            fee, slip, fund = E._cost_r(entry, px, risk, t_entry_s, t_ns[cand + j] / 1e9 + 3600.0)
            out[f"net_{sname}_{k}"] = (gross - fee - slip - fund).astype(np.float32)
            out[f"bars_{sname}_{k}"] = j.astype(np.int16)
    return out


def build(cache: Path, symbols: list[str]) -> pd.DataFrame:
    tab = E.build_table(cache, symbols)
    parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        cl = pd.DataFrame(cell_labels(df, g), index=g.index)
        parts.append(cl)
    return tab.join(pd.concat(parts))


def _stack(rows: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    X, y = [], []
    for side, sname in ((1, "long"), (-1, "short")):
        for k, (sl, tp) in enumerate(CELLS):
            x = rows[E.FEATURES].copy()
            x["side"], x["sl"], x["tp"] = side, sl, tp
            X.append(x)
            y.append(rows[f"net_{sname}_{k}"].to_numpy())
    return pd.concat(X, ignore_index=True), np.concatenate(y)


def fit_brackets(train: pd.DataFrame):
    import lightgbm as lgb
    sub = train.iloc[::TRAIN_STRIDE]
    X, y = _stack(sub)
    m = lgb.LGBMRegressor(**E.LGB_PARAMS)
    m.fit(X, y)
    return m


def predict_cells(m, rows: pd.DataFrame, side_arr: np.ndarray) -> np.ndarray:
    """(n, 24) predicted net R for each row's ENTRY side."""
    preds = np.empty((len(rows), len(CELLS)), dtype=np.float32)
    base = rows[E.FEATURES].copy()
    base["side"] = side_arr
    for k, (sl, tp) in enumerate(CELLS):
        x = base.copy()
        x["sl"], x["tp"] = sl, tp
        preds[:, k] = m.predict(x)
    return preds


def composed(test: pd.DataFrame, p_long, p_short, tau: float, chooser) -> pd.DataFrame:
    """ENTRY picks bar + side; ``chooser(row_pos, side) -> cell index`` picks the cell. One position per symbol."""
    t = test.assign(pos_ix=np.arange(len(test)), p_long=p_long, p_short=p_short).sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for row in g.itertuples(index=False):
            if row.i <= busy:
                continue
            side = "long" if row.p_long >= row.p_short else "short"
            if (row.p_long if side == "long" else row.p_short) <= tau:
                continue
            k = chooser(row.pos_ix, side)
            out.append((sym, row.ts, side, k, float(getattr(row, f"net_{side}_{k}"))))
            busy = row.i + int(getattr(row, f"bars_{side}_{k}"))
    return pd.DataFrame(out, columns=["symbol", "ts", "side", "cell", "net_r"])


def _s(tk: pd.DataFrame) -> dict:
    if tk.empty:
        return {"n": 0, "mean_net_r": None, "n_symbols": 0}
    return {"n": int(len(tk)), "mean_net_r": float(tk.net_r.mean()), "sum_net_r": float(tk.net_r.sum()),
            "n_symbols": int(tk.symbol.nunique())}


def run(a) -> int:
    t0 = time.time()
    entry_sum = json.loads(Path(a.entry_summary).read_text())
    tau = entry_sum["walk_forward"]["tau_star"]
    if tau is None:
        raise RuntimeError("ENTRY summary has no tau_star; BRACKETS composes on the frozen ENTRY policy")
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    syms = E.universe()
    E.fetch(cache, syms)
    tab = build(cache, syms)
    print(f"rows={len(tab)} t={time.time()-t0:.0f}s tau={tau}", flush=True)
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    ref_k = CELLS.index(REF_CELL)
    # dev walk-forward: ENTRY decisions per fold under each STATIC cell -> best static cell (dev only)
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [hs]
    static_dev = {k: [] for k in range(len(CELLS))}
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        test = dev[(dev.ts >= lo) & (dev.ts < hi - pd.Timedelta(hours=E.HORIZON_H + 1))]
        pl, ps = E.fit_predict(E.purge_train(dev, lo), test)
        for k in range(len(CELLS)):
            static_dev[k].append(composed(test, pl, ps, tau, lambda pos, side, k=k: k))
        print(f"dev fold {lo.date()} done t={time.time()-t0:.0f}s", flush=True)
    dev_means = {k: float(pd.concat(v).net_r.mean()) for k, v in static_dev.items()}
    best_static = max(dev_means, key=lambda k: dev_means[k])
    # held-out: ENTRY final fit + BRACKETS final fit
    train = E.purge_train(dev, hs)
    test = tab[tab.ts >= hs].reset_index(drop=True)
    pl, ps = E.fit_predict(train, test)
    side_arr = np.where(pl >= ps, 1, -1)
    m = fit_brackets(train)
    P = predict_cells(m, test, side_arr)
    model_tk = composed(test, pl, ps, tau, lambda pos, side: int(np.argmax(P[pos])))
    ref_tk = composed(test, pl, ps, tau, lambda pos, side: ref_k)
    static_tk = composed(test, pl, ps, tau, lambda pos, side: best_static)
    rng = np.random.default_rng(E.SEED)
    rand = [float(composed(test, pl, ps, tau, lambda pos, side: int(rng.integers(len(CELLS)))).net_r.mean())
            for _ in range(RANDOM_DRAWS)]
    ms = _s(model_tk)
    if ms["n"] < E.N_FLOOR or ms["n_symbols"] < E.SYMBOL_FLOOR:
        v, why = "indeterminate", f"composed held-out n={ms['n']} / symbols={ms['n_symbols']} below floor"
    elif ms["mean_net_r"] >= 0:
        v, why = "pass", f"composed held-out mean net R per decision {ms['mean_net_r']:+.4f} >= 0 at n={ms['n']}"
    else:
        v, why = "fail", f"composed held-out mean net R per decision {ms['mean_net_r']:+.4f} < 0 at n={ms['n']}"
    cell_mix = {f"{CELLS[k][0]}/{CELLS[k][1]}": int(c) for k, c in model_tk.cell.value_counts().items()} if len(model_tk) else {}
    meas = {"composed_model": ms, "reference_2_3": _s(ref_tk), "best_static_dev": {"cell": CELLS[best_static], **_s(static_tk)},
            "dev_static_means": {f"{CELLS[k][0]}/{CELLS[k][1]}": round(x, 4) for k, x in dev_means.items()},
            "random_cell": {"draws": RANDOM_DRAWS, "mean_of_means": float(np.mean(rand)), "p95": float(np.percentile(rand, 95))},
            "model_cell_mix": cell_mix, "entry_tau": tau, "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps({"schema": SCHEMA, "unit": a.unit, "verdict": v, "why": why, **meas},
                                                 indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": ms["n"], "measurement": meas, "note": why,
          "population": (f"BRACKETS composed with the frozen ENTRY policy (tau {tau}), held-out {E.HOLDOUT_START}..{E.END}, "
                         f"60-perp universe bp2-f4271084b120, 24 SL x TP cells, full cost stack")}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


def _self_test() -> None:
    assert len(CELLS) == 24 and REF_CELL in CELLS
    n = 6
    test = pd.DataFrame({"symbol": ["A"] * n, "i": [0, 4, 8, 40, 44, 48], "ts": pd.to_datetime(["2025-11-01"] * n, utc=True)})
    for s in ("long", "short"):
        for k in range(len(CELLS)):
            test[f"net_{s}_{k}"] = float(k)
            test[f"bars_{s}_{k}"] = 10
    tk = composed(test, np.ones(n), np.zeros(n), 0.0, lambda pos, side: 5)
    assert list(tk.net_r) == [5.0, 5.0], tk  # i=4,8 blocked by the hold from i=0 (busy to 10); 44,48 by i=40
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--entry-summary", default="")
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_decision_brackets_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
