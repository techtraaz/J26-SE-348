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
# What happened when a rule met a document, in the words of the live XAI steps:
# passed, failed (a finding), review (a finding asking the auditor to confirm),
# skipped (inputs missing) or error (could not be evaluated; a REV-006 item).
RuleOutcome = Literal["passed", "failed", "review", "skipped", "error"]


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


class RuleApplication(BaseModel):
    """One KG rule applied to one document, whatever the outcome. It carries the
    same facts as the live XAI rule_check / policy_check step (which is sent from
    it), so Component-04's report reads like its timeline."""
    kind: Literal["rule_check", "policy_check"] = "rule_check"
    rule_id: str
    rule_name: str = ""  # C2's rule name; a policy rule's text
    doc_id: str
    doc_type: str = ""
    agent: str  # compliance | anomaly
    outcome: RuleOutcome
    expression: str = ""  # the rule as C2 gives it
    values: dict[str, float | str] = Field(default_factory=dict)  # inputs used, by name
    sides: dict | None = None  # both sides of a comparison: left, op, right, left_value, right_value
    compared_with: dict[str, str] = Field(default_factory=dict)  # prior / child / parent -> doc_id
    severity: str | None = None
    below_materiality: bool = False
    reason: str | None = None  # why skipped, the error, or the finding's message
    limit: float | None = None  # policy rules
    approvals_required: int | None = None
    approvals_signed: float | None = None
    detail: str = ""  # the calculation in words, e.g. "assets 100.00 vs liabilities + capital 50.00"
    finding_id: str | None = None  # the finding it produced, if any


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
    rules_applied: list[RuleApplication] = Field(default_factory=list)  # every rule run, passed ones too
    # True when every XAI step of the run was accepted into the trace queue for C4
    # (tracing on, none dropped). Writes finish after the result is saved, so it
    # means queued, not confirmed written. When False, the trace says why.
    events_published: bool = False
    created_at: str = Field(default_factory=now_iso)
