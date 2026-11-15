"""select-workspace (PROP-TRADEIFY-WORKSPACE-SWITCHED, 2026-11-15): after a 45 s page-load
timeout the tradeify_1 terminal came back on "Trading Dashboard"; the watchlist and the
positions table live on "My Trading Account", so every executor read failed. ONE click on the
named tab's name span, never its close control; refused unless one-click reads OFF."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from src.prop.platform.dxtrade import DXtradeAdapter
from tests.test_prop_instrument_info_probe import browser  # noqa: F401  (fixture reuse)

REPO = Path(__file__).resolve().parents[1]
WATCHLIST = ('<div data-test-id="widget_tab">Watchlist</div>'
             '<table><thead><tr><th>Symbol</th><th>Bid</th><th>Ask</th></tr></thead></table>'
             '<table><tbody>'
             '<tr class="instrument" data-row-id="0"><td>SOL/USD</td><td><button>1.1</button></td><td><button>1.2</button></td></tr>'
             '</tbody></table>')


def page(browser, *, current="Trading Dashboard", one_click_on=False,  # noqa: F811
         tabs=("My Trading Account", "Trading Dashboard")):
    toggle = (f'<div style="position:relative;height:17px">'
              f'<div data-test-id="one_click_trading" data-value="{"true" if one_click_on else "false"}" '
              f'style="position:absolute;left:0;top:0;width:26px;height:16px"></div>'
              f'<div style="position:absolute;left:{"12px" if one_click_on else "2px"};top:2px;width:12px;height:12px"></div>'
              f'<div style="margin-left:30px">One-click trading</div></div>')
    lis = "".join(
        f'<li data-test-id="{"workspace_current" if t == current else "workspace_tab"}" data-ws="{t}">'
        f'<span data-test-id="workspace_name">{t}</span>'
        f'<button data-test-id="workspace_close_button" onclick="window.__del=(window.__del||0)+1">x</button></li>'
        for t in tabs)
    html = f"""<html><body>{toggle}<ul>{lis}</ul><div id="body"></div>
      <script>
        const WL = `{WATCHLIST}`;
        function render() {{
          const cur = document.querySelector('[data-test-id=workspace_current]');
          document.getElementById('body').innerHTML =
            (cur && cur.dataset.ws === 'My Trading Account') ? WL : '<div data-test-id="widget_tab">Dashboard</div>';
        }}
        document.querySelectorAll('[data-test-id=workspace_name]').forEach(sp => sp.addEventListener('click', () => {{
          window.__clicks = (window.__clicks || 0) + 1;
          document.querySelectorAll('li').forEach(li => li.setAttribute('data-test-id', 'workspace_tab'));
          sp.parentElement.setAttribute('data-test-id', 'workspace_current');
          render();
        }}));
        render();
      </script></body></html>"""
    p = browser.new_page()
    p.set_content(html)
    return p


def clicks(p):
    return p.evaluate("({clicks: window.__clicks||0, del: window.__del||0})")


def test_reselects_my_trading_account_with_one_click_and_the_watchlist_reads_back(browser):  # noqa: F811
    p = page(browser)
    got = DXtradeAdapter(timeout_ms=3_000).select_workspace(p)
    assert got["refused"] is None and got["selected"] is True and got["watchlist_ok"] is True
    assert got["clicks"] == ["workspace:My Trading Account"]
    assert clicks(p) == {"clicks": 1, "del": 0}


def test_noop_when_already_current(browser):  # noqa: F811
    p = page(browser, current="My Trading Account")
    got = DXtradeAdapter(timeout_ms=3_000).select_workspace(p)
    assert got["already_current"] is True and got["clicks"] == [] and got["watchlist_ok"] is True
    assert clicks(p) == {"clicks": 0, "del": 0}


def test_refused_with_nothing_clicked_unless_one_click_reads_off(browser):  # noqa: F811
    p = page(browser, one_click_on=True)
    got = DXtradeAdapter(timeout_ms=3_000).select_workspace(p)
    assert got["refused"] and "one-click" in got["refused"] and got["selected"] is False
    assert clicks(p) == {"clicks": 0, "del": 0}


def test_refused_when_the_tab_is_absent_or_ambiguous(browser):  # noqa: F811
    for tabs in (("Trading Dashboard", "Other"), ("My Trading Account", "My Trading Account", "Trading Dashboard")):
        p = page(browser, tabs=tabs)
        got = DXtradeAdapter(timeout_ms=3_000).select_workspace(p)
        assert got["refused"] and "need exactly 1" in got["refused"]
        assert clicks(p) == {"clicks": 0, "del": 0}


def test_tick_resolves_the_mode():
    from scripts.prop.prop_executor_tick import YIELD_MODES, resolve_mode
    args = argparse.Namespace(probe_ticket="", dry_run=False, watched_click=False, select_workspace=True,
                              account="tradeify_1")
    assert resolve_mode(args, {}) == "select_workspace"
    assert "select_workspace" in YIELD_MODES


def test_action_refuses_select_workspace_for_breakout_1(tmp_path):
    import shutil

    from tests.test_prop_executor_clear_halt import STUB_LIB
    d = tmp_path / "ops"
    d.mkdir()
    shutil.copy(REPO / "scripts" / "ops" / "breakout_login_check_action.sh", d / "action.sh")
    (d / "_lib.sh").write_text(STUB_LIB)
    home = tmp_path / "home"
    (home / ".cache" / "metis-prop-browser").mkdir(parents=True)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "ACTION_APPLY": "select-workspace"}
    p = subprocess.run(["bash", str(d / "action.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 1
    assert "select-workspace: refused for breakout_1" in p.stdout + p.stderr
