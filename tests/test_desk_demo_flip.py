"""The bybit_1 demo flip (row DESK-SHORT-HOLD-LANE item 1; operator popup 2026-10-27, verbatim
"Yes, live on bybit_1 demo now (Recommended)").

What these pin, end to end without a venue:
* desk_write writes a proposal on a symbol the live claude_desk leg trades as a LIVE row (route submitted,
  intent_id, max_hold_min <= 60, market entry), and every other row stays shadow;
* desk intake admits it ONLY while every account rostering the leg is a demo account in
  MD-TRADE-DESK.functions.entry_generation.demo_accounts -- a real-money roster (bybit_2) closes the gate;
* the accepted proposal becomes ONE order package carrying BOTH brackets and its max hold;
* the leg's monitor closes the trade at market once max_hold_min has passed.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from scripts.ops import desk_intake as di
from src.units.strategies import claude_desk as cd

cdr = di.cdr
dw = cdr.desk_write
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(cdr.DECISION_SCHEMA.read_text())
NOW = datetime(2026, 10, 26, 9, 6, tzinfo=timezone.utc)
MANDATES = yaml.safe_load((ROOT / "config/mandates.yaml").read_text())
ACCOUNTS = yaml.safe_load((ROOT / "config/accounts.yaml").read_text())
LIVE_SCOPE = {"enabled": True, "execution": "live", "symbols": ["ETHUSDT"]}
DRAFT = {"action": "propose_entry", "session": "s", "confidence": "suggestive", "basis": "ev_positive", "judge_prior": 0.4,
         "rationale": "r", "weighed": [],
         "proposal": {"symbol": "ETHUSDT", "side": "long", "horizon_bars": 12,
                      "entry": {"type": "market", "level": 100.0, "good_till_bars": 2},
                      "stop": {"level": 97.0, "basis": "swing_level"},
                      "tp": {"level": 104.0, "basis": "swing_level", "p_hit": 0.4},
                      "expected_r_net": 0.1, "thesis": "t", "max_hold_min": 45}}


def _packet():
    return copy.deepcopy(cdr.GOOD_SCAN)


def _pointer(p):
    return {"packet_id": p["meta"]["packet_id"], "packet_sha": cdr.packet_sha(p)}


def compile_(draft=DRAFT, scope=LIVE_SCOPE):
    p = _packet()
    row = dw.compile_row(copy.deepcopy(draft), _pointer(p), p, SCHEMA, now=NOW, skill_sha=None, scope=scope)
    return row, p


def guard(row, p, tmp_path):
    (tmp_path / f"{p['meta']['packet_id']}.json").write_text(json.dumps(p))
    return cdr.decision_problems(row, SCHEMA, tmp_path)


# --------------------------------------------------------------------------- the writer

def test_leg_scope_reads_the_real_strategies_yaml_like_yaml_does():
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"]["claude_desk"]
    got = dw.leg_scope((ROOT / "config/strategies.yaml").read_text())
    assert got == {"enabled": cfg["enabled"], "execution": cfg["execution"], "symbols": cfg["symbols"]}
    assert dw.leg_scope(None) is None and dw.leg_scope("strategies:\n  other:\n    enabled: true\n") is None


def test_a_proposal_on_a_live_leg_symbol_is_a_live_submitted_row_the_guard_accepts(tmp_path):
    row, p = compile_()
    assert row["label_source"] == "live" and row["disposition"] == {"route": "submitted", "per_account": []}
    assert row["intent_id"] == "DI-" + row["decision_id"][3:] and row["proposal"]["max_hold_min"] == 45
    assert dw.row_problems(row, p, SCHEMA) == []
    assert guard(row, p, tmp_path) == []


@pytest.mark.parametrize("scope", [None, dict(LIVE_SCOPE, execution="shadow"), dict(LIVE_SCOPE, symbols=["AVAXUSDT"]),
                                   dict(LIVE_SCOPE, enabled=False)])
def test_everything_else_stays_a_shadow_row(scope, tmp_path):
    row, p = compile_(scope=scope)
    assert row["label_source"] == "shadow" and row["intent_id"] is None and row["disposition"]["route"] == "none"
    assert dw.row_problems(row, p, SCHEMA) == [] and guard(row, p, tmp_path) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["proposal"].pop("max_hold_min"), "max_hold_min is required"),
    (lambda d: d["proposal"].update(max_hold_min=90), "max_hold_min is required"),
    (lambda d: d["proposal"]["entry"].update(type="limit"), "enters at `market`"),
])
def test_a_live_proposal_must_be_the_short_hold_kind(mutate, needle, tmp_path):
    d = copy.deepcopy(DRAFT)
    mutate(d)
    row, p = compile_(draft=d)
    assert any(needle in x for x in dw.row_problems(row, p, SCHEMA))
    assert any(needle in x for x in guard(row, p, tmp_path))


# --------------------------------------------------------------------------- intake: the demo floor

def _with_desk_on(account):
    a = copy.deepcopy(ACCOUNTS)
    a["accounts"][account]["strategies"] = list(a["accounts"][account].get("strategies") or []) + ["claude_desk"]
    return a


def test_the_gate_admits_the_bybit_1_demo_and_refuses_a_real_money_roster():
    assert di.entry_gate(MANDATES, ACCOUNTS) is None  # rostered on bybit_1 only today
    why = di.entry_gate(MANDATES, _with_desk_on("bybit_2"))
    assert why.startswith(di.R_GATED) and "not_a_demo_account:bybit_2" in why
    assert di.entry_gate(MANDATES, None).endswith("accounts_unreadable")


def test_a_demo_list_cannot_admit_a_real_money_account():
    """demo_accounts is checked AGAINST config/accounts.yaml: listing bybit_2 does not make it a demo."""
    m = copy.deepcopy(MANDATES)
    fn = next(x for x in m["mandates"] if x["id"] == "MD-TRADE-DESK")["functions"]["entry_generation"]
    fn["demo_accounts"] = ["bybit_1", "bybit_2"]
    assert "not_a_demo_account:bybit_2" in di.entry_gate(m, _with_desk_on("bybit_2"))


class _Git:
    def __init__(self, rows, packet):
        self.rows, self.packet = rows, packet

    def __call__(self, *args, timeout=30):
        path = args[1].split(":", 1)[1]
        if path == di.DECISIONS_PATH:
            return 0, "\n".join(json.dumps(r) for r in self.rows)
        return 0, json.dumps(self.packet, sort_keys=True, separators=(",", ":"))


def _intake(tmp_path, row, p, accounts):
    di.run_pass("t" * 40, git=_Git([], p), now_fn=lambda: NOW, logs=tmp_path, mandates_fn=lambda: MANDATES,
                leg_fn=lambda: True, accounts_fn=lambda: accounts, symbols_fn=lambda: ["ETHUSDT"],
                apply_fn=lambda *a: {"exit": 0}, flag_fn=lambda line: None)  # seed
    di.run_pass("t" * 40, git=_Git([row], p), now_fn=lambda: NOW, logs=tmp_path, mandates_fn=lambda: MANDATES,
                leg_fn=lambda: True, accounts_fn=lambda: accounts, symbols_fn=lambda: ["ETHUSDT"],
                apply_fn=lambda *a: {"exit": 0}, flag_fn=lambda line: None)
    return [json.loads(x) for x in (tmp_path / "intake.jsonl").read_text().splitlines()]


def test_a_bybit_1_proposal_becomes_one_order_package_with_both_brackets(tmp_path):
    row, p = compile_()
    (rec,) = _intake(tmp_path, row, p, ACCOUNTS)
    assert rec["verdict"] == "accepted", rec
    queue = cd.read_queue(tmp_path / "accepted_proposals.jsonl")
    assert [q["decision_id"] for q in queue] == [row["decision_id"]]
    pkg, terminal = cd.select(queue, symbol="ETHUSDT", consumed=set(), now=NOW, cfg={"confidence": 0.5})
    assert terminal == [] and pkg is not None
    assert (pkg["direction"], pkg["entry"], pkg["sl"], pkg["tp"]) == ("long", 100.0, 97.0, 104.0)
    assert pkg["meta"]["decision_id"] == row["decision_id"] and pkg["meta"]["intent_id"] == row["intent_id"]
    assert pkg["meta"]["max_hold_min"] == 45
    # one package per decision: once a package carries the decision_id nothing more is emitted
    again, _ = cd.select(queue, symbol="ETHUSDT", consumed={row["decision_id"]}, now=NOW)
    assert again is None


def test_the_same_proposal_is_refused_when_a_real_money_account_carries_the_leg(tmp_path):
    row, p = compile_()
    (rec,) = _intake(tmp_path, row, p, _with_desk_on("bybit_2"))
    assert rec["verdict"] == "refused" and "not_a_demo_account:bybit_2" in rec["detail"]
    assert not (tmp_path / "accepted_proposals.jsonl").exists()


def test_a_symbol_the_leg_does_not_trade_is_refused_by_name():
    row, p = compile_()
    v, detail, _ = di.classify(row, problems=[], packet=p, gate=None, leg_rostered=True, leg_symbols=["AVAXUSDT"])
    assert v == "refused" and detail.startswith(di.R_SYMBOL + ":ETHUSDT")


# --------------------------------------------------------------------------- the leg's max hold

def test_monitor_closes_at_market_once_max_hold_has_passed():
    opened = NOW - timedelta(minutes=45)
    pkg = {"created_at": opened.isoformat(), "meta": json.dumps({"max_hold_min": 45})}
    assert cd.max_hold_verdict(pkg, NOW) == {"action": "close", "reason": "max_hold"}
    assert cd.max_hold_verdict(pkg, NOW - timedelta(minutes=1)) is None
    assert cd.max_hold_verdict({"created_at": opened.isoformat(), "meta": {}}, NOW) is None  # no max hold: bracket only
    assert cd.max_hold_verdict({"meta": {"max_hold_min": 45}}, NOW) is None  # unreadable open time: bracket holds
