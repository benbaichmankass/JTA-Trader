# Operator grant: "Merge + deploy on green" (2026-11-12)

> **Doc status:** `unknown` · category `plan` · last verified `never` · registered in [`docs/DOCUMENT-INDEX.md`](../../docs/DOCUMENT-INDEX.md) · a record of an operator popup answer, written 2026-11-12 by AM-OPS on the manager's instruction.

This file records an answer the operator gave, in the operator's own words. It is not a new mandate. `config/mandates.yaml` is unchanged.

**Gates this adds or changes:** none. The JC-CA-04 hold-merge alarm (`scripts/ops/pr_landing_hold_alarm.py`) is unchanged. This file is a record that a held PR's `decision:` line or `recorded_decision.ref` can cite.

## What was granted

- **When and where:** about 20:40Z on 2026-11-12, in a popup question from Manager Session 2026-11-11a (session_01AFoLuLyarNRcy3nziCep2U).
- **The question and answer:** the question offered four grants and the operator selected all four. One of them is labelled, verbatim, **"Merge + deploy on green"**.
- **The other three labels:** the manager has not passed them on to the session writing this record, so they are not quoted here. The manager may add them verbatim.
- **Provenance:** relayed by the manager to AM-OPS (session_01AFoLuJUGfpon2bNgwFbFmx) at 22:45Z on 2026-11-12, and committed here on the manager's instruction.

## Scope, as the manager stated it

- **Covered:** merging and deploying Tier-1 and Tier-2 PRs once the required `guards` check is green. That includes PRs declared `landing: "hold"` in `.github/pr-landing/<slug>.json`.
- **Not covered:** Tier-3 changes (strategy logic or params, risk caps or sizing, account-mode flips, live promotion). These still need an explicit operator decision, or a committed evidence record under canonical § "Data-backed Tier-2/3 decisions".
- **Unchanged:** deploying through the normal path (`ict-git-sync`) and checking the post-state afterwards. Merged ≠ deployed ≠ observed still applies.

## How a held PR cites it

Put this exact line in the PR body. The alarm's `decision:` matcher already accepts it:

```
decision: 2026-11-12 operator-popup "Merge + deploy on green"
```

Or, in `.github/pr-landing/<slug>.json`:

```json
"recorded_decision": {"kind": "operator_decision", "ref": "docs/plans/operator-grant-merge-deploy-on-green-2026-11-12.md"}
```

**Why this file exists:** before it, Tier-2 held PRs merged under this grant carried no marker the alarm accepts. Each one filed a `send-ping ... hold-merge alarm (JC-CA-04)` system-actions issue: 10 of the 11 system-actions runs between 21:00Z and 22:36Z on 2026-11-12.
