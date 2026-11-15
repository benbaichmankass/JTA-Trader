# Weekly planning triage brief (Manager Session 2026-11-11a, 2026-11-12)

> **Doc status:** `unknown` · category `unknown` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../../../DOCUMENT-INDEX.md)


The operator ordered a FULL weekly planning: every queued work item gets understood and queued correctly (lane, slot, time). The failure being fixed: queued rows sat without lanes, so lanes redid work and re-specced things the operator had already specced (e.g. UI-REDESIGN-2026-11, 11-09).

You are READ-ONLY. Do NOT change the work store, git or GitHub. Read rows from the partition JSON file given to you (they come from `python3 scripts/ops/work.py --via direct list`). For more detail on a row use `python3 scripts/ops/work.py --via direct get <ID>` and `history <ID>`. Check main with `git -C /home/user/JTA-Trader grep` / `git log origin/main --oneline -S<term>` / reading code. Check live state with `curl -sS https://ict-bot.duckdns.org/api/bot/...` or `bash scripts/ops/diag_fetch.sh '<route>'` when cheap.

Context for this week (operator answers, 2026-11-12):
- p1: no capacity limit this week, surge until the reset (~Sat/Sun), then reset and keep surging until the throttle ahead of Wednesday's reset.
- p3: real money is promoted on backtest evidence. Shadow/paper is ONLY for demoted legs in iteration, not a step toward real money.
- Surge = real money (incl. prop + prop MLs), anything moving a strategy or ML toward live, the week's big ML/strategic milestones (incl. the UI redesign UI-REDESIGN-2026-11). Throttle = important but not top-line (infra that can't go live this week, less urgent UI, cleanups, guard pruning). Standing = recurring checkups (daily review, weekly reviews, research-ops, live review, health checks).
- Every kill needs a reason AND supporting data (operator p7).
- Lanes are created with the repo they work in as source_url: JTA-Trader, ict-trader-dashboard (SPA) or ict-trader-android.

For EVERY row in your partition, output ONE JSON object (a JSON array, written to the output path given) with:
  id, title_short (<=90 chars, plain words),
  status_check: "still_needed" | "already_done" (cite the PR/commit/file evidence) | "superseded_by:<ID>" | "duplicate_of:<ID>" | "unclear",
  evidence (one or two sentences: what you checked, with the population or file),
  disposition: "surge" | "throttle" | "standing" | "later:<ISO week, e.g. 2026-W48>" | "kill_candidate" | "close_done",
  reason (one sentence; for kill_candidate state the supporting data),
  cluster: a short lane-cluster name grouping rows one lane should do together (e.g. "ui-spa", "prop-phone", "ml-entry-heads", "ltr-desk", "security", "data-feeds", "research-harness", "ops-observability"),
  repo: "JTA-Trader" | "ict-trader-dashboard" | "ict-trader-android",
  tier: 1 | 2 | 3,
  size: "S" (<1h lane) | "M" (half day) | "L" (multi-day),
  depends_on: [ids] (only real blockers),
  operator_question: null or a one-line question if the row needs an operator preference no data settles.
Work through rows in batches; do not skip any (your array length MUST equal the partition length; say so at the end). Prefer cheap checks; a status_check of "unclear" is fine when checking would take more than a couple of minutes, but say what you would check.
Final message to the manager: counts by disposition and by cluster, the list of already_done/superseded/duplicate ids, the operator_questions, and the top 10 surge rows in the order you would run them. Keep it under 400 words. The JSON file is the full record.
