"""Per-package AUTO-APPLY mandates for the live trade review (MD-LTR-ADA-AUTO, operator 2026-10-29).

Every in-trade class is ADVICE ONLY (``live_review_rows.ADVICE_ONLY_ACTIONS``, operator 2026-10-28,
"Advice-only until tested"). The operator may lift that for ONE order package by granting a
``kind: ltr_auto_apply`` entry under ``mandates:`` in ``config/mandates.yaml``; the first was
MD-LTR-ADA-AUTO, verbatim on checklist row MD-LTR-ADA-AUTO: "I want to put a standing mandate for ltr
lanes recommendations on this trade to be applied automatically" (popups: scope "Every action";
mechanism "VM applies it directly").

This module is the ONE reader of those entries, keyed on the FILE (field beats comment), never on a
default-off flag: there is no third execution gate. A mandate decides what may be CHANGED without
asking; ``accounts.yaml::mode`` and ``strategies.yaml::execution`` still decide what runs, and each
account's own RiskManager still decides inside ``live_review_apply.py``.

An entry scopes a row when ALL of these hold (:func:`scoping`):

* it sits under ``mandates:`` (granted; ``proposed:`` never counts) with ``kind: ltr_auto_apply``;
* ``package_scope.order_package_id`` equals the row's ``order_package_id`` (one package, never a pattern);
* the row's action is in ``package_scope.actions``;
* it is not expired: no ``expired_at``, and ``expires_on`` (an optional ISO date backstop) not passed.
  ``expires_on_event: order_package_closed`` needs no read here: a closed package is refused by the apply
  (``package ... not open``), gets no due cadence (only open packages are evaluated) and never reopens.

Readers: the VM rows watcher and ``live_review_dispatch`` (which rows may execute), ``live_review_apply``
(re-checks the grant and enforces :data:`BOUNDS`), and the due computation (:func:`cadence`: the VM wake
poster's review cadence for a scoped open package). Every read failure reads as "no exception": the row
stays advice-only.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
MANDATES_PATH = ROOT / "config" / "mandates.yaml"
KIND = "ltr_auto_apply"
#: The due event a scoped open package gets on its cadence (src/runtime/live_review_due.py).
CADENCE_EVENT = "mandate_cadence"
#: Bounds that bind on every action applied under an auto mandate, enforced in live_review_apply.py
#: (each named in the entry's ``bounds:``; tests/test_ltr_auto_mandate.py pins the two lists equal).
BOUNDS = ("both_brackets", "widen_within_1r", "tp_live_target", "one_action_per_bar", "venue_readback",
          "one_ping_per_action")


#: (path, mtime_ns, size) -> parsed doc. A YAML parse of the file costs ~80 ms (MEASURED 2026-10-29); the
#: watcher and the due pass read it every pass, so it is re-parsed only when the file changes (git-sync).
_cache: Dict[Any, Dict[str, Any]] = {}


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    """The parsed mandates file, or {} when it cannot be read (= no exception anywhere)."""
    p = path or MANDATES_PATH
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if key in _cache:
            return _cache[key]
        import yaml

        doc = yaml.safe_load(p.read_text())
    except Exception:  # noqa: BLE001 -- an unreadable file grants nothing
        return {}
    doc = doc if isinstance(doc, dict) else {}
    _cache.clear()
    _cache[key] = doc
    return doc


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def active(doc: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every granted, unexpired ``ltr_auto_apply`` entry. Malformed entries are skipped (fail closed)."""
    doc = load() if doc is None else doc
    today = (now or datetime.now(timezone.utc)).date()
    out = []
    for m in (doc.get("mandates") or []) if isinstance(doc, dict) else []:
        if not isinstance(m, dict) or m.get("kind") != KIND or not m.get("id"):
            continue
        if m.get("expired_at"):
            continue
        if m.get("expires_on") is not None:
            until = _day(m.get("expires_on"))
            if until is None or today > until:
                continue
        sc = m.get("package_scope")
        if not isinstance(sc, dict) or not str(sc.get("order_package_id") or "").startswith("pkg-"):
            continue
        if not isinstance(sc.get("actions"), list) or not sc["actions"]:
            continue
        out.append(m)
    return out


def scoping(order_package_id: Any, action: Any, doc: Optional[Dict[str, Any]] = None,
            now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The active entry that scopes (package, action), or None (the row stays advice-only)."""
    if not order_package_id or not action:
        return None
    for m in active(doc, now):
        sc = m["package_scope"]
        if str(sc["order_package_id"]) == str(order_package_id) and str(action) in [str(a) for a in sc["actions"]]:
            return m
    return None


def exception_for(row: Dict[str, Any], doc: Optional[Dict[str, Any]] = None,
                  now: Optional[datetime] = None) -> Optional[str]:
    """The mandate id that lifts advice-only for this review row, or None."""
    m = scoping(row.get("order_package_id"), (row.get("recommendation") or {}).get("action"), doc, now)
    return str(m["id"]) if m else None


def is_auto_mandate(mandate_id: Any, doc: Optional[Dict[str, Any]] = None,
                    now: Optional[datetime] = None) -> bool:
    return any(str(m["id"]) == str(mandate_id) for m in active(doc, now))


def cadence(doc: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """{order_package_id: {"mandate": id, "minutes": N}} for every active entry with a review cadence."""
    out: Dict[str, Dict[str, Any]] = {}
    for m in active(doc, now):
        try:
            mins = int(m.get("review_cadence_minutes") or 0)
        except (TypeError, ValueError):
            continue
        if mins > 0:
            out[str(m["package_scope"]["order_package_id"])] = {"mandate": str(m["id"]), "minutes": mins}
    return out
