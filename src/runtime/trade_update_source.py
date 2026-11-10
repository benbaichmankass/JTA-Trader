"""The ``Source:`` label of a TRADE UPDATED ping — WHAT MECHANISM changed the SL/TP.

Checklist row ``TELEGRAM-TRIM`` (operator 2026-11-10: "every TRADE UPDATED message must say what
mechanism made the change"). Notification text only; changes no trading behaviour.

The five mechanisms the operator named, and the label each caller passes:

* Claude live review (LTR)            ``Claude live review (<review_id>)``
* our own ML                          ``ML: TP revision (<rule>)`` · ``ML: exit head``
* predefined rule, no AI              ``rule: <name>`` (trail / structure exit / breakeven / time stop / TP rule)
* manual (operator or manager)        ``manual (<who>)``
* the desk                            ``desk``

Unknown is ``source unknown`` — never blank (:func:`normalize`).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

UNKNOWN = "source unknown"

#: tp_revision rules that are our own ML (src/units/strategies/ml_entry.py::TP_RULE). Any other
#: registered tp_revision rule (donchian measured move, tp_extend) is a predefined rule.
ML_TP_RULES = frozenset({"ml_first_passage"})


def normalize(source: Optional[str]) -> str:
    """A non-blank, single-line label; ``source unknown`` when nothing was given."""
    s = " ".join(str(source or "").split())
    return s[:120] if s else UNKNOWN


def from_monitor_verdict(verdict: Optional[Mapping[str, Any]], strategy: Optional[str] = None) -> str:
    """Label for a change made by ``order_monitor`` from a strategy-monitor verdict.

    The verdict dict does not name its own rule for an SL move, so the label is as specific as the
    verdict is: a TP revision names its rule (``tp_reason`` is ``"<rule>: <why>"``), an exit-head
    verdict says so, a verdict carrying a ``reason`` names it, anything else is the strategy's own
    rule-based monitor (trail / breakeven / structure / time stop) — never AI.
    """
    v = verdict if isinstance(verdict, Mapping) else {}
    reason = str(v.get("reason") or "").strip()
    if reason == "exit_head":
        return "ML: exit head"
    tp_reason = str(v.get("tp_reason") or "").strip()
    if tp_reason and "sl" not in v:
        rule = tp_reason.split(":", 1)[0].strip()
        if rule in ML_TP_RULES:
            return f"ML: TP revision ({rule})"
        if rule:
            return f"rule: {rule}"
    if reason:
        return f"rule: {reason}"
    leg = str(strategy or "").strip()
    return f"rule: strategy monitor ({leg})" if leg else "rule: strategy monitor"
