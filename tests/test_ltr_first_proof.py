"""LTR first-proof pings: once ever per stage, seeded from existing receipts, retried on a failed send."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.runtime import live_review_rows as rows_lib
from src.runtime import live_review_rows_watch as w
from src.runtime import ltr_first_proof as fp


@pytest.fixture(autouse=True)
def _legacy_tighten_path(monkeypatch):
    """S3..S7 prove a TIGHTEN's chain; since 2026-10-28 a tighten is advice only (rows_lib.ADVICE_ONLY_ACTIONS),
    so these tests exercise the mechanism with the legacy path (PI-20261028-GGKQ4MZL-0001 generalises the stages)."""
    monkeypatch.setattr(rows_lib, "ADVICE_ONLY_ACTIONS", ())

T0 = datetime(2026, 10, 26, 13, 0, tzinfo=timezone.utc)
MONEY = [{"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply", "evidence": "x"}]


def row(action="tighten_sl", basis="judgement", rid="LR-1", paper=False):
    reads = [dict(a, account_class="paper") for a in MONEY] if paper else MONEY
    return {"review_id": rid, "leg": "ada_pullback_2h", "accounts": ["bybit_2"], "account_reads": reads,
            "reviewed_at": "2026-10-26T12:59:00Z", "trigger": {"l0_snapshot_at": "2026-10-26T12:58:00Z"},
            "recommendation": {"action": action, "basis": basis, "judgement_confidence": 0.6, "reason": "r"},
            "disposition": {"route": "recommended"}}


ENTRY = {"review_id": "LR-1", "at": "2026-10-26T13:01:00Z",
         "account_reads": [{"account_id": "bybit_2", "account_class": "real_money", "read": "would_apply"}],
         "accounts_applied": [{"account_id": "bybit_2", "level": 1.0, "executor": {"result": "applied"}}],
         "disposition": {"verified_readback": True}}


def setup(tmp_path, monkeypatch, sends=None, ok=True):
    sends = [] if sends is None else sends
    monkeypatch.setattr(fp, "state_path", lambda: tmp_path / "ltr_first_proof.json")
    monkeypatch.setattr(fp, "_committed_reviews", lambda: [])
    monkeypatch.setattr(fp, "_send", lambda text: (sends.append(text), ok)[1])
    return sends


def stages(tmp_path):
    return json.loads((tmp_path / "ltr_first_proof.json").read_text())["stages"]


def test_each_stage_pings_once_ever(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    assert fp.record("S1_wake", at=T0) is True
    assert fp.record("S1_wake", at=T0 + timedelta(hours=1)) is False
    assert len(sends) == 1 and sends[0].startswith("LTR FIRST PROOF S1_wake")


def test_a_failed_send_is_not_marked_and_retries(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, ok=False)
    assert fp.record("S1_wake", at=T0) is False and "S1_wake" not in stages(tmp_path)
    sends = setup(tmp_path, monkeypatch, ok=True)
    assert fp.record("S1_wake", at=T0) is True and len(sends) == 1


def test_seed_marks_already_proven_stages_and_they_never_ping(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    (tmp_path / "live_review").mkdir()
    (tmp_path / "live_review" / "applied.jsonl").write_text(json.dumps(ENTRY) + "\n")
    monkeypatch.setattr(fp, "_committed_reviews", lambda: [row()])
    fp.ensure_seeded()
    st = stages(tmp_path)
    assert {"S2_call", "S3_tighten", "S5_approve", "S6_sent", "S7_confirmed"} <= set(st)
    assert all(v.get("seeded") for v in st.values())
    assert fp.record_writeback(row(), ENTRY, at=T0) == [] and sends == []


def test_latency_from_the_previous_stage_and_end_to_end(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    fp.record("S4_pickup", at=T0, review_id="LR-1")
    got = fp.record_writeback(row(), ENTRY, at=T0 + timedelta(seconds=40))
    assert got == ["S5_approve", "S6_sent", "S7_confirmed"]
    assert "40s after S4_pickup" in sends[1]
    st = stages(tmp_path)
    assert st["S7_confirmed"]["end_to_end_s"] == (T0 + timedelta(seconds=40) -
                                                  datetime(2026, 10, 26, 12, 58, tzinfo=timezone.utc)).total_seconds()
    assert "trigger -> confirmed" in sends[-1]


def test_paper_rows_and_non_judgement_rows(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    assert fp.record_row(row(paper=True), at=T0) == []
    assert fp.record_row(row(action="hold", basis="ev_positive"), at=T0) == []
    assert fp.record_row(row(action="hold"), at=T0) == ["S2_call"]
    assert fp.record_row(row(basis="table"), at=T0) == ["S3_tighten"]
    assert len(sends) == 2


def test_a_wake_from_before_the_seed_is_history_not_a_late_ping(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    fp.ensure_seeded()
    old = {"kind": "wake", "posted_at": "2020-01-01T00:00:00+00:00", "entries": [{"leg": "x"}]}
    assert fp.observe_wake_markers([old]) is False and sends == []
    assert stages(tmp_path)["S1_wake"]["seeded"] is True


def test_a_wake_after_the_seed_pings(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    fp.ensure_seeded()
    new = {"kind": "wake", "posted_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
           "entries": [{"leg": "ada_pullback_2h", "accounts": ["bybit_2"], "poster": "vm"}]}
    assert fp.observe_wake_markers([new]) is True and "posted by vm" in sends[0]


def test_the_watcher_proves_s2_to_s7_for_a_real_dispatch(tmp_path, monkeypatch):
    sends = setup(tmp_path, monkeypatch)
    fp.ensure_seeded()
    logs = tmp_path / "live_review"
    logs.mkdir(exist_ok=True)

    class Git:
        def __init__(self, rows):
            self.rows = rows

        def __call__(self, *a, timeout=30):
            if a[0] == "fetch":
                return 0, ""
            if a[0] == "rev-parse":
                return 0, "a" * 40
            return 0, "\n".join(json.dumps(r) for r in self.rows)

    def dispatch(rid, ref):
        (logs / "applied.jsonl").write_text(json.dumps(ENTRY) + "\n")
        return {"exit": 0, "verdict": "dispatched", "lines": []}

    w.run_pass(git=Git([]), dispatch=dispatch, now_fn=lambda: T0, logs=logs)
    w.run_pass(git=Git([row()]), dispatch=dispatch, now_fn=lambda: T0, logs=logs)
    assert [s.split(":")[0] for s in sends] == [f"LTR FIRST PROOF {s}" for s in
                                                ("S2_call", "S3_tighten", "S4_pickup", "S5_approve",
                                                 "S6_sent", "S7_confirmed")]
