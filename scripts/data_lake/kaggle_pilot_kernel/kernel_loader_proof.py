"""Kaggle kernel body for hf-lake-kaggle-loader-proof.yml (row HF-LAKE-KAGGLE-LOADER, 2026-11-12).

Static and reviewed; carries no secret. Internet OFF, CPU only. The workflow replaces __BUNDLE_B64__ with a gzip+tar of the repo files
the loader needs (ml/datasets/lake.py + lake_mirror.py, scripts/data_lake/resample.py, config/data_universe.yaml), so the kernel runs the code
under review. It mounts the private mirror datasets metis-market-lake-p000..p010 and calls the loader on the mount, with no HF access:

    lake.symbols('crypto','um_perp','1h')       must list the mirror's symbols (1h is DERIVED on read from the 1m mirror)
    lake.load(... 1h, window of closed months)  must return complete, hash-verified bars from the mirror
    a window reaching the hot tail              must NOT be an empty frame: LakeReadError or an explicit could_not_look state

Output: /kaggle/working/result.json
"""
import base64
import io
import json
import os
import sys
import tarfile
import time
import traceback

WORK = os.environ.get("KERNEL_WORK_DIR", "/kaggle/working")  # env override only for the local rehearsal
OUT = os.path.join(WORK, "result.json")
res = {"ok": False, "checks": {}}


def save():
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=str)


try:
    root = os.path.join(WORK, "repo")
    os.makedirs(root, exist_ok=True)
    blob = base64.b64decode("__BUNDLE_B64__")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        tf.extractall(root, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(root)
    sys.path.insert(0, root)
    os.chdir(root)
    import types  # noqa: E402

    # the bundle holds only the loader: stub the package markers so ml/datasets/__init__.py (dataset families, they import src/) is not run
    for name, sub in (("ml", "ml"), ("ml.datasets", "ml/datasets")):
        mod = types.ModuleType(name)
        mod.__path__ = [os.path.join(root, sub)]
        sys.modules[name] = mod
    import pandas as pd  # noqa: E402
    from ml.datasets import lake, lake_mirror  # noqa: E402

    t0 = time.time()
    desc = lake_mirror.describe()                      # builds the member index (reads the 11 MANIFEST.json files)
    res["index_seconds"] = round(time.time() - t0, 2)
    res["mirror"] = {k: desc[k] for k in ("datasets", "members", "problems", "plan_ids", "last_month")}
    res["mounted"] = desc["mounted"]
    res["internet"] = "off (enable_internet=false)"

    # what the mirror really holds for the symbols this proof loads (diagnostic: a 0-row window must be explainable)
    members = lake_mirror.index()[0]
    diag = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        ms = sorted(p for p in members if f"/um_perp/1m/{sym}/" in p)
        diag[sym] = {"um_perp_1m_members": len(ms), "first": ms[0].rsplit("/", 1)[-1] if ms else None,
                     "last": ms[-1].rsplit("/", 1)[-1] if ms else None,
                     "has_2023_01_03": [f"crypto/um_perp/1m/{sym}/2023-0{m}.parquet" in members for m in (1, 2, 3)]}
    res["diag_members"] = diag

    # 1. the call the row names
    t1 = time.time()
    syms = lake.symbols("crypto", "um_perp", "1h")
    res["checks"]["symbols"] = {"n": len(syms), "first5": list(syms[:5]), "read_state": syms.read_state,
                                "manifest": {k: v for k, v in lake.read_state().items() if k != "mirror"},
                                "seconds": round(time.time() - t1, 2)}
    ents = {e["symbol"]: e for e in lake.entries("crypto", "um_perp", "1h")}
    res["diag_entries"] = {s_: {"n_partitions": len(ents[s_]["partitions"]), "months": sorted(ents[s_]["partitions"])[:2] +
                                sorted(ents[s_]["partitions"])[-2:]} for s_ in ("BTCUSDT", "ETHUSDT") if s_ in ents}

    # 2. a closed-month window, derived 1h from the 1m mirror, hash-verified
    cover = [s_ for s_, e in ents.items() if {"2023-01", "2023-02", "2023-03"} <= set(e["partitions"])]
    pick = [s_ for s_ in ("BTCUSDT", "ETHUSDT") if s_ in cover] or cover[:2]
    res["checks"]["window_symbols_covering_2023_Q1"] = {"n_covering": len(cover), "picked": pick}
    assert pick, "no symbol in the mirror manifest covers 2023-01..03; see diag_members / diag_entries"  # an empty list would mean ALL symbols
    t1 = time.time()
    df = lake.load("crypto", "um_perp", "1h", pick, start="2023-01-01", end="2023-04-01")
    per = df.groupby("symbol").size().to_dict() if len(df) else {}
    res["checks"]["load_1h_closed_window"] = {
        "symbols": pick, "rows": int(len(df)), "rows_by_symbol": per, "expected_per_symbol_if_complete": 90 * 24,
        "all_bars_complete": bool(df["complete"].all()) if len(df) else None, "read": df.attrs.get("lake_read"),
        "seconds": round(time.time() - t1, 2)}

    # 3. a streaming read over many series (bounded memory), still no network
    t2 = time.time()
    n_series, n_rows, bad = 0, 0, []
    cover22 = [s_ for s_, e in ents.items() if "2022-06" in e["partitions"]][:25]
    for sym, d in lake.iter_series("crypto", "um_perp", "1h", cover22, start="2022-06-01", end="2022-07-01"):
        n_series += 1
        n_rows += len(d)
    res["checks"]["iter_series_25"] = {"series": n_series, "rows": n_rows, "seconds": round(time.time() - t2, 2)}

    # 4. the hot tail cannot be read here (no internet): it must be explicit, never an empty frame
    now = pd.Timestamp.now(tz="UTC")
    start = (now - pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    try:
        hot = lake.load("crypto", "um_perp", "1h", pick[:1], start=start, on_unreadable="state")
        res["checks"]["hot_tail_window"] = {"rows": int(len(hot)), "read": hot.attrs.get("lake_read")}
        hot_ok = hot.attrs["lake_read"]["n_could_not_look"] > 0
    except lake.LakeReadError as e:
        res["checks"]["hot_tail_window"] = {"raised": "LakeReadError", "state": e.state}
        hot_ok = True

    rd = res["checks"]["load_1h_closed_window"]
    res["ok"] = bool(
        len(syms) > 0 and res["mirror"]["datasets"] >= 1 and not res["mirror"]["problems"]
        and rd["rows"] > 0 and rd["all_bars_complete"] and rd["read"]["from_kaggle_mirror"] > 0 and rd["read"]["n_could_not_look"] == 0
        and n_series > 0 and n_rows > 0 and hot_ok)
    res["seconds_total"] = round(time.time() - t0, 2)
except Exception as e:  # noqa: BLE001  -- recorded in the output, never hidden
    res["error"] = f"{type(e).__name__}: {e}"
    res["trace"] = traceback.format_exc()[-1500:]
save()
print(json.dumps({k: v for k, v in res.items() if k != "trace"}, default=str)[:1500])
