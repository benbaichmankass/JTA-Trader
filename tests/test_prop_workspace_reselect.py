"""PROP-TRADEIFY-WORKSPACE-RECUR (manager 2026-11-16): the tradeify_1 terminal fell back to the "Trading Dashboard"
workspace twice in ~24 h (page-load timeout reloads the default tab), the Positions / Orders tables vanished and the
executor was blind ~3.5 h with an open position. A table read that comes back missing now re-selects "My Trading
Account" ONCE per adapter (once per tick) through select_workspace's own click-only guards, then re-reads; a refused or
failed re-select leaves the original LookupError so the failure streak / single red flag / RECOVERED line are unchanged.
No halt, no new gate."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import Any, Dict, List

import pytest

from scripts.prop import prop_executor_tick as tick
from src.prop.platform import dxtrade
from src.prop.platform.dxtrade import DXtradeAdapter
from tests.test_prop_instrument_info_probe import browser  # noqa: F401  (fixture reuse)

POS_TABLE = {"headers": ["Symbol", "Side", "Quantity", "Open Price", "Stop Loss", "Take Profit"],
             "rows": [["SOL/USD", "Sell", "27.27", "71.34", "73.173", "68.591"]]}
ORD_TABLE = {"headers": ["Symbol", "Side", "Type", "Quantity", "Price"], "rows": []}


class Fake(DXtradeAdapter):
    """The adapter with the page replaced: ``tables`` is what the page shows on each workspace."""

    def __init__(self, *, on_other: bool = True, select_result: Dict[str, Any] = None):
        super().__init__(timeout_ms=1_000)
        self.on_other = on_other
        self.select_calls: List[Any] = []
        self._select_result = select_result or {"selected": True, "refused": None, "clicks": ["workspace:My Trading Account"],
                                                "watchlist_ok": True, "workspaces_before": [{"name": "Trading Dashboard", "current": True}]}

    def _show_tab(self, page, key):
        return True

    def _tables(self, page):
        return [] if self.on_other else [POS_TABLE, ORD_TABLE]

    def select_workspace(self, page, *, name="My Trading Account"):
        self.select_calls.append(name)
        if self._select_result.get("selected"):
            self.on_other = False
        return dict(self._select_result)


def test_a_missing_positions_table_reselects_the_workspace_once_and_rereads():
    a = Fake()
    got = a.read_positions(None)
    assert [p.symbol for p in got] == ["SOLUSD"] and got[0].stop_loss == 73.173 and got[0].take_profit == 68.591
    assert a.select_calls == ["My Trading Account"]
    (ev,) = a.workspace_events
    assert ev["what"] == "workspace_reselect" and ev["selected"] is True and ev["trigger"] == "positions table not found"
    # the orders read that follows needs no second click: the tab is already current
    assert a.read_orders(None) == [] and a.select_calls == ["My Trading Account"] and len(a.workspace_events) == 1


def test_a_refused_reselect_keeps_the_original_failure_and_clicks_nothing_more():
    a = Fake(select_result={"selected": False, "refused": "one-click not confirmed OFF (on)", "clicks": []})
    with pytest.raises(LookupError, match="no positions table found on the page"):
        a.read_positions(None)
    with pytest.raises(LookupError, match="no orders table found on the page"):
        a.read_orders(None)                                   # still failing, but NO second attempt this tick
    assert a.select_calls == ["My Trading Account"]
    (ev,) = a.workspace_events
    assert ev["selected"] is False and "one-click" in ev["refused"]


def test_an_exception_inside_the_reselect_is_contained():
    class Boom(Fake):
        def select_workspace(self, page, *, name="My Trading Account"):
            raise RuntimeError("page closed")

    a = Boom()
    with pytest.raises(LookupError):
        a.read_positions(None)
    assert a.workspace_events[0]["refused"].startswith("RuntimeError")


def test_a_healthy_page_never_clicks():
    a = Fake(on_other=False)
    assert len(a.read_positions(None)) == 1 and a.read_orders(None) == []
    assert a.select_calls == [] and a.workspace_events == []


def test_the_reselect_can_be_switched_off_per_adapter():
    a = Fake()
    a.auto_reselect_workspace = False
    with pytest.raises(LookupError):
        a.read_positions(None)
    assert a.select_calls == []


def test_already_current_does_not_count_as_a_recovery_and_is_not_retried():
    """The tab is already 'My Trading Account' (the watchlist/positions table is missing for another reason): the guarded
    step is a no-op, so there is nothing to re-read and the original failure stands."""
    a = Fake(select_result={"selected": False, "already_current": True, "refused": None, "clicks": [], "watchlist_ok": False})
    with pytest.raises(LookupError):
        a.read_positions(None)
    assert a.workspace_events[0]["already_current"] is True and a.workspace_events[0]["selected"] is False


def test_the_tick_emits_the_event_and_a_recovered_alert_once(capsys):
    a = Fake()
    a.read_positions(None)
    tick.emit_workspace_events(a)
    tick.emit_workspace_events(a)                              # drained: nothing twice
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [next(iter(l)) for l in lines] == ["action", "alert"]
    assert lines[0]["action"]["what"] == "workspace_reselect" and "re-selected" in lines[1]["alert"]


def test_the_tick_emits_the_refusal_without_a_recovered_alert(capsys):
    a = Fake(select_result={"selected": False, "refused": "2 workspace tabs named 'My Trading Account' (need exactly 1)", "clicks": []})
    with pytest.raises(LookupError):
        a.read_positions(None)
    tick.emit_workspace_events(a)
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [next(iter(l)) for l in lines] == ["action"] and "need exactly 1" in lines[0]["action"]["refused"]


def test_a_non_dxtrade_adapter_without_the_hook_is_harmless(capsys):
    class Plain:
        pass

    tick.emit_workspace_events(Plain())
    assert capsys.readouterr().out == ""


# ---- the real click path on a page that shows the tables only on "My Trading Account" (needs playwright) ---------------

def _page(browser, current="Trading Dashboard"):  # noqa: F811
    tabs = ("My Trading Account", "Trading Dashboard")
    toggle = ('<div style="position:relative;height:17px"><div data-test-id="one_click_trading" data-value="false" '
              'style="position:absolute;left:0;top:0;width:26px;height:16px"></div>'
              '<div style="position:absolute;left:2px;top:2px;width:12px;height:12px"></div>'
              '<div style="margin-left:30px">One-click trading</div></div>')
    lis = "".join(
        f'<li data-test-id="{"workspace_current" if t == current else "workspace_tab"}" data-ws="{t}">'
        f'<span data-test-id="workspace_name">{t}</span></li>' for t in tabs)
    mine = ('<div data-test-id="widget_tab">Watchlist</div><table><thead><tr><th>Symbol</th><th>Bid</th><th>Ask</th></tr></thead></table>'
            '<table><tbody><tr class="instrument" data-row-id="0"><td>SOL/USD</td><td><button>1.1</button></td><td><button>1.2</button></td></tr></tbody></table>'
            '<table><thead><tr><th>Symbol</th><th>Side</th><th>Quantity</th><th>Open Price</th><th>Stop Loss</th><th>Take Profit</th></tr></thead>'
            '<tbody><tr><td>SOL/USD</td><td>Sell</td><td>27.27</td><td>71.34</td><td>73.173</td><td>68.591</td></tr></tbody></table>'
            '<table><thead><tr><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th></tr></thead><tbody></tbody></table>')
    html = f"""<html><body>{toggle}<ul>{lis}</ul><div id="body"></div><script>
      const MINE = `{mine}`;
      function render() {{
        const cur = document.querySelector('[data-test-id=workspace_current]');
        document.getElementById('body').innerHTML = (cur && cur.dataset.ws === 'My Trading Account') ? MINE : '<div data-test-id="widget_tab">Dashboard</div>';
      }}
      document.querySelectorAll('[data-test-id=workspace_name]').forEach(sp => sp.addEventListener('click', () => {{
        window.__clicks = (window.__clicks || 0) + 1;
        document.querySelectorAll('li').forEach(li => li.setAttribute('data-test-id', 'workspace_tab'));
        sp.parentElement.setAttribute('data-test-id', 'workspace_current'); render(); }}));
      render();</script></body></html>"""
    p = browser.new_page()
    p.set_content(html)
    return p


def test_on_a_real_page_the_dashboard_workspace_is_recovered_by_one_click(browser):  # noqa: F811
    p = _page(browser)
    a = DXtradeAdapter(timeout_ms=3_000)
    got = a.read_positions(p)
    assert [x.symbol for x in got] == ["SOLUSD"] and got[0].stop_loss == 73.173
    assert p.evaluate("window.__clicks") == 1 and a.workspace_events[0]["selected"] is True
    a.read_orders(p)
    assert p.evaluate("window.__clicks") == 1                  # one click per tick, never more
