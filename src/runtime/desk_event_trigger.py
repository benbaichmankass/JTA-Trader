"""Desk EVENT TRIGGERS, VM side (row DESK-SHORT-HOLD-LANE item 2): cheap detectors on closed bars decide which
market situations wake a Claude desk session between the hourly scans.

Operator, 2026-10-27 ~07:05Z (manager relay, binding): the SYSTEM decides which situations wake Claude; Claude,
woken, decides "the next bar is going to be big green or big red, get in and get out quickly". No model watches
markets: this module runs on the live trader, every ``MIN_INTERVAL_S``, off-thread, from the tick loop.

One pass:

1. LOOK: closed ``timeframe`` bars for each ``config/desk_triggers.yaml`` symbol (the bot's public candle route,
   the one the scan builder reads), plus the newest HOURLY scan packet on ``desk/decisions`` (its system_book
   near-signals). An unreadable input is that detector's ``could_not_look``, never a quiet "nothing fired".
2. DETECT (pure, ``detect``): ``atr_burst`` · ``momentum_burst`` · ``level_break`` / ``liquidity_sweep`` ·
   ``near_signal`` · ``calendar``. Each firing has a dedupe key (symbol, kind, bar or event).
3. LIMIT (pure, ``plan``): dedupe on the key, a per-symbol cooldown after a wake, ``max_per_hour`` and
   ``max_per_day`` across symbols. At most ONE wake per pass (the strongest firing); the rest are logged.
4. WAKE: build a ``timeframe`` scan packet of THAT symbol (``desk_scan_packet.py --symbols SYM --trigger-json``,
   the hourly builder), stage it with ``desk_branch.py publish --pointer comms/desk/latest_trigger.json`` (the
   hourly pointer never moves), land it on ``desk/decisions`` with ``desk_packet_wake.commit_packet`` (one
   fast-forward commit, never forced) and post ONE ``desk-trigger-wake`` marker on the ops-flags PR. Its kind is
   NOT ``desk-wake``, so the hourly producer's one-wake-per-bar dedupe never swallows it, and vice versa.
5. LABEL: every firing, woken or limited, is one line in ``runtime_logs/desk/trigger_labels.jsonl``
   (``fired`` with ``disposition`` posted | deduped | cooldown | hour_cap | day_cap | not_strongest |
   could_not_build | could_not_commit | could_not_post, and the ``packet_id`` when one landed). Claude's answer and
   the outcome join on ``packet_id`` (``join_labels``: decisions.jsonl + outcomes.jsonl), so a student can learn
   which situations were worth a wake.
6. RECEIPT: ``runtime_logs/desk_trigger_receipt.json`` (``/api/diag/log_file?name=desk_trigger_receipt``) with the
   cost line: wakes today x MEASURED $/wake, against the ``max_per_day`` ceiling.

NO HALTING: every failure is a label disposition and a receipt state; the next pass retries.
Live VM only: ``kick()`` is a no-op unless this process is ``python -m src.main``.
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.runtime import desk_packet_wake as dpw
from src.runtime import live_review_wake_post as ltr_post

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "desk_triggers.yaml"
TRIGGER_POINTER = "comms/desk/latest_trigger.json"
MARKER_KIND = "desk-trigger-wake"
MIN_INTERVAL_S = 120
TF_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
#: Strength order when several fire in one pass: the one woken is the first in this list.
KINDS = ("atr_burst", "momentum_burst", "liquidity_sweep", "level_break", "near_signal", "calendar")

_LOCK = threading.Lock()
_last_kick = float("-inf")


def log_dir() -> Path:
    return ROOT / "runtime_logs" / "desk"


def receipt_path() -> Path:
    return ROOT / "runtime_logs" / "desk_trigger_receipt.json"


def load_config(path: Path = CONFIG) -> Dict[str, Any]:
    import yaml
    return yaml.safe_load(path.read_text()) or {}


# --------------------------------------------------------------------------- pure: detectors

def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def closed_bars(bars: List[dict], tf: str, now: datetime) -> List[dict]:
    """Drop a still-forming last bar (open time + tf > now)."""
    sec = TF_S[tf]
    return [b for b in bars if _f(b.get("time")) is not None and b["time"] + sec <= now.timestamp()]


def atr14(bars: List[dict]) -> Optional[float]:
    """Wilder-free simple mean of the last 14 true ranges BEFORE the last bar (the last bar is what is judged)."""
    if len(bars) < 16:
        return None
    trs = []
    for prev, b in zip(bars[-16:-2], bars[-15:-1]):
        trs.append(max(b["high"] - b["low"], abs(b["high"] - prev["close"]), abs(b["low"] - prev["close"])))
    a = sum(trs) / len(trs)
    return a if a > 0 else None


def _bar_iso(b: dict) -> str:
    return datetime.fromtimestamp(b["time"], timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def detect(symbol: str, bars: List[dict], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Price detectors on CLOSED bars. Each firing: {kind, symbol, bar, key, detail}. Pure."""
    det = cfg.get("detectors") or {}
    a = atr14(bars)
    if a is None:
        return []
    last = bars[-1]
    bar = _bar_iso(last)
    out: List[Dict[str, Any]] = []

    def fire(kind: str, **detail: Any) -> None:
        detail = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in detail.items()}
        out.append({"kind": kind, "symbol": symbol, "bar": bar, "key": f"{symbol}|{kind}|{bar}",
                    "detail": dict(detail, atr14=round(a, 6), close=last["close"])})

    if "atr_burst" in det:
        rng = (last["high"] - last["low"]) / a
        if rng >= float(det["atr_burst"].get("range_atr", 2.0)):
            fire("atr_burst", range_atr=rng, direction="up" if last["close"] >= last["open"] else "down")
    if "momentum_burst" in det:
        n = int(det["momentum_burst"].get("bars", 3))
        if len(bars) > n:
            mv = (last["close"] - bars[-1 - n]["close"]) / a
            if abs(mv) >= float(det["momentum_burst"].get("move_atr", 2.5)):
                fire("momentum_burst", move_atr=mv, bars=n)
    if "level_break" in det:
        lb = int(det["level_break"].get("lookback", 48))
        if len(bars) > lb:
            prior = bars[-1 - lb:-1]
            hi, lo = max(b["high"] for b in prior), min(b["low"] for b in prior)
            if last["close"] > hi:
                fire("level_break", side="up", level=hi, lookback=lb)
            elif last["close"] < lo:
                fire("level_break", side="down", level=lo, lookback=lb)
            elif last["high"] > hi:
                fire("liquidity_sweep", side="up", level=hi, lookback=lb)
            elif last["low"] < lo:
                fire("liquidity_sweep", side="down", level=lo, lookback=lb)
    return out


def detect_book(symbol: str, hourly_packet: Optional[dict], cfg: Dict[str, Any], now: datetime,
                calendar_fn: Optional[Callable[[str, datetime], Tuple[float, dict]]] = None) -> List[Dict[str, Any]]:
    """Near-signal and calendar detectors. Pure given ``calendar_fn``."""
    det = cfg.get("detectors") or {}
    out: List[Dict[str, Any]] = []
    if "near_signal" in det and isinstance(hourly_packet, dict):
        sb = hourly_packet.get("system_book") or {}
        if sb.get("read_state") == "read" and sb.get("near_signals_read_state") == "read":
            for i in sb.get("items") or []:
                if i.get("symbol") == symbol and i.get("status") == "near_signal" and i.get("bars_to_signal") in (0, 1):
                    pid = (hourly_packet.get("meta") or {}).get("packet_id")
                    out.append({"kind": "near_signal", "symbol": symbol, "bar": pid,
                                "key": f"{symbol}|near_signal|{i.get('leg')}|{i.get('side')}|{pid}",
                                "detail": {"leg": i.get("leg"), "side": i.get("side"),
                                           "bars_to_signal": i.get("bars_to_signal"), "hourly_packet": pid}})
    if "calendar" in det and calendar_fn is not None:
        try:
            risk, meta = calendar_fn(symbol, now)
        except Exception:  # noqa: BLE001 -- the calendar is one detector; it never stops the pass
            risk, meta = 0.0, {}
        at = None
        try:
            at = datetime.fromisoformat(str((meta or {}).get("time")).replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            at = None
        lead = float(det["calendar"].get("minutes_before", 15))
        if risk and risk > 0 and at is not None and timedelta(0) <= at - now <= timedelta(minutes=lead):
            ev = f"{meta.get('class')}@{meta.get('time')}"
            out.append({"kind": "calendar", "symbol": symbol, "bar": ev, "key": f"{symbol}|calendar|{ev}",
                        "detail": {"event": meta.get("class"), "time": meta.get("time"), "risk": round(float(risk), 4)}})
    return out


# --------------------------------------------------------------------------- pure: limits

def plan(firings: List[Dict[str, Any]], state: Dict[str, Any], cfg: Dict[str, Any],
         now: datetime) -> Tuple[Optional[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """(the ONE firing to wake on or None, [(firing, why it does not wake)]). Pure."""
    seen = set(state.get("seen_keys") or [])
    wakes = [w for w in state.get("wakes") or [] if isinstance(w, dict)]
    stamps = [(_parse(w.get("at")), w.get("symbol")) for w in wakes]
    stamps = [(t, s) for t, s in stamps if t is not None]
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n_day = sum(1 for t, _ in stamps if t >= day0)
    n_hour = sum(1 for t, _ in stamps if now - t < timedelta(hours=1))
    cool = timedelta(minutes=float(cfg.get("cooldown_min", 30)))
    order = {k: i for i, k in enumerate(KINDS)}
    chosen: Optional[Dict[str, Any]] = None
    limited: List[Tuple[Dict[str, Any], str]] = []
    for f in sorted(firings, key=lambda x: order.get(x["kind"], len(KINDS))):
        if f["key"] in seen:
            limited.append((f, "deduped"))
        elif any(s == f["symbol"] and now - t < cool for t, s in stamps):
            limited.append((f, "cooldown"))
        elif n_day >= int(cfg.get("max_per_day", 12)):
            limited.append((f, "day_cap"))
        elif n_hour >= int(cfg.get("max_per_hour", 2)):
            limited.append((f, "hour_cap"))
        elif chosen is not None:
            limited.append((f, "not_strongest"))
        else:
            chosen = f
    return chosen, limited


def _parse(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def cost_line(state: Dict[str, Any], cfg: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n = sum(1 for w in state.get("wakes") or [] if (_parse(w.get("at")) or day0 - timedelta(1)) >= day0)
    per = float(cfg.get("cost_per_wake_usd", 0.43))
    return {"wakes_today": n, "usd_per_wake_measured": per, "usd_today_inferred": round(n * per, 2),
            "usd_ceiling_per_day": round(int(cfg.get("max_per_day", 12)) * per, 2)}


def join_labels(labels: List[dict], decisions: List[dict], outcomes: List[dict]) -> List[dict]:
    """fired -> Claude's answer -> outcome, joined on packet_id / decision_id. Pure. A label with no packet (limited)
    keeps answer/outcome None; a packet with no row yet reads answer None (not 'no_trade')."""
    by_pkt = {d.get("packet_id"): d for d in decisions if isinstance(d, dict)}
    by_dec: Dict[str, List[dict]] = {}
    for o in outcomes:
        if isinstance(o, dict) and o.get("decision_id"):
            by_dec.setdefault(o["decision_id"], []).append(o)
    out = []
    for lab in labels:
        d = by_pkt.get(lab.get("packet_id")) if lab.get("packet_id") else None
        os_ = by_dec.get((d or {}).get("decision_id"), [])
        out.append(dict(lab, answer=(d or {}).get("action"), decision_id=(d or {}).get("decision_id"),
                        label_source=(d or {}).get("label_source"),
                        outcome=[{"kind": o.get("kind"), "r_net": o.get("r_net")} for o in os_] or None))
    return out


# --------------------------------------------------------------------------- I/O

def _read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _append(p: Path, doc: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(doc, default=str, separators=(",", ":")) + "\n")


def fetch_bars(symbols: List[str], tf: str, limit: int) -> Dict[str, Optional[List[dict]]]:
    """The bot's public candle route through the scan builder's own reader."""
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))
    os.environ.setdefault("LIVE_REVIEW_PUBLIC_BASE", dpw.LOCAL_API)
    import desk_scan_packet
    return desk_scan_packet.candles_from_api(symbols, tf, limit=limit)


def fetch_hourly_packet(auth: Optional[str], fetch: dpw.Fetch = dpw._get) -> Optional[dict]:
    code, ptr = fetch(dpw._contents_url(dpw.POINTER_PATH), auth)
    if code != 200 or not isinstance(ptr, dict) or not ptr.get("path"):
        return None
    code, pk = fetch(dpw._contents_url(ptr["path"]), auth)
    return pk if code == 200 and isinstance(pk, dict) else None


def _calendar(symbol: str, now: datetime) -> Tuple[float, dict]:
    from src.news.news_events import event_risk_for_symbol
    return event_risk_for_symbol(symbol, now)


def build_packet(f: Dict[str, Any], cfg: Dict[str, Any], decisions_text: str) -> Tuple[Optional[Path], Optional[str]]:
    """The hourly builder + publisher, on ONE symbol at the trigger timeframe. (stage, None) | (None, why)."""
    try:
        tmp = Path(tempfile.mkdtemp(prefix="desk-trigger-"))
        dec = tmp / "decisions.jsonl"
        dec.write_text(decisions_text)
        env = dict(os.environ, LIVE_REVIEW_PUBLIC_BASE=os.environ.get("LIVE_REVIEW_PUBLIC_BASE", dpw.LOCAL_API))
        scan, stage = tmp / "scan.json", tmp / "stage"
        trig = json.dumps({k: f[k] for k in ("kind", "symbol", "bar", "detail")}, separators=(",", ":"))
        tf, hz = str(cfg.get("timeframe", "5m")), ",".join(str(h) for h in cfg.get("horizons") or [3, 6, 12])
        for cmd in ([sys.executable, str(dpw.BUILDER), "--timeframe", tf, "--horizons", hz, "--symbols", f["symbol"],
                     "--decisions", str(dec), "--trigger-json", trig, "--out", str(scan)],
                    [sys.executable, str(dpw.PUBLISHER), "publish", "--packet", str(scan), "--stage", str(stage),
                     "--pointer", TRIGGER_POINTER]):
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=dpw.BUILD_TIMEOUT_S)
            if r.returncode != 0:
                return None, f"{Path(cmd[1]).name} exit {r.returncode}: {(r.stderr or r.stdout).strip()[-160:]}"
        return stage, None
    except Exception as exc:  # noqa: BLE001 -- a build failure is a label disposition
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def render_marker(entry: Dict[str, Any], now: datetime) -> str:
    marker = dict(entry, kind=MARKER_KIND, posted_at=now.isoformat())
    t = entry["trigger"]
    return "\n".join([
        f"**desk-trigger-wake: `{t['kind']}` on {t['symbol']}** (bar {t['bar']}) -- packet `{entry['packet_id']}` "
        f"(sha `{str(entry['packet_sha'])[:12]}`, commit `{str(entry['commit'])[:10]}`) landed on `desk/decisions`. "
        "Manager: `create_session` the desk wake as `.claude/skills/manager/SKILL.md` § \"Desk trigger wake\" "
        "specifies (the trading-desk WAKE PROMPT plus this packet id).",
        "", f"Detail (information only): `{json.dumps(t['detail'], separators=(',', ':'))}`", "",
        f"<!-- {dpw.marker_module().MARKER} {json.dumps(marker, separators=(',', ':'), default=str)} -->",
        "", "---", "_Generated by [Claude Code](https://claude.ai/code)_"])


def run_once(*, cfg: Optional[Dict[str, Any]] = None, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             bars_fn: Callable[[List[str], str, int], Dict[str, Optional[List[dict]]]] = fetch_bars,
             auth_fn: Callable[[], Optional[str]] = ltr_post.read_auth_header,
             fetch: dpw.Fetch = dpw._get, http: ltr_post.Http = ltr_post._http,
             pr_fn: Optional[Callable[[], int]] = None,
             build_fn: Callable[..., Tuple[Optional[Path], Optional[str]]] = build_packet,
             commit_fn: Optional[Callable[..., Tuple[Optional[str], Optional[int]]]] = None,
             calendar_fn: Optional[Callable[[str, datetime], Tuple[float, dict]]] = _calendar,
             logs: Optional[Path] = None, receipt: Optional[Path] = None) -> Dict[str, Any]:
    """One pass: look, detect, limit, wake at most once, label every firing, write the receipt."""
    now = now_fn()
    d = logs or log_dir()
    state_path, labels_path = d / "trigger_state.json", d / "trigger_labels.jsonl"
    rec: Dict[str, Any] = {"computed_at": now.isoformat(), "watcher": "vm"}
    state = _read_json(state_path) or {"seen_keys": [], "wakes": []}

    def done(st: str, **kw: Any) -> Dict[str, Any]:
        rec.update(state=st, **kw)
        rec["cost"] = cost_line(state, cfg or {}, now)
        ltr_post.write_receipt(rec, receipt or receipt_path())
        return rec

    try:
        cfg = cfg if cfg is not None else load_config()
    except Exception as exc:  # noqa: BLE001
        cfg = {}
        return done("could_not_look", reason=f"config/desk_triggers.yaml unreadable: {type(exc).__name__}")
    symbols = [str(s) for s in cfg.get("symbols") or []]
    if not symbols:
        return done("no_symbols")
    tf = str(cfg.get("timeframe", "5m"))
    auth = auth_fn()
    bars = bars_fn(symbols, tf, int(cfg.get("candles", 120)))
    hourly = fetch_hourly_packet(auth, fetch)
    firings: List[Dict[str, Any]] = []
    unread: List[str] = []
    for s in symbols:
        b = bars.get(s)
        if not b:
            unread.append(f"{s}:candles")
        else:
            firings += detect(s, closed_bars(b, tf, now), cfg)
        firings += detect_book(s, hourly, cfg, now, calendar_fn)
    if hourly is None:
        unread.append("hourly_packet (near_signal)")
    rec.update(firings=len(firings), unread=unread)
    chosen, limited = plan(firings, state, cfg, now)
    for f, why in limited:
        if why != "deduped":  # a deduped firing was labelled on the pass that first saw it
            _append(labels_path, {"at": now.isoformat(), "fired": f, "disposition": why, "packet_id": None})
    seen = list(state.get("seen_keys") or []) + [f["key"] for f, why in limited if why != "deduped"]
    state["seen_keys"] = seen[-500:]
    if chosen is None:
        _write_state(state_path, state)
        return done("quiet" if not firings else "limited", limited=[w for _, w in limited])

    def label(disp: str, **kw: Any) -> None:
        _append(labels_path, dict({"at": now.isoformat(), "fired": chosen, "disposition": disp}, **kw))
        state["seen_keys"] = (state["seen_keys"] + [chosen["key"]])[-500:]
        _write_state(state_path, state)

    if not auth:
        label("could_not_commit", packet_id=None, reason="no_credential_in_git_extraheader")
        return done("could_not_commit", fired=chosen["key"])
    code, text = fetch(dpw._contents_url(dpw.DECISIONS_PATH), auth)
    stage, why = build_fn(chosen, cfg, text if code == 200 and isinstance(text, str) else "")
    if stage is None:
        label("could_not_build", packet_id=None, reason=why)
        return done("could_not_build", fired=chosen["key"], reason=why)
    ptr = json.loads((stage / TRIGGER_POINTER).read_text())
    sha, ccode = (commit_fn or dpw.commit_packet)(stage, ptr["packet_id"], auth, http, pointer_path=TRIGGER_POINTER)
    if sha is None:
        label("could_not_commit", packet_id=ptr["packet_id"], http_code=ccode)
        return done("could_not_commit", fired=chosen["key"], http_code=ccode)
    try:
        pr = pr_fn() if pr_fn else ltr_post.wake_module().ops_flags_pr()
    except Exception as exc:  # noqa: BLE001
        label("could_not_post", packet_id=ptr["packet_id"], reason=type(exc).__name__)
        return done("could_not_post", fired=chosen["key"], packet_id=ptr["packet_id"])
    entry = {"packet_id": ptr["packet_id"], "packet_sha": ptr["packet_sha"], "path": ptr["path"],
             "built_at": ptr["built_at"], "commit": sha, "poster": "vm",
             "trigger": {k: chosen[k] for k in ("kind", "symbol", "bar", "detail")}}
    pcode, _ = http("POST", f"{dpw.API}/repos/{dpw.REPO}/issues/{pr}/comments",
                    json.dumps({"body": render_marker(entry, now)}).encode(), auth)
    if pcode != 201:
        label("could_not_post", packet_id=ptr["packet_id"], http_code=pcode)
        return done("could_not_post", fired=chosen["key"], packet_id=ptr["packet_id"], http_code=pcode)
    state["wakes"] = ([w for w in state.get("wakes") or [] if (_parse(w.get("at")) or now) > now - timedelta(days=2)]
                      + [{"at": now.isoformat(), "symbol": chosen["symbol"], "packet_id": ptr["packet_id"]}])
    label("posted", packet_id=ptr["packet_id"], commit=sha)
    return done("posted", fired=chosen["key"], packet_id=ptr["packet_id"], commit=sha,
                latency_s=round((now_fn() - now).total_seconds(), 1))


def _write_state(p: Path, state: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, default=str) + "\n")
    os.replace(tmp, p)


def _run_locked() -> None:
    try:
        run_once()
    except Exception:  # noqa: BLE001 -- contained: never reaches the tick loop
        logger.warning("desk-event-trigger: pass failed", exc_info=True)
        ltr_post.write_receipt({"computed_at": datetime.now(timezone.utc).isoformat(), "watcher": "vm",
                                "state": "could_not_look", "reason": "exception (see bot log)"}, receipt_path())
    finally:
        _LOCK.release()


def kick(force: bool = False) -> bool:
    """Start one background pass if due. Never blocks, never raises."""
    global _last_kick
    try:
        if not (force or ltr_post._is_live_trader()):
            return False
        t = time.monotonic()
        if t - _last_kick < MIN_INTERVAL_S or not _LOCK.acquire(blocking=False):
            return False
        _last_kick = t
        try:
            threading.Thread(target=_run_locked, name="desk-event-trigger", daemon=True).start()
        except Exception:  # noqa: BLE001
            _LOCK.release()
            return False
        return True
    except Exception:  # noqa: BLE001
        return False
