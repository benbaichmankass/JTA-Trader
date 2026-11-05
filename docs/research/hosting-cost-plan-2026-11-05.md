# Hosting cost plan — can the whole system run on one service for $10–15/month?

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current** · row `HOSTING-COST-PLAN` · Tier 1, research only (nothing provisioned, nothing changed).
> **Gates this adds or changes:** none.

**Operator question (2026-11-05, verbatim):** *"how much would it cost to have the whole thing hosted on oracle or a different unified server? If we can streamline the whole thing into one central service for under 10-15 usd a month, that would be worth considering"*.

Tags: **M** = MEASURED (read from a file, API or page this session) · **E** = ESTIMATED (arithmetic on M inputs, or an assumption stated) · **U** = UNVERIFIED (could not look). Prices were read 2026-11-05 unless a date is given.

## 1. Answer

1. **A single unified server under $15 does not exist for this system, and moving the live trader is not worth it.** The three hosts are all CPU-saturated at p95 (§2.1). One 4-vCPU box holds the same 4 OCPU the pool already runs, puts the IB Gateway back beside the trader (the 2026-06-10 wedge cascade) and costs more than today's $0. **Recommend: do not unify.**
2. **Today's bill is probably $0 (E).** 4 OCPU / 24 GB all month (2,920 OCPU-h / 17,520 GB-h at 730 h) sits under Oracle's price-list free thresholds of 3,000 OCPU-h / 18,000 GB-h. The Always Free page quotes a smaller figure that would make it ≈ $27/month, so the operator's "no charges" report is the deciding evidence (§2.4). **U** until the billing console is read.
3. **Cheapest setup that lifts the three ceilings: $6.50–$15.50/month (E).** The GPU ceiling is not binding; the trainer needs +1 OCPU and re-balanced memory; the lake needs either a squash that gets it under 100 GB ($0) or HF PRO ($9).
4. **Operator decision needed:** approve a $6.50/month tenancy overage (one more A1 OCPU on the trainer) and, only if the squash lane does not get the lake under ~90 GB, HF PRO at $9/month. Both are real recurring spend on a card.

## 2. Inventory (what runs today)

### 2.1 The three OCI A1 VMs

Source: `comms/cloud/compute_util_ledger.jsonl` (31 days per host, 2026-10-05→2026-11-04, `read_state` measured for cpu/mem/disk), `comms/cloud/compute_spare.json`, `comms/cloud/expected_topology.json`.

| host | shape (M) | CPU daily p95, last 8 days (M) | memory p95 / max (M) | disk used % on 2026-11-04 (M) |
|---|---|---|---|---|
| `ict-bot-arm` (live trader) | 2 OCPU / 12 GB | 94–100 % | p95 14–16 %, daily max 20–33 % (≈ 2.4–4 GB) | 65 % (was 87 % on 11-02) |
| `ict-trainer-vm` | 1 OCPU / 6 GB | 100 % every day | p95 41–81 %, daily max 96–97 % | 81 % (was 52 % on 10-28) |
| `ict-ib-gateway` | 1 OCPU / 6 GB | 78–100 % | p95 22–25 %, max 25–29 % (≈ 1.7 GB) | **94 % (100 % on 11-02)** |

- Disk sizes in GB are **U**: the ledger holds percentages only; `vm-topology.md` gives the live boot volume as 45 GB. The `oci-capacity-report` workflow would read volume sizes; I did not run it (no mutation, but also no dispatch path from this session).
- ⚠️ **If you see something:** the gateway's disk hit **100 %** on 2026-11-02 and is at 94 %, on a box the daily IB reset depends on. Not this lane's scope; flagged to the manager in the wake message.
- Trainer workload: `ict-drift-retrain` ran hourly, 167 runs, 30.45 CPU-h in 7 days to 2026-10-13 (M, `trainer_workload_profile.json`, older than the ledger).
- Tenancy limits (M, `oci_limits.json`, read 2026-11-04): 250 cores / 1,666 GB limit, used 4 / 24.
- Oracle idle rule (M, Always Free page): idle only if CPU p95 < 20 % and network < 20 % and (A1) memory < 20 % over 7 days. All three hosts are far above on CPU, so no reclaim risk (`compute_reclaim_state.json`: all `ok`).

### 2.2 The lake, `bentzbk/jta-market-lake` (private HF dataset)

- **Size: not measured by this lane (U).** The squash lane (`session_01AFoLuNBcS5NT55ncec8xTw`) was not reachable by message (no running peers, `ListAgents`), and the HF connector returns 403 on file reads (`DEPTH.md`) because the account is over its limit. Use that lane's numbers when they land.
- What is known: the account hit HF's private limit — runners get HTTP 403 "Private repository storage limit reached for bentzbk" (M, row `HF-LAKE-STORAGE-403`, 2026-11-05 11:48Z). HF's free private cap is 100 GB (M, HF storage-limits page). The design projected the core lake at ≈ 73 GB plus optional streams (≈ 17.5 GB premium index first) (M as a projection in `docs/data/market-data-lake.md` §3.1). The account's other private repos are a 2025 model and a 2025 Space (sizes unread).
- ETF 1m is **not** in the lake: the trainer is its store of record (operator 2026-11-03), so it is on the trainer's 81 %-full disk (M for the decision; size U).
- HF's own super-squash page: freed space shows on the quota "within 36 hours" (M), so a squash result is not instant.

### 2.3 Kaggle, GitHub Actions, runpod

- **Kaggle GPU (M, 462 `comms/research/utilization/*.json` snapshots, 2026-10-13→2026-11-05):** quota 30 h/week. Highest `used_h` per weekly window: 2.0 h (window ending 10-17), 0.0 h (10-24), 0.0 h (10-31), 0.0 h (11-07, in progress). The router flags 30 h unused with a reset in 36 h. **GPU is not a binding ceiling today.** I did not render Kaggle's own quota page (its docs page returned no body); the 30 h figure is the ledger's `total_h`.
- **Runpod burst (M):** budget $10/month, month-to-date $0 (Oct and Nov).
- **GitHub Actions (M for visibility, U for minutes):** the repo is **public** (`gh api repos/benbaichmankass/JTA-Trader` → `private:false`, 207 workflow files). GitHub documents standard runners as free for public repos (E, from GitHub's policy; I did not re-read the page this session). Actual minutes used need admin billing access: **U**. Not a cost today.

### 2.4 Is anything billed today? (4 OCPU / 24 GB all month)

The two Oracle sources disagree, and that is the whole question:

| source | free A1 allowance | at 4 OCPU / 24 GB × 730 h (2,920 OCPU-h, 17,520 GB-h) |
|---|---|---|
| Oracle price list API, `B93297`/`B93298`, `lastUpdated 2026-11-02` (M) — <https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?currencyCode=USD> | first **3,000** OCPU-h and **18,000** GB-h free, then $0.01/OCPU-h, $0.0015/GB-h | **$0** (E). A 744 h month is 2,976 / 17,856: still under, by 24 OCPU-h and 144 GB-h |
| Always Free page (M) — <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm> | "All tenancies get the first **1,500** OCPU hours and **9,000** GB hours per month… equivalent to 2 OCPUs and 12 GB" for Always Free tenancies | (2,920−1,500)×0.01 + (17,520−9,000)×0.0015 = $14.20 + $12.78 = **$26.98** (E) |

What decides it: the tenancy's limit is 250 cores (M), which is not an Always-Free-only tenancy's limit, and the page says Pay-as-you-go tenancies are "only charged above the Always Free limits". The operator reports no charges (stated in `vm-topology.md`, **U**). Conclusion (E): the price-list reading applies and today's bill is $0, with **~24 OCPU-h/month of headroom**. Read the billing console to close it (**operator**, 1 minute).

The x86-vs-Ampere detail: nothing here depends on the retired x86 micro.

## 3. Prices (each with URL and date read)

| item | price | source (read 2026-11-05) |
|---|---|---|
| OCI A1 OCPU / GB beyond free | $0.01 / OCPU-h; $0.0015 / GB-h | Oracle price list API above (M); `www.oracle.com/cloud/price-list/` returned HTTP 403 to my fetch |
| OCI Object Storage Standard | first 10 GB free, then **$0.0255/GB-month**; Infrequent Access $0.01/GB-month after 10 GB | same API, `B91628`, `B93000` (M) |
| OCI Block Volume | $0.0255/GB-month storage only (performance units not read) | same API, `B91961` (M); VPU price **U** |
| OCI outbound data | first 10,240 GB/month free, then $0.0085/GB | same API, `B88327` (M) |
| OCI free block storage | 200 GB total across boot + block volumes | Always Free page (M) |
| Hetzner CAX11 / CAX21 / CAX31 / CAX41 | €6.49 / **€10.99** / €21.49 / €41.49 per month ex-VAT (2 / 4 / 8 / 16 vCPU; 4 / 8 / 16 / 32 GB; 40 / 80 / 160 / 320 GB NVMe; 20 TB EU traffic) | <https://www.hetzner.com/cloud/cost-optimized> (M). ⚠️ **every plan on that page read "currently unavailable"** |
| Hetzner Object Storage | €6.49/month incl. 1 TB stored + 1 TB egress; extra storage €0.0087/TB-hour | <https://www.hetzner.com/storage/object-storage/> (M); the page's extra-traffic unit is internally inconsistent (U) |
| HF PRO | **$9/month**; private storage **1 TB** + pay-as-you-go $18/TB/month above | <https://huggingface.co/pricing>, <https://huggingface.co/docs/hub/storage-limits> (M) |
| HF free user/org | 100 GB private | storage-limits page (M) |
| HF Team org | $20/user/month, 1 TB private per seat | pricing + storage-limits pages (M) |

Hetzner moved prices several times in 2026 (third-party reports: a 2026-06-15 increase, CAX21 €7.99→€10.49 by one source; the official page shows €10.99, so third-party figures are not used). EUR→USD: **~1.15 assumed (E)**; the real rate was not read.

## 4. What cannot be unified

- **Kaggle GPU** — no cheap always-on GPU exists in any option above. Oracle GPUs are $2.00/h (A10) and $4.00/h (A100 v2) (M, price list `B95909`, `B95907`); a month of one A10 is $1,460 (E). The free 30 h/week is largely unused (§2.3), so the right move is nothing.
- **IB Gateway isolation** — the 2026-06-10 wedge cascade came from the gateway sharing a 1 GB box with the trader (M, `vm-topology.md`). It stays on its own host.
- **The live trader** — 24/7, risk-gated, and its latency to Bybit/Alpaca/IB was **not measured** by this lane (U). Moving it to Hetzner (Germany/Finland) changes the network path; the trader is already on Oracle Paris. Moving it also means Tier-2 cutover work with money at risk.

## 5. The options, priced

All monthly totals are **E** (price × the M inputs above), USD, one 730 h month.

| option | what it is | monthly | removes trainer ceiling | removes lake cap | GPU |
|---|---|---|---|---|---|
| **0 — today** | OCI Always Free pool, lake on free HF | **$0** (E, §2.4) | no | no (403 today) | free Kaggle |
| **(a1)** OCI, resize only | gateway 6→3 GB, trainer 6→9 GB inside the free pool | **$0** | memory only | no | — |
| **(a2)** + 1 OCPU on trainer | trainer 2 OCPU / 9 GB: pool 3,650 OCPU-h → overage 650 × $0.01 | **$6.50** | **yes** | no | — |
| **(a3)** + lake on OCI Object Storage, 150 GB | (150−10) × $0.0255 | **$3.57** (300 GB: $7.40; 1 TB: $25.86) | — | yes | — |
| **(b1)** Hetzner CAX21 replaces trainer only | €10.99 ≈ $12.64; frees the OCI trainer's 1 OCPU / 6 GB, which has no other planned use | **$12.64** (+ IPv4, ~€0.50, U) | yes (4 vCPU / 8 GB; 80 GB disk) | no | — |
| **(b2)** (b1) + lake on Hetzner Object Storage | + €6.49 ≈ $7.46 | **≈ $20.10** | yes | yes (1 TB) | — |
| **(c1)** HF free org | $0 | — | — | no: same 100 GB, a free org does not lift it (M, storage-limits page) | — |
| **(c2)** HF PRO for the lake | $9 | — | — | **yes, 1 TB** | — |
| **(d)** one unified paid host (everything on Hetzner CAX31, 8 vCPU / 16 GB) | €21.49 ≈ $24.71, plus storage for the lake | **> $25** | yes | needs object storage on top | — |

Why (d) fails: the three hosts together run 4 OCPU all at p95 ≥ ~80–100 % (§2.1), so 4 shared vCPUs would saturate with no headroom; it puts the gateway back beside the trader; and it is over the $10–15 line before the lake. The Hetzner CAX plans also read "unavailable" today.

## 6. Recommendation

**Do not unify. Keep all three VMs where they are. Fix the three ceilings in this order, cheapest first:**

| # | step | monthly | what moves | one-time effort | risk to live trader |
|---|---|---|---|---|---|
| 1 | **Resize inside the free pool:** gateway 6→3 GB, trainer 6→9 GB (gateway memory max is ≈ 1.7 GB of 6, M) | $0 | memory only; trainer + gateway reboot | ≈ 1 h, Tier-2 | none (trader untouched); the gateway reboot interrupts IB for the minutes it takes |
| 2 | **Wait for HF-LAKE-SQUASH's size.** If the squashed lake plus planned streams is **< ~90 GB**, stay on HF free | $0 | nothing | 0 | none |
| 3 | If it is **> ~90 GB**: **HF PRO, $9** (1 TB) | $9 | the HF account only; no code change (same repo, same loader) | 5 min, operator pays | none |
| 4 | **Trainer +1 OCPU** (2 OCPU / 9 GB) | $6.50 | trainer shape | ≈ 30 min, Tier-2 | none |

- **Monthly total: $6.50 (squash is enough) to $15.50 (HF PRO also needed)** (E). Inside the operator's $10–15 line only at the low end; at $15.50 it is a 50-cent overshoot.
- **Why HF PRO over OCI Object Storage for the lake:** OCI at 150 GB is $3.57 vs $9, but the loader (`ml/datasets/lake.py`) and the Kaggle kernels read HF; moving the store means a loader + mirror + secret change (days, not minutes) to save ~$5/month (E). Worth revisiting only if the lake grows past ~300 GB (OCI $7.40 vs HF's $9 + $18/TB over 1 TB).
- **Why not Hetzner (b1):** it gives 4× the trainer CPU for $12.64 vs $6.50, but it is out of region, the CAX plans read "unavailable", and the trainer syncs a read-only DB from the live VM, so a new cross-provider path appears (E). Reopen if the trainer needs more than ~2 OCPU.
- **GPU:** no spend; 30 h/week free, ≤ 2 h/week used.
- **The 24 OCPU-h headroom (§2.4) is the risk to watch:** step 4 doubles the margin of error away. If the billing console shows the **1,500 / 9,000** reading applies instead, today's overage is already ≈ $27/month and the whole plan changes: re-cost before spending anything.

## 7. What I did not establish

- Lake size, and what squash reduces it to (**U**, squash lane's number).
- Absolute disk GB on each VM (**U**; only % and one doc figure).
- Which Oracle free threshold the billing system applies (**U**; the billing console decides).
- GitHub Actions minutes (**U**).
- Latency from Paris vs a Hetzner EU region to the venues (**U**).
- EUR/USD rate (assumed ~1.15, E).
- Oracle's page `www.oracle.com/cloud/price-list/` returned 403; prices come from Oracle's own public cost-estimator JSON, `lastUpdated 2026-11-02`.
