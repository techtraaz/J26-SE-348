"""Downstream contract 0.1 (UC6): a verified record as other components and
people receive it.

The shape is C3's proposal (Backend/Component-03/docs/c1_verified_record_contract.md),
returned as is by GET /documents/{id}/verified. This module is the mapping
layer the plan keeps replaceable: when the contract changes (O2), only this
file and SCHEMA_VERSION change, not the stored records.
"""

import csv
import io

from app.schemas.review import VerifiedRecordOut

SCHEMA_VERSION = "0.1"

CSV_COLUMNS = [
    "document_id", "version", "line_id", "page", "sequence", "text", "confidence",
    "x1", "y1", "x2", "y2", "provenance", "escalated", "human_action",
]


def to_json(record: VerifiedRecordOut) -> dict:
    """The record as the contract defines it, tagged with its schema version."""
    return {"schema_version": SCHEMA_VERSION, **record.model_dump(mode="json")}


def to_csv(record: VerifiedRecordOut) -> str:
    """One row per line, for people (spreadsheets). Starts with a byte order
    mark so Excel reads the UTF-8 text (accents, currency signs) correctly."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for line in record.lines:
        x1, y1, x2, y2 = line.box
        writer.writerow([
            record.document_id, record.version, line.line_id, line.page, line.sequence, line.text,
            "" if line.confidence is None else line.confidence,
            x1, y1, x2, y2, line.provenance,
            "" if line.escalated is None else line.escalated,
            line.human_action,
        ])
    return "﻿" + out.getvalue()
