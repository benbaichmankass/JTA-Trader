"""THE STRUCTURED BLOCK — what is blocking an item, who owns it, and the machine-checkable condition that clears it.

WHY (operator, 2026-11-12 ~10:45Z, verbatim): *"when something is blocked or waiting, there needs to be clear reasoning for
what is blocking it and what conditions will change that, and ... either that item in the work queue needs to know how to
create an alert when those blocks are lifted, or it needs to be part of a regular checkup"*. The case: slv_trend_1h's demote
was lifted 2026-11-04, its one remaining blocker (a TP test) was parked with a far ``not_before``, and nothing watched it, so
for 8 days nobody acted. Row ``UNBLOCK-WATCH``.

Gates this adds or changes: this module refuses nothing itself; it supplies :func:`refusable`, which the two writers use.
GATE (operator-approved, decision: 2026-11-12 operator popup "Yes: refuse it (Recommended)"): ``scripts/ops/checklist.py`` and
``scripts/ops/pipeline.py`` REFUSE a NEW or CHANGED blocked/waiting item whose block has no machine-checkable condition and no
explicit ``manual:<text>``. Switch: ``config/unblock_watch.yaml::refuse_unconditioned`` (true); remove by setting it false.
Closing an item is never refused; an untouched legacy block is never refused (it only warns).

ONE SHAPE, THREE STORES (no parallel register — the condition lives ON the item that is blocked):

* checklist row: each ``blocked_on`` edge may carry ``reason`` / ``owner`` / ``clears_when`` / ``since`` / ``money`` / ``set_by``.
* research unit (``research/queue/*.yaml``): a ``blocked:`` mapping with the same keys.
* pipeline item: ``due_when.conditions`` (list) beside the prose ``due_when.clears_when``; ``what`` is the reason and
  ``routed_to`` the owner unless the block says otherwise.

A CONDITION is a string ``kind:arg`` (or a mapping ``{kind, arg}``). Kinds:

  ``pr_merged:<n>`` / ``pr_closed:<n>``      the PR is merged / closed (merged counts as closed)
  ``deployed:<#pr | sha>``                    the commit is an ancestor of a ``deployed_sha_by_unit`` marker (diag version)
  ``row_state:<ID>=<state>[|<state>]``        a checklist row (or pipeline item) is in one of the states
  ``unit_result:<RQ id>[=<verdict>]``         a MEASURED result landed under ``research/results/<id>/``
  ``operator_answer:<qid>``                   the decisions inbox records an answer for the request
  ``date:<iso>``                              the clock has passed it
  ``data_n:<diag path> >= <k>``               the diag query returns at least k rows
  ``manual:<text>``                           the last resort; not machine-checkable, goes stale after 7 days

LEGACY stays readable: free text is classed ``manual``; a legacy ``{kind: work_item, ref: X}`` edge implies
``row_state:X=done|dropped``; a research edge implies ``unit_result``; an ``operator_decision`` edge implies
``operator_answer``; a unit's ``not_before`` implies ``date`` and its ``requires_result`` implies ``unit_result``. Implied
conditions are marked ``implied: True`` so a report can say which conditions a human wrote and which were inferred.
"""
from __future__ import annotations

import re
from typing import Any

KINDS = ("pr_merged", "pr_closed", "deployed", "row_state", "unit_result", "operator_answer", "date", "data_n", "manual")
CHECKABLE = tuple(k for k in KINDS if k != "manual")
#: A manual condition older than this is ``stale_manual`` (operator brief, 2026-11-12).
STALE_MANUAL_DAYS = 7
#: A money-blocking wait longer than this goes to the operator's decisions page as a question.
MONEY_WAIT_DAYS = 7

ROW_DONE_STATES = ("done", "dropped")
_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Za-z0-9._]+)+$")
_PR_RE = re.compile(r"^#?(\d{1,6})$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


class ConditionError(ValueError):
    """A condition string that names a known kind but cannot be parsed."""


def parse(cond: Any) -> dict:
    """``"kind:arg"`` or ``{kind, arg}`` -> a normalised dict. Unknown kinds and bare prose become ``manual``
    (backward compatible: legacy free text stays readable). A KNOWN kind with a malformed argument raises."""
    if isinstance(cond, dict):
        kind = str(cond.get("kind") or "").strip()
        if kind in KINDS:
            arg = cond.get("arg")
            if arg is None:   # tolerate {kind: pr_merged, ref: 123} / {kind: data_n, query:..., k:...}
                arg = cond.get("ref") if cond.get("ref") is not None else cond.get("query")
                if kind == "data_n" and cond.get("k") is not None:
                    arg = f"{arg}>={cond.get('k')}"
            out = parse(f"{kind}:{arg}")
            for extra in ("implied", "since", "note"):
                if cond.get(extra) is not None:
                    out[extra] = cond[extra]
            return out
        text = cond.get("what") or cond.get("text") or cond.get("ref") or ""
        return {"kind": "manual", "arg": str(text).strip(), "raw": str(text).strip()}
    s = str(cond if cond is not None else "").strip()
    kind, sep, arg = s.partition(":")
    kind = kind.strip()
    if not sep or kind not in KINDS:
        return {"kind": "manual", "arg": s, "raw": s}
    arg = arg.strip()
    out: dict[str, Any] = {"kind": kind, "arg": arg, "raw": s}
    if kind in ("pr_merged", "pr_closed"):
        m = _PR_RE.match(arg)
        if not m:
            raise ConditionError(f"{s!r}: expected {kind}:<PR number>")
        out["pr"] = int(m.group(1))
    elif kind == "deployed":
        m = _PR_RE.match(arg)
        if m and arg.startswith("#"):
            out["pr"] = int(m.group(1))
        elif _SHA_RE.match(arg.lower()):
            out["sha"] = arg.lower()
        elif m:
            out["pr"] = int(m.group(1))
        else:
            raise ConditionError(f"{s!r}: expected deployed:<#PR or sha>")
    elif kind == "row_state":
        ref, eq, states = arg.partition("=")
        if not eq or not ref.strip() or not states.strip():
            raise ConditionError(f"{s!r}: expected row_state:<ID>=<state>[|<state>]")
        out["ref"] = ref.strip()
        out["states"] = [x.strip() for x in states.split("|") if x.strip()]
    elif kind == "unit_result":
        ref, _, verdict = arg.partition("=")
        if not ref.strip():
            raise ConditionError(f"{s!r}: expected unit_result:<RQ id>[=<verdict>]")
        out["ref"] = ref.strip()
        out["verdict"] = verdict.strip() or None
    elif kind == "operator_answer":
        if not arg:
            raise ConditionError(f"{s!r}: expected operator_answer:<qid>")
        out["ref"] = arg
    elif kind == "date":
        from datetime import datetime  # noqa: PLC0415
        try:
            datetime.fromisoformat(arg.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConditionError(f"{s!r}: expected date:<ISO date or timestamp>") from exc
    elif kind == "data_n":
        query, ge, k = arg.rpartition(">=")
        try:
            out["k"] = int(k.strip())
        except ValueError as exc:
            raise ConditionError(f"{s!r}: expected data_n:<diag path> >= <k>") from exc
        if not ge or not query.strip():
            raise ConditionError(f"{s!r}: expected data_n:<diag path> >= <k>")
        out["query"] = query.strip()
    return out


def parse_safe(cond: Any) -> dict:
    """``parse`` that never raises: a malformed known-kind condition is returned as ``manual`` with ``malformed`` set,
    so a reader never crashes on a bad hand edit and the report can name it."""
    try:
        return parse(cond)
    except ConditionError as exc:
        return {"kind": "manual", "arg": str(cond), "raw": str(cond), "malformed": str(exc)}


def is_checkable(c: dict) -> bool:
    return c.get("kind") in CHECKABLE


def _as_list(v: Any) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


# ── per-store normalisation: every reader sees the same {reason, owner, conditions, since, money, set_by} ──
def _block(reason: Any, owner: Any, conds: list[dict], since: Any = None, money: Any = None,
           set_by: Any = None, legacy: bool = False) -> dict:
    return {"reason": (str(reason).strip() or None) if reason else None, "owner": (str(owner).strip() or None) if owner else None,
            "conditions": conds, "since": since, "money": bool(money), "set_by": set_by, "legacy": legacy}


def edge_block(edge: Any) -> dict:
    """One checklist ``blocked_on`` entry (dict, bare string or int) -> a block."""
    if isinstance(edge, dict):
        explicit = [parse_safe(c) for c in _as_list(edge.get("clears_when"))]
        if explicit:
            return _block(edge.get("reason") or edge.get("what"), edge.get("owner"), explicit,
                          edge.get("since"), edge.get("money"), edge.get("set_by"))
        kind = str(edge.get("kind") or "").strip().lower()
        ref = str(edge.get("ref") or "").strip()
        what = edge.get("what") or edge.get("reason")
        implied: list[dict] = []
        if ref:
            if kind in ("work_item", "row", "object", "item", "checklist", "step", "intent", "pipeline", "pipeline_item"):
                implied = [dict(parse(f"row_state:{ref}={'|'.join(ROW_DONE_STATES + ('killed',))}"), implied=True)]
            elif kind in ("research", "research_unit", "rq", "queue") or ref.startswith("RQ-"):
                implied = [dict(parse(f"unit_result:{ref}"), implied=True)]
            elif kind in ("operator_decision", "operator"):
                implied = [dict(parse(f"operator_answer:{ref}"), implied=True)]
            elif kind == "pr" and _PR_RE.match(ref):
                implied = [dict(parse(f"pr_merged:{ref}"), implied=True)]
            elif kind in ("", "observation") and _ID_RE.match(ref) and not ref.startswith("RQ-"):
                implied = [dict(parse(f"row_state:{ref}={'|'.join(ROW_DONE_STATES + ('killed',))}"), implied=True)]
        if not implied:
            implied = [{"kind": "manual", "arg": str(what or ref), "raw": str(what or ref)}]
        return _block(what or ref, edge.get("owner"), implied, edge.get("since"), edge.get("money"),
                      edge.get("set_by"), legacy=True)
    s = str(edge if edge is not None else "").strip()
    c = parse_safe(s)
    if c["kind"] == "manual" and _ID_RE.match(s):
        c = dict(parse(f"row_state:{s}={'|'.join(ROW_DONE_STATES + ('killed',))}"), implied=True)
    return _block(s, None, [c] if s else [], legacy=c["kind"] == "manual" or bool(c.get("implied")))


def row_blocks(row: dict) -> list[dict]:
    """Every block on a checklist row (one per ``blocked_on`` edge). A ``blocked`` row with no edge returns one empty block
    so it reads ``unconditioned`` instead of vanishing."""
    raw = row.get("blocked_on")
    edges = raw if isinstance(raw, list) else ([] if raw in (None, "", [], {}) or isinstance(raw, bool) else [raw])
    blocks = [edge_block(e) for e in edges]
    if not blocks and row.get("state") == "blocked":
        blocks = [_block(None, None, [], legacy=True)]
    for b in blocks:
        b["owner"] = b["owner"] or row.get("owner")
        b["money"] = b["money"] or _row_money(row)
        b["since"] = b["since"] or row.get("updated_at")
    return blocks


def _row_money(row: dict) -> bool:
    try:
        tier = int(row.get("tier"))
    except (TypeError, ValueError):
        tier = 0
    return bool(row.get("money_blocking")) or tier >= 3


def unit_block(unit: dict) -> dict | None:
    """A research unit's block, or None when the unit is not waiting (no ``blocked:``, no future-or-set ``not_before``,
    no ``requires_result``, status not blocked)."""
    st = str(unit.get("status") or "")
    if st in ("done", "retired"):
        return None
    blk = unit.get("blocked") if isinstance(unit.get("blocked"), dict) else {}
    conds = [parse_safe(c) for c in _as_list(blk.get("clears_when"))]
    explicit = bool(conds)
    if not explicit:
        if unit.get("not_before"):
            conds.append(dict(parse_safe(f"date:{str(unit['not_before']).strip()}"), implied=True))
        req = unit.get("requires_result")
        if isinstance(req, dict) and req.get("unit"):
            v = req.get("verdict")
            conds.append(dict(parse_safe(f"unit_result:{req['unit']}" + (f"={v}" if v else "")), implied=True))
        if unit.get("blocked_reason") and st == "blocked":
            conds.append({"kind": "manual", "arg": str(unit["blocked_reason"]).strip(), "raw": str(unit["blocked_reason"]).strip()})
    if not conds and st != "blocked" and not blk:
        return None
    return _block(blk.get("reason") or unit.get("blocked_reason"), blk.get("owner"), conds, blk.get("since"),
                  blk.get("money"), blk.get("set_by"), legacy=not explicit)


def pipeline_block(item: dict) -> dict | None:
    """An OPEN pipeline item waiting on an event (``due_when.kind == event``) or carrying ``due_when.conditions``."""
    if item.get("state") in ("done", "killed"):
        return None
    dw = item.get("due_when") or {}
    conds = [parse_safe(c) for c in _as_list(dw.get("conditions"))]
    explicit = bool(conds)
    if not explicit:
        if dw.get("kind") != "event":
            return None
        c = parse_safe(dw.get("clears_when") or "")
        conds = [c] if c.get("arg") or c.get("kind") != "manual" else []
    return _block(dw.get("reason") or item.get("what"), dw.get("owner") or item.get("routed_to") or item.get("owner"), conds,
                  dw.get("since") or item.get("filed_at") or item.get("created_at") or item.get("ts"), dw.get("money"),
                  dw.get("set_by"), legacy=not explicit)


def problems(block: dict) -> list[str]:
    """What a block is missing against the contract (warn-only; the writers print these, nothing refuses)."""
    out = []
    if not block.get("reason"):
        out.append("no reason")
    if not block.get("owner"):
        out.append("no owner")
    if not any(is_checkable(c) for c in block.get("conditions") or []):
        out.append("no machine-checkable clears_when (only manual/free text)")
    for c in block.get("conditions") or []:
        if c.get("malformed"):
            out.append(f"malformed condition: {c['malformed']}")
    return out


def is_explicit_manual(c: dict) -> bool:
    """A ``manual:<text>`` condition someone WROTE (the sanctioned last resort), as opposed to legacy prose read as manual."""
    return c.get("kind") == "manual" and str(c.get("raw") or "").startswith("manual:") and bool(str(c.get("arg") or "").strip())


def refusable(block: dict) -> bool:
    """The operator's refusal test (2026-11-12 popup "Yes: refuse it (Recommended)"): a block with NO machine-checkable
    condition and NO explicit ``manual:<text>`` -- i.e. prose only, or nothing. A malformed known-kind condition also
    refuses (it was meant to be checkable and is not)."""
    conds = block.get("conditions") or []
    if any(c.get("malformed") for c in conds):
        return True
    return not any(is_checkable(c) or is_explicit_manual(c) for c in conds)


def refuse_unconditioned(repo=None) -> bool:
    """The operator's switch (``config/unblock_watch.yaml::refuse_unconditioned``). Default FALSE = warn and list in the
    brief. Unreadable reads as false (the less-friction reading, canonical § "No new gates" (b))."""
    from pathlib import Path  # noqa: PLC0415
    root = Path(repo) if repo else Path(__file__).resolve().parents[2]
    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load((root / "config" / "unblock_watch.yaml").read_text(encoding="utf-8")) or {}
        return doc.get("refuse_unconditioned") is True
    except Exception:  # noqa: BLE001  # allow-silent: an unreadable switch reads as the no-gate default
        return False
