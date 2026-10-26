#!/usr/bin/env python3
"""claude-judgments-guard: manifest lint for the `claude_judgments` family (CJ-2).

docs/plans/ml-claude-distillation-DESIGN.md § 3.5 test 2. A manifest whose
dataset family is `claude_judgments` may use as features ONLY the family's
decision-time columns (`FEATURE_COLUMNS`). Any judgment column (the teacher's
own output, siblings included) or outcome column as a feature is leakage, and
the target must be a judgment or outcome column, never a feature.

Scans every `ml/configs/*.yaml` (enabled manifests; `.disabled` files are not
read by the trainer). Exit 1 on any finding. `--self-test` runs fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml.datasets.families.claude_judgments import (  # noqa: E402
    FEATURE_COLUMNS,
    JUDGMENT_COLUMNS,
    OUTCOME_COLUMNS,
)

_FEATURE_KEYS = ("feature_column", "feature_columns", "features", "bucket_columns")
_TARGET_KEYS = ("target_column", "label_column")


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return []


def manifest_problems(m: dict) -> list[str]:
    if ((m.get("dataset") or {}).get("family")) != "claude_judgments":
        return []
    out: list[str] = []
    feats: list[str] = []
    targets: list[str] = []
    for block in ("trainer_config", "evaluator_config"):
        cfg = m.get(block) or {}
        for k in _FEATURE_KEYS:
            feats += _as_list(cfg.get(k))
        for k in _TARGET_KEYS:
            targets += _as_list(cfg.get(k))
    if not feats:
        out.append("declares no feature columns: the lint cannot certify it")
    for f in feats:
        if f in JUDGMENT_COLUMNS:
            out.append(f"feature {f!r} is a judgment column (the teacher's output): leakage")
        elif f in OUTCOME_COLUMNS:
            out.append(f"feature {f!r} is an outcome column (realised after the decision): leakage")
        elif f not in FEATURE_COLUMNS:
            out.append(f"feature {f!r} is not a decision-time column of claude_judgments")
    for t in targets:
        if t in FEATURE_COLUMNS:
            out.append(f"target {t!r} is a decision-time feature, not a label")
    return out


def findings(configs: Path = ROOT / "ml" / "configs") -> list[str]:
    out: list[str] = []
    for p in sorted(configs.glob("*.yaml")):
        try:
            m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            out.append(f"{p.name}: unparseable ({e})")
            continue
        if isinstance(m, dict):
            out += [f"{p.name}: {x}" for x in manifest_problems(m)]
    return out


def _self_test() -> int:
    good = {"dataset": {"family": "claude_judgments"},
            "trainer_config": {"target_column": "delta_r", "feature_columns": ["f_open_r", "f_peak_r"]}}
    cases = [
        ("a decision-time feature set passes", good, False),
        ("a judgment sibling as a feature is refused",
         {**good, "trainer_config": {"target_column": "delta_r", "feature_columns": ["f_open_r", "action"]}}, True),
        ("an outcome as a feature is refused",
         {**good, "trainer_config": {"target_column": "delta_r", "feature_column": "label_net_r"}}, True),
        ("an unknown column is refused",
         {**good, "trainer_config": {"target_column": "delta_r", "feature_columns": ["rationale"]}}, True),
        ("no features is refused", {**good, "trainer_config": {"target_column": "delta_r"}}, True),
        ("a feature as the target is refused",
         {**good, "trainer_config": {"target_column": "f_open_r", "feature_columns": ["f_peak_r"]}}, True),
        ("another family is not linted",
         {"dataset": {"family": "trade_outcomes"}, "trainer_config": {"feature_column": "action"}}, False),
    ]
    bad = 0
    for name, m, expect_fail in cases:
        got = bool(manifest_problems(m))
        if got != expect_fail:
            bad += 1
            print(f"SELF-TEST FAIL: {name}: problems={manifest_problems(m)}")
    print(f"claude-judgments-guard self-test: {len(cases) - bad}/{len(cases)} passed")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    f = findings()
    for x in f:
        print(f"claude-judgments-guard: {x}")
    if f:
        return 1
    print("claude-judgments-guard: no enabled manifest trains on a claude_judgments judgment or outcome column.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
