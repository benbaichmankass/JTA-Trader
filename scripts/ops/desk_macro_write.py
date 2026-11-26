#!/usr/bin/env python3
# wiring: row DESK-MACRO-DAILY (spec docs/research/desk-macro-daily-SPEC-2026-11-25.md); writes comms/desk/macro/<date>.json + <date>.md
"""Desk macro daily brief: validate a drafted brief and write it ONCE, point-in-time, with a readable render.

Tier 1 (advice-only). The brief's trades are SHADOW proposals graded later like desk proposals; nothing here places, sizes or
amends an order or writes config/. A brief that breaks a rule is REFUSED (exit 1, every problem listed), never fixed up.

Rules (spec section 2):
  - schema `desk_macro_brief/1`; required keys present; brief_id matches judged_at; model is a TIER (`*-tier`), never a model id
  - every source has retrieved_at <= judged_at and a content_sha256; every judgement cites >= 1 known source_id
  - trades: the desk proposal geometry and TP doctrine (stop/entry/tp ordering, tp < SENTINEL_R_FLOOR R, tp inside the venue cap,
    p_hit in [REACH_FLOOR, 1)); timeframe 1d; expected_r_net < tp R; no size-shaped key
  - symbol: ANY venue-tradable symbol "if it has the data to support it" (operator 2026-11-26, verbatim: "it shouldn't be limited
    to any specific symbols. It should be able to recommend trades on any symbols that we are able to trade if it has the data to
    support it."): its daily bars are measured in the packet or in a fetch file the brief lists in fetch_paths (fetch sha valid,
    tied to the same packet, retrieved_at <= judged_at), AND desk_macro_packet.is_tradable() says the proposal's venue_class can
    fill it (the venue's own answer, else the symbol is rostered on that venue). Shadow proposals only; real money follows the ladder
  - management: every trade carries a `management` block for the live-trade-review sessions that would manage it (operator
    2026-11-26: "specific instructions for the LTR sessions ... and how the trade was designed"): design, expected_path,
    watch_for[], catalyst_timing[], tighten_if[], exit_early_if[], do_not[], thesis_invalidated_by. watch_for / tighten_if /
    exit_early_if items are {signal, source_ids?, check?}; an optional check {kind: close_above|close_below|high_above|low_below,
    level} is machine-evaluated by desk_macro_outcomes on the replay window
  - informs: leg exists in config/strategies.yaml; until > judged_at
  - events: class in the v1 taxonomy
  - packet: packet_path names the desk_macro_packet the brief was drafted from (scripts/ops/desk_macro_packet.py); its sha256 must
    equal packet_sha and its built_at must be <= judged_at
  - trades == [] is REFUSED unless that packet itself shows prices could_not_look (operator 2026-11-26: "it needs to be proposing
    trades"); a thesis-free day still lists its best-ranked candidate trades, each with judge_prior. no_trade_reason is then required
  - write-once: an existing comms/desk/macro/<date>.json is never overwritten (a correction is a new brief with `supersedes`)

  python3 scripts/ops/desk_macro_write.py validate BRIEF.json
  python3 scripts/ops/desk_macro_write.py write BRIEF.json [--out-dir comms/desk/macro]
  python3 scripts/ops/desk_macro_write.py --self-test
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.ops.desk_macro_packet import is_tradable, prices_could_not_look, sha_ok  # noqa: E402
from src.runtime.target_expectation import SENTINEL_R_FLOOR  # noqa: E402  (the fleet's sentinel idiom)
from src.runtime.tp_venue_cap import TP_VENUE_CAP_PCT  # noqa: E402

SCHEMA = "desk_macro_brief/1"
REACH_FLOOR = 0.10                     # scripts/ci/check_desk_records.py REACH_FLOOR (same TP-doctrine floor)
OUT_DIR = REPO / "comms" / "desk" / "macro"
STRATEGIES = REPO / "config" / "strategies.yaml"
REQUIRED = ("schema", "brief_id", "judged_at", "info_cutoff_at", "model", "sources", "regime", "tilts", "calendar", "events",
            "trades", "informs", "training")
TAXONOMY = {
    "scheduled.macro": ("rate_decision", "cpi", "nfp", "gdp", "pmi", "claims"),
    "scheduled.earnings": ("index_heavyweight", "rostered_symbol"),
    "unscheduled.corporate": ("ceo_departure", "guidance_cut", "m_and_a", "buyback", "accounting_issue"),
    "unscheduled.tech": ("product_proof", "regulatory_approval", "outage_or_failure"),
    "unscheduled.policy": ("tariff", "sanction", "fiscal", "central_bank_unscheduled"),
    "unscheduled.geopolitical": ("conflict", "election"),
    "unscheduled.crypto": ("listing", "hack_or_exploit", "regulatory", "etf_flow"),
}
CLASSES = {f"{k}.{v}" for k, vs in TAXONOMY.items() for v in vs} | {"other"}
SIZE_KEYS = {"qty", "quantity", "size", "notional", "units", "contracts", "risk_pct", "risk_usd", "leverage", "position_size"}


def _ts(s) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def desk_universe(path: Path = STRATEGIES) -> tuple[set, set]:
    d = yaml.safe_load(path.read_text())["strategies"]
    return set(d.get("claude_desk", {}).get("symbols") or []), set(d)


def _size_keys(v, path="") -> list[str]:
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if str(k).lower() in SIZE_KEYS:
                out.append(f"{path}.{k}")
            out += _size_keys(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += _size_keys(x, f"{path}[{i}]")
    return out


MGMT_TEXT = ("design", "expected_path", "thesis_invalidated_by")
MGMT_LISTS = ("watch_for", "catalyst_timing", "tighten_if", "exit_early_if", "do_not")
MGMT_NONEMPTY = ("watch_for", "exit_early_if")
CHECK_KINDS = ("close_above", "close_below", "high_above", "low_below")


def management_problems(m, tag: str, sids: set) -> list[str]:
    if not isinstance(m, dict):
        return [f"{tag}: management block is required (design, expected_path, watch_for, catalyst_timing, tighten_if, "
                "exit_early_if, do_not, thesis_invalidated_by)"]
    out = [f"{tag}.management.{k}: non-empty text required" for k in MGMT_TEXT if not str(m.get(k) or "").strip()]
    for k in MGMT_LISTS:
        v = m.get(k)
        if not isinstance(v, list):
            out.append(f"{tag}.management.{k}: a list is required (empty only for catalyst_timing / tighten_if / do_not)")
            continue
        if k in MGMT_NONEMPTY and not v:
            out.append(f"{tag}.management.{k}: at least one item is required")
        if k in ("watch_for", "tighten_if", "exit_early_if"):
            for j, it in enumerate(v):
                it_tag = f"{tag}.management.{k}[{j}]"
                if not isinstance(it, dict) or not str(it.get("signal") or "").strip():
                    out.append(f"{it_tag}: an object with a non-empty `signal` is required")
                    continue
                bad = set(it.get("source_ids") or []) - sids
                if bad:
                    out.append(f"{it_tag}: cites unknown source_id(s) {sorted(bad)}")
                ck = it.get("check")
                if ck is not None:
                    try:
                        ok = ck.get("kind") in CHECK_KINDS and float(ck.get("level")) > 0
                    except (AttributeError, TypeError, ValueError):
                        ok = False
                    if not ok:
                        out.append(f"{it_tag}: check must be {{kind: {'|'.join(CHECK_KINDS)}, level: > 0}}")
    return out


def evidence(pkt: dict | None, fetches: list[dict], judged_at: datetime) -> tuple[dict, list[str]]:
    """symbol -> {bars, source, trad} from the packet, then each valid fetch file; plus the fetch-file problems."""
    ev, probs = {}, []

    def take(prices: dict, trad: dict, src: str):
        for s, v in (prices.get("symbols") or {}).items():
            if v.get("read_state") == "measured" or s not in ev:
                ev[s] = {"bars": v.get("read_state") == "measured", "source": src,
                         "trad": (trad.get("symbols") or {}).get(s)}
    if pkt:
        take((pkt.get("parts") or {}).get("prices") or {}, (pkt.get("parts") or {}).get("tradability") or {}, "packet")
    for f in fetches:
        fid = f.get("fetch_id", "?")
        if not sha_ok(f, "fetch_sha"):
            probs.append(f"fetch {fid}: fetch_sha does not match its body")
            continue
        if pkt and f.get("packet_sha") != pkt.get("packet_sha"):
            probs.append(f"fetch {fid}: extends a different packet")
            continue
        try:
            if _ts(f["retrieved_at"]) > judged_at:
                probs.append(f"fetch {fid}: retrieved_at is after judged_at")
                continue
        except (KeyError, ValueError):
            probs.append(f"fetch {fid}: retrieved_at missing or not ISO")
            continue
        take(f.get("prices") or {}, f.get("tradability") or {}, fid)
    return ev, probs


def _load_json(ref: str):
    path = Path(ref) if Path(ref).is_absolute() else REPO / ref
    return json.loads(path.read_text())


def trade_problems(t: dict, i: int, ev: dict, sids: set | None = None) -> list[str]:
    p, out, tag = t.get("proposal") or {}, [], f"trades[{i}]"
    try:
        side, e, sl, tp = p["side"], float(p["entry"]["level"]), float(p["stop"]["level"]), float(p["tp"]["level"])
        p_hit = float(p["tp"]["p_hit"])
    except (KeyError, TypeError, ValueError):
        return [f"{tag}: proposal needs side, entry.level, stop.level, tp.level, tp.p_hit"]
    e_sym = ev.get(p.get("symbol"))
    if not e_sym or not e_sym["bars"]:
        out.append(f"{tag}: no measured daily bars for {p.get('symbol')!r} in the packet or a listed fetch file "
                   "(run desk_macro_packet.py fetch --packet P SYMBOL, and list the file in fetch_paths)")
    else:
        ok, basis = is_tradable(e_sym["trad"], str(p.get("venue_class")))
        if not ok:
            out.append(f"{tag}: {p.get('symbol')} is not confirmed tradable as venue_class {p.get('venue_class')!r}: {basis}")
    out += management_problems(t.get("management"), tag, sids or set())
    if p.get("timeframe") != "1d":
        out.append(f"{tag}: timeframe must be 1d (a macro brief trades daily bars)")
    if not isinstance(p.get("horizon_bars"), int) or p["horizon_bars"] < 1:
        out.append(f"{tag}: horizon_bars must be a positive integer (days)")
    long_ = side == "long"
    if side not in ("long", "short") or not ((sl < e < tp) if long_ else (tp < e < sl)):
        out.append(f"{tag}: geometry: a {side} needs {'stop < entry < tp' if long_ else 'tp < entry < stop'}")
        return out
    tp_r = abs(tp - e) / abs(e - sl)
    if tp_r >= SENTINEL_R_FLOOR:
        out.append(f"{tag}: TP doctrine: tp is {tp_r:.1f} R (>= {SENTINEL_R_FLOOR:g} R is the sentinel, not a prediction)")
    if abs(tp - e) / e >= TP_VENUE_CAP_PCT:
        out.append(f"{tag}: TP doctrine: tp sits at or beyond the venue cap ({TP_VENUE_CAP_PCT:.1%} from entry)")
    if not REACH_FLOOR <= p_hit < 1:
        out.append(f"{tag}: TP doctrine: tp.p_hit must be in [{REACH_FLOOR}, 1)")
    if not p["tp"].get("basis") or not p["stop"].get("basis"):
        out.append(f"{tag}: stop.basis and tp.basis are required")
    er = p.get("expected_r_net")
    if er is None or not float(er) < tp_r:
        out.append(f"{tag}: expected_r_net is required and must be below the proposal's own tp R ({tp_r:.2f})")
    if t.get("judge_prior") is None or not 0 <= float(t["judge_prior"]) <= 1:
        out.append(f"{tag}: judge_prior (P(TP before SL)) in [0, 1] is required")
    if not t.get("invalidation"):
        out.append(f"{tag}: invalidation (a falsifiable condition beyond the stop) is required")
    if not t.get("catalyst"):
        out.append(f"{tag}: catalyst (event_key | event_id | regime) is required")
    return out


def load_packet(b: dict) -> tuple[dict | None, str | None]:
    """The packet the brief names, or (None, why)."""
    ref = b.get("packet_path")
    if not ref:
        return None, "packet_path is required (run scripts/ops/desk_macro_packet.py first and draft from it)"
    path = Path(ref) if Path(ref).is_absolute() else REPO / ref
    try:
        return json.loads(path.read_text()), None
    except (OSError, ValueError) as e:
        return None, f"packet_path {ref}: cannot read ({type(e).__name__})"


def packet_problems(b: dict, pkt: dict | None, why: str | None) -> list[str]:
    if pkt is None:
        return [why or "packet missing"]
    out = []
    if not sha_ok(pkt):
        out.append("packet: its packet_sha does not match its body (edited after build?)")
    if b.get("packet_sha") != pkt.get("packet_sha"):
        out.append("packet_sha does not match the packet at packet_path")
    try:
        if _ts(pkt["built_at"]) > _ts(b["judged_at"]):
            out.append("packet built_at is after judged_at")
    except (KeyError, ValueError):
        out.append("packet built_at missing or not ISO")
    if not b["trades"]:
        if not prices_could_not_look(pkt):
            out.append("trades == [] is refused: the packet shows prices were read, so list the best-ranked candidate trades "
                       "(each with judge_prior); an empty list is allowed only when packet prices are could_not_look")
        elif not b.get("no_trade_reason"):
            out.append("no_trade_reason is required when trades == []")
    return out


def problems(b: dict, universe: set | None = None, legs: set | None = None, packet: dict | None = None,  # inert: universe — retired 2026-11-26, kept positional for callers
             fetches: list[dict] | None = None) -> list[str]:
    """``universe`` is retired (any venue-tradable symbol with data); kept positional for callers. ``fetches`` overrides
    reading ``b['fetch_paths']``."""
    if legs is None:
        legs = desk_universe()[1]
    out = [f"missing key {k}" for k in REQUIRED if k not in b]
    if out:
        return out
    if b["schema"] != SCHEMA:
        out.append(f"schema must be {SCHEMA}")
    try:
        jt, ct = _ts(b["judged_at"]), _ts(b["info_cutoff_at"])
    except ValueError:
        return out + ["judged_at / info_cutoff_at must be ISO timestamps"]
    if ct > jt:
        out.append("info_cutoff_at is after judged_at")
    if b["brief_id"] != f"DMB-{jt.strftime('%Y%m%dT%H%MZ')}":
        out.append(f"brief_id must be DMB-{jt.strftime('%Y%m%dT%H%MZ')} (from judged_at)")
    if not re.fullmatch(r"[a-z]+-tier", str(b["model"])):
        out.append("model must be a TIER like 'opus-tier', never a model identifier (desk rule 6)")
    sids = set()
    for i, s in enumerate(b["sources"]):
        sids.add(s.get("source_id"))
        if not s.get("content_sha256") or not s.get("retrieved_at"):
            out.append(f"sources[{i}]: content_sha256 and retrieved_at are required")
        elif _ts(s["retrieved_at"]) > jt:
            out.append(f"sources[{i}]: retrieved_at {s['retrieved_at']} is after judged_at (the desk timestamp rule)")

    def cites(obj, tag):
        ids = obj.get("source_ids") or re.findall(r"\bS\d+\b", str(obj.get("basis", "")))
        if not ids:
            out.append(f"{tag}: cites no source_id")
        elif not set(ids) <= sids:
            out.append(f"{tag}: cites unknown source_id(s) {sorted(set(ids) - sids)}")
    cites(b["regime"], "regime")
    for i, x in enumerate(b["tilts"]):
        cites(x, f"tilts[{i}]")
    for i, x in enumerate(b["calendar"]):
        cites(x, f"calendar[{i}]")
        if x.get("class") not in CLASSES:
            out.append(f"calendar[{i}]: class {x.get('class')!r} not in the v1 taxonomy")
    for i, x in enumerate(b["events"]):
        cites(x, f"events[{i}]")
        if x.get("class") not in CLASSES:
            out.append(f"events[{i}]: class {x.get('class')!r} not in the v1 taxonomy")
        if x.get("published_at") and _ts(x["published_at"]) > jt:
            out.append(f"events[{i}]: published_at is after judged_at")
    pkt, why = (packet, None) if packet is not None else load_packet(b)
    out += packet_problems(b, pkt, why)
    if fetches is None:
        fetches = []
        for ref in b.get("fetch_paths") or []:
            try:
                fetches.append(_load_json(ref))
            except (OSError, ValueError) as e:
                out.append(f"fetch_paths {ref}: cannot read ({type(e).__name__})")
    ev, fprobs = evidence(pkt, fetches, jt)
    out += fprobs
    for i, t in enumerate(b["trades"]):
        out += trade_problems(t, i, ev, sids)
    for i, f in enumerate(b["informs"]):
        if f.get("leg") not in legs:
            out.append(f"informs[{i}]: leg {f.get('leg')!r} is not in config/strategies.yaml")
        if f.get("action") not in ("avoid_new", "size_down", "note"):
            out.append(f"informs[{i}]: action must be avoid_new | size_down | note")
        if not f.get("until") or _ts(f["until"]) <= jt:
            out.append(f"informs[{i}]: until must be after judged_at")
    out += [f"size-shaped key {k} (desk rule 2: no size, ever)" for k in _size_keys(b)]
    tr = b["training"]
    if tr.get("gate_eligible") is not False:
        out.append("training.gate_eligible must be false (advice-only until its own test passes)")
    if not tr.get("label_clean_from"):
        out.append("training.label_clean_from is required (label hygiene: pre-cutoff judgements are not clean teacher labels)")
    return out


def render(b: dict) -> str:
    L = [f"# Desk macro brief {b['brief_id']}", "", f"judged {b['judged_at']} · info cutoff {b['info_cutoff_at']} · {b['model']}", "",
         f"## Regime: {b['regime'].get('call')} (confidence {b['regime'].get('confidence')})", "", str(b["regime"].get("basis", "")), ""]
    if b["trades"]:
        L += ["## Trades (shadow, advice-only)", "", "| symbol | side | entry | stop | tp (p_hit) | horizon | catalyst |", "|---|---|---|---|---|---|---|"]
        for t in b["trades"]:
            p = t["proposal"]
            L.append(f"| {p['symbol']} | {p['side']} | {p['entry']['level']} | {p['stop']['level']} | {p['tp']['level']} ({p['tp']['p_hit']}) | "
                     f"{p['horizon_bars']}d | {t['catalyst']} |")
        for t in b["trades"]:
            m = t.get("management") or {}
            L += ["", f"### {t['proposal']['symbol']} {t['proposal']['side']}: management handoff (for live-trade-review)", "",
                  f"- design: {m.get('design')}", f"- expected path: {m.get('expected_path')}"]
            for k in ("watch_for", "tighten_if", "exit_early_if"):
                for it in m.get(k) or []:
                    ck = it.get("check")
                    L.append(f"- {k}: {it.get('signal')}" + (f" [check {ck['kind']} {ck['level']}]" if ck else ""))
            L += [f"- catalyst timing: {x}" for x in m.get("catalyst_timing") or []]
            L += [f"- do not: {x}" for x in m.get("do_not") or []]
            L.append(f"- thesis invalidated by: {m.get('thesis_invalidated_by')}")
    else:
        L += ["## Trades: none", "", str(b.get("no_trade_reason", ""))]
    for name in ("informs", "calendar", "events", "tilts"):
        if b[name]:
            L += ["", f"## {name.capitalize()}", ""] + [f"- {json.dumps(x, sort_keys=True)}" for x in b[name]]
    L += ["", f"Sources: {len(b['sources'])} (see the JSON record; every judgement cites them)."]
    return "\n".join(L) + "\n"


def write(b: dict, out_dir: Path = OUT_DIR, universe: set | None = None, legs: set | None = None,
          packet: dict | None = None, fetches: list[dict] | None = None) -> Path:
    probs = problems(b, universe, legs, packet, fetches)
    if probs:
        raise ValueError("refused:\n  " + "\n  ".join(probs))
    day = _ts(b["judged_at"]).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{day}.json"
    if p.exists():
        raise FileExistsError(f"{p} exists: a brief is written once; a correction is a new brief with `supersedes`")
    body = json.dumps(b, indent=1, sort_keys=False) + "\n"
    p.write_text(body)
    (out_dir / f"{day}.md").write_text(render(b))
    return p


# ---- self-test ------------------------------------------------------------------------------------------------------------
GOOD = {
    "schema": SCHEMA, "brief_id": "DMB-20261126T1307Z", "judged_at": "2026-11-26T13:07:00Z", "info_cutoff_at": "2026-11-26T13:00:00Z",
    "model": "opus-tier", "skill_sha": "x", "packet_sha": None, "packet_path": "PKT",
    "sources": [{"source_id": "S1", "kind": "econ_calendar", "ref": "comms/macro/econ_calendar_upcoming.json",
                 "retrieved_at": "2026-11-26T13:01:00Z", "content_sha256": hashlib.sha256(b"x").hexdigest(), "influence": "decisive"}],
    "regime": {"call": "neutral", "axes": {"growth": 0, "inflation": 0, "liquidity": 0, "vol": 0}, "confidence": 0.5, "basis": "S1 shows a quiet week"},
    "tilts": [{"asset": "TLT", "tilt": 1, "horizon_days": 20, "confidence": 0.4, "basis": "S1"}],
    "calendar": [{"event_key": "US_CPI_2026-12-10", "at": "2026-12-10T13:30:00Z", "class": "scheduled.macro.cpi", "source_ids": ["S1"]}],
    "events": [],
    "trades": [{"proposal": {"symbol": "TLT", "venue_class": "etf", "side": "long", "timeframe": "1d", "horizon_bars": 10,
                             "entry": {"type": "limit", "level": 90.0, "good_till_bars": 2}, "stop": {"level": 88.0, "basis": "swing_low"},
                             "tp": {"level": 94.0, "basis": "prior_range_high", "p_hit": 0.35}, "expected_r_net": 0.1, "thesis": "x",
                             "novelty": "unverifiable", "onboarding": "onboarded"},
                "judge_prior": 0.35, "catalyst": "US_CPI_2026-12-10", "invalidation": "10y yield closes above 4.8%",
                "management": {"design": "buy a pullback into a rising SMA20; TP at the prior range high", "expected_path": "toward TP in 3-6 sessions",
                               "watch_for": [{"signal": "CPI 12-10 13:30Z: core > 0.3% m/m weakens the thesis", "source_ids": ["S1"]}],
                               "catalyst_timing": ["2026-12-10T13:30:00Z CPI"], "tighten_if": [],
                               "exit_early_if": [{"signal": "daily close below 88.5", "check": {"kind": "close_below", "level": 88.5}}],
                               "do_not": ["do not trail inside 1 ATR before CPI"], "thesis_invalidated_by": "10y yield closes above 4.8%"}}],
    "informs": [], "no_trade_reason": None,
    "training": {"train_eligible": True, "gate_eligible": False, "label_clean_from": "2026-06-01"},
}


def _pkt(prices_state: str = "measured", built_at: str = "2026-11-26T13:00:00Z") -> dict:
    syms = {} if prices_state == "could_not_look" else {"TLT": {"read_state": "measured"}, "NVDA": {"read_state": "measured"}}
    trad = {"TLT": {"rostered_on": ["alpaca"], "venue": None},
            "NVDA": {"rostered_on": [], "venue": {"read_state": "measured", "exchange": "alpaca", "tradable": False}}}
    p = {"schema": "desk_macro_packet/1", "packet_id": "DMP-x", "built_at": built_at,
         "parts": {"prices": {"read_state": prices_state, "symbols": syms}, "tradability": {"symbols": trad}}}
    p["packet_sha"] = hashlib.sha256(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()
    return p


def self_test() -> int:
    uni, legs = {"TLT", "SPY", "BTCUSDT"}, {"claude_desk", "trend_donchian"}
    ok = True
    PKT = _pkt()
    GOOD["packet_sha"] = PKT["packet_sha"]

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + name)

    def bad(fn, pkt=None):
        b = copy.deepcopy(GOOD)
        fn(b)
        return problems(b, uni, legs, pkt or PKT)
    check("a good brief passes", problems(GOOD, uni, legs, PKT) == [])
    check("retrieved_at after judged_at is refused", bad(lambda b: b["sources"][0].update(retrieved_at="2026-11-26T13:30:00Z")))
    check("a model id instead of a tier is refused", bad(lambda b: b.update(model="claude-x-1")))
    check("wrong geometry is refused", bad(lambda b: b["trades"][0]["proposal"]["tp"].update(level=87.0)))
    check("tp beyond the venue cap is refused", bad(lambda b: b["trades"][0]["proposal"]["tp"].update(level=99.5)))
    check("p_hit below the reach floor is refused", bad(lambda b: b["trades"][0]["proposal"]["tp"].update(p_hit=0.05)))
    check("an untradable symbol is refused (venue says not tradable)", bad(lambda b: b["trades"][0]["proposal"].update(symbol="NVDA")))
    check("a symbol with no bars in the packet or a fetch file is refused", bad(lambda b: b["trades"][0]["proposal"].update(symbol="AAPL")))
    check("the wrong venue_class for a rostered symbol is refused", bad(lambda b: b["trades"][0]["proposal"].update(venue_class="perp")))
    fb = {"schema": "desk_macro_fetch/1", "fetch_id": "DMF-x", "retrieved_at": "2026-11-26T13:05:00Z", "packet_sha": PKT["packet_sha"],
          "prices": {"symbols": {"AAPL": {"read_state": "measured"}}},
          "tradability": {"symbols": {"AAPL": {"rostered_on": [], "venue": {"read_state": "measured", "exchange": "alpaca", "tradable": True}}}}}
    fb["fetch_sha"] = hashlib.sha256(json.dumps(fb, sort_keys=True, default=str).encode()).hexdigest()

    def with_fetch(fn, f):
        b = copy.deepcopy(GOOD)
        fn(b)
        return problems(b, uni, legs, PKT, [f])
    check("ANY symbol passes once fetched in-run with bars + a venue 'tradable'",
          with_fetch(lambda b: b["trades"][0]["proposal"].update(symbol="AAPL"), fb) == [])
    late_f = dict(fb, retrieved_at="2026-11-26T13:30:00Z")
    late_f["fetch_sha"] = hashlib.sha256(json.dumps({k: v for k, v in late_f.items() if k != "fetch_sha"}, sort_keys=True, default=str).encode()).hexdigest()
    check("a fetch retrieved after judged_at is refused", with_fetch(lambda b: b["trades"][0]["proposal"].update(symbol="AAPL"), late_f))
    check("a tampered fetch file is refused", with_fetch(lambda b: b["trades"][0]["proposal"].update(symbol="AAPL"), dict(fb, retrieved_at="2026-11-26T13:01:00Z")))
    check("a trade without a management block is refused", bad(lambda b: b["trades"][0].pop("management")))
    check("management without an exit_early_if item is refused", bad(lambda b: b["trades"][0]["management"].update(exit_early_if=[])))
    check("a malformed machine check is refused", bad(lambda b: b["trades"][0]["management"]["exit_early_if"][0].update(check={"kind": "vibes", "level": 1})))
    check("a management item citing an unknown source is refused", bad(lambda b: b["trades"][0]["management"]["watch_for"][0].update(source_ids=["S9"])))
    check("a size key is refused", bad(lambda b: b["trades"][0]["proposal"].update(qty=10)))
    check("an uncited judgement is refused", bad(lambda b: b["tilts"][0].update(basis="no citation")))
    check("an unknown taxonomy class is refused", bad(lambda b: b["calendar"][0].update(**{"class": "scheduled.macro.vibes"})))
    check("no trades is refused when the packet read prices, even WITH a reason",
          bad(lambda b: b.update(trades=[], no_trade_reason="quiet day")))
    dead = _pkt("could_not_look")
    check("no trades + reason passes only when packet prices are could_not_look",
          bad(lambda b: b.update(trades=[], no_trade_reason="price API down", packet_sha=dead["packet_sha"]), dead) == [])
    check("no trades without a reason is refused even then",
          bad(lambda b: b.update(trades=[], packet_sha=dead["packet_sha"]), dead))
    check("a packet_sha that does not match the packet is refused", bad(lambda b: b.update(packet_sha="0" * 64)))
    tampered = dict(PKT, parts={"prices": {"read_state": "could_not_look"}})
    check("a packet edited after build is refused", bad(lambda b: None, tampered))
    late = _pkt(built_at="2026-11-26T14:00:00Z")
    check("a packet built after judged_at is refused", bad(lambda b: b.update(packet_sha=late["packet_sha"]), late))
    check("a brief naming no packet is refused", problems(dict(GOOD, packet_path=None), uni, legs))
    check("an unknown leg in informs is refused", bad(lambda b: b["informs"].append({"leg": "nope", "action": "note", "until": "2026-11-27T00:00:00Z"})))
    check("gate_eligible true is refused", bad(lambda b: b["training"].update(gate_eligible=True)))
    with tempfile.TemporaryDirectory() as td:
        p = write(copy.deepcopy(GOOD), Path(td), uni, legs, PKT)
        check("write creates json + md", p.exists() and (Path(td) / "2026-11-26.md").exists())
        try:
            write(copy.deepcopy(GOOD), Path(td), uni, legs, PKT)
            check("write-once: a second write is refused", False)
        except FileExistsError:
            check("write-once: a second write is refused", True)
    real_legs = desk_universe()[1]
    check("the real roster loads (informs[] legs)", "claude_desk" in real_legs)
    print("SELF-TEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", choices=("validate", "write"))
    ap.add_argument("brief", nargs="?")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.cmd and a.brief):
        ap.error("validate|write BRIEF.json, or --self-test")
    b = json.loads(Path(a.brief).read_text())
    if a.cmd == "validate":
        probs = problems(b)
        print("OK" if not probs else "REFUSED:\n  " + "\n  ".join(probs))
        return 0 if not probs else 1
    try:
        print(write(b, Path(a.out_dir)))
    except (ValueError, FileExistsError) as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
