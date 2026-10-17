// lookups used by the query API and ingestion
CREATE INDEX standard_family IF NOT EXISTS FOR (n:Standard) ON (n.family);
CREATE INDEX standard_status IF NOT EXISTS FOR (n:Standard) ON (n.status);
CREATE INDEX requirement_type IF NOT EXISTS FOR (n:Requirement) ON (n.type);
CREATE INDEX equation_kind IF NOT EXISTS FOR (n:Equation) ON (n.kind);
CREATE INDEX check_rule_severity IF NOT EXISTS FOR (n:CheckRule) ON (n.severity);
CREATE INDEX source_document_doc_type IF NOT EXISTS FOR (n:SourceDocument) ON (n.doc_type);
CREATE INDEX source_document_period IF NOT EXISTS FOR (n:SourceDocument) ON (n.period_year);
CREATE INDEX ledger_entry_seq IF NOT EXISTS FOR (n:LedgerEntry) ON (n.seq);
CREATE INDEX source_chunk_file IF NOT EXISTS FOR (n:SourceChunk) ON (n.file);
