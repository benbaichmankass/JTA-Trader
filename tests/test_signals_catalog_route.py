"""GET /api/bot/signals/catalog: the SPA Signals Catalog tab (public repo files, ungated)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.web.api.routers import signals_catalog as sc

REPO = Path(__file__).resolve().parents[1]


def test_catalog_covers_every_input_with_population():
    out = sc.build_signals_catalog(REPO, limit=500)
    assert out["read_state"] == "read"
    pop = out["population"]
    assert pop["inputs"] == pop["matched"] == pop["returned"] > 0
    assert sum(g["count"] for g in out["groups"]) == pop["inputs"]
    assert pop["with_consumer"] + pop["without_consumer"] == pop["inputs"]
    it = out["items"][0]
    for k in ("id", "family", "kind", "used_by_strategies", "used_by_models", "freshness", "name"):
        assert k in it


def test_filters_and_paging():
    allx = sc.build_signals_catalog(REPO, limit=500)
    fam = allx["groups"][0]["family"]
    f = sc.build_signals_catalog(REPO, family=fam, limit=500)
    assert f["population"]["matched"] == sum(g["count"] for g in allx["groups"] if g["family"] == fam)
    none = sc.build_signals_catalog(REPO, consumer="none", limit=500)
    assert none["population"]["matched"] == allx["population"]["without_consumer"]
    p = sc.build_signals_catalog(REPO, limit=5, offset=5)
    assert p["population"]["returned"] == 5 and p["population"]["next_offset"] == 10
    q = sc.build_signals_catalog(REPO, q="candle.open")
    assert any(i["id"] == "candle.open" for i in q["items"])


def test_route_mounted_and_unreadable_is_not_empty(monkeypatch):
    from src.web.api import main
    c = TestClient(main.app)
    r = c.get("/api/bot/signals/catalog?limit=3")
    assert r.status_code == 200 and r.json()["population"]["returned"] == 3

    def boom(*a, **k):
        raise OSError("gone")
    monkeypatch.setattr(sc, "build_signals_catalog", boom)
    bad = c.get("/api/bot/signals/catalog").json()
    assert bad["read_state"] == "unreadable" and bad["items"] is None and bad["population"]["inputs"] is None
