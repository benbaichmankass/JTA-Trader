#!/usr/bin/env python3
"""ML-REAL-MONEY-OVERLAY demotion trigger: a Bernoulli CUSUM on the mirror's REDUCED trades (practice M10).

The overlay earns its place by reducing trades that win LESS often than the leg does as a whole. On the
V2 evidence record (RQ-20261029-5785-02, TD family, 1,830 OOS gate trades) the reduced trades won at
p0 = 0.325 (n 462) against p1 = 0.378 for take-all. This monitors each CLOSED reduced trade on the mirror
(bybit_portfolio by default) with the log-likelihood-ratio CUSUM for p0 vs p1:

    S_t = max(0, S_{t-1} + (ln(p1/p0) if won else ln((1-p1)/(1-p0))))      ALARM when S_t >= H

A win/loss CUSUM, not an R CUSUM, because per-trade R is heavy-tailed (one +10 R winner trips an R CUSUM
on a healthy overlay: measured 90% false alarms within 60 reduced trades at h=4). Calibrated on the same
record by simulation: H = 2.0 gives P(false alarm within 100 healthy reduced trades) = 0.05, and a median
144 reduced trades to alarm if the overlay degrades to no better than take-all (p = p1); a broken overlay
that cuts winners (p >= 0.5) alarms in ~30. ALARM -> demote: delete the leg from ``config/overlay_policy.yaml``
(back to annotate). The alarm is a demotion signal for the manager, never an automatic config write.

Input: JSONL rows ``{strategy, account, multiplier, net_r, closed_at}`` -- the shadow/applied multiplier of
each closed trade joined to its realised net R. Only rows with multiplier < 1.0 are reduced trades.

    python3 scripts/ops/overlay_cusum.py --decisions <joined.jsonl> [--account bybit_portfolio] [--json]
    python3 scripts/ops/overlay_cusum.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from typing import Iterable

P0 = 0.325   # healthy reduced-trade win rate, RQ-20261029-5785-02 TD OOS (n 462)
P1 = 0.378   # take-all win rate, same population (n 1830)
H = 2.0
EVIDENCE = "comms/research/RQ-20261029-5785-02/local-v2-20261029/verdict.json"
STEP_WIN, STEP_LOSS = math.log(P1 / P0), math.log((1 - P1) / (1 - P0))


def cusum(rows: Iterable[dict], account: str | None = "bybit_portfolio") -> dict:
    """Run the CUSUM over closed reduced trades in closed_at order. A count of 0 reduced trades reads
    ``no_reduced_trades`` (not 'healthy'): nothing was looked at."""
    rs = [r for r in rows if (account is None or r.get("account") == account)
          and r.get("multiplier") is not None and float(r["multiplier"]) < 1.0 and r.get("net_r") is not None]
    rs.sort(key=lambda r: str(r.get("closed_at") or ""))
    s, peak, alarm_at = 0.0, 0.0, None
    wins = 0
    for i, r in enumerate(rs, 1):
        won = float(r["net_r"]) > 0
        wins += won
        s = max(0.0, s + (STEP_WIN if won else STEP_LOSS))
        peak = max(peak, s)
        if alarm_at is None and s >= H:
            alarm_at = i
    state = "no_reduced_trades" if not rs else ("ALARM" if alarm_at else "ok")
    return {"state": state, "n_reduced": len(rs), "reduced_win_rate": round(wins / len(rs), 4) if rs else None,
            "S": round(s, 4), "S_peak": round(peak, 4), "H": H, "alarm_at_reduced_trade": alarm_at,
            "p0": P0, "p1": P1, "account": account, "evidence": EVIDENCE,
            "action": "demote: delete the alarming legs from config/overlay_policy.yaml" if alarm_at else None}


def _self_test() -> int:
    rnd = random.Random(7)
    healthy = [{"account": "bybit_portfolio", "multiplier": 0.5, "net_r": 1.0 if rnd.random() < P0 else -1.0,
                "closed_at": f"{i:05d}"} for i in range(60)]
    broken = [{"account": "bybit_portfolio", "multiplier": 0.5, "net_r": 1.0 if rnd.random() < 0.6 else -1.0,
               "closed_at": f"{i:05d}"} for i in range(200)]
    taken = [{"account": "bybit_portfolio", "multiplier": 1.0, "net_r": 5.0, "closed_at": "0"}] * 50
    other = [{"account": "bybit_2", "multiplier": 0.5, "net_r": 9.0, "closed_at": "0"}] * 50
    a, b, c = cusum(healthy + taken + other), cusum(broken), cusum(taken)
    ok = (a["n_reduced"] == 60 and b["state"] == "ALARM" and c["state"] == "no_reduced_trades"
          and b["alarm_at_reduced_trade"] is not None and b["alarm_at_reduced_trade"] < 80)
    print(json.dumps({"self_test": "PASS" if ok else "FAIL", "healthy": a["state"], "broken": b,
                      "empty": c["state"]}, indent=1))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--decisions", required=True)
    ap.add_argument("--account", default="bybit_portfolio", help="'all' for every account")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = [json.loads(ln) for ln in open(a.decisions, encoding="utf-8") if ln.strip()]
    out = cusum(rows, None if a.account == "all" else a.account)
    print(json.dumps(out, indent=None if a.json else 1))
    return 1 if out["state"] == "ALARM" else 0


if __name__ == "__main__":
    sys.exit(main())
