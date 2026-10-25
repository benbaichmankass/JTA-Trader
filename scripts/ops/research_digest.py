#!/usr/bin/env python3
# wiring: scripts/ops/work_digest_now.py (the hourly MANAGER update, ict-work-digest.timer)
"""RESEARCH QUEUE section of the manager update — everything NEW since the last one.

Operator, 2026-10-11 (verbatim): *"on the Claude channel, I want the regular
status updates to be divided into clear collapsible sections, and one of them
should include a review on everything new from the research que (tests run,
passed, failed, needs further research, etc)"* — checklist row
``TELEGRAM-CHANNELS``.

POPULATION. ``research/queue/*.yaml`` (unit status + ``last_dispatched_at``) and
every row of ``research/results/*/*.jsonl`` (``research_unit``, ``verdict``,
``power_state``, ``note``), read from the checkout this runs in (the VM clone,
git-synced from ``main`` every ~5 min — so a result is "new" when it LANDS on
main, not when it was generated).

CURSOR. ``runtime_logs/research_digest_cursor.json`` holds the previous
snapshot: each unit's status + dispatch stamp, and each result file's row count.
"New" is the difference. It is advanced ONLY after the update carrying it was
enqueued (``commit``), so a failed send re-reports rather than skips.
⚠️ With NO cursor (first run, or an unreadable file) the section says so and
reports a FIXED window instead — result rows ``generated_at`` in the last
``FIRST_RUN_WINDOW_H`` hours — and no status transitions (there is nothing to
diff against). It never reads as "nothing new".

"COULD NOT LOOK" ≠ "NOTHING NEW". An absent/unreadable queue directory renders
``read_state: unreadable`` and a ⚠️ line; unreadable result files are counted.
Missing fields render "—".
"""
from __future__ import annotations

import json
import re as _re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CURSOR = REPO_ROOT / "runtime_logs" / "research_digest_cursor.json"
FIRST_RUN_WINDOW_H = 24
_NOTE_CHARS = 110

PASSED, FAILED, FURTHER, OTHER = "passed", "failed", "needs_further_research", "other"
#: verdict -> bucket. ``indeterminate`` and any under-powered / accruing row are
#: "needs further research"; an unrecognised verdict is OTHER, shown verbatim.
_VERDICT_BUCKET = {"pass": PASSED, "fail": FAILED, "indeterminate": FURTHER,
                   "no_action_warranted": OTHER, "wiring_only": OTHER,
                   "not_applicable": OTHER}
#: ⚠️ ``accruing`` is deliberately NOT here: it is the power_state of ~60% of
#: all rows (395 of 650 on 2026-10-11) including rule-scored pass/fail rows,
#: so treating it as "no verdict" would hide the verdicts the operator asked for.
_UNDERPOWERED = {"underpowered", "insufficient_n"}


def _dash(v: Any) -> str:
    return "—" if v in (None, "") else str(v)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def snapshot(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Read the queue + results. Never raises; failures are COUNTED."""
    import yaml  # noqa: PLC0415 — the trader venv has it; keep import lazy

    qdir, rdir = root / "research" / "queue", root / "research" / "results"
    units: dict[str, dict] = {}
    unreadable_units = 0
    queue_state = "read" if qdir.is_dir() else "unreadable"
    for f in sorted(qdir.glob("*.yaml")) if qdir.is_dir() else []:
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            uid = str(d.get("id") or f.stem)
            units[uid] = {"status": _dash(d.get("status")),
                          "last_dispatched_at": d.get("last_dispatched_at")
                          and str(d.get("last_dispatched_at")),
                          "title": str(d.get("title") or "")[:_NOTE_CHARS]}
        except Exception:  # noqa: BLE001 — counted, not hidden
            unreadable_units += 1
    results: dict[str, int] = {}
    unreadable_results = 0
    results_state = "read" if rdir.is_dir() else "unreadable"
    for f in sorted(rdir.glob("*/*.jsonl")) if rdir.is_dir() else []:
        try:
            results[str(f.relative_to(root))] = sum(
                1 for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip())
        except (OSError, UnicodeDecodeError):
            unreadable_results += 1
    return {"units": units, "results": results, "queue_state": queue_state,
            "results_state": results_state, "unreadable_units": unreadable_units,
            "unreadable_results": unreadable_results}


def read_cursor(path: Path = CURSOR) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and "units" in d and "results" in d else None
    except (OSError, ValueError):
        return None


def commit(snap: dict, path: Path = CURSOR, now: Optional[datetime] = None) -> None:
    """Advance the cursor. Call ONLY after the update was enqueued."""
    payload = {"at": (now or datetime.now(timezone.utc)).isoformat(),
               "units": snap["units"], "results": snap["results"]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"research-digest: WARNING could not write cursor: {exc}")


def _bucket(row: dict) -> str:
    b = _VERDICT_BUCKET.get(str(row.get("verdict") or "").strip().lower(), OTHER)
    if b == OTHER and not row.get("verdict"):
        return FURTHER
    ps = str(row.get("power_state") or "").strip().lower()
    if b in (PASSED, FAILED) and ps in _UNDERPOWERED:
        return FURTHER  # a verdict at insufficient n is not yet a verdict
    if b == OTHER and ps in _UNDERPOWERED:
        return FURTHER
    return b


def _new_rows(root: Path, snap: dict, prev: Optional[dict], now: datetime) -> tuple[list[dict], int]:
    rows, unreadable = [], 0
    since = now - timedelta(hours=FIRST_RUN_WINDOW_H)
    for rel, n in snap["results"].items():
        skip = (prev or {}).get("results", {}).get(rel, 0) if prev is not None else 0
        if prev is not None and n <= skip:
            continue
        try:
            lines = [ln for ln in (root / rel).read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        for ln in lines[skip:] if prev is not None else lines:
            try:
                r = json.loads(ln)
            except ValueError:
                unreadable += 1
                continue
            if prev is None:
                t = _parse_ts(r.get("generated_at"))
                if not (t and t >= since):
                    continue
            if isinstance(r, dict):
                r.setdefault("_unit_dir", Path(rel).parent.name)
                rows.append(r)
    return rows, unreadable


_RQ_RE = _re.compile(r"(RQ-\d{8}-[A-Za-z0-9]+(?:-\d{2})?)")


def _attribute(r: dict) -> Optional[str]:
    """The unit a row belongs to: its own ``research_unit``, else its results
    directory, else an RQ id inside its rule id, else the producing check named
    by rule (e.g. the soak-book grade). ``None`` only when nothing names it."""
    unit = r.get("research_unit")
    if unit:
        return str(unit)
    d = str(r.get("_unit_dir") or "")
    if d and not d.startswith("_"):
        return d
    rule = str((r.get("decision_rule") or {}).get("id") or "")
    m = _RQ_RE.search(rule)
    if m:
        return m.group(1)
    if rule:
        return rule.removeprefix("RULE-")
    tool = (r.get("produced_by") or {}).get("tool")
    return str(tool) if tool else None


def _unit_meta(root: Path, unit: str, cache: dict) -> dict:
    if unit in cache:
        return cache[unit]
    meta: dict = {}
    f = root / "research" / "queue" / f"{unit}.yaml"
    try:
        import yaml  # noqa: PLC0415
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        title = _re.sub(r"\([^)]*\)", "", str(d.get("title") or d.get("question") or ""))
        title = title.split(": ", 1)[-1] if ": " in title else title
        meta["title"] = " ".join(title.split())[:60]
        rule = d.get("decision_rule") or {}
        meta["rule"] = str(rule.get("rule") or "") if isinstance(rule, dict) else ""
    except Exception:  # noqa: BLE001 — a missing unit yaml just means less context
        pass
    cache[unit] = meta
    return meta


def _fmt(v: Any) -> str:
    return f"{v:+.2f}" if isinstance(v, float) else str(v)


def _metric(r: dict) -> str:
    """The key numbers of a result row, in a fixed precedence. "" when none."""
    m = r.get("measurement") if isinstance(r.get("measurement"), dict) else {}
    pop_n = (r.get("population") or {}).get("n") if isinstance(r.get("population"), dict) else None
    parts: list[str] = []
    if "net_total_r" in m:
        parts.append(f"net {_fmt(m['net_total_r'])}R")
        if "net_expectancy_r" in m:
            parts.append(f"{_fmt(m['net_expectancy_r'])}R/trade")
        parts.append(f"n={m.get('total_trades', pop_n if pop_n is not None else '—')}")
    elif "base_net_r_OOS" in m:
        parts.append(f"OOS base {_fmt(m['base_net_r_OOS'])}R n={m.get('base_trades_OOS', '—')}")
        if "cells_passed" in m:
            parts.append(f"cells {m['cells_passed']}/{m.get('cells_swept', '—')} passed")
    elif "net_r_pooled" in m:
        parts.append(f"pooled {_fmt(m['net_r_pooled'])}R")
        if "net_r_half1" in m:
            parts.append(f"halves {_fmt(m['net_r_half1'])}/{_fmt(m.get('net_r_half2'))}R")
    elif isinstance(m.get("by_disposition"), dict):
        parts.append(" · ".join(f"{k} {v}" for k, v in m["by_disposition"].items()))
    for k, v in m.items():
        if "delta" in k.lower() and not isinstance(v, (dict, list)):
            parts.append(f"{k} {_fmt(v)}")
            break
    if not parts and pop_n is not None:
        parts.append(f"n={pop_n}")
    return ", ".join(parts)


def _next_step(rule_text: str, verdict: str) -> str:
    """What the unit's OWN registered rule says follows this verdict (the text
    after ``--`` in its clause), else ""."""
    if not rule_text or not verdict:
        return ""
    m = _re.search(rf"{_re.escape(verdict)}\s+IF[^-]*?--\s*([^.]+)", rule_text, _re.I)
    return " ".join(m.group(1).split())[:90] if m else ""


def summarise_row(r: dict, root: Path = REPO_ROOT, cache: Optional[dict] = None) -> Optional[str]:
    """``unit — leg/question: verdict · key metric → next`` for one row, or
    None when the row cannot be attributed. Never a bare "—" summary: when the
    row has no note the line is built from the unit yaml + measurement."""
    unit = _attribute(r)
    if unit is None:
        return None
    meta = _unit_meta(root, unit, cache if cache is not None else {})
    verdict = _dash(r.get("verdict"))
    ps = str(r.get("power_state") or "")
    metric = _metric(r)
    note = " ".join(str(r.get("note") or (r.get("measurement") or {}).get("note") or "").split())
    nxt = _next_step(meta.get("rule", ""), verdict)
    head = f"{unit}" + (f" — {meta['title']}" if meta.get("title") else "")
    body = verdict + (f" · {metric}" if metric else "")
    if ps and ps in _UNDERPOWERED:
        body += f" · power {ps}"
    if not metric and note:
        body += f": {note[:_NOTE_CHARS]}"
    if nxt:
        body += f" → {nxt}"
    if not metric and not note and not nxt:
        body += " (row carries no measurement — open the result file)"
    return f"{head}: {body}"


def build(root: Path = REPO_ROOT, prev: Optional[dict] = None,
          now: Optional[datetime] = None, snap: Optional[dict] = None) -> dict[str, Any]:
    """The section's data: new results bucketed + unit transitions."""
    now = now or datetime.now(timezone.utc)
    snap = snap or snapshot(root)
    rows, bad_rows = _new_rows(root, snap, prev, now)
    buckets: dict[str, list[str]] = {PASSED: [], FAILED: [], FURTHER: [], OTHER: []}
    cache: dict = {}
    unattributed = 0
    run_ids: set[str] = set()
    for r in rows:
        line = summarise_row(r, root, cache)
        if line is None:
            unattributed += 1
            continue
        rid = (r.get("produced_by") or {}).get("run_id") if isinstance(r.get("produced_by"), dict) else None
        run_ids.add(str(rid or f"{_attribute(r)}@{r.get('generated_at')}"))
        buckets[_bucket(r)].append(line)

    trans = {"run": [], "newly_queued": [], "newly_blocked": [], "unblocked": [],
             "done": [], "retired": []}
    if prev is not None:
        pu = prev.get("units", {})
        for uid, u in sorted(snap["units"].items()):
            p = pu.get(uid)
            title = u.get("title") or "—"
            if p is None:
                if u["status"] == "queued":
                    trans["newly_queued"].append(f"{uid} — {title}")
                elif u["status"] == "blocked":
                    trans["newly_blocked"].append(f"{uid} — {title}")
                continue
            if u.get("last_dispatched_at") and u["last_dispatched_at"] != p.get("last_dispatched_at"):
                trans["run"].append(f"{uid} — fired {u['last_dispatched_at'][:16]}")
            if u["status"] != p.get("status"):
                if u["status"] == "blocked":
                    trans["newly_blocked"].append(f"{uid} — {title}")
                elif p.get("status") == "blocked":
                    trans["unblocked"].append(f"{uid} — now {u['status']}")
                if u["status"] == "done":
                    trans["done"].append(f"{uid} — {title}")
                elif u["status"] == "retired":
                    trans["retired"].append(f"{uid} — {title}")
    else:
        # No cursor: count the units FIRED inside the same fixed window the
        # results are drawn from, so the headline's run count matches the list.
        since = now - timedelta(hours=FIRST_RUN_WINDOW_H)
        for uid, u in sorted(snap["units"].items()):
            t = _parse_ts(u.get("last_dispatched_at"))
            if t and t >= since:
                trans["run"].append(f"{uid} — fired {u['last_dispatched_at'][:16]}")
    statuses: dict[str, int] = {}
    for u in snap["units"].values():
        statuses[u["status"]] = statuses.get(u["status"], 0) + 1
    return {"mode": "since_last_update" if prev is not None else "first_run_window",
            "since": (prev or {}).get("at"), "window_h": FIRST_RUN_WINDOW_H,
            "buckets": buckets, "transitions": trans, "statuses": statuses,
            "queue_state": snap["queue_state"], "results_state": snap["results_state"],
            "unreadable": snap["unreadable_units"] + snap["unreadable_results"] + bad_rows,
            "unattributed": unattributed, "runs_in_window": len(run_ids),
            "snapshot": snap}


_LABELS = ((PASSED, "✅ PASSED"), (FAILED, "❌ FAILED"),
           (FURTHER, "🔁 NEEDS FURTHER RESEARCH (indeterminate / underpowered / insufficient n)"),
           (OTHER, "· other verdicts (no action / wiring only / n.a.)"))
_TRANS = (("run", "▶ units run"), ("newly_queued", "🆕 newly queued"),
          ("newly_blocked", "⛔ newly blocked"), ("unblocked", "🔓 unblocked"),
          ("done", "🏁 done"), ("retired", "🗑 retired"))


def headline(d: dict) -> str:
    """One line for the visible headline."""
    if d["queue_state"] != "read" or d["results_state"] != "read":
        return "🔬 research: ⚠️ queue/results NOT READ — could not look"
    b, t = d["buckets"], d["transitions"]
    n = sum(len(v) for v in b.values())
    # Every count here is the length of a list the section prints, so the
    # headline and the body cannot disagree (operator, 2026-10-11: "0 run"
    # beside 24 listed results).
    return (f"🔬 research: {n} result(s) — {len(b[PASSED])} pass · {len(b[FAILED])} fail · "
            f"{len(b[FURTHER])} further · {len(b[OTHER])} other · "
            f"{len(t['run'])} unit(s) fired · {len(t['newly_queued'])} newly queued · "
            f"{len(t['newly_blocked'])} newly blocked")


def render_body(d: dict) -> str:
    """Plain-text body for the expandable section (escaped by the renderer)."""
    L: list[str] = []
    if d["mode"] == "first_run_window":
        L.append(f"No prior cursor — showing results generated and units fired in the "
                 f"last {d['window_h']}h (fixed window). Status transitions start next update.")
    else:
        L.append(f"New since the last update ({_dash(d['since'])[:16]}Z).")
    if d["queue_state"] != "read":
        L.append("⚠️ research/queue NOT READ — we could not look; this is NOT 'nothing new'.")
    if d["results_state"] != "read":
        L.append("⚠️ research/results NOT READ — we could not look; this is NOT 'nothing new'.")
    if d.get("unattributed"):
        L.append(f"· {d['unattributed']} result row(s) name no unit, rule or tool — omitted.")
    if d["unreadable"]:
        L.append(f"⚠️ {d['unreadable']} unreadable file(s)/row(s) skipped.")
    nothing = True
    for key, label in _LABELS:
        items = d["buckets"][key]
        if items:
            nothing = False
            L.append(f"{label} ({len(items)}):")
            L += [f"  {x}" for x in items]
    for key, label in _TRANS:
        items = d["transitions"][key]
        if items:
            nothing = False
            L.append(f"{label} ({len(items)}):")
            L += [f"  {x}" for x in items[:8]]
            if len(items) > 8:
                L.append(f"  … +{len(items) - 8} more")
    if nothing and d["queue_state"] == "read" and d["results_state"] == "read":
        L.append("Nothing new — queue and results were read; no new result rows "
                 "and no unit status change.")
    st = d["statuses"]
    L.append("Queue now: " + (" · ".join(f"{k} {v}" for k, v in sorted(st.items())) or "—")
             + f" (of {sum(st.values())} units)")
    return "\n".join(L)
