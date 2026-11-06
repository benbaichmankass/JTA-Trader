# research-ops SKILL.md § "What changed on 2026-10-16 (lane RESEARCH-ENGINE-1016)" — verbatim, archived 2026-11-06 (SKILLS-PRUNE)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · archived history, not instruction.

## What changed on 2026-10-16 (lane RESEARCH-ENGINE-1016)

> ⚠️ **Superseded in part 2026-11-01** (STOP-GENERATED-AUTHORING): `H1-THEME` / `H1-AUTHOR` shortfalls and the floor below are
> DIAGNOSTICS now, not authoring work. What still binds from this section: programme coverage, `RESULTS-UNDISPOSITIONED`, and
> that a ready plan question is drafted (`OPS-AUTHOR-SKIPPED`) -- after THE CORE MANDATE, never to fill a count.

MEASURED 07:15Z: runnable **2** against a computed floor of 50; theme `regime` (weight 5) held **0** queued units;
79 of 112 queued units were generated re-runs; four of the six programme plans (03 STRATEGY, 04 MACRO, 05 PROP,
06 DATA) had **no tree file**, so none of their questions could ever reach the authoring queue; and the last three
passes drafted 1 programme node between them. The weights in `THEMES.yaml` are a share of fire slots **among
themes that hold due work** -- an empty theme gets nothing however heavy it is. Weights are honoured by SUPPLY,
and supply is this pass's step E. So the health check now prints, every dispatch cycle:

- **`H1-THEME <theme>`** -- the floor split by weight, each theme's runnable units (authored + generated; generated
  units credited for at most 40 % of a theme's slice). Each short theme is authoring work for step E: author toward
  the largest shortfall first, from that theme's programme nodes or checklist research rows.
- **`OPS-AUTHOR-SKIPPED`** -- one of the newest three run records drafted no programme node while the authoring
  queue held questions. Step E.0 is **not optional**: when budget is short, draft at least ONE node before step D's
  follow-ups, and record it in the `authoring` block (step F).
- **programme coverage** -- `python3 scripts/research/programme_coverage.py` (guard `programme-coverage`, a
  ratchet): per plan, the questions with no node. An uncovered question is fixed by ADDING a node (a
  `needs_authoring:` line is enough) to `research/programmes/<NN>-*.yaml` -- that is how a plan question becomes
  visible to the machine at all.

- **`RESULTS-UNDISPOSITIONED`** -- `python3 scripts/research/result_disposition_check.py --list`: units whose
  landed results carry no verdict and no OWNED `needs_review` (`grading.owner`). "Read" in the run record is not a
  disposition; each of these gets its rule applied (step D) or an owner (step C). MEASURED 2026-10-16: 19 ungraded,
  24 `needs_review` with no owner.
- **Brief §0 `RESEARCH FLOOR GAP`** -- a gap at the end of your pass is now due work on the manager's brief, computed
  from the queue; your handoff still names it, but the manager acts on §0.

The dispatcher also now ranks **authored before generated inside a theme**, and a recurring unit ages from when it
came **due**, not from its last stamp (a monthly re-run used to come due already "starved").

**PROGRAMME PRIORITY (operator 2026-10-18 ~06:20Z: P1 active trade management + P2 AI trader are "our highest
priority").** `research_compute.yaml` `value.programme_priority: [P1, P2]` (ordered) -- a due unit of a listed
programme ranks first on every backend, above every theme and other programme; only a starved unit precedes it.
When you author for those programmes, set `programme_node.programme` (the emitter does) so the unit is recognised.

**MONEY FIRST across themes (operator 2026-10-18, "Fix now, money first").** Since that day `fair_order` does not
round-robin the themes: a due unit is taken by the router's value score across ALL themes (real-money / prop /
own-losses work first), a starved unit first in any theme, and the THEMES.yaml weight share only breaks an equal
score. Programme nodes (`generated.family: programme:*`) count as asked units. What that means for this pass: a
short theme (`H1-THEME`, `theme_share_min_ratio`) no longer recovers by waiting its turn -- it recovers when you
author units there that carry an honest `value:` block (money at stake, confidence), or on spare capacity, or at
`starve_hours`. Do not loosen the SLO to clear it; author the work.

