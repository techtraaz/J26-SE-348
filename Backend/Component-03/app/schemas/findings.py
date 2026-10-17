"""Finding shapes. Verdict word replaced with finding pending auditor review."""
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["arithmetic", "ledger", "format", "compliance", "possible_fraud"]
Severity = Literal["low", "medium", "high"]
# Auditor review state for one finding. Agreed with the frontend type.
ReviewStatus = Literal["pending_review", "confirmed", "dismissed", "needs_more_evidence"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EvidenceClaim(BaseModel):
    """One checkable claim: doc's field really holds this value.
    Validation verifies it in code (numbers within tolerance)."""
    evidence_id: str
    field: str
    claimed_value: float | str


class Finding(BaseModel):
    finding_id: str
    rule_id: str  # e.g. CHK-001, POL-07 — always cite, so trace stays
    category: Category
    severity: Severity
    message: str
    evidence_ids: list[str] = []
    policy_ids: list[str] = []
    confidence: float = 1.0
    # Set by Reasoning from confidence: low confidence -> "needs_more_evidence".
    review_status: ReviewStatus = "pending_review"
    # Structured claims Validation actually checks (existence + value match).
    claims: list[EvidenceClaim] = Field(default_factory=list)
    # Contract fields for Component-04 (Thennakoon). Filled by Reasoning, not empty.
    reasoning_chain: list[str] = Field(default_factory=list)
    evidence_validation: str = "unverified"
    citation_unverified: bool = False
    supersedes: int | None = None  # previous version number this finding replaces
    created_at: str = Field(default_factory=_now)


class TraceEntry(BaseModel):
    agent_name: str
    decision_type: str
    detail: str
    seq: int = 0  # completion-order stamp, set inside node at run time (not start order)


class RejectedFinding(BaseModel):
    finding: Finding
    reason: str


class AuditResult(BaseModel):
    case_id: str
    version: int = 1
    # Where the knowledge-graph data came from: live, mock, or mock_fallback.
    # A mock result must never look live.
    kg_source: str = "mock"
    # Wall-clock time for the whole case, measured with perf_counter.
    latency_ms: float = 0.0
    # pending_auditor_review = checked, needs human. not_auditable = nothing
    # could be checked (empty or all-rejected case); findings carry the DQ reasons.
    status: str = "pending_auditor_review"
    findings: list[Finding] = []
    trace: list[TraceEntry] = []
    rejected_records: list[str] = []  # doc_ids DQ rejected, logged not discarded
    rejected_citations: list[str] = []  # ONLY the failing IDs, not every ID on the finding
    rejected_findings: list[RejectedFinding] = []  # dropped findings + reason each
