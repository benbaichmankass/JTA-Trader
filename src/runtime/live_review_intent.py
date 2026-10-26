"""Package-level live-trade-review intent, and the per-account amend decision.

LTR-6R-APPLY-PATH (operator structural directive 2026-10-25, recorded on
checklist row ``LTR-6R-APPLY-PATH``): the live trade review acts at the
strategy-ticket / ORDER-PACKAGE level and never does per-account risk
management. Every action it proposes is routed through EACH account's own
risk manager (``RiskManager.approve_amend``), so each account carrying the
package decides inside its own bounds and drawdown limits.

This module holds the parts that are pure functions, so the policy is arguable
in tests rather than against a live position:

* :class:`LiveReviewIntent` — what the review asks for, once per package.
* :class:`AmendAccountView` — what ONE account's leg looks like right now.
* :class:`AmendVerdict` — ``approve`` / ``clip`` / ``refuse`` with a reason.
* :func:`decide_amend` — the decision, given the account-owned facts the
  RiskManager supplies (mode, daily-DD switch state, the account's own
  ``min_buffer_atr``).
* :func:`apply_mode_for` — reads ``config/live_trade_review.yaml``.
* :func:`floor_blocks` — the per-leg ``sl_floor`` the order monitor and the
  prop trail respect, so an amended leg is never loosened by the next trail.

Nothing here writes ``mode:``, sets ``execution: shadow``, halts anything,
closes a position or adds risk. A refusal is per account and per intent.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

ACTIONS = ("tighten_sl", "flag", "no_action")
#: The verdict set (registered with collapsed-state-guard). ``could_not_look``
#: is NEITHER approve nor refuse: a venue stop, mark, ATR, leg stop or position
#: read failed, so nothing is applied, the next cycle retries, and ONE flag is
#: raised after :data:`COULD_NOT_LOOK_FLAG_AFTER` consecutive cycles (Prime
#: Directive rule 7: no halting, a red flag that keeps trying).
V_APPROVE = "approve"
V_CLIP = "clip"
V_REFUSE = "refuse"
V_COULD_NOT_LOOK = "could_not_look"
VERDICTS = (V_APPROVE, V_CLIP, V_REFUSE, V_COULD_NOT_LOOK)
COULD_NOT_LOOK_FLAG_AFTER = 3
APPLY_MODES = ("off", "recommend", "apply")
DEFAULT_APPLY_MODE = "recommend"
DEFAULT_MIN_BUFFER_ATR = 1.0

#: Provenance stamped on every leg the apply path moves (design § 4).
PROVENANCE = "live_review_mandate"
#: The mandate the operator may grant (design § 4; NOT written by this module).
MANDATE_ID = "MD-LIVE-TIGHTEN-SL"

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "live_trade_review.yaml"

# Refusal reasons. Stable strings: tests, the dry-run CLI and the review row's
# ``account_reads.evidence`` all carry them.
R_NOT_TIGHTEN = "intent_not_tighten_sl"
R_BAD_INPUT = "bad_input"
R_COULD_NOT_LOOK = "could_not_look"
R_WRONG_SIDE = "wrong_side_of_mark"
R_LOOSENS = "would_loosen"
R_ALREADY = "already_at_or_tighter"
R_NOISE_FLOOR = "inside_noise_floor"
R_RATE = "one_amend_per_package_per_bar"
R_DRY = "account_mode_dry_run"
R_SHADOW = "strategy_execution_shadow"
R_NO_PATH = "no_amend_path"
R_APPLY_OFF = "apply_mode_off"
R_MANDATE = "mandate_precondition"

#: What a tighten rests on (LTR-JUDGEMENT-APPLY, operator 2026-10-26, popup
#: verbatim "Claude's judgement applies (Recommended)": "Drop the n>=20 clause.
#: When the table is thin, Claude's call applies, logged as 'judgement' with a
#: confidence; the table is used when it's there."). ``table``: the LTR-0 cell
#: is ``measured`` and its EV bounds hold. ``judgement``: the cell is
#: ``insufficient_n`` and the reviewer's call applies, with a confidence in
#: [0, 1] and a reason, graded later against the realised outcome (LTR-5).
BASIS_TABLE = "table"
BASIS_JUDGEMENT = "judgement"
BASES = (BASIS_TABLE, BASIS_JUDGEMENT)
#: Operator Q1 apply bound: a table-backed tighten may cost at most 0.25 R of EV.
TABLE_EV_BOUND_R = -0.25


@dataclass(frozen=True)
class LiveReviewIntent:
    """One review's ask for one order package. Package-level by construction:
    it names no account, no size and no risk budget."""

    order_package_id: str
    action: str                      # tighten_sl | flag | no_action
    direction: str                   # long | short (the package's)
    review_id: str
    new_sl: Optional[float] = None
    packet_sha: Optional[str] = None
    evidence_path: Optional[str] = None
    expected_cost_r: Optional[float] = None   # ev_delta_r from the priced table (negative = a cost)
    mark: Optional[float] = None              # the price the noise floor is measured from
    atr: Optional[float] = None               # the leg's ATR (price units)
    bar_ts: Optional[str] = None              # the closed bar this intent was made on
    min_buffer_atr: float = DEFAULT_MIN_BUFFER_ATR
    mandate: Optional[str] = None
    basis: Optional[str] = None               # table | judgement (BASES); None = not stated
    confidence: Optional[float] = None        # judgement basis: the reviewer's confidence in [0, 1]
    reason: Optional[str] = None              # judgement basis: why, in one line
    mechanics_verdict: Optional[str] = None   # the review row's mechanics.verdict
    worst_case_delta_r: Optional[float] = None  # table basis: tighten worst - hold worst

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AmendAccountView:
    """One account's leg of the package, as read now. ``None`` = we could not
    look (never a fabricated 0)."""

    account_id: str
    account_class: Optional[str] = None   # bybit | prop_vm | phone | alpaca | other
    strategy_execution: str = "live"      # config/strategies.yaml::execution for this leg
    leg_sl: Optional[float] = None        # the leg's current stop (journal / ticket)
    venue_sl: Optional[float] = None      # the resting stop at the venue, when read
    last_amend_bar: Optional[str] = None  # bar_ts of this account's last review amend on the package
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AmendVerdict:
    account_id: str
    verdict: str                 # approve | clip | refuse | could_not_look
    level: Optional[float]       # the level this account may apply (None unless approve/clip)
    reason: str

    @property
    def ok(self) -> bool:
        return self.verdict in (V_APPROVE, V_CLIP)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def is_looser(direction: str, new_sl: float, current: float, tol: float = 1e-9) -> bool:
    """True when ``new_sl`` moves the stop AWAY from price relative to ``current``."""
    return new_sl > current + tol if direction == "short" else new_sl < current - tol


def is_tighter(direction: str, new_sl: float, current: float, tol: float = 1e-9) -> bool:
    return new_sl < current - tol if direction == "short" else new_sl > current + tol


def floor_level(direction: str, mark: float, atr: float, buffer_atr: float) -> float:
    """The tightest stop the noise floor allows: ``buffer_atr`` x ATR beyond the mark."""
    d = buffer_atr * atr
    return mark + d if direction == "short" else mark - d


def decide_amend(intent: LiveReviewIntent, view: AmendAccountView, *,
                 dry_run: bool,
                 account_min_buffer_atr: Optional[float] = None) -> AmendVerdict:
    """The per-account decision. Pure. The noise floor is the LARGER of the
    intent's and the account's own ``min_buffer_atr`` (an account may only be
    stricter).

    The daily-DD switch does NOT refuse a tighten (manager decision
    2026-10-25, desk design § 3.0): a tighten only reduces risk, and the
    operator's switch refuses NEW ENTRIES while keeping open positions
    protected -- ``RiskManager.evaluate(..., opening=False)`` semantics."""
    aid = view.account_id

    def refuse(reason: str) -> AmendVerdict:
        return AmendVerdict(aid, V_REFUSE, None, reason)

    def could_not_look(reason: str) -> AmendVerdict:
        return AmendVerdict(aid, V_COULD_NOT_LOOK, None, reason)

    if intent.action != "tighten_sl":
        return refuse(R_NOT_TIGHTEN)
    direction = str(intent.direction or "").lower()
    new_sl = _f(intent.new_sl)
    if direction not in ("long", "short"):
        return refuse(R_BAD_INPUT)
    if new_sl is None:
        # A probe carries no level; it is derived from mark + ATR. When those
        # reads failed there is no level BECAUSE we could not look -- that is
        # could_not_look (retried), not bad_input. An explicit level that did
        # not parse is genuinely malformed.
        missing = [n for n, v in (("mark", _f(intent.mark)), ("atr", _f(intent.atr))) if v is None]
        if intent.new_sl is None and missing:
            return could_not_look(f"{R_COULD_NOT_LOOK}:{','.join(missing)}")
        return refuse(R_BAD_INPUT)
    # The strategy's own execution gate: a shadow leg sends no live order, so
    # the review takes no action on it either.
    if str(view.strategy_execution or "live").lower() == "shadow":
        return refuse(R_SHADOW)
    if dry_run:
        return refuse(R_DRY)
    mark, atr, cur = _f(intent.mark), _f(intent.atr), _f(view.leg_sl)
    if mark is None or atr is None or cur is None:
        missing = [n for n, v in (("mark", mark), ("atr", atr), ("leg_sl", cur)) if v is None]
        return could_not_look(f"{R_COULD_NOT_LOOK}:{','.join(missing)}")
    # At most one amend per package per closed bar, per account.
    if intent.bar_ts and view.last_amend_bar and str(view.last_amend_bar) == str(intent.bar_ts):
        return refuse(R_RATE)
    # A short's stop at/below the mark (a long's at/above) fires at once.
    if (direction == "short" and new_sl <= mark) or (direction == "long" and new_sl >= mark):
        return refuse(R_WRONG_SIDE)
    # Tighten only, against the leg's journal stop AND the resting venue stop.
    refs = [cur] + ([_f(view.venue_sl)] if _f(view.venue_sl) is not None else [])
    for ref in refs:
        if is_looser(direction, new_sl, ref):
            return refuse(R_LOOSENS)
    if not all(is_tighter(direction, new_sl, ref) for ref in refs):
        return refuse(R_ALREADY)
    buf = max(float(intent.min_buffer_atr or 0.0), float(account_min_buffer_atr or 0.0))
    floor = floor_level(direction, mark, atr, buf)
    inside = new_sl < floor if direction == "short" else new_sl > floor
    if not inside:
        return AmendVerdict(aid, V_APPROVE, new_sl, "within_bounds")
    # Clip back to the noise floor when that is still a real tighten for THIS
    # account; otherwise there is nothing this account may do.
    if all(is_tighter(direction, floor, ref) for ref in refs):
        return AmendVerdict(aid, V_CLIP, floor,
                            f"clipped_to_noise_floor:{buf:g}xATR")
    return refuse(R_NOISE_FLOOR)


def mandate_precondition(intent: LiveReviewIntent) -> Optional[str]:
    """The package-level clauses of ``MD-LIVE-TIGHTEN-SL`` that no account's
    risk manager can see. Pure. Returns None when they hold, else a refusal
    reason ``mandate_precondition:<clause>``. Checked only before an EXECUTE;
    the per-account guardrails (tighten-only, noise floor, one amend per bar,
    could_not_look) stay in :func:`decide_amend`, unchanged.

    * ``mechanics_verdict`` must be ``match`` -- no exit judgment on a broken trade;
    * ``basis: table`` -- ``expected_cost_r`` >= -0.25 R and ``worst_case_delta_r`` > 0;
    * ``basis: judgement`` -- a confidence in [0, 1] and a stated reason
      (the n >= 20 clause was dropped by the operator on 2026-10-26)."""
    def bad(clause: str) -> str:
        return f"{R_MANDATE}:{clause}"

    if intent.action != "tighten_sl":
        return bad("action_not_tighten_sl")
    if str(intent.mechanics_verdict or "").lower() != "match":
        return bad(f"mechanics_{intent.mechanics_verdict or 'unstated'}")
    basis = str(intent.basis or "").lower()
    if basis == BASIS_TABLE:
        ev, worst = intent.expected_cost_r, intent.worst_case_delta_r
        if not isinstance(ev, (int, float)) or not math.isfinite(ev) or ev < TABLE_EV_BOUND_R:
            return bad("table_ev_outside_bound")
        if not isinstance(worst, (int, float)) or not math.isfinite(worst) or worst <= 0:
            return bad("table_worst_case_not_improved")
        return None
    if basis == BASIS_JUDGEMENT:
        c = intent.confidence
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(c) or not 0.0 <= c <= 1.0:
            return bad("judgement_confidence_missing")
        if not str(intent.reason or "").strip():
            return bad("judgement_reason_missing")
        return None
    return bad("basis_unstated")


# -- config -------------------------------------------------------------------

def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """``config/live_trade_review.yaml``; an absent or unreadable file reads as
    the defaults (``recommend``), never as ``apply``."""
    import yaml

    p = Path(path) if path else CONFIG_PATH
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except (OSError, ValueError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def apply_mode_for(account_id: str, cfg: Optional[Mapping[str, Any]] = None) -> str:
    """The effective ``apply_mode`` for one account: the per-account override
    if declared, else the global one, else ``recommend``. An unknown spelling
    reads as ``recommend`` (the safe middle: compute, never apply)."""
    cfg = cfg if cfg is not None else load_config()
    over = ((cfg.get("accounts") or {}).get(account_id) or {}) if isinstance(cfg.get("accounts"), Mapping) else {}
    mode = over.get("apply_mode") if isinstance(over, Mapping) and over.get("apply_mode") else cfg.get("apply_mode")
    mode = str(mode or DEFAULT_APPLY_MODE).strip().lower()
    return mode if mode in APPLY_MODES else DEFAULT_APPLY_MODE


def min_buffer_atr_from(cfg: Optional[Mapping[str, Any]] = None) -> float:
    cfg = cfg if cfg is not None else load_config()
    v = _f(cfg.get("min_buffer_atr"))
    return v if v is not None else DEFAULT_MIN_BUFFER_ATR


# -- per-leg floor (respected by the order monitor and the prop trail) --------

def sl_floor_from(notes_or_meta: Any) -> Optional[float]:
    """The ``sl_floor`` level a leg carries in ``trades.notes`` or a prop
    ticket's ``meta``; None when absent or unreadable."""
    import json

    m = notes_or_meta
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except (TypeError, ValueError):
            return None
    if not isinstance(m, Mapping):
        return None
    fl = m.get("sl_floor")
    if isinstance(fl, Mapping):
        return _f(fl.get("level"))
    return _f(fl)


def floor_blocks(direction: Any, candidate_sl: Any, floor: Optional[float]) -> bool:
    """True when ``candidate_sl`` would LOOSEN a leg past its ``sl_floor``."""
    c, fl = _f(candidate_sl), _f(floor)
    d = str(direction or "").lower()
    if c is None or fl is None or d not in ("long", "short"):
        return False
    return is_looser(d, c, fl)


def account_read(verdict: AmendVerdict, *, applied: Optional[bool] = None) -> str:
    """Map a verdict onto the review row's ``account_reads.read`` vocabulary
    (``comms/schema/live_review.schema.json``)."""
    if verdict.verdict in (V_APPROVE, V_CLIP):
        return "would_apply"
    if verdict.verdict == V_COULD_NOT_LOOK:
        return "unknown"
    if verdict.reason in (R_SHADOW, R_ALREADY, R_NOT_TIGHTEN, R_NO_PATH, R_APPLY_OFF):
        return "no_action"
    return "refused_by_account_risk"
