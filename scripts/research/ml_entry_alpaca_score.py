#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-bdc2-01.yaml (lane ALPACA-LIVE-ACTIVITY-ML, deliverable B1); spec docs/research/alpaca-live-activity-2026-11-01.md section B
"""Score THE frozen ENTRY model (c692-01 final fit, served artifact ml-decision-entry-v1) on alpaca_live's symbols.

NOT a new model and NOT a re-fit (operator 2026-11-01 ~10:40Z: "the supra-symbol mls are for all symbols on all
accounts"). The artifact is loaded as-is (its sha256 is recorded); the account's constraints are EXECUTION RULES:

* SHORT -> nothing on alpaca_live (cash account, venue shorting disabled, ``side_filter: long``). The model still
  picks its side exactly as served (``ml_entry.decide``: the larger of the two regressed net R vs tau); a decision whose
  side is SHORT is not taken on the long-only book. The mirror read (both sides) is REPORTED.
* Market hours: bars are Yahoo 1h REGULAR-session bars (pre/post excluded). A decision is taken at the CLOSE of an RTH
  bar whose UTC close hour h has ``floor(h) % 4 == 0`` -- the model's own 4-hourly clock (``decision_every_h`` 4), applied
  to the bars that exist; entry at the NEXT RTH bar's open (overnight / weekend gaps are real: a gap through the stop
  fills at the open).
* Horizon: 24 BARS (the model's ``horizon_h`` 24, counted in bars as the harness labels it), time stop at bar 24's close.
* Bracket: SL 2 x ATR14, TP 3 x ATR14 (the scored reference bracket). Tie -> SL. TP fills at the TP price.
* Costs (Alpaca): fee ``resolve_fee_bps_roundtrip('SPY')`` (0.0, commission-free venue), slippage
  ``resolve_cost_policy('SPY')`` (5.0 bps round trip, a PROVISIONAL placeholder), REGULATORY 0.5 bps round trip (SEC
  section 31 27.80 USD per million of sale notional = 0.278 bps + FINRA TAF, rounded up), funding 0.

Features: the frozen model's 20, computed by ``scripts/research/ml_decision_entry.features_symbol`` on the equity's own
RTH bar sequence (``ret_k`` / ``vol24`` / ``vol_ratio`` / ``range_pos`` / ``vol_z`` count BARS). The cross-sectional and
BTC features (``xs_rank_ret24``, ``btc_ret24``, ``btc_vol24``, ``breadth_up24``, ``rel_vol``) are defined by the model
against its 60-perp ``xs_reference``; they are read at the latest perp bar whose close is <= the equity bar's close,
i.e. the equity's 24-bar return is ranked among the 60 perps' 24h returns. No feature is missing (the model has no
funding / OI input), so no missing-feature handling is needed.

    python3 scripts/research/ml_entry_alpaca_score.py run --model /path/model.json --cache /tmp/c --out /tmp/o
    python3 scripts/research/ml_entry_alpaca_score.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

import ml_decision_entry as E  # noqa: E402  the c692 harness: bracket_outcome, features_symbol, _fetch_month

SCHEMA = "ml_entry_alpaca_score/1"
HOLDOUT_START, HOLDOUT_END = "2025-10-01", "2026-09-30"     # the c692 sealed window, read ONCE here
FETCH_START = "2025-05-01"                                    # >= 337 RTH bars of feature history before the window
H = 24
REGULATORY_BPS = 0.5
N_FLOOR = 30                                                  # the c692-06 traded-subset floor
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"


def _account_symbols(account_id: str) -> list[str]:
    from src.config.accounts_loader import load_accounts_dict
    return [str(s) for s in ((load_accounts_dict() or {}).get(account_id, {}).get("symbols") or [])]


def live_symbols() -> list[str]:
    return _account_symbols("alpaca_live")


def mirror_symbols() -> list[str]:
    return _account_symbols("alpaca_portfolio")


def fetch_equity_1h(sym: str, cache: Path) -> pd.DataFrame:
    import requests
    p = cache / f"eq_{sym}.pkl"
    if p.exists():
        return pd.read_pickle(p)
    p1 = int(pd.Timestamp(FETCH_START, tz="UTC").timestamp())
    p2 = int(pd.Timestamp("2026-10-31", tz="UTC").timestamp())
    last = None
    for wait in (0, 2, 4, 8, 16):
        time.sleep(wait)
        try:
            r = requests.get(_YAHOO.format(sym=sym), timeout=60, headers={"User-Agent": "Mozilla/5.0 (research)"},
                             params={"period1": p1, "period2": p2, "interval": "60m", "includePrePost": "false"})
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"ts": pd.to_datetime(res["timestamp"], unit="s", utc=True), "open": q["open"],
                               "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
            df = df.dropna(subset=["open", "high", "low", "close"])
            df = df[(df.open > 0) & (df.close > 0)].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
            df["volume"] = df["volume"].fillna(0).astype(float)
            # bar close time: the next bar's open within the session, else open + 1h capped at the 16:00 ET close
            et = df.ts.dt.tz_convert("America/New_York")
            rth = (et.dt.hour * 60 + et.dt.minute >= 570) & (et.dt.hour * 60 + et.dt.minute < 960)
            df, et = df[rth.to_numpy()].reset_index(drop=True), et[rth.to_numpy()].reset_index(drop=True)
            session_close = (et.dt.normalize() + pd.Timedelta(hours=16)).dt.tz_convert("UTC")
            df["close_ts"] = pd.concat([df.ts + pd.Timedelta(hours=1), session_close], axis=1).min(axis=1)
            cache.mkdir(parents=True, exist_ok=True)
            df.to_pickle(p)
            return df
        except Exception as e:  # noqa: BLE001  # allow-silent: retried with backoff; final failure raised
            last = e
    raise RuntimeError(f"yahoo 1h fetch failed {sym}: {last}")


def fetch_perps(cache: Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    import concurrent.futures as cf
    months = E._months(FETCH_START, HOLDOUT_END)

    def one(sym):
        p = cache / f"perp_{sym}.pkl"
        if p.exists():
            return sym, pd.read_pickle(p)
        frames = [d for m in months if (d := E._fetch_month(sym, m)) is not None]
        if not frames:
            return sym, None
        df = pd.concat(frames, ignore_index=True)
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        df = df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        df.to_pickle(p)
        return sym, df

    cache.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(8) as ex:
        return {s: d for s, d in ex.map(one, symbols) if d is not None}


def perp_context(perps: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per perp-bar CLOSE time: ret24/vol24 of every reference perp -> btc_ret24, btc_vol24, breadth, median vol, and
    the per-symbol ret24 matrix (for ranking an equity among them)."""
    r24, v24 = {}, {}
    for s, df in perps.items():
        f = E.features_symbol(df)
        idx = df.ts + pd.Timedelta(hours=1)
        r24[s] = pd.Series(f["ret24_raw"].to_numpy(), index=idx)
        v24[s] = pd.Series(f["vol24"].to_numpy(), index=idx)
    R, V = pd.DataFrame(r24), pd.DataFrame(v24)
    return R, V


def equity_rows(sym: str, df: pd.DataFrame, R: pd.DataFrame, V: pd.DataFrame, slip_bps: float, fee_bps: float) -> pd.DataFrame:
    f = E.features_symbol(df[["ts", "open", "high", "low", "close", "volume"]])
    # hour / dow are the model's "close hour" features: read from the bar's real close time
    f["hour"] = df.close_ts.dt.hour.to_numpy()
    f["dow"] = df.close_ts.dt.dayofweek.to_numpy()
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    atr = pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy()
    N = len(df)
    close_ts = df.close_ts
    decision = close_ts.dt.hour % 4 == 0          # the model clock: floor(UTC close hour) % 4 == 0
    cand = np.where(decision.to_numpy() & ~np.isnan(atr))[0]
    cand = cand[cand + H < N]
    win = cand[:, None] + np.arange(1, H + 1)[None, :]
    entry = o[win][:, 0]
    a = atr[cand]
    risk = 2.0 * a
    out = {"i": cand, "ts": close_ts.to_numpy()[cand], "symbol": sym, "entry": entry, "atr": a}
    for name, side in (("long", 1), ("short", -1)):
        px, j, reason = E.bracket_outcome(o[win], h[win], lo[win], c[win], entry, a, side)
        gross = side * (px - entry) / risk
        per_r = ((np.abs(entry) + np.abs(px)) / 2.0) / risk
        cost = (fee_bps + slip_bps + REGULATORY_BPS) / 1e4 * per_r
        out[f"net_{name}"], out[f"gross_{name}"], out[f"cost_{name}"] = gross - cost, gross, cost
        out[f"reason_{name}"], out[f"bars_{name}"] = reason, j
    rows = pd.DataFrame(out).join(f.drop(columns=["ts"]), on="i")
    # cross-sectional context at the latest perp bar whose close <= this equity bar's close
    t = pd.to_datetime(rows.ts, utc=True)
    pos = R.index.searchsorted(t, side="right") - 1
    ok = pos >= 0
    Rv, Vv = R.to_numpy(), V.to_numpy()
    rr, vv = Rv[np.clip(pos, 0, None)], Vv[np.clip(pos, 0, None)]
    own = rows["ret24_raw"].to_numpy()
    valid = ~np.isnan(rr)
    less = ((rr < own[:, None]) & valid).sum(1)
    eq = ((rr == own[:, None]) & valid).sum(1)
    nval = valid.sum(1)
    rows["xs_rank_ret24"] = np.where(nval > 0, (less + 0.5 * eq + 1.0) / (nval + 1.0), np.nan)  # rank among refs + itself
    bi = list(R.columns).index("BTCUSDT")
    rows["btc_ret24"] = rr[:, bi]
    rows["btc_vol24"] = vv[:, bi]
    rows["breadth_up24"] = np.where(nval > 0, ((rr > 0) & valid).sum(1) / np.maximum(nval, 1), np.nan)
    rows["rel_vol"] = rows["vol24"].to_numpy() / np.nanmedian(vv, axis=1)
    rows.loc[~ok, ["xs_rank_ret24", "btc_ret24"]] = np.nan
    rows["n_reference"] = nval
    return rows


def load_model(path: Path) -> dict:
    import lightgbm as lgb
    art = json.loads(path.read_text())
    return {"meta": {k: v for k, v in art.items() if k != "booster_txt"},
            "long": lgb.Booster(model_str=art["booster_txt"]["long"]),
            "short": lgb.Booster(model_str=art["booster_txt"]["short"])}


def take(rows: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, tau: float, long_only: bool) -> pd.DataFrame:
    """The served decide() + one position per symbol. long_only: a SHORT decision is not taken (no position opens)."""
    t = rows.assign(p_long=pl, p_short=ps).sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for r in g.itertuples(index=False):
            if r.i <= busy:
                continue
            side = "long" if r.p_long >= r.p_short else "short"
            best = r.p_long if side == "long" else r.p_short
            if best <= tau or (long_only and side == "short"):
                continue
            out.append((sym, r.ts, side, getattr(r, f"net_{side}"), getattr(r, f"gross_{side}"),
                        getattr(r, f"cost_{side}"), int(getattr(r, f"reason_{side}")), best))
            busy = r.i + getattr(r, f"bars_{side}")
    return pd.DataFrame(out, columns=["symbol", "ts", "side", "net_r", "gross_r", "cost_r", "reason", "pred"])


def summ(tk: pd.DataFrame) -> dict:
    if tk.empty:
        return {"n": 0, "mean_net_r": None, "n_symbols": 0}
    rng = np.random.default_rng(20261101)
    bs = [tk.net_r.sample(len(tk), replace=True, random_state=int(rng.integers(1 << 31))).mean() for _ in range(500)]
    return {"n": len(tk), "mean_net_r": float(tk.net_r.mean()), "sum_net_r": float(tk.net_r.sum()),
            "mean_gross_r": float(tk.gross_r.mean()), "mean_cost_r": float(tk.cost_r.mean()),
            "n_symbols": int(tk.symbol.nunique()),
            "by_side": {k: {"n": len(g), "mean_net_r": float(g.net_r.mean())} for k, g in tk.groupby("side")},
            "exit_reason_counts": {{0: "time", 1: "sl", 2: "tp"}[k]: int(v) for k, v in tk.reason.value_counts().items()},
            "per_symbol": {k: {"n": len(g), "mean_net_r": round(float(g.net_r.mean()), 4)} for k, g in tk.groupby("symbol")},
            "by_month": {k: {"n": int(v.count()), "mean_net_r": round(float(v.mean()), 4)} for k, v in
                         tk.assign(m=pd.to_datetime(tk.ts, utc=True).dt.strftime("%Y-%m")).groupby("m").net_r},
            "bootstrap_ci95_reported_not_gating": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}


def verdict(m: dict) -> tuple[str, str]:
    if m["n"] < N_FLOOR:
        return "indeterminate", f"alpaca_live long-only held-out n={m['n']} < {N_FLOOR}"
    if m["mean_net_r"] >= 0:
        return "pass", f"alpaca_live long-only held-out mean net R per decision {m['mean_net_r']:+.4f} >= 0 at n={m['n']}"
    return "fail", f"alpaca_live long-only held-out mean net R per decision {m['mean_net_r']:+.4f} < 0 at n={m['n']}"


def run(a) -> int:
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    t0 = time.time()
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mpath = Path(a.model)
    sha = hashlib.sha256(mpath.read_bytes()).hexdigest()
    model = load_model(mpath)
    meta = model["meta"]
    tau, feats = float(meta["tau"]), list(meta["features"])
    slip, fund = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    perps = fetch_perps(cache, list(meta["xs_reference"]))
    R, V = perp_context(perps)
    live, mirror = live_symbols(), mirror_symbols()
    syms = sorted(set(live) | set(mirror))
    fetch_rep, frames = {}, []
    for s in syms:
        try:
            df = fetch_equity_1h(s, cache)
            fetch_rep[s] = {"rows": len(df), "first": str(df.ts.min()), "last": str(df.ts.max())}
            frames.append(equity_rows(s, df, R, V, slip, fee))
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded per symbol, never dropped
            fetch_rep[s] = {"rows": 0, "error": str(e)[:200]}
    tab = pd.concat(frames, ignore_index=True)
    tab["ts"] = pd.to_datetime(tab.ts, utc=True)
    hs, he = pd.Timestamp(HOLDOUT_START, tz="UTC"), pd.Timestamp(HOLDOUT_END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].replace([np.inf, -np.inf], np.nan).dropna(subset=feats + ["net_long"])
    # provenance: predict -- Booster.predict is the regressed net R of that side (the served model), not a probability
    pl = model["long"].predict(test[feats])
    ps = model["short"].predict(test[feats])
    tk_live = take(test[test.symbol.isin(live)], pl[test.symbol.isin(live).to_numpy()],
                   ps[test.symbol.isin(live).to_numpy()], tau, long_only=True)
    m = summ(tk_live)
    v, why = verdict(m)
    msk = test.symbol.isin(mirror).to_numpy()
    mirror_both = summ(take(test[msk], pl[msk], ps[msk], tau, long_only=False))
    live_both = summ(take(test[test.symbol.isin(live)], pl[test.symbol.isin(live).to_numpy()],
                          ps[test.symbol.isin(live).to_numpy()], tau, long_only=False))
    al = test[test.symbol.isin(live)].sort_values(["symbol", "i"])
    alw = []
    for sym, g in al.groupby("symbol"):
        busy = -1
        for r in g.itertuples(index=False):
            if r.i > busy:
                alw.append(r.net_long)
                busy = r.i + r.bars_long
    row = {
        "schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": v, "note": why,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision_rule": {"id": "RULE-RQ20261101-bdc2-01-ENTRY-ON-ALPACA", "registered_at": "2026-11-01",
                          "registered_before_run": True},
        "population": {"n": m["n"], "description": f"frozen ml-decision-entry-v1 (tau {tau}) LONG decisions on alpaca_live "
                       f"symbols {live}, Yahoo 1h RTH bars, held-out {HOLDOUT_START}..{HOLDOUT_END}, net of fee {fee} + "
                       f"slippage {slip} + regulatory {REGULATORY_BPS} bps round trip, funding {fund}"},
        "variants_read_on_this_heldout": 1,
        "measurement": {"schema": SCHEMA, "model_sha256": sha, "model_meta": {k: v for k, v in meta.items() if k != "xs_reference"},
                        "tau": tau, "alpaca_live_long_only": m,
                        "reported_alpaca_live_both_sides": live_both,
                        "reported_mirror_symbols_both_sides": mirror_both,
                        "reported_always_long_same_mechanics": {"n": len(alw), "mean_net_r": float(np.mean(alw)) if alw else None},
                        "decision_rows": int(len(test)), "decision_rows_by_symbol": test.groupby("symbol").size().to_dict(),
                        "perp_reference_loaded": len(perps), "median_n_reference": float(test.n_reference.median()),
                        "fetch": fetch_rep, "costs": {"fee_bps": fee, "slippage_bps": slip, "regulatory_bps": REGULATORY_BPS,
                                                      "funding_bps": fund}},
        "produced_by": {"tool": "python3 scripts/research/ml_entry_alpaca_score.py", "where": a.where,
                        "runtime_s": round(time.time() - t0, 1)},
    }
    p = out / f"{a.unit}.json"
    p.write_text(json.dumps(row, indent=1, default=str))
    print(f"VERDICT {v}: {why}\nwrote {p}", flush=True)
    return 0


def self_test() -> int:
    # decision clock: UTC close hours divisible by 4 only
    ts = pd.to_datetime(["2025-11-03 14:30", "2025-11-03 15:30", "2025-11-03 20:30"], utc=True)
    df = pd.DataFrame({"close_ts": ts + pd.Timedelta(hours=1)})
    hit = ((df.close_ts.dt.hour % 4) == 0).tolist()
    assert hit == [False, True, False], hit       # closes 15:30, 16:30, 21:30 UTC -> only 16:30
    rows = pd.DataFrame({"symbol": "X", "i": [0, 1, 40], "ts": pd.Timestamp("2025-11-03", tz="UTC"),
                         "net_long": [1.0, 1.0, 0.5], "gross_long": [1.0, 1, .5], "cost_long": [0.0] * 3,
                         "reason_long": [2, 2, 2], "bars_long": [24, 24, 24], "net_short": [9.0] * 3,
                         "gross_short": [9.0] * 3, "cost_short": [0.0] * 3, "reason_short": [2] * 3, "bars_short": [24] * 3})
    tk = take(rows, np.array([0.2, 0.2, 0.0]), np.array([0.0, 0.0, 0.5]), 0.1, long_only=True)
    assert tk.net_r.tolist() == [1.0], tk          # row 1 blocked (busy), row 3 is a SHORT -> nothing on a cash book
    tk2 = take(rows, np.array([0.2, 0.2, 0.0]), np.array([0.0, 0.0, 0.5]), 0.1, long_only=False)
    assert tk2.side.tolist() == ["long", "short"], tk2
    assert verdict({"n": 29, "mean_net_r": 1.0})[0] == "indeterminate"
    assert verdict({"n": 30, "mean_net_r": 0.0})[0] == "pass"
    assert verdict({"n": 30, "mean_net_r": -0.01})[0] == "fail"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--cache", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--unit", default="RQ-20261101-bdc2-01")
    r.add_argument("--where", default="local")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    return run(a) if a.cmd == "run" else 2


if __name__ == "__main__":
    sys.exit(main())
