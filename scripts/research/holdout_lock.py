#!/usr/bin/env python3
"""HOLDOUT LEDGER: every read of a held-out window is recorded, and each re-read raises the pass bar (row HOLDOUT-DEFLATED-REUSE).

Operator 2026-11-05 ~19:05Z (chat, verbatim): "We can't just, like, give up on a certain line of research because we've already
trained a model on all the data that we have. That's ridiculous." Popup answer, verbatim: "Adopt (Rec.)". The adopted rule
(docs/reference/trading-and-model-practice-principles.md § "Re-reading a holdout"):

1. tweaking and retraining on the training-period walk-forward slices is unlimited (those reads are not claimed here);
2. re-testing on the SAME held-out window is allowed; every read of a FAMILY on an overlapping window and symbol set is recorded
   here, and the N-th read is graded against a DEFLATED bar (``bar_for(N)``) that tightens with N;
3. a family may use several holdout windows, all after its training period;
4. a holdout that overlaps the training dates is REFUSED (``WindowOverlapsTraining``; PI-20261105-GEXSLEAK-0001). That is the
   one hard refusal left; the old one-model-one-read refusal (operator 2026-11-01, "Yes, one model, one read (Rec.)") is replaced.

The deflated bar (``bar_for``), for the N-th read of a family on a window:
* CI bars ("CI lower bound > 0"): a Sidak multiple-testing correction. The one-sided level is alpha_N = 1 - (1 - 0.025)^(1/N), so the
  grader uses a two-sided (1 - 2*alpha_N) interval: N=1 is the CI95 used today (z 1.960), N=2 z 2.239, N=5 z 2.572, N=10 z 2.803.
* point bars ("mean net R >= 0"): the Bailey & Lopez de Prado (2014) deflated-Sharpe hurdle, the expected maximum of N null
  t-statistics, E[max_N] = (1-g)*inv(1-1/N) + g*inv(1-1/(N e)), g = Euler-Mascheroni. The grader requires mean / se >= that
  hurdle: N=1 is 0 (today's mean >= 0), N=2 0.52, N=5 1.19, N=10 1.57.

    python3 scripts/research/holdout_lock.py --self-test
    python3 scripts/research/holdout_lock.py claim --model-id ENTRY-v3 --family ENTRY --train-end 2025-09-30 \
        --start 2025-10-01 --end 2026-09-30 --unit RQ-... --reader <who>
    python3 scripts/research/holdout_lock.py next-bar --family ENTRY --start 2025-10-01 --end 2026-09-30
    python3 scripts/research/holdout_lock.py families      # n_tries per (family, window) so far
    python3 scripts/research/holdout_lock.py list
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist

LEDGER = Path(__file__).resolve().parents[2] / "comms" / "research" / "holdout_reads.jsonl"
ALPHA_ONE_SIDED = 0.025          # the CI95 lower bound every grader uses today (N = 1)
EULER_GAMMA = 0.5772156649015329
METHOD = ("Sidak-corrected CI (alpha_N = 1-(1-0.025)^(1/N), one-sided) for CI bars; Bailey-Lopez de Prado expected max of N null "
          "t-stats for point bars")
_N = NormalDist()


class WindowOverlapsTraining(ValueError):
    """The one hard refusal: a holdout that starts on or before the training data's end (rule 4)."""


def _rows(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]


def _overlap(a0: str, a1: str, b0: str, b1: str) -> bool:
    return a0 <= b1 and b0 <= a1


def _syms_overlap(a, b: set) -> bool:
    """A claim with no symbol list means 'all symbols' and overlaps everything; two explicit lists overlap iff they share one."""
    return (not a) or (not b) or bool(set(a) & b)


def family_of(row_or_model_id) -> str:
    """The family a read counts against: the row's ``family`` field, else the model_id's first dash-separated token
    (ENTRY-v1-c692-01 -> ENTRY, MANAGE-mlsl -> MANAGE). Rows written before 2026-11-05 carry no family field."""
    if isinstance(row_or_model_id, dict):
        return row_or_model_id.get("family") or row_or_model_id["model_id"].split("-")[0]
    return row_or_model_id.split("-")[0]


def check_window_disjoint(train_end: str, start: str) -> None:
    """Rule 4 (PI-20261105-GEXSLEAK-0001): the holdout must start AFTER the last training date. For a symbol holdout this is still
    a date rule: correlated series leak through shared dates (principles M3), so other symbols over training dates are refused too."""
    if not train_end:
        raise WindowOverlapsTraining("train_end is required: the holdout must be shown to start after the training data ends")
    date.fromisoformat(train_end), date.fromisoformat(start)
    if start <= train_end:
        raise WindowOverlapsTraining(f"holdout starts {start}, on or before the training end {train_end}: the dates overlap training")


def bar_for(n_tries: int) -> dict:
    """The pass bar for the ``n_tries``-th read of a family on a window. N = 1 is exactly today's bar."""
    n = max(1, int(n_tries))
    a = 1.0 - (1.0 - ALPHA_ONE_SIDED) ** (1.0 / n)
    z = _N.inv_cdf(1.0 - a)
    t_min = 0.0 if n == 1 else ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n) + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))
    return {"n_tries": n, "alpha_one_sided": round(a, 6), "ci_level": round(1 - 2 * a, 6), "ci_z": round(z, 4),
            "ci_lo_percentile": round(100 * a, 4), "point_t_min": round(t_min, 4), "method": METHOD}


def ci_lower(mean: float, se: float, bar: dict | None) -> float:
    """The deflated normal-approximation CI lower bound: mean - z_N * se (z_1 = 1.96)."""
    return mean - (bar or bar_for(1))["ci_z"] * se


def point_ok(mean: float | None, se: float | None, bar: dict | None) -> bool:
    """A point bar 'mean >= 0' deflated: mean >= point_t_min * se. At N = 1 it is exactly mean >= 0."""
    if mean is None:
        return False
    t_min = (bar or bar_for(1))["point_t_min"]
    if t_min == 0:
        return mean >= 0
    return se is not None and mean >= t_min * se


def boot_ci(means, bar: dict | None) -> list[float]:
    """Percentile bootstrap interval at the deflated level, from a list of bootstrap means."""
    import numpy as np
    p = (bar or bar_for(1))["ci_lo_percentile"]
    return [float(np.percentile(means, p)), float(np.percentile(means, 100 - p))]


def prior_tries(family: str, start: str, end: str, symbols=None, ledger: Path = LEDGER) -> list[dict]:
    syms = set(symbols or [])
    return [r for r in _rows(ledger) if family_of(r) == family and _overlap(r["start"], r["end"], start, end)
            and _syms_overlap(r.get("symbols"), syms)]


def next_bar(family: str, start: str, end: str, symbols=None, ledger: Path = LEDGER) -> dict:
    """Read-only: the bar the NEXT read of this family on this window would be graded against."""
    return bar_for(len(prior_tries(family, start, end, symbols, ledger)) + 1)


def claim_read(model_id: str, start: str, end: str, unit: str, reader: str, ledger: Path = LEDGER,
               read_at: str | None = None, symbols: list[str] | None = None, *, train_end: str,
               family: str | None = None) -> dict:
    """Record one read BEFORE any outcome in the window is touched, and return the deflated bar it is graded against
    (``rec["bar"]``) plus the bar for the next read (``rec["next_bar"]``). Never refuses a re-read; refuses a window that
    overlaps training. ``read_at`` is only for BACKFILLING a read that happened earlier (recorded with backfilled=true)."""
    if not (model_id and unit and reader):
        raise ValueError("model_id, unit and reader are required")
    if not start <= end:
        raise ValueError("start must be <= end")
    check_window_disjoint(train_end, start)
    fam = family or family_of(model_id)
    syms = set(symbols or [])
    rows = _rows(ledger)
    n = len(prior_tries(fam, start, end, symbols, ledger)) + 1
    models = {r["model_id"] for r in rows if _overlap(r["start"], r["end"], start, end)
              and _syms_overlap(r.get("symbols"), syms)} | {model_id}
    rec = {"model_id": model_id, "family": fam, "start": start, "end": end, "train_end": train_end, "unit": unit, "reader": reader,
           "read_at": read_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "backfilled": bool(read_at), "symbols": sorted(syms) or None,
           "variants_on_window": len(models), "n_tries": n, "bar": bar_for(n)}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return {**rec, "next_bar": bar_for(n + 1)}


def families(ledger: Path = LEDGER) -> list[dict]:
    """n_tries so far per (family, window, symbol scope), from the ledger; rows before 2026-11-05 are counted by family_of."""
    out: dict[tuple, dict] = {}
    for r in _rows(ledger):
        k = (family_of(r), r["start"], r["end"], "all" if not r.get("symbols") else f"{len(r['symbols'])} symbols")
        e = out.setdefault(k, {"family": k[0], "start": k[1], "end": k[2], "symbols": k[3], "n_tries": 0, "models": [], "units": [],
                               "_syms": r.get("symbols")})
        e["n_tries"] += 1
        e["models"].append(r["model_id"])
        e["units"].append(r["unit"])
    for e in out.values():   # the next read counts every OVERLAPPING read of the family, not only this exact window's
        e["next_bar"] = next_bar(e["family"], e["start"], e["end"], e.pop("_syms"), ledger)
    return list(out.values())


def self_test() -> None:
    b1, b2, b5 = bar_for(1), bar_for(2), bar_for(5)
    assert abs(b1["ci_z"] - 1.96) < 1e-3 and b1["ci_level"] == 0.95 and b1["point_t_min"] == 0.0, b1   # 1st read = today's bar
    assert b1["ci_z"] < b2["ci_z"] < b5["ci_z"] and 0 < b2["point_t_min"] < b5["point_t_min"], (b2, b5)  # N-th read is stricter
    assert point_ok(0.0, 0.1, b1) and not point_ok(-1e-9, 0.1, b1)
    assert not point_ok(0.04, 0.1, b2) and point_ok(0.06, 0.1, b2)
    assert ci_lower(0.21, 0.1, b1) > 0 and ci_lower(0.21, 0.1, b2) < 0
    with tempfile.TemporaryDirectory() as d:
        led = Path(d) / "l.jsonl"
        a = claim_read("ENTRY-m1", "2026-10-01", "2026-10-31", "U1", "tester", led, train_end="2026-09-30")
        assert a["n_tries"] == 1 and a["bar"] == b1 and a["next_bar"] == b2 and a["family"] == "ENTRY"
        b = claim_read("ENTRY-m1", "2026-10-15", "2026-11-05", "U1b", "tester", led, train_end="2026-09-30")   # re-read: allowed
        assert b["n_tries"] == 2 and b["bar"]["ci_z"] > a["bar"]["ci_z"], "a re-read must be graded against a stricter bar"
        c = claim_read("ENTRY-m2", "2026-10-01", "2026-10-31", "U2", "tester", led, train_end="2026-09-30")
        assert c["n_tries"] == 3 and c["variants_on_window"] == 2, "a second variant of the family counts as a try"
        e = claim_read("MANAGE-x", "2026-10-01", "2026-10-31", "U3", "tester", led, train_end="2026-09-30")
        assert e["n_tries"] == 1, "another family on the same window starts its own count"
        f = claim_read("ENTRY-m3", "2026-11-11", "2026-11-20", "U4", "tester", led, train_end="2026-09-30")
        assert f["n_tries"] == 1, "a disjoint holdout window starts a fresh count (rule 3)"
        g = claim_read("ENTRY-m3", "2025-10-01", "2026-09-30", "U5", "t", led, symbols=["BTCUSDT"], train_end="2025-09-30")
        h = claim_read("ENTRY-m3", "2025-10-01", "2026-09-30", "U6", "t", led, symbols=["SPY"], train_end="2025-09-30")
        assert g["n_tries"] == 1 and h["n_tries"] == 1, "disjoint symbol sets count separately"
        assert next_bar("ENTRY", "2026-10-01", "2026-10-31", None, led)["n_tries"] == 4
        n_before = len(_rows(led))
        for bad in ("2026-09-30", "2026-09-01"):    # rule 4: starting on or before the training end is refused
            try:
                claim_read("ENTRY-m4", bad, "2026-10-31", "U7", "t", led, train_end="2026-09-30")
                raise AssertionError("a holdout overlapping the training dates was allowed")
            except WindowOverlapsTraining:
                pass
        try:
            claim_read("ENTRY-m4", "2026-10-01", "2026-10-31", "U7", "t", led, train_end="")
            raise AssertionError("a claim without a training end was allowed")
        except WindowOverlapsTraining:
            pass
        assert len(_rows(led)) == n_before, "a refused claim must append nothing"
        fam = [x for x in families(led) if x["family"] == "ENTRY" and x["start"] == "2026-10-01"]
        assert fam and fam[0]["n_tries"] == 2 and fam[0]["next_bar"]["n_tries"] == 4, fam
    # the committed ledger parses and every row has a family
    assert all(family_of(r) for r in _rows(LEDGER))
    print(f"holdout_lock self-test OK: read 1 bar z={b1['ci_z']:.3f} t>={b1['point_t_min']:.2f}; read 2 z={b2['ci_z']:.3f} "
          f"t>={b2['point_t_min']:.2f}; read 5 z={b5['ci_z']:.3f} t>={b5['point_t_min']:.2f}; overlap refused")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["claim", "list", "next-bar", "families"])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--model-id")
    ap.add_argument("--family")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--train-end", default="")
    ap.add_argument("--unit")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--reader", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--ledger", default=str(LEDGER))
    a = ap.parse_args()
    syms = [x for x in a.symbols.split(",") if x] or None
    if a.self_test:
        self_test()
        return 0
    if a.cmd == "claim":
        print(json.dumps(claim_read(a.model_id, a.start, a.end, a.unit, a.reader, Path(a.ledger), symbols=syms,
                                    train_end=a.train_end, family=a.family)))
        return 0
    if a.cmd == "next-bar":
        print(json.dumps(next_bar(a.family, a.start, a.end, syms, Path(a.ledger))))
        return 0
    if a.cmd == "families":
        for e in families(Path(a.ledger)):
            print(json.dumps(e))
        return 0
    if a.cmd == "list":
        for r in _rows(Path(a.ledger)):
            print(json.dumps(r))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
