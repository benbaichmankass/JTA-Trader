#!/usr/bin/env python3
"""oi-feed-freshness -- is the live open-interest feed the E4 leg reads fresh, per symbol? (row E4-DEMO-LEG)

The E4 leg (``e4_oi_shock_1h``) can only see an open-interest shock the feed has recorded. Its feed
(``src/runtime/oi_feed.py``) writes ``runtime_logs/oi_feed/status.json`` on the VM, served by
``/api/diag/log_file?name=oi_feed_status``. This grades that CONSUMED artifact -- never the producer's
own say-so -- for every symbol the leg declares in ``config/strategies.yaml``:

  fresh           the symbol's newest OI row is within the feed's ``stale_after_s`` of the read time
                  AND the store spans the 7-day detector window (``warm``)
  cold            fresh, but the store does not yet span the detector window (no event can fire)
  stale           the newest row is older than ``stale_after_s``
  could_not_look  no status payload, the symbol is absent from it, or its read_state says so

The population is the leg's declared symbols; a missing symbol is ``could_not_look``, never fresh.

Runner: ``.github/workflows/oi-feed-freshness.yml`` (every 2 h; one tracking issue). Also run by hand:
    bash scripts/ops/diag_fetch.sh 'log_file?name=oi_feed_status&lines=1' > /tmp/oi.json
    python3 scripts/ops/oi_feed_freshness.py --status-json /tmp/oi.json
Exit: 0 all fresh · 1 any stale/cold · 3 any could_not_look (worst wins). ``--self-test`` plants a
good, a stale and an absent fixture and checks each grades as it must.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
LEG = "e4_oi_shock_1h"
RANK = {"fresh": 0, "cold": 1, "stale": 1, "could_not_look": 3}


def leg_symbols(strategies_yaml: Path = REPO / "config" / "strategies.yaml") -> List[str]:
    import yaml
    cfg = (yaml.safe_load(strategies_yaml.read_text()) or {}).get("strategies", {}).get(LEG) or {}
    return sorted(str(s).upper() for s in cfg.get("symbols") or [])


def unwrap(payload: Any) -> Optional[dict]:
    """The status document from either the raw file or a ``/api/diag/log_file`` response (``lines``)."""
    if isinstance(payload, dict) and isinstance(payload.get("symbols"), dict):
        return payload
    if isinstance(payload, dict) and payload.get("lines"):
        text = "\n".join(x if isinstance(x, str) else json.dumps(x) for x in payload["lines"])
        try:
            doc = json.loads(text)
        except ValueError:
            return None
        return doc if isinstance(doc, dict) and isinstance(doc.get("symbols"), dict) else None
    return None


def grade(doc: Optional[dict], symbols: List[str], now: float) -> Dict[str, Any]:
    rows = {}
    for s in symbols:
        st = ((doc or {}).get("symbols") or {}).get(s)
        if not isinstance(st, dict) or st.get("newest_ts") is None:
            rows[s] = {"state": "could_not_look", "why": "absent from the status payload" if doc else "no payload",
                       "last_error": (st or {}).get("last_error") if isinstance(st, dict) else None}
            continue
        bound = float((doc or {}).get("stale_after_s") or 1200)
        age = now - (float(st["newest_ts"]) + 300)
        state = "stale" if age > bound else ("fresh" if st.get("warm") else "cold")
        rows[s] = {"state": state, "newest_age_s": round(age, 1), "bound_s": bound, "n_rows": st.get("n_rows"),
                   "span_h": None if st.get("span_s") is None else round(float(st["span_s"]) / 3600, 1),
                   "n_live": st.get("n_live"), "last_error": st.get("last_error")}
    worst = max((RANK[r["state"]] for r in rows.values()), default=3)
    return {"population": f"{len(symbols)} symbol(s) declared by {LEG}", "symbols": rows,
            "exit": worst, "states": {k: v["state"] for k, v in rows.items()}}


def render(res: Dict[str, Any]) -> str:
    out = [f"oi-feed-freshness: {res['population']}"]
    for s, r in sorted(res["symbols"].items()):
        out.append(f"  {s:9s} {r['state']:15s} age={r.get('newest_age_s', '—')}s span={r.get('span_h', '—')}h "
                   f"rows={r.get('n_rows', '—')} live={r.get('n_live', '—')} err={r.get('last_error') or '—'}")
    return "\n".join(out)


def _self_test() -> int:
    now = 1_800_000_000.0
    syms = ["BTCUSDT", "ETHUSDT"]
    good = {"stale_after_s": 1200, "symbols": {s: {"newest_ts": now - 400, "warm": True, "n_rows": 2100, "span_s": 7.5 * 86400}
                                               for s in syms}}
    stale = json.loads(json.dumps(good))
    stale["symbols"]["ETHUSDT"]["newest_ts"] = now - 7200
    checks = [(grade(good, syms, now)["exit"], 0, "good"), (grade(stale, syms, now)["exit"], 1, "stale"),
              (grade(None, syms, now)["exit"], 3, "absent"),
              (grade({"symbols": {"BTCUSDT": good["symbols"]["BTCUSDT"]}}, syms, now)["exit"], 3, "one symbol missing"),
              (grade(unwrap({"lines": [json.dumps(good)]}), syms, now)["exit"], 0, "diag-wrapped good")]
    bad = [f"{name}: exit {got} != {want}" for got, want, name in checks if got != want]
    print("self-test:", "OK" if not bad else bad)
    return 0 if not bad else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status-json", help="the raw status.json or a /api/diag/log_file response")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    doc = None
    if a.status_json:
        try:
            doc = unwrap(json.loads(Path(a.status_json).read_text()))
        except (OSError, ValueError):
            doc = None
    res = grade(doc, leg_symbols(), time.time())
    print(json.dumps(res, indent=1) if a.json else render(res))
    return res["exit"]


if __name__ == "__main__":
    sys.exit(main())
