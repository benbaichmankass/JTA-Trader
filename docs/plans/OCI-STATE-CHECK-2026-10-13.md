# OCI state check — 2026-10-13

> **Doc status:** `unknown` · category `evidence` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `OCI-STATE-CHECK` (read-only; no VM, config or service change). Row: `COMPUTE-OCI-QUOTA-CHECK`, roadmap `L-OPS`.

Operator ask (2026-10-13): *"verify the state of the oracle vm — we don't want to lose any resources."*

## Verdict (top line)

**No VM is at demonstrated risk of idle reclaim within days. One cannot be ruled out: the IB gateway VM was NOT measured.**
The live trader and the trainer each fail at least one of Oracle's three idle conditions (below). The gateway is the open question, and the only data-loss exposure that is real today is **backup coverage**, not reclaim.

## What was established (and from what)

| Fact | Source | Status |
|---|---|---|
| 3 A1.Flex instances exist at the declared shapes (2/12 + 1/6 + 1/6 = 4 OCPU / 24 GB); verdict `clean` | scheduled `oci-inventory` run 38265931712, 2026-10-12 14:51Z (`Auto-resolve` ran, `drift` branch skipped, log line `verdict: state=clean`) | **MEASURED** via the OCI API |
| Per-instance lifecycle state | not printed in that run's log | **not read** |
| Tenancy limits / account type (Always-Free vs upgraded) | no workflow or script reads `oci limits` or the billing account | **not readable from the repo's OCI path** |
| Per-instance 7-day CPU/memory/network | no `oci monitoring` read exists anywhere in `.github/workflows/` or `scripts/ops/` (searched for `limits`, `monitoring`, `metric`) | **not readable**; a search that finds nothing proves nothing about the console |
| Live VM now: CPU 50.0 %, mem 10.6 %, disk 75.6 % | `/api/diag/status` `vm_health`, 2026-10-13 09:17Z | one instant, not p95 |
| Trainer now: up 42 d, load 2.09/2.10/1.86 on 1 OCPU, CPU 84 % over a 5 s sample, mem 1.4 of 5.9 GB used (24 %), swap 151 MB, disk 44 % of 97 G | trainer-vm-diag issue #17839 | one instant, not p95 |
| Gateway | trainer cannot SSH it (`Permission denied (publickey)`; port 22 is open, #17840). The runner reaches it only via ProxyJump through the live VM | **UNMEASURED** |

## The quota discrepancy: what is and is not known

Oracle's page (fetched 2026-10-13, docs.oracle.com Always Free Resources): *"All tenancies get the first 1,500 OCPU hours and 9,000 GB hours per month for free … For Always Free tenancies, this is equivalent to 2 OCPUs and 12 GB."* Upgraded accounts are charged only for usage **above** the Always Free limits.

- 4 OCPU / 24 GB running all month is 2,880 OCPU-h / 17,280 GB-h, i.e. roughly 1,380 OCPU-h and 8,280 GB-h above the free pool.
- A tenancy that is Always-Free-only could not hold 4/24 at all, and the three instances exist and match (measured). **Inference, not verified:** the tenancy is upgraded (pay-as-you-go) or grandfathered at the older allowance. The operator's earlier report of a card on file with no charges fits grandfathering; it does not prove it. Only the OCI console billing page or `oci limits` settles it.
- If upgraded, the overage is a small recurring bill, not a loss of resources. If the account is Always-Free-only with a limit that was not enforced on existing instances, a forced shrink would hit the live trader first. **That second case is the only quota path that threatens resources, and it is unverified in either direction.**

## Idle reclaim: exposure per VM

Oracle rule (same page): a VM is idle when, over **7 days**, ALL of: CPU p95 < 20 %, network < 20 %, and (A1 only) memory < 20 %. The page says *Always Free* instances may be reclaimed; it is silent on whether instances in an upgraded tenancy are exempt, and silent on what reclaim does.

| VM | Reclaim exposure | Why |
|---|---|---|
| `ict-bot-arm` (live, 2/12) | **Low, not zero.** Memory 10.6–15.1 % is under 20 %, but CPU read 31.6 % and 50 % at two instants. | Idle needs all three conditions; CPU p95 is the one likely to clear 20 %. p95 and network unmeasured. |
| `ict-trainer-vm` (1/6) | **Low.** Load ~2 on 1 OCPU, CPU 84 % at the sample, memory 24 %. | Fails the CPU and memory conditions at this instant. |
| `ict-ib-gateway` (1/6) | **UNKNOWN; highest of the three.** | Dockerised IB Gateway, no public IP, nothing else on the box. No measurement exists. |

## Data that would be lost on reclaim

- **`trade_journal.db` (live, the money DB).** The only copy found off the live VM is the trainer's daily pull: `data/trade_journal.db`, 2.0 GB, mtime 2026-10-13 05:00, written by `sync_trainer_data.sh` (log: `sync_done overall_rc 0` at 05:03Z). It is **one overwritten replica, not a versioned backup**: a corruption on the live DB propagates to it at the next pull. Up to ~24 h of trades would be missing on a restore.
- **No scheduled backup workflow exists.** Searched `.github/workflows/` and `deploy/` for backup/offsite/snapshot; the `.backup` calls found are one-off pre-mutation copies inside prop/repair scripts (stored on the VM itself). Whether an OCI boot-volume backup policy exists is a console setting and was **not read**.
- **Trainer store / registry.** `trainer_store.db` was not found at the two paths probed (location not established this session); the trainer's model registry is on the trainer only. Not verified either way.
- **Live VM root-filesystem use 75.6 %** (one `vm_health` sample, 2026-10-13 09:17Z; separate from reclaim): the boot volume is the only home of the journal's live copy; headroom is a real operational risk.
- **Gateway:** stateless by design (Dockerised, reproducible from `vm-ib-gateway-deploy`); loss costs IBKR connectivity and re-login, not data. Not verified this session.

## Recommendations, ranked

| # | Action | Tier | Why |
|---|---|---|---|
| 1 | **Read the console once:** Billing → account type, and Governance → Limits for `standard-a1-core-count`/`standard-a1-memory-count`. Record in `docs/reference/vm-topology.md`. | 1 (read; needs the operator's console or a limits-read added to `oci_inventory.py`) | Resolves 4/24 vs 2/12; nothing else is decidable without it. |
| 2 | **Versioned off-VM backup of `trade_journal.db`** (SQLite `.backup`, daily, keep 7, to OCI Object Storage within the free 20 GB, or a private repo artifact/Release if size allows). | 2 (new timer on the live VM) | The only money-DB copy is an unversioned daily mirror. Biggest real loss exposure. |
| 3 | **Add a read-only OCI Monitoring pull** to `oci-inventory` (`CpuUtilization`, `MemoryUtilization`, `NetworksBytesIn/Out`, 7 d, p95, per instance) plus `limits`. Needs the API user's policy to allow `read metrics`/`read limits`; if denied, that itself is the finding. | 1 | Replaces guesses with p95s; the gateway reading in particular. |
| 4 | **Read-only gateway probe via ProxyJump through the live VM** (`uptime`, `free`, `docker stats`), added to an existing gateway workflow's read mode. | 1 | Only way to measure the gateway today. |
| 5 | **OCI boot-volume backup policy** on the live VM (console toggle, free tier covers 5 backups). | 2 | Cheap second layer under #2. |
| 6 | **Keep-alive load: do NOT add.** The Oracle page does not say whether artificial load is permitted. Only consider it for the gateway if #3/#4 show it is actually idle, and then prefer real work (e.g. moving an existing timer) over a synthetic burner. | 2 | Unknown terms plus a stress process next to a live-money process is a net risk. |
| 7 | **Moving the gateway** onto the live VM: no. It was split off after the 2026-06-10 wedge cascade. | 2 | Reverts a deliberate isolation. |

## Not done / limits of this check

- No `oci limits`, billing or monitoring read was possible; no console access.
- All utilisation numbers are single instants, not 7-day p95.
- Gateway: nothing measured. Lifecycle states: not read.
- Oracle's reclaim policy was read from the public page only.
