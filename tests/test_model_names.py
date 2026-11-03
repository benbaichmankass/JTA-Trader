import yaml

from ml.model_names import _PATH, display_name, labelled


def test_fallback_to_id():
    assert display_name("unknown-model") == "unknown-model"
    assert labelled("unknown-model") == "unknown-model"


def test_lookup_with_injected_table():
    t = {"m-1": {"name": "Collie-1a"}}
    assert display_name("m-1", t) == "Collie-1a"
    assert labelled("m-1", t) == "Collie-1a (m-1)"


def test_alias_file_is_well_formed():
    d = yaml.safe_load(_PATH.read_text())
    breeds, models = d["breeds"], d["models"]
    names = [m["name"] for m in models.values()]
    assert len(names) == len(set(names))
    for m in models.values():
        assert m["name"].split("-")[0] in breeds
    assert display_name("exit-policy-v1") == "Retriever-1"
    assert display_name("ml-decision-entry-v2") == "Bloodhound-2"
