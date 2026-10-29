#!/usr/bin/env python3
# wiring: `vm-pass` is run by src/runtime/live_review_rows_watch.py (the live trader's watcher, its
# directed-actions thread) as a subprocess, once per new directed/actions tip; `submit` / `receipt` are run
# by the manager session.
"""Directed trade actions -- submit a record, apply it on the VM, read its receipt (TRADE-ACTION-FAST-PATH).

Operator, 2026-10-29 ~08:20Z, verbatim: "It looks like we also need a fast track for trade updates - not really
sure why these require a PR at all, but the action needs to be immediate". The design, the authority (the
operator's verbatim quote, refused without one) and the deliberate differences from a reviewer apply are in
``src/runtime/directed_actions.py``. This file is the I/O around it.

``submit`` (the manager)
    Builds ONE record, validates it locally with the VM's own validator, and adds
    ``comms/directed_actions/<id>.json`` to the ``directed/actions`` branch with a plain git push: a commit
    whose parent is the current tip and whose tree adds only that file (create-only; non-force; a rejected
    push re-reads the tip and retries; the branch is created as an orphan if it does not exist). Never a PR,
    never a GitHub Actions job. Then (unless ``--no-wait``) it polls the receipt through
    ``scripts/ops/diag_fetch.sh`` until the VM has handled the record and prints each account's venue
    read-back and the latency push -> done.

``vm-pass --ref <tip>`` (the VM watcher)
    Every record file at ``<tip>`` not yet handled: validated, then handed to ``live_review_apply.run()`` --
    the SAME executors, each account's OWN RiskManager, the venue read-back. ``dry_run: true`` computes every
    account's decision and executes nothing. Exactly one receipt line per record id (``receipts.jsonl``,
    diag ``log_file?name=directed_actions``) and ONE ping per non-dry record. Idempotent per id
    (``state.json``); a record first seen more than ``STALE_S`` after its ``created_at`` is refused
    ``stale_record``; a could-not-look apply is retried for ``RETRY_WINDOW_S``, then ``expired`` with one
    flag (no halting). First ever pass: records already older than ``STALE_S`` are seeded as seen.

``receipt --id <id>``
    One read of the receipt (direct diag).

Exit codes: 0 ok (applied / dry run) · 1 an apply did not verify · 2 refused · 3 could not look / no receipt.

Usage:
    python3 scripts/ops/directed_action.py submit --package pkg-... --action tighten_sl --level 0.6512 \
        --quote "<the operator's words, verbatim>" --directed-by "manager:<session> for operator" --dry-run
    python3 scripts/ops/directed_action.py submit --package pkg-... --action close --scope bybit_2 \
        --quote "..." --live
    python3 scripts/ops/directed_action.py receipt --id DA-...
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.runtime import directed_actions as da  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_UNREADABLE = 0, 1, 2, 3
Git = Callable[..., Tuple[int, str]]


def log_dir() -> Path:
    from src.utils.paths import repo_root
    return Path(repo_root()) / "runtime_logs" / "directed_actions"


def _git(*args: str, timeout: int = 30, stdin: Optional[str] = None,
         env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", _REPO_ROOT, *args], capture_output=True, text=True, timeout=timeout,
                           input=stdin, env={**os.environ, **(env or {})})
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


# --------------------------------------------------------------------------- VM side

def _apply_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Hand one valid record to ``live_review_apply.run()``. Never raises (exit 3 = could not look)."""
    try:
        from dataclasses import replace

        from scripts.ops import live_review_apply as lra
        from src.runtime import live_review_intent as lri

        db = lra._open_db()
        pkg = lra._get_package(db, record["order_package_id"])
        if not pkg or pkg.get("status") != "open":
            return {"exit": EXIT_REFUSED, "detail": f"package {record['order_package_id']} not open", "accounts": []}
        direction = str(pkg.get("direction") or "").lower()
        action = da.resolve_action(record, pkg.get("sl"), direction)
        if action is None:
            return {"exit": EXIT_REFUSED, "accounts": [],
                    "detail": f"move_sl: level {record.get('level')} equals the package stop {pkg.get('sl')} or it is unread"}
        strategies, accounts, cfg = lra._strategies(), lra._accounts(), lri.load_config()
        lvl, sc = record.get("level"), da.scope_of(record)
        intent = lra.build_intent(
            pkg, new_sl=lvl if action in ("tighten_sl", "widen_sl") else None, review_id=record["id"],
            market=lra.market_state(pkg, strategies), min_buffer_atr=lri.min_buffer_atr_from(cfg),
            reason=f"directed by {record['directed_by']}: {record['operator_quote']}"[:500], action=action,
            new_tp=lvl if action == "move_tp" else None,
            size_fraction=record.get("fraction") if action == "partial_close" else None)
        # bar_ts=None: the reviewer's one-action-per-bar guard does not bind a directed action (see module doc).
        intent = replace(intent, bar_ts=None, directed_by=record["directed_by"],
                         operator_quote=record["operator_quote"], target_account_id=sc["account_id"],
                         target_trade_id=sc["trade_id"])
        res = lra.run(intent, apply=not record["dry_run"], db=db, accounts=accounts, strategies=strategies,
                      review_cfg=cfg)
    except Exception as exc:  # noqa: BLE001 -- contained per record; retried (no halting)
        return {"exit": EXIT_UNREADABLE, "detail": f"apply did not run: {type(exc).__name__}: {exc}"[:300],
                "accounts": []}
    keep = ("account_id", "account_class", "leg_kind", "trade_id", "ticket_id", "verdict", "level", "qty",
            "reason", "read", "executed")
    accts = [dict({k: a.get(k) for k in keep},
                  executor={k: (a.get("executor") or {}).get(k) for k in ("result", "detail", "venue_after",
                                                                         "venue_tp_after")}
                  if a.get("executor") else None)
             for a in res.get("accounts", [])]
    return {"exit": int(res.get("exit", 0)), "detail": res.get("detail") or res.get("mandate_precondition"),
            "resolved_action": action, "symbol": pkg.get("symbol"), "strategy": pkg.get("strategy_name"),
            "accounts": accts, "package_sl_moved": res.get("package_sl_moved"), "flags": res.get("flags")}


def _ping(record: Dict[str, Any], res: Dict[str, Any], verdict: str) -> None:
    """ONE trade-update ping per non-dry record (TRADES channel via execution_diagnostics)."""
    try:
        from src.runtime.execution_diagnostics import enqueue_trade_update

        accts = [a.get("account_id") for a in res.get("accounts") or []]
        enqueue_trade_update(symbol=res.get("symbol") or "?", account=",".join(map(str, accts)) or "-",
                             strategy=res.get("strategy"), priority="normal" if verdict == "applied" else "high",
                             changes=[f"{'✅' if verdict == 'applied' else '⚠️'} {verdict}: "
                                      f"{da.summary_line(record, res.get('accounts') or [])}",
                                      f"{res.get('detail') or ''}".strip() or f"record {record.get('id')}",
                                      f"operator: \"{str(record.get('operator_quote') or '')[:200]}\"",
                                      f"record {record.get('id')}"])
    except Exception as exc:  # noqa: BLE001 -- the action already stands
        print(f">>> directed-action: ping failed: {exc}")


def verdict_of(record: Dict[str, Any], res: Dict[str, Any]) -> str:
    if record.get("dry_run"):
        return "dry_run"
    accts = res.get("accounts") or []
    done = [a for a in accts if a.get("executed")]
    if done and len(done) == len(accts):
        return "applied"
    if done:
        return "partially_applied"
    return "not_applied"


def vm_pass(ref: str, *, git: Git = _git, apply_fn: Callable[[Dict[str, Any]], Dict[str, Any]] = _apply_record,
            ping: Callable[[Dict[str, Any], Dict[str, Any], str], None] = _ping,
            now_fn: Callable[[], datetime] = _now, logs: Optional[Path] = None) -> Dict[str, Any]:
    """Handle every record at ``ref`` not yet handled. Returns the status it wrote."""
    d = logs or log_dir()
    state_path, status_path, receipts = d / "state.json", d / "status.json", d / "receipts.jsonl"
    seen_at = now_fn()
    status: Dict[str, Any] = {"pass_at": seen_at.isoformat(), "ref": ref}
    rc, out = git("ls-tree", "--name-only", ref, f"{da.RECORDS_DIR}/")
    if rc != 0:
        status.update(state="could_not_read", detail=out[-200:], exit=EXIT_UNREADABLE)
        _write_json(status_path, status)
        return status
    paths = sorted(p for p in out.splitlines() if p.endswith(".json"))
    state = _load(state_path)
    first_ever = state is None
    state = state or {"seen": {}, "pending": {}}
    seen: Dict[str, Any] = state.setdefault("seen", {})
    pending: Dict[str, Any] = state.setdefault("pending", {})
    handled, worst = 0, EXIT_OK
    for path in paths:
        rid = Path(path).stem
        if rid in seen:
            continue
        rc, text = git("show", f"{ref}:{path}")
        if rc != 0:
            worst = EXIT_UNREADABLE
            continue
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        first = da._ts((pending.get(rid) or {}).get("first_seen_at")) or seen_at
        if first_ever and isinstance(record, dict) and da.is_stale(record, seen_at):
            seen[rid] = {"verdict": "seeded", "at": seen_at.isoformat()}
            continue
        rec: Dict[str, Any] = {"id": rid, "ref": ref, "path": path, "seen_at": first.isoformat()}
        if isinstance(record, dict):
            rec.update({k: record.get(k) for k in ("order_package_id", "action", "level", "fraction", "scope",
                                                   "dry_run", "directed_by", "operator_quote", "created_at")})
        probs = da.problems(record, path=path)
        res: Dict[str, Any] = {}
        if probs:
            rec.update(verdict="refused", exit=EXIT_REFUSED, detail=", ".join(probs[:6]))
        elif da.is_stale(record, first):
            rec.update(verdict="refused", exit=EXIT_REFUSED,
                       detail=f"{da.R_STALE}: created {record.get('created_at')}, first seen {first.isoformat()}"
                              f" (> {da.STALE_S}s); re-issue it")
        else:
            res = apply_fn(record)
            done = now_fn()
            if res.get("exit") == EXIT_UNREADABLE and (done - first).total_seconds() < da.RETRY_WINDOW_S:
                att = int((pending.get(rid) or {}).get("attempts") or 0) + 1
                pending[rid] = {"first_seen_at": first.isoformat(), "attempts": att, "detail": res.get("detail")}
                worst = EXIT_UNREADABLE
                continue
            verdict = "expired" if res.get("exit") == EXIT_UNREADABLE else verdict_of(record, res)
            rec.update(verdict=verdict, exit=res.get("exit"), detail=res.get("detail"),
                       resolved_action=res.get("resolved_action"), accounts=res.get("accounts"),
                       package_sl_moved=res.get("package_sl_moved"), flags=res.get("flags"),
                       done_at=done.isoformat())
            c = da._ts(record.get("created_at"))
            if c:
                rec["created_to_done_s"] = round((done - c).total_seconds(), 1)
            rec["seen_to_done_s"] = round((done - first).total_seconds(), 1)
        if not (isinstance(record, dict) and record.get("dry_run") is True):
            ping(record if isinstance(record, dict) else {"id": rid}, dict(res, detail=rec.get("detail")),
                 rec["verdict"])
        pending.pop(rid, None)
        seen[rid] = {"verdict": rec["verdict"], "at": seen_at.isoformat()}
        _append(receipts, rec)
        handled += 1
        worst = max(worst, int(rec.get("exit") or 0)) if rec["verdict"] != "dry_run" else worst
    _write_json(state_path, state)
    status.update(state="read", records=len(paths), handled=handled, pending=sorted(pending),
                  seeded=first_ever, exit=EXIT_UNREADABLE if pending else min(worst, EXIT_REFUSED))
    _write_json(status_path, status)
    return status


# --------------------------------------------------------------------------- manager side

def build_record(a: argparse.Namespace, now: datetime) -> Dict[str, Any]:
    if a.scope in (None, "", "package"):
        scope: Any = "package"
    else:
        acct, _, tid = a.scope.partition(":")
        scope = {"account_id": acct, **({"trade_id": tid} if tid else {})}
    quote = a.quote if a.quote is not None else (Path(a.quote_file).read_text().strip() if a.quote_file else "")
    rec: Dict[str, Any] = {"schema": da.SCHEMA, "id": da.new_id(a.action, now, secrets.token_hex(3)),
                           "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "directed_by": a.directed_by,
                           "operator_quote": quote, "order_package_id": a.package, "scope": scope,
                           "action": a.action, "dry_run": bool(a.dry_run)}
    if a.level is not None:
        rec["level"] = a.level
    if a.fraction is not None:
        rec["fraction"] = a.fraction
    return rec


def push_record(record: Dict[str, Any], *, git: Git = _git, tries: int = 5) -> Tuple[bool, str]:
    """Add ONE file to ``directed/actions`` (create-only, non-force). Returns (ok, commit sha or why)."""
    path = da.record_path(record["id"])
    body = json.dumps(record, indent=1) + "\n"
    local = "refs/directed-submit/tip"
    last = ""
    for _ in range(tries):
        rc, out = git("fetch", "--quiet", "--no-write-fetch-head", "origin", f"+refs/heads/{da.BRANCH}:{local}")
        parent: Optional[str] = None
        if rc == 0:
            rc, parent = git("rev-parse", local)
            if rc != 0:
                return False, f"could not read the fetched tip: {parent}"
            if git("cat-file", "-e", f"{parent}:{path}")[0] == 0:
                return False, f"{path} already exists on {da.BRANCH} (create-only)"
        elif "couldn't find remote ref" not in out:
            last = f"fetch failed: {out[-200:]}"
            time.sleep(2)
            continue
        rc, blob = git("hash-object", "-w", "--stdin", stdin=body)
        if rc != 0:
            return False, f"hash-object: {blob}"
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            if parent:
                git("read-tree", parent, env=env)
            rc, o = git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
            if rc != 0:
                return False, f"update-index: {o}"
            rc, tree = git("write-tree", env=env)
        if rc != 0:
            return False, f"write-tree: {tree}"
        msg = f"directed: {record['id']} {record['action']} {record['order_package_id']}" \
              f"{' (dry run)' if record['dry_run'] else ''}"
        rc, commit = git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", msg)
        if rc != 0:
            return False, f"commit-tree: {commit}"
        rc, out = git("push", "origin", f"{commit}:refs/heads/{da.BRANCH}", timeout=60)
        if rc == 0:
            return True, commit
        last = f"push rejected/failed: {out[-300:]}"
        time.sleep(2)
    return False, last


def _diag(path: str) -> Tuple[int, Optional[Dict[str, Any]]]:
    try:
        r = subprocess.run([str(Path(_REPO_ROOT) / "scripts" / "ops" / "diag_fetch.sh"), path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return EXIT_UNREADABLE, None
    if r.returncode != 0:
        return r.returncode, None
    try:
        return 0, json.loads(r.stdout)
    except ValueError:
        return EXIT_UNREADABLE, None


def find_receipt(doc: Optional[Dict[str, Any]], record_id: str) -> Optional[Dict[str, Any]]:
    for ln in reversed((doc or {}).get("lines") or []):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("id") == record_id:
            return r
    return None


def print_receipt(r: Dict[str, Any], pushed_at: Optional[datetime] = None) -> int:
    print(json.dumps(r, indent=1, default=str))
    for a in r.get("accounts") or []:
        ex = a.get("executor") or {}
        print(f">>> {a.get('account_id')} [{a.get('account_class')}] {a.get('verdict')} {a.get('level')}"
              f" executed={bool(a.get('executed'))} venue_after={ex.get('venue_after')} -- {a.get('reason')}"
              f"{' / ' + str(ex.get('detail')) if ex.get('detail') else ''}")
    done = da._ts(r.get("done_at"))
    if pushed_at and done:
        print(f">>> latency push -> done: {(done - pushed_at).total_seconds():.1f}s"
              f" (seen -> done {r.get('seen_to_done_s')}s)")
    print(f">>> verdict: {r.get('verdict')}  {r.get('detail') or ''}")
    v = r.get("verdict")
    return {"applied": EXIT_OK, "dry_run": EXIT_OK, "partially_applied": EXIT_FAILED,
            "expired": EXIT_UNREADABLE}.get(v, EXIT_REFUSED if v in ("refused", "not_applied") else EXIT_FAILED)


def wait_receipt(record_id: str, *, timeout_s: float, pushed_at: Optional[datetime] = None) -> int:
    deadline = time.monotonic() + timeout_s
    path = "log_file?name=directed_actions&lines=200"
    while True:
        rc, doc = _diag(path)
        if rc == 3 and doc is None and time.monotonic() > deadline:
            print(f">>> could not reach the diag API directly; read it through the relay: issue title "
                  f"'[diag-request] {path}' (label vm-diag-request) and look for id {record_id}")
            return EXIT_UNREADABLE
        r = find_receipt(doc, record_id)
        if r:
            return print_receipt(r, pushed_at)
        if time.monotonic() > deadline:
            print(f">>> no receipt for {record_id} after {timeout_s:.0f}s; check "
                  f"log_file?name=directed_actions_watch_status and directed_actions_status")
            return EXIT_UNREADABLE
        time.sleep(10)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit", help="write + push a record, then poll its receipt")
    s.add_argument("--package", required=True)
    s.add_argument("--action", required=True, choices=da.ACTIONS)
    s.add_argument("--level", type=float, default=None, help="tighten_sl / move_sl / move_tp: the price")
    s.add_argument("--fraction", type=float, default=None, help="partial_close: fraction in (0, 1)")
    s.add_argument("--scope", default="package", help="package | <account_id> | <account_id>:<trade_id or ticket_id>")
    s.add_argument("--quote", default=None, help="the operator's words, VERBATIM (required)")
    s.add_argument("--quote-file", default=None)
    s.add_argument("--directed-by", default="manager")
    mode = s.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="every account decides; nothing is executed")
    mode.add_argument("--live", action="store_true", help="execute")
    s.add_argument("--wait", type=float, default=240.0, help="seconds to poll the receipt (0 = do not wait)")
    v = sub.add_parser("vm-pass", help="(VM) handle every new record at a pinned tip")
    v.add_argument("--ref", required=True)
    r = sub.add_parser("receipt", help="read one record's receipt")
    r.add_argument("--id", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "vm-pass":
        st = vm_pass(a.ref)
        print(json.dumps(st, default=str))
        return int(st.get("exit") or 0)
    if a.cmd == "receipt":
        rc, doc = _diag("log_file?name=directed_actions&lines=500")
        rec = find_receipt(doc, a.id)
        if rec is None:
            print(f">>> no receipt for {a.id} (diag rc={rc})")
            return EXIT_UNREADABLE
        return print_receipt(rec)
    record = build_record(a, _now())
    probs = da.problems(record, path=da.record_path(record["id"]))
    if probs:
        print(json.dumps({"refused": probs, "record": record}, indent=1))
        return EXIT_REFUSED
    ok, why = push_record(record)
    pushed_at = _now()
    if not ok:
        print(f">>> push failed: {why}")
        print(f">>> fallback (GitHub MCP create_or_update_file, create-only, no sha): branch {da.BRANCH}, "
              f"path {da.record_path(record['id'])}, content:\n{json.dumps(record, indent=1)}")
        return EXIT_UNREADABLE
    print(f">>> pushed {record['id']} as {why[:12]} to {da.BRANCH} at {pushed_at.isoformat()}")
    if a.wait <= 0:
        return EXIT_OK
    return wait_receipt(record["id"], timeout_s=a.wait, pushed_at=pushed_at)


if __name__ == "__main__":
    sys.exit(main())
