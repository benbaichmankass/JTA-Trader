# 2026-11-19 co-direction vs next-24h realised R — authoring dry run (NOT a pre-registered test)

Produced while authoring PI-20261118-PREP1118-0002's answer (lane PERF-FOLLOWUP-2026W47). Population: the 8 legs with a
committed full-history corpus (`comms/strategy_evidence/ltr_corpus`), BACKTEST rows net of the full cost stack, never the
live journal. Command: `python3 scripts/research/codirection_drawdown.py [--by-family]` (seed 20261119, 2000 draws).
The pooled run and the by-family run were both read before any rule was written for them, so they carry no
pre-registration; they are MEASURED descriptive reads. The live-journal population has not been read: it is the
pre-registered test (pipeline item, rule = the script's `grade()` as committed here).
