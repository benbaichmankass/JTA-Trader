"""TELEGRAM-CHANNELS: every Telegram sender is mapped to exactly one channel,
and no alert path becomes unrouted by the 3-channel re-plumb (operator
2026-10-11: "it relates to operational stability, not just UI")."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src.runtime import telegram_channels as tc

REPO = Path(__file__).resolve().parents[1]

#: Every way this repo puts a message on Telegram. A file containing one of
#: these IS a sender and must be in ``telegram_channels.SENDERS``.
PRIMITIVES = re.compile(
    r"send_telegram_direct\b|send_to_operator\(|send_via_alert_manager\b|"
    r"notify_operator\(|api\.telegram\.org|\.send_message\(|"
    r"\"pending_(claude_)?pings\"|send_ping import|scripts\.send_ping|"
    r"send_ping\.py|execution_diagnostics import \(?\s*enqueue_|telegram_channels\.send\("
)

#: Files that name an inbox only to READ it (observability), never to send.
READERS = {"src/web/api/routers/diag.py"}


def _tracked(*roots: str) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", *roots], cwd=REPO, text=True)
    return [f for f in out.split() if f.endswith((".py", ".sh", ".yml"))]


def _senders_on_disk() -> set[str]:
    hits = set()
    for f in _tracked("src", "scripts", ".github/workflows"):
        if f.startswith("scripts/") and "/tests/" in f:
            continue
        try:
            text = (REPO / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if f.endswith(".yml") and "api.telegram.org" not in text:
            continue  # a workflow is a sender only if it POSTs to Telegram itself
        if PRIMITIVES.search(text):
            hits.add(f)
    return hits - READERS


def test_every_sender_is_mapped():
    on_disk = _senders_on_disk()
    unmapped = sorted(on_disk - set(tc.SENDERS))
    assert not unmapped, (
        f"{len(unmapped)} Telegram sender(s) not in telegram_channels.SENDERS: "
        f"{unmapped} — map each to its event kind(s)")


def test_no_stale_sender_entries():
    stale = sorted(f for f in tc.SENDERS if not (REPO / f).exists())
    assert not stale, f"SENDERS names files that no longer exist: {stale}"


def test_every_sender_kind_is_routed():
    bad = {f: k for f, ks in tc.SENDERS.items() for k in ks if k not in tc.EVENT_CHANNEL}
    assert not bad, f"kinds with no channel: {bad}"


def test_every_kind_maps_to_exactly_one_known_channel():
    allowed = set(tc.CHANNELS) | {tc.RETIRED, tc.REPLY}
    assert all(ch in allowed for ch in tc.EVENT_CHANNEL.values())


def test_alerts_route_to_system_and_are_never_retired_or_muteable():
    for k in ("alert", "execution_alert", "prop_alert", "red_flag", "restart",
              "hourly_report", "pipeline_result"):
        assert tc.channel_for(k) == tc.SYSTEM, k
    for k in tc.UNMUTABLE:
        assert not tc.mutable(k), k
        assert tc.EVENT_CHANNEL[k] not in (tc.RETIRED, tc.REPLY), k


def test_retired_kinds_are_only_the_prop_prompts():
    retired = {k for k, c in tc.EVENT_CHANNEL.items() if c == tc.RETIRED}
    assert retired == {"prop_ticket", "prop_expiry_prompt", "prop_expiry_notice",
                       "prop_invalidation_prompt"}


def test_trade_lifecycle_routes_to_trades():
    for k in ("trade_opened", "trade_closed", "trade_updated", "trade-open",
              "trade-close", "trade-update", "prop_fill", "prop_monitor"):
        assert tc.channel_for(k) == tc.TRADES, k


def test_manager_kinds():
    for k in ("manager_update", "claude_ping", "decision", "pr_merged", "session"):
        assert tc.channel_for(k) == tc.MANAGER, k


def test_unknown_kind_is_system_never_nowhere():
    assert tc.channel_for("some-new-kind-nobody-mapped") == tc.SYSTEM


def test_trades_and_manager_senders_actually_use_their_channel():
    """A file mapped ONLY to TRADES/MANAGER must route through the table (or the
    manager inbox); one mapped only to SYSTEM must not send to the Claude inbox."""
    for f, kinds in tc.SENDERS.items():
        chans = {tc.EVENT_CHANNEL[k] for k in kinds}
        text = (REPO / f).read_text(encoding="utf-8")
        if chans == {tc.TRADES}:
            assert "telegram_channels" in text, f
        if chans == {tc.SYSTEM} and f.endswith(".sh"):
            assert "--target claude" not in text, f


ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_PROP_TRADE_BOT",
       "TELEGRAM_PROP_BOT_TOKEN", "TELEGRAM_CLAUDE_BOT_TOKEN",
       "TELEGRAM_CLAUDE_BOT_SECRET", "TELEGRAM_CLAUDE_CHAT_ID",
       "TELEGRAM_PROP_CHAT_ID", "TELEGRAM_SYSTEM_CHAT_ID")


@pytest.fixture
def env(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "sys-tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "op")
    return monkeypatch


def _capture(monkeypatch, fail_tokens=()):
    sent = []

    def fake(text, *, parse_mode=None, mirror_to_fcm=True, bot_token=None,
             chat_id=None, reply_markup=None):
        if bot_token in fail_tokens:
            raise RuntimeError("boom")
        sent.append((bot_token, chat_id, text))
        return True

    monkeypatch.setattr("src.runtime.notify.send_telegram_direct", fake)
    return sent


def test_send_routes_each_channel_to_its_bot(env):
    env.setenv("TELEGRAM_PROP_TRADE_BOT", "trades-tok")
    env.setenv("TELEGRAM_CLAUDE_BOT_SECRET", "mgr-tok")
    sent = _capture(env)
    assert tc.send("trade_opened", "o")
    assert tc.send("alert", "a")
    assert tc.send("decision", "d")
    assert [s[0] for s in sent] == ["trades-tok", "sys-tok", "mgr-tok"]


def test_undeliverable_channel_falls_back_to_system(env):
    sent = _capture(env)  # no trades / manager token at all
    assert tc.send("trade_closed", "c")
    assert sent[0][0] == "sys-tok"


def test_failed_channel_send_is_retried_on_system_not_lost(env):
    env.setenv("TELEGRAM_PROP_TRADE_BOT", "trades-tok")
    sent = _capture(env, fail_tokens=("trades-tok",))
    assert tc.send("trade_opened", "hello")
    assert sent == [("sys-tok", "op", "[meant for TRADES] hello")]


def test_system_failure_propagates(env):
    _capture(env, fail_tokens=("sys-tok",))
    with pytest.raises(RuntimeError):
        tc.send("alert", "x")


def test_retired_kind_is_refused(env):
    sent = _capture(env)
    assert tc.send("prop_ticket", "t") is False
    assert sent == []


def test_trade_ping_payload_carries_trades_channel(tmp_path, monkeypatch):
    from src.runtime import execution_diagnostics as ed

    monkeypatch.setattr(ed, "PENDING_PINGS_DIR", tmp_path)
    p = ed.enqueue_trade_open(account="a", strategy="s", symbol="BTCUSDT",
                              side="long", qty=1.0)
    payload = json.loads(Path(p).read_text())
    assert payload["channel"] == "trades" and payload["kind"] == "trade-open"


def test_drainer_delivers_trades_ping_on_trades_bot(env, tmp_path):
    import asyncio

    from src.bot import cloud_notifier as cn

    env.setenv("TELEGRAM_PROP_TRADE_BOT", "trades-tok")
    sent = _capture(env)
    (tmp_path / "1-trade-open.json").write_text(json.dumps(
        {"priority": "normal", "body": "<b>T</b>", "parse_mode": "HTML",
         "kind": "trade-open", "channel": "trades"}))
    (tmp_path / "2-x.json").write_text(json.dumps({"priority": "high", "body": "alert"}))

    bot_sent = []

    class Bot:
        async def send_message(self, **kw):
            bot_sent.append(kw["text"])

    class Ctx:
        bot = Bot()

    asyncio.run(cn._drain_one_ping_dir(Ctx(), "op", str(tmp_path)))
    assert [s[0] for s in sent] == ["trades-tok"]
    assert len(bot_sent) == 1 and "alert" in bot_sent[0]
    assert list(tmp_path.glob("*.json")) == []


def test_drainer_falls_back_to_own_bot_when_trades_send_fails(env, tmp_path):
    import asyncio

    from src.bot import cloud_notifier as cn

    env.setenv("TELEGRAM_PROP_TRADE_BOT", "trades-tok")
    _capture(env, fail_tokens=("trades-tok",))
    (tmp_path / "1-trade-open.json").write_text(json.dumps(
        {"priority": "normal", "body": "T", "kind": "trade-open", "channel": "trades"}))
    bot_sent = []

    class Bot:
        async def send_message(self, **kw):
            bot_sent.append(kw["text"])

    class Ctx:
        bot = Bot()

    asyncio.run(cn._drain_one_ping_dir(Ctx(), "op", str(tmp_path)))
    assert len(bot_sent) == 1  # delivered on SYSTEM, not lost


def test_manual_flow_prompts_are_not_sent_by_default(env):
    from src.prop import breakout_notify as bn

    sent = _capture(env)
    t = {"ticket_id": "t1", "account_id": None, "symbol": "X", "direction": "long"}
    assert bn.emit_prop_expiry_prompt(t) is False
    assert bn.emit_prop_expiry_notice(t) is False
    assert sent == []
