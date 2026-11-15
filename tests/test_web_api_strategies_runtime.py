"""GET /api/bot/strategies — live-runtime enrichment tests.

Pins the fields that make the Strategies tab reflect what the bot is
ACTUALLY running (not just static YAML):
  * ``loaded`` — strategy is in runtime_status.json `strategies`.
  * ``running`` — loaded AND the last tick is fresh.
  * ``accounts`` — routing from accounts.yaml + per-account live/dry.
  * top-level ``runtime`` block (bot_running, tick age, loaded set).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path / "runtime_logs"))
    (tmp_path / "runtime_logs").mkdir(parents=True, exist_ok=True)

    from src.web.api import main as api_main
    from src.web.api.routers import strategies as sr

    monkeypatch.setattr(sr, "_STRATEGIES_YAML", tmp_path / "strategies.yaml")
    monkeypatch.setattr(sr, "_ACCOUNTS_YAML", tmp_path / "accounts.yaml")
    monkeypatch.setattr(sr, "_CHANGELOG_JSON", tmp_path / "changelog.json")
    monkeypatch.setattr(sr, "_DB_PATH", tmp_path / "absent.db")

    (tmp_path / "strategies.yaml").write_text(yaml.safe_dump({
        "strategies": {
            "vwap": {"enabled": True, "risk_pct": 1.0, "timeframe": "5m", "symbols": ["BTCUSDT"]},
            "ict_scalp_5m": {"enabled": True, "risk_pct": 0.3, "timeframe": "5m"},
        }
    }), encoding="utf-8")
    (tmp_path / "accounts.yaml").write_text(yaml.safe_dump({
        "accounts": {
            "bybit_1": {"strategies": ["vwap", "ict_scalp_5m"]},
            "bybit_2": {"strategies": ["vwap"]},
        }
    }), encoding="utf-8")

    client = TestClient(api_main.app, raise_server_exceptions=False)
    return client, tmp_path


def _write_status(tmp_path: Path, strategies, live, last_tick) -> None:
    (tmp_path / "runtime_logs" / "runtime_status.json").write_text(
        json.dumps({"strategies": strategies, "live": live, "last_tick_utc": last_tick}),
        encoding="utf-8",
    )


def test_running_when_loaded_and_fresh(setup):
    client, tmp_path = setup
    _write_status(tmp_path, ["vwap", "ict_scalp_5m"],
                  {"bybit_1": True, "bybit_2": False}, _now_iso())
    body = client.get("/api/bot/strategies").json()
    assert body["runtime"]["bot_running"] is True
    by_name = {s["name"]: s for s in body["strategies"]}
    assert by_name["vwap"]["loaded"] is True
    assert by_name["vwap"]["running"] is True
    # accounts routing + per-account live/dry
    accts = {a["id"]: a["live"] for a in by_name["vwap"]["accounts"]}
    assert accts == {"bybit_1": True, "bybit_2": False}
    assert by_name["ict_scalp_5m"]["accounts"] == [{"id": "bybit_1", "live": True}]


def test_not_running_when_tick_stale(setup):
    client, tmp_path = setup
    _write_status(tmp_path, ["vwap"], {"bybit_1": True}, "2020-01-01T00:00:00Z")
    body = client.get("/api/bot/strategies").json()
    assert body["runtime"]["bot_running"] is False
    by_name = {s["name"]: s for s in body["strategies"]}
    # loaded reflects the status file; running is gated on freshness.
    assert by_name["vwap"]["loaded"] is True
    assert by_name["vwap"]["running"] is False


def test_not_loaded_when_absent_from_status(setup):
    client, tmp_path = setup
    _write_status(tmp_path, ["vwap"], {}, _now_iso())
    body = client.get("/api/bot/strategies").json()
    by_name = {s["name"]: s for s in body["strategies"]}
    assert by_name["ict_scalp_5m"]["loaded"] is False
    assert by_name["ict_scalp_5m"]["running"] is False


def test_missing_status_file_degrades(setup):
    client, _ = setup  # no runtime_status.json written
    body = client.get("/api/bot/strategies").json()
    assert body["runtime"]["bot_running"] is False
    assert all(s["running"] is False for s in body["strategies"])
    # endpoint still returns the configured strategies
    assert {s["name"] for s in body["strategies"]} == {"vwap", "ict_scalp_5m"}


def test_strategies_carry_derived_status_and_books(setup):
    """UI-MODELS-STRATEGIES-TABLES: status is DERIVED (strategy_status rule), books = rosters carrying the leg."""
    client, tmp_path = setup
    (tmp_path / "strategies.yaml").write_text(yaml.safe_dump({"strategies": {
        "vwap": {"enabled": True}, "ict_scalp_5m": {"enabled": True}, "old_leg": {"enabled": False},
        "orphan_leg": {"enabled": True}}}), encoding="utf-8")
    (tmp_path / "accounts.yaml").write_text(yaml.safe_dump({"accounts": {
        "bybit_1": {"strategies": ["vwap", "ict_scalp_5m", "old_leg"]},
        "bybit_2": {"strategies": ["vwap"]}, "bybit_portfolio": {"strategies": ["vwap"]}}}), encoding="utf-8")
    rows = {s["name"]: s for s in client.get("/api/bot/strategies").json()["strategies"]}
    assert rows["vwap"]["status"] == "production" and rows["vwap"]["books"] == ["bybit_1", "bybit_2", "bybit_portfolio"]
    assert rows["ict_scalp_5m"]["status"] == "testing" and rows["ict_scalp_5m"]["books"] == ["bybit_1"]
    assert rows["old_leg"]["status"] == "inactive"                       # retirement marker wins over a roster entry
    assert rows["orphan_leg"]["status"] == "testing" and rows["orphan_leg"]["books"] == []
    assert all(r["status_read_state"] == "measured" for r in rows.values())
    from scripts.ops import strategy_status as ss                          # the cross-check: same rule, same answers
    ros = ss.rosters(yaml.safe_load((tmp_path / "accounts.yaml").read_text())["accounts"])
    cfg = yaml.safe_load((tmp_path / "strategies.yaml").read_text())["strategies"]
    assert {n: r["status"] for n, r in rows.items()} == {n: ss.status_of(n, ros, cfg) for n in cfg}


def test_strategies_status_unreadable_is_null_not_a_guess(setup, monkeypatch):
    client, _tmp = setup
    from scripts.ops import strategy_status as ss
    monkeypatch.setattr(ss, "rosters", lambda a: (_ for _ in ()).throw(RuntimeError("boom")))
    rows = client.get("/api/bot/strategies").json()["strategies"]
    assert rows and all(r["status"] is None and r["books"] is None and r["status_read_state"] == "unreadable" for r in rows)
