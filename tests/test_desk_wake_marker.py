"""DESK-6B: the packet job's wake step (scripts/ops/desk_wake_marker.py) and its workflow wiring."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dwm", ROOT / "scripts/ops/desk_wake_marker.py")
dwm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dwm)
NOW = datetime(2026, 10, 26, 16, 40, tzinfo=timezone.utc)
PK = {"universe": [{"symbol": "BTCUSDT", "calendar": {"read_state": "could_not_look", "events_next_bar": None}}],
      "system_book": {"read_state": "read", "near_signals_read_state": "could_not_look",
                      "items": [{"status": "open"}, {"status": "open"}]},
      "desk_book": {"read_state": "read", "items": []}}


def stage(tmp_path, pk=PK):
    (tmp_path / "comms/desk/packets").mkdir(parents=True)
    ptr = {"packet_id": "DP-20261026T1631Z-scan-1h", "packet_sha": "a" * 64, "built_at": "2026-10-26T16:33:38Z",
           "info_cutoff_at": "2026-10-26T16:31:00Z", "path": "comms/desk/packets/DP-20261026T1631Z-scan-1h.json"}
    (tmp_path / "comms/desk/latest_scan.json").write_text(json.dumps(ptr))
    (tmp_path / ptr["path"]).write_text(json.dumps(pk))
    return tmp_path


def test_marker_carries_packet_id_sha_commit_and_context(tmp_path):
    e = dwm.build_entry(stage(tmp_path), "c" * 40, NOW)
    m = dwm.parse_markers([{"body": dwm.render_wake(e, NOW, "https://run")}])[0]
    assert (m["packet_id"], m["packet_sha"], m["commit"], m["bar"]) == (
        "DP-20261026T1631Z-scan-1h", "a" * 64, "c" * 40, "2026-10-26T16:00:00Z")
    assert m["context"]["open_positions"] == 2 and m["context"]["near_signals"] is None
    assert m["context"]["unread"] == ["near_signals"]


def test_dedupe_is_on_the_packet_id_not_the_bar(tmp_path):
    e = dwm.build_entry(stage(tmp_path), "c" * 40, NOW)
    assert dwm.plan_post(e, []) == "post"
    assert dwm.plan_post(e, [{"packet_id": e["packet_id"]}]) == "already_posted"
    # two producers (VM primary, workflow fallback): one wake per bar, whichever lands first
    assert dwm.plan_post(e, [{"kind": "desk-wake", "packet_id": "DP-other", "bar": e["bar"]}]) == "already_posted"
    assert dwm.plan_post(e, [{"kind": "desk-wake", "packet_id": "DP-other", "bar": "2026-10-26T15:00:00Z"}]) == "post"


def test_gate_skips_when_the_vm_already_built_this_hours_packet(monkeypatch, tmp_path):
    import subprocess
    now_bar = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for cutoff, skip in ((now_bar.strftime("%Y-%m-%dT%H:05:00Z"), "true"), ("2020-01-01T00:05:00Z", "false")):
        monkeypatch.setattr(subprocess, "run", lambda *a, _c=cutoff, **k: subprocess.CompletedProcess(
            a, 0, stdout=json.dumps({"info_cutoff_at": _c}), stderr=""))
        out = tmp_path / f"o{skip}"
        assert dwm._gate("origin/desk/decisions", out) == 0
        assert out.read_text() == f"skip={skip}\n"


def test_every_packet_wakes_whatever_the_context(tmp_path):
    quiet = {"universe": [], "system_book": {"read_state": "could_not_look", "items": None},
             "desk_book": {"read_state": "could_not_look", "items": None}}
    e = dwm.build_entry(stage(tmp_path, quiet), "c" * 40, NOW)
    assert dwm.plan_post(e, []) == "post" and e["context"]["open_positions"] is None


def test_failed_build_posts_one_incident_marker_per_bar():
    body = dwm.render_fail("Build the scan packet", "2026-10-26T16:00:00Z", NOW)
    m = dwm.parse_markers([{"body": body}])
    assert m[0]["kind"] == "could_not_build" and "packet_id" not in m[0]
    assert dwm.plan_fail("2026-10-26T16:00:00Z", m) == "already_posted"
    assert dwm.plan_fail("2026-10-26T17:00:00Z", m) == "post"


def test_workflow_posts_the_wake_after_the_commit_and_reports_failures():
    wf = yaml.safe_load((ROOT / ".github/workflows/desk-scan-packet.yml").read_text())
    steps = wf["jobs"]["build"]["steps"]
    ids = [s.get("id") for s in steps]
    assert ids.index("commit") < ids.index("wake") == len(steps) - 2
    assert "desk_wake_marker.py post" in steps[ids.index("wake")]["run"]
    last = steps[-1]
    assert "desk_wake_marker.py fail" in last["run"] and "failure()" in last["if"]
    assert "desk_wake_marker.py gate" in steps[ids.index("gate")]["run"]
    assert all(st.get("if") == "steps.gate.outputs.skip != 'true'" for st in steps[ids.index("gate") + 1:-1])
    assert wf["permissions"]["pull-requests"] == "write" and wf["permissions"]["issues"] == "write"
    assert (wf.get("on") or wf.get(True))["schedule"], "the schedule stays: the packet job is the only trigger"
