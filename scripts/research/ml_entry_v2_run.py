#!/usr/bin/env python3
"""Runner entry for the ENTRY v2 units (RQ-20261101-fs01-01 ablation, fs02-01 forward). The research runner executes only
``python3 scripts/research/<name>.py``, so the pipeline that used to be a shell script lives here.

    python3 scripts/research/ml_entry_v2_run.py ablation <unit> <out_dir>
    python3 scripts/research/ml_entry_v2_run.py forward  <unit> <out_dir>   # needs ABLATION_JSON=<fs01-01 ablation.json>
    python3 scripts/research/ml_entry_v2_run.py recipe   <unit> <out_dir>   # fs05-01: arms R0..R3 x sets S0..S2 x 3 seeds, DEV FOLDS ONLY
    python3 scripts/research/ml_entry_v2_run.py labels   <unit> <out_dir>   # fs06-01: targets T0..T4 x sets S0,S1 x 3 seeds, DEV FOLDS ONLY
    python3 scripts/research/ml_entry_v2_run.py levers   <unit> <out_dir>   # b601/b602/b604/a508: one-factor ENTRY lever tests, DEV FOLDS ONLY
    python3 scripts/research/ml_entry_v2_run.py ensemble <unit> <out_dir>   # d507-01: K=3 seed ensembles + per-fold quantile threshold, DEV FOLDS ONLY
    python3 scripts/research/ml_entry_v2_run.py timeframe <unit> <out_dir>  # b620..b626: the ENTRY pipeline at 5m/15m/1h/4h bars, DEV FOLDS ONLY

Steps: install the PINNED lightgbm (the live pin; a no-op once the runner image carries it, row RESEARCH-RUNNER-ML-DEPS / #22143),
fetch the Binance Vision streams (vision_streams.py), build the family table, run the arms in parallel (dev folds only), combine.
`forward` claims ONE read of W1 through holdout_lock.py inside ml_entry_v2.py.
"""
# wiring: manual-only - run by hand until the four ENTRY units (fs01/fs02/fs05/fs06) point at it; those command repoints are the held PR #22158 (pre-registered unit files cannot self-land)
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PIN = "lightgbm==4.6.0"
HERE = Path(__file__).resolve().parent
ARMS = ["A", "A2", "B", "C", "D", "E", "F", "G"]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("ablation", "ablation_trend", "forward", "recipe", "labels", "ensemble", "levers", "timeframe"):
        print(__doc__)
        return 2
    mode, unit, out = argv[0], argv[1], Path(argv[2])
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", PIN, "scikit-learn"], check=True)
    streams, octd, work = out / "streams", out / "oct", out / "work"
    for d in (streams, octd, work):
        d.mkdir(parents=True, exist_ok=True)
    vs = str(HERE / "vision_streams.py")
    v2 = str(HERE / "ml_entry_v2.py")
    if mode == "timeframe":
        # fetches its own Binance Vision monthly klines at the unit's bar size, 2020-07..2025-09 only (the held-out year is never downloaded)
        run(str(HERE / "ml_entry_timeframe.py"), "run", "--unit", unit, "--out", str(work), "--n-jobs", "4")
        for f in work.glob("*_result.json"):
            shutil.copy(f, out / f.name)
        return 0
    if mode == "levers":
        # ENTRY lever round 1 (b601/b602/b604/a508): baseline-feature table from the 12-column klines only, dev window only
        run(vs, "--out", str(streams), "--streams", "klines12", "--start", "2020-07-01", "--end", "2025-09-30", "--workers", "24")
        run(str(HERE / "ml_entry_levers.py"), "build-table", "--streams", str(streams), "--out", str(work))
        run(str(HERE / "ml_entry_levers.py"), "run", "--unit", unit, "--table", str(work / "table.pkl"), "--out", str(work), "--n-jobs", "4")
        for f in work.glob("*_result.json"):
            shutil.copy(f, out / f.name)
        return 0
    if mode in ("recipe", "labels", "ensemble"):
        # dev-only fetch: no date after 2025-09-30 is downloaded, so no sealed window can be read
        run(vs, "--out", str(streams), "--streams", "klines12,funding,premium", "--start", "2020-07-01", "--end", "2025-09-30", "--workers", "24")
        run(vs, "--out", str(streams), "--streams", "metrics", "--start", "2021-12-01", "--end", "2025-09-30", "--workers", "32")
        run(v2, "build-table", "--streams", str(streams), "--out", str(work))
        rc = str(HERE / "ml_entry_recipe.py")
        if mode == "ensemble":
            run(rc, "ens-run", "--table", str(work / "table.pkl"), "--out", str(work), "--n-jobs", "4")
            run(rc, "ens-combine", "--out", str(work))
            for f in (work / "ens_result.json", work / "ENS_RESULT.md"):
                shutil.copy(f, out / f.name)
            shutil.copytree(work / "ens_cells", out / "ens_cells", dirs_exist_ok=True)
            return 0
        run(rc, "run", "--unit", mode, "--table", str(work / "table.pkl"), "--out", str(work), "--n-jobs", "4")
        run(rc, "combine", "--unit", mode, "--out", str(work))
        for f in (work / "result.json", work / "RESULT.md"):
            shutil.copy(f, out / f.name)
        shutil.copytree(work / "runs", out / "runs", dirs_exist_ok=True)
        return 0
    run(vs, "--out", str(streams), "--streams", "klines12,funding,premium", "--workers", "24")
    run(vs, "--out", str(streams), "--streams", "metrics", "--start", "2021-12-01", "--end", "2026-10-31", "--workers", "32")
    run(vs, "--out", str(octd), "--streams", "klines12d,premiumd", "--start", "2026-10-01", "--end", "2026-10-31", "--workers", "16")
    run(vs, "--out", str(octd), "--streams", "funding", "--start", "2026-10", "--end", "2026-10", "--workers", "16")
    run(v2, "build-table", "--streams", str(streams), "--oct-dir", str(octd), "--out", str(work))
    if mode in ("ablation", "ablation_trend"):
        arms = ARMS if mode == "ablation" else ["A", "A2", "T"]   # ablation_trend (TREND-ALIGNMENT-FEATURE step 5): baseline + seed-noise + the F7 trend-align family only
        procs = [subprocess.Popen([sys.executable, v2, "arm", "--arm", a, "--out", str(work), "--n-jobs", "2"]) for a in arms]
        if any(p.wait() for p in procs):
            return 1
        run(v2, "combine", "--out", str(work))
        for f in list(work.glob("ablation.json")) + list(work.glob("arm_*.json")):
            shutil.copy(f, out / f.name)
        if mode == "ablation_trend":
            write_ablation_trend_verdict(unit, out)
    else:
        abl = os.environ.get("ABLATION_JSON")
        if not abl:
            print("set ABLATION_JSON to the fs01-01 ablation.json", file=sys.stderr)
            return 2
        run(v2, "forward", "--out", str(work), "--ablation", abl, "--unit", unit)
        shutil.copy(work / "forward.json", out / "forward.json")
    return 0


# RESEARCH-FLOW 2026-11-02: these modes copied their *_result.json into out_dir but never wrote the verdict.json
# script_run.py grades from, so every completed run (b60x/b62x/a508 ...) landed as read_state=producer_failed with real
# results sitting ungraded on main (71 of 90 landed records since 2026-11-01). The verdict word below is the script's OWN
# pre-registered per-cell verdict, mapped mechanically; an unrecognised shape writes NOTHING (stays producer_failed).
_WIN, _LOSS = {"win"}, {"no_win", "does_not_reproduce"}
_TF = {"beats_1h": "pass", "reproduces": "pass", "viable_not_better": "no_action_warranted", "not_viable": "fail",
       "does_not_reproduce": "fail", "indeterminate": "indeterminate", "smoke_not_judged": "indeterminate"}


def write_ablation_trend_verdict(unit: str, out: Path) -> bool:
    """TREND-ALIGNMENT-FEATURE step 5: map the F7 arm's combine verdict (admit/reject/indeterminate) to the unit's E5
    verdict. admit -> pass (the trend-align family adds >= +0.010 R per decision over the noise floor, 6/8 folds,
    >= 40 percent coverage, on the DEV folds); reject -> fail; indeterminate (coverage) -> indeterminate. The admission
    rule is ml_entry_v2.combine's, registered before any run. DEV FOLDS ONLY; no sealed window is read."""
    import json
    ab = out / "ablation.json"
    if not ab.exists():
        return False
    d = json.loads(ab.read_text())
    arm = (d.get("arms") or {}).get("T")
    if not isinstance(arm, dict) or arm.get("verdict") not in ("admit", "reject", "indeterminate"):
        return False
    v = {"admit": "pass", "reject": "fail", "indeterminate": "indeterminate"}[arm["verdict"]]
    (out / "verdict.json").write_text(json.dumps({
        "verdict": v, "read_state": "measured",
        "population": f"{unit}: F7 trend-align family vs baseline A (+ seed-noise A2), pooled ENTRY recipe, DEV FOLDS ONLY; "
                      f"n={arm.get('n')} decisions, dev_coverage={arm.get('dev_coverage')}",
        "n": arm.get("n"),
        "measurement": {"rule": d.get("rule"), "baseline_A": d.get("baseline_A"),
                        "noise_floor_abs_A_minus_A2": d.get("noise_floor_abs_A_minus_A2"), "T": arm},
        "note": "mechanical map of ml_entry_v2.combine's admission verdict for the F7 arm (admit->pass, reject->fail, "
                "indeterminate->indeterminate); directional trend features, the pooled model chooses its own side",
    }, indent=2) + "\n")
    return True


def write_verdict(unit: str, out: Path) -> bool:
    import json
    words, ns = [], []
    for f in sorted(out.glob("*_result.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            return False
        if isinstance(d, dict) and str(d.get("schema", "")).startswith("ml_entry_timeframe/"):
            # b620..b626: the unit's OWN registered word (ungated headline) -- beats_1h | viable_not_better | not_viable | indeterminate;
            # the 1h reproduction unit (b620) says reproduces | does_not_reproduce | smoke_not_judged. Mapped, never invented.
            w = d.get("verdict")
            v = _TF.get(str(w))
            if v is None:
                return False
            rows = d.get("rows")
            if isinstance(rows, dict):
                # ml_entry_timeframe/* writes rows as {"<tf>/<scaling>": {"decision_rows": N, ...}}; the evaluated population
                # is the sum of decision_rows. A null n with read_state=measured is refused by research_result.py
                # (inadmissible record), which lost b620/b621/b622/b624/b625/b626 in run 41566793018 (2026-11-03).
                drs = [v.get("decision_rows") for v in rows.values() if isinstance(v, dict)]
                drs = [x for x in drs if isinstance(x, int) and not isinstance(x, bool)]
                rows = sum(drs) if drs else None
            (out / "verdict.json").write_text(json.dumps({
                "verdict": v, "read_state": "measured",
                "population": f"{unit}: timeframe {d.get('timeframe')} ENTRY pipeline, DEV FOLDS ONLY; registered word {w!r} "
                              f"(gated variant {d.get('gated_verdict')!r}); features read-out is in the result file",
                "n": rows if isinstance(rows, int) else None,
                "note": "mechanical map of the unit's own registered verdict word: beats_1h/reproduces->pass, viable_not_better->"
                        "no_action_warranted, not_viable/does_not_reproduce->fail, indeterminate/smoke_not_judged->indeterminate",
            }, indent=2) + "\n")
            return True
        cells = d.get("cells") if isinstance(d.get("cells"), dict) else None
        for c in (cells.values() if cells else [d]):
            w = c.get("verdict") if isinstance(c, dict) else None
            if w in (None, "base"):
                continue
            words.append(str(w))
            if isinstance(c.get("n"), list) and c["n"]:
                ns.append(int(c["n"][0]))
    if not words or not set(words) <= (_WIN | _LOSS | {"indeterminate"}):
        return False
    v = "pass" if any(w in _WIN for w in words) else ("indeterminate" if "indeterminate" in words else "fail")
    (out / "verdict.json").write_text(json.dumps({
        "verdict": v, "read_state": "measured",
        "population": f"{unit}: {len(words)} non-base cell(s), DEV FOLDS ONLY; cell verdicts {sorted(set(words))}",
        "n": max(ns) if ns else None,
        "note": "mechanical map of the script's own per-cell verdicts (win->pass, all no_win->fail, any indeterminate->indeterminate); see *_result.json for cells",
    }, indent=2) + "\n")
    return True


if __name__ == "__main__":
    rc = main(sys.argv[1:])
    if rc == 0 and len(sys.argv) == 4 and sys.argv[1] != "ablation_trend":
        write_verdict(sys.argv[2], Path(sys.argv[3]))
    sys.exit(rc)
