#!/usr/bin/env bash
# security-posture-report — Tier-1, READ-ONLY host security posture.
#
# Row SEC-VM-POSTURE-READ (parent SECURITY-HARDENING-AUDIT). The system-actions
# workflow runs this on the live trader VM AND on the IB gateway, piping it over
# ssh stdin (`bash -s`) so it needs no checkout on either host.
#
# It reports: listening sockets, sshd EFFECTIVE config (selected keys), fail2ban
# jails and ban COUNTS, pending updates, reboot-required, users with a login
# shell, a sudoers summary, authorized_keys FINGERPRINTS, and the modes of the
# secret-bearing files we know about.
#
# It NEVER prints secret values or key material. The output is posted to an
# issue on a PUBLIC repo, so:
#   * every IPv4 address and IBKR account id is masked (mask());
#   * authorized_keys lines are reduced to "<bits> <SHA256 fingerprint> <type>"
#     — the key body and its comment (often user@host) are never printed;
#   * fail2ban prints counts, never the banned addresses;
#   * secret files are stat()ed (mode, owner, size), never read.
# It changes nothing: no writes, no restarts, no package operations. Each
# section is independent; a section that cannot read says so and the next
# one still runs (no halting).
set -euo pipefail

# Piped over ssh stdin, so there is no BASH_SOURCE dir: source the shared lib
# only where a checkout exists (the trader; the gateway may have none).
# Nothing below needs it; this keeps the wrapper conventions uniform.
REPO_DIR="${REPO_DIR:-/home/ubuntu/ict-trading-bot}"
if [ -f "${REPO_DIR}/scripts/ops/_lib.sh" ]; then
  # shellcheck source=scripts/ops/_lib.sh
  source "${REPO_DIR}/scripts/ops/_lib.sh" || true
fi
# The report body runs with -e OFF on purpose: every section is a separate
# read, and one unreadable section (no sudo for sshd -T, fail2ban absent) must
# not stop the rest (Prime Directive rule 7, no halting). -u and pipefail stay.
set +e

mask() {
  # Wildcard and loopback binds are kept: whether a port listens on every
  # interface or only locally IS the finding, and neither address identifies
  # a host. Every other IPv4 address is masked (public repo).
  sed -E 's/(^|[^0-9.])0\.0\.0\.0([^0-9]|$)/\1@ANY4@\2/g; s/(^|[^0-9.])127\.0\.0\.(1|53|54)([^0-9]|$)/\1@LO4\2@\3/g' \
    | sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<ip>/g; s/\b(DU|DF|U)[0-9]{5,}\b/<acct>/g' \
    | sed -E 's/@ANY4@/0.0.0.0/g; s/@LO4([0-9]+)@/127.0.0.\1/g'
}
hdr() { printf '\n===== %s =====\n' "$1"; }
SUDO="sudo -n"

{
hdr "host"
echo "role: ${POSTURE_ROLE:-unknown}"
date -u +%Y-%m-%dT%H:%M:%SZ
. /etc/os-release 2>/dev/null && echo "os: ${PRETTY_NAME:-?}"
echo "kernel: $(uname -r)"
echo "uptime: $(uptime -p 2>/dev/null || true)"

hdr "listening sockets (tcp+udp, addresses masked)"
if $SUDO ss -H -tulnp >/dev/null 2>&1; then
  $SUDO ss -H -tulnp 2>/dev/null \
    | awk '{proc=$7; sub(/.*users:\(\("/,"",proc); sub(/".*/,"",proc); print $1, $5, proc}' \
    | sort -u
else
  ss -H -tuln 2>/dev/null | awk '{print $1, $5, "(process names need sudo)"}' | sort -u
fi

hdr "sshd effective config (sshd -T, selected keys)"
if out=$($SUDO sshd -T 2>/dev/null); then
  echo "$out" | grep -Ei '^(port|listenaddress|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|challengeresponseauthentication|pubkeyauthentication|authenticationmethods|permitemptypasswords|maxauthtries|maxsessions|logingracetime|allowusers|allowgroups|denyusers|x11forwarding|allowtcpforwarding|allowagentforwarding|permittunnel|gatewayports|usepam|loglevel|clientaliveinterval|clientalivecountmax) ' \
    | sort
else
  echo "UNREADABLE: sudo -n sshd -T failed (no passwordless sudo for sshd?)"
fi

hdr "fail2ban"
if command -v fail2ban-client >/dev/null 2>&1; then
  echo "service: $(systemctl is-active fail2ban 2>/dev/null || echo unknown)"
  jails=$($SUDO fail2ban-client status 2>/dev/null | sed -n 's/.*Jail list:[[:space:]]*//p' | tr ',' ' ')
  if [ -z "${jails// }" ]; then
    echo "jails: none readable (not running, or no sudo)"
  fi
  for j in $jails; do
    st=$($SUDO fail2ban-client status "$j" 2>/dev/null)
    cf=$(echo "$st" | sed -n 's/.*Currently failed:[[:space:]]*//p')
    tf=$(echo "$st" | sed -n 's/.*Total failed:[[:space:]]*//p')
    cb=$(echo "$st" | sed -n 's/.*Currently banned:[[:space:]]*//p')
    tb=$(echo "$st" | sed -n 's/.*Total banned:[[:space:]]*//p')
    echo "jail=$j currently_failed=${cf:-?} total_failed=${tf:-?} currently_banned=${cb:-?} total_banned=${tb:-?}"
  done
else
  echo "NOT INSTALLED"
fi

hdr "pending updates"
if [ -x /usr/lib/update-notifier/apt-check ]; then
  ac=$(/usr/lib/update-notifier/apt-check 2>&1 >/dev/null)
  echo "apt-check (all;security): ${ac:-?}"
fi
n_up=$(apt list --upgradable 2>/dev/null | grep -c 'upgradable from' || true)
echo "apt list --upgradable (from the cached index): ${n_up}"
echo "apt cache built: $(stat -c %y /var/cache/apt/pkgcache.bin 2>/dev/null || echo "?")"
uu_en=$(systemctl is-enabled unattended-upgrades 2>/dev/null || true)
uu_ac=$(systemctl is-active unattended-upgrades 2>/dev/null || true)
echo "unattended-upgrades: enabled=${uu_en:-absent} active=${uu_ac:-?}"
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
  grep -v '^\s*//' /etc/apt/apt.conf.d/20auto-upgrades | grep -v '^\s*$' | sed 's/^/  /'
fi

hdr "reboot required"
if [ -f /var/run/reboot-required ]; then
  echo "YES"
  n_pk=$(wc -l < /var/run/reboot-required.pkgs 2>/dev/null || echo 0)
  echo "packages asking: ${n_pk}"
  head -n 20 /var/run/reboot-required.pkgs 2>/dev/null | sed 's/^/  /'
else
  echo "no"
fi

hdr "users with a login shell"
awk -F: '$7 !~ /(nologin|false|sync|shutdown|halt)$/ {print $1, "uid="$3, "shell="$7}' /etc/passwd
echo "uid 0 accounts: $(awk -F: '$3==0{print $1}' /etc/passwd | tr '\n' ' ')"
echo "accounts with a usable password hash: $($SUDO awk -F: '$2 ~ /^\$/ {n++} END{print n+0}' /etc/shadow 2>/dev/null || echo UNREADABLE)"

hdr "sudoers summary (comments and Defaults dropped)"
# /etc/sudoers.d is 0750 root: a plain glob cannot list it as the service
# user, so list it with sudo (the D3 file watch counts 5 files there).
sudoers_d=$($SUDO find /etc/sudoers.d -maxdepth 1 -type f 2>/dev/null | sort)
for f in /etc/sudoers $sudoers_d; do
  $SUDO test -e "$f" 2>/dev/null || continue
  echo "-- $f ($($SUDO stat -c '%a %U:%G' "$f" 2>/dev/null))"
  if body=$($SUDO cat "$f" 2>/dev/null); then
    echo "$body" | grep -Ev '^\s*(#|$|Defaults)' | sed 's/^/  /'
  else
    echo "  UNREADABLE"
  fi
done
echo "sudo group: $(getent group sudo | cut -d: -f4)"

hdr "authorized_keys (fingerprints only; key bodies and comments never printed)"
while IFS=: read -r user _ _ _ _ home shell; do
  case "$shell" in *nologin|*false) continue ;; esac
  for f in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
    if $SUDO test -e "$f" 2>/dev/null; then
      meta=$($SUDO stat -c '%a %U:%G' "$f" 2>/dev/null)
      n=$($SUDO grep -cEv '^\s*(#|$)' "$f" 2>/dev/null || echo '?')
      echo "-- user=$user file=$f mode=$meta keys=$n"
      opts=$($SUDO grep -cE '^(from=|command=|restrict|no-)' "$f" 2>/dev/null || true)
      echo "   lines with options (from=/command=/restrict): ${opts:-0}"
      $SUDO cat "$f" 2>/dev/null | grep -Ev '^\s*(#|$)' | while read -r line; do
        fp=$(printf '%s\n' "$line" | ssh-keygen -lf - 2>/dev/null)
        # "<bits> SHA256:<fp> <comment...> (<TYPE>)" -> drop the comment
        if [ -n "$fp" ]; then
          echo "   $(echo "$fp" | awk '{print $1, $2, $NF}')"
        else
          echo "   (line not parseable as a public key)"
        fi
      done
    fi
  done
done < /etc/passwd

hdr "secret-bearing files (stat only, never read)"
for f in /home/ubuntu/ict-trading-bot/.env /opt/ict-trading-bot/.env \
         /home/ubuntu/ict-trading-bot/config/.env /etc/ict-trading-bot/env \
         /home/ubuntu/.ssh/id_rsa /home/ubuntu/.ssh/id_ed25519; do
  if $SUDO test -e "$f" 2>/dev/null; then
    echo "$f $($SUDO stat -c 'mode=%a owner=%U:%G size=%s' "$f" 2>/dev/null)"
  fi
done
for d in /home/ubuntu/secrets /home/ubuntu/.config/gcloud /home/ubuntu/ict-trading-bot/secrets; do
  if $SUDO test -d "$d" 2>/dev/null; then
    echo "$d (dir $($SUDO stat -c '%a %U:%G' "$d")): $($SUDO find "$d" -maxdepth 2 -type f 2>/dev/null | wc -l) files;" \
         "world-readable: $($SUDO find "$d" -maxdepth 2 -type f -perm -o+r 2>/dev/null | wc -l)"
  fi
done

hdr "firewall"
if command -v ufw >/dev/null 2>&1; then
  echo "ufw: $($SUDO ufw status 2>/dev/null | head -n1 || echo UNREADABLE)"
fi
echo "iptables INPUT policy: $($SUDO iptables -S INPUT 2>/dev/null | head -n1 || echo UNREADABLE)"
echo "iptables INPUT rules: $($SUDO iptables -S INPUT 2>/dev/null | grep -c '^-A' || true)"

hdr "end"
} 2>&1 | mask

exit 0
