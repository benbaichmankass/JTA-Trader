#!/usr/bin/env python3
# wiring: research-script-run - RQ-20261114-db1a-09 (eth_4h tp_r 4 prop EV re-run) dispatches it as its last command
"""Prop EV/survival A-vs-B for ONE leg: two trade ledgers of the same leg (arm A config-exact, arm B a candidate
change) scored by ``scripts/research/prop_ev_sim.py`` on every firm ruleset the leg trades, and graded as
NON-INFERIORITY (the prop superset rule: a change on a prop leg must not worsen its EV/survival on any firm).

Row RM-AM-ETH4H-ENTRYTP, manager 2026-11-14 14:05Z: after RQ-20261114-db1a-08 passed (tp_r 4 non-inferior on the
real-money cost stack), "a prop EV re-run (prop superset) before anything ships". Cell parameters are the ones the
2026-11-06 prop retest used (docs/research/prop-retest-2026-11-06/run_cells.sh, the 'cur' cost arm), so A here
reproduces that record's population on the same window.

THE RULE (registered in the calling unit before the run; this module only applies it), per account:
  ev    mean over seeds of B's ev_net_usd_per_life >= A's - ev_margin_frac x |A's|
  risk  mean over seeds of B's p_breach (max-DD + daily-loss) <= A's + breach_margin
  unit  pass iff both hold on EVERY account; fail iff any account fails; indeterminate iff any cell is missing or
        either ledger has fewer than n_floor rows.
Edits no config, roster or record; places no order. Writes <out>/verdict.json (E5 fields) and <out>/cells/.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
SIM = REPO / "scripts" / "research" / "prop_ev_sim.py"
# account -> (ruleset, risk_pct, lev_cap), the 2026-11-06 retest's cells for a non-sol leg; 'cur' cost arm
ACCOUNTS = {
    "breakout_2": ("breakout_turbo_1step", 0.0035, 5),
    "tradeify_1": ("tradeify_247_1step", 0.005, 5),
    "velotrade_1": ("velotrade_classic_1step", 0.005, 5),
}
COSTS = ("11.0", "3.0", "0.0003")  # commission bps rt, slippage bps rt, swap daily


def cell_argv(leg: str, trades: Path, account: str, seed: int, out: Path) -> List[str]:
    rs, risk, cap = ACCOUNTS[account]
    c, s, sw = COSTS
    return [sys.executable, str(SIM), "--trades", f"{leg}={trades}", "--ruleset", f"config/prop_rulesets/{rs}.yaml",
            "--costs", "breakout", "--commission-bps-rt", c, "--slippage-bps-rt", s, "--swap-daily", sw,
            "--swap-model", "prorated", "--funded-start", "fresh", "--lev-cap", f"{leg}={cap}", "--sizing", "start",
            "--risk-pct", str(risk), "--dd-switch-frac", "0.8", "--seed", str(seed), "--lives", "1000", "--outer", "2",
            "--lives-per-outer", "100", "--modes", "path", "--out", str(out)]


def run_cell(argv: List[str], out: Path) -> Optional[Dict[str, Any]]:
    r = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True, check=False)
    if r.returncode != 0 or not out.exists():
        return None
    res = (json.loads(out.read_text(encoding="utf-8")).get("results") or {}).get("path") or {}
    ev = res.get("ev_net_usd_per_life")
    if not isinstance(ev, (int, float)):
        return None
    return {"ev": float(ev), "p_breach": float(res.get("p_breach_max_dd") or 0.0) + float(res.get("p_breach_daily_loss") or 0.0),
            "p_alive": res.get("p_alive_at_horizon")}


def grade(cells: Dict[str, Dict[str, List[Optional[dict]]]], ev_margin_frac: float, breach_margin: float) -> Dict[str, Any]:
    per: Dict[str, Any] = {}
    missing = False
    for acct, arms in cells.items():
        if any(c is None for arm in arms.values() for c in arm):
            missing = True
            per[acct] = {"verdict": "indeterminate", "note": "a cell failed or wrote no result"}
            continue
        ev = {k: sum(c["ev"] for c in v) / len(v) for k, v in arms.items()}
        br = {k: sum(c["p_breach"] for c in v) / len(v) for k, v in arms.items()}
        ev_ok = ev["B"] >= ev["A"] - ev_margin_frac * abs(ev["A"])
        br_ok = br["B"] <= br["A"] + breach_margin
        per[acct] = {"verdict": "pass" if ev_ok and br_ok else "fail", "ev_A": round(ev["A"], 2), "ev_B": round(ev["B"], 2),
                     "p_breach_A": round(br["A"], 4), "p_breach_B": round(br["B"], 4), "ev_ok": ev_ok, "breach_ok": br_ok}
    if missing:
        v = "indeterminate"
    else:
        v = "pass" if all(p["verdict"] == "pass" for p in per.values()) else "fail"
    return {"verdict": v, "accounts": per}


def run(leg: str, a: Path, b: Path, out: Path, seeds: List[int], n_floor: int, ev_margin_frac: float,
        breach_margin: float, unit: str, rule: str, runner: Callable = run_cell) -> Dict[str, Any]:
    rows = {k: sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()) if p.exists() else 0
            for k, p in (("A", a), ("B", b))}
    pop = (f"{leg}: ledgers A={a.name} (n {rows['A']}) and B={b.name} (n {rows['B']}); prop_ev_sim path mode, seeds {seeds}, "
           f"1000 lives, 2026-11-06 retest cells ('cur' cost arm), accounts {sorted(ACCOUNTS)}")
    base = {"research_unit": unit, "rule": rule, "population": pop}
    if min(rows.values()) < n_floor:
        v = {"verdict": "indeterminate", "read_state": "producer_failed", "n": None,
             "note": f"a ledger has fewer than {n_floor} rows ({rows})"}
    else:
        (out / "cells").mkdir(parents=True, exist_ok=True)
        cells: Dict[str, Dict[str, List[Optional[dict]]]] = {}
        for acct in ACCOUNTS:
            cells[acct] = {}
            for arm, path in (("A", a), ("B", b)):
                cells[acct][arm] = []
                for s in seeds:
                    o = out / "cells" / f"{acct}__{arm}__s{s}.json"
                    cells[acct][arm].append(runner(cell_argv(leg, path, acct, s, o), o))
        g = grade(cells, ev_margin_frac, breach_margin)
        v = {"verdict": g["verdict"], "read_state": "measured" if g["verdict"] != "indeterminate" else "producer_failed",
             "n": rows["A"] + rows["B"], "accounts": g["accounts"],
             "note": "; ".join(f"{k} {p['verdict']}" + (f" ev {p['ev_A']}->{p['ev_B']} breach {p['p_breach_A']}->{p['p_breach_B']}"
                                                        if "ev_A" in p else "") for k, p in g["accounts"].items())}
    v.update(base)
    v["records"] = [{"leg": f"{leg}:{acct}", "verdict": p["verdict"], "read_state": v["read_state"], "n": v["n"],
                     "population": pop, "note": json.dumps(p, default=str)} for acct, p in (v.get("accounts") or {}).items()] or [
        {"leg": leg, "verdict": v["verdict"], "read_state": v["read_state"], "n": v["n"], "population": pop, "note": v.get("note")}]
    return v


def _self_test() -> int:
    import tempfile
    def fake(evA, evB, brA, brB):
        def runner(argv, out):
            arm = Path(out).name.split("__")[1]
            return {"ev": evA if arm == "A" else evB, "p_breach": brA if arm == "A" else brB, "p_alive": 0.5}
        return runner
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a, b = d / "a.jsonl", d / "b.jsonl"
        a.write_text("{}\n" * 40)
        b.write_text("{}\n" * 40)
        args = ("x", a, b, d / "o", [1, 2], 30, 0.10, 0.02, "U", "R")
        assert run(*args, runner=fake(100, 95, 0.30, 0.31))["verdict"] == "pass"
        assert run(*args, runner=fake(100, 85, 0.30, 0.30))["verdict"] == "fail"       # ev down > 10%
        assert run(*args, runner=fake(100, 100, 0.30, 0.33))["verdict"] == "fail"      # breach up > 0.02
        assert run(*args, runner=lambda argv, out: None)["verdict"] == "indeterminate"
        b.write_text("{}\n" * 10)
        assert run(*args, runner=fake(100, 100, 0.3, 0.3))["verdict"] == "indeterminate"  # under the n floor
    print("prop_ev_ab_grade self-test: ok")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--leg")
    ap.add_argument("--a-trades")
    ap.add_argument("--b-trades")
    ap.add_argument("--out")
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--n-floor", type=int, default=60)
    ap.add_argument("--ev-margin-frac", type=float, default=0.10)
    ap.add_argument("--breach-margin", type=float, default=0.02)
    ap.add_argument("--unit")
    ap.add_argument("--rule")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not all((a.leg, a.a_trades, a.b_trades, a.out, a.unit, a.rule)):
        ap.error("--leg, --a-trades, --b-trades, --out, --unit and --rule are required")
    out = Path(a.out)
    v = run(a.leg, Path(a.a_trades), Path(a.b_trades), out, [int(s) for s in a.seeds.split(",")], a.n_floor,
            a.ev_margin_frac, a.breach_margin, a.unit, a.rule)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"unit: {v['verdict']} (n {v['n']}) {v.get('note')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
