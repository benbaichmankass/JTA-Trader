#!/usr/bin/env python3
"""Purge real-money / prop account balance and equity figures from the git HISTORY of this public repo.

PREPARATION TOOL (lane BALANCE-HISTORY-PURGE-PREP-20261123). Nothing here pushes; the manager runs the rewrite after review.
Runbook: docs/runbooks/account-balance-history-purge.md
# wiring: manual-only - one-off operator-gated history rewrite, run by the manager per the runbook (Tier 2/3), never from a schedule

Subcommands (all operate on a LOCAL --mirror clone path, never on a working checkout):
  selftest                       positive + negative controls for the redaction rules (no repo needed)
  scan    <mirror> [out.json]    inventory: every blob in the repo that matches the balance probe, mapped to path + commits
  rewrite <mirror>               run git-filter-repo on the mirror with the redaction callback (rewrites the mirror in place)
  verify  <mirror> [--dump F | --load F]   classified residual probe (REAL target 0; ALLOWED per named narrow rule, with samples); --load re-classifies a dump offline

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
RE_AG = re.compile(r'(["\'][A-Za-z_]*(?:balance|equity|net_?liquidation|buying_?power|wallet|cash)[A-Za-z_]*["\']\s*:\s*)(?:-?\d[\d.eE+\-]*|"-?\d[\d,.]*")', re.I)
_KEEP_KEY = re.compile(r"(?i)snapshots|rows|count|as_of|source|_n$|n_")

_FLOOR = r"(?:(?:above|below|to)\s+(?:the\s+)?(?:\$\s?[\d,.]+\s+)?(?:static[- ]?)?(?:dd[- ])?floor|distance[ _]to)"
WORDS = (r"(?<![A-Za-z])(?:equity|balances?|net[_ ]?liquidation|buying[ _]power|wallet|cushion|funded|cash|" + _FLOOR + r")(?![A-Za-z])")
AMT = r"~?-?\$\s?-?\d[\d,]*(?:\.\d+)?(?:[kKmM](?![A-Za-z]))?"
BIGNUM = r"-?\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|-?\b\d{3,}\.\d{2}\b"
#: B1: a trigger word followed (<= 60 chars, same line) by amounts -> every amount in that window is redacted
WINDOW = int(os.environ.get("PURGE_WINDOW", "120"))   # chars after a trigger word in which every amount is redacted; raise to over-redact
RE_B1 = re.compile(r"(?i)(?=(" + WORDS + r"[^\n]{0," + str(WINDOW) + r"}))")
RE_AMT = re.compile(AMT + "|" + BIGNUM)
#: B2: an amount followed (<= 25 chars) by a trigger word ("$99k of equity", "$12,345 above the floor"), or by "account" ("a $87,654 account")
RE_B2 = re.compile(r"(" + AMT + "|" + BIGNUM + r")(?=[^\n$]{0,40}" + WORDS + r"|\s?(?:[A-Za-z-]{1,12}\s)?account(?![A-Za-z_])|\s?start(?:ing)?(?![A-Za-z_])|\s?(?:risk|snapshot)(?![A-Za-z_]))", re.I)
#: B7: "<n>% on $amount" (a risk % applied to an account size)
RE_ON = re.compile(r"(\d%\s+(?:on|of)\s+)(" + AMT + ")", re.I)
#: B3: key=value / key: value with a bare number in prose (gate_balance=123.4, min_balance_usd: 99); counts/provenance kept
RE_B3 = re.compile(r"(?i)(?<![A-Za-z])([A-Za-z_]*(?:net_?liquidation|equity|balance|buying_power|wallet|cash)[A-Za-z_]*)(\s*(?:[=:]|≈|~)\s*)~?\$?-?\d[\d,]*(?:[  ]\d{3}\b)*(?:\.\d+)?")
#: B4: number with a currency suffix near a trigger word ("balance 1234.5 USDT")
RE_B4 = re.compile(r"(?i)(" + WORDS + r"[^\n$]{0,35}?)(?<![\w.])\d[\d,]*(?:\.\d+)?(\s?(?:USDT|USD)\b)")
#: B5: number + currency suffix followed (<= 20 chars) by a trigger word ("8765.4 USDT balance")
RE_B5 = re.compile(r"(?i)(?<![\w.])\d[\d,]*(?:\.\d+)?(\s?(?:USDT|USD)\b)(?=[^\n$]{0,20}" + WORDS + r")")
#: B8 (operator 2026-11-24 "Redact them"): prop-firm ACCOUNT-SIZE TIERS and the limits derived from them (a static-DD floor or daily-loss limit
#: back-solves the tier). An amount within 25 chars of a firm / tier / limit word, either side, plus "STATIC 9% = $N" equations.
FIRM = (r"(?<![A-Za-z])(?:breakout|tradeify|velotrade|topstep|apex|ftmo|funded ?next|prop(?:[- ]firm)?|tier|plan|eval(?:uation)?|challenge|"
        r"pass|profit target|static[- ]?dd|daily[- ]loss|drawdown|(?<!demo-)(?<!demo )(?<!pre-)(?<!post-)floor)(?![A-Za-z])")
RE_T1 = re.compile(r"(" + AMT + "|" + BIGNUM + r")(?=[^\n$]{0,25}" + FIRM + ")", re.I)
RE_T2 = re.compile(r"(" + FIRM + r"[^\n$]{0,25}?)(" + AMT + "|" + BIGNUM + ")", re.I)
RE_T3 = re.compile(r"((?:static|daily)[^=\n]{0,15}=\s*)(" + AMT + ")", re.I)
RED = "$[redacted]"


def in_scope(path: str) -> bool:
    return path.startswith(SCOPE_PREFIXES) and path.lower().endswith(TEXT_EXT)


STATS = collections.Counter()
_LINE_MEMO: dict = {}


def _dump_stats():
    f = os.environ.get("PURGE_STATS")
    if f and STATS:
        json.dump(dict(STATS), open(f, "w"))


import atexit  # noqa: E402

atexit.register(_dump_stats)
_TRIGGERS = ("equity", "balance", "liquidation", "buying", "wallet", "floor", "distance to", "distance_to", "cushion", "funded", "cash", "account",
             "pct_of_account", "budget_usd", "breakout", "tradeify", "velotrade", "topstep", "apex", "ftmo", "prop", "tier", "plan", "static", "daily", "drawdown", "challenge", "eval", "pass", "target")


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


_BALW = re.compile(r"(?i)(?<![A-Za-z])(?:balances?|equity|net[_ ]?liq\\w*|cash|buying[ _]?power|wallet|account value|nav)(?![A-Za-z])")
_AMT3 = re.compile(r"~?-?\$\s?-?\d[\d,]{2,}(?:\.\d+)?(?:[kKmM](?![A-Za-z]))?")
RE_B1X = re.compile(r"(?i)(?=(" + WORDS + r"(?:[^\n]|\n[ \t#>*|-]{0,12}){0,%d}))" % WINDOW)


def _b1x(s: str) -> str:
    """B1 across wrapped lines (YAML/markdown continuation): amounts within WINDOW chars after a trigger word, newlines allowed."""
    spans = []
    for m in RE_B1X.finditer(s):
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
    s = RE_ON.sub(lambda m: m.group(1) + RED, s)
    t0 = s
    s = RE_T3.sub(lambda m: m.group(1) + RED, s)
    s = RE_T2.sub(lambda m: m.group(1) + RED, s)
    s = RE_T1.sub(RED, s)
    if s != t0:
        STATS["tier_rule_distinct_lines"] += 1       # distinct lines (per-line memo) where the B8 tier-size rule changed something
    s = RE_B3.sub(_b3_sub, s)
    s = RE_B4.sub(lambda m: m.group(1) + "[redacted]" + m.group(2), s)
    s = RE_B5.sub(lambda m: "[redacted]" + m.group(1), s)
    if "$" in s and _BALW.search(s):                       # B6: a balance word anywhere on the line -> every $amount (3+ digits) on it
        s = _AMT3.sub(RED, s)
    return s


#: wrapped prose: an amount at the end of a line whose trigger word starts the next line, and the reverse
RE_WRAP1 = re.compile(r"(" + AMT + r")(?=[ \t]*\n[ \t>*#-]*[^\n$]{0,25}" + WORDS + r")", re.I)
RE_WRAP2 = re.compile(r"(" + WORDS + r"[^\n$]{0,60}\n[ \t>*#-]*[^\n$]{0,20}?)(" + AMT + r")", re.I)


def redact_bytes(path: str, data: bytes) -> bytes:
    if not in_scope(path) or b"\0" in data[:4000]:
        return data
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    out = "\n".join(_redact_line(ln) for ln in txt.split("\n"))
    if "$" in out and "\n" in out:
        out = RE_WRAP1.sub(RED, out)
        out = RE_WRAP2.sub(lambda m: m.group(1) + RED, out)
        out = _b1x(out)
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


#: retired registers deleted from ALL history (operator 2026-11-23). Not on main (retired 2026-09-21); path mentions in guards tolerate absence.
DELETE_GLOBS = ("docs/claude/*-backlog.json",)


def cmd_rewrite(mirror: str) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    # refs/pull/* cannot be pushed to GitHub (hidden refs); drop them from the REWRITE input so the result is exactly what is pushed.
    refs = subprocess.run(["git", "-C", mirror, "for-each-ref", "--format=delete %(refname)", "refs/pull"], capture_output=True, text=True,
                          check=True).stdout
    if refs.strip():
        subprocess.run(["git", "-C", mirror, "update-ref", "--stdin"], input=refs, text=True, check=True)
    subprocess.run(["git", "-C", mirror, "filter-repo", "--force", *[a for g in DELETE_GLOBS for a in ("--path-glob", g)], "--invert-paths", "--file-info-callback", FILTER_BODY % here], check=True)
    subprocess.run(["git", "-C", mirror, "reflog", "expire", "--expire=now", "--all"], check=True)
    # Repack is OPT-IN (manager 2026-11-24: skip it, GitHub repacks server-side). PURGE_REPACK=1 runs a memory-capped full repack
    # (plain gc keeps ~4.7 GiB, gc --aggressive is OOM-killed at 16 GB).
    if os.environ.get("PURGE_REPACK") != "1":
        return 0
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


#: Residual classification (manager review 2026-11-23: the first allowlist was too broad). PRECEDENCE:
#:   1. a NARROW rule that matches the KEY / PHRASE the amount is directly attached to  -> allowed (named rule)
#:   2. else a balance-class word within 40 chars of the amount (either side)           -> REAL
#:   3. else a NARROW context rule                                                      -> allowed
#:   4. else                                                                            -> REAL (unclassified)
#: Generic words (loss, delta, cost, exposure, notional, max_, minimum, trailing, tickers) never allowlist anything.
BALW = re.compile(r"(?i)(?<![A-Za-z])(balance|equity|net[_ ]?liq\w*|cash|buying[ _]?power|wallet|account value|nav)(?![A-Za-z])")
AMTV = re.compile(r"~?-?\$\s?-?\d[\d,]{2,}(?:\.\d+)?(?:[kKmM](?![A-Za-z]))?|(?<=[:=])\s?\"?-?\d[\d,]{2,}(?:\.\d+)?|-?\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")
ATTACHED = {   # matched against the <=40 chars immediately LEFT of the amount, anchored at its end
    "key_threshold": r"(?:min_balance_usd|min_equity_usd|static_dd_floor_usd|daily_loss_limit(?:_usd)?|risk_budget_usd|account_size_usd)[\"']?\W{0,6}$",
    "key_count_or_ratio": r"(?:n_affordable|n_refused_\w+|n_no_bars|days_below\w*|pct_equity|pct_of_equity)[\"']?\W{0,6}$",
    "threshold_param": r"N[≥>=]+\d+\s*/\s*$",
    "pnl_key": r"(?:pnl|p&l|realized|profit)(?:_usd)?[\"']?\W{0,8}$",
}
ATTACHED_RIGHT = {  # matched against the <=14 chars immediately RIGHT of the amount
    "price_per_share": r"^\s?(?:/|per\s)(?:share|sh)\b",
    "threshold_bleed": r"^\s?bleed",
}
CONTEXT_RULES = {   # only consulted when NO balance-class word is within 40 chars of the amount
    "demo_floor_stage_name": r"demo[- ]floor|soak \+ floor|pre-floor|post-floor|floor shipped",
    "balance_removed_marker": r"\[balance removed\]",
    "start_delta_marker": r"from its \$\[redacted\] start",
}
ATT_RE = {k: re.compile(v, re.I) for k, v in ATTACHED.items()}
ATTR_RE = {k: re.compile(v, re.I) for k, v in ATTACHED_RIGHT.items()}
CTX_RE = {k: re.compile(v, re.I) for k, v in CONTEXT_RULES.items()}
#: LEFT rules consulted only AFTER the balance-word check (a comparison threshold next to a balance word stays REAL)
LEFT_AFTER_BAL = {"comparison_threshold": re.compile(r"(?:\u2265|>=|<=|\u2264)\s*$")}


BALKEY = re.compile(r"(?i)(balance|equity|net_?liq|cash|buying_?power|wallet)[A-Za-z_]*[\"']?\s*[:=]\s*\"?$")
ANYKEY = re.compile(r"(?i)[A-Za-z_]+[\"']?\s*[:=]\s*\"?$")


NO_AMOUNT_OK = re.compile(r"(?i)min_balance_usd|risk_budget_usd|risk_pct|_pct_equity|pct_of_equity")


def classify(ctx: str, amt_start: int, amt_end: int):
    """-> (verdict, rule): verdict in {'allowed', 'real'}."""
    left, right = ctx[max(0, amt_start - 40):amt_start], ctx[amt_end:amt_end + 14]
    if ctx[amt_start:amt_start + 1] != "$" and ANYKEY.search(left):      # a bare number is judged by ITS key only
        for k, rx in ATT_RE.items():
            if rx.search(left):
                return "allowed", k
        if BALKEY.search(left):
            return "real", "balance_key_value"
        return "allowed", "non_balance_key_value"
    for k, rx in ATT_RE.items():
        if rx.search(left):
            return "allowed", k
    for k, rx in ATTR_RE.items():
        if rx.search(right):
            return "allowed", k
    if BALW.search(ctx[max(0, amt_start - 40):amt_start]) or BALW.search(ctx[amt_end:amt_end + 40]):
        return "real", "balance_word_near_amount"
    for k, rx in LEFT_AFTER_BAL.items():
        if rx.search(left):
            return "allowed", k
    for k, rx in CTX_RE.items():
        if rx.search(ctx):
            return "allowed", k
    return "real", "unclassified"


def cmd_verify(mirror, dump=None, load=None, samples=10):
    """Residual probe over branches + tags, in scope. --dump FILE saves every residual context; --load FILE re-classifies offline."""
    import random
    ctxs = collections.Counter()
    if load:
        ctxs.update({k: v for k, v in json.load(open(load)).items()})
    else:
        objs = _blobs(mirror, ["--branches", "--tags"])
        cand = [o for o, ps in objs.items() if any(in_scope(p) for p in ps)]
        q = subprocess.Popen(["git", "-C", mirror, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        import threading
        threading.Thread(target=lambda: (q.stdin.write("".join(c + "\n" for c in cand).encode()), q.stdin.close())).start()
        while True:
            h = q.stdout.readline()
            if not h:
                break
            _o, t, sz = h.split()
            d = q.stdout.read(int(sz))
            q.stdout.read(1)
            if t != b"blob" or int(sz) > 8_000_000 or not any(p in d for p in PRE) or b"\0" in d[:4000]:
                continue
            for rx in (PROBE_KEYS, PROBE_DOL, PROBE_DOL_REV):
                for m in rx.finditer(d):
                    c = d[max(0, m.start() - 80):m.end() + 60].decode("utf8", "replace").replace("\n", " ")
                    ctxs[c if False else re.sub(r"\d", "9", c)] += 1
        if dump:
            json.dump(ctxs, open(dump, "w"))
    verdicts = collections.defaultdict(list)   # (verdict, rule) -> [(ctx, n)]
    for c, n in ctxs.items():
        amts = list(AMTV.finditer(c))
        if not amts:
            ok = NO_AMOUNT_OK.search(c) and not re.search(r"\[redacted\][ \u00a0,]\d{3}", c) and not re.search(r"(?i)(balance|equity|cash|wallet|net_?liq)\w*\s*(?:\u2248|~|=|:)\s*\$?\d{3,}", c)
            verdicts[("allowed", "threshold_or_pct_key_no_amount") if ok else ("real", "no_amount_unrecognised")].append((c, n))
            continue
        res = [classify(c, a.start(), a.end()) for a in amts]
        worst = next((r for r in res if r[0] == "real"), res[0])
        verdicts[worst].append((c, n))
    rnd = random.Random(20261123)
    tot = collections.Counter()
    for (v, rule), lst in verdicts.items():
        tot[v] += sum(n for _, n in lst)
    print("REAL (target 0): %d matches in %d contexts | ALLOWED: %d matches" % (
        tot["real"], sum(len(lst_) for (v, _), lst_ in verdicts.items() if v == "real"), tot["allowed"]))
    for (v, rule), lst in sorted(verdicts.items(), key=lambda kv: (kv[0][0], -sum(n for _, n in kv[1]))):
        print("\n## %s / %s: %d matches, %d distinct contexts" % (v, rule, sum(n for _, n in lst), len(lst)))
        for c, n in (sorted(lst, key=lambda x: -x[1])[:samples] if v == "real" else rnd.sample(lst, min(samples, len(lst)))):
            print("  %4d  %s" % (n, repr(c[:250])))
    return 0 if not tot["real"] else 1


# ---- self-test: positive and negative controls (synthetic numbers only) -----------------------------------------------------------
def selftest() -> int:
    pos = {
        "comms/research/counterfactual_grades/x.json": '{"legs":[{"account_id":"a","equity_pre_usd": 123456.78,"pnl_usd_venue": 3.2}]}',
        "comms/gates/g.json": '{"equity_usd": 4321.5, "balance_usd": 4321.5, "distance_to_floor_usd": 321.5, "static_dd_floor_usd": 4000.0}',
        "docs/claude/b.json": '{"note": "bybit_2 equity $9,876.54 and balance ~$9876; net_liquidation=$99999.99, 8765.4 USDT balance"}',
        "docs/claude/w.md": "bybit_2 was live with $8,765\n  balance and the cushion\n  was $4,321 here",
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
        assert out != s and not [d for d in leaked if d.startswith(("123456", "4321", "9,876", "9876", "99999", "8765", "1,234", "777", "98765", "87654", "8,765", "4,321", "76543", "65,432", "54,321", "43,210"))], (p, out)
        json.loads(out) if p.endswith(".json") else None
    assert '"static_dd_floor_usd": 4000.0' in redact_bytes("comms/gates/g.json", pos["comms/gates/g.json"].encode()).decode()
    for p, s in neg.items():
        assert redact_bytes(p, s.encode()) == s.encode(), p
    def cls(t):
        a = list(AMTV.finditer(t))
        return [classify(t, x.start(), x.end())[0] for x in a]
    assert cls("alpaca_live balance $1,234 on the SPY line") == ["real"]          # ticker never allowlists
    assert cls("bybit_2 loss delta cost $5,000 exposure; equity $7,777") == ["real", "real"]
    assert cls('"min_balance_usd": 999') == ["allowed"] and cls("static_dd_floor_usd: 9999") == ["allowed"]
    assert cls("static-DD floor $9,999 on a balance $8,888 account") == ["real", "real"]
    assert cls("GLD at $999 per share") == ["allowed"] and cls("n_refused_cash: 999") == ["allowed"]
    assert cls("wallet truth -$777 vs journal") == ["real"]
    assert "4444" not in redact_text("sized_qty=9 with balance\u22484444 available") and "5555" not in redact_text("equity~5555 here")
    assert cls("pos_size: 999 risk_pct: 9.99 min_balance_usd: 99 snapshot_balance: 5555") == ["allowed", "real"]
    assert cls("under the $999 daily-loss limit") == ["real"]   # firm limits are no longer allowed: they are redacted (tier sizes)
    assert cls("balance >= $5,000 here") == ["real"] and cls("realized loss is \u2265 $999") == ["allowed"]
    assert "5,000" not in redact_text("at 2% on $5,000 and a $7,000 snapshot, ~$300 risk")
    assert redact_text("the 'balance': 12345.6 repro") != "the 'balance': 12345.6 repro"
    assert "$[redacted]" in redact_text("room k=9 +$999.99 and equity here, then $555 more")
    for t in ("a $9k Breakout account", "the $50K tier", "static-DD floor $9,999 here", "daily-loss limit $999", "Tradeify $150K plan",
              "Turbo STATIC 9% = $999 (floor $9,999)", "pass (>= $9,999) or die (<= $9,999 floor"):
        out = redact_text(t)
        assert not re.search(r"\$\s?\d", out), (t, out)
    assert redact_text("demo-floor sag +$9,999 and risk per ticket $50") == "demo-floor sag +$9,999 and risk per ticket $50"
    assert "999" not in redact_text("sized_qty=9 with balance\u2248123 999 available_usd=n/a")      # space-grouped thousands
    print("tier-size controls ok")
    print("classifier controls ok")
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
        kw = {}
        for flag, key in (("--dump", "dump"), ("--load", "load")):
            if flag in a:
                kw[key] = a[a.index(flag) + 1]
        sys.exit(cmd_verify(a[1] if not a[1].startswith("--") else None, **kw))
    print(__doc__)
    sys.exit(2)
