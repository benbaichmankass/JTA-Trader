#!/usr/bin/env python3
# wiring: research/programmes/05-prop.yaml (nodes P5-MLDIAG-DECOMP / -RISKCURVE / -MINEDGE; ML-PROP-ITERATE)
"""Why does ml_entry fail the prop gate on ETH+SOL, and what lever (sizing / selection / a prop-specific model) could change that?

Three read-only sections on the ml_entry v1 ETH+SOL gate ledger (n=381, held-out 2025-10-01..2026-09-30; shape in
docs/research/ml-entry-prop-gate-2026-11-02/ledgers/). They measure; they register no pass bar and change no rule:
  decomp   mean net R (and 95% CI, trades independent) by symbol, side, UTC hour block, exit reason, and -- when the ledger carries
           `pred_net_r` / `ret_168` / `vol_ratio` (build_ledger.py --enrich) -- by tau-threshold quantile, trend and vol tercile; plus the
           firm cost stack split into commission / slippage / swap (mean R each, and net R with each removed).
  risk     p_breach (eval), EV and EV% vs per-trade risk_pct on each firm (prop_ev_sim path mode, same cell params as the gate).
  minedge  the gross edge shifted in so mean net R = e: EV and B vs e per firm; the smallest e on the grid at which the registered V2
           bar (median and worst seed B < c, EV > 0) holds, and the e that gives the CI lower bound 0 at this n.
Every section carries read_state: ok | needs_enriched_ledger:<fields> | not_run.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import statistics as st
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prop_ev_sim as pes
import prop_gate as G

DEFAULT_LEDGER = REPO / "docs/research/ml-entry-prop-gate-2026-11-02/ledgers/ml_entry_ethsol.jsonl"
RISK_GRID = (0.001, 0.0015, 0.0025, 0.0035, 0.005, 0.0075, 0.01)
EDGE_GRID = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20)


def ci(xs):
    e = G.edge_ci(xs)
    return {"n": e["n"], "mean_r": e["mean_r"], "ci_lo": e["ci_lo"], "ci_hi": e["ci_hi"]}


def per_row(rows, acct, arm, **zero):
    c = G.arm_costs(acct, arm)
    c = dataclasses.replace(c, **zero) if zero else c
    out = []
    for r in rows:
        a, b = pes._parse_ts(r["entry_time"]), pes._parse_ts(r["exit_time"])
        cost = pes.trade_cost_r(r, c, a, b)
        out.append((float(r["gross_r"]) - cost, cost))
    return out


def group(rows, nets, keyf):
    g = {}
    for r, n in zip(rows, nets):
        g.setdefault(keyf(r), []).append(n)
    return {str(k): ci(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def terciles(vals):
    s = sorted(vals)
    return s[len(s) // 3], s[2 * len(s) // 3]


def decomp(rows):
    need = [f for f in ("pred_net_r", "ret_168", "vol_ratio") if f not in rows[0]]
    out = {"read_state": "ok" if not need else f"needs_enriched_ledger:{','.join(need)} (symbol/side/hour/exit/cost parts are ok)", "firms": {}}
    for acct in G.SIM:
        pr = per_row(rows, acct, "ven")
        nets = [n for n, _ in pr]
        d = {"all": ci(nets),
             "by_symbol": group(rows, nets, lambda r: r["symbol"]),
             "by_side": group(rows, nets, lambda r: r["direction"]),
             "by_symbol_side": group(rows, nets, lambda r: f"{r['symbol']}/{r['direction']}"),
             "by_hour_block_utc": group(rows, nets, lambda r: f"{int(str(r['entry_time'])[11:13]) // 6 * 6:02d}h"),
             "by_exit_reason": group(rows, nets, lambda r: r["exit_reason"]),
             "by_month": group(rows, nets, lambda r: str(r["entry_time"])[:7])}
        gross = [float(r["gross_r"]) for r in rows]
        comp = {"gross_mean_r": round(st.fmean(gross), 5), "cost_mean_r": round(st.fmean(c for _, c in pr), 5)}
        for k in ("commission_bps_rt", "slippage_bps_rt", "swap_daily"):
            alt = [n for n, _ in per_row(rows, acct, "ven", **{k: 0.0})]
            comp[f"net_mean_r_without_{k}"] = round(st.fmean(alt), 5)
            comp[f"{k}_mean_r"] = round(st.fmean(alt) - st.fmean(nets), 5)
        d["cost_components"] = comp
        if "pred_net_r" in rows[0]:
            sc = [float(r["pred_net_r"]) for r in rows]
            qs = {f"pred_net_r>=p{q}": sorted(sc)[int(len(sc) * q / 100)] for q in (0, 25, 50, 75)}  # provenance: sc — scores of the ledger passed in, quantile thresholds computed over that same population
            d["by_tau_threshold"] = {k: ci([n for r, n in zip(rows, nets) if float(r["pred_net_r"]) >= thr]) | {"tau": round(thr, 5)} for k, thr in qs.items()}
        if "ret_168" in rows[0]:
            t1, t2 = terciles([abs(float(r["ret_168"])) for r in rows])
            d["by_trend_strength"] = group(rows, nets, lambda r, t1=t1, t2=t2: "low" if abs(float(r["ret_168"])) < t1 else ("mid" if abs(float(r["ret_168"])) < t2 else "high"))
            d["by_trend_alignment"] = group(rows, nets, lambda r: "with" if (float(r["ret_168"]) > 0) == (r["direction"] == "long") else "against")
        if "vol_ratio" in rows[0]:
            t1, t2 = terciles([float(r["vol_ratio"]) for r in rows])
            d["by_vol_ratio"] = group(rows, nets, lambda r, t1=t1, t2=t2: "low" if float(r["vol_ratio"]) < t1 else ("mid" if float(r["vol_ratio"]) < t2 else "high"))
        out["firms"][acct] = d
    return out


def sim(rows_path: Path, acct, arm, risk, seed, out: Path):
    if not out.exists():
        sm = G.SIM[acct]
        c, s, sw = G.CUR if arm == "cur" else sm["ven"]
        subprocess.run([sys.executable, str(REPO / "scripts/research/prop_ev_sim.py"), "--trades", f"ml-entry={rows_path}",
                        "--ruleset", str(REPO / f"config/prop_rulesets/{sm['rs']}.yaml"), "--costs", "breakout",
                        "--commission-bps-rt", str(c), "--slippage-bps-rt", str(s), "--swap-daily", str(sw), "--swap-model", "prorated",
                        "--funded-start", "fresh", "--lev-cap", f"ml-entry={G.lev_cap(acct, 'ml_entry')}", "--sizing", "start",
                        "--risk-pct", str(risk), "--dd-switch-frac", "0.8", "--seed", str(seed), "--lives", "1000", "--outer", "2",
                        "--lives-per-outer", "100", "--modes", "path", "--out", str(out)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(REPO))
    d = json.loads(out.read_text())
    p = d["results"]["path"]
    return {"ev": p["ev_net_usd_per_life"], "B": min(1.0, p["p_breach_max_dd_in_eval"] + p["p_breach_daily_loss_in_eval"]),
            "life": p["p_breach_max_dd"], "pass_eval": p["p_pass_eval"]}


def med(xs):
    return round(st.median(xs), 4)


def grid_section(rows, work: Path, jobs, seeds, kind):
    work.mkdir(parents=True, exist_ok=True)
    jobs_l = []
    for acct in G.SIM:
        net_mean = st.fmean(n for n, _ in per_row(rows, acct, "ven"))
        pts = RISK_GRID if kind == "risk" else EDGE_GRID
        for pt in pts:
            if kind == "risk":
                rp, rr = pt, rows
                tag = f"r{pt}"
            else:
                rp = G.SIM[acct]["risk"]
                rr = [dict(r, gross_r=float(r["gross_r"]) - net_mean + pt) for r in rows]
                tag = f"e{pt}"
            p = work / f"{kind}_{acct}_{tag}.jsonl"
            p.write_text("\n".join(json.dumps(dict(r, leg="ml-entry", strategy="ml-entry")) for r in rr) + "\n")
            for s in seeds:
                jobs_l.append((acct, pt, rp, s, p, work / f"{kind}_{acct}_{tag}_s{s}.json"))
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(lambda j: (j[0], j[1], j[3], sim(j[4], j[0], "ven", j[2], j[3], j[5])), jobs_l))
    out = {"read_state": "ok", "seeds": list(seeds), "firms": {}}
    for acct in G.SIM:
        size, c = G.ACCT[acct]
        pts = []
        for pt in (RISK_GRID if kind == "risk" else EDGE_GRID):
            xs = [r for a, p_, s, r in res if a == acct and p_ == pt]
            evs, Bs = [x["ev"] for x in xs], [x["B"] for x in xs]
            pts.append({("risk_pct" if kind == "risk" else "net_edge_r"): pt, "ev_median_usd": med(evs), "ev_worst_usd": round(min(evs), 2),
                        "ev_median_pct": round(100 * st.median(evs) / size, 3), "B_median": med(Bs), "B_worst": round(max(Bs), 4),
                        "ceiling": round(c, 3), "life_p_breach_median": med([x["life"] for x in xs]),
                        "p_pass_eval_median": med([x["pass_eval"] for x in xs]),
                        "v2_bar_holds": bool(st.median(Bs) < c and max(Bs) < c and st.median(evs) > 0 and min(evs) > 0)})
        f = {"points": pts}
        if kind == "risk":
            ok = [p for p in pts if p["B_worst"] < c and p["ev_worst_usd"] > 0]
            f["best_ev_risk_with_B_below_ceiling"] = max(ok, key=lambda p: p["ev_median_usd"])["risk_pct"] if ok else None
        else:
            hit = [p["net_edge_r"] for p in pts if p["v2_bar_holds"]]
            f["min_edge_r_on_grid_clearing_v2"] = min(hit) if hit else None
        out["firms"][acct] = f
    return out


def ci_edge_needed(rows):
    nets = [n for n, _ in per_row(rows, "breakout_2", "ven")]
    sd = st.stdev(nets)
    n = len(nets)
    return {"n": n, "sd_net_r": round(sd, 4), "true_mean_net_r_for_ci_lower_bound_zero_at_this_n": round(G.Z95 * sd / math.sqrt(n), 4),
            "n_needed_for_ci_lower_zero_at_edge": {str(e): math.ceil((G.Z95 * sd / e) ** 2) for e in (0.03, 0.05, 0.08, 0.10)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--enrich-build", action="store_true", help="first rebuild the ledger with pred_net_r/regime fields (build_ledger.py; keyless Binance Vision)")
    ap.add_argument("--sections", default="decomp,risk,minedge")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    led = Path(a.ledger)
    if a.enrich_build:
        b = out / "enriched"
        r = subprocess.run([sys.executable, str(REPO / "docs/research/ml-entry-prop-gate-2026-11-02/build_ledger.py"), str(b)], cwd=str(REPO), check=False)
        if r.returncode == 0 and (b / "ml_entry_ethsol.jsonl").exists():
            led = b / "ml_entry_ethsol.jsonl"
    rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    rows = [r for r in rows if r["symbol"] in ("ETHUSDT", "SOLUSDT")]
    secs = a.sections.split(",")
    seeds = [int(s) for s in a.seeds.split(",")]
    res = {"ledger": str(led), "n": len(rows), "population": "ml_entry v1 served ENTRY, extend-only TP, ETHUSDT+SOLUSDT, held-out 2025-10-01..2026-09-30",
           "enriched": "pred_net_r" in rows[0], "decomp": {"read_state": "not_run"}, "risk": {"read_state": "not_run"}, "minedge": {"read_state": "not_run"}}
    if "decomp" in secs:
        res["decomp"] = decomp(rows)
    if "risk" in secs:
        res["risk"] = grid_section(rows, out / "risk_work", a.jobs, seeds, "risk")
    if "minedge" in secs:
        res["minedge"] = grid_section(rows, out / "minedge_work", a.jobs, seeds, "edge")
        res["minedge"]["ci_clause"] = ci_edge_needed(rows)
    (out / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: (v.get("read_state") if isinstance(v, dict) else v) for k, v in res.items() if k in ("decomp", "risk", "minedge", "enriched", "n")}))


if __name__ == "__main__":
    main()
