#!/usr/bin/env python3
"""Run the work digest on the VM's own clock and SEND it. MI-83, half (2).

⚠️ **THIS EXISTS BECAUSE GITHUB ACTIONS CRON IS NOT A CLOCK IN THIS REPO.**
``.github/workflows/work-digest.yml`` declares ``20 * * * *``. Measured over its
complete run history: **5 runs in a day, at :19, :10, :33 and :47** — never on
its declared minute, and 5 firings against 24 declared. ``probes.yml``'s first
scheduled run came ~4h50m late; ``due-list.yml``'s two landings were 4h41m and
4h07m late and 23h27m apart. A correct cron here is not evidence of a run, and
an ERRATIC one cannot carry a cadence the operator is relying on.

What DOES fire reliably on this system is the VM's own systemd timers:
``ict-git-sync.timer`` is observably pulling every ~5 minutes. So the digest
moves onto that clock — ``deploy/ict-work-digest.timer``, ``OnCalendar=hourly``.

⚠️ **A CLOUD ROUTINE WAS REFUSED AND MUST NOT BE PROPOSED.** Operator, verbatim
(2026-09-02): *"no cloud routine. We can't have anything that's gonna die at the
end of the session… You cannot create a Band Aid that's gonna get lost as soon
as the session is over."* A systemd unit on the VM is the opposite of that: it
outlives every session, and it is reinstalled by ``install_systemd_units.sh`` on
every deploy.

WHAT THIS DOES **NOT** DO, and why each omission is deliberate:

* **It does not write ``docs/claude/pending-pings.jsonl``, and it does not
  commit.** The workflow path must queue-then-commit because a GitHub runner has
  no way to reach Telegram. This runs ON the VM, where ``send_ping.enqueue`` is
  a local atomic file write into the bot's inbox, drained within ~5s. Routing it
  through the repo would add a PR plus a full required-check run (``pytest-run``
  alone is 12.9-14.6 min) to send one message, and would make every digest a
  merge to ``main``.
* **It does not call ``work_digest.main(--write)``.** That path carries a
  DAY-granular latch (``_already_sent_today``) against
  ``runtime_logs/work_digest_state.json``. ⚠️ That latch is INERT in CI —
  ``runtime_logs/`` is ``.gitignore``d, so a fresh runner never has the file —
  and it would be LIVE here, silently capping an hourly carrier at one digest
  per day. This runner keeps its own HOUR-granular latch, in its own receipt
  file, and never reads or writes the workflow's latch. The two paths cannot
  interfere.
* **It does not fetch the standing close-wedge ledger over diag.** The workflow
  has to (``runtime_logs/`` is VM-local, so the file is absent on a runner). On
  the VM the trader has already written it locally, so this reads the real file
  with no token, no network, and no way for a diag outage to degrade the
  section. ``work_digest.standing_wedges()`` still reports ``not_fetched`` for an
  absent file, so *we did not look* and *nothing is wedged* stay distinct.

THE RECEIPT IS THE POINT OF THE WHOLE EXERCISE. A cadence nobody can check is
how the repo got here: the standing rule is that *anything soaking needs an
alarm with a timer or a soak threshold, so that we know to get back to it*. Each
run stamps ``runtime_logs/work_digest_receipt.json`` with what it did, and that
file is allowlisted on ``/api/diag/log_file?name=work_digest_receipt`` — so
"has the hourly clock fired?" is answerable by READING, not by trusting a
``OnCalendar=`` line. The receipt is written on EVERY outcome, including the
failures, because a receipt that only appears on success cannot distinguish a
dead timer from a failing run.

Usage::

    python3 scripts/ops/work_digest_now.py              # send if the hour is due
    python3 scripts/ops/work_digest_now.py --dry-run    # render, send nothing
    python3 scripts/ops/work_digest_now.py --force      # ignore the hour latch
    python3 scripts/ops/work_digest_now.py --self-test
"""
# wiring: deploy/ict-work-digest.service <- deploy/ict-work-digest.timer
# (OnCalendar=hourly, Persistent=true). Installed by the deploy/*.timer glob in
# scripts/install_systemd_units.sh -- no edit to that script is needed, and none
# was made. Both units are in diag's _CANONICAL_UNITS so /api/diag/services can
# report them.

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# ⚠️ ANCHORED TO REPO_ROOT, NOT a data-dir helper. This runs from
# ict-work-digest.service, which carries no data-dir drop-in, so it writes to
# /home/ubuntu/ict-trading-bot/runtime_logs/ — the same anchor
# notify_on_pull.py uses, and the same one diag's _PENDING_PINGS_DELIVERED
# entry had to name. A reader pointed at the OTHER path reports an eternally
# absent file, which is the writer/reader split that hid the hourly-snapshot
# balance stall for ~3 weeks (BL-20260611-M15-2).
RECEIPT = REPO_ROOT / "runtime_logs" / "work_digest_receipt.json"

WINDOW = "1 hour ago"


def _resolve_base(head: str = "HEAD") -> tuple[str | None, str]:
    """``(base_ref, basis)`` for the window start. ``None`` == could not resolve.

    ``basis`` is never collapsed: ``window`` (a real commit older than the
    window) · ``root_fallback`` (the repo was quiet for longer than the window,
    so we report over ALL history — a loud over-report is recoverable, a silent
    empty one is not) · ``unresolved`` (**we could not look**; git refused).
    """
    try:
        out = subprocess.run(
            ["git", "rev-list", "-1", f"--before={WINDOW}", head],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip(), "window"
        root = subprocess.run(
            ["git", "rev-list", "--max-parents=0", head],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
        )
        if root.returncode == 0 and root.stdout.split():
            return root.stdout.split()[-1], "root_fallback"
    except (subprocess.SubprocessError, OSError):
        pass
    return None, "unresolved"


def _read_receipt() -> dict:
    try:
        data = json.loads(RECEIPT.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # ⚠️ An unreadable latch SENDS rather than suppresses — the same
        # direction work_digest._already_sent_today takes, and for the same
        # reason: on a notification path a broken latch must announce itself as
        # a duplicate, never as silence.
        return {}


def _write_receipt(**fields) -> None:
    """Stamp the receipt. Best-effort, and written on EVERY outcome."""
    payload = {"at": datetime.now(timezone.utc).isoformat(), **fields}
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        tmp = RECEIPT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(RECEIPT)
    except OSError as exc:
        print(f"work-digest-now: WARNING could not write receipt: {exc}")


def run(dry_run: bool = False, force: bool = False) -> int:
    from scripts.ops.work_digest import build_digest, render  # noqa: PLC0415

    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    prior = _read_receipt()
    if prior.get("lastSentHour") == hour and not force:
        print(f"work-digest-now: already sent for {hour}Z — not sending a second "
              f"(use --force to override)")
        _write_receipt(outcome="skipped_hour_latch", hour=hour,
                       lastSentHour=prior.get("lastSentHour"))
        return 0

    due, why = _cadence_gate(force)
    if not due:
        print(f"work-digest-now: not due at the operator's cadence ({why}) — not sending")
        _write_receipt(outcome="skipped_cadence", hour=hour, cadence=why,
                       lastSentHour=prior.get("lastSentHour"))
        return 0

    base, basis = _resolve_base()
    if base is None:
        # We could not establish a window. That is NOT a quiet hour, and it must
        # not render as one — say so on the receipt and exit nonzero so systemd
        # marks the unit failed and the state is visible in `systemctl status`.
        print("work-digest-now: could not resolve a window base — NOT the same "
              "as 'nothing happened'. Sending nothing.")
        _write_receipt(outcome="window_unresolved", hour=hour,
                       lastSentHour=prior.get("lastSentHour"))
        return 1
    if basis == "root_fallback":
        print(f"work-digest-now: no commit older than {WINDOW!r}; falling back "
              f"to the root commit — this digest covers ALL history.")

    digest = build_digest(base, "HEAD")
    aw, prep = _attention_prepare(dry_run)
    research, rsnap = _research_prepare()
    work, wsnap = _work_prepare()
    message = compose_update(hour, prep, render(digest), digest, research, work)
    priority = prep["priority"]
    print(message)

    if dry_run:
        _write_receipt(outcome="dry_run", hour=hour, base=base, windowBasis=basis,
                       digestState=digest.get("digestState"),
                       lastSentHour=prior.get("lastSentHour"))
        if aw:
            aw.commit(prep, "dry_run")
        return 0

    # PHONE-KEEPALIVE: a stale phone heartbeat is its own SYSTEM-channel alert (+ one recovery message), not only a
    # line in the collapsed "Manager watch" section below. Never raises.
    try:
        from scripts.ops import phone_hb_alert  # noqa: PLC0415
        phone_hb_alert.run()
    except Exception as exc:  # noqa: BLE001
        print(f"work-digest-now: phone-hb-alert failed: {exc}")

    from send_ping import enqueue  # noqa: PLC0415

    try:
        # TELEGRAM-CHANNELS: the MANAGER channel (the Claude bot), sent as
        # Telegram HTML so its sections collapse.
        path = enqueue(message, priority=priority, target="manager",
                       parse_mode="HTML")
    except (OSError, ValueError) as exc:
        print(f"work-digest-now: FAILED to enqueue: {exc}")
        _write_receipt(outcome="enqueue_failed", hour=hour, base=base,
                       windowBasis=basis, error=str(exc),
                       lastSentHour=prior.get("lastSentHour"))
        if aw:
            aw.commit(prep, "enqueue_failed")  # receipt only; state NOT advanced
        return 1

    # lastSentHour advances ONLY after a successful enqueue, so a failed run is
    # retried by the next firing rather than latched out of it.
    _write_receipt(outcome="sent", hour=hour, lastSentHour=hour, base=base,
                   windowBasis=basis, digestState=digest.get("digestState"),
                   queued=str(path), attention="committed" if aw else "failed")
    if aw:
        aw.commit(prep, "sent")
    if rsnap is not None:
        from scripts.ops import research_digest  # noqa: PLC0415
        research_digest.commit(rsnap, path=RESEARCH_CURSOR)
    if wsnap is not None:
        from scripts.ops import work_section  # noqa: PLC0415
        work_section.commit(wsnap, path=WORK_CURSOR)
    _mark_sent()
    print(f"work-digest-now: queued {path} — the bot drains within ~5s")
    return 0 if aw else 1


#: TELEGRAM-CHANNELS (2026-10-11): the research-queue section's cursor. Module
#: attribute so tests can point it at a tmp dir; advanced only after a send.
RESEARCH_CURSOR = REPO_ROOT / "runtime_logs" / "research_digest_cursor.json"


#: TELEGRAM-CHANNELS (2026-10-11): the WORK section's cursor (same pattern).
WORK_CURSOR = REPO_ROOT / "runtime_logs" / "work_section_cursor.json"


def _work_prepare():
    """``(section_data, snapshot)`` for the WORK section, or an error dict —
    a failure is SAID in the message, never rendered as "nothing new"."""
    try:
        from scripts.ops import work_section  # noqa: PLC0415
        d = work_section.build(prev=work_section.read_cursor(WORK_CURSOR))
        return d, d["snapshot"]
    except Exception as exc:  # noqa: BLE001
        print(f"work-digest-now: work section FAILED: {exc}")
        return {"error": f"{type(exc).__name__}: {exc}"}, None


def _cadence_gate(force: bool) -> tuple[bool, str]:
    """Part C: the ONE shared gate (src/runtime/telegram_settings.is_due)
    decides whether the MANAGER update is due at the operator's cadence."""
    if force:
        return True, "forced"
    try:
        from src.runtime import telegram_settings  # noqa: PLC0415
        return telegram_settings.is_due("manager_update")
    except Exception as exc:  # noqa: BLE001 — a broken gate SENDS
        return True, f"gate unreadable ({type(exc).__name__}) — sending"


def _mark_sent() -> None:
    try:
        from src.runtime import telegram_settings  # noqa: PLC0415
        telegram_settings.mark_sent("manager_update")
    except Exception as exc:  # noqa: BLE001
        print(f"work-digest-now: WARNING could not stamp cadence: {exc}")


def _research_prepare():
    """``(section_data, snapshot)`` for the RESEARCH QUEUE section, or
    ``(None, None)`` when building it failed — which the message then SAYS
    (a failure here must not stop the update, nor read as "nothing new")."""
    try:
        from scripts.ops import research_digest  # noqa: PLC0415
        prev = research_digest.read_cursor(RESEARCH_CURSOR)
        d = research_digest.build(prev=prev)
        return d, d["snapshot"]
    except Exception as exc:  # noqa: BLE001 — loud, in the message itself
        print(f"work-digest-now: research section FAILED: {exc}")
        return {"error": f"{type(exc).__name__}: {exc}"}, None


#: The "nothing to decide" line. It rides the HEADER; the Needs-you section is
#: only built when there is an ask, or the same line printed twice.
NO_ASK_PREFIX = "🟢 No new decisions for you"


def route_attention(prep: dict) -> tuple[str, str, str]:
    """Split the attention pass's messages by WHO acts (operator, 2026-10-11):
    ``Needs you`` holds ONLY genuine operator decisions (❓ ask_operator);
    research units needing a read (🔎 needs_review) are research-ops' job and
    ride the research section; everything else (soaks, blocker-watch, silence
    alarms, the daily summary) is the manager's and rides "Manager watch".
    Returns ``(needs_you, research_ops, watch)``."""
    msgs = prep.get("msgs")
    if msgs is None:   # an older prepare() without the split: keep its block
        return str(prep.get("block") or "—"), "", ""
    ask = [m for m in msgs if m.startswith("❓")]
    rops = [m for m in msgs if m.startswith("🔎")]
    rest = [m for m in msgs if not m.startswith(("❓", "🔎"))]
    n_open = (prep.get("receipt") or {}).get("ask_operator_open")
    tail = f"open ask_operator items: {'—' if n_open is None else n_open} (GET /api/bot/work/report)"
    needs = ("\n".join(ask) + "\n" + tail) if ask else f"{NO_ASK_PREFIX} · {tail}"
    return needs, "\n".join(rops), "\n\n".join(rest)


def compose_update(hour: str, prep: dict, work_text: str, digest: dict,
                   research: dict | None, work: dict | None = None) -> str:
    """The MANAGER channel's regular status update — operator 2026-10-11:
    *"divided into clear collapsible sections"*. A visible 1–3 line headline,
    then named expandable sections; fitted to Telegram's 4096-char cap by
    trimming section bodies with an explicit count of what was dropped.
    """
    from scripts.ops import research_digest  # noqa: PLC0415
    from src.units.ui.telegram_format import Section, render_html_fitted  # noqa: PLC0415

    needs, research_ops, watch = route_attention(prep)
    attention_line = (needs.splitlines() or ["—"])[0][:200]
    # No ask -> the header already says so; a collapsed section repeating it
    # is the duplicate "No new decisions" line (TELEGRAM-CHANNELS-3 item 4).
    needs_section = not needs.startswith(NO_ASK_PREFIX)
    if research is None or "error" in (research or {}):
        r_head = "🔬 research: ⛔ section FAILED to build — queue NOT checked"
        r_body = ("⛔ The research-queue section failed to build "
                  f"({(research or {}).get('error', 'unknown')}). This is 'we could "
                  "not look', NOT 'nothing new'.")
    else:
        r_head = research_digest.headline(research)
        r_body = research_digest.render_body(research)
    # TELEGRAM-CHANNELS (2026-10-11): the WORK section carries the same detail
    # as the research one (scripts/ops/work_section.py). The legacy register
    # diff (``work_text``) is the fallback only when that section failed —
    # its standing close-wedge block now rides the SYSTEM health check.
    from scripts.ops import work_section  # noqa: PLC0415
    if work is not None and "error" not in work:
        w_head = work_section.headline(work)
        w_body = work_section.render_body(work)
    else:
        w_head = "🛠 work: ⛔ section FAILED to build — checklist NOT checked"
        w_body = ("⛔ The work section failed to build "
                  f"({(work or {}).get('error', 'not built')}). This is 'we could not "
                  "look', NOT 'nothing new'. Legacy register diff "
                  f"(state {digest.get('digestState') or '—'}) follows:\n" + work_text)
    header = "\n".join([f"🧭 Manager update · {hour[:10]} {hour[11:13]}:00Z",
                        attention_line, f"{r_head} · {w_head}"])
    if research_ops:
        r_body = (r_body + "\n\n🔎 For research-ops (not you):\n" + research_ops).strip()
    sections = [Section(summary="Needs you — decisions only", body=needs, priority=10)] \
        if needs_section else []
    sections += [
        Section(summary="Research queue — new since last update", body=r_body, priority=20),
        Section(summary="Work — blocked · didn't work · in flight · next · shipped · verified",
                body=w_body, priority=30),
    ]
    if watch:
        sections.append(Section(summary="Manager watch — FYI, the manager acts on these",
                                body=watch, priority=40))
    return render_html_fitted(header=header, sections=sections)


def _attention_prepare(dry_run: bool):
    """WORK-SYSTEM (operator decision 2026-10-04 ~15:30Z): this ONE hourly
    message also carries the attention block — NEW actionable items first
    (new ask_operator, soak transitions, silence alarms), the daily ranked
    summary once a day, else one quiet line. ``attention_watch.prepare()``
    writes nothing; ``commit()`` runs only after the enqueue succeeds. A
    failure here must not stop the change digest, so it is isolated and the
    message SAYS the block is missing rather than omitting it silently."""
    try:
        from scripts.ops import attention_watch  # noqa: PLC0415
        return attention_watch, attention_watch.prepare(dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — loud, in the message itself
        print(f"work-digest-now: attention block FAILED: {exc}")
        return None, {"block": f"⛔ attention block FAILED to build ({type(exc).__name__}: "
                               f"{exc}) — due items, soaks and alarms NOT checked this hour.",
                      "priority": "high"}


def _self_test() -> int:
    """A detector whose failure path is never exercised is indistinguishable
    from one that always passes."""
    ok = True

    def check(n: int, label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"  self-test {n} ({label}): {'PASS' if passed else f'FAIL {detail}'}")

    base, basis = _resolve_base()
    check(1, "a window base resolves in a real repo",
          base is not None and basis in ("window", "root_fallback"), str(basis))

    b2, basis2 = _resolve_base("definitely-not-a-ref-000")
    check(2, "an unresolvable head reads 'unresolved', never a quiet hour",
          b2 is None and basis2 == "unresolved", f"{b2} {basis2}")

    check(3, "the receipt is anchored to the repo root, not a data dir",
          RECEIPT == REPO_ROOT / "runtime_logs" / "work_digest_receipt.json",
          str(RECEIPT))

    # 4: the workflow's day latch must not be this runner's latch.
    from scripts.ops.work_digest import STATE  # noqa: PLC0415
    check(4, "does NOT share work_digest's day-granular latch file",
          RECEIPT != STATE, f"{RECEIPT} == {STATE}")

    print("work-digest-now self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="render and stamp the receipt, but send nothing")
    ap.add_argument("--force", action="store_true",
                    help="send even if this hour already sent")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    return run(dry_run=a.dry_run, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
