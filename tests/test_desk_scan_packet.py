"""DESK-16-SCAN-PACKETS: the scan-packet builder (scripts/ops/desk_scan_packet.py)."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dsp", REPO / "scripts/ops/desk_scan_packet.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_self_test_passes():
    assert m._self_test() == 0


def _packet(bars, cutoff):
    return m.build_scan_packet(cutoff=cutoff, tf="1h", universe=[{"symbol": "ETHUSDT", "venue": "bybit", "classes": ["paper"]}],
                               candles={"ETHUSDT": bars}, horizons=(4,), lookback=200, system_book=[], desk_book=[],
                               built_at=cutoff)


def test_point_in_time_and_guard_valid():
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    bars = m._walk(400, 100.0, 1.0, t0, 3600)
    cut = datetime.fromtimestamp(t0 + 300 * 3600, tz=timezone.utc)
    p = _packet(bars, cut)
    assert m.validate(p) == []
    later = bars[:300] + [dict(b, close=b["close"] * 2) for b in bars[300:]]
    assert m.cdr.packet_sha(_packet(later, cut)) == m.cdr.packet_sha(p)


def test_read_only_no_order_path_imports():
    src = (REPO / "scripts/ops/desk_scan_packet.py").read_text()
    for banned in ("place_order", "multi_account_execute", "set-account-mode", "accounts.yaml\").write", "executor"):
        assert banned not in src


def test_masked_packet_leaks_no_identity():
    t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    p = _packet(m._walk(400, 2500.0, 10.0, t0, 3600), datetime.fromtimestamp(t0 + 300 * 3600, tz=timezone.utc))
    masked, key = m.mask_packet(p)
    blob = json.dumps(masked)
    assert "ETHUSDT" not in blob and "2026-" not in blob and m.validate(masked) == []
    assert key["alias"] == {"ASSET_01": "ETHUSDT"} and key["real_info_cutoff_at"].startswith("2026-")
    assert masked["meta"]["mode"] == "historical_masked"
    assert m.cdr.expected_training(dict(m.cdr.GOOD_ENTRY_DECISION, label_source="historical_masked"))[1] is False
