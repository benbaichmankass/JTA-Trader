#!/usr/bin/env python3
# wiring: research/queue/RQ-20261017-ae17-2*.yaml (theme infra daily self-test units; research-script-run.yml)
"""Research-pipeline self-tests that run AS queue units (theme `infra`).

Each ``--check`` reads only the repo checkout on the runner, measures one property of the research
machinery against a threshold registered in the owning unit, and writes ``<out>/verdict.json`` in the
shape scripts/research/script_run.py derives an E5 record from. A check that cannot look says so
(``read_state: no_data``); it never reports a pass it did not measure. Measures nothing about markets.

  runner_deps         the Python modules a runner-side unit's command may import (yfinance's absence killed
                      RQ-20261016-c56e-16/-17/-18 with exit=1 on 2026-10-17)
  results_readable    every research/results/*/*.jsonl line parses to an object carrying read_state
  queue_integrity     every queued unit names a known theme, a priority 1-3 and a pre-registered rule
  disposition_census  result_disposition_check findings (ungraded + needs_review without an owner) <= 5
  programme_coverage  plan questions with a programme node or a reasoned discharge >= 75 %
  machinery_selftests the grader, replenisher, runner-plan and disposition-check self-tests all pass
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RUNNER_MODULES = ("numpy", "pandas", "yaml", "requests", "dotenv", "yfinance")
DISPOSITION_MAX = 5          # == research_slo.yaml undispositioned_24h
COVERAGE_MIN_PCT = 75.0      # == research_slo.yaml programme_coverage_pct
SELFTESTS = ("queue_grade.py", "queue_replenish.py", "script_run.py", "result_disposition_check.py")


def runner_deps() -> Dict[str, Any]:
    present = {m: importlib.util.find_spec(m) is not None for m in RUNNER_MODULES}
    missing = sorted(m for m, ok in present.items() if not ok)
    return {"verdict": "fail" if missing else "pass", "read_state": "measured",
            "population": f"{len(RUNNER_MODULES)} modules a runner-side unit may import",
            "n": len(RUNNER_MODULES), "measurement": {"present": present, "missing": missing}}


def results_readable() -> Dict[str, Any]:
    files = rows = 0
    bad = []
    for f in sorted((ROOT / "research" / "results").glob("*/*.jsonl")):
        files += 1
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            rows += 1
            try:
                r = json.loads(line)
                ok = isinstance(r, dict) and "read_state" in r
            except ValueError:
                ok = False
            if not ok:
                bad.append(f"{f.relative_to(ROOT).as_posix()}:{i}")
    return {"verdict": "fail" if bad else "pass", "read_state": "measured" if files else "no_data",
            "population": f"{rows} row(s) in {files} result file(s) under research/results/",
            "n": rows, "measurement": {"files": files, "rows": rows, "unreadable_rows": len(bad), "sample": bad[:10]}}


def queue_integrity() -> Dict[str, Any]:
    import yaml
    themes = set((yaml.safe_load((ROOT / "research" / "THEMES.yaml").read_text())).get("themes") or {})
    queued = 0
    bad: Dict[str, list] = {}
    for f in sorted((ROOT / "research" / "queue").glob("RQ-*.yaml")):
        try:
            u = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as e:                       # noqa: BLE001 -- an unparseable unit is the finding
            bad[f.stem] = [f"unparseable: {type(e).__name__}"]
            continue
        if not isinstance(u, dict) or u.get("status") != "queued":
            continue
        queued += 1
        why = []
        if u.get("id") != f.stem:
            why.append("id != filename")
        if u.get("theme") not in themes:
            why.append(f"theme {u.get('theme')!r} not in THEMES.yaml")
        if u.get("priority") not in (1, 2, 3):
            why.append("priority not 1-3")
        dr = u.get("decision_rule")
        # e35-bracket-sweep.yml units carry the E35 gate (RULE-TPL-E35-BRACKET-*) inside the harness, graded by
        # queue_grade.grade_e35; every other unit must state its own rule here.
        if (not (isinstance(dr, dict) and dr.get("id") and dr.get("rule"))
                and (u.get("run") or {}).get("workflow") != "e35-bracket-sweep.yml"):
            why.append("no decision_rule.id/rule")
        if why:
            bad[f.stem] = why
    return {"verdict": "fail" if bad else "pass", "read_state": "measured" if queued else "no_data",
            "population": f"{queued} unit(s) with status queued in research/queue/",
            "n": queued, "measurement": {"queued": queued, "violations": len(bad),
                                         "sample": dict(list(bad.items())[:10])}}


def disposition_census() -> Dict[str, Any]:
    from scripts.research.result_disposition_check import census
    c = census(ROOT)
    return {"verdict": "pass" if c["findings"] <= DISPOSITION_MAX else "fail", "read_state": "measured",
            "population": f"{c['with_results']} unit(s) with landed results (24 h grace)",
            "n": c["with_results"], "measurement": {"findings": c["findings"], "max": DISPOSITION_MAX,
                                                    "counts": c["counts"]}}


def programme_coverage() -> Dict[str, Any]:
    from scripts.research.programme_coverage import coverage
    qs = cov = 0
    for p in coverage(ROOT)["programmes"]:
        qs += len(p["questions"])
        cov += len(p["covered"]) + len(p["carried"])
    pct = round(100.0 * cov / qs, 1) if qs else None
    return {"verdict": "pass" if pct is not None and pct >= COVERAGE_MIN_PCT else "fail",
            "read_state": "measured" if qs else "no_data",
            "population": f"{qs} plan question(s) across the programme plans",
            "n": qs, "measurement": {"covered": cov, "questions": qs, "pct": pct, "min_pct": COVERAGE_MIN_PCT}}


def machinery_selftests() -> Dict[str, Any]:
    out = {}
    for s in SELFTESTS:
        r = subprocess.run([sys.executable, f"scripts/research/{s}", "--self-test"], cwd=ROOT,
                           capture_output=True, text=True, timeout=600)
        out[s] = {"rc": r.returncode, "tail": (r.stdout + r.stderr).strip().splitlines()[-1:] or []}
    failed = sorted(s for s, v in out.items() if v["rc"] != 0)
    return {"verdict": "fail" if failed else "pass", "read_state": "measured",
            "population": f"{len(SELFTESTS)} research machinery self-test(s)", "n": len(SELFTESTS),
            "measurement": {"results": out, "failed": failed}}


CHECKS = {"runner_deps": runner_deps, "results_readable": results_readable, "queue_integrity": queue_integrity,
          "disposition_census": disposition_census, "programme_coverage": programme_coverage,
          "machinery_selftests": machinery_selftests}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", choices=sorted(CHECKS), required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    v = CHECKS[a.check]()
    v["note"] = f"infra self-test {a.check}: pipeline plumbing only; says nothing about any strategy or model"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2) + "\n")
    print(json.dumps({k: v[k] for k in ("verdict", "read_state", "population", "n")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
