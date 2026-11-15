"""FEATURE-IMPACT-MAP UI backend: heat map / detail / invest over the M1 long table (schema feature_impact/1)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.web.api import main as api_main
from src.web.api.routers import feature_impact as fi


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


def _row(model, side, feat, fam, measure, value, *, asset="crypto_perp", mtype="entry", stage="served",
         state="measured", n_obs=1000):
    return {"schema": "feature_impact/1", "run_id": "R1", "model_id": model, "side": side, "stage": stage,
            "ml_type": mtype, "asset_class": asset, "symbol": "pooled", "timeframe": "1h", "feature": feat,
            "feature_id": f"ml_feature.{feat}", "feature_family": fam, "measure": measure, "value": value,
            "read_state": state, "provenance": "MEASURED", "n_obs": n_obs, "source_artifact": f"ml/{model}/model.json"}


def _write(root, rows, summary_over=None):
    d = root / "comms" / "feature_impact"
    d.mkdir(parents=True)
    (d / "R1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    s = {"schema": "feature_impact/1", "run_id": "R1", "computed_at": "2026-11-11T18:57:51Z", "file": "R1.jsonl",
         "read_state": "measured", "coverage": {"not_in_v0": ["M2"]}}
    s.update(summary_over or {})
    (d / "latest.json").write_text(json.dumps(s))


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "repo_root", lambda: tmp_path)
    rows = []
    # model A (crypto, entry): long booster set  vol 0.6 / momentum 0.3 / calendar 0.1 (a measured zero would be 0.0)
    for f, fam, v in (("vol24", "volatility", 0.6), ("ret_24", "momentum", 0.3), ("hour", "calendar", 0.1)):
        rows.append(_row("A", "long", f, fam, "gain_share", v))
        rows.append(_row("A", "short", f, fam, "gain_share", {"volatility": 0.2, "momentum": 0.5, "calendar": 0.3}[fam]))
    # model B (equities, entry_eq): only long; vol 0.4 / momentum 0.6 / calendar 0.0 (measured zero)
    for f, fam, v in (("vol24", "volatility", 0.4), ("ret_24", "momentum", 0.6), ("hour", "calendar", 0.0)):
        rows.append(_row("B", "long", f, fam, "gain_share", v, asset="us_etf", stage="candidate"))
    rows.append(_row("A", "long", "vol24", "volatility", "split_share", 0.5))
    rows.append(_row("A", "long", "bad", "volatility", "gain_share", None, state="not_computed"))   # excluded, never a 0
    _write(tmp_path, rows)
    return tmp_path


def test_heatmap_family_by_asset_class_is_the_mean_of_booster_set_shares(run, client):
    d = client.get("/api/bot/feature-impact/heatmap", params={"by": "asset_class"}).json()
    cell = {(c["row"], c["col"]): c for c in d["cells"]}
    # crypto_perp: booster sets (A,long) vol .6 and (A,short) vol .2 -> mean .4, n=2
    assert cell[("volatility", "crypto_perp")]["value"] == 0.4 and cell[("volatility", "crypto_perp")]["n"] == 2
    assert cell[("momentum", "crypto_perp")]["value"] == 0.4                     # (.3 + .5) / 2
    assert cell[("volatility", "us_etf")]["value"] == 0.4 and cell[("volatility", "us_etf")]["n"] == 1
    assert cell[("calendar", "us_etf")]["value"] == 0.0                          # a MEASURED zero stays 0.0
    for col, n in (("crypto_perp", 2), ("us_etf", 1)):                           # arithmetic cross-check: shares sum to 1 per set
        assert round(sum(c["value"] for c in d["cells"] if c["col"] == col), 6) == 1.0
    assert d["n_booster_sets"] == 3 and d["read_state"] == "measured" and d["run_id"] == "R1"
    assert d["rows"] == ["calendar", "momentum", "volatility"] and d["cols"] == ["crypto_perp", "us_etf"]
    assert "NOT edge" in d["caveat"] and d["coverage"] == {"not_in_v0": ["M2"]}


def test_heatmap_other_axes_measure_and_stage_filter(run, client):
    d = client.get("/api/bot/feature-impact/heatmap", params={"by": "stage"}).json()
    assert {c["col"] for c in d["cells"]} == {"served", "candidate"}
    only = client.get("/api/bot/feature-impact/heatmap", params={"by": "ml_type", "stage": "candidate"}).json()
    assert only["n_booster_sets"] == 1 and {c["col"] for c in only["cells"]} == {"entry"}
    sp = client.get("/api/bot/feature-impact/heatmap", params={"measure": "split_share"}).json()
    assert [(c["row"], c["col"], c["value"]) for c in sp["cells"]] == [("volatility", "crypto_perp", 0.5)]


def test_missing_pair_is_absent_not_zero_and_unusable_rows_are_dropped(run, client):
    d = client.get("/api/bot/feature-impact/heatmap", params={"measure": "split_share"}).json()
    assert ("momentum", "us_etf") not in {(c["row"], c["col"]) for c in d["cells"]}
    dt = client.get("/api/bot/feature-impact/detail", params={"family": "volatility"}).json()
    assert "bad" not in dt["rows"]                                               # the not_computed row never becomes a cell


def test_detail_cells_equal_the_rows_and_state_pooled_resolution(run, client):
    d = client.get("/api/bot/feature-impact/detail", params={"family": "momentum", "asset_class": "crypto_perp"}).json()
    got = {(c["row"], c["col"]): c["value"] for c in d["cells"]}
    assert got == {("ret_24", "A:long"): 0.3, ("ret_24", "A:short"): 0.5}
    assert d["cells"][0]["symbol"] == "pooled" and d["cells"][0]["timeframe"] == "1h" and d["cells"][0]["n"] == 1000
    assert d["resolution"]["symbol"] == "pooled" and "M2" in d["resolution"]["note"]


def test_no_run_unreadable_and_invest_are_stated_not_zero(tmp_path, monkeypatch, client):
    monkeypatch.setattr(fi, "repo_root", lambda: tmp_path)
    h = client.get("/api/bot/feature-impact/heatmap").json()
    assert h["read_state"] == "no_run" and h["cells"] == [] and h["rows"] == [] and h["run_id"] is None
    assert client.get("/api/bot/feature-impact/detail").json()["read_state"] == "no_run"
    inv = client.get("/api/bot/feature-impact/invest").json()
    assert inv["read_state"] == "not_computed" and inv["items"] == [] and inv["source_read_state"] == "no_run"
    d = tmp_path / "comms" / "feature_impact"
    d.mkdir(parents=True)
    (d / "latest.json").write_text(json.dumps({"file": "missing.jsonl", "read_state": "measured"}))
    assert client.get("/api/bot/feature-impact/heatmap").json()["read_state"] == "unreadable"


def test_errors(run, client):
    assert client.get("/api/bot/feature-impact/heatmap", params={"by": "nope"}).status_code == 400
    assert client.get("/api/bot/feature-impact/heatmap", params={"measure": "ic"}).status_code == 400
    assert client.get("/api/bot/feature-impact/detail", params={"measure": "ic"}).status_code == 400


def test_family_missing_from_some_models_reports_coverage_not_a_zero(tmp_path, monkeypatch, client):
    """Real-data finding: tp_revision alone carries `position_state`; its cell must say 1 of N sets, not look column-wide."""
    monkeypatch.setattr(fi, "repo_root", lambda: tmp_path)
    rows = [_row("A", "long", "vol24", "volatility", "gain_share", 1.0),
            _row("B", "all", "vol24", "volatility", "gain_share", 0.2, mtype="tp_revision"),
            _row("B", "all", "open_r", "position_state", "gain_share", 0.8, mtype="tp_revision")]
    _write(tmp_path, rows)
    d = client.get("/api/bot/feature-impact/heatmap", params={"by": "asset_class"}).json()
    c = {x["row"]: x for x in d["cells"]}
    assert (c["volatility"]["n"], c["volatility"]["n_col"], c["volatility"]["coverage"]) == (2, 2, 1.0)
    assert c["volatility"]["value"] == 0.6                                       # (1.0 + 0.2) / 2
    assert (c["position_state"]["n"], c["position_state"]["n_col"], c["position_state"]["coverage"]) == (1, 2, 0.5)
    assert c["position_state"]["value"] == 0.8                                   # one model's number, flagged by coverage
    by_type = {(x["row"], x["col"]): x for x in client.get("/api/bot/feature-impact/heatmap", params={"by": "ml_type"}).json()["cells"]}
    assert by_type[("position_state", "tp_revision")]["coverage"] == 1.0         # splitting by ml_type restores full coverage
