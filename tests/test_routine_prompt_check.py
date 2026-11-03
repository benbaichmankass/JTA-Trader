import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location(
    "rpc", pathlib.Path(__file__).resolve().parents[1] / "scripts/ops/routine_prompt_check.py")
rpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpc)

SID = "session_01AFoLuJwBvR58WBtD4qc5Gp"


def trig(i, prompt, enabled=True, cron="0 1 * * *", once=None):
    t = {"id": i, "name": i, "enabled": enabled, "cron_expression": cron,
         "derived_state": {"prompt": prompt}}
    if once:
        t["run_once_at"] = once
    return t


def run(*ts):
    return rpc.check({"data": list(ts)})


def test_flags_session_id_positive_control():
    r = run(trig("a", f"report to {SID}"))
    assert r["n_flagged"] == 1 and r["flagged"][0]["session_ids"] == [SID]


def test_flags_old_repo_slug():
    r = run(trig("a", "source_url https://github.com/benbaichmankass/ict-trading-bot"),
            trig("b", "repo benbaichmankass/Metis-Insights"))
    assert r["n_flagged"] == 2


def test_clean_and_historical_mention_not_flagged():
    r = run(trig("a", "source_url https://github.com/benbaichmankass/JTA-Trader (renamed from Metis-Insights 2026-10-28)"))
    assert r["n_flagged"] == 0 and r["n_checked"] == 1


def test_runtime_identifiers_not_flagged():
    r = run(trig("a", "cd /home/ubuntu/ict-trading-bot; /opt/ict-trading-bot; https://ict-bot.duckdns.org/api"))
    assert r["n_flagged"] == 0


def test_disabled_skipped_and_kinds():
    r = run(trig("a", SID, enabled=False),
            trig("b", SID, cron="", once="2026-11-02T13:25:00Z"),
            trig("c", SID, cron=""))
    kinds = {f["id"]: f["kind"] for f in r["flagged"]}
    assert r["n_checked"] == 2 and kinds == {"b": "one_shot_pending", "c": "one_shot_fired"}


def test_short_ids_and_title_lookup_not_flagged():
    r = run(trig("a", "the non-archived 'Manager Session YYYY-MM-DD<letter>'; session_abc"))
    assert r["n_flagged"] == 0
