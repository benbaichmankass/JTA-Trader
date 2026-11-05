#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-bdc2-01.yaml (lane ALPACA-LIVE-ACTIVITY-ML, deliverable B1); spec docs/research/alpaca-live-activity-2026-11-01.md section B
# wiring: research/queue/RQ-20261104-a41f-01.yaml (lane ML-ENTRY-ALL-ACCOUNTS): --side-rule restricted / --session-gate / window flags
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

Row ML-ENTRY-ALL-ACCOUNTS (2026-11-04) adds three OPT-IN flags that score exactly what the per-account profile
(``src/runtime/ml_entry_profile.py``) does live; every default is the bdc2-01 read, byte-identical:

* ``--side-rule restricted``: on the long-only book the argmax runs over the ALLOWED side only (``long`` when
  ``p_long > tau``), the live ``side_filter: long`` profile rule; ``served`` (default) = SHORT -> nothing.
* ``--session-gate``: a decision is taken only when ``market_hours.is_market_open('us_equity')`` holds at the bar's close
  AND at close + 24h (the live ``session: us_equity`` refusals ``market_closed`` / ``market_closes_before_max_hold``).
* ``--holdout-start`` / ``--holdout-end`` / ``--fetch-start``: the scored window (default the c692 sealed window).
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
    p = cache / (f"eq_{sym}.pkl" if FETCH_START == "2025-05-01" else f"eq_{sym}_{FETCH_START}.pkl")
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
        p = cache / (f"perp_{sym}.pkl" if (FETCH_START, HOLDOUT_END) == ("2025-05-01", "2026-09-30")
                     else f"perp_{sym}_{FETCH_START}_{HOLDOUT_END}.pkl")
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


def daily_structure(df: pd.DataFrame, pivot_n: int):
    """Session-aware DAILY structure for hourly RTH bars (STRUCTURE-EXITS-DEFAULT).
    Returns (StructureLevels over daily bars, daily ATR14 array, t_map). ``t_map[k]`` = index of the last
    COMPLETED session before bar k's own session (strictly earlier: the session still forming is never read), -1 if none."""
    from src.runtime.structure_levels import StructureLevels
    sess = df.ts.dt.tz_convert("America/New_York").dt.date
    codes = pd.factorize(sess)[0]                      # session index per hourly bar, ascending in time
    g = df.assign(_s=codes).groupby("_s")
    dh, dl, dc = g["high"].max().to_numpy(float), g["low"].min().to_numpy(float), g["close"].last().to_numpy(float)
    pc = np.r_[np.nan, dc[:-1]]
    tr = np.nanmax(np.vstack([dh - dl, np.abs(dh - pc), np.abs(dl - pc)]), axis=0)
    datr = pd.Series(tr).rolling(14, min_periods=14).mean().to_numpy()
    return StructureLevels(dh, dl, pivot_n), datr, codes - 1


def equity_rows(sym: str, df: pd.DataFrame, R: pd.DataFrame, V: pd.DataFrame, slip_bps: float, fee_bps: float,
                structure_pivot: int = 0) -> pd.DataFrame:
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
    if structure_pivot:
        from ml_structure_bracket import structure_outcome
        lv_d, datr, tmap = daily_structure(df, structure_pivot)
        a_d = np.where(tmap[cand] >= 0, datr[np.clip(tmap[cand], 0, None)], np.nan)
        out["atr"] = a_d
    for name, side in (("long", 1), ("short", -1)):
        if structure_pivot:
            px, j, reason, risk_s, _fb = structure_outcome(lv_d, o[win], h[win], lo[win], c[win], cand, entry, a_d, side,
                                                           sl_atr=2.0, tp_atr=3.0, t_map=tmap)
            risk = risk_s
        else:
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


def take(rows: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, tau: float, long_only: bool,
         side_rule: str = "served") -> pd.DataFrame:
    """The served decide() + one position per symbol. long_only: a SHORT decision is not taken (no position opens).
    ``side_rule="restricted"`` with ``long_only``: the argmax runs over LONG only (the live ``side_filter: long``
    profile, ``ml_entry.decide(sides=("long",))``), so a long whose p_long clears tau is taken even when p_short is larger."""
    t = rows.assign(p_long=pl, p_short=ps).sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        busy = -1
        for r in g.itertuples(index=False):
            if r.i <= busy:
                continue
            side = "long" if (r.p_long >= r.p_short or (long_only and side_rule == "restricted")) else "short"
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


def verdict(m: dict, label: str = "alpaca_live") -> tuple[str, str]:
    if m["n"] < N_FLOOR:
        return "indeterminate", f"{label} long-only held-out n={m['n']} < {N_FLOOR}"
    if m["mean_net_r"] >= 0:
        return "pass", f"{label} long-only held-out mean net R per decision {m['mean_net_r']:+.4f} >= 0 at n={m['n']}"
    return "fail", f"{label} long-only held-out mean net R per decision {m['mean_net_r']:+.4f} < 0 at n={m['n']}"


def session_ok(close_ts: pd.Series, hold_h: int = H) -> np.ndarray:
    """The live ``session: us_equity`` gate: open at the decision close AND at close + ``hold_h`` hours."""
    from src.runtime.market_hours import is_market_open
    t = pd.to_datetime(close_ts, utc=True)
    return np.array([is_market_open("us_equity", x.to_pydatetime())
                     and is_market_open("us_equity", (x + pd.Timedelta(hours=hold_h)).to_pydatetime()) for x in t], bool)


def run(a) -> int:
    global HOLDOUT_START, HOLDOUT_END, FETCH_START
    HOLDOUT_START, HOLDOUT_END, FETCH_START = a.holdout_start, a.holdout_end, a.fetch_start
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
            frames.append(equity_rows(s, df, R, V, slip, fee, structure_pivot=a.structure_pivot))
        except Exception as e:  # noqa: BLE001  # allow-silent: recorded per symbol, never dropped
            fetch_rep[s] = {"rows": 0, "error": str(e)[:200]}
    tab = pd.concat(frames, ignore_index=True)
    tab["ts"] = pd.to_datetime(tab.ts, utc=True)
    hs, he = pd.Timestamp(HOLDOUT_START, tz="UTC"), pd.Timestamp(HOLDOUT_END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].replace([np.inf, -np.inf], np.nan).dropna(subset=feats + ["net_long"])
    n_before_gate = int(len(test))
    if a.session_gate:
        test = test[session_ok(test.ts)]
    # provenance: predict -- Booster.predict is the regressed net R of that side (the served model), not a probability
    pl = model["long"].predict(test[feats])
    ps = model["short"].predict(test[feats])
    tk_live = take(test[test.symbol.isin(live)], pl[test.symbol.isin(live).to_numpy()],
                   ps[test.symbol.isin(live).to_numpy()], tau, long_only=True, side_rule=a.side_rule)
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
        "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
        "population": {"n": m["n"], "description": f"frozen ml-decision-entry-v1 (tau {tau}) LONG decisions on alpaca_live "
                       f"symbols {live}, Yahoo 1h RTH bars, held-out {HOLDOUT_START}..{HOLDOUT_END}, net of fee {fee} + "
                       f"slippage {slip} + regulatory {REGULATORY_BPS} bps round trip, funding {fund}"},
        "variants_read_on_this_heldout": a.variants_read,
        "multiple_comparison_note": (a.mc_note or None),
        "bracket": ("structure: daily pivot=%d (SL beyond last confirmed daily swing - 0.25 dATR, clamp [0.5,3]x2 dATR, ratchet; "
                    "TP nearest opposing daily swing/unfilled FVG >=1R, extend-only); levels read as of the PREVIOUS completed session"
                    % a.structure_pivot) if a.structure_pivot else "fixed ATR 2/3 (hourly ATR14)",
        "measurement": {"schema": SCHEMA, "model_sha256": sha, "model_meta": {k: v for k, v in meta.items() if k != "xs_reference"},
                        "tau": tau, "alpaca_live_long_only": m,
                        "reported_alpaca_live_both_sides": live_both,
                        "reported_mirror_symbols_both_sides": mirror_both,
                        "reported_always_long_same_mechanics": {"n": len(alw), "mean_net_r": float(np.mean(alw)) if alw else None},
                        "side_rule": a.side_rule, "session_gate": bool(a.session_gate),
                        "decision_rows_before_session_gate": n_before_gate,
                        "decision_rows": int(len(test)), "decision_rows_by_symbol": test.groupby("symbol").size().to_dict(),
                        "perp_reference_loaded": len(perps), "median_n_reference": float(test.n_reference.median()),
                        "fetch": fetch_rep, "costs": {"fee_bps": fee, "slippage_bps": slip, "regulatory_bps": REGULATORY_BPS,
                                                      "funding_bps": fund}},
        "produced_by": {"tool": "python3 scripts/research/ml_entry_alpaca_score.py", "where": a.where,
                        "runtime_s": round(time.time() - t0, 1)},
    }
    p = out / f"{a.unit}.json"
    p.write_text(json.dumps(row, indent=1, default=str))
    # The runner pipeline grades from <out>/verdict.json; without it a measured FAIL lands as producer_failed
    # (RQ-20261102-5e03-01, run 41600034132: VERDICT fail printed, nothing graded). Same fix as ml_entry_tp_revision.py.
    (out / "verdict.json").write_text(json.dumps({**row, "n": m["n"]}, indent=1, default=str) + "\n")
    print(f"VERDICT {v}: {why}\nwrote {p}", flush=True)
    return 0


# ---------------------------------------------------------------------------------------------------------------------------
# RQ-20261104-a41f-01: the POOLED Alpaca ETF population on Alpaca 1h RTH bars (--bars alpaca --population alpaca-liquidity).
# Registered BEFORE any run; the ETF rule and the pool rule are FROZEN in POOL_RULE and hashed (POOL_RULE_SHA256, recorded in the unit).
# ---------------------------------------------------------------------------------------------------------------------------
NASDAQTRADED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
POOL_RULE = {
    "asset": "Alpaca /v2/assets with status=active, tradable=true, class=us_equity (read at run time, sha256 of the sorted symbol list recorded)",
    "etf": ("Alpaca assets carry NO ETF flag. A symbol is an ETF iff nasdaqtrader nasdaqtraded.txt (read at run time, sha256 of the file "
            "recorded) has Test Issue == 'N' and ETF == 'Y' for that exact symbol; a symbol absent from that file is NOT an ETF. "
            "No name matching, no manual list."),
    "liquidity": "median over daily bars 2019-01-01..2020-12-31 of close*volume (Alpaca 1Day, adjustment=split, feed=sip) >= 50000000 USD",
    "no_dev_bars": "an asset with no daily bar in the dev window is excluded (counted and listed)",
    "dev_window": ["2019-01-01", "2020-12-31"], "min_median_dollar_volume": 50_000_000.0,
    "bars_1h": "Alpaca 1Hour, adjustment=split, feed=sip, from 2021-01-01; RTH = bar open 09:00..15:00 America/New_York (hour-aligned; the 09:00 bar holds 09:30-10:00 trades)",
}
POOL_RULE_SHA256 = hashlib.sha256(json.dumps(POOL_RULE, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
POOL_START = "2021-01-01"
DEV_START, DEV_END = "2019-01-01", "2020-12-31"
MIN_MEDIAN_DV = POOL_RULE["min_median_dollar_volume"]


def etf_symbols(text: str) -> set[str]:
    """The frozen ETF rule: nasdaqtraded.txt rows with Test Issue == N and ETF == Y."""
    rows = [ln.split("|") for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df[(df["Test Issue"] == "N") & (df["ETF"] == "Y")]
    return set(df["Symbol"].astype(str))


def filter_pool(assets: list[dict], etfs: set[str], dev_daily: dict[str, pd.DataFrame]) -> tuple[list[str], dict]:
    """Apply POOL_RULE. ``assets``: Alpaca asset dicts; ``dev_daily``: symbol -> daily frame (close, volume) over the dev window."""
    act = sorted({a["symbol"] for a in assets if a.get("status") == "active" and a.get("tradable")
                  and a.get("class", "us_equity") == "us_equity"})
    cand = [s for s in act if s in etfs]
    pool, excl = [], {}
    for s in cand:
        d = dev_daily.get(s)
        if d is None or len(d) == 0:
            excl[s] = {"reason": "no_dev_bars", "median_dollar_volume": None, "n_bars": 0}
            continue
        med = float((d["close"].astype(float) * d["volume"].astype(float)).median())
        if med >= MIN_MEDIAN_DV:
            pool.append(s)
        else:
            excl[s] = {"reason": "illiquid", "median_dollar_volume": round(med, 2), "n_bars": int(len(d))}
    rep = {"n_assets_active_tradable": len(act), "n_etf_candidates": len(cand), "n_pool": len(pool),
           "n_excluded_no_dev_bars": sum(1 for e in excl.values() if e["reason"] == "no_dev_bars"),
           "n_excluded_illiquid": sum(1 for e in excl.values() if e["reason"] == "illiquid"),
           "assets_sha256": hashlib.sha256("\n".join(act).encode()).hexdigest(), "excluded": excl}
    return sorted(pool), rep


def alpaca_bars_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).rename(columns={"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"]) \
        .drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def rth_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Alpaca 1Hour bars are hour-aligned (open 09:00 ET holds 09:30-10:00). RTH = open in [09:00, 16:00) ET; close_ts = open + 1h
    capped at the 16:00 ET close. Pre/post-market bars are dropped."""
    et = df.ts.dt.tz_convert("America/New_York")
    m = et.dt.hour * 60 + et.dt.minute
    keep = ((m >= 540) & (m < 960)).to_numpy()
    df, et = df[keep].reset_index(drop=True), et[keep].reset_index(drop=True)
    df = df[(df.open > 0) & (df.close > 0)].reset_index(drop=True)
    et = df.ts.dt.tz_convert("America/New_York")
    session_close = (et.dt.normalize() + pd.Timedelta(hours=16)).dt.tz_convert("UTC")
    df["close_ts"] = pd.concat([df.ts + pd.Timedelta(hours=1), session_close], axis=1).min(axis=1)
    df["volume"] = df["volume"].fillna(0).astype(float)
    return df


def fetch_alpaca_1h(client, syms: list[str], cache: Path, end: str) -> dict[str, pd.DataFrame]:
    out, need = {}, []
    for s in syms:
        p = cache / f"alp1h_{s}_{POOL_START}_{end}.pkl"
        if p.exists():
            out[s] = pd.read_pickle(p)
        else:
            need.append(s)
    cache.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(need), 20):
        b = need[i:i + 20]
        got = client.bars(b, "1Hour", f"{POOL_START}T00:00:00Z", f"{end}T00:00:00Z")
        for s in b:
            if got.get(s):
                out[s] = rth_hourly(alpaca_bars_df(got[s]))
                out[s].to_pickle(cache / f"alp1h_{s}_{POOL_START}_{end}.pkl")
        print(f"[alpaca] 1h {min(i + 20, len(need))}/{len(need)} symbols, calls={client.calls} 429s={client.n_429}", flush=True)
    return out


def pool_population_record(unit: str, rule_id: str, verdict_: str, result: str, pool: list[str]) -> dict:
    return {"unit": unit, "rule_id": rule_id, "verdict": verdict_, "result": result,
            "symbols": {s: {"venues": ["alpaca"]} for s in pool}}


def run_pool(a) -> int:
    global HOLDOUT_START, HOLDOUT_END, FETCH_START
    import requests
    from alpaca_readonly import AlpacaReadOnly
    from src.config import ml_universe
    from src.runtime.execution_costs import resolve_cost_policy, resolve_fee_bps_roundtrip
    t0 = time.time()
    if a.bars != "alpaca":
        raise SystemExit("--population alpaca-liquidity requires --bars alpaca")
    end_day = a.holdout_end or (pd.Timestamp.now(tz="UTC").normalize().replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    HOLDOUT_START, HOLDOUT_END, FETCH_START = a.holdout_start if a.holdout_start != "2025-10-01" else POOL_START, end_day, POOL_START
    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    mpath = Path(a.model)
    sha = hashlib.sha256(mpath.read_bytes()).hexdigest()
    model = load_model(mpath)
    meta = model["meta"]
    tau, feats = float(meta["tau"]), list(meta["features"])
    slip, fund = resolve_cost_policy("SPY")
    fee = resolve_fee_bps_roundtrip("SPY")
    client = AlpacaReadOnly.from_env()
    # 1. the pool (frozen rule)
    nq = requests.get(NASDAQTRADED_URL, timeout=60, headers={"User-Agent": "jta-trader-research"}).text
    etfs = etf_symbols(nq)
    assets = client.assets()
    cand = sorted({x["symbol"] for x in assets if x.get("status") == "active" and x.get("tradable")
                   and x.get("class", "us_equity") == "us_equity"} & etfs)
    dev = {}
    for i in range(0, len(cand), 100):
        got = client.bars(cand[i:i + 100], "1Day", f"{DEV_START}T00:00:00Z", "2021-01-01T00:00:00Z")
        dev.update({s: alpaca_bars_df(bl) for s, bl in got.items() if bl})
        print(f"[alpaca] dev daily {min(i + 100, len(cand))}/{len(cand)} calls={client.calls}", flush=True)
    pool, prep = filter_pool(assets, etfs, dev)
    prep.update({"etf_file_sha256": hashlib.sha256(nq.encode()).hexdigest(), "n_etf_in_file": len(etfs),
                 "pool_rule_sha256": POOL_RULE_SHA256, "key_kind": client.key_kind})
    if not pool:
        raise RuntimeError(f"empty pool: {json.dumps({k: v for k, v in prep.items() if k != 'excluded'})}")
    # 2. the positive control (SPY back to 2021-01-01) and the 1h bars
    paper13 = [s for s in _account_symbols("alpaca_paper")]
    want = sorted(set(pool) | set(paper13) | {"SPY"})
    bars = fetch_alpaca_1h(client, want, cache, (pd.Timestamp(end_day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    spy = bars.get("SPY")
    control = {"symbol": "SPY", "rows": 0 if spy is None else int(len(spy)),
               "first": None if spy is None else str(spy.ts.min()), "last": None if spy is None else str(spy.ts.max())}
    if spy is None or spy.ts.min() > pd.Timestamp("2021-01-08", tz="UTC") or len(spy) < 5000:
        (out / "verdict.json").write_text(json.dumps({"read_state": "producer_failed", "verdict": None, "n": None,
                                                      "note": "positive control failed", "control": control, "pool": prep}, default=str))
        raise RuntimeError(f"positive control failed: {control}")
    print(f"[control] {control}", flush=True)
    # 3. features/rows, window, gate, decisions
    perps = fetch_perps(cache, list(meta["xs_reference"]))
    R, V = perp_context(perps)
    frames, fetch_rep = [], {}
    for s in want:
        if s not in bars:
            fetch_rep[s] = {"rows": 0, "error": "no 1h bars"}
            continue
        fetch_rep[s] = {"rows": int(len(bars[s])), "first": str(bars[s].ts.min()), "last": str(bars[s].ts.max())}
        frames.append(equity_rows(s, bars[s], R, V, slip, fee))
    tab = pd.concat(frames, ignore_index=True)
    tab["ts"] = pd.to_datetime(tab.ts, utc=True)
    hs, he = pd.Timestamp(HOLDOUT_START, tz="UTC"), pd.Timestamp(HOLDOUT_END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[(tab.ts >= hs) & (tab.ts < he)].replace([np.inf, -np.inf], np.nan).dropna(subset=feats + ["net_long"])
    n_before_gate = int(len(test))
    if a.session_gate:
        test = test[session_ok(test.ts)]
    pl, ps = model["long"].predict(test[feats]), model["short"].predict(test[feats])  # provenance: predict -- Booster.predict is the regressed net R of that side (the served model), not a probability
    inp = test.symbol.isin(pool).to_numpy()
    tk = take(test[inp], pl[inp], ps[inp], tau, long_only=True, side_rule=a.side_rule)
    m = summ(tk)
    v, why = verdict(m, label=f"alpaca-liquidity pool of {len(pool)} ETFs")
    by_year = {str(k): {"n": int(len(g)), "mean_net_r": round(float(g.net_r.mean()), 4)}
               for k, g in tk.assign(y=pd.to_datetime(tk.ts, utc=True).dt.year).groupby("y")}
    tk_new = tk[pd.to_datetime(tk.ts, utc=True) >= pd.Timestamp("2025-10-01", tz="UTC")]
    pp = test.symbol.isin(paper13).to_numpy()
    tk_p = take(test[pp], pl[pp], ps[pp], tau, long_only=True, side_rule=a.side_rule)
    result_rel = f"comms/research/{a.unit}/<run_id>/{a.unit}.json"
    rec = pool_population_record(a.unit, a.rule_id, v, result_rel, pool)
    ml_universe.write_population("ml_entry", rec, base=out / "ml_universe", seed_from=ml_universe.RECORD_DIR)
    row = {
        "schema_version": 1, "research_unit": a.unit, "read_state": "measured", "verdict": v, "note": why,
        "generated_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
        "population": {"n": m["n"], "description": f"frozen ml-decision-entry-v1 (tau {tau}) restricted-LONG decisions, pooled over "
                       f"{len(pool)} liquid Alpaca ETFs, Alpaca 1h RTH bars {HOLDOUT_START}..{HOLDOUT_END}, net of fee {fee} + "
                       f"slippage {slip} + regulatory {REGULATORY_BPS} bps round trip, funding {fund}"},
        "variants_read_on_this_heldout": a.variants_read, "multiple_comparison_note": (a.mc_note or None),
        "bracket": "fixed ATR 2/3 (hourly ATR14)",
        "measurement": {"schema": SCHEMA, "model_sha256": sha, "tau": tau, "pooled_long_only": m,
                        "reported_by_year": by_year, "reported_2025_10_01_onward": summ(tk_new),
                        "reported_alpaca_paper_symbols_pooled": summ(tk_p), "alpaca_paper_symbols": paper13,
                        "side_rule": a.side_rule, "session_gate": bool(a.session_gate),
                        "decision_rows_before_session_gate": n_before_gate, "decision_rows": int(len(test)),
                        "pool": prep, "pool_symbols": pool, "positive_control": control, "fetch": fetch_rep,
                        "perp_reference_loaded": len(perps), "median_n_reference": float(test.n_reference.median()),
                        "alpaca_calls": client.calls, "alpaca_429s": client.n_429,
                        "costs": {"fee_bps": fee, "slippage_bps": slip, "regulatory_bps": REGULATORY_BPS, "funding_bps": fund},
                        "bar_alignment_note": "Alpaca 1Hour bars are hour-aligned (09:00 ET bar holds 09:30-10:00); decision clock UTC close hour % 4 == 0 applied to those closes"},
        "ml_universe_record": rec if v == "pass" else {**rec, "symbols": "omitted (non-pass adds nothing)"},
        "produced_by": {"tool": "python3 scripts/research/ml_entry_alpaca_score.py", "where": a.where,
                        "runtime_s": round(time.time() - t0, 1)},
    }
    p = out / f"{a.unit}.json"
    p.write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps({**row, "n": m["n"]}, indent=1, default=str) + "\n")
    print(f"VERDICT {v}: {why}\nwrote {p}", flush=True)
    return 0


def pool_self_test() -> None:
    """RQ-20261104-a41f-01 self-test: a planted illiquid ETF is excluded by the dev-window filter; a PASS record round-trips through
    src/config/ml_universe.load; the ETF rule and the Alpaca RTH alignment behave; no network."""
    import tempfile
    from src.config import ml_universe as MU
    txt = ("Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|"
           "CQS Symbol|NASDAQ Symbol|NextShares\n"
           "Y|LIQD|Liquid ETF|P| |Y|100|N| |LIQD|LIQD|N\nY|ILLQ|Illiquid ETF|P| |Y|100|N| |ILLQ|ILLQ|N\n"
           "Y|AAPL|Apple|Q|Q|N|100|N|N|AAPL|AAPL|N\nY|TSTX|Test ETF|P| |Y|100|Y| |TSTX|TSTX|N\n"
           "Y|NEWE|New ETF|P| |Y|100|N| |NEWE|NEWE|N\nY|INAC|Inactive ETF|P| |Y|100|N| |INAC|INAC|N\n"
           "File Creation Time: 1105202600:00|||||||||||\n")
    etfs = etf_symbols(txt)
    assert etfs == {"LIQD", "ILLQ", "NEWE", "INAC"}, etfs        # AAPL not an ETF; TSTX is a test issue
    ix = pd.date_range("2019-01-02", periods=100, freq="B")
    d = lambda px, vol: pd.DataFrame({"ts": ix, "close": px, "volume": vol})   # noqa: E731
    assets = [{"symbol": x, "status": "active", "tradable": True, "class": "us_equity"} for x in ("LIQD", "ILLQ", "AAPL", "NEWE")]
    assets.append({"symbol": "INAC", "status": "inactive", "tradable": False, "class": "us_equity"})
    pool, rep = filter_pool(assets, etfs, {"LIQD": d(100.0, 1_000_000.0), "ILLQ": d(100.0, 100_000.0), "AAPL": d(100.0, 9e9)})
    assert pool == ["LIQD"], pool                                  # ILLQ (10M median) planted illiquid; NEWE no dev bars; AAPL not ETF
    assert rep["excluded"]["ILLQ"]["reason"] == "illiquid" and rep["excluded"]["NEWE"]["reason"] == "no_dev_bars", rep
    assert "INAC" not in rep["excluded"] and "AAPL" not in rep["excluded"], rep
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        rec = pool_population_record("RQ-X", "RULE-X", "pass", "comms/research/RQ-X/1/RQ-X.json", pool)
        MU.write_population("ml_entry", rec, base=base)
        loaded = MU.load("ml_entry", base=base)
        assert loaded and loaded[0]["verdict"] == "pass" and MU.passed_symbols(loaded, "alpaca") == ["LIQD"], loaded
        assert MU.apply(["SPY"], loaded, "alpaca") == ["SPY", "LIQD"] and MU.apply(["SPY"], loaded, "bybit") == ["SPY"]
        MU.write_population("ml_entry", {**rec, "verdict": "fail"}, base=base)          # same unit replaces, never duplicates
        assert len(MU.load("ml_entry", base=base)) == 1 and MU.passed_symbols(MU.load("ml_entry", base=base)) == []
    ts = pd.to_datetime(["2025-11-03 13:00", "2025-11-03 14:00", "2025-11-03 20:00", "2025-11-03 21:00"], utc=True)   # EST: 08,09,15,16 ET
    raw = pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    r = rth_hourly(raw)
    assert r.ts.dt.hour.tolist() == [14, 20], r                      # 08:00 ET (pre) and 16:00 ET (post) dropped
    assert r.close_ts.dt.hour.tolist() == [15, 21], r               # 15:00 UTC = 10:00 ET; 21:00 UTC = the 16:00 ET close


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
    tk3 = take(rows, np.array([0.2, 0.2, 0.15]), np.array([0.0, 0.0, 0.5]), 0.1, long_only=True, side_rule="restricted")
    assert tk3.side.tolist() == ["long", "long"] and tk3.net_r.tolist() == [1.0, 0.5], tk3   # row 3: long clears tau
    g = session_ok(pd.Series(pd.to_datetime(["2026-07-14 16:00", "2026-07-14 20:00", "2026-07-17 16:00"], utc=True)))
    assert g.tolist() == [True, False, False], g   # Tue mid-session ok; the session close; Fri (+24h = Sat)
    assert verdict({"n": 29, "mean_net_r": 1.0})[0] == "indeterminate"
    assert verdict({"n": 30, "mean_net_r": 0.0})[0] == "pass"
    assert verdict({"n": 30, "mean_net_r": -0.01})[0] == "fail"
    pool_self_test()
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
    r.add_argument("--structure-pivot", type=int, default=0,
                   help="0 = the fixed ATR bracket (bdc2-01, byte-identical); N>=1 = DAILY session-aware structure SL/TP (STRUCTURE-EXITS-DEFAULT).")
    r.add_argument("--rule-id", default="RULE-RQ20261101-bdc2-01-ENTRY-ON-ALPACA")
    r.add_argument("--registered-at", default="2026-11-01")
    r.add_argument("--variants-read", type=int, default=1)
    r.add_argument("--mc-note", default="")
    r.add_argument("--side-rule", choices=("served", "restricted"), default="served",
                   help="served (bdc2-01): SHORT -> nothing; restricted: argmax over LONG only (live side_filter: long profile)")
    r.add_argument("--session-gate", action="store_true",
                   help="decide only when us_equity is open at the close and at close + 24h (live session: us_equity)")
    r.add_argument("--bars", choices=("yahoo", "alpaca"), default="yahoo",
                   help="yahoo (bdc2-01, default); alpaca: read-only Alpaca data API (scripts/research/alpaca_readonly.py allowlist)")
    r.add_argument("--population", choices=("account", "alpaca-liquidity"), default="account",
                   help="account (default): alpaca_live + alpaca_portfolio symbols; alpaca-liquidity: the pre-registered pooled ETF pool (POOL_RULE)")
    r.add_argument("--holdout-start", default=HOLDOUT_START)
    r.add_argument("--holdout-end", default=HOLDOUT_END)
    r.add_argument("--fetch-start", default=FETCH_START)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run":
        return 2
    if a.population == "alpaca-liquidity":
        if a.holdout_end == HOLDOUT_END:
            a.holdout_end = None        # default: the last complete month before the run
        return run_pool(a)
    if a.bars != "yahoo":
        raise SystemExit("--bars alpaca is only wired for --population alpaca-liquidity")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
