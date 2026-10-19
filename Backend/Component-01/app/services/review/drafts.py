"""Review drafts (M4): seed a draft from the latest successful run, validate
the reviewer's lines, and save them with optimistic concurrency.

Rules that keep the draft an honest record of human review:
- Every machine region of the run appears exactly once. A false region is
  marked `deleted`, never dropped, so nothing disappears without a trace.
- Machine fields (confidence, provenance, escalated) come from the region,
  not from the client (D2, D4).
- The server decides `edited`: a machine line whose text or box differs from
  its region is edited, whatever the client called it.
- Machine boxes are accepted as the engine produced them; only changed or
  added boxes must lie inside the page.

No corrections are written here: M5 derives them on confirm by comparing the
draft with the regions, so autosaves do not flood the audit log.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import DocumentStatus, RunStatus
from app.db.models import Document, ExtractionRun, Page, Region, ReviewDraft
from app.db.types import utcnow
from app.schemas.review import DraftLine, DraftLineIn, ReviewDraftIn, ReviewDraftOut

HUMAN_PROVENANCE = "human"


class DraftError(Exception):
    """A request the draft rules refuse. `code` is stable for the API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def latest_successful_run(document: Document) -> ExtractionRun | None:
    return max(
        (r for r in document.runs if r.status == RunStatus.SUCCEEDED.value),
        key=lambda r: (r.created_at, str(r.id)),
        default=None,
    )


def _require_run(document: Document) -> ExtractionRun:
    run = latest_successful_run(document)
    if run is None:
        raise DraftError(
            "extraction_not_ready",
            f"No extraction result yet (document status: {document.status}).",
        )
    return run


def _regions(db: Session, run: ExtractionRun) -> list[Region]:
    return list(db.scalars(select(Region).where(Region.run_id == run.id).order_by(Region.sequence)))


def _machine_line(region: Region, page_number: int, **changes) -> DraftLine:
    values = {
        "line_id": region.id,
        "region_id": region.id,
        "page": page_number,
        "sequence": region.sequence,
        "text": region.text,
        "box": list(region.box),
        "human_action": "untouched",
        "confidence": region.confidence,
        "provenance": region.provenance,
        "escalated": region.escalated,
    }
    values.update(changes)
    return DraftLine(**values)


# ---- read ------------------------------------------------------------------


def get_draft(db: Session, document: Document) -> ReviewDraftOut:
    """The saved draft, or one seeded from the latest successful run
    (version 0, not stored until the first save)."""
    run = _require_run(document)
    draft = db.get(ReviewDraft, document.id)
    if draft is not None:
        # A draft based on an older run (only possible once re-extraction
        # exists, UC7) is returned as saved; saving it reports run_changed.
        return ReviewDraftOut(
            document_id=document.id,
            based_on_run_id=draft.based_on_run_id,
            version=draft.version,
            updated_at=draft.updated_at,
            lines=[DraftLine.model_validate(line) for line in draft.data["lines"]],
        )

    page_numbers = {p.id: p.page_number for p in document.pages}
    lines = [
        _machine_line(r, page_numbers[r.page_id], sequence=i)
        for i, r in enumerate(_regions(db, run))
    ]
    return ReviewDraftOut(
        document_id=document.id, based_on_run_id=run.id, version=0, updated_at=None, lines=lines
    )


# ---- validate --------------------------------------------------------------


def _check_box(box: list[int], page: Page, line_id: uuid.UUID) -> None:
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= page.width and 0 <= y1 < y2 <= page.height):
        raise DraftError(
            "invalid_draft",
            f"Line {line_id}: box {box} is not inside page {page.page_number} "
            f"({page.width}x{page.height}).",
        )


def normalize_lines(
    lines: list[DraftLineIn], regions: list[Region], pages: list[Page]
) -> list[DraftLine]:
    """Validate the reviewer's lines against the run and return them complete
    (machine fields filled in, `edited` decided, sequence renumbered)."""
    regions_by_id = {r.id: r for r in regions}
    pages_by_number = {p.page_number: p for p in pages}
    page_number_by_id = {p.id: p.page_number for p in pages}

    seen_lines: set[uuid.UUID] = set()
    seen_regions: set[uuid.UUID] = set()
    out: list[DraftLine] = []

    for line in lines:
        if line.line_id in seen_lines:
            raise DraftError("invalid_draft", f"Line {line.line_id} appears more than once.")
        seen_lines.add(line.line_id)
        page = pages_by_number.get(line.page)
        if page is None:
            raise DraftError("invalid_draft", f"Line {line.line_id}: there is no page {line.page}.")

        if line.region_id is None:  # added by the reviewer
            if line.line_id in regions_by_id:
                raise DraftError("invalid_draft", f"Line {line.line_id}: an added line needs a new id.")
            if line.human_action not in ("added", "deleted"):
                raise DraftError("invalid_draft", f"Line {line.line_id}: a line without a region must be added.")
            _check_box(line.box, page, line.line_id)
            out.append(
                DraftLine(
                    **line.model_dump(), confidence=None, provenance=HUMAN_PROVENANCE, escalated=None
                )
            )
            continue

        region = regions_by_id.get(line.region_id)
        if region is None:
            raise DraftError("invalid_draft", f"Line {line.line_id}: region {line.region_id} is not in this run.")
        if line.region_id in seen_regions:
            raise DraftError("invalid_draft", f"Region {line.region_id} appears more than once.")
        seen_regions.add(line.region_id)
        if line.line_id != line.region_id:
            raise DraftError("invalid_draft", f"Line {line.line_id}: a machine line keeps its region's id.")
        if line.page != page_number_by_id[region.page_id]:
            raise DraftError("invalid_draft", f"Line {line.line_id}: a machine line cannot change page.")
        if line.human_action == "added":
            raise DraftError("invalid_draft", f"Line {line.line_id}: a machine line cannot be 'added'.")

        box_changed = list(line.box) != list(region.box)
        if box_changed:
            _check_box(line.box, page, line.line_id)
        action = line.human_action
        if action != "deleted":
            if box_changed or line.text != region.text:
                action = "edited"
            elif action == "edited":  # changed, then changed back: reviewed as read
                action = "accepted"
        out.append(
            _machine_line(
                region,
                line.page,
                sequence=line.sequence,
                text=line.text,
                box=list(line.box),
                human_action=action,
            )
        )

    missing = len(regions_by_id) - len(seen_regions)
    if missing:
        raise DraftError(
            "invalid_draft",
            f"{missing} machine line(s) are missing. Mark false lines as deleted instead of removing them.",
        )

    # Reading order: the client's sequence, ties kept in the order sent; then 0..n-1.
    ordered = sorted(enumerate(out), key=lambda item: (item[1].sequence, item[0]))
    return [line.model_copy(update={"sequence": i}) for i, (_, line) in enumerate(ordered)]


# ---- save ------------------------------------------------------------------


def save_draft(db: Session, document: Document, payload: ReviewDraftIn) -> ReviewDraftOut:
    """Full replace with optimistic concurrency; returns the stored draft."""
    if document.status == DocumentStatus.VERIFIED.value:
        raise DraftError("document_verified", "This document is verified; reopening it comes with confirmation (M5).")
    run = _require_run(document)
    if document.status != DocumentStatus.NEEDS_REVIEW.value:
        raise DraftError("extraction_not_ready", f"The document is not ready for review (status: {document.status}).")
    if payload.based_on_run_id != run.id:
        raise DraftError("run_changed", "The document was extracted again. Reload to review the new result.")

    lines = normalize_lines(payload.lines, _regions(db, run), list(document.pages))
    data = {"lines": [line.model_dump(mode="json") for line in lines]}
    conflict = DraftError("draft_conflict", "This draft was changed elsewhere. Reload to see the latest version.")

    if db.get(ReviewDraft, document.id) is None:
        if payload.version != 0:
            raise conflict
        db.add(ReviewDraft(document_id=document.id, based_on_run_id=run.id, data=data, version=1))
        try:
            db.commit()
        except IntegrityError:  # another first save won the race
            db.rollback()
            raise conflict from None
    else:
        # Conditional update: of two saves based on the same version, one wins.
        result = db.execute(
            update(ReviewDraft)
            .where(ReviewDraft.document_id == document.id, ReviewDraft.version == payload.version)
            .values(data=data, version=payload.version + 1, based_on_run_id=run.id, updated_at=utcnow())
        )
        if result.rowcount != 1:
            db.rollback()
            raise conflict
        db.commit()

    db.expire_all()
    return get_draft(db, document)
