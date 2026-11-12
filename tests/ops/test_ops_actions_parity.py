"""MANAGER-VM-DIRECT-OPS: the ops channel can never grant more than the system-actions workflow does.

* ``ops_actions.REGISTRY`` equals the § 2.3 table in docs/claude/system-actions.md, row for row (name AND tier);
* an entry whose Ports names a § 2 allowlist action carries that action's tier;
* a ported action missing from § 2 is allowed only while its wrapper is not in the tree (amend-prop-bracket waits
  on PR #25016); once the wrapper lands, the § 2 row must exist;
* nothing is Tier 3, and every refused-by-name action is absent from the registry.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.runtime import ops_actions as ops

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "claude" / "system-actions.md").read_text()
ROW_RE = re.compile(r"^\| `([a-z0-9-]+)` \| ([0-9]) \| ([^|]*)\|", re.M)


def _section(start: str, end: str) -> str:
    i = DOC.index(start)
    return DOC[i:DOC.index(end, i + len(start))]


ALLOWLIST = {m.group(1): int(m.group(2)) for m in ROW_RE.finditer(_section("## 2. Allowlist", "### 2.1 "))}
CHANNEL = {m.group(1): (int(m.group(2)), m.group(3).strip())
           for m in ROW_RE.finditer(_section("### 2.3 The direct ops channel", "## 3. Tier policy"))}

#: A ported action whose § 2 row is not on this tree yet -> the wrapper that, once present, requires the row.
PENDING_PORTS = {"amend-prop-bracket": "scripts/ops/amend_prop_bracket_action.sh"}


def test_probe_reads_both_tables():
    # A negative needs a denominator: the parser finds the known rows.
    assert ALLOWLIST.get("restart-bot-service") == 2 and ALLOWLIST.get("status-check") == 1
    assert len(ALLOWLIST) > 100
    assert CHANNEL, "§ 2.3 table not found"


def test_registry_equals_the_doc_table_name_and_tier():
    assert {n: a.tier for n, a in ops.REGISTRY.items()} == {n: t for n, (t, _) in CHANNEL.items()}


def test_wave_one_is_exactly_the_design_list():
    assert set(ops.REGISTRY) == {"live-review-row", "directed-action", "amend-prop-bracket", "sync-now",
                                 "restart-service"}


def test_a_ported_allowlist_action_keeps_its_tier():
    for name, (tier, ports) in CHANNEL.items():
        m = re.match(r"`([a-z0-9-]+)`", ports)
        port = m.group(1) if m else None
        if port in ALLOWLIST:
            assert tier == ALLOWLIST[port], (name, port, tier, ALLOWLIST[port])
        elif port in PENDING_PORTS:
            assert not (ROOT / PENDING_PORTS[port]).exists(), (
                f"{PENDING_PORTS[port]} is in the tree: add the § 2 row for {port} (and drop it from PENDING_PORTS)")
        assert ops.REGISTRY[name].tier == tier


def test_restart_service_ports_restart_bot_service_at_tier_2():
    assert CHANNEL["restart-service"][1].startswith("`restart-bot-service`")
    assert ops.REGISTRY["restart-service"].tier == ALLOWLIST["restart-bot-service"] == 2


def test_nothing_is_tier_three_and_refused_names_are_not_registered():
    assert all(a.tier in (1, 2) for a in ops.REGISTRY.values())
    assert not set(ops.REFUSED_BY_NAME) & set(ops.REGISTRY)
    assert "set-account-mode" in ops.REFUSED_BY_NAME


def test_every_registry_entry_has_a_runner():
    for a in ops.REGISTRY.values():
        assert a.run in ops.RUNNERS, a.name
