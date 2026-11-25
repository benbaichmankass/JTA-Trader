# Loss disposition: `watchdog-rows` (run 45069395246) and `research-store-bundle` (run 45094782352)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-25` · registered in [`../DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `RT-EXPIRE-1125`

Raised by the research loss detector (run 45294201604, check `C_expiring_unlanded_artifacts`); pipeline item `PI-20261124-RTEXPIRE-0001`.
Both artifacts were downloaded and read before expiry. Gates this adds or changes: none.

## 1. `watchdog-rows`, run 45069395246 (expired 2026-11-25T21:02Z) — LANDED
- One 451-byte row: a `resolved` event for `backend:github_runner@20261122T2028Z` at 2026-11-22T21:00:46Z (14 units route here, none due; idle is correct).
- The run's `land` job was `cancelled` (step "Land the incident ledger"), so the row never reached main. Main held the matching `escalated` row and a later `resolved` at 21:32:18Z, not this one (checked with `grep -c` on the incident id: 2 rows, neither at 21:00:46Z).
- Landed into `comms/research/ops/watchdog_incidents.jsonl` as the workflow would (idempotent by line), inserted in timestamp order. The row has no secrets, IPs or balances.

## 2. `research-store-bundle`, run 45094782352 (expires 2026-11-26T01:34Z) — SAFE TO LOSE
- A 7 KB `rs-bundle.tgz`: 50 `grade` events for 50 units (`meta.json` `payloads: 0`), the hand-off between two jobs of `research-queue-grade.yml`.
- Its durable landing happened: job `research-store` concluded `success`. The `grade` job step "Land the dispositions on main" failed (as in run 43689172680, see [that disposition](loss-disposition-research-store-bundle-43689172680.md)).
- The grades are a pure function of committed results: all 50 unit directories exist under `research/results/` on main, so later grade runs recompute them.
- The bundle was not committed (grade events carry derived summaries only; no need to duplicate a trainer-store payload in a public repo).
- Recurring class: the detector cannot see a trainer-store landing, so it re-flags every failed-land grade run. Same follow-up as the 43689172680 note (teach question C the `research-store` job outcome); not re-filed here.
