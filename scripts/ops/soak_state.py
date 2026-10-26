#!/usr/bin/env python3
# wiring: CONTRACTS docs/claude/work/SOAKS.json (committed, guarded by
#   scripts/ci/check_soak_contracts.py) -> STATE soak_states() computed LIVE from
#   the contracts + the journal DB (trades, order_packages, prop_tickets/prop_fills).
#   Consumers: the brief (BRIEF-FIX), WORK-SYSTEM's /api/bot/work/report and its
#   Telegram attention watch, and (via the committed brief snapshot)
#   mandate_resolver's MD-S1-CUT-ON-STAGE0-FAIL soak clause. Nobody else computes
#   soak state; state is NEVER written into the committed file.
"""THE SOAK CONTRACT — a soak is a MECHANICAL verification, passed on 1–2 clean trades.

Operator, 2026-10-15 (binding, verbatim): "A soak is a mechanical verification
that was already proven in backtesting, and nothing needs to soak for more than
one or two trades."

So a Stage-1 soak asks ONE question — do the mechanics work for this leg? — and
it is answered by the first ``n_needed`` (1 or 2) CLEAN trades. Edge is decided
OFFLINE at Stage 0 and nowhere else. Realized cost (R3) and live-vs-backtest are
ONGOING MONITORING (the Gate-2 demotion signal and the underperformer first
step) — they are NOT soak exit criteria. A soak has NO calendar: no end date, no
duration, no expected rate. A leg with no signal yet is ``awaiting_first_trade``,
never failing.

A CONTRACT (one row of ``docs/claude/work/SOAKS.json``) carries:
  id, leg, account, kind      what is soaking (kind: stage1 | shadow)
  started                     when it went on the soak roster / shadow (from git)
  verifies, metric            the mechanics question and the event counted
  n_needed                    1 or 2 clean trades (MAX_N_NEEDED). Never more.
  checklist                   the mechanical items EVERY counted trade must clear
                              (STAGE1_CHECKLIST / SHADOW_CHECKLIST, exactly)
  pass_rule, fail_rule        prose of the rule this module applies
  monitoring                  where cost / live-vs-backtest live instead
  design                      ``mechanical`` | ``not_soaking`` (disabled /
                              unrostered shadow: a recorded decision, not a soak)
  sources (optional)          extra evidence streams; ``kind: prop_live`` =
                              the leg's LIVE prop trades count as soak trades
                              (operator amendment, 2026-10-15)
  disposition (optional)      a graded verdict with evidence (PASS / FAIL /
                              REFUSE / KILLED / NEEDS_DATA)

REFUSED (``contract_problems``): ``n_needed`` > 2 or < 1, a checklist that is
not the canonical one, and ANY calendar/accrual field — ``end_date``,
``duration_days``, ``expected_per_week``, ``power`` — because a soak that waits
on a calendar or a sample is the design the operator rejected.

A CLEAN STAGE-1 TRADE (``grade_trade``) clears every checklist item:
  signal_fired             the trade carries its order package (signal -> package)
  order_size_side          side is long/short, size > 0, entry filled; matches the
                           package's side when the package is known
  bracket_real_at_venue    a real SL and a real TP (TP within MAX_TP_R of risk —
                           a 50R sentinel is not a TP, TP doctrine) and the bracket
                           RESTED: the venue order ids are stamped where the venue
                           path stamps them; a ``naked_rearm`` protection repair
                           (the position was found unprotected) is a FAULT
  management_no_fault      no protection fault during the trade; trail/amend is
                           observed where the journal shows it, and a trade that
                           exited before any management condition is not a fault
  exit_journaled           closed with a TP / SL / strategy exit reason
                           (CLEAN_EXITS), an exit price and a close time
  fill_and_fees            pnl and the fee are recorded (provenance carried: on
                           2026-10-15 ~99.6% of closes are ``cost_source:
                           estimate`` — a known, separate provenance gap)
Rows that are not a trade decision are NEUTRAL — neither clean nor a fault:
intent-layer reduce bookkeeping rows, operator/manual closes, and rows a
reconcile marked ``superseded`` (duplicates).
Any other close (reconciler_*, exchange_flat_reconciled, stuck_*, netting_*,
orphan/coverage closes, or a null reason) is a MECHANICAL FAULT.

STATE (``evaluate`` / ``soak_states()``), computed per call, never stored —
the graded (non-neutral) trades in time order since ``started``:
  passed               the run of clean trades since the LAST fault reached
                       n_needed (a fault followed by n_needed clean trades is
                       "fixed and re-soaked")
  mechanical_fail      the most recent graded trade is a fault — fix it, then
                       re-soak (the next clean trades flip it to passed)
  in_progress          some clean trades since the last fault, fewer than n_needed
  awaiting_first_trade no graded trade yet. NOT failing, no deadline.
  unknown              the journal could not be read (or is not the live one).
                       NEVER folded into awaiting or passed.
A ``PASS`` disposition (a session graded it, evidence cited) reads ``passed``.
KILLED / REFUSE / FAIL / NEEDS_DATA dispositions are quiet while in force.

SHADOW soaks place no order, so their checklist is what shadow can prove: the
signal fires, the package is complete (side, entry, real SL, real TP), and every
rostered account sizes it (>0) and records it DRY (``dry_run_no_order_placed``).
A passed shadow soak is NOT a Stage-1 soak: a promotion still needs the leg
``execution: live`` on a Stage-1 roster and its own passed Stage-1 soak.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import touch_record  # noqa: E402  (DESK-12-SANDBOX: the touched/untouched split)

CONTRACTS = REPO / "docs/claude/work/SOAKS.json"
STAGE1_ACCOUNTS = ("bybit_1", "alpaca_paper")
MAX_N_NEEDED = 2        # operator, 2026-10-15: "nothing needs to soak for more than one or two trades"
#: One clean trade passes (manager 2026-10-15, on the operator's "1-2 trades":
#: SOL passed on its one clean tradeify_1 trade). A contract may ask for 2.
N_DEFAULT = 1
STAGE1_CHECKLIST = ("signal_fired", "order_size_side", "bracket_real_at_venue",
                    "management_no_fault", "exit_journaled", "fill_and_fees")
SHADOW_CHECKLIST = ("signal_fired", "package_complete", "sized_and_routed_dry")
#: The prop checklist items that are the LEG's own mechanics. The rest
#: (bracket_real_at_venue = the adapter's venue read, exit_journaled,
#: fill_recorded) are the prop ACCOUNT ADAPTER's, and a fault there is recorded
#: against the adapter, not the leg's soak.
PROP_LEG_ITEMS = ("signal_fired", "order_size_side", "ticket_bracket_real")
PROP_CHECKLIST = ("signal_fired", "order_size_side", "ticket_bracket_real", "bracket_real_at_venue",
                  "management_no_fault", "exit_journaled", "fill_recorded")
#: Calendar / accrual fields of the retired design. A contract carrying any of
#: them is refused — a soak never waits on a date or a sample.
BANNED_FIELDS = ("end_date", "duration_days", "expected_per_week", "power")
DESIGNS = ("mechanical", "not_soaking")
#: A pass/fail rule naming any of these is a STATISTICAL exit — the retired design
#: (R3 cost fidelity, live-vs-backtest, a CI, a sample floor). Refused.
STATISTICAL_EXIT = re.compile(
    r"realized cost|cost[- _]fidelity|\bR3\b|slippage|\bbps\b|live[- _]vs[- _]backtest|\bCI ?95\b|"
    r"\bn ?(>=|≥|=) ?\d|cost_tolerance", re.I)
#: Bracket / strategy exits (src/analysis/paper_record_classifier.py
#: _CLEAN_EXIT_REASONS, plus ``giveback_stop`` — the M20 giveback lever, the same
#: kind of in-strategy exit as ``stale_stop``).
CLEAN_EXITS = frozenset({"sl", "tp", "sl_cross", "tp_cross", "exit_head", "stale_stop",
                         "giveback_stop"})
#: Not a trade decision of the leg: graded neither way.
NEUTRAL_EXITS = frozenset({"intent_reduce", "intent_reduce_executed", "manual",
                           "operator_flatten_reconciled"})
#: A TP further than this many R from entry is a sentinel, not a prediction
#: (TP doctrine: ``tp_r: 50.0`` is non-compliant).
MAX_TP_R = 20.0
#: A protection repair of this kind means the position was found UNPROTECTED.
FAULT_REPAIR_KINDS = frozenset({"naked_rearm"})
#: Venue paths that stamp the SL/TP venue order ids on the trade row. Elsewhere
#: (alpaca: one ``order_class: bracket`` submit, alpaca_client.py; ib) the legs
#: are not stamped, so "rested" is read from the ABSENCE of a naked repair.
STAMPING_ACCOUNTS_PREFIX = ("bybit",)
#: A journal whose newest row is older than this is not the live journal (a test
#: fixture, a stale copy): reading nothing from it would manufacture
#: "awaiting_first_trade". MEASURED 2026-10-04: a pytest-left trade_journal.db at
#: the repo root graded 32 of 48 soaks dead until this gate existed.
JOURNAL_FRESH_DAYS = 3
STATES = ("passed", "in_progress", "awaiting_first_trade", "mechanical_fail", "unknown")
DISPOSITION_VERDICTS = ("PASS", "FAIL", "REFUSE", "KILLED", "NEEDS_DATA")
REQUIRED = ("id", "leg", "account", "kind", "verifies", "metric", "n_needed", "checklist",
            "started", "pass_rule", "fail_rule", "monitoring", "design")
MONITORING = ("ONGOING, not soak exit criteria: realized cost vs the Stage-0 model "
              "(R3, scripts/ops/r3_cost_fidelity.py) and live-vs-backtest "
              "(scripts/research/live_vs_backtest.py) feed the Gate-2 demotion signal "
              "and the underperformer first step")


# ── contracts ───────────────────────────────────────────────────────────────
def checklist_for(kind: str) -> tuple:
    return SHADOW_CHECKLIST if kind == "shadow" else STAGE1_CHECKLIST


def make_contract(*, kind: str, leg: str, account: str, started: str,
                  enabled: bool = True, rostered: bool = True,
                  n_needed: int = N_DEFAULT) -> Dict[str, Any]:
    """One contract. ``started`` is ISO (a ``<=`` floor is stripped)."""
    started = started.lstrip("<=")
    if kind == "stage1":
        metric = f"clean closed trades on {account}/{leg} (each = one entry + one journaled exit)"
        verifies = ("live MECHANICS: the signal fires, the order is placed with the right size "
                    "and side, a real SL and TP rest at the venue, management works, the exit is "
                    "journaled with a reason, and the fill and fees are recorded")
        pass_rule = (f"{n_needed} clean trade(s) since the last mechanical fault, each clearing "
                     "every checklist item")
        fail_rule = ("the most recent graded trade is a mechanical fault (a checklist item fails, "
                     "or a reconciler / watchdog / orphan close) -> fix, then re-soak")
    else:
        metric = f"shadow order packages for {leg} (any rostered account)"
        verifies = ("shadow MECHANICS: the signal fires, the package is complete (side, entry, "
                    "real SL and TP), and every rostered account sizes it and records it DRY")
        pass_rule = f"{n_needed} complete shadow package(s), each clearing every checklist item"
        fail_rule = "the most recent package is incomplete or not recorded dry -> fix, then re-soak"
    c: Dict[str, Any] = {
        "id": f"SOAK-{kind}-{account}-{leg}" if kind == "stage1" else f"SOAK-shadow-{leg}",
        "leg": leg, "account": account, "kind": kind, "verifies": verifies, "metric": metric,
        "n_needed": n_needed, "checklist": list(checklist_for(kind)), "started": started,
        "pass_rule": pass_rule, "fail_rule": fail_rule, "monitoring": MONITORING,
        "design": "mechanical",
    }
    if kind == "shadow" and (not enabled or not rostered):
        c.update(design="not_soaking",
                 recommended_fix=("enabled: false" if not enabled else "on no account roster")
                 + " — nothing runs it; retire the strategy block or re-roster it with a fresh contract")
    return c


def load_contracts(path: Path = CONTRACTS) -> List[Dict[str, Any]]:
    return json.loads(path.read_text()).get("soaks") or []


def _n_ok(n: Any) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= MAX_N_NEEDED


def contract_problems(c: Dict[str, Any]) -> List[str]:
    """Why a contract is not a mechanical definition of done. Empty = admissible."""
    p = [f"missing `{k}`" for k in REQUIRED if k not in c]
    for k in BANNED_FIELDS:
        if k in c:
            p.append(f"carries `{k}` — a soak has no calendar and waits on no sample "
                     f"(operator 2026-10-15); remove it")
    for k in ("pass_rule", "fail_rule"):
        if STATISTICAL_EXIT.search(str(c.get(k) or "")):
            p.append(f"`{k}` names a cost / live-vs-backtest / sample criterion — those are ONGOING "
                     "MONITORING, never a soak's exit (OPERATING-PLAN § 2 'The soak is MECHANICAL')")
    if "n_needed" in c and not _n_ok(c.get("n_needed")):
        p.append(f"n_needed must be 1 or 2 (got {c.get('n_needed')!r}) — nothing soaks for more "
                 "than one or two trades")
    if "checklist" in c and list(c.get("checklist") or []) != list(checklist_for(c.get("kind"))):
        p.append(f"checklist must be exactly {list(checklist_for(c.get('kind')))}")
    if c.get("kind") not in ("stage1", "shadow"):
        p.append(f"kind must be stage1|shadow, got {c.get('kind')!r}")
    if c.get("design") not in DESIGNS:
        p.append(f"design must be one of {DESIGNS}, got {c.get('design')!r}")
    if c.get("design") == "not_soaking" and not str(c.get("recommended_fix") or "").strip():
        p.append("design not_soaking needs a recommended_fix — say what to change")
    try:
        date.fromisoformat(str(c.get("started"))[:10])
    except ValueError:
        p.append("started is not an ISO date")
    for i, s in enumerate(c.get("sources") or []):
        if not isinstance(s, dict):
            p.append(f"sources[{i}] must be an object")
            continue
        for k in BANNED_FIELDS:
            if k in s:
                p.append(f"sources[{i}] carries `{k}` — a soak source has no calendar either")
        if "n_needed" in s and not _n_ok(s.get("n_needed")):
            p.append(f"sources[{i}].n_needed must be 1 or 2")
        if STATISTICAL_EXIT.search(str(s.get("pass_rule") or "")):
            p.append(f"sources[{i}].pass_rule names a cost / live-vs-backtest / sample criterion — "
                     "monitoring, never a soak's exit")
    d = c.get("disposition")
    if d is not None:
        if not isinstance(d, dict):
            p.append("disposition must be an object")
        else:
            if d.get("verdict") not in DISPOSITION_VERDICTS:
                p.append(f"disposition.verdict must be one of {DISPOSITION_VERDICTS}")
            for k in ("reason", "decided_at"):
                if not str(d.get(k) or "").strip():
                    p.append(f"disposition needs `{k}`")
            if not d.get("evidence"):
                p.append("disposition needs `evidence` (paths/refs the verdict was read from)")
            for k in ("decided_at", "until"):
                if d.get(k):
                    try:
                        date.fromisoformat(str(d[k]))
                    except ValueError:
                        p.append(f"disposition.{k} not an ISO date")
            if d.get("verdict") == "NEEDS_DATA" and not (d.get("until") and d.get("missing")):
                p.append("NEEDS_DATA disposition needs `until` (dated) and `missing` (the exact quantity)")
            if d.get("verdict") == "PASS" and not d.get("trades"):
                p.append("PASS disposition needs `trades` — the clean trades (journal ids / "
                         "order-package ids) the pass was read from")
    return p


# ── grading one trade / one package ─────────────────────────────────────────
def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _tp_real(entry: Any, sl: Any, tp: Any) -> Optional[str]:
    """None when (sl, tp) is a real bracket around ``entry``; else why not."""
    e, s, t = _num(entry), _num(sl), _num(tp)
    if s is None or t is None:
        return "SL or TP missing"
    if e is None or e == s:
        return None if e is None else "SL equals entry"
    r = abs(t - e) / abs(e - s)
    return None if r <= MAX_TP_R else f"TP {r:.0f}R from entry is a sentinel, not a prediction"


def _notes(t: Dict[str, Any]) -> Dict[str, Any]:
    try:
        n = json.loads(t.get("notes") or "{}")
        return n if isinstance(n, dict) else {}
    except (TypeError, ValueError):
        return {}


def at_entry_bracket(t: Dict[str, Any], package: Optional[Dict[str, Any]]) -> tuple:
    """(entry, sl, tp) as placed: the package's exit_plan stop/final, else the
    package's sl/tp, else the trade row's."""
    pk = package or {}
    plan: Dict[str, Any] = {}
    try:
        plan = json.loads(pk.get("exit_plan") or "{}") if isinstance(pk.get("exit_plan"), str) \
            else (pk.get("exit_plan") or {})
    except (TypeError, ValueError):
        plan = {}
    entry = pk.get("entry") if pk.get("entry") is not None else t.get("entry_price")
    sl = ((plan.get("stop") or {}).get("price") if isinstance(plan, dict) else None)
    tp = ((plan.get("final") or {}).get("price") if isinstance(plan, dict) else None)
    sl = sl if sl is not None else (pk.get("sl") if pk.get("sl") is not None else t.get("stop_loss"))
    tp = tp if tp is not None else (pk.get("tp") if pk.get("tp") is not None else t.get("take_profit_1"))
    return entry, sl, tp


def grade_trade(t: Dict[str, Any], package: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pure: one CLOSED journal ``trades`` row -> ``{clean, fault, items}``.
    ``clean`` is None for a NEUTRAL row (not a trade decision of the leg)."""
    reason = t.get("exit_reason")
    items: Dict[str, str] = {}
    if reason in NEUTRAL_EXITS or t.get("reconcile_status") == "superseded":
        return {"id": t.get("id"), "clean": None, "fault": None,
                "items": {"neutral": f"exit_reason={reason!r} reconcile={t.get('reconcile_status')!r}"}}
    items["signal_fired"] = "ok" if t.get("order_package_id") else "fault: no order package"
    side_ok = t.get("direction") in ("long", "short")
    size_ok = (_num(t.get("position_size")) or 0) > 0 and (_num(t.get("entry_price")) or 0) > 0
    pk_side = (package or {}).get("direction")
    if not (side_ok and size_ok):
        items["order_size_side"] = "fault: side/size/entry missing"
    elif pk_side and pk_side != t.get("direction"):
        items["order_size_side"] = f"fault: side {t.get('direction')} != package {pk_side}"
    else:
        items["order_size_side"] = "ok"
    # The bracket AT ENTRY is the package's exit_plan: the trade row's stop_loss
    # AND the package's `sl` are the CURRENT (possibly trailed) stop, and a stop
    # trailed past entry makes any TP read as a 100R+ "sentinel" (MEASURED
    # 2026-10-15: ada_pullback_2h #5946, package sl trailed above a long's entry).
    e0, sl0, tp0 = at_entry_bracket(t, package)
    why = _tp_real(e0, sl0, tp0)
    repair = t.get("protection_repair_last_kind") if t.get("protection_repairs") else None
    if why:
        items["bracket_real_at_venue"] = f"fault: {why}"
    elif repair in FAULT_REPAIR_KINDS:
        items["bracket_real_at_venue"] = f"fault: protection repair {repair} (position found unprotected)"
    elif str(t.get("account_id") or "").startswith(STAMPING_ACCOUNTS_PREFIX):
        items["bracket_real_at_venue"] = ("ok" if t.get("sl_order_id") and t.get("tp_order_id")
                                          else "fault: venue SL/TP order ids not stamped")
    else:
        items["bracket_real_at_venue"] = "ok (venue leg ids not stamped on this path; no naked repair)"
    cur = _num(t.get("stop_loss"))
    if t.get("protection_repairs") and repair in FAULT_REPAIR_KINDS:
        items["management_no_fault"] = f"fault: {repair}"
    elif cur is not None and _num(sl0) is not None and abs(cur - _num(sl0)) > 1e-9 * max(1.0, abs(cur)):
        items["management_no_fault"] = "ok (stop trailed/amended at venue)"
    else:
        items["management_no_fault"] = "ok (not exercised: exited before any management condition)"
    if reason in CLEAN_EXITS and t.get("exit_price") is not None and t.get("closed_at"):
        items["exit_journaled"] = f"ok ({reason})"
    else:
        items["exit_journaled"] = f"fault: exit_reason={reason!r}" + (
            "" if t.get("exit_price") is not None else ", no exit price")
    fee = t.get("fee_taker_usd") if t.get("fee_taker_usd") is not None else t.get("fee_maker_usd")
    if t.get("pnl") is not None and fee is not None:
        items["fill_and_fees"] = f"ok (cost_source={t.get('cost_source')})"
    else:
        items["fill_and_fees"] = "fault: pnl or fee not recorded"
    faults = [f"{k}: {v[7:]}" for k, v in items.items() if v.startswith("fault")]
    # DESK-12-SANDBOX: a leg whose stop a desk / LTR / operator amend moved has an exit that is no
    # longer the leg's own. It is graded and shown, but evaluate() never counts it as a clean trade.
    tch = touch_record.touches(t)
    return {"id": t.get("id"), "clean": not faults, "fault": "; ".join(faults) or None, "items": items,
            "touched": bool(tch), "touches": tch}


def grade_shadow_package(p: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: one shadow ``order_packages`` row + its per-account trade rows.
    ``clean`` None = not a shadow decision (no account row recorded it dry)."""
    rows = list(rows)
    dry = [r for r in rows if _notes(r).get("is_dry") is True]
    if not dry:
        return {"id": p.get("order_package_id"), "clean": None, "fault": None,
                "items": {"neutral": "no dry account row (a noop / refusal, not a shadow decision)"}}
    items = {"signal_fired": "ok"}
    why = (None if p.get("direction") in ("long", "short") else "no side") or \
        _tp_real(p.get("entry"), p.get("sl"), p.get("tp"))
    items["package_complete"] = "ok" if not why else f"fault: {why}"
    bad = [r.get("account_id") for r in dry if not (_num(r.get("position_size")) or 0) > 0]
    items["sized_and_routed_dry"] = ("ok" if not bad else f"fault: unsized on {bad}")
    faults = [f"{k}: {v[7:]}" for k, v in items.items() if v.startswith("fault")]
    return {"id": p.get("order_package_id"), "clean": not faults, "fault": "; ".join(faults) or None,
            "items": items}


def grade_prop_signal(ticket_rows: List[Dict[str, Any]], fills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One prop SIGNAL (an order package fanned out as tickets to N prop accounts)
    -> clean when at least one account's fill clears PROP_CHECKLIST. A fault on one
    account's journaling path (e.g. an unpriced breakout_2 exit) is reported, but
    is that account path's defect, not the leg's. The prop journal has no fee
    column (prop fees are the firm's schedule), so ``fill_recorded`` asks for the
    exit price and time; the Bybit fee item is proven on the Bybit soak path."""
    per: List[Dict[str, Any]] = []
    for tk in ticket_rows:
        fs = [f for f in fills if f.get("ticket_id") == tk.get("ticket_id")]
        opened = next((f for f in fs if f.get("status") in ("open", "filled")), None)
        closed = next((f for f in fs if f.get("status") == "closed"), None)
        if closed is None:
            continue
        reason = str(closed.get("reason") or "")
        # Older (manual-bridge era) fills carry free text after the reason token:
        # "sl - closed Buy 3.00 @ ...". The leading token is the reason.
        token = re.match(r"[a-z_]*", reason.strip().lower()).group(0)
        items: Dict[str, str] = {"signal_fired": "ok" if tk.get("order_package_id") else "fault: no package"}
        ok_side = tk.get("direction") in ("long", "short") and (_num(tk.get("qty")) or 0) > 0
        items["order_size_side"] = "ok" if ok_side else "fault: side/qty missing"
        rest = opened or {}
        why = _tp_real(rest.get("entry_price"), rest.get("sl"), rest.get("tp")) if opened else \
            "no venue-read open fill (bracket at venue not observed)"
        items["bracket_real_at_venue"] = "ok" if not why else f"fault: {why}"
        moved = opened and _num(opened.get("sl")) is not None and _num(tk.get("sl")) is not None \
            and abs(_num(opened.get("sl")) - _num(tk.get("sl"))) > 1e-6 * max(1.0, abs(_num(tk.get("sl"))))
        items["management_no_fault"] = "ok (stop amended/trailed at venue)" if moved else \
            "ok (not exercised: exited before any management condition)"
        if token in ("manual", "operator"):
            per.append({"ticket": tk.get("ticket_id"), "account": tk.get("account_id"), "clean": None,
                        "fault": None, "items": {"neutral": "operator manual close"}})
            continue
        exit_ok = token in CLEAN_EXITS and closed.get("exit_price") is not None and closed.get("closed_at")
        items["exit_journaled"] = f"ok ({token})" if exit_ok else \
            f"fault: exit not journaled with a clean reason/price ({reason[:60]!r})"
        items["fill_recorded"] = ("ok (no fee column on the prop journal)"
                                  if closed.get("exit_price") is not None else "fault: no exit price")
        tk_why = _tp_real(tk.get("entry"), tk.get("sl"), tk.get("tp"))
        items["ticket_bracket_real"] = "ok" if not tk_why else f"fault: {tk_why}"
        faults = {k: v[7:] for k, v in items.items() if v.startswith("fault")}
        leg_faults = [f"{k}: {v}" for k, v in faults.items() if k in PROP_LEG_ITEMS]
        adapter_faults = [f"{k}: {v}" for k, v in faults.items() if k not in PROP_LEG_ITEMS]
        if leg_faults:
            per.append({"ticket": tk.get("ticket_id"), "account": tk.get("account_id"), "clean": False,
                        "fault": "; ".join(leg_faults), "items": items})
        elif adapter_faults:
            # The ACCOUNT'S ADAPTER failed (no venue read, exit not journaled, no
            # exit price) -- e.g. breakout_2's reconcile gap, fixed in #18413.
            # That is the adapter's defect, recorded against it, not the leg's:
            # neither clean nor a fault for the leg's soak (manager, 2026-10-15).
            per.append({"ticket": tk.get("ticket_id"), "account": tk.get("account_id"), "clean": None,
                        "fault": None, "adapter_fault": "; ".join(adapter_faults), "items": items})
        else:
            per.append({"ticket": tk.get("ticket_id"), "account": tk.get("account_id"), "clean": True,
                        "fault": None, "items": items})
    graded = [x for x in per if x["clean"] is not None]
    clean = any(x["clean"] for x in graded)
    out = {"id": (ticket_rows[0] if ticket_rows else {}).get("order_package_id"),
           "clean": (clean if graded else None),
           "fault": None if clean or not graded else "; ".join(x["fault"] for x in graded),
           "accounts": per}
    adapters = [f"{x['account']}: {x['adapter_fault']}" for x in per if x.get("adapter_fault")]
    if adapters:
        out["adapter_faults"] = adapters
    return out


def evaluate(graded: List[Dict[str, Any]], n_needed: int) -> Dict[str, Any]:
    """Pure: chronologically ordered grades -> the soak state (module docstring).

    Only UNTOUCHED trades count (design § 3.6): a desk/LTR-touched trade is reported in ``touched`` but is
    never one of the leg's clean trades and never its fault, because its exit is not the leg's own."""
    touched = [x for x in graded if x.get("clean") is not None and x.get("touched")]
    g = [x for x in graded if x.get("clean") is not None and not x.get("touched")]
    tid = [x["id"] for x in touched]
    suffix = f" ({len(touched)} desk/LTR-touched trade(s) excluded: {', '.join(str(i) for i in tid)})" if touched else ""
    if not g:
        return {"state": "awaiting_first_trade", "clean": [], "fault": None, "touched": tid,
                "progress": f"0/{n_needed} clean",
                "reason": "no graded trade yet — waiting, not failing" + suffix}
    last_fault = max((i for i, x in enumerate(g) if not x["clean"]), default=-1)
    run = g[last_fault + 1:]
    if last_fault == len(g) - 1:
        return {"state": "mechanical_fail", "clean": [], "fault": g[-1]["fault"], "fault_id": g[-1]["id"],
                "touched": tid, "progress": f"0/{n_needed} clean since fault",
                "reason": f"latest graded trade {g[-1]['id']} faulted: {g[-1]['fault']} — fix, then re-soak" + suffix}
    ids = [x["id"] for x in run[:n_needed]]
    if len(run) >= n_needed:
        return {"state": "passed", "clean": ids, "fault": None, "touched": tid,
                "progress": f"{n_needed}/{n_needed} clean",
                "reason": f"clean: {', '.join(str(i) for i in ids)}"
                          + (f" (after fault {g[last_fault]['id']})" if last_fault >= 0 else "") + suffix}
    return {"state": "in_progress", "clean": ids, "fault": None, "touched": tid,
            "progress": f"{len(run)}/{n_needed} clean",
            "reason": f"clean so far: {', '.join(str(i) for i in ids)}" + suffix}


# ── live state ──────────────────────────────────────────────────────────────
def _db_path() -> Optional[str]:
    try:
        sys.path.insert(0, str(REPO))
        from src.utils.paths import trade_journal_db_path  # noqa: PLC0415
        return trade_journal_db_path()
    except Exception:  # noqa: BLE001
        return None


def _rows(conn: sqlite3.Connection, sql: str, args: tuple) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() \
        is not None


def graded_for(conn: sqlite3.Connection, c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every graded event for a contract, oldest first (stage1 trades, shadow
    packages, plus any prop_live signals)."""
    out: List[tuple] = []
    if c["kind"] == "stage1":
        for t in _rows(conn, "SELECT * FROM trades WHERE account_id=? AND strategy_name=? "
                             "AND status='closed' AND COALESCE(is_backtest,0)=0 "
                             "AND datetime(closed_at) >= datetime(?)",
                       (c["account"], c["leg"], c["started"])):
            pk = _rows(conn, "SELECT * FROM order_packages WHERE order_package_id=?",
                       (t.get("order_package_id"),)) if t.get("order_package_id") else []
            out.append((str(t.get("closed_at")), grade_trade(t, pk[0] if pk else None)))
        if any((s or {}).get("kind") == "prop_live" for s in c.get("sources") or []) \
                and _has_table(conn, "prop_tickets") and _has_table(conn, "prop_fills"):
            from src.prop.exec_test_trades import exclude_exec_test
            tks = exclude_exec_test(_rows(conn, "SELECT * FROM prop_tickets WHERE strategy=?", (c["leg"],)))  # never a test trade
            by_pkg: Dict[str, List[Dict[str, Any]]] = {}
            for tk in tks:
                by_pkg.setdefault(str(tk.get("order_package_id")), []).append(tk)
            ids = tuple(tk["ticket_id"] for tk in tks)
            fills = _rows(conn, f"SELECT * FROM prop_fills WHERE ticket_id IN ({','.join('?' * len(ids))})",
                          ids) if ids else []
            for pkg, group in by_pkg.items():
                g = grade_prop_signal(group, fills)
                when = max((str(f.get("closed_at") or "") for f in fills
                            if f.get("ticket_id") in {x["ticket_id"] for x in group}), default="")
                out.append((when, dict(g, id=f"prop:{pkg}")))
    else:
        pk = _rows(conn, "SELECT * FROM order_packages WHERE strategy_name=? "
                         "AND datetime(created_at) >= datetime(?)", (c["leg"], c["started"]))
        for p in pk:
            rows = _rows(conn, "SELECT * FROM trades WHERE order_package_id=?", (p["order_package_id"],))
            out.append((str(p.get("created_at")), grade_shadow_package(p, rows)))
    return [g for _, g in sorted(out, key=lambda x: x[0])]


def _base_row(c: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": c["id"], "leg": c["leg"], "account": c["account"], "kind": c["kind"],
            "started": c["started"], "n_needed": c.get("n_needed"), "design": c.get("design"),
            "progress": None, "state": "unknown", "reason": ""}


def _disposition_holds(c: Dict[str, Any], today: date) -> bool:
    """True when a graded soak's disposition is still in force (no ``until``, or
    ``until`` not yet passed). An unreadable ``until`` holds NOTHING — it fails
    loud (the soak shows again) rather than hiding."""
    d = c.get("disposition")
    if not isinstance(d, dict) or d.get("verdict") not in DISPOSITION_VERDICTS:
        return False
    if not d.get("until"):
        return True
    try:
        return today <= date.fromisoformat(str(d["until"]))
    except ValueError:
        return False


def soak_states(today: Optional[date] = None, db_path: Optional[str] = None,
                contracts_path: Path = CONTRACTS) -> List[Dict[str, Any]]:
    """THE soak state computation. One row per contract:
    {id, leg, account, kind, state, started, n_needed, progress, reason, design}.
    ``state`` is one of STATES. A DB that cannot be opened makes every row
    ``unknown`` — never ``awaiting_first_trade``."""
    today = today or datetime.now(timezone.utc).date()
    contracts = load_contracts(contracts_path)
    path = db_path or _db_path()
    conn = None
    if path and Path(path).exists():
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            conn = None
    stale = None
    if conn is not None:
        try:
            newest = conn.execute("SELECT MAX(created_at) FROM order_packages").fetchone()[0]
            nd = datetime.fromisoformat(str(newest).replace("Z", "+00:00")).date() if newest else None
            if nd is None or (today - nd).days > JOURNAL_FRESH_DAYS:
                stale = f"journal at {path} is not live (newest order package {newest})"
        except (sqlite3.Error, ValueError):
            stale = f"journal at {path} unreadable"
        if stale:
            conn.close()
            conn = None
    rows = []
    for c in contracts:
        if c.get("design") == "not_soaking":
            # Not a soak (disabled / on no roster): its contract records that decision.
            continue
        d = c.get("disposition") or {}
        if _disposition_holds(c, today):
            if d.get("verdict") != "PASS":
                continue
            row = _base_row(c)
            row.update(state="passed", progress=f"{len(d.get('trades') or [])}/{c.get('n_needed')} clean",
                       reason=f"PASS {d.get('decided_at')}: {str(d.get('reason'))[:120]}")
            rows.append(row)
            continue
        row = _base_row(c)
        if conn is None:
            row["reason"] = (stale + " — we could not look") if stale else \
                "journal DB unreadable — we could not look (not awaiting, not passed)"
            rows.append(row)
            continue
        try:
            ev = evaluate(graded_for(conn, c), int(c.get("n_needed") or N_DEFAULT))
        except sqlite3.Error as exc:
            row["reason"] = f"journal read failed ({exc}) — we could not look"
            rows.append(row)
            continue
        row.update(state=ev["state"], progress=ev["progress"], reason=ev["reason"], touched=ev.get("touched", []))
        rows.append(row)
    if conn is not None:
        conn.close()
    return rows


# ── backfill ────────────────────────────────────────────────────────────────
def _strategies() -> Dict[str, Any]:
    import yaml  # noqa: PLC0415
    return yaml.safe_load(open(REPO / "config/strategies.yaml"))["strategies"]


def backfill(ref: str = "HEAD") -> Dict[str, Any]:
    """Contracts for every CURRENT Stage-1 (non-shadow) leg and shadow strategy.
    Start dates are measured from git (soak_report.start_dates)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import soak_report as sr  # noqa: PLC0415

    sys.path.insert(0, str(REPO))
    from src.config.accounts_loader import load_accounts_dict  # noqa: PLC0415
    acc = load_accounts_dict()
    if not acc:
        raise SystemExit("soak_state --backfill: the accounts config is unreadable — refusing to write contracts")
    strat = _strategies()
    shadow = sorted(n for n, v in strat.items() if isinstance(v, dict) and v.get("execution") == "shadow")
    stage1 = sorted(f"{a}/{s}" for a in STAGE1_ACCOUNTS for s in (acc.get(a) or {}).get("strategies") or []
                    if s not in shadow)
    s1 = sr.start_dates(set(stage1), "config/accounts.yaml", sr.roster_members, ref)
    sh = sr.start_dates(set(shadow), "config/strategies.yaml", sr.shadow_members, ref)
    out = []
    for subj in stage1:
        a, leg = subj.split("/", 1)
        out.append(make_contract(kind="stage1", leg=leg, account=a, started=s1[subj]))
    for leg in shadow:
        accts = [a for a, x in acc.items() if leg in (x.get("strategies") or [])]
        out.append(make_contract(kind="shadow", leg=leg, account=",".join(accts) or "-",
                                 started=sh[leg], enabled=strat[leg].get("enabled") is not False,
                                 rostered=bool(accts)))
    return {"as_of": datetime.now(timezone.utc).date().isoformat(),
            "_comment": "SOAK CONTRACTS — mechanical definitions of done (1-2 clean trades, no "
                        "calendar), NOT state. State is computed live by "
                        "scripts/ops/soak_state.py::soak_states(). Guarded by "
                        "scripts/ci/check_soak_contracts.py.",
            "soaks": out}


def _self_test() -> int:
    ok = True

    def ck(label: str, cond: bool) -> None:
        nonlocal ok
        ok &= cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    clean = {"id": 1, "order_package_id": "p", "direction": "long", "position_size": 1.0,
             "entry_price": 100.0, "stop_loss": 95.0, "take_profit_1": 110.0, "sl_order_id": "s",
             "tp_order_id": "t", "exit_reason": "sl", "exit_price": 95.0, "closed_at": "2026-10-01",
             "pnl": -5.0, "fee_taker_usd": 0.1, "cost_source": "estimate", "account_id": "bybit_1"}
    ck("a clean bybit SL close is clean", grade_trade(clean)["clean"] is True)
    ck("a reconciler close is a fault", grade_trade(dict(clean, exit_reason="reconciler_filled"))["clean"] is False)
    ck("an intent-reduce row is neutral", grade_trade(dict(clean, exit_reason="intent_reduce_executed"))["clean"] is None)
    ck("a 50R TP is a sentinel fault", grade_trade(dict(clean, take_profit_1=350.0))["clean"] is False)
    ck("a naked_rearm repair is a fault",
       grade_trade(dict(clean, protection_repairs=1, protection_repair_last_kind="naked_rearm"))["clean"] is False)
    ck("unstamped bybit venue ids are a fault", grade_trade(dict(clean, sl_order_id=None))["clean"] is False)
    ck("alpaca (unstamped path) with no repair is clean",
       grade_trade(dict(clean, account_id="alpaca_paper", sl_order_id=None, tp_order_id=None))["clean"] is True)
    ck("no fee recorded is a fault", grade_trade(dict(clean, fee_taker_usd=None))["clean"] is False)
    ck("a trailed-to-breakeven stop is not read as a sentinel when the package is known",
       grade_trade(dict(clean, stop_loss=99.99, exit_reason="tp"),
                   {"entry": 100.0, "sl": 95.0, "tp": 110.0, "direction": "long"})["clean"] is True)
    ck("the exit_plan stop wins over a trailed package sl",
       grade_trade(dict(clean, stop_loss=100.2, exit_reason="tp"),
                   {"entry": 100.0, "sl": 100.2, "tp": 110.0, "direction": "long",
                    "exit_plan": json.dumps({"stop": {"price": 95.0}, "final": {"price": 110.0}})}
                   )["clean"] is True)
    ck("a moved stop is recorded as observed management",
       "trailed" in grade_trade(dict(clean, stop_loss=101.0),
                                {"entry": 100.0, "sl": 95.0, "tp": 110.0})["items"]["management_no_fault"])
    ck("a package on the other side is a fault",
       grade_trade(clean, {"entry": 100.0, "sl": 105.0, "tp": 90.0, "direction": "short"})["clean"] is False)
    C, F, N = {"id": "c", "clean": True}, {"id": "f", "clean": False, "fault": "x"}, {"id": "n", "clean": None}
    ck("nothing graded -> awaiting_first_trade", evaluate([N], 2)["state"] == "awaiting_first_trade")
    ck("one clean of two -> in_progress", evaluate([C], 2)["state"] == "in_progress")
    ck("two clean -> passed", evaluate([C, N, C], 2)["state"] == "passed")
    ck("n_needed 1: one clean -> passed", evaluate([C], 1)["state"] == "passed")
    ck("latest graded is a fault -> mechanical_fail", evaluate([C, C, F], 2)["state"] == "mechanical_fail")
    ck("fault then two clean -> passed (fixed and re-soaked)", evaluate([F, C, C], 2)["state"] == "passed")
    ck("fault then one clean -> in_progress", evaluate([F, C], 2)["state"] == "in_progress")
    T = {"id": "t", "clean": True, "touched": True}
    TF = {"id": "tf", "clean": False, "fault": "x", "touched": True}
    ck("a touched trade never counts as clean (design 3.6)", evaluate([C, T, T], 2)["state"] == "in_progress")
    ck("only touched trades -> awaiting_first_trade, and names them",
       evaluate([T], 1)["state"] == "awaiting_first_trade" and evaluate([T], 1)["touched"] == ["t"])
    ck("a touched fault is not the leg's fault", evaluate([C, TF], 1)["state"] == "passed")
    ck("grade_trade carries the touch record",
       grade_trade(dict(clean, notes=json.dumps({"sl_amends": [{"source": "live_review_mandate", "at": "t",
                                                                 "from": 1.0, "to": 2.0, "venue_after": 2.0}]})),
                   None)["touched"] is True)
    base = make_contract(kind="stage1", leg="l", account="bybit_1", started="2026-10-01")
    ck("a fresh contract is admissible", contract_problems(base) == [])
    ck("n_needed 10 is refused", any("n_needed" in p for p in contract_problems(dict(base, n_needed=10))))
    ck("an end_date is refused", any("end_date" in p for p in contract_problems(dict(base, end_date="2027-01-01"))))
    ck("a duration_days is refused", any("duration_days" in p for p in contract_problems(dict(base, duration_days=9))))
    ck("a non-canonical checklist is refused",
       any("checklist" in p for p in contract_problems(dict(base, checklist=["signal_fired"]))))
    ck("a prop_live source with n_needed 10 is refused",
       any("sources[0]" in p for p in contract_problems(dict(base, sources=[{"kind": "prop_live", "n_needed": 10}]))))
    ck("a cost-fidelity pass rule is refused",
       any("pass_rule" in p for p in contract_problems(dict(base, pass_rule="R3 verdict consistent: CI95 upper <= modelled + 2 bps"))))
    ck("a live-vs-backtest prop_live pass rule is refused",
       any("sources[0].pass_rule" in p for p in contract_problems(
           dict(base, sources=[{"kind": "prop_live", "n_needed": 2, "pass_rule": "live_vs_backtest CONSISTENT"}]))))
    ck("a PASS disposition without trades is refused",
       any("trades" in p for p in contract_problems(dict(base, disposition={
           "verdict": "PASS", "reason": "r", "decided_at": "2026-10-15", "evidence": ["e"]}))))
    tk = [{"ticket_id": "a", "account_id": "x", "order_package_id": "P", "direction": "long", "qty": 1,
           "entry": 100, "sl": 95, "tp": 110}]
    fl = [{"ticket_id": "a", "status": "open", "entry_price": 100, "sl": 97, "tp": 110},
          {"ticket_id": "a", "status": "closed", "reason": "sl", "exit_price": 97, "closed_at": "t"}]
    g = grade_prop_signal(tk, fl)
    ck("a prop SL close with a venue-read bracket is clean", g["clean"] is True)
    ck("a trailed prop stop is observed as management",
       "trailed" in g["accounts"][0]["items"]["management_no_fault"])
    ck("a free-text 'sl - closed ...' prop reason reads as sl",
       grade_prop_signal(tk, [fl[0], dict(fl[1], reason="sl - closed Buy 3 @ 97")])["clean"] is True)
    ck("an adapter fault (exit not journaled) is neutral for the leg, recorded against the adapter",
       (lambda g: g["clean"] is None and bool(g.get("adapter_faults")))(
           grade_prop_signal(tk, [fl[0], dict(fl[1], reason="closed on terminal, exit unknown",
                                               exit_price=None)])))
    ck("a ticket with no SL is a LEG fault",
       grade_prop_signal([dict(tk[0], sl=None)], fl)["clean"] is False)
    ck("a manual prop close is neutral",
       grade_prop_signal(tk, [fl[0], dict(fl[1], reason="manual - operator")])["clean"] is None)
    print("soak_state self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backfill", action="store_true",
                    help=f"add contracts to {CONTRACTS.relative_to(REPO)} for current Stage-1 + shadow "
                         "legs that have none, keeping existing contracts as they are")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--db", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.backfill:
        doc = backfill(a.ref)
        if CONTRACTS.exists():  # a contract, once registered, keeps its start and evidence
            old = {c["id"]: c for c in load_contracts()}
            new_ids = {c["id"] for c in doc["soaks"]}
            doc["soaks"] = [old.get(c["id"], c) for c in doc["soaks"]]
            doc["soaks"] += [c for i, c in old.items() if i not in new_ids]
        CONTRACTS.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        print(f"wrote {len(doc['soaks'])} contracts to {CONTRACTS.relative_to(REPO)}")
        return 0
    print(json.dumps(soak_states(db_path=a.db), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
