"""ML-DATA-OFF-TRAINER: market-only export allowlist + router published-data routing."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.research import market_data_export as mde
from scripts.research import compute_router as cr
from scripts.research import trainer_queue as tq

REPO = Path(__file__).resolve().parents[1]
BTC = "datasets-out/market_features/BTCUSDT/15m/v002/data.jsonl"


def _unit(path=BTC, **routing):
    r = {"needs_trainer_resident_data": True, "published_data": "metis-market-data", "est_minutes": 15, "peak_memory_gb": 3.0}
    r.update(routing)
    return {"id": "RQ-20261013-aaaa-01", "compute": "auto", "routing": r, "ml_bakeoff": {"dataset": {"kind": "jsonl", "path": path}}}


def test_self_tests():
    assert mde._self_test() == 0


def test_allowlist_is_market_only():
    for rel in mde.ALLOW:
        fam = rel.split("/")[0]
        assert fam in ("market_features", "market_raw"), rel
        assert rel.split("/")[1] in ("BTCUSDT", "ETHUSDT", "SOLUSDT"), rel   # MES / ETF shards are licence-restricted
    for ours in ("trade_outcomes", "setup_labels", "conviction_meta", "execution_quality", "account_context",
                 "backtest_results", "review_journal", "setup_labels_audit"):
        assert not any(a.startswith(ours) for a in mde.ALLOW)


def test_published_unit_leaves_the_trainer():
    cfg = cr.load_config()
    p = cr.plan(_unit(), cfg)
    assert p.ok and p.backend == "kaggle_cpu" and p.workflow == "research-script-run-kaggle-cpu.yml" and p.cls == "cpu_light", p
    assert cr.plan(_unit(est_minutes=90), cfg).cls == "cpu_long"


def test_gpu_unit_with_published_data_goes_to_kaggle():
    cfg = cr.load_config()
    u = _unit(needs_gpu=True)
    p = cr.plan(u, cfg)
    assert p.ok and p.backend == "kaggle" and p.cls == "gpu", p


def test_claim_is_checked_not_trusted():
    cfg = cr.load_config()
    p = cr.plan(_unit(path="datasets-out/trade_outcomes/all/all/v002/data.jsonl"), cfg)
    assert not p.ok and "NOT in the published allowlist" in p.error
    p = cr.plan(_unit(path="datasets-out/market_features/MES/15m/v002/data.jsonl"), cfg)
    assert not p.ok
    u = _unit()
    u["routing"]["published_data"] = "no-such-dataset"
    assert not cr.plan(u, cfg).ok
    u = _unit()
    del u["ml_bakeoff"]
    assert not cr.plan(u, cfg).ok, "a claim with no dataset path to check is refused"


def test_trainer_resident_unit_still_needs_the_vm():
    cfg = cr.load_config()
    u = _unit()
    del u["routing"]["published_data"]
    assert cr.plan(u, cfg).cls == "needs_vm_data"


def test_needs_vm_data_class_conflicts_with_published():
    cfg = cr.load_config()
    u = _unit()
    u["compute"] = "needs_vm_data"
    p = cr.plan(u, cfg)
    assert not p.ok and "published" in p.error


def test_every_published_unit_in_the_queue_passes_the_router():
    import yaml
    cfg = cr.load_config()
    n = 0
    for f in sorted((REPO / "research" / "queue").glob("RQ-*.yaml")):
        d = yaml.safe_load(f.read_text()) or {}
        if (d.get("routing") or {}).get("published_data"):
            n += 1
            assert cr.published_problem(d, cfg) is None, f.name
            assert cr.plan(d, cfg).ok, f.name
    assert n >= 0   # the queue edit lands after the first verified export (separate PR)


# ── trainer as its own queue ─────────────────────────────────────────────────────────────────────────────


def _at(h, m=0):
    return datetime(2026, 10, 14, h, m, tzinfo=timezone.utc)


def test_trainer_config_windows_never_open_a_busy_hour():
    cfg = cr.load_config()
    prof = tq.load()
    cfg_hours = set()
    for a, b in cr.parse_windows(cfg["backends"]["trainer"]["queue"]["windows_utc"]):
        cfg_hours |= set(range(a // 60, (b + 59) // 60))
    assert cfg_hours <= set(tq.open_hours(prof)), (sorted(cfg_hours - set(tq.open_hours(prof))), "config opens an hour the measured profile says is busy")


def test_trainer_unit_waits_for_an_idle_window_and_must_fit():
    cfg = cr.load_config()
    u = {"compute": "needs_vm_data", "routing": {"needs_trainer_resident_data": True, "est_minutes": 15}}
    assert cr.resolve(u, cfg, cr.BackendState(now=_at(1))).wait            # the 00:05Z training cycle
    assert cr.resolve(u, cfg, cr.BackendState(now=_at(6))).wait            # catch-up sweep
    assert not cr.resolve(u, cfg, cr.BackendState(now=_at(12))).wait
    assert cr.resolve(u, cfg, cr.BackendState(now=_at(23, 50))).wait       # would run into 00:00Z
    assert not cr.resolve(u, cfg, cr.BackendState(now=None)).wait          # no clock -> no window gating (dry tooling)


def test_runpod_is_only_a_fallback_and_respects_the_ledger():
    cfg = cr.load_config()
    req = {"manifest": "ml/configs/btc-regime-15m-lgbm-v2.yaml", "est_cost_usd": 0.5}
    u = {"compute": "gpu", "routing": {"needs_gpu": True, "est_minutes": 60, "runpod": req}}
    ok = cr.resolve(u, cfg, cr.BackendState(quota_hours=20.0, now=_at(12)))
    assert ok.backend == "kaggle" and not ok.wait, "Kaggle is always tried first"
    short = cr.resolve(u, cfg, cr.BackendState(quota_hours=1.0, now=_at(12)))
    assert short.backend == "runpod" and not short.wait, short
    big = dict(u, routing=dict(u["routing"], runpod=dict(req, est_cost_usd=50.0)))
    assert cr.resolve(big, cfg, cr.BackendState(quota_hours=1.0, now=_at(12))).wait, "a $50 estimate cannot fit a $10/month cap"
    none = dict(u, routing={"needs_gpu": True, "est_minutes": 60})
    assert cr.resolve(none, cfg, cr.BackendState(quota_hours=1.0, now=_at(12))).wait, "no declared manifest -> wait, never CPU, never blind spend"


def test_fallback_cannot_be_a_first_choice(tmp_path):
    import yaml
    doc = yaml.safe_load((REPO / "scripts/research/research_compute.yaml").read_text())
    doc["classes"]["gpu"]["backends"] = ["runpod", "kaggle"]
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="fallback"):
        cr.load_config(p)


def test_trainer_workload_names_the_biggest_consumer():
    b = tq.breakdown(tq.load())
    assert b["rows"][0]["service"] == "ict-drift-retrain"
    assert abs(sum(r["share_of_service_cpu"] for r in b["rows"]) - 1.0) < 0.01
