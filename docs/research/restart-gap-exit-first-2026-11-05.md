# Restart gap: exit loop first (RESTART-GAP-EXIT-FIRST, 2026-11-05)

> **Doc status:** `live` · category `evidence` · lane `RESTART-GAP-EXIT-FIRST` (Manager Session 2026-11-05a)

**Gates this adds or changes: none.**

## The measurement (the 10:58Z restart, exit restart gap 64.1 s vs the 60 s requirement)

MEASURED by this lane from relay #23271 (vm-diag-snapshot run 42016072052, `journalctl` of
`ict-trader-live`, window 10:57:20Z–10:58:40Z, read_state `complete`, 10 of 451 lines matched):

| time (UTC) | event | delta |
|---|---|---|
| 10:57:55 | systemd stop + start (`Stopping` → `Started` in the same second) | (b) < 1 s |
| 10:57:56.911 | `trade journal: WAL mode active` | (c) ~1.9 s |
| 10:58:10.347 | `boot_audit: restart report` (main() joins this thread before the exit loop) | (d) 13.4 s |
| 10:58:19.384 | `exit-evaluation loop DECOUPLED onto its own thread` | (e) 9.0 s |

Boot to exit thread ≈ 23.5 s, of which 22.4 s (d + e) is init the exit pass does not use.

Relayed by lane TICK-STAGE2 (relay #23266), NOT re-measured by this lane: (a) 26.2 s pre-stop idle (the
old exit loop was asleep between passes when stopped) and (f) a 13.5 s cold first pass (steady ~1 s).
Cross-check: 26.2 + 0.5 + 1.9 + 13.4 + 9.0 + 13.5 = 64.5 s ≈ the graded 64.1 s.

## The change

1. `src/main.py::main()` starts the exit loop right after `enable_wal_mode()`, before the restart-report
   join, the strategy_versions snapshot, leverage and the adapter/telegram build. Removes (d) + (e).
2. A SIGTERM handler lets the exit loop run ONE final pass (bounded 20 s), then re-raises SIGTERM with the
   default disposition, so systemd records the same exit. Removes (a). Rollback:
   `EXIT_LOOP_FINAL_PASS_DISABLED=1` + restart.
3. `deploy/trainer/` joins the non-runtime set in all three lockstep copies, so a trainer-only file no
   longer restarts the trader (the 10:58Z restart was forced by `deploy/trainer/Caddyfile.console` alone).

INFERRED next gap: ≈ stop (<1 s) + WAL (1.9 s) + cold first pass (13.5 s, possibly slower while the
report/leverage threads run beside it) ≈ 16–25 s, against the 45 s target. Without (2) the worst case is
~30 s idle + the same ≈ 46–55 s, which is why (2) is in.

## What the first pass needs, and why it is ready

The exit pass reads `accounts.yaml`/`strategies.yaml` and opens the journal itself each pass, and builds
its broker clients per pass from `accounts.yaml` + env (`_build_account_client`,
`_build_monitor_ohlcv_fetcher`). It never uses `exchange_client`, `telegram_client`, or leverage. It
therefore ACTS from the first pass. A broker not yet reachable gives `candles=None` and the per-pass retry.

IB: the restart report reads through `ib_read_client_for` (clientId 9000+pid, its own `IBClient` and
`_usage_lock`). The pinned `_IB_FETCH_EXECUTOR` serves only `IBMarketData.get_ohlcv` (clientId exec+1).
So the two do not queue against each other.

## Known side effects (stated, accepted)

- A close that lands while the restart report is reconciling can show one ghost/untracked line in that
  ping. It has no effect on trading or the next reconcile.
- With the handler installed, SIGTERM is handled between bytecodes on the main thread. A main thread stuck
  inside a C call that never returns now waits for systemd's TimeoutStopSec (90 s) SIGKILL instead of
  dying at once. Python-level waits (sleep, locks, futures, sockets) are interrupted, so the handler runs
  promptly.
- Stop takes up to one pass longer (≈1 s steady; bounded at 20 s).

## Observe (closes the row)

The next trader restart after deploy: the `exit restart gap` log line / `/api/bot/exit-interval/soak`
restart gap reads < 45000 ms, and `/api/bot/alerts` carries no `EXIT-EVAL RESTART GAP BREACHED`.
