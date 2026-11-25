#!/usr/bin/env python3
# wiring: .github/workflows/am-action-value.yml (plan -> label shards -> fit -> policy shards -> reduce/grade); research/queue/RQ-20261124-c7e3-0{1..4}.yaml; tests/test_am_action_value.py
"""AM v2 STAGE B ITERATION 2: ACTION-VALUE policies. The heads stop choosing actions on raw probabilities; a regressor of the action's OWN realised net
value (E[R | act] - E[R | hold], net of the full cost stack) chooses, and the policy acts only where that expected value is positive.

Tier 1 research tooling. Reads the committed trade corpus + keyless Binance Vision bars + the Stage-B heads (``am_heads_fit.py dump``); writes only
``--out``. No served model, no order path, no config.

WHY (the diagnosis that authored this, RQ-20261124-b5a1-01..05 + ``am_policy_diag.py``): the Stage-A heads have skill, but the Stage-B policy mapped
skill to action by fixed probability cuts, never by the action's value. Tighten fired only where P(stop_first) was high, i.e. where the trade is already
deep under water (open_r ~ -0.7) and a half-way move is worth almost nothing while still killing the third that recover; random timing fired it in
profitable states too, where the same move locks gains. Bank re-placed a resting limit at close + Q50 on every 0.1 R move (~15 orders a trade), so it
chased price down and filled on bounces. Neither rule ever asked "is THIS action worth more than holding, here, after cost?". That question is a
regression target that can be measured directly on the replay, so this driver measures it and learns it.

STAGES
  label   For every replayable trade entering 2022-01-01..2025-12-31 (dev only; no holdout trade is labelled), up to ROWS_PER_TRADE decision rows are
          drawn (seeded by the trade key) and EVERY menu action is replayed alone from that row (placed once at the row's close, never re-placed): the
          label is that arm's net R minus HOLD's net R, the engine's own net_of (fee + exit slippage + funding). Ineligible (row, action) cells are NaN.
  fit     Per test fold of the heads (half-years 2022-07.. plus the 2026 holdout fold), one LightGBM regressor per action on the label rows of trades
          whose label window ends EMBARGO_DAYS before the fold (the holdout fold: before HOLDOUT_TRAIN_END), labels winsorised to +-LABEL_CAP_R, fixed
          params and seed. The ``family`` class fits one regressor per (family, action). Score cuts: none; the rule is the sign of the expected value.
  shard   The policy arm per class on the same replay as am_policy_arm (HOLD = replayed_actual byte for byte). At each decision row (the unmanaged trade's
          open rows, features from bars <= k) the class's eligible actions are scored; the policy fires the FIRST row where the best predicted value
          exceeds EV_MARGIN_R, takes that action once, and does nothing else on that trade. Control (R4): N_CONTROL seeded draws, each the SAME action
          kind placed once at a uniformly drawn row where that action is eligible (same count, same kind, same level rule; no timing information).
  reduce  am_policy_arm's books and RULE-AM-RISK-ADJUSTED-V1 grade (V1 params unchanged) on DEV and the claimed HOLDOUT; PASS iff both pass R1-R4.

CLASSES (fixed before the first run)
  av_bank     menu {bank_q50, bank_1r, bank_2r}: one resting 50% partial limit at close+max(Q50,0.25R) / entry+1R / entry+2R (the fixed levels only
              while the close is at least TP_MIN_DIST_R below them). The value model chooses the level or skips.
  av_tighten  menu {tighten_half, breakeven, lock_half}: stop half-way from the original stop to the close / to entry (open_r >= 0.5) / to entry +
              half the open profit (open_r >= 1.0). ``set_stop`` only tightens.
  av_loosen   menu {loosen_struct}, ELIGIBLE only where the dip head says the dip recovers (P(dip_recovers) >= the fold's training p90, as Stage B)
              AND a structure level exists; the value model must also say it pays. Loosen was the one class better than HOLD on the holdout.
  av_family   the union menu (all seven actions), one value model per (strategy family, action): trend / pullback / scalp / breakout / other.

ITERATION 3 CLASSES (RQ-20261125-c7e3-05..07; diagnosis: scripts/research/am_av_fire_timing.py on a9d2-02 -- the av policies fired at the FIRST
decision bar on 87% of trades, the eventual winners were cut there, and a uniform placement of the same tighten beat HOLD)
  mf_tighten_random  MODEL-FREE: tighten_half once at a uniformly drawn eligible row (seeded by the trade key). No control (it IS a uniform draw);
                     graded on R1-R3 vs HOLD only (``r123_segment``).
  mf_tighten_fixed   MODEL-FREE: tighten_half once at the first eligible row aged >= MIN_AGE_K bars. Control: tighten_half at a uniform eligible row.
  av_tighten_late    the av_tighten value models with the first crossing allowed only from MIN_AGE_K. Control: the same kind at a uniform eligible
                     row aged >= MIN_AGE_K (does the model's choice beat random timing INSIDE the late window?).

  python3 scripts/research/am_action_value.py label  --run-id ID --out DIR --heads DIR --index I [I ...]
  python3 scripts/research/am_action_value.py fit    --labels DIR --heads DIR --out DIR
  python3 scripts/research/am_action_value.py shard  --run-id ID --out DIR --heads DIR --av DIR --index I [I ...] --classes av_bank
  python3 scripts/research/am_action_value.py reduce --out DIR --classes av_bank --unit RQ-... --reader '...'
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import am_policy_arm as P  # noqa: E402
import cf_bars  # noqa: E402
import cf_bulk  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "am_action_value/1"
RULE_ID = "RULE-AM-ACTION-VALUE-20261124"
RULE_ID_R123 = "RULE-AM-MF-RANDOM-TIGHTEN-20261125"   # mf_tighten_random: V1 R1-R3 vs HOLD, R4 not a clause (RQ-20261125-c7e3-05)
ACTIONS = ("bank_now", "bank_q50", "bank_1r", "bank_2r", "tighten_half", "breakeven", "lock_half", "loosen_struct")
CLASS_MENU = {"av_bank": ("bank_now", "bank_q50", "bank_1r", "bank_2r"), "av_tighten": ("tighten_half", "breakeven", "lock_half"),
              "av_loosen": ("loosen_struct",), "av_family": ACTIONS,
              # ITERATION 3 (RQ-20261125-c7e3-05..07, row AM-V2-STAGE-B-POLICY-ARM): the av policies fired at the FIRST decision bar on 87% of
              # trades (optional stopping over noisy per-bar values) and cut the eventual winners; uniform placement of the same tighten beat HOLD.
              "mf_tighten_random": ("tighten_half",),     # MODEL-FREE: tighten_half once at a uniformly drawn eligible row (the winning control, standalone)
              "mf_tighten_fixed": ("tighten_half",),      # MODEL-FREE: tighten_half once at the first eligible row aged >= MIN_AGE_K bars
              "av_tighten_late": ("tighten_half", "breakeven", "lock_half"),   # the av_tighten value models, first crossing only from MIN_AGE_K
              # ITERATION 4 (RQ-20261125-c7e3-08/09): CAUSAL draws. The iteration-2/3 controls and mf_tighten_random drew from decision rows that
              # stop at the ACTUAL exit, i.e. with the trade's future length known. These draw an age at ENTRY from U{1..hz_bars} (the leg's harness
              # horizon in bars) and do nothing if the trade has already closed by that age.
              "mf_tighten_causal": ("tighten_half",),     # MODEL-FREE: tighten_half once at a causally drawn age (fair version of mf_tighten_random)
              "mf_tighten_fixed_cc": ("tighten_half",)}   # mf_tighten_fixed's policy, graded against the CAUSAL control
CLASSES = tuple(CLASS_MENU)
#: classes that consult no value model (they still replay only trades in a fold with one, so the population equals the av units')
MODEL_FREE = ("mf_tighten_random", "mf_tighten_fixed", "mf_tighten_causal", "mf_tighten_fixed_cc")
#: classes whose R4 control (if any) is the CAUSAL age draw, not the uniform draw over the realised rows
CAUSAL_CONTROL = ("mf_tighten_fixed_cc",)
#: the age floor (decision rows are bars since fill, k = 1, 2, ...) for mf_tighten_fixed and av_tighten_late; FIXED before any run
#: (RQ-20261125-c7e3-06/07). Basis: the a9d2-02 fire-timing read put the av fires' gain at k / bars_held >= 0.1; the median HOLD path is 22 bars.
MIN_AGE_K = 5
#: the value-model menu whose fold coverage defines the replayed population of each class (model-free classes use av_tighten's)
VM_MENU = {**{c: CLASS_MENU[c] for c in ("av_bank", "av_tighten", "av_loosen", "av_family")},
           "mf_tighten_random": CLASS_MENU["av_tighten"], "mf_tighten_fixed": CLASS_MENU["av_tighten"], "av_tighten_late": CLASS_MENU["av_tighten"],
           "mf_tighten_causal": CLASS_MENU["av_tighten"], "mf_tighten_fixed_cc": CLASS_MENU["av_tighten"]}
FAMILIES = ("trend", "pullback", "scalp", "breakout", "other")
ROWS_PER_TRADE = 8
BANK_FRAC = 0.5
LABEL_CAP_R = 3.0
EV_MARGIN_R = 0.0
EV_CUT_PCT = 75            # act only where the predicted value is >= the TRAINING p75 of that action's predicted value (and > EV_MARGIN_R)
EMBARGO_DAYS = 7
MIN_TRAIN_ROWS = 20000
ROWS_PER_FIT = 300000
SEED = 20261124
N_CONTROL = 100
EXTRA_HEADS = ("reach_1", "reach_2")
AV_EXTRA = ["q50", "q90", "reach_1", "reach_2", "p_stop", "p_dip", "struct_gap_r", "tp_gap_r"]
AV_FEATS = P.HEAD_FEATS + AV_EXTRA
AV_FEATS_RICH = P.RICH_HEAD_FEATS + AV_EXTRA     # rich heads (RQ-20261124-a9d2-01): the head feature block carries the 6 ctx columns too


def av_feats_for(head_feats) -> list:
    """The value models' feature list for a heads manifest's ``feats`` (base or rich)."""
    return list(head_feats) + AV_EXTRA
LGB = {"objective": "huber", "alpha": 1.0, "n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 2000, "subsample": 0.7,
       "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0, "random_state": SEED, "deterministic": True, "force_row_wise": True,
       "n_jobs": 4, "verbose": -1}


def family(strategy: Any) -> str:
    s = str(strategy)
    if "scalp" in s:
        return "scalp"
    if "pullback" in s:
        return "pullback"
    if "donchian" in s or "trend" in s:
        return "trend"
    if "breakout" in s or "squeeze" in s:
        return "breakout"
    return "other"


class Heads5(P.Heads):
    """The Stage-B heads plus the reach heads (same dump, same sha check)."""

    NEEDED = P.Heads.NEEDED + EXTRA_HEADS


# ---- actions -----------------------------------------------------------------------------------------------------------
def action_spec(name: str, ctx: dict, row: dict, pr: dict) -> dict | None:
    """The single bracket action ``name`` placed at row ``row``'s close, or None where it is ineligible. ``pr`` = that row's head outputs."""
    k, o = row["k"], row["features"]["open_r"]
    ts = P._close_ts(ctx, ctx["post"], k)
    mk = lambda kind, lvl, **kw: {"ts": ts, "kind": kind, "level": P._px(ctx, lvl), "k": k, "lvl_r": lvl, **kw}  # noqa: E731
    if name == "bank_now":
        return {"ts": ts, "kind": "close", "level": None, "frac": BANK_FRAC, "k": k, "lvl_r": o}
    if name == "bank_q50":
        return mk("bank_at", o + max(pr["q50"], P.TP_MIN_DIST_R), frac=BANK_FRAC)
    if name == "bank_1r":
        return mk("bank_at", 1.0, frac=BANK_FRAC) if o <= 1.0 - P.TP_MIN_DIST_R else None
    if name == "bank_2r":
        return mk("bank_at", 2.0, frac=BANK_FRAC) if o <= 2.0 - P.TP_MIN_DIST_R else None
    if name == "tighten_half":
        return mk("set_stop", -1.0 + 0.5 * (o + 1.0))
    if name == "breakeven":
        return mk("set_stop", 0.0) if o >= 0.5 else None
    if name == "lock_half":
        return mk("set_stop", 0.5 * o) if o >= 1.0 else None
    if name == "loosen_struct":
        lvl = P.structure_level_r(ctx, k)
        return mk("loosen_stop", lvl) if lvl is not None else None
    raise ValueError(name)


def eligible(cls: str, name: str, ctx: dict, row: dict, pr: dict, thr: dict) -> dict | None:
    """The class's eligibility on top of the action's own: av_loosen also needs the dip head's Stage-B cut."""
    if cls == "av_loosen" and pr["p_dip"] < thr["dip_recovers"]["p90"]:
        return None
    return action_spec(name, ctx, row, pr)


def _act(s: dict) -> dict:
    return {"ts": s["ts"], "kind": s["kind"], "level": s["level"], **({"frac": s["frac"]} if "frac" in s else {})}


# ---- features ----------------------------------------------------------------------------------------------------------
def row_preds(pred: dict[str, Sequence[float]], i: int) -> dict:
    q50 = max(0.0, float(pred["q0.5"][i]))
    return {"q50": q50, "q90": max(q50, float(pred["q0.9"][i])), "reach_1": float(pred["reach_1"][i]), "reach_2": float(pred["reach_2"][i]),
            "p_stop": float(pred["stop_first"][i]), "p_dip": float(pred["dip_recovers"][i])}


def av_features(ctx: dict, rows: Sequence[dict], pred: dict, base_X) -> Any:
    """The value models' inputs: the head features (``base_X``, already built: 9, or 15 for rich heads), the six head outputs, and two level gaps."""
    import numpy as np
    tp0 = P._tp0_r(ctx)
    extra = []
    for i, r in enumerate(rows):
        pr = row_preds(pred, i)
        s = P.structure_level_r(ctx, r["k"])
        o = r["features"]["open_r"]
        extra.append([pr["q50"], pr["q90"], pr["reach_1"], pr["reach_2"], pr["p_stop"], pr["p_dip"],
                      (o - s) if s is not None else float("nan"), (tp0 - o) if tp0 is not None else float("nan")])
    return np.hstack([base_X, np.array(extra, dtype="float32").reshape(len(rows), 8)])


# ---- shared shard plumbing (bars, contexts, head scores) ---------------------------------------------------------------
def prepare_shard(shard: dict, chunks, jobs, heads: Heads5, keep, fetcher=None) -> tuple:
    """Fetch the shard's bars, build contexts/rows and score the heads. ``keep(job)`` filters jobs. Returns (items, reasons, state, err) with
    items = [key, job, ctx, rows, fold, pred, X]."""
    import numpy as np
    tf, sym = shard["timeframe"], shard["symbol"]
    chosen = [k for k in chunks[shard["shard_id"]] if keep(jobs[k])]
    reasons: Counter = Counter()
    state, err, bars = "done", None, []
    if tf is None:
        reasons["timeframe_unresolved"] = len(chosen)
    elif not cf_bulk.is_crypto(sym):
        reasons["no_bar_source"] = len(chosen)
    elif chosen:
        hz = lambda j: cf_core.resolve_horizon({"timeframe": tf}, {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for(j.get("strategy"))) else {})})["seconds"]  # noqa: E731
        try:
            sec = cf_bars.TF_SECONDS[tf]
            lo = min(lrc._ts(jobs[k]["entry_time"]) for k in chosen) - heads.pre_bars * sec
            hi = max(lrc._ts(jobs[k]["exit_time"]) + hz(jobs[k]) for k in chosen)
            bars = cf_bars.historical_bars(sym, tf, lo, hi, fetcher)
        except Exception as e:  # noqa: BLE001  # allow-silent: a failed fetch is a recorded state (no 'done' meta, so a re-run retries), never a halt
            state, err = "fetch_failed", f"{type(e).__name__}: {e}"[:300]
    store = cf_bulk.BarStore(bars) if bars else None
    if store is None and state == "done" and not reasons and chosen:
        reasons["no_bars"] = len(chosen)
    items, by_fold = [], defaultdict(list)
    for key in chosen if (store is not None and state == "done") else []:
        job = dict(jobs[key], trade_key=key)
        t_row, t_exit = lrc._ts(job["entry_time"]), lrc._ts(job["exit_time"])
        if t_row is None or t_exit is None:
            reasons["row_incomplete"] += 1
            continue
        fold = heads.fold_of(t_row)
        if fold is None:
            reasons["entry_before_first_fold"] += 1
            continue
        sec = cf_bars.TF_SECONDS[tf]
        h = cf_core.resolve_horizon({"timeframe": tf}, {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for(job.get("strategy"))) else {})})["seconds"]
        ctx = P.attach_history(P.make_ctx(job, store.window(t_row - P.PRE_BARS * sec, t_exit + h), tf), store, heads)
        if ctx is None:
            reasons["no_replay_context"] += 1
            continue
        ctx["label_end"] = t_exit + h
        ctx["hz_bars"] = max(1, int(h // sec))      # the leg's harness horizon in bars: the support of the CAUSAL age draw
        rows = P.decision_rows(ctx)
        it = [key, job, ctx, rows, fold, None, None]
        items.append(it)
        if rows:
            by_fold[fold["fold_id"]].append((it, P.feature_matrix(ctx, rows, heads.strat.get(str(job.get("strategy")), -1))))
    for fid, lst in by_fold.items():
        # provenance: predict -- Booster.predict per Stage-B head (q0.5/q0.9 remaining-MFE quantiles, reach / stop_first / dip_recovers probabilities)
        p = heads.predict(fid, np.vstack([m for _, m in lst]))
        i = 0
        for it, m in lst:
            it[5] = {h: p[h][i:i + len(m)] for h in p}
            it[6] = av_features(it[2], it[3], it[5], m)
            i += len(m)
    return items, reasons, state, err


# ---- label -------------------------------------------------------------------------------------------------------------
def label_trade(ctx: dict, rows, pred, X, rng: random.Random) -> dict | None:
    """Up to ROWS_PER_TRADE sampled rows x every action: delta = arm net R - HOLD net R (NaN where ineligible)."""
    import numpy as np
    if not rows:
        return None
    base = P.run_arm(ctx)["net_r"]
    idx = sorted(rng.sample(range(len(rows)), min(ROWS_PER_TRADE, len(rows))))
    Y = np.full((len(idx), len(ACTIONS)), np.nan, dtype="float32")
    for j, i in enumerate(idx):
        pr = row_preds(pred, i)
        for a, name in enumerate(ACTIONS):
            s = action_spec(name, ctx, rows[i], pr)
            if s is not None:
                Y[j, a] = P.run_arm(ctx, [_act(s)])["net_r"] - base
    return {"X": X[idx], "Y": Y, "k": np.array([rows[i]["k"] for i in idx], dtype="int32")}


def trade_rng(key: str, salt: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{key}|{salt}".encode()).hexdigest()[:12], 16))


def run_label_shard(shard, chunks, jobs, heads, out: Path, fetcher=None) -> dict:
    import numpy as np
    t0 = time.time()
    ldir = out / "av_labels"
    ldir.mkdir(parents=True, exist_ok=True)
    items, reasons, state, err = prepare_shard(shard, chunks, jobs, heads, lambda j: str(j.get("entry_time"))[:10] < P.DEV_END, fetcher)
    Xs, Ys, ent, end, fam, ks = [], [], [], [], [], []
    for key, job, ctx, rows, fold, pred, X in items:
        lab = label_trade(ctx, rows, pred, X, trade_rng(key, "label")) if pred is not None else None
        if lab is None:
            continue
        n = len(lab["k"])
        Xs.append(lab["X"])
        Ys.append(lab["Y"])
        ent += [ctx["t_row"]] * n
        end += [ctx["label_end"]] * n
        fam += [FAMILIES.index(family(job.get("strategy")))] * n
        ks.append(lab["k"])
    n_rows = int(sum(len(x) for x in Xs))
    if state == "done":
        np.savez_compressed(ldir / f"{shard['shard_id']}.npz", X=np.vstack(Xs) if Xs else np.zeros((0, len(av_feats_for(heads.feats))), "float32"),
                            Y=np.vstack(Ys) if Ys else np.zeros((0, len(ACTIONS)), "float32"), entry=np.array(ent, "float64"),
                            end=np.array(end, "float64"), fam=np.array(fam, "int8"), k=np.concatenate(ks) if ks else np.zeros(0, "int32"))
    meta = {**shard, "schema": SCHEMA, "stage": "label", "state": state, "error": err, "n_trades": len(items), "n_rows": n_rows,
            "could_not_replay": dict(reasons), "seconds": round(time.time() - t0, 2)}
    if state == "done":
        (ldir / f"{shard['shard_id']}.meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


# ---- fit ---------------------------------------------------------------------------------------------------------------
def load_labels(ldir: Path) -> dict:
    import numpy as np
    parts = [np.load(p) for p in sorted(Path(ldir).rglob("*.npz"))]
    if not parts:
        raise SystemExit(f"no label shards under {ldir}")
    return {k: np.concatenate([p[k] for p in parts]) for k in ("X", "Y", "entry", "end", "fam", "k")}


def _day(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def fit_one(X, y, seed_salt: str, min_rows: int = MIN_TRAIN_ROWS, feats=None):
    import lightgbm as lgb
    import numpy as np
    m = ~np.isnan(y)
    if m.sum() < min_rows:
        return None, int(m.sum()), None
    Xm, ym = X[m], np.clip(y[m], -LABEL_CAP_R, LABEL_CAP_R)
    if len(ym) > ROWS_PER_FIT:
        sel = np.random.default_rng(int(hashlib.sha256(seed_salt.encode()).hexdigest()[:8], 16)).choice(len(ym), ROWS_PER_FIT, replace=False)
        Xm, ym = Xm[sel], ym[sel]
    model = lgb.LGBMRegressor(**LGB)
    model.fit(Xm, ym, feature_name=list(feats or AV_FEATS))
    # provenance: predict -- the regressor's in-sample predicted net-R value on its own TRAINING rows, used only for the p75 action cut
    cut = max(EV_MARGIN_R, float(np.percentile(model.booster_.predict(Xm), EV_CUT_PCT)))
    return model.booster_, len(ym), (float(np.mean(ym)), cut)


def fit(labels: Path, heads_dir: Path, out: Path, min_rows: int = MIN_TRAIN_ROWS, only_fold: str | None = None) -> dict:
    import numpy as np
    d = load_labels(labels)
    man = json.loads((Path(heads_dir) / "manifest.json").read_text())
    feats = av_feats_for(man["feats"])
    if d["X"].shape[1] != len(feats):
        raise SystemExit(f"label width {d['X'].shape[1]} != {len(feats)} value features for heads feats {man['feats']}")
    out.mkdir(parents=True, exist_ok=True)
    folds = []
    for f in man["folds"]:
        if f.get("skipped") or not f.get("files") or (only_fold and f["fold_id"] != only_fold):
            continue
        a = _day(f["test_start"])
        cut = min(a, _day(P.HOLDOUT_TRAIN_END)) if f["test_start"] >= P.HOLDOUT_START else a
        tr = np.where(d["end"] < cut - EMBARGO_DAYS * 86400)[0]
        rec = {"fold_id": f["fold_id"], "test_start": f["test_start"], "test_end": f.get("test_end"), "n_train_rows": len(tr), "files": {},
               "train_mean": {}, "ev_cut": {}, "n_fit": {}}
        fdir = out / f["fold_id"]
        for scope in ["all"] + [f"fam:{x}" for x in FAMILIES]:
            sel = tr if scope == "all" else tr[d["fam"][tr] == FAMILIES.index(scope.split(":")[1])]
            for ai, name in enumerate(ACTIONS):
                bst, n, mu = fit_one(d["X"][sel], d["Y"][sel, ai], f"{f['fold_id']}|{scope}|{name}", min_rows, feats)
                tag = f"{scope}|{name}"
                rec["n_fit"][tag] = n
                if bst is None:
                    continue
                fdir.mkdir(parents=True, exist_ok=True)
                p = fdir / f"{scope.replace(':', '_')}__{name}.txt"
                bst.save_model(str(p))
                rec["files"][tag] = hashlib.sha256(p.read_bytes()).hexdigest()
                rec["train_mean"][tag] = round(mu[0], 6)
                rec["ev_cut"][tag] = round(mu[1], 6)
        folds.append(rec)
        print(json.dumps({"fold": f["fold_id"], "n_train_rows": rec["n_train_rows"], "models": len(rec["files"])}), flush=True)
    labelled = {"n_rows": len(d["entry"]), "n_cells": {a: int((~np.isnan(d["Y"][:, i])).sum()) for i, a in enumerate(ACTIONS)},
                "mean_delta": {a: (round(float(np.nanmean(d["Y"][:, i])), 6) if (~np.isnan(d["Y"][:, i])).any() else None) for i, a in enumerate(ACTIONS)}}
    manifest = {"schema": "am_action_value_dump/1", "feats": feats, "actions": list(ACTIONS), "families": list(FAMILIES), "lgb_params": LGB,
                "label_cap_r": LABEL_CAP_R, "embargo_days": EMBARGO_DAYS, "rows_per_fit": ROWS_PER_FIT, "folds": folds, "labels": labelled,
                "provenance": "ESTIMATED"}
    (out / (f"manifest_{only_fold}.json" if only_fold else "manifest.json")).write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def fit_merge(root: Path) -> dict:
    """Merge the per-fold manifests ``fit --only-fold`` wrote (one runner per fold) into manifest.json, in the heads' fold order."""
    parts = [json.loads(p.read_text()) for p in sorted(Path(root).glob("manifest_*.json"))]
    if not parts:
        raise SystemExit(f"no per-fold manifests under {root}")
    man = dict(parts[0])
    man["folds"] = sorted((f for p in parts for f in p["folds"]), key=lambda f: f["test_start"])
    (Path(root) / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    return man


class ValueModels:
    def __init__(self, root: Path):
        import lightgbm as lgb
        self.root = Path(root)
        self.man = json.loads((self.root / "manifest.json").read_text())
        if self.man.get("schema") != "am_action_value_dump/1" or list(self.man["feats"]) not in (AV_FEATS, AV_FEATS_RICH):
            raise ValueError("unexpected action-value manifest")
        self.boosters: dict[tuple, Any] = {}
        self.cuts: dict[tuple, float] = {}
        for f in self.man["folds"]:
            for tag, sha in f["files"].items():
                scope, name = tag.split("|")
                p = self.root / f["fold_id"] / f"{scope.replace(':', '_')}__{name}.txt"
                if hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                    raise ValueError(f"value model {p} does not match the manifest sha256")
                self.boosters[(f["fold_id"], scope, name)] = lgb.Booster(model_file=str(p))
                self.cuts[(f["fold_id"], scope, name)] = float(f["ev_cut"][tag])

    def has_fold(self, fold_id: str, scope: str, menu: Sequence[str]) -> bool:
        return all((fold_id, scope, a) in self.boosters for a in menu)

    def predict(self, fold_id: str, scope: str, name: str, X):
        return self.boosters[(fold_id, scope, name)].predict(X)


# ---- policy ------------------------------------------------------------------------------------------------------------
def decide_av(cls: str, ctx, rows, pred, thr, ev: dict[str, Any], cuts: dict[str, float]) -> list[dict]:
    """First row where an eligible action's predicted value clears its cut (max(EV_MARGIN_R, training p75)): the highest-value such action, once.
    ``ev[name]`` aligns with ``rows``."""
    for i, row in enumerate(rows):
        pr = row_preds(pred, i)
        best, best_v = None, None
        for name in CLASS_MENU[cls]:
            v = float(ev[name][i])
            if v > max(EV_MARGIN_R, cuts[name]) and (best_v is None or v > best_v):
                s = eligible(cls, name, ctx, row, pr, thr)
                if s is not None:
                    best, best_v = dict(s, cls=cls, name=name, ev=v), v
        if best is not None:
            return [best]
    return []


def control_av(cls: str, ctx, rows, pred, thr, spec: dict, rng: random.Random, min_k: int = 0) -> list[dict]:
    """The same action kind, placed once at a uniformly drawn row where it is eligible (same eligibility as the policy, incl. the dip cut), among
    rows aged >= ``min_k`` (av_tighten_late's control is drawn from the same late window its policy may fire in)."""
    cache = ctx.setdefault("_elig_av", {})
    ck = (spec["name"], min_k)
    el = cache.get(ck)
    if el is None:
        el = cache[ck] = [i for i, r in enumerate(rows)
                          if r["k"] >= min_k and eligible(cls, spec["name"], ctx, r, row_preds(pred, i), thr) is not None]
    if not el:
        return []
    i = rng.choice(el)
    return [eligible(cls, spec["name"], ctx, rows[i], row_preds(pred, i), thr)]


def policy_rng(key: str, cls: str) -> random.Random:
    """mf_tighten_random's own placement draw: seeded by the trade key, disjoint from every control draw (control_rng salts are 0..N_CONTROL-1)."""
    return random.Random(int(hashlib.sha256(f"{key}|{cls}|policy".encode()).hexdigest()[:12], 16))


def causal_pick(ctx: dict, rows, rng: random.Random) -> int | None:
    """An age drawn at ENTRY from U{1..hz_bars}, independent of the realised exit; the index of the decision row at that age, or None when the
    trade has already closed by then (no row carries that age)."""
    age = rng.randint(1, max(1, int(ctx.get("hz_bars") or 1)))
    return next((i for i, r in enumerate(rows) if r["k"] == age), None)


def control_causal(cls: str, ctx, rows, pred, thr, spec: dict, rng: random.Random) -> list[dict]:
    """CAUSAL control: the same action kind at a causally drawn age; nothing if the trade closed first or the action is ineligible there."""
    i = causal_pick(ctx, rows, rng)
    if i is None:
        return []
    s = eligible(cls, spec["name"], ctx, rows[i], row_preds(pred, i), thr)
    return [s] if s is not None else []


def decide_mf(cls: str, ctx, rows, pred, thr, key: str) -> list[dict]:
    """The model-free policies (no value model is read). mf_tighten_random: tighten_half once at a uniformly drawn eligible row. mf_tighten_fixed:
    tighten_half once at the first eligible row aged >= MIN_AGE_K (HOLD if the trade never reaches that age)."""
    if cls == "mf_tighten_causal":
        i = causal_pick(ctx, rows, policy_rng(key, cls))
        s = None if i is None else eligible(cls, "tighten_half", ctx, rows[i], row_preds(pred, i), thr)
        return [dict(s, cls=cls, name="tighten_half", ev=0.0)] if s is not None else []
    el = [i for i, r in enumerate(rows) if eligible(cls, "tighten_half", ctx, r, row_preds(pred, i), thr) is not None]
    if cls in ("mf_tighten_fixed", "mf_tighten_fixed_cc"):
        el = [i for i in el if rows[i]["k"] >= MIN_AGE_K][:1]
    elif cls != "mf_tighten_random":
        raise ValueError(cls)
    if not el:
        return []
    i = el[0] if cls == "mf_tighten_fixed" else policy_rng(key, cls).choice(el)
    return [dict(eligible(cls, "tighten_half", ctx, rows[i], row_preds(pred, i), thr), cls=cls, name="tighten_half", ev=0.0)]


def decide_late(cls: str, ctx, rows, pred, thr, ev: dict[str, Any], cuts: dict[str, float]) -> list[dict]:
    """av_tighten_late: decide_av restricted to rows aged >= MIN_AGE_K (the first crossing may not happen before that age); ``ev`` aligns with ``rows``."""
    idx = [i for i, r in enumerate(rows) if r["k"] >= MIN_AGE_K]
    sub_ev = {n: [ev[n][i] for i in idx] for n in ev}
    sub_pred = {h: [pred[h][i] for i in idx] for h in pred}
    return decide_av(cls, ctx, [rows[i] for i in idx], sub_pred, thr, sub_ev, cuts)


def run_policy_shard(shard, chunks, jobs, heads, vm: ValueModels, out: Path, cls: str, n_control: int = N_CONTROL, fetcher=None) -> dict:
    t0 = time.time()
    sdir = out / "am_policy"
    sdir.mkdir(parents=True, exist_ok=True)
    items, reasons, state, err = prepare_shard(shard, chunks, jobs, heads, lambda j: True, fetcher)
    menu = CLASS_MENU[cls]
    vmenu = VM_MENU[cls]
    min_k = MIN_AGE_K if cls == "av_tighten_late" else 0
    if cls in ("mf_tighten_random", "mf_tighten_causal"):
        n_control = 0           # its own placement IS a uniform draw: a uniform control would be the same distribution (R4 is not a clause)
    tmp = sdir / f"{shard['shard_id']}.jsonl.gz.tmp"
    n_rep, n_fired, kinds = 0, 0, Counter()
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for key, job, ctx, rows, fold, pred, X in items:
            scope = f"fam:{family(job.get('strategy'))}" if cls == "av_family" else "all"
            if not vm.has_fold(fold["fold_id"], scope, vmenu):
                reasons["no_value_model_for_fold"] += 1
                continue
            base = P.run_arm(ctx)
            rec = {"b": P._arm_cell(base), "a": {}}
            specs = []
            if rows and pred is not None and cls in MODEL_FREE:
                specs = decide_mf(cls, ctx, rows, pred, fold["thresholds"], key)
            elif rows and pred is not None:
                # provenance: predict -- ValueModels.predict: each action's predicted net-R value vs HOLD (E[R|act]-E[R|hold], cost included)
                ev = {name: vm.predict(fold["fold_id"], scope, name, X) for name in menu}
                cuts = {n: vm.cuts[(fold["fold_id"], scope, n)] for n in menu}
                specs = (decide_late if cls == "av_tighten_late" else decide_av)(cls, ctx, rows, pred, fold["thresholds"], ev, cuts)
            if not specs:
                rec["a"][cls] = {"n": 0}
            else:
                n_fired += 1
                kinds[specs[0]["name"]] += 1
                arm = P.run_arm(ctx, [_act(s) for s in specs])
                ctl = []
                for d in range(n_control):
                    crng = P.control_rng(ctx["key"], cls, d)
                    cs = (control_causal(cls, ctx, rows, pred, fold["thresholds"], specs[0], crng) if cls in CAUSAL_CONTROL
                          else control_av(cls, ctx, rows, pred, fold["thresholds"], specs[0], crng, min_k))
                    c = P.run_arm(ctx, [_act(s) for s in cs]) if cs else base
                    ctl.append([round(c["net_r"], 6), None if c["exit_ts"] is None else int(c["exit_ts"])])
                rec["a"][cls] = {"n": 1, "p": P._arm_cell(arm), "c": ctl, "kind": specs[0]["name"], "k": specs[0]["k"], "ev": round(specs[0]["ev"], 5)}
            n_rep += 1
            fh.write(json.dumps({"k": key, "st": job.get("strategy"), "sy": shard["symbol"], "tf": shard["timeframe"], "e": job.get("entry_time"),
                                 "f": fold["fold_id"], **rec}, separators=(",", ":"), default=str) + "\n")
    tmp.replace(sdir / f"{shard['shard_id']}.jsonl.gz")
    meta = {**shard, "schema": SCHEMA, "stage": "policy", "state": state, "error": err, "n_jobs": len(chunks[shard["shard_id"]]), "n_replayed": n_rep,
            "n_fired": n_fired, "kinds": dict(kinds), "could_not_replay": dict(reasons), "classes": [cls], "n_control": n_control,
            "seconds": round(time.time() - t0, 2), "provenance": "ESTIMATED"}
    if state == "done":
        (sdir / f"{shard['shard_id']}.meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


# ---- reduce ------------------------------------------------------------------------------------------------------------
def reduce_run(out: Path, cls: str, unit: str, reader: str, ledger: Path | None, claim: bool, n_control: int = N_CONTROL) -> dict:
    recs, metas = P.read_shards(out)
    dev = [r for r in recs if str(r["e"])[:10] < P.DEV_END]
    hold = [r for r in recs if str(r["e"])[:10] >= P.HOLDOUT_START]
    claim_rec = None
    if claim:
        import holdout_lock
        end_day = max((str(r["e"])[:10] for r in recs), default=P.HOLDOUT_START)
        claim_rec = holdout_lock.claim_read(f"AM-HEADS-av-{cls}", P.HOLDOUT_START, max(end_day, P.HOLDOUT_START), unit, reader,
                                            ledger or holdout_lock.LEDGER, train_end=P.HOLDOUT_TRAIN_END, family="AM-HEADS")
        (out / "holdout_claims.jsonl").write_text(json.dumps(claim_rec) + "\n")
    if cls in ("mf_tighten_random", "mf_tighten_causal"):
        n_control = 0
    seg_dev = P._segment(dev, cls, n_control)
    seg_hold = P._segment(hold, cls, n_control)
    if cls in ("mf_tighten_random", "mf_tighten_causal"):
        seg_dev, seg_hold = r123_segment(seg_dev), r123_segment(seg_hold)
    verdict = P.unit_verdict(seg_dev, seg_hold)
    cuts = {"family": P._cuts(dev + hold, cls, lambda r: family(r["st"]), 500), "strategy": P._cuts(dev + hold, cls, lambda r: str(r["st"]), 500),
            "timeframe": P._cuts(dev + hold, cls, lambda r: str(r["tf"]), 500)}
    fired = [r["a"].get(cls, {"n": 0}) for r in recs]
    kinds = Counter(c.get("kind") for c in fired if c["n"])
    could = Counter()
    for m in metas:
        could.update(m.get("could_not_replay") or {})
    pop = (f"{len(recs)} replayed backtest trades (run-w corpus sha 1eb164f4, crypto legs with Binance Vision bars, entry in a fold with a value model, "
           f"i.e. 2022-07-01..end): {len(dev)} dev (entry < {P.DEV_END}), {len(hold)} claimed holdout; arm {cls} vs HOLD (replayed_actual) and "
           f"{n_control} matched random re-timings of the same action; R in the original stop distance, full cost stack; per-trade-R SCREEN")
    return {"schema": SCHEMA, "rule_id": RULE_ID_R123 if cls in ("mf_tighten_random", "mf_tighten_causal") else RULE_ID, "unit": unit, "class": cls, "verdict": verdict, "read_state": "measured", "n": len(recs),
            "population": pop, "dev": seg_dev, "holdout": seg_hold,
            "lever": {"trades_fired": sum(1 for c in fired if c["n"]), "share_fired": round(sum(1 for c in fired if c["n"]) / len(recs), 4) if recs else None,
                      "kinds": dict(kinds)},
            "could_not_replay": dict(could), "n_shards": len(metas), "reported_cuts": cuts, "holdout_claim": claim_rec, "graduation_eligible": False,
            "note": "SCREEN under RULE-AM-RISK-ADJUSTED-V1 (per-trade R books); a PASS is a fresh-window confirmation input, then a Tier-3 proposal input.",
            "provenance": "ESTIMATED"}


def r123_segment(seg: dict) -> dict:
    """mf_tighten_random's registered rule (RQ-20261125-c7e3-05): R1-R3 of RULE-AM-RISK-ADJUSTED-V1 vs HOLD decide; R4 is NOT a clause, because the
    policy is itself a uniform random placement (a uniform control is the same distribution). With no declared control the V1 grader returns
    INDETERMINATE (no_random_control) when R1-R3 pass; this maps that to PASS, and leaves a failed R1-R3 as FAIL."""
    c = (seg.get("candidate") or {}).get("clauses") or {}
    if not c or seg.get("n", 0) == 0:
        return seg
    r123 = [c.get("R1_cost"), c.get("R2_risk_cut"), c.get("R3_folds")]
    if any(v is False for v in r123):
        v, lab = "fail", "fails_R1_R3_model_free"
    elif all(v is True for v in r123):
        v, lab = "pass", "passes_R1_R3_model_free_R4_not_a_clause"
    else:
        v, lab = "indeterminate", "r1_r3_unreadable"
    return dict(seg, verdict=v, label=lab, r4_clause=False)


def brief(res: dict) -> dict:
    b = P._brief(res)
    b["measurement"]["top_strategy_cuts"] = dict(list(res["reported_cuts"]["strategy"].items())[:12])
    b["measurement"]["family_cuts"] = res["reported_cuts"]["family"]
    return b


# ---- cli ---------------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    lb = sub.add_parser("label")
    lb.add_argument("--run-id", default="am-action-value")
    lb.add_argument("--out", required=True)
    lb.add_argument("--heads", required=True)
    lb.add_argument("--index", type=int, nargs="+", required=True)
    lb.add_argument("--max-jobs", type=int, default=cf_bulk.DEFAULT_MAX_JOBS)
    ft = sub.add_parser("fit")
    ft.add_argument("--labels", required=True)
    ft.add_argument("--heads", required=True)
    ft.add_argument("--out", required=True)
    ft.add_argument("--only-fold", default=None, help="fit one heads fold (its test_start id) and write manifest_<fold>.json")
    fm = sub.add_parser("fit-merge")
    fm.add_argument("--models", required=True)
    ft.add_argument("--min-train-rows", type=int, default=MIN_TRAIN_ROWS, help="tests only; the registered value is MIN_TRAIN_ROWS")
    s = sub.add_parser("shard")
    s.add_argument("--run-id", default="am-action-value")
    s.add_argument("--out", required=True)
    s.add_argument("--heads", required=True)
    s.add_argument("--av", required=True)
    s.add_argument("--index", type=int, nargs="+", required=True)
    s.add_argument("--classes", required=True)
    s.add_argument("--n-control", type=int, default=N_CONTROL)
    s.add_argument("--max-jobs", type=int, default=cf_bulk.DEFAULT_MAX_JOBS)
    r = sub.add_parser("reduce")
    r.add_argument("--out", required=True)
    r.add_argument("--classes", required=True)
    r.add_argument("--unit", required=True)
    r.add_argument("--reader", default="research-script-run")
    r.add_argument("--ledger", default="")
    r.add_argument("--no-claim", action="store_true")
    r.add_argument("--n-control", type=int, default=N_CONTROL)
    a = ap.parse_args(argv)
    if a.cmd == "fit-merge":
        man = fit_merge(Path(a.models))
        print(json.dumps({"folds": [f["fold_id"] for f in man["folds"]]}))
        return 0
    if a.cmd == "fit":
        man = fit(Path(a.labels), Path(a.heads), Path(a.out), a.min_train_rows, a.only_fold)
        print(json.dumps({"folds": len(man["folds"]), "labels": man["labels"]}))
        return 0
    if a.cmd in ("shard", "reduce") and a.classes not in CLASSES:
        ap.error(f"--classes must be ONE of {CLASSES}; got {a.classes!r}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "reduce":
        res = reduce_run(out, a.classes, a.unit, a.reader, Path(a.ledger) if a.ledger else None, not a.no_claim, a.n_control)
        (out / "grade_full.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        (out / "verdict.json").write_text(json.dumps(brief(res), indent=1, default=str) + "\n")
        print(json.dumps({k: res[k] for k in ("verdict", "class", "n")}))
        return 0
    heads = Heads5(Path(a.heads))
    plan, jobs, chunks = cf_bulk.build_plan(a.run_id, a.max_jobs)
    vm = ValueModels(Path(a.av)) if a.cmd == "shard" else None
    rc = 0
    for i in a.index:
        if a.cmd == "label":
            meta = run_label_shard(plan["shards"][i], chunks, jobs, heads, out)
        else:
            meta = run_policy_shard(plan["shards"][i], chunks, jobs, heads, vm, out, a.classes, a.n_control)
        print(json.dumps({k: meta.get(k) for k in ("shard_id", "stage", "state", "n_trades", "n_rows", "n_replayed", "n_fired", "could_not_replay")}), flush=True)
        rc = rc or (0 if meta["state"] == "done" else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
