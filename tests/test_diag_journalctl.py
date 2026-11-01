"""Pin the diag-relay journalctl helper's timestamp normalization +
rc=1 disambiguation. Closes #930.

Two bugs fixed:
  1. journalctl on Ubuntu 20.04 (v245) rejects `2026-05-11T15:40:00Z`
     and returns rc=1 with no matches. The helper now normalizes
     `T` → ` ` and `Z` → ` UTC` (journalctl-universal form) so any
     supported version accepts the timestamp.
  2. journalctl rc=1 with empty stderr means "valid query, zero
     matches" — NOT a real failure. The helper now reports
     `available: true` in that case so callers can distinguish a
     legitimate empty window from a real error.
"""
from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock, patch

from src.web.api.routers.diag import (
    _journalctl_tail,
    _normalize_journalctl_timestamp,
)


# -- timestamp normalization ----------------------------------------------


def test_normalize_iso_with_T_and_Z_to_space_and_UTC():
    assert (
        _normalize_journalctl_timestamp("2026-05-11T15:40:00Z")
        == "2026-05-11 15:40:00 UTC"
    )


def test_normalize_iso_with_T_and_explicit_zero_offset():
    assert (
        _normalize_journalctl_timestamp("2026-05-11T15:40:00+00:00")
        == "2026-05-11 15:40:00 UTC"
    )


def test_normalize_iso_with_T_and_explicit_zero_offset_no_colon():
    assert (
        _normalize_journalctl_timestamp("2026-05-11T15:40:00+0000")
        == "2026-05-11 15:40:00 UTC"
    )


def test_normalize_iso_with_T_naive_passes_through_minus_T():
    # No Z, no offset → keep naive (journalctl will treat as local)
    assert (
        _normalize_journalctl_timestamp("2026-05-11T15:40:00")
        == "2026-05-11 15:40:00"
    )


def test_normalize_space_separated_passes_through_unchanged():
    # Already journalctl-native; no-op
    assert (
        _normalize_journalctl_timestamp("2026-05-11 15:40:00")
        == "2026-05-11 15:40:00"
    )


def test_normalize_non_utc_offset_preserves_offset():
    # Non-UTC offset stays in ISO form (journalctl 252+ accepts it;
    # older journalctl would error and the rc=1+stderr path surfaces it)
    assert (
        _normalize_journalctl_timestamp("2026-05-11T15:40:00-05:00")
        == "2026-05-11 15:40:00-05:00"
    )


# -- rc=1 disambiguation --------------------------------------------------


def _mk_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


class _Out:
    def __init__(self, lines):
        self._it = iter(lines)

    def __iter__(self):
        return self._it

    def close(self):
        pass


class _FakePopen:
    """Stands in for subprocess.Popen in WINDOW mode (stdout is streamed)."""
    last_cmd: ClassVar[list[str]] = []

    def __init__(self, cmd, stdout=None, stderr=None, **kw):
        type(self).last_cmd = cmd
        self.stdout = _Out(type(self).out_lines)
        self.returncode = type(self).rc
        if type(self).err and stderr is not None:
            stderr.write(type(self).err)

    out_lines: ClassVar[list[str]] = []
    rc = 0
    err = ""

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self):
        return self.returncode


def _popen(lines=(), rc=0, err=""):
    cls = type("P", (_FakePopen,), {"out_lines": [l + "\n" for l in lines], "rc": rc, "err": err})
    return patch("src.web.api.routers.diag.subprocess.Popen", cls), cls


def test_rc0_with_lines_is_available_with_lines():
    with patch(
        "src.web.api.routers.diag.subprocess.run",
        return_value=_mk_proc(0, "line1\nline2\n"),
    ):
        out = _journalctl_tail("ict-web-api.service", lines=10)
    assert out["available"] is True
    assert out["returncode"] == 0
    assert out["lines"] == ["line1", "line2"]
    assert "stderr" not in out


def test_rc1_with_empty_stderr_is_available_empty_lines():
    """Legit zero-match window: journalctl exits 1, no stderr → still 'available'."""
    ctx, _ = _popen([], rc=1)
    with ctx:
        out = _journalctl_tail(
            "ict-web-api.service",
            lines=10,
            since="2026-05-11T15:40:00Z",
            until="2026-05-11T16:00:00Z",
        )
    # Before this fix, available was False; now it must be True.
    assert out["available"] is True
    assert out["returncode"] == 1
    assert out["lines"] == []
    assert "stderr" not in out


def test_rc1_with_stderr_is_real_failure():
    """Genuine journalctl error: stderr has content → 'available': False."""
    ctx, _ = _popen([], rc=1, err="Failed to parse timestamp: foo\n")
    with ctx:
        out = _journalctl_tail(
            "ict-web-api.service",
            lines=10,
            since="garbage",
        )
    assert out["available"] is False
    assert out["returncode"] == 1
    assert "Failed to parse timestamp" in out["stderr"]


def test_journalctl_call_uses_normalized_timestamps():
    """The Popen argv must carry the normalized form, not the raw input."""
    ctx, cls = _popen(["ok"])
    with ctx:
        _journalctl_tail(
            "ict-web-api.service",
            lines=10,
            since="2026-05-11T15:40:00Z",
            until="2026-05-11T16:00:00Z",
        )
    cmd = cls.last_cmd
    assert cmd[cmd.index("--since") + 1] == "2026-05-11 15:40:00 UTC"
    assert cmd[cmd.index("--until") + 1] == "2026-05-11 16:00:00 UTC"
    assert "-n" not in cmd  # window mode streams; the cap is applied (and reported) by us


# -- DIAG-LOG-DEPTH: the cap must be visible --------------------------------


def test_tail_mode_flags_truncation_via_extra_line():
    with patch("src.web.api.routers.diag.subprocess.run",
               return_value=_mk_proc(0, "a\nb\nc\n")) as run:
        out = _journalctl_tail("ict-web-api.service", lines=2)
    assert "-n" in run.call_args[0][0] and "3" in run.call_args[0][0]  # lines+1
    assert out["lines"] == ["b", "c"] and out["truncated"] is True
    assert out["lines_dropped"] is None  # unknown in tail mode: None, never 0


def test_tail_mode_not_truncated_when_fits():
    with patch("src.web.api.routers.diag.subprocess.run",
               return_value=_mk_proc(0, "a\nb\n")):
        out = _journalctl_tail("ict-web-api.service", lines=5)
    assert out["truncated"] is False and out["lines_dropped"] == 0


def test_window_grep_applies_before_cap_and_reports_counts():
    rows = [f"x{i} NOISE" for i in range(50)] + [f"hit{i} order_monitor" for i in range(7)]
    ctx, _ = _popen(rows)
    with ctx:
        out = _journalctl_tail("ict-web-api.service", lines=3,
                               since="2026-05-11T15:40:00Z", grep=["order_monitor"])
    assert out["lines_scanned"] == 57 and out["lines_matched"] == 7
    assert out["lines_returned"] == 3 and out["lines_dropped"] == 4
    assert out["lines"][-1] == "hit6 order_monitor"  # newest kept
    assert out["truncated"] is True and out["read_state"] == "complete"


def test_window_zero_matches_is_distinguishable_from_not_read():
    ctx, _ = _popen(["a", "b", "c"])
    with ctx:
        out = _journalctl_tail("ict-web-api.service", lines=5, grep=["zzz"])
    assert out["lines"] == [] and out["lines_scanned"] == 3
    assert out["lines_matched"] == 0 and out["truncated"] is False


def test_window_scan_cap_marks_truncated_lower_bound():
    from src.web.api.routers import diag
    ctx, _ = _popen(["l"] * 20)
    with ctx, patch.object(diag, "_LOG_SCAN_MAX_LINES", 10):
        out = _journalctl_tail("ict-web-api.service", lines=100, since="2026-05-11 00:00:00")
    assert out["read_state"] == "scan_cap_hit" and out["truncated"] is True
    assert out["available"] is True


def test_parse_grep_validation():
    import pytest
    from fastapi import HTTPException

    from src.web.api.routers.diag import _parse_grep
    assert _parse_grep(None) is None
    assert _parse_grep("Order_Monitor|FILL") == ["order_monitor", "fill"]
    for bad in ("", "|", "a;b", "$(x)", "a" * 201, "|".join(f"x{i}" for i in range(11))):
        with pytest.raises(HTTPException):
            _parse_grep(bad)
