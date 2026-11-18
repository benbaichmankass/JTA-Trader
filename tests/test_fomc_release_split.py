"""CALENDAR-FOMC-RELEASE-SPLIT (PRACTICE-REFRESH-20261118 T-G2).

Two defects, both measured on main e66d3b333:
  1. "FOMC Minutes" was classified as kind fomc (impact 1.0, same as a rate decision).
  2. A decision day carries several releases under ONE event_id; the forward calendar kept only the last-observed, so
     evt-fomc-2026-12-09-us became a single 19:30Z press-conference line and the 19:00Z decision was missing.
"""
from __future__ import annotations

from scripts.macro.econ_calendar_data import (
    KIND_TO_NEWS_CLASS, classify_kind, impact_to_float,
)
from scripts.macro.econ_calendar_produce import _latest_upcoming, build_news_config_events


def _row(name, at, kind, observed="2026-11-18T03:51:02Z", eid="evt-fomc-2026-12-09-us"):
    return {"event_id": eid, "kind": kind, "event_name": name, "country": "US", "status": "scheduled",
            "scheduled_for": at[:10], "scheduled_at": at, "impact_score": 1.0, "observed_at": observed}


def test_minutes_are_their_own_kind_and_decisions_stay_fomc():
    assert classify_kind("FOMC Minutes") == "fomc_minutes"
    assert classify_kind("FOMC Meeting Minutes") == "fomc_minutes"
    assert classify_kind("Fed Minutes") == "fomc_minutes"
    for n in ("Fed Interest Rate Decision", "Fed Monetary Policy Statement", "FOMC Economic Projections",
              "FOMC Press Conference"):
        assert classify_kind(n) == "fomc", n


def test_minutes_keep_their_current_live_weight_and_class():
    # unchanged on purpose until RQ-20261118-a5b3-02 supplies an evidenced weight
    assert impact_to_float("HIGH", kind="fomc_minutes") == 1.0
    assert impact_to_float("HIGH", kind="fomc") == 1.0
    assert KIND_TO_NEWS_CLASS["fomc_minutes"] == "fomc" == KIND_TO_NEWS_CLASS["fomc"]


def test_every_release_on_a_decision_day_survives_the_forward_calendar():
    rows = [
        _row("FOMC Press Conference", "2026-12-09T19:30:00Z", "fomc", observed="2026-11-17T04:45:29Z"),
        _row("Fed Interest Rate Decision", "2026-12-09T19:00:00Z", "fomc"),
        _row("Fed Monetary Policy Statement", "2026-12-09T19:00:00Z", "fomc"),
        _row("FOMC Economic Projections", "2026-12-09T19:00:00Z", "fomc"),
        _row("FOMC Press Conference", "2026-12-09T19:30:00Z", "fomc"),
    ]
    up = _latest_upcoming(rows)
    assert len(up) == 4
    assert {r["event_name"] for r in up} == {
        "Fed Interest Rate Decision", "Fed Monetary Policy Statement", "FOMC Economic Projections",
        "FOMC Press Conference"}


def test_regenerated_config_lists_the_19z_decision_and_the_press_conference():
    rows = [
        _row("Fed Interest Rate Decision", "2026-12-09T19:00:00Z", "fomc"),
        _row("Fed Monetary Policy Statement", "2026-12-09T19:00:00Z", "fomc"),
        _row("FOMC Press Conference", "2026-12-09T19:30:00Z", "fomc"),
    ]
    ev = build_news_config_events(_latest_upcoming(rows), as_of="2026-11-18T12:00:00Z")
    times = [(e["class"], e["time"]) for e in ev]
    assert ("fomc", "2026-12-09T19:00:00Z") in times
    assert ("fomc", "2026-12-09T19:30:00Z") in times
    assert times.count(("fomc", "2026-12-09T19:00:00Z")) == 1  # statement + decision share one line


def test_a_rescheduled_release_still_replaces_its_old_time():
    rows = [
        _row("Fed Interest Rate Decision", "2026-12-09T19:00:00Z", "fomc", observed="2026-11-10T00:00:00Z"),
        _row("Fed Interest Rate Decision", "2026-12-09T18:00:00Z", "fomc", observed="2026-11-18T00:00:00Z"),
    ]
    up = _latest_upcoming(rows)
    assert len(up) == 1 and up[0]["scheduled_at"] == "2026-12-09T18:00:00Z"


def test_minutes_event_is_labelled_minutes_in_the_config_pipeline():
    r = _row("FOMC Minutes", "2026-11-18T19:00:00Z", classify_kind("FOMC Minutes"), eid="evt-fomc-2026-11-18-us")
    assert r["kind"] == "fomc_minutes"
