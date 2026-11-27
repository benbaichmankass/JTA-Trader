#!/usr/bin/env python3
# wiring: manual-only - run through units RQ-20261101-5e01-12/-13/-14/-15 once the manager moves them out of research/queue/blocked/ (row STRUCTURE-FAMILY-EXPANSION); no schedule runs it
"""Structure-exit ablation over a FAMILY of legs (row STRUCTURE-FAMILY-EXPANSION, units RQ-20261101-5e01-12..15).

``exit_lever_ablation.py --leg`` takes ONE ``config/strategies.yaml`` key, so a unit that names a family cannot run as authored. This
expands the family at run time and runs ``exit_lever_ablation`` once per leg with the SAME arms, window, grade and bars as the single-leg
units RQ-20261101-5e01-01..08 (A hold-to-bracket; S3/S5/S8 = ``--structure-exit=pivot=N``; replace grade, 6 folds, majority 4, n floor 39).

LEG LIST IS RE-PARSED, NEVER QUOTED. A leg is in the family when it is on the ``--account`` rosters (``config/accounts.yaml``, the
``strategies:`` list) and its ``config/strategies.yaml`` key matches the family selector:
  trend_donchian  key starts with ``trend_donchian``      pullback  ``pullback`` in the key
  ict_scalp       key starts with ``ict_scalp``           remaining every other rostered leg (the families above are excluded)
COVERAGE. ``--structure-exit`` exists only on backtest_trend.py and backtest_pullback.py. A leg whose harness (``regime_debt_matrix.classify``)
is anything else, or none (an ML head or desk leg with no harness), is LISTED under ``not_covered`` with its harness, never run and never dropped.

OUTPUT. ``<out>/<leg>/`` is one exit_lever_ablation run (its own verdict.json). ``<out>/verdict.json`` is the script_run contract with one
``records`` row per COVERED leg (the unit's rule is per leg). The top-level verdict is a roll-up for the listing only: ``pass`` if any leg
passes, else ``indeterminate`` if any is, else ``fail``; ``not_applicable`` with no covered leg. A pooled-across-legs test is NOT run here:
the units' rule grades per leg. Every count is over the printed leg list. A leg that errors is recorded ``producer_failed`` and the loop
continues (no pipeline halts on one item).

    python3 scripts/research/structure_family_run.py --family trend_donchian --account bybit_1 --list
    python3 scripts/research/structure_family_run.py --family pullback --account bybit_1 --out DIR
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))

FAMILIES = ("trend_donchian", "pullback", "ict_scalp", "remaining")
ARMS_HARNESS = ("trend", "pullback")      # the harnesses that carry --structure-exit
CRYPTO_WINDOW = ("2020-07-01", "2026-10-15 23:59")
NONCRYPTO_WINDOW = ("2021-07-01", "2026-10-15 23:59")


def _match(family: str, leg: str) -> bool:
    if family == "trend_donchian":
        return leg.startswith("trend_donchian")
    if family == "pullback":
        return "pullback" in leg
    if family == "ict_scalp":
        return leg.startswith("ict_scalp")
    return not any(_match(f, leg) for f in ("trend_donchian", "pullback", "ict_scalp"))


def expand(family: str, accounts: list[str], strategies: dict, accounts_cfg: dict) -> list[str]:
    """Rostered legs of ``family`` (de-duplicated, roster order), re-parsed from the two configs."""
    seen: list[str] = []
    for acct in accounts:
        for leg in (accounts_cfg.get(acct) or {}).get("strategies") or []:
            if leg in strategies and leg not in seen and _match(family, leg):
                seen.append(leg)
    return seen


def harness_of(cfg: dict) -> str | None:
    import regime_debt_matrix as rdm  # noqa: PLC0415 -- heavy import, only when a leg is classified

    return rdm.classify(cfg)


def is_crypto(cfg: dict) -> bool:
    syms = cfg.get("symbols") or []
    return bool(syms) and all(str(s).upper().endswith("USDT") for s in syms)


def leg_argv(leg: str, cfg: dict, out: Path) -> list[str]:
    start, end = CRYPTO_WINDOW if is_crypto(cfg) else NONCRYPTO_WINDOW
    argv = [sys.executable, str(REPO / "scripts" / "research" / "exit_lever_ablation.py"), "--leg", leg,
            "--arm", "A=", "--arm", "S3=--structure-exit=pivot=3", "--arm", "S5=--structure-exit=pivot=5",
            "--arm", "S8=--structure-exit=pivot=8", "--days", "2330"]
    if not is_crypto(cfg):
        argv += ["--non-crypto-source", "dukascopy"]
    argv += ["--start", start, "--end", end, "--grade", "replace", "--baseline", "A", "--delta-r", "0",
             "--delta-r-per-trade", "0.02", "--folds", "6", "--fold-majority", "4", "--dd-tol-frac", "0.35",
             "--n-floor", "39", "--out", str(out)]
    return argv


def plan(family: str, accounts: list[str], strategies: dict, accounts_cfg: dict, classify=harness_of) -> dict[str, Any]:
    legs = expand(family, accounts, strategies, accounts_cfg)
    covered, not_covered = [], []
    for leg in legs:
        h = classify(strategies[leg])
        (covered if h in ARMS_HARNESS else not_covered).append({"leg": leg, "harness": h})
    return {"family": family, "accounts": accounts, "legs": legs, "covered": covered, "not_covered": not_covered}


def roll_up(records: list[dict]) -> str:
    vs = [str(r.get("verdict")) for r in records]
    if not vs:
        return "not_applicable"
    if "pass" in vs:
        return "pass"
    if "indeterminate" in vs or "not_applicable" in vs:
        return "indeterminate"
    return "fail"


def run_leg(leg: str, cfg: dict, out: Path, timeout_s: int) -> dict[str, Any]:
    d = out / leg
    d.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(leg_argv(leg, cfg, d), capture_output=True, text=True, timeout=timeout_s, check=False)
        (d / "stdout.log").write_text(r.stdout[-20000:], encoding="utf-8")
        (d / "stderr.log").write_text(r.stderr[-20000:], encoding="utf-8")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"leg": leg, "verdict": "not_applicable", "read_state": "producer_failed", "note": f"timed out after {timeout_s}s"}
    vp = d / "verdict.json"
    if rc != 0 or not vp.is_file():
        return {"leg": leg, "verdict": "not_applicable", "read_state": "producer_failed",
                "note": f"exit_lever_ablation exit {rc}; {'no verdict.json' if not vp.is_file() else 'verdict.json present'}"}
    try:
        rec = json.loads(vp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"leg": leg, "verdict": "not_applicable", "read_state": "producer_failed", "note": f"verdict.json unreadable: {type(exc).__name__}"}
    return {"leg": leg, **rec}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", required=True, choices=FAMILIES)
    ap.add_argument("--account", action="append", default=None, help="roster account (repeatable); default bybit_1")
    ap.add_argument("--out", default="/tmp/structure_family")
    ap.add_argument("--list", action="store_true", help="print the expanded leg list and coverage, run nothing")
    ap.add_argument("--leg-timeout-minutes", type=int, default=45)
    a = ap.parse_args(argv)
    accounts = a.account or ["bybit_1"]
    st = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text(encoding="utf-8"))
    st = st.get("strategies", st)
    from src.config.accounts_loader import load_accounts_dict
    ac = load_accounts_dict()
    p = plan(a.family, accounts, st, ac)
    print(json.dumps({k: v for k, v in p.items() if k != "legs"} | {"n_legs": len(p["legs"]), "n_covered": len(p["covered"]),
                                                                  "n_not_covered": len(p["not_covered"])}, indent=1))
    if a.list:
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for c in p["covered"]:
        rec = run_leg(c["leg"], st[c["leg"]], out, a.leg_timeout_minutes * 60)
        print(c["leg"], rec.get("verdict"), flush=True)
        records.append(rec)
    verdict = roll_up(records)
    graded = [r for r in records if r.get("read_state") != "producer_failed"]
    top = {"verdict": verdict, "read_state": "measured" if graded else "producer_failed",
           "population": f"family {a.family} on roster {accounts}: {len(p['legs'])} rostered legs re-parsed at run time, "
                         f"{len(p['covered'])} covered (harness carries --structure-exit), {len(p['not_covered'])} not covered",
           "n": len(graded), "records": records, "not_covered": p["not_covered"],
           "note": "per-leg grading (the units' rule is per leg); the top-level verdict is a listing roll-up, not a pooled test"}
    (out / "verdict.json").write_text(json.dumps(top, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "legs_graded": len(graded), "not_covered": len(p["not_covered"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
