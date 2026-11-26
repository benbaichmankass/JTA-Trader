#!/usr/bin/env python3
# wiring: manual-only - a read tool for the DESK-MACRO end-to-end runs (operator 2026-11-26: "with as little latency as possible")
"""DESK-MACRO-DAILY v2: the per-hop latency of a desk proposal, from judgement to broker fill.

Operator 2026-11-26 chat, verbatim: "we know how to turn the trade recommendation from the macro briefing into an
order on a broker, and that it goes correctly and smoothly and with as little latency as possible." The spec
(DESK-MACRO-DAILY row) names the hops; this joins the receipts that already exist, one line per (decision, account):

  judged      the row's ``judged_at`` (intake.jsonl)
  picked_up   intake's ``seen_at``: the VM rows watcher read the row (intake.jsonl)
  minted      the claude_desk order package's ``entry_time`` (journal order_packages.signal_logic)
  submitted   the venue's own order ``created_time`` (Bybit raw order history; other venues: could_not_look for now)
  filled      the venue order's ``updated_time`` when its status is Filled (Bybit), else could_not_look
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
HOPS = ("judged", "picked_up", "minted", "submitted", "filled", "journaled")   # measured: the journal row lands ~0.2 s AFTER the venue fill
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
        base.update(order_package_id=pkg.get("order_package_id"), symbol=pkg.get("symbol"), minted=_ts(sl.get("entry_time")))
        rows = [t for t in trades if t.get("order_package_id") == pkg.get("order_package_id")]
        if not rows:
            out.append(dict(base, account=None, why="no trades row for the package (no account placed it)"))
            continue
        for t in rows:
            rec = dict(base, account=t.get("account_id"), journaled=_ts(t.get("timestamp")),
                       broker_order_id=t.get("broker_order_id"))
            if str(t.get("account_id") or "").startswith("bybit") and t.get("broker_order_id") and rec["journaled"]:
                v = _venue_order(fetch, str(t["account_id"]), str(t.get("symbol")), str(t["broker_order_id"]), rec["journaled"])
                rec.update(submitted=v.get("submitted"), filled=v.get("filled"), why=v.get("why"))
            else:
                rec["why"] = "venue order times are read for Bybit accounts only so far"
            out.append(rec)
    return out


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
    r["missing_hops"] = [h for h in HOPS if not isinstance(rec.get(h), datetime)]
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
        return None

    out = run(fetch, last=5)
    r1 = next(r for r in out["rows"] if r["decision_id"] == "D1")
    r2 = next(r for r in out["rows"] if r["decision_id"] == "D2")
    check("every hop measured on a filled Bybit desk trade", r1["missing_hops"] == [])
    check("hop deltas are consecutive and positive", r1["hop_seconds"]["judged->picked_up"] == 123.0
          and all(v >= 0 for v in r1["hop_seconds"].values()))
    check("total = judged -> journaled (the last hop)", r1["total_seconds"] == round((_ts("2026-11-19T12:37:14+00:00") - _ts("2026-11-19T12:34:32Z")).total_seconds(), 3))
    check("a decision without a package read is named, not zero", r2["why"].startswith("no claude_desk package") and r2["total_seconds"] is not None)
    check("unreadable intake -> could_not_look", run(lambda p: None)["read_state"] == "could_not_look")
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
        print(f"{r['decision_id']} {r.get('symbol') or '-'} {r.get('account') or '-'}: total {total} | {hs}{miss}{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
