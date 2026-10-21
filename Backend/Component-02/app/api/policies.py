import hashlib
import re
import tempfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.api import kg
from app.config import get_settings
from app.construction.documents import LoadedDocument
from app.construction.loaders import load_pdf
from app.storage.objects import NotFound, ObjectStore, StorageError, StorageNotConfigured, get_store

router = APIRouter(prefix="/policies", tags=["policies"])

# what is kept of a run next to the PDF, so the last KG update survives a restart
RUN_FIELDS = ("job_id", "file", "code", "status", "kind", "stage", "stages_done", "error",
              "summary", "changes", "totals", "queued_at", "started_at", "finished_at")
_BAD_CHARS = re.compile(r"[\x00-\x1f/\\]")


def _store() -> ObjectStore:
    try:
        return get_store()
    except StorageNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc


def _prefix() -> str:
    return get_settings().policies_prefix.strip("/")


def _key(name: str) -> str:
    return f"{_prefix()}/{name}"


def _run_key(name: str) -> str:
    return f"{_prefix()}/_runs/{name}.json"


def _safe_name(filename: str | None) -> str:
    name = _BAD_CHARS.sub("_", Path(filename or "").name).strip()
    if not name.lower().endswith(".pdf") or name.startswith(".") or len(name) > 200:
        raise HTTPException(400, "Upload a .pdf file")
    return name


def _check_name(name: str) -> str:
    if _BAD_CHARS.search(name) or not name.lower().endswith(".pdf"):
        raise HTTPException(404, f"Unknown policy '{name}'")
    return name


def _load(name: str, data: bytes, code: str | None) -> LoadedDocument:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        try:
            return load_pdf(path, code or None)
        except Exception as exc:
            raise HTTPException(422, f"Could not read PDF: {exc}") from exc


def _active_job(name: str) -> dict | None:
    jobs = [j for j in kg.JOBS.values() if j.get("policy") == name]
    return max(jobs, key=lambda j: j["queued_at"]) if jobs else None


def _busy(name: str) -> bool:
    job = _active_job(name)
    return bool(job) and job["status"] in ("queued", "running")


def _last_run(store: ObjectStore, name: str) -> dict | None:
    job = _active_job(name)
    if job:
        return {k: job.get(k) for k in (*RUN_FIELDS, "progress")}
    try:
        return store.get_json(_run_key(name))
    except StorageError:
        return None


def _brief(run: dict | None) -> dict | None:
    if not run:
        return None
    s = run.get("summary") or {}
    totals = run.get("totals") or {}
    before, after = totals.get("before"), totals.get("after")
    added = ({k: after[k] - before[k] for k in ("nodes", "relationships")}
             if before and after else None)
    return {"job_id": run.get("job_id"), "status": run.get("status"), "stage": run.get("stage"),
            "progress": run.get("progress"), "kind": run.get("kind"), "code": run.get("code"),
            "error": run.get("error"), "finished_at": run.get("finished_at"), "added": added,
            "requirements": s.get("requirements"), "definitions": s.get("definitions"),
            "equations": s.get("equations"), "llm_unavailable": s.get("llm_unavailable")}


def _start(background: BackgroundTasks, store: ObjectStore, name: str,
           doc: LoadedDocument) -> dict:
    def save(job: dict) -> None:
        store.put_json(_run_key(name), {k: job.get(k) for k in RUN_FIELDS})
    return kg._queue(background, doc, True, None, on_done=save, policy=name)


@router.get("")
def list_policies() -> dict:
    store = _store()
    prefix = _prefix() + "/"
    try:
        objects = store.list(prefix)
    except StorageError as exc:
        raise HTTPException(502, str(exc)) from exc
    policies = []
    for obj in objects:
        name = obj.key[len(prefix):]
        if not name or "/" in name:
            continue
        policies.append({"name": name, "size_bytes": obj.size, "uploaded_at": obj.last_modified,
                         "last_run": _brief(_last_run(store, name))})
    policies.sort(key=lambda p: p["uploaded_at"], reverse=True)
    return {"bucket": store.bucket, "prefix": prefix, "policies": policies}


@router.post("", status_code=202)
async def upload_policy(background: BackgroundTasks, file: Annotated[UploadFile, File()],
                        code: Annotated[str | None, Form()] = None) -> dict:
    """Store the PDF in object storage, then add it to the knowledge graph as a background job.
    code, e.g. "LKAS 18", is only needed when neither the file name nor the title page has it."""
    name = _safe_name(file.filename)
    if _busy(name):
        raise HTTPException(409, f"'{name}' is already being added to the knowledge graph")
    data = await file.read()
    limit = get_settings().policy_max_mb
    if len(data) > limit * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than {limit} MB")
    doc = _load(name, data, code)
    store = _store()
    sha = hashlib.sha256(data).hexdigest()
    try:
        store.put(_key(name), data, "application/pdf",
                  {"sha256": sha, **({"code": code} if code else {})})
    except StorageError as exc:
        raise HTTPException(502, str(exc)) from exc
    job = _start(background, store, name, doc)
    return {"policy": {"name": name, "key": _key(name), "size_bytes": len(data), "sha256": sha},
            "job": job}


@router.post("/{name}/ingest", status_code=202)
def reingest_policy(name: str, background: BackgroundTasks, code: str | None = None) -> dict:
    """Run the KG update again from the stored copy, e.g. after the LLM was offline."""
    name = _check_name(name)
    if _busy(name):
        raise HTTPException(409, f"'{name}' is already being added to the knowledge graph")
    store = _store()
    try:
        data, _ = store.get(_key(name))
        meta = store.head(_key(name)).get("metadata", {})
    except NotFound as exc:
        raise HTTPException(404, f"Unknown policy '{name}'") from exc
    except StorageError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _start(background, store, name, _load(name, data, code or meta.get("code")))


@router.get("/{name}/run")
def get_policy_run(name: str) -> dict:
    run = _last_run(_store(), _check_name(name))
    if not run:
        raise HTTPException(404, f"'{name}' has not been added to the knowledge graph yet")
    return run


@router.get("/{name}/file")
def get_policy_file(name: str, download: bool = False) -> Response:
    name = _check_name(name)
    try:
        data, content_type = _store().get(_key(name))
    except NotFound as exc:
        raise HTTPException(404, f"Unknown policy '{name}'") from exc
    except StorageError as exc:
        raise HTTPException(502, str(exc)) from exc
    disposition = "attachment" if download else "inline"
    return Response(data, media_type=content_type, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"})
