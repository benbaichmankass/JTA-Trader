#!/usr/bin/env python3
# wiring: manual-only - run by hand by a live-review reviewer (skill live-trade-review § 1b); `--bundle` is also invoked by path from scripts/ops/live_review_wake.py::build_bundle (the ltr-wake poller and the VM poster, LTR C2).
"""Decision-packet generator for the live trade review (LTR-11-PACKET).

    python3 scripts/ops/live_review_packet.py pkg-b1e4fdf9b9d049a3          # one package
    python3 scripts/ops/live_review_packet.py --all-open                    # every open package
    python3 scripts/ops/live_review_packet.py --all-open --write            # + commit-ready files

WHY. Operator, 2026-10-25: the repo builds the context for every live-trade decision and Claude
spends its usage only on judgment. Claude and the ML models must see the SAME packet, so each
decision is joinable (``packet_sha``) to exactly what was seen. Contract:
``.claude/skills/live-trade-review/SKILL.md`` § 1b. The first nine packets were assembled by hand
(``comms/live_review/packets/``, ``assembled_by: hand``); roughly half of that lane's tokens went on
assembly. This is that assembly, as code.

PURE READS. Everything comes from the read-only diag relay (``scripts/ops/diag_fetch.sh``), the
public ``/api/bot/*`` reads, the repo's committed config and the committed Stage-0 evidence (via
``scripts/research/live_review_outcomes.py``). Nothing here writes to a venue, a DB or ``config/``.

SHAPE. ``collect()`` does all I/O and returns one ``Snapshot``; ``build_packet()`` is a pure function
of ``(package id, snapshot, now)``. Tests drive ``build_packet`` with fixtures reproducing the golden
packets' state.

COULD-NOT-LOOK != ZERO. A field the generator cannot reach is ``null`` and is named in
``missing_inputs`` with the reason. The gaps (2026-10-25) are listed on checklist row LTR-11-PACKET:
perp funding (no route), the live volatility bucket (edges live only in the VM model registry), and
the venue positions of prop accounts whose status carries no ``positions`` field.

``packet_sha`` is sha256 of the packet's canonical JSON (``sort_keys``, compact separators) --
exactly what ``scripts/ci/check_live_review_records.py::packet_problems`` recomputes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # `src.runtime.regime` (the live detector) must import when run as a script
PACKET_VERSION = 3  # v1 = the hand-built packets; v2 is a strict superset of their keys; v3 adds context_v3 (DESK-AM-REFOCUS)
GENERATOR = "scripts/ops/live_review_packet.py"
PUBLIC_BASE = "https://ict-bot.duckdns.org"
PACKETS_DIR = REPO / "comms" / "live_review" / "packets"
TABLES_DIR = REPO / "comms" / "live_review" / "tables"
#: full-history per-leg corpora (build: scripts/research/build_ltr_corpus.py); ``--corpus auto`` prefers them
LTR_CORPUS_DIR = "comms/strategy_evidence/ltr_corpus"
REVIEWS = REPO / "comms" / "live_review" / "reviews.jsonl"
PRICE_TOL = 5e-4  # relative: a venue trigger is rounded to the tick; 0.05% separates a tick from a real move
CLASS_ORDER = {"real_money": 0, "prop": 1, "paper": 2}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


# ----------------------------------------------------------------------------- reads

def _diag(path: str) -> Any:
    out = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"diag {path}: exit {out.returncode} ({out.stderr.strip()[-200:]})")
    # diag_fetch.sh appends a "diag_fetch: served by ..." trailer after the JSON document
    doc, _ = json.JSONDecoder().raw_decode(out.stdout.lstrip())
    return doc


def _public(path: str) -> Any:
    base = os.environ.get("LIVE_REVIEW_PUBLIC_BASE", PUBLIC_BASE)
    with urllib.request.urlopen(f"{base}/{path}", timeout=60) as r:  # noqa: S310 (fixed https base)
        return json.loads(r.read().decode())


@dataclass
class Snapshot:
    """Every raw read, with the time it was taken. ``errors`` records reads that failed (never silently)."""
    reads: Dict[str, Any] = field(default_factory=dict)
    read_at: Dict[str, str] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    candles: Dict[str, Any] = field(default_factory=dict)  # "SYM|tf" -> candles read or None
    trades: List[dict] = field(default_factory=list)
    packages: Dict[str, dict] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        return self.reads.get(name)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(wanted: Optional[List[str]] = None, *, max_pages: int = 3, diag: Callable[[str], Any] = _diag,
            public: Callable[[str], Any] = _public) -> Snapshot:
    """All I/O. ``wanted`` = package ids to locate in the paged journal reads (None = the open set).

    Paging stops as soon as every wanted package has been found: the costliest step by hand was paging
    ``journal?table=trades`` to offset 2000 to find August opens. The open set itself needs no paging
    (telemetry + positions + prop tickets); paging is only to fetch an open package's sl/tp/meta/trade rows.
    """
    s = Snapshot()
    s.reads["generator"] = generator_state()

    def read(name: str, fn: Callable[[str], Any], path: str) -> None:
        try:
            s.reads[name] = fn(path)
            s.read_at[name] = _now_iso()
        except Exception as exc:  # allow-silent: recorded in errors and surfaced as could_not_look
            s.errors[name] = str(exc)[:200]

    read("telemetry", diag, "position_telemetry?limit=300")
    read("positions", public, "api/bot/positions")
    read("prop_tickets", public, "api/bot/prop/tickets")
    read("bybit_orders", diag, "bybit_open_orders")
    read("alpaca_orders", diag, "alpaca_open_orders")
    read("ib_orders", diag, "ib_open_orders")
    read("news", public, "api/bot/news/recent?limit=60")
    read("perf_recent", public, "api/bot/performance/recent?n=200")  # context_v3.live_vs_backtest
    for acct in ("breakout_2", "tradeify_1", "velotrade_1"):
        read(f"prop_status:{acct}", public, f"api/bot/prop/status?account_id={acct}")

    open_ids = set(wanted or open_package_ids(s))
    # order_packages: newest-updated first, so old opens may sit past page 1
    for page in range(max_pages):
        try:
            rows = diag(f"journal?table=order_packages&limit=150&offset={page * 150}")
        except Exception as exc:  # allow-silent: recorded
            s.errors[f"order_packages@{page}"] = str(exc)[:200]
            break
        s.read_at[f"order_packages@{page}"] = _now_iso()
        for r in rows:
            s.packages[r["order_package_id"]] = r
        if open_ids <= set(s.packages) or len(rows) < 150:
            break
    for page in range(max_pages):
        try:
            rows = diag(f"journal?table=trades&limit=1000&offset={page * 1000}")
        except Exception as exc:  # allow-silent: recorded
            s.errors[f"trades@{page}"] = str(exc)[:200]
            break
        s.read_at[f"trades@{page}"] = _now_iso()
        s.trades.extend(rows)
        have = {t.get("order_package_id") for t in s.trades}
        if open_ids <= have or len(rows) < 1000:
            break
    return s


def generator_state() -> dict:
    """Is THIS generator the one on ``origin/main``? (LTR-PACKET-FIXES C, 2026-11-01.)

    The 14:32Z lane built v2 packets (no context_v3, symbol-matched IB orders) because it ran the generator from a
    checkout of the ``live-review/rows`` data branch, whose ``scripts/`` froze at 2026-10-25. A packet now says
    which generator built it: ``current`` / ``stale_vs_origin_main`` / ``could_not_look`` (never a gate)."""
    here = Path(__file__).resolve()
    try:
        rel = here.relative_to(REPO).as_posix()
        main_txt = subprocess.run(["git", "-C", str(REPO), "show", f"origin/main:{rel}"], capture_output=True,
                                  text=True, timeout=30)
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=10", "HEAD"], capture_output=True,
                              text=True, timeout=30).stdout.strip() or None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"state": "could_not_look", "reason": type(exc).__name__}
    if main_txt.returncode != 0:
        return {"state": "could_not_look", "head": head, "reason": "origin/main not readable in this checkout"}
    same = main_txt.stdout == here.read_text()
    return {"state": "current" if same else "stale_vs_origin_main", "head": head}


def open_package_ids(s: Snapshot) -> List[str]:
    """Union of every source that can say a package is open. A package in one source and not another is
    itself a finding (skill § 1), so the union is taken here and reconciled in ``_mechanics``."""
    ids: List[str] = []
    for r in (s.get("telemetry") or {}).get("rows", []):
        if r.get("lifecycle") == "open":
            ids.append(r["order_package_id"])
    for t in (s.get("prop_tickets") or {}).get("tickets", []):
        if t.get("status") == "filled":  # a filled ticket with no close is open at the prop venue
            ids.append(t["order_package_id"])
    for r in s.packages.values():
        if r.get("status") == "open":
            ids.append(r["order_package_id"])
    for t in s.trades:
        if t.get("status") == "open" and t.get("order_package_id"):
            ids.append(t["order_package_id"])
    return sorted(set(i for i in ids if i))


# ----------------------------------------------------------------------------- helpers

def _f(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "", "None") else float(v)
    except (TypeError, ValueError):
        return None


def _json(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    try:
        out = json.loads(v) if isinstance(v, str) else {}
        return out if isinstance(out, dict) else {}
    except ValueError:
        return {}


def packet_sha(packet: dict) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _accounts_cfg() -> Dict[str, dict]:
    from src.config.accounts_loader import load_accounts_dict
    return load_accounts_dict()


def _close(a: Optional[float], b: Optional[float]) -> bool:
    return a is not None and b is not None and abs(a - b) <= PRICE_TOL * max(abs(b), 1e-12)


# ----------------------------------------------------------------------------- venue reads

def _own_or_ambiguous(own: List[dict], cands: List[dict], siblings: int) -> Tuple[List[dict], bool]:
    """This package's own venue orders, or (``[]``, True) when they cannot be told apart from a sibling's.

    ``own`` = the orders provably this package's (its order ids / OCA group). With none, the symbol's orders
    stand in ONLY when no other open package holds the symbol on this account (the pre-id venues, e.g. legacy
    IB group names). LTR-PACKET-FIXES A (2026-11-01): ib_paper held two MGC packages and symbol-level,
    last-order-wins matching read pkg-d76f's STP/LMT as pkg-011a's and filed a false mismatch."""
    if own:
        return own, False
    if siblings <= 0:
        return cands, False
    return [], bool(cands)


def _venue_exit_prices(s: Snapshot, account: str, exchange: str, symbol: str, direction: str,
                       sl_order_id: Optional[str] = None, tp_order_id: Optional[str] = None, *,
                       trade_id: Any = None, broker_order_id: Optional[str] = None, qty: Optional[float] = None,
                       siblings: int = 0) -> dict:
    """Resting SL/TP and position presence for ONE PACKAGE's leg on one account, or could-not-look.

    Orders are matched to the package by its own identifiers, never by symbol alone, because one account can
    hold several packages on one symbol:

    * bybit -- the trade's ``sl_order_id`` / ``tp_order_id`` (``position_model: slices`` accounts hold one
      qty-scoped Partial leg per package; PI-20261031-TD4QC5GP-0004);
    * interactive_brokers -- the keyed OCA group ``oca-protect-t<trade id>`` (``IBClient.place_protective``;
      the journal carries no IB sl/tp order ids);
    * alpaca -- the order or its ``parent_id`` equal to the trade's ``broker_order_id`` / sl / tp ids (a bracket
      stop leg's parent is the entry), else the one exit-side leg whose qty equals the trade's
      (``alpaca_amend.read_trade_legs`` scopes the same way).

    ``siblings`` = other open packages on this account + symbol. With siblings and no id match the level is
    ``None`` and ``ambiguous`` is set: a mismatch is never asserted from a leg that is not this package's."""
    exit_side = "buy" if direction == "short" else "sell"
    src = {"bybit": "bybit_orders", "alpaca": "alpaca_orders", "interactive_brokers": "ib_orders"}.get(exchange)
    if src is None:
        return {"state": "could_not_look", "why": f"no venue read for exchange {exchange}"}
    doc = s.get(src)
    if doc is None:
        return {"state": "could_not_look", "why": f"{src} read failed: {s.errors.get(src, 'not read')}"}
    acct = next((a for a in doc.get("accounts", []) if a.get("account_id") == account), None)
    if acct is None or acct.get("read_state") not in ("orders_read",):
        return {"state": "could_not_look", "why": f"{account} {src} read_state={acct and acct.get('read_state')}"}
    sl = tp = None
    pos = None
    amb_sl = amb_tp = False
    match = "symbol"
    if exchange == "bybit":
        res = acct.get("result") or {}
        pos = next((p for p in res.get("positions", []) if p.get("symbol") == symbol and (p.get("size") or 0) > 0), None)
        sl_legs, tp_legs = [], []
        for o in res.get("orders", []):
            if o.get("symbol") != symbol:
                continue
            kind = str(o.get("stop_order_type") or "")
            if "StopLoss" in kind:
                sl_legs.append(o)
            elif "TakeProfit" in kind:
                tp_legs.append(o)

        def _pick(legs, oid):
            hit = [o for o in legs if oid and o.get("order_id") == oid]
            if hit:
                return _f(hit[0].get("trigger_price")), False
            if len(legs) == 1 and not oid and siblings <= 0:
                return _f(legs[0].get("trigger_price")), False
            if not legs:
                return None, False
            # legs exist but none is provably this package's (id unknown or not resting): do not guess
            return None, True
        sl, amb_sl = _pick(sl_legs, sl_order_id)
        tp, amb_tp = _pick(tp_legs, tp_order_id)
        match = "order_id" if (sl_order_id or tp_order_id) else "symbol"
        if not sl_legs and sl is None and pos and siblings <= 0:
            sl = _f(pos.get("stop_loss"))
        if not tp_legs and tp is None and pos and siblings <= 0:
            tp = _f(pos.get("take_profit"))
        pos_present = pos is not None
    elif exchange == "alpaca":
        res = acct.get("result") or {}
        pos = next((p for p in res.get("positions", []) if p.get("symbol") == symbol), None)
        cands = [o for o in res.get("orders", []) if o.get("symbol") == symbol
                 and (str(o.get("side")) == exit_side or o.get("order_class") == "bracket")]
        ids = {str(i) for i in (broker_order_id, sl_order_id, tp_order_id) if i}
        own = [o for o in cands if ids and (str(o.get("order_id")) in ids or str(o.get("parent_id")) in ids)]
        # an OCO / bracket pair: the sibling leg of an own leg (one shares the other's id as parent) is own too
        own_ids = {str(o.get("order_id")) for o in own} | {str(o.get("parent_id")) for o in own if o.get("parent_id")}
        own += [o for o in cands if o not in own and (str(o.get("parent_id")) in own_ids or str(o.get("order_id")) in own_ids)]
        stops = [o for o in cands if _f(o.get("stop_price")) is not None and o.get("order_type") in ("stop", "stop_limit")]
        lims = [o for o in cands if o.get("order_type") == "limit" and _f(o.get("limit_price")) is not None]

        def _leg(legs):
            mine = [o for o in legs if o in own]
            if mine:
                return mine[-1], False, "order_id"
            if qty:
                q = [o for o in legs if _f(o.get("qty")) is not None and abs(_f(o.get("qty")) - float(qty)) < 1e-9]
                if len(q) == 1:
                    return q[0], False, "qty"
            got, amb = _own_or_ambiguous([], legs, siblings)
            return (got[-1] if got else None), amb, "symbol"
        so, amb_sl, m1 = _leg(stops)
        to, amb_tp, m2 = _leg(lims)
        sl = _f(so["stop_price"]) if so else None
        tp = _f(to["limit_price"]) if to else None
        match = m1 if m1 == m2 else f"sl:{m1},tp:{m2}"
        pos_present = pos is not None or sl is not None or tp is not None
    else:  # interactive_brokers
        cands = [o for o in acct.get("orders") or []
                 if o.get("symbol") == symbol and str(o.get("action", "")).lower() == exit_side]
        group = f"oca-protect-t{trade_id}" if trade_id not in (None, "") else None
        own = [o for o in cands if group and o.get("oca_group") == group]
        legs, amb = _own_or_ambiguous(own, cands, siblings)
        if not own and legs and len({o.get("oca_group") for o in legs if o.get("oca_group")}) > 1:
            legs, amb = [], True  # several protective groups and none is this trade's keyed group: do not guess
        match = "oca_group" if own else "symbol"
        stp = [o for o in legs if o.get("order_type") == "STP"]
        lmt = [o for o in legs if o.get("order_type") == "LMT"]
        sl = _f(stp[0].get("aux_price")) if len(stp) == 1 else None
        tp = _f(lmt[0].get("lmt_price")) if len(lmt) == 1 else None
        amb_sl = amb or len(stp) > 1
        amb_tp = amb or len(lmt) > 1
        pos_present = sl is not None or tp is not None or bool(cands)
    return {"state": "read", "position": pos_present, "sl": sl, "tp": tp, "src": src,
            "ambiguous": bool(amb_sl or amb_tp), "matched_by": match}


# ----------------------------------------------------------------------------- candles: ATR and regime

def _closed_bars(candles: List[dict], tf: str, now: datetime) -> List[dict]:
    sec = TF_SECONDS.get(tf)
    if not candles or sec is None:
        return []
    cut = now.timestamp()
    return [c for c in candles if c["time"] + sec <= cut]  # drop the forming bar


def atr_sma(bars: List[dict], period: int) -> Optional[float]:
    """Mean true range of the last ``period`` closed bars (the strategies' ATR: SMA of TR)."""
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, c in zip(bars[-period - 1:-1], bars[-period:]):
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev["close"]), abs(c["low"] - prev["close"])))
    return sum(trs) / period


def trend_now(bars: List[dict]) -> Tuple[Optional[str], Optional[float]]:
    """ADX-14 trend label, via the SAME functions the live detector uses (src.runtime.regime.detector)."""
    try:
        import pandas as pd

        from src.runtime.regime.detector import detect_regime
    except Exception:  # allow-silent: reported as a missing input by the caller
        return None, None
    if len(bars) < 30:
        return None, None
    r = detect_regime(pd.DataFrame(bars))
    return (r["regime"] if r["regime"] != "unknown" else None), r.get("adx")


# ----------------------------------------------------------------------------- context_v3 (DESK-AM-REFOCUS)
#
# The discretionary context a trader manages a position with (docs/research/desk-am-refocus-diagnosis-2026-10-30.md
# section 1.2: the v2 packet carried no candles, no higher timeframe and no book, so the reviewer could only restate the
# priced table). Pure functions of reads already taken; a block it cannot fill is null with a missing_inputs entry.

HTF_OF = {"5m": "1h", "15m": "1h", "30m": "4h", "1h": "4h", "2h": "1d", "4h": "1d", "1d": "1w"}  # 1w: built from 1d bars (the candles route has no 1w)
CHART_BARS = 16   # leg-timeframe bars shown (16h of 1h, ~5 days of 4h); swings + since_entry cover further back
HTF_BARS = 8
SWING_LOOKBACK = 60
SWING_K = 2       # a pivot is the extreme of the K bars either side


def _sig(v: Any, n: int = 6) -> Optional[float]:
    f = _f(v)
    return None if f is None else float(f"{f:.{n}g}")


def _candles(s: "Snapshot", symbol: str, tf: str, limit: int = 200) -> Any:
    key = f"{symbol}|{tf}"
    if key not in s.candles:
        try:
            s.candles[key] = _public(f"api/bot/candles?symbol={symbol}&interval={tf}&limit={limit}")
        except Exception as exc:  # allow-silent: becomes a missing input
            s.candles[key] = {"candles": [], "error": str(exc)[:120]}
    return s.candles[key]


def weekly(daily: List[dict]) -> List[dict]:
    """ISO-week bars from closed daily bars; the current, unfinished week is dropped."""
    weeks: Dict[Tuple[int, int], List[dict]] = {}
    for c in daily:
        weeks.setdefault(datetime.fromtimestamp(c["time"], timezone.utc).isocalendar()[:2], []).append(c)
    keys = sorted(weeks)[:-1]
    return [{"time": weeks[k][0]["time"], "open": weeks[k][0]["open"], "high": max(c["high"] for c in weeks[k]),
             "low": min(c["low"] for c in weeks[k]), "close": weeks[k][-1]["close"]} for k in keys]


def swings(bars: List[dict], k: int = SWING_K, lookback: int = SWING_LOOKBACK) -> Dict[str, List[dict]]:
    """Pivot highs / lows over the last ``lookback`` closed bars, newest first (bars_ago 0 = the last closed bar)."""
    w = bars[-lookback:]
    highs, lows = [], []
    for i in range(k, len(w) - k):
        hi, lo = w[i]["high"], w[i]["low"]
        if all(hi >= w[j]["high"] for j in range(i - k, i + k + 1)):
            highs.append({"px": _sig(hi), "bars_ago": len(w) - 1 - i})
        if all(lo <= w[j]["low"] for j in range(i - k, i + k + 1)):
            lows.append({"px": _sig(lo), "bars_ago": len(w) - 1 - i})
    return {"highs": highs[::-1][:3], "lows": lows[::-1][:3]}


def _with_dist(levels: List[dict], last: float, atr: Optional[float]) -> List[dict]:
    return [dict(x, dist_atr=None if not atr else round((x["px"] - last) / atr, 2)) for x in levels]


def chart_block(bars: List[dict], atr: Optional[float], n: int = CHART_BARS) -> Optional[dict]:
    if not bars:
        return None
    last = bars[-1]["close"]
    sw = swings(bars)
    return {"bars_ohlc": [[c["time"], _sig(c["open"]), _sig(c["high"]), _sig(c["low"]), _sig(c["close"])] for c in bars[-n:]],
            "bars_note": "[epoch_s, open, high, low, close], closed bars only, oldest first",
            "last_close": _sig(last), "atr": _sig(atr),
            "swings": {"highs": _with_dist(sw["highs"], last, atr), "lows": _with_dist(sw["lows"], last, atr)}}


def since_entry(bars: List[dict], opened_ts: Optional[float], atr: Optional[float]) -> Optional[dict]:
    if not bars or opened_ts is None:
        return None
    w = [c for c in bars if c["time"] >= opened_ts - 1]
    if not w:
        return None
    last = bars[-1]["close"]
    hi, lo = max(c["high"] for c in w), min(c["low"] for c in w)
    return {"bars": len(w), "high": _sig(hi), "low": _sig(lo),
            "high_dist_atr": None if not atr else round((hi - last) / atr, 2),
            "low_dist_atr": None if not atr else round((lo - last) / atr, 2)}


def _ts(v: Any) -> Optional[float]:
    """Epoch seconds of a journal timestamp ('2026-10-30 12:00:00', ISO with or without Z); naive reads as UTC."""
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _opened_ts(p: Optional[dict], trades: List[dict]) -> Optional[float]:
    cands = [(p or {}).get(k) for k in ("created_at", "opened_at")]
    cands += [t.get(k) for t in trades for k in ("entry_time", "opened_at", "created_at")]
    for v in cands:
        if v and _ts(v) is not None:
            return _ts(v)
    return None


def book_block(s: "Snapshot", pkg: str) -> List[dict]:
    """Every OTHER open package, either side: the book this trade sits in (the v2 field kept same-direction ids only)."""
    tel = {r.get("order_package_id"): r for r in (s.get("telemetry") or {}).get("rows", []) if r.get("lifecycle") == "open"}
    out = []
    for o in open_package_ids(s):
        if o == pkg:
            continue
        p = s.packages.get(o) or {}
        t = tel.get(o) or {}
        d = p.get("direction") or t.get("direction")
        out.append([p.get("symbol") or t.get("symbol"), d, p.get("strategy_name") or t.get("strategy"),
                    _sig(t.get("open_r"), 3)])
    return out


BOOK_NOTE = "[symbol, direction, leg, open_r (null = not measured)] per OTHER open package, either side"


EXIT_META_KEYS = ("atr", "atr_period", "atr_stop_mult", "trail_mult", "trail_atr_mult", "trail_activation_r", "tp_r",
                  "tp_intent", "max_hold_bars", "time_stop_bars", "breakeven_r", "timeframe")


def exit_plan_block(p: Optional[dict], meta: dict, entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> dict:
    """What HOLD actually does: the strategy's own brackets and declared exit levers (copied, never inferred)."""
    eps = {k: v for k, v in _json((p or {}).get("exit_plan_state")).items()
           if k in ("stop", "targets", "trailing_stop", "final_trailing", "time_decay_minutes", "residual_qty")}
    return {"entry": _sig(entry), "sl_now": _sig(sl), "tp_now": _sig(tp),
            "sl_initial": _sig(meta.get("sl_initial") or meta.get("initial_sl")),
            "declared": {k: meta[k] for k in EXIT_META_KEYS if k in meta},
            "exit_plan_state": eps or None}


def live_vs_backtest_block(s: "Snapshot", leg: str) -> Optional[dict]:
    recent = s.get("perf_recent")
    if not recent:
        return None
    try:
        sys.path.insert(0, str(REPO / "scripts" / "research"))
        import live_vs_backtest as lvb
        rows = lvb.run(recent, [(None, leg)])
    except Exception as exc:  # allow-silent: becomes a missing input
        return {"read_state": "could_not_look", "reason": str(exc)[:160]}
    keep = ("book", "verdict", "closed", "r_trades", "live_r", "p5", "p50", "p95", "live_percentile",
            "backtest_n", "backtest_expectancy_r", "why")
    return {"read_state": "read", "rows": [{k: r.get(k) for k in keep if k in r} for r in rows]}


def context_v3(s: "Snapshot", pkg: str, view: dict, meta: dict, symbol: Optional[str],
               tf: Optional[str], bars: List[dict], atr_now: Optional[float], entry: Optional[float],
               sl: Optional[float], tp: Optional[float], leg: str, now: datetime,
               miss: Callable[[str, str], None]) -> dict:
    chart = chart_block(bars, atr_now)
    if chart is None:
        miss("context_v3.chart", "no closed candles on the leg timeframe (route unreachable or timeframe unrecorded)")
    else:
        chart["timeframe"] = tf
        chart["since_entry"] = since_entry(bars, _opened_ts(view["package"], view["trades"]), atr_now)
        if chart["since_entry"] is None:
            miss("context_v3.chart.since_entry", "package open time not in the journal reads")
    htf = None
    htf_tf = HTF_OF.get(tf or "")
    if chart is not None and htf_tf and symbol:
        if htf_tf == "1w":
            hb = weekly(bars)
        else:
            hb = _closed_bars((_candles(s, symbol, htf_tf, 120) or {}).get("candles") or [], htf_tf, now)
        if hb:
            h_atr = atr_sma(hb, 14)
            t_now, adx = trend_now(hb)
            hc = chart_block(hb, h_atr, HTF_BARS)
            htf = dict(hc, timeframe=htf_tf, trend_now=t_now, adx_now=_sig(adx, 4))
    if htf is None:
        miss("context_v3.htf", f"no closed candles on the higher timeframe {htf_tf!r}" if htf_tf else f"no higher timeframe mapped for {tf!r}")
    lvb_ = live_vs_backtest_block(s, leg)
    if lvb_ is None:
        miss("context_v3.live_vs_backtest", "api/bot/performance/recent not read")
    return {"chart": chart, "htf": htf, "book": book_block(s, pkg), "book_note": BOOK_NOTE,
            "exit_plan": exit_plan_block(view["package"], meta, entry, sl, tp), "live_vs_backtest": lvb_}


# ----------------------------------------------------------------------------- the packet

def _package_view(s: Snapshot, pkg: str) -> dict:
    p = s.packages.get(pkg)
    trade_rows = [t for t in s.trades if t.get("order_package_id") == pkg]
    tel = [r for r in (s.get("telemetry") or {}).get("rows", []) if r.get("order_package_id") == pkg]
    tickets = [t for t in (s.get("prop_tickets") or {}).get("tickets", []) if t.get("order_package_id") == pkg]
    return {"package": p, "trades": trade_rows, "telemetry": tel, "tickets": tickets}


def _accounts_for(view: dict, cfg: Dict[str, dict]) -> List[dict]:
    seen: Dict[str, dict] = {}
    pkg_open = (view["package"] or {}).get("status") == "open"
    for t in view["trades"]:
        # a rejected/skipped row never carried the package; a closed row carries it only while the package
        # itself is no longer open (its leftovers are the story), never beside a still-open package
        if t.get("account_id") and (t.get("status") == "open" or (not pkg_open and t.get("status") == "closed")):
            seen.setdefault(t["account_id"], {})["trade"] = t
    for r in view["telemetry"]:
        if r.get("account_id"):
            seen.setdefault(r["account_id"], {})["telemetry"] = r
    for t in view["tickets"]:
        seen.setdefault(t["account_id"], {})["ticket"] = t
    out = []
    for aid, d in seen.items():
        c = cfg.get(aid, {})
        out.append({"account_id": aid, "account_class": c.get("account_class") or (d.get("trade") or {}).get("account_class"),
                    "exchange": c.get("exchange"), **d})
    out.sort(key=lambda a: (CLASS_ORDER.get(a["account_class"], 9), a["account_id"]))
    return out


def _phone_refusal(s: Snapshot, account: str, ticket: dict) -> dict:
    pt = (ticket or {}).get("phone_trail") or {}
    if not pt.get("amend_id"):
        return {}
    key = pt["amend_id"].replace("#", "")
    reason = None
    for e in (s.get(f"prop_status:{account}") or {}).get("phone_events", []):
        txt = str(e.get("reason") or "")
        if key in txt and "REFUSED" in txt.upper():
            reason = txt
    return {"amend_id": pt["amend_id"], "amend_status": pt.get("amend_status"), "fails": pt.get("fails"),
            "last_plan_action": pt.get("last_plan_action"), "last_plan_why": pt.get("last_plan_why"),
            "refusal_reason": reason,
            "refusal_reason_state": "read" if reason else "not_in_phone_events"}


def _siblings(s: Snapshot, pkg: Optional[str], account: str, symbol: str) -> List[str]:
    """OTHER open packages on this account + symbol (journal trade rows and filled prop tickets)."""
    out = {t.get("order_package_id") for t in s.trades
           if t.get("status") == "open" and t.get("account_id") == account and t.get("symbol") == symbol}
    out |= {t.get("order_package_id") for t in (s.get("prop_tickets") or {}).get("tickets", [])
            if t.get("status") == "filled" and t.get("account_id") == account and t.get("symbol") == symbol}
    return sorted(o for o in out if o and o != pkg)


#: The live-review executor matrix (scripts/ops/live_review_apply.py): ACTION_PATHS holds the trade actions;
#: the SL tighten dispatches separately (``run()``: bybit / alpaca / prop_vm / phone; ``other`` -- IB -- has none).
TIGHTEN_CLASSES = ("bybit", "alpaca", "prop_vm", "phone")


def apply_paths(exchange: Optional[str]) -> Optional[List[str]]:
    """The actions live_review_apply.py can execute on a NON-prop account of this exchange (None = could not look)."""
    try:
        sys.path.insert(0, str(REPO))
        from scripts.ops.live_review_apply import ACTION_PATHS
    except Exception:  # allow-silent: the caller records could_not_look
        return None
    cls = {"bybit": "bybit", "alpaca": "alpaca"}.get(str(exchange or "").lower(), "other")
    return sorted(set(ACTION_PATHS.get(cls, ())) | ({"tighten"} if cls in TIGHTEN_CLASSES else set()))


def prop_apply_paths(account_id: str) -> Optional[List[str]]:
    """The actions live_review_apply.py can execute on a prop account (phone / prop_vm), None = could not look."""
    try:
        sys.path.insert(0, str(REPO))
        from scripts.ops import live_review_apply as lra
        cls = lra.account_class(account_id, _accounts_cfg().get(account_id) or {})
    except Exception:  # allow-silent: the caller records could_not_look
        return None
    return sorted(set(lra.ACTION_PATHS.get(cls, ())) | ({"tighten"} if cls in TIGHTEN_CLASSES else set()))


def _mechanics(s: Snapshot, view: dict, accts: List[dict], sl: Optional[float], tp: Optional[float],
               direction: str, symbol: str) -> Tuple[dict, List[dict]]:
    """Venue vs journal vs package for every account; one verdict plus the evidence, and the per-account reads."""
    ev: List[str] = []
    bad = looked_fail = 0
    bounds: List[dict] = []
    p = view["package"]
    pkg_status = p.get("status") if p else None
    pkg_id = (p or {}).get("order_package_id") or next(
        (x.get("order_package_id") for x in view["trades"] + view["telemetry"] + view["tickets"] if x.get("order_package_id")), None)
    for a in accts:
        aid, cls, ex = a["account_id"], a["account_class"], a.get("exchange")
        item = {"account_id": aid, "account_class": cls, "read": None,
                "read_basis": "depends on the recommendation: no_action for hold/no_recommendation, else see read_if_amend",
                "read_if_amend": "unknown", "evidence": None}
        if cls == "prop":
            tk, st = a.get("ticket"), s.get(f"prop_status:{aid}")
            pos = None
            if st is not None:
                try:
                    raw = json.loads((st.get("status") or {}).get("raw") or "{}")
                except ValueError:
                    raw = {}
                if "positions" in raw:
                    pos = [x for x in raw["positions"] if x.get("symbol") == symbol]
            ref = _phone_refusal(s, aid, tk) if tk else {}
            if tk and tk.get("status") == "filled":
                if pos is None:
                    looked_fail += 1
                    ev.append(f"{aid}: ticket filled, positions field absent in status")
                elif pos and pkg_status == "closed" and _siblings(s, pkg_id, aid, symbol):
                    ev.append(f"{aid}: package {pkg_status}; the open {symbol} position belongs to sibling package(s) "
                              f"{', '.join(_siblings(s, pkg_id, aid, symbol))}, not read as an orphan")
                elif pos and pkg_status == "closed":
                    bad += 1
                    ev.append(f"{aid}: ticket {tk['status']}/{tk.get('close_reason')} and package {pkg_status}, but status still reports {len(pos)} open {symbol} {direction}")
            elif tk and pos is None:
                looked_fail += 1
            if ref.get("amend_status") == "refused":
                item["read_if_amend"] = "refused_by_account_risk"
                item["evidence"] = (f"amend {ref['amend_id']} refused, fails {ref.get('fails')}; reason: "
                                    f"{ref.get('refusal_reason') or 'not readable from a session (phone events do not carry it)'}")
            else:
                paths = prop_apply_paths(aid)
                item["apply_paths"] = paths
                item["evidence"] = ((f"apply paths {', '.join(paths)}" if paths else
                                     "apply paths could_not_look" if paths is None else "no apply path")
                                    + " (live_review_apply.py); positions "
                                    + ("unreadable (status carries no positions field)" if pos is None else f"read: {len(pos)} open"))
            if ref:
                item["phone_amend"] = ref
        else:
            tr = a.get("trade") or {}
            sibs = _siblings(s, pkg_id, aid, symbol)
            v = _venue_exit_prices(s, aid, ex or "", symbol, direction, tr.get("sl_order_id"), tr.get("tp_order_id"),
                                   trade_id=tr.get("id"), broker_order_id=tr.get("broker_order_id"),
                                   qty=_f(tr.get("position_size")), siblings=len(sibs))
            tr = a.get("trade")
            trade_open = (tr or {}).get("status") == "open" or (a.get("telemetry") or {}).get("lifecycle") == "open"
            if v["state"] != "read":
                looked_fail += 1
                item["evidence"] = v["why"]
            else:
                if trade_open and not v["position"]:
                    bad += 1
                    ev.append(f"{aid}: journal open but no {symbol} position/protection at the venue")
                elif trade_open:
                    if sl is not None and v["sl"] is not None and not _close(v["sl"], sl):
                        bad += 1
                        ev.append(f"{aid}: venue SL {v['sl']} != package SL {sl}")
                    if tp is not None and v["tp"] is not None and not _close(v["tp"], tp):
                        bad += 1
                        ev.append(f"{aid}: venue TP {v['tp']} != package TP {tp}")
                    if v.get("ambiguous"):
                        ev.append(f"{aid}: several {symbol} bracket legs rest at the venue and none matches this package's order ids; levels not compared")
                    elif tp is not None and v["tp"] is None:
                        ev.append(f"{aid}: no resting TP found at the venue read")
                elif v["position"] and sibs:
                    ev.append(f"{aid}: venue holds {symbol} for sibling package(s) {', '.join(sibs)}; this package's trade row is not open")
                elif v["position"]:
                    bad += 1
                    ev.append(f"{aid}: venue still holds {symbol} but its trade row is not open (orphan or missed close)")
                item["evidence"] = (f"{v['src']}: SL {v['sl']} / TP {v['tp']}, position {v['position']}, "
                                    f"matched by {v.get('matched_by')}"
                                    + (f", {len(sibs)} sibling package(s) on {symbol}" if sibs else ""))
                paths = apply_paths(ex)
                item["apply_paths"] = paths
                item["read_if_amend"] = ("would_apply" if paths and v["position"] and not v.get("ambiguous") else "unknown")
                if paths is None:
                    item["evidence"] += "; apply paths could_not_look (live_review_apply.py did not import)"
                elif not paths:
                    item["evidence"] += f"; no apply path for {ex} (live_review_apply.py ACTION_PATHS / tighten dispatch: none)"
                else:
                    item["evidence"] += (f"; apply paths {', '.join(paths)}; would_apply = an executor reaches this leg, "
                                         "NOT that its RiskManager approved (LTR-6 gap)")
        bounds.append(item)
    verdict = "mismatch" if bad else ("could_not_look" if looked_fail and not accts else "match")
    if not bad and looked_fail:
        verdict = "match" if looked_fail < len(accts) else "could_not_look"
        ev.append(f"{looked_fail} account(s) could not be read")
    if not ev:
        ev.append(f"package sl {sl} / tp {tp} agree with every readable account")
    return {"verdict": verdict, "evidence": "; ".join(ev)}, bounds


def _calendar(symbol: str, cutoff: datetime) -> dict:
    import yaml
    cal = yaml.safe_load((REPO / "config" / "economic_calendar.yaml").read_text()) or {}
    base = re.sub(r"(USDT|USD|PERP)$", "", symbol)
    classes = (cal.get("symbol_event_classes") or {}).get(base)
    if not classes:
        return {"state": "no_event_classes_for_symbol", "events_next_24h": []}
    evs = []
    latest = None
    for e in cal.get("events") or []:
        t = datetime.fromisoformat(str(e["time"]).replace("Z", "+00:00"))
        latest = max(latest, t) if latest else t
        if e.get("class") in classes and cutoff <= t <= cutoff + timedelta(hours=24):
            evs.append({"class": e["class"], "time": e["time"], "impact": e.get("impact")})
    if latest is None or latest < cutoff:
        return {"state": "stale", "events_next_24h": [],
                "reason": f"config/economic_calendar.yaml newest event is {latest and latest.date()}; it is not being refreshed, so 'no events' is NOT known"}
    return {"state": "read", "events_next_24h": evs}


def _price(leg: str, side: str, tel: dict, atr_mult: Optional[float], review_id: str, write: bool,
           tables_out: Optional[Dict[str, dict]] = None) -> Tuple[Optional[dict], Optional[str]]:
    if not (REPO / "comms" / "strategy_evidence" / f"{leg}.json").exists():
        # LTR-PACKET-FIXES B (2026-11-01): trend_donchian_1h traded on bybit_1 with no record and the packet carried
        # a bare FileNotFoundError traceback. A missing record is a named state, and a ladder finding.
        return None, (f"{EVIDENCE_MISSING}: no committed Stage-0 evidence record comms/strategy_evidence/{leg}.json "
                      "(build: scripts/ops/build_strategy_evidence.py --strategy <leg>)")
    if tel.get("open_r") is None or tel.get("peak_r") is None or atr_mult is None:
        return None, "open_r/peak_r/atr_stop_mult not available for this package"
    cmd = [sys.executable, str(REPO / "scripts/research/live_review_outcomes.py"), "--leg", leg, "--side", side,
           "--open-r", str(tel["open_r"]), "--peak-r", str(tel["peak_r"]), "--atr-stop-mult", str(atr_mult), "--json",
           # the leg's committed full-history corpus (comms/strategy_evidence/ltr_corpus/) when it has one, else
           # the evidence record's source_run; the packet records which one priced it (corpus_source)
           "--corpus", "auto"]
    if tel.get("bars_held") is not None:
        cmd += ["--bars-held", str(int(tel["bars_held"]))]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
    if out.returncode != 0:
        return None, f"live_review_outcomes failed: {out.stderr.strip()[-200:]}"
    table = json.loads(out.stdout)
    rel = f"comms/live_review/tables/{review_id}.json"
    if write:
        TABLES_DIR.mkdir(parents=True, exist_ok=True)
        (REPO / rel).write_text(json.dumps(table, indent=2) + "\n")
    if tables_out is not None:
        tables_out[rel] = table
    full = str(table["corpus"]).startswith(LTR_CORPUS_DIR)
    return {"biases": table["biases"], "corpus": table["corpus"],
            "corpus_source": "ltr_full_history" if full else "evidence_source_run",
            "corpus_trades": (table.get("population") or {}).get("corpus_trades"),
            "candles": table.get("candles"), "n_floor": table["n_floor"], "options": table["options"],
            "population": table["population"], "read_state": table["read_state"], "source": rel}, None


EVIDENCE_MISSING = "evidence_missing"


def priced_state(priced: Optional[dict], why: Optional[str], asked: bool) -> str:
    """The read state beside the nullable ``priced_options``: priced / evidence_missing / could_not_price / not_priced."""
    if priced is not None:
        return "priced"
    if not asked:
        return "not_priced"
    return EVIDENCE_MISSING if (why or "").startswith(EVIDENCE_MISSING) else "could_not_price"


DESK_LEG = "claude_desk"
DESK_DECISIONS = "comms/desk/decisions.jsonl"


def _desk_rows() -> Optional[List[dict]]:
    """Every desk decision row: main's mirror plus the ``desk/decisions`` branch tip (newer). None = could not look."""
    texts = []
    try:
        texts.append((REPO / DESK_DECISIONS).read_text())
    except OSError:
        pass
    try:
        out = subprocess.run(["git", "-C", str(REPO), "show", f"origin/desk/decisions:{DESK_DECISIONS}"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            texts.append(out.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    if not texts:
        return None
    rows: Dict[str, dict] = {}
    for t in texts:
        for ln in t.splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("decision_id"):
                rows[r["decision_id"]] = r
    return list(rows.values())


PREV_REASON_MAX = 400  # chars of the prior row's recommendation.reason carried into previous_review (packet size)


def previous_review_block(r: dict) -> dict:
    """The packet's ``context.previous_review`` for the newest prior review row on a package.

    The first four keys are the original shape. ``forecast`` is the prior row's ``forecast`` object verbatim (its
    ``thesis`` is inside it), or an explicit None when that row carries none (mechanics / record_only / pre-rule
    rows): never a fabricated value. ``reason`` is the prior recommendation's reason, cut to PREV_REASON_MAX."""
    rec = r.get("recommendation") or {}
    fc = r.get("forecast")
    reason = rec.get("reason")
    if isinstance(reason, str) and len(reason) > PREV_REASON_MAX:
        reason = reason[:PREV_REASON_MAX - 1] + "\u2026"
    return {"review_id": r.get("review_id"), "reviewed_at": r.get("reviewed_at"),
            "action": rec.get("action"), "route": rec.get("route"),
            "forecast": fc if isinstance(fc, dict) and fc else None, "reason": reason}


def build_packet(pkg: str, s: Snapshot, now: datetime, *, write_tables: bool = False,
                 cfg: Optional[Dict[str, dict]] = None, price: bool = True,
                 tables_out: Optional[Dict[str, dict]] = None) -> dict:
    cfg = cfg if cfg is not None else _accounts_cfg()
    view = _package_view(s, pkg)
    p, tel = view["package"], (view["telemetry"] or [{}])[0]
    missing: List[dict] = []

    def miss(field_: str, why: str) -> None:
        missing.append({"field": field_, "reason": why})

    meta = _json((p or {}).get("meta"))
    tr0 = (view["trades"] or [{}])[0]
    leg = (p or {}).get("strategy_name") or tel.get("strategy") or tr0.get("strategy_name") or "unknown"
    symbol = (p or {}).get("symbol") or tel.get("symbol") or tr0.get("symbol")
    direction = (p or {}).get("direction") or tel.get("direction") or tr0.get("direction")
    entry = _f((p or {}).get("entry")) or _f(tel.get("entry"))
    sl = _f((p or {}).get("sl")) if p else None
    tp = _f((p or {}).get("tp")) if p else None
    if p is None:
        miss("state.sl/tp", "order_packages row not in the paged journal read; falling back to the trade row")
        sl, tp = _f(tr0.get("stop_loss")), _f(tr0.get("take_profit_1"))
        if sl is None and tel.get("risk_per_unit") and entry:
            sl = entry + (tel["risk_per_unit"] if direction == "short" else -tel["risk_per_unit"])
            miss("state.sl", "derived from telemetry entry +/- risk_per_unit (initial stop), not the live stop")
    accts = _accounts_for(view, cfg)
    for e in s.errors:
        miss(f"read:{e}", s.errors[e])
    if (s.get("generator") or {}).get("state") == "stale_vs_origin_main":
        miss("generator", "this generator differs from origin/main's; rebuild the packet from a main checkout")

    # --- state / features (telemetry first; the public positions r-block for a real-money row it lacks)
    pos_r = {}
    for x in s.get("positions") or []:
        if x.get("symbol") == symbol and x.get("pattern") == leg and x.get("r"):
            pos_r = x["r"]
    def tv(k_tel: str, k_pos: str) -> Optional[float]:
        return _f(tel.get(k_tel)) if tel.get(k_tel) is not None else _f(pos_r.get(k_pos))
    open_r, peak_r, giveback = tv("open_r", "openR"), tv("peak_r", "peakR"), tv("giveback_r", "givebackR")
    bars_held = tel.get("bars_held") if tel.get("bars_held") is not None else pos_r.get("barsHeld")
    if open_r is None:
        miss("state.open_r", "no position_telemetry row for this package (telemetry covers the donchian/pullback family) and no /api/bot/positions row")
    provenance = tel.get("peak_provenance") or pos_r.get("peakProvenance") or "unverified"

    # --- candles: ATR now / trend now
    tf = meta.get("timeframe")
    atr_ratio = trend = adx = a_now = None
    bars: List[dict] = []
    if symbol and tf in TF_SECONDS:
        cd = _candles(s, symbol, tf)
        bars = _closed_bars((cd or {}).get("candles") or [], tf, now)
        a_now = atr_sma(bars, int(meta.get("atr_period") or 14))
        a_entry = _f(meta.get("atr"))
        if a_now and a_entry:
            atr_ratio = round(a_now / a_entry, 4)
        else:
            miss("regime.atr_now_over_entry", "candles unavailable or meta.atr (ATR at entry) not recorded")
        trend, adx = trend_now(bars)
        if trend is None:
            miss("regime.trend_now", "fewer than 30 closed bars, or the detector could not be imported")
    else:
        miss("regime.atr_now_over_entry", "package timeframe not recorded in meta")
        miss("regime.trend_now", "package timeframe not recorded in meta")
    miss("regime.vol_now", "calm/volatile buckets use frozen edges held only in the VM model registry; not reachable read-only from a session")
    ent_t, ent_v = meta.get("regime"), meta.get("vol_regime")
    cell_entry = f"{ent_t}/{ent_v}" if ent_t in ("trending", "transitional", "chop") and ent_v in ("calm", "volatile") else None
    if cell_entry is None:
        miss("regime.cell_entry", f"entry meta regime={ent_t!r} vol_regime={ent_v!r}: not both known")

    mech, bounds = _mechanics(s, view, accts, sl, tp, direction or "", symbol or "")
    if p is not None and p.get("status") != "open":
        mech["evidence"] = f"order_packages status={p.get('status')} close_reason={p.get('close_reason')}; " + mech["evidence"]

    review_id = f"LR-{now.strftime('%Y%m%dT%H%MZ')}-{pkg}"
    priced = why = None
    if price and direction:
        priced, why = _price(leg, direction, {"open_r": open_r, "peak_r": peak_r, "bars_held": bars_held},
                             _f(meta.get("atr_stop_mult")), review_id, write_tables, tables_out)
        if why:
            miss("priced_options", why)
    cost = {"basis": "evidence-record net_r per trade (fee + slippage + funding, execution_costs.resolve_cost_policy)"} if priced else {"basis": None}

    perp = bool(symbol and symbol.endswith("USDT"))
    if perp:
        miss("context.funding", "Bybit public funding API is geo-blocked from session networks and no read-only diag route carries funding_now; needs a diag route")
    news = None
    for r in (s.get("news") or {}).get("records", []):
        if r.get("symbol") == symbol:
            news = {"ts": r.get("ts"), "decision": r.get("decision"), "adjustment": r.get("adjustment"), "veto": r.get("veto")}
            break
    if news is None:
        miss("context.news", "no news decision for this symbol in the last 60 records (or news read failed)")
    cal = _calendar(symbol or "", now)
    if cal["state"] == "stale":
        miss("context.calendar", cal["reason"])
    corr = [{"order_package_id": o, "symbol": (s.packages.get(o) or {}).get("symbol"), "direction": (s.packages.get(o) or {}).get("direction")}
            for o in open_package_ids(s) if o != pkg and (s.packages.get(o) or {}).get("direction") == direction]
    prev = None
    all_reviews: Optional[List[dict]] = None
    try:
        from src.runtime import live_review_due as _lrd
        all_reviews = _lrd.read_reviews_merged(str(REVIEWS))["rows"]
        mine = [r for r in all_reviews if r.get("order_package_id") == pkg]
        mine.sort(key=lambda r: str(r.get("reviewed_at") or ""))
    except Exception:  # noqa: BLE001  # allow-silent: no previous_review beats a failed packet
        mine = []
    for r in mine[-1:]:
        prev = previous_review_block(r)
    ctx3 = context_v3(s, pkg, view, meta, symbol, tf, bars, a_now, entry, sl, tp, leg, now, miss)
    if ctx3["live_vs_backtest"] is None:
        miss("context.live_vs_backtest", "per-leg live-vs-backtest read failed (api/bot/performance/recent); see context_v3")

    handoff = None
    if leg == DESK_LEG:  # DESK-HANDOFF-PROTOCOL (b): the opening desk record + the chain, for every wake
        from src.runtime import desk_handoff as _dh
        handoff = _dh.handoff_block(pkg, meta, _desk_rows(), all_reviews)
        if handoff["read_state"] != "read":
            miss("desk_handoff", "; ".join(handoff["missing"]) or "could not look")

    reads = [t for k, t in s.read_at.items()]
    cutoff = max(reads) if reads else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    packet = {
        "account_bounds": bounds,
        "assembled_by": f"generator {GENERATOR}",
        "context": {"calendar": cal, "correlated_open_packages": corr,
                    "funding": None if perp else {"state": "not_applicable"}, "news": news,
                    "previous_review": prev, "symbol": symbol, "direction": direction},
        "context_v3": ctx3,
        "cost": cost,
        **({"desk_handoff": handoff} if handoff is not None else {}),
        "features_at_review": {"atr_now_over_entry": atr_ratio, "bars_since_peak": tel.get("bars_since_peak") if tel else pos_r.get("barsSincePeak"),
                               "giveback_r": giveback, "open_r": open_r, "peak_r": peak_r,
                               "r_to_stop": tv("r_to_stop", "rToStop"), "r_to_target": tv("r_to_target", "rToTarget")},
        "generator": s.get("generator") or {"state": "not_checked"},
        "info_cutoff_at": cutoff,
        "leg": leg,
        "mechanics": mech,
        "missing_inputs": missing,
        "order_package_id": pkg,
        "packet_version": PACKET_VERSION,
        "priced_options": priced,
        "priced_options_state": priced_state(priced, why, bool(price and direction)),
        "regime": {"adx_now": adx, "atr_now_over_entry": atr_ratio, "cell_entry": cell_entry, "cell_now": None, "trend_now": trend},
        "review_id": review_id,
        "state": {"atr_now_over_entry": atr_ratio, "bars_held": bars_held, "giveback_r": giveback, "open_r": open_r,
                  "peak_provenance": provenance, "peak_r": peak_r, "regime_cell_entry": cell_entry, "regime_cell_now": None,
                  "sl": sl, "tp": tp},
    }
    return packet


# ----------------------------------------------------------------------------- CLI

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", nargs="?", help="order_package_id")
    ap.add_argument("--all-open", action="store_true", help="every package open in ANY source (telemetry, journal, prop tickets)")
    ap.add_argument("--write", action="store_true", help="write comms/live_review/packets/<review_id>.json (+ the priced table)")
    ap.add_argument("--bundle", action="store_true",
                    help="print {packet, packet_sha, table_path, table} per package and write NOTHING "
                         "(the VM wake poster attaches this to the ltr-wake comment, LTR C2)")
    ap.add_argument("--max-pages", type=int, default=3, help="journal pages to walk, stopping once every wanted package is found")
    a = ap.parse_args(argv)
    if bool(a.package) == bool(a.all_open):
        ap.error("give exactly one of <order_package_id> or --all-open")
    if a.bundle and a.write:
        ap.error("--bundle writes nothing; drop --write")
    snap = collect([a.package] if a.package else None, max_pages=a.max_pages)
    ids = [a.package] if a.package else open_package_ids(snap)
    now = datetime.now(timezone.utc)
    out = []
    for pkg in ids:
        tables: Dict[str, dict] = {}
        pk = build_packet(pkg, snap, now, write_tables=a.write, tables_out=tables)
        sha = packet_sha(pk)
        if a.bundle:
            src = (pk.get("priced_options") or {}).get("source")
            out.append({"packet": pk, "packet_sha": sha, "table_path": src, "table": tables.get(src)})
            continue
        if a.write:
            PACKETS_DIR.mkdir(parents=True, exist_ok=True)
            (PACKETS_DIR / f"{pk['review_id']}.json").write_text(json.dumps(pk, indent=1, sort_keys=True) + "\n")
        out.append({"packet": pk, "packet_sha": sha})
    print(json.dumps(out if a.all_open else out[0], indent=1, sort_keys=True))
    print(f"# open set ({len(ids)}): {', '.join(ids)}; read errors: {snap.errors or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
