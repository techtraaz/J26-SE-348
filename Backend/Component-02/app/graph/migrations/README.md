Cypher files for indexes, applied in name order by `python -m scripts.migrate`.

Uniqueness constraints are generated from `app/ontology/schema.yaml` (one per node key),
and the vector index on `SourceChunk.embedding` uses `EMBEDDING_DIM` from settings.
