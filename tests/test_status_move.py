"""scripts/ops/status_move.py — open positions on a book move (row STATUS-MOVE-OPEN-POSITIONS)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import status_move as sm


def _p(i, acct, leg, sym="ADAUSDT", side="sell", pkg=None):
    return {"id": i, "account": acct, "pattern": leg, "symbol": sym, "side": side, "order_package_id": pkg}


def _v(res, i):
    return next(p for p in res["positions"] if p["id"] == str(i))


PROMOTED = {"bybit_1": ["other"], "bybit_2": ["ada"], "bybit_portfolio": ["ada"]}


def test_on_book_is_clean():
    res = sm.classify([_p(1, "bybit_1", "ada")], {"bybit_1": ["ada"]})
    assert _v(res, 1)["verdict"] == sm.ON_BOOK and not res["version_breaches"]


def test_promoted_leg_paper_copy_with_siblings_is_the_third_version():
    """The ADA 6734 case: promoted, paper copy left open beside the money + mirror copies."""
    res = sm.classify([_p(1, "bybit_1", "ada"), _p(2, "bybit_2", "ada"), _p(3, "bybit_portfolio", "ada")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.CLOSE_DUPLICATE
    assert _v(res, 1)["siblings"] == ["2", "3"] and _v(res, 1)["match"] == sm.ESTIMATED
    assert {_v(res, 2)["verdict"], _v(res, 3)["verdict"]} == {sm.ON_BOOK}
    assert len(res["version_breaches"]) == 1 and res["version_breaches"][0]["copies"] == [
        "bybit_1", "bybit_2", "bybit_portfolio"]


def test_netted_neighbour_needs_a_per_row_close():
    res = sm.classify([_p(1, "bybit_1", "ada"), _p(2, "bybit_2", "ada"), _p(4, "bybit_1", "other")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.CLOSE_NETTED and _v(res, 1)["neighbours"] == ["4"]


def test_promoted_sole_copy_runs_out():
    res = sm.classify([_p(1, "bybit_1", "ada")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.RUN_OUT


def test_package_id_match_is_exact():
    res = sm.classify([_p(1, "bybit_1", "ada", pkg="A"), _p(2, "bybit_2", "ada", pkg="B")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.RUN_OUT and _v(res, 1)["match"] == sm.MEASURED
    res = sm.classify([_p(1, "bybit_1", "ada", pkg="A"), _p(2, "bybit_2", "ada", pkg="A")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.CLOSE_DUPLICATE


def test_demoted_money_and_mirror_run_out():
    ros = {"bybit_1": ["ada"], "bybit_2": [], "bybit_portfolio": []}
    res = sm.classify([_p(2, "bybit_2", "ada"), _p(3, "bybit_portfolio", "ada")], ros)
    assert {_v(res, 2)["verdict"], _v(res, 3)["verdict"]} == {sm.RUN_OUT}


def test_retired_runs_out_and_prop_not_judged():
    res = sm.classify([_p(1, "bybit_1", "ada"), _p(5, "breakout_2", "ada")], {"bybit_1": []}, retired=["ada"])
    assert _v(res, 1)["verdict"] == sm.RUN_OUT and _v(res, 5)["verdict"] == sm.NOT_JUDGED


def test_unexplained_and_population():
    res = sm.classify([_p(1, "alpaca_paper", "ada", sym="X")], {"bybit_1": ["ada"]})
    assert _v(res, 1)["verdict"] == sm.UNEXPLAINED and res["population"] == 1
    assert sum(res["counts"].values()) == 1


def test_journal_row_shape():
    row = {"id": 9, "account_id": "bybit_1", "strategy": "ada", "symbol": "S", "direction": "long"}
    assert _v(sm.classify([row], {"bybit_1": ["ada"]}), 9)["side"] == "buy"


def test_api_positions_row_package_id_is_read():
    """POSITIONS-API-ORDER-PACKAGE-ID: an /api/bot/positions row (orderPackageId) matches exactly, like a journal row."""
    def api(i, acct, pkg):
        return {"id": i, "account": acct, "pattern": "ada", "symbol": "ADAUSDT", "side": "sell", "orderPackageId": pkg}
    res = sm.classify([api(1, "bybit_1", "A"), api(2, "bybit_2", "A")], PROMOTED)
    assert _v(res, 1)["verdict"] == sm.CLOSE_DUPLICATE and _v(res, 1)["match"] == sm.MEASURED
