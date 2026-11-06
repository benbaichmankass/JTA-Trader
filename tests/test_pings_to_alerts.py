"""WSD-S6A: GitHub producers POST pings to /api/bot/alerts instead of committing them."""
import io
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
sys.path.insert(0, str(ROOT / "scripts"))

import digest_due  # noqa: E402
import post_ping  # noqa: E402
from src.runtime import alerts_ledger, ping_ingest  # noqa: E402

ENTRY = {"at": "2026-11-06T20:05:20+00:00", "target": "claude", "priority": "normal",
         "event": "work_digest", "message": "[work digest] hello"}


@pytest.fixture()
def vm(tmp_path, monkeypatch):
    from scripts import notify_on_pull as npl
    monkeypatch.setenv("ALERTS_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(npl, "DELIVERED_HASHES", tmp_path / "delivered.txt")
    sent = []
    import send_ping
    monkeypatch.setattr(send_ping, "enqueue", lambda b, priority="normal", target="trader", **k: sent.append((b, priority, target)))
    return npl, sent, tmp_path


def test_enqueues_like_the_drain_and_is_idempotent(vm, monkeypatch):
    npl, sent, _ = vm
    monkeypatch.setattr(npl, "_digest_suppressed", lambda e: False)
    r = ping_ingest.ingest(ENTRY)
    assert r["ping"] == "enqueued" and len(sent) == 1 and sent[0][2] == "claude"
    assert "hello" in sent[0][0]
    assert ping_ingest.ingest(ENTRY)["ping"] == "duplicate" and len(sent) == 1  # retry never double-sends


def test_policy_suppressed_is_recorded_not_sent(vm, monkeypatch):
    npl, sent, _ = vm
    monkeypatch.setattr(npl, "_digest_suppressed", lambda e: True)
    assert ping_ingest.ingest(ENTRY)["ping"] == "suppressed_by_policy"
    assert sent == []
    rows = alerts_ledger.read(None, None, None)["rows"]
    assert rows and rows[-1]["delivered"] == "suppressed_by_policy" and rows[-1]["kind"] == "manager_update"


def test_receipt_row_is_recorded_and_read_back(vm, monkeypatch):
    npl, _, _ = vm
    monkeypatch.setattr(npl, "_digest_suppressed", lambda e: True)
    now = datetime.now(timezone.utc)
    rec = digest_due.build_receipt(now, "b", "h", "u", "push")
    ping_ingest.ingest(ENTRY, rec)
    rows = [r for r in alerts_ledger.read(None, "work_digest_receipt", None)["rows"]]
    assert len(rows) == 1 and json.loads(rows[0]["body"])["window_head"] == "h"
    assert "work_digest_receipt" in alerts_ledger.ROUTINE_KINDS  # never wakes the manager


def test_bad_entry_raises():
    with pytest.raises(ValueError):
        ping_ingest.ingest({})


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_post_retries_with_diagnosis_then_succeeds(capsys):
    calls = []
    def opener(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(b"busy"))
        return _Resp(b'{"recorded": true}')
    assert post_ping.post({"a": 1}, "t", sleep=lambda s: None, opener=opener) is None
    assert len(calls) == 3 and "HTTP 503" in capsys.readouterr().out


def test_post_gives_up_with_a_diagnosis_never_raises():
    def opener(req, timeout=0): raise urllib.error.URLError("dns")
    d = post_ping.post({"a": 1}, "t", sleep=lambda s: None, opener=opener)
    assert d and "network" in d


def test_post_does_not_retry_auth_failures():
    n = []
    def opener(req, timeout=0):
        n.append(1)
        raise urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b"no"))
    assert "401" in post_ping.post({}, "t", sleep=lambda s: None, opener=opener) and len(n) == 1


def test_main_falls_back_when_token_missing(tmp_path, monkeypatch):
    pend = tmp_path / "p.jsonl"
    pend.write_text(json.dumps(ENTRY) + "\n")
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    assert post_ping.main(["--pending", str(pend), "--receipt", str(tmp_path / "none")]) == 0
    assert "delivered=false" in out.read_text()   # -> workflow commits the legacy way, nothing dropped


def test_gate_prefers_newer_ledger_receipt_and_reports_unreachable(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    f = tmp_path / "r.json"
    f.write_text(json.dumps(digest_due.build_receipt(now - timedelta(hours=5), "a", "old")))
    monkeypatch.setattr(digest_due, "read_ledger_receipt",
                        lambda *a, **k: (digest_due.build_receipt(now, "a", "new"), "read"))
    rec, st, ls = digest_due.read_best_receipt(f)
    assert rec["window_head"] == "new" and ls == "read"
    assert digest_due.grade(rec, st, now)["due"] is False       # no longer due every push
    monkeypatch.setattr(digest_due, "read_ledger_receipt", lambda *a, **k: (None, "could_not_look"))
    rec, st, ls = digest_due.read_best_receipt(f)
    assert rec["window_head"] == "old" and ls == "could_not_look"
