# Compute topology design: retire the trainer VM, relieve the live VM (2026-11-28)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current** (its measurements are dated in § 1 and § 2)
> Row `COMPUTE-TOPOLOGY-REVIEW`, phase 1 (a DESIGN doc; nothing in this lane changed any VM). Lane `INFRA-BUILD-20261128`, dispatched by Manager Session 2026-11-28b.
> Builds on, and does not repeat: [`COMPUTE-ARCH-REVIEW-2026-10-13.md`](COMPUTE-ARCH-REVIEW-2026-10-13.md), [`KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13.md`](KAGGLE-TRAINING-PIPELINE-DESIGN-2026-10-13.md) (§ 10 is the parity gate that already passed for one manifest class), [`COMPUTE-ALLOCATION-2026-11-03.md`](COMPUTE-ALLOCATION-2026-11-03.md) (GitHub-runner side).
> **Gates this adds or changes:** none. Every switch below is an operator-tiered act that already exists as a tier; this doc proposes the order, it grants nothing.

## 0. The answer in six lines

1. **The trainer VM can be retired, and it is now nearly idle**: load 0.01, 306 MB of 5.9 GB used, `ict-drift-retrain` ran **1** time in 7 days (167 in the October profile that justified keeping it). What still ties it down is not compute. It is **three always-on jobs and one single-writer registry** (§ 3).
2. **The live VM's problem is peaks, not average**: 24 h of completed-run journal CPU is about 68 % of its 2 OCPU (§ 2), but the OCI daily p95 is 98-100 % on every one of the last 7 days. About **a fifth of the timer CPU is three cheap-to-fix jobs** (§ 5, quick wins).
3. **Recommended target** (§ 4): live resized 2 → 3 OCPU / 12 → 18 GB; trainer retired; **IB gateway VM kept** and made the home of the small always-on non-compute jobs; training, builds and research on GitHub runners / Kaggle CPU / Kaggle GPU. Merging the IB gateway INTO the live VM is not recommended (§ 6).
4. **Money to check first**: the OCI Limits API shows 250 cores in the tenancy, not the Always-Free 4 (read 2026-10-13, `comms/cloud/oci_limits.json`). If the tenancy is upgraded, **+1 OCPU on live can be bought now** without retiring anything. Billing is unverified (§ 8, decision D1).
5. **Usage to execute**: about **30 lane-hours** across 6 lanes, most of it waiting on runs (§ 9). Prep (P0) is about 45 % of that and touches no production path.
6. **Recommendation** (§ 10): do the quick wins and P0 prep **before** the 12-02 reset; start the dual-run, cutover and resize **right after** it.

## 1. Measured inventory (read 2026-11-28 09:30-09:40Z)

**Populations.** Live and gateway: OCI Monitoring daily p95 from `comms/cloud/compute_util_ledger.jsonl` (7 complete days 2026-11-21..27, written by workflow `compute-util-telemetry`), plus the live diag routes `/api/diag/services`, `/timers`, `/journalctl` read directly. Trainer: `trainer-vm-diag` issues #29729 and #29736 (read-only commands). The October table in `docs/reference/vm-topology.md` is stale; **this table replaces it** for planning.

| host | shape | CPU p95 (max daily, 7 d) | memory p95 | disk | note |
|---|---|---|---|---|---|
| `ict-bot-arm` (live) | A1 2 OCPU / 12 GB | **99.7 %** (88-100 % each day) | 21.6 % (max 26 %) | 73 % of 45 GB | load1 2.0-4.6 in the three ssh samples |
| `ict-trainer-vm` | A1 1 OCPU / 6 GB | **100 %** every day | 50-82 % (max 95 %) | 74 % of 97 GB (72 GB used) | at the 09:34Z read: load 0.01, 306 MB used, 7.9 GB free swap |
| `ict-ib-gateway` | A1 1 OCPU / 6 GB | **99 %** (76-99 %) | 33 % | 29 % | load1 0.14-1.15 in the ssh samples |

⚠️ **How to read the CPU column.** It is the p95 of one-minute OCI samples within a day, so 98-100 % means "at least 72 minutes of the day at the ceiling", not "busy all day". The trainer's load of 0.01 against a p95 of 100 % says its day is a few saturated bursts (the 00:29Z cycle, the 08:00Z catch-up, the 6-hourly lifecycle, forecast every 15 min). The gateway's 99 % against load 0.14-1.15 is unexplained here (candidates: the 06:05Z container reset, the watchdog); **it is not evidence that the gateway is busy**. Network is `could_not_look` for all three (the unit conversion is unverified), so no network claim is made.

Tenancy: Limits API read 2026-10-13: 250 cores / 1,666 GB limit, 4 / 24 used. **Not re-read today**; the workflow refreshes it daily, so D1 should start from the current file.

## 2. The live VM, per unit (24 h of the journal, 2026-11-27 09:40Z to 2026-11-28 09:40Z)

**Method.** `/api/diag/journalctl?unit=…&grep=Consumed`, summing systemd's `Consumed … CPU time` line that each completed run logs. **Completed runs only**: a unit still running (the current trader and web-api process) is not yet in the journal, so the services row is an undercount. Capacity is 2 OCPU × 86,400 s = 172,800 CPU-s.

| unit | completed runs | CPU-s | per run | share of 2 OCPU |
|---|---|---|---|---|
| `ict-trader-live` (12 restarts, i.e. auto-deploys) | 12 | 66,292 | n/a | 38.4 % |
| `ict-web-api` | 19 | 26,379 | n/a | 15.3 % |
| `ict-git-sync` (timer, ~5 min) | 269 | 7,373 | 27 s | 4.3 % |
| `ict-prop-executor@tradeify_1` (5 min) | 286 | 4,705 | 16 s | 2.7 % |
| `ict-work-digest` (5 min) | 46 | 4,293 | 93 s | 2.5 % |
| `ict-prop-feed@tradeify_1` (5 min) | 287 | 3,701 | 13 s | 2.1 % |
| `ict-work-store-import` (5 min) | 287 | 933 | 3.3 s | 0.5 % |
| `ict-prop-executor@velotrade_1` (5 min) | 287 | 859 | 3 s | 0.5 % |
| `ict-ml-decision-shadow` (15 min) | 96 | 656 | 6.8 s | 0.4 % |
| `ict-exchange-fills-pull` (hourly) | 24 | 687 | 29 s | 0.4 % |
| `ict-hourly-snapshot`, `-db-integrity`, `-health-snapshot`, `-work-report`, insights ×2, funding/MES pulls, results-gate | 141 | 892 | n/a | 0.5 % |
| `ict-claude-bridge`, `-claude-decision-bot`, `ict-telegram-bot` | 50 | 176 | n/a | 0.1 % |
| **Total logged** | | **≈ 117,000** | | **≈ 68 %** |

Reading: (a) the trader and its API are 54 % of the box; (b) **the 5-minute timers add up to 12.2 % of the whole VM** (git-sync, prop feed/executor, work-digest, work-store-import); (c) **twelve trader restarts a day** are auto-deploys from `main` (`ict-git-sync`); each restart pays import warm-up and, because the merge rate is high, the trader spends part of every day cold. Not measured: the share of the trader's CPU that is per-tick work versus start-up (`/api/diag/tick_cost` has the hooks; am:OPS owns the bounded quick-wins read on the row and this section should be reconciled with it before the operator page).

`ict-prop-feed@velotrade_1` shows 0 in the table above because its journal does not print the `Consumed … CPU time` line (it does run: the journal shows it finishing at 09:51:07Z, per the manager's check). **The method undercounts any unit whose runs do not log that line, so the timer total is a lower bound**; the velotrade feed's CPU is unmeasured, not zero.

## 3. The trainer VM, per workload: what it does now and where each piece goes

Population: `deploy/trainer/*.service` + `*.timer`, `trainer-vm-diag` #29729 (units, timers, sizes), #29736 (CPU per unit, filled in § 3.1).

| workload | cadence | what it touches | destination | transfer path / blocker |
|---|---|---|---|---|
| `ict-trainer` daily cycle + `ict-trainer-catchup` | 00:29Z, 08:00Z | rebuilds datasets, trains ~67 manifests, writes the registry | **GitHub runner** (CPU manifests) and **Kaggle CPU** (published-data units) | 63 of 73 manifests are market-data-only (KAGGLE design § 0). **Parity gate passed for ONE class** (LightGBM, `eth-regime-1h-lgbm-v1`, bit-identical, 2026-10-16). HMM, RegimeClassifier, regression and PerStrategyWinRate classes have no parity unit yet. The 10 manifests that read OUR journal stay on a host that can hold the journal until a sanitising export exists |
| `ict-trainer-lifecycle` | 03/09/15/21:20Z | per-model retrain / retest plans | GitHub runner | same registry write path as above |
| dataset builds (inside the cycle) | nightly | public **Bybit** klines → `market_raw` → `market_features` | runner, with a feed caveat | ⚠️ GitHub-hosted runners are **geoblocked by Bybit**; Binance-vision is a different feed, so a model trained on it is not comparable without a check (KAGGLE design § 2). Either the fetch stays on a small always-on EU host (the gateway VM, same Paris region as the trainer) and publishes to the dataset, or a feed-equivalence check is passed first. **This is the main technical risk (R1).** |
| `ict-trainer-forecast` | every 15 min | Chronos TSFM, writes `fc_*` side-stream the fc-pcv regime heads read | **no clean destination** | needs torch and the latest bars every 15 min. Kaggle kernels are push-to-run, not a 15-minute service, and the GPU quota is 30 h/week. Options: CPU Chronos on a GitHub schedule (cron jitter), or keep on the freed OCPU of a small host. **Open question: which live decisions read `fc_*` today** (checked: none in this lane). If only research heads read it, it can pause. |
| `ict-trainer-publish` (mirror) | every 2 min | rsyncs `trainer_status.json` and `models/<id>.json` to the live VM | **removed**: replaced by a pull | the live shadow factory and the training-center dashboard read this mirror (`ml/shadow/factory.py`). A puller on the live side (a timer that fetches the registry export) replaces the push |
| **registry** (`ml/registry-store`, 20 MB, 96 entries) | append-only, **single writer** | the shadow factory loads from it | **a private HF dataset repo or a git path**, single writer = the cutover job | the one-writer rule is the constraint (KAGGLE design § 4, § 6). Drain path exists (`ict-offload-drain`, `ml/offload-inbox`), shipped UNARMED |
| `datasets-out` 9.5 GB, `data` 28 GB, 20 MB registry | storage | training inputs | HF private dataset + the existing `metis-market-data` Kaggle dataset | one-time copy; archive before shutdown |
| `ict-orderflow-capture` | always on (websocket) | BTCUSDT microstructure, forward-only since 2026-06-04 | **gateway VM** (always-on, light) | **a gap is permanent data loss**: move with an overlap of one day, never a stop-then-start |
| `ict-promotion-readiness`, `ict-candle-refresh`, `ict-pm-snapshot` | daily / 6-hourly | read the journal copy and lake; small | GitHub schedule or the gateway VM | needs the read-only journal copy (today pulled by `sync_trainer_data.sh`) |
| `ict-keeper-dispatch`, `ict-ltr-wake-dispatch` | hourly, 15 min | dispatch GitHub workflows (the schedule floor) | the gateway VM, or a GitHub-side keeper | holds a GitHub token; moving it is a secret placement the operator originates |
| `jta-console-connector` + caddy (console ingress) | always on | read-only MCP, Google sign-in | live VM (caddy already there) or the gateway VM | public ingress needs a DNS/Caddy change (Tier-2) |
| `trainer-vm-diag` relay | on demand | arbitrary read bash | **disappears** | sessions lose "run any read on the trainer"; replaced by workflow-level reads of the artifacts |

### 3.1 Trainer activity by unit (7 days)

Population: `journalctl --since '7 days ago'` run counts per unit, `trainer-vm-diag` #29729 (09:34Z). **CPU-hours per unit: NOT MEASURED** (the first command's `Consumed` pattern missed decimal values; the corrected read is issue #29736, which sat in the runner queue for over 15 minutes at the time this was written; if it has returned, its table supersedes this one).

| unit | runs in 7 days | October profile (runs / 7 d) |
|---|---|---|
| `ict-trainer-publish` (2-min mirror) | 3,620 | 4,704 |
| `ict-trainer-forecast` (15 min) | 529 | 672 |
| `ict-trainer-lifecycle` (6-hourly) | 22 | n/a |
| `ict-trainer`, `-catchup`, `ict-promotion-readiness`, `ict-candle-refresh` (daily) | 6 each | 7 |
| **`ict-drift-retrain`** | **1** | **167 (63.7 % of the trainer's service CPU)** |
| `ict-offload-drain`, `ict-pm-snapshot`, `ict-orderflow-capture` | 0 logged completed runs (orderflow is a long-running service, up now) | n/a |

What the counts say: the October profile's biggest consumer, drift retraining, has effectively stopped (1 run vs 167), which is why the host is at load 0.01 between the daily bursts. The remaining recurring load is the daily cycle, catch-up and lifecycle (the part that moves to runners) and the two cheap high-frequency units (forecast, mirror publish).

## 4. Target topology (recommended)

```
live  ict-bot-arm   3 OCPU / 18 GB   trader, web-api, caddy, bots, order-path timers (after the § 5 cuts), registry PULL timer
gate  ict-ib-gateway 1 OCPU /  6 GB   IB gateway container + orderflow capture + keeper/dispatch + (maybe) console connector
trainer                                RETIRED (stopped 14 days, then terminated)
compute                                GitHub runners: CPU training, dataset builds, research units
                                       Kaggle CPU: published-data units (free, no internet)
                                       Kaggle GPU: TSFM / TCN heads (30 h/week)
                                       HF private dataset repo: registry export + archived datasets
```

Why this and not the alternatives: the live VM is the only host whose CPU p95 is a trading risk (a starved tick is a late order); it gets the freed OCPU. The gateway VM stays because (§ 6) its job is isolation, and its 4 GB of spare memory fits the small always-on jobs. Free OCPU pool arithmetic: 2 + 1 + 1 = 4 today; after: 3 + 1 = 4. **The pool stays full, so the resize needs the trainer gone first unless D1 says paid is fine.**

## 5. Switches, each with risk, rollback and tier

| # | switch | risk | rollback | tier |
|---|---|---|---|---|
| S0 | **Quick wins on live** (all Tier-1 repo changes, no VM edit): (a) `ict-git-sync` fetches only when `ls-remote` shows a new SHA (27 s CPU per run today, 269 runs: 4.3 % of the box); (b) prop feed/executor become one long-lived process per account, or share a warm interpreter (16 s + 13 s per 5-minute run: 4.8 %); (c) `work-digest` 93 s per run to 15-minute cadence (2.5 % → 0.8 %); (d) stagger the 5-minute timers so they do not all start on the same second as the :03/:18/:33/:48 shadow run. **ESTIMATE, not measured: 10-12 % of the 2 OCPU box (about 19,000 CPU-s a day) and a lower p95.** | low; (b) is on the prop order path, so it is Tier-2 and needs its own review | revert the unit/script | (a),(c),(d) Tier-1 or Tier-2 timer edit (the unit files are `deploy/`, a Tier-2 deploy); (b) Tier-2 |
| S1 | **Parity units for the remaining manifest classes** (HMM, RegimeClassifier, regression, PerStrategyWinRate) on Kaggle CPU/runner, same rule as § 10 of the KAGGLE doc | none to production | n/a | Tier-1 |
| S2 | **Registry export + live-side puller** with a stale-guard (a stale registry is surfaced, never silently used) | medium: the shadow factory read path | keep the push mirror running during dual-run; revert the puller | Tier-2 |
| S3 | **Off-trainer dataset build + publish** with a freshness gate (`last_ts` older than 36 h refuses) | medium: feed equivalence (R1) | the trainer build keeps running until cutover | Tier-1 build, Tier-2 to schedule |
| S4 | **Dual-run N ≥ 5 nights**: the runner trains the same manifests; the trainer stays primary | low | stop the runner job | Tier-1 |
| S5 | **Cutover, one timer at a time** (cycle, catch-up, lifecycle), each only after the runner's artifact for the night passed the parity tolerance and was drained | the point of no gap: a missed night | re-enable the trainer timer (it is still there) | Tier-2 each, one operator OK covering the series |
| S6 | **Move the always-ons** (orderflow with one-day overlap, dispatchers, connector) | medium for orderflow (permanent gap if botched), low otherwise | restart on the trainer (still up until S7) | Tier-2; the token move is operator-originated |
| S7 | **Stop the trainer VM, archive datasets-out/data/registry, terminate after 14 days** | low if S5-S6 verified | start the stopped VM (the boot volume is kept) | Tier-2 (destructive step is the terminate: operator) |
| S8 | **Resize the live VM 2 → 3 OCPU / 12 → 18 GB** (A1.Flex in-place; needs a reboot, so the trader and web-api are down for the reboot, minutes, with venue-side brackets standing) | medium: the only step that interrupts the order path | resize back (same operation) | Tier-2, one operator window, between bars, never during a funding or session boundary |

## 6. The IB gateway VM: consolidate it? **Recommend no (for now)**

What it is: one A1 VM (1 OCPU / 6 GB) hosting a Docker IB Gateway (`ghcr.io/gnzsnz/ib-gateway`) for `ib_paper` (11 rostered legs on MES/MGC/MHG; `ib_live` is dry-run with no strategies). It exists because the 2026-06-10 wedge cascade was a heavy Java/Xvfb process sharing a 1 GB box with the trader (`docs/reference/vm-topology.md`).

- **Into the live VM**: the live box has 9.4 GB of spare memory today, so memory is not the old failure. **CPU is**: the live VM is at p95 99.7 %, and a Java gateway restart (daily 06:05Z reset, watchdog restarts) is a burst. It would only be safe after S0 + S8 and with a container `CPUQuota`/`MemoryMax`. It saves 1 OCPU / 6 GB, which is exactly what the pool needs for a 4 OCPU live VM, so it is the **second wave** option, not the first. It also needs `config/accounts.yaml::ib_paper.ib_host` to change, a Tier-3 file this lane may not edit.
- **Into the trainer VM, or the trainer's role into it**: the trainer VM is going away, so the useful merge is the opposite one: **the small trainer jobs move onto the gateway VM** (§ 4). Cost: a second reason for that VM to be up, so its reboot windows now matter to orderflow capture.
- **With prop tooling**: prop feed/executor are order-path, 5-minute, and want low latency to the live DB; they stay with the trader.

## 7. Migration order with no missed daily production retrain

"Production retrain" here means the 00:29Z cycle and the 08:00Z catch-up, which refresh the registry the live shadow factory reads.

1. **P0 (any time, Tier-1, no production change)**: S0 quick wins, S1 parity units, S3 dataset build + freshness gate, the registry export format. Nothing is switched off.
2. **P1 (dual-run, ≥ 5 consecutive nights)**: the runner trains the same manifests on the same dataset hash; the trainer remains the only writer to the live-readable registry. Pass rule per class: the KAGGLE doc's parity rule (same input hash, counts equal, scores within 0.01, ≥ 0.99 agreement).
3. **P2 (cutover per timer)**: the cycle first, then catch-up, then lifecycle. Each cut happens the morning after a night in which the runner's output passed and was ingested through the drain as `candidate`. **The trainer timers stay installed (disabled, not deleted) until S7**, so the rollback is one `systemctl enable --now`.
4. **P3**: S2 puller armed; S6 always-ons moved (orderflow overlap day).
5. **P4**: S7 stop, 14-day hold, S8 resize in one operator window.

At no point is there a night with zero trainers: until step 3 completes the trainer runs; from then the runner has run ≥ 5 passing nights.

## 8. Decisions for the operator

**Decided 2026-11-28 ~10:00Z (verbatim, relayed by the manager):** "Prep now, cutover after reset (Recommended)" (§ 10); "Stay free tier (Recommended)" (D1: no paid OCPU, so S8 waits for the trainer retirement); "Keep Bybit, from an always-on EU host (Recommended)" (D3). D2 and D4 remain open. The list below is the original ask.

- **D1. Is the tenancy upgraded, and is paying for +1 OCPU on live acceptable?** If yes, S8 does not wait for the trainer, and the whole retirement becomes optional rather than urgent. Evidence needed: the billing console (not readable from here). The Limits API says 250 cores are available.
- **D2. May the `fc_*` forecast producer pause if only research heads read it?** (Needs the consumer check in § 11.)
- **D3. The dataset-build feed**: keep fetching Bybit klines from an EU always-on host (recommended), or accept Binance-vision after a feed-equivalence unit.
- **D4. Order of the two waves**: S8 (live resize) right after the trainer is gone, then the gateway-into-live question reopens with a measured p95.

## 9. Usage estimate to execute (lane-hours, model)

ESTIMATE (not measured). Basis: comparable lanes on the checklist (`ML-DATA-OFF-TRAINER`, `KAGGLE-TRAIN-RUNNER-FIRST`, `COMPUTE-ALLOCATION-DESIGN`); most of the wall time is runs, not model tokens.

| lane | work | model | lane-hours |
|---|---|---|---|
| A | S0 quick wins on live (a, c, d Tier-1/2 timer edits) | Sonnet | 3 |
| B | S1 parity units for 4 manifest classes + analysis | Sonnet | 6 |
| C | S3 off-trainer dataset build/publish + freshness gate + feed check | Sonnet | 8 |
| D | S2 registry export, live puller, stale-guard (touches the shadow-factory read path) | **Opus** | 6 |
| E | S4-S6 dual-run watch, cutover, always-on moves | Opus | 5 |
| F | S7-S8 shutdown, archive, resize window | Opus | 3 |
| | **Total** | 3 Sonnet + 3 Opus lanes | **≈ 31** |

P0 (A, B, C) is ≈ 17 h (55 %); the rest needs the dual-run to have passed first.

## 10. Recommendation: before or after the 12-02 reset?

**Split it.** Do P0 now: it is Tier-1, mostly waits on runs, and S0 attacks the live VM's real constraint (peak CPU) at once. **Start P1 onward right after the reset**: a cutover in the reset week competes with the weekly planning for manager attention, and the dual-run needs five clean nights that cannot start until S1-S3 land. If D1 comes back "upgraded", do S8 first and demote the rest to a normal-priority roadmap item, because the trainer is idle and the live box is the only constrained host.

## 11. Not verified (stated, not hidden)

- Trainer per-unit CPU hours: not measured (§ 3.1 has run counts only); the October table (`docs/research/trainer-workload-2026-10-13.md`) is the older reference.
- Whether any LIVE decision reads `fc_*` (D2).
- The CPU of `ict-prop-feed@velotrade_1` (it runs but logs no `Consumed` line, so § 2 excludes it).
- The gateway's 99 % CPU p95 against a low load average.
- Billing and the current Limits API values (D1).
- Network utilisation: `could_not_look` on all hosts.
- All S0 savings and every lane-hour figure are ESTIMATES.
