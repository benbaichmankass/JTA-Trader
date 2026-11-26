"""ADX-cell removal confirmation (rostered_leg_replay --mode adxcell, RQ-20261126-4d1c-01): live-detector regime at entry, cells from
config/regime_policy.yaml (YAML booleans normalised), removal framed as add-back weights 2/1."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO))


def test_cells_normalise_yaml_booleans():
    import rostered_leg_replay as R
    c = R.load_cells()
    assert c["trending"]["htf_pullback_trend_2h"] == {"long": "off", "short": "off"}
    assert c["transitional"]["htf_pullback_trend_2h"] == {"long": "on", "short": "off"}


def test_regime_at_entry_uses_the_last_closed_bar():
    import rostered_leg_replay as R
    from src.runtime.regime.detector import regime_label, wilder_adx
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=300, freq="2h", tz="UTC")
    c = 100 + np.cumsum(rng.normal(0, 1, 300))
    bars = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c}, index=idx)
    when = pd.Series([idx[100] + pd.Timedelta(hours=2), idx[100] + pd.Timedelta(hours=1), idx[0]])
    got = R.adx_regime_at_entry(bars, when, 7200.0).tolist()
    adx = wilder_adx(bars)
    assert got[0] == regime_label(float(adx.iloc[100]))      # bar 100 closes exactly at the entry: it counts
    assert got[1] == regime_label(float(adx.iloc[99]))       # mid-bar entry: only bar 99 has closed
    assert got[2] == "unknown"                               # nothing closed yet


def test_removal_delta_is_the_dropped_trades_r(monkeypatch):
    import rostered_leg_replay as R
    rng = np.random.default_rng(1)
    n = 800
    ts = pd.Series(pd.to_datetime("2022-01-03", utc=True) + pd.to_timedelta(np.sort(rng.uniform(0, 1700, n)), unit="D"))
    tr = pd.DataFrame({"family": "htf_pullback_trend_2h", "direction": rng.choice(["long", "short"], n), "net_r": rng.normal(0, 1, n), "ts": ts})
    regimes = rng.choice(["trending", "transitional", "chop"], n)
    monkeypatch.setattr(R, "adx_regime_at_entry", lambda bars, when, tf: pd.Series(regimes[when.index], index=when.index))
    out = R.grade_adxcell(tr, {"htf_pullback_trend_2h": None}, {"htf_pullback_trend_2h": 7200.0}, R.load_cells())
    g = out["arms"]["remove_cells"]
    kept = (regimes == "transitional") & (tr.direction.to_numpy() == "long")
    assert g["dropped"]["n"] == int((~kept).sum())
    assert abs(g["delta"] - tr.net_r[~kept].sum() / n) < 1e-4
    assert g["per_cell_reported"]["transitional/long"]["cell"] == "on" and g["per_cell_reported"]["trending/short"]["cell"] == "off"
