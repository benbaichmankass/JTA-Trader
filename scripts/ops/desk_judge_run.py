#!/usr/bin/env python3
# wiring: manual-only - run by the `run-desk-judge` system-action (scripts/ops/run_desk_judge_action.sh) on the live VM; no schedule consumes it.
"""DESK-18B -- the judging run, as one dispatchable unit: packets -> API judge -> merge -> intake.

Runs on the LIVE VM, the only place ANTHROPIC_API_KEY exists. One dispatch judges the packet range
[offset, offset + n) of the REGISTERED schedule (seed 20261026, never the pilot seed 20261027), spends at most
`--max-usd` of API money, and prints the per-call ledger, the dollars spent and the driver's `intake` summary.

WHAT IT DOES NOT DO: it never replays and never scores (`intake` is the stopping-rule accounting from the proposals
alone, no outcome is seen); it never touches the trader, any service, any config or any order path; it never prints
the API key.

Refusals (exit 2, BEFORE any packet is built or any call is made):
  * --max-usd missing, not a positive finite number, or above HARD_CEILING_USD;
  * --n / --offset outside the registered schedule (1,500 packets);
  * a range that overlaps packets already judged by a DIFFERENT dispatch, or that leaves a gap after the judged
    prefix (the stopping rule needs a schedule prefix);
  * a stop already satisfied: the judged proposals already reach the registered stopping count (next_batch_allowed false).
`--apply` is required to spend; without it the run is a DRY RUN: it builds the packets, prints the worst-case
dollar estimate (desk_judge_api --estimate-only, no client, no key) and exits before any API call.

Layout (all under <repo>/runtime_logs/desk_judge/judged-1/, untracked, mode 0700, never on a branch):
  candles/                      Binance Vision klines, fetched once and reused (so every packet sees one candle set)
  batches/off<OFFSET>_n<N>/     packets.jsonl, mask-key.json, JUDGE-PROTOCOL.md, judged/pNN.json, usage.jsonl
  export/                       the merged judged-1 deliverable: mask-key.json + proposals.jsonl (+ packets.jsonl)
Re-dispatching the SAME offset and n resumes that batch (judged packets are skipped, the ledger appends).

Exit: 0 ok (a cap / deadline stop is still 0: it is the designed stop, reported in `stopped`); 2 refused;
3 environment (no key, driver failed); 4 the judge ran but intake could not.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

REGISTERED_SEED = 20261026           # == scripts/research/desk_gen_replay_driver.SEED; pinned by a test
SCHEDULE_LEN = 1500                  # == driver SCHEDULE_LEN
HARD_CEILING_USD = 40.0              # the largest option the operator's spend decision offers
DEFAULT_DEADLINE_S = 840             # the workflow job limit is 20 min; leave room for packets, merge and intake
BATCH_RE = re.compile(r"^off(\d{4})_n(\d{4})$")


class Refused(Exception):
    """A precondition failed; nothing was built and nothing was spent."""


# ----------------------------------------------------------------------------- argument checks
def parse_max_usd(raw: Any) -> float:
    if raw is None or str(raw).strip() == "":
        raise Refused("--max-usd is required: a judging run never starts without an explicit dollar cap")
    try:
        v = float(str(raw).strip())
    except ValueError:
        raise Refused(f"--max-usd {raw!r} is not a number") from None
    if not math.isfinite(v) or v <= 0:
        raise Refused(f"--max-usd must be a positive finite number (got {raw!r})")
    if v > HARD_CEILING_USD:
        raise Refused(f"--max-usd {v} is above the hard ceiling {HARD_CEILING_USD} (the largest option in the spend decision)")
    return v


def check_range(n: int, offset: int) -> None:
    if n < 1:
        raise Refused(f"--n must be >= 1 (got {n})")
    if offset < 0:
        raise Refused(f"--offset must be >= 0 (got {offset})")
    if offset + n > SCHEDULE_LEN:
        raise Refused(f"--offset {offset} + --n {n} = {offset + n} runs past the registered schedule ({SCHEDULE_LEN} packets)")


# ----------------------------------------------------------------------------- state on disk
def batch_dir(root: Path, offset: int, n: int) -> Path:
    return root / "batches" / f"off{offset:04d}_n{n:04d}"


def judged_indices(root: Path) -> dict[int, tuple[Path, int]]:
    """{global schedule index: (batch dir, local index)} for every packet with a judged file."""
    out: dict[int, tuple[Path, int]] = {}
    for d in sorted((root / "batches").glob("off*_n*")):
        m = BATCH_RE.match(d.name)
        if not m:
            continue
        off = int(m.group(1))
        for f in (d / "judged").glob("p*.json"):
            k = int(f.stem[1:])
            out[off + k] = (d, k)
    return out


def judged_prefix(idx: set[int]) -> int:
    p = 0
    while p in idx:
        p += 1
    return p


def check_against_state(root: Path, offset: int, n: int) -> None:
    """Resuming the same (offset, n) is always allowed. A new shape must start exactly at the judged prefix and
    overlap nothing already judged: the registered stopping rule counts a schedule PREFIX, and an overlap is a
    packet paid for twice."""
    if batch_dir(root, offset, n).is_dir():
        return
    J = set(judged_indices(root))
    clash = sorted(i for i in range(offset, offset + n) if i in J)
    if clash:
        raise Refused(f"packets {clash[0]}..{clash[-1]} ({len(clash)}) are already judged by another dispatch. Re-dispatch the "
                      f"ORIGINAL offset and n to resume that batch, or start at offset {judged_prefix(J)} once it is complete")
    p = judged_prefix(J)
    if offset != p:
        raise Refused(f"offset {offset} leaves a gap: the judged schedule prefix is {p} packets, so the next batch starts at "
                      f"offset {p} (the stopping rule needs a prefix)")


def check_stop_rule(root: Path, offset: int, n: int) -> None:
    """The last intake said the registered stopping rule is met: no NEW batch may start (a resume of an old one may)."""
    f = root / "export" / "intake.json"
    if f.exists() and not batch_dir(root, offset, n).is_dir():
        if json.loads(f.read_text()).get("next_batch_allowed") is False:
            raise Refused("the last intake reports next_batch_allowed=false (the registered stopping rule is met); no further batch is allowed")


# ----------------------------------------------------------------------------- merge
def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def merge_run(root: Path) -> dict[str, Any]:
    """Write root/export/{mask-key.json,proposals.jsonl,packets.jsonl} for the JUDGED packets only, in schedule order.

    mask-key.json carries exactly the keys of judged packets (each with its packet_sha); proposals.jsonl is the judge's
    rows concatenated in the same order, which is what `intake` and `score` consume."""
    export = root / "export"
    export.mkdir(parents=True, exist_ok=True)
    keys: list[dict] = []
    props: list[str] = []
    pkts: list[str] = []
    conflicts: list[str] = []
    seen: dict[str, str] = {}
    for gi, (d, k) in sorted(judged_indices(root).items()):
        packets = [ln for ln in (d / "packets.jsonl").read_text().splitlines() if ln.strip()]
        pid = json.loads(packets[k])["packet_id"]
        kd = {x["packet_id"]: x for x in json.loads((d / "mask-key.json").read_text())["keys"]}
        key = kd[pid]
        if int(key["index"]) != gi:
            raise RuntimeError(f"{d.name}: packet {pid} has key index {key['index']} but sits at schedule index {gi}")
        if pid in seen:
            conflicts.append(pid)
            continue
        seen[pid] = d.name
        keys.append(key)
        pkts.append(packets[k])
        props.extend(json.dumps(r, sort_keys=True) for r in json.loads((d / "judged" / f"p{k:02d}.json").read_text()))
    (export / "mask-key.json").write_text(json.dumps({"seed": REGISTERED_SEED, "note": "NEVER given to the judging session", "keys": keys}, indent=1) + "\n")
    (export / "proposals.jsonl").write_text("".join(ln + "\n" for ln in props))
    (export / "packets.jsonl").write_text("".join(ln + "\n" for ln in pkts))
    return {"packets_merged": len(keys), "rows": len(props), "duplicate_packet_ids": conflicts}


def ledger_lines(d: Path) -> list[dict]:
    f = d / "usage.jsonl"
    return _read_jsonl(f) if f.exists() else []


def ledger_total(root: Path) -> tuple[float, int]:
    tot, calls = 0.0, 0
    for d in (root / "batches").glob("off*_n*"):
        for r in ledger_lines(d):
            tot += float(r.get("cost_usd") or 0)
            calls += 1
    return round(tot, 6), calls


# ----------------------------------------------------------------------------- orchestration
Runner = Callable[[list[str], dict[str, str] | None], "subprocess.CompletedProcess[str]"]


def _run(cmd: list[str], env: dict[str, str] | None = None) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


def _json_tail(text: str) -> dict:
    for ln in reversed(text.strip().splitlines()):
        try:
            v = json.loads(ln)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return {}


def execute(a: argparse.Namespace, runner: Runner = _run, now: Callable[[], float] = time.monotonic,
            environ: dict[str, str] | None = None, out=print) -> int:
    environ = os.environ if environ is None else environ
    t0 = now()
    try:
        cap = parse_max_usd(a.max_usd)
        check_range(a.n, a.offset)
        root = Path(a.root)
        check_against_state(root, a.offset, a.n)
        check_stop_rule(root, a.offset, a.n)
    except Refused as e:
        out(f"REFUSED: {e}")
        return 2
    if a.apply and not environ.get("ANTHROPIC_API_KEY"):
        out("ENVIRONMENT: ANTHROPIC_API_KEY is not set in the VM's .env; nothing was built or spent")
        return 3
    repo = Path(a.repo_dir)
    py = a.python
    drv = str(repo / "scripts/research/desk_gen_replay_driver.py")
    jdg = str(repo / "scripts/research/desk_judge_api.py")
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    cdir = root / "candles"
    bdir = batch_dir(root, a.offset, a.n)
    out(f"=== run-desk-judge: {'APPLY' if a.apply else 'DRY-RUN'} offset={a.offset} n={a.n} max_usd={cap} seed={REGISTERED_SEED} "
        f"key_present={'yes' if environ.get('ANTHROPIC_API_KEY') else 'no'} ===")

    # 1. packets (reused when this exact batch was already built, so a resume judges the packets it began with)
    if (bdir / "packets.jsonl").exists() and (bdir / "mask-key.json").exists():
        out(f"packets: reusing {bdir.name}")
    else:
        cmd = [py, drv, "packets", "--out", str(bdir), "--candles-dir", str(cdir), "--seed", str(REGISTERED_SEED),
               "--n", str(a.n), "--offset", str(a.offset)]
        if not cdir.is_dir() or not any(cdir.iterdir()):
            cmd.append("--fetch")
        r = runner(cmd, None)
        info = _json_tail(r.stdout)
        if r.returncode != 0 or not info.get("packets"):
            out(f"ENVIRONMENT: packets step failed (rc {r.returncode}): {(r.stdout + r.stderr).strip()[-600:]}")
            return 3
        out(f"packets: built {info['packets']} (withheld_for_leak {info.get('withheld_for_leak')}, median_packet_chars "
            f"{info.get('median_packet_chars')}) -> {bdir.name}")
    os.chmod(bdir / "mask-key.json", 0o600)

    base = [py, jdg, "--packets", str(bdir / "packets.jsonl"), "--protocol", str(bdir / "JUDGE-PROTOCOL.md"), "--out", str(bdir),
            "--offset", "0", "--n", str(a.n), "--max-usd", repr(cap)]
    if not a.apply:
        r = runner(base + ["--estimate-only"], None)
        out("dry-run estimate (no API call): " + (r.stdout.strip().splitlines() or ["<none>"])[-1])
        out("DRY-RUN complete: packets built, no API call made. Re-dispatch with 'apply: true' to spend.")
        return 0

    # 2. judge (stateless API, one call per packet; the cap and the deadline stop it BEFORE a call, never mid-call)
    before = len(ledger_lines(bdir))
    remaining = max(1.0, a.deadline_s - (now() - t0))
    r = runner(base + ["--deadline-s", f"{remaining:.0f}"], dict(environ))
    res = _json_tail(r.stdout)
    if r.returncode != 0 and not res:
        out(f"ENVIRONMENT: judge failed (rc {r.returncode}): {(r.stdout + r.stderr).strip()[-600:]}")
        return 3

    # 3. merge + intake over EVERYTHING judged so far
    mer = merge_run(root)
    ex = root / "export"
    ir = runner([py, drv, "intake", "--out", str(ex), "--candles-dir", str(cdir), "--seed", str(REGISTERED_SEED),
                 "--proposals", str(ex / "proposals.jsonl"), "--packets", str(ex / "packets.jsonl"),
                 "--mask-key", str(ex / "mask-key.json")], None)
    intake = _json_tail(ir.stdout)
    if intake.get("next_batch_allowed") is not None:
        (ex / "intake.json").write_text(json.dumps(intake) + "\n")

    # 4. report: the ledger first, the summary LAST (the issue comment keeps the tail)
    led = ledger_lines(bdir)
    out(f"--- per-call ledger, this batch ({len(led)} lines; {len(led) - before} added by this dispatch) ---")
    out("idx packet_id in_tok out_tok cache_w cache_r cost_usd parsed")
    for x in led:
        u = x.get("usage") or {}
        out(f"{x['index']} {x['packet_id']} {u.get('input_tokens', 0)} {u.get('output_tokens', 0)} "
            f"{u.get('cache_creation_input_tokens', 0)} {u.get('cache_read_input_tokens', 0)} {x.get('cost_usd')} "
            f"{'ok' if x.get('parsed') else 'UNPARSED:' + str(x.get('problem'))[:60]}")
    run_total, run_calls = ledger_total(root)
    summary = {
        "this_dispatch": {"judged": res.get("judged"), "skipped_existing": res.get("skipped_existing"), "unparsed": res.get("unparsed"),
                          "spent_usd": res.get("spent_usd"), "usd_per_packet": res.get("usd_per_packet"), "stopped": res.get("stopped"),
                          "max_usd": cap},
        "whole_run_ledger": {"calls": run_calls, "spent_usd": run_total},
        "merge": mer,
        "intake": intake or {"error": "intake produced no result", "stderr": ir.stderr.strip()[-300:]},
        "export_dir": str(ex),
        "prices_note": "list prices are INFERRED for the model; the ledger's token counts are the API's own usage",
    }
    out("=== SUMMARY ===")
    out(json.dumps(summary, indent=1))
    if intake and intake.get("next_batch_allowed") is False:
        out("STOP RULE: next_batch_allowed is false. Do not dispatch another batch; the judged-1 export is complete.")
    if not intake:
        return 4
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--offset", type=int, required=True)
    p.add_argument("--max-usd", default=None, help="REQUIRED, per-dispatch hard cap in dollars (refused if absent)")
    p.add_argument("--apply", action="store_true", help="spend; without it the run is a dry run that exits before any API call")
    p.add_argument("--repo-dir", default=os.environ.get("REPO_DIR", str(Path(__file__).resolve().parents[2])))
    p.add_argument("--root", default=None)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--deadline-s", type=float, default=DEFAULT_DEADLINE_S)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.root is None:
        a.root = str(Path(a.repo_dir) / "runtime_logs" / "desk_judge" / "judged-1")
    return execute(a)


if __name__ == "__main__":
    sys.exit(main())
