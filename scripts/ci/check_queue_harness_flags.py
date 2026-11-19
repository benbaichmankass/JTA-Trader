#!/usr/bin/env python3
"""A queue unit may only pass a harness the flags that harness accepts.

WHY THIS EXISTS (2026-11-19, PROGRAMME-REVIEW-20261119 + lane QUEUE-FILL-STANDING-W47b)
-------------------------------------------------------------------------------
Two flag families were authored against `scripts/backtest_ict_scalp.py` that it did not have: `--side-filter` (7 units,
RQ-20261118-abab-24..36) and `--skip-hours` (7 units, abab-25..37). Each died at argparse (`unrecognized arguments`) and landed
`producer_failed`, spending a runner slot on a failure that was knowable from the spec. The guard that looks like it should have
caught this, `scripts/check_harness_lever_coupling.py`, cannot: it checks strategy CONFIG KEYS against the debt matrix's PLAIN /
LEVER_FLAG maps and says so in its own docstring ("a strategy family the debt matrix does not model at all (e.g. ict_scalp, vwap) has no
lever maps to check against and is skipped"). It never reads a queue unit.

WHAT THIS CHECKS. For a queue unit (status queued) whose `run.command` reaches a harness, every `--flag` the unit supplies must be a
flag that harness's parser declares (`add_argument("--flag", ...)`, read from the script's AST):
  * a unit that runs `scripts/backtest_*.py` / `src/backtest/run_backtest_vwap.py` directly: every `--flag` after the script;
  * a unit that runs `scripts/research/exit_lever_ablation.py`: the harness is the one `regime_debt_matrix.build_harness_cmd` picks for the
    unit's `--leg`; the checked flags are the ones in each `--arm LABEL=tok;tok` value (the arm tokens are appended to that harness's argv).
The harness's own base argv is built by repo code and is not re-checked here.

GRADING. Same new-vs-grandfathered shape as `check_research_queue_decision_rule.py`: a unit NEW on this branch that uses a missing flag
FAILS; a unit that already existed at the merge-base is counted, never failed (14 are known on main at the time of writing and are blocked by
their own PRs). States are never collapsed: `graded` / `no_base` / `base_unresolved`. A unit the guard cannot resolve to a harness (a leg
`exit_lever_ablation` itself refuses, an unreadable config) is COUNTED as `unresolved`, never reported clean.

`--audit` lists every queued unit's missing flags and every harness family this guard cannot model, with no pass/fail.

Gates this adds or changes: NONE as shipped. The check is REPORT-ONLY: a new unit with a missing flag prints a ::warning:: and the run
exits 0. Refusing the spec (`--enforce`, exit 1) would be a CI refusal, i.e. a new gate, and docs/CLAUDE-RULES-CANONICAL.md § "No new gates
without the operator's permission" reserves that to the operator's recorded permission (an ambiguous instruction is read as LESS friction).
To enforce: the operator records permission, then add `--enforce` to the `queue-harness-flags-guard` entry in scripts/ci/run_guards.py.

Run:
    python3 scripts/ci/check_queue_harness_flags.py --base origin/main
    python3 scripts/ci/check_queue_harness_flags.py --audit
    python3 scripts/ci/check_queue_harness_flags.py --self-test
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_research_queue_decision_rule import (  # noqa: E402
    _load_yaml, existed_at_merge_base, queue_files)

_ABLATION = "exit_lever_ablation.py"
_HARNESS_RE = re.compile(r"(?:^|/)(?:scripts/backtest_[a-z_0-9]+\.py|src/backtest/run_backtest_vwap\.py)$")
_FLAG_RE = re.compile(r"^(--[A-Za-z0-9][A-Za-z0-9_-]*)")

_flag_cache: Dict[str, Set[str]] = {}
_rdm = None


def harness_flags(script: str, root: Path = REPO) -> Optional[Set[str]]:
    """Every option string the script's argparse declares, from the AST; None when the file cannot be read."""
    key = f"{root}:{script}"
    if key in _flag_cache:
        return _flag_cache[key]
    try:
        tree = ast.parse((root / script).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument":
            for a in n.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("--"):
                    out.add(a.value)
    _flag_cache[key] = out
    return out


def _flags_in(tokens: List[str]) -> List[str]:
    out = []
    for t in tokens:
        m = _FLAG_RE.match(str(t))
        if m:
            out.append(m.group(1))
    return out


def _rdm_module():
    global _rdm
    if _rdm is None:
        p = REPO / "scripts" / "research" / "regime_debt_matrix.py"
        sys.path.insert(0, str(p.parent))
        spec = importlib.util.spec_from_file_location("regime_debt_matrix", p)
        _rdm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_rdm)
    return _rdm


def _leg_harness_script(leg: str, strategies: dict) -> Tuple[Optional[str], str]:
    """(harness script path, why-None) for a leg, using the SAME resolution exit_lever_ablation does."""
    cfg = strategies.get(leg)
    if not isinstance(cfg, dict):
        return None, f"leg {leg!r} is not in config/strategies.yaml"
    try:
        rdm = _rdm_module()
        harness = rdm.classify(cfg)
        argv, _, _ = rdm.build_harness_cmd(leg, cfg, harness, "x.csv", "1h", "e.jsonl", "j.json")
    except Exception as exc:  # noqa: BLE001 -- any failure is "could not resolve", counted, never clean
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    for a in argv[1:3]:
        if str(a).endswith(".py"):
            try:
                return Path(a).resolve().relative_to(REPO).as_posix(), ""
            except ValueError:
                return str(a), ""
    return None, "no script in the resolved argv"


def unit_problems(entry: dict, strategies: dict, root: Path = REPO) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """([(missing flag, harness script)], unresolved reason or None)."""
    cmd = ((entry.get("run") or {}).get("command")) or []
    if not isinstance(cmd, list):
        return [], "run.command is not a list"
    cmd = [str(c) for c in cmd]
    script = next((c for c in cmd if _HARNESS_RE.search(c)), None)
    if script is not None:
        known = harness_flags(script, root)
        if known is None:
            return [], f"cannot read {script}"
        after = cmd[cmd.index(script) + 1:]
        return [(f, script) for f in _flags_in(after) if f not in known], None
    if any(Path(c).name == _ABLATION for c in cmd):
        leg = None
        arms: List[str] = []
        for i, c in enumerate(cmd[:-1]):
            if c == "--leg":
                leg = cmd[i + 1]
            elif c == "--arm":
                arms.append(cmd[i + 1])
        if not leg:
            return [], "exit_lever_ablation unit without --leg"
        hs, why = _leg_harness_script(leg, strategies)
        if hs is None:
            return [], why
        known = harness_flags(hs, root)
        if known is None:
            return [], f"cannot read {hs}"
        toks: List[str] = []
        for arm in arms:
            rest = arm.split("=", 1)[1] if "=" in arm else ""
            toks += [t for part in rest.split(";") for t in part.split()]
        return [(f, hs) for f in _flags_in(toks) if f not in known], None
    return [], None   # not a harness-reaching unit (a driver script of its own): out of scope, not "clean harness"


def _strategies(root: Path) -> dict:
    raw, _ = _load_yaml(root / "config" / "strategies.yaml")
    return (raw or {}).get("strategies") or {}


def scan(root: Path, base: Optional[str]) -> Tuple[List[str], Dict[str, int], str]:
    strategies = _strategies(root)
    failures: List[str] = []
    c = {"units": 0, "checked": 0, "unresolved": 0, "grandfathered_bad": 0, "new_bad": 0}
    state = "no_base" if base is None else "graded"
    for rel in queue_files(root):
        if rel.startswith("research/queue/blocked/"):
            continue
        entry, err = _load_yaml(root / rel)
        if entry is None or str(entry.get("status") or "queued") != "queued":
            continue
        c["units"] += 1
        bad, unresolved = unit_problems(entry, strategies, root)
        if unresolved:
            c["unresolved"] += 1
            continue
        c["checked"] += 1
        if not bad:
            continue
        existed = None if base is None else existed_at_merge_base(root, base, rel)
        if base is not None and existed is None:
            state = "base_unresolved"
        msg = (f"{rel}: passes {sorted({f for f, _ in bad})} but {bad[0][1]} declares no such flag -- the run would die at argparse "
               "(`unrecognized arguments`) and land producer_failed. Build the flag first (default byte-identical, golden test), "
               "or block the unit on that build")
        if base is None:
            c["grandfathered_bad"] += 1
        elif existed is True:
            c["grandfathered_bad"] += 1
        else:                      # NEW, or the base could not be read: refuse rather than grant
            c["new_bad"] += 1
            failures.append(msg)
    return failures, c, state


def audit(root: Path) -> int:
    strategies = _strategies(root)
    print("== queued units whose flags the harness does not declare ==")
    n = 0
    unresolved: Dict[str, int] = {}
    for rel in queue_files(root):
        if rel.startswith("research/queue/blocked/"):
            continue
        entry, _ = _load_yaml(root / rel)
        if entry is None or str(entry.get("status") or "queued") != "queued":
            continue
        bad, un = unit_problems(entry, strategies, root)
        if un:
            unresolved[un] = unresolved.get(un, 0) + 1
        if bad:
            n += 1
            print(f"  {rel}: {sorted({f for f, _ in bad})} not in {bad[0][1]}")
    print(f"  total units with a missing flag: {n}")
    print("== units the guard cannot resolve to a harness (counted, not clean) ==")
    for why, k in sorted(unresolved.items(), key=lambda x: -x[1]):
        print(f"  {k:4d}  {why}")
    print("== harness families exit_lever_ablation can run vs scripts/backtest_*.py that exist ==")
    ablation_src = (REPO / "scripts/research/exit_lever_ablation.py").read_text()
    m = re.search(r'if harness not in \(([^)]*)\)', ablation_src)
    covered = set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()
    print(f"  exit_lever_ablation covers harness classes: {sorted(covered)}")
    present = sorted(p.name for p in (REPO / "scripts").glob("backtest_*.py"))
    print(f"  harness scripts present: {present}")
    return 0


_UNIT = """id: {id}
status: queued
run:
  command:
{cmd}
"""


def _write(root: Path, name: str, cmd: List[str]) -> None:
    body = "\n".join(f"  - {c}" for c in cmd)
    (root / "research" / "queue" / f"{name}.yaml").write_text(_UNIT.format(id=name, cmd=body))


def _self_test() -> int:
    bad = 0

    def check(label: str, cond: bool) -> None:
        nonlocal bad
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        bad += not cond

    strategies = _strategies(REPO)
    ict_leg = next((k for k, v in strategies.items() if isinstance(v, dict) and str(k).startswith("ict_scalp_")
                    and (v.get("symbols") or [None])[0] and v.get("timeframe")), None)
    check("a real ict_scalp leg exists to plant against", ict_leg is not None)
    flags = harness_flags("scripts/backtest_ict_scalp.py") or set()
    check("the parser's flags are read from the AST (known flag present)", "--cooldown-bars" in flags)
    check("an invented flag is absent", "--no-such-flag-zz" not in flags)

    def ablation(arm: str) -> dict:
        return {"run": {"command": ["python3", "scripts/research/exit_lever_ablation.py", "--leg", ict_leg or "x",
                                    "--arm", "A=", "--arm", arm]}}

    p, un = unit_problems(ablation("B=--cooldown-bars=3"), strategies)
    check("ablation arm with a declared flag passes", p == [] and un is None)
    p, un = unit_problems(ablation("B=--no-such-flag-zz=1"), strategies)
    check("ablation arm with a flag the ict_scalp harness lacks is REFUSED (the abab-33 shape)",
          [f for f, _ in p] == ["--no-such-flag-zz"] and un is None)
    p, un = unit_problems(ablation("B=--cooldown-bars 3;--no-such-flag-zz"), strategies)
    check("a ';'-joined arm is split and each flag graded", [f for f, _ in p] == ["--no-such-flag-zz"])
    p, un = unit_problems({"run": {"command": ["python3", "scripts/backtest_ict_scalp.py", "--no-such-flag-zz", "1"]}}, strategies)
    check("a direct harness call with a missing flag is refused", [f for f, _ in p] == ["--no-such-flag-zz"])
    p, un = unit_problems(ablation("B=--cooldown-bars=3") | {"run": {"command": ["python3", "scripts/research/exit_lever_ablation.py",
                                                                              "--leg", "no_such_leg", "--arm", "B=--x"]}}, strategies)
    check("a leg the guard cannot resolve is UNRESOLVED, never clean", un is not None and p == [])
    check("report-only by default: a NEW missing flag exits 0", exit_code(["x: missing flag"], enforce=False) == 0)
    check("--enforce (a gate, operator permission) exits 1 on the same input", exit_code(["x: missing flag"], enforce=True) == 1)
    check("--enforce with nothing to refuse exits 0", exit_code([], enforce=True) == 0)
    p, un = unit_problems({"run": {"command": ["python3", "scripts/research/some_driver.py", "--whatever"]}}, strategies)
    check("a driver script of its own is out of scope (not a harness flag check)", p == [] and un is None)

    def git(r: Path, *a: str) -> None:
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "research" / "queue").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "config" / "strategies.yaml").write_text((REPO / "config" / "strategies.yaml").read_text())
        git(root, "init", "-q", "-b", "trunk")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "t")
        bad_cmd = ["python3", "scripts/backtest_ict_scalp.py", "--no-such-flag-zz", "1"]
        _write(root, "OLD-BAD", bad_cmd)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "b")
        git(root, "checkout", "-q", "-b", "f")
        _write(root, "NEW-BAD", bad_cmd)
        _write(root, "NEW-GOOD", ["python3", "scripts/backtest_ict_scalp.py", "--cooldown-bars", "3"])
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "f")
        # the planted units run the REAL repo's harness parser: point the AST reader at REPO, the units at the temp tree
        f, c, st = scan_with_harness_root(root, "trunk")
        check("graded state", st == "graded")
        check("NEW unit with a missing flag is REPORTED (graded)", any("NEW-BAD" in x for x in f))
        check("NEW unit with a declared flag passes", not any("NEW-GOOD" in x for x in f))
        check("OLD unit grandfathered, but counted", not any("OLD-BAD" in x for x in f) and c["grandfathered_bad"] == 1)
        check("no_base fails nothing", scan_with_harness_root(root, None)[0] == [])
        f2, _, st2 = scan_with_harness_root(root, "does-not-exist")
        check("base_unresolved refuses rather than grants", st2 == "base_unresolved" and any("OLD-BAD" in x for x in f2))
    print(f"check-queue-harness-flags --self-test: {bad} failure(s)")
    return 1 if bad else 0


def exit_code(failures: List[str], enforce: bool) -> int:
    """Report-only unless enforced: refusing is a CI gate, which needs the operator's recorded permission."""
    return 1 if (failures and enforce) else 0


def scan_with_harness_root(root: Path, base: Optional[str]):
    """scan() over a temp tree whose harness scripts are the REAL repo's (the temp tree holds only units + config)."""
    real = harness_flags
    globals()["harness_flags"] = lambda script, r=REPO: real(script, REPO)
    try:
        return scan(root, base)
    finally:
        globals()["harness_flags"] = real


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--enforce", action="store_true",
                    help="exit 1 on a NEW unit with a missing flag (a gate: needs the operator's recorded permission); default is report-only")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    import _dirty_tree  # noqa: PLC0415 -- path shim above; the shared dirty-tree notice (a --base guard grades a commit range)
    _dirty_tree.warn()
    if a.self_test:
        return _self_test()
    if a.audit:
        return audit(REPO)
    failures, c, st = scan(REPO, a.base)
    print(f"check-queue-harness-flags: base_state={st} queued_units={c['units']} checked={c['checked']} unresolved={c['unresolved']} "
          f"grandfathered_missing_flag={c['grandfathered_bad']} new_missing_flag={c['new_bad']}")
    for f in failures:
        print(f"::{'error' if a.enforce else 'warning'}::check-queue-harness-flags: {f}")
    print("check-queue-harness-flags: " + ("OK" if not failures else "REPORT-ONLY (not enforced): see the warnings above"))
    return exit_code(failures, a.enforce)


if __name__ == "__main__":
    raise SystemExit(main())
