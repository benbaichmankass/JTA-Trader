#!/usr/bin/env python3
# wiring: run by src/runtime/live_review_rows_watch.py (the live trader's rows watcher) as a
# subprocess, once per new desk/decisions tip; also runnable by hand with --dry-run.
"""DESK-4-INTAKE -- a validated desk decision row (schema v2) -> the apply path.

Why this exists
---------------
The desk writes ONE decision row per wake to ``comms/desk/decisions.jsonl`` on the append-only
``desk/decisions`` branch (``.claude/skills/trading-desk/SKILL.md`` § 1). Until this file nothing
read a desk row on the VM, so a desk ``tighten_sl`` could never reach an account and a desk
``propose_entry`` had nowhere to go once its gate clears. This is that intake. It adds NO order path
and NO gate:

* an in-trade action is handed to ``scripts/ops/live_review_apply.run()`` as a
  ``LiveReviewIntent`` under ``MD-TRADE-DESK`` -- every account carrying the package decides through
  its OWN ``RiskManager.approve_amend`` / ``approve_action`` (``PropRiskManager`` on a prop account,
  DESK-2), its own ``apply_mode`` (``config/live_trade_review.yaml``) and its own executor, and the
  venue is read back. All four verdicts (approve / clip / refuse / could_not_look) stay the apply's.
* a ``propose_entry`` is REFUSED, named, while ``MD-TRADE-DESK.functions.entry_generation.blocked_until``
  is in force for any account that rosters the ``claude_desk`` leg (read from ``config/mandates.yaml`` and
  ``config/accounts.yaml`` on every pass, never hard-coded). THE DEMO FLOOR (operator popup 2026-10-27,
  verbatim *"Yes, live on bybit_1 demo now (Recommended)"*): the gate is open when EVERY rostering account
  is in ``entry_generation.demo_accounts`` AND is a demo/paper account in ``config/accounts.yaml``; one
  real-money, mirror or prop account carrying the leg closes it for all. Once open, a live proposal on a
  symbol the leg trades (``strategies.yaml`` ``symbols:``) is queued for the ``claude_desk`` leg (DESK-17)
  in ``accepted_proposals.jsonl``; until that leg is rostered it is refused ``desk_leg_not_rostered``, and a
  symbol outside its ``symbols:`` is refused ``symbol_not_in_desk_leg``.
  BOTH brackets are required on every proposal (operator 2026-10-26: *"every trade always must have
  BOTH brackets"*); a missing one is refused ``both_brackets_required``.

Why the rows watcher and not a new endpoint (DESK-4 design choice): the watcher already fetches a
branch into a private ref namespace inside the live trader and hands rows to the apply with a
seed-on-first-start, dedupe and retry contract; desk rows already land on a protected append-only
branch by CAS. A new authenticated VM endpoint would add an inbound write surface for no latency
gain at the hourly cadence (the watcher polls every 45 s). It is the fallback only if the 5-min
cadence needs a push.

What is decided where
---------------------
1. **Validated.** Every new row is checked by ``desk-records-guard``'s own
   ``decision_problems`` against the packet it cites, both read at the PINNED tip (``git show``),
   never a working tree. A malformed row is ``refused`` with the first problems, recorded.
2. **Recorded, never dropped.** Every new decision_id gets exactly one line in ``intake.jsonl``:
   ``dispatched`` (with the apply's per-account ``>>>`` lines) · ``refused`` (named reason) ·
   ``not_dispatchable`` (a record-only row: shadow, hold, flag_mechanics, a recommendation on a
   strategy trade) · ``accepted`` (queued for the desk leg) · ``expired``.
3. **Once.** ``intake_state.json`` keeps every seen decision_id and every dispatched intent_id; a
   repeated decision_id is never re-handled and a second decision carrying a dispatched intent_id is
   refused ``duplicate_intent``. First start SEEDS every row already on the branch as seen.
4. **No halting.** A could-not-look (packet unreadable at the tip, apply exit 3) is retried on later
   passes for ``RETRY_WINDOW_S``; past that the row is ``expired`` and ONE flag is sent. A row
   first seen more than ``STALE_S`` after it was judged is ``refused: stale_decision``.

Exit: 0 ok · 3 could not look (the tip or a row could not be read; retried next pass).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_desk_records as cdr  # noqa: E402

DECISIONS_PATH = "comms/desk/decisions.jsonl"
PACKETS_PATH = "comms/desk/packets"
MANDATE_ID = "MD-TRADE-DESK"
DESK_LEG = cdr.DESK_LEG
STALE_S = 3600
RETRY_WINDOW_S = 3600
#: desk (role, action) -> the apply's action. Keys are exactly desk-records-guard's APPLICABLE set
#: (pinned by a test); the "desk"-only ones apply only on the claude_desk leg's own trades.
APPLY_ACTION = {("in_trade", "tighten_sl"): "tighten_sl", ("in_trade", "tp_revise"): "move_tp",
                ("exit", "close"): "close", ("exit", "partial_close"): "partial_close"}
R_BRACKETS = "both_brackets_required"
R_GATED = "entry_generation_blocked_until"
R_SYMBOL = "symbol_not_in_desk_leg"
#: An account the demo floor may admit: config/accounts.yaml marks it a demo (``demo: true``) or a paper/soak
#: account. Checked IN ADDITION to the mandate's demo_accounts list, so a mis-typed list cannot admit real money.
DEMO_CLASSES = {"paper", "soak"}

Git = Callable[..., Tuple[int, str]]


def log_dir() -> Path:
    return ROOT / "runtime_logs" / "desk"


def _git(*args: str, timeout: int = 30) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


# --------------------------------------------------------------------------- pure checks

def _accounts(accounts_doc: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(accounts_doc, dict):
        return None
    acc = accounts_doc.get("accounts", accounts_doc)
    return acc if isinstance(acc, dict) else None


def carrying_accounts(accounts_doc: Any) -> Optional[List[str]]:
    """Every account whose ``strategies:`` roster carries the desk leg; None when unreadable."""
    acc = _accounts(accounts_doc)
    if acc is None:
        return None
    return sorted(k for k, v in acc.items() if isinstance(v, dict) and DESK_LEG in (v.get("strategies") or []))


def entry_gate(mandates_doc: Optional[Dict[str, Any]], accounts_doc: Any = None) -> Optional[str]:
    """None when desk-generated entries may pass; else why not. Fail closed: an unreadable store, an
    ungranted MD-TRADE-DESK or a missing entry_generation function all refuse. With ``blocked_until`` set,
    the demo floor opens the gate only when every account rostering the leg is listed in
    ``demo_accounts`` AND is a demo/paper account in ``accounts_doc`` (unreadable accounts => closed)."""
    if not isinstance(mandates_doc, dict):
        return f"{R_GATED}:mandates_unreadable"
    m = next((x for x in mandates_doc.get("mandates") or [] if isinstance(x, dict) and x.get("id") == MANDATE_ID), None)
    if m is None:
        return f"{R_GATED}:{MANDATE_ID}_not_granted"
    fn = (m.get("functions") or {}).get("entry_generation")
    if not isinstance(fn, dict):
        return f"{R_GATED}:no_entry_generation_function"
    blocked = str(fn.get("blocked_until") or "").strip()
    if not blocked:
        return None
    gated = f"{R_GATED}: {' '.join(blocked.split())[:160]}"
    demo = set(fn.get("demo_accounts") or [])
    if not demo:
        return gated
    acc, carrying = _accounts(accounts_doc), carrying_accounts(accounts_doc)
    if acc is None or carrying is None:
        return f"{R_GATED}:accounts_unreadable"
    if not carrying:
        return f"{R_GATED}:no_account_rosters_{DESK_LEG}"
    bad = [a for a in carrying if a not in demo or not (acc[a].get("demo") is True
                                                        or acc[a].get("account_class") in DEMO_CLASSES)]
    if bad:
        return f"{R_GATED}:not_a_demo_account:{','.join(bad)} -- {gated[len(R_GATED) + 2:][:120]}"
    return None


def brackets_problem(proposal: Any) -> Optional[str]:
    """Both brackets, always: a proposal with no numeric stop level or no numeric tp level is refused."""
    p = proposal if isinstance(proposal, dict) else {}
    missing = [k for k in ("stop", "tp") if _num((p.get(k) or {}).get("level") if isinstance(p.get(k), dict) else None) is None]
    return f"{R_BRACKETS}:missing_{'+'.join(missing)}" if missing else None


def classify(row: Dict[str, Any], *, problems: List[str], packet: Optional[Dict[str, Any]],
             gate: Optional[str], leg_rostered: bool,
             leg_symbols: Optional[List[str]] = None,
             carrying: Optional[List[str]] = None) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """(verdict, detail, plan). verdict in dispatch | accepted | refused | not_dispatchable. Pure."""
    role, action = row.get("role"), row.get("action")
    if action == "propose_entry":
        why = brackets_problem(row.get("proposal"))
        if why:
            return "refused", why, None
    if problems:
        return "refused", "invalid_row: " + "; ".join(problems[:3]), None
    disp = row.get("disposition") or {}
    if action == "propose_entry":
        if gate:
            return "refused", gate, None
        if row.get("label_source") != "live" or disp.get("route") != "submitted":
            return "not_dispatchable", f"record_only:{row.get('label_source')}/{disp.get('route')}", None
        if not leg_rostered:
            return "refused", f"desk_leg_not_rostered:{DESK_LEG}", None
        sym = str((row.get("proposal") or {}).get("symbol") or "")
        if leg_symbols is None or sym not in leg_symbols:
            return "refused", f"{R_SYMBOL}:{sym} (leg trades {leg_symbols})", None
        if cdr.desk_write.is_probe(row) and (carrying is None or set(carrying) - set(cdr.desk_write.PROBE_ACCOUNTS)):
            return "refused", f"probe_account_not_demo:{carrying}", None
        return "accepted", f"queued for {DESK_LEG}", None
    if row.get("label_source") != "live":
        return "not_dispatchable", f"label_source_{row.get('label_source')}", None
    apply_action = APPLY_ACTION.get((role, action))
    if apply_action is None:
        return "not_dispatchable", f"action_{role}/{action}", None
    if disp.get("route") != "recommended" or not row.get("intent_id"):
        return "not_dispatchable", f"route_{disp.get('route')}_intent_{bool(row.get('intent_id'))}", None
    leg = ((packet or {}).get("package") or {}).get("leg")
    if cdr.APPLICABLE.get((role, action)) == "desk" and leg != DESK_LEG:
        return "not_dispatchable", f"recommendation_only_on_strategy_trade:{action}", None
    conf = _num(row.get("judge_prior"))
    if conf is None or not 0.0 <= conf <= 1.0:
        return "refused", "judgement_confidence_missing (judge_prior)", None
    if not str(row.get("rationale") or "").strip():
        return "refused", "reason_missing (rationale)", None
    params = row.get("params") or {}
    plan = {"order_package_id": row["order_package_id"], "action": apply_action,
            "new_sl": _num(params.get("level")) if apply_action == "tighten_sl" else None,
            "new_tp": _num(params.get("level")) if apply_action == "move_tp" else None,
            "size_fraction": _num(params.get("frac")) if apply_action == "partial_close" else None,
            "review_id": row["decision_id"], "intent_id": row["intent_id"], "packet_sha": row.get("packet_sha"),
            "mandate": MANDATE_ID, "basis": "judgement", "confidence": conf,
            "reason": " ".join(str(row["rationale"]).split())[:300],
            "mechanics": ((packet or {}).get("mechanics") or {}).get("verdict")}
    return "dispatch", apply_action, plan


# --------------------------------------------------------------------------- seams

def _load_yaml(rel: str) -> Optional[Dict[str, Any]]:
    try:
        import yaml
        return yaml.safe_load((ROOT / rel).read_text()) or {}
    except Exception:  # noqa: BLE001 -- unreadable is its own state (fail closed for entries)
        return None


def _leg_symbols() -> Optional[List[str]]:
    """The desk leg's ``symbols:`` (what its builder evaluates); None when unreadable."""
    cfg = ((_load_yaml("config/strategies.yaml") or {}).get("strategies") or {}).get(DESK_LEG)
    syms = cfg.get("symbols") if isinstance(cfg, dict) else None
    return [str(s) for s in syms] if isinstance(syms, list) else None


def _leg_rostered() -> bool:
    """The leg is configured in ``config/strategies.yaml``'s ``strategies:`` section (the file's
    only top-level key -- a top-level membership test can never be true)."""
    return DESK_LEG in ((_load_yaml("config/strategies.yaml") or {}).get("strategies") or {})


def _apply(plan: Dict[str, Any], evidence_rel: str) -> Dict[str, Any]:
    """Build the LiveReviewIntent and run the per-account apply. Never raises."""
    try:
        from scripts.ops import live_review_apply as lra
        from src.runtime import live_review_intent as lri

        db = lra._open_db()
        pkg = lra._get_package(db, plan["order_package_id"])
        if not pkg or pkg.get("status") != "open":
            return {"exit": 2, "detail": f"package {plan['order_package_id']} not open", "lines": []}
        strategies, accounts, cfg = lra._strategies(), lra._accounts(), lri.load_config()
        intent = lra.build_intent(
            pkg, new_sl=plan["new_sl"], review_id=plan["review_id"], market=lra.market_state(pkg, strategies),
            min_buffer_atr=lri.min_buffer_atr_from(cfg), mandate=plan["mandate"], evidence=evidence_rel,
            packet_sha=plan["packet_sha"], basis=plan["basis"], confidence=plan["confidence"],
            reason=plan["reason"], mechanics_verdict=plan["mechanics"], action=plan["action"],
            new_tp=plan["new_tp"], size_fraction=plan["size_fraction"])
        res = lra.run(intent, apply=True, db=db, accounts=accounts, strategies=strategies, review_cfg=cfg)
    except Exception as exc:  # noqa: BLE001 -- contained per row; retried (no halting)
        return {"exit": 3, "detail": f"apply did not run: {type(exc).__name__}: {exc}"[:300], "lines": []}
    lines = [f">>> {a['account_id']} [{a.get('account_class')}/{a.get('apply_mode')}]: {a.get('verdict')}"
             f" {a.get('level')} executed={bool(a.get('executed'))} -- {a.get('reason')}" for a in res.get("accounts", [])]
    return {"exit": int(res.get("exit", 0)), "detail": res.get("detail") or res.get("mandate_precondition"),
            "lines": lines[-20:], "applied": bool((res.get("writeback") or {}).get("applied"))}


def _flag(line: str) -> None:
    """ONE high-priority ping for a row that kept failing (Prime Directive rule 7: flag, keep trying).
    ``enqueue_trade_update`` routes it to the TRADES channel through ``src.runtime.telegram_channels``."""
    try:
        from src.runtime.execution_diagnostics import enqueue_trade_update
        enqueue_trade_update(symbol="desk", account="desk-intake", strategy=DESK_LEG, priority="high",
                             changes=[f"⚠️ desk intake: {line}"])
    except Exception as exc:  # noqa: BLE001
        print(f">>> desk-intake: flag ping failed: {exc}")


# --------------------------------------------------------------------------- the pass

def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n")
    os.replace(tmp, path)


def _append(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(doc, default=str, separators=(",", ":")) + "\n")


def _rows(text: str) -> List[Dict[str, Any]]:
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and "_meta" not in r:
            out.append(r)
    return out


def _rel(p: Path) -> str:
    """The evidence path as the apply records it: repo-relative when under the checkout."""
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def run_pass(ref: str, *, apply: bool = True, git: Git = _git,
             apply_fn: Callable[[Dict[str, Any], str], Dict[str, Any]] = _apply,
             now_fn: Callable[[], datetime] = _now, logs: Optional[Path] = None,
             mandates_fn: Callable[[], Optional[Dict[str, Any]]] = lambda: _load_yaml("config/mandates.yaml"),
             leg_fn: Callable[[], bool] = _leg_rostered, flag_fn: Callable[[str], None] = _flag,
             accounts_fn: Callable[[], Any] = lambda: _load_yaml("config/accounts.yaml"),
             symbols_fn: Callable[[], Optional[List[str]]] = _leg_symbols) -> Dict[str, Any]:
    """Every new decision row at ``ref`` -> one recorded disposition. Returns the status written."""
    d = logs or log_dir()
    state_path, status_path, log_path = d / "intake_state.json", d / "intake_status.json", d / "intake.jsonl"
    accepted_path, pk_dir = d / "accepted_proposals.jsonl", d / "packets"
    seen_at = now_fn()
    status: Dict[str, Any] = {"pass_at": seen_at.isoformat(), "ref": ref, "apply": apply}
    rc, text = git("show", f"{ref}:{DECISIONS_PATH}")
    if rc != 0:
        status.update(state="could_not_read", detail=text[-200:], exit=3)
        _write_json(status_path, status)
        return status
    rows = [r for r in _rows(text) if r.get("decision_id")]
    status.update(state="read", rows=len(rows))
    state = _load(state_path)
    if state is None and not apply:
        state = {"seen": [], "intents": [], "pending": {}}  # a dry run classifies every row, writes no state
    if state is None:
        state = {"seeded_at": seen_at.isoformat(), "seeded_ref": ref,
                 "seen": sorted({r["decision_id"] for r in rows}), "intents": [], "pending": {}}
        _write_json(state_path, state)
        status.update(new=0, seeded=len(state["seen"]), exit=0)
        _write_json(status_path, status)
        return status
    seen, intents = set(state.get("seen") or []), set(state.get("intents") or [])
    pending: Dict[str, Any] = state.get("pending") or {}
    new = [r for r in rows if r["decision_id"] not in seen]
    status["new"] = len(new)
    schema = json.loads(cdr.DECISION_SCHEMA.read_text())
    accounts_doc = accounts_fn()
    gate, leg, leg_syms = entry_gate(mandates_fn(), accounts_doc), None, None
    carrying = carrying_accounts(accounts_doc)
    worst, handled = 0, set()
    for row in new:
        did = row["decision_id"]
        if did in handled:  # the same decision_id twice on the branch: handled once
            continue
        handled.add(did)
        first = _ts((pending.get(did) or {}).get("first_seen_at")) or seen_at
        rec: Dict[str, Any] = {"decision_id": did, "role": row.get("role"), "action": row.get("action"),
                               "order_package_id": row.get("order_package_id"), "intent_id": row.get("intent_id"),
                               "ref": ref, "judged_at": row.get("judged_at"), "seen_at": first.isoformat()}
        pid = str(row.get("packet_id") or "")
        prc, ptext = git("show", f"{ref}:{PACKETS_PATH}/{pid}.json") if pid else (1, "no packet_id")
        packet: Optional[Dict[str, Any]] = None
        if prc == 0:
            try:
                packet = json.loads(ptext)
                pk_dir.mkdir(parents=True, exist_ok=True)
                (pk_dir / f"{pid}.json").write_text(ptext if ptext.endswith("\n") else ptext + "\n")
            except (ValueError, OSError):
                packet = None
        judged = _ts(row.get("judged_at"))
        if packet is None and pid:
            verdict, detail, plan = "could_not_look", f"packet {pid} unreadable at {ref[:12]}", None
        elif judged and (first - judged).total_seconds() > STALE_S:
            verdict, detail, plan = "refused", f"stale_decision: judged {row.get('judged_at')}, first seen {first.isoformat()}", None
        else:
            problems = cdr.decision_problems(row, schema, pk_dir) if packet is not None else ["packet_id missing"]
            if leg is None:
                leg, leg_syms = leg_fn(), symbols_fn()
            verdict, detail, plan = classify(row, problems=problems, packet=packet, gate=gate, leg_rostered=leg,
                                             leg_symbols=leg_syms, carrying=carrying)
        if verdict == "dispatch" and row.get("intent_id") in intents:
            verdict, detail, plan = "refused", f"duplicate_intent:{row.get('intent_id')}", None
        rec.update(verdict=verdict, detail=detail)
        if verdict == "dispatch" and plan is not None:
            if not apply:
                rec.update(verdict="would_dispatch", plan=plan)
            else:
                res = apply_fn(plan, _rel(pk_dir / f"{pid}.json"))
                done = now_fn()
                rec.update(verdict="dispatched" if res.get("exit") != 3 else "could_not_look", exit=res.get("exit"),
                           detail=res.get("detail"), lines=res.get("lines"), applied=res.get("applied"),
                           done_at=done.isoformat(), seen_to_done_s=round((done - first).total_seconds(), 1))
                if judged:
                    rec["judged_to_done_s"] = round((done - judged).total_seconds(), 1)
        if verdict == "accepted":
            if apply:
                _append(accepted_path, {"at": seen_at.isoformat(), "decision_id": did, "intent_id": row.get("intent_id"),
                                        "packet_id": pid, "packet_sha": row.get("packet_sha"), "ref": ref,
                                        "proposal": row.get("proposal"),
                                        **({"mechanics_probe": True} if cdr.desk_write.is_probe(row) else {})})
            else:
                rec["verdict"] = "would_accept"
        if rec["verdict"] == "could_not_look":
            worst = 3
            if (now_fn() - first).total_seconds() < RETRY_WINDOW_S:
                att = int((pending.get(did) or {}).get("attempts") or 0) + 1
                pending[did] = {"first_seen_at": first.isoformat(), "attempts": att}
                if att == 1 or att % 10 == 0:
                    _append(log_path, dict(rec, retrying=True, attempts=att))
                continue
            rec["verdict"] = "expired"
            if apply:
                flag_fn(f"{did} could not be handled for {RETRY_WINDOW_S // 60} min ({rec.get('detail')}); expired")
        if not apply:
            _append(log_path, dict(rec, dry_run=True))
            continue
        if rec["verdict"] == "dispatched" and row.get("intent_id"):
            intents.add(row["intent_id"])
        pending.pop(did, None)
        seen.add(did)
        _append(log_path, rec)
    if apply:
        state.update(seen=sorted(seen), intents=sorted(intents), pending=pending)
        _write_json(state_path, state)
    status.update(pending=len(pending), exit=worst, entry_gate=gate)
    _write_json(status_path, status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--ref", required=True, help="the pinned desk/decisions commit to read")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dry-run", action="store_true", help="classify only: no apply, no state change")
    a = ap.parse_args(argv)
    st = run_pass(a.ref, apply=bool(a.apply))
    print(json.dumps(st, default=str))
    return int(st.get("exit") or 0)


if __name__ == "__main__":
    sys.exit(main())
