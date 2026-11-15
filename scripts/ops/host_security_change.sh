#!/usr/bin/env bash
# host-security-change — Tier-2, RUNNER-SIDE orchestrator for the four host
# security changes approved on 2026-11-12 (operator decisions page m4, "Do all
# four now"; row SEC-HOST-CHANGES-1112; record
# docs/plans/thursday-planning-2026-11-12-answers.md).
#
# Runs on the GitHub runner inside system-actions.yml (like
# security-posture-report): every remote step goes over ssh from here, so no
# host needs this file on disk. Output is posted to a PUBLIC issue, so it never
# prints an IP address, a private key, a public-key body or a key comment —
# fingerprints only (SHA256, as the posture report already publishes).
#
# One `target:` per dispatch. Every mutating target is a DRY RUN unless
# `apply: true`; every one has a named revert target.
#
#   ssh-harden           trader + gateway: drop-in /etc/ssh/sshd_config.d/01-ict-hardening.conf
#                        (MaxAuthTries 3, X11Forwarding no, AllowAgentForwarding no;
#                        the trader also pins AllowTcpForwarding yes — the gateway
#                        is reached THROUGH it). sshd -t, reload (open sessions
#                        survive), sshd -T check, then a FRESH login (and, on the
#                        trader, a fresh ProxyJump to the gateway) is tested while
#                        the pre-change master connection is still open; a failed
#                        fresh login removes the drop-in over that master.
#   ssh-harden-revert    removes the drop-in on both hosts, reloads, re-tests.
#   fail2ban             trader only (the only host with a public sshd): installs
#                        fail2ban + /etc/fail2ban/jail.d/ict-sshd.local (sshd jail,
#                        maxretry 5 / findtime 10m / bantime 1h, incremental to 1w;
#                        ignoreip = loopback, the VCN 10.0.0.0/16 and the trainer,
#                        which hosts the self-hosted infra runner). Fresh login
#                        re-tested after start.
#   fail2ban-revert      stop + disable + purge fail2ban (its iptables chain goes with it).
#   gateway-reboot       IB gateway VM: pre-read, `systemctl reboot` (delayed 5 s so
#                        ssh returns), poll ssh up to 10 min, post-read (kernel,
#                        uptime, container, port 4002, watchdog/reset timers) and one
#                        dry-run ib_paper probe. Not revertible; recovery if ssh does
#                        not return is the OCI instance reset.
#   keys-survey          read-only: authorized_keys + private-key fingerprints for
#                        root/opc/ubuntu on trader, gateway and trainer.
#   keys-runner-rotate   new ed25519 key for the GitHub runners: appended to ubuntu's
#                        authorized_keys on trader, gateway, trainer (old key KEPT);
#                        fresh login with the new key ALONE verified on all three
#                        (gateway via a jump that also uses only the new key); only
#                        then secret VM_SSH_KEY_LEGACY := the current key and
#                        VM_SSH_KEY := the new key.
#   keys-runner-revert   VM_SSH_KEY := VM_SSH_KEY_LEGACY (the old key is still authorized).
#   keys-trainer-rotate  new ed25519 key generated ON the trainer for its trader pulls;
#                        public half appended to ubuntu@trader; verified from the trainer
#                        with that key alone; then the trainer's key file
#                        (~/.ssh/ict-bot-ovm-private.key, which its sync/mirror scripts
#                        read) is swapped for it, the old file kept as *.legacy-<ts>.
#   keys-trainer-revert  restores the newest *.legacy-* file on the trainer.
#   keys-retire-legacy   removes the shared legacy key from ubuntu's authorized_keys on
#                        all three hosts and deletes the trainer's legacy copy — refused
#                        unless the runner's current key is NOT the legacy key and logs
#                        in fresh everywhere, and the trainer's own key reaches the
#                        trader. Backups kept (authorized_keys.bak-<ts>); revert target
#                        keys-retire-legacy-revert restores them (with the new keys).
#
# Env: ACTION_TARGET, ACTION_APPLY, VM_SSH_USER, VM_SSH_HOST, GATEWAY_HOST,
#      TRAINER_IP, TRAINER_USER, SSH_KEY (default ~/.ssh/id_rsa), GH_TOKEN
#      (keys-runner-*: a PAT that can write Actions secrets), LEGACY_KEY_VALUE
#      (keys-runner-revert), GITHUB_REPOSITORY, RUNNER_TEMP.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if [ -f "${REPO_DIR}/scripts/ops/_lib.sh" ]; then
  # shellcheck source=scripts/ops/_lib.sh
  source "${REPO_DIR}/scripts/ops/_lib.sh" || true
fi
SCRIPT_NAME="host_security_change"
# -e OFF from here on purpose: a failed ssh inside $(...) must reach the
# explicit rollback branch, not abort the script half-way through a change
# (pipefail would turn every failed fresh-login probe into an exit). Every
# mutating step checks its own result. -u and pipefail stay.
set +e

TARGET="${ACTION_TARGET:-}"
APPLY="${ACTION_APPLY:-}"
U="${VM_SSH_USER:-ubuntu}"
TRADER="${VM_SSH_HOST:-}"  # job-level env on the runner (not forwarded to a VM)
[ -n "${TRADER}" ] || { echo "VM_SSH_HOST is empty (job env)"; exit 2; }
GW="${GATEWAY_HOST:-10.0.0.251}"
TRAINER="${TRAINER_IP:-}"
TU="${TRAINER_USER:-ubuntu}"
KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
TMP="${RUNNER_TEMP:-/tmp}/hsc.$$"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DROPIN="/etc/ssh/sshd_config.d/01-ict-hardening.conf"
JAIL="/etc/fail2ban/jail.d/ict-sshd.local"
TRAINER_KEYFILE=".ssh/ict-bot-ovm-private.key"
RUNNER_KEY_COMMENT="jta-gha-runner-${TS:0:8}"
TRAINER_KEY_COMMENT="jta-trainer-to-trader-${TS:0:8}"
mkdir -p "${TMP}"; chmod 700 "${TMP}"
trap 'for c in "${TMP}"/ctl-*; do [ -S "$c" ] && ssh -o ControlPath="$c" -O exit x 2>/dev/null; done; rm -rf "${TMP}"' EXIT

case "${APPLY}" in true) DRY=0 ;; ""|false) DRY=1 ;; *) echo "apply must be true or false (got '${APPLY}')"; exit 2 ;; esac
say() { printf '%s\n' "$*"; }
mask() { sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<ip>/g'; }
mode_line() { if [ "${DRY}" = 1 ]; then say "mode: DRY RUN (nothing changes; add 'apply: true')"; else say "mode: APPLY"; fi; }

BASE=( -i "${KEY}" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new
       -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o LogLevel=ERROR )
JUMP_CMD() { printf 'ssh -i %q -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o LogLevel=ERROR -W %%h:%%p %s@%s' "$1" "${U}" "${TRADER}"; }

# host_args <trader|gateway|trainer> <keyfile> -> prints nothing; sets HA array
host_args() {
  local h="$1" k="${2:-${KEY}}"
  HA=( -i "${k}" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new
       -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=10 -o LogLevel=ERROR )
  case "$h" in
    trader)  HDEST="${U}@${TRADER}" ;;
    gateway) HDEST="${U}@${GW}"; HA+=( -o "ProxyCommand=$(JUMP_CMD "${k}")" ) ;;
    trainer) [ -n "${TRAINER}" ] || { say "trainer address not configured (secret TRAINER_VM_IP)"; return 1; }
             HDEST="${TU}@${TRAINER}" ;;
  esac
}
# run_on <host> <cmd...>  — fresh connection (or over the host's master if open)
run_on() { local h="$1"; shift; host_args "$h"; local c="${TMP}/ctl-$h"
  if [ -S "$c" ]; then ssh "${HA[@]}" -o ControlPath="$c" "${HDEST}" "$@"; else ssh "${HA[@]}" "${HDEST}" "$@"; fi; }
# open_master <host> — the "old session path" that must survive the change
open_master() { local h="$1"; host_args "$h"; ssh "${HA[@]}" -o ControlMaster=yes -o ControlPath="${TMP}/ctl-$h" -o ControlPersist=20m -fN "${HDEST}"; }
# fresh_login <host> [keyfile] — a NEW connection, never the master
fresh_login() { local h="$1" k="${2:-${KEY}}"; host_args "$h" "$k"; ssh "${HA[@]}" -o ControlMaster=no -o ControlPath=none "${HDEST}" 'echo fresh-login-ok' 2>&1 | mask | tail -1; }

sshd_keys() { run_on "$1" "sudo -n sshd -T 2>/dev/null | grep -Ei '^(maxauthtries|x11forwarding|allowagentforwarding|allowtcpforwarding|passwordauthentication|permitrootlogin) ' | sort | tr '\n' ' '"; echo; }

fp_authorized() {  # remote snippet: fingerprints of authorized_keys for root/opc/ubuntu
  cat <<'R'
for u in root opc ubuntu; do h=$(getent passwd "$u" | cut -d: -f6); [ -n "$h" ] || continue
  f="$h/.ssh/authorized_keys"; sudo -n test -e "$f" || { echo "  $u: no authorized_keys"; continue; }
  sudo -n grep -Ev '^\s*(#|$)' "$f" | while read -r l; do
    o=no; case "$l" in ssh-*|ecdsa-*|sk-*) ;; *) o=yes ;; esac
    printf '%s\n' "$l" | ssh-keygen -lf - 2>/dev/null | awk -v u="$u" -v o="$o" '{print "  "u": "$1" "$2" "$NF" options="o}'
  done
  for k in $(sudo -n find "$h/.ssh" -maxdepth 1 -type f 2>/dev/null); do
    case "$k" in *authorized_keys*|*known_hosts*|*/config|*.pub) continue ;; esac
    fp=$(sudo -n ssh-keygen -lf "$k" 2>/dev/null | awk '{print $1" "$2" "$NF}')
    [ -n "$fp" ] && echo "  $u: PRIVATE ${k##*/} -> $fp"
  done
done
R
}

legacy_fp() { ssh-keygen -lf "${KEY}" 2>/dev/null | awk '{print $2}'; }

# ---------------------------------------------------------------- ssh-harden
harden_conf() {  # $1 = trader|gateway
  say "# ict: SEC-HOST-CHANGES-1112 (operator 2026-11-12 m4). Revert: system-action host-security-change target: ssh-harden-revert"
  say "MaxAuthTries 3"
  say "X11Forwarding no"
  say "AllowAgentForwarding no"
  if [ "$1" = trader ]; then say "# the IB gateway is reached THROUGH this host (ProxyJump): TCP forwarding stays on"; say "AllowTcpForwarding yes"; fi
}
harden_host() {  # $1 host; returns 0 on verified success
  local h="$1"
  say "--- ${h}: before: $(sshd_keys "$h")"
  if [ "${DRY}" = 1 ]; then say "--- ${h}: would write ${DROPIN}:"; harden_conf "$h" | sed 's/^/      /'; return 0; fi
  open_master "$h" || { say "--- ${h}: could not open the pre-change master connection; NOT changing"; return 1; }
  harden_conf "$h" | run_on "$h" "sudo -n tee ${DROPIN}.new >/dev/null && sudo -n chmod 644 ${DROPIN}.new && sudo -n mv ${DROPIN}.new ${DROPIN} && sudo -n sshd -t && sudo -n systemctl reload ssh && echo reloaded" \
    || { say "--- ${h}: write/sshd -t/reload FAILED; removing the drop-in"; run_on "$h" "sudo -n rm -f ${DROPIN} ${DROPIN}.new; sudo -n sshd -t && sudo -n systemctl reload ssh"; return 1; }
  sleep 2
  say "--- ${h}: after:  $(sshd_keys "$h")"
  local ok; ok=$(fresh_login "$h")
  say "--- ${h}: fresh login with the master still open: ${ok}"
  if [ "${h}" = trader ]; then local okg; okg=$(fresh_login gateway); say "--- trader: fresh ProxyJump to the gateway (TCP forwarding): ${okg}"; [ "${okg}" = fresh-login-ok ] || ok="jump-failed"; fi
  if [ "${ok}" != fresh-login-ok ]; then
    say "--- ${h}: FRESH LOGIN FAILED -> rolling back over the master"
    run_on "$h" "sudo -n rm -f ${DROPIN}; sudo -n sshd -t && sudo -n systemctl reload ssh && echo rolled-back"
    say "--- ${h}: fresh login after rollback: $(fresh_login "$h")"
    return 1
  fi
  return 0
}
do_ssh_harden() {
  mode_line
  harden_host trader || { say "RESULT: ssh-harden FAILED on the trader (rolled back); gateway not touched"; return 1; }
  harden_host gateway || { say "RESULT: ssh-harden FAILED on the gateway (rolled back); trader keeps its change"; return 1; }
  say "RESULT: ssh-harden $( [ "${DRY}" = 1 ] && echo dry_run || echo applied_and_verified )"
}
do_ssh_harden_revert() {
  mode_line
  for h in trader gateway; do
    say "--- ${h}: before: $(sshd_keys "$h")"
    [ "${DRY}" = 1 ] && { say "--- ${h}: would remove ${DROPIN} and reload"; continue; }
    open_master "$h" || true
    run_on "$h" "sudo -n rm -f ${DROPIN}; sudo -n sshd -t && sudo -n systemctl reload ssh && echo reloaded"
    sleep 2; say "--- ${h}: after:  $(sshd_keys "$h")"; say "--- ${h}: fresh login: $(fresh_login "$h")"
  done
  say "RESULT: ssh-harden-revert $( [ "${DRY}" = 1 ] && echo dry_run || echo done )"
}

# ---------------------------------------------------------------- fail2ban
jail_conf() {
  local ign="127.0.0.1/8 ::1 10.0.0.0/16"; [ -n "${TRAINER}" ] && ign="${ign} ${TRAINER}"
  cat <<EOF
# ict: SEC-HOST-CHANGES-1112 (operator 2026-11-12 m4). Revert: host-security-change target: fail2ban-revert
[DEFAULT]
# loopback, the VCN (the gateway and any VCN peer) and the trainer (self-hosted infra runner) are never banned
ignoreip = ${ign}
bantime = 1h
findtime = 10m
maxretry = 5
bantime.increment = true
bantime.maxtime = 1w

[sshd]
enabled = true
mode = normal
port = ssh
EOF
}
do_fail2ban() {
  mode_line
  say "--- trader: fail2ban before: $(run_on trader 'command -v fail2ban-client >/dev/null && systemctl is-active fail2ban || echo not-installed' 2>&1 | tail -1)"
  say "--- gateway: NOT installed by design — it has no public sshd (reached only from the trader over the VCN), so every ssh there comes from one VCN address and a ban would cut the workflows off."
  if [ "${DRY}" = 1 ]; then say "--- trader: would apt-get install fail2ban and write ${JAIL} (trainer address masked):"; jail_conf | mask | sed 's/^/      /'; say "RESULT: fail2ban dry_run"; return 0; fi
  open_master trader || { say "could not open the master; NOT changing"; return 1; }
  run_on trader "sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 NEEDRESTART_MODE=l apt-get -o DPkg::Lock::Timeout=600 -o Dpkg::Options::=--force-confold install -y --no-install-recommends fail2ban 2>&1 | tail -3" | mask
  jail_conf | run_on trader "sudo -n mkdir -p /etc/fail2ban/jail.d && sudo -n tee ${JAIL} >/dev/null && sudo -n chmod 644 ${JAIL} && sudo -n fail2ban-client -t >/dev/null && sudo -n systemctl enable fail2ban >/dev/null 2>&1; sudo -n systemctl restart fail2ban && sleep 3 && systemctl is-active fail2ban" | mask
  say "--- trader: jail: $(run_on trader "sudo -n fail2ban-client status sshd 2>&1 | grep -E 'Currently failed|Total failed|Currently banned|Total banned' | tr -s ' \t' ' ' | tr '\n' ';'" | mask)"
  say "--- trader: iptables f2b chain present: $(run_on trader "sudo -n iptables -S 2>/dev/null | grep -c '^-N f2b-sshd' || true")"
  local ok; ok=$(fresh_login trader); say "--- trader: fresh login with fail2ban running: ${ok}"
  local okg; okg=$(fresh_login gateway); say "--- trader: fresh ProxyJump to the gateway: ${okg}"
  if [ "${ok}" != fresh-login-ok ] || [ "${okg}" != fresh-login-ok ]; then
    say "--- FRESH LOGIN FAILED -> stopping fail2ban over the master"; run_on trader "sudo -n systemctl disable --now fail2ban; echo stopped"
    say "RESULT: fail2ban FAILED (stopped)"; return 1
  fi
  say "RESULT: fail2ban applied_and_verified"
}
do_fail2ban_revert() {
  mode_line
  [ "${DRY}" = 1 ] && { say "would: systemctl disable --now fail2ban; apt-get purge -y fail2ban; rm ${JAIL}"; say "RESULT: fail2ban-revert dry_run"; return 0; }
  run_on trader "sudo -n systemctl disable --now fail2ban 2>/dev/null; sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get -o DPkg::Lock::Timeout=600 purge -y fail2ban 2>&1 | tail -2; sudo -n rm -f ${JAIL}; echo f2b-chains=\$(sudo -n iptables -S | grep -c '^-N f2b-' || true)" | mask
  say "--- trader: fresh login: $(fresh_login trader)"
  say "RESULT: fail2ban-revert done"
}

# ---------------------------------------------------------------- gateway-reboot
gw_read() {
  run_on gateway 'bash -s' <<'R' 2>&1 | mask
echo "kernel: $(uname -r)  uptime: $(uptime -p)  boot: $(uptime -s)"
echo "reboot-required: $([ -f /var/run/reboot-required ] && echo YES || echo no)"
echo "container: $(sudo -n docker ps -a --filter name=^/ib-gateway$ --format '{{.Status}}' 2>/dev/null)  restart-policy: $(sudo -n docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' ib-gateway 2>/dev/null)"
echo "port 4002 listening: $(sudo -n ss -H -tln 2>/dev/null | grep -c ':4002 ' || true)"
for t in ict-ib-gateway-watchdog.timer ict-ib-gateway-reset.timer ict-git-sync.timer; do echo "$t: active=$(systemctl is-active $t 2>/dev/null) enabled=$(systemctl is-enabled $t 2>/dev/null)"; done
R
}
do_gateway_reboot() {
  mode_line
  say "--- gateway before:"; gw_read | sed 's/^/    /'
  [ "${DRY}" = 1 ] && { say "would: systemd-run --on-active=5 systemctl reboot; poll ssh <=10 min; post-read; one dry-run ib_paper probe"; say "RESULT: gateway-reboot dry_run"; return 0; }
  local boot0; boot0=$(run_on gateway 'uptime -s')
  run_on gateway "sudo -n systemd-run --on-active=5 --unit=ict-sec-reboot-${TS} /bin/systemctl reboot >/dev/null 2>&1 && echo reboot-scheduled-5s" || { say "could not schedule the reboot"; return 1; }
  say "--- reboot issued at $(date -u +%H:%M:%SZ); polling ssh up to 9 min"
  sleep 45
  local deadline=$(( $(date +%s) + 540 )) back=no boot1=""
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    boot1=$(run_on gateway 'uptime -s' 2>/dev/null || true)
    if [ -n "${boot1}" ] && [ "${boot1}" != "${boot0}" ]; then back=yes; break; fi
    sleep 15
  done
  if [ "${back}" != yes ]; then say "RESULT: gateway-reboot NOT_BACK — ssh did not return with a new boot time within ~10 min. Recovery: OCI console instance reset of ict-ib-gateway."; return 1; fi
  say "--- gateway back at $(date -u +%H:%M:%SZ) (new boot time)"
  local d2=$(( $(date +%s) + 180 ))
  while [ "$(date +%s)" -lt "${d2}" ]; do
    [ "$(run_on gateway "sudo -n ss -H -tln | grep -c ':4002 ' || true" 2>/dev/null)" -ge 1 ] 2>/dev/null && break; sleep 15
  done
  say "--- gateway after:"; gw_read | sed 's/^/    /'
  say "--- one dry-run ib_paper probe (no restart):"
  run_on gateway 'cd /home/ubuntu/ict-trading-bot 2>/dev/null && timeout 120 python3 -u scripts/check_ib_gateway.py --probe-account ib_paper --probe-script scripts/ops/ib_gateway_local_probe.py --state runtime_logs/ib_gateway_watchdog_state.json --dry-run 2>&1 | grep -E "probe:|action" | tail -3' 2>&1 | mask | sed 's/^/    /'
  say "RESULT: gateway-reboot rebooted_and_back (IBC 2FA may still be pending: check the probe line above and the trader's ib_paper read)"
}

# ---------------------------------------------------------------- keys
do_keys_survey() {
  say "runner key (VM_SSH_KEY) fingerprint: $(ssh-keygen -lf "${KEY}" | awk '{print $1" "$2" "$NF}')"
  for h in trader gateway trainer; do
    say "--- ${h}:"; run_on "$h" 'bash -s' < <(fp_authorized) 2>&1 | mask || say "  (unreachable)"
  done
  say "RESULT: keys-survey read_only"
}
add_pub_cmd() {  # remote: append a pubkey (stdin) to ubuntu authorized_keys if absent; print count
  cat <<'R'
set -e; f="$HOME/.ssh/authorized_keys"; IFS= read -r pub
cp -p "$f" "$f.bak-$TS"
grep -qxF "$pub" "$f" || printf '%s\n' "$pub" >> "$f"
chmod 600 "$f"; echo "keys now: $(grep -cEv '^\s*(#|$)' "$f")"
R
}
do_keys_runner_rotate() {
  mode_line
  local old; old=$(legacy_fp)
  say "current runner key: ${old}"
  [ -n "${GH_TOKEN:-}" ] || { say "GH_TOKEN (Actions-secrets writer) is empty: refusing before any change"; return 1; }
  gh api "repos/${GITHUB_REPOSITORY:-}/actions/secrets/public-key" --silent >/dev/null 2>&1 || { say "GH_TOKEN cannot reach the secrets API: refusing before any change"; return 1; }
  [ "${DRY}" = 1 ] && { say "would: generate ed25519 '${RUNNER_KEY_COMMENT}', append to ubuntu@trader/gateway/trainer (old key kept), verify fresh logins with it alone, then VM_SSH_KEY_LEGACY := current, VM_SSH_KEY := new"; say "RESULT: keys-runner-rotate dry_run"; return 0; }
  local nk="${TMP}/new_runner_key"
  ssh-keygen -q -t ed25519 -N '' -C "${RUNNER_KEY_COMMENT}" -f "${nk}"
  say "new runner key: $(ssh-keygen -lf "${nk}.pub" | awk '{print $1" "$2" "$NF}')"
  for h in trader gateway trainer; do
    say "--- ${h}: $(cat "${nk}.pub" | run_on "$h" "TS=${TS} bash -c $(printf '%q' "$(add_pub_cmd)")" 2>&1 | mask | tail -1)"
  done
  local fail=0
  for h in trader gateway trainer; do r=$(fresh_login "$h" "${nk}"); say "--- ${h}: fresh login with the NEW key alone: ${r}"; [ "$r" = fresh-login-ok ] || fail=1; done
  [ "${fail}" = 0 ] || { say "RESULT: keys-runner-rotate NOT_SWITCHED — the new key did not log in everywhere; secrets untouched, old key still authorized (new key line left in place, harmless; listed by keys-survey)"; return 1; }
  gh secret set VM_SSH_KEY_LEGACY --repo "${GITHUB_REPOSITORY:-}" < "${KEY}" >/dev/null 2>&1 || { say "RESULT: could not write VM_SSH_KEY_LEGACY; VM_SSH_KEY untouched"; return 1; }
  gh secret set VM_SSH_KEY --repo "${GITHUB_REPOSITORY:-}" < "${nk}" >/dev/null 2>&1 || { say "RESULT: could not write VM_SSH_KEY; it still holds the old key (also saved as VM_SSH_KEY_LEGACY)"; return 1; }
  say "secrets updated_at: VM_SSH_KEY=$(gh api "repos/${GITHUB_REPOSITORY:-}/actions/secrets/VM_SSH_KEY" --jq .updated_at 2>/dev/null) VM_SSH_KEY_LEGACY=$(gh api "repos/${GITHUB_REPOSITORY:-}/actions/secrets/VM_SSH_KEY_LEGACY" --jq .updated_at 2>/dev/null)"
  shred -u "${nk}" 2>/dev/null || rm -f "${nk}"
  say "RESULT: keys-runner-rotate switched (every later workflow uses the new key; revert: target keys-runner-revert)"
}
do_keys_runner_revert() {
  mode_line
  [ -n "${LEGACY_KEY_VALUE:-}" ] || { say "secret VM_SSH_KEY_LEGACY is empty: nothing to revert to"; return 1; }
  local lk="${TMP}/legacy"; ( umask 077; printf '%s\n' "${LEGACY_KEY_VALUE}" > "${lk}" )
  say "legacy key: $(ssh-keygen -lf "${lk}" | awk '{print $2}')"
  r=$(fresh_login trader "${lk}"); say "legacy key fresh login on the trader: ${r}"
  [ "$r" = fresh-login-ok ] || { say "RESULT: legacy key no longer logs in; NOT reverting"; return 1; }
  [ "${DRY}" = 1 ] && { say "RESULT: keys-runner-revert dry_run"; return 0; }
  gh secret set VM_SSH_KEY --repo "${GITHUB_REPOSITORY:-}" < "${lk}" >/dev/null 2>&1 && say "RESULT: keys-runner-revert done (VM_SSH_KEY = legacy)" || { say "RESULT: gh secret set failed"; return 1; }
}
do_keys_trainer_rotate() {
  mode_line
  [ "${DRY}" = 1 ] && { say "would: on the trainer generate ~/.ssh/jta_trainer_to_trader_ed25519, append its .pub to ubuntu@trader, verify from the trainer with it alone, then swap ~/${TRAINER_KEYFILE} (old kept as .legacy-${TS})"; run_on trainer "ls -la ~/.ssh | awk 'NR>1{print \$1,\$NF}'" | sed 's/^/    /'; say "RESULT: keys-trainer-rotate dry_run"; return 0; }
  local pub
  pub=$(run_on trainer "set -e; k=~/.ssh/jta_trainer_to_trader_ed25519; [ -f \$k ] || ssh-keygen -q -t ed25519 -N '' -C ${TRAINER_KEY_COMMENT} -f \$k; cat \$k.pub")
  say "trainer key: $(printf '%s\n' "${pub}" | ssh-keygen -lf - | awk '{print $1" "$2" "$NF}')"
  say "--- trader: $(printf '%s\n' "${pub}" | run_on trader "TS=${TS} bash -c $(printf '%q' "$(add_pub_cmd)")" 2>&1 | mask | tail -1)"
  local t; t=$(run_on trainer "ssh -i ~/.ssh/jta_trainer_to_trader_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o LogLevel=ERROR ${U}@${TRADER} 'echo fresh-login-ok' 2>&1 | tail -1" | mask)
  say "--- trainer -> trader with the new key alone: ${t}"
  [ "$t" = fresh-login-ok ] || { say "RESULT: keys-trainer-rotate NOT_SWITCHED (trainer key file untouched)"; return 1; }
  run_on trainer "set -e; f=~/${TRAINER_KEYFILE}; [ -f \$f ] && cp -p \$f \$f.legacy-${TS}; install -m 600 ~/.ssh/jta_trainer_to_trader_ed25519 \$f; ssh-keygen -lf \$f | awk '{print \"trainer key file now: \"\$2}'"
  t=$(run_on trainer "ssh -i ~/${TRAINER_KEYFILE} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15 -o LogLevel=ERROR ${U}@${TRADER} 'echo fresh-login-ok' 2>&1 | tail -1" | mask)
  say "--- trainer -> trader via the swapped key file: ${t}"
  [ "$t" = fresh-login-ok ] || { run_on trainer "cp -p ~/${TRAINER_KEYFILE}.legacy-${TS} ~/${TRAINER_KEYFILE}"; say "RESULT: FAILED after swap -> legacy file restored"; return 1; }
  say "RESULT: keys-trainer-rotate switched (revert: target keys-trainer-revert)"
}
do_keys_trainer_revert() {
  mode_line
  run_on trainer "ls -1t ~/${TRAINER_KEYFILE}.legacy-* 2>/dev/null | head -1 | xargs -r -n1 basename"
  [ "${DRY}" = 1 ] && { say "RESULT: keys-trainer-revert dry_run"; return 0; }
  run_on trainer "l=\$(ls -1t ~/${TRAINER_KEYFILE}.legacy-* 2>/dev/null | head -1); [ -n \"\$l\" ] && install -m 600 \"\$l\" ~/${TRAINER_KEYFILE} && ssh-keygen -lf ~/${TRAINER_KEYFILE} | awk '{print \"restored: \"\$2}'"
  say "RESULT: keys-trainer-revert done"
}
do_keys_retire_legacy() {
  mode_line
  [ -n "${LEGACY_KEY_VALUE:-}" ] || { say "secret VM_SSH_KEY_LEGACY is empty: run keys-runner-rotate first"; return 1; }
  local lk="${TMP}/legacy"; ( umask 077; printf '%s\n' "${LEGACY_KEY_VALUE}" > "${lk}" )
  local lfp; lfp=$(ssh-keygen -lf "${lk}" | awk '{print $2}')
  [ "$(legacy_fp)" != "${lfp}" ] || { say "refused: the runner's VM_SSH_KEY IS still the legacy key"; return 1; }
  local fail=0
  for h in trader gateway trainer; do r=$(fresh_login "$h"); say "current runner key fresh login ${h}: ${r}"; [ "$r" = fresh-login-ok ] || fail=1; done
  t=$(run_on trainer "ssh -i ~/${TRAINER_KEYFILE} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15 -o LogLevel=ERROR ${U}@${TRADER} 'echo fresh-login-ok' 2>&1 | tail -1" | mask)
  say "trainer's own key -> trader: ${t}"; [ "$t" = fresh-login-ok ] || fail=1
  [ "$(run_on trainer "ssh-keygen -lf ~/${TRAINER_KEYFILE} | awk '{print \$2}'")" != "${lfp}" ] || { say "refused: the trainer key file is still the legacy key"; fail=1; }
  [ "${fail}" = 0 ] || { say "RESULT: keys-retire-legacy refused (preconditions)"; return 1; }
  [ "${DRY}" = 1 ] && { say "would remove ${lfp} from ubuntu authorized_keys on trader/gateway/trainer (backups kept) and delete the trainer's *.legacy-* copies"; say "RESULT: keys-retire-legacy dry_run"; return 0; }
  local rm_cmd
  rm_cmd=$(cat <<R
set -e; f="\$HOME/.ssh/authorized_keys"; cp -p "\$f" "\$f.bak-${TS}"; : > "\$f.new"
while IFS= read -r l; do fp=\$(printf '%s\n' "\$l" | ssh-keygen -lf - 2>/dev/null | awk '{print \$2}'); [ "\$fp" = "${lfp}" ] && continue; printf '%s\n' "\$l" >> "\$f.new"; done < "\$f"
[ -s "\$f.new" ] || { echo "refused: would empty authorized_keys"; rm -f "\$f.new"; exit 1; }
chmod 600 "\$f.new"; mv "\$f.new" "\$f"; echo "keys now: \$(grep -cEv '^\s*(#|\$)' "\$f")"
R
)
  for h in trader gateway trainer; do say "--- ${h}: $(run_on "$h" "bash -c $(printf '%q' "${rm_cmd}")" 2>&1 | mask | tail -1)"; r=$(fresh_login "$h"); say "--- ${h}: fresh login after: ${r}"; done
  run_on trainer "rm -f ~/${TRAINER_KEYFILE}.legacy-*; echo trainer-legacy-copies-removed"
  r=$(fresh_login trader "${lk}"); say "legacy key on the trader now: ${r} (expected: denied)"
  say "RESULT: keys-retire-legacy done (revert: target keys-retire-legacy-revert restores authorized_keys.bak-${TS})"
}
do_keys_retire_legacy_revert() {
  mode_line
  for h in trader gateway trainer; do
    say "--- ${h}: newest backup: $(run_on "$h" 'ls -1t ~/.ssh/authorized_keys.bak-* 2>/dev/null | head -1 | xargs -r -n1 basename')"
    [ "${DRY}" = 1 ] && continue
    say "--- ${h}: $(run_on "$h" 'b=$(ls -1t ~/.ssh/authorized_keys.bak-* | head -1); cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.pre-revert; cp -p "$b" ~/.ssh/authorized_keys; echo restored')"
  done
  say "RESULT: keys-retire-legacy-revert $( [ "${DRY}" = 1 ] && echo dry_run || echo done )"
}

say "host-security-change target=${TARGET:-<none>} ts=${TS}"
case "${TARGET}" in
  ssh-harden)               do_ssh_harden ;;
  ssh-harden-revert)        do_ssh_harden_revert ;;
  fail2ban)                 do_fail2ban ;;
  fail2ban-revert)          do_fail2ban_revert ;;
  gateway-reboot)           do_gateway_reboot ;;
  keys-survey)              do_keys_survey ;;
  keys-runner-rotate)       do_keys_runner_rotate ;;
  keys-runner-revert)       do_keys_runner_revert ;;
  keys-trainer-rotate)      do_keys_trainer_rotate ;;
  keys-trainer-revert)      do_keys_trainer_revert ;;
  keys-retire-legacy)       do_keys_retire_legacy ;;
  keys-retire-legacy-revert) do_keys_retire_legacy_revert ;;
  *) say "unknown target '${TARGET}'"; exit 2 ;;
esac
