#!/usr/bin/env python3
# wiring: research/queue/RQ-20261014-470a-11 via .github/workflows/research-script-run.yml (compute: cpu_light)
"""Programme 03 (strategy improvement), the Stage-0 half of the headline measure:
net R per capital-day per ROUTED leg, read off the committed evidence records,
split by account class (real / mirror / prop / paper), never pooled across them.

WHY (lane P3-STRATEGY-PROGRAMME, 2026-10-14). The operator's headline measure is
net P&L per capital-day, per strategy and capital-weighted at portfolio level.
The harnesses already compute ``net_r_per_capital_day`` (``scripts/capital_efficiency.py``
is its one definition) and every committed evidence record names the ``__bt.json``
it was built from (``cost_stack.source``), but nothing reads that column across the
roster. So "which leg pulls its own weight, at the parameters it is configured with"
had no number. This script is that number for Stage 0; the live half is checklist
row ``HEADLINE-MEASURE-CAPITAL-DAY`` and the giveback census (``RQ-20261014-9807-01``).

WHAT IT READS. ``config/accounts.yaml`` (routings + ``account_class``; the class rule
is ``check_tp_doctrine._class_of``, imported, not copied), ``comms/strategy_evidence/<leg>.json``
(the record of each routed leg) and the ``__bt.json`` its ``cost_stack.source`` names.
It runs no harness and fetches nothing.

WHAT IT GRADES (the unit's rule, flags passed in, never defaults chosen here). Per leg:
  * ``no_record``      -- no evidence record, or its ``__bt.json`` is missing/unreadable
                         (a COULD-NOT-LOOK state, never a zero);
  * ``underpowered``   -- record n < ``--n-floor``;
  * ``drag``           -- net_r_per_capital_day <= 0 OR folds_positive/folds < ``--fold-share``;
  * ``pulls_weight``   -- otherwise.
The run's verdict is ``no_action_warranted`` (it is a census: the record IS the
deliverable) with read_state ``measured`` when at least one leg was read, else
``no_data``. ``records`` fans out one row per (class, leg) so research-ops can read
every leg's state without opening the measurement file.

Honesty notes. A record's ``net_r_per_capital_day`` covers the record's OWN window
(365 d for most legs; 1095 d / 1460 d where a longer run was committed) -- the window is
reported beside every figure, and figures from different windows are not comparable
as levels, only as signs. Capital-days here are POSITION-days at 1R risk (the harness
definition); the dollar twin and portfolio capital weighting need live account equity
and are the HEADLINE-MEASURE-CAPITAL-DAY row's, not this script's.

Tier-1 research tooling: reads committed files, writes ``<out>/verdict.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "ci"))
from check_tp_doctrine import _class_of  # noqa: E402  (one class rule, not two)

CLASS_ORDER = ("real", "prop", "mirror", "paper")


def _class(acc: dict[str, Any]) -> str:
    c = _class_of(acc)
    return {"live": "real", "real_money": "real"}.get(c, c)


def routings(accounts_yaml: Path) -> list[tuple[str, str, str]]:
    """(class, account, leg) for every leg on a roster of an account whose mode is live."""
    accts = (yaml.safe_load(accounts_yaml.read_text()) or {}).get("accounts") or {}
    out = []
    for name, acc in accts.items():
        if not isinstance(acc, dict) or str(acc.get("mode")) != "live":
            continue
        for s in acc.get("strategies") or []:
            leg = s if isinstance(s, str) else (s.get("name") if isinstance(s, dict) else None)
            if leg:
                out.append((_class(acc), name, leg))
    return out


def read_leg(repo: Path, leg: str) -> dict[str, Any]:
    rec_p = repo / "comms" / "strategy_evidence" / f"{leg}.json"
    if not rec_p.exists():
        return {"state": "no_record", "why": f"{rec_p.relative_to(repo)} absent"}
    try:
        rec = json.loads(rec_p.read_text())
    except (OSError, ValueError) as e:
        return {"state": "no_record", "why": f"record unreadable: {e}"}
    src = str((rec.get("cost_stack") or {}).get("source") or "")
    bt_p = repo / src if src else None
    if not bt_p or not bt_p.exists():
        return {"state": "no_record", "why": f"record names no readable __bt.json ({src or 'none'})"}
    bt = json.loads(bt_p.read_text())
    return {
        "record": rec_p.relative_to(repo).as_posix(), "bt": src,
        "window_days": rec.get("window_days"), "data_start": bt.get("data_start"), "data_end": bt.get("data_end"),
        "fidelity": rec.get("fidelity"), "n": rec.get("n_trades_oos"), "net_r": rec.get("net_r_oos"),
        "folds": rec.get("folds"), "folds_positive": rec.get("folds_positive"),
        "capital_days": bt.get("capital_days"), "net_r_per_capital_day": bt.get("net_r_per_capital_day"),
        "max_drawdown_r": bt.get("max_drawdown_r"),
    }


def grade_leg(m: dict[str, Any], n_floor: int, fold_share: float) -> str:
    if m.get("state") == "no_record" or m.get("net_r_per_capital_day") is None:
        return "no_record"
    if (m.get("n") or 0) < n_floor:
        return "underpowered"
    folds, pos = m.get("folds") or 0, m.get("folds_positive") or 0
    if m["net_r_per_capital_day"] <= 0 or (folds and pos / folds < fold_share):
        return "drag"
    return "pulls_weight"


def census(repo: Path, n_floor: int, fold_share: float) -> dict[str, Any]:
    rows, cache = [], {}
    for cls, acct, leg in routings(repo / "config" / "accounts.yaml"):
        if leg not in cache:
            cache[leg] = read_leg(repo, leg)
        m = cache[leg]
        rows.append({"class": cls, "account": acct, "leg": leg, "grade": grade_leg(m, n_floor, fold_share), **m})
    by_class: dict[str, dict[str, Any]] = {}
    for cls in sorted({r["class"] for r in rows}, key=lambda c: (CLASS_ORDER + (c,)).index(c)):
        legs = {r["leg"]: r for r in rows if r["class"] == cls}
        g = [r["grade"] for r in legs.values()]
        by_class[cls] = {"legs": len(legs), **{k: g.count(k) for k in ("pulls_weight", "drag", "underpowered", "no_record")}}
    return {"rows": rows, "by_class": by_class}


def verdict(c: dict[str, Any], n_floor: int, fold_share: float) -> dict[str, Any]:
    read = [r for r in c["rows"] if r["grade"] != "no_record"]
    legs = sorted({r["leg"] for r in c["rows"]})
    return {
        "verdict": "no_action_warranted" if read else "indeterminate",
        "read_state": "measured" if read else "no_data",
        "population": (f"{len(c['rows'])} (account, leg) routings on live-mode accounts in config/accounts.yaml, "
                       f"{len(legs)} distinct legs; each leg's committed evidence record + the __bt.json it names; "
                       f"split by account class {sorted(c['by_class'])}, never pooled"),
        "n": len(read),
        "note": ("Stage-0 census at CONFIGURED params: " + "; ".join(
            f"{k}: {v['pulls_weight']} pull weight / {v['drag']} drag / {v['underpowered']} underpowered / "
            f"{v['no_record']} no record (of {v['legs']})" for k, v in c["by_class"].items())
            + f". Grades use n_floor={n_floor}, fold_share={fold_share}; windows differ per record (see rows)."),
        "measurement": {"by_class": c["by_class"], "n_floor": n_floor, "fold_share": fold_share},
        "records": [{"population": f"{r['class']}/{r['account']}/{r['leg']}", "n": r.get("n"),
                     "verdict": "no_action_warranted", "read_state": "measured" if r["grade"] != "no_record" else "no_data",
                     **{k: r.get(k) for k in ("class", "account", "leg", "grade", "window_days", "net_r",
                                              "net_r_per_capital_day", "capital_days", "folds", "folds_positive",
                                              "fidelity", "record", "bt", "why")}}
                    for r in c["rows"]],
    }


def _self_test() -> int:
    import tempfile
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        ok &= cond
        print(("  PASS  " if cond else "  FAIL  ") + name)

    with tempfile.TemporaryDirectory() as td:
        r = Path(td)
        (r / "config").mkdir()
        (r / "comms" / "strategy_evidence" / "runs" / "x").mkdir(parents=True)
        (r / "config" / "accounts.yaml").write_text(yaml.safe_dump({"accounts": {
            "real_a": {"mode": "live", "account_class": "live", "strategies": ["good", "bad", "thin", "none"]},
            "mir_a": {"mode": "live", "account_class": "paper", "paper_role": "portfolio", "strategies": ["good"]},
            "off": {"mode": "dry_run", "account_class": "live", "strategies": ["good"]}}}))
        for leg, n, rpc, fp in (("good", 60, 0.1, 4), ("bad", 60, -0.02, 3), ("thin", 10, 0.3, 4)):
            src = f"comms/strategy_evidence/runs/x/{leg}__bt.json"
            (r / src).write_text(json.dumps({"net_r_per_capital_day": rpc, "capital_days": 50}))
            (r / "comms" / "strategy_evidence" / f"{leg}.json").write_text(json.dumps(
                {"n_trades_oos": n, "net_r_oos": 1.0, "folds": 4, "folds_positive": fp, "window_days": 365,
                 "cost_stack": {"source": src}}))
        c = census(r, 39, 0.75)
        g = {(x["account"], x["leg"]): x["grade"] for x in c["rows"]}
        check("dry_run account is not a routing", not any(a == "off" for a, _ in g))
        check("positive, powered, 4/4 folds -> pulls_weight", g[("real_a", "good")] == "pulls_weight")
        check("negative per-capital-day -> drag", g[("real_a", "bad")] == "drag")
        check("n below floor -> underpowered, not drag", g[("real_a", "thin")] == "underpowered")
        check("missing record -> no_record (could not look), never zero", g[("real_a", "none")] == "no_record")
        check("portfolio paper is the mirror class", "mirror" in c["by_class"] and c["by_class"]["mirror"]["legs"] == 1)
        v = verdict(c, 39, 0.75)
        check("verdict.json carries the script_run fields", all(k in v for k in ("verdict", "read_state", "population", "n")))
        check("one record row per routing", len(v["records"]) == 5)
    print("self-test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n-floor", type=int, default=None, help="the unit's n floor (required unless --self-test)")
    ap.add_argument("--fold-share", type=float, default=None, help="the unit's minimum folds_positive/folds")
    ap.add_argument("--out", default=None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()
    if a.n_floor is None or a.fold_share is None or not a.out:
        ap.error("--n-floor, --fold-share and --out are required (the unit's thresholds, never defaults)")
    c = census(REPO, a.n_floor, a.fold_share)
    v = verdict(c, a.n_floor, a.fold_share)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(v, indent=2, default=str) + "\n")
    for cls, s in c["by_class"].items():
        print(f"{cls:7s} legs={s['legs']} pulls_weight={s['pulls_weight']} drag={s['drag']} "
              f"underpowered={s['underpowered']} no_record={s['no_record']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
