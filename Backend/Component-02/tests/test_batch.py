from app.construction.batch import corpus_totals, ingest_files, load_manifest
from app.construction.context import SeedReader
from app.construction.documents import LoadedDocument, Page
from app.construction.llm import FakeLLM
from app.construction.pipeline import KGPipeline

PAGE = "9  Inventories shall be measured at the lower of cost and net realisable value."


def _load(path):
    if "broken" in path.name:
        raise ValueError("cannot read PDF")
    return LoadedDocument(file=path.name, code="LKAS 2", source="pdf", pages=[Page(1, PAGE)])


def _files(tmp_path, *names):
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(name.encode())
        paths.append(p)
    return paths


def test_resumes_and_skips_finished_files(tmp_path):
    llm = FakeLLM()
    pipeline = KGPipeline(llm, SeedReader(), embed=False)
    paths = _files(tmp_path, "LKAS_02_a.pdf", "LKAS_02_b.pdf")
    manifest = tmp_path / "out" / "manifest.json"

    first = ingest_files(paths, pipeline, _load, manifest, "fake:m", tmp_path / "out")
    assert first["totals"] == {"done": 2, "skipped": 0, "failed": 0}
    calls = len(llm.calls)

    second = ingest_files(paths, pipeline, _load, manifest, "fake:m")
    assert second["totals"] == {"done": 0, "skipped": 2, "failed": 0}
    assert len(llm.calls) == calls
    assert (tmp_path / "out" / "LKAS_02_a.json").exists()


def test_changed_file_or_model_runs_again(tmp_path):
    pipeline = KGPipeline(FakeLLM(), SeedReader(), embed=False)
    paths = _files(tmp_path, "LKAS_02_a.pdf")
    manifest = tmp_path / "manifest.json"
    ingest_files(paths, pipeline, _load, manifest, "fake:m")
    assert ingest_files(paths, pipeline, _load, manifest, "openai:qwen")["totals"]["done"] == 1
    paths[0].write_bytes(b"new edition")
    assert ingest_files(paths, pipeline, _load, manifest, "openai:qwen")["totals"]["done"] == 1


def test_one_failure_does_not_stop_the_batch(tmp_path):
    pipeline = KGPipeline(FakeLLM(), SeedReader(), embed=False)
    paths = _files(tmp_path, "broken.pdf", "LKAS_02_a.pdf")
    manifest = tmp_path / "manifest.json"
    out = ingest_files(paths, pipeline, _load, manifest, "fake:m")
    assert out["totals"] == {"done": 1, "skipped": 0, "failed": 1}
    saved = load_manifest(manifest)
    assert saved["broken.pdf"]["status"] == "failed" and "cannot read PDF" in saved["broken.pdf"]["error"]
    # the failed file is retried on the next run
    assert ingest_files(paths, pipeline, _load, manifest, "fake:m")["totals"]["failed"] == 1


def test_corpus_totals():
    manifest = {
        "a.pdf": {"status": "done", "summary": {"chunks": 10, "requirements": 3, "definitions": 1}},
        "b.pdf": {"status": "done", "summary": {"chunks": 5, "requirements": 2}},
        "c.pdf": {"status": "failed"},
    }
    totals = corpus_totals(manifest)
    assert totals["files_done"] == 2 and totals["files_failed"] == 1
    assert totals["chunks"] == 15 and totals["requirements"] == 5 and totals["definitions"] == 1
