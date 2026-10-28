# DESK-LIFECYCLE-S0 — the desk's full-lifecycle factorial: where is the value (entry vs management), and how does the desk combine with the strategies?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-LIFECYCLE-S0` (Tier 1 research), dispatched by Manager Session 2026-10-27a (session_01AFoLuJi1vLTnYv9LbP6539). Checklist row `docs/claude/work/checklist/DESK-LIFECYCLE-S0.json` (roadmap `L-DESK`). Driver `scripts/research/desk_lifecycle_driver.py` (tests `tests/test_desk_lifecycle_driver.py`). Units `RQ-20261028-d1f5-01` (self-check), `-02` (the C48 factorial), `-03` (the live 60-minute contract).

**Operator, 2026-10-28 ~06:10Z (paraphrased by the manager, binding for this lane):** the desk's edge test must be a FULL RUN of each trade from entry to close, not one step in isolation, so we learn WHERE the value is (entry vs management vs exit) and HOW to combine the desk with the existing strategies.

**Sections 1–6 were committed before any management decision was judged and before any static-rule or managed outcome was computed** (the only numbers computed before this commit are the instrument's own: the judged-1 reproduction, the self-check clauses and the checkpoint count under HOLD, all path-only). Results are appended in § 7 afterwards and labelled.

## 0. DESIGN v2 (2026-10-28 ~07:15Z) — the management factor is the CHECK-IN POLICY. Supersedes §§ 1–6's management factor.

**Why v2.** Manager -> lane, 06:25Z, relaying the operator (~06:35Z, paraphrased, binding; now recorded in
`docs/plans/claude-trading-desk-DESIGN.md` § 8.1 "Active-management test design"): *"One check when the trade hits
1R is not how active management works. It is first and foremost HIGH-FREQUENCY TIME-BASED check-ins, and on top of
that EVENT triggers ... Design tests that give actual information."* And 06:33Z: design FROM the practice review
(`docs/research/practice-review-trade-mgmt-and-ai-2026-10-28.md` § A.4 and § F.1, branch
`practice-research-trade-mgmt-ai`). v1 (§§ 1–6) checked in at four FIXED points (bars held 4/12/24/36), the same
for every trade: that is the shape the rule forbids. **v1 is superseded.** Its 78 judged check-ins (rounds 1–2 of the
v1 pilot, judged before the redesign reached the lane; § 7.2) are kept as a record and for the cost measurement,
never scored as a result. **RQ-20261026-bf56-02/-03** (lane DESK-MGMT-S0, #20836: one decision per trade at +1 R,
n = 176; in-trade −0.048 R [−0.143, +0.041], exit −0.091 R [−0.198, −0.003]) is cited only as **"a single +1 R
intervention"**, never as "management fails".

### 0.1 The factors

| factor | levels |
|---|---|
| **E: entry** (held fixed across every management arm) | **claude** = the 732 committed judged-1 fills (C48 contract); **random** = one matched partner each (same symbol, fold, side, ATR-unit bracket); **strategy** = the four real-money legs' committed trades (registered in -02 § strategy arm, not built here) |
| **M: management** | **M0** hold to bracket · **M1** matched random intervention for EACH Claude arm (Claude's own count and sequence of action types, at random check-ins of the same policy, 50 draws) · **M2** Chandelier trail 2 / 3 x ATR off the running extreme · **M3** channel exit (a close beyond the prior 12-bar extreme against the trade) · **M5** time stop (bars held >= 12 or 24 with MFE < +0.5 R) · **M6** breakeven at +1 R · **M7** 50 % partial at +1 R, Chandelier 3 x ATR on the rest · v1's menu (close at first check-in, breakeven at +0.5 R, 1 R trail, partial at +1 R, cut below −0.5 R) · **M8/M9 Claude** |
| **C: check-in policy** (the Claude arms; M1 inherits it) | **C1E** every 1h bar + event tags · **C4E** every 4 bars + event triggers · **E** event triggers only. Events: first close beyond each R milestone −0.5 / +0.5 / +1 / +1.5 / +2 R; ATR(now)/ATR(entry) crossing 1.5 or 1/1.5 (and back); 3-bar momentum sign flip (with / against the trade); a close beyond the prior 12-bar high/low (level break, with / against). Every check-in carries its trigger tags (`why_now`). |

Rule arms M2–M7 run token-free on the WHOLE population at every bar (C1E); B3 = the best rule of the combined menu
chosen leave-one-fold-out. M4 (re-score with the entry model) is not replayable for a Claude entry (no entry model; checked: `scripts/research/desk_gen_replay_driver.py` — a judged-1 entry is a proposal row, not a model with a re-scorable signal)
and is out of scope here; it belongs in the strategy arm. Deviations from F.1, stated: ATR is the 14-bar ATR of the
packet (F.1: ATR(22)); the channel is 12 bars (F.1: 10 / 20; amended to 10 / 20 in § 0.1b); the time stop is fixed at 12 / 24 bars (F.1: the leg's
median winning duration; the desk has no leg history).

### 0.1b Additions from the FINAL practice review (PR #20844, § F.1 / F.2; manager 06:45Z)

- **Channel exit at N = 10 and 20** (replacing v2's 12-bar channel arm before any v2 result is scored; the 12-bar level
  break stays an EVENT TRIGGER only). Built with the scorer after the pilot's walkers finish (the walk command must not
  change under a running judge).
- **Strategy arm** (registered in -02, not built here): adds the **re-score exit (M4)** where a leg's entry model replays
  point in time, the **trend vs mean-reversion strata** (lag-1 autocorrelation / variance ratio of the leg's Stage-0 returns,
  training folds only), and a replay-only **"TP far, trail does the work" arm** on the TREND legs (target at the 10 R cap,
  Chandelier 3 x ATR trail) to MEASURE what the TP doctrine costs there. Evidence only: the doctrine is binding
  (ARCHITECTURE-CANONICAL § TP doctrine) and any live change would be Tier 3.
- **Reusable label file (F.2: the ML target is a supervised meta-model over the best rule, labelled with the PRICED outcome of
  every action; Claude is a feature / hypothesis source, not the imitation target):** the scorer writes
  `labels.jsonl`, one row per (trade, arm, check-in): entry source, policy, arm, bars held, R state, trigger tags, the action, and
  its priced marginal value (the trade's net R minus the same trade with that one answer replaced: action -> hold, hold -> close),
  for Claude, M1 and every rule arm.

### 0.1c Fresh-window confirmation (proposal; decided Thursday)

The DESK-EDGE-PROGRAM HOLDOUT (2025-05-01..2025-10-25) and FULL-RUN (2023-11-01..2025-04-30) windows are reserved for
entry variants. Two windows nobody has spent:
1. **Forward window:** cutoffs 2026-09-15..2026-10-20 (after judged-1's window ends; candles MEASURED to 2026-10-26),
   random entries with geometries drawn from the judged-1 bracket distribution, x the passing Claude arm. About 5 weeks:
   n is bounded by weeks, so it confirms the sign, not the size.
2. **Other-symbol window (preferred for n):** the DEV window 2025-11-01..2026-09-15 on USD-M perps NOT in the registered six
   (e.g. BNB, DOGE, LINK, LTC, DOT, TRX; Binance Vision has them), random entries x the passing arm. Same weeks, fresh paths;
   a symbol-specific memorisation could not carry over.

### 0.2 How Claude manages a whole trade: one judge walks one trade

A plan subagent (Sonnet tier, the desk's in-trade tier; no API credits) is given trade tokens and ONE command:
`python3 scripts/research/desk_lifecycle_driver.py walk --out DIR --candles-dir C --trade T [--decision JSON]`.
It prints the trade's next check-in packet (prices rebased once per trade, fill = 100; the first packet carries the last
48 closed 1h bars, later ones only the bars since the previous check-in; the trigger tags; the actions taken so far;
the current brackets in price and R; cost if closed now) or `{"closed": true}`. `--decision` records the answer to the
CURRENT packet only (refused otherwise), then the engine replays the trade with every answer so far and reveals the
next check-in. The judge never sees a bar after its check-in. **Isolation is audited mechanically**: every tool call
in every judge transcript must be exactly that command (regex); one other call voids that judge's trades, which are
re-judged. Sources (claude / random) interleave in token order and are not labelled.

### 0.3 Statistics and the registered rule (RULE-RQ20261028-D1F5-02-LIFECYCLE, v2)

Per trade, paired dR = net R(arm) − net R(M0), net of the full cost stack (§ 2), weekly-cluster bootstrap
(10,000 draws). For each Claude arm (policy C) and entry source: **PASS** iff n >= 126 pairs AND dR vs M0 has mean
> 0, CI lower > 0, > 0 in >= 3 of 4 folds AND **dR vs its own M1 has CI lower > 0** (else "acting helps, timing does
not"); Holm across the three Claude arms within the family; labelled `judgement` only if it also beats B3 (CI lower
> 0), else `pass_rule`. FAIL iff CI upper < 0 vs M0. Otherwise INDETERMINATE with the observed paired sd and the n
that would resolve ±0.10 R. A PASS on this window is provisional until it **re-passes once on a fresh window**
(`RESEARCH-CONFIRM-FRESH-WINDOW`): random entries x the same Claude arm on a window the manager allocates (the
DESK-EDGE-PROGRAM holdout and full-run windows are reserved for entry variants; a decision for the manager).
**Reported, not graded:** the factorial contrasts of § 3 (entry value, main effects, interaction) per policy; the
**value of acting vs not acting** (per check-in ablation: each Claude action vs that one answer replaced by hold;
each Claude hold vs that one answer replaced by close), by action type, trigger tag, time in trade and R state;
capture ratio and action rate; strata: volatility tercile at entry and side (the desk has no trend / mean-reversion
leg label; the strategy arm stratifies by leg type per F.1). Every arm and parameter is counted in the trial ledger.

### 0.4 n, power and spend (the n the plan can buy)

- **Check-in load, MEASURED on the HOLD path over all 1,464 trades** (`comms/research/desk_lifecycle/explore/explore.json`):
  C1 every bar **16,176** (11.05 / trade), C4 every 4 bars 3,521 (2.41), E events only **7,141** (4.88), C4E **9,111** (6.22).
  Claude's actions change the path (a close ends it), so a judged arm is at or below these.
- **Paired sd, MEASURED on the token-free rule arms** (Claude entries): 0.51–0.96 R for active rules (Chandelier 3 x ATR
  0.71, breakeven 0.63, channel 0.52); design effect of week clustering ≈ 1.1 (Chandelier 3 x ATR: cluster half-width
  0.053 vs iid 0.051). At sd 0.7, ±0.10 R needs about (2.8 x 0.7 / 0.1)^2 x 1.1 ≈ **420 trades = ~200 pairs per Claude arm**.
- **Judge cost per check-in:** MEASURED in v1's batched mode at ~8.0k subagent tokens per check-in (6 judges,
  624k tokens, 78 check-ins); the walker's multi-turn cost is NOT yet measured (INFERRED $0.01–0.025 per check-in at
  Sonnet list prices, mostly cached context). The pilot measures it.
- **Registered full run:** the same **200 pairs** (the first 200 of one seeded order of the 732, seed 20261031; the pilot is its first 20) under each of **C4E (M8, primary)**,
  **E (M9)** and **C1E** (the cadence factor). Check-ins ≈ 200 x 2 x (6.2 + 4.9 + 11.0) = **8,860** -> **~$90–220**
  API-equivalent on the plan (INFERRED until the pilot measures $/check-in). The rule arms, M0 and M1 cost nothing.
  Cheaper registered fallback (the manager's call): C4E and E only, 126 pairs (the floor): ~2,800 check-ins, **~$30–70**.
- **Pilot (not yet run; waits for the manager):** 20 pairs (40 trades) under C4E, walker mode, ~250 check-ins,
  **~$3–6**; labelled pilot; measures $/check-in, paired sd, invalid rate, isolation audit, action mix by trigger.

### 0.5 Token-free results already in hand (rules, not Claude; computed 2026-10-28 before this v2 registration)

Disclosure: these were computed while v2 was being designed (they set the power numbers above). The rule menu
itself was fixed by practice review F.1 before they were seen; nothing in the Claude-arm rule depends on them.
Population: 732 Claude entries and 732 matched random entries, current cost stack (11 / 3 / 1 bps).

| rule arm (dR vs HOLD, mean [95% cluster CI]) | Claude entries | random entries |
|---|---|---|
| HOLD itself (net R / trade) | +0.132 [−0.086, +0.331] | +0.184 [+0.038, +0.310] |
| Chandelier 2 x ATR | **−0.128 [−0.226, −0.017]** | **−0.091 [−0.153, −0.019]** |
| Chandelier 3 x ATR | **−0.093 [−0.144, −0.038]** | **−0.043 [−0.084, −0.001]** |
| channel 10 / 20 (re-run after the F.1 amendment) | −0.051 [−0.105, +0.002] / −0.005 [−0.032, +0.022] | −0.025 [−0.065, +0.012] / −0.019 [−0.046, +0.003] |
| time stop 12 / 24 | −0.018 / −0.003 | −0.016 / −0.004 |
| breakeven at +1 R | −0.050 [−0.097, +0.003] | −0.008 [−0.046, +0.029] |
| partial at +1 R + Chandelier 3 | −0.051 [−0.098, +0.003] | −0.052 [−0.103, +0.005] |

**Hindsight map (bounds, reads the future on purpose):** at every C1E check-in of the HOLD path, closing now minus
holding is NEGATIVE in every time bucket (−0.27 to −0.36 R), every R state (−0.14 to −0.41 R) and every trigger tag
with n >= 100; the hindsight-oracle upper bound is +0.2 to +0.6 R per check-in. At −0.5 R and below, closing is better
in 77–82 % of check-ins yet worse on average (holding has positive skew). Reading: in this window (723 of 732 entries
short, a falling market) **no state rule captures management value and every trail costs R**; whatever value exists
must come from information in the path, which is exactly what the Claude arms vs M1 test. Not a verdict on Claude.

> **§§ 1–6 below are DESIGN v1, SUPERSEDED by § 0 for the management factor** (kept as registered; the engine, cost stack, entries and factorial arithmetic carry over).

## 1. The design: a factorial over one real path per trade

Every trade is replayed bar by bar from its fill to its close on the real 1h candle path, under the full cost stack. Two factors:

| | **management = HOLD** (bracket + time stop, untouched) | **management = CLAUDE** (decisions at every checkpoint until the close) | **management = STATIC (B3)** (best fixed rule, leave-one-fold-out) |
|---|---|---|---|
| **entry = RANDOM** (frequency / direction / geometry matched) | R_h — token-free | R_m — **new cell, judged** | R_b3 — token-free |
| **entry = CLAUDE** (judged-1 entries) | C_h — **exists**: e535-03 (cited, re-scored at the current fee) | C_m — **new cell, judged** | C_b3 — token-free |
| **entry = STRATEGY** (committed Stage-0 legs) | S_h — **exists**: the legs' evidence records | S_m — single-checkpoint slice **in flight** in lane DESK-MGMT-S0 (RQ-20261026-bf56-02/-03, consumed, not re-judged); the full-run version is registered in -02 § strategy arm | S_b3 — token-free in bf56 (its B3) |

**Why one path per trade matters.** Management value is a PAIRED quantity: the same trade, the same candles, HOLD vs managed. Its variance is the variance of the *difference*, which is far below the variance of net R itself, so it resolves at an n where entry value (an unpaired quantity whose CI is set by the number of distinct weeks, `desk-edge-program-2026-10-27.md` § 4.1) cannot. The factorial uses that: entry value and management value are estimated on matched pairs, and the interaction is a difference of paired differences.

### 1.1 The contract replayed: C48 (this unit) and C60 (the live contract, unit -03)

**C48** is the contract the committed Claude entries were judged under: 1h bars, the proposal's own stop and target, a 48-bar time stop (all 732 judged-1 proposals have `horizon_bars: 48`, market entry). Using it means the Claude-entry factor costs **$0** to supply (the entries are committed: `comms/research/desk_gen_replay/judged-1/`) and the C_h cell is already a landed record (`RQ-20261026-e535-03`), so the whole judging spend goes to the new question: management.

**C60 is NOT replayed here.** The live `claude_desk` leg caps a hold at 60 minutes (`max_hold_min` ≤ 60, DESK-18E). A 60-minute trade on 1h bars is one bar and has no interior checkpoint, so C60 needs a 5-minute (or 1-minute) path and FRESH Claude entries judged under the 60-minute brief (none of the 732 were). It is registered as `RQ-20261028-d1f5-03` (blocked on that build and on a manager spend decision). Stated so nobody reads a C48 result as the live contract's.

## 2. The chained engine (what "full run" means mechanically)

`desk_lifecycle_driver.run(series, entry, decide)`:

- **Fill** exactly as `desk_gen_replay_driver.simulate` (market = next bar's open; limit/stop through the level; the MIN_RISK_ATR refusal floor). **HOLD is verified to equal `simulate` on every trade** (self-check clause a).
- **Checkpoints** at bars held = round(f × horizon), f ∈ {1/12, 1/4, 1/2, 3/4} → **4, 12, 24, 36 of 48**, decided at the CLOSE of that bar, effective from the NEXT bar. A trade already closed has no further checkpoint.
- **Closed action enum** (desk schema v2 in-trade + exit, and the live review's § 3b actions that a bracket replay can price): `hold` · `tighten_sl r` (to r R from entry; above the current stop, ≥ 0.10 R below price) · `widen_sl r` (below the current stop, floor −2.0 R) · `move_tp r` (≥ 0.10 R beyond price, cap 10 R) · `partial_close` (50 %, once) · `close`. `close` and `partial_close` fill at the next bar's open. An invalid or missing answer is HOLD and is **counted**. Neither bracket is ever removed (operator: *both brackets, always*). `change_size` / `add_entry` are not in the replay (sizing is the risk manager's; stated).
- **Within a bar**: SL before TP; a gap fills at the open; a limit/stop fill bar credits no TP. Time stop at the close of bar fill + horizon − 1.
- **Cost stack (the full one, per piece)**: `execution_costs.roundtrip_cost_r` with the venue fee from `profile_loader.roundtrip_fee_bps_for` = **11.0 bps round trip, Bybit linear taker, after #20783**; slippage and funding from `resolve_cost_policy(symbol)` = **3.0 bps round trip** and **1.0 bps per 8-hour funding window** (MEASURED 2026-10-28 for all six symbols by calling `desk_scan_packet.cost_policy`). A partial pays each piece's cost on its own size. A moved stop that fills pays no extra charge (the original stop pays none either); `+0.05 R` per moved-stop exit is reported as a sensitivity.
- **Chaining.** A checkpoint packet exists only if the trade is still open under the decisions already made, so judging runs in ROUNDS: `step` replays every trade under the answers so far and writes the packets now due (round-NN-packets.jsonl for the judge, round-NN-key.jsonl for the scorer); judges answer; `step` again until nothing is pending. Deterministic and resumable: a re-run with the same answers reproduces the same packets.

### 2.1 The checkpoint packet (masked)

The open trade's side, entry / stop / target as rebased prices and in R, `now_r`, MFE / MAE in R, bars held, bars left to the time stop, whether a partial was taken, the checkpoint number, ATR now, `cost_r_if_closed_now`, and the last 48 closed 1h bars (offset-indexed, 0 = now) rebased to 100 at the checkpoint close. **No symbol, no date, no epoch, no real price, no source** (random vs Claude vs strategy), no entry thesis, no entry id; the packet id is a salted hash. Sources interleave in id order. The unmask key is a separate file. Leak scan on every packet with a planted positive control (self-check clause c).

## 3. Cells and statistics (registered)

Population per pair p: one Claude entry and its matched random partner (same symbol, same fold, same side, the same bracket in ATR units at a random eligible cutoff of that fold; the first draw that fills; seeded per pair by sha256(20261029 | pair id), so a pilot pair is the same pair in the full run).

| statistic | definition (per pair, then the mean) |
|---|---|
| cells | C_h, C_m, R_h, R_m, C_b3, R_b3 — mean net R per trade |
| **management value \| claude entry** | C_m − C_h (paired) |
| **management value \| random entry** | R_m − R_h (paired) |
| entry value \| hold | C_h − R_h (= S3 of e535, matched 1:1 instead of the 200-draw mean) |
| entry value \| claude management | C_m − R_m |
| main effect, management | ½[(C_m − C_h) + (R_m − R_h)] |
| main effect, entry | ½[(C_h − R_h) + (C_m − R_m)] |
| **interaction** | (C_m − C_h) − (R_m − R_h): does Claude manage its OWN entries better than random ones? |
| judgement vs rule | C_m − C_b3 and R_m − R_b3 |
| end to end | C_m − R_h: the desk as a whole vs a random trade left alone |

**Inference.** Weekly-cluster bootstrap (10,000 draws, seed 20261028), the cluster being the Claude entry's ISO week (the pair is the unit; the random partner's own week differs — an approximation, stated). Per-fold means (the driver's four folds).

**B3, the static menu (fixed now, in code):** `hold`, `close_at_ckpt1`, `breakeven_at_0.5r` (stop to 0 R once price is ≥ +0.5 R), `trail_1r` (stop to price − 1 R at each checkpoint), `partial_at_1r`, `cut_below_-0.5r` (close at a checkpoint at ≤ −0.5 R). B3 per pair = the rule with the best mean dR on the OTHER three folds. Every rule's dR is also reported on its own, for both entry sources.

## 4. The pre-registered decision rule (RULE-RQ20261028-D1F5-02-LIFECYCLE)

For each management contrast (C_m − C_h and R_m − R_h) and each entry contrast:

- **PASS** if n ≥ 126 pairs AND mean > 0 AND the cluster CI lower bound > 0 AND > 0 in ≥ 3 of 4 folds (each fold n ≥ 20). A management PASS is labelled **`judgement`** only if Claude's managed outcome also beats B3 (C_m − C_b3 CI lower bound > 0); otherwise **`pass_rule`**: *the value is there, a fixed rule captures it, give it to a rule or a student, not to Claude*.
- **FAIL** if n ≥ 126 and the CI upper bound < 0: the role costs R.
- **INDETERMINATE** otherwise; the record states the OBSERVED paired sd and the n at which it would resolve ±0.10 R. Never a lowered bar.
- Interaction: reported with its CI; a CI excluding 0 is read as "management value depends on who entered".
- The numbers (126, 3 of 4, 20, the checkpoint fractions, the action bounds, the B3 menu, the seeds) are not changed after any result.

**What the factorial decides (the combination table, registered):**

| management \| claude | management \| strategy (bf56 + -02 strategy arm) | entry value | reading |
|---|---|---|---|
| `judgement` PASS | — | any | Claude adds value in the trade it opened; keep the desk managing its own trades (per-trade lane) |
| — | `judgement` PASS | — | **Claude managing our existing legs** is supported: a Tier-3 proposal under MD-TRADE-DESK's in-trade function on those legs |
| `pass_rule` | `pass_rule` | — | ship the rule (exit-refinement pipeline), not Claude |
| FAIL / indeterminate | FAIL / indeterminate | S3 ≤ 0 | the desk has no Stage-0 edge on this contract; nothing promotes |
| any | any | C_m − R_m PASS | the desk's entries are worth taking **when Claude also manages them** (the entry value only shows with management) |

## 5. Power, n per cell and spend

- **n per cell (full run, fixed population, no stopping rule):** all **732** judged-1 fills (C_h, C_m) and their **732** matched random partners (R_h, R_m). The population is complete before any answer is seen, so no stopping rule is needed; every pair is judged.
- **MEASURED path load (before any judging):** under HOLD the 1,464 trades reach **1,757** checkpoints (mean 1.20; 500 trades close before checkpoint 1, 503 reach exactly 1, 252 reach 2, 86 reach 3, 123 reach all 4). Managed paths differ (a `close` removes later checkpoints, a widen can add some); the pilot measures the ratio.
- **Power:** the paired sd of a management contrast does not exist yet; the pilot measures it. At the pass floor n = 126 the MDE is 2.8·sd/√126; at n = 732 it is 2.8·sd/√732 (× √deff for week clustering, deff measured by the run). For orientation only: at a paired sd of 0.5 R (INFERRED from the planted hindsight oracle's own sd, 0.58 R) n = 732 resolves about 0.05 R × √deff. The verdict grades on the OBSERVED CI.
- **Spend estimate (API-equivalent on the plan; nothing spends API credits):** packets x the pilot's MEASURED $/packet, stated in § 7 after the pilot. Upper anchor: $0.0688 per packet (judged-1, stateless) → 1,757 × $0.07 ≈ **$123**; a batched subagent with small packets measured lower (§ 7).

## 6. The pilot (labelled pilot; not a verdict)

- 40 Claude entries drawn from the 732 with seed 20261028 and their 40 matched random partners (80 trades). Judged by Sonnet-tier plan subagents (the desk's in-trade tier), **packet only**: no tools, no repo, no web; the packets are inside the prompt and the answer is the subagent's final message, so isolation does not depend on obedience.
- Pilot rows are reused in the full run only if the protocol text and the packet builder are byte-identical to the pilot's (protocol sha in the pilot record); otherwise they are re-judged.
- The pilot reports every cell and contrast with its CI, labelled **pilot (n = 40 pairs, below the 126 floor: not a verdict)**, the measured paired sd, invalid-answer rate, checkpoints per trade and $ per packet, and the full run's n and $ estimate.

## 7. Results

### 7.1 Instrument (MEASURED)
Self-check PASS 6 / 6 (local, `RULE-RQ20261028-D1F5-01`, plus clause a3 added with v2: HOLD under C1E / C4E / E equals
the bracket engine on all 1,464 trades, max |diff| 0.0). judged-1 reproduced exactly (732 fills, +0.158866 R at
e535-03's 7.5 bps fee; **+0.1315 R at the current 11 bps**).

### 7.2 v1 pilot (SUPERSEDED, not scored)
40 pairs drawn; v1 rounds 1–2 judged before the redesign reached the lane: 78 check-ins (62 hold, 16 tighten_sl,
0 invalid), 6 Sonnet plan subagents, 624k subagent tokens, every transcript audited (Read of its own two files only).
Rounds 3–4 were not judged. Kept in `comms/research/desk_lifecycle/pilot/` as a record and as the batched-mode cost
anchor; not reused by v2 (different packets, different policy).

### 7.3 v2 pilot — **PILOT, n = 20 pairs (40 trades), below the 126 floor: not a verdict**

Manager GO 06:53Z (cap $8). Population: the first 20 pairs of the registered seeded order (seed 20261031) of the 732
judged-1 fills and their matched random partners; policy **C4E**; 4 Sonnet plan subagents x 10 trades, walker mode;
WALK-PROTOCOL.md sha256 231ce3b1908b7946 (committed before judging). Evidence: `comms/research/desk_lifecycle/pilot-v2/`
(`entries.jsonl`, `decisions.jsonl`, `rounds/round-walk-key.jsonl`, `score.json`, `pairs.jsonl`, `labels.jsonl`).

**Mechanics (MEASURED).** 40 of 40 trades walked to close; **122 check-ins** answered (hold 68, tighten_sl 45, move_tp 4,
close 5; **0 invalid**); 18 trades exited at a moved stop. Under HOLD the same 40 trades would reach 260 C4E check-ins:
Claude's tightening ended trades earlier (ratio 0.47). **Isolation audit: 162 tool calls across 4 transcripts, every one the
registered walk command (regex), 0 violations.**

**Cost (MEASURED from the transcripts' usage, Sonnet list prices, on the plan; no API credits):** 15.17 M cache-read,
0.44 M cache-write, 42 k output tokens = **$6.85 for 122 check-ins = $0.056 per check-in ($0.17 per trade)**. Cache reads
dominate (each walk call re-reads the judge's growing context), so fewer trades per judge is cheaper per check-in
(INFERRED: ~5 trades per judge roughly halves it).

**Read (PILOT; every interval spans 0 unless stated).**

| contrast (mean [95% cluster CI], n = 20 pairs) | Claude entries | random entries |
|---|---|---|
| HOLD net R / trade | −0.084 [−0.770, +0.555] | +0.307 [−0.401, +1.025] |
| Claude-managed net R / trade | −0.123 [−0.486, +0.273] | +0.176 [−0.402, +0.712] |
| **management dR vs HOLD (M0)** | −0.039 [−0.578, +0.421] | −0.131 [−0.580, +0.380] |
| **vs its matched random intervention (M1)** | +0.168 [−0.012, +0.476] | −0.138 [−0.347, +0.072] |
| vs best rule B3 | −0.081 [−0.277, +0.193] | −0.031 [−0.465, +0.464] |
| interaction (Claude-entry mgmt value − random-entry mgmt value) | +0.091 [−0.427, +0.678] | |

**When does acting add value (per-check-in ablation, both entry sources, PILOT):** the 5 `close` answers (all at the −0.5 R
trigger) were worth **+0.346 R each [+0.294, +0.493]** vs holding on; the 45 `tighten_sl` answers −0.072 [−0.422, +0.234],
and tightening at the +1 R milestone −0.484 [−1.139, +0.221] (n 17); the 68 `hold` answers were worth +0.375 [−0.087, +0.856]
vs closing there. The pattern the practice review predicts (judgement helps when rare and information-driven, hurts as
frequent tweaking) is what the pilot shows at n = 20: Claude acted on 44 % of check-ins, mostly tightening, and the
tightening is where it lost.

**Power, re-measured.** The paired sd of Claude's management dR is **1.06 (Claude entries) and 1.18 R (random)**, not the
0.7 R registered from the rule arms. At sd 1.1, 200 pairs resolves about **±0.16 R**; ±0.10 R needs ≈ (2.8 x 1.1 / 0.1)^2 x 1.1
≈ 1,040 trades ≈ **520 pairs** per arm. The rule (graded on the OBSERVED CI) is unchanged; the n it buys is what changes.

### 7.4 Full-run options with the MEASURED $0.056 / check-in (decided Thursday with the operator)

Check-ins per trade = the HOLD-path load x the pilot's managed / hold ratio 0.47 (MEASURED for C4E; assumed for the others).

| option | pairs | check-ins | $ (at $0.056) | resolves |
|---|---|---|---|---|
| **A. 3 policies (C1E, C4E, E)** | 200 each | ~2,080 + 1,220 + 920 ≈ 4,220 | **~$235** | ±0.16 R per arm |
| **B. fallback C4E + E** | 126 each | ~770 + 580 ≈ 1,350 | **~$75** | ±0.20 R per arm |
| C. C4E only, powered for ±0.10 R | 520 | ~3,170 | ~$178 | ±0.10 R |
| D. C4E only, all 732 pairs | 732 | ~4,470 | ~$250 | ±0.085 R |

**DECIDED — option C** (operator 2026-10-28 07:05Z, popup verbatim *"C: 520 pairs, after reset (Recommended)"*, relayed by
the manager): **policy C4E x 520 pairs** (the first 520 of the seeded order, seed 20261031; the pilot's 20 pairs are its first 20),
resolving about ±0.10 R, ~$178 at $0.056 per check-in. **Why:** the pilot measured Claude's paired management dR sd at 1.06–1.18 R,
so 200 pairs per arm would resolve only ±0.16 R. C1E and E are not run in RQ-20261028-d1f5-02 (registered for a later unit if funded).
The registration was amended to option C before any full-run data existed; the full run starts after the ~18:00Z reset on the manager's GO,
with walkers batched to minimise cache cost (fewer trades per judge, § 7.3).

Every row halves if the judge carries ~5 trades instead of 10 (INFERRED; measure on the first batch). The pilot's 20 pairs are
reusable in any option (the protocol and packet builder are unchanged since the pilot; the channel 10 / 20 amendment touches
only the scorer). The rule arms, M0 and M1 cost nothing at any n.

### 7.5 FULL RUN (option C: C4E x 520 pairs) — registered verdict **FAIL: Claude's whole-trade management COSTS R on both entry sources**

Manager GO 2026-10-28 18:15Z (post-reset, hard ceiling $200, plan sessions only). Evidence record:
`comms/research/desk_lifecycle/full-c4e/` (`verdict.json`, `score.json`, `pairs.jsonl`, `labels.jsonl` = 12,500 per-check-in
priced labels for F.2, `decisions.jsonl`, `rounds/round-walk-key.jsonl`, `voided-b018-decisions.jsonl`, `batches/`).

**Population and coverage (MEASURED).** 520 registered pairs = 1,040 trades. **938 trades fully walked** (473 Claude entries,
465 random); the pilot's 40 trades reused (protocol byte-identical, 0 pending). **102 trades not judged**: batches b088–b099
were stopped to keep inside the $200 ceiling (my orchestration counts against it); every pending trade lies in those batches.
The 18 other trades in them close before their first check-in. 3,156 check-ins answered, **0 invalid**: hold 2,001,
tighten_sl 981, close 72, partial_close 57, move_tp 45; 350 trades exited at a moved stop.
**Isolation:** 89 judge transcripts audited mechanically. One judge (b018) made one stray `sleep 0; true` call and
disclosed it; its 31 decisions were voided under the registered rule (kept in `voided-b018-decisions.jsonl`) and its 10
trades were re-judged by a fresh judge. **0 violations in the counted set.**

**Spend (API-equivalent on the plan; no API credits).** Full-run judges **$159.48 MEASURED** from transcript usage
($0.050–0.055 per check-in); pilot v2 $6.85 MEASURED; orchestration session INFERRED ~$25–35 (not measurable from inside).

**The registered rule (n >= 126 pairs, weekly-cluster 95% CI, Holm over a family of one):**

| contrast (mean [95% CI], trades) | Claude entries (n 473) | random entries (n 465) |
|---|---|---|
| HOLD net R / trade | +0.169 [−0.048, +0.385] (n 520) | +0.259 [+0.106, +0.393] (n 520) |
| Claude-managed net R / trade | +0.014 [−0.131, +0.173] | +0.052 [−0.066, +0.163] |
| **management dR vs HOLD (M0)** | **−0.159 [−0.261, −0.041] → FAIL** | **−0.124 [−0.197, −0.043] → FAIL** |
| vs its matched random intervention (M1) | −0.013 [−0.054, +0.031] | −0.046 [−0.072, −0.017] |
| vs the best fixed rule (B3, leave-one-fold-out) | −0.075 [−0.162, +0.018] | −0.101 [−0.167, −0.026] |
| entry value under HOLD (Claude − random, n 520 pairs) | −0.090 [−0.277, +0.097] (indeterminate) | |
| interaction (mgmt value Claude-entry − random-entry, n 419 pairs) | −0.006 [−0.118, +0.109] (indeterminate) | |
| end to end (Claude entry x Claude mgmt − random entry x HOLD) | −0.288 [−0.426, −0.137] | |

Robustness (added after the result; the registered 50-draw M1 above stays the primary): re-scoring the same 938 managed trades with
100 matched-random draws per trade gives vs M1 −0.011 [−0.051, +0.034] (claude entries, n 473) and −0.049 [−0.077, −0.019] (random
entries, n 465), the same reading. File: `comms/research/desk_lifecycle/full-c4e/robustness-m1-100/score.json` (`--m1-draws 100`).

Paired sd of management dR MEASURED 1.01–1.02 R (the pilot's 1.06–1.18 R estimate held); the resolution achieved is about
±0.10 R per arm, as option C intended.

**WHEN it costs and when it helps (per-check-in ablation; reported, not graded):**
- **Acting cost R:** all 1,155 non-hold answers −0.083 [−0.129, −0.030]. `tighten_sl` (981, 85 % of all actions) −0.097
  [−0.140, −0.047]; `move_tp` −0.155 [−0.302, −0.037]; acting at 0–1 R of open profit −0.12 to −0.19 (CIs exclude 0);
  acting on the regular clock −0.104 and on the first +0.5 R milestone −0.104 (CIs exclude 0).
- **Not acting earned R:** the 2,001 holds were worth **+0.142 [+0.042, +0.230]** versus closing at that check-in, most of
  all near entry (−0.5..0 R: +0.21, CI excludes 0).
- **The only positive pockets (n.s.):** `close` +0.078 [−0.18, +0.28] (n 72); acting below −0.5 R +0.129 (n 56); acting at the
  −0.5 R milestone +0.185 [−0.05, +0.33] (n 44). This repeats the pilot's sign (cut losers early), but the full run does not
  confirm it.

**Reading (DECIDED by the registered rule; interpretation marked).**
1. On the C48 contract, Claude managing a whole trade at every-4-bars-plus-events check-ins **loses about 0.12–0.16 R per
   trade versus leaving the bracket alone**, on its own entries and on random ones alike. **FAIL. Nothing about it promotes.**
   The fresh-window confirmation is moot for a FAIL.
2. INFERRED: the loss is **frequent tightening**. Claude moved a stop on 981 of the 3,156 scored check-ins (31 %), and that is where the R went. It is
   the failure mode the practice review predicts (judgement hurts as frequent tweaking). On random entries Claude is also
   significantly worse than the matched random intervention (M1), so its *timing* of those same actions is no better than
   chance; on its own entries it is indistinguishable from M1.
3. **Where the value is (the operator's question):** on this contract it is **in neither the entry nor the management**.
   Entry value is indeterminate (−0.09, CI spans 0; the random partner earned more under HOLD in this short-drift window).
   Management is negative. The only measured positive is holding. The interaction is zero: Claude does not manage its own
   entries better than random ones.
4. **For combining with the strategies:** this run does not support Claude managing the existing legs (the strategy arm is
   registered, not built, and DESK-MGMT-S0's single +1 R intervention was also negative). It argues for **holding to the
   bracket as the default**, with at most a narrowly scoped, separately registered *loss-cut* hypothesis (close at ≤ −0.5 R
   on new information). That hypothesis is the one pocket the pilot and the full run agree on in sign.

## 8. Not verified / limits

- Six crypto USD-M perps, Binance Vision 1h klines; the desk's venue is Bybit perp; funding charged, not seen.
- C48 is not the live 60-minute contract (§ 1.1; unit -03).
- The strategy arm's full-run version is registered, not built (`-02` § strategy arm); the in-flight bf56 slice is one checkpoint at +1 R, so it answers "Claude at the +1 R decision", not the full run.
- The judge sees no historical system book and no news; the packet is the only feed (as in D-S0 entry generation).
