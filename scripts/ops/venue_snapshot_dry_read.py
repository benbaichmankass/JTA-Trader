#!/usr/bin/env python3
"""DRY READ for LTR-MECHANICS-VENUE-SNAPSHOT: what the snapshot would hold NOW.

Before the writer is deployed there is no ``venue_protection_snapshot`` table on
the VM to read, so this shows the rows the real open packages WOULD produce. It
reads the live diag relay (read-only: ``open_packages``, ``bybit_open_orders``,
``ib_open_orders``, ``alpaca_open_orders``, ``exchange_positions``,
``position_path_history``), turns each account's resting orders into the same
``stop_prices`` / ``target_prices`` / ``size`` the three broker sweeps hand to
the writer, runs the REAL ``build_snapshot_row`` and the REAL
``live_review_due.venue_events`` over them, and prints the result. It writes
nothing: no database, no file, no venue call beyond the diag GETs.

LIMIT, stated rather than hidden: the per-venue order -> price transform below is
THIS script's, because the diag relay serves raw order lists while the sweeps use
their client coverage reads. So this proves the row builder and the divergence
rule on live prices; it does NOT prove the sweep call sites (tests/ pins those)
and cannot replace the first VM pass.

Usage: python3 scripts/ops/venue_snapshot_dry_read.py [--json]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from src.runtime import live_review_due as lrd  # noqa: E402
from src.runtime import venue_protection_snapshot as vps  # noqa: E402

_BASE = {"MGC": "MGC", "MHG": "MHG"}


def diag(path: str):
    out = subprocess.run([os.path.join(ROOT, "scripts", "ops", "diag_fetch.sh"), path],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SystemExit(f"diag_fetch {path} exit {out.returncode}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def _root(symbol: str) -> str:
    """IB contract root of a journal symbol (``MGCZ6`` -> ``MGC``): longest known prefix."""
    s = str(symbol).upper()
    for r in sorted(_BASE, key=len, reverse=True):
        if s.startswith(r):
            return r
    return s


def bybit_cov(acct: dict, symbol: str, direction: str):
    res = acct.get("result") or {}
    pos = [p for p in (res.get("positions") or []) if p.get("symbol") == symbol]
    if not pos:
        return {"size": 0.0, "stop_prices": [], "target_prices": []}
    p = pos[0]
    stops = [_f(o.get("trigger_price")) for o in (res.get("orders") or [])
             if o.get("symbol") == symbol and str(o.get("stop_order_type")) in ("PartialStopLoss", "StopLoss")]
    tgts = [_f(o.get("trigger_price")) for o in (res.get("orders") or [])
            if o.get("symbol") == symbol and str(o.get("stop_order_type")) in ("PartialTakeProfit", "TakeProfit")]
    if _f(p.get("stop_loss")):
        stops.append(_f(p["stop_loss"]))
    if _f(p.get("take_profit")):
        tgts.append(_f(p["take_profit"]))
    return {"size": p.get("size"), "stop_prices": [x for x in stops if x], "target_prices": [x for x in tgts if x]}


def ib_cov(acct: dict, positions: list, symbol: str):
    root = _root(symbol)
    size = sum(abs(float(p["size"])) for p in positions if str(p.get("symbol")).upper() == root)
    orders = [o for o in (acct.get("orders") or []) if str(o.get("symbol")).upper() == root]
    return {"size": size,
            "stop_prices": [_f(o.get("aux_price")) for o in orders if o.get("order_type") in ("STP", "STP LMT")
                            and _f(o.get("aux_price"))],
            "target_prices": [_f(o.get("lmt_price")) for o in orders if o.get("order_type") == "LMT"
                              and _f(o.get("lmt_price"))]}


def alpaca_cov(acct: dict, symbol: str, direction: str):
    res = acct.get("result") or {}
    pos = [p for p in (res.get("positions") or []) if p.get("symbol") == symbol]
    size = abs(float(pos[0].get("qty") or pos[0].get("size") or 0)) if pos else 0.0
    reducing = "sell" if direction == "long" else "buy"
    legs = [o for o in (res.get("orders") or []) if o.get("symbol") == symbol and o.get("side") == reducing]
    return {"size": size,
            "stop_prices": [_f(o.get("stop_price")) for o in legs
                            if "stop" in str(o.get("order_type")) and _f(o.get("stop_price"))],
            "target_prices": [_f(o.get("limit_price")) for o in legs
                              if str(o.get("order_type")) == "limit" and _f(o.get("limit_price"))]}


def main() -> int:
    as_json = "--json" in sys.argv
    now = datetime.now(timezone.utc)
    op = diag("open_packages")
    bybit = {a["account_id"]: a for a in diag("bybit_open_orders")["accounts"]}
    ib = {a["account_id"]: a for a in diag("ib_open_orders")["accounts"]}
    alp = {a["account_id"]: a for a in diag("alpaca_open_orders")["accounts"]}
    ibpos = {a["account_id"]: a.get("positions") or [] for a in diag("exchange_positions")["accounts"]}
    hist = diag("position_path_history?limit=10000")
    atr_by_pkg = {}
    for r in sorted(hist.get("rows") or [], key=lambda r: str(r.get("bar_ts"))):
        if _f(r.get("atr")):
            atr_by_pkg[r["order_package_id"]] = _f(r["atr"])
    pkgs = {p["order_package_id"]: p for p in op["packages"]}
    cfg = lrd.load_config()
    rows, fired_by_pkg, cnl_by_pkg = [], {}, {}
    for t in op["open_trades"]:
        acct, sym, dirn, pid = t["account_id"], t["symbol"], t["direction"], t["order_package_id"]
        pkg = pkgs.get(pid)
        if pkg is None:
            continue
        if acct in bybit and bybit[acct].get("read_state") == "orders_read":
            venue, cov = "bybit", bybit_cov(bybit[acct], sym, dirn)
        elif acct in ib and ib[acct].get("read_state") == "orders_read":
            venue, cov = "ib", ib_cov(ib[acct], ibpos.get(acct, []), sym)
        elif acct in alp and alp[acct].get("read_state") == "orders_read":
            venue, cov = "alpaca", alpaca_cov(alp[acct], sym, dirn)
        else:
            venue, cov = None, None
        row = vps.build_snapshot_row(
            order_package_id=pid, account_id=acct, symbol=sym, direction=dirn, trade_id=t["id"],
            venue=venue, stop_prices=(cov or {}).get("stop_prices"),
            target_prices=(cov or {}).get("target_prices"), position_size=(cov or {}).get("size"),
            ref_sl=pkg["sl"], ref_tp=pkg["tp"],
            unreadable=None if cov is not None else "venue_read_unavailable", now=now)
        rows.append(row)
        meta = {}
        try:
            meta = json.loads(pkg.get("meta") or "{}")
        except ValueError:
            meta = {}
        snaps = [r for r in rows if r["order_package_id"] == pid]
        ctx = {"venue": {"state": "read", "snapshots": snaps, "pkg_sl": pkg["sl"], "pkg_tp": pkg["tp"],
                         "meta_atr": _f(meta.get("atr"))},
               "history": ([{"bar_ts": now.isoformat(), "atr": atr_by_pkg[pid]}] if pid in atr_by_pkg else [])}
        ev, cnl = lrd.venue_events({}, ctx, cfg, now)
        fired_by_pkg[pid] = [e[2] for e in ev]
        cnl_by_pkg[pid] = [c["reason"] for c in cnl]
    if as_json:
        print(json.dumps({"rows": rows, "fired": fired_by_pkg, "could_not_look": cnl_by_pkg}, indent=1))
        return 0
    print(f"dry read at {now.isoformat()}  open packages={len(pkgs)}  open trades={len(op['open_trades'])}  "
          f"snapshot rows={len(rows)}")
    hdr = f"{'package':<22}{'account':<16}{'symbol':<9}{'state':<15}{'venue_sl':>11}{'pkg_sl':>11}{'venue_tp':>11}{'pkg_tp':>11} nS nT  reason"
    print(hdr)
    for r in rows:
        pkg = pkgs[r["order_package_id"]]
        print(f"{r['order_package_id']:<22}{r['account_id']:<16}{str(r['symbol']):<9}{r['read_state']:<15}"
              f"{(r['venue_sl'] if r['venue_sl'] is not None else '-')!s:>11}{pkg['sl']:>11.6g}"
              f"{(r['venue_tp'] if r['venue_tp'] is not None else '-')!s:>11}{pkg['tp']:>11.6g}"
              f" {r['n_stop_legs']:>2} {r['n_target_legs']:>2}  {r['read_reason'] or ''}")
    print("\nvenue_sl_diverges would fire for:", {k: v for k, v in fired_by_pkg.items() if v} or "none")
    print("could_not_look:", {k: v for k, v in cnl_by_pkg.items() if v} or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
