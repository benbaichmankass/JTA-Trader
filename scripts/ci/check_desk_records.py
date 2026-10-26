#!/usr/bin/env python3
"""desk-records-guard -- validates the trading-desk records against comms/schema/desk_*.schema.json.

DESK-0-SCHEMA + DESK-0B-SCHEMA-V2 (design docs/plans/claude-trading-desk-DESIGN.md sections 2.3, 2.4,
3.7, 3.8, 4A). v2: the desk is a trader -- role entry_generation judges a SCAN packet and proposes the
desk's own entries; the v0 market_watch veto enum is gone.
A sibling of live-review-records-guard, not a replacement: it reuses that guard's schema walker and
leaves comms/live_review/ (and its v2 packets) to it. It checks

* comms/desk/packets/*.json  -- packet v3 (desk_packet.schema.json): which blocks a kind carries,
  `outcome` only on kind exit (T1), could-not-look is null AND named in meta.missing_inputs; scan
  packets: universe tiers, system_book near-signals, net-of-cost base rates, the feature projection;
* comms/desk/decisions.jsonl -- desk_decision.schema.json `decisions`: action closed per role, role
  matched to packet kind, params agree with the action; propose_entry carries a full proposal with
  NO size field and a REAL predictive TP (geometry, < SENTINEL_R_FLOOR, inside the venue cap,
  p_hit >= REACH_FLOOR), novelty agrees with the scan's system_book; priced alternatives[]; applied
  only for a tighten (any leg) or a claude_desk leg's own tp_revise / close / partial_close; the
  training marker is the derivation of label_source / pre_cutoff / external_context;
  external_context consistent (used => sources + trigger, reproducible=false), packet_sha equals
  the committed packet and the row agrees with it;
* comms/desk/touches.jsonl   -- desk_decision.schema.json `touches`: only applied intents, tighten-only,
  `sandbox` iff the account is the sandbox account, each touch joins to a decision that applied it;
* comms/desk/outcomes.jsonl  -- T1 outcome rows join to a decision, after its cutoff, net of cost;
* comms/desk/consumed.jsonl  -- dataset-build consumption; only train-eligible decisions.
never_trained_on() is the read DESK-21's detector uses.

Files are append-only and start empty; a leading {"_meta": ...} line is skipped.
Exit: 0 clean / 1 refused.   Usage: check_desk_records.py [--self-test]
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_live_review_records as lr  # noqa: E402  (the shared schema walker)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.runtime.target_expectation import SENTINEL_R_FLOOR  # noqa: E402  (the fleet's sentinel idiom)
from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT  # noqa: E402

# check_tp_doctrine.py's TP-REACH-FLOOR: a target reached < 10% of the time is the sentinel by another name.
REACH_FLOOR = 0.10
PACKET_SCHEMA = REPO / "comms/schema/desk_packet.schema.json"
DECISION_SCHEMA = REPO / "comms/schema/desk_decision.schema.json"
DESK = REPO / "comms/desk"
DECISIONS = DESK / "decisions.jsonl"
TOUCHES = DESK / "touches.jsonl"
OUTCOMES = DESK / "outcomes.jsonl"
CONSUMED = DESK / "consumed.jsonl"
PACKETS = DESK / "packets"

# design 2.3 table: which blocks each kind carries. Blocks outside a kind's set are FORBIDDEN, not optional.
COMMON = {"meta", "features_at_review"}
PACKAGE = {"package", "market"}
BLOCKS_BY_KIND = {
    "scan": COMMON | {"universe", "system_book", "desk_book", "history", "ml"},
    "entry": COMMON | PACKAGE | {"history", "book", "per_account", "ml"},
    "in_trade": COMMON | PACKAGE | {"state", "history", "book", "per_account", "mechanics", "ml", "prior_decisions"},
    "exit": COMMON | PACKAGE | {"state", "mechanics", "prior_decisions", "outcome"},
}
ALL_BLOCKS = set().union(*BLOCKS_BY_KIND.values()) - COMMON
# Roles whose actions are never applied (design 2.1): entries reach accounts as claude_desk packages
# (route `submitted`, sized by each account), never as an applied decision.
NEVER_APPLIED = {"entry_generation", "entry_review", "post_trade"}
# What may be auto_applied, and on which leg (design 2.1 roles 2-3, 3.8). None = any leg.
APPLICABLE = {("in_trade", "tighten_sl"): None, ("in_trade", "tp_revise"): "desk",
              ("exit", "close"): "desk", ("exit", "partial_close"): "desk"}
LEVEL_ACTIONS = {"tighten_sl", "tp_revise"}
BARS_ACTIONS = {"delay"}
# No-size rule (design 2.4): no key that sizes a trade may appear anywhere in a decision row.
SIZE_KEYS = {"size", "qty", "quantity", "notional", "contracts", "lots", "leverage", "position_size",
             "risk_pct", "risk_usd", "risk_amount", "risk_fraction"}
# Universe fields a full-tier row must read (or name in missing_inputs); a light row must leave null.
UNIVERSE_FULL_NUM = ("last_close", "atr")
UNIVERSE_FULL_BLOCKS = ("funding", "swing", "calendar")
UNIVERSE_FEATURES = {"last_close": ("last_close",), "atr": ("atr",), "funding_rate": ("funding", "rate"),
                     "spread_bps": ("spread", "bps"), "dist_swing_high_atr": ("swing", "dist_high_atr"),
                     "dist_swing_low_atr": ("swing", "dist_low_atr"), "volume_24h": ("volume_24h",)}
# Fields projected into features_at_review (flat numeric view of the same packet; design 2.2).
FEATURE_SOURCES = {
    "open_r": ("state", "open_r"), "peak_r": ("state", "peak_r"), "giveback_r": ("state", "giveback_r"),
    "bars_held": ("state", "bars_held"), "bars_since_peak": ("state", "bars_since_peak"),
    "r_to_stop": ("state", "r_to_stop"), "r_to_target": ("state", "r_to_target"),
    "atr_now": ("market", "atr_now"), "atr_entry": ("market", "atr_entry"),
}


def packet_sha(packet: dict) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def project_scan_features(packet: dict) -> dict:
    """A scan packet's feature view: per universe symbol `<SYM>.<field>`, per base-rate row
    `<SYM>.<tf>.<side>.h<H>.mean_r`, and book counts. Unread is null, never 0."""
    out: dict = {}
    for u in packet.get("universe") or []:
        for name, path in UNIVERSE_FEATURES.items():
            v = u
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            out[f"{u['symbol']}.{name}"] = _num(v)
    for r in (packet.get("history") or {}).get("rows") or []:
        out[f"{r['symbol']}.{r['timeframe']}.{r['side']}.h{r['horizon_bars']}.mean_r"] = _num(r.get("mean_r"))
    sb, db = packet.get("system_book") or {}, packet.get("desk_book") or {}
    sbi = sb.get("items") if sb.get("read_state") == "read" else None
    dbi = db.get("items") if db.get("read_state") == "read" else None
    nsr = sbi is not None and sb.get("near_signals_read_state") == "read"
    out["n_system_open"] = None if sbi is None else sum(i["status"] != "near_signal" for i in sbi)
    out["n_near_signals"] = sum(i["status"] == "near_signal" for i in sbi) if nsr else None
    out["n_desk_open"] = None if dbi is None else len(dbi)
    return out


def project_features(packet: dict) -> dict:
    """The ML feature view as a projection of the packet: flat, numeric-or-null. A block the kind does
    not carry, or a field the packet could not read, projects to null -- never 0."""
    if (packet.get("meta") or {}).get("packet_kind") == "scan":
        return project_scan_features(packet)
    out = {}
    for name, (blk, key) in FEATURE_SOURCES.items():
        v = (packet.get(blk) or {}).get(key)
        out[name] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    a, b = out["atr_now"], out["atr_entry"]
    out["atr_now_over_entry"] = (a / b) if a is not None and b else None
    return out


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _named(missing: set, key: str) -> bool:
    return any(m == key or m.startswith(f"{key}:") or m.startswith(f"{key}.") for m in missing)


def scan_problems(p: dict, missing: set) -> list[str]:
    """Scan-only rules (design 2.3): universe tiers, system/desk book read states, base rates."""
    out: list[str] = []
    syms = [u["symbol"] for u in p["universe"]]
    if len(syms) != len(set(syms)):
        out.append("universe names a symbol more than once")
    if not syms:
        out.append("universe is empty (a scan over nothing is not a scan)")
    for u in p["universe"]:
        tag = f"universe.{u['symbol']}"
        if u["tier"] == "light":
            if any(u[k] is not None for k in UNIVERSE_FULL_NUM + ("htf_trend", "regime_cell", "timeframe")):
                out.append(f"{tag}: a light-tier row carries only ticker, volume and spread (full-only fields must be null)")
            if any(u[b]["read_state"] != "not_applicable" for b in UNIVERSE_FULL_BLOCKS):
                out.append(f"{tag}: a light-tier row's funding/swing/calendar read_state must be not_applicable")
        else:
            if u["timeframe"] is None:
                out.append(f"{tag}: a full-tier row names its timeframe")
            for k in UNIVERSE_FULL_NUM:
                if u[k] is None and not _named(missing, f"{tag}.{k}"):
                    out.append(f"{tag}.{k} is null but not named in meta.missing_inputs (could-not-look != zero)")
            for b in UNIVERSE_FULL_BLOCKS + ("spread",):
                if u[b]["read_state"] == "could_not_look" and not _named(missing, f"{tag}.{b}"):
                    out.append(f"{tag}.{b} could_not_look but not named in meta.missing_inputs")
        for b, k in (("funding", "rate"), ("spread", "bps")):
            if u[b]["read_state"] != "read" and u[b][k] is not None:
                out.append(f"{tag}.{b}: a value with read_state {u[b]['read_state']} (only a read carries a number)")
        if u["swing"]["read_state"] != "read" and any(u["swing"][k] is not None for k in ("high", "low", "dist_high_atr", "dist_low_atr")):
            out.append(f"{tag}.swing: levels with read_state {u['swing']['read_state']}")
    for name in ("system_book", "desk_book"):
        b = p[name]
        if b["read_state"] == "read" and b["items"] is None:
            out.append(f"{name}: read with items null (read and empty is [])")
        if b["read_state"] != "read" and b["items"] is not None:
            out.append(f"{name}: items present with read_state {b['read_state']} (could-not-look is null)")
        if b["read_state"] == "could_not_look" and not _named(missing, name):
            out.append(f"{name} could_not_look but not named in meta.missing_inputs")
    sb = p["system_book"]
    if sb["near_signals_read_state"] != "read":
        if any(i["status"] == "near_signal" for i in sb["items"] or []):
            out.append(f"system_book: near_signal items with near_signals_read_state {sb['near_signals_read_state']}")
        if sb["near_signals_read_state"] == "could_not_look" and not _named(missing, "system_book.near_signals"):
            out.append("system_book.near_signals could_not_look but not named in meta.missing_inputs")
    for i, it in enumerate(sb["items"] or []):
        if it["status"] == "near_signal":
            if it["order_package_id"] is not None:
                out.append(f"system_book.items[{i}]: a near-signal has no order package yet")
            if it["bars_to_signal"] is None or it["bars_to_signal"] > 1:
                out.append(f"system_book.items[{i}]: a near-signal is a leg within one bar of a signal (bars_to_signal 0|1)")
        else:
            if it["order_package_id"] is None or it["side"] is None:
                out.append(f"system_book.items[{i}]: an {it['status']} package names its order_package_id and side")
            if it["bars_to_signal"] is not None:
                out.append(f"system_book.items[{i}]: bars_to_signal only on a near-signal")
    h = p["history"]
    if h["read_state"] == "read" and (h["net_of_full_cost_stack"] is not True or not h["cost_policy"]):
        out.append("history: scan base rates are net of the full cost stack and name the cost policy (resolve_cost_policy)")
    if h["read_state"] == "could_not_look" and not _named(missing, "history"):
        out.append("history could_not_look but not named in meta.missing_inputs")
    if h["read_state"] != "read" and h["rows"]:
        out.append(f"history: rows present with read_state {h['read_state']}")
    for i, r in enumerate(h["rows"]):
        nums = ("mean_r", "sd_r", "p10_r", "p50_r", "p90_r", "mean_cost_r")
        if not r["n"] and any(r[k] is not None for k in nums):
            out.append(f"history.rows[{i}]: n == 0 or null but numbers present (must be null)")
        if r["symbol"] not in syms:
            out.append(f"history.rows[{i}]: symbol {r['symbol']} is not in the universe")
        q = [r[k] for k in ("p10_r", "p50_r", "p90_r")]
        if None not in q and not q[0] <= q[1] <= q[2]:
            out.append(f"history.rows[{i}]: quantiles out of order (p10 <= p50 <= p90)")
    keys = [(r["symbol"], r["timeframe"], r["side"], r["horizon_bars"]) for r in h["rows"]]
    if len(keys) != len(set(keys)):
        out.append("history.rows: duplicate (symbol, timeframe, side, horizon_bars)")
    return out


def packet_problems(p: dict, schema: dict) -> list[str]:
    out: list[str] = []
    kind = (p.get("meta") or {}).get("packet_kind") if isinstance(p, dict) else None
    spec = schema["packet"]
    if kind == "scan":  # the dialect has no conditionals: a scan's history has its own shape
        spec = copy.deepcopy(spec)
        spec["properties"]["history"] = schema["scan_history"]
    lr._check(p, spec, schema["enums"], "packet", out)
    if out:
        return out
    have = set(p) & ALL_BLOCKS
    for b in sorted(BLOCKS_BY_KIND[kind] - COMMON - have):
        out.append(f"packet kind {kind} requires block `{b}`")
    for b in sorted(have - BLOCKS_BY_KIND[kind]):
        out.append(f"packet kind {kind} must not carry block `{b}`")
    if kind != "exit" and "outcome" in p:
        out.append("outcome (T1) is only allowed on kind exit")
    if out:
        return out
    if _ts(p["meta"]["info_cutoff_at"]) > _ts(p["meta"]["built_at"]):
        out.append("meta.info_cutoff_at is after built_at (a packet cannot see past its own build)")
    missing = set(p["meta"]["missing_inputs"])
    if kind == "scan":
        out += scan_problems(p, missing)
        proj = project_scan_features(p)
        if p["features_at_review"] != proj:
            diff = sorted(set(proj) ^ set(p["features_at_review"])) or sorted(
                k for k in proj if proj[k] != p["features_at_review"].get(k))
            out.append(f"features_at_review is not the projection of the scan packet (differs on {diff[:5]})")
        for i, m in enumerate(p.get("ml", [])):
            if (m["state"] == "absent") != (m["prediction"] is None):
                out.append(f"ml[{i}]: state absent <=> prediction null (absent is never imputed)")
        return out
    # collapsed-state rule: a null feature must be named in missing_inputs or have a null source
    feats = p["features_at_review"]
    for k, v in project_features(p).items():
        if k in feats and feats[k] != v:
            out.append(f"features_at_review.{k} is not the projection of the packet (got {feats[k]!r}, packet says {v!r})")
    if "state" in p:
        st = p["state"]
        if st["peak_provenance"] in ("unverified", "fabricated") and st["peak_r"] == 0:
            out.append("state.peak_r: 0 with unverified/fabricated provenance (unmeasured must be null)")
        for k in ("open_r", "peak_r", "giveback_r"):
            if st[k] is None and not any(m == f"state.{k}" or m.startswith(f"state.{k}:") for m in missing):
                out.append(f"state.{k} is null but not named in meta.missing_inputs (could-not-look != zero)")
    for blk in ("funding", "calendar"):
        if p["market"][blk]["read_state"] == "could_not_look" and not any(m.startswith(f"market.{blk}") for m in missing):
            out.append(f"market.{blk} could_not_look but not named in meta.missing_inputs")
    for i, o in enumerate((p.get("history") or {}).get("options", [])):
        if o["n"] == 0 and any(o[k] is not None for k in ("mean_r", "sd_r", "worst_r")):
            out.append(f"history.options[{i}]: n == 0 but numbers present (must be null)")
    for i, m in enumerate(p.get("ml", [])):
        if (m["state"] == "absent") != (m["prediction"] is None):
            out.append(f"ml[{i}]: state absent <=> prediction null (absent is never imputed)")
    ids = [a["account_id"] for a in p["package"]["accounts"]]
    if len(ids) != len(set(ids)):
        out.append("package.accounts names an account more than once")
    if "per_account" in p and {a["account_id"] for a in p["per_account"]} != set(ids):
        out.append("per_account must cover exactly package.accounts")
    return out


def _size_keys(v, path="") -> list[str]:
    if isinstance(v, dict):
        return [f"{path}.{k}".lstrip(".") for k in v if k.lower() in SIZE_KEYS] + [
            x for k, w in v.items() for x in _size_keys(w, f"{path}.{k}")]
    if isinstance(v, list):
        return [x for i, w in enumerate(v) for x in _size_keys(w, f"{path}[{i}]")]
    return []


def expected_training(r: dict) -> tuple[bool, bool, set]:
    """The training marker is DERIVED (design 4A, 4C.3): (train_eligible, gate_eligible, reasons)."""
    reasons = set()
    if r["external_context"]["used"]:
        reasons.add("external_context")
    if r["label_source"] == "synthetic":
        reasons.add("synthetic")
    if r["label_source"] == "historical_masked":
        reasons.add("historical_masked")
    if r["pre_cutoff"]:
        reasons.add("pre_cutoff")
    train = not ({"external_context", "synthetic"} & reasons)
    return train, train and not reasons, reasons


def proposal_problems(r: dict, scan: dict | None) -> list[str]:
    """propose_entry (design 2.4): full spec, no size, a REAL predictive TP, novelty vs the scan."""
    out: list[str] = []
    pr = r["proposal"]
    long_ = pr["side"] == "long"
    e, sl, tp = pr["entry"]["level"], pr["stop"]["level"], pr["tp"]["level"]
    if not ((sl < e < tp) if long_ else (tp < e < sl)):
        out.append(f"proposal geometry: a {pr['side']} needs {'stop < entry < tp' if long_ else 'tp < entry < stop'}")
        return out
    tp_r = abs(tp - e) / abs(e - sl)
    if tp_r >= SENTINEL_R_FLOOR:
        out.append(f"TP doctrine: tp is {tp_r:.1f} R from entry (>= {SENTINEL_R_FLOOR:g} R is the sentinel, not a prediction)")
    if abs(tp - e) / e >= TP_VENUE_CAP_PCT:
        out.append(f"TP doctrine: tp sits at or beyond the venue cap ({TP_VENUE_CAP_PCT:.1%} from entry) -- the cap wearing a target's label")
    if pr["tp"]["p_hit"] < REACH_FLOOR or pr["tp"]["p_hit"] >= 1:
        out.append(f"TP doctrine: tp.p_hit must be in [{REACH_FLOOR}, 1) (below the reach floor the target is not a prediction)")
    if r["judge_prior"] is None:
        out.append("propose_entry requires judge_prior (P(TP before SL))")
    if not pr["expected_r_net"] < tp_r:
        out.append("expected_r_net cannot reach the proposal's own gross best case (tp R)")
    if scan is None:
        return out
    uni = {u["symbol"]: u for u in scan.get("universe", [])}
    u = uni.get(pr["symbol"])
    if u is None:
        out.append(f"proposal symbol {pr['symbol']} is not in the scan packet's universe")
    elif (pr["onboarding"] == "onboarded") != (u["tier"] == "full"):
        out.append("proposal onboarding must be `onboarded` exactly when the symbol is full-tier in the scan (design 3.9)")
    sb = scan.get("system_book") or {}
    if sb.get("read_state") != "read":
        if pr["novelty"] != "unverifiable":
            out.append("novelty must be `unverifiable` when the scan could not read the system book")
    else:
        same = [i for i in sb["items"] if i["symbol"] == pr["symbol"] and i["side"] == pr["side"]]
        want = ("duplicates_system_package" if any(i["status"] != "near_signal" for i in same)
                else "duplicates_near_signal" if same
                else "new" if sb.get("near_signals_read_state") == "read" else "unverifiable")
        if pr["novelty"] != want:
            out.append(f"novelty {pr['novelty']!r} disagrees with the scan's system_book (it says {want!r})")
    return out


def alternatives_problems(r: dict, schema: dict) -> list[str]:
    out: list[str] = []
    role, alts = r["role"], r["alternatives"]
    if role == "post_trade":
        return ["post_trade rows carry no alternatives (a grade is not a choice among actions)"] if alts else []
    if not alts and role != "entry_review":
        return [f"role {role} requires alternatives[] (the priced options; the student learns from the choice and the options)"]
    chosen = [a for a in alts if a["chosen"]]
    if alts and (len(chosen) != 1 or chosen[0]["action"] != r["action"]):
        out.append("alternatives: exactly one is chosen, and it is the row's action")
    acts = {a["action"] for a in alts}
    if alts and schema["role_defaults"].get(role) not in acts:
        out.append(f"alternatives must list the role default {schema['role_defaults'].get(role)!r} (the baseline the choice is graded against)")
    for i, a in enumerate(alts):
        if a["action"] not in schema["role_actions"][role]:
            out.append(f"alternatives[{i}]: {a['action']!r} is not in role {role}'s enum")
        nums = (a["mean_r"], a["sd_r"])
        if (a["source"] == "not_priced" or not a["n"]) and any(x is not None for x in nums):
            out.append(f"alternatives[{i}]: unpriced (not_priced or n 0/null) but numbers present (must be null)")
        if a["source"] != "not_priced" and a["n"] is None:
            out.append(f"alternatives[{i}]: a priced alternative states its n")
    return out


def decision_problems(r: dict, schema: dict, packets: Path) -> list[str]:
    out: list[str] = [f"no-size rule: `{k}` -- size is each account's (RiskManager), never the desk's"
                      for k in _size_keys(r)]
    lr._check(r, schema["decisions"], schema["enums"], "decision", out)
    if out:
        return out
    role, action = r["role"], r["action"]
    if action not in schema["role_actions"][role]:
        out.append(f"action {action!r} is not in the closed enum for role {role}: {schema['role_actions'][role]}")
    if r["packet_kind"] not in schema["role_packet_kinds"][role]:
        out.append(f"role {role} cannot judge a {r['packet_kind']} packet (allowed: {schema['role_packet_kinds'][role]})")
    if (action == "propose_entry") != (r["proposal"] is not None):
        out.append("proposal is required on propose_entry and null on every other action")
    if role == "entry_generation" and r["order_package_id"] is not None:
        out.append("entry_generation rows carry order_package_id null (the claude_desk leg creates the package and carries decision_id)")
    if role != "entry_generation" and r["order_package_id"] is None:
        out.append(f"role {role} judges a package: order_package_id is required")
    out += alternatives_problems(r, schema)
    train, gate, reasons = expected_training(r)
    t = r["training"]
    if (t["train_eligible"], t["gate_eligible"], set(t["exclusion_reasons"])) != (train, gate, reasons):
        out.append(f"training marker disagrees with its derivation (expected train={train} gate={gate} reasons={sorted(reasons)})")
    pr = r["params"]
    if action in LEVEL_ACTIONS and pr["level"] is None:
        out.append(f"{action} requires params.level")
    if action not in LEVEL_ACTIONS and (pr["level"] is not None or pr["level_atr"] is not None):
        out.append(f"params.level/level_atr only with {sorted(LEVEL_ACTIONS)}")
    if action == "partial_close" and (pr["frac"] is None or not 0 < pr["frac"] < 1):
        out.append("partial_close requires 0 < params.frac < 1")
    if action != "partial_close" and pr["frac"] is not None:
        out.append("params.frac only with partial_close")
    if action in BARS_ACTIONS and pr["bars"] is None:
        out.append(f"{action} requires params.bars")
    if action not in BARS_ACTIONS and pr["bars"] is not None:
        out.append(f"params.bars only with {sorted(BARS_ACTIONS)}")
    if r["basis"] == "insufficient_n" and action in ("hold", "take"):
        out.append("basis insufficient_n is never hold/take (insufficient_n is no recommendation)")
    if r["label_provenance"] != "judgment" and role != "post_trade":
        out.append("label_provenance computed/measured only on post_trade rows")
    d = r["disposition"]
    applied = [a for a in d["per_account"] if a["applied"]]
    if len({a["account_id"] for a in d["per_account"]}) != len(d["per_account"]):
        out.append("disposition.per_account names an account more than once")
    if r["label_source"] != "live" and (d["route"] in ("auto_applied", "submitted") or r["intent_id"] is not None):
        out.append(f"a {r['label_source']} row is recorded only: no intent, never applied or submitted")
    if action == "propose_entry":
        if d["route"] not in ("none", "submitted"):
            out.append("propose_entry routes `none` (shadow) or `submitted` (to the claude_desk leg via intake)")
        if (d["route"] == "submitted") != (r["intent_id"] is not None):
            out.append("propose_entry: route submitted <=> intent_id set")
        if d["per_account"]:
            out.append("propose_entry has no per_account disposition: each account's verdict and fill arrive as outcomes")
    elif d["route"] == "submitted":
        out.append("route submitted is only for propose_entry")
    if d["route"] == "auto_applied":
        if (role, action) not in APPLICABLE:
            out.append("only an in_trade tighten_sl, or a claude_desk trade's own tp_revise / close / partial_close, may be auto_applied (size and widening are never applied)")
        if r["intent_id"] is None:
            out.append("auto_applied requires intent_id")
        if not applied:
            out.append("auto_applied requires at least one applied per_account entry")
    elif applied:
        out.append("a per_account entry is applied but route is not auto_applied")
    if role in NEVER_APPLIED and action != "propose_entry" and (applied or r["intent_id"] is not None):
        out.append(f"role {role} is never applied: intent_id must be null and nothing applied")
    if role in NEVER_APPLIED and applied:
        out.append(f"role {role} is never applied")
    for a in d["per_account"]:
        if a["applied"] and not (a["verdict"] in ("approve", "clip") and a["readback"] == "match"):
            out.append(f"{a['account_id']}: applied requires verdict approve|clip and readback match (a mismatch is apply_failed)")
        if a["applied"] and (a["level_before"] is None or a["level_after"] is None):
            out.append(f"{a['account_id']}: applied requires level_before and level_after")
        if a["desk_touched"] != a["applied"]:
            out.append(f"{a['account_id']}: desk_touched must equal applied (a pair is touched from its first applied intent)")
        if a["trade_id"] is not None and not a["applied"]:
            out.append(f"{a['account_id']}: trade_id names the trade an applied action landed on (null when not applied)")
    ec = r["external_context"]
    if ec["used"]:
        if not ec["sources"]:
            out.append("external_context.used with empty sources")
        if ec["trigger"] is None:
            out.append("external_context.used requires a trigger (calendar|swing|escalation)")
        if ec["trigger"] in ("calendar", "swing") and r["trigger_event"] != ec["trigger"]:
            out.append("external_context.trigger calendar/swing must equal trigger_event (big-event exception only)")
        if not ec["summary"]:
            out.append("external_context.used requires a summary")
        if ec["reproducible"] is not False:
            out.append("external_context.used requires reproducible=false (replays and training exclude these rows)")
    else:
        if ec["sources"] or ec["trigger"] is not None or ec["summary"] is not None:
            out.append("external_context.used=false must have no sources, trigger or summary")
        if ec["reproducible"] is not True:
            out.append("external_context.used=false requires reproducible=true")
    f = packets / f"{r['packet_id']}.json"
    if not f.exists():
        out.append(f"packet {f.name} is missing from comms/desk/packets/")
    else:
        try:
            pk = json.loads(f.read_text())
        except ValueError:
            return out + [f"packet {f.name} is not valid JSON"]
        if packet_sha(pk) != r["packet_sha"]:
            out.append(f"packet_sha does not match {f.name}")
        meta = pk.get("meta", {})
        if meta.get("packet_kind") != r["packet_kind"]:
            out.append("packet_kind disagrees with the committed packet")
        if meta.get("info_cutoff_at") != r["info_cutoff_at"]:
            out.append("info_cutoff_at disagrees with the committed packet")
        want_mode = {"live": "live", "shadow": "live"}.get(r["label_source"], r["label_source"])
        if meta.get("mode") != want_mode:
            out.append(f"label_source {r['label_source']} needs a packet of mode {want_mode} (got {meta.get('mode')!r})")
        if action == "propose_entry" and r["proposal"] is not None:
            out += proposal_problems(r, pk if meta.get("packet_kind") == "scan" else None)
        if r["packet_kind"] == "scan":
            return out
        if pk.get("package", {}).get("order_package_id") != r["order_package_id"]:
            out.append("order_package_id disagrees with the committed packet")
        leg = pk.get("package", {}).get("leg")
        if d["route"] == "auto_applied" and APPLICABLE.get((role, action)) == "desk" and leg != DESK_LEG:
            out.append(f"{action} is applied only on the desk's own trades (leg {DESK_LEG}); on a strategy trade it is a recommendation")
        sl_live = (pk.get("state") or {}).get("sl_live")
        side = pk.get("package", {}).get("side")
        if action == "tighten_sl" and pr["level"] is not None and sl_live is not None:
            if not (pr["level"] > sl_live if side == "long" else pr["level"] < sl_live):
                out.append("tighten_sl must tighten: a long stop rises, a short stop falls (a widened stop is never in any enum)")
        known = {a["account_id"] for a in pk.get("package", {}).get("accounts", [])}
        for a in d["per_account"]:
            if a["account_id"] not in known:
                out.append(f"disposition names account {a['account_id']} that does not carry the package")
    return out


DESK_LEG = json.loads(DECISION_SCHEMA.read_text())["desk_leg"]


def outcome_problems(o: dict, schema: dict, decisions: dict[str, dict]) -> list[str]:
    out: list[str] = []
    lr._check(o, schema["outcomes"], schema["enums"], "outcome", out)
    if out:
        return out
    d = decisions.get(o["decision_id"])
    if d is None:
        return [f"decision {o['decision_id']} has no row in decisions.jsonl"]
    if _ts(o["computed_at"]) <= _ts(d["info_cutoff_at"]):
        out.append("computed_at must be after the decision's info_cutoff_at (an outcome is T1)")
    k = o["kind"]
    if k == "realised":
        if None in (o["account_id"], o["trade_id"], o["order_package_id"]) or o["provenance"] != "measured":
            out.append("realised: account_id, trade_id and order_package_id set, provenance measured (a broker fill)")
    else:
        if o["account_id"] is not None or o["trade_id"] is not None:
            out.append(f"{k}: account_id and trade_id only on realised rows")
        if o["provenance"] != "computed":
            out.append(f"{k}: provenance computed")
    if k == "expired_unfilled" and d["action"] != "propose_entry":
        out.append("expired_unfilled only on a propose_entry decision")
    nums = ("net_r", "mae_r", "mfe_r", "giveback_r", "bars_held")
    if k in ("not_computable", "expired_unfilled"):
        if any(o[x] is not None for x in nums):
            out.append(f"{k}: every number is null (could-not-look / no fill is never zero)")
        if k == "not_computable" and not o["reason"]:
            out.append("not_computable requires a reason")
    if o["net_r"] is not None and (o["net_of_full_cost_stack"] is not True or not o["cost_policy"]):
        out.append("a net_r is net of the full cost stack and names its cost policy")
    if d["order_package_id"] is not None and o["order_package_id"] not in (None, d["order_package_id"]):
        out.append("order_package_id disagrees with the decision")
    return out


def consumed_problems(c: dict, schema: dict, decisions: dict[str, dict]) -> list[str]:
    out: list[str] = []
    lr._check(c, schema["consumed"], schema["enums"], "consumed", out)
    if out:
        return out
    d = decisions.get(c["decision_id"])
    if d is None:
        return [f"decision {c['decision_id']} has no row in decisions.jsonl"]
    if not d["training"]["train_eligible"]:
        out.append(f"decision {c['decision_id']} is not train-eligible ({d['training']['exclusion_reasons']}): consuming it is a leak")
    return out


def never_trained_on(decisions: Path = DECISIONS, consumed: Path = CONSUMED, *, as_of: datetime | None = None,
                     min_age_days: int = 14) -> list[str]:
    """Train-eligible decision_ids older than `min_age_days` that no dataset build consumed (design 4A;
    DESK-21's detector fails on a non-empty answer). Age is judged_at vs `as_of` (default now)."""
    as_of = as_of or datetime.now(timezone.utc)
    used = {r.get("decision_id") for _, r, err in _rows(consumed) if not err and isinstance(r, dict)} if consumed.exists() else set()
    out = []
    for _, r, err in _rows(decisions) if decisions.exists() else []:
        if err or not isinstance(r, dict) or not (r.get("training") or {}).get("train_eligible"):
            continue
        if r["decision_id"] not in used and as_of - _ts(r["judged_at"]) > timedelta(days=min_age_days):
            out.append(r["decision_id"])
    return out


def touch_problems(t: dict, schema: dict, decisions: dict[str, dict]) -> list[str]:
    out: list[str] = []
    lr._check(t, schema["touches"], schema["enums"], "touch", out)
    if out:
        return out
    if t["sandbox"] != (t["account"] == schema["sandbox_account"]):
        out.append(f"sandbox must be true exactly when account == {schema['sandbox_account']}")
    long_ = t["side"] == "long"
    if not (t["level_after"] > t["level_before"] if long_ else t["level_after"] < t["level_before"]):
        out.append("a desk touch is tighten-only: long stops rise, short stops fall")
    d = decisions.get(t["decision_id"])
    if d is None:
        return out + [f"decision {t['decision_id']} has no row in decisions.jsonl"]
    if d["intent_id"] != t["intent_id"] or d["order_package_id"] != t["order_package_id"]:
        out.append("touch intent_id/order_package_id disagree with its decision")
    if not any(a["account_id"] == t["account"] and a["applied"] and a["level_after"] == t["level_after"]
               and a["level_before"] == t["level_before"] for a in d["disposition"]["per_account"]):
        out.append("no applied per_account entry on the decision matches this touch")
    return out


def _rows(path: Path):
    yield from lr._rows(path)


def findings(decisions: Path = DECISIONS, touches: Path = TOUCHES, packets: Path = PACKETS,
             pschema: Path = PACKET_SCHEMA, dschema: Path = DECISION_SCHEMA,
             outcomes: Path | None = None, consumed: Path | None = None) -> list[str]:
    outcomes = outcomes or decisions.parent / "outcomes.jsonl"
    consumed = consumed or decisions.parent / "consumed.jsonl"
    ps, ds = json.loads(pschema.read_text()), json.loads(dschema.read_text())
    out: list[str] = []
    if packets.exists():
        for f in sorted(packets.glob("*.json")):
            try:
                pk = json.loads(f.read_text())
            except ValueError as e:
                out.append(f"{f.name}: invalid JSON ({e})")
                continue
            out += [f"{f.name}: {m}" for m in packet_problems(pk, ps)]
            if pk.get("meta", {}).get("packet_id") != f.stem:
                out.append(f"{f.name}: meta.packet_id must equal the file name")
    byid: dict[str, dict] = {}
    for kind, p in (("decisions", decisions), ("touches", touches), ("outcomes", outcomes), ("consumed", consumed)):
        if not p.exists():
            out.append(f"{p.name}: file missing")
            continue
        for n, r, err in _rows(p):
            tag = f"{p.name}:{n}"
            if err or not isinstance(r, dict):
                out.append(f"{tag}: {err or 'not an object'}")
                continue
            if kind == "decisions":
                out += [f"{tag}: {m}" for m in decision_problems(r, ds, packets)]
                if r.get("decision_id") in byid:
                    out.append(f"{tag}: duplicate decision_id {r.get('decision_id')}")
                byid[r.get("decision_id")] = r
    for p, fn, idk in ((outcomes, outcome_problems, "outcome_id"), (consumed, consumed_problems, None)):
        if not p.exists():
            continue
        seen_ids: set = set()
        for n, r, err in _rows(p):
            if isinstance(r, dict) and not err:
                out += [f"{p.name}:{n}: {m}" for m in fn(r, ds, byid)]
                key = r.get(idk) if idk else (r.get("decision_id"), r.get("dataset_build_id"))
                if key in seen_ids:
                    out.append(f"{p.name}:{n}: duplicate {idk or '(decision_id, dataset_build_id)'} {key}")
                seen_ids.add(key)
    if touches.exists():
        seen: set[str] = set()
        for n, r, err in _rows(touches):
            if isinstance(r, dict):
                out += [f"{touches.name}:{n}: {m}" for m in touch_problems(r, ds, byid)]
                if r.get("touch_id") in seen:
                    out.append(f"{touches.name}:{n}: duplicate touch_id {r.get('touch_id')}")
                seen.add(r.get("touch_id"))
    return out


# ----------------------------------------------------------------------------- fixtures / self-test

GOOD_PACKET = {
    "schema_version": 2,
    "meta": {"packet_id": "DP-20261026T0900Z-pkg-1", "packet_kind": "in_trade", "packet_version": 3, "mode": "live",
             "built_at": "2026-10-26T09:00:00Z", "info_cutoff_at": "2026-10-26T08:59:30Z",
             "generator": "example", "missing_inputs": ["market.funding: no route"]},
    "package": {"order_package_id": "pkg-1", "leg": "example_leg", "symbol": "ETHUSDT", "side": "long",
                "timeframe": "4h", "signal_logic": "example", "entry": 100.0, "sl": 95.0, "tp": 120.0,
                "risk_per_unit": 5.0,
                "accounts": [{"account_id": "acct_a", "account_class": "real_money"},
                             {"account_id": "bybit_1", "account_class": "soak"}]},
    "state": {"open_r": 1.2, "peak_r": 1.5, "peak_provenance": "estimated", "giveback_r": 0.3, "bars_held": 6,
              "bars_since_peak": 2, "r_to_stop": 2.2, "r_to_target": 2.8, "sl_live": 95.0, "tp_live": 120.0},
    "market": {"atr_now": 2.0, "atr_entry": 2.0, "htf_trend": "up", "regime_cell_now": None, "regime_cell_entry": "trend_calm",
               "funding": {"read_state": "could_not_look", "rate": None, "vs_assumption": None},
               "calendar": {"read_state": "read", "events_next_bar": []},
               "news": {"state": "none_found", "decision": None}},
    "history": {"source": "live_review_outcomes.py", "read_state": "read", "population": "comparable", "n_floor": 20,
                "net_of_full_cost_stack": True,
                "options": [{"action": "hold", "level": None, "n": 32, "mean_r": 3.1, "sd_r": 1.3, "worst_r": 0.2}]},
    "book": {"read_state": "read", "correlated_open": []},
    "per_account": [
        {"account_id": "acct_a", "account_class": "real_money", "mode": "live", "venue_read_state": "read", "venue_sl": 95.0,
         "venue_tp": 120.0, "venue_size": 1.0, "gate_preview": {"verdict": "not_available", "reason": "gate not built"}},
        {"account_id": "bybit_1", "account_class": "soak", "mode": "live", "venue_read_state": "read", "venue_sl": 95.0,
         "venue_tp": 120.0, "venue_size": 1.0, "gate_preview": {"verdict": "not_available", "reason": "gate not built"}}],
    "mechanics": {"verdict": "match", "evidence": "example"},
    "ml": [{"head": "example_head", "stage": "shadow", "state": "absent", "prediction": None}],
    "prior_decisions": [],
    "features_at_review": {"open_r": 1.2, "peak_r": 1.5, "giveback_r": 0.3, "bars_held": 6, "bars_since_peak": 2,
                           "r_to_stop": 2.2, "r_to_target": 2.8, "atr_now": 2.0, "atr_entry": 2.0, "atr_now_over_entry": 1.0},
}
GOOD_EXIT_PACKET = {k: v for k, v in GOOD_PACKET.items() if k not in ("history", "book", "per_account", "ml")}
GOOD_EXIT_PACKET["meta"] = dict(GOOD_PACKET["meta"], packet_id="DP-20261026T1200Z-pkg-1", packet_kind="exit")
GOOD_EXIT_PACKET["prior_decisions"] = [{"decision_id": "DD-20261026T0900Z-pkg-1", "judged_at": "2026-10-26T09:00:30Z",
                                        "action": "tighten_sl", "applied": True}]
GOOD_EXIT_PACKET["outcome"] = {"t1": True, "closed_at": "2026-10-26T12:00:00Z", "net_r": 1.4,
                               "provenance": "measured", "exit_reason": "sl_hit"}

GOOD_DECISION = {
    "schema_version": 2, "decision_id": "DD-20261026T0900Z-pkg-1", "packet_id": "DP-20261026T0900Z-pkg-1",
    "packet_sha": packet_sha(GOOD_PACKET), "packet_kind": "in_trade", "role": "in_trade", "order_package_id": "pkg-1",
    "judged_at": "2026-10-26T09:00:30Z", "info_cutoff_at": "2026-10-26T08:59:30Z", "trigger_event": "r_milestone",
    "model": "sonnet-tier", "session": "session_x", "prompt_sha": None, "skill_sha": None, "label_version": 1,
    "label_provenance": "judgment", "label_source": "live", "pre_cutoff": False, "action": "tighten_sl",
    "params": {"level": 98.0, "level_atr": 1.0, "frac": None, "bars": None}, "proposal": None,
    "alternatives": [
        {"action": "hold", "chosen": False, "symbol": None, "side": None, "level": None, "source": "ltr0_table", "n": 32, "mean_r": 3.1, "sd_r": 1.3},
        {"action": "tighten_sl", "chosen": True, "symbol": None, "side": None, "level": 98.0, "source": "not_priced", "n": None, "mean_r": None, "sd_r": None}],
    "judge_prior": 0.6, "confidence": "measured", "basis": "preference_within_bound", "rationale": "example",
    "escalated_to": None, "intent_id": "INT-1",
    "disposition": {"route": "auto_applied", "per_account": [
        {"account_id": "bybit_1", "account_class": "soak", "verdict": "approve", "reason": None, "applied": True,
         "level_before": 95.0, "level_after": 98.0, "readback": "match", "desk_touched": True, "trade_id": "T-b1-1"},
        {"account_id": "acct_a", "account_class": "real_money", "verdict": "refuse", "reason": "example", "applied": False,
         "level_before": 95.0, "level_after": None, "readback": "not_applicable", "desk_touched": False, "trade_id": None}]},
    "external_context": {"used": False, "trigger": None, "sources": [], "summary": None, "reproducible": True},
    "training": {"train_eligible": True, "gate_eligible": True, "exclusion_reasons": []},
}
GOOD_TOUCH = {
    "schema_version": 2, "touch_id": "DT-20261026T0900Z-pkg-1-bybit_1", "order_package_id": "pkg-1", "account": "bybit_1",
    "account_class": "soak", "side": "long", "intent_id": "INT-1", "decision_id": "DD-20261026T0900Z-pkg-1",
    "applied_at": "2026-10-26T09:01:00Z", "level_before": 95.0, "level_after": 98.0, "verdict": "approve", "sandbox": True,
}


_NA = {"read_state": "not_applicable"}
GOOD_SCAN = {
    "schema_version": 2,
    "meta": {"packet_id": "DP-20261026T0900Z-scan-15m", "packet_kind": "scan", "packet_version": 3, "mode": "live",
             "built_at": "2026-10-26T09:00:00Z", "info_cutoff_at": "2026-10-26T09:00:00Z", "generator": "example",
             "missing_inputs": ["universe.SOLUSDT.funding: no route"]},
    "universe": [
        {"symbol": "ETHUSDT", "venue": "bybit", "venue_class": "linear_perp", "tier": "full", "tradable_by": ["soak", "real_money"],
         "timeframe": "1h", "last_close": 100.0, "atr": 2.0, "htf_trend": "up", "regime_cell": "trend_calm",
         "funding": {"read_state": "read", "rate": 0.0001},
         "swing": {"read_state": "read", "high": 106.0, "low": 96.0, "dist_high_atr": 3.0, "dist_low_atr": 2.0},
         "session": "us", "calendar": {"read_state": "read", "events_next_bar": []},
         "spread": {"read_state": "read", "bps": 1.0}, "volume_24h": 1.0e9},
        {"symbol": "SOLUSDT", "venue": "bybit", "venue_class": "linear_perp", "tier": "full", "tradable_by": ["soak"],
         "timeframe": "1h", "last_close": 50.0, "atr": 1.0, "htf_trend": "flat", "regime_cell": None,
         "funding": {"read_state": "could_not_look", "rate": None},
         "swing": {"read_state": "read", "high": 52.0, "low": 48.0, "dist_high_atr": 2.0, "dist_low_atr": 2.0},
         "session": "us", "calendar": {"read_state": "read", "events_next_bar": []},
         "spread": {"read_state": "read", "bps": 2.0}, "volume_24h": 4.0e8},
        {"symbol": "NEWUSDT", "venue": "bybit", "venue_class": "linear_perp", "tier": "light", "tradable_by": [],
         "timeframe": None, "last_close": None, "atr": None, "htf_trend": None, "regime_cell": None,
         "funding": dict(_NA, rate=None),
         "swing": dict(_NA, high=None, low=None, dist_high_atr=None, dist_low_atr=None),
         "session": None, "calendar": dict(_NA, events_next_bar=None),
         "spread": {"read_state": "read", "bps": 9.0}, "volume_24h": 2.0e6}],
    "system_book": {"read_state": "read", "near_signals_read_state": "read", "items": [
        {"order_package_id": "pkg-9", "leg": "example_leg", "symbol": "ETHUSDT", "side": "short", "timeframe": "4h",
         "status": "open", "bars_to_signal": None, "entry": 104.0, "sl": 108.0, "tp": 96.0},
        {"order_package_id": None, "leg": "example_leg_2", "symbol": "SOLUSDT", "side": "long", "timeframe": "1h",
         "status": "near_signal", "bars_to_signal": 1, "entry": None, "sl": None, "tp": None}]},
    "desk_book": {"read_state": "read", "items": []},
    "history": {"source": "scan_packet.py base rates", "read_state": "read", "population": "ETHUSDT 1h bars 2024-01..2026-10",
                "n_floor": 200, "net_of_full_cost_stack": True, "cost_policy": "resolve_cost_policy(bybit, ETHUSDT)",
                "r_unit": "atr_stop_1x", "rows": [
                    {"symbol": "ETHUSDT", "timeframe": "1h", "side": "long", "horizon_bars": 12, "n": 1500, "mean_r": 0.02,
                     "sd_r": 1.9, "p10_r": -2.3, "p50_r": 0.0, "p90_r": 2.4, "mean_cost_r": 0.04}]},
    "ml": [{"head": "example_head", "stage": "shadow", "state": "absent", "prediction": None}],
}
GOOD_SCAN["features_at_review"] = project_scan_features(GOOD_SCAN)

GOOD_PROPOSAL = {
    "symbol": "ETHUSDT", "venue_class": "linear_perp", "side": "long", "timeframe": "1h", "horizon_bars": 12,
    "entry": {"type": "limit", "level": 99.0, "good_till_bars": 3},
    "stop": {"level": 96.0, "basis": "swing_level"},
    "tp": {"level": 105.0, "basis": "swing_level", "p_hit": 0.4},
    "expected_r_net": 0.15, "thesis": "example", "novelty": "new", "onboarding": "onboarded",
}
GOOD_ENTRY_DECISION = dict(
    copy.deepcopy(GOOD_DECISION), decision_id="DD-20261026T0900Z-scan-15m-1", packet_id=GOOD_SCAN["meta"]["packet_id"],
    packet_sha=packet_sha(GOOD_SCAN), packet_kind="scan", role="entry_generation", order_package_id=None,
    info_cutoff_at=GOOD_SCAN["meta"]["info_cutoff_at"], trigger_event="bar_close", label_source="shadow",
    action="propose_entry", params={"level": None, "level_atr": None, "frac": None, "bars": None},
    proposal=GOOD_PROPOSAL, judge_prior=0.4, confidence="suggestive", basis="ev_positive", intent_id=None,
    alternatives=[
        {"action": "no_trade", "chosen": False, "symbol": None, "side": None, "level": None, "source": "base_rate", "n": 1500, "mean_r": 0.0, "sd_r": 0.0},
        {"action": "propose_entry", "chosen": True, "symbol": "ETHUSDT", "side": "long", "level": 99.0, "source": "base_rate", "n": 1500, "mean_r": 0.02, "sd_r": 1.9}],
    disposition={"route": "none", "per_account": []},
)
GOOD_OUTCOME = {
    "schema_version": 2, "outcome_id": "DO-20261026T2100Z-scan-15m-1", "decision_id": GOOD_ENTRY_DECISION["decision_id"],
    "kind": "replayed", "account_id": None, "order_package_id": None, "trade_id": None, "computed_at": "2026-10-26T21:00:00Z",
    "net_r": 1.9, "mae_r": -0.4, "mfe_r": 2.1, "giveback_r": 0.0, "bars_held": 9, "close_reason": "tp_hit",
    "provenance": "computed", "net_of_full_cost_stack": True, "cost_policy": "resolve_cost_policy(bybit, ETHUSDT)", "reason": None,
}
GOOD_CONSUMED = {"schema_version": 2, "decision_id": GOOD_ENTRY_DECISION["decision_id"],
                 "dataset_build_id": "claude_judgments@example", "consumed_at": "2026-11-20T00:00:00Z"}


def _mut(base, fn):
    r = copy.deepcopy(base)
    fn(r)
    return r


def _self_test() -> int:
    ps, ds = json.loads(PACKET_SCHEMA.read_text()), json.loads(DECISION_SCHEMA.read_text())
    ok = True

    def expect(label, problems, bad):
        nonlocal ok
        good = bool(problems) == bad
        print(f"  {'PASS' if good else 'FAIL'}  {label}")
        ok &= good

    with tempfile.TemporaryDirectory() as d:
        pk = Path(d) / "packets"
        pk.mkdir()
        (pk / "DP-20261026T0900Z-pkg-1.json").write_text(json.dumps(GOOD_PACKET))
        (pk / f"{GOOD_SCAN['meta']['packet_id']}.json").write_text(json.dumps(GOOD_SCAN))
        desk_pkt = _mut(GOOD_PACKET, lambda r: (r["meta"].update(packet_id="DP-20261026T0900Z-desk-1"), r["package"].update(leg="claude_desk", order_package_id="desk-1")))
        (pk / "DP-20261026T0900Z-desk-1.json").write_text(json.dumps(desk_pkt))
        dp = lambda r: decision_problems(r, ds, pk)  # noqa: E731
        E = GOOD_ENTRY_DECISION
        PR = lambda fn: _mut(E, lambda r: fn(r["proposal"]))  # noqa: E731
        OP = lambda r: outcome_problems(r, ds, {E["decision_id"]: E})  # noqa: E731
        P = lambda r: packet_problems(r, ps)  # noqa: E731
        T = lambda r: touch_problems(r, ds, {GOOD_DECISION["decision_id"]: GOOD_DECISION})  # noqa: E731

        expect("a well-formed in_trade packet passes", P(GOOD_PACKET), False)
        expect("a well-formed exit packet passes", P(GOOD_EXIT_PACKET), False)
        expect("a well-formed decision passes", dp(GOOD_DECISION), False)
        expect("a well-formed touch passes", T(GOOD_TOUCH), False)
        # packets
        expect("entry packet carrying `state` is refused", P(_mut(GOOD_PACKET, lambda r: (r["meta"].update(packet_kind="entry"), r.pop("mechanics"), r.pop("prior_decisions")))), True)
        expect("in_trade packet missing `mechanics` is refused", P(_mut(GOOD_PACKET, lambda r: r.pop("mechanics"))), True)
        expect("outcome on a non-exit packet is refused", P(_mut(GOOD_PACKET, lambda r: r.update(outcome=GOOD_EXIT_PACKET["outcome"]))), True)
        expect("exit packet without outcome is refused", P(_mut(GOOD_EXIT_PACKET, lambda r: r.pop("outcome"))), True)
        expect("packet_version 2 is refused", P(_mut(GOOD_PACKET, lambda r: r["meta"].update(packet_version=2))), True)
        expect("null state.open_r not named in missing_inputs is refused",
               P(_mut(GOOD_PACKET, lambda r: (r["state"].update(open_r=None), r["features_at_review"].update(open_r=None)))), True)
        expect("could_not_look funding not named in missing_inputs is refused",
               P(_mut(GOOD_PACKET, lambda r: r["meta"].update(missing_inputs=[]))), True)
        expect("zero peak with unverified provenance is refused",
               P(_mut(GOOD_PACKET, lambda r: (r["state"].update(peak_r=0, peak_provenance="unverified"), r["features_at_review"].update(peak_r=0)))), True)
        expect("features_at_review that is not the projection is refused",
               P(_mut(GOOD_PACKET, lambda r: r["features_at_review"].update(open_r=9.9))), True)
        expect("ml head absent with a prediction (imputed) is refused",
               P(_mut(GOOD_PACKET, lambda r: r["ml"][0].update(prediction=0.0))), True)
        expect("a history option with n == 0 and numbers is refused",
               P(_mut(GOOD_PACKET, lambda r: r["history"]["options"][0].update(n=0))), True)
        expect("per_account not covering package.accounts is refused",
               P(_mut(GOOD_PACKET, lambda r: r["per_account"].pop())), True)
        # decisions
        expect("prose action is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(action="move it up a bit"))), True)
        expect("size change is not in any enum", dp(_mut(GOOD_DECISION, lambda r: r.update(action="size_up"))), True)
        expect("widen_sl is not in any enum", dp(_mut(GOOD_DECISION, lambda r: r.update(action="widen_sl"))), True)
        expect("an entry-role action on an in_trade role is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(action="skip"))), True)
        expect("the v0 veto action is in no enum", dp(_mut(E, lambda r: r.update(action="veto_candidate"))), True)
        expect("the v0 market_watch role is gone", dp(_mut(E, lambda r: r.update(role="market_watch"))), True)
        expect("schema_version 1 is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(schema_version=1))), True)
        expect("a widening tighten_sl (long stop falls) is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r["params"].update(level=94.0), r["alternatives"][1].update(level=94.0)))), True)
        expect("role entry_review on an in_trade packet is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(role="entry_review", action="take"))), True)
        expect("tighten_sl without a level is refused", dp(_mut(GOOD_DECISION, lambda r: r["params"].update(level=None))), True)
        expect("partial_close frac out of (0,1) is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="exit", action="partial_close"), r["params"].update(level=None, level_atr=None, frac=1.0)))), True)
        expect("insufficient_n written as hold is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(action="hold", basis="insufficient_n"), r["params"].update(level=None, level_atr=None)))), True)
        expect("auto_applied on an exit-role close is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="exit", action="close"), r["params"].update(level=None, level_atr=None)))), True)
        expect("a shadow entry_review row carrying an intent is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(role="entry_review", packet_kind="entry", action="skip"), r["params"].update(level=None, level_atr=None)))), True)
        expect("an applied account with a readback mismatch is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][0].update(readback="mismatch"))), True)
        expect("desk_touched that disagrees with applied is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][0].update(desk_touched=False))), True)
        expect("an account that does not carry the package is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["disposition"]["per_account"][1].update(account_id="acct_zzz"))), True)
        expect("packet_sha not matching the committed packet is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(packet_sha="0" * 64))), True)
        expect("a missing packet file is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(packet_id="DP-20261026T0900Z-nope"))), True)
        expect("a model identifier instead of a tier is refused", dp(_mut(GOOD_DECISION, lambda r: r.update(model="some-model-5"))), True)
        # scan packets
        expect("a well-formed scan packet passes", P(GOOD_SCAN), False)
        expect("scan carrying a package is refused", P(_mut(GOOD_SCAN, lambda r: r.update(package=GOOD_PACKET["package"]))), True)
        expect("entry packet without package is refused", P(_mut(GOOD_PACKET, lambda r: (r["meta"].update(packet_kind="entry"), [r.pop(k) for k in ("state", "mechanics", "prior_decisions", "package")]))), True)
        expect("scan without system_book is refused", P(_mut(GOOD_SCAN, lambda r: r.pop("system_book"))), True)
        expect("a light-tier row carrying an ATR is refused",
               P(_mut(GOOD_SCAN, lambda r: (r["universe"][2].update(atr=1.0), r.update(features_at_review=project_scan_features(r))))), True)
        expect("a full-tier null ATR not named in missing_inputs is refused",
               P(_mut(GOOD_SCAN, lambda r: (r["universe"][0].update(atr=None), r.update(features_at_review=project_scan_features(r))))), True)
        expect("could_not_look funding not named is refused", P(_mut(GOOD_SCAN, lambda r: r["meta"].update(missing_inputs=[]))), True)
        expect("system_book could_not_look with [] (collapsed) is refused",
               P(_mut(GOOD_SCAN, lambda r: (r["system_book"].update(read_state="could_not_look", items=[]), r["meta"]["missing_inputs"].append("system_book: relay down"), r.update(features_at_review=project_scan_features(r))))), True)
        expect("system_book could_not_look, null and named passes",
               P(_mut(GOOD_SCAN, lambda r: (r["system_book"].update(read_state="could_not_look", items=None), r["meta"]["missing_inputs"].append("system_book: relay down"), r.update(features_at_review=project_scan_features(r))))), False)
        expect("near-signals unread but near_signal items present is refused",
               P(_mut(GOOD_SCAN, lambda r: (r["system_book"].update(near_signals_read_state="not_applicable"), r.update(features_at_review=project_scan_features(r))))), True)
        unread = _mut(GOOD_SCAN, lambda r: (r["system_book"].update(near_signals_read_state="could_not_look", items=r["system_book"]["items"][:1]),
                                            r["meta"]["missing_inputs"].append("system_book.near_signals: no producer"),
                                            r.update(features_at_review=project_scan_features(r))))
        expect("a scan with near-signals could_not_look (named) passes", P(unread), False)
        nov = proposal_problems(_mut(E, lambda r: r["proposal"].update(symbol="SOLUSDT", entry={"type": "market", "level": 50.0, "good_till_bars": 1},
                                                                        stop={"level": 49.0, "basis": "atr_multiple"},
                                                                        tp={"level": 52.0, "basis": "swing_level", "p_hit": 0.3})), unread)
        expect("near-signals unread and no package match: novelty `new` is refused (it is unverifiable)",
               [x for x in nov if "unverifiable" in x], True)
        expect("a near-signal two bars out is refused",
               P(_mut(GOOD_SCAN, lambda r: r["system_book"]["items"][1].update(bars_to_signal=2))), True)
        expect("base rates not net of the full cost stack are refused",
               P(_mut(GOOD_SCAN, lambda r: r["history"].update(net_of_full_cost_stack=False))), True)
        expect("a base-rate row with n 0 and numbers is refused",
               P(_mut(GOOD_SCAN, lambda r: r["history"]["rows"][0].update(n=0))), True)
        expect("a scan history in the entry shape is refused",
               P(_mut(GOOD_SCAN, lambda r: r.update(history=GOOD_PACKET["history"]))), True)
        expect("scan features that are not the projection are refused",
               P(_mut(GOOD_SCAN, lambda r: r["features_at_review"].update({"ETHUSDT.atr": 9.0}))), True)
        expect("info_cutoff_at after built_at is refused",
               P(_mut(GOOD_SCAN, lambda r: r["meta"].update(info_cutoff_at="2026-10-26T09:05:00Z"))), True)
        # entry generation
        expect("a well-formed shadow propose_entry passes", dp(E), False)
        expect("a no_trade on a scan passes", dp(_mut(E, lambda r: (r.update(action="no_trade", proposal=None, judge_prior=None),
               [a.update(chosen=a["action"] == "no_trade") for a in r["alternatives"]]))), False)
        expect("propose_entry without a proposal is refused", dp(_mut(E, lambda r: r.update(proposal=None))), True)
        expect("a proposal with a size field is refused", dp(PR(lambda p: p.update(size=1.0))), True)
        expect("a size key anywhere in the row is refused", dp(_mut(E, lambda r: r["disposition"].update(qty=3))), True)
        expect("a proposal missing tp is refused", dp(PR(lambda p: p.pop("tp"))), True)
        expect("a trail-decides tp basis is refused", dp(PR(lambda p: p["tp"].update(basis="trail"))), True)
        expect("a 50 R sentinel tp is refused", dp(PR(lambda p: (p["stop"].update(level=98.99), p["tp"].update(level=99.6)))), True)
        expect("a tp at the venue cap is refused", dp(PR(lambda p: p["tp"].update(level=109.0))), True)
        expect("a tp below the reach floor is refused", dp(PR(lambda p: p["tp"].update(p_hit=0.05))), True)
        expect("inverted long geometry is refused", dp(PR(lambda p: p["stop"].update(level=101.0))), True)
        expect("a short with long geometry is refused", dp(PR(lambda p: p.update(side="short"))), True)
        expect("expected_r_net above the gross best case is refused", dp(PR(lambda p: p.update(expected_r_net=5.0))), True)
        expect("propose_entry without judge_prior is refused", dp(_mut(E, lambda r: r.update(judge_prior=None))), True)
        expect("a proposal on a symbol outside the universe is refused", dp(PR(lambda p: p.update(symbol="XRPUSDT"))), True)
        expect("a light-tier symbol claimed onboarded is refused", dp(PR(lambda p: p.update(symbol="NEWUSDT"))), True)
        expect("novelty `new` on a near-signal duplicate is refused",
               dp(PR(lambda p: p.update(symbol="SOLUSDT", entry={"type": "market", "level": 50.0, "good_till_bars": 1},
                                        stop={"level": 49.0, "basis": "atr_multiple"}, tp={"level": 52.0, "basis": "swing_level", "p_hit": 0.3}))), True)
        expect("novelty duplicates_near_signal on the near-signal passes",
               dp(PR(lambda p: p.update(symbol="SOLUSDT", novelty="duplicates_near_signal", entry={"type": "market", "level": 50.0, "good_till_bars": 1},
                                        stop={"level": 49.0, "basis": "atr_multiple"}, tp={"level": 52.0, "basis": "swing_level", "p_hit": 0.3}))), False)
        expect("entry_generation with an order_package_id is refused", dp(_mut(E, lambda r: r.update(order_package_id="pkg-1"))), True)
        expect("entry_generation on an in_trade packet is refused",
               dp(_mut(E, lambda r: r.update(packet_id=GOOD_DECISION["packet_id"], packet_sha=GOOD_DECISION["packet_sha"], packet_kind="in_trade"))), True)
        expect("a shadow proposal routed submitted is refused", dp(_mut(E, lambda r: (r["disposition"].update(route="submitted"), r.update(intent_id="INT-9")))), True)
        expect("a live proposal submitted with an intent passes",
               dp(_mut(E, lambda r: (r.update(label_source="live", intent_id="INT-9"), r["disposition"].update(route="submitted")))), False)
        expect("a live proposal submitted without an intent is refused",
               dp(_mut(E, lambda r: (r.update(label_source="live"), r["disposition"].update(route="submitted")))), True)
        expect("a proposal auto_applied is refused",
               dp(_mut(E, lambda r: (r.update(label_source="live", intent_id="INT-9"), r["disposition"].update(route="auto_applied")))), True)
        expect("a historical_masked row on a live packet is refused",
               dp(_mut(E, lambda r: (r.update(label_source="historical_masked"), r["training"].update(gate_eligible=False, exclusion_reasons=["historical_masked"])))), True)
        # alternatives + training marker
        expect("missing alternatives are refused", dp(_mut(E, lambda r: r.update(alternatives=[]))), True)
        expect("alternatives without the no_trade baseline are refused", dp(_mut(E, lambda r: r["alternatives"].pop(0))), True)
        expect("two chosen alternatives are refused", dp(_mut(E, lambda r: r["alternatives"][0].update(chosen=True))), True)
        expect("an unpriced alternative with numbers is refused", dp(_mut(E, lambda r: r["alternatives"][0].update(source="not_priced"))), True)
        expect("a pre_cutoff row marked gate-eligible is refused", dp(_mut(E, lambda r: r.update(pre_cutoff=True))), True)
        expect("a pre_cutoff row trains but never gates",
               dp(_mut(E, lambda r: (r.update(pre_cutoff=True), r["training"].update(gate_eligible=False, exclusion_reasons=["pre_cutoff"])))), False)
        # desk-leg applies
        DL = _mut(GOOD_DECISION, lambda r: r.update(packet_id="DP-20261026T0900Z-desk-1", packet_sha=packet_sha(desk_pkt), order_package_id="desk-1"))
        CL = lambda r: (r.update(role="exit", action="close"), r["params"].update(level=None, level_atr=None),  # noqa: E731
                        r.update(alternatives=[dict(GOOD_DECISION["alternatives"][0]), dict(GOOD_DECISION["alternatives"][1], action="close", level=None)]),
                        [a.update(level_after=None, level_before=None) for a in r["disposition"]["per_account"]])
        expect("a close applied on a strategy trade is refused", dp(_mut(GOOD_DECISION, CL)), True)
        expect("a tp_revise applied on a strategy trade is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(action="tp_revise"), r["alternatives"][1].update(action="tp_revise")))), True)
        expect("a tp_revise applied on the desk's own trade passes",
               dp(_mut(DL, lambda r: (r.update(action="tp_revise"), r["alternatives"][1].update(action="tp_revise")))), False)
        # outcomes + consumed
        expect("a replayed outcome passes", OP(GOOD_OUTCOME), False)
        expect("an outcome before the cutoff (T0 leak) is refused", OP(_mut(GOOD_OUTCOME, lambda r: r.update(computed_at="2026-10-26T08:00:00Z"))), True)
        expect("a net_r not net of cost is refused", OP(_mut(GOOD_OUTCOME, lambda r: r.update(net_of_full_cost_stack=False))), True)
        expect("a realised outcome without trade_id is refused", OP(_mut(GOOD_OUTCOME, lambda r: r.update(kind="realised", provenance="measured", account_id="bybit_1", order_package_id="desk-1"))), True)
        expect("not_computable with a zero is refused", OP(_mut(GOOD_OUTCOME, lambda r: r.update(kind="not_computable", net_r=0.0, reason="no candles"))), True)
        expect("an orphan outcome is refused", outcome_problems(GOOD_OUTCOME, ds, {}), True)
        expect("consuming a train-eligible decision passes", consumed_problems(GOOD_CONSUMED, ds, {E["decision_id"]: E}), False)
        expect("consuming an external_context row (a leak) is refused",
               consumed_problems(GOOD_CONSUMED, ds, {E["decision_id"]: _mut(E, lambda r: r["training"].update(train_eligible=False, gate_eligible=False))}), True)
        # external_context
        EXT = {"used": True, "trigger": "calendar", "reproducible": False, "summary": "CPI due",
               "sources": [{"url_or_id": "example:cpi", "title": None, "fetched_at": "2026-10-26T08:59:00Z"}]}
        expect("external_context used with a calendar trigger event passes",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=EXT),
                                                 r.update(training={"train_eligible": False, "gate_eligible": False, "exclusion_reasons": ["external_context"]})))), False)
        expect("external_context used but still train-eligible is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=EXT)))), True)
        expect("external_context used with empty sources is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=dict(EXT, sources=[]))))), True)
        expect("external_context used but reproducible=true is refused",
               dp(_mut(GOOD_DECISION, lambda r: (r.update(trigger_event="calendar"), r.update(external_context=dict(EXT, reproducible=True))))), True)
        expect("external_context calendar trigger on an r_milestone event is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(external_context=EXT))), True)
        expect("external_context unused but carrying sources is refused",
               dp(_mut(GOOD_DECISION, lambda r: r["external_context"].update(sources=EXT["sources"]))), True)
        expect("external_context trigger outside the exception list is refused",
               dp(_mut(GOOD_DECISION, lambda r: r.update(external_context=dict(EXT, trigger="curiosity")))), True)
        # touches
        expect("a touch on a non-sandbox account flagged sandbox is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(account="acct_a"))), True)
        expect("a loosening long touch is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(level_after=94.0))), True)
        expect("a touch with verdict refuse is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(verdict="refuse"))), True)
        expect("a touch whose decision did not apply it is refused", T(_mut(GOOD_TOUCH, lambda r: r.update(level_after=97.0))), True)
        expect("an orphan touch is refused", touch_problems(GOOD_TOUCH, ds, {}), True)
        # file level
        dec, tch = Path(d) / "decisions.jsonl", Path(d) / "touches.jsonl"
        oc, cs = Path(d) / "outcomes.jsonl", Path(d) / "consumed.jsonl"
        dec.write_text(json.dumps(GOOD_DECISION) + "\n" + json.dumps(E) + "\n")
        tch.write_text(json.dumps(GOOD_TOUCH) + "\n")
        oc.write_text(json.dumps(GOOD_OUTCOME) + "\n")
        cs.write_text(json.dumps(GOOD_CONSUMED) + "\n")
        c = findings(dec, tch, pk)
        expect("a consistent decision + touch + outcome + consumed + packet set passes", c, False)
        late = datetime(2026, 12, 1, tzinfo=timezone.utc)
        expect("never_trained_on names the old unconsumed row only",
               [] if never_trained_on(dec, cs, as_of=late) == [GOOD_DECISION["decision_id"]] else ["mismatch"], False)
        oc.write_text(json.dumps(GOOD_OUTCOME) + "\n" + json.dumps(GOOD_OUTCOME) + "\n")
        expect("a duplicate outcome_id is refused", findings(dec, tch, pk), True)
        oc.write_text("")
        cs.write_text("")
        tch.write_text(json.dumps(GOOD_TOUCH) + "\n" + json.dumps(GOOD_TOUCH) + "\n")
        expect("a duplicate touch_id is refused", findings(dec, tch, pk), True)
        tch.write_text("")
        dec.write_text("not json\n")
        expect("a bad line is refused", findings(dec, tch, pk), True)
        dec.write_text("")
        expect("empty files pass (append-only, start empty)", findings(dec, tch, pk), False)
        cs.unlink()
        expect("a missing consumed.jsonl is refused", findings(dec, tch, pk), True)
        cs.write_text("")
        (pk / "DP-20261026T0900Z-pkg-1.json").write_text(json.dumps(_mut(GOOD_PACKET, lambda r: r.pop("mechanics"))))
        expect("a committed packet that breaks the kind matrix is refused", findings(dec, tch, pk), True)
    print("desk-records-guard self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--self-test" in argv:
        return _self_test()
    f = findings()
    if f:
        print("::error::comms/desk records fail comms/schema/desk_*.schema.json:")
        for x in f:
            print(f"  ✗ {x}")
        return 1
    print("desk-records-guard: comms/desk packets, decisions, touches, outcomes and consumed rows are schema-valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
