"""DESK-SHORT-HOLD-LANE: the lane's only write path (.claude/skills/trading-desk/short_hold_write.py)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("short_hold_write", REPO / ".claude/skills/trading-desk/short_hold_write.py")
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)
sys.path.insert(0, str(REPO / "scripts" / "ci"))
import check_live_review_records as guard  # noqa: E402

SCHEMA = json.loads((REPO / "comms/schema/live_review.schema.json").read_text())
NOW = datetime(2026, 10, 27, 9, 6, 0, tzinfo=timezone.utc)
PKG = "pkg-eth1"


def envelope(side="long", verdict="match"):
    packet = {
        "review_id": f"LR-20261027T0905Z-{PKG}", "order_package_id": PKG, "leg": "ict_scalp_eth_15m",
        "info_cutoff_at": "2026-10-27T09:05:20Z",
        "context": {"direction": side, "symbol": "ETHUSDT"},
        "state": {"open_r": 0.4, "peak_r": 0.6, "peak_provenance": "estimated", "giveback_r": 0.2, "bars_held": 2,
                  "sl": 2390.0 if side == "long" else 2410.0, "tp": 2430.0 if side == "long" else 2370.0,
                  "atr_now_over_entry": 1.1, "regime_cell_now": None, "regime_cell_entry": None},
        "features_at_review": {"open_r": 0.4, "peak_r": 0.6, "giveback_r": 0.2},
        "mechanics": {"verdict": verdict, "evidence": "sl/tp agree"},
        "priced_options": {"source": f"comms/live_review/tables/LR-20261027T0905Z-{PKG}.json", "options": [
            {"action": "hold", "n": 12, "n_floor": 20, "state": "insufficient_n", "mean_r": None, "sd_r": None, "worst_r": None},
            {"action": "tighten", "n": 0, "state": "insufficient_n", "mean_r": None}]},
        "account_bounds": [{"account_id": "bybit_1", "account_class": "paper", "evidence": "bybit_orders ok",
                            "read": None, "read_if_amend": "would_apply"}],
        "short_hold": {"bar": "2026-10-27T09:00:00Z", "bar_close": "2026-10-27T09:05:00Z", "mark": 2404.0, "atr": 3.0},
        "missing_inputs": [],
    }
    return {"order_package_id": PKG, "bar": "2026-10-27T09:00:00Z", "bar_close": "2026-10-27T09:05:00Z",
            "built_at": "2026-10-27T09:05:25Z", "packet": packet, "packet_sha": sw.packet_sha(packet),
            "table_path": packet["priced_options"]["source"], "table": {"rows": []},
            "short_hold": packet["short_hold"], "closed": False}


EC = {"query_or_url": "https://example.org/funding", "source": "venue funding page", "retrieved_at": "2026-10-27T09:05:50Z",
      "extracted": {"funding_rate_8h": 0.0003}, "why_packet_insufficient": "packet carries no funding", "influence": "supporting"}


def draft(**kw):
    d = {"action": "hold", "reason": "5m higher lows intact", "judgement_confidence": 0.6, "confidence": "anecdote",
         "session": "session_X"}
    d.update(kw)
    return d


def valid(row, env):
    return guard.row_problems(row, "reviews", SCHEMA) + guard.packet_blob_problems(row, json.dumps(env["packet"]).encode())


@pytest.mark.parametrize("d,route,mandate", [
    (draft(), "none", None),
    (draft(action="tighten_sl", level=2398.0), "recommended", "MD-LIVE-TIGHTEN-SL"),
    (draft(action="move_tp", level=2440.0), "recommended", "MD-TRADE-DESK"),
    (draft(action="partial_close", size_fraction=0.5), "recommended", "MD-TRADE-DESK"),
    (draft(action="close"), "recommended", "MD-TRADE-DESK"),
    (draft(action="change_size", size_multiplier=1.5), "recommended", "MD-TRADE-DESK"),
])
def test_every_lane_action_compiles_to_a_row_the_guard_accepts(d, route, mandate):
    env = envelope()
    row = sw.compile_row(d, env, now=NOW)
    assert valid(row, env) == []
    assert row["disposition"]["route"] == route and row["disposition"]["mandate"] == mandate
    assert row["applied"] is False and row["model"] == sw.MODEL_TIER
    assert row["trigger"] == {"event": "short_hold", "level": "2026-10-27T09:00:00Z", "l0_snapshot_at": "2026-10-27T09:05:25Z"}
    assert row["account_reads"][0]["read"] == ("no_action" if d["action"] == "hold" else "would_apply")


def test_short_side_geometry():
    env = envelope(side="short")
    assert valid(sw.compile_row(draft(action="tighten_sl", level=2408.0), env, now=NOW), env) == []
    with pytest.raises(sw.Refused, match="loss side"):
        sw.compile_row(draft(action="tighten_sl", level=2400.0), env, now=NOW)


@pytest.mark.parametrize("d,why", [
    (draft(action="tighten_sl", level=2406.0), "loss side"),                 # above the mark on a long
    (draft(action="tighten_sl", level=2385.0), "does not tighten"),           # below the current stop: a widen
    (draft(action="tighten_sl"), "never removed"),                           # no level = removing a bracket
    (draft(action="move_tp", level=2400.0), "profit side"),
    (draft(action="partial_close", size_fraction=1.0), "size_fraction"),
    (draft(action="close", level=2400.0), "takes no level"),
    (draft(judgement_confidence=None), "judgement_confidence"),
    (draft(reason=""), "reason is required"),
    (draft(action="widen_sl", level=2380.0), "action must be one of"),
    (draft(review_id="LR-x"), "not allowed"),
    (draft(action="change_size", size_multiplier=1.0), "size_multiplier"),
    (draft(size_multiplier=2.0), "takes no size_multiplier"),
    (draft(external_context=[{"query_or_url": "q"}]), "must have exactly"),
    (draft(external_context=[dict(EC, influence="huge")]), "influence"),
    (draft(external_context=[dict(EC, retrieved_at="2026-10-27T09:30:00Z")]), "at or before the decision"),
])
def test_refusals(d, why):
    with pytest.raises(sw.Refused, match=why):
        sw.compile_row(d, envelope(), now=NOW)


def test_mechanics_mismatch_allows_only_flag_mechanics():
    env = envelope(verdict="mismatch")
    with pytest.raises(sw.Refused, match="flag_mechanics"):
        sw.compile_row(draft(), env, now=NOW)
    row = sw.compile_row(draft(action="flag_mechanics"), env, now=NOW)
    assert row["disposition"]["route"] == "operator_ask" and valid(row, env) == []


def test_corrupt_envelope_is_refused():
    env = envelope()
    env["packet_sha"] = "0" * 64
    with pytest.raises(sw.Refused, match="packet_sha"):
        sw.compile_row(draft(), env, now=NOW)


def test_brief_draft_example_uses_only_draft_keys_and_compiles():
    brief = (REPO / ".claude/skills/trading-desk/SHORT-HOLD-BRIEF.md").read_text()
    ex = json.loads(re.search(r'```json\n(\{"action".*?\})\n```', brief, re.S).group(1))
    assert set(ex) <= sw.DRAFT_KEYS and ex["action"] in sw.ACTIONS
    for a in sw.ACTIONS:
        assert f"`{a}`" in brief


# ----------------------------------------------------------------------------- end to end, local git remote

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def remote(tmp_path):
    origin, seed, lane = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "lane"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", str(seed))
    for a in (("config", "user.email", "t@t"), ("config", "user.name", "t")):
        _git(seed, *a)
    for rel in (sw.VALIDATOR, sw.SCHEMA):
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, seed / rel)
    _git(seed, "add", "-A"), _git(seed, "commit", "-qm", "main"), _git(seed, "push", "-q", str(origin), "HEAD:refs/heads/main")
    p = seed / sw.ENVELOPE.format(pkg=PKG)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(envelope()))
    _git(seed, "add", "-A"), _git(seed, "commit", "-qm", "env"), _git(seed, "push", "-q", str(origin), "HEAD:refs/heads/live-review/rows")
    _git(tmp_path, "clone", "-q", str(origin), str(lane))
    return {"origin": origin, "seed": seed, "lane": str(lane)}


def test_end_to_end_write_then_nothing_due(remote):
    code, rep = sw.run(draft(action="tighten_sl", level=2398.0), remote["lane"], PKG, now_fn=lambda: NOW)
    assert code == 0, rep
    tip = "origin/live-review/rows"
    _git(remote["lane"], "fetch", "-q", "origin")
    rows = [json.loads(x) for x in _git(remote["lane"], "show", f"{tip}:{sw.REVIEWS}").splitlines()]
    assert [r["recommendation"]["action"] for r in rows] == ["tighten_sl"]
    pkt = _git(remote["lane"], "show", f"{tip}:{sw.PACKETS.format(rid=rows[0]['review_id'])}")
    assert guard.packet_blob_problems(rows[0], pkt.encode()) == []
    lat = json.loads(_git(remote["lane"], "show", f"{tip}:{sw.LATENCY}"))
    assert lat["bar_close_to_decision_s"] == 60.0 and lat["packet_to_decision_s"] == 35.0
    code, rep = sw.run(draft(), remote["lane"], PKG, now_fn=lambda: NOW)
    assert code == 3 and rep["state"] == "nothing_due"


def test_dry_run_never_touches_reviews_jsonl(remote):
    code, rep = sw.run(draft(action="close"), remote["lane"], PKG, dry_run=True, now_fn=lambda: NOW)
    assert code == 0 and rep["file"] == sw.DRYRUN_REVIEWS
    _git(remote["lane"], "fetch", "-q", "origin")
    names = _git(remote["lane"], "ls-tree", "-r", "--name-only", "origin/live-review/rows").splitlines()
    assert sw.DRYRUN_REVIEWS in names and sw.REVIEWS not in names


def test_closed_envelope_stops_the_lane(remote):
    env = envelope()
    env["closed"], env["closed_at"] = True, "2026-10-27T09:20:00Z"
    p = remote["seed"] / sw.ENVELOPE.format(pkg=PKG)
    p.write_text(json.dumps(env))
    _git(remote["seed"], "commit", "-qam", "closed"), _git(remote["seed"], "push", "-q", str(remote["origin"]), "HEAD:refs/heads/live-review/rows")
    code, rep = sw.run(draft(), remote["lane"], PKG, now_fn=lambda: NOW)
    assert code == 3 and rep["state"] == "closed"


def test_external_context_goes_to_training_and_feed_gap_files(remote):
    code, rep = sw.run(draft(external_context=[EC]), remote["lane"], PKG, now_fn=lambda: NOW)
    assert code == 0, rep
    _git(remote["lane"], "fetch", "-q", "origin")
    tip = "origin/live-review/rows"
    (tr,) = [json.loads(x) for x in _git(remote["lane"], "show", f"{tip}:{sw.EXTERNAL}").splitlines()]
    assert tr["source_flag"] == "external" and tr["extracted"] == {"funding_rate_8h": 0.0003} and tr["review_id"] == rep["review_id"]
    (gap,) = [json.loads(x) for x in _git(remote["lane"], "show", f"{tip}:{sw.FEED_GAPS}").splitlines()]
    assert gap["fields"] == ["funding_rate_8h"] and gap["influence"] == "supporting"
    (row,) = [json.loads(x) for x in _git(remote["lane"], "show", f"{tip}:{sw.REVIEWS}").splitlines()]
    assert any(f.startswith("external_context: 1 source") for f in row["context_flags"])
