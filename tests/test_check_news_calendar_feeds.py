"""DATA-FEEDS-NEWS-CALENDAR: feed liveness verdicts + the calendar emitter's no-blank/idempotent contract."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "macro"))
import check_producer_liveness as C  # noqa: E402
import econ_calendar_produce as P  # noqa: E402

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _cal(tmp_path, *times):
    p = tmp_path / "c.yaml"
    p.write_text("events:\n" + "".join(f'  - {{class: fomc, time: "{t}", impact: 1.0}}\n' for t in times))
    return p


def test_horizon_ok_stale_and_could_not_look(tmp_path):
    assert C.check_calendar_horizon(_cal(tmp_path, "2026-11-06T13:30:00Z"), NOW)["status"] == "fresh"
    assert C.check_calendar_horizon(_cal(tmp_path, "2026-10-30T13:30:00Z"), NOW)["status"] == "stale"
    assert C.check_calendar_horizon(tmp_path / "missing.yaml", NOW)["status"] == "could_not_look"


def test_refresh_age(tmp_path):
    (tmp_path / "US-20261026T003922Z.fxstreet.json").write_text("{}")
    assert C.check_calendar_refresh(tmp_path, NOW)["status"] == "fresh"
    old = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert C.check_calendar_refresh(tmp_path, old)["status"] == "stale"
    assert C.check_calendar_refresh(tmp_path / "nope", NOW)["status"] == "could_not_look"


def test_news_states():
    row = lambda ts: {"present": True, "lines": [json.dumps({"ts": ts})]}  # noqa: E731
    crypto = {"db_state": "read", "packages": [{"symbol": "ETHUSDT"}]}
    flat = {"db_state": "read", "packages": [{"symbol": "SPY"}]}
    assert C.check_news(row("2026-10-26T11:00:00+00:00"), crypto, NOW)["status"] == "fresh"
    assert C.check_news(row("2026-10-25T20:00:00+00:00"), crypto, NOW)["status"] == "stale"
    assert C.check_news(row("2026-10-25T20:00:00+00:00"), flat, NOW)["status"] == "fresh"
    assert C.check_news({}, crypto, NOW)["status"] == "could_not_look"
    assert C.check_news(row("2026-10-26T11:00:00+00:00"), {}, NOW)["status"] == "could_not_look"


def test_emit_keeps_last_good_and_is_idempotent(tmp_path):
    p = tmp_path / "cal.yaml"
    p.write_text("defaults: {}\n\nevents:\n  - {class: fomc, time: \"2026-11-04T18:30:00Z\", impact: 1.0}\n")
    before = p.read_text()
    n = P._emit_config_yaml([], out_path=p, base_path=p, as_of="2026-10-26")
    assert n == 1 and p.read_text() == before  # failed/empty run never blanks the file
    ev = [{"class": "fomc", "time": "2026-11-04T18:30:00Z", "impact": 1.0}]
    P._emit_config_yaml(ev, out_path=p, base_path=p, as_of="2026-10-26")
    first = p.read_text()
    P._emit_config_yaml(ev, out_path=p, base_path=p, as_of="2026-10-26")
    assert p.read_text() == first and first.count("Auto-populated") == 1
