#!/usr/bin/env python3
# wiring: research/queue/RQ-20261016-6013-01.yaml (weekly trial-ledger unit) is the intended regenerator; design
#         docs/research/measure-read-ledger-pbo-design-2026-11-28.md § 3 (row MEASURE-READ-LEDGER-PBO)
"""SUBJECT-WIDE READ LEDGER: how many graded reads each (subject, window) has taken, claimed or not.

REPORT-ONLY. Gates this adds or changes: none. Nothing here refuses, blocks or changes a bar. The bar a read
would face is ``holdout_lock.bar_for`` (principle M13, operator 2026-11-05): imported, never re-implemented.

Why: ``comms/research/holdout_reads.jsonl`` counts only reads that a harness CLAIMED through
``holdout_lock.claim_read``. Every other graded result that read a window (trading legs, levers, regime
cells, live-review classes, harnesses that never claim) is invisible to it, so ``n_tries`` undercounts
(design § 2, G1). This file folds both populations and says, per (subject, window), how many reads were
claimed and how many were not, and which results could not be placed on a window at all.

POPULATION (stated): every JSON row of ``research/results/**/*.jsonl`` with ``read_state: measured``, plus
every claim row in ``comms/research/holdout_reads.jsonl``, at the working tree's commit.

A READ is one (research_unit, window) pair from a measured result row. A re-ask of the same unit on the same
window is the same read. WINDOW is resolved from the first source that states it:
  1. ``measurement.data_start`` / ``measurement.data_end``
  2. ``measurement.window`` (dict with start/end, or fold_edges first..last)
  3. a ``--since/--start/--from/--holdout-start/--test-start/--oos-start`` date in the unit's YAML commands
A result with none of these is ``window_unstated``: counted, kept apart, never dropped and never a 0.
SUBJECT is the unit's ``iteration.subject``; else ``leg:<measurement.leg>``; else ``subject_unstated``.

    python3 scripts/research/read_ledger.py --self-test
    python3 scripts/research/read_ledger.py [--out comms/research/read_ledger.json] [--summary]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import holdout_lock  # noqa: E402  (the one bar function, M13)

DEFAULT_OUT = ROOT / "comms" / "research" / "read_ledger.json"
SCHEMA = 1
_DATE = r"([0-9]{4}-[0-9]{2}-[0-9]{2})"
_CMD_START = re.compile(r"--(?:since|start|from|start-date|holdout-start|test-start|oos-start)[ =]" + _DATE)
_CMD_END = re.compile(r"--(?:until|end|to|end-date|holdout-end|test-end|oos-end)[ =]" + _DATE)
OPEN_END = "9999-12-31"


def _d(x) -> str | None:
    if not isinstance(x, str) or len(x) < 10 or not re.match(_DATE, x[:10]):
        return None
    return x[:10]


def _units(root: Path) -> dict[str, str]:
    out = {}
    for f in glob.glob(str(root / "research" / "queue" / "*.yaml")) + glob.glob(str(root / "research" / "queue" / "blocked" / "*.yaml")):
        try:
            out[os.path.basename(f)[:-5]] = Path(f).read_text(encoding="utf-8")
        except OSError:
            continue
    return out


def resolve_window(measurement, unit_text: str | None) -> tuple[str | None, str | None, str]:
    """(start, end, basis). start None means window_unstated. An open end reads as OPEN_END."""
    m = measurement if isinstance(measurement, dict) else {}
    s, e = _d(m.get("data_start")), _d(m.get("data_end"))
    if s:
        return s, e or OPEN_END, "measurement.data_start"
    w = m.get("window")
    if isinstance(w, dict):
        s, e = _d(w.get("start")), _d(w.get("end"))
        if s:
            return s, e or OPEN_END, "measurement.window"
        edges = [x for x in (_d(v) for v in (w.get("fold_edges") or [])) if x]
        if edges:
            return min(edges), max(edges) if len(edges) > 1 else OPEN_END, "measurement.window.fold_edges"
    if unit_text:
        ms = _CMD_START.search(unit_text)
        if ms:
            me = _CMD_END.search(unit_text)
            return ms.group(1), me.group(1) if me else OPEN_END, "unit_command"
    return None, None, "window_unstated"


def _iteration_subject(unit_text: str | None) -> str | None:
    """The unit's ``iteration.subject`` read from the parsed YAML (a bare regex also matched unrelated ``subject:`` keys)."""
    if not unit_text or "iteration:" not in unit_text:
        return None
    try:
        import yaml  # noqa: PLC0415
        u = yaml.safe_load(unit_text)
    except Exception:  # noqa: BLE001  # allow-silent: an unparseable unit falls back to the next subject source, stated in the docstring
        return None
    it = u.get("iteration") if isinstance(u, dict) else None
    sub = it.get("subject") if isinstance(it, dict) else None
    return str(sub) if sub else None


def resolve_subject(measurement, unit_text: str | None) -> str:
    sub = _iteration_subject(unit_text)
    if sub:
        return sub
    m = measurement if isinstance(measurement, dict) else {}
    if isinstance(m.get("leg"), str) and m["leg"]:
        return f"leg:{m['leg']}"
    return "subject_unstated"


def build(root: Path = ROOT, ledger: Path | None = None) -> dict:
    ledger = ledger or root / "comms" / "research" / "holdout_reads.jsonl"
    units = _units(root)
    claims = holdout_lock._rows(ledger) if ledger.exists() else []
    claimed_units = defaultdict(list)          # unit -> [(start, end)]
    for c in claims:
        claimed_units[c.get("unit")].append((c["start"], c["end"]))

    reads: dict[tuple, dict] = {}               # (unit, start, end) -> read
    unstated: dict[str, set] = defaultdict(set)  # subject -> units
    rows_seen = rows_measured = 0
    for f in sorted(glob.glob(str(root / "research" / "results" / "**" / "*.jsonl"), recursive=True)):
        try:
            lines = Path(f).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            rows_seen += 1
            if r.get("read_state") != "measured":
                continue
            rows_measured += 1
            unit = r.get("research_unit") or "unit_unstated"
            text = units.get(unit)
            subj = resolve_subject(r.get("measurement"), text)
            s, e, basis = resolve_window(r.get("measurement"), text)
            if s is None and claimed_units.get(unit):
                continue        # the unit's claim (folded below) states its window; the claim is the read
            if s is None:
                unstated[subj].add(unit)
                continue
            key = (unit, s, e)
            if key not in reads:
                claimed = any(holdout_lock._overlap(cs, ce, s, e) for cs, ce in claimed_units.get(unit, []))
                reads[key] = {"unit": unit, "subject": subj, "start": s, "end": e, "basis": basis, "claimed": claimed}

    # A claim whose unit names no iteration.subject takes the subject most claims of its holdout FAMILY name (e.g. ENTRY ->
    # ml-entry), so one subject is not split across two keys; with no such claim it stays family:<FAMILY>, stated.
    fam_subj: dict[str, Counter] = defaultdict(Counter)
    for c in claims:
        sub = _iteration_subject(units.get(c.get("unit")))
        if sub:
            fam_subj[holdout_lock.family_of(c)][sub] += 1
    for c in claims:                            # every claim is a read of its window
        unit = c.get("unit") or "unit_unstated"
        fam = holdout_lock.family_of(c)
        subj = _iteration_subject(units.get(unit)) or (
            fam_subj[fam].most_common(1)[0][0] if fam_subj.get(fam) else f"family:{fam}")
        key = (unit, c["start"], c["end"])
        prev = reads.get(key)
        reads[key] = {"unit": unit, "subject": prev["subject"] if prev else subj, "start": c["start"], "end": c["end"],
                      "basis": "holdout_claim", "claimed": True}

    by_subject: dict[str, list] = defaultdict(list)
    for rd in reads.values():
        by_subject[rd["subject"]].append(rd)
    subjects = []
    for subj in sorted(set(by_subject) | set(unstated)):
        rs = by_subject.get(subj, [])
        windows = sorted({(x["start"], x["end"]) for x in rs})
        wout = []
        for (s, e) in windows:
            ov = [x for x in rs if holdout_lock._overlap(x["start"], x["end"], s, e)]
            n = len(ov)
            wout.append({"start": s, "end": e, "n_reads": n, "n_claimed": sum(x["claimed"] for x in ov),
                         "n_unclaimed": sum(not x["claimed"] for x in ov), "units": sorted({x["unit"] for x in ov}),
                         "next_bar": holdout_lock.bar_for(n + 1), "read_state": "measured"})
        subjects.append({"subject": subj, "windows": wout,
                         "window_unstated": {"n_units": len(unstated.get(subj, ())), "units": sorted(unstated.get(subj, ())),
                                             "read_state": "window_unstated"}})
    fams = holdout_lock.families(ledger) if ledger.exists() else []
    n_unstated_units = sum(len(v) for v in unstated.values())
    return {
        "schema": SCHEMA,
        "population": {"result_rows": rows_seen, "measured_rows": rows_measured, "claim_rows": len(claims),
                       "description": "research/results/**/*.jsonl rows with read_state measured + comms/research/holdout_reads.jsonl claims"},
        "totals": {"reads_with_window": len(reads), "reads_claimed": sum(x["claimed"] for x in reads.values()),
                   "reads_unclaimed": sum(not x["claimed"] for x in reads.values()),
                   "unit_subject_pairs_window_unstated": n_unstated_units},
        "subjects": subjects,
        # T1: the claimed families exactly as holdout_lock counts them (positive control).
        "claimed_families": [{k: e[k] for k in ("family", "start", "end", "symbols", "n_tries")} for e in fams],
        "bar_method": holdout_lock.METHOD,
    }


def read_block(unit_id: str, measurement, root: Path = ROOT, ledger_doc: dict | None = None) -> dict:
    """The block a NEW result row carries (stamped by script_run.derive_record into measurement.json): its subject and
    window, the graded reads of that subject that already overlap the window, and the M13 bar THIS read faces
    (``holdout_lock.bar_for(prior + 1)``). Report-only; ``read_state`` is window_unstated / measured, never a silent 0."""
    units = _units(root)
    text = units.get(unit_id)
    subj = resolve_subject(measurement, text)
    s, e, basis = resolve_window(measurement, text)
    out = {"subject": subj, "window": [s, e], "window_basis": basis, "decisive": False}
    if s is None:
        return out | {"read_state": "window_unstated", "prior_reads": None, "bar": None}
    doc = ledger_doc if ledger_doc is not None else build(root)
    # prior reads = DISTINCT other units that read a window overlapping this one (this unit's own re-asks excluded)
    seen: set[str] = set()
    for sub in doc.get("subjects") or []:
        if sub.get("subject") != subj:
            continue
        for w in sub.get("windows") or []:
            if holdout_lock._overlap(w["start"], w["end"], s, e):
                seen |= {u for u in w.get("units") or [] if u != unit_id}
    prior = len(seen)
    return out | {"read_state": "measured", "prior_reads": prior, "prior_units": sorted(seen)[:50],
                  "bar": holdout_lock.bar_for(prior + 1)}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "research" / "queue").mkdir(parents=True)
        (root / "research" / "results" / "U1").mkdir(parents=True)
        (root / "research" / "results" / "U2").mkdir(parents=True)
        (root / "research" / "results" / "U3").mkdir(parents=True)
        (root / "comms" / "research").mkdir(parents=True)
        (root / "research" / "queue" / "U1.yaml").write_text("iteration:\n  subject: ml-entry\n")
        (root / "research" / "queue" / "U2.yaml").write_text("iteration:\n  subject: ml-entry\ncommands: x --since 2025-11-01 --until 2026-01-01\n")
        (root / "research" / "queue" / "U3.yaml").write_text("iteration:\n  subject: ml-entry\n")
        row = {"read_state": "measured", "research_unit": "U1", "measurement": {"data_start": "2025-10-01", "data_end": "2026-09-30"}}
        p1 = root / "research" / "results" / "U1" / "1.jsonl"
        p1.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")   # a re-ask: one read
        (root / "research" / "results" / "U2" / "2.jsonl").write_text(json.dumps({"read_state": "measured", "research_unit": "U2", "measurement": {}}) + "\n")
        (root / "research" / "results" / "U3" / "3.jsonl").write_text(json.dumps({"read_state": "measured", "research_unit": "U3", "measurement": {}}) + "\n")
        led = root / "comms" / "research" / "holdout_reads.jsonl"
        led.write_text(json.dumps({"model_id": "ENTRY-x", "family": "ENTRY", "start": "2025-10-01", "end": "2026-09-30", "unit": "U1"}) + "\n")
        out = build(root, led)
        s = {x["subject"]: x for x in out["subjects"]}["ml-entry"]
        w = {(x["start"], x["end"]): x for x in s["windows"]}
        a = w[("2025-10-01", "2026-09-30")]
        assert a["n_reads"] == 2 and a["n_claimed"] == 1 and a["n_unclaimed"] == 1, a   # claim + result merge to one read   # U1 claimed + U2 (overlaps) unclaimed
        assert a["next_bar"] == holdout_lock.bar_for(3)
        assert s["window_unstated"]["units"] == ["U3"], s["window_unstated"]            # counted, not dropped
        assert out["claimed_families"][0]["n_tries"] == 1
        assert json.dumps(build(root, led), sort_keys=True) == json.dumps(out, sort_keys=True)   # T2 determinism
        b = read_block("U3", {"data_start": "2025-11-01", "data_end": "2025-12-01"}, root, out)
        assert b["read_state"] == "measured" and b["prior_reads"] == 2 and b["bar"] == holdout_lock.bar_for(3), b
        assert read_block("U3", {}, root, out)["read_state"] == "window_unstated"
    print("read-ledger self-test OK")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--summary", action="store_true", help="print totals and the top subjects instead of writing")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    out = build()
    if a.summary:
        print(json.dumps({"population": out["population"], "totals": out["totals"]}, indent=1))
        top = sorted(((w["n_reads"], s["subject"], w["start"], w["end"], w["n_unclaimed"]) for s in out["subjects"] for w in s["windows"]), reverse=True)[:10]
        for t in top:
            print("n_reads %3d  %-28s %s..%s  unclaimed %d" % t)
        return 0
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"read-ledger: wrote {a.out} ({out['totals']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
