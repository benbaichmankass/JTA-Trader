"""`leg:SYMBOL` support in m20_exit_head_round (RESEARCH-FILL-20261122, D8 corpus widening)."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("m20r", REPO / "scripts/research/m20_exit_head_round.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_parse_bare_leg():
    assert m.parse_leg_spec("trend_donchian") == ("trend_donchian", None)


def test_parse_leg_symbol():
    assert m.parse_leg_spec(" trend_donchian:LINKUSDT ") == ("trend_donchian", "LINKUSDT")
    assert m.parse_leg_spec("trend_donchian:") == ("trend_donchian", None)


def test_builder_db_legs_are_base_names_deduped():
    src = (REPO / "scripts/research/m20_exit_head_round.py").read_text()
    assert "dict.fromkeys(parse_leg_spec(x)[0]" in src
    assert 'emitted_meta[leg_spec]' in src
