#!/usr/bin/env python3
# wiring: imported by scripts/ops/fetch_etf_history.py, capture_options_snapshot.py and etf_history_verify.py
"""Read config/data_universe.yaml: the single place the pipelines learn WHAT to collect."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "data_universe.yaml"


def _dedupe(xs: List[str]) -> List[str]:
    seen, out = set(), []
    for x in xs:
        x = str(x).strip().upper()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def load(path: Path | str | None = None) -> Dict[str, Any]:
    p = Path(path) if path else DEFAULT_PATH
    return yaml.safe_load(p.read_text())


def sp500_rows(u: Dict[str, Any], base: Path | None = None) -> List[Dict[str, str]]:
    rel = (u.get("us_equity_bars") or {}).get("sp500_membership")
    if not rel:
        return []
    f = Path(rel)
    if not f.is_absolute():
        f = (base or DEFAULT_PATH.parents[1]) / rel
    with open(f, newline="") as fh:
        return list(csv.DictReader(fh))


def snapshot_symbols(path: Path | str) -> List[str]:
    """Symbols from a dated lake universe snapshot (universe/us_equity/<date>.csv; needs a ``symbol`` column).
    Written by lane MARKET-DATA-LAKE (scripts/data_lake/free_sources.py universe)."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    col = next((c for c in ("symbol", "Symbol", "ticker", "act_symbol") if rows and c in rows[0]), None)
    return _dedupe([r[col] for r in rows if col and r.get(col)])


def equity_symbols(u: Dict[str, Any], base: Path | None = None, snapshot: Path | str | None = None) -> List[str]:
    """Ordered, de-duplicated: core -> curated ETFs -> current S&P 500 members -> removed S&P 500 members -> every symbol of an optional
    lake universe snapshot (so a time-budgeted run covers the things we trade first, and 1h reaches every listed ETF last)."""
    e = u.get("us_equity_bars") or {}
    etfs: List[str] = []
    for v in (e.get("etfs") or {}).values():
        etfs += list(v or [])
    rows = sp500_rows(u, base)
    cur = [r["symbol"] for r in rows if r.get("still_member") == "true"]
    old = [r["symbol"] for r in rows if r.get("still_member") != "true"]
    snap = snapshot_symbols(snapshot) if snapshot else []
    return _dedupe(list(e.get("core") or []) + etfs + list(e.get("extra") or []) + cur + old + snap)


def delisted_symbols(u: Dict[str, Any], base: Path | None = None) -> List[str]:
    cur = {r["symbol"] for r in sp500_rows(u, base) if r.get("still_member") == "true"}
    return _dedupe([r["symbol"] for r in sp500_rows(u, base) if r["symbol"] not in cur])


def options_underlyings(u: Dict[str, Any]) -> List[str]:
    return _dedupe((u.get("options") or {}).get("underlyings") or [])


if __name__ == "__main__":
    u = load()
    es = equity_symbols(u)
    print(f"equities: {len(es)} symbols (core {len((u["us_equity_bars"].get('core') or []))}, delisted S&P names {len(delisted_symbols(u))}); "
          f"options underlyings: {len(options_underlyings(u))}")
