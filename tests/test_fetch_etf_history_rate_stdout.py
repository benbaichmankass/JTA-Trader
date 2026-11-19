"""The ETF bar fetcher's rate gate must not write to STDOUT.

scripts/research/live_review_outcomes.py imports scripts/ops/fetch_etf_history.py (the Alpaca fallback when
yfinance is absent) and scripts/ops/live_review_packet.py json.loads the pricer's stdout. On 2026-11-19 the
gate's "[rate] plan declares ..." status line landed first on stdout, so every equity packet (IEF
LR-20261119T1437Z-pkg-c2d9a660f6a14fce) recorded priced_options_state=could_not_price.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))

import fetch_etf_history as feh  # noqa: E402


def test_declare_writes_nothing_to_stdout(capsys):
    gate = feh.RateGate()
    gate.declare(200)
    out, err = capsys.readouterr()
    assert out == ""
    assert "[rate] plan declares 200 req/min" in err
    assert gate.declared_per_min == 200
