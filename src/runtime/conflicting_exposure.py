"""Conflicting exposure: one symbol held LONG and SHORT at once across the books (row CONFLICTING-EXPOSURE-ALERT).

Operator, 2026-11-11 ~22:30Z (verbatim, on the checklist row): *"it should, like, raise at least a red flag for
review ... I'm not saying that we should have a rule against it ... but we should understand what circumstances
justify doing that, and if it's not the situation, then it should be like an alert that we probably need to close
one side of that trade."*

What this does, and nothing more:

* **Detects.** Every open leg on every book: the trade journal's open ``trades`` rows (real money, paper, the
  mirrors, Alpaca, IB; one row per account) plus the prop journal's filled ``prop_tickets`` (one per prop
  account). A symbol with at least one open LONG package and at least one open SHORT package is a conflict.
  The per-account opposite-direction guard (``src/prop/breakout_executor.py``, #24402) already stops ONE account
  holding both sides; this sees ACROSS accounts and strategies, which nothing did.
* **Alerts once.** One Telegram alert per distinct conflict (symbol + the set of packages on each side), through
  the ``telegram_channels`` chokepoint, so it lands in the alert ledger. It names each leg, its timeframe, its
  accounts and its open R. A conflict that resolves and comes back alerts again; a standing one never repeats.
* **Queues a review.** ``live_review_due`` adds the due event ``conflicting_exposure`` (level = the conflict key)
  to every package in the conflict, so the live-trade review prices "keep both" vs "close one side" for the
  package set, once per conflict.

Gates this adds or changes: **none**. It is an alert, never a gate: it refuses no order, closes nothing, moves no
bracket and never halts anything (Prime Directive rule 7). Every failure is contained and reported as
``could_not_look``; a book that could not be read is named, never read as "no conflict".
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

EVENT = "conflicting_exposure"
ALERT_KIND = "alert"
STATE_FILENAME = "conflicting_exposure_state.json"

_LONG = ("long", "buy")
_SHORT = ("short", "sell")


def side_of(direction: Any) -> Optional[str]:
    d = str(direction or "").strip().lower()
    return "long" if d in _LONG else "short" if d in _SHORT else None


def normalize_symbol(symbol: Any) -> str:
    """``SOL/USDT:USDT`` / ``SOLUSDT`` / ``sol-usdt`` -> ``SOLUSDT``. Equities pass through upper-cased."""
    s = str(symbol or "").strip().upper()
    s = s.split(":")[0]
    return re.sub(r"[^A-Z0-9]", "", s)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


_TF_SUFFIX = re.compile(r"_(\d+)(m|h|d)$")


def leg_timeframes(path: Optional[str] = None) -> Dict[str, str]:
    """strategy -> its declared ``timeframe`` from ``config/strategies.yaml`` ({} when unreadable)."""
    try:
        import yaml
        if path is None:
            from src.utils.paths import repo_root
            path = os.path.join(repo_root(), "config", "strategies.yaml")
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        return {str(k): str(v.get("timeframe")) for k, v in (doc.get("strategies") or {}).items()
                if isinstance(v, dict) and v.get("timeframe")}
    except Exception as exc:  # noqa: BLE001  # allow-silent: the timeframe falls back to the name suffix, labelled
        logger.debug("conflicting_exposure: strategies.yaml unreadable: %s", exc)
        return {}


def timeframe_of(strategy: Any, declared: Dict[str, str]) -> Optional[str]:
    s = str(strategy or "")
    if s in declared:
        return declared[s]
    m = _TF_SUFFIX.search(s)
    return f"{m.group(1)}{m.group(2)}" if m else None


def open_r(direction: Any, entry: Any, sl: Any, mark: Any) -> Optional[float]:
    """Open R from a mark: (mark - entry) x side / |entry - sl|. None when any input is missing."""
    side = side_of(direction)
    e, s, m = _f(entry), _f(sl), _f(mark)
    if side is None or e is None or s is None or m is None or e == s:
        return None
    sign = 1.0 if side == "long" else -1.0
    return round((m - e) * sign / abs(e - s), 2)


def read_open_legs(db_path: Optional[str] = None,
                   mark_fn: Optional[Callable[[Any], Optional[float]]] = None,
                   strategies_path: Optional[str] = None) -> Dict[str, Any]:
    """Open legs on every book, one record per order package (its accounts listed).

    ``books`` keeps the two reads apart (``journal`` / ``prop``), each ``read`` or ``could_not_look``; the
    envelope ``state`` is ``read`` only when both were read. A failed book is never an empty book.
    """
    if db_path is None:
        try:
            from src.utils.paths import trade_journal_db_path
            db_path = str(trade_journal_db_path())
        except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
            return {"state": "could_not_look", "reason": f"db_path_unresolved: {exc}", "books": {}, "legs": []}
    declared = leg_timeframes(strategies_path)
    pkgs: Dict[str, Dict[str, Any]] = {}
    books: Dict[str, Dict[str, Any]] = {}

    def _pkg(pkg: str, strategy: Any, symbol: Any, direction: Any, entry: Any, sl: Any) -> Dict[str, Any]:
        return pkgs.setdefault(pkg, {
            "order_package_id": pkg, "leg": strategy, "symbol": normalize_symbol(symbol),
            "direction": side_of(direction), "entry": _f(entry), "sl": _f(sl),
            "timeframe": timeframe_of(strategy, declared), "accounts": [], "account_classes": {}})

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT order_package_id, strategy_name, symbol, direction, entry_price, stop_loss, "
                "account_id, account_class FROM trades WHERE status = 'open' "
                "AND order_package_id IS NOT NULL AND order_package_id != ''").fetchall()
            has_prop = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prop_tickets'").fetchone()
            prop_rows = conn.execute(
                "SELECT order_package_id, strategy, symbol, direction, entry, sl, account_id FROM prop_tickets "
                "WHERE status = 'filled' AND order_package_id IS NOT NULL AND order_package_id != ''"
            ).fetchall() if has_prop else []
        finally:
            conn.close()
        books["journal"] = {"state": "read", "rows": len(rows)}
        books["prop"] = {"state": "read" if has_prop else "table_absent", "rows": len(prop_rows)}
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return {"state": "could_not_look", "reason": f"journal_unreadable: {type(exc).__name__}: {exc}",
                "books": books, "legs": []}
    for r in rows:
        d = _pkg(str(r["order_package_id"]), r["strategy_name"], r["symbol"], r["direction"],
                 r["entry_price"], r["stop_loss"])
        aid = str(r["account_id"])
        if aid not in d["accounts"]:
            d["accounts"].append(aid)
            d["account_classes"][aid] = r["account_class"]
    for r in prop_rows:
        d = _pkg(str(r["order_package_id"]), r["strategy"], r["symbol"], r["direction"], r["entry"], r["sl"])
        aid = str(r["account_id"])
        if aid not in d["accounts"]:
            d["accounts"].append(aid)
            d["account_classes"][aid] = "prop"
    marks: Dict[str, Optional[float]] = {}
    for d in pkgs.values():
        d["open_r"], d["open_r_state"] = None, "could_not_look"
        if mark_fn is None:
            d["open_r_reason"] = "no_mark_source_supplied"
            continue
        sym = d["symbol"]
        if sym not in marks:
            try:
                marks[sym] = _f(mark_fn(sym))
            except Exception as exc:  # noqa: BLE001  # allow-silent: one unread mark is labelled, never 0
                marks[sym] = None
                logger.debug("conflicting_exposure: mark read failed for %s: %s", sym, exc)
        r = open_r(d["direction"], d["entry"], d["sl"], marks[sym])
        if r is None:
            d["open_r_reason"] = "mark_or_bracket_missing"
        else:
            d["open_r"], d["open_r_state"], d["mark"] = r, "estimated", marks[sym]
    return {"state": "read", "reason": None, "books": books, "legs": list(pkgs.values())}


def conflict_key(symbol: str, legs: Iterable[Dict[str, Any]]) -> str:
    """``<SYMBOL>#<sha1 of the sorted long and short package ids>``: one key per distinct conflict."""
    longs = sorted(str(x["order_package_id"]) for x in legs if x.get("direction") == "long")
    shorts = sorted(str(x["order_package_id"]) for x in legs if x.get("direction") == "short")
    h = hashlib.sha1(f"L={','.join(longs)};S={','.join(shorts)}".encode()).hexdigest()[:10]
    return f"{symbol}#{h}"


def find_conflicts(legs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Symbols with an open LONG package and an open SHORT package. Pure."""
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for leg in legs:
        if leg.get("direction") in ("long", "short") and leg.get("symbol"):
            by_sym.setdefault(leg["symbol"], []).append(leg)
    out = []
    for sym in sorted(by_sym):
        group = by_sym[sym]
        sides = {x["direction"] for x in group}
        if sides != {"long", "short"}:
            continue
        group = sorted(group, key=lambda x: (x["direction"], str(x.get("leg")), str(x["order_package_id"])))
        out.append({"symbol": sym, "key": conflict_key(sym, group), "legs": group,
                    "packages": [x["order_package_id"] for x in group]})
    return out


def why(conflict: Dict[str, Any], pkg: str) -> str:
    other = [x for x in conflict["legs"] if x["order_package_id"] != pkg]
    me = next((x for x in conflict["legs"] if x["order_package_id"] == pkg), {})
    opp = [x for x in other if x.get("direction") != me.get("direction")]
    names = ", ".join(f"{x.get('leg')} {x.get('direction')} {x.get('timeframe') or '?'}" for x in opp)
    return (f"{conflict['symbol']} held both ways across the books: this {me.get('direction')} vs {names}. "
            "Review keep both (timeframe separation) vs close one side.")


def _fmt_r(v: Any) -> str:
    return "—" if v is None else f"{v:+.2f}R"


def render_alert(conflict: Dict[str, Any]) -> str:
    """The Telegram text. Open R is ESTIMATED from the bot's mark; a missing one reads "—"."""
    lines = [f"⚠️ CONFLICTING EXPOSURE: {conflict['symbol']} is held LONG and SHORT at once",
             "Alert only: nothing is closed or blocked. A live review is queued for the package set."]
    for x in conflict["legs"]:
        accts = ", ".join(x.get("accounts") or []) or "—"
        lines.append(f"• {str(x.get('direction')).upper()} {x.get('leg')} ({x.get('timeframe') or '—'}) "
                     f"on {accts}: open {_fmt_r(x.get('open_r'))} est, pkg {x['order_package_id']}")
    lines.append(f"key {conflict['key']}")
    return "\n".join(lines)


def state_path() -> Path:
    if os.environ.get("CONFLICTING_EXPOSURE_STATE_PATH"):
        return Path(os.environ["CONFLICTING_EXPOSURE_STATE_PATH"])
    from src.utils.paths import runtime_logs_dir
    return Path(runtime_logs_dir()) / STATE_FILENAME


def _read_state(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text())
        return doc if isinstance(doc, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001  # allow-silent: an unreadable state re-alerts (fails toward telling)
        logger.warning("conflicting_exposure: state unreadable (%s) — re-alerting standing conflicts", exc)
        return {}


def _default_send(text: str) -> bool:
    from src.runtime import telegram_channels
    return bool(telegram_channels.send(ALERT_KIND, text))


def fill_open_r(found: Dict[str, Any], mark_fn: Callable[[Any], Optional[float]]) -> None:
    """Estimate open R for the legs of each conflict that lack one (only the conflicting symbols are marked)."""
    marks: Dict[str, Optional[float]] = {}
    for c in found.get("conflicts") or []:
        for x in c.get("legs") or []:
            if x.get("open_r") is not None:
                continue
            sym = x.get("symbol")
            if sym not in marks:
                try:
                    marks[sym] = _f(mark_fn(sym))
                except Exception as exc:  # noqa: BLE001  # allow-silent: one unread mark is labelled, never 0
                    marks[sym] = None
                    logger.debug("conflicting_exposure: mark read failed for %s: %s", sym, exc)
            r = open_r(x.get("direction"), x.get("entry"), x.get("sl"), marks[sym])
            if r is not None:
                x["open_r"], x["open_r_state"], x["mark"] = r, "estimated", marks[sym]
                x.pop("open_r_reason", None)


def alert(found: Dict[str, Any], *, path: Optional[Path] = None,
          send: Optional[Callable[[str], bool]] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """ONE send per NEW conflict key; resolved keys are forgotten so a recurrence alerts again.

    ``found`` = ``{"state", "conflicts"}``. On ``could_not_look`` nothing is sent and the state is untouched
    (a failed read is not a resolution). A send that does not confirm leaves the key unrecorded, so the next
    pass retries it. Never raises.
    """
    now = now or datetime.now(timezone.utc)
    rec: Dict[str, Any] = {"at": now.isoformat(), "state": found.get("state"), "sent": [], "standing": [],
                           "failed": []}
    if found.get("state") != "read":
        rec["reason"] = found.get("reason")
        return rec
    try:
        path = path or state_path()
        send = send or _default_send
        st = _read_state(path)
        known: Dict[str, Any] = st.get("alerted") or {}
        live = {c["key"]: c for c in found.get("conflicts") or []}
        kept = {k: v for k, v in known.items() if k in live}
        for k, c in live.items():
            if k in kept:
                rec["standing"].append(k)
                continue
            try:
                ok = send(render_alert(c))
            except Exception as exc:  # noqa: BLE001  # allow-silent: retried next pass, recorded here
                ok = False
                logger.warning("conflicting_exposure: send failed for %s: %s", k, exc)
            if ok:
                kept[k] = {"first_alerted_at": now.isoformat(), "symbol": c["symbol"], "packages": c["packages"]}
                rec["sent"].append(k)
            else:
                rec["failed"].append(k)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updated_at": now.isoformat(), "alerted": kept}, indent=1, sort_keys=True))
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: contained; the review event still fires
        logger.warning("conflicting_exposure: alert pass failed: %s", exc)
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def detect(db_path: Optional[str] = None,
           mark_fn: Optional[Callable[[Any], Optional[float]]] = None) -> Dict[str, Any]:
    """Read every book and return ``{state, reason, books, conflicts}``. Never raises."""
    try:
        legs = read_open_legs(db_path, mark_fn)
    except Exception as exc:  # noqa: BLE001  # allow-silent: surfaced as could_not_look
        return {"state": "could_not_look", "reason": f"{type(exc).__name__}: {exc}", "books": {}, "conflicts": []}
    if legs["state"] != "read":
        return {"state": legs["state"], "reason": legs.get("reason"), "books": legs.get("books"), "conflicts": []}
    return {"state": "read", "reason": None, "books": legs["books"], "open_legs": len(legs["legs"]),
            "conflicts": find_conflicts(legs["legs"])}
