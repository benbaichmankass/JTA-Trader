#!/usr/bin/env python3
# wiring: manual-only - run once by a system-action on the live VM (the only place ANTHROPIC_API_KEY legitimately exists) for the DESK-18B judging run; no schedule consumes it.
"""DESK-18B -- stateless batch judge: ONE Anthropic Messages API call per masked packet.

Why this exists: the pilot judged 50 packets through five manager-spawned sessions at $0.337/packet MEASURED,
because every batch carried ~290k tokens of session context. A stateless call carries only JUDGE-PROTOCOL.md
(system, prompt-cached) plus the one packet (~6 k tokens in).

What the model sees: JUDGE-PROTOCOL.md and one packet's JSON. Never the mask key, never the repo, never a tool.
Output format matches the pilot's: `<out>/judged/pNN.json` is a JSON array of the judge's parsed rows, which
`desk_gen_replay_driver.py intake` consumes after concatenation. This script never replays and never scores.

Spend: `--max-usd` is a HARD cap. Before every call the worst case for that call (input tokens estimated from
characters, plus `max_tokens` of output, at the declared prices, with the cache write premium) is added to the
spend so far; if that would pass the cap, the run stops BEFORE the call. Spend is then updated from the API's
reported `usage`. Every call appends one line to `<out>/usage.jsonl` (tokens and dollars), so a stop is resumable
(`--skip-done`, the default, skips packets whose judged file exists).

The key is read from the environment only (`ANTHROPIC_API_KEY`, as `src/runtime/insights/generator.py` does) and
is never printed or written.

Prices are PARAMETERS, not facts: the defaults are the Sonnet-tier list price carried by
`src/runtime/insights/usage.py` (input 3.00, cache read 0.30, output 15.00 $/MTok; cache write = 1.25 x input)
and are INFERRED for `claude-sonnet-5-5` -- pass --price-* to override. Verify the real price before relying on
the dollar column.

  python3 scripts/research/desk_judge_api.py --packets P/packets.jsonl --protocol P/JUDGE-PROTOCOL.md \\
      --out OUT --offset 0 --n 200 --max-usd 5 [--estimate-only]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_OUTPUT_TOKENS = 700            # two proposal rows with a one-line thesis fit well inside this
CHARS_PER_TOKEN = 3.5              # INFERRED; the real count comes back in usage
PRICES = {"input": 3.00, "cache_read": 0.30, "output": 15.00}     # $/MTok, see module docstring
CACHE_WRITE_MULT = 1.25
USER_TMPL = "PACKET:\n{packet}\n\nReply with the JSON line(s) only. Do not use any tools."


def call_cost(usage: Dict[str, int], prices: Dict[str, float]) -> float:
    """Dollars from an API `usage` dict: uncached input, cache writes (1.25x input), cache reads, output."""
    return (usage.get("input_tokens", 0) * prices["input"]
            + usage.get("cache_creation_input_tokens", 0) * prices["input"] * CACHE_WRITE_MULT
            + usage.get("cache_read_input_tokens", 0) * prices["cache_read"]
            + usage.get("output_tokens", 0) * prices["output"]) / 1e6


def worst_case_cost(chars_in: int, prices: Dict[str, float], max_out: int = MAX_OUTPUT_TOKENS) -> float:
    """Upper bound for ONE call: every input token billed as a cache write, the full output allowance used."""
    tok = chars_in / CHARS_PER_TOKEN
    return (tok * prices["input"] * CACHE_WRITE_MULT + max_out * prices["output"]) / 1e6


def parse_rows(text: str, packet_id: str) -> Tuple[Optional[List[dict]], str]:
    """The judge's JSON line(s) -> rows, or (None, reason). Tolerates a ```json fence; nothing else."""
    body = text.strip()
    if body.startswith("```"):
        body = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("```"))
    rows: List[dict] = []
    for ln in body.splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            return None, f"unparsable line: {ln[:80]!r}"
        if not isinstance(r, dict) or r.get("packet_id") != packet_id or r.get("action") not in ("no_trade", "propose_entry"):
            return None, "row without the packet's id or a valid action"
        rows.append(r)
    return (rows, "") if rows else (None, "empty reply")


def make_client() -> Any:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set in this environment (it exists on the live VM's .env only)")
    import anthropic  # lazy: tests inject a fake client
    return anthropic.Anthropic()


def judge_one(client: Any, model: str, protocol: str, packet: dict, packet_id: str) -> Tuple[str, Dict[str, int]]:
    resp = client.messages.create(
        model=model, max_tokens=MAX_OUTPUT_TOKENS,
        system=[{"type": "text", "text": protocol, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": USER_TMPL.format(packet=json.dumps(packet, separators=(",", ":")))}])
    text = "".join(getattr(b, "text", "") or "" for b in (resp.content or []) if getattr(b, "type", None) == "text")
    u = resp.usage
    usage = {k: int(getattr(u, k, 0) or 0) for k in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    return text, usage


def load_packets(path: Path) -> List[Tuple[str, dict]]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out.append((r["packet_id"], r["packet"]))
    return out


def run(a: argparse.Namespace, client: Any = None, sleep=time.sleep) -> Dict[str, Any]:
    prices = {"input": a.price_input, "cache_read": a.price_cache_read, "output": a.price_output}
    protocol = Path(a.protocol).read_text()
    packets = load_packets(Path(a.packets))[a.offset:a.offset + a.n]
    out = Path(a.out)
    (out / "judged").mkdir(parents=True, exist_ok=True)
    ledger = out / "usage.jsonl"
    spent, done, skipped, unparsed, stopped = 0.0, 0, 0, 0, ""
    est = [worst_case_cost(len(protocol) + len(json.dumps(p, separators=(",", ":"))) + len(USER_TMPL), prices) for _, p in packets]
    if a.estimate_only:
        return {"estimate_only": True, "packets": len(packets), "worst_case_usd_total": round(sum(est), 4),
                "worst_case_usd_per_packet": round(sum(est) / max(1, len(est)), 5),
                "note": "worst case: all input billed as cache write + full max_tokens output; the real figure is far lower"}
    client = client or make_client()
    for k, (pid, pkt) in enumerate(packets):
        idx = a.offset + k
        f = out / "judged" / f"p{idx:02d}.json"
        if a.skip_done and f.exists():
            skipped += 1
            continue
        if spent + est[k] > a.max_usd:
            stopped = f"max_usd {a.max_usd} would be exceeded by packet index {idx} (spent {spent:.4f} + worst case {est[k]:.4f})"
            break
        for attempt in range(3):               # a transient API failure is retried; it never halts the run
            try:
                text, usage = judge_one(client, a.model, protocol, pkt, pid)
                break
            except Exception as e:             # noqa: BLE001 - recorded, then retried
                text, usage = "", {}
                err = f"{type(e).__name__}: {str(e)[:120]}"
                sleep(2 ** (attempt + 1))
        cost = call_cost(usage, prices)
        spent += cost
        rows, why = parse_rows(text, pid) if text else (None, locals().get("err", "no reply"))
        with ledger.open("a") as fh:
            fh.write(json.dumps({"index": idx, "packet_id": pid, "model": a.model, "usage": usage,
                                 "cost_usd": round(cost, 6), "parsed": rows is not None, "problem": why}) + "\n")
        if rows is None:
            unparsed += 1                       # no judged file: the packet stays visible as missing, never a silent no_trade
            continue
        f.write_text(json.dumps(rows))
        done += 1
    return {"judged": done, "skipped_existing": skipped, "unparsed": unparsed, "spent_usd": round(spent, 6),
            "usd_per_packet": round(spent / done, 6) if done else None, "stopped": stopped or None, "prices": prices}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--packets", required=True, help="packets.jsonl from `desk_gen_replay_driver.py packets`")
    p.add_argument("--protocol", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--price-input", type=float, default=PRICES["input"])
    p.add_argument("--price-cache-read", type=float, default=PRICES["cache_read"])
    p.add_argument("--price-output", type=float, default=PRICES["output"])
    p.add_argument("--no-skip-done", dest="skip_done", action="store_false")
    p.add_argument("--estimate-only", action="store_true")
    a = p.parse_args(argv)
    print(json.dumps(run(a)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
