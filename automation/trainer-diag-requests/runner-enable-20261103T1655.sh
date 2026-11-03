# PI-20261103-RAM7EH86-0004: smoke green 16:48Z; enable runners 1-2 at boot (they were disabled 14:31Z). 3-4 stay disabled.
for i in 1 2; do u=actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service; sudo -n systemctl enable "$u" 2>&1 | tail -1; echo "$u $(systemctl is-active $u)/$(systemctl is-enabled $u)"; done
for i in 3 4; do echo "runner $i $(systemctl is-active actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)/$(systemctl is-enabled actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)"; done
df --output=avail -k / | tail -1 | awk '{printf "avail_gb=%.1f\n", $1/1048576}'
