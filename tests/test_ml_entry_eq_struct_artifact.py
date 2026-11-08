"""Serve parity for the STRUCTURE-trained ml_entry_eq candidate (RQ-20261107-98e3-02): the committed booster reproduces the harness predictions in its
parity fixture exactly, the artifact carries the structure exit and the shipped-vs-graded caveat, and the live fixed-bracket candidate is untouched."""
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DIR = REPO / "ml" / "candidates" / "ml_entry_eq_v2_struct"
ART = json.loads((DIR / "model.json").read_text())
FIX = json.loads((DIR / "parity_fixture.json").read_text())


def test_committed_booster_reproduces_the_fixture_predictions():
    text = ART["booster_txt"]["long"]
    assert hashlib.sha256(text.encode()).hexdigest() == ART["booster_sha256"]
    assert FIX["model_id"] == ART["model_id"] and FIX["features"] == ART["features"]
    rows = FIX["rows"]
    assert len(rows) >= 50
    bst = lgb.Booster(model_str=text)
    got = bst.predict(pd.DataFrame([{f: r[f] for f in ART["features"]} for r in rows]))
    for g, r in zip(got, rows):
        assert abs(float(g) - float(r["pred"])) < 1e-9, r


def test_artifact_declares_the_structure_exit_and_what_was_not_graded():
    assert ART["structure_exit"] == "pivot=5;sl_only" and ART["tau"] == 0.2 and ART["side"] == "long"
    assert ART["bracket"]["sl_atr"] == 2.0 and ART["bracket"]["tp_atr"] == 3.0
    assert ART["shipped"] == "B_pinned_deterministic" and ART["sha_match_confirm"] is False   # the graded booster is a DIFFERENT fit
    assert ART["a_vs_b_delta"]["decision_agreement_at_tau"] > 0.95


def test_the_fixed_bracket_candidate_is_untouched():
    v1 = json.loads((REPO / "ml" / "candidates" / "ml_entry_eq_v1" / "model.json").read_text())
    assert v1["booster_sha256"].startswith("ceeb8698bb130b9b") and v1.get("structure_exit") in (None, "")   # the SERVED fixed-bracket fit (pinned), not the graded af4835e29fe83c86
