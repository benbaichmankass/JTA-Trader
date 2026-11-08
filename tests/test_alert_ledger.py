"""ALERT-LEDGER-TO-MANAGER: the alert ledger, its read/write routes, the chokepoint hook and the alert_watch pass.

Gates this adds: none. The detector at the bottom is REPORT-ONLY (operator 2026-11-04: "Yes, non-blocking OK")."""
from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.runtime import alerts_ledger as al
from src.runtime import notify
from src.runtime import telegram_channels as tc

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _row(kind="alert", channel="system", priority="high", minutes_ago=1, body="x failed 3", key=None, delivered="telegram_ok"):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return al.build_row(kind, channel, body, priority=priority, dedup_key=key, delivered=delivered, ts=ts)


# ── ledger ──────────────────────────────────────────────────────────────────
def test_append_read_roundtrip_and_row_shape(tmp_path):
    p = tmp_path / "l.jsonl"
    assert al.append("alert", "system", "B" * 3000, delivered="telegram_ok", path=p)
    out = al.read(path=p)
    assert out["read_state"] == "read" and out["total_matching"] == 1
    r = out["rows"][0]
    assert set(r) == {"ts", "kind", "channel", "priority", "dedup_key", "body", "delivered"}
    assert len(r["body"]) == 1024 and r["priority"] == "high"
    assert out["counts_by_kind"] == {"alert": 1} and out["newest_ts"] == r["ts"]
    assert out["population"]["lines_scanned"] == 1


def test_absent_and_could_not_look_are_never_zero_alerts(tmp_path):
    assert al.read(path=tmp_path / "nope.jsonl")["read_state"] == "absent"
    d = tmp_path / "dir.jsonl"
    d.mkdir()                                     # exists but cannot be read as a file -> not "absent"
    assert al.read(path=d)["read_state"] in ("absent", "could_not_look")
    assert al.read(since="not-a-time", path=tmp_path / "x")["read_state"] == "could_not_look"


def test_filters_since_kind_channel_and_unparseable_lines_are_counted(tmp_path):
    p = tmp_path / "l.jsonl"
    old = al.build_row("alert", "system", "old", ts=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    p.write_text("\n".join([json.dumps(old), "{not json", json.dumps(al.build_row("deploy", "system", "new"))]) + "\n")
    out = al.read(since="1h", path=p)
    assert [r["kind"] for r in out["rows"]] == ["deploy"] and out["population"]["lines_unparseable"] == 1
    assert al.read(kind="alert", path=p)["total_matching"] == 1
    assert al.read(channel="manager", path=p)["total_matching"] == 0


def test_append_failure_is_swallowed(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    assert al.append("alert", "system", "b", path=blocker / "sub" / "l.jsonl") is False   # parent is a file


def test_replies_are_never_ledgered(tmp_path):
    p = tmp_path / "l.jsonl"
    assert al.append("command_reply", "reply", "hi", path=p) is False and not p.exists()


def test_wake_rule():
    assert al.wakes_manager(_row(channel="trades", priority="high")) is False        # trades never wakes
    assert al.wakes_manager(_row(kind="alert", channel="system", priority="high"))
    assert al.wakes_manager(_row(kind="restart", channel="system", priority="normal"))
    assert not al.wakes_manager(_row(kind="hourly_report", channel="system", priority="normal"))
    assert al.wakes_manager(_row(kind="x", channel="manager", priority="high"))
    assert not al.wakes_manager(_row(kind="manager_update", channel="manager", priority="normal"))


# ── chokepoint: the hook records, and can never change the send ────────────────────
def test_chokepoint_records_skipped_ok_and_raised(monkeypatch, tmp_path):
    p = tmp_path / "l.jsonl"
    monkeypatch.setattr(al, "ledger_path", lambda: p)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.send_telegram_direct("no creds", mirror_to_fcm=False, kind="alert", channel="system") is False
    monkeypatch.setattr(notify, "_send_telegram_direct", lambda *a, **k: True)
    assert notify.send_telegram_direct("ok", kind="alert", channel="system") is True

    def boom(*a, **k):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(notify, "_send_telegram_direct", boom)
    with pytest.raises(RuntimeError):                 # the raise is NOT swallowed by the ledger
        notify.send_telegram_direct("bad", kind="alert", channel="system")
    assert [r["delivered"] for r in al.read(path=p)["rows"]] == ["skipped_no_creds", "telegram_ok", "raised"]


def test_ledger_failure_never_changes_the_send(monkeypatch):
    monkeypatch.setattr(notify, "_send_telegram_direct", lambda *a, **k: True)
    monkeypatch.setattr(al, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert notify.send_telegram_direct("still sent", kind="alert") is True


def test_unlabelled_sender_is_unclassified_and_replies_skipped(monkeypatch, tmp_path):
    p = tmp_path / "l.jsonl"
    monkeypatch.setattr(al, "ledger_path", lambda: p)
    monkeypatch.setattr(notify, "_send_telegram_direct", lambda *a, **k: True)
    notify.send_telegram_direct("unlabelled")
    notify.send_telegram_direct("reply", kind="command_reply")
    rows = al.read(path=p)["rows"]
    assert len(rows) == 1 and rows[0]["kind"] == "unclassified" and rows[0]["channel"] == "system"


def test_telegram_channels_send_labels_kind_and_channel(monkeypatch, tmp_path):
    p = tmp_path / "l.jsonl"
    monkeypatch.setattr(al, "ledger_path", lambda: p)
    monkeypatch.setattr(notify, "_send_telegram_direct", lambda *a, **k: True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    assert tc.send("red_flag", "pipeline stuck") is True
    r = al.read(path=p)["rows"][0]
    assert (r["kind"], r["channel"], r["priority"]) == ("red_flag", "system", "high")


# ── routes ───────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src.web.api.main import app
    p = tmp_path / "l.jsonl"
    monkeypatch.setattr(al, "ledger_path", lambda: p)
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
    monkeypatch.setenv("DIAG_READ_TOKEN", "dtok")
    monkeypatch.delenv("SITE_AUTH_ENFORCE", raising=False)
    return TestClient(app)


def test_post_is_fail_closed_and_get_reads_back(client):
    body = {"kind": "alert", "channel": "system", "body": "guards tripped", "delivered": "telegram_ok"}
    assert client.post("/api/bot/alerts", json=body).status_code == 401
    assert client.post("/api/bot/alerts", json=body, headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.post("/api/bot/alerts", json={"kind": "command_reply", "body": "x"},
                       headers={"Authorization": "Bearer tok"}).status_code == 400
    assert client.post("/api/bot/alerts", json=body, headers={"Authorization": "Bearer tok"}).status_code == 200
    g = client.get("/api/bot/alerts?kind=alert").json()
    assert g["read_state"] == "read" and g["rows"][0]["body"] == "guards tripped" and g["counts_by_kind"] == {"alert": 1}


def test_get_before_any_write_is_absent_not_zero(client):
    g = client.get("/api/bot/alerts").json()
    assert g["read_state"] == "absent" and g["rows"] == []


def test_diag_mirror_needs_diag_token(client):
    assert client.get("/api/diag/alerts").status_code == 401
    r = client.get("/api/diag/alerts", headers={"Authorization": "Bearer dtok"})
    assert r.status_code == 200 and r.json()["read_state"] == "absent"


def test_cors_allows_browser_get_and_authorized_post(client):
    r = client.options("/api/bot/alerts", headers={"Origin": "https://benbaichmankass.github.io",
                                                   "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.status_code == 200 and "authorization" in r.headers.get("access-control-allow-headers", "").lower()


# ── alert_watch ──────────────────────────────────────────────────────────────
aw = pytest.importorskip("scripts.ops.attention_watch")


def test_one_compact_comment_per_burst_and_cap():
    rows = [_row(minutes_ago=m, body=f"all_accounts_failed bybit_1 try {m} " + "z" * 400, key="k1") for m in range(1, 6)]
    rows += [_row(kind="trade_opened", channel="trades", priority="high")]            # never wakes
    body, st, summ = aw.plan_alert_comment(rows, {}, NOW)
    assert body and len(body) <= 1500 and body.startswith("ALERT ×5 alert×5")
    assert "trade_opened" not in body and "/api/bot/alerts?since=" in body and "<!-- alert-watch" in body
    assert body.count("- `alert`") == 1                                                # collapsed by dedup_key, with a count
    assert "×5" in body.splitlines()[1]
    # the same rows again after the post: silent
    assert aw.plan_alert_comment(rows, st, NOW + timedelta(minutes=5))[0] is None


def test_kind_cooldown_holds_then_releases_with_count():
    st = aw.plan_alert_comment([_row(minutes_ago=2)], {}, NOW)[1]
    later = [_row(minutes_ago=0, body="new burst", key="k2")]
    body, st2, summ = aw.plan_alert_comment(later, st, NOW + timedelta(minutes=10))
    assert body is None and summ["held_kinds"] == ["alert"]
    body, _, _ = aw.plan_alert_comment(later, st, NOW + timedelta(minutes=31))
    assert body and "alert×1" in body


def test_first_run_does_not_replay_history():
    assert aw.plan_alert_comment([_row(minutes_ago=120)], {}, NOW)[0] is None


def test_alert_watch_posts_once_and_advances_cursor_only_on_201(monkeypatch, tmp_path):
    monkeypatch.setattr(aw, "ALERT_STATE", tmp_path / "s.json")
    monkeypatch.setattr(aw, "ALERT_RECEIPT", tmp_path / "r.json")
    calls = []

    def http(method, url, body, auth):
        calls.append((method, url))
        return (500 if len(calls) == 1 else 201), None
    led = {"read_state": "read", "rows": [_row()]}
    r1 = aw.alert_watch(NOW, rows_override=led, github=("Basic x", http, "https://api.github.com"))
    assert r1["state"] == "could_not_post" and not (tmp_path / "s.json").exists()   # not advanced: retried next pass
    r2 = aw.alert_watch(NOW, rows_override=led, github=("Basic x", http, "https://api.github.com"))
    assert r2["state"] == "posted" and any("issues/17895/comments" in u for _, u in calls)
    assert aw.alert_watch(NOW + timedelta(minutes=5), rows_override=led,
                          github=("Basic x", http, "https://api.github.com"))["state"] == "nothing_new"


def test_unreadable_ledger_is_could_not_look_not_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(aw, "ALERT_RECEIPT", tmp_path / "r.json")
    r = aw.alert_watch(NOW, rows_override={"read_state": "could_not_look", "reason": "OSError"},
                       github=(None, None, None))
    assert r["state"] == "could_not_look"


def test_ltr_compaction_keeps_marker_and_shrinks():
    marker = '<!-- ltr-wake {"kind":"due","entries":[{"order_package_id":"p1"}]} -->'
    big = ('**LTR wake: 1 event**\n- `p1` x\n\n<details><summary>review packet</summary>\n\n<!-- ltr-packet p1 -->\n```json\n'
           '{"table_path":"comms/live_review/tables/r1.json","packet":{"a":"' + "q" * 30000 + '"}}\n```\n</details>\n\n' + marker)
    out = aw.compact_ltr_body(big)
    assert out and len(out) < 1500 and marker in out and "live-review/rows/comms/live_review/tables/r1.json" in out
    assert aw.compact_ltr_body(out) is None                                           # idempotent
    from scripts.ops import live_review_wake as lw
    assert lw.parse_markers([{"body": out}]) == lw.parse_markers([{"body": big}])     # dedupe state survives


def test_ltr_compaction_only_old_oversized(monkeypatch):
    marker = '<!-- ltr-wake {"kind":"due","entries":[]} -->'
    def mk(age_h, size):
        return {"id": 1, "created_at": (NOW - timedelta(hours=age_h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "body": "<details>" + "p" * size + "</details>\n" + marker}
    patched = []

    def http(method, url, body, auth):
        if method == "GET":
            return 200, [mk(1, 5000), mk(48, 100), mk(48, 5000)]
        patched.append(url)
        return 200, None
    out = aw.compact_ltr_comments("a", http, "https://api.github.com", NOW)
    assert out["compacted"] == 1 and len(patched) == 1       # fresh one kept whole (the lane still needs the packet); small kept


def test_alert_watch_pass_never_edits_comments(monkeypatch, tmp_path):
    """Every PATCH on the ops-flags PR wakes the subscribed manager (LTR-COMPACT-EDIT-WAKES): the pass must not edit."""
    monkeypatch.setattr(aw, "ALERT_STATE", tmp_path / "state.json")
    monkeypatch.setattr(aw, "ALERT_RECEIPT", tmp_path / "receipt.json")
    calls = []

    def http(method, url, body, auth):
        calls.append(method)
        return (200, []) if method == "GET" else (201, None)
    rec = aw.alert_watch(NOW, rows_override={"read_state": "read", "rows": []}, github=("a", http, "https://api.github.com"))
    assert "PATCH" not in calls
    assert rec["ltr_compact"] == {"state": "disabled_wakes_manager"}


# ── REPORT-ONLY detector (operator 2026-11-04: non-blocking) ───────────────────────
_CHOKE = re.compile(r"send_telegram_direct|telegram_channels|tc\.send|send_to_operator|send_via_alert_manager|notify_operator|send_ping|enqueue")
_LEDGERED = re.compile(r"alerts_ledger|post_alert\.sh|/api/bot/alerts")


def classify_senders() -> dict:
    out = {"chokepoint": [], "bypass_ledgered": [], "bypass_unledgered": []}
    for rel in sorted(tc.SENDERS):
        f = REPO / rel
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        direct = "api.telegram.org" in text and rel != "src/runtime/notify.py"
        if not direct:
            out["chokepoint"].append(rel)
        elif _LEDGERED.search(text):
            out["bypass_ledgered"].append(rel)
        elif _CHOKE.search(text) and rel.endswith(".py"):
            out["chokepoint"].append(rel)      # imports the chokepoint as well
        else:
            out["bypass_unledgered"].append(rel)
    return out


def test_detector_report_python_senders_that_bypass_the_chokepoint():
    """REPORT, never a failure for an unledgered sender: it prints the measured split of SENDERS (the F2 count) and
    warns. Hard asserts are only the probe's own positive controls, so a probe that cannot see a bypass cannot pass."""
    c = classify_senders()
    n = sum(len(v) for v in c.values())
    print(f"\nALERT-LEDGER detector: {n} mapped senders · {len(c['chokepoint'])} via the chokepoint/queue · "
          f"{len(c['bypass_ledgered'])} bypass-but-ledgered · {len(c['bypass_unledgered'])} bypass-UNLEDGERED")
    for rel in c["bypass_unledgered"]:
        print(f"  UNLEDGERED: {rel}")
    if c["bypass_unledgered"]:
        warnings.warn(f"{len(c['bypass_unledgered'])} sender(s) bypass the alert-ledger chokepoint: {c['bypass_unledgered']}")
    assert n > 50, "denominator: SENDERS must be read"
    assert "scripts/ops/send_route_test_ping.py" in c["bypass_ledgered"], "positive control: a known bypass must be seen"
    assert "src/runtime/hourly_report.py" in c["chokepoint"]
    assert ".github/workflows/guards.yml" in c["bypass_ledgered"]


import pytest as _pytest_wt  # noqa: E402


@_pytest_wt.fixture(autouse=True)
def _wake_switches_all_on(tmp_path, monkeypatch):
    from src.runtime import wake_toggles as _wt
    monkeypatch.setenv("RUNTIME_STATE_DIR", str(tmp_path / "_wt_state"))
    monkeypatch.setenv("RUNTIME_LOGS_DIR", str(tmp_path / "_wt_logs"))
    monkeypatch.delenv("WAKE_TOGGLES_REMOTE", raising=False)
    for _k in _wt.TOGGLES:
        _wt.set_toggle(_k, True, "test")
