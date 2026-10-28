# JTA Trader rename — operator steps and follow-ups

> **Doc status:** `live` · category `instruction` · last verified `2026-10-28` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)

Operator decision 2026-10-28: the project is **JTA Trader** (scope: docs + UI + GitHub repo). Runtime identifiers do **not** change.

## Do NOT rename (identifiers)

- VM paths `/home/ubuntu/ict-trading-bot`, `/opt/ict-trading-bot`; systemd unit names (`ict-*.service`); Python package/module names (`src/`, `ml/`).
- Domain `ict-bot.duckdns.org`; bot names (Telegram `@claude_ict_comms_bot`); the `Manager Session` title convention.
- Kaggle slugs (`metis-market-data`, `metis-research-*`, `metis-gpu-pilot`), `~/.cache/metis-*` dirs, `data-metis-*` DOM selectors, `metis-exec-js`
  signing message, User-Agent strings. Changing the signing message or Kaggle slugs breaks live verification/datasets.
- Repo slugs in historical records (`comms/`, `research/results/`, `automation/`, `.github/pr-landing/`, `docs/archive/`).
- `.claude/settings.json` `gh api` allow-rules and the trading-desk `source_url`: keep the current slug until the rename lands, then add the new one.

## Operator steps (one GitHub Settings action)

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
