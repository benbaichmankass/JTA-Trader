#!/usr/bin/env python3
"""Weekly CANDIDATE retrain of the live ENTRY model (row ML-ENTRY-RETRAIN-CADENCE; Tier 2, held PR).

Refits the REGISTERED c692-01 recipe (``ml_decision_entry``: same 20 features, LGB_PARAMS, 2/3 ATR / 24h bracket, pooled
over the frozen 60-perp universe, tau carried from the served artifact) on ALL data through the previous UTC day, minus
the registered embargo (``purge_train``: 7 days + the 25h label horizon). It publishes a CANDIDATE artifact with the
feature list, sha and data-through date, plus ``freshness.json``.

IT NEVER SWAPS THE SERVED MODEL. ``ml/served/ml_decision_entry_v1`` is untouched: serving a new artifact on real money is
the operator's call under the promotion ladder. NO HALTING (Prime Directive rule 7): a failed retrain writes
``retrain_status.json`` (status failed + why), exits non-zero so the Actions run is the ONE red flag, and leaves the
previous artifact serving. The candidate carries no edge claim: it has had no held-out read.

  python3 scripts/research/ml_entry_retrain.py run --out DIR [--run-date YYYY-MM-DD] [--cache DIR]
  python3 scripts/research/ml_entry_retrain.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_decision_entry as E  # noqa: E402

SERVED = REPO / "ml/served/ml_decision_entry_v1/model.json"
DAILY = "https://data.binance.vision/data/futures/um/daily/klines"


def plan(run_date: date) -> dict:
    """Pure date arithmetic. ``data_through`` = previous UTC day; the fit sees only rows before ``run_date`` minus the
    registered purge (E.purge_train), i.e. ``train_end_bound``."""
    import pandas as pd
    start = pd.Timestamp(run_date.isoformat(), tz="UTC")
    bound = start - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=E.HORIZON_H + 1)
    return {"run_date": run_date.isoformat(), "data_through": (run_date - timedelta(days=1)).isoformat(),
            "train_end_bound": str(bound),
            "last_complete_month": (run_date.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
            "daily_days": [(run_date.replace(day=1) + timedelta(days=i)).isoformat()
                           for i in range((run_date - run_date.replace(day=1)).days)]}


def _fetch_zip(url: str):
    import pandas as pd
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
            df = pd.read_csv(io.StringIO(raw), header=0 if first.startswith("open_time") else None).iloc[:, :6]
            df.columns = ["open_time", "open", "high", "low", "close", "volume"]
            return df
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch_through(cache: Path, symbols: list[str], p: dict) -> dict:
    """Monthly archives through the last complete month, then DAILY archives for the current month's days up to
    ``data_through``. Writes the same ``<SYM>.pkl`` schema ``ml_decision_entry.build_table`` reads. A missing daily file
    (Binance publishes with a lag) is recorded, never faked; the realised data-through is reported from the data."""
    import concurrent.futures as cf
    import pandas as pd
    cache.mkdir(parents=True, exist_ok=True)

    def one(sym: str):
        frames, missing = [], []
        for m in E._months(E.START, p["last_complete_month"] + "-01"):
            d = _fetch_zip(f"{E._BASE}/{sym}/1h/{sym}-1h-{m}.zip")
            (missing.append(m) if d is None else frames.append(d))
        for day in p["daily_days"]:
            d = _fetch_zip(f"{DAILY}/{sym}/1h/{sym}-1h-{day}.zip")
            (missing.append(day) if d is None else frames.append(d))
        df = pd.concat(frames, ignore_index=True)
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df = df.dropna().drop_duplicates("open_time").sort_values("open_time")
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        df["ts"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        df = df[(df.ts >= pd.Timestamp(E.START, tz="UTC"))][["ts", "open", "high", "low", "close", "volume"]]
        df.reset_index(drop=True).to_pickle(cache / f"{sym}.pkl")
        return sym, {"rows": len(df), "last_bar": str(df.ts.max()), "missing": missing}

    with cf.ThreadPoolExecutor(8) as ex:
        return dict(ex.map(one, symbols))


def recipe_sha() -> str:
    blob = json.dumps({"features": E.FEATURES, "lgb": E.LGB_PARAMS, "sl": E.SL_ATR, "tp": E.TP_ATR, "atr": E.ATR_N,
                       "horizon": E.HORIZON_H, "every": E.DECISION_EVERY_H, "embargo": E.EMBARGO_DAYS}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def build_candidate(tab, p: dict, symbols: list[str], served: dict | None, out: Path) -> dict:
    import pandas as pd
    start = pd.Timestamp(p["run_date"], tz="UTC")
    train = E.purge_train(tab[tab.ts < start], start)
    if len(train) < 100_000:
        raise RuntimeError(f"degenerate training table: {len(train)} rows")
    models = E.fit_models(train)
    booster = {s: m.booster_.model_to_string() for s, m in models.items()}
    served_tau = (served or {}).get("tau")
    if served_tau is None:
        raise RuntimeError("served artifact carries no tau: refusing to invent one")
    cid = f"ml-decision-entry-v1-cand-{p['run_date']}"
    art = {"model_id": cid, "schema": "ml_decision_entry_model/1", "candidate": True, "served_artifact": "ml-decision-entry-v1",
           "features": E.FEATURES, "tau": served_tau, "tau_source": "carried from the served artifact (not re-chosen)",
           "train_rows": len(train), "train_end_exclusive": str(train.ts.max()), "data_through": p["data_through"],
           "lgb_params": E.LGB_PARAMS, "bracket": {"sl_atr": E.SL_ATR, "tp_atr": E.TP_ATR, "atr_n": E.ATR_N,
           "horizon_h": E.HORIZON_H, "decision_every_h": E.DECISION_EVERY_H}, "xs_reference": symbols,
           "recipe_sha": recipe_sha(), "git_sha": E._git_sha(), "booster_txt": booster,
           "provenance": "RUNNER-BUILT weekly candidate by scripts/research/ml_entry_retrain.py; NO held-out read, no edge claim"}
    body = json.dumps(art, indent=1, default=str)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidate_model.json").write_text(body + "\n")
    sha = hashlib.sha256(body.encode()).hexdigest()
    served_end = (served or {}).get("train_end_exclusive")
    fr = {"read_state": "measured", "candidate_id": cid, "candidate_sha256": sha, "recipe_sha": art["recipe_sha"],
          "features": E.FEATURES, "n_features": len(E.FEATURES), "data_through": p["data_through"],
          "candidate_train_end_exclusive": art["train_end_exclusive"], "train_rows": len(train),
          "served_train_end_exclusive": served_end,
          "candidate_gain_days": (round((train.ts.max() - pd.Timestamp(served_end)).total_seconds() / 86400, 1)
                                  if served_end else None),
          "freshness_line": (f"candidate {cid}: data through {p['data_through']}, train_end {art['train_end_exclusive']}, "
                             f"sha256 {sha[:12]}, {len(E.FEATURES)} features; served artifact train_end {served_end}")}
    (out / "freshness.json").write_text(json.dumps(fr, indent=1, default=str) + "\n")
    return fr


def run(a) -> int:
    out, cache = Path(a.out), Path(a.cache)
    out.mkdir(parents=True, exist_ok=True)
    run_date = date.fromisoformat(a.run_date) if a.run_date else datetime.now(timezone.utc).date()
    p = plan(run_date)
    try:
        syms = E.universe()
        rep = fetch_through(cache, syms, p)
        last = max(v["last_bar"] for v in rep.values())
        tab = E.build_table(cache, syms)
        served = json.loads(SERVED.read_text())
        served = {k: v for k, v in served.items() if k != "booster_txt"}
        fr = build_candidate(tab, p, syms, served, out)
        fr["fetch"] = {"symbols": len(rep), "latest_bar_fetched": last,
                       "symbols_with_missing_files": {k: v["missing"][:5] for k, v in rep.items() if v["missing"]}}
        (out / "freshness.json").write_text(json.dumps(fr, indent=1, default=str) + "\n")
        (out / "retrain_status.json").write_text(json.dumps({"status": "ok", "plan": p}, indent=1) + "\n")
        print(fr["freshness_line"], flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent, writes retrain_status.json (failed + why) and exits 1, so the run is the red flag
        # No halting: nothing serving is touched. The non-zero exit makes this run the ONE red flag.
        (out / "retrain_status.json").write_text(json.dumps(
            {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:500], "plan": p,
             "previous_artifact_kept": "ml/served/ml_decision_entry_v1 (untouched)"}, indent=1) + "\n")
        print(f"RETRAIN FAILED (previous artifact kept): {exc}", file=sys.stderr, flush=True)
        return 1


def _self_test() -> None:
    p = plan(date(2026, 11, 8))
    assert p["data_through"] == "2026-11-07" and p["last_complete_month"] == "2026-10"
    assert p["daily_days"] == [f"2026-11-0{i}" for i in range(1, 8)]          # Nov 1..7: through the previous day
    assert p["train_end_bound"].startswith("2026-10-30 23:00:00")           # 11-08 00:00 - 7d (11-01 00:00) - 25h
    assert plan(date(2026, 11, 1))["daily_days"] == [] and plan(date(2026, 11, 1))["last_complete_month"] == "2026-10"
    assert plan(date(2027, 1, 3))["last_complete_month"] == "2026-12"
    assert len(recipe_sha()) == 16
    served = json.loads(SERVED.read_text())
    assert served["tau"] == 0.1 and served["features"] == E.FEATURES, "recipe drifted from the served artifact"
    print("ml_entry_retrain self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--out", default="/tmp/ml_entry_retrain_out")
    ap.add_argument("--cache", default="/tmp/ml_entry_retrain_klines")
    ap.add_argument("--run-date", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
