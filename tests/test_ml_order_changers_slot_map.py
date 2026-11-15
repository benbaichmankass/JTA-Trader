"""ML-SLOT-BASELINES-DECLARE: every model in the power file carries a slot, a baseline and a demotion read (report-only)."""
from pathlib import Path

import yaml

from scripts.ops import ml_order_changers as moc

POWER = Path(moc.POWER)


def test_every_model_has_a_declared_slot_baseline_and_demotion_read():
    sm = moc.slot_map(moc.load_power_doc(POWER))
    assert sm["undeclared"] == [], sm["undeclared"]
    assert set(sm["slots"]) >= {"D2", "D3", "D4", "D7", "D8"}


def test_served_artifacts_are_all_mapped():
    models = yaml.safe_load(POWER.read_text())["models"]
    for mid in ("ml-decision-entry-v1", "ml-decision-entry-v1r20261106", "ml-decision-entry-v2", "ml-entry-eq-v1",
                "ml-entry-eq-struct-ens5-v1", "overlay-td-v1", "ml-entry-tp-revision-v1", "exit-head-donchian-1h-v1"):
        assert mid in models and models[mid].get("demotion_read"), mid


def test_undeclared_field_is_reported_not_invented():
    sm = moc.slot_map({"slots": {"D3": {"baseline": "b", "competition_metric": "m"}}, "models": {"x": {"slot": "D3", "baseline": "D3"}}})
    assert sm["undeclared"] == ["x"] and sm["models"]["x"]["demotion_read"] is None
