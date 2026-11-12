"""ONE Telegram delivery policy: which messages reach Telegram, and which are only RECORDED.

Checklist row ``TELEGRAM-TRIM`` (Tier 2, operator 2026-11-04; verbatim quote in
``config/telegram_policy.yaml``). Three decisions, all read from that one file:

A. **Recurring posts are off.** A kind in ``recurring_off`` (hourly health check,
   hourly trades snapshot, daily heartbeat, the hourly work digest) is recorded,
   not sent. Event-driven alerts are never recurring: :func:`load_policy`
   refuses any ``telegram_channels.UNMUTABLE`` kind in that list.
B. **One trades-channel ping per ORDER-PACKAGE event**, classed from
   ``config/accounts.yaml`` (``account_class`` + ``paper_role``, field beats
   name): real money and prop send (real money noted "real money + mirror" when
   its Stage-2 mirror carries the leg); a paper-PORTFOLIO account sends only for
   a leg real money does not trade; testing paper sends nothing. Two producer
   paths (journal observer + execute/order_monitor enqueue) and N accounts
   collapse to one ping by a cross-process ``(package, event)`` claim.
C. **Nothing is lost.** Every suppressed message is appended to
   THE alert ledger (``src/runtime/alerts_ledger``) with ``delivered:
   suppressed_by_policy`` (``GET /api/bot/alerts``, diag ``log_file?name=alerts_ledger``).

Fail-OPEN everywhere: an unreadable policy, accounts file or claim store SENDS.
On a notification path a broken filter must announce itself as a duplicate,
never as silence (the ``telegram_settings`` rule).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "telegram_policy.yaml"
ACCOUNTS_PATH = REPO_ROOT / "config" / "accounts.yaml"

#: account classes (the four the trades policy names, plus unknown)
REAL_MONEY = "real_money"
PROP = "prop"
PAPER_PORTFOLIO = "paper_portfolio"
TESTING_PAPER = "testing_paper"
UNKNOWN = "unknown_account"

#: event classes — both producer kind families fold onto these
_EVENT_OF_KIND = {
    "trade_opened": "open", "trade-open": "open", "demotrade": "open",
    "trade_closed": "close", "trade-close": "close",
    "trade_updated": "update", "trade-update": "update",
}

SUPPRESSED = "suppressed_by_policy"

_cache_lock = threading.Lock()
_cache: Dict[str, tuple] = {}


def _load_yaml_cached(path: Path) -> Any:
    """YAML at *path*, re-read when its mtime changes. Raises on failure."""
    st = path.stat()
    key = str(path)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime_ns:
            return hit[1]
    import yaml  # lazy: some VM units run under the system python

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    with _cache_lock:
        _cache[key] = (st.st_mtime_ns, data)
    return data


def load_policy(path: Optional[Path] = None) -> Dict[str, Any]:
    """The policy, validated. ``{}`` when unreadable (== send everything)."""
    try:
        raw = _load_yaml_cached(path or Path(os.environ.get("TELEGRAM_POLICY_PATH") or POLICY_PATH))
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_policy: policy unreadable (%s) — sending everything",
                       type(exc).__name__)
        return {}
    if not isinstance(raw, dict):
        return {}
    from src.runtime.telegram_channels import UNMUTABLE

    off = [str(k) for k in (raw.get("recurring_off") or [])]
    bad = sorted(set(off) & set(UNMUTABLE))
    if bad:
        # An alert can never be "recurring". Refuse the whole list rather than
        # silence an alert because someone listed it.
        logger.error("telegram_policy: recurring_off names alert kinds %s — ignoring the list", bad)
        off = []
    return {**raw, "recurring_off": off}


# ── A. recurring ───────────────────────────────────────────────────────────

def recurring_off(kind: str, policy: Optional[Mapping] = None) -> bool:
    """Is *kind* a recurring post the operator turned off?"""
    pol = load_policy() if policy is None else policy
    return str(kind or "") in set(pol.get("recurring_off") or [])


def digest_event_lines(msgs: list, policy: Optional[Mapping] = None,
                       accounts: Optional[Mapping] = None) -> list:
    """The attention messages of an hourly digest that are EVENTS (still sent).

    TELEGRAM-TRIM phase 3 (operator popup 2026-11-10 "Keep b, trim c"): a soak-state message (prefix in
    ``digest_paper_soak_prefixes``, default ``🧪``) is dropped unless it names an account that is NOT testing
    paper. Soaks run on the Stage-1 testing-paper floor only (OPERATING-PLAN § 2), so these lines are paper
    noise; they stay in the ledger / UI (the digest itself is recorded)."""
    pol = load_policy() if policy is None else policy
    drop = tuple(pol.get("digest_event_drop_prefixes") or ("📋", "🔎"))
    soak = tuple(pol.get("digest_paper_soak_prefixes") or ())
    out = []
    for m in (msgs or []):
        if not m or str(m).startswith(drop):
            continue
        if soak and str(m).startswith(soak):
            named = accounts_named(str(m), accounts)
            if not any(account_class(a, accounts) != TESTING_PAPER for a in named):
                continue
        out.append(m)
    return out


def accounts_named(text: str, accounts: Optional[Mapping] = None) -> List[str]:
    """The configured account ids that appear in *text* as whole tokens (``alpaca_paper`` never matches inside
    ``alpaca_paper_x``). Order-free; empty when none is named."""
    import re

    accs = _accounts() if accounts is None else accounts
    t = str(text or "")
    return sorted(a for a in accs if re.search(r"(?<![A-Za-z0-9_])" + re.escape(str(a)) + r"(?![A-Za-z0-9_])", t))


# ── C. paper-account alerts: the manager first, the operator only if unfixed ──
#
# Operator popup 2026-11-10 ~09:45Z "Only me; you if unfixed (Recommended)", after the operator's 09:40Z
# "You should still be getting all those pings, so that if there's an issue on a paper account you can fix it.
# I just want to cut down the noise so that if I see an alert I can be more sure that it's really worth my
# attention". An ALERT about testing-paper accounts only is recorded ``suppressed_by_policy`` with priority
# HIGH (so ``alerts_ledger.wakes_manager`` wakes the manager to fix it) instead of reaching Telegram; when the
# SAME alert is still firing ``escalate_after_minutes`` after its first sighting, the operator gets it ONCE as
# a red flag. Narrow by construction and fail-open (send): never the trades channel, never an operator ask
# (``_PAPER_ALERT_NEVER_KINDS``), only text that opens with an alert level marker, and only when EVERY account
# it names is testing paper (a mirror / real-money / prop account, or no account at all, sends as before).

PAPER_ALERT_MANAGER, PAPER_ALERT_ESCALATE, PAPER_ALERT_SEND = "manager", "escalate", "send"
_PAPER_ALERT_NEVER_KINDS = frozenset({"decision", "claude_ping", "system_action", "red_flag"})
_ALERT_MARKER = ("🔴", "🟡", "🟠", "⚠️", "⚠", "🚨", "❌", "‼️", "[WARN]", "[ERROR]", "[CRITICAL]", "[ALERT]",
                 "WARN", "ERROR", "CRITICAL")


def _alert_signature(kind: Optional[str], text: str) -> str:
    import hashlib
    import re

    first = re.sub(r"<[^>]+>", "", str(text or "")).strip().splitlines()[0] if str(text or "").strip() else ""
    masked = re.sub(r"\d[\d.,]*", "#", first)[:160]   # a number of any size is one token
    return hashlib.sha256(f"{kind or 'unclassified'}|{masked}".encode()).hexdigest()[:20]


def paper_alert_route(kind: Optional[str], text: str, channel: Optional[str], *,
                      now: Optional[float] = None, policy: Optional[Mapping] = None,
                      accounts: Optional[Mapping] = None, directory: Optional[Path] = None) -> str:
    """``send`` (not a paper-only alert, or the policy is off) | ``manager`` (record suppressed, priority high:
    the manager is woken to fix it) | ``escalate`` (still firing after the manager's window: send ONCE, flagged).
    Never raises: any failure answers ``send``."""
    import json as _json
    import re
    import time as _time

    try:
        pol = load_policy() if policy is None else policy
        cfg = pol.get("paper_alerts") or {}
        if str(cfg.get("route") or "") != "manager_then_escalate":
            return PAPER_ALERT_SEND
        if str(channel or "") == "trades" or str(kind or "") in _PAPER_ALERT_NEVER_KINDS:
            return PAPER_ALERT_SEND
        head = re.sub(r"<[^>]+>", "", str(text or "")).lstrip()
        if not head.startswith(_ALERT_MARKER):
            return PAPER_ALERT_SEND
        named = accounts_named(text, accounts)
        if not named or any(account_class(a, accounts) != TESTING_PAPER for a in named):
            return PAPER_ALERT_SEND
        t = float(now if now is not None else _time.time())
        after = float(cfg.get("escalate_after_minutes") or 120) * 60.0
        reset = float(cfg.get("reset_after_hours") or 24) * 3600.0
        d = (directory or _claims_dir()) / "paper_alerts"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{_alert_signature(kind, text)}.json"
        st = _json.loads(f.read_text()) if f.exists() else {}
        if not st or st.get("last") is None or t - float(st["last"]) > reset:
            st = {"first": t, "last": t, "flagged": False, "n": 1}
            route = PAPER_ALERT_MANAGER
        else:
            st["last"], st["n"] = t, int(st.get("n") or 0) + 1
            first = float(st["first"]) if st.get("first") is not None else t
            if not st.get("flagged") and t - first >= after:
                st["flagged"], route = True, PAPER_ALERT_ESCALATE
            else:
                route = PAPER_ALERT_MANAGER
        tmp = f.with_suffix(".tmp")
        tmp.write_text(_json.dumps(st))
        tmp.replace(f)
        return route
    except Exception as exc:  # noqa: BLE001 -- a broken policy or store over-sends, never silences
        logger.warning("telegram_policy: paper-alert route failed (%s) — sending", exc)
        return PAPER_ALERT_SEND


def escalation_text(text: str, minutes: float) -> str:
    return (f"🚩 STILL FAILING after the manager's attempt (testing-paper alert, first seen about "
            f"{int(minutes)} min ago; the manager was woken at the first one):\n{text}")


# ── B. account classification (config/accounts.yaml) ──────────────────────

def _accounts(path: Optional[Path] = None) -> Dict[str, dict]:
    try:
        raw = _load_yaml_cached(path or ACCOUNTS_PATH)
        accts = raw.get("accounts", raw) if isinstance(raw, dict) else {}
        return {str(k): v for k, v in accts.items() if isinstance(v, dict)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_policy: accounts.yaml unreadable (%s)", type(exc).__name__)
        return {}


def account_class(account: Optional[str], accounts: Optional[Mapping] = None) -> str:
    """real_money · prop · paper_portfolio · testing_paper · unknown_account."""
    accts = _accounts() if accounts is None else accounts
    cfg = accts.get(str(account or ""))
    if not isinstance(cfg, dict):
        return UNKNOWN
    cls = str(cfg.get("account_class") or "").strip().lower()
    if cls == "real_money":
        return REAL_MONEY
    if cls == "prop":
        return PROP
    if cls == "paper":
        if str(cfg.get("paper_role") or "").strip().lower() == "portfolio":
            return PAPER_PORTFOLIO
        return TESTING_PAPER
    return UNKNOWN


def _roster(cfg: Mapping) -> set:
    s = cfg.get("strategies") if isinstance(cfg, Mapping) else None
    return {str(x) for x in s} if isinstance(s, list) else set()


def _mirror_pairs() -> Dict[str, str]:
    """mirror -> real-money primary (the one src-side pairing constant)."""
    try:
        from src.runtime.mirror_pairs import MIRROR_PAIRS

        return dict(MIRROR_PAIRS)
    except Exception:  # noqa: BLE001
        return {}


def _proxy_underlying() -> Dict[str, Dict[str, str]]:
    """mirror -> {real-money proxy leg: full-size leg it carries instead}."""
    try:
        from scripts.ops.strategy_status import MIRROR_PROXY_UNDERLYING

        return {k: dict(v) for k, v in MIRROR_PROXY_UNDERLYING.items()}
    except Exception:  # noqa: BLE001
        return {}


def mirror_note(account: str, strategy: Optional[str],
                accounts: Optional[Mapping] = None) -> Optional[str]:
    """For a real-money *account*: the mirror carrying the same leg, else None."""
    accts = _accounts() if accounts is None else accounts
    proxies = _proxy_underlying()
    for mirror, primary in _mirror_pairs().items():
        if primary != account or mirror not in accts:
            continue
        rm = _roster(accts[mirror])
        leg = str(strategy or "")
        if leg in rm or proxies.get(mirror, {}).get(leg) in rm:
            return mirror
    return None


def portfolio_leg_on_real_money(account: str, strategy: Optional[str],
                                accounts: Optional[Mapping] = None) -> bool:
    """For a paper-portfolio *account*: does its real-money primary trade this leg
    (directly, or as the affordability proxy this leg replaces)?"""
    accts = _accounts() if accounts is None else accounts
    primary = _mirror_pairs().get(account)
    if not primary or primary not in accts:
        return False
    rp = _roster(accts[primary])
    leg = str(strategy or "")
    if leg in rp:
        return True
    return any(under == leg and proxy in rp
               for proxy, under in _proxy_underlying().get(account, {}).items())


@dataclass(frozen=True)
class TradeDecision:
    send: bool
    reason: str
    account_class: str
    note: Optional[str] = None   # e.g. "real money + mirror (bybit_portfolio)"
    dedupe_key: Optional[str] = None


def trade_decision(kind: str, *, account: Optional[str], strategy: Optional[str],
                   symbol: Optional[str] = None, package_id: Optional[str] = None,
                   priority: Optional[str] = None, now: Optional[float] = None,
                   policy: Optional[Mapping] = None,
                   accounts: Optional[Mapping] = None) -> TradeDecision:
    """Class decision for one trades-channel event. Does NOT claim the dedupe
    key — :func:`should_send_trade` does both."""
    pol = load_policy() if policy is None else policy
    tp = pol.get("trades") or {}
    if not tp:
        return TradeDecision(True, "no_policy", UNKNOWN)
    cls = account_class(account, accounts)
    # High/urgent flags bypass the filter, EXCEPT for testing paper (operator 2026-11-10: no paper-testing
    # trade updates; a not-applied flag on a paper leg is recorded in the ledger, never pinged).
    if (str(priority or "").lower() in {str(p).lower() for p in tp.get("bypass_priorities") or []}
            and not (cls == TESTING_PAPER and str(tp.get(cls) or "send") == "suppress")):
        return TradeDecision(True, "priority_bypass", cls)
    rule = str(tp.get(cls) or "send")
    if rule == "suppress":
        return TradeDecision(False, f"{cls}_suppressed", cls)
    note = None
    if cls == PAPER_PORTFOLIO and rule == "send_if_not_on_real_money":
        if portfolio_leg_on_real_money(str(account), strategy, accounts):
            return TradeDecision(False, "covered_by_real_money_ping", cls)
        note = "paper portfolio only (not on real money yet)"
    elif cls == REAL_MONEY:
        m = mirror_note(str(account), strategy, accounts)
        if m:
            note = f"real money + mirror ({m})"
    return TradeDecision(True, f"{cls}_send", cls, note,
                         _dedupe_key(kind, package_id, strategy, symbol, now, tp))


def _dedupe_key(kind: str, package_id: Optional[str], strategy: Optional[str],
                symbol: Optional[str], now: Optional[float], tp: Mapping) -> str:
    ev = _EVENT_OF_KIND.get(str(kind or ""), str(kind or ""))
    t = time.time() if now is None else now
    if package_id:
        parts = ["pkg", str(package_id), ev]
        if ev == "update":
            parts.append(str(int(t // (60 * float(tp.get("update_bucket_minutes") or 10)))))
    else:
        parts = ["nopkg", str(strategy or "?"), str(symbol or "?"), ev,
                 str(int(t // (60 * float(tp.get("no_package_bucket_minutes") or 5))))]
    return "|".join(parts)


def _claims_dir() -> Path:
    if os.environ.get("TELEGRAM_POLICY_CLAIMS_DIR"):
        return Path(os.environ["TELEGRAM_POLICY_CLAIMS_DIR"])
    from src.utils.paths import runtime_state_dir

    return runtime_state_dir() / "telegram_policy_claims"


def claim(key: str, directory: Optional[Path] = None) -> bool:
    """First claimer of *key* wins, across processes (O_EXCL create). A store
    that cannot be written CLAIMS (over-send, never silence)."""
    try:
        d = directory or _claims_dir()
        d.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(key.encode("utf-8")).hexdigest()
        fd = os.open(str(d / name), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        _maybe_prune(d)
        return True
    except FileExistsError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_policy: claim store failed (%s) — sending", type(exc).__name__)
        return True


def _maybe_prune(d: Path, keep_s: float = 7 * 86400) -> None:
    try:
        if hash(time.time()) % 50:   # ~1 in 50 claims
            return
        cut = time.time() - keep_s
        for p in d.iterdir():
            if p.stat().st_mtime < cut:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def should_send_trade(kind: str, text: str = "", **kw) -> TradeDecision:
    """Decide + claim + record. The one call a trades producer makes.

    Returns the decision; when it is not sent, the message is already recorded
    in the suppressed ledger. Never raises (fails open)."""
    try:
        source = kw.pop("source", None)   # the trade-update mechanism label: ledger field only
        d = trade_decision(kind, **kw)
        if d.send and d.dedupe_key and not claim(d.dedupe_key):
            d = TradeDecision(False, "duplicate_package_event", d.account_class,
                              d.note, d.dedupe_key)
        if not d.send:
            record_suppressed(kind, text, reason=d.reason, priority=kw.get("priority"),
                              account=kw.get("account"),
                              strategy=kw.get("strategy"), symbol=kw.get("symbol"),
                              package_id=kw.get("package_id"), account_class=d.account_class,
                              **({"source": source} if source else {}))
        return d
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_policy: trade decision failed (%s) — sending", exc)
        return TradeDecision(True, "policy_error", UNKNOWN)


def rejection_ledger_only(account: Optional[str], *, accounts: Optional[Mapping] = None,
                          policy: Optional[Mapping] = None) -> bool:
    """Prime Directive rule 4 as amended 2026-11-04: a testing-paper rejection is
    recorded (operator_alerts ledger) but not pinged."""
    pol = load_policy() if policy is None else policy
    rule = (pol.get("rejections") or {}).get("testing_paper")
    return rule == "ledger_only" and account_class(account, accounts) == TESTING_PAPER


# ── C. the suppressed ledger = the alert ledger ────────────────────────────
# A suppressed message is recorded in THE alert ledger (src/runtime/alerts_ledger,
# ALERT-LEDGER-TO-MANAGER) with delivered="suppressed_by_policy" — one event log,
# served at GET /api/bot/alerts and diag log_file?name=alerts_ledger.

def suppressed_log_path() -> Path:
    from src.runtime import alerts_ledger

    return alerts_ledger.ledger_path()


def record_suppressed(kind: str, text: str, *, reason: str, path: Optional[Path] = None,
                      channel: Optional[str] = None, priority: Optional[str] = None,
                      **fields: Any) -> bool:
    """Append one ``delivered: suppressed_by_policy`` row to the alert ledger.
    Best-effort (the ledger's own contract): never raises."""
    try:
        from src.runtime import alerts_ledger
        from src.runtime.telegram_channels import channel_for

        ch = channel or channel_for(kind)
        return alerts_ledger.append(kind, ch, text, delivered=SUPPRESSED, path=path, priority=priority,
                                    extra={"reason": str(reason), **fields})
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram_policy: suppressed-ledger append failed: %s", exc)
        return False


__all__ = [
    "load_policy", "recurring_off", "digest_event_lines", "account_class",
    "mirror_note", "portfolio_leg_on_real_money", "trade_decision", "should_send_trade",
    "claim", "rejection_ledger_only", "record_suppressed", "suppressed_log_path",
    "accounts_named", "paper_alert_route", "escalation_text", "PAPER_ALERT_MANAGER", "PAPER_ALERT_ESCALATE",
    "PAPER_ALERT_SEND",
    "TradeDecision", "SUPPRESSED",
]
