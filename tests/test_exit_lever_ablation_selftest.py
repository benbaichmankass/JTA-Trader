"""The exit-lever ablation instrument's self-test must not depend on live config drift.

PI-20261013-407C-0001: --self-test failed on main because EXIT-LEVER-STRIP (#17002) removed
stale_exit_bars from trend_donchian_eth_prop, while the self-test used that leg's live config as
its fixture. The arm builder was never wrong.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
sys.path.insert(0, str(REPO / "scripts" / "ops"))
sys.path.insert(0, str(REPO))


def test_self_test_passes():
    r = subprocess.run([sys.executable, str(REPO / "scripts/research/exit_lever_ablation.py"), "--self-test"],
                       capture_output=True, text=True, cwd=REPO, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ablated_arm_drops_lever_and_keeps_window_independent_of_live_config():
    import exit_lever_ablation as e
    import yaml
    legs = yaml.safe_load((REPO / "config/strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    cfg = {**legs["trend_donchian_eth_prop"], "stale_exit_bars": 12, "stale_exit_below_r": 0.0}
    base, _ = e.build_arm_argv("trend_donchian_eth_prop", cfg, "<d>", "1h", "<e>", "<j>", [], None, None)
    abl, _ = e.build_arm_argv("trend_donchian_eth_prop", e.arm_cfg(cfg, {}, ["stale_exit_bars", "stale_exit_below_r"]),
                              "<d>", "1h", "<e>", "<j>", [], "2024-10-05", "2026-10-03 23:59")
    assert "--stale-exit-bars" in base and "--stale-exit-bars" not in abl
    assert abl[abl.index("--start") + 1] == "2024-10-05" and abl[abl.index("--end") + 1] == "2026-10-03 23:59"
    # an unset of a key the leg does not declare is a no-op, not an error
    noop, _ = e.build_arm_argv("trend_donchian_eth_prop", e.arm_cfg(legs["trend_donchian_eth_prop"], {}, ["stale_exit_bars"]),
                               "<d>", "1h", "<e>", "<j>", [], None, None)
    assert "--stale-exit-bars" not in noop
