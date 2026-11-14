#!/usr/bin/env bash
# system-action wrapper (Tier 2): free disk on the IB GATEWAY VM. Runs ON the gateway
# (the workflow ProxyJumps through the trader, same as gateway-disk-report).
#
# GATEWAY-DISK-CLEANUP (operator popup ~05:35Z 2026-11-05, verbatim "A+B+C now, rehearse D
# (Recommended)"; findings PI-20261104-GWDISK-0001 / #23101). Root fs 45G at 94%; the
# /home/ubuntu/ict-trading-bot checkout is 33G (.git 23G, 8.86G untracked research caches).
# The checkout is LIVE (ict-git-sync, ict-ib-gateway-watchdog, ict-ib-gateway-reset run from
# it): nothing here removes, moves or renames it, restarts the ib-gateway container, or
# touches IB settings/credentials.
#
# target (required), every one DRY-RUN unless apply: true:
#   journald           - write /etc/systemd/journald.conf.d/90-ict-gateway-cap.conf
#                        (SystemMaxUse=500M), journalctl --vacuum-size=500M, restart
#                        systemd-journald (journald only; no other unit).
#   research-clean     - `git clean -ndx -- comms/research`: prints every path, whether it
#                        holds a tracked file, its size, the total and the sha256 of the list.
#                        apply additionally needs confirm: <that sha256>, so the real clean
#                        removes EXACTLY the list that was reviewed (exit 3 if it changed).
#                        Refuses any path outside comms/research/ or holding a tracked file.
#   prune-packed       - `git prune-packed` (loose objects that are ALREADY in a pack only).
#   rehearse-sideclone - D rehearsal, NO swap: a depth-1 sparse side-clone at
#                        ${SIDE_DIR}, the git-sync (VM-SPARSE-SYNC) block of
#                        scripts/deploy_pull_restart.sh run against it, and
#                        check_ib_gateway.py --dry-run from it. Live dir untouched.
#   sideclone-remove   - delete the rehearsal side-clone (never the live dir).
# Env: ACTION_TARGET, ACTION_APPLY, ACTION_CONFIRM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/ops/_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

TARGET="${ACTION_TARGET:-}"
APPLY="${ACTION_APPLY:-false}"
case "${APPLY}" in True) APPLY=true ;; False|"") APPLY=false ;; esac
CONFIRM="${ACTION_CONFIRM:-}"
LIVE="/home/ubuntu/ict-trading-bot"
SIDE_DIR="/home/ubuntu/ict-trading-bot.sideclone-rehearsal"
G=(git -c safe.directory="${LIVE}" -C "${LIVE}")
first() { awk -v n="$1" 'NR<=n'; }

# Gateway only: the trader VM has no /etc/ict-vm-role marker (deploy_pull_restart.sh).
ROLE=""
[ -r /etc/ict-vm-role ] && ROLE="$(tr -d '[:space:]' < /etc/ict-vm-role 2>/dev/null || true)"
if [ "${ROLE}" != "gateway" ]; then
    echo "ERROR: /etc/ict-vm-role is '${ROLE}', not 'gateway' -- this action runs on the IB gateway VM only."
    exit 2
fi
if ! sudo -n true 2>/dev/null; then
    echo "ERROR: passwordless sudo is not available on this host."; exit 4
fi

df_line() { df -B1 --output=used,avail,pcent / | awk 'NR==2{printf "used=%.2fG avail=%.2fG use=%s\n",$1/1073741824,$2/1073741824,$3}'; }
avail_b() { df -B1 --output=avail / | awk 'NR==2{print $1}'; }

# A sync tick running `git reset --hard` while we clean or prune is avoidable: wait it out
# (bounded; we never stop or disable the timer -- no halting).
wait_git_sync_idle() {
    local i
    for i in $(seq 1 48); do
        if [ "$(systemctl is-active ict-git-sync.service 2>/dev/null || true)" != "activating" ] \
           && [ "$(systemctl is-active ict-git-sync.service 2>/dev/null || true)" != "active" ]; then
            echo "ict-git-sync.service idle (check ${i})"; return 0
        fi
        sleep 5
    done
    echo "WARNING: ict-git-sync.service still running after 240s; proceeding (the step is safe against a concurrent fetch)."
}

OLD_DIR="/home/ubuntu/ict-trading-bot.pre-swap-old"
FAILED_DIR="/home/ubuntu/ict-trading-bot.swap-failed"

wait_unit_idle() {
    local i st
    for i in $(seq 1 36); do
        st="$(systemctl is-active "$1" 2>/dev/null || true)"
        if [ "${st}" != "active" ] && [ "${st}" != "activating" ]; then return 0; fi
        sleep 5
    done
    echo "WARNING: $1 still running after 180s; proceeding."
}

# Health of the gateway's checkout-dependent units. Returns non-zero on a hard failure.
health_report() {
    local rc=0 u res st
    echo "df: $(df_line)"
    if "${G[@]}" rev-parse --verify -q HEAD >/dev/null; then
        echo "live: HEAD $("${G[@]}" log -1 --format='%h %cI') shallow=$("${G[@]}" rev-parse --is-shallow-repository) .git=$(du -sh "${LIVE}/.git" 2>/dev/null | awk '{print $1}')"
    else echo "FAIL: ${LIVE} has no readable HEAD"; rc=1; fi
    for f in scripts/deploy_pull_restart.sh scripts/check_ib_gateway.py scripts/ops/ib_gateway_local_probe.py; do
        [ -f "${LIVE}/${f}" ] || { echo "FAIL: missing ${LIVE}/${f}"; rc=1; }
    done
    for u in ict-git-sync ict-ib-gateway-watchdog ict-ib-gateway-reset; do
        res="$(systemctl show -p Result --value "${u}.service" 2>/dev/null || true)"
        st="$(systemctl show -p ExecMainStatus --value "${u}.service" 2>/dev/null || true)"
        echo "${u}.service: result=${res:-?} exit=${st:-?} last_exit=$(systemctl show -p ExecMainExitTimestamp --value "${u}.service" 2>/dev/null)"
    done
    local cst tst t
    cst="$(sudo -n docker inspect -f '{{.State.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}}' ib-gateway 2>/dev/null || true)"
    echo "ib-gateway container: ${cst:-could_not_look}"
    case "${cst}" in running*) ;; *) echo "FAIL: ib-gateway container not running"; rc=1 ;; esac
    for t in ict-ib-gateway-watchdog.timer ict-git-sync.timer ict-ib-gateway-reset.timer; do
        tst="$(systemctl is-active "${t}" 2>/dev/null || true)"
        echo "${t}: ${tst:-unknown} next=$(systemctl show -p NextElapseUSecRealtime --value "${t}" 2>/dev/null || true)"
        [ "${tst}" = "active" ] || { echo "FAIL: ${t} is not active"; rc=1; }
    done
    mkdir -p /tmp/gwdisk-swap
    [ -f "${LIVE}/runtime_logs/ib_gateway_watchdog_state.json" ] && cp -f "${LIVE}/runtime_logs/ib_gateway_watchdog_state.json" /tmp/gwdisk-swap/state.json
    local out
    out="$(cd "${LIVE}" && timeout 180 /usr/bin/python3 -u scripts/check_ib_gateway.py --probe-account ib_paper \
          --probe-script scripts/ops/ib_gateway_local_probe.py --state /tmp/gwdisk-swap/state.json \
          --restart-after 2 --max-restarts 3 --cooldown-min 20 --max-backoff-min 60 --dry-run 2>&1 | tail -n 3)" || { echo "FAIL: check_ib_gateway.py --dry-run rc=$?"; rc=1; }
    echo "check_ib_gateway: ${out}"
    printf "%s" "${out}" | grep -q "healthy=True" || { echo "FAIL: gateway probe not healthy=True (ib_paper read did not answer)"; rc=1; }
    return "${rc}"
}

revert_swap() {
    [ -d "${OLD_DIR}" ] || { echo "revert: no ${OLD_DIR}"; return 1; }
    rm -rf --one-file-system -- "${FAILED_DIR}" 2>/dev/null || true
    mv -T "${LIVE}" "${FAILED_DIR}" && mv -T "${OLD_DIR}" "${LIVE}" && echo "REVERTED: ${LIVE} is the old checkout again; failed clone at ${FAILED_DIR}"
}

echo "===== gateway-disk-cleanup target=${TARGET} apply=${APPLY} $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
B0="$(avail_b)"
echo ">>> before: $(df_line)"

case "${TARGET}" in
journald)
    CONF_DIR=/etc/systemd/journald.conf.d
    CONF=${CONF_DIR}/90-ict-gateway-cap.conf
    CONF_BODY=$'[Journal]\nSystemMaxUse=500M\n'
    sudo -n journalctl --disk-usage 2>&1 || echo "could_not_look: journalctl --disk-usage"
    echo "existing drop-ins:"; ls -la "${CONF_DIR}" 2>&1 || echo "(none: ${CONF_DIR} absent)"
    echo "planned: write ${CONF} =>"; printf '%s' "${CONF_BODY}"
    echo "planned: journalctl --vacuum-size=500M ; systemctl restart systemd-journald"
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing changed. Re-dispatch with apply: true."; exit 0; fi
    sudo -n mkdir -p "${CONF_DIR}"
    printf '%s' "${CONF_BODY}" | sudo -n tee "${CONF}" >/dev/null
    sudo -n journalctl --vacuum-size=500M 2>&1 | tail -n 3
    sudo -n systemctl restart systemd-journald
    sleep 2
    echo "systemd-journald: $(systemctl is-active systemd-journald 2>&1 || true)"
    echo "persisted: $(sudo -n cat "${CONF}" | tr '\n' ' ')"
    sudo -n journalctl --disk-usage 2>&1 || true
    ;;
research-clean)
    wait_git_sync_idle
    LIST="$("${G[@]}" clean -ndx -- comms/research | sed -n 's/^Would remove //p')"
    N="$(printf '%s' "${LIST}" | grep -c . || true)"
    SHA="$(printf '%s\n' "${LIST}" | sha256sum | awk '{print $1}')"
    echo "paths: ${N}"
    BAD=0; TOTAL=0
    echo "size_bytes	tracked_files	shape	path"
    while IFS= read -r p; do
        [ -n "${p}" ] || continue
        case "${p}" in comms/research/*) ;; *) echo "REFUSE: outside comms/research: ${p}"; BAD=1; continue ;; esac
        case "${p}" in *..*) echo "REFUSE: '..' in path: ${p}"; BAD=1; continue ;; esac
        tr_n="$("${G[@]}" ls-files -- "${p}" | grep -c . || true)"
        [ "${tr_n}" = "0" ] || BAD=1
        sz="$(du -sb -- "${LIVE}/${p}" 2>/dev/null | awk '{print $1}')"; sz="${sz:-0}"
        TOTAL=$((TOTAL + sz))
        shape="other"; case "${p}" in comms/research/RQ-*) shape="RQ-unit" ;; esac
        printf '%s\t%s\t%s\t%s\n' "${sz}" "${tr_n}" "${shape}" "${p}"
    done <<< "${LIST}"
    awk -v t="${TOTAL}" 'BEGIN{printf "total: %.2fG (%d bytes)\n", t/1073741824, t}'
    echo "list_sha256: ${SHA}"
    if [ "${BAD}" != "0" ]; then echo "REFUSED: a path is outside comms/research or holds a tracked file. Nothing removed."; exit 3; fi
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing removed. Re-dispatch with apply: true and confirm: ${SHA}"; exit 0; fi
    if [ "${CONFIRM}" != "${SHA}" ]; then
        echo "REFUSED: confirm '${CONFIRM}' != list_sha256 ${SHA} (the list changed or was not reviewed). Nothing removed."; exit 3
    fi
    while IFS= read -r p; do
        [ -n "${p}" ] || continue
        "${G[@]}" clean -fdx -q -- "${p}"
    done <<< "${LIST}"
    LEFT="$("${G[@]}" clean -ndx -- comms/research | grep -c . || true)"
    echo "removed ${N} paths; still untracked under comms/research: ${LEFT}"
    echo "tracked files missing from disk after clean (must be 0): $("${G[@]}" ls-files -d -- comms/research | grep -c . || true)"
    ;;
prune-packed)
    wait_git_sync_idle
    "${G[@]}" count-objects -vH 2>/dev/null
    PLAN="$(cd "${LIVE}" && "${G[@]}" prune-packed -n 2>/dev/null | sed -n 's/^rm -f //p')"
    PN="$(printf '%s' "${PLAN}" | grep -c . || true)"
    PB="$(cd "${LIVE}" && printf '%s\n' "${PLAN}" | awk 'NF' | xargs -r -d '\n' stat -c %s 2>/dev/null | awk '{s+=$1} END{print s+0}')"
    awk -v n="${PN}" -v b="${PB}" 'BEGIN{printf "prune-packed would remove: %d loose objects, %.2fG (each already in a pack)\n", n, b/1073741824}'
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing removed. Re-dispatch with apply: true."; exit 0; fi
    timeout 1800 "${G[@]}" prune-packed
    "${G[@]}" count-objects -vH 2>/dev/null
    echo "post-check, every tree of HEAD readable: $(timeout 600 "${G[@]}" ls-tree -r HEAD >/dev/null 2>&1 && echo ok || echo FAILED)"
    echo "post-check, worktree clean vs HEAD: $("${G[@]}" status --porcelain --untracked-files=no | grep -c . || true) modified entries"
    ;;
rehearse-sideclone)
    if [ "${APPLY}" != "true" ]; then
        echo "planned: depth-1, blob:limit=5m, sparse (deploy/vm-sparse-checkout) clone at ${SIDE_DIR};"
        echo "         VM-SPARSE-SYNC block of scripts/deploy_pull_restart.sh run there twice;"
        echo "         check_ib_gateway.py --dry-run from it. Live dir untouched. Needs >= 6G free."
        echo "DRY-RUN: nothing created. Re-dispatch with apply: true."; exit 0
    fi
    if [ "$(avail_b)" -lt $((6 * 1073741824)) ]; then echo "REFUSED: under 6G free."; exit 3; fi
    [ -e "${SIDE_DIR}" ] && { echo "REFUSED: ${SIDE_DIR} exists; run target: sideclone-remove first."; exit 3; }
    URL="$("${G[@]}" remote get-url origin)"
    echo "origin: ${URL%%@*}..." | sed -E 's#https://[^/]*@#https://<cred>@#'
    t0=$(date +%s)
    git clone --depth 1 --single-branch --branch main --no-checkout \
        --filter=blob:limit=5m "${URL}" "${SIDE_DIR}" 2>&1 | tail -n 3
    S=(git -c safe.directory="${SIDE_DIR}" -C "${SIDE_DIR}")
    "${S[@]}" config core.sparseCheckout true
    "${S[@]}" config core.sparseCheckoutCone false
    "${S[@]}" show origin/main:deploy/vm-sparse-checkout | tee "${SIDE_DIR}/.git/info/sparse-checkout" >/dev/null
    "${S[@]}" checkout -q main 2>&1 | tail -n 3
    echo "clone+checkout: $(( $(date +%s) - t0 ))s; shallow=$("${S[@]}" rev-parse --is-shallow-repository); HEAD=$("${S[@]}" log -1 --format='%h %cI')"
    echo "live HEAD: $("${G[@]}" log -1 --format='%h %cI')"
    echo "side .git: $(du -sh "${SIDE_DIR}/.git" | awk '{print $1}')  side worktree: $(du -sh --exclude=.git "${SIDE_DIR}" | awk '{print $1}')"
    # The git-sync path, verbatim from the side clone's own copy of deploy_pull_restart.sh.
    BLOCK="$(sed -n '/>>> VM-SPARSE-SYNC begin/,/<<< VM-SPARSE-SYNC end/p' "${SIDE_DIR}/scripts/deploy_pull_restart.sh")"
    [ -n "${BLOCK}" ] || { echo "ERROR: VM-SPARSE-SYNC block not found"; exit 5; }
    for tick in 1 2; do
        echo "--- sync tick ${tick} (VM-SPARSE-SYNC block, cwd=${SIDE_DIR}) ---"
        PRE="$("${S[@]}" rev-parse HEAD)"; t0=$(date +%s)
        if (cd "${SIDE_DIR}" && bash -c "set -euo pipefail; ${BLOCK}" 2>&1 | tail -n 6); then rc=0; else rc=$?; fi
        POST="$("${S[@]}" rev-parse HEAD)"
        echo "tick ${tick}: rc=${rc} $(( $(date +%s) - t0 ))s ${PRE:0:9} -> ${POST:0:9}; shallow=$("${S[@]}" rev-parse --is-shallow-repository); commits_held=$("${S[@]}" rev-list --count HEAD)"
        echo "tick ${tick}: gateway branch would: $([ "${PRE}" = "${POST}" ] && echo 'no-op (HEAD unchanged)' || echo 'install_systemd_units.sh + restart gateway timers (NOT run in rehearsal)')"
        echo "tick ${tick}: status: $("${S[@]}" status --porcelain | grep -c . || true) dirty entries; diff --name-only PRE..POST ok: $("${S[@]}" diff --name-only "${PRE}" "${POST}" >/dev/null 2>&1 && echo yes || echo NO)"
        [ "${tick}" = 1 ] && sleep 330
    done
    echo "--- check_ib_gateway.py --dry-run from the side clone ---"
    mkdir -p /tmp/gwdisk-rehearsal && cp -f "${LIVE}/runtime_logs/ib_gateway_watchdog_state.json" /tmp/gwdisk-rehearsal/state.json 2>/dev/null || echo "(no live watchdog state file to copy)"
    if (cd "${SIDE_DIR}" && timeout 180 /usr/bin/python3 -u scripts/check_ib_gateway.py --probe-account ib_paper \
          --probe-script scripts/ops/ib_gateway_local_probe.py --state /tmp/gwdisk-rehearsal/state.json \
          --restart-after 2 --max-restarts 3 --cooldown-min 20 --max-backoff-min 60 --dry-run 2>&1 | tail -n 15); then
        echo "check_ib_gateway.py --dry-run: rc=0"
    else
        echo "check_ib_gateway.py --dry-run: rc=$?"
    fi
    echo "side .git after ticks: $(du -sh "${SIDE_DIR}/.git" | awk '{print $1}')"
    echo "who would need repointing (unit files naming the live path; none changed):"
    grep -l "${LIVE}" /etc/systemd/system/*.service /etc/systemd/system/*.timer 2>/dev/null | first 40 || true
    echo "untracked state in the live dir a swap must carry over:"
    for f in .env runtime_logs runtime_flags data logs; do
        [ -e "${LIVE}/${f}" ] && echo "  ${f}: $(du -sh "${LIVE}/${f}" 2>/dev/null | awk '{print $1}') tracked=$("${G[@]}" ls-files -- "${f}" | grep -c . || true)"
    done
    echo "live dir NOT touched; NO swap performed."
    ;;
sideclone-remove)
    [ -d "${SIDE_DIR}" ] || { echo "absent: ${SIDE_DIR}"; exit 0; }
    echo "planned: rm -rf ${SIDE_DIR} ($(du -sh "${SIDE_DIR}" | awk '{print $1}'))"
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing removed."; exit 0; fi
    [ "${SIDE_DIR}" != "${LIVE}" ] || exit 9
    sudo -n rm -rf --one-file-system -- "${SIDE_DIR}"
    ;;
swap-status)
    # Read-only: the health picture before/after the swap (no change on any path).
    health_report
    ;;
swap-sideclone)
    # Operator popup ~09:21Z 2026-11-05 "Do the swap (Recommended)" (relay; see row GATEWAY-DISK-CLEANUP).
    [ -d "${SIDE_DIR}/.git" ] || { echo "REFUSED: no side-clone at ${SIDE_DIR} (run rehearse-sideclone first)."; exit 3; }
    [ -e "${OLD_DIR}" ] && { echo "REFUSED: ${OLD_DIR} already exists (a previous swap is not cleaned up)."; exit 3; }
    hh=$(date -u +%H%M)
    if { [ "${hh}" -ge 0345 ] && [ "${hh}" -lt 0545 ]; } || { [ "${hh}" -ge 0555 ] && [ "${hh}" -lt 0620 ]; }; then
        echo "REFUSED: ${hh}Z is inside the IBKR reset window (03:45-05:45Z) or the 06:05Z reset-timer window."; exit 3
    fi
    echo "--- pre-swap health (live dir) ---"; health_report
    echo "planned: sync side-clone; copy the live dir's untracked/ignored files into it; mv ${LIVE} ${OLD_DIR}; mv ${SIDE_DIR} ${LIVE}"
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing changed."; exit 0; fi
    wait_git_sync_idle
    wait_unit_idle ict-ib-gateway-watchdog.service
    wait_unit_idle ict-ib-gateway-reset.service
    S=(git -c safe.directory="${SIDE_DIR}" -C "${SIDE_DIR}")
    BLOCK="$(sed -n '/>>> VM-SPARSE-SYNC begin/,/<<< VM-SPARSE-SYNC end/p' "${SIDE_DIR}/scripts/deploy_pull_restart.sh")"
    [ -n "${BLOCK}" ] || { echo "REFUSED: VM-SPARSE-SYNC block not found in the side-clone."; exit 5; }
    (cd "${SIDE_DIR}" && bash -c "set -euo pipefail; ${BLOCK}" 2>&1 | tail -n 3)
    echo "side HEAD $("${S[@]}" rev-parse --short HEAD); live HEAD $("${G[@]}" rev-parse --short HEAD); live origin/main $("${G[@]}" rev-parse --short origin/main)"
    # Untracked + ignored files of the live dir (runtime_logs/ state, flags, data, logs, .env if any).
    LST="$(mktemp)"; (cd "${LIVE}" && "${G[@]}" ls-files -o -z) > "${LST}"
    echo "carrying over $(tr -cd '\0' < "${LST}" | wc -c) untracked/ignored files ($(cd "${LIVE}" && xargs -0 -r du -cb -- < "${LST}" 2>/dev/null | tail -n1 | awk '{print $1}') bytes)"
    (cd "${LIVE}" && tar --null -T "${LST}" -cf - ) | (cd "${SIDE_DIR}" && tar -xpf -)
    rm -f "${LST}"
    echo "side status after carry-over (tracked changes must be 0): $("${S[@]}" status --porcelain --untracked-files=no | grep -c . || true)"
    if ! mv -T "${LIVE}" "${OLD_DIR}"; then echo "FAILED: first rename; nothing changed."; exit 6; fi
    if ! mv -T "${SIDE_DIR}" "${LIVE}"; then
        echo "FAILED: second rename; restoring."; mv -T "${OLD_DIR}" "${LIVE}" && echo "restored ${LIVE}"; exit 6
    fi
    echo "SWAPPED at $(date -u +%Y-%m-%dT%H:%M:%SZ): ${LIVE} is now the shallow clone; old checkout at ${OLD_DIR}"
    G=(git -c safe.directory="${LIVE}" -C "${LIVE}")
    echo "--- post-swap health (new live dir) ---"
    if ! health_report; then
        echo "FAILED post-swap health; reverting."; revert_swap; exit 7
    fi
    ;;
swap-revert)
    [ -d "${OLD_DIR}" ] || { echo "REFUSED: no ${OLD_DIR} to revert to."; exit 3; }
    echo "planned: mv ${LIVE} ${FAILED_DIR}; mv ${OLD_DIR} ${LIVE}"
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing changed."; exit 0; fi
    wait_git_sync_idle; wait_unit_idle ict-ib-gateway-watchdog.service
    revert_swap
    G=(git -c safe.directory="${LIVE}" -C "${LIVE}"); health_report || true
    ;;
old-remove)
    [ -d "${OLD_DIR}" ] || { echo "absent: ${OLD_DIR}"; exit 0; }
    [ "${OLD_DIR}" != "${LIVE}" ] || exit 9
    [ "$("${G[@]}" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ] || { echo "REFUSED: ${LIVE} is not the shallow clone; old checkout kept."; exit 3; }
    echo "planned: rm -rf ${OLD_DIR} ($(du -sh "${OLD_DIR}" 2>/dev/null | awk '{print $1}'))"
    health_report || { echo "REFUSED: health not clean; old checkout kept."; exit 3; }
    for u in ict-git-sync ict-ib-gateway-watchdog ict-ib-gateway-reset; do
        since="$(systemctl show -p ExecMainExitTimestamp --value "${u}.service" 2>/dev/null || true)"
        echo "${u}: last exit ${since:-never}"
    done
    if [ "${APPLY}" != "true" ]; then echo "DRY-RUN: nothing removed."; exit 0; fi
    sudo -n rm -rf --one-file-system -- "${OLD_DIR}"
    ;;
*) echo "ERROR: target must be journald|research-clean|prune-packed|rehearse-sideclone|sideclone-remove|swap-status|swap-sideclone|swap-revert|old-remove (got '${TARGET}')"; exit 2 ;;
esac

B1="$(avail_b)"
echo ">>> after: $(df_line)"
awk -v a="${B0}" -v b="${B1}" 'BEGIN{printf ">>> freed: %.2fG\n", (b-a)/1073741824}'
record_audit "gateway-disk-cleanup" "ok" "{\"target\": \"${TARGET}\", \"apply\": \"${APPLY}\"}" >/dev/null 2>&1 || true
