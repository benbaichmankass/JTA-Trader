"""Tests for scripts/ops/live_replay_parity.py.

The planted-defect cases are the mandated positive control: a fabricated live
record that is missing a replay signal MUST be flagged. Each planted test is
paired with an un-planted twin over the SAME candles that must come back clean,
so a check that flags everything cannot pass either.
"""
from __future__ import annotations

import copy
import math

import pytest

pd = pytest.importorskip("pandas")

import scripts.ops.live_replay_parity as P  # noqa: E402

TF_S = 14400
START = 1_790_000_000 // TF_S * TF_S  # a 4h boundary
N_BARS = 260
BREAK_BAR = N_BARS - 3  # the bar that breaks out
SINCE = START + (N_BARS - 12) * TF_S
UNTIL = START + (N_BARS - 1) * TF_S


def _bars():
    """Flat-ish channel 100..110, then a decisive up-breakout on BREAK_BAR."""
    rows = []
    for i in range(N_BARS):
        mid = 105 + 4 * math.sin(i / 3.0)
        o = mid - 0.5
        c = mid + 0.5
        h, lo = max(o, c) + 0.8, min(o, c) - 0.8
        if i >= BREAK_BAR:
            o, c, h, lo = 110.0, 140.0, 141.0, 109.5
        rows.append({"time": START + i * TF_S, "open": o, "high": h, "low": lo,
                     "close": c, "volume": 10.0})
    return rows


def _fine(tf_rows):
    """16 x 15m candles per 4h bar, for the last 20 bars, path open→close."""
    out = []
    for b in tf_rows[-20:]:
        for k in range(16):
            frac0, frac1 = k / 16, (k + 1) / 16
            o = b["open"] + (b["close"] - b["open"]) * frac0
            c = b["open"] + (b["close"] - b["open"]) * frac1
            out.append({"time": b["time"] + k * 900, "open": o, "close": c,
                        "high": max(o, c) + 0.01, "low": min(o, c) - 0.01, "volume": 1.0})
    return out


def _leg(cfg_over=None):
    import yaml
    cfg = yaml.safe_load(open(P.REPO_ROOT / "config/strategies.yaml"))
    cfg = (cfg.get("strategies", cfg))["trend_donchian_eth_4h"]
    cfg = {**cfg, **(cfg_over or {}), "decision_bar": "forming"}
    return P.Leg(name="trend_donchian_eth_4h", symbol="ETHUSDT", timeframe="4h",
                 unit="trend_donchian", decision_bar="forming", execution="live",
                 accounts=["bybit_2"], real_money=True,
                 features={"side_filter": True, "decision_frame": True,
                           "us_session_gate": False, "long_only": False}, cfg=cfg)


def _bundle(evals, packages=None, trades=None):
    tf = _bars()
    return {"since": P.iso(SINCE), "until": P.iso(UNTIL),
            "candles": {"ETHUSDT|4h": {"candles": tf, "error": None},
                        "ETHUSDT|15m": {"candles": _fine(tf), "error": None}},
            "signals": {"trend_donchian_eth_4h": {"rows": evals, "error": None}},
            "order_packages": {"rows": packages or [], "error": None},
            "trades": {"rows": trades or [], "error": None}}


def _consistent_evals(leg):
    """Live evals every 2 min that say exactly what the replay robustly says."""
    probe = P.analyse_leg(leg, _bundle([]), SINCE, UNTIL)
    robust = {w.split("|")[0]: w.split("|")[1] for w in probe["replay_signal_windows"]}
    rows = []
    for t in range(SINCE + 40, UNTIL, 120):
        fs = P.iso(t // 900 * 900)
        side = robust.get(fs, "none")
        rows.append({"event": "trend_donchian_eth_4h_eval", "logged_at_utc": P.iso(t),
                     "strategy": "trend_donchian_eth_4h",
                     "side": {"long": "buy", "short": "sell"}.get(side, "none"),
                     "reason": "x", "adx_14": None})
    return rows, robust


def test_replay_finds_the_breakout():
    leg = _leg()
    res = P.analyse_leg(leg, _bundle([]), SINCE, UNTIL)
    assert res["replay_signal_windows"], "fixture must contain a replay signal"


def test_consistent_live_record_has_zero_missed_or_side_divergence():
    leg = _leg()
    rows, robust = _consistent_evals(leg)
    assert robust
    sig_bars = sorted({P.to_epoch(w) // TF_S * TF_S for w in robust})
    pk = [{"order_package_id": f"p{b}", "strategy_name": leg.name,
           "created_at": P.iso(b + 1900)} for b in sig_bars]
    tr = [{"id": n, "order_package_id": p["order_package_id"], "account_id": "bybit_2",
           "status": "open"} for n, p in enumerate(pk)]
    res = P.analyse_leg(leg, _bundle(rows, pk, tr), SINCE, UNTIL)
    assert res["state"] == "checked"
    bad = {k: v for k, v in res["by_class"].items()
           if v and k in ("missed_signal", "side_mismatch", "lost_bar", "dropped_no_package",
                          "dropped_no_order", "candle_mismatch")}
    assert not bad, res["divergence_detail"]
    assert res["matched_signal_bars"]


def test_planted_defect_live_none_where_replay_signals_is_flagged():
    """THE mandated control: fabricated live 'no signal' over a replay signal."""
    leg = _leg()
    rows, robust = _consistent_evals(leg)
    planted = [dict(r, side="none") for r in rows]
    res = P.analyse_leg(leg, _bundle(planted), SINCE, UNTIL)
    assert res["by_class"]["missed_signal"] > 0
    assert res["divergences"] > 0


def test_planted_lost_bar_is_flagged():
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    b0 = START + (N_BARS - 6) * TF_S
    lost = [r for r in rows if not (b0 <= P.to_epoch(r["logged_at_utc"]) < b0 + TF_S)]
    res = P.analyse_leg(leg, _bundle(lost), SINCE, UNTIL)
    assert any(d["class"] == "lost_bar" and d["bar"] == P.iso(b0) for d in res["divergence_detail"])


def test_planted_live_signal_replay_cannot_produce_is_flagged():
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    b0 = START + (N_BARS - 8) * TF_S  # quiet channel bar
    fake = copy.deepcopy(rows)
    for r in fake:
        if b0 <= P.to_epoch(r["logged_at_utc"]) < b0 + 900:
            r["side"] = "buy"
    res = P.analyse_leg(leg, _bundle(fake), SINCE, UNTIL)
    assert res["by_class"]["live_only_signal"] > 0


def test_signal_without_package_or_named_gate_is_dropped_downstream():
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    res = P.analyse_leg(leg, _bundle(rows), SINCE, UNTIL)
    assert res["by_class"]["dropped_no_package"] > 0
    # ...and a named gate explains it
    gate_t = None
    for r in rows:
        if r["side"] != "none":
            gate_t = r["logged_at_utc"]
            break
    gated = rows + [{"event": "open_package_blocked", "logged_at_utc": gate_t,
                     "strategy": leg.name, "side": "buy"}]
    res2 = P.analyse_leg(leg, _bundle(gated), SINCE, UNTIL)
    assert res2["by_class"]["dropped_no_package"] == 0


def test_candle_mismatch_on_printed_close_outside_the_15m_candle():
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    for r in rows[:3]:
        r["reason"] = "no breakout on the latest bar (close=999.0 within channel [1, 2])"
    res = P.analyse_leg(leg, _bundle(rows), SINCE, UNTIL)
    assert res["by_class"]["candle_mismatch"] >= 1


def test_could_not_check_is_null_never_zero():
    leg = _leg()
    b = _bundle([])
    b["candles"]["ETHUSDT|15m"] = {"candles": [], "error": "fetch_failed: boom"}
    res = P.analyse_leg(leg, b, SINCE, UNTIL)
    assert res["state"] == "could_not_check"
    assert res["divergences"] is None and res["bars_checked"] is None


def test_run_headline_says_could_not_check_before_divergences():
    leg = _leg()
    b = _bundle([])
    b["signals"]["trend_donchian_eth_4h"] = {"rows": [], "error": "signals_table_absent"}
    doc = P.run(b, [leg], SINCE, UNTIL)
    assert doc["status"] == "could_not_check"
    assert doc["totals"]["divergences_real_money"] is None
    assert "COULD NOT CHECK" in doc["headline"]
    assert "COULD NOT CHECK" in P.summary_line(None)


def test_planted_defect_control_passes_in_run():
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    doc = P.run(_bundle(rows), [leg], SINCE, UNTIL)
    pd_ = doc["controls"]["planted_defect"]
    first = pd_["plants"][0]
    assert first["plant"] == "replay_signal_live_none" and first["flagged"] is True


def test_liveness_needs_a_placed_order():
    b = _bundle([], [{"order_package_id": "p", "strategy_name": "x",
                      "created_at": P.iso(SINCE + 10)}],
                [{"order_package_id": "p", "account_id": "bybit_1", "status": "rejected"}])
    assert P.liveness(b, SINCE)["state"] == "fail"
    b["trades"]["rows"][0]["status"] = "closed"
    assert P.liveness(b, SINCE)["state"] == "pass"


def test_findings_file_one_pipeline_row_each_and_never_twice(tmp_path):
    leg = _leg()
    rows, _ = _consistent_evals(leg)
    planted = [dict(r, side="none") for r in rows]
    doc = P.run(_bundle(planted), [leg], SINCE, UNTIL)
    store = tmp_path / "pipeline"
    first = P.file_pipeline(doc, store)
    assert first, "a planted divergence must become a pipeline row"
    from scripts.ops import pipeline
    items = pipeline.read_log(store).items
    for pid in first:
        it = items[pid]
        assert it["due_when"]["kind"] == "observation" and it["origin"]["rerun"]
    assert P.file_pipeline(doc, store) == []  # open row already carries it


def test_seeded_not_yet_run_artifact_reads_could_not_check():
    line = P.summary_line({"schemaVersion": 1, "status": "not_yet_run", "note": "x"})
    assert "COULD NOT CHECK" in line and "divergences = 0" not in line


def _clean_bundle(leg):
    """A bundle with zero divergences: consistent evals plus a package and a
    placed trade on every replay-signal bar."""
    rows, robust = _consistent_evals(leg)
    sig_bars = sorted({P.to_epoch(w) // TF_S * TF_S for w in robust})
    pk = [{"order_package_id": f"p{b}", "strategy_name": leg.name,
           "created_at": P.iso(b + 1900)} for b in sig_bars]
    tr = [{"id": n, "order_package_id": p["order_package_id"], "account_id": "bybit_2",
           "status": "open"} for n, p in enumerate(pk)]
    return _bundle(rows, pk, tr)

@pytest.mark.parametrize("unproven_state", ["could_not_check", "partial"])
def test_unproven_control_is_not_ok_and_is_a_finding(monkeypatch, unproven_state):
    """OA-13: a control that could not run (or ran partly) must not leave the
    run `ok` / exit 0 / no ping -- that is a green while the check could not
    look. Paired with the all-pass twin below so a status that is never `ok`
    cannot pass either."""
    leg = _leg()
    monkeypatch.setattr(P, "planted_defect",
                        lambda *a, **k: {"state": unproven_state, "plants": []})
    monkeypatch.setattr(P, "historical_positive", lambda *a, **k: {"state": "pass"})
    monkeypatch.setattr(P, "liveness", lambda *a, **k: {"state": "pass"})
    doc = P.run(_clean_bundle(leg), [leg], SINCE, UNTIL)
    assert doc["totals"]["divergences_all"] == 0
    assert doc["status"] == "controls_unproven"
    f = [x for x in P.findings(doc) if x["class"] == "control_planted_defect_unproven"]
    assert len(f) == 1 and f[0]["real_money"] is True  # -> ping_needed


def test_all_controls_pass_and_no_divergence_is_ok(monkeypatch):
    leg = _leg()
    for name in ("planted_defect", "historical_positive", "liveness"):
        monkeypatch.setattr(P, name, lambda *a, **k: {"state": "pass"})
    doc = P.run(_clean_bundle(leg), [leg], SINCE, UNTIL)
    assert doc["totals"]["divergences_all"] == 0
    assert doc["status"] == "ok"
    assert not [x for x in P.findings(doc) if x["class"].startswith("control_")]


# ── roster AT THE SIGNAL (LIVE-PARITY-DIAG-1016) ─────────────────────────────
# 2026-10-16: 13 trend_donchian_eth_prop + 2 trend_donchian_sol_prop packages
# (10-10..10-15, prop-only legs then) were scored dropped_no_order on bybit_*
# because today's roster (#18394, #18500) was applied to the whole window, and
# that failed historical_positive 7/22. A pair (planted / clean) per rule.

def _packages_and_orders(leg):
    rows, robust = _consistent_evals(leg)
    sig_bars = sorted({P.to_epoch(w) // TF_S * TF_S for w in robust})
    pk = [{"order_package_id": f"p{b}", "strategy_name": leg.name,
           "created_at": P.iso(b + 1900)} for b in sig_bars]
    return rows, pk, sig_bars


def test_account_joined_after_the_signal_is_not_a_dropped_order():
    leg = _leg()
    rows, pk, sig_bars = _packages_and_orders(leg)
    # clean twin: the leg was on bybit_2 all along, no order -> a real drop
    res = P.analyse_leg(leg, _bundle(rows, pk, []), SINCE, UNTIL)
    assert res["by_class"]["dropped_no_order"] > 0
    # the leg joined bybit_2 AFTER every signal -> nothing was expected there
    leg2 = _leg()
    leg2.roster_from["bybit_2"] = float(UNTIL)
    res2 = P.analyse_leg(leg2, _bundle(rows, pk, []), SINCE, UNTIL)
    assert res2["by_class"]["dropped_no_order"] == 0
    downs = [b["downstream"] for b in res2["bars"] if b.get("downstream")]
    assert downs and all(d.get("not_on_roster_at_signal") == ["bybit_2"] for d in downs)
    # joined BEFORE the signals (past the grace) -> the drop is still flagged
    leg3 = _leg()
    leg3.roster_from["bybit_2"] = float(sig_bars[0] - P.ROSTER_DEPLOY_GRACE_S - 3600)
    res3 = P.analyse_leg(leg3, _bundle(rows, pk, []), SINCE, UNTIL)
    assert res3["by_class"]["dropped_no_order"] == res["by_class"]["dropped_no_order"]


def test_historical_positive_counts_signal_match_not_downstream_drop():
    """The control tests the replay instrument: a matched signal whose order is
    missing is still a matched SIGNAL (the drop stays a leg divergence)."""
    leg = _leg()
    rows, pk, _ = _packages_and_orders(leg)
    b = _bundle(rows, pk, [])
    res = P.analyse_leg(leg, b, SINCE, UNTIL)
    assert res["by_class"]["dropped_no_order"] > 0
    hp = P.historical_positive([res], b)
    assert hp["packages_checked"] > 0
    assert hp["packages_matched"] == hp["packages_checked"]
    assert hp["packages_matched_signal_downstream_divergent"] == hp["packages_checked"]
    # planted: live signals the replay cannot produce, with a package -> FAIL
    fake = copy.deepcopy(rows)
    b0 = START + (N_BARS - 8) * TF_S  # quiet channel bar
    for r in fake:
        if b0 <= P.to_epoch(r["logged_at_utc"]) < b0 + 900:
            r["side"] = "buy"
    pk2 = pk + [{"order_package_id": "planted", "strategy_name": leg.name,
                 "created_at": P.iso(b0 + 300)}]
    b2 = _bundle(fake, pk2, [])
    res2 = P.analyse_leg(leg, b2, SINCE, UNTIL)
    hp2 = P.historical_positive([res2], b2)
    assert hp2["state"] == "fail"
    assert any(c["package"] == "planted" and not c["matched"] for c in hp2["packages"])


def test_roster_joins_dates_a_join_inside_the_window():
    since = 1000.0
    versions = [  # newest first; the last one is in effect at `since`
        (3000.0, {"bybit_2": {"a", "b"}, "bybit_1": {"a", "b"}}),
        (2000.0, {"bybit_2": {"a"}, "bybit_1": {"a", "b"}}),
        (500.0, {"bybit_2": {"a"}, "bybit_1": {"a"}}),
    ]
    current = {"bybit_2": {"a", "b"}, "bybit_1": {"a", "b"}, "x": {"c"}}
    j = P.roster_joins(versions, current)
    assert j == {("b", "bybit_2"): 3000.0, ("b", "bybit_1"): 2000.0}
    assert versions[-1][0] <= since


def test_roster_history_could_not_check_falls_back_and_says_so(tmp_path):
    leg = _leg()
    out = P.roster_history([leg], {"accounts": {}}, float(SINCE), repo=tmp_path)
    assert out["state"] == "could_not_check" and out["fallback"]
    assert leg.roster_from == {}


def test_roster_history_reads_the_real_repo_history():
    """Against this checkout: accounts.yaml has history, so either the read
    reaches the window start or it says why — never a silent empty result."""
    import yaml
    doc = yaml.safe_load((P.REPO_ROOT / P.ACCOUNTS_PATH).read_text(encoding="utf-8"))
    now = __import__("time").time()
    out = P.roster_history([], doc, now - 86400, repo=P.REPO_ROOT)
    assert out["state"] in ("checked", "could_not_check")
    if out["state"] == "could_not_check":
        assert out["reason"]
    else:
        assert out["versions_read"] >= 1


def test_planted_defect_skips_a_signal_window_in_a_bar_before_since():
    """2026-10-16 run 38878704887: the plant landed in the last 15m window of
    the bar BEFORE `since` (cached as a stale-frame candidate), which the run
    never analyses, so the control read FAIL for the instrument's own reason."""
    leg = _leg()
    rows, robust = _consistent_evals(leg)
    sig_bars = sorted({P.to_epoch(w) // TF_S * TF_S for w in robust})
    since = sig_bars[0] + TF_S  # the signal bar is now before the window
    b = _bundle(rows)
    res = P.analyse_leg(leg, b, since, UNTIL)
    cached = [w for w in res["replay_signal_windows"]
              if P.to_epoch(w.split("|")[0]) < since]
    assert cached, "fixture must reproduce a cached signal window before since"
    p1 = P.planted_defect([leg], [res], b, since, UNTIL)["plants"][0]
    assert p1["flagged"] is not False, p1  # never a false FAIL
    assert p1.get("window") is None or P.to_epoch(p1["window"]) >= since
    # and the analysed-window case still plants and flags (clean twin)
    res2 = P.analyse_leg(leg, b, SINCE, UNTIL)
    p2 = P.planted_defect([leg], [res2], b, SINCE, UNTIL)["plants"][0]
    assert p2["flagged"] is True, p2


def test_bar_of_follows_the_mode_live_ran_not_todays_config():
    """LIVE-PARITY-DIAG-1024: a closed-config leg whose bar ran FORMING (a
    decision_bar flip mid-window) owns a package created inside that bar; the
    closed attribution (previous bar) is only for bars that really ran closed."""
    b0 = START + 10 * TF_S
    bars = [{"bar": P.iso(b0 + k * TF_S), "status": "matched_signal"} for k in range(3)]
    r = {"timeframe": "4h", "decision_bar": "closed", "bars": bars,
         "mode_notes": {bars[1]["bar"]: "forming (inferred from eval cadence)"}}
    t = b0 + TF_S + 600  # created 10 min into bar 1, which ran forming
    assert P._bar_of(r, t)["bar"] == bars[1]["bar"]
    # a bar that really ran closed: created just after bar 0 closes -> bar 0
    assert P._bar_of({**r, "mode_notes": {}}, t)["bar"] == bars[0]["bar"]


def test_bars_before_a_legs_join_are_not_lost_bars():
    """A leg that joined every account's roster mid-window has no evals before
    the join; those bars must not be scored lost_bar."""
    leg = _leg()
    res0 = P.analyse_leg(leg, _bundle([]), SINCE, UNTIL)
    assert res0["by_class"]["lost_bar"] > 0  # no evals at all -> every bar lost
    leg.roster_from = {"bybit_2": UNTIL - 2 * TF_S}
    res = P.analyse_leg(leg, _bundle([]), SINCE, UNTIL)
    lost = [d for d in res["divergence_detail"] if d["class"] == "lost_bar"]
    assert lost and all(P.to_epoch(d["bar"]) >= UNTIL - 2 * TF_S for d in lost)
