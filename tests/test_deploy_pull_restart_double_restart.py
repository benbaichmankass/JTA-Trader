"""TRADER-DEPLOY-DOUBLE-RESTART — one deploy batch restarts the trader at most once.

ict-git-sync and the pull-and-deploy system action both run
``scripts/deploy_pull_restart.sh``. The trader deploy marker is written only
AFTER the restart, so two overlapping runs both read a stale marker and both
bounced the trader. The fix is a dedupe on the deployed sha (a non-blocking lock
across restart + marker), not a delay, wait or gate.

Reuses the fake-VM fixture from test_deploy_pull_restart_trader_gate.py, with a
per-process git stub (so two concurrent runs each see old -> new) and a trader
``systemctl restart`` slow enough that the two runs reliably overlap.
"""
from __future__ import annotations

import os
import subprocess
import time

from tests.test_deploy_pull_restart_trader_gate import (  # noqa: F401 (fixture)
    TRADER, _restarted, _stub, _with_trader_marker, fake,
)


def _concurrent_setup(fake, tmp_path):
    counters = tmp_path / "counters"
    counters.mkdir()
    # per-run counter keyed on RUN_ID (set per spawned deploy run)
    _stub(fake["bindir"] / "git", f"""#!/bin/bash
case "$1" in
  rev-parse)
    if [ "$2" = "-q" ]; then exit 0; fi
    if [ "$2" = "--short" ]; then echo newsha8; exit 0; fi
    f="{counters}/$RUN_ID"
    if [ ! -e "$f" ]; then echo oldsha7; : > "$f"; else echo newsha8; fi ;;
  diff) echo src/core.py ;;
  *) exit 0 ;;
esac
""")
    log = fake["restart_log"]
    # a trader restart takes ~1.5 s, like a real stop+start; the marker is written after it
    _stub(fake["bindir"] / "systemctl", f"""#!/bin/bash
case "$1" in
  --version) echo "systemd 250" ;;
  list-units)
    if [[ "${{*: -1}}" == "ict-*.service" ]]; then
      printf '%s\\n' "{TRADER} loaded active running x"
    fi ;;
  restart) echo "$2" >> "{log}"; [ "$2" = "{TRADER}" ] && sleep 1.5; exit 0 ;;
  is-active) echo active ;;
  *) exit 0 ;;
esac
""")


_RUNS = iter(range(1, 1000))


def _spawn(fake, **extra):
    env = {**os.environ, "PATH": f"{fake['bindir']}:/usr/bin:/bin", "RUN_ID": str(next(_RUNS)), **extra}
    return subprocess.Popen(["bash", str(fake["deploy"])], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)


def test_two_overlapping_deploy_runs_restart_the_trader_once(fake, tmp_path):
    _concurrent_setup(fake, tmp_path)
    _with_trader_marker(fake)
    a = _spawn(fake)
    time.sleep(0.3)  # b arrives while a is mid-restart, marker still stale
    b = _spawn(fake)
    out_a, out_b = a.communicate(timeout=60)[0], b.communicate(timeout=60)[0]
    assert a.returncode == 0, out_a
    assert b.returncode == 0, out_b
    assert _restarted(fake).count(TRADER) == 1, (_restarted(fake), out_a, out_b)
    assert fake["trader_marker"].read_text().strip() == "newsha8"


def test_a_second_run_after_the_first_finished_does_not_restart(fake, tmp_path):
    _concurrent_setup(fake, tmp_path)
    _with_trader_marker(fake)
    a = _spawn(fake)
    oa = a.communicate(timeout=60)[0]
    b = _spawn(fake)
    ob = b.communicate(timeout=60)[0]
    print(oa[-1500:], ob[-800:])
    assert _restarted(fake).count(TRADER) == 1


def test_lock_is_released_so_a_later_deploy_batch_restarts_again(fake, tmp_path):
    _concurrent_setup(fake, tmp_path)
    _with_trader_marker(fake)
    _spawn(fake).communicate(timeout=60)
    assert _restarted(fake).count(TRADER) == 1
    # a NEW deploy batch: the markers say the units run an older sha again
    fake["trader_marker"].write_text("tradersha1\n")
    fake["marker"].write_text("tradersha1\n")
    out = _spawn(fake).communicate(timeout=60)[0]
    assert _restarted(fake).count(TRADER) == 2, out
