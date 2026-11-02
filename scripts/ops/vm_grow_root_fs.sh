#!/usr/bin/env bash
# VM-side half of `oci-grow-boot-volume` (run over ssh stdin: `bash -s -- <step>`).
#
#   preflight  read-only. Prints df -T / and lsblk, checks that passwordless sudo
#              covers every command `grow` needs. Runs BEFORE the OCI backup or
#              resize so a missing sudoers line strands nothing.
#   grow       rescan the device (dd iflag=direct on /dev/oracleoci/oraclevda,
#              then `echo 1 > /sys/class/block/<disk>/device/rescan`), growpart on
#              the root partition, then resize2fs (ext*) or xfs_growfs (xfs),
#              chosen from df -T. No reboot, no service restart.
#   verify     df -h /, lsblk, and the trader + web-api units still active.
#
# Env: TARGET_GB (grow; lower-bound check on the device size), EXPECTED_NAME
# (IMDS displayName pin).
#
# Exit codes: 0 ok; 1 failed; 2 identity refused; 5 sudo missing (the exact
# sudoers line is printed; this script does NOT work around it).
set -euo pipefail

STEP="${1:-preflight}"
EXPECTED_NAME="${EXPECTED_NAME:-ict-bot-arm}"
SVCS="ict-trader-live.service ict-web-api.service"

identity() {
  local imds name
  imds=$(curl -sS -H "Authorization: Bearer Oracle" --max-time 5 http://169.254.169.254/opc/v2/instance/)
  name=$(printf '%s' "$imds" | python3 -c 'import json,sys;print(json.load(sys.stdin)["displayName"])')
  if [ "$name" != "$EXPECTED_NAME" ]; then
    echo "REFUSED: this host is '$name', not '$EXPECTED_NAME'"; exit 2
  fi
  echo "identity ok: $name"
}

root_layout() {
  SRC=$(findmnt -no SOURCE /)
  FST=$(findmnt -no FSTYPE /)
  PART=$(basename "$SRC")
  DISK=$(lsblk -no PKNAME "$SRC" | head -1)
  PNUM=$(cat "/sys/class/block/$PART/partition")
  echo "root: $SRC ($FST) on /dev/$DISK partition $PNUM"
}

fs_tool() {
  case "$FST" in
    ext2|ext3|ext4) FSBIN=resize2fs ;;
    xfs) FSBIN=xfs_growfs ;;
    *) echo "unsupported root fs: $FST"; exit 1 ;;
  esac
}

sudo_ok() {  # sudo_ok <cmd> : passwordless sudo permitted for the resolved path?
  local p
  p=$(command -v "$1" 2>/dev/null || true)
  [ -n "$p" ] && sudo -n -l "$p" >/dev/null 2>&1
}

sudo_check() {
  local missing=() c cmds=()
  for c in growpart "$FSBIN" dd tee; do
    command -v "$c" >/dev/null 2>&1 || { echo "tool missing on VM: $c"; exit 1; }
    sudo_ok "$c" || missing+=("$c")
    cmds+=("$(command -v "$c")")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "SUDO MISSING (passwordless) for: ${missing[*]}"
    echo "The operator must add this line via visudo (e.g. /etc/sudoers.d/oci-grow-root):"
    printf '%s ALL=(root) NOPASSWD: %s\n' "$(id -un)" "$(IFS=,; echo "${cmds[*]}" | sed 's/,/, /g')"
    exit 5
  fi
  echo "sudo ok: growpart, $FSBIN, dd, tee"
}

case "$STEP" in
  preflight)
    identity; root_layout; fs_tool
    df -T /; lsblk
    sudo_check ;;
  grow)
    identity; root_layout; fs_tool; sudo_check
    : "${TARGET_GB:?TARGET_GB required}"
    TARGET_B=$(( TARGET_GB * 1000 * 1000 * 1000 ))   # decimal lower bound; holds for GB or GiB
    BEFORE_G=$(df -B1G --output=size / | tail -1 | tr -d ' ')
    DEV=/dev/oracleoci/oraclevda; [ -e "$DEV" ] || DEV="/dev/$DISK"
    for i in $(seq 1 40); do
      sudo dd iflag=direct if="$DEV" of=/dev/null count=1 >/dev/null 2>&1 || true
      if [ -e "/sys/class/block/$DISK/device/rescan" ]; then
        echo 1 | sudo tee "/sys/class/block/$DISK/device/rescan" >/dev/null
      fi
      DEV_B=$(lsblk -bdno SIZE "/dev/$DISK")
      [ "$DEV_B" -ge "$TARGET_B" ] && break
      sleep 15
    done
    DEV_B=$(lsblk -bdno SIZE "/dev/$DISK")
    if [ "$DEV_B" -lt "$TARGET_B" ]; then
      echo "FAILED: /dev/$DISK is $DEV_B bytes after rescan, below $TARGET_B"; exit 1
    fi
    lsblk "/dev/$DISK"
    set +e; out=$(sudo growpart "/dev/$DISK" "$PNUM" 2>&1); grc=$?; set -e
    echo "$out"
    if [ $grc -ne 0 ] && ! printf '%s' "$out" | grep -q NOCHANGE; then
      echo "growpart failed rc=$grc"; exit 1
    fi
    if [ "$FSBIN" = resize2fs ]; then sudo resize2fs "$SRC"; else sudo xfs_growfs /; fi
    AFTER_G=$(df -B1G --output=size / | tail -1 | tr -d ' ')
    echo "root filesystem size: ${BEFORE_G}G -> ${AFTER_G}G"
    if [ "$AFTER_G" -le "$BEFORE_G" ] && ! printf '%s' "$out" | grep -q NOCHANGE; then
      echo "FAILED: root filesystem did not grow"; exit 1
    fi ;;
  verify)
    df -h /; lsblk
    bad=0
    for s in $SVCS; do
      st=$(systemctl is-active "$s" || true)
      echo "$s: $st"
      [ "$st" = active ] || bad=1
    done
    [ "$bad" -eq 0 ] || { echo "FAILED: a service is not active"; exit 1; } ;;
  *) echo "usage: $0 preflight|grow|verify"; exit 2 ;;
esac
