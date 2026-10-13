# COMPUTE-KAGGLE-GPU pilot — 2026-10-13

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `COMPUTE-KAGGLE-GPU` · checklist row `COMPUTE-KAGGLE-GPU` (`landed_unproven`) · parent `docs/plans/COMPUTE-ARCH-REVIEW-2026-10-13.md` rec. 6

## Result: PASSED on the second dispatch (run 38383862376, 2026-10-13 10:30Z, `main` @ 5ef34ee1)

| Question | Answer | Basis |
|---|---|---|
| Auth smoke test from GitHub Actions | **OK.** `KAGGLE_API_TOKEN` (KGAT) alone authenticated; username derived from the token; no `KAGGLE_USERNAME`. | job 115250670252: auth step success, token masked |
| Push → run → output downloaded | **OK end to end.** `Kernel version 1 successfully pushed` → QUEUED (3 polls, ~90 s) → RUNNING (~90 s) → COMPLETE → output `result.json` + kernel log downloaded → artifact `kaggle-gpu-pilot` uploaded (id 11804603919, 14-day retention) | job log + artifact contents |
| GPU | `nvidia-smi` listed **2 × Tesla T4 (15 GiB each)**; torch 2.11.0+cu128 used one: **3.49 TFLOPS fp32, 17.12 TFLOPS fp16** (4096² matmul, 30 s each) | `kernel/result.json`, kernel log |
| Wall time | **186 s** push→COMPLETE (≈90 s queued + ≈90 s run, of which ≈70 s was the benchmark itself) | `wall.txt`; log timestamps |
| Weekly quota (`kaggle quota`) | **GPU 30.00 h/week** (0.00 h used before, **0.02 h used after → 29.98 h remaining**); TPU 20.00 h; both refresh **2026-10-17T00:00** | `quota-before.txt` / `quota-after.txt` |
| Phone verification / GPU eligibility | Not blocking: GPU kernel with `enable_internet: false` ran on the verified account | run above |

Observation window: one run, one account, one moment. Queue time (≈90 s) and the T4/P100 assignment are Kaggle's to vary; do not read 186 s as a guarantee. The 0.02 h charged for a ≈90 s run suggests quota is billed on run time, but one data point does not establish the rounding rule.

### First dispatch, for the record (run 38382717680, 10:20Z)

Failed in 1 s: `KAGGLE_API_TOKEN` reached the job as an empty string before any Kaggle call (why was never established: a session cannot list secrets, so "missing", "wrong scope" and "saved empty" are all untested). The operator re-saved it as a repository secret and the second dispatch passed. The cleanup/upload steps of that first run produced noise because the username never resolved; they are now skipped when `USERNAME` is empty.

## What is established about the client (read from `kaggle==2.2.4` source, 2026-10-13)

- Needs **`kaggle>=2`**; the workflow installs `kaggle>=2.0`.
- Token is read from env `KAGGLE_API_TOKEN` (or `~/.kaggle/access_token`). The username is derived by introspecting the token, so **`KAGGLE_USERNAME` is not needed**.
- `kaggle quota` prints weekly GPU/TPU hours used, remaining, total and refresh time; the workflow records it before and after.
- Kernel metadata fields used: `enable_gpu: true`, `enable_internet: false`, `is_private: true`. Kaggle accepted GPU with internet off for this account (run 38383862376).

## What the workflow does when it runs

Auth smoke → `kaggle quota` → push private kernel (`scripts/research/kaggle_gpu_pilot/`: `nvidia-smi` + 2×30 s fp32/fp16 matmul benchmark, public data only) → poll `kaggle kernels status` every 30 s (25 min cap) → download output → upload artifact `kaggle-gpu-pilot` (username masked). Secret and username are masked and never echoed.

## Next: routing a research-queue unit to it

Not built; one clean run now exists. Sketch for a follow-up row: a unit declares `compute: kaggle-gpu`; a dispatcher step pushes a kernel from a pre-reviewed script directory (never a dispatch input, same rule as `research-script-run`), polls, and lands the output through the research-result path. Data must be public or derived non-sensitive panels; trade/account data never leaves the repo. Quota (weekly hours) is the budget gate in place of the $10 RunPod ledger.

## Row state

`COMPUTE-KAGGLE-GPU` is `landed_unproven` → observed once (this run). It is left for the manager to move to `done` with the roadmap writeback; the routing build above is a separate row, not part of this pilot.
