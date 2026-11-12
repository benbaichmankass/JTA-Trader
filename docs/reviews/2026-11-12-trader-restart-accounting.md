> **Doc status:** `live` · category `evidence` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

# ict-trader-live restart accounting, 2026-11-11T14:59Z .. 2026-11-12T10:45Z (row TRADER-RESTART-ACCOUNTING-1112)

**Population:** every `Stopping`/`Started ICT Trader Live` pair in the live VM's `ict-trader-live` journal in the window, read through
`journalctl` windows that each returned `read_state: complete` (a first, wider read hit its time budget and was discarded as a lower
bound). Causes come from the `ict-git-sync` journal (the `sudo systemctl restart ict-trader-live` line and the `Trader restart gate` line) and
the `system-actions` workflow run list. Read-only, Tier 1.

## Result

- **36 restarts, not ~10** (MEASURED). The VENUE-KLINE count of about 10 distinct PIDs undercounted.
- **None between 14:59Z and 18:11Z** (window read complete, 0 stops). The first is 18:11:18Z; the last in the window 10:41:52Z.
- **Every stop is a clean SIGTERM** (`Deactivated successfully`; the trader logs `SIGTERM: final exit pass recorded`). **0 crashes, 0 OOM, 0 non-zero
  exits, 0 watchdog restarts** (the liveness watchdog ran every 60 s and issued no restart; `LIVENESS_AUTO_RESTART_AFTER` is opt-in).
- **Cause:** 34 by `ict-git-sync` deploys (each has a `sudo systemctl restart` line within 3 s of the stop and a `Trader restart gate: restart (...)`
  line naming the closure files); 2 by the `system-actions` `pull-and-deploy` workflow racing git-sync. **Unexplained: 0.**
- **Cost** (MEASURED, n=35 boots that ticked): stop to first `Tick result` mean 75 s, min 47 s, max 132 s; the 03:43:24Z boot was killed 24 s in by
  the next restart and never ticked. About 36 x 75 s = 45 min of no ticking in 18.5 h (about 4%).
- **Bars at a boundary:** 1 of 36 blind windows spanned a 15-minute boundary (06:30:00Z restart, first tick 06:31:04Z); none spanned an hour
  boundary. Whether that bar was actually missed or caught up on boot is **UNVERIFIED** (not read).

## Table (start time Z, cause, first tick after start)

| Start | Cause | First tick |
|---|---|---|
| 11-11 18:11:20 | git-sync deploy | 127 s |
| 18:58:11 | git-sync deploy | 95 s |
| 19:54:41 | git-sync deploy | 95 s |
| 20:33:38 | git-sync deploy | 95 s |
| 20:40:10 | git-sync deploy | 103 s |
| 21:10:32 | git-sync deploy | 76 s |
| 21:23:51 | git-sync deploy | 79 s |
| 22:00:16 | git-sync deploy | 74 s |
| 22:21:36 | git-sync deploy | 87 s |
| 23:22:27 | git-sync deploy | 97 s |
| 23:40:29 | git-sync deploy | 132 s |
| 23:54:21 | git-sync deploy | 94 s |
| 11-12 00:01:28 | git-sync deploy | 47 s |
| 00:16:36 | git-sync deploy | 50 s |
| 00:55:41 | git-sync deploy | 79 s |
| 01:05:11 | git-sync deploy | 84 s |
| 01:42:14 | git-sync deploy | 80 s |
| 01:49:42 | git-sync deploy | 54 s |
| 02:03:57 | git-sync deploy | 97 s |
| **02:56:40** | **system-action pull-and-deploy (run 9133, deploys b861f68); git-sync's gate then logged "already deployed" and skipped** | 51 s |
| 03:17:47 | git-sync deploy | 57 s |
| 03:24:08 | git-sync deploy | 79 s |
| 03:30:48 | git-sync deploy | 56 s |
| **03:43:24** | **system-action pull-and-deploy (run at 03:39:17Z, deploys c26311c); git-sync then restarted again 24 s later** | never (killed) |
| 03:43:48 | git-sync deploy (c26311c) | 56 s |
| 03:49:48 | git-sync deploy | 57 s |
| 04:26:52 | git-sync deploy | 74 s |
| 06:17:57 | git-sync deploy | 83 s |
| 06:30:03 | git-sync deploy | 61 s |
| 08:08:47 | git-sync deploy | 60 s |
| 08:54:41 | git-sync deploy | 55 s |
| 09:17:49 | git-sync deploy | 58 s |
| 09:43:43 | git-sync deploy | 56 s |
| 10:08:20 | git-sync deploy | 59 s |
| 10:19:22 | git-sync deploy (8a6feab) | 55 s |
| 10:41:55 | git-sync deploy | 57 s |

Sha per git-sync restart is in the `ict-git-sync` journal (`Post-sync HEAD`, same tick); not repeated here.

## Findings

1. **Two deploy paths restart the same unit.** A `pull-and-deploy` system-action and the 5-minute git-sync can both restart on one change; at
   03:43 that cost a full extra restart and one boot that never ticked. Filed as `TRADER-DEPLOY-DOUBLE-RESTART`.
2. **Restart cadence is a deploy-cadence cost, not instability:** 34 of 36 are single deploys. Each costs a median of about 1 min of no ticking while
   positions keep their venue SL/TP. Whether batching deploys (or a quiet window around bar closes) is worth it is a Tier-2 choice; filed in the same row.
3. Boundary catch-up on boot is unread (UNVERIFIED); included in the same row as its check.
