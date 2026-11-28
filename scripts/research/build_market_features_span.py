#!/usr/bin/env python3
# wiring: research/queue/blocked/RQ-20261128-f1a5-05.yaml (research-script-run-trainer.yml); RESEARCH-NO-WAIT-FOR-DATA
"""Build a one-off market_raw + market_features dataset for ONE symbol/timeframe over a STATED span, into --out.

Why: the research runners allow only ``python3 scripts/research/*.py`` (script_run.py), so a unit cannot call
``python -m ml build-dataset`` directly. The nightly trainer build keeps a rolling 5-year window (MARKET_START =
5 years ago, scripts/ops/build_trainer_datasets.sh), which is too short for a disjoint read of older history
(RQ-20261128-f1a5-05 needs BTC 15m from 2020-03). This wrapper runs the SAME two ``ml.datasets`` builds the
nightly script runs (same adapter and the same market_features params), with an explicit start/end, into a
directory the run owns. It writes nothing outside --out and touches no nightly dataset. Report-only tooling;
Gates this adds or changes: none.

    python3 scripts/research/build_market_features_span.py --symbol BTCUSDT --timeframe 15m \\
        --start 2020-03-01 --end 2026-11-27 --out {out_dir}/ds [--version v901]
    python3 scripts/research/build_market_features_span.py --self-test
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# The nightly script's market_features params (build_bybit_features), kept identical so a span build matches it.
FEATURE_PARAMS = ("vol_window_n=20", "forward_window_m=5", "vol_threshold=0.005", "trend_threshold=0.005",
                  "n_vol_buckets=3")


def build_argvs(symbol: str, timeframe: str, start: str, end: str, out: str, version: str) -> tuple[list, list]:
    """The two ``ml.datasets build`` argv lists (raw, then features). Pure, so the self-test pins them."""
    raw_path = f"{out}/market_raw/{symbol}/{timeframe}/{version}"
    raw = ["build", "market_raw", "--output-dir", out, "--version", version, "--source", "bybit_v5_offvm",
           "--symbol-scope", symbol, "--timeframe", timeframe, "--overwrite", "adapter=bybit_v5_offvm",
           f"symbol={symbol}", f"timeframe={timeframe}", f"start={start}", f"end={end}"]
    feats = ["build", "market_features", "--output-dir", out, "--version", version, "--source", raw_path,
             "--symbol-scope", symbol, "--timeframe", timeframe, "--overwrite", f"market_raw_path={raw_path}",
             *FEATURE_PARAMS]
    return raw, feats


def self_test() -> None:
    raw, feats = build_argvs("BTCUSDT", "15m", "2020-03-01", "2026-11-27", "/o/ds", "v901")
    assert raw[:2] == ["build", "market_raw"] and "start=2020-03-01" in raw and "end=2026-11-27" in raw
    assert feats[feats.index("--source") + 1] == "/o/ds/market_raw/BTCUSDT/15m/v901"
    assert all(p in feats for p in FEATURE_PARAMS)
    print("build-market-features-span self-test OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbol")
    ap.add_argument("--timeframe")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out")
    ap.add_argument("--version", default="v901")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not all((a.symbol, a.timeframe, a.start, a.end, a.out)):
        ap.error("--symbol --timeframe --start --end --out are required")
    if ".." in a.out:
        ap.error("--out must not contain '..'")
    from ml.datasets.cli import main as datasets_main  # noqa: PLC0415  (heavy import only on a real run)
    raw, feats = build_argvs(a.symbol, a.timeframe, a.start, a.end, a.out, a.version)
    for argv_ in (raw, feats):
        print("ml.datasets", " ".join(argv_), flush=True)
        rc = datasets_main(argv_)
        if rc:
            print(f"ERROR: ml.datasets {argv_[1]} exited {rc}", file=sys.stderr)
            return int(rc)
    print(f"built {a.out}/market_features/{a.symbol}/{a.timeframe}/{a.version}/data.jsonl", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
