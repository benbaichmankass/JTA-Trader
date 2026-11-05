#!/usr/bin/env python3
# wiring: research/queue/RQ-20261101-c692-03.yaml (MANAGE head) and RQ-20261105-c692-08..11 (dynamic-SL arms); spec docs/research/ml-decision-models-2026-11-01/DESIGN.md section 4 + 4a
"""MANAGE decision model and the dynamic-SL single-factor arms, pooled across symbols (Tier-1 research, no order, no sizing).

Spec: DESIGN.md sections 4 (MANAGE) and 4a (dynamic-SL arms); rules registered before any run in the unit files.
Reuses ``ml_decision_entry`` for data, features, the first-passage / tie / gap / cost rules and the frozen ENTRY recipe, and
the ENTRY tau read from the c692-01 summary (never re-chosen here).

BASE TRADES (fixed for every arm, so every comparison is PAIRED): the frozen ENTRY policy (walk-forward OOS predictions on dev,
one final fit for the held-out; tau from c692-01) opens a trade at the next bar open, one position per symbol, with the static
bracket SL ``BASE_SL`` x ATR14 / TP ``BASE_TP`` x ATR14 (the dev-chosen static cell of c692-02) and a 24 h time stop. The set of trades
is defined by HOLD (hold-to-bracket); an action never frees a symbol for a re-entry (the comparison is trade-for-trade).

CHECK-INS: the close of bar k = 4, 8, ..., 20 after the entry bar (the ENTRY decision grid), while the trade is alive. An action
decided at the close of bar k is applied from bar k+1 (no look-ahead). Actions: HOLD, CLOSE (exit at bar k+1's open), BE (SL to entry,
only if the bar-k close is above entry), TRAIL (SL to the bar-k 4-bar extreme minus 1 ATR, ratcheting each bar, only if below the
close and tightening), TPX (TP +1 ATR). A tightening that would sit at/above the close is UNAVAILABLE (never an implicit close).

Net R is per unit of the ORIGINAL stop distance (sizing stays the RiskManager's) and subtracts the canonical cost stack
(``E._cost_r``: fee 11 bps round trip + slippage + funding per 8h window crossed). Never scripts/backtest_orb.py / backtester.py.

    python3 scripts/research/ml_decision_manage.py run --arm manage|be|trail|timedecay|mlsl --entry-summary S --cache C --out O --unit U
    python3 scripts/research/ml_decision_manage.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "scripts" / "research")]
import ml_decision_entry as E  # noqa: E402

SCHEMA = "ml_decision_manage/1"
BASE_SL, BASE_TP = 2.0, 4.0
H = E.HORIZON_H
CHECKINS = [4, 8, 12, 16, 20]
ACTIONS = ["HOLD", "CLOSE", "BE", "TRAIL", "TPX"]
LEARNED = ["CLOSE", "BE", "TRAIL", "TPX"]
SL_ONLY = ["BE", "TRAIL"]                       # the ML-SL-revision arm (d): SL tighten actions only
MARGIN_GRID = [0.0, 0.02, 0.05, 0.10, 0.15]    # predicted delta net R an action must exceed; chosen on dev only
BE_R = 1.0                                      # arm (a): break-even after a bar close >= +1R
TRAIL_ACT_R = 1.0                               # arm (b): trail activates after a bar close >= +1R
TRAIL_GRID = [1.0, 1.5, 2.0]                    # arm (b): trail distance in ATR, chosen on dev
DECAY_GRID = [0.5, 1.0, 1.5]                    # arm (c): SL distance in ATR reached at 24 h, chosen on dev
MIN_TRADES, MIN_SYMBOLS = 300, 10
DEV_MIN_TRADES = 1000
MANAGE_FOLDS = E.DEV_FOLDS[2:]                  # ENTRY OOS dev trades exist from 2022-01; MANAGE needs one fold of history
BOOT = 2000


# ------------------------------------------------------------------------------------------------ simulator
class Paths:
    """Trade price paths in LONG coordinates (shorts are sign-flipped), bars 1..H after the entry decision bar."""

    def __init__(self, o, h, lo, c, atr, side, t_entry_s, t_bar_open_s):
        s = side.astype(float)[:, None]
        self.o, self.c = s * o, s * c
        self.h = np.where(s > 0, h, -lo)
        self.l = np.where(s > 0, lo, -h)
        self.atr, self.side = atr, side.astype(float)
        self.e = self.o[:, 0]
        self.risk = BASE_SL * atr
        self.t_entry_s, self.t_open = t_entry_s, t_bar_open_s      # t_open (N,H): open time of bar b in seconds
        self.n = len(atr)


def simulate(P: Paths, hook=None, sl_m=BASE_SL, tp_m=BASE_TP):
    """Bar loop over all trades at once. ``hook(b, st)`` runs after bar b (1-based) closes for trades still alive and may
    change ``st['sl']``, ``st['tp']`` or set ``st['close']`` (exit at bar b+1's open). Returns net R, bars held, exit reason,
    gross R, MFE R. Tie (SL and TP in one bar) -> SL; a bar opening through the stop fills at its open."""
    n = P.n
    sl = P.e - sl_m * P.atr
    tp = P.e + tp_m * P.atr
    alive = np.ones(n, bool)
    px = np.zeros(n)
    jx = np.zeros(n, int)
    reason = np.zeros(n, int)               # 0 time, 1 sl, 2 tp, 3 close
    runmax = P.h[:, 0].copy()
    mfe = np.zeros(n)
    st = {"sl": sl, "tp": tp, "close": np.zeros(n, bool), "alive": alive, "runmax": runmax, "P": P}
    for j in range(H):
        b = j + 1
        o, hh, ll, c = P.o[:, j], P.h[:, j], P.l[:, j], P.c[:, j]
        hit_sl = alive & (ll <= st["sl"])
        hit_tp = alive & ~hit_sl & (hh >= st["tp"])
        fill = np.where(o <= st["sl"], o, st["sl"])
        px = np.where(hit_sl, fill, np.where(hit_tp, st["tp"], px))
        reason = np.where(hit_sl, 1, np.where(hit_tp, 2, reason))
        jx = np.where(hit_sl | hit_tp, b, jx)
        mfe = np.where(alive, np.maximum(mfe, (hh - P.e) / P.risk), mfe)
        alive = alive & ~(hit_sl | hit_tp)
        runmax = np.where(alive, np.maximum(runmax, hh), runmax)
        st.update(alive=alive, runmax=runmax)
        if b == H:
            px = np.where(alive, c, px)
            jx = np.where(alive, b, jx)
            alive = np.zeros(n, bool)
            break
        if hook is not None:
            st["close"] = np.zeros(n, bool)
            hook(b, st)
            cl = alive & st["close"]
            px = np.where(cl, P.o[:, j + 1], px)
            jx = np.where(cl, b, jx)
            reason = np.where(cl, 3, reason)
            alive = alive & ~cl
            st["alive"] = alive
    gross = (px - P.e) / P.risk
    t_exit = P.t_open[np.arange(n), np.clip(jx - 1, 0, H - 1)] + 3600.0
    # a CLOSE at bar b+1's open is stamped at the end of bar b == the open of bar b+1
    fee, slip, fund = E._cost_r(P.e, px, P.risk, P.t_entry_s, t_exit)
    net = gross - fee - slip - fund
    return {"net": net.astype(np.float64), "gross": gross, "bars": jx, "reason": reason, "mfe": mfe}


def action_hook(k: int, action: str, mask: np.ndarray, avail_out: np.ndarray | None = None):
    """One discrete action at the bar-k check-in for the trades in ``mask`` (and a TRAIL ratchet afterwards)."""
    trail_on = np.zeros(len(mask), bool)

    def hook(b, st):
        P = st["P"]
        al = st["alive"]
        j = b - 1
        c = P.c[:, j]
        if b == k and action != "HOLD":
            m = al & mask
            if action == "CLOSE":
                st["close"] = st["close"] | m
            elif action == "TPX":
                st["tp"] = np.where(m, st["tp"] + P.atr, st["tp"])
            elif action == "BE":
                ok = m & (c > P.e) & (P.e > st["sl"])
                st["sl"] = np.where(ok, P.e, st["sl"])
                if avail_out is not None:
                    avail_out[:] = ok
            elif action == "TRAIL":
                lvl = P.h[:, max(0, j - 3):j + 1].max(axis=1) - P.atr
                ok = m & (lvl < c) & (lvl > st["sl"])
                st["sl"] = np.where(ok, lvl, st["sl"])
                trail_on[:] = ok
                if avail_out is not None:
                    avail_out[:] = ok
        if action == "TRAIL" and b >= k:
            lvl = st["runmax"] - P.atr
            tight = trail_on & al & (lvl > st["sl"])
            st["sl"] = np.where(tight, lvl, st["sl"])
    return hook


def rule_hook(arm: str, param: float):
    """The one-factor RULE arms, evaluated at every bar close (price-triggered), applied from the next bar."""
    state = {}

    def hook(b, st):
        P = st["P"]
        al = st["alive"]
        j = b - 1
        c = P.c[:, j]
        if arm == "be":
            hit = al & (c >= P.e + BE_R * P.risk) & (st["sl"] < P.e)
            st["sl"] = np.where(hit, P.e, st["sl"])
        elif arm == "trail":
            on = state.setdefault("on", np.zeros(P.n, bool))
            on |= al & (c >= P.e + TRAIL_ACT_R * P.risk)
            lvl = st["runmax"] - param * P.atr
            tight = on & al & (lvl > st["sl"])
            st["sl"] = np.where(tight, lvl, st["sl"])
        elif arm == "timedecay" and b % 4 == 0:
            dist = BASE_SL - (BASE_SL - param) * (b / H)
            lvl = P.e - dist * P.atr
            ok = al & (lvl > st["sl"]) & (lvl < c)
            st["sl"] = np.where(ok, lvl, st["sl"])
    return hook


# ------------------------------------------------------------------------------------------------ trades
def entry_trades(tab: pd.DataFrame, pl: np.ndarray, ps: np.ndarray, tau: float, df_by_sym: dict) -> pd.DataFrame:
    """ENTRY picks bar + side (prediction > tau); busy until the static-bracket exit (HOLD). Returns one row per trade."""
    t = tab.assign(p_long=pl, p_short=ps).sort_values(["symbol", "i"])
    out = []
    for sym, g in t.groupby("symbol", sort=False):
        df = df_by_sym[sym]
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        cand = g["i"].to_numpy()
        win = cand[:, None] + np.arange(1, H + 1)[None, :]
        Ob, Hh, Lb, Cb = o[win], h[win], lo[win], c[win]
        a = g["atr"].to_numpy()
        entry = Ob[:, 0]
        bars = {}
        for side, nm in ((1, "long"), (-1, "short")):
            _, j, _ = E.bracket_outcome(Ob, Hh, Lb, Cb, entry, a, side, sl_atr=BASE_SL, tp_atr=BASE_TP)
            bars[side] = j
        pl_g, ps_g = g["p_long"].to_numpy(), g["p_short"].to_numpy()
        busy = -1
        for r in range(len(g)):
            if cand[r] <= busy:
                continue
            side = 1 if pl_g[r] >= ps_g[r] else -1
            p = pl_g[r] if side == 1 else ps_g[r]
            if p > tau:
                out.append((sym, int(cand[r]), side, g["ts"].iloc[r]))
                busy = cand[r] + int(bars[side][r])
    return pd.DataFrame(out, columns=["symbol", "i", "side", "ts"])


def gather(trades: pd.DataFrame, df_by_sym: dict, atr_by: pd.DataFrame) -> Paths:
    parts = {k: [] for k in ("o", "h", "l", "c", "t0", "topen", "atr", "side")}
    order = []
    for sym, g in trades.groupby("symbol", sort=False):
        df = df_by_sym[sym]
        o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        t_ns = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
        i = g["i"].to_numpy()
        win = i[:, None] + np.arange(1, H + 1)[None, :]
        parts["o"].append(o[win]); parts["h"].append(h[win]); parts["l"].append(lo[win]); parts["c"].append(c[win])
        parts["t0"].append(t_ns[i + 1] / 1e9); parts["topen"].append(t_ns[win] / 1e9)
        parts["atr"].append(atr_by.loc[g.index].to_numpy()); parts["side"].append(g["side"].to_numpy())
        order.append(g.index.to_numpy())
    cat = {k: np.concatenate(v) for k, v in parts.items()}
    return Paths(cat["o"], cat["h"], cat["l"], cat["c"], cat["atr"], cat["side"], cat["t0"], cat["topen"]), np.concatenate(order)


# ------------------------------------------------------------------------------------------------ labels and features
def label_actions(P: Paths) -> dict:
    """HOLD outcome plus, for each check-in k and action a, the paired delta net R and availability."""
    base = simulate(P)
    lab = {"base": base, "delta": {}, "avail": {}}
    everyone = np.ones(P.n, bool)
    for k in CHECKINS:
        for a in LEARNED:
            av = np.zeros(P.n, bool)
            r = simulate(P, action_hook(k, a, everyone, av))
            alive = base["bars"] > k
            ok = alive & (av if a in ("BE", "TRAIL") else True)
            lab["delta"][(k, a)] = np.where(ok, r["net"] - base["net"], np.nan)
            lab["avail"][(k, a)] = ok
    return lab


STATE_COLS = ["open_r", "bars_held", "mfe_r", "mae_r", "dist_sl_atr", "dist_tp_atr", "side_n", "ret_since_entry_atr"]


def checkin_table(trades: pd.DataFrame, P: Paths, lab: dict, tab: pd.DataFrame) -> pd.DataFrame:
    """One row per (trade, check-in) with the trade still alive: market features at the check-in bar (the tab row of the same
    symbol at index i+k, all <= that bar's close) + trade state + the paired deltas."""
    base = lab["base"]
    feat = tab.set_index(["symbol", "i"])[E.FEATURES]
    rows = []
    for k in CHECKINS:
        alive = np.where(base["bars"] > k)[0]
        if not len(alive):
            continue
        tr = trades.iloc[alive]
        key = pd.MultiIndex.from_arrays([tr["symbol"].to_numpy(), tr["i"].to_numpy() + k])
        f = feat.reindex(key).reset_index(drop=True)
        j = k - 1
        c = P.c[alive, j]
        e, risk, atr = P.e[alive], P.risk[alive], P.atr[alive]
        run_h = P.h[alive, :k].max(axis=1)
        run_l = P.l[alive, :k].min(axis=1)
        d = pd.DataFrame({
            "open_r": (c - e) / risk, "bars_held": k, "mfe_r": (run_h - e) / risk, "mae_r": (run_l - e) / risk,
            "dist_sl_atr": (c - (e - BASE_SL * atr)) / atr, "dist_tp_atr": ((e + BASE_TP * atr) - c) / atr,
            "side_n": P.side[alive], "ret_since_entry_atr": (c - e) / atr})
        d = pd.concat([f, d], axis=1)
        d["trade"] = alive
        d["k"] = k
        d["ts"] = tr["ts"].to_numpy()
        d["symbol"] = tr["symbol"].to_numpy()
        for a in LEARNED:
            d[f"d_{a}"] = lab["delta"][(k, a)][alive]
            d[f"av_{a}"] = lab["avail"][(k, a)][alive]
        rows.append(d)
    out = pd.concat(rows, ignore_index=True)
    return out.dropna(subset=E.FEATURES[:6])


MODEL_COLS = E.FEATURES + STATE_COLS


def fit_heads(train: pd.DataFrame, actions: list[str]) -> dict:
    import lightgbm as lgb
    heads = {}
    for a in actions:
        sub = train[train[f"av_{a}"] & train[f"d_{a}"].notna()]
        m = lgb.LGBMRegressor(**E.LGB_PARAMS)
        m.fit(sub[MODEL_COLS], sub[f"d_{a}"])
        heads[a] = m
    return heads


def predict_heads(heads: dict, rows: pd.DataFrame) -> pd.DataFrame:
    # provenance: predict — LGBMRegressor.predict is the regressed delta net R of that action, not a probability
    return pd.DataFrame({a: np.where(rows[f"av_{a}"], m.predict(rows[MODEL_COLS]), -np.inf) for a, m in heads.items()}, index=rows.index)


def choose(pred: pd.DataFrame, margin: float) -> pd.Series:
    """Per check-in row: the best action if its predicted delta exceeds the margin, else HOLD."""
    best = pred.idxmax(axis=1)
    top = pred.max(axis=1)
    return best.where(top > margin, "HOLD")


def realised(rows: pd.DataFrame, trades_n: int, P: Paths, base: dict, action_by_row: pd.Series) -> dict:
    """Apply, per trade, the FIRST check-in at which the policy acts (a trade is managed once; later check-ins of that trade are
    ignored), and re-simulate the whole path. Returns the managed net R per trade."""
    acts = action_by_row[action_by_row != "HOLD"]
    first = rows.loc[acts.index].assign(act=acts).sort_values("k").drop_duplicates("trade")
    n_act = {a: 0 for a in LEARNED}
    acted = np.zeros(trades_n, bool)
    managed = base["net"].copy()
    gross, bars, mfe = base["gross"].copy(), base["bars"].copy(), base["mfe"].copy()
    for (k, a), g in first.groupby(["k", "act"]):
        mask = np.zeros(trades_n, bool)
        mask[g["trade"].to_numpy()] = True
        r = simulate(P, action_hook(int(k), a, mask))
        managed[mask] = r["net"][mask]
        gross[mask], bars[mask], mfe[mask] = r["gross"][mask], r["bars"][mask], r["mfe"][mask]
        n_act[a] += int(mask.sum())
        acted |= mask
    return {"net": managed, "gross": gross, "bars": bars, "mfe": mfe, "n_actions": n_act, "acted": acted}


# ------------------------------------------------------------------------------------------------ stats
def stats(net, base_net, symbols) -> dict:
    d = net - base_net
    return {"n": int(len(net)), "mean_net_r": float(np.mean(net)), "delta_vs_hold": float(np.mean(d)),
            "win_rate": float(np.mean(net > 0)), "p05_net_r": float(np.percentile(net, 5)), "min_net_r": float(np.min(net)),
            "n_symbols": int(len(set(symbols))), "share_changed": float(np.mean(np.abs(d) > 1e-12))}


def paired_boot(d: np.ndarray, seed: int = E.SEED) -> list:
    rng = np.random.default_rng(seed)
    n = len(d)
    ms = [float(d[rng.integers(0, n, n)].mean()) for _ in range(BOOT)]
    return [float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5))]


def giveback(res: dict) -> float:
    return float(np.mean(np.maximum(res["mfe"] - res["gross"], 0.0)))


def month_split(ts, d) -> dict:
    m = pd.Series(d).groupby(pd.to_datetime(ts, utc=True).strftime("%Y-%m").to_numpy())
    return {k: {"n": int(v.count()), "delta": round(float(v.mean()), 4)} for k, v in m}


# ------------------------------------------------------------------------------------------------ run
def build_world(a, tau):
    syms = E.universe()
    if a.smoke:
        syms = sorted(set(syms[:9]) | {"BTCUSDT"})
    cache = Path(a.cache)
    E.fetch(cache, syms, end=E.END)     # E.fetch's default end is bound at import: always pass it (smoke would otherwise pull the sealed window)
    tab = E.build_table(cache, syms)
    if a.smoke and tab.ts.max() >= pd.Timestamp("2025-10-01", tz="UTC"):
        raise RuntimeError("smoke run saw the sealed held-out window; refusing")
    df_by = {s: pd.read_pickle(cache / f"{s}.pkl").reset_index(drop=True) for s in syms}
    hs = pd.Timestamp(E.HOLDOUT_START, tz="UTC")
    dev = tab[tab.ts < hs]
    # dev ENTRY OOS predictions: the c692-01 walk-forward folds (identical recipe), then the held-out final fit
    bounds = [pd.Timestamp(x, tz="UTC") for x in E.DEV_FOLDS] + [hs]
    dev_tr = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        test = dev[(dev.ts >= lo) & (dev.ts < hi - pd.Timedelta(hours=H + 1))]
        pl, ps = E.fit_predict(E.purge_train(dev, lo), test)
        tr = entry_trades(test.reset_index(drop=True), pl, ps, tau, df_by)
        tr["fold"] = str(lo.date())
        dev_tr.append(tr)
        print(f"ENTRY dev fold {lo.date()} trades={len(tr)}", flush=True)
    dev_trades = pd.concat(dev_tr, ignore_index=True)
    test = tab[tab.ts >= hs].reset_index(drop=True)
    pl, ps = E.fit_predict(E.purge_train(dev, hs), test)
    ho_trades = entry_trades(test, pl, ps, tau, df_by)
    return tab, df_by, dev_trades, ho_trades


def atr_series(tab: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    key = tab.set_index(["symbol", "i"])["atr"]
    v = key.reindex(pd.MultiIndex.from_arrays([trades["symbol"], trades["i"]])).to_numpy()
    return pd.DataFrame({"atr": v}, index=trades.index)["atr"]


def run(a) -> int:
    t0 = time.time()
    if a.smoke:      # DEV-ONLY plumbing check: a pseudo held-out inside the dev window; the sealed 2025-10+ window is never fetched
        global MANAGE_FOLDS
        E.START, E.END, E.HOLDOUT_START = "2021-07-01", "2025-03-31", "2024-10-01"
        E.DEV_FOLDS = ["2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2024-04-01"]
        MANAGE_FOLDS = E.DEV_FOLDS[2:]
        tau = 0.1
    else:
        tau = json.loads(Path(a.entry_summary).read_text())["walk_forward"]["tau_star"]
    if tau is None:
        raise RuntimeError("ENTRY summary has no tau_star")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tab, df_by, dev_tr, ho_tr = build_world(a, tau)
    dev_tr = dev_tr.sort_values(["symbol", "i"], kind="stable").reset_index(drop=True)   # Paths order == trades order
    ho_tr = ho_tr.sort_values(["symbol", "i"], kind="stable").reset_index(drop=True)
    print(f"dev trades={len(dev_tr)} heldout trades={len(ho_tr)} tau={tau} t={time.time()-t0:.0f}s", flush=True)
    res = (arm_rule if a.arm in ("be", "trail", "timedecay") else arm_model)(a, tab, df_by, dev_tr, ho_tr)
    res.update({"schema": SCHEMA, "unit": a.unit, "arm": a.arm, "entry_tau": tau, "git_sha": E._git_sha(),
                "elapsed_s": round(time.time() - t0)})
    v, why = res.pop("verdict"), res.pop("why")
    (out / "summary.json").write_text(json.dumps({**res, "verdict": v, "why": why}, indent=1, default=str) + "\n")
    vj = {"verdict": v, "read_state": "measured", "n": res["heldout"]["n"] if res.get("heldout") else 0, "measurement": res,
          "note": why, "population": (f"{a.arm}: frozen ENTRY (tau {tau}) trades, static {BASE_SL}/{BASE_TP} ATR bracket, 24h, held-out "
                                      f"{E.HOLDOUT_START}..{E.END}, 60-perp bp2-f4271084b120, full cost stack, paired vs hold-to-bracket")}
    (out / "verdict.json").write_text(json.dumps(vj, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": v, "why": why}), flush=True)
    return 0


def _sim_rule(arm, param, P):
    return simulate(P, rule_hook(arm, param))


def arm_rule(a, tab, df_by, dev_tr, ho_tr) -> dict:
    grid = {"be": [BE_R], "trail": TRAIL_GRID, "timedecay": DECAY_GRID}[a.arm]
    dP, d_idx = gather(dev_tr, df_by, atr_series(tab, dev_tr))
    dev_base = simulate(dP)
    dev_rows = {}
    for g in grid:
        r = _sim_rule(a.arm, g, dP)
        dev_rows[g] = float(np.mean(r["net"] - dev_base["net"]))
    chosen = max(grid, key=lambda g: (dev_rows[g], g))
    dev_delta = dev_rows[chosen]
    res = {"dev": {"trades": int(len(dev_tr)), "delta_by_param": {str(k): round(v, 5) for k, v in dev_rows.items()},
                   "chosen_param": chosen, "chosen_dev_delta": dev_delta}, "heldout": None}
    if dev_delta <= 0:
        res.update(verdict="fail", why=f"dev delta {dev_delta:+.5f} <= 0 for the dev-chosen parameter {chosen}: not read on the held-out (registered)")
        return res
    claim = claim_read(a, f"{a.arm}-{chosen}")
    hP, h_idx = gather(ho_tr, df_by, atr_series(tab, ho_tr))
    hb = simulate(hP)
    r = _sim_rule(a.arm, chosen, hP)
    d = r["net"] - hb["net"]
    sy = ho_tr.loc[h_idx, "symbol"].to_numpy()
    ts = ho_tr.loc[h_idx, "ts"].to_numpy()
    s = stats(r["net"], hb["net"], sy)
    ci = paired_boot(d)
    res["heldout"] = {**s, "hold": stats(hb["net"], hb["net"], sy), "delta_ci95": ci, "giveback_r": giveback(r), "giveback_r_hold": giveback(hb),
                      "by_month_delta": month_split(ts, d), "reason_counts": {str(k): int(v) for k, v in pd.Series(r["reason"]).value_counts().items()}}
    res["variants_read_on_window"] = (claim or {}).get("variants_on_window")
    if s["n"] < MIN_TRADES or s["n_symbols"] < MIN_SYMBOLS:
        v, why = "indeterminate", f"held-out trades={s['n']} / symbols={s['n_symbols']} below floor"
    elif s["delta_vs_hold"] > 0 and ci[0] > 0:
        v, why = "pass", f"delta vs hold-to-bracket {s['delta_vs_hold']:+.4f} R/trade, CI95 [{ci[0]:+.4f}, {ci[1]:+.4f}] > 0 at n={s['n']} (param {chosen})"
    else:
        v, why = "fail", f"delta vs hold-to-bracket {s['delta_vs_hold']:+.4f} R/trade, CI95 [{ci[0]:+.4f}, {ci[1]:+.4f}] does not clear 0 at n={s['n']} (param {chosen})"
    res.update(verdict=v, why=why)
    return res


def claim_read(a, model_id: str) -> dict | None:
    """Claim the sealed window ONCE per model (holdout_lock). The runner does not commit the repo ledger, so the claim is made
    against a COPY inside the out dir (which lands with the result); the lane appends that line to comms/research/holdout_reads.jsonl."""
    if a.smoke:
        return None
    import shutil

    import holdout_lock as HL
    led = Path(a.out) / "holdout_reads.jsonl"
    if not led.exists() and HL.LEDGER.exists():
        shutil.copy(HL.LEDGER, led)
    return HL.claim_read(model_id=f"MANAGE-{model_id}", start=E.HOLDOUT_START, end=E.END, unit=a.unit, reader=a.reader, ledger=led)


def arm_model(a, tab, df_by, dev_tr, ho_tr) -> dict:
    actions = LEARNED if a.arm == "manage" else SL_ONLY
    dP, _ = gather(dev_tr, df_by, atr_series(tab, dev_tr))
    dlab = label_actions(dP)
    dev_rows = checkin_table(dev_tr, dP, dlab, tab)
    # dev walk-forward for the margin: expanding folds over MANAGE_FOLDS, trade-level purge by exit time
    dev_tr = dev_tr.reset_index(drop=True)
    bounds = [pd.Timestamp(x, tz="UTC") for x in MANAGE_FOLDS] + [pd.Timestamp(E.HOLDOUT_START, tz="UTC")]
    fold_net = {m: [] for m in MARGIN_GRID}
    fold_base, n_by_margin = [], {m: 0 for m in MARGIN_GRID}
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        cut = lo - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=H + 1)
        tr_rows = dev_rows[dev_rows.ts < cut]
        te_rows = dev_rows[(dev_rows.ts >= lo) & (dev_rows.ts < hi - pd.Timedelta(hours=H + 1))]
        if len(tr_rows) < 5000 or te_rows.empty:
            continue
        heads = fit_heads(tr_rows, actions)
        pred = predict_heads(heads, te_rows)
        te_trades = np.unique(te_rows["trade"])
        for m in MARGIN_GRID:
            act = choose(pred, m)
            r = realised(te_rows, len(dev_tr), dP, simulate(dP), act)
            d = (r["net"] - simulate(dP)["net"])[te_trades]
            fold_net[m].append(d)
            n_by_margin[m] += int((act != "HOLD").sum())
        print(f"MANAGE dev fold {lo.date()} done", flush=True)
    dev_delta = {m: float(np.mean(np.concatenate(v))) if v else None for m, v in fold_net.items()}
    elig = [m for m in MARGIN_GRID if dev_delta[m] is not None and n_by_margin[m] >= 1]
    margin = max(elig, key=lambda m: (dev_delta[m], m)) if elig else None
    res = {"dev": {"delta_by_margin": {str(m): (None if v is None else round(v, 5)) for m, v in dev_delta.items()},
                   "actions_by_margin": n_by_margin, "chosen_margin": margin}, "heldout": None}
    if margin is None or dev_delta[margin] <= 0:
        res.update(verdict="fail", why=f"dev walk-forward delta vs hold <= 0 at every margin (best {margin}: {dev_delta.get(margin)}): not read on the held-out (registered)")
        return res
    claim = claim_read(a, a.arm)
    heads = fit_heads(dev_rows[dev_rows.ts < pd.Timestamp(E.HOLDOUT_START, tz="UTC") - pd.Timedelta(days=E.EMBARGO_DAYS) - pd.Timedelta(hours=H + 1)], actions)
    ho_tr = ho_tr.reset_index(drop=True)
    hP, _ = gather(ho_tr, df_by, atr_series(tab, ho_tr))
    hlab = label_actions(hP)
    hrows = checkin_table(ho_tr, hP, hlab, tab)
    pred = predict_heads(heads, hrows)
    act = choose(pred, margin)
    hb = hlab["base"]
    r = realised(hrows, len(ho_tr), hP, hb, act)
    d = r["net"] - hb["net"]
    sy = ho_tr["symbol"].to_numpy()
    s = stats(r["net"], hb["net"], sy)
    n_act = int(r["acted"].sum())
    s["n_actions"] = r["n_actions"]
    s["mean_delta_per_nonhold_action"] = float(d[r["acted"]].mean()) if n_act else None
    ci = paired_boot(d)
    # controls: matched random (same count and type of actions at random valid check-ins of the SAME trades) and best static action
    rng = np.random.default_rng(E.SEED)
    draws = []
    types = [x for x in act[act != "HOLD"].tolist()]
    valid_idx = {a_: hrows.index[hrows[f"av_{a_}"]].to_numpy() for a_ in LEARNED}
    for _ in range(200):
        fake = pd.Series("HOLD", index=hrows.index)
        for a_ in set(types):
            cnt = types.count(a_)
            pick = rng.choice(valid_idx[a_], size=min(cnt, len(valid_idx[a_])), replace=False)
            fake.loc[pick] = a_
        rr = realised(hrows, len(ho_tr), hP, hb, fake)
        draws.append(float(np.mean(rr["net"] - hb["net"])))
    static = {}
    for a_ in LEARNED:
        fk = pd.Series("HOLD", index=hrows.index)
        first = hrows[hrows[f"av_{a_}"] & (hrows.k == 8)]
        fk.loc[first.index] = a_
        rr = realised(hrows, len(ho_tr), hP, hb, fk)
        static[f"{a_}_at_8h"] = float(np.mean(rr["net"] - hb["net"]))
    res["heldout"] = {**s, "hold": stats(hb["net"], hb["net"], sy), "delta_ci95": ci, "giveback_r": giveback(r), "giveback_r_hold": giveback(hb),
                      "by_month_delta": month_split(ho_tr["ts"].to_numpy(), d),
                      "matched_random_delta": {"draws": 200, "mean": float(np.mean(draws)), "p95": float(np.percentile(draws, 95))},
                      "static_single_action_delta_reported": static, "action_mix_checkins": pd.Series(act).value_counts().to_dict()}
    res["variants_read_on_window"] = (claim or {}).get("variants_on_window")
    res["proposal_eligible"] = bool(s["delta_vs_hold"] > 0 and ci[0] > 0)
    if s["n"] < MIN_TRADES or s["n_symbols"] < MIN_SYMBOLS:
        v, why = "indeterminate", f"held-out trades={s['n']} / symbols={s['n_symbols']} below floor"
    elif a.arm == "manage":
        ok = s["mean_net_r"] >= 0 and (s["mean_delta_per_nonhold_action"] is None or s["mean_delta_per_nonhold_action"] >= 0)
        v = "pass" if ok else "fail"
        why = (f"managed mean net R/trade {s['mean_net_r']:+.4f}, delta/non-HOLD action {s['mean_delta_per_nonhold_action']}, delta vs hold "
               f"{s['delta_vs_hold']:+.4f} CI95 {ci} at n={s['n']}; proposal_eligible={res['proposal_eligible']}")
    else:
        ok = s["delta_vs_hold"] > 0 and ci[0] > 0
        v = "pass" if ok else "fail"
        why = f"delta vs hold-to-bracket {s['delta_vs_hold']:+.4f} R/trade, CI95 [{ci[0]:+.4f}, {ci[1]:+.4f}] at n={s['n']} (margin {margin})"
    res.update(verdict=v, why=why)
    return res


# ------------------------------------------------------------------------------------------------ self-test
def _synthetic(n=40, seed=1):
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0, 0.6, (n, H + 1)), axis=1)
    o = base[:, 1:] + 0.0
    c = base[:, 1:] + rng.normal(0, 0.1, (n, H))
    h = np.maximum(o, c) + np.abs(rng.normal(0, 0.3, (n, H)))
    lo = np.minimum(o, c) - np.abs(rng.normal(0, 0.3, (n, H)))
    side = rng.choice([1, -1], n)
    atr = np.full(n, 1.0)
    t_open = 1.7e9 + np.arange(H)[None, :] * 3600.0 + np.zeros((n, 1))
    return Paths(o, h, lo, c, atr, side, t_open[:, 0], t_open), (o, h, lo, c)


def _self_test() -> None:
    P, (o, h, lo, c) = _synthetic()
    base = simulate(P)
    assert len(base["net"]) == P.n and np.isfinite(base["net"]).all()
    # 1. the HOLD path equals ml_decision_entry.bracket_outcome (same first-passage / tie / gap rules), long and short
    for side in (1, -1):
        m = P.side == side
        px, j, _ = E.bracket_outcome(o[m], h[m], lo[m], c[m], o[m][:, 0], P.atr[m], side, sl_atr=BASE_SL, tp_atr=BASE_TP)
        gross = side * (px - o[m][:, 0]) / P.risk[m]
        assert np.allclose(gross, base["gross"][m], atol=1e-9), (side, gross[:4], base["gross"][m][:4])
        assert (j == base["bars"][m]).all()
    # 2. an action at k never touches a trade that already exited at or before k
    ev = np.ones(P.n, bool)
    done = base["bars"] <= 8
    for a_ in LEARNED:
        r = simulate(P, action_hook(8, a_, ev))
        assert np.allclose(r["net"][done], base["net"][done]), a_
    # 3. CLOSE exits at bar k and is labelled reason 3
    r = simulate(P, action_hook(8, "CLOSE", ev))
    live = base["bars"] > 8
    assert (r["bars"][live] == 8).all() and (r["reason"][live] == 3).all()
    # 4. BE is available only where the bar-k close is above entry (long coordinates)
    av = np.zeros(P.n, bool)
    simulate(P, action_hook(8, "BE", ev, av))
    assert (av <= (P.c[:, 7] > P.e)).all()
    # 5. a rule with an inert parameter is a no-op (time-decay whose final distance equals the base stop)
    assert np.allclose(simulate(P, rule_hook("timedecay", BASE_SL))["net"], base["net"])
    # 6. a BE stop never loses more than the hold stop on a trade it touches (SL moved up only)
    rb = simulate(P, rule_hook("be", 0.0))
    assert (rb["net"] >= base["net"] - 1.0).all()
    # 7. costs: the vectorised stack is positive and funding counts windows crossed
    fee, slip, fund = E._cost_r(np.array([100.0]), np.array([101.0]), np.array([2.0]), np.array([0.0]), np.array([9 * 3600.0]))
    assert fee[0] > 0 and slip[0] > 0 and fund[0] > 0
    print("self-test ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--arm", default="manage", choices=["manage", "be", "trail", "timedecay", "mlsl"])
    ap.add_argument("--entry-summary", default=str(REPO / "comms/research/RQ-20261101-c692-01/local-20261101T0835Z/summary.json"))
    ap.add_argument("--cache", default="/tmp/ml_decision_klines")
    ap.add_argument("--out", default="/tmp/ml_decision_manage_out")
    ap.add_argument("--unit", default="")
    ap.add_argument("--reader", default="research-script-run")
    ap.add_argument("--smoke", action="store_true", help="dev-only plumbing check on 10 symbols; never touches the sealed window")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        _self_test()
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
