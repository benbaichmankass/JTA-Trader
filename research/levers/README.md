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


## ONE schema (unified 2026-11-01, PI-20261101-HIPIPRHQ-0004)

`scripts/research/lever_map.py` writes and reads every map in this directory; there is no second shape. `--backfill` regenerates the
results-derived part (`kind`, `baseline`, `attribution`, `manifest`, `levers.<family>.<lever>.tests`) and **preserves the author block
verbatim** (`HAND_KEYS` in the script: `title`, `declared`, `manifest_notes`, `units`, `status`, `doctrine`, `verdict_so_far`,
`failure_attribution`, `levers_tested`, `lever_families_untested`, `power_note`, `evidence`, `handed_to`). A research CANDIDATE (no
roster leg, so no arm records) has its `attribution` (`read_state: attributed`) and `manifest` (`tested` / `underpowered` / `untested`)
DERIVED from `failure_attribution` + `levers_tested`, so `iteration_orphans.py --levers` and `research_ops_checks.py` read one shape.

* `levers_tested[].family` is free text. It is mapped to one of the nine strategy-leg policy families by `iteration_orphans.policy_family`
  (keyword order in `_FAMILY_ALIASES`); set `lever_family:` on the entry to override (e.g. `scale_invariant_control` for a control that
  varies no cost input and so must not close `sizing_vs_cost`).
* `tested_at_power: false` renders as `u` (tried, **not closed**, still in `remaining`); `true` renders `T`.
* **Append a new test with `lever_map.py --append <subject> --family ... --varied ... --shape ... --unit RQ-... [--at-power]`**, never by hand;
  a repeat of the same unit + family replaces its entry, so a rerun does not double-count.
