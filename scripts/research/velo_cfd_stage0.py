#!/usr/bin/env python3
"""VELO-CFD-STAGE0 -- Stage 0 of the commodity legs on the SPOT/CFD series, at Velotrade's full cost stack, then the prop EV + survival bar.

Lane VELO-CFD-STAGE0 (2026-11-12), pipeline PI-20261112-D6UC5YT4-0001. The rule is registered BEFORE the run in
``comms/research/velo_cfd_stage0/rule.json`` (its own commit, pushed first); this script reads it, refuses to run without it, and names it
in the verdict. Memo context: docs/research/prop-frontier-2026-11-12.md (PR #25304). Result memo: docs/research/velo-cfd-stage0-2026-11-12.md.

What it does, in order:
  1. fetch (or reuse) the Dukascopy 1h series for XAG_USD / XAU_USD / WTI, clipped to the rule's window; record sha256 + row counts;
  2. per leg: the leg's EXACT config/strategies.yaml params -> harness flags via regime_debt_matrix.build_harness_cmd (the call the
     evidence builder makes), harness run at --fee-bps-roundtrip 0 so the ledger is gross; costs are applied once by prop_ev_sim.build_trades;
  3. leg verdict (rule.leg_rule) on 4 equal-count time folds, three cost arms (only ``primary`` grades);
  4. book verdict (rule.book_rule): prop_ev_sim path mode on Velotrade CLASSIC 1-Step, real vs zero-edge null, plus descriptive arms
     (PRO, 1% risk, 2025-06+ window, closed/eod/intraday-trailing what-ifs via the PROP-TRAILING-DD-SIM generalisation).

Offline research only: places no order, reads no account id or balance, changes no config. Imports regime_debt_matrix (research code) and
nothing from the live path.

# wiring: manual-only - a one-off lane screen (VELO-CFD-STAGE0); re-run by hand when the leg set, the cost stack or the Velotrade
#   instrument spec (PI-20261112-D6UC5YT4-0002) changes, per the memo's buy-point table.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics as st
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))
import prop_ev_sim as pes  # noqa: E402
import prop_gate as pg  # noqa: E402
import regime_debt_matrix as rdm  # noqa: E402

RULE = REPO / "comms/research/velo_cfd_stage0/rule.json"
DUKA = {"XAG_USD": "INSTRUMENT_FX_METALS_XAG_USD", "XAU_USD": "INSTRUMENT_FX_METALS_XAU_USD", "WTI": "INSTRUMENT_CMD_ENERGY_E_LIGHT"}
# leg -> instrument (rule.series.instruments)
LEG_INSTR = {"slv_trend_1h": "XAG_USD", "slv_pullback_1d": "XAG_USD", "gld_pullback_1h": "XAU_USD",
             "gld_pullback_1d": "XAU_USD", "uso_trend_1h": "WTI"}
CLASSIC = REPO / "config/prop_rulesets/velotrade_classic_1step.yaml"
PRO = REPO / "config/prop_rulesets/velotrade_pro_1step.yaml"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fetch(instr: str, workdir: Path, start: str, end: str) -> dict:
    out = workdir / f"{instr}_1h.csv"
    if not out.exists():
        r = subprocess.run([sys.executable, str(REPO / "scripts/ops/fetch_dukascopy_ohlcv.py"), "--instrument", DUKA[instr],
                            "--interval", "1h", "--start", start, "--output", str(out)], capture_output=True, text=True, check=False)
        if r.returncode != 0 or not out.exists():
            raise SystemExit(f"fetch {instr} failed: {(r.stderr or r.stdout)[-300:]}")
    df = pd.read_csv(out)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df = df[(ts >= pd.Timestamp(start, tz="UTC")) & (ts < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))]
    clip = workdir / f"{instr}_1h_clip.csv"
    df.to_csv(clip, index=False)
    return {"path": clip, "rows": len(df), "first": str(df["timestamp"].iloc[0]), "last": str(df["timestamp"].iloc[-1]),
            "sha256": sha(clip), "dukascopy_instrument": DUKA[instr]}


def run_leg(leg: str, cfg: dict, data: dict, workdir: Path) -> dict:
    harness = rdm.classify(cfg)
    if harness is None:
        return {"state": "producer_failed", "error": "classify() routes nothing"}
    emit, jout = workdir / f"{leg}__trades.jsonl", workdir / f"{leg}__bt.json"
    argv, faithful, omitted = rdm.build_harness_cmd(leg, cfg, harness, str(data["path"]), cfg["timeframe"], str(emit), str(jout),
                                                   fee_override=0.0)
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not emit.exists():
        return {"state": "producer_failed", "error": (r.stderr or r.stdout)[-400:], "argv": argv[1:]}
    rows = [json.loads(x) for x in emit.read_text().splitlines() if x.strip()]
    rows = [x for x in rows if x.get("exit_time")]
    return {"state": "measured", "harness": harness, "faithful": faithful, "omitted_levers": omitted, "rows": rows, "ledger": emit,
            "argv": argv[1:]}


def costs(c: dict) -> pes.CostConfig:
    return pes.CostConfig(mode="breakout", commission_bps_rt=c["commission_bps_rt"], slippage_bps_rt=c["slippage_bps_rt"],
                          swap_daily=c["swap_daily"], swap_model=c["swap_model"])


def net_r(rows: list[dict], cc: pes.CostConfig) -> list[float]:
    trades, _, _ = pes.build_trades({"x": rows}, cc)
    return [t.net_r for t in trades]


def folds4(rows: list[dict], cc: pes.CostConfig) -> list[float]:
    """Net R per equal-count time fold (rows ordered by entry_time) -- the harness_timefolds convention."""
    rows = sorted(rows, key=lambda r: str(r["entry_time"]))
    n = len(rows)
    size = max(1, n // 4)
    out = []
    for i in range(4):
        blk = rows[i * size: (n if i == 3 else (i + 1) * size)]
        out.append(round(sum(net_r(blk, cc)), 4) if blk else 0.0)
    return out


def leg_verdict(rows: list[dict], arms: dict[str, pes.CostConfig]) -> dict:
    out: dict = {"n": len(rows)}
    for a, cc in arms.items():
        nr = net_r(rows, cc) if rows else []
        out[a] = {"net_r_total": round(sum(nr), 4), "mean_r": round(st.fmean(nr), 4) if nr else None,
                  "folds_net_r": folds4(rows, cc) if rows else [], **(pg.edge_ci(nr) if nr else {})}
    p = out["primary"]
    if len(rows) < 30:
        out["verdict"] = "INDETERMINATE"
    else:
        npos = sum(1 for f in p["folds_net_r"] if f > 0)
        out["folds_positive_primary"] = npos
        out["verdict"] = "PASS" if (p["net_r_total"] > 0 and npos >= 3) else "FAIL"
        out["robust"] = bool(out["verdict"] == "PASS" and all(out[a]["net_r_total"] > 0 for a in arms if a != "primary"))
    return out


def demean(rows: list[dict], cc: pes.CostConfig) -> list[dict]:
    m = st.fmean(net_r(rows, cc))
    res = []
    for r in rows:
        r = dict(r)
        r["gross_r"] = float(r["gross_r"]) - m
        if r.get("mfe_r") is not None:
            r["mfe_r"] = max(float(r["mfe_r"]), r["gross_r"])
        res.append(r)
    return res


def ruleset_variant(base: Path, dd_type: str | None, workdir: Path) -> Path:
    if dd_type is None:
        return base
    d = yaml.safe_load(base.read_text())
    d["limits"]["drawdown_type"] = dd_type
    d["limits"]["trailing_lock_buffer_pct"] = 0.01
    d["limits"]["trailing_lock_offset_usd"] = 0.0
    p = workdir / f"{base.stem}__{dd_type}.yaml"
    p.write_text(yaml.safe_dump(d))
    return p


def cell(rs: Path, legs: dict[str, Path], seed: int, risk: float, c: dict, sim: dict, out: Path) -> dict:
    cmd = [sys.executable, str(REPO / "scripts/research/prop_ev_sim.py")]
    for k, p in legs.items():
        cmd += ["--trades", f"{k}={p}", "--lev-cap", f"{k}={sim['lev_cap']}"]
    cmd += ["--ruleset", str(rs), "--costs", "breakout", "--commission-bps-rt", str(c["commission_bps_rt"]),
            "--slippage-bps-rt", str(c["slippage_bps_rt"]), "--swap-daily", str(c["swap_daily"]), "--swap-model", c["swap_model"],
            "--funded-start", "fresh", "--sizing", "start", "--risk-pct", str(risk), "--dd-switch-frac", str(sim["dd_switch_frac"]),
            "--horizon-days", str(sim["horizon_days"]), "--seed", str(seed), "--lives", str(sim["lives"]),
            "--outer", "2", "--lives-per-outer", str(sim["lives"] // 10), "--modes", "path", "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3000, check=False)
    if r.returncode != 0 or not out.exists():
        return {"error": (r.stderr or r.stdout)[-500:]}
    p = json.loads(out.read_text())["results"]["path"]
    return {"ev": p["ev_net_usd_per_life"], "p_pass_eval": p["p_pass_eval"], "p_breach_dd": p["p_breach_max_dd"],
            "p_breach_daily": p["p_breach_daily_loss"], "fee": p["account_fee_usd"], "trades_per_life": p.get("mean_trades_per_life"),
            "death_causes": p.get("death_causes")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="evidence dir (committed): ledgers + verdict.json")
    ap.add_argument("--workdir", required=True, help="scratch: candle CSVs, harness json, sim cells (not committed)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--legs-only", action="store_true", help="stop after the leg verdicts (no book simulation)")
    a = ap.parse_args(argv)
    if not RULE.exists():
        raise SystemExit("rule not registered: comms/research/velo_cfd_stage0/rule.json")
    rule = json.loads(RULE.read_text())
    out, wd = Path(a.out), Path(a.workdir)
    (out / "ledgers").mkdir(parents=True, exist_ok=True)
    wd.mkdir(parents=True, exist_ok=True)
    start, end = "2019-01-01", "2026-10-31"
    yml = yaml.safe_load((REPO / "config/strategies.yaml").read_text())
    blk = yml.get("strategies", yml)
    legs = rule["legs"]["decisive"] + rule["legs"]["descriptive"]
    data = {i: fetch(i, wd, start, end) for i in sorted(set(LEG_INSTR[leg] for leg in legs))}
    arms = {"primary": costs(rule["costs"]["primary"]), "stress_ev6m_commission": costs(rule["costs"]["stress_ev6m_commission"]),
            "stress_wide_spread": costs(rule["costs"]["stress_wide_spread"])}
    produced, verdicts = {}, {}
    for leg in legs:
        cfg = blk[leg]
        prod = run_leg(leg, cfg, data[LEG_INSTR[leg]], wd)
        produced[leg] = prod
        if prod["state"] != "measured":
            verdicts[leg] = {"verdict": "INDETERMINATE", "read_state": "producer_failed", "error": prod.get("error")}
            print(f"{leg}: producer_failed {prod.get('error','')[:200]}", file=sys.stderr)
            continue
        verdicts[leg] = {"instrument": LEG_INSTR[leg], "harness": prod["harness"], "fidelity": "faithful" if prod["faithful"] else "approximate",
                         "omitted_levers": prod["omitted_levers"], "harness_argv": prod["argv"], **leg_verdict(prod["rows"], arms)}
        (out / "ledgers" / f"{leg}__trades.jsonl").write_text(prod["ledger"].read_text())
        print(f"{leg}: n={verdicts[leg]['n']} primary net_r={verdicts[leg]['primary']['net_r_total']} "
              f"folds={verdicts[leg]['primary']['folds_net_r']} -> {verdicts[leg]['verdict']}", file=sys.stderr)
    dec = rule["legs"]["decisive"]
    book_legs = [leg for leg in dec if verdicts[leg]["verdict"] == "PASS"]
    robust_legs = [leg for leg in book_legs if verdicts[leg].get("robust")]
    all5 = [leg for leg in legs if verdicts[leg]["verdict"] == "PASS"]
    # UNFILTERED_5 is NOT a rule arm: the five legs regardless of verdict, added post-hoc (recorded as such) so the new simulator and the
    # trailing what-ifs still say something when the registered book is empty.
    books = {"VELO_CFD": book_legs, "VELO_CFD_ROBUST": robust_legs, "ALL5": all5, "UNFILTERED_5": list(legs)}
    edges = {b: pg.edge_ci([x for leg in ls for x in net_r(produced[leg]["rows"], arms["primary"])]) if ls else {"n": 0}
             for b, ls in books.items()}
    verdict = {"rule_id": rule["rule_id"], "rule_file": str(RULE.relative_to(REPO)),
               "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "series": {k: {kk: (str(vv) if kk == "path" else vv) for kk, vv in v.items() if kk != "path"} for k, v in data.items()},
               "legs": verdicts, "books": books, "book_edges": edges}
    if a.legs_only:
        (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
        print(json.dumps({k: verdicts[k].get("verdict") for k in verdicts}))
        return 0

    c = rule["costs"]["primary"]
    simcfg = {"horizon_days": 182, "lives": 1000, "dd_switch_frac": 0.8, "lev_cap": 5}
    tmp = Path(tempfile.mkdtemp(prefix="velocfd-", dir=wd))
    paths: dict = {}
    for leg in set(x for ls in books.values() for x in ls):
        for tag, win in (("full", None), ("w2025", "2025-06-01")):
            rows = [r for r in produced[leg]["rows"] if win is None or r["entry_time"] >= win]
            if not rows:
                continue
            p = tmp / f"{leg}.{tag}.jsonl"
            p.write_text("".join(json.dumps(x) + "\n" for x in rows))
            q = tmp / f"{leg}.{tag}.null.jsonl"
            q.write_text("".join(json.dumps(x) + "\n" for x in demean(rows, arms["primary"])))
            paths[(leg, tag, "real")], paths[(leg, tag, "null")] = p, q
    jobs = []  # (name, ruleset_path, book, window, risk, seed, arm)
    seeds = (1, 2, 3)

    def add(name, rs, book, win, risk):
        ls = [leg for leg in books[book] if (leg, win, "real") in paths]
        if not ls:
            return
        for s in seeds:
            for arm in ("real", "null"):
                jobs.append((name, rs, book, win, risk, s, arm, {leg: paths[(leg, win, arm)] for leg in ls}))

    add("graded_classic", CLASSIC, "VELO_CFD", "full", 0.005)
    add("pro", PRO, "VELO_CFD", "full", 0.005)
    add("classic_risk1pct", CLASSIC, "VELO_CFD", "full", 0.01)
    add("classic_w2025", CLASSIC, "VELO_CFD", "w2025", 0.005)
    add("classic_robust", CLASSIC, "VELO_CFD_ROBUST", "full", 0.005)
    add("classic_all5", CLASSIC, "ALL5", "full", 0.005)
    add("posthoc_unfiltered5_classic", CLASSIC, "UNFILTERED_5", "full", 0.005)
    add("posthoc_unfiltered5_classic_w2025", CLASSIC, "UNFILTERED_5", "w2025", 0.005)
    wb = "VELO_CFD" if book_legs else "UNFILTERED_5"
    for dt in ("closed_trailing", "eod_trailing", "intraday_trailing"):
        add(f"whatif_{wb}_{dt}", ruleset_variant(CLASSIC, dt, tmp), wb, "full", 0.005)

    def run(j):
        name, rs, book, win, risk, s, arm, lg = j
        return (name, book, win, risk, s, arm), cell(rs, lg, s, risk, c, simcfg, tmp / f"{name}__{book}__{win}__s{s}__{arm}.json")

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(run, jobs))
    by: dict = {}
    for (name, book, win, risk, s, arm), r in res:
        by.setdefault((name, book, win, risk), {}).setdefault(arm, []).append(r)
    table = []
    for (name, book, win, risk), d in by.items():
        real, null = d["real"], d["null"]
        row = {"cell": name, "book": book, "window": win, "risk_pct": risk, "legs": books[book]}
        if any("error" in x for x in real + null):
            row.update({"verdict": "not_attempted", "error": [x["error"] for x in real + null if "error" in x][:1]})
        else:
            evs = [x["ev"] for x in real]
            pb = [x["p_breach_dd"] + x["p_breach_daily"] for x in real]
            row.update({"fee_usd": real[0]["fee"], "ev_mean": round(st.fmean(evs), 2), "ev_min": round(min(evs), 2),
                        "ev_null_mean": round(st.fmean(x["ev"] for x in null), 2),
                        "p_pass_eval": round(st.fmean(x["p_pass_eval"] for x in real), 4),
                        "p_breach_any_mean": round(st.fmean(pb), 4), "trades_per_life": real[0].get("trades_per_life"),
                        "death_causes_seed1": real[0].get("death_causes")})
        table.append(row)
    g = next((r for r in table if r["cell"] == "graded_classic"), None)
    lo = edges["VELO_CFD"].get("ci_lo")
    if not book_legs:
        buy, why = "NOT_BUYABLE", {"(1)_ge2_pass_legs": False, "note": "no decisive leg PASSed Stage 0 on the CFD series; the registered book is empty"}
    elif g is None or g.get("verdict") == "not_attempted":
        buy, why = "NOT_ATTEMPTED", {"error": "graded cell missing or errored"}
    else:
        conds = {"(1)_ge2_pass_legs": len(book_legs) >= 2, "(2)_min_seed_ev_gt_0": g["ev_min"] > 0,
                 "(3)_mean_ev_gt_null": g["ev_mean"] > g["ev_null_mean"], "(4)_book_ci_lo_gt_0": lo is not None and lo > 0,
                 "(5)_p_breach_le_0.25": g["p_breach_any_mean"] <= 0.25}
        buy, why = ("BUYABLE" if all(conds.values()) else "NOT_BUYABLE"), conds
    verdict.update({"book_cells": table, "buy_verdict": buy, "buy_conditions": why, "graded_cell": g})
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
    print(json.dumps({"legs": {k: verdicts[k].get("verdict") for k in verdicts}, "books": books, "buy_verdict": buy, "conditions": why,
                      "graded": g}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
