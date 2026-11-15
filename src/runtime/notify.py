from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


def send_telegram_direct(
    message: str,
    *,
    parse_mode: Optional[str] = "HTML",
    mirror_to_fcm: bool = True,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    reply_markup: Optional[dict] = None,
    kind: Optional[str] = None,
    channel: Optional[str] = None,
    priority: Optional[str] = None,
    dedup_key: Optional[str] = None,
) -> bool:
    """Send via Telegram and record the outcome in the alert ledger.

    ``kind`` / ``channel`` / ``priority`` / ``dedup_key`` are optional LEDGER
    labels (``telegram_channels.send`` passes them); an unlabelled caller is
    recorded as ``kind="unclassified"``. The ledger append is a best-effort
    side-write (``src.runtime.alerts_ledger``): it never changes what is sent,
    what is returned or what is raised. See ``_send_telegram_direct`` for the
    transport contract.
    """
    # TELEGRAM-TRIM phase 3 (operator popup 2026-11-10 "Only me; you if unfixed"): an ALERT about testing-paper
    # accounts only goes to the manager (recorded suppressed, priority high -> alerts_ledger.wakes_manager) and
    # reaches Telegram ONCE, flagged, only if it is still firing after the manager's window. Returns True
    # ("handled") on a suppression so no queue drainer retries it. Fails open: any error sends.
    try:
        from src.runtime import telegram_policy as _tp

        _route = _tp.paper_alert_route(kind, message, channel or _channel_for_token(bot_token))
        if _route == _tp.PAPER_ALERT_MANAGER:
            _tp.record_suppressed(kind or "unclassified", message, reason="paper_alert_to_manager",
                                  channel=channel or _channel_for_token(bot_token), priority="high")
            return True
        if _route == _tp.PAPER_ALERT_ESCALATE:
            _mins = float(((_tp.load_policy().get("paper_alerts") or {}).get("escalate_after_minutes")) or 120)
            message = _tp.escalation_text(message, _mins)
            priority = "high"
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify: paper-alert routing failed (%s) — sending", exc)
    delivered = "raised"
    try:
        result = _send_telegram_direct(
            message, parse_mode=parse_mode, mirror_to_fcm=mirror_to_fcm,
            bot_token=bot_token, chat_id=chat_id, reply_markup=reply_markup)
        delivered = "telegram_ok" if result else "skipped_no_creds"
        return result
    finally:
        _ledger_record(message, delivered, bot_token=bot_token, kind=kind,
                       channel=channel, priority=priority, dedup_key=dedup_key)


def _ledger_record(message: str, delivered: str, *, bot_token: Optional[str],
                   kind: Optional[str], channel: Optional[str],
                   priority: Optional[str], dedup_key: Optional[str]) -> None:
    """Best-effort ledger append; every failure is swallowed (logged)."""
    try:
        from src.runtime import alerts_ledger

        k = kind or "unclassified"
        if k in alerts_ledger.SKIP_KINDS:
            return
        ch = channel or _channel_for_token(bot_token)
        alerts_ledger.append(k, ch, message, priority=priority, dedup_key=dedup_key,
                             delivered=delivered)
    except Exception as exc:  # noqa: BLE001  # allow-silent: ledger is a best-effort side-write; the send must proceed unchanged
        logger.warning("notify: alert-ledger record failed (send unaffected): %s", exc)


def _channel_for_token(bot_token: Optional[str]) -> str:
    """Channel an unlabelled send landed on, from the bot token alone
    (never logged): the default bot is SYSTEM, the prop/trades and claude/manager
    tokens are matched against their resolved routes; anything else is ``unknown``."""
    if not bot_token or bot_token == os.environ.get("TELEGRAM_BOT_TOKEN"):
        return "system"
    try:
        from src.bot import telegram_routes as tr

        if bot_token == tr.prop_route().token:
            return "trades"
        if bot_token == tr.claude_route().token:
            return "manager"
    except Exception:  # noqa: BLE001  # allow-silent: label inference only
        pass
    return "unknown"


def _send_telegram_direct(
    message: str,
    *,
    parse_mode: Optional[str] = "HTML",
    mirror_to_fcm: bool = True,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """
    Stdlib-only direct POST to Telegram's sendMessage API.

    Returns ``True`` only when Telegram confirmed the send (``ok=true``);
    ``False`` when the send was SKIPPED because credentials were missing.
    Raises on a hard send failure (non-2xx / ok=false). The boolean lets a
    queue-drainer (``claude_bridge._drain_pending_claude_pings``) distinguish a
    real send from a silent skip and only delete the queued file on ``True`` —
    without it, a creds-missing skip returned normally and the drainer deleted
    the file, silently losing the ping (2026-06-23). Existing callers that
    ignore the return value are unaffected.

    Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from the process
    environment. If either is missing, logs a warning and returns ``False``
    (back-compat with the previous AlertManager-based path).

    On present credentials, performs a synchronous form-encoded POST. Raises
    ``urllib.error.URLError`` / ``urllib.error.HTTPError`` on network failure
    or non-2xx responses, and ``RuntimeError`` if the API replies with
    ``ok=false``. Callers are responsible for translating those into exit codes.

    ``parse_mode`` defaults to ``"HTML"`` for back-compat with existing
    HTML-formatted callers (``cmd_accounts_status`` etc.). Plain-text content
    that contains ``<``/``>``/``&`` (e.g. the hourly report's
    ``expected <= 15m`` line) MUST pass ``parse_mode=None`` to avoid Telegram's
    HTML parser rejecting the message with ``BadRequest: Can't parse entities``.
    Pass an explicit ``"MarkdownV2"`` only when every special character has
    been escaped.

    Security: the bot token is embedded in the request URL but is never logged
    or printed in any form (full, redacted, or length). Only ``ok``,
    ``message_id``, and HTTP ``status_code`` are logged on success.
    """
    # M12 S1 mirror — every operator-facing Telegram is also published as
    # an FCM data message to subscribed Android devices. This is the
    # single chokepoint (every higher-level helper — send_to_operator,
    # notify_operator, send_via_alert_manager — funnels through here), so
    # one hook covers the hourly report, the news-veto reporter, every
    # pipeline-result line, the watchdog (when it routes through this
    # path), the daily heartbeat, etc.
    #
    # Failure isolation: publish_event already swallows every exception
    # (feature flag off / credentials missing / FCM 5xx / network
    # timeout). The defense-in-depth try/except here adds belt + suspenders
    # so a bad import or a transient bug in mobile_push can't propagate
    # into the Telegram send path.
    #
    # Position: BEFORE the Telegram HTTP call so the push fires even when
    # Telegram itself is unreachable (push as a strict superset of
    # operator-facing comms). The body the phone shows is the *intended*
    # message, not the post-Telegram-formatting one — fine for plain text;
    # HTML/Markdown source survives intact and is human-readable on the
    # phone shade.
    # ``mirror_to_fcm=False`` is for callers that already fire their own
    # typed FCM event (e.g. the trade-lifecycle dispatch in
    # ``mobile_push.trade_events``, which publishes ``trade_opened`` /
    # ``trade_closed`` / ``trade_updated`` directly). Without this the phone
    # would get TWO pushes for one event — the typed kind AND the generic
    # ``telegram`` mirror — so those callers opt the mirror out.
    if mirror_to_fcm:
        try:
            _publish_telegram_to_fcm(message, parse_mode=parse_mode)
        except Exception as exc:  # noqa: BLE001  # allow-silent: M12 S1 mirror — mobile_push failure must never propagate into the Telegram send path
            logger.warning("notify: mobile_push mirror failed: %s", exc)

    # ``bot_token`` lets a caller target a SPECIFIC bot (e.g. the prop-account
    # bot) instead of the default operator/trader bot; default None keeps the
    # historical TELEGRAM_BOT_TOKEN behaviour.
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    # ``chat_id`` lets a caller target a SPECIFIC conversation, the companion of
    # the ``bot_token`` override above. Without it a route could name its own
    # chat and never reach it — src/bot/telegram_routes.py resolves a per-route
    # chat id (TELEGRAM_CLAUDE_CHAT_ID / TELEGRAM_PROP_CHAT_ID) and, until this
    # parameter existed, that half of every Route was decorative: the token
    # picked the BOT and the environment silently picked the CHAT.
    # Default None keeps the historical TELEGRAM_CHAT_ID behaviour exactly.
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning(
            "Telegram credentials missing (bot token or "
            "TELEGRAM_CHAT_ID); skipping send"
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    fields = {"chat_id": chat_id, "text": message}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    # Optional inline keyboard (Telegram expects a JSON-encoded reply_markup in
    # the form field). Used by the prop ticket-expiry Yes/No prompt — the button
    # press lands as a callback_query on whichever bot token owns this message,
    # so the prompt MUST be sent via the prop bot token for the prop bot to
    # receive the answer.
    if reply_markup is not None:
        fields["reply_markup"] = json.dumps(reply_markup)
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.getcode()
        body = resp.read()
        if not (200 <= status < 300):
            raise urllib.error.HTTPError(
                "<redacted>", status, "non-2xx from Telegram", resp.headers, None
            )
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Telegram returned non-JSON body: {exc}") from exc
        ok = bool(parsed.get("ok"))
        message_id = (parsed.get("result") or {}).get("message_id")
        logger.info(
            "Telegram send: ok=%s message_id=%s status_code=%s",
            ok,
            message_id,
            status,
        )
        if not ok:
            raise RuntimeError("Telegram API returned ok=false")
        return True


def notify_operator(telegram_client: Any, message: str) -> None:
    """
    Send a short operator-facing message without allowing notification
    failures to crash the runtime.
    """
    try:
        if telegram_client is None:
            logger.warning("Telegram client missing; message not sent: %s", message)
            return

        if hasattr(telegram_client, "send_message"):
            telegram_client.send_message(message)
            return

        raise AttributeError("telegram_client has no send_message method")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to notify operator: %s | original=%s", exc, message)


def send_to_operator(
    plain: str,
    html: Optional[str] = None,
    *,
    telegram_client: Any = None,
) -> None:
    """Single entry-point for runtime-to-operator messages.

    Resolution order:
      1. telegram_client present → ``notify_operator(client, plain)``
      2. html provided           → ``send_telegram_direct(html, "HTML")``;
                                   on failure falls back to plain.
      3. plain only              → ``send_telegram_direct(plain, None)``

    Callers should not replicate this fallback chain themselves. Raises only
    if ALL paths fail; individual step failures are logged.
    """
    if telegram_client is not None:
        notify_operator(telegram_client, plain)
        return
    if html is not None:
        try:
            send_telegram_direct(html, parse_mode="HTML")
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "send_to_operator: HTML send failed (%s); falling back to plain text",
                exc,
            )
    send_telegram_direct(plain, parse_mode=None)


def _publish_telegram_to_fcm(message: str, *, parse_mode: Optional[str]) -> None:
    """Fan a Telegram message out to subscribed Android devices via FCM.

    Lazy import — ``src.runtime.mobile_push`` is a sibling module and the
    function-scope import means a startup ordering quirk (or a missing
    google-auth in a stripped env) can't crash this module's import.

    The payload is kept small: the message text + the parse_mode hint
    (so the device can render Markdown / HTML differently if it wants).
    FCM caps data payloads at 4 KB; long hourly reports get truncated
    to stay inside that with margin.
    """
    from src.runtime.mobile_push import publish_event
    from src.runtime.mobile_push.event_kinds import TELEGRAM

    # 3 KB leaves headroom for the event_kind key + JSON envelope below
    # FCM's 4 KB data-message limit.
    _MAX_PAYLOAD_CHARS = 3000
    _TRUNC_SUFFIX = "\n…(truncated)"
    body = (
        message
        if len(message) <= _MAX_PAYLOAD_CHARS
        else message[: _MAX_PAYLOAD_CHARS - len(_TRUNC_SUFFIX)] + _TRUNC_SUFFIX
    )
    publish_event(
        TELEGRAM,
        {
            "text": body,
            "parse_mode": parse_mode or "plain",
        },
    )


def send_via_alert_manager(message: str) -> None:
    """Send a message to the operator's Telegram chat. Plain-text mode.

    Used by the hourly report scheduler, the news-veto pipeline reporter,
    and the "Pipeline result" message at the end of every tick. The name
    is historical — there is no AlertManager dependency anymore.

    Previously this routed through ``src.bot.alert_manager.AlertManager``
    which had two problems:

      1. The wrapper called ``mgr.send(message)`` but ``AlertManager``
         only exposes ``send_alert``. Every send raised ``AttributeError``,
         was caught by ``outcomes._send_telegram_or_queue``, and the
         message landed in the pending-queue JSONL. Operator never
         received hourly summaries (fixed CP-2026-05-02).
      2. The wrapper's nested ``asyncio.run`` could not run from inside
         an existing event loop, which the bot process is.

    The replacement is a direct sync call to ``send_telegram_direct``
    with ``parse_mode=None`` so the hourly summary's plain-text content
    (which contains characters like ``<= 15m`` that Telegram's HTML
    parser rejects) is delivered without the parser interpreting any
    of it. Callers that DO want HTML/Markdown should call
    ``send_telegram_direct`` directly with the appropriate ``parse_mode``.
    """
    try:
        send_telegram_direct(message, parse_mode=None)
    except Exception as exc:  # noqa: BLE001
        # Re-raise so the caller (typically ``outcomes._send_telegram_or_queue``)
        # can fall through to the pending-queue JSONL drain. The previous
        # silent-failure mode hid this exact code path for two sprints.
        logger.warning("send_via_alert_manager: telegram send failed: %s", exc)
        raise
