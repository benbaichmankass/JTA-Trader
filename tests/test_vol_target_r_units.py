"""PI-20261120-H58PIBEE-0003: vol targeting on an R-unit leg book.

With --target-vol 0.10 the annualized mode compares a 10%/yr budget against a book whose
daily returns are in R (realised vol of tens of R/yr), so the multiplier pins at cap_lo
(MEASURED on RQ-20261120-8ef8-01/02: 44 of 45 periods). The trailing_median mode is unit-free.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import scripts.backtest_vol_target as vt  # noqa: E402


def _r_book(n=600, seed=3):
    rnd = random.Random(seed)
    d0 = date(2023, 1, 2)
    out = []
    for i in range(n):
        sd = 1.0 if (i // 120) % 2 == 0 else 2.5   # vol regimes, in R
        out.append((d0 + timedelta(days=i), rnd.gauss(0.05, sd), 1))
    return out


def _cap_share(mult_out):
    return mult_out["multiplier"]["pct_periods_at_cap"]


def test_annualized_target_pins_an_r_book_at_the_floor():
    out = vt.run_vol_target(_r_book(), target_vol=0.10, short=20, long=60, blend=0.5,
                            cap_lo=0.5, cap_hi=1.5, retarget="monthly", costs=vt.resolve_overlay_costs("ETHUSDT"))
    assert _cap_share(out) > 90.0
    assert out["params"]["target_mode"] == "annualized"


def test_trailing_median_moves_around_one_and_off_the_caps():
    out = vt.run_vol_target(_r_book(), target_vol=0.10, short=20, long=60, blend=0.5,
                            cap_lo=0.5, cap_hi=1.5, retarget="monthly", costs=vt.resolve_overlay_costs("ETHUSDT"),
                            target_mode="trailing_median")
    m = out["multiplier"]
    assert _cap_share(out) < 50.0
    assert m["min"] < 1.0 < m["max"]
    assert out["params"]["target_mode"] == "trailing_median"


def test_trailing_median_is_causal():
    book = _r_book()
    kw = dict(target_vol=0.10, short=20, long=60, blend=0.5, cap_lo=0.5, cap_hi=1.5, retarget="monthly",
              target_mode="trailing_median")
    base, _ = vt.compute_multipliers(book, **kw)
    cut = 400
    perturbed = book[:cut] + [(d, r * 10.0 + 5.0, n) for (d, r, n) in book[cut:]]
    pert, _ = vt.compute_multipliers(perturbed, **kw)
    assert base[:cut] == pert[:cut]


def test_unknown_target_mode_is_refused():
    with pytest.raises(ValueError):
        vt.compute_multipliers(_r_book(50), target_vol=0.1, short=5, long=10, blend=0.5,
                               cap_lo=0.5, cap_hi=1.5, retarget="weekly", target_mode="bogus")
