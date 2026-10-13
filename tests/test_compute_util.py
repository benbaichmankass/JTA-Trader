"""compute_util: ledger merge, Oracle idle verdict, read-state honesty, spare figure."""
import datetime as dt
import json

from scripts.ops import compute_util as cu

TODAY = "2026-10-14"


def _days(n, cpu, mem, net=0.1):
    base = dt.date.fromisoformat(TODAY)
    return {(base - dt.timedelta(days=i)).isoformat(): {"cpu_p95": cpu, "cpu_max": cpu + 5, "mem_p95": mem, "mem_max": mem + 1,
                                                        "net_in_p95": net * 1e6, "net_out_p95": net * 1e6}
            for i in range(1, n + 1)}


def _metrics(**per_host):
    inst = {"ocpus": 1.0, "memory_gb": 6.0}
    return {h: {"instance": inst, "days": d, "errors": {}} for h, d in per_host.items()}


def test_idle_host_is_at_risk_and_busy_is_ok():
    m = _metrics(live=_days(7, 40, 12), trainer=_days(7, 8, 10), gateway=_days(7, 25, 15))
    rows = cu.build_rows(TODAY, m, {})
    v = {h: cu.evaluate_host(rows, h, TODAY) for h in cu.HOSTS}
    assert v["live"]["status"] == "ok"
    assert v["trainer"]["status"] == "at_risk" and v["trainer"]["net_unmeasured"]
    assert v["gateway"]["status"] == "watch"   # 25% < 30% watch line, >= 20% idle line


def test_one_busy_day_in_window_prevents_at_risk():
    d = _days(7, 8, 10)
    d[sorted(d)[3]]["cpu_p95"] = 55.0
    rows = cu.build_rows(TODAY, _metrics(trainer=d), {})
    assert cu.evaluate_host(rows, "trainer", TODAY)["status"] == "ok"


def test_unreadable_host_is_unknown_never_zero_or_ok():
    rows = cu.build_rows(TODAY, _metrics(live=_days(7, 40, 12)), {})   # trainer + gateway absent
    g = [r for r in rows if r["host"] == "gateway"]
    assert g and all(r["cpu_p95"] is None and r["read_state"]["cpu"] == "could_not_look" for r in g)
    assert cu.evaluate_host(rows, "gateway", TODAY)["status"] == "unknown"
    sp = cu.spare_capacity(rows, TODAY, "t")["hosts"]["gateway"]
    assert sp["read_state"] == "could_not_look" and sp["spare_ocpus"] is None and sp["spare_memory_gb"] is None


def test_partial_today_excluded_and_few_days_insufficient():
    rows = cu.build_rows(TODAY, _metrics(trainer={**_days(2, 8, 10), TODAY: {"cpu_p95": 1.0, "mem_p95": 1.0}}), {})
    v = cu.evaluate_host(rows, "trainer", TODAY)
    assert v["status"] == "insufficient" and v["days_in_window"] == 2


def test_merge_keeps_measured_disk_when_new_run_lacks_ssh():
    first = cu.build_rows(TODAY, _metrics(live=_days(1, 30, 10)), {"live": {"disk_pct": 71.0, "load1": 0.5, "mem_used_pct": 11.0}})
    second = cu.build_rows(TODAY, _metrics(live=_days(1, 30, 10)), {})
    out = cu.merge_ledger(first, second)
    today = next(r for r in out if r["host"] == "live" and r["date"] == TODAY)
    assert today["disk_pct"] == 71.0 and today["read_state"]["disk"] == "measured"
    assert len([r for r in out if r["host"] == "live" and r["date"] == TODAY]) == 1


def test_spare_is_conservative_and_reader_degrades(tmp_path):
    rows = cu.build_rows(TODAY, _metrics(trainer=_days(7, 50, 25)), {})
    sp = cu.spare_capacity(rows, TODAY, "t")
    t = sp["hosts"]["trainer"]
    assert t["spare_ocpus"] == 0.5 and t["spare_memory_gb"] == 4.5
    p = tmp_path / "s.json"
    p.write_text(json.dumps(sp))
    assert cu.get_spare("trainer", p)["spare_ocpus"] == 0.5
    assert cu.get_spare("trainer", tmp_path / "missing.json")["read_state"] == "could_not_look"


def test_alert_only_on_transition(tmp_path, monkeypatch):
    monkeypatch.setattr(cu, "STATE", tmp_path / "st.json")
    rows = cu.build_rows(TODAY, _metrics(trainer=_days(7, 8, 10)), {})
    r1 = cu.cmd_evaluate(rows, TODAY, write=True)
    assert r1["alert_hosts"] == ["trainer"]
    r2 = cu.cmd_evaluate(rows, TODAY, write=True)
    assert r2["alert_hosts"] == []


def test_network_is_never_derived_to_a_percentage():
    rows = cu.build_rows(TODAY, _metrics(trainer=_days(3, 8, 10, net=500.0)), {})
    r = next(x for x in rows if x["host"] == "trainer" and x["date"] < TODAY)
    assert r["net_p95_pct_of_shape"] is None and r["read_state"]["net"] == "could_not_look"
    assert r["net_in_p95_raw"] is not None      # raw kept for a later unit check


def test_merge_drops_legacy_network_percentage():
    legacy = cu.build_rows(TODAY, _metrics(trainer=_days(1, 8, 10)), {})
    for r in legacy:
        r["net_p95_pct_of_shape"] = 571.0      # first-run bogus value
        r["net_p95_bps"] = 1.0
    out = cu.merge_ledger(legacy, cu.build_rows(TODAY, _metrics(trainer=_days(1, 8, 10)), {}))
    assert all(r["net_p95_pct_of_shape"] is None and "net_p95_bps" not in r and r["read_state"]["net"] == "could_not_look"
               for r in out)
