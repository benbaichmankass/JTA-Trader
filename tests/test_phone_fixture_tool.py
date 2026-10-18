"""fixture_from_capture.py (PHONE-EXEC-OBSERVABLE-1018, piece 3): numbers replaced, masks kept, geometry and handlers
carried, and the sample fixture + spec in the repo agree with the generator's shape."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "phone-executor" / "test" / "fixture_from_capture.py"
FIX = ROOT / "tools" / "phone-executor" / "test" / "fixtures"


def _mod():
    spec = importlib.util.spec_from_file_location("fixture_from_capture", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_replace_numbers_keeps_shape_and_masks_and_is_stable():
    m = _mod()
    out = m.replace_numbers("2,461.52USD and 2,461.52 again; Sum ##.##USD; 0.54 ETH", "salt")
    assert out != "2,461.52USD and 2,461.52 again; Sum ##.##USD; 0.54 ETH"
    assert re.match(r"^2,\d{3}\.\d{2}USD and 2,\d{3}\.\d{2} again; Sum ##\.##USD; 0\.\d{2} ETH$", out)
    a, b = re.findall(r"2,\d{3}\.\d{2}", out)
    assert a == b, "one value maps to one replacement across the page"
    assert m.replace_numbers("2,461.52", "salt") == m.replace_numbers("2,461.52", "salt")
    assert m.replace_numbers("2,461.52", "salt") != m.replace_numbers("2,461.52", "other")


def test_build_renders_roots_at_their_rects_with_handlers_and_masks():
    m = _mod()
    snap = {"v": "2026-10-18.1", "vw": 390, "vh": 800, "dpr": 2, "path": "/en/account/ACCT/trade", "nodes": 4, "cut": False,
            "roots": [
                {"k": "body", "chain": [], "tree": {"t": "body", "r": [0, 0, 390, 800], "c": [
                    {"t": "div", "r": [10, 20, 100, 30], "a": {"id": "chd", "class": "r"}, "h": ["Click"], "s": {"cur": "p"},
                     "x": "ETH 5x", "c": [{"t": "span", "r": [12, 22, 60, 20], "x": "1,318.20USD"}]},
                    {"t": "div", "r": [0, 60, 390, 20], "x": "Position – ID", "s": {"pos": "fixed", "z": "5"}},
                    {"t": "input", "r": [0, 90, 100, 20], "a": {"value": "2504.25", "type": "text"}},
                    {"t": "div", "ref": 1}]}},
                {"k": "sheet", "chain": ["div", "div"], "tree": {"t": "div", "r": [0, 400, 390, 400], "x": "Sum ##.##USD"}}]}
    b = m.build(snap, name="t-fixture", note="n", source="run/003-sheet")
    html, meta = b["html"], b["meta"]
    assert "1,318.20" not in html and re.search(r"1,\d{3}\.\d{2}USD", html)
    assert "Sum ##.##USD" in html and "Position – ID" in html
    assert 'id="chd"' in html and 'data-h="Click"' in html and "__reactProps$fx" in html
    assert "position:absolute;left:10px;top:20px;width:100px;height:30px" in html
    assert "position:fixed;left:0px;top:60px" in html and "z-index:5" in html and "cursor:pointer" in html
    assert re.search(r'<input value="2\d{3}\.\d{2}" type="text"', html) and "2504.25" not in html
    assert html.count('data-root="') == 2 and 'data-root="sheet"' in html and 'data-chain="div &gt; div"' in html
    assert meta["nodes_rendered"] == 6 and meta["roots"] == ["body", "sheet"] and meta["vw"] == 390 and meta["cut"] is False


def test_sample_fixture_in_repo_matches_its_meta_and_spec_shape():
    names = sorted(p.stem for p in FIX.glob("*.html"))
    assert names, "the fixtures dir carries at least the sample"
    for n in names:
        meta = json.loads((FIX / f"{n}.meta.json").read_text())
        spec = json.loads((FIX / f"{n}.spec.json").read_text())
        html = (FIX / f"{n}.html").read_text()
        assert meta["name"] == n and meta["numbers"].startswith("replaced")
        assert isinstance(spec.get("checks"), list) and spec["checks"], f"{n}: a spec with checks"
        assert all(isinstance(c.get("call"), str) and "__ex." in c["call"] and "expect" in c for c in spec["checks"]), n
        assert f"exec_check fixture {n}" in html and "fixture_from_capture.py" in html
        assert not re.search(r"/account/\d", html) and "7f3a9c" not in html, f"{n}: no account id, no raw position id"
