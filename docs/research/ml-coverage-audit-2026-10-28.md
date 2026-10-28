# ML coverage audit — what we have, why it is that way, what to build next (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` (registry read from `/api/bot/ml/registry` ~06:05Z; roster re-parsed at `main@7108d8a3a`; VM runtime flags UNMEASURED) · lane `ML-COVERAGE-AUDIT` (dispatched by Manager Session 2026-10-27a) · Tier 1, analysis + planning only · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`docs/claude/work/checklist/ML-COVERAGE-AUDIT.json`](../claude/work/checklist/ML-COVERAGE-AUDIT.json) · roadmap `M25`, `L-DATA`
> **Operator question (2026-10-28 ~06:20Z, paraphrased):** *"We've been building MLs for a while. If they only cover ~4 symbols we've seriously gone wrong with the roadmap. Find exactly what we have, why it is that way, and use it to plan next week's builds and infra."*

## Answer in four lines

1. **Per-symbol models cover 4 of 23 rostered symbols** (BTC, ETH, SOL, MES). The manager's first look was right.
2. **Order-changing ML reaches 5 of 51 rostered legs (9.8%). All 5 are `bybit_1` demo legs. 0 of the 7 legs that trade real money or prop get one.** The 5 legs: the BTC vol gate on 3 legs, plus the donchian exit head on 3 legs, with BTC donchian counted once.
3. **Three causes:**
   - After 2026-07-21 the plan pointed the ML effort at model depth on BTC 15m, and no breadth objective ever existed.
   - The data and infra pipeline only builds features for BTC, ETH, SOL and MES. No head was ever built for the other symbols, so no features were added for them either.
   - An ML output only changes an order through a per-leg cell that someone has to write. Those cells exist for 3 BTC legs only, so even the SOL and MES advisory heads gate nothing.
4. **Next week's plan:** 7 builds that reuse the BTC recipe instead of adding more BTC variants (§ 4). In order: data for the alt coins, one pooled crypto vol head, the router cells for real-money legs, a wider exporter, a pooled daily head for equities and metals, freezing the BTC variant families, and a coverage detector.

---

## 0. Populations and sources (every number below is measured over one of these)

| id | population | source, read at |
|---|---|---|
| **P-REG** | the live trainer registry, 97 rows | `GET https://ict-bot.duckdns.org/api/bot/ml/registry`, 2026-10-28 ~06:05Z. `ml/status` reports a mirror age of 39 s and `stages: advisory 3 · shadow 20 · candidate 73 · research_only 1` |
| **P-MAN** | manifests in `ml/configs/*.yaml` (excludes `retired/` and `*.disabled`) | 72 files at `main@7108d8a3a` |
| **P-ROSTER** | **rostered legs**: strategies listed on ≥1 account whose `mode: live` in `config/accounts.yaml` | **51 legs**, re-parsed at `main@7108d8a3a`. Not rostered: `vwap`, `xauusd_trend_1h`, `gld/spy/qqq/tlt_pullback_1h` |
| **P-SYM** | symbols of P-ROSTER legs | **23 symbols**: BTC 9 legs, ETH 7, SOL 7, XRP 6, AVAX 4, MGC 4, ADA 3, SPY/QQQ/IWM/GLD/TLT/MES/MHG/SLV 2 each, IEF/GDX/TQQQ/QLD/SPLG/IAUM/SCHA/USO 1 each. The `claude_desk` leg spans 14 of these |
| **P-REAL** | P-ROSTER legs on a real-money or prop account | 7 legs: `xrp_pullback_2h`, `trend_donchian_eth_4h`, `trend_donchian_xrp_4h`, `ada_pullback_2h` and `trend_donchian_sol_prop` (all on `bybit_2` + `bybit_portfolio`, and `sol_prop` also on prop); `trend_donchian_eth_prop` (prop: breakout_2, tradeify_1, velotrade_1); `iaum_pullback_1d` (`alpaca_live`) |
| **P-CODE** | the decision-path consumers in `src/`, traced from code and spot-checked by this lane | file:line references in § 1b |

**The VM's runtime flags were not measured.** `REGIME_ML_VERDICT_MODE`, `CONVICTION_SIZING_MODE` and `CONVICTION_SIZING_ACCOUNTS` are not in the repo or on `/api/bot/config`, so their VM values are **UNMEASURED**.
- `docs/research/signals-catalog.yaml:231` already records the vol-gate value as UNMEASURED.
- The "vol gate is live" statements below are **INFERRED** from `docs/research/M25-readiness-assessment-2026-07-18.md:33` ("BTC enforce is LIVE").
- One relay read settles all three (`get-env`). It is the first observation on the row.

## 1. Inventory

### 1a. Model family × symbol × timeframe (P-REG, P-MAN; MEASURED)

| family | BTC | ETH | SOL | MES | pooled (`symbol_scope: all`) | any other rostered symbol |
|---|---|---|---|---|---|---|
| vol/trend **regime** heads (LightGBM, HMM) | 26 manifests, 5m/15m/1h. **Advisory: `btc-regime-15m-lgbm-fc-pcv-v2`** · shadow: lgbm-v2 15m, fc-pcv-v1, yz 1h/5m, plus baseline heads | 9 manifests, 5m/15m/1h. Shadow: 1h-v1, 1h-xasset, plus 15m-xasset and selfonly heads. **No advisory** | 5 manifests, 5m/15m. **Advisory: `sol-regime-15m-lgbm-fc-pcv-v2`** · shadow: fc-pcv-v1 | 8 manifests, 5m/15m/1d. **Advisory: `mes-regime-5m-lgbm-v2`** · shadow: 1d-v2, baselines | — | **none** |
| direction heads | 2 (15m), candidate | 2 (1h), candidate | — | — | — | none |
| conviction meta | 1 (`base-btc`), candidate | — | — | — | 2 (`conviction-meta-v1`, `-v1-bt`), candidate | rows from pooled data only |
| setup / meta-label | 5 BTC-only metalabel variants, candidate | — | — | 1 setup-quality, candidate | `xsym` (BTC+MES only), `p2pool` (BTC+ETH+SOL only), `setup-quality*`, all candidate | **none: the "pooled" models pool BTC, ETH, SOL and MES only** |
| trade outcome | — | — | — | 1 winrate, candidate | `trade-outcome-lgbm-v1`, candidate | trade rows only |
| execution quality | — | — | — | 1 | `execution-quality-baseline-v0`, shadow | **not read anywhere** (`conviction_inputs.py:47`) |
| exit head | not in the registry. A separate mirror artifact, `exit-head-donchian-1h-v1` (1h donchian family) | ← same | ← same | — | — | none |

- **Manifest count by symbol** (P-MAN, `symbol_scope` field): BTCUSDT 35 · ETHUSDT 12 · MES 9 · SOLUSDT 5 · all 11 · **XRP, ADA, AVAX, every equity and ETF, MGC, MHG: 0**.
- **Manifest count by family:** GBDT is 76 of 97 registered models (`ml_plan_status.py --diversity`, `MANIFEST-CONCENTRATION`).
- **Advisory models:** 3 of 97. All three are volatility-regime heads.

### 1b. What the live decision path actually reads (P-CODE)

| consumer | evidence | reads | symbol rule | effect | gate |
|---|---|---|---|---|---|
| Regime vol verdict (router) | `src/runtime/intents.py:1042-1092,1298`; `src/runtime/regime/ml_vol_verdict.py:341-411` | advisory regime heads | **Exact symbol.** No BTC fallback and no pooled head. A symbol without an advisory head resolves to `unknown`, and an `unknown` vol label never drops an intent | **drops intents**, but only where a `trend_vol` OFF-cell exists | `REGIME_ML_VERDICT_MODE` (default `off`; VM value UNMEASURED, INFERRED `use`) |
| `trend_vol` OFF-cells | `config/regime_policy.yaml::trend_vol` (MEASURED: 6 cells) | — | cells name **only `trend_donchian`, `ict_scalp_5m` and `squeeze_breakout_4h`**, all BTC legs on `bybit_1` | ⇒ **the SOL and MES advisory heads are scored and logged but gate nothing** | — |
| Exit head | `trend_donchian.py:796-804`; `exit_head_apply.py:76-127`; `strategies.yaml` sets `exit_head_action: close` | `exit-head-donchian-1h-v1` mirror artifact | 1h only, and only symbols in the artifact's own list (artifact not read; INFERRED BTC/ETH/SOL) | **closes positions** on `trend_donchian`, `trend_donchian_eth`, `trend_donchian_sol` | YAML per leg |
| Conviction stamp → sizing | `strategy_signal_builders.py:327-411`; `coordinator.py:2152`; `conviction_sizing.py` | **shadow-stage** models, auto-wired by symbol scope. A leg with `shadow_model_ids: []` opts out | scope = the leg's symbol, or `all` | resizes qty in `apply` mode (reductive) and on the slice allocator (`position_model: slices`, `bybit_1` only) | `CONVICTION_SIZING_MODE` (default `off`; VM UNMEASURED). The useful slots need trade-outcome or setup heads at shadow (there are none) or a regime-alignment calibrator (not established), so INFERRED: mostly falls back to `c_strat` |
| Advisory downsize (WS7) | `advisory_sizing.py:105-149` | advisory, non-regime models | — | **inert**: all 3 advisory models are regime heads, so `no_scores` and factor 1.0 | stage |
| Entry-head p_win | `entry_head_pwin.py`; `trend_donchian.py:505` | mirror artifacts | artifact symbol list | log only | — |

### 2. Coverage matrix against the roster (P-ROSTER, P-SYM, P-REAL)

| tier of ML at decision time | legs | symbols | real-money legs (P-REAL) |
|---|---|---|---|
| **A: an ML output can change an order** (vol gate or exit head) | **5 / 51 = 9.8%**: `trend_donchian`, `ict_scalp_5m`, `squeeze_breakout_4h` (vol gate), plus `trend_donchian_eth`, `trend_donchian_sol` (exit head) | BTC, ETH*, SOL* (* exit-head symbol list INFERRED) = **3 / 23** | **0 / 7** |
| **B: shadow conviction may resize** (needs `apply` on the VM, which is UNMEASURED; `bybit_1` demo only) | 16 `bybit_1` legs on BTC, ETH or SOL with `shadow_model_ids` omitted, including the 5 above | BTC, ETH, SOL | 0 (the `bybit_2` copies of the same legs are not slice or apply accounts; INFERRED) |
| **C: log-only** (shadow scores stamped into audit rows) | the remaining BTC, ETH, SOL and MES legs, plus equities and metals where wired | — | `trend_donchian_eth_4h`, `trend_donchian_sol_prop`, `trend_donchian_eth_prop` |
| **D: no per-symbol model exists at all** | every leg on **XRP (6), ADA (3), AVAX (4), MGC (4), MHG (2)**, and **all 15 equity/ETF symbols** (19 legs) | **19 / 23 symbols** | `xrp_pullback_2h`, `trend_donchian_xrp_4h`, `ada_pullback_2h`, `iaum_pullback_1d` |

- Regime-cell coverage ledger (`config/regime_coverage_exemptions.yaml`, MEASURED): **34 legs in `coverage_debt`, 13 `exempt`**. That leaves 7 rostered legs outside both lists. All 7 are BTC legs, and only 3 of them have a **vol**-axis (ML) cell; the other 4 rely on non-ML axes; their cells were not checked individually.
- The desk (`claude_desk`, 14 symbols) has no ML inputs: `shadow_model_ids: []`.
- **Bottom line:** the money the system actually risks (P-REAL: XRP, ADA, ETH 4h, SOL prop, IAUM) gets **no** order-changing ML. Tiers A and B are entirely on the `bybit_1` demo book.

## 3. Why it is this way (dated decisions; sources are files on `main`)

**3.1 Breadth stopped in July; depth on BTC took the capacity (plan / roadmap cause).**
- The per-symbol expansion happened, then stopped (manifest add dates are from `git log --diff-filter=A -- ml/configs/`, full history after `--unshallow`):
  - BTC and MES first (2026-05-22 to 05-28).
  - ETH (2026-06-19 and 06-28, "multi-symbol A, #1").
  - SOL (2026-06-28, #4918, "multi-symbol follow-on to ETH").
  - **The last new-symbol manifest was 2026-07-21** (`sol-regime-15m-lgbm-fc-pcv-v2`).
- Over the same weeks the **roster widened without ML**:
  - metals (2026-06-02, #2634) and ETF legs (2026-06-11, #3336);
  - nine alt cells on XRP/ADA/AVAX (2026-06-18, #3941), intraday ETFs (2026-06-21) and sub-$100 proxies (2026-07-07);
  - the M27 alt scalps (2026-07-21, #7254).
  - `new-strategy` wiring requires a regime cell **or** an exemption. It never requires a model.
- **Dated decision, 2026-07-21** (`docs/sprint-logs/S-M27-ALTCOIN-PROMOTION-2026-07-21.md:59,72,161`):
  - It found that XRP's pass was conditional on an off-cell gate, and that "no live regime head is trained for XRP".
  - It therefore gated XRP with a **strategy-local frozen spec**.
  - It recorded the follow-up as "migrate … once an XRP regime head is registered (**tracked informally … not a separate backlog item** — low urgency)". **The breadth gap was named and deliberately left unfiled.** That is the drop.
- From July on, M19 (`docs/research/M19-ai-trader-postmortem-and-staged-path-2026-09-28.md`) spent the effort on representation depth: embeddings, TCN, SSL, HMM and forecast features. These were almost all on **BTC 15m**, which now has 26 regime manifests. The post-mortem's lesson was that "the binding constraint is **labels**", read as closed trades.
- **The 2026-10-11 ML plan** (`ROADMAP.md` § "AI trader (ML) — build plan", tracks R/P/X/D/S/N/V/F):
  - It concluded that "the only ML that has earned an order-influencing role is *when is volatility high*".
  - It has **no symbol-coverage track or milestone**. The frontier track F measures concentration by **model family** (`--diversity`), never by symbol.
  - So the one head type proven to work was never carried to the 19 uncovered symbols. That recipe needs market data only, not trade labels.
- The operator re-opened breadth on **2026-10-27** (`ML-ARCH-GENERALIST-VS-SPECIALIST`: "one model per traded market … and one overall model"). The row is queued; nothing has been built yet.

**3.2 Data and infra only cover 4 symbols (pipeline cause; MEASURED from code).**
- **Dataset builder** (`scripts/ops/build_trainer_datasets.sh`):
  - builds the `market_features` the heads train on **only** for BTC (1h/5m/15m), ETH, SOL and MES (lines ~614-640);
  - builds `market_raw` 15m **only** for ADA, AVAX and XRP, and daily raw only for equities and metals. The code says so: "No market_features derivation — no head trains on these yet (add features when one does)" (WS-B, MB-20260712, ~line 944). That rule is circular: no features without a head, and no head without features.
- **Exporter** (`scripts/research/market_data_export.py:36-37`): `SYMBOLS = ("BTCUSDT","ETHUSDT","SOLUSDT")`, `TIMEFRAMES = ("15m","1h")`. Off-trainer ML research can only see those 3 symbols × 2 timeframes. On top of that:
  - the GitHub-runner download still 404s (`ML-DATA-RUNNER-FETCH`);
  - the BTC/SOL 15m shards were truncated (`ML-SHARD-TRUNCATED`, fix #18891 `landed_unproven`; truncated BTC/ETH 1h, BTC 5m and ADA 15m were reported 2026-10-18).
- **Trainer capacity:**
  - The trainer has 1 OCPU and 6 GB, with **0.0 spare OCPU and 0.649 GB spare memory** (`comms/cloud/compute_spare.json`, as_of 2026-10-27T12:40Z, p95 over 7 days).
  - The nightly cycle retrains every manifest: **66 trained** on 2026-10-28 01:24Z (`ml/status.last_cycle`), roughly two-thirds of them BTC/ETH variants.
  - Peak RSS for a 5m head is 4.70 GB against a 4.5 GiB MemoryMax (ROADMAP 2026-10-18 update).
  - So every new symbol competes with BTC variant retrains for the same box.

**3.3 Influence is authored per leg, and only 3 legs were authored (wiring cause; MEASURED).**
- Even a perfect head for symbol S changes nothing until a `trend_vol` cell names one of S's legs.
- `regime-selectivity` (correctly) requires a walk-forward net of cost before any cell. No cell has been authored since the BTC A/B (`docs/research/A-vol-gating-AB-evidence-2026-06-27.md`).
- So the **SOL advisory head (since 2026-08-02) and the MES advisory head gate nothing**, and 47 legs sit in `coverage_debt` or `exempt`.
- The per-leg walk-forward needs label files on a runner (`REGIME-VOL-LABELS-EXPORT`, still open) and equity fetch on the runner (`REGIME-EQUITY-LEG-FETCH`, blocked: the runner has no yfinance).

**Not a cause:** compute spend. Nothing here is blocked on money; every block is a builder, exporter or cell that was never written.

## 4. Plan for next week (post-reset). Proposed rows; the manager files them at Thursday planning

Ordered by value to real-money and desk legs, then cost. All builds use the **existing recipe** (LightGBM vol-regime head on `market_features`, which is the one family that has earned advisory) applied across symbols. They add no new variants. Every new head enters as `candidate`. Shadow is autonomous, advisory is Tier-3, and a router cell is Tier-3 with walk-forward evidence. Ceilings are per row.

| # | proposed row | what | tier · ceiling | roadmap | re-entry test (the observation that closes it) |
|---|---|---|---|---|---|
| 1 | **ML-COV-DATA-ALTS** | Builder: derive `market_features` for XRP/ADA/AVAX at 15m and 1h (raw 1h added), with the same params as BTC. Confirm #18891 untruncated every shard first. | 1 (trainer is autonomous territory) · $8 | L-DATA, M25 | `ml/builds` shows `market_features/{XRP,ADA,AVAX}USDT/{15m,1h}` ok in 2 consecutive nightly cycles. Each shard's `last ts` is ≤ 2 d old and its `row_count` equals its metadata |
| 2 | **ML-COV-POOLED-CRYPTO-VOL** | One **pooled** crypto vol-regime head (`symbol_scope: all`, `symbol` categorical; BTC/ETH/SOL/XRP/ADA/AVAX 15m), evaluated **per symbol** against (a) the constant baseline and (b) the existing per-symbol heads. This is the first concrete generalist-vs-specialist comparison for `ML-ARCH-GENERALIST-VS-SPECIALIST`. Pre-register the rule as a `research/queue` `ml_bakeoff` unit. | 1 · $10 | M25, L-DESK | The unit lands a verdict. PASS = on each of XRP/ADA/AVAX, per-symbol macro_f1 ≥ the constant baseline + 0.10, and on BTC/SOL within 0.02 of the specialist. A PASS earns a candidate → shadow manifest. A FAIL earns per-symbol specialist manifests for the alts instead |
| 3 | **ML-COV-ROUTER-CELLS** | Per-leg `regime_cell_walkforward` (net of the full cost stack) using the ML vol label, on the **P-REAL legs first** (XRP/ADA/ETH-4h/SOL-prop), then the SOL legs, which already have an advisory head. Depends on `REGIME-VOL-LABELS-EXPORT`. Output: Tier-3 cell proposals, or "no cell earns" per leg. | 1 (research) → 3 (cells) · $8 | L-REGIME, M25 | Each of the 7 P-REAL legs and 7 SOL legs has a committed walk-forward record with a verdict. Every PASS has its exact `trend_vol` YAML in front of the operator |
| 4 | **ML-COV-EXPORTER-WIDEN** | `market_data_export.py` SYMBOLS → every rostered crypto symbol; TIMEFRAMES add 4h, plus an equities/metals 1d set. Close `ML-DATA-RUNNER-FETCH` (route data units to Kaggle CPU). This moves the breadth work **off the saturated trainer**. | 1 · $5 | L-DATA | `MANIFEST.json` lists ≥ 6 crypto symbols × 3 timeframes plus the 1d set, with `stale_days` ≤ 2. One queued unit reads an alt shard off-trainer and lands a result |
| 5 | **ML-COV-EQUITY-DAILY** | `market_features` 1d for the 15 equity/ETF symbols plus MGC/MHG (raw already built nightly), and one **pooled daily** vol/trend head (`symbol_scope: all`, 1d) for the 26 equity and metal legs, including `iaum_pullback_1d` (real money). Fix `REGIME-EQUITY-LEG-FETCH` (yfinance on the runner) in the same row. | 1 · $10 | L-DATA, M25, L-TIMEFRAMES | The pooled 1d head is registered as candidate, with per-symbol macro_f1 against the constant baseline on ≥ 12 of 17 symbols in the eval record. `regime_debt_matrix` runs on `ief_pullback_1d` on the runner |
| 6 | **ML-COV-TRAINER-BUDGET** | **Stop growing the BTC variant families** (below). Move the frozen ones to a weekly retrain via `TRAINING_MANIFESTS`, so rows 1/2/5 fit inside 0 spare OCPU. Do not retire them: a line ends only on its registered exhaustion condition (operator 2026-09-27). | 2 (trainer timer/env) · $3 | M25, L-OPS | The nightly cycle trains ≤ 45 manifests. Trainer p95 CPU over 7 days is < 90% in `compute_spare.json`. The new alt/pooled manifests train nightly with rc 0 |
| 7 | **ML-COV-DETECTOR** | Add a `--coverage` mode to `ml_plan_status.py`. It re-parses the roster and registry, prints legs/symbols per tier A–D (this doc's § 2), records the count in `comms/ml-plan/<stamp>.json`, and flags any newly rostered leg with tier D. Wire it into `/ml-review` step 1. **This is the detector the gap never had.** | 1 · $3 | M25, M39 | Running it reproduces § 2's 5/51 and 4/23 at `main@7108d8a3a`. The next `/ml-review` record carries a `coverage` block |

**Order:** 7 (cheap; makes the gap visible every week) ∥ 1 → 2 and 4 in parallel → 3 → 5, with 6 before 2 lands on the trainer.
- **First-week target:** tier-D symbols drop from 19 to 16 (XRP/ADA/AVAX get candidate heads).
- The P-REAL legs then have a walk-forward verdict, which is what turns a head into order influence.

**BTC variant families to stop growing (no new manifests; frozen to weekly retrain, not retired):**
- `btc-regime-15m-lgbm-vt00{3,4,5}-pin-v1` and `-base-vt003-pcv-v1` (threshold sweep; vt003 audit-refused nightly)
- the BTC HMM line: `btc-regime-15m-hmm{,-fc,-cw}-v1`, `btc-regime-1h-hmm-v1`
- the `base-v003` / `base-pcv-v003` controls at 15m and 1h
- `btc-regime-15m-lgbm-fc-v1` (superseded by fc-pcv-v2)
- `btc-direction-15m-lgbm-{base-v003,fc-v1}` (direction failed offline: M19 post-mortem)
- the 5 BTC-only `setup-candidates-metalabel*` variants (keep the pooled `p2pool`/`xsym`)

That freezes about 17 manifests. Keep the advisory head, its shadow twins (`lgbm-v2`, `fc-pcv-v1`, `yz`), the funding `svble` head (P1) and `flow` (P2) on the nightly cycle.

## 5. What this audit did not establish (and how it closes)

| item | state | closes by |
|---|---|---|
| VM values of `REGIME_ML_VERDICT_MODE`, `CONVICTION_SIZING_MODE`, `CONVICTION_SIZING_ACCOUNTS` | UNMEASURED | one `system-action get-env` read. If the vol gate is `off`, tier A drops to the 3 exit-head legs |
| `exit-head-donchian-1h-v1` artifact `stage` and `symbols` | INFERRED (advisory; BTC/ETH/SOL) | a trainer-mirror read of `trainer_mirror/exit_head/*.json` |
| Whether the regime-alignment calibrator exists (conviction `c_reg`) | not checked | the same mirror read |
| Model *quality* per symbol | out of scope. Coverage is not edge, and every new head still goes through the ladder | rows 2/3 |

Both open observations ride the `ML-COVERAGE-AUDIT` row.
