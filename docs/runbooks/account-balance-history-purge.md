# Account balance / equity history purge (git history rewrite)

> **Doc status:** `live` · category `instruction` · last verified `2026-11-23` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)
>
> **Gates this adds or changes: none.** This is a one-off operation, not a standing rule. It is **prepared, not executed**: lane
> `BALANCE-HISTORY-PURGE-PREP-20261123` ran it only on a scratch `--mirror` clone. Nothing has been pushed.

**Why.** Operator, 2026-11-23: *"let's purge those numbers from the repo as well"*: real-money and prop account equity / balance
figures committed to this PUBLIC repo. The tip is guarded (`tests/test_no_balance_in_committed_research.py`); history is not.
**This document names fields and counts only. It never prints a value.**

Tool: `scripts/ops/purge_balance_history.py` (`selftest` · `scan` · `rewrite` · `verify`), driving `git-filter-repo` 2.47
(`pip install git-filter-repo`). It uses `--file-info-callback`, so rules are path-aware and every other byte is kept.

## 1. What is in history (inventory, 2026-11-23, tip `87570dab8a`)

Population: every blob in the repo's object store under 8 MB (199,009 of them; 8,566 matched the broad probe), mapped to commits on
`refs/heads/*` + `refs/tags/*` (**33,669 commits**, 2,377 branches). Probe: a key-with-number regex over 25 balance-like key names plus a
`balance word … $amount` / `$amount … balance word` prose regex. Positive control: the probe finds `balance_usd` and
`distance_to_floor_usd` in the 2026-11-14 gate-decision blob that entered at `caaf1da524` (2 commits, both 2026-11-14), and finds
`equity_pre_usd` in the counterfactual grade files. Commit counts below are commits that **introduced** a matching blob version.

| Class | In scope (docs/, comms/, research/, ROADMAP, config/) | Commits | First .. last |
|---|---|---|---|
| `budget_usd` (risk % x equity: back-solves a balance) | `comms/research/utilization/*` etc., 4 file shapes | 1,089 | 2026-10-13 .. 2026-11-23 |
| `net_liquidation` | review backlog JSON (prose + fields), 5 files | 1,613 | 2026-05-28 .. 2026-09-21 |
| `$` amounts in prose beside equity/balance words | 125 files (backlogs, ROADMAP, research docs, reports) | 3,002 | 2026-05-01 .. 2026-11-23 |
| bare `balance` / `equity` / `cash` keys | 46 files | 525 | 2026-05-19 .. 2026-11-17 |
| `equity_pre_usd` + `pct_of_account` | counterfactual grade files, 17 files | 16 | 2026-10-29 .. 2026-11-10 |
| `equity_usd` | 7 files | 9 | 2026-09-18 .. 2026-11-14 |
| `balance_usd`, `distance_to_floor_usd` | `comms/gates/gate_decisions_2026-11-14.json` | 2 | 2026-11-14 |
| `walletBalance`, `buying_power`, `cash_usd`, `account_equity` | 4 files | 1-6 each | 2026-05-10 .. 2026-10-23 |

Union: **4,414 in-scope commits** carry at least one hit blob. This is **much wider than the lane's starting list**: the biggest
surfaces are the free-text review backlogs (`docs/claude/*-backlog.json`, retired from the tip but still in history) and prose in
ROADMAP / research docs, not the structured grade files. Differences from the starting note: `equity_pre_usd` is 16 introducing commits
here against 49 commits that *touched* the grade files (touching includes later nulling).

Out of scope on purpose: `src/`, `tests/`, tools: hold **synthetic** fixtures (`equity=...`, `walletBalance` in test data). Not rewritten.
`static_dd_floor_usd` (a firm rule limit, not a balance) is kept.

## 2. The rules (what the rewrite does)

* **A, structured:** in JSON/JSONL under scope, the numeric value of `equity_pre_usd`, `equity_usd`, `balance_usd`,
  `distance_to_floor_usd`, `account_equity`, `totalEquity`, `total_equity`, `pct_of_account`, `budget_usd`, `net_liquidation`,
  `buying_power`, `cash_usd`, `walletBalance`, `available_balance` (and spellings) becomes `null`. Formatting is byte-preserved.
* **B, prose:** inside the same scope, a `$` amount within 120 characters after (`PURGE_WINDOW`, also across a wrapped line) (or 25 before) `equity | balance(s) | net_liquidation |
  buying power | wallet | distance to floor | cushion | funded`, and `key=number` / `<number> USDT` forms, becomes `$[redacted]` /
  `[redacted]`. **Heuristic.** It over-redacts (for example a `$50 risk` near the word balance) and can miss unusual phrasings.
  Both are visible in the dry run below; the over-redaction is accepted, the misses are measured by `verify`.
* **Deleted outright from all history:** `docs/claude/*-backlog.json` (retired registers, `DELETE_GLOBS` in the script). Archived copies under `docs/archive/**` are redacted, not deleted.
* `refs/pull/*` are dropped from the **rewrite input** (GitHub will not accept pushes to them anyway), so the result is exactly what is pushed.

## 3. Dry-run result (scratch mirror, nothing pushed; operator scope decision 2026-11-23: "Delete backlogs + iterate")

Final dry run against `main` `6a2d6bbeb67b`, rules as committed (`PURGE_WINDOW` default 120, wrapped-line rules, backlog deletion):

| Check | Result |
|---|---|
| Backlogs deleted from ALL history | `docs/claude/{health,ml,performance,research}-review-backlog.json`: 4 paths, 3,004 commits touched them, **0 remain** in rewritten history. Checked retired first: none exists on `main` (retired 2026-09-21; copies live in `docs/archive/2026-09-21-operating-reset/registers/`), the 45 files naming them are path lists in guards/docs/`.gitattributes` that tolerate absence, so the tip tree is unaffected. Archived copies under `docs/archive/**` are **redacted, not deleted** (same rules) |
| Commits | all reachable from branches + tags rewritten; 2,377 refs kept; `refs/pull/*` dropped from the rewrite input |
| Old tip -> new tip | `6a2d6bbeb67bd34ad4f9ea6f6f3348f00598de20` -> `39ba6215da58efee435b71a0cc73604ca07b1381` |
| Tip tree vs current main | 112,099 paths both sides; **0 added, 0 removed**; **1,743 files differ**; all 6,506 changed lines are `null` (5,420) / `[redacted]` (1,261); 0 line-count changes; 0 unexplained |
| Where the tip changed | `comms/research/utilization` ~1,033 (`budget_usd`), `docs/claude/work` ~209, `comms/reports` ~66, `docs/archive` ~18, `comms/research/RQ-*`, `comms/strategy_evidence`, gates, scores jsonl, ROADMAP |
| Residual probe (`verify`) | **(i) real balance/equity/cash values: 0 unclassified** after one reviewed entry. **(ii) allowlisted non-balance numbers: 1,929 matches** (`firm_limit_or_floor` 1,178; `config_threshold` 518; `pnl_fee_price` 181; `demo_floor_stage_or_package_pnl` 33; `counts_and_ratios` 19) plus 1 reviewed delta (`delta_vs_redacted_start`) |
| Size (packed) | 2.32 GiB before (with pull refs) -> 2.17 GiB after |
| Wall time | rewrite 19-26 min, `verify` ~25 min on 4 vCPU / 16 GB |

`verify` prints (i) unclassified candidates, which the operator or manager must read, and (ii) counts by named allowlist rule (`ALLOW` in the script: reviewed regexes for firm drawdown/daily-loss limits, config thresholds, P&L / fee / price, demo-floor stage names, counts and ratios).
Two iterations of misses were fixed by this loop (second amount beyond the window; amount and trigger word split across a wrapped line; `$N start`). **Honest limit:** 0 means "the probe, after the allowlist, finds none". The probe and
the rules are related patterns, so a phrasing neither covers survives, and the allowlist (ii) is a classification by regex, not a proof that each of 1,929 matches is a non-balance. Read the (ii) rule list once before the real run; re-run `verify` on the day.

Re-run on the day. Refs move, so counts and the new tip sha will differ. The dry-run numbers are a template, not the record.

## 4. Pre-flight (manager, before the window)

1. **Operator decision on scope**: class B is lossy and rewrites prose in ROADMAP / research docs at the tip. Confirm, or narrow `SCOPE_PREFIXES`.
2. **Pause lanes**: no dispatch, no merges, no routine PRs; `ict-git-sync` on the VMs keeps pulling `main`, so stop it (section 6) before the push.
3. **Freeze**: record the old tip (`git ls-remote origin refs/heads/main`) and a **backup**: keep the un-rewritten mirror
   (`git clone --mirror ... backup.git`, stored privately, **not** in the repo). It contains the data; treat it as sensitive.
4. **List what will need rebasing or recreation**: open PRs (24 at 2026-11-23) and all 2,377 branches. Every branch is rewritten, so every
   open PR's head moves; `gh pr list --state open --json number,headRefName` before, and again after. Branches not worth saving: delete.
5. **Branch protection on `main` must allow a force push for the window** (operator setting: Settings -> Branches -> rule for `main` ->
   "Allow force pushes", or remove the rule). Re-enable immediately after. Also check rulesets and "require linear history / signed commits".
6. Check `pip install git-filter-repo` works on the runner and that `python3 scripts/ops/purge_balance_history.py selftest` prints `selftest ok`.

## 5. Commands (fresh mirror, on a machine with ~12 GB free disk)

```bash
set -euo pipefail
git clone --mirror https://github.com/benbaichmankass/JTA-Trader work.git      # ~4 min
cp -a work.git backup.git                                                      # sensitive; keep private
python3 JTA-Trader/scripts/ops/purge_balance_history.py scan   work.git before.json   # inventory (about 10 min)
python3 JTA-Trader/scripts/ops/purge_balance_history.py rewrite work.git              # filter-repo + reflog expire + capped repack
python3 JTA-Trader/scripts/ops/purge_balance_history.py verify work.git               # expect exit 0 / 0 hits in scope
# tree check: the only differences must be redactions
git -C backup.git ls-tree -r main > old.tree; git -C work.git ls-tree -r main > new.tree
diff <(cut -f2 old.tree) <(cut -f2 new.tree) && echo "same path set"
git -C work.git log -1 --format=%H main            # the new tip
```

`rewrite` deletes `refs/pull/*` from the mirror first (not pushable). It runs `git filter-repo --force --file-info-callback <body>`; the
body imports `purge_balance_history.file_info`. Memory: the per-line memo is capped at 2M lines.

## 6. Push (operator or manager, inside the window)

```bash
# 1. stop the VM sync so nothing pulls a half-state (workflow/system-action; see docs/claude/system-actions.md)
# 2. force-push heads and tags only; refs/pull/* is read-only on GitHub
git -C work.git remote add origin https://github.com/benbaichmankass/JTA-Trader   # filter-repo removes origin
git -C work.git push --force --prune origin 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*'
```

Expect some branch pushes to be rejected (protected / rulesets). Handle each by name; do not widen protection permanently.
Check: `git ls-remote origin refs/heads/main` equals the new tip.

## 7. Post-steps

* **Every clone re-clones** (CI runners with persistent checkouts, the manager's and lanes' sandboxes, the operator's machines). A `git pull` into an old
  clone will merge old history back and **reintroduce the data**: tell everyone not to `git pull`/`push` from an old clone.
* **VM checkouts** (`/home/ubuntu/ict-trading-bot` on `ict-bot-arm`, `/opt/ict-trading-bot` on the trainer VM): `git fetch origin && git reset --hard origin/main && git reflog expire --expire=now --all && git gc --prune=now`;
  then re-check `ict-git-sync` is running and that untracked runtime data (DBs, `comms/` outputs the services write) is intact. Dispatch via the
  `vm-ops` / `system-actions` route, Tier-2 after an operator OK. Verify `git rev-parse HEAD` equals the new tip on both VMs and that the services still read their config.
* **Open PRs**: each one's head branch was rewritten. The old PR commits no longer match; rebase onto the new `main` (`git rebase --onto new/main <old-base> <branch>`) or close and
  recreate. Merged PR history is rewritten in place. Re-add `.github/pr-landing/*` and merge-slot claims if a branch is recreated.
* **CI**: clear Actions caches and any cache keyed on a commit sha; re-run the required checks; confirm `tests/test_no_balance_in_committed_research.py` is still green. Dependabot / auto-merge bots
  may reference old shas.
* **Docs that cite commit shas** (`caaf1da524`, `76977fe61e`, ...) now point at nothing; add a one-line mapping note in the PR that lands this, or accept the dangling references.
* Run `purge_balance_history.py verify` again against a **fresh clone** of GitHub, not the local mirror.

## 7b. Post-purge: gitleaks full-history scan + baseline regeneration (manager 2026-11-23, wake Wed 11-25)

The rewrite changes every commit SHA, so **every fingerprint in `.gitleaks-baseline.json` is stale** (gitleaks fingerprints include the commit). Do this on a runner
(`workflow_dispatch` of `gitleaks-history-weekly`, or a scratch clone in a workflow), never on a laptop, **after** the force-push and the protection toggle is back on:

1. **Scan the pushed history with the existing `.gitleaks.toml` and NO baseline** (`gitleaks detect --source . --redact=100 --no-banner --log-level error --exit-code 0 --report-format json --report-path new.json`).
   This scan **doubles as purge verification**: (a) none of the purged balance values may match anything (the redaction removed them; spot-check the previously flagged backlog files),
   (b) **no vendor-rule hit** (anything other than `generic-api-key`) may appear. A vendor hit is a stop-and-escalate, not a baseline row.
2. Triage by eye with `scripts/ops/gitleaks_summarize.py` (rule / file / commit / line, values masked). The 2026-11-23 weekly run (45211501436, 4th straight failure) had 14 `generic-api-key`
   findings, all false positives: 1 RFC 6455 sample `Sec-WebSocket-Key` (`.github/workflows/vm-net-diag.yml:99`), 10 SSH-key SHA256 fingerprints
   (`docs/claude/work/checklist/SEC-HOST-CHANGES-1112.json:19`), 3 rows quoting a test fixture (`GITLEAKS-HISTORY-FALSE-POSITIVES`), 1 row/pipeline id
   (`comms/reviews/ml-review-20261118-200000.json:124`). **Investigate why the `vm-net-diag.yml` entry, already in the baseline since 2026-11-16, was not matched** (Message / Date / Secret field drift)
   before regenerating, or the same entry will fail again.
3. **Regenerate `.gitleaks-baseline.json` from that scan**, keeping the four named known-revoked rows of `docs/security/gitleaks-baseline.md` (re-pointed at their new commit SHAs: find them by rule + file), and update the table in that doc.
   **Do not widen any rule or path allowlist.**
4. **Prove 0 new findings**: re-run with `--baseline-path .gitleaks-baseline.json` and require exit 0; and the planted-key proof (a scratch commit with a random synthetic `ghp_`-shaped string still fails, never pushed).
   Land the baseline as a normal Tier-1 PR. `tests/test_gitleaks_baseline.py` must pass.

## 7c. Timing (operator, 2026-11-23): Wednesday 11-25 morning, before the 18:00Z reset

Runbook PR merged and a **fresh dry run against current `main` by Wed 06:30Z**; the manager starts the sequence from a wake at 07:00Z: (1) ping the operator with the dry-run result; (2) operator toggles branch protection;
(3) one final operator confirmation; (4) pause lanes, force-push; (5) re-enable protection, run section 7; (6) section 7b. Keep it runner-side: sections 5 and 7b are scriptable in a single workflow
(`scan` -> `rewrite` -> `verify` -> tree check), so the manager's usage before the reset is spent on decisions, not typing. The dry run takes ~25 min rewrite + ~25 min verify on 4 vCPU.

## 8. LIMITS (stated honestly)

* **GitHub keeps the old commits.** Objects stay reachable through `refs/pull/*` (18,707 pull refs, which cannot be rewritten or deleted by a push) and in server-side caches until
  **GitHub Support** runs a garbage collection and drops cached views. **The operator must file that request** (support.github.com -> "Remove sensitive data from a repository";
  give the repo, the old tip sha, and ask for a cache purge + gc; ask that the pull-request refs be pruned). Until it is done, `git fetch origin 'refs/pull/*:...'` or a direct
  commit URL on the old sha can still return the old data.
* **Forks and existing clones keep the data**, as does anything that scraped or cached the repo (search indexes, archive sites, the Software Heritage archive, mirrors, Actions caches,
  other people's PR notifications by email).
* **The prose rules are heuristic.** `verify` is a second, wider probe, but a phrasing neither pattern knows will survive. A `0` from `verify` means "the probe found none", not
  "none exist". Spot-check a sample of old backlog blobs manually after the rewrite.
* **The purge reduces exposure; it does not erase what is already out.** If a figure is itself a security concern (an account number, a credential), rotate it; balances cannot be rotated.
* The tip still carries the same `src/` and `tests/` synthetic fixtures. Intended.
* Rewriting changes **every** commit sha: signatures on commits are gone, `git blame` links in old issues break, release tags are recreated pointing at new commits.
