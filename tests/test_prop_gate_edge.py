"""Self-test for the V3 prop gate edge clause (lane PROP-GATE-EDGE-SENSITIVE).

A zero-edge ledger must FAIL on all three prop accounts even when the v2 breach/EV statistics PASS (which is exactly
what v2 did for a random walk); a clearly positive-edge ledger can still PASS. Pure functions: no simulator run.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/research"))
import prop_gate as pg

ACCOUNTS = ("breakout_2", "tradeify_1", "velotrade_1")


def _ledger(mean_gross_r, n=600, seed=7):
    """Synthetic ledger: 1.5% stop, ~1/3 winners at +gross, 2/3 stops at -1, shifted so E[gross_r] == mean_gross_r."""
    rng = random.Random(seed)
    base = [(-1.0 if rng.random() < 0.6667 else 2.0) + rng.gauss(0, 0.05) for _ in range(n)]
    shift = mean_gross_r - sum(base) / n
    rows = []
    for i, g in enumerate(base):
        t0 = 1_700_000_000 + i * 86400
        from datetime import datetime, timezone
        a = datetime.fromtimestamp(t0, timezone.utc)
        b = datetime.fromtimestamp(t0 + 6 * 3600, timezone.utc)
        rows.append({"entry_time": a.isoformat(), "exit_time": b.isoformat(), "entry": 100.0, "sl": 98.5,
                     "gross_r": g + shift, "mfe_r": max(0.0, g + shift)})
    return rows


def test_zero_edge_ledger_fails_on_all_accounts_even_when_v2_passes():
    rows = _ledger(0.0)
    for acct in ACCOUNTS:
        for arm in ("cur", "ven"):
            edge = pg.edge_ci(pg.ledger_net_r(rows, acct, arm))
            assert edge["ci_lo"] < 0, (acct, arm, edge)
            assert pg.grade_v3("PASS", edge) == "FAIL_EDGE", (acct, arm, edge)


def test_clearly_positive_edge_can_still_pass():
    rows = _ledger(0.6)
    for acct in ACCOUNTS:
        edge = pg.edge_ci(pg.ledger_net_r(rows, acct, "cur"))
        assert edge["ci_lo"] > 0, (acct, edge)
        assert pg.grade_v3("PASS", edge) == "PASS"


def test_edge_clause_only_downgrades_and_missing_edge_never_passes():
    pos = {"ci_lo": 0.1}
    assert pg.grade_v3("FAIL", pos) == "FAIL"
    assert pg.grade_v3("INDETERMINATE", pos) == "INDETERMINATE"
    assert pg.grade_v3("PASS", {"ci_lo": None}) == "INDETERMINATE"
    assert pg.grade_v3("PASS", {"ci_lo": 0.0}) == "FAIL_EDGE"


def test_demeaned_ledger_has_zero_net_edge():
    rows = _ledger(0.6)
    for acct in ACCOUNTS:
        z = pg.demean_rows(rows, acct, "cur")
        assert abs(sum(pg.ledger_net_r(z, acct, "cur")) / len(z)) < 1e-9
