#!/usr/bin/env python3
"""VM-CONTROL-1127: separate CPU starvation from venue/network latency on the live VM. Read-only.

Prints, each with its population:
  1. scheduler latency -- 200 x ``sleep(10 ms)``; the overshoot is time spent waiting for a CPU (run-queue delay).
     An idle box overshoots by well under 1 ms; a starved one by many ms.
  2. Bybit PUBLIC GET /v5/market/time from Python ``requests`` (mainnet + demo host), 3 each.
  3. Bybit PRIVATE ``get_positions(settleCoin=USDT)`` -- the exact call ``account_open_positions`` makes -- 3 per Bybit
     account, timed. Prints elapsed seconds, retCode and the ROW COUNT only: no balances, sizes, prices or keys.

Writes nothing, places nothing, cancels nothing.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _q(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def sched_latency(n: int = 200, sleep_s: float = 0.010) -> None:
    over = []
    for _ in range(n):
        t0 = time.perf_counter()
        time.sleep(sleep_s)
        over.append((time.perf_counter() - t0 - sleep_s) * 1000.0)
    print(f"population: {n} sleeps of {sleep_s * 1000:.0f} ms (this probe process, default nice)")
    print(f"overshoot ms: median {statistics.median(over):.2f}  p90 {_q(over, 0.9):.2f}  "
          f"p99 {_q(over, 0.99):.2f}  max {max(over):.2f}")


def public_http() -> None:
    import requests
    for host in ("https://api.bybit.com", "https://api-demo.bybit.com"):
        for i in range(3):
            t0 = time.perf_counter()
            try:
                r = requests.get(f"{host}/v5/market/time", timeout=20)
                status = r.status_code
            except Exception as exc:  # noqa: BLE001  # allow-silent: a diagnostic probe; the failure IS the printed result
                status = f"error {type(exc).__name__}"
            print(f"{host} try {i + 1}: {time.perf_counter() - t0:.3f} s  status {status}")


def private_positions() -> None:
    from src.units.accounts.clients import bybit_client_for
    from src.units.accounts.execute import _bybit_category
    from src.units.ui.data_loaders import list_accounts

    accts = [a for a in (list_accounts() or []) if str((a or {}).get("exchange") or "").lower() == "bybit"]
    print(f"population: {len(accts)} Bybit accounts from list_accounts(), 3 calls each")
    for acc in accts:
        aid = acc.get("account_id")
        t0 = time.perf_counter()
        try:
            client = bybit_client_for(acc)
        except Exception as exc:  # noqa: BLE001  # allow-silent: diagnostic probe; printed
            print(f"{aid}: client build failed {type(exc).__name__}")
            continue
        build_s = time.perf_counter() - t0
        if client is None:
            print(f"{aid}: no credentials (could_not_look)")
            continue
        try:
            category = _bybit_category(acc)
        except Exception:  # noqa: BLE001  # allow-silent: diagnostic probe; falls back to the common category
            category = "linear"
        if category == "spot":
            print(f"{aid}: spot account, no position read (matches account_open_positions)")
            continue
        for i in range(3):
            t1 = time.perf_counter()
            try:
                resp = client.get_positions(category=category, settleCoin="USDT")
                rc = resp.get("retCode") if isinstance(resp, dict) else type(resp).__name__
                rows = len(((resp or {}).get("result") or {}).get("list") or []) if isinstance(resp, dict) else None
                out = f"retCode {rc} rows {rows}"
            except Exception as exc:  # noqa: BLE001  # allow-silent: diagnostic probe; the failure IS the printed result
                out = f"error {type(exc).__name__}: {str(exc)[:120]}"
            print(f"{aid} ({category}) try {i + 1}: {time.perf_counter() - t1:.3f} s  {out}"
                  + (f"  [client build {build_s:.3f} s]" if i == 0 else ""))


def main() -> int:
    for title, fn in (("scheduler latency (CPU run-queue wait)", sched_latency),
                      ("Bybit public HTTP from Python", public_http),
                      ("Bybit private get_positions (the account_open_positions call)", private_positions)):
        print(f"\n===== {title} =====")
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001  # allow-silent: one section failing must not hide the others; printed
            print(f"section failed: {type(exc).__name__}: {str(exc)[:200]}")
        print(f"(section took {time.perf_counter() - t0:.1f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
