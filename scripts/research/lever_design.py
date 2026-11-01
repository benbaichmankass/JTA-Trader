#!/usr/bin/env python3
# wiring: scripts/research/queue_replenish.py (structured templates: roster-walkforward, leg-corpus-s1) -> research/queue units
"""STRUCTURED LEVER DESIGN for generated research units (lane RESEARCH-TEMPLATES-STRUCTURED, 2026-11-01).

OPERATING-PLAN § 2 "THE research workflow" step 1+4: the first test of a subject is never one configuration. It is the BASE as
the control arm plus ONE-FACTOR sweeps of the subject's levers, and the lever tested NEXT is read from the lever map
(`research/levers/<subject>.yaml`), never picked at random. This module is the pure chooser the templates share:

  next_lever(...)  an UNTESTED family first, then the family the subject's attribution points at, then a family whose
                   measured response is noisy / single-point, then the least-tested one. Only families that have at least one
                   lever KEY in the subject's config (or a `declared:` entry in its map) are candidates -- a lever the harness
                   cannot vary is not a lever of this subject.
  arms_for(...)    control `A=` plus, for each numeric key of the chosen family, a low and a high step (x0.75, x1.25; ints
                   rounded, floor 1). `declared:` entries carry their own `values` and win over the config-derived steps.
  design_block(..) the `iteration:` mapping a unit carries (lever, why, map entries, arms counted, multiple-testing).

DEFAULTS, never refusals (the plan's "Gates this adds or changes: none"). A subject with no map, no config keys, or no
harness-varied lever gets the control arm alone and `design_gap` says why -- the unit still runs.
No network, no writes. `python3 scripts/research/lever_design.py --self-test`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "scripts" / "research"), str(REPO)]

STEPS = (("lo", 0.75), ("hi", 1.25))
MAX_KEYS_PER_LEVER = 2          # bounds one unit to <= 1 + 2 keys x 2 steps = 5 arms
#: keys that name the harness, a window or a structure, not a tunable: never perturbed
_NOT_A_LEVER = {"symbols", "timeframe", "enabled", "execution", "risk_pct", "weight", "tp_revision"}


def _yaml(p: Path) -> dict[str, Any]:
    import yaml
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def lever_of(key: str) -> str | None:
    from iteration_orphans import _lever_of
    return _lever_of(key)


def config_levers(cfg: dict[str, Any]) -> dict[str, list[str]]:
    """family -> the numeric (non-bool) config keys of that family, sorted. Keys the harness cannot vary are not listed."""
    out: dict[str, list[str]] = {}
    for k in sorted(cfg):
        v = cfg[k]
        if k in _NOT_A_LEVER or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        fam = lever_of(k)
        if fam and not (fam == "exit" and k.startswith("tp_") and cfg.get("tp_revision")):
            out.setdefault(fam, []).append(k)
    return out


def declared_levers(map_doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """`declared:` of research/levers/<subject>.yaml -> family -> [{key, values?}]. Accepts a list of
    {family, key, values} or a mapping family -> [key | {key, values}]. Anything else is ignored (author-owned, free-form)."""
    d = map_doc.get("declared")
    out: dict[str, list[dict[str, Any]]] = {}
    if isinstance(d, list):
        for e in d:
            if isinstance(e, dict) and e.get("family") and e.get("key"):
                out.setdefault(str(e["family"]), []).append(e)
    elif isinstance(d, dict):
        for fam, es in d.items():
            for e in (es if isinstance(es, list) else []):
                out.setdefault(str(fam), []).append(e if isinstance(e, dict) else {"key": str(e)})
    return out


def attribution_family(attr: dict[str, Any]) -> tuple[str | None, str]:
    """The family the attribution points at, and the row it read. (None, why) when it is not measured / decisive."""
    if not isinstance(attr, dict) or attr.get("read_state") != "measured":
        return None, "attribution not measured"
    eq, ec = attr.get("entry_quality") or {}, attr.get("exit_capture") or {}
    n = attr.get("n") or 0
    losers_1r, share1r = ec.get("losers_that_reached_1r_mfe"), eq.get("share_mfe_ge_1r")
    if attr.get("cost_share_of_gross") is not None and attr["cost_share_of_gross"] > 0.4:
        return "sizing_vs_cost", f"cost is {attr['cost_share_of_gross']:.0%} of gross R"
    if losers_1r and n and losers_1r / n >= 0.15:
        return "exit", f"{losers_1r} of {n} trades were losers that had reached 1R (exit capture)"
    if share1r is not None and share1r < 0.35:
        return "entry", f"only {share1r:.0%} of trades reach 1R MFE (entry quality)"
    years = attr.get("by_year") or {}
    nets = [v.get("net_r") for _, v in sorted(years.items()) if isinstance(v, dict) and v.get("net_r") is not None]
    if len(nets) >= 2 and nets[-1] < 0 < max(nets[:-1]):
        return "regime_gating", f"latest year net R {nets[-1]:+.2f} vs earlier {max(nets[:-1]):+.2f} (regime-dependent)"
    return None, "attribution not decisive"


def next_lever(map_doc: dict[str, Any], families: list[str], available: list[str]) -> dict[str, Any]:
    """Pick the family to sweep next. `families` is policy order; `available` those the subject can vary."""
    manifest = map_doc.get("manifest") or {}
    levers = map_doc.get("levers") or {}
    cand = [f for f in families if f in available]
    if not cand:
        return {"lever": None, "why": "no lever family of this subject has a key the harness can vary",
                "map_entries": [], "basis": "none"}
    untested = [f for f in cand if manifest.get(f, "untested") != "tested"]
    if untested:
        return {"lever": untested[0], "basis": "untested_family", "map_entries": [],
                "why": f"{untested[0]} is the first lever family with no measured response in the map "
                       f"({len(untested)} of {len(cand)} variable families untested)"}
    fam, row = attribution_family(map_doc.get("attribution") or {})
    if fam in cand:
        return {"lever": fam, "basis": "attribution", "why": f"every variable family has a reading; attribution points at {fam}: {row}",
                "map_entries": [f"{fam}: {sorted((levers.get(fam) or {}))}"]}
    for f in cand:
        ent = {k: e.get("shape") for k, e in (levers.get(f) or {}).items() if isinstance(e, dict)}
        unres = sorted(k for k, sh in ent.items() if sh in ("noisy", "single_point", "no_reading"))
        if unres:
            return {"lever": f, "basis": "unresolved_shape", "map_entries": [f"{f}.{k}: {ent[k]}" for k in unres],
                    "why": f"{f} has a noisy / single-point / unread response on {unres} -- a finer sweep, not a verdict"}
    least = min(cand, key=lambda f: sum(len((e or {}).get("tests") or []) for e in (levers.get(f) or {}).values()))
    return {"lever": least, "basis": "least_tested", "map_entries": [f"{least}: fewest recorded tests"],
            "why": f"every variable family has a smooth reading; {least} has the fewest recorded tests"}


def _step(v: Any, f: float) -> Any:
    nv = float(v) * f
    return max(1, int(round(nv))) if isinstance(v, int) else round(nv, 6)


def arms_for(cfg: dict[str, Any], keys: list[str], declared: list[dict[str, Any]] | None = None
             ) -> list[tuple[str, str]]:
    """[(label, spec)] with the control `A=` first. One factor at a time; duplicate settings are dropped."""
    arms: list[tuple[str, str]] = [("A", "")]
    seen: set = set()
    plan: list[tuple[str, list[Any]]] = []
    for e in (declared or []):
        if e.get("values"):
            plan.append((str(e["key"]), list(e["values"])))
    for k in keys:
        if k not in {p[0] for p in plan} and k in cfg:
            plan.append((k, [_step(cfg[k], f) for _, f in STEPS]))
    for k, vals in plan[:MAX_KEYS_PER_LEVER]:
        for i, v in enumerate(vals):
            if (k, v) in seen or cfg.get(k) == v:
                continue
            seen.add((k, v))
            arms.append((f"{k}_{('lo', 'hi')[i] if i < 2 else 'v' + str(i)}", f"{k}={v}"))
    return arms


def design_block(subject: str, kind: str, cfg: dict[str, Any], map_doc: dict[str, Any], families: list[str],
                 *, fam_override: str | None = None) -> dict[str, Any]:
    """Everything a generated unit stamps for a structured design. `arms` is [] only when no lever can be varied."""
    cl = config_levers(cfg)
    dl = declared_levers(map_doc)
    available = [f for f in families if f in cl or f in dl]
    pick = ({"lever": fam_override, "basis": "template_fixed", "why": f"{fam_override} is this template's lever", "map_entries": []}
            if fam_override else next_lever(map_doc, families, available))
    fam = pick["lever"]
    arms = arms_for(cfg, cl.get(fam, []), dl.get(fam)) if fam else [("A", "")]
    out = {"subject": subject, "subject_kind": kind, "lever": fam, "lever_basis": pick["basis"], "why_this_lever": pick["why"],
           "map_entries": pick["map_entries"], "arms": [[a, s] for a, s in arms], "k_variants": len(arms) - 1}
    base, attr = map_doc.get("baseline") or {}, map_doc.get("attribution") or {}
    out["from_result"] = str(base.get("record") or f"none: {subject} has no Stage-0 record (first measurement)")
    out["verdict_read"] = str(base.get("rule_verdict") or base.get("verdict") or "pending")
    hint = attr.get("verdict_hint")
    out["diagnosis"] = (f"{subject}: baseline net R {base.get('net_r')} on n {base.get('n')}; attribution "
                        f"{('read: ' + str(hint)) if hint else 'not yet measured'}; lever map reads "
                        f"{sum(1 for v in (map_doc.get('manifest') or {}).values() if v == 'tested')} of "
                        f"{len(map_doc.get('manifest') or {})} lever families tested. {pick['why']}.")
    if len(arms) < 2:
        out["design_gap"] = pick.get("why") if not fam else f"{fam}: no numeric key to step in the config and no `declared:` values"
    return out


def read_map(root: Path, subject: str) -> dict[str, Any]:
    return _yaml(root / "research" / "levers" / f"{subject}.yaml")


def families_for(root: Path, kind: str) -> list[str]:
    pol = _yaml(root / "scripts/research/family_retirement_policy.yaml")
    return list((pol.get("lever_families") or {}).get(kind) or [])


def _self_test() -> int:
    cfg = {"symbols": ["X"], "timeframe": "1d", "donchian": 20, "atr_stop_mult": 2.5, "trail_mult": 3, "adx_min": 20.0,
           "tp_r": 3.0, "enabled": True}
    cl = config_levers(cfg)
    assert cl == {"entry": ["donchian"], "exit": ["atr_stop_mult", "tp_r", "trail_mult"], "filter": ["adx_min"]}, cl
    fams = ["entry", "exit", "filter", "regime_gating"]
    avail = [f for f in fams if f in cl]
    m0 = {"manifest": {"entry": "untested", "exit": "untested", "filter": "untested"}}
    assert next_lever(m0, fams, avail)["lever"] == "entry"
    m1 = {"manifest": {"entry": "tested", "exit": "tested", "filter": "tested"}, "levers": {},
          "attribution": {"read_state": "measured", "n": 20, "exit_capture": {"losers_that_reached_1r_mfe": 5}}}
    r = next_lever(m1, fams, avail)
    assert r["lever"] == "exit" and r["basis"] == "attribution", r
    m2 = {"manifest": {f: "tested" for f in avail}, "levers": {"filter": {"adx": {"shape": "noisy", "tests": [1]}}},
          "attribution": {"read_state": "measured", "n": 20}}
    assert next_lever(m2, fams, avail)["basis"] == "unresolved_shape"
    assert next_lever(m0, fams, [])["lever"] is None
    arms = arms_for(cfg, ["donchian"])
    assert arms == [("A", ""), ("donchian_lo", "donchian=15"), ("donchian_hi", "donchian=25")], arms
    d = arms_for(cfg, ["adx_min"], [{"key": "adx_min", "values": [15, 25]}])
    assert [s for _, s in d] == ["", "adx_min=15", "adx_min=25"], d
    blk = design_block("s", "strategy_leg", cfg, m0, fams)
    assert blk["lever"] == "entry" and blk["k_variants"] == 2 and "design_gap" not in blk
    gap = design_block("s", "strategy_leg", {"timeframe": "1d"}, m0, fams)
    assert gap["arms"] == [["A", ""]] and gap["design_gap"], gap
    assert design_block("s", "strategy_leg", cfg, m0, fams, fam_override="sizing_vs_cost")["lever"] == "sizing_vs_cost"
    assert json.dumps(blk)  # serialisable: it travels in generated.params
    print("self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test() if "--self-test" in sys.argv else 0)
