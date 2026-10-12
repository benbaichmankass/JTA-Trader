# FU-20260515-001: pin market_type wiring in _build_account_client so the
# vwap_cross close path doesn't send spot reduceOnly to linear (Bybit 170131).
from unittest.mock import MagicMock

from src.runtime import order_monitor


def test_build_account_client_populates_market_type_for_linear_account(monkeypatch):
    """FU-20260515-001 regression: closes on a linear Bybit account must
    carry market_type=linear so execute.py doesn't fall back to spot (170131)."""
    fake_acc = MagicMock()
    fake_acc.name = "bybit_2"
    fake_acc.exchange = "bybit"
    fake_acc.api_key_env = "BYBIT_API_KEY_2"
    fake_acc.market_type = "linear"

    dummy_client = MagicMock()

    monkeypatch.setattr(
        "src.units.accounts.load_accounts", lambda: [fake_acc]
    )
    monkeypatch.setattr(
        "src.units.accounts.clients.bybit_client_for",
        lambda cfg: dummy_client,
    )

    client, cfg = order_monitor._build_account_client("bybit_2")

    assert cfg["market_type"] == "linear"
    assert cfg["account_id"] == "bybit_2"
    # MagicMock() fabricates .dry_run (not True) -> must read as live, never as
    # a fabricated child Mock (_account_mode uses `is True`).
    assert cfg["mode"] == "live"
    assert client is not None


def test_build_account_client_defaults_market_type_to_spot_when_attribute_missing(monkeypatch):
    """Legacy account fixtures without market_type must still produce a cfg
    with market_type='spot' (defensive fallback for FU-20260515-001)."""
    fake_acc = MagicMock(spec=["name", "exchange", "api_key_env"])
    fake_acc.name = "bybit_legacy"
    fake_acc.exchange = "bybit"
    fake_acc.api_key_env = "BYBIT_API_KEY_LEGACY"

    dummy_client = MagicMock()

    monkeypatch.setattr(
        "src.units.accounts.load_accounts", lambda: [fake_acc]
    )
    monkeypatch.setattr(
        "src.units.accounts.clients.bybit_client_for",
        lambda cfg: dummy_client,
    )

    _client, cfg = order_monitor._build_account_client("bybit_legacy")

    assert cfg["market_type"] == "spot"
    # spec has neither .dry_run nor .mode -> default applies.
    assert cfg["mode"] == "live"


def _real_account(name, dry_run):
    from src.units.accounts.account import TradingAccount
    return TradingAccount(
        name=name, exchange="bybit", api_key_env="BYBIT_API_KEY_X",
        risk_manager=MagicMock(), dry_run=dry_run, market_type="linear",
    )


def test_build_account_client_reports_dry_run_for_a_real_dry_run_account(monkeypatch):
    """CA-A04 / PI-20260927-JT7JW9CR-0004: TradingAccount has no ``.mode``; a
    reader of ``getattr(acc, "mode", "live")`` resolved every account to live.
    A REAL TradingAccount(dry_run=True) must surface as cfg['mode']=='dry_run'."""
    acc = _real_account("bybit_dry", True)
    assert not hasattr(acc, "mode")  # the premise of the original bug
    monkeypatch.setattr("src.units.accounts.load_accounts", lambda: [acc])
    monkeypatch.setattr(
        "src.units.accounts.clients.bybit_client_for", lambda cfg: MagicMock())
    _client, cfg = order_monitor._build_account_client("bybit_dry")
    assert cfg["mode"] == "dry_run"


def test_build_account_client_reports_live_for_a_real_live_account(monkeypatch):
    acc = _real_account("bybit_live", False)
    monkeypatch.setattr("src.units.accounts.load_accounts", lambda: [acc])
    monkeypatch.setattr(
        "src.units.accounts.clients.bybit_client_for", lambda cfg: MagicMock())
    _client, cfg = order_monitor._build_account_client("bybit_live")
    assert cfg["mode"] == "live"
