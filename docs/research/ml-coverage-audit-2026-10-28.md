# ML coverage audit — what we have, why it is that way, what to build next (2026-10-28)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` (registry read from `/api/bot/ml/registry` ~06:05Z; roster re-parsed at `main@7108d8a3a`; VM runtime flags UNMEASURED) · lane `ML-COVERAGE-AUDIT` (dispatched by Manager Session 2026-10-27a) · Tier 1, analysis + planning only · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Checklist row:** [`docs/claude/work/checklist/ML-COVERAGE-AUDIT.json`](../claude/work/checklist/ML-COVERAGE-AUDIT.json) · roadmap `M25`, `L-DATA`
> **Operator question (2026-10-28 ~06:20Z, paraphrased):** *"We've been building MLs for a while. If they only cover ~4 symbols we've seriously gone wrong with the roadmap. Find exactly what we have, why it is that way, and use it to plan next week's builds and infra."*

## Answer

1. **Per-symbol models cover 4 of 23 rostered symbols** (BTC, ETH, SOL, MES). The manager's first look was right.
2. **Order-changing ML reaches 5 of 51 rostered legs (9.8%). All 5 are `bybit_1` demo legs. 0 of the 7 real-money or prop legs get one** (§ 2).
   - **Since 2026-10-22, no learned model feeds conviction on any leg**: every package carries `c_strat` only (§ 6, measured on packages).
3. **The data-generation chain is mostly broken at the floor** (§ 6).
   - Of 57 rostered leg × demo-floor pairs, only **14 (25%) closed a trade in the last 14 days**.
   - The rest: 16 are BLOCKED (signals, no fills; most rejections record no reason), 6 SILENT, 2 have NEVER signalled since June, and 19 are quiet.
   - 48% of closed trades since 06-01 carry the close reason `other` and 15% `reconciler`.
4. **What the floor does generate is recorded and not learned from** (§ 1c):
   - The teacher data (desk decisions, live reviews and grades: `claude_judgments`, 627 rows) is built nightly, and **0 manifests train on it**.
   - Trade data trains only candidate models.
5. **Why** (§ 3):
   - After 2026-07-21 the plan pointed the ML effort at BTC-15m depth and never had a breadth objective.
   - The builders and exporter cover 4 symbols, and the trainer has 0 spare CPU.
   - Router cells exist for 3 BTC legs only.
   - **Every "done" check measured a declaration or a job run, never per-leg output** (§ 8).
6. **The fixes:**
   - ML breadth fixes are in § 4; the full gap list (G1–G11) is in § 7. The `ML-PROGRAMME-PLAN` lane owns the design.
   - One standing probe (`chain_probe`, § 8) would have caught all of this.
   - Filed: `PI-20261028-AGEAUDIT-0001` (root-cause every blocked/silent leg from audit relay #20840) and `-0002` (persist the rejection reason).

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

### 1c. Infra: what exists, what it builds, and what is recorded but never trained (MEASURED unless marked)

Sources: `GET /api/bot/ml/{status,builds,cycle}` read 2026-10-28 ~06:35Z (mirror age 39 s); `scripts/ops/build_trainer_datasets.sh`, `ml/datasets/families/*`, `ml/configs/*` and `comms/` at `main`.

| layer | what exists | scope (symbols × timeframes) | last good run / state |
|---|---|---|---|
| **Market data → `market_raw`** | Bybit kline (`bybit_v5_offvm`), IBKR/yfinance for MES, yfinance daily for equities/metals | BTC 1h/5m/15m · ETH 1h/5m/15m · SOL 1h/5m/15m · MES 5m/15m/1d · **ADA/AVAX/XRP 15m only** · 11 ETFs + MGC/MHG **1d only** | builds 2026-10-28 00:36–00:53Z, `overall_rc 0`. 24 h: 110 ok / 2 skipped / 0 failed (`ml/status.dataset_builds_24h`) |
| **Features → `market_features`** (what the regime heads train on) | vol/trend labels plus ~130 cols; `fc_*` forecast side-stream (Chronos-Bolt) for BTC/SOL 15m; cross-asset side-stream for ETH 1h | **BTC, ETH, SOL, MES only.** None for ADA/AVAX/XRP, equities or metals (builder comment ~l.944: "no head trains on these yet") | same build. ⚠️ The build log omits `symbol`/`timeframe` on most `market_raw`/`market_features` rows, so `ml/builds` cannot show **which** shard built (finding F-INFRA-1). Truncation history: `ML-SHARD-TRUNCATED` (#18891, `landed_unproven`) |
| **Our-data families** (`trade_journal.db`, pulled from the live VM; last pull ok 2026-10-28 04:17Z) | `trade_outcomes` 2,875 rows (pooled incl. backtest) + 34 (MES); `setup_labels` 2,875; `setup_labels_audit` 1,144; `conviction_meta` 1,545; `execution_quality` 1,760; `account_context` 45; `backtest_results`; `review_journal` (0 rows) | all closed trades, **every account incl. paper/demo** (no account filter in `trade_outcomes.py`; `is_backtest` is the only split) | built nightly |
| **Teacher (Claude) family `claude_judgments`** | live-review rows (`comms/live_review/reviews.jsonl`, 98), desk decisions (`comms/desk/decisions.jsonl`, 59, newest 2026-10-28 05:04Z), blind/revealed grades (617/546) | — | **built nightly, 627 rows — and NO manifest trains on it** (grep of `ml/configs/*.yaml` for `family: claude_judgments`: 0; positive control: the same grep finds 17 manifests on the other our-data families) |
| **Trainer** | `ict-trainer.timer` → `run_training_cycle.sh`: pull → build → train **every** manifest → publish mirror | 1 OCPU · 6 GB; **0.0 spare OCPU, 0.649 GB spare** (p95, 7 d, `comms/cloud/compute_spare.json` 2026-10-27) | nightly cycle **~31 min** of training (00:53→01:24Z, 66 trained, 3 audit refusals, rc 0) after ~17 min of builds. A second ~08:4xZ slot trains 0. Peak RSS of a 5m head 4.7 GB vs MemoryMax 4.5 GiB |
| **Registry** | append-only `ml/registry-store`, mirrored to the live VM | 97 models: advisory 3 · shadow 20 · candidate 73 · research_only 1 | `setup-quality-baseline-v0` (last trained 10-21) and `mes-setup-quality`/`mes-trade-outcome` (10-11) are **no longer trained**: their manifests are gone from `ml/configs`, but the registry rows still read `candidate` |
| **Live consumers** | § 1b | 3 advisory regime heads (only BTC gates anything) + exit head (3 donchian legs) + shadow conviction stamp | VM flags UNMEASURED (§ 0) |
| **Off-trainer research path** | `market_data_export.py` → private Kaggle dataset; `ml_bakeoff` units | **BTC/ETH/SOL × 15m/1h** only | runner download 404 (`ML-DATA-RUNNER-FETCH`) |

**Label pipelines: does each source of trade or decision data reach a dataset, and does anything train on it?**

| source | reaches a dataset? | trained on? | consumed live? |
|---|---|---|---|
| live + paper/demo closed trades (journal) | yes: `trade_outcomes`, `setup_labels`, `conviction_meta`, `execution_quality` | yes, but only by candidate manifests (`trade-outcome-lgbm-v1`, `conviction-meta-*`, `setup-candidates-*`, execution-quality baseline at shadow) | **no**. No trade-outcome/setup head sits at shadow, so conviction `c_wr`/`c_setup` are empty (INFERRED from § 1b), and `execution_quality` is explicitly ignored |
| desk decisions (`desk/decisions` → `comms/desk/decisions.jsonl`) | yes: `claude_judgments` (`kind: desk_*`) | **no** | no. Outcome join `DESK-20-OUTCOME-JOIN` and students `DESK-19-STUDENT-HANDOFF` are `blocked` (later phase) |
| live-trade-review rows | yes: `claude_judgments` (`ltr_review`) | **no** | no |
| blind/revealed post-trade grades | yes: `claude_judgments` | **no** | no |
| judged replays (DESK-18*) | not established (no family names them; UNMEASURED) | no | no |
| signal audit (4.56 M lines pulled) | `setup_labels_audit` 1,144 rows | baseline audit manifest (candidate) | no |
| backtest corpora | `backtest_results`, pooled-augment | metalabel/conviction candidates | no |

**The never-trained gap (as asked):** every teacher-side record the desk and live review produce is **recorded → built into a dataset → never trained**. The trade records are **trained → never promoted**, so nothing that learns from paper or demo trades reaches a decision. The detector for this, `DESK-21-NEVER-TRAINED-DETECTOR`, is `blocked`.

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

## 4. ML-breadth fixes (input to `ML-PROGRAMME-PLAN`, which owns the programme design and sequencing; the full gap list is § 7)

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

## 6. Ground truth: every strategy leg × its demo-floor account (operator scope extension 2026-10-28 ~06:25Z)

**Populations and sources:**
- **Rows:** every `config/strategies.yaml` strategy (57) × each demo-floor account (`bybit_1` · `alpaca_paper` · `ib_paper`) it is rostered on at `main@7108d8a3a`. That gives 57 rostered pairs (51 strategies; `claude_desk` sits on 3 floors, and `spy/qqq/iwm/tlt` on 2); the 6 unrostered strategies get one row each.
- **Packages:** `GET /api/bot/order-packages?strategy=<leg>&since=2026-06-01&include_paper&include_demo&limit=200`, read 2026-10-28 ~06:50Z.
  - ⚠️ A package row carries **no account field**, so package columns are per strategy across all accounts (finding G8).
  - The 200-row cap is hit by `mgc_trend_1h` and `vwap` (marked `+`).
- **Trades:** `GET /api/bot/trades/closed?since=2026-06-01&include_paper&include_demo`, paged to exhaustion: **1,812 closed trades**, filtered to the floor account.
- **"hist pkgs/wk" is a PROXY:** packages since 06-01 ÷ 21 weeks. It is **not** the Stage-0 expected rate. No per-leg Stage-0 signal rate is recorded anywhere machine-readable (`strategies.yaml` has no such field, and `SOAKS.json` correctly refuses `expected_per_week` as a soak exit), finding G9. So "QUIET-BY-RATE?" is a proxy judgement, not a measured one.
- **Soak state:** `scripts/ops/soak_state.py` computes it from the DB and **no route serves it** (G10), so it is UNMEASURED here. 68 contracts exist in `docs/claude/work/SOAKS.json`.
- **Model consumption:** every closed trade on every account lands in `trade_outcomes`/`setup_labels` (§ 1c), so every row's trades are **consumed by candidate models only**. "ML at decision" is the § 2 tier: A = order-changing; C = per-symbol shadow scores exist but are log-only; D = none.
- **Measured on packages:** since 2026-10-22, conviction carries **only `c_strat`** (15 packages across 10 legs, 2026-10-22..27). Before that it carried `c_setup` (+`c_wr`). `c_setup` stopped when `setup-quality-baseline-v0` was retired from shadow by operator decision 2026-10-21 (degenerate flat scores; registry `stage_history`). So **no ML input reaches conviction on any leg today**: tier B of § 2 is empty in fact, not just unmeasured.

**State legend:**
- **ACTIVE:** a trade closed on the floor account in the last 14 d.
- **BLOCKED:** packages in the last 14 d but no floor fill.
- **QUIET <30d:** a package in the last 30 d but no recent fill.
- **SILENT:** the proxy rate is ≥ 0.5 packages/wk but there has been no package for > 30 d.
- **QUIET-BY-RATE?:** the proxy rate is < 0.5/wk.
- **NEVER:** 0 packages since 06-01.

| leg | floor acct | symbol · tf | hist pkgs/wk (proxy) | last package | pkgs 14d | rejected/pkgs | last floor trade | trades 14d / 30d / since 06-01 | ML at decision (§ 2 tier) | state |
|---|---|---|---|---|---|---|---|---|---|---|
| `trend_donchian_1h` | bybit_1 | BTCUSDT · 1h | 0.1 | 2026-06-01 | 0 | 0/2 | — | 0 / 0 / 0 | C | QUIET-BY-RATE? |
| `trend_donchian_eth_4h` | bybit_1 | ETHUSDT · 4h | 1.3 | 2026-10-24 | 3 | 3/27 | 2026-10-25 | 2 / 5 / 19 | C | ACTIVE |
| `trend_donchian_xrp_adx25` | bybit_1 | XRPUSDT · 4h | 0.0 | — | 0 | 0/0 | — | 0 / 0 / 0 | D | NEVER SIGNALLED (0 pkgs since 06-01) |
| `xrp_pullback_2h` | bybit_1 | XRPUSDT · 2h | 2.8 | 2026-10-25 | 4 | 19/58 | 2026-10-27 | 4 / 5 / 23 | D | ACTIVE |
| `ada_pullback_2h` | bybit_1 | ADAUSDT · 2h | 3.3 | 2026-10-24 | 3 | 18/69 | 2026-10-24 | 2 / 7 / 38 | D | ACTIVE |
| `trend_donchian_eth_prop` | bybit_1 | ETHUSDT · 1h | 6.0 | 2026-10-24 | 16 | 0/125 | 2026-10-24 | 7 / 7 / 7 | C | ACTIVE |
| `trend_donchian_sol_prop` | bybit_1 | SOLUSDT · 1h | 2.3 | 2026-10-21 | 3 | 0/48 | 2026-10-21 | 2 / 2 / 2 | C | ACTIVE |
| `claude_desk` | bybit_1 | 14 symbols · — | 0.1 | 2026-10-27 | 2 | 2/2 | — | 0 / 0 / 0 | C | BLOCKED: signals, no fill |
| `claude_desk` | ib_paper | 14 symbols · — | 0.1 | 2026-10-27 | 2 | 2/2 | — | 0 / 0 / 0 | C | BLOCKED: signals, no fill |
| `claude_desk` | alpaca_paper | 14 symbols · — | 0.1 | 2026-10-27 | 2 | 2/2 | — | 0 / 0 / 0 | C | BLOCKED: signals, no fill |
| `ict_scalp_eth_15m` | bybit_1 | ETHUSDT · 15m | 3.8 | 2026-10-27 | 1 | 41/80 | 2026-10-27 | 1 / 7 / 39 | C | ACTIVE |
| `ict_scalp_xrp_15m` | bybit_1 | XRPUSDT · 15m | 2.8 | 2026-10-27 | 2 | 21/59 | 2026-10-05 | 0 / 7 / 38 | D | BLOCKED: signals, no fill |
| `avax_pullback_2h` | bybit_1 | AVAXUSDT · 2h | 7.4 | 2026-10-27 | 1 | 126/155 | 2026-07-25 | 0 / 0 / 8 | D | BLOCKED: signals, no fill |
| `eth_pullback_2h` | bybit_1 | ETHUSDT · 2h | 5.2 | 2026-10-27 | 1 | 8/109 | 2026-09-24 | 0 / 0 / 22 | C | BLOCKED: signals, no fill |
| `eth_pullback_prop_2h` | bybit_1 | ETHUSDT · 2h | 0.3 | 2026-10-27 | 1 | 2/7 | 2026-07-18 | 0 / 0 / 1 | C | BLOCKED: signals, no fill |
| `sol_pullback_2h` | bybit_1 | SOLUSDT · 2h | 4.1 | 2026-10-27 | 1 | 52/87 | 2026-09-16 | 0 / 0 / 11 | C | BLOCKED: signals, no fill |
| `fade_breakout_4h` | bybit_1 | BTCUSDT · 4h | 2.0 | 2026-09-30 | 0 | 29/43 | — | 0 / 0 / 0 | C | QUIET <30d |
| `fvg_range_15m` | bybit_1 | BTCUSDT · 15m | 0.0 | 2026-06-04 | 0 | 0/1 | 2026-06-05 | 0 / 0 / 1 | C | QUIET-BY-RATE? |
| `htf_pullback_trend_2h` | bybit_1 | BTCUSDT · 2h | 4.7 | 2026-09-15 | 0 | 31/99 | 2026-08-10 | 0 / 0 / 25 | C | SILENT (rate >=0.5/wk, no pkg 30d) |
| `ict_scalp_5m` | bybit_1 | BTCUSDT · 5m | 4.0 | 2026-10-27 | 2 | 27/84 | 2026-10-28 | 1 / 1 / 33 | A | ACTIVE |
| `ict_scalp_avax_5m` | bybit_1 | AVAXUSDT · 5m | 9.4 | 2026-10-27 | 1 | 114/197 | 2026-10-27 | 1 / 4 / 82 | D | ACTIVE |
| `ict_scalp_sol_5m` | bybit_1 | SOLUSDT · 5m | 6.0 | 2026-10-01 | 0 | 67/127 | 2026-09-27 | 0 / 1 / 61 | C | QUIET <30d |
| `ict_scalp_sol_15m` | bybit_1 | SOLUSDT · 15m | 3.5 | 2026-10-01 | 0 | 31/73 | 2026-10-02 | 0 / 3 / 48 | C | QUIET <30d |
| `ict_scalp_xrp_5m` | bybit_1 | XRPUSDT · 5m | 2.6 | 2026-10-05 | 0 | 10/54 | 2026-10-05 | 0 / 5 / 44 | D | QUIET <30d |
| `squeeze_breakout_4h` | bybit_1 | BTCUSDT · 4h | 0.7 | 2026-10-02 | 0 | 4/15 | 2026-09-28 | 0 / 1 / 8 | A | QUIET <30d |
| `trend_donchian` | bybit_1 | BTCUSDT · 1h | 1.8 | 2026-10-04 | 0 | 0/37 | 2026-10-05 | 0 / 1 / 30 | A | QUIET <30d |
| `trend_donchian_ada_4h` | bybit_1 | ADAUSDT · 4h | 1.6 | 2026-09-21 | 0 | 2/33 | 2026-10-04 | 0 / 1 / 21 | D | SILENT (rate >=0.5/wk, no pkg 30d) |
| `trend_donchian_avax_4h` | bybit_1 | AVAXUSDT · 4h | 1.2 | 2026-09-20 | 0 | 0/26 | 2026-09-21 | 0 / 0 / 23 | D | SILENT (rate >=0.5/wk, no pkg 30d) |
| `trend_donchian_eth` | bybit_1 | ETHUSDT · 1h | 2.4 | 2026-10-27 | 1 | 18/51 | 2026-10-02 | 0 / 5 / 20 | A | BLOCKED: signals, no fill |
| `trend_donchian_sol` | bybit_1 | SOLUSDT · 1h | 1.1 | 2026-10-04 | 0 | 9/24 | 2026-10-05 | 0 / 3 / 11 | A | QUIET <30d |
| `trend_donchian_sol_4h` | bybit_1 | SOLUSDT · 4h | 1.4 | 2026-09-21 | 0 | 6/30 | 2026-09-22 | 0 / 0 / 19 | C | SILENT (rate >=0.5/wk, no pkg 30d) |
| `trend_donchian_xrp_4h` | bybit_1 | XRPUSDT · 4h | 0.5 | 2026-10-08 | 0 | 0/11 | 2026-10-09 | 0 / 1 / 6 | D | QUIET <30d |
| `turtle_soup` | bybit_1 | BTCUSDT · 15m | 0.1 | 2026-09-23 | 0 | 2/3 | — | 0 / 0 / 0 | C | QUIET-BY-RATE? |
| `mes_trend_long_1d` | ib_paper | MES · 1d | 0.4 | 2026-10-06 | 0 | 0/9 | 2026-10-23 | 1 / 1 / 4 | C | ACTIVE |
| `mgc_pullback_1d` | ib_paper | MGC · 1d | 1.4 | 2026-10-19 | 1 | 21/30 | 2026-09-21 | 0 / 0 / 5 | D | BLOCKED: signals, no fill |
| `mhg_pullback_1d` | ib_paper | MHG · 1d | 0.9 | 2026-09-17 | 0 | 11/18 | 2026-09-14 | 0 / 0 / 6 | D | SILENT (rate >=0.5/wk, no pkg 30d) |
| `mgc_trend_1h` | ib_paper | MGC · 1h | 9.5+ | 2026-10-27 | 28 | 199/200 | 2026-09-10 | 0 / 0 / 3 | D | BLOCKED: signals, no fill |
| `ict_scalp_mgc_15m` | ib_paper | MGC · 15m | 2.0 | 2026-10-27 | 3 | 18/41 | 2026-10-26 | 3 / 7 / 23 | D | ACTIVE |
| `spy_trend_long_1d` | ib_paper | SPY · 1d | 0.1 | 2026-10-06 | 0 | 2/3 | — | 0 / 0 / 0 | D | QUIET <30d |
| `spy_trend_long_1d` | alpaca_paper | SPY · 1d | 0.1 | 2026-10-06 | 0 | 2/3 | — | 0 / 0 / 0 | D | QUIET <30d |
| `qqq_trend_long_1d` | ib_paper | QQQ · 1d | 0.3 | 2026-10-06 | 0 | 4/6 | — | 0 / 0 / 0 | D | QUIET <30d |
| `qqq_trend_long_1d` | alpaca_paper | QQQ · 1d | 0.3 | 2026-10-06 | 0 | 4/6 | 2026-09-24 | 0 / 0 / 2 | D | QUIET <30d |
| `iwm_trend_long_1d` | ib_paper | IWM · 1d | 0.1 | 2026-08-05 | 0 | 0/3 | — | 0 / 0 / 0 | D | QUIET-BY-RATE? |
| `iwm_trend_long_1d` | alpaca_paper | IWM · 1d | 0.1 | 2026-08-05 | 0 | 0/3 | 2026-08-28 | 0 / 0 / 4 | D | QUIET-BY-RATE? |
| `tlt_pullback_1d` | ib_paper | TLT · 1d | 0.6 | 2026-10-21 | 4 | 7/13 | — | 0 / 0 / 0 | D | BLOCKED: signals, no fill |
| `tlt_pullback_1d` | alpaca_paper | TLT · 1d | 0.6 | 2026-10-21 | 4 | 7/13 | 2026-10-22 | 2 / 2 / 5 | D | ACTIVE |
| `gld_pullback_1d` | ib_paper | GLD · 1d | 0.6 | 2026-10-20 | 3 | 9/13 | — | 0 / 0 / 0 | D | BLOCKED: signals, no fill |
| `ief_pullback_1d` | alpaca_paper | IEF · 1d | 0.2 | 2026-10-21 | 3 | 2/5 | 2026-10-22 | 2 / 2 / 4 | D | ACTIVE |
| `slv_trend_1h` | alpaca_paper | SLV · 1h | 2.9 | 2026-10-23 | 7 | 45/61 | 2026-08-25 | 0 / 0 / 14 | D | BLOCKED: signals, no fill |
| `slv_pullback_1d` | alpaca_paper | SLV · 1d | 0.3 | 2026-09-17 | 0 | 3/7 | 2026-09-28 | 0 / 1 / 4 | D | QUIET-BY-RATE? |
| `gdx_pullback_1d` | alpaca_paper | GDX · 1d | 0.6 | 2026-10-21 | 4 | 9/12 | 2026-09-28 | 0 / 1 / 2 | D | BLOCKED: signals, no fill |
| `tqqq_trend_long_1d` | alpaca_paper | TQQQ · 1d | 0.1 | 2026-10-02 | 0 | 2/3 | 2026-10-14 | 1 / 1 / 1 | D | ACTIVE |
| `qld_trend_long_1d` | alpaca_paper | QLD · 1d | 0.1 | 2026-09-21 | 0 | 0/2 | 2026-10-14 | 1 / 1 / 2 | D | ACTIVE |
| `splg_trend_long_1d` | alpaca_paper | SPLG · 1d | 0.0 | — | 0 | 0/0 | — | 0 / 0 / 0 | D | NEVER SIGNALLED (0 pkgs since 06-01) |
| `iaum_pullback_1d` | alpaca_paper | IAUM · 1d | 0.6 | 2026-10-20 | 3 | 8/12 | 2026-09-21 | 0 / 0 / 2 | D | BLOCKED: signals, no fill |
| `scha_trend_long_1d` | alpaca_paper | SCHA · 1d | 0.0 | 2026-08-17 | 0 | 0/1 | 2026-08-24 | 0 / 0 / 1 | D | QUIET-BY-RATE? |
| `uso_trend_1h` | alpaca_paper | USO · 1h | 1.9 | 2026-09-24 | 0 | 24/39 | 2026-09-24 | 0 / 0 / 11 | D | SILENT (rate >=0.5/wk, no pkg 30d) |
| `vwap` | — | BTCUSDT · 5m | 9.5+ | 2026-06-08 | 0 | 0/200 | — | 0 / 0 / 0 | C | NOT ROSTERED |
| `xauusd_trend_1h` | — | XAUUSD · 1h | 0.4 | 2026-06-15 | 0 | 0/8 | — | 0 / 0 / 0 | D | NOT ROSTERED |
| `gld_pullback_1h` | — | GLD · 1h | 2.6 | 2026-08-28 | 0 | 41/54 | — | 0 / 0 / 0 | D | NOT ROSTERED |
| `spy_pullback_1h` | — | SPY · 1h | 3.7 | 2026-10-01 | 0 | 56/77 | — | 0 / 0 / 0 | D | NOT ROSTERED |
| `qqq_pullback_1h` | — | QQQ · 1h | 3.3 | 2026-09-28 | 0 | 50/70 | — | 0 / 0 / 0 | D | NOT ROSTERED |
| `tlt_pullback_1h` | — | TLT · 1h | 4.3 | 2026-10-02 | 0 | 72/90 | — | 0 / 0 / 0 | D | NOT ROSTERED |

**Read-out (57 rostered leg × floor pairs):**
- 14 ACTIVE, 16 BLOCKED, 12 QUIET <30d, 6 SILENT, 7 QUIET-BY-RATE?, 2 NEVER.
- **Only 14 of 57 (25%) put a trade on the demo floor in the last 14 days.** For comparison, the manager's 06:20Z journal count was 23 of 51 strategies in 14 d. That count was any trade on the floor account by strategy, from `/api/diag/journal` capped at 1,000 rows. Both are measurements; they differ in route and population.
- **ML tier of the 14 ACTIVE pairs:** 1 is tier A (`ict_scalp_5m`), 5 are tier C, 8 are tier D.

**Rejected packages with no recorded reason:** e.g. `mgc_trend_1h` 103 of 119 since 09-01, `avax_pullback_2h` 39/48, `slv_trend_1h` 26/26. The package's `closeReason` is null, so the route cannot say why (finding G3a). The batched audit read is in flight (vm-diag issue #20840, 18 legs). Until it answers, every BLOCKED/SILENT cause below is **"not yet established"**, not a guess.

## 7. Gap list: cause and fix, ordered by data/learning value

The manager's brief says the plan lane (`ML-PROGRAMME-PLAN`) owns sequencing and design. This list states each gap, its cause as far as measured, and the fix the evidence points at.

| # | gap (measured) | cause | fix |
|---|---|---|---|
| **G1** | **Teacher data is recorded and never trained.** `claude_judgments` is built nightly (627 rows: 59 desk decisions, 98 live reviews, 617 blind / 546 revealed grades), and **0 manifests train on it** | the pipe was built "so it exists the day they do" (family docstring), and the student rows `DESK-19`/`20`/`21` are `blocked` as "later phase" | a first student manifest on `claude_judgments` (entry-generation role) at candidate. `DESK-20` outcome join first, so labels exist |
| **G2** | **No learned model reaches any decision since 2026-10-22** (conviction is `c_strat` only on every package). Trade data trains only candidates | `setup-quality-baseline-v0` was retired (degenerate); `trade-outcome-winrate` retired 06-30; `setup-quality-lgbm-v2` demoted 09-29 (4 of 9 features never served); nothing replaced them | a non-degenerate trade-outcome/setup head with **value-equal served features** to shadow, then conviction. Pair with § 4 rows 1–3 for the regime side |
| **G3** | **16 BLOCKED pairs**: signals but no floor fills, e.g. `mgc_trend_1h` 199/200 rejected (last fill 09-10), `avax_pullback_2h` 126/155 (last fill 07-25), `sol_pullback_2h` (last 09-16), `eth_pullback_2h` (last 09-24), `slv_trend_1h` (last 08-25), `claude_desk` (2/2 `no_fill_all_accounts`), and the IB copies of `tlt`/`gld` | **(a)** most rejections carry no reason on the package. Visible reasons: `all_accounts_noop`, `no_fill_all_accounts`, `empty_sizing_map: all_accounts_excluded_pre_sizing`. Per-leg root cause is pending audit #20840 | persist the rejection reason on the package; run `scripts/ops/dead_leg_audit.py` on a schedule; root-cause each leg from #20840 (the desk leg is `DESK-17`, in flight) |
| **G4** | **6 SILENT legs** (≥ 0.5/wk historically, no package > 30 d): `htf_pullback_trend_2h`, `trend_donchian_{ada,avax,sol}_4h`, `mhg_pullback_1d`, `uso_trend_1h` | not established (audit #20840) | same audit; `strategy_liveness.py` on a schedule |
| **G5** | **2 legs NEVER signalled since 06-01**: `trend_donchian_xrp_adx25`, `splg_trend_long_1d` | not established | same |
| **G6** | **Dirty labels**: of 1,812 closed trades since 06-01, **878 (48%) read `other` and 265 (15%) `reconciler`** on `/api/bot/trades/closed`. Packages show `reconciler_filled`, `exchange_flat_reconciled`, `stuck_*` closes | the route normalises unknown reasons to `other`; reconciler and watchdog closes are bugs under the session contract | map every exit reason (no `other`); fix the reconciler-close paths per leg; until then, label builders must exclude or flag non-TP/SL/strategy closes |
| **G7** | ML coverage: § 2 (5/51 legs order-changing, 0/7 real money; 19/23 symbols tier D) | § 3 | § 4 rows 1–7 |
| **G8** | packages carry no account | API shape | add `accounts[]` (from the package's fan-out) to `/api/bot/order-packages` |
| **G9** | no per-leg expected signal rate, so "quiet by design" cannot be told from "blocked" | never recorded at Stage 0 | record `expected_signals_per_week` from the leg's Stage-0 evidence as a **monitoring** field (never a soak exit) |
| **G10** | soak state is computed but not served | no route | serve `soak_state.soak_states()` read-only |
| **G11** | the build log omits symbol/timeframe (F-INFRA-1) | logging | add the fields to every `market_*` build row |

## 8. How did we report "done" without this?

Every check that went green measured a **declaration or a job run**. None measured **output per leg**:

- **DEMO-FLOOR (#20561 merged).** It established roster membership (layer 4, YAML). Nothing checks that each rostered leg produces packages and fills (layer 6).
  - `scripts/ops/verify_running_roster.py` is `manual-only`.
  - The inverse-roster anomaly detector it names (`PI-20260922-E32-…`) is not built.
- **`soak-contract-guard`.** It proves a contract *exists* for every rostered leg, not that a trade happened.
- **`check_strategy_coverage.py` / `regime_coverage_exemptions.yaml`.** They prove a cell *or an exemption* exists. 47 legs pass by exemption or debt.
- **Trainer health.** "66 trained, rc 0" and "110 builds ok" measure that jobs ran, not that the data covers the roster or that anything consumes it. `claude_judgments` builds 627 rows nightly and reads `ok`.
- **`ml_plan_status.py --plumbing/--diversity`.** It counts model **families** and registry/shadow liveness, never rostered legs or symbols.
- **The liveness tools exist and run on no schedule:**
  - `strategy_liveness.py` (manual);
  - `leg_flow_report.py` (manual);
  - `dead_leg_audit.py` (the 2026-08-14 "signals but never places" gap, exactly G3);
  - `verify_running_roster.py` (manual-only).
  - The detector that would catch G1, `DESK-21-NEVER-TRAINED-DETECTOR`, is `blocked`.

**Proposed standing probe (one, Tier 1): `chain_probe`.**
- **Schedule:** daily, plus on demand.
- **Covers:** every rostered leg × floor account.
- **Measures, each with an explicit read-state:**
  1. last package age against 3× the leg's expected interval (G9);
  2. packages → fills ratio over 14 d;
  3. share of closes that are TP/SL/strategy;
  4. whether its trades land in a dataset;
  5. whether ≥ 1 non-candidate model consumes that dataset;
  6. whether any model scores its decisions (§ 2 tier).
- **Output:** a red row in brief section 1 (`GET /api/bot/work/brief`).
- **Turns red when:**
  - a rostered leg has no package within 3× its expected interval;
  - ≥ 3 packages and 0 fills in 14 d;
  - a dataset has rows and 0 consuming manifests;
  - a rostered symbol is tier D.
- **What it would have caught:** run on 2026-10-28, it flags the 16 BLOCKED, 6 SILENT and 2 NEVER pairs, G1 and G2. G2 would have gone red on 2026-10-22, the day conviction lost its last ML input.

## 9. What this audit did not establish (and how it closes)

| item | state | closes by |
|---|---|---|
| VM values of `REGIME_ML_VERDICT_MODE`, `CONVICTION_SIZING_MODE`, `CONVICTION_SIZING_ACCOUNTS` | UNMEASURED | one `system-action get-env` read. If the vol gate is `off`, tier A drops to the 3 exit-head legs |
| `exit-head-donchian-1h-v1` artifact `stage` and `symbols` | INFERRED (advisory; BTC/ETH/SOL) | a trainer-mirror read of `trainer_mirror/exit_head/*.json` |
| Whether the regime-alignment calibrator exists (conviction `c_reg`) | not checked | the same mirror read |
| Model *quality* per symbol | out of scope. Coverage is not edge, and every new head still goes through the ladder | rows 2/3 |

Both open observations ride the `ML-COVERAGE-AUDIT` row.
