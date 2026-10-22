"""RQ-20261022-4de5-01/-02: assemble docs/research/evidence/decision-bar-match-2026-10-22.json from the replay verdicts
and the per-firm prop sim cells
(prop_ev_sim.py, argv identical to prop_ev_grid; re-run: python3 scripts/research/decision_bar_match_assemble.py). Applies RULE-RQ-20261022-4de5-02 (TP) exactly as registered."""
import json, glob, statistics, sys
from pathlib import Path
R = Path(__file__).resolve().parents[2]
S = R / 'comms/research/RQ-20261022-4de5-01/prop'  # <g>/<firm>/<leg>__CFG__seed<n>.json
A = 'comms/research/RQ-20261022-4de5-01'
legs = {}
for p in sorted(glob.glob(str(R / A / '*/verdict.json'))):
    d = json.load(open(p))
    for k, r in d['legs'].items():
        r = dict(r); r['source'] = str(Path(p).relative_to(R)); legs[k] = r
FIRMS = {'breakout_2': ('breakout_turbo_1step', 0.0035), 'tradeify_1': ('tradeify_247_1step', 0.005),
         'velotrade_1': ('velotrade_classic_1step', 0.005)}
def grid(dirpath, leg, ledger):
    """Cells read from <dir>/sims (prop_ev_grid's own layout); graded with prop_ev_grid.grade_pass_all_seeds."""
    sys.path.insert(0, str(R / 'scripts/research'))
    import prop_ev_grid as peg
    g = Path(dirpath)
    cells = []
    for seed in range(1, 6):
        f = g / f'{leg}__CFG__seed{seed}.json'
        if not f.exists():
            continue
        pr = json.load(open(f))['results']['path']
        cells.append({'seed': seed, 'ev': pr['ev_net_usd_per_life'], 'p_net_positive': pr['p_net_positive'],
                      'p_alive_at_horizon': pr.get('p_alive_at_horizon'), 'p_breach_max_dd': pr.get('p_breach_max_dd'),
                      'p_pass_eval': pr.get('p_pass_eval')})
    if not cells:
        return None
    n = sum(1 for l in open(R / ledger) if l.strip())
    med = lambda k: statistics.median(x[k] for x in cells) if all(x[k] is not None for x in cells) else None
    v, why = peg.grade_pass_all_seeds({'CFG': {c['seed']: c for c in cells}}, n=n, n_floor=88, p_floor=0.0)
    if len(cells) < 5:
        v, why = 'indeterminate', f'only {len(cells)} of 5 seeds ran'
    return {'n_trades': n, 'trades_file': ledger, 'cells': cells, 'seed_median_ev': med('ev'),
            'seed_median_p_alive': med('p_alive_at_horizon'), 'seed_median_p_breach_max_dd': med('p_breach_max_dd'),
            'pass_all_seeds': v, 'grade_reason': why, 'all_ev_pos': all(x['ev'] > 0 for x in cells),
            'harness': 'prop_ev_sim.py per cell, argv identical to prop_ev_grid (RULE-P5-GATE-BRK-PER-LEG common/arm args)'}
L6 = A + '/eth/arms/trend_donchian_eth_prop__A_closed__trades.jsonl'
L25 = A + '/eth/arms/trend_donchian_eth_prop__tp2.5__A_closed__trades.jsonl'
LS = A + '/sol/arms/trend_donchian_sol_prop__A_closed__trades.jsonl'
prop = {'trend_donchian_eth_prop': {}, 'trend_donchian_sol_prop': {}, 'eth_prop_tp2.5': {}}
for f in FIRMS:
    prop['trend_donchian_eth_prop'][f] = grid(S / f'eth_T6/{f}', 'trend_donchian_eth_prop', L6)
    prop['eth_prop_tp2.5'][f] = grid(S / f'eth_T25/{f}', 'trend_donchian_eth_prop', L25)
    prop['trend_donchian_sol_prop'][f] = grid(S / f'sol/{f}', 'trend_donchian_sol_prop', LS)
# RULE-RQ-20261022-4de5-02
tp = {'rule': 'RULE-RQ-20261022-4de5-02', 'bar': 'closed (RQ-20261022-4de5-01 SWITCH_TO_CLOSED)', 'per_firm': {}}
ok_all, indet = True, False
for f in FIRMS:
    t6, t25 = prop['trend_donchian_eth_prop'][f], prop['eth_prop_tp2.5'][f]
    if not t6 or not t25 or t25['n_trades'] < 88 or len(t25['cells']) < 5 or len(t6['cells']) < 5 or t25['seed_median_p_alive'] is None:
        indet = True; tp['per_firm'][f] = {'state': 'INDETERMINATE'}; continue
    a = t25['pass_all_seeds'] == 'pass'
    b = t25['seed_median_p_alive'] >= t6['seed_median_p_alive'] - 0.02
    c = t25['seed_median_ev'] >= t6['seed_median_ev'] - 0.10 * abs(t6['seed_median_ev'])
    tp['per_firm'][f] = {'a_ev_pos_all_seeds': a, 'b_survival_noninferior': b, 'c_ev_noninferior': c,
                         'T25_median_ev': t25['seed_median_ev'], 'T6_median_ev': t6['seed_median_ev'],
                         'T25_median_p_alive': t25['seed_median_p_alive'], 'T6_median_p_alive': t6['seed_median_p_alive']}
    ok_all &= a and b and c
tp['verdict'] = 'INDETERMINATE' if indet else ('DECLARE_2P5' if ok_all else 'NOT_DECLARED')
# prop gate per firm for the adopted bar (closed, tp as configured)
gate = {lg: {f: (prop[lg][f]['pass_all_seeds'] if prop[lg][f] else 'not_run') for f in FIRMS}
        for lg in ('trend_donchian_eth_prop', 'trend_donchian_sol_prop')}
out = {'units': ['RQ-20261022-4de5-01', 'RQ-20261022-4de5-02'],
       'rules': ['RULE-RQ-20261022-4de5-01', 'RULE-RQ-20261022-4de5-02'],
       'generated': '2026-10-22', 'lane': 'DECISION-BAR-MATCH (manager session_01CSwhZWiw15rVCkjsJ8Cpuh)',
       'data_source': 'Binance USD-M perp 1m klines (data.binance.vision), LABELLED PROXY for Bybit; window end pinned 2026-10-20 23:59Z',
       'population': ('5 real-money/prop legs whose traded bar (forming) != evidence bar (closed): xrp_pullback_2h, '
                      'ada_pullback_2h, trend_donchian_eth_4h (bybit_2), trend_donchian_sol_prop (bybit_2 + breakout_2 + '
                      'tradeify_1 + velotrade_1), trend_donchian_eth_prop (breakout_2 + tradeify_1 + velotrade_1); '
                      'trend_donchian_xrp_4h already closed (matched, not graded); alpaca_live slv/iaum_pullback_1d not '
                      'measurable here (DECISION-BAR-SESSION-INSTRUMENT)'),
       'verdicts': {k: {'better': r['grade']['better'], 'verdict': r['grade']['verdict'], 'reason': r['grade']['reason'],
                        'folds_closed': r['grade']['folds_closed'], 'folds_forming': r['grade']['folds_forming'],
                        'delta_r_full_closed_minus_forming': r['grade']['delta_r_full'],
                        'full_closed': r['A_closed'], 'full_forming': r['B_forming'],
                        'record_window': (r['record_restatement'] or {}).get('window'),
                        'record_window_closed': (r['record_restatement'] or {}).get('proxy_closed'),
                        'record_window_forming': (r['record_restatement'] or {}).get('proxy_forming')}
                    for k, r in legs.items()},
       'prop_survival_gate_closed_bar': gate,
       'tp_eth_prop_2p5': tp,
       'prop_grids': prop,
       'legs': legs}
dst = R / 'docs/research/evidence/decision-bar-match-2026-10-22.json'
dst.write_text(json.dumps(out, indent=1, default=str) + '\n')
print(json.dumps({'verdicts': {k: v['verdict'] for k, v in out['verdicts'].items()}, 'gate': gate, 'tp': tp}, indent=1, default=str))
