"""Oversized pings are SPLIT and delivered — never retried forever (TELEGRAM-CHANNELS,
manager 2026-10-11: one ~50h-old ping failed every 5 s in both drainers)."""
from __future__ import annotations

import asyncio
import json
import urllib.error

import pytest

from src.runtime import telegram_split as ts


def _plain_big(n_lines=400):
    return "\n".join(f"line {i:04d} " + "x" * 40 for i in range(n_lines))


def test_short_text_is_untouched():
    assert ts.split_message("hello", None) == ["hello"]


def test_oversize_plain_splits_on_lines_in_order_with_markers():
    text = _plain_big()
    parts = ts.split_message(text, None)
    assert len(parts) > 1 and all(len(p) <= ts.LIMIT for p in parts)
    n = len(parts)
    for i, p in enumerate(parts, 1):
        assert p.startswith(f"({i}/{n}) ")
    body = "\n".join(p.split(") ", 1)[1] for p in parts)
    assert body == text                                   # nothing lost, order kept


def test_a_single_overlong_line_is_hard_cut():
    parts = ts.split_message("y" * 10000, None)
    assert all(len(p) <= ts.LIMIT for p in parts) and len(parts) == 3


def test_oversize_html_splits_on_sections_and_every_part_parses():
    # the shape render_html emits (sections separated by blank lines)
    text = "\n\n".join(f"<b>S{i}</b>\n<blockquote expandable>" + "row &amp; data\n" * 60
                       + "</blockquote>" for i in range(12))
    assert len(text) > ts.LIMIT
    parts = ts.split_message(text, "HTML")
    assert len(parts) > 1
    for p in parts:
        assert len(p) <= ts.LIMIT
        assert ts._balanced(p), p[:80]
    assert "S0" in parts[0] and "S11" in parts[-1]


def test_an_unbalanced_html_block_degrades_to_escaped_plain():
    text = "<b>open\n\n" + "z <tag> & " * 600 + "\n\n</b>"
    parts = ts.split_message(text, "HTML")
    assert all(ts._balanced(p) and len(p) <= ts.LIMIT for p in parts)


def _ping(tmp_path, body, **extra):
    p = tmp_path / "823138194672-normal.json"
    p.write_text(json.dumps({"priority": "normal", "body": body, **extra}))
    return p


def test_the_stuck_file_case_is_delivered_then_deleted(tmp_path):
    path = _ping(tmp_path, _plain_big())
    payload = json.loads(path.read_text())
    sent = []
    out = ts.process_ping(path, payload, payload["body"], None,
                          lambda part: sent.append(part) or True, where="test")
    assert out == "sent" and len(sent) > 1
    assert [p.split(")")[0] for p in sent] == [f"({i}/{len(sent)}" for i in range(1, len(sent) + 1)]


def test_partial_failure_resumes_without_resending_delivered_parts(tmp_path):
    path = _ping(tmp_path, _plain_big())
    payload = json.loads(path.read_text())
    sent, calls = [], {"n": 0}

    def flaky(part):
        calls["n"] += 1
        if calls["n"] == 2:
            raise urllib.error.URLError("network down")      # transient
        sent.append(part)
        return True

    assert ts.process_ping(path, payload, payload["body"], None, flaky, where="t") == "retry"
    saved = json.loads(path.read_text())
    assert saved["_parts_sent"] == 1 and "_client_errors" not in saved
    assert ts.process_ping(path, saved, saved["body"], None, flaky, where="t") == "sent"
    assert len(sent) == len(set(sent)) == len(ts.split_message(saved["body"], None))


def test_non_length_4xx_moves_aside_as_broken_with_one_red_flag(tmp_path, monkeypatch):
    path = _ping(tmp_path, "short body")
    flags = []
    monkeypatch.setattr(ts, "red_flag_broken", lambda *a: flags.append(a))

    def refuse(_part):
        raise urllib.error.HTTPError("u", 403, "Forbidden", None, None)

    outcomes = []
    for _ in range(ts.MAX_CLIENT_ERRORS):
        payload = json.loads(path.read_text())
        outcomes.append(ts.process_ping(path, payload, payload["body"], None, refuse, where="t"))
    assert outcomes == ["retry"] * (ts.MAX_CLIENT_ERRORS - 1) + ["broken"]
    assert not path.exists() and (tmp_path / (path.name + ".broken")).exists()
    assert len(flags) == 1


def test_transient_errors_never_break_a_file(tmp_path, monkeypatch):
    path = _ping(tmp_path, "short")
    monkeypatch.setattr(ts, "red_flag_broken", lambda *a: pytest.fail("no flag on transient"))
    for code in (429, 500, 502):
        for _ in range(ts.MAX_CLIENT_ERRORS + 2):
            payload = json.loads(path.read_text())

            def fail(_p, code=code):
                raise urllib.error.HTTPError("u", code, "x", None, None)
            assert ts.process_ping(path, payload, payload["body"], None, fail, where="t") == "retry"
    assert path.exists()


def test_classify_ptb_errors_by_name():
    BadRequest = type("BadRequest", (Exception,), {})
    TimedOut = type("TimedOut", (Exception,), {})
    assert ts.classify_error(BadRequest("Message is too long")) == "client"
    assert ts.classify_error(TimedOut()) == "transient"


def test_failover_drainer_delivers_an_oversized_ping_in_parts(tmp_path):
    from src.bot import cloud_notifier

    _ping(tmp_path, _plain_big())
    sent = []

    class Bot:
        async def send_message(self, chat_id, text, parse_mode=None, disable_web_page_preview=True):
            assert len(text) <= ts.LIMIT
            sent.append(text)

    asyncio.run(cloud_notifier._drain_one_ping_dir(None, "123", str(tmp_path), bot=Bot()))
    assert len(sent) > 1 and not list(tmp_path.glob("*.json"))


def test_enqueue_fits_at_write_time(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_send_ping_t", root / "scripts/send_ping.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_inbox_for", lambda target: tmp_path)
    first = mod.enqueue(_plain_big(), target="claude")
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) > 1 and files[0] == first
    for f in files:
        assert len(json.loads(f.read_text())["body"]) <= ts.LIMIT
    assert mod.enqueue("small", target="claude").name.count("-p") == 0
