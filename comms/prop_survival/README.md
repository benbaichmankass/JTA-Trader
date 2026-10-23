# comms/prop_survival — prop survival-gate records

One file per leg: `comms/prop_survival/<leg>.json`. Read by `prop-roster-gate-guard`
(`scripts/ci/check_prop_roster_gate.py`); a PR adding a leg to a prop roster needs one of these
(plus a Stage-1 soak). Operator rule 2026-10-15: prop clears everything real money clears, PLUS this.

Required fields (fail closed; a PR body is not a record):

| field | meaning |
|---|---|
| `leg` | equals the filename stem |
| `harness` | the EV/survival harness (e.g. `account_compat_matrix -> run_ev_montecarlo`) |
| `ruleset` | the firm ruleset graded under (`config/prop_rulesets/*.yaml`) |
| `ev_net_usd` | number — EV net of the full cost stack |
| `p_breach` | number in [0,1] |
| `n_trades` | integer >= 1 — trades in the graded ledger |
| `decision_rule` | `{id, registered_at, verdict: "pass"}` — the rule registered BEFORE the run |

The directory is empty by design today: `trend_donchian_eth_prop` and `trend_donchian_sol_prop` are
grandfathered by name (grandfather exemption lapses 2026-11-07 / 2026-12-11, row `PROP-GATE-PARITY`; the soak itself is mechanical, 1-2 clean trades, OPERATING-PLAN § 2). Programme 05 nodes `P5-GATE-*` (research/programmes/05-prop.yaml) produce the per-leg inputs for these records.
