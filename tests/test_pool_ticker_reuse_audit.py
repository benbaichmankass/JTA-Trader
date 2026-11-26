"""Self-test of the ml_entry_eq pool ticker-reuse audit (RQ-20261126-7c11-01): run splitting, the two-security rule, verdict mapping."""
from scripts.research import pool_ticker_reuse_audit as A


def test_self_test_passes():
    A.self_test()


def test_runs_split_on_a_30_day_gap():
    import pandas as pd
    ts = pd.Series(pd.to_datetime(["2021-01-04", "2021-01-05", "2021-03-01"], utc=True))
    r = A.runs(ts)
    assert [x["bars"] for x in r] == [2, 1]
