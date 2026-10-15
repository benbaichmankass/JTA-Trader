#!/usr/bin/env python3
"""Off-VM, versioned, private backup of trade_journal.db -- OCI Object Storage side.

JOURNAL-OFFVM-BACKUP (Tier 2, operator-approved 2026-10-13). The snapshot itself
is taken on the live VM by scripts/ops/journal_snapshot_remote.py; this module
owns everything after the bytes reach the Actions runner: bucket (private,
versioning ON), dated object names, upload, retention pruning, status, and the
restore check. Uses the `oci` CLI with the same OCI_CLI_* secrets that
oci-inventory.yml / oci-storage.yml already use.

Retention: daily objects 30 days + weekly (Sunday) copies 12 weeks. A versioned
bucket keeps old versions after a plain delete, so pruning deletes every VERSION
of an expired name -- otherwise "retention" would silently keep everything.

Output is sizes, counts and object names only -- never row contents.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

BUCKET = os.environ.get("JOURNAL_BACKUP_BUCKET", "ict-journal-backups")
DAILY_DAYS = 30
WEEKLY_WEEKS = 12
_NAME_RE = re.compile(r"^(?P<db>[a-z_]+)/(?P<kind>daily|weekly)/(?P=db)-(?P<d>\d{8})\.db\.gz$")


def object_name(db: str, kind: str, day: dt.date) -> str:
    return f"{db}/{kind}/{db}-{day:%Y%m%d}.db.gz"


def parse_name(name: str):
    m = _NAME_RE.match(name)
    if not m:
        return None
    return m["db"], m["kind"], dt.datetime.strptime(m["d"], "%Y%m%d").date()


def kinds_for(day: dt.date):
    """A daily copy every day; a weekly copy additionally on Sundays."""
    return ["daily", "weekly"] if day.weekday() == 6 else ["daily"]


def prune_candidates(names, today: dt.date):
    """Names past retention. Unparseable names are NEVER pruned."""
    out = []
    for n in names:
        p = parse_name(n)
        if not p:
            continue
        _, kind, d = p
        age = (today - d).days
        if kind == "daily" and age > DAILY_DAYS:
            out.append(n)
        elif kind == "weekly" and age > WEEKLY_WEEKS * 7:
            out.append(n)
    return sorted(out)


def consecutive_daily(names, db: str, today: dt.date) -> int:
    have = {p[2] for n in names if (p := parse_name(n)) and p[0] == db and p[1] == "daily"}
    n, d = 0, today
    if d not in have:  # today's run may not have happened yet
        d -= dt.timedelta(days=1)
    while d in have:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def _oci(*args, check=True, want_json=True):
    cmd = ["oci", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.stderr.write(f"oci {' '.join(args[:3])} failed rc={r.returncode}: {r.stderr[-400:]}\n")
        raise SystemExit(r.returncode or 1)
    if r.returncode == 0 and want_json and r.stdout.strip():
        return json.loads(r.stdout)
    return r


def _ns():
    return _oci("os", "ns", "get")["data"]


def cmd_ensure_bucket(_a):
    ns = _ns()
    r = _oci("os", "bucket", "get", "--namespace-name", ns, "--bucket-name", BUCKET, check=False)
    if getattr(r, "returncode", 0) != 0:
        comp = os.environ["OCI_CLI_TENANCY"]  # root compartment, as oci-storage.yml does
        _oci("os", "bucket", "create", "--namespace-name", ns, "--compartment-id", comp,
             "--name", BUCKET, "--versioning", "Enabled", "--public-access-type", "NoPublicAccess")
        print(json.dumps({"bucket": BUCKET, "action": "created"}))
    else:
        r = _oci("os", "bucket", "get", "--namespace-name", ns, "--bucket-name", BUCKET)
        d = r["data"]
        if d.get("versioning") != "Enabled":
            _oci("os", "bucket", "update", "--namespace-name", ns, "--bucket-name", BUCKET,
                 "--versioning", "Enabled")
        print(json.dumps({"bucket": BUCKET, "action": "exists",
                          "public_access_type": d.get("public-access-type"),
                          "versioning": "Enabled"}))
    # Never leave a public bucket: assert the field, not the create flag.
    d = _oci("os", "bucket", "get", "--namespace-name", ns, "--bucket-name", BUCKET)["data"]
    if d.get("public-access-type") != "NoPublicAccess" or d.get("versioning") != "Enabled":
        sys.stderr.write(f"bucket not private+versioned: {d.get('public-access-type')}/{d.get('versioning')}\n")
        return 1
    return 0


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_upload(a):
    day = dt.datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else dt.datetime.now(dt.timezone.utc).date()
    ns = _ns()
    names = []
    for kind in kinds_for(day):
        name = object_name(a.db, kind, day)
        _oci("os", "object", "put", "--namespace-name", ns, "--bucket-name", BUCKET,
             "--name", name, "--file", a.file, "--force", want_json=False)
        names.append(name)
    print(json.dumps({"uploaded": names, "bytes": os.path.getsize(a.file)}))
    return 0


def _list_names(ns, prefix=""):
    args = ["os", "object", "list", "--namespace-name", ns, "--bucket-name", BUCKET, "--all"]
    if prefix:
        args += ["--prefix", prefix]
    r = _oci(*args, check=False)
    if getattr(r, "returncode", 0) != 0:
        sys.stderr.write("object list failed\n")
        raise SystemExit(1)
    return [o["name"] for o in r.get("data", [])] if isinstance(r, dict) else []


def cmd_prune(_a):
    ns = _ns()
    today = dt.datetime.now(dt.timezone.utc).date()
    doomed = prune_candidates(_list_names(ns), today)
    versions_deleted = 0
    for name in doomed:
        vs = _oci("os", "object", "list-object-versions", "--namespace-name", ns,
                  "--bucket-name", BUCKET, "--prefix", name, "--all")
        for v in (vs.get("data", []) if isinstance(vs, dict) else []):
            if v["name"] != name:
                continue
            _oci("os", "object", "delete", "--namespace-name", ns, "--bucket-name", BUCKET,
                 "--object-name", name, "--version-id", v["version-id"], "--force", want_json=False)
            versions_deleted += 1
    print(json.dumps({"pruned_names": len(doomed), "versions_deleted": versions_deleted}))
    return 0


def cmd_status(_a):
    ns = _ns()
    today = dt.datetime.now(dt.timezone.utc).date()
    names = _list_names(ns)
    out = {"bucket": BUCKET, "objects": len(names)}
    for db in ("trade_journal", "trainer_store"):
        out[db] = {
            "daily": sum(1 for n in names if (p := parse_name(n)) and p[0] == db and p[1] == "daily"),
            "weekly": sum(1 for n in names if (p := parse_name(n)) and p[0] == db and p[1] == "weekly"),
            "consecutive_daily": consecutive_daily(names, db, today),
        }
    print(json.dumps(out))
    return 0


def cmd_fetch_latest(a):
    """Download the newest daily object for --db into --dest (a scratch path)."""
    ns = _ns()
    names = [n for n in _list_names(ns, f"{a.db}/daily/") if parse_name(n)]
    if not names:
        sys.stderr.write("no daily object found\n")
        return 1
    latest = sorted(names)[-1]
    _oci("os", "object", "get", "--namespace-name", ns, "--bucket-name", BUCKET,
         "--name", latest, "--file", a.dest, want_json=False)
    print(json.dumps({"object": latest, "bytes": os.path.getsize(a.dest), "sha256": _sha(a.dest)}))
    return 0


def cmd_verify(a):
    """gunzip a downloaded object to a scratch DB, integrity_check, emit table counts."""
    raw = a.gz[:-3] if a.gz.endswith(".gz") else a.gz + ".out"
    with gzip.open(a.gz, "rb") as fi, open(raw, "wb") as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
    con = sqlite3.connect(f"file:{raw}?mode=ro", uri=True)
    integ = [r[0] for r in con.execute("PRAGMA integrity_check")]
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    con.close()
    os.remove(raw)
    print(json.dumps({"integrity": "ok" if integ == ["ok"] else integ[:3], "counts": counts}))
    return 0 if integ == ["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ensure-bucket").set_defaults(fn=cmd_ensure_bucket)
    u = sub.add_parser("upload")
    u.add_argument("--db", required=True)
    u.add_argument("--file", required=True)
    u.add_argument("--date")
    u.set_defaults(fn=cmd_upload)
    sub.add_parser("prune").set_defaults(fn=cmd_prune)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    f = sub.add_parser("fetch-latest")
    f.add_argument("--db", required=True)
    f.add_argument("--dest", required=True)
    f.set_defaults(fn=cmd_fetch_latest)
    v = sub.add_parser("verify")
    v.add_argument("--gz", required=True)
    v.set_defaults(fn=cmd_verify)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
