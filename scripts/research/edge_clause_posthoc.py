#!/usr/bin/env python3
# wiring: manual-only - POST-HOC application of the 2026-11-01 regime-robustness clause to the already-graded RESEARCH-EDGE units (-01,-02,-05). Not pre-registered for them; cannot change a verdict, only add failing items.
import json
import sys
import argparse
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edge_portfolio_discovery as D
import regime_robustness as RR
from src.runtime import execution_costs as xc


def _unused_split(W, ret, F, side_bps):
    Wp, Wn = W.clip(lower=0), W.clip(upper=0)

    def one(Wx):
        return (
            Wx * ret.reindex_like(Wx).fillna(0)
            - Wx * F.reindex_like(Wx).fillna(0)
            - Wx.diff().abs().fillna(0) * side_bps / 1e4
        ).sum(axis=1)

    return one(Wp), one(Wn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.data_root)
    P = D.load_panels(root / "klines_all.pkl")
    close, qv = P["close"], P["qv"]
    ret = close.pct_change()
    fee = xc.resolve_fee_bps_roundtrip("BTCUSDT")
    side = (fee + D.SLIP_BPS_RT) / 2
    ever = set()
    for t in range(0, len(close), 7):
        ever |= set(D.universe_at(qv, close, t, 20))
    F, _ = D.load_funding(sorted(ever), root)
    F = F.reindex(close.index)
    out = {
        "label": "POST-HOC: clause registered 2026-11-01 AFTER these units ran; informational, verdicts unchanged"
    }
    for name, W in (
        ("tsmom_T4", D.tsmom_weights(close, qv, D.TSMOM_CONFIGS["T4"])),
        ("xsec_X1", D.xsec_weights(close, qv, D.XSEC_CONFIGS["X1"])),
    ):
        net, _, _ = D.net_from_weights(W, ret, F, 1.0, fee)
        lg, s = RR.split_sides(W, ret, F, side)
        m = net.index >= D.EVAL_START
        out[name] = RR.clause(net[m], lg[m], s[m], two_sided=True)
    c1 = pd.read_csv(
        Path(a.data_root).parent / "series" / "carry_C1.csv",
        index_col=0,
        parse_dates=True,
    )["net"]
    out["carry_C1"] = RR.clause(c1[c1.index >= D.EVAL_START], two_sided=False)
    out["carry_C1"]["note"] = "one-sided by construction (long spot / short perp)"
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    print(
        json.dumps(
            {
                k: (
                    v.get("clause_pass"),
                    v.get("years_positive"),
                    v.get("top_year_share_of_total"),
                    v.get("long_net_sum"),
                    v.get("short_net_sum"),
                    v.get("subperiod_sums"),
                )
                for k, v in out.items()
                if isinstance(v, dict)
            },
            indent=1,
        )
    )


main()
