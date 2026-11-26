"""capture_options_snapshot: OCC parse, slice to first N expiries, NaN-not-zero, idempotent day file, freshness. No network."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ops"))
import capture_options_snapshot as c  # noqa: E402

TODAY = date(2026, 11, 2)


def _snap(iv=0.2, bid=1.0):
    return {"latestQuote": {"bp": bid, "ap": bid + 0.1, "bs": 1, "as": 2, "t": "2026-11-02T20:59:00Z"},
            "latestTrade": {"p": 1.05, "t": "2026-11-02T20:58:00Z"}, "impliedVolatility": iv,
            "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.1, "vega": 0.2, "rho": 0.01} if iv else {}}


def getter(path, params):
    if "trades/latest" in path:
        return {"trade": {"p": 500.0}}
    snaps = {}
    for exp in ("261102", "261104", "261106", "261113"):  # 4 expiries -> only 3 kept
        snaps[f"SPY{exp}C00500000"] = _snap()
        snaps[f"SPY{exp}P00500000"] = _snap(iv=None)  # illiquid: no IV/greeks
    snaps["SPYW261102C00500000"] = _snap()  # different root: dropped
    return {"snapshots": snaps}


def test_parse_occ():
    p = c.parse_occ("SPY261102C00500000")
    assert p == {"root": "SPY", "expiry": date(2026, 11, 2), "cp": "C", "strike": 500.0}
    assert c.parse_occ("garbage") is None


def test_capture_slice_and_nan(tmp_path):
    rec = c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")
    assert rec["rows"] == 6 and rec["expiries"] == 3
    df = __import__("pandas").read_parquet(tmp_path / "SPY" / "2026-11-02.parquet")
    assert df["iv"].isna().sum() == 3 and (df["iv"].dropna() > 0).all()  # absent stays NaN, never 0
    c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")  # idempotent
    assert len(list((tmp_path / "SPY").glob("*.parquet"))) == 1


def test_verify_freshness(tmp_path):
    c.capture(getter, tmp_path, "SPY", TODAY, 3, 0.06, "indicative")
    assert c.verify(tmp_path, ["SPY"], 4.0, datetime(2026, 11, 4, tzinfo=timezone.utc)) == 0
    assert c.verify(tmp_path, ["SPY"], 4.0, datetime(2026, 11, 20, tzinfo=timezone.utc)) == 1
    assert c.verify(tmp_path, ["QQQ"], 4.0, datetime(2026, 11, 4, tzinfo=timezone.utc)) == 1


def test_cboe_source_zero_is_absent(tmp_path):
    j = {"timestamp": "2026-11-02 15:59:00", "data": {"current_price": 500.0, "options": [
        {"option": "B1SPY261102C00500000", "bid": 1.0, "ask": 1.1, "iv": 0.0, "open_interest": 7.0, "volume": 3.0, "delta": 0.5,
         "last_trade_price": 0.0, "last_trade_time": None},
        {"option": "SPY261104P00500000", "bid": 2.0, "ask": 2.1, "iv": 0.21, "open_interest": 9.0, "volume": 1.0, "delta": -0.5},
        {"option": "SPY261104C00900000", "bid": 0.0, "ask": 0.0, "iv": 0.0}]}}  # far OTM: dropped by moneyness
    rec = c.capture(lambda path, params: j, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", source="cboe")
    assert rec["rows"] == 2 and rec["feed"] == "cboe_delayed"
    df = __import__("pandas").read_parquet(tmp_path / "SPY" / "2026-11-02.parquet")
    assert df["iv"].isna().sum() == 1 and df["open_interest"].tolist() == [7.0, 9.0]


# ── option A probe (CBOE-OPTIONS-SOURCE-BLOCKED): the shapes open interest and volume must come from are MEASURED, never assumed ──
def _probe_get(path, params):
    if "trades/latest" in path:
        return {"trade": {"p": 500.0}}
    if "snapshots" in path:
        s = _snap()
        s["dailyBar"] = {"o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1, "v": 321, "n": 7, "vw": 1.05, "t": "2026-11-02T05:00:00Z"}
        return {"snapshots": {"SPY261102C00500000": s, "SPY261102P00500000": _snap(iv=None)}}
    if "bars" in path:
        return {"bars": {params["symbols"]: [{"t": "2026-11-02T05:00:00Z", "v": 321, "c": 1.1}]}}
    raise AssertionError(path)


def _probe_tget(path, params):
    assert path == "/v2/options/contracts" and params["underlying_symbols"] == "SPY"      # a listing GET, nothing else
    return {"option_contracts": [{"symbol": "SPY261102C00500000", "open_interest": "1234", "open_interest_date": "2026-11-01"},
                                 {"symbol": "SPY261102P00500000", "open_interest": None, "open_interest_date": None}],
            "next_page_token": None}


def test_probe_shapes_reports_where_volume_and_open_interest_live():
    rows = {r["shape"]: r for r in c.probe_shapes(_probe_get, _probe_tget, TODAY)}
    assert rows["snapshot"]["with_dailyBar"] == 1 and rows["snapshot"]["dailyBar"]["v"] == 321
    assert rows["contracts"]["n_page"] == 2 and rows["contracts"]["with_open_interest"] == 1
    assert rows["contracts"]["oi_dates"] == ["2026-11-01"] and "open_interest" in rows["contracts"]["keys"]
    assert rows["bars"]["newest"]["v"] == 321


def test_probe_shapes_never_raises_a_refused_call_is_a_finding():
    def boom(path, params):
        raise RuntimeError("HTTP 403 " + path)
    rows = {r["shape"]: r for r in c.probe_shapes(lambda p, q: {"trade": {"p": 500.0}} if "trades" in p else boom(p, q), boom, TODAY)}
    assert rows["snapshot"]["status"] == "error" and rows["contracts"]["status"] == "error" and "403" in rows["contracts"]["error"]
    assert "bars" not in rows                                                         # no symbol to ask about


# ── option A: open interest (Trading-API contracts listing) + volume (snapshot dailyBar) filled under the ALPACA label ───────────
def _snap_v(iv=0.2, v=321):
    s = _snap(iv=iv)
    s["dailyBar"] = {"o": 1.0, "c": 1.1, "v": v, "t": "2026-11-02T05:00:00Z"}
    return s


def getter_v(path, params):
    if "trades/latest" in path:
        return {"trade": {"p": 500.0}}
    snaps = {}
    for exp in ("261102", "261104", "261106"):
        snaps[f"SPY{exp}C00500000"] = _snap_v(v=100)
        snaps[f"SPY{exp}P00500000"] = _snap()                 # no dailyBar: volume stays None, never 0
    return {"snapshots": snaps}


def _contracts_pages():
    return {None: {"option_contracts": [
                {"symbol": "SPY261102C00500000", "open_interest": "25", "open_interest_date": "2026-10-30"},
                {"symbol": "SPY261102P00500000", "open_interest": None, "open_interest_date": None}], "next_page_token": "p2"},
            "p2": {"option_contracts": [
                {"symbol": "SPY261104C00500000", "open_interest": "0", "open_interest_date": "2026-10-30"}], "next_page_token": None}}


def tget_ok(path, params):
    assert path == "/v2/options/contracts"                         # a listing GET only
    return _contracts_pages()[params.get("page_token")]


def test_fetch_open_interest_paginates_keeps_the_date_and_leaves_unknown_absent():
    r = c.fetch_open_interest(tget_ok, "SPY", 500.0, TODAY, 0.06)
    assert r["pages"] == 2 and r["contracts"] == 3 and r["complete"] is True
    assert r["oi"] == {"SPY261102C00500000": (25, "2026-10-30"), "SPY261104C00500000": (0, "2026-10-30")}   # a real 0 is kept
    assert "SPY261102P00500000" not in r["oi"]                      # null open interest is UNKNOWN, not 0
    cut = c.fetch_open_interest(tget_ok, "SPY", 500.0, TODAY, 0.06, max_pages=1)
    assert cut["complete"] is False                                  # a page cap is published as incomplete


def test_capture_fills_volume_and_open_interest_with_their_dates_and_never_zero_for_unknown(tmp_path):
    rec = c.capture(getter_v, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", "alpaca", tget_ok)
    assert rec["oi_read_state"] == "ok" and rec["oi_dates"] == ["2026-10-30"]
    df = c.pd.read_parquet(tmp_path / "SPY" / f"{TODAY.isoformat()}.parquet")
    call = df[(df["cp"] == "C") & (df["expiry"] == "2026-11-02")].iloc[0]
    assert call["open_interest"] == 25 and call["open_interest_date"] == "2026-10-30" and call["volume"] == 100 and call["volume_date"] == "2026-11-02"
    put = df[(df["cp"] == "P") & (df["expiry"] == "2026-11-02")].iloc[0]
    assert c.pd.isna(put["open_interest"]) and c.pd.isna(put["volume"])                    # unknown, not 0
    assert rec["volume_coverage"] == round(3 / 6, 3) and rec["oi_coverage"] == round(2 / 6, 3)
    assert "feed" in df.columns and set(df["feed"]) == {"indicative"}                      # still the alpaca label, never cboe


def test_a_failed_open_interest_read_is_published_as_could_not_look_and_the_quotes_still_land(tmp_path):
    def boom(path, params):
        raise RuntimeError("HTTP 500 /v2/options/contracts")
    rec = c.capture(getter_v, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", "alpaca", boom)
    assert rec["oi_read_state"] == "could_not_look" and "500" in rec["oi_error"] and "oi_coverage" not in rec
    df = c.pd.read_parquet(tmp_path / "SPY" / f"{TODAY.isoformat()}.parquet")
    assert len(df) == 6 and df["open_interest"].isna().all()                                # absent, never a fabricated 0
    assert c.capture(getter_v, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", "alpaca", None)["oi_read_state"] == "not_requested"


def test_main_turns_a_could_not_look_open_interest_into_a_failure_line_and_a_red_exit(tmp_path, monkeypatch, capsys):
    from datetime import timedelta
    exp = (datetime.now(timezone.utc).date() + timedelta(days=2)).strftime("%y%m%d")      # main() uses the real clock

    def getter_now(path, params):
        if "trades/latest" in path:
            return {"trade": {"p": 500.0}}
        return {"snapshots": {f"SPY{exp}C00500000": _snap_v(), f"SPY{exp}P00500000": _snap()}}

    def boom(path, params):
        raise RuntimeError("HTTP 500 /v2/options/contracts")
    monkeypatch.setattr(c, "make_getter", lambda base=None: boom if base else getter_now)
    rc = c.main(["--mode", "capture", "--source", "alpaca", "--underlyings", "SPY", "--out", str(tmp_path)])
    assert rc == 1 and "could_not_look" in capsys.readouterr().err
    assert (tmp_path / "alpaca" / "SPY" / f"{c.datetime.now(c.timezone.utc).date().isoformat()}.parquet").exists()   # the quotes still landed
    monkeypatch.setattr(c, "make_getter", lambda base=None: tget_ok if base else getter_now)
    assert c.main(["--mode", "capture", "--source", "alpaca", "--underlyings", "SPY", "--out", str(tmp_path)]) == 0


def test_the_cboe_path_is_untouched_by_option_a(tmp_path):
    j = {"timestamp": "2026-11-02 21:00:00", "data": {"current_price": 500.0, "options": [
        {"option": "SPY261102C00500000", "bid": 1.0, "ask": 1.1, "iv": 0.2, "open_interest": 7, "volume": 3}]}}
    rec = c.capture(lambda p, q: j, tmp_path, "SPY", TODAY, 3, 0.06, "indicative", "cboe")
    assert "oi_read_state" not in rec and rec["feed"] == "cboe_delayed"


def _wf_steps():
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/options-snapshot-capture.yml").read_text())
    return wf["jobs"]["options-snapshot"]["steps"]


def test_the_workflow_no_longer_fetches_or_verifies_cboe_and_records_it_as_blocked_without_overwriting():
    import json as _json
    import subprocess
    steps = _wf_steps()
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "--source cboe" not in runs                                           # no fetch, no verify of the blocked source
    assert "for src in alpaca; do" in runs and "source=cboe: BLOCKED" in runs
    prov = next(s for s in steps if s.get("id") == "fetch_cboe")
    assert prov.get("if") == "steps.mode.outputs.mode == 'capture'" and not prov.get("continue-on-error")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        assert subprocess.run(["bash", "-c", prov["run"]], cwd=td, capture_output=True).returncode == 0
        f = Path(td) / "store/cboe/PROVENANCE.json"
        j = _json.loads(f.read_text())
        assert j["status"] == "blocked" and j["last_good_capture"] == "2026-11-19" and "never filled" in j["backfill"]
        f.write_text('{"kept": 1}\n')
        assert subprocess.run(["bash", "-c", prov["run"]], cwd=td, capture_output=True).returncode == 0
        assert _json.loads(f.read_text()) == {"kept": 1}                          # written once, never overwritten


def test_the_red_flag_condition_is_unchanged_so_the_alarm_clears_by_itself_once_alpaca_is_green():
    flag = next(s for s in _wf_steps() if str(s.get("name", "")).startswith("Red flag"))
    assert flag["if"] == ("always() && (steps.fetch.outcome == 'failure' || steps.fetch_cboe.outcome == 'failure' "
                          "|| steps.verify.outcome == 'failure')")
