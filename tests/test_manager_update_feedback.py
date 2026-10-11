"""Operator feedback on the first live MANAGER update (2026-10-11 09:00Z), relayed by
the manager — one test per item, fixtures shaped like that day's real rows."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ops import research_digest as rd

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)


def _wdn():
    spec = importlib.util.spec_from_file_location("_wdn_fb", ROOT / "scripts/ops/work_digest_now.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. Needs-you holds ONLY operator decisions; decided wedges read as decided ──

PREP = {
    "priority": "normal",
    "receipt": {"ask_operator_open": 3},
    "msgs": [
        "🔎 1 research unit(s) newly need a read (needs_review):\n"
        "• RQ-20261010-008: base_oos_trades 0 < 39",
        "🧱 1 new blocker-watch finding(s) — act this turn:\n• STALE_BLOCK X: gone",
    ],
}


def test_needs_review_never_reaches_needs_you():
    needs, rops, watch = _wdn().route_attention(PREP)
    assert "RQ-20261010-008" not in needs and needs.startswith("🟢 No new decisions for you")
    assert "open ask_operator items: 3" in needs
    assert "RQ-20261010-008" in rops and "STALE_BLOCK" in watch


def test_genuine_asks_stay_in_needs_you_and_the_message_routes_sections():
    from scripts.ops import work_section as w

    prep = {**PREP, "msgs": ["❓ 1 new decision(s) for you (ask_operator):\n• PI-X: arm?"] + PREP["msgs"]}
    work = w.build(prev=None, now=NOW, git={"merged_prs": 0, "reverts": []},
                   snap={"rows": {}, "items": {}, "checklist_state": "read", "pipeline_state": "read"})
    msg = _wdn().compose_update("2026-10-11T09", prep, "", {}, {"error": "x"}, work)
    needs = msg[msg.index("Needs you"):msg.index("Research queue")]
    assert "PI-X: arm?" in needs and "RQ-20261010-008" not in needs
    assert "For research-ops (not you)" in msg and "Manager watch" in msg
    assert len(msg) <= 4096


def test_a_wedge_the_operator_decided_renders_decided_not_as_an_ask():
    from src.runtime.hourly_report import wedge_lines

    sw = {"wedgeState": "read", "source": "ledger", "wedges": [
        {"account": "alpaca_paper", "symbol": "GLD", "side": "long",
         "first_seen": "2026-09-30T00:00:00Z", "detail": "zombie OCO"}]}
    decided = [{"id": "PI-20260930-ZIFJ1RKM-0001",
                "text": "[money-path/paper] alpaca_paper GLD 39 sh long held by a ZOMBIE OCO",
                "reason": "Operator decision 2026-10-02: 'Mark it, keep going (Recommended)'"}]
    out = "\n".join(wedge_lines(sw, NOW, decided))
    assert "DECIDED (PI-20260930-ZIFJ1RKM-0001)" in out and "Mark it, keep going" in out
    assert "need OPERATOR" not in out
    undecided = "\n".join(wedge_lines(sw, NOW, []))
    assert "need OPERATOR or VENUE action" in undecided


# ── 2–4. research lines, attribution, consistent counts ──────────────────────

def _root(tmp_path):
    q = tmp_path / "research" / "queue"
    q.mkdir(parents=True)
    (q / "RQ-20261010-353c-01.yaml").write_text(
        "id: RQ-20261010-353c-01\n"
        "title: 'Stage-0 breadth for the prop book: trend harness on ZECUSDT 1h (RESEARCH-NIGHT-1010)'\n"
        "status: queued\n"
        f"last_dispatched_at: '{(NOW - timedelta(hours=10)).isoformat()}'\n"
        "decision_rule:\n  id: RULE-RQ-20261010-353c-01-TREND-ZECUSDT-1h-STAGE0\n"
        "  rule: PASS IF net_total_r > 0 AND n_trades >= 39 -- Stage-0 evidence only. FAIL IF "
        "net_total_r <= 0 AND n_trades >= 39 -- one pass; re-queues for a confirmatory run.\n")
    (q / "RQ-20261007-230.yaml").write_text(
        "id: RQ-20261007-230\ntitle: 'old unit'\nstatus: done\n"
        f"last_dispatched_at: '{(NOW - timedelta(days=3)).isoformat()}'\n")
    r = tmp_path / "research" / "results"
    (r / "RQ-20261010-353c-01").mkdir(parents=True)
    (r / "RQ-20261010-353c-01" / "1.jsonl").write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=9)).isoformat(), "note": "", "verdict": "pass",
        "power_state": "accruing", "research_unit": "RQ-20261010-353c-01",  # collapsed-state: accruing — fixture shaped like the 2026-10-11 rows
        "produced_by": {"run_id": "38092213492"},
        "measurement": {"net_total_r": 43.6911, "net_expectancy_r": 0.0658, "total_trades": 664}}) + "\n")
    (r / "_unattributed").mkdir()
    (r / "_unattributed" / "2.jsonl").write_text(
        json.dumps({"generated_at": (NOW - timedelta(hours=3)).isoformat(), "verdict": "fail",
                    "power_state": "accruing", "decision_rule": {"id": "RULE-R5-SOAK-BOOK-GRADE-v1"},  # collapsed-state: accruing — fixture
                    "produced_by": {"run_id": "777"},
                    "measurement": {"by_disposition": {"healthy": 0, "kill": 1}}}) + "\n"
        + json.dumps({"generated_at": (NOW - timedelta(hours=2)).isoformat(), "verdict": "fail"}) + "\n")
    return tmp_path


def test_research_lines_carry_the_finding_never_a_bare_dash(tmp_path):
    d = rd.build(root=_root(tmp_path), now=NOW)
    line = d["buckets"][rd.PASSED][0]
    assert line.startswith("RQ-20261010-353c-01 — trend harness on ZECUSDT 1h: pass")
    assert "net +43.69R" in line and "n=664" in line and "→ Stage-0 evidence only" in line
    assert "power accruing: —" not in rd.render_body(d)  # collapsed-state: accruing — fixture value; asserts the old bare-dash line is gone, no branch on state


def test_unattributed_rows_are_attributed_or_counted(tmp_path):
    d = rd.build(root=_root(tmp_path), now=NOW)
    fails = d["buckets"][rd.FAILED]
    assert any(f.startswith("R5-SOAK-BOOK-GRADE-v1: fail · healthy 0 · kill 1") for f in fails)
    assert not any("_unattributed" in f for f in fails)
    assert d["unattributed"] == 1
    assert "1 result row(s) name no unit, rule or tool — omitted" in rd.render_body(d)


def test_first_run_headline_counts_match_the_sections(tmp_path):
    d = rd.build(root=_root(tmp_path), now=NOW)
    h = rd.headline(d)
    n = sum(len(v) for v in d["buckets"].values())
    assert f"{n} result(s)" in h and n == 2
    assert d["transitions"]["run"] == ["RQ-20261010-353c-01 — fired " +
                                       (NOW - timedelta(hours=10)).isoformat()[:16]]
    assert "1 unit(s) fired" in h                       # not "0 run"
