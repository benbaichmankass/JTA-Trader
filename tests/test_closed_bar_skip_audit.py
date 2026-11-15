"""A closed-bar leg that leaves its bar UNDECIDED writes one audit row saying why.

Before this, ``_closed_window_skip`` / ``_decision_frame`` returned a skip reason
with no audit row, so live-vs-replay parity could not tell "never decided" from
"decided and dropped downstream" (PI-20261111-LRP-C5F97202). Logging only: the
returned skip reasons are unchanged.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.runtime import decision_bar_ledger as ledger
from src.runtime import strategy_signal_builders as ssb
from src.runtime.strategy_signal_builders import _closed_window_skip, _decision_frame

TF = "4h"
H4 = 4 * 3600
T0 = 1_800_000_000 - (1_800_000_000 % H4)
CLOSE = T0 + 10 * H4            # the bar opened at CLOSE - H4 closes here
CFG = {"decision_bar": "closed"}


@pytest.fixture
def rows(monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(ssb, "log_signal", lambda payload: out.append(dict(payload)))
    ssb._CLOSED_SKIP_AUDITED.clear()
    yield out
    ssb._CLOSED_SKIP_AUDITED.clear()


def _frame(last_open, n=5):
    ts = [last_open - (n - 1 - i) * H4 for i in range(n)]
    return pd.DataFrame({"timestamp": pd.to_datetime(ts, unit="s", utc=True),
                         "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0})


def test_stale_skip_writes_one_row_per_bar(monkeypatch, rows):
    monkeypatch.setattr(ledger, "PROCESS_STARTED", CLOSE + 1000)   # restarted past the bound
    for dt in (1100, 1300, 1500):
        assert _closed_window_skip(TF, CFG, name="legA", now=CLOSE + dt) == "closed_bar_stale_skipped"
    assert len(rows) == 1
    r = rows[0]
    assert r["event"] == "legA_eval" and r["side"] == "none"
    assert r["reason"] == "closed_bar_stale_skipped" and r["closed_bar_skip"] is True
    assert r["bar_open_ts"] == CLOSE - H4 and r["timeframe"] == TF


def test_routine_states_stay_out_of_the_audit(rows):
    assert _closed_window_skip(TF, CFG, name="legA", now=CLOSE + 2) == "closed_bar_settling"
    assert _decision_frame(_frame(CLOSE), TF, CFG, name="legA", now=CLOSE + 120)[1] is None
    assert _closed_window_skip(TF, CFG, name="legA", now=CLOSE + 240) == "closed_bar_already_evaluated"
    assert rows == []


def test_unconfirmed_frame_is_audited_once_and_decision_still_retries(rows):
    # the venue returned no forming row yet: the frame ends in the just-closed bar
    for dt in (60, 180):
        assert _decision_frame(_frame(CLOSE - H4), TF, CFG, name="legA",
                               now=CLOSE + dt)[1] == "closed_bar_unconfirmed"
    assert [r["reason"] for r in rows] == ["closed_bar_unconfirmed"]
    # the next tick still decides the bar (no ledger write on unconfirmed)
    assert _decision_frame(_frame(CLOSE), TF, CFG, name="legA", now=CLOSE + 300)[1] is None


def test_symbol_keyed_leg_names_split_into_strategy_and_symbol(monkeypatch, rows):
    monkeypatch.setattr(ledger, "PROCESS_STARTED", CLOSE + 1000)
    _closed_window_skip(TF, CFG, name="e4_oi_shock_1h:SOLUSDT", now=CLOSE + 1100)
    assert rows[0]["event"] == "e4_oi_shock_1h_eval"
    assert rows[0]["strategy"] == "e4_oi_shock_1h" and rows[0]["symbol"] == "SOLUSDT"


def test_audit_failure_never_breaks_the_tick(monkeypatch):
    def boom(_payload):
        raise OSError("disk full")
    monkeypatch.setattr(ssb, "log_signal", boom)
    ssb._CLOSED_SKIP_AUDITED.clear()
    monkeypatch.setattr(ledger, "PROCESS_STARTED", CLOSE + 1000)
    assert _closed_window_skip(TF, CFG, name="legB", now=CLOSE + 1100) == "closed_bar_stale_skipped"
