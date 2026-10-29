"""TRADE-ACTION-FAST-PATH: operator/manager-directed trade actions, applied by the VM watcher with no PR.

Operator 2026-10-29 ~08:20Z, verbatim: "It looks like we also need a fast track for trade updates - not really
sure why these require a PR at all, but the action needs to be immediate". These tests pin the record schema,
the refusal of a record without the operator's verbatim quote, per-account / per-trade targeting (the other
legs untouched, the shared package stop never moved), idempotency per record id, dry run (every account
decides, nothing executes, no ping), and the watcher's directed pass. The apply itself is
``live_review_apply.run()``: the same per-account RiskManager and executors as every live-review apply.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from scripts.ops import directed_action as cli
from scripts.ops import live_review_apply as lra
from src.runtime import directed_actions as da
from src.runtime import live_review_intent as lri
from src.runtime import live_review_rows_watch as watch
from tests.test_live_review_apply import ACCOUNTS, PKG, STRATS, _ApplyDB, _intent, _trade
from tests.test_live_review_apply import wired as wired  # noqa: F401  (fixture reuse)

NOW = datetime(2026, 10, 29, 8, 30, 0, tzinfo=timezone.utc)
QUOTE = "move the ADA stop to 0.21 now"


def _record(**kw) -> Dict[str, Any]:
    base = {"schema": da.SCHEMA, "id": "DA-20261029T082900Z-tighten_sl-a1b2c3",
            "created_at": "2026-10-29T08:29:00Z", "directed_by": "manager:session_x for operator",
            "operator_quote": QUOTE, "order_package_id": "pkg-465a5d7d27644027", "scope": "package",
            "action": "tighten_sl", "level": 0.21, "dry_run": False}
    base.update(kw)
    return base


# ------------------------------------------------------------------ schema

def test_a_complete_record_is_valid_and_its_file_name_must_be_its_id():
    r = _record()
    assert da.problems(r) == []
    assert da.problems(r, path=da.record_path(r["id"])) == []
    assert "schema:file_name_differs_from_id" in da.problems(r, path="comms/directed_actions/other.json")


@pytest.mark.parametrize("quote", [None, "", "   "])
def test_a_record_without_the_operators_verbatim_quote_is_refused_naming_it(quote):
    r = _record(operator_quote=quote)
    probs = da.problems(r)
    assert probs and probs[0] == da.R_NO_QUOTE
    r.pop("operator_quote")
    assert da.problems(r)[0] == da.R_NO_QUOTE


@pytest.mark.parametrize("kw, want", [
    ({"action": "widen_sl"}, "schema:action_not_in"),
    ({"action": "move_tp", "level": None}, "schema:level_required_for_move_tp"),
    ({"action": "close", "level": 0.2}, "schema:level_not_used_by_close"),
    ({"action": "partial_close", "level": None, "fraction": 1.0}, "schema:fraction_in_(0,1)"),
    ({"action": "partial_close", "level": None}, "schema:fraction_in_(0,1)"),
    ({"dry_run": "yes"}, "schema:dry_run_must_be_true_or_false"),
    ({"directed_by": ""}, "schema:directed_by"),
    ({"order_package_id": "P"}, "schema:order_package_id"),
    ({"id": "LR-x"}, "schema:id"),
    ({"created_at": "soon"}, "schema:created_at"),
    ({"scope": {"trade_id": 7}}, "schema:scope_is_package_or_an_account"),
    ({"scope": {"account_id": "bybit_2", "size": 1}}, "schema:scope_keys"),
])
def test_schema_problems_are_named(kw, want):
    probs = da.problems(_record(**kw))
    assert any(p.startswith(want) for p in probs), probs


def test_valid_actions_and_scopes():
    assert da.problems(_record(action="close", level=None)) == []
    assert da.problems(_record(action="partial_close", level=None, fraction=0.5)) == []
    assert da.problems(_record(action="move_tp", level=0.19, scope={"account_id": "bybit_2"})) == []
    assert da.problems(_record(action="move_sl", scope={"account_id": "bybit_2", "trade_id": 7})) == []
    assert da.scope_of(_record()) == {"account_id": None, "trade_id": None}
    assert da.scope_of(_record(scope={"account_id": "bybit_2", "trade_id": 7})) == {"account_id": "bybit_2",
                                                                                    "trade_id": "7"}


def test_move_sl_resolves_to_a_tighten_or_a_widen_against_the_package_stop():
    assert da.resolve_action(_record(action="move_sl", level=0.21), 0.22, "short") == "tighten_sl"
    assert da.resolve_action(_record(action="move_sl", level=0.23), 0.22, "short") == "widen_sl"
    assert da.resolve_action(_record(action="move_sl", level=0.23), 0.22, "long") == "tighten_sl"
    assert da.resolve_action(_record(action="move_sl", level=0.22), 0.22, "short") is None
    assert da.resolve_action(_record(action="move_sl", level=0.22), None, "short") is None
    assert da.resolve_action(_record(action="close"), 0.22, "short") == "close"


def test_staleness():
    r = _record()
    assert not da.is_stale(r, NOW)
    assert da.is_stale(r, NOW + timedelta(seconds=da.STALE_S + 120))


def test_submit_builds_a_record_the_vm_validator_accepts():
    import argparse
    a = argparse.Namespace(scope="bybit_2:41", quote=QUOTE, quote_file=None, action="partial_close",
                           directed_by="manager", package="pkg-abc", dry_run=True, level=None, fraction=0.5)
    r = cli.build_record(a, NOW)
    assert r["scope"] == {"account_id": "bybit_2", "trade_id": "41"} and r["dry_run"] is True
    assert da.ID_RE.match(r["id"]) and da.problems(r, path=da.record_path(r["id"])) == []


# ------------------------------------------------------- through live_review_apply.run

def _directed(**kw) -> lri.LiveReviewIntent:
    base = dict(mandate=None, bar_ts=None, basis=None, mechanics_verdict=None, evidence_path=None,
                expected_cost_r=None, worst_case_delta_r=None, review_id="DA-20261029T082900Z-tighten_sl-a1b2c3",
                directed_by="manager", operator_quote=QUOTE)
    base.update(kw)
    return _intent(**base)


def _run(db, intent, *, apply=True, granted=frozenset()):
    return lra.run(intent, apply=apply, db=db, accounts=ACCOUNTS, strategies=STRATS,
                   review_cfg={"apply_mode": "apply"}, granted=set(granted), write_log=False, state={})


def test_directed_needs_no_mandate_and_each_account_still_decides(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    wired["dry"].add("bybit_portfolio")
    res = _run(db, _directed())
    by = {a["account_id"]: a for a in res["accounts"]}
    assert by["bybit_2"]["executed"] is True and wired["exec"] == [("bybit", "bybit_2", 0.21)]
    assert by["bybit_portfolio"]["reason"] == lri.R_DRY           # the account's OWN RiskManager refused
    assert res["mandate_precondition"] is None


def test_the_per_leg_trade_update_ping_is_silent_for_a_directed_intent(monkeypatch):
    """A directed record pings ONCE per record (directed_action.py), never once per leg."""
    from src.runtime import execution_diagnostics
    sent: List[Any] = []
    monkeypatch.setattr(execution_diagnostics, "enqueue_trade_update", lambda **kw: sent.append(kw))
    lra._ping(PKG, "bybit_2", 0.21, _directed())
    assert sent == []
    lra._ping(PKG, "bybit_2", 0.21, _intent())
    assert len(sent) == 1


def test_directed_without_a_quote_executes_nothing(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    res = _run(db, _directed(operator_quote="  "))
    assert wired["exec"] == [] and res["exit"] == lra.EXIT_REFUSED
    assert res["mandate_precondition"] == f"directed:{da.R_NO_QUOTE}"


def test_an_undirected_intent_without_a_mandate_is_still_refused(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    res = _run(db, _directed(directed_by=None, operator_quote=None))
    assert wired["exec"] == [] and "not granted" in res["accounts"][0]["executor"]["detail"]


def test_directed_keeps_every_existing_guard(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    assert _run(db, _directed(new_sl=0.2300))["accounts"][0]["reason"] == lri.R_LOOSENS
    clip = _run(db, _directed(new_sl=0.2010))["accounts"][0]       # the noise floor still clips
    assert clip["verdict"] == "clip" and clip["level"] == pytest.approx(0.2040)


def test_directed_is_not_bound_by_the_reviewers_one_action_per_bar_guard(wired):
    db = _ApplyDB([_trade(1, "bybit_2")], PKG)
    db.trades[0]["notes"] = json.dumps({"sl_amends": [{"source": lri.PROVENANCE, "bar": "2026-10-29T08:00:00Z"}]})
    reviewer = _run(db, _intent(bar_ts="2026-10-29T08:00:00Z"), granted={lri.MANDATE_ID})
    assert reviewer["accounts"][0]["reason"] == lri.R_RATE
    assert _run(db, _directed())["accounts"][0]["executed"] is True


def test_account_scope_touches_only_that_accounts_leg_and_never_the_package_stop(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    res = _run(db, _directed(target_account_id="bybit_portfolio"))
    assert [a["account_id"] for a in res["accounts"]] == ["bybit_portfolio"]
    assert wired["exec"] == [("bybit", "bybit_portfolio", 0.21)]
    assert res["package_sl_moved"] is False and db.package_writes == []
    unscoped = _run(_ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG), _directed())
    assert unscoped["package_sl_moved"] is True


def test_trade_scope_picks_one_leg_and_a_scope_matching_nothing_is_refused(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(5, "bybit_2")], PKG)
    res = _run(db, _directed(target_account_id="bybit_2", target_trade_id="5"))
    assert [a["trade_id"] for a in res["accounts"]] == [5]
    none = _run(db, _directed(target_account_id="bybit_9"))
    assert none["exit"] == lra.EXIT_REFUSED and none["detail"].startswith(da.R_SCOPE_EMPTY)


def test_scoped_close_closes_one_leg_only(wired, monkeypatch):
    sent: List[Any] = []
    monkeypatch.setattr(lra, "_exec_trade_action", lambda db, leg, pkg, cls, v, intent:
                        sent.append((leg["account_id"], intent.action)) or {"result": lra.X_APPLIED})
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    res = _run(db, _directed(action="close", new_sl=None, target_account_id="bybit_2"))
    assert sent == [("bybit_2", "close")] and res["accounts"][0]["executed"] is True


def test_directed_dry_run_decides_per_account_and_executes_nothing(wired):
    db = _ApplyDB([_trade(1, "bybit_2"), _trade(2, "bybit_portfolio")], PKG)
    res = _run(db, _directed(), apply=False)
    assert {a["verdict"] for a in res["accounts"]} == {"approve"}
    assert wired["exec"] == [] and db.trade_writes == []


# ------------------------------------------------------------------ the VM pass

class _Branch:
    """A fake ``git`` over one pinned tip holding record files."""

    def __init__(self, files: Dict[str, Any]):
        self.files = {p: (c if isinstance(c, str) else json.dumps(c)) for p, c in files.items()}

    def __call__(self, *args, **_kw):
        if args[0] == "ls-tree":
            return 0, "\n".join(sorted(self.files))
        if args[0] == "show":
            path = args[1].split(":", 1)[1]
            return (0, self.files[path]) if path in self.files else (128, "missing")
        return 1, "unexpected"


def _pass(tmp_path, files, *, apply_fn=None, now=NOW):
    calls, pings = [], []

    def _apply(rec):
        calls.append(rec["id"])
        return (apply_fn or (lambda r: {"exit": 0, "resolved_action": r["action"], "symbol": "ADAUSDT",
                                        "accounts": [{"account_id": "bybit_2", "verdict": "approve",
                                                      "executed": not r["dry_run"], "level": 0.21,
                                                      "executor": {"result": "applied", "venue_after": 0.21}}]}))(rec)
    st = cli.vm_pass("tip1", git=_Branch(files), apply_fn=_apply, now_fn=lambda: now, logs=tmp_path,
                     ping=lambda rec, res, verdict: pings.append((rec.get("id"), verdict)))
    receipts = [json.loads(ln) for ln in (tmp_path / "receipts.jsonl").read_text().splitlines()] \
        if (tmp_path / "receipts.jsonl").exists() else []
    return st, calls, pings, receipts


def _files(*records):
    return {da.record_path(r["id"]): r for r in records}


def test_vm_pass_applies_once_with_one_receipt_and_one_ping(tmp_path):
    r = _record()
    st, calls, pings, receipts = _pass(tmp_path, _files(r))
    assert calls == [r["id"]] and pings == [(r["id"], "applied")]
    assert len(receipts) == 1 and receipts[0]["verdict"] == "applied"
    assert receipts[0]["accounts"][0]["executor"]["venue_after"] == 0.21
    assert receipts[0]["created_to_done_s"] == 60.0 and st["exit"] == 0
    # idempotent per id: the same tip again (or a later tip still carrying it) does nothing
    st2, calls2, pings2, receipts2 = _pass(tmp_path, _files(r))
    assert calls2 == [] and pings2 == [] and len(receipts2) == 1 and st2["handled"] == 0


def test_vm_pass_refuses_a_record_without_a_quote_and_pings_the_refusal(tmp_path):
    r = _record(operator_quote="")
    _, calls, pings, receipts = _pass(tmp_path, _files(r))
    assert calls == [] and receipts[0]["verdict"] == "refused"
    assert receipts[0]["detail"].startswith(da.R_NO_QUOTE) and pings == [(r["id"], "refused")]


def test_vm_pass_dry_run_records_every_decision_without_a_ping(tmp_path):
    r = _record(dry_run=True)
    st, calls, pings, receipts = _pass(tmp_path, _files(r))
    assert calls == [r["id"]] and pings == [] and receipts[0]["verdict"] == "dry_run"
    assert receipts[0]["accounts"][0]["executed"] is False and st["exit"] == 0


def test_vm_pass_refuses_a_stale_record(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"seen": {}, "pending": {}}))
    r = _record(created_at="2026-10-29T07:00:00Z")
    _, calls, _, receipts = _pass(tmp_path, _files(r))
    assert calls == [] and receipts[0]["detail"].startswith(da.R_STALE)


def test_first_ever_pass_seeds_old_records_but_applies_fresh_ones(tmp_path):
    old = _record(id="DA-20261029T060000Z-close-000001", action="close", level=None,
                  created_at="2026-10-29T06:00:00Z")
    fresh = _record()
    st, calls, _, receipts = _pass(tmp_path, _files(old, fresh))
    assert calls == [fresh["id"]] and [x["id"] for x in receipts] == [fresh["id"]] and st["seeded"] is True
    assert json.loads((tmp_path / "state.json").read_text())["seen"][old["id"]]["verdict"] == "seeded"


def test_could_not_look_is_retried_then_expires(tmp_path):
    r = _record()
    cnl = lambda rec: {"exit": 3, "detail": "venue read failed", "accounts": []}  # noqa: E731
    st, calls, pings, receipts = _pass(tmp_path, _files(r), apply_fn=cnl)
    assert calls == [r["id"]] and receipts == [] and pings == [] and st["exit"] == 3 and st["pending"] == [r["id"]]
    st, calls, pings, receipts = _pass(tmp_path, _files(r), apply_fn=cnl, now=NOW + timedelta(seconds=30))
    assert calls == [r["id"]] and receipts == []
    st, calls, pings, receipts = _pass(tmp_path, _files(r), apply_fn=cnl,
                                       now=NOW + timedelta(seconds=da.RETRY_WINDOW_S + 1))
    assert receipts[0]["verdict"] == "expired" and pings == [(r["id"], "expired")] and st["pending"] == []


def test_partially_applied_and_not_applied_verdicts():
    rec = _record()
    two = {"accounts": [{"executed": True}, {"executed": False}]}
    assert cli.verdict_of(rec, two) == "partially_applied"
    assert cli.verdict_of(rec, {"accounts": [{"executed": False}]}) == "not_applied"
    assert cli.verdict_of(rec, {"accounts": []}) == "not_applied"


def test_apply_record_builds_a_directed_scoped_intent_without_a_bar(monkeypatch):
    seen: Dict[str, Any] = {}
    pkg = dict(PKG, order_package_id="pkg-465a5d7d27644027")
    monkeypatch.setattr(lra, "_open_db", lambda: object())
    monkeypatch.setattr(lra, "_get_package", lambda db, pid: pkg)
    monkeypatch.setattr(lra, "_strategies", lambda: STRATS)
    monkeypatch.setattr(lra, "_accounts", lambda: ACCOUNTS)
    monkeypatch.setattr(lra, "market_state", lambda p, s: {"mark": 0.2, "atr": 0.004, "bar_ts": "B"})
    monkeypatch.setattr(lra, "run", lambda intent, **kw: seen.update(intent=intent, **kw) or
                        {"exit": 0, "accounts": []})
    out = cli._apply_record(_record(action="move_sl", level=0.23, scope={"account_id": "bybit_2", "trade_id": 4},
                                    dry_run=True))
    it = seen["intent"]
    assert out["resolved_action"] == "widen_sl" and it.action == "widen_sl" and it.new_sl == 0.23
    assert it.bar_ts is None and it.directed_by and it.operator_quote == QUOTE and it.mandate is None
    assert (it.target_account_id, it.target_trade_id) == ("bybit_2", "4") and seen["apply"] is False
    assert it.review_id == _record()["id"]


# ------------------------------------------------------------------ the watcher

def test_directed_watch_runs_the_pass_only_when_the_tip_moves_or_a_record_is_pending(tmp_path):
    tips = iter(["t1", "t1", "t2", "t2"])
    ran: List[str] = []

    def git(*args, **_kw):
        if args[0] == "fetch":
            return 0, ""
        return 0, next(tips)
    exits = iter([0, 3, 0])

    def vm_pass(tip):
        ran.append(tip)
        return {"exit": next(exits)}
    for _ in range(4):
        watch.run_directed_pass(git=git, vm_pass=vm_pass, now_fn=lambda: NOW, logs=tmp_path)
    assert ran == ["t1", "t2", "t2"]          # t1 unchanged once; t2 re-run after a could-not-look


def test_directed_watch_names_an_absent_branch(tmp_path):
    st = watch.run_directed_pass(git=lambda *a, **k: (128, "fatal: couldn't find remote ref refs/heads/directed/actions"),
                                 vm_pass=lambda tip: pytest.fail("must not run"), now_fn=lambda: NOW, logs=tmp_path)
    assert st["fetch_state"] == "branch_absent"


def test_the_diag_receipts_are_registered():
    from src.web.api.routers import diag
    for name, rel in (("directed_actions", "runtime_logs/directed_actions/receipts.jsonl"),
                      ("directed_actions_status", "runtime_logs/directed_actions/pass_status.json"),
                      ("directed_actions_watch_status", "runtime_logs/directed_actions/watch_status.json")):
        assert str(diag._LOG_FILES[name]).endswith(rel)


def test_push_record_adds_exactly_one_file_on_a_real_repo(tmp_path, monkeypatch):
    """The git plumbing against a real bare remote: orphan create, then a second record on top, create-only."""
    import subprocess
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(remote)], check=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    monkeypatch.setattr(cli, "_REPO_ROOT", str(work))
    git = lambda *a, **k: cli._git(*a, **{**k, "env": {**env, **(k.get("env") or {})}})  # noqa: E731
    r1, r2 = _record(), _record(id="DA-20261029T082901Z-close-ffffff", action="close", level=None)
    ok, c1 = cli.push_record(r1, git=git, tries=1)
    assert ok, c1
    ok, c2 = cli.push_record(r2, git=git, tries=1)
    assert ok, c2
    names = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "refs/heads/directed/actions"],
                           capture_output=True, text=True, check=True).stdout.split()
    assert names == sorted([da.record_path(r1["id"]), da.record_path(r2["id"])])
    ok, why = cli.push_record(r1, git=git, tries=1)
    assert not ok and "create-only" in why
