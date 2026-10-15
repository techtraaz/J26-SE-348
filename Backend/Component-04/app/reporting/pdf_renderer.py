"""Deterministic slot-filling PDF report generator.

Fetches verified audit data from the SQLite Middle DB, fills slots in
the Jinja2 HTML template, and converts the result to PDF via xhtml2pdf.

This module owns the full pipeline:
  1. Query DB for audit_run metadata + traces + (future) findings
  2. Build a template context dict
  3. Render HTML from the Jinja2 template
  4. Convert HTML → PDF via xhtml2pdf (pure Python, no system deps)
  5. Save the PDF to the local ``reports/`` directory
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

from app.services import database as db

logger = logging.getLogger("c04.reporting")

# ── Paths ──────────────────────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"

# Jinja2 environment — loaded once, reused
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)


def _ensure_reports_dir() -> Path:
    """Create the reports output directory if it doesn't exist."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORTS_DIR


# ── Slot Filling ───────────────────────────────────────────────────────

def _extract_findings_from_traces(traces: list[dict]) -> list[dict]:
    """Extract inline findings from agent_end trace payloads.

    The raw_payload of each agent_end event may contain findings data
    serialised by C03.  This function parses them out for the report.
    """
    findings: list[dict] = []
    for t in traces:
        if t.get("event_type") != "agent_end":
            continue
        raw = t.get("raw_payload")
        if not raw:
            continue
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            trace_data = payload.get("trace", {})
            # If findings were embedded in the trace, collect them
            if "findings" in payload:
                findings.extend(payload["findings"])
        except (json.JSONDecodeError, TypeError):
            continue
    return findings


def _build_context(
    case_id: str,
    run: dict | None,
    traces: list[dict],
    findings: list[dict] | None = None,
) -> dict:
    """Assemble the template context from DB data."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Try to extract findings from trace payloads if not provided
    if findings is None:
        findings = _extract_findings_from_traces(traces)

    return {
        "case_id": case_id,
        "status": run["status"] if run else "unknown",
        "doc_count": run["doc_count"] if run else 0,
        "total_findings": run["total_findings"] if run else len(findings),
        "started_at": run["started_at"] if run else "N/A",
        "ended_at": run["ended_at"] if run else "N/A",
        "generated_at": now,
        "findings": findings,
        "traces": traces,
    }


# ── Public API ─────────────────────────────────────────────────────────

async def generate_report(case_id: str) -> dict:
    """Generate a PDF audit report for the given case_id.

    Returns a dict with:
      - ``pdf_path``: absolute path to the generated PDF file
      - ``filename``: just the filename for download headers
      - ``case_id``: echo back
      - ``generated_at``: ISO timestamp

    Raises ``ValueError`` if no audit data exists for the case.
    """
    # 1. Fetch data from Middle DB
    runs = await db.get_runs(limit=200)
    run = next((r for r in runs if r["case_id"] == case_id), None)

    traces = await db.get_traces_for_case(case_id)
    if not traces and run is None:
        raise ValueError(f"No audit data found for case_id={case_id!r}")

    # 2. Build the template context
    context = _build_context(case_id, run, traces)

    # 3. Render HTML via Jinja2
    template = _jinja_env.get_template("audit_report.html")
    rendered_html = template.render(**context)

    # 4. Convert HTML → PDF via xhtml2pdf
    out_dir = _ensure_reports_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_report_{case_id}_{timestamp}.pdf"
    pdf_path = out_dir / filename

    with open(pdf_path, "w+b") as pdf_file:
        status = pisa.CreatePDF(rendered_html, dest=pdf_file)
        if status.err:
            raise RuntimeError(f"xhtml2pdf failed to render PDF for case={case_id}")

    logger.info("PDF report generated: %s", pdf_path)

    return {
        "pdf_path": str(pdf_path),
        "filename": filename,
        "case_id": case_id,
        "generated_at": context["generated_at"],
    }
