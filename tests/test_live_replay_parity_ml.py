"""Live-vs-replay parity covers the ML legs (row ML-LIVE-PARITY-ML-LEGS).

Pairs, per leg: a CLEAN control (records regenerated from the replay itself -> 0 divergences, state ``checked``) and a PLANTED
defect (a fabricated live record -> the exact class is flagged). Plus the collapsed states: nothing readable is ``could_not_check``
with ``divergences: None``, never ``0``."""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import scripts.ops.live_replay_parity as P  # noqa: E402
import scripts.ops.live_replay_parity_ml as M  # noqa: E402
from src.runtime import ml_entry_eq_features as F  # noqa: E402
from src.units.strategies import ml_entry as ME  # noqa: E402
from src.units.strategies import ml_entry_eq as L  # noqa: E402


def _ep(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


# ── ml_entry ─────────────────────────────────────────────────────────────────

LAST_BAR = "2026-11-10T19:00:00+00:00"   # closes 20:00 -> a decision close (hour % 4 == 0)
SINCE, UNTIL = _ep("2026-11-10T00:00:00+00:00"), _ep("2026-11-10T21:00:00+00:00")


def _candles(seed: int, n: int = 600) -> list:
    rng = np.random.default_rng(seed)
    end = int(_ep(LAST_BAR))
    px = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    out = []
    for i in range(n):
        t = end - (n - 1 - i) * 3600
        o = px[i - 1] if i else px[0]
        c = px[i]
        out.append({"time": t, "open": o, "high": max(o, c) * 1.002, "low": min(o, c) * 0.998, "close": c,
                    "volume": float(1000 + 50 * rng.random())})
    return out


def _entry_setup():
    ref = list(ME.load_model()["meta"]["xs_reference"])
    own = ["BTCUSDT", "ETHUSDT"]
    bundle = {"ml_candles": {s: {"candles": _candles(i), "error": None} for i, s in enumerate(ref)},
              "signals": {"ml_entry": {"rows": [], "error": None}}, "audit_until_epoch": UNTIL + 6 * 3600}
    leg = SimpleNamespace(name="ml_entry", symbol="BTCUSDT", timeframe="1h", unit="ml_entry", decision_bar="closed",
                          execution="live", accounts=["bybit_2"], real_money=True, features={},
                          cfg={"symbols": own, "min_reference_symbols": 40, "decision_bar": "closed", "enabled": True})
    return leg, bundle, ref


def _live_from_replay(leg, bundle):
    """What an exact live would have written: the replay's own decision, in the live audit grammar."""
    from src.runtime import ml_entry_profile as PR
    frames = {s: M._frame(b["candles"]) for s, b in bundle["ml_candles"].items()}
    model = ME.load_model()
    rows = []
    for bar in M.decision_bars(SINCE, UNTIL, 4):
        for k, sym in enumerate(leg.cfg["symbols"]):
            rep = M._entry_replay(dict(leg.cfg), sym, bar, frames, model, PR)
            assert "error" not in rep, rep
            row = {"event": "ml_entry_eval", "strategy": "ml_entry", "symbol": sym, "id": len(rows) + 1,
                   "logged_at_utc": M._iso(bar + 3600 + 120 + k)}
            if rep["side"] == "none":
                row.update({"side": "none", "reason": rep["reason"]})
            else:
                p = rep["pkg"]
                row.update({"side": "buy" if rep["side"] == "long" else "sell", "reason": None, "entry": p["entry"],
                            "stop_loss": p["sl"], "take_profit": p["tp"], "p_long": p["meta"]["p_long"],
                            "p_short": p["meta"]["p_short"]})
            rows.append(row)
    return rows


@pytest.fixture(scope="module")
def entry():
    leg, bundle, _ = _entry_setup()
    rows = _live_from_replay(leg, bundle)
    bundle["signals"]["ml_entry"]["rows"] = rows
    return leg, bundle, rows


def test_clean_entry_control_checks_and_reports_zero(entry):
    leg, bundle, rows = entry
    assert rows
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL)
    assert r["state"] == "checked" and r["divergences"] == 0 and r["evals_checked"] == len(rows)
    assert r["by_class"] and not any(r["by_class"].values())


def test_planted_feature_defect_is_flagged_as_feature_mismatch(entry):
    leg, bundle, rows = entry
    tail = [r for r in rows if "feat=" in (r.get("reason") or "")]
    assert tail, "fixture produced no refusal carrying a feature vector"
    v = tail[0]
    p = M.parse_reason(v["reason"])
    nudged = ",".join(f"{x + (0.01 if i == 8 else 0.0):.5f}" for i, x in enumerate(p["feat"]))
    bad = dict(v, reason=v["reason"].replace(";feat=" + v["reason"].split(";feat=")[1].split(";")[0], f";feat={nudged}"))
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL, evals_override=[bad if x is v else x for x in rows])
    assert r["divergences"] == 1 and r["by_class"]["ml_feature_mismatch"] == 1


def test_planted_flipped_decision_is_flagged(entry):
    leg, bundle, rows = entry
    v = next(x for x in rows if x["side"] == "none")
    fake = {k: val for k, val in v.items() if k != "reason"}
    fake.update({"side": "buy", "reason": None, "entry": 1.0, "stop_loss": 0.9, "take_profit": 1.2,
                 "p_long": 0.5, "p_short": 0.0})
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL, evals_override=[fake if x is v else x for x in rows])
    assert r["divergences"] >= 1 and (r["by_class"]["ml_side_mismatch"] + r["by_class"]["ml_score_mismatch"]) >= 1


def test_planted_geometry_defect_is_flagged():
    leg, bundle, _ = _entry_setup()
    rows = _live_from_replay(leg, bundle)
    pk = [x for x in rows if x["side"] != "none"]
    if not pk:
        pytest.skip("synthetic candles produced no package this seed")
    pk[0]["take_profit"] *= 1.01
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL, evals_override=rows)
    assert r["by_class"]["ml_package_mismatch"] == 1


def test_lost_decision_is_flagged_not_ignored(entry):
    leg, bundle, rows = entry
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL, evals_override=rows[1:])
    assert r["by_class"]["lost_bar"] == 1


def test_unreadable_inputs_are_could_not_check_never_zero(entry):
    leg, bundle, _rows = entry
    for b in (dict(bundle, ml_candles={}), dict(bundle, signals={"ml_entry": {"rows": [], "error": "boom"}}),
              dict(bundle, ml_candles={s: {"candles": [], "error": "fetch_failed"} for s in bundle["ml_candles"]})):
        r = M.analyse_ml_entry(leg, b, SINCE, UNTIL)
        assert r["state"] == "could_not_check" and r["divergences"] is None and r["reason"]
    # live recorded nothing and the replay has no frames to compare with -> nothing comparable, still not 0
    empty = dict(bundle, signals={"ml_entry": {"rows": [], "error": None}}, audit_until_epoch=0)
    r = M.analyse_ml_entry(leg, empty, SINCE, UNTIL)
    assert r["state"] == "could_not_check" and r["divergences"] is None


# ── ml_entry_eq_struct ───────────────────────────────────────────────────────

CFG = {"structure_exit": "pivot=5;sl_only", "artifact": "ml/candidates/ml_entry_eq_v3_struct_ens5/model.json",
       "session": None, "max_snapshot_age_h": 4.0}


def _snap(bar_close, n=173, seed=0):
    rng = np.random.default_rng(seed)
    syms = {}
    for i in range(n):
        row = {k: float(rng.normal(0, 1)) for k in F.FEATURES_B}
        row.update({"hour": 20.0, "dow": 3.0, "atr14": 1.0 + i / 100, "close": 100.0 + i})
        syms[f"E{i}"] = row
    return {"schema": F.SCHEMA, "bar_close": bar_close, "pool_size": n, "covered": n, "symbols": syms,
            "built_at": bar_close}


EQ_CLOSE = "2026-11-10T20:00:00+00:00"   # a decision close for the equity cadence


def _eq_setup(seed=0):
    snap = _snap(EQ_CLOSE, seed=seed)
    cfg = dict(CFG, symbols=list(snap["symbols"]))
    leg = SimpleNamespace(name="ml_entry_eq_struct", symbol="E0", timeframe="1h", unit="ml_entry_eq", decision_bar="closed",
                          execution="live", accounts=["alpaca_live"], real_money=True, features={}, cfg=cfg)
    res = L.score_pool(cfg, snap, cfg["symbols"], L.load_model(L.artifact_path(cfg)))
    pk = {s: v for s, v in res.items() if isinstance(v, dict)}
    assert len(pk) >= 2, "fixture seed produced fewer than 2 packages"
    rows = [{"event": "ml_entry_eq_struct_eval", "strategy": "ml_entry_eq_struct", "symbol": s, "side": "buy", "id": i + 1,
             "entry": v["entry"], "stop_loss": v["sl"], "take_profit": v["tp"],
             "logged_at_utc": M._iso(_ep(EQ_CLOSE) + 120 + i)} for i, (s, v) in enumerate(pk.items())]
    bundle = {"signals": {leg.name: {"rows": rows, "error": None}}, "audit_until_epoch": _ep(EQ_CLOSE) + 8 * 3600,
              "ml_pool_snapshots": {"snapshots": {"20261110T2000Z": snap}, "error": None, "present": True, "index_count": 1}}
    return leg, bundle, rows, pk


EQ_SINCE, EQ_UNTIL = _ep("2026-11-10T00:00:00+00:00"), _ep("2026-11-11T00:00:00+00:00")


def test_clean_eq_control_checks_and_reports_zero():
    leg, bundle, _rows, pk = _eq_setup()
    r = M.analyse_ml_eq(leg, bundle, EQ_SINCE, EQ_UNTIL)
    assert r["state"] == "checked" and r["divergences"] == 0 and r["snapshots_replayed"] == 1
    assert r["evals_checked"] == len(pk)


def test_planted_missing_live_package_is_flagged_missed():
    leg, bundle, rows, _ = _eq_setup()
    r = M.analyse_ml_eq(leg, bundle, EQ_SINCE, EQ_UNTIL, evals_override=rows[1:])
    assert r["by_class"]["ml_missed_package"] == 1 and r["divergences"] == 1


def test_planted_invented_live_package_is_flagged_live_only():
    leg, bundle, rows, pk = _eq_setup()
    refused = next(s for s in leg.cfg["symbols"] if s not in pk)
    fake = {"event": "ml_entry_eq_struct_eval", "strategy": "ml_entry_eq_struct", "symbol": refused, "side": "buy", "id": 999,
            "entry": 1.0, "stop_loss": 0.9, "take_profit": 1.2, "logged_at_utc": M._iso(_ep(EQ_CLOSE) + 300)}
    r = M.analyse_ml_eq(leg, bundle, EQ_SINCE, EQ_UNTIL, evals_override=rows + [fake])
    assert r["by_class"]["ml_live_only_package"] == 1


def test_planted_geometry_difference_is_flagged_on_the_same_symbol():
    leg, bundle, rows, _ = _eq_setup()
    rows[0]["stop_loss"] *= 0.99
    r = M.analyse_ml_eq(leg, bundle, EQ_SINCE, EQ_UNTIL, evals_override=rows)
    assert r["by_class"]["ml_package_mismatch"] == 1


def test_eq_unreadable_or_empty_archive_is_could_not_check_never_zero():
    leg, bundle, _rows, _ = _eq_setup()
    for blob in ({"snapshots": None, "error": "boom"}, {"snapshots": {}, "error": None, "present": False, "index_count": 0}):
        r = M.analyse_ml_eq(leg, dict(bundle, ml_pool_snapshots=blob), EQ_SINCE, EQ_UNTIL)
        assert r["state"] == "could_not_check" and r["divergences"] is None and r["reason"]


# ── wiring into the weekly job ───────────────────────────────────────────────

def test_resolve_legs_covers_both_ml_legs_not_could_not_check():
    import yaml
    acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())
    st = yaml.safe_load((REPO / "config/strategies.yaml").read_text())
    legs = {lg.name: lg for lg in P.resolve_legs(acc, st)}
    for name, unit in (("ml_entry", "ml_entry"), ("ml_entry_eq_struct", "ml_entry_eq")):
        assert name in legs, name
        assert legs[name].skip_reason is None and legs[name].unit == unit, (name, legs[name].skip_reason)


def test_run_dispatches_the_ml_legs_and_the_controls_gate_the_status(entry, monkeypatch):
    leg, bundle, _rows = entry
    bundle = dict(bundle, candles={}, order_packages={"rows": [], "complete": True}, trades={"rows": [], "complete": True},
                  allocator={}, since=M._iso(SINCE), until=M._iso(UNTIL), fetched_at=M._iso(UNTIL))
    doc = P.run(bundle, [leg], SINCE, UNTIL)
    r = doc["legs"][0]
    assert r["state"] == "checked" and r["divergences"] == 0 and r.get("ml_replay")
    c = doc["controls"]["ml_controls"]
    assert c["state"] == "pass", c
    assert c["plants"] and all(p["flagged"] is True for p in c["plants"])
    assert c["clean"] and all(x["passed"] for x in c["clean"])
    assert "ml_entry" not in doc["totals"]["real_money_legs_could_not_check"]


def test_bars_decided_by_the_previous_served_artifact_are_not_comparable(entry, monkeypatch):
    leg, bundle, _ = entry
    monkeypatch.setattr(M, "served_epoch", lambda repo=None: UNTIL + 86400)   # the pointer 'changed' after every bar
    r = M.analyse_ml_entry(leg, bundle, SINCE, UNTIL)
    assert r["state"] == "could_not_check" and r["divergences"] is None


def test_live_nonmodel_refusal_where_replay_decides_is_its_own_class():
    live = {"side": "none", "reason": "feature_row_unformable"}
    rep = {"side": "short", "pkg": {}, "parsed": {"head": "package"}}
    cls, _ = M.compare_entry(live, rep)
    assert cls == "ml_refusal_mismatch"
