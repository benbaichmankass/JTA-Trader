#!/usr/bin/env python3
"""Stop hook: a LANE may not end a turn waiting on the manager without having woken it.

Why (operator, 2026-11-08): lane ML-ENTRY-EQ-STRUCT-LIVE ended its 12:31Z turn on "re-export awaits go-ahead"
and sat for ~2.5 h because it never fired the manager wake; the manager only found it when the operator asked for a status
update. The rule already existed (manager SKILL § "Manager <-> lane: PUSH plus POLL", dispatch block "WAKE THE MANAGER
when you ... are blocked"); nothing enforced it. This hook is the mechanical backstop: it reads the turn's transcript and,
when the session is a dispatched lane, the turn ends on a question / a wait / a block, and no report went out this turn
(manager wake via create_trigger+fire_trigger, send_later, or a PR comment), it blocks the stop ONCE with the exact call to make.

Never blocks twice in a row (stop_hook_active), never blocks a non-lane session, and fails open on any error, so it cannot
trap a session. Input: the Claude Code Stop-hook JSON on stdin ({transcript_path, stop_hook_active, ...}).

    python3 scripts/ops/lane_report_stop_hook.py --self-test
"""
from __future__ import annotations

import json
import re
import sys

LANE_MARKERS = re.compile(r"You are lane\b|dispatched by Manager Session|From Manager\b|lane:[A-Z0-9-]{3,}", re.IGNORECASE)
MANAGER_ID = re.compile(r"(?:Manager[^\n]{0,80}?|manager:)(session_[A-Za-z0-9]{16,})")
#: The manager itself (a fresh start or a rotation), never a lane. STOP-HOOK-ROTATION-MANAGER (2026-11-11):
#: the rotation brief opens "You are the JTA Trader manager (rotation)", which the old pattern missed, so the hook
#: blocked the manager's own stop with lane wording.
MANAGER_SELF = re.compile(
    r"\bYou are Manager Session\b|^\s*Manager Session \d{4}-\d{2}-\d{2}[a-z]|^\s*Run the operating loop"
    r"|\bYou are the (?:JTA[ -]Trader |Metis(?: Insights)? |ICT(?: bot)? )?manager\b(?!['’]s)",
    re.IGNORECASE)
REPORT_TOOLS = re.compile(r"fire_trigger|send_later|add_issue_comment|add_reply_to_pull_request_comment|send_message", re.IGNORECASE)
WAITING = re.compile(
    r"\b(awaits?|awaiting|waiting (?:on|for)|go[- ]ahead|needs? (?:your|the manager'?s?|an? operator|operator)|"
    r"blocked (?:on|by)|is blocked|am blocked|need input|needs input|should I|shall I|want me to|"
    r"please (?:confirm|approve|advise)|(?:confirm|approve) (?:to|before)|say go)\b",
    re.IGNORECASE,
)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            out.append(c.get("text", ""))
    return "\n".join(out)


def _is_real_user(entry: dict) -> bool:
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return any(isinstance(c, dict) and c.get("type") == "text" for c in content or []) and not any(
        isinstance(c, dict) and c.get("type") == "tool_result" for c in content or [])


def current_manager(users: list[dict]) -> str | None:
    """The manager id named in the MOST RECENT user turn that names one.

    STOP-HOOK-STALE-MANAGER (2026-11-14): this read the FIRST match in the whole transcript, so a lane dispatched by
    Manager Session 2026-11-11a (session_01AFoLuLyarNRcy3nziCep2U, retired 11-13) was still told to wake that dead session
    after a rotation handed it to 2026-11-13a. A rotation names the new manager in a later user turn; the latest one wins."""
    for u in reversed(users):
        ids = MANAGER_ID.findall(_text_of((u.get("message") or {}).get("content")))
        if ids:
            return ids[-1]
    return None


def _titled_manager(entries: list[dict]) -> bool:
    """True when this session titled itself "Manager Session ..." (manager SKILL § Start of session, step 1): a session
    whose first prompt does not read as a manager brief (a handoff doc, a resumed context) is still the manager."""
    for e in entries:
        if e.get("type") != "assistant":
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and "set_session_title" in str(c.get("name", "")):
                if re.match(r"\s*Manager Session\b", str((c.get("input") or {}).get("title") or "")):
                    return True
    return False


def decide(entries: list[dict]) -> str | None:
    """Return a block reason, or None to let the session stop."""
    users = [e for e in entries if _is_real_user(e)]
    if not users:
        return None
    first = _text_of((users[0].get("message") or {}).get("content"))
    all_user = "\n".join(_text_of((u.get("message") or {}).get("content")) for u in users)
    if not LANE_MARKERS.search(first) and not LANE_MARKERS.search(all_user):
        return None
    if MANAGER_SELF.search(first) \
            and not re.search(r"\bYou are lane\b", first):
        return None                                  # the manager itself, not a lane
    if _titled_manager(entries):
        return None                                  # it titled ITSELF "Manager Session ..." (manager skill step 1)
    last_user_idx = max(i for i, e in enumerate(entries) if _is_real_user(e))
    turn = entries[last_user_idx + 1:]
    for e in turn:
        if e.get("type") != "assistant":
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and REPORT_TOOLS.search(c.get("name", "")):
                return None                          # it reported this turn
    last_text = ""
    for e in reversed(turn):
        if e.get("type") == "assistant":
            t = _text_of((e.get("message") or {}).get("content"))
            if t.strip():
                last_text = t
                break
    tail = last_text.strip()[-1200:]
    if not tail or not (WAITING.search(tail) or tail.rstrip().endswith("?")):
        return None
    mgr = current_manager(users) or "<manager session id from your dispatch prompt>"
    return ("You are a dispatched lane and this turn ends waiting on a decision or blocked, but you have not told the manager. "
            "Lanes cannot be seen while idle: the manager only polls every 3 h (operator 2026-11-08, after a 2.5 h silent stall). "
            f"Before stopping: create_trigger(persistent_session_id=\"{mgr}\", prompt=<what you need, the options, your "
            "recommendation, what happens if no answer>) then fire_trigger(<trigger id>) with no run_once_at. If that tool "
            "is refused, comment on your PR instead. If you are not actually waiting on anyone, schedule your own next wake "
            "with send_later and keep going.")


def _load(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def main() -> int:
    try:
        hook = json.load(sys.stdin)
        if hook.get("stop_hook_active"):
            return 0
        reason = decide(_load(hook["transcript_path"]))
    except Exception:  # noqa: BLE001 -- fail open: a hook error must never trap a session
        return 0
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


# ---------------------------------------------------------------------------------------------- self-test
def _u(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _a(text=None, tool=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "name": tool, "input": {}})
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _tr():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def self_test() -> int:
    lane = _u("Build X. You are lane ML-ENTRY-EQ-STRUCT-LIVE, dispatched by Manager Session 2026-11-07a "
              "(session_01AFoLuJ3yguifJsDomuAzGx). WAKE THE MANAGER when blocked.")
    cases = [
        ("silent stall on a go-ahead BLOCKS", [lane, _a("checking", "Bash"), _tr(), _a("Run sha mismatch; re-export awaits go-ahead.")], True),
        ("ends on a question BLOCKS", [lane, _a("Should the unit use tau 0.1 or 0.2?")], True),
        ("woke the manager this turn passes", [lane, _a(None, "mcp__claude-code-remote__create_trigger"), _tr(),
                                                _a(None, "mcp__claude-code-remote__fire_trigger"), _tr(), _a("Waiting on the manager's go-ahead.")], False),
        ("send_later counts as a report", [lane, _a(None, "mcp__claude-code-remote__send_later"), _tr(), _a("Run in progress; awaiting the runner.")], False),
        ("PR comment counts as a report", [lane, _a(None, "mcp__github__add_issue_comment"), _tr(), _a("Blocked on the manager's merge.")], False),
        ("lane finishing normally passes", [lane, _a("PR #1 merged; deployed; observed. Close-out done.")], False),
        ("non-lane session never blocks", [_u("fix the typo in README"), _a("Done. Want me to also fix the other one?")], False),
        ("the manager itself never blocks", [_u("Run the operating loop (manager SKILL.md). From Manager lane:X"), _a("Should I merge #5?")], False),
        ("a rotation manager never blocks", [_u("You are Manager Session 2026-11-07a for JTA Trader. Dispatch lane:ML-X via From Manager triggers."),
                                             _a("Waiting on the operator's go-ahead?")], False),
        ("a rotation manager brief ('You are the JTA Trader manager (rotation)') never blocks",
         [_u("You are the JTA Trader manager (rotation). Dispatch lane:GENERAL via From Manager triggers."),
          _a("Waiting on the operator's go-ahead?")], False),
        ("a lane brief that QUOTES the manager is still a lane",
         [_u("You are lane GENERAL, dispatched by Manager Session 2026-11-11a (session_01AFoLuLyarNRcy3nziCep2U). "
             "The manager said: 'You are the JTA Trader manager'."), _a("Blocked; awaiting your go-ahead.")], True),
        ("'You are the manager's lane' is a lane, not the manager",
         [_u("You are the manager's GENERAL lane (session_01AFoLuLyarNRcy3nziCep2U); lane:GENERAL."),
          _a("Blocked; awaiting your go-ahead.")], True),
        ("a report in an EARLIER turn does not count", [lane, _a(None, "fire_trigger"), _tr(), _a("reported"),
                                                         _u("From Manager: GO. re-export."), _a("Re-export failed again; awaiting your go-ahead.")], True),
        ("empty transcript passes", [], False),
        ("a session that titled itself Manager Session never blocks (a handoff-doc start)",
         [_u("Read docs/claude/work/MANAGER-HANDOFF-2026-11-14.md. From Manager lane:GENERAL is AM-OPS."),
          {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__x__set_session_title",
                                                          "input": {"title": "Manager Session 2026-11-13a"}}]}},
          _tr(), _a("Waiting on the operator's go-ahead?")], False),
        ("a lane that titles a CHILD session is still a lane",
         [lane, {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__x__set_session_title",
                                                                "input": {"title": "AM-OPS catch-up"}}]}},
          _tr(), _a("Blocked; awaiting your go-ahead.")], True),
    ]
    bad = 0
    for name, entries, want in cases:
        got = decide(entries) is not None
        print(("PASS " if got == want else "FAIL ") + name)
        bad += got != want
    r = decide(cases[0][1])
    if not r or "session_01AFoLuJ3yguifJsDomuAzGx" not in r:
        print("FAIL block reason names the manager session id")
        bad += 1
    else:
        print("PASS block reason names the manager session id")
    rotated = [lane, _a("ok"), _u("From Manager: you now report to Manager Session 2026-11-13a (session_01AFoLuKXonDBdED7cNK7FhN)."),
               _a("Blocked; awaiting your go-ahead.")]
    r = decide(rotated)
    if not r or "session_01AFoLuKXonDBdED7cNK7FhN" not in r or "session_01AFoLuJ3yguifJsDomuAzGx" in r:
        print("FAIL after a rotation the block reason names the NEW manager, never the dispatching one")
        bad += 1
    else:
        print("PASS after a rotation the block reason names the NEW manager, never the dispatching one")
    print(f"{len(cases) + 2 - bad}/{len(cases) + 2} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
