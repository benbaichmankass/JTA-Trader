"""DESK-MACRO-DAILY packet builder (scripts/ops/desk_macro_packet.py): offline self-test + sha contract."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def test_desk_macro_packet_self_test():
    from scripts.ops import desk_macro_packet as P
    assert P.self_test() == 0


def test_sha_ok_detects_an_edit():
    import hashlib
    import json

    from scripts.ops import desk_macro_packet as P
    pkt = {"schema": P.SCHEMA, "built_at": "2026-11-26T13:00:00Z", "parts": {"prices": {"read_state": "measured"}}}
    pkt["packet_sha"] = hashlib.sha256(json.dumps(pkt, sort_keys=True, default=str).encode()).hexdigest()
    assert P.sha_ok(pkt) and not P.prices_could_not_look(pkt)
    pkt["parts"]["prices"]["read_state"] = "could_not_look"
    assert not P.sha_ok(pkt) and P.prices_could_not_look(pkt)
