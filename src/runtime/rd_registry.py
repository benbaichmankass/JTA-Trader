"""R&D registry: ONE entry per IDEA (a strategy or an ML model/idea), never per research unit.

Operator ask, 2026-11-12 12:22Z (lane RD-REGISTRY): an ML + strategy testing registry "so that I can keep
track of ... what different ideas we have for different strategies and MLs, and where each of them stand.
What's been tested, what's failed, what's in iterations, what's on".

This is a READ projection. It writes nothing anywhere except the file the CLI asks it to write, gates
nothing, refuses nothing (CLAUDE.md "No new gates"). Every stage is COMPUTED from fields by the ordered
rule list ``STAGE_RULES`` (published in the output), never typed by hand. A null stays null (render
"—"); every source carries a read_state so "we could not look" never reads as "nothing there".

Sources (all committed to this repo except the optional live ML registry rows):
  research/queue/*.yaml (+ blocked/) via ``src.runtime.research_catalog`` (status, verdict per unit)
  config/strategies.yaml + config/accounts.yaml via ``scripts.ops.strategy_status`` (production/testing/inactive)
  comms/strategy_evidence/<leg>.json (Stage-0 offline edge record per leg)
  ML registry rows: live ``/api/bot/ml/registry`` rows when the caller passes them, else the newest
    committed snapshot comms/ml_consolidation/*.json (bucket LIVE / SHADOW / OFFLINE per model)
  docs/reference/model_names.yaml (display names), docs/plans/ml-plan-items.yaml (ML ideas)
  research/programmes/*.yaml (question nodes; an open needs_authoring with no unit = an idea not yet authored)
  docs/claude/work/checklist/ via ``src.runtime.checklist_store`` (owner rows)

Unit -> idea attribution (each unit to exactly ONE idea, first match wins; ``ATTRIBUTION`` in the output):
  1. the unit is the ``ref`` of an ML plan item            -> that ML plan item
  2. iteration.subject / generated.params.leg / run.inputs.{leg,strategy,legs} (one token) -> that subject
  3. a strategies.yaml leg id or an ML registry model id in the title (longest match) -> that leg / model
  4. programme_node.node (or a programme node whose ``unit`` is this unit)           -> that programme question
  5. otherwise the unit is UNATTRIBUTED and counted in ``summary.unattributed_units`` (never dropped)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from src.runtime import research_catalog as rc

SCHEMA = 1
REPO_BLOB = rc.REPO_BLOB

STRATEGY, ML = "STRATEGY", "ML"
STAGES = ("idea", "queued", "testing_offline", "failed", "iterating", "passed_waiting",
          "testing_book", "production", "shadow_advisory", "retired", "stuck")
STAGE_LABEL = {
    "idea": "idea (not yet authored)", "queued": "queued", "testing_offline": "testing offline (Stage 0 running)",
    "failed": "failed", "iterating": "iterating (failed, open iteration unit)",
    "passed_waiting": "passed, waiting to promote", "testing_book": "testing book (Stage 1 demo floor)",
    "production": "production (real money)", "shadow_advisory": "shadow / advisory (ML)",
    "retired": "retired (by record)", "stuck": "stuck",
}

#: The rule that sets each stage, in evaluation order. First rule that holds wins.
STAGE_RULES: list[dict[str, str]] = [
    {"stage": "retired", "rule": "strategy leg has enabled: false in config/strategies.yaml (the retirement record), "
                                 "or ML plan item state == killed"},
    {"stage": "production", "rule": "strategy leg is on a real-money roster (bybit_2 / alpaca_live / ib_live) and not retired "
                                    "(scripts/ops/strategy_status.py == production)"},
    {"stage": "production", "rule": "ML model: a registry consumer is a real-money account (consumer account_class real_money, "
                                    "or the account is bybit_2 / alpaca_live / ib_live) -- the one ladder: a model reaches a "
                                    "book the way a strategy does (row ML-ONE-LADDER)"},
    {"stage": "testing_book", "rule": "ML model: a registry consumer is any other book (paper / prop) and none is real money"},
    {"stage": "shadow_advisory", "rule": "ML model with NO order consumer whose registry deployment_bucket is LIVE (advisory) or "
                                         "SHADOW -- a housekeeping label, not a step to real money (operator 2026-11-12)"},
    {"stage": "testing_book", "rule": "strategy leg is on a general paper roster (bybit_1 / alpaca_paper / ib_paper), not retired, "
                                      "not production"},
    {"stage": "stuck", "rule": "ML plan item state == parked (reason = the item's close text)"},
    {"stage": "idea", "rule": "no research unit attributed to the idea (e.g. a programme node with an open needs_authoring and "
                              "no unit), or an ML plan item whose ref is an open build row"},
    {"stage": "iterating", "rule": "EFFECTIVE verdict = the unit verdict, except pass with grading.confirmation not_replicated "
                                   "reads fail and pass with confirmation underpowered reads indeterminate. Latest graded edge verdict (pass/fail/indeterminate, by latestResultAt) is fail AND an "
                                   "attributed unit is open (due/dispatched/running/queued)"},
    {"stage": "failed", "rule": "latest graded edge verdict is fail and no attributed unit is open (reason = that unit's result note)"},
    {"stage": "passed_waiting", "rule": "latest graded edge verdict is pass and no attributed unit is open"},
    {"stage": "testing_offline", "rule": "an attributed unit is due/dispatched/running and at least one of those is not flagged stuck"},
    {"stage": "stuck", "rule": "every due/dispatched/running unit is flagged stuck by the catalog (reason = its stuckReason)"},
    {"stage": "queued", "rule": "an attributed unit is queued (not yet due)"},
    {"stage": "stuck", "rule": "the only non-closed attributed units are blocked (reason = the blocked_on text)"},
    {"stage": "stuck", "rule": "latest graded verdict is indeterminate and no unit is open (reason: no iteration authored)"},
    {"stage": "stuck", "rule": "no graded edge verdict and no open unit (only retired / wiring / no-action units)"},
]
ATTRIBUTION = [
    "ml_plan_ref: the unit is the ref of an item in docs/plans/ml-plan-items.yaml",
    "declared_subject: iteration.subject | generated.params.leg | run.inputs.leg/strategy/legs (single token)",
    "title_match: the longest strategies.yaml leg id or ML registry model id contained in the unit title",
    "programme_node: programme_node.node, or a research/programmes node whose unit: is this unit",
    "unattributed: none of the above; counted in summary.unattributed_units",
]

OPEN = ("due", "dispatched", "running", "queued")
RUNNING = ("due", "dispatched", "running")
EDGE_VERDICTS = ("pass", "fail", "indeterminate")
PLAN_IDEA_TRACKS = ("S", "R", "X", "N", "F")
#: programme -> track. P6 (data infra) holds builds, not strategy/ML ideas, so it is not projected.
PROGRAMME_TRACK = {"P1": STRATEGY, "P2": ML, "P3": STRATEGY, "P4": STRATEGY, "P5": STRATEGY,
                   "P7": STRATEGY, "P8": STRATEGY}
CLOSED_ROW_STATES = {"done", "killed", "closed", "retired", "superseded", "dropped", "cancelled"}
_RQ = re.compile(r"^RQ-[0-9A-Za-z-]+$")
_TOKEN = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ── small readers ────────────────────────────────────────────────────────────────────────────
def _yaml(path: Path) -> tuple[Any, str]:
    if not path.is_file():
        return None, "missing"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"unreadable: {type(exc).__name__}"


def _json(path: Path) -> tuple[Any, str]:
    if not path.is_file():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"unreadable: {type(exc).__name__}"


def _blocked_text(doc: dict) -> str | None:
    """blocked_on as one readable line: a list of {ref, what} dicts, a dict, or a string."""
    bo = doc.get("blocked_on")
    if isinstance(bo, list):
        parts = [f"{x.get('ref') or x.get('kind') or ''}: {x.get('what') or ''}".strip(": ") if isinstance(x, dict) else str(x)
                 for x in bo]
        return rc._text("; ".join(p for p in parts if p), 300)
    if isinstance(bo, dict):
        return rc._text(" ".join(str(v) for v in bo.values() if isinstance(v, str)), 300)
    return rc._text(bo, 300) or rc._text(doc.get("blocked_reason"), 300)


def _raw_verdict(u: dict) -> str | None:
    v = u.get("verdict")
    return str(v).strip().lower() if v not in (None, "") else None


def _verdict(u: dict) -> str | None:
    """EFFECTIVE verdict: a pass the held-out confirmation did not replicate is not a pass
    (grading.confirmation; row RESEARCH-SLO-SURVIVOR-CONVERSION)."""
    v = _raw_verdict(u)
    c = str(u.get("confirmation") or "").lower()
    if v == "pass" and c == "not_replicated":
        return "fail"
    if v == "pass" and c == "underpowered":
        return "indeterminate"
    return v


def load_queue_docs(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    q = root / "research" / "queue"
    for sub in (q, q / "blocked"):
        if not sub.is_dir():
            continue
        for p in sorted(sub.glob("*.yaml")):
            doc, _ = _yaml(p)
            if isinstance(doc, dict):
                out[str(doc.get("id") or p.stem)] = doc
    return out


def load_ml_registry(root: Path, live_rows: list[dict] | None) -> tuple[list[dict], dict]:
    """[{model_id, bucket, slot, display, family}], read_state. Live rows win; else newest committed snapshot."""
    if live_rows:
        rows = [{"model_id": r.get("model_id"), "bucket": r.get("deployment_bucket"), "slot": r.get("slot"),
                 "display": r.get("display_name"), "family": r.get("model_family"),
                 "consumers": [{"account": c.get("account"), "strategy": c.get("strategy"),
                                "account_class": c.get("account_class")}
                               for c in (r.get("consumers") or []) if isinstance(c, dict)]}
                for r in live_rows if isinstance(r, dict) and r.get("model_id")]
        return rows, {"state": "ok", "source": "live /api/bot/ml/registry rows", "n": len(rows)}
    snaps = sorted((root / "comms" / "ml_consolidation").glob("*.json"))
    if not snaps:
        return [], {"state": "missing", "source": "comms/ml_consolidation/*.json", "n": None}
    doc, st = _json(snaps[-1])
    if not isinstance(doc, dict):
        return [], {"state": st, "source": snaps[-1].relative_to(root).as_posix(), "n": None}
    rows = [{"model_id": m.get("model_id"), "bucket": m.get("bucket"), "slot": m.get("slot"),
             "display": m.get("display"), "family": m.get("family"),
             "consumers": [{"account": a, "strategy": None, "account_class": None} for a in (m.get("cons_acc") or [])]}
            for m in doc.get("models") or [] if isinstance(m, dict) and m.get("model_id")]
    return rows, {"state": "snapshot", "source": snaps[-1].relative_to(root).as_posix(),
                  "as_of": doc.get("as_of"), "n": len(rows)}


def _declared_subject(d: dict) -> tuple[str | None, str | None]:
    it = d.get("iteration")
    if isinstance(it, dict) and isinstance(it.get("subject"), str) and it["subject"].strip():
        return it["subject"].strip(), str(it.get("subject_kind") or "")
    g = d.get("generated") if isinstance(d.get("generated"), dict) else {}
    p = g.get("params") if isinstance(g.get("params"), dict) else {}
    if isinstance(p.get("leg"), str) and _TOKEN.match(p["leg"]):
        return p["leg"], "strategy_leg"
    run = d.get("run") if isinstance(d.get("run"), dict) else {}
    ri = run.get("inputs") if isinstance(run.get("inputs"), dict) else {}
    for k in ("leg", "strategy", "legs"):
        v = ri.get(k)
        if isinstance(v, str) and v and _TOKEN.match(v):
            return v, "strategy_leg"
    return None, None


# ── stage ────────────────────────────────────────────────────────────────────────────────────
def offline_stage(units: list[dict]) -> tuple[str, str | None, dict | None]:
    """(stage, reason, latest graded unit) from attributed catalog units. Mirrors STAGE_RULES after 'idea'."""
    if not units:
        return "idea", "no research unit attributed", None
    graded = [u for u in units if _verdict(u) in EDGE_VERDICTS]
    latest = max(graded, key=lambda u: u.get("latestResultAt") or u.get("lastActivity") or "") if graded else None
    lv = _verdict(latest) if latest else None
    open_ = [u for u in units if u["status"] in OPEN]
    running = [u for u in open_ if u["status"] in RUNNING]
    if lv == "fail":
        if open_:
            return "iterating", f"latest {latest['id']} failed; open: {', '.join(u['id'] for u in open_[:3])}", latest
        return "failed", latest.get("resultNote") or f"{latest['id']} verdict fail", latest
    if lv == "pass" and not open_:
        return "passed_waiting", f"{latest['id']} passed; no open unit", latest
    if running:
        live = [u for u in running if not u.get("stuck")]
        if live:
            return "testing_offline", f"{len(live)} unit(s) due/dispatched/running", latest
        return "stuck", running[0].get("stuckReason"), latest
    if any(u["status"] == "queued" for u in open_):
        return "queued", f"{sum(1 for u in open_ if u['status'] == 'queued')} unit(s) queued", latest
    blocked = [u for u in units if u["status"] == "blocked"]
    if blocked:
        return "stuck", blocked[0].get("blockedReason") or "blocked", latest
    if lv == "indeterminate":
        return "stuck", f"latest {latest['id']} indeterminate and no iteration unit is open", latest
    return "stuck", "no graded edge verdict and no open unit", latest


def _result(u: dict | None) -> dict | None:
    if not u:
        return None
    du = u.get("dataUsed") or {}
    metrics = {k: v for k, v in (u.get("metrics") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return {"unit": u["id"], "verdict": _verdict(u), "verdict_raw": _raw_verdict(u),
            "confirmation": u.get("confirmation"), "date": u.get("latestResultAt"),
            "metrics": dict(list(metrics.items())[:4]) or None,
            "population": du.get("population"), "n": du.get("n"),
            "note": u.get("resultNote"), "title": u.get("title")}


def _counts(units: list[dict]) -> dict[str, int]:
    v = [_verdict(u) for u in units]
    return {"units": len(units), "passed": v.count("pass"), "failed": v.count("fail"),
            "indeterminate": v.count("indeterminate"),
            "open": sum(1 for u in units if u["status"] in OPEN),
            "blocked": sum(1 for u in units if u["status"] == "blocked")}


# ── build ────────────────────────────────────────────────────────────────────────────────────
def build_registry(root: Path, *, now: datetime | None = None, catalog: dict | None = None,
                   live_registry_rows: list[dict] | None = None,
                   previous: dict | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    read_state: dict[str, Any] = {}

    cat = catalog or rc.build_catalog(root, now=now)
    units = {u["id"]: u for u in cat.get("units") or []}
    read_state["research_catalog"] = {"state": "ok" if units and not cat.get("readErrors") else
                                      ("partial" if units else "unreadable"),
                                      "n": len(units) if units else None, "read_errors": len(cat.get("readErrors") or [])}
    docs = load_queue_docs(root)
    for uid, u in list(units.items()):
        d = docs.get(uid)
        if not d:
            continue
        g = d.get("grading") if isinstance(d.get("grading"), dict) else {}
        conf = g.get("confirmation") if isinstance(g.get("confirmation"), str) else None
        units[uid] = {**u, "confirmation": conf,
                      "blockedReason": (_blocked_text(d) or u.get("blockedReason")) if u.get("status") == "blocked"
                      else u.get("blockedReason")}

    # strategies
    try:
        from scripts.ops import strategy_status as ss
        status_table = ss.table(root)
        accounts, strategies = ss.load(root)
        ros = ss.rosters(accounts)
        read_state["strategy_status"] = {"state": "ok" if status_table else "unreadable",
                                         "n": len(status_table) if status_table else None}
    except Exception as exc:  # noqa: BLE001 -- surfaced as read_state, never as an empty fleet
        status_table, strategies, ros = {}, {}, {}
        read_state["strategy_status"] = {"state": f"unreadable: {type(exc).__name__}", "n": None}

    reg_rows, read_state["ml_registry"] = load_ml_registry(root, live_registry_rows)
    reg = {r["model_id"]: r for r in reg_rows}
    names_doc, st = _yaml(root / "docs" / "reference" / "model_names.yaml")
    model_names = (names_doc or {}).get("models") or {} if isinstance(names_doc, dict) else {}
    read_state["model_names"] = {"state": st, "n": len(model_names) if st == "ok" else None}
    plan_doc, st = _yaml(root / "docs" / "plans" / "ml-plan-items.yaml")
    plan_items = [i for i in ((plan_doc or {}).get("items") or []) if isinstance(i, dict)] if isinstance(plan_doc, dict) else []
    read_state["ml_plan_items"] = {"state": st, "n": len(plan_items) if st == "ok" else None}

    nodes: dict[str, dict] = {}
    prog_files = sorted((root / "research" / "programmes").glob("*.yaml"))
    bad = 0
    for p in prog_files:
        d, st = _yaml(p)
        if not isinstance(d, dict):
            bad += 1
            continue
        for n in d.get("nodes") or []:
            if isinstance(n, dict) and n.get("id"):
                nodes[str(n["id"])] = {**n, "_programme": d.get("programme"), "_file": p.relative_to(root).as_posix()}
    read_state["programmes"] = {"state": "ok" if prog_files and not bad else ("partial" if nodes else "unreadable"),
                                "files": len(prog_files), "nodes": len(nodes) if nodes else None}

    try:
        from src.runtime import checklist_store
        rows = [r for r in (checklist_store.load(root).get("items") or []) if isinstance(r, dict)]
        read_state["checklist"] = {"state": "ok", "n": len(rows)}
    except Exception as exc:  # noqa: BLE001
        rows = []
        read_state["checklist"] = {"state": f"unreadable: {type(exc).__name__}", "n": None}
    open_rows = [r for r in rows if str(r.get("state") or "").lower() not in CLOSED_ROW_STATES]

    ev_dir = root / "comms" / "strategy_evidence"
    read_state["strategy_evidence"] = {"state": "ok" if ev_dir.is_dir() else "missing",
                                       "n": len(list(ev_dir.glob("*.json"))) if ev_dir.is_dir() else None,
                                       "note": "PARTIAL by design: an absent record means nobody ran the producer"}

    # ── attribution ──
    node_of_unit = {str(n["unit"]): nid for nid, n in nodes.items() if isinstance(n.get("unit"), str)}
    plan_ref_units = {str(i["ref"]): str(i["id"]) for i in plan_items if isinstance(i.get("ref"), str) and _RQ.match(i["ref"])}
    title_keys = sorted(set(strategies) | set(reg), key=len, reverse=True)
    attributed: dict[str, list[str]] = {}
    node_prog: dict[str, str] = {}
    subject_kind: dict[str, str] = {}
    how_count: dict[str, int] = {}
    unattributed: list[str] = []
    for uid in units:
        d = docs.get(uid) or {}
        key, how = None, None
        if uid in plan_ref_units:
            key, how = f"mlplan:{plan_ref_units[uid]}", "ml_plan_ref"
        if not key:
            s, kind = _declared_subject(d)
            if s:
                key, how = f"subj:{s}", "declared_subject"
                subject_kind.setdefault(s, kind or "")
        if not key:
            title = str(units[uid].get("title") or "")
            hit = next((k for k in title_keys if k in title), None)
            if hit:
                key, how = f"subj:{hit}", "title_match"
        if not key:
            pn = d.get("programme_node") if isinstance(d.get("programme_node"), dict) else {}
            nid = pn.get("node") if isinstance(pn.get("node"), str) else node_of_unit.get(uid)
            prog = (nodes.get(nid) or {}).get("_programme") or pn.get("programme") if nid else None
            if nid and str(prog) in PROGRAMME_TRACK:   # a data-infra (P6) node is a build, not an idea
                key, how = f"node:{nid}", "programme_node"
                node_prog.setdefault(nid, str(prog))
        if not key:
            unattributed.append(uid)
            continue
        attributed.setdefault(key, []).append(uid)
        how_count[how] = how_count.get(how, 0) + 1

    def ulist(key: str) -> list[dict]:
        return [units[u] for u in attributed.get(key, [])]

    def owner_rows(*needles: str) -> list[str]:
        out = []
        for r in open_rows:
            hay = f"{r.get('id')} {r.get('title')}"
            if any(n and n in hay for n in needles):
                out.append(str(r.get("id")))
            if len(out) >= 3:
                break
        return out

    def programmes_of(us: list[dict]) -> list[str]:
        out = set()
        for u in us:
            d = docs.get(u["id"]) or {}
            pn = d.get("programme_node") if isinstance(d.get("programme_node"), dict) else {}
            p = pn.get("programme") or d.get("programme") or (nodes.get(node_of_unit.get(u["id"], ""), {}).get("_programme"))
            if isinstance(p, str):
                out.add(p)
        return sorted(out)

    ideas: list[dict] = []

    def emit(*, iid: str, name: str, track: str, kind: str, stage: str, reason: str | None,
             us: list[dict], latest: dict | None, programme: list[str] | str | None, next_step: str | None,
             owner: list[str], links: dict, extra: dict | None = None) -> None:
        acts = [u.get("lastActivity") for u in us if u.get("lastActivity")]
        ideas.append({
            "id": iid, "name": name, "track": track, "kind": kind,
            "programme": programme or None,
            "stage": stage, "stage_label": STAGE_LABEL[stage], "stage_reason": reason,
            "latest_result": _result(latest),
            "counts": _counts(us) if us else {"units": 0, "passed": 0, "failed": 0, "indeterminate": 0, "open": 0, "blocked": 0},
            "open_units": [u["id"] for u in us if u["status"] in OPEN][:5] or None,
            "next_step": next_step, "owner_rows": owner or None,
            "last_activity": max(acts) if acts else None, "links": links, **(extra or {}),
        })

    def next_from(stage: str, us: list[dict], latest: dict | None) -> str | None:
        o = [u for u in us if u["status"] in OPEN]
        if o:
            return f"{o[0]['id']} ({o[0]['status']}): {o[0].get('title') or ''}"[:240]
        if stage == "passed_waiting":
            return "promotion decision on the passing record (Gate 1 / Stage-1 roster)"
        if stage == "failed":
            return "author an iteration unit from a diagnosis, or record lever exhaustion (programme-review iteration loop)"
        if stage == "stuck":
            b = [u for u in us if u["status"] == "blocked"]
            return f"unblock {b[0]['id']}: {b[0].get('blockedReason') or ''}"[:240] if b else "author the next unit"
        return None

    # 1) strategy legs in config/strategies.yaml
    for leg, row in sorted(status_table.items()):
        us = ulist(f"subj:{leg}")
        books = row["books"]
        if row["status"] == "inactive":
            stage, reason = "retired", "enabled: false in config/strategies.yaml (retirement record)"
            _, _, latest = offline_stage(us)
        elif row["status"] == "production":
            stage, reason = "production", f"real-money roster: {', '.join(b for b in books if b in ss.REAL_MONEY_MIRROR)}"
            _, _, latest = offline_stage(us)
        elif any(b in ss.GENERAL_PAPER for b in books):
            stage, reason = "testing_book", f"general paper roster: {', '.join(b for b in books if b in ss.GENERAL_PAPER)}"
            _, _, latest = offline_stage(us)
        else:
            stage, reason, latest = offline_stage(us)
            reason = f"on no general-paper or real-money roster; {reason}"
        ev, _ = _json(ev_dir / f"{leg}.json")
        evidence = None
        if isinstance(ev, dict):
            evidence = {k: ev.get(k) for k in ("coverage_state", "basis", "net_r_oos", "expectancy_r_oos", "n_trades_oos",
                                               "folds", "folds_positive", "window_days", "fee_bps_roundtrip")}
            evidence["path"] = f"comms/strategy_evidence/{leg}.json"
        cfg = strategies.get(leg) if isinstance(strategies.get(leg), dict) else {}
        emit(iid=f"strategy:{leg}", name=leg, track=STRATEGY, kind="strategy_leg", stage=stage, reason=reason, us=us,
             latest=latest, programme=programmes_of(us), next_step=next_from(stage, us, latest),
             owner=owner_rows(leg), links={"evidence": f"{REPO_BLOB}/comms/strategy_evidence/{leg}.json" if evidence else None,
                                           "config": f"{REPO_BLOB}/config/strategies.yaml"},
             extra={"books": books or None, "execution": cfg.get("execution"), "stage0_evidence": evidence})

    # 2) ML registry models: every LIVE/SHADOW row or row with an order consumer; OFFLINE rows only with a unit
    real_money = ("bybit_2", "alpaca_live", "ib_live")
    for mid, r in sorted(reg.items()):
        us = ulist(f"subj:{mid}")
        bucket = str(r.get("bucket") or "").upper()
        cons = r.get("consumers") or []
        if bucket not in ("LIVE", "SHADOW") and not us and not cons:
            continue
        name = (model_names.get(mid) or {}).get("name") if isinstance(model_names.get(mid), dict) else None
        rm = sorted({c["account"] for c in cons if c.get("account_class") == "real_money" or c.get("account") in real_money})
        books = sorted({c["account"] for c in cons if c.get("account")})
        if rm:
            stage, reason = "production", f"order consumer on real money: {', '.join(rm)}"
            _, _, latest = offline_stage(us)
        elif books:
            stage, reason = "testing_book", f"order consumer on: {', '.join(books)}"
            _, _, latest = offline_stage(us)
        elif bucket in ("LIVE", "SHADOW"):
            stage = "shadow_advisory"
            reason = ("advisory (LIVE bucket), no order consumer" if bucket == "LIVE" else "shadow, no order consumer")
            _, _, latest = offline_stage(us)
        else:
            stage, reason, latest = offline_stage(us)
            reason = f"registry bucket {bucket or '—'}; {reason}"
        emit(iid=f"ml:{mid}", name=name or r.get("display") or mid, track=ML, kind="ml_model", stage=stage, reason=reason,
             us=us, latest=latest, programme=programmes_of(us), next_step=next_from(stage, us, latest),
             owner=owner_rows(mid), links={"registry": "/api/bot/ml/registry"},
             extra={"model_id": mid, "slot": r.get("slot"), "bucket": bucket or None, "family": r.get("family"),
                    "consumers": cons or None})

    # 3) declared subjects that are neither a config leg nor a registry model (new hypotheses / ML ideas)
    for key in sorted(k for k in attributed if k.startswith("subj:")):
        s = key[5:]
        if s in status_table or s in reg:
            continue
        us = ulist(key)
        kind = subject_kind.get(s, "")
        track = ML if (kind == "ml_model" or s.lower().startswith("ml") or "ml_leg" in s or "ml-" in s) else STRATEGY
        stage, reason, latest = offline_stage(us)
        emit(iid=f"hypothesis:{s}", name=s, track=track, kind=f"hypothesis ({kind})" if kind else "hypothesis",
             stage=stage, reason=reason, us=us, latest=latest, programme=programmes_of(us),
             next_step=next_from(stage, us, latest), owner=owner_rows(s), links={})

    # 4) ML plan items that are ideas (unit ref, or an idea track), never pure builds
    excluded_plan_builds = 0
    for it in plan_items:
        iid, ref, state = str(it.get("id")), str(it.get("ref") or ""), str(it.get("state") or "")
        is_unit = bool(_RQ.match(ref))
        if not is_unit and str(it.get("track")) not in PLAN_IDEA_TRACKS:
            excluded_plan_builds += 1
            continue
        us = ulist(f"mlplan:{iid}")
        if state == "killed":
            stage, reason = "retired", "ML plan item state killed"
            _, _, latest = offline_stage(us)
        elif state == "parked":
            stage, reason = "stuck", f"parked: {rc._text(it.get('close'), 300)}"
            _, _, latest = offline_stage(us)
        elif not is_unit and not us:
            if state == "done":
                excluded_plan_builds += 1
                continue
            stage, reason, latest = "idea", f"waiting on build row {ref}", None
        else:
            stage, reason, latest = offline_stage(us)
        emit(iid=f"mlplan:{iid}", name=rc._text(it.get("title"), 160) or iid, track=ML, kind="ml_plan_item",
             stage=stage, reason=reason, us=us, latest=latest, programme="P2 / ML plan track " + str(it.get("track")),
             next_step=next_from(stage, us, latest) or (f"build row {ref}" if not is_unit else None),
             owner=[ref] if ref and not is_unit else owner_rows(iid),
             links={"plan": f"{REPO_BLOB}/docs/plans/ml-plan-items.yaml"},
             extra={"plan_state": state or None, "ref": ref or None, "family": it.get("family")})

    # 5) programme question nodes: units attributed to the node, or an open needs_authoring with no unit
    excluded_infra_nodes = 0
    node_keys = sorted(set(nodes) | {k[5:] for k in attributed if k.startswith("node:")})
    for nid in node_keys:
        n = nodes.get(nid) or {"_programme": node_prog.get(nid), "_file": None, "_missing": True}
        track = PROGRAMME_TRACK.get(str(n.get("_programme")))
        us = ulist(f"node:{nid}")
        na = str(n.get("needs_authoring") or "")
        open_authoring = bool(na) and not na.startswith("AUTHORED") and not n.get("unit")
        if not us and not open_authoring:
            continue
        if track is None:
            excluded_infra_nodes += 1
            continue
        stage, reason, latest = offline_stage(us)
        if not us:
            reason = "programme node needs_authoring; no unit authored"
        emit(iid=f"question:{nid}", name=nid, track=track, kind="programme_question", stage=stage, reason=reason,
             us=us, latest=latest, programme=n.get("_programme"),
             next_step=(rc._text(na, 300) if open_authoring else next_from(stage, us, latest)),
             owner=owner_rows(nid), links={"programme": f"{REPO_BLOB}/{n['_file']}" if n.get("_file") else None},
             extra={"goal": n.get("goal"), "roadmap": n.get("roadmap") or None,
                    "node_read_state": "not in research/programmes (named by a unit's programme_node)"
                    if n.get("_missing") else "ok"})

    # ── summary ──
    per_stage = {t: {s: 0 for s in STAGES} for t in (STRATEGY, ML)}
    for i in ideas:
        per_stage[i["track"]][i["stage"]] += 1
    cutoff = rc._iso(now - timedelta(days=7))
    changed = sorted((i for i in ideas if i["last_activity"] and i["last_activity"] >= cutoff),
                     key=lambda i: i["last_activity"], reverse=True)
    prev_stage = {p["id"]: p["stage"] for p in (previous or {}).get("ideas") or [] if isinstance(p, dict)}
    stage_changes = [{"id": i["id"], "from": prev_stage[i["id"]], "to": i["stage"]}
                     for i in ideas if i["id"] in prev_stage and prev_stage[i["id"]] != i["stage"]]
    un_by_theme: dict[str, int] = {}
    un_by_status: dict[str, int] = {}
    for uid in unattributed:
        th = str(units[uid].get("theme") or "none")
        un_by_theme[th] = un_by_theme.get(th, 0) + 1
        s = units[uid]["status"]
        un_by_status[s] = un_by_status.get(s, 0) + 1
    n_attr = sum(len(v) for v in attributed.values())
    summary = {
        "ideas": len(ideas),
        "per_track": {t: sum(per_stage[t].values()) for t in per_stage},
        "per_stage_per_track": per_stage,
        "changed_last_7d": {"basis": "idea's newest attributed-unit activity (result, dispatch or grading) on/after "
                                     f"{cutoff}", "count": len(changed),
                            "items": [{"id": i["id"], "name": i["name"], "track": i["track"], "stage": i["stage"],
                                       "verdict": (i["latest_result"] or {}).get("verdict"), "last_activity": i["last_activity"]}
                                      for i in changed[:40]]},
        "stage_changes_since_previous": stage_changes if previous is not None else None,
        "units": {"total": len(units), "attributed": n_attr, "unattributed": len(unattributed),
                  "by_attribution": how_count,
                  "check": "attributed + unattributed == total" if n_attr + len(unattributed) == len(units) else "MISMATCH"},
        "unattributed_units": {"count": len(unattributed), "by_theme": dict(sorted(un_by_theme.items(), key=lambda kv: -kv[1])),
                               "by_status": un_by_status,
                               "note": "units no rule could tie to one strategy/ML idea (cross-cutting infra, macro event "
                                       "studies, prop book compositions...). Counted, never dropped; still in /api/bot/research/catalog"},
        "excluded": {"ml_plan_build_items": excluded_plan_builds, "data_infra_programme_nodes": excluded_infra_nodes},
    }
    return {
        "schema": SCHEMA,
        "generated_at": rc._iso(now),
        "population": "every strategy leg in config/strategies.yaml; every ML registry row in bucket LIVE/SHADOW (plus "
                      "OFFLINE rows with an attributed unit); every unit-subject that is neither; every ML plan item that is "
                      "an idea; every programme question node with attributed units or an open needs_authoring",
        "decision": "operator 2026-11-12 chat — idea-level ML + strategy testing registry for visibility",
        "gates": "none: a read projection; it refuses and blocks nothing",
        "stages": [{"stage": s, "label": STAGE_LABEL[s]} for s in STAGES],
        "stage_rules": STAGE_RULES,
        "attribution": ATTRIBUTION,
        "read_state": read_state,
        "summary": summary,
        "ideas": sorted(ideas, key=lambda i: (i["track"], STAGES.index(i["stage"]), i["id"])),
    }


def cross_check(doc: dict, root: Path) -> list[str]:
    """Arithmetic checks of the registry against its sources. [] = all hold. Never raises."""
    out: list[str] = []
    s = doc["summary"]
    u = s["units"]
    if u["attributed"] + u["unattributed"] != u["total"]:
        out.append(f"units: attributed {u['attributed']} + unattributed {u['unattributed']} != total {u['total']}")
    if sum(s["per_track"].values()) != s["ideas"] or len(doc["ideas"]) != s["ideas"]:
        out.append("ideas: per-track sum or idea list length != summary.ideas")
    try:
        from scripts.ops import strategy_status as ss
        t = ss.table(root)
        legs = [i for i in doc["ideas"] if i["kind"] == "strategy_leg"]
        for want, stage in (("production", "production"), ("inactive", "retired")):
            a = sum(1 for r in t.values() if r["status"] == want)
            b = sum(1 for i in legs if i["stage"] == stage)
            if a != b:
                out.append(f"strategy_status {want} {a} != registry {stage} legs {b}")
        if len(legs) != len(t):
            out.append(f"strategy legs {len(legs)} != strategies.yaml legs {len(t)}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"strategy_status unreadable: {type(exc).__name__}")
    regs = [i for i in doc["ideas"] if i["kind"] == "ml_model" and i.get("bucket") in ("LIVE", "SHADOW")]
    n_reg = doc["read_state"]["ml_registry"].get("n")
    if n_reg is not None:
        rows, _ = load_ml_registry(root, None) if doc["read_state"]["ml_registry"]["state"] == "snapshot" else ([], None)
        if rows:
            want = sum(1 for r in rows if str(r.get("bucket") or "").upper() in ("LIVE", "SHADOW"))
            if want != len(regs):
                out.append(f"registry LIVE+SHADOW {want} != LIVE/SHADOW ml_model ideas {len(regs)}")
    shown = sum(i["counts"]["units"] for i in doc["ideas"])
    if shown != u["attributed"]:
        out.append(f"units shown on ideas {shown} != attributed {u['attributed']} (an attributed unit is hidden or doubled)")
    for i in doc["ideas"]:
        c = i["counts"]
        if c["passed"] + c["failed"] + c["indeterminate"] > c["units"]:
            out.append(f"{i['id']}: verdict counts exceed units")
    return out
