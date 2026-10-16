"""Finding shapes. Verdict word replaced with finding pending auditor review."""
from typing import Literal
from pydantic import BaseModel

Category = Literal["arithmetic", "ledger", "format", "compliance", "possible_fraud"]
Severity = Literal["low", "medium", "high"]


class Finding(BaseModel):
    finding_id: str
    rule_id: str  # e.g. CHK-001, POL-07 — always cite, so trace stays
    category: Category
    severity: Severity
    message: str
    evidence_ids: list[str] = []
    policy_ids: list[str] = []
    confidence: float = 1.0


class TraceEntry(BaseModel):
    agent_name: str
    decision_type: str
    detail: str


class AuditResult(BaseModel):
    case_id: str
    version: int = 1
    status: str = "pending_auditor_review"
    findings: list[Finding] = []
    trace: list[TraceEntry] = []
    rejected_records: list[str] = []  # doc_ids DQ rejected, logged not discarded
    rejected_citations: list[str] = []  # fake evidence IDs validation threw out
