#!/usr/bin/env python3
# wiring: research/queue/RQ-20261108-98e3-22.yaml (dev), -23 (confirm); lanes CRYPTO-ENTRY-RETRAIN-UNIT and ML-ENTRY-PROP
"""CRYPTO structure-label ENTRY model: the equity recipe (ml_entry_equity.py) ported to the Binance-perp universe.

WHY (manager 2026-11-08, operator priority "a live ML ENTRY model on EVERY live-money account"): the served crypto ENTRY model reads
-0.13 R net over 14 days (comms/research/ml_entry_grade/42473814600) and ml_entry failed the prop gate RULE-P5-GATE-BRK-PER-LEG-V3 on all
three firms (comms/prop_survival/ml_entry.json: edge +0.017 R, CI95 [-0.106, +0.140]). The equity structure recipe (pivot=5;sl_only labels, a
5-seed LightGBM ensemble) is the one ENTRY variant with a registered pass; this module is the same machinery on the crypto table.

REUSE, not a fork: labels/costs come from ml_decision_entry (the crypto table, bracket long/short columns and the canonical cost stack
`_cost_r`: fee 11 bps + slippage + funding); the long-side outcome is REPLACED by the live structure-exit replay
(ml_entry_equity._structure_outcomes); the model, ensemble, purge and take-rule are ml_entry_equity's. Restricted-LONG, net R regressor.

    python3 scripts/research/ml_entry_crypto_struct.py --self-test
    python3 scripts/research/ml_entry_crypto_struct.py dev     --cache /tmp/ml_decision_klines --out /tmp/o --unit RQ-... --ensemble-seeds 1,2,3,4,5
    python3 scripts/research/ml_entry_crypto_struct.py confirm --cache ... --out ... --unit RQ-... --config A --tau 0.1 --dev-oof-mean 0.05 --ensemble-seeds 1,2,3,4,5

DEV never loads rows on or after HOLDOUT_START (2025-10-01). CONFIRM scores 2025-10-01..2026-09-30 once under its own ledger family
(ENTRY-CRYPTO-STRUCT); that window was already read by the served model's records, so the read is recorded with its true N.
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
import ml_entry_equity as Q  # noqa: E402

FAMILY = "ENTRY-CRYPTO-STRUCT"
TRAIN_END = "2025-09-16"            # last date the model may see; confirm starts 2025-10-01 >= train_end + 14 d embargo
CONFIRM_START = E.HOLDOUT_START     # 2025-10-01
CONFIRM_END = E.END                 # 2026-09-30
DEV_FOLDS = list(E.DEV_FOLDS)       # 2022-01-01 .. 2025-07-01 (the last tests [2025-07-01, train_end])
TAUS = [0.05, 0.10, 0.15, 0.20, 0.30]
MIN_OOF_N = 300
PROP_SYMBOLS = ["ETHUSDT", "SOLUSDT"]
SPEC = Q.STRUCT_SPEC
OWN = Q.OWN
XS = ["xs_rank_ret24", "btc_ret24", "btc_vol24", "breadth_up24", "rel_vol"]
CONFIGS = {"A": {"features": OWN + XS, "params": {}},      # own + cross-sectional/BTC context (the served feature set)
           "B": {"features": OWN, "params": {}}}           # own price/volume/vol only
REGISTERED_SELECTION = ("max pooled dev out-of-fold mean net R over (config, tau) subject to >= %d OOF trades" % MIN_OOF_N)


def struct_table(cache: Path, symbols: list[str], spec: str = SPEC) -> pd.DataFrame:
    """The crypto label table with the LONG outcome replaced by the structure-exit replay (same entry, same 2 ATR risk, same TP 3 ATR,
    same 24-bar stop), costed by the canonical stack. Short columns stay the fixed-bracket ones and are never used (long-only)."""
    tab = E.build_table(cache, symbols)
    parts = []
    for sym, g in tab.groupby("symbol", sort=False):
        df = pd.read_pickle(cache / f"{sym}.pkl").reset_index(drop=True)
        cand = g["i"].to_numpy(int)
        entry, atr = g["entry"].to_numpy(float), g["atr"].to_numpy(float)
        px, jj, rs = Q._structure_outcomes(df, cand, entry, atr, spec)
        risk = E.SL_ATR * atr
        t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
        t_entry_s = t_ns[cand + 1] / 1e9
        t_exit_s = t_ns[cand + jj] / 1e9 + 3600.0
        fee, slip, fund = E._cost_r(entry, px, risk, t_entry_s, t_exit_s)
        gross = (px - entry) / risk
        parts.append(g.assign(gross_long=gross, cost_long=fee + slip + fund, net_long=gross - fee - slip - fund,
                              reason_long=rs, bars_long=jj))
    return pd.concat(parts).sort_values(["ts", "symbol"]).reset_index(drop=True)


def _no_session(ts) -> np.ndarray:
    return np.ones(len(ts), dtype=bool)        # 24/7 market: no session gate


def _enter_crypto_mode() -> None:
    """Point the equity machinery at the crypto family: no RTH gate, own ledger family, crypto embargo unchanged (14 d)."""
    Q.session_mask = _no_session
    Q.FAMILY = FAMILY


def _subset(tk: pd.DataFrame, symbols) -> dict:
    s = tk[tk.symbol.isin(symbols)]
    return Q._stats(s)


def dev_stage(tab: pd.DataFrame, folds=DEV_FOLDS, train_end: str = TRAIN_END, taus=TAUS, configs: dict = CONFIGS,
              min_oof_n: int = MIN_OOF_N, prop_symbols=PROP_SYMBOLS, log=print) -> dict:
    """Purged expanding walk-forward on dates <= train_end ONLY. Pooled OOF read per (config, tau) plus the same OOF restricted to the
    prop symbols (reported, never selected on). Registered selection: max pooled mean net R subject to >= min_oof_n trades."""
    _enter_crypto_mode()
    te = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(days=1)
    assert te <= pd.Timestamp(CONFIRM_START, tz="UTC"), "dev may not reach the sealed window"
    dev = tab[tab.ts < te].dropna(subset=["net_long"])
    bounds = [pd.Timestamp(x, tz="UTC") for x in folds] + [te]
    res = {}
    for name, cfg in configs.items():
        feats = cfg["features"]
        oof = []
        for k in range(len(folds)):
            tr = Q.purge(dev[dev.ts < bounds[k]], bounds[k]).dropna(subset=feats)
            ts_ = dev[(dev.ts >= bounds[k]) & (dev.ts < bounds[k + 1])].dropna(subset=feats)
            if len(tr) < 1000 or len(ts_) == 0:
                continue
            m = Q._lgb(cfg["params"]).fit(tr[feats], tr["net_long"])
            # provenance: predict -- the regressed LONG net R, not a probability
            oof.append(ts_.assign(pred=m.predict(ts_[feats]), fold=k))
            log(f"[dev] config {name} fold {k} train={len(tr)} test={len(ts_)} t={time.strftime('%H:%M:%S')}")
        if not oof:
            continue
        o = pd.concat(oof)
        for tau in taus:
            tk = Q.taken_trades(o, o["pred"].to_numpy(), tau)
            st = Q._stats(tk)
            st["by_fold"] = ({int(k): {"n": int(len(g)), "mean_net_r": round(float(g.net_r.mean()), 4)}
                              for k, g in tk.assign(fold=Q._fold_of(tk.ts, bounds)).groupby("fold")} if len(tk) else {})
            st["prop_symbols"] = _subset(tk, prop_symbols)
            res[f"{name}|{tau}"] = {"config": name, "tau": tau, **st}
    ok = {k: v for k, v in res.items() if v["n"] >= min_oof_n and v["mean_net_r"] is not None}
    best = max(ok.items(), key=lambda kv: kv[1]["mean_net_r"]) if ok else None
    return {"grid": res, "n_selection_draws": len(res), "selection_rule": REGISTERED_SELECTION,
            "selected": None if best is None else {"key": best[0], **best[1]}, "dev_rows": int(len(dev))}


def _ens(configs: dict, seeds) -> dict:
    if not seeds:
        return configs
    return {k: {"features": v["features"], "params": {**v["params"], "_ens_seeds": [int(x) for x in seeds]}} for k, v in configs.items()}


def confirm_stage(tab: pd.DataFrame, config: str, tau: float, dev_oof_mean: float, unit: str, ledger_dir: Path, symbols,
                  seeds=None, min_mean: float = 0.0, claim: bool = True, train_end: str = TRAIN_END, start: str = CONFIRM_START,
                  end: str = CONFIRM_END) -> dict:
    """ONE confirming read of [start, end], refit on rows <= train_end; deflated bar from the family's ledger N."""
    _enter_crypto_mode()
    tag = "-STRUCT-" + SPEC.replace(";", "-").replace("=", "") + (f"-ENS{len(seeds)}" if seeds else "")
    return Q.confirm_stage(tab, config, float(tau), float(dev_oof_mean), unit, ledger_dir, train_end=train_end, start=start, end=end,
                           symbols=symbols, configs=_ens(CONFIGS, seeds), claim=claim, model_tag=tag, min_mean=min_mean)


def full_stage(tab: pd.DataFrame, unit: str, ledger_dir: Path, symbols, seeds, taus=TAUS, configs: dict = CONFIGS,
               min_mean: float = 0.05, claim: bool = True, log=print) -> dict:
    """dev -> registered selection -> ONE confirm (the equity structure_stage pattern). ``min_mean`` is the registered margin floor."""
    d = dev_stage(tab, taus=taus, configs=_ens(configs, seeds), log=log)
    sel = d["selected"]
    if sel is None:
        return {"verdict": "indeterminate", "note": "dev stage selected nothing (no tau with >= %d OOF trades)" % MIN_OOF_N, "dev": d}
    c = confirm_stage(tab, sel["config"], float(sel["tau"]), float(sel["mean_net_r"]), unit, ledger_dir, symbols, seeds=seeds,
                      min_mean=min_mean, claim=claim)
    c["dev"] = d
    c["structure_exit"] = SPEC
    return c


def main_run(a) -> int:
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    symbols = E.universe()
    cache = Path(a.cache)
    rep = E.fetch(cache, symbols, end=E.END)
    missing = [s for s in symbols if not (cache / f"{s}.pkl").exists()]
    if missing:
        raise RuntimeError(f"kline cache incomplete: {missing[:5]}")
    tab = struct_table(cache, symbols)
    print(f"[table] {len(tab)} decision rows, {tab.symbol.nunique()} symbols t={time.strftime('%H:%M:%S')}", flush=True)
    seeds = a.ensemble_seeds.split(",") if a.ensemble_seeds else None
    cfgs = {k: CONFIGS[k] for k in a.configs.split(",")} if a.configs else CONFIGS
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    if a.cmd == "dev":
        taus = [float(x) for x in a.taus.split(",")] if a.taus else TAUS
        d = dev_stage(tab, taus=taus, configs=_ens(cfgs, seeds))
        sel = d["selected"]
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": "indeterminate",
               "population": (f"DEV stage: purged walk-forward OOF restricted-long decisions on the {tab.symbol.nunique()}-symbol Binance-perp table "
                              f"(ml_decision_entry universe), dates <= {TRAIN_END}, structure exit {SPEC}, net of fee 11 bps + slippage + funding; "
                              f"{d['n_selection_draws']} (config, tau) draws"),
               "note": ("DEV stage (<= %s; sealed window not loaded). Selected %s: OOF mean net R %s at n=%s; prop symbols (ETH+SOL) at that cell: %s"
                        % (TRAIN_END, None if sel is None else sel["key"], None if sel is None else sel["mean_net_r"],
                           None if sel is None else sel["n"], None if sel is None else sel["prop_symbols"])),
               "generated_at": now, "measurement": {**d, "fetch": rep, "runtime_s": round(time.time() - t0, 1), "structure_exit": SPEC},
               "n": None if sel is None else sel["n"], "produced_by": {"tool": "python3 scripts/research/ml_entry_crypto_struct.py dev", "where": a.where}}
    elif a.cmd == "full":
        c = full_stage(tab, a.unit, out / "ledger", symbols, seeds, taus=[float(x) for x in a.taus.split(",")] if a.taus else TAUS,
                       configs=cfgs, min_mean=float(a.min_mean))
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": now, "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c.get("stats", {}).get("n"), "description": f"crypto structure ENTRY (dev-selected config/tau, {SPEC}) restricted-LONG on the "
                              f"{tab.symbol.nunique()}-symbol Binance-perp table, ONE confirm {CONFIRM_START}..{CONFIRM_END}, net of the canonical cost stack"},
               "measurement": {**c, "fetch": rep, "runtime_s": round(time.time() - t0, 1)}, "n": c.get("stats", {}).get("n"),
               "produced_by": {"tool": "python3 scripts/research/ml_entry_crypto_struct.py full", "where": a.where}}
    else:
        c = confirm_stage(tab, a.config, float(a.tau), float(a.dev_oof_mean), a.unit, out / "ledger", symbols, seeds=seeds,
                          min_mean=float(a.min_mean))
        row = {"schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": c["verdict"], "note": c["note"],
               "generated_at": now, "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
               "population": {"n": c["stats"]["n"], "description": f"crypto structure ENTRY ({a.config}, tau {a.tau}, {SPEC}) restricted-LONG on the "
                              f"{tab.symbol.nunique()}-symbol Binance-perp table, window {CONFIRM_START}..{CONFIRM_END}, net of the canonical cost stack"},
               "measurement": {**c, "fetch": rep, "runtime_s": round(time.time() - t0, 1)}, "n": c["stats"]["n"],
               "produced_by": {"tool": "python3 scripts/research/ml_entry_crypto_struct.py confirm", "where": a.where}}
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print(f"{a.cmd.upper()} {row['verdict']}: {row['note']}", flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _synthetic_cache(root: Path, seed: int = 0, n_hours: int = 24 * 900) -> list[str]:
    rng = np.random.default_rng(seed)
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"] + [f"X{i}USDT" for i in range(5)]
    ts = pd.date_range("2021-01-01", periods=n_hours, freq="h", tz="UTC")
    for s in syms:
        r = rng.normal(0, 0.004, n_hours)
        c = 100.0 * np.exp(np.cumsum(r))
        o = np.r_[c[0], c[:-1]]
        df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c,
                           "volume": rng.integers(1_000, 10_000, n_hours).astype(float)})
        df.to_pickle(root / f"{s}.pkl")
    return syms


def self_test() -> int:
    import tempfile
    root = Path(tempfile.mkdtemp())
    syms = _synthetic_cache(root)
    tab = struct_table(root, syms)
    assert {"net_long", "gross_long", "cost_long", "reason_long", "bars_long"} <= set(tab.columns)
    assert tab[["net_long", "cost_long"]].notna().all().all() and (tab.cost_long > 0).all(), "costed by the canonical stack"
    plain = E.build_table(root, syms)
    assert len(plain) == len(tab) and not np.allclose(plain.sort_values(["ts", "symbol"]).net_long.to_numpy(), tab.net_long.to_numpy()), \
        "the structure replay must change the long outcome"
    small = {"A": {"features": OWN + XS, "params": {"n_estimators": 20, "min_child_samples": 20}},
             "B": {"features": OWN, "params": {"n_estimators": 20, "min_child_samples": 20}}}
    d = dev_stage(tab, folds=["2022-09-01", "2023-01-01"], train_end="2023-04-30", taus=[0.0, 0.05], configs=small, min_oof_n=1,
                  prop_symbols=["ETHUSDT", "SOLUSDT"], log=lambda *_: None)
    assert d["n_selection_draws"] == 4 and d["selected"] is not None and "prop_symbols" in d["selected"], d
    assert max(len(r["by_fold"]) for r in d["grid"].values()) >= 2, "by_fold collapsed into one fold"
    try:
        dev_stage(tab, train_end="2025-12-31", configs=small, log=lambda *_: None)
        raise AssertionError("dev reached the sealed window")
    except AssertionError as e:
        assert "sealed" in str(e), e
    cs = {"A": {"features": OWN + XS, "params": {"n_estimators": 20, "min_child_samples": 20}}}
    global CONFIGS
    keep, CONFIGS = CONFIGS, cs
    try:
        r = confirm_stage(tab, "A", 0.0, 0.01, "RQ-T", Path(tempfile.mkdtemp()), syms, claim=False, train_end="2023-03-01", start="2023-03-20", end="2023-06-01")
    finally:
        CONFIGS = keep
    assert r["verdict"] in ("pass", "fail", "indeterminate") and r["window"]["start"] == "2023-03-20" and r["stats"]["n"] >= 0, r
    assert Q.FAMILY == FAMILY and Q.session_mask(pd.Series(pd.to_datetime(["2023-01-01 03:00"], utc=True))).all()
    assert E.HOLDOUT_START == CONFIRM_START and pd.Timestamp(CONFIRM_START) >= pd.Timestamp(TRAIN_END) + pd.Timedelta(days=Q.EMBARGO_DAYS)
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("dev", "confirm", "full"):
        p = sub.add_parser(name)
        p.add_argument("--cache", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--unit", required=True)
        p.add_argument("--where", default="local")
        p.add_argument("--ensemble-seeds", dest="ensemble_seeds", default="")
        p.add_argument("--configs", default="")
        if name in ("dev", "full"):
            p.add_argument("--taus", default="")
        if name == "full":
            p.add_argument("--min-mean", default="0.05")
            p.add_argument("--rule-id", dest="rule_id", default="")
            p.add_argument("--registered-at", dest="registered_at", default="")
        if name == "confirm":
            p.add_argument("--config", required=True, choices=sorted(CONFIGS))
            p.add_argument("--tau", required=True)
            p.add_argument("--dev-oof-mean", required=True)
            p.add_argument("--min-mean", default="0.0")
            p.add_argument("--rule-id", dest="rule_id", default="")
            p.add_argument("--registered-at", dest="registered_at", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.cmd:
        ap.error("a stage or --self-test is required")
    return main_run(a)


if __name__ == "__main__":
    sys.exit(main())
