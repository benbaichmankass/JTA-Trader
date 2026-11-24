"""AM v2 Stage B (scripts/research/am_policy_arm.py): parity with the baseline replay, no lookahead, one fixture per action class, the engine's two new
actions, the heads dump/load round trip and the reduce/grade plumbing. Offline: synthetic bars, no network."""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    sys.path.insert(0, str(p))

import am_policy_arm as P  # noqa: E402
import cf_core  # noqa: E402
import cf_harness  # noqa: E402

T0 = 1704067200.0          # 2024-01-01T00:00Z, an hourly boundary: the signal bar opens here
SEC = 3600.0
THR = {"stop_first": {"p90": 0.5}, "dip_recovers": {"p50": 0.1, "p90": 0.5}}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def bar(t, o, h, l, c):
    return {"time": float(t), "open": o, "high": h, "low": l, "close": c, "dur": SEC}


def make_bars(path, pre_low=99.0, n_pre=30):
    """30 pre-entry bars (the last is the signal bar, opening at T0) then ``path`` = [(o,h,l,c), ...] as bars 1..n."""
    out = [bar(T0 - (n_pre - 1 - i) * SEC, 100.0, 101.0, pre_low, 100.0) for i in range(n_pre)]
    out += [bar(T0 + (i + 1) * SEC, *x) for i, x in enumerate(path)]
    return out


def make_job(*, tp=None, exit_after=40, reason="sl", entry=100.0, sl=98.0, direction="long"):
    meta = {"tp": tp} if tp is not None else {}
    return {"strategy": "trend_donchian_t", "symbol": "BTCUSDT", "entry_time": iso(T0), "exit_time": iso(T0 + exit_after * SEC), "direction": direction,
            "entry": entry, "sl": sl, "net_r": -1.0, "cost_fee_r": 0.02, "exit_reason": reason, "_leg_meta": meta, "trade_key": "k1"}


def ctx_for(path, **kw):
    pre_low = kw.pop("pre_low", 99.0)
    job = make_job(**kw)
    return P.make_ctx(job, make_bars(path, pre_low=pre_low), "1h"), job


def preds(n, q50=1.0, q90=2.0, stop=0.0, dip=0.0):
    return {"q0.5": [q50] * n, "q0.9": [q90] * n, "stop_first": [stop] * n, "dip_recovers": [dip] * n}


FLAT = [(100.8, 101.0, 100.0, 100.8), (100.8, 101.5, 100.5, 101.0), (101.0, 101.4, 100.6, 101.2)] + [(101.2, 101.6, 100.8, 101.2)] * 10


# ---- parity ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("reason", ["sl", "timeout"])
def test_baseline_arm_is_replayed_actual(reason):
    path = [(100.8, 103.0, 100.0, 102.0), (102.0, 104.0, 101.5, 103.0), (103.0, 103.5, 97.0, 98.0)] + [(98.0, 99.0, 97.0, 98.0)] * 20
    ctx, job = ctx_for(path, tp=106.0, reason=reason, exit_after=12)
    base = P.run_arm(ctx)
    cfg = {"timeframe": "1h"}
    row = {k: v for k, v in job.items() if not k.startswith("_")}
    cf = cf_harness.cf_fields(row, ctx["bars"], None, cfg, n_random=5, leg_meta=job["_leg_meta"], entry_at_bar_close=True)
    assert cf["status"] == "graded"
    assert round(base["net_r"], 4) == cf["arms"]["replayed_actual_net_r"]


def test_policy_that_never_acts_equals_baseline_exactly():
    path = [(100.8, 103.0, 100.0, 102.0), (102.0, 104.0, 101.5, 103.0), (103.0, 103.5, 97.0, 98.0)] + [(98.0, 99.0, 97.0, 98.0)] * 5
    ctx, _ = ctx_for(path, tp=106.0)
    base = P.run_arm(ctx)
    # actions that exist in the policy's vocabulary but cannot change this path: a bank far above the path, a TP set to the TP it already has,
    # a "tighten" below the live stop (set_stop only ever tightens) and a "loosen" that is not looser than the live stop
    noop = [{"ts": T0 + 2 * SEC, "kind": "bank_at", "level": 150.0, "frac": 0.5}, {"ts": T0 + 2 * SEC, "kind": "set_tp", "level": 106.0},
            {"ts": T0 + 2 * SEC, "kind": "set_stop", "level": 90.0}, {"ts": T0 + 2 * SEC, "kind": "loosen_stop", "level": 99.0}]
    arm = P.run_arm(ctx, noop)
    assert arm["net_r"] == base["net_r"] and arm["fills"] == base["fills"] and arm["exit_ts"] == base["exit_ts"]
    # and a policy whose score cuts are unreachable emits nothing, so every arm of the trade equals HOLD
    rows = P.decision_rows(ctx)
    rec = P.replay_trade(ctx, rows, preds(len(rows), stop=0.9, dip=0.0), {"stop_first": {"p90": 2.0}, "dip_recovers": {"p50": -1.0, "p90": 2.0}}, ["tighten", "loosen"], 3)
    assert rec["a"] == {"tighten": {"n": 0}, "loosen": {"n": 0}}


# ---- no lookahead ----------------------------------------------------------------------------------------------------
def _fake_preds(rows):
    f = [r["features"] for r in rows]
    return {"q0.5": [max(0.0, 1.2 - x["open_r"] * 0.3 + 0.1 * x["bars_since_peak"]) for x in f], "q0.9": [2.5 + 0.2 * x["peak_r"] for x in f],
            "stop_first": [0.9 if x["open_r"] < 0.9 else 0.1 for x in f], "dip_recovers": [0.0 if x["open_r"] < 0.9 else 0.9 for x in f]}


def test_actions_up_to_bar_k_do_not_depend_on_later_bars():
    rng = random.Random(7)
    path = [(100.8, 101.5, 99.6, 100.7), (100.7, 102.0, 100.2, 101.6), (101.6, 102.5, 100.9, 102.0), (102.0, 102.2, 100.4, 100.9),
            (100.9, 101.4, 100.0, 101.0), (101.0, 101.2, 100.1, 100.5)] + [(100.5, 101.0, 100.0, 100.6)] * 6
    K = 4
    fut = list(path)
    for i in range(K, len(fut)):                                    # a different future from bar K+1 on
        o = 100 + rng.uniform(-1, 3)
        fut[i] = (o, o + rng.uniform(0.2, 2.5), o - rng.uniform(0.2, 1.5), o + rng.uniform(-1, 1))
    a, _ = ctx_for(path, tp=108.0, exit_after=20)
    b, _ = ctx_for(fut, tp=108.0, exit_after=20)
    out = []
    for ctx in (a, b):
        rows = P.decision_rows(ctx)
        specs = P.decide(ctx, rows, _fake_preds(rows), THR, ["combined"])
        out.append([(s["cls"], s["k"], s["ts"], s["kind"], round(s["level"], 9)) for s in specs if s["k"] <= K])
        for s in specs:                                             # every move is stamped at the CLOSE of its decision bar, never before
            assert s["ts"] == ctx["post"][s["k"] - 1]["time"] + SEC
    assert out[0] == out[1] and out[0], "the early actions must exist and match"


# ---- one fixture per action class -------------------------------------------------------------------------------------
def test_target_pulls_in_extends_and_leaves_in_band():
    ctx, _ = ctx_for(FLAT, tp=110.0)                                # tp0 = +5 R, far above q0.9
    rows = P.decision_rows(ctx)
    s = P.decide(ctx, rows, preds(len(rows), q50=1.0, q90=2.0), THR, ["target"])[0]
    assert (s["kind"], s["k"]) == ("set_tp", 1) and s["level"] == pytest.approx(100.0 + 2.0 * (0.4 + 2.0))      # open_r 0.4 + q0.9 2.0 = 2.4 R
    ctx2, _ = ctx_for(FLAT, tp=101.0)                               # tp0 = +0.5 R, nearer than the median reach
    rows2 = P.decision_rows(ctx2)
    s2 = P.decide(ctx2, rows2, preds(len(rows2), q50=1.0, q90=2.0), THR, ["target"])[0]
    assert s2["level"] == pytest.approx(100.0 + 2.0 * (0.4 + 1.0))                                              # extended to the q0.5 level
    ctx5, _ = ctx_for(FLAT, tp=103.0)                               # tp0 = +1.5 R, inside [0.4 + 0.5, 0.4 + 2.0] = [0.9, 2.4] at bar 1: left alone
    assert P.decide(ctx5, P.decision_rows(ctx5)[:1], preds(1, q50=0.5, q90=2.0), THR, ["target"]) == []
    # a leg with no TP in the replay gets no target action
    ctx6, _ = ctx_for(FLAT)
    assert P.decide(ctx6, P.decision_rows(ctx6), preds(len(P.decision_rows(ctx6))), THR, ["target"]) == []
    # the pulled-in TP actually fills at its level
    path = [(100.8, 101.0, 100.0, 100.8), (100.8, 105.5, 100.5, 105.0), (105.0, 105.2, 97.0, 98.0)] + [(98.0, 98.5, 97.0, 97.5)] * 8
    c, _ = ctx_for(path, tp=112.0)
    rw = P.decision_rows(c)
    sp = P.decide(c, rw, preds(len(rw), q50=1.0, q90=2.0), THR, ["target"])
    arm, base = P.run_arm(c, [P._spec_action(x) for x in sp]), P.run_arm(c)
    assert arm["fills"][-1]["reason"] == "tp" and arm["fills"][-1]["px"] == pytest.approx(sp[0]["level"]) and arm["net_r"] > base["net_r"]


def test_tighten_cuts_the_loss_the_original_stop_would_take():
    path = [(100.8, 101.0, 100.0, 100.8), (100.8, 100.9, 99.0, 99.2), (99.2, 99.3, 97.5, 98.0)] + [(98.0, 98.5, 97.0, 97.5)] * 8
    ctx, _ = ctx_for(path, tp=110.0)
    rows = P.decision_rows(ctx)
    specs = P.decide(ctx, rows, preds(len(rows), stop=0.9, dip=0.0), THR, ["tighten"])
    assert specs and specs[0]["kind"] == "set_stop" and specs[0]["level"] == pytest.approx(100.0 + 2.0 * (-1.0 + 0.5 * (0.4 + 1.0)))
    arm, base = P.run_arm(ctx, [P._spec_action(x) for x in specs]), P.run_arm(ctx)
    assert arm["fills"][-1]["reason"] == "stop" and arm["fills"][-1]["px"] > base["fills"][-1]["px"] and arm["net_r"] > base["net_r"]
    # a high dip-recovers score vetoes the tighten
    assert P.decide(ctx, rows, preds(len(rows), stop=0.9, dip=0.9), THR, ["tighten"]) == []


def test_loosen_to_structure_lets_a_dip_recover():
    path = [(100.8, 101.0, 100.0, 100.8), (100.8, 101.0, 100.0, 100.5), (100.5, 100.6, 97.9, 99.5), (99.5, 104.0, 99.0, 103.0)] + [(103.0, 107.5, 102.0, 107.0)] * 6
    ctx, _ = ctx_for(path, tp=106.0, pre_low=95.5)                  # the pre-entry swing low (95.5) sits well beyond the 98 stop
    rows = P.decision_rows(ctx)
    assert [r["k"] for r in rows] == [1, 2]                         # the unmanaged trade is stopped on bar 3: no decision row at or after it
    specs = P.decide(ctx, rows, preds(len(rows), stop=0.0, dip=0.9), THR, ["loosen"])
    assert specs and specs[0]["kind"] == "loosen_stop"
    assert specs[0]["level"] == pytest.approx(100.0 - 2.0 * 2.0)    # (95.5 - 100)/2 = -2.25 R, minus the buffer, capped at -2 R -> 96.0
    arm, base = P.run_arm(ctx, [P._spec_action(x) for x in specs]), P.run_arm(ctx)
    assert base["fills"][-1]["reason"] == "stop" and arm["fills"][-1]["reason"] == "tp" and arm["net_r"] > base["net_r"] + 1.5
    assert P.decide(ctx, rows, preds(len(rows), stop=0.0, dip=0.0), THR, ["loosen"]) == []     # the head must call the dip
    ctx2, _ = ctx_for(path, tp=106.0, pre_low=99.0)                 # structure not beyond the stop: nothing to loosen to
    assert P.decide(ctx2, P.decision_rows(ctx2), preds(2, dip=0.9), THR, ["loosen"]) == []


def test_bank_takes_half_at_the_median_target_and_charges_slippage():
    path = [(100.8, 101.0, 100.0, 100.8), (100.8, 103.2, 100.5, 102.0), (102.0, 102.5, 97.0, 98.0)] + [(98.0, 98.5, 97.0, 97.5)] * 8
    ctx, _ = ctx_for(path, tp=110.0)
    rows = P.decision_rows(ctx)
    specs = P.decide(ctx, rows, preds(len(rows), q50=1.0), THR, ["bank"])
    assert specs[0]["kind"] == "bank_at" and specs[0]["frac"] == 0.5 and specs[0]["level"] == pytest.approx(100.0 + 2.0 * 1.4)
    arm, base = P.run_arm(ctx, [P._spec_action(x) for x in specs]), P.run_arm(ctx)
    assert [f["reason"] for f in arm["fills"]] == ["partial", "stop"] and arm["fills"][0]["frac"] == 0.5
    assert arm["fills"][0]["px"] == pytest.approx(102.8) and arm["net_r"] > base["net_r"]
    assert arm["cost_r"]["slip"] == pytest.approx(base["cost_r"]["slip"])                  # the partial pays exit slippage like any non-TP fill (conservative)


def test_combined_runs_all_four_components_and_controls_keep_counts():
    path = [(100.8, 101.0, 100.0, 100.8), (100.8, 103.2, 100.5, 102.0), (102.0, 102.5, 97.0, 98.0)] + [(98.0, 98.5, 97.0, 97.5)] * 8
    ctx, _ = ctx_for(path, tp=110.0, pre_low=95.5)
    rows = P.decision_rows(ctx)
    pr = {"q0.5": [1.0] * len(rows), "q0.9": [2.0] * len(rows), "stop_first": [0.9] * len(rows), "dip_recovers": [0.0] * len(rows)}
    specs = P.decide(ctx, rows, pr, THR, ["combined"])
    assert {s["cls"] for s in specs} >= {"target", "bank", "tighten"}
    cs = P.control_specs(ctx, rows, specs, P.control_rng("k1", "combined", 0))
    for cls in {s["cls"] for s in specs}:
        assert sum(1 for c in cs if c["cls"] == cls) == min(sum(1 for s in specs if s["cls"] == cls), len(rows))
    assert [c["cls"] for c in cs] == [c["cls"] for c in sorted(cs, key=lambda x: x["cls"])]  # deterministic order, seeded per (trade, class, draw)
    assert cs == P.control_specs(ctx, rows, specs, P.control_rng("k1", "combined", 0))
    assert cs != P.control_specs(ctx, rows, specs, P.control_rng("k1", "combined", 1)) or len(rows) <= 1


# ---- the engine's two new actions -------------------------------------------------------------------------------------
def test_cf_core_loosen_stop_never_tightens_and_bank_at_banks_once():
    bars = [bar(T0 + i * SEC, 100, 100.5, 99.5, 100) for i in range(3)] + [bar(T0 + 3 * SEC, 100, 103, 99.5, 102), bar(T0 + 4 * SEC, 102, 104, 101, 103)]
    kw = dict(side="long", entry_ref=100.0, r_dist=2.0, t_entry=T0, stop0=98.0, tp=None)
    s = cf_core.simulate(bars, actions=[{"ts": T0, "kind": "set_stop", "level": 99.0}, {"ts": T0, "kind": "loosen_stop", "level": 99.5}], **kw)
    assert s["fills"][-1]["reason"] == "open_at_data_end"           # loosen_stop to 99.5 is TIGHTER than 99.0: ignored, and the 99.5 low does not trade through 99
    s2 = cf_core.simulate([bar(T0, 100, 100.5, 98.5, 100)], actions=[{"ts": T0, "kind": "loosen_stop", "level": 97.0}], **kw)
    assert s2["fills"][-1]["reason"] == "open_at_data_end"          # stop moved from 98 to 97: the 98.5 low does not stop it either way
    s3 = cf_core.simulate([bar(T0, 100, 100.5, 97.5, 100)], actions=[{"ts": T0, "kind": "loosen_stop", "level": 97.0}], **kw)
    assert s3["fills"][-1]["reason"] == "open_at_data_end"          # 97.5 > 97: survives; the original 98 stop would have filled
    s4 = cf_core.simulate([bar(T0, 100, 100.5, 97.5, 100)], **kw)
    assert s4["fills"][-1]["reason"] == "stop"
    b = cf_core.simulate(bars, actions=[{"ts": T0, "kind": "bank_at", "level": 101.0, "frac": 0.4}, {"ts": T0 + SEC, "kind": "bank_at", "level": 101.5, "frac": 0.4}], **kw)
    parts = [f for f in b["fills"] if f["reason"] == "partial"]
    assert len(parts) == 1 and parts[0]["frac"] == pytest.approx(0.4)      # one bank only: the later order does not re-bank


# ---- heads dump / load round trip ---------------------------------------------------------------------------------------
def _dump_heads(tmp_path, strategies):
    np = pytest.importorskip("numpy")
    pytest.importorskip("lightgbm")
    import am_heads_fit as H
    rng = np.random.default_rng(1)
    n = 12000
    arr = {k: rng.normal(size=n).astype("float32") for k in H.FEATS}
    arr["strat"] = rng.integers(0, 3, n).astype("float32")
    arr["side"] = np.where(rng.random(n) > 0.5, 1.0, -1.0).astype("float32")
    arr["fwd_mfe_r"] = np.abs(arr["open_r"] + rng.normal(size=n)).astype("float32")
    for h in H.BIN_HEADS:
        arr[h] = (arr["open_r"] + rng.normal(size=n) > 0.3).astype("float32")
    tidx = np.arange(n, dtype="int32") // 10
    rec = H.dump_fold(arr, tidx, np.arange(0, n // 10), 20000, np.random.default_rng(2), "2024-01-01", tmp_path)
    man = {"schema": "am_heads_dump/1", "feats": H.FEATS, "heads": list(H.DUMP_HEADS), "strategies": strategies,
           "folds": [{**rec, "kind": "dev", "test_start": "2024-01-01", "test_end": "2024-07-01"}]}
    (tmp_path / "manifest.json").write_text(json.dumps(man))
    return arr, rec, H


def test_heads_dump_load_round_trip(tmp_path):
    arr, rec, H = _dump_heads(tmp_path, {"0": "a", "1": "trend_donchian_t", "2": "c"})
    import numpy as np
    assert set(rec["files"]) == set(H.DUMP_HEADS) and set(rec["thresholds"]) == set(H.BIN_HEADS)
    heads = P.Heads(tmp_path)
    assert heads.strat["trend_donchian_t"] == 1 and heads.fold_of(T0 + 5)["fold_id"] == "2024-01-01" and heads.fold_of(T0 - 10 * 86400) is None
    X = np.column_stack([arr[k] for k in H.FEATS])[:50]
    p = heads.predict("2024-01-01", X)
    assert set(p) == set(P.Heads.NEEDED) and all(len(v) == 50 for v in p.values()) and (p["q0.9"] >= p["q0.5"]).all()
    assert ((p["stop_first"] >= 0) & (p["stop_first"] <= 1)).all()
    (tmp_path / "2024-01-01" / "q0.5.txt").write_text("tampered")
    with pytest.raises(ValueError):
        P.Heads(tmp_path)


def test_run_shard_end_to_end_on_synthetic_bars(tmp_path):
    """plan-shaped inputs -> heads -> per-trade arms -> reduce: the plumbing the workflow runs, offline (the fetcher is a stub)."""
    hd = tmp_path / "heads"
    hd.mkdir()
    _dump_heads(hd, {"0": "trend_donchian_t", "1": "x", "2": "y"})
    heads = P.Heads(hd)
    rng = random.Random(5)
    jobs, keys = {}, []
    allrows = []
    for i in range(30):
        t0 = T0 + i * 6 * SEC
        j = {**make_job(tp=106.0, exit_after=20, reason="timeout"), "entry_time": iso(t0), "exit_time": iso(t0 + 20 * SEC)}
        jobs[f"k{i}"] = j
        keys.append(f"k{i}")
    px = 100.0
    t = T0 - 40 * SEC
    while t < T0 + 400 * SEC:
        o = px
        px = max(90.0, o + rng.uniform(-1.2, 1.3))
        allrows.append({"time": t, "open": o, "high": max(o, px) + rng.uniform(0, 0.8), "low": min(o, px) - rng.uniform(0, 0.8), "close": px})
        t += SEC
    shard = {"shard_id": "BTCUSDT_1h_test", "symbol": "BTCUSDT", "timeframe": "1h", "n_jobs": len(keys)}
    meta = P.run_shard(shard, {"BTCUSDT_1h_test": keys}, jobs, heads, tmp_path, ["target", "tighten", "combined"], n_control=3,
                       fetcher=lambda sym, tf, a, b: allrows)
    assert meta["state"] == "done" and meta["n_replayed"] == 30 and meta["n_decision_rows"] > 30
    recs, metas = P.read_shards(tmp_path)
    assert len(recs) == 30 and len(metas) == 1
    r = recs[0]
    assert set(r["a"]) == {"target", "tighten", "combined"} and r["f"] == "2024-01-01"
    for rr in recs:                                               # HOLD in every record is replayed_actual of the same trade
        ctx = P.make_ctx(dict(jobs[rr["k"]], trade_key=rr["k"]), [b | {"dur": SEC} for b in allrows], "1h")
        assert rr["b"][0] == round(P.run_arm(ctx)["net_r"], 6)
        for cell in rr["a"].values():
            assert cell["n"] == 0 or len(cell["cn"]) == 3
    # a trade that entered before the first fold is counted, not replayed
    early = {**jobs["k0"], "entry_time": iso(T0 - 30 * 86400), "exit_time": iso(T0 - 30 * 86400 + 20 * SEC)}
    shift = -30 * 86400
    early_bars = [{**b, "time": b["time"] + shift} for b in allrows]
    m2 = P.run_shard({**shard, "shard_id": "e"}, {"e": ["z"]}, {"z": early}, heads, tmp_path / "o2", ["target"], n_control=1, fetcher=lambda *a: early_bars)
    assert m2["n_replayed"] == 0 and m2["could_not_replay"] == {"entry_before_first_fold": 1}
    m3 = P.run_shard({**shard, "shard_id": "n"}, {"n": ["z"]}, {"z": early}, heads, tmp_path / "o3", ["target"], n_control=1, fetcher=lambda *a: [])
    assert m3["could_not_replay"] == {"no_bars": 1}


# ---- reduce / grade ------------------------------------------------------------------------------------------------------
def _recs(n, *, edge):
    rng = random.Random(3)
    out = []
    for i in range(n):
        yr = 2022 + (i * 5) // n                                      # 2022..2026: the last fifth is holdout
        e = f"{yr}-{1 + i % 12:02d}-{1 + i % 27:02d}T00:00:00+00:00"
        x = int(datetime.fromisoformat(e).timestamp()) + 4 * 3600
        base = rng.gauss(0.0, 1.0)
        # the policy halves a loser half the time (a drawdown cut) at a small cost; the controls are plain noise around HOLD
        pol = base * 0.5 - 0.01 if (base < -0.8 and edge) else base
        out.append({"k": f"k{i}", "st": "s", "sy": "BTCUSDT", "tf": "1h", "e": e, "f": "x", "b": [round(base, 6), x, 1.0],
                    "a": {"target": {"n": 1, "p": [round(pol, 6), x, 1.0], "c": [[round(base + rng.gauss(0, 0.05), 6), x] for _ in range(20)]}}})
    return out


def _write_shard(out: Path, recs):
    d = out / "am_policy"
    d.mkdir(parents=True)
    import gzip
    with gzip.open(d / "s1.jsonl.gz", "wt") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in recs)
    (d / "s1.meta.json").write_text(json.dumps({"shard_id": "s1", "could_not_replay": {}}))


def test_reduce_claims_the_holdout_first_and_grades_both_segments(tmp_path):
    _write_shard(tmp_path, _recs(2000, edge=True))
    ledger = tmp_path / "ledger.jsonl"
    res = P.reduce_run(tmp_path, "target", "RQ-test", "tester", ledger, True, 20)
    assert ledger.exists() and json.loads(ledger.read_text().splitlines()[0])["family"] == "AM-HEADS"
    assert (tmp_path / "holdout_claims.jsonl").exists() and res["holdout_claim"]["n_tries"] == 1
    assert res["read_state"] == "measured" and res["graduation_eligible"] is False and res["n"] == 2000
    assert res["dev"]["n"] + res["holdout"]["n"] == 2000 and res["dev"]["controls"]["n"] == 20
    assert res["verdict"] in ("pass", "fail", "indeterminate")
    brief = P._brief(res)
    assert brief["verdict"] == res["verdict"] and "measurement" in brief and brief["n"] == 2000
    assert P.unit_verdict({"verdict": "fail"}, {"verdict": "pass"}) == "fail"
    assert P.unit_verdict({"verdict": "pass"}, {"verdict": "pass"}) == "pass"
    assert P.unit_verdict({"verdict": "pass"}, {"verdict": "indeterminate"}) == "indeterminate"
    assert P.unit_verdict({"verdict": "indeterminate"}, {"verdict": "pass"}) == "indeterminate"


def test_a_policy_that_never_fired_is_indeterminate_not_pass(tmp_path):
    recs = _recs(800, edge=False)
    for r in recs:
        r["a"] = {"target": {"n": 0}}
    _write_shard(tmp_path, recs)
    res = P.reduce_run(tmp_path, "target", "RQ-test", "tester", None, False, 20)
    assert res["verdict"] == "indeterminate" and res["lever"]["trades_fired"] == 0 and res["dev"]["label"] == "lever_never_fired"
