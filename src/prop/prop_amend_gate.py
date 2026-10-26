"""The firm's rules on a live-review / desk AMEND of an open prop position (DESK-2-RISK-GATE).

``RiskManager.approve_amend`` / ``approve_action`` (``src/runtime/live_review_intent.py``) decide
what every account decides: tighten-only, the noise floor, one amend per bar, the account mode, the
strategy's ``execution: shadow``, both brackets kept, and the account's own fresh-entry check for an
action that adds risk (which carries the daily-DD switch's block on new risk). A prop account adds
the FIRM's rules on top (desk design § 3.2), and this module is that layer:

* **The DD cushion.** An action that ADDS risk (``widen_sl``, an add) must fit inside what is left
  to the firm's static-DD floor and daily-loss limit after the open positions' loss to their stops
  (``prop_risk_gate.grade_ticket_risk``, the ticket gate's own grader). ``exceeds_cushion`` is a
  refusal; ``cushion_unknown`` (a stale or absent status snapshot, an open stop we cannot see) is
  ``could_not_look``, never an approve.
* **The firm's leverage cap** (``limits.leverage_caps``, ``prop_rule_guards``) on an action that
  adds SIZE.
* **A human's stop is never fought** on the phone account: a ``human_hold`` on the ticket refuses.

Actions that only REDUCE risk -- a tighten, a close, a reduce, a TP move -- are never refused for
the DD cushion: the operator's daily-DD rule is "keep open, block new", and a cushion that is
already thin is a reason to tighten, not a reason to refuse one.

Not built, deliberately: the firm's minimum stop distance and a news-window modification
restriction (design § 3.2 "if the ruleset has one"). No ruleset under ``config/prop_rulesets/``
declares either; a check for an undeclared rule would guess at its terms.

Pure: values in, ``AmendVerdict`` out. Every verdict uses ``live_review_intent``'s four states
(registered with ``collapsed-state-guard`` as ``live_review_intent.amend_verdict``). Never writes,
never halts; a refusal is for this action on this account only.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from src.prop import prop_risk_gate as _gate
from src.prop import prop_rule_guards as _guards
from src.runtime import live_review_intent as lri

#: + ":<binding limit>" -- the added risk is at or past what is left to the firm's limit.
R_DD_HEADROOM = "prop_dd_headroom"
#: + ":<symbol>" -- the size after the add breaches the firm's declared leverage cap.
R_LEVERAGE = "prop_leverage_cap"
#: A human moved the stop on the phone account; the review does not fight it.
R_HUMAN_HOLD = "prop_human_hold"
#: could-not-look reasons (prefixed ``could_not_look:``).
CNL_CUSHION = "prop_dd_cushion"
CNL_RULESET = "prop_ruleset"
CNL_LEVERAGE = "prop_leverage_basis"


def adds_risk(intent: lri.LiveReviewIntent) -> bool:
    """True for an action that adds risk: ``widen_sl``, ``add_entry``, ``change_size`` > 1."""
    if intent.action == "widen_sl":
        return True
    if intent.action in ("add_entry", "change_size"):
        d = lri.size_delta(intent)
        return d is not None and d > 0
    return False


def added_risk_usd(intent: lri.LiveReviewIntent, view: lri.AmendAccountView,
                   base: lri.AmendVerdict) -> Optional[float]:
    """The loss-to-stop this action ADDS on this leg, in account currency. None = could not look.

    ``widen_sl``: the open size times the extra stop distance. An add: the added size (the base
    verdict's ``qty``) times its distance from the mark to the stop in force."""
    f = lri._f
    if intent.action == "widen_sl":
        new_sl, cur, pos = f(intent.new_sl), f(view.leg_sl), f(view.position_size)
        if new_sl is None or cur is None or pos is None:
            return None
        return abs(new_sl - cur) * pos
    mark, stop, qty = f(intent.mark), f(view.leg_sl), f(base.qty)
    if mark is None or stop is None or qty is None:
        return None
    return abs(mark - stop) * qty


def decide_prop(base: lri.AmendVerdict, intent: lri.LiveReviewIntent, view: lri.AmendAccountView, *,
                limits: Optional[Mapping[str, Any]],
                cushion_for: Callable[[float], Mapping[str, Any]],
                symbol: Optional[str] = None,
                account_size_usd: Optional[float] = None,
                equity_usd: Optional[float] = None) -> lri.AmendVerdict:
    """The prop layer over ``base`` (the account-generic verdict). Pure apart from ``cushion_for``.

    ``limits`` is the ruleset's ``limits:`` block: ``{}`` = the account declares no ruleset, None =
    it declares one we could not read. ``cushion_for(risk_usd)`` grades a risk against the account's
    remaining cushion (``prop_risk_gate.grade_account_ticket_risk``); it is only called for an action
    that adds risk."""
    if not base.ok:
        return base
    aid = view.account_id

    def refuse(reason: str) -> lri.AmendVerdict:
        return lri.AmendVerdict(aid, lri.V_REFUSE, None, reason)

    def cnl(what: str) -> lri.AmendVerdict:
        return lri.AmendVerdict(aid, lri.V_COULD_NOT_LOOK, None, f"{lri.R_COULD_NOT_LOOK}:{what}")

    hold = (view.extra or {}).get("human_hold")
    if hold:
        return refuse(R_HUMAN_HOLD)
    if not adds_risk(intent):
        return base

    if limits is None:
        return cnl(CNL_RULESET)
    if intent.action != "widen_sl":
        caps = _guards.leverage_caps(limits)
        if _guards.leverage_cap_for(caps, symbol or "") is not None:
            mark, pos, add = lri._f(intent.mark), lri._f(view.position_size), lri._f(base.qty)
            notional = (pos + add) * mark if None not in (mark, pos, add) else None
            basis = _guards.leverage_basis(account_size_usd, [equity_usd])
            if notional is None or basis is None:
                return cnl(CNL_LEVERAGE)
            if _guards.leverage_breach(symbol=symbol or "", notional_usd=notional, caps=caps,
                                       basis_usd=basis):
                return refuse(f"{R_LEVERAGE}:{str(symbol or '').upper()}")

    risk = added_risk_usd(intent, view, base)
    if risk is None:
        return cnl(f"{CNL_CUSHION}:added_risk")
    try:
        g = dict(cushion_for(risk) or {})
    except Exception as exc:  # noqa: BLE001 -- a failed read is could-not-look, never an approve
        return cnl(f"{CNL_CUSHION}:{type(exc).__name__}")
    state = g.get("state")
    if state == _gate.WITHIN:
        return base
    if state == _gate.EXCEEDS:
        return refuse(f"{R_DD_HEADROOM}:{g.get('binding_limit') or 'limit'}")
    why = g.get("status_freshness") if g.get("status_freshness") not in (None, "ok") \
        else (g.get("open_risk_state") or state or "unread")
    return cnl(f"{CNL_CUSHION}:{why}")


__all__ = ["R_DD_HEADROOM", "R_LEVERAGE", "R_HUMAN_HOLD", "CNL_CUSHION", "CNL_RULESET", "CNL_LEVERAGE",
           "adds_risk", "added_risk_usd", "decide_prop"]
