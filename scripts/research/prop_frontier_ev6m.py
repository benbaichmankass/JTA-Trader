#!/usr/bin/env python3
"""PROP-FRONTIER-RESEARCH -- 6-month EV screen for prop plans that pass the device-free automation filter.

Lane PROP-FRONTIER-RESEARCH (2026-11-12). The rule is registered BEFORE the run in
``comms/research/prop_frontier/ev6m_rule.json`` (pushed in its own commit); this script reads it and
refuses to run if the file is absent. Memo: docs/research/prop-frontier-2026-11-12.md.

Same engine and rule shape as RQ-20261112-09d2-06 (PROP-PLAN-EV-6M, PR #25203): every cell is one
``scripts/research/prop_ev_sim.py`` subprocess at ``--horizon-days 182``; the zero-edge null is the same
ledger re-centred to mean net R 0 under the same costs (``prop_gate.demean_rows`` logic); the edge CI is
``prop_gate.edge_ci``. Nothing here re-implements the simulator.

Inputs are the per-trade ledgers already committed beside each leg's Stage-0 evidence record
(``comms/strategy_evidence/runs/<date>/<leg>__trades.jsonl``), clipped to a common window so that legs with
16-year histories do not dilute legs with 1-year histories. The ledgers are on the ETF/futures instrument the
leg was measured on; the firm's CFD on the same underlying is a PROXY transfer, priced at the firm's own
first-party cost stack (commission per side + overnight fee per 00:30 UTC rollover).

Offline research only: imports nothing from src/, places no order, changes no config.

# wiring: manual-only - a one-off lane screen (PROP-FRONTIER-RESEARCH); re-run by hand when a follow-up
#   (PI-20261112-D6UC5YT4-0001/-0003) changes the book or the simulator, per the memo's buy-point table.
"""
from __future__ import annotations

import argparse
import glob
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
import prop_ev_sim as pes  # noqa: E402
import prop_gate as pg  # noqa: E402

RULE = REPO / "comms/research/prop_frontier/ev6m_rule.json"


def ledger_path(leg: str) -> Path:
    """The leg's NEWEST committed Stage-0 trade ledger. The chosen path is printed and recorded in
    verdict.json population.per_leg[leg].ledger, so the selection is never silent."""
    # provenance: ledger_path — newest committed run dir for the leg; printed below and stored in the verdict
    hits = sorted(glob.glob(str(REPO / f"comms/strategy_evidence/runs/*/{leg}__trades.jsonl")))
    if not hits:
        raise SystemExit(f"no committed ledger for {leg}")
    chosen = Path(hits[-1])  # provenance: ledger_path — newest of the sorted run dirs, printed
    print(f"ledger {leg}: {chosen.relative_to(REPO)} (newest of {len(hits)})", file=sys.stderr)
    return chosen


def load(leg: str, start: str) -> list[dict]:
    rows = [json.loads(x) for x in ledger_path(leg).read_text().splitlines() if x.strip()]
    return [r for r in rows if r["entry_time"] >= start and r.get("exit_time")]


def costs(c: dict) -> pes.CostConfig:
    return pes.CostConfig(mode="breakout", commission_bps_rt=c["commission_bps_rt"], slippage_bps_rt=c["slippage_bps_rt"],
                          swap_daily=c["swap_daily"], swap_model=c["swap_model"])


def net_r(rows: list[dict], cc: pes.CostConfig) -> list[float]:
    trades, _, _ = pes.build_trades({"x": rows}, cc)
    return [t.net_r for t in trades]


def demean(rows: list[dict], cc: pes.CostConfig) -> list[dict]:
    m = st.fmean(net_r(rows, cc))
    out = []
    for r in rows:
        r = dict(r)
        r["gross_r"] = float(r["gross_r"]) - m
        if r.get("mfe_r") is not None:
            r["mfe_r"] = max(float(r["mfe_r"]), r["gross_r"])
        out.append(r)
    return out


def cell(rs: str, legs: dict[str, Path], seed: int, risk: float, c: dict, sim: dict, out: Path) -> dict:
    cmd = [sys.executable, str(REPO / "scripts/research/prop_ev_sim.py")]
    for k, p in legs.items():
        cmd += ["--trades", f"{k}={p}", "--lev-cap", f"{k}={sim['lev_cap']}"]
    cmd += ["--ruleset", str(REPO / f"config/prop_rulesets/{rs}.yaml"), "--costs", "breakout",
            "--commission-bps-rt", str(c["commission_bps_rt"]), "--slippage-bps-rt", str(c["slippage_bps_rt"]),
            "--swap-daily", str(c["swap_daily"]), "--swap-model", c["swap_model"],
            "--funded-start", "fresh", "--sizing", "start", "--risk-pct", str(risk), "--dd-switch-frac", str(sim["dd_switch_frac"]),
            "--horizon-days", str(sim["horizon_days"]), "--seed", str(seed), "--lives", str(sim["lives"]),
            "--outer", "2", "--lives-per-outer", "100", "--modes", "path", "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, check=False)
    if r.returncode != 0 or not out.exists():
        return {"error": (r.stderr or r.stdout)[-600:]}
    p = json.loads(out.read_text())["results"]["path"]
    return {"ev": p["ev_net_usd_per_life"], "ev_rebuy_6m": round(p["ev_net_usd_per_365d_with_rebuy"] / 2, 2),
            "p_pass_eval": p["p_pass_eval"], "p_breach": p["p_breach_max_dd"], "fee": p["account_fee_usd"],
            "trades_per_life": p.get("mean_trades_per_life")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if not RULE.exists():
        raise SystemExit("rule not registered: comms/research/prop_frontier/ev6m_rule.json")
    rule = json.loads(RULE.read_text())
    sim, c = rule["sim"], rule["costs"]
    cc = costs(c)
    out = Path(a.out)
    (out / "cells").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pfev6m-"))
    all_legs = sorted({leg for b in rule["books"].values() for leg in b})
    rows = {leg: load(leg, sim["window_start"]) for leg in all_legs}
    real_p, null_p = {}, {}
    for leg, r in rows.items():
        real_p[leg] = tmp / f"{leg}.jsonl"
        real_p[leg].write_text("".join(json.dumps(x) + "\n" for x in r))
        null_p[leg] = tmp / f"{leg}.null.jsonl"
        null_p[leg].write_text("".join(json.dumps(x) + "\n" for x in demean(r, cc)))
    edges = {b: pg.edge_ci([x for leg in legs for x in net_r(rows[leg], cc)]) for b, legs in rule["books"].items()}
    per_leg = {leg: {"n": len(r), "ledger": str(ledger_path(leg).relative_to(REPO)), **pg.edge_ci(net_r(r, cc))}
               for leg, r in rows.items()}
    jobs = []
    for rs in rule["rulesets"]:
        for b, legs in rule["books"].items():
            for risk in [sim["risk_pct_primary"]] + sim.get("risk_pct_sensitivity", []):
                for s in sim["seeds"]:
                    for arm in ("real", "null"):
                        src = real_p if arm == "real" else null_p
                        jobs.append((rs, b, risk, s, arm, {k: src[k] for k in legs}))

    def run(j):
        rs, b, risk, s, arm, legs = j
        return (rs, b, risk, s, arm), cell(rs, legs, s, risk, c, sim, out / "cells" / f"{rs}__{b}__r{risk}__{arm}__s{s}.json")

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs))
    by: dict = {}
    for (rs, b, risk, s, arm), r in res:
        by.setdefault((rs, b, risk), {}).setdefault(arm, []).append(r)
    table = []
    for (rs, b, risk), d in by.items():
        real, null = d["real"], d["null"]
        primary = risk == sim["risk_pct_primary"] and b == rule["primary_book"]
        if any("error" in x for x in real + null):
            table.append({"ruleset": rs, "book": b, "risk_pct": risk, "primary": primary, "verdict": "not_attempted",
                          "error": [x["error"] for x in real + null if "error" in x][:1]})
            continue
        evs = [x["ev"] for x in real]
        ev_null = st.fmean(x["ev"] for x in null)
        lo = edges[b].get("ci_lo")
        buyable = min(evs) > 0 and st.fmean(evs) > ev_null and lo is not None and lo > 0
        table.append({"ruleset": rs, "book": b, "risk_pct": risk, "primary": primary, "fee_usd": real[0]["fee"],
                      "ev_6m_mean": round(st.fmean(evs), 2), "ev_6m_min": round(min(evs), 2),
                      "ev_6m_null_mean": round(ev_null, 2),
                      "ev_6m_with_rebuy_mean": round(st.fmean(x["ev_rebuy_6m"] for x in real), 2),
                      "p_pass_eval": round(st.fmean(x["p_pass_eval"] for x in real), 4),
                      "p_breach": round(st.fmean(x["p_breach"] for x in real), 4),
                      "trades_per_life": real[0].get("trades_per_life"), "edge_ci_lo": lo,
                      "verdict": ("BUYABLE" if buyable else "NOT_BUYABLE") if primary else "descriptive_only"})
    table.sort(key=lambda r: (not r["primary"], -(r.get("ev_6m_mean") or -1e9)))
    verdict = {"rule_id": rule["rule_id"], "rule_file": str(RULE.relative_to(REPO)),
               "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "population": {"window_start": sim["window_start"], "per_leg": per_leg},
               "book_edges": edges, "table": table,
               "any_buyable": any(r.get("verdict") == "BUYABLE" for r in table)}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    print(json.dumps({"any_buyable": verdict["any_buyable"], "book_edges": edges,
                      "table": [{k: r.get(k) for k in ("ruleset", "book", "risk_pct", "ev_6m_mean", "ev_6m_min",
                                                        "ev_6m_null_mean", "p_pass_eval", "p_breach", "verdict")}
                                for r in table]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
