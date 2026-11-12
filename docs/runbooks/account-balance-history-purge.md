# Account-balance history purge: plan

> **Doc status:** `live` · category `instruction` · last verified `2026-11-12` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

**Row:** `ACCOUNT-SNAPSHOT-BALANCE-HISTORY` (Tier 3, owner AM-OPS). **Decision:** operator decisions page 2026-11-12, w2,
*"Purge with a history rewrite and force-push"*. **Author:** lane `session_01AFoLuMtnPz2CHSySqy6bWv`, dispatched by Manager
Session 2026-11-11a for AM-OPS. **Status: PLAN ONLY.** Nothing has been pushed or rewritten. The manager schedules the
freeze and runs it with OPS. **Nobody force-pushes alone.**

**Scope widened (rev 2, 2026-11-12).** Decision: 2026-11-12 operator decisions page x5 *"Real-money and prop and paper balances"*.
The purge now covers **every account balance**: real-money, prop and paper. Rev 1 covered the two snapshot files (S1) plus the
counterfactual grades and RQ-20261106-d5a1-01 (S2). Rev 2 adds the report balances (S3, real + paper + prop) and the balance
literals quoted in code, docs, registers and research queue files (S4), and re-runs the scan and dry run at that scope. Author of
rev 2: lane of Manager Session 2026-11-11a. **Still PLAN ONLY**: nothing rewritten, nothing pushed to `main`; the purge runs after
PR #25305 (EQUITY-LEAK-STOP) merges.

**Gates this adds or changes:** no permanent gate. It adds one **temporary merge freeze**, scheduled by the manager, and one
**temporary branch-protection relaxation** on `main`, flipped by the operator and reverted in the same window. §8 offers an
optional detector, but it is off the merge path, so it is not a gate.

This plan quotes no balance values. Each value is identified by an index (`value#1..#4`) into a sandbox-only file that
is never committed.

---

## OPERATOR: what you do, what you file, what you will see (plain words)

You do three things on purge day. The manager runs everything else with you on a call. **Nothing here happens until PR #25305 is merged
and the manager has announced the freeze window.** The window is about **2 hours** (section 3).

### A. Allow force-push on `main`, then put it back (exact clicks)

Do these in order, with the manager and OPS on the call. Write down what each setting says **before** you change it, so you can put it back.

**Turn it on (just before the push):**
1. Open <https://github.com/benbaichmankass/JTA-Trader/settings/actions> → **Actions permissions** → choose **Disable actions** → **Save**.
   (Write down which option was selected before. This stops every bot that commits while the history is being replaced.)
2. Open <https://github.com/benbaichmankass/JTA-Trader/settings/branches> → under **Branch protection rules** click **Edit** next to `main`.
3. Scroll to **Allow force pushes** → tick it → choose **Specify who can force push** → add **yourself only**.
4. Scroll to **Do not allow bypassing the above settings** → **untick** it. If **Require signed commits** is ticked, untick it too and write
   that down: the rewritten commits are unsigned.
5. Click **Save changes** at the bottom (enter your password if GitHub asks).
6. Tell OPS "protection is open". **You** then run the one push command OPS gives you
   (`git push --force origin 'refs/heads/*:refs/heads/*'`, from the checked mirror). A session cannot make this push for you.

**Put it back (immediately after the push; do not wait for the checks):**
1. Same page → **Edit** next to `main` → **untick Allow force pushes** → **tick Do not allow bypassing the above settings**
   (and re-tick **Require signed commits** if it was on) → **Save changes**.
2. Open <https://github.com/benbaichmankass/JTA-Trader/settings/actions> → set **Actions permissions** back to what you wrote down → **Save**.
3. Open <https://github.com/benbaichmankass/JTA-Trader/actions> → **branch-protection-sync** → **Run workflow** → **Run workflow**.
   It re-applies the three required checks.
4. Tell the manager "protection is back". The manager confirms with the `[bp-report]` issue: `allow_force_pushes: false`, `enforce_admins: true`.

If a setting is not where this says, **stop and tell the manager**. Do not look for another route.

### B. The GitHub Support request (you file it; paste this)

Go to <https://support.github.com/contact> and pick **Remove sensitive data** (if there is no such choice, pick **Something else** and paste
the same text). OPS gives you the two things for the brackets: the push date, and `first-changed-commits.txt` from the rewrite to attach.
**The text holds no balance value.**

> **Subject:** Sensitive data removal: benbaichmankass/JTA-Trader (rewritten history; please dereference pull-request refs, clear cached views, run garbage collection)
>
> I am the owner of the public repository benbaichmankass/JTA-Trader. It had committed private financial account information (account
> balances of real-money, paper and prop-firm accounts) in JSON, Markdown and HTML files, in source code and test fixtures, and in
> commit messages. On [DATE, UTC] I rewrote the full history with `git filter-repo --sensitive-data-removal` and force-pushed every
> branch. The repository has no forks and no tags.
>
> filter-repo reported [N] first-changed commits (list attached as `first-changed-commits.txt`).
>
> Please:
> 1. Dereference or remove the **pull-request refs** (`refs/pull/*`) that still point at the old commits, so the old commits are no longer reachable.
> 2. Clear the **cached views** of the old commits, and the **cached pull-request diffs and file views** that still show the old content,
>    including through direct commit URLs.
> 3. Run **garbage collection** on the repository so the old objects cannot be fetched by SHA.
>
> I understand some old pull requests may lose their diff views. Please confirm when this is complete so that I can check that the old
> commit URLs return 404.

**Before you file:** the manager hands you the list of issue and pull-request bodies that quote a balance (section 0.3). Edit each one
(replace the number with `[balance removed]`), then open the **edited** menu on it and **Delete** the older revisions. GitHub Support
does not touch issue or PR text. After PR #25305 merges, the diag and system-action output is redacted, so that list stops growing.

### C. What will visibly change

- **Every commit gets a new ID**, on `main` and on every branch. Commit links and SHAs quoted anywhere (old PR comments, notes, docs)
  stop matching. A committed old-to-new map (`commit-map.txt`) translates them.
- **The green "Verified" badge disappears from every commit.** The rewrite cannot keep signatures. Authors and commit dates stay.
- **Open pull requests stay open with the same numbers.** Their branches are rewritten with the rest, so they keep working; a few may need
  a rebase (OPS lists them). After Support finishes, **old pull-request diff views may go blank or return 404**.
- **99 files on `main` change content** (paths in `scripts/ops/history_purge/tip-prescrub-paths.txt`, measured on the dry run): they stop
  showing a balance. Normal PRs fix them **before** the freeze, so on purge day the files on `main` come out identical.
- **The live trader restarts once** (converging onto the new history). The trainer and the IB gateway just re-sync. You get **one large
  "N PRs merged" Telegram ping**.
- **For about 2 hours nothing merges and the bots that commit are off.** Trading is not affected: open positions keep their SL/TP.
- **Every working copy of the repo** (yours and each lane's) must be re-cloned; the manager tells the lanes.
- **Edited issue and PR bodies** show an "edited" mark where a balance was removed.

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

### 0.2b Rev 2: the wider scan (every account balance; MEASURED 2026-11-12 on a second fresh mirror, 12:38Z)

**Population.** 2,058 `refs/heads/*`, 15,892 `refs/pull/*`, **52,848 commits** across all refs, no tags. Method: take every balance
value the committed files carry (read from the blobs; kept in a sandbox-only file, never printed), then search **all 156,469 reachable
text blobs under 3 MB, every ref** for each exact value (whole number, not inside a longer one), plus a key-name probe
(`equity|balance|buying_power|net_liq|wallet|cash` followed by a number of 3+ digits) outside `comms/research`. **Positive control:** the
probe finds the 4 known S1 blobs and the known S2 files. **Caveat (RULE ONE):** this finds values I could read from the files. A balance
that sits only in a form I did not extract (a rounded figure in prose, an image, a value under another key) is not proven absent.

What rev 1 missed, by family:

| family | what | on the tip of main? | verdict |
|---|---|---|---|
| **S2, more keys** | `counterfactual_grades/*.json` `per_account.*.pct_of_account` (with the same file's `pnl_usd` it back-solves the balance); RQ-20261106-d5a1-01 `budget_usd` (= risk % x balance); the balance inside RQ `note` / population strings, `run-manifest.json`, `record-inputs.json`, and the run command line in `logs/cmd-0.log` | yes (17 grade files, 9 RQ files) | real money. Key nulling alone leaves the literal in the strings and the log |
| **S3 reports, real money too** | `comms/reports/{since-last,weekly}/*/report.json` under `consolidated.pnl_by_class`: `real.account_equity`, `real.per_asset_class[].equity`, `paper.per_asset_class[].equity`, `prop.balance`, `prop.equity`, `prop.per_account[].balance/equity`, `prop.rule_distance.balance` | yes (25 paths: 20 `since-last` and 4 `weekly` files as `.json`/`.md`/`.html`, plus `reports/index.json`) | **real + paper + prop.** Rev 1 saw only the prop aggregate |
| **S4, balance literals quoted in text** | the S1 and RQ values written into prose or code: `scripts/ops/mandate_resolver.py`, `scripts/research/{alpaca_baseline_affordability,alpaca_live_book}.py`, `tests/test_mandate_resolver.py`, `config/accounts.yaml` (a comment), the `.github/pr-landing/*.json`, 24 `docs/**` files (10 in `docs/research`, 4 in the archive, 4 checklist rows (`STAGE2-MIRROR`, `DAILY-DD-SWITCH`, `PROD-LEGS-DSR-DECISION`, `SCOREBOARD-PNL-FIRST`; 4 `docs/claude/work/pipeline/*.json` items), 7 `tests/`, 3 `src/` (prop reconcile and parse, a refusal alert), 5 `research/queue/*.yaml`, `research/results/RQ-20261106-d5a1-01/*.jsonl`, `research/programmes/08-alpaca-live-book.yaml`, `comms/claude_strategy_scores.jsonl`; and older versions of `docs/claude/work/MANAGER-CHECKLIST.json` (233 blob versions hold an S1 or RQ value) | yes, 99 tip files in all with S2 and S3 (list: `scripts/ops/history_purge/tip-prescrub-paths.txt`) | real money (alpaca_live, bybit_2); some prose sites are paper/IB |
| **Prose, one-off** | a paper-equity sentence in `docs/research/alpaca-live-refusal-verdict-2026-09-07.md`, a net-liquidation figure in `docs/sprint-logs/S-MES-AUTOHEAL-2026-05-28.md`, `comms/follow_ups.json`, `.../report.html` | yes | paper / IB paper. Added by hand to the literal list |

**Not balances (verified collisions, left alone).** The same 5-digit figures also occur as ordinary numbers in backtest and market-data
files: 277 blobs under `comms/research/*/{data,cells,sims,arms,candles,corpus}`, `*.csv`, `*trades.jsonl` and `*paths.jsonl` hold a
numeric match. I did not check each one; the paths and the shape (price series, simulated equity paths) say they are not account
balances, and a literal scrub there would corrupt market data. **Two literals had to be dropped by a specificity rule:** a zero and a
round figure matched **4,079** unrelated tip files in the first dry run. The rule is in §2.1.

**Outside git (§0.3 stands).** The PR and issue bodies listed there. Nothing new turned up in this scan, because it searched git, not
GitHub text; **re-run the GitHub search for the S3 and RQ values too** before filing (not done in rev 2).

### 0.4 Re-run on freeze day (every count above is dated)

The counts move every day: branches come and go, and S2 keeps growing until its writer is fixed. On freeze day, run
§2 on a fresh mirror and record the new counts beside these.

---

## 1. Scope and order. Fix the writers and the tip first, then rewrite ONCE

The operator decided (2026-11-12) to purge **every account balance**: S1 snapshots, S2 grades and RQ, S3 reports, S4 quoted literals.
Several writers still commit balances today, so a rewrite done now would need a second one. Order:

1. **Writers first (Tier 1/2, normal PRs, no freeze).** PR **#25305** (EQUITY-LEAK-STOP, open; **merge is the precondition for the
   purge**) already covers, per its diff:
   - `scripts/research/cf_core.py` and `counterfactual_grader.py`: `equity_pre_usd` and `per_account.*.pct_of_account` are no longer
     written; the 17 tip grade files are nulled; the equity is kept in memory only.
   - `scripts/research/alpaca_baseline_affordability.py` (RQ-20261106-d5a1-01): no `equity_usd`, no `budget_usd`, no balance in `note` /
     population strings; the 9 tip run files are scrubbed; its docstring and self-test constants are synthetic.
   - `scripts/ops/redact_diag_output.py` + `.github/workflows/system-actions.yml`: an `account_balance` redaction on the text the relay
     posts into public issues (the leak channel in §0.3).
   - `tests/test_no_balance_in_committed_research.py`: positive/negative controls and a scan of the committed grade and RQ files.
   **#25305 does NOT cover** (found in rev 2, each needs its own writer or scrub): `comms/reports/**/report.json` balances (the report
   generator), the report `.md`/`.html`, `comms/claude_strategy_scores.jsonl`, `config/accounts.yaml` (a comment), and every S4 text
   site. **Filed as the pre-scrub work below.**
2. **Tip pre-scrub PRs (Tier 1/2; list in `scripts/ops/history_purge/tip-prescrub-paths.txt`, 99 paths).** Remove the balance from each
   tip file by a normal commit, with semantics decided by the file's owner: a code or test file needs a synthetic fixture, **not** the
   purge token (the dry run replaced a literal inside `round(0.015 * <literal>, 2)` with text, which is a syntax error at the tip).
   Add the report generator's no-balance test and extend the `test_no_balance_in_committed_research.py` scan to `comms/reports/`.
   **Goal: the tip tree of `main` is unchanged by the rewrite** (§7 check 4); until it is, the purge is not ready.
3. **S3 paper/prop scope is decided: all balances** (decision line above). The keys are nulled and the literals scrubbed, for real, paper
   and prop alike. `PURGE_INCLUDE_S3=0` and `build_purge_values.py --no-s3` still exist to narrow it.
4. **One rewrite** in the single freeze window below.

---

## 2. The tool: `git filter-repo` (v2.47.0, `a40bce548d2c`)

### 2.1 Callbacks (`scripts/ops/history_purge/`; they hold no values)

- **`build_purge_values.py`** reads the blobs of every committed version of the balance files and writes the exact numeric values, one per
  line, to a local file **outside the repo** (`PURGE_STRONG_FILE`). Specificity filter, from the dry run: drop zero and any figure with
  fewer than 4 significant digits. Without it, one round figure matched 4,079 tip files. OPS adds the two prose-only figures (§0.2b) by hand.
- **File-info callback** (`file_info_callback.filter-repo.txt`), two path-scoped passes; everything else passes byte-identical:
  1. **Key nulling** (JSON): `account_snapshot/*.json` → `equity_usd`, `buying_power_usd`, `cash_usd`; `counterfactual_grades/*.json` →
     `equity_pre_usd`, `pct_of_account`; `RQ-20261106-d5a1-01/**.json` → `equity_usd`, `budget_usd`; `comms/reports/**/report.json` →
     `equity`, `balance`, `account_equity` **only under `pnl_by_class`**. Set to `null` (not deleted) so readers' schemas stay valid.
  2. **Literal scrub**: each exact literal in `PURGE_STRONG_FILE`, in the **allow-listed paths** (`docs/ research/ scripts/ tests/ config/
     .github/ src/`, plus named `comms/` files), skipping `*.csv`, `*trades.jsonl`, `*paths.jsonl` and `data|cells|sims|arms|candles|corpus|runs`
     directories. A bare JSON number becomes `null`; a literal inside a string, Markdown, YAML or code becomes `[balance removed]`.
- **Message callback:** the same literals in commit messages become `[balance removed]` (whole-number match; rounded forms are not touched,
  they collide). The dry run found 18 commit messages with a literal, and 0 afterwards.
- **Removed:** `strip_balance_blobs.filter-repo.txt` (the S1-only blob variant). It cannot reach S2 to S4. For an S1-only purge, use the
  callbacks with a values file built from S1 only.

⚠️ **Code at the tip.** The literal scrub is for **history**. A code or test file at the tip that still holds a literal comes out with
`[balance removed]` in the middle of an expression and no longer parses. That is why §1 step 2 pre-scrubs the tip first.

### 2.2 Exact commands (run by OPS with the manager, inside the freeze, on a fresh mirror)

```bash
# 0. fresh mirror AFTER the freeze starts (so nothing lands mid-rewrite)
git clone --mirror https://github.com/benbaichmankass/JTA-Trader jta.git
git -C jta.git show-ref > pre-refs.txt                    # rollback position (section 7)
git -C jta.git bundle create pre-rewrite.bundle --all     # full offline backup, kept off-repo
# 1. build the literal file (never committed, never printed); add the two prose-only figures by hand (section 0.2b)
python3 -I scripts/ops/history_purge/build_purge_values.py jta.git .purge-strong
# 2. rewrite (callback paths relative to a JTA-Trader checkout)
cd jta.git && PURGE_STRONG_FILE=../.purge-strong git filter-repo --sensitive-data-removal --no-fetch \
  --file-info-callback "$(cat ../scripts/ops/history_purge/file_info_callback.filter-repo.txt)" \
  --message-callback  "$(cat ../scripts/ops/history_purge/message_callback.filter-repo.txt)"
# 3. verify (section 7) BEFORE any push
# 4. push only branch heads (GitHub refuses writes to refs/pull/*; no tags exist). The OPERATOR runs this (OPERATOR section A)
git push --force origin 'refs/heads/*:refs/heads/*'
```

`--sensitive-data-removal` records the **first changed commits** and the orphaned refs, which the Support request needs
(`filter-repo/first-changed-commits`; attach it). filter-repo also writes `filter-repo/commit-map` (old to new SHA). **Commit that map**
under `docs/archive/2026-11-history-purge/commit-map.txt` after the push: evidence records, PR bodies, checklist notes and pipeline rows
cite SHAs, and once GitHub garbage-collects the old commits those citations stop resolving. The map holds SHAs only, no values.

### 2.3 Dry-run results (full scope, sandbox mirror, 2026-11-12; 4 vCPU)

Run on a copy of the 12:38Z mirror (2,058 heads, 15,892 PR refs, 52,848 commits), with the callbacks as committed here, S3 on.

| measure | result |
|---|---|
| **time** | **21 min 14 s** end to end on a warm disk cache (1,180 s writing, then repack). The first run, cold cache and an unfiltered literal list, took **40 min 39 s** (2,328 s writing). **Plan for 40 minutes** |
| commits rewritten | **52,824 of 52,848** (all refs); all of `main` gets new SHAs |
| "first changed commit" entries | 49 |
| refs changed | 2,056 of 2,058 `refs/heads/*`; 15,892 of 15,892 `refs/pull/*` (cannot be pushed; Support handles them, §6) |
| old S1 blobs, old `43e844e3cd` | **gone** (not a valid object in the rewritten repo) |
| commit messages with a literal | **18 before, 0 after** (of 52,848) |
| text blobs in the allow-list still holding a literal | **0** (of 156,469 reachable blobs scanned) |
| JSON blobs in the key-nulled families with a non-null balance key | **0** (319 blob versions parsed, 0 unparseable) |
| out-of-scope blobs with a numeric collision, left unchanged | 277 (market data and backtest files, §0.2b) |
| **tip tree of `main`, old vs new** | **NOT identical: 99 files differ** (S2 26, S3 25, S4 and prose 48; `tip-prescrub-paths.txt`). The tip pre-scrub (§1 step 2) must bring this to 0 |
| `filter-repo/suboptimal-issues` | 3,369 lines, not examined (references to commits that no longer exist; rev 1 saw 17) |

**Not tested:** that the rewritten tip builds and its tests pass. It cannot, until the pre-scrub is done (a code literal becomes a
syntax error at the tip). Run `pytest` on the rewritten mirror's `main` as §7 check 5 once the pre-scrub has landed.


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

**Window:** about 2 hours: a fresh mirror (~4 min measured), the rewrite (21 to 41 min measured, §2.3; plan 40), verification (~20 min,
because scans over all refs are slow), the push of ~2,040 heads, VM convergence and the post-push checks. Pick a slot that avoids **05:17Z Monday** (`gitleaks-history-weekly`) and **05:23Z daily**
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

**Yes, the repo owner must file it.** GitHub keeps the old commits reachable through `refs/pull/*` (15,892 PR refs on 2026-11-12, read-only
to us), cached PR diff views and commit URLs, until Support dereferences them and runs gc. Only the owner can request that, at
<https://support.github.com/contact> → "Remove sensitive data". `filter-repo --sensitive-data-removal` writes the first changed commits
(`filter-repo/first-changed-commits`) to attach. **The ready-to-paste request text is in the OPERATOR section, part B** (kept in one place).
Order: edit the PR and issue bodies (§0.3) first, delete their older revisions, then file.

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
3. Every literal in `PURGE_STRONG_FILE`: a scan of all reachable text blobs in the allow-listed paths (§2.1) finds **0**, and
   `git log --all --format=%B` finds **0** whole-number matches. (`git log --all -S` per literal is too slow on this repo; the scan used
   `git cat-file --batch` over the reachable blobs, ~10 min.) Print counts only, never the literal. Also confirm every rewritten JSON
   blob in the key-nulled families parses and carries no non-null balance key (dry run: 319 parsed, 0 bad, 0 non-null).
4. `git rev-parse <old main tip>^{tree}` equals `git rev-parse refs/heads/main^{tree}` (same tip tree, once the §1 writer fixes **and the
   tip pre-scrub** landed). **Dry run: 99 files differ today**; the purge is not ready until this is 0.
5. `pytest tests/test_mandate_resolver.py -k no_balance`, `tests/test_no_balance_in_committed_research.py` (from #25305) and the full `pytest-run`
   suite pass on the rewritten tip, and `python3 -m compileall -q src scripts tests` is clean (a stray purge token in code fails here).
6. After the push: §4 HEAD checks on all three VMs, and §5's `[bp-report]` shows protection restored.
7. After Support confirms: `curl -s -o /dev/null -w '%{http_code}' https://github.com/benbaichmankass/JTA-Trader/commit/43e844e3cd`
   → **404**.

---

## 8. Findings filed separately (outside the rewrite)

- **The counterfactual grader and the RQ-20261106-d5a1-01 runner committed real-money equity.** Fixed going forward by PR #25305
  (row `CF-GRADES-EQUITY-COMMITTED`); merge it before the purge.
- **The report generator commits real, paper and prop balances** into `comms/reports/**/report.json` (and `.md`/`.html`), and ~48 other
  tip files quote a balance in prose or code (§0.2b). #25305 does not cover them. Filed as row `BALANCE-TIP-PRESCRUB`, which
  gates the purge.
- **Diag and system-action issues publish alpaca_live equity** in journal and config output (13 issues found for one
  value). Filed as row `DIAG-RELAY-EQUITY-LEAK`.
- **Optional detector, not a gate:** add the four old blob ids to the weekly `gitleaks-history-weekly` run as a
  "reintroduced old history" check. It reports and blocks nothing. The operator decides.
