#!/usr/bin/env python3
"""short_hold_write -- the ONLY way a short-hold lane writes its in-trade decision row (DESK-SHORT-HOLD-LANE).

A short-hold lane is ONE session that lives for ONE trade (design § 6.2 "per-trade spawned lane"). Every
~5 minutes it reads the newest in-trade packet the VM landed for its package and decides one of
hold / tighten_sl / move_tp / partial_close / change_size / close -- the best trading decision now. It never
hand-builds the row. It writes a short DRAFT and runs

    git fetch -q --depth 1 origin main && git show origin/main:.claude/skills/trading-desk/short_hold_write.py \
        | python3 - --package <pkg> DRAFT.json

which, in order:
1. reads ``comms/live_review/short_hold/<pkg>/latest.json`` (the VM's packet envelope) from the branch tip;
2. COMPILES the full live-review row (schema ``comms/schema/live_review.schema.json``) from the draft: every id,
   timestamp, state, option and account read is copied from the packet, so none can be mistyped;
3. VALIDATES it with ``scripts/ci/check_live_review_records.py`` itself, loaded from origin/main (the CI guard and
   the mirror run the same function: there is no second copy of the rules), plus the short-hold rules below;
4. writes ONE commit on the branch tip -- the packet, its priced table, the row, a latency line and, when the lane
   used outside sources, its ``external_context`` lines (INTO training, flagged source: external) and feed-gap rows
   (operator 2026-10-27 ~07:12Z) -- pushed WITHOUT
   force, so a moved branch is a rejected push that is re-read and retried, never a lost line.

Short-hold rules (on top of the guard):
- the action is one of ``ACTIONS``; ``flag_mechanics`` is required when the packet's mechanics are not ``match``;
- BOTH BRACKETS ALWAYS (operator 2026-10-26): a tighten / move_tp names a level, a tighten moves the stop toward
  the mark and stays on the loss side of it, a move_tp stays on the profit side; nothing removes a bracket;
- every call carries ``reason`` and ``judgement_confidence`` (operator: *"all trade actions, as long as they have
  reasoning and confidence attached"*); ``hold`` is a real, graded call, never a silent default.

``--dry-run`` (the recommend-only proof): the row goes to ``DRYRUN_REVIEWS`` instead of ``reviews.jsonl``. The VM
rows watcher reads ONLY ``reviews.jsonl`` on ``live-review/rows`` (``src/runtime/live_review_rows_watch.py``), so
a dry-run row is never applied; run the dry run on its own branch as well (``--branch``).

Exit: 0 written (or ``--check`` clean) / 1 refused / 2 could_not_look|could_not_write / 3 nothing_due|closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timezone

BRANCH = "live-review/rows"
REVIEWS = "comms/live_review/reviews.jsonl"
DRYRUN_REVIEWS = "comms/live_review/short_hold/dryrun_reviews.jsonl"
LATENCY = "comms/live_review/short_hold/latency.jsonl"
ENVELOPE = "comms/live_review/short_hold/{pkg}/latest.json"
PACKETS = "comms/live_review/packets/{rid}.json"
VALIDATOR = "scripts/ci/check_live_review_records.py"
SCHEMA = "comms/schema/live_review.schema.json"
ACTIONS = ("hold", "tighten_sl", "move_tp", "partial_close", "change_size", "close", "flag_mechanics")
CONFIDENCE = ("measured", "suggestive", "anecdote")
DRAFT_KEYS = {"action", "level", "size_fraction", "size_multiplier", "reason", "judgement_confidence", "confidence",
              "context_flags", "session", "external_context"}
EXTERNAL = "comms/live_review/short_hold/external_context.jsonl"
FEED_GAPS = "comms/live_review/short_hold/feed_gaps.jsonl"
INFLUENCE = ("decisive", "supporting", "checked_only")
GAP_CLASSES = ("news", "funding", "orderbook", "calendar", "onchain", "macro", "other")
# DESK-14: summary + content (hashed, never stored) + the feed-gap name/class are required beside the original keys.
EC_KEYS = {"query_or_url", "source", "retrieved_at", "extracted", "why_packet_insufficient", "influence",
           "summary", "content", "gap_class", "feed_gap"}
MODEL_TIER = "sonnet-tier (short-hold lane)"
TRIGGER_EVENT = "short_hold"


class Refused(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def packet_sha(packet: dict) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- compile

def _options(packet: dict) -> list[dict]:
    """The packet's priced options in the row's shape; an unpriced cell carries null numbers."""
    out = []
    for o in (packet.get("priced_options") or {}).get("options") or []:
        n = o.get("n")
        n = n if isinstance(n, int) and not isinstance(n, bool) else None
        priced = o.get("state") in (None, "priced", "measured") and n
        act = "hold" if o.get("action") == "hold" else "tighten_sl"
        out.append({"action": act, "level": None, "n": n,
                    "mean_r": o.get("mean_r") if priced else None, "sd_r": o.get("sd_r") if priced else None,
                    "worst_r": o.get("worst_r") if priced else None, "net": True if priced else None})
    return out


def compile_row(draft: dict, env: dict, *, now: datetime) -> dict:
    """The full row from the lane's draft and the VM's packet envelope. Raises Refused."""
    problems = [f"draft key {k!r} is not allowed (everything else is derived from the packet)"
                for k in sorted(set(draft) - DRAFT_KEYS)]
    packet = env.get("packet")
    if not isinstance(packet, dict):
        raise Refused(["envelope has no packet"])
    if env.get("packet_sha") != packet_sha(packet):
        problems.append("envelope packet_sha does not match its packet (corrupt envelope: could_not_look)")
    act = draft.get("action")
    if act not in ACTIONS:
        problems.append(f"action must be one of {ACTIONS}, got {act!r}")
    mech = packet.get("mechanics") or {}
    if mech.get("verdict") != "match" and act != "flag_mechanics":
        problems.append(f"mechanics verdict is {mech.get('verdict')!r}: the only call is flag_mechanics")
    reason = str(draft.get("reason") or "").strip()
    conf = draft.get("judgement_confidence")
    if not reason:
        problems.append("reason is required on every call")
    if not (_num(conf) and 0 <= conf <= 1):
        problems.append("judgement_confidence in [0, 1] is required on every call")
    if draft.get("confidence", "anecdote") not in CONFIDENCE:
        problems.append(f"confidence must be one of {CONFIDENCE}")
    flags = draft.get("context_flags") or []
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        problems.append("context_flags must be a list of strings")
    problems += bracket_problems(draft, packet, env.get("short_hold") or packet.get("short_hold") or {})
    problems += external_problems(draft.get("external_context"), now)
    if problems:
        raise Refused(problems)

    pkg = packet["order_package_id"]
    rid = packet["review_id"]
    hold_like = act in ("hold", "flag_mechanics")
    route = "operator_ask" if act == "flag_mechanics" else ("none" if act == "hold" else "recommended")
    mandate = None if hold_like else ("MD-LIVE-TIGHTEN-SL" if act == "tighten_sl" else "MD-TRADE-DESK")
    bounds = packet.get("account_bounds") or []
    level = draft.get("level") if act in ("tighten_sl", "move_tp") else None
    rec = {"action": act, "level": level, "level_atr": None, "ev_delta_r": None, "worst_case_delta_r": None,
           "basis": "mechanics" if act == "flag_mechanics" else "judgement",
           "confidence": draft.get("confidence", "anecdote"),
           "evidence_source": "none" if act == "flag_mechanics" else "judgement",
           "judgement_confidence": None if act == "flag_mechanics" else conf, "reason": reason,
           "size_fraction": draft.get("size_fraction") if act == "partial_close" else None,
           "size_multiplier": draft.get("size_multiplier") if act == "change_size" else None}
    sh = env.get("short_hold") or packet.get("short_hold") or {}
    atr = sh.get("atr")
    if level is not None and _num(atr) and atr > 0 and _num(sh.get("mark")):
        rec["level_atr"] = round(abs(sh["mark"] - level) / atr, 4)
    st = packet.get("state") or {}
    return {
        "schema_version": 1, "review_id": rid, "reviewed_at": _iso(now), "order_package_id": pkg, "trade_id": None,
        "leg": packet.get("leg"), "accounts": [b["account_id"] for b in bounds],
        "trigger": {"event": TRIGGER_EVENT, "level": env.get("bar") or sh.get("bar"),
                    "l0_snapshot_at": env.get("built_at")},
        "info_cutoff_at": packet.get("info_cutoff_at"),
        "state": {k: st.get(k) for k in ("open_r", "peak_r", "peak_provenance", "giveback_r", "bars_held", "sl", "tp",
                                         "atr_now_over_entry", "regime_cell_now", "regime_cell_entry")},
        "features_at_review": packet.get("features_at_review") or {},
        "mechanics": {"verdict": mech.get("verdict"), "evidence": mech.get("evidence")},
        "options": _options(packet), "outcome_table_source": env.get("table_path") if env.get("table") else None,
        "recommendation": rec, "judge_prior": None, "applied": False,
        "apply_policy": {"bound_r": 0.25, "within_bound": None, "tighten_r": None},
        "shadow_policy": {"bound_r": 0.5, "within_bound": None, "would_apply": None, "tighten_r": None},
        "context_flags": list(flags) + ([f"external_context: {len(draft['external_context'])} source(s), see {EXTERNAL}"]
                                        if draft.get("external_context") else []),
        "account_reads": [{"account_id": b["account_id"], "account_class": b.get("account_class"),
                           "read": "no_action" if hold_like else (b.get("read_if_amend") or "unknown"),
                           "evidence": b.get("evidence")} for b in bounds],
        "disposition": {"route": route, "mandate": mandate, "action_issue": None, "applied_at": None,
                        "verified_readback": None},
        "model": MODEL_TIER, "session": str(draft.get("session") or "unknown"), "prompt_sha": None, "skill_sha": None,
        "packet_sha": env.get("packet_sha"),
    }


def bracket_problems(draft: dict, packet: dict, sh: dict) -> list[str]:
    """BOTH BRACKETS ALWAYS: a call may move a bracket, never remove one, never put it on the wrong side."""
    act, level = draft.get("action"), draft.get("level")
    st = packet.get("state") or {}
    side = (packet.get("context") or {}).get("direction")
    mark, sl = sh.get("mark"), st.get("sl")
    out = []
    if act in ("tighten_sl", "move_tp"):
        if not (_num(level) and level > 0):
            return [f"{act} requires a price level > 0 (a bracket is moved, never removed)"]
        if side not in ("long", "short") or not _num(mark):
            return [f"{act}: the packet has no direction or 5-min mark; cannot check the bracket side (could_not_look)"]
        long_ = side == "long"
        if act == "tighten_sl":
            if (level >= mark) if long_ else (level <= mark):
                out.append(f"tighten_sl level {level} is not on the loss side of the mark {mark}")
            if _num(sl) and ((level <= sl) if long_ else (level >= sl)):
                out.append(f"tighten_sl level {level} does not tighten the stop {sl} (widening is not this lane's call)")
        if act == "move_tp" and ((level <= mark) if long_ else (level >= mark)):
            out.append(f"move_tp level {level} is not beyond the mark {mark} on the profit side")
    elif level is not None and act != "flag_mechanics":
        out.append(f"{act} takes no level")
    if act == "partial_close":
        f = draft.get("size_fraction")
        if not (_num(f) and 0 < f < 1):
            out.append("partial_close needs size_fraction in (0, 1) (a full exit is close)")
    elif draft.get("size_fraction") is not None:
        out.append(f"{act} takes no size_fraction")
    if act == "change_size":
        m = draft.get("size_multiplier")
        if not (_num(m) and m > 0 and m != 1):
            out.append("change_size needs size_multiplier > 0 and != 1 (< 1 reduces, > 1 adds)")
    elif draft.get("size_multiplier") is not None:
        out.append(f"{act} takes no size_multiplier")
    return out


def external_problems(ec, now: datetime) -> list[str]:
    """external_context[] (operator 2026-10-27 ~07:12Z): every outside source Claude used, point-in-time, with the
    values it used; it goes into training (flagged source: external) and raises a feed-gap row."""
    if ec is None:
        return []
    if not isinstance(ec, list):
        return ["external_context must be a list of entries"]
    out = []
    for i, e in enumerate(ec):
        if not isinstance(e, dict) or set(e) != EC_KEYS:
            out.append(f"external_context[{i}] must have exactly {sorted(EC_KEYS)}")
            continue
        t = _ts(e["retrieved_at"])
        if t is None or t > now:
            out.append(f"external_context[{i}].retrieved_at must be a time at or before the decision's judged_at "
                       "(operator 2026-10-27, 'Use judged_at'; not the packet's info_cutoff_at)")
        if e["gap_class"] not in GAP_CLASSES:
            out.append(f"external_context[{i}].gap_class must be one of {GAP_CLASSES}")
        if e["influence"] not in INFLUENCE:
            out.append(f"external_context[{i}].influence must be one of {INFLUENCE}")
        if not isinstance(e["extracted"], dict) or not e["extracted"]:
            out.append(f"external_context[{i}].extracted must hold the field/value pairs actually used")
        if not all(str(e[k] or "").strip() for k in ("query_or_url", "source", "why_packet_insufficient", "summary",
                                                     "content", "feed_gap")):
            out.append(f"external_context[{i}]: query_or_url, source, summary, content, feed_gap and "
                       "why_packet_insufficient are required")
    return out


def external_lines(row: dict, ec: list) -> tuple[list[dict], list[dict]]:
    """(training rows, feed-gap rows). The extracted values are stored here point-in-time so a replay or a training
    run reproduces them without re-fetching; DESK-11 / CJ-2 read them as a feature block flagged source: external."""
    base = {"review_id": row["review_id"], "order_package_id": row["order_package_id"], "leg": row["leg"],
            "decided_at": row["reviewed_at"], "info_cutoff_at": row["info_cutoff_at"], "source_flag": "external"}
    train = [dict(base, **{k: v for k, v in e.items() if k != "content"},
                  content_sha256=hashlib.sha256(str(e["content"]).encode()).hexdigest()) for e in ec]
    gaps = [{"review_id": row["review_id"], "decided_at": row["reviewed_at"], "leg": row["leg"],
             "source": e["source"], "fields": sorted(e["extracted"]), "influence": e["influence"],
             "gap_class": e["gap_class"], "feed_gap": e["feed_gap"],
             "why_packet_insufficient": e["why_packet_insufficient"]} for e in ec]
    return train, gaps


# ----------------------------------------------------------------------------- git

def git(*args: str, cwd: str | None = None, input: bytes | None = None, env: dict | None = None):
    return subprocess.run(["git", *args], cwd=cwd, input=input, capture_output=True,
                          env={**os.environ, **(env or {})}, check=False)


def show(cwd: str, ref: str, path: str) -> bytes | None:
    r = git("show", f"{ref}:{path}", cwd=cwd)
    return r.stdout if r.returncode == 0 else None


def fetch(cwd: str, branch: str) -> str | None:
    r = git("fetch", "-q", "--depth", "1", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", cwd=cwd)
    return f"origin/{branch}" if r.returncode == 0 else None


def commit_files(cwd: str, tip: str, files: dict[str, str], message: str) -> str | None:
    """One commit on `tip` writing every path in `files`, built with plumbing (the sparse worktree is untouched)."""
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index"), "GIT_AUTHOR_NAME": "Claude", "GIT_COMMITTER_NAME": "Claude",
               "GIT_AUTHOR_EMAIL": "noreply@anthropic.com", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
        if git("read-tree", tip, cwd=cwd, env=env).returncode:
            return None
        for path, text in files.items():
            h = git("hash-object", "-w", "--stdin", cwd=cwd, input=text.encode())
            if h.returncode or git("update-index", "--add", "--cacheinfo",
                                   f"100644,{h.stdout.decode().strip()},{path}", cwd=cwd, env=env).returncode:
                return None
        tree = git("write-tree", cwd=cwd, env=env)
        if tree.returncode:
            return None
        c = git("commit-tree", tree.stdout.decode().strip(), "-p", tip, "-m", message, cwd=cwd, env=env)
    return c.stdout.decode().strip() if c.returncode == 0 else None


def load_validator(cwd: str, ref: str):
    """``scripts/ci/check_live_review_records.py`` and its schema, read from ``ref`` (origin/main): the guard's own rules."""
    src, schema = show(cwd, ref, VALIDATOR), show(cwd, ref, SCHEMA)
    if src is None or schema is None:
        return None, None
    mod = types.ModuleType("_check_live_review_records")
    mod.__file__ = os.path.join(cwd, VALIDATOR)
    sys.modules[mod.__name__] = mod
    exec(compile(src, VALIDATOR, "exec"), mod.__dict__)  # noqa: S102 -- the repo's own guard, pinned to origin/main
    return mod, json.loads(schema)


def append(text: str, line: dict) -> str:
    text = text or ""
    if text and not text.endswith("\n"):
        text += "\n"
    return text + json.dumps(line, separators=(",", ":"), sort_keys=False) + "\n"


def latency_line(row: dict, env: dict, now: datetime, tries: int) -> dict:
    bar_close, built = _ts(env.get("bar_close") or (env.get("short_hold") or {}).get("bar_close")), _ts(env.get("built_at"))
    return {"review_id": row["review_id"], "order_package_id": row["order_package_id"], "leg": row["leg"],
            "action": row["recommendation"]["action"], "session": row["session"], "bar": row["trigger"]["level"],
            "bar_close": _iso(bar_close) if bar_close else None, "packet_built_at": env.get("built_at"),
            "decided_at": _iso(now), "tries": tries,
            "bar_close_to_decision_s": round((now - bar_close).total_seconds(), 1) if bar_close else None,
            "packet_to_decision_s": round((now - built).total_seconds(), 1) if built else None}


def run(draft: dict, cwd: str, pkg: str, *, branch: str = BRANCH, rules_ref: str = "origin/main",
        dry_run: bool = False, check_only: bool = False, tries: int = 5, now_fn=lambda: datetime.now(timezone.utc)):
    """(exit code, report dict)."""
    if git("fetch", "-q", "--depth", "1", "origin", "main", cwd=cwd).returncode and rules_ref == "origin/main":
        return 2, {"state": "could_not_look", "reason": "cannot fetch origin/main for the validator"}
    validator, schema = load_validator(cwd, rules_ref)
    if validator is None:
        return 2, {"state": "could_not_look", "reason": f"validator or schema unreadable at {rules_ref}"}
    reviews_path = DRYRUN_REVIEWS if dry_run else REVIEWS
    last = None
    for attempt in range(1, tries + 1):
        tip = fetch(cwd, branch)
        if tip is None:
            return 2, {"state": "could_not_look", "reason": f"cannot fetch {branch}"}
        raw = show(cwd, tip, ENVELOPE.format(pkg=pkg))
        if raw is None:
            return 2, {"state": "could_not_look", "reason": f"no packet envelope for {pkg} on {branch}"}
        try:
            env = json.loads(raw)
        except ValueError:
            return 2, {"state": "could_not_look", "reason": "packet envelope is not JSON"}
        if env.get("closed"):
            return 3, {"state": "closed", "order_package_id": pkg, "closed_at": env.get("closed_at")}
        now = now_fn()
        try:
            row = compile_row(draft, env, now=now)
        except Refused as r:
            return 1, {"state": "refused", "problems": r.problems}
        problems = validator.row_problems(row, "reviews", schema)
        problems += validator.packet_blob_problems(row, json.dumps(env["packet"]).encode())
        if problems:
            return 1, {"state": "refused", "problems": problems, "row": row}
        text = (show(cwd, tip, reviews_path) or b"").decode()
        if any((json.loads(ln) if ln.strip().startswith("{") else {}).get("review_id") == row["review_id"]
               for ln in text.splitlines() if ln.strip()):
            return 3, {"state": "nothing_due", "review_id": row["review_id"],
                       "reason": "this packet already has a row: wait for the next 5-min packet"}
        if check_only:
            return 0, {"state": "check_ok", "review_id": row["review_id"], "row": row}
        files = {reviews_path: append(text, row),
                 LATENCY: append((show(cwd, tip, LATENCY) or b"").decode(), latency_line(row, env, now, attempt))}
        if draft.get("external_context"):
            train, gaps = external_lines(row, draft["external_context"])
            for path, lines in ((EXTERNAL, train), (FEED_GAPS, gaps)):
                t = (show(cwd, tip, path) or b"").decode()
                for ln in lines:
                    t = append(t, ln)
                files[path] = t
        pkt_path = PACKETS.format(rid=row["review_id"])
        if show(cwd, tip, pkt_path) is None:
            files[pkt_path] = json.dumps(env["packet"], indent=1, sort_keys=True) + "\n"
        if env.get("table") and env.get("table_path") and show(cwd, tip, env["table_path"]) is None:
            files[env["table_path"]] = json.dumps(env["table"], indent=1, sort_keys=True) + "\n"
        msg = (f"short-hold{' dry-run' if dry_run else ''}: {row['review_id']} {row['recommendation']['action']} "
               f"({row['leg']}, judgement {row['recommendation']['judgement_confidence']})")
        sha = commit_files(cwd, tip.replace("origin/", "refs/remotes/origin/"), files, msg)
        if sha is None:
            return 2, {"state": "could_not_write", "reason": "local commit failed"}
        push = git("push", "-q", "origin", f"{sha}:refs/heads/{branch}", cwd=cwd)
        if push.returncode == 0:
            return 0, {"state": "written", "review_id": row["review_id"], "action": row["recommendation"]["action"],
                       "route": row["disposition"]["route"], "commit": sha, "tries": attempt, "file": reviews_path,
                       "latency": files[LATENCY].splitlines()[-1]}
        last = push.stderr.decode(errors="replace").strip()[-200:]
    return 2, {"state": "could_not_write", "reason": f"push rejected {tries}x (branch moving?): {last}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("draft")
    ap.add_argument("--package", required=True, help="the order_package_id this lane manages")
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--rules-ref", default="origin/main")
    ap.add_argument("--dry-run", action="store_true", help=f"write to {DRYRUN_REVIEWS} (never applied)")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    a = ap.parse_args(argv)
    try:
        draft = json.loads(open(a.draft).read())
    except (OSError, ValueError) as exc:
        print(json.dumps({"state": "refused", "problems": [f"draft unreadable: {exc}"]}))
        return 1
    code, rep = run(draft, os.getcwd(), a.package, branch=a.branch, rules_ref=a.rules_ref, dry_run=a.dry_run,
                    check_only=a.check)
    print(json.dumps(rep, indent=1, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
