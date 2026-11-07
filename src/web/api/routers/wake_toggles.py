"""Wake-notification switches: the read side (console + posters on GitHub runners).

``GET /api/bot/wake-toggles``  unauthenticated read (Tier 1, like the other read routes): ``read_state`` first
(``read | defaults | could_not_look``; ``defaults`` = nobody has flipped anything yet), per-switch ``on``,
``changed_at`` / ``changed_by``, recent flips. Read-only: this router writes nothing. The write route and the posters
that obey the switches ship separately (Tier 2). Logic: ``src/runtime/wake_toggles.py``.

Gates this adds or changes: none.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.runtime import wake_toggles as wt

router = APIRouter(prefix="/api/bot", tags=["wake-toggles"])


def payload() -> dict[str, Any]:
    st = wt.read_local()
    t = st.get("toggles")
    rows = [{"key": k, "label": m["label"], "group": m["group"], "default": m["default"],
             "on": (None if t is None else t[k]), **((st.get("detail") or {}).get(k) or {})}
            for k, m in wt.TOGGLES.items()]
    return {"read_state": st["read_state"], "toggles": t, "rows": rows, "recent_flips": wt.recent_flips(),
            "population": f"{len(wt.TOGGLES)} wake switches (VM runtime state)",
            "note": "unreadable state => every poster posts (never silences by doubt)"}


@router.get("/wake-toggles")
def get_wake_toggles() -> dict[str, Any]:
    return payload()
