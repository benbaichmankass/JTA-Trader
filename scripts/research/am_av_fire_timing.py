#!/usr/bin/env python3
# wiring: diagnostic read of am-action-value policy shards (artifacts <run_id>-<class>-avshards-<run>-*); row AM-V2-STAGE-B-POLICY-ARM; authored iteration 3 (RQ-20261125-c7e3-05..07)
"""WHEN does an am_action_value policy fire, and what does that timing cost against its matched uniform control on the same trades?

Tier 1 research tooling: reads downloaded policy shards (``am_policy/*.jsonl.gz``, schema am_action_value/1) and prints buckets; writes nothing.
Population: fired DEV trades (entry < 2026-01-01) of one class. Per trade: the policy's fire bar ``k`` (bars since fill), the HOLD path length in
bars (exit_ts - entry over the timeframe), policy - HOLD net R, and mean(control) - HOLD net R. Every number is ESTIMATED (replay)."""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics as st
from datetime import datetime

TF = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def load(root: str, cls: str, dev_end: str = "2026-01-01") -> list[tuple]:
    rows = []
    for f in glob.glob(f"{root}/**/*.jsonl.gz", recursive=True):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                d = json.loads(line)
                a = d.get("a", {}).get(cls)
                tf = TF.get(d.get("tf"))
                if not a or not a.get("n") or not tf or str(d["e"])[:10] >= dev_end:
                    continue
                held = max(1.0, (d["b"][1] - datetime.fromisoformat(str(d["e"])).timestamp()) / tf)
                cm = st.mean(c[0] for c in a["c"]) if a.get("c") else None
                rows.append((a["k"], held, a["p"][0] - d["b"][0], None if cm is None else cm - d["b"][0], d["b"][0]))
    return rows


def buckets(rows: list[tuple]) -> dict:
    out = {"n_fired_dev": len(rows), "by_k": {}, "by_frac": {}}
    if not rows:
        return out

    def summ(sel):
        s = [r for r in rows if sel(r)]
        if not s:
            return None
        ctl = [r[3] for r in s if r[3] is not None]
        return {"n": len(s), "share": round(len(s) / len(rows), 4), "policy_minus_hold_r": round(sum(r[2] for r in s), 1),
                "control_minus_hold_r": round(sum(ctl), 1) if ctl else None, "hold_win_rate": round(sum(r[4] > 0 for r in s) / len(s), 3)}
    for lo, hi in ((0, 2), (2, 3), (3, 6), (6, 11), (11, 10**9)):
        out["by_k"][f"[{lo},{hi})"] = summ(lambda r, lo=lo, hi=hi: lo <= r[0] < hi)
    for lo, hi in ((0, .1), (.1, .25), (.25, .5), (.5, 1.01), (1.01, 99)):
        out["by_frac"][f"[{lo},{hi})"] = summ(lambda r, lo=lo, hi=hi: lo <= r[0] / r[1] < hi)
    ks, fr = sorted(r[0] for r in rows), sorted(r[0] / r[1] for r in rows)
    out["k_p25_p50_p75"] = [ks[len(ks) // 4], ks[len(ks) // 2], ks[3 * len(ks) // 4]]
    out["k_over_held_p25_p50_p75"] = [round(fr[len(fr) // 4], 3), round(fr[len(fr) // 2], 3), round(fr[3 * len(fr) // 4], 3)]
    out["provenance"] = "ESTIMATED"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shards", required=True, help="directory holding the downloaded policy shard artifacts")
    ap.add_argument("--class", dest="cls", required=True)
    a = ap.parse_args(argv)
    print(json.dumps(buckets(load(a.shards, a.cls)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
