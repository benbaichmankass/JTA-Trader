#!/usr/bin/env python3
"""Fractional-order probe, PAPER ACCOUNTS ONLY (Alpaca paper here; IB paper in ib_fractional_probe.py).

Records every request and response to stdout (the workflow log is the only record; nothing is committed).
Refuses to run unless the base URL is the paper host. Sizes are tiny (default 0.5 share of SH) and everything
is cancelled / flattened in the `finally` block.

Phases:  assets  - GET /v2/assets/<SYM> for the candidate set (read-only)
         open    - tests (a) fractional day market bracket, (b) separate fractional day stop + limit TP, OCO attempt
         premarket - test (c) a fractional DAY stop placed while the market is closed (needs an open SH position
                     or buys 0.5 SH with an extended-hours limit when closed)
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.error

BASE = "https://paper-api.alpaca.markets"
DATA = "https://data.alpaca.markets"
SYMS = "SQQQ SPXU SPXS SDOW TZA SH PSQ TQQQ UPRO SPXL SSO UDOW TNA QLD".split()
SYM = os.environ.get("PROBE_SYMBOL", "SH")
QTY = os.environ.get("PROBE_QTY", "0.5")
K, S = os.environ.get("ALPACA_API_KEY_ID", ""), os.environ.get("ALPACA_API_SECRET_KEY", "")

def call(method, url, body=None):
    assert url.startswith(BASE) or url.startswith(DATA), "refusing non-paper/non-data host"
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
    print(json.dumps({"req": [method, url.replace(BASE, ""), body], "http": code, "resp": out}, default=str)[:1800])
    return code, out

def last_price():
    c, o = call("GET", f"{DATA}/v2/stocks/{SYM}/trades/latest?feed=iex")
    return float(o["trade"]["p"]) if c == 200 and o and o.get("trade") else None

def cleanup():
    call("DELETE", f"{BASE}/v2/orders")
    call("DELETE", f"{BASE}/v2/positions/{SYM}")

def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "assets"
    if not K or not S:
        sys.exit("paper keys missing")
    acct = call("GET", f"{BASE}/v2/account")[1] or {}
    print("paper account status:", acct.get("status"), "(trading_blocked=%s)" % acct.get("trading_blocked"))
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
    try:
        if phase == "open":
            if px is None:
                sys.exit("no price")
            tp, sl = round(px * 1.03, 2), round(px * 0.97, 2)
            print("== (a) fractional DAY market bracket ==")
            c, o = call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "market", "time_in_force": "day",
                        "order_class": "bracket", "take_profit": {"limit_price": f"{tp:.2f}"}, "stop_loss": {"stop_price": f"{sl:.2f}"}})
            if c in (200, 201):
                time.sleep(3)
                call("GET", f"{BASE}/v2/orders/{o['id']}?nested=true")
                call("GET", f"{BASE}/v2/positions/{SYM}")
            else:
                print("== (b) separate legs after a fractional DAY market entry ==")
                cleanup()
                c2, o2 = call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "market", "time_in_force": "day"})
                time.sleep(3)
                call("GET", f"{BASE}/v2/positions/{SYM}")
                print("-- (b1) fractional DAY stop sell")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "stop", "stop_price": f"{sl:.2f}", "time_in_force": "day"})
                print("-- (b2) fractional DAY limit TP sell")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "limit", "limit_price": f"{tp:.2f}", "time_in_force": "day"})
                print("-- (b3) fractional OCO (DAY) of TP + stop")
                cleanup_orders = call("DELETE", f"{BASE}/v2/orders")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "limit", "time_in_force": "day",
                      "order_class": "oco", "take_profit": {"limit_price": f"{tp:.2f}"}, "stop_loss": {"stop_price": f"{sl:.2f}"}})
        elif phase == "premarket":
            print("== (c) fractional DAY stop while the market is closed ==")
            pos = call("GET", f"{BASE}/v2/positions/{SYM}")
            if pos[0] != 200 and px:
                print("no open position; buying", QTY, "with an extended-hours DAY limit (fractional)")
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "buy", "type": "limit", "limit_price": f"{round(px*1.01,2):.2f}",
                      "time_in_force": "day", "extended_hours": True})
                time.sleep(5)
            if px:
                call("POST", f"{BASE}/v2/orders", {"symbol": SYM, "qty": QTY, "side": "sell", "type": "stop", "stop_price": f"{round(px*0.97,2):.2f}", "time_in_force": "day"})
                time.sleep(2)
                call("GET", f"{BASE}/v2/orders?status=open")
    finally:
        print("== cleanup ==")
        cleanup()

main()
