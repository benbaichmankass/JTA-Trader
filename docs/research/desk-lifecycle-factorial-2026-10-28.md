# DESK-LIFECYCLE-S0 — the desk's full-lifecycle factorial: where is the value (entry vs management), and how does the desk combine with the strategies?

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

Lane `DESK-LIFECYCLE-S0` (Tier 1 research), dispatched by Manager Session 2026-10-27a (session_01AFoLuJi1vLTnYv9LbP6539). Checklist row `docs/claude/work/checklist/DESK-LIFECYCLE-S0.json` (roadmap `L-DESK`). Driver `scripts/research/desk_lifecycle_driver.py` (tests `tests/test_desk_lifecycle_driver.py`). Units `RQ-20261028-d1f5-01` (self-check), `-02` (the C48 factorial), `-03` (the live 60-minute contract).

**Operator, 2026-10-28 ~06:10Z (paraphrased by the manager, binding for this lane):** the desk's edge test must be a FULL RUN of each trade from entry to close, not one step in isolation, so we learn WHERE the value is (entry vs management vs exit) and HOW to combine the desk with the existing strategies.

**Sections 1–6 were committed before any management decision was judged and before any static-rule or managed outcome was computed** (the only numbers computed before this commit are the instrument's own: the judged-1 reproduction, the self-check clauses and the checkpoint count under HOLD, all path-only). Results are appended in § 7 afterwards and labelled.

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

*(appended after the pilot; see below)*

## 8. Not verified / limits

- Six crypto USD-M perps, Binance Vision 1h klines; the desk's venue is Bybit perp; funding charged, not seen.
- C48 is not the live 60-minute contract (§ 1.1; unit -03).
- The strategy arm's full-run version is registered, not built (`-02` § strategy arm); the in-flight bf56 slice is one checkpoint at +1 R, so it answers "Claude at the +1 R decision", not the full run.
- The judge sees no historical system book and no news; the packet is the only feed (as in D-S0 entry generation).
