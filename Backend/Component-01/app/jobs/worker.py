"""A single in-process worker draining the database-backed queue.

The queue is simply ExtractionRun rows with status "queued". One worker
thread means model inference is serialized, which keeps latency
measurements clean and never shares a model across threads. A run is
claimed with a conditional UPDATE, so even if a second worker ever existed
it could not process the same run twice.
"""

import logging
import threading
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.enums import DocumentStatus, RunStatus
from app.db.models import Document, ExtractionRun
from app.db.types import utcnow
from app.jobs.tasks import process_run
from app.services.ocr.base import OCREngine
from app.services.storage.base import Storage

logger = logging.getLogger(__name__)

class JobWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: Storage,
        engine: OCREngine,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._engine = engine
        self._settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- queue -------------------------------------------------------

    def recover_interrupted(self) -> int:
        """Re-queue runs left "running" by a process that died mid-run.

        Safe because a run writes its pages and regions in one final
        transaction: an interrupted run left nothing half-written.
        """
        with self._session_factory() as db:
            runs = db.scalars(
                select(ExtractionRun).where(ExtractionRun.status == RunStatus.RUNNING.value)
            ).all()
            for run in runs:
                run.status = RunStatus.QUEUED.value
                run.started_at = None
                run.pages_total = None
                run.pages_done = 0
                document = db.get(Document, run.document_id)
                if document is not None and document.status == DocumentStatus.PROCESSING.value:
                    document.status = DocumentStatus.UPLOADED.value
            db.commit()
            return len(runs)

    def _claim_next(self) -> uuid.UUID | None:
        with self._session_factory() as db:
            run_id = db.scalar(
                select(ExtractionRun.id)
                .where(ExtractionRun.status == RunStatus.QUEUED.value)
                .order_by(ExtractionRun.created_at, ExtractionRun.id)
                .limit(1)
            )
            if run_id is None:
                return None
            claimed = db.execute(
                update(ExtractionRun)
                .where(ExtractionRun.id == run_id, ExtractionRun.status == RunStatus.QUEUED.value)
                .values(status=RunStatus.RUNNING.value, started_at=utcnow())
            )
            db.commit()
            return run_id if claimed.rowcount == 1 else None

    def run_once(self) -> bool:
        """Process the oldest queued run. Returns False if there was none."""
        run_id = self._claim_next()
        if run_id is None:
            return False
        process_run(
            run_id,
            session_factory=self._session_factory,
            storage=self._storage,
            engine=self._engine,
            settings=self._settings,
        )
        return True

    # ---- thread ------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("Worker loop error")
                processed = False
            if not processed:
                self._stop.wait(self._settings.worker_poll_interval_s)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="extraction-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        # A run in progress is not interrupted: the thread is a daemon, and
        # an unfinished run is re-queued by recover_interrupted() at next start.
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()