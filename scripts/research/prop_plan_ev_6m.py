#!/usr/bin/env python3
"""PROP-PLAN-EV-6M -- standing 6-month expected return per prop firm and plan (unit RQ-20261112-09d2-06).

Operator 2026-11-10: "which one gives the highest expected return over, say a 6 month period? (we should probably add this to all
prop accounts and run it on the existing ones as well)".

It does NOT re-implement the simulation. Every cell is one ``scripts/research/prop_ev_sim.py`` subprocess at ``--horizon-days 182``;
the zero-edge null and the edge CI come from ``scripts/research/prop_gate.py`` (the one V3 implementation). The rule lives in the unit.

Tradeify FUTURES plans (EOD trailing drawdown, CME micros) are not simulated here: no leg is eligible for them
(RQ-20261112-09d2-01..03; docs/research/tradeify-futures-frontier-2026-11-12.md), so they are listed at EV = -fee if bought.

Offline research only: imports nothing from src/, places no order, changes no config.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prop_gate as pg  # noqa: E402

RULESETS = ["breakout_turbo_1step", "breakout", "velotrade_classic_1step", "velotrade_pro_1step", "tradeify_247_1step",
            "propr_classic_1step", "propr_turbo_1step", "hyrotrader", "hyrotrader_lenient"]
LEDGERS = {
    "eth4h": REPO / "docs/research/prop-retest-2026-11-06/ledgers/eth4h_3y.jsonl",
    "sol4h": REPO / "docs/research/prop-retest-2026-11-06/ledgers/sol4h_3y.jsonl",
    "ml": REPO / "docs/research/ml-entry-prop-gate-2026-11-02/ledgers/ml_entry_ethsol.jsonl",
}
BOOKS = {"ROSTER": ["eth4h", "sol4h", "ml"], "ETH4H": ["eth4h"], "ML": ["ml"]}
PRIMARY_BOOK = "ROSTER"
LEV = {"eth4h": 5, "sol4h": 2, "ml": 2}
SEEDS = (1, 2, 3)
HORIZON = 182
RISK = 0.005
CUR = ("11.0", "3.0", "0.0003")
# Tradeify FUTURES 50K list prices (help-centre article 14369021, fetched 2026-11-12); no eligible leg -> EV = -fee.
FUTURES_PLANS = {"tradeify_fut_growth_50k": 145.0, "tradeify_fut_select_50k": 165.0, "tradeify_fut_lightning_50k": 492.0}


def read_rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def cell(rs: str, legs: dict[str, Path], seed: int, out: Path) -> dict:
    cmd = [sys.executable, str(REPO / "scripts/research/prop_ev_sim.py")]
    for k, p in legs.items():
        cmd += ["--trades", f"{k}={p}", "--lev-cap", f"{k}={LEV[k]}"]
    cmd += ["--ruleset", str(REPO / f"config/prop_rulesets/{rs}.yaml"), "--costs", "breakout",
            "--commission-bps-rt", CUR[0], "--slippage-bps-rt", CUR[1], "--swap-daily", CUR[2], "--swap-model", "prorated",
            "--funded-start", "fresh", "--sizing", "start", "--risk-pct", str(RISK), "--dd-switch-frac", "0.8",
            "--horizon-days", str(HORIZON), "--seed", str(seed), "--lives", "1000", "--outer", "2", "--lives-per-outer", "100",
            "--modes", "path", "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    if r.returncode != 0 or not out.exists():
        return {"error": (r.stderr or r.stdout)[-400:]}
    p = json.loads(out.read_text())["results"]["path"]
    return {"ev": p["ev_net_usd_per_life"], "ev_rebuy_6m": round(p["ev_net_usd_per_365d_with_rebuy"] / 2, 2),
            "p_pass_eval": p["p_pass_eval"], "p_breach": p["p_breach_max_dd"], "fee": p["account_fee_usd"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    out = Path(a.out)
    (out / "cells").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ev6m-"))
    rows = {k: read_rows(p) for k, p in LEDGERS.items()}
    null_paths = {}
    for k, r in rows.items():
        p = tmp / f"{k}.null.jsonl"
        p.write_text("".join(json.dumps(x) + "\n" for x in pg.demean_rows(r, "tradeify_1", "cur")))
        null_paths[k] = p
    edges = {}
    for b, legs in BOOKS.items():
        nr = [x for k in legs for x in pg.ledger_net_r(rows[k], "tradeify_1", "cur")]
        edges[b] = pg.edge_ci(nr)
    jobs = []
    for rs in RULESETS:
        for b, legs in BOOKS.items():
            for s in SEEDS:
                for arm in ("real", "null"):
                    src = LEDGERS if arm == "real" else null_paths
                    jobs.append((rs, b, s, arm, {k: src[k] for k in legs}))
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda j: (j[:4], cell(j[0], j[4], j[2], out / "cells" / f"{j[0]}__{j[1]}__{j[3]}__s{j[2]}.json")), jobs))
    by: dict = {}
    for (rs, b, s, arm), r in res:
        by.setdefault((rs, b), {}).setdefault(arm, []).append(r)
    table = []
    for (rs, b), d in by.items():
        real, null = d["real"], d["null"]
        if any("error" in x for x in real + null):
            table.append({"ruleset": rs, "book": b, "error": [x.get("error") for x in real + null if "error" in x][:1],
                          "verdict": "not_attempted"})
            continue
        evs = [x["ev"] for x in real]
        ev_null = st.fmean(x["ev"] for x in null)
        lo = edges[b].get("ci_lo")
        buyable = min(evs) > 0 and st.fmean(evs) > ev_null and lo is not None and lo > 0
        table.append({"ruleset": rs, "book": b, "fee_usd": real[0]["fee"], "ev_6m_mean": round(st.fmean(evs), 2),
                      "ev_6m_min": round(min(evs), 2), "ev_6m_null_mean": round(ev_null, 2),
                      "ev_6m_with_rebuy_mean": round(st.fmean(x["ev_rebuy_6m"] for x in real), 2),
                      "p_pass_eval": round(st.fmean(x["p_pass_eval"] for x in real), 4),
                      "p_breach": round(st.fmean(x["p_breach"] for x in real), 4), "edge_ci_lo": lo,
                      "verdict": "BUYABLE" if buyable else "NOT_BUYABLE"})
    table.sort(key=lambda r: (r["book"] != PRIMARY_BOOK, -(r.get("ev_6m_mean") or -1e9)))
    for name, fee in FUTURES_PLANS.items():
        table.append({"ruleset": name, "book": "none eligible", "fee_usd": fee, "ev_6m_mean": -fee, "verdict": "NOT_BUYABLE",
                      "note": "no session-flat leg passes Stage 0 (RQ-20261112-09d2-01..03)"})
    prim = [r for r in table if r["book"] == PRIMARY_BOOK and r["verdict"] == "BUYABLE"]
    answer = (f"highest 6-month EV buyable plan: {prim[0]['ruleset']} (mean ${prim[0]['ev_6m_mean']})" if prim else
              "no plan is buyable with the book we run; least-negative: " +
              next((f"{r['ruleset']} (mean ${r['ev_6m_mean']}, NOT BUYABLE)" for r in table if r["book"] == PRIMARY_BOOK
                    and "ev_6m_mean" in r), "none"))
    rec = {"research_unit": a.unit, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "produced_by": "scripts/research/prop_plan_ev_6m.py", "horizon_days": HORIZON, "risk_pct": RISK, "cost_arm": "cur",
           "edges": edges, "population": {k: len(v) for k, v in rows.items()}, "table": table, "answer": answer,
           "verdict": "pass" if prim else "fail"}
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": rec["verdict"], "answer": answer}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
