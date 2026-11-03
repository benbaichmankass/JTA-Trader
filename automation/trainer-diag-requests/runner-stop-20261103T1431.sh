# Operator-approved (popup ~14:28Z via manager): self-hosted OFF until fix + green smoke. Stop + disable all jta-infra runners.
for u in $(systemctl list-units --all --no-legend 'actions.runner.*' | awk '{print $1}'); do
  sudo -n systemctl disable --now "$u" 2>&1 | tail -1; echo "$u -> $(systemctl is-active "$u") / $(systemctl is-enabled "$u")"
done
for i in 1 2 3 4; do sudo -n rm -rf /opt/actions-runner/ghr$i/_work/JTA-Trader 2>/dev/null; done
pgrep -fa 'Runner.(Listener|Worker)' || echo "no runner processes"
df -h / | tail -1
