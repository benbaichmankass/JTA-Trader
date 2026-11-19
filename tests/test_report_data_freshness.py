import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import report_data_freshness as rdf

NOW = datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)


def _w(p, name, last):
    (p / name).write_text(f"timestamp,open,close\n2026-01-01 00:00:00+00:00,1,1\n{last},1,1\n")


def test_fresh_stale_unreadable_and_exit_zero(tmp_path, capsys):
    _w(tmp_path, "AAA_15m.csv", "2026-11-18 20:15:00+00:00")
    _w(tmp_path, "BBB_15m.csv", "2026-06-18 00:00:00+00:00")
    _w(tmp_path, "CCC_1d.csv", "2026-11-15T00:00:00Z")
    (tmp_path / "DDD_5m.csv").write_text("timestamp,open\n")
    by = {r["file"]: r for r in rdf.report(tmp_path, NOW)}
    assert by["AAA_15m.csv"]["stale"] is False
    assert by["BBB_15m.csv"]["stale"] is True
    assert by["CCC_1d.csv"]["stale"] is False
    assert by["DDD_5m.csv"]["read_state"] == "unreadable" and by["DDD_5m.csv"]["last_bar"] is None
    assert rdf.main(["--data-dir", str(tmp_path)]) == 0


# TRAINER-1D-STALE-ROSTERED (2026-11-19): a stale ROSTERED 1d file must reach a person, once per cooldown.
def _rows():
    return [
        {"file": "GDX_1d.csv", "grain": "1d", "read_state": "ok", "last_bar": "2026-07-10T00:00:00+00:00", "stale": True},
        {"file": "SPY_1d.csv", "grain": "1d", "read_state": "ok", "last_bar": "2026-11-18T00:00:00+00:00", "stale": False},
        {"file": "DBC_1d.csv", "grain": "1d", "read_state": "ok", "last_bar": "2026-06-18T00:00:00+00:00", "stale": True},
        {"file": "GC_F_1d.csv", "grain": "1d", "read_state": "unreadable", "last_bar": None, "stale": None},
        {"file": "BTCUSDT_15m.csv", "grain": "15m", "read_state": "ok", "last_bar": "2026-07-01", "stale": True},
    ]


def test_stale_rostered_keeps_only_rostered_1d_rows_and_maps_micros():
    import scripts.ops.report_data_freshness as rdf
    bad = rdf.stale_rostered(_rows(), {"GDX", "SPY", "MGC", "BTCUSDT"})
    # GDX stale; MGC reads GC_F (unreadable counts: could not look); DBC not rostered; 15m not a 1d row
    assert sorted(r["file"] for r in bad) == ["GC_F_1d.csv", "GDX_1d.csv"]


def test_alert_pings_once_per_cooldown_and_is_clean_when_nothing_is_stale(tmp_path, monkeypatch):
    import scripts.ops.report_data_freshness as rdf
    sent = []
    import scripts.send_ping as sp
    monkeypatch.setattr(sp, "enqueue", lambda text, priority="normal": sent.append(text) or str(tmp_path / "p.json"))
    monkeypatch.delenv("UNIT_FAILURE_FORWARD", raising=False)
    bad = rdf.stale_rostered(_rows(), {"GDX"})
    assert rdf.alert([], tmp_path, 1.8e9) == "clean" and not sent
    assert rdf.alert(bad, tmp_path, 1.8e9) == "pinged" and len(sent) == 1 and "GDX_1d.csv" in sent[0]
    assert rdf.alert(bad, tmp_path, 1.8e9 + 3600) == "suppressed" and len(sent) == 1
    assert rdf.alert(bad, tmp_path, 1.8e9 + rdf.ALERT_COOLDOWN_S + 1) == "pinged" and len(sent) == 2


def test_main_alert_mode_never_gates(tmp_path, monkeypatch, capsys):
    import scripts.ops.report_data_freshness as rdf
    (tmp_path / "GDX_1d.csv").write_text("timestamp,open,high,low,close,volume\n2026-07-10,1,1,1,1,1\n2026-07-11,1,1,1,1,1\n")
    monkeypatch.setattr(rdf, "rostered_symbols", lambda repo=None: None)       # could not look
    assert rdf.main(["--data-dir", str(tmp_path), "--alert-rostered"]) == 0
    assert "rostered_symbols_unreadable" in capsys.readouterr().out


def test_stale_rostered_watches_the_legs_own_timeframe():
    import scripts.ops.report_data_freshness as rdf
    rows = _rows() + [
        {"file": "USO_1h.csv", "grain": "1h", "read_state": "ok", "last_bar": "2026-06-18T19:00:00+00:00", "stale": True},
        {"file": "SPY_15m.csv", "grain": "15m", "read_state": "ok", "last_bar": "2026-06-18", "stale": True},
    ]
    bad = rdf.stale_rostered(rows, {"USO": {"1h"}, "SPY": {"1h"}, "GDX": {"1d"}})
    # USO_1h (its leg's tf) and GDX_1d; SPY_15m is not a rostered tf, SPY_1d is fresh
    assert sorted(r["file"] for r in bad) == ["GDX_1d.csv", "USO_1h.csv"]


def test_stale_rostered_watches_the_file_the_resolver_reads(tmp_path):
    """A crypto 4h leg reads <SYM>_5m.csv (no native 4h file): that file must be watched (ML-10, 2026-11-19)."""
    (tmp_path / "ETHUSDT_5m.csv").write_text("timestamp,open,high,low,close,volume\n2026-06-18 19:00:00,1,1,1,1,1\n")
    (tmp_path / "ETHUSDT_15m.csv").write_text("timestamp,open,high,low,close,volume\n2026-06-18 19:00:00,1,1,1,1,1\n")
    now = datetime(2026, 11, 19, 6, tzinfo=timezone.utc)
    rows = rdf.report(tmp_path, now)
    syms = {"ETHUSDT": {"4h", "1d"}}
    assert rdf.stale_rostered(rows, syms) == []          # the exact-name match alone misses it
    read = rdf.resolved_files(syms, tmp_path)
    assert read == {"ETHUSDT_5m.csv"}                    # finest grain <= 4h, not the 15m file
    assert [r["file"] for r in rdf.stale_rostered(rows, syms, read)] == ["ETHUSDT_5m.csv"]
