# wiring: manual-only - one-off replay behind comms/strategy_evidence/eth_same_symbol_h2h.json (PROMOTE-PROP-LEGS); rerun by hand from the repo root
"""Same-symbol head-to-head: trend_donchian_eth_4h vs trend_donchian_eth_prop on ETHUSDT.

Replays the two COMMITTED harness ledgers (full cost stack, per-trade net_r) over the
eth_prop evidence window, holding ONE position at a time (bybit_2 is one-way):
  (a) eth_4h alone, (b) eth_prop alone, (c) both sharing one slot.
Same-tick ties are ordered by the live election key (-confidence, then name).
Prints the arms as JSON, then the tie-order sensitivity of arm (c).
"""
import json
from collections import Counter
from datetime import datetime

PROP = "comms/strategy_evidence/runs/2026-10-07/trend_donchian_eth_prop__trades.jsonl"
H4 = "comms/strategy_evidence/runs/2026-10-12-1095d/trend_donchian_eth_4h__trades.jsonl"
LO = datetime.fromisoformat("2025-10-07 00:00:00+00:00")
HI = datetime.fromisoformat("2026-10-07 19:13:55+00:00")
DAYS = (HI - LO).total_seconds() / 86400


def load(path, leg):
    out = []
    with open(path) as fh:
        for line in fh:
            r = json.loads(line)
            r["leg"] = leg
            r["et"] = datetime.fromisoformat(r["entry_time"])
            r["xt"] = datetime.fromisoformat(r["exit_time"])
            if LO <= r["et"] <= HI:
                out.append(r)
    return out


def single_slot(trades, key):
    taken, busy_until = [], None
    for r in sorted(trades, key=key):
        if busy_until is not None and r["et"] < busy_until:
            continue
        taken.append(r)
        busy_until = r["xt"]
    return taken


def live_key(r):
    return (r["et"], -r.get("confidence", 0), r["leg"])


def stats(tr):
    net = sum(r["net_r"] for r in tr)
    pos_days = sum((r["xt"] - r["et"]).total_seconds() for r in tr) / 86400
    eq = pk = dd = 0.0
    for r in sorted(tr, key=lambda r: r["xt"]):
        eq += r["net_r"]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return {
        "n": len(tr),
        "net_r": round(net, 4),
        "net_r_per_capital_day": round(net / DAYS, 5),
        "net_r_per_position_day": round(net / pos_days, 4) if pos_days else None,
        "days_in_position": round(pos_days, 1),
        "max_dd_r": round(dd, 4),
        "by_leg": dict(sorted(Counter(r["leg"] for r in tr).items())),
    }


def main():
    a_raw = load(H4, "trend_donchian_eth_4h")
    b_raw = load(PROP, "trend_donchian_eth_prop")
    a, b = single_slot(a_raw, live_key), single_slot(b_raw, live_key)
    c = single_slot(a_raw + b_raw, live_key)
    res = {
        "window": [LO.isoformat(), HI.isoformat()],
        "window_days": round(DAYS, 2),
        "raw_overlap_check": {
            "eth_4h_ledger_n_in_window": len(a_raw),
            "eth_prop_ledger_n_in_window": len(b_raw),
            "eth_4h_self_overlaps_removed": len(a_raw) - len(a),
            "eth_prop_self_overlaps_removed": len(b_raw) - len(b),
        },
        "arm_a_eth_4h_alone": stats(a),
        "arm_b_eth_prop_alone": stats(b),
        "arm_c_both_one_slot": stats(c),
    }
    print(json.dumps(res, indent=1))
    same = Counter(r["et"] for r in a_raw) & Counter(r["et"] for r in b_raw)
    print("same_entry_tick_collisions", sum(same.values()))
    for first in ("trend_donchian_eth_prop", "trend_donchian_eth_4h"):
        arm = single_slot(a_raw + b_raw,
                          lambda r, f=first: (r["et"], 0 if r["leg"] == f else 1))
        print(first, "first on ties:", stats(arm)["net_r"])


if __name__ == "__main__":
    main()
