"""CF-INSIGHTS step 6: live frequency, corpus mapping and the robust-arm rule (highest LOWER bound, never the highest mean)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
import cf_live_lens as ll  # noqa: E402


def _pk(s, sym, day):
    return {"strategy_name": s, "symbol": sym, "status": "closed", "created_at": f"2026-{(day // 28) + 1:02d}-{day % 28 + 1:02d}T00:00:00+00:00"}


def _r(i, arms):
    return {"k": f"k{i}", "strat": "trend_donchian_eth_4h", "fam": "trend_donchian", "sym": "ETHUSDT", "tf": "4h",
            "dir": "long", "et": f"2026-{i // 672 + 1:02d}-{i % 28 + 1:02d} {i // 28 % 24:02d}:00:00+00:00", "rep": 0.0, "arm": arms, "ctx": {}, "post_mfe": None,
            "post_mae": None, "pv": None, "rdiff": None, "gap": 0.0}


def test_frequency_counts_closed_packages_only_and_annualises():
    pk = [_pk("s", "ETHUSDT", d) for d in range(60)] + [dict(_pk("s", "ETHUSDT", 1), status="open")]
    f = ll.live_frequency(pk)["s"]
    assert f["n_closed"] == 60 and f["symbol"] == "ETHUSDT" and f["trades_per_year"] == round(60 / f["span_days"] * 365, 1)


def test_robust_arm_is_the_highest_lower_bound_not_the_highest_mean():
    # A: steady +0.10 every trade; B: mean +0.20 but half the trades -0.6 / half +1.0 => wide CI
    rows = [_r(i, {"A": 0.10, "B": (1.0 if i % 2 else -0.6)}) for i in range(1200)]
    assert ll.robust_arm(rows)["arm"] == "A"


def test_lens_reports_no_corpus_and_thin_frequency_as_states_not_zeros():
    out = ll.lens([_r(i, {"A": 0.1}) for i in range(600)], [_pk("ghost_leg", "DOGEUSDT", d) for d in range(30)] + [_pk("trend_donchian_eth_4h", "ETHUSDT", d) for d in range(5)])
    st = {r["strategy"]: r["read_state"] for r in out}
    assert st["ghost_leg"] == "no_corpus" and st["trend_donchian_eth_4h"] == "thin_live_frequency"
