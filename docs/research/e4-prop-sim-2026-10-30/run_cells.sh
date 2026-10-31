#!/bin/bash
# one prop_ev_sim cell, same parameters as RQ-20261029-9a2c-01/run_cells.sh; leg = e4 (one leg, one position at a time)
cd "$(dirname "$0")/../../.."
leg=$1; win=$2; acct=$3; arm=$4; seed=$5
case $acct in
 breakout_2) rs=breakout_turbo_1step; risk=0.0035; cap=5; vc=8:3:0.00033;;
 tradeify_1) rs=tradeify_247_1step; risk=0.005; cap=5; vc=8:3:0.00033;;
 velotrade_1) rs=velotrade_classic_1step; risk=0.005; cap=5; vc=6:3:0.0005;;
esac
if [ $arm = cur ]; then c=11.0; s=3.0; sw=0.0003; else IFS=: read c s sw <<<"$vc"; fi
D=docs/research/e4-prop-sim-2026-10-30
python3 scripts/research/prop_ev_sim.py --trades $leg=$D/ledgers/${leg}_${win}.jsonl \
 --ruleset config/prop_rulesets/$rs.yaml --costs breakout --commission-bps-rt $c --slippage-bps-rt $s --swap-daily $sw --swap-model prorated \
 --funded-start fresh --lev-cap $leg=$cap --sizing start --risk-pct $risk --dd-switch-frac 0.8 \
 --seed $seed --lives 1000 --outer 2 --lives-per-outer 100 --modes path --out $D/cells/${leg}__${win}__${acct}__${arm}__s${seed}.json >/dev/null 2>&1
