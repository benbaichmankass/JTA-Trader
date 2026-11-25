# Desk macro daily: trades + teacher labels (SPEC, step 1 of row DESK-MACRO-DAILY)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

> Lane ML-PRIMARY · 2026-11-25 · row `DESK-MACRO-DAILY` · a DESIGN for the manager's review (not yet adopted).
>
> **Gates this adds or changes: none.** Advice-only. The brief never places, sizes, amends or cancels an order and writes no
> `config/`. Its trade proposals are recorded as **shadow** rows and graded; nothing it emits reaches a venue until its own
> pre-registered, net-of-cost test passes and the normal ladder applies (OPERATING-PLAN § 2; ARCHITECTURE-CANONICAL § Active
> management). No new CI guard: the record checker below runs as a `--self-test` and inside the writer, not as a merge gate.

## 1. What it is for (operator 2026-11-25, row note)

Not a report. One daily Claude pass over macro conditions and events that produces:

1. **TRADES**: concrete, pre-specified proposals (symbol, side, entry, stop, a real predictive TP, horizon), graded exactly like
   desk proposals (replayed on real candles, net of the full cost stack), plus **informs** tags that modify existing legs
   (avoid / size-down / note, with an expiry).
2. **TEACHER LABELS** for two students:
   - the **macro sleeve** (M28 value / M29 system dynamics; dormant since MACRO-RESHAPE was dropped): daily regime call and
     per-asset macro tilt, stamped point-in-time, are labels and features the sleeve can be trained on and checked against;
   - the **news model** (NEWS-ALPHA-PROGRAM): Claude's per-event classification (class, direction, magnitude, horizon,
     confidence) is the supervised target / distillation set, and the graded outcomes say which classes move prices.

The pattern is the existing desk one (DESK-19-STUDENT-HANDOFF, `ml-claude-distillation-DESIGN.md`, the `claude_judgments`
pipe): Claude decides now (slow, expensive, broad context), the cheap model learns to reproduce the decisions that **graded
well**. The value of the labels depends on their being point-in-time and unedited, so the schema below is fixed from day 1.

## 2. The daily record: `comms/desk/macro/<YYYY-MM-DD>.json` (one per brief, append-only, never edited)

Machine-readable first; the human render (`<date>.md`) is generated from it, never the other way round.

```jsonc
{
  "schema": "desk_macro_brief/1",
  "brief_id": "DMB-20261126T1300Z",
  "judged_at": "2026-11-26T13:07:00Z",          // when Claude decided
  "info_cutoff_at": "2026-11-26T13:00:00Z",     // the packet's data cutoff
  "model": "opus-tier",                          // a TIER, never a model identifier (desk rule 6)
  "skill_sha": "…", "packet_sha": "…",
  "sources": [                                    // every input actually read, desk external_context[] shape
    {"source_id": "S1", "kind": "econ_calendar|cot|valuation|bigdata_news|web|price_panel|funding",
     "ref": "comms/macro/econ_calendar_upcoming.json | URL | bigdata doc id", "retrieved_at": "…", "content_sha256": "…",
     "influence": "decisive|supporting|checked_only"}
  ],
  "regime": {"call": "risk_on|risk_off|neutral", "axes": {"growth": -1|0|1, "inflation": …, "liquidity": …, "vol": …},
             "confidence": 0.0-1.0, "basis": "free text, cites source_ids"},
  "tilts": [ {"asset": "SPY|TLT|GLD|BTCUSDT|…", "tilt": -2..2, "horizon_days": 5|20|60, "confidence": …, "basis": "…"} ],
  "calendar": [ {"event_key": "US_CPI_2026-12-10", "at": "…", "class": "scheduled.macro.cpi", "consensus": …,
                 "read": "free text", "affected": ["SPY","TLT"], "source_ids": ["S1"]} ],
  "events": [                                     // UNSCHEDULED: the news-model teacher rows
    {"event_id": "EV-…", "published_at": "…", "first_seen_at": "…", "class": "<taxonomy § 3>", "entities": ["…"],
     "direction": -1|0|1, "magnitude": "small|medium|large", "horizon_days": 1|5|20, "confidence": …,
     "affected": ["symbol", …], "source_ids": ["S3"], "summary": "…"}
  ],
  "trades": [                                     // the desk proposal object, unchanged, so desk grading applies
    {"proposal": {"symbol": "…", "venue_class": "etf|linear_perp|cme_micro", "side": "long|short", "timeframe": "1d",
                  "horizon_bars": 5, "entry": {"type": "limit|market", "level": …, "good_till_bars": 2},
                  "stop": {"level": …, "basis": "…"}, "tp": {"level": …, "basis": "…", "p_hit": 0.10-0.99},
                  "expected_r_net": …, "thesis": "…", "novelty": "new|duplicates_system_package|unverifiable",
                  "onboarding": "onboarded|not_onboarded"},
     "judge_prior": 0.0-1.0, "catalyst": "event_key|event_id|regime", "invalidation": "falsifiable condition, not just the stop"}
  ],
  "informs": [ {"leg": "<strategies.yaml leg>", "action": "avoid_new|size_down|note", "until": "…", "reason": "…",
                "catalyst": "event_key|event_id"} ],
  "no_trade_reason": "required when trades == []",
  "training": {"train_eligible": true, "gate_eligible": false, "label_clean_from": "<model knowledge cutoff>"}
}
```

Rules the writer enforces (refuse the record, never fix it up):
- every `retrieved_at` ≤ `judged_at` (the desk timestamp rule); effective info time = max(info_cutoff_at, max retrieved_at);
- `trades[].proposal` passes the desk's own `proposal_problems` geometry + TP-doctrine checks (`scripts/ci/check_desk_records.py`);
  no size-shaped key anywhere (desk rule 2);
- `informs[].leg` exists in `config/strategies.yaml`; every judgement cites ≥ 1 `source_id`;
- a brief is written once; a correction is a new brief with `supersedes`, never an edit.

**Label hygiene (binding for the teacher use).** A Claude judgement about an event that happened before the model's knowledge
cutoff can be contaminated by remembered outcomes. Historical "replays" of Claude on past news are therefore NOT clean labels;
only briefs judged **after** `label_clean_from` are train-eligible as teacher labels. Historical backfill is still useful for
the PRICE side (event studies on archived events with mechanical classification), never as Claude labels.

## 3. Event-class taxonomy (v1, fixed before any test; extend only by version bump)

`scheduled.macro.{rate_decision, cpi, nfp, gdp, pmi, claims}` · `scheduled.earnings.{index_heavyweight, rostered_symbol}` ·
`unscheduled.corporate.{ceo_departure, guidance_cut, m_and_a, buyback, accounting_issue}` ·
`unscheduled.tech.{product_proof, regulatory_approval, outage_or_failure}` ·
`unscheduled.policy.{tariff, sanction, fiscal, central_bank_unscheduled}` · `unscheduled.geopolitical.{conflict, election}` ·
`unscheduled.crypto.{listing, hack_or_exploit, regulatory, etf_flow}` · `other`.

## 4. Inputs and sources (existing first; gaps named)

| Input | Source | Point-in-time? | State |
|---|---|---|---|
| Scheduled macro calendar + consensus | `comms/macro/econ_calendar_upcoming.json`, `econ_calendar_snapshots*.jsonl` (FXStreet, PIT survey backfill) | yes (observed_at, append-only) | exists |
| Event-study priors per release kind | `comms/macro/econ_event_study_*_scorecard.json` | yes | exists |
| Positioning | `comms/macro/cot_snapshots.jsonl` | yes | exists |
| Valuation (M28) | `comms/macro/` valuation snapshots, `config/macro_valuation.yaml` | yes | exists |
| System dynamics (M29) | `sysdyn_gas_*` | yes | exists (gas only) |
| Crypto funding / OI | Binance Vision metrics (as in `prop_ml_leg`) | yes | exists |
| Price / vol panel | Alpaca SIP daily, Binance Vision | yes | exists |
| News + unscheduled events | Bigdata.com search/events (MCP) | per-doc published_at | exists, live only |
| News archive for event studies | GDELT (`news_alpha_features.py`) | yes | exists (features part built) |
| Live web context | DESK-14 web reads (`external_context[]` logging) | retrieved_at | exists |
| Earnings calendar for rostered symbols + heavyweights | PROBED 2026-11-25 (fixtures in `comms/macro/earnings_calendar_probe_20261125/`): (a) Nasdaq `api.nasdaq.com/api/calendar/earnings?date=` (keyless, per-date list: symbol, time, consensus EPS forecast, # ests, reported EPS, surprise); (b) yfinance `get_earnings_dates` (per-symbol history + next date, EPS estimate / reported / surprise) | forward: yes if snapshotted daily (append-only `observed_at`); historical estimates: **unverified PIT** (may be the last pre-release consensus or revised) | **source found**; build a daily forward snapshot producer; use history only for event DATES, not for consensus, until PIT is shown |
| Open positions / rostered legs | desk scan packet (`latest_scan.json`) | yes | exists |

## 5. Grading (how Claude's macro judgement gets a measured hit rate)

- **Trades**: replayed from `info_cutoff_at` on real daily candles by the desk outcome replayer (`scripts/ops/desk_outcomes.py`
  logic, daily timeframe), net of the full cost stack; per-trade R, calibration of `judge_prior` and `tp.p_hit`. Graded like
  DESK-9; the baseline is the same symbol's base-rate bracket (the desk `alternatives[]` convention).
- **Informs**: counterfactual on the tagged leg's trades inside `[judged_at, until]`: realised vs with-the-tag-applied, net of cost.
- **Events (news teacher)**: abnormal return of each `affected` symbol at 1d / 5d / 20d vs its own drift and the index, signed by
  `direction`; per-class hit rate and mean signed abnormal return; calibration by `confidence`.
- **Regime / tilts (macro-sleeve teacher)**: forward 5d / 20d / 60d return of each asset, signed by tilt; IC per horizon; vs the
  naive floor ("no tilt" and "yesterday's tilt"), macro-research invariant 5.

## 6. Teacher → student wiring

- A dataset family `macro_judgments` (sibling of `ml/datasets/families/claude_judgments.py`): one row per (brief, judgement),
  the judgement as label, `sources` / features as of `info_cutoff_at`, the graded outcome joined once its horizon closes,
  `train_eligible` only when `judged_at ≥ label_clean_from`; consumption tracked in a `consumed.jsonl` like the desk's.
- Students learn ONLY classes whose graded outcome is positive net of cost (DESK-19 stage criteria); the rest train a
  "this class does not move prices" prior for the news model.

## 7. Build order (each step a commit or a unit; no memos)

1. **This spec** (held PR for the manager).
2. **Prototype**: `scripts/ops/desk_macro_write.py` (writer + refusal rules above, `--self-test`), a JSON schema file, the
   render, and a desk routine/skill section that runs the brief once a day (advice-only, shadow trades). Grading adapter for
   daily-bar replay.
3. **Pre-registered tests** (research/queue units, rules fixed before any run):
   - (a) scheduled-event conditioning of EXISTING legs (reuse the econ event-study scorecards; IR-MACRO-ANNDAY-POOLED was
     dropped as value-unknown, so this is the pooled release-day read under a fresh unit, not a revival of the row);
   - (b) unscheduled event study per taxonomy class on the GDELT / Bigdata.com archive with MECHANICAL classification
     (no Claude labels, see label hygiene), abnormal return at 1d/5d/20d net of cost, one unit per class with n stated;
   - (c) the longer-horizon macro trade arm: graded from the live briefs' shadow trades. Forward-only by nature (a Claude
     label on a past event may carry remembered outcomes, see Label hygiene in section 2), so its n accrues ~1-3 trades/day: the unit states the accrual rate and the date
     its pre-registered n is reached (macro-research invariant 4), and the event-study units (b) carry the near-term evidence.
4. A pass → the normal ladder. A fail → the next iteration from the diagnosis (regime is a standing lever, REGIME-PROGRAM).

## 8. Open questions for the manager (preferences no data settles)

- Cadence: once daily at a fixed time (proposed **13:00Z**, before the US open, after the European morning), or twice?
- Universe for trades: the desk's existing `account_symbols` (SPY QQQ IWM GLD TLT, MES MGC MHG, the desk perps), or wider?
