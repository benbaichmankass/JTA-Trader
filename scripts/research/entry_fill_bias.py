#!/usr/bin/env python3
# wiring: manual-only - a measurement for row ENTRY-FILL-BIAS-30D, re-run by hand after ENTRY-FILL-WRITEBACK lands to confirm new rows carry the fill; no schedule by design
"""ENTRY-FILL-BIAS-30D: planned entry (journal ``entry_price``) vs the venue's entry fill, per account.

Why: the journal's ``entry_price`` is the PACKAGE's planned entry, not the fill (row ENTRY-FILL-WRITEBACK; 2026-11-14
evidence: SOL 73.85 planned vs 73.60 / 73.58 filled, XRP 0.9715 vs 0.9707; 7224's venue closed_pnl reproduces to the
cent only with the fill). This measures how far apart they are over the last N days of live closes, so we know which
R figures are distorted before the write-back changes anything.

Venue entry fill, per venue (read-only diag routes):
  * Bybit: ``/api/diag/bybit_raw_closed_pnl`` -> record ``avg_entry_price``, matched to the trade by the closing order
    id (``tp_order_id`` / ``sl_order_id``) first, else side + qty + close time. On a symbol where the account held
    OVERLAPPING rows, the venue entry is the POSITION average, so those rows are reported separately (``overlap``).
  * Alpaca: ``/api/diag/alpaca_order_history?order_ids=<broker_order_id>`` -> ``filled_avg_price``.
  * Anything else (IB, prop): ``could_not_look``, counted, never dropped.

Bias in R = (fill - plan) x side / initial risk. Initial risk = the package's declared ``risk_per_unit``
(``r_provenance.declared_initial_risk``), else |plan - stop_loss| from the trade row (labelled; the stored stop may
have trailed). r_bias > 0 means a long filled ABOVE its plan or a short filled BELOW it: an adverse fill, so R computed
from the plan overstates the realised R by that much.

Usage: python3 scripts/research/entry_fill_bias.py --days 30 --out comms/research/entry_fill_bias/<date>.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

DAY_MS = 86_400_000
WINDOW_MS = 7 * DAY_MS - 60_000          # Bybit closed-pnl window cap is 7 days
QTY_TOL = 0.02                           # 2% qty tolerance for the fallback match
CLOSE_TOL_MS = 15 * 60_000               # fallback: venue close within 15 min of the journal close


def _diag(path: str) -> Any:
    out = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), path], capture_output=True, text=True, timeout=240)
    if out.returncode != 0:
        raise RuntimeError(f"diag {path}: exit {out.returncode} ({out.stderr.strip()[-200:]})")
    doc, _ = json.JSONDecoder().raw_decode(out.stdout.lstrip())
    return doc


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _ms(v: Any) -> Optional[int]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def _side(direction: Any) -> Optional[int]:
    d = str(direction or "").lower()
    return 1 if d in ("long", "buy") else -1 if d in ("short", "sell") else None


def _pct(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


# ----------------------------------------------------------------------------- reads
def read_journal(diag: Callable[[str], Any], table: str, pages: int, limit: int = 1000) -> List[dict]:
    rows: List[dict] = []
    for i in range(pages):
        page = diag(f"/api/diag/journal?table={table}&limit={limit}&offset={i * limit}")
        if not page:
            break
        rows.extend(page)
        if len(page) < limit:
            break
    return rows


def overlap_ids(trades: List[dict]) -> set:
    """Ids of rows whose life overlapped another row on the same account + symbol (venue entry = position average)."""
    by: Dict[Tuple[str, str], List[Tuple[int, int, int]]] = defaultdict(list)
    for t in trades:
        o, c = _ms(t.get("timestamp")), _ms(t.get("closed_at")) or 10 ** 15
        if o is not None:
            by[(t.get("account_id"), t.get("symbol"))].append((o, c, t["id"]))
    out = set()
    for spans in by.values():
        spans.sort()
        for i, (o1, c1, id1) in enumerate(spans):
            for o2, c2, id2 in spans[i + 1:]:
                if o2 >= c1:
                    break
                out.update((id1, id2))
    return out


def bybit_fills(rows: List[dict], diag: Callable[[str], Any]) -> Dict[int, dict]:
    """{trade id: {fill, basis, match}} for closed Bybit rows; read in <=7d windows per (account, symbol)."""
    out: Dict[int, dict] = {}
    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["account_id"], r["symbol"])].append(r)
    for (acct, sym), rs in groups.items():
        rs.sort(key=lambda r: _ms(r.get("closed_at")) or 0)
        recs: List[dict] = []
        state = "rows_returned"
        i = 0
        while i < len(rs):
            start = (_ms(rs[i].get("closed_at")) or 0) - 60 * 60_000
            end = start + WINDOW_MS
            try:
                d = diag(f"/api/diag/bybit_raw_closed_pnl?account_id={acct}&symbol={sym}&start_ms={start}&end_ms={end}")
                res = d.get("result") or {}
                if res.get("query_state") == "could_not_look" or d.get("read_state") not in (None, "closed_pnl_read"):
                    state = "could_not_look"
                recs.extend(res.get("records") or [])
            except Exception as exc:  # noqa: BLE001  # allow-silent: the rows in this window are counted could_not_look
                state = f"could_not_look: {str(exc)[:80]}"
            while i < len(rs) and (_ms(rs[i].get("closed_at")) or 0) <= end - 60 * 60_000:
                i += 1
        by_oid = {str(x.get("order_id")): x for x in recs if x.get("order_id")}
        used: set = set()
        for r in rs:
            hit, how = None, None
            for k in ("tp_order_id", "sl_order_id"):
                oid = str(r.get(k) or "")
                if oid and oid in by_oid and oid not in used:
                    hit, how = by_oid[oid], f"order_id:{k}"
                    break
            if hit is None:
                side, qty, cms = _side(r.get("direction")), _f(r.get("position_size")), _ms(r.get("closed_at"))
                close_side = "Sell" if side == 1 else "Buy" if side == -1 else None
                for x in recs:
                    if str(x.get("order_id")) in used or x.get("side") != close_side:
                        continue
                    q, u = _f(x.get("qty")), _f(x.get("updated_time"))
                    if qty and q and abs(q - qty) / qty <= QTY_TOL and cms and u and abs(u - cms) <= CLOSE_TOL_MS:
                        hit, how = x, "side+qty+close_time"
                        break
            if hit is not None:
                used.add(str(hit.get("order_id")))
                out[r["id"]] = {"fill": _f(hit.get("avg_entry_price")), "match": how, "read_state": "measured"}
            else:
                out[r["id"]] = {"fill": None, "match": None,
                                "read_state": "could_not_look" if state != "rows_returned" else "unmatched"}
    return out


def alpaca_fills(rows: List[dict], diag: Callable[[str], Any]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    by_acct: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_acct[r["account_id"]].append(r)
    for acct, rs in by_acct.items():
        ids = [str(r.get("broker_order_id")) for r in rs if r.get("broker_order_id")]
        orders: Dict[str, dict] = {}
        not_found: set = set()
        for k in range(0, len(ids), 40):
            try:
                d = diag(f"/api/diag/alpaca_order_history?account_id={acct}&order_ids={','.join(ids[k:k + 40])}")
                # shape: result.by_id[<order id>] = {read_state: order_read, order: {..., filled_avg_price}}
                for oid, hit in ((d.get("result") or {}).get("by_id") or {}).items():
                    if (hit or {}).get("read_state") == "order_read" and hit.get("order"):
                        orders[str(oid)] = hit["order"]
                    elif (hit or {}).get("read_state") == "not_found":
                        not_found.add(str(oid))
            except Exception:  # noqa: BLE001  # allow-silent: rows without a read are counted could_not_look
                pass
        for r in rs:
            o = orders.get(str(r.get("broker_order_id")))
            fill = _f((o or {}).get("filled_avg_price"))
            state = ("measured" if fill is not None
                     else "unmatched" if str(r.get("broker_order_id")) in not_found else "could_not_look")
            out[r["id"]] = {"fill": fill, "match": "broker_order_id" if fill is not None else None, "read_state": state,
                            **({"reason": "venue_not_found"} if state == "unmatched" else {})}
    return out


# ----------------------------------------------------------------------------- measure
def measure(trades: List[dict], packages: Dict[str, dict], fills: Dict[int, dict], overlap: set) -> Dict[str, Any]:
    from src.runtime.r_provenance import declared_initial_risk
    per: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        a = t["account_id"]
        acc = per.setdefault(a, {"n_closed": 0, "n_measured": 0, "n_unmatched": 0, "n_could_not_look": 0,
                                 "risk_basis": defaultdict(int), "clean": [], "overlap": []})
        acc["n_closed"] += 1
        fz = fills.get(t["id"]) or {"read_state": "could_not_look"}
        if fz["read_state"] != "measured" or fz.get("fill") is None:
            acc["n_unmatched" if fz["read_state"] == "unmatched" else "n_could_not_look"] += 1
            continue
        plan, fill, side = _f(t.get("entry_price")), fz["fill"], _side(t.get("direction"))
        if not plan or side is None:
            acc["n_could_not_look"] += 1
            continue
        risk = declared_initial_risk((packages.get(t.get("order_package_id")) or {}).get("meta"))
        basis = "declared_initial_risk"
        if risk is None:
            sl = _f(t.get("stop_loss"))
            risk, basis = (abs(plan - sl), "trade_stop_loss") if sl is not None and abs(plan - sl) > 0 else (None, "none")
        acc["n_measured"] += 1
        acc["risk_basis"][basis] += 1
        acc["overlap" if t["id"] in overlap else "clean"].append({
            "id": t["id"], "bps": abs(fill - plan) / plan * 1e4,
            "r_bias": None if not risk else (fill - plan) * side / risk})
    out = {}
    for a, acc in sorted(per.items()):
        def stats(xs: List[dict]) -> Dict[str, Any]:
            bps = [x["bps"] for x in xs]
            rb = [x["r_bias"] for x in xs if x["r_bias"] is not None]
            return {"n": len(xs), "abs_bps_median": None if not bps else round(statistics.median(bps), 2),
                    "abs_bps_p90": None if not bps else round(_pct(bps, 0.9), 2),
                    "r_bias_n": len(rb), "r_bias_mean": None if not rb else round(statistics.fmean(rb), 4),
                    "r_bias_median": None if not rb else round(statistics.median(rb), 4),
                    "r_bias_p10": None if not rb else round(_pct(rb, 0.1), 4),
                    "r_bias_p90": None if not rb else round(_pct(rb, 0.9), 4),
                    "abs_r_bias_over_0p05": sum(1 for x in rb if abs(x) > 0.05)}
        out[a] = {"n_closed": acc["n_closed"], "n_measured": acc["n_measured"], "n_unmatched": acc["n_unmatched"],
                  "n_could_not_look": acc["n_could_not_look"], "risk_basis": dict(acc["risk_basis"]),
                  "clean": stats(acc["clean"]), "overlap": stats(acc["overlap"])}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--pages", type=int, default=3, help="journal pages of 1000 rows to read (newest first)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=a.days)).isoformat()
    trades_all = read_journal(_diag, "trades", a.pages)
    pkgs = {p["order_package_id"]: p for p in read_journal(_diag, "order_packages", a.pages)}
    since_ms = _ms(since)
    closed = [t for t in trades_all if t.get("status") == "closed" and not t.get("is_backtest")
              and (_ms(t.get("closed_at")) or 0) >= since_ms]
    oldest_read = min((t.get("timestamp") or "") for t in trades_all) if trades_all else None
    by_venue: Dict[str, List[dict]] = defaultdict(list)
    for t in closed:
        acct = str(t.get("account_id") or "")
        by_venue["bybit" if acct.startswith("bybit") else "alpaca" if acct.startswith("alpaca") else "other"].append(t)
    fills: Dict[int, dict] = {}
    fills.update(bybit_fills(by_venue["bybit"], _diag))
    fills.update(alpaca_fills(by_venue["alpaca"], _diag))
    for t in by_venue["other"]:
        fills[t["id"]] = {"fill": None, "match": None, "read_state": "could_not_look"}
    result = measure(closed, pkgs, fills, overlap_ids(trades_all))
    record = {
        "schema": "entry_fill_bias/v1", "row": "ENTRY-FILL-BIAS-30D", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "produced_by": "python3 scripts/research/entry_fill_bias.py",
        "population": {"window": f"closed_at >= {since[:19]}Z (last {a.days}d)", "filter": "status closed, not backtest",
                       "n_closed": len(closed), "journal_rows_read": len(trades_all),
                       "oldest_row_read": oldest_read,
                       "note": "rows opened before oldest_row_read and closed in the window are not in this read"},
        "definition": {"plan": "trades.entry_price", "fill": "Bybit closed-pnl avg_entry_price / Alpaca filled_avg_price",
                       "r_bias": "(fill - plan) x side / initial risk; > 0 = adverse fill (R computed from the plan is overstated)",
                       "overlap": "row overlapped another row on the same account+symbol: the venue entry is the position average"},
        "accounts": result,
        "match_methods": dict(sorted(((m, sum(1 for f in fills.values() if f.get("match") == m))
                                      for m in {f.get("match") for f in fills.values()}), key=lambda kv: str(kv[0]))),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(record, indent=1, sort_keys=False, default=str) + "\n")
    print(json.dumps({k: {kk: v[kk] for kk in ("n_closed", "n_measured", "n_unmatched", "n_could_not_look")}
                      for k, v in result.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
