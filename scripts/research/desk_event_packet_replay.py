#!/usr/bin/env python3
# wiring: manual-only - run by lane DESK-18D-JUDGE-2 (event-driven packet arm; `packets`, `intake`, `score`) and by research/queue unit RQ-20261112-e4a7-01; no schedule consumes it.
"""DESK-18H -- the desk PACKET arm, woken by an event: does Claude, judging a masked packet opened ONLY when an
open-interest shock (E4) fires, beat a same-geometry random entry by S3 >= +0.25 R on DEV?

Operator 2026-11-12 decisions page w6, verbatim: "Event-driven entries; lane keeps its defaults on the 4 small questions".
The lever is the one DESK-18G (docs/research/desk-18g-event-entries-2026-10-30.md) named as its open option (b): E4 combined
with the desk's own judgement. DESK-18G scored the MECHANICAL E4 rule (DEV S3 +0.157 R, 97.5% CI [+0.044, +0.276]; held-out
+0.184 R); this file scores the JUDGED packet arm on the same events. Design: docs/design/desk-entry-review-redesign-2026-11-11.md
§ 3 (the entry packet carries the trigger and each structure's base rate from replay of the same trigger), with the lane's
defaults on its § 6 questions: (1) graded by OUTCOME; (2) the periodic scan is untouched (no live change here); (3) the six
crypto USDT perps only; (4) the other four detectors are not retired and not scored here.

Reuses, never rewrites, the certified instruments:
  desk_event_entry_replay.detect      the frozen E4 detector (events, known_at, decision cutoff, rule side)
  desk_gen_replay_driver              Series, build_masked_packet + leak_scan (the live builder and mask), read_proposals (the
                                      proposal guard), simulate / geometry_of / transplant / random_baseline / vol_matched_pool,
                                      the cost stack, JUDGE_PROTOCOL
Tier 1 research tooling: reads public Binance Vision files and committed evidence, writes only under --out.

THE ARM (registered in research/queue/RQ-20261112-e4a7-01.yaml before any packet is judged)
  population   every E4 event whose decision cutoff lies in DEV (2025-11-01 .. 2026-09-15) and has its cutoff bar, in a
               seeded random ORDER (seed 20261112); judged in schedule-prefix batches.
  packet       the live builder's masked scan packet at the event's decision cutoff, universe = the EVENT symbol only (one
               alias), plus two blocks the 1h price packet cannot see:
                 event            {type open_interest_shock, oi_change_1h_pct, oi_change_z, known_minutes_before_cutoff,
                                  last_closed_bar_return_pct / _atr, continuation_side}
                 trigger_history  (in JUDGE-PROTOCOL.md, identical for every packet) the same trigger's net-of-cost outcomes per structure (continuation / fade x six reference
                                  brackets), pooled over the six symbols, from the HOLDOUT window 2024-11-01 .. 2025-10-25,
                                  which ENDS BEFORE DEV STARTS (point-in-time valid at every DEV cutoff). No DEV outcome is in it.
  proposal     at most one propose_entry (the event alias) or no_trade; the driver's guard refuses a bad row (scored no_trade).
  replay       the driver's simulate on the real candles, full cost stack.
  baseline     per filled proposal, its OWN geometry transplanted to 200 random cutoffs of the same symbol in DEV, same
               ATR%-decile, more than 24 bars from any E4 event of that symbol (DESK-18G's B3 pool), driver random_baseline.
  S3           weekly-cluster mean of (proposal net R - its baseline mean), 10,000 draws, seed 20261112, 95% CI (one arm).
  clears       n_filled >= 30 AND S3 >= +0.25 R AND the 95% CI lower bound > 0 AND the planted controls hold.
Reported, not decisive: S1 (mean net R), the mechanical E4 rule's S3 on the SAME judged events, the judge-minus-rule paired
difference per judged event (a pass or refusal = 0 R, the rule's refused slot = 0 R), take rate, side mix, by symbol.

CONTROLS (RULE ONE: the probe must see a positive) a planted ORACLE proposal (the realised 24-bar forward sign, the rule's
bracket) on every judged event, through the same scorer path, must clear; the ANTI-ORACLE must read S3 < 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "ops", REPO / "scripts" / "ci", REPO / "scripts" / "research", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_desk_records as cdr
import desk_event_calendar_study as ecs
import desk_event_entry_replay as dee
import desk_gen_replay_driver as gr

UNIT_ID = "RQ-20261112-e4a7-01"
RULE_ID = "RULE-RQ20261112-E4A7-01-DESK-EVENT-PACKET-ARM"

# ----------------------------------------------------------------------------- registered numbers (not tunable)
SYMS = gr.REGISTERED_SYMBOLS
DEV = dee.DEV
HOLDOUT = dee.HOLDOUT
SEED = 20261112
S3_BAR = 0.25
N_MIN = 30
ALPHA = 0.05                     # one decisive arm
B_DRAWS = 200
BOOT = 10_000
EXCL_BARS = dee.EXCL_BARS        # 24
BATCH = 100                      # packets per batch (the stopping grain)
MAX_PER_PACKET = 1
HISTORY_GEOMS = gr.REFERENCE_GEOMETRIES   # (name, sl_atr, tp_R, horizon)
HISTORY_FILE = REPO / "comms" / "research" / "desk_event_packet" / "trigger_history_holdout.json"


# ----------------------------------------------------------------------------- events
_OI_CACHE: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}


def _oi_rows(root: Path, sym: str) -> tuple[np.ndarray, np.ndarray]:
    k = (str(root), sym)
    if k not in _OI_CACHE:
        rows = sorted((dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp(), float(r[2]))
                      for r in ecs._dir_rows(root / "oi" / sym))
        _OI_CACHE[k] = (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]))
    return _OI_CACHE[k]


def oi_stats(root: Path, ev: dict) -> tuple[float | None, float | None]:
    """(1h OI change, its z vs the previous 2016 5-minute-grid 1h changes) at the event's detection row (known - 300 s).
    The same arithmetic as dee.detect, reading only rows at or before that row."""
    t_ev = ev["known"] - 300
    t_all, oi_all = _oi_rows(root, ev["sym"])
    n = int(np.searchsorted(t_all, t_ev, side="right"))
    if n < dee.OI_W + dee.OI_LAG_BARS + 1 or t_all[n - 1] != t_ev:
        return None, None
    oi = oi_all[:n]
    lag = dee.OI_LAG_BARS
    ch = np.zeros(len(oi))
    good = (oi[lag:] > 0) & (oi[:-lag] > 0)
    ch[lag:][good] = oi[lag:][good] / oi[:-lag][good] - 1
    i = len(oi) - 1
    w = ch[i - dee.OI_W:i]
    sd = float(w.std())
    return float(ch[i]), (float((ch[i] - w.mean()) / sd) if sd > 0 else None)


def dev_events(root: Path, mkt: dict[str, gr.Series], window=DEV) -> list[dict]:
    """E4 events with a cutoff bar inside the window, in the registered seeded order (index = schedule position)."""
    lo, hi = gr._epoch(window[0]), gr._epoch(window[1])
    evs = []
    for e in dee.detect(root, mkt)["E4"]:
        ser = mkt[e["sym"]]
        if not (lo <= e["cutoff"] < hi):
            continue
        i = ser.last_closed(e["cutoff"])
        if i < 0 or ser.t[i] + gr.SEC != e["cutoff"]:
            continue
        evs.append(e)
    evs.sort(key=lambda e: (e["cutoff"], e["sym"]))
    order = np.random.default_rng(SEED).permutation(len(evs))
    return [dict(evs[j], index=k) for k, j in enumerate(order)]


# ----------------------------------------------------------------------------- trigger history (holdout window only)
def trigger_history(root: Path) -> dict[str, Any]:
    """Per structure (rule side continuation / fade x reference bracket): the E4 trigger's outcomes on the HOLDOUT window,
    pooled over the six symbols, market entry at the next open, full cost stack. A refused slot is excluded and counted."""
    mkt, missing = gr.load_market(root / "candles", list(SYMS))
    if missing:
        raise SystemExit(f"candles missing for {missing}")
    lo, hi = gr._epoch(HOLDOUT[0]), gr._epoch(HOLDOUT[1])
    evs = [e for e in dee.detect(root, mkt)["E4"] if lo <= e["cutoff"] < hi]
    rows = []
    for name, sl, tp_r, hz in HISTORY_GEOMS:
        for rule in ("continuation", "fade"):
            nets, hit, refused = [], 0, 0
            for e in evs:
                ser = mkt[e["sym"]]
                i = ser.last_closed(e["cutoff"])
                if i < 0 or ser.t[i] + gr.SEC != e["cutoff"]:
                    continue
                side = float(e["side"]) * (1.0 if rule == "continuation" else -1.0)
                t = gr.transplant(ser, i, {"side": side, "etype": "market", "offset_atr": 0.0, "sl_atr": sl,
                                           "tp_atr": sl * tp_r, "good_till": 1, "horizon": hz})
                if t is None or t.state == "unresolved":
                    continue
                if t.state != "filled":
                    refused += 1
                    continue
                nets.append(t.net_r)
                hit += t.reason in ("tp", "gap_tp")
            rows.append({"structure": f"{rule}_{name}", "side_rule": rule,
                         "side_rule_means": "the sign of the last CLOSED 1h bar's return at the cutoff" if rule == "continuation"
                         else "against the sign of the last CLOSED 1h bar's return",
                         "stop_atr": sl, "target_atr": round(sl * tp_r, 4), "horizon_bars": hz, "n": len(nets),
                         "mean_net_r": round(float(np.mean(nets)), 4) if nets else None,
                         "p_target_first": round(hit / len(nets), 4) if nets else None, "refused": refused})
    return {"window": [w.isoformat() for w in HOLDOUT], "events": len(evs),
            "note": "E4 trigger outcomes on a window that ends before DEV starts; pooled over six symbols; net of fee, slippage, funding",
            "rows": rows}


# ----------------------------------------------------------------------------- packets
EVENT_ADDENDUM = """
## DESK-18H addendum: this packet was OPENED BY AN EVENT

This packet was opened because an open-interest shock fired on the one alias it shows: the 1h change in that asset's
open interest is at least 3 standard deviations above its previous 7 days of 1h changes. The `event` block gives the
change, its z-score, and the last closed 1h bar's return. `trigger_history` (below) gives what entering on this same trigger did on an EARLIER period, per
structure (side rule x stop / target in ATR x horizon), net of all costs: `continuation` means the side of the last
closed 1h bar (given as `event.continuation_side`), `fade` the opposite. ATR is the packet's own ATR14. The
table is at the end of this protocol. Use it as the base rate; decide whether THIS instance,
given the packet, is worth a trade, and which structure. `no_trade` remains a real answer. At most one proposal.
"""


def history_table(hist: dict) -> str:
    """The trigger_history as a table in the protocol (identical for every packet, so it is stated once)."""
    lines = ["", f"### trigger_history ({hist['events']} earlier events of this trigger, pooled over six assets; {hist['note']})", "",
             "| structure | side | stop (ATR) | target (ATR) | horizon (1h bars) | n | mean net R | P(target first) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in hist["rows"]:
        lines.append(f"| {r['structure']} | {r['side_rule']} | {r['stop_atr']} | {r['target_atr']} | {r['horizon_bars']} | {r['n']} | "
                     f"{r['mean_net_r']:+.3f} | {r['p_target_first']:.3f} |")
    lines += ["", "`continuation` = the packet's `event.continuation_side` (the side of the last closed 1h bar); `fade` = the other side.", ""]
    return "\n".join(lines)


def build_event_packet(mkt: dict[str, gr.Series], classes: dict[str, list[str]], ev: dict, root: Path) -> tuple[dict, dict]:
    s = ev["sym"]
    m, key = gr.build_masked_packet({s: mkt[s]}, classes, ev["cutoff"], ev["index"], SEED)
    ch, z = oi_stats(root, ev)
    alias = next(iter(key["alias"]))
    ser = mkt[s]
    j = ser.last_closed(ev["cutoff"])
    bar_ret = float(ser.c[j] / ser.c[j - 1] - 1)          # the bar that closes AT the cutoff (dee.detect's side source)
    m["event"] = {"type": "open_interest_shock", "alias": alias,
                  "oi_change_1h_pct": None if ch is None else round(100 * ch, 3),
                  "oi_change_z": None if z is None else round(z, 2),
                  "known_minutes_before_cutoff": int((ev["cutoff"] - ev["known"]) // 60),
                  "last_closed_bar_return_pct": round(100 * bar_ret, 3),
                  "last_closed_bar_return_atr": round((ser.c[j] - ser.c[j - 1]) / ser.atr[j], 3) if ser.atr[j] > 0 else None,
                  "continuation_side": "long" if ev["side"] > 0 else "short",
                  "read_state": "read" if z is not None else "could_not_look"}
    key.update(event_side=ev["side"], event_known=ev["known"], arm="E4_packet")
    return m, key


def _market(a) -> tuple[dict[str, gr.Series], dict[str, list[str]]]:
    if getattr(a, "fetch", False):
        dee.fetch(Path(a.root), "dev")          # the runner route: public Binance Vision files, skipped when cached
    mkt, missing = gr.load_market(Path(a.root) / "candles", list(SYMS))
    if missing:
        raise SystemExit(f"candles missing for {missing}: refusing a partial universe")
    uni, _ = gr.parse_universe()
    return mkt, {u["symbol"]: u["classes"] for u in uni}


def _hist(a) -> dict:
    p = Path(getattr(a, "history", None) or HISTORY_FILE)
    return json.loads(p.read_text())


def cmd_history(a) -> int:
    h = trigger_history(Path(a.root))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(h, indent=1) + "\n")
    print(json.dumps({"events": h["events"], "rows": len(h["rows"])}))
    return 0


def cmd_packets(a) -> int:
    mkt, classes = _market(a)
    root, hist = Path(a.root), _hist(a)
    evs = dev_events(root, mkt)
    sel = evs[a.offset: a.offset + a.n]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys, leaked, sizes = [], 0, []
    with (out / "packets.jsonl").open("w") as fh:
        for ev in sel:
            m, key = build_event_packet(mkt, classes, ev, root)
            txt = json.dumps(m, sort_keys=True)
            if gr.leak_scan(txt, key, list(SYMS)):
                leaked += 1
                continue
            fh.write(json.dumps({"packet_id": m["meta"]["packet_id"], "packet": m}, sort_keys=True) + "\n")
            key["packet_sha"] = cdr.packet_sha(m)
            keys.append(key)
            sizes.append(len(txt))
    (out / "mask-key.json").write_text(json.dumps({"seed": SEED, "unit": UNIT_ID, "schedule_len": len(evs),
                                                   "note": "NEVER given to the judging session", "keys": keys}, indent=1) + "\n")
    proto = gr.JUDGE_PROTOCOL % {"cap": MAX_PER_PACKET, "sent": cdr.SENTINEL_R_FLOOR, "cap_pct": cdr.TP_VENUE_CAP_PCT * 100,
                                 "reach": cdr.REACH_FLOOR, "minrisk": gr.MIN_RISK_ATR}
    (out / "JUDGE-PROTOCOL.md").write_text(proto + EVENT_ADDENDUM + history_table(hist))
    print(json.dumps({"packets": len(keys), "withheld_for_leak": leaked, "schedule_len": len(evs),
                      "median_packet_chars": int(np.median(sizes)) if sizes else None}))
    return 0


def _load(a, mkt, classes) -> tuple[dict[str, dict], dict[str, dict], dict[str, list[dict]], dict[str, Any]]:
    """keys, packets (re-derived from the candles and sha-verified), proposals by packet, intake accounting."""
    keyf = json.loads(Path(a.mask_key).read_text())
    keys = {k["packet_id"]: k for k in keyf["keys"]}
    root = Path(a.root)
    evs = {e["index"]: e for e in dev_events(root, mkt)}
    want = {json.loads(ln)["packet_id"] for ln in Path(a.proposals).read_text().splitlines() if ln.strip()}
    packets, drift = {}, []
    for pid in sorted(want):
        if pid not in keys:
            raise SystemExit(f"proposal packet_id {pid!r} is not in the mask key")
        k = keys[pid]
        m, _ = build_event_packet(mkt, classes, evs[k["index"]], root)
        if m["meta"]["packet_id"] != pid or cdr.packet_sha(m) != k["packet_sha"]:
            drift.append(pid)
        packets[pid] = m
    if drift:
        raise SystemExit(f"{len(drift)} re-derived packet(s) differ from what the judge saw: {drift[:3]}")
    by, intake = gr.read_proposals(Path(a.proposals), packets)
    return keys, packets, by, intake


def prefix_design(keys: dict[str, dict], by: dict[str, list[dict]], schedule_len: int) -> dict[str, Any]:
    """Judged packets must be exactly the KEYED schedule indices below a batch boundary (a packet withheld for a mask leak has
    no key and was never offered, so its hole is not a skip)."""
    idx = sorted(int(keys[p]["index"]) for p in by)
    keyed = sorted(int(k["index"]) for k in keys.values())
    prefix_ok = bool(idx) and idx == [k for k in keyed if k <= idx[-1]]
    end = min(schedule_len, math.ceil((idx[-1] + 1) / BATCH) * BATCH) if idx else 0
    whole_batches = bool(idx) and idx == [k for k in keyed if k < end]
    return {"packets_judged": len(idx), "is_schedule_prefix": prefix_ok, "whole_batches": whole_batches, "batch": BATCH,
            "schedule_len": schedule_len, "last_index": idx[-1] if idx else None, "batch_end": end}


def cmd_intake(a) -> int:
    mkt, classes = _market(a)
    keys, _packets, by, intake = _load(a, mkt, classes)
    sl = json.loads(Path(a.mask_key).read_text()).get("schedule_len")
    d = prefix_design(keys, by, sl)
    print(json.dumps({**d, "valid_proposals": sum(len(v) for v in by.values()), "intake": intake}))
    return 0


# ----------------------------------------------------------------------------- scoring
def _excl_mask(ser: gr.Series, idxs: list[int]) -> np.ndarray:
    near = np.zeros(len(ser.t), bool)
    for j in idxs:
        near[max(0, j - EXCL_BARS): j + EXCL_BARS + 1] = True
    return near


def score_rows(mkt, items: list[tuple[dict, dict]], ev_idx: dict[str, list[int]], seed: int, draws: int = B_DRAWS) -> list[dict]:
    """items = [(key, proposal-dict in REAL prices with side +/-1)], scored against the B3 pool with the proposal's own geometry."""
    rng = np.random.default_rng(seed)
    pools: dict[str, np.ndarray] = {}
    near = {s: _excl_mask(mkt[s], ev_idx.get(s, [])) for s in mkt}
    out = []
    for key, p in items:
        s = key["symbol"]
        ser = mkt[s]
        i = ser.last_closed(key["cutoff_epoch"])
        t = gr.simulate(ser, i, p["side"], p["etype"], p["level"], p["stop"], p["tp"], p["good_till"], p["horizon"])
        if t.state != "filled":
            out.append({"packet_id": key["packet_id"], "state": t.state})
            continue
        g = gr.geometry_of(ser, i, p["side"], p["etype"], p["level"], p["stop"], p["tp"], p["good_till"], p["horizon"])
        if s not in pools:
            pools[s] = gr.eligible_cutoffs(ser, *DEV)
        pool = gr.vol_matched_pool(ser, pools[s], i, window=DEV)
        pool = pool[~near[s][pool]]
        b = gr.random_baseline(ser, g, pool, rng, draws) if g is not None else {"mean": None}
        out.append({"packet_id": key["packet_id"], "state": "filled", "symbol": s, "week": gr.iso_week(key["cutoff_epoch"]),
                    "side": "long" if p["side"] > 0 else "short", "net_r": t.net_r, "gross_r": t.gross_r, "exit": t.reason,
                    "b_mean": b["mean"], "d": None if b["mean"] is None else t.net_r - b["mean"]})
    return out


def _stat(rows: list[dict], field: str = "d", seed: int = SEED) -> dict[str, Any]:
    r = [x for x in rows if x.get(field) is not None]
    return dee.cluster_mean([x[field] for x in r], [x["week"] for x in r], ALPHA, seed=seed, draws=BOOT)


def _real(pr: dict, key: dict) -> dict:
    sc = float(key["price_scale"][pr["symbol"]])
    return {"side": 1.0 if pr["side"] == "long" else -1.0, "etype": pr["entry"]["type"], "level": pr["entry"]["level"] / sc,
            "stop": pr["stop"]["level"] / sc, "tp": pr["tp"]["level"] / sc, "good_till": pr["entry"]["good_till_bars"],
            "horizon": pr["horizon_bars"]}


def _rule_prop(ser: gr.Series, i: int, side: float) -> dict:
    a, c = float(ser.atr[i]), float(ser.c[i])
    return {"side": side, "etype": "market", "level": c, "stop": c - side * dee.SL_ATR * a, "tp": c + side * dee.TP_ATR * a,
            "good_till": 1, "horizon": dee.HORIZON}


def cmd_score(a) -> int:
    mkt, classes = _market(a)
    keys, _packets, by, intake = _load(a, mkt, classes)
    keyf = json.loads(Path(a.mask_key).read_text())
    design = prefix_design(keys, by, keyf.get("schedule_len"))
    root = Path(a.root)
    evs = dev_events(root, mkt)
    ev_idx: dict[str, list[int]] = {s: [] for s in SYMS}
    for e in evs:
        ev_idx[e["sym"]].append(mkt[e["sym"]].last_closed(e["cutoff"]))
    judged = [keys[p] for p in by]
    for k in judged:
        k["symbol"] = k["alias"][next(iter(k["alias"]))]
    items = [(keys[p], _real(r["proposal"], keys[p])) for p, rows in by.items() for r in rows]
    desk = score_rows(mkt, items, ev_idx, SEED + 7)
    filled = [r for r in desk if r["state"] == "filled"]
    st = _stat(filled)
    # the mechanical E4 rule on the SAME judged events, and the planted controls, through the same scorer path
    rule_items, orc_items, anti_items = [], [], []
    for k in judged:
        ser = mkt[k["symbol"]]
        i = ser.last_closed(k["cutoff_epoch"])
        rule_items.append((k, _rule_prop(ser, i, float(k["event_side"]))))
        f = dee._fwd_sign(ser, i)
        orc_items.append((k, _rule_prop(ser, i, f)))
        anti_items.append((k, _rule_prop(ser, i, -f)))
    rule = score_rows(mkt, rule_items, ev_idx, SEED + 13)
    orc = [r for r in score_rows(mkt, orc_items, ev_idx, SEED + 17, draws=40) if r["state"] == "filled"]
    anti = [r for r in score_rows(mkt, anti_items, ev_idx, SEED + 19, draws=40) if r["state"] == "filled"]
    rule_f = [r for r in rule if r["state"] == "filled"]
    # judge minus rule per judged event: a pass / refusal / unfilled = 0 R for the desk; the rule's non-fill = 0 R
    dnet = {r["packet_id"]: r["net_r"] for r in filled}
    rnet = {r["packet_id"]: r["net_r"] for r in rule_f}
    jvr = [{"week": gr.iso_week(k["cutoff_epoch"]), "x": dnet.get(k["packet_id"], 0.0) - rnet.get(k["packet_id"], 0.0)} for k in judged]
    controls = {"oracle": _stat(orc), "anti_oracle": _stat(anti)}
    ctl_ok = bool(controls["oracle"]["n"] and controls["oracle"]["mean"] >= S3_BAR and controls["oracle"]["ci"][0] > 0
                  and controls["anti_oracle"]["mean"] is not None and controls["anti_oracle"]["mean"] < 0)
    n = st["n"]
    clears = bool(n >= N_MIN and st["mean"] is not None and st["mean"] >= S3_BAR and st["ci"][0] > 0)
    if not (design["is_schedule_prefix"] and design["whole_batches"]) or not ctl_ok:
        verdict = "INDETERMINATE_INSTRUMENT"
    elif clears:
        verdict = "S3_CLEARED"
    elif n < N_MIN:
        verdict = "INDETERMINATE"
    else:
        verdict = "S3_NOT_CLEARED"
    sd = float(np.std([r["d"] for r in filled if r["d"] is not None], ddof=1)) if n > 1 else None
    res = {
        "unit": UNIT_ID, "rule": RULE_ID, "verdict": verdict, "window": [w.isoformat() for w in DEV],
        "population": f"E4-triggered masked packets: {len(judged)} judged of a {keyf.get('schedule_len')}-event DEV schedule; "
                      f"{n} filled proposals; six crypto USDT perps; Binance Vision 1h",
        "design": design, "intake": intake,
        "take_rate": round(sum(len(v) for v in by.values()) / len(judged), 4) if judged else None,
        "states": {s: sum(1 for r in desk if r["state"] == s) for s in sorted({r["state"] for r in desk})},
        "S3": st, "S1_net_r": _stat(filled, "net_r"), "sd_d": sd,
        "mde_iid_r": None if not sd or not n else round(2.8 * sd / math.sqrt(n), 4),
        "by_side": {s: sum(1 for r in filled if r["side"] == s) for s in ("long", "short")},
        "by_symbol": {s: {"n": sum(1 for r in filled if r["symbol"] == s),
                          "S3": float(np.mean([r["d"] for r in filled if r["symbol"] == s and r["d"] is not None]))
                          if any(r["symbol"] == s and r["d"] is not None for r in filled) else None} for s in SYMS},
        "rule_same_events": {"S3": _stat(rule_f), "S1_net_r": _stat(rule_f, "net_r")},
        "judge_minus_rule_per_event": dee.cluster_mean([x["x"] for x in jvr], [x["week"] for x in jvr], ALPHA, seed=SEED, draws=BOOT),
        "controls": controls, "controls_ok": ctl_ok,
        "bar": {"n_min": N_MIN, "S3": S3_BAR, "ci": "95% weekly-cluster, lower bound > 0"},
        "read_state": "measured",
        "limits": ["Binance candles stand in for Bybit", "entry at least one 1h bar after the event is known",
                   "judge model's knowledge cutoff postdates DEV: masked replay only, a clear needs the held-out run",
                   "trigger_history is from the holdout window, so a held-out run of this arm needs a different history window"],
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    (out / "records.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in desk))
    print(json.dumps({k: res[k] for k in ("verdict", "population", "take_rate")}, default=str))
    print(json.dumps({"S3": st, "rule_same_events_S3": res["rule_same_events"]["S3"], "jvr": res["judge_minus_rule_per_event"],
                      "controls_ok": ctl_ok}, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, fn in (("history", cmd_history), ("packets", cmd_packets), ("intake", cmd_intake), ("score", cmd_score)):
        s = sub.add_parser(name)
        s.add_argument("--root", required=True, help="cache dir with candles/, oi/, fr/ (desk_event_entry_replay.py fetch); never inside --out")
        s.add_argument("--fetch", action="store_true", help="fetch the DEV event files and candles into --root first")
        s.add_argument("--out", required=True)
        s.set_defaults(fn=fn)
        if name != "history":
            s.add_argument("--history", help=f"default {HISTORY_FILE.relative_to(REPO)}")
        if name == "packets":
            s.add_argument("--n", type=int, required=True)
            s.add_argument("--offset", type=int, default=0)
        if name in ("intake", "score"):
            s.add_argument("--proposals", required=True)
            s.add_argument("--mask-key", required=True)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
