#!/usr/bin/env bash
# JOURNAL-OFFVM-BACKUP orchestrator (runs on the Actions runner).
#   backup        snapshot on the live VM (read-only) -> pull -> verify hash ->
#                 upload to the private versioned OCI bucket -> prune -> restore test
#   status        object counts / consecutive daily copies (names + counts only)
#   restore-test  restore the newest object into scratch and check it
# Env: VM_HOST VM_USER (ssh set up by the workflow), OCI_CLI_* , SCRATCH.
# Prints sizes, counts and object names only -- never row contents.
set -uo pipefail
MODE="${1:-backup}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="python3 $HERE/journal_offvm_backup.py"
SCRATCH="${SCRATCH:-$(mktemp -d)}"
RDIR="/tmp/journal_offvm_$$"
SSH="ssh -i $HOME/.ssh/id_rsa -o StrictHostKeyChecking=yes -o ConnectTimeout=20 -o BatchMode=yes ${VM_USER}@${VM_HOST}"
DBS="trade_journal:/data/bot-data/trade_journal.db trainer_store:/data/bot-data/trainer_store.db"
rc=0
cleanup() { $SSH "rm -rf '$RDIR'" >/dev/null 2>&1 || true; }
trap cleanup EXIT

backup_one() {  # label path -> 0 ok / 3 absent / else fail
  local label="$1" path="$2" meta
  meta="$($SSH "python3 - --db '$path' --out-dir '$RDIR' --label '$label'" < "$HERE/journal_snapshot_remote.py")" || return 1
  local state; state="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["state"])' "$meta")"
  [ "$state" = "absent" ] && { echo "$label: absent on live VM (skipped)"; return 3; }
  [ "$state" = "ok" ] || { echo "$label: snapshot state=$state"; return 1; }
  local want have
  want="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["sha256"])' "$meta")"
  $SSH "cat '$RDIR/$label.db.gz'" > "$SCRATCH/$label.db.gz" || return 1
  have="$(sha256sum "$SCRATCH/$label.db.gz" | cut -d' ' -f1)"
  [ "$want" = "$have" ] || { echo "$label: transfer hash mismatch"; return 1; }
  echo "$meta" > "$SCRATCH/$label.meta.json"
  $PY upload --db "$label" --file "$SCRATCH/$label.db.gz" || return 1
  python3 - "$SCRATCH/$label.meta.json" <<'PYM'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"{m['label']}: raw_bytes={m['raw_bytes']} gz_bytes={m['gz_bytes']} integrity={m['integrity']} tables={len(m['counts'])}")
PYM
}

restore_test() {  # label: newest object -> scratch -> integrity + counts vs snapshot meta
  local label="$1" dest="$SCRATCH/restore_$1.db.gz" v
  $PY fetch-latest --db "$label" --dest "$dest" || return 1
  v="$($PY verify --gz "$dest")" || { echo "$label: RESTORE integrity FAILED"; return 1; }
  python3 - "$SCRATCH/$label.meta.json" "$v" <<'PYV'
import json, sys
snap = json.load(open(sys.argv[1]))["counts"]
rest = json.loads(sys.argv[2])["counts"]
bad = {t: (snap.get(t), rest.get(t)) for t in set(snap) | set(rest) if snap.get(t) != rest.get(t)}
print(f"restore ok: tables={len(rest)} mismatches_vs_snapshot={len(bad)}")
for t in sorted(rest)[:12]:
    print(f"  {t}: restored={rest[t]} snapshot={snap.get(t)}")
sys.exit(1 if bad else 0)
PYV
}

live_delta() {  # label path: counts-only read of the LIVE db vs the restored copy (live >= backup expected)
  local label="$1" path="$2" live
  live="$($SSH "python3 - --db '$path' --out-dir '$RDIR' --label '$label' --counts-only" < "$HERE/journal_snapshot_remote.py" | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin)["counts"]))')" || { echo "live counts unavailable"; return 0; }
  python3 - "$SCRATCH/$label.meta.json" "$live" <<'PYL'
import json, sys
snap = json.load(open(sys.argv[1]))["counts"]; live = json.loads(sys.argv[2])
shrunk = {t: (snap[t], live.get(t)) for t in snap if live.get(t) is None or live[t] < snap[t]}
print(f"live-vs-backup: tables={len(snap)} shrunk_in_live={len(shrunk)} (live may only grow)")
for t in sorted(snap, key=lambda k: -snap[k])[:6]:
    print(f"  {t}: backup={snap[t]} live_now={live.get(t)}")
PYL
}

case "$MODE" in
  status) $PY status; exit $? ;;
  restore-test)
    $PY fetch-latest --db trade_journal --dest "$SCRATCH/r.db.gz" && $PY verify --gz "$SCRATCH/r.db.gz"; exit $? ;;
  backup)
    $PY ensure-bucket || exit 1
    for pair in $DBS; do
      label="${pair%%:*}"; path="${pair#*:}"; ok=1
      for attempt in 1 2 3; do
        backup_one "$label" "$path"; r=$?
        [ $r -eq 3 ] && { ok=0; break; }
        [ $r -eq 0 ] && { restore_test "$label" && ok=0 && live_delta "$label" "$path"; break; }
        echo "$label: attempt $attempt failed; retrying in $((attempt*20))s"; sleep $((attempt*20))
      done
      if [ $ok -ne 0 ]; then
        # The journal is the money DB: failure is a red flag. The sidecar is
        # best-effort (it may not live on this VM) and never fails the run alone.
        [ "$label" = "trade_journal" ] && rc=1 || echo "$label: not backed up (non-fatal)"
      fi
    done
    [ $rc -eq 0 ] && { $PY prune || rc=1; $PY status; }
    exit $rc ;;
  *) echo "unknown mode $MODE"; exit 2 ;;
esac
