"""RQ-20261101-78fc-11 lever: --oi-z on the frozen E4 arm (desk_event_entry_replay.detect / e4_prop_ledger) + the arms grader."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "research"))

import desk_event_entry_replay as m  # noqa: E402
import e4_oi_z_arms as arms  # noqa: E402


class _Ser:
    """Minimal stand-in for gr.Series: rising closes, so every shock gets side +1."""
    def __init__(self, t0: int, n: int):
        self.t = np.arange(n) * 3600 + t0
        self.c = np.linspace(100, 200, n)

    def last_closed(self, cutoff: int) -> int:
        k = int((cutoff - self.t[0]) // 3600) - 1
        return k if 0 <= k < len(self.t) else -1


def _fixture(tmp_path: Path) -> tuple:
    """5-minute OI for one symbol: small noise plus three shocks of increasing size (detected: 3 at oi_z 3, 2 at 4, 0 at 5)."""
    rng = np.random.default_rng(1)
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    n = m.OI_W + m.OI_LAG_BARS + 900
    oi = 1e6 * np.cumprod(1 + rng.normal(0, 0.0005, n))
    sd_ch = 0.0005 * np.sqrt(m.OI_LAG_BARS) * 0.5   # empirical scale: the rolling z of a step reads ~2x its nominal size here
    for k, z in ((m.OI_W + 200, 3.5), (m.OI_W + 500, 4.5), (m.OI_W + 800, 8.0)):
        oi[k:] *= 1 + z * sd_ch
    sym = m.SYMS[0]
    d = tmp_path / "oi" / sym
    d.mkdir(parents=True)
    lines = [f"{(t0 + timedelta(minutes=5 * i)).strftime('%Y-%m-%d %H:%M:%S')},{sym},{oi[i]:.4f}" for i in range(n)]
    (d / "2025-01-01.csv").write_text("create_time,symbol,sum_open_interest\n" + "\n".join(lines) + "\n")
    mkt = {s: _Ser(int(t0.timestamp()), n // 12 + 50) for s in m.SYMS}
    return tmp_path, mkt


def test_default_threshold_unchanged_and_higher_threshold_is_a_subset(tmp_path):
    root, mkt = _fixture(tmp_path)
    base = m.detect(root, mkt)["E4"]
    same = m.detect(root, mkt, oi_z=3.0)["E4"]
    hi4 = m.detect(root, mkt, oi_z=4.0)["E4"]
    hi5 = m.detect(root, mkt, oi_z=5.0)["E4"]
    assert base == same                                   # the default IS the frozen arm
    assert len(base) == 3 and 0 < len(hi4) < len(base) and len(hi5) < len(hi4)   # 3 -> 2 -> 0 on this fixture
    # a stricter threshold crosses LATER inside the same 12-bar step, so the same shock fires at most one lag window
    # (OI_LAG_BARS x 5 min = 1 h) after the base arm's event -- never a shock the base arm did not see
    for e in hi4 + hi5:
        assert any(b["sym"] == e["sym"] and 0 <= e["known"] - b["known"] <= 3600 for b in base), e


def test_ledger_cli_accepts_oi_z():
    import e4_prop_ledger as led
    import inspect
    assert inspect.signature(led.rows_for).parameters["oi_z"].default == m.OI_Z == 3.0
    src = inspect.getsource(led.main)
    assert "--oi-z" in src


def test_arms_self_test_passes():
    assert arms.self_test() == 0


def test_committed_ledger_holdout_is_the_registered_population():
    import json
    rows = [json.loads(ln) for ln in arms.LEDGER.read_text().splitlines() if ln.strip()]
    ho = [r for r in rows if r["window"] == "holdout"]
    ev = json.loads((REPO / "comms" / "strategy_evidence" / "e4_oi_shock.json").read_text())
    assert len(ho) == 856 and ev.get("n_trades_oos", ev.get("n")) in (856, None)
