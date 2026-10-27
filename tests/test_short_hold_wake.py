"""DESK-SHORT-HOLD-LANE: the VM trigger + 5-min packets (src/runtime/short_hold_wake.py)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.runtime import short_hold_wake as sh

NOW = datetime(2026, 10, 27, 9, 7, 30, tzinfo=timezone.utc)  # last closed 5m bar opens 09:00
CFG = {"legs": ["ict_scalp_eth_15m"], "branch": "live-review/rows", "hard_cap_minutes": 90}
PKG = "pkg-aaa"
ROW = {"order_package_id": PKG, "entry": 2400.0, "sl": 2390.0, "tp": 2420.0, "created_at": "2026-10-27T08:50:00Z",
       "status": "open", "close_reason": None, "updated_at": "2026-10-27T08:50:00Z"}


def jo(*pkgs, state="read"):
    return lambda: {"state": state, "packages": [
        {"order_package_id": p, "strategy": leg, "symbol": "ETHUSDT", "direction": "long", "account_id": "bybit_1"}
        for p, leg in pkgs]}


class Net:
    def __init__(self, markers=()):
        self.markers, self.posts, self.commits = list(markers), [], []

    def http(self, method, url, body, auth):
        if method == "GET":
            return 200, [{"body": "x\n<!-- short-hold " + json.dumps(m) + " -->"} for m in self.markers]
        self.posts.append(json.loads(body)["body"])
        self.markers += sh.parse_markers([{"body": self.posts[-1]}])
        return 201, {"html_url": "u"}

    def commit(self, branch, files, message, auth, http):
        self.commits.append((branch, files, message))
        return "c" * 40, None


def env_for(pkg, opened_at):
    return {"order_package_id": pkg, "bar": "2026-10-27T09:00:00Z", "closed": False, "packet": {}}, None


def run(tmp_path, net, journal, row=ROW, build=env_for, now=NOW):
    return sh.run_once(journal_fn=journal, package_fn=lambda p: dict(row), build_fn=build, commit_fn=net.commit,
                       auth_fn=lambda: "Basic eA==", http=net.http, now_fn=lambda: now, cfg=CFG,
                       pr_fn=lambda: 17895, receipt=tmp_path / "r.json", state_path=tmp_path / "s.json")


def test_last_closed_bar():
    assert sh.last_closed_bar(NOW) == "2026-10-27T09:00:00Z"
    assert sh.last_closed_bar(datetime(2026, 10, 27, 9, 5, 0, tzinfo=timezone.utc)) == "2026-10-27T09:00:00Z"


def test_idle_when_no_short_hold_package(tmp_path):
    net = Net()
    rec = run(tmp_path, net, jo(("pkg-x", "ada_pullback_2h")))
    assert rec["state"] == "idle" and not net.posts and not net.commits


def test_could_not_look_is_not_idle(tmp_path):
    rec = run(tmp_path, Net(), jo(state="could_not_look"))
    assert rec["state"] == "could_not_look"


def test_entry_lands_packet_then_posts_one_wake(tmp_path):
    net = Net()
    rec = run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    assert rec["packages"][PKG] == "wake_posted"
    assert len(net.commits) == 1 and net.commits[0][1][0][0] == f"comms/live_review/short_hold/{PKG}/latest.json"
    (m,) = net.markers
    assert m["kind"] == "short-hold-wake" and m["order_package_id"] == PKG and m["accounts"] == ["bybit_1"]
    assert (m["entry"], m["sl"], m["tp"], m["leg"], m["symbol"]) == (2400.0, 2390.0, 2420.0, "ict_scalp_eth_15m", "ETHUSDT")
    assert m["opened_at"] == "2026-10-27T08:50:00Z" and m["hard_cap_at"] == "2026-10-27T10:20:00Z"
    assert m["commit"] == "c" * 40
    # same bar, next pass: no new packet, no second wake
    rec = run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    assert rec["packages"][PKG] == "tracking" and len(net.commits) == 1 and len(net.posts) == 1


def test_next_bar_lands_a_new_packet_without_a_new_wake(tmp_path):
    net = Net()
    run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    rec = run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")), now=datetime(2026, 10, 27, 9, 12, 30, tzinfo=timezone.utc))
    assert rec["packages"][PKG] == "packet_landed" and len(net.commits) == 2 and len(net.posts) == 1


def test_lagging_candles_cost_one_packet_per_bar_not_per_pass(tmp_path):
    net = Net()
    lag = lambda p, o: ({"order_package_id": p, "bar": "2026-10-27T08:55:00Z", "closed": False}, None)  # noqa: E731
    run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")), build=lag)
    run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")), build=lag)
    assert len(net.commits) == 1


def test_build_failure_posts_no_wake_and_retries(tmp_path):
    net = Net()
    rec = run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")), build=lambda p, o: (None, "exit 1: boom"))
    assert rec["packages"][PKG].startswith("could_not_build") and not net.posts and not net.commits
    rec = run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    assert rec["packages"][PKG] == "wake_posted"


def test_close_rewrites_envelope_closed_and_posts_closed_once(tmp_path):
    net = Net()
    run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    closed = dict(ROW, status="closed", close_reason="tp_hit", updated_at="2026-10-27T09:20:00Z")
    rec = run(tmp_path, net, jo(), row=closed)
    assert rec["packages"][PKG] == "closed_posted"
    env = json.loads(net.commits[-1][1][0][1])
    assert env["closed"] is True and env["close_reason"] == "tp_hit"
    assert [m["kind"] for m in net.markers] == ["short-hold-wake", "short-hold-closed"]
    rec = run(tmp_path, net, jo(), row=closed)
    assert rec["state"] == "idle" and len(net.posts) == 2


def test_never_closes_on_a_doubt(tmp_path):
    """The journal's open set missed the package but its own row still reads open: keep tracking."""
    net = Net()
    run(tmp_path, net, jo((PKG, "ict_scalp_eth_15m")))
    rec = run(tmp_path, net, jo())
    assert rec["packages"][PKG] == "tracking" and len(net.posts) == 1


def test_marker_roundtrip_and_render_names_the_manager_step():
    e = {"kind": "short-hold-wake", "order_package_id": PKG, "accounts": ["bybit_1"], "leg": "l", "symbol": "s",
         "side": "long", "branch": "live-review/rows", "commit": "c" * 40}
    body = sh.render(e, NOW)
    assert "Short-hold wake" in body and "Generated by [Claude Code]" in body
    (m,) = sh.parse_markers([{"body": body}])
    assert sh.posted([m], "short-hold-wake", PKG) and not sh.posted([m], "short-hold-closed", PKG)


def test_config_on_disk_names_the_two_first_legs():
    cfg = sh.load_config()
    assert cfg["legs"] == ["ict_scalp_eth_15m", "ict_scalp_xrp_15m"]
    assert cfg["branch"] == "live-review/rows" and cfg["hard_cap_minutes"] == 90


def test_kick_is_a_noop_off_the_live_trader():
    assert sh.kick() is False
