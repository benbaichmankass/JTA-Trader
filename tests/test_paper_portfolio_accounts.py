"""S-PAPER-PORTFOLIO — the two live-portfolio-mirror paper accounts.

`bybit_portfolio` and `alpaca_portfolio` exist to mirror the *actual
live-traded portfolio* (bybit_2 / alpaca_live) on paper money, so the real
portfolio's performance + risk plumbing can be read without the small-account
constraints of the real books or the soak-roster noise.

These tests turn the ``ROSTER-SYNC`` comments in ``config/accounts.yaml`` into
an ENFORCED invariant: if the real-money roster changes and the mirror is not
kept in step, CI fails here (guard structure, not judgment — sanctioned by the
canonical rules). ``alpaca_portfolio`` carries ONE operator-approved divergence:
it drops the affordability-only proxies SPYM/IAUM so a big-balance paper book
doesn't double S&P/gold exposure.

``bybit_portfolio`` is STRICT EQUALITY with ``bybit_2``.

``alpaca_portfolio`` is a SUPERSET of ``alpaca_live`` (operator, 2026-11-01, in chat, relayed by Manager Session
2026-11-01a, verbatim): *"The paper portfolio decision is wrong - it should mirror the live account, as per the
definition of paper mirror."* and *"The only difference with alpaca mirror is that it also has shorting and includes
the symbols we can't yet trade on alpaca live, but there's no excuse for that account having nothing/less than alpaca
live trading, that's a serious process flaw that is unacceptable"*. This REVERSES the 2026-09-21 B2 decision
(strict equality minus the affordability proxies, "empty live => empty mirror"), under which the proxy carve-out left
the mirror EMPTY while alpaca_live traded iaum_pullback_1d, and CI enforced the empty mirror.

The rule now: every alpaca_live leg is on the mirror, with each affordability PROXY replaced by the full-size leg it
proxies (``_ALPACA_PROXY_UNDERLYING``), never just dropped; every alpaca_live symbol (proxy symbols mapped likewise) is
on the mirror's pull list; the mirror trades BOTH sides (``alpaca_live`` is a long-only cash book). The mirror MAY
carry more. An empty mirror while alpaca_live has a leg fails here.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ACCOUNTS_YAML = _REPO_ROOT / "config" / "accounts.yaml"

# alpaca_live affordability proxies -> the full-size leg / symbol they proxy. MEASURED 2026-11-01 from
# config/strategies.yaml: iaum_pullback_1d's config comment reads "proxy for gld_pullback_1d" and its parameters equal
# gld_pullback_1d's except symbols/signal_prefixes; splg_trend_long_1d reads "proxy for spy_trend_long_1d" (its exit
# params have since diverged: tp_r/atr_stop_mult/trail_decay, so mapping it is by underlying, stated).
_ALPACA_PROXY_UNDERLYING = {"iaum_pullback_1d": "gld_pullback_1d", "splg_trend_long_1d": "spy_trend_long_1d"}
_ALPACA_PROXY_SYMBOL_UNDERLYING = {"IAUM": "GLD", "SPYM": "SPY"}
_ALPACA_PROXY_STRATEGIES = set(_ALPACA_PROXY_UNDERLYING)
_ALPACA_PROXY_SYMBOLS = set(_ALPACA_PROXY_SYMBOL_UNDERLYING)


def _accounts() -> dict:
    data = yaml.safe_load(_ACCOUNTS_YAML.read_text(encoding="utf-8")) or {}
    return data.get("accounts") or {}


def _expected_mirror_roster(alpaca_live_cfg: dict) -> list[str]:
    """The legs ``alpaca_portfolio`` must AT LEAST carry: alpaca_live's roster, each proxy replaced by its
    underlying. ONE definition, read by every alpaca mirror test."""
    return [_ALPACA_PROXY_UNDERLYING.get(s, s) for s in (alpaca_live_cfg.get("strategies") or [])]


def _expected_mirror_symbols(alpaca_live_cfg: dict) -> list[str]:
    return [_ALPACA_PROXY_SYMBOL_UNDERLYING.get(s, s) for s in (alpaca_live_cfg.get("symbols") or [])]


def test_portfolio_accounts_present_and_paper():
    accts = _accounts()
    for aid in ("bybit_portfolio", "alpaca_portfolio"):
        assert aid in accts, f"{aid} missing from config/accounts.yaml"
        cfg = accts[aid]
        assert cfg.get("account_class") == "paper", f"{aid} must be paper money"
        assert cfg.get("paper_role") == "portfolio", (
            f"{aid} must carry paper_role: portfolio (the live-portfolio-mirror "
            "marker the dashboard/Android 'Paper' view scopes to)"
        )
        assert str(cfg.get("mode")) == "live", f"{aid} paper account executes (mode: live)"


def test_bybit_portfolio_key_wiring():
    cfg = _accounts()["bybit_portfolio"]
    assert cfg.get("exchange") == "bybit"
    assert cfg.get("demo") is True, "bybit_portfolio trades the Bybit demo (paper) venue"
    assert cfg.get("api_key_env") == "BYBIT_API_KEY_3", (
        "bybit_portfolio uses the reutilized 'bybit 3' demo keys "
        "(secret BYBIT_API_SECRET_3 auto-derived by clients._derive_secret_env)"
    )


def test_alpaca_portfolio_key_wiring():
    cfg = _accounts()["alpaca_portfolio"]
    assert cfg.get("exchange") == "alpaca"
    assert cfg.get("alpaca_env") == "paper"
    assert cfg.get("api_key_env") == "ALPACA_API_KEY_PAPER_PORTFOLIO"
    assert cfg.get("api_secret_env") == "ALPACA_API_SECRET_KEY_PAPER_PORTFOLIO"


def test_bybit_portfolio_mirrors_bybit_2_exactly():
    accts = _accounts()
    portfolio, real = accts["bybit_portfolio"], accts["bybit_2"]
    assert portfolio.get("strategies") == real.get("strategies"), (
        "bybit_portfolio must mirror bybit_2's roster exactly — keep them in "
        "step (ROSTER-SYNC). If bybit_2's roster changed, update bybit_portfolio."
    )
    assert portfolio.get("symbols") == real.get("symbols"), (
        "bybit_portfolio must mirror bybit_2's symbols exactly (ROSTER-SYNC)."
    )
    # Same sizing basis so the paper read is representative of the live account.
    assert portfolio["risk"].get("leverage") == real["risk"].get("leverage")
    assert portfolio["risk"].get("risk_pct") == real["risk"].get("risk_pct")


def test_alpaca_portfolio_covers_every_alpaca_live_leg():
    """SUPERSET (operator 2026-11-01): every alpaca_live leg, proxies replaced by their underlying, is on the
    mirror. Fails whenever the mirror carries FEWER legs than live, the empty mirror included."""
    accts = _accounts()
    portfolio, real = accts["alpaca_portfolio"], accts["alpaca_live"]
    expected = _expected_mirror_roster(real)
    port = list(portfolio.get("strategies") or [])
    missing = sorted(set(expected) - set(port))
    assert not missing, (
        "alpaca_portfolio must carry every alpaca_live leg, each affordability proxy replaced by its underlying "
        f"{_ALPACA_PROXY_UNDERLYING} (operator 2026-11-01: 'no excuse for that account having nothing/less than "
        f"alpaca live trading'). Missing: {missing}; mirror: {port}"
    )
    assert len(port) >= len(real.get("strategies") or []), (port, real.get("strategies"))


def test_alpaca_portfolio_is_never_empty_while_alpaca_live_trades():
    accts = _accounts()
    if accts["alpaca_live"].get("strategies"):
        assert accts["alpaca_portfolio"].get("strategies"), "alpaca_portfolio is empty while alpaca_live has legs"


def test_alpaca_portfolio_symbols_cover_alpaca_live():
    accts = _accounts()
    portfolio, real = accts["alpaca_portfolio"], accts["alpaca_live"]
    missing = sorted(set(_expected_mirror_symbols(real)) - set(portfolio.get("symbols") or []))
    assert not missing, f"alpaca_portfolio symbols must cover alpaca_live's (proxies mapped). Missing: {missing}"


def test_alpaca_proxy_mapping_names_real_legs():
    """The mapping is checked against config, not trusted: each proxy and its underlying are configured legs, and
    the proxy trades the proxy symbol while the underlying trades the underlying symbol."""
    strategies = (yaml.safe_load((_REPO_ROOT / "config" / "strategies.yaml").read_text()) or {}).get("strategies") or {}
    for proxy, under in _ALPACA_PROXY_UNDERLYING.items():
        assert proxy in strategies and under in strategies, (proxy, under)
        psym, usym = strategies[proxy].get("symbols") or [], strategies[under].get("symbols") or []
        assert len(psym) == 1 and len(usym) == 1, (psym, usym)
        assert _ALPACA_PROXY_SYMBOL_UNDERLYING.get(psym[0]) == usym[0], (proxy, psym, under, usym)


def test_superset_probe_catches_an_empty_mirror():
    """Positive control: the B2-era state (live [iaum_pullback_1d], mirror []) is refused by this probe."""
    expected = _expected_mirror_roster({"strategies": ["iaum_pullback_1d"]})
    assert expected == ["gld_pullback_1d"]
    assert set(expected) - set([]) == {"gld_pullback_1d"}


# ── Trade-shaping fields: the mirror must take the SAME trades, not only carry
# the same roster (PI-20260928-E8Y3BGBS-0002 / -SVBNZOVH-0002, 2026-09-30).
#
# Roster equality alone let ``alpaca_portfolio`` trade the shorts
# ``alpaca_live``'s ``side_filter: long`` suppresses, and run at half live's
# daily-loss / max-DD tolerance — so Gate 2's demotion read was a different
# book's P&L. The check below is FAIL-CLOSED: every key either account declares
# must be EQUAL on the two, unless it is in ``_MIRROR_IDENTITY_KEYS`` — the keys
# that name WHICH venue, credentials or money class the book is, and so differ
# by construction. A new per-account gate added to the live account only turns
# this red without anyone remembering to list it.
#
# The per-account inputs ``Coordinator.multi_account_execute`` reads that decide
# WHETHER and HOW BIG a package trades, all covered by that rule:
#   mode              → effective_dry (account execution gate)
#   side_filter       → effective_dry for a suppressed direction
#   options           → options-expression (debit spread instead of a short)
#   market_type       → sizing branch + Bybit category
#   exchange / type   → routing + account_type scope
#   enabled           → load_accounts drops the account
#   risk.*            → RiskManager: risk_pct, max_dd_pct, daily_loss_pct,
#                       daily_usd, leverage, max_gross_exposure_pct,
#                       confidence_sizing/_floor/_knee, min_qty, qty_precision
#   strategies        → per-account roster filter (asserted above, with the
#                       proxy carve-out)
#
# NOT config, so NOT assertable here, and each can still make the two books
# take different trades — stated so no one reads green as "identical":
#   * the venue's ``shorting_enabled`` (broker_shorting_gate): alpaca_live is a
#     cash book that reads false; moot for OPENS while both carry
#     ``side_filter: long``;
#   * ALPACA_CASH_SETTLEMENT_ACCOUNTS (env): the T+1 basis binds alpaca_live
#     only (accounts.yaml alpaca_live comment: the mirror measured negative
#     venue_cash and would halt under ``apply``);
#   * cash vs margin buying power: the whole-share cash wall refuses on the
#     ~$200 live book what the paper book sizes.
_MIRROR_IDENTITY_KEYS = {
    "account_class",   # real_money vs paper — the point of the pair
    "paper_role",      # the mirror's marker
    "alpaca_env",      # live vs paper host
    "api_key_env",     # its own credentials
    "api_secret_env",
    "demo",            # Bybit demo venue selector
    "strategies",      # asserted by the roster tests (superset, proxies mapped)
    "symbols",         # asserted by the roster tests (superset, proxies mapped)
}

#: Declared, per-pair trade-shaping divergences, each with the operator decision behind it. NOT the identity
#: allowlist above (which may never hold a trade gate): this names a gate that differs ON PURPOSE.
_SANCTIONED_DIVERGENCE = {
    ("alpaca_live", "alpaca_portfolio"): {
        # operator 2026-11-01: "The only difference with alpaca mirror is that it also has shorting ..."
        "side_filter": ("long", None),
    },
}


def _trade_shaping_diff(live: dict, mirror: dict) -> dict:
    keys = (set(live) | set(mirror)) - _MIRROR_IDENTITY_KEYS
    return {k: (live.get(k), mirror.get(k))
            for k in sorted(keys) if live.get(k) != mirror.get(k)}


@pytest.mark.parametrize("live_id,mirror_id", [
    ("bybit_2", "bybit_portfolio"),
    ("alpaca_live", "alpaca_portfolio"),
])
def test_mirror_trade_shaping_fields_equal_live(live_id, mirror_id):
    accts = _accounts()
    diff = _trade_shaping_diff(accts[live_id], accts[mirror_id])
    for k, pair in _SANCTIONED_DIVERGENCE.get((live_id, mirror_id), {}).items():
        if diff.get(k) == pair:
            diff.pop(k)
    assert not diff, (
        f"{mirror_id} must take the SAME trades as {live_id} (CLAUDE.md § The "
        "promotion ladder; B2 2026-09-21), so every trade-shaping field must be "
        "equal. Differing (live, mirror): " + repr(diff) + ". If a key is "
        "genuinely an identity field rather than a trade gate, add it to "
        "_MIRROR_IDENTITY_KEYS with the reason — that is an operator-visible "
        "decision, not a test fix."
    )


def test_alpaca_portfolio_trade_shaping_fields_equal_alpaca_live():
    """alpaca_live is long-only; the mirror trades BOTH sides (operator 2026-11-01). Risk stays equal."""
    accts = _accounts()
    live, mirror = accts["alpaca_live"], accts["alpaca_portfolio"]
    assert live.get("side_filter") == "long"
    assert mirror.get("side_filter") in (None, "both")
    assert mirror["risk"] == live["risk"]


def test_identity_allowlist_never_swallows_a_trade_gate():
    """The carve-out must not be widened to hide a gate."""
    for gate in ("mode", "side_filter", "options", "market_type", "risk",
                 "exchange", "type", "enabled"):
        assert gate not in _MIRROR_IDENTITY_KEYS, gate


def test_the_comparison_catches_a_side_filter_divergence():
    """Positive control: the probe can find what it is looking for."""
    assert _trade_shaping_diff(
        {"side_filter": "long", "api_key_env": "A"}, {"api_key_env": "B"},
    ) == {"side_filter": ("long", None)}


def test_paper_role_surfaced_on_config_api():
    """paper_role must be in the /api/bot/config account allowlist so consumers
    can distinguish portfolio-paper from soak-paper (imported lazily so the
    test is skippable where FastAPI isn't installed, e.g. a lint-only env)."""
    try:
        from src.web.api.routers.bot_config import _ACCOUNT_PUBLIC_FIELDS
    except Exception:  # pragma: no cover - FastAPI absent (sandbox/lint)
        import pytest
        pytest.skip("bot_config router not importable in this environment")
    assert "paper_role" in _ACCOUNT_PUBLIC_FIELDS


def test_mirror_carries_the_same_position_model_as_live():
    """NETTED-SLICES: `position_model: slices` changes which trades an account
    takes (several strategies may each hold a slice), so a mirror must carry
    exactly the live book's value — the rollout puts it on bybit_2 and
    bybit_portfolio TOGETHER. Named so a one-sided edit reads by name in CI."""
    accts = _accounts()
    assert accts["bybit_portfolio"].get("position_model") == accts["bybit_2"].get("position_model")
    assert _trade_shaping_diff({"position_model": "slices"}, {}) == {
        "position_model": ("slices", None)}
