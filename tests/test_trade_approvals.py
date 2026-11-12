"""TRADE-ACTION-DIRECT-PATH phase 1: Telegram Approve / Reject for operator-needed live-review recommendations.

Pins: which rows get a button; the 64-byte callback; one ask per review; the fail-closed chat check; decide-once;
expiry; Approve writes a VALID directed_action/v1 record into the spool; the spool pass runs it through the same
vm_pass (once), moves it to handled/, and a later git copy of it is never applied twice; the rows watcher offers
only for rows it did not execute.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from scripts.ops import directed_action as cli
from src.runtime import directed_actions as da
from src.runtime import trade_approvals as ta

NOW = datetime(2026, 11, 11, 22, 50, 13, tzinfo=timezone.utc)


def _row(action="close", route="operator_ask", mech="match", **rec) -> Dict[str, Any]:
    r = {"action": action, "basis": "ev_positive", "confidence": "measured", "ev_delta_r": 0.3574,
         "level": None, "reason": "Live state is a PULLBACK: close beats hold by +0.357R (n=75, net of full cost)."}
    r.update(rec)
    return {"review_id": "LR-20261111T2243Z-pkg-462cfc59b2a1469b", "order_package_id": "pkg-462cfc59b2a1469b",
            "leg": "ml_entry", "accounts": ["bybit_2", "bybit_portfolio"], "recommendation": r,
            "disposition": {"route": route}, "mechanics": {"verdict": mech}}


def _offer(tmp_path, row=None, **kw):
    sent = []
    res = ta.offer(row or _row(), send=lambda text, kb: sent.append((text, kb)) or True,
                   fallback=lambda t: False, now=kw.pop("now", NOW), root=tmp_path, **kw)
    return res, sent


# ─────────────────────────────────────────────── which rows get a button

@pytest.mark.parametrize("row,verdict,yes,why", [
    (_row(), "advice_only", True, "ok"),                                  # the 2026-11-11 ETH case
    (_row(route="recommended"), "advice_only", True, "ok"),              # advice-only recommended: needs the operator
    (_row(route="recommended"), None, False, "route_recommended"),       # the VM executes it itself
    (_row(route="none"), "advice_only", False, "route_none"),
    (_row(action="hold", route="none"), "not_dispatchable", False, "action_hold"),
    (_row(action="flag_mechanics", mech="mismatch"), "not_dispatchable", False, "action_flag_mechanics"),
    (_row(mech="mismatch"), "advice_only", False, "mechanics_mismatch"),
    (_row(mech="could_not_look"), "advice_only", True, "ok"),
    (_row(action="change_size"), "advice_only", False, "no_direct_executor"),
    (_row(action="move_tp"), "advice_only", False, "level_missing"),
    (_row(action="move_tp", level=78.964), "advice_only", True, "ok"),
    (_row(action="partial_close"), "advice_only", False, "size_fraction_missing"),
    (_row(action="partial_close", size_fraction=0.5), "advice_only", True, "ok"),
])
def test_wants_button(row, verdict, yes, why):
    assert ta.wants_button(row, verdict) == (yes, why)


def test_widen_maps_to_a_directed_move_sl_and_every_mapped_action_is_a_directed_action():
    assert ta.directed_fields(_row(action="widen_sl", level=3100.0)) == {"action": "move_sl", "level": 3100.0}
    assert set(ta.ACTION_MAP.values()) <= set(da.ACTIONS)


def test_callback_data_fits_telegram_and_round_trips():
    kb = ta.keyboard("0123456789")
    cbs = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert cbs == ["tapv:a:0123456789", "tapv:r:0123456789"]
    assert all(len(c.encode()) <= 64 and ta.CB_RE.match(c) for c in cbs)


# ─────────────────────────────────────────────── offer

def test_offer_sends_one_ask_per_review_with_the_evidence(tmp_path):
    res, sent = _offer(tmp_path)
    assert res["state"] == "offered" and res["sent"] is True and len(sent) == 1
    text, kb = sent[0]
    assert "CLOSE the position" in text and "+0.357R" in text and "bybit_2, bybit_portfolio" in text
    assert "expires 23:05Z" in text                       # default 15 min
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"tapv:a:{res['token']}"
    again, sent2 = _offer(tmp_path)
    assert again == {"state": "already_offered", "token": res["token"]} and sent2 == []
    journal = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text().splitlines()]
    assert [j["event"] for j in journal] == ["offered"] and journal[0]["sent"] is True


def test_offer_without_an_answerable_bot_falls_back_to_a_plain_alert(tmp_path):
    alerts = []
    res = ta.offer(_row(), vm_verdict="advice_only", send=lambda t, k: False,
                   fallback=lambda t: alerts.append(t) or True, now=NOW, root=tmp_path)
    assert res["sent"] is False and res["fallback_alert"] is True and len(alerts) == 1


def test_offer_never_raises(tmp_path):
    res = ta.offer({"recommendation": "garbage", "disposition": {"route": "operator_ask"}}, root=tmp_path)
    assert res["state"] in ("error", "not_offered")


def test_expiry_knob_falls_back_to_default_on_garbage(monkeypatch):
    monkeypatch.setenv("TRADE_APPROVAL_EXPIRY_MIN", "abc")
    assert ta.expiry_minutes() == ta.DEFAULT_EXPIRY_MIN
    monkeypatch.setenv("TRADE_APPROVAL_EXPIRY_MIN", "0")
    assert ta.expiry_minutes() == ta.DEFAULT_EXPIRY_MIN
    monkeypatch.setenv("TRADE_APPROVAL_EXPIRY_MIN", "5")
    assert ta.expiry_minutes() == 5.0


# ─────────────────────────────────────────────── decide

def _spooled(tmp_path):
    d = ta.spool_root(tmp_path) / da.RECORDS_DIR
    return sorted(d.glob("*.json")) if d.is_dir() else []


def test_unauthorised_chat_decides_nothing(tmp_path):
    res, _ = _offer(tmp_path, vm_verdict="advice_only")
    out = ta.handle_callback(f"tapv:a:{res['token']}", authorised=False, now=NOW, root=tmp_path)
    assert out["outcome"] == "unauthorized" and _spooled(tmp_path) == []
    assert ta.read_pending(tmp_path)["asks"][res["token"]]["state"] == "pending"


def test_approve_writes_one_valid_directed_record_and_decides_once(tmp_path):
    res, _ = _offer(tmp_path, vm_verdict="advice_only")
    t = NOW + timedelta(minutes=2)
    out = ta.handle_callback(f"tapv:a:{res['token']}", authorised=True, now=t, root=tmp_path)
    assert out["outcome"] == "approved"
    files = _spooled(tmp_path)
    assert len(files) == 1
    rec = json.loads(files[0].read_text())
    assert da.problems(rec, path=da.record_path(rec["id"])) == []
    assert rec["action"] == "close" and rec["scope"] == "package" and rec["dry_run"] is False
    assert rec["directed_by"] == "operator:telegram" and res["token"] in rec["operator_quote"]
    assert rec["order_package_id"] == "pkg-462cfc59b2a1469b" and rec["id"] == out["record_id"]
    # a second tap (or the Reject button after Approve) does nothing
    for raw in (f"tapv:a:{res['token']}", f"tapv:r:{res['token']}"):
        again = ta.handle_callback(raw, authorised=True, now=t, root=tmp_path)
        assert again["outcome"] == "already_approved"
    assert len(_spooled(tmp_path)) == 1


def test_reject_and_expiry_execute_nothing(tmp_path):
    res, _ = _offer(tmp_path, vm_verdict="advice_only")
    out = ta.handle_callback(f"tapv:r:{res['token']}", authorised=True, now=NOW, root=tmp_path)
    assert out["outcome"] == "rejected" and _spooled(tmp_path) == []

    row2 = _row()
    row2["review_id"] = "LR-20261111T2235Z-pkg-6df5f9dfb83e47b8"
    res2, _ = _offer(tmp_path, row=row2, vm_verdict="advice_only")
    late = NOW + timedelta(minutes=16)
    out2 = ta.handle_callback(f"tapv:a:{res2['token']}", authorised=True, now=late, root=tmp_path)
    assert out2["outcome"] == "expired" and _spooled(tmp_path) == []


def test_unknown_and_foreign_callbacks(tmp_path):
    assert ta.handle_callback("wdec:abc:def", authorised=True, root=tmp_path) is None
    assert ta.handle_callback("tapv:x:zz", authorised=True, root=tmp_path)["outcome"] == "refused"
    assert ta.handle_callback("tapv:a:0123456789", authorised=True, root=tmp_path)["outcome"] == "unknown"


# ─────────────────────────────────────────────── the spool pass (same vm_pass, once)

def test_spool_pass_applies_once_moves_to_handled_and_a_git_copy_never_replays(tmp_path):
    root, logs = tmp_path / "ta", tmp_path / "logs"
    res = ta.offer(_row(), vm_verdict="advice_only", send=lambda t, k: True, fallback=lambda t: False,
                   now=NOW, root=root)
    tap = NOW + timedelta(seconds=30)
    ta.handle_callback(f"tapv:a:{res['token']}", authorised=True, now=tap, root=root)
    calls, pings = [], []

    def _apply(rec):
        calls.append(rec["id"])
        return {"exit": 0, "resolved_action": rec["action"], "symbol": "ETHUSDT",
                "accounts": [{"account_id": "bybit_2", "executed": True,
                              "executor": {"result": "applied", "venue_after": None}}]}

    kw = dict(apply_fn=_apply, ping=lambda r, s, v: pings.append(v), now_fn=lambda: tap + timedelta(seconds=3),
              logs=logs)
    st = cli.spool_pass(ta.spool_root(root), **kw)
    assert st["handled"] == 1 and st["spool_moved"] == 1 and len(calls) == 1 and pings == ["applied"]
    assert _spooled(root) == [] and len(list((ta.spool_root(root) / "handled").glob("*.json"))) == 1
    receipt = json.loads((logs / "receipts.jsonl").read_text().splitlines()[0])
    assert receipt["verdict"] == "applied" and receipt["approval_token"] == res["token"]
    assert receipt["created_to_done_s"] == 3.0
    # an exported git copy of the same record is seen already: the git pass applies nothing
    rec = json.loads(next((ta.spool_root(root) / "handled").glob("*.json")).read_text())
    files = {da.record_path(rec["id"]): json.dumps(rec)}

    def _git(*args, **_):
        if args[0] == "ls-tree":
            return 0, "\n".join(files)
        return 0, files[args[1].split(":", 1)[1]]

    st2 = cli.vm_pass("tip", git=_git, **kw)
    assert st2["handled"] == 0 and len(calls) == 1


def test_spool_git_shim_on_an_empty_spool(tmp_path):
    g = cli.spool_git(tmp_path)
    assert g("ls-tree", "--name-only", "spool", f"{da.RECORDS_DIR}/") == (0, "")
    assert g("fetch")[0] == 1


# ─────────────────────────────────────────────── the watcher hook and the directed loop cadence

def test_spool_due():
    from src.runtime import live_review_rows_watch as w
    assert w.spool_due((), (), 999) is False
    assert w.spool_due(("a.json",), (), 0) is True                 # a new approval: run now
    assert w.spool_due(("a.json",), ("a.json",), 1) is False       # still pending: wait a full poll
    assert w.spool_due(("a.json",), ("a.json",), da.POLL_S) is True


def test_rows_watcher_offers_only_for_rows_it_did_not_execute(tmp_path, monkeypatch):
    from src.runtime import live_review_rows as rows_lib
    from src.runtime import live_review_rows_watch as w

    close_ask = _row()
    held = _row(action="hold", route="none")
    held["review_id"] = "LR-20261111T2245Z-pkg-3de13868d406447a"
    rows = [close_ask, held]
    seen_state = {"seeded_at": NOW.isoformat(), "seen": [], "pending": {}, "tip_rows": 0}
    (tmp_path / "rows_watch_state.json").write_text(json.dumps(seen_state))
    monkeypatch.setattr(rows_lib, "read_at", lambda tip, git: {"state": "ok", "rows": rows, "legacy_rows": 0,
                                                               "file_rows": 2, "bad_lines": 0, "bad_files": []})
    monkeypatch.setattr(w, "_proof", lambda fn: None)
    offered = []

    def _offer_fn(row, verdict):
        offered.append((row["review_id"], verdict))
        return ta.wants_button(row, verdict)[0] and {"state": "offered", "token": "t"} or {"state": "not_offered"}

    w.run_pass(git=lambda *a, **k: (0, "tip"), dispatch=lambda rid, tip: pytest.fail("must not dispatch"),
               now_fn=lambda: NOW, logs=tmp_path, alert=lambda t: True, offer=_offer_fn)
    lines = [json.loads(x) for x in (tmp_path / "rows_watch.jsonl").read_text().splitlines()]
    by = {ln["review_id"]: ln for ln in lines}
    assert by[close_ask["review_id"]]["verdict"] == "advice_only"
    assert by[close_ask["review_id"]]["approval"] == {"state": "offered", "token": "t"}
    assert "approval" not in by[held["review_id"]]
