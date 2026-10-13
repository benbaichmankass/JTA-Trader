# PR event wake policy — which PR events deserve a Claude wake

> **Doc status:** `unknown` · category `lookup` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · **nobody has verified this document's status — do not act on it as current**
>
> Row `AUTO-NOTIF-POLICY` (plan `docs/plans/OPS-AUTOMATION-INVENTORY-2026-10-13.md`, act M-d). Written 2026-10-13 by lane
> AUTO-WAVE1. **This file is the policy; `.claude/skills/manager/SKILL.md` is edited separately** (lane
> MANAGER-HANDOVER-SKILL) and should carry ONE pointer line to this file. Until it does, the manager reads this file directly.

## The problem

`subscribe_pr_activity` delivers every review, CI result, merge and push on the PR as a wake. A session that subscribes to every
PR it opens or watches spends a model turn on events that need no decision. The plan estimated ~8% of the manager's mechanical <!-- population-ok: quoted estimate from the inventory plan act M-d, not a measurement -->
effort and rated it low confidence (an ESTIMATE, not a measurement).

## What a wake costs and what it buys

A wake is worth paying for only when **a session can change the outcome**. A workflow cannot wake or read a session, so anything
a script can decide is decided by the script and the session hears only about what is left.

## The rule

| PR state | Subscribe? | Why |
|---|---|---|
| `landing: self`, Tier 1, auto-merge armed (`.github/pr-automerge-requests/<slug>.txt`), CI not red | **No** | GitHub merges it on green. A wake would only acknowledge that. |
| Same, and `pytest-run` died at its timeout or before tests | **No** | `pytest-rerun` (AUTO-PYTEST-RERUN) reruns it once. |
| Same, and only *behind* `main` | **No** | `branch-sync` (AUTO-BRANCH-SYNC) merges `main` in. |
| Any PR with a **real red** check (a failed test step, a failed guard, a failed rerun) | **Yes, from the red onward** | Only a session can fix the cause. |
| A conflict `branch-sync` could not resolve (it leaves one comment) | **Yes** | Needs a human-grade merge. |
| `landing: hold`, Tier 2 or Tier 3, or any PR waiting on the operator | **Yes** | The point of a hold is a decision; the wake carries the operator's answer. |
| A review requesting changes from a human | **Yes** | Needs a reply or a push. |

**Unsubscribe when the PR is merged, closed, or green again with nothing waiting** (`unsubscribe_pr_activity`).

## Events that never justify acting on their own

- An event echoing a comment or review this session posted.
- A duplicate of an event already handled.
- `check_suite` success: each required check is its own suite, so one success never means the PR is green. Read the whole head
  (`ci-settled`) before acting.

## What this does NOT establish

- It does not make the manager notice a red PR it is not subscribed to. The pull side is the manager's open-PR sweep at the start
  of a session, and `AUTO-CI-TRIAGE` (queued) is the row that would post a red diagnosis for it. Until that exists, **an armed PR
  that goes red unseen is the risk this policy accepts**; the sweep must list armed PRs whose latest `pytest-run` is red.
- The wake-count saving is unmeasured. Observation that closes the row: PR-event wakes per day in the manager session fall against
  the pre-change count (due 2026-10-27).
- Lanes already must not subscribe to their own PR (manager skill, ownership rule 1). This policy governs the manager and any
  assistant session, and does not change that rule.
