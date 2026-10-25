"""MIRROR-QTY-DIVERGE — a Stage-2 mirror pair cannot silently diverge.

Incident: 2026-10-09T06:02Z, ``xrp_pullback_2h`` short, pkg-63b56da53bfe4d64.
bybit_2 sent a 0.5 XRP intent-mode top-up delta (journal said 57.4, the
target), the venue refused it (110094, min order value 5 USDT), and
bybit_portfolio's 160.9 XRP delta filled. These tests pin the three fixes:

1. a mirror places a package only if its primary placed it (``mirror_pairs``),
   and the unpreventable reverse direction raises an ERROR alert;
2. an opening delta below the venue's minimum ORDER VALUE is a benign noop,
   never a venue reject;
3. an exchange-rejected row journals the qty actually SENT.
"""
from __future__ import annotations

import os
import textwrap

import pytest
import yaml

from src.core.coordinator import Coordinator, OrderPackage
from src.runtime import mirror_pairs as mp
from src.runtime.intents import INTENT_MODE_META_KEY, INTENT_MODE_META_VALUE
from tests.test_intent_delta_dispatch import _init_trade_journal, _insert_trade

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# The pair map is pinned to config/accounts.yaml
# ---------------------------------------------------------------------------


def _accounts():
    with open(os.path.join(_REPO, "config", "accounts.yaml")) as fh:
        data = yaml.safe_load(fh)
    return data.get("accounts", data)


def test_every_portfolio_mirror_is_in_the_pair_map():
    accts = _accounts()
    portfolio = {
        name for name, cfg in accts.items()
        if isinstance(cfg, dict) and str(cfg.get("paper_role") or "") == "portfolio"
    }
    assert portfolio == set(mp.MIRROR_PAIRS), (
        "every paper_role: portfolio account must name its real-money primary "
        "in src/runtime/mirror_pairs.py::MIRROR_PAIRS (and nothing else may)"
    )
    for mirror, primary in mp.MIRROR_PAIRS.items():
        assert primary in accts, f"{mirror}'s primary {primary} is not an account"
        assert accts[primary].get("account_class") == "real_money"
        assert accts[mirror].get("account_class") == "paper"


class _A:
    def __init__(self, name):
        self.name = name


def test_order_primaries_first_moves_mirror_after_primary():
    accts = [_A("alpaca_portfolio"), _A("bybit_1"), _A("alpaca_live"),
             _A("bybit_2"), _A("bybit_portfolio")]
    out = [a.name for a in mp.order_primaries_first(accts, lambda a: a.name)]
    assert out.index("alpaca_portfolio") > out.index("alpaca_live")
    assert out.index("bybit_portfolio") > out.index("bybit_2")
    assert sorted(out) == sorted(a.name for a in accts)


def test_order_primaries_first_leaves_lone_mirror_in_place():
    accts = [_A("bybit_portfolio"), _A("bybit_1")]
    out = [a.name for a in mp.order_primaries_first(accts, lambda a: a.name)]
    assert out == ["bybit_portfolio", "bybit_1"]


@pytest.mark.parametrize("results,excluded,verdict", [
    ([{"name": "bybit_2", "trade_id": "t1"}], {}, mp.FOLLOW),
    ([{"name": "bybit_2", "trade_id": None, "error": "RuntimeError: 110094"}], {}, mp.SKIP),
    ([{"name": "bybit_2", "trade_id": None, "error": "intent_sub_min_qty_delta"}], {}, mp.SKIP),
    ([], {"bybit_2": "outside_account_scope"}, mp.SKIP),
    ([], {}, mp.UNOBSERVED),
])
def test_follow_decision(results, excluded, verdict):
    v, reason = mp.follow_decision("bybit_portfolio", results, excluded)
    assert v == verdict
    if verdict == mp.SKIP:
        assert reason.startswith("mirror_primary_")


def test_follow_decision_non_mirror():
    assert mp.follow_decision("bybit_1", [], {}) == (mp.NOT_A_MIRROR, None)


def test_divergences_only_primary_placed_mirror_not():
    rows = [{"name": "bybit_2", "trade_id": "t1"},
            {"name": "bybit_portfolio", "trade_id": None, "error": "boom"}]
    d = mp.divergences(rows)
    assert len(d) == 1 and d[0]["mirror"] == "bybit_portfolio"
    rows[1]["trade_id"] = "t2"
    assert mp.divergences(rows) == []


# ---------------------------------------------------------------------------
# Coordinator integration
# ---------------------------------------------------------------------------

# Mirror declared FIRST on purpose: the dispatcher must still run the primary
# first (alpaca_portfolio sits above alpaca_live in the real config).
PAIR_YAML = textwrap.dedent("""\
    accounts:
      bybit_portfolio:
        type: regular
        exchange: bybit
        account_class: paper
        paper_role: portfolio
        api_key_env: BYBIT_API_KEY_3
        demo: true
        mode: live
        market_type: linear
        strategies: [xrp_pullback_2h]
        risk: {max_dd_pct: 0.05, daily_usd: 100, risk_pct: 0.01, leverage: 3}
      bybit_2:
        type: regular
        exchange: bybit
        account_class: real_money
        api_key_env: BYBIT_API_KEY_2
        mode: live
        market_type: linear
        strategies: [xrp_pullback_2h]
        risk: {max_dd_pct: 0.05, daily_usd: 100, risk_pct: 0.01, leverage: 3}
""")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "trade_journal.db")
    _init_trade_journal(db)
    monkeypatch.setenv("TRADE_JOURNAL_DB", db)
    for n in ("2", "3"):
        monkeypatch.setenv(f"BYBIT_API_KEY_{n}", "k")
        monkeypatch.setenv(f"BYBIT_API_SECRET_{n}", "s")
    acc = tmp_path / "accounts.yaml"
    acc.write_text(PAIR_YAML)
    units = tmp_path / "units.yaml"
    units.write_text("units: {}\n")
    return {"db": db, "accounts": str(acc), "coord": Coordinator(units_path=str(units))}


def _xrp_short_pkg():
    return OrderPackage(
        strategy="xrp_pullback_2h", symbol="XRPUSDT", direction="short",
        entry=1.3964, sl=1.45509643, tp=1.2581564,
        meta={INTENT_MODE_META_KEY: INTENT_MODE_META_VALUE,
              "aggregated_target_qty": 0.0,
              "contributing_strategies": ["xrp_pullback_2h"]},
    )


def _patch(monkeypatch, *, fail_on=(), calls, rejections, alerts):
    import src.core.coordinator as coord_mod
    import src.units.accounts.clients as clients_mod
    import src.units.accounts.execute as execute_mod

    def _exec(pkg, account_cfg, *, exchange_client=None, balance_usdt=None,
              dry_run=None, qty_override=None, reduce_only=False):
        name = account_cfg.get("account_id") or account_cfg.get("name")
        calls.append((name, qty_override))
        if name in fail_on:
            raise RuntimeError(
                "Order submission failed for XRPUSDT: Order does not meet "
                "minimum order value 5USDT (ErrCode: 110094)"
            )
        return f"trade-{name}"

    monkeypatch.setattr(execute_mod, "execute_pkg", _exec)
    monkeypatch.setattr(clients_mod, "bybit_client_for", lambda cfg: object())
    monkeypatch.setattr(
        execute_mod, "log_rejection_to_journal",
        lambda pkg, cfg, **kw: rejections.append((cfg.get("account_id"), kw)) or True,
    )
    monkeypatch.setattr(coord_mod, "_log_new_order_package", lambda pkg: None)
    monkeypatch.setattr(coord_mod, "_emit_execution_failure_ping", lambda **k: None)
    monkeypatch.setattr(
        Coordinator, "push_alert",
        lambda self, msg, source="coordinator", level="info", **kw:
            alerts.append((level, msg)) or {},
    )


def _run(env):
    return env["coord"].multi_account_execute(
        _xrp_short_pkg(), accounts_path=env["accounts"],
        balance_fetcher=lambda account: 10_000.0,
    )


def test_mirror_skips_when_primary_rejected_by_venue(env, monkeypatch):
    calls, rej, alerts = [], [], []
    _patch(monkeypatch, fail_on={"bybit_2"}, calls=calls, rejections=rej, alerts=alerts)
    results = _run(env)
    # Primary dispatched first despite being declared second; mirror never sent.
    assert [c[0] for c in calls] == ["bybit_2"]
    by = {r["name"]: r for r in results}
    assert by["bybit_portfolio"]["trade_id"] is None
    assert by["bybit_portfolio"]["error"].startswith("mirror_primary_not_placed:bybit_2:")
    # The mirror's skip is journalled as a paper row (not mis-stamped real_money).
    mirror_rows = [kw for acct, kw in rej if acct == "bybit_portfolio"]
    assert mirror_rows and mirror_rows[0]["reason"].startswith("mirror_primary_not_placed")


def test_mirror_follows_when_primary_placed(env, monkeypatch):
    calls, rej, alerts = [], [], []
    _patch(monkeypatch, calls=calls, rejections=rej, alerts=alerts)
    results = _run(env)
    assert [c[0] for c in calls] == ["bybit_2", "bybit_portfolio"]
    assert all(r["trade_id"] for r in results)
    assert not [a for a in alerts if a[0] == "error"]


def test_primary_placed_mirror_failed_raises_error_alert(env, monkeypatch):
    calls, rej, alerts = [], [], []
    _patch(monkeypatch, fail_on={"bybit_portfolio"}, calls=calls,
           rejections=rej, alerts=alerts)
    _run(env)
    errs = [m for lvl, m in alerts if lvl == "error" and "mirror divergence" in m]
    assert errs, f"divergence must alert at ERROR; got {alerts}"


def test_exchange_rejected_row_records_the_sent_qty(env, monkeypatch):
    """Row 6544 said 57.4 while the POST carried 0.5: the row must say what was sent."""
    calls, rej, alerts = [], [], []
    _patch(monkeypatch, fail_on={"bybit_2"}, calls=calls, rejections=rej, alerts=alerts)
    # Existing short -> intent-mode sends a top-up DELTA, not the target.
    _insert_trade(env["db"], account_id="bybit_2", symbol="XRPUSDT",
                  direction="short", position_size=1000.0,
                  strategy_name="trend_donchian_xrp_4h")
    _run(env)
    sent = [q for name, q in calls if name == "bybit_2"]
    assert len(sent) == 1
    row = [kw for acct, kw in rej
           if acct == "bybit_2" and kw.get("status") == "exchange_rejected"]
    assert len(row) == 1
    assert row[0]["sized_qty"] == pytest.approx(sent[0])
    assert row[0]["extra_notes"]["risk_sized_qty"] > sent[0]


def test_sub_min_notional_delta_is_noop_not_a_venue_reject(env, monkeypatch):
    """The 6544 shape: a delta above the 0.1 XRP lot but worth < $5."""
    calls, rej, alerts = [], [], []
    _patch(monkeypatch, calls=calls, rejections=rej, alerts=alerts)
    # Probe the risk-sized target, then seed a short 0.4 XRP below it.
    probe_calls = []
    _patch(monkeypatch, calls=probe_calls, rejections=[], alerts=[])
    _run(env)
    target = dict(probe_calls)["bybit_2"]
    _patch(monkeypatch, calls=calls, rejections=rej, alerts=alerts)
    # Fresh journal for the real run.
    _insert_trade(env["db"], account_id="bybit_2", symbol="XRPUSDT",
                  direction="short", position_size=round(target - 0.4, 1),
                  strategy_name="trend_donchian_xrp_4h")
    results = _run(env)
    by = {r["name"]: r for r in results}
    assert by["bybit_2"]["error"] == "intent_sub_min_notional_delta"
    assert "bybit_2" not in [c[0] for c in calls]
    # ...and the mirror follows the primary's noop instead of diverging.
    assert by["bybit_portfolio"]["error"].startswith("mirror_primary_not_placed")
