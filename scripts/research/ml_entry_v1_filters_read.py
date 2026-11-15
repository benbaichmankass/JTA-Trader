#!/usr/bin/env python3
# wiring: research/queue/RQ-20261115-a474-04.yaml (run.command, via research-script-run.yml); --self-test in CI-free use
"""ML-BAR-ONE-READ for the FROZEN served ENTRY v1: the ONE combined held-out read of the dev-fold lever candidates.

Candidates (each a dev-fold WIN under its own registered rule, hand-graded 2026-11-15, PR #26252):
  * RQ-20261101-b602-01  C_vol24_abstain_t0 -- abstain when vol24 is in the LOWEST dev tercile;
  * RQ-20261101-b606-01  gate_0.06          -- abstain when the estimated round-trip cost per R (k / atr_pct) > 0.06.
(RQ-20261101-b601-01, the 2/4 bracket, FAILED and is not a candidate.)

The served artifact (ml/served/ml_decision_entry_v1/model.json, trained to 2025-09-22) is scored, unchanged, on the held-out
year 2025-10-01 .. 2026-09-30 of its own frozen-60 population (ml_decision_entry.build_table, the c692-01 recipe's table).
Every number that shapes a filter is fixed on DEV rows only (ts < HOLDOUT_START) before the read is claimed:
  vol24 cut = the 1/3 quantile of dev vol24 (label-free); k = median over dev rows of mean(cost_long, cost_short) x atr_pct.
The read is CLAIMED in the holdout ledger (holdout_lock.claim_read) BEFORE any held-out outcome is touched, and graded on the
deflated bar that claim returns (HOLDOUT-DEFLATED-REUSE, operator 2026-11-05).

Arms (one-position-per-symbol policy, ml_decision_entry.policy, at the artifact's tau): base (v1 as served), V (vol24 abstain),
G (cost gate), VG (both). VG is the graded arm; V and G are reported, never graded. An abstained bar frees the symbol, as in the
dev runs. Writes <out>/filters_read.json + <out>/verdict.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]

UNIT = "RQ-20261115-a474-04"
MODEL_ID = "ENTRY-v1-frozen-vol24abstain-gate006"
WINDOW = ("2025-10-01", "2026-09-30")
HOLD_END_EXCL = "2026-10-01"
TRAIN_END = "2025-09-22"
GATE = 0.06
ABSTAIN = -9.0
TRADED = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]


def masks(vol24, atr_pct, vol_cut: float, k_cost: float):
    """(abstain_vol, abstain_gate) boolean arrays. A NaN input abstains nothing on that filter (never a silent trade change)."""
    import numpy as np
    v, a = np.asarray(vol24, float), np.asarray(atr_pct, float)
    av = np.where(np.isnan(v), False, v <= vol_cut)
    with np.errstate(divide="ignore", invalid="ignore"):
        est = k_cost / a
    ag = np.where(np.isnan(est), False, est > GATE)
    return av, ag


def decide(vg: Dict[str, Any], base: Dict[str, Any], bar: Dict[str, Any], n_floor: int, sym_floor: int) -> Dict[str, Any]:
    """The registered rule. (a) VG n >= n_floor and n_symbols >= sym_floor, else INDETERMINATE; (b) VG mean clears the
    deflated point bar (holdout_lock.point_ok); (c) VG mean >= base mean. PASS iff (a) and (b) and (c); FAIL otherwise."""
    import holdout_lock
    a = (vg.get("n") or 0) >= n_floor and (vg.get("n_symbols") or 0) >= sym_floor
    b = holdout_lock.point_ok(vg.get("mean_net_r"), vg.get("se_net_r"), bar)
    c = vg.get("mean_net_r") is not None and base.get("mean_net_r") is not None and vg["mean_net_r"] >= base["mean_net_r"]
    v = "indeterminate" if not a else ("pass" if (b and c) else "fail")
    return {"verdict": v, "conditions": {"a_n_and_symbols": a, "b_deflated_point_bar": b, "c_ge_base": c}}


def run(out: Path, cache: Path, reader: str, ledger: Optional[Path]) -> int:
    import lightgbm as lgb
    import numpy as np
    import pandas as pd
    import holdout_lock
    import ml_decision_entry as E
    out.mkdir(parents=True, exist_ok=True)
    try:
        art = json.loads((REPO / "ml/served/ml_decision_entry_v1/model.json").read_text())
        syms = E.universe()
        E.fetch(cache, syms)
        tab = E.build_table(cache, syms)
        tab["ts"] = pd.to_datetime(tab["ts"], utc=True)
        hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
        dev = tab[tab.ts < hs]
        # ---- fixed on DEV rows only, label-free for the vol cut
        vol_cut = float(dev["vol24"].quantile(1 / 3))
        k_cost = float(np.nanmedian(((dev.cost_long + dev.cost_short) / 2 * dev.atr_pct).to_numpy()))
        fixed = {"vol24_cut_t0": vol_cut, "k_cost_x_atr": k_cost, "gate": GATE, "tau": float(art["tau"]),
                 "dev_rows": int(len(dev)), "artifact": "ml/served/ml_decision_entry_v1/model.json"}
        # ---- the claim comes BEFORE any held-out outcome is touched
        kw = {"train_end": TRAIN_END}
        claim = (holdout_lock.claim_read(MODEL_ID, WINDOW[0], WINDOW[1], UNIT, reader, ledger, **kw) if ledger
                 else holdout_lock.claim_read(MODEL_ID, WINDOW[0], WINDOW[1], UNIT, reader, **kw))
        (out / "holdout_claim.json").write_text(json.dumps(claim, indent=1))
        test = tab[(tab.ts >= hs) & (tab.ts < pd.Timestamp(HOLD_END_EXCL, tz="UTC"))].reset_index(drop=True)
        bl = lgb.Booster(model_str=art["booster_txt"]["long"])
        bs = lgb.Booster(model_str=art["booster_txt"]["short"])
        # provenance: predict — the served ENTRY regressors' net R per side (the artifact ml_entry serves)
        pl0, ps0 = bl.predict(test[art["features"]]), bs.predict(test[art["features"]])
        av, ag = masks(test["vol24"], test["atr_pct"], vol_cut, k_cost)
        arms = {"base": np.zeros(len(test), bool), "V": av, "G": ag, "VG": av | ag}
        res: Dict[str, Any] = {"unit": UNIT, "model_id": MODEL_ID, "window": list(WINDOW), "fixed_on_dev": fixed,
                               "holdout_lock": claim, "n_test_rows": int(len(test)), "test_symbols": int(test.symbol.nunique()),
                               "abstain_share": {k: float(m.mean()) for k, m in arms.items()}, "arms": {}, "arms_traded5": {}}
        for name, m in arms.items():
            pl, ps = pl0.copy(), ps0.copy()
            pl[m], ps[m] = ABSTAIN, ABSTAIN
            taken = E.policy(test, pl, ps, float(art["tau"]))
            res["arms"][name] = E.summarize(taken)
            res["arms_traded5"][name] = E.summarize(taken[taken.symbol.isin(TRADED)])
        v = decide(res["arms"]["VG"], res["arms"]["base"], claim["bar"], E.N_FLOOR, E.SYMBOL_FLOOR)
        res.update(v)
        vg, b = res["arms"]["VG"], res["arms"]["base"]
        note = (f"{v['verdict']}: VG mean {vg.get('mean_net_r')} (n {vg.get('n')}, se {vg.get('se_net_r')}) vs base "
                f"{b.get('mean_net_r')} (n {b.get('n')}); deflated bar n_tries {claim['bar']['n_tries']} point_t_min "
                f"{claim['bar']['point_t_min']}; conditions {v['conditions']}")
        res["note"] = note
        (out / "filters_read.json").write_text(json.dumps(res, indent=1, default=str))
        (out / "verdict.json").write_text(json.dumps({
            "verdict": v["verdict"], "read_state": "measured",
            "population": (f"served ENTRY v1 (frozen) on its frozen-60 population, held-out {WINDOW[0]}..{WINDOW[1]}; VG = vol24 "
                           f"low-tercile abstention + cost gate {GATE}; graded on the deflated bar of read {claim['bar']['n_tries']}"),
            "n": vg.get("n"), "measurement": res, "note": note}, default=str))
        print("VERDICT", note, flush=True)
        return 0
    except Exception as exc:  # allow-silent: landed as read_state=producer_failed with the reason in verdict.json
        (out / "verdict.json").write_text(json.dumps({"verdict": "not_applicable", "read_state": "producer_failed",
                                                      "population": "served ENTRY v1 held-out year", "n": None,
                                                      "note": f"{type(exc).__name__}: {exc}"}))
        raise


def _self_test() -> None:
    import numpy as np
    av, ag = masks([0.01, 0.05, np.nan], [0.02, 0.005, 0.01], vol_cut=0.02, k_cost=0.0006)
    assert av.tolist() == [True, False, False], av            # NaN vol abstains nothing
    assert ag.tolist() == [False, True, False], ag            # est 0.03 / 0.12 / 0.06 (not > 0.06)
    bar1 = {"point_t_min": 0.0}
    bar12 = {"point_t_min": 1.6648}
    vg = {"n": 500, "n_symbols": 30, "mean_net_r": 0.03, "se_net_r": 0.01}
    assert decide(vg, {"mean_net_r": 0.02}, bar12, 300, 10)["verdict"] == "pass"
    assert decide({**vg, "mean_net_r": 0.015}, {"mean_net_r": 0.01}, bar12, 300, 10)["verdict"] == "fail"  # under 1.66 se
    assert decide(vg, {"mean_net_r": 0.04}, bar1, 300, 10)["verdict"] == "fail"                        # below base
    assert decide({**vg, "n": 200}, {"mean_net_r": 0.0}, bar1, 300, 10)["verdict"] == "indeterminate"
    print("self-test ok")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/tmp/ml_entry_v1_filters")
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--reader", default="research-script-run (claimed on the runner before any held-out outcome)")
    ap.add_argument("--ledger", default=None, help="holdout ledger path (default: holdout_lock's committed ledger)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(Path(a.out), Path(a.cache), a.reader, Path(a.ledger) if a.ledger else None)


if __name__ == "__main__":
    sys.exit(main())
