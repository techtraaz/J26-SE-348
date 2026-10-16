import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.construction.documents import LoadedDocument
from app.construction.pipeline import IngestResult, KGPipeline

log = logging.getLogger("kg.batch")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def is_done(entry: dict | None, sha: str, model: str) -> bool:
    return bool(entry) and entry.get("status") == "done" and entry.get("sha256") == sha \
        and entry.get("model") == model


def ingest_files(paths: list[Path], pipeline: KGPipeline, load: Callable[[Path], LoadedDocument],
                 manifest_path: Path, model: str, out_dir: Path | None = None,
                 force: bool = False) -> dict:
    """Ingest files one by one. Finished files (same hash and model) are skipped, so a run
    that stopped half way continues where it left off. One failure does not stop the batch."""
    manifest = load_manifest(manifest_path)
    totals = {"done": 0, "skipped": 0, "failed": 0}
    for i, path in enumerate(paths, start=1):
        sha = file_hash(path)
        if not force and is_done(manifest.get(path.name), sha, model):
            totals["skipped"] += 1
            log.info("[%d/%d] skip %s (already done)", i, len(paths), path.name)
            continue
        started = datetime.now(UTC)
        log.info("[%d/%d] start %s", i, len(paths), path.name)
        try:
            result: IngestResult = pipeline.run(load(path))
        except Exception as exc:  # keep going with the next file, the error is recorded
            manifest[path.name] = {"status": "failed", "sha256": sha, "model": model,
                                   "error": f"{type(exc).__name__}: {exc}",
                                   "finished_at": datetime.now(UTC).isoformat()}
            totals["failed"] += 1
            log.exception("[%d/%d] failed %s", i, len(paths), path.name)
        else:
            summary = result.summary()
            status = "failed" if result.plan_errors else "done"
            manifest[path.name] = {"status": status, "sha256": sha, "model": model,
                                   "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
                                   "finished_at": datetime.now(UTC).isoformat(), "summary": summary}
            totals["done" if status == "done" else "failed"] += 1
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{path.stem}.json").write_text(
                    json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
            log.info("[%d/%d] %s %s: reqs %s defs %s eqs %s llm errors %s", i, len(paths),
                     status, path.name, summary["requirements"], summary["definitions"],
                     summary["equations"], summary["llm_errors"])
        save_manifest(manifest_path, manifest)
    return {"totals": totals, "manifest": manifest}


def corpus_totals(manifest: dict) -> dict:
    keys = ("chunks", "sent_to_llm", "requirements", "definitions", "equations", "llm_errors",
            "proposals", "written")
    done = [e["summary"] for e in manifest.values() if e.get("status") == "done"]
    return {"files_done": len(done),
            "files_failed": sum(1 for e in manifest.values() if e.get("status") == "failed"),
            **{k: sum(s.get(k, 0) for s in done) for k in keys}}
