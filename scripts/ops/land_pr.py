#!/usr/bin/env python3
# wiring: manual-only - run by hand or by a lane before opening a PR; tests/test_land_pr.py covers it
"""Write the three landing files for a branch, with the slug and tier the guard would assign.

WHY (row AUTO-LANDING-FILES, plan docs/plans/OPS-AUTOMATION-INVENTORY-2026-10-13.md act M-c):
every PR needs `.github/pr-landing/<slug>.json`, `.github/pr-automerge-requests/<slug>.txt`
and `.github/merge-slots/<slug>.json`, and a wrong slug ("lane-" dropped) is the commonest
R11 failure. This writes all three from ONE derivation.

NOTHING HERE IS RE-DERIVED. The slug comes from `check_pr_landing.branch_slug`, the claim
from `claim_merge_slot` (`build_claim` / `branch_slot_rel`), and the tier from the guard's
own `TIER3_PATHS` / `TIER2_PATHS` / `LANDING_MACHINERY` / `unvouched_paths`, so the script
cannot drift from the check that grades its output.

THE TIER IS NEVER LOWER THAN THE GUARD'S. The diff decides:
  Tier-3 path   -> tier 3, hold  (tier_2_3_needs_approval)
  Tier-2 path   -> tier 2, hold  (tier_2_3_needs_approval)
  landing route -> tier 1, hold  (changes_landing_machinery, R12)
  outside TIER1_SURFACE -> tier 1, hold (unvouchable_paths, R14)
  otherwise     -> tier 1, self + arming file + merge-slot claim
`--tier` may only RAISE the result. A hold writes NO arming file (R10) and no claim (R13
applies only to an armed branch). A diff that cannot be read refuses rather than guessing.
It weakens no guard: `pr-landing-guard` still grades the files, and `--verify` runs it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import check_pr_landing as cpl  # noqa: E402
import claim_merge_slot as cms  # noqa: E402

HOLD_TEXT = {
    "tier_2_3_needs_approval": "touches Tier-{tier} paths ({paths}); needs explicit operator approval before merge",
    "changes_landing_machinery": "edits the landing route itself ({paths}); one human read before merge",
    "unvouchable_paths": "Tier-1 work touching paths outside TIER1_SURFACE ({paths}); a human merges",
}


class LandError(RuntimeError):
    pass


def classify(root: Path, base: str, branch: str, changed: list[str]) -> dict:
    """Return {tier, landing, hold_reason?, paths} for the diff. Pure over the guard's lists."""
    slug = cpl.branch_slug(branch)
    own = {f"{cpl.LANDING_DIR}/{slug}.json", f"{cpl.AUTOMERGE_DIR}/{slug}.txt",
           f"{cpl.BRANCH_SLOT_DIR}/{slug}.json"}
    changed = [p for p in changed if p not in own]
    b3 = [p for p in changed if cpl._match(p, cpl.TIER3_PATHS)]
    b2 = [p for p in changed if cpl._match(p, cpl.TIER2_PATHS) and p not in b3]
    if b3:
        return {"tier": 3, "landing": "hold", "hold_reason": "tier_2_3_needs_approval", "paths": b3}
    if b2:
        return {"tier": 2, "landing": "hold", "hold_reason": "tier_2_3_needs_approval", "paths": b2}
    machinery = [p for p in changed if cpl._match(p, cpl.LANDING_MACHINERY)]
    if machinery:
        return {"tier": 1, "landing": "hold", "hold_reason": "changes_landing_machinery", "paths": machinery}
    unv = cpl.unvouched_paths(root, base, changed)
    if unv:
        return {"tier": 1, "landing": "hold", "hold_reason": "unvouchable_paths", "paths": unv}
    return {"tier": 1, "landing": "self", "paths": []}


def build_declaration(cls: dict, why: str, min_tier: int | None = None) -> dict:
    tier = max(cls["tier"], min_tier or 1)
    landing = cls["landing"]
    reason = cls.get("hold_reason")
    if tier > cls["tier"]:                 # operator/lane raised it: a raise always holds
        landing, reason = "hold", "tier_2_3_needs_approval"
    decl: dict = {"tier": tier, "landing": landing}
    if landing == "hold":
        paths = ", ".join(sorted(cls["paths"])[:3]) or "the diff"
        decl["hold_reason"] = reason
        decl["hold_text"] = HOLD_TEXT[reason].format(tier=tier, paths=paths)
    decl["why"] = why
    if len(why.strip()) < cpl.MIN_TEXT:
        raise LandError(f"--why needs at least {cpl.MIN_TEXT} chars (R3): the tier judgement in your words")
    return decl


def land(root: Path, branch: str, base: str, held_by: str, why: str,
         min_tier: int | None = None, dry_run: bool = False, claimed_at: str | None = None) -> dict:
    changed = cpl.changed_paths(root, base)
    if changed is None:
        raise LandError(f"cannot diff against {base}: refusing to guess a tier")
    cls = classify(root, base, branch, changed)
    decl = build_declaration(cls, why, min_tier)
    slug = cpl.branch_slug(branch)
    out = {"slug": slug, "declaration": decl, "files": []}
    decl_rel = f"{cpl.LANDING_DIR}/{slug}.json"
    writes = {decl_rel: json.dumps(decl, indent=2, ensure_ascii=False) + "\n"}
    if decl["landing"] == "self":
        writes[f"{cpl.AUTOMERGE_DIR}/{slug}.txt"] = f"auto-merge: {why.strip()[:80]}\n"
        claim = cms.build_claim(branch, held_by, "", claimed_at)
        writes[cms.branch_slot_rel(branch)] = json.dumps(claim, indent=2, ensure_ascii=False) + "\n"
    for rel, text in writes.items():
        out["files"].append(rel)
        if not dry_run:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("branch", nargs="?", help="branch name (default: current branch)")
    ap.add_argument("--held-by", required=True, help="session id recorded on the merge-slot claim")
    ap.add_argument("--why", required=True, help="tier judgement in your own words (>=20 chars)")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--tier", type=int, choices=(1, 2, 3), help="may only RAISE the computed tier")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="after writing, run pr-landing-guard (needs the files COMMITTED)")
    a = ap.parse_args(argv)
    branch = a.branch or cpl.current_branch(REPO)
    if not branch:
        ap.error("no branch given and none detected")
    try:
        res = land(REPO, branch, a.base, a.held_by, a.why, a.tier, a.dry_run)
    except (LandError, cms.SpliceError) as exc:
        print(f"land_pr: {exc}", file=sys.stderr)
        return 2
    d = res["declaration"]
    print(f"land_pr: slug={res['slug']} tier={d['tier']} landing={d['landing']}"
          + (f" ({d['hold_reason']})" if d["landing"] == "hold" else ""))
    for f in res["files"]:
        print(f"  {'would write' if a.dry_run else 'wrote'} {f}")
    if d["landing"] == "self":
        print("  next: commit these, push, and open the PR NOT as a draft (a draft is refused by design).")
    if a.verify and not a.dry_run:
        return subprocess.call([sys.executable, str(REPO / "scripts/ci/check_pr_landing.py"),
                                "--base", a.base, "--branch", branch])
    return 0


if __name__ == "__main__":
    sys.exit(main())
