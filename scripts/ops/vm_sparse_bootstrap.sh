#!/usr/bin/env bash
# system-action wrapper (Tier 2): vm-sparse-bootstrap — one-time recovery of the
# live VM's checkout after #22365 (21.6 GB of comms/research caches) filled the
# 45G root disk (VM-SPARSE-SYNC, operator OK 2026-11-02: "let's try both fixes -
# better organizing the data").
#
# ⚠️ Runs WITHOUT the VM's on-disk scripts and WITHOUT a prior fetch: the VM is
# at 100% disk, its old deploy_pull_restart.sh dies inside an UNFILTERED fetch
# (packed-refs.new: No space left on device), and its checkout predates this
# file. system-actions.yml therefore pipes THIS file from the runner's checkout
# of main over ssh stdin (`bash -s`) and passes the sparse patterns
# (deploy/vm-sparse-checkout) base64-encoded in SPARSE_PATTERNS_B64.
#
# Order (apply):
#   1. df + sizes.
#   2. pause ict-git-sync.timer (restored on EXIT by trap) so an old-script tick
#      cannot run an unfiltered fetch into the freed space; wait for a running
#      ict-git-sync.service to finish.
#   3. delete the cache paths from the WORKING TREE by the exact
#      deploy/vm-sparse-checkout shapes under comms/research (find -delete; no
#      git), plus failed-fetch leftovers (.git/objects/pack/tmp_*,
#      packed-refs.new, stale *.lock); prints bytes freed.
#   4. write the sparse patterns + config, make the clone a partial clone
#      (promisor, blob:limit=5m), fetch --filter=blob:limit=5m.
#   5. reset --hard origin/main + read-tree -mu HEAD (the same block as
#      deploy_pull_restart.sh).
#   6. if .git is still > GIT_BLOAT_GB and git >= 2.36, repack dropping blobs
#      above the limit (they stay fetchable from the promisor), then prune.
#   7. df + HEAD.
# NEVER touches /data/bot-data, the journal DB, or any service but the
# ict-git-sync timer pause. The trader keeps running; the next ict-git-sync
# tick (new script) redeploys onto the new HEAD by its normal drift logic.
#
# Env (passed by system-actions.yml):
#   ACTION_APPLY         - "true" to mutate; anything else = dry-run (report only)
#   SPARSE_PATTERNS_B64  - base64 of deploy/vm-sparse-checkout (required for apply)
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ubuntu/ict-trading-bot}"
# Shared helpers from the VM's checkout when present (heal_devnull). Optional:
# this script must work even if the checkout is broken.
if [ -f "${REPO_DIR}/scripts/ops/_lib.sh" ]; then
    # shellcheck source=scripts/ops/_lib.sh
    source "${REPO_DIR}/scripts/ops/_lib.sh" || true
fi
type heal_devnull >/dev/null 2>&1 && { heal_devnull || true; }

APPLY="false"; [ "${ACTION_APPLY:-}" = "true" ] && APPLY="true"
BLOB_LIMIT="${VM_FETCH_BLOB_LIMIT:-5m}"
GIT_BLOAT_GB="${GIT_BLOAT_GB:-3}"
RESEARCH_DIR="${REPO_DIR}/comms/research"

if [ "$(id -u)" -eq 0 ]; then SYSTEMCTL=(systemctl); else SYSTEMCTL=(sudo -n systemctl); fi

say() { echo ">>> $*"; }
kb_used() { df -Pk / | awk 'NR==2{print $3}'; }
show_df() { say "df ($1):"; df -h / | sed 's/^/    /'; }

cd "${REPO_DIR}"
say "vm-sparse-bootstrap mode=$([ "${APPLY}" = true ] && echo APPLY || echo DRY-RUN) repo=${REPO_DIR}"
say "git $(git --version | awk '{print $3}') · HEAD $(git rev-parse HEAD 2>/dev/null || echo unknown)"
show_df "before"
say ".git size: $(du -sh .git 2>/dev/null | cut -f1)"

# --- the deletion set: the exact deploy/vm-sparse-checkout shapes ------------
# (dirs streams/ work/ candles/ anywhere under comms/research; files with the
# listed extensions anywhere under comms/research). Kept in sync with the
# pattern file by tests/ops/test_vm_sparse_bootstrap.py.
CACHE_DIRS=(streams work candles)
CACHE_EXTS=(pkl pickle npz npy parquet feather arrow h5 hdf5 joblib pt csv gz zip)

find_cache() {
    # -print0 list of every cache file (files inside cache dirs + by extension).
    [ -d "${RESEARCH_DIR}" ] || return 0
    local dir_expr=() ext_expr=() d e
    for d in "${CACHE_DIRS[@]}"; do dir_expr+=( -o -path "*/${d}/*" ); done
    for e in "${CACHE_EXTS[@]}"; do ext_expr+=( -o -name "*.${e}" ); done
    find "${RESEARCH_DIR}" -mindepth 1 \( -type f -o -type l \) \
        \( -false "${dir_expr[@]}" "${ext_expr[@]}" \) -print0
}
cache_bytes=$(find_cache | xargs -0 -r stat -c %s 2>/dev/null | awk '{s+=$1} END{print s+0}')
cache_files=$(find_cache | tr -cd '\0' | wc -c)
say "working-tree cache under comms/research: ${cache_files} files, $((cache_bytes / 1024 / 1024)) MiB"
leftovers=$(find .git/objects/pack -maxdepth 1 -name 'tmp_*' 2>/dev/null | wc -l)
say "failed-fetch leftovers in .git/objects/pack: ${leftovers} tmp_* file(s), $(find .git/objects/pack -maxdepth 1 -name 'tmp_*' -printf '%s\n' 2>/dev/null | awk '{s+=$1} END{printf "%d", s/1048576}') MiB"

if [ "${APPLY}" != "true" ]; then
    say "DRY-RUN: nothing changed. Re-dispatch with 'apply: true' to run steps 2-7."
    exit 0
fi

# CI-SPARSE-BOOTSTRAP-FLAKE: three distinct refusals, and no `printf | grep -q`
# pipe. Under `set -o pipefail` that pipe can report failure when grep exits on
# its first match before the writer finishes (SIGPIPE), which made the
# idempotent-second-run test refuse with patterns present (seen once in CI).
if [ -z "${SPARSE_PATTERNS_B64:-}" ]; then
    echo "ERROR: SPARSE_PATTERNS_B64 missing; refusing to apply." >&2
    exit 2
fi
PATTERNS="$(base64 -d <<<"${SPARSE_PATTERNS_B64}" 2>/dev/null || true)"
if [ -z "${PATTERNS}" ]; then
    echo "ERROR: SPARSE_PATTERNS_B64 is not valid base64 (${#SPARSE_PATTERNS_B64} chars); refusing to apply." >&2
    exit 2
fi
if [[ $'\n'"${PATTERNS}"$'\n' != *$'\n/*\n'* ]]; then
    echo "ERROR: SPARSE_PATTERNS_B64 is not a sparse pattern file (no '/*' line); refusing to apply." >&2
    exit 2
fi

# --- 2. pause the sync timer, restore it whatever happens ---------------------
TIMER_WAS_ACTIVE="false"
if "${SYSTEMCTL[@]}" is-active --quiet ict-git-sync.timer 2>/dev/null; then
    TIMER_WAS_ACTIVE="true"
    "${SYSTEMCTL[@]}" stop ict-git-sync.timer || say "WARNING: could not stop ict-git-sync.timer"
fi
restore_timer() {
    if [ "${TIMER_WAS_ACTIVE}" = "true" ]; then
        "${SYSTEMCTL[@]}" start ict-git-sync.timer && say "ict-git-sync.timer restarted." \
            || echo "WARNING: could not restart ict-git-sync.timer — start it by hand / restart-bot-service" >&2
    fi
}
trap restore_timer EXIT
for _ in $(seq 1 60); do
    "${SYSTEMCTL[@]}" is-active --quiet ict-git-sync.service 2>/dev/null || break
    sleep 2
done
"${SYSTEMCTL[@]}" is-active --quiet ict-git-sync.service 2>/dev/null \
    && say "WARNING: ict-git-sync.service still running after 120 s; continuing (it cannot fetch while the disk is full)."

# --- 3. delete caches + failed-fetch leftovers --------------------------------
used0=$(kb_used)
find_cache | xargs -0 -r rm -f --
[ -d "${RESEARCH_DIR}" ] && find "${RESEARCH_DIR}" -mindepth 1 -type d -empty -delete 2>/dev/null || true
find .git/objects/pack -maxdepth 1 -name 'tmp_*' -delete 2>/dev/null || true
rm -f .git/packed-refs.new .git/packed-refs.lock .git/index.lock .git/shallow.lock 2>/dev/null || true
find .git/refs -name '*.lock' -delete 2>/dev/null || true
used1=$(kb_used)
say "step 3 freed $(( (used0 - used1) / 1024 )) MiB (working-tree caches + fetch leftovers)."
show_df "after cache delete"

# --- 4. sparse config + partial clone + filtered fetch ------------------------
SPARSE_DST="$(git rev-parse --git-path info/sparse-checkout)"
mkdir -p "$(dirname "${SPARSE_DST}")"
printf '%s\n' "${PATTERNS}" > "${SPARSE_DST}"
git config core.sparseCheckout true
git config core.sparseCheckoutCone false
git config remote.origin.promisor true
git config remote.origin.partialclonefilter "blob:limit=${BLOB_LIMIT}"
say "sparse patterns written ($(grep -vc '^\s*\(#\|$\)' "${SPARSE_DST}") rules); origin is a promisor (blob:limit=${BLOB_LIMIT})."
git fetch --prune --filter="blob:limit=${BLOB_LIMIT}" origin
say "fetched: origin/main = $(git rev-parse origin/main)"

# --- 5. the deploy_pull_restart.sh sparse block -------------------------------
git reset --hard origin/main
git read-tree -mu HEAD || say "WARNING: git read-tree -mu HEAD failed — continuing."
say "HEAD now $(git rev-parse HEAD)"

# --- 6. drop already-packed large blobs if .git is bloated --------------------
git_kb=$(du -sk .git 2>/dev/null | cut -f1)
say ".git size after fetch: $((git_kb / 1024)) MiB"
if [ "${git_kb}" -gt $((GIT_BLOAT_GB * 1024 * 1024)) ]; then
    gv="$(git --version | awk '{print $3}')"
    if [ "$(printf '%s\n2.36\n' "${gv}" | sort -V | head -1)" = "2.36" ]; then
        say ".git > ${GIT_BLOAT_GB} GB — repacking without blobs above ${BLOB_LIMIT} (refetchable from the promisor)..."
        if timeout 540 git repack -a -d --filter="blob:limit=${BLOB_LIMIT}" \
                && timeout 120 git prune --expire=now; then
            say "repack done: .git now $(du -sh .git | cut -f1)"
        else
            say "WARNING: repack/prune failed or timed out — .git left as is (filed: PI-20261102-ARSESYNC-0002)."
        fi
    else
        say "git ${gv} < 2.36 has no 'repack --filter'; .git left as is (filed: PI-20261102-ARSESYNC-0002)."
    fi
fi

# --- 7. post-state ------------------------------------------------------------
show_df "after"
say "HEAD $(git rev-parse HEAD) · origin/main $(git rev-parse origin/main)"
say "working-tree cache files left: $(find_cache | tr -cd '\0' | wc -c)"
say "git status entries: $(git status --porcelain 2>/dev/null | wc -l)"
type record_audit >/dev/null 2>&1 && \
    record_audit "vm-sparse-bootstrap" "ok" "{\"freed_kb\": $((used0 - used1)), \"head\": \"$(git rev-parse HEAD)\"}" >/dev/null 2>&1 || true
say "done. The trader was not touched; the next ict-git-sync tick redeploys onto HEAD."
