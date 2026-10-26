"""CJ-3: the blind-grade masking helper must refuse every leak class, and the probe must be able to fire.

Each ``test_plant_*`` puts ONE leak into an otherwise clean packet and asserts
``find_leaks`` names it -- a leak check that has never caught a planted leak
proves nothing (CLAUDE-RULES-CANONICAL § RULE ONE, "a negative needs a
denominator"). ``test_clean_packet_has_no_leaks`` is the negative control.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ops import blind_grade as bg

DEC = 1_760_000_000.0  # decision time (epoch s); the 2h bars below straddle it
IV = 7200


def _bars(n_before: int = 70, n_after: int = 10) -> list[dict]:
    out = []
    t0 = DEC - IV * n_before
    for i in range(n_before + n_after):
        c = 2400.0 + i * 1.5
        out.append({"time": t0 + i * IV, "open": c - 0.7, "high": c + 3.3, "low": c - 4.1, "close": c,
                    "volume": 100.0 + i})
    return out


def _pkg() -> dict:
    sl = {"strategy_name": "eth_pullback_2h", "timeframe": "2h", "atr": 30.0, "risk_per_unit": 45.0,
          "confidence": 0.61, "direction": "long", "regime": "trending", "vol_regime": "calm",
          "trend_midline": 2450.25, "pullback_pos_in_range": 0.24, "entry_time": "2025-10-09 08:00:00",
          "contributing_strategies": ["eth_pullback_2h"], "aggregation": {"x": 1},
          "news": {"decision": "neutral", "item_count": 2, "event_risk": 0.0},
          "conviction": {"conviction": 0.65, "blended": 0.65}}
    return {"order_package_id": "pkg-abc", "strategy_name": "eth_pullback_2h", "symbol": "ETHUSDT",
            "direction": "long", "entry": "2505.5", "sl": "2460.5", "tp": "2685.5",
            "signal_logic": json.dumps(sl), "created_at": "2025-10-09T09:33:20+00:00"}


def _packet() -> tuple[dict, dict, list[dict]]:
    p = _pkg()
    p["created_at"] = "2025-10-09T08:53:20+00:00"  # == DEC
    bars = _bars()
    pkt, priv = bg.build_blind_packet(p, bars=bars, exposure={"same_market_same_dir": 1}, salt="s")
    return pkt, priv, bars


def _secrets(bars):
    return {"secret_prices": [2505.5, 2460.5, 2685.5, 2600.0], "raw_bars": bars}


def test_clean_packet_has_no_leaks():
    pkt, priv, bars = _packet()
    assert bg.find_leaks(pkt, **_secrets(bars), symbol="ETHUSDT") == []
    assert pkt["strategy_family"] == "pullback"
    assert "entry_time" in priv["dropped_keys"] and "contributing_strategies" in priv["dropped_keys"]
    assert "strategy_name" in priv["dropped_keys"]


def test_no_lookahead_bars_only_closed_before_decision():
    pkt, _, bars = _packet()
    # the fixture has 10 bars at/after the decision; none may appear, and the window is the last N_BARS
    assert len(pkt["bars"]) == bg.N_BARS
    assert [r[0] for r in pkt["bars"]] == list(range(-bg.N_BARS, 0))
    # the last admitted bar is the one that closed exactly at the decision; its close is the reference (0.0)
    assert pkt["bars"][-1][4] == 0.0
    nb = bg.normalise_bars(bars, decision_ts=DEC, interval_s=IV, atr=30.0)
    assert len(nb) == bg.N_BARS
    # a bar that OPENED before the decision but closes after it is excluded (it is still forming)
    nb2 = bg.normalise_bars(bars, decision_ts=DEC + IV / 2, interval_s=IV, atr=30.0)
    assert nb2 == nb


@pytest.mark.parametrize("plant,expect", [
    (lambda p: p["signal"].__setitem__("exit_price", 2600.0), "absolute_price"),
    (lambda p: p["signal"].__setitem__("pnl", 1.2), "outcome_key"),
    (lambda p: p["signal"].__setitem__("note", "fired at 2025-10-09"), "date"),
    (lambda p: p["signal"].__setitem__("note", "eth long"), "symbol"),
    (lambda p: p["signal"].__setitem__("bar_open_ts", 1760000000), "epoch"),
    (lambda p: p["bars"].append([0, 0.1, 0.2, -0.1, 0.05, 1.0]), "bar_index_not_past"),
    (lambda p: p["bars"].__setitem__(-1, [-1, 2502.8, 2506.8, 2499.4, 2503.5, 1.0]), "raw_bar_row"),
    (lambda p: p.__setitem__("strategy", "ict_scalp_sol_5m"), "symbol"),
])
def test_plant_leak_is_caught(plant, expect):
    pkt, _, bars = _packet()
    leaky = copy.deepcopy(pkt)
    plant(leaky)
    leaks = bg.find_leaks(leaky, **_secrets(bars), symbol="ETHUSDT")
    assert any(lk.startswith(expect) for lk in leaks), (expect, leaks)


def test_chance_coincidences_are_not_a_leak_but_a_raw_series_is():
    raw = [{"open": 0.167, "high": 0.170, "low": 0.165, "close": 0.169}]
    # ADA ~0.167 vs an ATR-normalised 0.167: two chance hits in one row, from different positions
    assert bg.find_leaks({"bars": [[-1, 0.167, 0.169, -0.8, 0.0, 1.0]]}, raw_bars=raw) == []
    assert any(lk.startswith("raw_bar_row") for lk in
               bg.find_leaks({"bars": [[-1, 0.167, 0.170, 0.165, 0.0, 1.0]]}, raw_bars=raw))
    # raw prices smuggled into named fields: 3+ is a leak, 1 is chance
    assert bg.find_leaks({"signal": {"a": 0.167}}, raw_bars=raw) == []
    assert any(lk.startswith("raw_bar_price") for lk in
               bg.find_leaks({"signal": {"a": 0.167, "b": 0.170, "c": 0.169}}, raw_bars=raw))


def test_builder_refuses_a_leaking_packet(monkeypatch):
    # a masker bug that passes a raw price through must be refused by the builder, not shipped
    real = bg.mask_signal_logic

    def buggy(sl, *, entry, atr):
        m, d = real(sl, entry=entry, atr=atr)
        m["oops"] = entry
        return m, d

    monkeypatch.setattr(bg, "mask_signal_logic", buggy)
    p = _pkg()
    p["created_at"] = "2025-10-09T08:53:20+00:00"
    with pytest.raises(ValueError, match="leaks"):
        bg.build_blind_packet(p, bars=_bars(), exposure={}, salt="s")


def test_mask_is_an_allowlist():
    m, dropped = bg.mask_signal_logic({"brand_new_field": 123.0, "confidence": 0.5, "regime": "Trending 2026"},
                                      entry=100.0, atr=2.0)
    assert m == {"confidence": 0.5}
    assert set(dropped) == {"brand_new_field", "regime"}


def test_packet_id_is_opaque_and_stable():
    a = bg.packet_id("pkg-1", "salt")
    assert a == bg.packet_id("pkg-1", "salt") and a != bg.packet_id("pkg-1", "other")
    assert "pkg" not in a


def test_path_excursions_long_and_short():
    bars = [{"time": 0, "open": 100, "high": 106, "low": 97, "close": 101},
            {"time": 60, "open": 101, "high": 104, "low": 95, "close": 96}]
    assert bg.path_excursions(bars, entry=100, stop=98, direction="long", open_ts=0, close_ts=120,
                              interval_s=60) == (3.0, -2.5, 2)
    assert bg.path_excursions(bars, entry=100, stop=102, direction="short", open_ts=0, close_ts=120,
                              interval_s=60) == (2.5, -3.0, 2)


def _store_rows():
    b = {"schema_version": 1, "judgment_id": "BG-pkg-1-aaaaaaaa", "kind": "blind_grade", "order_package_id": "pkg-1",
         "trade_id": 7, "judged_at": "2026-10-26T18:00:00Z", "info_cutoff_at": "2026-09-01T00:00:00Z",
         "decision_ts": "2026-09-01T00:00:00Z", "author_kind": "llm", "model_id": "claude-sonnet-5-5",
         "prompt_sha": "a" * 40, "mask_version": "mask-v1", "packet_sha": "b" * 64, "run_id": "r1",
         "session_id": "session_x", "packet_id": "BP-0123456789ab", "decision_grade": "B", "grade_score": 3, "entry_quality": "acceptable",
         "risk_management": "correct", "p_win": 0.45, "expected_r": 0.2, "thesis": "trend pullback, decent"}
    r = dict(b, judgment_id="RG-pkg-1-cccccccc", kind="revealed_grade", blind_judgment_id=b["judgment_id"],
             info_cutoff_at="2026-09-02T00:00:00Z", revised_decision_grade="C", revised_grade_score=2,
             exit_quality="sl_appropriate", alternative_action="none", hindsight_note="stop was fair")
    return b, r


def test_store_validation(tmp_path: Path):
    b, r = _store_rows()
    d = tmp_path / "claude_judgments"
    d.mkdir()
    (d / "blind_grades.jsonl").write_text(json.dumps(b) + "\n")
    (d / "revealed_grades.jsonl").write_text(json.dumps(r) + "\n")
    assert bg.validate_stores(tmp_path) == []
    # a "blind" row whose cutoff is after the decision is not blind
    bad = dict(b, info_cutoff_at="2026-09-05T00:00:00Z")
    assert any("not blind" in e for e in bg.store_row_problems(bad))
    assert any("grade_score" in e for e in bg.store_row_problems(dict(b, grade_score=4)))
    assert any("blind_judgment_id" in e for e in bg.store_row_problems(dict(r, blind_judgment_id=None)))


def test_committed_stores_validate():
    # the real stores on main (empty is valid; a malformed row is not)
    assert bg.validate_stores(Path(__file__).resolve().parents[1] / "comms") == []


def run_all() -> int:
    return pytest.main([__file__, "-q"])
