"""The trading pipeline map, GENERATED from the sources of truth (lane PIPELINE-MAP, 2026-11-14).

Operator, 2026-11-14 (relayed by the manager): "as much of it as possible should be wired into
something else that's a source of truth -- the database, the training roster, things like that --
so it stays up to date."

So the map is assembled, not written. The ONLY hand-written part is the static skeleton
``docs/reference/trading-pipeline-map.skeleton.md``: the stage order, what each stage does, and
which modules run it. Every ``<!-- GEN:<name> -->`` marker in it is replaced by a block built from
a source of truth:

    where      deploy/*.service + deploy/trainer/*.service (which unit runs what, on which VM) and
               config/trader_import_closure.txt (does a skeleton module run inside the trader)
    accounts   config/accounts.yaml (class, exchange, mode, position model, DD switch, roster size)
    ml         ml/served/SERVED_MODELS.yaml (stage + headline metric with provenance)
    mandates   config/mandates.yaml + config/live_trade_review.yaml (what may be applied unasked)
    legs       scripts/ops/strategy_status.py + comms/strategy_evidence/*.json (backtest) + the
               journal's /api/bot/performance payload (live, R only) + scripts/ci/check_tp_doctrine.py
    checks     the skeleton checked against the repo: every module path it cites exists; every
               rostered leg is defined; every enabled leg is on a book. Drift shows as a warning
               here, never as a wrong claim.

An unreadable source renders "—" with its read state, never 0. A live book never establishes edge;
backtest and live sit in separate columns. Used by ``GET /api/bot/work/pipeline-map`` (built live,
cached) and by ``scripts/ops/pipeline_map_numbers.py`` (writes the committed snapshot
``docs/reference/trading-pipeline-map.md``). A report, never a gate.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from src.runtime.provenance import MEASURED, UNVERIFIED

REPO = Path(__file__).resolve().parents[2]
SKELETON_REL = "docs/reference/trading-pipeline-map.skeleton.md"
SNAPSHOT_REL = "docs/reference/trading-pipeline-map.md"
DASH = "—"
_MARK = re.compile(r"<!--\s*GEN:([a-z_]+)\s*-->")
_PATH = re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-<>]+)+/?)(?:::[A-Za-z0-9_.]+)?`")


def _yaml(root: Path, rel: str) -> tuple[Any, str]:
    p = root / rel
    if not p.is_file():
        return None, f"missing ({rel})"
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")), "read"
    except (OSError, yaml.YAMLError) as e:
        return None, f"unreadable ({type(e).__name__})"


def _cell(v: Any) -> str:
    if v is None or v == "":
        return DASH
    return str(v).replace("|", "\\|").replace("\n", " ")


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return DASH
    if isinstance(v, float):
        return f"{v:+.{nd}f}"
    return str(v)


def _clip(s: Any, n: int = 140) -> str:
    t = _cell(s)
    return t if len(t) <= n else t[: n - 1] + "…"


# ── where: units and the trader closure ────────────────────────────────────────────────────
def _closure(root: Path) -> set | None:
    p = root / "config" / "trader_import_closure.txt"
    if not p.is_file():
        return None
    return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def _exec(unit: Path) -> str:
    for ln in unit.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("ExecStart="):
            cmd = ln.split("=", 1)[1]
            cmd = re.sub(r"/home/ubuntu/ict-trading-bot/(\.venv/bin/)?", "", cmd)
            cmd = re.sub(r"/opt/ict-trading-bot/", "", cmd)
            return cmd.replace("/usr/bin/python3", "python3").replace("/bin/bash ", "bash ")
    return DASH


def gen_where(root: Path, _ctx: dict[str, Any]) -> str:
    rows = []
    for vm, pattern in (("live VM (`ict-bot-arm`)", "deploy/*.service"),
                        ("trainer VM (`ict-trainer-vm`)", "deploy/trainer/*.service")):
        for u in sorted(glob.glob(str(root / pattern))):
            rows.append(f"| `{Path(u).stem}` | {vm} | `{_clip(_exec(Path(u)), 110)}` |")
    if not rows:
        return f"_Units: {DASH} (no unit files found under `deploy/`)._"
    return ("**Every systemd unit in the repo and what it runs** (source: `deploy/*.service`, "
            f"`deploy/trainer/*.service`; {len(rows)} units; a unit file in the repo is not proof it is "
            "enabled on the VM: `/api/diag/services` is the runtime truth).\n\n"
            "| Unit | Host | Runs |\n|---|---|---|\n" + "\n".join(rows))


# ── accounts ─────────────────────────────────────────────────────────────────────────────
def gen_accounts(root: Path, _ctx: dict[str, Any]) -> str:
    doc, state = _yaml(root, "config/accounts.yaml")
    accts = (doc or {}).get("accounts") if isinstance(doc, dict) else None
    if not isinstance(accts, dict):
        return f"_Accounts: {DASH} (`config/accounts.yaml` {state})._"
    out = [("**Accounts** (source: `config/accounts.yaml`; names only, no ids or balances; "
            f"{len(accts)} accounts)."), "",
           "| Account | Class | Exchange | Mode (gate 1) | Position model | Daily DD switch | Legs on roster |",
           "|---|---|---|---|---|---|---|"]
    for name, cfg in accts.items():
        if not isinstance(cfg, dict):
            continue
        dd = ((cfg.get("risk") or {}).get("daily_dd_switch") or {}) if isinstance(cfg.get("risk"), dict) else {}
        armed = "armed" if dd.get("armed") is True else "disarmed"
        out.append("| " + " | ".join([f"`{name}`", _cell(cfg.get("account_class")), _cell(cfg.get("exchange")),
                                      _cell(cfg.get("mode")), _cell(cfg.get("position_model") or f"{DASH} (default)"),
                                      armed, str(len(cfg.get("strategies") or []))]) + " |")
    return "\n".join(out)


# ── ML ───────────────────────────────────────────────────────────────────────────────────
def gen_ml(root: Path, _ctx: dict[str, Any]) -> str:
    doc, state = _yaml(root, "ml/served/SERVED_MODELS.yaml")
    models = (doc or {}).get("models") if isinstance(doc, dict) else None
    if not isinstance(models, dict):
        return f"_Served models: {DASH} (`ml/served/SERVED_MODELS.yaml` {state})._"
    ptr = root / "ml" / "served" / "ENTRY_SERVED.json"
    try:
        served_dir = json.loads(ptr.read_text(encoding="utf-8")).get("artifact_dir")
    except (OSError, ValueError):
        served_dir = None
    out = [(f"**Served ML models** (source: `ml/served/SERVED_MODELS.yaml`; {len(models)} models; the entry "
            f"pointer `ml/served/ENTRY_SERVED.json` serves `{served_dir or DASH}`). Headline metrics are the "
            "registry's own, with its provenance and population."), "",
           "| Model | Stage | Headline metric | Value | n | Window | Verdict | Provenance | Source |",
           "|---|---|---|---|---|---|---|---|---|"]
    for mid, m in models.items():
        m = m if isinstance(m, dict) else {}
        h = m.get("headline_metric") if isinstance(m.get("headline_metric"), dict) else {}
        src = h.get("source")
        out.append("| " + " | ".join([f"`{mid}`", _cell(m.get("stage")), _cell(h.get("name")),
                                      _fmt(h.get("value"), 4), _cell(h.get("n")), _cell(h.get("window")),
                                      _cell(h.get("verdict")), _cell(h.get("provenance")),
                                      f"`{src}`" if src else DASH]) + " |")
    return "\n".join(out)


# ── mandates ─────────────────────────────────────────────────────────────────────────────
def gen_mandates(root: Path, _ctx: dict[str, Any]) -> str:
    doc, state = _yaml(root, "config/mandates.yaml")
    granted = (doc or {}).get("mandates") if isinstance(doc, dict) else None
    if not isinstance(granted, list):
        return f"_Mandates: {DASH} (`config/mandates.yaml` {state})._"
    out = [(f"**Granted mandates** (source: `config/mandates.yaml` `mandates:`; {len(granted)} granted; "
            f"{len((doc or {}).get('proposed') or [])} proposed, not shown). A mandate decides what may be "
            "CHANGED without asking, never what runs."), "",
           "| Mandate | Kind | Grants | Granted | Auto-land |", "|---|---|---|---|---|"]
    for m in granted:
        if isinstance(m, dict):
            out.append("| " + " | ".join([f"`{_cell(m.get('id'))}`", _cell(m.get("kind")), _clip(m.get("grants")),
                                          _cell(str(m.get("granted_at") or "")[:10]),
                                          "yes" if m.get("autoland") else DASH]) + " |")
    ltr, lstate = _yaml(root, "config/live_trade_review.yaml")
    if isinstance(ltr, dict):
        out += ["", (f"**Live trade review config** (`config/live_trade_review.yaml`): apply_mode "
                     f"`{_cell(ltr.get('apply_mode'))}`, accounts `{_cell(ltr.get('accounts'))}`.")]
    else:
        out += ["", f"_Live trade review config: {DASH} ({lstate})._"]
    return "\n".join(out)


# ── legs ─────────────────────────────────────────────────────────────────────────────────
def _evidence(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(glob.glob(str(root / "comms" / "strategy_evidence" / "*.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # unreadable record: the leg then reads "no evidence record", stated below
        if isinstance(d, dict) and isinstance(d.get("strategy"), str):
            d["_path"] = os.path.relpath(f, root)
            out[d["strategy"]] = d
    return out


def _cost_basis(ev: dict[str, Any]) -> str:
    cs = ev.get("cost_stack")
    if isinstance(cs, dict) and all(cs.get(k) is not None for k in ("fees", "slippage", "funding")):
        return "full"
    return "fee-only" if ev.get("fee_bps_roundtrip") is not None else DASH


def _per_strategy(block: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(block, dict):
        return {}
    return {r.get("name"): r for r in block.get("perStrategy") or [] if isinstance(r, dict)}


def _live_cell(row: dict[str, Any] | None, read: bool) -> str:
    if not read:
        return DASH
    if not row:
        return "0 trades"
    rp = row.get("rProvenance") or {}
    # every r_provenance state the route reports, so none fall together
    states = [("confirmed", rp.get("confirmedInitial")), (UNVERIFIED, rp.get("unverified")),
              ("contaminated", rp.get("contaminated")), ("no basis", rp.get("noBasis"))]
    parts = [f"{k} {v}" for k, v in states if v]
    tag = f" · R basis: {', '.join(parts)}" if parts else (" · R basis —" if not rp else "")
    return f"n={row.get('trades')} · ΣR {_fmt(row.get('totalR'))} · E[R] {_fmt(row.get('expectancyR'))}{tag}"


def _tp_summary(root: Path) -> str:
    try:
        p = subprocess.run([sys.executable, str(root / "scripts" / "ci" / "check_tp_doctrine.py")], cwd=root,
                           capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return f"unreadable ({type(e).__name__})"
    lines = [ln.rstrip() for ln in (p.stdout + p.stderr).splitlines()
             if ln.startswith(("population:", "  real_money", "  prop", "  mirror", "  paper"))]
    return "\n".join(lines) if lines else "unreadable (no summary lines)"


def gen_legs(root: Path, ctx: dict[str, Any]) -> str:
    from scripts.ops import strategy_status as ss
    status = ss.table(root)
    strategies = ss.load(root)[1]
    if not status:
        return f"_Legs: {DASH} (`config/strategies.yaml` empty or unreadable)._"
    evidence = _evidence(root)
    ctx["evidence"] = evidence
    live, live_state = ctx.get("live"), ctx.get("live_state", "not read")
    read = live_state == "read"
    real, paper = _per_strategy(live), _per_strategy((live or {}).get("paper"))
    trust = (live or {}).get("journalTrust") or {}
    counts: dict[str, int] = {}
    for r in status.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    order = {"production": 0, "testing": 1, "inactive": 2}
    out = [f"**Population:** {len(status)} legs in `config/strategies.yaml` — "
           + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9)))
           + " (status DERIVED by `scripts/ops/strategy_status.py`).", "",
           "**Read this table in two halves.** *Backtest* is the offline Stage-0 evidence record (the only "
           f"thing that establishes edge; provenance `{MEASURED}` when the record's `coverage_state` is measured). "
           "*Live* is the journal's realized R from `/api/bot/performance?window=all` (lifetime window, so it can "
           "include trades from before a leg's current status): it checks mechanics and cost, **never edge**. Live "
           "real money = the route's top-level real-money aggregate; live paper = its `paper` block. "
           f"Live read-state: **{live_state}**"
           + (f"; journal trust: known-divergent {trust.get('accountsKnownDivergent') or []}, "
              f"unrecorded {trust.get('accountsUnrecorded') or []}" if trust else "") + ".", "",
           ("| Leg | Status | Books | Exec (gate 2) | Backtest net R OOS (full cost) | n OOS | Folds + | Cost basis "
            "| Stage-0 verdict | Evidence as of | Live real money (R) | Live paper (R) |"),
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for leg, row in sorted(status.items(), key=lambda kv: (order.get(kv[1]["status"], 9), kv[0])):
        ev = evidence.get(leg) or {}
        cfg = strategies.get(leg) or {}
        rule = ev.get("decision_rule") if isinstance(ev.get("decision_rule"), dict) else {}
        folds = (f"{ev['folds_positive']}/{ev['folds']}"
                 if ev.get("folds_positive") is not None and ev.get("folds") else DASH)
        cov = ev.get("coverage_state")
        prov = f" `{MEASURED}`" if cov == "measured" else (f" `{cov}`" if cov else "")
        net = (_fmt(ev.get("net_r_oos")) + prov) if ev.get("net_r_oos") is not None else DASH
        asof = str(ev.get("generated_at") or "")[:10] or DASH
        link = f"[{asof}](../../{ev['_path']})" if ev.get("_path") and asof != DASH else asof
        out.append("| " + " | ".join([
            f"`{leg}`", row["status"], ", ".join(row["books"]) or DASH, _cell(cfg.get("execution")),
            net, _fmt(ev.get("n_trades_oos")), folds, _cost_basis(ev) if ev else DASH,
            _cell(rule.get("verdict")), link, _live_cell(real.get(leg), read), _live_cell(paper.get(leg), read),
        ]) + " |")
    no_ev = sorted(leg for leg, r in status.items() if r["status"] != "inactive" and leg not in evidence)
    orphan = sorted((k, e["_path"]) for k, e in evidence.items() if k not in status)
    out += ["", f"**Active legs with NO evidence record** ({len(no_ev)}): "
            + (", ".join(f"`{x}`" for x in no_ev) or "none")
            + ". A leg without a committed record has no Stage-0 evidence on file — it is not a pass.", "",
            "**Evidence records naming no leg in `config/strategies.yaml`** (matched on the record's `strategy` "
            "field): " + (", ".join(f"`{p}` (`{k}`)" for k, p in orphan) or "none")
            + ". Each is a renamed leg (fix the record's `strategy` field) or a research record.", "",
            "**TP doctrine compliance** (`scripts/ci/check_tp_doctrine.py`):", "", "```", _tp_summary(root), "```"]
    return "\n".join(out)


# ── checks: the skeleton against the repo ───────────────────────────────────────────────
def gen_checks(root: Path, ctx: dict[str, Any]) -> str:
    skel = ctx.get("skeleton", "")
    closure = _closure(root)
    cited = sorted({m.group(1) for m in _PATH.finditer(skel)})
    vm_only = ("runtime_logs/",)
    missing, in_trader = [], 0
    checked = 0
    for p in cited:
        if "<" in p or p.startswith(vm_only) or not (root / p.split("/")[0]).is_dir():
            continue  # a repo slug, a git branch or a VM-only path is not a repo module
        checked += 1
        if not (root / p).exists():
            missing.append(p)
        elif closure is not None and p in closure:
            in_trader += 1
    acc, _ = _yaml(root, "config/accounts.yaml")
    strat, _ = _yaml(root, "config/strategies.yaml")
    accts = (acc or {}).get("accounts") or {}
    legs = (strat or {}).get("strategies") or {}
    rostered = {leg for c in accts.values() if isinstance(c, dict) for leg in (c.get("strategies") or [])}
    undefined = sorted(rostered - set(legs))
    unbooked = sorted(k for k, c in legs.items()
                      if isinstance(c, dict) and c.get("enabled") is not False and k not in rostered)
    warn = []
    if missing:
        warn.append(f"⚠️ **{len(missing)} skeleton path(s) no longer exist** — the skeleton is stale there: "
                    + ", ".join(f"`{p}`" for p in missing))
    if undefined:
        warn.append("⚠️ **Rostered legs with no definition in `config/strategies.yaml`**: "
                    + ", ".join(f"`{x}`" for x in undefined))
    if unbooked:
        warn.append("⚠️ **Enabled legs on no account roster** (they run nowhere): "
                    + ", ".join(f"`{x}`" for x in unbooked))
    head = (f"Checked {checked} module/config paths cited by the skeleton "
            f"({in_trader} of them are in the trader's import closure, `config/trader_import_closure.txt`"
            + ("" if closure is not None else f": {DASH}, closure file missing") + f"); {len(rostered)} rostered "
            f"legs against {len(legs)} defined legs.")
    return head + "\n\n" + ("\n\n".join(warn) if warn else "✅ No drift found: every cited path exists, every "
                            "rostered leg is defined, every enabled leg is on a book.")


GENERATORS: dict[str, Callable[[Path, dict[str, Any]], str]] = {
    "where": gen_where, "accounts": gen_accounts, "ml": gen_ml, "mandates": gen_mandates,
    "legs": gen_legs, "checks": gen_checks,
}


def build(root: Path = REPO, *, live: dict[str, Any] | None = None, live_state: str = "not read") -> str:
    """Assemble the map from the skeleton. Never raises on a bad source: that block reads "—"."""
    skel_path = root / SKELETON_REL
    skel = skel_path.read_text(encoding="utf-8")
    ctx: dict[str, Any] = {"live": live, "live_state": live_state, "skeleton": skel}
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        fn = GENERATORS.get(name)
        if fn is None:
            return f"_Unknown generated block `{name}`: {DASH}._"
        try:
            body = fn(root, ctx)
        except Exception as e:  # noqa: BLE001  # allow-silent: one bad source must not blank the map; the block states it
            body = f"_Block `{name}`: {DASH} (generator failed: {type(e).__name__}: {str(e)[:120]})._"
        return f"<!-- BEGIN GEN:{name} -->\n{body}\n<!-- END GEN:{name} -->"

    body = _MARK.sub(_sub, skel)
    banner = (f"> **Generated {stamp}** from `{SKELETON_REL}` by `src/runtime/pipeline_map.py`. Edit the skeleton, "
              "never this output; the generated blocks are rebuilt from their sources on every build.\n")
    lines = body.split("\n")
    # banner goes right after the title + doc-status header
    insert_at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("> **Doc status:**")), 1)
    lines[insert_at:insert_at] = ["", banner.rstrip()]
    return "\n".join(lines)


# ── structured payload (v2, lane PIPELINE-MAP-V2, 2026-11-15) ────────────────────────────────
# Operator, 2026-11-15: a straight vertical spine, technical elements LEFT, trading elements RIGHT,
# iteration loops on the side, every element openable. Steps, their text and the loops are PARSED from
# the same skeleton; the trading elements come from the same sources of truth as the markdown.
_STEP = re.compile(r"^## (\d+) · (.+)$", re.M)
_NODE = re.compile(r'\b([A-Z])\["(\d+) · ')
_LOOP = re.compile(r'^\s*([A-Z]) -\. "([^"]+)" \.-> ([A-Z])\s*$')
_BOLD = re.compile(r"\*\*([^*]+?)\*\*:?\s*")
_TICK = re.compile(r"`([^`]+)`")
# which sources of truth show up as TRADING elements at which step number
STEP_SOURCES: dict[int, tuple[str, ...]] = {3: ("legs", "ml"), 5: ("accounts",), 6: ("dd",), 9: ("mandates",)}


def _kind(tok: str) -> str:
    t = tok.split("::")[0]
    if t.startswith(("/api/", "GET /")):
        return "route"
    if t.endswith(".service") or t.startswith("ict-"):
        return "service"
    if t.endswith((".yaml", ".yml", ".json", ".jsonl", ".txt")):
        return "config"
    if t.endswith(".db"):
        return "store"
    if t.endswith((".py", ".sh")) or "/" in t:
        return "module"
    return ""


def _tech_elements(cell: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set = set()
    cur_dir = ""
    for m in _TICK.finditer(cell):
        tok = m.group(1).strip()
        if tok.endswith("/") and "/" in tok[:-1]:
            cur_dir = tok
        elif "/" not in tok and tok.endswith(".py") and cur_dir:
            tok = cur_dir + tok  # a bare module name listed under a directory token: resolve it
        kind = _kind(tok)
        if not kind or tok in seen or "<" in tok or (" " in tok and not tok.startswith("GET ")):
            continue
        seen.add(tok)
        i = m.start()
        lo = max(cell.rfind(". ", 0, i), cell.rfind("; ", 0, i), 0)
        hi = [x for x in (cell.find(". ", m.end()), cell.find("; ", m.end())) if x != -1]
        ctx = cell[lo:(min(hi) + 1) if hi else len(cell)].lstrip(".; ").strip()
        if len(ctx) > 260:
            ctx = "…" + ctx[max(0, i - lo - 110): i - lo + 150].strip() + "…"
        path = tok.split("::")[0]
        out.append({"id": f"t:{tok}", "kind": kind, "label": (path.rstrip("/").rsplit("/", 1)[-1] + ("/" if path.endswith("/") else "")) if kind == "module" else tok,
                    "sub": tok if kind == "module" else None,
                    "path": path if kind in ("module", "config") and "/" in path else None,
                    "text": ctx, "details": {}})
    return out


def _rule_elements(cell: str) -> list[dict[str, Any]]:
    parts = _BOLD.split(cell)
    out = []
    for i in range(1, len(parts) - 1, 2):
        text = re.sub(r"<!--.*?-->", "", parts[i + 1]).strip().rstrip(".")
        out.append({"id": f"r:{parts[i]}", "kind": "rule", "label": parts[i].strip(": "),
                    "sub": None, "text": text, "details": {}})
    return out


def _leg_elements(root: Path, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    from scripts.ops import strategy_status as ss
    status = ss.table(root)
    strategies = ss.load(root)[1]
    evidence = _evidence(root)
    live, read = ctx.get("live"), ctx.get("live_state") == "read"
    real, paper = _per_strategy(live), _per_strategy((live or {}).get("paper"))
    order = {"production": 0, "testing": 1, "inactive": 2}
    out = []
    for leg, row in sorted(status.items(), key=lambda kv: (order.get(kv[1]["status"], 9), kv[0])):
        ev = evidence.get(leg) or {}
        rule = ev.get("decision_rule") if isinstance(ev.get("decision_rule"), dict) else {}
        mod = f"src/units/strategies/{leg}.py"
        out.append({"id": f"leg:{leg}", "kind": "leg", "label": leg, "sub": row["status"], "state": row["status"],
                    "path": mod if (root / mod).is_file() else None, "text": None, "details": {
                        "status": row["status"], "books": ", ".join(row["books"]) or None,
                        "execution (gate 2)": (strategies.get(leg) or {}).get("execution"),
                        "backtest net R OOS": ev.get("net_r_oos"), "backtest n OOS": ev.get("n_trades_oos"),
                        "cost basis": _cost_basis(ev) if ev else None, "stage-0 verdict": rule.get("verdict"),
                        "evidence record": ev.get("_path"),
                        "live real money (R)": _live_cell(real.get(leg), read) if read else None,
                        "live paper (R)": _live_cell(paper.get(leg), read) if read else None}})
    return out


def _account_elements(root: Path, dd_only: bool = False) -> list[dict[str, Any]]:
    doc, _ = _yaml(root, "config/accounts.yaml")
    accts = (doc or {}).get("accounts") if isinstance(doc, dict) else None
    out = []
    for name, cfg in (accts or {}).items():
        if not isinstance(cfg, dict):
            continue
        rk = cfg.get("risk") if isinstance(cfg.get("risk"), dict) else {}
        dd = rk.get("daily_dd_switch") if isinstance(rk.get("daily_dd_switch"), dict) else {}
        armed = "armed" if dd.get("armed") is True else "disarmed"
        st = armed if dd_only else cfg.get("mode")
        out.append({"id": f"{'dd' if dd_only else 'acct'}:{name}", "kind": "account", "label": name, "sub": st,
                    "state": st, "text": None,
                    "details": {"class": cfg.get("account_class"), "exchange": cfg.get("exchange"),
                                "mode (gate 1)": cfg.get("mode"), "position model": cfg.get("position_model"),
                                "daily DD switch": armed, "legs on roster": len(cfg.get("strategies") or [])}})
    return out


def _ml_elements(root: Path) -> list[dict[str, Any]]:
    doc, _ = _yaml(root, "ml/served/SERVED_MODELS.yaml")
    models = (doc or {}).get("models") if isinstance(doc, dict) else None
    out = []
    for mid, m in (models or {}).items():
        m = m if isinstance(m, dict) else {}
        h = m.get("headline_metric") if isinstance(m.get("headline_metric"), dict) else {}
        out.append({"id": f"ml:{mid}", "kind": "model", "label": mid, "sub": m.get("stage"), "state": m.get("stage"),
                    "text": None, "details": {"stage": m.get("stage"), "metric": h.get("name"), "value": h.get("value"),
                                              "n": h.get("n"), "window": h.get("window"), "verdict": h.get("verdict"),
                                              "provenance": h.get("provenance"), "source": h.get("source")}})
    return out


def _mandate_elements(root: Path) -> list[dict[str, Any]]:
    doc, _ = _yaml(root, "config/mandates.yaml")
    granted = (doc or {}).get("mandates") if isinstance(doc, dict) else None
    out = []
    for m in granted or []:
        if isinstance(m, dict):
            out.append({"id": f"mandate:{m.get('id')}", "kind": "mandate", "label": str(m.get("id")),
                        "sub": m.get("kind"), "state": None, "text": m.get("grants"),
                        "details": {"kind": m.get("kind"), "granted": str(m.get("granted_at") or "")[:10] or None,
                                    "auto-land": "yes" if m.get("autoland") else None}})
    return out


def parse_skeleton(skel: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(steps, loops) from the skeleton: ``## N · Title`` sections holding a TECHNICAL | TRADING row, and the
    dashed edges of the mermaid flow (a node label ``N · Name`` ties a letter to a step number)."""
    nodes: dict[str, int] = {}
    loops: list[dict[str, Any]] = []
    for m in _NODE.finditer(skel):
        nodes[m.group(1)] = int(m.group(2))
    for ln in skel.splitlines():
        m = _LOOP.match(ln)
        if m and m.group(1) in nodes and m.group(3) in nodes:
            loops.append({"id": f"loop:{m.group(1)}{m.group(3)}:{len(loops)}", "label": m.group(2),
                          "from": f"step-{nodes[m.group(1)]}", "to": f"step-{nodes[m.group(3)]}"})
    heads = list(_STEP.finditer(skel))
    steps = []
    for i, h in enumerate(heads):
        body = skel[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(skel)]
        rows = [r for r in body.splitlines() if r.startswith("|") and not r.startswith(("| TECHNICAL", "|---"))]
        cells = re.split(r"(?<!\\)\|", rows[0].strip().strip("|")) if rows else []
        if len(cells) < 2:
            continue
        n = int(h.group(1))
        rules = _rule_elements(cells[1]) or [{"id": "r:note", "kind": "rule", "label": "How it works here", "sub": None,
                                              "text": re.sub(r"<!--.*?-->", "", cells[1]).strip(), "details": {}}]
        steps.append({"id": f"step-{n}", "n": n, "name": h.group(2).split(":")[0].strip(), "title": h.group(2).strip(),
                      "technical": _tech_elements(cells[0]), "trading": rules,
                      "technical_text": cells[0].strip(), "trading_text": cells[1].replace("\\|", "|").strip()})
    return steps, loops


def build_structured(root: Path = REPO, *, live: dict[str, Any] | None = None, live_state: str = "not read") -> dict[str, Any]:
    """The map as data: ordered steps (technical left, trading right) plus side loops. A bad source reads "—"."""
    steps, loops = parse_skeleton((root / SKELETON_REL).read_text(encoding="utf-8"))
    ctx: dict[str, Any] = {"live": live, "live_state": live_state}
    makers: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "legs": lambda: _leg_elements(root, ctx), "ml": lambda: _ml_elements(root),
        "accounts": lambda: _account_elements(root), "dd": lambda: _account_elements(root, dd_only=True),
        "mandates": lambda: _mandate_elements(root)}
    for st in steps:
        st["read_state"] = {}
        for src in STEP_SOURCES.get(st["n"], ()):
            try:
                els, st["read_state"][src] = makers[src](), "read"
            except Exception as e:  # noqa: BLE001  # allow-silent: not silent -- the step's read_state names the failure
                els, st["read_state"][src] = [], f"unreadable ({type(e).__name__})"
            st["trading"] += els
    return {"steps": steps, "loops": loops, "live_state": live_state}
