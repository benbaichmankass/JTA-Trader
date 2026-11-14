"""HEALTH-20261112-LIVE-DISK-OTHER-GROWERS: the trader's per-tick no-op lines and the per-open DB banner
filled /var/log/syslog (~200 MB/day). The banner logs once per process per DB path and never hits stdout."""
from __future__ import annotations

import logging

from src.units.db import database as dbmod


def test_tables_banner_logs_once_per_path_and_not_to_stdout(tmp_path, caplog, capsys, monkeypatch):
    monkeypatch.setattr(dbmod, "_TABLES_VERIFIED", set())
    p = tmp_path / "trade_journal.db"
    with caplog.at_level(logging.INFO, logger=dbmod.__name__):
        for _ in range(5):
            dbmod.Database(str(p))
    banners = [r for r in caplog.records if "created/verified" in r.getMessage()]
    assert len(banners) == 1
    assert "created/verified" not in capsys.readouterr().out


def test_tables_banner_logs_again_for_a_different_path(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(dbmod, "_TABLES_VERIFIED", set())
    with caplog.at_level(logging.INFO, logger=dbmod.__name__):
        dbmod.Database(str(tmp_path / "a.db"))
        dbmod.Database(str(tmp_path / "b.db"))
    assert len([r for r in caplog.records if "created/verified" in r.getMessage()]) == 2


def test_per_tick_noop_lines_are_debug():
    import inspect

    from src.runtime import intent_multiplexer, pipeline
    p = inspect.getsource(pipeline)
    m = inspect.getsource(intent_multiplexer)
    for s in ('logger.info("Pipeline start")', 'logger.info("Using strategy builder',
              'logger.info("No actionable signal', "logger.info(\"Multiplexer: '%s' returned no actionable"):
        assert s not in p
    assert 'logger.info("intent_multiplexer: no strategy emitted an intent' not in m
