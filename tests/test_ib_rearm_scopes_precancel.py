"""Every IB re-arm must scope its pre-cancel to the trade's OWN OCA group.

BL-20260825-THE-TRAILING-AMEND-NEVER-PASSES-OCA-KEY-SO-IT-STILL-CANCELS-SYMBOL-WIDE.

#10282 gave `place_protective` a deterministic per-trade group
`oca-protect-t<oca_key>`, whose fallback when no key is supplied is the legacy
SYMBOL-WIDE cancel — the branch the code itself flags as able to cancel a
sibling trade's protective legs on a netted contract
(BL-20260814-IB-PROTECTION-BOOLEAN-NOT-QUANTITY).

Measured by reading every call site 2026-08-25: three IB callers reached
`place_protective` / `modify_protective`, ONE passed `oca_key`
(`_attempt_naked_autoprotect`) and TWO did not — `execute.modify_open_order`'s
IB branch, which is the trailing amend that runs on every stop move and is
therefore the most frequent re-arm in the system, and
`_reassert_from_divergence`, inert at the default
`PROTECTION_REASSERT_MODE=annotate` but which would have inherited the defect
silently on the flip to `apply`.

Live corroboration: both resting `ib_paper` MHG groups were named
`oca-protect-465` / `oca-protect-446` — the legacy `<orderId>` form with no
`t` prefix, i.e. minted by the no-key path.

IB nets per contract per account, so the consequence is concrete: a symbol-wide
cancel from one trade's trailing amend deletes the OTHER trades' resting
take-profit legs and replaces them with a bracket covering only the amending
trade's qty. That is the documented mechanism behind a take-profit that was
reached and never executed.
"""
from __future__ import annotations

import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]


class _FakeIB:
    """Stands in for IBClient — records the order dict it was handed."""

    def __init__(self):
        self.seen = []

    def modify_protective(self, order):
        self.seen.append(order)
        return {"retCode": 0, "result": {"orderId": 1}}


@pytest.fixture()
def ib(monkeypatch):
    import src.units.accounts.execute as ex
    from src.units.accounts.ib_client import IBClient

    fake = _FakeIB()
    # modify_open_order's IB branch isinstance-checks the client, so the fake
    # must pass that gate without opening a socket.
    monkeypatch.setattr(ex, "modify_open_order", ex.modify_open_order)
    fake.__class__ = type("_FakeIBClient", (IBClient,), {
        "modify_protective": lambda self, order: (
            fake.seen.append(order) or {"retCode": 0, "result": {"orderId": 1}}
        ),
        "__init__": lambda self: None,
    })
    return fake


def _call(trade_id, ib_client):
    from src.units.accounts.execute import modify_open_order
    return modify_open_order(
        ib_client, {"account_id": "ib_paper", "exchange": "interactive_brokers"},
        symbol="MHG", side="long", qty=29.0, sl=6.312, tp=7.1415,
        trade_id=trade_id,
    )


class TestTheTrailingAmendScopesItsPreCancel:
    def test_a_trade_id_becomes_the_oca_key(self, ib):
        _call(4796, ib)
        assert ib.seen, "the IB branch must have been reached"
        assert ib.seen[0]["oca_key"] == "4796"

    def test_an_int_and_a_str_id_agree(self, ib):
        _call(4796, ib)
        _call("4796", ib)
        assert ib.seen[0]["oca_key"] == ib.seen[1]["oca_key"] == "4796"

    def test_a_missing_id_does_NOT_invent_a_key(self, ib):
        """Fabricating a group name would silently stop the re-arm cancelling
        the trade's OWN previous bracket — strictly worse than the gap."""
        _call(None, ib)
        assert "oca_key" not in ib.seen[0]

    def test_a_blank_id_is_treated_as_missing(self, ib):
        _call("   ", ib)
        assert "oca_key" not in ib.seen[0]

    def test_the_rest_of_the_order_is_unchanged(self, ib):
        _call(4796, ib)
        o = ib.seen[0]
        assert o["symbol"] == "MHG" and o["direction"] == "long"
        assert o["qty"] == 29.0 and o["sl"] == 6.312 and o["tp"] == 7.1415


class TestEveryIBCallSitePassesIt:
    """Source-level, because a call site that simply forgets the kwarg is the
    defect — and it type-checks, runs, and silently takes the legacy branch."""

    def test_the_monitor_trailing_amend_forwards_the_trade_id(self):
        src = (_REPO / "src/runtime/order_monitor.py").read_text()
        call = src[src.index("return modify_open_order("):]
        call = call[:call.index("\n        )")]
        assert 'trade_id=matched_trade.get("id")' in call

    def test_the_reassert_path_passes_oca_key(self):
        src = (_REPO / "src/runtime/order_monitor.py").read_text()
        call = src[src.index("result = client.modify_protective({"):]
        call = call[:call.index("})")]
        assert '"oca_key"' in call

    def test_the_naked_autoprotect_path_still_passes_it(self):
        """The one caller that was already correct — asserted so a future
        refactor cannot quietly drop it while the other two are watched."""
        src = (_REPO / "src/runtime/order_monitor.py").read_text()
        call = src[src.index("resp = client.place_protective("):]
        call = call[:call.index("\n        )")]
        assert '"oca_key"' in call

    #: Every re-arm call site in order_monitor, by ENCLOSING FUNCTION -> venue. A new site fails
    #: the population test below until it is named here (so a reviewer sees which venue it is),
    #: and every site, IB or Alpaca, must pass oca_key (inert on Alpaca, the scope on IB).
    #: History: 3 since PI-20260929-PR6YRTQY-0003 (_alpaca_top_up_uncovered); 4 since
    #: PR6YRTQY-0005 / REVIEW-14241 (the naked-sweep additive OCO); 5 since
    #: ALPACA-PARTIAL-TP-STOP-GAP (_alpaca_protect_after_target_cancel); 6 since
    #: BRACKETS-ALWAYS item 4 (_alpaca_restore_declared_target, #27141).
    REARM_CALL_SITES = {
        "_alpaca_top_up_uncovered": "alpaca",
        "_attempt_naked_autoprotect": "ib+alpaca",
        "_alpaca_protect_after_target_cancel": "alpaca",
        "_alpaca_restore_declared_target": "alpaca",
        "_check_broker_naked_equity_positions": "alpaca",
        "_reassert_from_divergence": "ib",
    }

    @staticmethod
    def _rearm_calls(src):
        """(enclosing function, call text) for every modify_/place_protective( call."""
        import re
        out = []
        for m in re.finditer(r"\b(modify_protective|place_protective)\(", src):
            d = src.rfind("\ndef ", 0, m.start())
            fn = src[d + 5:src.index("(", d + 5)]
            i, depth = m.end(), 1
            while depth:
                depth += (src[i] == "(") - (src[i] == ")")
                i += 1
            out.append((fn, src[m.start():i]))
        return out

    def test_no_IB_rearm_call_site_is_left_unscoped(self):
        """The population control, by name rather than by count: the set of enclosing functions
        must equal REARM_CALL_SITES exactly (a new site FAILS until it is registered with its
        venue), each function holds exactly one call, and every call passes oca_key."""
        src = (_REPO / "src/runtime/order_monitor.py").read_text()
        calls = self._rearm_calls(src)
        fns = [fn for fn, _ in calls]
        assert sorted(fns) == sorted(self.REARM_CALL_SITES), (
            f"re-arm call sites in order_monitor are {sorted(fns)}; registered "
            f"{sorted(self.REARM_CALL_SITES)}. A new one must pass oca_key and be named "
            "in REARM_CALL_SITES with its venue."
        )
        unscoped = [fn for fn, call in calls if '"oca_key"' not in call]
        assert not unscoped, f"re-arm call(s) without oca_key: {unscoped}"
