#!/usr/bin/env python3
"""Commit-ready AFFORDABILITY answer for the mandate resolver's R-AFFORD clause -- never the balance.

⚠️ NO BALANCE IS WRITTEN (manager 2026-11-01, relaying the rule: account balances do not go into this PUBLIC repo; the
v1 files committed equity / buying power / cash). The writer reads the balance from the diag read, runs the
resolver's OWN sizer (``mandate_resolver.affordability_answer``) for every leg with a committed Stage-0 record, and
commits only each leg's answer: setups in run / permitted / sized at the latest committed price, and ``affordable``.
The resolver reads that answer (``_affordability_from_legs``) and treats it as valid only for the record it was
computed against (config_fingerprint + source_run). Git history still holds the v1 balances: row
ACCOUNT-SNAPSHOT-BALANCE-HISTORY.

Original description (v1), kept for the read path:

Reads the JSON of ``GET /api/diag/broker_account_status?account_id=<id>`` on
stdin and writes ``comms/mandate_evidence/account_snapshot/<id>.json`` -- the
one file ``scripts/ops/mandate_resolver.py`` reads to decide whether a Stage-2
account can size a leg at all (PI-20260928-E8Y3BGBS-0003)::

    scripts/ops/diag_fetch.sh 'broker_account_status?account_id=alpaca_live' \\
        | python3 scripts/ops/snapshot_account_for_mandate.py

Aggregates only (equity / buying power / cash / multiplier / shorting flag),
the same public class ``broker_account_status`` already serves. It never writes
a number the diag read did not carry: a field the venue did not report is
``null``, never ``0`` ("we did not look" stays distinct from "we looked").

Bybit: ``broker_account_status`` carries ``available_margin`` but no equity, so
``equity_usd`` is set to that available figure and ``equity_basis`` says so.
It understates equity, which can only make R-AFFORD refuse MORE, never fire on
money the account does not have.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR_REL = "comms/mandate_evidence/account_snapshot"


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _reading(diag: dict, account_id: str) -> dict:
    """The balance reading, IN MEMORY ONLY (v1 shape). Raises when the read has no measurement."""
    rows = [a for a in diag.get("accounts") or [] if a.get("account_id") == account_id]
    if len(rows) != 1:
        raise SystemExit(f"snapshot: {account_id!r} appears {len(rows)} times in the diag read")
    a = rows[0]
    if a.get("error"):
        raise SystemExit(f"snapshot: diag read for {account_id} errored: {a['error']}")
    out = {"account_id": account_id, "exchange": a.get("exchange"),
           "captured_at": diag.get("captured_at"),
           "source": f"GET /api/diag/broker_account_status?account_id={account_id}"}
    cap = ((a.get("status_flags") or {}).get("capacity")) or {}
    if cap:
        out.update({"equity_usd": _f(cap.get("equity")),
                    "buying_power_usd": _f(cap.get("buying_power")),
                    "multiplier": cap.get("multiplier"),
                    "equity_basis": "venue equity"})
    else:
        am = a.get("available_margin") or {}
        avail = None if am.get("could_not_look") else _f(am.get("available_usd"))
        out.update({"equity_usd": avail, "buying_power_usd": avail, "multiplier": None,
                    "equity_basis": f"available_margin ({am.get('read_state')}) -- equity not "
                                    "in this endpoint; understates, so R-AFFORD errs to refuse"})
    out["shorting_enabled"] = (a.get("status_flags") or {}).get("shorting_enabled")
    if out["equity_usd"] is None or not out["captured_at"]:
        raise SystemExit(f"snapshot: {account_id} read carries no equity/captured_at -- not written")
    return out


def _legs_with_records(root: Path) -> list:
    import yaml
    strategies = (yaml.safe_load((root / "config/strategies.yaml").read_text()) or {}).get("strategies") or {}
    ev = root / "comms/strategy_evidence"
    return sorted(leg for leg in strategies if (ev / f"{leg}.json").is_file())


def build(diag: dict, account_id: str, root: Path = REPO, legs=None) -> dict:
    """The committed snapshot (schema 2): per-leg affordability, NO balance."""
    sys.path.insert(0, str(root / "scripts" / "ops"))
    import mandate_resolver as mr
    r = _reading(diag, account_id)
    answers = {}
    for leg in (legs if legs is not None else _legs_with_records(root)):
        a = mr.affordability_answer(leg, account_id, r["equity_usd"], r["buying_power_usd"], root=root)
        if a.get("source_run"):
            answers[leg] = a
    return {"account_id": account_id, "exchange": r["exchange"], "captured_at": r["captured_at"],
            "source": r["source"], "schema": mr.AFFORD_SNAPSHOT_SCHEMA, "balance_committed": False,
            "equity_basis": r["equity_basis"], "multiplier": r["multiplier"],
            "shorting_enabled": r["shorting_enabled"], "legs": answers}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--account", help="account id (default: the read's requested_account_id)")
    ap.add_argument("--root", default=str(REPO))
    a = ap.parse_args(argv)
    diag = json.load(sys.stdin)
    acct = a.account or diag.get("requested_account_id")
    if not acct:
        raise SystemExit("snapshot: no --account and the read names no requested_account_id")
    snap = build(diag, acct, Path(a.root))
    p = Path(a.root) / OUT_DIR_REL / f"{acct}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    n_ok = sum(1 for v in snap["legs"].values() if v.get("affordable"))
    print(f"snapshot: wrote {p.relative_to(a.root)} (no balance) legs={len(snap['legs'])} "
          f"affordable={n_ok} captured_at={snap['captured_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
