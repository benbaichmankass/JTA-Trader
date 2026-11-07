#!/usr/bin/env python3
"""Real-lake parity run (row ML-DATA-WIRING, Tier 1): lake klines cache vs the Binance-Vision streams cache, same universe + window.

Needs HF_TOKEN (read) for the lake; the streams side is keyless (data.binance.vision). Writes ``<out>/lake_parity.json`` with the
population (symbols requested / written, window, tf, lake revision) beside every number. Never raises on a diff: the record says what differs.

    python3 scripts/research/lake_parity_run.py --out /tmp/lp [--max-symbols N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/lake_parity")
    ap.add_argument("--max-symbols", type=int, default=0, help="0 = whole bp2 universe")
    ap.add_argument("--lake-revision", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import ml_decision_entry as E
    import ml_entry_families as F
    import vision_streams as VS
    from ml.datasets import lake, lake_klines as LK

    syms = E.universe()[: a.max_symbols or None]
    end = str((pd.Timestamp(E.END) + pd.Timedelta(days=1)).date())
    rec: dict = {"row": "ML-DATA-WIRING", "tf": "1h", "market": "um_perp", "window": [E.START, E.END],
                 "symbols_requested": len(syms), "read_state": "unknown"}
    try:
        rec["manifest_paths"] = [{k: e.get(k) for k in ("symbol", "first", "last", "rows")}
                                 for e in lake.entries("crypto", "um_perp", "1h", a.lake_revision)]
        rec["manifest_1h_um_perp_series"] = len(rec["manifest_paths"])
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded in the record, nothing halts
        rec["manifest_error"] = f"{type(e).__name__}: {e}"[:300]
    try:
        lcache, lsyms, info = LK.build_klines_cache(out, syms, E.START, end, revision=a.lake_revision)
    except Exception as e:  # noqa: BLE001  # allow-silent: the record says "could not look" + why; the step still exits non-zero
        rec.update(read_state="could_not_look", lake_error=f"{type(e).__name__}: {e}"[:600],
                   cause_hint="HF 403 'Private repository storage limit reached' means the lake is unreadable until the plan/storage is fixed")
        (out / "lake_parity.json").write_text(json.dumps(rec, indent=1, default=str))
        print(json.dumps(rec, indent=1, default=str)[:3000])
        return 1
    rec["lake"] = info
    VS.run(out / "vs", ["klines12"], E.START, E.END, 16, syms)
    scache = out / "klines_streams"
    scache.mkdir(exist_ok=True)
    ssyms = []
    for s in syms:
        p = out / "vs" / "klines12" / f"{s}.pkl"
        if not p.exists():
            continue
        k = pd.read_pickle(p)
        k["ts"] = F._ts(k["open_time"])
        k = LK.clean(k, E.START, end)
        k.to_pickle(scache / f"{s}.pkl")
        ssyms.append(s)
    rec["streams"] = {"symbols_written": len(ssyms), "missing": sorted(set(syms) - set(ssyms))}
    both = [s for s in syms if s in lsyms and s in ssyms]
    p = LK.parity(scache, lcache, both)
    rec["parity"] = {"population": f"{len(both)} symbols present on both sides of {len(syms)} requested",
                     "identical": p["identical"], "symbols_compared": p["symbols_compared"],
                     "n_diff_symbols": len(p["diffs"]), "diffs_first20": p["diffs"][:20],
                     "overlap_rows_total": sum(v["overlap_rows"] for v in p["per_symbol"].values()),
                     "only_stream_rows_total": sum(v["only_stream"] for v in p["per_symbol"].values()),
                     "only_lake_rows_total": sum(v["only_lake"] for v in p["per_symbol"].values()),
                     "max_abs_diff_overall": max([v["max_abs_diff"] or 0.0 for v in p["per_symbol"].values()] or [None])}
    rec["read_state"] = "read"
    # build-table --source lake: the real consumer path, on the lake cache we just wrote
    try:
        tab = E.build_table(lcache, lsyms)
        rec["build_table_lake"] = {"rows": int(len(tab)), "symbols": int(tab["symbol"].nunique()) if "symbol" in tab else None}
    except Exception as e:  # noqa: BLE001  # allow-silent: recorded
        rec["build_table_lake"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    (out / "lake_parity.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: v for k, v in rec.items() if k != "manifest_paths"}, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
