# GH-CAPACITY-INFRA-RUNNER URGENT: jta-infra jobs queued with no runner pickup (system-actions 41652871656 flatten retry).
echo "== BEFORE $(date -u +%FT%TZ)"; df -h / | tail -1; free -m | sed -n 2p; uptime
for i in 1 2 3 4; do u=actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service
  echo "-- runner $i: $(systemctl is-active $u) du=$(sudo -n du -sh /opt/actions-runner/ghr$i/_work 2>/dev/null | cut -f1) workers=$(pgrep -u ghr$i -fc Runner.Worker)"
  sudo -n journalctl -u $u --since "2026-11-03 14:00" --no-pager 2>/dev/null | tail -8
done
f=$(sudo -n bash -c 'ls -t /opt/actions-runner/ghr4/_diag/Worker_*.log 2>/dev/null | head -1'); echo "worker log: $f"
[ -n "$f" ] && sudo -n grep -iE 'error|exception|space|timeout|fatal|git ' "$f" | tail -25
f=$(sudo -n bash -c 'ls -t /opt/actions-runner/ghr4/_diag/Runner_*.log 2>/dev/null | head -1'); [ -n "$f" ] && sudo -n tail -25 "$f"
sudo -n dmesg 2>/dev/null | grep -iE 'oom|no space|killed process' | tail -5
echo "== REMEDIATE"
avail=$(df --output=avail -k / | tail -1)
for i in 1 2 3 4; do sudo -n find /opt/actions-runner/ghr$i/_work/JTA-Trader -mindepth 1 -maxdepth 2 -exec rm -rf {} + 2>/dev/null; done
echo "freed workspaces (avail before ${avail} KB)"
sudo -n systemctl restart $(systemctl list-units --all --no-legend 'actions.runner.*' | awk '{print $1}')
sleep 20
echo "== AFTER"; df -h / | tail -1
for i in 1 2 3 4; do echo "runner $i: $(systemctl is-active actions.runner.benbaichmankass-JTA-Trader.trainer-jta-infra-$i.service)"; done
