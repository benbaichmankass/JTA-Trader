#!/usr/bin/env python3
# wiring: research/queue/RQ-20261108-98e3-29.yaml (runner twin, routing.published_data: metis-market-lake); PROP-ML-NEW-DATA step 1 follow-up
"""Lake-presence column of the non-price census: which (symbol, series) the Kaggle lake mirror holds, over which periods.

Reads ONLY the per-part ``MANIFEST.json`` files the manifest-only published_data fetch put under ``$LAKE_MANIFEST_ROOT/<slug>/``
(scripts/research/published_data.py::fetch_manifests). No shard is read, nothing is re-hashed: a manifest member path is a CLAIM
that the file was copied, verified separately by kaggle-cold-lake-copy.yml. Member paths look like
``crypto/um_perp/<label>/<SYMBOL>/<YYYY or YYYY-MM>.parquet``; every member that does NOT parse is counted and sampled, so a layout
surprise shows up as a low parse rate and an INDETERMINATE verdict instead of a silent undercount.

The mirror holds the FROZEN (closed-month) history only: the hot tail (current months) is not in it, so ``last_period`` is expected
to trail the present. The graded census RQ-20261108-98e3-28 is a different record and is never edited.

    python3 scripts/research/lake_presence.py run --out DIR --unit RQ-... [--rule-id ..] [--registered-at ..]   # needs LAKE_MANIFEST_ROOT
    python3 scripts/research/lake_presence.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]
REQUIRED = ["ETHUSDT", "SOLUSDT"]
# lake series labels for the streams the census grades (docs/data/market-data-lake.md, binance_vision_lake.STREAMS labels)
STREAM_LABELS = {"fundingRate": "funding", "premiumIndexKlines": "premium_1m", "metrics": "metrics_5m",
                 "bookDepth": "bookdepth", "aggTrades": "orderflow_1m", "klines": "1m"}
MIN_PARSE_RATE = 0.95            # registered: below this the layout is not understood and presence cannot be stated
PAT = re.compile(r"(?:^|/)crypto/(?P<market>[a-z_]+)/(?P<label>[^/]+)/(?P<sym>[^/]+)/(?P<period>\d{4}(?:-\d{2})?)\.parquet$")


def parse_member(path: str) -> dict | None:
    m = PAT.search(path)
    return m.groupdict() if m else None


def months_of(period: str) -> list[tuple[int, int]]:
    y = int(period[:4])
    return [(y, int(period[5:7]))] if len(period) == 7 else [(y, mo) for mo in range(1, 13)]


def summarize(paths: list[str]) -> dict:
    """Pure: per (market, label, symbol) the members, first/last period and the months missing INSIDE the span."""
    series: dict[tuple[str, str, str], set[tuple[int, int]]] = {}
    counts: dict[tuple[str, str, str], int] = {}
    unparsed: list[str] = []
    for p in paths:
        r = parse_member(p)
        if r is None:
            unparsed.append(p)
            continue
        k = (r["market"], r["label"], r["sym"])
        series.setdefault(k, set()).update(months_of(r["period"]))
        counts[k] = counts.get(k, 0) + 1
    out = {}
    for k, ms in series.items():
        lo, hi = min(ms), max(ms)
        span = (hi[0] - lo[0]) * 12 + (hi[1] - lo[1]) + 1
        out["/".join(k)] = {"members": counts[k], "first_month": f"{lo[0]:04d}-{lo[1]:02d}", "last_month": f"{hi[0]:04d}-{hi[1]:02d}",
                            "months_present": len(ms), "months_missing_inside_span": span - len(ms)}
    return {"series": out, "n_members": len(paths), "n_parsed": len(paths) - len(unparsed),
            "parse_rate": (1 - len(unparsed) / len(paths)) if paths else None, "unparsed_sample": unparsed[:10]}


def presence_table(summary: dict) -> list[dict]:
    """The rows the census needs: (symbol, stream) -> present / absent, with the span the lake holds."""
    rows = []
    for sym in SYMBOLS:
        for stream, label in STREAM_LABELS.items():
            hits = {k: v for k, v in summary["series"].items() if k.split("/")[1:] == [label, sym]}
            if not hits:
                rows.append({"symbol": sym, "stream": stream, "label": label, "lake_state": "ABSENT-FROM-MANIFESTS"})
                continue
            k, v = min(hits.items(), key=lambda kv: kv[0])
            rows.append({"symbol": sym, "stream": stream, "label": label, "lake_state": "IN-MANIFEST", "series": k, **v})
    return rows


def verdict(parts: int, summary: dict) -> tuple[str, str]:
    if parts < 1 or not summary["n_members"]:
        return "indeterminate", f"{parts} part manifest(s) read, {summary['n_members']} members: nothing to state"
    if summary["parse_rate"] < MIN_PARSE_RATE:
        return "indeterminate", (f"only {summary['parse_rate']:.3f} of {summary['n_members']} member paths parse (< {MIN_PARSE_RATE}); "
                                 "the layout is not understood, so presence cannot be stated")
    return "pass", f"{parts} part manifests, {summary['n_members']} members, {summary['parse_rate']:.3f} parsed"


def read_members(root: Path) -> tuple[int, list[str]]:
    paths: list[str] = []
    parts = 0
    for mp in sorted(root.rglob("MANIFEST.json")):
        man = json.loads(mp.read_text(encoding="utf-8"))
        parts += 1
        for f in man.get("files") or []:
            for m in f.get("members") or []:
                if m.get("path"):
                    paths.append(str(m["path"]))
    return parts, paths


def run(a) -> int:
    root_s = os.environ.get("LAKE_MANIFEST_ROOT", "")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not root_s or not Path(root_s).is_dir():
        row = _row(a, "not_applicable", "NEVER MEASURED: LAKE_MANIFEST_ROOT is unset or missing (the manifest-only fetch did not run)", {})
    else:
        parts, paths = read_members(Path(root_s))
        s = summarize(paths)
        v, why = verdict(parts, s)
        table = presence_table(s)
        n_req = sum(1 for r in table if r["symbol"] in REQUIRED and r["lake_state"] == "IN-MANIFEST")
        note = f"{v}: {why}; ETH+SOL streams in manifest {n_req} of {len(REQUIRED) * len(STREAM_LABELS)}"
        row = _row(a, v, note, {"parts_read": parts, "summary": {k: s[k] for k in ("n_members", "n_parsed", "parse_rate", "unparsed_sample")},
                                "all_series_for_prop_symbols": {k: x for k, x in s["series"].items() if k.split("/")[-1] in SYMBOLS},
                                "presence": table, "hot_tail_note": "the mirror holds frozen closed-month history only; recent months are not in it",
                                "min_parse_rate": MIN_PARSE_RATE}, n=s["n_members"])
    (out / f"{a.unit}.json").write_text(json.dumps(row, indent=1, default=str))
    (out / "verdict.json").write_text(json.dumps(row, indent=1, default=str) + "\n")
    print("LAKE-PRESENCE: " + row["note"], flush=True)
    return 0


def _row(a, verdict_: str, note: str, measurement: dict, n=None) -> dict:
    # read_state is the HARNESS's vocabulary (script_run.READ_STATES): "not_attempted" is the only value for a run that never read the manifests
    # (the verdict not_applicable, NEVER MEASURED); every verdict reached by reading them (pass / fail / indeterminate) is "measured". Writing
    # "not_measured" here (2026-11-09, runs 42551423143 and 42562200115) made the harness reject the record as malformed and grade it producer_failed.
    return {"schema_version": 1, "research_unit": a.unit, "read_state": "not_attempted" if verdict_ == "not_applicable" else "measured",
            "verdict": verdict_,
            "population": ("members listed in the per-part MANIFEST.json of the private Kaggle lake mirror metis-market-lake-pNNN (frozen crypto "
                           "history); a CLAIM of copy, not a read of any shard"),
            "note": note, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "decision_rule": {"id": a.rule_id, "registered_at": a.registered_at, "registered_before_run": True},
            "measurement": measurement, "n": n, "produced_by": {"tool": "python3 scripts/research/lake_presence.py run", "where": a.where}}


def self_test() -> int:
    ok = ["crypto/um_perp/funding/ETHUSDT/2021.parquet", "crypto/um_perp/funding/ETHUSDT/2022.parquet",
          "crypto/um_perp/metrics_5m/ETHUSDT/2022-01.parquet", "crypto/um_perp/metrics_5m/ETHUSDT/2022-03.parquet",
          "crypto/um_perp/funding/SOLUSDT/2022.parquet", "crypto/spot/1m/ETHUSDT/2024-05.parquet"]
    s = summarize(ok + ["weird/path.txt"])
    assert s["n_members"] == 7 and s["n_parsed"] == 6 and s["unparsed_sample"] == ["weird/path.txt"]
    f = s["series"]["um_perp/funding/ETHUSDT"]
    assert f["first_month"] == "2021-01" and f["last_month"] == "2022-12" and f["months_present"] == 24 and f["months_missing_inside_span"] == 0
    m = s["series"]["um_perp/metrics_5m/ETHUSDT"]
    assert m["months_present"] == 2 and m["months_missing_inside_span"] == 1, m          # 2022-02 is a gap inside the span
    t = {(r["symbol"], r["stream"]): r for r in presence_table(s)}
    assert t[("ETHUSDT", "fundingRate")]["lake_state"] == "IN-MANIFEST" and t[("ETHUSDT", "bookDepth")]["lake_state"] == "ABSENT-FROM-MANIFESTS"
    assert t[("SOLUSDT", "metrics")]["lake_state"] == "ABSENT-FROM-MANIFESTS"
    assert verdict(2, summarize(ok))[0] == "pass"
    assert verdict(0, summarize(ok))[0] == "indeterminate"
    assert verdict(2, summarize(["x/y.txt"] * 10 + ok[:1]))[0] == "indeterminate"        # a layout we do not understand is never a presence claim
    assert verdict(1, summarize([]))[0] == "indeterminate"
    with tempfile.TemporaryDirectory() as td:
        for slug, members in (("metis-market-lake-p000", ok[:3]), ("metis-market-lake-p001", ok[3:])):
            d = Path(td) / slug
            d.mkdir()
            (d / "MANIFEST.json").write_text(json.dumps({"files": [{"path": "a.tar", "members": [{"path": p} for p in members]}]}))
        parts, paths = read_members(Path(td))
        assert parts == 2 and sorted(paths) == sorted(ok)
    import script_run as SR       # the harness's own vocabulary: a record that uses a word outside it is graded producer_failed
    class _A:
        unit, where, rule_id, registered_at = "RQ-X", "local", "RULE-X", "2026-11-08"
    for v_ in ("pass", "fail", "indeterminate", "not_applicable"):
        r_ = _row(_A, v_, "n", {})
        assert r_["read_state"] in SR.READ_STATES and r_["verdict"] in SR.VERDICTS, (v_, r_["read_state"])
    assert _row(_A, "not_applicable", "n", {})["read_state"] == "not_attempted"     # NEVER MEASURED: the manifests were not read
    assert _row(_A, "indeterminate", "n", {})["read_state"] == "measured"            # read, but the layout was not understood: a measurement
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--out", default="/tmp/lake_presence_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--where", default="local")
    ap.add_argument("--rule-id", dest="rule_id", default="")
    ap.add_argument("--registered-at", dest="registered_at", default="")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.cmd != "run" or not a.unit:
        ap.error("run --unit RQ-... (or --self-test)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
