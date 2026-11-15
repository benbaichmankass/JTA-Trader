"""ml_entry_eq_struct (row ML-ENTRY-EQ-STRUCT-LIVE, Tier 3): the 5-seed structure-exit ensemble that PASSED RQ-20261107-98e3-06, served on alpaca_live + its
alpaca_portfolio mirror. The committed ensemble reproduces the graded sha and the harness predictions to 1e-9; the leg carries the SL-only structure exit; the
fixed-bracket ml_entry_eq leg is unchanged."""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from src.runtime import ml_entry_eq_features as F  # noqa: E402
from src.units.strategies import ml_entry as ME  # noqa: E402
from src.units.strategies import ml_entry_eq as L  # noqa: E402

DIR = REPO / "ml" / "candidates" / "ml_entry_eq_v3_struct_ens5"
ART = DIR / "model.json"
GRADED_SHA_PREFIX = "0afc49948a41671a"   # RQ-20261107-98e3-06 run 42432561069 (sha256 of the 5 concatenated booster texts)
CFG = {"structure_exit": "pivot=5;sl_only", "artifact": "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json", "session": None}


def _snap(bar_close="2026-11-05T20:00:00+00:00", n=173):
    syms = {f"E{i}": {**{k: 0.0 for k in F.FEATURES_B}, "atr14": 1.0, "close": 100.0} for i in range(n)}
    return {"schema": F.SCHEMA, "bar_close": bar_close, "pool_size": 173, "covered": n, "symbols": syms}


def test_committed_ensemble_is_the_graded_model_and_reproduces_the_fixture():
    art = json.loads(ART.read_text())
    texts = art["booster_txt"]["long"]
    assert isinstance(texts, list) and len(texts) == 5 and art["ensemble_seeds"] == [1, 2, 3, 4, 5]
    sha = hashlib.sha256("".join(texts).encode()).hexdigest()
    assert sha == art["booster_sha256"] and sha.startswith(GRADED_SHA_PREFIX) and art["sha_match_confirm"] is True
    assert art["tau"] == 0.25 and art["structure_exit"] == "pivot=5;sl_only" and art["side"] == "long" and art["train_rows"] == 368757
    model = L.load_model(ART)
    assert len(model["boosters"]) == 5 and model["meta"]["features"] == F.FEATURES_B
    fx = json.loads((DIR / "parity_fixture.json").read_text())
    assert fx["model_id"] == art["model_id"] and len(fx["rows"]) >= 50
    for r in fx["rows"]:
        assert abs(L.score({k: r[k] for k in F.FEATURES_B}, model) - float(r["pred"])) < 1e-9, r   # mean of 5 == the harness ensemble


def test_sha_is_verified_at_load(tmp_path):
    art = json.loads(ART.read_text())
    art["booster_sha256"] = "0" * 64
    p = tmp_path / "model.json"
    p.write_text(json.dumps(art))
    with pytest.raises(ValueError, match="sha256"):
        L.load_model(p)


def test_struct_package_carries_structure_exit_and_the_scored_bracket(monkeypatch):
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.5] * len(rows))
    pkg = L.order_package({"symbol": "E0", **CFG}, _snap(), L.load_model(ART))
    assert pkg["meta"]["structure_exit"] == "pivot=5;sl_only" and pkg["meta"]["tau"] == 0.25
    assert pkg["sl"] == 98.0 and pkg["tp"] == 103.0 and pkg["meta"]["max_hold_min"] == 24 * 60
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.22] * len(rows))          # above the fixed-bracket tau 0.20, below this artifact's 0.25
    with pytest.raises(ValueError, match="below_tau"):
        L.order_package({"symbol": "E0", **CFG}, _snap(), L.load_model(ART))


def test_fixed_bracket_leg_is_unchanged(monkeypatch):
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.5] * len(rows))
    pkg = L.order_package({"symbol": "E0", "session": None}, _snap())
    assert "structure_exit" not in pkg["meta"] and pkg["meta"]["tau"] == 0.2
    assert L.artifact_path({}) == L.ARTIFACT and L.artifact_path(CFG) == REPO / CFG["artifact"]


_PKG = {"order_package_id": "p", "direction": "long", "entry": 100.0, "sl": 98.0, "tp": 103.0, "meta": {"structure_exit": "pivot=5;sl_only"}}


def _stub(monkeypatch, base=None, sx=None):
    import src.units.strategies.claude_desk as desk
    monkeypatch.setattr(desk, "max_hold_verdict", lambda pkg, now: base)
    monkeypatch.setattr(ME, "structure_verdict", lambda pkg, df: sx)


def test_monitor_merges_the_sl_only_structure_verdict(monkeypatch):
    sx = {"sl": 99.0, "tp": 999.0, "structure_move": {"sl_before": 98.0, "sl_after": 99.0, "tp_before": 103.0, "tp_after": 999.0}}
    _stub(monkeypatch, base=None, sx=sx)
    v = L.monitor({}, None, _PKG)
    assert v["sl"] == 99.0 and "tp" not in v and v["structure_move"]["tp_after"] == 103.0   # SL only: the TP is never touched
    _stub(monkeypatch, base={"action": "close", "reason": "max_hold"}, sx=sx)
    assert L.monitor({}, None, _PKG) == {"action": "close", "reason": "max_hold"}            # the time stop wins
    _stub(monkeypatch, base=None, sx={"action": "close", "reason": "structure_sl_cross"})
    assert L.monitor({}, None, _PKG)["reason"] == "structure_sl_cross"                        # a structure cross closes


def test_monitor_without_a_declared_structure_exit_is_the_time_stop_only(monkeypatch):
    _stub(monkeypatch, base=None, sx=ME._NOT_DECLARED)
    assert L.monitor({}, None, {**_PKG, "meta": {}}) is None


def test_monitor_never_raises_and_structure_failure_falls_back(monkeypatch):
    import src.units.strategies.claude_desk as desk
    monkeypatch.setattr(desk, "max_hold_verdict", lambda pkg, now: None)
    monkeypatch.setattr(ME, "structure_verdict", lambda pkg, df: (_ for _ in ()).throw(RuntimeError("boom")))
    assert L.monitor({}, None, _PKG) is None


def test_roster_is_alpaca_live_and_its_mirror_only_and_the_leg_is_registered():
    acc = yaml.safe_load((REPO / "config" / "accounts.yaml").read_text())
    acc = acc.get("accounts", acc)
    assert "ml_entry_eq_struct" in acc["alpaca_live"]["strategies"] and "ml_entry_eq_struct" in acc["alpaca_portfolio"]["strategies"]
    assert "ml_entry_eq_struct" not in (acc["alpaca_paper"]["strategies"] or [])       # a production leg is not on general paper
    assert "ml_entry_eq" in acc["alpaca_paper"]["strategies"] and "ml_entry_eq" not in acc["alpaca_live"]["strategies"]
    st = yaml.safe_load((REPO / "config" / "strategies.yaml").read_text())
    st = st.get("strategies", st)["ml_entry_eq_struct"]
    assert st["execution"] == "live" and st["structure_exit"] == "pivot=5;sl_only" and (REPO / st["artifact"]).exists()
    from src.runtime import pipeline
    assert pipeline.monitor_unit_for("ml_entry_eq_struct") == "ml_entry_eq"


def test_builder_emits_a_buy_with_the_structure_exit(tmp_path, monkeypatch):
    from src.runtime import strategy_signal_builders as B
    monkeypatch.setenv("ML_ENTRY_EQ_SNAPSHOT", str(tmp_path / "s.json"))
    now = pd.Timestamp.now(tz="UTC").floor("h")
    while not F.is_decision_close(now):
        now -= pd.Timedelta(hours=1)
    F.write_snapshot(tmp_path / "s.json", _snap(now.isoformat()))
    monkeypatch.setattr(L, "score_rows", lambda rows, model: [0.5] * len(rows))
    sig = B.ml_entry_eq_struct_signal_builder({"SYMBOL": "E0"})
    assert sig["side"] == "buy" and sig["meta"]["structure_exit"] == "pivot=5;sl_only" and sig["meta"]["strategy_name"] == "ml_entry_eq_struct"
