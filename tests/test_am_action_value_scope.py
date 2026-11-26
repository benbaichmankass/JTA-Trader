"""Q10 one-leg re-scope: the reduce-time strategy / symbol / entry_from filter of scripts/research/am_action_value.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

import am_action_value as V  # noqa: E402
import am_policy_arm as P  # noqa: E402

RECS = [
    {"st": "ict_scalp_5m", "sy": "BTCUSDT", "tf": "5m", "e": "2025-06-01 00:00:00+00:00", "a": {}, "b": [0.0]},
    {"st": "ict_scalp_5m", "sy": "BTCUSDT", "tf": "5m", "e": "2026-03-01 00:00:00+00:00", "a": {}, "b": [0.0]},
    {"st": "ict_scalp_5m", "sy": "BTCUSDT", "tf": "5m", "e": "2026-11-24 00:00:00+00:00", "a": {}, "b": [0.0]},
    {"st": "fade_breakout", "sy": "BTCUSDT", "tf": "4h", "e": "2025-06-01 00:00:00+00:00", "a": {}, "b": [0.0]},
    {"st": "fade_breakout", "sy": "ETHUSDT", "tf": "4h", "e": "2026-03-01 00:00:00+00:00", "a": {}, "b": [0.0]},
]


def test_scope_filter_empty_is_identity_and_filters_compose():
    assert V.scope_filter(RECS) == RECS
    assert V.scope_filter(RECS, [], [""]) == RECS
    assert len(V.scope_filter(RECS, ["ict_scalp_5m"])) == 3
    assert len(V.scope_filter(RECS, None, ["ETHUSDT"])) == 1
    assert V.scope_filter(RECS, ["fade_breakout"], ["BTCUSDT"]) == [RECS[3]]


@pytest.fixture
def stub(monkeypatch):
    seen = {}
    monkeypatch.setattr(P, "read_shards", lambda out: (list(RECS), [{}]))

    def seg(recs, cls, n_control):
        seen.setdefault("segs", []).append(len(recs))
        return {"verdict": "indeterminate", "n": len(recs)}
    monkeypatch.setattr(P, "_segment", seg)
    monkeypatch.setattr(P, "_cuts", lambda *a, **k: {})
    return seen


def test_reduce_scopes_and_moves_the_holdout_start(stub, tmp_path):
    res = V.reduce_run(tmp_path, "mf_tighten_fixed", "RQ-TEST", "pytest", None, False, 0,
                       strategies=["ict_scalp_5m"], symbols=["BTCUSDT"], entry_from="2026-11-24")
    assert res["n"] == 3
    assert stub["segs"] == [1, 1]          # dev: the 2025 trade; holdout: only the post-2026-11-24 trade
    assert res["scope"] == {"strategies": ["ict_scalp_5m"], "symbols": ["BTCUSDT"], "holdout_start": "2026-11-24", "n_corpus": 5}
    assert "SCOPED" in res["population"] and "3 of 5" in res["population"]


def test_reduce_unscoped_is_unchanged(stub, tmp_path):
    res = V.reduce_run(tmp_path, "mf_tighten_fixed", "RQ-TEST", "pytest", None, False, 0)
    assert res["n"] == 5
    assert stub["segs"] == [2, 3]
    assert res["scope"]["holdout_start"] == P.HOLDOUT_START and "SCOPED" not in res["population"]


def test_entry_from_before_holdout_start_is_refused(stub, tmp_path):
    with pytest.raises(ValueError):
        V.reduce_run(tmp_path, "mf_tighten_fixed", "RQ-TEST", "pytest", None, False, 0, entry_from="2025-12-31")


def test_paired_stats_delta_sd_t_and_controls():
    recs = [{"b": [1.0], "a": {"k": {"n": 1, "p": [1.5], "cn": [1.0, 2.0]}}},       # delta +0.5; controls 0.0, +1.0
            {"b": [-1.0], "a": {"k": {"n": 1, "p": [-0.5], "cn": [-1.0, -1.0]}}},   # delta +0.5; controls 0, 0
            {"b": [0.2], "a": {}}]                                                   # never fired: delta 0
    p = V.paired_stats(recs, "k", 2)
    assert (p["n"], p["n_fired"]) == (3, 2)
    assert abs(p["mean_delta_r"] - 1 / 3) < 1e-4 and p["sd_delta_r"] > 0 and p["t"] > 0
    assert p["share_controls_beaten"] == 0.5                                         # beats control 0 (mean 0), not control 1 (mean 1/3)
    assert V.paired_stats([], "k", 2)["mean_delta_r"] is None


def test_reduce_reports_paired_per_segment(stub, tmp_path):
    res = V.reduce_run(tmp_path, "mf_tighten_fixed", "RQ-TEST", "pytest", None, False, 0, strategies=["ict_scalp_5m"], entry_from="2026-11-24")
    assert res["paired"]["dev"]["n"] == 1 and res["paired"]["holdout"]["n"] == 1
