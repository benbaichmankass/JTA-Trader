# JTA Trader rename — operator steps and follow-ups

> **Doc status:** `live` · category `instruction` · last verified `2026-11-11` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Operator decision 2026-10-28: the project is **JTA Trader** (scope: docs + UI + GitHub repo). Runtime identifiers do **not** change.

## A rename breaks STRING matches first (RENAME-SLUG-FUNCTIONAL-AUDIT, 2026-11-11)

GitHub's redirects cover URLs and API calls, so prose, labels and links need no sweep. They do **not** cover anything that
compares the name as a STRING. After the 2026-10-28 rename these silently stopped matching:

- the manager's merge permission rules in `.claude/settings.json` (pinned `repos/benbaichmankass/Metis-Insights`): every held
  PR needed an operator window for about 11 days (fixed by #24221);
- `scripts/ops/manager_view.py` `DEFAULT_REPO` (PR refs `JTA-Trader#n` read as another repo's);
- `scripts/ops/session_reaper.py` `REPO_PREFIX` (branch refs `JTA-Trader:…` were dropped);
- `scripts/ops/lane_reconcile.py` `PROJECT_REPOS` (no `jta-trader`, so sessions on the renamed repo read as foreign).

All four now read the name through `scripts/ops/repo_slug.py` (`GITHUB_REPOSITORY`, else the git remote) or list the new
name. **On the next rename, do this first:**
1. `git grep -n -i "<old-name>" -- '*.py' '*.yml' '*.yaml' '*.json' '*.sh'`, and classify each hit as a string match (a
   permission pattern, an `==` / `startswith` / set membership) or a label (prose, a User-Agent, a fixture).
2. Fix every string match to read the slug (`repo_slug.current_name()` / `is_this_repo()`), and add the OLD name to
   `repo_slug.HISTORICAL_NAMES` so register rows written before the rename still match.
3. Add the new name next to the old one in `.claude/settings.json` permission patterns.

## Do NOT rename (identifiers)

- VM paths `/home/ubuntu/ict-trading-bot`, `/opt/ict-trading-bot`; systemd unit names (`ict-*.service`); Python package/module names (`src/`, `ml/`).
- Domain `ict-bot.duckdns.org`; bot names (Telegram `@claude_ict_comms_bot`); the `Manager Session` title convention.
- Kaggle slugs (`metis-market-data`, `metis-research-*`, `metis-gpu-pilot`), `~/.cache/metis-*` dirs, `data-metis-*` DOM selectors, `metis-exec-js`
  signing message, User-Agent strings. Changing the signing message or Kaggle slugs breaks live verification/datasets.
- Repo slugs in historical records (`comms/`, `research/results/`, `automation/`, `.github/pr-landing/`, `docs/archive/`).
- `.claude/settings.json` `gh api` allow-rules and the trading-desk `source_url`: keep the current slug until the rename lands, then add the new one.

## Operator steps (one GitHub Settings action)

**Status 2026-10-28:** step 1 DONE — repo is now `benbaichmankass/JTA-Trader`; the old URL still fetches via the redirect. In-repo slug defaults were updated (Tier 1). Step 5 (VM remotes) is deferred; the VMs stay on the redirect.

1. GitHub → `benbaichmankass/Metis-Insights` → Settings → General → Repository name → `JTA-Trader` (or the chosen slug) → Rename.
2. GitHub redirects the old web, git and API URLs. Verify: Actions secrets (`VM_SSH_KEY`, `DIAG_READ_TOKEN`) are carried over (Settings → Secrets);
   webhooks still deliver (Settings → Webhooks → Recent Deliveries); Pages/branch protection intact; GitHub App installation (Claude) still covers the repo.
3. Tell the manager the new slug. Sessions are scoped by repo name in the Claude app: re-attach the repo if a session reports a scope denial.
4. Rename the Google Doc "Metis — Ideas inbox" to "JTA Trader — Ideas inbox" (the manager matches either title).
5. **Tier-2 follow-up (after an operator OK):** on both VMs run `git remote set-url origin https://github.com/benbaichmankass/<new-slug>` in the clone dir
   (works through the redirect until then). Check `ict-git-sync` pulls `main` on its next ~5 min run.

## Dashboard repo (`benbaichmankass/ict-trader-dashboard`, out of this lane's scope)

Follow-up PR there: the `<title>` and app header strings ("ICT Trader"/"Metis"), PWA manifest `name`/`short_name`, the login/passkey screen copy,
and README. Do not change the API base URL or CORS origin.
