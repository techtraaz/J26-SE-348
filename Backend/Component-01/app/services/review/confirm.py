"""Confirmation (M5): turn the reviewer's draft into an immutable verified
version, log every human action, and read verified versions back.

Confirming accepts every line nobody acted on (decision 2026-10-19): C3
treats each line of a verified record as human-confirmed, so the record must
not hold lines without a human action. Deleted lines are left out of the
record's `lines` (kept in `data.deleted` for the audit trail).

Corrections compare each line with its previous state: the machine region
for version 1, the previous verified version after that. So a reopened and
re-confirmed document logs only what changed since the last confirmation.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import DocumentStatus
from app.db.models import Correction, Document, Region, VerifiedRecord
from app.schemas.review import DraftLine, VerifiedLine, VerifiedRecordOut
from app.services.review.drafts import DraftError, get_draft, require_run, write_draft


@dataclass(frozen=True)
class _State:
    """What a line looked like before this confirmation."""

    text: str
    box: list[int]
    deleted: bool
    reviewed: bool  # a person had already acted on it


# ---- read ------------------------------------------------------------------


def latest_record(db: Session, document: Document) -> VerifiedRecord | None:
    return db.scalars(
        select(VerifiedRecord)
        .where(VerifiedRecord.document_id == document.id)
        .order_by(VerifiedRecord.version.desc())
        .limit(1)
    ).first()


def record_out(record: VerifiedRecord) -> VerifiedRecordOut:
    return VerifiedRecordOut(
        document_id=record.document_id,
        version=record.version,
        based_on_run_id=record.based_on_run_id,
        confirmed_by=record.confirmed_by,
        confirmed_at=record.confirmed_at,
        lines=[VerifiedLine.model_validate(line) for line in record.data["lines"]],
    )


def get_record(db: Session, document: Document, version: int | None = None) -> VerifiedRecordOut:
    """The latest verified version, or one by number."""
    if version is None:
        record = latest_record(db, document)
        if record is None:
            raise DraftError("not_verified", "This document has no verified version yet.")
    else:
        record = db.scalar(
            select(VerifiedRecord).where(
                VerifiedRecord.document_id == document.id, VerifiedRecord.version == version
            )
        )
        if record is None:
            raise DraftError("version_not_found", f"Verified version {version} does not exist.")
    return record_out(record)


# ---- confirm ---------------------------------------------------------------


def _baseline(db: Session, document: Document, run_id, previous: VerifiedRecord | None) -> dict[str, _State]:
    """Each line's state before this confirmation, by line id."""
    if previous is None:
        regions = db.scalars(select(Region).where(Region.run_id == run_id))
        return {str(r.id): _State(r.text, list(r.box), deleted=False, reviewed=False) for r in regions}
    states = {
        line["line_id"]: _State(line["text"], list(line["box"]), deleted=False, reviewed=True)
        for line in previous.data["lines"]
    }
    for line in previous.data.get("deleted", []):
        states[line["line_id"]] = _State(line["text"], list(line["box"]), deleted=True, reviewed=True)
    return states


def _corrections(lines: list[DraftLine], baseline: dict[str, _State]) -> list[dict]:
    """The human actions since the baseline, one entry each."""
    out: list[dict] = []

    def log(line_id: str, region_id, action: str, before: dict | None, after: dict | None) -> None:
        out.append({"line_id": line_id, "region_id": region_id, "action": action, "before": before, "after": after})

    seen: set[str] = set()
    for line in lines:
        line_id = str(line.line_id)
        seen.add(line_id)
        deleted = line.human_action == "deleted"
        current = {"text": line.text, "box": list(line.box)}
        before = baseline.get(line_id)

        if before is None:  # added since the baseline
            if not deleted:
                log(line_id, None, "add", None, {**current, "page": line.page})
            continue
        was = {"text": before.text, "box": before.box}
        if deleted:
            if not before.deleted:
                log(line_id, line.region_id, "delete", was, None)
            continue
        if before.deleted:
            log(line_id, line.region_id, "restore", None, current)
        if line.text != before.text:
            log(line_id, line.region_id, "edit_text", {"text": before.text}, {"text": line.text})
        if list(line.box) != before.box:
            log(line_id, line.region_id, "move_box", {"box": before.box}, {"box": list(line.box)})
        if line.human_action == "accepted" and not before.reviewed:
            log(line_id, line.region_id, "accept", None, {"text": line.text})

    # An added line from an earlier version that the draft no longer has.
    for line_id, state in baseline.items():
        if line_id not in seen and not state.deleted:
            log(line_id, None, "delete", {"text": state.text, "box": state.box}, None)
    return out


def _contract_line(line: DraftLine) -> dict:
    return VerifiedLine.model_validate(line.model_dump()).model_dump(mode="json")


def confirm(db: Session, document: Document, version: int) -> VerifiedRecordOut:
    """Freeze the draft at `version` as the next verified version."""
    if document.status == DocumentStatus.VERIFIED.value:
        raise DraftError("already_verified", "This document is already verified. Reopen it to make changes.")
    run = require_run(document)
    if document.status != DocumentStatus.NEEDS_REVIEW.value:
        raise DraftError("extraction_not_ready", f"The document is not ready for review (status: {document.status}).")

    draft = get_draft(db, document)  # saved, or seeded (version 0)
    if draft.based_on_run_id != run.id:
        raise DraftError("run_changed", "The document was extracted again. Reload to review the new result.")
    if draft.version != version:
        raise DraftError("draft_conflict", "This draft changed since you opened it. Reload before confirming.")

    # Confirming vouches for the whole document: untouched lines become accepted.
    lines = [
        line.model_copy(update={"human_action": "accepted"}) if line.human_action == "untouched" else line
        for line in draft.lines
    ]
    previous = latest_record(db, document)
    new_version = (previous.version if previous else 0) + 1
    baseline = _baseline(db, document, run.id, previous)

    db.add(
        VerifiedRecord(
            document_id=document.id,
            version=new_version,
            based_on_run_id=run.id,
            data={
                "lines": [_contract_line(line) for line in lines if line.human_action != "deleted"],
                "deleted": [line.model_dump(mode="json") for line in lines if line.human_action == "deleted"],
            },
            confirmed_by=None,  # no authentication yet (O3)
        )
    )
    for entry in _corrections(lines, baseline):
        db.add(
            Correction(
                document_id=document.id,
                region_id=entry["region_id"],
                action=entry["action"],
                before=entry["before"],
                after={**(entry["after"] or {}), "line_id": entry["line_id"]},
                source=document.source,
                by=None,
                verified_version=new_version,
            )
        )
    # The draft continues from the confirmed state if the document is reopened.
    write_draft(db, document, run, lines, version)
    document.status = DocumentStatus.VERIFIED.value
    try:
        db.commit()
    except IntegrityError:  # a simultaneous confirmation took this version number
        db.rollback()
        raise DraftError("draft_conflict", "This document was confirmed elsewhere. Reload to see it.") from None

    db.expire_all()
    return get_record(db, document, new_version)


def reopen(db: Session, document: Document) -> None:
    """Back to review; the next confirmation creates a new version."""
    if document.status != DocumentStatus.VERIFIED.value:
        raise DraftError("not_reopenable", "Only a verified document can be reopened.")
    document.status = DocumentStatus.NEEDS_REVIEW.value
    db.commit()
