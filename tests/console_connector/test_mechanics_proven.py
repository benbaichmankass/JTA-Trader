"""C2: per-leg mechanics_proven on the console Ladder (route + connector merge)."""
from pathlib import Path

from src.console_connector import tabs
from src.web.api.routers import soak_mechanics as M

REPO = Path(__file__).resolve().parents[2]


class _SS:
    """Fake soak_state: the REAL mechanics_proven is used; only its inputs are faked."""
    from scripts.ops import soak_state as _real
    mechanics_proven = staticmethod(_real.mechanics_proven)

    def __init__(self, rows=None, raise_on_states=False):
        self._rows, self._raise = rows or [], raise_on_states

    def soak_states(self):
        if self._raise:
            raise OSError("SOAKS.json unreadable")
        return self._rows

    def load_mechanics_paths(self):
        return {"leg_on_path": {"path": "p1", "exchange": "bybit", "delta": "none"},
                "leg_new_code": {"path": "p1", "exchange": "bybit", "delta": "new_code"}}


class _Status:
    def load(self):
        return {"bybit_1": {"exchange": "bybit"}}, {}

    def table(self):
        return {"leg_own": {}, "leg_on_path": {}, "leg_new_code": {}, "leg_unknown": {}}


ROWS = [{"id": "S-own", "leg": "leg_own", "account": "bybit_1", "state": "passed"},
        {"id": "S-sib", "leg": "leg_new_code", "account": "bybit_1", "state": "passed"},
        {"id": "S-unk", "leg": "leg_unknown", "account": "bybit_1", "state": "unknown", "reason": "db closed"}]


def test_route_proven_unproven_and_unknown():
    r = M.build_mechanics(_SS(ROWS), _Status())
    assert r["read_state"] == "read"
    legs = r["legs"]
    assert legs["leg_own"]["proven"] is True and legs["leg_own"]["basis"] == "own_soak"
    # a delta:none leg proven by a passed sibling on the same path + exchange
    assert legs["leg_on_path"]["proven"] is True and legs["leg_on_path"]["basis"] == "path_soak"
    # new code proves itself, so a path never proves it -- but it has its own passed soak here
    assert legs["leg_new_code"]["proven"] is True
    # its own soak reads unknown: null with the reason, never False
    assert legs["leg_unknown"]["proven"] is None and "unknown" in legs["leg_unknown"]["reason"]
    p = r["population"]
    assert p["proven"] + p["not_proven"] + p["unknown"] == p["legs"]


def test_route_unproven_leg_is_false_with_reason():
    rows = [{"id": "S-x", "leg": "other", "account": "bybit_1", "state": "in_progress"}]
    r = M.build_mechanics(_SS(rows), _Status())
    assert r["legs"]["leg_own"]["proven"] is False
    assert "no own passed soak" in r["legs"]["leg_own"]["reason"]


def test_route_unreadable_is_could_not_look_never_false():
    r = M.build_mechanics(_SS(raise_on_states=True), _Status())
    assert r["read_state"] == "could_not_look" and r["legs"] is None and "unreadable" in r["reason"]
    every_unknown = [{"id": "a", "leg": "leg_own", "state": "unknown", "reason": "journal missing"}]
    r2 = M.build_mechanics(_SS(every_unknown), _Status())
    assert r2["read_state"] == "could_not_look" and r2["legs"] is None


def test_connector_attaches_mechanics_per_leg(monkeypatch):
    def fake(path, token):
        assert path == "/api/bot/soak/mechanics"
        return {"read_state": "read", "legs": {"tlt_pullback_1d": {"proven": True, "reason": "x passed"}},
                "population": {"legs": 1}}
    monkeypatch.setattr(tabs, "FETCH", fake)
    legs = tabs.system_catalog(REPO, 1, mechanics=True)["sections"]["legs"]
    assert legs["mechanics"]["read_state"] == "read"
    by = {r["leg"]: r for r in legs["items"]}
    if "tlt_pullback_1d" in by:
        assert by["tlt_pullback_1d"]["mechanics_proven"]["proven"] is True
    assert any(r["mechanics_proven"] is None for r in legs["items"])   # a leg the route did not list: None, not False


def test_connector_unreadable_route_is_none_not_false(monkeypatch):
    def boom(path, token):
        raise TimeoutError("502")
    monkeypatch.setattr(tabs, "FETCH", boom)
    legs = tabs.system_catalog(REPO, 1, mechanics=True)["sections"]["legs"]
    assert legs["read_state"] == "read"                      # the roster itself still reads
    assert legs["mechanics"]["read_state"] == "could_not_look"
    assert all(r["mechanics_proven"] is None for r in legs["items"])


def test_default_call_reads_nothing_live_and_carries_no_mechanics(monkeypatch):
    def boom(path, token):
        raise AssertionError("the default system_catalog call must not read the live VM")
    monkeypatch.setattr(tabs, "FETCH", boom)
    out = tabs.system_catalog(REPO, 10)
    legs = out["sections"]["legs"]
    assert "mechanics" not in legs and all("mechanics_proven" not in r for r in legs["items"])
    assert {"ml_models", "signals"} <= set(out["sections"])


def test_ladder_mechanics_call_fits_the_reply_budget(monkeypatch):
    """Per-leg detail for EVERY leg, with long reasons, still fits: the call drops models + signals."""
    import json

    from src.console_connector import server as srv
    legs_all = [r["leg"] for r in tabs.system_catalog(REPO, 1)["sections"]["legs"]["items"]]
    detail = {leg: {"proven": False, "basis": None, "path": "alpaca_equity_bracket_v1", "delta": "new_code",
                    "reason": f"{leg} has no own passed soak and is not registered in config/mechanics_paths.yaml"}
              for leg in legs_all}
    monkeypatch.setattr(tabs, "FETCH", lambda path, token: {"read_state": "read", "legs": detail,
                                                            "population": {"legs": len(detail)}})
    out = tabs.system_catalog(REPO, 1, mechanics=True)
    assert set(out["sections"]) == {"legs"}
    assert len(json.dumps(out, default=str)) <= srv.REPLY_BUDGET
