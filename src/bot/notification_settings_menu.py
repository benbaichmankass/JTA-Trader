"""ONE settings-menu component, mounted in all three channel bots.

TELEGRAM-CHANNELS part C (operator, 2026-10-11): each channel's menu has a
settings button to toggle notification TYPES and set the CADENCE of every
periodic update (hourly / every 4h / twice a day / once a day / off). Cadence
is per channel / per update; the mechanism is shared: the store and the gate
are ``src/runtime/telegram_settings.py``, the menu is this module, and each bot
mounts it with :func:`register` — the same ``/settings`` command and the same
``ns:`` callback prefix everywhere.

Which bot is which channel (the process that POLLS it):

* SYSTEM  — ``ict-telegram-bot``          (``src/bot/telegram_query_bot.py``)
* TRADES  — ``ict-claude-bridge``         (``src/bot/claude_bridge.py``, the prop bot)
* MANAGER — ``ict-claude-decision-bot``   (``src/bot/claude_decision_bot.py``)

Alert / red-flag / decision kinds (``telegram_channels.UNMUTABLE``) are shown
as locked and have no button: they cannot be muted from here, and the store
refuses them too.

The pure half (:func:`render`, :func:`apply`) takes no Telegram objects so it
is tested without python-telegram-bot.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

CB_PREFIX = "ns"
_CH_TITLE = {"system": "SYSTEM", "trades": "TRADES", "manager": "MANAGER"}
_CHOICE_SHORT = {"1h": "1h", "4h": "4h", "12h": "2×/day", "24h": "1×/day", "off": "off"}


def _btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def render(channel: str) -> tuple[str, dict]:
    """``(text, reply_markup)`` for *channel*'s settings menu."""
    from src.runtime import telegram_channels as tc
    from src.runtime import telegram_settings as ts

    if channel not in _CH_TITLE:
        raise ValueError(f"unknown channel {channel!r}")
    st = ts.load()
    lines = [f"⚙️ <b>{_CH_TITLE[channel]} notification settings</b>"]
    if st["read_state"] == "unreadable":
        lines.append("⚠️ settings file unreadable — showing defaults (everything on, hourly)")
    rows: list[list[dict]] = []
    for update, (ch, name) in ts.PERIODIC.items():
        if ch != channel:
            continue
        cur = ts.cadence(update)
        lines.append(f"🕒 {name}: <b>{ts.CADENCE_LABELS[cur]}</b>")
        rows.append([_btn(("• " if c == cur else "") + _CHOICE_SHORT[c],
                          f"{CB_PREFIX}:c:{update}:{c}") for c in ts.CADENCES])
    for group, (label, _kinds) in ts.TOGGLES.get(channel, {}).items():
        muted = ts.group_muted(channel, group)
        rows.append([_btn(f"{'🔕' if muted else '✅'} {label}",
                          f"{CB_PREFIX}:t:{channel}:{group}")])
    locked = sorted(k for k in tc.UNMUTABLE if tc.EVENT_CHANNEL.get(k) == channel)
    if locked:
        lines.append("🔒 always on (cannot be muted): " + ", ".join(locked))
    lines.append("Tap a cadence to change it; tap a type to toggle it.")
    rows.append([_btn("↻ Refresh", f"{CB_PREFIX}:open:{channel}")])
    return "\n".join(lines), {"inline_keyboard": rows}


def apply(data: str, *, by: str) -> tuple[str, str]:
    """Apply a ``ns:`` callback. Returns ``(channel, toast)``. Raises
    ValueError on anything malformed or refused (the bot shows the reason)."""
    from src.runtime import telegram_settings as ts

    parts = str(data or "").split(":")
    if len(parts) < 3 or parts[0] != CB_PREFIX:
        raise ValueError("not a settings callback")
    op = parts[1]
    if op == "open" and parts[2] in _CH_TITLE:
        return parts[2], "refreshed"
    if op == "c" and len(parts) == 4:
        update, choice = parts[2], parts[3]
        if update not in ts.PERIODIC:
            raise ValueError(f"unknown update {update!r}")
        ts.set_cadence(update, choice, by=by)
        ch, name = ts.PERIODIC[update]
        return ch, f"{name}: {ts.CADENCE_LABELS[choice]}"
    if op == "t" and len(parts) == 4:
        ch, group = parts[2], parts[3]
        if group not in ts.TOGGLES.get(ch, {}):
            raise ValueError(f"unknown type {group!r} for {ch!r}")
        now_muted = not ts.group_muted(ch, group)
        ts.set_group_muted(ch, group, now_muted, by=by)
        return ch, f"{ts.TOGGLES[ch][group][0]}: {'off' if now_muted else 'on'}"
    raise ValueError("malformed settings callback")


def settings_button(channel: str) -> dict:
    """The ⚙️ button other menus embed to open this one."""
    return _btn("⚙️ Settings", f"{CB_PREFIX}:open:{channel}")


# ── python-telegram-bot glue ───────────────────────────────────────────────

def _authorized(update: Any) -> bool:
    allowed = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    chat = getattr(update, "effective_chat", None)
    return bool(allowed) and chat is not None and str(chat.id) == allowed


def _markup(m: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton(b["text"], callback_data=b["callback_data"])
                                  for b in row] for row in m["inline_keyboard"]])


def register(app: Any, channel: str, *, service: Optional[str] = None) -> None:
    """Mount ``/settings`` + the ``ns:`` callback on *app*. Call BEFORE the
    bot's catch-all ``CallbackQueryHandler`` so ``ns:`` taps reach this one."""
    from telegram.ext import CallbackQueryHandler, CommandHandler

    async def settings_cmd(update, _ctx) -> None:
        if not _authorized(update):
            return
        text, m = render(channel)
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=_markup(m))

    async def on_cb(update, _ctx) -> None:
        q = update.callback_query
        if not _authorized(update):
            await q.answer("not authorised")
            return
        try:
            ch, toast = apply(q.data, by=f"telegram:{service or channel}")
        except ValueError as exc:
            await q.answer(str(exc)[:190], show_alert=True)
            return
        text, m = render(ch)
        await q.answer(toast[:190])
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=_markup(m))
        except Exception as exc:  # noqa: BLE001 — "message is not modified" etc.
            logger.info("settings menu: edit skipped (%s)", type(exc).__name__)

    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(on_cb, pattern=rf"^{CB_PREFIX}:"))
