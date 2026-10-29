#!/usr/bin/env python3
# wiring: research/queue/RQ-20261029-1f39-02 via .github/workflows/research-script-run.yml; tests/test_am_class_regrade.py
"""Per-class re-grade of the DESK-LIFECYCLE-S0 corpus (#20967) under RULE-AM-RISK-ADJUSTED-V1.

WHY (operator decision 2026-10-29 ~12:40Z, relayed by Manager Session 2026-10-29c, verbatim on row
AM-RISK-ADJUSTED-RULE): *"Re-grade, then auto-unlock (Recommended)"* and *"1, but we need to make sure we're also
measuring R giveback and overall PNL"*. The corpus was scored as WHOLE-TRADE management (every action class at
once, #20967). This script splits it by ACTION CLASS and grades each class on its own (ARCHITECTURE-CANONICAL
§ Active management clause 4), with no re-judging and no new decisions:

  * hold        the trade as entered, no action (desk_lifecycle_driver.run with no decider);
  * class X     Claude's RECORDED decisions with every action that is not X replaced by hold;
  * random X    the same number and sequence of X actions at random check-ins of the same trade
                (desk_lifecycle_driver.matched_random over the X-only check-ins), ``--draws`` seeded draws.

Every arm runs on the committed corpus (entries, decisions, round key and policy under
``comms/research/desk_lifecycle/full-c4e/``) with the driver's own replay and full cost stack
(src.runtime.execution_costs, fee + slippage + funding). Per entry source (Claude entries / random entries) each
arm is a BOOK of trades {entry_time, exit_time, net_r, mfe_r} graded by am_risk_adjusted.grade_risk_adjusted.

POSITIVE CONTROL, read before anything else: the hold arm and the all-classes arm must reproduce the committed
pairs.jsonl C_h / C_m / R_h / R_m byte-for-byte (to 1e-9). If they do not, the verdict is ``control_failed`` and
no class is read.

STATED LIMITS (also in every verdict):
  * the corpus is per-trade R; no account book is simulated (row BOOK-SIM-REAL-SIZER), so every grade here is
    measurement_basis=per_trade_r_screen;
  * a recorded decision was taken on the all-classes path; replaying it after other classes are masked keeps its
    check-in ordinal k, not the state Claude saw. A class-only arm is the class's recorded calls, not a re-judgement;
  * the corpus is 1h crypto USD-M perps over 2025-05..2026-09 (candle manifest in entries-meta.json).

Tier-1 research tooling: reads committed records and public candles, writes only --out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts" / "research", REPO / "scripts" / "ops"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import am_risk_adjusted as am  # noqa: E402
from scripts.research import desk_lifecycle_driver as dl  # noqa: E402

CORPUS = REPO / "comms" / "research" / "desk_lifecycle" / "full-c4e"
CLASSES = ("tighten_sl", "widen_sl", "move_tp", "partial_close", "close")
DRAWS = 100            # R4: beat >= 95% of 100 seeded draws (RULE_V1.min_control_beat_frac)
FOLDS, FOLD_MAJORITY = 4, 3   # the corpus's own fold convention (RULE-RQ20261028-D1F5-02: 3 of 4)
SEED = 20261029
ACCOUNTS = ("bybit_1", "bybit_2", "bybit_portfolio")   # the crypto accounts the desk / LTR acts on (% view only)


def class_only(dec: Dict[Tuple[str, int], dict], entry_id: str, cls: str) -> dl.Decider:
    """Claude's recorded answer when it is ``cls``; hold for every other answer (a missing answer stays missing)."""
    def d(k, j, st):  # inert: j, st -- the shared Decider signature
        a = dec.get((entry_id, k))
        if a is None:
            return None
        return a if a.get("action") == cls else {"action": "hold"}
    return d


def trade_row(s: Any, e: dl.Entry, res: dl.Result) -> Dict[str, Any]:
    """One book row: entry/exit time from the replay, net R, and the peak favourable excursion in R over the bars the
    position was open (the giveback measurement's numerator)."""
    t0 = dl.g.simulate(s, e.i, e.side, e.etype, e.level, e.stop, e.tp, e.good_till, e.horizon)
    fi, fill, risk = t0.fill_i, t0.fill_px, t0.risk
    last = max(xi for _f, _px, xi, _w in res.pieces)
    ext = max(s.h[fi:last + 1]) if e.side > 0 else min(s.l[fi:last + 1])
    mfe = max(0.0, e.side * (float(ext) - fill) / risk)
    ts = lambda i: datetime.fromtimestamp(int(s.t[i]), tz=timezone.utc).isoformat()  # noqa: E731
    return {"entry_time": ts(fi), "exit_time": ts(last), "net_r": float(res.net_r), "mfe_r": round(mfe, 6)}


def build_books(mkt, entries, dec, policy: str, draws: int, classes=CLASSES, seed: int = SEED) -> Dict[str, Any]:
    pol = dl.POLICIES[policy]
    by_pair: Dict[str, Dict[str, dl.Entry]] = {}
    for e in entries:
        by_pair.setdefault(e.pair_id, {})[e.source] = e
    out: Dict[str, Any] = {}
    for src in ("claude", "random"):
        books: Dict[str, List[dict]] = {"hold": [], "all": []}
        for c in classes:
            books[c] = []
            for q in range(draws):
                books[f"{c}~rnd{q}"] = []
        repro: List[Tuple[str, float, float]] = []
        action_counts: Dict[str, int] = {c: 0 for c in classes}
        for pid, d in sorted(by_pair.items()):
            if "claude" not in d or "random" not in d:
                continue
            e = d[src]
            s = mkt[e.symbol]
            h = dl.run(s, e)[0]
            allr, pend = dl.run(s, e, dl._decider(e.entry_id, dec), pol())
            if h.state != "filled" or pend is not None:
                continue          # the corpus's own population: a pending managed run has no C_m either
            repro.append((pid, h.net_r, allr.net_r))
            books["hold"].append(trade_row(s, e, h))
            books["all"].append(trade_row(s, e, allr))
            for c in classes:
                r, p2 = dl.run(s, e, class_only(dec, e.entry_id, c), pol())
                if p2 is not None:
                    raise AssertionError(f"class-only replay of {pid} pended: a decision the all-classes run had is missing")
                books[c].append(trade_row(s, e, r))
                xs = [x for x in r.checkins if x["action"] == c]
                action_counts[c] += len(xs)
                for q in range(draws):
                    sd = int(hashlib.sha256(f"amcr|{seed}|{e.entry_id}|{c}|{q}".encode()).hexdigest()[:8], 16)
                    rr = dl.run(s, e, dl.matched_random(r.checkins, sd), pol())[0]
                    books[f"{c}~rnd{q}"].append(trade_row(s, e, rr))
        out[src] = {"books": books, "repro": repro, "actions": action_counts}
    return out


def positive_control(repro: List[Tuple[str, float, float]], pairs_path: Path, src: str) -> Dict[str, Any]:
    tag = "C" if src == "claude" else "R"
    committed = {}
    for ln in pairs_path.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get(f"{tag}_m") is not None:
                committed[r["pair_id"]] = (r[f"{tag}_h"], r[f"{tag}_m"])
    got = {pid: (h, m) for pid, h, m in repro}
    bad = [pid for pid in set(got) | set(committed)
           if pid not in got or pid not in committed
           or abs(got[pid][0] - committed[pid][0]) > 1e-9 or abs(got[pid][1] - committed[pid][1]) > 1e-9]
    return {"ok": not bad, "committed": len(committed), "reproduced": len(got), "mismatched_or_missing": len(bad),
            "examples": sorted(bad)[:5]}


def grade_all(built: Dict[str, Any], risk_pcts: Dict[str, float], classes=CLASSES, draws: int = DRAWS) -> Dict[str, Any]:
    params = {"folds": FOLDS, "fold_majority": FOLD_MAJORITY}
    res: Dict[str, Any] = {}
    for src, b in built.items():
        books = b["books"]
        per: Dict[str, Any] = {}
        for c in [*classes, "all"]:
            if c != "all" and b["actions"][c] == 0:
                per[c] = {"verdict": "indeterminate", "label": "class_never_acted", "n_actions": 0}
                continue
            ctl = [f"{c}~rnd{q}" for q in range(draws)] if c != "all" else []
            sub = {"hold": books["hold"], c: books[c], **{k: books[k] for k in ctl}}
            g = am.grade_risk_adjusted(sub, baseline="hold", candidates=[c], controls={c: ctl} if ctl else None,
                                       params=params, risk_pct_by_account=risk_pcts, basis="per_trade_r_screen")
            row = g["candidates"][c]
            # the random draws are summarised (their mean book + the beat count), never dumped one by one
            ctls = row.pop("controls", {})
            rk = [v["book"] for v in ctls.values()]
            row["random_control_summary"] = None if not rk else {
                "draws": len(rk), "beaten": sum(1 for v in ctls.values() if v["beats"]),
                "mean_net_r": round(sum(x["net_r"] for x in rk) / len(rk), 6),
                "mean_max_drawdown_r": round(sum(x["max_drawdown_r"] for x in rk) / len(rk), 6),
                "mean_giveback_r": round(sum(x["giveback"]["mean_r"] for x in rk) / len(rk), 6),
                "mean_pnl_pct_by_account": {a: round(sum(v["pnl_by_account"][a]["candidate_net_return_pct"]
                                                         for v in ctls.values()) / len(ctls), 4)
                                            for a in (risk_pcts or {})}}
            row["n_actions"] = b["actions"].get(c)
            row["mean_net_r_per_trade"] = {"hold": round(g["baseline_book"]["net_r"] / g["baseline_book"]["n"], 6),
                                           "action": round(row["book"]["net_r"] / row["book"]["n"], 6)}
            per[c] = {"baseline_book": g["baseline_book"], "rule": g["rule"], **row}
        res[src] = per
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--fetch", action="store_true", help="fetch the corpus candles from Binance Vision")
    ap.add_argument("--candles-dir", default=None)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--control-only", action="store_true",
                    help="fidelity check only: reproduce pairs.jsonl C_h/C_m/R_h/R_m, read no class outcome")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mkt, missing, _cls, src_manifest = dl._prepare_market(a)
    pop = ("DESK-LIFECYCLE-S0 corpus comms/research/desk_lifecycle/full-c4e (#20967): judged-1 Claude entries and their "
           "matched random partners, policy C4E, 1h Binance Vision USD-M perps, full cost stack; per class: hold vs the "
           f"class's recorded calls vs {a.draws} matched random draws of the class")
    if missing:
        (out / "verdict.json").write_text(json.dumps({"verdict": "indeterminate", "read_state": "no_data", "n": None,
                                                      "population": pop, "note": f"candles missing for {missing}"}) + "\n")
        return 1
    policy = (CORPUS / "POLICY").read_text().strip()
    entries = dl.read_entries(CORPUS / "entries.jsonl")
    dec = dl.read_decisions(CORPUS, CORPUS / "decisions.jsonl")
    built = build_books(mkt, entries, dec, policy, 0 if a.control_only else a.draws,
                        classes=() if a.control_only else CLASSES)
    controls = {src: positive_control(b["repro"], CORPUS / "pairs.jsonl", src) for src, b in built.items()}
    if a.control_only:
        (out / "control.json").write_text(json.dumps(controls, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(controls))
        return 0 if all(c["ok"] for c in controls.values()) else 1
    rp = am.risk_pcts(list(ACCOUNTS))
    rec: Dict[str, Any] = {"decision_rule": {"id": am.RULE_ID, "unit_rule_id": "RULE-RQ20261029-1F39-02-DESK-CLASS-REGRADE",
                                             "registered_before_run": True},
                           "population": pop, "read_state": "measured", "candles": src_manifest,
                           "measurement_basis": "per_trade_r_screen",
                           "positive_control": controls}
    rec["known_limitation"] = ("No account book is simulated (row BOOK-SIM-REAL-SIZER): every grade is a per-trade-R "
                               "SCREEN; % per account is R x risk.risk_pct, uncompounded, never a book result; no $ "
                               "figure is committed (public repo). A class-only arm replays Claude's recorded calls by "
                               "check-in ordinal after other classes are masked; it is not a re-judgement.")
    if not all(c["ok"] for c in controls.values()):
        rec.update(verdict="indeterminate", label="control_failed", n=None,
                   note="the replay does not reproduce the committed pairs.jsonl: no class is read")
    else:
        g = grade_all(built, rp, draws=a.draws)
        rec["grades"] = g
        n_claude = len(built["claude"]["books"]["hold"])
        # the class verdict of record (registered): pass on BOTH entry sources, Claude entries and random entries
        both = sorted(c for c in CLASSES if all(g[s].get(c, {}).get("verdict") == "pass" for s in g))
        rec.update(n=n_claude, verdict="pass" if both else "fail",
                   label="classes_pass_both_sources" if both else "no_class_passes_both_sources",
                   classes_passing_both_sources=both,
                   classes_passing_any_source=sorted({c for s in g for c, r in g[s].items()
                                                      if c != "all" and r.get("verdict") == "pass"}),
                   note="per-trade-R SCREEN under RULE-AM-RISK-ADJUSTED-V1 (measurement_basis per_trade_r_screen)")
    (out / "verdict.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"], "label": rec.get("label"), "controls": {k: v["ok"] for k, v in controls.items()},
                      "both": rec.get("classes_passing_both_sources")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
