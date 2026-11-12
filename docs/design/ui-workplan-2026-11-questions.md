# UI workplan 2026-11 — the eight operator questions, in plain words

> **Doc status:** `unknown` · category `plan` · last verified `2026-11-11` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
> **Gates this adds or changes: none.** This file only restates questions; Q8 asks whether to add one CI guard and recommends against it.

The source is [`ui-workplan-2026-11.md`](ui-workplan-2026-11.md) § 13 (questions 1 to 6) and § 16 (questions 7 to 9). That is nine numbered items. Item 6 is not a design question: it asks whether the nine row ids that were missing from `main` were meant to carry your wording. It is a process note for the manager, so it is left out here. The other eight are below, renumbered Q1 to Q8, with the source number in brackets. Each says what is asked, why it matters, the options, a recommendation, and what the UI lane does until you answer. Nothing here authorizes anything; a flip or a new store still needs its own approval.

## Q1 (source 1). May the manager turn the site sign-in gate on without another popup?

**Why it matters.** Sign-in (Google plus passkey) is built and the gate is off. Turning on `SITE_AUTH_ENFORCE=1` locks every `/api/*` route, so any tool that reads the API without a token would suddenly get "401". That is Tier-3.

**Options.**
1. Standing OK: the manager flips it once three things are done (hardening items, a 24-hour access-log check of who calls the API, tokens added to each caller found).
2. One OK per flip: you are asked each time. (Current default.)
3. Never enforce; keep the gate off.

**Recommendation: option 1.** The checks make the flip safe and the rollback is one unset. A popup after the checks add no new information. If you prefer less risk, option 2 costs one popup.

**Current default.** Option 2. The UI lane arms nothing and builds the checks only.

## Q2 (source 2). Is any anonymous read access wanted?

**Why it matters.** The gate is all-or-nothing, apart from 2 exact public paths and 3 public prefixes. A public read-only page or a shareable link would need a new public list.

**Options.**
1. No anonymous access; keep the current short public list. (Recommended.)
2. A public read-only dashboard view with a fixed list of safe routes.
3. Signed share links that expire.

**Recommendation: option 1.** Nothing in the plan needs it, and every public route is a hole to test. Add option 2 or 3 only when you name a person who needs it.

**Current default.** Option 1.

## Q3 (source 3). What is the base for the percent return on the Performance chart?

**Why it matters.** The chart shows cumulative return as a percent of capital. Which capital you divide by changes every curve.

**Options.**
1. Capital at the start of the chosen window (nearest hourly equity snapshot; prop uses the evaluation size; paper uses the configured balance). (Recommended.)
2. Current equity.
3. Both, with a switch.

**Recommendation: option 1.** It keeps curves comparable across categories and windows, and later gains cannot flatter earlier results. Current equity makes old trades look smaller as the account grows.

**Current default.** Option 1. With no capital record the line is drawn in dollars only and labelled "no capital record", never as 0 percent.

## Q4 (source 4). Prop take-profit and stop history: accept gaps, or fix the phone path?

**Why it matters.** Prop levels move through the phone bridge. If an amend never reaches `prop_journal`, the chart cannot show it.

**Options.**
1. Accept gaps; the chart says "no record" for those moves. (Recommended for now.)
2. Make the phone executor report every amend (a Tier-2 change).
3. Hide history for prop trades until option 2 is done.

**Recommendation: option 1, then revisit.** It is honest, costs nothing and ships now. Measure how often records are missing first; if it is common, do option 2.

**Current default.** Option 1: main lines only, no markers, tooltip "no record".

## Q5 (source 5). Are mirror and prop separate categories from real money on the Performance page?

**Why it matters.** The table has one row per category. Merging mirror into real money would double count the same trades; merging prop would mix firm accounts with ours.

**Options.**
1. Four separate rows: real money, real mirror, prop, paper. (Recommended.)
2. Merge mirror into real money, since Stage 2 is one stage.
3. Merge mirror and prop into real money.

**Recommendation: option 1.** The mirror is the demotion signal, so it must be readable by itself. Prop has its own firm limits. A combined total can still be a computed footer.

**Current default.** Option 1, derived from `config/accounts.yaml`, never hard-coded.

## Q6 (source 7). How should the data-collection "where to invest" view rank features?

**Why it matters.** It will steer where collection effort goes. It recommends only and authorizes nothing.

**Options.**
1. Rank by stable edge proxy times coverage gap divided by collection cost, with every factor shown in its own column. (Recommended.)
2. Rank by the asset class you plan to trade next.
3. Rank by edge proxy alone.

**Recommendation: option 1.** A gap in something with no edge is not worth filling, and an edge you already cover is not a gap. Showing factors keeps it from being an opaque score. Register the rule before first use.

**Current default.** Option 1, with "—" where a family has no coverage record.

## Q7 (source 8). Where does the feature-impact result live?

**Why it matters.** A new database table needs your OK and a data-wiring declaration. Files do not.

**Options.**
1. Files under `comms/feature_impact/`, read by the route. No new table. (Recommended for version 1.)
2. A new `feature_impact` table in a database.

**Recommendation: option 1.** It is enough for a weekly job and a heat map, and moves to a table later if queries get slow.

**Current default.** Option 1.

## Q8 (source 9). Add a CI guard that fails when a model uses features the catalog does not list?

**Why it matters.** The feature catalog was last generated 2026-10-08 and misses the newer entry models. A guard keeps it current, but it is a new gate, and new gates need your explicit permission.

**Options.**
1. No guard. The route computes and shows "models missing from the catalog" as a number, and the weekly review reads it. (Recommended.)
2. Add the guard so a new model with unlisted features fails CI.

**Recommendation: option 1.** It follows the no-new-gates rule, shows the gap in plain sight, and can be upgraded to a guard later if the number keeps growing.

**Current default.** Option 1.
