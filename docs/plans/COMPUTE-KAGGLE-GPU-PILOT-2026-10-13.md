# COMPUTE-KAGGLE-GPU pilot — 2026-10-13

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `COMPUTE-KAGGLE-GPU` · checklist row `COMPUTE-KAGGLE-GPU` (`landed_unproven`) · parent `docs/plans/COMPUTE-ARCH-REVIEW-2026-10-13.md` rec. 6

## Result: NOT PROVEN — blocked on the Actions secret, before any Kaggle call

| Question | Answer | Basis |
|---|---|---|
| Workflow landed? | Yes — PR #17843, `.github/workflows/kaggle-gpu-pilot.yml` (workflow_dispatch only) | merged 2026-10-13 10:20Z |
| Auth smoke test from GitHub Actions | **NOT PROVEN.** Run 38382717680 (dispatched 10:20:45Z) failed in 1 s: `KAGGLE_API_TOKEN` reached the job as an **empty string**. | job 115246850792 log: env shows `KAGGLE_API_TOKEN:` blank; step printed "KAGGLE_API_TOKEN secret is empty" |
| Kaggle reached? | **No.** The failure precedes the first Kaggle call, so it says nothing about phone verification, GPU eligibility or token validity. | same log |
| GPU type / run wall time / quota | **Unmeasured** — the kernel was never pushed. | — |
| Pipeline push → run → output | **Unmeasured.** | — |

**Most likely cause (hypothesis, not verified):** no *repository* Actions secret named exactly `KAGGLE_API_TOKEN` is visible to this workflow — wrong name, saved as an Environment/Dependabot/Codespaces secret, saved in another repo, or saved empty. A session cannot list secrets, so this cannot be checked from here.

**What the operator must do:** Settings → Secrets and variables → Actions → **Repository secrets** tab: confirm a secret named exactly `KAGGLE_API_TOKEN` exists with a non-empty `KGAT_…` value (re-save it if unsure). Then ask the manager/lane to re-dispatch `kaggle-gpu-pilot`, or use Actions → kaggle-gpu-pilot → Run workflow.

## What is established about the client (read from `kaggle==2.2.4` source, 2026-10-13)

- Needs **`kaggle>=2`**; the workflow installs `kaggle>=2.0`.
- Token is read from env `KAGGLE_API_TOKEN` (or `~/.kaggle/access_token`). The username is derived by introspecting the token, so **`KAGGLE_USERNAME` is not needed**.
- `kaggle quota` prints weekly GPU/TPU hours used, remaining, total and refresh time; the workflow records it before and after.
- Kernel metadata fields used: `enable_gpu: true`, `enable_internet: false`, `is_private: true`. Whether Kaggle accepts GPU with internet off for this account is unverified until a run reaches the push step.

## What the workflow does when it runs

Auth smoke → `kaggle quota` → push private kernel (`scripts/research/kaggle_gpu_pilot/`: `nvidia-smi` + 2×30 s fp32/fp16 matmul benchmark, public data only) → poll `kaggle kernels status` every 30 s (25 min cap) → download output → upload artifact `kaggle-gpu-pilot` (username masked). Secret and username are masked and never echoed.

## Next, if the pilot passes: routing a research-queue unit to it

Not built. Sketch for a follow-up row, only after one clean run: a unit declares `compute: kaggle-gpu`; a dispatcher step pushes a kernel from a pre-reviewed script directory (never a dispatch input, same rule as `research-script-run`), polls, and lands the output through the research-result path. Data must be public or derived non-sensitive panels; trade/account data never leaves the repo. Quota (weekly hours) is the budget gate in place of the $10 RunPod ledger.

## Closing condition for the row

`COMPUTE-KAGGLE-GPU` closes (`done`) when a dispatched run's artifact shows `nvidia-smi` output and a `kaggle quota` reading, or the run names a Kaggle-side blocker. Until then it stays `landed_unproven`.
