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
PACKET_VERSION = 2  # v1 = the hand-built packets; v2 is a strict superset of their keys
GENERATOR = "scripts/ops/live_review_packet.py"
PUBLIC_BASE = "https://ict-bot.duckdns.org"
PACKETS_DIR = REPO / "comms" / "live_review" / "packets"
TABLES_DIR = REPO / "comms" / "live_review" / "tables"
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

def _venue_exit_prices(s: Snapshot, account: str, exchange: str, symbol: str, direction: str) -> dict:
    """Resting SL/TP and position presence for one account on one symbol, or could-not-look."""
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
    if exchange == "bybit":
        res = acct.get("result") or {}
        pos = next((p for p in res.get("positions", []) if p.get("symbol") == symbol and (p.get("size") or 0) > 0), None)
        for o in res.get("orders", []):
            if o.get("symbol") != symbol:
                continue
            kind = str(o.get("stop_order_type") or "")
            if "StopLoss" in kind:
                sl = _f(o.get("trigger_price"))
            elif "TakeProfit" in kind:
                tp = _f(o.get("trigger_price"))
        if sl is None and pos:
            sl = _f(pos.get("stop_loss"))
        if tp is None and pos:
            tp = _f(pos.get("take_profit"))
        pos_present = pos is not None
    elif exchange == "alpaca":
        res = acct.get("result") or {}
        pos = next((p for p in res.get("positions", []) if p.get("symbol") == symbol), None)
        for o in res.get("orders", []):
            if o.get("symbol") != symbol or str(o.get("side")) != exit_side and o.get("order_class") != "bracket":
                continue
            if _f(o.get("stop_price")) is not None and o.get("order_type") in ("stop", "stop_limit"):
                sl = _f(o["stop_price"])
            elif o.get("order_type") == "limit" and _f(o.get("limit_price")) is not None:
                tp = _f(o["limit_price"])
        pos_present = pos is not None or sl is not None or tp is not None
    else:  # interactive_brokers
        for o in acct.get("orders") or []:
            if o.get("symbol") != symbol or str(o.get("action", "")).lower() != exit_side:
                continue
            if o.get("order_type") == "STP":
                sl = _f(o.get("aux_price"))
            elif o.get("order_type") == "LMT":
                tp = _f(o.get("lmt_price"))
        pos_present = sl is not None or tp is not None
    return {"state": "read", "position": pos_present, "sl": sl, "tp": tp, "src": src}


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


def _mechanics(s: Snapshot, view: dict, accts: List[dict], sl: Optional[float], tp: Optional[float],
               direction: str, symbol: str) -> Tuple[dict, List[dict]]:
    """Venue vs journal vs package for every account; one verdict plus the evidence, and the per-account reads."""
    ev: List[str] = []
    bad = looked_fail = 0
    bounds: List[dict] = []
    p = view["package"]
    pkg_status = p.get("status") if p else None
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
                item["evidence"] = ("no apply path for this action until LTR-8; positions "
                                    + ("unreadable (status carries no positions field)" if pos is None else f"read: {len(pos)} open"))
            if ref:
                item["phone_amend"] = ref
        else:
            v = _venue_exit_prices(s, aid, ex or "", symbol, direction)
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
                    if sl is not None and not _close(v["sl"], sl):
                        bad += 1
                        ev.append(f"{aid}: venue SL {v['sl']} != package SL {sl}")
                    if tp is not None and v["tp"] is not None and not _close(v["tp"], tp):
                        bad += 1
                        ev.append(f"{aid}: venue TP {v['tp']} != package TP {tp}")
                    if tp is not None and v["tp"] is None:
                        ev.append(f"{aid}: no resting TP found at the venue read")
                elif v["position"]:
                    bad += 1
                    ev.append(f"{aid}: venue still holds {symbol} but its trade row is not open (orphan or missed close)")
                item["evidence"] = f"{v['src']}: SL {v['sl']} / TP {v['tp']}, position {v['position']}"
                item["read_if_amend"] = "would_apply" if ex == "bybit" and v["position"] else "unknown"
                if item["read_if_amend"] == "would_apply":
                    item["evidence"] += "; would_apply = the shared amend reaches this leg, NOT that its RiskManager approved (LTR-6 gap)"
                else:
                    item["evidence"] += "; no apply path for this exchange yet (LTR-9 / none)"
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
    if tel.get("open_r") is None or tel.get("peak_r") is None or atr_mult is None:
        return None, "open_r/peak_r/atr_stop_mult not available for this package"
    cmd = [sys.executable, str(REPO / "scripts/research/live_review_outcomes.py"), "--leg", leg, "--side", side,
           "--open-r", str(tel["open_r"]), "--peak-r", str(tel["peak_r"]), "--atr-stop-mult", str(atr_mult), "--json"]
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
    return {"biases": table["biases"], "corpus": table["corpus"], "n_floor": table["n_floor"], "options": table["options"],
            "population": table["population"], "read_state": table["read_state"], "source": rel}, None


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
    atr_ratio = trend = adx = None
    if symbol and tf in TF_SECONDS:
        cd = s.candles.get(f"{symbol}|{tf}")
        if cd is None and f"{symbol}|{tf}" not in s.candles:
            try:
                cd = _public(f"api/bot/candles?symbol={symbol}&interval={tf}&limit=200")
            except Exception as exc:  # allow-silent: becomes a missing input
                cd = {"candles": [], "error": str(exc)[:120]}
            s.candles[f"{symbol}|{tf}"] = cd
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
    priced = None
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
    if REVIEWS.exists():
        for line in REVIEWS.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("order_package_id") == pkg:
                prev = {"review_id": r["review_id"], "reviewed_at": r.get("reviewed_at"),
                        "action": (r.get("recommendation") or {}).get("action"), "route": (r.get("recommendation") or {}).get("route")}
    miss("context.live_vs_backtest", "per-leg live-vs-backtest verdict not assembled by this generator yet")

    reads = [t for k, t in s.read_at.items()]
    cutoff = max(reads) if reads else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    packet = {
        "account_bounds": bounds,
        "assembled_by": f"generator {GENERATOR}",
        "context": {"calendar": cal, "correlated_open_packages": corr,
                    "funding": None if perp else {"state": "not_applicable"}, "news": news,
                    "previous_review": prev, "symbol": symbol, "direction": direction},
        "cost": cost,
        "features_at_review": {"atr_now_over_entry": atr_ratio, "bars_since_peak": tel.get("bars_since_peak") if tel else pos_r.get("barsSincePeak"),
                               "giveback_r": giveback, "open_r": open_r, "peak_r": peak_r,
                               "r_to_stop": tv("r_to_stop", "rToStop"), "r_to_target": tv("r_to_target", "rToTarget")},
        "info_cutoff_at": cutoff,
        "leg": leg,
        "mechanics": mech,
        "missing_inputs": missing,
        "order_package_id": pkg,
        "packet_version": PACKET_VERSION,
        "priced_options": priced,
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
