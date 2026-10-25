# Compute architecture review — 2026-10-13

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · nobody has verified this document's status. Lane `COMPUTE-ARCH-REVIEW` (read-only review; nothing built, no VM/config/order change); parent row `STRATEGY-REALIGN`. Its figures are dated 2026-10-13 and are single samples.

**Question (operator, 2026-10-13, voice paraphrase):** with Claude effort and compute moving to research (exploration, backtests, the AI trader, frontier models), is compute allocated well? Can training consolidate onto one VM? What else is free? The VMs stay as they are for the continuous pipelines; bursty research may belong elsewhere; GPU bursts should be part of the workflow.

**Short answer.**
1. Training is *already* on one VM. The real overlap is that **bursty research is queued on the 1-OCPU trainer** (`research-script-run-trainer`) behind the daily cycle and promotion sweep, while GitHub-hosted runners (free, 20 concurrent, 6 h/job) are barely used for it.
2. **Do not move training onto the live VM.** It is the money box, its disk is 75.5% full, and the trust split in `docs/reference/vm-topology.md` forbids it.
3. The best free capacity is already wired but under-used: GitHub runners, the M19 GPU burst (7 runs, $0.22 lifetime of a $10/month cap, none since 2026-07-06), and the Hugging Face Hub (sourcing, not compute).
4. We **do not measure VM utilization over time**, so "optimal" cannot yet be shown. The first recommendation is to measure it.

Population and date for every figure below: one read at **2026-10-13 ~08:40Z** unless a window is named. A single sample is not a utilization profile.

---

## A. Current map

### A1. VMs

Shapes are the repo's declared topology (`docs/reference/vm-topology.md`, last verified `never` — treat as a claim); utilization is measured where noted.

| Role | Shape (declared) | What runs on it | Measured utilization |
|---|---|---|---|
| **Live trader** (Ampere A1) | 2 OCPU / 12 GB, 45 GB boot volume | `ict-trader-live`, `ict-web-api` (:8001), `caddy`, `ict-telegram-bot`, `ict-claude-bridge`, `ict-claude-decision-bot`; timers: git-sync (~5 min), liveness/web-api watchdogs, db-integrity, insights generators, fills/funding pulls, health snapshot, prop feed/executor | `/api/diag/snapshot` `vm_health`: **CPU 31.6%, memory 15.1%, disk 75.5%** (one sample). Uptime of the trader process 2,629 s (restarted by a deploy). No time series. |
| **Trainer** (Ampere A1) | 1 OCPU / 6 GB | `ict-trainer.timer` (daily; last trigger 00:05Z), `ict-promotion-readiness` (04:00Z, ~99 min, ~3.2 GB), `ict-trainer-catchup` (05:00Z), `ict-drift-retrain` (hourly), `ict-candle-refresh` (03:20Z), `ict-trainer-forecast` (every 15 min), `ict-trainer-publish` (every 2 min), `ict-offload-drain` (every 20 min), `ict-pm-snapshot` (4×/day), git-sync (15 min). Also the SSH target of `research-script-run-trainer`. | `/api/bot/ml/status` (mirror, 31 s old): **load_1m 1.00** on 1 OCPU, disk 43.6% used (58.6 GB free of 103.9 GB), uptime 3.69 M s. Daily cycle wall time **≈35–65 min** (from `/api/bot/ml/cycle`, 500 rows, 2026-10-09 → 10-13: 67–69 manifests trained per cycle; per-day sum of manifest wall time 28–64 min; 10-09 is a partial day). Peak RSS ~5 GB per manifest under a `MemoryMax=5G` cap (docs, not measured here). **Heavy-job occupancy ≈ 2.5–3 h of 24 h** (cycle + 99-min promotion sweep), inferred from timers; the light always-on timers are not included. |
| **IB gateway** (Ampere A1) | 1 OCPU / 6 GB | Dockerised IB Gateway, daily reset 06:05Z, ~5-min watchdog | **Unmeasured.** No read path exists from a web session; I did not SSH. |

**Free-tier ledger.** The repo says Ampere is 2 + 1 + 1 = **4 of 4 OCPU, 24 of 24 GB — full**. Oracle's Always Free page, fetched 2026-10-13, reads **"2 OCPU and 12 GB total"** for Ampere A1 (1,500 OCPU-hours / 9,000 GB-hours a month), plus up to 2 AMD micro VMs (1/8 OCPU, 1 GB), 200 GB block+boot, 20 GB object storage, 10 TB/month egress. Those two statements cannot both describe the same tenancy. Either the page changed, the fetch summary dropped a factor of two, or the account is not Always-Free-only (a paid tenancy is billed for the excess). **Unverified which.** This matters: Oracle also states it may reclaim Always Free instances idle for 7 days (CPU p95 < 20%, network < 20%, and for A1 memory < 20%). The live VM's memory (15.1%) is under that line; its CPU sample (31.6%) is not. Nobody has computed p95 over 7 days. Row `COMPUTE-OCI-QUOTA-CHECK`.

### A2. GitHub Actions (repo is public → standard hosted runners are free)

Limits from `docs.github.com/en/actions/reference/limits`, fetched 2026-10-13: **6 h per job**, **20 concurrent jobs on the Free plan**, 35-day workflow-run ceiling, 1,000 `GITHUB_TOKEN` API requests/hour/repo. The plan tier of this account is not shown by anything I can read; 20 is the Free-plan figure, so treat larger caps as **unverified**.

Research-relevant workflows (timeouts read from the YAML; run durations from `list_workflow_runs`, 2026-10-09 → 10-13):

| Workflow | Where it computes | `timeout-minutes` | Concurrency group | Measured |
|---|---|---|---|---|
| `research-script-run` | GitHub runner | 360 | per research unit → units run in parallel | 162 runs lifetime. Latest 30: most **1–6 min**; a cluster on 10-09 took **19–120 min** (batch of 3 started the same second ⇒ parallel, not queued). All 30 succeeded. |
| `research-script-run-trainer` | runner SSHes to the trainer and runs the unit there | 360 | **single global group** (`1 OCPU / 6 GB — one run at a time`) | 11 runs lifetime; **4 failed** (10-12 13:52 after 41 s; 10-13 00:48, 02:16 and 05:55 each after ≈45 min in the "run on trainer" step). The failure step is "Fail if the trainer command failed"; the cause inside the command was not read (unmeasured). The 3 × 45-min failures sit in/after the 00:05–02:18Z cycle and the 04:00Z promotion sweep windows, which share the trainer's heavy-job lock — consistent with queueing behind them, **not shown**. |
| `research-harness-dispatch` | runner | 30 (+110 verify job) | per harness+run → parallel | not sampled |
| `research-queue-dispatch` | runner; hourly cron `:20` | 30 | `research-queue-dispatch` (one) | not sampled |
| `trainer-offload-train` | runner (training offloaded from the trainer) | 330 | per issue/run | not sampled |
| sweeps (`e35-bracket-sweep`, `m20-exit-lever-sweep`, `regime-adx-cutpoint-sweep`, `pullback-frac-cross-leg-sweep`, `ict-scalp-exit-sweep`) | runner | not read | not read | not sampled |

### A3. M19 spot-GPU burst (`gpu-burst-train.yml`)

- **Trigger:** open an issue labelled `gpu-burst-train` with `experiment`, `est_cost`, `train_cmd`, `max_minutes`. Only labelled issues share one serializing concurrency group, so two real bursts never overlap.
- **Gates:** (1) preflight against `comms/gpu_spend_ledger.json` — aborts if month-to-date + est_cost > **$10/month**; (2) repo variable `GPU_BURST_ARMED == '1'`, else dry preflight with zero spend; (3) `run_burst.sh` launches one pod and tears it down in an EXIT trap; (4) the billed cost is appended to the ledger. `status_only: true` reports the arm-gate state without spending.
- **Measured (ledger, read today):** provider RunPod; **7 runs, all in July 2026 (2026-07-02 → 07-06); 4 completed, 3 failed; lifetime $0.2164; ~RTX 3090 at $0.22/h**; none since 2026-07-06. So the path works and has been unused for 3 months. Current value of `GPU_BURST_ARMED` is **unknown** (not readable by a session; `status_only` would tell).
- No research-queue unit can ask for a GPU today; a burst needs a hand-written issue.

### A4. Other resources in the session environment (not repo compute)

The Hugging Face Hub connector is attached to Claude sessions (authenticated, can search models/datasets/papers/Spaces). HF is already referenced in the repo only for large-file upload (`scripts/hf_upload_large_files.py`) and `hf-cron.yml`. No Kaggle, Colab or Modal use found in the repo (grep, 2026-10-13; a negative from one grep, not proof).

---

## B. Workload map

| Workload | Class | Runs now | Should run | Note |
|---|---|---|---|---|
| Trading pipeline, web API, prop executor/feed, watchdogs, fills pulls, git-sync | continuous | live VM | live VM (unchanged) | |
| IB gateway | continuous | gateway VM | gateway VM (unchanged) | |
| Daily training cycle, promotion-readiness sweep, drift scan, candle refresh, forecasts, mirror publish | scheduled batch (some continuous-light) | trainer VM | trainer VM | needs the trainer's DB mirror and registry; 2.5–3 h/day heavy |
| Research units whose data is in git/public APIs (backtests, sweeps, harness runs) | bursty research | GitHub runners (`research-script-run`) | GitHub runners | already right; parallel; free |
| Research units that need trainer-local data (exit-head builds, replay, large ML datasets) | bursty research | trainer VM via SSH, **serialized, 1 OCPU** | trainer for data access, but **queue it explicitly** and keep it off the cycle/sweep windows | 4/11 failed; cause unread |
| ML training that fits in 6 GB | scheduled batch | trainer VM | trainer VM | |
| ML training / bake-offs that need > 5 GB or a GPU (TCN, deep heads, frontier models) | bursty research | `trainer-offload-train` (runner CPU) or hand-opened `gpu-burst-train` issue | GPU burst, requested **from the queue unit** | M19 exists; unused since July |
| Frontier-model/hypothesis sourcing | bursty research (Claude-side) | ad hoc web search | HF Hub MCP + weekly frontier scan | no compute, only Claude tokens |

**Is training spread in a way that could be consolidated?** Training is spread across three *places* — trainer VM (scheduled), GitHub runner (`trainer-offload-train`), RunPod (M19) — but each has a distinct job (always-on scheduled, CPU-heavy one-off, GPU one-off). That is a sensible tiering, not duplication. Consolidating onto "one VM" would not free research capacity: the trainer's heavy-job occupancy is ≈ 2.5–3 h/day, so the capacity lost to training is small, and **the research that is blocked is the research that *also* runs on that same 1-OCPU box**. Moving the scheduled cycle off it would not help; moving the research off it would.

**Is the trainer idle much of the day?** Heavy work ≈ 10–13% of the day by timer arithmetic, but load_1m was 1.00 at the sample (a 1-OCPU box with light always-on timers sits near 1.0). It has memory headroom outside the cycle windows but only **1 OCPU**, so the headroom is for light CPU work, not a research farm. No utilization series exists to say more.

**Are research jobs queued behind each other on Actions?** Not on the runner route (20 concurrent; same-second batches ran in parallel). **Yes on the trainer route**, by design: one global group. The measured cost is 4 failures of 11 runs; the cause is not read. This is the one real queue.

---

## C. Free / cheap resources

Verification status is stated per row. "Claude-cost" = effect on Claude tokens, the scarce input per `STRATEGY-REALIGN`.

| Option | Limits (source) | Fit for our workloads | Effort | Risk | Claude-cost |
|---|---|---|---|---|---|
| **GitHub Actions public-repo runners** | 6 h/job, 20 concurrent (Free) — *verified*, official limits page. Larger runners: **unverified**. Runners are ~4 vCPU/16 GB class (not re-checked today). | Best fit for all backtests/sweeps not needing trainer data. Cannot read the private VM DBs without SSH. | S | Results land in a public repo (already the practice). Secrets in env on the SSH route. | Lowers it: fewer sessions babysitting the trainer queue. |
| **Oracle Always Free — unused quota** | Page says Ampere 2 OCPU/12 GB total, AMD micro ×2 (1 GB each), 200 GB storage, 10 TB egress — *fetched, conflicts with repo's 4/24* | Ampere pool is full per repo. Two AMD micros (1/8 OCPU, 1 GB) are too small for research; usable only for light watchers. 200 GB storage cap vs 45 GB + ~104 GB boot volumes: not verified. | M (verify) | Tier 2 for any VM change; idle-reclaim exposure (see A1). | Neutral. |
| **Hugging Face Hub** (models, datasets, papers) | Free to read; connector attached to sessions — *verified by connector availability* | Sourcing ideas and pretrained time-series/tabular models for the frontier scan; dataset hosting for derived (non-secret) research data | S | **Data leakage:** public repos/datasets are world-readable — never upload trade/account data; use private repos only after a credential-handling review. Model licences. | Lowers it: structured search replaces ad-hoc browsing. |
| **HF ZeroGPU Spaces** | Free account: **5 GPU-minutes/day**, 2 hosted Spaces, Gradio SDK only, NVIDIA RTX Pro 6000 Blackwell halves (48 GB), PyTorch 2.8+ — *verified*, official doc | Inference demos; **not suited to training/backtests** (minutes/day, Gradio-bound, no batch API) | — | n/a | Not worth it. |
| **HF Jobs** | **Pay-as-you-go only; needs a positive credit balance**; T4 $0.40/h, A10G $1.00/h, A100 $2.50/h, H200 $5.00/h; default timeout 30 min; CLI `hf jobs run` — *verified*, official doc | A credible alternative to RunPod for GPU bursts (scriptable, per-second billing, bucket mounts); *not free* | M | Credentials (HF token as a secret); spend must go through the same ledger gate. | Neutral. Consider only if RunPod becomes a problem. |
| **Kaggle notebooks** | ~30 GPU-h/week, ~12 h sessions, T4/P100, ~30 GB RAM — **unverified** (docs pages did not render in the fetch; figures are from memory). CLI `kaggle kernels push/status/output`. | Free GPU for bake-offs. Needs a Kaggle account token (operator originates) and a dataset upload. | M | Data must be uploaded as a Kaggle dataset (private is possible; confirm). Account/phone verification. Reliability: queue/availability varies. | Neutral to slightly lower once wired; first pilot costs a session. |
| **Google Colab (free)** | Not guaranteed, up to 12 h, idle disconnects, **no background execution on free**, and the FAQ lists SSH shells / bypassing the notebook UI as grounds for termination — *verified*, official FAQ | Interactive only. Automating it is against stated practice. | — | ToS | **Reject.** |
| **M19 / RunPod spot GPU** | $10/month cap, ledger-gated, teardown trap; $0.22/h RTX 3090 in July | The existing GPU path; works | S (queue wiring) | Ledger already bounds spend | Lowers it once units can request it. |

**What this does not recommend:** buying capacity, resizing a VM, or enlarging the $10 cap — none is justified by anything measured yet.

---

## Ranked recommendations

Ranked by research capacity gained per unit of effort/risk. Each is a checklist row (`COMPUTE-*`, state `queued`, roadmap ref and observation set).

1. **`COMPUTE-GH-FIRST` — route research to GitHub runners by default; make the trainer route explicit and non-colliding.** Tag each queue unit as `runner` or `needs_trainer_data`; read the cause of the 4 failed trainer runs (the 3 × 45-min ones first); keep trainer-route units out of the 00:00–06:00Z cycle/sweep windows or let them yield to the heavy lock explicitly. Tier 1 (workflow + queue metadata). Effort S–M. *Why first:* it removes the only measured queue and uses capacity that is already free and idle.
2. **`COMPUTE-GPU-WIRE` — let a queue unit request the M19 GPU burst.** Add a `compute: gpu` declaration that opens the labelled issue with the unit's `est_cost` and `max_minutes`; start with `status_only` to report `GPU_BURST_ARMED`/`GPU_PROVIDER`/key state. Keep the $10 cap; any cap change is the operator's. Tier 1 (dispatch glue); arming is the operator's existing gate. Effort S–M. *Why:* the path works ($0.22 lifetime, 3 of 7 runs failed — read why before scaling) and the operator asked for it in the workflow.
3. **`COMPUTE-UTIL-TELEMETRY` — start measuring.** Record daily CPU/memory/disk/load p95 for live, trainer and gateway (live already has `vm_health` in the snapshot; trainer has `load_1m` and disk in the mirror; gateway has nothing). Needed to decide anything about consolidation or reclamation. Tier 1 for a read-only collector in the existing health snapshot; adding a gateway reader touches a VM → Tier 2. Effort S.
4. **`COMPUTE-OCI-QUOTA-CHECK` — resolve the 4/24 vs 2/12 Always-Free discrepancy and the idle-reclaim exposure.** Read the tenancy limits and the 7-day p95 for each A1 instance; confirm whether the account is Always-Free-only. Read-only (Tier 1); any resulting VM change is Tier 2. Effort S. *Why:* if the page is right and the account is Free-only, the topology is over its quota; if reclamation applies, the live VM is the one at risk.
5. **`COMPUTE-HF-SOURCING` — make the HF Hub connector a standing input to the frontier scan.** Add a fixed HF search step (trending/new time-series, tabular, forecasting models and papers) to `frontier-research`, output to pre-registered queue units only. Public data only; no uploads. Tier 1. Effort S. Directly serves the operator's "AI and frontier" priority.
6. **`COMPUTE-KAGGLE-GPU` — pilot one free-GPU bake-off on Kaggle.** One private notebook + private dataset of a **public-data** feature panel; success = one result retrieved by CLI without a session babysitting it. Needs an operator-originated Kaggle token. Verify the quota first (**currently unverified**). Tier 1. Effort M. Lowest rank because the burst path already covers GPU and Kaggle adds a credential and a data-egress surface.

**Not recommended now:** moving training onto the live VM; consolidating the gateway into the trainer; Colab; HF ZeroGPU for training; HF Jobs (revisit only if RunPod fails); raising the GPU cap.

## Gaps in this review (stated, not hidden)
- No utilization time series for any VM; the numbers are single samples (live 08:40Z; trainer mirror 08:41Z).
- Gateway VM: shape and load unmeasured.
- Cause of the 4 failed `research-script-run-trainer` runs not read (budget); the queue-behind-the-cycle explanation is a hypothesis.
- Sweep workflows' timeouts/concurrency not read; `research-harness-dispatch`, `research-queue-dispatch`, `trainer-offload-train` durations not sampled.
- Kaggle figures and GitHub larger-runner limits are unverified; Colab, ZeroGPU, HF Jobs, GitHub limits and Oracle limits come from the official pages fetched today.
- `GPU_BURST_ARMED` current value unknown.
