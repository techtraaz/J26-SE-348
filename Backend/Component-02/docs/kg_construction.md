# Knowledge Graph Construction

An LLM agent built with LangGraph reads compliance documents and grows the knowledge graph
against the [ontology](ontology.md). The same pipeline handles the initial standards corpus
and any new document uploaded later, so the graph evolves without being rebuilt.

Code: [`app/construction/`](../app/construction/).

## Pipeline

| Step | What it does |
|---|---|
| `chunk` | Splits the document into numbered paragraphs (`54`, `81A`, `4.1.1`, `QC11`, `B5.4.2`), keeping heading and page. Contents pages, `[Deleted]` paragraphs, "not yet effective" placeholders, footnotes and the unnumbered intro of a standard are dropped. Numbered examples stay inside their paragraph. |
| `classify` | Standard, amendment or act go on; client documents (invoices, bank statements) stop here and belong to the evidence ledger. |
| `retrieve_context` | Reads the allowed ontology codes and a snapshot of what the graph already holds for the standard. |
| `extract` | One LLM call per paragraph (`LLM_WORKERS` in parallel), returning JSON in a fixed schema: requirements, definitions, references, equations and proposals. The prompt spells out the JSON shape and lists what the graph already knows for that paragraph. |
| `validate` | Checks the output against the ontology: unknown codes removed, shall/may wording checked, duplicates dropped, equations with unknown line items turned into proposals. |
| `resolve` | Matches against the graph so nothing is duplicated: requirements by wording within the paragraph, definitions by term, equations by expression. |
| `write` | Validates the full write plan against the ontology, adds embeddings, and writes with `MERGE` so a document can be ingested again safely. |

## Provenance

- Every paragraph is a `Section` with its verbatim text; every chunk is a `SourceChunk` with
  file, page and embedding.
- Every extracted requirement, definition and equation has `EXTRACTED_FROM` to the exact
  chunk, plus `source` (file) and `confidence`.
- Confidence: PDF text 1.0, LLM extractions 0.8, both multiplied by OCR confidence for
  scanned documents from Component 01.

## Evolving the ontology

- New requirements and definitions attach to existing standards and paragraphs.
- The standard code comes from the `code` parameter, else the file name (`LKAS_18_Revenue.pdf`),
  else the title page ("Sri Lanka Accounting Standard – LKAS 18"). A code the graph does not
  know yet gets a new `Standard` with `status: unreviewed`.
- Equations that use line items the ontology does not have become **proposals**
  (`label`, `name`, `reason`), collected per document for review before the schema changes.
- References in the text (`LKAS 1.25`, `paragraph 81A of LKAS 1`) become `REFERS_TO` links.

## Running it

```powershell
python -m scripts.check_llm                      # test the LLM connection on LKAS 2:9
python -m scripts.extract_preview LKAS_02_Inventories.pdf --max-chunks 5   # dry run, saves JSON
python -m scripts.ingest_all                     # all PDFs, resumable
python -m scripts.ingest_all --dry-run --max-chunks 3
python -m scripts.ingest_all --workers 4         # parallel LLM calls
python -m scripts.ingest_all --no-embed          # GPU time on extraction only; embed afterwards
python -m scripts.prune_chunks                   # list sections the chunker no longer makes
python -m scripts.prune_chunks --apply           # and delete them
python -m scripts.embed_chunks                   # embed chunks without an embedding
python -m scripts.embed_chunks --recreate-index  # after changing EMBEDDING_MODEL / EMBEDDING_DIM
```

LLM settings (`.env`):

| Setting | Meaning |
|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Any OpenAI-compatible server. A token proxy that accepts `Authorization: Bearer` takes the token as `LLM_API_KEY`. |
| `LLM_REASONING_EFFORT` | `none` turns off thinking on reasoning models such as Qwen 3.5 (about 15x faster on extraction). |
| `LLM_WORKERS` | Paragraphs sent at once. Match the server's parallel slots. |
| `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | Embedding server, usually a local Ollama, so search works while the GPU is off. |

`ingest_all` keeps `data/standards/processed/manifest.json` with the file hash and model of
every finished file. A stopped run continues where it left off; a changed PDF or a different
model runs again. A failing file is logged and the batch continues. Totals go to
`summary.json`, the log to `ingest.log`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /kg/ingest/pdf` | Upload a text PDF. Returns a job (`202`). `?write=false` for a dry run, `?code=LKAS 18` when the file name and title page do not give the code. |
| `POST /kg/ingest/ocr` | Component 01 OCR output (`ExtractionResult`) for scanned documents, optional `code`. |
| `GET /kg/jobs/{id}` | Job status and summary: counts created and matched, issues, proposals. |
| `GET /kg/jobs` | All jobs, newest first. |
| `GET /kg/pipeline` | The pipeline as a Mermaid diagram. |

A running job also has `stage` (what runs now), `stages_done` and `progress` (`{done, total}`
paragraphs sent to the LLM). A finished job has `totals` (graph nodes and relationships before
and after) and `changes`: the new nodes per type and the touched part of the graph for drawing.

If the LLM server cannot be reached, the remaining paragraphs are not sent. Standard, Sections
and SourceChunks are still written and `summary.llm_unavailable` says why; run it again once
the server is up.

## Policies (frontend upload)

The Policies page uploads PDFs here. They are stored in Garage (`GARAGE_*` in `.env`) under
`c02-policies/` in the shared bucket, and the last run of each file is saved next to it as
`c02-policies/_runs/<file>.json`, so it is still shown after a restart.

| Endpoint | Purpose |
|---|---|
| `GET /policies` | Stored policies with the status of their last KG update. |
| `POST /policies` | Multipart `file` (+ optional `code`): store, then update the KG as a job (`202`). |
| `POST /policies/{name}/ingest` | Run the KG update again from the stored copy. |
| `GET /policies/{name}/run` | The running or last job, with its `changes`. |
| `GET /policies/{name}/file` | The PDF (`?download=true` to save it). |

## Pipeline diagram

Generated from the LangGraph definition by `python -m scripts.export_ontology`.

<!-- generated:start -->
```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	chunk(chunk)
	classify(classify)
	retrieve_context(retrieve_context)
	extract(extract)
	validate(validate)
	resolve(resolve)
	write(write)
	__end__([<p>__end__</p>]):::last
	__start__ --> chunk;
	chunk --> classify;
	classify -. &nbsp;skip&nbsp; .-> __end__;
	classify -. &nbsp;kg&nbsp; .-> retrieve_context;
	extract --> validate;
	resolve --> write;
	retrieve_context --> extract;
	validate --> resolve;
	write --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
<!-- generated:end -->
