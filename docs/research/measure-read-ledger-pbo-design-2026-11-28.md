# Measurement tools: a subject-wide read ledger and PBO/CSCV deflation. Registered design (2026-11-28)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane ML-PRIMARY (session_01AFoLuLpCY5gABbqk3EBUeV), dispatched by Manager Session 2026-11-28b · row `MEASURE-READ-LEDGER-PBO`

**Gates this adds or changes:** none in the build this document registers. Every new number is **reported**: on the grade record, in the ledger file and on the resolver's evidence. Nothing refuses, blocks or changes a bar. Three decisive steps are listed in § 6 as **proposals for the operator**. None is applied, because each would tighten what promotes (No new gates, operator 2026-10-29).

Operator, 2026-11-28 ~09:30Z, popup to Manager Session 2026-11-28b (relayed), verbatim: Frontier = *"Measurement tools, then new families (Recommended)"*. Source item: frontier scan 2026-11-25, walk-through P-6 ([`frontier-scan-2026-11-25.md`](frontier-scan-2026-11-25.md) rows 42–43).

## 1. What already exists (read from the code and files, 2026-11-28 ~09:40Z)

| Instrument | What it counts | Population | Decisive? |
|---|---|---|---|
| `scripts/research/holdout_lock.py` → `comms/research/holdout_reads.jsonl` | Every **claimed** read of an ML family's held-out window. The N-th overlapping read is graded against `bar_for(N)` (Šidák CI / Bailey–López de Prado point hurdle) | 77 claim rows, 13 families (AM-HEADS, BRACKETS, ENTRY, ENTRY-CRYPTO-STRUCT, ENTRY-EQ, ENTRY-EQ-H2H, ENTRY-SAMEBAR, EXEC, MANAGE, PROPML-bv, PROPML-tradeify, PROPML-tradeify_es, TPREV). Largest: AM-HEADS 2026-01-01..11-21 at 18 reads; ENTRY has **17** claimed reads overlapping 2025-10-01..2026-09-30 | yes, inside the graders that call it (principle **M13**, operator 2026-11-05) |
| `scripts/research/trial_ledger.py` | **Configurations** tried per (leg, family) across the m20 corpus, E5 results and evidence records. Deflates each Stage-0 record (DSR, Harvey–Liu haircut) at the family's effective N | every evidence record | **no**: report-only (operator 2026-10-16, *"Measure first (Recommended)"*) |
| `scripts/ops/mandate_resolver.py::_holdout` | The Stage-0 record's **own** `holdout_check.evaluations_on_holdout`, which must equal 1 (0 for `no_discovery`) | the record being promoted | yes, but it trusts the record's self-count |

## 2. The gaps this build closes (each one measured, or stated as unmeasured)

- **G1. Only ML families that call `claim_read` are counted.** Trading legs, levers, regime cells, live-review classes and every harness that reads a fixed window without claiming are invisible to `holdout_reads.jsonl`. For example, `regime_cell_marginal_grade.py` re-reads the same `--since` window for each new cell rule. The scan quoted "27 reads" of ml_entry's window, but the ledger reproduces **17** claimed reads on the overlapping ENTRY window. The difference cannot be attributed from the ledger alone, and that is the gap. *Unmeasured: how many graded results read a window without a claim. Phase 1 measures it (§ 5, test T3).*
- **G2. The resolver trusts the record.** `_holdout` checks that `evaluations_on_holdout == 1` as written by the producer. It never compares that against the reads recorded on the same window.
- **G3. Nothing measures whether the SELECTION overfits.** `trial_ledger` deflates the chosen record by how many configs were tried. It does not ask how often the in-sample winner falls below the median out of sample. That is the probability of backtest overfitting, PBO (Bailey, Borwein, López de Prado & Zhu 2014, CSCV).
- **G4. The per-config series PBO needs are not committed.** The scan says *"the needed per-config series exist for the f1a0 family"*. **Checked: they do not.** `comms/research/RQ-20261124-f1a0-0*/<run>/measurement.json` holds pooled stats, `yearly_delta` (4 values), `n_folds` and a `folds_better` count. It has no per-period series per arm, and no `--emit-trades` file. PBO therefore needs an emit step in the harness first.
- **G5. A conflict with an operator rule.** P-6 says "a window past k reads is **spent**; promotion needs a fresh window". Principle **M13** (operator 2026-11-05: *"We can't just, like, give up on a certain line of research … That's ridiculous"*, popup *"Adopt (Rec.)"*) **replaced** exactly that (the one-read refusal) with "re-reading raises the bar; it is never refused". This build keeps M13. The spend rule (§ 6 **D-B**) is **rejected** (Manager 2026-11-28b, 09:26Z).

## 3. Design A: the subject-wide read ledger (`scripts/research/read_ledger.py`)

**Key.** `(subject, window)`.
- **subject** = the unit's `iteration.subject` (the same id `iteration_orphans.py` and `research/levers/<subject>.yaml` use). Fallback: the holdout family for ML claims; then `leg:<name>` from `measurement.leg`.
- **window** = `[start, end]` plus a symbol scope, from the first source that states it:
  1. a `holdout_reads.jsonl` claim;
  2. `measurement.data_start` / `data_end`;
  3. `measurement.window`;
  4. `--since` / `--until` / `--start` / `--end` in `measurement.argv` or the unit's commands.
  
  A result whose window cannot be resolved is a read of `window: unstated`. It is counted, kept apart, and never dropped. A count that cannot look is not a 0 (`check_collapsed_states`).

**What is a read.** One graded E5 result row (`read_state: measured`) of a unit on a window. A weekly re-ask of the same unit on the same window is **one** read (the same identity as `trial_ledger` source 2). Training-period walk-forward reads are not reads (M13 rule 1). Overlap uses the same `_overlap` / `_syms_overlap` as `holdout_lock`.

**Output.** `comms/research/read_ledger.json`, regenerated by the existing weekly trial-ledger unit (RQ-20261016-6013-01). For each (subject, window) it gives:
- `n_reads`, `n_claimed`, `n_unclaimed` and `units[]`;
- `next_bar` = `holdout_lock.bar_for(n_reads + 1)`. There is **one** bar function, imported, never re-implemented;
- `read_state`: one of `measured` / `window_unstated` / `could_not_look`.

**Population, stated.** Every row of `research/results/**/*.jsonl` plus every claim in `holdout_reads.jsonl`, at the generating commit.

## 4. Design B: PBO / CSCV (`scripts/research/pbo_cscv.py`)

**Input.** A T × N matrix of per-period net R for N candidate configurations over the same T periods, net of the full cost stack. The period is the ISO week of exit, the same clustering unit as `se_week_clustered`.

**Method (CSCV).**
1. Split T into S contiguous blocks (default S = 16; S must be even and each block must hold ≥ 4 periods).
2. For each of the C(S, S/2) splits (12,870 at S = 16), take the in-sample half and the out-of-sample complement.
3. Find the in-sample best config by mean net R. Compute its OOS relative rank ω, and λ = logit(ω).

**Outputs.**
- **PBO** = P(λ ≤ 0);
- the performance-degradation slope (OOS on IS);
- the probability of an OOS loss for the IS winner.

**The emit step (G4).** Each harness that selects among configs gains `--emit-series <path>`, which writes the per-config per-week net-R matrix beside `measurement.json`. It starts with the two harnesses that select most often: the ml_entry arm harness (f1a0 / f1a5) and `queue_grade.py`'s TEMPLATE cells. An existing record without the matrix reads `pbo: {read_state: no_series}`, never a number.

**Self-tests.**
- Pure-noise configs: PBO in [0.35, 0.65].
- One planted config with a true +0.10 R edge among 20 noise configs: PBO ≤ 0.10.
- Deterministic under a fixed seed.

## 5. Wiring (report-only) and the registered acceptance tests

**Wiring.**
- (a) `research_queue` grade path: every graded result gains a `read_ledger` block: n_reads on its window at grading time, and the deflated bar that read would face under M13. When the unit selected among ≥ 2 configs, the result also gains a `pbo` block (number or `no_series`).
- (b) `mandate_resolver._holdout`: evidence gains `ledger_n_reads` and `ledger_bar` for the record's holdout window. A disagreement with the record's `evaluations_on_holdout` is reported as `R-HOLDOUT-LEDGER-MISMATCH` beside the decision and does **not** change it.
- (c) `trial_ledger` gains the `pbo` column per (leg, family) where a matrix exists.

**Registered before any build run** (pass/fail is written here first):

| Test | Pass when |
|---|---|
| **T1** positive control | `read_ledger` reproduces `holdout_lock.families()` n_tries **exactly** for every claimed (family, window), e.g. AM-HEADS 2026-01-01..11-21 = 18 |
| **T2** | Re-running on the same commit gives a byte-identical `read_ledger.json` |
| **T3** coverage measurement | Report `n_unclaimed` and `window_unstated` counts over all results. Prediction: ≥ 1 unclaimed read on ENTRY 2025-10-01..2026-09-30 (p 0.7) |
| **T4** | The PBO self-tests in § 4 pass |
| **T5** | A first real PBO on the first matrix produced after the emit step lands, with N, T, S stated. Prediction: f1a0's ten arms read PBO ≥ 0.5 (p 0.6), consistent with 33 levers / 0 PASS on a +0.003 R base |
| **T6** resolver | With a planted record self-claiming 1 read on a window the ledger shows at 5, the result carries `R-HOLDOUT-LEDGER-MISMATCH` and its decision is **unchanged** |

**Build order.** Each step is one Tier-1 PR (research tooling and read paths):
1. `read_ledger.py` with T1–T3;
2. `pbo_cscv.py` with T4;
3. the emit step in the ml_entry arm harness, then the T5 read;
4. the wiring (a)–(c) with T6.

ML-ENTRY-REDESIGN (rank 2) grades its units under steps 1–2.

## 6. Proposals for the operator (not applied; each adds enforcement)

- **D-A.** Make the ledger's count decisive in `_holdout`: the bar is `bar_for(ledger_n_reads)`, not the record's self-claim. *Recommended*, once T6 holds on live records for one week. It closes G2 without a new kind of rule, because it only applies M13 with an honest N.
- **D-B.** P-6's "spent at k reads". **Rejected, not proposed** (Manager 2026-11-28b, 09:26Z). It would reverse two operator rules:
  - M13 (2026-11-05): *"We can't just, like, give up on a certain line of research because we've already trained a model on all the data that we have. That's ridiculous."*
  - The 2026-11-28 ~09:55Z rule (row `RESEARCH-NO-WAIT-FOR-DATA`): *"Eventually, we're going to have to retrain models on the same data. That's fine."*
  
  The deflated bar already makes the k-th read progressively harder to pass without forbidding it.
- **D-C.** A PBO ceiling on promotion (for example PBO < 0.5 for a record selected among ≥ 5 configs). *Defer* until T5 and three more families have real PBO numbers. A threshold chosen before any value is seen is the honest way, but we do not yet know the scale.

## 7. Calls (graded at the next weekly ML review)

- T1 holds on the first run (p 0.85). A miss means `family_of` and the subject mapping disagree, which is itself a finding.
- T3 finds ≥ 1 unclaimed read of the ENTRY year (p 0.7).
- Steps 1–2 merge by 2026-12-02 (p 0.7).
