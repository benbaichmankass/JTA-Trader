"""FUNDING-OI-DATASETS-ETH-SOL covariate builder: causality (nothing stamped after the bar close is used) and null-not-zero."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

import funding_oi_covariates as C


def test_self_test():
    C._self_test()


def test_missing_side_stream_is_null_not_zero(tmp_path):
    bars = tmp_path / "b.csv"
    bars.write_text("ts\n2026-01-01T00:00:00Z\n2026-01-01T01:00:00Z\n")
    out = tmp_path / "o.csv"
    rc = C.main(["build", "--funding-oi", str(tmp_path / "nope.jsonl"), "--bars", str(bars), "--out", str(out)])
    assert rc == 2
    rows = out.read_text().splitlines()[1:]
    assert rows and all(r.split(",")[1:] == [""] * 7 for r in rows)
