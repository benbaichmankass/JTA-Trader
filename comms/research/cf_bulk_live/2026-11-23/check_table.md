## C14 Counterfactual CHECK table — run paths_close
population: 992 graded of 2733 closed packages (whole run history); not graded: {'no_filled_leg': 646, 'legs_not_closed': 122, 'no_bars_non_crypto': 205, 'pairs_two_leg': 716, 'horizon_not_passed': 52}
fidelity (registered rule abs_gap_r <= 0.1 on >= 80%): overall FAIL 41.3% within tol, n=987, median abs gap +0.141 R

| leg | n | fidelity (frac, n) | actual net R | replayed net R | best arm vs replay (n, ΔR, 95% CI, of N searched) | readable |
|---|---|---|---|---|---|---|
| ict_scalp_avax_5m | 94 | FAIL (24.5%, 94) | -0.091 | -0.011 | less_without_action_1 (n=8, +0.384, [-0.2429, 1.0229], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_sol_5m | 65 | FAIL (18.5%, 65) | +0.066 | -0.304 | alt_sl1.5x_tp3R (n=56, +0.298, [-0.0959, 0.7293], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_5m | 55 | FAIL (54.5%, 55) | +0.144 | -0.068 | alt_sl1.5x_tp2R (n=47, +0.237, [-0.1476, 0.6152], of 29) | no: ESTIMATED_LOW_FIDELITY |
| htf_pullback_trend_2h | 51 | FAIL (29.4%, 51) | -2.371 | -0.285 | alt_sl0.75x_tp3R (n=47, +0.205, [-0.2005, 0.674], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_xrp_15m | 51 | FAIL (31.4%, 51) | -0.187 | -0.203 | more_atr_trail_1.5x (n=51, +0.010, [-0.2698, 0.2496], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_xrp_5m | 50 | FAIL (22.0%, 50) | -0.749 | -0.824 | alt_sl1.25x_tp3R (n=47, +0.236, [-0.2711, 0.7534], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ada_pullback_2h | 48 | FAIL (64.6%, 48) | +0.126 | +0.110 | alt_sl0.75x_tp4R (n=46, +0.095, [-0.3689, 0.5871], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_eth_15m | 48 | FAIL (31.9%, 47) | +0.186 | -0.009 | alt_sl0.75x_tp6R (n=44, +0.420, [-0.2864, 1.0753], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ict_scalp_sol_15m | 46 | FAIL (17.4%, 46) | +0.242 | -0.120 | alt_sl1x_tp2R (n=46, +0.046, [-0.1801, 0.2667], of 29) | no: ESTIMATED_LOW_FIDELITY |
| eth_pullback_2h | 45 | FAIL (46.7%, 45) | +0.064 | -0.065 | alt_sl1.5x_tp2R (n=40, +0.174, [-0.1771, 0.5236], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_eth | 37 | FAIL (51.3%, 37) | -0.060 | -0.121 | alt_sl0.75x_tp3R (n=37, +0.211, [-0.1325, 0.5796], of 30) | no: ESTIMATED_LOW_FIDELITY |
| xrp_pullback_2h | 36 | FAIL (57.1%, 35) | -0.045 | -0.149 | more_rule_ladder_be1_lock2 (n=32, +0.234, [-0.03, 0.5456], of 29) | no: ESTIMATED_LOW_FIDELITY |
| ml_entry | 36 | PASS (80.6%, 36) | -0.041 | -0.063 | alt_sl0.75x_tp6R (n=33, +0.236, [-0.407, 0.9174], of 28) | yes |
| trend_donchian_ada_4h | 33 | FAIL (39.4%, 33) | +0.354 | +0.098 | less_without_action_1 (n=19, +0.461, [-0.1402, 1.0518], of 29) | no: ESTIMATED_LOW_FIDELITY |
| e4_oi_shock_1h | 33 | FAIL (39.4%, 33) | +0.204 | +0.123 | less_without_action_3 (n=5, +0.476, [-0.5035, 1.5355], of 26) | no: ESTIMATED_LOW_FIDELITY |
| sol_pullback_2h | 31 | FAIL (31.0%, 29) | -0.115 | +0.082 | more_atr_trail_1.5x (n=31, -0.198, [-0.3202, -0.0711], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_avax_4h | 28 | FAIL (46.4%, 28) | +0.233 | +0.096 | more_atr_trail_1.5x (n=28, +0.165, [-0.1632, 0.477], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_eth_4h | 28 | FAIL (66.7%, 27) | +0.299 | +0.086 | more_rule_1R_to_0R (n=27, +0.178, [-0.0654, 0.525], of 30) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian | 26 | FAIL (42.3%, 26) | +0.808 | +0.568 | more_rule_ladder_be1_lock2 (n=26, +0.222, [-0.3452, 1.1599], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_sol_4h | 26 | FAIL (50.0%, 26) | +0.298 | +0.072 | alt_sl1.5x_tp3R (n=21, +0.276, [-0.4167, 1.0493], of 29) | no: ESTIMATED_LOW_FIDELITY |
| avax_pullback_2h | 21 | FAIL (33.3%, 21) | -0.336 | -0.310 | more_atr_trail_1.5x (n=21, +0.138, [-0.1324, 0.3949], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_eth_prop | 14 | FAIL (64.3%, 14) | +0.457 | +0.040 | less_without_action_2 (n=8, +0.192, [-0.2948, 0.9014], of 30) | no: ESTIMATED_LOW_FIDELITY |
| claude_desk | 14 | FAIL (42.9%, 14) | +0.507 | +0.574 | alt_sl1.25x_tp6R (n=12, +1.448, [0.0048, 2.8104], of 24) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_xrp_4h | 12 | FAIL (50.0%, 12) | +0.423 | -0.117 | alt_sl0.75x_tp2R (n=12, +0.296, [-0.411, 1.0637], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_sol | 12 | PASS (83.3%, 12) | -0.111 | -0.204 | more_atr_trail_1.5x (n=12, +0.291, [-0.2108, 0.7509], of 29) | yes |
| trend_donchian_1h | 11 | FAIL (63.6%, 11) | +0.021 | +0.011 | alt_sl1.5x_tp4R (n=10, +1.570, [0.4205, 3.0503], of 30) | no: ESTIMATED_LOW_FIDELITY |
| ml_entry_v2 | 10 | FAIL (60.0%, 10) | -0.012 | -0.173 | alt_sl1x_tp3R (n=7, +0.194, [-0.6061, 1.3307], of 22) | no: ESTIMATED_LOW_FIDELITY |
| squeeze_breakout_4h | 8 | INDETERMINATE (37.5%, 8) | -0.392 | -0.567 | more_atr_trail_1.5x (n=8, +0.153, [-0.1708, 0.4647], of 29) | no: ESTIMATED_LOW_FIDELITY |
| fade_breakout_4h | 7 | INDETERMINATE (42.9%, 7) | -0.120 | -0.078 | more_rule_1R_to_0R (n=7, +3.514, [-0.4995, 8.8649], of 29) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_sol_prop | 6 | INDETERMINATE (100.0%, 6) | -0.851 | -0.876 | more_atr_trail_1.5x (n=6, +0.596, [0.405, 0.7634], of 28) | no: ESTIMATED_LOW_FIDELITY |
| eth_pullback_prop_2h | 5 | INDETERMINATE (60.0%, 5) | +0.364 | +0.502 | alt_sl0.75x_tp4R (n=5, +1.043, [0.295, 1.7639], of 28) | no: ESTIMATED_LOW_FIDELITY |
| trend_donchian_xrp_adx25 | 2 | INDETERMINATE (50.0%, 2) | -0.173 | +0.187 | — | no: ESTIMATED_LOW_FIDELITY |
| turtle_soup | 2 | INDETERMINATE (50.0%, 2) | -0.363 | -0.025 | — | no: ESTIMATED_LOW_FIDELITY |
| fvg_range_15m | 1 | INDETERMINATE (0.0%, 1) | -0.012 | -0.191 | — | no: ESTIMATED_LOW_FIDELITY |

Best arm = in-sample maximum over the arms searched; a positive ΔR is a lead for a pre-registered test, not a result. Provenance ESTIMATED. A '—' means it could not be read.
