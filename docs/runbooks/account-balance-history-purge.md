# Account-balance history purge: plan

> **Doc status:** `live` · category `instruction` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Row:** `ACCOUNT-SNAPSHOT-BALANCE-HISTORY` (Tier 3, owner AM-OPS). **Decision:** operator decisions page 2026-11-12, w2,
*"Purge with a history rewrite and force-push"*. **Author:** lane `session_01AFoLuMtnPz2CHSySqy6bWv`, dispatched by Manager
Session 2026-11-11a for AM-OPS. **Status: PLAN ONLY.** Nothing has been pushed or rewritten. The manager schedules the
freeze and runs it with OPS. **Nobody force-pushes alone.**

**Gates this adds or changes:** no permanent gate. It adds one **temporary merge freeze**, scheduled by the manager, and one
**temporary branch-protection relaxation** on `main`, flipped by the operator and reverted in the same window. §8 offers an
optional detector, but it is off the merge path, so it is not a gate.

This plan quotes no balance values. Each value is identified by an index (`value#1..#4`) into a sandbox-only file that
is never committed.

---

## 0. What the scan found (MEASURED 2026-11-12 on a fresh `git clone --mirror`)

**Population.** A mirror of `benbaichmankass/JTA-Trader` cloned 2026-11-12 ~10:50Z holds 2,040 `refs/heads/*`,
15,850 `refs/pull/*` and no tags. That is **52,687 commits** across all refs and **15,569** on `main`. The repo has
**0 forks** (GitHub API `forks_count`). There are **86 open PRs**, and every head branch is in this repo.

### 0.1 The row's two files (scope S1). Every balance-carrying version is listed.

Commits touching `comms/mandate_evidence/account_snapshot/` total 5 on `main` and 10 across all refs:

| commit | date (UTC) | ref | what |
|---|---|---|---|
| `2b5243ace4` | 2026-09-30 | PR branch (#14543) | first v1 snapshot. **Commit message quotes value#2** |
| `43e844e3cd` | 2026-09-30 | **main** (#14543) | squash of the above. **Commit message quotes value#2** |
| `7b6cc35d75` | 2026-10-16 | PR branch (#18500) | bybit_2 refresh |
| `ed645d6fd1` | 2026-10-16 | **main** (#18500) | bybit_2 refresh |
| `ce8f803947` | 2026-10-23 | PR branch (#19671) | alpaca_live refresh |
| `dbf133d871` | 2026-10-23 | **main** (#19671) | alpaca_live refresh |
| `b0afe883b4` / `0f320baa26` | 2026-11-01 | branch / **main** (#22134) | the fix: schema 2, no balance |
| `832d571409` / `d8d60fa846` | 2026-11-06 | branch / **main** (#23935) | schema-2 refresh, no balance |

There are seven distinct blobs of the two files across all refs. **Four of them carry balance fields**
(`equity_usd`, `buying_power_usd`, plus `cash_usd` on alpaca_live), all numeric:

| blob | file | values |
|---|---|---|
| `cb6e9154…` | alpaca_live.json v1 | value#3 |
| `d7990439…` | alpaca_live.json v1 | value#2 |
| `dc27f6d0…` | bybit_2.json v1 | value#4 |
| `fec468e7…` | bybit_2.json v1 | value#1 |

The other three blobs are schema 2 with `balance_committed: false`. The current tip of `main` is clean, and
`tests/test_mandate_resolver.py::test_committed_snapshots_carry_no_balance` pins that.

### 0.2 The wider history scan: every committed balance or equity field in `comms/`

**Probe:** `git log -G '"?(equity|buying_power|balance|wallet_balance|cash|net_liq|nav|available_margin|margin_balance)[A-Za-z_]*"?\s*[:=]\s*"?-?[0-9]' -- comms/`
(a numeric value under a balance-like key). **Population:** the 15,569 commits on `main`. **Hits:** 98 commits.
**Positive control:** the probe finds all 3 balance-carrying snapshot commits on `main` from §0.1. The
all-refs run (52,687 commits) found **212** commits: the 98 above plus **114 branch-only** commits (PR-branch copies). Every one falls in the **same families**; no new family turned up.

I triaged the 98 commits by key and path family:

| family | key | commits on main | still in the **tip** of main? | verdict |
|---|---|--:|---|---|
| `comms/strategy_evidence/**`, `comms/research/*/records/` | `equity_r` | ~37 | yes | **false positive**: backtest R-multiple curve |
| `comms/macro/*scorecard.json` | `rebalances`, `balance_every`, `final_equity`/`peak_equity` | ~20 | yes | **false positive**: simulated thesis equity, not an account |
| `comms/research/*/model*` | `is_unbalance`, LightGBM `booster_str` | 5 | yes | **false positive** |
| `comms/research/ML-ENTRY-UNIVERSE/…/summary.json` | `total_pct_equity` | 1 | yes | **false positive**: asset-class share |
| `comms/schema/system_report_response.template.json` | `equity` | 2 | yes | template placeholder; operator check |
| **`comms/mandate_evidence/account_snapshot/*.json`** | `equity_usd`, `buying_power_usd`, `cash_usd` | 3 | no | **S1, the row** |
| **`comms/research/counterfactual_grades/pkg-*.json`** | `legs[].equity_pre_usd` | 15 (2026-10-29 → 2026-11-10) | **yes, 17 files** | **S2: real money.** Legs are on `bybit_2` (real money) and `bybit_portfolio` (its mirror). Written by `scripts/research/cf_core.py:351`, still active: `#25025` landed 2026-11-11 |
| **`comms/research/RQ-20261106-d5a1-01/*/{measurement,verdict}.json`** | `equity_usd` (+ `equity_as_of`) | 2 (2026-11-06) | **yes, 4 files** | **S2: real money** (`account: alpaca_live`) |
| `comms/reports/{since-last,weekly,daily}/*/report.json` (2026-06-23 → 2026-08-29) | `consolidated.pnl_by_class.prop.{balance,equity}` | ~17 | yes, 17 files | **S3:** prop-class aggregate, meaning firm evaluation balances, not the operator's cash. Operator's call |
| `comms/follow_ups.json` | prose `balance=` in a prop_velotrade follow-up | 1 | yes | **S3: prop.** Operator's call |
| `comms/reports/since-last/20260807T145500Z/report.html` | prose: "alpaca_paper has $…k balance" | 1 | yes | **S3: paper.** Operator's call |

### 0.3 Balance values outside git (a rewrite cannot reach these)

I ran a GitHub issue/PR search for each exact value (positive control `"R-AFFORD" is:pr` returned 11). It found these, with
text-match fragments confirming an **exact** match in the body:

- **value#2** (alpaca_live equity, 2026-09-30) is in the bodies of **PRs #14543, #13698, #16428, #16556, #16548** and **issue #13787**.
- **value#3** (alpaca_live equity, 2026-10-23) is in the bodies of **13 issues**: `[system-action] pull-and-deploy` #21230,
  #21092, #21138, #20161, #20158, and `[diag-request] journalctl…` / `api/bot/config` #21273, #18188, #19529, #18314,
  #17452, #18333, #18261, #18259. **This is a live leak channel.** The trader's journal or config output prints account
  equity, and the diag and system-action relays post it into public issues. A 6-character exact match could be a
  coincidence on any single item, so review each one. Thirteen hits on one value is unlikely to be coincidence.
- value#1 and value#4 (bybit_2) had 0 hits.

These need PR and issue body edits. The owner must then delete the edit-history revisions. GitHub Support does not scrub
issue text. See §6 and §8.

### 0.4 Re-run on freeze day (every count above is dated)

The counts move every day: branches come and go, and S2 keeps growing until its writer is fixed. On freeze day, run
§2 on a fresh mirror and record the new counts beside these.

---

## 1. Scope and order. The recommendation is to fix the writers first, then rewrite ONCE

The operator decided on S1, the row. The scan shows that **S2 is real-money equity that is still being committed today**
(bybit_2 through the counterfactual grader, alpaca_live through RQ-20261106-d5a1-01). Rewriting history for S1 alone and
then needing a second rewrite for S2 would break every clone and PR twice. Recommended order:

1. **Writers first (Tier 1/2, normal PRs, no freeze):**
   - (a) `scripts/research/cf_core.py` must stop committing `equity_pre_usd`. Keep it in memory for sizing, or commit
     only a ratio such as `risk_pct_of_equity`. Null the 17 tip files. Add a test like
     `test_committed_snapshots_carry_no_balance` for `comms/research/counterfactual_grades/`.
   - (b) The RQ-20261106-d5a1-01 runner must stop committing `equity_usd`. Null the 4 tip files.
   - (c) The diag and system-action relays should mask account equity in the journal and config output they post. The
     redactor shared with `lane/ib-acctid-mask` (#25244) is the natural home.
2. **Operator decides S3** (prop-class aggregate and paper prose). The default is to leave S3 out: no operator money, and
   the S3 files are not account-identifying.
3. **One rewrite** covering S1 + S2 (+ S3 if chosen) in the commit messages and the files, in the single freeze window
   below.

If the operator wants S1 rewritten now regardless, §2 has the S1-only command and its measured dry run. The rest of the
plan is the same either way.

---

## 2. The tool: `git filter-repo` (v2.47.0, `a40bce548d2c`)

### 2.1 Callbacks (`scripts/ops/history_purge/`; they hold no values)

- **File-info callback** (S1 + S2): for paths matching
  `^comms/mandate_evidence/account_snapshot/[^/]+\.json$`, `^comms/research/counterfactual_grades/[^/]+\.json$` and
  `^comms/research/RQ-20261106-d5a1-01/.+\.json$`, parse the JSON and set every `equity_usd` / `buying_power_usd` /
  `cash_usd` / `equity_pre_usd` key to `null`. Setting them to `null` rather than deleting them keeps the readers'
  schemas valid. Every other path passes through byte-identical. Once the §1 writer fixes land, the **tip tree of
  `main` is unchanged**. That matters for §4: the VM sees a new HEAD with the same tree.
- **Message callback:** replace each exact balance literal with `[balance removed]`. The literals are read at run time
  from `PURGE_VALUES_FILE`, a local file built from the four blobs that is never committed. Only the exact literals are
  used. The scan showed that the rounded 3-digit forms appear in 300–445 unrelated commit messages each, so they are not
  safe to replace.

Both callbacks were tested on a synthetic repo. Balance keys came out `null`, the commit message was scrubbed, an
out-of-scope `equity_usd` under `other/` was untouched, and `git log --all -p` showed 0 remaining occurrences of the
test values.

### 2.2 Exact commands (run by OPS with the manager, inside the freeze, on a fresh mirror)

```bash
# (callback paths are relative to a JTA-Trader checkout; copy them beside jta.git or use absolute paths)
# 0. fresh mirror AFTER the freeze starts (so nothing lands mid-rewrite)
git clone --mirror https://github.com/benbaichmankass/JTA-Trader jta.git && cd jta.git
git show-ref > ../pre-refs.txt                      # rollback position (§7)
git bundle create ../pre-rewrite.bundle --all       # full offline backup, kept off-repo
# 1. build the literal file from the 4 known blobs (never committed, never printed)
for b in cb6e9154 d7990439 dc27f6d0 fec468e7; do git cat-file -p $b | python3 -c \
 'import json,sys;d=json.load(sys.stdin);[print(repr(d[k])) for k in ("equity_usd","buying_power_usd","cash_usd") if d.get(k) is not None]'; \
 done | sort -u > ../.purge-values
# 2. rewrite
PURGE_VALUES_FILE=../.purge-values git filter-repo --sensitive-data-removal --no-fetch \
  --file-info-callback "$(cat scripts/ops/history_purge/file_info_callback.filter-repo.txt)" \
  --message-callback  "$(cat scripts/ops/history_purge/message_callback.filter-repo.txt)"
# S1-only variant (the row as decided, if the operator overrides §1): replace the file-info callback with
#   --blob-callback "$(cat scripts/ops/history_purge/strip_balance_blobs.filter-repo.txt)"   # rewrites exactly the 4 blob ids above
# 3. verify (§7) BEFORE any push
# 4. push only branch heads (GitHub refuses writes to refs/pull/*; tags: none exist)
git push --force origin 'refs/heads/*:refs/heads/*'
```

`--sensitive-data-removal` makes filter-repo record the **first changed commits** and the **orphaned refs**, which the
Support request in §6 needs. filter-repo also writes `filter-repo/commit-map` (old→new SHA). **Commit that map** under
`docs/archive/2026-11-history-purge/commit-map.txt` after the push. Evidence records, PR bodies, checklist notes and
pipeline rows cite SHAs from after 2026-09-30, and once GitHub garbage-collects the old commits those citations stop
resolving. The map translates them. The map holds SHAs only, no values.

### 2.3 Dry-run counts (sandbox mirror, 2026-11-12)

The S1-only run (`--sensitive-data-removal --no-fetch --blob-callback`, 4 blob ids) on the full mirror (2,040 heads,
15,850 PR refs, 52,687 commits; 4 vCPU sandbox) **ran in 16 min 28 s** (906 s writing, then repack). Results:

| measure | result |
|---|---|
| commits rewritten | **52,663 of 52,687** (all refs); `main` 15,569 → 15,569 commits, **all with new SHAs** |
| refs changed | 17,888 = 2,038 `refs/heads/*` + 15,850 `refs/pull/*` (the latter cannot be pushed; Support handles them, §6) |
| "first changed commit" entries | 49 |
| the 4 balance blobs reachable (`rev-list --all --objects`) | **0** each (was 1 each) |
| old `43e844e3cd` / old `main` tip in the rewritten repo | absent (`merge-base` exit 128: object gone after the repack) |
| tip tree of `main`, old vs new | **identical** |
| balance literals in the snapshot path's full `git log --all -p` | **2**, down from 42 (positive control on the old mirror). Both are the **commit message** of #14543 (squash + branch), which the blob callback cannot reach. **The message callback in §2.1 is therefore required, S1-only included.** |
| `filter-repo/suboptimal-issues` | 17 abbreviated references in messages to commits that no longer exist (left as-is; harmless) |

⚠️ **Why every SHA changes, not only those after 2026-09-30.** Every commit sampled on `main` (2,000 of 2,000) carries
a signature (`gpgsig`): GitHub's PGP on squash merges, SSH on session commits. filter-repo 2.47 / git 2.43 **strip
signatures**, so every commit from the root down gets a new SHA, and history loses its "Verified" badges. With a
toolchain that re-imports signatures verbatim, commits before `43e844e3cd` would keep their SHAs and badges. I have not
verified that any filter-repo + git version available here does this, so do not count on it. The consequences:
- **Every SHA cited anywhere** (evidence records, PR bodies, checklist notes, pipeline rows, deploy markers, docs) goes
  stale, not only post-2026-09-30 ones. Committing the commit-map is mandatory.
- The operator must confirm **"Require signed commits" is OFF** on `main`. The public API and `[bp-report]` do not show
  it. If it is on, GitHub refuses the unsigned rewritten commits.

filter-repo rewrites abbreviated SHAs inside commit messages. It does **not** rewrite SHAs inside file contents.

---

## 3. Merge freeze (manager schedules it; AM and every lane are told)

**Why:** every branch and every clone made before the push is based on the old history. If anyone pushes a branch from
an old clone after the rewrite, GitHub accepts it, and a merge would bring the old commits back, balance blobs included.

**Window:** about 2 hours: a fresh mirror (~4 min), the rewrite (~17 min measured, §2.3), verification (~20 min,
because `log -S` over all refs is slow), the push of ~2,040 heads, VM convergence and the post-push checks. Pick a slot that avoids **05:17Z Monday** (`gitleaks-history-weekly`) and **05:23Z daily**
(`branch-protection-sync`, which re-PUTs protection, although it preserves `allow_force_pushes`). Choose a low-activity
trading hour, because §4 restarts the live trader once.

**T-24h:** the manager announces the window to every AM and lane, in the brief and through each AM's session. **T-2h:**
lanes push and park their work. **T-0:**

1. **Stop automation that writes to the repo.** The operator sets Settings → Actions → General → **"Disable actions"**
   for the window. That stops `claude-pr-automerge`, the research and data commit bots, `delete-merged-branches` and the
   prune workflows in one switch, and no per-workflow edits are needed. It is temporary and reverted at T+end, so it is
   not a gate.
2. **Archive or pause every lane session.** Each running cloud session holds an old clone (manager:
   `list_sessions`, then `interrupt_session` / `archive_session`).
3. Record the open-PR list (86 on 2026-11-12, listed in the row note). Re-list it at T-0.

**PRs afterwards.** All 86 open PRs have their head branch in this repo, and step 4 of §2.2 force-pushes **every**
rewritten `refs/heads/*`. Each open PR's head is therefore rewritten consistently with the new `main`, and GitHub updates
the PR to the new head. **No manual rebase is needed for a PR whose branch was pushed before T-0.** Edge cases:

- A branch pushed after the mirror was taken: refuse it, or delete it and have its lane re-create it from the new base.
  To find such branches after the push, list branches whose tip is not in the new commit-map and whose merge-base with
  new `main` is older than 2026-09-30.
- A PR whose diff suddenly shows thousands of commits has an old base. Fix it with
  `git rebase --onto origin/main <old-merge-base-mapped-via-commit-map> <branch>`, then `push --force-with-lease`.
- **Every lane re-clones** (cloud sessions start fresh, so this is automatic) or runs
  `git fetch origin && git reset --hard origin/<branch>`. **Never `git pull` / merge an old local branch.**

---

## 4. git-sync on the VMs (three checkouts, not two)

Three hosts run git sync on `/home/ubuntu/ict-trading-bot`:

| host | unit | what it does on a rewritten main |
|---|---|---|
| live trader `ict-bot-arm` | `ict-git-sync.timer` → `scripts/deploy_pull_restart.sh` | `git fetch --prune --filter=blob:limit=5m origin` then **`git reset --hard origin/main`**, which handles a non-fast-forward. **No re-clone needed.** |
| trainer `ict-trainer-vm` | `ict-trainer-git-sync.timer` → `scripts/ops/trainer_git_sync.sh` | `git fetch origin main` then **`git checkout --force -B main origin/main`**, which also handles a non-fast-forward. Restarts nothing. |
| gateway `ict-ib-gateway` | same `deploy_pull_restart.sh`, `/etc/ict-vm-role=gateway` short-circuit | reset, refresh units, bounce gateway timers. No trader. |

**Expected side effects. Read these before the push:**
- **One full restart of every `ict-*` unit on the live VM, the trader included.** After the rewrite, HEAD moves but the
  tree is identical, so `git diff <deployed_sha> <new HEAD>` is **empty**. The old SHA still resolves locally. Both the
  runtime gate and `TRADER-RESTART-GATE` treat an empty diff with a moved HEAD as **restart (fail-safe)**. Open positions
  keep their venue-side SL/TP, so this is a routine restart, but schedule it.
- **One large "N PRs merged" Telegram ping.** `notify_on_pull.py` lists `old..new`, every rewritten merge since
  2026-09-30, capped at `MERGE_PING_MAX_LISTED`. It is cosmetic, but warn the operator.
- The old objects, including the balance blobs, stay in each VM's local `.git` until gc. That data is private on the VM's
  disk, not public, so nothing is required. An optional cleanup is
  `git reflog expire --expire=now --all && git gc --prune=now` through the trainer relay (trainer) and a future
  allowlisted action (trader). No such action exists today, and this plan does not add one.

**Order and exact actions (Tier 2, one operator OK covers the window):**
1. Push (§2.2 step 4).
2. **Live trader:** dispatch `system-action` `pull-and-deploy` (`docs/claude/system-actions.md`), body
   `action: pull-and-deploy` / `reason: ACCOUNT-SNAPSHOT-BALANCE-HISTORY: converge onto rewritten main`. This forces the
   one restart now, while people are watching, instead of at the next 5-minute tick. Verify with `status-check` (services
   active, HEAD = new `main` tip) and a `diag_fetch` of `/api/diag/services` plus a fresh journal write.
3. **Trainer:** `trainer-vm-diag` with `cmd: cd /home/ubuntu/ict-trading-bot && bash scripts/ops/trainer_git_sync.sh && git rev-parse HEAD`. Expect the new tip.
4. **Gateway:** converges on its own timer. Verify with `gateway-disk-cleanup target: swap-status` (read-only; prints
   live HEAD and the last `ict-git-sync` result). HEAD should be the new tip.
5. If any host's HEAD is not the new tip after 10 minutes, re-run step 2 for the trader. The other two follow their own
   timers. As a last resort, re-clone through the existing `vm-sparse-bootstrap` path (trader only, Tier 2).

---

## 5. Branch protection: the exact settings, and the operator flips them

The current protection on `main`, read 2026-11-12 from the public branches API: protected; required status checks
`pytest-collect`, `pytest-run` and `guards`, enforcement **everyone** (`enforce_admins` true). There are no rulesets on
`main` (`GET /rules/branches/main` → `[]`). `branch-protection-sync.yml` re-PUTs protection daily at 05:23Z and on demand.
It **hard-sets `enforce_admins=true`** and **preserves** `allow_force_pushes`.

The rewritten head commits carry no check results. So with `enforce_admins` true, even an allowed force push is refused
by the required checks. To let the push through for the window:

1. **Operator** (repo owner/admin): Settings → Branches → `main` → edit:
   - tick **"Allow force pushes"** → *Specify who can force push* → the operator only, and
   - untick **"Do not allow bypassing the above settings"** (`enforce_admins` → false), so an admin push bypasses the
     required checks.
2. **The push is made with an admin identity.** The Claude GitHub App cannot bypass classic protection. In practice the
   **operator runs §2.2 step 4** from the verified mirror, with OPS and the manager on the call. Alternatively OPS hands
   the operator the verified `jta.git` as a bundle. I have not verified whether a session's git proxy can force-push to
   `main` at all. Do not plan on it.
3. **Revert immediately after the push:** untick "Allow force pushes", then dispatch `branch-protection-sync`
   (workflow_dispatch). It restores `enforce_admins=true` and the three required checks. Confirm with a
   `[bp-report]` issue (`branch-protection-report.yml`): `allow_force_pushes: false`, `enforce_admins: true`.

---

## 6. GitHub Support request: the operator must file it

**Yes, the repo owner must file it.** GitHub keeps the old commits reachable through `refs/pull/*` (15,850 PR refs, which
are read-only to us), cached PR diff views and commit URLs, until Support dereferences them and runs gc. Only the owner
can request that, at <https://support.github.com/contact> → "Remove sensitive data". `filter-repo --sensitive-data-removal`
prints the first changed commit(s) and the orphaned-ref count to attach.

**Draft (operator fills in the bracketed lines from the filter-repo output; no values in it):**

> Subject: Sensitive data removal: benbaichmankass/JTA-Trader (rewritten history, request PR-ref dereference and GC)
>
> I am the owner of the public repository benbaichmankass/JTA-Trader. Committed JSON files exposed private financial
> account information (account balances) under `comms/mandate_evidence/account_snapshot/` and
> `comms/research/counterfactual_grades/` (and `comms/research/RQ-20261106-d5a1-01/`), plus two commit messages. I rewrote
> the history with `git filter-repo --sensitive-data-removal` and force-pushed all branches on [DATE, UTC].
>
> - First changed commit(s) reported by filter-repo: [LIST]
> - Number of orphaned/affected refs reported: [N]
> - The repository has no forks.
>
> Please (1) dereference or remove the pull-request refs and cached views that still point at the old commits, and (2)
> run garbage collection so the old objects are no longer reachable by SHA. I understand affected PRs may lose their diff
> views. Thank you.

Before filing, edit the **PR and issue bodies listed in §0.3**: replace the value with `[balance removed]`, then delete
each body's earlier revisions from its "edited" history menu (owner/admin only). Support does not touch issue or PR text.

---

## 7. Rollback position and verification

**Rollback position (taken at T-0, before the rewrite):** `pre-refs.txt` (every ref → SHA) and `pre-rewrite.bundle`
(a full `--all` bundle). Both are kept **off the repo** in the OPS sandbox and with the operator, because they contain the
balances. Rollback is possible only until Support runs gc. It means re-pushing `refs/heads/*` from the bundle with the
same protection flip. **Rollback re-publishes the balances**, so use it only if the rewritten history is broken in a way
the commit-map cannot fix (for example, the VM cannot converge).

**Verification (run on the rewritten mirror before the push, and again on a fresh clone after it):**

1. `git merge-base --is-ancestor 43e844e3cd refs/heads/main` → **exit 1**: the old first-touched commit is not in main.
   Same for the old `main` tip from `pre-refs.txt`.
2. For each of the four blob ids in §0.1: `git rev-list --all --objects | grep -c <blob>` → **0**.
3. Every `PURGE_VALUES_FILE` literal: `git log --all -S"<literal>" --oneline | wc -l` → **0**, and
   `git log --all --format=%B | grep -cF "<literal>"` → **0**. Print counts only, never the literal.
4. `git rev-parse <old main tip>^{tree}` equals `git rev-parse refs/heads/main^{tree}` (same tip tree, once the §1
   writer fixes landed).
5. `pytest tests/test_mandate_resolver.py -k no_balance` and the new counterfactual-grades no-balance test pass.
6. After the push: §4 HEAD checks on all three VMs, and §5's `[bp-report]` shows protection restored.
7. After Support confirms: `curl -s -o /dev/null -w '%{http_code}' https://github.com/benbaichmankass/JTA-Trader/commit/43e844e3cd`
   → **404**.

---

## 8. Findings filed separately (outside the rewrite)

- **The counterfactual grader commits real-money equity (active).** `cf_core.py:351` writes `equity_pre_usd` per leg.
  Filed as row `CF-GRADES-EQUITY-COMMITTED` (it also covers the 4 RQ-20261106-d5a1-01 files).
- **Diag and system-action issues publish alpaca_live equity** in journal and config output (13 issues found for one
  value). Filed as row `DIAG-RELAY-EQUITY-LEAK`.
- **Optional detector, not a gate:** add the four old blob ids to the weekly `gitleaks-history-weekly` run as a
  "reintroduced old history" check. It reports and blocks nothing. The operator decides.
