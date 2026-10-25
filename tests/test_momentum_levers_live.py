"""MOMENTUM-LEVERS-LIVE -- the live producers for the harness momentum levers.

Contract (mirrors tests/test_trail_decay_lever.py / test_stale_stop_lever.py):
  * Declared ADX trail => on a bar where the shared `momentum_trail_fired` rule
    holds, the monitor's trail ratchets with the TIGHTENED mult (a higher stop
    for a long than the base trail would give); not fired => identical to base.
  * Declared momentum-stale => a real close on an old trade whose ADX has
    fallen below its entry reading and under the bound; young / strong-ADX
    trades are untouched; undeclared => None and the monitor is byte-identical.
  * Half-declared keys read as OFF (the harness's armed() predicates).
  * The live ADX equals the harness ADX after warm-up (one rule, one series).
  * No prop leg declares the close verb (the prop paths cannot execute it).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.runtime import momentum_levers as ml
from src.units.strategies import htf_pullback_trend_2h as pb
from src.units.strategies import trend_donchian as td

REPO = Path(__file__).resolve().parents[1]


def _candles(n: int = 120, tf_minutes: int = 60, fade_from: int | None = None,
             seed: int = 7) -> pd.DataFrame:
    """A trending tape (strong ADX) that, from ``fade_from`` on, goes flat and
    choppy so ADX decays; timestamps are hourly and in the past (closed bars)."""
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows, price = [], 100.0
    for i in range(n):
        if fade_from is None or i < fade_from:
            price += 1.0 + rng.normal(0, 0.05)          # steady trend: ADX climbs
            hi, lo = price + 0.3, price - 0.3
        else:
            # Balanced zig-zag chop: alternate up and down bars of equal size,
            # so +DM and -DM run level and DX -> 0; ADX then decays at 1/period
            # per bar. (A merely flat tape does NOT fade ADX: DX is scale-free,
            # so decaying DMs keep their trend-time ratio.)
            price += 1.5 if i % 2 == 0 else -1.5
            hi, lo = price + 0.3, price - 0.3
        rows.append({"timestamp": (start + timedelta(minutes=tf_minutes * i)).isoformat(),
                     "open": price, "high": hi, "low": lo, "close": price, "volume": 1.0})
    return pd.DataFrame(rows)


def _pkg(df: pd.DataFrame, unit: str = "donchian", entry_bar: int = 40, **declared):
    meta = {"atr": 1.0, "atr_period": 14, "trail_mult": 6.0, "risk_per_unit": 2.0,
            "entry_time": df["timestamp"].iloc[entry_bar],
            "timeframe": "1h" if unit == "donchian" else "2h"}
    meta.update(declared)
    entry = float(df["close"].iloc[entry_bar])
    return {"symbol": "ETHUSDT", "direction": "long", "entry": entry,
            "sl": entry - 2.0, "tp": entry * 3, "meta": meta,
            "order_package_id": f"pkg-mom-{unit}-{sorted(declared)}"}


@pytest.fixture(autouse=True)
def _isolated_soak(tmp_path, monkeypatch):
    from src.runtime import exit_lever_soak
    monkeypatch.setattr(exit_lever_soak, "soak_log_path", lambda: tmp_path / "exit_lever_soak.jsonl")
    exit_lever_soak._ANNOTATED.clear()
    yield tmp_path


# ── ADX parity: one rule, one series ──────────────────────────────────────────

def _harness():
    name = "backtest_trend_for_parity"
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "backtest_trend.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_live_adx_matches_the_harness_adx():
    df = _candles(n=300, fade_from=200)
    live = ml.live_adx(df, 14)
    harness = _harness()._adx(df, 14)
    both = pd.concat([live, harness], axis=1).dropna()
    assert len(both) > 200
    assert float((both.iloc[:, 0] - both.iloc[:, 1]).abs().max()) < 1e-9


# ── the ADX-conditioned trail ─────────────────────────────────────────────────

@pytest.mark.parametrize("mod,unit", [(td, "donchian"), (pb, "pullback")])
def test_declared_adx_trail_tightens_when_momentum_fades(mod, unit):
    df = _candles(n=120, fade_from=70)
    adx_now = float(ml.live_adx(df, 14).iloc[-1])
    assert adx_now < 20.0, adx_now                       # the tape really did fade
    base = mod.monitor({}, df, _pkg(df, unit))
    tight = mod.monitor({}, df, _pkg(df, unit, trail_adx_below=20.0, trail_adx_tight_mult=2.5))
    assert base and "sl" in base and tight and "sl" in tight
    # peak high is the same for both; base 6.0 ATR vs tight 2.5 ATR with atr=1.0
    assert abs((tight["sl"] - base["sl"]) - 3.5) < 1e-6


@pytest.mark.parametrize("mod,unit", [(td, "donchian"), (pb, "pullback")])
def test_declared_adx_trail_is_inert_while_momentum_holds(mod, unit):
    df = _candles(n=120)                                 # no fade: ADX stays high
    assert float(ml.live_adx(df, 14).iloc[-1]) > 20.0
    base = mod.monitor({}, df, _pkg(df, unit))
    tight = mod.monitor({}, df, _pkg(df, unit, trail_adx_below=20.0, trail_adx_tight_mult=2.5))
    assert tight == base


def test_half_declared_adx_trail_reads_off():
    df = _candles(n=120, fade_from=70)
    base = ml.resolve_momentum_trail_mult({}, {}, df, 6.0, "long")
    only_tight = ml.resolve_momentum_trail_mult({"trail_adx_tight_mult": 2.5}, {}, df, 6.0, "long")
    only_cond = ml.resolve_momentum_trail_mult({"trail_adx_below": 20.0}, {}, df, 6.0, "long")
    assert base == only_tight == only_cond == 6.0


def test_adx_trail_reads_the_live_cfg_for_an_already_open_package():
    df = _candles(n=120, fade_from=70)
    eff = ml.resolve_momentum_trail_mult({}, {"trail_adx_below": 20.0, "trail_adx_tight_mult": 2.5},
                                         df, 6.0, "long")
    assert eff == 2.5


def test_adx_trail_fire_writes_one_soak_row(_isolated_soak):
    df = _candles(n=120, fade_from=70)
    td.monitor({}, df, _pkg(df, "donchian", trail_adx_below=20.0, trail_adx_tight_mult=2.5))
    rows = [json.loads(x) for x in (_isolated_soak / "exit_lever_soak.jsonl").read_text().splitlines()]
    mine = [r for r in rows if r.get("lever") == "momentum_trail"]
    assert len(mine) == 1 and mine[0]["state"]["applied"] is True


# ── the momentum-keyed time stop ──────────────────────────────────────────────

@pytest.mark.parametrize("mod,unit", [(td, "donchian"), (pb, "pullback")])
def test_declared_momentum_stale_closes_an_old_faded_trade(mod, unit):
    df = _candles(n=120, fade_from=70)
    pkg = _pkg(df, unit, entry_bar=60, momentum_stale_bars=8, momentum_stale_adx_below=20.0)
    v = mod.monitor({}, df, pkg)
    assert v == {"action": "close", "reason": "momentum_stale",
                 "exit_price": float(df["close"].iloc[-1])}


@pytest.mark.parametrize("mod,unit", [(td, "donchian"), (pb, "pullback")])
def test_momentum_stale_skips_a_young_trade_and_a_strong_trend(mod, unit):
    df = _candles(n=120, fade_from=70)
    young = _pkg(df, unit, entry_bar=115, momentum_stale_bars=8, momentum_stale_adx_below=20.0)
    v = mod.monitor({}, df, young)
    assert not (isinstance(v, dict) and v.get("reason") == "momentum_stale")
    strong = _candles(n=120)
    pkg = _pkg(strong, unit, entry_bar=60, momentum_stale_bars=8, momentum_stale_adx_below=20.0)
    v = mod.monitor({}, strong, pkg)
    assert not (isinstance(v, dict) and v.get("reason") == "momentum_stale")


@pytest.mark.parametrize("mod,unit", [(td, "donchian"), (pb, "pullback")])
def test_undeclared_momentum_stale_is_byte_identical(mod, unit):
    df = _candles(n=120, fade_from=70)
    assert ml.momentum_stale_verdict({}, {}, _pkg(df, unit, entry_bar=60), df,
                                     float(df["close"].iloc[-1]), "long") is None
    v = mod.monitor({}, df, _pkg(df, unit, entry_bar=60))
    assert not (isinstance(v, dict) and v.get("reason") == "momentum_stale")


def test_momentum_stale_is_fail_safe_without_entry_time_or_enough_bars():
    df = _candles(n=120, fade_from=70)
    pkg = _pkg(df, "donchian", entry_bar=60, momentum_stale_bars=8, momentum_stale_adx_below=20.0)
    pkg["meta"].pop("entry_time")
    assert ml.momentum_stale_verdict(pkg["meta"], {}, pkg, df, 1.0, "long") is None
    short = df.iloc[:20]
    pkg2 = _pkg(short, "donchian", entry_bar=5, momentum_stale_bars=8, momentum_stale_adx_below=20.0)
    assert ml.momentum_stale_verdict(pkg2["meta"], {}, pkg2, short, 1.0, "long") is None


# ── roster hygiene: the close verb never on a prop path ───────────────────────

def test_no_prop_leg_declares_the_momentum_close_verb():
    cfg = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]
    accts = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
    prop_legs = {leg for a in accts.values() if isinstance(a, dict)
                 and (a.get("account_class") or a.get("class")) == "prop"
                 for leg in (a.get("strategies") or [])}
    offenders = [leg for leg in prop_legs if ml.momentum_stale_declared(cfg.get(leg) or {})]
    assert offenders == [], f"a prop leg declares momentum_stale, which its path cannot execute: {offenders}"


def test_meta_threading_keys_cover_both_levers():
    for mod in (td, pb):
        src = Path(mod.__file__).read_text()
        for key in ("trail_adx_below", "trail_adx_tight_mult", "momentum_stale_bars",
                    "momentum_stale_adx_below"):
            assert f'"{key}"' in src, (mod.__name__, key)
