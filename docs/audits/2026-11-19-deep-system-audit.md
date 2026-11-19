# Deep system audit: resources, OCI free tier, structure, efficiency (2026-11-19)

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane AM-OPS-3 (GENERAL), week plan [`week-plan-2026-11-19.md`](../plans/week-plan-2026-11-19.md) § 4.
>
> **Gates this adds or changes:** none. This is a measured record and a ranked proposal. It authorizes nothing. Every live-infra move below is Tier 2 and waits for the operator (week plan § 5, M2: *"all OCI usage must stay inside the Always Free tier"*).

**Status: DRAFT 2 in progress** (Draft 1 2026-11-18 ~23:00Z by AM-OPS-3; Draft 2 by AM-OPS-4 from 2026-11-18 23:55Z). Sections marked *open* are still being measured; later drafts replace them in place.

## 0. Top line

1. **OCI is above the Always Free compute pool, measured.** Three `VM.Standard.A1.Flex` instances, all RUNNING, total **4 OCPU / 24 GB**. The Always Free pool is **1,500 OCPU-h + 9,000 GB-h a month = 2 OCPU / 12 GB** for every tenancy (docs.oracle.com *Always Free Resources*, re-read 2026-11-18). On Oracle's published Ampere rate card ($0.01 per OCPU-h, $0.0015 per GB-h), the overage is **~$26.20 a month** (720 h; $28.04 in a 31-day month). Whether Oracle actually bills it can only be seen on the billing page (§ 1.4 gives the steps).
2. **OCI storage sits exactly at its free limits.** Boot volumes total **200 / 200 GB** (0 headroom). The journal backup bucket holds **10.62 GB**, which equals the 10 GB Standard tier free on a paid account, and it grows with the journal.
3. **The live trader is CPU-bound and its tick is near its budget.** The live VM's daily CPU p95 is 99.8–100% every full day from 11-09 to 11-17 (2 OCPU). The trader's mean tick is **55.3 s against a 60 s interval** (max 98 s). Most of that is the main tick waiting for the reconciliation loop's journal lock (filed: `LIVE-TICK-NEAR-BUDGET`). This constrains every consolidation option: nothing moves onto the live VM until it is fixed.
4. **Recommended path back inside the free tier (operator decision, Tier 2):** fix the tick first. Then run the IB gateway as a container on the live VM and move training and research to GitHub-hosted runners (the repo is public, so standard runner minutes are free) and Kaggle. That retires the trainer and gateway VMs and lands at 2 OCPU / 12 GB and ≤ 200 GB. § 5 gives the plan and its risks.

## 1. OCI Always Free compliance (c2), the top finding class

### 1.1 Compute, MEASURED

Source: `oci-inventory` issue #26981 (run 44411483182) and `oci-capacity-report` issue #26980, both read-only, 2026-11-18 ~22:40Z, region eu-paris-1.

| Instance | Shape | OCPU | GB | State | Role |
|---|---|---|---|---|---|
| ict-bot-arm | VM.Standard.A1.Flex | 2 | 12 | RUNNING | live trader, web API, Caddy |
| ict-trainer-vm | VM.Standard.A1.Flex | 1 | 6 | RUNNING | training, research data, console connector |
| ict-ib-gateway | VM.Standard.A1.Flex | 1 | 6 | RUNNING | IB Gateway (Docker) |
| **Total** | | **4** | **24** | | Always Free pool: **2 / 12** |

- Monthly use is 2,880 OCPU-h and 17,280 GB-h (720 h). That is **1,380 OCPU-h and 8,280 GB-h over the pool**.
- Cost basis: Oracle's Arm compute page gives $0.01 per OCPU-h and $0.0015 per GB-h, so $13.80 + $12.42 = **$26.22 a month**. One older Oracle pricing page still says the first 3,000 OCPU-h and 18,000 GB-h are free; the Always Free docs page says 1,500 / 9,000. The docs page is the current, specific statement; the repo's `oci_inventory.py` already records the halving on 2026-06-15.
- The Limits API allows 250 A1 cores and 1,666 GB in this AD (`comms/cloud/oci_limits.json`, 2026-11-18 16:00Z). **Nothing in the tenancy stops billable growth**, so the free-tier rule has to be enforced by us. The one tool with a guard, `provision_training_vm.py`, still treated 4 OCPU as free. Fixed in PR #26984.

### 1.2 Storage, MEASURED (#26980)

| Resource | Use | Free limit | Headroom |
|---|---|---|---|
| Boot volumes: trainer 100 + live 53 + gateway 47 GB | 200 GB | 200 GB (boot + block combined) | **0 GB** |
| Block volumes | 0 | (in the 200 above) | — |
| Volume + boot-volume backups | 2 | 5 | 3 |
| Object storage, bucket `ict-journal-backups` | 10.62 GB (9.89 GiB), 76 objects | 20 GB combined (Always-Free-only account) **or** 10 GB Standard + 10 GB Infrequent Access + 10 GB Archive (paid account) | ~0 on a paid account |
| Outbound data | not measured | 10 TB / month | *open*: OCI Monitoring network p95 is recorded raw, unit unverified (`compute_util.py` header) |
| Load balancers, NLB, reserved IPs | none found by the inventory | 1 flexible LB + 1 NLB | — |

- **Backup bucket retention** is 30 daily + 12 weekly copies per DB (`scripts/ops/journal_offvm_backup.py`). At steady state that is ~42 objects per DB, and each object grows with `trade_journal.db` (2.9 GB uncompressed on the trainer mirror). **Proposal (Tier 2, reversible):** write the weekly copies to the **Archive** tier, which has its own 10 GB free on a paid account. Daily restores stay instant from Standard; a weekly restore from Archive takes ~1 h. Alternative: cut daily retention from 30 to 14 days.
- **Boot volumes at 200 / 200 GB**: any new VM, block volume or boot-volume grow is billable. The trainer's 100 GB boot volume is 84% full (82 / 97 GB; `etf_history` alone is 23 GB).

### 1.3 Reclaim risk (Oracle's idle rule)

`comms/cloud/compute_reclaim_state.json` (2026-11-18): every host's max daily CPU p95 over 7 days is well above 20% (gateway 63.5%, live 100%, trainer 100%). **No host meets the idle definition.** There is no reclaim exposure today.

### 1.4 Operator check on the OCI billing page (exact steps)

1. OCI Console, top-left menu: **Billing & Cost Management → Cost Analysis**.
2. Set the date range to the **last 3 months**, group by **Service**, and filter **Service = Compute**. A non-zero line for **"Compute – Ampere A1"** (or "Virtual Machine Standard - A1") confirms the overage is billed. Repeat with **Service = Object Storage** and **Block Storage**.
3. **Billing & Cost Management → Subscriptions** (or **Upgrade and Manage Payment**) shows whether the tenancy is **Pay As You Go** or **Free Tier**. A PAYG tenancy is charged for usage above the Always Free amounts.
4. Optional safety net: **Billing & Cost Management → Budgets → Create Budget**, compartment = root, monthly amount **$1**, with an alert to your email at 100%. This changes nothing that runs; it only emails you if any charge appears. Creating it needs your console login.

## 2. Efficiency (c): measured use per resource

| Resource | Measurement | Source | Read |
|---|---|---|---|
| Live VM CPU | daily p95 99.8–100% on 2 OCPU, every full day 11-09..11-17 | `comms/cloud/compute_util_ledger.jsonl` (OCI Monitoring) | saturated ≥ 5% of each day |
| Live VM CPU by unit | ONE 30 s window ending ~23:58Z 11-18 (n = 1 window, taken at the top of the hour, so biased towards the hourly jobs): whole machine **99.9% of 2 CPUs**, PSI some avg10 61.8%. Per unit (% of one CPU): `ict-trader-live` **71.4**, `ict-hourly-snapshot` **34.3**, `ict-work-digest` **32.2**, `ict-web-api` 19.4, `ict-prop-feed@tradeify_1` (headless Chromium) 19.2, caddy 0.6. 8 trader restarts in the previous 24 h | `vm-cpu-sample` #27025 (asked for a 60 s window; the action ran 30 s) | two hourly timers add ~0.66 CPU on the hour on top of the trader. **Cheap lever (Tier 2):** move `ict-hourly-snapshot` and `ict-work-digest` off :00 and off each other, or off the live VM (the work digest reads the work store, so it does not need the trader host). **Off-the-hour baseline, MEASURED** (`vm-cpu-sample` #27035, one 30 s window ~00:10Z 11-19): whole machine **34.9% of 2 CPUs**, PSI some avg10 1.4%; trader 51.6, web-api 10.4, nothing else above 0.3. So the daily p95 of ~100% is **burst load** (hourly timers on the hour, the prop-feed headless Chromium, trader restarts), not baseline. Implication for § 5: the live VM has ~1.3 CPU free off the bursts; de-bursting the schedule is the cheapest headroom. Population caveat: 2 windows (n = 2), more samples needed before a consolidation sizing |
| Live VM memory | daily p95 19–22% of 12 GB | same | ~9 GB spare |
| Live VM disk | 67–78% of 53 GB | same; `/api/diag/status` 68.1% at 22:12Z | |
| Live trader tick | mean 55.3 s, max 98.3 s vs `TICK_INTERVAL_SECONDS=60`; `journal_sync.wait` mean 23.8 s; reconcile hold mean 37.0 s | `/api/diag/tick_cost`, 136 ticks since 20:10:57Z | **row `LIVE-TICK-NEAR-BUDGET`** |
| Trainer CPU | daily p95 100% on 1 OCPU; ~3.5 CPU-h/day (~15% mean); `ict-trainer.service` 56 min 48 s CPU on 11-18 | ledger; `comms/cloud/trainer_cpu_by_unit_2026-11-06.json`; trainer-diag #26982 | bursty, mostly idle |
| Trainer memory | daily p95 33–85% of 6 GB | ledger | bursty |
| Trainer disk | 82 / 97 GB (84%): `data` 27 GB (etf_history 23 GB, journal mirror 2.9 GB), `datasets-out` 12 GB, `ml` 9.8 GB | #26982 | |
| Gateway | CPU p95 44–64% of 1 OCPU; memory p95 20–25% of 6 GB (~1.2–1.5 GB); disk 20–24% of 47 GB | ledger | |
| GitHub Actions | public repo, so standard-runner minutes are free; **404 runs queued** at 22:50Z. Re-read 2026-11-18 23:41Z: **423 queued**, of which 358 were created 2026-11-11 (sampled: 0 jobs each), 23 on 2026-05-15, 13 in Sep/Oct, and 23 on 11-18; 21 in progress | Actions API | concurrency, not minutes, is the limit; the 11-11 block is ghosts (0 jobs) that clutter the queue but hold no runner |
| Research dispatcher | cycles 19–21 min apart vs a 3–10 min target; the `rearm` job waited 6–13 min for a runner; its 1800 s idle sleep exceeded its 20-min timeout | Actions API | fixed in PR #26988 |
| Kaggle GPU | **29.84 of 30 h left this week (0.16 h used)**, refresh 2026-11-21 00:00Z | `comms/research/utilization/44416449619.json` (dispatcher, 2026-11-18 23:02Z) | **almost entirely unused**: ~30 free GPU-h/week |
| Research backends | github_runner capacity 4, all busy, **41 due waiting**; kaggle_cpu capacity 1, busy, **41 waiting**; trainer capacity 1, 5 waiting; kaggle (GPU) 0 due; runpod 0 due, $0 of $10 month-to-date | same record | the CPU lanes are the bottleneck while the GPU lane is idle. Lever: route GPU-eligible units to Kaggle GPU and check whether Kaggle allows more than 1 concurrent CPU session (*open*: verify the account's concurrent-session limit) |
| Hugging Face | account `bentzbk`; manager decision M6: no paid GPU | — | *open* |
| RunPod | $10 / month budget (operator-approved 2026-07-02), ledger `comms/gpu_spend_ledger.json` | | the only paid compute besides a possible OCI overage |
| Timers | trainer: 27 timers (11 ict-*), 0 failed units; live: 30 timers (`/api/diag/timers`, 30 read, 0 could_not_look) | #26982, diag | *open*: per-timer CPU on live |

## 3. Bugs found during this audit (a)

| # | Finding | State |
|---|---|---|
| B1 | Lake extender wrote `YYYY-MM-DD 00:00:00-07-07` into 13 date-only trainer files (pandas reads NaT) | fixed in #26978; trainer repaired and read back (#26972); no reader in the window (#26985) |
| B2 | `etf_history` backfill skipped series whose history starts years after `--start` (QQQ, TLT, IWM, SLV, IEF have only 2026-10/11 1m data) | fixed: #26990 merged 2026-11-18 23:23Z |
| B3 | Dispatcher re-arm waits for a second runner; idle heartbeat killed by its own timeout | fixed: #26988 merged 22:39Z. Re-read: dispatch gaps since were 7, 13, 20 and 6 min (4 cycles, 22:57–23:44Z) against a 3–10 min target, with runner queueing in the gaps; observation continues on PI-20261118-JFWRQYOV-0001 |
| B4 | `provision_training_vm.py` treated 4 OCPU as free | fixed: #26984 merged 22:33Z |
| B5 | Live tick near budget (journal lock held 37 s of every 60 s) | row `LIVE-TICK-NEAR-BUDGET` (Tier 2) |
| B6 | IB gross exposure ~1.5× equity from tight-stop futures sizing; the 1.5× cap then bricks the account | row `IB-GROSS-NO-CAP-FIX` (Tier 3, Stage-0 first) |
| B7 | `oci-inventory` posts tenancy and instance OCIDs on a public issue | *open*: identifiers, not secrets; propose redaction in the report step |
| B8 | Ghost runs: re-measured 23:41Z as **358 queued runs from 2026-11-11, sampled 0 jobs each** (plus 36 older), not 3 | *open*: a bulk cancel was refused by this session's tool classifier; routed to the manager |
| B9 | #26996 (IB open-trade cache prune) read `permId` off the `reqAllOpenOrders` response. The real ib_insync 0.9.86 response is `List[Trade]`, so every acknowledged leg was pruned on ib_paper and the naked sweep cancelled and re-armed 3 positions every ~6 min (23:29–23:47Z). A fresh-client read at ~23:44Z found **0** resting orders. Paper only | reverted by #27014 (deployed 23:49:29Z, first sweep covered=3 naked=0); re-land against the real response shape in #27023 (held); root cause on PI-20261117-LSFHBH4A-0006 |
| B10 | `/api/health` is a sync handler on the AnyIO threadpool shared with 67 sync diag routes, so one watchdog probe can queue past 10 s under CPU saturation (WEBAPI-WEDGE-RECURRING: 9 single failed probes in 68 h) | fix #27020 (held Tier 2) |

## 4. Free resources not yet used (d)

*Open: to be completed Thu.* First candidates, each with what it unlocks:

- **OCI Object Storage Infrequent Access + Archive tiers** (10 GB each, free on a paid account): the weekly journal backups and cold research data (`etf_history` history years) without touching the 200 GB boot limit. No sign-up; it is a bucket setting.
- **OCI Always Free Autonomous Database** (2 instances, 20 GB each): *assess only*. It could host the read-mostly trainer store off the VMs. No sign-up; console only.
- **Two AMD `VM.Standard.E2.1.Micro` instances** (1/8 OCPU, 1 GB each, free): too small for the IB Gateway (Java; measured ~1.2–1.5 GB in use), but enough for small always-on jobs (git-sync, freshness probes). They draw from the 200 GB boot total (~47 GB each), and that total is full.
- **Kaggle GPU, already signed up, ~99% unused** (MEASURED 2026-11-18 23:02Z: 29.84 of 30 h left this week). It unlocks GPU training for the ML lane's model-family work (the free-weights path, manager decision M6) and GPU-eligible research units, at $0. No sign-up; the lever is routing (`compute: gpu` units, `scripts/research/compute_router.py`). Currently 0 GPU units are due while 41 CPU units wait on each CPU lane.
- **GitHub-hosted runners**: already the research default; the constraint is concurrency (queue depth 404), so the real gain is moving work OFF the VMs, not adding runners.

## 5. Operator hypotheses (e), with numbers

### 5.1 "Move the IB gateway off its own VM" (now that the prop executors exist)

- **Fit:** the gateway uses ~1.2–1.5 GB RAM (p95 20–25% of 6 GB) and CPU p95 44–64% of 1 OCPU. The live VM has ~9 GB RAM spare but **no CPU headroom at p95**.
- **Free-tier effect:** retiring the gateway VM saves 1 OCPU / 6 GB and 47 GB of boot volume.
- **Risk:** the gateway was split off the live VM after the 2026-06-10 wedge cascade (OCI-STATE-CHECK 2026-10-13 rec. 7). Putting it back on a CPU-saturated trader host recreates that coupling.
- **Prerequisite:** `LIVE-TICK-NEAR-BUDGET` fixed and live CPU p95 measured below ~70%. Run the gateway as a container with a CPU quota (e.g. `--cpus=0.5`) so it cannot starve the trader.
- **Verdict:** feasible only after the tick fix. Tier 2.

### 5.2 "Move training and research off the trainer VM to Kaggle/HF" (VMs serve live trading only)

- **Fit:** the trainer averages ~3.5 CPU-h a day (~15% of 1 OCPU) in bursts. Research already defaults to runners and Kaggle (`research_compute.yaml`; manager decision M5).
- **What still lives only on the trainer:**
  - the nightly `ict-trainer` cycle (~57 CPU-min);
  - the candle and data refresh owners (`ict-candle-refresh`, the lake, `etf_history` sync target);
  - the forecast producer (every 15 min);
  - the publish mirror to the live VM (every 2 min);
  - the console connector (Caddy);
  - order-flow capture;
  - the journal mirror.
- **Blocker:** the runner's private-dataset 404 (week plan § 5, D11 / M5). Until it is fixed, runner-first training cannot read the published training data.
- **Free-tier effect:** retiring the trainer saves 1 OCPU / 6 GB and 100 GB of boot volume.
- **Risk:** the always-on producers (forecast every 15 min, publish every 2 min, order-flow capture) would need a home. The live VM has the RAM but not the CPU.
- **Verdict:** move the batch work (training, research, data refresh) to runners and Kaggle first. Move the always-on producers only after the tick fix frees live CPU. Tier 2.

### 5.3 Ranked migration plan *(draft)*

1. **Now, Tier 1, no infra change:** the fixes in § 3 (B2–B4 PRs), redact OCIDs (B7), and clear the ghost runs (B8).
2. **Tier 2, risk-free, reversible:** the Archive tier for weekly journal backups; an operator-created $1 billing budget alert (§ 1.4).
3. **Tier 2:** `LIVE-TICK-NEAR-BUDGET` (narrow the journal lock to DB writes). Re-measure live CPU p95.
4. **Tier 2, operator OK:** fix the runner dataset 404, then move the nightly training cycle and data refresh to runners and Kaggle.
5. **Tier 2, operator OK:** move the gateway into a CPU-capped container on the live VM, then retire the gateway VM. Free-tier result after steps 4–5: 2 OCPU / 12 GB if the trainer is also retired; otherwise 3 / 18, still billable.
6. **Tier 2, operator OK:** move the always-on producers to the live VM, then retire the trainer. Result: 2 / 12 and 53 GB boot. **Inside Always Free.**

#### 5.4 Per step: pre-state, rollback, acceptance (Draft 2)

| Step | Measured pre-state | Rollback | Acceptance check (population stated) |
|---|---|---|---|
| 1 Tier-1 fixes | B2 #26990, B3 #26988, B4 #26984 open/merged as listed in § 3; B8 358 ghost runs | `git revert` per PR | each PR's own test; B8: queued-runs count older than 24 h = 0 on the Actions API |
| 2a Archive tier for weekly journal backups | bucket 10.62 GB Standard, 76 objects (#26980) | lifecycle rule removed; objects restore from Archive in ~1 h | Standard-tier bytes ≤ 10 GB on the next `oci-capacity-report`; one weekly object restored and its sha256 matched |
| 2b $1 budget alert | none | delete the budget | operator sees the budget listed; no runtime change |
| 3 LIVE-TICK-NEAR-BUDGET (#27013) | tick mean 55.3 s / `journal_sync.wait` 23.8 s (136 ticks, 20:10–22:30Z); 58.7 s / 19.7 s (12 ticks, 23:29–23:41Z, a churning process) | `git revert` + restart | ≥ 100 ticks on `/api/diag/tick_cost`: wait mean < 5 s, tick mean < 40 s; then live CPU p95 re-read from the OCI ledger over ≥ 3 full days |
| 4 Runner dataset 404, then training/refresh off the trainer | trainer ~3.5 CPU-h/day, 82/97 GB disk | re-enable the trainer timers (units stay installed until step 6) | 3 consecutive nightly cycles complete on runners/Kaggle with the same artifacts registered; trainer `ict-trainer.service` idle |
| 5 Gateway into a CPU-capped container on the live VM | gateway VM CPU p95 44–64% of 1 OCPU, RAM ~1.2–1.5 GB | restart the gateway VM (kept stopped, not terminated, until acceptance) | 7 days: IB reads `read_state=ok` ≥ 99% of sweeps; trader tick mean unchanged ± 5%; live CPU p95 < 90% |
| 6 Always-on producers to the live VM, retire the trainer | forecast every 15 min, publish every 2 min, order-flow capture, console connector | restart the trainer VM from its stopped state; boot volume kept 30 days | 7 days of each producer's freshness check green from the live VM; then the 2 OCPU / 12 GB / ≤ 200 GB total is read on the next `oci-inventory` |

**Order matters.** Steps 5 and 6 add load to the live VM, which is the host with no CPU headroom, so neither starts before step 3's acceptance holds. Each step is reversible until its VM is TERMINATED. Termination is the last act, and it needs the operator's OK.
