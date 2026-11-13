#!/usr/bin/env python3
"""IS A WORK DIGEST DUE? — the one owner of the digest's interval decision.

WHY THIS EXISTS
───────────────
`work-digest.yml` declared `20 * * * *` (hourly) and GitHub did not honour it.
MEASURED 2026-09-02 over this repo:

  * work-digest.yml had FOUR runs in its entire life (`run_number: 4`), three of
    them scheduled, ~7h apart against a declared 6x/day. The 17:20Z and 18:20Z
    slots after the hourly change went live at 16:22Z both did not fire.
  * It is NOT a work-digest bug. Every scheduled producer in the repo lands
    hours late or skips days:
      probes.yml            `20 5 * * *`  generated_at 2026-09-01T10:13Z (+4h53m,
                                          and NOTHING on 09-02)
      due-list.yml          `50 5 * * *`  landed 2026-09-02T09:57Z (+4h07m)
      econ-calendar-produce `30 22 * * *` landed 2026-09-02T00:44Z (+2h14m)
      macro-valuation       `30 7 * * *`  landed 2026-09-01T12:52Z (+5h22m,
                                          and NOTHING on 09-02)
    Four different workflows, four different concurrency groups, one shape. So
    the cause is GitHub's scheduler, not any file in this repo, and it is not
    fixable from here.
  * `push` events on the SAME repo fire within seconds. Directly observed:
    merge 8c82be1a at 18:36:23Z triggered five push-event workflows at
    18:36:26Z. And main is BUSY — 34 merges in the 6h to 18:36Z, one every
    ~10.6 minutes.

So the digest moves onto the carrier this repo has measured to work, and this
module is the rate limiter that makes a per-push trigger produce an HOURLY
digest rather than one per merge.

⚠️ WHAT THIS DOES NOT FIX, STATED RATHER THAN GLOSSED
─────────────────────────────────────────────────────
A push-driven digest CANNOT produce a heartbeat while main is genuinely quiet —
there is no push to ride. The cron is deliberately KEPT as a best-effort second
carrier for exactly that case, but it is best-effort by measurement, not by
reputation. If the operator wants a guaranteed heartbeat through a quiet night,
that needs a carrier this repo does not own (a Claude Routine, which costs a
session per firing). That is an operator decision, not something to assume.

⚠️ IT IS NOT `work_digest._already_sent_today`, AND THAT LATCH IS INERT
──────────────────────────────────────────────────────────────────────
`work_digest.py` carries a one-digest-per-UTC-day latch whose docstring says
"One digest per UTC day. A latch, so a double invocation cannot double-ping."
It keys on `runtime_logs/work_digest_state.json`, and `runtime_logs/` is
`.gitignore`d (line 29), so on a GitHub runner — the only host that runs the
digest — the file never exists, `_already_sent_today()` always returns False,
and the latch guarantees nothing. Verified twice over: by the gitignore, and by
THREE digests landing on the same UTC day today (00:21Z #10710, 14:35Z #10813,
18:36Z #10836). **Field beats comment.**

That latch is left in place (removing a safety latch is a wider call than this
change), but the workflow now passes `--force` so the two mechanisms cannot
compete: an ephemeral per-runner latch and a committed receipt disagreeing about
whether to notify is exactly the two-sources-of-truth shape this repo keeps
paying for. **The receipt is the one authority on the interval.**

FOUR STATES, NEVER COLLAPSED
────────────────────────────
``due_never_ran``          no receipt at all — the first run, or the receipt has
                           never landed. NOT the same as "it broke".
``due_interval_elapsed``   a receipt exists and is older than the interval.
``due_unreadable``         **WE COULD NOT LOOK** — the receipt is corrupt or its
                           stamp will not parse. This is DUE, deliberately:
                           failing loud is the only safe direction on a
                           notification path, and it makes a broken receipt
                           announce itself as a duplicate digest rather than as
                           silence. Same polarity `_already_sent_today` chose
                           for its own unreadable case, and the opposite of the
                           polarity a *gate* would take.
``not_due``                a receipt exists and is inside the interval.

Collapsing `due_never_ran` into `due_unreadable` would report "not wired up yet"
as "corrupt", sending a reader to investigate a regression that never happened.

EXIT: 0 always in normal mode (so a `set -e` workflow step cannot be failed by a
routine "not due"); the verdict rides `--emit-github-output`. `--exit-code`
opts into 0=due / 1=not-due for shell predicate use. `--self-test` exits 0/1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT = REPO_ROOT / "docs" / "claude" / "work" / "WORK-DIGEST.json"

DUE_NEVER_RAN = "due_never_ran"
DUE_INTERVAL_ELAPSED = "due_interval_elapsed"
DUE_UNREADABLE = "due_unreadable"
NOT_DUE = "not_due"

#: Minutes between digests. 55 rather than 60 so an hourly cadence is not lost
#: to a few seconds of jitter between one push-triggered run and the next --
#: a 60 would make every second hour miss by a hair and silently halve the rate.
DEFAULT_INTERVAL_MINUTES = 55


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_receipt(path: Path = RECEIPT) -> Tuple[Optional[Dict[str, Any]], str]:
    """(receipt, read_state). ``absent`` and ``unreadable`` are opposite facts."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "unreadable"
    return (data, "read") if isinstance(data, dict) else (None, "unreadable")


#: WSD-S6A: the receipt now lives in the VM alert ledger (kind ``work_digest_receipt``), not in git.
LEDGER_URL = os.environ.get("BOT_API_BASE", "https://ict-bot.duckdns.org").rstrip("/") + \
    "/api/bot/alerts?kind=work_digest_receipt&limit=5"


def _service_headers() -> dict:
    """``Authorization: Bearer $DASHBOARD_API_TOKEN`` when the token is in the
    environment, else nothing. The read-only service credential the site gate
    accepts on GET/HEAD once ``SITE_AUTH_ENFORCE`` is on (UI-OAUTH-SIGNIN; the
    gate ignores it while off). Only ever sent to this project's own API."""
    tok = os.environ.get("DASHBOARD_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def read_ledger_receipt(url: str = "", timeout: float = 15.0) -> Tuple[Optional[Dict[str, Any]], str]:
    """(newest receipt, read_state) from the alert ledger. read_state is ``read`` |
    ``absent`` (ledger read, no receipt row yet) | ``could_not_look`` — never folded together."""
    import urllib.request  # noqa: PLC0415 — keep module import free
    try:
        req = urllib.request.Request(url or LEDGER_URL, headers=_service_headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            doc = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — a failed look is reported as such, not as "absent"
        return None, "could_not_look"
    if not isinstance(doc, dict) or doc.get("read_state") != "read":
        return None, "could_not_look"
    best: Optional[Dict[str, Any]] = None
    for row in doc.get("rows") or []:
        try:
            rec = json.loads(row.get("body") or "")
        except (ValueError, AttributeError):
            continue
        if isinstance(rec, dict) and _parse_ts(rec.get("generated_at")) and (
                best is None or _parse_ts(rec["generated_at"]) > _parse_ts(best["generated_at"])):
            best = rec
    return (best, "read") if best else (None, "absent")


def read_best_receipt(path: Path = RECEIPT, remote: bool = True
                      ) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """(receipt, read_state, ledger_state): the NEWER of the committed file (legacy fallback
    path) and the ledger row. ``ledger_state`` says whether the ledger was looked at."""
    f_rec, f_state = read_receipt(path)
    if not remote:
        return f_rec, f_state, "skipped"
    l_rec, l_state = read_ledger_receipt()
    if l_rec is not None and (f_rec is None or _parse_ts(l_rec["generated_at"])
                              >= (_parse_ts(f_rec.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc))):
        return l_rec, "read", l_state
    return f_rec, f_state, l_state


def grade(receipt: Optional[Dict[str, Any]], read_state: str, now: datetime,
          interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> Dict[str, Any]:
    """Pure decision, so the policy is arguable in tests rather than in YAML."""
    if read_state == "unreadable":
        return {"state": DUE_UNREADABLE, "due": True, "age_minutes": None,
                "why": ("the receipt exists and could not be read — we could not "
                        "look, which on a notification path is treated as DUE so "
                        "a broken receipt announces itself rather than going "
                        "silent")}
    if read_state == "absent" or receipt is None:
        return {"state": DUE_NEVER_RAN, "due": True, "age_minutes": None,
                "why": "no receipt has ever landed — this is the first digest"}

    ts = _parse_ts(receipt.get("generated_at"))
    if ts is None:
        return {"state": DUE_UNREADABLE, "due": True, "age_minutes": None,
                "why": ("the receipt carries no parseable `generated_at`, so it "
                        "cannot be shown to be recent, and an undateable receipt "
                        "must not suppress a notification")}

    age = (now - ts).total_seconds() / 60.0
    if age < 0:
        # A future stamp is not evidence of a recent digest; it is a broken
        # clock or a hand-edited receipt. Treat as unreadable, never as fresh.
        return {"state": DUE_UNREADABLE, "due": True, "age_minutes": round(age, 1),
                "why": ("the receipt is stamped in the FUTURE, so it cannot "
                        "attest a digest that has happened")}
    if age >= interval_minutes:
        return {"state": DUE_INTERVAL_ELAPSED, "due": True,
                "age_minutes": round(age, 1),
                "why": f"last digest was {age:.1f} min ago (>= {interval_minutes})"}
    return {"state": NOT_DUE, "due": False, "age_minutes": round(age, 1),
            "why": f"last digest was {age:.1f} min ago (< {interval_minutes})"}


def build_receipt(now: datetime, base: str, head: str, run_url: str = "",
                  trigger: str = "") -> Dict[str, Any]:
    """The receipt's shape lives HERE, beside its reader.

    One module owns both directions so a writer and a reader cannot drift into
    disagreeing about the field that decides whether the operator gets a ping.
    """
    return {
        "_doc": ("Receipt for the last WORK DIGEST that actually landed. Written "
                 "in the SAME commit as the pending-pings.jsonl row it attests, "
                 "so it can never claim a digest that did not reach the queue. "
                 "Read by scripts/ops/digest_due.py (the interval gate) and "
                 "scripts/ci/check_digest_liveness.py (the staleness guard)."),
        "schema": 1,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_base": base,
        "window_head": head,
        "trigger": trigger,
        "run_url": run_url,
    }


def render(verdict: Dict[str, Any]) -> str:
    age = verdict["age_minutes"]
    age_s = "n/a" if age is None else f"{age} min"
    return (f"digest-due: state={verdict['state']} due={str(verdict['due']).lower()} "
            f"last_digest_age={age_s}\n  {verdict['why']}")


# ───────────────────────────── self-test ─────────────────────────────

def _self_test() -> int:
    now = datetime(2026, 9, 2, 18, 0, 0, tzinfo=timezone.utc)
    fails = []

    def check(label: str, cond: bool) -> None:
        if not cond:
            fails.append(label)

    def stamped(minutes_ago: float, **kw):
        d = {"generated_at": (now - timedelta(minutes=minutes_ago))
             .strftime("%Y-%m-%dT%H:%M:%SZ")}
        d.update(kw)
        return d

    # Both directions: a due input fires and a fresh input stays quiet. One
    # direction proves the check runs, never that it discriminates.
    check("fresh receipt is not due",
          grade(stamped(10), "read", now)["state"] == NOT_DUE)
    check("fresh receipt reports due=False",
          grade(stamped(10), "read", now)["due"] is False)
    check("elapsed receipt is due",
          grade(stamped(90), "read", now)["state"] == DUE_INTERVAL_ELAPSED)
    check("elapsed receipt reports due=True",
          grade(stamped(90), "read", now)["due"] is True)

    # The boundary is inclusive at the interval, so a run landing exactly on
    # the cadence is not skipped.
    check("exactly at the interval is due",
          grade(stamped(DEFAULT_INTERVAL_MINUTES), "read", now)["due"] is True)
    check("one minute inside the interval is not due",
          grade(stamped(DEFAULT_INTERVAL_MINUTES - 1), "read", now)["due"] is False)

    # The four states are genuinely distinct -- collapsing any pair is the
    # defect this file is written against.
    check("absent grades never_ran, not unreadable",
          grade(None, "absent", now)["state"] == DUE_NEVER_RAN)
    check("unreadable grades unreadable, not never_ran",
          grade(None, "unreadable", now)["state"] == DUE_UNREADABLE)
    check("never_ran is due", grade(None, "absent", now)["due"] is True)
    check("unreadable is DUE, never suppressing",
          grade(None, "unreadable", now)["due"] is True)
    check("four states are distinct",
          len({DUE_NEVER_RAN, DUE_INTERVAL_ELAPSED, DUE_UNREADABLE, NOT_DUE}) == 4)

    # An undateable or future-dated receipt must not read as fresh -- both are
    # "we cannot show a digest happened", not "one just did".
    check("garbage stamp is unreadable, not fresh",
          grade({"generated_at": "not-a-date"}, "read", now)["state"] == DUE_UNREADABLE)
    check("missing stamp is unreadable, not fresh",
          grade({}, "read", now)["state"] == DUE_UNREADABLE)
    check("future stamp is unreadable, not fresh",
          grade(stamped(-120), "read", now)["state"] == DUE_UNREADABLE)

    # A custom interval actually binds -- a knob nothing reads is decoration.
    check("interval knob binds (tighter)",
          grade(stamped(30), "read", now, interval_minutes=20)["due"] is True)
    check("interval knob binds (wider)",
          grade(stamped(30), "read", now, interval_minutes=120)["due"] is False)

    # Naive timestamps are read as UTC rather than crashing.
    check("naive stamp parses as UTC",
          grade({"generated_at": "2026-09-02T17:00:00"}, "read", now)["due"] is True)

    # The receipt this module WRITES must be readable by the grader it ships
    # with -- a writer and reader that disagree is the whole failure class.
    rt = build_receipt(now, "abc", "main", trigger="push")
    back, st = ({k: v for k, v in rt.items()}, "read")
    check("own receipt round-trips to not_due",
          grade(back, st, now)["state"] == NOT_DUE)
    check("own receipt survives json", isinstance(json.dumps(rt), str))

    if fails:
        print("digest_due self-test FAILED:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("digest_due self-test OK")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES)
    ap.add_argument("--receipt", default=str(RECEIPT))
    ap.add_argument("--emit-github-output", action="store_true",
                    help="append due=true|false and state=... to $GITHUB_OUTPUT")
    ap.add_argument("--exit-code", action="store_true",
                    help="exit 0 when due, 1 when not (shell predicate use)")
    ap.add_argument("--no-ledger", action="store_true",
                    help="read only the committed file (tests, offline)")
    ap.add_argument("--print-window-head", action="store_true",
                    help="print the newest receipt's window_head (ledger or file) and exit")
    ap.add_argument("--record", action="store_true",
                    help="WRITE the receipt (call only after the digest is rendered)")
    ap.add_argument("--base", default="", help="--record: the window base ref")
    ap.add_argument("--head", default="", help="--record: the window head ref")
    ap.add_argument("--trigger", default="", help="--record: the triggering event")
    ap.add_argument("--run-url", default="", help="--record: this run's URL")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    # The verdict below is about the COMMITTED tree. Say so when that is
    # not the tree you edited. See
    # BL-20260917-THE-DIRTY-TREE-NOTICE-LIVES-ONLY-IN-RUN-GUARDS-SO-ALL-18-DIRECTLY-INVOCABLE-DIFF-SCOPED-GUARDS-STILL-GRADE-THE-WRONG-TREE-SILENTLY
    import pathlib  # noqa: PLC0415 — local, so importing this module stays free
    import sys as _sys  # noqa: PLC0415
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ci"))
    import _dirty_tree  # noqa: E402,PLC0415 — path shim above
    _dirty_tree.warn()


    if a.self_test:
        return _self_test()

    now = datetime.now(timezone.utc)
    path = Path(a.receipt)

    if a.record:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = build_receipt(now, a.base, a.head, a.run_url, a.trigger)
        path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        print(f"digest-due: receipt written {path} generated_at={rec['generated_at']}")
        return 0

    receipt, read_state, ledger_state = read_best_receipt(path, remote=not a.no_ledger)
    if a.print_window_head:
        print((receipt or {}).get("window_head", "") or "")
        return 0
    verdict = grade(receipt, read_state, now, a.interval_minutes)
    if ledger_state == "could_not_look":
        print("digest-due: ledger could not be read — graded on the committed file only")
    print(render(verdict))

    out = os.environ.get("GITHUB_OUTPUT")
    if a.emit_github_output and out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"due={str(verdict['due']).lower()}\n")
            fh.write(f"state={verdict['state']}\n")

    if a.exit_code:
        return 0 if verdict["due"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
