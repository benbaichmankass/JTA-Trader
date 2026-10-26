"""Trading-desk WAKE, VM side (DESK-6 follow-up): a gated hour -> ONE ops-flags comment -> manager.

Operator, 2026-10-26 ~16:30Z: the hourly desk wake should be triggered from the system itself,
through the same channel as the other triggers, with the VM holding the timer and knowing when the
hour holds something tradable. This replaces the hourly spawner routine (a fresh Sonnet session at
$0.34-0.47 a wake, fired regardless of state). Model: ``live_review_wake_post`` (same credential,
same ops-flags PR, same single-flight daemon thread, same receipt discipline).

Flow, once per 1h bar:

1. read ``comms/desk/latest_scan.json`` on ``desk/decisions`` (``desk-scan-packet.yml`` writes it at
   :03), then the packet it points at; verify the packet's sha against the pointer;
2. GATE (``evaluate_gate``): wake only when the hour holds something tradable, each reason named;
3. post ONE ``desk-wake`` marker comment on the ops-flags PR, deduped per bar. The manager is
   subscribed to that PR; on the marker it ``create_session``s the wake exactly as
   ``.claude/skills/trading-desk/SKILL.md`` § 6b specifies.

GATE REASONS (any one wakes; every decision carries the full list that fired) and their sources:

* ``market_open:<class>``   -- a universe market is open now. Crypto (bybit) 24/7; alpaca and IB
  equities/ETFs through ``market_hours.is_market_open("us_equity")``; IB futures through the 24/5
  ``fx`` window of the same helper (no futures calendar exists in the repo; the daily CME break is
  not modelled, so this errs toward waking).
* ``open_position``         -- packet ``system_book`` item with ``status: open``.
* ``open_desk_proposal``    -- packet ``desk_book`` item (an unresolved shadow proposal).
* ``near_signal``           -- packet ``system_book`` item with ``bars_to_signal`` 0 or 1 (DESK-16B).
* ``calendar_event``        -- ``news_events.event_risk_for_symbol`` > 0 for a universe symbol now,
  or a packet universe row whose ``calendar`` was ``read`` with events in the next bar.
* ``book_unread``           -- ``system_book`` or ``desk_book`` could not be looked at. COULD-NOT-LOOK
  IS NEVER "NOTHING OPEN": the gate wakes and says so.

``near_signals`` that could not be read are listed in ``unlooked`` on a ``not_due`` receipt and never
read as "no leg is near".

No halting: a failed read or post is a receipt state and the next pass retries (until the packet
ages out). Nothing here stops the desk, a leg, an account or a pipeline.

Credential: the ubuntu user's global git extraheader, read in process, never logged or written
(``live_review_wake_post.read_auth_header``). Live VM only: ``kick()`` is a no-op unless this process
is ``python -m src.main``.

Receipt: ``runtime_logs/desk_wake_post_receipt.json`` via
``/api/diag/log_file?name=desk_wake_post_receipt``. ``state``: ``not_due`` (with ``reasons_checked``
and ``unlooked``) · ``already_posted`` · ``posted`` (``comment_url``, ``reasons``) · ``could_not_look``
(``reason``) · ``could_not_post`` (``http_code`` / ``reason``). ``last_post`` is carried forward across
passes so a later pass does not erase the evidence of the last wake.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime import live_review_wake_post as ltr_post

logger = logging.getLogger(__name__)

RECEIPT_NAME = "desk_wake_post_receipt.json"
MARKER = "desk-wake"
REPO = ltr_post.REPO
API = ltr_post.API
BRANCH = "desk/decisions"
POINTER_PATH = "comms/desk/latest_scan.json"
#: One pass per this many seconds (a pass is one pointer GET once the bar is handled).
MIN_INTERVAL_S = 120
HTTP_TIMEOUT_S = 10
#: A packet built longer ago than this is not "this hour's": the builder missed a run.
PACKET_MAX_AGE_MIN = 90
BAR = timedelta(hours=1)
#: Operator 2026-10-26: "crypto 24/7" counts as an open market. If the universe holds a crypto
#: venue the gate therefore never reads not_due; flip this to make crypto count only through the
#: other reasons (open position, desk proposal, near signal, calendar).
CRYPTO_COUNTS_AS_OPEN = True
NEAR_BARS = (0, 1)

_LOCK = threading.Lock()
_last_kick = float("-inf")
#: bar key -> terminal state this process already reached for it.
_handled: Dict[str, str] = {}
_cached_markers: List[dict] = []

Http = ltr_post.Http
Fetch = Callable[[str, Optional[str]], Tuple[Optional[int], Any]]


def receipt_path() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / RECEIPT_NAME


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def bar_of(cutoff: datetime) -> datetime:
    return cutoff.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def packet_sha(packet: dict) -> str:
    """Same function as ``scripts/ci/check_desk_records.py::packet_sha``."""
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_markers(comments: Optional[list]) -> List[dict]:
    out: List[dict] = []
    for c in comments or []:
        body = str((c or {}).get("body") or "")
        i = body.find(f"<!-- {MARKER} ")
        if i < 0:
            continue
        j = body.find("-->", i)
        try:
            out.append(json.loads(body[i + len(MARKER) + 6:j]))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- the gate

def market_class(symbol: str, venue: str) -> str:
    """The ``market_hours`` asset class a universe row trades in."""
    v = str(venue or "").lower()
    if v == "bybit":
        return "crypto"
    if v == "alpaca":
        return "us_equity"
    if v == "interactive_brokers":
        try:
            from src.units.accounts.ib_instruments import is_ib_equity_symbol
            return "us_equity" if is_ib_equity_symbol(symbol) else "fx"  # futures: 24/5 proxy
        except Exception:  # noqa: BLE001
            return "fx"
    return "crypto"  # unknown venue: market_hours is fail-permissive too


def _calendar_events(universe: List[dict], now: datetime) -> List[str]:
    out: List[str] = []
    try:
        from src.news.news_events import event_risk_for_symbol
    except Exception:  # noqa: BLE001
        event_risk_for_symbol = None  # type: ignore[assignment]
    for r in universe:
        sym = str(r.get("symbol"))
        cal = r.get("calendar") or {}
        if cal.get("read_state") == "read" and cal.get("events_next_bar"):
            out.append(f"{sym}:packet:{','.join(map(str, cal['events_next_bar']))}")
            continue
        if event_risk_for_symbol is not None:
            try:
                risk, meta = event_risk_for_symbol(sym, now)
            except Exception:  # noqa: BLE001
                continue
            if risk and risk > 0:
                out.append(f"{sym}:{meta.get('class')}@{meta.get('time')} risk={risk:.2f}")
    return out


def evaluate_gate(packet: dict, now: datetime) -> Dict[str, Any]:
    """Pure. {wake, reasons: [{reason, detail}], unlooked: [...], checked: [...]}."""
    from src.runtime.market_hours import is_market_open

    reasons: List[Dict[str, str]] = []
    unlooked: List[str] = []
    universe = [r for r in packet.get("universe") or [] if isinstance(r, dict)]
    checked = ["market_open", "open_position", "open_desk_proposal", "near_signal", "calendar_event"]

    by_class: Dict[str, List[str]] = {}
    for r in universe:
        cls = market_class(r.get("symbol"), r.get("venue"))
        by_class.setdefault(cls, []).append(str(r.get("symbol")))
    for cls, syms in sorted(by_class.items()):
        if cls == "crypto" and not CRYPTO_COUNTS_AS_OPEN:
            continue
        if is_market_open("us_equity" if cls == "us_equity" else "fx" if cls == "fx" else "crypto", now):
            reasons.append({"reason": f"market_open:{cls}", "detail": f"{len(syms)} symbol(s): {','.join(syms[:6])}"})

    sb = packet.get("system_book") or {}
    if sb.get("read_state") != "read" or sb.get("items") is None:
        reasons.append({"reason": "book_unread", "detail": "system_book could not be looked at"})
    else:
        items = [i for i in sb["items"] if isinstance(i, dict)]
        opened = [i for i in items if i.get("status") == "open"]
        if opened:
            reasons.append({"reason": "open_position", "detail": f"{len(opened)} open package(s)"})
        near = [i for i in items if i.get("status") != "open" and i.get("bars_to_signal") in NEAR_BARS]
        if near:
            reasons.append({"reason": "near_signal", "detail": "; ".join(
                f"{i.get('leg')} {i.get('symbol')} bars={i.get('bars_to_signal')}" for i in near[:6])})
        if sb.get("near_signals_read_state") != "read":
            unlooked.append("near_signals")

    db = packet.get("desk_book") or {}
    if db.get("read_state") != "read" or db.get("items") is None:
        reasons.append({"reason": "book_unread", "detail": "desk_book could not be looked at"})
    elif db["items"]:
        reasons.append({"reason": "open_desk_proposal", "detail": f"{len(db['items'])} unresolved proposal(s)"})

    cal = _calendar_events(universe, now)
    if cal:
        reasons.append({"reason": "calendar_event", "detail": "; ".join(cal[:4])})
    return {"wake": bool(reasons), "reasons": reasons, "unlooked": unlooked, "checked": checked}


# ----------------------------------------------------------------------------- io

def _get(url: str, auth: Optional[str]) -> Tuple[Optional[int], Any]:
    """(status, parsed JSON or None). Raw media type: the contents API returns the file body."""
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "metis-desk-wake-vm"}
    if auth:
        headers["Authorization"] = auth
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001
        return None, None


def _contents_url(path: str) -> str:
    return f"{API}/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(BRANCH, safe='')}"


def read_packet(fetch: Fetch, auth: Optional[str]) -> Tuple[Optional[dict], Optional[dict], Optional[str]]:
    """(pointer, packet, why-not). ``why-not`` None means both were read and the sha verified."""
    code, ptr = fetch(_contents_url(POINTER_PATH), auth)
    if code != 200 or not isinstance(ptr, dict) or not ptr.get("packet_id") or not ptr.get("path"):
        return None, None, f"latest_scan unreadable (http {code})"
    code, pk = fetch(_contents_url(str(ptr["path"])), auth)
    if code != 200 or not isinstance(pk, dict):
        return ptr, None, f"packet {ptr.get('packet_id')} unreadable (http {code})"
    if ptr.get("packet_sha") and packet_sha(pk) != ptr["packet_sha"]:
        return ptr, None, f"packet {ptr.get('packet_id')} sha does not match the pointer"
    return ptr, pk, None


def render(entry: Dict[str, Any], now: datetime) -> str:
    marker = dict(entry, kind="desk-wake", posted_at=now.isoformat())
    lines = [f"- **{r['reason']}** — {r['detail']}" for r in entry["reasons"]]
    return "\n".join([
        f"**desk-wake: bar {entry['bar']}** — packet `{entry['packet_id']}` "
        f"(sha `{str(entry['packet_sha'])[:12]}`, built {entry['built_at']}). "
        "Manager: `create_session` the desk wake exactly as `.claude/skills/trading-desk/SKILL.md` § 6b "
        "specifies (outcome_branch/source_revision `desk/decisions`, the WAKE PROMPT).",
        "", "Gate reasons:", *lines, "",
        f"<!-- {MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
        "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def _load_last_post(path: Optional[Path]) -> Optional[dict]:
    try:
        return (json.loads((path or receipt_path()).read_text()) or {}).get("last_post")
    except Exception:  # noqa: BLE001
        return None


def run_once(fetch: Fetch = _get,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             http: Http = ltr_post._http,
             now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             receipt: Optional[Path] = None,
             pr_fn: Optional[Callable[[], int]] = None) -> Dict[str, Any]:
    """One bar's gate -> at most one comment. Returns (and writes) the receipt."""
    global _cached_markers
    now = now_fn()
    rec: Dict[str, Any] = {"computed_at": now.isoformat(), "poster": "vm"}
    last_post = _load_last_post(receipt)
    if last_post:
        rec["last_post"] = last_post

    def done(state: str, **kw: Any) -> Dict[str, Any]:
        rec.update(state=state, **kw)
        ltr_post.write_receipt(rec, receipt or receipt_path())
        return rec

    auth = auth_fn()
    ptr, pk, why = read_packet(fetch, auth)
    if why:
        return done("could_not_look", reason=why)
    cutoff, built = _ts(ptr.get("info_cutoff_at")), _ts(ptr.get("built_at"))
    if cutoff is None or built is None:
        return done("could_not_look", reason="pointer has no parseable info_cutoff_at/built_at")
    bar = _iso(bar_of(cutoff))
    rec.update(bar=bar, packet_id=ptr["packet_id"], packet_sha=ptr.get("packet_sha"), built_at=ptr["built_at"])
    if now - built > timedelta(minutes=PACKET_MAX_AGE_MIN):
        return done("could_not_look", reason=f"stale_packet: newest packet built {ptr['built_at']}, "
                                             f"older than {PACKET_MAX_AGE_MIN} min")
    if bar in _handled:
        return done(_handled[bar], note="bar already handled by this process")

    gate = evaluate_gate(pk, now)
    rec["reasons_checked"] = gate["checked"]
    if gate["unlooked"]:
        rec["unlooked"] = gate["unlooked"]
    if not gate["wake"]:
        _handled[bar] = "not_due"
        return done("not_due", reasons=[])
    rec["reasons"] = [r["reason"] for r in gate["reasons"]]

    if not auth:
        return done("could_not_post", http_code=None, reason="no_credential_in_git_extraheader")
    try:
        pr = pr_fn() if pr_fn else ltr_post.wake_module().ops_flags_pr()
    except Exception as exc:  # noqa: BLE001
        return done("could_not_post", http_code=None, reason=f"ops_flags_pr unreadable: {type(exc).__name__}")
    rec["pr"] = pr
    markers, code = ltr_post.read_markers(SimpleNamespace(parse_markers=parse_markers), pr, auth, now, http)
    if markers is None:
        return done("could_not_post", http_code=code, reason="marker_read_failed: dedupe unknown")
    _cached_markers = markers
    if any(m.get("bar") == bar for m in markers):
        _handled[bar] = "already_posted"
        return done("already_posted")

    entry = {"bar": bar, "packet_id": ptr["packet_id"], "packet_sha": ptr.get("packet_sha"),
             "path": ptr.get("path"), "built_at": ptr["built_at"], "poster": "vm",
             "reasons": gate["reasons"]}
    body = render(entry, now)
    code, data = http("POST", f"{API}/repos/{REPO}/issues/{pr}/comments", json.dumps({"body": body}).encode(), auth)
    rec["http_code"] = code
    if code != 201:
        return done("could_not_post", reason="comment_post_failed")
    posted_at = now_fn()
    url = (data or {}).get("html_url") if isinstance(data, dict) else None
    _handled[bar] = "already_posted"
    _cached_markers = markers + parse_markers([{"body": body}])
    rec["last_post"] = {"bar": bar, "packet_id": ptr["packet_id"], "posted_at": posted_at.isoformat(),
                        "comment_url": url, "reasons": rec["reasons"]}
    return done("posted", posted_at=posted_at.isoformat(), comment_url=url)


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 — contained: never reaches the tick loop
        logger.warning("desk-wake-post: pass failed", exc_info=True)
        ltr_post.write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "poster": "vm",
                               "state": "could_not_post", "http_code": None,
                               "reason": "exception (see bot log)"}, receipt_path())
    finally:
        _LOCK.release()


def kick(force: bool = False) -> bool:
    """Start one background pass if due. Never blocks, never raises."""
    global _last_kick
    try:
        if not (force or ltr_post._is_live_trader()):
            return False
        t = time.monotonic()
        if t - _last_kick < MIN_INTERVAL_S:
            return False
        if not _LOCK.acquire(blocking=False):
            return False
        _last_kick = t
        try:
            threading.Thread(target=_run_locked, name="desk-wake-post", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False
