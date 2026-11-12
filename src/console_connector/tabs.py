"""Payload builders for the five console tabs (workplan, ml_roadmap, performance, system_health, data_query).

Every builder is a PROJECTION over a canonical source -- never a store of its own:

  workplan       checklist store + docs/claude/work/USAGE-READINGS.jsonl + scripts/ops/spend_meter.py
  ml_roadmap     docs/roadmap/milestones.yaml + scripts/ops/ml_plan_status.py + ML-* checklist rows
  performance    live VM /api/bot/performance, /performance/recent, /shadow/stats, /ml/registry
                 + scripts/research/live_vs_backtest.py
  system_health  live VM /api/diag/* (DIAG_READ_TOKEN) + this host's own psutil stats + the checklist
  data_query     read-only SELECT over the db_explorer allowlist (trade_journal.db, trainer_store.db)

Each response carries ``as_of``, ``read_state`` (``read`` | ``stale`` | ``partial`` | ``could_not_look``
| ``auth_required``), ``population`` and ``provenance``. A source that cannot be read reports
``could_not_look`` with the reason; it is never an empty list or a ``0``. Nothing here writes.
Tools whose data is P&L, journal rows or live-VM state are gated on ``CONSOLE_CONNECTOR_AUTH=google``
in ``server.py``; this module does not decide that.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.console_connector import data as D

LIVE_BASE = (os.environ.get("CONSOLE_LIVE_BASE") or "https://ict-bot.duckdns.org").rstrip("/")
FETCH_TIMEOUT_S = 25
WINDOWS = ("7d", "30d", "all")
MAX_ROWS = 500
DEFAULT_ROWS = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env(repo: Path, read_state: str, population: dict, provenance: dict | None = None, **rest: Any) -> dict:
    prov = {"register": D.register_provenance(repo)}
    prov.update(provenance or {})
    return {"as_of": D._iso(_now()), "read_state": read_state, "population": population,
            "provenance": prov, **rest}


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:240]}"


def _trim(v: Any, n: int) -> Any:
    return v[:n] if isinstance(v, str) else v


# ───────────────────────────── live-VM reads ─────────────────────────────
#: Injectable for tests: (path_with_query, token_or_None) -> parsed JSON. Raises on failure.
def _http_get(path: str, token: str | None) -> Any:
    req = urllib.request.Request(f"{LIVE_BASE}{path}", method="GET")
    if token:
        # #23273 moves the diag token to X-Diag-Token; until it lands Authorization is read. Both carry
        # the SAME value, so the two can never disagree.
        req.add_header("X-Diag-Token", token)
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:  # read-only GET
        return json.loads(resp.read().decode("utf-8"))


FETCH: Callable[[str, str | None], Any] = _http_get


def _public(path: str) -> Any:
    return FETCH(path, None)


def _diag(path: str) -> Any:
    tok = (os.environ.get("DIAG_READ_TOKEN") or "").strip()
    if not tok:
        raise PermissionError("DIAG_READ_TOKEN is unset on the connector host")
    return FETCH(path, tok)


def _try(fn: Callable[[], Any]) -> tuple[Any, str | None]:
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001  # allow-silent: returned to the caller as could_not_look + reason
        return None, _err(exc)


# ───────────────────────────── 1. workplan ─────────────────────────────
def usage_block(repo: Path) -> dict:
    """Latest USAGE-READINGS reading per window + the spend_meter --capacity output."""
    try:
        from scripts.ops import spend_meter as sm
        log = sm.read_readings(repo / "docs/claude/work/USAGE-READINGS.jsonl")
        latest = sm.latest_by_window(log.records)
        cap = sm.capacity(log, live_open=None)
        return {"read_state": "read", "readings_scanned": len(log.records),
                "latest_by_window": latest, "capacity": cap,
                "capacity_note": "live_open not supplied: the reserve is sized at the roster bound "
                                 "(reserve_basis.exposure=exposure_unknown), as the CLI does without a feed"}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the error
        return {"read_state": "could_not_look", "error": _err(exc), "latest_by_window": None, "capacity": None}


def workplan(repo: Path, limit: int = 40, today: date | None = None) -> dict:
    now = _now()
    today = today or now.date()
    try:
        items = [r for r in D._load_checklist(repo).get("items", []) if isinstance(r, dict)]
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        return _env(repo, "could_not_look", {"rows_scanned": None}, error=_err(exc), usage=usage_block(repo))
    slim = [D._slim(r, today, now) for r in items]
    live = [r for r in slim if r["state"] in D.LIVE_STATES]
    week_end = (today + timedelta(days=7)).isoformat()
    due_week = [r for r in live if r["due_by"] and not r["overdue"] and r["due_by"] <= week_end]
    overdue = [r for r in live if r["overdue"]]
    prio = [r for r in live if r.get("priority_rank") is not None]
    wp = next((r for r in slim if r["id"] == "WEEKLY-PLANNING"), None)

    def by(key: str) -> dict:
        out: dict[str, int] = {}
        for r in live:
            out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    state_counts: dict[str, int] = {}
    for r in slim:
        state_counts[str(r["state"])] = state_counts.get(str(r["state"]), 0) + 1

    def srt(rows, k):
        return sorted(rows, key=k)[:limit]

    return _env(repo, "read",
                {"rows_scanned": len(items), "live_rows": len(live), "limit_per_list": limit,
                 "window": {"from": today.isoformat(), "to": week_end},
                 "counts": {"overdue": len(overdue), "due_this_week": len(due_week), "priority": len(prio)},
                 "truncated": {"overdue": len(overdue) > limit, "due_this_week": len(due_week) > limit,
                               "priority": len(prio) > limit}},
                {"source": ["checklist", "USAGE-READINGS.jsonl", "spend_meter --capacity"],
                 "measure": "MEASURED"},
                weekly_planning=wp, state_counts=state_counts, by_owner=by("owner"), by_lane=by("lane"),
                overdue=srt(overdue, lambda r: (r["due_by"] or "", r["id"])),
                due_this_week=srt(due_week, lambda r: (r["due_by"] or "", r["id"])),
                priority=srt(prio, lambda r: (r.get("priority_rank") or 9999, r["id"])),
                usage=usage_block(repo),
                closed_this_week=D.closed_this_week(items, now, today),
                week_lane_totals=D.week_lane_totals(items))


# ───────────────────────────── 2. ml_roadmap ─────────────────────────────
ML_GOAL = "G4"
ML_MILESTONE_PREFIX = "L-ML"


def ml_roadmap(repo: Path, limit: int = 60, today: date | None = None) -> dict:
    import yaml
    now = _now()
    today = today or now.date()
    sections: dict[str, Any] = {}
    # milestones
    try:
        ms = yaml.safe_load((repo / "docs/roadmap/milestones.yaml").read_text())["milestones"]
        mls = [m for m in ms if m.get("goal") == ML_GOAL or str(m.get("id", "")).startswith(ML_MILESTONE_PREFIX)]
        sections["milestones"] = {"read_state": "read", "population": {"milestones_scanned": len(ms), "ml": len(mls)},
                                  "items": [{"id": m.get("id"), "goal": m.get("goal"), "name": _trim(m.get("name"), 160),
                                             "status": m.get("status"), "week_priority": m.get("week_priority"),
                                             "target": str(m["target"]) if m.get("target") is not None else None,
                                             "reviewed": str(m["reviewed"]) if m.get("reviewed") is not None else None,
                                             "where": _trim(m.get("where"), 600), "next": _trim(m.get("next"), 600)}
                                            for m in mls[:limit]]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        sections["milestones"] = {"read_state": "could_not_look", "error": _err(exc), "items": []}
    # plan status (ml_plan_status.analyse over docs/plans/ml-plan-items.yaml)
    rowmap: dict = {}
    try:
        from scripts.ops import ml_plan_status as mps
        rowmap = mps.rows(repo)
        res = mps.analyse(mps.load_plan(repo / "docs/plans/ml-plan-items.yaml"), rowmap, repo)
        flagged = [r for r in res if r["flags"]]
        sections["plan_status"] = {"read_state": "read",
                                   "population": {"plan_items": len(res), "flagged": len(flagged)},
                                   "items": res[:limit * 2]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        sections["plan_status"] = {"read_state": "could_not_look", "error": _err(exc), "items": []}
    # ML-* rows
    try:
        if not rowmap:
            rowmap = {r["id"]: r for r in D._load_checklist(repo).get("items", []) if isinstance(r, dict)}
        mlrows = [r for rid, r in rowmap.items() if re.match(r"^(ML-|REGIME-|EXIT-HEAD|TP-PREDICT|FUNDING-OI)", rid)]
        slim = []
        for r in mlrows:
            s = D._slim(r, today, now)
            s["next"] = _trim(r.get("next"), 400) if isinstance(r.get("next"), str) else None
            slim.append(s)
        live = [s for s in slim if s["state"] in D.LIVE_STATES]
        live.sort(key=lambda s: (s["due_by"] or "9999", s["id"]))
        sections["rows"] = {"read_state": "read",
                            "population": {"ml_rows": len(slim), "live": len(live), "limit": limit,
                                           "truncated": len(live) > limit},
                            "items": live[:limit]}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        sections["rows"] = {"read_state": "could_not_look", "error": _err(exc), "items": []}
    states = {s["read_state"] for s in sections.values()}
    rs = "read" if states == {"read"} else ("could_not_look" if states == {"could_not_look"} else "partial")
    return _env(repo, rs, {k: v.get("population") for k, v in sections.items()},
                {"source": ["milestones.yaml", "ml_plan_status.analyse", "checklist ML-* rows"], "measure": "MEASURED"},
                sections=sections)


# ───────────────────────────── 3. performance ─────────────────────────────
LEG_FIELDS = ("trades", "wins", "winRate", "totalPnl", "totalPnlMeasured", "totalPnlEstimated", "totalR",
              "expectancyR", "rTradeCount", "pnlCoverage", "pnlMeasuredCount", "pnlEstimatedCount")
BOOKS = (("real_money", None), ("paper", "paper"), ("paper_portfolio", "paperPortfolio"))


def _signal_catalog(repo: Path) -> dict:
    """docs/reference/signal-catalog.yaml (row SIGNAL-CATALOG), parsed."""
    import yaml
    return yaml.safe_load((repo / "docs/reference/signal-catalog.yaml").read_text(encoding="utf-8")) or {}


def _mechanics_for_legs() -> dict:
    """Per-leg ``mechanics_proven`` from the live VM (GET /api/bot/soak/mechanics, row UI-CONSOLE-ARTIFACT C2).

    Soak state needs the trade journal, which only the live VM has; that route evaluates
    scripts/ops/soak_state.py::mechanics_proven there. A failed read is ``could_not_look`` and every leg's
    ``mechanics_proven`` is None, never False (an unread source is not a "not proven")."""
    try:
        doc = _work_get("/api/bot/soak/mechanics")
    except Exception as exc:  # noqa: BLE001 - a failed source says so; it is never an empty or false answer
        return {"read_state": "could_not_look", "reason": _err(exc), "legs": None}
    if not isinstance(doc, dict) or doc.get("read_state") != "read":
        return {"read_state": "could_not_look",
                "reason": (doc or {}).get("reason") if isinstance(doc, dict) else "unexpected reply", "legs": None,
                "population": (doc or {}).get("population") if isinstance(doc, dict) else None}
    return doc


def system_catalog(repo: Path, signals_limit: int = 400) -> dict:
    """The System tab: strategy legs (status, books, venue, symbol), ML models and the signal catalog.

    A projection over committed files only (config/strategies.yaml, config/accounts.yaml,
    scripts/ops/strategy_status.py, docs/reference/signal-catalog.yaml); nothing live is read, so a
    leg's status is the roster's status at the register commit, not a venue read. ML ``target_stage`` is the
    manifest's target, not the live registry stage (that is `performance` -> ml_models).
    """
    sections: dict[str, Any] = {}
    # (a) strategy legs
    try:
        ss = _load_script(repo, "scripts/ops/strategy_status.py", "_cc_strategy_status")
        accounts, strategies = ss.load(repo)
        table = ss.table(repo)
        legs = []
        for leg, row in table.items():
            cfg = strategies.get(leg) or {}
            books = row["books"]
            legs.append({
                "leg": leg, "status": row["status"], "books": books,
                "venues": sorted({str((accounts.get(b) or {}).get("exchange")) for b in books
                                  if (accounts.get(b) or {}).get("exchange")}),
                "book_classes": {b: (accounts.get(b) or {}).get("account_class") for b in books},
                "symbols": [str(s) for s in (cfg.get("symbols") or [])],
                "timeframe": cfg.get("timeframe"), "execution": cfg.get("execution"),
                "model": cfg.get("model"),
            })
        counts: dict[str, int] = {}
        for r in legs:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        mech = _mechanics_for_legs()
        for r in legs:
            r["mechanics_proven"] = (mech.get("legs") or {}).get(r["leg"]) if mech.get("read_state") == "read" else None
        sections["legs"] = {"read_state": "read", "population": {"legs": len(legs), "by_status": counts},
                            "items": legs,
                            "mechanics": {k: mech.get(k) for k in ("read_state", "reason", "as_of", "population", "provenance")}}
    except Exception as exc:  # noqa: BLE001 - a failed source says so; it is never an empty list
        sections["legs"] = {"read_state": "could_not_look", "population": {"legs": None}, "reason": _err(exc)}
    # (b) ML models + signals from the catalog artifact (row SIGNAL-CATALOG)
    try:
        cat = _signal_catalog(repo)
        models = [{"model_id": m.get("model_id"), "family": m.get("model_family"),
                   "target_stage": m.get("target_deployment_stage"),
                   "dataset": (m.get("dataset") or {}).get("family"),
                   "symbol_scope": (m.get("dataset") or {}).get("symbol_scope"),
                   "timeframe": (m.get("dataset") or {}).get("timeframe"),
                   "n_features": len(m.get("features") or [])} for m in (cat.get("ml_models") or [])]
        sections["ml_models"] = {"read_state": "read", "population": {"models": len(models),
                                 "stage_source": "manifest target_deployment_stage, not the live registry"},
                                 "items": models}
        inputs = cat.get("inputs") or []
        items = [{"id": i.get("id"), "name": i.get("name"), "family": i.get("family"), "kind": i.get("kind"),
                  "timeframe": i.get("timeframe"), "used_by": list(i.get("used_by") or [])[:6],
                  "health": (i.get("health") or {}).get("state"),
                  "definition": _trim(i.get("definition"), 160)} for i in inputs[:signals_limit]]
        sections["signals"] = {"read_state": "read", "population": {
            "inputs": len(inputs), "returned": len(items), "truncated": len(inputs) > len(items),
            "by_family_kind": (cat.get("population") or {}).get("by_family_kind"),
            "generated": cat.get("generated"), "health_note": "health.state says whether a metric EXISTS; "
            "'unmeasured' is a could-not-look, never healthy"}, "items": items}
    except Exception as exc:  # noqa: BLE001
        for k in ("ml_models", "signals"):
            sections[k] = {"read_state": "could_not_look", "population": {}, "reason": _err(exc)}
    states = {s["read_state"] for s in sections.values()}
    rs = "read" if states == {"read"} else ("could_not_look" if states == {"could_not_look"} else "partial")
    return _env(repo, rs, {"sections": len(sections)},
                {"source": ["config/strategies.yaml", "config/accounts.yaml", "scripts/ops/strategy_status.py",
                            "docs/reference/signal-catalog.yaml"], "measure": "MEASURED"},
                sections=sections)


def _load_script(repo: Path, rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, repo / rel)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.path.insert(0, str((repo / rel).parent))
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        sys.path.pop(0)
    return mod


def _legs(by_window: dict[str, dict]) -> dict:
    """{leg: {window: {fields}}} for one book; a window that failed is None, never zeros."""
    out: dict[str, dict] = {}
    for w, book in by_window.items():
        if book is None:
            for per_window in out.values():
                per_window[w] = None
            continue
        for s in book.get("perStrategy") or []:
            leg = out.setdefault(s["name"], {x: None for x in by_window})
            leg[w] = {k: s.get(k) for k in LEG_FIELDS}
    return out


def performance(repo: Path, draws: int = 2000) -> dict:
    sections: dict[str, Any] = {}
    raw: dict[str, dict | None] = {}
    errs: dict[str, str] = {}
    for w in WINDOWS:
        v, e = _try(lambda w=w: _public(f"/api/bot/performance?window={w}"))
        raw[w] = v
        if e:
            errs[w] = e
    books: dict[str, Any] = {}
    for label, key in BOOKS:
        by_w = {w: (None if raw[w] is None else (raw[w] if key is None else raw[w].get(key))) for w in WINDOWS}
        tot = {w: (None if b is None else {k: b.get(k) for k in (
            "totalTrades", "totalPnl", "totalR", "expectancyR", "rTradeCount", "pnlCoverage", "pnlMeasuredCount",
            "pnlEstimatedCount", "pnlFabricatedCount", "pnlUnverifiedCount", "journalTrust")}) for w, b in by_w.items()}
        books[label] = {"totals": tot, "legs": _legs(by_w)}
    ok_w = [w for w in WINDOWS if raw[w] is not None]
    sections["legs"] = {
        "read_state": "read" if len(ok_w) == len(WINDOWS) else ("could_not_look" if not ok_w else "partial"),
        "errors": errs or None, "books": books,
        "population": {"windows_read": ok_w, "books": [b for b, _ in BOOKS],
                       "note": "prop legs are not a separate book in /api/bot/performance; they appear in real_money "
                               "or paper by account class"},
        "provenance": {"source": f"{LIVE_BASE}/api/bot/performance?window=7d|30d|all",
                       "r": "rBasis/rProvenance counts are on the source payload; pnl split measured vs estimated "
                            "via totalPnlMeasured/totalPnlEstimated and pnlCoverage (MEASURED/ESTIMATED never folded)"}}
    # live vs backtest band
    recent, e = _try(lambda: _public("/api/bot/performance/recent?n=200"))
    if recent is None:
        sections["live_vs_backtest"] = {"read_state": "could_not_look", "error": e, "rows": []}
    else:
        try:
            lvb = _load_script(repo, "scripts/research/live_vs_backtest.py", "_cc_lvb")
            gate = _load_script(repo, "scripts/ops/r4_demotion_gate.py", "_cc_r4")
            rows = lvb.run(recent, gate.stage2_legs(repo), root=repo, draws=draws)
            sections["live_vs_backtest"] = {"read_state": "read", "population": {"rows": len(rows), "draws": draws},
                                            "rows": rows, "provenance": {"harness": "scripts/research/live_vs_backtest.py"}}
        except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
            sections["live_vs_backtest"] = {"read_state": "could_not_look", "error": _err(exc), "rows": []}
    # ML models: shadow stats + registry
    sh, e1 = _try(lambda: _public("/api/bot/shadow/stats"))
    reg, e2 = _try(lambda: _public("/api/bot/ml/registry"))
    if sh is None and reg is None:
        sections["ml_models"] = {"read_state": "could_not_look", "error": {"shadow_stats": e1, "registry": e2},
                                 "models": []}
    else:
        models: dict[str, dict] = {}
        for r in (reg or {}).get("rows") or []:
            m = models.setdefault(str(r.get("model_id")), {"model_id": r.get("model_id")})
            m.update(deployment_bucket=r.get("deployment_bucket"), model_family=r.get("model_family"),
                     status=r.get("status"), target_deployment_stage=r.get("target_deployment_stage"),
                     linked_strategies=r.get("linked_strategies"),
                     metrics={k: v for k, v in list((r.get("metrics") or {}).items())[:16]
                              if isinstance(v, (int, float, str)) and not isinstance(v, bool)})
        for r in (sh or {}).get("records") or []:
            m = models.setdefault(str(r.get("model_id")), {"model_id": r.get("model_id")})
            m["shadow"] = {k: r.get(k) for k in ("stage", "count", "score_mean", "score_min", "score_max",
                                                 "score_read_state", "first_seen", "last_seen", "soak_days",
                                                 "soak_days_is_lower_bound")}
        sections["ml_models"] = {
            "read_state": "read" if (sh is not None and reg is not None) else "partial",
            "errors": {"shadow_stats": e1, "registry": e2} if (e1 or e2) else None,
            "population": {"models": len(models), "registry_rows": (reg or {}).get("count"),
                           "shadow_models": (sh or {}).get("count"),
                           "shadow_log": (sh or {}).get("log_coverage")},
            "models": sorted(models.values(), key=lambda m: str(m["model_id"])),
            "provenance": {"source": "/api/bot/ml/registry + /api/bot/shadow/stats",
                           "note": "shadow/advisory scores are ESTIMATED model outputs, not realized P&L"}}
    states = {s["read_state"] for s in sections.values()}
    rs = "read" if states == {"read"} else ("could_not_look" if states == {"could_not_look"} else "partial")
    return _env(repo, rs, {k: s.get("population") for k, s in sections.items()},
                {"source": [f"{LIVE_BASE}/api/bot/*"], "measure": "MEASURED (journal-derived, see per-section provenance)"},
                sections=sections)


# ───────────────────────────── 4. system_health ─────────────────────────────
def _local_vm() -> dict:
    from src.web.api._vm_health import vm_health
    return vm_health()


def system_health(repo: Path) -> dict:
    sections: dict[str, Any] = {}

    def sect(name: str, path: str, shape: Callable[[Any], Any] = lambda v: v) -> None:
        v, e = _try(lambda: _diag(path))
        sections[name] = ({"read_state": "could_not_look", "error": e, "value": None} if e
                          else {"read_state": "read", "value": shape(v), "source": f"/api/diag{path[len('/api/diag'):]}"})

    sect("services", "/api/diag/services")
    sect("timers", "/api/diag/timers")
    sect("version", "/api/diag/version")
    sect("tick_cost", "/api/diag/tick_cost")
    sect("status", "/api/diag/status",
         lambda v: {"heartbeat": v.get("heartbeat"), "vm_health": v.get("vm_health"),
                    "exit_loop_health": (v.get("status") or {}).get("exit_loop_health")
                    if isinstance(v.get("status"), dict) else None})
    # restarts today: journal lines for the trader unit since 00:00Z
    since = _now().strftime("%Y-%m-%d 00:00:00")
    j, e = _try(lambda: _diag(
        "/api/diag/journalctl?unit=ict-trader-live.service&lines=2000&since="
        + since.replace(" ", "%20") + "&grep=Started%7CMain%20process%20exited%7CFailed%20with%20result"))
    if e:
        sections["restarts_today"] = {"read_state": "could_not_look", "error": e, "count": None, "causes": []}
    else:
        lines = [x for x in (j.get("lines") or []) if isinstance(x, str)]
        sections["restarts_today"] = {
            "read_state": "read" if j.get("read_state", "complete") == "complete" and not j.get("truncated") else "partial",
            "unit": "ict-trader-live.service", "since_utc": since, "count": sum(1 for x in lines if "Started " in x),
            "causes": [x[-220:] for x in lines if "exited" in x or "Failed" in x][-10:],
            "population": {"lines_scanned": j.get("lines_scanned"), "lines_matched": j.get("lines_matched"),
                           "truncated": j.get("truncated")}}
    # per-VM resources
    vms: dict[str, Any] = {}
    loc, e = _try(_local_vm)
    vms["trainer"] = ({"read_state": "could_not_look", "error": e} if e or not any(v is not None for v in (loc or {}).values())
                      else {"read_state": "read", **loc, "source": "psutil on the connector host"})
    live_st = sections["status"].get("value") or {}
    vm = live_st.get("vm_health") if isinstance(live_st, dict) else None
    vms["live"] = ({"read_state": "read", **vm, "source": "/api/diag/status.vm_health"} if isinstance(vm, dict)
                   else {"read_state": "could_not_look", "error": sections["status"].get("error") or "no vm_health in payload"})
    vms["gateway"] = {"read_state": "could_not_look",
                      "reason": "ict-ib-gateway (10.0.0.251) is isolated; no read path from the connector"}
    sections["vm_resources"] = {"read_state": "read" if all(v["read_state"] == "read" for v in vms.values()) else "partial",
                                "vms": vms}
    # lanes + spend vs weekly bar
    now = _now()
    try:
        items = [r for r in D._load_checklist(repo).get("items", []) if isinstance(r, dict)]
        lanes = sorted({str(r.get("lane")) for r in items if r.get("state") == "in_flight" and r.get("lane")})
        lane_state = {"read_state": "read", "in_flight_lanes": lanes, "count": len(lanes),
                      "population": {"rows_scanned": len(items)}}
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        lane_state = {"read_state": "could_not_look", "error": _err(exc), "count": None, "in_flight_lanes": []}
    sections["lanes_and_spend"] = {**lane_state, "usage": usage_block(repo)}
    states = {s["read_state"] for s in sections.values()}
    rs = "read" if states == {"read"} else ("could_not_look" if states == {"could_not_look"} else "partial")
    return _env(repo, rs, {k: s.get("population", "n/a") for k, s in sections.items()},
                {"source": [f"{LIVE_BASE}/api/diag/*", "psutil (trainer)", "checklist"], "measure": "MEASURED",
                 "captured_at": D._iso(now)}, sections=sections)


# ───────────────────────────── 5. data_query ─────────────────────────────
#: Deny-by-name for any column that looks like a credential, on top of db_explorer's own redaction.
#: EXACT names (``input_tokens`` is a count and must stay).
SECRET_COLUMNS = re.compile(
    r"^(token|secret|password|passwd|passphrase|api_?key|api_?secret|private_?key|auth_?token|access_?token|"
    r"refresh_?token|bearer|credential|credentials|signature|webhook(_url)?)$", re.IGNORECASE)
FILTER_COLUMNS = {"account": ("account_id", "account", "account_name"),
                  "leg": ("strategy_name", "strategy", "leg"),
                  "symbol": ("symbol",)}
TIME_COLUMN = {"trades": "closed_at", "order_packages": "created_at", "signals": "logged_at_utc",
               "balance_snapshots": "ts"}
TIME_FALLBACKS = ("created_at", "ts", "logged_at_utc", "timestamp", "started_at", "updated_at")
_ISO_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.+\-Zz]*)?$")


def _explorer():
    from src.web.api.routers import (
        db_explorer as ex,  # the ONE allowlist (default-deny, column redaction)
    )
    return ex


def _db_paths() -> dict[str, Path]:
    from src.utils.paths import trade_journal_db_path, trainer_store_db_path
    return {"trade_journal": Path(trade_journal_db_path()), "trainer_store": Path(trainer_store_db_path())}


def _visible(conn: sqlite3.Connection, table: str, ex) -> list[str]:
    hidden = ex._redacted_for(table)
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if r[1] not in hidden and not SECRET_COLUMNS.match(r[1])]


def _owners(ex, paths: dict[str, Path]) -> tuple[dict[str, tuple[str, Path]], dict[str, str]]:
    """table -> (db label, path) for allowlisted tables present on this host; label -> reason for absent DBs."""
    owners: dict[str, tuple[str, Path]] = {}
    missing: dict[str, str] = {}
    for label, p in paths.items():
        if not p.exists():
            missing[label] = f"{p} does not exist on this host"
            continue
        try:
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            finally:
                conn.close()
        except sqlite3.Error as exc:
            missing[label] = _err(exc)
            continue
        for t in sorted(names & set(ex._TABLE_ALLOWLIST)):
            owners.setdefault(t, (label, p))
    return owners, missing


def data_query(repo: Path, args: dict[str, Any]) -> dict:
    """Allowlisted, parameterized, read-only viewer. No free SQL: only the typed arguments below exist."""
    try:
        ex = _explorer()
        paths = _db_paths()
        owners, missing = _owners(ex, paths)
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look
        return _env(repo, "could_not_look", {"rows": None}, error=_err(exc), rows=[])
    table = args.get("table")
    prov = {"source": "db_explorer allowlist over " + ", ".join(f"{k}={v}" for k, v in paths.items()),
            "measure": "MEASURED (raw journal rows, not recomputed)"}
    if not table:
        cat = []
        for t, (label, p) in sorted(owners.items()):
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                cat.append({"table": t, "db": label, "columns": _visible(conn, t, ex)})
            finally:
                conn.close()
        return _env(repo, "read" if cat and not missing else ("partial" if cat else "could_not_look"),
                    {"tables": len(cat)}, prov, catalog=cat, unavailable_dbs=missing or None,
                    arguments="table (required for rows), account, leg, symbol, since, until, time_column, "
                              "order (asc|desc), limit (<=500), offset")
    table = str(table)
    if table not in ex._TABLE_ALLOWLIST:
        return _env(repo, "read", {"rows": 0}, prov, error=f"table not in the allowlist: {table}", rows=[],
                    allowed_tables=sorted(ex._TABLE_ALLOWLIST))
    if table not in owners:
        return _env(repo, "could_not_look", {"rows": None}, prov, error=f"{table} is allowlisted but its database "
                    "is not readable on this host", unavailable_dbs=missing or None, rows=[])
    label, path = owners[table]
    try:
        db_age_s = round(_now().timestamp() - path.stat().st_mtime)
    except OSError:
        db_age_s = None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = _visible(conn, table, ex)
        if not cols:
            return _env(repo, "read", {"rows": 0}, prov, error=f"{table} has no exposable columns", rows=[])
        where, params, applied, problems = [], [], {}, []
        for arg, cands in FILTER_COLUMNS.items():
            val = args.get(arg)
            if val is None or val == "":
                continue
            col = next((c for c in cands if c in cols), None)
            if col is None:
                problems.append(f"filter `{arg}` does not apply to {table} (no {'/'.join(cands)} column)")
                continue
            where.append(f'"{col}" = ?')
            params.append(str(val)[:128])
            applied[arg] = col
        tcol = args.get("time_column") or TIME_COLUMN.get(table) or next((c for c in TIME_FALLBACKS if c in cols), None)
        for arg, op in (("since", ">="), ("until", "<")):
            val = args.get(arg)
            if val is None or val == "":
                continue
            if not _ISO_PREFIX.match(str(val)):
                problems.append(f"`{arg}` must be an ISO date or datetime, got {str(val)[:40]!r}")
            elif tcol is None or tcol not in cols:
                problems.append(f"`{arg}` does not apply to {table}: no usable time column ({tcol!r})")
            else:
                where.append(f'"{tcol}" {op} ?')
                params.append(str(val))
                applied[arg] = tcol
        if problems:  # a requested filter that cannot be applied is refused, never dropped
            return _env(repo, "read", {"rows": None}, prov, error="; ".join(problems), rows=[], columns=cols)
        try:
            req_limit = int(args.get("limit", DEFAULT_ROWS))
        except (TypeError, ValueError):
            req_limit = DEFAULT_ROWS
        limit = max(1, min(MAX_ROWS, req_limit))
        limit_state = "as_requested" if limit == req_limit else ("clamped_to_max" if req_limit > MAX_ROWS else "defaulted_invalid")
        try:
            offset = max(0, int(args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        direction = "ASC" if str(args.get("order", "desc")).lower() == "asc" else "DESC"
        order_col = tcol if tcol in cols else ("id" if "id" in cols else cols[0])
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(f'SELECT COUNT(*) FROM "{table}"{w}', params).fetchone()[0]
        proj = ", ".join(f'"{c}"' for c in cols)
        rows = conn.execute(f'SELECT {proj} FROM "{table}"{w} ORDER BY "{order_col}" {direction} LIMIT ? OFFSET ?',
                            [*params, limit, offset]).fetchall()
        data = [{k: (v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else v)
                 for k, v in zip(r.keys(), tuple(r))} for r in rows]
    except sqlite3.Error as exc:
        return _env(repo, "could_not_look", {"rows": None}, prov, error=_err(exc), rows=[])
    finally:
        conn.close()
    return _env(repo, "read", {"table": table, "db": label, "matched_total": total, "returned": len(data),
                               "limit": limit, "limit_max": MAX_ROWS, "offset": offset, "limit_state": limit_state,
                               "truncated": total > offset + len(data)},
                {**prov, "db_file": str(path), "db_file_age_s": db_age_s,
                      "note": "rows come from this host's copy of the database; on the trainer VM trade_journal.db is the "
                              "sync_trainer_data.sh snapshot, so read db_file_age_s before treating it as live"},
                columns=cols, filters_applied=applied, order={"column": order_col, "dir": direction.lower()},
                rows=data)


# ---- research queue tab (operator 2026-11-07: "a tab with the research que so I can see what's in the pipeline") ----
_RQ_STATUS = {"queued": "queued", "due": "queued", "dispatched": "running", "running": "running",
              "result": "done", "retired": "done", "blocked": "blocked"}
_RQ_BACKEND = {"runner": "GitHub", "trainer": "trainer", "gpu": "trainer (GPU)"}


def research_queue(repo: Path, args: dict | None = None) -> dict:
    """Every research/queue unit, projected by ``src.runtime.research_catalog`` (the same projection behind
    ``/api/bot/research/catalog``): id, title, status (queued|running|done|blocked), kind, theme group (ml|trading),
    harness, compute (GitHub|trainer), last run + result pointer. Counts are over the FULL population; ``rows`` is
    the filtered page. Null fields stay None (the page renders a dash)."""
    args = args or {}
    want_status = str(args.get("status") or "pipeline")
    want_theme = str(args.get("theme") or "all")
    limit = max(1, min(300, int(args.get("limit") or 30)))
    offset = max(0, int(args.get("offset") or 0))
    try:
        from src.runtime import research_catalog as rc
        cat = rc.build_catalog(Path(repo))
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look, never an empty queue
        return _env(repo, "could_not_look", {"units_scanned": None}, error=_err(exc))
    rows = []
    for u in cat["units"]:
        du = u.get("dataUsed") if isinstance(u.get("dataUsed"), dict) else {}
        th = u.get("theme")
        links = u.get("links") if isinstance(u.get("links"), dict) else {}
        res = links.get("results") or []
        rows.append({
            "id": u.get("id"), "title": _trim(u.get("title"), 110), "status": _RQ_STATUS.get(u.get("status")),
            "blocked_reason": _trim(u.get("blockedReason"), 90),
            "kind": u.get("kind"), "theme": th, "theme_group": None if not th else ("ml" if str(th).startswith("ml") else "trading"),
            "harness": _trim(du.get("harness") or du.get("workflow"), 60),
            "compute": _RQ_BACKEND.get(u.get("backend")), "verdict": u.get("verdict"),
            "last_run_at": u.get("lastDispatchedAt"), "result_at": u.get("latestResultAt"),
            "result_pointer": (res[-1] if res else links.get("run")),
            "stuck": u.get("stuck"), "last_activity": u.get("lastActivity")})
    def tally(key):
        out: dict[str, int] = {}
        for r in rows:
            out[str(r[key])] = out.get(str(r[key]), 0) + 1
        return out
    sel = [r for r in rows
           if (want_status == "all" or (want_status == "pipeline" and r["status"] != "done") or r["status"] == want_status)
           and (want_theme == "all" or r["theme_group"] == want_theme)]
    sel.sort(key=lambda r: (r["last_activity"] or ""), reverse=True)
    return _env(repo, "partial" if cat["readErrors"] else "read",
                {"units_scanned": len(rows), "matched": len(sel), "limit": limit, "offset": offset,
                 "filter": {"status": want_status, "theme": want_theme}, "read_errors": len(cat["readErrors"]),
                 "note": "counts cover every unit; rows are the filtered page, newest activity first"},
                counts={"by_status": tally("status"), "by_theme_group": tally("theme_group"), "by_compute": tally("compute")},
                rows=sel[offset:offset + limit])


# ───────────────────────────── work_items (console Work tab, step C3) ─────────────────────────────
#: The work store's read routes (WORK-STORE S1, live since 2026-11-05) on the trader VM. The GETs are open
#: reads while SITE_AUTH_ENFORCE is off; when it is armed the gate accepts the service bearer on GET only,
#: so the connector sends DASHBOARD_API_TOKEN when the host has it. The work register is public-repo data
#: (the same rows as work_rows), so this tool is NOT in GATED_TOOLS.
WORK_ITEM_KEYS = ("id", "kind", "parent_id", "title", "state", "owner", "lane", "tier", "due_at", "priority_rank",
                  "next_action", "summary", "terminal_reason", "prs", "created_at", "updated_at", "version")
WORK_VIEWS = ("recent", "due", "open", "state")
OPEN_ITEM_STATES = ("queued", "in_flight", "blocked", "routed", "landed_unproven")


def _frozen() -> bool:
    try:
        from src.runtime import work_read
        return work_read.frozen()
    except Exception:  # noqa: BLE001  # allow-silent: unknown freeze state reports the route's own field
        return False


def _work_get(path: str) -> Any:
    tok = (os.environ.get("DASHBOARD_API_TOKEN") or "").strip() or None
    return FETCH(path, tok) if tok else _public(path)


def _slim_item(it: dict) -> dict:
    out = {k: it.get(k) for k in WORK_ITEM_KEYS}
    out["by"] = it.get("updated_by")   # who last wrote it: the C3 check is "a session-written item appears"
    out["blocked_on"] = [b.get("ref") for b in (it.get("blocked_on") or []) if isinstance(b, dict)] or None
    src = (it.get("extra") or {}).get("_source") if isinstance(it.get("extra"), dict) else None
    out["source"] = src or "store"      # "checklist" / "pipeline" = imported by S2; "store" = written natively
    return out


def work_items(args: dict[str, Any]) -> dict[str, Any]:
    """Work-store items for the console Work tab (C3), or one item's events when ``item_id`` is given.

    view: recent (newest updated_at first; ``since_hours`` window, default 24) | due (the due_now view) |
    open (queued/in_flight/blocked/routed/landed_unproven, newest first) | state (needs ``state``).
    """
    import urllib.parse as up
    now = _now()
    item_id = (args.get("item_id") or "").strip()
    if item_id:
        path = f"/api/bot/work/items/{up.quote(item_id, safe='')}/events"
        try:
            doc = _work_get(path)
        except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
            return {"as_of": D._iso(now), "read_state": "could_not_look", "item_id": item_id, "events": None,
                    "population": {"events_scanned": None}, "error": _err(exc), "upstream": path}
        evs = doc.get("events") or []
        tail = [{"seq": e.get("seq"), "at": e.get("at") or e.get("ts") or e.get("created_at"), "op": e.get("op"),
                 "by": e.get("by"), "op_id": e.get("op_id")} for e in evs[-40:]]
        return {"as_of": D._iso(now), "read_state": "read", "item_id": item_id, "events": tail,
                "population": {"events_scanned": len(evs), "shown": len(tail), "truncated": len(evs) > len(tail)},
                "chain": doc.get("chain"), "upstream": path}

    view = str(args.get("view") or "recent")
    if view not in WORK_VIEWS:
        view = "recent"
    limit = max(1, min(200, int(args.get("limit") or 30)))
    offset = max(0, int(args.get("offset") or 0))
    q: dict[str, Any] = {"limit": limit, "offset": offset}
    since = None
    if view == "recent":
        hours = max(1, min(24 * 14, int(args.get("since_hours") or 24)))
        since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        q["since"] = since
    elif view == "due":
        q["due"] = 1
    elif view == "state":
        st = str(args.get("state") or "")
        if not re.fullmatch(r"[a-z_]{2,24}", st):
            return {"as_of": D._iso(now), "read_state": "could_not_look", "items": None, "count": None,
                    "population": {"rows_scanned": None}, "error": "view=state needs a state, e.g. in_flight"}
        q["state"] = st
    if args.get("kind"):
        q["kind"] = str(args["kind"])

    def fetch(qq: dict) -> dict:
        return _work_get("/api/bot/work/items?" + up.urlencode(qq))

    try:
        if view == "open":
            # the route filters one state at a time: read each open state (5 cheap indexed reads) and merge
            items, per_state = [], {}
            for st in OPEN_ITEM_STATES:
                d = fetch({**q, "state": st, "offset": 0, "limit": min(1000, limit + offset)})
                got = d.get("items") or []
                per_state[st] = len(got)
                items.extend(got)
            items.sort(key=lambda it: str(it.get("updated_at") or ""), reverse=True)
            items = items[offset: offset + limit]
            doc = {"total": d.get("total"), "canonical": d.get("canonical"), "note": d.get("note")}
        else:
            doc = fetch(q)
            items, per_state = doc.get("items"), None
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason, never []
        return {"as_of": D._iso(now), "read_state": "could_not_look", "view": view, "items": None, "count": None,
                "population": {"rows_scanned": None}, "error": _err(exc)}
    if items is None or doc.get("readState") == "could_not_look":
        return {"as_of": D._iso(now), "read_state": "could_not_look", "view": view, "items": None, "count": None,
                "population": {"rows_scanned": None}, "error": doc.get("error") or "upstream returned no items"}
    slim = [_slim_item(it) for it in items]
    return {"as_of": D._iso(now), "read_state": "read", "view": view, "since": since, "count": len(slim),
            "items": slim,
            "population": {"store_items_total": doc.get("total"), "returned": len(slim), "offset": offset,
                           "limit": limit, "per_state": per_state,
                           "next_offset": offset + limit if len(slim) == limit else None},
            # the route still prints its S1-era "canonical": false; the committed S4 freeze is the fact
            "canonical": True if _frozen() else doc.get("canonical"),
            "canonical_note": ("register of record since the WORK-STORE S4 freeze (docs/claude/work/checklist/"
                               "_header.json frozen_into_work_store); the repo row files are its export")
            if _frozen() else (doc.get("note") or "the checklist + pipeline files are canonical until WORK-STORE S4"),
            "upstream": f"{LIVE_BASE}/api/bot/work/items"}


# ───────────────────── alerts · journal · reports (spec § 2.3; SIGN-IN ONLY) ─────────────────────
#: These serve the alert ledger, closed trades with P&L, order packages and the review reports, so
#: server.py lists them in GATED_TOOLS: they answer only while the connector's Google sign-in is on.
ALERT_KEYS = ("ts", "kind", "channel", "priority", "delivered", "reason", "body")
URGENT = ("system",)


def alerts(args: dict[str, Any]) -> dict[str, Any]:
    """The live alert ledger (GET /api/bot/alerts): newest first, optionally only urgent ones
    (channel system or priority high, the filter that wakes the manager)."""
    import urllib.parse as up
    now = _now()
    hours = max(1, min(24 * 14, int(args.get("since_hours") or 24)))
    limit = max(1, min(200, int(args.get("limit") or 40)))
    q: dict[str, Any] = {"since": (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 2000}
    for k in ("kind", "channel"):
        if args.get(k):
            q[k] = str(args[k])
    path = "/api/bot/alerts?" + up.urlencode(q)
    try:
        doc = _work_get(path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"as_of": D._iso(now), "read_state": "could_not_look", "rows": None, "count": None,
                "population": {"rows_scanned": None}, "error": _err(exc)}
    if not isinstance(doc, dict) or doc.get("rows") is None or doc.get("read_state") == "could_not_look":
        return {"as_of": D._iso(now), "read_state": "could_not_look", "rows": None, "count": None,
                "population": {"rows_scanned": None}, "error": (doc or {}).get("error") if isinstance(doc, dict) else None}
    rows = doc["rows"]
    if args.get("urgent"):
        rows = [r for r in rows if r.get("channel") in URGENT or r.get("priority") == "high"]
    rows = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    shown = [{k: (r.get(k)[:400] if k == "body" and isinstance(r.get(k), str) else r.get(k)) for k in ALERT_KEYS}
             for r in rows[:limit]]
    return {"as_of": D._iso(now), "read_state": doc.get("read_state") or "read", "since_hours": hours,
            "urgent_only": bool(args.get("urgent")), "count": len(rows), "rows": shown,
            "counts_by_kind": doc.get("counts_by_kind"), "newest_ts": doc.get("newest_ts"),
            "population": {"ledger_rows_matching": doc.get("total_matching"), "returned": len(shown),
                           "upstream_truncated": doc.get("rows_truncated_to_limit"), "upstream": doc.get("population")}}


TRADE_KEYS = ("id", "account", "accountClass", "assetClass", "symbol", "side", "qty", "entryPrice", "exitPrice",
              "openedAt", "closedAt", "closeReason", "pattern", "realizedPnl", "realizedPnlPct", "pnlProvenance",
              "journalTrust")
PACKAGE_KEYS = ("orderPackageId", "strategy", "symbol", "direction", "status", "tradeStatus", "entry", "sl", "tp",
                "confidence", "claudeScore", "pnl", "closeReason", "accountClass", "createdAt", "updatedAt",
                "linkedTradeId")


def journal(args: dict[str, Any]) -> dict[str, Any]:
    """Closed trades (GET /api/bot/trades/closed) or order packages (GET /api/bot/order-packages), newest first."""
    import urllib.parse as up
    now = _now()
    kind = "packages" if args.get("kind") == "packages" else "trades"
    limit = max(1, min(200, int(args.get("limit") or 50)))
    offset = max(0, int(args.get("offset") or 0))
    if kind == "trades":
        q: dict[str, Any] = {"limit": limit, "offset": offset, "include_paper": "true" if args.get("include_paper") else "false"}
        if args.get("account"):
            q["account_id"] = str(args["account"])
        if args.get("since"):
            q["since"] = str(args["since"])
        path, keys = "/api/bot/trades/closed?" + up.urlencode(q), TRADE_KEYS
    else:
        q = {"limit": limit, "offset": offset}
        for k in ("strategy", "symbol", "status"):
            if args.get(k):
                q[k] = str(args[k])
        path, keys = "/api/bot/order-packages?" + up.urlencode(q), PACKAGE_KEYS
    try:
        doc = _work_get(path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"as_of": D._iso(now), "read_state": "could_not_look", "kind": kind, "rows": None, "count": None,
                "population": {"rows_scanned": None}, "error": _err(exc)}
    rows = doc if isinstance(doc, list) else (doc.get("rows") if isinstance(doc, dict) else None)
    if rows is None:
        return {"as_of": D._iso(now), "read_state": "could_not_look", "kind": kind, "rows": None, "count": None,
                "population": {"rows_scanned": None}, "error": "upstream returned no rows"}
    shown = [{k: r.get(k) for k in keys} for r in rows if isinstance(r, dict)]
    return {"as_of": D._iso(now), "read_state": "read", "kind": kind, "count": len(shown), "rows": shown,
            "population": {"returned": len(shown), "offset": offset, "limit": limit,
                           "next_offset": offset + limit if len(shown) == limit else None,
                           "include_paper": bool(args.get("include_paper")) if kind == "trades" else None,
                           "filter_state": doc.get("filter_state") if isinstance(doc, dict) else None},
            "upstream": path.split("?")[0]}


def reports(args: dict[str, Any]) -> dict[str, Any]:
    """The review reports index (GET /api/bot/reports), or one report's metadata + markdown/HTML body."""
    import urllib.parse as up
    now = _now()
    rid = (args.get("report_id") or "").strip()
    path = "/api/bot/reports" + (f"/{up.quote(rid, safe='')}" if rid else "")
    try:
        doc = _work_get(path)
    except Exception as exc:  # noqa: BLE001  # allow-silent: could_not_look with the reason
        return {"as_of": D._iso(now), "read_state": "could_not_look", "report_id": rid or None,
                "population": {"rows_scanned": None}, "error": _err(exc)}
    if rid:
        body = doc.get("html") or doc.get("html_body") or doc.get("body") or ""
        body = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", body) if isinstance(body, str) else ""
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        meta = {k: v for k, v in doc.items() if not isinstance(v, str) or len(v) < 400}
        return {"as_of": D._iso(now), "read_state": "read", "report_id": rid, "meta": meta,
                "text": text[:12000], "population": {"text_chars": len(text), "truncated": len(text) > 12000}}
    reps = doc.get("reports") if isinstance(doc, dict) else None
    if reps is None:
        return {"as_of": D._iso(now), "read_state": "could_not_look", "report_id": None, "reports": None,
                "population": {"rows_scanned": None}, "error": "upstream returned no reports"}
    limit = max(1, min(100, int(args.get("limit") or 30)))
    keys = ("id", "headline", "generated_at", "window", "window_start", "window_end", "roll_up_grade")
    reps = sorted(reps, key=lambda r: str(r.get("generated_at") or ""), reverse=True)
    return {"as_of": D._iso(now), "read_state": "read", "count": len(reps),
            "reports": [{k: r.get(k) for k in keys} for r in reps[:limit]],
            "population": {"reports_total": doc.get("total"), "returned": min(limit, len(reps))}}
