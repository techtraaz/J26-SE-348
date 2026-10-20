"""The final audit report, as a PDF built from one saved audit record.

Input is Component-03's record (``c03_audit_results``, schema_version 1, see
Component-03/docs/c4_report_contract.md). Every verdict, score, finding and
recommendation is taken from the record as C3 decided it; this module only
lays it out. The AI-written ``narrative`` is shown as clearly labelled
commentary, never as a decision.

Layout (A4, corporate style in the NOMOS palette):
  header band     NOMOS, report id, generation date
  verdict card    verdict, audit score with a bar, key details
  1 Executive summary      verdict statement, C3's summary, key figures, commentary
  2 Scope and evidence     documents examined, with their source and verification
  3 Detailed findings      exceptions raised, then every rule on every document
  4 Recommendations        C3's actions, most severe first
  sign-off                 reviewer, date, signature lines and a disclaimer
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette (NOMOS) ────────────────────────────────────────────────────

INK = colors.HexColor("#1a1410")
TEXT = colors.HexColor("#3d3429")
BROWN = colors.HexColor("#3d3429")
MUTED = colors.HexColor("#8a7e72")
SOFT = colors.HexColor("#a69d93")
LINE = colors.HexColor("#ddd7ce")
LINE_LIGHT = colors.HexColor("#ebe6df")
PANEL = colors.HexColor("#faf7f3")
TINT = colors.HexColor("#f3eee7")
CREAM = colors.HexColor("#f5f0ea")
CREAM_DIM = colors.HexColor("#cfc4b6")
SUCCESS = colors.HexColor("#3d7a4a")
WARNING = colors.HexColor("#b07c2e")
DANGER = colors.HexColor("#a33b3b")
INFO = colors.HexColor("#4a7090")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
BAND_H = 40 * mm

VERDICTS = {
    "clean": ("Clean", SUCCESS),
    "issues_found": ("Issues found", DANGER),
    "needs_review": ("Needs review", WARNING),
    "not_auditable": ("Not auditable", MUTED),
}
OUTCOMES = {  # rules_applied outcome -> (label, colour, sort order)
    "failed": ("Failed", DANGER, 0),
    "error": ("Not evaluated", DANGER, 1),
    "review": ("Needs review", WARNING, 2),
    "passed": ("Passed", SUCCESS, 3),
    "skipped": ("Not run", SOFT, 4),
}
SEVERITIES = {"high": DANGER, "medium": WARNING, "low": INFO}
DOC_TYPES = {"balance_sheet": "Balance sheet", "income_statement": "Income statement",
             "purchase_order": "Purchase order", "goods_received_note": "Goods received note"}


# ── Text styles ────────────────────────────────────────────────────────

def _style(name: str, **kw) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 9.2, "leading": 13.2, "textColor": TEXT}
    return ParagraphStyle(name, **{**base, **kw})


S = {
    "body": _style("body"),
    "lead": _style("lead", fontSize=10.2, leading=15),
    "small": _style("small", fontSize=7.8, leading=10.5, textColor=MUTED),
    "label": _style("label", fontName="Helvetica-Bold", fontSize=6.8, leading=9, textColor=MUTED),
    "value": _style("value", fontSize=9, leading=12, textColor=INK),
    "cell": _style("cell", fontSize=8.2, leading=11),
    "cell_b": _style("cell_b", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=INK),
    "cell_muted": _style("cell_muted", fontSize=7.6, leading=10, textColor=MUTED),
    "th": _style("th", fontName="Helvetica-Bold", fontSize=7.2, leading=9.5, textColor=MUTED),
    "h1": _style("h1", fontName="Times-Bold", fontSize=15.5, leading=19, textColor=INK,
                 spaceBefore=16, spaceAfter=7),
    "h2": _style("h2", fontName="Helvetica-Bold", fontSize=9.6, leading=13, textColor=INK,
                 spaceBefore=10, spaceAfter=5),
    "title": _style("title", fontName="Times-Bold", fontSize=21, leading=25, textColor=INK),
    "subtitle": _style("subtitle", fontSize=9.4, leading=13, textColor=MUTED),
    "verdict": _style("verdict", fontName="Times-Bold", fontSize=19, leading=23),
    "score": _style("score", fontName="Helvetica-Bold", fontSize=30, leading=32, alignment=TA_RIGHT),
    "tile_n": _style("tile_n", fontName="Helvetica-Bold", fontSize=17, leading=20, alignment=TA_CENTER,
                     textColor=INK),
    "tile_l": _style("tile_l", fontSize=7.2, leading=9, alignment=TA_CENTER, textColor=MUTED),
    "quote": _style("quote", fontSize=9.2, leading=13.6, textColor=TEXT),
}


def _p(text: object, style: str = "body", color: colors.Color | None = None) -> Paragraph:
    """A paragraph of record text — always escaped, never interpreted as markup."""
    st = S[style] if color is None else ParagraphStyle(f"{style}-c", parent=S[style], textColor=color)
    return Paragraph(escape(str(text if text is not None else "")), st)


def _rich(markup: str, style: str = "body") -> Paragraph:
    """A paragraph whose markup is built here (record values inside are escaped)."""
    return Paragraph(markup, S[style])


def _hex(c: colors.Color) -> str:
    return c.hexval().replace("0x", "#")


# ── Small helpers ──────────────────────────────────────────────────────

def _date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return dt.strftime("%d %b %Y, %H:%M UTC")


def _doc_type(t: str | None) -> str:
    if not t or t == "unknown":
        return "Unknown type"
    return DOC_TYPES.get(t, t.replace("_", " ").capitalize())


def _plain(text: str) -> str:
    """'missing cash_out' -> 'Input missing: cash out'."""
    t = (text or "").strip()
    if t.startswith("missing "):
        return "Input missing: " + t.removeprefix("missing ").replace("_", " ").replace(".", " ")
    return t.replace("_", " ") if " " not in t else t


def _money(v: object) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"Rs {v:,.2f}"
    return "Not set"


def _pill(text: str, color: colors.Color, width: float | None = None) -> Table:
    """A small coloured label (e.g. HIGH, FAILED)."""
    t = Table([[Paragraph(escape(text.upper()), ParagraphStyle(
        "pill", fontName="Helvetica-Bold", fontSize=6.6, leading=8, textColor=color, alignment=TA_CENTER))]],
        colWidths=[width] if width else None)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.Color(color.red, color.green, color.blue, alpha=0.1)),
        ("BOX", (0, 0), (-1, -1), 0.6, color),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


class ScoreBar(Flowable):
    """A thin horizontal bar filled to score/100."""

    def __init__(self, score: int | None, color: colors.Color, width: float, height: float = 5):
        super().__init__()
        self.score, self.color, self.width, self.height = score, color, width, height

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(LINE_LIGHT)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        if self.score:
            c.setFillColor(self.color)
            c.roundRect(0, 0, self.width * max(0, min(self.score, 100)) / 100, self.height,
                        self.height / 2, stroke=0, fill=1)


def _table(rows: list, widths: list[float], header: bool = True, zebra: bool = True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
                  ("TOPPADDING", (0, 0), (-1, 0), 4), ("BOTTOMPADDING", (0, 0), (-1, 0), 4)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if (i - (1 if header else 0)) % 2 == 1:
                style.append(("BACKGROUND", (0, i), (-1, i), PANEL))
    t.setStyle(TableStyle(style))
    return t


def _section(number: int, title: str) -> list:
    return [CondPageBreak(42 * mm), _rich(f'<font color="{_hex(SOFT)}">{number:02d}</font>&nbsp;&nbsp;'
                                           f"{escape(title)}", "h1"),
            _Rule(CONTENT_W)]


class _Rule(Flowable):
    """A short accent line under a section title."""

    def __init__(self, width: float):
        super().__init__()
        self.width = width

    def wrap(self, *_):
        return self.width, 7

    def draw(self):
        self.canv.setStrokeColor(LINE)
        self.canv.setLineWidth(0.6)
        self.canv.line(0, 5, self.width, 5)
        self.canv.setStrokeColor(WARNING)
        self.canv.setLineWidth(1.6)
        self.canv.line(0, 5, 26 * mm, 5)


# ── Page furniture ─────────────────────────────────────────────────────

def _canvas_class(meta: dict):
    """A canvas that writes 'Page X of Y' and the running header/footer."""

    class NumberedCanvas(pdf_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._furniture(total)
                super().showPage()
            super().save()

        def _furniture(self, total: int):
            page = self._pageNumber
            if page == 1:
                self._band()
            else:
                self.setFont("Helvetica-Bold", 7.6)
                self.setFillColor(BROWN)
                self.drawString(MARGIN, PAGE_H - 12 * mm, "NOMOS")
                self.setFont("Helvetica", 7.6)
                self.setFillColor(MUTED)
                self.drawString(MARGIN + 12.5 * mm, PAGE_H - 12 * mm,
                                f"Audit report  ·  {meta['case_id']}  ·  version {meta['version']}")
                self.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, meta["report_id"])
                self.setStrokeColor(LINE)
                self.setLineWidth(0.5)
                self.line(MARGIN, PAGE_H - 14.5 * mm, PAGE_W - MARGIN, PAGE_H - 14.5 * mm)
            # footer
            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
            self.setFont("Helvetica", 7.2)
            self.setFillColor(SOFT)
            self.drawString(MARGIN, 9.5 * mm,
                            f"Confidential  ·  Prepared from audit record {meta['audit_id']}")
            self.drawRightString(PAGE_W - MARGIN, 9.5 * mm, f"Page {page} of {total}")

        def _band(self):
            self.setFillColor(BROWN)
            self.rect(0, PAGE_H - BAND_H, PAGE_W, BAND_H, stroke=0, fill=1)
            self.setFillColor(WARNING)
            self.rect(0, PAGE_H - BAND_H - 1.2 * mm, PAGE_W, 1.2 * mm, stroke=0, fill=1)
            self.setFillColor(CREAM)
            self.setFont("Times-Bold", 27)
            self.drawString(MARGIN, PAGE_H - 19 * mm, "NOMOS")
            self.setFont("Helvetica", 9)
            self.setFillColor(CREAM_DIM)
            self.drawString(MARGIN, PAGE_H - 26 * mm, "Audit Report")
            self.drawString(MARGIN, PAGE_H - 31 * mm, "Explainable multi-agent audit")
            self.setFont("Helvetica", 7)
            self.drawRightString(PAGE_W - MARGIN, PAGE_H - 16 * mm, "REPORT ID")
            self.setFont("Helvetica-Bold", 10)
            self.setFillColor(CREAM)
            self.drawRightString(PAGE_W - MARGIN, PAGE_H - 21.5 * mm, meta["report_id"])
            self.setFont("Helvetica", 7)
            self.setFillColor(CREAM_DIM)
            self.drawRightString(PAGE_W - MARGIN, PAGE_H - 28 * mm, "GENERATED")
            self.setFont("Helvetica", 9)
            self.setFillColor(CREAM)
            self.drawRightString(PAGE_W - MARGIN, PAGE_H - 33 * mm, meta["generated"])

    return NumberedCanvas


# ── Sections ───────────────────────────────────────────────────────────

def _verdict_statement(rec: dict, failed: int, reviews: int) -> str:
    verdict = rec.get("verdict")
    if verdict == "clean":
        return ("No exceptions were identified. Every rule that could be evaluated was met, and the "
                "audit can proceed to auditor sign-off.")
    if verdict == "issues_found":
        return (f"The audit identified {failed} rule exception{'s' if failed != 1 else ''} that "
                f"require{'s' if failed == 1 else ''} corrective action before sign-off.")
    if verdict == "needs_review":
        return (f"No rule failed, but {reviews} item{'s' if reviews != 1 else ''} need"
                f"{'s' if reviews == 1 else ''} the auditor's review before the audit can be relied on.")
    return "The documents could not be audited; the reasons are listed under Detailed findings."


def _cover(rec: dict, meta: dict, counts: dict) -> list:
    label, color = VERDICTS.get(rec.get("verdict"), ("Unknown", MUTED))
    score = rec.get("score")
    out = [Spacer(1, BAND_H - MARGIN + 8 * mm),
           _p(f"Case {rec.get('case_id', '')}", "title"),
           Spacer(1, 2),
           _p(f"Audit version {rec.get('version')}  ·  audited {_date(rec.get('created_at'))}", "subtitle"),
           Spacer(1, 10)]

    left = [_p("OVERALL VERDICT", "label"), Spacer(1, 3), _p(label, "verdict", color), Spacer(1, 3),
            _p(_verdict_statement(rec, counts["failed_rules"], counts["reviews"]), "body")]
    score_text = "—" if score is None else str(score)
    right = [_p("AUDIT SCORE", "label"),
             _rich(f'<font color="{_hex(color)}">{escape(score_text)}</font>'
                   f'<font size="11" color="{_hex(SOFT)}"> / 100</font>', "score"),
             Spacer(1, 6), ScoreBar(score, color, 48 * mm)]
    card = Table([[left, right]], colWidths=[CONTENT_W - 62 * mm, 62 * mm])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color), ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("LINEAFTER", (0, 0), (0, -1), 0.5, LINE),
    ]))
    out += [card, Spacer(1, 10)]

    kg = "Live Knowledge Graph (C02)" if rec.get("kg_source") == "live" else "Offline rule set"
    status = str(rec.get("status") or "").replace("_", " ").capitalize() or "—"
    details = [("Report ID", meta["report_id"]), ("Audit ID", meta["audit_id"]),
               ("Case", rec.get("case_id")), ("Audit version", rec.get("version")),
               ("Audit date", _date(rec.get("created_at"))), ("Report date", meta["generated"]),
               ("Status", status), ("Rules source", kg),
               ("Materiality", _money((rec.get("case") or {}).get("materiality"))),
               ("Documents", counts["documents"])]
    cells = [[[_p(k.upper(), "label"), _p(v, "value")] for k, v in details[i:i + 2]]
             for i in range(0, len(details), 2)]
    grid = Table(cells, colWidths=[CONTENT_W / 2] * 2)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    out.append(grid)
    return out


def _summary(rec: dict, counts: dict) -> list:
    out = _section(1, "Executive summary")
    out += [_p(_verdict_statement(rec, counts["failed_rules"], counts["reviews"]), "lead"), Spacer(1, 5),
            _p(rec.get("summary") or "", "body"), Spacer(1, 10)]

    tiles = [("Documents", counts["documents"], INK), ("Rules evaluated", counts["rules"], INK),
             ("Passed", counts["passed"], SUCCESS if counts["passed"] else INK),
             ("Failed", counts["failed"], DANGER if counts["failed"] else INK),
             ("Not run", counts["skipped"], INK), ("Findings", counts["findings"], INK)]
    row = [[_p(n, "tile_n", c), Spacer(1, 2), _p(label, "tile_l")] for label, n, c in tiles]
    t = Table([row], colWidths=[CONTENT_W / len(tiles)] * len(tiles))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.4, LINE_LIGHT), ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    out += [t]

    sev = counts["severity"]
    if counts["findings"]:
        parts = [f"{sev[s]} {s}" for s in ("high", "medium", "low") if sev.get(s)]
        out += [Spacer(1, 6), _p(f"Findings by severity: {', '.join(parts)}"
                                 + (f"; {counts['reviews']} review item(s)." if counts["reviews"] else "."),
                                 "small")]

    if rec.get("narrative"):
        # A bordered paragraph (not a table cell), so long commentary can continue on the next page
        quote = ParagraphStyle("commentary", parent=S["quote"], backColor=PANEL, borderColor=LINE,
                               borderWidth=0.6, borderPadding=(9, 10, 9, 10), borderRadius=4,
                               leftIndent=10, rightIndent=10)
        out += [Spacer(1, 14), _p("ANALYST COMMENTARY", "label"), Spacer(1, 9),
                Paragraph(escape(str(rec["narrative"])), quote), Spacer(1, 12),
                _p("Written by the AI assistant from the audit facts. The verdict, score, findings "
                   "and recommendations come from rule evaluation, not from this text.", "small")]
    return out


def _source(doc: dict) -> str:
    src = doc.get("source") or {}
    if not src:
        return "Values supplied directly"
    comp = str(src.get("component") or "c1").upper()
    if src.get("verified_version") is not None:
        who = f" by {src['confirmed_by']}" if src.get("confirmed_by") else ""
        return f"{comp} verified record, version {src['verified_version']}{who}"
    return f"{comp} extraction, not yet verified by a person"


def _scope(rec: dict, names: dict) -> list:
    docs = (rec.get("case") or {}).get("docs") or []
    out = _section(2, "Scope and evidence")
    out += [_p(f"{len(docs)} document{'s were' if len(docs) != 1 else ' was'} examined in this audit. "
               "Each value used by a rule traces back to the source record listed here.", "body"),
            Spacer(1, 8)]
    if not docs:
        return out + [_p("No documents were part of this audit.", "small")]
    rows = [[_p("#", "th"), _p("DOCUMENT", "th"), _p("TYPE", "th"), _p("PERIOD", "th"),
             _p("EVIDENCE SOURCE", "th")]]
    for i, d in enumerate(docs, 1):
        doc_cell = [_p(d.get("name") or d.get("doc_id"), "cell_b")]
        if d.get("parent_doc_id"):
            doc_cell.append(_p(f"Supports {names.get(d['parent_doc_id'], d['parent_doc_id'])}", "cell_muted"))
        doc_cell.append(_p(f"{len(d.get('fields') or {})} value(s) read", "cell_muted"))
        rows.append([_p(i, "cell"), doc_cell, _p(_doc_type(d.get("doc_type")), "cell"),
                     _p(d.get("period_year") or "—", "cell"), _p(_source(d), "cell")])
    out.append(_table(rows, [8 * mm, CONTENT_W - 8 * mm - 30 * mm - 16 * mm - 52 * mm,
                             30 * mm, 16 * mm, 52 * mm]))
    return out


def _findings(rec: dict, names: dict) -> list:
    out = _section(3, "Detailed findings")
    findings = rec.get("findings") or []
    out.append(_p("Exceptions raised", "h2"))
    if not findings:
        out.append(_p("No exceptions were raised by the rules evaluated in this audit.", "body"))
    else:
        order = {"high": 0, "medium": 1, "low": 2}
        rows = [[_p("SEVERITY", "th"), _p("RULE", "th"), _p("FINDING", "th"), _p("BASIS", "th")]]
        for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 3)):
            sev = str(f.get("severity") or "low")
            review = str(f.get("rule_id", "")).startswith("REV-")
            rule = [_p(f.get("rule_id"), "cell_b")]
            if review:
                rule.append(_p("Review item", "cell_muted"))
            basis = ", ".join(f.get("policy_ids") or []) or "—"
            rows.append([_pill(sev, SEVERITIES.get(sev, MUTED), 15 * mm), rule,
                         _p(f.get("message"), "cell"), _p(basis, "cell_muted")])
        out.append(_table(rows, [21 * mm, 24 * mm, CONTENT_W - 21 * mm - 24 * mm - 26 * mm, 26 * mm]))

    applied = rec.get("rules_applied") or []
    out.append(_p("Rule-by-rule results", "h2"))
    out.append(_p("Every rule evaluated on every document, including those that passed. "
                  "Rules marked “Not run” lacked an input value and could not be checked.", "small"))
    if not applied:
        return out + [Spacer(1, 4), _p("No rules were evaluated.", "body")]

    by_doc: dict[str, list] = {}
    for r in applied:
        by_doc.setdefault(r.get("doc_id") or "", []).append(r)
    for doc_id, rules in by_doc.items():
        rules.sort(key=lambda r: (OUTCOMES.get(r.get("outcome"), ("", MUTED, 9))[2], r.get("rule_id", "")))
        rows = [[_p("RULE", "th"), _p("RESULT", "th"), _p("CALCULATION", "th"), _p("EXPLANATION", "th")]]
        for r in rules:
            label, color, _ = OUTCOMES.get(r.get("outcome"), (str(r.get("outcome")), MUTED, 9))
            rule = [_p(r.get("rule_id"), "cell_b")]
            if r.get("rule_name"):
                rule.append(_p(r["rule_name"], "cell_muted"))
            calc = r.get("detail") or r.get("expression") or "—"
            rows.append([rule, _pill(label, color, 22 * mm), _p(calc, "cell"),
                         _p(_explain(r), "cell")])
        title = names.get(doc_id) or doc_id or "Case-level rules"
        block = [Spacer(1, 6), _rich(f'<font color="{_hex(MUTED)}">Document</font>&nbsp; '
                                     f"<b>{escape(title)}</b>", "body"), Spacer(1, 4),
                 _table(rows, [34 * mm, 26 * mm, (CONTENT_W - 60 * mm) * 0.5, (CONTENT_W - 60 * mm) * 0.5])]
        # short tables stay on one page with their heading; long ones may split (header repeats)
        if len(rules) <= 8:
            out.append(KeepTogether(block))
        else:
            out += block
    return out


def _explain(r: dict) -> str:
    outcome = r.get("outcome")
    if outcome == "passed":
        if r.get("approvals_required") is not None and (r.get("approvals_signed") or 0) > 0:
            return (f"Above the limit, but the required approvals are in place "
                    f"({r.get('approvals_signed'):g} of {r['approvals_required']} signed).")
        return "Condition met."
    if outcome == "failed":
        sev = r.get("severity") or "—"
        text = f"Exception raised ({sev} severity)."
        if r.get("below_materiality"):
            text += " The difference is below the case materiality, so severity was lowered."
        if r.get("approvals_required") is not None:
            text += (f" {r.get('approvals_signed') or 0:g} of {r['approvals_required']} "
                     f"required approvals signed.")
        return text
    if outcome == "skipped":
        return _plain(r.get("reason") or "Input missing.")
    return r.get("reason") or "—"


def _recommendations(rec: dict, findings_by_id: dict, names: dict) -> list:
    out = _section(4, "Recommendations")
    recs = rec.get("recommendations") or []
    if not recs:
        return out + [_p("No corrective action is required. The audit can proceed to auditor sign-off.", "body")]
    out.append(_p("Actions to resolve each finding, most severe first.", "body"))
    out.append(Spacer(1, 7))
    rows = [[_p("#", "th"), _p("PRIORITY", "th"), _p("ACTION", "th"), _p("RELATES TO", "th")]]
    for i, r in enumerate(recs, 1):
        sev = str(r.get("severity") or "low")
        f = findings_by_id.get(r.get("finding_id")) or {}
        docs = ", ".join(names.get(e, e) for e in f.get("evidence_ids") or [])
        relates = [_p(r.get("rule_id"), "cell_b")] + ([_p(docs, "cell_muted")] if docs else [])
        rows.append([_p(i, "cell"), _pill(sev, SEVERITIES.get(sev, MUTED), 16 * mm),
                     _p(r.get("text"), "cell"), relates])
    out.append(_table(rows, [8 * mm, 22 * mm, CONTENT_W - 8 * mm - 22 * mm - 48 * mm, 48 * mm]))
    return out


def _sign_off(rec: dict, meta: dict) -> list:
    line = [[_p("REVIEWED BY", "label"), _p("DATE", "label"), _p("SIGNATURE", "label")],
            [Spacer(1, 18)] * 3]
    t = Table(line, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.22, CONTENT_W * 0.36])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 1), (-1, 1), 0.6, MUTED), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    disclaimer = (f"This report was generated by NOMOS on {meta['generated']} from the saved audit "
                  f"record {meta['audit_id']}. The verdict, score, findings and recommendations are "
                  "determined by rule evaluation in code and are reproducible from that record; the "
                  "analyst commentary is AI-written from the same facts. The report supports, and does "
                  "not replace, the judgement of a qualified auditor, and must be reviewed before reliance.")
    # kept in one piece, and only moved to a new page when it does not fit
    return [Spacer(1, 14), KeepTogether([_p("Auditor sign-off", "h2"), Spacer(1, 6), t,
                                         Spacer(1, 14), _p(disclaimer, "small")])]


# ── Public API ─────────────────────────────────────────────────────────

def _counts(rec: dict) -> dict:
    applied = rec.get("rules_applied") or []
    findings = rec.get("findings") or []

    def by(outcome: str) -> int:
        return sum(1 for r in applied if r.get("outcome") == outcome)

    severity: dict[str, int] = {}
    for f in findings:
        if not str(f.get("rule_id", "")).startswith("REV-"):
            severity[f.get("severity")] = severity.get(f.get("severity"), 0) + 1
    return {
        "documents": len((rec.get("case") or {}).get("docs") or []),
        "rules": len(applied), "passed": by("passed"), "failed": by("failed") + by("error"),
        "skipped": by("skipped"), "findings": len(findings),
        "failed_rules": sum(1 for f in findings if not str(f.get("rule_id", "")).startswith("REV-")),
        "reviews": sum(1 for f in findings if str(f.get("rule_id", "")).startswith("REV-")) + by("review"),
        "severity": severity,
    }


def build_audit_report(record: dict, *, report_id: str, generated_at: datetime,
                       compress: bool = True) -> bytes:
    """The PDF for one audit record (schema_version 1)."""
    meta = {"report_id": report_id, "audit_id": str(record.get("_id") or ""),
            "case_id": str(record.get("case_id") or ""), "version": record.get("version"),
            "generated": generated_at.strftime("%d %b %Y, %H:%M UTC")}
    docs = (record.get("case") or {}).get("docs") or []
    names = {d.get("doc_id"): d.get("name") or d.get("doc_id") for d in docs}
    findings_by_id = {f.get("finding_id"): f for f in record.get("findings") or []}
    counts = _counts(record)

    buf = BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=20 * mm,
        title=f"Audit report {meta['case_id']} v{meta['version']}", author="NOMOS",
        subject=f"Audit record {meta['audit_id']}", creator="NOMOS Component 04",
        pageCompression=1 if compress else 0, invariant=0)
    first = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - 20 * mm - MARGIN, id="first", showBoundary=0)
    later = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - 20 * mm - 22 * mm, id="later", showBoundary=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=[first]),
                          PageTemplate(id="later", frames=[later])])

    story: list = [NextPageTemplate("later")]
    story += _cover(record, meta, counts)
    story += _summary(record, counts)
    story += _scope(record, names)
    story += _findings(record, names)
    story += _recommendations(record, findings_by_id, names)
    story += _sign_off(record, meta)
    doc.build(story, canvasmaker=_canvas_class(meta))
    return buf.getvalue()
