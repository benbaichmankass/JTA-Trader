"""FUT-CME-INTRADAY-HIST roll fix (2026-11-13): a far contract that out-trades the near ones on one session must not
lock the monotonic roll floor (run 43361991285 kept MNQ only from 2025-12-10, 100 d before the 2026-03-20 expiry)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))
import tradeify_futures_fit as tff


def _bar(ts: str, contract: str, volume: float) -> dict:
    return {"ts": ts, "contract": contract, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": volume}


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "data.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_far_contract_gap_day_does_not_lock_the_floor(tmp_path):
    rows = []
    # 2024-11-04 .. 2024-11-08: the Dec-2024 front trades; a far Mar-2026 contract is on file too, thin.
    for day in ("04", "05", "07", "08"):
        rows += [_bar(f"2024-11-{day}T15:00:00Z", "20241220", 1000), _bar(f"2024-11-{day}T15:00:00Z", "20260320", 5)]
    # 2024-11-06: a gap in the front's served bars; only the far contract has a bar that session.
    rows.append(_bar("2024-11-06T15:00:00Z", "20260320", 5))
    bars, prov = tff.load_ibkr_percontract(_write(tmp_path, rows), front_days=100)
    kept = sorted({str(d) for d in bars["d"]})
    assert kept == ["2024-11-04", "2024-11-05", "2024-11-07", "2024-11-08"]
    assert prov["first_session_kept"] == "2024-11-04"
    assert prov["sessions_dropped_not_front"] == 1          # the gap day is counted, not silently skipped
    assert [r["contract"] for r in prov["roll_calendar"]] == ["20241220"]


def test_rolls_forward_in_the_roll_week_and_never_back(tmp_path):
    rows = [
        _bar("2024-12-10T15:00:00Z", "20241220", 1000), _bar("2024-12-10T15:00:00Z", "20250321", 100),
        _bar("2024-12-13T15:00:00Z", "20241220", 300), _bar("2024-12-13T15:00:00Z", "20250321", 900),
        _bar("2024-12-16T15:00:00Z", "20241220", 950), _bar("2024-12-16T15:00:00Z", "20250321", 900),
    ]
    _, prov = tff.load_ibkr_percontract(_write(tmp_path, rows), front_days=100)
    assert [r["contract"] for r in prov["roll_calendar"]] == ["20241220", "20250321"]
    assert prov["roll_calendar"][1]["from_session"] == "2024-12-13"


def test_back_month_only_sessions_are_dropped_and_counted(tmp_path):
    rows = [_bar("2023-09-22T15:00:00Z", "20241220", 50), _bar("2024-10-01T15:00:00Z", "20241220", 1000)]
    bars, prov = tff.load_ibkr_percontract(_write(tmp_path, rows), front_days=100)
    assert sorted({str(d) for d in bars["d"]}) == ["2024-10-01"]
    assert prov["sessions_dropped_not_front"] == 1
