#!/usr/bin/env python3
"""Per-account apply of a live-trade-review intent (LTR-6R-APPLY-PATH).

Why this exists
---------------
Operator structural directive, 2026-10-25 (row ``LTR-6R-APPLY-PATH``): the
live trade review acts at the ORDER-PACKAGE level and never does per-account
risk management. Every action is routed through EACH account's own risk
manager, so each account carrying the package (bybit_2, bybit_portfolio, each
prop account, ...) decides inside its own bounds and drawdown limits.

``scripts/ops/amend_position_sl.py`` (the operator's manual amend) moves the
SHARED ``order_packages.sl`` and every leg, and asks no RiskManager. This
script is the review's path instead:

1. Build one package-level :class:`LiveReviewIntent` (``src/runtime/live_review_intent.py``).
2. Find every account carrying the package: its open ``trades`` legs and its
   placed/filled ``prop_tickets``.
3. For each account: ``RiskManager.approve_amend(intent, view)`` →
   approve / clip / refuse, with a reason.
4. ``apply_mode`` (``config/live_trade_review.yaml``, per account) decides
   what happens next — ``off``: nothing computed; ``recommend``: the verdict
   is recorded only; ``apply``: an approved/clipped level is handed to that
   account's EXISTING executor, and only when ``--mandate`` names a GRANTED
   mandate in ``config/mandates.yaml``:
     * Bybit — the monitor's own modify seam on THAT leg only
       (``order_monitor._send_modify_to_exchange``), read back from the venue,
       then ``trades.stop_loss`` + ``notes.sl_amends`` (provenance
       ``live_review_mandate``) + ``notes.sl_floor``. The order monitor never
       trails a floored leg looser (``held_by_floor``). The shared package stop
       moves ONLY when every trade leg applied the same level, which keeps
       live = mirror identical whenever every account agrees.
     * prop VM accounts — ``prop_tickets.meta.sl_floor``; the VM executor's
       trail (``prop_trail.plan_trail(sl_floor=...)``) tightens TO it through
       its own guards and never plans looser (LTR-8 minimal).
     * phone accounts — ``phone_trail.request_sl_tighten`` through the
       one-slot amend channel (+ ``meta.sl_floor`` so the trail re-emits it).
     * Alpaca (and anything else) — refused, ``no_amend_path`` (LTR-9).
5. Every account's outcome is written back in the review row's
   ``account_reads`` / ``disposition`` shape (``comms/schema/live_review.schema.json``)
   to ``runtime_logs/live_review/applied.jsonl`` and printed; every applied
   leg sends the existing trade-update ping tagged with the mandate.

Never: a halt, a ``mode:`` write, an ``execution:`` write, a size change, a
close, a TP move, or a wider stop.

Exit codes: 0 ok · 1 an apply did not verify · 2 refused / bad input · 3 could not look.

Usage:
    # read-only evidence: what would each account do for every open package?
    python3 scripts/ops/live_review_apply.py --dry-run
    python3 scripts/ops/live_review_apply.py --dry-run --package pkg-… --new-sl 0.2053
    # apply (only with apply_mode: apply AND a granted mandate)
    python3 scripts/ops/live_review_apply.py --package pkg-… --new-sl 0.2053 \
        --review-id LR-… --evidence comms/live_review/tables/LR-….json \
        --mandate MD-LIVE-TIGHTEN-SL --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.runtime import live_review_intent as lri  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_UNREADABLE = 0, 1, 2, 3
APPLIED_LOG = Path(_REPO_ROOT) / "runtime_logs" / "live_review" / "applied.jsonl"
_PROP_PARENT = ("placed", "filled")


# --------------------------------------------------------------------------
# Seams (monkeypatched in tests)
# --------------------------------------------------------------------------

def _open_db():
    from src.runtime.order_monitor import _resolve_db

    return _resolve_db(None)


def _load_yaml(rel: str) -> Dict[str, Any]:
    import yaml

    try:
        return yaml.safe_load((Path(_REPO_ROOT) / rel).read_text()) or {}
    except (OSError, ValueError):
        return {}


def _accounts() -> Dict[str, Dict[str, Any]]:
    return dict((_load_yaml("config/accounts.yaml").get("accounts") or {}))


def _strategies() -> Dict[str, Dict[str, Any]]:
    return dict((_load_yaml("config/strategies.yaml").get("strategies") or {}))


def _granted_mandates() -> set:
    return {m.get("id") for m in (_load_yaml("config/mandates.yaml").get("mandates") or [])
            if isinstance(m, dict)}


def _risk_manager(account_id: str, cfg: Dict[str, Any]):
    """The account's OWN risk manager, built exactly as ``load_accounts`` builds it."""
    from src.units.accounts import _resolve_mode
    from src.units.accounts.prop_risk import PropRiskManager
    from src.units.accounts.risk import RiskManager

    dry = _resolve_mode(cfg, account_id)
    if cfg.get("type", "regular") == "prop":
        return PropRiskManager(cfg, account_name=account_id, dry_run=dry)
    return RiskManager(cfg.get("risk") or {}, dry_run=dry, account_id=account_id)


def _is_phone(account_id: str) -> bool:
    try:
        from src.prop.phone_executor import is_phone_account

        return bool(is_phone_account(account_id))
    except Exception:  # noqa: BLE001
        return False


def _candles(symbol: str, timeframe: str):
    from src.prop.prop_trail import default_candles_fn

    return default_candles_fn(limit=100)(symbol, timeframe)


def _prop_tickets(pkg_id: str) -> List[Dict[str, Any]]:
    from src.prop import prop_journal

    conn = prop_journal._connect(read_only=True)
    try:
        rows = conn.execute("SELECT * FROM prop_tickets WHERE order_package_id = ? AND status IN (?, ?)",
                            (pkg_id, *_PROP_PARENT)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _open_packages(db) -> List[Dict[str, Any]]:
    import sqlite3

    conn = db.connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM order_packages WHERE status = 'open' ORDER BY created_at")]
    finally:
        conn.close()


def _get_package(db, pkg_id: str) -> Optional[Dict[str, Any]]:
    from scripts.ops.amend_position_sl import _get_package as g

    return g(db, pkg_id)


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def atr_from_candles(candles: Any, n: int = 14) -> Optional[float]:
    """Wilder-free simple ATR(n) over CLOSED bars (the last row may be forming)."""
    try:
        df = candles.iloc[:-1] if len(candles) > n + 1 else candles
        h, lo, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
        prev = c.shift(1)
        tr = (h - lo).combine((h - prev).abs(), max).combine((lo - prev).abs(), max)
        v = float(tr.tail(n).mean())
        return v if math.isfinite(v) and v > 0 else None
    except Exception:  # noqa: BLE001
        return None


def account_class(account_id: str, cfg: Dict[str, Any]) -> str:
    from src.prop.prop_identity import is_prop_account

    ex = str(cfg.get("exchange") or "").lower()
    if is_prop_account(cfg):
        return "phone" if _is_phone(account_id) else "prop_vm"
    if ex == "bybit":
        return "bybit"
    if ex == "alpaca":
        return "alpaca"
    return "other"


def _notes(raw: Any) -> Dict[str, Any]:
    from src.utils.json_notes import load_notes

    try:
        n = load_notes(raw)
        return n if isinstance(n, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def last_review_bar(notes: Dict[str, Any]) -> Optional[str]:
    for a in reversed(notes.get("sl_amends") or []):
        if isinstance(a, dict) and a.get("source") == lri.PROVENANCE and a.get("bar"):
            return str(a["bar"])
    return None


def tightest(direction: str, *levels: Optional[float]) -> Optional[float]:
    xs = [x for x in (_f(v) for v in levels) if x is not None]
    if not xs:
        return None
    return min(xs) if direction == "short" else max(xs)


# --------------------------------------------------------------------------
# Gather: every account carrying the package
# --------------------------------------------------------------------------

def gather_legs(db, pkg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One entry per (account, leg). Trade legs and prop tickets, never collapsed."""
    pkg_id = pkg["order_package_id"]
    direction = str(pkg.get("direction") or "").lower()
    out: List[Dict[str, Any]] = []
    for t in db.get_trades(filters={"order_package_id": pkg_id, "status": "open"}):
        if t.get("is_backtest"):
            continue
        notes = _notes(t.get("notes"))
        out.append({"kind": "trade", "account_id": t.get("account_id"), "row": t,
                    "leg_sl": tightest(direction, t.get("stop_loss"), lri.sl_floor_from(notes)),
                    "last_bar": last_review_bar(notes)})
    try:
        tickets = _prop_tickets(pkg_id)
    except Exception as exc:  # noqa: BLE001 — could not look is its own entry
        out.append({"kind": "prop_unreadable", "account_id": "?prop", "error": str(exc)})
        tickets = []
    for tk in tickets:
        meta = _notes(tk.get("meta"))
        trail = meta.get("phone_trail") if isinstance(meta.get("phone_trail"), dict) else {}
        out.append({"kind": "ticket", "account_id": tk.get("account_id"), "row": tk,
                    "leg_sl": tightest(direction, trail.get("resting_sl") or tk.get("sl"),
                                       lri.sl_floor_from(meta)),
                    "last_bar": (meta.get("sl_floor") or {}).get("bar")
                    if isinstance(meta.get("sl_floor"), dict) else None})
    return out


def market_state(pkg: Dict[str, Any], strategies: Dict[str, Any]) -> Dict[str, Any]:
    """Mark (last price), ATR(14) of the leg's timeframe and the last CLOSED bar ts."""
    leg = strategies.get(pkg.get("strategy_name")) or {}
    tf = str(leg.get("timeframe") or "1h")
    try:
        c = _candles(str(pkg.get("symbol")), tf)
    except Exception:  # noqa: BLE001
        c = None
    if c is None or len(c) < 3:
        return {"mark": None, "atr": None, "bar_ts": None, "timeframe": tf}
    bar = c["timestamp"].iloc[-2] if "timestamp" in c else None
    return {"mark": _f(c["close"].iloc[-1]), "atr": atr_from_candles(c), "timeframe": tf,
            "bar_ts": str(bar) if bar is not None else None}


# --------------------------------------------------------------------------
# Executors (each account's EXISTING path)
# --------------------------------------------------------------------------

def _exec_bybit(db, leg: Dict[str, Any], pkg: Dict[str, Any], level: float,
                intent: lri.LiveReviewIntent) -> Dict[str, Any]:
    from scripts.ops import amend_position_sl as aps
    from src.utils.json_notes import dump_capped

    t = leg["row"]
    aid, sym, direction = t["account_id"], str(t.get("symbol") or "").upper(), intent.direction
    client, cfg = aps._build_client(aid)
    if client is None or not cfg:
        return {"result": "could_not_look", "detail": f"no client for {aid}"}
    before = aps._venue_state(client, cfg, sym, direction, t.get("sl_order_id"))
    if before["read_state"] != "resolved" or before["position"] is None or before["venue_sl"] is None:
        return {"result": "could_not_look", "detail": f"venue read {before.get('read_state')}", "venue": before}
    if lri.is_looser(direction, level, before["venue_sl"]):
        return {"result": "refused", "detail": f"venue stop {before['venue_sl']} already tighter"}
    qty = _f(t.get("position_size"))
    sent = aps._send_modify(t, sl=level, side=direction, qty=qty,
                            cur_sl=_f(pkg.get("sl")), cur_tp=_f(pkg.get("tp")))
    after = aps._venue_state(client, cfg, sym, direction, t.get("sl_order_id"))
    tick = aps._tick_size(client, cfg, sym)
    tol = (tick / 2.0) if tick else max(level * 1e-6, 1e-9)
    if not (after["read_state"] == "resolved" and aps.same_level(after.get("venue_sl"), level, tol)):
        return {"result": "not_verified", "detail": f"venue reads {after.get('venue_sl')!r}", "send": sent}
    now = datetime.now(timezone.utc).isoformat()
    notes = _notes(t.get("notes"))
    amends = notes.get("sl_amends") if isinstance(notes.get("sl_amends"), list) else []
    amends.append({"source": lri.PROVENANCE, "mandate": intent.mandate, "review_id": intent.review_id,
                   "evidence": intent.evidence_path, "at": now, "bar": intent.bar_ts,
                   "from": _f(t.get("stop_loss")), "to": level,
                   "venue_before": before.get("venue_sl"), "venue_after": after.get("venue_sl")})
    notes["sl_amends"] = amends[-10:]
    notes["sl_floor"] = {"level": level, "source": lri.PROVENANCE, "review_id": intent.review_id, "at": now}
    db.update_trade(int(t["id"]), {"stop_loss": level, "notes": dump_capped(notes, 2000)})
    return {"result": "applied", "venue_after": after.get("venue_sl")}


def _exec_prop_vm(leg: Dict[str, Any], level: float, intent: lri.LiveReviewIntent) -> Dict[str, Any]:
    from src.prop import prop_journal
    from src.prop.phone_trail import _cas, _meta

    tk = leg["row"]
    conn = prop_journal._connect()
    try:
        r = conn.execute("SELECT meta, status FROM prop_tickets WHERE ticket_id = ?",
                         (tk["ticket_id"],)).fetchone()
        if r is None or r["status"] not in _PROP_PARENT:
            return {"result": "refused", "detail": "ticket no longer placed/filled"}
        m = _meta(r["meta"])
        m["sl_floor"] = {"level": level, "source": lri.PROVENANCE, "review_id": intent.review_id,
                         "bar": intent.bar_ts, "mandate": intent.mandate,
                         "at": datetime.now(timezone.utc).isoformat()}
        ok = _cas(conn, tk["ticket_id"], r["meta"], m)
    finally:
        conn.close()
    # The VM executor's next trail step tightens to the floor; that venue
    # confirmation arrives as its own ``amend`` report, not here.
    return {"result": "floor_set" if ok else "not_verified",
            "detail": "VM trail tightens to meta.sl_floor next step" if ok else "concurrent write"}


def _exec_phone(leg: Dict[str, Any], level: float, intent: lri.LiveReviewIntent) -> Dict[str, Any]:
    from src.prop.phone_trail import request_sl_tighten

    tk = leg["row"]
    r = request_sl_tighten(tk["account_id"], tk["ticket_id"], level,
                           reason=f"mandate {intent.mandate}", review_id=intent.review_id)
    if r.get("ok"):
        return {"result": "amend_emitted", "amend_id": r.get("amend_id"), "sl": r.get("sl")}
    return {"result": "floor_set" if r.get("floor_recorded") else "refused", "detail": r.get("why")}


def _ping(pkg: Dict[str, Any], account_id: str, level: float, intent: lri.LiveReviewIntent) -> None:
    try:
        from src.runtime.execution_diagnostics import enqueue_trade_update

        enqueue_trade_update(symbol=pkg.get("symbol") or "?", account=account_id,
                             strategy=pkg.get("strategy_name"),
                             changes=[f"SL → {level:g} ({lri.PROVENANCE})",
                                      f"mandate {intent.mandate} · review {intent.review_id}"])
    except Exception as exc:  # noqa: BLE001 — the amend already landed
        print(f">>> live-review-apply: trade-update ping failed (amend stands): {exc}")


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

def run(intent: lri.LiveReviewIntent, *, apply: bool = False, db=None,
        accounts: Optional[Dict[str, Any]] = None, strategies: Optional[Dict[str, Any]] = None,
        review_cfg: Optional[Dict[str, Any]] = None, granted: Optional[set] = None,
        write_log: bool = True) -> Dict[str, Any]:
    db = db or _open_db()
    accounts = accounts if accounts is not None else _accounts()
    strategies = strategies if strategies is not None else _strategies()
    review_cfg = review_cfg if review_cfg is not None else lri.load_config()
    out: Dict[str, Any] = {"intent": intent.to_dict(), "apply": apply, "accounts": [],
                           "exit": EXIT_OK, "package_sl_moved": False}
    pkg = _get_package(db, intent.order_package_id)
    if not pkg or pkg.get("status") != "open":
        out.update(exit=EXIT_REFUSED, detail=f"package {intent.order_package_id} not open")
        return out
    mandate_ok = bool(intent.mandate) and intent.mandate in (granted if granted is not None else _granted_mandates())
    execution = str((strategies.get(pkg.get("strategy_name")) or {}).get("execution") or "live")
    trade_applied: Dict[str, float] = {}
    n_trade_legs = 0
    for leg in gather_legs(db, pkg):
        aid = leg["account_id"]
        rec: Dict[str, Any] = {"account_id": aid, "leg_kind": leg["kind"]}
        if leg["kind"] == "prop_unreadable":
            rec.update(account_class="prop", verdict="refuse", level=None, reason=lri.R_COULD_NOT_LOOK,
                       read="unknown", evidence=leg.get("error"))
            out["accounts"].append(rec)
            out["exit"] = max(out["exit"], EXIT_UNREADABLE)
            continue
        if leg["kind"] == "trade":
            n_trade_legs += 1
        cfg = accounts.get(aid) or {}
        cls = account_class(aid, cfg) if cfg else "other"
        mode = lri.apply_mode_for(aid, review_cfg)
        rec.update(account_class=cls, apply_mode=mode,
                   trade_id=(leg["row"].get("id") if leg["kind"] == "trade" else None),
                   ticket_id=(leg["row"].get("ticket_id") if leg["kind"] == "ticket" else None))
        if mode == "off":
            v = lri.AmendVerdict(aid, "refuse", None, lri.R_APPLY_OFF)
        elif not cfg:
            v = lri.AmendVerdict(aid, "refuse", None, f"{lri.R_COULD_NOT_LOOK}:account_not_in_accounts_yaml")
        else:
            view = lri.AmendAccountView(account_id=aid, account_class=cls, strategy_execution=execution,
                                        leg_sl=leg["leg_sl"], last_amend_bar=leg.get("last_bar"))
            v = _risk_manager(aid, cfg).approve_amend(intent, view)
            if v.ok and cls in ("alpaca", "other"):
                v = lri.AmendVerdict(aid, "refuse", None, lri.R_NO_PATH)
        rec.update(verdict=v.verdict, level=v.level, reason=v.reason, read=lri.account_read(v),
                   evidence=f"approve_amend:{v.verdict}:{v.reason}")
        if v.ok and mode == "apply" and apply:
            if not mandate_ok:
                rec.update(executed=False, executor={"result": "refused",
                                                     "detail": f"mandate {intent.mandate!r} not granted"})
                out["exit"] = max(out["exit"], EXIT_REFUSED)
            else:
                if cls == "bybit":
                    res = _exec_bybit(db, leg, pkg, v.level, intent)
                elif cls == "prop_vm":
                    res = _exec_prop_vm(leg, v.level, intent)
                else:  # phone
                    res = _exec_phone(leg, v.level, intent)
                rec.update(executed=res.get("result") in ("applied", "floor_set", "amend_emitted"),
                           executor=res)
                if res.get("result") == "applied":
                    trade_applied[str(leg["row"].get("id"))] = v.level
                if rec["executed"]:
                    rec["read"] = "applied"
                    _ping(pkg, aid, v.level, intent)
                elif res.get("result") == "could_not_look":
                    out["exit"] = max(out["exit"], EXIT_UNREADABLE)
                else:
                    out["exit"] = max(out["exit"], EXIT_FAILED)
        out["accounts"].append(rec)

    # The shared package stop: moved only when EVERY trade leg applied the SAME
    # level (live = mirror identical whenever every account agrees). Otherwise
    # each applied leg is held by its own sl_floor and the trail keeps working.
    levels = set(trade_applied.values())
    if n_trade_legs and len(trade_applied) == n_trade_legs and len(levels) == 1:
        lvl = levels.pop()
        if lri.is_tighter(intent.direction, lvl, _f(pkg.get("sl")) or lvl):
            db.update_order_package(pkg["order_package_id"], {"sl": lvl})
            out["package_sl_moved"] = True

    applied_any = any(a.get("executed") for a in out["accounts"])
    out["writeback"] = {
        "review_id": intent.review_id, "order_package_id": intent.order_package_id,
        "packet_sha": intent.packet_sha, "evidence": intent.evidence_path,
        "applied": applied_any,
        "account_reads": [{"account_id": a["account_id"], "account_class": a.get("account_class"),
                           "read": a["read"] if a["read"] != "applied" else "would_apply",
                           "evidence": a.get("evidence")} for a in out["accounts"]],
        "accounts_applied": [{"account_id": a["account_id"], "level": a.get("level"),
                              "executor": a.get("executor")} for a in out["accounts"] if a.get("executed")],
        "disposition": {"route": "auto_applied" if applied_any else "recommended",
                        "mandate": intent.mandate if applied_any else None, "action_issue": None,
                        "applied_at": datetime.now(timezone.utc).isoformat() if applied_any else None,
                        "verified_readback": (all(a.get("executor", {}).get("result") == "applied"
                                                  for a in out["accounts"]
                                                  if a.get("executed") and a.get("account_class") == "bybit")
                                              if applied_any else None)},
    }
    if write_log and apply:
        try:
            APPLIED_LOG.parent.mkdir(parents=True, exist_ok=True)
            with APPLIED_LOG.open("a") as fh:
                fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **out["writeback"]},
                                    default=str) + "\n")
        except OSError as exc:
            out["writeback_error"] = str(exc)
    return out


def build_intent(pkg: Dict[str, Any], *, new_sl: Optional[float], review_id: str,
                 market: Dict[str, Any], min_buffer_atr: float, mandate: Optional[str] = None,
                 evidence: Optional[str] = None, packet_sha: Optional[str] = None,
                 expected_cost_r: Optional[float] = None) -> lri.LiveReviewIntent:
    """An intent for ``pkg``. With no ``new_sl`` it is a PROBE at the noise
    floor (the tightest stop the floor allows), used only by ``--dry-run`` to
    show what each account's own bounds would do."""
    direction = str(pkg.get("direction") or "").lower()
    if new_sl is None and market.get("mark") and market.get("atr"):
        new_sl = lri.floor_level(direction, market["mark"], market["atr"], min_buffer_atr)
    return lri.LiveReviewIntent(
        order_package_id=pkg["order_package_id"], action="tighten_sl", direction=direction,
        review_id=review_id, new_sl=new_sl, packet_sha=packet_sha, evidence_path=evidence,
        expected_cost_r=expected_cost_r, mark=market.get("mark"), atr=market.get("atr"),
        bar_ts=market.get("bar_ts"), min_buffer_atr=min_buffer_atr, mandate=mandate)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--package", help="order_package_id (default with --dry-run: every open package)")
    ap.add_argument("--new-sl", type=float, help="the review's level (omit with --dry-run for a noise-floor probe)")
    ap.add_argument("--review-id", default=None)
    ap.add_argument("--evidence", default=None, help="the committed evidence path (outcome table)")
    ap.add_argument("--packet-sha", default=None)
    ap.add_argument("--expected-cost-r", type=float, default=None)
    ap.add_argument("--mandate", default=None)
    ap.add_argument("--dry-run", action="store_true", help="read-only: print what each account WOULD do")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.apply and a.dry_run:
        print("--apply and --dry-run are exclusive")
        return EXIT_REFUSED
    if a.apply and not (a.package and a.new_sl and a.review_id and a.evidence and a.mandate):
        print("--apply needs --package --new-sl --review-id --evidence --mandate")
        return EXIT_REFUSED
    if a.apply and not Path(_REPO_ROOT, a.evidence).is_file():
        print(f"evidence {a.evidence!r} is not a file in the checkout (it must be on main)")
        return EXIT_REFUSED
    cfg = lri.load_config()
    buf = lri.min_buffer_atr_from(cfg)
    db = _open_db()
    strategies, accounts = _strategies(), _accounts()
    pkgs = [p for p in [_get_package(db, a.package)] if p] if a.package else _open_packages(db)
    if not pkgs:
        print(json.dumps({"packages": 0, "detail": "no open package matched"}))
        return EXIT_OK if a.dry_run else EXIT_REFUSED
    worst = EXIT_OK
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    for pkg in pkgs:
        market = market_state(pkg, strategies)
        intent = build_intent(pkg, new_sl=a.new_sl, review_id=a.review_id or f"LR-{stamp}-dryrun",
                              market=market, min_buffer_atr=buf, mandate=a.mandate,
                              evidence=a.evidence, packet_sha=a.packet_sha,
                              expected_cost_r=a.expected_cost_r)
        res = run(intent, apply=bool(a.apply), db=db, accounts=accounts, strategies=strategies,
                  review_cfg=cfg)
        res["probe"] = a.new_sl is None
        res["market"] = market
        print(json.dumps(res, indent=2, default=str))
        for r in res["accounts"]:
            print(f">>> {pkg['order_package_id']} {pkg.get('strategy_name')} {r['account_id']}"
                  f" [{r.get('account_class')}/{r.get('apply_mode')}]: {r['verdict']}"
                  f" {r.get('level')} — {r['reason']}")
        worst = max(worst, int(res["exit"]))
    return worst


if __name__ == "__main__":
    sys.exit(main())
