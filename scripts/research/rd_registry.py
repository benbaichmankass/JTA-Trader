#!/usr/bin/env python3
"""Write comms/research/rd_registry.json: the idea-level R&D registry (one entry per strategy / ML idea).

Operator 2026-11-12 (lane RD-REGISTRY). The projection, stage rules and attribution rules live in
``src/runtime/rd_registry.py`` and are copied into the output file. Read-only over the repo; gates nothing.

Usage:
  python3 scripts/research/rd_registry.py                 # write comms/research/rd_registry.json
  python3 scripts/research/rd_registry.py --registry-url https://ict-bot.duckdns.org/api/bot/ml/registry
  python3 scripts/research/rd_registry.py --stdout        # print, do not write
Exit 0 on a written registry; 2 when the research catalog could not be read at all (COULD NOT MEASURE).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.runtime import rd_registry  # noqa: E402

OUT_REL = "comms/research/rd_registry.json"


def _live_rows(url: str) -> list[dict] | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 -- operator-configured https read
            doc = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 -- falls back to the committed snapshot, stated in read_state
        print(f"rd_registry: live registry unreadable ({type(exc).__name__}); using committed snapshot", file=sys.stderr)
        return None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) and rows else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--out", default=OUT_REL)
    ap.add_argument("--registry-url", default=None, help="live /api/bot/ml/registry URL (else committed snapshot)")
    ap.add_argument("--stdout", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    out = root / a.out
    previous = None
    if out.is_file():
        try:
            previous = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
    live = _live_rows(a.registry_url) if a.registry_url else None
    doc = rd_registry.build_registry(root, live_registry_rows=live, previous=previous)
    if doc["read_state"]["research_catalog"]["state"] == "unreadable":
        print("rd_registry: COULD NOT MEASURE -- research catalog unreadable", file=sys.stderr)
        return 2
    problems = rd_registry.cross_check(doc, root)
    doc["cross_check"] = {"ok": not problems, "problems": problems or None}
    for p in problems:
        print(f"rd_registry: CROSS-CHECK MISMATCH: {p}", file=sys.stderr)
    text = json.dumps(doc, indent=1, sort_keys=False, default=str) + "\n"
    if a.stdout:
        sys.stdout.write(text)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    s = doc["summary"]
    print(f"rd_registry: {s['ideas']} ideas ({s['per_track']}); units {s['units']}", file=sys.stderr)
    for t, st in s["per_stage_per_track"].items():
        print(f"  {t}: " + ", ".join(f"{k} {v}" for k, v in st.items() if v), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
