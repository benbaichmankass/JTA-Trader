# Reveal grade brief (CJ-3, pass 2 of 2)

> **Doc status:** `live` · category `instruction` · last verified `2026-10-26` · registered in [`docs/DOCUMENT-INDEX.md`](../../../docs/DOCUMENT-INDEX.md) · companion to [`SKILL.md`](SKILL.md) § "Blind-then-reveal grade"

You are the second pass of a blind-then-reveal grade of trading DECISIONS for the Metis-Insights
trading system. The first pass graded each decision from a masked packet without its outcome.
Now you see the outcome. Your job is to say, with hindsight, how the trade was managed and
whether the blind grade still stands. The difference between the two grades is itself measured
(hindsight bias), so do not move a grade only because the trade won or lost: a good decision can
lose, and a bad one can win.

## Inputs (on this branch)

- `blind_packets.jsonl`: the masked decision packets (see `BLIND-GRADE-BRIEF.md` for the fields).
- `reveal_packets.jsonl`: one line per packet: `packet_id`, the `blind` grade written in pass 1, and
  the `outcome`:
  - `net_r`: realised R net of fees and costs (R = the entry-to-stop distance)
  - `exit_kind`: `tp` | `sl` | `trail` | `time` | `strategy_close` (the strategy or its intent layer
    closed it) | `reconciled_or_other` (closed by reconciliation or netting, not by the bracket)
  - `mfe_r` / `mae_r`: the best and worst price excursion while the trade was open, in gross R
  - `bars_held`

## What you write

One JSON object per packet, one per line, in the same order, to `revealed_grades.jsonl`:

```json
{"packet_id": "BP-...", "revised_decision_grade": "C", "revised_grade_score": 2,
 "exit_quality": "sl_appropriate", "alternative_action": "none",
 "hindsight_note": "one line, at most 240 characters"}
```

- `revised_decision_grade` / `revised_grade_score`: A=4 B=3 C=2 D=1 F=0, as in pass 1. Keep the blind
  grade unless the outcome reveals something the decision-time evidence should have shown.
- `exit_quality`: `optimal` | `tp_appropriate` | `sl_appropriate` | `premature_exit` | `held_too_long` | `unknown`
- `alternative_action`: the single change that would have helped most, judged against the path:
  `none` | `skip` | `tighter_sl` | `wider_sl` | `closer_tp` | `further_tp` | `earlier_exit` | `later_exit` | `unknown`
- `hindsight_note`: plain text, no market names, no dates.

## Then

Validate one row per packet, legal enums, matching scores. Then
`git add revealed_grades.jsonl && git commit -m "cj3 reveal grades" && git push` to the branch you are on.
Do nothing else.
