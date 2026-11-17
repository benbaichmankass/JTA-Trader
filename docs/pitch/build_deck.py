#!/usr/bin/env python3
"""Build the JTA Trader pitch deck (docs/pitch/jta-trader-pitch-deck.pptx) and its
markdown source / speaker notes (docs/pitch/jta-trader-pitch-deck.md).

Rows PROJECT-PITCH-DECK (v1, 2026-11-04) and PITCH-DECK-V2 (2026-11-17 refresh + docs/pitch/slides.json). Every number on a slide is COMPUTED here from a file on
disk at build time (config/strategies.yaml + scripts/ops/strategy_status.py,
config/accounts.yaml, config/mandates.yaml, config/values_exclusions.yaml,
comms/strategy_evidence/*.json, comms/live_review/reviews.jsonl, comms/ml_consolidation/*.json,
research/queue/*.yaml, scripts/ci/check_tp_doctrine.py) and carries a provenance tag (src/runtime/provenance.py
vocabulary: MEASURED / ESTIMATED). Re-run to refresh; never hand-edit numbers.

Shareability: the deck names no account ids, hosts, addresses, balances or dollar
amounts. Venue names (public companies) are the only proper nouns about brokers.

Run:  python3 docs/pitch/build_deck.py
"""
from __future__ import annotations

import collections
import datetime as _dt
import glob
import json
import os
import statistics
import subprocess
import sys

import yaml
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT_PPTX = os.path.join(ROOT, "docs", "pitch", "jta-trader-pitch-deck.pptx")
OUT_MD = os.path.join(ROOT, "docs", "pitch", "jta-trader-pitch-deck.md")
OUT_JSON = os.path.join(ROOT, "docs", "pitch", "slides.json")

# ----------------------------------------------------------------------------- data


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "unknown"


def load_facts() -> dict:
    f: dict = {}
    # Strategy statuses: derived, never declared (OPERATING-PLAN § 2).
    sys.path.insert(0, ROOT)
    out = subprocess.check_output([sys.executable, os.path.join(ROOT, "scripts/ops/strategy_status.py")],
                                  text=True, cwd=ROOT)
    st = collections.Counter()
    prod = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] in ("testing", "production", "inactive"):
            st[parts[0]] += 1
            if parts[0] == "production":
                prod.append(parts[1])
    f["status"] = st
    f["legs_total"] = sum(st.values())
    f["production_legs"] = sorted(prod)

    acc = yaml.safe_load(open(os.path.join(ROOT, "config/accounts.yaml")))["accounts"]
    f["accounts_total"] = len(acc)
    f["accounts_live_mode"] = sum(1 for v in acc.values() if v.get("mode") == "live")
    f["accounts_dry"] = sum(1 for v in acc.values() if v.get("mode") == "dry_run")
    f["prop_total"] = sum(1 for v in acc.values() if v.get("type") == "prop")
    f["prop_live"] = sum(1 for v in acc.values() if v.get("type") == "prop" and v.get("mode") == "live")
    f["venues"] = sorted({str(v.get("exchange")) for v in acc.values()})

    m = yaml.safe_load(open(os.path.join(ROOT, "config/mandates.yaml")))
    f["mandates_granted"] = len(m.get("mandates") or [])
    f["mandates_proposed"] = len(m.get("proposed") or [])

    # Research queue.
    q = collections.Counter()
    qv = collections.Counter()
    for p in glob.glob(os.path.join(ROOT, "research/queue/*.yaml")):
        try:
            d = yaml.load(open(p), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)) or {}
        except Exception:
            q["unparseable"] += 1
            continue
        q[d.get("status")] += 1
        if d.get("status") == "done":
            qv[str((d.get("grading") or {}).get("verdict")).lower()] += 1
    f["queue"] = q
    f["queue_verdicts"] = qv
    f["served"] = yaml.safe_load(open(os.path.join(ROOT, "ml/served/SERVED_MODELS.yaml")))["models"]
    f["queue_total"] = sum(q.values())
    f["queue_blocked"] = len(glob.glob(os.path.join(ROOT, "research/queue/blocked/*.yaml")))

    # Evidence corpus.
    recs = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "comms/strategy_evidence/*.json"))):
        recs[os.path.basename(p)[:-5]] = json.load(open(p))
    f["evidence_records"] = len(recs)
    cov = collections.Counter(d.get("coverage_state") for d in recs.values())
    f["coverage"] = cov
    meas = {k: d for k, d in recs.items() if d.get("coverage_state") == "measured"}
    f["measured_pass"] = sum(1 for d in meas.values() if (d.get("decision_rule") or {}).get("verdict") == "pass")
    f["measured_fail"] = sum(1 for d in meas.values() if (d.get("decision_rule") or {}).get("verdict") == "fail")
    fam = collections.defaultdict(list)
    for k, d in meas.items():
        h = str(d.get("harness"))
        # A record's harness field can carry a full run descriptor, e.g.
        # "ml_entry_tp_revision ... (on ml_decision_entry)"; group by the family it names.
        for known in ("ml_decision_entry", "event_oi_shock", "ml_entry_equity"):
            if known in h:
                h = known
        fam[h].append(d)
    f["families"] = {
        h: dict(records=len(v),
                passed=sum(1 for d in v if (d.get("decision_rule") or {}).get("verdict") == "pass"),
                median_exp=statistics.median(d["expectancy_r_oos"] for d in v),
                trades=sum(d["n_trades_oos"] for d in v))
        for h, v in fam.items()}
    rows = []
    for leg in f["production_legs"]:
        d = recs.get(leg)
        if not d or d.get("coverage_state") != "measured":
            rows.append(dict(leg=leg, missing=True))
            continue
        fd = d.get("fold_detail") or []
        start = (fd[0].get("start") if fd else None) or ""
        end = (fd[-1].get("end") if fd else None) or ""
        win = d.get("window") or []
        if not start and len(win) == 2:
            start, end = str(win[0]), str(win[1])
        fee_only = d.get("net_r_oos_fee_only")
        rows.append(dict(
            leg=leg, exp=d["expectancy_r_oos"], n=d["n_trades_oos"], net=d["net_r_oos"],
            folds_pos=d.get("folds_positive"), folds=d.get("folds"), basis=d.get("basis"),
            fidelity=d.get("fidelity"), maxdd=(d.get("path_stats") or {}).get("max_drawdown_r"),
            start=start[:7], end=end[:7], fee_only=fee_only,
            cost_cut=(1 - d["net_r_oos"] / fee_only) if fee_only else None,
            verdict=(d.get("decision_rule") or {}).get("verdict"),
            rule=(d.get("decision_rule") or {}).get("id")))
    f["prod_rows"] = rows
    cuts = [r["cost_cut"] for r in rows if not r.get("missing") and r["cost_cut"] is not None]
    f["cost_cut_min"], f["cost_cut_max"], f["cost_cut_n"] = min(cuts), max(cuts), len(cuts)
    slips = sorted({(d.get("cost_stack") or {}).get("slippage") for d in recs.values()
                    if (d.get("cost_stack") or {}).get("slippage") is not None})
    f["slippage_bps"] = slips
    f["scalp"] = f["families"].get("ict_scalp")

    # Real-money legs by venue (the production legs' real-money accounts).
    by_venue = collections.Counter()
    for leg in f["production_legs"]:
        venues = {str(v.get("exchange")) for v in acc.values()
                  if v.get("account_class") == "real_money" and leg in (v.get("strategies") or [])}
        for ven in venues:
            by_venue[ven] += 1
    f["prod_by_venue"] = by_venue

    # TP doctrine compliance (the guard itself, never a quoted count).
    tp = json.loads(subprocess.check_output([sys.executable, os.path.join(ROOT, "scripts/ci/check_tp_doctrine.py"),
                                             "--json"], text=True, cwd=ROOT))
    f["tp"] = tp["summary"]

    # Values exclusions (real money only).
    vx = yaml.safe_load(open(os.path.join(ROOT, "config/values_exclusions.yaml")))
    f["fossil_n"] = len(vx["fossil_fuels"]["symbols"])

    # Live-trade review record (append-only JSONL).
    lr = os.path.join(ROOT, "comms/live_review/reviews.jsonl")
    f["reviews_n"] = sum(1 for line in open(lr) if line.strip()) if os.path.exists(lr) else None
    # ML inventory by decision slot (dated snapshot; the live feed is /api/bot/ml/registry).
    mc = json.load(open(os.path.join(ROOT, "comms/ml_consolidation/2026-11-11.json")))
    slot_keep = collections.Counter(m["slot"] for m in mc["models"] if str(m.get("proposal", "")).startswith("KEEP (consumer)"))
    f["ml_inv"] = dict(as_of=str(mc.get("as_of"))[:10], total=len(mc["models"]), keep_consumer=slot_keep,
                       proposals=collections.Counter(str(m.get("proposal", "")).split(" ")[0] for m in mc["models"]))
    # Live real-money R per leg: the pipeline map's generated per-leg table, rebuilt now (journal via the API);
    # falls back to the committed snapshot docs/reference/trading-pipeline-map.md if the live build fails.
    md, src = None, "live: python3 scripts/ops/pipeline_map_numbers.py --stdout (GET /api/bot/performance?window=all)"
    try:
        md = subprocess.check_output([sys.executable, os.path.join(ROOT, "scripts/ops/pipeline_map_numbers.py"),
                                      "--stdout"], text=True, cwd=ROOT, timeout=150, stderr=subprocess.DEVNULL)
    except Exception:
        md = open(os.path.join(ROOT, "docs/reference/trading-pipeline-map.md")).read()
        src = "snapshot: docs/reference/trading-pipeline-map.md"
    live = {}
    _re = __import__("re")

    def _lv(c):
        m = _re.search(r"n=(\d+) · ΣR ([+-]?[0-9.]+) · E\[R\] ([+-]?[0-9.]+)", c)
        if not m:
            return None
        cf = _re.search(r"confirmed (\d+)", c)
        return dict(n=int(m.group(1)), sr=float(m.group(2)), er=float(m.group(3)), conf=int(cf.group(1)) if cf else 0)
    track = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 12 and cells[0].startswith("`"):
            leg = cells[0].strip("`")
            if (leg.startswith("ml_") or leg.endswith("_ml") or leg == "claude_desk" or "pair" in leg
                    or any(t["leg"] == leg for t in track)):
                continue
            bt = _re.search(r"([+-][0-9.]+)", cells[4])
            track.append(dict(leg=leg, status=cells[1], books=cells[2], bt=float(bt.group(1)) if bt else None,
                              bt_n=cells[5], bt_folds=cells[6], rm=_lv(cells[10]), paper=_lv(cells[11])))
    f["track"] = track
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 12 and cells[0].startswith("`") and cells[1] == "production":
            leg = cells[0].strip("`")
            m = __import__("re").search(r"n=(\d+).*?E\[R\] ([+-]?[0-9.]+)", cells[10])
            live[leg] = dict(n=int(m.group(1)), er=float(m.group(2))) if m else dict(n=0, er=None)
    f["live_rm"], f["live_rm_source"] = live, src
    f["sha"] = _git_sha()
    f["date"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    return f


PLAIN = {
    "ada_pullback_2h": "Cardano pullback (2-hour bars)",
    "iaum_pullback_1d": "Gold-ETF pullback (daily bars)",
    "ml_entry": "ML entry model (5 crypto coins, hourly)",
    "trend_donchian_eth_4h": "Ether trend breakout (4-hour bars)",
    "trend_donchian_sol_prop": "Solana trend breakout (hourly bars)",
    "trend_donchian_xrp_4h": "XRP trend breakout (4-hour bars)",
    "xrp_pullback_2h": "XRP pullback (2-hour bars)",
    "ml_entry_eq_struct": "ML entry model (US funds pool, hourly)",
    "slv_trend_1h": "Silver-ETF trend breakout (hourly bars)",
    "tlt_pullback_1h": "Long-bond-ETF pullback (hourly bars)",
    "tqqq_trend_long_1d": "Leveraged Nasdaq-ETF trend, long only (daily)",
    "trend_donchian_xrp_adx25": "XRP trend breakout, strong-trend filter (4-hour)",
}

FAMILY_PLAIN = {
    "trend": "Trend breakouts", "pullback": "Pullbacks in a trend", "ict_scalp": "Short-term scalps",
    "ml_decision_entry": "ML entry model (crypto)", "ml_entry_equity": "ML entry model (US funds)", "event_oi_shock": "Event: open-interest shock",
    "fade": "Fade a breakout", "fvg_range": "Price-gap range", "squeeze": "Volatility squeeze",
}

# ----------------------------------------------------------------------------- style

NAVY = RGBColor(0x12, 0x23, 0x3D)
TEAL = RGBColor(0x0F, 0x8B, 0x8D)
INK = RGBColor(0x22, 0x2B, 0x36)
GREY = RGBColor(0x6B, 0x75, 0x82)
LIGHT = RGBColor(0xF2, 0xF5, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
AMBER = RGBColor(0xB2, 0x6A, 0x00)
RED = RGBColor(0xB0, 0x3A, 0x2E)
FONT = "Calibri"

W, H = Inches(13.333), Inches(7.5)

# The trading pipeline map's eleven steps (docs/reference/trading-pipeline-map.skeleton.md § The flow): the deck's spine.
STAGES = ["Data in", "Signal builders", "Strategy legs and ML heads", "Intent layer", "Per-account routing",
          "RiskManager and sizing", "Order package + bracket", "Venue execution", "Live management",
          "Close and reconcile", "Grading, evidence, research"]
MAP_PNG = os.path.join(ROOT, "docs", "pitch", "pipeline_map.png")


class Deck:
    def __init__(self, facts):
        self.p = Presentation()
        self.p.slide_width, self.p.slide_height = W, H
        self.blank = self.p.slide_layouts[6]
        self.n = 0
        self.md: list[str] = []
        self.f = facts
        self.section = ""
        self.slides: list[dict] = []

    # -- slide records (docs/pitch/slides.json)
    def _rec(self, title, notes, kicker=None, tags=()):
        self.slides.append(dict(number=self.n, section=self.section or "Opening", title=title, kicker=kicker,
                                provenance=list(tags), bullets=[], notes=notes, numbers=[], sources=[]))

    def num(self, label, value, provenance, source, live_endpoint=None):
        """Register one number shown on the current slide, with where it comes from and what would refresh it."""
        self.slides[-1]["numbers"].append(dict(label=label, value=value, provenance=provenance, source=source,
                                                live_endpoint_candidate=live_endpoint))

    def cite(self, *paths):
        self.slides[-1]["sources"].extend(p for p in paths if p not in self.slides[-1]["sources"])

    def _b(self, text):
        if self.slides:
            self.slides[-1]["bullets"].append(text)

    # -- primitives
    def _text(self, slide, x, y, w, h, text, size=18, bold=False, color=INK, align=PP_ALIGN.LEFT,
              anchor=MSO_ANCHOR.TOP, font=FONT):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(0.05)
        lines = text if isinstance(text, list) else [text]
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = align
            r = para.add_run()
            r.text = line
            r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, font
        return tb

    def _box(self, slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE):
        s = slide.shapes.add_shape(shape, x, y, w, h)
        s.fill.solid()
        s.fill.fore_color.rgb = fill
        if line is None:
            s.line.fill.background()
        else:
            s.line.color.rgb = line
        s.shadow.inherit = False
        return s

    def _tag(self, slide, x, y, kind):
        color = GREEN if kind == "MEASURED" else AMBER
        b = self._box(slide, x, y, Inches(1.25), Inches(0.3), color, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        tf = b.text_frame
        tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = kind
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(11), True, WHITE, FONT

    def strip(self, s, stages, y=Inches(1.2)):
        """The compact pipeline strip: all eleven steps, the current ones highlighted."""
        gap = Inches(0.05)
        n_on = sum(1 for i in range(11) if (i + 1) in stages)
        off_w = Inches(0.42)
        on_w = (W - Inches(1.2) - gap * 10 - off_w * (11 - n_on)) / max(n_on, 1)
        x = Inches(0.6)
        for i, name in enumerate(STAGES):
            on = (i + 1) in stages
            bw = on_w if on else off_w
            b = self._box(s, x, y, bw, Inches(0.34), TEAL if on else LIGHT, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
            x += bw + gap
            tf = b.text_frame
            tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.CENTER
            r = para.add_run()
            r.text = f"{i + 1} · {name}" if on else str(i + 1)
            r.font.size, r.font.bold, r.font.name = Pt(9), on, FONT
            r.font.color.rgb = WHITE if on else GREY

    def new_at(self, stages, title, notes, **kw):
        return self.new(title, notes, stages=stages, **kw)

    def new(self, title, notes, kicker=None, tags=(), stages=()):
        self.n += 1
        s = self.p.slides.add_slide(self.blank)
        self._box(s, 0, 0, W, Inches(1.1), NAVY)
        self._box(s, 0, Inches(1.1), W, Inches(0.06), TEAL)
        self._text(s, Inches(0.6), Inches(0.18), Inches(11.0), Inches(0.8), title, size=28, bold=True,
                   color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
        if kicker and not stages:
            self._text(s, Inches(0.6), Inches(1.28), Inches(12.0), Inches(0.5), kicker, size=16,
                       color=TEAL, bold=True)
        for i, t in enumerate(tags):
            self._tag(s, W - Inches(0.6) - Inches(1.35) * (len(tags) - i), Inches(0.42), t)
        self._text(s, Inches(0.6), H - Inches(0.45), Inches(9), Inches(0.35),
                   f"JTA Trader · {self.section}" if self.section else "JTA Trader",
                   size=10, color=GREY)
        self._text(s, W - Inches(1.6), H - Inches(0.45), Inches(1.0), Inches(0.35), str(self.n),
                   size=10, color=GREY, align=PP_ALIGN.RIGHT)
        s.notes_slide.notes_text_frame.text = notes
        self.md.append(f"\n---\n\n## {self.n}. {title}\n")
        if kicker:
            self.md.append(f"*{kicker}*\n")
        if tags:
            self.md.append("Provenance: " + ", ".join(tags) + "\n")
        self._cur_notes = notes
        self._rec(title, notes, kicker, tags)
        if stages:
            self.strip(s, stages)
            self.slides[-1]["stages"] = list(stages)
            self.md.append("Pipeline stage(s): " + ", ".join(f"{i} {STAGES[i - 1]}" for i in stages) + "\n")
        return s

    def end_md(self):
        self.md.append(f"\n**Speaker notes.** {self._cur_notes}\n")

    def bullets(self, s, items, x=Inches(0.6), y=Inches(1.85), w=Inches(12.1), size=20, gap=10):
        tb = s.shapes.add_textbox(x, y, w, H - y - Inches(0.7))
        tf = tb.text_frame
        tf.word_wrap = True
        for i, it in enumerate(items):
            sub = isinstance(it, tuple)
            text = it[1] if sub else it
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(gap)
            r0 = p.add_run()
            r0.text = ("      – " if sub else "■  ")
            r0.font.size, r0.font.color.rgb, r0.font.name = Pt(size - (4 if sub else 6)), TEAL, FONT
            r = p.add_run()
            r.text = text
            r.font.size, r.font.color.rgb, r.font.name = Pt(size - (3 if sub else 0)), INK, FONT
            self.md.append(("  - " if sub else "- ") + text)
            self._b(("  – " if sub else "") + text)
        self.md.append("")
        return tb

    def cards(self, s, cards, y=Inches(1.9), h=Inches(4.25), cols=None, size=15, head=19, x0=None):
        cols = cols or len(cards)
        gap = Inches(0.25)
        x0 = x0 if x0 is not None else Inches(0.6)
        cw = (W - x0 - Inches(0.6) - gap * (cols - 1)) / cols
        for i, (head_txt, body) in enumerate(cards):
            r, c = divmod(i, cols)
            rows = (len(cards) + cols - 1) // cols
            ch = (h - gap * (rows - 1)) / rows
            x = x0 + (cw + gap) * c
            yy = y + (ch + gap) * r
            self._box(s, x, yy, cw, ch, LIGHT)
            self._box(s, x, yy, Inches(0.08), ch, TEAL)
            self._text(s, x + Inches(0.2), yy + Inches(0.12), cw - Inches(0.3), Inches(0.5), head_txt,
                       size=head, bold=True, color=NAVY)
            self._text(s, x + Inches(0.2), yy + Inches(0.62), cw - Inches(0.3), ch - Inches(0.7),
                       body if isinstance(body, list) else [body], size=size, color=INK)
            self.md.append(f"- **{head_txt}** — " + " ".join(body if isinstance(body, list) else [body]))
            self._b(f"{head_txt} — " + " ".join(body if isinstance(body, list) else [body]))
        self.md.append("")

    def flow(self, s, steps, y=Inches(2.2), h=Inches(1.6), size=14, sub=None):
        n = len(steps)
        gap = Inches(0.12)
        cw = (W - Inches(1.2) - gap * (n - 1)) / n
        for i in range(n):
            x = Inches(0.6) + (cw + gap) * i
            shp = self._box(s, x, y, cw, h, NAVY if i % 2 == 0 else TEAL, shape=MSO_SHAPE.CHEVRON
                            if i else MSO_SHAPE.PENTAGON)
            shp.adjustments[0] = 0.25
        for i, (head_txt, body) in enumerate(steps):
            x = Inches(0.6) + (cw + gap) * i
            self._text(s, x + Inches(0.42), y + Inches(0.1), cw - Inches(0.72), h - Inches(0.2),
                       [head_txt], size=size + 2, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE,
                       align=PP_ALIGN.CENTER)
            self._text(s, x, y + h + Inches(0.15), cw, Inches(2.3), body, size=size, color=INK,
                       align=PP_ALIGN.CENTER)
            self.md.append(f"{i + 1}. **{head_txt}** — " + " ".join(body if isinstance(body, list) else [body]))
            self._b(f"{i + 1}. {head_txt} — " + " ".join(body if isinstance(body, list) else [body]))
        self.md.append("")

    def table(self, s, header, rows, y=Inches(1.9), col_w=None, size=13, h_row=Inches(0.42)):
        ncol = len(header)
        tw = W - Inches(1.2)
        shape = s.shapes.add_table(len(rows) + 1, ncol, Inches(0.6), y, tw, h_row * (len(rows) + 1))
        t = shape.table
        if col_w:
            tot = sum(col_w)
            for i, cw in enumerate(col_w):
                t.columns[i].width = Emu(int(tw * cw / tot))
        for r_i, row in enumerate([header] + rows):
            t.rows[r_i].height = h_row
            for c_i, val in enumerate(row):
                cell = t.cell(r_i, c_i)
                cell.text = str(val)
                cell.margin_top = cell.margin_bottom = Inches(0.03)
                para = cell.text_frame.paragraphs[0]
                para.alignment = PP_ALIGN.LEFT if c_i == 0 else PP_ALIGN.CENTER
                for run in para.runs:
                    run.font.size = Pt(size)
                    run.font.name = FONT
                    run.font.bold = r_i == 0
                    run.font.color.rgb = WHITE if r_i == 0 else INK
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY if r_i == 0 else (LIGHT if r_i % 2 else WHITE)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        self.md.append("| " + " | ".join(header) + " |")
        self.md.append("|" + "---|" * ncol)
        for row in rows:
            self.md.append("| " + " | ".join(str(v) for v in row) + " |")
        if self.slides:
            self.slides[-1].setdefault("table", {"header": list(header), "rows": [[str(v) for v in r] for r in rows]})
        self.md.append("")

    def model_card(self, s, good, stats, nxt):
        """A 'model card': what makes it good (plain English) · headline stats (big number + bar) · what's next."""
        y0 = Inches(1.75)
        colw = Inches(3.9)
        # left: what makes it good
        self._box(s, Inches(0.6), y0, colw, Inches(4.75), LIGHT)
        self._text(s, Inches(0.75), y0 + Inches(0.1), colw - Inches(0.3), Inches(0.4), "Why it's good at its job",
                   size=15, bold=True, color=NAVY)
        self._text(s, Inches(0.75), y0 + Inches(0.55), colw - Inches(0.3), Inches(4.1), good, size=13, color=INK)
        # middle: stat tiles
        mx, mw = Inches(4.7), Inches(4.3)
        th = Inches(1.12)
        vmax = max([abs(t["r"]) for t in stats if t.get("r") is not None] or [1]) or 1
        for i, t in enumerate(stats):
            ty = y0 + (th + Inches(0.09)) * i
            self._box(s, mx, ty, mw, th, WHITE, line=LIGHT)
            self._text(s, mx + Inches(0.12), ty + Inches(0.02), Inches(1.9), Inches(0.6), t["big"], size=24, bold=True,
                       color=(RED if t.get("bad") else NAVY))
            self._text(s, mx + Inches(2.0), ty + Inches(0.06), mw - Inches(2.1), Inches(0.6), t["label"], size=10,
                       color=INK)
            self._text(s, mx + Inches(0.12), ty + Inches(0.72), mw - Inches(0.2), Inches(0.38),
                       f"{t['prov']} · {t['kind']} · {t['meta']}", size=8, color=GREY)
            if t.get("r") is not None:
                cx = mx + Inches(2.0) + Inches(1.1)
                ln = int(Inches(1.05) * min(1.0, abs(t["r"]) / vmax))
                if ln > 0:
                    self._box(s, cx if t["r"] >= 0 else cx - ln, ty + Inches(0.58), ln, Inches(0.1),
                              TEAL if t["r"] >= 0 else AMBER)
                self._box(s, cx, ty + Inches(0.52), Inches(0.015), Inches(0.22), GREY)
        # right: next
        rx = Inches(9.2)
        rw = W - rx - Inches(0.6)
        self._box(s, rx, y0, rw, Inches(4.75), LIGHT)
        self._text(s, rx + Inches(0.15), y0 + Inches(0.1), rw - Inches(0.3), Inches(0.4), "What's next",
                   size=15, bold=True, color=NAVY)
        self._text(s, rx + Inches(0.15), y0 + Inches(0.55), rw - Inches(0.3), Inches(4.1),
                   [f"→ {x}" for x in nxt], size=13, color=INK)
        self.slides[-1]["card"] = {"good": good, "stats": stats, "next": nxt}
        self.md.append("**Why it's good at its job.** " + " ".join(good) + "\n")
        self.md.append("| Stat | What | Provenance · kind · n / window |")
        self.md.append("|---|---|---|")
        for t in stats:
            self.md.append(f"| {t['big']} | {t['label']} | {t['prov']} · {t['kind']} · {t['meta']} |")
            self.slides[-1]["numbers"].append(dict(label=t["label"], value=t["big"], provenance=t["prov"],
                                                   source=t["source"], live_endpoint_candidate=t.get("live")))
        self.md.append("\n**What's next.** " + " ".join(f"→ {x}" for x in nxt) + "\n")
        for x in good + nxt:
            self._b(x)

    def footnote(self, s, text, y=None):
        self._text(s, Inches(0.6), y or (H - Inches(1.05)), Inches(12.1), Inches(0.55), text, size=12,
                   color=GREY)
        self.md.append(f"> {text}\n")
        if self.slides:
            self.slides[-1]["footnote"] = text


def pct(x):
    return f"{x * 100:.0f}%"


_STRATS = None


def plain_leg(leg):
    global _STRATS
    if leg in PLAIN:
        return PLAIN[leg]
    if _STRATS is None:
        d0 = yaml.safe_load(open(os.path.join(ROOT, "config/strategies.yaml")))
        _STRATS = d0.get("strategies", d0)
    cfg = _STRATS.get(leg) or {}
    syms = cfg.get("symbols") or ([cfg["symbol"]] if cfg.get("symbol") else [])
    tf = cfg.get("timeframe") or ""
    fam = ("Trend breakout" if "donchian" in leg else "ICT scalp" if "ict_scalp" in leg else
           "Pullback" if "pullback" in leg else "Trend" if "trend" in leg else None)
    if fam and len(syms) == 1:
        sym = str(syms[0]).replace("USDT", "")
        return f"{fam} · {sym} {tf}".strip() + (" (prop variant)" if leg.endswith("_prop") else "")
    t = leg.split("_")
    tf = next((x for x in t if x[:-1].isdigit() and x[-1] in "mhd"), "")
    words = {"trend": "trend", "donchian": "breakout", "pullback": "pullback", "ict": "ICT", "scalp": "scalp",
             "prop": "(prop variant)", "long": "long-only", "oi": "open-interest", "shock": "shock", "e4": "Event:"}
    out = [words.get(x, x.upper()) for x in t if x != tf]
    name = " ".join(out).replace("trend breakout", "trend breakout")
    return (name[0].upper() + name[1:] + (f" ({tf})" if tf else "")).replace("TREND", "Trend")


def build():
    f = load_facts()
    d = Deck(f)
    st = f["status"]
    cov = f["coverage"]
    q = f["queue"]
    qv = f["queue_verdicts"]
    sv = f["served"]
    rm = f["tp"]["by_class"]["real_money"]

    # ---------------------------------------------------------------- 1 title
    d.n += 1
    s = d.p.slides.add_slide(d.blank)
    d._box(s, 0, 0, W, H, NAVY)
    d._box(s, Inches(0.8), Inches(3.75), Inches(2.2), Inches(0.08), TEAL)
    d._text(s, Inches(0.8), Inches(1.6), Inches(11.5), Inches(1.2), "JTA Trader", size=54, bold=True, color=WHITE)
    d._text(s, Inches(0.8), Inches(2.55), Inches(11.8), Inches(1.2),
            "The edge comes from the research loop, not the plumbing", size=28, color=WHITE)
    d._text(s, Inches(0.8), Inches(4.0), Inches(11.5), Inches(1.4),
            ["How a trade flows · how the models keep getting better · what the research has produced",
             f"Project walkthrough · {f['date']}"], size=18, color=RGBColor(0xC8, 0xD3, 0xE0))
    d._text(s, Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.8),
            "Numbers are ratios only (R-multiples, percentages, counts) and each is tagged MEASURED or ESTIMATED. "
            "No dollar amounts or balances. Not investment advice.", size=12, color=RGBColor(0xC8, 0xD3, 0xE0))
    notes = ("Automated trading infrastructure is common; what is hard is finding an edge that survives costs and "
             "keeps surviving. This deck is about the research and development loop that produces that edge, "
             "especially on the machine-learning side, and about what it has produced so far. One slide covers how "
             "the system runs. Every number is either MEASURED, read straight from a committed file or result, or "
             "ESTIMATED, resting on an assumption, and the tag says which. R means one unit of risk: what a trade "
             "loses if its stop is hit.")
    s.notes_slide.notes_text_frame.text = notes
    d.md.append("## 1. JTA Trader — the edge comes from the research loop, not the plumbing\n\n"
                f"Project walkthrough · {f['date']}. Ratios only; each number tagged MEASURED or ESTIMATED; "
                "no dollar amounts. Not investment advice.\n")
    d._cur_notes = notes
    d._rec("JTA Trader — the edge comes from the research loop, not the plumbing", notes)
    d._b("The edge comes from the research loop, not the plumbing")
    d._b("How a trade flows · how the models keep getting better · what the research has produced")
    d._b(f"Project walkthrough · {f['date']}")
    d.num("build date", f["date"], "MEASURED", "docs/pitch/build_deck.py (build time, UTC)")
    d.end_md()

    # ---------------------------------------------------------------- 2 pipeline map
    d.section = "The trade pipeline"
    s = d.new("The trading pipeline",
              "This is the trading pipeline map we built and use on the Work tab, drawn from the same source. Every "
              "trade passes through these eleven steps. At step 3, two kinds of decision-makers run side by side: "
              "hand-designed rule strategies, such as trend breakouts, pullbacks in a trend and short-term scalps, "
              "each with its own backtest evidence; and machine-learning models that propose trades of their own. "
              "Both feed the same intent layer, risk manager, bracket and execution steps, so a model gets no "
              "shortcut around the risk controls. Step 11 grades every trade and test, and its two dashed arrows "
              "are the loop: new evidence changes which strategies run and with what settings, and retrained, "
              "promoted models go back in at step 3.")
    pic_h = H - Inches(1.45)
    pic = s.shapes.add_picture(MAP_PNG, Inches(0.6), Inches(1.3), height=pic_h)
    tx = Inches(0.6) + pic.width + Inches(0.5)
    d.slides[-1]["visual"] = "pipeline_image"
    d.slides[-1]["image"] = "docs/pitch/pipeline_map.png"
    d.slides[-1]["mermaid_source"] = "docs/reference/trading-pipeline-map.md § The flow"
    d.cards(s, [
        ("Step 3 runs two kinds of decision-makers", ["Rule strategies: trend breakouts, pullbacks, scalps and "
                                                      "others, each with its own backtest evidence.",
                                                      "ML models: learned entry models that propose trades too."]),
        ("Same path for both", ["Steps 4–10 treat them alike: intent layer, risk manager, stop and target, "
                                "execution, live management, reconciliation."]),
        ("The loop", ["Step 11 grades everything. New evidence changes rosters and settings; retrained models "
                      "re-enter at step 3."]),
    ], y=Inches(1.3), h=Inches(5.4), cols=1, size=14, head=16, x0=tx)
    fn = ("The map: docs/reference/trading-pipeline-map.md § The flow (mermaid source rendered verbatim; live at "
          "/api/bot/work/pipeline-map).")
    d._text(s, tx, H - Inches(0.75), W - tx - Inches(0.6), Inches(0.4), fn, size=11, color=GREY)
    d.md.append(f"> {fn}\n")
    d.slides[-1]["footnote"] = fn
    d.end_md()

    # ---------------------------------------------------------------- 3a first half of the pipeline (operator comment 2026-11-17)
    s = d.new_at((1, 2, 3, 4, 5, 6), "From data to a sized order: steps 1–6",
              "The first half of the map, from market data to an order that is ready to send. Data arrives from every "
              "venue. Each strategy computes its own inputs. At step 3, rule strategies and ML models propose trades "
              "side by side. The intent layer combines the proposals, steps aside where a strategy loses in the "
              "current market regime, and elects one trade per market. Routing decides which accounts carry the "
              "strategy, behind exactly two switches: account live or dry run, strategy live or shadow. The risk "
              f"manager then sizes the trade in R and applies the daily drawdown brake. Today {st['production']} "
              f"strategies trade real money and {st['testing']} trade on the demo floor; {f['accounts_live_mode']} of "
              f"{f['accounts_total']} accounts send orders.", tags=("MEASURED",))
    d.flow(s, [
        ("Data in", ["Candles, feeds and ML features from every venue."]),
        ("Signal builders", ["Each strategy computes its own inputs."]),
        ("Strategies + ML", ["Rule strategies and ML models propose trades."]),
        ("Intent layer", ["Combine; step aside in losing regimes; elect one."]),
        ("Routing", ["Which accounts; two on/off switches."]),
        ("Risk + sizing", ["Size in R; daily drawdown brake; exposure."]),
    ], size=12, h=Inches(1.25))
    d.num("production legs", st["production"], "MEASURED", "scripts/ops/strategy_status.py", "/api/bot/strategies")
    d.num("testing legs", st["testing"], "MEASURED", "scripts/ops/strategy_status.py", "/api/bot/strategies")
    d.num("accounts sending orders", f["accounts_live_mode"], "MEASURED", "config/accounts.yaml (mode: live)", "/api/bot/config")
    d.footnote(s, f"MEASURED: {st['production']} production and {st['testing']} testing legs (scripts/ops/strategy_status.py); "
                  f"{f['accounts_live_mode']} of {f['accounts_total']} accounts live (config/accounts.yaml). Steps from "
                  "docs/reference/trading-pipeline-map.md.", y=H - Inches(1.3))
    d.end_md()

    # ---------------------------------------------------------------- 3 trade management
    s = d.new_at((7, 8, 9, 10), "Trade management: entry, in-trade, exit",
              "The second half of the map, steps 7 to 10, where the trade is actually managed. At entry every order "
              "carries a protective stop, which defines 1R, and a profit target that must be a real prediction, "
              "not a placeholder set too far away to ever fill. In the trade, either bracket can move, or the "
              "position can be part-closed or closed, but only when something in the live market triggers it: "
              "structure, volatility, momentum, regime or a scheduled event. Never the profit alone, never the "
              "clock alone. A review function looks at every open trade, prices each option from that strategy's own "
              "backtest history, and since 14 November its recommended actions are applied automatically through "
              "each account's own risk checks, with a ping to the operator. At the exit the close reason is "
              "recorded and graded, and the grade feeds research. Honest status on targets: on real money "
              f"{rm['routings'] - rm['entry_fail']} of {rm['routings']} routings set a real target at entry, but only "
              f"{rm['routings'] - rm['revision_fail']} of {rm['routings']} revise it during the trade.",
              tags=("MEASURED",))
    d.flow(s, [
        ("Entry", ["Stop-loss defines 1R; profit target is a real prediction (the TP doctrine)."]),
        ("In-trade", ["Either bracket moves, part-close or close, triggered by live market evidence."]),
        ("Review desk", [f"Every open trade reviewed; options priced from the strategy's own history. "
                         f"{f['reviews_n']} reviews on record."]),
        ("Exit + grade", ["Close reason recorded, trade graded, grade becomes a training label."]),
    ], size=14, h=Inches(1.3))
    d.footnote(s, f"MEASURED: real-money target at entry {rm['routings'] - rm['entry_fail']} of {rm['routings']} "
                  f"routings, revised in-trade {rm['routings'] - rm['revision_fail']} of {rm['routings']} "
                  f"(scripts/ci/check_tp_doctrine.py); reviews: comms/live_review/reviews.jsonl. "
                  "Rules: docs/ARCHITECTURE-CANONICAL.md § TP doctrine, § Active management.", y=H - Inches(1.35))
    d.num("real-money routings with an entry target", f"{rm['routings'] - rm['entry_fail']} of {rm['routings']}", "MEASURED", "scripts/ci/check_tp_doctrine.py --json (summary.by_class.real_money)")
    d.num("real-money routings revising the target in-trade", f"{rm['routings'] - rm['revision_fail']} of {rm['routings']}", "MEASURED", "scripts/ci/check_tp_doctrine.py --json (summary.by_class.real_money)")
    d.num("live-trade reviews on record", f["reviews_n"], "MEASURED", "comms/live_review/reviews.jsonl (line count)")
    d.end_md()

    # ---------------------------------------------------------------- 4 R&D loop
    d.section = "How we find edge"
    s = d.new_at((11,), "The R&D loop: how a model earns, and keeps, its place",
              "This is the core of the project. Every strategy and every model sits in the same loop. Start from a "
              "diagnosis of why the current version is not better. Write down the test and its pass mark before "
              "running it. Run it on data held out from tuning, charged with the full cost of trading. Compare the "
              "challenger with the champion, the version in use, on the same trades and the same costs. Pass, and "
              "it goes straight to real money with a paper mirror. Fail, and the result is not thrown away: it "
              "becomes the next diagnosis. A live model whose mirror goes net-negative after costs drops back to the "
              "demo floor and keeps generating data while it is improved. Retirement needs evidence that no lever "
              "helps, never a fixed number of attempts.")
    d.flow(s, [
        ("Diagnose", ["Why is the champion not better? Name the lever: label, features, threshold, exit."]),
        ("Pre-register", ["Test, statistic and pass mark written down before the run."]),
        ("Test", ["Held-out data, full cost stack, challenger vs champion on the same trades."]),
        ("Decide", ["Pass → real money + mirror. Fail → back to Diagnose."]),
        ("Monitor", ["Mirror net-negative after costs → demo floor, keep iterating."]),
    ], size=13, h=Inches(1.3))
    d.footnote(s, "Rules: docs/plans/OPERATING-PLAN-2026-09-21.md § 2 (no step between a backtest pass and real money, "
                  "2026-11-12; the held-out pass governs real money) and § “What does not pass goes back into research”.",
               y=H - Inches(1.2))
    d.cite("docs/plans/ml-pipeline-design-2026-10-29.md (champion/challenger)")
    d.end_md()

    # ---------------------------------------------------------------- 5 worked example
    ex = sv.get("ml-entry-eq-struct-ens5-v1", {}).get("headline_metric", {})
    tlt = next((r for r in f["prod_rows"] if r["leg"] == "tlt_pullback_1h" and not r.get("missing")), None)
    s = d.new_at((3, 11), "Two real cycles: one ML model, one rule strategy",
              "Two worked examples of the loop from the last three weeks. On the left, the equity entry model: "
              "promoted on a strong held-out result, then a pre-registered test found its score mostly tracks how "
              "cheap a trade is relative to its risk, not direction, so the next challenger targets that. On the right, "
              "a rule strategy, the long-bond fund pullback: its one-year record failed because it traded too often "
              "for its small edge and costs ate it. Filters that cut trade frequency, chosen on early data and judged "
              "on held-back data, turned it positive; it was confirmed on older history it had never seen; the operator "
              "approved a long-only version with a real 3.5R target, and it went to real money on 14 November.",
              tags=("MEASURED",))
    d.cards(s, [
        ("Equity ML model (Foxhound-4)", [
            f"1 · Promoted: held-out {ex.get('value', 0):+.2f}R per trade, n {ex.get('n', '—')}.",
            "2 · Diagnosis: trades cluster in volatile months.",
            "3 · Test: does the score predict direction or cost? → cost (IC −0.53). FAIL.",
            "4 · Next: a cost-neutral training target, registered 17 Nov.",
        ]),
        ("Long-bond pullback (rule strategy)", [
            "1 · One-year record: −6.7R, n 94. FAIL: costs were 3.5× the gross edge.",
            "2 · Fix: fewer trades, chosen on early data; held-back read +4.5R, n 111. PASS.",
            "3 · Confirmed on unseen 2018–2020 history. PASS.",
            "4 · Long only, 3.5R target → real money 14 Nov" + (f"; record {tlt['net']:+.1f}R, n {tlt['n']}, "
                                                               f"{tlt['folds_pos']}/{tlt['folds']} folds +." if tlt else "."),
        ]),
    ], y=Inches(1.75), h=Inches(4.4), cols=2, size=14, head=17)
    d.num("Foxhound-4 held-out expectancy at promotion", round(ex.get("value", 0), 3), "MEASURED", "ml/served/SERVED_MODELS.yaml ml-entry-eq-struct-ens5-v1")
    d.num("Foxhound-4 score IC vs cost per R", -0.527, "MEASURED", "research/queue/RQ-20261111-207f-03.yaml grading.reason")
    d.num("TLT pullback one-year record (before)", -6.73, "MEASURED", "research/queue/RQ-20261101-78fc-56.yaml iteration.diagnosis")
    d.num("TLT pullback held-back read after the fix", 4.48, "MEASURED", "research/queue/RQ-20261112-c1b4-02.yaml iteration.diagnosis (from RQ-20261111-203c-02)")
    if tlt:
        d.num("TLT pullback promoted record net R", round(tlt["net"], 2), "MEASURED", "comms/strategy_evidence/tlt_pullback_1h.json")
    d.cite("research/queue/RQ-20261111-207f-03.yaml", "research/queue/RQ-20261117-c21d-06.yaml",
           "research/queue/RQ-20261101-78fc-56.yaml", "research/queue/RQ-20261111-203c-02.yaml",
           "research/queue/RQ-20261112-c1b4-02.yaml", "research/queue/RQ-20261114-db1a-14.yaml")
    d.footnote(s, "MEASURED: graded units 207f-03, c21d-06 (Foxhound-4); 78fc-56, 203c-02, c1b4-02, db1a-14 and "
                  "comms/strategy_evidence/tlt_pullback_1h.json (long-bond pullback). Every test was registered before "
                  "it ran, net of the full cost stack.", y=H - Inches(1.05))
    d.end_md()

    # ---------------------------------------------------------------- 10 strategies track record
    tr = f["track"]
    agg = {}
    for book in ("rm", "paper"):
        xs = [t[book] for t in tr if t[book]]
        n = sum(x["n"] for x in xs)
        sr = sum(x["sr"] for x in xs)
        agg[book] = dict(n=n, sr=sr, er=(sr / n if n else None), conf=sum(x["conf"] for x in xs),
                         legs=len(xs), pos=sum(1 for x in xs if x["sr"] > 0))
    # Operator comments 2026-11-17 16:54Z / 16:57Z ("these are the only strategies with positive records? That can't
    # be"): every rule strategy with a net-positive live record on ANY book (real money or demo/paper).
    entries = []
    for t in tr:
        for book, key in (("real money", "rm"), ("demo", "paper")):
            if t[key] and t[key]["sr"] > 0:
                entries.append((t, book, t[key]))
    # Operator comment 2026-11-17 17:04Z: "lead with the live money R positive ones, then paper".
    entries.sort(key=lambda e: (e[1] != "real money", -e[2]["sr"]))
    n_pos = len({e[0]["leg"] for e in entries})
    _names = collections.Counter(plain_leg(t["leg"]) for t in {e[0]["leg"]: e[0] for e in entries}.values())

    def nm(leg):
        n0 = plain_leg(leg)
        return f"{n0} [{leg}]" if _names[n0] > 1 else n0
    ra, pa = agg["rm"], agg["paper"]
    s = d.new_at((3,), "What our strategies have delivered",
              "The track record of the rule-based strategies, the part of the system that has run long enough to "
              "have one; the ML models are too new and are judged on their offline evidence. The table shows only "
              "strategies with a positive live record, on any book. For context, if asked: "
              f"across all {len(tr)} rule strategies, all-time realized results are negative, "
              f"{ra['sr']:+.1f}R over {ra['n']} real-money trades and {pa['sr']:+.1f}R over {pa['n']} demo trades. "
              "That total includes strategies that have since failed their backtests and been taken off real money, "
              "which is the ladder working. The table shows the production strategies with a positive actual record, "
              "and the Interactive Brokers paper strategies with a positive record, with their backtest beside them. Only a minority of live trades have their result "
              "confirmed against the venue, shown as a small tag.", tags=("MEASURED",))
    rows = []
    for t, book, x in entries[:8]:
        bt = (f"{t['bt']:+.1f}R · n {t['bt_n']} · {t['bt_folds']} folds +" if t["bt"] is not None else "no record yet")
        rows.append([f"{nm(t['leg'])} · {t['status']}", book,
                     f"{x['sr']:+.2f}R · n {x['n']} · E[R] {x['er']:+.2f} · {x['conf']} of {x['n']} confirmed", bt])
    for t, book, x in entries:
        d.num(f"live {book} ΣR: {t['leg']}", x["sr"], "MEASURED", f["live_rm_source"], "/api/bot/performance?window=all")
    d._text(s, Inches(0.6), Inches(1.65), Inches(12), Inches(0.5),
            f"{n_pos} rule strategies are net positive live", size=22, bold=True, color=TEAL)
    d.md.append(f"**{n_pos} rule strategies are net positive live.**\n")
    d.slides[-1]["headline"] = f"{n_pos} rule strategies are net positive live"
    d.num("rule strategies net positive live (any book)", n_pos, "MEASURED", f["live_rm_source"], "/api/bot/performance?window=all")
    d.table(s, ["Strategy", "Book", "Live result (actual)", "Backtest (net R, out of sample)"],
            rows, y=Inches(2.3), col_w=[3.7, 1.4, 4.4, 2.5], size=12, h_row=Inches(0.42))
    rest = entries[8:]
    if rest:
        line = "Also net positive: " + " · ".join(f"{nm(t['leg'])} ({book}) {x['sr']:+.1f}R" for t, book, x in rest)
        d._text(s, Inches(0.6), Inches(2.3) + Inches(0.42) * 9 + Inches(0.08), Inches(12.1), Inches(0.9), line,
                size=10, color=GREY)
        d.md.append(f"> {line}\n")
        d.slides[-1]["rest_line"] = line
    d.num("rule strategies, real money all-time ΣR", round(ra["sr"], 1), "MEASURED", f["live_rm_source"], "/api/bot/performance?window=all")
    d.num("rule strategies, demo all-time ΣR", round(pa["sr"], 1), "MEASURED", f["live_rm_source"], "/api/bot/performance?window=all")
    d.slides[-1]["track_record"] = dict(aggregate=agg, as_of=f["date"], source=f["live_rm_source"])
    d.footnote(s, f"Live results are real but small samples; edge is established offline, live checks it holds. "
                  f"MEASURED, journal all-time to {f['date']} (pipeline-map per-leg table); backtests "
                  "comms/strategy_evidence/. ML legs and the AI desk excluded.", y=H - Inches(0.85))
    d.end_md()

    # ---------------------------------------------------------------- 6 ML families on the map
    d.section = "The ML families"
    s = d.new_at((3, 4, 6, 7, 9), "The model families, placed on the map",
              "Each family sits on the step where it decides. Most are gradient-boosted decision trees: many "
              "small trees added together, each correcting the last; they suit tabular market data and retrain "
              "fast. The filter is a deliberately simple logistic regression. Three decisions have no model yet "
              "and run on rules, which we state rather than hide. The ML models have only been live a short time, "
              "so their story is the R&D process and the offline evidence; the rule strategies carry the live "
              "track record.", tags=("MEASURED",))
    d.table(s, ["Step", "Family · slot", "Model type", "Decides", "Where it stands"], [
        ["3 Strategies", "Foxhound · D3", "Gradient-boosted trees", "Open long, short or nothing", "Real money"],
        ["4 Intent layer", "Collie · D2", "Gradient-boosted classifier", "Which market regime", "Advisory on paper"],
        ["4 Intent layer", "Beagle · D4", "Logistic regression", "Take or halve a signal", "Live on 2 legs"],
        ["6 Risk", "Mastiff · D5", "None yet", "Combine signals on one market", "Research only"],
        ["7 Order", "Pointer · D6", "None yet", "Stop and target at entry", "Rule today"],
        ["9 Live mgmt", "Labrador · D7", "Gradient-boosted classifier", "Extend the target", "Live on ML trades"],
        ["9 Live mgmt", "Labrador · D8", "Close/hold head", "Close now?", "Demo floor"],
        ["11 Grade", "Basset · D10", "CUSUM baseline", "Is a strategy fading?", "Baseline tested"],
    ], col_w=[2.0, 2.2, 2.8, 3.2, 2.2], size=12, h_row=Inches(0.48))
    d.cite("docs/reference/model_names.yaml", "ml/served/SERVED_MODELS.yaml", "ml/served/*/model.json",
           "ml/overlay/overlay_td.json", "ml/configs/btc-regime-15m-lgbm-fc-pcv-v2.yaml",
           "research/queue/RQ-20261117-aadc-05.yaml")
    d.footnote(s, "The ML models have only been live a short time: judge them on the R&D process and offline evidence. "
                  "MEASURED from model artifacts (ml/served, ml/candidates, ml/overlay, ml/configs) and "
                  "ml/served/SERVED_MODELS.yaml. The D8 exit head's artifact lives on the trainer; its type is not "
                  "verified here.", y=H - Inches(0.95))
    d.end_md()

    # ---------------------------------------------------------------- 7 Foxhound card
    e1 = sv.get("ml-decision-entry-v1", {}).get("headline_metric", {})
    e4 = sv.get("ml-entry-eq-struct-ens5-v1", {}).get("headline_metric", {})
    rf = sv.get("ml-decision-entry-v1r20261106", {}).get("headline_metric", {})
    s = d.new_at((3,), "Model card · Foxhound, the entry model (step 3)",
              "Foxhound answers the first question of every trade: is there one worth taking right now? Think of a "
              "scout that has studied hundreds of thousands of past situations and only signals when the odds after "
              "costs look good; most of the time it says nothing. The crypto version trades real money on its "
              "held-out result. The equity version showed a much larger held-out result, but our own follow-up found "
              "it mostly picks trades that are cheap to make relative to their risk, so the next challenger targets "
              "that. A broader test on 51 coins at each coin's own costs failed, which is why it trades only the "
              "five it passed on.", tags=("MEASURED",))
    d.model_card(s, [
        "It scans every market every four hours and asks one question: after costs, would a standard trade here "
        "pay? If not, it stays out.",
        "Like a scout who has studied 660,000 past situations, it learns patterns in how prices move, not rules "
        "someone wrote down.",
        "It is judged only on data it never saw while learning.",
    ], [
        dict(big=f"{e1.get('value', 0):+.3f}R", r=e1.get("value"), label="Crypto model, average result per trade",
             prov="MEASURED", kind="offline, held-out", meta=f"n {e1.get('n')} · 2025-10 → 2026-09",
             source="ml/served/SERVED_MODELS.yaml ml-decision-entry-v1"),
        dict(big=f"{e4.get('value', 0):+.2f}R", r=e4.get("value"), label="Equity model, per trade (mostly a cost effect)",
             prov="MEASURED", kind="offline, held-out", meta=f"n {e4.get('n')} · 2025-07 → 2026-10",
             source="ml/served/SERVED_MODELS.yaml ml-entry-eq-struct-ens5-v1"),
        dict(big=f"{rf.get('value', 0):+.4f}R", r=rf.get("value"), label="Refit vs old model (−0.092R) on recent weeks",
             prov="MEASURED", kind="offline, 14-day grade", meta=f"n {rf.get('n')} · 2026-10-23 → 11-05",
             source="ml/served/SERVED_MODELS.yaml ml-decision-entry-v1r20261106"),
        dict(big="−0.068R", r=-0.068, bad=True, label="Wider test, 51 coins at own costs: FAIL",
             prov="MEASURED", kind="offline, held-out", meta="n 12,746 decisions · year to 2026-10",
             source="research/results/RQ-20261112-2e3b-01/43302779170.jsonl (measurement.pooled.mean_net_r)"),
    ], [
        "Test a stricter trigger on the held-out year: it won on development data (6 of 8 periods).",
        "Retrain the equity model so it predicts direction, not just cheapness to trade.",
        "Widen to new coins only where each coin's own costs still leave a profit.",
    ])
    d.end_md()

    # ---------------------------------------------------------------- 8 Beagle card
    ov = sv.get("overlay-td-v1", {}).get("headline_metric", {})
    inv = f["ml_inv"]
    s = d.new_at((4,), "Model card · Beagle, the signal filter (step 4)",
              "Beagle sits between a strategy's signal and the order. It does not veto; it turns the volume down on "
              "signals that look weak, halving their size, on two trend strategies. It is deliberately simple, a "
              "logistic regression on nine inputs, because simple models are harder to fool themselves with. It "
              "passed a test that it does no harm across 1,830 historical trades. Its first challenger did not "
              "beat it, so the next one has to disagree with it more often to be worth testing. The regime family, "
              "Collie, also sits at this step; an inventory on 11 November proposed retiring most of its unused "
              "models.", tags=("MEASURED",))
    d.model_card(s, [
        "A second opinion on every trend signal: if the setup looks weak, it halves the bet instead of refusing it.",
        "Like a volume knob, not an off switch, so a wrong call costs little.",
        "Nine plain inputs (trend strength, volatility, distance from average), kept simple on purpose.",
    ], [
        dict(big=str(ov.get("verdict", "—")).upper(), r=None, label="No-harm test vs taking every signal",
             prov="MEASURED", kind="offline, out-of-sample", meta=f"n {ov.get('n')} trades · 2020-07 → 2026-10",
             source="ml/served/SERVED_MODELS.yaml overlay-td-v1"),
        dict(big="2 legs", r=None, label="Live: halves size on weak signals",
             prov="MEASURED", kind="live, mechanics only", meta="config/overlay_policy.yaml",
             source="ml/served/SERVED_MODELS.yaml overlay-td-v1.stage_basis"),
        dict(big="NOT A WIN", r=None, bad=True, label="First challenger vs Beagle",
             prov="MEASURED", kind="offline", meta="graded indeterminate · 2026-11-16",
             source="research/queue/RQ-20261116-cc86-01.yaml grading"),
    ], [
        "Build a challenger that disagrees with Beagle more often: new inputs or a profit target, not a new cutoff.",
        "A live side-by-side read of the challenger runs in the background until enough disagreements pile up.",
        f"Regime models: keep only those that beat a simple baseline ({inv['proposals']['RETIRE']} of "
        f"{inv['total']} proposed for retirement).",
    ])
    d.end_md()

    # ---------------------------------------------------------------- 9 Labrador card
    tpr = sv.get("ml-entry-tp-revision-v1", {}).get("headline_metric", {})
    xh = sv.get("exit-head-donchian-1h-v1", {}).get("headline_metric", {})
    s = d.new_at((7, 9), "Model card · Labrador, the in-trade manager (steps 7 and 9)",
              "Labrador manages a trade that is already open. At five check-ins it re-estimates how far the trade is "
              "likely to run and can only move the target further out, never closer, so it cannot cut a winner "
              "short. Its registered forward test passed and its live gain is small but positive. Its sibling, the "
              "exit head, decides whether to close now; it failed out of sample on two of three markets and only "
              "acts on the demo floor. A new training label for it showed a small gain that missed the pass bar, "
              "and the next version is queued.", tags=("MEASURED",))
    d.model_card(s, [
        "Once a trade is open, it re-checks five times where the price is likely to get to.",
        "Like a navigator who only extends the destination when the road ahead is clear, never shortens it.",
        "So it can add profit on strong trades without ever cutting a winner short.",
    ], [
        dict(big="+0.0081R", r=0.0081, label="Registered forward test, per trade: PASS",
             prov="MEASURED", kind="offline, forward", meta="n 868 · Oct 2026",
             source="research/results/RQ-20261101-383f-01/local-20261101T1030Z.jsonl (via ml/served/SERVED_MODELS.yaml)"),
        dict(big=f"{tpr.get('value', 0):+.4f}R", r=tpr.get("value"), label="Live policy (extend only), per trade",
             prov="MEASURED", kind="offline replay", meta=f"n {tpr.get('n')} · 2025-10 → 2026-09",
             source="ml/served/SERVED_MODELS.yaml ml-entry-tp-revision-v1"),
        dict(big=f"{xh.get('value', 0):+.4f}R", r=xh.get("value"), bad=True, label="Exit head (close now?): FAIL",
             prov="MEASURED", kind="offline, out-of-sample", meta=f"n {xh.get('n')} · 3 folds 2022–2026",
             source="ml/served/SERVED_MODELS.yaml exit-head-donchian-1h-v1"),
    ], [
        "Re-check it once 300 live trades have closed since 12 November.",
        "Test checking in on market events, not only on a timer.",
        "Exit head: confirm a new training label (+0.007R per trade, just under the bar) on a wider margin.",
    ])
    d.end_md()

    # ---------------------------------------------------------------- 11 Basset card
    d.section = "What the R&D has produced"
    s = d.new_at((11,), "Model card · Basset, the early-warning light (step 11)",
              "The newest family, and an honest one to show. Basset's job is to spot a strategy that is starting to "
              "fade before the losses pile up. The first baseline is a classic statistical alarm, a CUSUM: it adds up "
              "how far each strategy's live results fall short of its backtest and rings when the shortfall builds "
              "up. It works as a warning, better than chance in its test window. But stopping strategies when it "
              "rang did not hold up on a fresh window of data, so it stays a warning light and does not act. Both "
              "results are recorded, which is exactly how the loop is meant to work.", tags=("MEASURED",))
    d.model_card(s, [
        "It watches every strategy's results against what its backtest promised, trade by trade.",
        "Like a smoke detector: small shortfalls add up, and when they build past a line it rings.",
        "Today it is a warning light, not an automatic switch, because the switch failed a fresh test.",
    ], [
        dict(big="0.654", r=None, label="Spots a fading strategy (0.5 = coin flip): PASS",
             prov="MEASURED", kind="offline, in-window", meta="AUC · n 664 points · 24 strategies",
             source="research/queue/RQ-20261117-aadc-05.yaml grading.reason"),
        dict(big="PASS", r=None, label="Stopping on the alarm beat random stops, in-window",
             prov="MEASURED", kind="offline, in-window", meta="p 0.0115 · 654 skipped trades",
             source="research/queue/RQ-20261117-aadc-07.yaml grading.reason"),
        dict(big="FAIL", r=None, bad=True, label="Same rule on a fresh window: did not replicate",
             prov="MEASURED", kind="offline, fresh window", meta="p 0.994 · 620 skipped · before 2026-05",
             source="research/queue/RQ-20261117-aadc-09.yaml grading.reason"),
    ], [
        "Keep the alarm as a warning in reviews; it does not switch anything off.",
        "Redesign the action before retesting, on data it has never seen.",
        "Find out why AI grades of past trades ran opposite to their results before using them as a signal.",
    ])
    d.end_md()

    # ---------------------------------------------------------------- 12 throughput
    decisive = qv["pass"] + qv["fail"]
    s = d.new_at((11,), "Produced so far 2 — research throughput, and how much fails",
              f"The volume behind the results. The research queue has {q['done']} completed questions. Of the graded "
              f"ones, {qv['pass']} passed their pre-registered rule and {qv['fail']} failed, with {qv['indeterminate']} "
              f"indeterminate because the sample was too small to call. That is a pass rate of "
              f"{pct(qv['pass'] / decisive)} on decisive results. Strategy evidence tells the same story: of "
              f"{cov['measured']} measured backtests, {f['measured_pass']} passed. The short-term scalp family passed "
              f"{(f['scalp'] or {}).get('passed', 0)} of its {(f['scalp'] or {}).get('records', 0)} tests and is not on "
              f"real money. Most ideas fail, and the system is built so that "
              f"they fail cheaply, offline, before any money is at risk.", tags=("MEASURED",))
    sc = f["scalp"] or {}
    d.cards(s, [
        (f"{q['done']} questions done", [f"{qv['pass']} passed · {qv['fail']} failed · {qv['indeterminate']} indeterminate.",
                                        f"{pct(qv['pass'] / decisive)} pass rate on decisive results."]),
        (f"{cov['measured']} strategy backtests", [f"{f['measured_pass']} passed, {f['measured_fail']} failed, after the "
                                                 "full cost stack.", f"Scalps: {sc.get('passed', 0)} of "
                                                 f"{sc.get('records', 0)} passed."]),
        (f"{q['queued']} questions queued", ["Each written down with its data, test and pass mark before it runs.",
                                            "A dispatcher runs them on cloud runners."]),
    ], size=15, h=Inches(3.3))
    d.num("research questions done", q["done"], "MEASURED", "research/queue/*.yaml (status: done)", "/api/bot/research/catalog")
    d.num("graded pass / fail / indeterminate", f"{qv['pass']} / {qv['fail']} / {qv['indeterminate']}", "MEASURED", "research/queue/*.yaml (grading.verdict, status done)", "/api/bot/research/catalog")
    d.num("pass rate on decisive results", pct(qv["pass"] / decisive), "MEASURED", "research/queue/*.yaml (grading.verdict)", "/api/bot/research/catalog")
    d.num("questions queued", q["queued"], "MEASURED", "research/queue/*.yaml (status: queued)", "/api/bot/research/catalog")
    d.num("measured strategy backtests passed", f"{f['measured_pass']} of {cov['measured']}", "MEASURED", "comms/strategy_evidence/*.json (decision_rule.verdict)")
    d.footnote(s, f"MEASURED: research/queue/*.yaml (status + grading.verdict; {qv['none']} done units carry no verdict); "
                  f"comms/strategy_evidence/*.json. Commit {f['sha']}.", y=H - Inches(1.1))
    d.end_md()

    # ---------------------------------------------------------------- 13 how it runs
    d.section = "How it runs"
    s = d.new_at((1, 2, 5, 8, 10), "How it runs automatically, in one slide",
              f"The infrastructure, briefly. The trader runs around the clock on cloud servers, on crypto, US funds "
              f"and futures venues, plus prop-firm accounts. {f['accounts_live_mode']} of {f['accounts_total']} "
              f"accounts are switched on to send orders. Exactly two switches decide whether something trades: one "
              f"per account, one per strategy. It never switches itself off: failures are contained to one trade or "
              f"job and retried. Day to day, AI agent sessions run the research, reviews and bookkeeping under "
              f"{f['mandates_granted']} standing mandates the operator has granted; agents may propose a mandate, "
              f"only the operator grants one. Real money excludes fossil-fuel funds by the operator's policy.",
              tags=("MEASURED",))
    d.cards(s, [
        ("Venues", ["Crypto perpetual futures, US funds and futures, and prop-firm accounts. "
                    f"{f['accounts_live_mode']} of {f['accounts_total']} accounts sending orders."]),
        ("Two switches", ["Account: live or dry run. Strategy: live or shadow. No hidden third switch; "
                          "never self-halts."]),
        ("Run by agents", [f"AI agent sessions do the research and reviews; {f['mandates_granted']} operator-granted "
                           "mandates let evidence-backed decisions proceed."]),
    ], size=15, h=Inches(3.0))
    d.num("accounts sending orders", f["accounts_live_mode"], "MEASURED", "config/accounts.yaml (mode: live)", "/api/bot/config")
    d.num("accounts configured", f["accounts_total"], "MEASURED", "config/accounts.yaml", "/api/bot/config")
    d.num("mandates granted", f["mandates_granted"], "MEASURED", "config/mandates.yaml (mandates)")
    d.footnote(s, "MEASURED: config/accounts.yaml, config/mandates.yaml; rules docs/CLAUDE-RULES-CANONICAL.md § Prime "
                  "Directive, CLAUDE.md § The two execution gates; config/values_exclusions.yaml.", y=H - Inches(1.3))
    d.end_md()

    # ---------------------------------------------------------------- 14 roadmap
    d.section = "Where it goes next"
    s = d.new_at((3, 4, 6, 7, 8, 9, 11), "Roadmap: the next ML milestone at each decision",
              "Where the loop goes next, decision by decision. The entry model's next challenger tests a "
              "cost-neutral target. The regime family is being pruned to the heads that beat their baseline. The "
              "empty slots each have a first question: predicted brackets at entry, combining several signals on one "
              "market, cheaper order placement, and whether a learned review of closed trades detects a fading "
              "strategy earlier than a simple statistical alarm. Alongside: more ML in the live loops, the trading "
              "desk made production-ready, and more labelled outcomes, which are the binding constraint. The deck "
              "ends here: no request, just the plan.")
    d.table(s, ["Slot", "Next milestone"], [
        ["D3 Entry", "Cost-neutral training target vs the live recipe (registered 2026-11-17)"],
        ["D2 Regime", "Keep only heads that beat their baseline; retire the rest"],
        ["D4 Filter / D7–D8", "Extend proven in-trade actions; retest the exit head per market"],
        ["D6 Bracket", "Does a predicted stop and target beat each strategy's fixed bracket?"],
        ["D5 Aggregate", "Offline research: combine several signals on one market"],
        ["D9 Execution", "Cut realised trading cost against today's order types"],
        ["D10 Review", "Does a learned grade spot a fading strategy earlier than a CUSUM alarm on R?"],
        ["Across slots", "ML in the live loops · trading desk V1 · more labelled outcomes"],
    ], col_w=[2.6, 9.4], size=14, h_row=Inches(0.46))
    d.cite("docs/roadmap/milestones.yaml (G4: L-ML-LIVE, L-ML-MECE, L-REGIME, L-DESK-V1, L-DATA, L-ML-AGGREGATOR)",
           "docs/plans/ML-ROADMAP-MECE-2026-11.md § 2–3", "docs/plans/ML-CONSOLIDATION-2026-11-11.md")
    d.footnote(s, "Source: ROADMAP.md live block (docs/roadmap/milestones.yaml, goal G4) and the ML plan's slot "
                  "questions (docs/plans/ML-ROADMAP-MECE-2026-11.md § 2).", y=H - Inches(1.1))
    d.end_md()

    # ---------------------------------------------------------------- 16 ML infrastructure roadmap (operator comment 17:13Z)
    s = d.new_at((1, 11), "ML infrastructure roadmap",
              "The operator asked what comes next for the ML infrastructure and for building more powerful models. "
              "Left, the infrastructure being built and what each piece unlocks; every item is a filed build or a "
              "queued research unit. Right, how the models get more powerful. The lesson so far is that labels and "
              "new information, not computing power, are the binding constraint: a sequence model lost to gradient-"
              "boosted trees on regime, and a tabular foundation model only tied. So GPU time is pointed at the "
              "questions with a diagnosis behind them, once their data is published where the GPU can read it.")
    d.cards(s, [
        ("Infrastructure we're building", [
            "1 · Entry and exit data published as GPU datasets → the diagnosed entry and exit questions can run on GPU.",
            "2 · Pooled reads across a strategy family → bigger samples in every test.",
            "3 · Live results as a column in the promotion packet → live evidence feeds the ladder (after the 18 Nov reset).",
            "4 · A benchmark for in-trade check-ins → test acting on market events, not only a timer.",
            "5 · A new teacher label for the review student model → the first AI grade ran opposite to results.",
        ]),
        ("How we'll get more powerful models", [
            "1 · More and better labels: the binding constraint on every model.",
            "2 · New information, not more price data: a news-layer veto and prediction-market surprises.",
            "3 · New model families, tested fairly: a sequence model lost and a tabular foundation model tied; next tries run on GPU.",
            "4 · Regime-transition research: spotting when markets change state.",
            "5 · Faster iteration: every ML test runs the same registered-rule pipeline as strategy tests.",
        ]),
    ], y=Inches(1.75), h=Inches(4.6), cols=2, size=13, head=17)
    d.cite("PI-20261117-ZQKSKUGH-0001 (Kaggle GPU datasets)", "PI-20261117-NIVCJP7T-0007 (pooled cells)",
           "PI-20261117-LSFHBH4A-0007 (live-performance promotion path, post-reset)",
           "research/queue/RQ-20261117-c21d-04.yaml (check-in cadence)", "CJ-LABEL-ALTERNATIVE (student teacher label)",
           "PI-20261117-LSFHBH4A-0004 (regime-transition research)", "ROADMAP.md § AI trader (ML) — build plan (tracks D, N, F)")
    d.footnote(s, "Sources: work-store items PI-20261117-ZQKSKUGH-0001, -NIVCJP7T-0007, -LSFHBH4A-0007, -LSFHBH4A-0004, "
                  "CJ-LABEL-ALTERNATIVE; unit RQ-20261117-c21d-04; ROADMAP.md § AI trader (ML) build plan. Dates only "
                  "where a plan states one.", y=H - Inches(0.95))
    d.end_md()

    d.p.save(OUT_PPTX)
    header = ("# JTA Trader — pitch deck: markdown source and speaker notes\n\n"
              f"> **Doc status:** `live` · category `unknown` · last verified `{f['date']}` · registered in "
              "[`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)\n\n"
              "Generated by [`build_deck.py`](build_deck.py) together with "
              "[`jta-trader-pitch-deck.pptx`](jta-trader-pitch-deck.pptx) and [`slides.json`](slides.json) "
              "(rows `PROJECT-PITCH-DECK`, `PITCH-DECK-V2`). "
              "Do not hand-edit: change the builder and re-run `python3 docs/pitch/build_deck.py`. "
              f"Built from commit `{f['sha']}` on {f['date']}; {d.n} slides.\n\n"
              "Audience: a smart non-expert. Numbers: ratios only (R, %, counts), each tagged MEASURED or "
              "ESTIMATED; no dollar amounts, balances, account ids, hosts or addresses.\n")
    with open(OUT_MD, "w") as fh:
        fh.write(header + "\n".join(d.md) + "\n")
    for sl in d.slides:
        # A slide is live-refreshable when every number on it is recomputable from a script or file at build time
        # (all are) AND at least one has a read-only API endpoint that could feed it without a rebuild.
        sl["live_refreshable"] = any(n.get("live_endpoint_candidate") for n in sl["numbers"])
    doc = dict(
        schema="jta-pitch-slides/v1",
        built_from_commit=f["sha"], built_on=f["date"], slide_count=len(d.slides),
        spec=dict(audience="smart non-expert", numbers="ratios only, no $, each tagged MEASURED or ESTIMATED",
                  length="deep dive, 20+ slides", close="roadmap, no ask"),
        refresh="python3 docs/pitch/build_deck.py (recomputes every number from the files named in `source`)",
        note=("live_endpoint_candidate names a read-only API route that serves the same underlying data; a UI that "
              "wires it must verify the field it reads matches `source` before showing the number."),
        slides=d.slides)
    assert [sl["number"] for sl in d.slides] == list(range(1, d.n + 1)), "slide records out of step with the deck"
    with open(OUT_JSON, "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False, default=str)
        fh.write("\n")
    print(f"wrote {OUT_PPTX} ({d.n} slides), {OUT_MD} and {OUT_JSON}")


if __name__ == "__main__":
    build()
