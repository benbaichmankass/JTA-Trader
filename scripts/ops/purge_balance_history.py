#!/usr/bin/env python3
"""Purge real-money / prop account balance and equity figures from the git HISTORY of this public repo.

PREPARATION TOOL (lane BALANCE-HISTORY-PURGE-PREP-20261123). Nothing here pushes; the manager runs the rewrite after review.
Runbook: docs/runbooks/account-balance-history-purge.md

Subcommands (all operate on a LOCAL --mirror clone path, never on a working checkout):
  selftest                       positive + negative controls for the redaction rules (no repo needed)
  scan    <mirror> [out.json]    inventory: every blob in the repo that matches the balance probe, mapped to path + commits
  rewrite <mirror>               run git-filter-repo on the mirror with the redaction callback (rewrites the mirror in place)
  verify  <mirror>               residual probe over the mirror's refs/heads + refs/tags (expects 0 hits in scope)

Two rule classes, applied only to files under SCOPE_PREFIXES with a text extension (src/ and tests/ hold synthetic fixtures and
are left alone; the tip diff is the check that nothing else moved):
  A  structured: the numeric value of a balance-bearing JSON key is replaced by null (formatting preserved byte-for-byte);
  B  prose: a $-amount (or bare number with a USD/USDT suffix) within a short window of a balance word is replaced by $[redacted].
Class B is a heuristic: it can over-redact (a "$50 risk" near the word balance) and can miss unusual phrasings. verify uses a
wider, independent window to measure what is left. Values are never printed by this tool; only counts and paths.
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys

SCOPE_PREFIXES = ("comms/", "docs/", "research/", "reports/", "ROADMAP.md", "CLAUDE.md", "README.md", "config/")
TEXT_EXT = (".json", ".jsonl", ".md", ".yaml", ".yml", ".html", ".txt", ".csv")

#: class A keys: numeric (or numeric-string) values are nulled. pct_of_account / budget_usd back-solve a balance.
KEYS_A = ("equity_pre_usd", "equity_usd", "balance_usd", "distance_to_floor_usd", "account_equity", "totalEquity", "total_equity",
          "pct_of_account", "budget_usd", "net_liquidation", "netLiquidation", "buying_power", "buyingPower", "cash_usd",
          "walletBalance", "wallet_balance", "available_balance", "wallet_balance_usd")
RE_A = re.compile(r'("(?:' + "|".join(KEYS_A) + r')"\s*:\s*)(?:-?\d[\d.eE+\-]*|"-?\d[\d,.]*")')
#: A2: ANY json key whose name carries a balance word (gate_balance, snapshot_balance, ...) with a numeric value; counts/provenance excluded
RE_AG = re.compile(r'("[A-Za-z_]*(?:balance|equity|net_?liquidation|buying_?power|wallet|cash)[A-Za-z_]*"\s*:\s*)(?:-?\d[\d.eE+\-]*|"-?\d[\d,.]*")', re.I)
_KEEP_KEY = re.compile(r"(?i)snapshots|rows|count|as_of|source|_n$|n_")

_FLOOR = r"(?:(?:above|below|to)\s+(?:the\s+)?(?:\$\s?[\d,.]+\s+)?(?:static[- ]?)?(?:dd[- ])?floor|distance[ _]to)"
WORDS = (r"(?<![A-Za-z])(?:equity|balances?|net[_ ]?liquidation|buying[ _]power|wallet|cushion|funded|cash|" + _FLOOR + r")(?![A-Za-z])")
AMT = r"~?-?\$\s?-?\d[\d,]*(?:\.\d+)?(?:[kKmM](?![A-Za-z]))?"
BIGNUM = r"-?\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|-?\b\d{3,}\.\d{2}\b"
#: B1: a trigger word followed (<= 60 chars, same line) by amounts -> every amount in that window is redacted
WINDOW = int(os.environ.get("PURGE_WINDOW", "60"))   # chars after a trigger word in which every amount is redacted; raise to over-redact
RE_B1 = re.compile(r"(?i)(?=(" + WORDS + r"[^\n]{0," + str(WINDOW) + r"}))")
RE_AMT = re.compile(AMT + "|" + BIGNUM)
#: B2: an amount followed (<= 25 chars) by a trigger word ("$99k of equity", "$12,345 above the floor"), or by "account" ("a $87,654 account")
RE_B2 = re.compile(r"(" + AMT + r")(?=[^\n$]{0,25}" + WORDS + r"|\s?(?:[A-Za-z-]{1,12}\s)?account(?![A-Za-z_]))", re.I)
#: B3: key=value / key: value with a bare number in prose (gate_balance=123.4, min_balance_usd: 99); counts/provenance kept
RE_B3 = re.compile(r"(?i)(?<![A-Za-z])([A-Za-z_]*(?:net_?liquidation|equity|balance|buying_power|wallet|cash)[A-Za-z_]*)(\s*[=:]\s*)~?\$?-?\d[\d,]*(?:\.\d+)?")
#: B4: number with a currency suffix near a trigger word ("balance 1234.5 USDT")
RE_B4 = re.compile(r"(?i)(" + WORDS + r"[^\n$]{0,35}?)(?<![\w.])\d[\d,]*(?:\.\d+)?(\s?(?:USDT|USD)\b)")
#: B5: number + currency suffix followed (<= 20 chars) by a trigger word ("8765.4 USDT balance")
RE_B5 = re.compile(r"(?i)(?<![\w.])\d[\d,]*(?:\.\d+)?(\s?(?:USDT|USD)\b)(?=[^\n$]{0,20}" + WORDS + r")")
RED = "$[redacted]"


def in_scope(path: str) -> bool:
    return path.startswith(SCOPE_PREFIXES) and path.lower().endswith(TEXT_EXT)


_LINE_MEMO: dict = {}
_TRIGGERS = ("equity", "balance", "liquidation", "buying", "wallet", "floor", "distance to", "distance_to", "cushion", "funded", "cash", "account",
             "pct_of_account", "budget_usd")


def _redact_line(ln: str) -> str:
    """All rules are single-line, so a per-line memo is exact and makes re-redacting near-identical file versions cheap."""
    r = _LINE_MEMO.get(ln)
    if r is None:
        low = ln.lower()
        r = redact_text(ln) if any(t in low for t in _TRIGGERS) else ln
        if len(_LINE_MEMO) < 2_000_000:
            _LINE_MEMO[ln] = r
    return r


def _b1(s: str) -> str:
    """Redact every amount within 60 chars after any trigger word. Windows overlap, so spans are merged, not consumed one by one."""
    spans = []
    for m in RE_B1.finditer(s):
        a, b = m.start(1), m.end(1)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    for a, b in reversed(spans):
        s = s[:a] + RE_AMT.sub(RED, s[a:b]) + s[b:]
    return s


def _key_sub(m):
    return m.group(0) if _KEEP_KEY.search(m.group(1)) else m.group(1) + "null"


def _b3_sub(m):
    return m.group(0) if _KEEP_KEY.search(m.group(1)) else m.group(1) + m.group(2) + "[redacted]"


def redact_text(s: str) -> str:
    s = RE_A.sub(lambda m: m.group(1) + "null", s)
    s = RE_AG.sub(_key_sub, s)
    s = _b1(s)
    s = RE_B2.sub(RED, s)
    s = RE_B3.sub(_b3_sub, s)
    s = RE_B4.sub(lambda m: m.group(1) + "[redacted]" + m.group(2), s)
    s = RE_B5.sub(lambda m: "[redacted]" + m.group(1), s)
    return s


def redact_bytes(path: str, data: bytes) -> bytes:
    if not in_scope(path) or b"\0" in data[:4000]:
        return data
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    out = "\n".join(_redact_line(ln) for ln in txt.split("\n"))
    return data if out == txt else out.encode("utf-8")


# ---- filter-repo glue -----------------------------------------------------------------------------------------------------------
_MEMO: dict = {}


def file_info(filename, mode, blob_id, value):
    """git-filter-repo --file-info-callback body (see FILTER_BODY). Memoised on (path-class, blob id)."""
    name = filename.decode("utf-8", "replace")
    if mode in (b"120000", b"160000") or not in_scope(name):
        return (filename, mode, blob_id)
    key = (name, blob_id)
    if key not in _MEMO:
        old = value.get_contents_by_identifier(blob_id)
        new = redact_bytes(name, old)
        _MEMO[key] = blob_id if new is old or new == old else value.insert_file_with_contents(new)
    return (filename, mode, _MEMO[key])


FILTER_BODY = (
    "import sys\nsys.path.insert(0, %r)\nimport purge_balance_history as p\nreturn p.file_info(filename, mode, blob_id, value)\n"
)


def cmd_rewrite(mirror: str) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    # refs/pull/* cannot be pushed to GitHub (hidden refs); drop them from the REWRITE input so the result is exactly what is pushed.
    refs = subprocess.run(["git", "-C", mirror, "for-each-ref", "--format=delete %(refname)", "refs/pull"], capture_output=True, text=True,
                          check=True).stdout
    if refs.strip():
        subprocess.run(["git", "-C", mirror, "update-ref", "--stdin"], input=refs, text=True, check=True)
    subprocess.run(["git", "-C", mirror, "filter-repo", "--force", "--file-info-callback", FILTER_BODY % here], check=True)
    subprocess.run(["git", "-C", mirror, "reflog", "expire", "--expire=now", "--all"], check=True)
    # memory-capped full repack (needed to shrink the pack; plain gc keeps 4.7 GiB, gc --aggressive was OOM-killed at 16 GB)
    subprocess.run(["git", "-C", mirror, "-c", "pack.windowMemory=400m", "-c", "pack.threads=2", "repack", "-a", "-d", "-f", "--window=50", "--depth=50", "-q"], check=True)
    return 0


# ---- inventory / verify (read-only) ---------------------------------------------------------------------------------------------
PROBE_KEYS = re.compile(rb"(?i)[\"']?(equity_pre_usd|equity_usd|balance_usd|distance_to_floor_usd|account_equity|totalequity|total_equity|"
                        rb"pct_of_account|budget_usd|net_?liquidation|buying_?power|wallet_?balance|cash_usd|equity|balance|cash)[\"']?\s*[:=]\s*\"?-?\d")
PROBE_DOL = re.compile(rb"(?i)\b(equity|balances?|net_?liquidation|buying power|cash|wallet|floor)\b[^\n]{0,90}\$\s?\d[\d,]{2,}")
PROBE_DOL_REV = re.compile(rb"(?i)\$\s?\d[\d,.]{2,}\s?[kKmM]?[^\n$]{0,40}\b(equity|balances?|net_?liquidation|buying power|wallet)\b")
PRE = (b"equity", b"balance", b"cash", b"buying", b"liquidation", b"floor", b"pct_of_account", b"budget_usd", b"Equity", b"Balance", b"Wallet")


def _blobs(mirror, refs):
    """{blob_sha: set(paths)} for every blob reachable from refs (rev-list --objects)."""
    out = subprocess.run(["git", "-C", mirror, "rev-list", "--objects", *refs], capture_output=True, text=True, check=True).stdout
    m = collections.defaultdict(set)
    for ln in out.splitlines():
        p = ln.split(" ", 1)
        if len(p) == 2:
            m[p[0]].add(p[1])
    return m


def probe(mirror, refs, only_scope=False):
    objs = _blobs(mirror, refs)
    types = subprocess.run(["git", "-C", mirror, "cat-file", "--batch-check"], input="\n".join(objs) + "\n", capture_output=True, text=True,
                           check=True).stdout.splitlines()
    cand = [ln.split()[0] for ln in types if ln.split()[1] == "blob" and int(ln.split()[2]) < 8_000_000]
    q = subprocess.Popen(["git", "-C", mirror, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    import threading
    threading.Thread(target=lambda: (q.stdin.write("".join(c + "\n" for c in cand).encode()), q.stdin.close())).start()
    hits = {}
    while True:
        h = q.stdout.readline()
        if not h:
            break
        o, _t, s = h.split()
        d = q.stdout.read(int(s))
        q.stdout.read(1)
        if not any(p in d for p in PRE) or b"\0" in d[:4000]:
            continue
        paths = objs[o.decode()]
        if only_scope and not any(in_scope(p) for p in paths):
            continue
        k = collections.Counter(m.group(1).decode().lower() for m in PROBE_KEYS.finditer(d))
        n = len(PROBE_DOL.findall(d)) + len(PROBE_DOL_REV.findall(d))
        if k or n:
            hits[o.decode()] = {"keys": dict(k), "dollar": n, "paths": sorted(paths)[:3]}
    return hits


def cmd_scan(mirror, out=None):
    hits = probe(mirror, ["--branches", "--tags"] if "--heads" in sys.argv else ["--all"])
    agg = collections.defaultdict(lambda: collections.Counter())
    for v in hits.values():
        for p in v["paths"][:1]:
            cls = "scope" if in_scope(p) else "out-of-scope(src/tests/other)"
            agg[cls]["blobs"] += 1
            for k, c in v["keys"].items():
                agg[cls]["key:" + k] += 1
            agg[cls]["dollar_blobs"] += 1 if v["dollar"] else 0
    print(json.dumps({k: dict(v) for k, v in agg.items()}, indent=1))
    if out:
        json.dump(hits, open(out, "w"))
    return 0


def cmd_verify(mirror):
    hits = probe(mirror, ["--branches", "--tags"], only_scope=True)
    tot = collections.Counter()
    for v in hits.values():
        for k in v["keys"]:
            tot[k] += 1
        tot["dollar_blobs"] += 1 if v["dollar"] else 0
    print("in-scope residual hit blobs:", len(hits), dict(tot))
    for o, v in list(hits.items())[:20]:
        print(" ", o[:10], v["paths"][0], v["keys"], v["dollar"])
    return 0 if not hits else 1


# ---- self-test: positive and negative controls (synthetic numbers only) -----------------------------------------------------------
def selftest() -> int:
    pos = {
        "comms/research/counterfactual_grades/x.json": '{"legs":[{"account_id":"a","equity_pre_usd": 123456.78,"pnl_usd_venue": 3.2}]}',
        "comms/gates/g.json": '{"equity_usd": 4321.5, "balance_usd": 4321.5, "distance_to_floor_usd": 321.5, "static_dd_floor_usd": 4000.0}',
        "docs/claude/b.json": '{"note": "bybit_2 equity $9,876.54 and balance ~$9876; net_liquidation=$99999.99, 8765.4 USDT balance"}',
        "ROADMAP.md": "alpaca_live balance $1,234.56 ; $50k of equity ; buying power: $777",
        "docs/claude/d.json": '{"snapshot_balance": 98765.43, "n": "gate_balance=87654.32 USD < min_balance_usd=76543.21; sits $65,432.10 above the floor; a $54,321 account; cash account holding ~$43,210"}',
    }
    neg = {
        "comms/x.json": '{"equity_as_of": "2026-11-06T01:00:13Z", "n_affordable": 138, "risk_pct": 0.02, "pnl_usd": 3.2}',
        "docs/claude/c.md": "risk per ticket is $50 and the fee is $0.12; no account figures here",
        "src/core/x.py": 'equity = 123456.78  # synthetic fixture, out of scope',
        "tests/t.json": '{"equity_usd": 1000.0}',
        "docs/claude/e.json": '{"balance_snapshots": 12, "rows_balance": 7, "note": "fee 0.12 per account, risk 0.02"}',
    }
    for p, s in pos.items():
        out = redact_bytes(p, s.encode()).decode()
        digits = re.findall(r"\d[\d,]{3,}(?:\.\d+)?", out)
        leaked = [d for d in digits if d.replace(",", "") not in ("4000.0", "2026", "1735")]  # static floor + year are not balances
        assert out != s and not [d for d in leaked if d.startswith(("123456", "4321", "9,876", "9876", "99999", "8765", "1,234", "777", "98765", "87654", "76543", "65,432", "54,321", "43,210"))], (p, out)
        json.loads(out) if p.endswith(".json") else None
    assert '"static_dd_floor_usd": 4000.0' in redact_bytes("comms/gates/g.json", pos["comms/gates/g.json"].encode()).decode()
    for p, s in neg.items():
        assert redact_bytes(p, s.encode()) == s.encode(), p
    print("selftest ok: %d positive, %d negative controls" % (len(pos), len(neg)))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(2)
    if a[0] == "selftest":
        sys.exit(selftest())
    if a[0] == "scan":
        sys.exit(cmd_scan(a[1], a[2] if len(a) > 2 and not a[2].startswith("--") else None))
    if a[0] == "rewrite":
        sys.exit(cmd_rewrite(a[1]))
    if a[0] == "verify":
        sys.exit(cmd_verify(a[1]))
    print(__doc__)
    sys.exit(2)
