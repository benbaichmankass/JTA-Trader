# PI-20261103-RAM7EH86-0004 step 0: trainer free disk BEFORE re-install (floor 15 GB).
df -h / | tail -1; df --output=avail -k / | tail -1 | awk '{printf "avail_gb=%.1f\n", $1/1048576}'
for i in 1 2 3 4; do echo "runner $i: $(systemctl is-active actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)/$(systemctl is-enabled actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service) du=$(sudo -n du -sh /opt/actions-runner/ghr$i/_work 2>/dev/null|cut -f1)"; done
grep -c 'rm -rf "/opt/actions-runner' /usr/local/bin/jta-runner-job-cleanup.sh
