# PI-20261103-RAM7EH86-0003: measure real per-job checkout disk on the trainer for each sparse profile (temp dir, deleted after).
set -u
T=$(mktemp -d /tmp/ckmeas.XXXX); cd "$T"; URL=https://github.com/benbaichmankass/JTA-Trader.git
echo "free before: $(df --output=avail -k / | tail -1 | awk '{printf "%.1f", $1/1048576}') GB"
meas() { # name depth patterns...
  n=$1; d=$2; shift 2; mkdir $n; cd $n; git init -q; git remote add origin $URL
  git sparse-checkout set --no-cone "$@" 2>/dev/null
  t0=$(date +%s); if [ "$d" = 0 ]; then git fetch -q --filter=blob:none origin main 2>&1|tail -1; else git fetch -q --filter=blob:none --depth $d origin main 2>&1|tail -1; fi
  git checkout -q FETCH_HEAD 2>&1 | tail -1; t1=$(date +%s)
  echo "$n: total=$(du -sm . | cut -f1)MB git=$(du -sm .git | cut -f1)MB secs=$((t1-t0))"; cd "$T"; rm -rf $n; }
meas infra 1 '/*' '!/comms/research/' '!/comms/macro/'
meas dispatch 0 '/*' '!/comms/research/RQ-*/**' '/comms/research/RQ-*/**/*.json' '!/comms/macro/'
# baseline: what the current full depth-1 checkout costs
mkdir full; cd full; git init -q; git remote add origin $URL; t0=$(date +%s); git fetch -q --depth 1 origin main; git checkout -q FETCH_HEAD; t1=$(date +%s); echo "full_depth1: total=$(du -sm . | cut -f1)MB git=$(du -sm .git | cut -f1)MB secs=$((t1-t0))"; cd "$T"; rm -rf full
cd /; rm -rf "$T"; echo "free after: $(df --output=avail -k / | tail -1 | awk '{printf "%.1f", $1/1048576}') GB"
