#!/usr/bin/env python3
"""Aggregate cells for RULE-P5-GATE-BRK-PER-LEG-V2 (unit RQ-20261029-9a2c-01), lane PROP-REPLACEMENT."""
# The rule now lives in ONE place (scripts/research/prop_gate.py, 2026-10-31, lane PROP-GATE-EDGE-SENSITIVE); this
# file only points it at this directory. Output (summary.json, v2 columns) is unchanged -- the v3 edge clause is
# applied by docs/research/prop-gate-edge-regrade-2026-10-31/regrade.py.
import sys

sys.path.insert(0, "scripts/research")
import prop_gate

prop_gate.run_aggregate("docs/research/prop-replacement-2026-10-30/")
