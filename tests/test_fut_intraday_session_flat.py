"""FUT-INTRADAY-DUKA-LANE (2026-11-12): the session-flat overlay, the per-contract cost arm, the
naive-timestamp HTF merge in scripts/backtest_ict_scalp.py, and the extended stage0 grade in
scripts/research/exit_lever_ablation.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.backtest_ict_scalp as h

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import exit_lever_ablation as ela  # noqa: E402


def _frame(start_utc: str, periods: int, freq: str = "15min") -> pd.DataFrame:
    ts = pd.date_range(start_utc, periods=periods, freq=freq)  # naive, UTC by contract
    px = np.full(periods, 100.0)
    return pd.DataFrame({"timestamp": ts, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px})


class TestSessionFlatMarks:
    def test_15m_flat_bar_is_the_1630_close(self):
        # 2026-08-27 is EDT (UTC-4): bar opening 20:15 UTC = 16:15 ET closes 16:30 ET.
        df = _frame("2026-08-27 18:00", 24)
        flat, no_entry = h.session_flat_marks(df, "16:35")
        et_open = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
        flagged = [str(t.time()) for t, f in zip(et_open, flat) if f]
        assert flagged == ["16:15:00"]
        # no entry on the flat bar itself nor on bars closing in [16:35, 18:00) ET
        blocked = {str(t.time()) for t, b in zip(et_open, no_entry) if b}
        assert "16:15:00" in blocked and "16:30:00" in blocked and "17:30:00" in blocked
        assert "16:00:00" not in blocked and "18:00:00" not in blocked

    def test_5m_flat_bar_closes_at_1635(self):
        df = _frame("2026-08-27 20:00", 30, "5min")
        flat, _ = h.session_flat_marks(df, "16:35")
        et_open = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
        assert [str(t.time()) for t, f in zip(et_open, flat) if f] == ["16:30:00"]

    def test_gap_over_cutoff_flags_last_bar_before_gap(self):
        df = _frame("2026-08-27 18:00", 8)       # last bar opens 19:45 UTC = 15:45 ET, closes 16:00
        nxt = _frame("2026-08-27 23:00", 4)       # resumes 19:00 ET
        both = pd.concat([df, nxt], ignore_index=True)
        flat, _ = h.session_flat_marks(both, "16:35")
        assert flat[7] and flat.sum() == 1


class TestSimulateExitSessionFlat:
    def test_open_trade_is_flattened_at_the_flat_bar_close(self):
        df = _frame("2026-08-27 18:00", 24)
        flat, _ = h.session_flat_marks(df, "16:35")
        j = int(np.flatnonzero(flat)[0])
        res = h._simulate_exit(df, start_idx=1, direction="long", sl=50.0, tp=200.0, timeout_bars=50,
                               entry=100.0, flat_bar=flat)
        assert res["outcome"] == "session_flat" and res["exit_index"] == j
        assert res["exit_price"] == float(df["close"].iloc[j])

    def test_stop_on_the_flat_bar_still_wins(self):
        df = _frame("2026-08-27 18:00", 24)
        flat, _ = h.session_flat_marks(df, "16:35")
        j = int(np.flatnonzero(flat)[0])
        df.loc[j, "low"] = 40.0
        res = h._simulate_exit(df, start_idx=1, direction="long", sl=50.0, tp=200.0, timeout_bars=50,
                               entry=100.0, flat_bar=flat)
        assert res["outcome"] == "sl_hit" and res["exit_index"] == j

    def test_default_off_is_unchanged(self):
        df = _frame("2026-08-27 18:00", 24)
        res = h._simulate_exit(df, start_idx=1, direction="long", sl=50.0, tp=200.0, timeout_bars=50,
                               entry=100.0)
        assert res["outcome"] == "timeout"


class TestContractCost:
    CC = {"commission_usd_rt": 2.12, "point_value": 10.0, "tick_size": 0.10, "slip_ticks_per_fill": 1.0}

    def _t(self, outcome, meta=None):
        return h.Trade(entry_index=0, entry_time="2026-01-01", direction="long", entry=100.0, sl=98.0,
                       tp=103.0, risk=2.0, exit_index=3, exit_time="2026-01-01 01:00", exit_price=103.0,
                       outcome=outcome, r_multiple=1.5, meta=meta or {})

    def test_take_profit_pays_entry_slip_only(self):
        c = h.contract_cost_r(self._t("tp_hit"), self.CC)
        assert c["fee_r"] == pytest.approx(2.12 / 20.0)
        assert c["slippage_r"] == pytest.approx(0.1 / 2.0)
        assert c["funding_r"] == 0.0

    @pytest.mark.parametrize("outcome", ["sl_hit", "be_stop", "timeout", "session_flat"])
    def test_market_or_stop_exit_pays_two_fills(self, outcome):
        assert h.contract_cost_r(self._t(outcome), self.CC)["slippage_r"] == pytest.approx(0.2 / 2.0)

    def test_limit_entry_pays_no_entry_slip(self):
        assert h.contract_cost_r(self._t("tp_hit", {"limit_entry": True}), self.CC)["slippage_r"] == 0.0

    def test_cost_breakdown_routes_to_contract_mode_and_back(self):
        t = self._t("sl_hit")
        try:
            h.CONTRACT_COST = dict(self.CC)
            assert h._cost_breakdown(t)["total_cost_r"] == pytest.approx(0.106 + 0.1)
        finally:
            h.CONTRACT_COST = None
        assert h._cost_breakdown(t)["total_cost_r"] != pytest.approx(0.206)

    def test_cli_refuses_contract_cost_without_point_value(self, tmp_path):
        assert h.main(["x", "--data", "data/backtest_candles.csv", "--contract-cost-usd-rt", "2"]) == 2
        h.CONTRACT_COST = None


def test_naive_timestamps_merge_with_the_utc_htf_series():
    """The dukascopy lane writes naive UTC timestamps; the HTF merge used to raise on them."""
    rng = np.random.default_rng(0)
    n = 400
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    df = pd.DataFrame({"timestamp": pd.date_range("2026-01-05", periods=n, freq="15min"),
                       "open": close, "high": close + 0.4, "low": close - 0.4, "close": close})
    out = h.run_backtest(df, cfg_overrides={}, timeframe="15m", symbol="MGC", warmup_bars=50,
                         timeout_bars=24, cooldown_bars=3, session_flat_et="16:35")
    assert out["session_flat"]["flat_et"] == "16:35"


class TestStage0Split:
    B = pd.Timestamp("2025-01-01", tz="UTC")
    HI = pd.Timestamp("2026-10-31", tz="UTC")
    EDGES = [pd.Timestamp(f"{y}-01-01", tz="UTC") for y in range(2019, 2026)]

    def _tr(self, day, r):
        e = pd.Timestamp(day, tz="UTC")
        return {"entry_time": str(e), "exit_time": str(e + pd.Timedelta(hours=2)), "net_r": r}

    def _book(self, disc_r, hold_r, hold_n=20):
        disc = [self._tr(f"{y}-0{m}-10", disc_r) for y in range(2019, 2025) for m in range(1, 7)]
        hold = [self._tr(f"2025-{(i % 9) + 1:02d}-15", hold_r) for i in range(hold_n)]
        return disc + hold

    def _g(self, book, ci_z=2.394, hmin=15):
        return ela.grade_stage0_split(book, boundary=self.B, hi=self.HI, edges=self.EDGES, fold_majority=4,
                                      n_floor=30, ci_z=ci_z, holdout_min_n=hmin, control=None)

    def test_pass_needs_discovery_and_holdout(self):
        book = self._book(0.5, 0.2)
        book[0]["net_r"] = 0.4            # non-zero sd so the CI is defined
        assert self._g(book)["verdict"] == "pass"

    def test_holdout_negative_is_not_replicated(self):
        book = self._book(0.5, -0.1)
        book[0]["net_r"] = 0.4
        assert self._g(book)["label"] == "not_replicated"

    def test_short_holdout_after_discovery_pass_is_indeterminate(self):
        book = self._book(0.5, 0.2, hold_n=5)
        book[0]["net_r"] = 0.4
        assert self._g(book)["label"] == "holdout_underpowered"

    def test_ci_clause_can_fail_a_positive_mean(self):
        book = self._book(0.05, 0.2)
        for i in range(0, 36, 2):
            book[i]["net_r"] = -2.0 if i % 4 == 0 else 2.2
        g = self._g(book)
        assert g["verdict"] == "fail" and "CI" in g["why"]

    def test_underpowered_discovery(self):
        book = self._book(0.5, 0.2)[30:]
        assert self._g(book)["label"] == "underpowered"

    def test_yearly_edges(self):
        e = ela.yearly_edges("2019-01-01", "2025-01-01")
        assert len(e) == 7 and str(e[0].date()) == "2019-01-01"
        with pytest.raises(ValueError):
            ela.yearly_edges("2019-01-01", "2025-03-01")


def test_dukascopy_interval_map_covers_intraday_and_drops_unservable_2h():
    assert ela._DUKA_INTERVAL["15m"] == "15" and ela._DUKA_INTERVAL["5m"] == "5"
    assert "2h" not in ela._DUKA_INTERVAL


class TestDefaultStage0Unchanged:
    """Operator rule (no new gates): the extended clauses are OPT-IN. Without --stage0-holdout-start the
    stage0 grade is the pre-existing grade_stage0, and its verdicts on planted arms are pinned here."""

    @staticmethod
    def _arm(n, net, folds):
        return {"n": n, "net_r": net, "max_drawdown_r": 1.0, "folds": [{"net_r": f} for f in folds]}

    def setup_method(self):
        self._nf = ela.N_FOLDS
        ela.N_FOLDS = 4

    def teardown_method(self):
        ela.N_FOLDS = self._nf

    @pytest.mark.parametrize("arm,verdict,label", [
        ((50, 3.0, [1, 1, 1, -1]), "pass", "stage0_edge"),
        ((50, 3.0, [1, 1, -1, -1]), "fail", "stage0_no_edge"),
        ((50, -1.0, [1, 1, 1, -4]), "fail", "stage0_no_edge"),
        ((10, 3.0, [1, 1, 1, 1]), "indeterminate", "underpowered"),
    ])
    def test_pinned_default_verdicts(self, arm, verdict, label):
        g = ela.grade_stage0({"B": self._arm(*arm)}, baseline="B", fold_majority=3, n_floor=30, control=None)
        assert (g["verdict"], g["label"]) == (verdict, label)
        assert "discovery_ci_lower_r_per_trade" not in g and "holdout" not in g

    def test_new_flags_default_off(self):
        src = Path(ela.__file__).read_text(encoding="utf-8")
        assert 'split = a.grade == "stage0" and a.stage0_holdout_start is not None' in src

    @pytest.mark.parametrize("flag", [["--stage0-ci-z", "2"], ["--stage0-yearly-folds"]])
    def test_extended_clause_without_holdout_start_is_refused(self, flag, tmp_path):
        rc = ela.main(["--leg", "ict_scalp_mgc_15m", "--arm", "W=", "--data-csv", "data/backtest_candles.csv",
                       "--grade", "stage0", "--baseline", "W", "--delta-r", "0", "--fold-majority", "2",
                       "--n-floor", "1", "--out", str(tmp_path), *flag])
        assert rc == 2
