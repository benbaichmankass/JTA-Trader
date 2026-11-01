#!/usr/bin/env python3
# wiring: research-ops pass (manual, every pass) + programme-review; writes research/levers/<subject>.yaml; read by
# scripts/research/research_ops_checks.py (iteration block) and scripts/research/iteration_orphans.py --levers.
"""LEVER RESPONSE MAP: how each lever affects each subject's outcome, persistent and cumulative (lane RESEARCH-ITERATE, 2026-11-01).

OPERATOR, 2026-11-01 (verbatim): "we have to have a process here by which we understand how to test the different levers so that
we can understand how each lever affects the outcome, and based on that, decide if something has potential or not have potential."
Canonical: docs/plans/OPERATING-PLAN-2026-09-21.md § 2 "What does not pass goes back into research".

One file per subject, research/levers/<subject>.yaml:
  subject, kind, manifest      -- the lever families for the kind (policy.lever_families) and each family's state
  attribution                  -- WHY the baseline wins or loses, decomposed from its own trade rows (see attribute())
  levers.<family>.<lever>      -- every tested value: unit, arm, value vs baseline value, n, net R, delta vs baseline,
                                  per-fold deltas, maxDD; then a SHAPE (flat / monotone / peaked / noisy / single_point)
                                  and fold STABILITY (share of folds where the arm >= baseline)
The map is REBUILT from the committed results every run (idempotent: no hand edits to the generated part); a subject's
`manifest_notes` and `declared` blocks (ranges and hypothesised effects written by an author) are preserved across rebuilds.

ONE SCHEMA (PI-20261101-HIPIPRHQ-0004, 2026-11-01): the generated keys above plus an author-owned HAND block, all preserved on rebuild
(HAND_KEYS): `units`, `status`, `doctrine`, `verdict_so_far`, `failure_attribution` (where_lost / by_direction / by_year / worst+best
months+symbols / cost_split / stage), `levers_tested` [{family, varied, response, shape, tested_at_power, lever_family?}],
`lever_families_untested`, `power_note`, `evidence`, `handed_to`. A subject with no results-derived arms (a research CANDIDATE) gets its
`attribution` (read_state "attributed") and its `manifest` (tested / underpowered / untested) DERIVED from that block, so
iteration_orphans --levers and research_ops_checks read one shape. `levers_tested[].family` is free text mapped to a policy family by
iteration_orphans.policy_family (or set `lever_family:` explicitly). New tests are appended with --append (below), never by hand-editing.

Reading it (canonical § 2): a flat or noisy response on every material lever family at adequate power is evidence of no edge;
a smooth, fold-stable response on some lever is potential; a spiky single-point optimum is overfit, not an edge.

Sources (reused, not re-measured): exit_lever_ablation result records (research/results/<unit>/*.jsonl, measurement.arms with
argv per arm and grade.candidates deltas) for the arm responses; comms/strategy_evidence/<leg>.json + its source_run trades for
the baseline attribution. ML heads and live-review classes have no arm-level harness records yet: their map carries the manifest
and the verdict basis from scripts/research/iteration_subjects.yaml until their units write lever rows.

Gates this adds or changes: none. Report/record tool; exit 0 on findings, 2 only when it could not read its inputs.
Usage:
  python3 scripts/research/lever_map.py --backfill          # rebuild every subject's map (testing + production legs, ML, LTR)
  python3 scripts/research/lever_map.py --subject <id>      # print one subject's map
  python3 scripts/research/lever_map.py --summary           # coverage counts (non-empty maps, families with responses)
  python3 scripts/research/lever_map.py --append <subject> --family F --varied "..." --shape "..." --unit RQ-... [--at-power] [--response-json '{}']
  python3 scripts/research/lever_map.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
LEVERS_DIR = "research/levers"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
import iteration_orphans as io

FLAT_R_PER_TRADE = 0.02      # |delta| below 0.02 R/trade x n is "no response" (the units' own materiality bar)
#: author-owned keys, preserved verbatim across --backfill (the hand-seeded schema of RESEARCH-EDGE, 2026-11-01, plus the 2 older ones)
HAND_KEYS = ("title", "declared", "manifest_notes", "units", "status", "doctrine", "verdict_so_far", "failure_attribution", "levers_tested",
             "lever_families_untested", "power_note", "evidence", "handed_to")
_SKIP_FLAGS = {"--data", "--emit-trades", "--json", "--start", "--end", "--symbol", "--resample", "--strategy-name"}


# ── attribution: why the baseline wins or loses, from its own trade rows ─────────────────────────────────────────────
def attribute(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Decompose net R: entry quality (MFE / gross), exit capture (net vs MFE), cost share, and splits by year, direction,
    exit reason, ADX bucket. Every number names its population (n). Reads only fields the harness emits."""
    if not trades:
        return {"read_state": "no_trades"}
    def s(rows, k):
        return round(sum(float(r.get(k) or 0.0) for r in rows), 3)
    n = len(trades)
    gross, net = s(trades, "gross_r"), s(trades, "net_r")
    cost = round(sum(float(r.get("cost_fee_r") or 0) + float(r.get("cost_slippage_r") or 0) + float(r.get("cost_funding_r") or 0)
                     for r in trades), 3)
    mfe = [float(r["mfe_r"]) for r in trades if r.get("mfe_r") is not None]
    winners = [r for r in trades if float(r.get("net_r") or 0) > 0]
    cap = [float(r["net_r"]) / float(r["mfe_r"]) for r in winners if r.get("mfe_r") and float(r["mfe_r"]) > 0]

    def split(key_fn):
        g: dict[str, list] = defaultdict(list)
        for r in trades:
            g[str(key_fn(r))].append(r)
        return {k: {"n": len(v), "net_r": s(v, "net_r"), "gross_r": s(v, "gross_r")} for k, v in sorted(g.items())}

    def adx_bucket(r):
        a = r.get("adx_at_entry")
        if a is None:
            return "unknown"
        a = float(a)
        return "<20" if a < 20 else "20-30" if a < 30 else "30-40" if a < 40 else ">=40"

    out = {
        "read_state": "measured", "n": n, "net_r": net, "gross_r": gross, "cost_r": cost,
        "cost_share_of_gross": (round(cost / abs(gross), 3) if gross else None),
        "verdict_hint": ("cost erases a gross edge" if gross > 0 >= net else "gross edge survives cost" if net > 0
                         else "no gross edge: the loss is entry/exit, not cost"),
        "entry_quality": {"mean_mfe_r": (round(statistics.mean(mfe), 3) if mfe else None),
                          "share_mfe_ge_1r": (round(sum(1 for x in mfe if x >= 1) / len(mfe), 3) if mfe else None),
                          "n_with_mfe": len(mfe)},
        "exit_capture": {"median_net_over_mfe_winners": (round(statistics.median(cap), 3) if cap else None),
                         "n_winners": len(winners),
                         "losers_that_reached_1r_mfe": sum(1 for r in trades if float(r.get("net_r") or 0) <= 0
                                                          and float(r.get("mfe_r") or 0) >= 1)},
        "by_year": split(lambda r: str(r.get("entry_time", ""))[:4]),
        "by_direction": split(lambda r: r.get("direction") or r.get("side") or "unknown"),
        "by_exit_reason": split(lambda r: r.get("exit_reason") or "unknown"),
        "by_adx_at_entry": split(adx_bucket),
    }
    return out


# ── lever responses from exit_lever_ablation records ─────────────────────────────────────────────────────────────────
def _flag_values(argv: list[str]) -> dict[str, str]:
    out, i = {}, 0
    while i < len(argv):
        t = str(argv[i])
        if t.startswith("--") and t not in _SKIP_FLAGS:
            v = argv[i + 1] if i + 1 < len(argv) and not str(argv[i + 1]).startswith("--") else "on"
            out[t] = str(v)
            i += 2 if v != "on" else 1
            continue
        i += 1 if not (t in _SKIP_FLAGS) else 2
    return out


def _window(w: Any, base_arm: dict[str, Any]) -> str:
    if isinstance(w, dict):
        return f"{str(w.get('start') or base_arm.get('data_start') or '')[:10]}..{str(w.get('end') or base_arm.get('data_end') or '')[:10]}"
    return str(w) if w else f"{str(base_arm.get('data_start') or '')[:10]}..{str(base_arm.get('data_end') or '')[:10]}"


def responses_from_record(rec: dict[str, Any]) -> list[dict[str, Any]]:
    m = rec.get("measurement") or {}
    arms, grade = m.get("arms") or {}, m.get("grade") or {}
    base = grade.get("baseline") or ("A" if "A" in arms else None)
    if not base or base not in arms or not isinstance(arms.get(base), dict):
        return []
    bflags = _flag_values(arms[base].get("argv") or [])
    bn = arms[base].get("n") or arms[base].get("trades")
    bnet = arms[base].get("net_r", arms[base].get("net_total_r"))
    bfolds = [f.get("net_r") for f in (arms[base].get("folds") or [])]
    out = []
    for lab, a in arms.items():
        if lab == base or not isinstance(a, dict):
            continue
        fl = _flag_values(a.get("argv") or [])
        diff = {k: v for k, v in fl.items() if bflags.get(k) != v}
        diff.update({k: "off" for k in bflags if k not in fl})
        if not diff:
            continue
        net = a.get("net_r", a.get("net_total_r"))
        afolds = [f.get("net_r") for f in (a.get("folds") or [])]
        fold_ge = [1 if (x is not None and y is not None and x >= y) else 0 for x, y in zip(afolds, bfolds)]
        for flag, val in diff.items():
            fam = io._lever_of(flag) or "other"
            out.append({"family": fam, "lever": flag.lstrip("-").replace("-", "_"), "value": val,
                        "baseline_value": bflags.get(flag, "off"), "arm": lab, "unit": rec.get("research_unit"),
                        "window": _window(m.get("window"), arms[base]),
                        "n": a.get("n") or a.get("trades"), "net_r": net, "baseline_n": bn, "baseline_net_r": bnet,
                        "delta_net_r": (round(float(net) - float(bnet), 4) if net is not None and bnet is not None else None),
                        "folds_ge_baseline": (f"{sum(fold_ge)}/{len(fold_ge)}" if fold_ge else None),
                        "max_drawdown_r": a.get("max_drawdown_r"), "verdict": rec.get("verdict"),
                        "joint_change": len(diff) > 1})
    return out


def shape(tests: list[dict[str, Any]]) -> dict[str, Any]:
    """flat / monotone / peaked / noisy / single_point, from per-trade deltas; stability = share of folds the arms hold."""
    pts = [t for t in tests if t.get("delta_net_r") is not None and t.get("baseline_n")]
    if not pts:
        return {"shape": "no_reading"}
    per_trade = [float(t["delta_net_r"]) / max(1, int(t["baseline_n"])) for t in pts]
    folds = [t["folds_ge_baseline"] for t in pts if t.get("folds_ge_baseline")]
    held = [int(f.split("/")[0]) / max(1, int(f.split("/")[1])) for f in folds]
    stab = round(statistics.mean(held), 3) if held else None
    if len(pts) == 1:
        sh = "flat" if abs(per_trade[0]) < FLAT_R_PER_TRADE else "single_point"
    elif all(abs(x) < FLAT_R_PER_TRADE for x in per_trade):
        sh = "flat"
    else:
        try:
            order = sorted(zip((float(t["value"]) for t in pts), per_trade))
            ys = [y for _, y in order]
            inc = all(b >= a for a, b in itertools.pairwise(ys))
            dec = all(b <= a for a, b in itertools.pairwise(ys))
            peak = ys.index(max(ys))
            sh = "monotone" if (inc or dec) else ("peaked" if 0 < peak < len(ys) - 1 else "noisy")
        except (TypeError, ValueError):
            sh = "noisy" if max(per_trade) > 0 > min(per_trade) else "monotone"
    best = max(per_trade)
    return {"shape": sh, "points": len(pts), "best_delta_r_per_trade": round(best, 4),
            "fold_stability": stab, "reading": _reading(sh, best, stab)}


def _reading(sh: str, best: float, stab: float | None) -> str:
    if sh == "flat":
        return "no response at the tested values"
    if best <= 0:
        return "every tested value is worse than the baseline"
    if sh == "single_point" or (stab is not None and stab < 0.5):
        return "one-point or fold-unstable gain: overfit until a holdout says otherwise"
    return "smooth, fold-stable gain: potential -- confirm on a holdout"


def collect_responses(root: Path) -> dict[str, list[dict[str, Any]]]:
    by_leg: dict[str, list] = defaultdict(list)
    for f in glob.glob(str(root / "research/results/*/*.jsonl")):
        try:
            lines = Path(f).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            leg = (rec.get("measurement") or {}).get("leg") if isinstance(rec.get("measurement"), dict) else None
            if leg:
                for r in responses_from_record(rec):
                    by_leg[str(leg)].append(r)
    return by_leg


def _trades(root: Path, src: str | None) -> list[dict[str, Any]]:
    if not src:
        return []
    p = root / src
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def build(root: Path) -> dict[str, dict[str, Any]]:
    import strategy_status as ss
    policy = yaml.safe_load((root / "scripts/research/family_retirement_policy.yaml").read_text(encoding="utf-8")) or {}
    fams = policy.get("lever_families") or {}
    responses = collect_responses(root)
    maps: dict[str, dict[str, Any]] = {}
    for leg, row in ss.table(root).items():
        if row["status"] == ss.INACTIVE:
            continue
        ev = io.evidence_path(root, leg)
        rec = json.loads(ev.read_text(encoding="utf-8")) if ev.is_file() else {}
        levers: dict[str, dict[str, Any]] = defaultdict(dict)
        for r in responses.get(leg, []):
            levers[r["family"]].setdefault(r["lever"], {"tests": []})["tests"].append(
                {k: v for k, v in r.items() if k not in ("family", "lever")})
        for lv in levers.values():
            for entry in lv.values():
                entry["tests"].sort(key=lambda t: (str(t.get("unit")), str(t.get("arm"))))
                entry.update(shape(entry["tests"]))
        manifest = {f: ("tested" if f in levers else "untested") for f in fams.get("strategy_leg", [])}
        maps[leg] = {"subject": leg, "kind": "strategy_leg", "status": row["status"], "books": row["books"],
                     "baseline": {"record": str(ev.relative_to(root)) if ev.is_file() else None,
                                  "net_r": rec.get("net_r_oos"), "n": rec.get("n_trades_oos"),
                                  "fidelity": rec.get("fidelity"), "rule_verdict": (rec.get("decision_rule") or {}).get("verdict")},
                     "attribution": attribute(_trades(root, rec.get("source_run"))) if rec else {"read_state": "no_record"},
                     "manifest": manifest, "levers": {f: dict(v) for f, v in sorted(levers.items())}}
    subj = yaml.safe_load((root / io.SUBJECTS_REL).read_text(encoding="utf-8")) or {}
    for kind in ("ml_model", "ltr_class"):
        for s in subj.get(kind) or []:
            lv = {}
            for e in s.get("lever_evidence") or []:   # seeded from committed results (iteration_subjects.yaml)
                lv.setdefault(e["family"], {}).setdefault(e.get("lever", e["family"]), {"tests": []})["tests"].append(
                    {k: v for k, v in e.items() if k not in ("family", "lever")})
            for fl in lv.values():
                for entry in fl.values():
                    shapes = {t.get("shape") for t in entry["tests"] if t.get("shape")}
                    entry["shape"] = shapes.pop() if len(shapes) == 1 else ("mixed" if shapes else "no_reading")
            maps[s["id"]] = {"subject": s["id"], "kind": kind, "status": "not_live",
                             "baseline": {"verdict": s.get("verdict"), "basis": s.get("basis")},
                             "attribution": {"read_state": "no_arm_records_yet"},
                             "manifest": {f: ("tested" if f in lv else "untested") for f in fams.get(kind, [])},
                             "levers": lv}
    for c in io.listed_subjects(root):          # research CANDIDATES (no roster leg, no arm records): derive from the hand block
        if c["kind"] != "strategy_leg" or c["id"] in maps:
            continue
        old = io.read_map(root, c["id"]) or {}
        mf = io.map_families(old)
        fa = old.get("failure_attribution")
        maps[c["id"]] = {"subject": c["id"], "kind": "strategy_leg", "status": "candidate",
                         **({"title": old["subject"]} if old.get("subject") not in (None, c["id"]) and "title" not in old else {}),
                         "baseline": {"verdict": c.get("verdict"), "basis": c.get("basis")},
                         "attribution": ({"read_state": "attributed", "source": "failure_attribution (hand block)",
                                          "where_lost": fa.get("where_lost"), "stage": fa.get("stage")} if isinstance(fa, dict)
                                         else {"read_state": "no_record"}),
                         "manifest": {f: ("tested" if mf.get(f, {}).get("at_power") else "underpowered" if f in mf else "untested")
                                      for f in fams.get("strategy_leg", [])},
                         "levers": {}}
    return maps


def non_empty(m: dict[str, Any]) -> bool:
    return bool(m.get("levers")) or (m.get("attribution") or {}).get("read_state") in ("measured", "attributed")


def write(root: Path, maps: dict[str, dict[str, Any]]) -> int:
    d = root / LEVERS_DIR
    d.mkdir(parents=True, exist_ok=True)
    for sid, m in maps.items():
        p = d / f"{sid}.yaml"
        keep = {}
        if p.is_file():
            old = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            keep = {k: old[k] for k in HAND_KEYS if k in old}
        body = {**m, **keep}
        p.write_text("# GENERATED by scripts/research/lever_map.py --backfill from committed results; `declared` and\n"
                     "# `manifest_notes` are author-owned and preserved. Canonical: OPERATING-PLAN § 2 (research loop).\n"
                     + yaml.safe_dump(body, sort_keys=False, width=140, allow_unicode=True), encoding="utf-8")
    return len(maps)


def append_test(root: Path, subject: str, entry: dict[str, Any]) -> Path:
    """Append one tested lever to a subject's `levers_tested` (cumulative; a repeat of the same unit+family replaces its entry)."""
    p = root / LEVERS_DIR / f"{subject}.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"no lever map for {subject}: run --backfill first")
    head = "".join(ln for ln in p.read_text(encoding="utf-8").splitlines(True) if ln.startswith("#"))
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    lt = [e for e in (d.get("levers_tested") or []) if not (e.get("unit") == entry.get("unit") and e.get("family") == entry["family"])]
    lt.append(entry)
    d["levers_tested"] = lt
    units = list(d.get("units") or [])
    if entry.get("unit") and entry["unit"] not in units:
        d["units"] = units + [entry["unit"]]
    p.write_text(head + yaml.safe_dump(d, sort_keys=False, width=140, allow_unicode=True), encoding="utf-8")
    return p


def summary(maps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for m in maps.values():
        c = by_kind[m["kind"]]
        c["subjects"] += 1
        c["non_empty"] += int(non_empty(m))
        c["with_lever_responses"] += int(bool(m.get("levers")))
        c["with_attribution"] += int((m.get("attribution") or {}).get("read_state") in ("measured", "attributed"))
    return {k: dict(v) for k, v in by_kind.items()}


def _self_test() -> int:
    ok = True

    def check(label: str, cond: bool) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok = ok and cond
    tr = [{"gross_r": 1.0, "net_r": 0.9, "mfe_r": 2.0, "cost_fee_r": 0.1, "entry_time": "2024-01-01", "direction": "long",
           "exit_reason": "tp", "adx_at_entry": 35},
          {"gross_r": -1.0, "net_r": -1.1, "mfe_r": 1.2, "cost_fee_r": 0.1, "entry_time": "2025-01-01", "direction": "short",
           "exit_reason": "stop", "adx_at_entry": 15}]
    a = attribute(tr)
    check("attribution: gross 0 -> no gross edge", a["gross_r"] == 0.0 and a["verdict_hint"].startswith("no gross edge"))
    check("attribution: a loser that reached 1R MFE is counted", a["exit_capture"]["losers_that_reached_1r_mfe"] == 1)
    check("attribution: split by year and ADX bucket", set(a["by_year"]) == {"2024", "2025"} and "30-40" in a["by_adx_at_entry"])
    rec = {"research_unit": "RQ-x", "verdict": "fail", "measurement": {"leg": "L", "grade": {"baseline": "A"}, "arms": {
        "A": {"argv": ["py", "h.py", "--data", "d", "--adx-min", "25", "--tp-r", "3"], "n": 100, "net_r": 10.0,
              "folds": [{"net_r": 1}, {"net_r": 2}]},
        "AD30": {"argv": ["py", "h.py", "--data", "d", "--adx-min", "30", "--tp-r", "3"], "n": 80, "net_r": 14.0,
                 "folds": [{"net_r": 2}, {"net_r": 1}]}}}}
    r = responses_from_record(rec)
    check("responses: the changed flag is the lever, baseline value kept", len(r) == 1 and r[0]["lever"] == "adx_min"
          and r[0]["value"] == "30" and r[0]["baseline_value"] == "25" and r[0]["family"] == "filter")
    check("responses: delta and fold stability", r[0]["delta_net_r"] == 4.0 and r[0]["folds_ge_baseline"] == "1/2")
    flat = shape([{"delta_net_r": 0.5, "baseline_n": 100, "value": "1"}, {"delta_net_r": -0.5, "baseline_n": 100, "value": "2"}])
    check("shape: tiny per-trade deltas read flat", flat["shape"] == "flat")
    pk = shape([{"delta_net_r": -5, "baseline_n": 100, "value": "1", "folds_ge_baseline": "1/4"},
                {"delta_net_r": 8, "baseline_n": 100, "value": "2", "folds_ge_baseline": "3/4"},
                {"delta_net_r": -4, "baseline_n": 100, "value": "3", "folds_ge_baseline": "1/4"}])
    check("shape: interior maximum reads peaked", pk["shape"] == "peaked")
    one = shape([{"delta_net_r": 9, "baseline_n": 100, "value": "x", "folds_ge_baseline": "1/4"}])
    check("shape: one big point is overfit until a holdout", one["shape"] == "single_point" and "overfit" in one["reading"])
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / LEVERS_DIR).mkdir(parents=True)
        (r / LEVERS_DIR / "x.yaml").write_text("subject: x\nstatus: open\nfailure_attribution: {where_lost: side}\nlevers_tested: []\n")
        append_test(r, "x", {"family": "side (short suppression)", "varied": "v", "response": {}, "shape": "s", "tested_at_power": False,
                             "unit": "RQ-1"})
        append_test(r, "x", {"family": "side (short suppression)", "varied": "v2", "response": {}, "shape": "s", "tested_at_power": True,
                             "unit": "RQ-1"})
        d = yaml.safe_load((r / LEVERS_DIR / "x.yaml").read_text())
        check("append: idempotent per unit+family, keeps the hand block", len(d["levers_tested"]) == 1 and d["levers_tested"][0]["varied"] == "v2"
              and d["failure_attribution"]["where_lost"] == "side" and d["units"] == ["RQ-1"])
        mf = io.map_families(d)
        check("schema: free-text family maps to a policy family, power carried", mf == {"direction": {"at_power": True, "tests": ["side (short suppression)"]}})
    check("schema: alias order (regime before gate, signal horizon -> entry)", io.policy_family("regime filter") == "regime_gating"
          and io.policy_family("signal horizon") == "entry" and io.policy_family("predicted-range gate") == "filter")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--subject")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--append", metavar="SUBJECT", help="append one tested lever to the subject's levers_tested")
    ap.add_argument("--family"); ap.add_argument("--varied"); ap.add_argument("--shape"); ap.add_argument("--unit")
    ap.add_argument("--lever-family", help="explicit policy family (else mapped from --family text)")
    ap.add_argument("--at-power", action="store_true"); ap.add_argument("--response-json", default="{}")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    root = Path(a.root)
    if a.append:
        if not (a.family and a.varied and a.shape):
            print("lever_map: --append needs --family, --varied and --shape", file=sys.stderr)
            return 2
        e = {"family": a.family, "varied": a.varied, "response": json.loads(a.response_json), "shape": a.shape,
             "tested_at_power": bool(a.at_power)}
        if a.unit:
            e["unit"] = a.unit
        if a.lever_family:
            e["lever_family"] = a.lever_family
        print(f"lever_map: appended to {append_test(root, a.append, e)}")
        return 0
    try:
        maps = build(root)
    except (OSError, ValueError, KeyError, ImportError, yaml.YAMLError) as exc:   # could not look: say so
        print(f"lever_map: COULD NOT MEASURE -- {exc}", file=sys.stderr)
        return 2
    if a.backfill:
        print(f"lever_map: wrote {write(root, maps)} maps under {LEVERS_DIR}/")
    if a.subject:
        print(yaml.safe_dump(maps.get(a.subject) or {"error": f"no subject {a.subject}"}, sort_keys=False, width=140))
    if a.summary or a.backfill:
        print(json.dumps({"population": "testing + production legs (strategy_status.py) + iteration_subjects.yaml",
                          "by_kind": summary(maps)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
