"""CALENDAR-EVENT-TYPES: new calendar classes ship DATA-ON / IMPACT-NEUTRAL (weight 0).

The operator rule (2026-10-26): a new event class is emitted and logged, but carries no
weight on the trade path until its own event study earns one. The mechanism is structural -
``news_events.event_risk_for_symbol`` only reads classes listed under the symbol in
``symbol_event_classes``, and shadow classes are listed nowhere. These tests prove it:

* the shadow and weighted mappings are disjoint, and no shadow class is in any symbol list;
* on a fixture, ``event_risk`` for every rostered symbol (and every listed base) is
  byte-identical with the shadow mapping on and off, at times that straddle every event;
* the probe is not vacuous - shadow events are present, they fall inside the windows being
  sampled, and listing a shadow class for a symbol WOULD change the risk.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "macro"))

import econ_calendar_data as ecd  # noqa: E402
import econ_calendar_produce as ecp  # noqa: E402
from src.news import news_events  # noqa: E402

AS_OF = "2026-10-26"
CONFIG = yaml.safe_load((REPO / "config" / "economic_calendar.yaml").read_text())
# Names that already exist in symbol lists without a producer mapping.
RESERVED = {"china_pmi", "opec", "dxy"}


def _row(kind: str, ts: str, impact: str, score: float) -> dict:
    return {"kind": kind, "scheduled_for": ts[:10], "scheduled_at": ts, "impact": impact, "impact_score": score}


# One release per time slot, so every class's window is isolated from the others.
FIXTURE = [
    _row("fomc", "2026-10-28T18:30:00Z", "HIGH", 1.0),
    _row("core_pce_mom", "2026-10-29T12:30:00Z", "HIGH", 0.9),
    _row("cpi_yoy", "2026-11-12T13:30:00Z", "HIGH", 0.9),
    _row("nfp", "2026-11-06T13:30:00Z", "HIGH", 0.9),
    _row("gdp_annualized", "2026-10-29T14:30:00Z", "HIGH", 0.9),
    _row("eia_crude_stocks", "2026-10-28T14:30:00Z", "LOW", 0.2),
    _row("initial_jobless_claims", "2026-10-29T12:30:00Z", "MEDIUM", 0.5),
    _row("ppi_mom", "2026-11-13T13:30:00Z", "MEDIUM", 0.5),
    _row("ppi_yoy", "2026-11-13T13:30:00Z", "HIGH", 0.9),
    _row("retail_sales_mom", "2026-11-14T13:30:00Z", "MEDIUM", 0.5),
    _row("ism_manufacturing", "2026-11-02T15:00:00Z", "HIGH", 0.9),
    _row("jolts_job_openings", "2026-11-03T15:00:00Z", "MEDIUM", 0.5),
    _row("michigan_sentiment", "2026-11-06T15:00:00Z", "HIGH", 0.9),
    _row("fed_s_williams_speech", "2026-11-04T17:00:00Z", "MEDIUM", 0.5),
    _row("10_year_note_auction", "2026-11-12T17:00:00Z", "LOW", 0.2),
    _row("3_month_bill_auction", "2026-11-09T15:30:00Z", "LOW", 0.2),   # bills are NOT mapped
    _row("columbus_day", "2026-11-09T00:00:00Z", "NONE", 0.0),          # unmapped, must not appear
]


def _roster_symbols() -> set[str]:
    out: set[str] = set()
    for acct in (yaml.safe_load((REPO / "config" / "accounts.yaml").read_text()).get("accounts") or {}).values():
        out.update(acct.get("symbols") or [])
    for leg in (yaml.safe_load((REPO / "config" / "strategies.yaml").read_text()).get("strategies") or {}).values():
        out.update((leg or {}).get("symbols") or [])
    return out


def _build(monkeypatch, *, shadow: bool) -> list[dict]:
    if not shadow:
        monkeypatch.setattr(ecp, "shadow_class_for_kind", lambda kind: None)
    return ecp.build_news_config_events(FIXTURE, as_of=AS_OF)


def _load_with(monkeypatch, tmp_path, events: list[dict], symbol_classes: dict) -> None:
    cfg = tmp_path / "economic_calendar.yaml"
    cfg.write_text(yaml.safe_dump({
        "defaults": CONFIG.get("defaults") or {},
        "symbol_event_classes": symbol_classes,
        "events": events,
    }))
    monkeypatch.setattr(news_events, "_CONFIG_PATH", cfg)
    news_events.reload_calendar()


@pytest.fixture(autouse=True)
def _fresh():
    news_events.reload_calendar()
    yield
    news_events.reload_calendar()


def test_mappings_are_disjoint_and_unreserved():
    assert not set(ecd.SHADOW_KIND_TO_NEWS_CLASS) & set(ecd.KIND_TO_NEWS_CLASS)
    assert not ecd.SHADOW_NEWS_CLASSES & set(ecd.KIND_TO_NEWS_CLASS.values())
    assert not ecd.SHADOW_NEWS_CLASSES & RESERVED
    for kind in ecd.KIND_TO_NEWS_CLASS:
        assert ecd.shadow_class_for_kind(kind) is None, kind


def test_no_shadow_class_is_listed_for_any_symbol():
    """The weight-0 guarantee. Putting a class here is the Tier-3 weight change."""
    listed = {str(c).lower() for cs in (CONFIG.get("symbol_event_classes") or {}).values() for c in cs}
    leaked = ecd.SHADOW_NEWS_CLASSES & listed
    assert not leaked, f"shadow class(es) {sorted(leaked)} have a weight: remove from symbol_event_classes or promote via Tier-3"


def test_event_risk_byte_identical_before_and_after(monkeypatch, tmp_path):
    before = _build(monkeypatch, shadow=False)
    monkeypatch.undo()
    after = _build(monkeypatch, shadow=True)
    monkeypatch.undo()

    shadow_after = [e for e in after if e["class"] in ecd.SHADOW_NEWS_CLASSES]
    weighted_after = [e for e in after if e["class"] not in ecd.SHADOW_NEWS_CLASSES]
    # the weighted events are exactly what the producer emitted before this change
    assert weighted_after == before
    assert not [e for e in before if e["class"] in ecd.SHADOW_NEWS_CLASSES]
    # non-vacuous: new classes really are emitted, with the highest impact per release
    classes = {e["class"] for e in shadow_after}
    assert {"jobless_claims", "ppi", "retail_sales", "ism", "jolts", "umich", "fed_speak", "treasury_auction"} <= classes
    assert {e["impact"] for e in shadow_after if e["class"] == "ppi"} == {0.9}
    assert not [e for e in after if e["time"].startswith("2026-11-09")], "bills/holidays must not be mapped"

    symbol_classes = CONFIG["symbol_event_classes"]
    symbols = sorted(_roster_symbols() | set(symbol_classes))
    assert len(symbols) >= 7
    times = sorted({e["time"] for e in after})
    offsets = [-90, -61, -60, -30, -1, 0, 1, 5, 14, 15, 16]
    grid = [(sym, datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(minutes=off))
            for sym in symbols for t in times for off in offsets]

    def sweep(events):
        _load_with(monkeypatch, tmp_path, events, symbol_classes)
        return [news_events.event_risk_for_symbol(sym, now=now) for sym, now in grid]

    r_before, r_after = sweep(before), sweep(after)
    assert len(r_before) == len(grid) == len(symbols) * len(times) * len(offsets)
    assert r_before == r_after
    assert any(r[0] > 0 for r in r_before), "sweep never entered a weighted window: proof would be vacuous"


def test_probe_detects_a_weight_if_one_were_given(monkeypatch, tmp_path):
    """Negative control: the same comparison DOES differ once a shadow class is listed."""
    after = _build(monkeypatch, shadow=True)
    monkeypatch.undo()
    t = next(e["time"] for e in after if e["class"] == "ism")
    now = datetime.fromisoformat(t.replace("Z", "+00:00"))
    plain = {"MES": ["fomc", "cpi", "nfp", "pce", "gdp"]}
    _load_with(monkeypatch, tmp_path, after, plain)
    assert news_events.event_risk_for_symbol("MES", now=now)[0] == 0.0
    _load_with(monkeypatch, tmp_path, after, {"MES": plain["MES"] + ["ism"]})
    assert news_events.event_risk_for_symbol("MES", now=now)[0] == pytest.approx(0.9)


def test_per_class_floor_and_window(monkeypatch):
    ev = _build(monkeypatch, shadow=True)
    auctions = [e for e in ev if e["class"] == "treasury_auction"]
    assert auctions and all(e["impact"] == 0.2 for e in auctions)
    # outside the 45-day horizon -> dropped, same as weighted classes
    far = [_row("ism_services", "2027-03-03T15:00:00Z", "HIGH", 0.9)]
    assert ecp.build_news_config_events(far, as_of=AS_OF) == []
