#!/usr/bin/env python3
# wiring: manual-only - run once by research unit RQ-20261125-bf90-01 (row INDEX-CAPIT-SIP-CLOSED-BARS) to establish the free-plan SIP entitlement
"""Does this Alpaca key pair get CLOSED daily bars on ``feed=sip`` for a request ending within the last day? (row INDEX-CAPIT-SIP-CLOSED-BARS)

The free market-data plan is documented to withhold only the LATEST 15 minutes of SIP data. ``index_capitulation_1x`` will read its
CLOSED daily bars with ``feed=sip`` and ``end = now - 16 min``. This probe sends exactly those requests, for every ticker of the leg,
plus two controls, and writes what the venue answered:

* ``sip_closed``   feed=sip, end = now - 16 min  -> the request the leg makes (expect HTTP 200, bars through the last closed session)
* ``sip_now``      feed=sip, end = now           -> NEGATIVE CONTROL: shows the probe can see a refusal (expect HTTP 403 while the
                                                    market has printed in the last 15 minutes; 200 outside the session is not a fail)
* ``iex_closed``   feed=iex, end = now - 16 min  -> the feed the leg reads today, for the bar-by-bar comparison

It records the key pair KIND (paper / live, from ``AlpacaReadOnly.from_env``) and a sha256 prefix of the key ID only (the same
fingerprint ``scripts/ops/get_env.py`` publishes), so the VM's pair can be compared without printing a key. Read-only (the
``alpaca_readonly`` allowlist). Exit 0 when every ticker's ``sip_closed`` read returned bars, 1 otherwise, 2 when no key is present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import alpaca_readonly as A  # noqa: E402

LEG_DIR = REPO / "comms" / "research" / "INDEX-CAPIT-1X-LEG"
SIP_DELAY_MIN = 16


def _fp(v: str | None) -> str | None:
    return None if not v else f"sha256:{hashlib.sha256(v.encode('utf-8', 'replace')).hexdigest()[:12]} (len={len(v)})"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(cli: Any, sym: str, feed: str, start: datetime, end: datetime) -> Dict[str, Any]:
    p = {"symbols": sym, "timeframe": "1Day", "start": _iso(start), "end": _iso(end), "limit": 1000, "adjustment": "split",
         "feed": feed}
    url = f"https://{A.DATA_HOST}{A.BARS_PATH}"
    try:
        # one direct GET (cli.get raises on a 4xx and drops the status this probe is about); the allowlist check runs first
        A.check_request("GET", url)
        r = cli._s.get(url, headers=cli._h, params=p, timeout=60)
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as read_state could_not_look with the error text
        return {"read_state": "could_not_look", "error": str(exc)[:200]}
    out: Dict[str, Any] = {"http": r.status_code, "start": p["start"], "end": p["end"]}
    if r.status_code != 200:
        out["read_state"] = "refused"
        out["message"] = str(r.text)[:200]
        return out
    bars = ((r.json() or {}).get("bars") or {}).get(sym) or []
    out["read_state"] = "ok" if bars else "empty"
    out["n_bars"] = len(bars)
    if bars:
        out["last_bar"] = {k: bars[-1].get(k) for k in ("t", "o", "h", "l", "c", "v")}
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args(argv)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        cli = A.AlpacaReadOnly.from_env()
    except Exception as exc:  # noqa: BLE001  # allow-silent: recorded as no_key and exit 2
        (out_dir / "sip_entitlement.json").write_text(json.dumps({"read_state": "no_key", "error": str(exc)}, indent=1) + "\n")
        return 2
    kid = os.environ.get("ALPACA_API_KEY_ID") if cli.key_kind == "paper" else os.environ.get("ALPACA_API_KEY_ID_LIVE")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=a.days)
    tickers = json.loads((LEG_DIR / "spec.json").read_text())["population"]
    res: Dict[str, Any] = {"schema": "alpaca_sip_entitlement_probe/1", "row": "INDEX-CAPIT-SIP-CLOSED-BARS",
                           "probed_at": _iso(now), "key_kind": cli.key_kind, "key_id_fingerprint": _fp(kid),
                           "sip_delay_minutes": SIP_DELAY_MIN, "tickers": {}}
    for t in tickers:
        res["tickers"][t] = {
            "sip_closed": _read(cli, t, "sip", start, now - timedelta(minutes=SIP_DELAY_MIN)),
            "sip_now": _read(cli, t, "sip", start, now),
            "iex_closed": _read(cli, t, "iex", start, now - timedelta(minutes=SIP_DELAY_MIN)),
        }
        r = res["tickers"][t]
        print(t, {k: (v.get("http"), v.get("read_state"), (v.get("last_bar") or {}).get("t")) for k, v in r.items()})
    rows = res["tickers"].values()
    res["summary"] = {
        "tickers": len(tickers),
        "sip_closed_ok": sum(1 for r in rows if r["sip_closed"].get("read_state") == "ok"),
        "sip_now_refused": sum(1 for r in rows if r["sip_now"].get("read_state") == "refused"),
        "iex_closed_ok": sum(1 for r in rows if r["iex_closed"].get("read_state") == "ok"),
        "sip_closed_last_bar_dates": sorted({(r["sip_closed"].get("last_bar") or {}).get("t") for r in rows} - {None}),
    }
    res["summary"]["entitled"] = res["summary"]["sip_closed_ok"] == len(tickers)
    (out_dir / "sip_entitlement.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["summary"]))
    return 0 if res["summary"]["entitled"] else 1


if __name__ == "__main__":
    sys.exit(main())
