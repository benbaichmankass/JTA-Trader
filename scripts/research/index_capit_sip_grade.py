#!/usr/bin/env python3
# wiring: manual-only - the grading command of research unit RQ-20261125-bf90-01 (row INDEX-CAPIT-SIP-CLOSED-BARS)
"""Grade RQ-20261125-bf90-01 against its registered rule and write ``verdict.json`` (the research-script-run record contract).

Rule RULE-RQ-20261125-bf90-01-SIP-CLOSED: PASS IFF ``sip_entitlement.json`` summary.sip_closed_ok == 18 of 18 AND, over the tickers
both feeds read (``feed_agreement_sip.json``), SIP signals match the consolidated set with 0 SIP-only signals and consolidated-only
<= 2% of consolidated signals. FAIL otherwise. A missing input is ``producer_failed``, never a verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def grade(out_dir: Path) -> dict:
    ent_p, fa_p = out_dir / "sip_entitlement.json", out_dir / "feed_agreement_sip.json"
    if not ent_p.exists() or not fa_p.exists():
        return {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                "population": "RQ-20261125-bf90-01: an input record is missing",
                "note": f"missing: {[p.name for p in (ent_p, fa_p) if not p.exists()]}"}
    ent, fa = json.loads(ent_p.read_text()), json.loads(fa_p.read_text())
    es, fs = ent.get("summary") or {}, fa.get("summary") or {}
    if ent.get("read_state") == "no_key" or not fs.get("tickers_read"):
        return {"verdict": "not_applicable", "read_state": "producer_failed", "n": None,
                "population": "RQ-20261125-bf90-01: no key, or no ticker read on both feeds",
                "note": json.dumps({"entitlement": ent.get("read_state"), "tickers_read": fs.get("tickers_read")})}
    n_t = int(es.get("tickers") or 0)
    cons = int(fs.get("signals_consolidated") or 0)
    checks = {
        "sip_closed_ok_all": es.get("sip_closed_ok") == n_t == 18,
        "sip_only_zero": int(fs.get("live_only") or 0) == 0,
        "consolidated_only_le_2pct": cons > 0 and int(fs.get("consolidated_only") or 0) <= 0.02 * cons,
    }
    ok = all(checks.values())
    hy = (fa.get("hybrid_sip_signal_iex_open") or {}).get("summary")
    return {
        "verdict": "pass" if ok else "fail",
        "read_state": "measured",
        "n": cons,
        "population": (f"{n_t} index_capitulation_1x tickers probed {ent.get('probed_at')} ({ent.get('key_kind')} pair); feed agreement over "
                       f"{fs.get('tickers_read')} tickers, consolidated signals {cons}, sessions = those the live IEX path serves "
                       "(2022-12-01 start where IEX has no bars)"),
        "measurement": {"checks": checks, "entitlement": es, "feed_agreement_sip": fs, "hybrid_sip_signal_iex_open": hy},
        "note": (f"sip_closed_ok {es.get('sip_closed_ok')}/{n_t}, sip_now refused {es.get('sip_now_refused')}/{n_t} (negative control); "
                 f"SIP signals {fs.get('signals_live')} vs consolidated {cons}, matching {fs.get('matching')}, SIP-only {fs.get('live_only')}, "
                 f"consolidated-only {fs.get('consolidated_only')}"),
    }


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    v = grade(Path(a.out))
    (Path(a.out) / "verdict.json").write_text(json.dumps(v, indent=1) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "n")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
