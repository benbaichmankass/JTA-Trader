"""LTR-1B part B: the live-review wake (due event -> one ops-flags comment)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lrw", ROOT / "scripts/ops/live_review_wake.py")
lrw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lrw)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
CFG = lrw.load_cfg()


def due(*pkgs):
    return {"read_state": "looked", "due_count": len(pkgs), "generated_at": NOW.isoformat(),
            "due": list(pkgs)}


def pkg(pid="pkg-1", acct="bybit_2", events=(("r_milestone", 1),)):
    return {"order_package_id": pid, "leg": "ada_pullback_2h", "symbol": "ADAUSDT", "account_id": acct,
            "telemetry_updated_at": NOW.isoformat(),
            "events": [{"event": e, "level": lvl, "why": "x"} for e, lvl in events]}


def posted_from(plan, at):
    body = lrw.render(plan, at, "run")
    return lrw.parse_markers([{"body": body}])


def test_real_money_wakes_paper_does_not():
    p = lrw.plan(due(pkg(), pkg("pkg-2", acct="bybit_1")), [], CFG, NOW)
    assert p["kind"] == "wake" and [e["order_package_id"] for e in p["entries"]] == ["pkg-1"]


def test_daily_floor_never_wakes():
    p = lrw.plan(due(pkg(events=(("daily_floor", "2026-10-26"),))), [], CFG, NOW)
    assert p["kind"] == "quiet"


def test_dedupe_and_cooldown_round_trip_through_the_marker():
    first = lrw.plan(due(pkg()), [], CFG, NOW)
    posted = posted_from(first, NOW - timedelta(minutes=10))
    assert posted[0]["entries"][0]["event"] == "r_milestone"
    assert lrw.plan(due(pkg()), posted, CFG, NOW)["kind"] == "quiet"            # same level: deduped
    nxt = due(pkg(events=(("r_milestone", 2),)))
    assert lrw.plan(nxt, posted, CFG, NOW)["kind"] == "quiet"                   # new level, in cooldown
    later = NOW + timedelta(minutes=lrw.COOLDOWN_MIN)
    assert lrw.plan(nxt, posted, CFG, later)["kind"] == "wake"                  # cooldown over
    gb = due(pkg(events=(("giveback", 1.5),)))
    gposted = posted_from(lrw.plan(gb, [], CFG, NOW), NOW - timedelta(minutes=5))
    assert lrw.plan(due(pkg(events=(("giveback", 2.0),))), gposted, CFG, NOW)["kind"] == "wake"  # exempt


def test_one_package_on_two_accounts_is_one_entry():
    p = lrw.plan(due(pkg(acct="bybit_2"), pkg(acct="bybit_portfolio")), [], CFG, NOW)
    assert len(p["entries"]) == 1 and p["entries"][0]["accounts"] == ["bybit_2", "bybit_portfolio"]


def test_could_not_look_flags_once_then_quiet():
    bad = {"read_state": "could_not_look", "due_count": None, "reason": "telemetry_table_absent"}
    p = lrw.plan(bad, [], CFG, NOW)
    assert p["kind"] == "could_not_look"
    posted = posted_from(p, NOW - timedelta(minutes=30))
    assert lrw.plan(bad, posted, CFG, NOW)["kind"] == "quiet"
    assert lrw.plan(bad, posted, CFG, NOW + timedelta(hours=7))["kind"] == "could_not_look"


def test_marker_carries_the_fields_the_manager_needs():
    m = posted_from(lrw.plan(due(pkg()), [], CFG, NOW), NOW)[0]["entries"][0]
    assert {"order_package_id", "leg", "accounts", "event", "level", "due_at"} <= set(m)
    assert json.dumps(m)


def test_cli_from_file_prints_and_does_not_post(tmp_path):
    f = tmp_path / "d.json"
    f.write_text(json.dumps(due(pkg())))
    assert lrw.main(["--from-file", str(f)]) == 0
