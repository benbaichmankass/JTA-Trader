"""Offline tests for scripts/research/wepe_g3_ledger.py (WEPE gate G3 on history)."""
import copy
import datetime as _dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "research"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "macro"))
import wepe_g3_ledger as g  # noqa: E402


def rel(kind, i, cons, act, prior=0.0):
    d = (_dt.date(2020, 1, 1) + _dt.timedelta(days=30 * i)).isoformat()
    return {"kind": kind, "date": d, "scheduled_at": f"{d}T12:30:00Z", "consensus": cons, "prior": prior,
            "actual": act, "consensus_basis": "t", "pit_basis": "t"}


def cpi_series(n=30):
    # surprises alternate 0, +0.1, 0, -0.1 ...
    return [rel("cpi_yoy", i, 2.0, 2.0 + [0, 0.1, 0, -0.1][i % 4]) for i in range(n)]


def test_asof_strictly_before_release_and_ledger_leakage_ok():
    rows = g.build_ledger(cpi_series())
    assert rows and g.leakage_check(rows)["ok"]
    for r in rows:
        assert r["question"]["forecast_cutoff"] < r["question"]["release_at"]


def test_no_forecast_without_min_history():
    rs = cpi_series(g.MIN_HISTORY)  # the last release has only MIN_HISTORY-1 earlier ones
    ids = {r["question"]["release_date"] for r in g.build_ledger(rs)}
    assert rs[-1]["date"] not in ids


def test_forecast_ignores_the_realized_value_and_later_releases():
    rs = cpi_series()
    target = rs[20]
    q = g.make_questions(target)[0]
    base = g.forecast_v0(q, target, rs)["p_yes"]
    mutated = copy.deepcopy(rs)
    mutated[20]["actual"] += 5.0                 # own realized value
    for h in mutated[21:]:
        h["actual"] += 3.0                       # the future
    assert g.forecast_v0(q, mutated[20], mutated)["p_yes"] == base
    assert g.base_rate(q, target, rs) == g.base_rate(q, mutated[20], mutated)


def test_resolution_and_fomc_contract():
    r = rel("cpi_yoy", 0, 2.0, 2.1)
    q1, q2 = g.make_questions(r)
    assert g.resolve(q1, r) == 1 and g.resolve(q2, r) == 0
    f = rel("fomc", 0, 0.25, 0.5, prior=0.25)
    (qf,) = g.make_questions(f)
    assert g.resolve(qf, f) == 1


def test_scoring_prefers_the_better_arm_and_is_deterministic():
    rows = [{"p_model": 0.9, "p_base": 0.5, "y": 1} for _ in range(10)] + \
           [{"p_model": 0.1, "p_base": 0.5, "y": 0} for _ in range(10)]
    s = g.score(rows, "p_model", "p_base")
    assert s["n"] == 20 and s["brier"]["ref_minus_arm"] > 0 and s["logloss"]["ref_minus_arm"] > 0
    assert s["brier"]["ci95"][0] > 0
    assert g.score(rows, "p_model", "p_base") == s
    assert g.score(rows, "p_model", "p_market")["n"] == 0


def test_probability_in_unit_interval():
    for r in g.build_ledger(cpi_series()):
        assert 0.0 <= r["p_model"] <= 1.0 and 0.0 < r["p_base"] < 1.0


# ── market leg (needs scripts/macro/pm_surprise.py from PM-SURPRISE-JOIN) ─────────────────────────────
def _row(mid, strike, ce, close, bid, ask, stype="greater", series="KXCPI"):
    return {"market_id": mid, "event_ticker": "KXCPI-26SEP", "strike_type": stype, "floor_strike": strike,
            "close_time": close, "candle_end_utc": ce, "yes_bid_close": bid, "yes_ask_close": ask}


def test_market_leg_uses_only_quotes_at_or_before_asof(tmp_path):
    pytest.importorskip("pm_surprise", reason="needs PM-SURPRISE-JOIN merged")
    r = rel("cpi_mom", 0, 0.2, 0.3)
    r["scheduled_at"] = "2026-09-11T12:30:00Z"
    r["date"] = "2026-09-11"
    q1 = g.make_questions(r)[0]            # actual >= 0.3  <=>  X > 0.2
    close = "2026-09-11T12:25:00Z"
    rows = [_row("KXCPI-26SEP-T0.2", 0.2, "2026-09-11T08:00:00Z", close, 0.38, 0.42),
            _row("KXCPI-26SEP-T0.2", 0.2, "2026-09-11T09:00:00Z", close, 0.48, 0.52),   # last <= as-of (09:30)
            _row("KXCPI-26SEP-T0.2", 0.2, "2026-09-11T11:00:00Z", close, 0.98, 1.0),    # after as-of: must not be read
            _row("KXCPI-26SEP-T0.1", 0.1, "2026-09-11T09:00:00Z", close, 0.70, 0.74)]
    d = tmp_path / "k"
    d.mkdir()
    (d / "KXCPI.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    book = g.build_kalshi(d)
    m = book.prob(q1, r)
    assert m and abs(m["p"] - 0.50) < 1e-9 and m["quote_candle_end_utc"] == "2026-09-11T09:00:00Z"
    q2 = g.make_questions(r)[1]            # needs strike 0.3: absent -> no match, reason recorded
    assert book.prob(q2, r) is None and book.miss


def test_public_ledger_omits_market_fields(tmp_path):
    out = tmp_path / "o"
    macro = tmp_path / "m"
    macro.mkdir()
    rows = []
    for i in range(20):
        r = rel("cpi_yoy", i, 2.0, 2.0)
        rows.append({"kind": "cpi_yoy", "status": "resolved", "event_name": "CPI", "scheduled_for": r["date"],
                     "scheduled_at": r["scheduled_at"], "expected": {"consensus": 2.0, "prior": 2.0},
                     "realized_outcome": {"actual": 2.0}})
    (macro / g.SNAP_FILES[0]).write_text("".join(json.dumps(x) + "\n" for x in rows))
    assert g.main(["--macro-dir", str(macro), "--out-dir", str(out)]) == 0
    first = json.loads((out / "ledger_public.jsonl").read_text().splitlines()[0])
    assert "p_market" not in first and "market_meta" not in first and first["market_matched"] is False
    assert json.loads((out / "scorecard.json").read_text())["leakage"]["ok"]


def test_nsa_index_level_rows_are_excluded(tmp_path):
    macro = tmp_path
    def mk(name, cons, act):
        return {"kind": "cpi_mom", "status": "resolved", "event_name": name,
                "scheduled_for": "2026-01-01", "scheduled_at": "2026-01-01T13:30:00Z",
                "expected": {"consensus": cons, "prior": 0.0}, "realized_outcome": {"actual": act}}

    (macro / g.SNAP_FILES[0]).write_text(json.dumps(mk("CPI (MoM)", 0.2, 0.3)) + "\n" +
                                         json.dumps(mk("CPI n.s.a (MoM)", 334.7, 333.9)) + "\n")
    (r,) = g.load_releases(macro)
    assert r["actual"] == 0.3
