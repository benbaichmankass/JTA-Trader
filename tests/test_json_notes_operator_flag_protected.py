"""The operator-close flag must survive notes truncation.

Regression for the live incident of 2026-08-30: six rows were back-marked in
one batch; trades 5238 and 5239 came back with `exit_reason` set (a COLUMN, so
it survived) and BOTH notes keys gone. Their surviving key set was exactly
`_DEFAULT_PROTECTED` + `_truncated` — the `_shrink_dict` minimal envelope.

Third instance of the class `json_notes.py`'s own comment describes: a
provenance sentinel added later, with nobody extending the protected set.

⚠️ EVERY test here carries an in-test CANARY — an UNPROTECTED key of the same
shape that must be dropped in the SAME call. Without it these tests are
vacuous: `_shrink_dict` trims long *strings* first and only DROPS keys once it
falls back to the minimal envelope, so a boolean survives a mild trim whether
it is protected or not. The first draft of this file asserted survival without
proving anything was dropped, and would have passed against the unfixed code.
"""
import json

import pytest

from src.utils.json_notes import _DEFAULT_PROTECTED, dump_capped

CANARY = "canary_unprotected_flag"


def _blob():
    """The live 5238 shape, plus a canary."""
    return {
        "trade_id": "aebea583-5ec7-4e83-93b3-15efad3f7825",
        "closed_at": "2026-08-30T09:33:25.721080+00:00",
        "closed_by": "monitor_reconciler",
        "closed_reason": "reconciler — Bybit reports order filled and position flat",
        "exit_price_source": "exchange_fill",
        "exit_reason_source": "unresolved",
        "signal_logic": "x" * 4000,
        "closed_by_operator": True,
        "pre_mark_exit_reason": "reconciler_filled",
        "operator_close_reason": "flattened by the operator " * 40,
        CANARY: True,
    }


def test_the_operator_flag_and_prior_label_are_protected():
    assert "closed_by_operator" in _DEFAULT_PROTECTED
    assert "pre_mark_exit_reason" in _DEFAULT_PROTECTED


def test_the_flag_survives_the_minimal_envelope_that_dropped_it_live():
    out = json.loads(dump_capped(_blob(), 400))
    # The canary proves the DROP path ran — not merely a string trim.
    assert out.get("_truncated") is True
    assert CANARY not in out, "no key was dropped — this test proves nothing"
    # The two that matter survived that same drop.
    assert out.get("closed_by_operator") is True
    assert out.get("pre_mark_exit_reason") == "reconciler_filled"


def test_the_long_free_text_reason_is_still_shed_first():
    """The FLAG is what a consumer branches on; the prose is not. Protecting the
    reason too would crowd out the keys that matter."""
    out = json.loads(dump_capped(_blob(), 400))
    assert out.get("closed_by_operator") is True
    assert len(out.get("operator_close_reason", "")) < 1000


@pytest.mark.parametrize("budget", [240, 300, 320])
def test_below_the_protected_sets_own_size_the_close_stamps_survive(budget):
    """The limit this used to assert is gone (DUMP-CAPPED-DROPS-PROTECTED, 2026-11-20).

    It read "NOTHING_survives": once the protected set overflowed, `dump_capped`
    emitted the bare `{"_truncated": true}` marker (live trade 7131 is stored that
    way). Now protected prose is shortened and protected keys are shed one at a
    time, the close stamps last, so under these budgets closed_at and the
    operator flag still survive, whole and unaltered.
    """
    raw = dump_capped(_blob(), budget)
    out = json.loads(raw)
    assert len(raw) <= budget
    assert out.get("_truncated") is True
    assert out.get("closed_at") == "2026-08-30T09:33:25.721080+00:00"
    assert out.get("closed_by_operator") is True