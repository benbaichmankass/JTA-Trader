# Weekly walkthrough 2026-10-28

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Several lanes write their sections here. On a collision, merge `main` first and keep every lane's section.

## Research programmes — lane PROGRAMME-REVIEW-20261028 (Tier 1; held PR, manager merges)

**Headline:** on the declared wide-trail legs, tightening the stop loses R. Two instruments agree, so P1 moves its value from tightening gates to loss-cut, TP and entry selectivity. The top TRADING test is a re-cost: about 36 of this week's 70 PASSes were priced at 7.5 bps, against the 11.0 the venue charges. MODEL's binding constraint is builds, not learners.

**Population:** units with a result row generated 2026-10-21T19:30Z..2026-10-28T19:30Z. That is 445 units, of which 412 are graded (70 pass, 50 indeterminate, 292 fail); 285 carry a programme field and 160 do not. The 160 are assigned in [`RESEARCH-MAP.md`](../research/programmes/RESEARCH-MAP.md). Record: [`comms/research/programme_review/20261028.json`](../../comms/research/programme_review/20261028.json). Per-programme reasoning sits in each plan's "Programme review 2026-10-28" section.

### 0. Prior calls
The 2026-10-21 review stated no probabilities, so Brier is INDETERMINATE. I graded 9 forward claims by outcome: **5 hit, 2 miss, 1 unresolved, 1 void.** Hits: the Q11 transfers came by leg and vol control (eba2-01/-04); Q3.1 was not re-asked early; ml_health stayed build-bound; breadth separated trend from pullback; breakout_2 sizing was applied (`risk_pct` 0.0035). Misses: the lever variants (0 of 11 passed), and "no new macro unit" (34 macro units were graded anyway). Unresolved: the MOMENTUM-LEVERS-LIVE declares (row still `landed_unproven`). **Ranking error:** last week ranked 11 tightening variants ahead of the label transfers. The variants were draws from a family now at about a 4% pass rate. The week's most informative P1 result, the desk full run, was on no plan.

### 1. CHECKS (from `research_ops_checks.py --kind programme_review --since 7d`)
| check | value |
|---|---|
| graded 7d by track | TRADING 73 pass / 29 indet. / 300 fail / 13 no-action · MODEL 10 / 25 / 31 · INFRA 7 pass |
| runnable by track | TRADING 41 · **MODEL 0** · INFRA 4 |
| fails without a next unit | 31 (the packet's list; this review's diagnoses cover the large clusters) |
| programme coverage | 0 uncovered plan questions in P1..P7 |
| follow-through (programme-review) | cohort 9 filed, 1 done, 8 open; backlog 16 open, median age 9 d, 0 without an owner |
| could not look | previous_calls (no prior record existed); #20967 artefacts are not on main |

### 2. ANALYSIS: the five shifts
1. **P1 TRADING: tightening loses.** About 129 of 140 exit-management lever units FAILED, and the 6 lever PASSes come at the rate chance alone produces. The desk full run (#20967) is −0.159 R vs hold on Claude entries; 981 tightens were worth −0.097 R each and holds were worth +0.142 R. One mechanism: these legs earn in the right tail. What survives is selective or entry-side. The direction filter is CONFIRMED on a disjoint window (RQ-20261028-001), though only at n(A) 39. The BE floor and the CHOP-gated trail are authored for confirmation. Not retired, because the family policy governs that; it is down-ranked.
2. **P3 TRADING: re-cost before reuse.** Trend-Donchian breadth transfers to about 17 alt perps and 2h pullback does not, but all of it ran at 7.5 bps. In #20966 the 3 trend-leg flips are window drift by the fee-isolated read, and 3 units now test drift against decay. The 2 scalps failed twice, on independent instruments: a retirement case goes to the operator.
3. **P2 MODEL: information over capacity.** 0 of 23 learner arms beat the shipped LightGBM regime head. Range-vol information moves log-loss on all 3 symbols. The #20869 refusal of the 9 setup-metalabel heads is a gross-data refusal, not a measured loss.
4. **P4:** PPI to ES/SPY is the one macro survivor, about 3 of 34. Its useful form is a tilt on the rostered spy/qqq 1d trend legs.
5. **P7:** daily long-only Donchian is fold-consistent on 12 perps and transfers to a new basket.

### 3. Decisions (ranked; every one is a node or handoff)
| call | decision | tier | pre-registered check | ending |
|---|---|---|---|---|
| eth_4h breadth survives 11.0 bps, p 0.75 | authored `P3-Q8-recost-11bps-eth4h` | 1 | its grading verdict by 2026-11-04 | node unit |
| C75 confirms, p 0.25 | authored `P1-ATM-ed1c10-c75-confirm` | 1 | verdict | node unit |
| ≥ 2 of 3 flips are window drift, p 0.55 | authored `P3-RECOST-flip-*` x3 | 1 | verdicts | node units |
| loss-cut on ada_pb passes, p 0.15 | authored `P1-Q4-desk-losscut-ada-pb` | 1 | verdict | node unit |
| no regime-head learner arm passes next week, p 0.9 | no new learner nodes | 1 | count of passing "Regime head" units | record call |
| cost-net rebuild done by 11-04, p 0.3 | `P2-Q2-costnet-metalabel-regate` waits on it | — | pipeline item state | gated node |
| ict_scalp eth/xrp 15m retirement case | proposal for the operator | 3 (operator) | — | handoff |
| proxy-symbol fee in research harnesses | build question | manager | — | handoff |

### 4. Not done
13 ready authoring-queue nodes were not turned into units. They are Tier-3 declare drafts or research-ops follow-ups, ranked in the record's handoff. I filed no checklist row: the two builds named (proxy-symbol fee, cross-asset feature block) need the manager's call on owner and scope first.
