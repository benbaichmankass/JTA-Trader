"""One-tap operator approval of a live-review recommendation, executed directly (TRADE-ACTION-DIRECT-PATH phase 1).

Operator, 2026-11-12 ~00:00Z, verbatim (checklist row TRADE-ACTION-DIRECT-PATH): "if it needs me, then it needs
to ping me so that I can immediately do that, right? But also through the system, not like going into the broker
account. So there needs to be a button that I press to accept a recommendation, and that directly executes that
action." MEASURED 2026-11-11: the ETH and SOL ml_entry close rows reached the VM within 45 s (rows watcher verdict
``advice_only``) and both stops hit 22.5 / 27 min later while the operator's yes travelled through chat and the
Actions queue. Design: docs/design/trade-action-direct-path-2026-11.md.

The path (no repo, PR or Actions hop):

1. The VM rows watcher classifies a new row. A row the VM will NOT execute itself (route ``operator_ask``, or an
   ``advice_only`` class on a non-``none`` route) whose action has a directed executor gets :func:`offer`: ONE ask
   per review_id, stored in ``pending.json``, sent to the operator's Telegram chat with Approve / Reject buttons.
2. A tap reaches :func:`handle_callback` in whichever polled bot carries the ``tapv`` prefix (the Claude decision
   bot or the trader bot). Only the operator's chat (``TELEGRAM_CHAT_ID``, fail-closed) may decide; an ask is decided
   once (file lock + state machine) and expires after :func:`expiry_minutes`.
3. Approve writes ONE ``directed_action/v1`` record (``directed_by: operator:telegram``, the operator's tapped
   approval as ``operator_quote``) into the local spool. The live trader's ``directed-actions-watch`` thread runs
   ``scripts/ops/directed_action.py spool-pass`` within ~2 s: the SAME ``vm_pass`` -> ``live_review_apply.run()``
   as every directed action, so each account still decides through its own ``RiskManager`` (tighten-only + noise
   floor, TP doctrine, both brackets, a widen's fresh-entry check) and every apply is read back from the venue.

GATES: none added. The expiry and the chat check are validity rules on the BUTTON, not trading gates (the same
shape as ``directed_actions.STALE_S`` and the ``wdec`` chat check). Nothing here can execute what the operator
could not already direct through ``directed_action.py submit``.

Journal (diag ``log_file?name=trade_approvals``): ``runtime_logs/trade_approvals/journal.jsonl``, one line per
event: offered (with ``sent``), decided (approve / reject / expired / refused, with ``record_id``).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from src.runtime import directed_actions as da

logger = logging.getLogger(__name__)

CB_PREFIX = "tapv"
TOKEN_HEX = 10
CB_RE = re.compile(rf"^{CB_PREFIX}:([ar]):([0-9a-f]{{{TOKEN_HEX}}})$")
TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64
DEFAULT_EXPIRY_MIN = 15.0
DIRECTED_BY = "operator:telegram"

#: Live-review recommendation -> directed action. Only classes with an executor on the directed path; change_size /
#: add_entry have none anywhere (LTR-ACTION-EXECUTOR-GAPS) and are logged ``no_direct_executor``.
ACTION_MAP = {"close": "close", "partial_close": "partial_close", "move_tp": "move_tp",
              "tighten_sl": "tighten_sl", "widen_sl": "move_sl"}
#: Mechanics verdicts that may carry a button. ``mismatch`` is an order-path bug (flag_mechanics), never an exit call.
BUTTON_MECHANICS = ("match", "could_not_look")

PENDING, APPROVED, REJECTED, EXPIRED, REFUSED = "pending", "approved", "rejected", "expired", "refused"
#: MANAGER-VM-DIRECT-OPS: an ask for a Tier-2 job of the direct ops channel (src/runtime/ops_actions.py) rides
#: the SAME store, buttons, expiry and decide() state machine; on approve/reject decide() hands the outcome to
#: ops_actions.on_approval instead of writing a directed record.
OPS_KIND = "ops_job"


def _root() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / "trade_approvals"


def spool_root(root: Optional[Path] = None) -> Path:
    """The spool tree ``directed_action.py spool-pass`` reads: ``<spool>/comms/directed_actions/<id>.json``."""
    return (root or _root()) / "spool"


def expiry_minutes() -> float:
    """``TRADE_APPROVAL_EXPIRY_MIN`` (default 15). An unparseable or non-positive value falls back to the default."""
    try:
        v = float(os.environ.get("TRADE_APPROVAL_EXPIRY_MIN", DEFAULT_EXPIRY_MIN))
    except (TypeError, ValueError):
        return DEFAULT_EXPIRY_MIN
    return v if v > 0 else DEFAULT_EXPIRY_MIN


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v: Any) -> Optional[float]:
    return da._num(v)


# ─────────────────────────────────────────────────────────────────────────── classification

def wants_button(row: Dict[str, Any], vm_verdict: Optional[str]) -> Tuple[bool, str]:
    """Whether a row the watcher just classified should become an operator ask. Returns (yes, why)."""
    rec = row.get("recommendation") or {}
    action = rec.get("action")
    route = (row.get("disposition") or {}).get("route")
    if action in (None, "hold", "no_recommendation", "flag_mechanics"):
        return False, f"action_{action}"
    needs_operator = route == "operator_ask" or (vm_verdict == "advice_only" and route not in (None, "none"))
    if not needs_operator:
        return False, f"route_{route}"
    if action not in ACTION_MAP:
        return False, "no_direct_executor"
    mech = (row.get("mechanics") or {}).get("verdict")
    if mech not in BUTTON_MECHANICS:
        return False, f"mechanics_{mech}"
    if action in ("move_tp", "tighten_sl", "widen_sl") and not (_num(rec.get("level")) or 0) > 0:
        return False, "level_missing"
    if action == "partial_close":
        f = _num(rec.get("size_fraction"))
        if f is None or not 0.0 < f < 1.0:
            return False, "size_fraction_missing"
    return True, "ok"


def directed_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """The directed_action/v1 action fields for a row that :func:`wants_button` accepted."""
    rec = row.get("recommendation") or {}
    a = ACTION_MAP[rec["action"]]
    out: Dict[str, Any] = {"action": a}
    if a in da.NEEDS_LEVEL:
        out["level"] = float(rec["level"])
    if a == "partial_close":
        out["fraction"] = float(rec["size_fraction"])
    return out


# ─────────────────────────────────────────────────────────────────────────── the store

@contextlib.contextmanager
def _locked(root: Path) -> Iterator[Dict[str, Any]]:
    """The pending store under an exclusive lock; written back on exit."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "pending.json"
    with open(root / "pending.lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            try:
                store = json.loads(path.read_text())
            except FileNotFoundError:
                store = {}
            except ValueError:
                # Never silently drop asks: keep the unreadable file aside and start a fresh store.
                os.replace(path, root / f"pending.unreadable.{int(_now().timestamp())}.json")
                store = {}
            store.setdefault("asks", {})
            store.setdefault("by_review", {})
            yield store
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(store, indent=1, default=str) + "\n")
            os.replace(tmp, path)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _journal(root: Path, doc: Dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "journal.jsonl").open("a") as fh:
        fh.write(json.dumps(doc, default=str, separators=(",", ":")) + "\n")


def read_pending(root: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only view for the SPA / diag (no lock needed for a snapshot)."""
    try:
        return json.loads(((root or _root()) / "pending.json").read_text())
    except (OSError, ValueError):
        return {"asks": {}, "by_review": {}}


# ─────────────────────────────────────────────────────────────────────────── rendering

def encode_callback(choice: str, token: str) -> str:
    cb = f"{CB_PREFIX}:{choice}:{token}"
    assert len(cb.encode()) <= TELEGRAM_CALLBACK_DATA_MAX_BYTES
    return cb


def keyboard(token: str) -> Dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": encode_callback("a", token)},
                                 {"text": "✖ Reject", "callback_data": encode_callback("r", token)}]]}


def _action_text(ask: Dict[str, Any]) -> str:
    if ask.get("kind") == OPS_KIND:
        return f"run ops action {ask.get('ops_action')}"
    a = ask["directed"]["action"]
    lvl, fr = ask["directed"].get("level"), ask["directed"].get("fraction")
    if a == "close":
        return "CLOSE the position"
    if a == "partial_close":
        return f"CLOSE {fr:.0%} of the position"
    if a == "move_tp":
        return f"move TP to {lvl:g}"
    if a == "tighten_sl":
        return f"tighten SL to {lvl:g}"
    return f"move SL to {lvl:g} (looser: a widen)"


def render(ask: Dict[str, Any]) -> str:
    ev = ask.get("ev_delta_r")
    ev_line = (f"EV vs hold: {ev:+.3f}R ({ask.get('basis')}, {ask.get('confidence')})"
               if isinstance(ev, (int, float)) else f"basis: {ask.get('basis')}, confidence: {ask.get('confidence')}")
    reason = " ".join(str(ask.get("reason") or "").split())
    lines = [f"🔔 Trade action needs you: {ask.get('symbol') or ask.get('leg') or '?'} ({ask.get('leg')})",
             f"➡️ {_action_text(ask)}",
             f"Accounts: {', '.join(map(str, ask.get('accounts') or [])) or '-'}",
             ev_line,
             (reason[:420] + "…") if len(reason) > 420 else reason]
    if ask.get("mechanics") != "match":
        lines.append(f"⚠️ mechanics: {ask.get('mechanics')} (the venue read did not complete at review time)")
    lines += [f"Review {ask['review_id']} · expires {ask['expires_at'][11:16]}Z",
              "Approve executes now on every account carrying the package, through each account's own risk checks."]
    return "\n".join(x for x in lines if x)


# ─────────────────────────────────────────────────────────────────────────── sending

Sender = Callable[[str, Dict[str, Any]], bool]


def _route():
    """The bot a ``tapv`` tap is RECEIVED on: the Claude decision bot when it claims the prefix, else the trader bot
    when it does. Same poll-evidence rule as telegram_decisions.answerable_route (a deliverable but unpolled bot
    would ship dead buttons)."""
    from src.runtime.telegram_poll_registry import poll_state
    # collapsed-state: unknown — only `.answerable` matters for sending a button: not polled and could-not-look
    # both mean "no button here" (the same rule as telegram_decisions.answerable_route), and offer() then falls back
    # to a plain alert, so neither state is silent.
    from src.bot.telegram_routes import claude_route

    trader_chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip() or None
    claude = claude_route()
    if claude.isolated and claude.token and claude.chat_id and poll_state(claude.token_from, prefix=CB_PREFIX).answerable:
        return claude.token, claude.chat_id, claude.token_from
    trader = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    if trader and trader_chat and poll_state("TELEGRAM_BOT_TOKEN", prefix=CB_PREFIX).answerable:
        return trader, trader_chat, "TELEGRAM_BOT_TOKEN"
    return None, None, None


def _default_sender(text: str, markup: Dict[str, Any]) -> bool:
    from src.runtime.notify import send_telegram_direct

    token, chat, _ = _route()
    if not token:
        return False
    return bool(send_telegram_direct(text, parse_mode=None, mirror_to_fcm=False, bot_token=token, chat_id=chat,
                                     reply_markup=markup))


def _fallback_alert(text: str) -> bool:
    """No answerable bot: the operator still hears about the ask, without a button, on the alert channel."""
    try:
        from src.runtime import telegram_channels
        return bool(telegram_channels.send("alert", text + "\n\n(no polled bot claims the Approve button: "
                                           "approve it with scripts/ops/directed_action.py submit)"))
    except Exception:  # noqa: BLE001
        return False


def offer(row: Dict[str, Any], *, vm_verdict: Optional[str] = None, send: Optional[Sender] = None,
          fallback: Callable[[str], bool] = _fallback_alert, now: Optional[datetime] = None,
          root: Optional[Path] = None) -> Dict[str, Any]:
    """Create and send ONE ask for ``row`` if it needs the operator. Never raises; returns a receipt for the
    watcher's log line (``{"approval": ...}``). Idempotent per review_id."""
    try:
        yes, why = wants_button(row, vm_verdict)
        if not yes:
            return {"state": "not_offered", "why": why}
        r, t = root or _root(), now or _now()
        rid = str(row.get("review_id"))
        rec = row.get("recommendation") or {}
        with _locked(r) as store:
            if rid in store["by_review"]:
                return {"state": "already_offered", "token": store["by_review"][rid]}
            token = secrets.token_hex(TOKEN_HEX // 2)
            ask = {"token": token, "review_id": rid, "order_package_id": row.get("order_package_id"),
                   "leg": row.get("leg"), "symbol": row.get("symbol"), "accounts": list(row.get("accounts") or []),
                   "row_action": rec.get("action"), "directed": directed_fields(row),
                   "ev_delta_r": _num(rec.get("ev_delta_r")), "basis": rec.get("basis"),
                   "confidence": rec.get("confidence"), "reason": rec.get("reason"),
                   "mechanics": (row.get("mechanics") or {}).get("verdict"),
                   "route": (row.get("disposition") or {}).get("route"), "vm_verdict": vm_verdict,
                   "created_at": _iso(t), "expires_at": _iso(t + timedelta(minutes=expiry_minutes())),
                   "state": PENDING}
            store["asks"][token] = ask
            store["by_review"][rid] = token
        text = render(ask)
        sent = False
        try:
            sent = bool((send or _default_sender)(text, keyboard(token)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("trade_approvals: send failed: %s", exc)
        fell_back = False if sent else bool(fallback(text))
        _journal(r, {"event": "offered", "at": _iso(t), "token": token, "review_id": rid,
                     "order_package_id": ask["order_package_id"], "directed": ask["directed"], "sent": sent,
                     "fallback_alert": fell_back, "expires_at": ask["expires_at"]})
        return {"state": "offered", "token": token, "sent": sent, "fallback_alert": fell_back}
    except Exception as exc:  # noqa: BLE001 -- an ask failure must never break the watcher pass
        logger.warning("trade_approvals: offer failed", exc_info=True)
        return {"state": "error", "detail": f"{type(exc).__name__}: {exc}"[:200]}


# ─────────────────────────────────────────────────────────────────────────── deciding

def render_ops(ask: Dict[str, Any]) -> str:
    params = json.dumps(ask.get("params") or {}, default=str, separators=(", ", ": "))
    params = params if len(params) <= 600 else params[:600] + "…"
    reason = " ".join(str(ask.get("reason") or "").split())[:420]
    return "\n".join([f"🛠 Ops action needs your OK (Tier {ask.get('tier')}): {ask.get('ops_action')}",
                      f"params: {params}", f"why: {reason}", f"asked by: {ask.get('session')}",
                      f"job {ask.get('job_id')} · expires {str(ask.get('expires_at'))[11:16]}Z",
                      "Approve runs it now on the VM, through the system's own scripts and checks."])


def offer_ops(job: Dict[str, Any], *, send: Optional[Sender] = None,
              fallback: Callable[[str], bool] = _fallback_alert, now: Optional[datetime] = None,
              root: Optional[Path] = None) -> Dict[str, Any]:
    """ONE Approve / Reject ask for a Tier-2 ops-channel job (MANAGER-VM-DIRECT-OPS). Same store, ``tapv`` buttons,
    operator-chat check, expiry and :func:`decide` as a trade ask; idempotent per job_id. Never raises."""
    try:
        r, t = root or _root(), now or _now()
        key = f"ops:{job['job_id']}"
        with _locked(r) as store:
            if key in store["by_review"]:
                tok = store["by_review"][key]
                return {"state": "already_offered", "token": tok,
                        "expires_at": (store["asks"].get(tok) or {}).get("expires_at")}
            token = secrets.token_hex(TOKEN_HEX // 2)
            ask = {"token": token, "kind": OPS_KIND, "review_id": key, "job_id": job["job_id"],
                   "ops_action": job.get("action"), "tier": job.get("tier"), "params": job.get("params"),
                   "reason": job.get("reason"), "session": job.get("session"), "symbol": "ops channel",
                   "created_at": _iso(t), "expires_at": _iso(t + timedelta(minutes=expiry_minutes())),
                   "state": PENDING}
            store["asks"][token] = ask
            store["by_review"][key] = token
        text = render_ops(ask)
        sent = False
        try:
            sent = bool((send or _default_sender)(text, keyboard(token)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("trade_approvals: ops send failed: %s", exc)
        fell_back = False if sent else bool(fallback(text))
        _journal(r, {"event": "offered", "at": _iso(t), "token": token, "review_id": key, "kind": OPS_KIND,
                     "job_id": job["job_id"], "sent": sent, "fallback_alert": fell_back,
                     "expires_at": ask["expires_at"]})
        return {"state": "offered", "token": token, "sent": sent, "fallback_alert": fell_back,
                "expires_at": ask["expires_at"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("trade_approvals: offer_ops failed", exc_info=True)
        return {"state": "error", "detail": f"{type(exc).__name__}: {exc}"[:200]}


def _ops_decided(ask: Dict[str, Any], choice: str, source: str, now: datetime) -> Tuple[bool, str]:
    """Hand an ops ask's decision to the ops channel (it queues or closes the job). Never raises."""
    try:
        from src.runtime import ops_actions
        quote = (f"Approved via {source} button: ops action {ask.get('ops_action')} "
                 f"(ops job {ask.get('job_id')}, ask {ask.get('token')})")
        return ops_actions.on_approval(str(ask.get("job_id")), choice, quote=quote, source=source, now=now)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trade_approvals: ops hand-off failed", exc_info=True)
        return False, f"ops hand-off failed: {type(exc).__name__}: {exc}"[:200]


def _write_spool(record: Dict[str, Any], root: Path) -> Path:
    d = spool_root(root) / da.RECORDS_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{record['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(tmp, path)
    return path


def build_record(ask: Dict[str, Any], *, source: str, now: datetime) -> Dict[str, Any]:
    d = ask["directed"]
    quote = (f"Approved via {source} button: {_action_text(ask)} on {ask.get('symbol') or ask.get('leg')} "
             f"({ask.get('order_package_id')}), review {ask['review_id']}, ask {ask['token']}")
    rec: Dict[str, Any] = {"schema": da.SCHEMA, "id": da.new_id(d["action"], now, secrets.token_hex(3)),
                           "created_at": _iso(now), "directed_by": DIRECTED_BY if source == "telegram"
                           else f"operator:{source}", "operator_quote": quote,
                           "order_package_id": ask["order_package_id"], "scope": "package",
                           "action": d["action"], "dry_run": False, "review_id": ask["review_id"],
                           "approval_token": ask["token"]}
    for k in ("level", "fraction"):
        if k in d:
            rec[k] = d[k]
    return rec


def decide(token: str, choice: str, *, authorised: bool, source: str = "telegram",
           now: Optional[datetime] = None, root: Optional[Path] = None) -> Dict[str, Any]:
    """Apply ONE operator decision. ``choice`` is ``approve`` or ``reject``. Returns ``{"outcome", "reply", ...}``.
    Outcomes: approved, rejected, expired, already_<state>, unknown, unauthorized, refused."""
    t, r = now or _now(), root or _root()
    if not authorised:
        return {"outcome": "unauthorized", "reply": "⛔ Unauthorised."}
    if choice not in ("approve", "reject"):
        return {"outcome": "refused", "reply": f"⚠️ Unknown choice {choice!r}; nothing was done."}
    with _locked(r) as store:
        ask = store["asks"].get(token)
        if ask is None:
            return {"outcome": "unknown", "reply": "⚠️ This approval is not known on the VM; nothing was done."}
        if ask["state"] != PENDING:
            return {"outcome": f"already_{ask['state']}", "token": token,
                    "reply": f"ℹ️ Already {ask['state']} at {ask.get('decided_at')}"
                             + (f" (record {ask.get('record_id')})" if ask.get("record_id") else "") + "."}
        exp = da._ts(ask.get("expires_at"))
        ev: Dict[str, Any] = {"event": "decided", "at": _iso(t), "token": token, "review_id": ask["review_id"],
                              "order_package_id": ask.get("order_package_id"), "source": source, "choice": choice}
        if exp is None or t > exp:
            ask.update(state=EXPIRED, decided_at=_iso(t), decided_via=source)
            ev["outcome"] = EXPIRED
            reply = (f"⌛ Expired at {ask.get('expires_at')}: nothing was executed. "
                     "A newer review will ask again if the call still stands.")
        elif choice == "reject":
            ask.update(state=REJECTED, decided_at=_iso(t), decided_via=source)
            ev["outcome"] = REJECTED
            if ask.get("kind") == OPS_KIND:
                _ops_decided(ask, "reject", source, t)
            reply = f"✖ Rejected: {_action_text(ask)} on {ask.get('symbol') or ask.get('leg')}. Nothing was executed."
        elif ask.get("kind") == OPS_KIND:
            ok, detail = _ops_decided(ask, "approve", source, t)
            if ok:
                ask.update(state=APPROVED, decided_at=_iso(t), decided_via=source)
                ev.update(outcome=APPROVED, job_id=ask.get("job_id"))
                reply = f"✅ Approved: {ask.get('ops_action')} ({ask.get('job_id')}) is queued on the VM."
            else:
                ask.update(state=REFUSED, decided_at=_iso(t), decided_via=source, refused=[detail])
                ev.update(outcome=REFUSED, detail=[detail])
                reply = f"⚠️ Not run: {detail}"
        else:
            record = build_record(ask, source=source, now=t)
            probs = da.problems(record, path=da.record_path(record["id"]))
            if probs:
                ask.update(state=REFUSED, decided_at=_iso(t), decided_via=source, refused=probs[:4])
                ev.update(outcome=REFUSED, detail=probs[:4])
                reply = f"⚠️ Refused before execution ({', '.join(probs[:3])}); nothing was executed."
            else:
                _write_spool(record, r)
                ask.update(state=APPROVED, decided_at=_iso(t), decided_via=source, record_id=record["id"])
                ev.update(outcome=APPROVED, record_id=record["id"])
                reply = (f"✅ Approved: {_action_text(ask)} on {ask.get('symbol') or ask.get('leg')}. "
                         f"Executing now on the live trader (record {record['id']}); "
                         "the per-account result follows on the trades channel.")
        _journal(r, ev)
    return {"outcome": ev["outcome"], "token": token, "record_id": ask.get("record_id"), "reply": reply}


def handle_callback(raw: str, *, authorised: bool, now: Optional[datetime] = None,
                    root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """A ``tapv:`` tap -> :func:`decide`. None for callback data that is not ours."""
    m = CB_RE.match(raw or "")
    if not m:
        return None if not (raw or "").startswith(f"{CB_PREFIX}:") else {
            "outcome": "refused", "reply": "⚠️ Malformed approval button; nothing was done."}
    return decide(m.group(2), "approve" if m.group(1) == "a" else "reject", authorised=authorised,
                  source="telegram", now=now, root=root)
