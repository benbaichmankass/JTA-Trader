#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-c692-07.yaml (serve-parity preflight of ML-ENTRY-LIVE-ADAPTER); manual fallback via the trainer-vm-diag relay
"""Serve parity for the ml_entry adapter: do LIVE Bybit 1h bars give the same features and decisions as the Binance
Vision bars the model was trained on, on the same decision bars? (Tier-1, read-only, keyless public endpoints.)

For each traded symbol (bybit_2 data-pull list, re-read from config/accounts.yaml) and every decision bar (close hour
% 4 == 0) in the last ``--days`` days: build the served feature row twice through ``src.runtime.ml_decision_features``
(the code the adapter runs) -- once from Bybit V5 public klines (own symbol + the model's 60 reference symbols), once
from Binance Vision daily klines -- and score both with the served artifact. Reports, per symbol: n bars compared,
per-feature max |diff| and median |diff|, decision agreement (long / short / none) and the |pred diff| distribution.

Verdict (registered in the unit before the run): PASS iff decision agreement >= 0.95 over all compared bars AND
n compared >= 50; FAIL otherwise; producer_failed (loud) when either venue cannot be read. A FAIL is a MECHANICAL
fault to fix in the adapter (manager 2026-11-01), not a reason to stop.

    python3 scripts/research/ml_entry_serve_parity.py --days 30 --out /tmp/parity
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

from src.runtime import ml_decision_features as F  # noqa: E402
from src.units.strategies import ml_entry as M  # noqa: E402

BYBIT = "https://api.bybit.com/v5/market/kline"
BINANCE_DAILY = "https://data.binance.vision/data/futures/um/daily/klines"
AGREE_BAR, N_FLOOR = 0.95, 50


def _get(url, params=None):
    import requests
    last = None
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001  # allow-silent: retried with backoff; the final failure is raised below
            last = e
    raise RuntimeError(f"GET failed {url}: {last}")


def bybit_1h(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame | None:
    rows, cur = [], end_ms
    while cur > start_ms:
        r = _get(BYBIT, {"category": "linear", "symbol": symbol, "interval": "60", "end": cur, "limit": 1000})
        lst = (r.json().get("result") or {}).get("list") or [] if r is not None else []
        if not lst:
            break
        rows += lst
        cur = int(lst[-1][0]) - 1
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "turnover"]).drop(columns="turnover")
    df = df.astype(float).drop_duplicates("t").sort_values("t")
    df["ts"] = pd.to_datetime(df.pop("t").astype("int64"), unit="ms", utc=True)
    # Compare as timestamps, never via int64: pandas 3 keeps unit="ms" datetimes at ms resolution, so the old
    # `ts.astype("int64") // 10**6 >= start_ms` (which assumed ns) dropped EVERY row -> n=0 (trainer run, issue #22152).
    keep = df.ts >= pd.Timestamp(int(start_ms), unit="ms", tz="UTC")
    return df[keep][["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def binance_1h(symbol: str, days: list[str]) -> pd.DataFrame | None:
    frames = []
    for d in days:
        r = _get(f"{BINANCE_DAILY}/{symbol}/1h/{symbol}-1h-{d}.zip")
        if r is None:
            continue
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        raw = zf.read(zf.namelist()[0]).decode()
        x = pd.read_csv(io.StringIO(raw), header=0 if raw.startswith("open_time") else None).iloc[:, :6]
        x.columns = ["t", "open", "high", "low", "close", "volume"]
        frames.append(x)
    if not frames:
        return None
    df = pd.concat(frames).astype(float).drop_duplicates("t").sort_values("t")
    df["ts"] = pd.to_datetime(df.pop("t").astype("int64"), unit="ms", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def compare(traded, src_a: dict, src_b: dict, model, every_h: int, since: pd.Timestamp) -> dict:
    out = {}
    for sym in traded:
        a_own, b_own = src_a.get(sym), src_b.get(sym)
        if a_own is None or b_own is None:
            out[sym] = {"n": 0, "read_state": "no_data"}
            continue
        common = sorted(set(a_own.ts) & set(b_own.ts))
        bars = [t for t in common if t >= since and M.is_decision_bar(t, every_h)]
        diffs, agree, pdiff, n = {k: [] for k in F.FEATURES}, 0, [], 0
        for t in bars:
            rows = []
            for srcs in (src_a, src_b):
                frames = {s: f[f.ts <= t].iloc[-400:].reset_index(drop=True) for s, f in srcs.items()
                          if f is not None and (f.ts == t).any()}
                rows.append(F.decision_row(sym, frames))
            if rows[0] is None or rows[1] is None:
                continue
            for r in rows:
                r.pop("_n_reference", None)
            da, db = M.decide(rows[0], model), M.decide(rows[1], model)
            n += 1
            agree += da["side"] == db["side"]
            pdiff.append(abs(da["pred_net_r"] - db["pred_net_r"]))
            for k in F.FEATURES:
                diffs[k].append(abs(rows[0][k] - rows[1][k]))
        out[sym] = {"n": n, "decision_agreement": agree / n if n else None,
                    "pred_absdiff_median": float(np.median(pdiff)) if pdiff else None,
                    "pred_absdiff_max": float(np.max(pdiff)) if pdiff else None,
                    "feature_absdiff_max": {k: float(np.max(v)) for k, v in diffs.items() if v},
                    "feature_absdiff_median": {k: float(np.median(v)) for k, v in diffs.items() if v}}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", choices=["v1", "v2"], default="v1",
                    help="v2: the ml_entry_v2 artifact (R2 recipe, cost gate, TP 4); decisions go through the same shared decide()")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import ml_decision_entry as E
    traded = E.traded_symbols()
    if a.model == "v2":
        from src.units.strategies import ml_entry_v2 as M2  # noqa: E402
        model = M2.load_model()
    else:
        model = M.load_model()
    meta = model["meta"]
    ref = list(meta["xs_reference"])
    end = pd.Timestamp.now(tz="UTC").floor("D")
    start = end - pd.Timedelta(days=a.days + 20)  # 20 extra days of warm-up for the 168-bar windows
    since = end - pd.Timedelta(days=a.days)
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end - pd.Timedelta(days=1), freq="D")]
    syms = sorted(set(ref) | set(traded))
    try:
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(12) as ex:
            bybit = dict(zip(syms, ex.map(lambda s: bybit_1h(s, int(start.value // 10**6), int(end.value // 10**6)), syms)))
            binance = dict(zip(syms, ex.map(lambda s: binance_1h(s, days), syms)))
    except RuntimeError as e:
        vj = {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
              "population": "ml_entry serve parity: a venue could not be read -- NEVER MEASURED",
              "note": f"producer_failed: {e}. Re-run from a host that reaches api.bybit.com (the trainer-vm-diag relay)."}
        (out / "verdict.json").write_text(json.dumps(vj, indent=1) + "\n")
        print(json.dumps(vj))
        return 0
    res = compare(traded, bybit, binance, model, int(meta["bracket"]["decision_every_h"]), since)
    n = sum(r["n"] for r in res.values())
    agree = sum((r["decision_agreement"] or 0) * r["n"] for r in res.values()) / n if n else None
    missing = {"bybit": [s for s in syms if bybit.get(s) is None], "binance": [s for s in syms if binance.get(s) is None]}
    if n < N_FLOOR:
        v, why = "indeterminate", f"compared decision bars n={n} < {N_FLOOR}"
    elif agree >= AGREE_BAR:
        v, why = "pass", f"decision agreement {agree:.3f} >= {AGREE_BAR} over n={n} bars"
    else:
        v, why = "fail", f"decision agreement {agree:.3f} < {AGREE_BAR} over n={n} bars -- a mechanical fault to fix"
    meas = {"per_symbol": res, "agreement": agree, "n": n, "missing_reference": missing, "window": [str(since), str(end)],
            "model_id": meta.get("model_id")}
    (out / "summary.json").write_text(json.dumps(meas, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": n, "measurement": meas, "note": why,
          "population": f"ml_entry decision bars {since.date()}..{end.date()} on {traded}: Bybit V5 vs Binance Vision 1h"}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
