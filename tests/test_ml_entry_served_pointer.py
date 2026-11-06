"""The ONE served-ENTRY-model pointer (src/runtime/ml_entry_served.py): resolution, fallback, and the repo's own pointer."""
import json

from src.runtime import ml_entry_served as S


def _root(tmp_path, names):
    for n in names:
        (tmp_path / n).mkdir()
        (tmp_path / n / "model.json").write_text("{}")
    return tmp_path


def _ptr(tmp_path, name):
    p = tmp_path / "ENTRY_SERVED.json"
    p.write_text(json.dumps({"artifact_dir": name}))
    return p


def test_repo_pointer_names_an_existing_artifact():
    assert S.served_artifact().is_file()
    assert S.served_dir() == json.loads(S.POINTER.read_text())["artifact_dir"]


def test_pointer_selects_a_dated_revision_and_leaves_v1(tmp_path):
    root = _root(tmp_path, ["ml_decision_entry_v1", "ml_decision_entry_v1r20261110"])
    ptr = _ptr(tmp_path, "ml_decision_entry_v1r20261110")
    assert S.served_artifact(ptr, root) == root / "ml_decision_entry_v1r20261110" / "model.json"
    assert (root / "ml_decision_entry_v1" / "model.json").is_file()      # revert is a one-line pointer edit


def test_bad_pointers_fall_back_to_v1_never_raise(tmp_path):
    root = _root(tmp_path, ["ml_decision_entry_v1", "ml_decision_entry_v2"])
    assert S.served_dir(tmp_path / "absent.json", root) == "ml_decision_entry_v1"          # no pointer
    assert S.served_dir(_ptr(tmp_path, "ml_decision_entry_v2"), root) == "ml_decision_entry_v1"  # v2 is a different leg
    assert S.served_dir(_ptr(tmp_path, "../etc"), root) == "ml_decision_entry_v1"          # not a known shape
    assert S.served_dir(_ptr(tmp_path, "ml_decision_entry_v1r20261110"), root) == "ml_decision_entry_v1"  # dir missing
    (tmp_path / "ENTRY_SERVED.json").write_text("not json")
    assert S.served_dir(tmp_path / "ENTRY_SERVED.json", root) == "ml_decision_entry_v1"
