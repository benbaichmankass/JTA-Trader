#!/usr/bin/env python3
"""Build the JTA Trader pitch deck (docs/pitch/jta-trader-pitch-deck.pptx) and its
markdown source / speaker notes (docs/pitch/jta-trader-pitch-deck.md).

Row PROJECT-PITCH-DECK. Every number on a slide is COMPUTED here from a file on
disk at build time (config/strategies.yaml + scripts/ops/strategy_status.py,
config/accounts.yaml, config/mandates.yaml, comms/strategy_evidence/*.json,
research/queue/*.yaml) and carries a provenance tag (src/runtime/provenance.py
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
        for known in ("ml_decision_entry", "event_oi_shock"):
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
}

FAMILY_PLAIN = {
    "trend": "Trend breakouts", "pullback": "Pullbacks in a trend", "ict_scalp": "Short-term scalps",
    "ml_decision_entry": "ML entry model", "event_oi_shock": "Event: open-interest shock",
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
        self.md.append("")

    def footnote(self, s, text, y=None):
        self._text(s, Inches(0.6), y or (H - Inches(1.05)), Inches(12.1), Inches(0.55), text, size=12,
                   color=GREY)
        self.md.append(f"> {text}\n")


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
                                       "down before the test was run."]),
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
                    "Bybit. Paper, real-money and mirror accounts."]),
        ("US funds (ETFs)", ["Broad index, bond, gold, silver, oil and leveraged funds on Alpaca. Paper, "
                             "real money, mirror and an options paper account."]),
        ("Futures", ["Micro index and metals futures on Interactive Brokers, on paper. A real-money account "
                     "exists in dry run with no strategies yet."]),
        ("Prop firms", [f"{f['prop_total']} prop-firm accounts are configured; {f['prop_live']} are switched on. "
                        "They must clear a stricter bar than real money (slide 14)."]),
    ], cols=2, size=16)
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
        ("Data", ["Prices arrive from four broker connections, every bar, every market."]),
        ("Signal", ["Each strategy checks its own rules on its own markets."]),
        ("Risk check", ["Per-account limits decide yes/no and the size, in R."]),
        ("Order", ["Sent with a stop-loss and a profit target already attached."]),
        ("Manage", ["Brackets can move, but only on evidence."]),
        ("Close & grade", ["Exit reason recorded; trade graded and fed back to research."]),
    ], size=14)
    d.end_md()

    s = d.new("Every trade carries a real stop and a real target",
              "A rule the operator set: no fictional take-profits. Many systems put a target so far away it "
              "never triggers, which is a way of not having one. Here, each strategy's target must be a real "
              "prediction of where price is going, and compliance is checked by a script. Active management "
              "means the system may move either bracket while a trade is open, but each kind of move stays "
              "advice-only until its own cost-aware test passes.")
    d.cards(s, [
        ("Stop-loss from the start", ["Every order rests at the broker with a protective stop. That stop "
                                      "defines 1R."]),
        ("A real profit target", ["The target is a prediction, not a placeholder. A target set so far away "
                                  "it can never fill counts as no target, and a checker flags it."]),
        ("Evidence-backed management", ["Moving a stop or a target mid-trade is allowed. Each kind of move "
                                        "is advice only until its own test, net of costs, says it helps."]),
    ], size=16, h=Inches(3.0))
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

    s = d.new("The promotion ladder: three stages, two gates",
              "This is how an idea becomes a real-money strategy. Stage 0 decides whether there is an edge, "
              "offline. Stage 1, paper trading, is not a performance test. It is a mechanical check: does the "
              "order go out at the right size, do the stop and target rest at the broker, does the close get "
              "recorded. One or two clean trades are enough. If the execution path is already proven, Stage 1 "
              "is skipped. Stage 2 is real money plus a paper mirror that copies it exactly; if the mirror turns "
              "net-negative after costs over its window, the strategy is demoted.")
    y = Inches(1.9)
    bw, bh, gap = Inches(3.6), Inches(3.2), Inches(0.55)
    stages = [
        ("STAGE 0 · Backtest", "Is there an edge, net of all costs?",
         "Passes only by clearing a pass mark registered before the run.", NAVY),
        ("STAGE 1 · Paper", "Do the mechanics work?",
         "1–2 clean trades. Skipped when the execution path is already proven.", TEAL),
        ("STAGE 2 · Real money", "Does it hold up live, with its mirror?",
         "A paper mirror copies every trade; net-negative after costs → demoted.", GREEN),
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
        d.md.append(f"- **{h1}** — {q} {body}")
    d.md.append("")
    d.footnote(s, "A paper or live record never proves an edge; it checks mechanics and cost. Edge is decided "
                  "offline, at Stage 0.", y=H - Inches(1.6))
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
    d.footnote(s, f"MEASURED: config/accounts.yaml (type: prop), commit {f['sha']}.")
    d.end_md()

    # ---------------------------------------------------------------- PART 4
    d.section = "The evidence"
    cov = f["coverage"]
    other = f["evidence_records"] - sum(cov[k] for k in ("measured", "harness_failed", "no_harness"))
    s = d.new("The evidence bar in numbers: about half of what we test fails",
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
    d.footnote(s, f"MEASURED: comms/strategy_evidence/*.json, {f['evidence_records']} files, commit {f['sha']}. "
                  f"Pass/fail = decision_rule.verdict. Percentages are of the {cov['measured']} measured records.")
    d.end_md()

    s = d.new("Production strategies: their backtest evidence",
              "The strategies trading real money right now, with the out-of-sample backtest result each was "
              "promoted on. Read the expectancy column as average profit per trade in units of risk, after the "
              "full cost stack. Positive folds means: of the separate time periods tested, how many came out "
              "positive. Two caveats are shown rather than hidden: the gold-ETF leg has very few trades, and "
              "rows marked approximate are from a harness that did not model every setting the live strategy "
              "uses.", tags=("MEASURED",))
    rows = []
    for r in f["prod_rows"]:
        if r.get("missing"):
            rows.append([PLAIN.get(r["leg"], r["leg"]), "—", "—", "—", "—", "—"])
            continue
        rows.append([PLAIN.get(r["leg"], r["leg"]), f"{r['exp']:+.2f}R" if abs(r['exp']) >= 0.05 else f"{r['exp']:+.3f}R",
                     str(r["n"]), f"{r['folds_pos']} of {r['folds']}", f"{r['start']} → {r['end']}",
                     r["fidelity"]])
    d.table(s, ["Strategy (production)", "Expectancy / trade", "Trades", "Positive folds", "Test window",
                "Harness fidelity"], rows, col_w=[4.2, 1.8, 1.1, 1.6, 2.4, 1.6], size=14, h_row=Inches(0.5))
    d.footnote(s, "MEASURED (backtest, out-of-sample, net of fees + slippage + funding): comms/strategy_evidence/"
                  "<leg>.json. The ML model's row is one held-out year scored once, not folds. "
                  "Parameter-selection history is not established for the six rule-based legs.",
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
    d.footnote(s, "Inputs MEASURED from comms/strategy_evidence/<leg>.json (net_r_oos vs net_r_oos_fee_only, "
                  "cost_stack); the resulting range is ESTIMATED because the slippage and funding inputs are "
                  "allowances.")
    d.end_md()

    s = d.new("What fails is useful",
              "An example of the filter working. The short-term scalp family looked attractive, but on honest "
              "testing every one of its measured records failed, so it is not on real money. That is a result, "
              "not a waste: it tells us where not to spend capital, and those records stay on file so nobody "
              "re-runs the same idea by accident. The table groups every measured record by strategy family.",
              tags=("MEASURED",))
    rows = []
    for h, v in sorted(f["families"].items(), key=lambda kv: -kv[1]["records"]):
        rows.append([FAMILY_PLAIN.get(h, h), str(v["records"]), str(v["passed"]),
                     f"{v['median_exp']:+.2f}R", str(v["trades"])])
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
              "warning: if it goes net-negative after costs over its window, the strategy moves back to paper.")
    d.cards(s, [
        ("Mechanics", ["Did the signal fire, the order go out at the right size, the brackets rest at the "
                       "broker, and the close get a real reason?"]),
        ("Cost", ["Are real fees and slippage in line with the backtest's allowances?"]),
        ("Demotion signal", ["The paper mirror's net-of-cost result over its declared window triggers "
                             "demotion to paper."]),
        ("Live-trade review", ["An AI review of open trades recommends the best action now, each option "
                               "priced from that strategy's own history."]),
    ], cols=2, size=16)
    d.end_md()

    s = d.new("Run by AI agents, governed by a human",
              f"Day-to-day operations are done by AI agent sessions. A manager session keeps one register of "
              f"work and dispatches focused lanes, like the one that built this deck. The operator sets "
              f"strategy and risk policy and grants standing authorizations, called mandates, for decisions the "
              f"data can settle. Currently {f['mandates_granted']} mandates are granted and {f['mandates_proposed']} "
              f"is proposed. Agents may propose a mandate; only the operator grants one.", tags=("MEASURED",))
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

    s = d.new("Machine learning today",
              "Where ML stands, honestly. The first ML-driven leg, a learned entry model, now trades real money; "
              "its evidence is one held-out year scored once, with a small positive expectancy over many trades. "
              "Elsewhere, ML is used for advice about market regime, for example whether volatility is high. "
              "Earlier attempts to have models predict what to do from price data alone failed offline, and "
              "the lesson recorded was that the binding constraint is labelled outcomes, not computing power.",
              tags=("MEASURED",))
    ml = next((r for r in f["prod_rows"] if r["leg"] == "ml_entry" and not r.get("missing")), None)
    items = []
    if ml:
        items.append(f"A learned entry model is in production: {ml['exp']:+.3f}R per trade over {ml['n']} trades "
                     f"in one held-out year ({ml['start']} → {ml['end']}), net of costs. Small, but over many trades.")
    items += [
        "Per the ML plan (last measured 2026-10-11, not re-checked for this deck), the advisory models are "
        "volatility-regime models: they advise on when conditions suit a strategy.",
        "Lesson recorded in the ML plan: models fed only price data did not predict direction; "
        "the limit is labelled outcomes, not compute.",
        "Every model follows the same ladder: candidate → shadow → advisory, and nothing past shadow without "
        "the operator.",
    ]
    d.bullets(s, items)
    d.footnote(s, "MEASURED: comms/strategy_evidence/ml_entry.json (basis "
                  f"{ml['basis'] if ml else '—'}, fidelity {ml['fidelity'] if ml else '—'}). "
                  "The ML plan's lessons: ROADMAP.md § “AI trader (ML) — build plan”.")
    d.end_md()

    # ---------------------------------------------------------------- PART 6 roadmap
    d.section = "Where it goes next"
    s = d.new("Roadmap 1 — scale the real-money strategies",
              "Goal one on the roadmap is real-money edge, decided offline. The near-term work: make active "
              "management a standard on every real-money strategy, finish making the promotion ladder fully "
              "mechanical, keep pushing the testing legs through Stage 0, and explore longer and shorter "
              "timeframes, always net of cost.")
    d.cards(s, [
        ("Active management as standard", ["Evidence-backed stop and target moves on every real-money "
                                           "strategy."]),
        ("A fully mechanical ladder", ["Promotion and demotion decided by registered rules and standing "
                                       "mandates, without a human in the loop for routine calls."]),
        ("More legs through Stage 0", [f"{st['testing']} testing legs keep iterating on their levers; each one "
                                       "that passes moves to real money."]),
        ("New horizons", ["Daily and weekly holds, and sub-hour breakout families, tested net of cost."]),
    ], cols=2, size=16)
    d.footnote(s, "Source: ROADMAP.md live block (generated from docs/roadmap/milestones.yaml), goal G1. "
                  "Testing-leg count MEASURED as on slide 13.")
    d.end_md()

    s = d.new("Roadmap 2 — machine learning",
              "Goal four on the roadmap is the AI trader. Near-term priorities: more ML in the live trading "
              "loops, with the infrastructure to run and monitor it; the regime programme, which asks when "
              "each strategy is primed; a frontier programme that tests newer model families against what we "
              "use today; and a data programme to collect, process and label more outcomes, since labels are "
              "the binding constraint.")
    d.cards(s, [
        ("ML in the live loops", ["Extend the ML entry model and add ML heads to live decisions, with the "
                                  "infrastructure to serve and monitor them."]),
        ("Regime: when to trade", ["Learn when each strategy is primed, and step aside when it is not."]),
        ("Model frontier", ["Bake newer forecasting and tabular models off against today's, on the same "
                            "data and cost stack."]),
        ("Data and labels", ["Grow the store of labelled outcomes, the binding constraint on every model."]),
    ], cols=2, size=16)
    d.footnote(s, "Source: ROADMAP.md live block, goal G4 (L-ML-LIVE, L-REGIME, frontier track, L-DATA).")
    d.end_md()

    s = d.new("Roadmap 3 — the learning machine",
              "The last part of the roadmap is about the machine that does the improving: prop accounts that "
              "qualify on their own, plumbing that can be trusted, a research queue that turns evidence into "
              "decisions without the operator in the path, and a slower macro and value sleeve. This is where "
              "the deck ends: no request, just the plan.")
    d.cards(s, [
        ("Prop accounts", ["Automate, protect and qualify the prop-firm accounts."]),
        ("Trustworthy plumbing", ["Every position protected, every close explained, every number labelled."]),
        ("Research machine", ["Evidence turns into decisions on its own: questions run, get graded, and "
                              "act."]),
        ("Macro and value", ["A slower, thesis-driven sleeve expressed through defined-risk options."]),
    ], cols=2, size=16)
    d.footnote(s, "Source: ROADMAP.md live block, goals G2, G3, G5, G6.")
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
            col_w=[4.2, 2, 1.2, 1.8, 2.4], size=14, h_row=Inches(0.5))
    d.footnote(s, "MEASURED: comms/strategy_evidence/<leg>.json fields net_r_oos, n_trades_oos, "
                  "path_stats.max_drawdown_r, basis. Windows differ by leg (slide 16).", y=H - Inches(1.1))
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
    ], col_w=[2.4, 8], size=14, h_row=Inches(0.5))
    d.end_md()

    s = d.new("Appendix E — sources and provenance",
              "Where every number in the deck came from. The deck is generated by a script that reads these files "
              "directly, so re-running it refreshes the numbers.")
    d.bullets(s, [
        f"Built {f['date']} from repo commit {f['sha']} by docs/pitch/build_deck.py (numbers are computed, not typed).",
        "Leg counts and statuses: scripts/ops/strategy_status.py over config/strategies.yaml + config/accounts.yaml.",
        "Accounts, prop accounts, modes: config/accounts.yaml. Mandates: config/mandates.yaml.",
        "Backtest evidence: comms/strategy_evidence/*.json (out of sample, net of the full cost stack).",
        "Research queue: research/queue/*.yaml status fields.",
        "Concepts and rules: docs/plans/OPERATING-PLAN-2026-09-21.md, docs/ARCHITECTURE-CANONICAL.md, ROADMAP.md.",
        "Left out on purpose: live and paper profit figures (a live book never establishes edge, and they were "
        "not re-verified for this build), and every dollar amount, balance, account id and server address.",
    ], size=16, gap=8)
    d.end_md()

    d.p.save(OUT_PPTX)
    header = ("# JTA Trader — pitch deck: markdown source and speaker notes\n\n"
              "> **Doc status:** `live` · category `unknown` · last verified `2026-11-04` · registered in "
              "[`docs/DOCUMENT-INDEX.md`](../DOCUMENT-INDEX.md)\n\n"
              "Generated by [`build_deck.py`](build_deck.py) together with "
              "[`jta-trader-pitch-deck.pptx`](jta-trader-pitch-deck.pptx) (row `PROJECT-PITCH-DECK`). "
              "Do not hand-edit: change the builder and re-run `python3 docs/pitch/build_deck.py`. "
              f"Built from commit `{f['sha']}` on {f['date']}; {d.n} slides.\n\n"
              "Audience: a smart non-expert. Numbers: ratios only (R, %, counts), each tagged MEASURED or "
              "ESTIMATED; no dollar amounts, balances, account ids, hosts or addresses.\n")
    with open(OUT_MD, "w") as fh:
        fh.write(header + "\n".join(d.md) + "\n")
    print(f"wrote {OUT_PPTX} ({d.n} slides) and {OUT_MD}")


if __name__ == "__main__":
    build()
