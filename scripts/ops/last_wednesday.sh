#!/usr/bin/env bash
# wiring: .github/workflows/reset-protocol-backup.yml (RESET_DATE), tests/test_reset_protocol_backup_date.py
# Prints the UTC date (YYYY-MM-DD) of the most recent Wednesday <= now (today if today is Wednesday).
# WHY: a delayed `0 19 * * 3` cron run crossed midnight UTC (run 41938013770) and "today" was Thursday,
# so the backup graded the wrong reset and posted a false RED-FLAG. Optional arg: a `date -d` timestamp (tests).
set -euo pipefail
NOW="${1:-now}"
dow="$(date -u -d "$NOW" +%u)"            # 1=Mon .. 3=Wed .. 7=Sun
back=$(( (dow - 3 + 7) % 7 ))
date -u -d "$NOW -${back} days" +%Y-%m-%d
