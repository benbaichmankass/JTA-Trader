#!/usr/bin/env python3
# wiring: .github/workflows/ml-entry-retrain.yml (runs after the retrain step); rule docs/research/ml-entry-promotion-rule-2026-11-06.md
"""Grade the weekly ENTRY candidate against the served artifact under the REGISTERED rule RULE-ENTRY-PROMOTE-20261106.

Tier 1 grading (reads market bars, writes an evidence record and, only on a PASS, a candidate directory in ``--out``). It never
touches ``ml/served``; the workflow turns a PASS into a DRAFT PR and a human merges it. Rule text, fixed BEFORE the first run:
``docs/research/ml-entry-promotion-rule-2026-11-06.md`` (its sha256 is stamped on every record).

  1. The candidate is the registered recipe refit AS OF ``S = run_date - window_days`` (``ml_decision_entry.purge_train``: rows before
     S minus 7 d minus 25 h), tau carried from the served artifact. A refit is NOT bit-reproducible
     (measured 2026-11-06, run 42250040398: ``refit_reproduces_retrain_candidate`` false), so what is graded is what is promoted: on a
     PASS the exact boosters that were scored are the ones written to ``--out/promote``. ``--candidate-json`` (today's retrain output)
     is refit as of ``run_date`` and compared to record whether the refit reproduces it.
  2. The window ``[S, run_date - 1]`` starts after the candidate's training data. The read is CLAIMED in the holdout ledger before
     any window outcome is scored, which fixes the deflated bar.
  3. Candidate and served score the SAME rows with the registered policy; net R is ``ml_decision_entry.label_symbol`` (the full cost
     stack: fee 11 bps, slippage 3 bps, funding 1 bps per 8 h window).
  4. PASS iff n >= 300 on >= 10 symbols AND candidate mean net R clears the deflated point bar AND candidate mean >= served mean.
     Under the floor -> ``insufficient_n``; otherwise ``fail``. The deflated CI lower bound is REPORTED, not gating (the registered
     c692-01 rule is a point bar).

  python3 scripts/research/ml_entry_candidate_grade.py run --cache DIR --out DIR [--run-date YYYY-MM-DD] [--candidate-json F]
  python3 scripts/research/ml_entry_candidate_grade.py --self-test

Exit 0 on pass, 1 on fail / insufficient_n / error (the run is then the ONE red flag; the served model keeps trading).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_decision_entry as E  # noqa: E402
import holdout_lock as HL  # noqa: E402
from src.runtime.ml_entry_served import served_artifact  # noqa: E402

RULE_ID = "RULE-ENTRY-PROMOTE-20261106"
RULE_DOC = REPO / "docs/research/ml-entry-promotion-rule-2026-11-06.md"
WINDOW_DAYS = 14
FAMILY = "ENTRY"


def plan(run_date: date, window_days: int = WINDOW_DAYS) -> dict:
    s = run_date - timedelta(days=window_days)
    return {"run_date": run_date.isoformat(), "asof": s.isoformat(), "window_start": s.isoformat(),
            "window_end": (run_date - timedelta(days=1)).isoformat(), "window_days": window_days}


def _read_tab(cache: Path):
    return E.build_table(cache, E.universe())


def hourly_gaps(ts) -> list:
    """[{after, before}] for every step in an hourly bar series longer than 1 h."""
    import pandas as pd
    t = ts.reset_index(drop=True)
    return [{"after": str(t[i - 1]), "before": str(t[i])} for i in (t.diff() > pd.Timedelta(hours=1))[lambda m: m].index]


def rule_verdict(cand: dict, served: dict, bar: dict) -> tuple[str, list[str]]:
    """The registered rule on two ``summarize`` dicts and the claimed bar. Pure, so the self-test can drive every branch."""
    n, ns, mean = cand.get("n", 0), cand.get("n_symbols", 0), cand.get("mean_net_r")
    if n < E.N_FLOOR or ns < E.SYMBOL_FLOOR:
        return "insufficient_n", [f"candidate n={n} (floor {E.N_FLOOR}) / symbols={ns} (floor {E.SYMBOL_FLOOR})"]
    why, ok = [], True
    if HL.point_ok(mean, cand.get("se_net_r"), bar):
        why.append(f"clears the deflated point bar: mean {mean:+.4f} at read {bar['n_tries']} (point_t_min {bar['point_t_min']})")
    else:
        ok = False
        why.append(f"below the deflated point bar: mean {mean:+.4f} < {bar['point_t_min']} x se {cand.get('se_net_r')} (read {bar['n_tries']})")
    sm = served.get("mean_net_r")
    if sm is None:
        why.append("served artifact took no decisions on this window: non-inferiority not binding")
    elif mean >= sm:
        why.append(f"not worse than served: {mean:+.4f} >= {sm:+.4f} (served n={served.get('n')})")
    else:
        ok = False
        why.append(f"worse than served: {mean:+.4f} < {sm:+.4f} (served n={served.get('n')})")
    return ("pass" if ok else "fail"), why


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fit(tab, asof: date):
    import pandas as pd
    start = pd.Timestamp(asof.isoformat(), tz="UTC")
    train = E.purge_train(tab[tab.ts < start], start)
    if len(train) < 100_000:
        raise RuntimeError(f"degenerate training table: {len(train)} rows")
    return train, E.fit_models(train)


def _score(models, test, tau):
    # provenance: predict — LGBMRegressor / Booster .predict is the regressed net R of that side (the quantity policy() thresholds at tau), not a probability
    pl, ps = models["long"].predict(test[E.FEATURES]), models["short"].predict(test[E.FEATURES])
    return E.policy(test, pl, ps, tau)


def run(a) -> int:
    import pandas as pd
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    run_date = date.fromisoformat(a.run_date) if a.run_date else datetime.now(timezone.utc).date()
    p = plan(run_date, a.window_days)
    served_path = served_artifact()
    served_meta, served_boost = E._frozen_models(served_path)
    tau = served_meta["tau"]
    ev = {"rule_id": RULE_ID, "rule_doc_sha256": _sha(RULE_DOC), "plan": p, "tau": tau,
          "served": {"path": str(served_path.relative_to(REPO)), "model_id": served_meta.get("model_id"),
                     "train_end_exclusive": served_meta.get("train_end_exclusive")},
          "cost_stack": "ml_decision_entry.label_symbol net R: fee 11.0 bps rt + slippage 3.0 bps + funding 1.0 bps/8h (src/runtime/execution_costs)",
          "read_state": "error"}
    try:
        tab = _read_tab(Path(a.cache))
        # diagnostics for the train_end vs plan-bound gap: what the labelled table actually holds near its tail
        day = tab.ts.dt.strftime("%Y-%m-%d").value_counts().sort_index()
        last_by_sym = tab.groupby("symbol").ts.max()
        ev["diagnostics"] = {
            "table_rows": int(len(tab)), "table_max_ts": str(tab.ts.max()),
            "rows_per_day_last_14": {k: int(v) for k, v in day.tail(14).items()},
            "last_labelled_ts_by_symbol": {"min": str(last_by_sym.min()), "median": str(last_by_sym.sort_values().iloc[len(last_by_sym) // 2]),
                                           "max": str(last_by_sym.max()), "n_symbols": int(len(last_by_sym))},
            "plan_train_end_bound_for_run_date": str(pd.Timestamp(p["run_date"], tz="UTC") - pd.Timedelta(days=E.EMBARGO_DAYS)
                                                     - pd.Timedelta(hours=E.HORIZON_H + 1))}
        # a decision row needs 24 contiguous forward bars, so a bar hole removes the decisions before it: record the hourly gaps
        try:
            ev["diagnostics"]["bar_gaps_last_30d"] = {sym: hourly_gaps(pd.read_pickle(Path(a.cache) / f"{sym}.pkl")["ts"].tail(24 * 30))
                                                      for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        except Exception as exc:  # noqa: BLE001  # allow-silent: a diagnostic; its own failure is recorded in the evidence, never fatal
            ev["diagnostics"]["bar_gaps_last_30d"] = f"unreadable: {type(exc).__name__}: {exc}"[:200]
        # (a) today's retrain candidate has no clean window under the registered embargo: its window would start at run_date
        today_start = pd.Timestamp(p["run_date"], tz="UTC")
        ev["today_candidate"] = {"window_start": p["run_date"], "labelled_rows_in_window": int((tab.ts >= today_start).sum()),
                                 "verdict": "insufficient_n" if int((tab.ts >= today_start).sum()) < E.N_FLOOR else "gradable"}
        if a.candidate_json and Path(a.candidate_json).exists():
            _, m_today = _fit(tab, run_date)
            retrain = json.loads(Path(a.candidate_json).read_text())["booster_txt"]
            same = all(m_today[s].booster_.model_to_string() == retrain[s] for s in ("long", "short"))
            ev["refit_reproduces_retrain_candidate"] = bool(same)
            ev["today_candidate"]["candidate_json_sha256"] = _sha(Path(a.candidate_json))
        # (b) the graded candidate: refit as of S, window [S, run_date-1]
        asof = date.fromisoformat(p["asof"])
        train, models = _fit(tab, asof)
        train_end = str(train.ts.max())
        ev["candidate"] = {"asof": p["asof"], "train_rows": int(len(train)), "train_end_exclusive": train_end}
        start, end = p["window_start"], p["window_end"]
        test = tab[(tab.ts >= pd.Timestamp(start, tz="UTC")) & (tab.ts < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))]
        ev["window_rows"] = int(len(test))
        model_id = f"ENTRY-v1-cand-asof-{p['asof']}"
        claim = HL.claim_read(model_id, start, end, "ml-entry-retrain-grade", f"workflow ml-entry-retrain / {RULE_ID}",
                              ledger=Path(a.ledger) if a.ledger else HL.LEDGER, train_end=train_end[:10], family=FAMILY)
        bar = claim["bar"]
        ev["holdout_claim"] = {k: claim[k] for k in ("model_id", "family", "start", "end", "train_end", "n_tries", "variants_on_window", "read_at")}
        ev["bar"] = bar
        cand = E.summarize(_score(models, test, tau)) if len(test) else {"n": 0, "mean_net_r": None}
        sp = {s: served_boost[s] for s in ("long", "short")}
        served = E.summarize(_score(sp, test, tau)) if len(test) else {"n": 0, "mean_net_r": None}
        for d in (cand, served):
            d.pop("by_month", None)
        if cand.get("mean_net_r") is not None and cand.get("se_net_r"):
            cand["deflated_ci_lower_reported_not_gating"] = HL.ci_lower(cand["mean_net_r"], cand["se_net_r"], bar)
        ev["candidate"]["result"], ev["served"]["result"] = cand, served
        verdict, why = rule_verdict(cand, served, bar)
        ev.update(verdict=verdict, why=why, read_state="measured")
        if verdict == "pass":
            tag = run_date.strftime("%Y%m%d")
            d = out / "promote" / f"ml_decision_entry_v1r{tag}"
            d.mkdir(parents=True, exist_ok=True)
            art = {k: v for k, v in served_meta.items() if k not in ("booster_txt", "evidence", "provenance", "pooled_heldout_mean_net_r")}
            art.update({"model_id": f"ml-decision-entry-v1r{tag}", "candidate": False, "train_rows": int(len(train)),
                        "train_end_exclusive": train_end, "data_through": p["window_end"], "git_sha": E._git_sha(),
                        "recipe_sha": hashlib.sha256(json.dumps({"f": E.FEATURES, "l": E.LGB_PARAMS}, sort_keys=True).encode()).hexdigest()[:16],
                        "evidence": [f"{RULE_ID} grade run (see grade_evidence.json beside this PR)"],
                        "provenance": f"RUNNER-BUILT refit as of {p['asof']} by scripts/research/ml_entry_candidate_grade.py; graded on "
                                      f"{start}..{end}: n {cand['n']}, mean net R {cand['mean_net_r']:+.4f} vs served {served.get('mean_net_r')}",
                        "booster_txt": {s: models[s].booster_.model_to_string() for s in ("long", "short")}})
            (d / "model.json").write_text(json.dumps(art, indent=1, default=str) + "\n")
            ev["promote_dir"] = d.name
        (out / "grade_evidence.json").write_text(json.dumps(ev, indent=1, default=str) + "\n")
        print(f"{RULE_ID}: {verdict} | window {start}..{end} | candidate n={cand.get('n')} mean={cand.get('mean_net_r')} | "
              f"served n={served.get('n')} mean={served.get('mean_net_r')} | read {bar['n_tries']} | " + "; ".join(why), flush=True)
        return 0 if verdict == "pass" else 1
    except Exception as exc:  # noqa: BLE001  # allow-silent: not silent; writes the evidence record (error + why) and exits 1 so the run is the one red flag
        ev["error"] = f"{type(exc).__name__}: {exc}"[:500]
        (out / "grade_evidence.json").write_text(json.dumps(ev, indent=1, default=str) + "\n")
        print(f"GRADE ERROR (served model kept): {ev['error']}", file=sys.stderr, flush=True)
        return 1


def _self_test() -> None:
    p = plan(date(2026, 11, 8))
    assert p["asof"] == "2026-10-25" and p["window_end"] == "2026-11-07", p
    b1, b5 = HL.bar_for(1), HL.bar_for(5)
    good = {"n": 400, "n_symbols": 30, "mean_net_r": 0.05, "se_net_r": 0.04}
    served_ok = {"n": 380, "mean_net_r": 0.01}
    assert rule_verdict(good, served_ok, b1)[0] == "pass"
    assert rule_verdict({**good, "n": 299}, served_ok, b1)[0] == "insufficient_n"
    assert rule_verdict({**good, "n_symbols": 9}, served_ok, b1)[0] == "insufficient_n"
    assert rule_verdict({**good, "mean_net_r": -0.01}, served_ok, b1)[0] == "fail"
    assert rule_verdict(good, {"n": 380, "mean_net_r": 0.06}, b1)[0] == "fail"          # worse than served
    assert rule_verdict(good, served_ok, b5)[0] == "pass"                              # 0.05 >= 1.19 x 0.04 = 0.0476
    assert rule_verdict({**good, "se_net_r": 0.05}, served_ok, b5)[0] == "fail"        # 0.05 < 1.19 x 0.05 at the 5th read
    assert rule_verdict(good, {"n": 0, "mean_net_r": None}, b1)[0] == "pass"
    import pandas as pd
    t = pd.Series(pd.date_range("2026-10-27", periods=6, freq="h", tz="UTC")).drop([2, 3])
    assert hourly_gaps(t) == [{"after": "2026-10-27 01:00:00+00:00", "before": "2026-10-27 04:00:00+00:00"}], hourly_gaps(t)
    assert hourly_gaps(pd.Series(pd.date_range("2026-10-27", periods=4, freq="h", tz="UTC"))) == []
    print("ml_entry_candidate_grade self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--cache", default="/tmp/ml_entry_klines")
    ap.add_argument("--out", default="/tmp/ml_entry_grade_out")
    ap.add_argument("--run-date", default="")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--candidate-json", default="")
    ap.add_argument("--ledger", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
