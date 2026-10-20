"""Finding and result shapes. A finding is pending auditor review, never a verdict."""
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["arithmetic", "ledger", "format", "compliance", "possible_fraud"]
Severity = Literal["low", "medium", "high"]
ReviewStatus = Literal["pending_review", "confirmed", "dismissed", "needs_more_evidence"]
# passed: every claim matched the document. existence_only: no value claims, cited
# documents exist. failed: a cited ID or value is wrong. unverified: nothing to check.
EvidenceValidation = Literal["unverified", "passed", "existence_only", "failed"]
Status = Literal["pending_auditor_review", "not_auditable"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EvidenceClaim(BaseModel):
    """One checkable claim: this document's field holds this value."""
    evidence_id: str
    field: str
    claimed_value: float | str


class Finding(BaseModel):
    finding_id: str
    rule_id: str  # KG rule (CHK-*, POL-*) or C3 review item (REV-*)
    category: Category
    severity: Severity
    message: str
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    review_status: ReviewStatus = "pending_review"
    claims: list[EvidenceClaim] = Field(default_factory=list)
    reasoning_chain: list[str] = Field(default_factory=list)
    evidence_validation: EvidenceValidation = "unverified"
    citation_unverified: bool = False
    supersedes: int | None = None  # version whose same finding_id this one replaces
    created_at: str = Field(default_factory=now_iso)


class TraceEntry(BaseModel):
    agent_name: str
    decision_type: str
    detail: str
    seq: int = 0  # completion order inside the graph; 0 for run-level notes


class RejectedFinding(BaseModel):
    finding: Finding
    reason: str


class AuditResult(BaseModel):
    case_id: str
    version: int = 1
    kg_source: str = "mock"  # live, mock or mock_fallback; a mock never looks live
    latency_ms: float = 0.0
    # not_auditable = nothing could be checked; findings then carry the DQ reasons.
    status: Status = "pending_auditor_review"
    findings: list[Finding] = Field(default_factory=list)
    trace: list[TraceEntry] = Field(default_factory=list)
    rejected_records: list[str] = Field(default_factory=list)  # doc_ids DQ rejected
    rejected_citations: list[str] = Field(default_factory=list)  # only the failing IDs
    rejected_findings: list[RejectedFinding] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
