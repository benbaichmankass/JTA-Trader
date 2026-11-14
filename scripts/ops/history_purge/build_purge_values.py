#!/usr/bin/env python3
"""Build the LOCAL purge-values file for the account-balance history purge. Prints COUNTS ONLY; the file goes OUTSIDE the repo.

wiring: manual-only. OPS + manager run it inside the merge freeze (docs/runbooks/account-balance-history-purge.md section 2.2).
  python3 -I build_purge_values.py <mirror.git> <out-file> [--no-s3]
Reads every committed version (all refs) of the balance-carrying files, collects the numeric balance values, and writes one literal
per line. Specificity filter (measured: a zero or a round number matched thousands of unrelated tip files): drop zero and any literal
with fewer than 4 significant digits. It holds no value in this script; the output file must never be committed or printed.
"""
import json, re, subprocess, sys

mirror, out = sys.argv[1], sys.argv[2]
with_s3 = "--no-s3" not in sys.argv


def git(*a):
    return subprocess.run(["git", "-C", mirror, *a], capture_output=True).stdout


vals = set()


def walk(o, keys, under=None, inside=False):
    if isinstance(o, dict):
        for k, v in o.items():
            ins = inside or under is None or k == under
            if k in keys and ins and isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.add(repr(float(v)))
            else:
                walk(v, keys, under, ins)
    elif isinstance(o, list):
        for x in o:
            walk(x, keys, under, inside)


def blobs(pathspec, suffix):
    seen = set()
    for l in git("log", "--all", "--format=", "--raw", "--no-abbrev", "--", pathspec).decode().splitlines():
        p = l.split()
        if len(p) >= 6 and p[-1].endswith(suffix) and set(p[3]) != {"0"}:
            seen.add(p[3])
    return seen


counts = {}
for name, pathspec, suffix, keys, under in (
    ("S1 snapshots", "comms/mandate_evidence/account_snapshot/", ".json", {"equity_usd", "buying_power_usd", "cash_usd"}, None),
    ("S2 RQ-20261106-d5a1-01", "comms/research/RQ-20261106-d5a1-01/", ".json", {"equity_usd", "budget_usd"}, None),
    ("S3 reports", "comms/reports", "report.json", {"equity", "balance", "account_equity"}, "pnl_by_class"),
):
    if name.startswith("S3") and not with_s3:
        continue
    before = len(vals)
    bl = blobs(pathspec, suffix)
    for b in bl:
        try:
            walk(json.loads(git("cat-file", "-p", b)), keys, under)
        except ValueError:
            pass
    counts[name] = (len(bl), len(vals) - before)
# prose-only sites: the literal sits in text, so each is added by hand by OPS from the tip file (one regex per site, see the plan 0.2b)
sig = lambda l: len(re.sub(r"\D", "", l).lstrip("0").rstrip("0"))
keep = sorted(v for v in vals if float(v) != 0 and sig(v) >= 4)
open(out, "w").write("\n".join(keep) + "\n")
for k, (nb, nv) in counts.items():
    print(f"{k}: {nb} blob versions, {nv} new distinct values")
print(f"distinct {len(vals)}, kept after the specificity filter {len(keep)} -> {out} (never commit it)")
