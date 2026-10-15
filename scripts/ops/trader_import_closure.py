#!/usr/bin/env python3
"""The ``ict-trader-live`` restart gate: which repo files the trader LOADS.

Checklist row ``TRADER-RESTART-GATE`` (operator decision 2026-10-15, "Build it
(Recommended)", Phase 1). ``scripts/deploy_pull_restart.sh`` restarts every
long-running ``ict-*`` unit on a runtime diff. A merge that changes only a
web-api router or an ops CLI does not change one byte the trader process has
loaded, yet it bounced the trader (MEASURED 2026-10-15 over 879 first-parent
merges: 42 of 168 runtime merges). Each restart can land inside a leg's
decision window, so a needless one is not free.

This module decides, for one deploy, whether the TRADER must restart:

    restart iff some changed path is
      (a) a ``.py`` in the trader's static import closure from ``src.main``, or
      (b) a non-``.py`` path outside the deploy's non-runtime set, or
      (c) a ``.py`` outside ``src/`` and ``scripts/`` that is outside that set.

Only a ``src/**.py`` or ``scripts/**.py`` file outside the closure lets the
trader stay up. Every other unit keeps the deploy's existing rule.

THE CLOSURE is an AST walk from ``src/main.py``: every ``import`` /
``from … import`` anywhere in a file (module level, inside functions, inside
``try`` and ``if TYPE_CHECKING``), relative imports, ``importlib.import_module``
/ ``__import__`` with a literal name, and the ``__init__.py`` of every package
on the way. A non-literal dynamic import cannot be followed; its call site is
reported (``dynamic_sites``) and pinned by
``tests/test_trader_import_closure.py`` so a new one has to be looked at.

FAIL-SAFE, everywhere: when the decision cannot be made it is RESTART. A
missing or unreadable committed closure, a file in the closure that does not
parse, a closure computed live that fails, an empty change list: RESTART. A
missed restart pins the trader to stale code; a needless one is the status quo.

The committed closure (``config/trader_import_closure.txt``) is recomputed by
the ``trader-import-closure`` guard (``--check``) on every PR that touches a
``.py``; the deploy ALSO recomputes it live on the VM and uses the UNION, so a
closure that drifted on ``main`` can only cause a restart, never prevent one.

CLI::

    trader_import_closure.py generate [--check]       # write / verify the committed file
    trader_import_closure.py decide --root R < paths  # first line RESTART|SKIP + reasons
    trader_import_closure.py replay --since ISO --until ISO [--ref main]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY_FILE = "src/main.py"
CLOSURE_REL = "config/trader_import_closure.txt"

#: The deploy's non-runtime path set. MUST equal the RUNTIME_CHANGES ``grep -vE``
#: in scripts/deploy_pull_restart.sh and diag's ``_NON_RUNTIME_PATHS_RE``;
#: tests/test_diag_restart_pending_lockstep.py pins all three equal.
NON_RUNTIME_PATHS_RE = re.compile(
    r"^(docs/|tests/|\.claude/|\.github/|[^/]+\.md$|research/|runtime_logs/"
    r"|scripts/research/|scripts/ci/|comms/research/|comms/strategy_evidence/|comms/macro/"
    r"|tools/phone-executor/|tools/phone-probe/)"
)

#: ...except these scripts/research modules, which the WEB-API imports in-process
#: (the deploy's IN_PROCESS_CHANGES grep; pinned by the same lockstep test). They
#: make a diff "runtime" for the deploy -- the trader rule below then decides on
#: them like any other scripts/ .py.
IN_PROCESS_RUNTIME_PATHS_RE = re.compile(
    r"^scripts/research/(dispatch_queue|e35_bracket_geometry_sweep|m20_fleet_exit_sweep|m20_wf_effective|queue_grade|queue_replenish|queue_throughput|research_queue)\.py$"
)

RESTART = "RESTART"
SKIP = "SKIP"


# ---------------------------------------------------------------------------
# sources: the working tree, or a git tree (for the replay)
# ---------------------------------------------------------------------------


class FsSource:
    """Files of a checkout on disk."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def is_file(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def is_dir(self, rel: str) -> bool:
        return (self.root / rel).is_dir()

    def py_files_under(self, rel_dir: str) -> List[str]:
        base = self.root / rel_dir
        return sorted(str(p.relative_to(self.root)).replace("\\", "/")
                      for p in base.rglob("*.py") if p.is_file())

    def read(self, rel: str) -> Optional[str]:
        try:
            return (self.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


class GitTreeSource:
    """Files of one commit, read through one ``git cat-file --batch``."""

    def __init__(self, repo: Path, sha: str):
        self.repo, self.sha = Path(repo), sha
        out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", sha],
                             capture_output=True, text=True, check=True).stdout
        self.files: Set[str] = set(out.splitlines())
        self.dirs: Set[str] = set()
        for f in self.files:
            parts = f.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                self.dirs.add("/".join(parts[:i]))
        self._proc: Optional[subprocess.Popen] = None

    def is_file(self, rel: str) -> bool:
        return rel in self.files

    def is_dir(self, rel: str) -> bool:
        return rel in self.dirs

    def py_files_under(self, rel_dir: str) -> List[str]:
        return sorted(f for f in self.files if f.startswith(rel_dir + "/") and f.endswith(".py"))

    def read(self, rel: str) -> Optional[str]:
        if rel not in self.files:
            return None
        if self._proc is None:
            self._proc = subprocess.Popen(["git", "-C", str(self.repo), "cat-file", "--batch"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(f"{self.sha}:{rel}\n".encode())
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().decode().split()
        if len(header) < 3 or header[1] == "missing":
            return None
        data = self._proc.stdout.read(int(header[2]))
        self._proc.stdout.read(1)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def close(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc = None


# ---------------------------------------------------------------------------
# the walk
# ---------------------------------------------------------------------------


@dataclass
class Closure:
    files: Set[str] = field(default_factory=set)
    #: ``path:line`` of import calls whose module name is not a literal
    dynamic_sites: List[str] = field(default_factory=list)
    #: closure files that could not be read or parsed -- their imports are unknown
    incomplete: List[str] = field(default_factory=list)


_IMPORT_FUNCS = {"import_module", "__import__"}
#: a string literal shaped like a dotted module path (``a.b`` / ``a.b.C`` / ``a.b.``)
_DOTTED_REF = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\.?$")
#: sentinel "name" meaning: every module under this package, recursively
PACKAGE_PREFIX = "<package-prefix>"


def _module_files(src, dotted: str, near_dir: Optional[str]) -> Optional[List[str]]:
    """Repo files executed by importing ``dotted``: every package ``__init__.py``
    on the way plus the module itself. None when it is not a repo module
    (stdlib / third-party)."""
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None
    for base in ([""] + ([near_dir] if near_dir else [])):
        prefix = f"{base}/" if base else ""
        if not (src.is_dir(prefix + parts[0]) or src.is_file(prefix + parts[0] + ".py")):
            continue
        out: List[str] = []
        for i in range(1, len(parts) + 1):
            stem = prefix + "/".join(parts[:i])
            if src.is_file(stem + ".py"):
                out.append(stem + ".py")
                break  # a module, not a package: nothing deeper is a file
            if src.is_dir(stem):
                if src.is_file(stem + "/__init__.py"):
                    out.append(stem + "/__init__.py")
                continue
            break
        return out
    return None


def _package_of(rel: str) -> List[str]:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


def _resolve_relative(rel: str, level: int, module: Optional[str]) -> Optional[str]:
    pkg = _package_of(rel)
    if level - 1 > len(pkg):
        return None
    base = pkg[: len(pkg) - (level - 1)]
    return ".".join(base + ([module] if module else []))


def _imports_of(rel: str, tree: ast.AST) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
    """``[(dotted, [names imported from it]), ...]`` and non-literal call sites."""
    found: List[Tuple[str, List[str]]] = []
    dynamic: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.append((a.name, []))
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names if a.name != "*"]
            if node.level:
                target = _resolve_relative(rel, node.level, node.module)
                if target is None:
                    continue
                found.append((target, names))
            elif node.module:
                found.append((node.module, names))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and _DOTTED_REF.match(node.value)):
            # A module named in a string -- a qualname handed to a resolver
            # (``_connector_class_id("src.exchange.x", ...)``) or the literal
            # prefix of a computed one (``f"src.units.strategies.{name}"``).
            # Conservative: a string that only LOOKS like a module path costs a
            # restart, never a skip.
            found.append((node.value, [PACKAGE_PREFIX] if node.value.endswith(".") else []))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name not in _IMPORT_FUNCS or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                target = arg.value
                if target.startswith("."):
                    pkg = None
                    for kw in node.keywords:
                        if kw.arg == "package" and isinstance(kw.value, ast.Constant):
                            pkg = kw.value.value
                    if not pkg and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        pkg = node.args[1].value
                    if not isinstance(pkg, str):
                        dynamic.append(f"{rel}:{node.lineno}")
                        continue
                    level = len(target) - len(target.lstrip("."))
                    base = pkg.split(".")
                    base = base[: len(base) - (level - 1)] if level > 1 else base
                    target = ".".join(base + ([target.lstrip(".")] if target.lstrip(".") else []))
                found.append((target, []))
            else:
                dynamic.append(f"{rel}:{node.lineno}")
    return found, dynamic


def compute_closure(src, entry: str = ENTRY_FILE) -> Closure:
    """Static import closure of ``entry`` over ``src`` (an Fs/GitTree source)."""
    out = Closure()
    todo = [entry]
    # the package __init__ files python runs to import ``src.main`` itself
    for f in _module_files(src, entry[:-3].replace("/", "."), None) or []:
        if f not in todo:
            todo.append(f)
    while todo:
        rel = todo.pop()
        if rel in out.files:
            continue
        out.files.add(rel)
        text = src.read(rel)
        if text is None:
            out.incomplete.append(rel)
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError):
            out.incomplete.append(rel)
            continue
        found, dynamic = _imports_of(rel, tree)
        out.dynamic_sites.extend(dynamic)
        near = rel.rsplit("/", 1)[0] if "/" in rel else None
        for dotted, names in found:
            if names == [PACKAGE_PREFIX]:
                dotted = dotted.rstrip(".")
                pkg_files = _module_files(src, dotted, None)
                pkg_dir = dotted.replace(".", "/")
                if pkg_files is None or not src.is_dir(pkg_dir):
                    continue
                todo.extend(f for f in pkg_files if f not in out.files)
                todo.extend(f for f in src.py_files_under(pkg_dir) if f not in out.files)
                continue
            files = _module_files(src, dotted, near)
            if files is None:
                continue
            todo.extend(f for f in files if f not in out.files)
            # ``from pkg import sub`` imports the SUBMODULE when ``sub`` is one
            for n in names:
                sub = _module_files(src, f"{dotted}.{n}", near)
                if sub:
                    todo.extend(f for f in sub if f not in out.files)
    out.dynamic_sites.sort()
    out.incomplete.sort()
    return out


# ---------------------------------------------------------------------------
# the committed file
# ---------------------------------------------------------------------------

_HEADER = """\
# GENERATED by scripts/ops/trader_import_closure.py generate -- do not edit.
# The repo files ict-trader-live loads (static import closure of src/main.py).
# scripts/deploy_pull_restart.sh skips restarting the trader only for a diff
# whose src/ and scripts/ .py files are ALL outside this list (TRADER-RESTART-GATE).
# Drift is a CI failure (guard trader-import-closure); regenerate with
#   python3 scripts/ops/trader_import_closure.py generate
"""


def render(closure: Closure) -> str:
    return _HEADER + "".join(f"{f}\n" for f in sorted(closure.files))


def parse_closure_text(text: str) -> Set[str]:
    return {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")}


def read_committed(root: Path) -> Optional[Set[str]]:
    """The committed closure, or None when missing / unreadable / empty."""
    try:
        files = parse_closure_text((Path(root) / CLOSURE_REL).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return files or None


# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------


def classify_path(path: str, closure: Set[str],
                  non_runtime_re: "re.Pattern[str]" = NON_RUNTIME_PATHS_RE) -> Optional[str]:
    """Why ``path`` forces a trader restart, or None when it does not."""
    if path in closure:
        return "in_closure"  # wins over the non-runtime set: the trader loads it
    if non_runtime_re.match(path):
        return None
    if not path.endswith(".py"):
        return "non_py_runtime"
    if not path.startswith(("src/", "scripts/")):
        return "py_outside_src_scripts"
    return None


def decide(changed: Sequence[str], closure: Optional[Set[str]],
           non_runtime_re: "re.Pattern[str]" = NON_RUNTIME_PATHS_RE) -> Tuple[str, List[str]]:
    """``(RESTART|SKIP, reasons)``. Fail-safe: no closure or no paths is RESTART."""
    paths = [p for p in (c.strip() for c in changed) if p]
    if closure is None:
        return RESTART, ["closure unavailable (missing, unreadable or incomplete)"]
    if not paths:
        return RESTART, ["empty change list"]
    reasons = []
    for p in paths:
        why = classify_path(p, closure, non_runtime_re)
        if why:
            reasons.append(f"{why}: {p}")
    if reasons:
        return RESTART, reasons
    return SKIP, [f"{len(paths)} changed path(s), none loaded by the trader"]


def deploy_closure(root: Path) -> Tuple[Optional[Set[str]], List[str]]:
    """The set the deploy decides on: committed file UNION a live recompute.

    None (= restart) if the committed file is missing/unreadable, the live
    walk raises, or any closure file could not be parsed."""
    notes: List[str] = []
    committed = read_committed(root)
    if committed is None:
        return None, [f"{CLOSURE_REL} missing or unreadable"]
    try:
        live = compute_closure(FsSource(root))
    except Exception as exc:  # noqa: BLE001 - any failure is fail-safe RESTART
        return None, [f"live closure walk failed: {type(exc).__name__}: {exc}"]
    if live.incomplete:
        return None, ["closure files could not be parsed: " + ", ".join(live.incomplete[:5])]
    extra = sorted(live.files - committed)
    if extra:
        notes.append(f"committed closure is stale: {len(extra)} live file(s) missing, e.g. {extra[:3]}")
    return committed | live.files, notes


# ---------------------------------------------------------------------------
# the replay
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout


def replay(repo: Path, since: str, until: str, ref: str = "origin/main",
           progress: Optional[Callable[[str], None]] = None) -> Dict[str, object]:
    """Classify every first-parent merge on ``ref`` in [since, until) the way the
    deploy would if it ran once per merge (the real deploy batches per ~5-min
    sync tick, so real restarts are <= these counts). The closure for each
    merge is recomputed from THAT merge's tree."""
    log = _git(repo, "log", "--first-parent", "--format=%H %P", f"--since={since}",
               f"--until={until}", ref).splitlines()
    rows = []
    counts = {"merges": 0, "non_runtime": 0, "runtime": 0, "skip": 0, "restart": 0,
              "no_parent": 0}
    forcing: Dict[str, int] = {}
    for line in log:
        sha, *parents = line.split()
        counts["merges"] += 1
        if not parents:
            counts["no_parent"] += 1
            continue
        changed = [p for p in _git(repo, "diff", "--no-renames", "--name-only", parents[0],
                                   sha).splitlines() if p]
        runtime = [p for p in changed if not NON_RUNTIME_PATHS_RE.match(p)
                   or IN_PROCESS_RUNTIME_PATHS_RE.match(p)]
        if changed and not runtime:
            counts["non_runtime"] += 1
            rows.append({"sha": sha, "class": "non_runtime"})
            continue
        counts["runtime"] += 1
        src = GitTreeSource(repo, sha)
        try:
            cl = compute_closure(src)
        finally:
            src.close()
        closure = None if cl.incomplete else cl.files
        verdict, reasons = decide(changed, closure)
        counts["skip" if verdict == SKIP else "restart"] += 1
        if verdict == RESTART:
            # merges per forcing area (each merge counted once per area)
            areas = set()
            for r in reasons:
                p = r.split(": ", 1)[-1]
                areas.add("/".join(p.split("/")[:2]) if "/" in p else p)
            for top in areas:
                forcing[top] = forcing.get(top, 0) + 1
        rows.append({"sha": sha, "class": verdict.lower(), "closure_size": len(cl.files),
                     "reasons": reasons[:5]})
        if progress:
            progress(f"{sha[:8]} {verdict}")
    top = sorted(forcing.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    return {"since": since, "until": until, "ref": ref, "counts": counts,
            "top_restart_forcing_areas_by_merge": top, "rows": rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_generate(args) -> int:
    root = Path(args.root)
    cl = compute_closure(FsSource(root))
    if cl.incomplete:
        print("trader-import-closure: could not parse: " + ", ".join(cl.incomplete), file=sys.stderr)
        return 2
    text = render(cl)
    path = root / CLOSURE_REL
    if args.check:
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current != text:
            have = parse_closure_text(current)
            add, drop = sorted(cl.files - have), sorted(have - cl.files)
            print(f"trader-import-closure: DRIFT -- {CLOSURE_REL} is not the trader's import "
                  f"closure ({len(add)} missing, {len(drop)} stale).", file=sys.stderr)
            for f in add[:20]:
                print(f"  + {f}", file=sys.stderr)
            for f in drop[:20]:
                print(f"  - {f}", file=sys.stderr)
            print("Regenerate: python3 scripts/ops/trader_import_closure.py generate", file=sys.stderr)
            return 1
        print(f"trader-import-closure: OK ({len(cl.files)} files, "
              f"{len(cl.dynamic_sites)} non-literal dynamic import site(s))")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote {CLOSURE_REL}: {len(cl.files)} files")
    return 0


def _cmd_decide(args) -> int:
    """Prints ``RESTART`` or ``SKIP`` on line 1, then reasons. Always exit 0 when a
    verdict was printed; the deploy treats anything but a first line of exactly
    ``SKIP`` as RESTART."""
    try:
        changed = sys.stdin.read().splitlines()
        closure, notes = deploy_closure(Path(args.root))
        verdict, reasons = decide(changed, closure)
    except Exception as exc:  # noqa: BLE001 - fail-safe
        print(RESTART)
        print(f"decision failed: {type(exc).__name__}: {exc}")
        return 0
    print(verdict)
    for r in notes + reasons[:20]:
        print(r)
    if len(reasons) > 20:
        print(f"... +{len(reasons) - 20} more")
    return 0


def _cmd_replay(args) -> int:
    res = replay(Path(args.root), args.since, args.until, args.ref,
                 progress=(lambda s: print(s, file=sys.stderr)) if args.verbose else None)
    if not args.rows:
        res.pop("rows")
    print(json.dumps(res, indent=2))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--root", default=str(REPO_ROOT))
    g.add_argument("--check", action="store_true")
    d = sub.add_parser("decide")
    d.add_argument("--root", default=str(REPO_ROOT))
    r = sub.add_parser("replay")
    r.add_argument("--root", default=str(REPO_ROOT))
    r.add_argument("--since", required=True)
    r.add_argument("--until", required=True)
    r.add_argument("--ref", default="origin/main")
    r.add_argument("--rows", action="store_true")
    r.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    return {"generate": _cmd_generate, "decide": _cmd_decide, "replay": _cmd_replay}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
