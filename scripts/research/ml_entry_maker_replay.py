#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-1c4e-01.yaml (ENTRY execution lever: maker entry on ml_entry's own decisions, lane ML-DECISION-MODELS)
# wiring: research/queue/RQ-20261118-e8a1-02.yaml (`run --entry-w-min 1 --entry-peg mid`: maker ENTRY at 04a5-05's passing exit policy)
# wiring: research/queue/RQ-20261118-04a5-05.yaml (`exit --exit-peg mid`: D9 mid-peg arm, aadc-10 fail_action)
# wiring: research/queue/RQ-20261118-e8a1-01.yaml (`exit --exit-peg mid --population dev_oof`: fresh-window confirmation of 04a5-05)
# wiring: research/queue/RQ-20261119-b9d0-03.yaml (`exit-gate`: D9 spec B, a learned P(fill) gate on the mid-peg time-stop exit)
# wiring: research/queue/RQ-20261117-aadc-02.yaml (`exit`: maker EXIT on v1's 24h time-stop exits, row ML-D9-MAKER-EXIT-HARNESS)
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
    python3 scripts/research/ml_entry_maker_replay.py exit --unit RQ-20261117-aadc-02 --out O [--cache C]
    python3 scripts/research/ml_entry_maker_replay.py --self-test

EXIT (row ML-D9-MAKER-EXIT-HARNESS, 2026-11-17): the same policy F, on the CLOSING order of v1's held-out decisions that leave on the
24h TIME STOP (reason 0). Why only those: 1c4e-01 FAILED because a directional pick runs away from a resting entry limit; a time-stop
exit is a clock event, not a directional pick, so that selection is absent. SL/TP exits are resting orders already and are untouched.
Exit epoch T = decision bar open + (HORIZON_H + 1) h (bar t+H's close); the closing order's direction is -side (sell to close a long).
delta_R = delta_F / 1e4 x mid / (SL_ATR x ATR14). An exit at 00:00Z needs the previous day's last minute, so that day is stitched in.
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
def delta_f(d: pd.DataFrame, T: int, direction: int, tick: float, w_min: int | None = None, peg: str = "touch") -> dict | None:
    """delta_F (bps) for a decision at epoch second T (on a minute boundary) on one symbol-day of 1m bars.

    w_min: the market-fallback window in minutes (default the a3f1-01 primary W_MIN; the calibration arm always uses it).
    peg: "touch" (default, policy F: rest at the near touch -/+ K ticks, i.e. bid for a buy, ask for a sell) or "mid" (D9 mid-peg arm,
    RQ-20261118-04a5-05: rest AT the modelled mid p, the close of the minute ending at T, half a tick inside the touch). The fill rule is
    unchanged for both: STRICT, the 1m path must trade one tick THROUGH the resting price within (T, T+W]; unfilled -> market at T+W."""
    w = int(w_min or W_MIN)
    t = d["t"].to_numpy()
    i0 = int(np.searchsorted(t, T - 60))          # the minute ending at T starts at T - 60
    if i0 >= len(t) or t[i0] != T - 60:
        return None
    iW = int(np.searchsorted(t, T + 60 * (w - 1)))
    if iW >= len(t) or t[iW] != T + 60 * (w - 1):
        return None
    p = float(d["close"].iat[i0])
    bid, ask, mid = p - tick / 2.0, p + tick / 2.0, p
    pw = float(d["close"].iat[iW])
    seg = slice(i0 + 1, iW + 1)                   # minutes starting T .. T+(W-1)m == (T, T+W]
    eps = tick * 1e-6
    long = direction == 1
    if peg not in ("touch", "mid"):
        raise ValueError(f"peg must be touch or mid, got {peg!r}")
    if long:
        L, taker_px, fb_px = (mid if peg == "mid" else bid - K * tick), ask, pw + tick / 2.0
        filled = bool((d["low"].to_numpy()[seg] <= L - tick + eps).any())
    else:
        L, taker_px, fb_px = (mid if peg == "mid" else ask + K * tick), bid, pw - tick / 2.0
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


def dev_oof_decisions(cache: Path, tau: float = 0.10) -> pd.DataFrame:
    """v1's RECIPE (c692-01: FEATURES, LGB_PARAMS, purge + embargo) scored OUT OF FOLD on the development walk-forward
    (E.DEV_FOLDS, 2022-01-01..HOLDOUT_START): each fold is fit only on rows before its start, exactly as E.walk_forward does,
    and the same tau-0.10 sequential policy picks the decisions. A population DISJOINT from the held-out year every maker-exit
    read so far used (1c4e-01, aadc-02, aadc-10, 04a5-05), so it is the fresh window 04a5-05's pass_action asks for. These are
    per-fold refits, not the frozen live booster (declared in the population string)."""
    import itertools
    syms = E.universe()
    E.fetch(cache, syms, end=E.END)
    tab = E.build_table(cache, syms)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [hs]
    out = []
    for lo, hi in itertools.pairwise(bounds):
        test = dev[(dev.ts >= lo) & (dev.ts < hi - pd.Timedelta(hours=E.HORIZON_H + 1))].reset_index(drop=True)
        pl, ps = E.fit_predict(E.purge_train(dev, lo), test)
        tk = E.policy(test, pl, ps, tau)
        key = test.set_index(["symbol", "ts"])[["atr", "entry"]]
        got = key.reindex(pd.MultiIndex.from_arrays([tk.symbol, pd.to_datetime(tk.ts, utc=True)]))
        tk["atr"], tk["entry"] = got["atr"].to_numpy(), got["entry"].to_numpy()
        out.append(tk)
        print(json.dumps({"fold": str(lo.date()), "n_taken": len(tk)}), flush=True)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


POPULATIONS = {  # name -> (window start, window end, train_end for the holdout-ledger disjointness check, label)
    "heldout": (E.HOLDOUT_START, E.END, "2025-09-30",
                f"v1 (frozen ml_entry booster, tau 0.10) held-out decisions {E.HOLDOUT_START}..{E.END}"),
    # each fold trains only on rows before its own start; the earliest test row is 2022-01-01, so the ledger's window-level
    # train_end is the day before it (the EXEC lever itself is not fit at all)
    "dev_oof": (E.DEV_FOLDS[0], "2025-09-30", "2021-12-31",
                f"v1's recipe (c692-01) scored out of fold on the dev walk-forward {E.DEV_FOLDS[0]}..2025-09-30 (per-fold "
                "refits, tau 0.10; disjoint from the held-out year)"),
}


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
    unit = getattr(a, "unit", UNIT) or UNIT
    ew, epeg = getattr(a, "entry_w_min", None), getattr(a, "entry_peg", "touch")
    claim = HL.claim_read(MODEL_ID, E.HOLDOUT_START, E.END, unit, a.reader, Path(a.ledger), train_end="2025-09-30", family="EXEC")
    # 1c4e-01 (the default unit) graded on the undeflated day-block CI95 (its claim was n_tries 1); every later entry unit is graded
    # at the DEFLATED lower percentile its own claim returns, as the exit units are
    deflated = unit != UNIT
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
            res = delta_f(d, int(r.T), 1 if r.side == "long" else -1, tk, ew, epeg)
            opp = delta_f(d, int(r.T), -1 if r.side == "long" else 1, tk, ew, epeg)
        rows.append({"symbol": r.symbol, "day": str(r.day), "side": r.side, "net_r_taker": r.net_r,
                     "delta_bps_opp": (opp or {}).get("delta_bps", np.nan),
                     "per_r": (r.entry / (2.0 * r.atr)) if r.atr and r.atr > 0 else np.nan,
                     **(res or {"delta_bps": np.nan, "filled": None, "mid": np.nan, "tick_bps": np.nan})})
    df = pd.DataFrame(rows)
    df["delta_r"] = df.delta_bps / 1e4 * df.per_r
    df["delta_r_opp"] = df.delta_bps_opp / 1e4 * df.per_r
    ok = df.dropna(subset=["delta_r", "delta_r_opp"])
    if deflated:
        lo_pct = float(claim["bar"]["ci_lo_percentile"])
        mean, lo, hi = block_ci(ok.delta_r.to_numpy(), ok.day.to_numpy(), lo_pct)
        mb, lob, hib = block_ci(ok.delta_bps.to_numpy(), ok.day.to_numpy(), lo_pct)
    else:
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
    if deflated:
        why = why.replace("day-block CI95", f"deflated day-block CI at percentile {lo_pct:.4f}")
    res = {"unit": unit, **({"entry_w_min": int(ew or W_MIN), "entry_peg": epeg, "ci_lo_percentile": lo_pct} if deflated else {}),
           "verdict": v, "why": why, "calibration": cal, "n_decisions": len(df), "n_measured": n, "n_symbols": ns,
           "mean_delta_r": mean, "ci95_delta_r": [lo, hi], "mean_delta_bps": mb, "ci95_delta_bps": [lob, hib],
           "fill_rate": float(fl.mean()), "delta_bps_if_filled": float(ok.delta_bps[fl].mean()) if fl.any() else None,
           "delta_bps_if_unfilled": float(ok.delta_bps[~fl].mean()) if (~fl).any() else None,
           "by_side": {s: {"n": int((ok.side == s).sum()), "mean_delta_r": float(ok.delta_r[ok.side == s].mean())} for s in ("long", "short")},
           "taker_mean_net_r_on_measured": float(ok.net_r_taker.mean()), "implied_maker_mean_net_r": float(ok.net_r_taker.mean() + mean),
           "traded5": {"n": int(ok.symbol.isin(["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]).sum()),
                       "mean_delta_r": float(ok.delta_r[ok.symbol.isin(["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"])].mean())},
           "median_tick_bps": float(ok.tick_bps.median()), "matched_random_direction": matched,
           **({} if deflated else {"disclosure": "a first attempt (2026-11-12 ~20:50Z) made the EXEC ledger claim, then computed every decision time in 1970 (pandas 3 datetime unit), so every 1m fetch 404d and NO post-decision bar was read; it crashed on an empty sample. This run re-claims from the repo ledger; the aborted claim is not counted as a read."}), "holdout_lock": claim, "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    df.to_csv(out / "decisions.csv.gz", index=False)
    if deflated:   # the runner collector reads verdict.json (1c4e-01 ran locally and wrote only result.json)
        verdict = {"verdict": v, "read_state": "measured", "n": n,
                   "population": (f"v1 (frozen ml_entry booster, tau 0.10) held-out decisions {E.HOLDOUT_START}..{E.END}, entry order "
                                  f"worked post-only at the {epeg} with a {int(ew or W_MIN)}-min market fallback, measured where 1m "
                                  "Binance-vision klines exist"),
                   "note": why, "measurement": {k: res[k] for k in res if k not in ("calibration", "holdout_lock", "disclosure")}}
        (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ exit (v1's time-stop exits)
EXIT_UNIT = "RQ-20261117-aadc-02"
EXIT_RULE_ID = "RULE-RQ20261117-aadc-02-MAKER-EXIT"
EXIT_MODEL_ID = "EXEC-maker-exit-ml_entry_v1"
EXIT_N_FLOOR, EXIT_SYM_FLOOR = 1000, 10


def exit_epoch(ts, horizon_h: int) -> int:
    """Epoch second of the time-stop exit: the close of bar t+H, i.e. decision bar open + (H + 1) h."""
    return int((pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts, tz="UTC")).timestamp()) \
        + 3600 * (horizon_h + 1)


def day_frame(sym: str, T: int, frames: dict) -> pd.DataFrame | None:
    """1m bars for the day of T; at 00:00Z the previous day is stitched in (the minute ending at T starts the day before)."""
    day = datetime.fromtimestamp(T, tz=timezone.utc).date()
    d = frames.get((sym, day))
    if d is None:
        return None
    if T % 86400 == 0:
        prev = frames.get((sym, date.fromordinal(day.toordinal() - 1)))
        if prev is None:
            return None
        d = pd.concat([prev, d], ignore_index=True)
    return d


def block_ci(values: np.ndarray, days: np.ndarray, lo_pct: float, reps: int = 2000, seed: int = 20261117):
    """Day-block bootstrap mean CI at an arbitrary lower percentile (the deflated holdout bar's ci_lo_percentile)."""
    uniq = np.unique(days)
    idx = [np.flatnonzero(days == d) for d in uniq]
    sums = np.array([values[i].sum() for i in idx])
    cnts = np.array([len(i) for i in idx])
    rng = np.random.default_rng(seed)
    boots = np.empty(reps)
    for r in range(reps):
        pick = rng.integers(0, len(uniq), len(uniq))
        boots[r] = sums[pick].sum() / cnts[pick].sum()
    return float(values.mean()), float(np.percentile(boots, lo_pct)), float(np.percentile(boots, 100.0 - lo_pct))


def matched_random_side(ok: pd.DataFrame, draws: int = 200) -> dict:
    """Reported, never gating: at the SAME exit moments, the closing order's side drawn at random with v1's long share.
    If the time-stop exit is truly non-directional, v1's own mean should sit inside the random draws' 5-95% band."""
    p_long = float((ok.side == "long").mean())
    is_long = (ok.side == "long").to_numpy()
    own, opp = ok.delta_r.to_numpy(), ok.delta_r_opp.to_numpy()
    sell_d, buy_d = np.where(is_long, own, opp), np.where(is_long, opp, own)   # closing a long = sell
    rng = np.random.default_rng(DMF.BOOT_SEED)
    means = [float(np.where(rng.random(len(ok)) < p_long, sell_d, buy_d).mean()) for _ in range(draws)]
    return {"draws": draws, "p_long": p_long, "own_mean": float(own.mean()), "mean_of_means": float(np.mean(means)),
            "p05": float(np.percentile(means, 5)), "p95": float(np.percentile(means, 95))}


def exit_verdict(cal_ok: bool, n: int, ns: int, mean: float | None, lo: float | None) -> tuple[str, str]:
    if not cal_ok:
        return "indeterminate", "1m approximation not calibrated against a3f1-01"
    if n < EXIT_N_FLOOR or ns < EXIT_SYM_FLOOR:
        return "indeterminate", f"measured time-stop exits {n} / symbols {ns} below floor ({EXIT_N_FLOOR} / {EXIT_SYM_FLOOR})"
    if mean is not None and lo is not None and mean > 0 and lo > 0:
        return "pass", f"maker exit delta {mean:+.4f} R/decision, deflated lower bound {lo:+.4f} > 0, n={n}"
    return "fail", f"maker exit delta {mean:+.4f} R/decision, deflated lower bound {lo:+.4f} does not clear 0, n={n}"


def run_exit(a) -> int:
    import holdout_lock as HL
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cal = calibrate(a)
    (out / "calibration.json").write_text(json.dumps(cal, indent=1) + "\n")
    pop = getattr(a, "population", "heldout")
    w_start, w_end, train_end, pop_label = POPULATIONS[pop]
    taken = v1_decisions(Path(a.kcache)) if pop == "heldout" else dev_oof_decisions(Path(a.kcache))
    n_all = len(taken)
    ts_exit = taken[taken.reason == 0].reset_index(drop=True)
    print(f"{pop} decisions {n_all}; time-stop exits {len(ts_exit)}", flush=True)
    # the claim comes BEFORE any post-exit 1m outcome is read
    claim = HL.claim_read(EXIT_MODEL_ID, w_start, w_end, a.unit, a.reader, Path(a.ledger), train_end=train_end,
                          family="EXEC")
    lo_pct = float(claim["bar"]["ci_lo_percentile"])
    cache = Path(a.cache)
    ts_exit["T"] = [exit_epoch(t, E.HORIZON_H) for t in ts_exit.ts]
    need = set()
    for sym, T in zip(ts_exit.symbol, ts_exit["T"]):
        day = datetime.fromtimestamp(int(T), tz=timezone.utc).date()
        need.add((sym, day))
        if int(T) % 86400 == 0:
            need.add((sym, date.fromordinal(day.toordinal() - 1)))
    jobs = sorted(need)
    with cf.ThreadPoolExecutor(24) as ex:
        frames = dict(zip(jobs, ex.map(lambda j: fetch_1m(j[0], j[1], cache), jobs)))
    rows = []
    no_tick_days: set = set()
    for r in ts_exit.itertuples(index=False):
        d = day_frame(r.symbol, int(r.T), frames)
        res = opp = None
        tk = None
        if d is not None and len(d) > 100:
            try:
                tk = tick_of(d)
            except ValueError:   # a flat (single-price) symbol-day: no tick, so this exit is UNMEASURED and counted, never a crash
                no_tick_days.add((r.symbol, datetime.fromtimestamp(int(r.T), tz=timezone.utc).date().isoformat()))
        if tk is not None:
            res = delta_f(d, int(r.T), -1 if r.side == "long" else 1, tk, a.exit_w_min, a.exit_peg)
            opp = delta_f(d, int(r.T), 1 if r.side == "long" else -1, tk, a.exit_w_min, a.exit_peg)
        atr = getattr(r, "atr", np.nan)
        mid = (res or {}).get("mid", np.nan)
        rows.append({"symbol": r.symbol, "day": datetime.fromtimestamp(int(r.T), tz=timezone.utc).date().isoformat(),
                     "side": r.side, "net_r_taker": r.net_r, "delta_bps_opp": (opp or {}).get("delta_bps", np.nan),
                     "per_r": (mid / (E.SL_ATR * atr)) if atr and atr > 0 else np.nan,
                     **(res or {"delta_bps": np.nan, "filled": None, "mid": np.nan, "tick_bps": np.nan})})
    df = pd.DataFrame(rows)
    df["delta_r"] = df.delta_bps / 1e4 * df.per_r
    df["delta_r_opp"] = df.delta_bps_opp / 1e4 * df.per_r
    ok = df.dropna(subset=["delta_r", "delta_r_opp"])
    n, ns = len(ok), int(ok.symbol.nunique())
    matched = matched_random_side(ok) if n else None
    if n:
        mean, lo, hi = block_ci(ok.delta_r.to_numpy(), ok.day.to_numpy(), lo_pct)
        mb, lob, hib = block_ci(ok.delta_bps.to_numpy(), ok.day.to_numpy(), lo_pct)
    else:
        mean = lo = hi = mb = lob = hib = None
    v, why = exit_verdict(bool(cal["calibrated"]), n, ns, mean, lo)
    fl = ok.filled.astype(bool) if n else pd.Series(dtype=bool)
    res = {"unit": a.unit, "rule": a.exit_rule, "exit_w_min": int(a.exit_w_min), **({"exit_peg": a.exit_peg} if a.exit_peg != "touch" else {}),
           **({"population": pop} if pop != "heldout" else {}), "verdict": v, "why": why, "calibration": cal, "n_decisions_all": n_all,
           "n_time_stop_exits": len(ts_exit), "n_measured": n, "n_symbols": ns, "mean_delta_r": mean,
           "deflated_ci_delta_r": [lo, hi], "ci_lo_percentile": lo_pct, "mean_delta_bps": mb, "deflated_ci_delta_bps": [lob, hib],
           "fill_rate": float(fl.mean()) if n else None,
           "delta_bps_if_filled": float(ok.delta_bps[fl].mean()) if n and fl.any() else None,
           "delta_bps_if_unfilled": float(ok.delta_bps[~fl].mean()) if n and (~fl).any() else None,
           "by_side": {s: {"n": int((ok.side == s).sum()), "mean_delta_r": float(ok.delta_r[ok.side == s].mean())}
                       for s in ("long", "short") if n and (ok.side == s).any()},
           "taker_mean_net_r_time_stop": float(ok.net_r_taker.mean()) if n else None,
           "share_of_all_decisions": (len(ts_exit) / n_all) if n_all else None,
           "per_all_decisions_delta_r": (mean * n / n_all) if (n_all and mean is not None) else None,
           "matched_random_side": matched, "unmeasured_flat_symbol_days": sorted(f"{a}:{b}" for a, b in no_tick_days),
           "holdout_lock": claim, "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    df.to_csv(out / "exits.csv.gz", index=False)
    verdict = {"verdict": v, "read_state": "measured", "n": n,
               "population": f"{pop_label} that exit on the 24h time stop, measured where 1m Binance-vision klines exist",
               "note": why, "measurement": {k: res[k] for k in res if k not in ("calibration", "holdout_lock")}}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ exit-gate (D9 spec B)
# RQ-20261119-b9d0-03 (e8a1-01's registered next step): a LEARNED gate on the mid-peg time-stop exit. At the mid peg a FILLED exit
# earns exactly half a tick plus the maker/taker fee gap (known at T); an UNFILLED one pays the W-minute drift to the fallback market.
# A P(fill) classifier fit on the dev out-of-fold exits (pre-T 1m features only) decides per exit: post at the mid iff
# P x filled_gain + (1 - P) x U_hat > 0 (U_hat = the dev mean unfilled delta, fixed before any held-out bar is read), else take the
# market at T (delta 0). Graded on the held-out year's exits against ALWAYS posting (the e8a1-01 / 04a5-05 policy), paired per exit.
GATE_UNIT = "RQ-20261119-b9d0-03"
GATE_RULE_ID = "RULE-RQ20261119-b9d0-03-MAKER-EXIT-FILL-GATE"
GATE_MODEL_ID = "EXEC-maker-exit-fillgate-ml_entry_v1"
GATE_FEATURES = ["dir", "hour", "tick_bps", "ret1", "ret5", "ret15", "ret60", "rv15", "rng5_ticks", "pos60"]
GATE_LGB = {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 200, "subsample": 0.8,
            "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": 20261119, "verbose": -1, "n_jobs": 4}
GATE_MIN_SKIP = 0.01   # a gate that skips < 1% of exits is inert: INDETERMINATE, not a FAIL on d == 0
GATE_RANDOM_DRAWS = 1000   # matched-random control: skip the SAME number of held-out exits chosen at random
GATE_RANDOM_P = 0.05


def pre_features(d: pd.DataFrame, T: int, direction: int, tick: float) -> dict | None:
    """Features from the 1m bars that END at or before T (the minute ending at T starts at T - 60); nothing after T is read.
    Returns are signed by the closing order's direction (dir x price change, in bps): positive = price moved the way the order
    trades (up for a buy). A window without enough history is NaN (LightGBM handles it)."""
    t = d["t"].to_numpy()
    i0 = int(np.searchsorted(t, T - 60))
    if i0 >= len(t) or t[i0] != T - 60:
        return None
    c = d["close"].to_numpy()
    h, lo = d["high"].to_numpy(), d["low"].to_numpy()
    p = float(c[i0])

    def ret(k):
        j = i0 - k
        return float(direction * (p - c[j]) / p * 1e4) if j >= 0 and t[j] == T - 60 * (k + 1) else np.nan
    w15 = c[max(0, i0 - 15):i0 + 1]
    rv15 = float(np.std(np.diff(np.log(w15))) * 1e4) if len(w15) >= 16 else np.nan
    rng5 = float((h[max(0, i0 - 4):i0 + 1].max() - lo[max(0, i0 - 4):i0 + 1].min()) / tick) if i0 >= 4 else np.nan
    if i0 >= 59:
        hh, ll = h[i0 - 59:i0 + 1].max(), lo[i0 - 59:i0 + 1].min()
        pos60 = float((p - ll) / (hh - ll)) if hh > ll else 0.5
        pos60 = pos60 if direction == 1 else 1.0 - pos60
    else:
        pos60 = np.nan
    return {"dir": float(direction), "hour": float(datetime.fromtimestamp(T, tz=timezone.utc).hour), "tick_bps": tick / p * 1e4,
            "ret1": ret(1), "ret5": ret(5), "ret15": ret(15), "ret60": ret(60), "rv15": rv15, "rng5_ticks": rng5, "pos60": pos60}


def exit_rows(taken: pd.DataFrame, a, frames_cache: Path) -> pd.DataFrame:
    """One row per measured time-stop exit of `taken`: the mid-peg W-min delta (delta_f), its fill flag, per_r and pre-T features."""
    ts_exit = taken[taken.reason == 0].reset_index(drop=True)
    ts_exit["T"] = [exit_epoch(t, E.HORIZON_H) for t in ts_exit.ts]
    need = set()
    for sym, T in zip(ts_exit.symbol, ts_exit["T"]):
        day = datetime.fromtimestamp(int(T), tz=timezone.utc).date()
        need.add((sym, day))
        if int(T) % 86400 == 0:
            need.add((sym, date.fromordinal(day.toordinal() - 1)))
    jobs = sorted(need)
    with cf.ThreadPoolExecutor(24) as ex:
        frames = dict(zip(jobs, ex.map(lambda j: fetch_1m(j[0], j[1], frames_cache), jobs)))
    rows = []
    for r in ts_exit.itertuples(index=False):
        d = day_frame(r.symbol, int(r.T), frames)
        if d is None or len(d) <= 100:
            continue
        try:
            tk = tick_of(d)
        except ValueError:   # allow-silent: a flat symbol-day has no tick; the exit is unmeasured (n_time_stop vs n_measured shows it)
            continue
        direction = -1 if r.side == "long" else 1
        res = delta_f(d, int(r.T), direction, tk, a.exit_w_min, "mid")
        ft = pre_features(d, int(r.T), direction, tk)
        atr = getattr(r, "atr", np.nan)
        if res is None or ft is None or not (atr and atr > 0):
            continue
        rows.append({"symbol": r.symbol, "day": datetime.fromtimestamp(int(r.T), tz=timezone.utc).date().isoformat(),
                     "side": r.side, "per_r": res["mid"] / (E.SL_ATR * atr), "filled": bool(res["filled"]),
                     "delta_bps": res["delta_bps"], **ft})
    df = pd.DataFrame(rows)
    if len(df):
        df["delta_r"] = df.delta_bps / 1e4 * df.per_r
        df["filled_gain_bps"] = df.tick_bps / 2.0 + (TAKER - MAKER)
    df.attrs["n_time_stop"] = len(ts_exit)
    return df


def gate_decide(p_fill: np.ndarray, filled_gain_bps: np.ndarray, u_hat_bps: float) -> np.ndarray:
    """True = post at the mid; False = take the market at T (delta 0)."""
    return p_fill * filled_gain_bps + (1.0 - p_fill) * u_hat_bps > 0.0


def auc_score(score: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def matched_random_skip(delta_r: np.ndarray, n_skip: int, mean_d: float, draws: int = GATE_RANDOM_DRAWS,
                        seed: int = 20261119) -> dict:
    """GATING control: skip the SAME number of exits, chosen uniformly at random, `draws` times. The gate's choice must beat it, so
    the result is about WHICH exits the model skips, not about skipping as such. p = (1 + #draws with mean d >= the gate's) / (1 + draws)."""
    n = len(delta_r)
    rng = np.random.default_rng(seed)
    means = np.array([-delta_r[rng.choice(n, n_skip, replace=False)].sum() / n for _ in range(draws)]) if n_skip and n else np.zeros(draws)
    return {"draws": draws, "n_skip": int(n_skip), "mean_of_means": float(means.mean()), "p95": float(np.percentile(means, 95)),
            "p_value": float((1 + (means >= mean_d).sum()) / (1 + draws))}


def gate_verdict(cal_ok: bool, n_dev: int, n_held: int, ns_held: int, skip_share: float | None, mean_d: float | None,
                 lo_d: float | None, gated_mean: float | None, p_random: float | None = None) -> tuple[str, str]:
    if not cal_ok:
        return "indeterminate", "1m approximation not calibrated against a3f1-01"
    if n_dev < EXIT_N_FLOOR or n_held < EXIT_N_FLOOR or ns_held < EXIT_SYM_FLOOR:
        return "indeterminate", f"exits dev {n_dev} / held-out {n_held} / held-out symbols {ns_held} below floor"
    if skip_share is None or skip_share < GATE_MIN_SKIP:
        return "indeterminate", f"gate inert: skips {skip_share} of held-out exits (< {GATE_MIN_SKIP})"
    txt = (f"gated - always-post {mean_d:+.5f} R/exit, deflated lower bound {lo_d:+.5f}; gated vs taker {gated_mean:+.5f} R/exit; "
           f"skips {skip_share:.3f}, matched-random p {p_random}, n={n_held}")
    if mean_d > 0 and lo_d > 0 and gated_mean > 0 and p_random is not None and p_random < GATE_RANDOM_P:
        return "pass", txt
    return "fail", txt


def run_exit_gate(a) -> int:
    import holdout_lock as HL
    import lightgbm as lgb
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cal = calibrate(a)
    (out / "calibration.json").write_text(json.dumps(cal, indent=1) + "\n")
    cache = Path(a.cache)
    # TRAIN: the dev out-of-fold exits (their outcomes were read by e8a1-01; here they are the training set, not a holdout read)
    dev = exit_rows(dev_oof_decisions(Path(a.kcache)), a, cache)
    u_hat = float(dev.delta_bps[~dev.filled].mean()) if len(dev) and (~dev.filled).any() else float("nan")
    clf = lgb.LGBMClassifier(**GATE_LGB).fit(dev[GATE_FEATURES], dev.filled.astype(int)) if len(dev) else None
    # TEST: the held-out year; the claim comes BEFORE any post-exit 1m bar of it is read
    w_start, w_end, train_end, _lab = POPULATIONS["heldout"]
    held_taken = v1_decisions(Path(a.kcache))
    claim = HL.claim_read(GATE_MODEL_ID, w_start, w_end, a.unit, a.reader, Path(a.ledger), train_end=train_end, family="EXEC")
    lo_pct = float(claim["bar"]["ci_lo_percentile"])
    held = exit_rows(held_taken, a, cache)
    n_dev, n_held = len(dev), len(held)
    ns_held = int(held.symbol.nunique()) if n_held else 0
    res = {"unit": a.unit, "rule": GATE_RULE_ID, "exit_w_min": int(a.exit_w_min), "exit_peg": "mid", "calibration": cal,
           "features": GATE_FEATURES, "lgb_params": GATE_LGB, "n_dev_time_stop": dev.attrs.get("n_time_stop"), "n_dev_exits": n_dev,
           "n_held_time_stop": held.attrs.get("n_time_stop"), "n_held_exits": n_held, "n_held_symbols": ns_held,
           "u_hat_bps_dev": u_hat, "dev_fill_rate": float(dev.filled.mean()) if n_dev else None}
    mean_d = lo_d = gated_mean = skip = p_random = None
    if n_held and clf is not None:
        # provenance: predict_proba — column 1 of the binary LGBMClassifier fit on dev is P(filled) for the order resting at the mid
        pf = clf.predict_proba(held[GATE_FEATURES])[:, 1]
        post = gate_decide(pf, held.filled_gain_bps.to_numpy(), u_hat)
        d = np.where(post, 0.0, -held.delta_r.to_numpy())                 # gated - always-post, per exit
        gated = np.where(post, held.delta_r.to_numpy(), 0.0)
        days = held.day.to_numpy()
        mean_d, lo_d, hi_d = block_ci(d, days, lo_pct)
        gated_mean, g_lo, g_hi = block_ci(gated, days, lo_pct)
        always_mean, a_lo, a_hi = block_ci(held.delta_r.to_numpy(), days, lo_pct)
        skip = float(1.0 - post.mean())
        mr = matched_random_skip(held.delta_r.to_numpy(), int((~post).sum()), mean_d)
        p_random = mr["p_value"]
        # reported, never gating: the SAME decision rule with P fixed at the dev base rate. The filled gain is known at T, so a gate
        # can beat random skips by tick size alone; the gap between the model gate and this one is what P(fill) itself adds.
        post0 = gate_decide(np.full(n_held, float(dev.filled.mean())), held.filled_gain_bps.to_numpy(), u_hat)
        d0 = np.where(post0, 0.0, -held.delta_r.to_numpy())
        base_rate_gate = {"skip_share": float(1.0 - post0.mean()), "mean_d_r": float(d0.mean()),
                          "model_minus_base_rate_d_r": float(np.mean(d) - d0.mean())}
        y = held.filled.astype(int).to_numpy()
        res.update({"skip_share": skip, "matched_random_skip": mr, "base_rate_gate_reported": base_rate_gate, "mean_d_r": mean_d, "deflated_ci_d_r": [lo_d, hi_d], "ci_lo_percentile": lo_pct,
                    "gated_mean_r": gated_mean, "deflated_ci_gated_r": [g_lo, g_hi], "always_post_mean_r": always_mean,
                    "deflated_ci_always_r": [a_lo, a_hi], "held_fill_rate": float(y.mean()),
                    "held_fill_rate_posted": float(y[post].mean()) if post.any() else None,
                    "held_fill_rate_skipped": float(y[~post].mean()) if (~post).any() else None,
                    "auc_p_fill_held": auc_score(pf, y), "brier_held": float(np.mean((pf - y) ** 2)),
                    "brier_const_held": float(np.mean((dev.filled.mean() - y) ** 2)),
                    "mean_d_bps": float(np.where(post, 0.0, -held.delta_bps.to_numpy()).mean()),
                    "by_side": {s: {"n": int((held.side == s).sum()), "mean_d_r": float(d[(held.side == s).to_numpy()].mean())}
                                for s in ("long", "short") if (held.side == s).any()}})
    v, why = gate_verdict(bool(cal["calibrated"]), n_dev, n_held, ns_held, skip, mean_d, lo_d, gated_mean, p_random)
    res.update({"verdict": v, "why": why, "holdout_lock": claim, "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0)})
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    verdict = {"verdict": v, "read_state": "measured", "n": n_held,
               "population": (f"v1 (frozen ml_entry booster, tau 0.10) held-out decisions {w_start}..{w_end} that exit on the 24h time "
                              f"stop, mid-peg W {int(a.exit_w_min)} closing order, P(fill) gate fit on {n_dev} dev out-of-fold exits; "
                              "measured where 1m Binance-vision klines exist"),
               "note": why, "measurement": {k: res[k] for k in res if k not in ("calibration", "holdout_lock", "lgb_params")}}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> None:
    # fresh-window population (RQ-20261118-e8a1-01): disjoint from the held-out year, and each window starts after its train_end
    for _name, (w0, w1, tr_end, _lab) in POPULATIONS.items():
        assert tr_end < w0 <= w1, _name
    assert POPULATIONS["dev_oof"][1] < POPULATIONS["heldout"][0]
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
    # EXIT: closing a long is a SELL (-1). A 2-tick pop fills the resting sell at the ask: +1 tick + 3.5 bps fee saving.
    d5 = d.copy()
    d5.loc[d5.t == T0 + 120, "high"] = 100.03
    r = delta_f(d5, int(T0), -1, tick)
    assert r["filled"] and abs(r["delta_bps"] - (0.01 / 100 * 1e4 + 3.5)) < 1e-6, r
    # W = 1: only the first minute (T, T+1m] counts; the pop at T+2m is outside it -> unfilled, market at T+1m
    r1 = delta_f(d5, int(T0), -1, tick, 1)
    assert r1 is not None and r1["filled"] is False, r1
    d5b = d.copy()
    d5b.loc[d5b.t == T0, "high"] = 100.03
    assert delta_f(d5b, int(T0), -1, tick, 1)["filled"] is True
    # MID PEG (RQ-20261118-04a5-05): a sell rests AT mid 100.0 (not the ask 100.005); STRICT fill needs a high >= 100.01 in (T, T+W].
    # A one-tick pop (100.01) fills the mid peg but NOT the touch (needs 100.015): the half-tick-inside trade-off.
    d6 = pd.DataFrame({"t": t, "open": base, "high": base, "low": base, "close": base})
    d6.loc[d6.t == T0, "high"] = 100.01
    rt, rm = delta_f(d6, int(T0), -1, tick, 1), delta_f(d6, int(T0), -1, tick, 1, "mid")
    assert rt["filled"] is False and rm["filled"] is True, (rt, rm)
    # filled mid sell vs taker at the bid: (mid - bid)/mid*1e4 = half a tick in bps, plus the 3.5 bps fee saving
    assert abs(rm["delta_bps"] - (0.005 / 100 * 1e4 + 3.5)) < 1e-6, rm
    # unfilled mid peg falls back to the market at T+W exactly as the touch arm does (identical delta)
    dflat = pd.DataFrame({"t": t, "open": base, "high": base, "low": base, "close": base})   # never trades a tick through mid
    ru_t, ru_m = delta_f(dflat, int(T0), -1, tick, 1), delta_f(dflat, int(T0), -1, tick, 1, "mid")
    assert ru_m["filled"] is False and abs(ru_m["delta_bps"] - ru_t["delta_bps"]) < 1e-12, (ru_t, ru_m)
    # buy-side mirror: a one-tick dip fills the mid peg only
    d7 = pd.DataFrame({"t": t, "open": base, "high": base, "low": base, "close": base})
    d7.loc[d7.t == T0, "low"] = 99.99
    assert delta_f(d7, int(T0), 1, tick, 1)["filled"] is False and delta_f(d7, int(T0), 1, tick, 1, "mid")["filled"] is True
    # defaults unchanged: peg="touch" is byte-identical to the pre-arm call on every fixture above
    for fx, dr, w in ((d2, 1, None), (d3, 1, None), (d4, -1, None), (d5, -1, 1), (d5b, -1, 1), (d6, -1, 1)):
        assert delta_f(fx, int(T0), dr, tick, w) == delta_f(fx, int(T0), dr, tick, w, "touch")
    try:
        delta_f(d, int(T0), 1, tick, 1, "far")
        raise AssertionError("an unknown peg must be refused")
    except ValueError:
        pass
    # exit epoch = decision bar open + 25 h
    assert exit_epoch(pd.Timestamp("2025-10-01 03:00", tz="UTC"), 24) == int(pd.Timestamp("2025-10-02 04:00", tz="UTC").timestamp())
    # 00:00Z exit stitches the previous day's last minute
    day0 = 1_700_006_400 - (1_700_006_400 % 86400)
    tp = np.arange(day0 - 3600, day0, 60)
    tn = np.arange(day0, day0 + 3600, 60)
    def mk(t):
        return pd.DataFrame({"t": t, "open": 100.0, "high": 100.01, "low": 99.99, "close": 100.0})
    from datetime import datetime as _dt
    dd = _dt.fromtimestamp(day0, tz=timezone.utc).date()
    frames = {("X", dd): mk(tn), ("X", date.fromordinal(dd.toordinal() - 1)): mk(tp)}
    st = day_frame("X", day0, frames)
    assert st is not None and delta_f(st, day0, -1, 0.01) is not None
    assert delta_f(frames[("X", dd)], day0, -1, 0.01) is None   # without the stitch the minute ending at T is missing
    # verdict mapping
    assert exit_verdict(True, 2500, 40, 0.01, 0.001)[0] == "pass"
    assert exit_verdict(True, 2500, 40, 0.01, -0.001)[0] == "fail"
    assert exit_verdict(True, 900, 40, 0.01, 0.001)[0] == "indeterminate"
    assert exit_verdict(False, 2500, 40, 0.01, 0.001)[0] == "indeterminate"
    mr = matched_random_side(pd.DataFrame({"side": ["long", "short"] * 50, "delta_r": [0.01] * 100, "delta_r_opp": [0.01] * 100}))
    assert mr["draws"] == 200 and abs(mr["mean_of_means"] - 0.01) < 1e-12, mr
    m, lo, hi = block_ci(np.array([1.0, 1.0, 1.0, 1.0]), np.array(["a", "a", "b", "b"]), 2.5)
    assert m == lo == hi == 1.0
    # a flat symbol-day has no inferable tick: run_exit treats it as unmeasured (tick_of raises ValueError, caught there)
    flat = pd.DataFrame({"t": t, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})
    try:
        tick_of(flat)
        raise AssertionError("tick_of must refuse a flat day")
    except ValueError:
        pass
    # EXIT-GATE (RQ-20261119-b9d0-03): features read nothing after T; the decision rule; the verdict mapping
    dz = pd.DataFrame({"t": t, "open": base, "high": base + 0.01, "low": base - 0.01, "close": base})
    f0 = pre_features(dz, int(T0), -1, tick)
    dz2 = dz.copy()
    dz2.loc[dz2.t >= T0, ["open", "high", "low", "close"]] = 150.0    # change only bars that START at/after T
    assert pre_features(dz2, int(T0), -1, tick) == f0, "pre_features must not read bars after T"
    assert set(GATE_FEATURES) == set(f0) and f0["dir"] == -1.0 and abs(f0["tick_bps"] - 1.0) < 1e-9, f0
    dz3 = dz.copy()
    dz3.loc[dz3.t == T0 - 360, "close"] = 99.0                        # the close 5 minutes before the minute ending at T
    assert abs(pre_features(dz3, int(T0), 1, tick)["ret5"] - (100.0 - 99.0) / 100.0 * 1e4) < 1e-6
    assert pre_features(dz3, int(T0), -1, tick)["ret5"] < 0           # signed by the closing direction
    g = gate_decide(np.array([0.9, 0.1, 0.5]), np.array([4.0, 4.0, 4.0]), -12.0)
    assert g.tolist() == [True, False, False], g                      # 0.9*4-0.1*12>0; 0.1*4-0.9*12<0; 0.5*4-0.5*12<0
    assert auc_score(np.array([0.1, 0.2, 0.8, 0.9]), np.array([0, 0, 1, 1])) == 1.0
    assert gate_verdict(True, 5000, 3000, 40, 0.1, 0.001, 0.0002, 0.006, 0.01)[0] == "pass"
    assert gate_verdict(True, 5000, 3000, 40, 0.1, 0.001, 0.0002, 0.006, 0.20)[0] == "fail"     # random skips do as well
    assert gate_verdict(True, 5000, 3000, 40, 0.1, 0.001, 0.0002, 0.006, None)[0] == "fail"     # no control, no pass
    assert gate_verdict(True, 5000, 3000, 40, 0.1, 0.001, -0.0002, 0.006, 0.01)[0] == "fail"
    assert gate_verdict(True, 5000, 3000, 40, 0.1, 0.001, 0.0002, -0.001, 0.01)[0] == "fail"
    # matched random: skipping exactly the losing exits beats random skips of the same count; skipping winners does not
    dr = np.array([0.01] * 90 + [-0.05] * 10)
    good = -dr[90:].sum() / 100
    assert matched_random_skip(dr, 10, good, draws=300)["p_value"] < 0.01
    bad = -dr[:10].sum() / 100
    assert matched_random_skip(dr, 10, bad, draws=300)["p_value"] > 0.5
    assert gate_verdict(True, 5000, 3000, 40, 0.005, 0.001, 0.0002, 0.006)[0] == "indeterminate"
    assert gate_verdict(True, 900, 3000, 40, 0.1, 0.001, 0.0002, 0.006)[0] == "indeterminate"
    assert gate_verdict(False, 5000, 3000, 40, 0.1, 0.001, 0.0002, 0.006)[0] == "indeterminate"
    print("ml_entry_maker_replay self-test OK")


def main(argv=None) -> int:
    import holdout_lock as HL
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "calibrate", "exit", "exit-gate"])
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--out", default="/tmp/maker_replay")
    ap.add_argument("--cache", default="/tmp/maker_1m")
    ap.add_argument("--kcache", default="/tmp/ml_decision_klines")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default=str(HL.LEDGER))
    ap.add_argument("--entry-w-min", type=int, default=None,
                    help="run mode: market-fallback window W for the ENTRY maker order (default W_MIN, reproducing 1c4e-01)")
    ap.add_argument("--entry-peg", choices=["touch", "mid"], default="touch",
                    help="run mode: where the entry maker order rests (touch = policy F, 1c4e-01's default; mid = RQ-20261118-e8a1-02)")
    ap.add_argument("--exit-rule", default=EXIT_RULE_ID, help="exit mode: the registered rule id the result names")
    ap.add_argument("--exit-w-min", type=int, default=W_MIN,
                    help="exit mode: market-fallback window W in minutes for the closing order (calibration stays at W_MIN)")
    ap.add_argument("--exit-peg", choices=["touch", "mid"], default="touch",
                    help="exit mode: where the closing maker order rests (touch = policy F, the default; mid = the D9 mid-peg arm)")
    ap.add_argument("--population", choices=sorted(POPULATIONS), default="heldout",
                    help="exit mode: heldout = v1's frozen booster on the held-out year (default); dev_oof = v1's recipe out of "
                         "fold on the dev walk-forward (the fresh-window confirmation, RQ-20261118-e8a1-01)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "calibrate":
        print(json.dumps(calibrate(a), indent=1))
        return 0
    if a.cmd == "exit-gate":
        if a.unit != GATE_UNIT:
            raise SystemExit(f"exit-gate answers {GATE_UNIT} only, got {a.unit}")
        return run_exit_gate(a)
    if a.cmd == "exit":
        if a.unit == UNIT:
            a.unit = EXIT_UNIT
        return run_exit(a)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
