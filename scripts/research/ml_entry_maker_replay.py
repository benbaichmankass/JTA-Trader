#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-1c4e-01.yaml (ENTRY execution lever: maker entry on ml_entry's own decisions, lane ML-DECISION-MODELS)
"""Does a post-only MAKER entry (DESK-MAKER-FILLS policy F: join the near touch, 5-min fallback to the market) improve the FROZEN
ENTRY v1 model's own decisions, net of fees and adverse selection, in R per decision? (Tier-1 research; no order, no config.)

Why: on v1's held-out decisions cost takes ~90% of gross (+0.073 gross vs +0.007 net R, RQ-20261112-a7e8-03). RQ-20261027-a3f1-01
measured +2.03 bps per entry for a maker entry on RANDOM-direction on-the-hour decisions (Bybit trade prints). A directional model's
picks may run away from a resting limit more often (worse selection), so the effect on ml_entry's own decisions is unmeasured.

DATA: Binance Vision daily 1m futures klines (Bybit trade prints are 135 MB per BTC day; a year is infeasible here). Approximation,
CALIBRATED before it is trusted (`calibrate`): the touch at T is the close of the minute ending at T with a one-tick spread
(bid = p - tick/2, ask = p + tick/2); maker long L = bid (k = 0); STRICT fill iff some 1m low in (T, T+5m] <= L - tick (short:
high >= L + tick); unfilled -> market at the T+5m ask/bid (close of the minute ending at T+5m +- tick/2). delta_F bps =
dir x (taker_px - eff_px) / mid x 1e4 + (5.5 - 2.0 if filled). The same formula as desk_maker_fills.decision_rows.
In R: delta_R = delta_F / 1e4 x entry / risk, risk = 2 x ATR14 (the leg's stop distance; the RiskManager sizes to it).

    python3 scripts/research/ml_entry_maker_replay.py calibrate --out O        # a3f1-01's 40 days x 6 perps, random direction
    python3 scripts/research/ml_entry_maker_replay.py run --unit RQ-20261112-1c4e-01 --out O [--cache C]
    python3 scripts/research/ml_entry_maker_replay.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import desk_maker_fills as DMF  # noqa: E402
import ml_decision_entry as E  # noqa: E402

UNIT = "RQ-20261112-1c4e-01"
RULE_ID = "RULE-RQ20261112-1c4e-01-MAKER-ENTRY"
W_MIN, K = DMF.PRIMARY_W, DMF.PRIMARY_K
TAKER, MAKER = DMF.TAKER_FEE_BPS, DMF.MAKER_FEE_BPS
A3F1_MEAN_BPS = 2.03
CAL_BAND = (1.0, 3.0)          # the 1m approximation must land within 1 bps of a3f1-01's print-based +2.03
N_FLOOR, SYM_FLOOR = 1000, 10
MODEL_ID = "EXEC-maker-entry-ml_entry_v1"
DAILY = "https://data.binance.vision/data/futures/um/daily/klines"


# ------------------------------------------------------------------------------------------------ data
def fetch_1m(sym: str, day: date, cache: Path) -> pd.DataFrame | None:
    p = cache / f"{sym}_{day.isoformat()}.pkl"
    if p.exists():
        return pd.read_pickle(p)
    import requests
    url = f"{DAILY}/{sym}/1m/{sym}-1m-{day.isoformat()}.zip"
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            raw = zf.read(zf.namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            d = pd.read_csv(io.StringIO(raw), header=0 if first.startswith("open_time") else None).iloc[:, :5]
            d.columns = ["open_time", "open", "high", "low", "close"]
            d = d.apply(pd.to_numeric, errors="coerce").dropna()
            d["t"] = (d["open_time"] // 1000).astype("int64")
            d = d[["t", "open", "high", "low", "close"]].sort_values("t").reset_index(drop=True)
            d.to_pickle(p)
            return d
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def tick_of(d: pd.DataFrame) -> float:
    return DMF.infer_tick(np.concatenate([d[c].to_numpy() for c in ("open", "high", "low", "close")]))


# ------------------------------------------------------------------------------------------------ the policy-F delta on 1m bars
def delta_f(d: pd.DataFrame, T: int, direction: int, tick: float) -> dict | None:
    """delta_F (bps) for a decision at epoch second T (on a minute boundary) on one symbol-day of 1m bars."""
    t = d["t"].to_numpy()
    i0 = int(np.searchsorted(t, T - 60))          # the minute ending at T starts at T - 60
    if i0 >= len(t) or t[i0] != T - 60:
        return None
    iW = int(np.searchsorted(t, T + 60 * (W_MIN - 1)))
    if iW >= len(t) or t[iW] != T + 60 * (W_MIN - 1):
        return None
    p = float(d["close"].iat[i0])
    bid, ask, mid = p - tick / 2.0, p + tick / 2.0, p
    pw = float(d["close"].iat[iW])
    seg = slice(i0 + 1, iW + 1)                   # minutes starting T .. T+(W-1)m == (T, T+W]
    eps = tick * 1e-6
    long = direction == 1
    if long:
        L, taker_px, fb_px = bid - K * tick, ask, pw + tick / 2.0
        filled = bool((d["low"].to_numpy()[seg] <= L - tick + eps).any())
    else:
        L, taker_px, fb_px = ask + K * tick, bid, pw - tick / 2.0
        filled = bool((d["high"].to_numpy()[seg] >= L + tick - eps).any())
    eff = L if filled else fb_px
    delta = direction * (taker_px - eff) / mid * 1e4 + ((TAKER - MAKER) if filled else 0.0)
    return {"delta_bps": float(delta), "filled": filled, "mid": mid, "tick_bps": tick / mid * 1e4}


# ------------------------------------------------------------------------------------------------ calibrate (a3f1-01's sample)
def calibrate(a) -> dict:
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    jobs = [(s, d) for d in DMF.sample_days() for s in DMF.SYMBOLS]
    with cf.ThreadPoolExecutor(24) as ex:
        frames = dict(zip(jobs, ex.map(lambda j: fetch_1m(j[0], j[1], cache), jobs)))
    vals, days, fills = [], [], []
    for (s, dday), d in frames.items():
        if d is None or len(d) < 100:
            continue
        tick = tick_of(d)
        day0 = int(datetime(dday.year, dday.month, dday.day, tzinfo=timezone.utc).timestamp())
        for h in DMF.HOURS:
            for direction in (1, -1):
                r = delta_f(d, day0 + 3600 * h, direction, tick)
                if r:
                    vals.append(r["delta_bps"])
                    days.append(dday.isoformat())
                    fills.append(r["filled"])
    v, dd = np.array(vals), np.array(days)
    mean, lo, hi = DMF.day_block_ci(v, dd)
    return {"n": len(v), "days": len(set(days)), "mean_delta_F_bps": mean, "ci95": [lo, hi], "fill_rate": float(np.mean(fills)) if fills else None,
            "a3f1_print_based_mean_bps": A3F1_MEAN_BPS, "band": list(CAL_BAND),
            "calibrated": bool(mean is not None and CAL_BAND[0] <= mean <= CAL_BAND[1])}


# ------------------------------------------------------------------------------------------------ run (v1's held-out decisions)
def v1_decisions(cache: Path) -> pd.DataFrame:
    import lightgbm as lgb
    syms = E.universe()
    E.fetch(cache, syms, end=E.END)
    tab = E.build_table(cache, syms)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    test = tab[tab.ts >= hs].reset_index(drop=True)
    art = REPO / "comms/research/RQ-20261101-c692-06/41324826751/model"   # the frozen v1 booster that is live
    # provenance: Booster — regression booster file: predicts net R per decision, not a class probability
    pl, ps = (lgb.Booster(model_file=str(art / f"entry_{s}.txt")).predict(test[E.FEATURES]) for s in ("long", "short"))
    taken = E.policy(test, pl, ps, 0.10)
    key = test.set_index(["symbol", "ts"])[["atr", "entry"]]
    got = key.reindex(pd.MultiIndex.from_arrays([taken.symbol, pd.to_datetime(taken.ts, utc=True)]))
    taken["atr"], taken["entry"] = got["atr"].to_numpy(), got["entry"].to_numpy()
    return taken


def run(a) -> int:
    import holdout_lock as HL
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cal = calibrate(a)
    (out / "calibration.json").write_text(json.dumps(cal, indent=1) + "\n")
    print(f"calibration: {cal['mean_delta_F_bps']:+.2f} bps (a3f1 +2.03), calibrated={cal['calibrated']}", flush=True)
    taken = v1_decisions(Path(a.kcache))
    print(f"v1 held-out decisions: {len(taken)} on {taken.symbol.nunique()} symbols", flush=True)
    # the claim comes BEFORE any post-decision 1m outcome is read
    claim = HL.claim_read(MODEL_ID, E.HOLDOUT_START, E.END, UNIT, a.reader, Path(a.ledger), train_end="2025-09-30", family="EXEC")
    cache = Path(a.cache)
    # epoch seconds via the unit-explicit path: pandas 3 stores datetimes in ms/us, so astype("int64") // 1e9 is wrong (found on the
    # first attempt 2026-11-12, which therefore read no post-decision bar; disclosed in the result)
    taken["T"] = (pd.to_datetime(taken.ts, utc=True) + pd.Timedelta(hours=1)).dt.as_unit("s").astype("int64")
    assert taken["T"].min() >= int(pd.Timestamp(E.HOLDOUT_START, tz="UTC").timestamp())
    taken["day"] = pd.to_datetime(taken["T"], unit="s", utc=True).dt.date
    jobs = sorted(set(zip(taken.symbol, taken.day)))
    with cf.ThreadPoolExecutor(24) as ex:
        frames = dict(zip(jobs, ex.map(lambda j: fetch_1m(j[0], j[1], cache), jobs)))
    rows = []
    for r in taken.itertuples(index=False):
        d = frames.get((r.symbol, r.day))
        res = None
        opp = None
        if d is not None and len(d) > 100:
            tk = tick_of(d)
            res = delta_f(d, int(r.T), 1 if r.side == "long" else -1, tk)
            opp = delta_f(d, int(r.T), -1 if r.side == "long" else 1, tk)
        rows.append({"symbol": r.symbol, "day": str(r.day), "side": r.side, "net_r_taker": r.net_r,
                     "delta_bps_opp": (opp or {}).get("delta_bps", np.nan),
                     "per_r": (r.entry / (2.0 * r.atr)) if r.atr and r.atr > 0 else np.nan,
                     **(res or {"delta_bps": np.nan, "filled": None, "mid": np.nan, "tick_bps": np.nan})})
    df = pd.DataFrame(rows)
    df["delta_r"] = df.delta_bps / 1e4 * df.per_r
    df["delta_r_opp"] = df.delta_bps_opp / 1e4 * df.per_r
    ok = df.dropna(subset=["delta_r", "delta_r_opp"])
    mean, lo, hi = DMF.day_block_ci(ok.delta_r.to_numpy(), ok.day.to_numpy())
    mb, lob, hib = DMF.day_block_ci(ok.delta_bps.to_numpy(), ok.day.to_numpy())
    n, ns = len(ok), int(ok.symbol.nunique())
    if not cal["calibrated"]:
        v, why = "indeterminate", f"1m approximation not calibrated: {cal['mean_delta_F_bps']:+.2f} bps vs a3f1 +2.03 (band {CAL_BAND})"
    elif n < N_FLOOR or ns < SYM_FLOOR:
        v, why = "indeterminate", f"measured decisions {n} / symbols {ns} below floor"
    elif mean > 0 and lo > 0:
        v, why = "pass", f"maker entry delta {mean:+.4f} R/decision (day-block CI95 [{lo:+.4f}, {hi:+.4f}]), {mb:+.2f} bps, n={n}"
    else:
        v, why = "fail", f"maker entry delta {mean:+.4f} R/decision (day-block CI95 [{lo:+.4f}, {hi:+.4f}]) does not clear 0, n={n}"
    fl = ok.filled.astype(bool)
    # matched random (reported): same (symbol, T), side drawn at random with v1's long share
    p_long = float((ok.side == "long").mean())
    is_long = (ok.side == "long").to_numpy()
    own, opp_r = ok.delta_r.to_numpy(), ok.delta_r_opp.to_numpy()
    long_d, short_d = np.where(is_long, own, opp_r), np.where(is_long, opp_r, own)
    rng = np.random.default_rng(DMF.BOOT_SEED)
    draws = [float(np.where(rng.random(len(ok)) < p_long, long_d, short_d).mean()) for _ in range(200)]
    matched = {"draws": 200, "p_long": p_long, "mean_of_means": float(np.mean(draws)), "p05": float(np.percentile(draws, 5)),
               "p95": float(np.percentile(draws, 95))}
    res = {"unit": UNIT, "verdict": v, "why": why, "calibration": cal, "n_decisions": len(df), "n_measured": n, "n_symbols": ns,
           "mean_delta_r": mean, "ci95_delta_r": [lo, hi], "mean_delta_bps": mb, "ci95_delta_bps": [lob, hib],
           "fill_rate": float(fl.mean()), "delta_bps_if_filled": float(ok.delta_bps[fl].mean()) if fl.any() else None,
           "delta_bps_if_unfilled": float(ok.delta_bps[~fl].mean()) if (~fl).any() else None,
           "by_side": {s: {"n": int((ok.side == s).sum()), "mean_delta_r": float(ok.delta_r[ok.side == s].mean())} for s in ("long", "short")},
           "taker_mean_net_r_on_measured": float(ok.net_r_taker.mean()), "implied_maker_mean_net_r": float(ok.net_r_taker.mean() + mean),
           "traded5": {"n": int(ok.symbol.isin(["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]).sum()),
                       "mean_delta_r": float(ok.delta_r[ok.symbol.isin(["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"])].mean())},
           "median_tick_bps": float(ok.tick_bps.median()), "matched_random_direction": matched,
           "disclosure": "a first attempt (2026-11-12 ~20:50Z) made the EXEC ledger claim, then computed every decision time in 1970 (pandas 3 datetime unit), so every 1m fetch 404d and NO post-decision bar was read; it crashed on an empty sample. This run re-claims from the repo ledger; the aborted claim is not counted as a read.", "holdout_lock": claim, "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    df.to_csv(out / "decisions.csv.gz", index=False)
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> None:
    T0 = 1_700_000_000 - (1_700_000_000 % 3600)
    t = np.arange(T0 - 3600, T0 + 3600, 60)
    base = np.full(len(t), 100.0)
    d = pd.DataFrame({"t": t, "open": base, "high": base + 0.01, "low": base - 0.01, "close": base})
    tick = 0.01
    # flat market within one tick: long maker never trades a tick THROUGH bid (99.995 - 0.01) -> unfilled, fallback ask 100.005
    r = delta_f(d, int(T0), 1, tick)
    assert r is not None and r["filled"] is False and abs(r["delta_bps"]) < 1e-9, r
    # a dip of 2 ticks in the window fills the long: delta = (ask - bid)/mid*1e4 + 3.5 = 1 tick in bps + 3.5
    d2 = d.copy()
    d2.loc[d2.t == T0 + 120, "low"] = 99.97
    r = delta_f(d2, int(T0), 1, tick)
    assert r["filled"] and abs(r["delta_bps"] - (0.01 / 100 * 1e4 + 3.5)) < 1e-6, r
    # runaway: price jumps up 1% and never returns -> unfilled long pays the drift
    d3 = d.copy()
    m = d3.t >= T0
    for c in ("open", "high", "low", "close"):
        d3.loc[m, c] = 101.0
    r = delta_f(d3, int(T0), 1, tick)
    assert (not r["filled"]) and r["delta_bps"] < -90, r
    # short mirror of the fill case
    d4 = d.copy()
    d4.loc[d4.t == T0 + 60, "high"] = 100.03
    r = delta_f(d4, int(T0), -1, tick)
    assert r["filled"] and abs(r["delta_bps"] - (0.01 / 100 * 1e4 + 3.5)) < 1e-6, r
    # the minute ending at T must exist
    assert delta_f(d[d.t != T0 - 60], int(T0), 1, tick) is None
    print("ml_entry_maker_replay self-test OK")


def main(argv=None) -> int:
    import holdout_lock as HL
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "calibrate"])
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--out", default="/tmp/maker_replay")
    ap.add_argument("--cache", default="/tmp/maker_1m")
    ap.add_argument("--kcache", default="/tmp/ml_decision_klines")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default=str(HL.LEDGER))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "calibrate":
        print(json.dumps(calibrate(a), indent=1))
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
