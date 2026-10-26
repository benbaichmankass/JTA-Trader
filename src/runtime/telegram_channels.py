"""ONE declared routing table: every Telegram event kind -> exactly one CHANNEL.

Operator spec, 2026-10-09 (checklist row ``TELEGRAM-CHANNELS``), reprioritised
2026-10-11 as OPERATIONAL STABILITY, not UI:

``TRADES``   (the bot that used to carry PROP tickets) — trade OPENED / CLOSED /
             UPDATED events, all accounts. **No prop ticket prompts**: prop
             execution is automated.
``SYSTEM``   (the main ICT trader bot) — the hourly system update, restarts,
             problems / alerts, NO-HALT red flags: what the operator must know
             about the machine.
``MANAGER``  (the Claude bot) — manager updates: PR merges, decisions taken
             under authority, questions that need the operator.

WHY A TABLE AND NOT A CONVENTION. Before this module the channel a message
landed in was decided by whichever token its sender happened to pass (or not
pass) to ``send_telegram_direct`` — 30-odd call sites, no inventory. A sender
nobody mapped could not be audited, and a move that orphans an alert is
invisible until the alert does not arrive. ``tests/test_telegram_channels.py``
scans the repo for every Telegram send primitive and fails when a file that
sends is not in :data:`SENDERS`, or names a kind that is not in
:data:`EVENT_CHANNEL`.

⚠️ AN ALERT IS NEVER LOST IN THE MOVE — the operational-stability half:

* an UNKNOWN kind routes to ``SYSTEM`` (the channel that has always carried
  alerts), never to nowhere;
* a channel whose route is not deliverable (its token unset) falls back to the
  ``SYSTEM`` route — the same ``fallback`` rung ``telegram_routes`` documents;
* a send that RAISES on a non-SYSTEM channel is retried once on ``SYSTEM``,
  prefixed with where it was meant to go, so it is delivered somewhere visible
  rather than dropped;
* :data:`RETIRED` is only ever assigned to a prompt the operator retired by
  name (prop ticket prompts, 2026-10-09). No alert kind may be retired —
  the test pins that ``SYSTEM`` kinds and ``RETIRED`` kinds are disjoint and
  that every ``alert`` kind routes to ``SYSTEM``.

⚠️ NEVER LOG A TOKEN. Routes are described by the NAME of the variable that
answered (``telegram_routes.Route.describe``), never its value.
"""
from __future__ import annotations

import logging
from typing import Final, Optional

logger = logging.getLogger(__name__)

TRADES: Final = "trades"
SYSTEM: Final = "system"
MANAGER: Final = "manager"
#: Deliberately NOT a channel: a kind the operator retired by name. A send of a
#: retired kind is refused (logged), never re-routed.
RETIRED: Final = "retired"
#: A reply to a command, sent into the conversation the command came from. It
#: is not a push and is not routed — the operator chose the conversation.
REPLY: Final = "reply"

CHANNELS: Final[tuple[str, ...]] = (TRADES, SYSTEM, MANAGER)

#: ── THE ROUTING TABLE ──────────────────────────────────────────────────────
#: kind -> channel. Kinds are stable strings; the pending-ping drainers read the
#: ``channel`` a producer stamped from here.
EVENT_CHANNEL: Final[dict[str, str]] = {
    # ── TRADES: trade lifecycle, every account ─────────────────────────────
    "trade_opened": TRADES,          # mobile_push/trade_events (journal observer)
    "trade_closed": TRADES,
    "trade_updated": TRADES,
    "trade-open": TRADES,            # execution_diagnostics.enqueue_trade_*
    "trade-close": TRADES,
    "trade-update": TRADES,
    "demotrade": TRADES,             # execution_diagnostics.enqueue_demo_trade_notification
    "prop_fill": TRADES,             # a prop ticket placed / closed (executor report)
    "prop_monitor": TRADES,          # open prop position update (pulse / consolidated)
    "trades_snapshot": TRADES,       # periodic PERFORMANCE SNAPSHOT (send_hourly_now, part C cadence)

    # ── RETIRED by the operator, 2026-10-09: "NO tickets there any more" ───
    # Machine-flow accounts already sent none of these; only a manual-flow
    # account could (breakout_1, mode dry_run). Tickets stay journaled and the
    # typed FCM push is unchanged — only the Telegram prompt is retired.
    "prop_ticket": RETIRED,
    "prop_expiry_prompt": RETIRED,
    "prop_expiry_notice": RETIRED,
    "prop_invalidation_prompt": RETIRED,

    # ── SYSTEM: the machine — hourly update, restarts, alerts, red flags ───
    "hourly_report": SYSTEM,         # hourly_report / outcomes (legacy combined path)
    "system_health": SYSTEM,         # periodic HEALTH CHECK (send_hourly_now, part C cadence)
    "daily_heartbeat": SYSTEM,
    "pipeline_result": SYSTEM,       # outcomes.report (tick results, refusals)
    "news_veto": SYSTEM,             # pipeline.py
    "restart": SYSTEM,               # boot_audit, notify_on_pull deploy/restart
    "deploy": SYSTEM,
    "alert": SYSTEM,                 # every latched/latching alert + watchdog
    "execution_alert": SYSTEM,       # execution_diagnostics non-trade enqueues
    "prop_alert": SYSTEM,            # prop SL/TP crossed, fills stale, phone executor
    "prop_status_request": SYSTEM,   # "report this account's status" — kept, not a ticket
    "red_flag": SYSTEM,              # NO-HALT persistent-failure flag (rule 7)

    # ── MANAGER: what the manager did, and what needs the operator ─────────
    "manager_update": MANAGER,       # work digest (hourly regular status update)
    "claude_ping": MANAGER,          # send_ping target=claude / send-ping action
    "decision": MANAGER,             # telegram_decisions (ask + answer)
    "pr_merged": MANAGER,            # notify_on_pull merge events
    "session": MANAGER,              # notify_session end-of-session pings
    "system_action": MANAGER,        # system-action run outcome (notify_run / cancel guard)

    # ── REPLY: command responses (not routed) ───────────────────────────────
    "command_reply": REPLY,
}

#: ── EVERY SENDER, MAPPED ───────────────────────────────────────────────────
#: repo-relative path -> the kinds it sends. The test derives the set of files
#: that call a Telegram send primitive and requires it to equal this key set.
SENDERS: Final[dict[str, tuple[str, ...]]] = {
    # transport / plumbing (route whatever they are handed)
    "src/runtime/notify.py": ("alert",),
    "src/runtime/telegram_channels.py": ("alert",),
    "src/runtime/telegram_split.py": ("red_flag",),   # .broken ping flag (oversize fix)
    "src/bot/telegram_routes.py": ("alert",),
    "src/bot/cloud_notifier.py": ("execution_alert", "trade-open", "claude_ping"),
    "src/bot/claude_bridge.py": ("claude_ping", "command_reply"),
    "src/units/ui/telegram_format.py": ("alert",),
    "src/utils/log_redact.py": ("alert",),
    "scripts/send_ping.py": ("claude_ping", "execution_alert"),
    "scripts/ops/send_route_test_ping.py": ("alert",),
    "scripts/research/research_watchdog.py": ("alert",),   # RESEARCH-WATCHDOG escalations/resolutions -> SYSTEM (direct sendMessage)
    # TRADES
    "src/runtime/mobile_push/trade_events.py": ("trade_opened", "trade_closed", "trade_updated"),
    "src/runtime/execution_diagnostics.py": (
        "trade-open", "trade-close", "trade-update", "demotrade", "execution_alert"),
    "scripts/ops/amend_position_sl.py": ("trade-update",),   # AMEND-SL-ACTION: one SL-moved ping via enqueue_trade_update
    "scripts/ops/live_review_apply.py": ("trade-update",),   # LTR-6R: SL-moved ping per applied account + ONE not-applied alert, both via enqueue_trade_update
    "scripts/ops/live_review_dispatch.py": ("trade-update",),   # LTR-APPLY-DISPATCH: ONE not-dispatched alert per review_id (money rows) via enqueue_trade_update
    "src/prop/breakout_notify.py": (
        "prop_fill", "prop_monitor", "prop_ticket", "prop_expiry_prompt",
        "prop_expiry_notice", "prop_invalidation_prompt", "prop_alert",
        "prop_status_request"),
    # SYSTEM
    "src/runtime/hourly_report.py": ("hourly_report",),
    "src/runtime/outcomes.py": ("pipeline_result", "hourly_report"),
    "src/runtime/pipeline.py": ("news_veto",),
    "src/runtime/boot_audit.py": ("restart",),
    "src/runtime/order_monitor.py": ("alert",),
    "src/runtime/account_reachability_alert.py": ("alert",),
    "src/runtime/trainer_reachability_alert.py": ("alert",),
    "src/runtime/decision_channel_alert.py": ("alert",),
    "src/runtime/exit_loop_health.py": ("alert",),
    "src/runtime/ltr_first_proof.py": ("alert",),   # LTR first-proof pings, one per stage, once ever (operator 2026-10-26)
    "src/runtime/losing_streak_alert.py": ("alert",),
    "src/runtime/silent_refusal_alert.py": ("alert",),
    "src/runtime/starved_account_alert.py": ("alert",),
    "src/runtime/package_leg_coverage.py": ("alert",),
    "src/runtime/validation.py": ("alert",),
    "src/units/accounts/execute.py": ("alert",),
    "src/prop/prop_fills_staleness.py": ("prop_alert",),
    "src/prop/phone_executor.py": ("prop_alert",),
    "src/prop/phone_trail.py": ("prop_alert",),
    "src/prop/phone_drill.py": ("prop_alert",),
    "scripts/check_heartbeat.py": ("alert",),
    "scripts/check_ib_gateway.py": ("alert",),
    "scripts/check_web_api.py": ("alert",),
    "scripts/db_integrity_alert.py": ("alert",),
    "scripts/daily_heartbeat.py": ("daily_heartbeat",),
    "scripts/send_hourly_now.py": ("system_health", "trades_snapshot", "hourly_report"),
    "scripts/startup_env_check.py": ("alert",),
    "scripts/secret_scan.py": ("alert",),
    "scripts/ops/system_action_cancel_guard.py": ("alert",),
    "src/core/coordinator.py": ("execution_alert", "demotrade"),
    "src/prop/prop_balance.py": ("execution_alert",),
    "src/units/accounts/daily_dd_switch.py": ("execution_alert",),
    "src/runtime/liveness_watchdog.py": ("alert",),
    "scripts/ops/notify_unit_failure.py": ("alert",),
    "scripts/ops/trainer_disk_alarm.py": ("alert",),
    "scripts/ops/prop_executor_tick.sh": ("red_flag",),
    "scripts/ops/prop_feed_tick.sh": ("red_flag",),
    "scripts/deploy_pull_restart.sh": ("deploy",),
    "scripts/ops/send_ping_action.sh": ("claude_ping", "alert"),
    "scripts/ops/notify_run.sh": ("system_action",),
    ".github/workflows/external-comment-alert.yml": ("alert",),
    ".github/workflows/external-issue-alert.yml": ("alert",),
    ".github/workflows/guards.yml": ("alert",),
    ".github/workflows/research-loss-detector.yml": ("alert",),
    ".github/workflows/claude-run-failure-alert.yml": ("alert",),
    ".github/workflows/system-actions.yml": ("system_action",),
    # MANAGER (git-pull fan-out of committed session pings / merges)
    "scripts/notify_on_pull.py": ("pr_merged", "claude_ping"),
    "scripts/ops/attention_watch.py": ("manager_update",),
    "scripts/ops/phone_hb_alert.py": ("alert",),   # PHONE-KEEPALIVE: stale phone heartbeat, target=system
    # MANAGER
    "scripts/notify_session.py": ("session",),
    "scripts/ops/work_digest_now.py": ("manager_update",),
    "src/runtime/telegram_decisions.py": ("decision",),
    "src/runtime/manager_status.py": ("command_reply",),
    # REPLY (polled bots answering the operator in-conversation)
    "src/bot/telegram_query_bot.py": ("command_reply",),
    "src/bot/operator_commands.py": ("command_reply",),
    "src/bot/claude_decision_bot.py": ("decision", "command_reply"),
    "src/bot/comms_handler.py": ("command_reply",),
    "src/bot/alert_manager.py": ("alert",),
    "src/prop/telegram_report_handler.py": ("command_reply",),
    "src/runtime/telegram_poll_registry.py": ("command_reply",),
    "src/main.py": ("alert",),
}


def channel_for(kind: str) -> str:
    """The channel *kind* routes to. An UNKNOWN kind is ``SYSTEM`` — never
    nowhere: an unmapped alert must still reach the operator."""
    ch = EVENT_CHANNEL.get(str(kind or ""))
    if ch is None:
        logger.warning("telegram_channels: unmapped kind %r -> SYSTEM", kind)
        return SYSTEM
    return ch


def is_retired(kind: str) -> bool:
    return EVENT_CHANNEL.get(str(kind or "")) == RETIRED


def channel_route(channel: str):
    """The :class:`telegram_routes.Route` for *channel*.

    TRADES uses the bot that carried PROP tickets (``prop_route`` — its token
    order is unchanged, so no secret is renamed by this move); MANAGER the
    Claude bot (``claude_route``); SYSTEM the shared trader bot.
    """
    from src.bot import telegram_routes as tr

    if channel == TRADES:
        return tr.prop_route()
    if channel == MANAGER:
        return tr.claude_route()
    return tr.system_route()


def route_for(kind: str):
    """``(channel, route)`` for *kind*, falling back to SYSTEM when the
    channel's own route cannot deliver. Never returns an undeliverable route
    for a non-SYSTEM channel while SYSTEM can deliver."""
    ch = channel_for(kind)
    if ch in (RETIRED, REPLY):
        return ch, None
    route = channel_route(ch)
    if ch != SYSTEM and not route.deliverable:
        logger.warning("telegram_channels: %s route not deliverable (%s) — "
                       "falling back to SYSTEM for kind %r", ch, route.describe(), kind)
        return SYSTEM, channel_route(SYSTEM)
    return ch, route


def send(kind: str, text: str, *, parse_mode: Optional[str] = None,
         mirror_to_fcm: bool = False, reply_markup: Optional[dict] = None) -> bool:
    """Send *text* as event *kind* to its channel. Returns True on a confirmed
    send, False when skipped (retired kind / muted by settings / no creds).

    Raises only if BOTH the channel's route and the SYSTEM fallback raised —
    the same contract as ``send_telegram_direct`` so existing ``try/except``
    callers keep their semantics.
    """
    from src.runtime.notify import send_telegram_direct

    ch, route = route_for(kind)
    if ch == RETIRED:
        logger.info("telegram_channels: kind %r is RETIRED (operator 2026-10-09) "
                    "— Telegram send refused", kind)
        return False
    if ch == REPLY or route is None:
        raise ValueError(f"kind {kind!r} is a command reply — reply in-conversation")
    if not enabled(kind):
        logger.info("telegram_channels: kind %r muted in settings — not sent", kind)
        return False
    try:
        return bool(send_telegram_direct(
            text, parse_mode=parse_mode, mirror_to_fcm=mirror_to_fcm,
            bot_token=route.token, chat_id=route.chat_id, reply_markup=reply_markup))
    except Exception as exc:  # noqa: BLE001
        if ch == SYSTEM:
            raise
        logger.warning("telegram_channels: %s send failed for %r via %s (%s) — "
                       "retrying on SYSTEM so it is not lost", ch, kind,
                       route.describe(), type(exc).__name__)
        sysr = channel_route(SYSTEM)
        return bool(send_telegram_direct(
            f"[meant for {ch.upper()}] {text}", parse_mode=parse_mode,
            mirror_to_fcm=mirror_to_fcm, bot_token=sysr.token, chat_id=sysr.chat_id))


def enabled(kind: str) -> bool:
    """Settings hook (TELEGRAM-CHANNELS part C): False only when the operator
    muted *kind* in ``src/runtime/telegram_settings.py``. An UNMUTABLE kind is
    always enabled, and a settings read that FAILS enables (over-send, never
    silence)."""
    if kind in UNMUTABLE:
        return True
    try:
        from src.runtime import telegram_settings

        return not telegram_settings.is_muted(kind)
    except Exception:  # noqa: BLE001 — a broken store must not silence anything
        logger.warning("telegram_channels: settings read failed — %r enabled", kind)
        return True


def mutable(kind: str) -> bool:
    """May the operator mute *kind*? Alerts / red flags / decisions: never —
    muting those is the desensitised-alarm failure inverted."""
    return EVENT_CHANNEL.get(kind) not in (None, RETIRED, REPLY) and kind not in UNMUTABLE


#: Kinds that can never be muted from a settings menu.
UNMUTABLE: Final[frozenset[str]] = frozenset({
    "alert", "execution_alert", "prop_alert", "red_flag", "restart",
    "decision", "system_action",
    # claude_ping carries the manager's questions to the operator ("needs
    # you") — muting it would hide asks, not noise (part C, 2026-10-11).
    "claude_ping",
})


def describe_table() -> str:
    """Human-readable routing table (for the PR body / diag), no secrets."""
    out = []
    for ch in (*CHANNELS, RETIRED, REPLY):
        kinds = sorted(k for k, c in EVENT_CHANNEL.items() if c == ch)
        out.append(f"{ch.upper():8} {', '.join(kinds)}")
    return "\n".join(out)
