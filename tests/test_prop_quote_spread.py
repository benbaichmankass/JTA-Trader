"""quote-spread (TRADEIFY-INSTR-SPECS, manager go 2026-10-15 20:21Z): READ-ONLY spread in bps of mid.

The tradeify_1 terminal has no instrument-info widget (instrument-info-dry #18434 refused), and link-state-dump
finds 0 rows there (#18437: the rows sit in a second, header-less table). ``read_quote`` already parses that
table for the executor, so the spread is derived from it and nothing else.
"""
import argparse
import inspect
import re
from pathlib import Path

import pytest

from src.prop.platform.dxtrade import DXtradeAdapter, quote_spread_summary, spread_bps

REPO = Path(__file__).resolve().parents[1]


class _Page:
    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def _adapter(quotes):
    """An adapter whose read_quote replays ``{symbol: [quote | None, ...]}``."""
    a = DXtradeAdapter.__new__(DXtradeAdapter)
    seq = {k: list(v) for k, v in quotes.items()}
    a.read_quote = lambda page, sym: (seq[sym].pop(0) if seq.get(sym) else None)
    return a


def test_spread_bps_is_ask_minus_bid_over_mid():
    assert spread_bps(99.0, 101.0) == pytest.approx(200.0)
    assert spread_bps(100.0, 100.0) == 0.0


@pytest.mark.parametrize("bid,ask", [(0, 1), (-1, 1), (2, 1)])
def test_spread_bps_refuses_a_quote_that_is_not_0_lt_bid_le_ask(bid, ask):
    assert spread_bps(bid, ask) is None


def test_summary_takes_the_median_and_reports_min_max_and_mid():
    s = quote_spread_summary([{"bid": 99, "ask": 101}, {"bid": 99.5, "ask": 100.5}, {"bid": 98, "ask": 102}], 3)
    assert s["read"] == "ok" and s["n_ok"] == 3
    assert s["spread_bps"] == pytest.approx(200.0, abs=0.01)
    assert s["spread_bps_min"] == pytest.approx(100.0, abs=0.01)
    assert s["spread_bps_max"] == pytest.approx(400.0, abs=0.01)
    assert s["mid"] == 100.0


def test_no_parsed_quote_is_none_never_zero():
    s = quote_spread_summary([], 3)
    assert s == {"read": "none", "n_ok": 0, "n_tried": 3}
    assert "spread_bps" not in s


def test_quote_spread_reads_each_symbol_and_marks_a_missing_one_none():
    a = _adapter({"SILVERUSD": [{"bid": 99, "ask": 101}] * 3, "USOILUSD": [None, None, None]})
    page = _Page()
    got = a.quote_spread(page, ["silverusd", "USOILUSD", "SILVERUSD"], samples=3, gap_ms=5)
    assert got["symbols"] == ["SILVERUSD", "USOILUSD"]  # upper-cased, de-duplicated
    assert got["results"]["SILVERUSD"]["spread_bps"] == pytest.approx(200.0, abs=0.01)
    assert got["results"]["USOILUSD"]["read"] == "none"
    assert page.waits == [5, 5, 5, 5]  # between samples only, per symbol


def test_a_read_that_raises_is_reported_not_swallowed_as_zero():
    a = DXtradeAdapter.__new__(DXtradeAdapter)

    def boom(page, sym):
        raise RuntimeError("x")

    a.read_quote = boom
    got = a.quote_spread(_Page(), ["ETHUSD"], samples=2, gap_ms=1)
    assert got["results"]["ETHUSD"] == {"read": "error", "error": "RuntimeError"}


def test_quote_spread_never_clicks_types_or_reads_an_account():
    src = inspect.getsource(DXtradeAdapter.quote_spread)
    for bad in (".click(", ".press(", ".fill(", "keyboard", "read_account", "evaluate("):
        assert bad not in src


def test_tick_resolves_the_mode():
    from scripts.prop.prop_executor_tick import YIELD_MODES, resolve_mode
    args = argparse.Namespace(probe_ticket="", dry_run=False, watched_click=False, quote_spread="SILVERUSD",
                              account="tradeify_1")
    assert resolve_mode(args, {}) == "quote_spread"
    assert "quote_spread" in YIELD_MODES


def test_workflow_and_action_script_both_allow_it_and_require_symbols():
    yml = (REPO / ".github/workflows/system-actions.yml").read_text()
    sh = (REPO / "scripts/ops/breakout_login_check_action.sh").read_text()
    assert yml.count("quote-spread") >= 3  # regex, error list, symbols-required case
    assert re.search(r'quote-spread\)\s+EARGS\+=\(--quote-spread "\$\{ACTION_SYMBOLS// /\}"\)', sh)
    assert '"${EXEC_MODE}" = "quote-spread"' in sh  # 'symbols:' required
