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
    for p in glob.glob(os.path.join(ROOT, "research/queue/*.yaml")):
        try:
            d = yaml.safe_load(open(p)) or {}
        except Exception:
            q["unparseable"] += 1
            continue
        q[d.get("status")] += 1
    f["queue"] = q
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

    def new(self, title, notes, kicker=None, tags=()):
        self.n += 1
        s = self.p.slides.add_slide(self.blank)
        self._box(s, 0, 0, W, Inches(1.1), NAVY)
        self._box(s, 0, Inches(1.1), W, Inches(0.06), TEAL)
        self._text(s, Inches(0.6), Inches(0.18), Inches(11.0), Inches(0.8), title, size=28, bold=True,
                   color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
        if kicker:
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

    def cards(self, s, cards, y=Inches(1.9), h=Inches(4.25), cols=None, size=15, head=19):
        cols = cols or len(cards)
        gap = Inches(0.25)
        cw = (W - Inches(1.2) - gap * (cols - 1)) / cols
        for i, (head_txt, body) in enumerate(cards):
            r, c = divmod(i, cols)
            rows = (len(cards) + cols - 1) // cols
            ch = (h - gap * (rows - 1)) / rows
            x = Inches(0.6) + (cw + gap) * c
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

    def footnote(self, s, text, y=None):
        self._text(s, Inches(0.6), y or (H - Inches(1.05)), Inches(12.1), Inches(0.55), text, size=12,
                   color=GREY)
        self.md.append(f"> {text}\n")
        if self.slides:
            self.slides[-1]["footnote"] = text


def pct(x):
    return f"{x * 100:.0f}%"


def build():
    f = load_facts()
    d = Deck(f)
    st = f["status"]

    # ---------------------------------------------------------------- 1 title
    d.n += 1
    s = d.p.slides.add_slide(d.blank)
    d._box(s, 0, 0, W, H, NAVY)
    d._box(s, Inches(0.8), Inches(3.55), Inches(2.2), Inches(0.08), TEAL)
    d._text(s, Inches(0.8), Inches(1.8), Inches(11.5), Inches(1.2), "JTA Trader", size=54, bold=True, color=WHITE)
    d._text(s, Inches(0.8), Inches(2.75), Inches(11.5), Inches(0.8),
            "An automated trading system that only trusts what it can prove", size=26, color=WHITE)
    d._text(s, Inches(0.8), Inches(3.9), Inches(11.5), Inches(1.4),
            ["What it is · how it works · how it keeps improving · where it goes next",
             f"Project walkthrough · {f['date']}"], size=18, color=RGBColor(0xC8, 0xD3, 0xE0))
    d._text(s, Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.8),
            "Numbers in this deck are ratios only (R-multiples, percentages, counts) and each is tagged "
            "MEASURED or ESTIMATED. No dollar amounts or balances. Not investment advice.",
            size=12, color=RGBColor(0xC8, 0xD3, 0xE0))
    notes = ("Welcome. This deck walks through the whole project for someone smart who does not trade for a living. "
             "The main section is plain language; the appendix has the technical detail. Every number is either "
             "MEASURED (read straight from a file or a backtest result) or ESTIMATED (rests on an assumption), "
             "and the tag on the slide says which.")
    s.notes_slide.notes_text_frame.text = notes
    d.md.append(f"## 1. JTA Trader — an automated trading system that only trusts what it can prove\n\n"
                f"Project walkthrough · {f['date']}. Ratios only; each number tagged MEASURED or ESTIMATED; "
                "no dollar amounts. Not investment advice.\n")
    d._cur_notes = notes
    d._rec("JTA Trader — an automated trading system that only trusts what it can prove", notes)
    d._b("An automated trading system that only trusts what it can prove")
    d._b("What it is · how it works · how it keeps improving · where it goes next")
    d._b(f"Project walkthrough · {f['date']}")
    d.num("build date", f["date"], "MEASURED", "docs/pitch/build_deck.py (build time, UTC)")
    d.end_md()

    # ---------------------------------------------------------------- PART 1
    d.section = "The idea"
    s = d.new("The one-minute version",
              "Three sentences to remember. It trades automatically. It tests ideas on history, with full costs, "
              "before risking money. And it keeps learning, because every trade and every test feeds the next "
              "round of research. The rest of the deck explains each of these.")
    d.cards(s, [
        ("It trades by itself", ["Many small, rule-based strategies run around the clock on crypto, US "
                                 "exchange-traded funds and futures. Each trade has a stop-loss and a profit "
                                 "target from the moment it opens."]),
        ("It proves before it risks", ["A strategy reaches real money only after a historical test, charged "
                                       "with realistic trading costs, clears a pass mark that was written "
                                       "down before the test was run. Then it goes straight to real money."]),
        ("It keeps learning", ["Failures go back into research, not the bin. AI agent sessions run the "
                               "research, the reviews and the bookkeeping. A human operator sets strategy "
                               "and risk policy."]),
    ], size=17, h=Inches(3.4))
    d.end_md()

    s = d.new("How to read the numbers in this deck",
              "Two ideas make every later slide readable. First, R. We never quote money; we quote how many "
              "units of risk a trade made or lost. Second, the tags. A MEASURED number was read directly from a "
              "result file. An ESTIMATED number depends on an assumption, for example how much worse than "
              "expected our fills are.")
    d.cards(s, [
        ("R = one unit of risk", ["Before a trade opens, it gets a stop-loss. The money lost if the stop is "
                                  "hit is 1R.", "A trade that makes +2R made twice what it risked. One "
                                  "that hits its stop is −1R.", "R lets us compare strategies of any size "
                                  "without quoting money."]),
        ("Expectancy", ["The average R per trade. +0.20R means that, on average, each trade earned a fifth "
                        "of what it risked, after costs.", "Small positive expectancy, repeated over "
                        "many trades, is what an edge looks like."]),
        ("The two tags", ["MEASURED: read straight from a backtest result or a config file.",
                          "ESTIMATED: depends on an assumption (e.g. an allowance for slippage).",
                          "If we could not verify a number, it is not in the deck."]),
    ], size=16)
    d.end_md()

    s = d.new("The problem: most trading ideas do not survive contact with costs",
              "This is the core problem the project is built around. Lots of ideas look good on a chart. Most "
              "of them stop working once you charge fees and slippage, or once you test on data the idea was "
              "not tuned on. People also fool themselves: they pick the pass mark after seeing the result. "
              "The system is designed to make those mistakes hard to make.")
    d.bullets(s, [
        "An idea that looks profitable on a chart is often an illusion. Three things usually kill it:",
        (1, "Costs: exchange fees, slippage (getting a worse price than expected) and funding charges."),
        (1, "Overfitting: rules tuned so tightly to the past that they describe noise, not a pattern."),
        (1, "Moving the goalposts: deciding what counts as success after seeing the result."),
        "Running a live book well is also hard: positions must be protected 24/7, and every close must "
        "be explained.",
        "JTA Trader's answer is to make discipline mechanical: the rules are code and records, not willpower.",
    ])
    d.end_md()

    s = d.new("What JTA Trader is",
              f"Concrete shape. The counts here were re-read from the configuration files on the day this deck "
              f"was built ({f['date']}, repo commit {f['sha']}). {f['legs_total']} strategy legs are configured; "
              f"{f['accounts_total']} trading accounts are configured, {f['accounts_live_mode']} of them switched "
              f"to send orders. Paper accounts trade with simulated money at the broker; real-money accounts "
              f"trade the operator's capital; prop-firm accounts trade a firm's capital under the firm's rules.",
              tags=("MEASURED",))
    d.cards(s, [
        (f"{f['legs_total']} strategy legs", ["A leg is one strategy on one market and timeframe, e.g. "
                                              "“Ether trend breakout on 4-hour bars”."]),
        (f"{f['accounts_total']} accounts", [f"{f['accounts_live_mode']} switched on to send orders, "
                                             f"{f['accounts_dry']} in dry run (they log what they would do, "
                                             "but send nothing)."]),
        ("3 kinds of book", ["Paper (simulated money at the broker), real money, and prop-firm "
                             "evaluation accounts (the firm's capital, the firm's rules)."]),
        ("Always on", ["Runs 24/7 on cloud servers. It never switches itself off; problems are "
                       "handled trade by trade."]),
    ], cols=2, size=16)
    d.num("strategy legs", f["legs_total"], "MEASURED", "scripts/ops/strategy_status.py over config/strategies.yaml + config/accounts.yaml", "/api/bot/strategies")
    d.num("accounts configured", f["accounts_total"], "MEASURED", "config/accounts.yaml", "/api/bot/config")
    d.num("accounts sending orders", f["accounts_live_mode"], "MEASURED", "config/accounts.yaml (mode: live)", "/api/bot/config")
    d.num("accounts in dry run", f["accounts_dry"], "MEASURED", "config/accounts.yaml (mode: dry_run)", "/api/bot/config")
    d.footnote(s, f"MEASURED: config/strategies.yaml (via scripts/ops/strategy_status.py) and config/accounts.yaml, "
                  f"commit {f['sha']}, {f['date']}. Population: every leg / account in those files.")
    d.end_md()

    s = d.new("Markets and venues",
              "Where the system trades. Crypto runs on Bybit as perpetual futures. US exchange-traded funds "
              "run on Alpaca. Futures and some ETFs run on Interactive Brokers. An OANDA forex practice account "
              "exists but is in dry run. Prop-firm accounts trade through the firms' own platforms.",
              tags=("MEASURED",))
    d.cards(s, [
        ("Crypto", ["Bitcoin, Ether, Solana, XRP, Cardano, Avalanche and others, as perpetual futures on "
                    f"Bybit. Paper, real-money and mirror accounts. {f['prod_by_venue'].get('bybit', 0)} legs "
                    "trade real money here."]),
        ("US funds (ETFs)", ["Broad index, bond, gold, silver and leveraged funds on Alpaca. Paper, real money, "
                             f"mirror and an options paper account. {f['prod_by_venue'].get('alpaca', 0)} legs "
                             "trade real money here."]),
        ("Futures", ["Micro index and metals futures on Interactive Brokers, on paper. A real-money account "
                     "exists in dry run with no strategies yet."]),
        ("Prop firms", [f"{f['prop_total']} prop-firm accounts are configured; {f['prop_live']} are switched on. "
                        "They must clear a stricter bar than real money."]),
    ], cols=2, size=16)
    d.num("real-money legs on Bybit", f["prod_by_venue"].get("bybit", 0), "MEASURED", "config/accounts.yaml (account_class real_money) × strategy_status.py production", "/api/bot/config")
    d.num("real-money legs on Alpaca", f["prod_by_venue"].get("alpaca", 0), "MEASURED", "config/accounts.yaml (account_class real_money) × strategy_status.py production", "/api/bot/config")
    d.num("prop accounts configured", f["prop_total"], "MEASURED", "config/accounts.yaml (type: prop)", "/api/bot/config")
    d.num("prop accounts switched on", f["prop_live"], "MEASURED", "config/accounts.yaml (type: prop, mode: live)", "/api/bot/config")
    d.footnote(s, f"MEASURED: config/accounts.yaml, {f['accounts_total']} accounts, commit {f['sha']}.")
    d.end_md()

    s = d.new("The strategy families, in plain words",
              "No single clever trick. A portfolio of simple, well-understood rule families, each tested "
              "separately on each market. The point is breadth plus honest testing, not secrecy.")
    d.cards(s, [
        ("Trend breakouts", ["Buy when price breaks above its recent range, sell when it breaks below. "
                             "Catches big moves; loses small often."]),
        ("Pullbacks", ["In an established trend, wait for a dip, then enter in the trend's direction."]),
        ("Short-term scalps", ["Quick trades on 5- and 15-minute bars around specific price patterns."]),
        ("Volatility & fades", ["Trade the break-out after a quiet squeeze, or bet a false break-out "
                                "reverses."]),
        ("Pairs & macro", ["Trade two related coins against each other; a slower, thesis-driven sleeve "
                           "built from valuation and economic events."]),
        ("Machine learning & AI desk", ["A learned model that picks entries; an AI trading desk that "
                                        "reviews open trades and proposes changes."]),
    ], cols=3, size=15, head=18)
    d.end_md()

    # ---------------------------------------------------------------- PART 2
    d.section = "How it works"
    s = d.new("The life of a trade",
              "Every trade follows the same path. Market data arrives. Strategies check their rules. If a rule "
              "fires, the risk manager decides whether this account may take it and how big it is. The order goes "
              "out with a stop and a target already attached. While it is open, management may move the "
              "brackets. When it closes, the reason is recorded and the trade is graded.")
    d.flow(s, [
        ("Data", ["Prices arrive from each broker connection, every bar, every market."]),
        ("Signal", ["Each strategy checks its own rules on its own markets."]),
        ("Risk check", ["Per-account limits decide yes/no and the size, in R."]),
        ("Order", ["Sent with a stop-loss and a profit target already attached."]),
        ("Manage", ["Brackets can move, but only on evidence."]),
        ("Close & grade", ["Exit reason recorded; trade graded and fed back to research."]),
    ], size=14)
    d.end_md()

    tp = f["tp"]["by_class"]
    rm = tp["real_money"]
    s = d.new("Every trade carries a real stop and a real target",
              "A rule the operator set: no fictional take-profits. Many systems put a target so far away it "
              "never triggers, which is a way of not having one. Here, each strategy's target must be a real "
              "prediction of where price is going, and the prediction should keep moving with the trade. A script "
              "measures compliance on every routing of a strategy to an account. Honest status: on real money, "
              f"{rm['routings'] - rm['entry_fail']} of {rm['routings']} routings set a real target at entry, but only "
              f"{rm['routings'] - rm['revision_fail']} of {rm['routings']} also revise it during the trade. That gap is "
              "open work, and the checker only lets the list of exceptions shrink.",
              tags=("MEASURED",))
    d.cards(s, [
        ("Stop-loss from the start", ["Every order rests at the broker with a protective stop. That stop "
                                      "defines 1R."]),
        ("A real profit target", ["The target is a prediction, not a placeholder. A target set so far away "
                                  "it can never fill counts as no target, and a checker flags it."]),
        ("Real money today", [f"Target at entry: {rm['routings'] - rm['entry_fail']} of {rm['routings']} routings.",
                              f"Target revised in the trade: {rm['routings'] - rm['revision_fail']} of "
                              f"{rm['routings']}. Closing this gap is on the roadmap."]),
    ], size=16, h=Inches(3.0))
    d.num("real-money routings with an entry target", f"{rm['routings'] - rm['entry_fail']} of {rm['routings']}", "MEASURED", "scripts/ci/check_tp_doctrine.py --json (summary.by_class.real_money)")
    d.num("real-money routings revising the target in-trade", f"{rm['routings'] - rm['revision_fail']} of {rm['routings']}", "MEASURED", "scripts/ci/check_tp_doctrine.py --json (summary.by_class.real_money)")
    d.footnote(s, f"MEASURED: scripts/ci/check_tp_doctrine.py, {f['tp']['routings']} routings over every account in "
                  f"config/accounts.yaml, commit {f['sha']}. A routing is one strategy on one account.",
               y=H - Inches(1.6))
    d.end_md()

    s = d.new("Active management: either bracket can move, on market evidence",
              "Once a trade is open, the system may move the stop or the target, or close part or all of the "
              "position. The trigger must be something in the live market: structure, volatility, momentum, regime, "
              "a scheduled event. Never the trade's profit alone and never the clock alone. Both brackets always "
              "stay in place. Since 14 November, every action a reviewed recommendation names is applied through "
              "each account's own risk manager, and the operator gets a ping for each change. Each kind of action "
              "is still graded separately against a risk-adjusted, cost-aware rule.")
    d.cards(s, [
        ("The whole bracket", ["Stop: tighten, widen or move to a structure level. Target: extend, pull in or "
                               "re-estimate. Position: partial or full close. Or hold, which is recorded too."]),
        ("Market-triggered", ["Structure, volatility, momentum, regime, scheduled events or liquidity levels. "
                              "Never P&L alone; never the clock alone."]),
        ("Applied, then graded", ["Reviewed actions are applied through each account's own risk checks, with a "
                                  "ping per change. Each action class is graded on its own rule: a small cost "
                                  "for a material cut in risk, holding across time and beating chance."]),
    ], size=15, h=Inches(3.4))
    d.cite("docs/ARCHITECTURE-CANONICAL.md § Active management")
    d.end_md()

    s = d.new("Risk controls that never switch the system off",
              "Risk is handled per trade, not by switching the whole system off. There are exactly two switches "
              "that decide whether something trades: one per account, one per strategy. The one sanctioned "
              "brake is a daily drawdown switch per account: once a day's loss reaches a set level, existing "
              "positions keep their stops and targets but no new trades open until the reset.")
    d.cards(s, [
        ("Sizing in R", ["Each account risks a fixed fraction per trade, so one loss is always a known, "
                         "small amount."]),
        ("Two switches only", ["Account: live or dry run. Strategy: live or shadow. There is no "
                               "hidden third switch."]),
        ("Daily drawdown brake", ["Per account, when armed: past a day's loss limit, open trades stay "
                                  "protected and new ones are blocked until the reset."]),
        ("Never self-halts", ["Failures are contained to the one trade or job and retried; persistent "
                              "problems raise a flag to the operator while the system keeps going."]),
    ], cols=2, size=16)
    d.end_md()

    # ---------------------------------------------------------------- PART 3
    d.section = "How we decide what trades"
    s = d.new("Backtesting, explained simply",
              "A backtest replays history and asks: if we had followed this rule, what would have happened? "
              "The trap is that you can always find a rule that worked in the past. So three protections: "
              "charge the full cost of trading; judge only on data the rule was not tuned on, split into several "
              "separate time periods called folds; and write down the pass mark before running the test.")
    d.flow(s, [
        ("Replay history", ["Run the exact rule over past prices, trade by trade."]),
        ("Charge full costs", ["Fees, plus allowances for slippage and funding."]),
        ("Test out of sample", ["Score it on time periods it was not tuned on, split into folds."]),
        ("Pass mark first", ["The rule for passing is registered before the run, never after."]),
    ], size=15, h=Inches(1.5))
    d.footnote(s, "The current pass mark for most legs: out-of-sample net R, after the full cost stack, must be "
                  "above zero (rule RULE-D1-STAGE0-NET-OF-FULL-COST, registered 2026-09-22).", y=H - Inches(1.3))
    d.end_md()

    s = d.new("The promotion ladder: a backtest pass goes straight to real money",
              "This is how an idea becomes a real-money strategy. Stage 0 decides whether there is an edge, "
              "offline, on history, net of the full cost stack. Since 12 November there is no step in between: a "
              "strategy that passes Stage 0 goes straight to real money, with a paper mirror that copies it "
              "exactly. The first live trades are watched as a mechanical check, never as a gate. The demo floor, "
              "Stage 1, is where every strategy that has not passed yet trades on paper to generate data, and "
              "where a demoted strategy goes back to keep generating data while it is improved. If the mirror "
              "turns net-negative after costs over its window, the strategy is demoted to the floor.")
    y = Inches(1.9)
    bw, bh, gap = Inches(3.6), Inches(3.2), Inches(0.55)
    stages = [
        ("STAGE 0 · Backtest", "Is there an edge, net of all costs?",
         "Passes only by clearing a pass mark registered before the run, on held-out data.", NAVY),
        ("STAGE 2 · Real money", "Live, with a paper mirror",
         "Entered directly on a Stage-0 pass. The mirror net-negative after costs → demoted.", GREEN),
        ("STAGE 1 · Demo floor", "Paper trading, for data",
         "Home of every testing leg, and of demoted legs while they are iterated on.", TEAL),
    ]
    for i, (h1, q, body, col) in enumerate(stages):
        x = Inches(0.6) + (bw + gap) * i
        d._box(s, x, y, bw, bh, col, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        d._text(s, x + Inches(0.2), y + Inches(0.2), bw - Inches(0.4), Inches(0.6), h1, size=19, bold=True,
                color=WHITE)
        d._text(s, x + Inches(0.2), y + Inches(0.9), bw - Inches(0.4), Inches(0.9), q, size=18, color=WHITE)
        d._text(s, x + Inches(0.2), y + Inches(1.8), bw - Inches(0.4), Inches(1.3), body, size=15, color=WHITE)
        if i < 2:
            d._box(s, x + bw + Inches(0.07), y + bh / 2 - Inches(0.25), Inches(0.42), Inches(0.5), GREY,
                   shape=MSO_SHAPE.RIGHT_ARROW)
        d.md.append(f"- **{h1}** — {q}. {body}")
        d._b(f"{h1} — {q}. {body}")
    d.md.append("")
    d.footnote(s, "No soak step between a backtest pass and real money (operator, 2026-11-12). A paper or live record "
                  "never proves an edge; it checks mechanics and cost.", y=H - Inches(1.6))
    d.cite("docs/plans/OPERATING-PLAN-2026-09-21.md § 2")
    d.end_md()

    s = d.new("What “pass” means for real money",
              "Two clarifications on the pass mark. First, real money is governed by a held-out test: the chosen "
              "configuration must clear its registered rule on data it never saw during tuning, net of the full "
              "cost stack, written into a committed evidence record. Second, a stricter statistic, the deflated "
              "Sharpe ratio, which corrects for how many variants were tried, is reported on every promotion but "
              "does not block it. A live strategy below its bar is on probation: it keeps an open research unit "
              "whose goal is a version that clears it.")
    d.cards(s, [
        ("Held-out data decides", ["The chosen configuration must pass its pre-registered rule on data it was "
                                   "not tuned on, after fees, slippage and funding."]),
        ("A committed record", ["The result is written by a script into an evidence record in the repository. "
                                "A claim in a message is not a record."]),
        ("Probation, not a block", ["The deflated Sharpe ratio is reported on every decision. A live strategy "
                                    "below 0.95 stays live but keeps iterating toward a version that clears it."]),
    ], size=16, h=Inches(3.4))
    d.cite("docs/plans/OPERATING-PLAN-2026-09-21.md § 2 “The HOLDOUT governs real money”")
    d.end_md()

    s = d.new("Three statuses, derived from the books",
              f"Every leg has exactly one of three statuses, and the status is computed from which accounts it "
              f"is on, never typed in by hand. Testing legs trade on paper so even weak ideas generate data. "
              f"Production legs trade real money plus the mirror. Inactive legs were retired by a written "
              f"research record that also says what evidence would bring them back. Counts as of {f['date']}.",
              tags=("MEASURED",))
    total = f["legs_total"]
    rows = [
        ["Testing", "Paper accounts (the demo floor)", str(st["testing"]), pct(st["testing"] / total)],
        ["Production", "Real money + its paper mirror", str(st["production"]), pct(st["production"] / total)],
        ["Inactive", "Nowhere — retired by a research record", str(st["inactive"]), pct(st["inactive"] / total)],
        ["Total", "", str(total), "100%"],
    ]
    d.table(s, ["Status", "Where it trades", "Legs", "Share"], rows, col_w=[2, 5, 1.2, 1.2], size=17,
            h_row=Inches(0.62))
    for k in ("testing", "production", "inactive"):
        d.num(f"{k} legs", st[k], "MEASURED", "scripts/ops/strategy_status.py over config/strategies.yaml + config/accounts.yaml", "/api/bot/strategies")
    d.footnote(s, f"MEASURED: scripts/ops/strategy_status.py over config/strategies.yaml + config/accounts.yaml, "
                  f"{total} legs, commit {f['sha']}. Shares are of those {total} legs.", y=H - Inches(2.0))
    d.end_md()

    s = d.new("Prop-firm accounts clear a stricter bar",
              "Prop firms lend capital under strict drawdown limits; break them and the account is gone. So a "
              "strategy must clear everything a real-money strategy clears, plus a survival test against that "
              "firm's specific limits. Never a lower bar.", tags=("MEASURED",))
    d.bullets(s, [
        "A prop firm funds a trader on condition they stay within daily and total loss limits.",
        "A prop leg must clear the real-money bar PLUS a survival and expected-value test against the "
        "firm's own drawdown rules.",
        "Prop trades are executed and protected automatically, like any other account.",
        f"{f['prop_total']} prop accounts are configured; {f['prop_live']} are switched on to send orders.",
    ])
    d.num("prop accounts configured", f["prop_total"], "MEASURED", "config/accounts.yaml (type: prop)", "/api/bot/config")
    d.num("prop accounts switched on", f["prop_live"], "MEASURED", "config/accounts.yaml (type: prop, mode: live)", "/api/bot/config")
    d.cite("comms/prop_survival/<leg>.json", "docs/plans/OPERATING-PLAN-2026-09-21.md § Prop legs clear a SUPERSET")
    d.footnote(s, f"MEASURED: config/accounts.yaml (type: prop), commit {f['sha']}.")
    d.end_md()

    s = d.new("Values: no fossil fuels on real money",
              "A values rule, not a performance rule. The operator asked on 17 November: “In general, I ask that we "
              "not trade fossil fuels.” Oil, gas, coal and energy-infrastructure funds are excluded from every "
              "real-money, prop and real-money-mirror roster. Paper accounts may still trade them, because the data "
              "helps research. No backtest result can re-open the list, and an automated test fails any change "
              "that would put one back on real money.", tags=("MEASURED",))
    d.cards(s, [
        ("What is excluded", [f"{f['fossil_n']} oil, gas, coal and energy-infrastructure funds and producers, "
                              "long, inverse and leveraged."]),
        ("Where it applies", ["Real money, prop accounts and the real-money mirrors. Paper accounts are exempt, "
                              "so research keeps its data."]),
        ("How it is held", ["One list in configuration, read by an automated test that fails any change "
                            "re-opening a gap. A good backtest does not override it."]),
    ], size=16, h=Inches(3.2))
    d.num("excluded fossil-fuel symbols", f["fossil_n"], "MEASURED", "config/values_exclusions.yaml (fossil_fuels.symbols)")
    d.footnote(s, "MEASURED: config/values_exclusions.yaml; enforced by tests/test_values_exclusions_real_money.py. "
                  "The quote is on record verbatim in that file.")
    d.end_md()

    # ---------------------------------------------------------------- PART 4
    d.section = "The evidence"
    cov = f["coverage"]
    other = f["evidence_records"] - sum(cov[k] for k in ("measured", "harness_failed", "no_harness"))
    fail_share = f["measured_fail"] / cov["measured"]
    s = d.new(f"The evidence bar in numbers: {pct(fail_share)} of what we measure fails",
              f"This is the slide that shows the discipline is real. Of {f['evidence_records']} strategy evidence "
              f"records on file, {cov['measured']} have a real measured backtest. Of those, {f['measured_pass']} "
              f"passed their pre-registered rule and {f['measured_fail']} failed. Failing is normal and expected: "
              f"it is the filter working. Records also include legs that are no longer on any book, so this is "
              f"a count of tests, not of live strategies.", tags=("MEASURED",))
    d.cards(s, [
        (f"{f['evidence_records']} evidence records", [f"{cov['measured']} measured", f"{cov['harness_failed']} "
                                                       f"where the test harness broke (we looked)",
                                                       f"{cov['no_harness']} with no harness yet",
                                                       f"{other} comparison record"]),
        (f"{f['measured_pass']} passed", [f"{pct(f['measured_pass'] / cov['measured'])} of measured records "
                                          "cleared their pre-registered rule, after the full cost stack."]),
        (f"{f['measured_fail']} failed", [f"{pct(f['measured_fail'] / cov['measured'])} did not. Failures stay "
                                          "on paper and go back into research, or are retired by record."]),
    ], size=17, head=22, h=Inches(3.6))
    d.num("evidence records", f["evidence_records"], "MEASURED", "comms/strategy_evidence/*.json")
    d.num("measured records", cov["measured"], "MEASURED", "comms/strategy_evidence/*.json (coverage_state)")
    d.num("measured records passed", f["measured_pass"], "MEASURED", "comms/strategy_evidence/*.json (decision_rule.verdict)")
    d.num("measured records failed", f["measured_fail"], "MEASURED", "comms/strategy_evidence/*.json (decision_rule.verdict)")
    d.num("pass rate", pct(f["measured_pass"] / cov["measured"]), "MEASURED", "comms/strategy_evidence/*.json")
    d.footnote(s, f"MEASURED: comms/strategy_evidence/*.json, {f['evidence_records']} files, commit {f['sha']}. "
                  f"Pass/fail = decision_rule.verdict. Percentages are of the {cov['measured']} measured records.")
    d.end_md()

    s = d.new("Production strategies: their backtest evidence",
              "The strategies trading real money right now, with the out-of-sample backtest result each was "
              "promoted on. Read the expectancy column as average profit per trade in units of risk, after the "
              "full cost stack. Positive folds means: of the separate time periods tested, how many came out "
              "positive. Caveats are shown rather than hidden: some legs have few test trades, and any row "
              "marked approximate is from a harness that did not model every setting the live strategy uses.",
              tags=("MEASURED",))
    rows = []
    for r in f["prod_rows"]:
        if r.get("missing"):
            rows.append([PLAIN.get(r["leg"], r["leg"]), "—", "—", "—", "—", "—"])
            continue
        rows.append([PLAIN.get(r["leg"], r["leg"]), f"{r['exp']:+.2f}R" if abs(r['exp']) >= 0.05 else f"{r['exp']:+.3f}R",
                     str(r["n"]), f"{r['folds_pos']} of {r['folds']}" if r["folds"] else "held-out",
                     f"{r['start']} → {r['end']}" if r["start"] else "—",
                     r["fidelity"]])
    d.table(s, ["Strategy (production)", "Expectancy / trade", "Trades", "Positive folds", "Test window",
                "Harness fidelity"], rows, col_w=[4.2, 1.8, 1.1, 1.6, 2.4, 1.6], size=12, h_row=Inches(0.4))
    for r in f["prod_rows"]:
        if not r.get("missing"):
            d.num(f"expectancy per trade: {r['leg']}", round(r["exp"], 3), "MEASURED", f"comms/strategy_evidence/{r['leg']}.json (expectancy_r_oos)")
    d.footnote(s, "MEASURED (backtest, out-of-sample, net of fees + slippage + funding): comms/strategy_evidence/"
                  "<leg>.json. The two ML rows are a held-out window scored once, not folds. "
                  "Parameter-selection history is not established for every rule-based leg.",
               y=H - Inches(1.25))
    d.end_md()

    s = d.new("Costs are charged in full, and they matter",
              f"Why we insist on the full cost stack. Taking the production legs that have a fee-only number "
              f"on file (n = {f['cost_cut_n']} of {len(f['prod_rows'])} production legs), adding slippage and funding allowances removed between {pct(f['cost_cut_min'])} and "
              f"{pct(f['cost_cut_max'])} of their fee-only net result. That range is ESTIMATED because the "
              f"slippage allowance is an assumption, not a measurement of our fills. A strategy that only "
              f"passes on fees alone does not pass.", tags=("MEASURED", "ESTIMATED"))
    d.cards(s, [
        ("Fees", ["Each venue's trading fee is charged on every entry and exit in the backtest."]),
        ("Slippage", [f"An allowance of {'–'.join(str(int(x)) for x in f['slippage_bps'])} basis points per "
                      "round trip for getting a worse price than the chart shows. ESTIMATED."]),
        ("Funding", ["Crypto perpetual futures pay or charge a periodic funding rate; the backtest "
                     "charges an allowance for it. ESTIMATED."]),
        ("The effect", [f"On the {f['cost_cut_n']} production legs with a fee-only figure, slippage + funding "
                        f"cut {pct(f['cost_cut_min'])}–{pct(f['cost_cut_max'])} of net R. ESTIMATED."]),
    ], cols=2, size=16)
    d.num("slippage allowance (bps per round trip)", "–".join(str(int(x)) for x in f["slippage_bps"]), "ESTIMATED", "comms/strategy_evidence/*.json (cost_stack.slippage)")
    d.num("share of fee-only net R removed by slippage + funding", f"{pct(f['cost_cut_min'])}–{pct(f['cost_cut_max'])}", "ESTIMATED", "comms/strategy_evidence/<production leg>.json (net_r_oos vs net_r_oos_fee_only)")
    d.footnote(s, "Inputs MEASURED from comms/strategy_evidence/<leg>.json (net_r_oos vs net_r_oos_fee_only, "
                  "cost_stack); the resulting range is ESTIMATED because the slippage and funding inputs are "
                  "allowances.")
    d.end_md()

    sc = f["scalp"] or {}
    scalp_line = (f"The short-term scalp family looked attractive, but on honest testing {sc.get('passed', 0)} of its "
                  f"{sc.get('records', 0)} measured records passed, so it is not on real money." if sc else "")
    s = d.new("What fails is useful",
              "An example of the filter working. " + scalp_line + " That is a result, "
              "not a waste: it tells us where not to spend capital, and those records stay on file so nobody "
              "re-runs the same idea by accident. The table groups every measured record by strategy family.",
              tags=("MEASURED",))
    rows = []
    for h, v in sorted(f["families"].items(), key=lambda kv: -kv[1]["records"]):
        rows.append([FAMILY_PLAIN.get(h, h), str(v["records"]), str(v["passed"]),
                     f"{v['median_exp']:+.2f}R", str(v["trades"])])
    for h, v in f["families"].items():
        d.num(f"records passed: {FAMILY_PLAIN.get(h, h)}", f"{v['passed']} of {v['records']}", "MEASURED", "comms/strategy_evidence/*.json (harness, decision_rule.verdict)")
    d.table(s, ["Family", "Records", "Passed", "Median expectancy", "Test trades"], rows,
            col_w=[4, 1.4, 1.4, 2.2, 1.6], size=14, h_row=Inches(0.46))
    d.footnote(s, f"MEASURED: the {cov['measured']} measured records in comms/strategy_evidence/, grouped by their "
                  "harness field; out-of-sample, net of the full cost stack. Median is across records.",
               y=H - Inches(0.95))
    d.end_md()

    # ---------------------------------------------------------------- PART 5
    d.section = "How it keeps improving"
    q = f["queue"]
    s = d.new("The research loop: decide before you measure",
              f"Research is run as a queue of questions. Each question is written down with its data, its test "
              f"and its decision rule before it runs, so the result IS the decision and nobody argues about it "
              f"afterwards. The queue currently holds {f['queue_total']} questions: {q['done']} done, "
              f"{q['queued']} waiting, {q['retired']} retired, plus {f['queue_blocked']} parked as blocked.",
              tags=("MEASURED",))
    d.flow(s, [
        ("Ask", ["One question, with its data, its test and its decision rule written first."]),
        ("Run", ["A dispatcher runs queued questions automatically on cloud runners."]),
        ("Grade", ["The result is graded against the rule that was registered."]),
        ("Act", ["Pass → next stage. Fail → back to research with a diagnosis."]),
    ], size=15, h=Inches(1.4))
    d.num("research questions in the queue", f["queue_total"], "MEASURED", "research/queue/*.yaml (status)", "/api/bot/research/catalog")
    d.num("questions done", q["done"], "MEASURED", "research/queue/*.yaml (status: done)", "/api/bot/research/catalog")
    d.num("questions waiting", q["queued"], "MEASURED", "research/queue/*.yaml (status: queued)", "/api/bot/research/catalog")
    d.num("questions retired", q["retired"], "MEASURED", "research/queue/*.yaml (status: retired)", "/api/bot/research/catalog")
    d.num("questions parked as blocked", f["queue_blocked"], "MEASURED", "research/queue/blocked/*.yaml", "/api/bot/research/catalog")
    d.footnote(s, f"MEASURED: research/queue/*.yaml status fields — {f['queue_total']} units: {q['done']} done, "
                  f"{q['queued']} queued, {q['retired']} retired; {f['queue_blocked']} more in research/queue/blocked/. "
                  f"Commit {f['sha']}.", y=H - Inches(1.3))
    d.end_md()

    s = d.new("Iterate on levers, not on luck",
              "A rule the operator set on 1 November: when something fails, we do not just try a different "
              "random idea. We work out why it failed, identify the levers that could change the outcome, "
              "and test them one by one. A strategy is retired only when the levers are exhausted, never after "
              "a fixed number of attempts. The same applies to ML models and to the live-trade review.")
    d.bullets(s, [
        "Every strategy, ML model and live-trade action class goes through the same research workflow.",
        "The centre of it is understanding how each lever moves the outcome, not pass/fail alone.",
        (1, "Levers include entry timing, stop distance, target placement, market regime and timeframe."),
        "A failed test returns with a diagnosis and the next lever to test.",
        "Retirement needs evidence that no lever helps, plus a written test that would bring it back.",
        "Weekly programme reviews check that every non-passing strategy has a live next step.",
    ])
    d.end_md()

    s = d.new("Live books check mechanics and cost, never edge",
              "Live and paper trades are watched closely, but they do not decide whether a strategy has an "
              "edge; a handful of live trades is far too few. They check that the machinery works and that "
              "costs match what the backtest assumed. The paper mirror of each real-money book is the early "
              "warning: if it goes net-negative after costs over its window, the strategy moves back to the demo "
              "floor, where it keeps trading on paper for data while it is improved.")
    d.cards(s, [
        ("Mechanics", ["Did the signal fire, the order go out at the right size, the brackets rest at the "
                       "broker, and the close get a real reason?"]),
        ("Cost", ["Are real fees and slippage in line with the backtest's allowances?"]),
        ("Demotion signal", ["The paper mirror's net-of-cost result over its declared window triggers "
                             "demotion back to the demo floor."]),
        ("Probation", ["A live strategy whose deflated Sharpe ratio is below its bar keeps an open research "
                       "unit to build a stronger version."]),
    ], cols=2, size=16)
    d.end_md()

    s = d.new("The trading desk and the live-trade review",
              "Two AI functions work on live trades. The live-trade review looks at every open order package, "
              "checks the mechanics first, then asks what the best decision is right now. Each option, such as hold, "
              "tighten or close, is priced from that strategy's own backtest history, and one recommendation per "
              "package is written to an append-only record. Since 14 November, recommended actions are applied "
              "automatically under one standing mandate, through each account's own risk checks, with a ping to "
              "the operator. The trading desk is the other half: an AI trader that finds trades the strategies are "
              "not taking, today on the demo floor only. The system's own models learn from its decisions, with the "
              "aim of eventually replacing it.", tags=("MEASURED",))
    d.cards(s, [
        ("Live-trade review", ["Every open package, every account. Mechanics first, then the best decision now, "
                               "each option priced from the strategy's own history.",
                               f"{f['reviews_n']} reviews on record." if f["reviews_n"] is not None else "—"]),
        ("Applied, with a ping", ["Recommended actions are applied through each account's own risk manager, "
                                  "with one ping per change. Each action class is graded afterwards."]),
        ("The trading desk", ["An AI trader that enters, manages and exits its own trades. Today it trades on "
                              "the demo floor only; real money is gated behind its own evidence."]),
        ("Teaching the models", ["The desk's decisions become labels for the system's own models, which aim to "
                                 "take over the job."]),
    ], cols=2, size=15)
    d.num("live-trade reviews on record", f["reviews_n"], "MEASURED", "comms/live_review/reviews.jsonl (line count)")
    d.cite(".claude/skills/live-trade-review/SKILL.md", ".claude/skills/trading-desk/SKILL.md", "config/mandates.yaml (MD-TRADE-DESK)")
    d.footnote(s, "MEASURED: comms/live_review/reviews.jsonl, one line per review, all accounts, commit "
                  f"{f['sha']}.")
    d.end_md()

    s = d.new("Run by AI agents, governed by a human",
              f"Day-to-day operations are done by AI agent sessions. A manager session keeps one register of "
              f"work and dispatches focused lanes, like the one that built this deck. The operator sets "
              f"strategy and risk policy and grants standing authorizations, called mandates, for decisions the "
              f"data can settle. Currently {f['mandates_granted']} mandates are granted and {f['mandates_proposed']} "
              f"{'is' if f['mandates_proposed'] == 1 else 'are'} proposed. Agents may propose a mandate; only the "
              f"operator grants one.", tags=("MEASURED",))
    d.cards(s, [
        ("Manager + lanes", ["One manager session keeps the work register and dispatches narrow lanes, each "
                             "with one question and a spending ceiling."]),
        ("Mandates", [f"{f['mandates_granted']} standing grants let evidence-backed decisions proceed without "
                      "asking. Agents can propose; only the operator grants."]),
        ("Daily sync", ["One brief a day: what came due, what was decided under mandate, decisions for the "
                        "operator, what moved, what is running, spend."]),
        ("Permission tiers", ["Docs and tooling: autonomous. Runtime changes: one OK. Strategy and risk: "
                              "operator approval, or a committed evidence record."]),
    ], cols=2, size=16)
    d.num("mandates granted", f["mandates_granted"], "MEASURED", "config/mandates.yaml (mandates)")
    d.num("mandates proposed", f["mandates_proposed"], "MEASURED", "config/mandates.yaml (proposed)")
    d.footnote(s, f"MEASURED: config/mandates.yaml, commit {f['sha']}.")
    d.end_md()

    s = d.new("Numbers you can trust",
              "Small rules that stop the most common reporting mistakes. Every number carries a label saying "
              "whether it was measured or estimated, or worse. A zero is never allowed to hide the fact that "
              "we could not look. A missing value shows as a dash, never as zero. And automated checks run on "
              "every change to keep the documents, the configuration and the code in agreement.")
    d.cards(s, [
        ("Provenance labels", ["Every number is MEASURED, ESTIMATED, FABRICATED or UNVERIFIED, and the four "
                               "are never mixed."]),
        ("“0” vs “could not look”", ["A count that reads zero must say whether we actually looked. "
                                     "Missing data shows as “—”."]),
        ("Merged ≠ deployed ≠ observed", ["A change is only done when its effect is seen on the running "
                                          "system, and reports say which of the three is true."]),
        ("Automated guards", ["Checks on every change keep rules, configuration and docs from drifting "
                              "apart, e.g. a guard refuses a strategy on both paper and real money."]),
    ], cols=2, size=16)
    d.end_md()

    mls = [r for r in f["prod_rows"] if r["leg"] in ("ml_entry", "ml_entry_eq_struct") and not r.get("missing")]
    s = d.new("Machine learning today",
              "Where ML stands, honestly. Two learned entry models now trade real money: one on crypto and one on a "
              "pool of US funds. Each was promoted on a held-out window scored once, net of the full cost stack. "
              "Models follow the same flow as strategies: offline evidence goes straight to use, and a demoted "
              "model drops back to shadow, where it keeps scoring for data while it is improved. Earlier attempts "
              "to predict direction from price data alone failed offline; the lesson recorded was that the binding "
              "constraint is labelled outcomes, not computing power.", tags=("MEASURED",))
    items = []
    for r in mls:
        items.append(f"{PLAIN.get(r['leg'], r['leg'])}: {r['exp']:+.3f}R per trade over {r['n']} held-out trades "
                     f"({r['start'][:7]} → {r['end'][:7]}), net of costs.")
        d.num(f"held-out expectancy: {r['leg']}", round(r["exp"], 3), "MEASURED", f"comms/strategy_evidence/{r['leg']}.json (expectancy_r_oos)")
        d.num(f"held-out trades: {r['leg']}", r["n"], "MEASURED", f"comms/strategy_evidence/{r['leg']}.json (n_trades_oos)")
    items += [
        "Same ladder as strategies: offline evidence → in use; demotion → shadow, still scoring for data.",
        f"An inventory on {f['ml_inv']['as_of']} counted {f['ml_inv']['total']} registered models; it proposed keeping "
        f"{f['ml_inv']['proposals']['KEEP']}, reviewing {f['ml_inv']['proposals']['REVIEW']} and retiring "
        f"{f['ml_inv']['proposals']['RETIRE']} that nothing uses.",
        "Lesson recorded: models fed only price data did not predict direction; the limit is labelled outcomes.",
    ]
    d.num("registered models (inventory)", f["ml_inv"]["total"], "MEASURED", f"comms/ml_consolidation/{f['ml_inv']['as_of']}.json", "/api/bot/ml/registry")
    d.bullets(s, items, size=18)
    d.footnote(s, "MEASURED: comms/strategy_evidence/ml_entry.json and ml_entry_eq_struct.json (basis heldout_window); "
                  f"inventory comms/ml_consolidation/{f['ml_inv']['as_of']}.json, a dated snapshot.")
    d.end_md()

    kc = f["ml_inv"]["keep_consumer"]
    s = d.new("The ML programme: ten decisions, one model family each",
              "The ML plan cuts the life of a trade into ten decisions, from which markets to trade to grading a "
              "closed trade. Each decision is owned by exactly one model family, with one question, a baseline it "
              "must beat net of cost, a label, and an offline test. Each slot runs its own champion and challenger "
              "loop: the model in use is the champion, a retrained or new model is the challenger, and the challenger "
              "replaces it only by beating it on the same data and the same costs. Several slots have no model yet; "
              "they run on rules today, which is stated rather than hidden.", tags=("MEASURED",))
    slots = [
        ("D1", "Universe & book", "Which markets and strategies sit on which account", "rule (the ladder)"),
        ("D2", "Regime gate", "May this strategy fire in today's market?", "Collie"),
        ("D3", "Entry", "Open long, short or nothing", "Foxhound"),
        ("D4", "Signal filter", "Take, reduce or skip a strategy's signal", "Beagle"),
        ("D5", "Position aggregation", "Combine several signals on one market", "Mastiff"),
        ("D6", "Bracket at entry", "Where the stop and target sit", "Pointer"),
        ("D7", "In-trade management", "Hold, move a bracket, take a partial", "Labrador"),
        ("D8", "Exit now", "Close the whole position now?", "Labrador"),
        ("D9", "Execution", "How to place the order to cut cost", "Whippet"),
        ("D10", "Review & grading", "Grade the decision; feed labels back", "Basset"),
    ]
    rows = [[sid, name, q, fam, str(kc.get(sid, 0)) if sid != "D1" else "—"] for sid, name, q, fam in slots]
    d.table(s, ["Slot", "Decision", "The question", "Family", "Models with a consumer"], rows,
            col_w=[0.8, 2.4, 4.6, 1.6, 1.4], size=12, h_row=Inches(0.4))
    for sid, *_ in slots[1:]:
        d.num(f"models with a consumer: {sid}", kc.get(sid, 0), "MEASURED", f"comms/ml_consolidation/{f['ml_inv']['as_of']}.json (proposal KEEP (consumer))", "/api/bot/ml/registry")
    d.cite("docs/plans/ML-ROADMAP-MECE-2026-11.md § 2", "docs/plans/ML-CONSOLIDATION-2026-11-11.md")
    d.footnote(s, f"Map: docs/plans/ML-ROADMAP-MECE-2026-11.md. “Models with a consumer” = a strategy, account or config uses it (demo floor included), per the "
                  f"{f['ml_inv']['as_of']} inventory (MEASURED, dated). Family names are internal labels.",
               y=H - Inches(0.95))
    d.end_md()

    # ---------------------------------------------------------------- PART 6 roadmap
    d.section = "Where it goes next"
    s = d.new("Roadmap 1 — scale the real-money strategies",
              "Goal one on the roadmap is real-money edge, decided offline. The near-term work: active management "
              "as a standard on every real-money strategy, with targets that are real predictions and move with the "
              "trade; a promotion ladder that runs mechanically from a backtest pass to real money and back; more "
              "testing legs pushed through Stage 0; and longer and shorter timeframes, always net of cost.")
    d.cards(s, [
        ("Active management as standard", ["Evidence-backed stop and target moves on every real-money strategy, "
                                           "and targets revised during every trade."]),
        ("A mechanical ladder", ["Backtest pass → real money; mirror net-negative → back to the demo floor. "
                                 "Decided by registered rules and standing mandates."]),
        ("More legs through Stage 0", [f"{st['testing']} testing legs keep iterating on their levers; each one "
                                       "that passes goes to real money."]),
        ("New horizons", ["Daily and weekly holds, and sub-hour breakout families, tested net of cost."]),
    ], cols=2, size=16)
    d.num("testing legs", st["testing"], "MEASURED", "scripts/ops/strategy_status.py", "/api/bot/strategies")
    d.cite("docs/roadmap/milestones.yaml (G1: L-AM-STANDARD, L-ATM, L-LADDER, L-TIMEFRAMES)")
    d.footnote(s, "Source: ROADMAP.md live block (generated from docs/roadmap/milestones.yaml), goal G1: L-AM-STANDARD, "
                  "L-ATM, L-LADDER, L-TIMEFRAMES. Testing-leg count MEASURED.")
    d.end_md()

    s = d.new("Roadmap 2 — machine learning and the desk",
              "Goal four on the roadmap is the AI trader. Near-term priorities: more ML in the live trading loops, "
              "with the infrastructure to run and monitor it; every one of the ten trade decisions with an owning "
              "model family and a registered test; the regime programme, which asks when each strategy is primed; "
              "the trading desk made production-ready; and a data programme to collect and label more outcomes, "
              "since labels are the binding constraint.")
    d.cards(s, [
        ("ML in the live loops", ["More learned decisions changing live orders, with serving and monitoring "
                                  "infrastructure."]),
        ("Ten slots, one loop each", ["Every trade decision gets a question, a baseline, a label and a "
                                      "champion-versus-challenger test."]),
        ("Regime and the desk", ["Learn when each strategy is primed; make the AI trading desk "
                                 "production-ready."]),
        ("Data and labels", ["Grow the store of labelled outcomes, the binding constraint on every model."]),
    ], cols=2, size=16)
    d.cite("docs/roadmap/milestones.yaml (G4: L-ML-LIVE, L-ML-MECE, L-REGIME, L-DESK-V1, L-DESK, L-DATA)")
    d.footnote(s, "Source: ROADMAP.md live block, goal G4: L-ML-LIVE, L-ML-MECE, L-REGIME, L-DESK-V1, L-DESK, L-DATA.")
    d.end_md()

    s = d.new("Roadmap 3 — the learning machine",
              "The last part of the roadmap is about the machine that does the improving: prop accounts that "
              "qualify on their own, plumbing and alerts that can be trusted, research programmes that turn "
              "evidence into decisions without the operator in the path, and a slower macro and value sleeve. "
              "This is where the deck ends: no request, just the plan.")
    d.cards(s, [
        ("Prop accounts", ["Automate, protect and qualify the prop-firm accounts."]),
        ("Trustworthy plumbing", ["Every position protected, every close explained, every number labelled, "
                                  "every alert reaching the system without a human relaying it."]),
        ("Research machine", ["Research programmes with weekly plans: questions run, get graded, and act."]),
        ("Macro and value", ["A slower, thesis-driven sleeve expressed through defined-risk options."]),
    ], cols=2, size=16)
    d.cite("docs/roadmap/milestones.yaml (G2 L-PROP; G3 M39, L-ALERT-INTEGRATION; G5 L-PROGRAMMES, M40; G6 M28)")
    d.footnote(s, "Source: ROADMAP.md live block: G2 L-PROP · G3 M39, L-ALERT-INTEGRATION · G5 L-PROGRAMMES, M40 · G6 M28.")
    d.end_md()

    # ---------------------------------------------------------------- APPENDIX
    d.section = "Appendix"
    s = d.new("Appendix A — system architecture",
              "For technical readers. Five layers, kept separate on purpose. The runtime layer is the live "
              "trader: market data, strategy evaluation, order construction, per-account risk, broker execution, "
              "and a single trade journal database. The research layer holds backtests and ML training, on a "
              "separate machine. Operator communications, deployment and governance are their own layers. A web "
              "API feeds one dashboard.")
    d.table(s, ["Layer", "What it holds"], [
        ["Runtime trading", "Market data · strategy evaluation · order build + validation · per-account risk · "
                            "broker execution · trade journal"],
        ["Research & validation", "Backtest harnesses · ML datasets, training, registry · research queue runner"],
        ["Operator comms", "Request/response channel · alert and ping delivery"],
        ["Deployment", "Service units · repo sync to the servers every few minutes · self-heal workflows"],
        ["Governance", "Canonical docs · work register · follow-through pipeline · CI guards"],
    ], col_w=[2.2, 8], size=14, h_row=Inches(0.62))
    d.footnote(s, "Source: docs/ARCHITECTURE-CANONICAL.md § System Layers. Two cloud servers: the live trader and "
                  "an ML trainer; a separate broker gateway. Addresses intentionally omitted.",
               y=H - Inches(1.4))
    d.end_md()

    s = d.new("Appendix B — what an evidence record contains",
              "Each strategy has one evidence record, written by a script, never by hand. These are the fields "
              "that matter. Coverage state is read first, so a missing number is never mistaken for a bad one. "
              "Fidelity says whether the harness modelled every setting the live strategy uses.")
    d.table(s, ["Field", "Meaning"], [
        ["coverage_state", "measured · harness_failed · no_harness · not_attempted — read first"],
        ["net_r_oos / expectancy_r_oos", "Out-of-sample net R and R per trade, after the full cost stack"],
        ["n_trades_oos · folds · folds_positive", "Sample size and how many separate time folds were positive"],
        ["cost_stack", "Fees, slippage allowance, funding allowance, with the source run"],
        ["fidelity · omitted_levers", "faithful = every configured lever modelled; approximate names the gaps"],
        ["decision_rule", "Rule id, when it was registered, and the verdict (pass / fail)"],
        ["path_stats", "Max drawdown in R, worst trade, worst day — descriptive, not a verdict"],
    ], col_w=[3.2, 7], size=14, h_row=Inches(0.55))
    d.footnote(s, "Source: comms/strategy_evidence/README.md and the records themselves "
                  "(producer scripts/ops/build_strategy_evidence.py).", y=H - Inches(1.1))
    d.end_md()

    s = d.new("Appendix C — production legs, path statistics",
              "The same production legs with path detail: total net R over the test, and the largest peak-to-"
              "trough drawdown in R. Drawdown is descriptive here; it is not a pass mark. The ML model's record "
              "does not carry path statistics, shown as a dash.", tags=("MEASURED",))
    rows = []
    for r in f["prod_rows"]:
        if r.get("missing"):
            continue
        rows.append([PLAIN.get(r["leg"], r["leg"]), f"{r['net']:+.1f}R", str(r["n"]),
                     f"{r['maxdd']:.1f}R" if r["maxdd"] is not None else "—", r["basis"].replace("_", " ")])
    d.table(s, ["Strategy (production)", "Net R, out of sample", "Trades", "Max drawdown", "Basis"], rows,
            col_w=[4.2, 2, 1.2, 1.8, 2.4], size=12, h_row=Inches(0.4))
    d.footnote(s, "MEASURED: comms/strategy_evidence/<leg>.json fields net_r_oos, n_trades_oos, "
                  "path_stats.max_drawdown_r, basis. Windows differ by leg (see the production-strategies slide).", y=H - Inches(1.1))
    d.end_md()

    s = d.new("Appendix D — glossary",
              "Plain definitions of the terms used in the deck.")
    d.table(s, ["Term", "Meaning"], [
        ["R", "One unit of risk: what a trade loses if its stop-loss is hit"],
        ["Expectancy", "Average R per trade, after costs"],
        ["Leg", "One strategy on one market and timeframe"],
        ["Out of sample / fold", "Data the rule was not tuned on; a fold is one separate time slice of it"],
        ["Slippage", "Getting a worse price than expected when the order fills"],
        ["Funding", "Periodic payment between long and short holders of crypto perpetual futures"],
        ["Paper / mirror", "Simulated-money account at the broker / a paper copy of a real-money book"],
        ["Mandate", "A standing operator grant to act on a class of decision when the evidence settles it"],
        ["Prop firm", "A firm that funds traders under strict loss limits"],
        ["Demo floor", "The paper accounts where every testing or demoted strategy trades for data"],
        ["Held-out", "Data kept aside and never used for tuning; the real-money pass is judged on it"],
        ["Champion / challenger", "The model in use vs a new one; the new one replaces it only by beating it on the same data"],
    ], col_w=[2.4, 8], size=12, h_row=Inches(0.38))
    d.end_md()

    s = d.new("Appendix E — sources and provenance",
              "Where every number in the deck came from. The deck is generated by a script that reads these files "
              "directly, so re-running it refreshes the numbers.")
    d.bullets(s, [
        f"Built {f['date']} from repo commit {f['sha']} by docs/pitch/build_deck.py (numbers are computed, not typed).",
        "Leg counts and statuses: scripts/ops/strategy_status.py over config/strategies.yaml + config/accounts.yaml.",
        "Accounts, prop accounts, modes: config/accounts.yaml. Mandates: config/mandates.yaml. Fossil-fuel list: "
        "config/values_exclusions.yaml.",
        "Target compliance: scripts/ci/check_tp_doctrine.py. Live-trade reviews: comms/live_review/reviews.jsonl. "
        "ML inventory: comms/ml_consolidation/ (dated snapshot).",
        "Backtest evidence: comms/strategy_evidence/*.json (out of sample, net of the full cost stack).",
        "Research queue: research/queue/*.yaml status fields.",
        "Concepts and rules: docs/plans/OPERATING-PLAN-2026-09-21.md, docs/ARCHITECTURE-CANONICAL.md, "
        "docs/plans/ML-ROADMAP-MECE-2026-11.md, ROADMAP.md.",
        "Machine-readable: docs/pitch/slides.json lists every slide with each number's provenance and source.",
        "Left out on purpose: live and paper profit figures (a live book never establishes edge, and they were "
        "not re-verified for this build), and every dollar amount, balance, account id and server address.",
    ], size=15, gap=6)
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
