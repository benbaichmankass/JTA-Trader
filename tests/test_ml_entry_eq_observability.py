"""Observability for the silent ml_entry_eq refresher (row ML-ENTRY-EQ-REFRESHER-SILENT, 2026-11-09): every poll has a named reason and every builder
refusal is logged once per (symbol, bar, reason)."""
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.runtime import ml_entry_eq_refresher as R  # noqa: E402
from src.runtime import strategy_signal_builders as B  # noqa: E402

NOW = pd.Timestamp("2026-11-09 16:30", tz="UTC")


def _raw():
    idx = pd.date_range("2026-10-01", "2026-11-09 16:00", freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": idx, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e5})


def test_poll_state_names_every_reason(tmp_path):
    p = tmp_path / "snap.json"
    assert R.poll_state(None, None, None, NOW, p) == "spy_fetch_none_or_empty"
    raw = _raw()
    assert R.poll_state(raw, raw.iloc[0:0], None, NOW, p).startswith("spy_frame_empty_after_rth_filter")
    df = R._frame(raw)
    assert R.poll_state(raw, df, None, NOW, p).startswith("no_decision_close")
    close = pd.Timestamp("2026-11-09 16:00", tz="UTC")
    assert R.poll_state(raw, df, close, close + pd.Timedelta(seconds=10), p).startswith("settling")
    assert R.poll_state(raw, df, close, NOW, p).startswith("due snapshot_pool_snapshot_missing")


def test_builder_refusal_logged_once_per_symbol_bar(caplog):
    B._REFUSAL_LOGGED.clear()
    with caplog.at_level(logging.INFO, logger=B.logger.name):
        for _ in range(3):
            B._log_refusal_once("ml_entry_eq_struct", "SPY", "2026-11-09T16:00", "below_tau")
        B._log_refusal_once("ml_entry_eq_struct", "QQQ", "2026-11-09T16:00", "below_tau")
    msgs = [r.getMessage() for r in caplog.records if "refused" in r.getMessage()]
    assert len(msgs) == 2 and "reason=below_tau" in msgs[0]
