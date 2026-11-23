#!/usr/bin/env python3
"""IB PAPER fractional-order probe through the path the trader uses (ib_insync -> IB Gateway socket, paper port 4002).

Runs on the live VM (which can reach the gateway VM over the private subnet). Refuses any port other than 4002 (paper).
Places ONE 0.5-share order of the symbol with an attached TP limit and stop (bracket); prints every result; cancels ONLY
the orders it placed and closes ONLY a position in the probe symbol that did not exist before it ran (preflight refuses
to run otherwise: the paper account also runs the bot). clientId 899 is used only here (trader uses 496/497).
"""
import sys

from ib_insync import IB, LimitOrder, MarketOrder, Stock, StopOrder

HOST, PORT, CID = (sys.argv[1] if len(sys.argv) > 1 else "10.0.0.251"), 4002, 899
SYM, QTY = (sys.argv[2] if len(sys.argv) > 2 else "SH"), 0.5
ib = IB()
ib.connect(HOST, PORT, clientId=CID, timeout=20)
print("connected; accounts:", len(ib.managedAccounts()), "server version:", ib.client.serverVersion())
# Preflight: refuse if the probe symbol already has a position or an open order from ANY client on this account.
ib.reqAllOpenOrders()
ib.sleep(2)
pre_pos = [p for p in ib.positions() if p.contract.symbol == SYM and p.position]
pre_orders = [t for t in ib.openTrades() if t.contract.symbol == SYM]
if pre_pos or pre_orders:
    print(f"refusing: {SYM} already has a position or open orders on this account")
    ib.disconnect()
    sys.exit(2)
MINE = []
try:
    c = Stock(SYM, "SMART", "USD")
    print("qualify:", ib.qualifyContracts(c))
    tk = ib.reqMktData(c, "", True, False)
    ib.sleep(3)
    px = tk.last or tk.close or tk.marketPrice()
    print("price", px)
    # 1) plain fractional market order
    t1 = ib.placeOrder(c, MarketOrder("BUY", QTY))
    MINE.append(t1)
    ib.sleep(4)
    print("1) fractional market:", t1.orderStatus.status, [e.message for e in t1.log][-3:])
    # 2) bracket: parent + TP + stop, fractional
    ids = ib.client.getReqId()
    parent = MarketOrder("BUY", QTY, orderId=ids, transmit=False)
    tp = LimitOrder("SELL", QTY, round(px * 1.03, 2), orderId=ids + 1, parentId=ids, transmit=False)
    sl = StopOrder("SELL", QTY, round(px * 0.97, 2), orderId=ids + 2, parentId=ids, transmit=True)
    trs = [ib.placeOrder(c, o) for o in (parent, tp, sl)]
    MINE.extend(trs)
    ib.sleep(5)
    print("2) bracket:", [(t.order.orderType, t.orderStatus.status, [e.message for e in t.log][-2:]) for t in trs])
    print("errors seen (see log above for ib_insync error lines)")
finally:
    for t in MINE:
        if not t.isDone():
            ib.cancelOrder(t.order)
    ib.sleep(2)
    for p in ib.positions():  # preflight guaranteed no pre-existing SYM position, so any SYM position here is the probe's own
        if p.contract.symbol == SYM and p.position:
            ib.placeOrder(p.contract, MarketOrder("SELL" if p.position > 0 else "BUY", abs(p.position)))
    ib.sleep(4)
    print("probe-symbol positions after cleanup:", [(p.contract.symbol, p.position) for p in ib.positions() if p.contract.symbol == SYM])
    ib.disconnect()
