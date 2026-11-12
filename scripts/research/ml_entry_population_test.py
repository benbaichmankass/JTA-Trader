#!/usr/bin/env python3
"""RQ-20261112-2e3b-01 -- the POPULATION test for ml_entry (row ML-ENTRY-POPULATION-TEST, Tier 1 research).

Operator rule 2026-11-04 (docs/CLAUDE-RULES-CANONICAL.md § "An account configures strategies, never symbols"): an ML trades the whole
population its registered POOLED test passed on, net of each symbol's own costs, minus a filter fixed BEFORE the run, limited to what the
venue can trade. Per-symbol results are reported, never gating. Gates this adds or changes: none (a measurement).

Two subcommands, run in this order:

  freeze   (no outcome is read) Bybit snapshot CSV -> the filtered population list, written BEFORE the unit is registered:
           F1 status Trading, LinearPerpetual, quote USDT; F2 Bybit launchTime <= 2025-06-30; F3 snapshot turnover24h >= 5,000,000 USD;
           F4 snapshot quoted spread (ask-bid)/mid <= 10 bps; F5 Binance Vision USDT-M 1h monthly klines exist under the same name for
           every month 2025-08..2026-10 (the harness's data source; a symbol it cannot score is outside what the model can be tested on).
  run      the frozen ml_decision_entry_v1 artifact (tau and features from model.json, unchanged) scored on every decision
           2025-10-01..2026-10-31 of the frozen population, each decision re-costed with ITS symbol's own cost stack, the read claimed
           in the holdout ledger first; verdict by RULE-RQ20261112-2e3b-01-ENTRY-POPULATION.

Cost stack per symbol (and month), round trip, bps of notional, in R through the label's price-per-R:
  fee 11.0 (bybit:linear taker, execution_costs.resolve_fee_bps_roundtrip('BTCUSDT'); charged to every symbol, never the 7.5 default)
  + max(3.0, spread + impact)  where 3.0 = execution_costs.PERP_SLIPPAGE_BPS_ROUNDTRIP (the measured bybit_2 floor),
        spread = the symbol's snapshot quoted spread floored at one tick at the month's median price,
        impact = 2 x 1e4 x sigma_daily x sqrt(Q / ADV_bybit), Q = 5,000 USD, ADV_bybit = Binance median daily quote volume of the month
                 x the symbol's Bybit/Binance turnover ratio (snapshot turnover24h / Binance median daily quote volume of 2026-10)
  + funding x 8h windows crossed, funding = max(1.0, 1e4 x mean |funding rate| x 8 / interval_h) of the symbol-month
        (Binance Vision fundingRate; directionless drag as execution_costs; a missing month charges 1.0 and is counted).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))
import ml_decision_entry as mde  # noqa: E402

UNIT = "RQ-20261112-2e3b-01"
RULE_ID = "RULE-RQ20261112-2e3b-01-ENTRY-POPULATION"
MODEL_ID = "ENTRY-v1-population-2e3b"
SNAPSHOT = REPO / "comms/research/RQ-20261112-2e3b-01/freeze/bybit_linear_usdt_snapshot.csv"
POPULATION = REPO / "comms/research/RQ-20261112-2e3b-01/freeze/population.json"
SERVED = REPO / "ml/served/ml_decision_entry_v1/model.json"

# ---- registered constants (RQ-20261112-2e3b-01 decision_rule); none is a tuning knob ----
LAUNCH_MAX = "2025-06-30"
TURNOVER_MIN_USD = 5_000_000.0
SPREAD_MAX_BPS = 10.0
DATA_MONTHS = ("2025-08", "2026-10")
WIN_START, WIN_END = "2025-10-01", "2026-10-31"
TRAIN_END = "2025-09-22"              # model.json train_end_exclusive 2025-09-22 19:00Z
FEE_BPS = 11.0
SLIP_FLOOR_BPS = 3.0
FUND_FLOOR_BPS = 1.0
Q_USD = 5000.0
RATIO_MONTH = "2026-10"
N_MIN = 300
SYMBOLS_MIN = 10
POP_MIN = 10
XS_REF_MIN = 40                       # strategies.yaml ml_entry.min_reference_symbols
MAX_MISSING_COST = 0.10

_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
_KL = "https://data.binance.vision/data/futures/um/monthly/klines"
_FR = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


def months(a: str, b: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(a, b, freq="M")]


# ----------------------------------------------------------------------------------------------- freeze (no outcomes)
def read_snapshot(path: Path) -> tuple[dict, pd.DataFrame]:
    lines = path.read_text().splitlines()
    head = next(x for x in lines if x.startswith("SNAPSHOT_UTC"))
    hdr = lines.index("symbol,status,tick,launch_ms,fund_min,turnover24h,bid1,ask1,last")
    body = [x for x in lines[hdr + 1:] if x and not x.startswith("ROWS")]
    df = pd.read_csv(io.StringIO("\n".join(lines[hdr:hdr + 1] + body)))
    for c in ("tick", "launch_ms", "turnover24h", "bid1", "ask1", "last"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    mid = (df.bid1 + df.ask1) / 2
    df["spread_bps"] = np.where((mid > 0) & (df.ask1 >= df.bid1), 1e4 * (df.ask1 - df.bid1) / mid, np.nan)
    return {"snapshot_line": head}, df


def binance_months(sym: str) -> set[str]:
    import requests
    r = requests.get(_S3, params={"delimiter": "/", "prefix": f"data/futures/um/monthly/klines/{sym}/1h/"}, timeout=60)
    r.raise_for_status()
    return set(re.findall(rf"{re.escape(sym)}-1h-(\d{{4}}-\d{{2}})\.zip<", r.text))


def apply_filter(df: pd.DataFrame, have_months) -> tuple[list[str], dict]:
    """F1..F5 in order; every dropped symbol is counted under the FIRST filter it fails."""
    launch_max_ms = pd.Timestamp(LAUNCH_MAX + " 23:59:59", tz="UTC").value // 10**6
    need = set(months(*DATA_MONTHS))
    dropped, keep = {}, []
    for r in df.itertuples(index=False):
        if r.status != "Trading":
            why = "F1 not Trading"
        elif not (r.launch_ms <= launch_max_ms):
            why = f"F2 launched after {LAUNCH_MAX}"
        elif not (r.turnover24h >= TURNOVER_MIN_USD):
            why = f"F3 turnover24h < {TURNOVER_MIN_USD:.0f}"
        elif not (r.spread_bps <= SPREAD_MAX_BPS):
            why = f"F4 quoted spread > {SPREAD_MAX_BPS} bps (or no quote)"
        elif not need <= have_months(r.symbol):
            why = "F5 Binance Vision 1h klines missing for a month of " + "..".join(DATA_MONTHS)
        else:
            keep.append(r.symbol)
            continue
        dropped[r.symbol] = why
    return sorted(keep), dropped


def freeze(args) -> int:
    meta, df = read_snapshot(Path(args.snapshot))
    cands = df[df.status.notna()]
    with cf.ThreadPoolExecutor(16) as ex:
        bm = dict(zip(cands.symbol, ex.map(lambda s: binance_months(s), cands.symbol)))
    keep, dropped = apply_filter(cands, lambda s: bm.get(s, set()))
    counts = pd.Series(dropped).str.split(" ").str[0].value_counts().to_dict() if dropped else {}
    spec = {r.symbol: {"tick": float(r.tick), "spread_bps": float(r.spread_bps), "turnover24h": float(r.turnover24h),
                       "launch_ms": int(r.launch_ms)} for r in df[df.symbol.isin(keep)].itertuples(index=False)}
    doc = {"schema": "ml_entry_population_freeze/1", "unit": UNIT, **meta, "snapshot_file": str(Path(args.snapshot)),
           "filter": {"F1": "status Trading, LinearPerpetual, quote USDT", "F2": f"launchTime <= {LAUNCH_MAX}",
                      "F3": f"turnover24h >= {TURNOVER_MIN_USD:.0f} USD", "F4": f"quoted spread <= {SPREAD_MAX_BPS} bps",
                      "F5": f"Binance Vision 1h monthly klines for every month {DATA_MONTHS[0]}..{DATA_MONTHS[1]}"},
           "n_snapshot_rows": int(len(df)), "n_population": len(keep), "dropped_counts": counts, "dropped": dropped,
           "population": keep, "spec": spec,
           "reference_symbols_in_population": sorted(set(keep) & set(_xs_ref())),
           "note": "Frozen BEFORE any outcome in the window was read; no label, prediction or P&L is computed by this step."}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps({k: doc[k] for k in ("n_snapshot_rows", "n_population", "dropped_counts")}))
    return 0


def _xs_ref() -> list[str]:
    ref = json.loads(SERVED.read_text())["xs_reference"]
    return ref if isinstance(ref, list) else json.loads(ref.replace("'", '"'))


# ----------------------------------------------------------------------------------------------- data
def _zip_csv(url: str) -> pd.DataFrame | None:
    import requests
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
            return pd.read_csv(io.StringIO(raw), header=0 if not first[:1].isdigit() else None)
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch_klines(cache: Path, sym: str) -> bool:
    p = cache / f"{sym}.pkl"
    if p.exists():
        return True
    frames = []
    for m in months(*DATA_MONTHS):
        d = _zip_csv(f"{_KL}/{sym}/1h/{sym}-1h-{m}.zip")
        if d is not None:
            d = d.iloc[:, :6]
            d.columns = ["open_time", "open", "high", "low", "close", "volume"]
            frames.append(d)
    if not frames:
        return False
    df = pd.concat(frames, ignore_index=True)
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_pickle(p)
    return True


def fetch_funding(sym: str) -> dict[str, float]:
    """month -> per-8h-equivalent mean |funding| in bps (before the floor); a month with no file is absent."""
    out = {}
    for m in months(WIN_START[:7], WIN_END[:7]):
        d = _zip_csv(f"{_FR}/{sym}/{sym}-fundingRate-{m}.zip")
        if d is None or d.empty:
            continue
        d = d.iloc[:, :3]
        d.columns = ["calc_time", "interval_h", "rate"]
        iv = pd.to_numeric(d.interval_h, errors="coerce").median()
        rate = pd.to_numeric(d.rate, errors="coerce").abs().mean()
        if np.isfinite(iv) and iv > 0 and np.isfinite(rate):
            out[m] = float(1e4 * rate * 8.0 / iv)
    return out


# ----------------------------------------------------------------------------------------------- costs
def symbol_costs(df: pd.DataFrame, spec: dict, fund: dict[str, float]) -> pd.DataFrame:
    """Per symbol-month: var_bps = max(SLIP_FLOOR, spread + impact) and fund_bps (per 8h window)."""
    d = df.assign(month=df.ts.dt.strftime("%Y-%m"), day=df.ts.dt.floor("D"), qv=df.volume * df.close)
    daily = d.groupby("day").agg(close=("close", "last"), qv=("qv", "sum"), month=("month", "first"))
    daily["lr"] = np.log(daily.close).diff()
    ref = daily[daily.month == RATIO_MONTH].qv.median()
    ratio = spec["turnover24h"] / ref if ref and ref > 0 else np.nan
    out = []
    for m, g in d.groupby("month"):
        dg = daily[daily.month == m]
        px = float(g.close.median())
        spread = max(spec["spread_bps"], 1e4 * spec["tick"] / px) if px > 0 else np.nan
        sig, adv = float(dg.lr.std()), float(dg.qv.median()) * ratio
        imp = 2.0 * 1e4 * sig * np.sqrt(Q_USD / adv) if adv > 0 and np.isfinite(sig) else np.nan
        f = fund.get(m)
        out.append({"month": m, "spread_bps": spread, "impact_bps": imp, "var_bps": max(SLIP_FLOOR_BPS, spread + imp),
                    "fund_bps": max(FUND_FLOOR_BPS, f) if f is not None else FUND_FLOOR_BPS, "fund_defaulted": f is None,
                    "bybit_binance_ratio": ratio})
    return pd.DataFrame(out)


def recost(tab: pd.DataFrame, costs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    t = tab.assign(month=tab.ts.dt.strftime("%Y-%m"))
    c = pd.concat([v.assign(symbol=k) for k, v in costs.items()], ignore_index=True)
    t = t.merge(c[["symbol", "month", "var_bps", "fund_bps", "fund_defaulted"]], on=["symbol", "month"], how="left")
    t["cost_ok"] = t.var_bps.notna()
    for side in ("long", "short"):
        bps = FEE_BPS + t.var_bps + t.fund_bps * t[f"nwin_{side}"]
        t[f"cost_{side}"] = t[f"per_r_{side}"] * bps / 1e4
        t[f"net_{side}"] = t[f"gross_{side}"] - t[f"cost_{side}"]
    return t


def verdict(m: dict, n_pop: int, n_ref: int, missing: float, bar: dict) -> tuple[str, str]:
    import holdout_lock as HL
    if n_pop < POP_MIN or n_ref < XS_REF_MIN:
        return "indeterminate", f"population {n_pop} (floor {POP_MIN}) / reference symbols {n_ref} (floor {XS_REF_MIN})"
    if missing > MAX_MISSING_COST:
        return "indeterminate", f"cost model missing for {missing:.1%} of decision rows (> {MAX_MISSING_COST:.0%})"
    if m["n"] < N_MIN or m.get("n_symbols", 0) < SYMBOLS_MIN:
        return "indeterminate", f"n={m['n']} (floor {N_MIN}) / symbols traded {m.get('n_symbols', 0)} (floor {SYMBOLS_MIN})"
    ok = HL.point_ok(m["mean_net_r"], m.get("se_net_r"), bar)
    why = (f"pooled mean net R {m['mean_net_r']:+.4f} (se {m.get('se_net_r') or float('nan'):.4f}) at n={m['n']} on {m['n_symbols']} symbols "
           f"vs the deflated hurdle mean >= {bar['point_t_min']:.2f} x se (read {bar['n_tries']} of family ENTRY on this window)")
    return ("pass" if ok else "fail"), why


# ----------------------------------------------------------------------------------------------- run
def run(args) -> int:
    import holdout_lock
    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    frz = json.loads(Path(args.population).read_text())
    pop, spec = frz["population"], frz["spec"]
    meta, models = mde._frozen_models(Path(args.served))
    tau, feats = float(meta["tau"]), meta["features"]
    ref = _xs_ref()
    syms = sorted(set(pop) | set(ref))
    with cf.ThreadPoolExecutor(8) as ex:
        have = dict(zip(syms, ex.map(lambda s: fetch_klines(cache, s), syms)))
    ref_ok = [s for s in ref if have.get(s)]
    pop_ok = [s for s in pop if have.get(s)]
    with cf.ThreadPoolExecutor(8) as ex:
        fund = dict(zip(pop_ok, ex.map(fetch_funding, pop_ok)))
    print(f"fetched: population {len(pop_ok)}/{len(pop)} reference {len(ref_ok)}/{len(ref)} t={time.time()-t0:.0f}s", flush=True)
    tab = mde.build_table(cache, sorted(set(pop_ok) | set(ref_ok)), xs_symbols=ref_ok, recost_inputs=True)
    tab = tab[tab.symbol.isin(pop_ok)]
    ws, we = pd.Timestamp(WIN_START, tz="UTC"), pd.Timestamp(WIN_END, tz="UTC") + pd.Timedelta(days=1)
    # a decision is in the window iff its 24h outcome also ends inside it
    tab = tab[(tab.ts >= ws) & (tab.ts < we - pd.Timedelta(hours=mde.HORIZON_H + 1))].reset_index(drop=True)
    costs = {s: symbol_costs(pd.read_pickle(cache / f"{s}.pkl"), spec[s], fund.get(s, {})) for s in pop_ok}
    sc = recost(tab, costs)
    missing = float((~sc.cost_ok).mean()) if len(sc) else 1.0
    sc = sc[sc.cost_ok].reset_index(drop=True)
    # the read is claimed BEFORE any outcome is summarised
    ledger = Path(args.ledger) if args.ledger else holdout_lock.LEDGER
    claim = holdout_lock.claim_read(MODEL_ID, WIN_START, WIN_END, UNIT, args.reader, ledger, symbols=pop_ok, train_end=TRAIN_END)
    # provenance: predict — Booster.predict is the regressed net R of that side, not a probability
    pl, ps = models["long"].predict(sc[feats]), models["short"].predict(sc[feats])
    tk = mde.policy(sc, pl, ps, tau)
    m = mde.summarize(tk)
    v, why = verdict(m, len(pop_ok), len(ref_ok), missing, claim["bar"])
    refset = set(ref)
    flat = sc.copy()
    for side in ("long", "short"):
        flat[f"net_{side}"] = flat[f"gross_{side}"] - flat[f"per_r_{side}"] * (FEE_BPS + 3.0 + 1.0 * flat[f"nwin_{side}"]) / 1e4
    rng = np.random.default_rng(mde.SEED)
    p_take = min(1.0, len(tk) / max(1, len(sc) / 6))
    p_long = float((tk.side == "long").mean()) if len(tk) else 0.5
    rand = [mde.sequential_baseline(sc, lambda r: None if r.random() > p_take else ("long" if r.random() < p_long else "short"), rng)
            .net_r.mean() for _ in range(50)]
    try:
        bybit2 = mde.traded_symbols()
    except Exception:  # noqa: BLE001  # allow-silent: a reported-only subset; recorded as null
        bybit2 = []
    reported = {
        "fresh_symbols_never_in_training": mde.summarize(tk[~tk.symbol.isin(refset)]),
        "reference_symbols_in_training": mde.summarize(tk[tk.symbol.isin(refset)]),
        "bybit2_pull_list": mde.summarize(tk[tk.symbol.isin(bybit2)]) if bybit2 else None,
        "flat_c692_cost_stack": mde.summarize(mde.policy(flat, pl, ps, tau)).get("mean_net_r"),
        "baselines": {"always_long": float(mde.sequential_baseline(sc, lambda r: "long").net_r.mean()),
                      "always_short": float(mde.sequential_baseline(sc, lambda r: "short").net_r.mean()),
                      "random_matched_mean_of_50": float(np.mean(rand)), "random_matched_p95": float(np.percentile(rand, 95))},
        "per_symbol_reported_never_gating": {k: {"n": len(g), "mean_net_r": round(float(g.net_r.mean()), 4)} for k, g in tk.groupby("symbol")},
        "cost_per_symbol_mean_rt_bps_ex_funding": {k: round(FEE_BPS + float(v.var_bps.mean()), 2) for k, v in costs.items()},
        "funding_months_defaulted": int(sum(int(v.fund_defaulted.sum()) for v in costs.values())),
    }
    res = {"schema": "ml_entry_population_test/1", "unit": UNIT, "rule_id": RULE_ID, "verdict": v, "why": why, "tau": tau,
           "window": [WIN_START, WIN_END], "population_frozen": len(pop), "population_scored": len(pop_ok),
           "population_unscorable": sorted(set(pop) - set(pop_ok)), "xs_reference_used": len(ref_ok),
           "cost_missing_share": missing, "pooled": m, "reported": reported, "holdout_claim": claim,
           "git_sha": mde._git_sha(), "elapsed_s": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    tk.to_csv(out / "decisions.csv.gz", index=False)
    vj = {"verdict": v, "read_state": "measured", "n": m.get("n"), "note": why,
          "population": (f"frozen ml_decision_entry_v1 (tau {tau}) decisions {WIN_START}..{WIN_END} on the {len(pop_ok)} scorable symbols of the "
                         f"{len(pop)}-symbol frozen Bybit USDT-perp population (F1-F5), each re-costed with its own fee 11 + max(3, quoted spread "
                         f"+ sqrt impact Q {Q_USD:.0f}) + its own |funding| per 8h"),
          "measurement": {"pooled": m, "holdout_claim": claim, "cost_missing_share": missing,
                          "fresh_symbols_mean_net_r": reported["fresh_symbols_never_in_training"].get("mean_net_r")}}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    # the population record (src/config/ml_universe.py, the only writer): written into the output dir, seeded from the committed record
    from src.config import ml_universe
    ml_universe.write_population("ml_entry", {"unit": UNIT, "rule_id": RULE_ID, "verdict": v,
                                              "result": f"research/results/{UNIT}/",
                                              "symbols": {s: {"venues": ["bybit"]} for s in pop_ok}},
                                 base=out / "ml_universe", seed_from=ml_universe.RECORD_DIR)
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------- self-test
def _self_test() -> None:
    snap = ("SNAPSHOT_UTC 2026-11-12T20:00:00Z instruments 5 tickers 5\n"
            "symbol,status,tick,launch_ms,fund_min,turnover24h,bid1,ask1,last\n"
            "AAAUSDT,Trading,0.01,1600000000000,480,9000000,100.00,100.01,100\n"      # keep
            "BBBUSDT,Trading,0.01,1760000000000,480,9000000,100.00,100.01,100\n"      # F2 too new
            "CCCUSDT,Trading,0.01,1600000000000,480,100000,100.00,100.01,100\n"       # F3 thin
            "DDDUSDT,Trading,0.01,1600000000000,480,9000000,100.00,100.50,100\n"      # F4 wide (50 bps)
            "EEEUSDT,Trading,0.01,1600000000000,480,9000000,100.00,100.01,100\n"      # F5 no data
            "FFFUSDT,PreLaunch,0.01,1600000000000,480,9000000,100.00,100.01,100\nROWS 6\n")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.csv"
        p.write_text(snap)
        _, df = read_snapshot(p)
    full = set(months(*DATA_MONTHS))
    keep, dropped = apply_filter(df, lambda s: set() if s == "EEEUSDT" else full)
    assert keep == ["AAAUSDT"], keep
    assert [dropped[k].split()[0] for k in ("FFFUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT")] == ["F1", "F2", "F3", "F4", "F5"], dropped
    # costs: a one-tick floor binds on a coarse tick; the 3 bps slippage floor binds on a deep book; funding floor 1.0
    ts = pd.date_range("2026-09-01", "2026-10-31 23:00", freq="h", tz="UTC")
    px = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.003, len(ts))))
    df = pd.DataFrame({"ts": ts, "open": px, "high": px * 1.001, "low": px * 0.999, "close": px, "volume": 1e7 / px})
    c = symbol_costs(df, {"tick": 0.5, "spread_bps": 0.1, "turnover24h": 2.4e8}, {"2026-10": 0.2})
    oct_ = c[c.month == "2026-10"].iloc[0]
    assert oct_.spread_bps >= 1e4 * 0.5 / float(px.max()) - 1e-9, oct_
    assert oct_.fund_bps == FUND_FLOOR_BPS and not oct_.fund_defaulted, oct_
    sep = c[c.month == "2026-09"].iloc[0]
    assert sep.fund_defaulted and sep.fund_bps == FUND_FLOOR_BPS, sep
    c2 = symbol_costs(df, {"tick": 1e-6, "spread_bps": 0.01, "turnover24h": 1e12}, {"2026-10": 5.0})
    assert abs(c2[c2.month == "2026-10"].iloc[0].var_bps - SLIP_FLOOR_BPS) < 1e-9
    assert c2[c2.month == "2026-10"].iloc[0].fund_bps == 5.0
    # verdict floors
    import holdout_lock as HL
    b1 = HL.bar_for(1)
    assert verdict({"n": 299, "n_symbols": 50, "mean_net_r": 1.0, "se_net_r": 0.1}, 100, 50, 0.0, b1)[0] == "indeterminate"
    assert verdict({"n": 999, "n_symbols": 50, "mean_net_r": 0.01, "se_net_r": 0.01}, 100, 39, 0.0, b1)[0] == "indeterminate"
    assert verdict({"n": 999, "n_symbols": 50, "mean_net_r": 0.0, "se_net_r": 0.01}, 100, 50, 0.0, b1)[0] == "pass"
    assert verdict({"n": 999, "n_symbols": 50, "mean_net_r": -0.001, "se_net_r": 0.01}, 100, 50, 0.0, b1)[0] == "fail"
    assert verdict({"n": 999, "n_symbols": 50, "mean_net_r": 0.01, "se_net_r": 0.01}, 100, 50, 0.0, HL.bar_for(20))[0] == "fail"
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "run", "self-test"])
    ap.add_argument("--snapshot", default=str(SNAPSHOT))
    ap.add_argument("--population", default=str(POPULATION))
    ap.add_argument("--served", default=str(SERVED))
    ap.add_argument("--cache", default="/tmp/ml_entry_population_klines")
    ap.add_argument("--out", default="")
    ap.add_argument("--unit", default=UNIT)
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default="")
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        _self_test()
        return 0
    if a.cmd == "freeze":
        a.out = a.out or str(POPULATION)
        return freeze(a)
    if not a.out:
        ap.error("--out is required for run")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
