#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-b610-01.yaml (frozen ENTRY v2, symbol-holdout read; amendment 2026-11-12 before any run)
"""RQ-20261101-b610-01, symbol-holdout read of the FROZEN ENTRY v2 artifact (Tier-1 research; no order, no config, no sizing).

The unit's 2026-11-05 amendment replaced the count-closed forward window with an in-hand symbol holdout S (the lexicographically first
USDT-M perps NOT in bp2-f4271084b120 with >= 3 years of 1h bars) over 2022-01..2026-10. Rule 4 of the holdout lock (PI-20261105-GEXSLEAK-0001,
adopted later the same day) refuses any holdout that starts on or before the artifact's training end, symbol holdouts included, because
correlated series leak through shared dates. The 2026-11-12 amendment (registered before any run) therefore reads S only on the dates the
artifact never saw: decisions from WINDOW_START (after the last training label, 2026-09-23 19:00Z) through WINDOW_END, on the first N_PRIMARY
symbols of S (the registered first 20 are reported beside it, non-gating). Rule RULE-20261101-b610-01 is unchanged: PASS iff (a) n >= 300
decisions on >= 10 symbols, (b) mean net R >= 0 at the lock's (deflated) point bar, (c) mean >= the frozen v1 reference on the same rows.

The window is FIXED by constants: it is never closed by a candidate count (the count-closed path of ml_entry_levers fwd-read is not used).

    python3 scripts/research/ml_entry_v2_symholdout.py run --out O [--cache C] [--reader R]
    python3 scripts/research/ml_entry_v2_symholdout.py symbols          # list S (listing spans only; reads no outcome)
    python3 scripts/research/ml_entry_v2_symholdout.py --self-test
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
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
import ml_decision_entry as E  # noqa: E402

UNIT = "RQ-20261101-b610-01"
ARTIFACT = REPO / "ml/served/ml_decision_entry_v2/model.json"
V1_DIR = REPO / "comms/research/RQ-20261101-c692-06/41324826751/model"
V1_TAU = 0.10
WINDOW_START, WINDOW_END = "2026-09-24", "2026-10-31"      # decision dates; labels run to WINDOW_END + 24h
TRAIN_END = "2026-09-23"                                   # artifact rows end 2026-09-22 19:00Z; their 24h labels end 2026-09-23 19:00Z
REGISTERED_S_START = "2022-01-01"                          # the 2026-11-05 window start, refused by rule 4 (self-test proves it)
FIRST_MONTH_MAX = "2023-10"                                # >= 3 years of 1h bars by WINDOW_END (2023-11-01..2026-10-31 = 36 months)
LAST_MONTH_MIN = "2026-10"
N_REGISTERED, N_PRIMARY = 20, 100
FETCH_START = "2026-03-01"                                 # feature warm-up (168h windows, ATR14, RSI14) well before WINDOW_START
MODEL_ID, MODEL_ID_V1 = "ENTRY-v2-frozen-symholdout", "ENTRY-v1-frozen-ref-symholdout"


# ------------------------------------------------------------------------------------------------ S (listing spans only)
def select_s(spans: dict[str, tuple[str, str]], pool: set[str], n: int) -> list[str]:
    """First ``n`` lexicographic USDT-M perps outside the pool with first month <= FIRST_MONTH_MAX and last month >= LAST_MONTH_MIN."""
    ok = [s for s, (first, last) in spans.items() if s not in pool and first <= FIRST_MONTH_MAX and last >= LAST_MONTH_MIN]
    return sorted(ok)[:n]


def list_s(n: int) -> list[str]:
    import broad_paths_corpus as bpc
    syms = [p.rstrip("/").split("/")[-1] for p in bpc._s3_list(bpc._PREFIX)]
    syms = [x for x in syms if bpc._PERP.match(x)]
    spans = {}
    with cf.ThreadPoolExecutor(16) as ex:
        for sym, sp in zip(syms, ex.map(bpc._span, syms)):
            if sp:
                spans[sym] = sp
    return select_s(spans, set(E.universe()), n)


# ------------------------------------------------------------------------------------------------ data
def _daily(sym: str, day: str) -> pd.DataFrame | None:
    import requests
    url = f"{E._DAILY}/{sym}/1h/{sym}-1h-{day}.zip"
    for wait in (0, 2, 4, 8):
        time.sleep(wait)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            raw = zipfile.ZipFile(io.BytesIO(r.content)).read(zipfile.ZipFile(io.BytesIO(r.content)).namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            d = pd.read_csv(io.StringIO(raw), header=0 if first.startswith("open_time") else None).iloc[:, :6]
            d.columns = ["open_time", "open", "high", "low", "close", "volume"]
            return d
        except Exception:  # noqa: BLE001, S112  # allow-silent: retried with backoff; the final failure raises below
            continue
    raise RuntimeError(f"fetch failed {url}")


def fetch_all(cache: Path, symbols: list[str]) -> None:
    """Monthly klines FETCH_START..WINDOW_END plus the two daily files after it (label horizon), one pickle per symbol."""
    E.START = FETCH_START
    E.fetch(cache, symbols, end=WINDOW_END)
    days = [str((pd.Timestamp(WINDOW_END) + pd.Timedelta(days=k)).date()) for k in (1, 2)]

    def one(sym):
        p = cache / f"{sym}.pkl"
        df = pd.read_pickle(p)
        if df.ts.max() >= pd.Timestamp(days[0], tz="UTC"):
            return
        extra = [d for d in (_daily(sym, x) for x in days) if d is not None]
        if not extra:
            return
        x = pd.concat(extra, ignore_index=True)
        x["open_time"] = pd.to_numeric(x["open_time"], errors="coerce")
        x = x.dropna()
        for c in ("open", "high", "low", "close", "volume"):
            x[c] = x[c].astype(float)
        x["ts"] = pd.to_datetime(x["open_time"].astype("int64"), unit="ms", utc=True)
        df = pd.concat([df, x[["ts", "open", "high", "low", "close", "volume"]]], ignore_index=True).drop_duplicates("ts").sort_values("ts")
        df.reset_index(drop=True).to_pickle(p)

    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(one, symbols))
    for sym in symbols:     # as ml_entry_levers.build_full_cache (b609): drop delisted-contract bars (volume 0 and high == low)
        p = cache / f"{sym}.pkl"
        if p.exists():
            df = pd.read_pickle(p)
            df[~((df["volume"] == 0) & (df["high"] == df["low"]))].reset_index(drop=True).to_pickle(p)


# ------------------------------------------------------------------------------------------------ run
def run(a) -> int:
    import holdout_lock as HL
    import lightgbm as lgb
    import ml_entry_levers as LV
    t0 = time.time()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache)
    art = json.loads(ARTIFACT.read_text())
    meta = {k: v for k, v in art.items() if k != "booster_txt"}
    assert pd.Timestamp(meta["train_end_exclusive"]) + pd.Timedelta(hours=E.HORIZON_H) < pd.Timestamp(WINDOW_START, tz="UTC")
    s_all = list_s(N_PRIMARY)
    s20 = s_all[:N_REGISTERED]
    pool = E.universe()
    xs_ref = list(meta.get("xs_reference") or pool)
    (out / "symbols.json").write_text(json.dumps({"S_primary": s_all, "S_registered_20": s20, "rule": {
        "first_month_max": FIRST_MONTH_MAX, "last_month_min": LAST_MONTH_MIN, "order": "lexicographic", "excludes": "bp2-f4271084b120"}}, indent=1))
    print(f"S: {len(s_all)} symbols frozen and written before any outcome is read", flush=True)
    fetch_all(cache, sorted(set(pool) | set(xs_ref) | set(s_all)))
    base = [s for s in pool if (cache / f"{s}.pkl").exists()]
    tab = E.build_table(cache, base + [s for s in s_all if s not in base], xs_symbols=xs_ref)
    tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
    w0, w1 = pd.Timestamp(WINDOW_START, tz="UTC"), pd.Timestamp(WINDOW_END, tz="UTC") + pd.Timedelta(days=1)
    test = tab[tab.symbol.isin(s_all) & (tab.ts >= w0) & (tab.ts < w1)].reset_index(drop=True)
    # ---- the claims come BEFORE any outcome in the window is touched (rule 4 checks the dates)
    led = Path(a.ledger)
    claim = HL.claim_read(MODEL_ID, WINDOW_START, WINDOW_END, UNIT, a.reader, led, symbols=s_all, train_end=TRAIN_END)
    claim1 = HL.claim_read(MODEL_ID_V1, WINDOW_START, WINDOW_END, f"{UNIT}-v1ref", a.reader, led, symbols=s_all, train_end=TRAIN_END)
    models = {side: lgb.Booster(model_str=art["booster_txt"][side]) for side in ("long", "short")}
    # provenance: Booster — regression booster: predicts net R per decision, not a class probability
    pl, ps = (models[side].predict(test[meta["features"]]) for side in ("long", "short"))
    gate = meta["cost_gate"]
    passes = (float(gate["k_cost_x_atr"]) / test["atr_pct"].to_numpy()) <= float(gate["max_cost_r"])
    pl[~passes] = LV.ABSTAIN
    ps[~passes] = LV.ABSTAIN
    br = meta["bracket"]
    score = LV.relabel_table(test, cache, float(br["sl_atr"]), float(br["tp_atr"]))
    taken = E.policy(score, pl, ps, float(meta["tau"]))
    m = E.summarize(taken)
    # provenance: Booster — regression booster file: predicts net R per decision, not a class probability
    v1p = {side: lgb.Booster(model_file=str(V1_DIR / f"entry_{side}.txt")).predict(test[E.FEATURES]) for side in ("long", "short")}
    taken1 = E.policy(test, v1p["long"], v1p["short"], V1_TAU)
    m1 = E.summarize(taken1)
    a_ok = m["n"] >= E.N_FLOOR and (m.get("n_symbols") or 0) >= E.SYMBOL_FLOOR
    b_ok = HL.point_ok(m["mean_net_r"], m.get("se_net_r"), claim["bar"])
    c_ok = m["mean_net_r"] is not None and m1["mean_net_r"] is not None and m["mean_net_r"] >= m1["mean_net_r"]
    verdict = "indeterminate" if not a_ok else ("pass" if (b_ok and c_ok) else "fail")
    reg20 = taken[taken.symbol.isin(s20)]
    res = {"unit": UNIT, "read_state": "measured", "verdict": verdict,
           "conditions": {"a_n_and_symbols": a_ok, "b_mean_ge_0_at_lock_bar": b_ok, "c_ge_v1_reference": c_ok},
           "window": {"decisions_from": WINDOW_START, "decisions_to": WINDOW_END, "train_end": TRAIN_END, "symbols_primary": len(s_all)},
           "n_test_rows": len(test), "test_symbols": int(test.symbol.nunique()), "candidates_after_gate": int(((np.maximum(pl, ps)) > float(meta["tau"])).sum()),
           "v2": m, "v2_registered_20_reported": E.summarize(reg20), "v1_reference": m1,
           "v1_reference_registered_20_reported": E.summarize(taken1[taken1.symbol.isin(s20)]),
           "baselines_v2_mechanics": LV._baselines(score, taken), "holdout_lock": claim, "holdout_lock_v1ref": claim1,
           "variants_on_window": claim1["variants_on_window"], "git_sha": E._git_sha(), "elapsed_s": round(time.time() - t0),
           "result": (f"{verdict}: v2 {m['mean_net_r']:+.4f} (n={m['n']}, {m.get('n_symbols')} symbols) vs v1 reference "
                      f"{(m1['mean_net_r'] if m1['mean_net_r'] is not None else float('nan')):+.4f} (n={m1['n']})") if m["n"] else f"{verdict}: v2 took no decision"}
    (out / "b610_result.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    taken.to_pickle(out / "symholdout_trades_v2.pkl")
    taken1.to_pickle(out / "symholdout_trades_v1ref.pkl")
    print(res["result"], flush=True)
    return 0


# ------------------------------------------------------------------------------------------------ self-test
def _self_test() -> None:
    import tempfile

    import holdout_lock as HL
    spans = {"AAAUSDT": ("2021-01", "2026-11"), "BBBUSDT": ("2024-01", "2026-11"), "BTCUSDT": ("2020-01", "2026-11"),
             "CCCUSDT": ("2022-05", "2026-06"), "DDDUSDT": ("2023-10", "2026-10"), "EEEUSDT": ("2019-09", "2026-11")}
    assert select_s(spans, {"BTCUSDT"}, 20) == ["AAAUSDT", "DDDUSDT", "EEEUSDT"], select_s(spans, {"BTCUSDT"}, 20)
    assert select_s(spans, {"BTCUSDT"}, 2) == ["AAAUSDT", "DDDUSDT"]
    # the window is fixed by constants, never by a candidate count: nothing in run() reads a count to close it
    src = Path(__file__).read_text()
    assert "count_only" not in src.split("def _self_test")[0] and "trigger_candidates" not in src.split("def _self_test")[0]
    assert WINDOW_START > TRAIN_END
    with tempfile.TemporaryDirectory() as td:
        led = Path(td) / "l.jsonl"
        try:
            HL.claim_read(MODEL_ID, REGISTERED_S_START, WINDOW_END, UNIT, "self-test", led, symbols=["AAAUSDT"], train_end=TRAIN_END)
            raise AssertionError("rule 4 must refuse the 2022-01 symbol-holdout window")
        except HL.WindowOverlapsTraining:
            pass
        c = HL.claim_read(MODEL_ID, WINDOW_START, WINDOW_END, UNIT, "self-test", led, symbols=["AAAUSDT"], train_end=TRAIN_END)
        assert c["n_tries"] == 1
    print("ml_entry_v2_symholdout self-test OK")


def main(argv=None) -> int:
    import holdout_lock as HL
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "symbols"])
    ap.add_argument("--out", default="/tmp/b610_symholdout")
    ap.add_argument("--cache", default="/tmp/b610_klines")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--ledger", default=str(HL.LEDGER))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    if a.cmd == "symbols":
        print(json.dumps(list_s(N_PRIMARY)))
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
