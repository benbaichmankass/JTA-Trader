"""Work-queue reorder (WORK-REORDER-ROUTE): move ONE row beside another, writing only the moved row.

``priority_rank`` is a priority CLASS shared by many rows (dispatch and ``due_by`` read it so), so a move
never renumbers anything. Display order is the key :func:`display_key`:

    (priority_rank asc, nulls last,  position asc,  id)      position = ``extra.queue_pos`` if set,
                                                              else the row's register order (``extra._seq``)

so rows that were never moved sit exactly where register order puts them, and a moved row's
``queue_pos`` lives in the same numeric space (midpoint between its new neighbours, or the neighbour
+/- 1 at an edge). A press writes the moved row only: ``priority_rank`` := ``over``'s rank (it may change
class when moved across a boundary) and ``queue_pos``; one versioned ``WorkStore.set``; a second write
(``over`` itself) only if the midpoint has no room. Lives outside the trader import closure on purpose:
it uses the store's public ``get`` / ``list_items`` / ``set`` only.
"""
from __future__ import annotations

from typing import Any

CLOSED = ("done", "dropped", "killed", "retired", "archived")
_NO_SEQ = 1_000_000.0   # a row with no register order sorts after every sequenced row; ties break on id


class ReorderError(Exception):
    """A refusal: ``code`` is the JSON ``error``, ``status`` the HTTP status."""

    def __init__(self, status: int, code: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def _get(row: dict, key: str) -> Any:
    """A key from a checklist-shaped row (top level) or a store item (``extra``)."""
    if key in row:
        return row[key]
    ex = row.get("extra")
    return ex.get(key) if isinstance(ex, dict) else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def rank_of(row: dict) -> float | None:
    r = _num(row.get("priority_rank"))
    return r if r is not None and r > 0 else None


def position(row: dict) -> float:
    q, seq = _num(_get(row, "queue_pos")), _num(_get(row, "_seq"))
    return q if q is not None else (seq if seq is not None else _NO_SEQ)


def display_key(row: dict) -> tuple:
    """The one order every list (``/work/snapshot``, the reorder neighbours) uses."""
    r = rank_of(row)
    return (r is None, r or 0.0, position(row), str(row.get("id") or ""))


def _open_builds(store) -> list[dict]:
    return [r for r in store.list_items(kind="build", limit=10 ** 7) if r.get("state") not in CLOSED]


def reorder(store, item_id: str, direction: str, *, by: str, over: str | None = None,
            expected_version: int | None = None) -> dict:
    if direction not in ("up", "down"):
        raise ReorderError(400, "bad_direction", "direction must be 'up' or 'down'")
    if over is not None and over == item_id:
        raise ReorderError(400, "same_id", "over must be a different row than id")
    rows = _open_builds(store)
    byid = {r["id"]: r for r in rows}
    moved = byid.get(item_id) or store.get(item_id)
    if moved is None or moved.get("kind") != "build":
        raise ReorderError(404, "unknown_id", f"no work row {item_id!r}")
    if moved.get("state") in CLOSED:
        raise ReorderError(422, "refused", f"{item_id!r} is {moved['state']}; a finished row is not in the queue")
    if expected_version is not None and int(expected_version) != moved["version"]:
        raise ReorderError(409, "version_conflict",
                           f"{item_id!r} is at version {moved['version']}, the move was based on {expected_version}")
    full = sorted(rows, key=display_key)
    ids = [r["id"] for r in full]
    if over is None:
        # No visible neighbour given: the neighbour in the row's own list (same state, same blocked-ness).
        blocked = bool(moved.get("blocked_on"))
        own = [r for r in full if r.get("state") == moved["state"] and bool(r.get("blocked_on")) == blocked]
        i = [r["id"] for r in own].index(item_id)
        j = i - 1 if direction == "up" else i + 1
        if j < 0 or j >= len(own):
            edge = "top" if direction == "up" else "bottom"
            raise ReorderError(409, f"at_{edge}", f"{item_id!r} is already at the {edge} of its list "
                               f"({len(own)} rows)", position=i + 1, population=len(own))
        over = own[j]["id"]
    anchor = byid.get(over)
    if anchor is None:
        if store.get(over) is None or store.get(over).get("kind") != "build":
            raise ReorderError(404, "unknown_over", f"no work row {over!r} (over)")
        raise ReorderError(422, "refused", f"{over!r} is finished; a finished row is not in the queue")
    ia, im = ids.index(over), ids.index(item_id)
    if im == (ia - 1 if direction == "up" else ia + 1):
        raise ReorderError(409, "no_change", f"{item_id!r} is already directly "
                           f"{'above' if direction == 'up' else 'below'} {over!r}")
    # The neighbour of `over` on the requested side, within over's own priority class and ignoring the
    # moved row: it bounds the midpoint. None = `over` is the class's edge on that side.
    cls = rank_of(anchor)
    same = [r for r in full if r["id"] != item_id and rank_of(r) == cls]
    k = [r["id"] for r in same].index(over)
    nb = same[k - 1] if direction == "up" and k > 0 else (same[k + 1] if direction == "down" and k + 1 < len(same) else None)
    pa = position(anchor)
    up = direction == "up"
    shove: float | None = None          # a new position for `over`, only when the midpoint has no room
    if nb is None:
        new_pos = pa + (-1.0 if up else 1.0)
    else:
        pn = position(nb)
        new_pos = (pa + pn) / 2.0
        if not min(pa, pn) < new_pos < max(pa, pn):          # equal positions (or float exhaustion)
            shove = pa + (1.0 if up else -1.0)               # over steps away from the moved row's side...
            new_pos = pa + (0.5 if up else -0.5)             # ...and the moved row takes the gap
    writes: list[str] = []
    if shove is not None:
        store.set(over, {"extra": _with_pos(anchor, shove)}, by=by, expected_version=anchor["version"])
        writes.append(over)
    fields = {"priority_rank": anchor.get("priority_rank"), "extra": _with_pos(moved, new_pos)}
    res = store.set(item_id, fields, by=by, expected_version=moved["version"])
    writes.append(item_id)
    return {"item": res["item"], "changed": writes, "over": over, "queue_pos": new_pos,
            "rank": anchor.get("priority_rank")}


def _with_pos(row: dict, pos: float) -> dict:
    ex = dict(row.get("extra") or {})
    ex["queue_pos"] = pos
    return ex
