#!/usr/bin/env python3
"""claude-judgments-guard: manifest lint for the `claude_judgments` family (CJ-2).

docs/plans/ml-claude-distillation-DESIGN.md § 3.5 test 2. A manifest whose
dataset family is `claude_judgments` may use as features ONLY the family's
decision-time columns (`FEATURE_COLUMNS`). Any judgment column (the teacher's
own output, siblings included) or outcome column as a feature is leakage, and
the target must be a judgment or outcome column, never a feature.

CLAUDE-GRADE-LOOP use rule (c) (design § 3.7), on EVERY family:

* W1 a Claude judgment column (e.g. `judgement_confidence`) named anywhere in a
  `sample_weight` block or as `sample_weight_column` is refused: Claude rows are
  weighted by their call class's GRADED skill (`claude_judgments.call_class_weight`),
  never by the row's own stated confidence.
* W2 a `claude_judgments` manifest whose TARGET is a judgment column (a teacher
  label) is refused until the trainer applies `call_class_weight`
  (`trainer_config.sample_weight.claude_call_class: graded` is the declaration,
  and `ml/trainers/sample_weights.py` does not yet honour it, so it is refused too:
  a declared weight nothing applies is worse than none). Outcome targets
  (`delta_r`, `label_net_r`) are unaffected.
* W3 Claude as a FEATURE (operator Q2 2026-10-25, "Allow as a feature later"): a
  feature column named `claude_*` / `ltr_*` / `desk_*` in any family is refused
  unless `claude_feature_gate.evidence` names a committed JSON whose `verdict` is
  `EDGE` and `out_of_sample` is true (a model proving net-R edge out of sample).

Scans every `ml/configs/*.yaml` (enabled manifests; `.disabled` files are not
read by the trainer). Exit 1 on any finding. `--self-test` runs fixtures.
"""
from __future__ import annotations

import json
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


_CLAUDE_FEATURE_PREFIXES = ("claude_", "ltr_", "desk_")


def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x)]
    return []


def use_rule_problems(m: dict, root: Path = ROOT) -> list[str]:
    out: list[str] = []
    for block in ("trainer_config", "evaluator_config"):
        cfg = m.get(block) or {}
        for s in _strings(cfg.get("sample_weight")) + _as_list(cfg.get("sample_weight_column")):
            if s in JUDGMENT_COLUMNS:
                out.append(f"W1: {s!r} used as a sample weight: weight Claude rows by graded call-class skill "
                           "(claude_judgments.call_class_weight), never by stated confidence")
        feats = [f for k in _FEATURE_KEYS for f in _as_list(cfg.get(k))]
        claude_feats = [f for f in feats if f.startswith(_CLAUDE_FEATURE_PREFIXES)]
        if claude_feats:
            ev = (m.get("claude_feature_gate") or {}).get("evidence")
            rec = None
            if ev and (root / ev).is_file():
                try:
                    rec = json.loads((root / ev).read_text(encoding="utf-8"))
                except ValueError:
                    rec = None
            if not (isinstance(rec, dict) and rec.get("verdict") == "EDGE" and rec.get("out_of_sample") is True):
                out.append(f"W3: Claude-derived feature(s) {claude_feats} need claude_feature_gate.evidence -> a committed "
                           "record with verdict EDGE and out_of_sample true (operator Q2: a feature only once a model "
                           "proves net-R edge out of sample)")
    if ((m.get("dataset") or {}).get("family")) == "claude_judgments":
        tgts = [t for b in ("trainer_config", "evaluator_config") for k in _TARGET_KEYS
                for t in _as_list((m.get(b) or {}).get(k))]
        for t in tgts:
            if t in JUDGMENT_COLUMNS:
                out.append(f"W2: target {t!r} is a teacher label; refused until ml/trainers/sample_weights.py applies "
                           "claude_judgments.call_class_weight (train on delta_r / label_net_r meanwhile)")
    return out


def manifest_problems(m: dict) -> list[str]:
    if ((m.get("dataset") or {}).get("family")) != "claude_judgments":
        return use_rule_problems(m)
    out: list[str] = use_rule_problems(m)
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
        ("another family is not linted for this family's columns",
         {"dataset": {"family": "trade_outcomes"}, "trainer_config": {"feature_column": "action"}}, False),
        ("W1 raw confidence as a weight is refused (any family)",
         {"dataset": {"family": "trade_outcomes"},
          "trainer_config": {"feature_column": "x", "sample_weight": {"column": "judgement_confidence"}}}, True),
        ("W1 recency weighting passes",
         {**good, "trainer_config": {**good["trainer_config"], "sample_weight": {"half_life_days": 30}}}, False),
        ("W2 a teacher-label target is refused until weighting is wired",
         {**good, "trainer_config": {"target_column": "action", "feature_columns": ["f_open_r"]}}, True),
        ("W3 a Claude feature without evidence is refused",
         {"dataset": {"family": "trade_outcomes"}, "trainer_config": {"feature_columns": ["claude_confidence"]}}, True),
        ("W3 a Claude feature with a non-existent evidence path is refused",
         {"dataset": {"family": "trade_outcomes"}, "claude_feature_gate": {"evidence": "nope/missing.json"},
          "trainer_config": {"feature_columns": ["desk_p_hit"]}}, True),
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
