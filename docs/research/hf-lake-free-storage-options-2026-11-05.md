# Free storage options for the 100 GB market data lake (2026-11-05)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-05` · row `HF-LAKE-STORAGE-403` · lane `HF-LAKE-SQUASH`
> Gates this adds or changes: none. Nothing was created, moved or deleted; the operator chooses from the table.

**Question** (operator, 2026-11-05): *"Can we find other free resources of data storage to tap into?"* Free only, the operator pays for nothing.

## What has to fit (MEASURED)

On a runner, PR #23333 job 127283415795: private storage on `bentzbk` = **100,308,956,315 B**, all in `bentzbk/jta-market-lake`;
current revision 100,340,690,155 B over 51,972 files (crypto 91.75 GB, us_equity 8.42 GB, the rest < 0.2 GB). History overhead is ~0, so a
squash frees nothing. The lake is 4 days old and still growing (open month + new series), so any single 100 GB cap is a ceiling we are
already on. Trainer VM root disk, MEASURED today (issue #23351): 100 GB, **85 GB used, 13 GB free (88 %)**, of which the repo `data/` is 25 GB.

**Hard exclusion, from our own record:** the lake holds Binance / Yahoo / other data with **no open licence**
(`scripts/data_lake/hf_publish.py` docstring, README of the dataset). It must stay private, which rules out Zenodo and any public HF repo.

## The table

"Verified" = read on the provider's own page by this lane today (search snippet of that page); "UNVERIFIED" = third-party or cached text, or not found.

| Option | Free GB | Egress / limits | New account? | Read path for trainers | Effort | Source |
|---|---|---|---|---|---|---|
| **HF, a free organization** (operator creates it) | 100 GB private per free user *or org* (best-effort) | no per-repo limit; < 100k files/repo, < 10k entries/folder | an **org**, not a new user account; operator's act | same loader, new repo id; HF from runners/VM/Kaggle internet-on | low code, but `ml/datasets/lake.py` must read two repos | [HF storage limits](https://huggingface.co/docs/hub/storage-limits) (verified) |
| **Kaggle private datasets** (existing account) | **200 GB** private datasets total, 200 GB per dataset (quota doubled per a Kaggle product post; the docs page text we saw is older, UNVERIFIED as current) | per-dataset size counted **uncompressed**; docs snippet mentions a 50-top-level-file cap (UNVERIFIED) so 52k files must ship as shards; whether old dataset versions count is UNVERIFIED | **No** (we already have one; Kaggle ToS forbids a second) | kernels mount it at `/kaggle/input` natively; trainer VM and runners via the Kaggle API with the creds the repo already uses | medium: shard + upload, version per refresh | [Kaggle: doubling of private quota](https://www.kaggle.com/discussions/product-feedback/512322), [Datasets docs](https://www.kaggle.com/docs/datasets) |
| **Oracle Always Free Object Storage** | **20 GB** total (Always-Free-only tenancy) | 50k API requests/month listed for accounts with trial credits; outbound-data allowance NOT read | No (tenancy exists) | S3-compatible / OCI CLI from VMs and runners; Kaggle needs internet-on + secrets | medium | [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) (verified) |
| **Oracle Always Free block volume** | 200 GB **total, shared with every boot volume**, home region only | n/a | No | VM-local disk only (not reachable from runners / Kaggle) | high: the trainer is the only VM with free headroom today and has 13 GB | same page (verified); trainer disk MEASURED #23351 |
| **Cloudflare R2** | 10 GB-month | egress free; 1M class-A / 10M class-B ops per month | **Yes** (unless the operator already has one: not known) | S3 API from anywhere | low | [R2 pricing](https://developers.cloudflare.com/r2/pricing/) (verified) |
| **Backblaze B2** | 10 GB | egress free up to 3x stored; overage $0.01/GB (a card may be required: UNVERIFIED) | **Yes** | S3 API | low | [B2 pricing](https://www.backblaze.com/cloud-storage/pricing) (verified) |
| **Google Drive** (operator's account) | **15 GB shared with Gmail + Photos** | Drive API download quotas and API-terms position on bulk data NOT read | No (operator's own account) | Drive connector or OAuth from runners; not usable from Kaggle without secrets | high for 52k files | [Google storage](https://support.google.com/drive/answer/6374270) (verified) |
| **GitHub Git LFS** | 10 GiB storage + 10 GiB bandwidth/month (Free) | 2 GB per file; $0 budget blocks at the cap | No | `git lfs` / runners | low but tiny | [LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs) (verified) |
| **GitHub Releases** (private repo) | no stated total limit; each file < 2 GiB; 1000 assets per release | docs: no bandwidth limit stated | No | `gh release download` with the repo token: trivial from runners and VMs | medium (about 50 shards of < 2 GiB) | [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) (verified); **whether bulk data hosting is within GitHub's ToS and private-repo release storage is metered: NOT found, UNVERIFIED** |
| **Zenodo** | 50 GB/record, 100 files | public by default | Yes | public URL | n/a | [Zenodo FAQ](https://support.zenodo.org/help/en-gb/1-upload-deposit/80-what-are-the-size-limitations-of-zenodo): **excluded (licence)** |

## Findings that shape the choice

1. **Only two free pools are large enough to matter: Kaggle (200 GB, existing account) and a second HF org (100 GB).** Everything else is ≤ 20 GB, tied to a VM disk, or excluded by licence.
2. **The 91.75 GB of crypto is the whole problem, and most of it is immutable.** The manifest already marks `frozen_months`; closed months never change. Only the open month and new series are written daily.
3. **Oracle is not an option for the bulk.** Object Storage is 20 GB; block volume is shared with boot volumes and the trainer is at 88 %. The tenancy's actual usage was not readable (no workflow reads `oci limits`, per `docs/plans/OCI-STATE-CHECK-2026-10-13.md`), so even the 200 GB figure's remaining headroom is UNMEASURED.
4. Not measured here: Kaggle quota already used by `metis-market-data` and `metis-aggtrades-tail` (the Account tab shows it).

## Recommendation (the operator chooses)

**A. Split by temperature, no new account.**
- **HF (existing) keeps:** us_equity (8.4 GB), macro/futures/fx/options/universe/health/MANIFEST, and the *hot* crypto tail (open month + last N months). Roughly 10 to 25 GB.
- **Kaggle private dataset `metis-market-lake` (the already-planned mirror, follow-up d2 in `docs/data/market-data-lake.md`) takes the frozen crypto 1m history**, uploaded once as sharded archives (no daily re-upload because closed months do not change), ~75 to 90 GB of its 200 GB. Kaggle training kernels read it from `/kaggle/input` with no network.
- Loader reads frozen months from `LAKE_LOCAL_DIR` / the Kaggle mount and the hot tail from HF (the loader already supports both layouts).
- Pilot first: upload 1 GB, confirm the 50-file cap, version accounting and a runner download, before sharding 90 GB.

**B. Fallback if Kaggle's quota or ToS disappoints:** free HF org (needs the operator) for the crypto half, plus a loader change to span two repos.

**C. Do not use** Oracle for bulk, R2/B2 (10 GB, new accounts), Drive (15 GB shared with Gmail), Zenodo (licence).

**Unresolved and worth one check before committing:** (1) Kaggle's current official limits and whether old dataset versions count against the 200 GB; (2) whether GitHub Releases may carry this data (an alternative cold tier with trivial read path, at ~50 shards); (3) Kaggle's ToS on using datasets as bulk storage.

## Kaggle: current official text (rendered and read 2026-11-05 14:5xZ; pages are client-side rendered, so a plain fetch returns only the title)

[Datasets docs, "Technical Specifications"](https://www.kaggle.com/docs/datasets) -- this **supersedes the UNVERIFIED cells above for the limits**:
> "We provide resources for storing and processing datasets, but there are certain technical specifications: 200GB per dataset limit. 200GB max private datasets (if you exceed this, either make your datasets public or delete unused datasets). A max of 50 top-level files (if you have more, use a directory structure and upload an archive)."

The docs say nothing on whether old dataset versions count toward the 200 GB (the pilot measures it, see the row note).

[Acceptable Use Policy](https://www.kaggle.com/aup) (effective June 22, 2025): it bars "adding, providing, or uploading data to the Services that violates the intellectual property or privacy rights of others" and "activity unrelated to ML data science" as resource abuse. No clause bans using datasets as storage.

[Terms of Use](https://www.kaggle.com/terms) (effective June 22, 2025), two clauses to put in front of the operator:
> "You will only use the Services for your own internal, personal, non-commercial use, and not on behalf of or for the benefit of any third party ..."
> "... you will not contribute any Content or User Submission or otherwise use the Services ... in a manner that ... Copies or stores any significant portion of the Content" (here "Content" is Kaggle's own materials and other users' submissions, not our upload).

**Open question for the operator, not decided here:** (1) whether training a trading system counts as "personal, non-commercial" use (we already use Kaggle for training today, so this is pre-existing exposure, not new); (2) the lake's Binance data has no open licence, and the AUP bars uploading data that violates others' rights, so a *private* Kaggle copy carries the same redistribution question the private HF copy does.

## Pilot results (Kaggle 1 GB pilot, MEASURED 2026-11-05, PR #23333 runs 42055574691 and 42060325476)

Operator decision 2026-11-05 ~14:51Z, verbatim: "Kaggle 1 GB pilot first (Rec.)". Existing Kaggle account, private dataset `metis-market-lake`. Nothing deleted from HF.
Population: **90 frozen crypto 1m partitions, 6 symbols (BTC ETH SOL BNB XRP DOGE), 866,860,151 B**, 4 tar shards of ~245 MB. Not the 1 GB asked for: see (0).

| # | Question | Measured |
|---|---|---|
| 0 | Source | **HF refused the read** (the account is at its cap, `hf_hub_download` failed on the first HEAD), so the stage rebuilt the 6 symbols from data.binance.vision with the lake's own builder. Listing the HF tree still works; only file reads are blocked. The 6 symbols hold only 867 MB frozen, so v1 is 0.87 GB. |
| a1 | Top-level file limit | The docs say 50. **120 tiny top-level files were accepted by the API and the dataset reached `ready`** (separate probe dataset `metis-market-lake-filecount-probe`, left in place, private, 120 x 18 B). The limit did not bite on upload. |
| a2 | How archives behave | **Kaggle auto-unpacks `.tar` shards into a folder per shard** (`crypto-um_perp-1m-000/crypto/um_perp/1m/<SYM>/<period>.parquet`). Readers see plain parquet files; no extraction step. Top-level entries stay at 5. |
| a3 | Sharding for ~75-90 GB | Frozen partitions in this sample average 9.6 MB (yearly files dominate for old months); the HF lake overall averages ~1.9 MB per file (100.3 GB / 51,972). At 250 MB per shard, 80 GB = ~320 shards = 320 folders at top level, which is **over the documented 50**. Not tested above 120 top-level entries, nor above 90 files inside shards. A 10 GB / ~5k-file step is needed before 80 GB. |
| a4 | Upload speed | v1 (867 MB) upload + processing to `ready`: **102 s** (~8.5 MB/s end to end). A second version with identical content became `ready` in 17 s. Linear extrapolation for 80 GB: ~2.6 h. Not measured at that size. |
| b | Do old versions count against the 200 GB? | **Not measurable from a runner.** The Kaggle client has no storage-quota call (`quota_view` is GPU/TPU only) and `dataset_list` returns no size for a just-created dataset. The existing 4 private datasets total 173,162,995 B in their current versions (their old versions: 23, 2, 138 and 15 versions). `metis-market-lake` now holds 3 versions of the same 867 MB. **One number settles it: the operator reads private-dataset usage on the Kaggle Account tab.** About 1.0 GB means old versions do not count; about 3.5 GB or more means they do (and a 90 GB dataset must be versioned once, never re-uploaded). |
| c1 | Read on a GitHub runner via the Kaggle API | `kaggle datasets download --unzip`: **867 MB in 12 s and 14 s (72 and 62 MB/s)**; all 4 shards re-read, 90 files, byte counts equal the manifest. |
| c2 | Read in a Kaggle CPU kernel (internet off, no GPU quota) | Mounted at `/kaggle/input/datasets/<user>/metis-market-lake`; all 4 shards verified, **867 MB read in 7.1 s (122 MB/s)**; one 18 MB parquet in 6 ms; kernel queued-to-complete ~30 s. |
| d | ToS / docs | See "Kaggle: current official text" above. No clause bans storage use; two items for the operator (non-commercial wording; third-party data rights). |

### Go / no-go for moving the frozen crypto 1m history

**Technical: GO, in steps. Not yet operator-ready.** The route works end to end (upload, runner read, kernel read, byte-exact). Three things stand between this and 80 GB:
1. **(b) unknown.** One Account-tab number (above). If old versions count, the design is a single upload of the frozen set and no re-versioning.
2. **Scale untested.** Run a 10 GB / ~5k-file step first (top-level entry count, `ready` time, kernel mount time).
3. **HF stays full.** Reads and writes on HF are blocked at the cap. Copying to Kaggle frees nothing there by itself: the daily lake refresh writes to HF and keeps failing until space is freed on HF. Freeing it means deleting the frozen crypto from HF after the Kaggle copy is verified, which is the operator-approved step still to be taken ("delete nothing from HF" held for this pilot) and changes the loader to read frozen months from the Kaggle mount and the recent tail from HF.

**Operator-level exposure (not a lane decision):** Kaggle terms say personal, non-commercial use; and Binance data has no open licence (same exposure as the private HF copy).
