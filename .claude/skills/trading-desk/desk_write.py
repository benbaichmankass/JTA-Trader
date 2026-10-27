#!/usr/bin/env python3
"""desk_write -- the ONLY way a desk wake writes its decision row (DESK-WAKE-WRITE).

A wake is a repo-less sparse checkout, so this file is stdlib-only and self-contained. It runs

    git fetch -q --depth 1 origin main && git show origin/main:.claude/skills/trading-desk/desk_write.py | python3 - DRAFT.json

and does, in order: read the pointer, the packet and decisions.jsonl from the tip of `desk/decisions`;
COMPILE the full v2 row from the wake's short draft (every boilerplate field, the novelty, the onboarding
and EVERY alternatives[] statistic are taken from the packet, so none can be mistyped); VALIDATE the row
against comms/schema/desk_decision.schema.json (read from origin/main) and the guard's rules; and write it with a compare-and-swap:
a commit on top of the tip pushed WITHOUT force, so a moved branch is a rejected push, never a lost line.
A refusal prints the reasons and writes nothing. There is no flag that skips validation.

LIVE vs SHADOW (the bybit_1 demo flip, operator popup 2026-10-27 "Yes, live on bybit_1 demo now (Recommended)"):
a `propose_entry` is written `label_source: live`, `route: submitted` with an `intent_id` exactly when, on
origin/main, the claude_desk leg in config/strategies.yaml is `enabled: true` + `execution: live` and the
proposal's symbol is in the leg's `symbols:`; it then needs `max_hold_min` <= 60 and a `market` entry. Every
other row stays shadow (record-only). Which ACCOUNTS may trade it is not decided here: desk intake
(scripts/ops/desk_intake.py) admits it only while every account rostering the leg is a demo account in
MD-TRADE-DESK's entry_generation.demo_accounts, and each account's RiskManager sizes it.

Exit: 0 written (or `--check` clean) / 1 refused / 2 could_not_look|could_not_write / 3 nothing_due.
The rules mirror scripts/ci/check_desk_records.py; tests/test_desk_wake_write.py asserts they agree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

BRANCH = "desk/decisions"
DECISIONS = "comms/desk/decisions.jsonl"
POINTER = "comms/desk/latest_scan.json"
BRIEF = ".claude/skills/trading-desk/DESK-BRIEF.md"
SCHEMA = "comms/schema/desk_decision.schema.json"
SENTINEL_R_FLOOR = 50.0  # src/runtime/target_expectation.py
VENUE_CAP_FRACTION = 0.099  # copy of src/runtime/tp_venue_cap.py (this file is stdlib-only); tests/test_desk_wake_write.py pins equality
REACH_FLOOR = 0.10
SHORT_HOLD_MAX_MIN = 60  # a live desk proposal is the short-hold kind (operator 2026-10-27); the guard imports it
DESK_LEG = "claude_desk"
STRATEGIES = "config/strategies.yaml"
STAT_TOL = 1e-3  # history rows are 6 d.p.; early wakes rounded to 3
STALE = timedelta(hours=3)
ACTIONS = ("no_trade", "propose_entry", "watch_note")
SIZE_KEYS = {"size", "qty", "quantity", "notional", "contracts", "lots", "leverage", "position_size",
             "risk_pct", "risk_usd", "risk_amount", "risk_fraction"}


class Refused(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def packet_sha(packet: dict) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------- schema walk

def _type_ok(v, t: str) -> bool:
    return {"string": isinstance(v, str), "boolean": isinstance(v, bool), "null": v is None,
            "integer": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "object": isinstance(v, dict), "array": isinstance(v, list)}[t]


def walk(v, spec: dict, enums: dict, path: str, out: list) -> None:
    t = spec.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_type_ok(v, x) for x in ts):
            out.append(f"{path}: expected {'|'.join(ts)}, got {type(v).__name__}")
            return
    if v is None:
        return
    allowed = spec.get("enum") or (enums[spec["enum_ref"]] if "enum_ref" in spec else None)
    if allowed is not None and v not in allowed:
        out.append(f"{path}: {v!r} not in {allowed}")
    if isinstance(v, str):
        if len(v) < spec.get("minLength", 0):
            out.append(f"{path}: empty string")
        if "pattern" in spec and not re.search(spec["pattern"], v):
            out.append(f"{path}: {v!r} does not match {spec['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in spec and v < spec["minimum"]:
            out.append(f"{path}: {v} < {spec['minimum']}")
        if "maximum" in spec and v > spec["maximum"]:
            out.append(f"{path}: {v} > {spec['maximum']}")
    if isinstance(v, dict):
        props = spec.get("properties", {})
        out += [f"{path}.{k}: missing" for k in spec.get("required", []) if k not in v]
        for k, x in v.items():
            if k in props:
                walk(x, props[k], enums, f"{path}.{k}", out)
            elif spec.get("additionalProperties") is False:
                out.append(f"{path}.{k}: unexpected field")
    if isinstance(v, list) and "items" in spec:
        for i, x in enumerate(v):
            walk(x, spec["items"], enums, f"{path}[{i}]", out)


def _size_keys(v, path="") -> list[str]:
    if isinstance(v, dict):
        return [f"{path}.{k}".lstrip(".") for k in v if k.lower() in SIZE_KEYS] + [
            x for k, w in v.items() for x in _size_keys(w, f"{path}.{k}")]
    if isinstance(v, list):
        return [x for i, w in enumerate(v) for x in _size_keys(w, f"{path}[{i}]")]
    return []


# ----------------------------------------------------------------------------- packet lookups

def history_row(packet: dict, symbol: str, side: str, horizon: int) -> dict | None:
    for h in (packet.get("history") or {}).get("rows") or []:
        if h.get("symbol") == symbol and h.get("side") == side and h.get("horizon_bars") == horizon:
            return h
    return None


def novelty_for(packet: dict, symbol: str, side: str) -> str:
    sb = packet.get("system_book") or {}
    if sb.get("read_state") != "read":
        return "unverifiable"
    same = [i for i in sb.get("items") or [] if i.get("symbol") == symbol and i.get("side") == side]
    if any(i.get("status") != "near_signal" for i in same):
        return "duplicates_system_package"
    if same:
        return "duplicates_near_signal"
    return "new" if sb.get("near_signals_read_state") == "read" else "unverifiable"


def alt_stat_problems(row: dict, packet: dict) -> list[str]:
    """The stat-match rule: every priced alternative equals a history row of ITS OWN packet.

    Shared with scripts/ci/check_desk_records.py and the mirror. A (symbol, side) alternative must equal
    one history row (n, mean_r, sd_r); a base_rate `no_trade` states 0 R and the n of a row weighed."""
    rows = (packet.get("history") or {}).get("rows") or []
    out: list[str] = []
    priced_ns = []
    for i, a in enumerate(row.get("alternatives") or []):
        if a.get("source") != "base_rate":
            continue
        if a["action"] == "no_trade":
            if a["mean_r"] != 0 or a["sd_r"] != 0:
                out.append(f"alternatives[{i}]: a base_rate no_trade earns exactly 0 R (mean_r 0.0, sd_r 0.0)")
            continue
        hit = [h for h in rows if h.get("symbol") == a["symbol"] and h.get("side") == a["side"]
               and h.get("n") == a["n"] and abs(h["mean_r"] - a["mean_r"]) <= STAT_TOL
               and abs(h["sd_r"] - a["sd_r"]) <= STAT_TOL]
        if not hit:
            out.append(f"alternatives[{i}]: {a['symbol']} {a['side']} n={a['n']} mean_r={a['mean_r']} sd_r={a['sd_r']} "
                       "equals no history row of the cited packet (a statistic must be copied from one row)")
        else:
            priced_ns.append(a["n"])
    for i, a in enumerate(row.get("alternatives") or []):
        if a.get("source") == "base_rate" and a["action"] == "no_trade":
            allowed = priced_ns or [h.get("n") for h in rows]
            if a["n"] not in allowed:
                out.append(f"alternatives[{i}]: no_trade n={a['n']} is not the n of a history row weighed")
    return out


# ----------------------------------------------------------------------------- the desk leg's live scope

def leg_scope(strategies_yaml: str | None) -> dict | None:
    """The claude_desk block of config/strategies.yaml, read without a YAML library (this file is stdlib-only):
    {"enabled", "execution", "symbols"}. None when the block or a field cannot be read (=> every row is shadow).
    tests/test_desk_demo_flip.py pins this against yaml.safe_load of the real file."""
    if not strategies_yaml:
        return None
    lines = strategies_yaml.splitlines()
    try:
        i = next(n for n, ln in enumerate(lines) if re.match(rf"^  {DESK_LEG}:\s*(#.*)?$", ln))
    except StopIteration:
        return None
    block = []
    for ln in lines[i + 1:]:
        if ln.strip() and not ln.startswith("   ") and not ln.lstrip().startswith("#"):
            break
        block.append(ln)
    got: dict = {}
    for ln in block:
        m = re.match(r"^    (enabled|execution|symbols):\s*(.*?)\s*(#.*)?$", ln)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if k == "symbols":
            sm = re.match(r"^\[(.*)\]$", v)
            if not sm:
                return None
            got[k] = [s.strip().strip("'\"") for s in sm.group(1).split(",") if s.strip()]
        elif k == "enabled":
            got[k] = v.lower() == "true"
        else:
            got[k] = v.strip("'\"")
    if set(got) != {"enabled", "execution", "symbols"}:
        return None
    return got


def is_live(action: str, symbol: str | None, scope: dict | None) -> bool:
    return (action == "propose_entry" and scope is not None and scope["enabled"] and scope["execution"] == "live"
            and symbol in scope["symbols"])


def live_proposal_problems(row: dict) -> list[str]:
    """A live desk proposal (it trades on the bybit_1 demo) is the short-hold kind. Shared with the guard."""
    if row.get("label_source") != "live" or row.get("action") != "propose_entry" or not isinstance(row.get("proposal"), dict):
        return []
    pr, out = row["proposal"], []
    mh = pr.get("max_hold_min")
    if not isinstance(mh, int) or isinstance(mh, bool) or not 1 <= mh <= SHORT_HOLD_MAX_MIN:
        out.append(f"a live proposal is the short-hold kind: max_hold_min is required, 1..{SHORT_HOLD_MAX_MIN} (got {mh!r})")
    if (pr.get("entry") or {}).get("type") != "market":
        out.append("a live proposal enters at `market` (the claude_desk leg refuses limit/stop as entry_type_unsupported)")
    return out


# ----------------------------------------------------------------------------- compile

def compile_row(draft: dict, pointer: dict, packet: dict, schema: dict, *, now: datetime,
                skill_sha: str | None, scope: dict | None = None) -> dict:
    bad = _size_keys(draft)
    if bad:
        raise Refused([f"no-size rule: `{k}` -- size is each account's (RiskManager), never the desk's" for k in bad])
    allowed = {"action", "session", "confidence", "basis", "rationale", "judge_prior", "proposal", "weighed"}
    extra = sorted(set(draft) - allowed)
    if extra:
        raise Refused([f"draft has fields the script derives or does not accept: {extra} (allowed: {sorted(allowed)})"])
    action = draft.get("action")
    if action not in ACTIONS:
        raise Refused([f"action {action!r} is not one of {list(ACTIONS)}"])
    meta = packet["meta"]
    pid = meta["packet_id"]
    universe = {u["symbol"]: u for u in packet.get("universe") or []}
    problems: list[str] = []

    proposal = None
    if action == "propose_entry":
        d = draft.get("proposal")
        if not isinstance(d, dict):
            raise Refused(["propose_entry needs a `proposal` object"])
        keys = {"symbol", "side", "horizon_bars", "entry", "stop", "tp", "expected_r_net", "thesis"}
        if set(d) - {"max_hold_min"} != keys:
            raise Refused([f"proposal keys must be exactly {sorted(keys)} plus optional max_hold_min (venue_class, "
                           f"timeframe, novelty and onboarding are derived from the packet); got {sorted(d)}"])
        u = universe.get(d["symbol"])
        if u is None:
            raise Refused([f"proposal symbol {d['symbol']} is not in the scan packet's universe"])
        proposal = {"symbol": d["symbol"], "venue_class": u["venue_class"], "side": d["side"], "timeframe": u["timeframe"],
                    "horizon_bars": d["horizon_bars"], "entry": d["entry"], "stop": d["stop"], "tp": d["tp"],
                    "expected_r_net": d["expected_r_net"], "thesis": d["thesis"],
                    "novelty": novelty_for(packet, d["symbol"], d["side"]),
                    "onboarding": "onboarded" if u["tier"] == "full" else "pending"}
        if "max_hold_min" in d:
            proposal["max_hold_min"] = d["max_hold_min"]

    def priced(symbol, side, horizon, level, chosen):
        h = history_row(packet, symbol, side, horizon) if isinstance(horizon, int) else None
        if h is None:
            if proposal and chosen and (universe.get(symbol) or {}).get("tier") == "full":
                problems.append(f"no history row for {symbol} {side} horizon_bars={horizon}: price the proposal "
                                "against a horizon the packet carries")
            return {"action": "propose_entry", "chosen": chosen, "symbol": symbol, "side": side, "level": level,
                    "source": "not_priced", "n": None, "mean_r": None, "sd_r": None}
        return {"action": "propose_entry", "chosen": chosen, "symbol": symbol, "side": side, "level": level,
                "source": "base_rate", "n": h["n"], "mean_r": h["mean_r"], "sd_r": h["sd_r"]}

    alts = []
    if proposal:
        alts.append(priced(proposal["symbol"], proposal["side"], proposal["horizon_bars"], proposal["entry"]["level"], True))
    for w in (draft.get("weighed") or [])[:3]:
        if not isinstance(w, dict) or set(w) - {"symbol", "side", "horizon_bars", "level"}:
            raise Refused(["each `weighed` item is {symbol, side, horizon_bars, level?} -- statistics are read from the packet"])
        if proposal and (w.get("symbol"), w.get("side")) == (proposal["symbol"], proposal["side"]):
            continue
        alts.append(priced(w.get("symbol"), w.get("side"), w.get("horizon_bars"), w.get("level"), False))
    weighed_n = next((a["n"] for a in alts if a["source"] == "base_rate"), None)
    flat_chosen = action == "no_trade"
    nt = {"action": "no_trade", "chosen": flat_chosen, "symbol": None, "side": None, "level": None}
    nt.update({"source": "base_rate", "n": weighed_n, "mean_r": 0.0, "sd_r": 0.0} if weighed_n is not None
              else {"source": "not_priced", "n": None, "mean_r": None, "sd_r": None})
    alts.insert(0, nt)
    if action == "watch_note":
        alts.append({"action": "watch_note", "chosen": True, "symbol": None, "side": None, "level": None,
                     "source": "not_priced", "n": None, "mean_r": None, "sd_r": None})
    if problems:
        raise Refused(problems)

    live = is_live(action, (proposal or {}).get("symbol"), scope)
    did = "DD-" + pid[3:] + "-1"
    rationale = str(draft.get("rationale") or "")
    built = _ts(meta["built_at"])
    if now - built > STALE and not rationale.startswith("stale_packet:"):
        rationale = f"stale_packet: built {meta['built_at']}. {rationale}"
    return {
        "schema_version": 2, "decision_id": did, "packet_id": pid, "packet_sha": pointer["packet_sha"],
        "packet_kind": "scan", "role": "entry_generation", "order_package_id": None,
        "judged_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "info_cutoff_at": meta["info_cutoff_at"],
        "trigger_event": "bar_close", "model": "sonnet-tier", "session": str(draft.get("session") or "desk-wake"),
        "prompt_sha": None, "skill_sha": skill_sha, "label_version": 1, "label_provenance": "judgment",
        "label_source": "live" if live else "shadow", "pre_cutoff": False, "action": action,
        "params": {"level": None, "level_atr": None, "frac": None, "bars": None}, "proposal": proposal,
        "alternatives": alts, "judge_prior": draft.get("judge_prior") if action == "propose_entry" else None,
        "confidence": draft.get("confidence"), "basis": draft.get("basis"), "rationale": rationale,
        "escalated_to": None, "intent_id": ("DI-" + did[3:]) if live else None,
        "disposition": {"route": "submitted" if live else "none", "per_account": []},
        "external_context": {"used": False, "trigger": None, "sources": [], "summary": None, "reproducible": True},
        "training": {"train_eligible": True, "gate_eligible": True, "exclusion_reasons": []},
    }


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# ----------------------------------------------------------------------------- validate

def row_problems(row: dict, packet: dict, schema: dict) -> list[str]:
    out: list[str] = [f"no-size rule: `{k}`" for k in _size_keys(row)]
    walk(row, schema["decisions"], schema["enums"], "decision", out)
    if out:
        return out
    action, meta = row["action"], packet["meta"]
    if row["role"] != "entry_generation" or row["packet_kind"] != "scan":
        out.append("this writer takes entry_generation rows on a scan packet only")
    if action not in schema["role_actions"]["entry_generation"]:
        out.append(f"action {action!r} not in the entry_generation enum")
    if (action == "propose_entry") != (row["proposal"] is not None):
        out.append("proposal is required on propose_entry and null on every other action")
    if (action == "propose_entry") != (row["judge_prior"] is not None):
        out.append("judge_prior is required on propose_entry and null otherwise")
    if row["basis"] == "insufficient_n" and action == "propose_entry":
        out.append("basis insufficient_n is only for no_trade / watch_note")
    if any(v is not None for v in row["params"].values()):
        out.append("params are all null on an entry_generation row")
    if row["label_source"] == "live":
        if action != "propose_entry" or row["disposition"] != {"route": "submitted", "per_account": []} \
                or not row["intent_id"] or row["escalated_to"]:
            out.append("a live row is a propose_entry routed `submitted`, with an intent_id and no escalation")
        out += live_proposal_problems(row)
    elif row["disposition"] != {"route": "none", "per_account": []} or row["intent_id"] or row["escalated_to"]:
        out.append("a shadow row routes `none`, with no intent and no escalation")
    alts = row["alternatives"]
    chosen = [a for a in alts if a["chosen"]]
    if len(chosen) != 1 or chosen[0]["action"] != action:
        out.append("alternatives: exactly one is chosen, and it is the row's action")
    if "no_trade" not in {a["action"] for a in alts}:
        out.append("alternatives must list no_trade (the baseline)")
    for i, a in enumerate(alts):
        if a["action"] not in schema["role_actions"]["entry_generation"]:
            out.append(f"alternatives[{i}]: {a['action']!r} not in the entry_generation enum")
        if (a["source"] == "not_priced" or not a["n"]) and any(x is not None for x in (a["mean_r"], a["sd_r"])):
            out.append(f"alternatives[{i}]: unpriced but numbers present (must be null)")
        if a["source"] != "not_priced" and a["n"] is None:
            out.append(f"alternatives[{i}]: a priced alternative states its n")
    if row["packet_id"] != meta.get("packet_id") or row["packet_sha"] != packet_sha(packet):
        out.append("packet_id / packet_sha do not match the packet")
    if row["info_cutoff_at"] != meta.get("info_cutoff_at"):
        out.append("info_cutoff_at must be the packet's, exactly")
    if meta.get("packet_kind") != "scan" or meta.get("mode") != "live":
        out.append("the cited packet must be a live scan packet")
    if row["training"] != {"train_eligible": True, "gate_eligible": True, "exclusion_reasons": []}:
        out.append("training marker disagrees with its derivation")
    out += alt_stat_problems(row, packet)
    if row["proposal"] is not None:
        out += proposal_problems(row, packet)
    return out


def proposal_problems(row: dict, packet: dict) -> list[str]:
    out: list[str] = []
    pr = row["proposal"]
    long_ = pr["side"] == "long"
    e, sl, tp = pr["entry"]["level"], pr["stop"]["level"], pr["tp"]["level"]
    if not ((sl < e < tp) if long_ else (tp < e < sl)):
        return [f"proposal geometry: a {pr['side']} needs {'stop < entry < tp' if long_ else 'tp < entry < stop'}"]
    tp_r = abs(tp - e) / abs(e - sl)
    if tp_r >= SENTINEL_R_FLOOR:
        out.append(f"TP doctrine: tp is {tp_r:.1f} R from entry (>= {SENTINEL_R_FLOOR:g} R is the sentinel, not a prediction)")
    if abs(tp - e) / e >= VENUE_CAP_FRACTION:
        out.append(f"TP doctrine: tp sits at or beyond the venue cap ({VENUE_CAP_FRACTION:.1%} from entry)")
    if pr["tp"]["p_hit"] < REACH_FLOOR or pr["tp"]["p_hit"] >= 1:
        out.append(f"TP doctrine: tp.p_hit must be in [{REACH_FLOOR}, 1)")
    if not pr["expected_r_net"] < tp_r:
        out.append("expected_r_net cannot reach the proposal's own gross best case (tp R)")
    u = {x["symbol"]: x for x in packet.get("universe") or []}.get(pr["symbol"])
    if u is None:
        out.append(f"proposal symbol {pr['symbol']} is not in the scan packet's universe")
    elif (pr["onboarding"] == "onboarded") != (u["tier"] == "full"):
        out.append("onboarding must be `onboarded` exactly when the symbol is full-tier")
    if pr["novelty"] != novelty_for(packet, pr["symbol"], pr["side"]):
        out.append(f"novelty {pr['novelty']!r} disagrees with the scan's system_book")
    return out


# ----------------------------------------------------------------------------- git (CAS)

def git(*args: str, cwd: str | None = None, input: bytes | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, input=input, capture_output=True, env={**os.environ, **(env or {})}, check=False)


def show(cwd: str, ref: str, path: str) -> bytes | None:
    r = git("show", f"{ref}:{path}", cwd=cwd)
    return r.stdout if r.returncode == 0 else None


def fetch(cwd: str, branch: str) -> str | None:
    r = git("fetch", "-q", "--depth", "1", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", cwd=cwd)
    return f"origin/{branch}" if r.returncode == 0 else None


def commit_on(cwd: str, tip: str, blob_text: str, message: str) -> str | None:
    """A commit on `tip` whose decisions.jsonl is `blob_text`, built with plumbing (the sparse worktree is untouched)."""
    h = git("hash-object", "-w", "--stdin", cwd=cwd, input=blob_text.encode())
    if h.returncode:
        return None
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index"), "GIT_AUTHOR_NAME": "Claude", "GIT_COMMITTER_NAME": "Claude",
               "GIT_AUTHOR_EMAIL": "noreply@anthropic.com", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
        steps = [git("read-tree", tip, cwd=cwd, env=env),
                 git("update-index", "--add", "--cacheinfo", f"100644,{h.stdout.decode().strip()},{DECISIONS}", cwd=cwd, env=env)]
        tree = git("write-tree", cwd=cwd, env=env)
        if any(s.returncode for s in steps) or tree.returncode:
            return None
        c = git("commit-tree", tree.stdout.decode().strip(), "-p", tip, "-m", message, cwd=cwd, env=env)
    return c.stdout.decode().strip() if c.returncode == 0 else None


def run(draft: dict, cwd: str, *, brief_ref: str = "origin/main", check_only: bool = False, tries: int = 5,
        now: datetime | None = None) -> tuple[int, dict]:
    now = now or datetime.now(timezone.utc)
    if fetch(cwd, brief_ref.split("/", 1)[1]) is None:
        return 2, {"state": "could_not_look", "reason": f"fetch {brief_ref}"}
    brief = show(cwd, brief_ref, BRIEF)
    sha = git("rev-parse", f"{brief_ref}:{BRIEF}", cwd=cwd).stdout.decode().strip() or None
    if brief is None:
        return 2, {"state": "could_not_look", "reason": f"{BRIEF} unreadable on {brief_ref}"}
    schema_raw = show(cwd, brief_ref, SCHEMA)
    if schema_raw is None:
        return 2, {"state": "could_not_look", "reason": f"{SCHEMA} unreadable on {brief_ref}"}
    schema = json.loads(schema_raw)
    scope = leg_scope((show(cwd, brief_ref, STRATEGIES) or b"").decode() or None)
    packet = pointer = None
    last = "no attempt"
    for attempt in range(1, tries + 1):
        if fetch(cwd, BRANCH) is None:
            return 2, {"state": "could_not_look", "reason": f"fetch {BRANCH}", "tries": attempt}
        tip = f"origin/{BRANCH}"
        raw = show(cwd, tip, DECISIONS)
        if raw is None:
            return 2, {"state": "could_not_look", "reason": f"{DECISIONS} unreadable", "tries": attempt}
        if packet is None:
            ptr_raw = show(cwd, tip, POINTER)
            if ptr_raw is None:
                return 2, {"state": "could_not_look", "reason": "latest_scan"}
            pointer = json.loads(ptr_raw)
            pk_raw = show(cwd, tip, pointer["path"])
            if pk_raw is None:
                return 2, {"state": "could_not_look", "reason": "packet unreadable"}
            packet = json.loads(pk_raw)
            if (packet.get("meta") or {}).get("packet_id") != pointer["packet_id"] or packet_sha(packet) != pointer["packet_sha"]:
                return 2, {"state": "could_not_look", "reason": "packet_mismatch"}
        text = raw.decode()
        for line in text.splitlines():
            try:
                if json.loads(line).get("packet_id") == pointer["packet_id"]:
                    return 3, {"state": "nothing_due", "packet_id": pointer["packet_id"]}
            except (ValueError, AttributeError):
                continue
        try:
            row = compile_row(draft, pointer, packet, schema, now=now, skill_sha=sha, scope=scope)
            problems = row_problems(row, packet, schema)
        except Refused as exc:
            problems = exc.problems
        if problems:
            return 1, {"state": "refused", "problems": problems}
        if check_only:
            return 0, {"state": "valid", "row": row}
        sep = "" if not text or text.endswith("\n") else "\n"
        new = text + sep + json.dumps(row, separators=(",", ":")) + "\n"
        c = commit_on(cwd, tip, new, f"desk: {row['decision_id']} {row['action']} ({row['label_source']})")
        if c is None:
            return 2, {"state": "could_not_write", "reason": "commit build failed", "tries": attempt}
        p = git("push", "origin", f"{c}:refs/heads/{BRANCH}", cwd=cwd)  # no force: a moved branch rejects the push
        if p.returncode == 0:
            return 0, {"state": "written", "decision_id": row["decision_id"], "action": row["action"],
                       "label_source": row["label_source"], "intent_id": row["intent_id"], "commit": c, "tries": attempt}
        last = p.stderr.decode()[-300:]
    return 2, {"state": "could_not_write", "reason": last, "tries": tries}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("draft", help="path to the draft JSON")
    ap.add_argument("--check", action="store_true", help="validate and print the compiled row; write nothing")
    ap.add_argument("--cwd", default=".")
    a = ap.parse_args(argv)
    try:
        draft = json.load(open(a.draft))
    except (OSError, ValueError) as exc:
        print(json.dumps({"state": "refused", "problems": [f"draft unreadable: {exc}"]}))
        return 1
    rc, res = run(draft, a.cwd, check_only=a.check)
    print(json.dumps(res, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
