#!/usr/bin/env python3
# wiring: scripts/ci/run_guards.py (family-retirement-guard)
"""family-retirement-guard -- a FAMILY (an idea) cannot be retired without a review record.

WHY (operator directive 2026-10-16, via the manager, lane RESEARCH-ENGINE-1016): "do not give up on an
IDEA because one configuration failed a few tests ... it may mean we tested it wrong. Equally, don't sink
resources into ideas with no potential: if an idea is viable there should be outside information on how
to do it better." A cell FAIL closes the CONFIGURATION it tested -- automatic and fine. Retiring the
FAMILY is a different act and needs evidence of a different kind: a check that the test design was
sound, breadth across configs / windows / instruments, outside evidence with sources, and a stated
reason the idea itself is dead. Policy and thresholds: scripts/research/family_retirement_policy.yaml
(PROVISIONAL; lane IDEA-REVIEW-1016 proposes the protocol details).

WHAT IT REFUSES
  R1  a STRUCTURED retirement whose family has no valid review record at research/family_reviews/<f>.yaml:
        docs/plans/ml-plan-items.yaml  families.<f>.state in policy.retired_states
        research/queue/**/*.yaml        retires_family: <f>
        research/programmes/*.yaml      a node with retires_family: <f>
      (whole-tree: a structured retirement is never grandfathered, it is a claim the record must back)
  R2  a review record that is invalid: missing fields, breadth below the policy minimums, fewer outside
      sources than required, test_design_check.verdict not in the allowed list ("flawed" = we tested it
      wrong: fix the test, do not retire), or a reason shorter than reason_chars
  R3  (with --base) an ADDED line on a research text surface that uses family-closure language
      (policy.closure_language) without citing `family_review: <f>` / research/family_reviews/<f>.yaml
      for a family whose review is valid. Added lines only: history is not re-litigated.

Config-level language is never refused: "this cell FAILED", "honest negative for this config", "this
lever setting does not earn its place on <leg>".
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[2]
POLICY = Path("scripts/research/family_retirement_policy.yaml")
REVIEWS = Path("research/family_reviews")
ML_PLAN = Path("docs/plans/ml-plan-items.yaml")
_NEG_RE = re.compile(r"\b(not|never|no longer|nor|doesn't|does not|do not|don't|cannot|isn't|is not)\b[^.;]*$", re.I)
_CITE_RE = re.compile(r"(?:family_review:\s*|research/family_reviews/)([A-Za-z0-9_.\-]+?)(?:\.ya?ml)?\b")


def _yaml():
    import yaml
    return yaml


def load_policy(root: Path) -> Dict[str, Any]:
    return _yaml().safe_load((root / POLICY).read_text(encoding="utf-8"))


def review_problems(root: Path, family: str, policy: Dict[str, Any]) -> List[str]:
    """Empty when research/family_reviews/<family>.yaml is a valid retirement record."""
    p = root / REVIEWS / f"{family}.yaml"
    if not p.is_file():
        return [f"no review record {p.relative_to(root).as_posix()}"]
    try:
        r = _yaml().safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001 -- an unreadable record is no record
        return [f"{p.name} unreadable ({e})"]
    mins = policy.get("minimums") or {}
    out = []
    for k in ("family", "decided_at", "reviewed_by", "test_design_check", "breadth", "outside_evidence",
              "reason_idea_dead"):
        if not r.get(k):
            out.append(f"missing `{k}`")
    if r.get("family") and str(r["family"]) != family:
        out.append(f"`family` is {r['family']!r}, file is {family}")
    tdc = r.get("test_design_check") or {}
    if isinstance(tdc, dict):
        if str(tdc.get("verdict")) not in [str(v) for v in policy.get("test_design_verdicts_allowed") or ["sound"]]:
            out.append(f"test_design_check.verdict is {tdc.get('verdict')!r}: a flawed or unchecked test design "
                       "means fix the test, not retire the idea")
        if not str(tdc.get("notes") or "").strip():
            out.append("test_design_check.notes is empty: say what was checked")
    br = r.get("breadth") or {}
    if isinstance(br, dict):
        for key, mkey in (("configs", "configs_tested"), ("windows", "windows_tested"),
                          ("instruments", "instruments_tested")):
            have = len(br.get(key) or [])
            need = int(mins.get(mkey) or 0)
            if key == "instruments" and have == 1 and str(br.get("single_instrument_why") or "").strip():
                continue
            if have < need:
                out.append(f"breadth.{key}: {have} < {need} ({mkey})")
    srcs = [s for s in (r.get("outside_evidence") or []) if isinstance(s, dict)
            and str(s.get("source") or "").strip() and str(s.get("finding") or "").strip()]
    if len(srcs) < int(mins.get("outside_sources") or 0):
        out.append(f"outside_evidence: {len(srcs)} source(s) with `source` + `finding` < {mins.get('outside_sources')} "
                   "-- if a viable idea exists, someone outside has written about doing it better")
    if len(str(r.get("reason_idea_dead") or "").strip()) < int(mins.get("reason_chars") or 0):
        out.append(f"reason_idea_dead shorter than {mins.get('reason_chars')} chars")
    return out


def structured_retirements(root: Path, policy: Dict[str, Any]) -> List[Dict[str, str]]:
    """[{family, where}] for every structured retirement in the tree."""
    yaml = _yaml()
    states = {str(s) for s in policy.get("retired_states") or []}
    out: List[Dict[str, str]] = []
    plan = root / ML_PLAN
    if plan.is_file():
        doc = yaml.safe_load(plan.read_text(encoding="utf-8")) or {}
        for fam, f in (doc.get("families") or {}).items():
            if isinstance(f, dict) and str(f.get("state") or "") in states:
                out.append({"family": str(fam), "where": f"{ML_PLAN.as_posix()} families.{fam}.state={f['state']}"})
    for p in sorted((root / "research" / "queue").rglob("*.yaml")):
        try:
            u = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 -- the queue validators own unreadable units
            continue
        if isinstance(u, dict) and u.get("retires_family"):
            out.append({"family": str(u["retires_family"]), "where": p.relative_to(root).as_posix()})
    for p in sorted((root / "research" / "programmes").glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for n in doc.get("nodes") or []:
            if isinstance(n, dict) and n.get("retires_family"):
                out.append({"family": str(n["retires_family"]), "where": f"{p.relative_to(root).as_posix()} {n.get('id')}"})
    return out


def _added_lines(root: Path, base: str, globs: List[str]) -> List[tuple]:
    mb = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    if not mb:
        return []
    diff = subprocess.run(["git", "diff", "-U0", "--no-color", mb, "HEAD", "--", *globs], cwd=root,
                          capture_output=True, text=True).stdout
    out, path = [], None
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            path = ln[6:] if ln.startswith("+++ b/") else None
        elif ln.startswith("+") and not ln.startswith("+++") and path:
            out.append((path, ln[1:]))
    return out


def closure_text_problems(lines: List[tuple], policy: Dict[str, Any], valid: set) -> List[str]:
    pats = [re.compile(p, re.I) for p in policy.get("closure_language") or []]
    out = []
    for path, text in lines:
        if not any(fnmatch.fnmatch(path, g) for g in policy.get("text_surfaces") or []):
            continue
        hits = [m for p in pats for m in p.finditer(text)]
        # A NEGATED closure ("this does not kill the idea", "not that the family is dead") is the opposite
        # claim -- exactly the wording the directive wants -- so it never needs a review.
        hits = [m for m in hits if not _NEG_RE.search(text[max(0, m.start() - 30):m.start()])]
        if not hits:
            continue
        cited = set(_CITE_RE.findall(text))
        if cited and cited <= valid:
            continue
        why = (f"cites {sorted(cited - valid)} with no valid review" if cited else "cites no family review")
        out.append(f"R3 {path}: family-closure language {why}: {text.strip()[:140]!r} -- say what CONFIG failed, "
                   "or write research/family_reviews/<family>.yaml and cite it")
    return out


def check(root: Path, base: Optional[str]) -> List[str]:
    policy = load_policy(root)
    problems: List[str] = []
    valid = set()
    for p in sorted((root / REVIEWS).glob("*.yaml")):
        fam = p.stem
        bad = review_problems(root, fam, policy)
        if bad:
            problems += [f"R2 {p.relative_to(root).as_posix()}: {b}" for b in bad]
        else:
            valid.add(fam)
    for r in structured_retirements(root, policy):
        if r["family"] not in valid:
            problems.append(f"R1 {r['where']}: retires family {r['family']!r} without a valid review record "
                            f"({'; '.join(review_problems(root, r['family'], policy))})")
    if base:
        problems += closure_text_problems(_added_lines(root, base, ["research", "docs", "comms"]), policy, valid)
    return problems


def _self_test() -> int:
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "research" / "queue").mkdir(parents=True)
        (r / "research" / "programmes").mkdir(parents=True)
        (r / REVIEWS).mkdir(parents=True)
        (r / "docs" / "plans").mkdir(parents=True)
        (r / POLICY).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_REPO / POLICY, r / POLICY)
        pol = load_policy(r)
        (r / ML_PLAN).write_text("families:\n  deep_sequence: {history: [FAIL], state: retired}\n  gbdt: {history: []}\n")
        (r / "research" / "queue" / "RQ-1.yaml").write_text("id: RQ-1\nstatus: retired\nretires_family: giveback_stop\n")
        p = check(r, None)
        assert sum(x.startswith("R1") for x in p) == 2, p           # two structured retirements, no records
        good = ("family: deep_sequence\ndecided_at: '2030-01-01'\nreviewed_by: lane X\n"
                "test_design_check: {verdict: sound, notes: 'label, horizon and leakage re-checked'}\n"
                "breadth: {configs: [tcn, lstm, patchtst], windows: [w1, w2], instruments: [BTC, ETH]}\n"
                "outside_evidence:\n  - {source: 'paper A', finding: 'no edge at this horizon'}\n"
                "  - {source: 'repo B', finding: 'same'}\n"
                "reason_idea_dead: '" + "x" * 90 + "'\n")
        (r / REVIEWS / "deep_sequence.yaml").write_text(good)
        p = check(r, None)
        assert not any("deep_sequence" in x for x in p) and any("giveback_stop" in x for x in p), p
        # R2: flawed design, thin breadth, one source -> refused, and the retirement it backs is refused too
        (r / REVIEWS / "giveback_stop.yaml").write_text(
            good.replace("deep_sequence", "giveback_stop").replace("verdict: sound", "verdict: flawed")
                .replace("[tcn, lstm, patchtst]", "[gb1R]").replace("  - {source: 'repo B', finding: 'same'}\n", ""))
        bad = review_problems(r, "giveback_stop", pol)
        assert any("flawed" in b for b in bad) and any("breadth.configs" in b for b in bad) \
            and any("outside_evidence" in b for b in bad), bad
        assert any(x.startswith("R1 research/queue/RQ-1.yaml") for x in check(r, None))
        # single instrument allowed only with a reason
        one = good.replace("instruments: [BTC, ETH]", "instruments: [MES]")
        (r / REVIEWS / "deep_sequence.yaml").write_text(one)
        assert any("breadth.instruments" in b for b in review_problems(r, "deep_sequence", pol))
        (r / REVIEWS / "deep_sequence.yaml").write_text(one.replace(
            "instruments: [MES]", "instruments: [MES], single_instrument_why: 'only futures book we run'"))
        assert review_problems(r, "deep_sequence", pol) == []
        # R3: closure language on an added line; config language passes; a valid citation passes
        lines = [("research/queue/RQ-2.yaml", "result: the giveback family is dead after one FAIL"),
                 ("research/queue/RQ-3.yaml", "result: this cell FAILED -- honest negative for this config"),
                 ("docs/plans/ml-plan-items.yaml", "close: line is exhausted (family_review: deep_sequence)"),
                 ("src/x.py", "# the family is dead"),                  # not a research surface
                 ("research/programmes/03.yaml", "retire the whole family (family_review: nope)"),
                 ("research/queue/RQ-4.yaml", "A NULL/FAIL here does not kill the idea"),
                 ("research/queue/RQ-5.yaml", "INDETERMINATE says n was the limit, not that the family is dead.")]
        t = closure_text_problems(lines, pol, {"deep_sequence"})
        assert len(t) == 2 and "RQ-2" in t[0] and "nope" in t[1], t
    print("family-retirement-guard self-test OK")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--base", default=None, help="also grade ADDED lines vs this base (R3)")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    problems = check(_REPO, args.base)
    for p in problems:
        print(f"::error::family-retirement-guard: {p}")
    print("family-retirement-guard: " + ("OK" if not problems else f"FAIL ({len(problems)})"))
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
