"""ML serving inventory + slot grouping for GET /api/bot/ml/registry (lane ML-REGISTRY-CONSOLIDATE, 2026-11-09).

Read-only. Joins three things the registry mirror alone cannot: the served / candidate / overlay artifacts that config
consumers reference (config/strategies.yaml, config/overlay_policy.yaml), the display names + slots in
docs/reference/model_names.yaml (the ONE slot mapping), and the account roster (stage from config). Nothing here
decides anything and no model id is renamed. Unknown values stay None (renders "—"); a slot we cannot derive is the
explicit string "unassigned".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

SLOTS = [f"D{i}" for i in range(1, 11)]
UNASSIGNED = "unassigned"
_VERSION_TAIL = re.compile(r"-v\d+[A-Za-z0-9]*$")
# Unnamed models: a slot only from an unambiguous token in the id (never a guess; no match -> "unassigned").
_ID_PATTERNS = [("-regime-", "D2"), ("exit-head", "D8"), ("execution-quality", "D9")]
_REAL = {"real_money", "prop"}


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _json(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def load_names(root: Path) -> tuple[dict, dict]:
    d = _yaml(root / "docs" / "reference" / "model_names.yaml")
    return d.get("breeds") or {}, d.get("models") or {}


def lineage_key(model_id: str) -> str:
    """Card key: the id with its trailing version stripped, so v1/v2 siblings share one card."""
    return _VERSION_TAIL.sub("", model_id)


def breed_of(name: str | None) -> str | None:
    return name.split("-", 1)[0] if name else None


def slot_for(model_id: str, breeds: dict, models: dict) -> tuple[str, str | None, str | None]:
    """(slot, breed, display_name). Per-model `slot:` overrides the breed's; none -> 'unassigned'."""
    m = models.get(model_id) if isinstance(models.get(model_id), dict) else {}
    name = m.get("name")
    breed = breed_of(name)
    slot = m.get("slot") or ((breeds.get(breed) or {}).get("slot") if breed else None)
    if not slot:
        slot = next((s for pat, s in _ID_PATTERNS if pat in model_id), None)  # unambiguous id token only; else unassigned
    return (str(slot) if slot else UNASSIGNED), breed, name


def _stage_from_consumers(consumers: list[dict]) -> str:
    """live = executes live on a real-money/prop account in live mode; testing = executes live on paper only;
    shadow = every consumer shadow; offline = no consumer."""
    if not consumers:
        return "offline"
    if any(c["execution"] == "live" and c["account_class"] in _REAL and c["mode"] == "live" for c in consumers):
        return "live"
    if any(c["execution"] == "live" and c["mode"] == "live" for c in consumers):
        return "testing"
    return "shadow"


def _consumers(strategy_names: list[str], strategies: dict, accounts: dict) -> list[dict]:
    out = []
    for s in strategy_names:
        ex = (strategies.get(s) or {}).get("execution", "live")
        for an, a in accounts.items():
            if isinstance(a, dict) and s in (a.get("strategies") or []):
                out.append({"strategy": s, "account": an, "execution": ex, "mode": a.get("mode"),
                            "account_class": a.get("account_class")})
    return out


def referenced_model_ids(root: Path) -> dict[str, dict]:
    """{model_id: {kind, strategies[], artifact?}} for every id a config consumer references."""
    strategies = (_yaml(root / "config" / "strategies.yaml").get("strategies")
                  or _yaml(root / "config" / "strategies.yaml"))
    refs: dict[str, dict] = {}

    def add(mid, kind, strat, artifact=None):
        if not mid or not isinstance(mid, str):
            return
        r = refs.setdefault(mid, {"kind": kind, "strategies": [], "artifact": artifact})
        if strat not in r["strategies"]:
            r["strategies"].append(strat)
        if artifact and not r["artifact"]:
            r["artifact"] = artifact

    for sname, p in strategies.items():
        if not isinstance(p, dict):
            continue
        add(p.get("model"), "entry", sname, p.get("artifact"))
        add(p.get("exit_head_model"), "exit_head", sname)
        if isinstance(p.get("tp_revision"), dict) and p["tp_revision"].get("rule") == "ml_first_passage":
            add("ml-entry-tp-revision-v1", "tp_revision", sname)
    ov = _yaml(root / "config" / "overlay_policy.yaml")
    for sname, p in ((ov.get("strategies") or ov) if isinstance(ov, dict) else {}).items():
        if isinstance(p, dict) and p.get("artifact"):
            add("overlay-" + Path(p["artifact"]).stem.replace("overlay_", "") + "-v1", "overlay", sname,
                "ml/overlay/" + p["artifact"])
    return refs


def _artifact_index(root: Path) -> dict[str, tuple[str, str]]:
    """model_id (from model.json) or dir-derived id -> (source, relative dir/file)."""
    idx: dict[str, tuple[str, str]] = {}
    for src, sub in (("served", "ml/served"), ("candidate", "ml/candidates")):
        base = root / sub
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            mj = _json(d / "model.json") if d.is_dir() else None
            if mj:
                idx[str(mj.get("model_id") or d.name)] = (src, f"{sub}/{d.name}")
                idx.setdefault("dir:" + d.name, (src, f"{sub}/{d.name}"))
    return idx


SERVED_MODELS_REL = "ml/served/SERVED_MODELS.yaml"


def load_served_models(root: Path) -> dict[str, dict]:
    """{model_id: entry} from ml/served/SERVED_MODELS.yaml (row ML-REGISTRY-SERVED-MODELS-NO-STAGE). {} if absent."""
    d = _yaml(root / SERVED_MODELS_REL)
    m = d.get("models") if isinstance(d, dict) else None
    return {str(k): v for k, v in (m or {}).items() if isinstance(v, dict)}


def apply_served_declaration(row: dict, served: dict[str, dict]) -> None:
    """Stamp target_deployment_stage + headline_metric on an inventory row from the declaration, in place.

    Undeclared -> both stay None (renders "—") and ``stage_read_state`` says "undeclared", never a guessed stage."""
    ent = served.get(row["model_id"])
    if not ent:
        row.update({"target_deployment_stage": None, "headline_metric": None, "stage_read_state": "undeclared",
                    "stage_source": None})
        return
    row.update({"target_deployment_stage": ent.get("stage"), "stage_basis": ent.get("stage_basis"),
                "headline_metric": ent.get("headline_metric"), "stage_read_state": "declared",
                "stage_source": SERVED_MODELS_REL})


def inventory_rows(root: Path) -> list[dict]:
    breeds, models = load_names(root)
    served = load_served_models(root)
    strategies = _yaml(root / "config" / "strategies.yaml")
    strategies = strategies.get("strategies") or strategies
    accounts = (_yaml(root / "config" / "accounts.yaml") or {}).get("accounts") or {}
    idx = _artifact_index(root)
    served_ptr = (_json(root / "ml" / "served" / "ENTRY_SERVED.json") or {}).get("artifact_dir")
    rows: list[dict] = []
    for mid, ref in sorted(referenced_model_ids(root).items()):
        art = ref.get("artifact")
        if ref["kind"] == "overlay":
            source, path = "overlay", art
        elif ref["kind"] == "exit_head":
            source, path = "served", f"runtime_logs/trainer_mirror/exit_head/{mid}.json"
        elif art:
            source, path = "candidate", art.rsplit("/", 1)[0] if art.endswith("model.json") else art
        elif mid in idx or "dir:" + mid.replace("-", "_") in idx:
            source, path = idx.get(mid) or idx["dir:" + mid.replace("-", "_")]
        else:
            source, path = "served", None
        cons = _consumers(ref["strategies"], strategies, accounts)
        slot, breed, name = slot_for(mid, breeds, models)
        row = _row(mid, source, path, cons, slot, breed, name, ref["kind"])
        if mid == "ml-decision-entry-v1" and served_ptr:
            row["served_artifact_dir"] = f"ml/served/{served_ptr}"
            row["notes"] = "served pointer ml/served/ENTRY_SERVED.json repoints this id to the artifact dir above"
            sib = f"ml-decision-entry-{served_ptr.split('entry_')[-1]}"
            if sib in idx and sib not in {r["model_id"] for r in rows}:
                rows.append(_row(sib, "served", idx[sib][1], cons, slot, breed, name, "entry"))
                rows[-1]["display_name"] = f"{name} (refit r20261106)" if name else sib
                rows[-1]["pointer_sibling"] = True
                rows[-1]["notes"] = "refit artifact the ENTRY_SERVED.json pointer serves for ml-decision-entry-v1"
        rows.append(row)
    for r in rows:
        apply_served_declaration(r, served)
    return rows


def _row(mid, source, path, cons, slot, breed, name, kind) -> dict:
    return {
        "model_id": mid, "display_name": name or mid, "slot": slot, "breed": breed,
        "source": source, "artifact_path": path, "artifact_kind": kind,
        "consumers": cons,
        "consuming_strategies": sorted({c["strategy"] for c in cons}),
        "consuming_accounts": sorted({c["account"] for c in cons}),
        "deployment_bucket": {"live": "LIVE", "testing": "SHADOW", "shadow": "SHADOW"}.get(_stage_from_consumers(cons), "OFFLINE"),
        "stage_from_config": _stage_from_consumers(cons),
        "model_family": None, "linked_strategies": sorted({c["strategy"] for c in cons}),
    }


def _chip(row: dict) -> str:
    st = row.get("stage_from_config")
    if st:
        return st
    return {"LIVE": "live", "SHADOW": "shadow"}.get(row.get("deployment_bucket"), "offline")


def build_by_slot(rows: list[dict], root: Path) -> dict[str, Any]:
    """slot -> {title, breeds: {breed -> [card]}}; every slot D1..D10 present; 'unassigned' only when used."""
    breeds, models = load_names(root)
    slots: dict[str, dict] = {s: {"breeds": {}} for s in SLOTS}
    rank = {"live": 0, "testing": 1, "shadow": 2, "offline": 3}
    for r in rows:
        slot = r.get("slot") or UNASSIGNED
        breed = r.get("breed") or "—"
        bucket = slots.setdefault(slot, {"breeds": {}})["breeds"].setdefault(breed, {})
        card = bucket.setdefault(lineage_key(r["model_id"]), {"lineage": lineage_key(r["model_id"]), "variants": [], "status": "offline"})
        chip = _chip(r)
        card["variants"].append({
            "model_id": r["model_id"], "display_name": r.get("display_name") or r["model_id"], "status": chip,
            "source": r.get("source") or "registry", "consuming_strategies": r.get("consuming_strategies") or [],
            "consuming_accounts": r.get("consuming_accounts") or [],
        })
        if rank[chip] < rank[card["status"]] or not card.get("status_set"):
            card["status"], card["status_set"] = chip, True
    out: dict[str, Any] = {}
    for s, v in slots.items():
        out[s] = {"breeds": {b: sorted((dict((k, x) for k, x in c.items() if k != "status_set") for c in cards.values()),
                                       key=lambda c: c["lineage"]) for b, cards in sorted(v["breeds"].items())}}
        out[s]["model_count"] = sum(len(c["variants"]) for cs in out[s]["breeds"].values() for c in cs)
        out[s]["empty"] = out[s]["model_count"] == 0
    return out


def decorate_registry_rows(rows: list[dict], root: Path) -> None:
    """Add display_name + slot + breed to every mirror row, in place (additive)."""
    breeds, models = load_names(root)
    for r in rows:
        slot, breed, name = slot_for(str(r.get("model_id")), breeds, models)
        if slot == UNASSIGNED and r.get("model_family") == "classification_hmm":
            pass  # no guess: leave unassigned
        r["display_name"], r["slot"], r["breed"] = name or r.get("model_id"), slot, breed
        r.setdefault("source", "registry")
