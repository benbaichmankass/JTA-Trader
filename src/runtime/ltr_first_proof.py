"""Live trade review FIRST-PROOF pings: one Telegram ping per LTR stage, once ever.

Operator, 2026-10-26 ~12:40Z (verbatim): "i also want a ping when each stage of
the ltr flow is first proved - the ltr session making a call, and each step to
that call being executed at the broker".

Stages, in order (``STAGES``):

  S1_wake       the first ltr-wake comment posted (VM poster, or a poller marker it reads)
  S2_call       the first real-money/prop review row with a judgement call
                (hold or tighten_sl, basis judgement, confidence + reason)
  S3_tighten    the first real-money/prop tighten_sl row
  S4_pickup     the VM rows watcher dispatches that row
  S5_approve    approve_amend approved/clipped it on >= 1 account (applied.jsonl
                account_reads read == would_apply)
  S6_sent       the executor sent the amend (applied.jsonl accounts_applied non-empty)
  S7_confirmed  the venue read-back shows the new stop (disposition.verified_readback)

S6 and S7 both come from the ONE apply writeback: the apply records an
executed amend only after its read-back, so their timestamps are the same
instant. That is a limit of the evidence, stated in the ping, not a measured
zero-latency send.

Each ping names the stage, review_id, leg, accounts, the timestamp and the
latency from the previous stage; S7 also carries trigger -> confirmed.

State: ``runtime_logs/ltr_first_proof.json`` (diag ``log_file`` name
``ltr_first_proof``). A stage is written ONLY after its send returned True, so a
failed send is retried at the next occurrence. When the file is absent it is
SEEDED from the receipts that already exist (poster receipt, rows-watch log,
applied log, the committed reviews): a stage already proven is marked
``seeded`` and never pings, so nothing fires falsely and nothing fires late.

Best-effort: ``record()`` never raises. No ``*_ENABLED`` flag.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

STAGES = ("S1_wake", "S2_call", "S3_tighten", "S4_pickup", "S5_approve", "S6_sent", "S7_confirmed")
LABELS = {
    "S1_wake": "wake posted (ops-flags ltr-wake)",
    "S2_call": "LTR session made a judgement call on real money/prop",
    "S3_tighten": "first real-money/prop tighten_sl recommended",
    "S4_pickup": "VM watcher picked the row up and dispatched it",
    "S5_approve": "approve_amend approved/clipped on an account",
    "S6_sent": "executor sent the amend to the venue",
    "S7_confirmed": "venue read-back confirms the new stop",
}
MONEY_CLASSES = ("real_money", "prop")
STATE_NAME = "ltr_first_proof.json"
_LOCK = threading.RLock()

Sender = Callable[[str], bool]


def state_path() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / STATE_NAME


def _send(text: str) -> bool:
    from src.runtime import telegram_channels
    return bool(telegram_channels.send("alert", text))


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def is_money(row: Dict[str, Any]) -> bool:
    return any(str((a or {}).get("account_class") or "").lower() in MONEY_CLASSES
               for a in row.get("account_reads") or [])


def is_judgement_call(row: Dict[str, Any]) -> bool:
    rec = row.get("recommendation") or {}
    return (rec.get("action") in ("hold", "tighten_sl") and rec.get("basis") == "judgement"
            and isinstance(rec.get("judgement_confidence"), (int, float))
            and bool(str(rec.get("reason") or "").strip()))


def is_tighten(row: Dict[str, Any]) -> bool:
    return (row.get("recommendation") or {}).get("action") == "tighten_sl"


def writeback_stages(entry: Dict[str, Any]) -> List[str]:
    """S5..S7 a money applied.jsonl writeback proves."""
    out = []
    reads = entry.get("account_reads") or []
    if any(str(a.get("account_class") or "").lower() in MONEY_CLASSES and a.get("read") == "would_apply"
           for a in reads):
        out.append("S5_approve")
    if entry.get("accounts_applied"):
        out.append("S6_sent")
        if (entry.get("disposition") or {}).get("verified_readback") is True:
            out.append("S7_confirmed")
    return out


# --------------------------------------------------------------------------- state

def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _save(path: Path, st: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def _jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _committed_reviews() -> List[Dict[str, Any]]:
    from src.utils.paths import repo_root
    rows: List[Dict[str, Any]] = []
    for ref in ("HEAD", "refs/live-review/live-review/rows"):
        try:
            r = subprocess.run(["git", "-C", repo_root(), "show", f"{ref}:comms/live_review/reviews.jsonl"],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            for ln in r.stdout.splitlines():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    pass
    try:  # the reviewers' per-row files (LTR-ROWS-SWAP-TRUNCATION); best-effort like the rest
        from src.runtime import live_review_rows
        from src.runtime.live_review_rows_watch import LOCAL_REF, _git
        read = live_review_rows.read_at(LOCAL_REF, _git)
        if read["state"] == "ok":
            have = {r.get("review_id") for r in rows if isinstance(r, dict)}
            rows.extend(r for r in read["rows"] if r["review_id"] not in have)
    except Exception:  # noqa: BLE001
        pass
    return rows


def seed(now: datetime, logs: Path, reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stages already proven by existing receipts; marked seeded, never pinged."""
    st: Dict[str, Any] = {"seeded_at": now.isoformat(), "stages": {}}

    def mark(stage: str, why: str) -> None:
        st["stages"].setdefault(stage, {"seeded": True, "evidence": why})

    post = _load(logs / "ltr_wake_post_receipt.json") or {}
    if post.get("state") in ("posted", "already_posted"):
        mark("S1_wake", f"ltr_wake_post_receipt {post.get('state')}")
    for r in reviews:
        if isinstance(r, dict) and is_money(r):
            if is_judgement_call(r):
                mark("S2_call", f"review {r.get('review_id')}")
            if is_tighten(r):
                mark("S3_tighten", f"review {r.get('review_id')}")
    for e in _jsonl(logs / "live_review" / "rows_watch.jsonl"):
        if e.get("exit") in (0, 1, 2) and e.get("verdict") not in ("not_dispatchable",):
            mark("S4_pickup", f"rows_watch {e.get('review_id')}")
    for e in _jsonl(logs / "live_review" / "applied.jsonl"):
        for s in writeback_stages(e):
            mark(s, f"applied {e.get('review_id')}")
    return st


def load_state(path: Optional[Path] = None, now: Optional[datetime] = None,
               reviews: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    p = path or state_path()
    with _LOCK:
        st = _load(p)
        if st is None:
            st = seed(now or datetime.now(timezone.utc), p.parent,
                      reviews if reviews is not None else _committed_reviews())
            _save(p, st)
        return st


def ensure_seeded() -> None:
    """Seed BEFORE any new event can reach a receipt (called at each emitter's
    thread start). Seeding later would swallow a real first proof. Never raises."""
    try:
        load_state()
    except Exception:  # noqa: BLE001
        logger.warning("ltr-first-proof: seed failed", exc_info=True)


# --------------------------------------------------------------------------- record

def render(stage: str, *, at: datetime, review_id: Optional[str], leg: Optional[str],
           accounts: List[str], latency_s: Optional[float], prev: Optional[str],
           end_to_end_s: Optional[float] = None, note: Optional[str] = None) -> str:
    lat = f"{latency_s:.0f}s after {prev}" if latency_s is not None and prev else "— (no earlier stage recorded)"
    lines = [f"LTR FIRST PROOF {stage}: {LABELS[stage]}",
             f"review: {review_id or '—'} · leg: {leg or '—'} · accounts: {', '.join(accounts) or '—'}",
             f"at: {at.isoformat()} · latency: {lat}"]
    if end_to_end_s is not None:
        lines.append(f"end to end, trigger -> confirmed: {end_to_end_s:.0f}s")
    if note:
        lines.append(note)
    return "\n".join(lines)


def record(stage: str, *, at: datetime, review_id: Optional[str] = None, leg: Optional[str] = None,
           accounts: Optional[List[str]] = None, trigger_at: Optional[datetime] = None,
           note: Optional[str] = None, send: Optional[Sender] = None, path: Optional[Path] = None) -> bool:
    """Ping the FIRST proof of ``stage``. True only when this call sent and stored it. Never raises."""
    try:
        with _LOCK:
            return _record_locked(stage, at=at, review_id=review_id, leg=leg, accounts=list(accounts or []),
                                  trigger_at=trigger_at, note=note, send=send or _send, path=path or state_path())
    except Exception:  # noqa: BLE001 — observability never blocks the path
        logger.warning("ltr-first-proof: %s not recorded", stage, exc_info=True)
        return False


def _record_locked(stage: str, *, at: datetime, review_id: Optional[str], leg: Optional[str],
                   accounts: List[str], trigger_at: Optional[datetime], note: Optional[str],
                   send: Sender, path: Path) -> bool:
    st = load_state(path, now=at)
    stages = st.setdefault("stages", {})
    if stage in stages:
        return False
    prev_name, prev_at = None, None
    for s in reversed(STAGES[:STAGES.index(stage)]):
        t = _ts((stages.get(s) or {}).get("at"))
        if t:
            prev_name, prev_at = s, t
            break
    latency = (at - prev_at).total_seconds() if prev_at else None
    e2e = (at - trigger_at).total_seconds() if (stage == "S7_confirmed" and trigger_at) else None
    text = render(stage, at=at, review_id=review_id, leg=leg, accounts=accounts,
                  latency_s=latency, prev=prev_name, end_to_end_s=e2e, note=note)
    if not send(text):
        return False  # not marked: the next occurrence retries
    stages[stage] = {"at": at.isoformat(), "review_id": review_id, "leg": leg, "accounts": accounts,
                     "latency_s": latency, "after": prev_name, "end_to_end_s": e2e,
                     "pinged_at": datetime.now(timezone.utc).isoformat()}
    _save(path, st)
    return True


def observe_wake_markers(markers: List[Dict[str, Any]], **kw: Any) -> bool:
    """S1 from ltr-wake markers read off the ops-flags PR (poller or VM). A wake posted
    before the state was seeded is history: marked seeded, never pinged late."""
    wakes = sorted((m for m in markers or [] if m.get("kind") == "wake" and _ts(m.get("posted_at"))),
                   key=lambda m: _ts(m.get("posted_at")))
    if not wakes:
        return False
    first = wakes[0]
    at = _ts(first["posted_at"])
    entry = (first.get("entries") or [{}])[0]
    path = kw.pop("path", None) or state_path()
    with _LOCK:
        st = load_state(path, now=at)
        seeded_at = _ts(st.get("seeded_at"))
        if "S1_wake" not in st.get("stages", {}) and seeded_at and at < seeded_at:
            st["stages"]["S1_wake"] = {"seeded": True, "evidence": f"ltr-wake marker {first.get('posted_at')}"}
            _save(path, st)
            return False
    return record("S1_wake", at=at, review_id=entry.get("review_id"), leg=entry.get("leg"),
                  accounts=list(entry.get("accounts") or []), path=path,
                  note=f"posted by {entry.get('poster') or 'poller'}", **kw)


def record_row(row: Dict[str, Any], *, at: datetime, **kw: Any) -> List[str]:
    """S2 / S3 for a newly seen review row. Returns the stages it sent."""
    if not is_money(row):
        return []
    common = dict(at=at, review_id=row.get("review_id"), leg=row.get("leg"),
                  accounts=list(row.get("accounts") or []), **kw)
    sent = []
    if is_judgement_call(row) and record("S2_call", **common):
        sent.append("S2_call")
    if is_tighten(row) and record("S3_tighten", **common):
        sent.append("S3_tighten")
    return sent


def record_writeback(row: Dict[str, Any], entry: Optional[Dict[str, Any]], *, at: datetime,
                     **kw: Any) -> List[str]:
    """S5..S7 from the apply's applied.jsonl writeback for ``row``."""
    if not entry or not is_money(row):
        return []
    trig = _ts((row.get("trigger") or {}).get("l0_snapshot_at")) or _ts(row.get("reviewed_at"))
    accts = [a.get("account_id") for a in entry.get("accounts_applied") or []] or list(row.get("accounts") or [])
    sent = []
    for s in writeback_stages(entry):
        note = ("S6 and S7 come from the same apply writeback (the executed amend is recorded only after "
                "its read-back), so their times coincide.") if s in ("S6_sent", "S7_confirmed") else None
        if record(s, at=at, review_id=row.get("review_id"), leg=row.get("leg"), accounts=accts,
                  trigger_at=trig, note=note, **kw):
            sent.append(s)
    return sent
