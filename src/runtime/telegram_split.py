"""ONE helper for Telegram's 4096-char cap, shared by both ping drainers and the
enqueue path — so an oversized ping is SPLIT and delivered, never retried forever.

Measured live 2026-10-11 (manager, checklist row ``TELEGRAM-CHANNELS``):
``pending_claude_pings/823138194672-normal.json`` (~50h old) failed every 5 s in
BOTH drainers — ``claude_bridge._drain_pending_claude_pings`` ("HTTP Error 400:
Bad Request") and ``cloud_notifier._drain_one_ping_dir`` ("Message is too
long") — ~660 failures/hour, never delivered, never moved aside.

What this module guarantees:

* :func:`split_message` — every returned part is <= ``limit`` chars. Plain text
  splits on LINE boundaries (a single over-long line is hard-cut). HTML splits
  on BLOCK boundaries (blank lines — the section boundaries ``render_html``
  emits); a part whose tags would not balance is sent as escaped plain text
  instead, so a split can never produce an unparseable entity. Parts carry
  ``(i/n)`` markers in order.
* :func:`deliver` — sends parts in order from a resume index, so a failure
  half-way re-sends only the undelivered parts (no duplicates of delivered
  ones). Returns how far it got and how the failure classifies.
* :func:`classify_error` — ``client`` (a non-429 4xx: retrying the same bytes
  cannot succeed) vs ``transient`` (network, 5xx, 429 — retry). A ``client``
  failure is counted by the drainer and, after :data:`MAX_CLIENT_ERRORS`, the
  file is moved aside as ``.broken`` with ONE red flag on SYSTEM — no infinite
  loop, and no silent drop.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

LIMIT = 4096
#: room for the "(i/n) " marker and a drainer's priority-icon prefix
_RESERVE = 24
MAX_CLIENT_ERRORS = 5
_TAGS = ("b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre",
         "a", "blockquote", "tg-spoiler", "span")


def _balanced(s: str) -> bool:
    for t in _TAGS:
        opens = len(re.findall(rf"<{t}(\s[^>]*)?>", s))
        closes = s.count(f"</{t}>")
        if opens != closes:
            return False
    return True


def _plain(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def _pack_lines(text: str, cap: int) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > cap:                      # one line longer than a part
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:cap])
            line = line[cap:]
        cand = f"{cur}\n{line}" if cur else line
        if len(cand) > cap:
            out.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def _pack_html(text: str, cap: int) -> list[str]:
    out, cur = [], ""
    for block in text.split("\n\n"):
        if len(block) > cap or not _balanced(block):
            if cur:
                out.append(cur)
                cur = ""
            # an over-long or unbalanced block: escaped plain text, line-split
            out += [html.escape(p, quote=False) for p in _pack_lines(_plain(block), cap - 64)]
            continue
        cand = f"{cur}\n\n{block}" if cur else block
        if len(cand) > cap:
            out.append(cur)
            cur = block
        else:
            cur = cand
    if cur:
        out.append(cur)
    # escaping can lengthen a plain part; re-cut anything still over the cap
    fixed = []
    for p in out:
        fixed += [p] if len(p) <= cap else [html.escape(x, quote=False)
                                            for x in _pack_lines(_plain(p), cap // 2)]
    return fixed


def split_message(text: str, parse_mode: Optional[str] = None,
                  limit: int = LIMIT) -> list[str]:
    """``text`` as an ordered list of parts, each <= ``limit`` chars."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    cap = limit - _RESERVE
    is_html = str(parse_mode or "").upper() == "HTML"
    parts = _pack_html(text, cap) if is_html else _pack_lines(text, cap)
    parts = [p for p in parts if p.strip()]
    n = len(parts)
    return [f"({i}/{n}) {p}" for i, p in enumerate(parts, 1)]


def classify_error(exc: BaseException) -> str:
    """``client`` = a non-429 4xx (the same request can never succeed);
    ``transient`` = anything else (network, 5xx, 429, unknown) — retry."""
    code = getattr(exc, "code", None)                       # urllib HTTPError
    if isinstance(code, int):
        return "client" if 400 <= code < 500 and code != 429 else "transient"
    name = type(exc).__name__                               # python-telegram-bot
    if name in ("BadRequest", "Forbidden", "InvalidToken", "ChatMigrated"):
        return "client"
    return "transient"


def deliver(send: Callable[[str], Any], parts: list[str], start: int = 0
            ) -> tuple[int, Optional[BaseException]]:
    """Send ``parts[start:]`` in order with ``send(part)`` (truthy = confirmed).
    Returns ``(next_index, error)``: ``next_index == len(parts)`` means all
    delivered; otherwise ``error`` is what stopped it (``None`` for an
    unconfirmed send, e.g. missing credentials)."""
    i = start
    while i < len(parts):
        try:
            ok = send(parts[i])
        except Exception as exc:  # noqa: BLE001 — classified by the caller
            return i, exc
        if not ok:
            return i, None
        i += 1
    return i, None


async def deliver_async(send, parts: list[str], start: int = 0
                        ) -> tuple[int, Optional[BaseException]]:
    """:func:`deliver` for an ``async`` sender (PTB ``bot.send_message``)."""
    i = start
    while i < len(parts):
        try:
            ok = await send(parts[i])
        except Exception as exc:  # noqa: BLE001
            return i, exc
        if not ok:
            return i, None
        i += 1
    return i, None


def red_flag_broken(name: str, where: str, exc: BaseException, attempts: int) -> None:
    """ONE red flag on SYSTEM for a ping moved aside as ``.broken``. Never raises."""
    msg = (f"🚩 Telegram ping moved aside as .broken after {attempts} client-error "
           f"attempts: {name} ({where}) — {type(exc).__name__}: {str(exc)[:200]}. "
           "It was NOT delivered; the file is kept for inspection.")
    try:
        from src.runtime import telegram_channels

        telegram_channels.send("red_flag", msg, parse_mode=None)
    except Exception as e:  # noqa: BLE001 — the .broken file + this log remain
        logger.error("telegram_split: red flag for %s could not be sent: %s", name, e)


# ── the per-file step both drainers share ─────────────────────────────────

def _rewrite(path, payload: dict) -> None:
    import json
    import os

    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _settle(path, payload: dict, parts: list[str], nxt: int,
            err: Optional[BaseException], where: str) -> str:
    """Record the outcome on the file. Returns ``sent`` (all parts delivered —
    the caller deletes), ``retry`` (left in place, progress saved) or
    ``broken`` (moved aside, one red flag)."""
    import os

    if nxt >= len(parts):
        return "sent"
    payload["_parts_sent"] = nxt
    if err is not None and classify_error(err) == "client":
        payload["_client_errors"] = int(payload.get("_client_errors") or 0) + 1
        if payload["_client_errors"] >= MAX_CLIENT_ERRORS:
            name = os.path.basename(str(path))
            try:
                _rewrite(path, payload)
                os.rename(path, f"{path}.broken")
            except OSError:
                pass
            logger.error("ping inbox: %s moved aside as .broken after %d client errors (%s)",
                         name, payload["_client_errors"], where)
            red_flag_broken(name, where, err, payload["_client_errors"])
            return "broken"
    try:
        _rewrite(path, payload)
    except OSError:
        pass
    return "retry"


def process_ping(path, payload: dict, text: str, parse_mode: Optional[str],
                 send: Callable[[str], Any], where: str) -> str:
    """Split *text*, deliver from the saved resume index, settle the file."""
    parts = split_message(text, parse_mode)
    start = min(int(payload.get("_parts_sent") or 0), len(parts))
    nxt, err = deliver(send, parts, start)
    if err is not None:
        logger.warning("ping inbox: %s part %d/%d failed via %s — %s",
                       path, nxt + 1, len(parts), where, err)
    return _settle(path, payload, parts, nxt, err, where)


async def process_ping_async(path, payload: dict, text: str, parse_mode: Optional[str],
                             send, where: str) -> str:
    parts = split_message(text, parse_mode)
    start = min(int(payload.get("_parts_sent") or 0), len(parts))
    nxt, err = await deliver_async(send, parts, start)
    if err is not None:
        logger.warning("ping inbox: %s part %d/%d failed via %s — %s",
                       path, nxt + 1, len(parts), where, err)
    return _settle(path, payload, parts, nxt, err, where)
