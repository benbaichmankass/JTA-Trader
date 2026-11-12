#!/usr/bin/env python3
"""VELO-CFD-STAGE0 -- Stage 0 for the Velotrade commodity-CFD legs on the CFD underlying's own series.

Pipeline item PI-20261112-D6UC5YT4-0001, lane PROP-FRONTIER-RESEARCH. Rule registered BEFORE the run:
``comms/research/prop_frontier/velo_cfd_stage0_rule.json`` (this script refuses to run without it).

1. Fetch Dukascopy 1h bid bars (RTH-filtered) for each leg's CFD underlying (scripts/ops/fetch_dukascopy_ohlcv.py).
2. Run each leg through the SAME harness argv the Stage-0 evidence producer builds
   (``regime_debt_matrix.build_harness_cmd``), fee 0, leg parameters unchanged from config/strategies.yaml.
3. Re-cost every trade's gross R with the per-leg Velotrade stack (commission + slippage + assumed spread +
   overnight fee per rollover) through ``prop_ev_sim.build_trades``.
4. Grade each leg on the registered per-leg predicate; then, on the PASS legs, run the EV6M engine/predicate
   with the registered drop-one sensitivity check.

Offline research only: imports nothing from src/, places no order, changes no config.

# wiring: manual-only - a one-off pre-registered unit for PI-20261112-D6UC5YT4-0001; re-run by hand.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "scripts/ops"))
import fetch_dukascopy_ohlcv as fd  # noqa: E402
import prop_ev_sim as pes  # noqa: E402
import prop_frontier_ev6m as ev  # noqa: E402
import prop_gate as pg  # noqa: E402
import regime_debt_matrix as rdm  # noqa: E402

RULE = REPO / "comms/research/prop_frontier/velo_cfd_stage0_rule.json"
START, END = "2019-01-01", "2026-10-31"
Z_LEG = 2.241
EV_RULE = json.loads((REPO / "comms/research/prop_frontier/ev6m_rule.json").read_text())


def fetch_csv(inst: str, work: Path) -> Path:
    p = work / f"{inst}_1h_rth.csv"
    if p.exists():
        print(f"cached {p.name}", file=sys.stderr)
        return p
    s = datetime.fromisoformat(START).replace(tzinfo=timezone.utc)
    e = datetime.fromisoformat(END).replace(tzinfo=timezone.utc)
    df = fd.rth_filter(fd.fetch(inst, s, e, "1h"))
    df.to_csv(p, index=False)
    print(f"fetched {inst}: {len(df)} RTH 1h rows -> {p}", file=sys.stderr)
    return p


def run_leg(leg: str, cfg: dict, csv: Path, work: Path) -> list[dict]:
    harness = rdm.classify(cfg)
    emit, jout = work / f"{leg}__trades.jsonl", work / f"{leg}__bt.json"
    argv, faithful, omitted = rdm.build_harness_cmd(leg, cfg, harness, str(csv), cfg["timeframe"], str(emit), str(jout),
                                                    fee_override=0.0)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=1800, check=False, cwd=REPO)
    if r.returncode != 0 or not emit.exists():
        raise RuntimeError(f"harness failed for {leg}: {(r.stderr or r.stdout)[-500:]}")
    rows = [json.loads(x) for x in emit.read_text().splitlines() if x.strip()]
    return [x for x in rows if x.get("exit_time")], {"harness": harness, "faithful": faithful, "omitted_levers": omitted}


def leg_costs(rule: dict, leg: str) -> pes.CostConfig:
    c = rule["costs"]["per_leg_basis"][leg]
    return pes.CostConfig(mode="breakout", commission_bps_rt=c["commission_bps_rt"],
                          slippage_bps_rt=c["slippage_bps_rt"] + c["spread_bps_rt"], swap_daily=0.0005, swap_model="dxtrade")


def _t(x: str) -> datetime:
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def grade(rows: list[dict], cc: pes.CostConfig) -> dict:
    nr = [float(r["gross_r"]) - pes.trade_cost_r(r, cc, _t(r["entry_time"]), _t(r["exit_time"])) for r in rows]
    gross = [float(r["gross_r"]) for r in rows]
    by_year: dict[str, float] = {}
    for r, x in zip(rows, nr):
        by_year[r["entry_time"][:4]] = by_year.get(r["entry_time"][:4], 0.0) + x
    n = len(nr)
    mean = st.fmean(nr) if n else None
    se = st.stdev(nr) / math.sqrt(n) if n > 1 else None
    lo = (mean - Z_LEG * se) if se is not None else None
    pos = sum(1 for v in by_year.values() if v > 0)
    ok = n >= 30 and sum(nr) > 0 and by_year and pos / len(by_year) >= 0.6 and lo is not None and lo > 0
    return {"n": n, "gross_r": round(sum(gross), 3), "net_r": round(sum(nr), 3), "cost_r": round(sum(gross) - sum(nr), 3),
            "mean_net_r": round(mean, 4) if mean is not None else None, "ci_lo_z2241": round(lo, 4) if lo is not None else None,
            "years_positive": f"{pos}/{len(by_year)}", "net_r_by_year": {k: round(v, 3) for k, v in sorted(by_year.items())},
            "verdict": "PASS" if ok else "FAIL"}


def ev_book(name: str, legs: dict[str, Path], nulls: dict[str, Path], out: Path) -> dict:
    sim = dict(EV_RULE["sim"])
    res = {}
    for rs in EV_RULE["rulesets"]:
        real, null = [], []
        for s in sim["seeds"]:
            for arm, src, acc in (("real", legs, real), ("null", nulls, null)):
                # one cost stack per call: commodity legs share commission 2 / swap 5 bps; spread differs by <= 2 bps,
                # folded in at the book's WORST leg (5 bps) -- conservative.
                c = {"commission_bps_rt": 2.0, "slippage_bps_rt": 8.0, "swap_daily": 0.0005, "swap_model": "dxtrade"}
                acc.append(ev.cell(rs, src, s, sim["risk_pct_primary"], c, {**sim, "window_start": START},
                                   out / f"{name}__{rs}__{arm}__s{s}.json"))
        if any("error" in x for x in real + null):
            res[rs] = {"verdict": "not_attempted", "error": [x.get("error") for x in real + null if "error" in x][:1]}
            continue
        evs = [x["ev"] for x in real]
        res[rs] = {"ev_6m_mean": round(st.fmean(evs), 2), "ev_6m_min": round(min(evs), 2),
                   "ev_6m_null_mean": round(st.fmean(x["ev"] for x in null), 2),
                   "p_pass_eval": round(st.fmean(x["p_pass_eval"] for x in real), 4),
                   "p_breach": round(st.fmean(x["p_breach"] for x in real), 4),
                   "ev_ok": min(evs) > 0 and st.fmean(evs) > st.fmean(x["ev"] for x in null)}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", required=True, help="scratch dir for fetched bars and harness output (not committed)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not RULE.exists():
        raise SystemExit("rule not registered: comms/research/prop_frontier/velo_cfd_stage0_rule.json")
    rule = json.loads(RULE.read_text())
    S = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]
    work, out = Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    (out / "cells").mkdir(parents=True, exist_ok=True)
    legs = rule["population"]["legs"]
    per_leg, ledgers, nulls = {}, {}, {}
    for leg, spec in legs.items():
        cfg = S[leg]
        from build_strategy_evidence import config_fingerprint
        if config_fingerprint(cfg) != spec["config_fingerprint"]:
            per_leg[leg] = {"verdict": "INDETERMINATE", "error": "config changed since registration"}
            continue
        try:
            csv = fetch_csv(spec["cfd_underlying"], work)
            rows, meta = run_leg(leg, cfg, csv, work)
        except Exception as e:  # noqa: BLE001 - a leg-level failure is INDETERMINATE, never a FAIL
            per_leg[leg] = {"verdict": "INDETERMINATE", "error": f"{type(e).__name__}: {e}"[:500]}
            continue
        cc = leg_costs(rule, leg)
        g = grade(rows, cc)
        per_leg[leg] = {**g, **meta, "cfd_underlying": spec["cfd_underlying"]}
        if g["verdict"] == "PASS":
            ledgers[leg] = work / f"{leg}__spot.jsonl"
            ledgers[leg].write_text("".join(json.dumps(r) + "\n" for r in rows))
            nulls[leg] = work / f"{leg}__spot.null.jsonl"
            nulls[leg].write_text("".join(json.dumps(r) + "\n" for r in ev.demean(rows, cc)))
    book = {}
    if ledgers:
        cc_by = {k: leg_costs(rule, k) for k in ledgers}
        books = {"ALL": list(ledgers)}
        if len(ledgers) >= 2:
            books.update({f"DROP_{k}": [x for x in ledgers if x != k] for k in ledgers})
        with ThreadPoolExecutor(4) as ex:
            res = dict(zip(books, ex.map(lambda b: ev_book(b, {k: ledgers[k] for k in books[b]},
                                                           {k: nulls[k] for k in books[b]}, out / "cells"), books)))
        net_all = [x for k in ledgers
                   for x in ev.net_r([json.loads(y) for y in ledgers[k].read_text().splitlines() if y.strip()], cc_by[k])]
        edge = pg.edge_ci(net_all)
        for rs in EV_RULE["rulesets"]:
            full = res["ALL"].get(rs, {})
            drops = [res[b].get(rs, {}) for b in books if b != "ALL"]
            buyable = bool(full.get("ev_ok")) and edge.get("ci_lo") is not None and edge["ci_lo"] > 0 \
                and all(d.get("ev_6m_min", -1) > 0 and d.get("ev_ok") for d in drops)
            book[rs] = {"full_book": full, "drop_one": {b: res[b].get(rs) for b in books if b != "ALL"},
                        "book_edge": edge, "verdict": "BUYABLE" if buyable else "NOT_BUYABLE"}
    verdict = {"rule_id": rule["rule_id"], "rule_file": str(RULE.relative_to(REPO)),
               "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "window": [START, END], "per_leg": per_leg,
               "pass_legs": list(ledgers), "book": book or {"verdict": "NOT_APPLICABLE (no leg passed)"}}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1) + "\n")
    print(json.dumps({k: {kk: v.get(kk) for kk in ("n", "gross_r", "net_r", "mean_net_r", "ci_lo_z2241", "years_positive", "verdict", "error")}
                      for k, v in per_leg.items()}, indent=1))
    print(json.dumps({rs: b.get("verdict") for rs, b in book.items()} if book else "book: not applicable"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
