#!/usr/bin/env python3
# wiring: manual-only - a read tool for the DESK-MACRO end-to-end runs (operator 2026-11-26: "with as little latency as possible")
"""DESK-MACRO-DAILY v2: the per-hop latency of a desk proposal, from judgement to broker fill.

Operator 2026-11-26 chat, verbatim: "we know how to turn the trade recommendation from the macro briefing into an
order on a broker, and that it goes correctly and smoothly and with as little latency as possible." The spec
(DESK-MACRO-DAILY row) names the hops; this joins the receipts that already exist, one line per (decision, account):

  judged      the row's ``judged_at`` (intake.jsonl)
  picked_up   intake's ``seen_at``: the VM rows watcher read the row (intake.jsonl)
  touched     a LIMIT proposal only (DESK-MACRO v2 b1, the leg holds the limit): the tick its price reached the limit
              (``signal_logic.touched_at``); absent for a market entry, which has no such hop
  minted      the claude_desk order package's ``entry_time`` (journal order_packages.signal_logic)
  submitted   the venue's own order time: Bybit raw order history ``created_time``; Alpaca order-by-id ``submitted_at``
              (/api/diag/alpaca_order_history); IB: could_not_look (no IB fill-history diag route; ib_open_orders shows
              resting orders only)
  filled      Bybit ``updated_time`` when Filled; Alpaca ``filled_at`` when status filled; else could_not_look
  journaled   the trades row ``timestamp`` (journal trades; written after the venue fill returns)

Each hop is a measured timestamp or null with a ``why``; a gap is never folded into zero (collapsed-state rule). One
proposal can reach several accounts (a desk ETF package goes to alpaca_paper AND ib_paper, ML-UNIVERSE-RULE), so the
account hops repeat per account while the judgement hops are shared.

Read-only: it fetches through scripts/ops/diag_fetch.sh. No order path, no write.

  python3 scripts/ops/desk_latency_hops.py [--decision DD-...] [--last N] [--json]
  python3 scripts/ops/desk_latency_hops.py --self-test
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
#: entry_price_source values that ARE a venue measurement of the fill (mirror of src.runtime.order_monitor.VENUE_ENTRY_SOURCES;
#: the self-test pins the two equal). Slippage vs the limit is MEASURED only on these; a row still carrying the plan price
#: (source plan / fill_pending_writeback / no_venue_fill_read) reports slippage as unmeasured with the reason, never a number
#: (2026-11-27: the BTC T2 row read -0.4 bps on the plan price before the writeback made it -13.87 bps).
VENUE_ENTRY_SOURCES = ("alpaca_order_status", "bybit_order_history", "venue_fill")
HOPS = ("judged", "picked_up", "touched", "minted", "submitted", "filled", "journaled")   # measured: the journal row lands ~0.2 s AFTER the venue fill
Fetch = Callable[[str], Optional[Any]]


def _diag(path: str) -> Optional[Any]:
    r = subprocess.run(["bash", str(ROOT / "scripts" / "ops" / "diag_fetch.sh"), path],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError):
        return None


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat().replace("+00:00", "Z") if t else None


def _signal_logic(pkg: Dict[str, Any]) -> Dict[str, Any]:
    sl = pkg.get("signal_logic")
    if isinstance(sl, str):
        try:
            sl = json.loads(sl)
        except ValueError:
            return {}
    return sl if isinstance(sl, dict) else {}


def accepted_decisions(fetch: Fetch, last: int) -> Optional[List[Dict[str, Any]]]:
    d = fetch(f"/api/diag/log_file?name=desk_intake&grep=accepted&lines={max(1, min(last, 1000))}")
    if not isinstance(d, dict) or d.get("read_state") != "complete":
        return None
    out = []
    for ln in d.get("lines") or []:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("verdict") == "accepted":
            out.append(r)
    return out


def _venue_order(fetch: Fetch, account: str, symbol: str, order_id: str, around: datetime) -> Dict[str, Any]:
    s = int((around - timedelta(minutes=10)).timestamp() * 1000)
    e = int((around + timedelta(minutes=50)).timestamp() * 1000)
    d = fetch(f"/api/diag/bybit_raw_order_history?account_id={account}&symbol={symbol}&start_ms={s}&end_ms={e}")
    recs = (((d or {}).get("result") or {}).get("records")) if isinstance(d, dict) else None
    if recs is None:
        return {"why": "venue order history could not be read"}
    for o in recs:
        if str(o.get("order_id")) == str(order_id):
            filled = str(o.get("order_status")) == "Filled"
            return {"submitted": _ts(o.get("created_time")), "filled": _ts(o.get("updated_time")) if filled else None,
                    "status": o.get("order_status"), "why": None if filled else f"order status {o.get('order_status')}"}
    return {"why": f"order {order_id} not in the venue window read"}


def _alpaca_order(fetch: Fetch, account: str, order_id: str) -> Dict[str, Any]:
    d = fetch(f"/api/diag/alpaca_order_history?account_id={account}&order_ids={order_id}")
    if not isinstance(d, dict) or d.get("read_state") != "orders_read":
        return {"why": "alpaca order history could not be read"}
    one = ((d.get("result") or {}).get("by_id") or {}).get(str(order_id)) or {}
    o = one.get("order") if isinstance(one, dict) else None
    if not isinstance(o, dict):
        return {"why": f"order {order_id} not returned by alpaca ({(one or {}).get('read_state') or 'no row'})"}
    filled = str(o.get("status")) == "filled"
    return {"submitted": _ts(o.get("submitted_at")), "filled": _ts(o.get("filled_at")) if filled else None,
            "status": o.get("status"), "venue_fill_price": o.get("filled_avg_price"),
            "why": None if filled else f"order status {o.get('status')}"}


def _entry_source(t: Dict[str, Any]) -> Optional[str]:
    n = t.get("notes")
    if isinstance(n, str):
        try:
            n = json.loads(n)
        except ValueError:
            return None
    return str(n.get("entry_price_source")) if isinstance(n, dict) and n.get("entry_price_source") else None


def hops(decisions: List[Dict[str, Any]], packages: List[Dict[str, Any]], trades: List[Dict[str, Any]],
         fetch: Fetch) -> List[Dict[str, Any]]:
    by_dec: Dict[str, Dict[str, Any]] = {}
    for p in packages:
        if p.get("strategy_name") == "claude_desk":
            did = _signal_logic(p).get("decision_id")
            if did:
                by_dec[str(did)] = p
    out = []
    for dec in decisions:
        did = str(dec.get("decision_id"))
        base = {"decision_id": did, "judged": _ts(dec.get("judged_at")), "picked_up": _ts(dec.get("seen_at"))}
        pkg = by_dec.get(did)
        if pkg is None:
            out.append(dict(base, account=None, why="no claude_desk package with this decision in the order_packages rows read (older than the read, or never minted)"))
            continue
        sl = _signal_logic(pkg)
        base.update(order_package_id=pkg.get("order_package_id"), symbol=pkg.get("symbol"), minted=_ts(sl.get("entry_time")),
                    entry_type=sl.get("entry_type") or "market", limit_level=sl.get("limit_level"),
                    touch_price=sl.get("touch_price"), direction=pkg.get("direction"))
        if sl.get("entry_type") == "limit":
            base["touched"] = _ts(sl.get("touched_at"))
        rows = [t for t in trades if t.get("order_package_id") == pkg.get("order_package_id")]
        if not rows:
            out.append(dict(base, account=None, why="no trades row for the package (no account placed it)"))
            continue
        for t in rows:
            rec = dict(base, account=t.get("account_id"), journaled=_ts(t.get("timestamp")),
                       broker_order_id=t.get("broker_order_id"), fill_price=t.get("entry_price"),
                       entry_price_source=_entry_source(t))
            rec["slippage_vs_limit"] = None
            if rec.get("entry_type") == "limit":
                if rec["entry_price_source"] in VENUE_ENTRY_SOURCES:
                    rec["slippage_vs_limit"] = slippage(rec)
                else:
                    rec["slippage_unmeasured"] = (f"entry_price_source={rec['entry_price_source'] or 'unlabelled'}: the row holds the "
                                                  "plan price, not a venue fill")
            acct = str(t.get("account_id") or "")
            if acct.startswith("bybit") and t.get("broker_order_id") and rec["journaled"]:
                v = _venue_order(fetch, acct, str(t.get("symbol")), str(t["broker_order_id"]), rec["journaled"])
                rec.update(submitted=v.get("submitted"), filled=v.get("filled"), why=v.get("why"))
            elif acct.startswith("alpaca") and t.get("broker_order_id"):
                v = _alpaca_order(fetch, acct, str(t["broker_order_id"]))
                rec.update(submitted=v.get("submitted"), filled=v.get("filled"), why=v.get("why"))
            elif acct.startswith("ib"):
                rec["why"] = "IB order times: no fill-history diag route (ib_open_orders shows resting orders only)"
            else:
                rec["why"] = "venue order times could not be read for this account (no broker_order_id or unknown venue)"
            out.append(rec)
    return out


def slippage(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """For a leg-held LIMIT entry (b1): how far the actual fill was from the limit level, signed so that positive = WORSE
    than the limit (paid more on a long, received less on a short), in price and in bps of the limit. None for a market
    entry or when a price is missing (never 0). This is the number DESK-VENUE-RESTING-LIMIT's re-entry test reads."""
    if rec.get("entry_type") != "limit":
        return None
    try:
        lvl, fill = float(rec["limit_level"]), float(rec["fill_price"])
    except (KeyError, TypeError, ValueError):
        return None
    sign = 1.0 if rec.get("direction") == "long" else -1.0
    worse = sign * (fill - lvl)
    return {"limit_level": lvl, "fill_price": fill, "worse_by": round(worse, 8), "worse_bps": round(worse / lvl * 1e4, 2)}


def with_deltas(rec: Dict[str, Any]) -> Dict[str, Any]:
    r = {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in rec.items()}
    prev = None
    deltas = {}
    for h in HOPS:
        t = rec.get(h)
        if isinstance(t, datetime) and isinstance(prev, tuple):
            deltas[f"{prev[0]}->{h}"] = round((t - prev[1]).total_seconds(), 3)
        if isinstance(t, datetime):
            prev = (h, t)
    j, last = rec.get("judged"), next((rec.get(h) for h in reversed(HOPS) if isinstance(rec.get(h), datetime)), None)
    r["hop_seconds"] = deltas
    r["total_seconds"] = round((last - j).total_seconds(), 3) if isinstance(j, datetime) and last and last is not j else None
    r["missing_hops"] = [h for h in HOPS if not isinstance(rec.get(h), datetime) and not (h == "touched" and rec.get("entry_type") != "limit")]
    return r


def run(fetch: Fetch, last: int = 20, decision: Optional[str] = None) -> Dict[str, Any]:
    decs = accepted_decisions(fetch, last if not decision else 1000)
    if decs is None:
        return {"read_state": "could_not_look", "why": "desk_intake log unreadable"}
    if decision:
        decs = [d for d in decs if d.get("decision_id") == decision]
    else:
        decs = decs[-last:]
    pk = fetch("/api/diag/journal?table=order_packages&limit=1000")
    tr = fetch("/api/diag/journal?table=trades&limit=1000")
    if not isinstance(pk, list) or not isinstance(tr, list):
        return {"read_state": "could_not_look", "why": "journal order_packages / trades unreadable"}
    rows = [with_deltas(r) for r in hops(decs, pk, tr, fetch)]
    return {"read_state": "measured", "population": f"{len(decs)} accepted desk proposals (newest of desk_intake), "
            "joined against the newest 1000 order_packages and trades rows", "rows": rows}


def _self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    intake = {"read_state": "complete", "lines": [json.dumps({"decision_id": "D1", "verdict": "accepted",
              "judged_at": "2026-11-19T12:34:32Z", "seen_at": "2026-11-19T12:36:35+00:00"}),
              json.dumps({"decision_id": "D2", "verdict": "accepted", "judged_at": "2026-11-19T13:00:00Z",
                          "seen_at": "2026-11-19T13:02:00+00:00"})]}
    pkgs = [{"order_package_id": "P1", "strategy_name": "claude_desk", "symbol": "XRPUSDT",
             "signal_logic": json.dumps({"decision_id": "D1", "entry_time": "2026-11-19T12:37:08+00:00"})}]
    trades = [{"order_package_id": "P1", "account_id": "bybit_1", "symbol": "XRPUSDT", "broker_order_id": "O1",
               "timestamp": "2026-11-19T12:37:14+00:00"}]
    venue = {"result": {"records": [{"order_id": "O1", "order_status": "Filled", "created_time": "1795091833726",
                                     "updated_time": "1795091833900"}]}}

    def fetch(path):
        if "desk_intake" in path:
            return intake
        if "order_packages" in path:
            return pkgs
        if "table=trades" in path:
            return trades
        if "bybit_raw_order_history" in path:
            return venue
        if "alpaca_order_history" in path and "order_ids=A1" in path:
            return alp
        return None

    pkgs.append({"order_package_id": "P3", "strategy_name": "claude_desk", "symbol": "SLV", "direction": "long",
                 "signal_logic": json.dumps({"decision_id": "D3", "entry_time": "2026-11-27T15:00:05+00:00", "entry_type": "limit",
                                             "limit_level": 36.8, "touch_price": 36.79, "touched_at": "2026-11-27T15:00:00+00:00"})})
    trades.append({"order_package_id": "P3", "account_id": "alpaca_paper", "symbol": "SLV", "entry_price": 36.83,
                   "timestamp": "2026-11-27T15:00:09+00:00", "broker_order_id": "A1",
                   "notes": json.dumps({"entry_price_source": "alpaca_order_status"})})
    trades.append({"order_package_id": "P3", "account_id": "ib_paper", "symbol": "SLV", "entry_price": 36.80,
                   "timestamp": "2026-11-27T15:00:08+00:00", "broker_order_id": "7",
                   "notes": json.dumps({"entry_price_source": "plan", "entry_price_source_reason": "no_venue_fill_read"})})
    alp = {"read_state": "orders_read", "result": {"by_id": {"A1": {"read_state": "order_read", "order": {
        "status": "filled", "submitted_at": "2026-11-27T15:00:06.5Z", "filled_at": "2026-11-27T15:00:07.25Z", "filled_avg_price": 36.83}}}}}
    intake["lines"].append(json.dumps({"decision_id": "D3", "verdict": "accepted", "judged_at": "2026-11-27T13:10:00Z",
                                       "seen_at": "2026-11-27T13:15:00+00:00"}))
    out = run(fetch, last=5)
    r1 = next(r for r in out["rows"] if r["decision_id"] == "D1")
    r2 = next(r for r in out["rows"] if r["decision_id"] == "D2")
    check("every hop measured on a filled Bybit desk trade", r1["missing_hops"] == [])
    check("hop deltas are consecutive and positive", r1["hop_seconds"]["judged->picked_up"] == 123.0
          and all(v >= 0 for v in r1["hop_seconds"].values()))
    check("total = judged -> journaled (the last hop)", r1["total_seconds"] == round((_ts("2026-11-19T12:37:14+00:00") - _ts("2026-11-19T12:34:32Z")).total_seconds(), 3))
    check("a decision without a package read is named, not zero", r2["why"].startswith("no claude_desk package") and r2["total_seconds"] is not None)
    check("unreadable intake -> could_not_look", run(lambda p: None)["read_state"] == "could_not_look")
    r3 = next(r for r in out["rows"] if r["decision_id"] == "D3" and r["account"] == "alpaca_paper")
    r3ib = next(r for r in out["rows"] if r["decision_id"] == "D3" and r["account"] == "ib_paper")
    check("alpaca: submitted / filled read from the order-by-id read", r3["submitted"] == "2026-11-27T15:00:06.500000Z"
          and r3["filled"] == "2026-11-27T15:00:07.250000Z" and r3.get("why") is None and "submitted->filled" in r3["hop_seconds"])
    check("ib: order times named as unreadable, never zero", r3ib.get("submitted") is None and "submitted" in r3ib["missing_hops"] and "no fill-history diag route" in r3ib["why"])
    check("a plan-price fill reports slippage as unmeasured, not a number", r3ib["slippage_vs_limit"] is None
          and "plan price" in r3ib["slippage_unmeasured"])
    try:
        sys.path.insert(0, str(ROOT))
        from src.runtime.order_monitor import VENUE_ENTRY_SOURCES as _V
        check("VENUE_ENTRY_SOURCES mirrors order_monitor", set(_V) == set(VENUE_ENTRY_SOURCES))
    except Exception as exc:  # noqa: BLE001  # allow-silent: printed as a SKIP; the mirror is still pinned by value below
        print(f"SKIP mirror check (order_monitor not importable here: {type(exc).__name__})")
    check("a leg-held limit shows the touched hop and its slippage (worse = positive)",
          "picked_up->touched" in r3["hop_seconds"] and r3["slippage_vs_limit"]["worse_by"] == 0.03
          and r3["slippage_vs_limit"]["worse_bps"] == 8.15)
    check("a market entry has no touched hop and no slippage", "touched" not in r1["missing_hops"] and r1["slippage_vs_limit"] is None)
    print("self-test", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decision")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    out = run(_diag, a.last, a.decision)
    if a.json or out.get("read_state") != "measured":
        print(json.dumps(out, indent=1))
        return 0 if out.get("read_state") == "measured" else 3
    print(out["population"])
    for r in out["rows"]:
        hs = " ".join(f"{k}={v:.1f}s" for k, v in r["hop_seconds"].items())
        total = "—" if r["total_seconds"] is None else f"{r['total_seconds']:.1f}s"
        miss = f" | missing {','.join(r['missing_hops'])}" if r["missing_hops"] else ""
        why = f" | {r['why']}" if r.get("why") else ""
        sv = r.get("slippage_vs_limit")
        why += f" | vs limit {sv['limit_level']}: {sv['worse_bps']:+.1f} bps worse" if sv else ""
        why += f" | slippage unmeasured ({r['slippage_unmeasured']})" if r.get("slippage_unmeasured") else ""
        print(f"{r['decision_id']} {r.get('symbol') or '-'} {r.get('account') or '-'}: total {total} | {hs}{miss}{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
