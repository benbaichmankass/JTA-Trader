#!/usr/bin/env python3
"""Turn a captured DOM snapshot into an exec_check fixture (PHONE-EXEC-OBSERVABLE-1018, piece 3).

Operator decision 2026-10-18: *tooling that turns captured DOM snapshots into exec_check.js fixtures, with numbers
replaced, so CI proves a fix against the real Breakout page.* Before this, every fixture in exec_check.js was a
hand-written GUESS of the terminal's DOM (its own header says so), and four APKs went out on guesses.

Input: one ``NNN-<step>.dom.json`` the phone posted (``src.prop.phone_captures``; read it with
``GET /api/diag/phone_capture_file?account_id=&run_id=&name=``). It is exec.js's ``__ex.snapshot``: visible elements
with their rects, attributes, computed-style subset, React handler names and own text, already REDACTED on the
device (account ids, balances, equity, P&L masked) and scrubbed again on the server.

Output: ``<out dir>/<name>.html`` (+ ``<name>.meta.json``): every element laid out ABSOLUTELY at the rect it had on
the phone (so ``elementFromPoint``, ``getBoundingClientRect``, overflow clipping, sticky columns and z-order behave
as they did), with the same tags / roles / aria / data-* / classes / ids / input values, the same ancestor nesting
inside each root subtree, the React handler names restored as ``__reactProps$fx`` objects (so ``handlerMap`` and
the snapshot's own ``h`` read the same), and EVERY NUMBER REPLACED: each digit run becomes a different run of the
same length and leading digit (seeded by the number itself, so one value maps to one replacement throughout the
page and relations like "the same price in the row and in the sheet" survive). Masked texts (``#``) stay masked.
The page is served under ``https://trade.breakoutprop.com/`` by the runner, so ``hostOk()`` passes.

A fixture is static: it proves READS and TARGETS (what positionsRead parses, which cell sheetTarget picks, whether
a point is covered, what the sheet / modal readers return) against the real page shape. It cannot prove that a
tap OPENS something -- that is what the rehearsal drill is for, on the phone. Pair each fixture with a
``<name>.spec.json`` (see tools/phone-executor/test/exec_fixtures_check.js) and CI runs it on every push.

Usage:
    python3 tools/phone-executor/test/fixture_from_capture.py <snapshot.dom.json> --name breakout-positions-sheet \\
        [--out tools/phone-executor/test/fixtures] [--note "1b.263 05:00Z amend #a6 after child_entry tap"]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

VOID = {"img", "input", "br", "hr", "meta", "link", "use", "path", "circle", "rect", "line"}
STYLE_KEYS = {"ov": "overflow", "pos": "position", "z": "z-index", "pe": "pointer-events", "vis": "visibility", "op": "opacity",
              "cur": "cursor", "d": "display"}
_NUM_RE = re.compile(r"\d+")


def replace_numbers(text: str, salt: str = "") -> str:
    """Every digit run -> a run of the same length and first digit, seeded by the run (stable within a page)."""
    def one(m: re.Match) -> str:
        run = m.group(0)
        if set(run) == {"#"} or len(run) == 0:
            return run
        h = hashlib.sha256((salt + run).encode()).digest()
        out = [run[0]]
        for i in range(1, len(run)):
            out.append(str((int(run[i]) + h[i % len(h)]) % 10))
        return "".join(out)
    return _NUM_RE.sub(one, text)


def _style(node: Dict[str, Any], fixed: bool, origin: Any = (0, 0)) -> str:
    """The node's box. The snapshot's ``r`` is viewport-relative (getBoundingClientRect); an absolute box is laid out
    relative to its CONTAINING block, which here is its rendered parent (every rendered node is positioned), so the
    parent's origin is subtracted -- MEASURED 2026-10-18 (drill 1 follow-up): with raw viewport coordinates on every
    nested node the offsets ADDED UP (the Stop row's Edit button rendered at 1383,4926 instead of 335,392) and the first
    geometry assertion on a nested element (``sheetEditStopTarget``) read "clipped". A fixed node is relative to the
    viewport (no transforms in a fixture), so its coordinates stay raw."""
    r = node.get("r") or [0, 0, 0, 0]
    ox, oy = (0, 0) if fixed else (origin[0], origin[1])
    parts = [f"position:{'fixed' if fixed else 'absolute'}", f"left:{int(r[0]) - int(ox)}px", f"top:{int(r[1]) - int(oy)}px",
             f"width:{int(r[2])}px", f"height:{int(r[3])}px", "box-sizing:border-box", "margin:0", "padding:0"]
    s = node.get("s") or {}
    if "ov" in s:
        ov = str(s["ov"]).replace("v", "visible").split("/")
        parts.append(f"overflow:{ov[0] if len(ov) == 1 else ov[0] + ' ' + ov[1]}")
    if "z" in s:
        parts.append(f"z-index:{s['z']}")
    if s.get("pe") == "none":
        parts.append("pointer-events:none")
    if s.get("vis"):
        parts.append(f"visibility:{s['vis']}")
    if s.get("op"):
        parts.append(f"opacity:{s['op']}")
    if s.get("cur") == "p":
        parts.append("cursor:pointer")
    if str(s.get("d", "")).startswith("inline"):
        parts.append("display:inline-block")
    if s.get("d") == "none":
        parts.append("display:none")
    parts.append("white-space:nowrap")
    return ";".join(parts)


def _attrs(node: Dict[str, Any], salt: str) -> str:
    out = []
    a = node.get("a") or {}
    for k, v in a.items():
        if not re.match(r"^[A-Za-z][A-Za-z0-9_:.-]*$", k):
            continue
        if k == "onclick":
            out.append(' data-onclick="1"')
            continue
        v = replace_numbers(str(v), salt) if k in ("value", "aria-label", "title", "alt", "placeholder") else str(v)
        out.append(f' {k}="{html.escape(v, quote=True)}"')
    if node.get("h"):
        out.append(f' data-h="{html.escape("+".join(node["h"]), quote=True)}"')
    if node.get("svg"):
        out.append(' data-svg="1"')
    return "".join(out)


def _render(node: Dict[str, Any], salt: str, depth: int, out: List[str], counter: List[int], origin: Any = (0, 0)) -> None:
    """``origin`` = the containing block's viewport position: (0, 0) for a root tree (its wrapper is static, so the
    initial containing block applies; the snapshot's scroll is [0, 0]), else the rendered parent's ``r``."""
    tag = str(node.get("t") or "div").lower()
    if not re.match(r"^[a-z][a-z0-9-]*$", tag):
        tag = "div"
    if tag in ("html", "body", "head", "script", "style", "link", "meta"):
        tag = "div"
    if node.get("ref") is not None:   # a placeholder for a priority root rendered on its own: nothing here
        return
    counter[0] += 1
    s = node.get("s") or {}
    fixed = s.get("pos") == "fixed"
    r = node.get("r") or [0, 0, 0, 0]
    text = html.escape(replace_numbers(str(node.get("x") or ""), salt))
    if tag == "svg":
        out.append(f'<svg{_attrs(node, salt)} style="{_style(node, fixed, origin)}"></svg>')
        return
    if tag in VOID:
        out.append(f'<{tag}{_attrs(node, salt)} style="{_style(node, fixed, origin)}">')
        return
    out.append(f'<{tag}{_attrs(node, salt)} style="{_style(node, fixed, origin)}">{text}')
    for c in node.get("c") or []:
        if isinstance(c, dict):
            _render(c, salt, depth + 1, out, counter, (r[0], r[1]))
    out.append(f"</{tag}>")


def _refs(node: Dict[str, Any], acc: List[int]) -> None:
    """The priority-root placeholders ({"ref": <index into snapshot.roots>}) under ``node``, in DOM (depth-first) order."""
    if not isinstance(node, dict):
        return
    if node.get("ref") is not None:
        try:
            acc.append(int(node["ref"]))
        except (TypeError, ValueError):
            pass
        return
    for c in node.get("c") or []:
        _refs(c, acc)


def build(snapshot: Dict[str, Any], *, name: str, note: str = "", source: str = "") -> Dict[str, Any]:
    """The fixture HTML + meta for one snapshot. Returns ``{"html", "meta"}``."""
    salt = name
    vw = int(snapshot.get("vw") or 390)
    vh = int(snapshot.get("vh") or 800)
    roots = [r for r in (snapshot.get("roots") or []) if isinstance(r, dict) and isinstance(r.get("tree"), dict)]
    body_parts: List[str] = []
    counter = [0]
    # the body root first (it holds the placeholders), then each priority root on top in its own wrapper -- in the
    # order the page PAINTS them: roots with a placeholder in the body tree in placeholder (DOM) order, then roots
    # without one (a portal outside the captured body subtree, e.g. the position sheet dialog) last, so they sit on top.
    # MEASURED 2026-10-18 (drill 1 follow-up): in the snapshot's priority order (sheet, grid) the grid's table painted
    # over the sheet and sheetEditStopTarget read the pencil as "covered" on a page where the phone's sheet is on top.
    raw = snapshot.get("roots") or []
    body_roots = [r for r in roots if r.get("k") == "body"]
    others = [r for r in roots if r.get("k") != "body"]
    ref_order: List[int] = []
    for b in body_roots:
        _refs(b["tree"], ref_order)
    by_ref = [raw[i] for i in ref_order if 0 <= i < len(raw)]
    order = body_roots + [r for r in by_ref if any(r is o for o in others)]
    order += [r for r in others if not any(r is o for o in order)]
    for r in order:
        k = str(r.get("k") or "root")
        body_parts.append(f'<div data-root="{html.escape(k)}" data-chain="{html.escape(" > ".join(r.get("chain") or []))}">')
        _render(r["tree"], salt, 0, body_parts, counter)
        body_parts.append("</div>")
    script = (
        "<script>\n"
        "// restore the page's React handler names (data-h) as __reactProps$fx so exec.js handlerMap / snapshot read them\n"
        "document.querySelectorAll('[data-h]').forEach(function (e) { var o = {}; e.getAttribute('data-h').split('+').forEach(function (n) {"
        " var k = {Click:'onClick',PUp:'onPointerUp',PDown:'onPointerDown',MUp:'onMouseUp',MDown:'onMouseDown',TEnd:'onTouchEnd',TStart:'onTouchStart'}[n];"
        " if (k) o[k] = function () {}; }); Object.defineProperty(e, '__reactProps$fx', {value: o, enumerable: true}); });\n"
        "document.querySelectorAll('[data-onclick]').forEach(function (e) { e.setAttribute('onclick', 'void 0'); });\n"
        "</script>"
    )
    doc = (
        "<!doctype html><html><head><meta charset=utf-8>"
        f'<meta name="viewport" content="width={vw}">'
        f"<!-- exec_check fixture {html.escape(name)}: generated by tools/phone-executor/test/fixture_from_capture.py from a phone capture "
        f"({html.escape(source)}); every number replaced; redacted on the device. {html.escape(note)} -->"
        f"<style>html,body{{margin:0;padding:0;width:{vw}px;height:{vh}px;overflow:hidden;font:12px/1.2 sans-serif}}"
        "[data-root]{position:static}</style></head><body>"
        + "".join(body_parts) + script + "</body></html>"
    )
    meta = {"name": name, "source": source, "note": note, "snapshot_version": snapshot.get("v"), "vw": vw, "vh": vh,
            "dpr": snapshot.get("dpr"), "path": snapshot.get("path"), "roots": [r.get("k") for r in roots],
            "nodes_in_snapshot": snapshot.get("nodes"), "nodes_rendered": counter[0], "cut": snapshot.get("cut"),
            "numbers": "replaced (same length + leading digit, seeded by the value)", "redaction": "on device + server"}
    return {"html": doc, "meta": meta}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", help="the NNN-<step>.dom.json file read from GET /api/diag/phone_capture_file")
    ap.add_argument("--name", required=True, help="fixture name ([a-z0-9-]+), becomes fixtures/<name>.html")
    ap.add_argument("--out", default="tools/phone-executor/test/fixtures")
    ap.add_argument("--note", default="", help="what this page shows / which miss it reproduces (goes in the HTML comment + meta)")
    ap.add_argument("--source", default="", help="run id + step, for the meta")
    a = ap.parse_args(argv)
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,60}$", a.name):
        print("name must be [a-z0-9-]+", file=sys.stderr)
        return 2
    try:
        snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read snapshot: {exc}", file=sys.stderr)
        return 1
    if isinstance(snap, dict) and "text" in snap and "roots" not in snap:
        print("this snapshot is a text document, not a DOM tree (the server wrapped it); nothing to build", file=sys.stderr)
        return 1
    if not isinstance(snap, dict) or not snap.get("roots"):
        print("snapshot has no roots", file=sys.stderr)
        return 1
    built = build(snap, name=a.name, note=a.note, source=a.source or Path(a.snapshot).name)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.name}.html").write_text(built["html"], encoding="utf-8")
    (out / f"{a.name}.meta.json").write_text(json.dumps(built["meta"], indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "html": str(out / f"{a.name}.html"), "nodes": built["meta"]["nodes_rendered"],
                      "roots": built["meta"]["roots"], "spec": str(out / f"{a.name}.spec.json") + " (write the assertions)"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
