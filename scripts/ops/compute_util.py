"""Daily CPU / memory / network / disk utilisation for the three OCI VMs, a
rolling committed ledger, an Oracle idle-reclaim check, the tenancy limits read,
and a per-VM spare-capacity figure for the research router.

Rows: COMPUTE-UTIL-TELEMETRY, COMPUTE-OCI-QUOTA-CHECK (roadmap L-OPS).
Motivation: docs/plans/OCI-STATE-CHECK-2026-10-13.md — the gateway had never been
measured, and "is any VM trending toward Oracle's idle criteria" was unanswerable.

Source of truth: the OCI Monitoring API (namespace ``oci_computeagent``) — the
same metrics Oracle's idle rule is defined over — read with the repo's existing
OCI credentials. It covers all three VMs, including the gateway (no public IP),
with no SSH. Disk is NOT an oci_computeagent metric, so it comes from a point
sample over SSH (done by the workflow, passed in with ``--ssh-samples``).

Oracle's rule (docs.oracle.com Always Free Resources, fetched 2026-10-13): a VM
is idle when, during a 7-day period, ALL hold: CPU 95th percentile < 20 %,
network utilisation < 20 %, and (A1 shapes only) memory utilisation < 20 %.

READ-STATE, never collapsed: every metric on every row is ``measured`` or
``could_not_look`` and its value is ``null`` in the latter case. A host we could
not read is NEVER 0, never "ok", and never silently absent from the ledger.

Daily p95 -> 7-day p95: the pooled 95th percentile over seven equal days is
bounded above by the largest per-day 95th percentile (if no day has more than 5 %
of its samples above x, neither does the pool). So ``max(daily p95)`` is a
conservative upper bound on Oracle's 7-day p95 — it can over-estimate
utilisation (under-warn of idleness) but never under-estimate it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

LEDGER = Path("comms/cloud/compute_util_ledger.jsonl")
SPARE = Path("comms/cloud/compute_spare.json")
STATE = Path("comms/cloud/compute_reclaim_state.json")
LIMITS = Path("comms/cloud/oci_limits.json")

# alias -> OCI display_name (comms/cloud/expected_topology.json)
HOSTS = {"live": "ict-bot-arm", "trainer": "ict-trainer-vm", "gateway": "ict-ib-gateway"}
METRICS = ("cpu", "mem", "net", "disk")

IDLE_PCT = 20.0          # Oracle: each of CPU p95 / network / memory below 20 %
WATCH_PCT = 30.0         # "trending toward": every condition within 1.5x of idle
WINDOW_DAYS = 7
MIN_DAYS = 3             # fewer measured complete days => verdict ``insufficient``
# NETWORK IS NOT GATED. The first live run (2026-10-13) converted NetworksBytesIn/Out
# p95 to a % of an assumed 1 Gbps/OCPU and got 570-1,240 % on every host, so the
# unit/aggregation of the raw value is not what was assumed (and Oracle's page does
# not define "network utilisation"). The raw p95 is kept in the ledger for a later
# unit check; the % is ``null`` / ``could_not_look`` and the idle verdict says so.

NS = "oci_computeagent"
LIMIT_NAMES = ("standard-a1-core-count", "standard-a1-memory-count")


# ---------------------------------------------------------------- OCI reads
def _cfg() -> dict[str, str]:
    need = ("OCI_CLI_USER", "OCI_CLI_KEY_CONTENT", "OCI_CLI_FINGERPRINT",
            "OCI_CLI_TENANCY", "OCI_CLI_REGION")
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing OCI env vars: {', '.join(missing)}")
    return {"user": os.environ["OCI_CLI_USER"], "key_content": os.environ["OCI_CLI_KEY_CONTENT"],
            "fingerprint": os.environ["OCI_CLI_FINGERPRINT"], "tenancy": os.environ["OCI_CLI_TENANCY"],
            "region": os.environ["OCI_CLI_REGION"]}


def _series(mon: Any, compartment: str, ocid: str, metric: str, stat: str,
            start: dt.datetime, end: dt.datetime) -> dict[str, float]:
    """{YYYY-MM-DD: value} of one daily-bucketed statistic; raises on API error."""
    import oci
    q = f'{metric}[1d]{{resourceId = "{ocid}"}}.{stat}'
    resp = mon.summarize_metrics_data(
        compartment_id=compartment,
        summarize_metrics_data_details=oci.monitoring.models.SummarizeMetricsDataDetails(
            namespace=NS, query=q, start_time=start, end_time=end),
    )
    out: dict[str, float] = {}
    for item in resp.data:
        for p in item.aggregated_datapoints:
            out[p.timestamp.astimezone(dt.timezone.utc).strftime("%Y-%m-%d")] = float(p.value)
    return out


def fetch_metrics(compartment: str, instances: list[dict]) -> dict[str, dict]:
    """Per host alias: {"shape":..., "days": {date: {metric: value|None}}, "errors": {metric: msg}}."""
    import oci
    mon = oci.monitoring.MonitoringClient(_cfg())
    end = dt.datetime.now(dt.timezone.utc)
    start = (end - dt.timedelta(days=WINDOW_DAYS + 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    by_name = {i["display_name"]: i for i in instances}
    result: dict[str, dict] = {}
    for alias, name in HOSTS.items():
        inst = by_name.get(name)
        if inst is None or inst.get("lifecycle_state") in ("TERMINATED", "TERMINATING"):
            result[alias] = {"instance": None, "days": {}, "errors": {"all": "instance not found live"}}
            continue
        days: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for key, metric, stat in (
            ("cpu_p95", "CpuUtilization", "percentile(0.95)"), ("cpu_max", "CpuUtilization", "max()"),
            ("mem_p95", "MemoryUtilization", "percentile(0.95)"), ("mem_max", "MemoryUtilization", "max()"),
            ("net_in_p95", "NetworksBytesIn", "percentile(0.95)"), ("net_out_p95", "NetworksBytesOut", "percentile(0.95)"),
        ):
            try:
                for d, v in _series(mon, compartment, inst["ocid"], metric, stat, start, end).items():
                    days.setdefault(d, {})[key] = v
            except Exception as exc:  # noqa: BLE001 - recorded as could_not_look, not swallowed
                errors[key] = f"{type(exc).__name__}: {str(exc)[:160]}"
        result[alias] = {"instance": inst, "days": days, "errors": errors}
    return result


def fetch_limits(tenancy: str, compartment: str, instances: list[dict]) -> dict:
    """Tenancy A1 limits via the Limits API; each limit carries its own read-state."""
    import oci
    lc = oci.limits.LimitsClient(_cfg())
    ads = sorted({i["availability_domain"] for i in instances if i.get("availability_domain")})
    out: dict[str, Any] = {"read_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           "source": "OCI Limits API (list_limit_values + get_resource_availability, service=compute)",
                           "limits": {}}
    for name in LIMIT_NAMES:
        entry: dict[str, Any] = {"read_state": "could_not_look", "per_ad": []}
        try:
            vals = lc.list_limit_values(compartment_id=tenancy, service_name="compute", name=name).data
            entry["limit_values"] = [{"scope": str(v.scope_type), "ad": v.availability_domain, "value": v.value} for v in vals]
            entry["read_state"] = "measured"
            for ad in ads:
                try:
                    a = lc.get_resource_availability(service_name="compute", limit_name=name,
                                                     compartment_id=compartment, availability_domain=ad).data
                    entry["per_ad"].append({"ad": ad, "used": a.used, "available": a.available,
                                            "fractional_used": getattr(a, "fractional_usage", None)})
                except Exception as exc:  # noqa: BLE001
                    entry["per_ad"].append({"ad": ad, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        out["limits"][name] = entry
    return out



def fetch_hosts(compartment: str, instances: list[dict]) -> dict[str, dict]:
    """{alias: {"public_ip", "private_ip"}} from the OCI API, so no address is ever
    committed to this public repo. Best-effort: a host that cannot be resolved is
    simply absent (its disk then reads ``could_not_look``)."""
    import oci
    cfg = _cfg()
    compute, net = oci.core.ComputeClient(cfg), oci.core.VirtualNetworkClient(cfg)
    by_name = {i["display_name"]: i for i in instances}
    out: dict[str, dict] = {}
    for alias, name in HOSTS.items():
        inst = by_name.get(name)
        if not inst or inst.get("lifecycle_state") != "RUNNING":
            continue
        try:
            atts = compute.list_vnic_attachments(compartment_id=compartment, instance_id=inst["ocid"]).data
            for a in atts:
                if a.lifecycle_state != "ATTACHED":
                    continue
                v = net.get_vnic(a.vnic_id).data
                if getattr(v, "is_primary", True):
                    out[alias] = {"public_ip": v.public_ip, "private_ip": v.private_ip}
                    break
        except Exception as exc:  # noqa: BLE001 - absence is the recorded outcome
            print(f"host lookup failed for {alias}: {type(exc).__name__}")
    return out

# ------------------------------------------------------------------ ledger
def build_rows(date_today: str, metrics: dict[str, dict], ssh: dict[str, dict]) -> list[dict]:
    """One ledger row per (host, date). Every host appears every run, measured or not."""
    rows: list[dict] = []
    for alias, name in HOSTS.items():
        m = metrics.get(alias, {"instance": None, "days": {}, "errors": {"all": "no metrics read"}})
        inst = m.get("instance") or {}
        ocpus = inst.get("ocpus")
        s = ssh.get(alias) or {}
        dates = set(m.get("days", {})) | {date_today}
        for d in sorted(dates):
            v = m.get("days", {}).get(d, {})
            row = {
                "date": d, "host": alias, "display_name": name,
                "partial_day": d >= date_today,
                "ocpus": ocpus, "memory_gb": inst.get("memory_gb"),
                "cpu_p95": v.get("cpu_p95"), "cpu_max": v.get("cpu_max"),
                "mem_p95": v.get("mem_p95"), "mem_max": v.get("mem_max"),
                "net_in_p95_raw": v.get("net_in_p95"), "net_out_p95_raw": v.get("net_out_p95"),
                "net_p95_pct_of_shape": None,   # unit unverified - see header note
                # disk is a point sample taken today; earlier days cannot be back-filled.
                "disk_pct": s.get("disk_pct") if d == date_today else None,
                "ssh_load1": s.get("load1") if d == date_today else None,
                "ssh_mem_used_pct": s.get("mem_used_pct") if d == date_today else None,
            }
            row["read_state"] = {
                "cpu": "measured" if row["cpu_p95"] is not None else "could_not_look",
                "mem": "measured" if row["mem_p95"] is not None else "could_not_look",
                "net": "could_not_look",   # raw bytes recorded; % of shape not derivable
                "disk": "measured" if row["disk_pct"] is not None else "could_not_look",
            }
            errs = {k: e for k, e in m.get("errors", {}).items()}
            if errs and d == date_today:
                row["errors"] = errs
            rows.append(row)
    return rows


def load_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def merge_ledger(existing: list[dict], new: list[dict], keep_days: int = 60) -> list[dict]:
    """Replace by (host, date); a new null never erases an earlier measured value."""
    idx = {(r["host"], r["date"]): r for r in existing}
    for r in new:
        old = idx.get((r["host"], r["date"]))
        if old:
            for k, v in r.items():
                if k in ("read_state", "errors", "partial_day"):
                    continue
                if v is None and old.get(k) is not None:
                    r[k] = old[k]
            r["read_state"] = {m: ("measured" if _val(r, m) is not None else "could_not_look") for m in METRICS}
        # legacy first-run rows carried a bogus network % (unit unverified): never carry it forward.
        r["net_p95_pct_of_shape"] = None
        r.pop("net_p95_bps", None)
        r["read_state"]["net"] = "could_not_look"
        idx[(r["host"], r["date"])] = r
    rows = sorted(idx.values(), key=lambda r: (r["date"], r["host"]))
    cutoff = (dt.date.fromisoformat(rows[-1]["date"]) - dt.timedelta(days=keep_days)).isoformat() if rows else ""
    return [r for r in rows if r["date"] >= cutoff]


def _val(r: dict, m: str) -> Any:
    return r.get({"cpu": "cpu_p95", "mem": "mem_p95", "net": "net_p95_pct_of_shape", "disk": "disk_pct"}[m])


def write_ledger(rows: list[dict], path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


# --------------------------------------------------------- reclaim + spare
def evaluate_host(rows: list[dict], host: str, today: str) -> dict:
    """Oracle idle-reclaim verdict for one host from its last 7 COMPLETE days."""
    mine = [r for r in rows if r["host"] == host and r["date"] < today][-WINDOW_DAYS:]
    out: dict[str, Any] = {"host": host, "days_in_window": len(mine)}
    worst: dict[str, float | None] = {}
    for m in ("cpu", "mem", "net"):
        vals = [_val(r, m) for r in mine if _val(r, m) is not None]
        worst[m] = max(vals) if vals else None
        out[f"{m}_days_measured"] = len(vals)
    out["max_daily_p95"] = {"cpu_pct": worst["cpu"], "mem_pct": worst["mem"], "net_pct_of_shape": worst["net"]}
    if out["cpu_days_measured"] < MIN_DAYS or out["mem_days_measured"] < MIN_DAYS:
        out["status"] = "unknown" if out["cpu_days_measured"] == 0 and out["mem_days_measured"] == 0 else "insufficient"
        out["reason"] = (f"cpu measured {out['cpu_days_measured']}d, mem measured {out['mem_days_measured']}d of the last "
                         f"{WINDOW_DAYS} complete days; need >= {MIN_DAYS} of each. NOT a pass.")
        return out
    # net unmeasured => judge on cpu+mem alone and say so (never treat it as 0 % = idle-qualifying
    # silently; it can only make the verdict MORE cautious to count it as not-below-threshold).
    net_ok = worst["net"] is not None
    out["net_unmeasured"] = not net_ok

    def below(limit: float) -> bool:
        return worst["cpu"] < limit and worst["mem"] < limit and (not net_ok or worst["net"] < limit)

    if below(IDLE_PCT):
        out["status"] = "at_risk"
    elif below(WATCH_PCT):
        out["status"] = "watch"
    else:
        out["status"] = "ok"
    out["reason"] = (f"max daily p95 over {len(mine)}d: cpu {worst['cpu']:.1f}% mem {worst['mem']:.1f}% "
                     f"net {'n/a' if not net_ok else format(worst['net'], '.3f') + '%'} vs Oracle idle < {IDLE_PCT:.0f}% "
                     f"(watch < {WATCH_PCT:.0f}%)")
    return out


def spare_capacity(rows: list[dict], today: str, read_at: str) -> dict:
    """Per-host spare cores / GB, conservative: shape x (1 - max daily p95 over the window).

    ``spare_*`` is ``null`` (never 0) when the host could not be read.
    """
    hosts: dict[str, Any] = {}
    for host, name in HOSTS.items():
        mine = [r for r in rows if r["host"] == host and r["date"] < today][-WINDOW_DAYS:]
        cpu = [r["cpu_p95"] for r in mine if r.get("cpu_p95") is not None]
        mem = [r["mem_p95"] for r in mine if r.get("mem_p95") is not None]
        last = next((r for r in reversed(rows) if r["host"] == host and r.get("ocpus")), {})
        ocpus, gb = last.get("ocpus"), last.get("memory_gb")
        ok = bool(cpu) and bool(mem) and ocpus and gb
        hosts[host] = {
            "display_name": name, "ocpus": ocpus, "memory_gb": gb,
            "read_state": "measured" if ok else "could_not_look",
            "days_measured": min(len(cpu), len(mem)),
            "spare_ocpus": round(ocpus * (1 - max(cpu) / 100.0), 3) if ok else None,
            "spare_memory_gb": round(gb * (1 - max(mem) / 100.0), 3) if ok else None,
            "basis": f"shape x (1 - max daily p95 over last {WINDOW_DAYS} complete days)",
        }
    return {"as_of": read_at, "consumer": "research router (config/research_compute.yaml), trainer backend = hosts.trainer",
            "hosts": hosts}


def get_spare(host: str = "trainer", path: Path = SPARE) -> dict:
    """Reader for the research router. Returns {"read_state","spare_ocpus","spare_memory_gb",...};
    a missing/garbled file is ``could_not_look`` with null spare — never 0."""
    try:
        h = json.loads(path.read_text())["hosts"][host]
        return {**h, "as_of": json.loads(path.read_text())["as_of"]}
    except (OSError, ValueError, KeyError):
        return {"read_state": "could_not_look", "spare_ocpus": None, "spare_memory_gb": None}


# --------------------------------------------------------------------- CLI
def _prior_status() -> dict[str, str]:
    try:
        return {h: v["status"] for h, v in json.loads(STATE.read_text())["hosts"].items()}
    except (OSError, ValueError, KeyError):
        return {}


def cmd_evaluate(rows: list[dict], today: str, write: bool) -> dict:
    verdicts = {h: evaluate_host(rows, h, today) for h in HOSTS}
    prior = _prior_status()
    alert = {h: v for h, v in verdicts.items() if v["status"] in ("at_risk", "watch") and prior.get(h) != v["status"]}
    unknown = [h for h, v in verdicts.items() if v["status"] in ("unknown", "insufficient")]
    state = {"as_of": today, "rule": f"Oracle idle: CPU p95<{IDLE_PCT:.0f}% & net<{IDLE_PCT:.0f}% & mem<{IDLE_PCT:.0f}% over 7d (A1)",
             "hosts": verdicts}
    if write:
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return {"state": state, "alert_hosts": sorted(alert), "unmeasured_hosts": unknown,
            "alert_text": "; ".join(f"{HOSTS[h]} [{v['status']}] {v['reason']}" for h, v in sorted(alert.items()))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["collect", "evaluate", "hosts"])
    ap.add_argument("--out", default=None, help="hosts: where to write the address map")
    ap.add_argument("--ssh-samples", default=None, help="JSON {alias: {disk_pct, load1, mem_used_pct}}")
    ap.add_argument("--gh-output", default=os.environ.get("GITHUB_OUTPUT"))
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    today = now.strftime("%Y-%m-%d")

    if a.cmd == "hosts":
        sys.path.insert(0, str(Path(__file__).parent))
        from oci_inventory import fetch_live
        comp = os.environ.get("OCI_COMPARTMENT_OCID") or os.environ["OCI_CLI_TENANCY"]
        hosts = fetch_hosts(comp, fetch_live(comp))
        for h in hosts.values():          # logs of a public repo are public: mask first
            for ip in h.values():
                if ip:
                    print(f"::add-mask::{ip}")
        Path(a.out or "/tmp/cu/hosts.json").write_text(json.dumps(hosts))
        print("host addresses resolved for:", sorted(hosts))
        return 0

    if a.cmd == "collect":
        comp = os.environ.get("OCI_COMPARTMENT_OCID") or os.environ["OCI_CLI_TENANCY"]
        sys.path.insert(0, str(Path(__file__).parent))
        from oci_inventory import fetch_live  # existing, read-only list_instances
        live = fetch_live(comp)
        metrics = fetch_metrics(comp, live)
        ssh = json.loads(Path(a.ssh_samples).read_text()) if a.ssh_samples and Path(a.ssh_samples).is_file() else {}
        rows = merge_ledger(load_ledger(), build_rows(today, metrics, ssh))
        write_ledger(rows)
        SPARE.write_text(json.dumps(spare_capacity(rows, today, now.isoformat(timespec="seconds")), indent=2, sort_keys=True) + "\n")
        LIMITS.write_text(json.dumps(fetch_limits(os.environ["OCI_CLI_TENANCY"], comp, live), indent=2, sort_keys=True) + "\n")

    rows = load_ledger()
    res = cmd_evaluate(rows, today, write=(a.cmd == "collect"))
    print(json.dumps(res, indent=2, sort_keys=True))
    if a.gh_output:
        with open(a.gh_output, "a") as fh:
            fh.write(f"alert={'true' if res['alert_hosts'] else 'false'}\n")
            fh.write(f"alert_text={' '.join(res['alert_text'].split())}\n")
            fh.write(f"unmeasured={','.join(res['unmeasured_hosts'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
