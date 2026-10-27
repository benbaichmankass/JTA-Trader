#!/usr/bin/env python3
# wiring: manual-only - run by the manager (or a DESK-18B lane) to stage a batch for a spawned plan-session judge; no schedule consumes it.
"""DESK-18B plan-session judging: stage N masked packets on an orphan branch, and take the judged rows back.

Replaces the retired API path (`desk_judge_api.py`, operator 2026-10-27 "No API: plan sessions only"). Judging is done by
ONE spawned Sonnet session per batch, reading packets one at a time from an orphan branch that holds nothing else
(no CLAUDE.md, no repo code, no mask key), then pushing `judged.jsonl` back to that branch.

  stage   packets.jsonl (from `desk_gen_replay_driver.py packets`) -> <workdir>/ with JUDGE-PROTOCOL.md + packets/pNN.json,
          committed as an orphan branch `desk/judge-<tag>` and pushed. The mask key is NEVER copied: it stays beside the
          driver's output on the machine that built the packets.
  collect fetch `desk/judge-<tag>`, read judged.jsonl, write proposals.jsonl for `desk_gen_replay_driver.py intake`.

The session brief for the spawned judge is `BRIEF` below (printed by `stage`); spawn with source_revision and
outcome_branch both set to the staged branch, model claude-sonnet-5-5, clone_depth 1.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

BRIEF = """You are a blind judge. This checkout holds only JUDGE-PROTOCOL.md and packets/p{first:02d}.json ... p{last:02d}.json. \
Read JUDGE-PROTOCOL.md first, then judge the {n} packets in order, ONE AT A TIME (open the file, decide, move on; do not let one \
packet influence another). Use no web, no other files, no subagents, no tools other than reading those files and the final git \
commit/push. Do not look at git history or any other branch.

Write your answers to judged.jsonl at the repo root: for each packet, exactly the JSON line(s) the protocol specifies (one \
no_trade row, or 1-2 propose_entry rows), using the packet's meta.packet_id. Nothing else in the file. Then `git add judged.jsonl \
&& git commit -m "{tag} judged rows" && git push origin HEAD:{branch}`. Finish with a one-line message: how many rows you wrote \
and how many were propose_entry."""


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


def stage(a: argparse.Namespace) -> int:
    src = Path(a.packets_dir)
    rows = [json.loads(ln) for ln in (src / "packets.jsonl").read_text().splitlines() if ln.strip()]
    work = Path(a.workdir)
    if work.exists():
        shutil.rmtree(work)
    (work / "packets").mkdir(parents=True)
    for i, r in enumerate(rows):
        (work / "packets" / f"p{a.offset + i:02d}.json").write_text(json.dumps(r["packet"], separators=(",", ":")))
    shutil.copy(src / "JUDGE-PROTOCOL.md", work / "JUDGE-PROTOCOL.md")
    branch = f"desk/judge-{a.tag}"
    _git(work, "init", "-q", "-b", branch)
    _git(work, "-c", "user.email=desk@invalid", "-c", "user.name=desk-stage", "add", "-A")
    _git(work, "-c", "user.email=desk@invalid", "-c", "user.name=desk-stage", "commit", "-qm", f"stage {len(rows)} masked packets")
    _git(work, "remote", "add", "origin", a.remote)
    _git(work, "push", "-q", "origin", branch)
    print(json.dumps({"branch": branch, "packets": len(rows), "brief": BRIEF.format(
        first=a.offset, last=a.offset + len(rows) - 1, n=len(rows), tag=a.tag, branch=branch)}, indent=1))
    return 0


def collect(a: argparse.Namespace) -> int:
    branch = f"desk/judge-{a.tag}"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    _git(Path("."), "fetch", "-q", a.remote, branch)
    text = _git(Path("."), "show", "FETCH_HEAD:judged.jsonl")
    rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    (out / "proposals.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    print(json.dumps({"rows": len(rows), "propose_entry": sum(r.get("action") == "propose_entry" for r in rows),
                      "no_trade": sum(r.get("action") == "no_trade" for r in rows)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--packets-dir", required=True, help="output dir of desk_gen_replay_driver.py packets")
    s.add_argument("--workdir", required=True, help="scratch dir for the orphan checkout (outside the repo)")
    s.add_argument("--tag", required=True)
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--remote", required=True)
    s.set_defaults(fn=stage)
    c = sub.add_parser("collect")
    c.add_argument("--tag", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--remote", default="origin")
    c.set_defaults(fn=collect)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
