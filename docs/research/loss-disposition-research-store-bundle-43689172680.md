# Loss disposition: `research-store-bundle` of run 43689172680 (expires 2026-11-18T07:34:51Z)

> **Doc status:** `unknown` · category `evidence` · last verified `2026-11-15` · registered in [`../DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md) · lane `RESEARCH-OPS-20261115-2247`

Raised by the research loss detector (run 43749722621, question `C_expiring_unlanded_artifacts`). Dispositioned by
RESEARCH-OPS-20261115-2247. Verdict: **safe to lose; not landed into the repo, and the reasons are checkable.**

- **What it is:** the grade job's hand-off bundle for `research-queue-grade.yml` (workflow header: *"the only artifact is the
  research-store bundle, a minutes-long hand-off between two jobs of one run"*). It holds grading events, not a result.
- **Its durable landing already happened, in the trainer store:** job `research-store` of run 43689172680 finished `success`
  (steps "download-artifact" and `research-store-ship` both `success`, 07:35:21Z-07:35:23Z).
- **Its repo landing failed but the content is re-derived:** the same run's `grade` job step "Land the dispositions on main"
  ended `failure` after 82 min (07:34:52Z-08:56:16Z). The grades are a pure function of committed `research/results`; later grade
  runs recompute them (`105c25525`, run 43750762663, landed 19:20Z). A dry `queue_grade.py` on main at 22:50Z shows only
  fresh bf1b results pending, none from that run's window.
- **Open follow-up, not a loss:** why one commit-to-main step hung 82 min is a mechanism question for the manager (flagged on the
  RESEARCH-OPS-20261115-2247 row); the detector cannot see a trainer-store landing, so this class will re-flag every grade run
  until its question learns the `research-store` job outcome.
