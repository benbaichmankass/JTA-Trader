"""A strategy unit must not call itself unwired while the order path imports it.

CA-A05-006 / PI-20260927-CAA05-0004: ``htf_pullback_trend_2h.py`` opened with
"SCAFFOLD, not wired … inert until the Tier-3 activation PR" while being the live
implementation behind enabled legs, one of which traded real money. A reader
trusting that header would treat edits to a live order path as low-risk.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNITS = ROOT / "src/units/strategies"
WIRING = [
    ROOT / "src/runtime/strategy_signal_builders.py",
    ROOT / "src/runtime/intent_multiplexer.py",
]
CLAIM = re.compile(r"SCAFFOLD|not\s+(yet\s+)?wired|inert\s+until", re.I)


def _header(path: pathlib.Path) -> str:
    text = path.read_text()
    m = re.match(r'\s*(?:#[^\n]*\n\s*)*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', text, re.S)
    return (m.group(1) or m.group(2) or "") if m else ""


def test_no_unit_claims_unwired_while_the_order_path_imports_it():
    wiring_src = "\n".join(p.read_text() for p in WIRING)
    offenders = []
    for unit in sorted(UNITS.glob("*.py")):
        if unit.name == "__init__.py":
            continue
        # Claim lives in the module docstring's opening ~600 chars (the summary).
        if not CLAIM.search(_header(unit)[:600]):
            continue
        if re.search(rf"\b{re.escape(unit.stem)}\b", wiring_src):
            offenders.append(unit.name)
    assert not offenders, (
        "module docstring claims SCAFFOLD/not wired/inert but the order path "
        f"references it: {offenders}"
    )


def test_guard_detects_the_original_false_header():
    old = '"""HTF trend-pullback (SCAFFOLD, not wired).\n\ninert until the Tier-3 activation PR.\n"""'
    p = pathlib.Path(__file__).parent / "_tmp_hdr.py"
    try:
        p.write_text(old)
        assert CLAIM.search(_header(p)[:600])
    finally:
        p.unlink(missing_ok=True)
