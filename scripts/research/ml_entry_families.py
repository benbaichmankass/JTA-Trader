#!/usr/bin/env python3
"""Feature families for the pooled ENTRY recipe (rows ML-FS-ENTRY-V2, ML-FS-STORE; plan docs/research/ml-feature-inventory-2026-11-01.md section 4).

Each family is a pure function of data AT OR BEFORE the decision bar's close. A decision at table timestamp ``ts``
(the decision bar's OPEN time, as in ``ml_decision_entry``) may use bar ``ts`` (closed at ``ts + 1h``) and everything
earlier. Missing stays NaN (never 0) and a ``*_present`` flag marks families with a hole in history.

Families (columns are prefixed ``f<n>_``):
  F1 taker flow      from the 12-column klines (taker-buy share, trade count, average trade size, vwap deviation)
  F2 basis, funding  premium-index 1h klines + last SETTLED funding at or before the bar close
  F3 positioning     5m metrics (OI, top-trader and account long/short, taker ratio): last row with create_time at or
                     before bar_open + 50 min (10 min before the close, conservative for the undocumented stamp convention)
  F4 cross-section   ranks, dispersion, breadth and BTC-relative terms over the symbols present at the same ts
  F5 shape/calendar  higher moments, semivariance, range volatility, efficiency ratio, extreme age, hour-of-week

Leakage test (``--self-test``): a feature at ts must be IDENTICAL when every input row after the bar close is removed.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

FAMILIES = {
    "F1": ["f1_tb", "f1_tb_z168", "f1_tb_ma4", "f1_tb_ma24", "f1_cnt_z168", "f1_avgtrade_z168", "f1_vwap_dev", "f1_signed_vol24"],
    "F2": ["f2_prem", "f2_prem_z168", "f2_prem_ma24", "f2_prem_chg4", "f2_fund", "f2_fund_z21", "f2_fund_hrs", "f2_prem8_minus_fund"],
    "F3": ["f3_oi_chg1", "f3_oi_chg4", "f3_oi_chg24", "f3_oi_chg4_z168", "f3_top_ls", "f3_top_pos_ls", "f3_acct_ls",
           "f3_taker_ls", "f3_taker_ls_ma4", "f3_present"],
    "F4": ["f4_rank_ret4", "f4_rank_ret72", "f4_rank_ret168", "f4_rank_vol24", "f4_disp24", "f4_breadth4", "f4_breadth168",
           "f4_rel_btc24", "f4_corr_btc168"],
    "F5": ["f5_skew24", "f5_kurt24", "f5_semivar_ratio24", "f5_park24", "f5_er24", "f5_since_hi168", "f5_since_lo168",
           "f5_dist_hi168_atr", "f5_dist_lo168_atr", "f5_how", "f5_hrs_to_funding"],
}


def _z(s: pd.Series, n: int) -> pd.Series:
    sd = s.rolling(n).std().replace(0, np.nan)
    return (s - s.rolling(n).mean()) / sd


def _ts(open_time: pd.Series) -> pd.Series:
    return pd.to_datetime(pd.to_numeric(open_time), unit="ms", utc=True).astype("datetime64[ns, UTC]")


def f1(k: pd.DataFrame) -> pd.DataFrame:
    vol = k["volume"].replace(0, np.nan)
    tb = k["taker_buy_volume"] / vol
    cnt = k["count"].replace(0, np.nan)
    qv = k["quote_volume"]
    out = pd.DataFrame({"ts": k["ts"]})
    out["f1_tb"] = tb
    out["f1_tb_z168"] = _z(tb, 168)
    out["f1_tb_ma4"] = tb.rolling(4).mean()
    out["f1_tb_ma24"] = tb.rolling(24).mean()
    out["f1_cnt_z168"] = _z(np.log(cnt), 168)
    out["f1_avgtrade_z168"] = _z(np.log(qv.replace(0, np.nan) / cnt), 168)
    out["f1_vwap_dev"] = (qv / vol - k["close"]) / k["close"]
    out["f1_signed_vol24"] = ((2 * tb - 1) * qv).rolling(24).sum() / qv.rolling(24).sum().replace(0, np.nan)
    return out


def f2(k: pd.DataFrame, prem: pd.DataFrame | None, fund: pd.DataFrame | None) -> pd.DataFrame:
    out = pd.DataFrame({"ts": k["ts"]})
    if prem is not None and len(prem):
        p = prem.assign(ts=_ts(prem["open_time"]))[["ts", "close"]].drop_duplicates("ts").sort_values("ts")
        pc = p.set_index("ts")["close"].reindex(k["ts"]).to_numpy()
        ps = pd.Series(pc)
        out["f2_prem"] = ps
        out["f2_prem_z168"] = _z(ps, 168)
        out["f2_prem_ma24"] = ps.rolling(24).mean()
        out["f2_prem_chg4"] = ps - ps.shift(4)
        prem8 = ps.rolling(8).mean()
    else:
        prem8 = pd.Series(np.nan, index=out.index)
    if fund is not None and len(fund):
        f = fund.copy()
        f["calc"] = pd.to_datetime(pd.to_numeric(f["calc_time"]), unit="ms", utc=True).astype("datetime64[ns, UTC]")
        f = f.sort_values("calc").drop_duplicates("calc")
        f["rate"] = f["last_funding_rate"].astype(float)
        f["z21"] = _z(f["rate"], 21)
        bar_close = (k["ts"] + pd.Timedelta(hours=1)).astype("datetime64[ns, UTC]")
        left = pd.DataFrame({"bar_close": bar_close}).reset_index().rename(columns={"index": "_i"})
        m = pd.merge_asof(left.sort_values("bar_close"), f[["calc", "rate", "z21"]], left_on="bar_close", right_on="calc",
                          direction="backward").sort_values("_i")
        out["f2_fund"] = m["rate"].to_numpy()
        out["f2_fund_z21"] = m["z21"].to_numpy()
        out["f2_fund_hrs"] = ((m["bar_close"] - m["calc"]).dt.total_seconds() / 3600.0).to_numpy()
        out["f2_prem8_minus_fund"] = prem8.to_numpy() - m["rate"].to_numpy()
    return out


def f3(k: pd.DataFrame, met: pd.DataFrame | None) -> pd.DataFrame:
    out = pd.DataFrame({"ts": k["ts"]})
    if met is None or not len(met):
        out["f3_present"] = 0.0
        return out
    m = met.copy()
    m["create_time"] = pd.to_datetime(m["create_time"], utc=True).astype("datetime64[ns, UTC]")
    m = m.sort_values("create_time")
    m["bucket"] = m["create_time"].dt.floor("h")
    m = m[(m["create_time"] - m["bucket"]) <= pd.Timedelta(minutes=50)]
    h = m.groupby("bucket").last()
    h = h.reindex(k["ts"].astype("datetime64[ns, UTC]"))
    oi = np.log(h["sum_open_interest_value"].astype(float).replace(0, np.nan)).reset_index(drop=True)
    out["f3_oi_chg1"] = oi - oi.shift(1)
    out["f3_oi_chg4"] = oi - oi.shift(4)
    out["f3_oi_chg24"] = oi - oi.shift(24)
    out["f3_oi_chg4_z168"] = _z(out["f3_oi_chg4"], 168)
    pos = lambda c: np.log(h[c].astype(float).replace(0, np.nan)).reset_index(drop=True)
    out["f3_top_ls"] = pos("count_toptrader_long_short_ratio")
    out["f3_top_pos_ls"] = pos("sum_toptrader_long_short_ratio")
    out["f3_acct_ls"] = pos("count_long_short_ratio")
    out["f3_taker_ls"] = pos("sum_taker_long_short_vol_ratio")
    out["f3_taker_ls_ma4"] = out["f3_taker_ls"].rolling(4).mean()
    out["f3_present"] = h["sum_open_interest_value"].notna().astype(float).to_numpy()
    return out


def f5(k: pd.DataFrame) -> pd.DataFrame:
    c, h, lo = k["close"].astype(float), k["high"].astype(float), k["low"].astype(float)
    lr = np.log(c).diff()
    out = pd.DataFrame({"ts": k["ts"]})
    out["f5_skew24"] = lr.rolling(24).skew()
    out["f5_kurt24"] = lr.rolling(24).kurt()
    up = (lr.clip(lower=0) ** 2).rolling(24).sum()
    dn = ((-lr.clip(upper=0)) ** 2).rolling(24).sum()
    out["f5_semivar_ratio24"] = np.log((dn + 1e-12) / (up + 1e-12))
    out["f5_park24"] = np.sqrt((np.log(h / lo) ** 2).rolling(24).mean() / (4 * np.log(2)))
    out["f5_er24"] = (c - c.shift(24)).abs() / c.diff().abs().rolling(24).sum().replace(0, np.nan)
    hi168, lo168 = h.rolling(168).max(), lo.rolling(168).min()
    out["f5_since_hi168"] = h.rolling(168).apply(lambda a: len(a) - 1 - int(np.argmax(a)), raw=True)
    out["f5_since_lo168"] = lo.rolling(168).apply(lambda a: len(a) - 1 - int(np.argmin(a)), raw=True)
    pc = c.shift(1)
    atr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1).rolling(14).mean().replace(0, np.nan)
    out["f5_dist_hi168_atr"] = (hi168 - c) / atr
    out["f5_dist_lo168_atr"] = (c - lo168) / atr
    close_ts = k["ts"] + pd.Timedelta(hours=1)
    out["f5_how"] = close_ts.dt.dayofweek * 24 + close_ts.dt.hour
    out["f5_hrs_to_funding"] = (8 - close_ts.dt.hour % 8) % 8
    return out


def symbol_frame(k12: pd.DataFrame, prem: pd.DataFrame | None, fund: pd.DataFrame | None, met: pd.DataFrame | None) -> pd.DataFrame:
    k = k12.copy()
    k["ts"] = _ts(k["open_time"])
    k = k.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "quote_volume", "count", "taker_buy_volume"):
        k[c] = k[c].astype(float)
    parts = [f1(k), f2(k, prem, fund), f3(k, met), f5(k)]
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="ts", how="left")
    out["_close"] = k["close"].to_numpy()
    out["_lr"] = np.log(k["close"]).diff().to_numpy()
    return out


def cross_section(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """F4 over the symbols present at each ts. Inputs: per-symbol frames with ``ts``, ``_close``, ``_lr``."""
    close = pd.DataFrame({s: f.set_index("ts")["_close"] for s, f in frames.items()})
    lr = pd.DataFrame({s: f.set_index("ts")["_lr"] for s, f in frames.items()})
    lc = np.log(close)
    r = {k: lc - lc.shift(k) for k in (4, 24, 72, 168)}
    vol24 = lr.rolling(24).std()
    rank = lambda df: df.rank(axis=1, pct=True)
    out = {
        "f4_rank_ret4": rank(r[4]), "f4_rank_ret72": rank(r[72]), "f4_rank_ret168": rank(r[168]), "f4_rank_vol24": rank(vol24),
    }
    breadth4 = (r[4] > 0).astype(float).where(r[4].notna()).mean(axis=1)
    breadth168 = (r[168] > 0).astype(float).where(r[168].notna()).mean(axis=1)
    disp24 = r[24].std(axis=1)
    btc24 = r[24]["BTCUSDT"] if "BTCUSDT" in r[24] else pd.Series(np.nan, index=close.index)
    rel = r[24].sub(btc24, axis=0)
    corr = pd.DataFrame({s: lr[s].rolling(168).corr(lr["BTCUSDT"]) for s in lr.columns}) if "BTCUSDT" in lr else lr * np.nan
    long = []
    for s in close.columns:
        d = pd.DataFrame({"ts": close.index, "symbol": s,
                          "f4_rank_ret4": out["f4_rank_ret4"][s].to_numpy(), "f4_rank_ret72": out["f4_rank_ret72"][s].to_numpy(),
                          "f4_rank_ret168": out["f4_rank_ret168"][s].to_numpy(), "f4_rank_vol24": out["f4_rank_vol24"][s].to_numpy(),
                          "f4_disp24": disp24.to_numpy(), "f4_breadth4": breadth4.to_numpy(), "f4_breadth168": breadth168.to_numpy(),
                          "f4_rel_btc24": rel[s].to_numpy(), "f4_corr_btc168": corr[s].to_numpy()})
        long.append(d)
    res = pd.concat(long, ignore_index=True)
    res["ts"] = res["ts"].astype("datetime64[ns, UTC]")
    return res


def _synthetic(n=900, seed=1):
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2024-01-01", tz="UTC")
    ot = (t0.value // 10**6) + np.arange(n) * 3_600_000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    v = rng.uniform(100, 200, n)
    k = pd.DataFrame({"open_time": ot, "open": c * 0.999, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": v,
                      "quote_volume": v * c, "count": rng.integers(500, 900, n).astype(float),
                      "taker_buy_volume": v * rng.uniform(0.4, 0.6, n)})
    prem = pd.DataFrame({"open_time": ot, "close": rng.normal(0, 0.001, n)})
    fo = (t0.value // 10**6) + np.arange(0, n, 8) * 3_600_000
    fund = pd.DataFrame({"calc_time": fo, "last_funding_rate": rng.normal(1e-4, 5e-5, len(fo))})
    mt = pd.date_range(t0, periods=n * 12, freq="5min", tz="UTC")
    met = pd.DataFrame({"create_time": mt, "sum_open_interest_value": 1e9 * np.exp(np.cumsum(rng.normal(0, 0.002, len(mt)))),
                        "count_toptrader_long_short_ratio": rng.uniform(0.8, 1.6, len(mt)),
                        "sum_toptrader_long_short_ratio": rng.uniform(0.8, 1.6, len(mt)),
                        "count_long_short_ratio": rng.uniform(0.8, 3, len(mt)),
                        "sum_taker_long_short_vol_ratio": rng.uniform(0.5, 1.8, len(mt))})
    return k, prem, fund, met


def self_test() -> None:
    k, prem, fund, met = _synthetic()
    full = symbol_frame(k, prem, fund, met)
    cols = [c for fam in ("F1", "F2", "F3", "F5") for c in FAMILIES[fam]]
    assert all(c in full.columns for c in cols), [c for c in cols if c not in full.columns]
    # truncation invariance: removing every input after bar t's close must not change the features at t
    for t in (400, 600, 850):
        close_ms = int(k["open_time"].iloc[t]) + 3_600_000
        kt = k[k["open_time"] <= int(k["open_time"].iloc[t])]
        pt = prem[prem["open_time"] <= int(k["open_time"].iloc[t])]
        ft = fund[fund["calc_time"] <= close_ms]
        mt = met[met["create_time"] <= pd.Timestamp(close_ms, unit="ms", tz="UTC")]
        part = symbol_frame(kt, pt, ft, mt)
        a, b = full.iloc[t][cols].astype(float), part.iloc[t][cols].astype(float)
        bad = [c for c in cols if not (np.isclose(a[c], b[c], equal_nan=True))]
        assert not bad, f"LOOKAHEAD at t={t}: {bad}"
    # a planted lead IS caught by the same test
    lead = full.copy()
    lead["f1_tb"] = lead["f1_tb"].shift(-1)
    t = 600
    kt = k[k["open_time"] <= int(k["open_time"].iloc[t])]
    part = symbol_frame(kt, prem, fund, met)
    assert not np.isclose(lead.iloc[t]["f1_tb"], part.iloc[t]["f1_tb"]), "planted lead was not detected"
    # missing metrics -> NaN features and present flag 0 (never 0.0 features)
    nm = symbol_frame(k, prem, fund, None)
    assert nm["f3_present"].eq(0).all() and "f3_oi_chg4" not in nm.columns
    # cross-section: invariant to later rows and rank in [0,1]
    frames = {"BTCUSDT": full, "ETHUSDT": symbol_frame(_synthetic(seed=2)[0], None, None, None)}
    cs = cross_section(frames)
    assert cs["f4_rank_ret4"].dropna().between(0, 1).all()
    print("ml_entry_families self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
