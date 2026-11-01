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
    rel = (u.get("equities") or {}).get("sp500_membership")
    if not rel:
        return []
    f = Path(rel)
    if not f.is_absolute():
        f = (base or DEFAULT_PATH.parents[1]) / rel
    with open(f, newline="") as fh:
        return list(csv.DictReader(fh))


def equity_symbols(u: Dict[str, Any], base: Path | None = None) -> List[str]:
    """Ordered, de-duplicated: core -> ETFs -> current S&P 500 members -> removed S&P 500 members (so a time-budgeted run
    covers the things we trade first)."""
    e = u.get("equities") or {}
    etfs: List[str] = []
    for v in (e.get("etfs") or {}).values():
        etfs += list(v or [])
    rows = sp500_rows(u, base)
    cur = [r["symbol"] for r in rows if r.get("still_member") == "true"]
    old = [r["symbol"] for r in rows if r.get("still_member") != "true"]
    return _dedupe(list(e.get("core") or []) + etfs + list(e.get("extra") or []) + cur + old)


def delisted_symbols(u: Dict[str, Any], base: Path | None = None) -> List[str]:
    cur = {r["symbol"] for r in sp500_rows(u, base) if r.get("still_member") == "true"}
    return _dedupe([r["symbol"] for r in sp500_rows(u, base) if r["symbol"] not in cur])


def options_underlyings(u: Dict[str, Any]) -> List[str]:
    return _dedupe((u.get("options") or {}).get("underlyings") or [])


if __name__ == "__main__":
    u = load()
    es = equity_symbols(u)
    print(f"equities: {len(es)} symbols (core {len((u['equities'].get('core') or []))}, delisted S&P names {len(delisted_symbols(u))}); "
          f"options underlyings: {len(options_underlyings(u))}")
