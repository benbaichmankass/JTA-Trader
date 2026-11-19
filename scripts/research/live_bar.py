#!/usr/bin/env python3
# wiring: manual-only - run by sessions for the promotion packet and the performance review; the scheduled ladder feed is row LIVE-BAR-LADDER-FEED.
"""The LIVE BAR check (operator, 2026-11-17; OPERATING-PLAN § 2 "Live-performance promotion path").

A leg clears the live bar with >= 20 closed live trades whose R is CONFIRMED, net of real costs (the journal's realized
pnl), total R > 0 AND the mean's one-sided ~80% lower confidence bound above zero:
``mean - 0.8416 * sd / sqrt(n) > 0``. Demo-floor and real-money trades of the same leg configuration POOL; the output says so
and splits them. Unconfirmed-R trades never count, and every number carries its n.

WHICH TRADES ARE "CONFIRMED" (measured 2026-11-18, AM-OPS-3). ``classify_r``'s ``confirmed_initial`` grade means the STORED
stop still equals the declared initial risk, i.e. the stop NEVER MOVED. Any trade that trailed or went to breakeven (mostly
winners) is graded ``unverified``, so that population is biased toward losses. The R that is trustworthy is the one whose
DENOMINATOR is the signal-time declared risk (``r_multiple_provenanced`` basis ``declared_initial``), which no trailing amend
can reach. The bar therefore counts basis ``declared_initial`` trades; the stop-never-moved subset is reported beside it
(``stop_unmoved``) so the bias is visible, never used as the bar. The venue-MEASURED-pnl subset (``classify_pnl``) is reported
too: a PASS whose measured subset is short or failing says the "net of real costs" half rests on estimated pnl.

Verdicts per leg: ``pass`` / ``fail`` / ``n_short`` (fewer than 20 confirmed) / ``no_data``.

    python3 scripts/research/live_bar.py                    # reads the live diag journal (needs diag access)
    python3 scripts/research/live_bar.py --trades t.json --packages p.json --json
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MIN_N = 20
Z80 = 0.8416  # one-sided 80%


def lcb80(xs: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return mu - Z80 * sd / math.sqrt(n)


def verdict(xs: List[float], min_n: int = MIN_N) -> Dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"verdict": "no_data", "n": 0, "sum_r": None, "mean_r": None, "lcb80": None}
    s = sum(xs)
    lb = lcb80(xs)
    out = {"n": n, "sum_r": round(s, 4), "mean_r": round(s / n, 4), "lcb80": (round(lb, 4) if lb is not None else None)}
    if n < min_n:
        return {"verdict": "n_short", **out}
    ok = s > 0 and lb is not None and lb > 0
    return {"verdict": "pass" if ok else "fail", **out}


def _meta(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def confirmed_r_rows(trades: Iterable[Mapping], packages: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Closed trades whose R denominator is the declared signal-time risk (basis ``declared_initial``), with that R (pure)."""
    from src.runtime.local_pnl import contract_value_usd_for
    from src.runtime.provenance import MEASURED, classify_pnl
    from src.runtime.r_provenance import R_BASIS_DECLARED, R_CONFIRMED_INITIAL, classify_r, r_multiple_provenanced
    out = []
    for t in trades:
        if str(t.get("status") or "").lower() != "closed" or t.get("pnl") is None:
            continue
        row = {"pnl": t.get("pnl"), "entry_price": t.get("entry_price"), "stop_loss": t.get("stop_loss"),
               "take_profit_1": t.get("take_profit_1"), "direction": t.get("direction"),
               "qty": t.get("qty") if t.get("qty") is not None else t.get("position_size"),
               "package_meta": packages.get(str(t.get("order_package_id") or ""))}
        r, basis = r_multiple_provenanced(row, contract_value_usd_for(t.get("symbol")))
        if r is None or basis != R_BASIS_DECLARED:
            continue
        state, _ = classify_r(row)
        try:
            pnl_bucket = classify_pnl(t)[0]
        except Exception:  # noqa: BLE001  # allow-silent: an unreadable pnl provenance counts as NOT measured (the conservative bucket), never as measured
            pnl_bucket = "unverified"
        out.append({"strategy": t.get("strategy_name") or "unknown", "account": t.get("account_id"),
                    "account_class": t.get("account_class"), "r": float(r), "closed_at": t.get("closed_at"),
                    "stop_unmoved": state == R_CONFIRMED_INITIAL, "pnl_measured": pnl_bucket == MEASURED})
    return out


def live_bar(trades: Iterable[Mapping], packages: Mapping[str, Any], min_n: int = MIN_N) -> Dict[str, Any]:
    rows = confirmed_r_rows(trades, packages)
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["strategy"], []).append(r)
    legs = {}
    for leg, rs in sorted(by.items()):
        v = verdict([x["r"] for x in rs], min_n)
        v["stop_unmoved_subset"] = verdict([x["r"] for x in rs if x["stop_unmoved"]], min_n)
        v["pnl_measured_subset"] = verdict([x["r"] for x in rs if x["pnl_measured"]], min_n)
        v["pooled"] = {"real_money": sum(1 for x in rs if x["account_class"] == "real_money"),
                       "paper": sum(1 for x in rs if x["account_class"] != "real_money"),
                       "accounts": sorted({str(x["account"]) for x in rs})}
        legs[leg] = v
    return {"rule": {"min_n": min_n, "lcb": "one-sided 80% (z 0.8416)", "r_population": "R on the declared_initial basis (signal-time risk); stop_unmoved subset reported, not used",
                     "pooling": "demo floor + real money of the same leg pooled"},
            "population": {"confirmed_r_trades": len(rows)}, "legs": legs}


#: The daily ladder feed (LIVE-BAR-LADDER-FEED, OPERATING-PLAN § 2 "Live-performance promotion path").
LATEST_REL = Path("comms/live_bar/latest.json")


def write_latest(out: Dict[str, Any], path: Path, now: Optional[datetime] = None) -> Path:
    """Write the live-bar result as the feed file, atomically, stamped ``generated_at`` (UTC ISO).

    Consumers judge freshness from ``generated_at`` (the row's closing check: < 26 h old). The file carries
    per-leg verdicts, n and R statistics only: no balances, no account ids beyond the account names already
    in config/accounts.yaml."""
    doc = dict(out)
    doc["generated_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    doc["schema"] = 1
    p = path if path.is_absolute() else REPO / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def _fetch(table: str, max_pages: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for page in range(max_pages):
        res = subprocess.run([str(REPO / "scripts/ops/diag_fetch.sh"), f"journal?table={table}&limit=1000&offset={page * 1000}"],
                             capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            raise RuntimeError(f"diag fetch {table} page {page} failed: {res.stderr[-200:]}")
        batch = json.loads(res.stdout)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--trades", help="JSON list of trades rows (default: read the live diag journal)")
    ap.add_argument("--packages", help="JSON list of order_packages rows")
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", nargs="?", const=str(LATEST_REL), default=None, metavar="PATH",
                    help=f"also write the result (with generated_at) to PATH (default {LATEST_REL}): the daily "
                         "ladder feed (LIVE-BAR-LADDER-FEED) read by the resolver and the reviews")
    a = ap.parse_args(argv)
    trades = json.loads(Path(a.trades).read_text()) if a.trades else _fetch("trades", a.max_pages)
    pk_rows = json.loads(Path(a.packages).read_text()) if a.packages else _fetch("order_packages", a.max_pages)
    packages = {str(p.get("order_package_id")): _meta(p.get("meta")) for p in pk_rows}
    out = live_bar(trades, packages, a.min_n)
    out["population"].update({"trades_read": len(trades), "packages_read": len(pk_rows)})
    if a.write:
        write_latest(out, Path(a.write))
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"live bar: >= {a.min_n} confirmed-R trades, sum R > 0, 80% LCB > 0 · confirmed-R trades {len([1 for _ in out['legs']])} legs, "
          f"{out['population']['confirmed_r_trades']} trades of {len(trades)} read")
    for leg, v in sorted(out["legs"].items(), key=lambda kv: (-kv[1]["n"])):
        print(f"  {leg:34s} {v['verdict']:8s} n={v['n']:4d} sumR={v['sum_r']} mean={v['mean_r']} lcb80={v['lcb80']} "
              f"(real {v['pooled']['real_money']}, paper {v['pooled']['paper']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
