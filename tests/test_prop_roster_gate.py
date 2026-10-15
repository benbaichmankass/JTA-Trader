"""prop-roster-gate-guard: its planted-violation self-test must pass, and the grandfather table must
name exactly the two pre-rule legs with ISO due dates that match their SOAKS.json contracts."""
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))

import check_prop_roster_gate as g  # noqa: E402


def test_self_test_passes():
    assert g.self_test() == 0


def test_grandfather_names_and_due_dates_match_soak_contracts():
    assert set(g.GRANDFATHERED) == {"trend_donchian_eth_prop", "trend_donchian_sol_prop"}
    soaks = json.loads((REPO / g.SOAKS_REL).read_text())["soaks"]
    for leg, meta in g.GRANDFATHERED.items():
        c = [s for s in soaks if s["id"] == f"SOAK-stage1-bybit_1-{leg}"]
        assert c, f"no Stage-1 contract for grandfathered {leg}"
        assert c[0]["end_date"] == meta["due"]
        date.fromisoformat(meta["due"])
