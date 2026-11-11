# Health review 2026-11-11 — the live trader VM's disk is refilling (24% free, about −11.6 points a week); real money is clean

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-11` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `HEALTH-REVIEW-20261111` (session_01AFoLuLK6atheaCCZ33wjBJ, dispatched by Manager Session 2026-11-11a under the 2026-11-11 weekly reset) · window 2026-11-04 19:45Z → 2026-11-11 20:00Z · record [`comms/reviews/health/2026-11-11-health-review.json`](../../comms/reviews/health/2026-11-11-health-review.json)

**Grade: investigate.** 3 concerns (H10, H12, H15), 7 watches, 1 could_not_look (H16), 3 stalled calls. Live reads were partial. `DIAG_READ_TOKEN` was rotated (direct diag returns 401), the relay cut each of 14 paths to about 4 KB, and 63–80 Actions runs were queued. So `system_invariants.py`, the audit tail and the ssh sweep did not run. That gap is owned by AUD-20261111-RELAY-INVARIANTS-BRIDGE and is not re-filed here.

## S. Scoreboard (`/api/bot/performance`, window 7d since 11-04 19:21Z; journalTrust carried)

| book | n | net $ | net R | read-state |
|---|---|---|---|---|
| Real money (bybit_2, alpaca_live) | 11 | +3.82 | +3.77 | read; bybit_2 known-divergent |
| Mirror (bybit_portfolio, alpaca_portfolio) | 10 | +1,280.81 | +3.94 | read; bybit_portfolio unrecorded |
| General paper | 83 | −36,749.85 | −2.43 | read; 95% pnl coverage |
| Real money, lifetime | 487 | −137.79 | −152.12 (PF 0.63) | read; 78% coverage |

% per book: "—" (no balance read; public repo). Two trades make up most of paper's $ loss: alpaca_paper SLV 7005 (−$28,137 on 26,615 shares) and IWM 7011 (−$9,622). Both are SL exits of about −1.5 to −2 R. That is a sizing question for `/performance-review`.

**Would a sceptical quant believe it?** ml_entry is 8 of the 11 real-money closes (+3.62 R). Its offline record shows expR +0.0271 on n = 907 held-out, with a fixed-TP 95% CI of [−0.042, +0.099]. That figure is quoted from PI-20261104-PREP1104-0001, not re-run here. The interval spans zero, so not yet. The leg also has no live-vs-backtest band; that item owns it.

## 0. Prior calls (11-04 record, 8 calls)

- **Hit, closed:**
  - C1 TLT over-cover: ib_paper TLT now rests one OCA group (1234/1235).
  - C2 trainer disk: 81.8% used, flat, under 90%. Row closed; `ict-trainer-disk-alarm.timer` is the detector.
- **Miss:** C3 MGC journal now equals venue (11 = 11). The drift did not widen. Row closed; the repair path is unknown.
- **Unresolved:** C5. The rule is met (max snapshot gap 15 min), but the 11-02/11-03 gaps were never explained. Closed as not reconstructable.
- **Void:** C6 GLD. The operator decided 11-04, and GLD 5209 closed by SL on 11-09. GLD-WEDGE-RETRO (due 11-18) owns prevention.
- **Stalled:**
  - C4 leverage pre-flight: still failing on the 18:11Z boot. Row due 11-13.
  - C7 research SLOs: 9 breaches a day. AUD-20261019-RESEARCH-SLO-RED has been stalled for 3 reviews; a re-scope proposal is noted on the row.
  - C8 unrouted: stalled 3 reviews. Its row is dropped as superseded by WSD-DRAIN-W2 (the register now lives in `work_store.db`).

*Footer: 5 hit · 1 miss · 1 unresolved · 1 void; Brier INDETERMINATE (n < 10). Follow-through cohort: 8 filed / 2 done / 6 open (read from the stale export, see C2).*

## 1. CHECKS

- **H1 watch.** All canonical units are active. `ib-gateway-watchdog.timer` is inactive by design on this VM. 760 snapshots in 168 h: 741 ok, 17 watch, 2 concern; max gap 15 min. The two ict-web-api outages today (about 2 min and 1 min) are invisible at the 15-min cadence.
- **H2 ok.** The VM runs `9d61127`; on disk is `6c2dc87`. 0 `src/` or `config/` files differ up to origin/main.
- **H3 ok.** 8/8 broker-API accounts read `api_ok`. The 4 manual-bridge prop accounts and the 2 shelved ones are could_not_look.
- **H4 watch.** Journal and venue agree on all 15 open positions. Each of the 4 IB and 3 Alpaca positions has exactly one stop and one target at full qty. Bybit venue orders were not read (truncated).
- **H5 watch.** 96 closes in the window. The exit loop is fresh with 0 interval breaches. The signal→package audit is could_not_look (truncated).
- **H6 watch.** Real money, 11 closes: SL 4, max_hold 4, TP 3, all clean. Paper, 83 closes: 2 `exchange_flat_reconciled` (see C7). 0 new orphans (newest `orphan_created` is 09-16).
- **H7 ok.** 0 rows with close before open; 0 missing exit price; 1 missing pnl (7042).
- **H8 watch.** 5/5 producers fresh. news_decisions is could_not_look for the 3rd week; AUD-20261104-PRODUCER-OK-OVER-CNL owns it.
- **H9 ok.** 7 of 7 research alert runs delivered to Telegram.
- **H10 concern.** 89 runs; one gap of 4.14 h. Breaches per day went 6 → 9 over the window.
- **H11 watch.** Timer active; last cycle rc 0 but trained 0 models. The registry is 98 rows now and was 98 on 11-04.
- **H12 concern.** Live VM: 76.1% used, 24.0% free. Free space by review: 26.7 → 22.5 → 35.6 (after the prune) → 24.0%. Trainer flat at 81.8%.
- **H13 watch.**
  - No literal secret in the window's diff of config, deploy and workflow files (keyword grep).
  - The repo has 1 collaborator (the owner).
  - `run_secret_scanning` is could_not_look: GitHub Advanced Security is not enabled.
  - The ssh sweep was not run.
  - **New:** relay replies publish the IB paper account id (C5).
- **H14 ok.** 111 of 1,640 commits touched Tier-2/3 paths. All 4 sampled carry a hold or manager-merge record.
- **H15 concern.** The store holds 4,211 items, with 812 open observations, all owned. The off-VM gate reads the 11-06 export: 444 items, 311 unrouted.
- **H16 could_not_look.** `SOAKS.json` has no state field (2nd review). Soak state now lives in the `PI-SOAK-20261108-*` store items.

## 2. ANALYSIS

**Trend.**
- Live disk regrowth projects 85% used around 11-15 and 10% free around 11-19.
- Research SLO breaches rose every day of the window.
- Real-money exits have been clean for 3 reviews running.

**Questions.**

1. **Why is the live disk refilling?**
   - Hypotheses: (a) an uncapped writer; (b) journald growth (its cap needs a sudoers line); (c) noise, i.e. a one-off backup.
   - Test: the disk-usage-report (#24935).
   - Survivor: (a), MEASURED by the report at 19:57Z. Two journal backups left by the Tier-2 prop-report helpers (11-05: 2.37 GB; 11-10: 2.57 GB) total 4.9 GB, about 80% of the ~6 GB regrowth. Syslog adds 1.7 GB; the journal DB itself is 2.61 GB.
2. **Are the register numbers real?**
   - Hypotheses: (a) the export has been stale since the WSD-S4 freeze; (b) the export is current.
   - Evidence: the newest pipeline file is from 11-06 22:02Z, no workflow runs `export --to-files`, and the store holds 4,211 items against 4,098 in the files.
   - Survivor: (a), p 0.9 MEASURED. Off-VM reads fall back to the files silently (`work_read._store_for_read` returns None).
3. **Is learning alive?**
   - Hypotheses: idle and correct, or rows recorded but never trained.
   - The registry did not move. The discriminating read is the labelled-rows chain, which belongs to `/ml-review`.
   - p 0.5 each.
4. **Reconciler closes on paper?**
   - alpaca_paper TLT 6880 is the only Alpaca/IB close in the window that is neither TP nor SL.
   - INFERRED p 0.6 that it was the TLT second bracket, which PAPER-MECHANICS-20261104 owns.

**Correlation.** Three things today are one observability failure: the token rotation, the relay's 4 KB-per-path cut, and the Actions queue. Together they blinded H4, H5 and H13. Existing rows own it.

**Hunt.** I looked at a surface that reports ok while nothing could falsify it: the register readers after the freeze. That found C2. Reading the relay output also found C5.

## 3. Decisions (ranked by money at risk)

| call | decision | tier | check | ending · due_by |
|---|---|---|---|---|
| C1 live disk refilling | Run `prune-db-backups` (dry-run first) on the two window backups (4.9 GB); make the prop-report helpers prune their own backup; cap syslog | 2 | `free_pct` ≥ 20 on 11-18 | HEALTH-20261111-LIVE-DISK-REGROWTH · 11-15 |
| C2 off-VM register reads are stale | Read the store off-VM, or print the export's age | 1 | `--stats` equals the store or names the age | HEALTH-20261111-EXPORT-READS-STALE · 11-18 |
| C3 research SLOs at 9 a day | Existing rows; re-scope proposal on the stalled one | 1 | breaches ≤ 6 on 11-18 | AUD-20261111-RESEARCH-OPS-NO-RECORD · 11-13; AUD-20261019-RESEARCH-SLO-RED |
| C4 trainer trains nothing | `/ml-review` answers it | 1 | registry > 98 or "no new labels" shown | HEALTH-20261111-TRAINER-NO-NEW-MODELS · 11-18 |
| C5 IB paper account id in public relay replies | Mask it like `gateway-forensics` does | 1 | 0 unmasked ids | HEALTH-20261111-IB-ACCTID-PUBLIC · 11-18 |
| C6 leverage pre-flight | Existing row (stalled) | 2 | 0 "symbol invalid" lines per boot | HEALTH-20261104-LEVERAGE-PREFLIGHT-EQUITY · 11-13 |
| C7 paper reconciler closes | Note on the existing row | 2 | `exchange_flat_reconciled` = 0 | PAPER-MECHANICS-20261104 · its due_by |

**Closed this run:** HEALTH-20261104-MGC-JOURNAL-DRIFT, -TRAINER-DISK and -OBS-GAPS (done); HEALTH-20261028-PIPELINE-ROUTING-OWNER (dropped, superseded); PI-20261017-VMDGITZI-0002 and PI-20261017-VSMHZYHF-0001 (dropped, superseded by C1).

**Premortem, C1.** The risk is a retention change that deletes a store of record, such as a journal backup an operator wanted. Name the files first, and cap at the writer rather than with a sweep.

## 4. Not done

- `system_invariants.py`, the audit tail, the ssh sweep and `check_db_integrity.py`: blocked by relay truncation and the diag 401.
- The trainer relay (#24923) had not returned. H11 and H12 use the `/api/bot/ml/status` mirror instead.
- The open-set walk (§ 3c) was cut. The gate set is computed from a stale export (C2).
- The ping system-action was not opened, to spare the Actions queue (80 queued). The manager is reported to directly instead.
- H16 soak grading was not done.
