# Desk macro daily brief: the 13:00Z routine prompt (proposed, for the manager's trigger)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**

The manager pastes the block below into the 13:00Z trigger. `.claude/skills/trading-desk/SKILL.md` § 7b is the binding text and wins on any conflict.

```
DESK-MACRO-DAILY lane (advice-only, Tier 1). Read .claude/skills/trading-desk/SKILL.md section 7b and follow it in order.

The brief exists to PROPOSE TRADES from a WIDE input set. Operator, 2026-11-26, verbatim: "It needs to have very wide variety
of inputs, all the information that it needs in order to propose trades, and it needs to be proposing trades. That's what we
built here."

1. Grade the record: python3 scripts/ops/desk_macro_outcomes.py, then --summary. Calibrate today's judge_prior values on it.
2. Build the packet: python3 scripts/ops/desk_macro_packet.py --check (dry run, writes nothing: a broken source shows here),
   then python3 scripts/ops/desk_macro_packet.py (writes comms/desk/macro/packets/<stamp>.json). Read ALL of it:
   prices/ATR/levels for every rostered symbol (the panel), the screen (movers, unusual range), tradability, the calendar (note n_with_consensus and every schedule_unconfirmed row: re-check
   the date of any such row before using it), event-study priors, COT, valuation, crypto OI, roster legs and the desk book,
   prior outcomes. A part that is stale or could_not_look is evidence you lacked; say so in the brief's notes. Never treat it as
   an empty reading.
3. ANALYSE: the brief is an analyst, not an aggregator. Operator 2026-11-26, verbatim: "It should be looking at data to develop
   its own forecasts ... Not just aggregating open source data, but actually making inferences of deep big data analysis."
   Run python3 scripts/ops/desk_macro_analysis.py --packet <packet>: release nowcasts (own point + 80% interval + model vs naive
   RMSE) and the whole-panel relative-value screen. Go deeper in Python where a question calls for it (scripts/macro/ event-study,
   COT/valuation horizon-IC, sysdyn tools). Name every data gap in the brief's notes.
4. Search wide, Bigdata.com and the open web, one focus per call: every high-impact event in the next 14 days and its consensus;
   Fed pricing and speakers; rates and the dollar; equity-index drivers; gold and copper drivers; crypto flows (ETF flows,
   stablecoin supply, funding, liquidations, regulation); geopolitics and policy; plus at least one search per desk symbol.
   Every item you use becomes a sources[] entry (retrieved_at <= judged_at, content_sha256).
   The universe is ANY symbol we can trade (operator 2026-11-26: "it shouldn't be limited to any specific symbols ... if it
   has the data to support it"). For any symbol outside the panel you want to propose, run
   python3 scripts/ops/desk_macro_packet.py fetch --packet <packet> SYM [SYM ...] and list the file in fetch_paths. The writer
   refuses a symbol with no measured bars or no tradability answer for its venue_class.
5. Draft trades, always: rank candidates across every symbol you hold data for by expected net R, using the packet's ATR levels and the
   searched catalysts. List the best 3-5, each with entry/stop/TP (a real predictive TP inside the venue cap, no size),
   tp.p_hit, judge_prior, catalyst, invalidation and cited sources. On a thesis-free day, still list them; a low judge_prior is
   the honest record. The writer refuses trades == [] unless the packet's prices part is could_not_look.
   Every trade carries a `management` block for the live-trade-review sessions (operator 2026-11-26): design, expected_path,
   watch_for[] ({signal, source_ids, check?}), catalyst_timing[], tighten_if[], exit_early_if[] (>= 1), do_not[],
   thesis_invalidated_by. Give an item a machine check {kind: close_above|close_below|high_above|low_below, level} wherever
   it is a price level; the outcomes replay grades those.
   Run python3 scripts/ops/desk_macro_analysis.py --packet <packet> --candidates CANDS.json for each candidate's empirical
   TP-before-SL rate on its own history; set tp.p_hit / judge_prior from it.
   forecasts[] is required: copy each analysis brief_forecast, fill the consensus you found (or null), add any own asset
   forecasts, and list each trade's forecast_ids.
6. Set packet_path, packet_sha, fetch_paths and analysis_paths in the brief. Then run: python3 scripts/ops/desk_macro_write.py validate BRIEF.json, then
   write BRIEF.json. Commit the packet, every fetch and analysis file, the brief JSON and its .md render together on main (Tier 1). Report to the manager:
   the trade list, n sources, and every part whose read_state was not measured.

Constraints: advice-only. Never place, size or amend an order, and never write config/. Use the model tier (opus-tier) in the
brief, never a model id. No secrets and no balances.
```
