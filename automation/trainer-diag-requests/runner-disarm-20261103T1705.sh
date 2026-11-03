# PI-20261103-RAM7EH86-0004 FAILED the disk floor (13.2 GB free during one ~6 GB clone; floor 15 GB "throughout").
# Disable at boot NOW; stop each runner only once it has no Runner.Worker (let the in-flight research dispatch finish).
for i in 1 2; do u=actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service; sudo -n systemctl disable "$u" >/dev/null 2>&1; done
for t in $(seq 1 50); do
  busy=0
  for i in 1 2; do u=actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service
    if pgrep -u ghr$i -f Runner.Worker >/dev/null; then busy=1; elif systemctl is-active -q $u; then sudo -n systemctl stop $u; echo "$(date -u +%TZ) stopped runner $i"; fi
  done
  [ $busy = 0 ] && break; sleep 30
done
for i in 1 2 3 4; do echo "runner $i: $(systemctl is-active actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)/$(systemctl is-enabled actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)"; done
df --output=avail -k / | tail -1 | awk '{printf "avail_gb=%.1f\n", $1/1048576}'
