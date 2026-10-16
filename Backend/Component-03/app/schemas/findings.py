"""Finding shapes. Verdict word replaced with finding pending auditor review."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["arithmetic", "ledger", "format", "compliance", "possible_fraud"]
Severity = Literal["low", "medium", "high"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Finding(BaseModel):
    finding_id: str
    rule_id: str  # e.g. CHK-001, POL-07 — always cite, so trace stays
    category: Category
    severity: Severity
    message: str
    evidence_ids: list[str] = []
    policy_ids: list[str] = []
    confidence: float = 1.0
    # Contract fields promised to Component-04 (Thennakoon). Optional so old data still loads.
    reasoning_chain: list[str] = Field(default_factory=list)
    evidence_validation: str = "unverified"
    citation_unverified: bool = False
    supersedes: int | None = None  # previous version number this finding replaces
    created_at: str = Field(default_factory=_now)


class TraceEntry(BaseModel):
    agent_name: str
    decision_type: str
    detail: str
    seq: int = 0  # execution order number, set inside node at run time (no sorting)


class RejectedFinding(BaseModel):
    finding: Finding
    reason: str


class AuditResult(BaseModel):
    case_id: str
    version: int = 1
    status: str = "pending_auditor_review"
    findings: list[Finding] = []
    trace: list[TraceEntry] = []
    rejected_records: list[str] = []  # doc_ids DQ rejected, logged not discarded
    rejected_citations: list[str] = []  # ONLY the failing IDs, not every ID on the finding
    rejected_findings: list[RejectedFinding] = []  # dropped findings + reason each
