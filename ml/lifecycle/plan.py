"""Load + validate lifecycle plans. Pure functions; no I/O beyond reading YAML."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
PLANS_DIR = Path(__file__).resolve().parent / "plans"
CONFIGS_DIR = REPO / "ml" / "configs"
PROVENANCE = {"MEASURED", "ESTIMATED"}
JOB_KINDS = {"retrain", "retest", "update"}
PLACEHOLDERS = {"py", "manifest", "model_id", "datasets_root", "experiments_root",
                "registry_root", "journal_db", "symbol", "timeframe"}


def population() -> list[Path]:
    """The population: every top-level *.yaml manifest in ml/configs/ (the set the
    nightly cycle trains; .disabled and retired/ are out by construction)."""
    return sorted(CONFIGS_DIR.glob("*.yaml"))


def load_plan(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_all() -> dict[str, dict[str, Any]]:
    return {p.stem: load_plan(p) for p in sorted(PLANS_DIR.glob("*.yaml"))}


def jobs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a plan into schedulable jobs: retrain, each retest, update."""
    out = []
    rt = plan["retrain"]
    out.append({"id": "retrain", "kind": "retrain", "cadence_days": rt["cadence_days"],
                "provenance": rt["cadence_provenance"], "command": rt["command"],
                "timeout_s": rt.get("timeout_s", 1800)})
    for t in plan.get("retest", []):
        out.append({"id": t["id"], "kind": "retest", "cadence_days": t["cadence_days"],
                    "provenance": t["cadence_provenance"], "command": t["command"],
                    "timeout_s": t.get("timeout_s", 900)})
    up = plan["update"]
    out.append({"id": "update", "kind": "update", "cadence_days": up["cadence_days"],
                "provenance": up["cadence_provenance"], "command": up["command"],
                "timeout_s": up.get("timeout_s", 900)})
    return out


def fill(command: list[str], plan: dict[str, Any], ctx: dict[str, str]) -> list[str]:
    vals = {"manifest": plan["manifest"], "model_id": plan["model_id"],
            "symbol": plan["datasets"][0].get("symbol_scope", ""),
            "timeframe": plan["datasets"][0].get("timeframe", ""), **ctx}
    return [re.sub(r"\{(\w+)\}", lambda m: vals[m.group(1)], a) for a in command]


def validate(stem: str, plan: dict[str, Any]) -> list[str]:
    """Return problems ([] = ok). Static: nothing is executed."""
    errs: list[str] = []
    for k in ("plan_id", "model_id", "manifest", "datasets", "retrain", "retest", "update", "reporting"):
        if k not in plan:
            errs.append(f"missing key {k}")
    if errs:
        return errs
    if plan["plan_id"] != stem:
        errs.append("plan_id != filename stem")
    if not (REPO / plan["manifest"]).is_file():
        errs.append(f"manifest not found: {plan['manifest']}")
    if plan["update"].get("promote_past_shadow") != "operator_tier3":
        errs.append("update.promote_past_shadow must be 'operator_tier3' (the schedule proposes, never promotes)")
    for j in jobs(plan):
        if j["provenance"] not in PROVENANCE:
            errs.append(f"{j['id']}: cadence_provenance must be MEASURED|ESTIMATED")
        if not isinstance(j["cadence_days"], (int, float)) or j["cadence_days"] <= 0:
            errs.append(f"{j['id']}: cadence_days must be > 0")
        errs += [f"{j['id']}: {e}" for e in resolve_command(j["command"])]
    rt_kinds = {t.get("kind") for t in plan["retrain"].get("triggers", [])}
    if "calendar" not in rt_kinds:
        errs.append("retrain.triggers must include a calendar trigger")
    return errs


def _cli_subcommands() -> set[str]:
    src = (REPO / "ml" / "cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'add_parser\(\s*"([\w-]+)"', src))


def resolve_command(cmd: list[str]) -> list[str]:
    """Static resolution: placeholders known, script/module/subcommand exists."""
    errs = []
    if not cmd or not all(isinstance(a, str) for a in cmd):
        return ["command must be a non-empty list of strings"]
    for a in cmd:
        for ph in re.findall(r"\{(\w+)\}", a):
            if ph not in PLACEHOLDERS:
                errs.append(f"unknown placeholder {{{ph}}}")
    if cmd[0] != "{py}":
        return errs + ["command[0] must be {py}"]
    if cmd[1:3] == ["-m", "ml"]:
        if len(cmd) < 4 or cmd[3] not in _cli_subcommands():
            errs.append(f"unknown `python -m ml` subcommand: {cmd[3:4]}")
    elif cmd[1] == "-m":
        mod = cmd[2].replace(".", "/")
        if not ((REPO / f"{mod}.py").is_file() or (REPO / mod / "__init__.py").is_file()):
            errs.append(f"module not found: {cmd[2]}")
    elif not (REPO / cmd[1]).is_file():
        errs.append(f"script not found: {cmd[1]}")
    return errs
