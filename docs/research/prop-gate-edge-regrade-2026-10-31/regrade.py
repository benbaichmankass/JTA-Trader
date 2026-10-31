#!/usr/bin/env python3
"""Re-grade every recorded RULE-P5-GATE-BRK-PER-LEG-V2 verdict under V3 (v2 AND edge CI lower bound > 0).

Inputs: the three research dirs' ledgers + summary.json (v2 columns). Outputs: regrade.json, null_cells/.
`python3 regrade.py`          -> edge + (cached) null EV, writes regrade.json
`python3 regrade.py --nulls`  -> (re)runs the missing zero-edge null simulations first (1 seed, cells' protocol), 4 procs
Lane PROP-GATE-EDGE-SENSITIVE.
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts/research"))
import prop_ev_sim as pes  # noqa: E402
import prop_gate as pg  # noqa: E402

SOURCES = [  # (dir, record leg name fn)
    ("docs/research/prop-gate-rerun-2026-10-29/RQ-20261029-9a2c-01", None),
    ("docs/research/prop-replacement-2026-10-30", None),
    ("docs/research/e4-prop-sim-2026-10-30", None),
]
NULLS = HERE / "null_cells"


def groups():
    out = []
    for d, _ in SOURCES:
        for r in json.loads((REPO / d / "summary.json").read_text()):
            lg = r["leg"]
            short = lg.replace("trend_donchian_", "").replace("_prop", "") if lg.startswith("trend_donchian_") else lg
            out.append((d, r, short))
    return out


def ledger_rows(d, short, win):
    return pes.load_rows(REPO / d / "ledgers" / f"{short}_{win}.jsonl")


def null_path(d, short, win, acct, arm):
    return NULLS / f"{Path(d).name}__{short}__{win}__{acct}__{arm}.json"


def _job(a):
    d, short, win, acct, arm = a
    p = null_path(d, short, win, acct, arm)
    if not p.exists():
        pg.null_cell(ledger_rows(d, short, win), short, acct, arm, p, HERE / "work")


def main():
    gs = groups()
    if "--nulls" in sys.argv:
        NULLS.mkdir(exist_ok=True)
        jobs = [(d, short, r["window"], r["account"], r["arm"]) for d, r, short in gs if r["n"] >= pg.N_FLOOR]
        with ProcessPoolExecutor(4) as ex:
            list(ex.map(_job, jobs))
    res = []
    for d, r, short in gs:
        rows = ledger_rows(d, short, r["window"])
        edge = pg.edge_ci(pg.ledger_net_r(rows, r["account"], r["arm"]))
        npth = null_path(d, short, r["window"], r["account"], r["arm"])
        null = None
        if npth.exists():
            p = json.loads(npth.read_text())["results"]["path"]
            null = {"null_ev_usd": p["ev_net_usd_per_life"],
                    "null_B": round(min(1.0, p["p_breach_max_dd_in_eval"] + p["p_breach_daily_loss_in_eval"]), 3)}
        res.append({"source": Path(d).name, "leg": r["leg"], "window": r["window"], "account": r["account"], "arm": r["arm"],
                    "n": r["n"], "v2_verdict": r["verdict"], "v2_ev_median_usd": r["ev_median_usd"], "v2_ev_worst_usd": r["ev_worst_usd"],
                    "edge": edge, "null": null if null else {"read_state": "not_run" if r["n"] >= pg.N_FLOOR else "n<floor"},
                    "v3_verdict": pg.grade_v3(r["verdict"], edge)})
    (HERE / "regrade.json").write_text(json.dumps({"rule": pg.RULE_V3, "z": pg.Z95, "rows": res}, indent=1))
    for x in res:
        e = x["edge"]
        print(f"{x['source'][:14]:15}{x['leg']:25}{x['window']:5}{x['account']:12}{x['arm']:4}n={x['n']:<5}{x['v2_verdict']:14}"
              f"edge={e['mean_r']} [{e['ci_lo']},{e['ci_hi']}] null={x['null'].get('null_ev_usd')} -> {x['v3_verdict']}")


if __name__ == "__main__":
    main()
