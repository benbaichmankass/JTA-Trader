"""LTR-PRACTICE-REDESIGN: the pre-screen events (adverse_r / stall / momentum_flip /
structure_break) and the per-evaluation log. Each event fires on a planted path and
stays quiet on a control path; dedupe/cooldown hold; existing due output is unchanged."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

from src.runtime import live_review_due as lrd
from src.runtime import live_review_wake_post as post

NOW = datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc)
CFG = lrd.load_config()
TF = 7200
NO_PRIOR = {"fired": set(), "last": None, "peak": None, "mech": None}


def row(**kw):
    base = {"order_package_id": "pkg-1", "strategy": "ada_pullback_2h", "account_id": "bybit_2",
            "symbol": "ADAUSDT", "direction": "long", "open_r": 0.1, "peak_r": 0.6,
            "giveback_r": 0.5, "r_to_target": 3.0, "bars_held": 3,
            "updated_at": NOW.isoformat(), "lifecycle": "open"}
    base.update(kw)
    return base


def hist(prices, atr=0.1):
    """Path-history bars ending with a FORMING bar (the last one is never read as closed)."""
    start = NOW - timedelta(seconds=TF * (len(prices) - 1))
    return [{"bar_ts": (start + timedelta(seconds=TF * i)).isoformat(), "last_price": p, "atr": atr}
            for i, p in enumerate(prices)]


def ctx(history):
    return {"history": history, "history_reason": None, "calendar": {"state": "read", "events": [],
            "classes": {}}, "funding": {"state": "read", "row": None}}


def ps(r, history=None, prior=None):
    return lrd.prescreen(r, prior or copy.deepcopy(NO_PRIOR), ctx(history if history is not None else []),
                         CFG, NOW, TF)


def fired(evs):
    return {e[0]: e[1] for e in evs}


FLAT = [1.0, 1.01, 1.0, 1.01, 1.0, 1.01, 1.0]


# -- adverse_r ----------------------------------------------------------------

def test_adverse_r_fires_at_each_level_and_quiet_above():
    assert "adverse_r" not in fired(ps(row(open_r=-0.4))[0])
    assert fired(ps(row(open_r=-0.55))[0])["adverse_r"] == -0.5
    assert fired(ps(row(open_r=-0.8))[0])["adverse_r"] == -0.75


def test_adverse_r_deeper_review_covers_shallower_and_same_level_dedupes():
    prior = dict(NO_PRIOR, fired={("adverse_r", "-0.75")})
    assert "adverse_r" not in fired(ps(row(open_r=-0.6), prior=prior)[0])
    prior = dict(NO_PRIOR, fired={("adverse_r", "-0.5")})
    assert "adverse_r" not in fired(ps(row(open_r=-0.6), prior=prior)[0])
    assert fired(ps(row(open_r=-0.8), prior=prior)[0])["adverse_r"] == -0.75


# -- stall --------------------------------------------------------------------

def test_stall_threshold_from_timeframe_and_peak_guard():
    need = lrd.stall_bars(CFG["events"]["stall"], TF)
    assert need == 8
    assert fired(ps(row(bars_held=need, peak_r=0.3))[0])["stall"] == need
    assert "stall" not in fired(ps(row(bars_held=need - 1, peak_r=0.3))[0])
    assert "stall" not in fired(ps(row(bars_held=need + 4, peak_r=0.6))[0])  # made progress
    # re-fires only at the next multiple
    assert fired(ps(row(bars_held=2 * need + 1, peak_r=0.3))[0])["stall"] == 2 * need
    assert lrd.stall_bars(CFG["events"]["stall"], 86400) == 5


# -- momentum_flip --------------------------------------------------------------

def test_momentum_flip_fires_on_three_adverse_closes_and_not_on_chop():
    planted = [1.0, 1.01, 1.0, 1.01, 0.96, 0.92, 0.88, 0.99]  # last bar forming, ignored
    assert "momentum_flip" in fired(ps(row(), hist(planted))[0])
    assert "momentum_flip" not in fired(ps(row(), hist(FLAT))[0])
    # same path is FAVOURABLE for a short: quiet
    assert "momentum_flip" not in fired(ps(row(direction="short"), hist(planted))[0])
    # three adverse closes but net < 1 ATR: quiet
    small = [1.0, 1.01, 1.0, 1.01, 0.99, 0.97, 0.95, 1.0]
    assert "momentum_flip" not in fired(ps(row(), hist(small))[0])


def test_momentum_flip_one_level_per_episode():
    a = [1.0, 1.01, 1.0, 1.01, 0.96, 0.92, 0.88, 0.88]
    b = a[:-1] + [0.84, 0.84]  # the episode continues one more closed bar
    la = fired(ps(row(), hist(a))[0])["momentum_flip"]
    lb = fired(ps(row(), hist(b))[0])
    # the level is the bar that OPENED the episode, so a continuing episode keeps it
    assert la == hist(a)[6]["bar_ts"]
    assert lb["momentum_flip"] == hist(b)[6]["bar_ts"]


# -- structure_break -------------------------------------------------------------

def test_structure_break_fires_below_since_entry_low_and_not_inside():
    planted = [1.0, 0.98, 1.02, 1.03, 1.01, 0.95, 0.95]
    assert "structure_break" in fired(ps(row(), hist(planted))[0])
    inside = [1.0, 0.98, 1.02, 1.03, 1.01, 0.985, 0.985]  # above the 0.98 low
    assert "structure_break" not in fired(ps(row(), hist(inside))[0])
    # within the buffer (0.1 ATR = 0.01): quiet
    buffer = [1.0, 0.98, 1.02, 1.03, 1.01, 0.975, 0.975]
    assert "structure_break" not in fired(ps(row(), hist(buffer))[0])
    # too few closed bars: could not look, never quiet
    _, cnl, rec = ps(row(), hist([1.0, 0.9, 0.9]))
    assert "structure_break" in {c["event"] for c in cnl}
    assert rec["checks"]["structure_break"]["read"] == "could_not_look"


def test_cooldown_blocks_a_new_episode_too_soon():
    conds = [False, True, False, True, True]
    assert lrd._episode(conds, 3) is None  # re-opened 2 bars after the last episode
    assert lrd._episode([False, True, False, False, True], 3) == 4
    assert lrd._episode([False, True, False, True], 3) is None


# -- read states, records and rollback ---------------------------------------------

def test_telemetry_absent_and_no_history_are_could_not_look():
    r = row(telemetry_absent=True, open_r=None, peak_r=None, bars_held=None)
    evs, cnl, rec = lrd.prescreen(r, NO_PRIOR, {"history": None, "history_reason": "history_table_absent"},
                                  CFG, NOW, TF)
    assert not evs
    assert {c["event"] for c in cnl} == set(lrd.PRESCREEN_EVENTS)
    assert all(c["read"] == "could_not_look" for c in rec["checks"].values())


def test_record_written_for_quiet_package_with_control_draw():
    evs, cnl, rec = ps(row(), hist(FLAT))
    assert not evs and not cnl
    assert rec["flagged"] == [] and set(rec["checks"]) == set(lrd.PRESCREEN_EVENTS)
    assert all(c["read"] == "looked" for c in rec["checks"].values())
    assert rec["closed_bar_ts"] == hist(FLAT)[-2]["bar_ts"]
    assert 0 <= rec["control_u"] < 1
    assert rec["control_u"] == ps(row(), hist(FLAT))[2]["control_u"]  # fixed by (pkg, bar)


def test_rollback_absent_config_evaluates_nothing():
    cfg = copy.deepcopy(CFG)
    for n in lrd.PRESCREEN_EVENTS:
        cfg["events"].pop(n)
    evs, cnl, rec = lrd.prescreen(row(open_r=-0.9), NO_PRIOR, ctx(hist(FLAT)), cfg, NOW, TF)
    assert (evs, cnl, rec) == ([], [], None)


# -- compute_due integration -----------------------------------------------------

def _no_prescreen_cfg():
    cfg = copy.deepcopy(CFG)
    for n in lrd.PRESCREEN_EVENTS:
        cfg["events"].pop(n)
    return cfg


def test_existing_due_output_unchanged_on_control_path():
    rows = [row(), row(order_package_id="pkg-2", open_r=1.2, peak_r=1.3, giveback_r=0.1)]
    market = {"pkg-1": ctx(hist(FLAT)), "pkg-2": ctx(hist(FLAT))}
    reviews = [{"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(hours=3)).isoformat(),
                "trigger": {"event": "daily_floor", "level": "2026-10-28"}}]
    new = lrd.compute_due(rows, reviews, CFG, NOW, market=market)
    old = lrd.compute_due(rows, reviews, _no_prescreen_cfg(), NOW, market=market)
    assert new["due"] == old["due"]
    assert new["due_count"] == old["due_count"]
    assert len(new["prescreen"]) == 2 and old["prescreen"] == []
    for c in new["event_coverage"]:
        assert set(lrd.PRESCREEN_EVENTS) <= set(c["events_looked"])


def test_compute_due_dedupes_an_answered_event_and_adverse_is_cooldown_exempt():
    r = row(open_r=-0.6)
    market = {"pkg-1": ctx(hist(FLAT))}
    due = lrd.compute_due([r], [], CFG, NOW, market=market)
    evs = [e for d in due["due"] for e in d["events"]]
    assert ("adverse_r", -0.5) in [(e["event"], e["level"]) for e in evs]
    # reviewed THIS bar for another reason: adverse_r still due (cooldown-exempt) ...
    rv = [{"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(minutes=5)).isoformat(),
           "trigger": {"event": "swing", "level": "x"}}]
    evs = [e["event"] for d in lrd.compute_due([r], rv, CFG, NOW, market=market)["due"] for e in d["events"]]
    assert "adverse_r" in evs
    # ... and once answered, quiet
    rv.append({"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(minutes=4)).isoformat(),
               "trigger": {"event": "adverse_r", "level": -0.5}})
    evs = [e["event"] for d in lrd.compute_due([r], rv, CFG, NOW, market=market)["due"] for e in d["events"]]
    assert "adverse_r" not in evs


def test_stall_is_inside_the_per_bar_cooldown():
    r = row(bars_held=9, peak_r=0.2)
    rv = [{"order_package_id": "pkg-1", "reviewed_at": (NOW - timedelta(minutes=5)).isoformat(),
           "trigger": {"event": "swing", "level": "x"}}]
    out = lrd.compute_due([r], rv, CFG, NOW, market={"pkg-1": ctx(hist(FLAT))})
    assert out["due"] == [] and out["suppressed_by_cooldown"] == 1


# -- the log ---------------------------------------------------------------------

def test_log_prescreen_writes_once_per_bar_and_on_flag_change(tmp_path):
    post._prescreen_seen.clear()
    p = tmp_path / "prescreen.jsonl"
    _, _, rec = ps(row(), hist(FLAT))
    doc = {"prescreen": [rec]}
    assert post.log_prescreen(doc, p) == 1
    assert post.log_prescreen(doc, p) == 0  # same bar, same flags
    _, _, rec2 = ps(row(open_r=-0.6), hist(FLAT))
    assert post.log_prescreen({"prescreen": [rec2]}, p) == 1  # flagged set changed
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    assert [x["flagged"] for x in lines] == [[], ["adverse_r"]]
    assert post.log_prescreen({"due": []}, p) == 0
    assert post.log_prescreen(None, p) == 0


def test_validator_knows_the_new_events():
    import importlib.util
    spec = importlib.util.spec_from_file_location("clr", "scripts/ci/check_live_review_records.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert set(lrd.PRESCREEN_EVENTS) <= set(m.DUE_EVENTS)
