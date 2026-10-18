"""Database model tests.

Run on in-memory SQLite by default. To run the same tests against a real
PostgreSQL database (JSONB, real constraint behaviour), set
NOMOS_TEST_DATABASE_URL to an EMPTY throwaway database; its tables are
created and dropped around every test.
"""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.enums import DocumentSource, DocumentStatus
from app.db.models import (
    Correction,
    Document,
    ExtractionRun,
    Page,
    Region,
    VerifiedRecord,
)
from app.db.session import create_db_engine, create_session_factory, session_scope


@pytest.fixture
def session():
    engine = create_db_engine(os.environ.get("NOMOS_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = create_session_factory(engine)()
    yield db
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _document(db: Session) -> Document:
    doc = Document(filename="inv.png", mime="image/png", sha256="a" * 64, original_key="k/original.png")
    doc.pages.append(
        Page(page_number=1, width=754, height=1000, original_image_key="k/pages/1.original.png")
    )
    db.add(doc)
    db.flush()
    return doc


def _run_with_region(db: Session, doc: Document) -> tuple[ExtractionRun, Region]:
    run = ExtractionRun(document_id=doc.id, engine_info={"name": "paddleocr", "version": "3.7.0"})
    db.add(run)
    db.flush()
    region = Region(
        run_id=run.id,
        page_id=doc.pages[0].id,
        sequence=0,
        text="TOTAL 42.00",
        confidence=0.999794065952301,
        box=[10, 20, 110, 40],
        polygon=[[10, 20], [110, 20], [110, 40], [10, 40]],
        provenance="paddleocr",
    )
    db.add(region)
    db.flush()
    return run, region


def test_defaults_are_applied(session):
    doc = _document(session)

    assert doc.status == DocumentStatus.UPLOADED.value
    assert doc.source == DocumentSource.DEMO.value
    assert doc.created_at is not None and doc.created_by is None


def test_machine_output_round_trips_exactly(session):
    doc = _document(session)
    _, region = _run_with_region(session, doc)
    session.commit()
    session.expire_all()

    saved = session.get(Region, region.id)
    assert saved.confidence == 0.999794065952301  # raw score untouched
    assert saved.box == [10, 20, 110, 40]
    assert saved.polygon[2] == [110, 40]
    assert saved.escalated is None and saved.field_key is None  # reserved, empty


def test_regions_and_pages_come_back_in_order(session):
    doc = _document(session)
    doc.pages.append(Page(page_number=2, width=1, height=1, original_image_key="k2"))
    run, _ = _run_with_region(session, doc)
    for seq in (2, 1):
        session.add(Region(run_id=run.id, page_id=doc.pages[0].id, sequence=seq, text=str(seq),
                           box=[0, 0, 1, 1], provenance="paddleocr"))
    session.commit()
    session.expire_all()

    assert [p.page_number for p in session.get(Document, doc.id).pages] == [1, 2]
    assert [r.sequence for r in session.get(ExtractionRun, run.id).regions] == [0, 1, 2]


def test_confidence_may_be_missing(session):
    doc = _document(session)
    run, _ = _run_with_region(session, doc)
    session.add(Region(run_id=run.id, page_id=doc.pages[0].id, sequence=9, text="vlm text",
                       confidence=None, box=[0, 0, 1, 1], provenance="vlm"))
    session.commit()

    assert session.scalars(select(Region).where(Region.provenance == "vlm")).one().confidence is None


def test_deleting_a_document_cascades_to_pages_runs_and_regions(session):
    doc = _document(session)
    _run_with_region(session, doc)
    session.commit()

    session.delete(doc)
    session.commit()

    for model in (Page, ExtractionRun, Region):
        assert session.scalars(select(model)).first() is None


def test_page_number_is_unique_per_document(session):
    doc = _document(session)
    session.add(Page(document_id=doc.id, page_number=1, width=1, height=1, original_image_key="x"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_verified_version_is_unique_per_document(session):
    doc = _document(session)
    run, _ = _run_with_region(session, doc)
    session.add(VerifiedRecord(document_id=doc.id, version=1, based_on_run_id=run.id, data={}))
    session.flush()
    session.add(VerifiedRecord(document_id=doc.id, version=1, based_on_run_id=run.id, data={}))

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_document_with_verified_data_cannot_be_deleted_by_accident(session):
    doc = _document(session)
    run, _ = _run_with_region(session, doc)
    session.add(VerifiedRecord(document_id=doc.id, version=1, based_on_run_id=run.id, data={"lines": []}))
    session.commit()

    session.delete(doc)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_region_keeps_its_correction_with_a_null_link(session):
    doc = _document(session)
    _, region = _run_with_region(session, doc)
    correction = Correction(
        document_id=doc.id,
        region_id=region.id,
        action="edit_text",
        before={"text": "Indianapofis"},
        after={"text": "Indianapolis"},
    )
    session.add(correction)
    session.commit()

    session.delete(region)
    session.commit()
    session.refresh(correction)

    assert correction.region_id is None and correction.after == {"text": "Indianapolis"}


def test_session_scope_rolls_back_on_error():
    factory = create_session_factory(create_db_engine("sqlite://"))
    Base.metadata.create_all(factory.kw["bind"])

    with pytest.raises(RuntimeError):
        gen = session_scope(factory)
        db = next(gen)
        db.add(Document(filename="x", mime="image/png", sha256="b" * 64, original_key="k"))
        db.flush()
        gen.throw(RuntimeError("boom"))

    with factory() as check:
        assert check.scalars(select(Document)).first() is None