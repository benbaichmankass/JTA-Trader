#!/usr/bin/env python3
# wiring: invoked by path from src/runtime/short_hold_wake.py (the VM, every 5-min bar of an open short-hold package); also run by hand for a recommend-only dry run (skill trading-desk SHORT-HOLD-BRIEF.md § 7).
"""In-trade packet at 5-minute granularity for ONE package (DESK-SHORT-HOLD-LANE).

    python3 scripts/ops/short_hold_packet.py pkg-...                 # print the envelope
    python3 scripts/ops/short_hold_packet.py pkg-... --out FILE      # write it

It is the live-review decision packet (``scripts/ops/live_review_packet.py``, LTR-11: state, mechanics, priced
options, account bounds, ``missing_inputs``) PLUS a ``short_hold`` block read on 5-minute bars: the last closed
5m bar, its close (the mark), ATR14 on 5m, open R at the mark, minutes held and the last 12 closed 5m bars. The
block is added INSIDE the packet before ``packet_sha`` is taken, so a decision joins to exactly what was seen.

The envelope a short-hold lane reads (``comms/live_review/short_hold/<pkg>/latest.json`` on the rows branch):
``{order_package_id, bar, bar_close, built_at, packet, packet_sha, table_path, table, short_hold, closed}``.

PURE READS (diag relay / public routes / committed evidence), like the builder it wraps. A 5m input it cannot
read is ``null`` and named in ``missing_inputs``; it is never 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import live_review_packet as lrp  # noqa: E402

TF = "5m"
BAR_S = 300
RECENT_BARS = 12


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bar_open(c: dict) -> Optional[datetime]:
    v = c.get("time", c.get("t", c.get("timestamp")))
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def five_min_block(packet: dict, candles: Optional[List[dict]], now: datetime,
                   opened_at: Optional[str] = None, entry: Optional[float] = None,
                   risk_per_unit: Optional[float] = None) -> Dict[str, Any]:
    """Pure. The 5-minute view of one open package. Unread -> null fields + ``read_state``."""
    st = packet.get("state") or {}
    side = (packet.get("context") or {}).get("direction")
    bars = lrp._closed_bars(candles or [], TF, now) if candles else []
    out: Dict[str, Any] = {"timeframe": TF, "read_state": "read" if bars else "could_not_look",
                           "bar": None, "bar_close": None, "mark": None, "atr": None, "entry": entry,
                           "risk_per_unit": risk_per_unit, "open_r_at_mark": None,
                           "minutes_held": None, "recent_bars": []}
    if opened_at:
        o = lrp_ts(opened_at)
        if o:
            out["minutes_held"] = round((now - o).total_seconds() / 60, 1)
    if not bars:
        return out
    last = bars[-1]
    t = _bar_open(last)
    out["bar"] = _iso(t) if t else None
    out["bar_close"] = _iso(t + timedelta(seconds=BAR_S)) if t else None
    mark = lrp._f(last.get("close", last.get("c")))
    out["mark"] = mark
    out["atr"] = lrp.atr_sma(bars, 14)
    # R unit = the INITIAL risk (telemetry risk_per_unit); |entry - current stop| only when that is unread,
    # and then said so, because a trailed stop shrinks it.
    risk = risk_per_unit if risk_per_unit and risk_per_unit > 0 else None
    out["r_unit"] = "risk_per_unit" if risk else None
    if risk is None and entry and lrp._f(st.get("sl")) and entry != lrp._f(st.get("sl")):
        risk, out["r_unit"] = abs(entry - lrp._f(st.get("sl"))), "entry_to_current_sl"
    open_r = None
    if mark is not None and entry and risk and side in ("long", "short"):
        open_r = (mark - entry) / risk if side == "long" else (entry - mark) / risk
    out["open_r_at_mark"] = round(open_r, 4) if isinstance(open_r, (int, float)) else None
    out["recent_bars"] = [{"t": _iso(_bar_open(b)) if _bar_open(b) else None,
                           **{k: lrp._f(b.get(k, b.get(k[0]))) for k in ("open", "high", "low", "close")}}
                          for b in bars[-RECENT_BARS:]]
    return out


def lrp_ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build_envelope(pkg: str, *, now: Optional[datetime] = None, snapshot: Optional[lrp.Snapshot] = None,
                   candles_fn: Callable[[str], Any] = lrp._public, opened_at: Optional[str] = None) -> Dict[str, Any]:
    """The envelope for ``pkg``: the LTR-11 packet + the 5-min block, sha taken over both."""
    now = now or datetime.now(timezone.utc)
    snap = snapshot if snapshot is not None else lrp.collect([pkg])
    tables: Dict[str, dict] = {}
    pk = lrp.build_packet(pkg, snap, now, tables_out=tables)
    symbol = (pk.get("context") or {}).get("symbol")
    candles = None
    if symbol:
        try:
            candles = (candles_fn(f"api/bot/candles?symbol={symbol}&interval={TF}&limit=60") or {}).get("candles")
        except Exception as exc:  # allow-silent: recorded as a missing input, never 0
            pk["missing_inputs"].append({"field": "short_hold.candles_5m", "reason": str(exc)[:160]})
    view = lrp._package_view(snap, pkg)
    p, tel = view.get("package") or {}, (view.get("telemetry") or [{}])[0]
    entry = lrp._f(p.get("entry")) or lrp._f(tel.get("entry"))
    block = five_min_block(pk, candles, now, opened_at or p.get("created_at") or tel.get("opened_at"),
                           entry=entry, risk_per_unit=lrp._f(tel.get("risk_per_unit")))
    if block["read_state"] != "read":
        pk["missing_inputs"].append({"field": "short_hold", "reason": "no closed 5m candles read"})
    pk["short_hold"] = block
    sha = lrp.packet_sha(pk)
    src = (pk.get("priced_options") or {}).get("source")
    return {"order_package_id": pkg, "bar": block["bar"], "bar_close": block["bar_close"], "built_at": _iso(now),
            "packet": pk, "packet_sha": sha, "table_path": src, "table": tables.get(src), "short_hold": block,
            "closed": False}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("package")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--opened-at", default=None)
    a = ap.parse_args(argv)
    env = build_envelope(a.package, opened_at=a.opened_at)
    text = json.dumps(env, indent=1, sort_keys=True, default=str) + "\n"
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)
        print(f"short_hold_packet: {a.package} bar {env['bar']} sha {env['packet_sha'][:12]} -> {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
