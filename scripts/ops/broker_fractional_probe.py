#!/usr/bin/env python3
"""Fractional-order probe, PAPER ACCOUNTS ONLY (Alpaca paper here; IB paper in ib_fractional_probe.py).

Records every request and response to stdout (the workflow log is the only record; nothing is committed).
Refuses to run unless the base URL is the paper host. Sizes are tiny (default 0.5 share of SH) and everything
is cancelled / flattened in the `finally` block.

Cleanup cancels ONLY order ids this probe created and closes ONLY its own quantity (the paper account also runs the bot).
Phases:  assets  - GET /v2/assets/<SYM> for the candidate set (read-only)
         open    - tests (a) fractional day market bracket, (b) separate fractional day stop + limit TP, OCO attempt
         premarket - test (c) a fractional DAY stop placed while the market is closed (needs an open SH position
                     or buys 0.5 SH with an extended-hours limit when closed)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
SYMS = ["SQQQ", "SPXU", "SPXS", "SDOW", "TZA", "SH", "PSQ", "TQQQ", "UPRO", "SPXL", "SSO", "UDOW", "TNA", "QLD"]
SYM = os.environ.get("PROBE_SYMBOL", "SH")
QTY = os.environ.get("PROBE_QTY", "0.5")
K, S = os.environ.get("ALPACA_API_KEY_ID", ""), os.environ.get("ALPACA_API_SECRET_KEY", "")

# The job log of a public repo is public: log only these response fields (never account ids, balances or raw payloads).
ALLOW = {"symbol", "side", "type", "time_in_force", "order_class", "qty", "filled_qty", "status", "code", "message",
         "tradable", "fractionable", "shortable", "easy_to_borrow", "legs", "stop_price", "limit_price", "extended_hours",
         "trading_blocked", "is_open", "next_open", "p"}


def _allow(o):
    if isinstance(o, list):
        return [_allow(x) for x in o]
    if isinstance(o, dict):
        return {k: _allow(v) for k, v in o.items() if k in ALLOW}
    return o


OWN_POSITION = [False]  # True once this probe opened the position it may close
MINE = []  # order ids this probe created: the ONLY orders it may cancel (the paper account also runs the bot)


def call(method, url, body=None, quiet=False):
    assert url.startswith((BASE, DATA)), "refusing non-paper/non-data host"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"APCA-API-KEY-ID": K, "APCA-API-SECRET-KEY": S, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, txt = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, txt = e.code, e.read().decode()
    try:
        out = json.loads(txt) if txt else None
    except ValueError:
        out = txt[:300]
    shown = "<redacted>" if quiet else _allow(out)
    print(json.dumps({"req": [method, url.replace(BASE, ""), body], "http": code, "resp": shown}, default=str)[:1800])
    if method == "POST" and url.endswith("/v2/orders") and code in (200, 201) and isinstance(out, dict) and out.get("id"):
        MINE.append(out["id"])
    if method == "POST" and url.endswith("/v2/orders") and code in (200, 201) and isinstance(out, dict) and out.get("id"):
        MINE.append(out["id"])
    return code, out

def last_price():
    c, o = call("GET", f"{DATA}/v2/stocks/{SYM}/trades/latest?feed=iex")
    return float(o["trade"]["p"]) if c == 200 and o and o.get("trade") else None

def cancel_mine():
    for oid in list(MINE):
        call("DELETE", f"{BASE}/v2/orders/{oid}")


def cleanup():
    """Cancel ONLY this probe's own orders and close ONLY the quantity it opened. Never a bulk cancel/close:
    the paper account also runs the bot, and a bulk DELETE cancelled four of its orders on 2026-11-23."""
    cancel_mine()
    if OWN_POSITION[0]:
        call("DELETE", f"{BASE}/v2/positions/{SYM}?qty={QTY}")


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "assets"
    if not K or not S:
        sys.exit("paper keys missing")
    acct = call("GET", f"{BASE}/v2/account", quiet=True)[1] or {}
    print("paper account status:", acct.get("status"), f"(trading_blocked={acct.get('trading_blocked')})")
    if phase == "assets":
        for s in SYMS:
            c, o = call("GET", f"{BASE}/v2/assets/{s}")
            if c == 200 and isinstance(o, dict):
                print("ASSET", s, {k: o.get(k) for k in ("tradable", "fractionable", "shortable", "easy_to_borrow")})
        return
    clock = call("GET", f"{BASE}/v2/clock")[1] or {}
    print("market is_open:", clock.get("is_open"), "next_open:", clock.get("next_open"))
    px = last_price()
    print("last price", SYM, px)
    # Preflight: the paper account also runs the bot. Refuse if the probe symbol is already in use there.
    pre_pos = call("GET", f"{BASE}/v2/positions/{SYM}")[0]
    pre_orders = call("GET", f"{BASE}/v2/orders?status=open&symbols={SYM}")[1]
    if pre_pos == 200 or pre_orders:
        sys.exit(f"refusing: {SYM} already has a position or open orders on this account; pick another symbol")
    try:
        if phase == "open":
            if px is None:
                sys.exit("no price")
            tp, sl = round(px * 1.03, 2), round(px * 0.97, 2)
            print("== (a) fractional DAY market bracket ==")
            c, o = call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "market", "time_in_force": "day",
                        "order_class": "bracket", "take_profit": {"limit_price": f"{tp:.2f}"}, "stop_loss": {"stop_price": f"{sl:.2f}"}})
            if c in (200, 201):
                OWN_POSITION[0] = True
                time.sleep(3)
                call("GET", f"{BASE}/v2/orders/{o['id']}?nested=true")
                call("GET", f"{BASE}/v2/positions/{SYM}")
            else:
                print("== (b) separate legs after a fractional DAY market entry ==")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "market", "time_in_force": "day"})
                OWN_POSITION[0] = True
                time.sleep(3)
                call("GET", f"{BASE}/v2/positions/{SYM}")
                print("-- (b1) fractional DAY stop sell")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "stop", "stop_price": f"{sl:.2f}", "time_in_force": "day"})
                print("-- (b2) fractional DAY limit TP sell")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "limit", "limit_price": f"{tp:.2f}", "time_in_force": "day"})
                print("-- (b3) fractional OCO (DAY) of TP + stop")
                cancel_mine()
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "limit", "time_in_force": "day",
                      "order_class": "oco", "take_profit": {"limit_price": f"{tp:.2f}"}, "stop_loss": {"stop_price": f"{sl:.2f}"}})
        elif phase == "premarket":
            print("== (c) fractional DAY stop while the market is closed ==")
            pos = call("GET", f"{BASE}/v2/positions/{SYM}")
            if pos[0] != 200 and px:
                print("no open position; buying", QTY, "with an extended-hours DAY limit (fractional)")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "limit", "limit_price": f"{round(px*1.01,2):.2f}",
                      "time_in_force": "day", "extended_hours": True})
                OWN_POSITION[0] = True
                time.sleep(5)
            if px:
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "stop", "stop_price": f"{round(px*0.97,2):.2f}", "time_in_force": "day"})
                time.sleep(2)
                call("GET", f"{BASE}/v2/orders?status=open&symbols={SYM}")
    finally:
        print("== cleanup ==")
        cleanup()

main()
