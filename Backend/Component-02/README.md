# Component 02 - Audit Knowledge Graph & Evidence Ledger

Sri Lankan accounting/auditing knowledge graph (SLFRS / LKAS / SLAuS / Companies Act),
built and evolved by an LLM agent, plus an evidence ledger over Garage object storage.

## Responsibilities

1. **Ontology**: Sri Lankan audit-specific schema (`app/ontology`).
2. **KG construction & evolution**: LangGraph agent ingests compliance documents and
   merges them into the existing graph (`app/construction`).
3. **KG query API**: fixed, parameterised Cypher doors used by Component 03 (`app/query`).
4. **Evidence ledger**: uploaded documents stored in Garage, recorded as hash-chained
   ledger entries so agents can cite them (`app/ledger`).

## Layout

```
app/
  api/            FastAPI routers
  config.py       settings from .env
  graph/          Neo4j driver + Cypher migrations
  ontology/       ontology definition + seed data
  construction/   LangGraph KG construction / update agent
  query/          fixed Cypher queries for audit agents
  ledger/         Garage storage + ledger entries
  schemas/        pydantic models
data/standards/   local standards corpus (git-ignored)
docs/             design notes
scripts/          one-off utilities
tests/
```

## Run

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
copy .env.example .env      # fill in AuraDB credentials
python -m scripts.check_neo4j
python -m scripts.migrate   # constraints + indexes, safe to re-run
python -m scripts.seed      # load seed data (--check to validate only)
python -m scripts.ingest_all  # ingest all standards PDFs, resumable
uvicorn app.main:app --reload --port 8002
pytest
```

## Doors (FastAPI)

- `GET /health`: alive check + Neo4j connectivity
- `GET /ontology`: full ontology schema (layers, node and relationship types)
- `GET /ontology/nodes/{label}`: one node type with its relationships
- `GET /ontology/diagram?layer=`: Mermaid diagram
- `GET /ontology/stats`: live node and relationship counts

- `POST /kg/ingest/pdf`: upload a standard PDF, returns a job
- `POST /kg/ingest/ocr`: Component 01 OCR output for scanned documents
- `GET /kg/jobs/{id}`: job status and summary
- `GET /kg/pipeline`: KG construction pipeline diagram

- `GET /query/rules/{doc_type}`, `/query/check-rules/{doc_type}`: rules for Component 03
- `GET /query/evidence-chain/{doc_id}`, `/query/postings/{case_id}`, `/query/period-totals/{case_id}?year=`
- `GET /query/fields`: document field name -> line item code
- `GET /query/rules/{rule_id}/explain`: rule -> equation -> paragraph -> standard, with a sentence
- `GET /query/standards/{code}`, `/query/sections/{id}`, `/query/line-items/{code}`,
  `/query/equations?statement=&kind=`, `/query/definitions/{term}`

See [docs/ontology.md](docs/ontology.md) for the ontology and
[docs/kg_construction.md](docs/kg_construction.md) for KG construction.
