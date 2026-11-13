#!/usr/bin/env python3
# wiring: .github/workflows/feature-impact.yml (weekly + workflow_dispatch) + tests/test_feature_impact.py
"""FEATURE-IMPACT-MAP v0 -- the long table of per-feature impact, M1 (model-internal importance) only.

Design: docs/design/ui-workplan-2026-11.md section 15 (row FEATURE-IMPACT-MAP). Off-VM, no Claude, no network:
reads the committed model artifacts and writes ``comms/feature_impact/<run_id>.jsonl`` plus
``comms/feature_impact/latest.json`` (a pointer and the run's summary).

M1 SOURCES (v0): every ``ml/served/*/model.json`` and ``ml/candidates/*/model.json`` whose ``booster_txt`` holds
LightGBM model text (a string, a ``{side: text}`` map, or ``{side: [text, ...]}`` for a seed ensemble).
  * ``split_share`` -- the booster's split count per feature / total splits. Parsed from the text's
    ``feature_importances:`` block, so it needs no lightgbm import. That block LISTS ONLY FEATURES WITH >= 1 SPLIT;
    a feature in the model's ``features`` list with no split is written as value 0.0, read_state ``measured``
    (zero splits is a measured fact, not a could-not-look).
  * ``gain_share`` -- total gain per feature / total gain, via ``lightgbm.Booster(model_str=...)``. If lightgbm is
    not importable the row is written with value null and read_state ``not_computed`` -- never 0.
  * Shares are normalised WITHIN one (model, side) booster set; a seed ensemble sums its members first.
  * Population: the model's own TRAINING population, pooled over its symbols (``symbol: "pooled"``). There is no
    per-symbol M1 in a pooled model; per-symbol impact is M2's job (rank IC, NOT in v0).

NOT IN v0 (stated, not hidden): M2 model-free rank IC per symbol/asset/timeframe (needs the pooled bar store
off-VM), M3 ablation (reuse fs01 results), the registry regime models whose importances live on the trainer VM
(``ml/offload-inbox/*/model_state.json``), and SHAP/permutation on OOF data. Each is a ``coverage.not_in_v0`` entry
in latest.json so a reader cannot mistake absence for zero impact.

No halting: a model whose artifact cannot be parsed gets one ``read_state: "not_computed"`` row with the reason
and the run continues. Exit 0 unless NO model could be read (then exit 1: a run over nothing is not a pass).

    python3 scripts/research/feature_impact.py --out-dir comms/feature_impact
    python3 scripts/research/feature_impact.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
STAGE_DIRS = (("ml/served", "served"), ("ml/candidates", "candidate"))
SCHEMA = "feature_impact/1"
_IMP_RE = re.compile(r"^feature_importances:\s*$")

#: Feature family by name (v0; the catalog id is ``ml_feature.<name>``). Unknown names -> "other", never dropped.
FAMILY_RULES: Tuple[Tuple[str, str], ...] = (
    (r"^(xs_rank_|breadth_|rel_vol$|btc_)", "cross_section"),
    (r"^(ret_\d+|rsi\d+|sret_\d+)$", "momentum"),
    (r"^(vol24|vol_ratio|atr_pct|atr_ratio)$", "volatility"),
    (r"^vol_z$", "volume"),
    (r"^range_pos_", "range_position"),
    (r"^(hour|dow)$", "calendar"),
    (r"^(side|bars_held|open_r|mfe_r|mae_r|dist_sl_atr)$", "position_state"),
    (r"^(spy_|qqq_|iwm_|tlt_|vixy_|rel_ret_spy$)", "market_context"),
    (r"^(log_return|log_return_lag_\d+)$", "momentum"),
    (r"^(rolling_log_return_vol|vol_bucket)$", "volatility"),
    (r"^(hour_of_day|dayofweek)$", "calendar"),
)


def feature_family(name: str) -> str:
    for pat, fam in FAMILY_RULES:
        if re.search(pat, name):
            return fam
    return "other"


def parse_split_counts(model_txt: str) -> Dict[str, int]:
    """The ``feature_importances:`` block of LightGBM model text -> {feature: split count}."""
    out: Dict[str, int] = {}
    on = False
    for line in model_txt.splitlines():
        if not on:
            on = bool(_IMP_RE.match(line))
            continue
        line = line.strip()
        if not line or "=" not in line or line.startswith("["):
            break
        k, _, v = line.rpartition("=")
        try:
            out[k] = out.get(k, 0) + int(v)
        except ValueError:
            break
    return out


def gain_totals(model_txt: str) -> Optional[Dict[str, float]]:
    """{feature: total gain} via lightgbm, or None when lightgbm is not importable."""
    try:
        import lightgbm as lgb  # noqa: PLC0415
    except Exception:  # allow-silent: absence is reported as read_state not_computed on every gain row
        return None
    try:
        b = lgb.Booster(model_str=model_txt)
        return {n: float(g) for n, g in zip(b.feature_name(), b.feature_importance(importance_type="gain"))}
    except Exception:  # allow-silent: an unloadable booster reports its gain rows as not_computed, splits still land
        return None


def booster_sets(model: Dict[str, Any]) -> Dict[str, List[str]]:
    """{side: [model_text, ...]} from ``booster_txt`` (str | {side: str} | {side: [str, ...]})."""
    b = model.get("booster_txt")
    if isinstance(b, str):
        return {"all": [b]}
    if isinstance(b, dict):
        return {str(s): (v if isinstance(v, list) else [v]) for s, v in b.items()}
    raise TypeError("booster_txt is neither text nor a {side: text} map")


def model_meta(model: Dict[str, Any], stage: str) -> Dict[str, Any]:
    br = model.get("bracket") or {}
    horizon = br.get("horizon_bars") or br.get("horizon_h") or model.get("horizon_h")
    eq = bool(model.get("pool_symbols")) or "EQ" in str(model.get("model_id", ""))
    return {"model_id": model.get("model_id"), "stage": stage,
            "ml_type": "tp_revision" if "tp-revision" in str(model.get("model_id")) else "entry",
            "asset_class": "us_etf" if eq else "crypto_perp",
            "venue": "alpaca" if eq else "bybit", "timeframe": "1h", "horizon_bars": horizon}


def rows_for_model(path: Path, stage: str, run_id: str, computed_at: str) -> List[Dict[str, Any]]:
    model = json.loads(path.read_text(encoding="utf-8"))
    meta = model_meta(model, stage)
    feats = [str(f) for f in (model.get("features") or [])]
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, **meta, "symbol": "pooled",
            "regime": "all", "source_artifact": str(path.relative_to(REPO)) if REPO in path.parents else str(path),
            "provenance": "MEASURED", "ci_low": None, "ci_high": None,
            "window_end": model.get("train_end_exclusive"), "n_obs": model.get("train_rows") or model.get("n_train")}
    out: List[Dict[str, Any]] = []
    for side, texts in booster_sets(model).items():
        splits: Dict[str, int] = {}
        gains: Optional[Dict[str, float]] = {}
        for t in texts:
            for k, v in parse_split_counts(t).items():
                splits[k] = splits.get(k, 0) + v
            g = gain_totals(t)
            if g is None or gains is None:
                gains = None
            else:
                for k, v in g.items():
                    gains[k] = gains.get(k, 0.0) + v
        names = feats or sorted(set(splits) | set(gains or {}))
        s_tot = float(sum(splits.values()))
        g_tot = float(sum(gains.values())) if gains else 0.0
        for f in names:
            row = {**base, "side": side, "n_boosters": len(texts), "feature_id": f"ml_feature.{f}", "feature": f,
                   "feature_family": feature_family(f)}
            out.append({**row, "measure": "split_share", "value": (splits.get(f, 0) / s_tot) if s_tot else None,
                        "raw": splits.get(f, 0), "read_state": "measured" if s_tot else "not_computed"})
            if gains is None:
                out.append({**row, "measure": "gain_share", "value": None, "raw": None, "read_state": "not_computed",
                            "reason": "lightgbm not importable, or the booster text did not load"})
            else:
                out.append({**row, "measure": "gain_share", "value": (gains.get(f, 0.0) / g_tot) if g_tot else None,
                            "raw": gains.get(f, 0.0), "read_state": "measured" if g_tot else "not_computed"})
    return out


# ── M2: model-free rank IC (FEATURE-IMPACT-MAP increment 1, 2026-11-11) ─────────────────────────────────────────────
#: The crypto decision-entry family (ml_decision_entry_v1 / v1r20261106 / v2 share these 20 features). Its research
#: harness ``scripts/research/ml_decision_entry.py::build_table`` builds the EXACT training features and the model's own
#: cost-adjusted label (net R of a 2 ATR stop / 3 ATR target bracket over 24 h, full cost stack) per 4-hourly decision
#: row, so M2 reuses it rather than re-deriving anything. v2 trains on a 2 / 4 bracket: its rows carry
#: ``label_note`` saying the IC label is the 2 / 3 recipe.
M2_FAMILY = {"family_id": "ml_decision_entry", "served": ("ml_decision_entry_v1", "ml_decision_entry_v1r20261106",
                                                          "ml_decision_entry_v2")}
M2_LABELS = ("net_long", "fwd_ret_24h")
M2_MIN_XS = 10        # symbols needed at a timestamp for a cross-sectional IC
M2_MIN_TS = 200       # decision rows needed for a per-symbol IC
M2_OVERLAP = 6        # 24 h label / 4 h decision step: labels overlap 6x, so effective n = n / 6 for the SE


def _spearman(a, b) -> Optional[float]:
    import numpy as np
    import pandas as pd
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 3:
        return None
    ra, rb = pd.Series(a[m]).rank().to_numpy(), pd.Series(b[m]).rank().to_numpy()
    if ra.std() < 1e-12 or rb.std() < 1e-12:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def m2_xs_ic(tab, feature: str, label: str, overlap: int = M2_OVERLAP, min_xs: int = M2_MIN_XS) -> Dict[str, Any]:
    """Cross-sectional rank IC per decision timestamp, then averaged. Returns the mean, t over timestamps, n
    timestamps, and per-calendar-quarter means. A feature constant across symbols at every timestamp is
    ``not_applicable`` (its cross-sectional IC does not exist), never 0."""
    import numpy as np
    ics, qs = [], []
    for ts, g in tab.groupby("ts"):
        if len(g) < min_xs:
            continue
        ic = _spearman(g[feature].to_numpy(float), g[label].to_numpy(float))
        if ic is not None:
            ics.append(ic)
            qs.append(f"{ts.year}Q{(ts.month - 1) // 3 + 1}")
    if not ics:
        return {"read_state": "not_applicable", "reason": "no timestamp with >= %d symbols and cross-sectional variance "
                "(a feature identical across symbols at a timestamp, e.g. hour / BTC context / breadth)" % min_xs}
    v = np.array(ics)
    # adjacent decision timestamps share 5 of 6 label hours (24 h label, 4 h step): effective n = n / M2_OVERLAP
    n_eff = len(v) / overlap
    se = float(v.std(ddof=1) / np.sqrt(n_eff)) if n_eff > 1 else None
    by_q: Dict[str, List[float]] = {}
    for q, x in zip(qs, ics):
        by_q.setdefault(q, []).append(x)
    qmeans = {q: float(np.mean(x)) for q, x in sorted(by_q.items())}
    sgn = np.sign(v.mean())
    return {"read_state": "measured", "value": float(v.mean()), "se": se, "n": int(len(v)),
            "t": (float(v.mean()) / se) if se else None,
            "sign_consistency_quarters": float(np.mean([np.sign(x) == sgn for x in qmeans.values()])) if qmeans else None,
            "by_quarter": qmeans}


M2_LABEL_NOTE = ("net_long = net R of the 2 ATR / 3 ATR / 24 h long bracket after the full cost stack (the v1 / v1r20261106 label; "
                 "v2 trains on a 2 / 4 bracket); fwd_ret_24h = raw 24 h log return. READ BOTH: net_long is in R, and cost in R = "
                 "cost_bps / stop distance, so volatility features rank net_long through cheaper cost per R, not direction (first run "
                 "2026-11-11: atr_pct IC +0.49 vs net_long, -0.08 vs fwd_ret_24h)")
M2_SE_BASIS = "rank_ic_xs: sd over timestamps / sqrt(n / %d) (overlapping 24 h labels on a 4 h step)" % M2_OVERLAP


def m2_rows(tab, run_id: str, computed_at: str, *, data_end: str, symbols_requested: int) -> List[Dict[str, Any]]:
    """Long-table rows for M2 over one decision table (features + labels per (ts, symbol))."""
    import numpy as np
    from scripts.research import ml_decision_entry as mde  # noqa: PLC0415
    tab = tab.copy()
    if "fwd_ret_24h" not in tab.columns:
        raise ValueError("decision table has no fwd_ret_24h column")
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "ml_family": M2_FAMILY["family_id"],
            "model_id": None, "served_models": list(M2_FAMILY["served"]), "stage": "family", "ml_type": "entry",
            "asset_class": "crypto_perp", "venue": "bybit (Binance USD-M proxy bars)", "timeframe": "1h",
            "horizon_bars": mde.HORIZON_H, "regime": "all", "provenance": "MEASURED", "window_end": data_end,
            "source_artifact": "scripts/research/ml_decision_entry.py::build_table",
            "label_note": "see coverage.m2.label_note",
            "se_basis": "see coverage.m2.se_basis"}
    out: List[Dict[str, Any]] = []
    n_sym = int(tab["symbol"].nunique())
    for f in mde.FEATURES:
        fam = feature_family(f)
        for label in M2_LABELS:
            row = {**base, "feature_id": f"ml_feature.{f}", "feature": f, "feature_family": fam, "label": label,
                   "side": "long" if label == "net_long" else "all"}
            xs = m2_xs_ic(tab, f, label)
            out.append({**row, "measure": "rank_ic_xs", "symbol": "pooled", "window": "all",
                        "n_obs": xs.get("n"), "n_symbols": n_sym, "symbols_requested": symbols_requested,
                        "value": xs.get("value"), "se": xs.get("se"), "t": xs.get("t"),
                        "ci_low": (xs["value"] - 1.96 * xs["se"]) if xs.get("se") else None,
                        "ci_high": (xs["value"] + 1.96 * xs["se"]) if xs.get("se") else None,
                        "sign_consistency_quarters": xs.get("sign_consistency_quarters"),
                        "read_state": xs["read_state"], **({"reason": xs["reason"]} if "reason" in xs else {})})
            for q, qv in (xs.get("by_quarter") or {}).items():
                out.append({**row, "measure": "rank_ic_xs", "symbol": "pooled", "window": q, "n_obs": None,
                            "value": qv, "se": None, "read_state": "measured"})
            for sym, g in tab.groupby("symbol"):
                ic = _spearman(g[f].to_numpy(float), g[label].to_numpy(float)) if len(g) >= M2_MIN_TS else None
                n_eff = len(g) / M2_OVERLAP
                se = (1.0 / np.sqrt(n_eff - 3)) if (ic is not None and n_eff > 3) else None
                out.append({**row, "measure": "rank_ic_ts", "symbol": sym, "window": "all", "n_obs": int(len(g)),
                            "value": ic, "se": se, "n_eff_div": M2_OVERLAP,
                            "read_state": "measured" if ic is not None else "not_computed",
                            **({} if ic is not None else {"reason": f"< {M2_MIN_TS} decision rows or no variance"})})
    return out


def m2_build_table(cache: Path, symbols: Optional[List[str]] = None):
    """Fetch (keyless Binance Vision 1h klines, cached) and build the decision table for the family's universe, with
    the cross-sectional context computed against the served model's own ``xs_reference`` set."""
    import numpy as np
    from scripts.research import ml_decision_entry as mde  # noqa: PLC0415
    ref = json.loads((REPO / "ml/served/ml_decision_entry_v2/model.json").read_text(encoding="utf-8")).get("xs_reference")
    syms = list(symbols or ref or mde.universe())
    report = mde.fetch(cache, syms)
    ok = [s for s in syms if (cache / f"{s}.pkl").exists()]
    xs = [s for s in (ref or ok) if s in ok]
    tab = mde.build_table(cache, ok, xs_symbols=xs if (ref and len(xs) == len(ref)) else None)
    # raw 24 h forward log return from the decision bar's close (the same bars build_table labelled)
    fwd = []
    for sym in ok:
        import pandas as pd  # noqa: PLC0415
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        c = np.log(df["close"].astype(float).to_numpy())
        f = np.full(len(c), np.nan)
        f[:-mde.HORIZON_H] = c[mde.HORIZON_H:] - c[:-mde.HORIZON_H]
        fwd.append(pd.DataFrame({"ts": pd.to_datetime(df["ts"], utc=True), "symbol": sym, "fwd_ret_24h": f}))
    import pandas as pd  # noqa: PLC0415
    tab = tab.merge(pd.concat(fwd), on=["ts", "symbol"], how="left")
    return tab, {"symbols_requested": len(syms), "symbols_built": int(tab["symbol"].nunique()), "fetch": report,
                 "xs_reference": "served v2 xs_reference" if (ref and len(xs) == len(ref)) else "the built symbols",
                 "data_end": str(tab["ts"].max())}


# ── M2 for the equity entry + regime families, and M3 drop-column ablation (FEATURE-IMPACT-MAP increment 2, 2026-11-12) ──
#: DEV-ONLY: every equity and ablation read stops at DEV_END (exclusive). The ENTRY-EQ confirming window (2025-07-15 ..)
#: and the crypto forward windows are never loaded here, so this job can never consume a holdout read.
DEV_END = "2025-07-01"
ABL_TRAIN_END = "2024-07-01"     # M3: train on rows before this (minus a 10 d purge), score [ABL_TRAIN_END, DEV_END)
ABL_PURGE_DAYS = 10
EQ_OVERLAP = 7                   # 24 RTH-bar label / ~3.5 RTH bars between 4h-aligned decisions: labels overlap ~7x
REGIME_M = 5                     # market_features forward_window_m (scripts/ops/build_trainer_datasets.sh passes 5)
REGIME_VOL_N = 20                # vol_window_n
REGIME_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")   # the symbols the btc-/eth-/sol-regime heads train on
REGIME_FEATURES = ["rolling_log_return_vol", "log_return", "log_return_lag_1", "log_return_lag_2", "hour_of_day", "dayofweek"]
CYCLIC = {"hour", "dow", "hour_of_day", "dayofweek"}
_CYC_NOTE = "cyclic / categorical feature: rank IC measures only a monotone association, so a 0 here is not 'no effect'"


def _r(x: Optional[float], nd: int = 5) -> Optional[float]:
    return None if x is None else round(float(x), nd)


REGIME_LABEL_NOTE = ("regime_label = forward_vol > vol_threshold (a function of forward_vol alone) and trend_regime_label keys off "
                     "the Kaufman efficiency ratio of the same forward window; both are measured here as the continuous quantity "
                     "(forward_vol = pstdev of the next %d 1h log returns; forward_er = |sum r| / sum |r|), which carries every "
                     "threshold. Features are re-derived past-only from the cached klines (vol_bucket is a monotone bucket of "
                     "rolling_log_return_vol and is not listed separately). Rank IC is monotone association only." % REGIME_M)
EQUITY_LABEL_NOTE = ("net_long = LONG net R of the registered 2 ATR stop / 3 ATR target / 24 RTH-bar bracket after fee + provisional 5 bps "
                     "slippage + 0.5 bps regulatory (the ENTRY-EQ label; the struct models train a pivot-5 SL-only variant of it); "
                     "fwd_ret_24 = raw 24 RTH-bar log return. Read both: net R divides by stop distance, so a volatility feature "
                     "can rank net R through cost-per-R rather than direction. DEV ONLY: decisions before %s; the confirming window "
                     "is never loaded. Population: the registered POOL_RULE ETF pool (sha in this block)." % DEV_END)


def m2_generic_rows(tab, *, features: List[str], labels: Dict[str, str], base: Dict[str, Any], overlap: int,
                    xs: bool, min_xs: int, min_ts: int, windows: Optional[str] = None) -> List[Dict[str, Any]]:
    """Long-table M2 rows over a (ts, symbol, features.., labels..) table. ``labels`` maps label column -> side tag.
    rank_ic_xs (cross-sectional per timestamp, averaged) only when ``xs`` and >= ``min_xs`` symbols; rank_ic_ts per symbol
    (and pooled over all rows), optionally per calendar year (``windows='year'``). A missing cell is value null with a
    read_state, never 0. The SE of a per-symbol IC uses n / ``overlap`` as the effective n (overlapping labels)."""
    import numpy as np
    out: List[Dict[str, Any]] = []
    n_sym = int(tab["symbol"].nunique())
    years = sorted({int(y) for y in tab["ts"].dt.year.unique()}) if windows == "year" else []
    for f in features:
        fam = feature_family(f)
        for label, side in labels.items():
            row = {**base, "feature_id": f"ml_feature.{f}", "feature": f, "feature_family": fam, "label": label,
                   "side": side, **({"ic_caveat": _CYC_NOTE} if f in CYCLIC else {})}
            if xs:
                r = m2_xs_ic(tab, f, label, overlap=overlap, min_xs=min_xs)
                out.append({**row, "measure": "rank_ic_xs", "symbol": "pooled", "window": "all", "n_obs": r.get("n"),
                            "n_symbols": n_sym, "value": _r(r.get("value")), "se": _r(r.get("se")), "t": _r(r.get("t"), 3),
                            "ci_low": _r(r["value"] - 1.96 * r["se"]) if r.get("se") else None,
                            "ci_high": _r(r["value"] + 1.96 * r["se"]) if r.get("se") else None,
                            "sign_consistency_quarters": _r(r.get("sign_consistency_quarters"), 3),
                            "read_state": r["read_state"], **({"reason": r["reason"]} if "reason" in r else {})})
                for q, qv in (r.get("by_quarter") or {}).items():
                    out.append({**row, "measure": "rank_ic_xs", "symbol": "pooled", "window": q, "n_obs": None,
                                "value": _r(qv), "se": None, "read_state": "measured"})
            pooled = _spearman(tab[f].to_numpy(float), tab[label].to_numpy(float)) if len(tab) >= min_ts else None
            out.append({**row, "measure": "rank_ic_ts", "symbol": "pooled", "window": "all", "n_obs": int(len(tab)),
                        "value": _r(pooled), "se": None, "read_state": "measured" if pooled is not None else "not_computed",
                        "note": "Spearman over every (symbol, decision) row pooled; se omitted (rows are cross-correlated)"})
            for sym, g in tab.groupby("symbol"):
                for win, gg in [("all", g)] + [(str(y), g[g["ts"].dt.year == y]) for y in years]:
                    ic = _spearman(gg[f].to_numpy(float), gg[label].to_numpy(float)) if len(gg) >= min_ts else None
                    n_eff = len(gg) / overlap
                    se = (1.0 / np.sqrt(n_eff - 3)) if (ic is not None and n_eff > 3) else None
                    out.append({**row, "measure": "rank_ic_ts", "symbol": sym, "window": win, "n_obs": int(len(gg)),
                                "value": _r(ic), "se": _r(se), "n_eff_div": overlap,
                                "read_state": "measured" if ic is not None else "not_computed",
                                **({} if ic is not None else {"reason": f"< {min_ts} rows or no variance"})})
    return out


def equity_table(cache: Path):
    """The ENTRY-EQ decision table on the registered POOL_RULE pool, DEV ONLY (bars end at TRAIN_END). Needs the read-only
    Alpaca data key pair in the environment (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY; the repo's research-script-run key)."""
    from types import SimpleNamespace
    import numpy as np
    import pandas as pd
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip  # noqa: PLC0415
    from scripts.research import ml_entry_equity as EQ  # noqa: PLC0415
    pool, prep, bars, _client = EQ._pool_and_bars(SimpleNamespace(cache=str(cache)), EQ.TRAIN_END)
    slip, _f = resolve_cost_policy("SPY")
    tab = EQ.build_table(bars, pool, slip, resolve_fee_bps_roundtrip("SPY"))
    fwd = []
    for sym in pool:
        df = bars.get(sym)
        if df is None or len(df) <= 400:
            continue
        c = np.log(df["close"].astype(float).to_numpy())
        f = np.full(len(c), np.nan)
        f[:-EQ.H] = c[EQ.H:] - c[:-EQ.H]
        fwd.append(pd.DataFrame({"ts": pd.to_datetime(df["close_ts"], utc=True), "symbol": sym, "fwd_ret_24": f}))
    tab = tab.merge(pd.concat(fwd), on=["ts", "symbol"], how="left")
    tab = tab[tab["ts"] < pd.Timestamp(DEV_END, tz="UTC")].reset_index(drop=True)
    feats = list(dict.fromkeys(EQ.OWN + EQ.XS + EQ.MKT))
    info = {"pool_symbols": len(pool), "symbols_built": int(tab["symbol"].nunique()), "decision_rows": int(len(tab)),
            "data_end": str(tab["ts"].max()), "pool_rule_sha256": prep.get("pool_rule_sha256"),
            "cost": {"slippage_bps": slip, "regulatory_bps": EQ.S.REGULATORY_BPS, "slippage_status": "PROVISIONAL"}}
    return tab, feats, info, EQ


def m2_equity_rows(tab, feats: List[str], run_id: str, computed_at: str, info: Dict[str, Any]) -> List[Dict[str, Any]]:
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "ml_family": "ml_entry_eq",
            "model_id": None, "served_models": ["ml_entry_eq_v1", "ml_entry_eq_v2_struct", "ml_entry_eq_v3_struct_ens5"],
            "stage": "family", "ml_type": "entry", "asset_class": "us_etf", "venue": "alpaca (1h RTH bars)",
            "timeframe": "1h", "horizon_bars": 24, "regime": "all", "provenance": "MEASURED", "window_end": info["data_end"],
            "source_artifact": "scripts/research/ml_entry_equity.py::build_table",
            "label_note": "see coverage.m2_equity.label_note"}
    return m2_generic_rows(tab, features=feats, labels={"net_long": "long", "fwd_ret_24": "all"}, base=base,
                           overlap=EQ_OVERLAP, xs=True, min_xs=M2_MIN_XS, min_ts=M2_MIN_TS)


def regime_table(cache: Path):
    """1h regime-head table for BTC/ETH/SOL from the SAME cached Binance Vision klines M2-crypto fetched: the head's
    features as market_features v002 builds them (past-only) and the two forward quantities its labels are functions of:
    forward_vol (pstdev of the next REGIME_M log returns: regime_label = forward_vol > vol_threshold) and the Kaufman
    efficiency ratio of the same window (trend_regime_label). The label thresholds are not applied: the continuous
    quantity carries every threshold."""
    import numpy as np
    import pandas as pd
    frames = []
    for sym in REGIME_SYMBOLS:
        p = cache / f"{sym}.pkl"
        if not p.exists():
            continue
        df = pd.read_pickle(p).reset_index(drop=True)
        ts = pd.to_datetime(df["ts"], utc=True)
        lr = pd.Series(np.log(df["close"].astype(float).to_numpy())).diff()
        past = lr.rolling(REGIME_VOL_N, min_periods=REGIME_VOL_N - 1).std(ddof=0)
        fwin = [lr.shift(-k) for k in range(1, REGIME_M + 1)]
        fm = pd.concat(fwin, axis=1)
        fvol = fm.std(axis=1, ddof=0)
        gross = fm.abs().sum(axis=1)
        er = (fm.sum(axis=1).abs() / gross).where(gross > 0, 0.0)
        valid = fm.notna().all(axis=1)
        frames.append(pd.DataFrame({"ts": ts, "symbol": sym, "rolling_log_return_vol": past, "log_return": lr,
                                    "log_return_lag_1": lr.shift(1), "log_return_lag_2": lr.shift(2),
                                    "hour_of_day": ts.dt.hour.astype(float), "dayofweek": ts.dt.dayofweek.astype(float),
                                    "forward_vol": fvol.where(valid), "forward_er": er.where(valid)}))
    if not frames:
        raise RuntimeError("no regime symbols in the kline cache")
    t = pd.concat(frames, ignore_index=True).dropna(subset=["rolling_log_return_vol", "forward_vol", "forward_er"])
    t = t[t["ts"] < pd.Timestamp(DEV_END, tz="UTC")].reset_index(drop=True)
    return t, {"symbols": sorted(t["symbol"].unique()), "rows": int(len(t)), "data_end": str(t["ts"].max()),
               "data_start": str(t["ts"].min())}


def m2_regime_rows(t, run_id: str, computed_at: str, info: Dict[str, Any]) -> List[Dict[str, Any]]:
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "ml_family": "regime_heads_1h",
            "model_id": None, "served_models": [], "stage": "family", "ml_type": "regime", "asset_class": "crypto_perp",
            "venue": "bybit (Binance USD-M proxy bars)", "timeframe": "1h", "horizon_bars": REGIME_M, "regime": "all",
            "provenance": "MEASURED", "window_end": info["data_end"],
            "source_artifact": "ml/datasets/families/market_features.py (re-derived past-only from the klines)",
            "label_note": "see coverage.m2_regime.label_note"}
    return m2_generic_rows(t, features=REGIME_FEATURES, labels={"forward_vol": "vol", "forward_er": "trend"}, base=base,
                           overlap=REGIME_M, xs=False, min_xs=M2_MIN_XS, min_ts=M2_MIN_TS, windows="year")


def _fit_score(train, test, feats: List[str], params: Dict[str, Any], tau: float, label: str, gate=None):
    """One LightGBM regressor on ``train`` -> (mean net R of test rows with pred > tau, n taken, rank IC pred vs label)."""
    import lightgbm as lgb
    m = lgb.LGBMRegressor(**params)
    m.fit(train[feats], train[label])
    pred = m.predict(test[feats])  # provenance: predict -- the regressed net R of the long side, not a probability
    take = pred > tau
    if gate is not None:
        take &= gate
    y = test[label].to_numpy(float)
    return {"mean_net_r": float(y[take].mean()) if take.sum() else None, "n_taken": int(take.sum()),
            "rank_ic": _spearman(pred, y)}


def m3_rows(tab, feats: List[str], *, params: Dict[str, Any], tau: float,
            base: Dict[str, Any], gate_fn=None, label: str = "net_long", log=print) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Drop-column ablation on the held-out score of a MONEY head (long-side net-R regressor). Train rows < ABL_TRAIN_END
    minus a purge, test rows [ABL_TRAIN_END, DEV_END). For each feature and each feature FAMILY: refit without it (same
    params, same seed) and report impact = base score - dropped score (positive = removing it hurts), for two scores:
    ``abl_taken_mean_net_r`` (mean net R of test rows with predicted net R > tau, net of the full cost stack) and
    ``abl_rank_ic`` (rank IC of the prediction vs net R, all test rows). A second base refit with a different seed gives the
    NOISE FLOOR: an impact smaller than it is not distinguishable from refit noise. Correlated features substitute for each
    other, so a small drop impact is not 'unimportant'."""
    import pandas as pd
    cut = pd.Timestamp(ABL_TRAIN_END, tz="UTC")
    dev = tab.dropna(subset=[label])
    train = dev[dev["ts"] < cut - pd.Timedelta(days=ABL_PURGE_DAYS)]
    test = dev[(dev["ts"] >= cut) & (dev["ts"] < pd.Timestamp(DEV_END, tz="UTC"))]
    gate = gate_fn(test) if gate_fn else None
    meta = {"train_rows": int(len(train)), "test_rows": int(len(test)), "train_end": ABL_TRAIN_END, "test_end": DEV_END,
            "tau": tau, "symbols_test": int(test["symbol"].nunique())}
    if len(train) < 5000 or len(test) < 1000:
        return [], {"state": "not_computed", "why": f"too few rows (train {len(train)}, test {len(test)})", **meta}
    b = _fit_score(train, test, feats, params, tau, label, gate)
    b2 = _fit_score(train, test, feats, {**params, "random_state": int(params.get("random_state", 0)) + 1}, tau, label, gate)
    floor = {"taken": abs(b["mean_net_r"] - b2["mean_net_r"]) if (b["mean_net_r"] is not None and b2["mean_net_r"] is not None) else None,
             "ic": abs(b["rank_ic"] - b2["rank_ic"]) if (b["rank_ic"] is not None and b2["rank_ic"] is not None) else None}
    meta.update({"base": b, "noise_floor": floor})
    groups: List[Tuple[str, str, List[str]]] = [("feature", f, [f]) for f in feats]
    fams: Dict[str, List[str]] = {}
    for f in feats:
        fams.setdefault(feature_family(f), []).append(f)
    groups += [("family", fam, fs) for fam, fs in fams.items() if len(fs) > 1]
    out: List[Dict[str, Any]] = []
    for kind, name, drop in groups:
        keep = [f for f in feats if f not in drop]
        try:
            d = _fit_score(train, test, keep, params, tau, label, gate)
            err = None
        except Exception as exc:  # noqa: BLE001  # allow-silent: this cell is a not_computed row, the other ablations continue
            d, err = None, f"{type(exc).__name__}: {exc}"
        log(f"[m3] drop {kind} {name}: {'ERR ' + err if err else d}")
        row = {**base, "feature": name if kind == "feature" else None, "feature_id": f"ml_feature.{name}" if kind == "feature" else None,
               "feature_family": feature_family(name) if kind == "feature" else name, "ablation_unit": kind,
               "dropped": drop, "symbol": "pooled", "window": f"test {ABL_TRAIN_END}..{DEV_END}", "label": label,
               "side": "long", "n_obs": meta["test_rows"], "n_train": meta["train_rows"], "tau": tau}
        for measure, key, fl in (("abl_taken_mean_net_r", "mean_net_r", floor["taken"]), ("abl_rank_ic", "rank_ic", floor["ic"])):
            ok = d is not None and d[key] is not None and b[key] is not None
            val = (b[key] - d[key]) if ok else None
            out.append({**row, "measure": measure, "value": _r(val), "base_score": _r(b[key]),
                        "dropped_score": _r(d[key]) if d else None, "n_taken_base": b["n_taken"],
                        "n_taken_dropped": d["n_taken"] if d else None, "noise_floor": _r(fl),
                        "above_noise_floor": (abs(val) > fl) if (ok and fl is not None) else None,
                        "read_state": "measured" if ok else "not_computed", **({} if ok else {"reason": err or "no trades taken or no variance"})})
    meta["state"] = "measured"
    meta["rows"] = len(out)
    return out, meta


def m3_crypto(tab, run_id: str, computed_at: str, log=print):
    from scripts.research import ml_decision_entry as mde  # noqa: PLC0415
    served = json.loads((REPO / "ml/served/ml_decision_entry_v2/model.json").read_text(encoding="utf-8"))
    tau = float(served.get("tau", 0.1))
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "ml_family": "ml_decision_entry", "model_id": None,
            "stage": "family", "ml_type": "entry", "asset_class": "crypto_perp", "venue": "bybit (Binance USD-M proxy bars)",
            "timeframe": "1h", "horizon_bars": mde.HORIZON_H, "regime": "all", "provenance": "MEASURED",
            "window_end": DEV_END, "source_artifact": "scripts/research/ml_decision_entry.py::LGB_PARAMS"}
    return m3_rows(tab, list(mde.FEATURES), params={**mde.LGB_PARAMS, "n_jobs": 4}, tau=tau, base=base, log=log)


def m3_equity(tab, feats: List[str], EQ, run_id: str, computed_at: str, log=print):
    tau = float(json.loads((REPO / "ml/candidates/ml_entry_eq_v1/model.json").read_text(encoding="utf-8")).get("tau", 0.2))
    base = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "ml_family": "ml_entry_eq", "model_id": None,
            "stage": "family", "ml_type": "entry", "asset_class": "us_etf", "venue": "alpaca (1h RTH bars)", "timeframe": "1h",
            "horizon_bars": 24, "regime": "all", "provenance": "MEASURED", "window_end": DEV_END,
            "source_artifact": "scripts/research/ml_entry_equity.py::BASE_PARAMS (CONFIG A: own + cross-section + market context)"}
    return m3_rows(tab, feats, params=dict(EQ.BASE_PARAMS), tau=tau, base=base,
                   gate_fn=lambda t: EQ.session_mask(t["ts"]), log=log)


def model_paths(root: Path) -> Iterable[Tuple[Path, str]]:
    for rel, stage in STAGE_DIRS:
        for p in sorted((root / rel).glob("*/model.json")):
            yield p, stage


def run(root: Path, out_dir: Path, run_id: Optional[str] = None, m2_cache: Optional[Path] = None,
        m2_symbols: Optional[List[str]] = None, eq_cache: Optional[Path] = None, m3: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    computed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = run_id or now.strftime("%Y%m%dT%H%MZ")
    rows: List[Dict[str, Any]] = []
    models: Dict[str, str] = {}
    for p, stage in model_paths(root):
        try:
            r = rows_for_model(p, stage, run_id, computed_at)
            rows += r
            models[str(p.relative_to(root))] = "measured"
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as a not_computed row, run continues
            rows.append({"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at,
                         "source_artifact": str(p.relative_to(root)), "stage": stage, "measure": "split_share",
                         "value": None, "read_state": "not_computed", "reason": f"{type(exc).__name__}: {exc}"})
            models[str(p.relative_to(root))] = f"not_computed: {type(exc).__name__}"
    m2_state: Dict[str, Any] = {"state": "not_attempted", "why": "run without --m2"}
    fams: Dict[str, Any] = {}
    tab = None
    if m2_cache is not None:
        try:
            tab, info = m2_build_table(m2_cache, m2_symbols)
            r2 = m2_rows(tab, run_id, computed_at, data_end=info["data_end"], symbols_requested=info["symbols_requested"])
            rows += r2
            m2_state = {"state": "measured", "rows": len(r2), "label_note": M2_LABEL_NOTE, "se_basis": M2_SE_BASIS,
                        **{k: v for k, v in info.items() if k != "fetch"},
                        "missing_months": {s: v.get("missing_months") for s, v in info["fetch"].items()
                                           if v.get("missing_months")}}
        except Exception as exc:  # noqa: BLE001  # allow-silent: M2 failure is recorded in latest.json coverage.m2; M1 still lands
            m2_state = {"state": "not_computed", "why": f"{type(exc).__name__}: {exc}"}
        try:
            rt, ri = regime_table(m2_cache)
            rr = m2_regime_rows(rt, run_id, computed_at, ri)
            rows += rr
            fams["m2_regime"] = {"state": "measured", "rows": len(rr), **{("table_rows" if k == "rows" else k): v for k, v in ri.items()},
                                 "label_note": REGIME_LABEL_NOTE}
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded in coverage.m2_regime; other families still land
            fams["m2_regime"] = {"state": "not_computed", "why": f"{type(exc).__name__}: {exc}"}
    else:
        fams["m2_regime"] = {"state": "not_attempted", "why": "run without --m2 (needs the kline cache)"}
    if eq_cache is not None:
        try:
            et, efeats, einfo, EQ = equity_table(eq_cache)
            re_ = m2_equity_rows(et, efeats, run_id, computed_at, einfo)
            rows += re_
            fams["m2_equity"] = {"state": "measured", "rows": len(re_), **einfo, "features": efeats, "label_note": EQUITY_LABEL_NOTE}
            if m3:
                r3, i3 = m3_equity(et, efeats, EQ, run_id, computed_at)
                rows += r3
                fams["m3_equity"] = i3
        except Exception as exc:  # noqa: BLE001  # allow-silent: recorded in coverage; crypto + M1 still land
            fams["m2_equity"] = {"state": "not_computed", "why": f"{type(exc).__name__}: {exc}"}
            fams["m3_equity"] = {"state": "not_computed", "why": "equity table unavailable"}
    else:
        fams["m2_equity"] = {"state": "not_attempted", "why": "run without --eq-cache (needs the Alpaca read-only data key)"}
    if m3:
        if tab is not None:
            try:
                r3, i3 = m3_crypto(tab, run_id, computed_at)
                rows += r3
                fams["m3_crypto"] = i3
            except Exception as exc:  # noqa: BLE001  # allow-silent: recorded in coverage.m3_crypto
                fams["m3_crypto"] = {"state": "not_computed", "why": f"{type(exc).__name__}: {exc}"}
        else:
            fams["m3_crypto"] = {"state": "not_computed", "why": "crypto decision table unavailable (M2 did not run or failed)"}
    else:
        fams["m3_crypto"] = {"state": "not_attempted", "why": "run without --m3"}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run_id}.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    measured = [r for r in rows if r.get("read_state") == "measured"]
    summary = {"schema": SCHEMA, "run_id": run_id, "computed_at": computed_at, "file": f"{run_id}.jsonl",
               "read_state": "measured" if measured else "no_data", "n_rows": len(rows), "n_measured": len(measured),
               "models": models,
               "measures": sorted({r["measure"] for r in rows if "measure" in r}),
               "coverage": {"in_v0": "M1 split_share + gain_share for ml/served + ml/candidates LightGBM artifacts, pooled population",
                            "m2": m2_state, **fams,
                            "m2_scope": ("rank_ic_xs (cross-sectional per 4 h decision timestamp, averaged; by quarter) and "
                                         "rank_ic_ts (per symbol) for the crypto decision-entry family's 20 features vs its own "
                                         "net-R label and the raw 24 h return"),
                            "not_yet": [
                                "M2 / M3 for the tp-revision exit head (its 18-class check-in label needs its own builder)",
                                "M3 for the regime heads (not money heads; their score is a classification metric)",
                                "regime heads at 5m / 15m (only 1h klines are cached) and the MES regime heads (no keyless equity-futures bars)",
                                "registry regime models' M1 importances (on the trainer VM)", "SHAP / permutation on OOF"]}}
    (out_dir / "latest.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _self_test() -> int:
    ok = True
    txt = "tree\nfeature_importances:\na=3\nb=1\n\nparameters:\n[boosting: gbdt]\n"
    if parse_split_counts(txt) != {"a": 3, "b": 1}:
        print("  FAIL  parse_split_counts", parse_split_counts(txt))
        ok = False
    else:
        print("  PASS  split block parsed and stops at the blank line")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "ml/candidates/x"
        d.mkdir(parents=True)
        (d / "model.json").write_text(json.dumps({"model_id": "ENTRY-EQ-x", "features": ["a", "b", "c"],
                                                  "booster_txt": {"long": [txt, txt]}}))
        bad = root / "ml/served/bad"
        bad.mkdir(parents=True)
        (bad / "model.json").write_text(json.dumps({"model_id": "bad", "features": ["a"]}))
        s = run(root, root / "out", run_id="T")
        rows = [json.loads(x) for x in (root / "out/T.jsonl").read_text().splitlines()]
        sp = {r["feature"]: r["value"] for r in rows if r.get("measure") == "split_share" and r.get("feature")}
        if abs(sp["a"] - 0.75) < 1e-9 and abs(sp["b"] - 0.25) < 1e-9 and sp["c"] == 0.0:
            print("  PASS  ensemble split shares sum members; an unsplit listed feature is a measured 0")
        else:
            print("  FAIL  shares", sp)
            ok = False
        if s["models"].get("ml/served/bad/model.json", "").startswith("not_computed") and s["read_state"] == "measured":
            print("  PASS  an unreadable artifact is a not_computed row and the run continues")
        else:
            print("  FAIL  bad artifact handling", s["models"])
            ok = False
        gains = [r for r in rows if r.get("measure") == "gain_share" and r.get("feature")]
        if all((r["value"] is None) == (r["read_state"] == "not_computed") for r in gains):
            print("  PASS  a gain row is null exactly when not_computed (never a silent 0)")
        else:
            print("  FAIL  gain null/read_state mismatch")
            ok = False
        empty = run(root / "nothing", root / "out2", run_id="E")
        if empty["read_state"] == "no_data":
            print("  PASS  a run over no artifacts reads no_data")
        else:
            print("  FAIL  empty run", empty["read_state"])
            ok = False
    try:
        ok = _self_test_m2() and ok
        ok = _self_test_m3_regime() and ok
    except Exception as exc:  # noqa: BLE001  # allow-silent: printed as a FAIL and fails the self-test
        print(f"  FAIL  M2 self-test raised {type(exc).__name__}: {exc}")
        ok = False
    print("feature_impact self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def _self_test_m2() -> bool:
    """A planted cross-sectional signal is found with the right sign; a feature constant across symbols reads
    not_applicable (never 0); the long table carries quarter rows and per-symbol rows."""
    import numpy as np
    import pandas as pd
    from scripts.research import ml_decision_entry as mde
    rng = np.random.default_rng(7)
    ts = pd.date_range("2024-01-01", periods=600, freq="4h", tz="UTC")
    rows = []
    for i in range(20):
        f = {k: rng.normal(size=len(ts)) for k in mde.FEATURES}
        f["hour"] = ts.hour.to_numpy().astype(float)          # identical across symbols
        lab = 0.5 * f["ret_24"] + rng.normal(size=len(ts))
        rows.append(pd.DataFrame({"ts": ts, "symbol": f"S{i}", "net_long": lab, "fwd_ret_24h": lab, **f}))
    tab = pd.concat(rows, ignore_index=True)
    out = m2_rows(tab, "T", "now", data_end="2024-04-10", symbols_requested=20)
    xs = {(r["feature"], r["label"]): r for r in out if r["measure"] == "rank_ic_xs" and r["window"] == "all"}
    ok = True
    r = xs[("ret_24", "net_long")]
    if r["read_state"] == "measured" and r["value"] > 0.3 and r["t"] > 10:
        print("  PASS  M2 finds a planted cross-sectional signal (IC %.3f, t %.1f)" % (r["value"], r["t"]))
    else:
        print("  FAIL  M2 planted signal", r)
        ok = False
    h = xs[("hour", "net_long")]
    if h["read_state"] == "not_applicable" and h["value"] is None:
        print("  PASS  a feature identical across symbols is not_applicable for rank_ic_xs, never 0")
    else:
        print("  FAIL  constant feature", h)
        ok = False
    nul = xs[("vol24", "net_long")]
    if abs(nul["value"]) < 0.03:
        print("  PASS  a null feature reads ~0 (%.4f)" % nul["value"])
    else:
        print("  FAIL  null feature", nul["value"])
        ok = False
    q = [x for x in out if x["measure"] == "rank_ic_xs" and x["window"] != "all"]
    ts_rows = [x for x in out if x["measure"] == "rank_ic_ts"]
    if q and len(ts_rows) == 20 * len(mde.FEATURES) * len(M2_LABELS):
        print("  PASS  quarter rows and one per-symbol row per (feature, label, symbol)")
    else:
        print("  FAIL  row shape", len(q), len(ts_rows))
        ok = False
    return ok


def _self_test_m3_regime() -> bool:
    """M3: dropping the one informative feature hurts, dropping a noise feature does not (inside the noise floor); an
    equity-style table with no cross-section still gets per-symbol / pooled / per-year IC rows and never an xs row; the
    regime table's forward_vol uses the NEXT m returns only (a planted vol clustering is found by rolling vol)."""
    import numpy as np
    import pandas as pd
    global ABL_TRAIN_END, DEV_END
    rng = np.random.default_rng(3)
    ts = pd.date_range("2023-01-01", periods=3000, freq="4h", tz="UTC")
    parts = []
    for i in range(6):
        sig, noise = rng.normal(size=len(ts)), rng.normal(size=len(ts))
        parts.append(pd.DataFrame({"ts": ts, "symbol": f"S{i}", "sig": sig, "noise": noise,
                                   "net_long": 0.6 * sig + rng.normal(size=len(ts))}))
    tab = pd.concat(parts, ignore_index=True)
    old = (ABL_TRAIN_END, DEV_END)
    ABL_TRAIN_END, DEV_END = "2023-09-01", "2024-03-01"
    try:
        rows, meta = m3_rows(tab, ["sig", "noise"], params={"n_estimators": 60, "learning_rate": 0.1, "num_leaves": 7,
                                                           "min_child_samples": 50, "verbose": -1, "n_jobs": 2, "random_state": 1},
                             tau=0.0, base={"schema": SCHEMA}, log=lambda *_: None)
    finally:
        ABL_TRAIN_END, DEV_END = old
    ic = {r["feature"]: r for r in rows if r["measure"] == "abl_rank_ic" and r["ablation_unit"] == "feature"}
    ok = True
    if meta["state"] == "measured" and ic["sig"]["value"] > 0.2 and ic["sig"]["above_noise_floor"] \
            and abs(ic["noise"]["value"]) < max(0.02, 3 * (ic["noise"]["noise_floor"] or 0)):
        print("  PASS  M3 drop-column: the planted feature's removal costs %.3f IC, the noise feature's %.4f" %
              (ic["sig"]["value"], ic["noise"]["value"]))
    else:
        print("  FAIL  M3 ablation", meta.get("state"), ic)
        ok = False
    if all((r["value"] is None) == (r["read_state"] == "not_computed") for r in rows):
        print("  PASS  an M3 cell is null exactly when not_computed")
    else:
        print("  FAIL  M3 null/read_state")
        ok = False
    t2 = tab.assign(fwd=tab["net_long"])
    out = m2_generic_rows(t2, features=["sig"], labels={"fwd": "all"}, base={"schema": SCHEMA}, overlap=5, xs=False,
                          min_xs=10, min_ts=200, windows="year")
    kinds = {(r["measure"], r["symbol"] == "pooled", r["window"] == "all") for r in out}
    if ("rank_ic_xs", True, True) not in kinds and ("rank_ic_ts", True, True) in kinds and any(r["window"] == "2024" for r in out):
        print("  PASS  generic M2 with xs=False: no cross-sectional rows, pooled + per-symbol + per-year time-series rows")
    else:
        print("  FAIL  generic M2 row kinds", sorted(kinds))
        ok = False
    with tempfile.TemporaryDirectory() as td:
        n = 3000
        px = np.exp(np.cumsum(rng.normal(scale=0.01, size=n)))
        pd.DataFrame({"ts": pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC"), "close": px}).to_pickle(Path(td) / "BTCUSDT.pkl")
        t, info = regime_table(Path(td))
        # forward_vol of row i must equal pstdev of lr[i+1..i+5] and NOT depend on lr[i]
        lr = np.diff(np.log(px), prepend=np.nan)
        j = 1000
        row = t[t["ts"] == pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")[j]].iloc[0]
        if abs(row["forward_vol"] - np.std(lr[j + 1:j + 6])) < 1e-12 and abs(row["log_return"] - lr[j]) < 1e-12:
            print("  PASS  regime table: forward_vol is the pstdev of the NEXT %d returns; features are past-only" % REGIME_M)
        else:
            print("  FAIL  regime table forward window", row["forward_vol"], np.std(lr[j + 1:j + 6]))
            ok = False
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", default=str(REPO / "comms/feature_impact"))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--m2", action="store_true", help="also compute M2 rank IC (fetches keyless Binance Vision klines)")
    ap.add_argument("--m2-cache", default=None, help="kline cache dir for --m2 (default: a temp dir)")
    ap.add_argument("--m2-symbols", default=None, help="comma list; default = the served model's xs_reference universe")
    ap.add_argument("--eq-cache", default=None, help="bar cache dir: also compute the equity-entry M2 (needs ALPACA_API_KEY_ID / "
                    "ALPACA_API_SECRET_KEY, read-only data)")
    ap.add_argument("--m3", action="store_true", help="also compute the M3 drop-column ablation (crypto needs --m2; equity needs --eq-cache)")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    cache = (Path(a.m2_cache) if a.m2_cache else Path(tempfile.mkdtemp(prefix="fi_m2_"))) if a.m2 else None
    syms = [x for x in a.m2_symbols.split(",") if x] if a.m2_symbols else None
    s = run(REPO, Path(a.out_dir), a.run_id, m2_cache=cache, m2_symbols=syms,
            eq_cache=Path(a.eq_cache) if a.eq_cache else None, m3=a.m3)
    print(f"feature_impact: run={s['run_id']} read_state={s['read_state']} rows={s['n_rows']} measured={s['n_measured']} "
          f"m2={s['coverage']['m2']['state']}")
    return 0 if s["read_state"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
