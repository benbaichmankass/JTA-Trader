"""LEDGER-REFRESH: freshness grader, live block, daily buckets, delta join."""
import importlib.util
import pathlib
from datetime import datetime, timezone

from src.runtime import broker_truth as bt
from src.runtime import bybit_wallet_truth as wt

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "ops" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fresh = _load("broker_truth_freshness")
delta = _load("journal_vs_wallet_delta")
NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)


def test_stale_without_gap_is_a_finding():
    g = fresh.grade({"accounts": [{"account_id": "a", "stale": True, "as_of_age_days": 89}]})
    assert g["rc"] == 1 and g["records"][0]["verdict"] == "stale"


def test_declared_gap_with_measured_live_is_not_a_finding():
    rec = {"account_id": "a", "stale": True, "declared_gaps": [{"sub_account": "SUB", "reason": "csv only"}],
           "live": {"state": "measured_api"}}
    assert fresh.grade({"accounts": [rec]})["rc"] == 0
    rec["live"] = {"state": "silent"}
    assert fresh.grade({"accounts": [rec]})["rc"] == 1


def test_unreadable_is_never_clean():
    assert fresh.grade({"error": "x"})["rc"] == 3
    assert fresh.grade(None)["rc"] == 3
    assert fresh.grade({"accounts": [{"account_id": "a", "stale": None}]})["rc"] == 3
    assert fresh.grade({"accounts": []})["rc"] == 1


def _row(i, change, hours_ago, **kw):
    return {"id": str(i), "type": "TRADE", "currency": "USDT", "change": change, "fee": 1.0,
            "funding": 0.0, "transactionTime": MS - hours_ago * 3_600_000, **kw}


def test_live_block_states():
    ok = bt.live_wallet_block("a", since_ms=MS - 86_400_000 * 5, now=NOW, lister=lambda *a, **k: [_row(1, -2.0, 3)])
    assert ok["state"] == "measured_api" and ok["realized_usd_since"] == -2.0 and ok["latest_row_age_hours"] == 3.0
    silent = bt.live_wallet_block("a", since_ms=MS - 86_400_000 * 20, now=NOW, lister=lambda *a, **k: [_row(1, 1.0, 100)])
    assert silent["state"] == "silent"
    none = bt.live_wallet_block("a", since_ms=MS - 1000, now=NOW, lister=lambda *a, **k: [])
    assert none["state"] == "not_pulled" and none["realized_usd_since"] is None

    def boom(*a, **k):
        raise RuntimeError("db")
    bad = bt.live_wallet_block("a", since_ms=None, now=NOW, lister=boom)
    assert bad["state"] == "unreadable" and bad["realized_usd_since"] is None


def test_daily_buckets_sum_to_headline_and_none_in_none_out():
    rows = [_row(1, -3.0, 2), _row(2, 5.0, 30), {**_row(3, 100.0, 2), "type": "TRANSFER_IN"}]
    d = wt.daily_buckets(rows)
    assert round(sum(b["wallet_usd"] for b in d), 6) == wt.compute_wallet_truth("a", rows).realized_usd == 2.0
    assert wt.daily_buckets(None) is None and wt.daily_buckets([]) == []


def test_delta_join_and_could_not_look():
    wallet = {"accounts": [{"account_id": "a", "daily": [
        {"date": "2026-10-09", "wallet_usd": -10.0, "fees_usd": 2.0, "funding_usd": 0.0}]}]}
    closed = [{"closedAt": "2026-10-09T01:00:00+00:00", "realizedPnl": -7.0},
              {"closedAt": "2026-10-09T02:00:00+00:00", "realizedPnl": None}]
    r = delta.compute("a", wallet, closed)
    assert r["days"][0]["delta"] == -3.0 and r["days"][0]["null_pnl_rows"] == 1
    assert delta.compute("a", {"accounts": [{"account_id": "a"}]}, closed)["state"] == "could_not_look"


def test_ledger_declares_bybit2_gap():
    s = bt.summarize_broker_truth(now=NOW)
    rec = next(a for a in s["accounts"] if a["account_id"] == "bybit_2")
    assert rec["declared_gaps"] and rec["declared_gaps"][0]["sub_account"] == "SUB"


# --- LEDGER-REFRESH 2026-11-12: hand record + live API folded into `current` ---

def test_live_since_is_day_after_inclusive_window_end():
    ms = bt.live_since_ms({"window_end": "2026-07-13"})
    assert ms == int(datetime(2026, 7, 14, tzinfo=timezone.utc).timestamp() * 1000)
    assert bt.live_since_ms({}) is None and bt.live_since_ms({"window_end": "junk"}) is None


def test_current_sums_only_when_every_gap_closed():
    live = {"state": "measured_api", "realized_usd_since": -101.69, "latest_row_at": "2026-10-10T09:00:00+00:00"}
    rec = {"realized_usd": -262.52, "window_end": "2026-07-13",
           "declared_gaps": [{"sub_account": "SUB", "closed": True}]}
    cur = bt.current_wallet_truth(rec, live, now=NOW)
    assert cur["state"] == "measured" and cur["realized_usd"] == -364.21
    assert cur["as_of_age_days"] == 0 and cur["stale"] is False and cur["closed_components"] == ["SUB"]
    # an OPEN gap: no figure, never the hand number passed off as current
    rec_open = {**rec, "declared_gaps": [{"sub_account": "SUB"}]}
    o = bt.current_wallet_truth(rec_open, live, now=NOW)
    assert o["state"] == "incomplete" and o["realized_usd"] is None and "SUB" in o["reason"]
    # live not measured: no figure
    for st in ("unreadable", "not_pulled", "silent"):
        n = bt.current_wallet_truth(rec, {"state": st, "realized_usd_since": None}, now=NOW)
        assert n["state"] == "incomplete" and n["realized_usd"] is None
    assert bt.current_wallet_truth({"realized_usd": None}, live, now=NOW)["state"] == "incomplete"


def test_journal_trust_uses_current_when_measured(tmp_path):
    import json
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"accounts": [{"account_id": "a", "realized_usd": -10.0, "as_of": "2026-07-13",
                                           "window_end": "2026-07-13", "source": "x",
                                           "declared_gaps": [{"sub_account": "S", "closed": True}]}]}))
    m = bt.journal_trust_map(p, now=NOW, lister=lambda *a, **k: [_row(1, -2.0, 3)])
    assert m["read_state"] == "read"
    assert bt.journal_trust_map(tmp_path / "missing.json", now=NOW)["read_state"] == "absent"
    (tmp_path / "bad.json").write_text("{not json")
    assert bt.journal_trust_map(tmp_path / "bad.json", now=NOW)["read_state"] == "unreadable"
    v = bt.journal_trust_for("a", m)
    assert v["state"] == bt.TRUST_KNOWN_DIVERGENT and v["realized_usd"] == -12.0 and v["stale"] is False
    # store unreadable -> falls back to the hand record, still flagged stale
    def boom(*a, **k):
        raise RuntimeError("db")
    v2 = bt.journal_trust_for("a", bt.journal_trust_map(p, now=NOW, lister=boom))
    assert v2["realized_usd"] == -10.0 and v2["stale"] is True
    assert v2["figure"] == "hand_record" and v2["current_state"] == "incomplete" and v2["current_reason"]
    assert v["figure"] == "current" and v["current_state"] == "measured"


def test_grader_fresh_when_current_measured():
    rec = {"account_id": "a", "stale": True, "as_of_age_days": 122,
           "current": {"state": "measured", "stale": False, "as_of": "2026-11-12T08:00:00+00:00", "as_of_age_days": 0}}
    g = fresh.grade({"accounts": [rec]})
    assert g["rc"] == 0 and g["records"][0]["verdict"] == "fresh"


def test_committed_ledger_sub_gap_is_closed_with_evidence():
    rec = next(a for a in bt.summarize_broker_truth(now=NOW)["accounts"] if a["account_id"] == "bybit_2")
    g = rec["declared_gaps"][0]
    assert g["closed"] is True and "2026-06-29" in g["closed_evidence"]
