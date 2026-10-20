"""The final audit report, as a PDF built from one saved audit record.

Input is Component-03's record (``c03_audit_results``, schema_version 1, see
Component-03/docs/c4_report_contract.md). Every verdict, score, finding and
recommendation is taken from the record as C3 decided it; this module only
lays it out. The AI-written ``narrative`` is shown as clearly labelled
commentary, never as a decision.

Style: a plain corporate document — standard fonts (Times headings, Helvetica
text), document-sized type, generous margins, hairline rules instead of filled
boxes, and colour only where it carries meaning (the verdict and each result).

Page flow:
  page 1   letterhead, title, verdict and score, key details,
           1 Executive summary (with key figures and the analyst commentary)
  page 2+  2 Scope and evidence, 3 Detailed findings, 4 Recommendations,
           auditor sign-off — tables split across pages with their headers repeated
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette: near-black text, warm greys, the NOMOS brown as the one accent ──

INK = colors.HexColor("#1f1a15")
TEXT = colors.HexColor("#3a332b")
MUTED = colors.HexColor("#857a6e")
SOFT = colors.HexColor("#a39a90")
RULE = colors.HexColor("#d9d2c8")
HAIR = colors.HexColor("#e8e3dc")
BROWN = colors.HexColor("#3d3429")
SUCCESS = colors.HexColor("#3d7a4a")
WARNING = colors.HexColor("#9a6a22")
DANGER = colors.HexColor("#a33b3b")
INFO = colors.HexColor("#4a7090")

PAGE_W, PAGE_H = A4
SIDE = 24 * mm
TOP = 30 * mm      # below the letterhead
BOTTOM = 24 * mm   # above the footer
CONTENT_W = PAGE_W - 2 * SIDE

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
    base = {"fontName": "Helvetica", "fontSize": 9.4, "leading": 14, "textColor": TEXT}
    return ParagraphStyle(name, **{**base, **kw})


S = {
    "body": _style("body"),
    "lead": _style("lead", fontSize=10, leading=15, textColor=INK),
    "verdict": _style("verdict", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=INK),
    "small": _style("small", fontSize=7.8, leading=11, textColor=MUTED),
    "label": _style("label", fontSize=7.4, leading=10, textColor=MUTED),
    "value": _style("value", fontSize=9.2, leading=12.5, textColor=INK),
    "cell": _style("cell", fontSize=8.4, leading=11.6),
    "cell_b": _style("cell_b", fontName="Helvetica-Bold", fontSize=8.4, leading=11.6, textColor=INK),
    "cell_muted": _style("cell_muted", fontSize=7.6, leading=10.4, textColor=MUTED),
    "th": _style("th", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED),
    "title": _style("title", fontName="Times-Bold", fontSize=20, leading=24, textColor=INK),
    "subtitle": _style("subtitle", fontSize=9.6, leading=14, textColor=MUTED),
    "h1": _style("h1", fontName="Times-Bold", fontSize=13.5, leading=17, textColor=INK, spaceAfter=2),
    "h2": _style("h2", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=INK),
    "figure_n": _style("figure_n", fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=INK),
    "figure_l": _style("figure_l", fontSize=7.4, leading=9.5, textColor=MUTED),
    "commentary": _style("commentary", fontName="Times-Roman", fontSize=10.2, leading=15.2, textColor=TEXT),
}


def _p(text: object, style: str = "body", color: colors.Color | None = None) -> Paragraph:
    """A paragraph of record text — always escaped, never interpreted as markup."""
    st = S[style] if color is None else ParagraphStyle(f"{style}-c", parent=S[style], textColor=color)
    return Paragraph(escape(str(text if text is not None else "")), st)


def _word(text: str, color: colors.Color, style: str = "cell_b") -> Paragraph:
    """A coloured word (a result or a severity): colour carries the meaning, no badge."""
    return _p(text, style, color)


# ── Small helpers ──────────────────────────────────────────────────────

def _date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return dt.strftime("%d %B %Y, %H:%M UTC")


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


def _table(rows: list, widths: list[float]) -> Table:
    """A quiet table: small grey header over a rule, hairlines between rows, no fills."""
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, HAIR),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, RULE),
    ]))
    return t


def _section(number: int, title: str) -> list:
    return [CondPageBreak(36 * mm), Spacer(1, 4),
            Paragraph(f'<font color="{_hex(SOFT)}">{number}.</font>&nbsp; {escape(title)}', S["h1"]),
            _Hair(), Spacer(1, 7)]


def _hex(c: colors.Color) -> str:
    return c.hexval().replace("0x", "#")


class _Hair(Table):
    """A full-width hairline under a section title."""

    def __init__(self):
        super().__init__([[""]], colWidths=[CONTENT_W], rowHeights=[3])
        self.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, RULE),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))


# ── Page furniture ─────────────────────────────────────────────────────

def _canvas_class(meta: dict):
    """Letterhead, running header and 'Page X of Y' footer on every page."""

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
            top = PAGE_H - 16 * mm
            # letterhead: wordmark left, document name right, one hairline
            self.setFillColor(BROWN)
            self.setFont("Times-Bold", 13 if page == 1 else 10.5)
            self.drawString(SIDE, top, "NOMOS")
            self.setFont("Helvetica", 7.6)
            self.setFillColor(MUTED)
            if page == 1:
                self.drawRightString(PAGE_W - SIDE, top + 2.6 * mm, "AUDIT REPORT")
                self.drawRightString(PAGE_W - SIDE, top - 1 * mm, meta["report_id"])
            else:
                self.drawRightString(PAGE_W - SIDE, top,
                                     f"Audit report  ·  {meta['case_id']}  ·  version {meta['version']}")
            self.setStrokeColor(RULE)
            self.setLineWidth(0.6)
            self.line(SIDE, top - 4 * mm, PAGE_W - SIDE, top - 4 * mm)
            # footer
            self.setStrokeColor(HAIR)
            self.line(SIDE, 15 * mm, PAGE_W - SIDE, 15 * mm)
            self.setFont("Helvetica", 7.2)
            self.setFillColor(SOFT)
            self.drawString(SIDE, 10.5 * mm,
                            f"Confidential  ·  {meta['report_id']}  ·  audit record {meta['audit_id']}")
            self.drawRightString(PAGE_W - SIDE, 10.5 * mm, f"Page {page} of {total}")

    return NumberedCanvas


# ── Page 1: overview ───────────────────────────────────────────────────

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


def _overview(rec: dict, meta: dict, counts: dict) -> list:
    label, color = VERDICTS.get(rec.get("verdict"), ("Unknown", MUTED))
    score = rec.get("score")
    out = [_p("Audit Report", "title"), Spacer(1, 3),
           _p(f"Case {rec.get('case_id', '')}  ·  Version {rec.get('version')}  ·  "
              f"audited {_date(rec.get('created_at'))}", "subtitle"),
           Spacer(1, 16)]

    # verdict and score: two quiet columns over a rule, colour only on the verdict
    head = Table(
        [[_p("Overall verdict", "label"), _p("Audit score", "label")],
         [_p(label, "verdict", color),
          Paragraph(f'<font color="{_hex(INK)}">{escape("—" if score is None else str(score))}</font>'
                    f'<font name="Helvetica" color="{_hex(SOFT)}"> / 100</font>', S["verdict"])]],
        colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4])
    head.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, RULE), ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, RULE), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    out += [head, Spacer(1, 10)]

    kg = "Live Knowledge Graph (C02)" if rec.get("kg_source") == "live" else "Offline rule set"
    status = str(rec.get("status") or "").replace("_", " ").capitalize() or "—"
    details = [("Report ID", meta["report_id"]), ("Audit ID", meta["audit_id"]),
               ("Report date", meta["generated"]), ("Audit date", _date(rec.get("created_at"))),
               ("Status", status), ("Rules source", kg),
               ("Materiality", _money((rec.get("case") or {}).get("materiality"))),
               ("Documents examined", counts["documents"])]
    rows = []
    for i in range(0, len(details), 2):
        row = []
        for k, v in details[i:i + 2]:
            row += [_p(k, "label"), _p(v, "value")]
        rows.append(row)
    w = CONTENT_W / 2
    grid = Table(rows, colWidths=[w * 0.38, w * 0.62, w * 0.38, w * 0.62])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("TOPPADDING", (0, 0), (0, 0), 3.5),
        ("LINEBELOW", (0, -1), (-1, -1), 0.35, HAIR), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
    ]))
    out.append(grid)
    return out


def _summary(rec: dict, counts: dict) -> list:
    out = _section(1, "Executive summary")
    out += [_p(_verdict_statement(rec, counts["failed_rules"], counts["reviews"]), "lead"), Spacer(1, 6),
            _p(rec.get("summary") or "", "body"), Spacer(1, 14)]

    figures = [("Documents", counts["documents"], INK), ("Rules evaluated", counts["rules"], INK),
               ("Passed", counts["passed"], SUCCESS if counts["passed"] else INK),
               ("Failed", counts["failed"], DANGER if counts["failed"] else INK),
               ("Not run", counts["skipped"], INK), ("Findings", counts["findings"], INK)]
    t = Table([[_p(n, "figure_n", c) for _, n, c in figures],
               [_p(label, "figure_l") for label, _, _ in figures]],
              colWidths=[CONTENT_W / len(figures)] * len(figures))
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEABOVE", (0, 0), (-1, 0), 0.35, HAIR), ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("LINEBELOW", (0, -1), (-1, -1), 0.35, HAIR), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    out.append(t)

    sev = counts["severity"]
    if counts["findings"]:
        parts = [f"{sev[s]} {s}" for s in ("high", "medium", "low") if sev.get(s)]
        text = "Findings by severity: " + (", ".join(parts) if parts else "none")
        if counts["reviews"]:
            text += f"; {counts['reviews']} review item(s)"
        out += [Spacer(1, 6), _p(text + ".", "small")]

    if rec.get("narrative"):
        out += [Spacer(1, 18), _p("Analyst commentary", "h2"), Spacer(1, 6),
                _p(rec["narrative"], "commentary"), Spacer(1, 7),
                _p("Written by the AI assistant from the audit facts. The verdict, score, findings and "
                   "recommendations come from rule evaluation, not from this commentary.", "small")]
    return out


# ── Page 2 onwards: the detail ─────────────────────────────────────────

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
            Spacer(1, 10)]
    if not docs:
        return out + [_p("No documents were part of this audit.", "small")]
    rows = [[_p("#", "th"), _p("DOCUMENT", "th"), _p("TYPE", "th"), _p("PERIOD", "th"),
             _p("EVIDENCE SOURCE", "th")]]
    for i, d in enumerate(docs, 1):
        doc_cell = [_p(d.get("name") or d.get("doc_id"), "cell_b")]
        if d.get("parent_doc_id"):
            doc_cell.append(_p(f"Supports {names.get(d['parent_doc_id'], d['parent_doc_id'])}", "cell_muted"))
        doc_cell.append(_p(f"{len(d.get('fields') or {})} value(s) read", "cell_muted"))
        rows.append([_p(i, "cell_muted"), doc_cell, _p(_doc_type(d.get("doc_type")), "cell"),
                     _p(d.get("period_year") or "—", "cell"), _p(_source(d), "cell")])
    out.append(_table(rows, [8 * mm, CONTENT_W - 8 * mm - 30 * mm - 16 * mm - 48 * mm,
                             30 * mm, 16 * mm, 48 * mm]))
    return out


def _findings(rec: dict, names: dict) -> list:
    out = _section(3, "Detailed findings")
    findings = rec.get("findings") or []
    out += [_p("Exceptions raised", "h2"), Spacer(1, 6)]
    if not findings:
        out.append(_p("No exceptions were raised by the rules evaluated in this audit.", "body"))
    else:
        order = {"high": 0, "medium": 1, "low": 2}
        rows = [[_p("SEVERITY", "th"), _p("RULE", "th"), _p("FINDING", "th"), _p("BASIS", "th")]]
        for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 3)):
            sev = str(f.get("severity") or "low")
            rule = [_p(f.get("rule_id"), "cell_b")]
            if str(f.get("rule_id", "")).startswith("REV-"):
                rule.append(_p("Review item", "cell_muted"))
            rows.append([_word(sev.capitalize(), SEVERITIES.get(sev, MUTED)), rule,
                         _p(f.get("message"), "cell"),
                         _p(", ".join(f.get("policy_ids") or []) or "—", "cell_muted")])
        out.append(_table(rows, [18 * mm, 22 * mm, CONTENT_W - 18 * mm - 22 * mm - 24 * mm, 24 * mm]))

    applied = rec.get("rules_applied") or []
    out += [Spacer(1, 12), _p("Rule-by-rule results", "h2"), Spacer(1, 3),
            _p("Every rule evaluated on every document, including those that passed. Rules marked "
               "“Not run” lacked an input value and could not be checked.", "small")]
    if not applied:
        return out + [Spacer(1, 6), _p("No rules were evaluated.", "body")]

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
            rows.append([rule, _word(label, color), _p(r.get("detail") or r.get("expression") or "—", "cell"),
                         _p(_explain(r), "cell")])
        title = names.get(doc_id) or doc_id or "Case-level rules"
        block = [Spacer(1, 10), _p(title, "cell_b"), Spacer(1, 5),
                 _table(rows, [36 * mm, 22 * mm, (CONTENT_W - 58 * mm) * 0.52, (CONTENT_W - 58 * mm) * 0.48])]
        # a short table stays on one page with its document name; a long one splits, header repeated
        out += [KeepTogether(block)] if len(rules) <= 8 else block
    return out


def _explain(r: dict) -> str:
    outcome = r.get("outcome")
    if outcome == "passed":
        if r.get("approvals_required") is not None and (r.get("approvals_signed") or 0) > 0:
            return (f"Above the limit, but the required approvals are in place "
                    f"({r.get('approvals_signed'):g} of {r['approvals_required']} signed).")
        return "Condition met."
    if outcome == "failed":
        text = f"Exception raised ({r.get('severity') or '—'} severity)."
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
    out += [_p("Actions to resolve each finding, most severe first.", "body"), Spacer(1, 10)]
    rows = [[_p("#", "th"), _p("PRIORITY", "th"), _p("ACTION", "th"), _p("RELATES TO", "th")]]
    for i, r in enumerate(recs, 1):
        sev = str(r.get("severity") or "low")
        f = findings_by_id.get(r.get("finding_id")) or {}
        docs = ", ".join(names.get(e, e) for e in f.get("evidence_ids") or [])
        relates = [_p(r.get("rule_id"), "cell_b")] + ([_p(docs, "cell_muted")] if docs else [])
        rows.append([_p(i, "cell_muted"), _word(sev.capitalize(), SEVERITIES.get(sev, MUTED)),
                     _p(r.get("text"), "cell"), relates])
    out.append(_table(rows, [8 * mm, 20 * mm, CONTENT_W - 8 * mm - 20 * mm - 46 * mm, 46 * mm]))
    return out


def _sign_off(meta: dict) -> list:
    lines = Table([[_p("Reviewed by", "label"), "", _p("Date", "label"), "", _p("Signature", "label")],
                   [Spacer(1, 16), "", Spacer(1, 16), "", Spacer(1, 16)]],
                  colWidths=[CONTENT_W * 0.38, CONTENT_W * 0.05, CONTENT_W * 0.2, CONTENT_W * 0.05,
                             CONTENT_W * 0.32])
    lines.setStyle(TableStyle([
        ("LINEBELOW", (0, 1), (0, 1), 0.6, MUTED), ("LINEBELOW", (2, 1), (2, 1), 0.6, MUTED),
        ("LINEBELOW", (4, 1), (4, 1), 0.6, MUTED),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    disclaimer = (f"This report was generated by NOMOS on {meta['generated']} from the saved audit "
                  f"record {meta['audit_id']}. The verdict, score, findings and recommendations are "
                  "determined by rule evaluation in code and are reproducible from that record; the "
                  "analyst commentary is AI-written from the same facts. The report supports, and does "
                  "not replace, the judgement of a qualified auditor, and must be reviewed before reliance.")
    return [Spacer(1, 16), KeepTogether([_p("Auditor sign-off", "h2"), Spacer(1, 8), lines,
                                         Spacer(1, 12), _p(disclaimer, "small")])]


# ── Public API ─────────────────────────────────────────────────────────

def _counts(rec: dict) -> dict:
    applied = rec.get("rules_applied") or []
    findings = rec.get("findings") or []

    def by(outcome: str) -> int:
        return sum(1 for r in applied if r.get("outcome") == outcome)

    def review(f: dict) -> bool:
        return str(f.get("rule_id", "")).startswith("REV-")

    severity: dict[str, int] = {}
    for f in findings:
        if not review(f):
            severity[f.get("severity")] = severity.get(f.get("severity"), 0) + 1
    return {
        "documents": len((rec.get("case") or {}).get("docs") or []),
        "rules": len(applied), "passed": by("passed"), "failed": by("failed") + by("error"),
        "skipped": by("skipped"), "findings": len(findings),
        "failed_rules": sum(1 for f in findings if not review(f)),
        "reviews": sum(1 for f in findings if review(f)) + by("review"),
        "severity": severity,
    }


def build_audit_report(record: dict, *, report_id: str, generated_at: datetime,
                       compress: bool = True) -> bytes:
    """The PDF for one audit record (schema_version 1)."""
    meta = {"report_id": report_id, "audit_id": str(record.get("_id") or ""),
            "case_id": str(record.get("case_id") or ""), "version": record.get("version"),
            "generated": generated_at.strftime("%d %B %Y, %H:%M UTC")}
    docs = (record.get("case") or {}).get("docs") or []
    names = {d.get("doc_id"): d.get("name") or d.get("doc_id") for d in docs}
    findings_by_id = {f.get("finding_id"): f for f in record.get("findings") or []}
    counts = _counts(record)

    buf = BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=SIDE, rightMargin=SIDE, topMargin=TOP, bottomMargin=BOTTOM,
        title=f"Audit report {meta['case_id']} v{meta['version']}", author="NOMOS",
        subject=f"Audit record {meta['audit_id']}", creator="NOMOS Component 04",
        pageCompression=1 if compress else 0, invariant=0)
    frame = Frame(SIDE, BOTTOM, CONTENT_W, PAGE_H - TOP - BOTTOM, id="body", showBoundary=0,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])

    story: list = [NextPageTemplate("page")]
    story += _overview(record, meta, counts)
    story += _summary(record, counts)
    story.append(PageBreak())  # page 1 is the executive overview; the detail starts on page 2
    story += _scope(record, names)
    story += _findings(record, names)
    story += _recommendations(record, findings_by_id, names)
    story += _sign_off(meta)
    doc.build(story, canvasmaker=_canvas_class(meta))
    return buf.getvalue()
