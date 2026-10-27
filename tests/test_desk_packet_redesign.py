"""DESK-PACKET-REDESIGN: packet builder modes B / C and the arm runner (synthetic data, no network, no LLM)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.research import desk_packet_arms as pa  # noqa: E402
from scripts.research import desk_packet_modes as pm  # noqa: E402

T0 = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())


def _packet_a():
    """The shape of a masked A packet: the fields modes B / C read or remove."""
    far = {}
    for a in ("ASSET_01", "ASSET_02"):
        for side in ("long", "short"):
            for h in (4, 12, 48):
                far[f"{a}.1h.{side}.h{h}.mean_r"] = 0.1 * h * (1 if side == "long" else -1)
        far[f"{a}.atr"] = 1.5
        far[f"{a}.dist_swing_high_atr"] = 2.0
    return {"meta": {"packet_id": "DP-20000101T0000Z-scan-abc", "missing_inputs": []},
            "history": {"rows": [{"symbol": "ASSET_01", "mean_r": 0.3, "p90_r": 1.0}], "read_state": "read"},
            "features_at_review": far,
            "universe": [{"symbol": "ASSET_01", "atr": 1.5, "session": "asia", "last_close": 100.0},
                         {"symbol": "ASSET_02", "atr": 2.5, "session": "asia", "last_close": 100.0}]}


def _raw(n_min=60 * 24 * 40, start=T0 - 60 * 24 * 35 * 60, seed=0):
    """Two symbols of synthetic 1m bars from `start`, a random walk around 1000 / 50."""
    rng = np.random.default_rng(seed)
    bars, fund = {}, {}
    for s, p0 in (("AAAUSDT", 1000.0), ("BBBUSDT", 50.0)):
        t = start + 60 * np.arange(n_min, dtype=np.int64)
        c = p0 * np.exp(np.cumsum(rng.normal(0, 1e-3, n_min)))
        o = np.r_[p0, c[:-1]]
        h = np.maximum(o, c) * 1.0005
        l = np.minimum(o, c) * 0.9995  # noqa: E741
        v = rng.uniform(1, 3, n_min)
        bars[s] = pm.Raw1m(t, o, h, l, c, v, v * rng.uniform(0.3, 0.7, n_min))
        ft = start + 8 * 3600 * np.arange(n_min // 480)
        fund[s] = np.c_[ft, rng.normal(1e-4, 5e-5, len(ft))]
    return pm.RawStore(bars, fund)


def _key(raw, cutoff):
    key = {"cutoff_epoch": cutoff, "alias": {"ASSET_01": "AAAUSDT", "ASSET_02": "BBBUSDT"}, "price_scale": {}}
    for a, s in key["alias"].items():
        b = raw.bars[s]
        j = int(np.searchsorted(b.t + 60, cutoff, side="right")) - 1          # the last 1m bar closed by the cutoff
        key["price_scale"][a] = 100.0 / float(b.c[j])
    return key


# ----------------------------------------------------------------------------- mode B
def test_mode_b_removes_every_base_rate_quantity_and_nothing_else():
    a = _packet_a()
    b = pm.strip_base_rates(a)
    assert "history" not in b and pm.base_rate_keys_left(b) == []
    assert "history" in a and pm.base_rate_keys_left(a)              # the input is not mutated
    assert b["features_at_review"] == {k: v for k, v in a["features_at_review"].items() if not k.endswith("_r")}
    assert b["universe"] == a["universe"] and b["meta"]["packet_id"] == a["meta"]["packet_id"]
    assert b["meta"]["packet_mode"] == "B"


def test_apply_a_is_identity_and_unknown_mode_raises():
    a = _packet_a()
    assert pm.apply("A", a, {}) is a
    with pytest.raises(ValueError):
        pm.apply("D", a, {})
    with pytest.raises(ValueError):
        pm.apply("C", a, {}, None)


# ----------------------------------------------------------------------------- mode C
def test_aggregate_builds_closed_buckets_from_1m():
    raw = _raw()
    cut = T0 + 7 * 3600                                     # on the hour
    a = pm.aggregate(raw.bars["AAAUSDT"], 300, cut, 12)
    assert len(a) == 12 and a[-1][0] == cut - 300           # the newest 5m bucket closed AT the cutoff
    b = raw.bars["AAAUSDT"]
    m = (b.t >= cut - 300) & (b.t < cut)
    assert a[-1][1] == b.o[m][0] and a[-1][4] == b.c[m][-1]
    assert a[-1][2] == b.h[m].max() and a[-1][3] == b.l[m].min()
    assert a[-1][5] == pytest.approx(b.v[m].sum()) and a[-1][6] == pytest.approx(b.tb[m].sum())


def test_mode_c_is_point_in_time():
    """Nothing at or after the cutoff: a store truncated AT the cutoff builds the identical packet, and perturbing
    every bar after the cutoff changes nothing."""
    raw = _raw()
    cut = T0 + 7 * 3600
    key = _key(raw, cut)
    full = pm.raw_packet(_packet_a(), key, raw)
    cutstore = pm.RawStore({s: b.upto(cut) for s, b in raw.bars.items()},
                           {s: f[f[:, 0] <= cut] for s, f in raw.funding.items()})
    assert pm.raw_packet(_packet_a(), key, cutstore) == full
    for b in raw.bars.values():
        after = b.t + 60 > cut
        b.c[after] *= 3.0
        b.h[after] *= 3.0
    raw.funding["AAAUSDT"][raw.funding["AAAUSDT"][:, 0] > cut, 1] = 9.0
    assert pm.raw_packet(_packet_a(), key, raw) == full


def test_mode_c_carries_no_summary_and_rebases_to_the_last_close():
    raw = _raw()
    cut = T0 + 7 * 3600
    c = pm.raw_packet(_packet_a(), _key(raw, cut), raw)
    assert pm.base_rate_keys_left(c) == [] and "history" not in c
    assert pm.check_against_1h(c) == []                    # newest 1h close = the rebased last close (0 bps)
    for a in c["assets"].values():
        assert set(a) == {"atr_1h", "session", "funding_bps_per_8h", "bars"}
        assert [len(a["bars"][nm]) for nm, _, _ in pm.RAW_TABLES] == [n for _, _, n in pm.RAW_TABLES]
        assert len(a["funding_bps_per_8h"]) == pm.FUNDING_PRINTS
    txt = pm.render_raw_text(c)
    assert "mean_r" not in txt and "USDT" not in txt and c["packet_id"] in txt


def test_check_against_1h_flags_a_mismatch():
    raw = _raw()
    c = pm.raw_packet(_packet_a(), _key(raw, T0 + 7 * 3600), raw)
    c["assets"]["ASSET_01"]["bars"]["1h"][-1][2] = 9
    assert pm.check_against_1h(c) == ["ASSET_01: newest 1h close 9 bps, expected 0"]


def test_months_for_covers_the_1d_lookback():
    c = int(datetime(2026, 3, 2, tzinfo=timezone.utc).timestamp())
    assert pm.months_for([c]) == ["2026-01", "2026-03"]           # 31 days back from 2026-03-02 is 2026-01-30


# ----------------------------------------------------------------------------- the arm runner
def test_protocol_a_is_the_v1_protocol_and_b_c_drop_the_base_rate_sentence():
    v1 = REPO / "comms/research/desk_edge/dev-1/JUDGE-PROTOCOL.md"
    assert pa.protocol("A") == v1.read_text()
    for arm in ("B", "C"):
        p = pa.protocol(arm)
        assert "base rates" not in p.split("Reply with")[0] or "NO" in p.split("Reply with")[0]
        assert "history` rows" not in p and "SCORE EVERY (asset, side) cell" in p


def test_base_rate_r2_detects_a_linear_rule_and_not_noise():
    rng = np.random.default_rng(1)
    order = [f"p{j}" for j in range(40)]
    base = {p: {f"S{i}:{sd}": tuple(rng.normal(size=3)) for i in range(6) for sd in ("long", "short")} for p in order}
    lin = {p: {c: 0.2 * x[1] + 0.1 * x[2] for c, x in base[p].items()} for p in order}
    noise = {p: {c: float(rng.normal()) for c in base[p]} for p in order}
    r_lin, r_noise = pa.base_rate_r2(lin, base, order), pa.base_rate_r2(noise, base, order)
    assert r_lin["pooled_r2"] == pytest.approx(1.0) and r_lin["median_group_r2"] == pytest.approx(1.0)
    assert r_noise["pooled_r2"] < 0.1 and len(r_noise["group_r2"]) == 4


def test_recommend_needs_s3_bar_and_ci():
    def arm(s3, lo, dec="screen_fail"):
        return {"s3_top_pick": {"s3": s3, "ci95": [lo, 1.0], "useful": s3 >= pa.S3_USEFUL and lo > 0}, "sel": {"decision": dec}}
    assert pa.recommend({"A": arm(0.16, -0.18), "B": arm(0.30, -0.01)})[0] == "none_yet"
    rec, why = pa.recommend({"A": arm(0.16, -0.18), "B": arm(0.30, 0.02), "C": arm(0.40, 0.05, "promote")})
    assert rec == "C" and len(why) == 1
    rec, why = pa.recommend({"B": arm(0.30, 0.02)})
    assert rec == "B" and "holdout" in why[1]


def test_contrast_is_paired_by_packet():
    weeks = {f"p{j}": f"2026-W{j // 3:02d}" for j in range(30)}
    a = {"_per_packet": {"sel": {p: (w, 0.0) for p, w in weeks.items()}, "top_long": {p: 0.0 for p in weeks}, "week": weeks}}
    x = {"_per_packet": {"sel": {p: (w, 0.5) for p, w in weeks.items()}, "top_long": {p: 1.0 for p in weeks}, "week": weeks}}
    c = pa.contrast(a, x)
    assert c["sel"]["diff"] == pytest.approx(0.5) and c["sel"]["differs"] and c["sel"]["packets"] == 30
    assert c["top_cell_long_share"]["diff"] == pytest.approx(1.0)
    same = pa.contrast(a, a)
    assert not same["sel"]["differs"]


def test_registered_constants():
    assert pa.S3_USEFUL == 0.25 and pa.R2_BREAK == 0.50 and pa.CONTRAST_ALPHA == pytest.approx(0.025)
    assert json.loads(json.dumps(pm.RAW_TABLES)) == [["1m", 60, 30], ["5m", 300, 48], ["1h", 3600, 48], ["4h", 14400, 30], ["1d", 86400, 20]]


def test_score_takes_only_the_looks_the_sample_reaches():
    """At n=50 the 75- and 100-packet looks are not taken (they would re-use the same 50 packets)."""
    src = (REPO / "scripts/research/desk_packet_arms.py").read_text()
    assert "L <= len(order) and set(order[:L]) <= set(ranks)" in src


def test_c_size_cap_is_registered_and_enforced_in_build():
    """Amendment 2: one fixed cap for every C packet, refused (not trimmed) above it."""
    assert pa.MAX_C_CHARS == 24_000 and pa.BATCH_C == 2
    src = (REPO / "scripts/research/desk_packet_arms.py").read_text()
    assert 'if len(text) > MAX_C_CHARS:' in src
    raw = _raw()
    txt = pm.render_raw_text(pm.raw_packet(_packet_a(), _key(raw, T0 + 7 * 3600), raw))
    assert len(txt) < pa.MAX_C_CHARS            # two aliases here; six real ones measured 20,274 median
