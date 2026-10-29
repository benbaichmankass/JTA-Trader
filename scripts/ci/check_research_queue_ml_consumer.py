#!/usr/bin/env python3
"""Every NEW research-queue ML unit names its consumer and the live or demo decision it would change.

WHY THIS EXISTS
---------------
Operator 2026-10-29, system-first rule (`docs/claude/work/checklist/_header.json` `priorities.system_first`): the ML
programme picked its targets from the models it already had, so its lead candidate's training book covered none of the
real-money legs, and 43 of the 50 ML units of the week of 2026-10-22 were learner variants of existing heads (manager
measurement, checklist row `ML-PIPELINE-DESIGN`). The intake rule in `research/queue/PLANNING.md` § 1c and
`docs/plans/ml-pipeline-design-2026-10-29.md` § 4 closes that path: an ML unit is admitted only if it names the
CONSUMER that would act on its answer and the live or demo DECISION that answer would change. This guard is the
mechanical half. Same grading as `check_research_queue_decision_rule.py` and
`check_research_queue_design_fields.py`: a unit NEW on this branch is graded, one that existed at the merge-base is
GRANDFATHERED (counted, never failed), and the population-wide counts print on every run.

WHAT IS AN ML UNIT. Any one of: an `ml_consumer:` or `ml_bakeoff:` block; `theme: ml_health`; or an ML term in the
title or question (`ML`, learner, LightGBM/XGBoost/CatBoost, classifier head, meta-label, neural, transformer,
TabPFN, TSFM, Chronos, foundation model, "<kind> head", "train a model", `model_id`). A false keyword hit writes
`ml_consumer: {not_applicable: <reason, >= 20 chars>}`; the count of those prints on every run.

THE FIELD.
    ml_consumer:
      consumer: <repo path that acts on the answer (e.g. src/runtime/advisory_sizing.py), or a checklist row id
                 (e.g. ML-SERVE-SETUP-FEATURES) whose build is that consumer>
      decision: <the decision it would change, >= 15 chars (e.g. "downsize or skip entries on ada_pullback_2h")>
      legs: [<leg>, ...]     # each on a `mode: live` account roster in config/accounts.yaml
      book: money | demo_floor   # optional; when present it must equal what the roster says

`money` = a leg on a real-money account or its mirror, or on a prop account (`account_class: prop`). `demo_floor` = a
leg on a general paper account only (bybit_1 / alpaca_paper / ib_paper; `scripts/ops/strategy_status.py`). A leg on
neither (e.g. only `alpaca_options_paper`, or unrostered) is refused: no consumer acts on it.

States, never collapsed (`graded` / `no_base` / `base_unresolved`) are those of the decision-rule guard.

Run:
    python3 scripts/ci/check_research_queue_ml_consumer.py --base origin/main
    python3 scripts/ci/check_research_queue_ml_consumer.py --self-test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_research_queue_decision_rule import (  # noqa: E402
    _load_yaml, existed_at_merge_base, queue_files)

GENERAL_PAPER = ("bybit_1", "alpaca_paper", "ib_paper")       # scripts/ops/strategy_status.py GENERAL_PAPER
REAL_MONEY = ("bybit_2", "bybit_portfolio", "alpaca_live", "alpaca_portfolio", "ib_live")  # REAL_MONEY_MIRROR + mirrors
_CHECKLIST_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,}$")
_ML_CASED = re.compile(r"\bML\b")
_ML = re.compile(
    r"\bmachine[- ]learn|\blearner|\blgbm\b|lightgbm|xgboost|catboost|\bclassifier head|meta-?label|\bneural\b"
    r"|transformer|tabpfn|\btsfm\b|chronos|foundation[- ]model"
    r"|\b(?:regime|exit|vol|direction|setup|bracket|quantile|meta|ranker|conviction)[- ](?:head|model)s?\b"
    r"|\bmodel_id\b|\btrain(?:ed|ing)? (?:a |the )?(?:model|head)", re.I)
MIN_DECISION = 15
MIN_NA = 20


def is_ml_unit(entry: dict) -> bool:
    if "ml_consumer" in entry or "ml_bakeoff" in entry or entry.get("theme") == "ml_health":
        return True
    text = f"{entry.get('title') or ''} {entry.get('question') or ''}"
    return bool(_ML_CASED.search(text) or _ML.search(text))


def books(root: Path) -> Dict[str, str]:
    """leg -> `money` | `demo_floor`, re-parsed from config/accounts.yaml (live accounts only)."""
    from src.config.accounts_loader import load_accounts_dict  # noqa: PLC0415 -- the canonical accounts.yaml reader
    accounts = load_accounts_dict(root / "config" / "accounts.yaml")
    out: Dict[str, str] = {}
    for name, cfg in accounts.items():
        if not isinstance(cfg, dict) or cfg.get("mode") != "live":
            continue
        money = name in REAL_MONEY or cfg.get("account_class") == "prop"
        for leg in cfg.get("strategies") or []:
            if money:
                out[str(leg)] = "money"
            elif name in GENERAL_PAPER:
                out.setdefault(str(leg), "demo_floor")
    return out


def consumer_errors(entry: dict, root: Path, book_of: Dict[str, str]) -> List[str]:
    if not is_ml_unit(entry):
        return []
    c = entry.get("ml_consumer")
    if not isinstance(c, dict):
        return ["ML unit with no `ml_consumer` block: name the consumer that acts on the answer, the live or demo "
                "decision it would change, and the rostered legs (research/queue/PLANNING.md § 1c)"]
    na = c.get("not_applicable")
    if na is not None:
        return [] if isinstance(na, str) and len(na.strip()) >= MIN_NA else [
            f"`ml_consumer.not_applicable` needs a reason of >= {MIN_NA} characters"]
    errs: List[str] = []
    cons = c.get("consumer")
    if not (isinstance(cons, str) and cons.strip()):
        errs.append("`ml_consumer.consumer` is required (a repo path, or the checklist row id that builds it)")
    else:
        s = cons.strip()
        path_ok = (root / s.split("::", 1)[0]).exists()
        row_ok = bool(_CHECKLIST_ID.match(s)) and (root / "docs/claude/work/checklist" / f"{s}.json").is_file()
        if not (path_ok or row_ok):
            errs.append(f"`ml_consumer.consumer` {s[:60]!r} is neither an existing repo path nor a checklist row id")
    dec = c.get("decision")
    if not (isinstance(dec, str) and len(dec.strip()) >= MIN_DECISION):
        errs.append(f"`ml_consumer.decision` must state the decision it would change (>= {MIN_DECISION} chars)")
    legs = c.get("legs")
    if not (isinstance(legs, list) and legs and all(isinstance(x, str) and x for x in legs)):
        errs.append("`ml_consumer.legs` must be a non-empty list of rostered legs")
        return errs
    off = [x for x in legs if x not in book_of]
    if off:
        errs.append(f"`ml_consumer.legs` {off} are on no real-money, prop or demo-floor roster with `mode: live` "
                    "(config/accounts.yaml)")
    declared = c.get("book")
    if declared is not None:
        actual = "money" if any(book_of.get(x) == "money" for x in legs) else "demo_floor"
        if declared not in ("money", "demo_floor"):
            errs.append("`ml_consumer.book` must be `money` or `demo_floor`")
        elif not off and declared != actual:
            errs.append(f"`ml_consumer.book: {declared}` disagrees with the roster, which says `{actual}`")
    return errs


def scan(root: Path, base: Optional[str]) -> Tuple[List[str], dict, str]:
    files = queue_files(root)
    book_of = books(root)
    counts = {"units": len(files), "ml_units": 0, "missing_or_bad": 0, "not_applicable": 0, "money": 0,
              "demo_floor": 0}
    failures: List[str] = []
    base_state = "no_base"
    merge_base_ok = True
    if base is not None:
        p = subprocess.run(["git", "-C", str(root), "merge-base", base, "HEAD"], capture_output=True, text=True)
        merge_base_ok = p.returncode == 0 and bool(p.stdout.strip())
        base_state = "graded" if merge_base_ok else "base_unresolved"
    for rel in files:
        entry, err = _load_yaml(root / rel)
        if err is not None or not is_ml_unit(entry):
            continue  # unreadable is reported by the decision-rule guard; not double-counted here
        counts["ml_units"] += 1
        c = entry.get("ml_consumer") if isinstance(entry.get("ml_consumer"), dict) else {}
        if "not_applicable" in c:
            counts["not_applicable"] += 1
        errs = consumer_errors(entry, root, book_of)
        if not errs and isinstance(c.get("legs"), list):
            counts["money" if any(book_of.get(x) == "money" for x in c["legs"]) else "demo_floor"] += 1
        counts["missing_or_bad"] += bool(errs)
        if not errs or base is None:
            continue
        if merge_base_ok and existed_at_merge_base(root, base, rel):
            continue  # grandfathered: counted, never failed
        why = "NEW unit" if merge_base_ok else "merge-base unreadable, newness UNKNOWN (refusing)"
        failures.append(f"{rel}: {why}: " + "; ".join(errs))
    return failures, counts, base_state


# --------------------------------------------------------------------- self-test
_ACCOUNTS = """accounts:
  bybit_2: {mode: live, strategies: [money_leg]}
  breakout_2: {mode: live, account_class: prop, strategies: [prop_leg]}
  bybit_1: {mode: live, strategies: [demo_leg, prop_leg]}
  alpaca_options_paper: {mode: live, strategies: [options_leg]}
  breakout_1: {mode: dry_run, account_class: prop, strategies: [dry_leg]}
"""
_UNIT = "id: {id}\ntitle: {t}\nquestion: q\nstatus: queued\n{extra}"
_GOOD = ("ml_consumer:\n  consumer: src/runtime/advisory_sizing.py\n"
         "  decision: downsize or skip entries on money_leg\n  legs: [money_leg]\n  book: money\n")


def _self_test() -> int:
    bad = 0

    def check(label: str, cond: bool) -> None:
        nonlocal bad
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")
        bad += not cond

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "config").mkdir()
        (root / "config" / "accounts.yaml").write_text(_ACCOUNTS)
        (root / "src/runtime").mkdir(parents=True)
        (root / "src/runtime/advisory_sizing.py").write_text("")
        (root / "docs/claude/work/checklist").mkdir(parents=True)
        (root / "docs/claude/work/checklist/ML-SERVE-X.json").write_text("{}")
        b = books(root)
        check("roster: real-money leg is money", b.get("money_leg") == "money")
        check("roster: prop leg is money even when also on the demo floor", b.get("prop_leg") == "money")
        check("roster: general-paper leg is demo_floor", b.get("demo_leg") == "demo_floor")
        check("roster: options-paper-only and dry-run legs are on no book",
              "options_leg" not in b and "dry_leg" not in b)

        def errs(**c):
            return consumer_errors({"title": "LightGBM meta-label", "ml_consumer": c}, root, b)

        full = {"consumer": "src/runtime/advisory_sizing.py", "decision": "downsize entries on money_leg",
                "legs": ["money_leg"]}
        check("detect: theme ml_health", is_ml_unit({"theme": "ml_health"}))
        check("detect: LightGBM in title", is_ml_unit({"title": "a LightGBM bake-off"}))
        check("detect: exit head", is_ml_unit({"question": "does the exit head add value"}))
        check("detect: ml_bakeoff block", is_ml_unit({"ml_bakeoff": {}}))
        check("detect: head-to-head is not ML", not is_ml_unit({"title": "prop head-to-head on velotrade_1"}))
        check("detect: lowercase path 'ml/' is not ML", not is_ml_unit({"question": "edit ml/ configs"}))
        check("detect: a sizing 'model' is not ML", not is_ml_unit({"title": "prop fit under the sizing model"}))
        check("non-ML unit not graded", not consumer_errors({"title": "Donchian 20 vs 30"}, root, b))
        check("ML unit with no block caught", bool(consumer_errors({"title": "LightGBM head"}, root, b)))
        check("full block ok", not errs(**full))
        check("checklist row id as consumer ok", not errs(**{**full, "consumer": "ML-SERVE-X"}))
        check("missing consumer path caught", bool(errs(**{**full, "consumer": "src/nope.py"})))
        check("unknown row id caught", bool(errs(**{**full, "consumer": "ML-NOPE"})))
        check("short decision caught", bool(errs(**{**full, "decision": "improve it"})))
        check("empty legs caught", bool(errs(**{**full, "legs": []})))
        check("unrostered leg caught", bool(errs(**{**full, "legs": ["options_leg"]})))
        check("book mismatch caught", bool(errs(**{**full, "book": "demo_floor"})))
        check("demo-floor leg with book demo_floor ok", not errs(**{**full, "legs": ["demo_leg"], "book": "demo_floor"}))
        check("not_applicable with reason ok", not errs(not_applicable="a data-pipeline smoke test, no decision"))
        check("not_applicable without reason caught", bool(errs(not_applicable="n/a")))

        def git(*a: str) -> None:
            subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)

        q = root / "research" / "queue"
        q.mkdir(parents=True)
        git("init", "-q", "-b", "trunk")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (q / "OLD.yaml").write_text(_UNIT.format(id="OLD", t="LightGBM regime head variant", extra=""))
        git("add", "-A")
        git("commit", "-q", "-m", "b")
        git("checkout", "-q", "-b", "f")
        (q / "NEW-BAD.yaml").write_text(_UNIT.format(id="NEW-BAD", t="LightGBM regime head variant", extra=""))
        (q / "NEW-GOOD.yaml").write_text(_UNIT.format(id="NEW-GOOD", t="meta-label overlay", extra=_GOOD))
        (q / "NEW-NONML.yaml").write_text(_UNIT.format(id="NEW-NONML", t="Donchian 20 vs 30", extra=""))
        git("add", "-A")
        git("commit", "-q", "-m", "f")
        f, c, st = scan(root, "trunk")
        check("graded state", st == "graded")
        check("NEW ML unit without the field FAILS", any("NEW-BAD" in x and "ml_consumer" in x for x in f))
        check("NEW ML unit with the field passes", not any("NEW-GOOD" in x for x in f))
        check("NEW non-ML unit passes", not any("NEW-NONML" in x for x in f))
        check("OLD unit grandfathered, but counted",
              not any("OLD" in x for x in f) and c["missing_or_bad"] == 2 and c["ml_units"] == 3)
        check("money count", c["money"] == 1)
        check("no_base fails nothing", scan(root, None)[0] == [])
        f2, _, st2 = scan(root, "does-not-exist")
        check("base_unresolved refuses rather than grants", st2 == "base_unresolved" and any("OLD" in x for x in f2))
    print(f"research-queue-ml-consumer-guard --self-test: {bad} failure(s)")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    import _dirty_tree  # noqa: PLC0415 -- path shim above; the shared dirty-tree notice
    _dirty_tree.warn()
    if a.self_test:
        return _self_test()
    failures, c, st = scan(REPO, a.base)
    print(f"research-queue-ml-consumer-guard: base_state={st} units={c['units']} ml_units={c['ml_units']} "
          f"missing_or_bad_ml_consumer={c['missing_or_bad']} not_applicable={c['not_applicable']} "
          f"money={c['money']} demo_floor={c['demo_floor']} failures={len(failures)}")
    for f in failures:
        print(f"::error::research-queue-ml-consumer-guard: {f}")
    if failures:
        return 1
    print("research-queue-ml-consumer-guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
