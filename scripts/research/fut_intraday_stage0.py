#!/usr/bin/env python3
# wiring: research/queue/RQ-20261112-09d2-04 via .github/workflows/research-script-run.yml
"""Stage 0 of ONE declared intraday leg, config-exact, on several futures instruments at a
session-flat prop venue's per-contract costs (FUT-INTRADAY-DUKA-LANE, 2026-11-12).

One ``exit_lever_ablation.py --grade stage0`` run per instrument (the leg's config with only
``symbols[0]`` replaced, the ablation's ``--symbol`` twin), each with the harness's session-flat
overlay (``--session-flat-et``) and per-contract cost arm (``--contract-cost-usd-rt`` /
``--point-value`` / ``--tick-size`` / ``--slip-ticks-per-fill``), graded by the ablation's
extended stage0 (fixed holdout boundary, calendar-year folds, discovery CI clause). The rule's
thresholds are the UNIT's, passed as flags.

``--instrument SYM:COMMISSION_USD_RT:POINT_VALUE:TICK_SIZE`` (repeatable).

Per-instrument verdicts are the rule's; the RUN verdict only rolls them up:
  pass           iff >= 1 instrument passes (each pass is named);
  fail           iff every instrument fails;
  indeterminate  otherwise (no pass, >= 1 indeterminate);
  read_state producer_failed (verdict indeterminate) iff any instrument's run produced no verdict.

Tier-1 research tooling: public candles (dukascopy), writes only under --out. No live path, no
config write, no order.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
ABL = REPO / "scripts" / "research" / "exit_lever_ablation.py"


def parse_instrument(spec: str) -> dict[str, Any]:
    parts = spec.split(":")
    if len(parts) != 4:
        raise ValueError(f"--instrument {spec!r} must be SYM:COMMISSION_USD_RT:POINT_VALUE:TICK_SIZE")
    sym, comm, pv, tick = parts
    out = {"symbol": sym.strip().upper(), "commission_usd_rt": float(comm), "point_value": float(pv),
           "tick_size": float(tick)}
    if not out["symbol"] or out["point_value"] <= 0 or out["tick_size"] <= 0 or out["commission_usd_rt"] < 0:
        raise ValueError(f"--instrument {spec!r}: empty symbol or non-positive point value / tick")
    return out


def ablation_argv(a: argparse.Namespace, inst: dict[str, Any], out: Path) -> list[str]:
    arm = (f"T=--session-flat-et={a.flat_et};--contract-cost-usd-rt={inst['commission_usd_rt']};"
           f"--point-value={inst['point_value']};--tick-size={inst['tick_size']};"
           f"--slip-ticks-per-fill={a.slip_ticks_per_fill}")
    argv = [sys.executable, str(ABL), "--leg", a.leg, "--symbol", inst["symbol"], "--arm", arm,
            "--days", str(a.days), "--start", a.start, "--end", a.end,
            "--non-crypto-source", a.non_crypto_source,
            "--grade", "stage0", "--baseline", "T", "--delta-r", "0",
            "--folds", str(a.folds), "--fold-majority", str(a.fold_majority), "--n-floor", str(a.n_floor),
            "--stage0-holdout-start", a.holdout_start, "--holdout-min-trades", str(a.holdout_min_trades),
            "--out", str(out)]
    if a.ci_z is not None:
        argv += ["--stage0-ci-z", str(a.ci_z)]
    if a.yearly_folds:
        argv.append("--stage0-yearly-folds")
    if a.data_dir:
        argv += ["--data-csv", str(Path(a.data_dir) / f"{inst['symbol']}.csv")]
    return argv


def roll_up(per: dict[str, dict[str, Any] | None]) -> tuple[str, str, str]:
    """(verdict, read_state, why) over per-instrument grades (None = that run produced no verdict). Pure."""
    missing = sorted(k for k, g in per.items() if g is None)
    if missing:
        return "indeterminate", "producer_failed", f"no verdict for {missing}"
    vs = {k: g["verdict"] for k, g in per.items()}
    passed = sorted(k for k, v in vs.items() if v == "pass")
    if passed:
        return "pass", "measured", f"PASS on {passed}; per instrument {vs}"
    if all(v == "fail" for v in vs.values()):
        return "fail", "measured", f"every instrument fails; per instrument {vs}"
    return "indeterminate", "measured", f"no pass, >= 1 indeterminate; per instrument {vs}"


def _self_test() -> int:
    ok = True

    def ck(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"  self-test {'ok  ' if cond else 'FAIL'}: {name}")
    P, F, I = {"verdict": "pass"}, {"verdict": "fail"}, {"verdict": "indeterminate"}
    ck("one pass -> pass", roll_up({"A": P, "B": F, "C": I})[0] == "pass")
    ck("all fail -> fail", roll_up({"A": F, "B": F})[0] == "fail")
    ck("fail + indeterminate -> indeterminate", roll_up({"A": F, "B": I})[0] == "indeterminate")
    ck("a missing run -> producer_failed, even beside a pass", roll_up({"A": P, "B": None})[1] == "producer_failed")
    ck("instrument spec parses", parse_instrument("mgc:2.12:10:0.1")["symbol"] == "MGC")
    try:
        parse_instrument("MGC:2.12:0:0.1")
        ck("a zero point value is refused", False)
    except ValueError:
        ck("a zero point value is refused", True)
    print(f"self-test: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (sys.argv[1:] if argv is None else argv):
        return _self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leg", required=True)
    ap.add_argument("--instrument", action="append", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--holdout-start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--days", type=int, required=True, help="trailing days to fetch (must cover --start)")
    ap.add_argument("--flat-et", required=True, help="HH:MM America/New_York")
    ap.add_argument("--slip-ticks-per-fill", type=float, default=1.0)
    ap.add_argument("--folds", type=int, required=True)
    ap.add_argument("--fold-majority", type=int, required=True)
    ap.add_argument("--yearly-folds", action="store_true")
    ap.add_argument("--n-floor", type=int, required=True)
    ap.add_argument("--ci-z", type=float, default=None)
    ap.add_argument("--holdout-min-trades", type=int, required=True)
    ap.add_argument("--non-crypto-source", choices=("auto", "dukascopy"), default="dukascopy")
    ap.add_argument("--data-dir", default=None, help="tests: <dir>/<SYM>.csv instead of a fetch")
    ap.add_argument("--research-unit", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    insts = [parse_instrument(s) for s in a.instrument]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    per: dict[str, dict[str, Any] | None] = {}
    rows: dict[str, Any] = {}
    for inst in insts:
        sub = out / inst["symbol"]
        argv_i = ablation_argv(a, inst, sub)
        print(f"[{inst['symbol']}] {' '.join(argv_i[1:])}", flush=True)
        r = subprocess.run(argv_i, cwd=str(REPO), capture_output=True, text=True, check=False)
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "run.log").write_text((r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-20000:]), encoding="utf-8")
        vpath = sub / "verdict.json"
        g = None
        if r.returncode == 0 and vpath.is_file():
            rec = json.loads(vpath.read_text(encoding="utf-8"))
            g = rec["measurement"]["grade"]
            arm = rec["measurement"]["arms"]["T"]
            rows[inst["symbol"]] = {"verdict": g["verdict"], "label": g.get("label"), "why": g.get("why"),
                                    "discovery": g.get("discovery"), "holdout": g.get("holdout"),
                                    "discovery_ci_lower_r_per_trade": g.get("discovery_ci_lower_r_per_trade"),
                                    "by_outcome": arm.get("by_outcome"), "session_flat": arm.get("session_flat"),
                                    "cost_stack": arm.get("cost_stack"), "feed": rec["measurement"]["window"]["feed"],
                                    "data_start": arm.get("data_start"), "data_end": arm.get("data_end")}
        else:
            rows[inst["symbol"]] = {"verdict": None, "exit_code": r.returncode, "stderr_tail": r.stderr[-2000:]}
        per[inst["symbol"]] = g
        print(f"[{inst['symbol']}] -> {rows[inst['symbol']].get('verdict')} {rows[inst['symbol']].get('why', '')}",
              flush=True)
    verdict, read_state, why = roll_up(per)
    n_disc = sum(int((g or {}).get("discovery", {}).get("n") or 0) for g in per.values())
    rec = {"verdict": verdict, "read_state": read_state,
           "population": (f"{a.leg} config-exact on {[i['symbol'] for i in insts]} (dukascopy proxies: see each feed), "
                          f"discovery [{a.start}, {a.holdout_start}) / holdout [{a.holdout_start}, {a.end}], "
                          f"session-flat at {a.flat_et} ET, per-contract commission + {a.slip_ticks_per_fill} tick "
                          "per market/stop fill; n = discovery trades summed over instruments"),
           "n": n_disc, "data_inputs": [],
           "measurement": {"leg": a.leg, "research_unit": a.research_unit, "why": why, "per_instrument": rows,
                           "instruments": insts, "roll_up": "pass iff >= 1 instrument passes; fail iff all fail; "
                                                            "else indeterminate"}}
    (out / "verdict.json").write_text(json.dumps(rec, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "read_state": read_state, "why": why}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
