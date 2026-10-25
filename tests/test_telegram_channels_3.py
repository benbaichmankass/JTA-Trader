"""TELEGRAM-CHANNELS-3 — the manager-update format fixes (items 1-4) and the
telegram_settings visibility finding (item 6). One test per item."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from scripts.ops import research_digest as rd
from scripts.ops import work_section as w

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)


def _row(state, title="t", **kw):
    return {"state": state, "title": title, "blocked_on": kw.get("blocked_on", []),
            "why": kw.get("why", "—"), "observation": kw.get("observation"),
            "updated_at": kw.get("updated_at")}


def _snap(rows):
    return {"rows": rows, "items": {}, "checklist_state": "read", "pipeline_state": "read"}


def _wdn():
    spec = importlib.util.spec_from_file_location("_wdn_tc3", ROOT / "scripts/ops/work_digest_now.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_item1_blocked_leads_and_history_is_capped_and_last():
    prev = {"at": "2026-10-11T07:00:00+00:00", "items": {},
            "rows": {**{f"S{i}": "in_flight" for i in range(9)},
                     **{f"V{i}": "in_flight" for i in range(9)}, "B": "queued"}}
    rows = {**{f"S{i}": _row("landed_unproven", f"ship {i}") for i in range(9)},
            **{f"V{i}": _row("done", observation=f"saw {i}") for i in range(9)},
            "B": _row("blocked", blocked_on=["X"]), "N": _row("queued", "next")}
    body = w.render_body(w.build(prev=prev, now=NOW, snap=_snap(rows),
                                 git={"merged_prs": 0, "reverts": []}))
    i = [body.index(k) for k in ("BLOCKED", "IN FLIGHT / NEXT", "SHIPPED", "VERIFIED")]
    assert i == sorted(i)
    assert body.count("S0 —") == 1 and "S5 —" not in body       # cap 5
    assert "… +4 more" in body and "V5 —" not in body


def test_item2_verified_states_the_outcome_not_the_title_or_the_plan():
    prev = {"at": "2026-10-11T07:00:00+00:00", "items": {},
            "rows": {k: "landed_unproven" for k in "ABC"}}
    rows = {"A": _row("done", "Row title A", why="probe returned 200 with 3 journal lines"),
            "B": _row("done", "Row title B", observation=w._obs({"what": "check X", "result": "X read 0.12"})),
            "C": _row("done", "Row title C", observation=w._obs({"what": "check Y"}), why="Y confirmed live")}
    v = w.build(prev=prev, now=NOW, snap=_snap(rows),
                git={"merged_prs": 0, "reverts": []})["buckets"][w.VERIFIED]
    assert v == ["A — probe returned 200 with 3 journal lines", "B — X read 0.12",
                 "C — Y confirmed live"]


def test_item3_headline_says_newly_queued_not_queued():
    t = {"run": [], "newly_queued": [], "newly_blocked": []}
    h = rd.headline({"queue_state": "read", "results_state": "read",
                     "buckets": {k: [] for k in (rd.PASSED, rd.FAILED, rd.FURTHER, rd.OTHER)},
                     "transitions": t})
    assert "0 newly queued · 0 newly blocked" in h


def test_item4_no_ask_prints_the_no_decisions_line_once():
    mod = _wdn()
    prep = {"priority": "normal", "receipt": {"ask_operator_open": 0},
            "msgs": ["🧱 1 finding\n• X"]}
    work = w.build(prev=None, now=NOW, git={"merged_prs": 0, "reverts": []}, snap=_snap({}))
    msg = mod.compose_update("2026-10-11T14", prep, "", {}, {"error": "x"}, work)
    assert msg.count("No new decisions for you") == 1 and "Needs you" not in msg
    ask = {**prep, "msgs": ["❓ 1 new decision(s) for you:\n• PI-X: arm?"] + prep["msgs"]}
    msg = mod.compose_update("2026-10-11T14", ask, "", {}, {"error": "x"}, work)
    assert "Needs you" in msg and "PI-X: arm?" in msg


def test_item6_diag_log_file_allowlist_reads_the_settings_store():
    from src.web.api.routers import diag

    # Not compared with ts._path(): that reads TELEGRAM_SETTINGS_PATH at call
    # time and other tests set it; the router resolves it once at import.
    assert diag._LOG_FILES["telegram_settings"].name == "telegram_settings.json"


def test_item6_system_health_shows_only_non_default_settings(tmp_path, monkeypatch):
    from src.runtime import hourly_report as hr
    from src.runtime import telegram_settings as ts

    monkeypatch.setenv("TELEGRAM_SETTINGS_PATH", str(tmp_path / "s.json"))
    assert hr._notification_settings_section() is None            # absent == defaults
    ts.set_cadence("manager_update", "4h", by="operator:menu")
    sec = hr._notification_settings_section()
    assert "1 non-default" in sec.summary
    assert "Manager update (manager): every 4h" in sec.body
    assert "by operator:menu" in sec.body
    (tmp_path / "s.json").write_text("{not json")
    assert "UNREADABLE" in hr._notification_settings_section().body
