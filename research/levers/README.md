# research/levers/ - one lever map per failed subject

Operator doctrine (2026-11-01 14:00-14:09Z, relayed by the manager): **nothing that failed is closed or left.** Every result gets a failure
attribution first (where the return was lost - entry, exit, filter, cost - and in which regime, month, symbol and direction). Its lever
response is recorded here. The next tests are one-factor or ablation designs chosen from this map, never a random next idea. A subject is
retired only when every lever family has been tested at power, net of cost, and none moved the outcome; never on attempt count.

One file per subject, `<subject>.yaml`. Keys: `subject`, `units`, `status` (open until retirement), `verdict_so_far`, `failure_attribution`
(`where_lost`, `by_direction`, `by_year`, worst/best months and symbols, `stage`), `levers_tested` (each: `family`, `varied`, `response`,
`shape`, `tested_at_power`), `lever_families_untested`, `power_note`, `evidence`, `handed_to`. Seeded 2026-11-01 by lane RESEARCH-EDGE;
RESEARCH-ITERATE owns the maps from here. `tested_at_power: false` means the response is within the standard error of the window, so the
family is NOT closed by it.
