#!/usr/bin/env python3
# wiring: research/queue/RQ-20261125-f1a0-24.yaml (row REGIME-ROSTERED-CONFIG-REPLAY: the R3 confirmation on the configs we actually trade)
"""REGIME-ROSTERED-CONFIG-REPLAY: replay every ROSTERED crypto leg (a `mode: live` book, real-money / prop / demo floor) of the trend, pullback,
fade and squeeze families with its DECLARED config/strategies.yaml params over one pinned window, then grade the REGIME-PROGRAM R3 / R4 tilts on
those legs as books. The confirmation population of RQ-20261125-f1a0-20 (R3 PASS on the sweep corpus): different trades (declared configs, not
averaged sweep variants), the legs a sizing proposal would act on.

Replay: the evidence builder's own path, nothing reimplemented: exit_lever_ablation.fetch_candles (regime_debt_matrix._fetch_csv, keyless Binance
Vision) + exit_lever_ablation.build_arm_argv (regime_debt_matrix.build_harness_cmd, the harness's own venue-aware fee + slippage + funding) with
--start/--end pinned to WINDOW. A leg whose harness fails is a recorded state (`legs.<leg>.state`), never dropped silently.

Grade (RULE-REGIME-R3-CONFIRM-ROSTERED-20261125): books = leg x direction; the regime_r2_family_router machinery unchanged (weekly books, causal
trailing / same-cell prior means, 2.0 / 0.5 tilt renormalised weekly, 1,000 week-bootstrap draws, 200 within-week permutations). Arms: advol and hmm2
state tilts (f1a0-20) and the no-state tilt (f1a0-23's control), each vs equal risk. An arm PASSES iff delta >= +0.01 R/trade AND t >= 2 AND
permutation share <= 0.0167 (three arms, Bonferroni of 0.05) AND >= 4 of 5 test years > 0. UNIT PASS iff any arm passes; FAIL iff every arm has
delta <= 0 or share >= 0.5; else INDETERMINATE. Reported, not graded: the state-vs-no-state week-paired deltas (decomp), per-leg trade counts / net R.

TRADE-STATE (``--mode tradestate``, unit RQ-20261125-f1a0-25, RULE-REGIME-TRADESTATE-20261125), from f1a0-24 (book-level BTC-state and book-quality
tilts NOT confirmed on the rostered legs; f1a0-23 showed BTC state adds nothing beyond book quality): condition each TRADE on its OWN symbol's state at
entry (the traded symbol's last daily close before the entry day above / below its 50-day mean x its 20-day realised vol above / below its trailing
365-day median), tilting 2.0 / 0.5 by the sign of the mean net R of that leg x direction's PRIOR trades in the same cell that had EXITED before this
entry (>= TS_MIN_N of them, else 1.0), renormalised within each leg x calendar month (same risk per leg-month). Statistic: weighted minus unweighted net
R per trade, 1,000 entry-week bootstrap draws; control: the raw tilts permuted within each leg x month (200 draws). PASS iff delta >= +0.01 AND t >= 2
AND permutation share <= 0.05 AND >= 4 of 5 years > 0; FAIL iff delta <= 0 or share >= 0.5; else INDETERMINATE.

    python3 scripts/research/rostered_leg_replay.py --out DIR [--legs a,b] [--work DIR] [--mode book|tradestate]
    python3 scripts/research/rostered_leg_replay.py --self-test
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import regime_r2_family_router as RR  # noqa: E402

FAMILIES = ("trend", "pullback", "fade", "squeeze")
WINDOW = ("2020-09-01", "2026-10-26")          # pinned: the R2-R3 corpus window
FETCH_DAYS = 2350
TS_MIN_N = 20
RULE_TS = {"id": "RULE-REGIME-TRADESTATE-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05, "min_years_positive": 4,
           "n_test_years": 5, "fail_random_share": 0.5}
RULE = {"id": "RULE-REGIME-R3-CONFIRM-ROSTERED-20261125", "min_delta_r": 0.01, "min_t": 2.0, "max_random_share": 0.05 / 3,
        "min_years_positive": 4, "n_test_years": 5, "fail_random_share": 0.5}


def rostered_legs(root: Path = REPO) -> Dict[str, Dict[str, Any]]:
    """Crypto legs on a `mode: live` book whose cfg classifies into FAMILIES: {leg: {cfg, book, harness}}."""
    import yaml
    import regime_debt_matrix as rdm
    spec = importlib.util.spec_from_file_location("mlc", root / "scripts/ci/check_research_queue_ml_consumer.py")
    mlc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mlc)
    book = mlc.books(root)
    st = yaml.safe_load((root / "config/strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    out = {}
    for leg, b in sorted(book.items()):
        cfg = st.get(leg)
        if not isinstance(cfg, dict):
            continue
        sym = (cfg.get("symbols") or [None])[0]
        h = rdm.classify(cfg)
        if str(sym).endswith("USDT") and h in FAMILIES:
            out[leg] = {"cfg": cfg, "book": b, "harness": h}
    return out


def replay_leg(leg: str, cfg: Dict[str, Any], work: Path) -> Dict[str, Any]:
    import exit_lever_ablation as ela
    work.mkdir(parents=True, exist_ok=True)
    csv, emit, jout, log = (str(work / f"{leg}{x}") for x in (".csv", "__trades.jsonl", "__bt.json", ".log"))
    try:
        feed = ela.fetch_candles(leg, cfg, FETCH_DAYS, csv)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        return {"state": "fetch_failed", "why": f"{type(e).__name__}: {e}"[:300]}
    argv, omitted = ela.build_arm_argv(leg, cfg, csv, str(feed["resample"]), emit, jout, [], WINDOW[0], WINDOW[1])
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO), timeout=3600, check=False).returncode
    if rc != 0 or not Path(jout).is_file():
        return {"state": "harness_failed", "why": f"exit {rc}", "argv": argv[1:]}
    trades = ela._load_trades(emit) if Path(emit).is_file() else []
    return {"state": "measured", "n": len(trades), "net_r": round(float(sum(t.get("net_r") or 0.0 for t in trades)), 3),
            "omitted_levers": omitted, "argv": argv[1:], "trades": trades}


def trades_frame(per_leg: Dict[str, Dict[str, Any]], cfgs: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for leg, r in per_leg.items():
        if r.get("state") != "measured":
            continue
        sym, tf = cfgs[leg]["cfg"]["symbols"][0], str(cfgs[leg]["cfg"].get("timeframe"))
        for t in r["trades"]:
            if t.get("net_r") is None or t.get("entry_time") is None:
                continue
            rows.append((leg, sym, tf, str(t["entry_time"])[:19], str(t.get("direction")), float(t["net_r"]), str(t.get("exit_time") or "")[:19]))
    df = pd.DataFrame(rows, columns=["family", "symbol", "tf", "entry_time", "direction", "net_r", "exit_time"])
    df["ts"] = pd.to_datetime(df.entry_time, utc=True, errors="coerce")
    df["xts"] = pd.to_datetime(df.exit_time, utc=True, errors="coerce")
    return df.dropna(subset=["ts"])


def daily_closes(csv: Path) -> pd.Series:
    """Daily closes (UTC) from a fetched candle CSV (fetch_backtest_candles output); the time column is the first datetime-like column."""
    d = pd.read_csv(csv)
    cols = {c.lower(): c for c in d.columns}
    tcol = next((cols[c] for c in ("timestamp", "time", "datetime", "date", "open_time") if c in cols), d.columns[0])
    t = d[tcol]
    num = pd.api.types.is_numeric_dtype(t)
    ts = pd.to_datetime(t, unit="ms", utc=True) if num and t.max() > 1e11 else (
        pd.to_datetime(t, unit="s", utc=True) if num else pd.to_datetime(t, utc=True, errors="coerce"))
    c = d[cols.get("close", "close")].astype(float)
    return pd.Series(c.to_numpy(), index=ts).dropna().sort_index().resample("1D").last().dropna()


def symbol_cell(close: pd.Series, when: pd.Series) -> pd.Series:
    """Cell of the traded symbol at each entry: last daily close strictly before the entry DAY."""
    sma = close.rolling(50).mean()
    rv = np.log(close).diff().rolling(20).std()
    med = rv.rolling(365, min_periods=180).median()
    st = pd.DataFrame({"up": close > sma, "hv": rv > med, "ok": sma.notna() & med.notna()})
    st.index = st.index + pd.Timedelta(days=1)                  # a day's state is usable from the NEXT day on
    idx = st.index.searchsorted(when.dt.floor("D").to_numpy(), side="right") - 1
    out = []
    for i in idx:
        if i < 0 or not st.ok.iloc[i]:
            out.append(None)
        else:
            out.append(f"{'up' if st.up.iloc[i] else 'dn'}_{'hv' if st.hv.iloc[i] else 'lv'}")
    return pd.Series(out, index=when.index)


def tradestate_raw(tr: pd.DataFrame) -> np.ndarray:
    """Per trade: TILT by the sign of the mean net R of the same leg x direction x cell trades that EXITED before this entry (>= TS_MIN_N)."""
    raw = np.ones(len(tr))
    for _, g in tr.groupby(["family", "direction"]):
        g = g.sort_values("ts")
        for pos, (i, row) in enumerate(g.iterrows()):
            if row.cell is None:
                continue
            prior = g[(g.cell == row.cell) & (g.xts < row.ts)]
            if len(prior) >= TS_MIN_N:
                raw[tr.index.get_loc(i)] = RR.TILT[0] if prior.net_r.mean() > 0 else RR.TILT[1]
    return raw


def ts_weights(tr: pd.DataFrame, raw: np.ndarray) -> np.ndarray:
    key = tr.family + "|" + tr.ts.dt.strftime("%Y-%m")
    s = pd.Series(raw, index=tr.index).groupby(key).transform("mean").to_numpy()
    return raw / s


def grade_tradestate(tr: pd.DataFrame, closes: Dict[str, pd.Series], seed: int = RR.SEED) -> Dict[str, Any]:
    tr = tr.copy().reset_index(drop=True)
    cells = pd.Series([None] * len(tr), dtype=object)
    for leg, g in tr.groupby("family"):
        if leg in closes:
            cells.loc[g.index] = symbol_cell(closes[leg], g.ts).to_numpy()
    tr["cell"] = cells
    test = tr[tr.ts >= pd.Timestamp(RR.TEST_START, tz="UTC")]
    raw_all = tradestate_raw(tr)
    t = test.copy()
    raw = raw_all[t.index.to_numpy()]
    t = t.reset_index(drop=True)
    w = ts_weights(t, raw)
    r = t.net_r.to_numpy(float)
    n = len(t)
    delta = float(((w - 1.0) * r).sum() / n)
    wk = t.ts.dt.strftime("%G-%V").to_numpy()
    ws = pd.Series((w - 1.0) * r).groupby(wk).sum()
    wn = pd.Series(np.ones(n)).groupby(wk).sum()
    rng = np.random.default_rng(seed)
    W = len(ws)
    boots = [float(ws.to_numpy()[ix].sum() / wn.to_numpy()[ix].sum()) for ix in (rng.integers(0, W, W) for _ in range(RR.N_BOOT))]
    se = float(np.std(boots))
    key = (t.family + "|" + t.ts.dt.strftime("%Y-%m")).to_numpy()
    groups = [np.flatnonzero(key == k) for k in np.unique(key)]
    draws = []
    for _ in range(RR.N_RANDOM):
        pr = raw.copy()
        for ii in groups:
            pr[ii] = pr[ii][rng.permutation(len(ii))]
        draws.append(float(((ts_weights(t, pr) - 1.0) * r).sum() / n))
    draws = np.array(draws)
    share = float(np.mean(draws >= delta))
    yrs = {str(y): round(float(((w - 1.0) * r)[t.ts.dt.year.to_numpy() == y].sum() / max((t.ts.dt.year == y).sum(), 1)), 4)
           for y in sorted(t.ts.dt.year.unique())}
    g = {"n_trades": n, "money_base": round(float(r.mean()), 5), "money_arm": round(float((w * r).mean()), 5), "delta": round(delta, 5),
         "se_week_boot": round(se, 5), "t": round(delta / se, 3) if se > 0 else None,
         "random": {"draws": RR.N_RANDOM, "kind": "raw tilts permuted within leg x month", "mean": round(float(draws.mean()), 5),
                    "p95": round(float(np.percentile(draws, 95)), 5), "share_ge_arm": round(share, 4)},
         "yearly_delta": yrs, "share_tilted": round(float((raw != 1.0).mean()), 4), "share_up_tilt": round(float((raw == RR.TILT[0]).mean()), 4),
         "cell_counts_test": {str(k): int(v) for k, v in t.cell.value_counts(dropna=False).items()}}
    v, g["checks"] = RR.tilt_verdict(g, RULE_TS)
    g["verdict"] = v
    return {"arms": {"tradestate": g}, "verdict": v, "n_legs": int(t.family.nunique())}


def grade(trades: pd.DataFrame, btc: Optional[pd.Series] = None, seed: int = RR.SEED) -> Dict[str, Any]:
    S, N = RR.weekly_books(trades, "family")
    f = RR.features(S, N)
    test_weeks = [w for w in S.index if w >= pd.Timestamp(RR.TEST_START)]
    btc = btc if btc is not None else RR.btc_daily()
    raws = {"nostate": RR.state_raw(f, pd.Series("all", index=S.index)), "advol": RR.state_raw(f, RR.cells_advol(btc, list(S.index))),
            "hmm2": RR.state_raw(f, RR.cells_hmm2(btc, list(S.index))[0])}
    arms, verdicts = {}, {}
    for k, raw in raws.items():
        g = RR.grade_tilt(f, test_weeks, np.random.default_rng(seed), raw_all=raw)
        v, g["checks"] = RR.tilt_verdict(g, RULE)
        g["verdict"] = verdicts[k] = v
        arms[k] = g
    sums = {k: RR.tilt_week_sums(f, test_weeks, r) for k, r in raws.items()}
    decomp = {f"{k}_vs_nostate": RR.paired_delta(sums[k], sums["nostate"], np.random.default_rng(seed + 1)) for k in ("advol", "hmm2")}
    uv = "pass" if "pass" in verdicts.values() else ("fail" if all(v == "fail" for v in verdicts.values()) else "indeterminate")
    return {"arms": arms, "decomp_reported": decomp, "verdict": uv, "n_books": int(S.shape[1]), "n_test_weeks": len(test_weeks)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/rostered_replay")
    ap.add_argument("--work", default="")
    ap.add_argument("--legs", default="")
    ap.add_argument("--unit", default="")
    ap.add_argument("--mode", choices=["book", "tradestate"], default="book")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work) if a.work else out / "work"
    cfgs = rostered_legs()
    if a.legs:
        cfgs = {k: v for k, v in cfgs.items() if k in set(a.legs.split(","))}
    per = {}
    for leg, c in cfgs.items():
        per[leg] = replay_leg(leg, c["cfg"], work)
        print(json.dumps({"leg": leg, "state": per[leg]["state"], "n": per[leg].get("n")}), flush=True)
    tr = trades_frame(per, cfgs)
    tr = tr[(tr.ts >= pd.Timestamp(WINDOW[0], tz="UTC")) & (tr.ts < pd.Timestamp(WINDOW[1], tz="UTC"))]
    (out / "legs").mkdir(exist_ok=True)
    for leg, r in per.items():
        if r.get("state") == "measured":
            with open(out / "legs" / f"{leg}__trades.jsonl", "w", encoding="utf-8") as fh:
                for t in r["trades"]:
                    fh.write(json.dumps(t, default=str) + "\n")
    if a.mode == "tradestate":
        closes = {leg: daily_closes(work / f"{leg}.csv") for leg, r in per.items() if r.get("state") == "measured" and (work / f"{leg}.csv").exists()}
        m = grade_tradestate(tr, closes) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE_TS
    else:
        m = grade(tr) if len(tr) else {"verdict": "indeterminate", "why": "no measured trades"}
        rule_used = RULE
    legs_report = {k: {x: v[x] for x in v if x != "trades"} | {"book": cfgs[k]["book"], "harness": cfgs[k]["harness"]} for k, v in per.items()}
    pop = (f"{sum(1 for v in per.values() if v.get('state') == 'measured')} of {len(per)} rostered crypto legs ({'/'.join(FAMILIES)} harnesses) "
           f"replayed with DECLARED params over {WINDOW[0]}..{WINDOW[1]} ({len(tr)} trades, harness net_r full cost stack); books = leg x direction; "
           f"test weeks {RR.TEST_START}..{WINDOW[1]}")
    why = "; ".join(f"{k}: {g['verdict']} delta {g['delta']:+.4f} t {g['t']} share {g['random']['share_ge_arm']}" for k, g in (m.get("arms") or {}).items())
    summ = {"schema": "rostered_leg_replay/1", "unit": a.unit, "mode": a.mode, "verdict": m["verdict"], "why": why, "rule": rule_used, "population": pop,
            "window": WINDOW, "legs": legs_report, "measurement": m, "git_sha": RR._git_sha(), "elapsed_s": round(time.time() - t0), "read_state": "measured"}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str) + "\n")
    (out / "verdict.json").write_text(json.dumps({"verdict": m["verdict"], "read_state": "measured", "n": int(len(tr)), "note": why, "population": pop,
                                                  "rule": rule_used, "data_window": {"start": WINDOW[0], "end": WINDOW[1], "legs": sorted(per)},
                                                  "measurement": m}, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": m["verdict"], "why": why}), flush=True)
    return 0


def _self_test() -> int:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")

    legs = rostered_legs()
    check("rostered legs found in the four families", len(legs) >= 10 and all(v["harness"] in FAMILIES for v in legs.values()))
    check("every rostered leg is a crypto symbol", all(str(v["cfg"]["symbols"][0]).endswith("USDT") for v in legs.values()))
    per = {"L1": {"state": "measured", "trades": [{"entry_time": "2023-01-02 00:00:00", "direction": "long", "net_r": 1.0}]},
           "L2": {"state": "harness_failed"}}
    tf = trades_frame(per, {"L1": {"cfg": {"symbols": ["BTCUSDT"], "timeframe": "1h"}}, "L2": {"cfg": {"symbols": ["X"]}}})
    check("trades frame keeps measured legs only, family = leg", list(tf.family) == ["L1"] and tf.net_r.iloc[0] == 1.0)
    # the grade runs the router on leg books: a synthetic BTC-trend-conditioned edge must be found by advol
    days = pd.date_range("2019-01-01", "2026-10-26", freq="1D", tz="UTC")
    rng = np.random.default_rng(5)
    regime = np.repeat(rng.choice([1.0, -1.0], size=len(days) // 60 + 1), 60)[:len(days)]
    btc = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.01, len(days)))), index=days)
    syn = RR._synthetic(persistent=False)
    up = btc > btc.rolling(50).mean()
    st = up.reindex(syn.ts.dt.floor("D")).fillna(False).to_numpy()
    syn = syn.assign(net_r=syn.net_r + 0.3 * np.where(syn.direction == "long", 1.0, -1.0) * np.where(st, 1.0, -1.0))
    g = grade(syn, btc=btc)
    check("grade: advol finds a trend-conditioned edge on leg books", g["arms"]["advol"]["delta"] > 0.02 and g["arms"]["advol"]["random"]["share_ge_arm"] <= 0.05)
    check("grade: decomp reported", "advol_vs_nostate" in g["decomp_reported"])
    # tradestate: a leg whose edge sign follows its OWN symbol's trend must be found; and the prior uses EXITED trades only
    sym = pd.Series(100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.01, len(days)))), index=days)
    ents = pd.date_range("2020-09-02", "2026-10-20", freq="13h", tz="UTC")
    upx = (sym > sym.rolling(50).mean()).shift(1).reindex(ents.floor("D")).fillna(False).to_numpy()
    r0 = rng.normal(0, 1, len(ents)) + np.where(upx, 0.3, -0.3)
    trd = pd.DataFrame({"family": "L", "symbol": "S", "tf": "1h", "entry_time": ents.astype(str), "direction": "long", "net_r": r0,
                        "exit_time": (ents + pd.Timedelta(hours=10)).astype(str), "ts": ents, "xts": ents + pd.Timedelta(hours=10)})
    gt = grade_tradestate(trd, {"L": sym})
    check("tradestate: an own-symbol trend edge is found and beats the permutation control",
          gt["arms"]["tradestate"]["delta"] > 0.02 and gt["arms"]["tradestate"]["random"]["share_ge_arm"] <= 0.05)
    tiny = trd.iloc[:30].copy()
    tiny["xts"] = tiny.ts + pd.Timedelta(days=3650)              # nothing exits before any later entry
    tiny["cell"] = "up_lv"
    check("tradestate: a trade still open is never in a prior", (tradestate_raw(tiny.reset_index(drop=True)) == 1.0).all())
    print("SELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
