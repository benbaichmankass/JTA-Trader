# Health review 2026-10-28 — a venue-wedged GLD stop, a delisted ticker, and disk running out by about 11-11

> **Doc status:** `unknown` · category `evidence` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `HEALTH-REVIEW-20261028` (session_01AFoLuK9sfam8pmqP2UuRgz, dispatched by manager session_01AFoLuJi1vLTnYv9LbP6539) · window 2026-10-24 08:10Z → 2026-10-28 19:20Z · live reads 19:05–19:30Z · record [`comms/reviews/health/2026-10-28-health-review.json`](../../comms/reviews/health/2026-10-28-health-review.json)

**Grade: investigate.** There are 3 concerns (H6, H12, H15), 7 watches and 2 stalled calls. Real-money plumbing is clean: 4 real-money closes, all SL; the 1 open bybit_2 position is protected and reconciled. The problems are on paper accounts, in follow-through, and in capacity.

## 0. Prior calls (10-24 record; it predates the redesign, so its findings and filed PIs are graded)

The 10-24 record had 8 graded items: 5 hit · 0 miss · 2 unresolved · 1 void. Brier: INDETERMINATE (n < 10).
- **Hit.**
  - The ssh attribution (ONHEALTH-0001) and the auth-sweep coverage (ONHEALTH-0002) are both closed. This run's sweep covered the whole window: 321 slices, 0 unreadable.
  - The gate redefinition (ONHEALTH-0003) is closed: the gate now holds 87 items against 510 due.
  - The SHA-surface disagreement (41BO5V65): both surfaces now read SHAs that are on main, 9 min apart.
  - Close reasons were clean.
- **Unresolved, moving.** Disk prevention (VMDGITZI-0002, due 10-31). The prune got usage to < 85%, but the erosion continues.
- **STALLED ≥ 2 reviews, decided now (not re-filed).**
  - **GLD wedge** (PI-20260930-ZPDIPMDA-0001). Open on day 29, across 4 reviews. Escalated to `ask_operator` (call C1).
  - **TP doctrine** (PI-20261006-5FUGHVX8-0001). 0 of 77 routings compliant, against 0 of 52 on 10-24. Put to the manager as a scoping decision (C5).

## 1. CHECKS (population · value · prior)

| id | status | value (population) |
|---|---|---|
| H1 | ok | All trader-VM units are active and the heartbeat is 20 s old. Health snapshots: 813 of 815 ok over 168 h; max gap 15.5 min. |
| H2 | ok | The VM runs 3b6794253. Versus main 37646efca, 0 files differ under src/ or config/. The roster's layer 5 is current (14 accounts, 57 strategies). |
| H3 | ok | 8 of 8 probeable accounts were read. Not probed (`could_not_look`): breakout_2, tradeify_1, velotrade_1 (live prop, manual bridge). |
| H4 | watch | 11 invariants: 1 FAIL, 3 not_measured, 7 pass. The FAIL is the ib_paper/MGC journal at 14 against 12 at the broker; it is already filed (CDTDGVDN-0001). The protection checks paged "NAKED by 2" on a fully covered broker position, which was an instrument bug, **fixed here**. |
| H5 | watch | The window had 24 closes and 11 rejections. `splg_trend_long_1d` raises "no candle data" on every tick. The audit tail covers only 21 min, so coverage is partial. |
| H6 | **concern** | Closes: SL 20 · TP 1 · sl_cross 1 · live_review_close 2. There were 0 reconciler, watchdog or orphan closes, and the positive control held. **The GLD stop at 416.09 is crossed (price about 371) and does not fill.** |
| H7 | ok | INV-1..8 show recent=0. 0 closed rows are missing pnl, exit_reason or exit_price. |
| H8 | watch | 5 of 5 producer ledgers are fresh. `news_decisions` is `could_not_look`. |
| H9 | ok | 19 of 19 research-health alerts were delivered to Telegram. |
| H10 | watch | 61 runs, max gap 2.8 h. Throughput is 68 fired and 80 landed per 24 h. Red SLOs: theme_share 4 of 5 days, research_ops_not_run 4 of 5. Both have owners. |
| H11 | ok | Last trainer cycle: rc 0, 66 trained, 0 failed builds. 5 manifests have not trained for more than 93 d; handed to /ml-review. |
| H12 | **concern** | Live-VM free disk is 10.1 GB (22.5%). It was 12.0 GB on 10-24 and ~15 GB on 10-17, so it falls ~0.42 GB/day. **At that rate it crosses 10% around 2026-11-11.** |
| H13 | watch | ssh: 262 non-trainer accepts, all from one key. 1 collaborator. 0 regex hits over 51,872 added lines. run_secret_scanning is `could_not_look` (GHAS is off). |
| H14 | ok | 76 of 1,013 commits touched Tier-2/3 paths. All carry hold or operator-approved (checked by title, not by diff). |
| H15 | **concern** | The gate holds 87 items. 510 are due (prior: 110 → 256 → 369). **59 are unrouted, the oldest 94 d**, and the alarm is breached. The health backlog has 337 open items, 275 with no owner. |
| H16 | watch | soak-state: 8 ready, 12 accruing, 15 dead. It is stale: 13 legs marked "dead" were rostered on 10-27. |

## 2. ANALYSIS (my reading; p is my probability)

**Trends.**
- Disk: −0.42 GB/day, monotonic since the 10-17 prune.
- Due items: +~35/day, and unrouted items went 0 → 59 in 4 days.
- TP-doctrine debt grows with every leg rostered.

**Q1. GLD wedge** (alpaca_paper, 39 long).
- H-venue: Alpaca paper returns 2xx on the cancel but never moves orders 2e843e04/891ddff0. So the shares stay reserved and our close is refused for "insufficient qty".
- H-ours: we cancel the wrong ids.
- Test: the ids match the venue's own open-order list, and the 19:08Z RTH log says `cancel_accepted_ineffective`.
- **Venue survives, p 0.85.** No code fix closes it. One cause has 3 symptoms: the position is unmanaged, the gld_pullback_1d soak is dead, and GLD intents are refused.

**Q2. Silent leg.**
- Hypotheses: H-rename (SPLG → SPYM), an IEX gap, or a transient.
- Test: Yahoo returns "delisted" for SPLG. It returns SPYM with first trade on 2005-11-15, which is SPLG's inception date.
- **Rename survives, p 0.9.** The rostered alpaca_paper leg never evaluates, which violates the demo-floor rule.

**Q3. Disk.**
- The growth is monotonic across 4 readings, so the noise hypothesis is eliminated (p 0.9).
- The composition is pending the disk-usage-report (#20981). The prevention item is due 10-31.

**Q4. Open set.**
- H-no-owner: the research-ops record lists "routing of due pipeline items … not routed by this pass".
- H-broken-job: eliminated, because no routing job exists to break.
- H-intake: contributes.
- **No-owner survives, p 0.7.**

**Q5. MGC "NAKED by 2".**
- Test: at the broker the position is 12, the stop is 12 and the target is 12. The journal says 14.
- **This was a false money-at-risk page from the instrument, p 0.95.**

**Hunt.** I compared the WARNING/ERROR signatures in journalctl: GLD ×5 (known) and SPLG empty bars ×8. The SPLG one is new to the live path. That is how Q2 was found.

## 3. Decisions (ranked by money at risk)

| call | decision | tier | pre-registered check | ending |
|---|---|---|---|---|
| C3 disk < 10% ~11-11 | ship the prevention by 10-31; composition from #20981 | 2 | `status .vm_health.disk` ≤ 85% used on 11-04 | PI-20261017-VMDGITZI-0002 |
| C5 TP doctrine 0/77 | manager: assign an owning build lane or re-scope it to real_money first | 3 | `check_tp_doctrine.py` real_money compliant ≥ 1 | PI-20261006-5FUGHVX8-0001 (stalled; decision in report) |
| C1 GLD wedge | **operator**: open an Alpaca ticket to cancel the 2 order ids, or kill the item and record a venue-wedged exclusion | venue | alpaca_open_orders shows no GLD legs or no position | PI-20260930-ZPDIPMDA-0001 → ask_operator |
| C2 SPLG delisted | move the leg's symbol SPLG → SPYM; keep the leg id | 3 (data-backed) | an _eval of splg_trend_long_1d on SPYM bars | row HEALTH-20261028-SPLG-DELISTED |
| C4 routing owner | one recurring lane owns routing; run a kill pass on the 275 ownerless items | 1 | `pipeline.py --stats` alarm not breached 2 weeks running | row HEALTH-20261028-PIPELINE-ROUTING-OWNER |
| C6 invariant sizing | protection invariants size on the broker qty | 1 | `system_invariants.py --self-test` 66/66 | **fixed in this PR** (merged pending; a repo script, nothing to deploy) |

C3 ranks above C1 because a full disk stops real-money journal writes, while GLD is paper.

**Premortem.**
- C2: the symbol-keyed joins could split the SPLG and SPYM history. The row says to keep the leg id and check the readers.
- C4: a routing owner who only redates turns the open set into churn. The check counts the breached alarm, not the activity.

**Open-set walk** (bounded, 5 of 87):
- 3 kept_open: JN54P2HH-0006, HVCIFOQV-0001 and WQAPZD8B-0003. The last needs prop fill 90, which is outside the last 100 fills.
- 1 redated: WH81NW96-0001. 3 of 4 shards are whole and ADAUSDT 15m was not read.
- 1 escalated: the GLD wedge.
- 82 were left untriaged.

## 4. Not done

- **Disk.** The composition is not read yet; #20981 was still running when this page was written.
- **Security.**
  - Secret scanning could not run (GHAS is off).
  - Deploy keys and Actions secrets were not enumerated.
  - The 262 ssh accepts were attributed by key, not run by run.
- **H5.** The audit tail is 21 min; the window's enumeration rests on the 500-row journal page plus journalctl.
- **H3.** Prop venues were not probed.
- **H9.** Trade-refusal pings were not enumerated.
- **H16.** The soak readiness was not re-computed, because the weekly grade on 11-01 owns it.
