#!/usr/bin/env python3
# wiring: manual-only - run by units minted from programme-05 nodes (research/programmes/05-prop.yaml P5-MLV-GATE-*), a source this guard does not scan
# ruff: noqa: E402
"""Prop gate for ONE ML variant's ledger: RULE-P5-GATE-BRK-PER-LEG-V3, as registered in RQ-20261102-5e1a-01.

Re-runs exactly the harness of docs/research/ml-entry-prop-gate-2026-11-02/run_grade.py (prop_ev_sim path mode, 5 seeds x 1000
lives, configured risk_pct, dd switch 0.8, firm arm + current-stack arm, edge CI, zero-edge null) on a VARIANT's ledger
restricted to ETHUSDT+SOL USDT. Nothing is tuned here: the rule lives in scripts/research/prop_gate.py and is not changed.

Ledger: jsonl rows {symbol, direction, entry_time, exit_time, entry, sl, exit_reason, gross_r, mfe_r} (the ml_entry gate-ledger
shape). `--from-unit <RQ id>` finds `ledger_ethsol.jsonl` / `ledger.jsonl` under research/results/<id>/ or comms/research/<id>/**.
A variant that emitted no ledger is NOT graded: read_state `no_variant_ledger` + the missing piece, verdict INDETERMINATE
(never a silent PASS, never a FAIL). A PASS only yields a held Tier-3 roster-add PR (operator conditional approval 2026-11-02).
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prop_gate as G

SYMS = ("ETHUSDT", "SOLUSDT")
MISSING_PIECE = ("the variant's harness must emit its ETH+SOL trade ledger (gross_r per trade, shape of "
                 "docs/research/ml-entry-prop-gate-2026-11-02/ledgers/ml_entry_ethsol.jsonl) as ledger_ethsol.jsonl beside its result")


def find_ledger(unit: str, arm: str | None = None) -> Path | None:
    if arm:   # exit_lever_ablation arm book: comms/research/<unit>/<run>/arms/<label>__trades.jsonl (the gate input of a Donchian structure-exit arm)
        hits = sorted(glob.glob(str(REPO / f"comms/research/{unit}/**/arms/{arm}__trades.jsonl"), recursive=True))
        if hits:
            print(f"[find_ledger] arm {arm}: {len(hits)} candidate(s), using {hits[-1]}", file=sys.stderr)   # provenance: print — the chosen path is shown, never silent
        return Path(hits[-1]) if hits else None
    pats = [f"research/results/{unit}/**/ledger_ethsol.jsonl", f"comms/research/{unit}/**/ledger_ethsol.jsonl",
            f"research/results/{unit}/**/ledger.jsonl", f"comms/research/{unit}/**/ledger.jsonl"]
    for p in pats:  # provenance: pats — fixed list of the variant's own result dirs by unit id, in priority order (named ledger first)
        hits = sorted(glob.glob(str(REPO / p), recursive=True))
        if hits:
            print(f"[find_ledger] {len(hits)} candidate(s) for {p}, using {hits[-1]}", file=sys.stderr)   # provenance: print — the chosen path is shown, never silent
            return Path(hits[-1])
    return None


def run_cells(leg: str, led: Path, out: Path, jobs: int, leg_key: str = "ml_entry") -> None:
    def cell(acct: str, arm: str, seed: int) -> None:
        o = out / "cells" / f"{leg}__3y__{acct}__{arm}__s{seed}.json"
        if o.exists():
            return
        sim = G.SIM[acct]
        c, s, sw = G.CUR if arm == "cur" else sim["ven"]
        subprocess.run([sys.executable, str(REPO / "scripts/research/prop_ev_sim.py"), "--trades", f"{leg}={led}",
                        "--ruleset", str(REPO / f"config/prop_rulesets/{sim['rs']}.yaml"), "--costs", "breakout",
                        "--commission-bps-rt", str(c), "--slippage-bps-rt", str(s), "--swap-daily", str(sw),
                        "--swap-model", "prorated", "--funded-start", "fresh", "--lev-cap", f"{leg}={G.lev_cap(acct, leg_key)}",
                        "--sizing", "start", "--risk-pct", str(sim["risk"]), "--dd-switch-frac", "0.8", "--seed", str(seed),
                        "--lives", "1000", "--outer", "2", "--lives-per-outer", "100", "--modes", "path", "--out", str(o)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(REPO))
    (out / "cells").mkdir(parents=True, exist_ok=True)
    (out / "null_cells").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(lambda j: cell(*j), [(a, arm, s) for a in G.SIM for arm in ("ven", "cur") for s in range(1, 6)]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, help="slug, [a-z0-9-] only (no double underscore): names cells and the record")
    ap.add_argument("--ledger"), ap.add_argument("--from-unit")
    ap.add_argument("--arm-label", default=None, help="with --from-unit: read arms/<label>__trades.jsonl of an exit_lever_ablation unit")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--symbols", default=",".join(SYMS), help="comma list of ledger symbols graded (default ETHUSDT,SOLUSDT)")
    ap.add_argument("--leg-key", default="ml_entry", help="leg name prop_ev_sim keys lev-cap / cost on (default ml_entry; a Donchian arm passes its strategy key)")
    ap.add_argument("--write-record", action="store_true", help="write comms/prop_survival/<variant>.json (verdict as graded)")
    ap.add_argument("--family", default=None, help="holdout-ledger family (e.g. ENTRY); with --window-start/--window-end/--train-end the "
                    "read is recorded in comms/research/holdout_reads.jsonl and the edge CI uses that read's deflated z")
    ap.add_argument("--window-start"), ap.add_argument("--window-end"), ap.add_argument("--train-end", default="")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--edge-z", type=float, default=None, help="the caller already recorded the read: use its deflated z (no second claim)")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    leg = a.variant.replace("_", "-")
    led = Path(a.ledger) if a.ledger else (find_ledger(a.from_unit, a.arm_label) if a.from_unit else None)
    if led is None or not led.exists():
        res = {"rule": G.RULE_V3, "variant": a.variant, "from_unit": a.from_unit, "read_state": "no_variant_ledger",
               "verdict": "INDETERMINATE", "missing_piece": MISSING_PIECE}
        (out / "result.json").write_text(json.dumps(res, indent=1))
        print(json.dumps(res))
        return 0
    rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()]
    syms = tuple(x for x in a.symbols.split(",") if x)
    rows = [r for r in rows if r.get("symbol") in syms]
    if len(rows) < G.N_FLOOR:
        res = {"rule": G.RULE_V3, "variant": a.variant, "ledger": str(led), "read_state": "n_below_floor", "n": len(rows),
               "floor": G.N_FLOOR, "verdict": "INDETERMINATE"}
        (out / "result.json").write_text(json.dumps(res, indent=1))
        print(json.dumps(res))
        return 0
    claim = None
    if a.window_start and a.window_end:   # HOLDOUT-DEFLATED-REUSE: record the read; a re-read of the window is graded on a deflated z
        import holdout_lock as HL
        claim = HL.claim_read(f"{a.family or 'ENTRY'}-prop-{a.variant}", a.window_start, a.window_end, a.from_unit or a.variant,
                              a.reader, HL.LEDGER, symbols=list(syms), train_end=a.train_end, family=a.family)
    z = claim["bar"]["ci_z"] if claim else (a.edge_z or G.Z95)
    for r in rows:
        r["leg"] = r["strategy"] = a.leg_key      # prop_ev_sim lev-cap / cost keys on the leg name
    stage = out / "ledger_ethsol.jsonl"
    stage.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    run_cells(leg, stage, out, a.jobs, a.leg_key)
    agg = G.aggregate_v2(str(out) + "/")
    res = {"rule": G.RULE_V3, "variant": a.variant, "from_unit": a.from_unit, "ledger": str(led), "n": len(rows),
           "read_state": "graded", "prior_ml_records_on_this_window": len(glob.glob(str(REPO / "comms/prop_survival/ml_*.json"))),
           "holdout_claim": claim, "edge_ci_z": z,
           "window": "served-model held-out or dev-OOS as the variant's own ledger states; see its unit", "firms": {}}
    for acct in G.SIM:
        for arm in ("ven", "cur"):
            r = next(x for x in agg if x["account"] == acct and x["arm"] == arm)
            edge = G.edge_ci(G.ledger_net_r(rows, acct, arm), z=z)
            null = G.null_cell(rows, leg, acct, arm, out / "null_cells" / f"null_{acct}_{arm}.json", out / "null_work")
            res["firms"].setdefault(acct, {})[arm] = {"v2": r, "edge": edge, "null": null, "v3_verdict": G.grade_v3(r["verdict"], edge)}
    res["verdict_by_firm"] = {acct: arms["ven"]["v3_verdict"] for acct, arms in res["firms"].items()}
    res["verdict"] = "PASS" if any(v == "PASS" for v in res["verdict_by_firm"].values()) else \
        ("INDETERMINATE" if all(v == "INDETERMINATE" for v in res["verdict_by_firm"].values()) else "FAIL")
    (out / "result.json").write_text(json.dumps(res, indent=1))
    if a.write_record:
        h = res["firms"]["breakout_2"]["ven"]
        rec = {"leg": a.variant.replace("-", "_"), "harness": "ml_variant_prop_gate.py -> prop_ev_sim (path mode) via prop_gate.py",
               "ruleset": G.SIM["breakout_2"]["rs"], "ev_net_usd": h["v2"]["ev_median_usd"], "p_breach": h["v2"]["life_p_breach_worst"],
               "n_trades": len(rows), "decision_rule": {"id": G.RULE_V3, "registered_at": "2026-11-02T10:47:24Z",
                                                        "verdict": "pass" if res["verdict"] == "PASS" else "fail"},
               "per_firm_verdict": res["verdict_by_firm"]}
        (REPO / "comms/prop_survival" / f"{rec['leg']}.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({"verdict": res["verdict"], "by_firm": res["verdict_by_firm"], "n": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
