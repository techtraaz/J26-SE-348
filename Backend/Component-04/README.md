# Component 04 — XAI Trace Collector & Deterministic Reporting Engine

Passive observer that captures, verifies, and stores execution traces
from the Component 03 multi-agent audit system via Redis Pub/Sub.

## Prerequisites

- Python 3.12+
- Redis server running on `localhost:6379` (default)

## Run

```powershell
uv sync
uv run uvicorn app.main:app --reload --port 8004
```

## Endpoints

- `GET  /health`            — alive check
- `GET  /runs`              — list recent audit runs
- `GET  /traces/{case_id}`  — full trace history for a case

## Architecture

Component 04 **never** sits in the critical HTTP path of Component 03.
It subscribes to the `nomos:trace_events` Redis channel as an independent
observer and persists enriched traces into a local SQLite database.
