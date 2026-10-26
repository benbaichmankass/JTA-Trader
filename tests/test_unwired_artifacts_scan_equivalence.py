"""`check_unwired_artifacts.scan` candidate-stem optimisation (CI-SPEED-1026).

scan() used to run ONE alternation over every target stem against every runner
file (O(files x stems), 250 s on the live tree). It now compiles the same
pattern over only the stems present as tokens in each file. This test pins that
the result is IDENTICAL to the original full-alternation algorithm, kept here
as a reference implementation, on a fixture covering all five reference shapes,
a non-word stem, and the negative cases.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
import check_unwired_artifacts as cua  # noqa: E402


def _reference_refs(root, targets):
    """The pre-optimisation algorithm: one alternation over every stem."""
    by_stem = {}
    for t in targets:
        by_stem.setdefault(t.stem, []).append(t)
    alt = "|".join(sorted(map(re.escape, by_stem)))
    pat = re.compile(
        r"\b(?:" + alt + r")\.py\b"
        r"|^[ \t]*import[ \t]+(?:[\w.]+\.)?(?:" + alt + r")\b"
        r"|^[ \t]*from[ \t]+(?:[\w.]+\.)?(?:" + alt + r")[ \t]+import\b"
        r"|^[ \t]*from[ \t]+[\w.]+[ \t]+import[ \t]+\(?[^\n]*?\b(?:" + alt + r")\b"
        r"|-m[ \t]+(?:[\w.]+\.)?(?:" + alt + r")\b",
        re.MULTILINE,
    )
    stem_of = re.compile(r"\b(" + alt + r")\b")
    refs = {st: [] for st in by_stem}
    for text, f in cua._runner_corpus(root):
        fr = f.relative_to(root).as_posix()
        if fr.startswith("tests/"):
            continue
        own = {t.stem for t in by_stem.get(f.stem, []) if t == f}
        matched = set()
        for m in pat.findall(text):
            got = stem_of.search(m if isinstance(m, str) else m[0])
            if got:
                matched.add(got.group(1))
        for m in matched:
            if m not in own:
                refs[m].append(fr)
    return refs


def _build(tmp_path):
    files = {
        "scripts/ops/t_invoke.py": "def main():\n    return 0\n",
        "scripts/ops/t_import.py": "def main():\n    return 0\n",
        "scripts/ops/t_fromimp.py": "def main():\n    return 0\n",
        "src/pkg/t_names.py": "def main():\n    return 0\n",
        "src/pkg/t_run.py": "def main():\n    return 0\n",
        "scripts/ops/t-hyphen.py": "def main():\n    return 0\n",
        "scripts/ops/t_doc_only.py": "def main():\n    return 0\n",
        "scripts/ops/t_orphan.py": "def main():\n    return 0\n",
        "scripts/ops/t_prefix_extra.py": "def main():\n    return 0\n",
        "scripts/ops/runner.sh": "python3 scripts/ops/t_invoke.py --x\n"
        "echo t-hyphen.py\n",
        "scripts/ops/user.py": "import t_import\n"
        "from scripts.ops import t_fromimp\n"
        "from src.pkg import other, t_names as n\n"
        "x = 't_orphan_mentioned_in_prose'\n",
        "deploy/x.service": "ExecStart=/usr/bin/python3 -u -m src.pkg.t_run\n",
        ".claude/skills/s/SKILL.md": "run scripts/ops/t_doc_only.py\n",
    }
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return [tmp_path / r for r in files if r.endswith(".py") and "user.py" not in r]


def test_scan_matches_full_alternation_reference(tmp_path):
    targets = _build(tmp_path)
    refs = _reference_refs(tmp_path, targets)
    findings = cua.scan(tmp_path, targets)
    unwired = {rel for rel, v, _ in findings if v == cua.V_UNWIRED}
    ref_unwired = {
        t.relative_to(tmp_path).as_posix()
        for t in targets
        if not [x for x in refs[t.stem] if x != t.relative_to(tmp_path).as_posix()]
    }
    assert unwired == ref_unwired
    # every reference shape wired; the three negatives are not
    for stem in ("t_invoke", "t_import", "t_fromimp", "t_names", "t_run", "t-hyphen"):
        assert refs[stem], stem
    assert {Path(r).stem for r in unwired} == {"t_orphan", "t_prefix_extra"}
    # doc-only gets its own (non-unwired) verdict in both
    assert refs["t_doc_only"] == [".claude/skills/s/SKILL.md"]
    assert any(
        rel.endswith("t_doc_only.py") and v != cua.V_UNWIRED for rel, v, _ in findings
    )
