#!/usr/bin/env python3
# wiring: called once per hourly pass by scripts/ops/work_digest_now.py::run
# (deploy/ict-work-digest.timer — the ONE scheduled carrier; this module has no
# unit of its own, by decision, see the docstring). Receipt readable at
# /api/diag/log_file?name=attention_watch_receipt. Guard:
# scripts/ci/run_guards.py::attention-watch (--self-test).
"""THE ATTENTION WATCH — the VM tells people when something needs them.

Design of record: ``docs/plans/work-system-2026-10-04.md`` (WORK-SYSTEM row).

WHY THIS EXISTS (measured 2026-10-04 by Manager Session 2026-10-04): 366
pipeline items due, 151 unrouted, 25 ``ask_operator`` items due that had never
reached the operator; the R5 weekly soak grade's last record is 2026-09-26 and
this week's run landed nothing; the brief at ``GET /api/bot/work/brief`` was
737 KB and nobody read it. Everything that was supposed to ask for attention
was a PAGE someone had to choose to open. This module PUSHES.

ONE MESSAGE, ONE CARRIER (operator decision 2026-10-04 ~15:30Z, relayed by the
manager): fold into the EXISTING hourly digest — ``ict-work-digest.timer`` →
``work_digest_now.py``. No timer of its own. ``work_digest_now.run()`` calls
``prepare()``, PREPENDS the block to its change digest, sends ONE message, and
calls ``commit()`` only after the enqueue succeeded. The block puts the
ACTIONABLE things first:

  * NEW since the last digest, marked 🆕 (edge items, only on change):
      - a new ``ask_operator`` pipeline item;
      - a soak moving into ``passed`` / ``mechanical_fail`` (the mechanical
        soak, operator 2026-10-15: no calendar, so no overdue / dead)
        (``scripts/ops/soak_state.py::soak_states()``, SOAK-WATCH's live
        computation — never computed here);
      - a silence alarm breaching (re-sent at most every ``REALERT_HOURS``)
        or clearing. The alarms cover: the R5 weekly soak grade
        (``SOAK_GRADE_MAX_DAYS``), research results (``RESEARCH_MAX_HOURS``),
        quiet ``in_flight`` rows (``INFLIGHT_STALE_DAYS``), the checklist
        unwritten (``MANAGER_SILENT_HOURS``), and the 05:30Z work report
        missing, stale, errored or oversized.
  * once a day at/after ``DIGEST_HOUR_UTC``: the ranked summary (counts + top
    items, ask_operator first);
  * otherwise ONE line: "no new actionable items", plus open counts.

So a new actionable thing is unmissable and the steady state is quiet.

MANAGER READS IT: a session cannot receive Telegram, so each committed block is
appended to ``runtime_logs/work_reports/digest_log.jsonl`` and served at
``GET /api/bot/work/report?since=<iso>``.

NEVER COLLAPSED: every probe returns ``ok`` / ``breached`` / ``unknown``.
``unknown`` (we could not look — shallow clone, unreadable file, missing
module) is reported as such and is never read as ``ok``. A digest that cannot
read the pipeline says so in its first line.

Read-only against the repo. Its only writes are under ``runtime_logs/``
(state, receipt, digest log) and, standalone only, the ping inbox. Sends go to the
@claude_ict_comms_bot inbox (``send_ping.enqueue(target="claude")``) — the
operator's Claude-comms channel, separate from trade alerts.

Usage::

    python3 scripts/ops/attention_watch.py              # one standalone pass (sends)
    python3 scripts/ops/attention_watch.py --dry-run    # print, send nothing, keep state
    python3 scripts/ops/attention_watch.py --digest-now # force today's digest
    python3 scripts/ops/attention_watch.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.ops import pipeline  # noqa: E402
from scripts.ops import prop_trail_watch  # noqa: E402
from scripts.ops import prop_silence  # noqa: E402

# ⚠️ Anchored to the repo root, like work_digest_now.py: the unit carries no
# data-dir drop-in and diag reads the receipt through repo_root().
STATE = REPO_ROOT / "runtime_logs" / "attention_watch_state.json"
# LTR-1B-ATTENTION-PROBE: when each (package, event) was first seen DUE. The due
# route recomputes ``bar_start`` from "now" on every call, so "due since" exists
# nowhere else; this observation cache is the only memory the probe has.
LR_DUE_SEEN = REPO_ROOT / "runtime_logs" / "live_review_due_seen.json"
LR_CONFIG = REPO_ROOT / "config" / "live_trade_review.yaml"
LR_REVIEWS_REL = "comms/live_review/reviews.jsonl"
LR_ROWS_REF = "refs/live-review/live-review/rows"   # the VM watcher's own fetch namespace
DESK_REF = "refs/live-review/desk/decisions"   # the VM rows watcher's fetch of the desk branch (DESK-4-INTAKE)
DESK_POINTER = "comms/desk/latest_scan.json"
DESK_DECISIONS = "comms/desk/decisions.jsonl"
RECEIPT = REPO_ROOT / "runtime_logs" / "attention_watch_receipt.json"

CHECKLIST = REPO_ROOT / "docs" / "claude" / "work" / "MANAGER-CHECKLIST.json"
SOAK_GRADE_DIR = REPO_ROOT / "comms" / "research" / "soak_book_grade"
RESEARCH_RESULTS = "research/results"

# Bounds. Constants, so moving one is a reviewed diff, not a tuning knob.
DIGEST_HOUR_UTC = 6          # before the operator's day; after the 03:10Z grade slot
SOAK_GRADE_MAX_DAYS = 8      # weekly (Sun 03:00Z) + one day of grace
RESEARCH_MAX_HOURS = 36      # dispatcher lands results several times a day when healthy
INFLIGHT_STALE_DAYS = 3      # an in_flight row nobody has touched in 3 days is not in flight
MANAGER_SILENT_HOURS = 30    # one daily review + 6h grace
DESK_WAKE_POST_MAX_HOURS = 3  # the VM producer writes its receipt every pass (~2 min); 3 h silent = it stopped
DESK_ROW_MISSING_MIN = 15    # a desk packet this old with no decision row: the wake did not run (G1, MEASURED 7 h on 2026-10-28)
REALERT_HOURS = 24
TOP_N = 8
#: The mechanical soak (operator 2026-10-15): ``passed`` is a promotion candidate,
#: ``mechanical_fail`` is a fault to fix (HIGH). ``awaiting_first_trade`` /
#: ``in_progress`` are quiet — waiting is not failing and has no deadline.
ALERT_SOAK_STATES = ("passed", "mechanical_fail")

OK, BREACHED, UNKNOWN = "ok", "breached", "unknown"


# ── small helpers ────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                             text=True, check=False, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout if out.returncode == 0 else None


def _is_shallow() -> bool | None:
    out = _git("rev-parse", "--is-shallow-repository")
    return None if out is None else out.strip() == "true"


def _last_commit_time(path: str) -> datetime | None:
    out = _git("log", "-1", "--format=%ct", "--", path)
    if not out or not out.strip():
        return None
    return datetime.fromtimestamp(int(out.strip()), tz=timezone.utc)


def _short(s: Any, n: int = 140) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"attention-watch: WARNING could not write {path.name}: {exc}")


# ── pipeline: ranking + ask_operator ─────────────────────────────────────────
def rank_attention(items: list[dict], today: date) -> list[dict]:
    """Due items, ranked for a HUMAN: ask_operator first, then unrouted
    oldest-filed first, then routed-and-still-due oldest first."""
    rows = pipeline.due(items, today)
    far = date.max

    def key(i: dict) -> tuple:
        return (i.get("next_action") != "ask_operator",
                i.get("state") == "routed",
                pipeline.filed_date(i) or far, i.get("id", ""))
    return sorted(rows, key=key)


def _ranked(res: Any, items: list[dict], today: date) -> list[dict]:
    """Use BRIEF-FIX's ranking when it exists (PR #16384), so the digest, the
    report and the brief rank identically; fall back to ``rank_attention``."""
    try:
        from scripts.ops import render_daily_brief as rdb  # noqa: PLC0415
        fn = getattr(rdb, "ranked_items", None)
        if callable(fn):
            return list(fn(res, today))
    except Exception as exc:  # noqa: BLE001 — fall back, loudly
        print(f"attention-watch: render_daily_brief.ranked_items failed, using fallback: {exc}")
    return rank_attention(items, today)


def open_ask_operator(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("next_action") == "ask_operator"
            and i.get("state") not in pipeline.TERMINAL_STATES]


# ── soak state (owned by SOAK-WATCH; consumed, never computed, here) ─────────
# SETTLED by the manager 2026-10-04 15:25Z for all three lanes: CONTRACTS are a
# committed file SOAK-WATCH owns; STATE is COMPUTED LIVE on the VM by
# ``scripts/ops/soak_state.py::soak_states()`` (contracts + journal DB). The brief,
# the report and this pass all call it. Never a session-written state field.
SOAK_STATES = ("passed", "in_progress", "awaiting_first_trade", "mechanical_fail", "unknown")


def read_soak_states() -> tuple[str, list[dict]]:
    """``(read_state, rows)``. read_state ∈ read / absent / unreadable.
    ``absent`` = we looked and the module is not there — never "no soaks"."""
    try:
        from scripts.ops import soak_state  # noqa: PLC0415
    except ImportError:
        return "absent", []
    fn = getattr(soak_state, "soak_states", None)
    if not callable(fn):
        return "absent", []
    try:
        rows = [r for r in fn() if isinstance(r, dict)]
    except Exception as exc:  # noqa: BLE001 — a broken producer is "unreadable", loud
        print(f"attention-watch: soak_state.soak_states() raised: {exc}")
        return "unreadable", []
    out = []
    for r in rows:
        st = str(r.get("state") or "unknown")
        out.append({**r, "state": st if st in SOAK_STATES else "unknown"})
    return "read", out


QUEUE_DIR = REPO_ROOT / "research" / "queue"


def read_needs_review(queue_dir: Path | None = None) -> tuple[str, list[dict]]:
    """Units whose mechanical grading could not decide (``grading.needs_review: true``).

    PI-20261006-LCEVL8D5-0003: this bucket was only ``grep -l 'needs_review: true'
    research/queue/*.yaml`` -- reachable only by a session that thought to run it.
    Returns ``("read", rows)`` / ``("absent", [])`` (no queue dir) /
    ``("unreadable", [])`` -- never an empty list for a failed read.
    """
    d = queue_dir or QUEUE_DIR
    if not d.is_dir():
        return "absent", []
    try:
        import yaml
    except ImportError:
        return "unreadable", []
    rows: list[dict] = []
    for f in sorted(d.glob("*.yaml")):
        try:
            text = f.read_text(encoding="utf-8")
            if "needs_review: true" not in text:
                continue
            u = yaml.safe_load(text)
        except (OSError, yaml.YAMLError):
            return "unreadable", []
        g = (u or {}).get("grading") if isinstance(u, dict) else None
        if isinstance(g, dict) and g.get("needs_review") is True:
            rows.append({"id": str(u.get("id") or f.stem), "graded_at": str(g.get("graded_at") or ""),
                         "reason": g.get("reason") or g.get("note") or ""})
    return "read", rows


def _age_days(graded_at: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(graded_at[:10])).days
    except ValueError:
        return None


def _needs_review_line(v: dict) -> str | None:
    read, rows = v.get("needs_review_read", "absent"), v.get("needs_review", [])
    if read == "unreadable":
        return "❔ needs_review bucket: research/queue UNREADABLE (not zero — not measured)"
    if read != "read" or not rows:
        return None
    ages = [a for a in (_age_days(r["graded_at"], v["today"]) for r in rows) if a is not None]
    oldest = f", oldest flagged {max(ages)}d ago" if ages else ""
    ids = ", ".join(r["id"] for r in rows[:4])
    return (f"🔎 {len(rows)} research unit(s) need a read (grading.needs_review){oldest}: "
            f"{ids}{' …' if len(rows) > 4 else ''}")


def _soak_key(r: dict) -> str:
    return str(r.get("id") or f"{r.get('account', '?')}:{r.get('leg', '?')}")


# ── silence probes ───────────────────────────────────────────────────────────
def probe_soak_grade(now: datetime) -> dict:
    files = sorted(SOAK_GRADE_DIR.glob("*.json")) if SOAK_GRADE_DIR.is_dir() else []
    dated = []
    for f in files:
        try:
            dated.append(datetime.strptime(f.stem[:10], "%Y-%m-%d").date())
        except ValueError:
            continue
    if not dated:
        return {"status": UNKNOWN if not SOAK_GRADE_DIR.is_dir() else BREACHED,
                "detail": f"no dated record under {SOAK_GRADE_DIR.relative_to(REPO_ROOT)}"}
    newest = max(dated)
    age = (now.date() - newest).days
    st = BREACHED if age >= SOAK_GRADE_MAX_DAYS else OK
    return {"status": st, "detail": f"newest R5 weekly soak grade {newest} ({age}d old; "
                                    f"bound {SOAK_GRADE_MAX_DAYS}d)"}


def probe_research(now: datetime, shallow: bool | None) -> dict:
    t = _last_commit_time(RESEARCH_RESULTS)
    if t is None:
        return {"status": UNKNOWN, "detail": "could not read the last research/results commit"
                + (" (shallow clone)" if shallow else "")}
    hours = (now - t).total_seconds() / 3600
    st = BREACHED if hours > RESEARCH_MAX_HOURS else OK
    return {"status": st, "detail": f"last research result landed {hours:.0f}h ago "
                                    f"(bound {RESEARCH_MAX_HOURS}h)"}


def probe_manager(now: datetime) -> dict:
    # The register is the per-row store since the 2026-10-08 cutover; the
    # monolith was deleted then, so probing it alone read the deletion commit
    # and the alarm grew without bound. Newest commit over BOTH paths
    # (checklist_store.HISTORY_PATHS) so either layout counts as a write.
    from src.runtime import checklist_store as _ck  # noqa: PLC0415
    times = [t for t in (_last_commit_time(p) for p in _ck.HISTORY_PATHS) if t]
    t = max(times) if times else None
    if t is None:
        return {"status": UNKNOWN, "detail": "could not read the checklist's last commit"}
    hours = (now - t).total_seconds() / 3600
    st = BREACHED if hours > MANAGER_SILENT_HOURS else OK
    return {"status": st, "detail": f"checklist last written {hours:.0f}h ago "
                                    f"(bound {MANAGER_SILENT_HOURS}h — no daily review?)"}


def probe_desk_wake_post(now: datetime) -> dict:
    """The VM desk packet+wake producer (src/runtime/desk_packet_wake.py) rewrites its receipt on EVERY pass.
    Breached when the producer stopped (old ``computed_at``) or when it reports the trigger did not fire
    (``wake_missing`` / ``could_not_*``). A missing receipt is ``unknown``, never ``ok``."""
    p = REPO_ROOT / "runtime_logs" / "desk_wake_post_receipt.json"
    if not p.exists():
        return {"status": UNKNOWN, "detail": "desk_wake_post_receipt.json not found (the producer never ran on this host)"}
    try:
        doc = json.loads(p.read_text())
        t = datetime.fromisoformat(str(doc.get("computed_at")).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, AttributeError):
        return {"status": UNKNOWN, "detail": "desk_wake_post_receipt.json unreadable or has no computed_at"}
    hours = (now - t).total_seconds() / 3600
    state = doc.get("state")
    if hours > DESK_WAKE_POST_MAX_HOURS:
        return {"status": BREACHED, "detail": f"desk packet+wake producer last ran {hours:.1f}h ago (bound {DESK_WAKE_POST_MAX_HOURS}h)"}
    if state in ("wake_missing", "could_not_build", "could_not_commit", "could_not_post"):
        return {"status": BREACHED, "detail": f"desk wake trigger: {state} — {doc.get('reason') or doc.get('step') or ''}"}
    return {"status": OK, "detail": f"desk packet+wake producer ran {hours:.1f}h ago; state {state}"}


def probe_desk_row_missing(now: datetime) -> dict:
    """The newest desk packet on ``desk/decisions`` with no decision row after ``DESK_ROW_MISSING_MIN`` minutes.

    The producer receipt reads ``posted`` once the wake marker is up, whether or not a wake session ever ran,
    so it cannot see this. Reads the branch the VM rows watcher already fetches. Every branch it could not
    read is ``unknown`` with ``read_state: could_not_look`` in the detail, never ``ok`` (a count of 0 rows
    would be a lie): an unreadable ref, pointer or rows file, or an unparseable ``built_at``."""
    ptr_text = _git("show", f"{DESK_REF}:{DESK_POINTER}")
    rows_text = _git("show", f"{DESK_REF}:{DESK_DECISIONS}")
    if ptr_text is None or rows_text is None:
        gone = [n for n, t in (("pointer", ptr_text), ("decisions.jsonl", rows_text)) if t is None]
        return {"status": UNKNOWN, "read_state": "could_not_look",
                "detail": f"read_state could_not_look: {DESK_REF} {' and '.join(gone)} not readable on this host"}
    try:
        ptr = json.loads(ptr_text)
        pid = str(ptr["packet_id"])
        built = datetime.fromisoformat(str(ptr["built_at"]).replace("Z", "+00:00"))
        if built.tzinfo is None:
            built = built.replace(tzinfo=timezone.utc)
    except (ValueError, KeyError, TypeError):
        return {"status": UNKNOWN, "read_state": "could_not_look",
                "detail": "read_state could_not_look: latest_scan pointer has no parseable packet_id/built_at"}
    have = set()
    for line in rows_text.splitlines():
        try:
            have.add(json.loads(line).get("packet_id"))
        except (ValueError, AttributeError):
            continue
    age_min = (now - built).total_seconds() / 60
    if pid in have:
        return {"status": OK, "read_state": "read", "detail": f"newest desk packet {pid} has a decision row"}
    if age_min <= DESK_ROW_MISSING_MIN:
        return {"status": OK, "read_state": "read",
                "detail": f"newest desk packet {pid} is {age_min:.0f} min old, inside the {DESK_ROW_MISSING_MIN} min wake window"}
    return {"status": BREACHED, "read_state": "read",
            "detail": f"desk packet {pid} landed {age_min:.0f} min ago and has no decision row "
                      f"(bound {DESK_ROW_MISSING_MIN} min): the wake did not run or did not write"}


def _lr_thresholds(path: Path | None = None) -> tuple[float, float] | None:
    """(due_stale_minutes, rows_lag_minutes) from config/live_trade_review.yaml ``watch:``."""
    try:
        import yaml  # noqa: PLC0415
        w = (yaml.safe_load((path or LR_CONFIG).read_text()) or {}).get("watch") or {}
        return float(w["due_stale_minutes"]), float(w["rows_lag_minutes"])
    except Exception:  # noqa: BLE001  # allow-silent: caller reports unknown
        return None


def _lr_ts(v: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _lr_rows(text: str, refuses: Any = None) -> tuple[dict[str, datetime | None], int, set[str]]:
    """({review_id: reviewed_at}, unparseable-line count, ids ``refuses`` rejects) from a reviews.jsonl body."""
    out: dict[str, datetime | None] = {}
    refused: set[str] = set()
    bad = 0
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
            rid = str(d["review_id"])
            out[rid] = _lr_ts(d.get("reviewed_at"))
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        if refuses is not None and refuses(d):
            refused.add(rid)
    return out, bad, refused


def _lr_branch_text() -> str | None:
    """The rows branch's rows as one JSONL body: the legacy reviews.jsonl verbatim, then each per-row
    file ``comms/live_review/rows/<review_id>.json`` (LTR-ROWS-SWAP-TRUNCATION) as one line. None when
    the watcher's fetched ref is unreadable here."""
    legacy = _git("show", f"{LR_ROWS_REF}:{LR_REVIEWS_REL}")
    listing = _git("ls-tree", "--name-only", LR_ROWS_REF, "--", "comms/live_review/rows/")
    if legacy is None and not listing:
        return None
    lines = [legacy.rstrip("\n")] if legacy else []
    for path in (listing or "").splitlines():
        body = _git("show", f"{LR_ROWS_REF}:{path}") if path.endswith(".json") else None
        try:
            lines.append(json.dumps(json.loads(body or ""), separators=(",", ":")))
        except ValueError:
            lines.append(f"<unparseable {path}>")
    return "\n".join(lines) + "\n"


def _lr_refuses() -> Any:
    """row -> bool: does check_live_review_records refuse this row? The live_review_rows_mirror
    SKIPS such a row for good, so it can never reach main and is not a stall. None if the
    checker cannot be loaded (the caller then answers unknown, never ok)."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
        try:
            import check_live_review_records as rules  # noqa: PLC0415
            schema = json.loads(rules.SCHEMA.read_text())
        finally:
            sys.path.pop(0)
        return lambda row: bool(rules.row_problems(row, "reviews", schema)) if isinstance(row, dict) else True
    except Exception:  # noqa: BLE001  # allow-silent: caller reports unknown
        return None


def _lr_due_clause(now: datetime, mins: float, due_doc: dict | None, seen_path: Path,
                   persist: bool) -> tuple[str, str]:
    """(status, detail): a due package unreviewed past ``mins``. ``due_doc`` None -> read the route's payload."""
    if due_doc is None:
        try:
            from src.runtime.live_review_due import live_review_due  # noqa: PLC0415
            due_doc = live_review_due()
        except Exception as exc:  # noqa: BLE001  # allow-silent: -> unknown
            return UNKNOWN, f"due route unreadable ({type(exc).__name__})"
    if due_doc.get("read_state") != "looked":
        # could_not_look: due_count is null, which is NOT "nothing due".
        return UNKNOWN, f"due route could_not_look ({due_doc.get('reason')})"
    prior = _read_json(seen_path).get("seen") or {}
    seen: dict[str, str] = {}
    ages: list[tuple[float, str]] = []
    for d in due_doc.get("due") or []:
        for ev in d.get("events") or []:
            key = f"{d.get('order_package_id')}|{ev.get('event')}|{ev.get('level')}"
            first = _lr_ts(prior.get(key)) or now
            seen[key] = first.isoformat()
            ages.append(((now - first).total_seconds() / 60, f"{d.get('leg')}/{d.get('account_id')} {ev.get('event')}"))
    if persist:
        try:
            _write_json(seen_path, {"at": now.isoformat(), "seen": seen})
        except OSError:
            pass  # the clock restarts next pass; the probe still answers from this one
    old = sorted((a for a in ages if a[0] > mins), reverse=True)
    if old:
        return BREACHED, (f"{len(old)} due event(s) unreviewed > {mins:.0f}m; oldest {old[0][0]:.0f}m "
                          f"({old[0][1]})")
    return OK, f"{due_doc.get('due_count')} due, none unreviewed > {mins:.0f}m"


def _lr_rows_clause(now: datetime, mins: float, branch_text: str | None, main_text: str | None,
                    refuses: Any = None) -> tuple[str, str]:
    """(status, detail): rows on live-review/rows that main lacks for > ``mins`` since their reviewed_at.
    A row ``refuses`` rejects is excluded (the mirror skips it permanently) and counted in the detail."""
    if branch_text is None:
        return UNKNOWN, f"{LR_ROWS_REF} not readable on this host (watcher never fetched it?)"
    if refuses is None:
        return UNKNOWN, "scripts/ci/check_live_review_records not importable: cannot tell a stuck row from a refused one"
    branch, bad, refused = _lr_rows(branch_text, refuses)
    main, _, _ = _lr_rows(main_text or "")
    ahead = {rid: t for rid, t in branch.items() if rid not in main and rid not in refused}
    excl = sum(1 for rid in refused if rid not in main)
    note = (f" ({excl} schema-refused row excluded)" if excl == 1 else f" ({excl} schema-refused rows excluded)") if excl else ""
    if not ahead:
        return OK, f"main has all {len(branch) - excl} mirrorable rows-branch rows" + note + (f" ({bad} unparseable line(s) on branch)" if bad else "")
    stamped = {rid: t for rid, t in ahead.items() if t is not None}
    if not stamped:
        return UNKNOWN, f"{len(ahead)} rows-branch row(s) missing from main, none with a readable reviewed_at" + note
    rid, t = min(stamped.items(), key=lambda kv: kv[1])
    lag = (now - t).total_seconds() / 60
    if lag > mins:
        return BREACHED, (f"{len(ahead)} review row(s) on live-review/rows not on main; oldest {rid} "
                          f"reviewed {lag:.0f}m ago (bound {mins:.0f}m) — the rows mirror is stuck" + note)
    return OK, f"{len(ahead)} row(s) ahead of main, oldest {lag:.0f}m (bound {mins:.0f}m)" + note


def probe_live_review_due_stale(now: datetime, *, due_doc: dict | None = None,
                                branch_text: str | None = None, main_text: str | None = None,
                                seen_path: Path | None = None, persist: bool = True,
                                thresholds: tuple[float, float] | None = None,
                                refuses: Any = None) -> dict:
    """Live trade review has gone quiet: (1) a due package stays unreviewed past
    ``watch.due_stale_minutes``, or (2) reviews exist on ``live-review/rows`` that never
    reach main's reviews.jsonl past ``watch.rows_lag_minutes`` (the 2026-10-26 mirror stall:
    one schema-invalid row blocked every later row, nothing alerted).

    Either clause breaching breaches the probe; a clause that could not look is ``unknown``
    (never ``ok``) unless the other already breached. Inputs are injectable for tests; by
    default clause 1 calls ``live_review_due()`` (the route's own function) and clause 2
    reads the VM watcher's fetched ref (legacy reviews.jsonl + per-row files) against the working
    tree's reviews.jsonl."""
    th = thresholds or _lr_thresholds()
    if th is None:
        return {"status": UNKNOWN, "detail": "config/live_trade_review.yaml watch: thresholds unreadable"}
    if branch_text is None:
        branch_text = _lr_branch_text()
    if main_text is None:
        try:
            main_text = (REPO_ROOT / LR_REVIEWS_REL).read_text()
        except FileNotFoundError:
            main_text = ""   # no review has ever landed: a legitimate empty, not a blind spot
        except OSError:
            main_text = None
    if main_text is None:
        rows = (UNKNOWN, f"{LR_REVIEWS_REL} unreadable")
    else:
        rows = _lr_rows_clause(now, th[1], branch_text, main_text,
                               refuses if refuses is not None else _lr_refuses())
    due = _lr_due_clause(now, th[0], due_doc, seen_path or LR_DUE_SEEN, persist)
    parts = [f"due: {due[1]}", f"rows: {rows[1]}"]
    sts = {due[0], rows[0]}
    st = BREACHED if BREACHED in sts else UNKNOWN if UNKNOWN in sts else OK
    return {"status": st, "detail": "; ".join(parts)}


def _retired_accounts() -> set:
    """Accounts marked ``retired: true`` in config/accounts.yaml (fail-open: unreadable -> none)."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from src.config.accounts_loader import load_accounts_dict
        from src.prop.prop_identity import is_retired_account
        return {a for a, c in (load_accounts_dict() or {}).items() if is_retired_account(c)}
    except Exception:  # noqa: BLE001  # allow-silent: an unreadable config must not hide a live account's trip
        return set()


def _drop_retired(probes: dict) -> dict:
    """Per-account probes (``<kind>_<account>``) minus those of retired accounts."""
    ret = _retired_accounts()
    return {k: v for k, v in probes.items() if not any(k.endswith("_" + a) for a in ret)}


PROP_BACKOFF_MAX_HOURS = 2   # the red-flag ping fires once; a feed still flagged 2h later re-pages


def _read_feed_backoff(path: Path) -> dict:
    """The key=value backoff state scripts/ops/prop_feed_tick.sh writes."""
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def probe_prop_feed(now: datetime) -> dict:
    """A prop feed that keeps failing (red-flagged: 3+ consecutive failures, a
    feasibility stop, or the relogin ceiling) is retrying on a capped backoff
    and not refreshing its account's saved session, so that account's executor
    runs on a session nobody renews; the silence probe cannot see it (it keys
    on fills). Since NO-HALT (2026-10-09) the feed never stops, so there is no
    `tripped` marker to read: this reads each ``feed/backoff`` state file.
    No base dir, or a state file that cannot be read, is UNKNOWN (we could not
    look), never OK; a backoff below the red-flag threshold is OK (retrying
    normally)."""
    base = Path(os.environ.get("PROP_BROWSER_BASE") or Path.home() / ".cache" / "metis-prop-browser")
    if not base.is_dir():
        return {"status": UNKNOWN, "detail": f"no prop browser base dir ({base.name})"}
    states = [*base.glob("accounts/*/feed/backoff"), base / "feed" / "backoff"]
    flagged, unreadable = [], []
    for f in states:
        name = "breakout_1" if f.parent.parent == base else f.parent.parent.name
        if not f.exists():
            continue
        if name in _retired_accounts():
            continue  # a retired account's stale state must never page (OPS-DECISIONS-1009)
        try:
            st = _read_feed_backoff(f)
        except OSError:
            unreadable.append(name)
            continue
        if st.get("flagged") != "1":
            continue
        try:
            at = datetime.strptime(st.get("flagged_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                at = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
            except OSError:
                unreadable.append(name)
                continue
        age = (now - at).total_seconds() / 3600
        flagged.append((age, f"{name} ({age:.0f}h, {st.get('consecutive_failures', '?')} failure(s), "
                             f"next try {st.get('next_attempt_at_utc', '?')}: {st.get('reason', '')[:90]})"))
    old = [d for a, d in flagged if a >= PROP_BACKOFF_MAX_HOURS]
    if old:
        return {"status": BREACHED,
                "detail": "feed failing, retrying on backoff: " + "; ".join(old)
                          + " — fix the cause; to retry sooner: breakout-login-check apply: reset-feed"}
    if unreadable:
        return {"status": UNKNOWN, "detail": "could not read the backoff state of: " + ", ".join(unreadable)}
    return {"status": OK,
            "detail": f"{len(flagged)} prop feed(s) red-flagged under {PROP_BACKOFF_MAX_HOURS}h" if flagged
            else "no prop feed red-flagged"}


REPORT_MAX_AGE_HOURS = 26     # daily 05:30Z + grace
REPORT_DUE_UTC = (5, 50)      # today's report must exist by 05:50Z (review at 05:52Z)
#: A report nobody can read in one sitting is the 737 KB brief again. BRIEF-FIX
#: caps the brief at 16 KB; the report adds the attention summary on top.
REPORT_MAX_BYTES = 64_000


def probe_report(now: datetime) -> dict:
    """The scheduled work report (scripts/ops/work_report.py) exists, is fresh,
    and has no errored section. An absent or unreadable report is BREACHED:
    the report is an expected signal, and its absence is the finding."""
    from scripts.ops import work_report  # noqa: PLC0415
    st, rep = work_report.read_latest()
    if st != "read" or rep is None:
        return {"status": BREACHED, "detail": f"latest work report {st}"}
    try:
        gen = datetime.fromisoformat(rep["generated_at"])
    except (KeyError, ValueError):
        return {"status": BREACHED, "detail": f"{rep.get('report_id')} has no readable generated_at"}
    age_h = (now - gen).total_seconds() / 3600
    due_today = now.replace(hour=REPORT_DUE_UTC[0], minute=REPORT_DUE_UTC[1], second=0,
                            microsecond=0)
    missed_today = now >= due_today and gen < due_today - timedelta(minutes=30)
    errs = rep.get("errored_sections") or []
    if age_h > REPORT_MAX_AGE_HOURS or missed_today:
        return {"status": BREACHED, "detail": f"latest report {rep['report_id']} is {age_h:.0f}h old "
                                              f"— today's 05:30Z report was not produced"}
    if errs:
        return {"status": BREACHED, "detail": f"{rep['report_id']} has errored section(s): "
                                              f"{', '.join(errs)}"}
    size = rep.get("bytes")
    if isinstance(size, int) and size > REPORT_MAX_BYTES:
        return {"status": BREACHED, "detail": f"{rep['report_id']} is {size // 1000} KB "
                                              f"(> {REPORT_MAX_BYTES // 1000} KB — too long to be read)"}
    return {"status": OK, "detail": f"{rep['report_id']} ({age_h:.0f}h old, all sections built)"}


def _row_line_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map row id -> (first, last) 1-based line of its object in the items array.
    Relies on the checklist's indent=2 layout: rows open with ``    {``."""
    out: dict[str, tuple[int, int]] = {}
    start = None
    rid = None
    for n, line in enumerate(lines, 1):
        if line.rstrip() == "    {":
            start, rid = n, None
        elif start is not None and rid is None and line.startswith('      "id": "'):
            rid = line.split('"id": "', 1)[1].split('"', 1)[0]
        elif start is not None and line.rstrip() in ("    }", "    },"):
            if rid:
                out[rid] = (start, n)
            start = None
    return out


def probe_inflight(now: datetime, shallow: bool | None) -> dict:
    """In_flight rows whose checklist text has not changed in INFLIGHT_STALE_DAYS.

    Activity = the newest commit touching any line of the row (``git blame``).
    ⚠️ On a shallow clone blame attributes old lines to the boundary commit,
    which makes a stale row look FRESH — so a shallow clone reads ``unknown``.
    """
    try:
        from src.runtime import checklist_store as _ck  # noqa: PLC0415
        d = _ck.load_path(CHECKLIST)
        text_lines = ([] if _ck.seeded(CHECKLIST)
                      else CHECKLIST.read_text(encoding="utf-8").splitlines())
    except (OSError, ValueError) as exc:
        return {"status": UNKNOWN, "detail": f"checklist unreadable: {exc}", "rows": []}
    inflight = [r for r in d.get("items", []) if r.get("state") == "in_flight"]
    if shallow:
        return {"status": UNKNOWN, "detail": f"{len(inflight)} in_flight rows; clone is "
                "shallow so row age cannot be read", "rows": []}
    if not text_lines:  # per-row store: a row's activity is the last commit on ITS file
        stale = []
        for r in inflight:
            out = _git("log", "-1", "--format=%ct", "--",
                       f"docs/claude/work/checklist/{r.get('id')}.json")
            if not out or not out.strip().isdigit():
                continue
            age = (now - datetime.fromtimestamp(int(out.strip()), tz=timezone.utc)).total_seconds() / 86400
            if age >= INFLIGHT_STALE_DAYS:
                stale.append({"id": r.get("id"), "days": round(age, 1), "lane": r.get("lane")})
        stale.sort(key=lambda x: -x["days"])
        return {"status": BREACHED if stale else OK, "rows": stale,
                "detail": f"{len(stale)} of {len(inflight)} in_flight rows untouched "
                          f">= {INFLIGHT_STALE_DAYS}d (per-row history)"
                          + (": " + ", ".join(f"{s['id']} {s['days']:.0f}d" for s in stale[:6])
                             if stale else "")}
    blame = _git("blame", "--line-porcelain", "--", str(CHECKLIST.relative_to(REPO_ROOT)))
    if blame is None:
        return {"status": UNKNOWN, "detail": "git blame failed", "rows": []}
    times: list[int] = []
    for line in blame.splitlines():
        if line.startswith("committer-time "):
            times.append(int(line.split()[1]))
    ranges = _row_line_ranges(text_lines)
    stale = []
    for r in inflight:
        rng = ranges.get(r.get("id"))
        if not rng or rng[1] > len(times):
            continue
        last = datetime.fromtimestamp(max(times[rng[0] - 1: rng[1]]), tz=timezone.utc)
        age = (now - last).total_seconds() / 86400
        if age >= INFLIGHT_STALE_DAYS:
            stale.append({"id": r.get("id"), "days": round(age, 1), "lane": r.get("lane")})
    stale.sort(key=lambda x: -x["days"])
    st = BREACHED if stale else OK
    return {"status": st, "rows": stale,
            "detail": f"{len(stale)} of {len(inflight)} in_flight rows untouched "
                      f">= {INFLIGHT_STALE_DAYS}d"
                      + (": " + ", ".join(f"{s['id']} {s['days']:.0f}d" for s in stale[:6])
                         if stale else "")}


def read_blocker_watch() -> tuple[str, list[dict]]:
    """BLOCKER-WATCH findings (``scripts/ops/blocker_watch.py``) as
    ``(read_state, findings)``. ``unreadable`` = we could not look; it never
    reads as 'no findings' and never clears a seen key."""
    try:
        from scripts.ops import blocker_watch  # noqa: PLC0415
        rep = blocker_watch.build(_now())
    except Exception:  # noqa: BLE001 — unreadable is a state, not a crash
        return "unreadable", []
    if not rep.get("readable"):
        return "unreadable", []
    return "read", list(rep["findings"])


# ── the pass ─────────────────────────────────────────────────────────────────
def build(now: datetime | None = None, persist_seen: bool = True) -> dict:
    now = now or _now()
    today = now.date()
    res = pipeline.load(REPO_ROOT / pipeline.STORE)
    items = list(res.items.values())
    shallow = _is_shallow()
    soak_read, soaks = read_soak_states()
    nr_read, nr_rows = read_needs_review()
    bw_read, bw_rows = read_blocker_watch()
    return {
        "blocker_read": bw_read, "blocker_findings": bw_rows,
        "needs_review_read": nr_read, "needs_review": nr_rows,
        "now": now, "today": today, "pipeline_readable": res.healthy,
        "pipeline_unreadable": len(res.unreadable),
        "stats": pipeline.stats(res, today),
        "ranked": _ranked(res, items, today),
        "ask_operator": open_ask_operator(items),
        "soak_read": soak_read, "soaks": soaks,
        "probes": {
            "soak_grade": probe_soak_grade(now),
            "research": probe_research(now, shallow),
            "inflight": probe_inflight(now, shallow),
            "manager": probe_manager(now),
            "report": probe_report(now),
            "desk_wake_post": probe_desk_wake_post(now),
            "desk_row_missing": probe_desk_row_missing(now),
            "live_review_due_stale": probe_live_review_due_stale(now, persist=persist_seen),
            # TRAIL-PAUSE-PULSE: prop_trail_paused_<account>, one per executor
            # account with a state dir on this host; see prop_trail_watch.py.
            # a retired account (breakout_1, operator 2026-10-09: "shouldn't be
            # coming up again") gets no probe at all -- not even "unknown".
            **_drop_retired(prop_trail_watch.all_probes(now)),
            # PROP-SILENCE-ALERTS: idle-fill (warn 14 d / urgent 21 d) per prop
            # account + breakout_2's phone heartbeat. Each carries `level` and
            # `priority`; see scripts/ops/prop_silence.py.
            **_drop_retired(prop_silence.all_probes(now)),
            "prop_feed": probe_prop_feed(now),
        },
    }


PROBE_LABEL = {
    "soak_grade": "R5 weekly soak grade missing",
    "research": "research results not landing",
    "inflight": "in_flight rows gone quiet",
    "manager": "manager's register not written",
    "report": "scheduled work report missing or broken",
    "desk_wake_post": "the desk packet+wake trigger stopped (producer silent, wake missing, or packet build/commit/post failing)",
    "desk_row_missing": "a desk packet landed more than 15 min ago and no desk decision row followed (the wake did not run or did not write)",
    "live_review_due_stale": "live trade review gone quiet (a due package unreviewed past the bound, or reviews on live-review/rows not reaching main)",
    **prop_trail_watch.LABELS,
    **prop_silence.LABELS,
    "prop_feed": "a prop account feed keeps failing (red-flagged; retrying on a capped backoff)",
}


def render_digest(v: dict) -> str:
    s = v["stats"]
    rep = v["probes"].get("report", {})
    L = [f"📋 Daily summary {v['today']}"
         + (f" — {rep['detail'].split(' ')[0]}" if rep.get("status") == OK else "")]
    if not v["pipeline_readable"]:
        L.append(f"⚠️ {v['pipeline_unreadable']} pipeline record(s) UNREADABLE — counts are a floor.")
    ao_due = [i for i in v["ask_operator"] if pipeline.is_due(i, v["today"])]
    L.append(f"Due {s['due']} · unrouted {s['unrouted']} · needs you {len(ao_due)} "
             f"(open ask_operator {len(v['ask_operator'])})")
    if s["unrouted_alarm"]["breached"]:
        L.append("🚨 routing alarm: " + "; ".join(s["unrouted_alarm"]["breached"]))
    if v["soak_read"] == "read":
        by: dict[str, int] = {}
        for r in v["soaks"]:
            by[str(r.get("state"))] = by.get(str(r.get("state")), 0) + 1
        L.append("Soaks: " + (" · ".join(f"{k} {n}" for k, n in sorted(by.items())) or "none"))
    else:
        L.append(f"Soaks: state source {v['soak_read'].upper()} (not zero — not measured)")
    nr_line = _needs_review_line(v)
    if nr_line:
        L.append(nr_line)
    bad = [k for k, p in v["probes"].items() if p["status"] != OK]
    for k in bad:
        p = v["probes"][k]
        L.append(f"{'🔕' if p['status'] == BREACHED else '❔'} {PROBE_LABEL[k]}: {p['detail']}")
    L.append("")
    L.append(f"Top {min(TOP_N, len(v['ranked']))} of {len(v['ranked'])} due:")
    for i in v["ranked"][:TOP_N]:
        tag = "❓ASK" if i.get("next_action") == "ask_operator" else i.get("state")
        L.append(f"• [{tag}] {i.get('id')}: {_short(i.get('what'), 120)}")
    L.append("Reviewed report: /api/bot/work/report · live: /api/bot/work/brief")
    return "\n".join(L)


def plan_messages(v: dict, state: dict, digest_now: bool = False) -> tuple[list[tuple[str, str]], dict]:
    """Return ``([(priority, body)], new_state)``. Pure — no I/O."""
    now: datetime = v["now"]
    today_s = v["today"].isoformat()
    new = dict(state)
    msgs: list[tuple[str, str]] = []
    first_run = "seen_ask_operator" not in state

    # (b1) new ask_operator items — edge-triggered. The first run SEEDS, but
    # never silently (manager, 2026-10-04: seeding an actionable set without a
    # word is the "things exist and nobody is told" pattern) — it sends ONE
    # count line instead of one line per item.
    seen = set(state.get("seen_ask_operator", []))
    cur = {i["id"]: i for i in v["ask_operator"]}
    fresh = [cur[k] for k in sorted(cur) if k not in seen]
    if fresh and not first_run:
        L = [f"❓ {len(fresh)} new decision(s) for you (ask_operator):"]
        for i in fresh[:6]:
            L.append(f"• {i['id']}: {_short(i.get('what'), 160)}")
        if len(fresh) > 6:
            L.append(f"…and {len(fresh) - 6} more — see the daily digest.")
        msgs.append(("high", "\n".join(L)))
    # ORDER-INDEPENDENT (manager, 2026-10-04 18:16Z): the seed line keys on its
    # OWN marker, not on whether the set was already seeded — so it fires once
    # even if an earlier pass (shipped without it) seeded the set silently.
    if "seed_ask_sent_at" not in state:
        n_due = sum(1 for i in cur.values() if pipeline.is_due(i, v["today"]))
        msgs.append(("high", f"❓ ask_operator at deploy: {len(cur)} open ({n_due} due) — "
                             f"see the report (GET /api/bot/work/report)"))
        new["seed_ask_sent_at"] = now.isoformat()
    new["seen_ask_operator"] = sorted(seen | set(cur))

    # (b2) soak transitions into passed / mechanical_fail.
    if v["soak_read"] == "read":
        prior = state.get("soak_states", {})
        cur_s = {_soak_key(r): str(r.get("state")) for r in v["soaks"]}
        moved = [r for r in v["soaks"]
                 if str(r.get("state")) in ALERT_SOAK_STATES
                 and prior.get(_soak_key(r)) != str(r.get("state"))]
        if moved and "soak_states" in state:
            L = [f"🧪 {len(moved)} soak(s) changed state:"]
            for r in moved[:8]:
                L.append(f"• {_soak_key(r)} → {r.get('state')} {_short(r.get('reason'), 100)}")
            pri = "high" if any(str(r.get("state")) == "mechanical_fail" for r in moved) else "normal"
            msgs.append((pri, "\n".join(L)))
        if "seed_soaks_sent_at" not in state:
            # Seed line, same rule as ask_operator above: one count line, keyed
            # on its own marker — and only once the soak source was READ, so an
            # absent/unreadable first pass does not burn it.
            n = {k: sum(1 for s in cur_s.values() if s == k) for k in ALERT_SOAK_STATES}
            msgs.append(("high" if n["mechanical_fail"] else "normal",
                         f"🧪 Soaks at deploy: {n['passed']} passed · "
                         f"{n['mechanical_fail']} mechanical_fail (see report)"))
            new["seed_soaks_sent_at"] = now.isoformat()
        new["soak_states"] = cur_s

    # (b3) research units newly needing a read — edge-triggered, same seeding rule
    # as (b1): the first pass sends ONE count line, never silently, never per item.
    if v.get("needs_review_read") == "read":
        cur_nr = {r["id"]: r for r in v.get("needs_review", [])}
        seen_nr = set(state.get("seen_needs_review", []))
        fresh_nr = [cur_nr[k] for k in sorted(cur_nr) if k not in seen_nr]
        if fresh_nr and "seen_needs_review" in state:
            L = [f"🔎 {len(fresh_nr)} research unit(s) newly need a read (needs_review):"]
            for r in fresh_nr[:6]:
                L.append(f"• {r['id']}: {_short(r.get('reason'), 140)}")
            if len(fresh_nr) > 6:
                L.append(f"…and {len(fresh_nr) - 6} more — see the daily digest.")
            msgs.append(("normal", "\n".join(L)))
        if "seed_needs_review_sent_at" not in state:
            msgs.append(("normal", f"🔎 needs_review at deploy: {len(cur_nr)} research unit(s) flagged "
                                   f"(listed in the daily digest)"))
            new["seed_needs_review_sent_at"] = now.isoformat()
        new["seen_needs_review"] = sorted(cur_nr)

    # (b4) BLOCKER-WATCH: a blocked row whose blocker is gone, a queued unit that is
    # not being dispatched, an operator wait > 7 d, a landed_unproven past due.
    # ONE alert per NEW finding, keyed row+kind (+edge); a key that is still
    # present is never re-sent. A key that disappears is forgotten, so a finding
    # that recurs after being fixed alerts again. Same seeding rule as (b1)/(b3):
    # the first pass sends ONE count line, never silently and never per item.
    if v.get("blocker_read") == "read":
        cur_bw = {f["key"]: f for f in v.get("blocker_findings", [])}
        seen_bw = set(state.get("seen_blocker_findings", []))
        fresh_bw = [cur_bw[k] for k in sorted(cur_bw) if k not in seen_bw]
        if fresh_bw and "seen_blocker_findings" in state:
            L = [f"🧱 {len(fresh_bw)} new blocker-watch finding(s) — act this turn "
                 f"(unblock, re-queue, dispatch, or drop with a reason):"]
            for f in fresh_bw[:6]:
                L.append(f"• {f['kind']} {f['id']}: {_short(f.get('evidence'), 150)}")
            if len(fresh_bw) > 6:
                L.append(f"…and {len(fresh_bw) - 6} more — python3 scripts/ops/blocker_watch.py")
            msgs.append(("high" if any(f["kind"] == "STALE_BLOCK" for f in fresh_bw) else "normal",
                         "\n".join(L)))
        if "seed_blocker_watch_sent_at" not in state:
            by: dict[str, int] = {}
            for f in cur_bw.values():
                by[f["kind"]] = by.get(f["kind"], 0) + 1
            msgs.append(("normal", "🧱 blocker-watch at deploy: " +
                         (" · ".join(f"{k} {n}" for k, n in sorted(by.items())) or "no findings") +
                         " (listed in the daily brief; only NEW findings alert from here)"))
            new["seed_blocker_watch_sent_at"] = now.isoformat()
        new["seen_blocker_findings"] = sorted(cur_bw)

    # (c) silence alarms — send on breach, re-send every REALERT_HOURS, one clear.
    alarms = dict(state.get("alarms", {}))
    for k, p in v["probes"].items():
        a = alarms.get(k, {})
        if p["status"] == BREACHED:
            last = a.get("last_sent")
            level = p.get("level")
            # A warn -> urgent step is a NEW fact: send it now, not in 24 h.
            escalated = bool(a.get("breached")) and level is not None and a.get("level") != level
            due = (last is None or escalated or
                   now - datetime.fromisoformat(last) >= timedelta(hours=REALERT_HOURS))
            if due:
                msgs.append((p.get("priority", "high"),
                             f"🔕 Expected signal missing — {PROBE_LABEL[k]}: {p['detail']}"))
                a = {"status": BREACHED, "breached": True, "last_sent": now.isoformat(),
                     "level": level}
            else:
                a = {**a, "status": BREACHED, "breached": True, "level": level}
        elif p["status"] == OK:
            if a.get("breached"):
                msgs.append(("normal", f"✅ Cleared — {PROBE_LABEL[k]}: {p['detail']}"))
            a = {"status": OK}
        else:
            # ⚠️ unknown keeps `breached` — "we could not look" never clears an alarm.
            a = {**a, "status": UNKNOWN}
        alarms[k] = a
    new["alarms"] = alarms

    # (a) the daily digest.
    if digest_now or (now.hour >= DIGEST_HOUR_UTC and state.get("last_digest_date") != today_s):
        msgs.insert(0, ("normal", render_digest(v)))
        new["last_digest_date"] = today_s
    return msgs, new


DIGEST_LOG_NAME = "digest_log.jsonl"


def compose_block(v: dict, msgs: list[tuple[str, str]]) -> tuple[str, str, list[str]]:
    """Turn planned messages into ONE block for the hourly digest.

    Returns ``(block, priority, new_items)``. NEW actionable items first and
    marked; the daily summary after them; and when nothing is new, ONE line —
    so a new actionable thing is unmissable and the steady state is quiet."""
    summary = [b for _, b in msgs if b.startswith("📋")]
    new = [b for _, b in msgs if not b.startswith("📋")]
    pris = {p for p, b in msgs if not b.startswith("📋")}
    pri = "urgent" if "urgent" in pris else "high" if "high" in pris else "normal"
    L: list[str] = []
    if new:
        L.append(f"🆕 NEW since last digest ({len(new)}):")
        L += new
    else:
        breached = sum(1 for p in v["probes"].values() if p["status"] == BREACHED)
        L.append(f"🟢 No new actionable items · open: {len(v['ask_operator'])} ask_operator, "
                 f"{v['stats']['due']} due, {breached} alarm(s) still breached "
                 f"(GET /api/bot/work/report)")
    if summary:
        L += ["", *summary]
    return "\n".join(L), pri, new


def prepare(dry_run: bool = False, digest_now: bool = False) -> dict:
    """Build this hour's attention block. Writes nothing; ``commit`` does,
    and only after the digest carrying the block was enqueued."""
    v = build(persist_seen=not dry_run)
    state = _read_json(STATE)
    msgs, new_state = plan_messages(v, state, digest_now=digest_now)
    block, pri, new = compose_block(v, msgs)
    receipt = {"at": v["now"].isoformat(), "new_items": len(new),
               "summary": any(b.startswith("📋") for _, b in msgs),
               "probes": {k: p["status"] for k, p in v["probes"].items()},
               "soak_read": v["soak_read"], "due": v["stats"]["due"],
               "unrouted": v["stats"]["unrouted"],
               "ask_operator_open": len(v["ask_operator"]),
               "pipeline_readable": v["pipeline_readable"]}
    log_entry = {"at": v["now"].isoformat(), "priority": pri, "new": new,
                 "summary": receipt["summary"],
                 "counts": {"due": v["stats"]["due"], "unrouted": v["stats"]["unrouted"],
                            "ask_operator_open": len(v["ask_operator"]),
                            "alarms_breached": sorted(k for k, p in v["probes"].items()
                                                      if p["status"] == BREACHED)}}
    return {"block": block, "priority": pri, "state": new_state,
            "receipt": receipt, "log": log_entry, "dry_run": dry_run,
            # TELEGRAM-CHANNELS: the planned messages, so the manager update can
            # route each to its section (only ❓ asks are "Needs you").
            "msgs": [b for _, b in msgs]}


def commit(prep: dict, outcome: str) -> None:
    """Advance state, append the machine-readable digest log (what the manager
    reads, since a session cannot receive Telegram), stamp the receipt."""
    if prep["dry_run"] or outcome != "sent":
        _write_json(RECEIPT, {**prep["receipt"], "outcome": "dry_run" if prep["dry_run"] else outcome})
        return
    _write_json(STATE, prep["state"])
    from scripts.ops import work_report  # noqa: PLC0415
    try:
        work_report.append_digest_log(prep["log"])
    except OSError as exc:
        print(f"attention-watch: WARNING could not append digest log: {exc}")
    _write_json(RECEIPT, {**prep["receipt"], "outcome": outcome})


def run(dry_run: bool = False, digest_now: bool = False) -> int:
    """Standalone pass (manual / debugging). The scheduled path is
    ``work_digest_now.run``, which prepends the block to its hourly digest."""
    prep = prepare(dry_run=dry_run, digest_now=digest_now)
    print(prep["block"])
    if dry_run:
        commit(prep, "dry_run")
        return 0
    from send_ping import enqueue  # noqa: PLC0415
    try:
        enqueue(prep["block"], priority=prep["priority"], target="claude")
    except (OSError, ValueError) as exc:
        commit(prep, "enqueue_failed")
        print(f"attention-watch: enqueue failed: {exc}")
        return 1
    commit(prep, "sent")
    return 0


# ── self-test ────────────────────────────────────────────────────────────────
def _self_test() -> int:
    ok = True

    def check(label: str, passed: bool, detail: Any = "") -> None:
        nonlocal ok
        ok &= bool(passed)
        print(f"  {'PASS' if passed else 'FAIL'} {label}" + ("" if passed else f" — {detail}"))

    now = datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc)
    today = now.date()
    ao = {"id": "PI-20261001-x-0001", "state": "queued", "next_action": "ask_operator",
          "what": "decide X", "due_when": {"kind": "date", "due_date": "2026-10-01"}}
    old = {"id": "PI-20260920-x-0001", "state": "queued", "next_action": "dispatch_lane",
           "what": "old", "due_when": {"kind": "date", "due_date": "2026-09-21"}}
    routed = {"id": "PI-20260901-x-0001", "state": "routed", "next_action": "dispatch_lane",
              "what": "r", "due_when": {"kind": "date", "due_date": "2026-09-02"}}
    ranked = rank_attention([routed, old, ao], today)
    check("ask_operator ranks first, routed last",
          [r["id"] for r in ranked] == [ao["id"], old["id"], routed["id"]], ranked)

    def view(**kw: Any) -> dict:
        base = {"now": now, "today": today, "pipeline_readable": True, "pipeline_unreadable": 0,
                "stats": {"due": 3, "unrouted": 2,
                          "unrouted_alarm": {"breached": []}},
                "ranked": ranked, "ask_operator": [ao], "soak_read": "absent", "soaks": [],
                "probes": {k: {"status": OK, "detail": "fine"} for k in PROBE_LABEL}}
        base.update(kw)
        return base

    msgs, st = plan_messages(view(), {})
    check("first run sends the digest plus ONE ask_operator seed line, not one per item",
          len(msgs) == 2 and msgs[0][1].startswith("📋")
          and msgs[1][1].startswith("❓ ask_operator at deploy: 1 open"), msgs)
    check("absent soak source is said, never rendered as zero",
          "ABSENT" in msgs[0][1], msgs[0][1])
    msgs2, st2 = plan_messages(view(), st)
    check("second pass same day is quiet", msgs2 == [], msgs2)
    ao2 = {**ao, "id": "PI-20261004-x-0002"}
    msgs3, st3 = plan_messages(view(ask_operator=[ao, ao2]), st2)
    check("a NEW ask_operator item alerts once, high",
          len(msgs3) == 1 and msgs3[0][0] == "high" and ao2["id"] in msgs3[0][1], msgs3)
    probes = {k: {"status": OK, "detail": "fine"} for k in PROBE_LABEL}
    probes["soak_grade"] = {"status": BREACHED, "detail": "9d old"}
    msgs4, st4 = plan_messages(view(probes=probes, ask_operator=[ao, ao2]), st3)
    check("a breached silence probe alerts", any("Expected signal missing" in b for _, b in msgs4), msgs4)
    msgs5, st5 = plan_messages(view(probes=probes, ask_operator=[ao, ao2]), st4)
    check("…and does not re-alert inside REALERT_HOURS", msgs5 == [], msgs5)
    probes_u = dict(probes, soak_grade={"status": UNKNOWN, "detail": "?"})
    _, st6 = plan_messages(view(probes=probes_u, ask_operator=[ao, ao2]), st5)
    msgs7, _ = plan_messages(view(ask_operator=[ao, ao2]), st6)
    check("unknown does not silently clear a breach; the later OK sends one clear",
          len(msgs7) == 1 and msgs7[0][1].startswith("✅"), msgs7)
    s1 = {"leg": "a", "account": "bybit_1", "state": "awaiting_first_trade"}
    d1 = {"leg": "b", "account": "bybit_1", "state": "mechanical_fail"}
    seed, _ = plan_messages(view(soak_read="read", soaks=[s1, d1]), st2)
    check("first soak read sends ONE seed line with the counts",
          [b for _, b in seed] == ["🧪 Soaks at deploy: 0 passed · 1 mechanical_fail (see report)"], seed)
    legacy = {k: v for k, v in st2.items() if not k.startswith("seed_")}
    legacy["soak_states"] = {"bybit_1:b": "mechanical_fail"}
    late, late_st = plan_messages(view(soak_read="read", soaks=[d1]), legacy)
    check("order-independent: a state seeded WITHOUT markers still gets both seed lines once",
          sum(1 for _, b in late if "at deploy" in b) == 2, late)
    again, _ = plan_messages(view(soak_read="read", soaks=[d1]), late_st)
    check("…and never again once the markers are set",
          not any("at deploy" in b for _, b in again), again)
    absent_first, absent_st = plan_messages(view(), {k: v for k, v in st2.items()
                                                    if k != "seed_soaks_sent_at"})
    check("an absent soak source does not burn the soak seed marker",
          "seed_soaks_sent_at" not in absent_st, absent_st)
    _, st8 = plan_messages(view(soak_read="read", soaks=[s1]), st2)
    msgs9, _ = plan_messages(view(soak_read="read", soaks=[{**s1, "state": "mechanical_fail"}]), st8)
    check("a soak moving to mechanical_fail alerts high",
          len(msgs9) == 1 and msgs9[0][0] == "high" and "mechanical_fail" in msgs9[0][1], msgs9)
    later = view(now=now + timedelta(days=1), today=today + timedelta(days=1))
    msgs10, _ = plan_messages(later, st2)
    check("next day sends the next digest", len(msgs10) == 1 and msgs10[0][1].startswith("📋"), msgs10)
    early = view(now=now.replace(hour=2))
    check("no digest before DIGEST_HOUR_UTC",
          not any(b.startswith("📋") for _, b in plan_messages(early, {})[0]), "")
    nr1 = {"id": "RQ-1", "graded_at": "2026-10-02", "reason": "n 9 < 39"}
    nr2 = {"id": "RQ-2", "graded_at": "2026-10-04", "reason": "mixed"}
    nseed, nst = plan_messages(view(needs_review_read="read", needs_review=[nr1]), st2)
    check("first needs_review read sends ONE count line, not one per unit",
          [b for _, b in nseed if "needs_review at deploy" in b] == [
              "🔎 needs_review at deploy: 1 research unit(s) flagged (listed in the daily digest)"], nseed)
    nnew, nst2 = plan_messages(view(needs_review_read="read", needs_review=[nr1, nr2]), nst)
    check("a newly flagged unit alerts once, naming it",
          len(nnew) == 1 and "RQ-2" in nnew[0][1] and "RQ-1" not in nnew[0][1], nnew)
    check("…and is quiet on the next pass",
          plan_messages(view(needs_review_read="read", needs_review=[nr1, nr2]), nst2)[0] == [], "")
    check("an UNREADABLE queue neither alerts nor burns the seed marker",
          plan_messages(view(needs_review_read="unreadable"), st2)[1].get("seed_needs_review_sent_at") is None, "")
    dig = render_digest(view(needs_review_read="read", needs_review=[nr1, nr2]))
    check("the digest carries a loud line with count, age and ids",
          "🔎 2 research unit(s) need a read" in dig and "oldest flagged 2d ago" in dig and "RQ-1" in dig, dig)
    check("unreadable is said, not rendered as zero",
          "UNREADABLE" in render_digest(view(needs_review_read="unreadable")), "")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "RQ-9.yaml").write_text("id: RQ-9\ngrading:\n  needs_review: true\n  graded_at: '2026-10-01'\n  reason: r\n")
        (Path(td) / "RQ-8.yaml").write_text("id: RQ-8\ngrading:\n  needs_review: false\n")
        rd, rows = read_needs_review(Path(td))
        check("the reader finds the flagged unit and skips the unflagged one",
              rd == "read" and [r["id"] for r in rows] == ["RQ-9"], (rd, rows))
        (Path(td) / "RQ-7.yaml").write_text("id: [unclosed\nneeds_review: true\n")
        check("a corrupt unit makes the read UNREADABLE, never a shorter list",
              read_needs_review(Path(td))[0] == "unreadable", "")
    blk, pri, new_items = compose_block(view(), [])
    check("nothing new → ONE quiet line", blk.startswith("🟢") and "\n" not in blk and not new_items, blk)
    blk2, pri2, _ = compose_block(view(), [("high", "❓ 1 new decision"), ("normal", "📋 Daily")])
    check("new items lead, marked 🆕, summary after, priority high",
          blk2.startswith("🆕 NEW since last digest (1)") and blk2.index("❓") < blk2.index("📋")
          and pri2 == "high", blk2)
    lines = ['{', '  "items": [', '    {', '      "id": "A1",', '      "state": "x"',
             '    },', '    {', '      "id": "B2"', '    }', '  ]', '}']
    check("row line ranges parse", _row_line_ranges(lines) == {"A1": (3, 6), "B2": (7, 9)},
          _row_line_ranges(lines))
    check("receipt and state anchored at repo root",
          RECEIPT.parent == REPO_ROOT / "runtime_logs" and STATE.parent == RECEIPT.parent)
    print("attention-watch self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--digest-now", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    return run(dry_run=a.dry_run, digest_now=a.digest_now)


if __name__ == "__main__":
    sys.exit(main())
