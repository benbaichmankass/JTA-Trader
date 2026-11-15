#!/usr/bin/env bash
# Tier-2 system-action `close-api-port` (SEC-8001-LOCKDOWN step 3).
#
# Operator decisions page m3, 2026-11-12: "Lock it down: move those three clients
# to HTTPS, then bind 8001 to localhost and drop its firewall rule".
#
# Removes the HOST firewall's ACCEPT rules for TCP/8001 (iptables + ip6tables,
# and ufw if it is active), then persists the rule set. Fixed port, no
# parameters. Nothing else is touched: not 22/80/443, not the chain policy,
# not the OCI security list (cloud-side; there is no write path from here).
#
# REFUSES (exit 3, no change) unless ict-web-api already listens on 127.0.0.1
# ONLY. The rule order matters: close the firewall after the bind change has
# deployed, never instead of it, and never while the API is unbound.
#
# Every IPv4 address in the output is masked except 0.0.0.0 and 127.0.0.1,
# because the output is posted to a public issue. Revert: the vm-net-fix
# workflow re-adds the rule (it opens port 8001 by default).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh" || true
# -e OFF for the body on purpose: every step reports its own result and one
# failed delete must not hide the rest (the AFTER read always prints).
set +e

PORT=8001
SUDO="sudo -n"

mask() {
  sed -E 's/(^|[^0-9.])0\.0\.0\.0([^0-9]|$)/\1@ANY4@\2/g; s/(^|[^0-9.])127\.0\.0\.1([^0-9]|$)/\1@LO4@\2/g' \
    | sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<ip>/g' \
    | sed -E 's/@ANY4@/0.0.0.0/g; s/@LO4@/127.0.0.1/g'
}
hdr() { printf '\n===== %s =====\n' "$1"; }

port_rules() {  # $1 = iptables | ip6tables -> the -A rules that ACCEPT tcp dport $PORT
  $SUDO "$1" -S INPUT 2>/dev/null | grep -E '^-A INPUT ' | grep -E -- "--dport ${PORT}( |$)" | grep -E -- '-j ACCEPT( |$)' || true
}

{
hdr "precondition: :${PORT} listens on loopback only"
listeners="$(ss -Htln "sport = :${PORT}" 2>/dev/null | awk '{print $4}')"
echo "${listeners:-(nothing listening on :${PORT})}"
if [ -z "${listeners}" ]; then
  echo "REFUSED: nothing listens on :${PORT}. Is ict-web-api up? No change made."
  exit 3
fi
if printf '%s\n' "${listeners}" | grep -qvE "^(127\.0\.0\.1|\[::1\]):${PORT}$"; then
  echo "REFUSED: :${PORT} is still bound to a non-loopback address. Deploy the 127.0.0.1 bind first. No change made."
  exit 3
fi
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:${PORT}/api/health" || true)"
echo "loopback /api/health: http=${code}"

hdr "host firewall rules for :${PORT} BEFORE"
for t in iptables ip6tables; do echo "-- ${t}"; port_rules "$t" | sed 's/^/  /'; done
ufw_state="$($SUDO ufw status 2>/dev/null | head -n1 || true)"
echo "-- ufw: ${ufw_state:-unreadable}"

hdr "removing"
removed=0
for t in iptables ip6tables; do
  while IFS= read -r rule; do
    [ -n "${rule}" ] || continue
    # shellcheck disable=SC2086  # the rule spec must word-split back into arguments
    if $SUDO "$t" ${rule/#-A /-D }; then
      echo "${t}: deleted: ${rule}"
      removed=$((removed + 1))
    else
      echo "${t}: FAILED to delete: ${rule}"
    fi
  done < <(port_rules "$t")
done
case "${ufw_state}" in
  *"Status: active"*) $SUDO ufw --force delete allow "${PORT}/tcp" 2>&1 | sed 's/^/ufw: /' ;;
  *) echo "ufw: not active, nothing to delete" ;;
esac
echo "rules removed: ${removed}"

hdr "persist"
if [ "${removed}" -gt 0 ]; then
  $SUDO netfilter-persistent save 2>&1 \
    || { $SUDO sh -c 'iptables-save > /etc/iptables/rules.v4 && ip6tables-save > /etc/iptables/rules.v6' 2>&1 && echo "saved via iptables-save"; } \
    || echo "WARNING: could not persist; the change is live but a reboot restores the rule"
else
  echo "nothing removed, nothing to persist"
fi

hdr "AFTER"
for t in iptables ip6tables; do
  left="$(port_rules "$t")"
  echo "-- ${t}: ${left:-no ACCEPT rule for :${PORT}}"
done
echo "loopback /api/health: http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:${PORT}/api/health" || true)"
echo "https front /api/health: http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://ict-bot.duckdns.org/api/health || true)"
echo "reminder: the OCI security list may still allow ${PORT}; it is cloud-side and has no write path here."
} 2>&1 | mask
exit "${PIPESTATUS[0]}"
