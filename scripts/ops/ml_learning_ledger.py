#!/usr/bin/env python3
"""ml_learning_ledger -- is the ML pipeline LEARNING?  (ML-PROGRAMME-2026-10-28 section 7; row ML-LEARNING-LEDGER)

Hops, per data source (a source is one producer of teacher/label rows):

  H1 produced   rows produced in the window
  H2 labelled   rows with an outcome joined (replayed/realised; ``not_computable`` is NOT a label)
  H3 in dataset labelled rows listed as consumed by a dataset build / bench run
  H4 trained    registry manifests on this source's dataset family whose latest run is in the window
  H5 scored     research units on the ML theme graded (verdict != none) in the window     (pipeline-wide)
  H6 promoted   models at shadow/advisory whose dataset family is a TRADE decision        (pipeline-wide)
  H7 order      rostered legs where an ML output can change an order; real-money among them (pipeline-wide)

Every hop is ``{"value": <int|None>, "provenance": measured|estimated|unverified, "read_state": ...}``.
A hop that could not be looked at is ``value: null`` + ``read_state: could_not_look`` + ``reason`` (renders "—",
never 0: CLAUDE.md "Render a missing/null field as —"). ``absent`` = the source exists nowhere (a true zero is only
``read`` with a population). Provenance vocabulary: ``src/runtime/provenance.py`` (imported, not re-declared).

ALARMS (one flag each to the manager, never a halt -- Prime Directive rule 7): a hop at 0 for the window while the
hop before it is non-zero; a manifest absent from the registry; a hop that could not be looked at.

WHERE THE RECORD LIVES (operator 2026-11-04: not the repo as a database). This script reads, prints and optionally
POSTS the weekly record as a note on a work-store item (``--post-note <ITEM>``, via ``scripts/ops/work.py``: the
hash-chained event log behind ``/api/bot/work/items/<id>/events``). It never writes a file under ``comms/``. The
record is shaped as ledger rows (one per source x hop) so the S6C ``ml_learning`` ledger (WORK-STORE-DESIGN-2026-11
section 6/7) can import it unchanged.

Gates this adds or changes: none. Read-only; ``--post-note`` is the only write and is opt-in. Exit 0 = ran
(alarms are printed, not failed on), 2 = could not measure ANYTHING. No secrets, ids or balances are read or printed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.runtime import provenance as P  # noqa: E402

API = "https://ict-bot.duckdns.org/api/bot"
LABEL_KINDS_EXCLUDED = {"not_computable", "pending"}
#: Source -> the registry dataset families whose manifests read it. ESTIMATED mapping (declared here, once).
SOURCE_FAMILIES = {
    "desk": ("claude_judgments",),
    "live_review": ("live_review", "live_review_outcomes"),
    "trade_closes": ("trade_outcomes", "execution_quality", "setup_labels", "conviction_meta"),
    "paths_corpus": ("corpus_panel", "setup_candidates"),
}
#: Families whose target is a trade decision (not a vol/regime head). ESTIMATED proxy for "H6 target".
TRADE_DECISION_FAMILIES = {"trade_outcomes", "setup_candidates", "setup_labels", "setup_labels_audit",
                           "conviction_meta", "execution_quality", "account_context", "claude_judgments"}
ML_THEMES = {"ml_health"}


def hop(value, prov, read_state="read", **kw):
    return {"value": value, "provenance": prov, "read_state": read_state, **kw}


def cnl(reason):
    """could_not_look: null, never 0."""
    return {"value": None, "provenance": P.UNVERIFIED, "read_state": "could_not_look", "reason": reason}


def fmt(h):
    return "—" if h.get("value") is None else str(h["value"])


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def jsonl(path):
    """-> (rows, read_state). absent != empty != could_not_look."""
    if not path.exists():
        return [], "absent"
    rows = []
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except (OSError, ValueError):
        return [], "could_not_look"
    return rows, "read"


def in_window(row, keys, start):
    for k in keys:
        t = _ts(row.get(k))
        if t:
            return t >= start
    return False


def get_json(url):
    try:
        with urlopen(url, timeout=30) as r:  # noqa: S310 - fixed https host
            return json.load(r)
    except Exception as e:  # noqa: BLE001 - a failed read is a read-state, not a crash
        return {"_error": type(e).__name__}


def count_file_source(root, name, h1_file, h1_keys, h2_file, h2_keys, h3_file, start):
    """Counts for a source whose rows are committed files. Returns hops H1-H3."""
    out = {}
    d = root / "comms" / name
    rows, st = jsonl(d / h1_file)
    if st != "read":
        out["H1"] = cnl(f"{h1_file} {st}")
        out["H2"] = cnl("H1 source unreadable")
        out["H3"] = cnl("H1 source unreadable")
        return out
    h1 = [r for r in rows if in_window(r, h1_keys, start)]
    out["H1"] = hop(len(h1), P.MEASURED, population=f"{len(rows)} rows all-time in {h1_file}; window by {'/'.join(h1_keys)}",
                    all_time=len(rows))
    orows, ost = jsonl(d / h2_file)
    if ost != "read":
        out["H2"] = cnl(f"{h2_file} {ost}")
    else:
        lab = [r for r in orows if r.get("kind", "labelled") not in LABEL_KINDS_EXCLUDED
               and (r.get("net_r") is not None or r.get("cf_r") is not None) and in_window(r, h2_keys, start)]
        out["H2"] = hop(len(lab), P.MEASURED, population=f"{len(orows)} outcome rows all-time; "
                        "label = net_r or cf_r present, kind not not_computable", all_time=len(orows))
    if h3_file is None:
        out["H3"] = cnl("no consumed-ids ledger exists for this source (nothing records which labels a dataset build read)")
    else:
        crows, cst = jsonl(d / h3_file)
        out["H3"] = (cnl(f"{h3_file} {cst}") if cst == "could_not_look" else
                     hop(len([r for r in crows if in_window(r, ("consumed_at", "ts", "at"), start)]), P.MEASURED,
                         read_state=cst, population=f"{len(crows)} rows all-time in {h3_file}", all_time=len(crows)))
    return out


def registry_hops(start):
    """H4 per family, H6, from the public registry. Returns (rows|None, reason)."""
    reg = get_json(f"{API}/ml/registry")
    if "_error" in reg or "rows" not in reg:
        return None, f"/ml/registry {reg.get('_error', 'no rows key')}"
    return reg["rows"], None


def stage_of(r):
    return str(r.get("target_deployment_stage") or "").lower(), str(r.get("deployment_bucket") or "").upper()


def h4_for(rows, families, start):
    n = 0
    for r in rows:
        ref = r.get("dataset_ref")
        fam = ref.get("family") if isinstance(ref, dict) else None
        t = _ts((r.get("latest_run") or {}).get("at"))
        if fam in families and t and t >= start:
            n += 1
    return n


def h5(root, start):
    q = REPO / "research" / "queue"
    res = REPO / "research" / "results"
    if not q.exists() or not res.exists():
        return cnl("research/queue or research/results absent")
    ml_units = set()
    try:
        for f in q.glob("RQ-*.yaml"):
            head = f.read_text().split("\n")
            for line in head[:200]:
                if line.startswith("theme:"):
                    if line.split(":", 1)[1].strip() in ML_THEMES:
                        ml_units.add(f.stem)
                    break
    except OSError:
        return cnl("research/queue unreadable")
    n, verdicts = 0, {}
    for d in res.iterdir():
        if d.name not in ml_units:
            continue
        for f in d.glob("*.jsonl"):
            for line in f.read_text().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("verdict") and in_window(r, ("generated_at",), start):
                    n += 1
                    verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    return hop(n, P.MEASURED, population=f"result rows with a verdict, generated in window, for {len(ml_units)} queue units "
               f"of theme {sorted(ML_THEMES)}", verdicts=verdicts)


def h7():
    try:
        strat = yaml.safe_load((REPO / "config/strategies.yaml").read_text())["strategies"]
        acc = yaml.safe_load((REPO / "config/accounts.yaml").read_text())["accounts"]
        ov = yaml.safe_load((REPO / "config/overlay_policy.yaml").read_text()).get("strategies") or {}
    except (OSError, KeyError, yaml.YAMLError) as e:
        return cnl(f"config unreadable: {type(e).__name__}"), cnl("config unreadable")
    live = {k for k, v in strat.items() if v.get("enabled") and v.get("execution") == "live"}
    changers = {k for k in live if strat[k].get("model")} | {k for k, v in ov.items() if v.get("mode") == "reduce" and k in live}
    real = set()
    for a in acc.values():
        if a.get("account_class") in ("real_money", "prop") and a.get("mode") == "live":
            real |= set(a.get("strategies") or [])
    note = ("ML output can change an order = strategy declares a `model:` or is overlay mode `reduce`; regime-router "
            "advisory consumers are NOT counted, so this is a LOWER BOUND")
    a = hop(len(changers), P.ESTIMATED, population=f"{len(live)} enabled live-execution legs in config/strategies.yaml", note=note)
    b = hop(len(changers & real), P.ESTIMATED,
            population=f"{len(real)} legs rostered on a live real_money/prop account", note=note)
    return a, b


def build(root, window_days, now):
    start = now - timedelta(days=window_days)
    rec = {"schema": "ml_learning/1", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": window_days,
           "window_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": {}, "pipeline": {}, "alarms": []}
    reg_rows, reg_err = registry_hops(start)
    srcs = rec["sources"]
    srcs["desk"] = count_file_source(root, "desk", "decisions.jsonl", ("judged_at",), "outcomes.jsonl",
                                     ("computed_at",), "consumed.jsonl", start)
    srcs["live_review"] = count_file_source(root, "live_review", "reviews.jsonl", ("reviewed_at",), "outcomes.jsonl",
                                            ("computed_at",), None, start)
    srcs["trade_closes"] = {"H1": cnl("journal closes need the live VM journal (diag read token); not read by this script"),
                            "H2": cnl("same"), "H3": cnl("same")}
    srcs["paths_corpus"] = {"H1": cnl("paths corpus lives in the research harness (broad_paths_corpus), not a committed file"),
                            "H2": cnl("same"), "H3": cnl("same")}
    for s, fams in SOURCE_FAMILIES.items():
        if reg_rows is None:
            srcs[s]["H4"] = cnl(reg_err)
        else:
            srcs[s]["H4"] = hop(h4_for(reg_rows, fams, start), P.ESTIMATED,
                                population=f"{len(reg_rows)} registry rows; source->family mapping {list(fams)} is declared, not read")
    pl = rec["pipeline"]
    pl["H5"] = h5(root, start)
    if reg_rows is None:
        pl["H6"] = cnl(reg_err)
    else:
        n = 0
        for r in reg_rows:
            tgt, bucket = stage_of(r)
            ref = r.get("dataset_ref")
            fam = ref.get("family") if isinstance(ref, dict) else None
            if (tgt in ("shadow", "advisory") or bucket in ("SHADOW", "LIVE")) and fam in TRADE_DECISION_FAMILIES:
                n += 1
        pl["H6"] = hop(n, P.ESTIMATED, population=f"{len(reg_rows)} registry rows; trade-decision = dataset family in "
                       f"{sorted(TRADE_DECISION_FAMILIES)} (proxy: manifests carry no target field)")
    pl["H7"], pl["H7_real_money"] = h7()
    # alarms: hop at 0 while the previous hop is non-zero; any could_not_look
    for s, hops in srcs.items():
        order = [k for k in ("H1", "H2", "H3", "H4") if k in hops]
        for prev, cur in zip(order, order[1:]):
            pv, cv = hops[prev].get("value"), hops[cur].get("value")
            if pv and cv == 0:
                rec["alarms"].append(f"{s}: {cur} is 0 while {prev} is {pv} (recorded-but-never-learned shape)")
        for k, h in hops.items():
            if h["read_state"] == "could_not_look":
                rec["alarms"].append(f"{s}.{k}: could_not_look ({h['reason']})")
    for k, h in pl.items():
        if h["read_state"] == "could_not_look":
            rec["alarms"].append(f"pipeline.{k}: could_not_look ({h['reason']})")
    if pl.get("H5", {}).get("value") and pl.get("H6", {}).get("value") == 0:
        rec["alarms"].append("pipeline: H5 scored is non-zero but H6 promoted is 0")
    return rec


def render(rec):
    lines = [f"ML learning ledger  window {rec['window_start']} .. {rec['generated_at']} ({rec['window_days']} d)", ""]
    lines.append(f"{'source':14}" + "".join(f"{h:>8}" for h in ("H1", "H2", "H3", "H4")))
    for s, hops in rec["sources"].items():
        lines.append(f"{s:14}" + "".join(f"{fmt(hops.get(h, cnl('')))+('*' if hops.get(h, {}).get('provenance') == P.ESTIMATED else ''):>8}"
                                         for h in ("H1", "H2", "H3", "H4")))
    pl = rec["pipeline"]
    lines += ["", f"H5 scored {fmt(pl['H5'])}   H6 promoted {fmt(pl['H6'])}*   H7 order-changing legs {fmt(pl['H7'])}* "
              f"(real-money/prop {fmt(pl['H7_real_money'])}*)", "  * ESTIMATED; — = could_not_look", ""]
    lines += ["ALARMS:"] + [f"  - {a}" for a in rec["alarms"]] if rec["alarms"] else ["ALARMS: none"]
    return "\n".join(lines)


def self_test():
    """Planted/clean pair: planted -> alarm fires and nulls render '—'; clean -> no alarm."""
    import tempfile
    for planted in (True, False):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "comms" / "desk"
            d.mkdir(parents=True)
            now = datetime(2026, 11, 12, tzinfo=timezone.utc)
            ts = "2026-11-10T00:00:00Z"
            (d / "decisions.jsonl").write_text(json.dumps({"judged_at": ts}) + "\n")
            out = {"kind": "replayed", "net_r": 1.0, "computed_at": ts}
            (d / "outcomes.jsonl").write_text(json.dumps(out) + "\n")
            (d / "consumed.jsonl").write_text("" if planted else json.dumps({"consumed_at": ts}) + "\n")
            h = count_file_source(Path(td), "desk", "decisions.jsonl", ("judged_at",), "outcomes.jsonl",
                                  ("computed_at",), "consumed.jsonl", now - timedelta(days=7))
            assert h["H1"]["value"] == 1 and h["H2"]["value"] == 1, h
            assert h["H3"]["value"] == (0 if planted else 1), h
            assert fmt(cnl("x")) == "—"
            # absent file must be could_not_look (null), never 0
            h2 = count_file_source(Path(td), "nonexistent", "decisions.jsonl", ("judged_at",), "o.jsonl", ("computed_at",),
                                   None, now - timedelta(days=7))
            assert h2["H1"]["value"] is None and fmt(h2["H1"]) == "—"
            zero_after_nonzero = bool(h["H2"]["value"] and h["H3"]["value"] == 0)
            assert zero_after_nonzero is planted
    print("self-test ok (planted alarms, clean does not; absent source renders —)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--post-note", metavar="ITEM", help="post the compact record as a note on this work-store item")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
        return 0
    rec = build(Path(a.root), a.window_days, datetime.now(timezone.utc))
    print(json.dumps(rec, indent=1) if a.json else render(rec))
    if a.post_note:
        text = "ml_learning/1 " + json.dumps(rec, separators=(",", ":"))
        subprocess.run([sys.executable, str(REPO / "scripts/ops/work.py"), "--via", "direct", "note", a.post_note, text,
                        "--by", "ml_learning_ledger"], check=True)
    looked = [h for hs in rec["sources"].values() for h in hs.values()] + list(rec["pipeline"].values())
    return 0 if any(h["read_state"] != "could_not_look" for h in looked) else 2


if __name__ == "__main__":
    sys.exit(main())
