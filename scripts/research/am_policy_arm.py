#!/usr/bin/env python3
# wiring: .github/workflows/am-policy-arm.yml (plan -> train heads -> sharded replay -> reduce/grade); research/queue/RQ-20261124-b5a1-0{1..5}.yaml; tests/test_am_policy_arm.py
"""AM v2 STAGE B: the Stage-A heads applied as a BRACKET POLICY on the counterfactual replay, graded by RULE-AM-RISK-ADJUSTED-V1.

Tier 1 research tooling. Reads the committed trade corpus + the keyless Binance Vision bars + the heads dumped by ``am_heads_fit.py dump``; writes only
``--out``. No served model, no order path, no config. Design: ``docs/research/ml-am-heads-design-2026-11-23.md`` sections 3-7; the registered units are
``research/queue/RQ-20261124-b5a1-01..05`` (one per action class, each carrying its rule BEFORE any run).

WHAT A POLICY ARM IS. For every cf_bulk replay job (a backtest trade) the driver re-runs the SAME replay that produces ``replayed_actual`` (the leg's own
management: its TP and trail, plus the harness timeout) and adds the policy's bracket moves on top, through ``cf_core.simulate``. So the baseline arm
(HOLD) is ``replayed_actual`` byte for byte, a policy that never acts equals it exactly (the parity test), and the candidate differs only by the moves.
Net R is the engine's own ``net_of`` (fee + exit slippage + funding, the full cost stack) in R of the ORIGINAL stop distance. A loosened stop is NOT
re-sized: the position was sized at entry, so a stop pushed to 2 R genuinely risks 2 R and that tail shows up in the book's drawdown and CVaR.

DECISION ROWS (no lookahead). One decision per bar CLOSE k, k = 1.. the bars the UNMANAGED trade is still open (the rows ``cf_bar_labels`` builds, the
distribution the heads were fitted on). Features use bars 1..k only; the head of the half-year fold the trade ENTERED in scores them (a head fitted on
trades whose label window ends 7 days before that fold, so it never saw the trade); the move is stamped at bar k's close, effective on the first bar that
opens at or after it. After the unmanaged trade's last row the brackets are frozen where the policy left them (the conservative choice: no head output
is used outside its training distribution).

THE FOUR ACTION CLASSES (every number fixed before the first run; the heads' own score cuts are the fold's TRAINING percentiles, never test data):
  target   two-way TP. Level = clip(original TP, close + Q50, close + Q90) in R from entry, with Q the q0.5 / q0.9 heads' remaining-MFE predictions and a
           floor of TP_MIN_DIST_R above the close. A TP farther than what 90% of paths reach is PULLED IN to the q0.9 level; one nearer than the median
           reach is EXTENDED to the q0.5 level; one inside the band is untouched. Legs with no TP in the replay (tp is None) get no target action.
  tighten  invalidation. When P(stop_first) >= the fold's training p90 AND P(dip_recovers) <= the fold's training p50: move the stop halfway from the
           original stop to the close (``set_stop`` only ever tightens, so the leg's own trail is never undone).
  loosen   the dip that recovers. When P(dip_recovers) >= the fold's training p90: move the stop to the nearest opposing swing (the extreme of the last
           STRUCT_N closed bars, pre-entry bars included, minus STRUCT_BUFFER_R), only if that is at least LOOSEN_MIN_R beyond the live stop, never past
           LOOSEN_CAP_R from entry (``loosen_stop``: only ever loosens). A trailing leg's own trail re-tightens it as soon as the trail passes it.
  bank     a resting partial limit of BANK_FRAC at close + Q50 (``bank_at``), re-placed when the level moves by LEVEL_HYST_R; banks at most once.
  combined all four at once (they are mutually consistent: tighten needs a low dip score, loosen a high one).

THE MATCHED RANDOM-INTERVENTION CONTROL (R4). N_CONTROL (100) seeded draws per class. A draw keeps, per trade, the policy's number of actions of the class and
their level parameters (the TP / bank offset, the tighten fraction; loosen's structure level is head-free) but re-times them to rows drawn uniformly,
without replacement, from the same decision rows that satisfy the class's head-free precondition. The control therefore carries the same intervention
count, size and kind and none of the head's timing information. (It is drawn from the unmanaged trade's open rows, so it never fires into a closed trade:
a STRONGER control than a causal one, which is the conservative direction for the policy.)

GRADING. ``reduce`` builds the books of HOLD, the class arm and its N_CONTROL controls, grades them with ``am_risk_adjusted.grade_risk_adjusted`` (V1
parameters, unchanged) on the DEV segment (entry before 2026-01-01) and on the claimed HOLDOUT segment (entry from 2026-01-01; the claim is written
to the holdout ledger BEFORE the holdout books are built). Unit verdict: PASS iff both segments pass R1-R4; FAIL iff the dev segment fails R1, R2 or R3
or R4; else INDETERMINATE. Until BOOK-SIM-REAL-SIZER exists this is a SCREEN (``graduation_eligible: false``): a PASS is a proposal input, never an apply.
Per-strategy and per-leg cuts are REPORTED, never graded.

  python3 scripts/research/am_policy_arm.py shard  --run-id ID --out DIR --heads DIR --index I [I ...] [--classes target] [--n-control 100]
  python3 scripts/research/am_policy_arm.py reduce --out DIR --classes target --unit RQ-... --reader '...' [--ledger PATH] [--no-claim]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "scripts", REPO / "scripts" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import cf_bar_labels as L  # noqa: E402
import cf_bars  # noqa: E402
import cf_bulk  # noqa: E402
import cf_core  # noqa: E402
import live_review_counterfactual as lrc  # noqa: E402

SCHEMA = "am_policy_arm/1"
COMPONENTS = ("target", "tighten", "loosen", "bank")
CLASSES = COMPONENTS + ("combined",)
N_CONTROL = 100
TP_MIN_DIST_R = 0.25          # a target/bank level sits at least this far (R) beyond the close: never a market-order in disguise
LEVEL_HYST_R = 0.10           # re-place a target/bank level only when it moves by this much (R)
TIGHTEN_FRAC = 0.5            # new stop = original stop + this fraction of the way to the close
TIGHTEN_STEP_R = 0.05         # emit a further tighten only when it is at least this much tighter than the last emitted one
STRUCT_N = 20                 # closed bars (pre-entry included) the swing extreme is read over
STRUCT_BUFFER_R = 0.10
LOOSEN_MIN_R = 0.05           # the structure level must be at least this far beyond the live (original) stop to be worth moving to
LOOSEN_CAP_R = 2.0            # never a stop farther than this from entry
BANK_FRAC = 0.5
PRE_BARS = STRUCT_N + 5       # bars fetched before the fill so the swing window exists at bar 1
DEV_END = "2026-01-01"
HOLDOUT_START = "2026-01-01"
HOLDOUT_TRAIN_END = "2025-12-01"   # what the heads' training windows end by (matches Stage A's claim)
RULE_ID = "RULE-AM-HEADS-STAGE-B-20261124"
HEAD_FEATS = ["open_r", "peak_r", "mae_r", "bars_since_peak", "bars_open", "range_atr_k", "side", "tf_log_sec", "strat"]
#: RICH heads (``am_heads_fit.py dump --feats rich``, unit RQ-20261124-a9d2-01 PASS): the 9 features + the cf_bar_labels ctx block. A rich manifest makes every
#: driver build its decision rows with ``context=True`` over CTX_LOOKBACK bars of pre-fill history (``attach_history``); a base manifest is unchanged.
CTX_HEAD_FEATS = [f"ctx_{k}" for k in L.CTX_KEYS]
RICH_HEAD_FEATS = HEAD_FEATS + CTX_HEAD_FEATS


# ---- the heads --------------------------------------------------------------------------------------------------------
class Heads:
    """The heads ``am_heads_fit.py dump`` saved: a LightGBM booster per (fold, head), the fold windows, strategy codes and score cuts."""

    NEEDED = ("q0.5", "q0.9", "stop_first", "dip_recovers")

    def __init__(self, root: Path):
        import lightgbm as lgb
        self.root = Path(root)
        self.man = json.loads((self.root / "manifest.json").read_text())
        if self.man.get("schema") != "am_heads_dump/1":
            raise ValueError(f"unexpected heads manifest schema {self.man.get('schema')!r}")
        if list(self.man["feats"]) not in (HEAD_FEATS, RICH_HEAD_FEATS):
            raise ValueError(f"head feature list {self.man['feats']} is neither driver feature list {HEAD_FEATS} nor {RICH_HEAD_FEATS}")
        self.feats = list(self.man["feats"])
        self.rich = self.feats == RICH_HEAD_FEATS
        self.pre_bars = max(PRE_BARS, L.CTX_LOOKBACK + 1) if self.rich else PRE_BARS   # bars the shard fetch reaches back before the earliest fill
        self.strat = {str(name): int(code) for code, name in self.man["strategies"].items()}   # the manifest stores {code: name}
        self.folds: List[dict] = []
        self.boosters: Dict[tuple, Any] = {}
        for f in self.man["folds"]:
            if f.get("skipped") or not f.get("files"):
                continue
            if any(h not in f["files"] for h in self.NEEDED):
                continue
            for h in self.NEEDED:
                p = self.root / f["fold_id"] / f"{h}.txt"
                if hashlib.sha256(p.read_bytes()).hexdigest() != f["files"][h]:
                    raise ValueError(f"head file {p} does not match the manifest sha256")
                self.boosters[(f["fold_id"], h)] = lgb.Booster(model_file=str(p))
            self.folds.append(f)
        self._starts = [self._ts(f["test_start"]) for f in self.folds]
        self._ends = [self._ts(f["test_end"]) if f.get("test_end") else float("inf") for f in self.folds]

    @staticmethod
    def _ts(day: str) -> float:
        return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

    def fold_of(self, entry_ts: float) -> Optional[dict]:
        """The fold whose TEST window holds this entry time (the head that never saw the trade), else None (a trade before the first fold)."""
        for f, a, b in zip(self.folds, self._starts, self._ends):
            if a <= entry_ts < b:
                return f
        return None

    def predict(self, fold_id: str, X) -> Dict[str, Any]:
        import numpy as np
        out = {h: self.boosters[(fold_id, h)].predict(X) for h in self.NEEDED}
        out["q0.9"] = np.maximum(out["q0.9"], out["q0.5"])         # monotone rearrangement of the two quantile heads
        return out


# ---- one trade's replay context ---------------------------------------------------------------------------------------
def make_ctx(job: dict, bars: Sequence[dict], tf: str) -> Optional[dict]:
    """The inputs ``cf_harness.cf_fields(..., entry_at_bar_close=True)`` hands ``cf_core.grade_package`` for ``replayed_actual``, rebuilt here so the
    baseline arm is that arm exactly. None when the job has no usable geometry or no bars after the fill."""
    row = {k: v for k, v in job.items() if not k.startswith("_")}
    side = {"buy": "long", "sell": "short"}.get(str(row.get("direction") or "").lower(), str(row.get("direction") or "").lower())
    entry, sl = lrc._num(row.get("entry")), lrc._num(row.get("sl"))
    t_row, t_exit = lrc._ts(row.get("entry_time")), lrc._ts(row.get("exit_time"))
    if side not in ("long", "short") or entry is None or sl is None or entry == sl or t_row is None or t_exit is None:
        return None
    sec = float(cf_bars.TF_SECONDS[tf])
    pkg = {"entry": entry, "exit_plan": {"stop": {"price": sl}}, "direction": side}
    stop0 = lrc.initial_stop(pkg)
    entry_ref = lrc._num(pkg.get("entry"))
    if stop0 is None or entry_ref is None or abs(entry_ref - stop0) <= 0:
        return None
    r_dist = abs(entry_ref - stop0)
    meta = dict(job.get("_leg_meta") or {})
    atr, trail_mult = lrc._num(meta.get("atr")), lrc._num(meta.get("trail_mult"))
    cfg = {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for(row.get("strategy"))) else {})}
    horizon = cf_core.resolve_horizon({"timeframe": tf}, cfg)
    t_fill = lrc._ts(lrc._iso(t_row + sec))                      # entry_at_bar_close: the fill is the signal bar's close
    t_close = lrc._ts(lrc._iso(t_exit))
    bars = sorted((b for b in bars if b["time"] < t_close + horizon["seconds"]), key=lambda b: b["time"])
    if not any(b["time"] >= t_fill for b in bars):
        return None
    fee_r = lrc._num(row.get("cost_fee_r")) or 0.0
    lead = {"fee_taker_usd": fee_r * r_dist, "cost_source": "estimate"}
    timed = ([{"ts": t_exit + sec, "kind": "close", "level": None, "frac": 1.0}]
             if str(row.get("exit_reason") or "").lower() == "timeout" else [])
    post = [b for b in bars if b["time"] >= t_fill]
    return {"post": post, "i0": len(bars) - len(post), "side": side, "sign": 1.0 if side == "long" else -1.0, "entry_ref": entry_ref, "entry_fill": entry_ref, "stop0": stop0, "r_dist": r_dist,
            "tp0": lrc._num(meta.get("tp")), "own_trail": atr * trail_mult if atr and trail_mult else None, "t_row": t_row, "t_fill": t_fill,
            "t_close": t_close, "t_exit": t_exit, "sec": sec, "bars": bars, "timed": timed, "symbol": str(row.get("symbol")), "tf": tf,
            "cm": cf_core.cost_model(lead, str(row.get("symbol")), entry_ref, 1.0), "strategy": row.get("strategy"),
            "key": job.get("trade_key") or f"{row.get('strategy')}|{row.get('symbol')}|{row.get('entry_time')}|{side}|{sl}"}


def run_arm(ctx: dict, extra: Sequence[dict] = ()) -> dict:
    """One replay of the trade with ``extra`` bracket actions on top of the leg's own management. ``extra == []`` IS ``replayed_actual``."""
    sim = cf_core.simulate(ctx["bars"], side=ctx["side"], entry_ref=ctx["entry_ref"], r_dist=ctx["r_dist"], t_entry=ctx["t_fill"], stop0=ctx["stop0"],
                           tp=ctx["tp0"], actions=list(ctx["timed"]) + list(extra), rules=(), trail_dist=ctx["own_trail"])
    n = cf_core.net_of(sim, side=ctx["side"], entry_fill=ctx["entry_fill"], r_dist=ctx["r_dist"], t_entry=ctx["t_fill"], cm=ctx["cm"])
    x_ts = sim["fills"][-1]["ts"] if sim["fills"] else None
    return {"net_r": n["net_r"], "gross_r": n["gross_r"], "cost_r": n["cost_r"], "exit_ts": x_ts, "fills": sim["fills"], "resolved": sim["resolved"],
            "mfe_r": _mfe_r(ctx, x_ts)}


def _mfe_r(ctx: dict, x_ts: Optional[float]) -> Optional[float]:
    if x_ts is None:
        return None
    sg, e, r = ctx["sign"], ctx["entry_ref"], ctx["r_dist"]
    best = 0.0
    for b in ctx["bars"]:
        if b["time"] < ctx["t_fill"]:
            continue
        if b["time"] > x_ts:
            break
        best = max(best, sg * ((b["high"] if sg > 0 else b["low"]) - e) / r)
    return round(best, 6)


# ---- decision rows and the policy -------------------------------------------------------------------------------------
def attach_history(ctx: Optional[dict], store: Any, heads: "Heads") -> Optional[dict]:
    """RICH heads only: stash the CTX_LOOKBACK closed bars before the fill (``store.window``) as ``ctx["hist_pre"]`` so ``decision_rows`` builds the ctx block
    exactly as ``cf_bar_labels_run.py shard --context`` did for the labels the heads were fitted on (``pre`` = bars with time < t_fill, last CTX_LOOKBACK).
    The replay bars (``ctx["bars"]``) are untouched, so every arm, HOLD included, replays byte-identically to a base run. No-op for base heads."""
    if ctx is not None and getattr(heads, "rich", False):
        ctx["hist_pre"] = [b for b in store.window(ctx["t_fill"] - (L.CTX_LOOKBACK + 1) * ctx["sec"], ctx["t_fill"]) if b["time"] < ctx["t_fill"]][-L.CTX_LOOKBACK:]
    return ctx


def decision_rows(ctx: dict) -> List[dict]:
    """The point-in-time rows of the unmanaged trade (``cf_bar_labels``, features only), capped at the harness exit exactly as the label build is.
    With ``ctx["hist_pre"]`` (rich heads) each row also carries the ctx block; the base features and the row set are unchanged (they never read pre-fill bars)."""
    post = ctx["post"]
    exit_idx = next((k for k, b in enumerate(post, start=1) if b["time"] + ctx["sec"] >= ctx["t_exit"]), None)
    if "hist_pre" in ctx:
        return L.build_rows(side=ctx["side"], entry=ctx["entry_ref"], sl=ctx["stop0"], bars=list(ctx["hist_pre"]) + list(post), entry_time=ctx["t_row"],
                            bar_seconds=ctx["sec"], exit_idx=exit_idx, with_labels=False, context=True)
    return L.build_rows(side=ctx["side"], entry=ctx["entry_ref"], sl=ctx["stop0"], bars=ctx["bars"], entry_time=ctx["t_row"], bar_seconds=ctx["sec"],
                        exit_idx=exit_idx, with_labels=False)


def _nan(v) -> float:
    return float("nan") if v is None else float(v)


def feature_matrix(ctx: dict, rows: Sequence[dict], strat_id: int):
    """The heads' input matrix: the 9 HEAD_FEATS, plus the 6 ctx columns (NaN where None, as ``am_heads_fit.load(rich=True)`` reads them) when the
    rows carry a ctx block (rich heads)."""
    import numpy as np
    sg = ctx["sign"]
    ltf = math.log(ctx["sec"])
    rich = "hist_pre" in ctx
    width = len(RICH_HEAD_FEATS) if rich else len(HEAD_FEATS)
    out = []
    for r in rows:
        f = r["features"]
        v = [f["open_r"], f["peak_r"], f["mae_r"], f["bars_since_peak"], f["bars_open"], _nan(f["range_atr_k"]), sg, ltf, float(strat_id)]
        if rich:
            c = r.get("ctx") or {}
            v += [_nan(c.get(k)) for k in L.CTX_KEYS]
        out.append(v)
    return np.array(out, dtype="float32").reshape(len(rows), width)


def _px(ctx: dict, level_r: float) -> float:
    return ctx["entry_ref"] + ctx["sign"] * level_r * ctx["r_dist"]


def _close_ts(ctx: dict, post: Sequence[dict], k: int) -> float:
    return post[k - 1]["time"] + ctx["sec"]


def structure_level_r(ctx: dict, k: int) -> Optional[float]:
    """The swing-extreme stop level (R from entry, negative) at bar k's close, or None when it is not at least LOOSEN_MIN_R beyond the original stop.
    Reads only closed bars <= k (pre-entry bars included): the extreme adverse excursion of the last STRUCT_N bars."""
    bars, i0 = ctx["bars"], ctx["i0"]
    win = bars[max(0, i0 + k - STRUCT_N): i0 + k]
    if not win:
        return None
    sg, e, r = ctx["sign"], ctx["entry_ref"], ctx["r_dist"]
    adv = min(sg * ((b["low"] if sg > 0 else b["high"]) - e) / r for b in win)
    lvl = adv - STRUCT_BUFFER_R
    if lvl >= -1.0 - LOOSEN_MIN_R:
        return None
    return max(lvl, -LOOSEN_CAP_R)


def _tp0_r(ctx: dict) -> Optional[float]:
    return None if ctx["tp0"] is None else ctx["sign"] * (ctx["tp0"] - ctx["entry_ref"]) / ctx["r_dist"]


def decide(ctx: dict, rows: Sequence[dict], pred: Dict[str, Sequence[float]], thr: dict, classes: Sequence[str]) -> List[dict]:
    """The policy: bracket moves, one list of specs. ``pred`` rows align with ``rows``; ``thr`` = the fold's training score cuts
    (``{"stop_first": {"p90":..}, "dip_recovers": {"p50":..,"p90":..}}``). Pure; reads only rows <= k at row k."""
    want = set(COMPONENTS) if "combined" in classes else set(classes)
    post = ctx["post"]
    tp0_r = _tp0_r(ctx)
    last_tp, last_bank, last_tight, last_loose = tp0_r, None, -1.0, -1.0
    out: List[dict] = []
    for i, row in enumerate(rows):
        k, open_r = row["k"], row["features"]["open_r"]
        ts = _close_ts(ctx, post, k)
        q50 = max(0.0, float(pred["q0.5"][i]))
        q90 = max(q50, float(pred["q0.9"][i]))
        near = max(q50, TP_MIN_DIST_R)
        if "target" in want and tp0_r is not None:
            new = min(max(tp0_r, open_r + near), open_r + max(q90, near))
            if abs(new - last_tp) >= LEVEL_HYST_R:
                out.append({"cls": "target", "k": k, "ts": ts, "kind": "set_tp", "level": _px(ctx, new), "rel": {"offset": new - open_r}})
                last_tp = new
        if "bank" in want:
            lvl = open_r + near
            if last_bank is None or abs(lvl - last_bank) >= LEVEL_HYST_R:
                out.append({"cls": "bank", "k": k, "ts": ts, "kind": "bank_at", "level": _px(ctx, lvl), "frac": BANK_FRAC, "rel": {"offset": lvl - open_r}})
                last_bank = lvl
        p_stop, p_dip = float(pred["stop_first"][i]), float(pred["dip_recovers"][i])
        if "tighten" in want and p_stop >= thr["stop_first"]["p90"] and p_dip <= thr["dip_recovers"]["p50"]:
            lvl = -1.0 + TIGHTEN_FRAC * (open_r + 1.0)
            if lvl >= last_tight + TIGHTEN_STEP_R:
                out.append({"cls": "tighten", "k": k, "ts": ts, "kind": "set_stop", "level": _px(ctx, lvl), "rel": {"frac": TIGHTEN_FRAC}})
                last_tight = lvl
        if "loosen" in want and p_dip >= thr["dip_recovers"]["p90"]:
            lvl = structure_level_r(ctx, k)
            if lvl is not None and lvl <= last_loose - LOOSEN_MIN_R:
                out.append({"cls": "loosen", "k": k, "ts": ts, "kind": "loosen_stop", "level": _px(ctx, lvl), "rel": {}})
                last_loose = lvl
    return out


def _spec_action(s: dict) -> dict:
    return {"ts": s["ts"], "kind": s["kind"], "level": s["level"], **({"frac": s["frac"]} if "frac" in s else {})}


def _eligible(cls: str, ctx: dict, row: dict) -> bool:
    if cls == "target":
        return ctx["tp0"] is not None
    if cls == "loosen":
        return structure_level_r(ctx, row["k"]) is not None
    return True


def control_specs(ctx: dict, rows: Sequence[dict], specs: Sequence[dict], rng: random.Random) -> List[dict]:
    """One matched random draw: the policy's per-class action count and level parameters, re-timed to uniformly drawn eligible rows."""
    post = ctx["post"]
    by_cls: Dict[str, List[dict]] = defaultdict(list)
    for s in specs:
        by_cls[s["cls"]].append(s)
    out: List[dict] = []
    for cls, ss in sorted(by_cls.items()):
        elig = ctx.setdefault("_elig", {}).get(cls)
        if elig is None:
            elig = ctx["_elig"][cls] = [r for r in rows if _eligible(cls, ctx, r)]
        n = min(len(ss), len(elig))
        if not n:
            continue
        rels = [s["rel"] for s in ss]
        rng.shuffle(rels)
        for rel, row in zip(rels, rng.sample(elig, n)):
            k, open_r = row["k"], row["features"]["open_r"]
            ts = _close_ts(ctx, post, k)
            if cls == "target":
                out.append({"cls": cls, "k": k, "ts": ts, "kind": "set_tp", "level": _px(ctx, open_r + rel["offset"])})
            elif cls == "bank":
                out.append({"cls": cls, "k": k, "ts": ts, "kind": "bank_at", "level": _px(ctx, open_r + rel["offset"]), "frac": BANK_FRAC})
            elif cls == "tighten":
                out.append({"cls": cls, "k": k, "ts": ts, "kind": "set_stop", "level": _px(ctx, -1.0 + rel["frac"] * (open_r + 1.0))})
            else:
                out.append({"cls": cls, "k": k, "ts": ts, "kind": "loosen_stop", "level": _px(ctx, structure_level_r(ctx, k))})
    return out


def control_rng(key: str, cls: str, draw: int) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{key}|{cls}|{draw}".encode()).hexdigest()[:12], 16))


# ---- a shard ----------------------------------------------------------------------------------------------------------
def _arm_cell(a: dict) -> list:
    return [round(a["net_r"], 6), None if a["exit_ts"] is None else int(a["exit_ts"]), a["mfe_r"]]


def replay_trade(ctx: dict, rows: Sequence[dict], pred: Optional[dict], thr: Optional[dict], classes: Sequence[str], n_control: int) -> dict:
    """Baseline + each class arm + its controls for one trade. ``pred`` None (no rows) means every arm equals the baseline."""
    base = run_arm(ctx)
    rec: Dict[str, Any] = {"b": _arm_cell(base), "a": {}}
    for cls in classes:
        specs = decide(ctx, rows, pred, thr, [cls]) if rows and pred is not None else []
        if not specs:
            rec["a"][cls] = {"n": 0}                        # the lever never fired on this trade: policy and every control equal HOLD
            continue
        arm = run_arm(ctx, [_spec_action(s) for s in specs])
        ctl = []
        for d in range(n_control):
            cs = control_specs(ctx, rows, specs, control_rng(ctx["key"], cls, d))
            c = run_arm(ctx, [_spec_action(s) for s in cs]) if cs else base
            ctl.append([round(c["net_r"], 6), None if c["exit_ts"] is None else int(c["exit_ts"])])
        rec["a"][cls] = {"n": len(specs), "p": _arm_cell(arm), "c": ctl}
    return rec


def run_shard(shard: dict, chunks: Dict[str, List[str]], jobs: Dict[str, dict], heads: Heads, out: Path, classes: Sequence[str], *,
              n_control: int = N_CONTROL, fetcher=None) -> dict:
    import numpy as np
    sdir = out / "am_policy"
    sdir.mkdir(parents=True, exist_ok=True)
    tf, sym = shard["timeframe"], shard["symbol"]
    chosen = chunks[shard["shard_id"]]
    t0, state, err, bars = time.time(), "done", None, []
    reasons: Counter = Counter()
    if tf is None:
        reasons["timeframe_unresolved"] = len(chosen)
    elif not cf_bulk.is_crypto(sym):
        reasons["no_bar_source"] = len(chosen)
    else:
        try:
            sec = cf_bars.TF_SECONDS[tf]
            lo = min(lrc._ts(jobs[k]["entry_time"]) for k in chosen) - heads.pre_bars * sec
            hi = max(lrc._ts(jobs[k]["exit_time"]) + cf_core.resolve_horizon(
                {"timeframe": tf}, {"timeframe": tf, **({"max_hold_bars": mb} if (mb := cf_bulk.timeout_bars_for(jobs[k].get("strategy"))) else {})})["seconds"]
                for k in chosen)
            bars = cf_bars.historical_bars(sym, tf, lo, hi, fetcher)
        except Exception as e:   # allow-silent: a failed fetch is a recorded state (no 'done' meta, so a re-run retries), never a halt
            state, err = "fetch_failed", f"{type(e).__name__}: {e}"[:300]
    store = cf_bulk.BarStore(bars) if bars else None
    if store is None and state == "done" and not reasons:
        reasons["no_bars"] = len(chosen)                     # a crypto shard whose window returned no bars: counted, never silent
    # pass 1: contexts, decision rows, features per fold
    prep: List[tuple] = []
    by_fold: Dict[str, List[Any]] = defaultdict(list)
    n_unknown_strat = 0
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
        ctx = attach_history(make_ctx(job, store.window(t_row - PRE_BARS * sec, t_exit + h), tf), store, heads)
        if ctx is None:
            reasons["no_replay_context"] += 1
            continue
        rows = decision_rows(ctx)
        sid = heads.strat.get(str(job.get("strategy")), -1)
        n_unknown_strat += sid < 0
        item = [key, job, ctx, rows, fold, None]
        prep.append(item)
        if rows:
            by_fold[fold["fold_id"]].append((item, feature_matrix(ctx, rows, sid)))
    # pass 2: score every row with the head of the fold the trade entered in
    for fid, items in by_fold.items():
        X = np.vstack([m for _, m in items])
        # provenance: predict -- Booster.predict per head: the q0.5/q0.9 remaining-MFE quantiles in R0 and the binary stop_first / dip_recovers P(label=1)
        p = heads.predict(fid, X)
        i = 0
        for item, m in items:
            n = len(m)
            item[5] = {h: p[h][i:i + n] for h in p}
            i += n
    # pass 3: arms
    tmp = sdir / f"{shard['shard_id']}.jsonl.gz.tmp"
    n_rows = 0
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for key, job, ctx, rows, fold, pred in prep:
            rec = replay_trade(ctx, rows, pred, fold["thresholds"], classes, n_control)
            n_rows += len(rows)
            fh.write(json.dumps({"k": key, "st": job.get("strategy"), "sy": sym, "tf": tf, "e": job.get("entry_time"), "f": fold["fold_id"], **rec},
                                separators=(",", ":"), default=str) + "\n")
    tmp.replace(sdir / f"{shard['shard_id']}.jsonl.gz")
    meta = {**shard, "schema": SCHEMA, "state": state, "error": err, "n_jobs": len(chosen), "n_replayed": len(prep), "n_decision_rows": n_rows,
            "n_unknown_strategy_code": int(n_unknown_strat), "could_not_replay": dict(reasons), "classes": list(classes), "n_control": n_control,
            "seconds": round(time.time() - t0, 2), "provenance": "ESTIMATED"}
    if state == "done":
        (sdir / f"{shard['shard_id']}.meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


# ---- reduce / grade ---------------------------------------------------------------------------------------------------
def _iso(ts: int, _c: Dict[int, str] = {}) -> str:
    s = _c.get(ts)
    if s is None:
        s = _c[ts] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return s


def read_shards(out: Path) -> tuple:
    """Every shard's records plus metas. The per-trade control cells are converted to compact numpy arrays on read (``cn`` nets, ``cx`` exit
    seconds) so ~100 controls x ~470k trades never sit in memory as Python lists."""
    import numpy as np
    recs, metas = [], []
    for mp in sorted((out / "am_policy").glob("*.meta.json")):
        m = json.loads(mp.read_text())
        dp = mp.with_name(mp.name.replace(".meta.json", ".jsonl.gz"))
        if not dp.exists():
            continue
        metas.append(m)
        with gzip.open(dp, "rt", encoding="utf-8") as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                for cell in r["a"].values():
                    if cell.get("c"):
                        cell["cn"] = np.array([c[0] for c in cell["c"]], dtype="float64")
                        cell["cx"] = np.array([c[1] if c[1] is not None else -1 for c in cell["c"]], dtype="int64")
                        del cell["c"]
                recs.append(r)
    return recs, metas


class LazyBook:
    """A control book as arrays: iterating yields the trade dicts ``am_risk_adjusted`` reads, built on demand (never ~47M dicts at once)."""

    def __init__(self, entries: List[str], net, exit_ts):
        self.entries, self.net, self.exit_ts = entries, net, exit_ts

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        for e, n, x in zip(self.entries, self.net, self.exit_ts):
            yield {"entry_time": e, "exit_time": _iso(int(x)), "net_r": float(n)}


def build_books(recs: Sequence[dict], cls: str, n_control: int) -> Dict[str, Any]:
    """HOLD, the class arm ``cls`` and its controls ``cls_C00..`` for ``am_risk_adjusted``. A trade whose lever never fired carries the HOLD cell in
    every arm (it is part of every book)."""
    import numpy as np
    n = len(recs)
    books: Dict[str, Any] = {"H": [], cls: []}
    cn = np.empty((n, n_control), dtype="float64") if n_control else None
    cx = np.empty((n, n_control), dtype="int64") if n_control else None
    ents: List[str] = []
    for i, r in enumerate(recs):
        e = r["e"] if isinstance(r["e"], str) else str(r["e"])
        ents.append(e)
        b = r["b"]
        base_x = b[1] if b[1] is not None else 0
        h = {"entry_time": e, "exit_time": _iso(base_x), "net_r": b[0], "mfe_r": b[2]}
        books["H"].append(h)
        a = r["a"].get(cls, {"n": 0})
        if a["n"] == 0:
            books[cls].append(h)
            if n_control:
                cn[i, :], cx[i, :] = b[0], base_x
            continue
        p = a["p"]
        books[cls].append({"entry_time": e, "exit_time": _iso(p[1] if p[1] is not None else base_x), "net_r": p[0], "mfe_r": p[2]})
        if n_control:
            cn[i, :] = a["cn"][:n_control]
            cx[i, :] = np.where(a["cx"][:n_control] < 0, base_x, a["cx"][:n_control])
    for d in range(n_control):
        books[f"{cls}_C{d:02d}"] = LazyBook(ents, cn[:, d], cx[:, d])
    return books


def _cuts(recs: Sequence[dict], cls: str, keyf, min_n: int) -> Dict[str, Any]:
    import am_risk_adjusted as A
    g: Dict[str, List[dict]] = defaultdict(list)
    for r in recs:
        g[keyf(r)].append(r)
    out = {}
    for k, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < min_n:
            continue
        bk = build_books(rs, cls, 0)
        Ah, Cb = A.book_metrics(bk["H"]), A.book_metrics(bk[cls])
        fired = sum(1 for r in rs if r["a"].get(cls, {"n": 0})["n"] > 0)
        out[k] = {"n": len(rs), "share_lever_fired": round(fired / len(rs), 4), "hold_net_r": Ah["net_r"], "policy_net_r": Cb["net_r"],
                  "mean_delta_r_per_trade": round((Cb["net_r"] - Ah["net_r"]) / len(rs), 5), "hold_max_dd_r": Ah["max_drawdown_r"],
                  "policy_max_dd_r": Cb["max_drawdown_r"], "provenance": "ESTIMATED", "graded": False}
    return out


def _segment(recs: Sequence[dict], cls: str, n_control: int, params: Optional[dict] = None) -> Dict[str, Any]:
    import am_risk_adjusted as A
    if not recs:
        return {"verdict": "indeterminate", "label": "empty_segment", "n": 0}
    books = build_books(recs, cls, n_control)
    ctl = [f"{cls}_C{d:02d}" for d in range(n_control)]
    res = A.grade_risk_adjusted(books, baseline="H", candidates=[cls], controls={cls: ctl}, params=params, basis="per_trade_r_screen")
    cand = res.get("candidates", {}).get(cls, {})
    keep = {k: cand.get(k) for k in ("verdict", "label", "lever_fired", "r_cost_per_trade", "dd_cut_pct", "cvar5_cut_pct", "risk_metrics_passing",
                                     "folds_held", "n_folds", "clauses", "book")}
    ctls = cand.get("controls") or {}
    return {"verdict": res.get("verdict"), "label": cand.get("label") or res.get("label"), "n": len(recs), "baseline_book": res.get("baseline_book"),
            "graduation_eligible": res.get("graduation_eligible"), "candidate": keep,
            "controls": {"n": len(ctls), "n_beaten": sum(1 for v in ctls.values() if v["beats"]),
                         "mean_net_r": round(sum(v["book"]["net_r"] for v in ctls.values()) / len(ctls), 6) if ctls else None,
                         "mean_max_dd_r": round(sum(v["book"]["max_drawdown_r"] for v in ctls.values()) / len(ctls), 6) if ctls else None},
            "folds": cand.get("folds"), "why": res.get("why")}


def unit_verdict(dev: dict, hold: dict) -> str:
    """PASS iff dev and holdout both pass R1-R4; FAIL iff the dev segment FAILS (a necessary clause read and failed); else INDETERMINATE."""
    if dev.get("verdict") == "fail":
        return "fail"
    if dev.get("verdict") == "pass" and hold.get("verdict") == "pass":
        return "pass"
    return "indeterminate"


def reduce_run(out: Path, cls: str, unit: str, reader: str, ledger: Optional[Path], claim: bool, n_control: int = N_CONTROL) -> dict:
    recs, metas = read_shards(out)
    dev = [r for r in recs if str(r["e"])[:10] < DEV_END]
    hold = [r for r in recs if str(r["e"])[:10] >= HOLDOUT_START]
    claim_rec = None
    if claim:
        import holdout_lock
        end_day = max((str(r["e"])[:10] for r in recs), default=HOLDOUT_START)
        claim_rec = holdout_lock.claim_read(f"AM-HEADS-stageB-{cls}", HOLDOUT_START, max(end_day, HOLDOUT_START), unit, reader,
                                            ledger or holdout_lock.LEDGER, train_end=HOLDOUT_TRAIN_END, family="AM-HEADS")
        (out / "holdout_claims.jsonl").write_text(json.dumps(claim_rec) + "\n")
    seg_dev = _segment(dev, cls, n_control)
    seg_hold = _segment(hold, cls, n_control)
    verdict = unit_verdict(seg_dev, seg_hold)
    rep_cls = {"strategy": _cuts(dev + hold, cls, lambda r: str(r["st"]), 500),
               "leg": _cuts(dev + hold, cls, lambda r: f"{r['st']}|{r['sy']}|{r['tf']}", 1500),
               "timeframe": _cuts(dev + hold, cls, lambda r: str(r["tf"]), 500)}
    fired = sum(1 for r in recs if r["a"].get(cls, {"n": 0})["n"] > 0)
    n_act = sum(r["a"].get(cls, {"n": 0})["n"] for r in recs)
    could = Counter()
    for m in metas:
        could.update(m.get("could_not_replay") or {})
    pop = (f"{len(recs)} replayed backtest trades (run-w corpus sha 1eb164f4, crypto legs with Binance Vision bars, entry 2022-01-01..end): "
           f"{len(dev)} dev (entry < {DEV_END}), {len(hold)} claimed holdout; arm {cls} vs HOLD (replayed_actual) and {n_control} matched random "
           f"re-timings; R in the original stop distance, full cost stack; per-trade-R SCREEN, not a graduation")
    res = {"schema": SCHEMA, "rule_id": RULE_ID, "unit": unit, "class": cls, "verdict": verdict, "read_state": "measured", "n": len(recs),
           "population": pop, "dev": seg_dev, "holdout": seg_hold, "lever": {"trades_fired": fired, "share_fired": round(fired / len(recs), 4) if recs else None,
                                                                         "actions": n_act, "mean_actions_per_fired_trade": round(n_act / fired, 3) if fired else None},
           "could_not_replay": dict(could), "n_shards": len(metas), "reported_cuts": rep_cls, "holdout_claim": claim_rec,
           "graduation_eligible": False, "note": "SCREEN under RULE-AM-RISK-ADJUSTED-V1 (per-trade R books); a PASS is a Tier-3 proposal input, never an apply. "
                                               "BOOK-SIM-REAL-SIZER owns the book-level $ measurement.", "provenance": "ESTIMATED"}
    return res


def _brief(res: dict) -> dict:
    """The verdict.json the research-result emitter reads (small; the full grade stays in the artifact)."""
    def seg(s):
        c = s.get("candidate") or {}
        return {"verdict": s.get("verdict"), "label": s.get("label"), "n": s.get("n"), "clauses": c.get("clauses"), "r_cost_per_trade": c.get("r_cost_per_trade"),
                "dd_cut_pct": c.get("dd_cut_pct"), "cvar5_cut_pct": c.get("cvar5_cut_pct"), "folds_held": c.get("folds_held"), "controls": s.get("controls"),
                "baseline_book": s.get("baseline_book"), "candidate_book": c.get("book")}
    return {"verdict": res["verdict"], "read_state": res["read_state"], "n": res["n"], "population": res["population"],
            "note": f"class {res['class']}: dev {res['dev'].get('verdict')}/{res['dev'].get('label')}, holdout {res['holdout'].get('verdict')}/{res['holdout'].get('label')}; "
                    f"a per-trade-R screen, never a graduation",
            "measurement": {"rule_id": res["rule_id"], "class": res["class"], "dev": seg(res["dev"]), "holdout": seg(res["holdout"]), "lever": res["lever"],
                            "could_not_replay": res["could_not_replay"], "holdout_claim": res["holdout_claim"],
                            "top_strategy_cuts": dict(list(res["reported_cuts"]["strategy"].items())[:12])}}


# ---- cli --------------------------------------------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--run-id", default="am-policy-arm")
    s.add_argument("--out", required=True)
    s.add_argument("--heads", required=True)
    s.add_argument("--index", type=int, nargs="+", required=True)
    s.add_argument("--classes", default="target")
    s.add_argument("--n-control", type=int, default=N_CONTROL)
    s.add_argument("--max-jobs", type=int, default=cf_bulk.DEFAULT_MAX_JOBS)
    r = sub.add_parser("reduce")
    r.add_argument("--out", required=True)
    r.add_argument("--classes", default="target")
    r.add_argument("--unit", required=True)
    r.add_argument("--reader", default="research-script-run")
    r.add_argument("--ledger", default="")
    r.add_argument("--no-claim", action="store_true")
    r.add_argument("--n-control", type=int, default=N_CONTROL)
    a = ap.parse_args(argv)
    classes = [c for c in a.classes.split(",") if c]
    bad = [c for c in classes if c not in CLASSES]
    if bad or not classes:
        ap.error(f"--classes must be a non-empty subset of {CLASSES}; got {a.classes!r}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "reduce":
        if len(classes) != 1:
            ap.error("reduce grades ONE class per unit")
        res = reduce_run(out, classes[0], a.unit, a.reader, Path(a.ledger) if a.ledger else None, not a.no_claim, a.n_control)
        (out / "grade_full.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
        (out / "verdict.json").write_text(json.dumps(_brief(res), indent=1, default=str) + "\n")
        print(json.dumps({k: res[k] for k in ("verdict", "class", "n")}))
        return 0
    heads = Heads(Path(a.heads))
    plan, jobs, chunks = cf_bulk.build_plan(a.run_id, a.max_jobs)
    rc = 0
    for i in a.index:
        meta = run_shard(plan["shards"][i], chunks, jobs, heads, out, classes, n_control=a.n_control)
        print(json.dumps({k: meta[k] for k in ("shard_id", "state", "n_jobs", "n_replayed", "could_not_replay")}), flush=True)
        rc = rc or (0 if meta["state"] == "done" else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
