"""UI-RESEARCH-CATALOG-502: the catalog's YAML loader (libyaml when built) and its per-file memo."""
from __future__ import annotations

import os

import yaml

from src.runtime import research_catalog as rc


def test_loader_is_a_safe_loader():
    assert rc._LOADER in (getattr(yaml, "CSafeLoader", None), yaml.SafeLoader)
    assert issubclass(rc._LOADER, (yaml.SafeLoader,) + ((yaml.CSafeLoader,) if hasattr(yaml, "CSafeLoader") else ()))


def test_memo_reuses_unchanged_files_and_reparses_edited_ones(tmp_path):
    p = tmp_path / "u.yaml"
    p.write_text("id: RQ-1\ntitle: a\n", encoding="utf-8")
    doc1, err = rc._load_yaml(p)
    assert err is None and doc1 == {"id": "RQ-1", "title": "a"}
    doc2, _ = rc._load_yaml(p)
    assert doc2 is doc1  # served from the memo
    p.write_text("id: RQ-1\ntitle: bb\n", encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    doc3, _ = rc._load_yaml(p)
    assert doc3 == {"id": "RQ-1", "title": "bb"}


def test_errors_are_reported_and_never_memoized(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    doc, err = rc._load_yaml(p)
    assert doc is None and err.startswith("unreadable:")
    assert str(p) not in rc._PARSE_MEMO
    p.write_text("- a list\n", encoding="utf-8")
    assert rc._load_yaml(p) == (None, "top level is not a mapping")


def test_safe_loader_refuses_python_tags(tmp_path):
    p = tmp_path / "evil.yaml"
    p.write_text("x: !!python/object/apply:os.system ['true']\n", encoding="utf-8")
    doc, err = rc._load_yaml(p)
    assert doc is None and err.startswith("unreadable:")
