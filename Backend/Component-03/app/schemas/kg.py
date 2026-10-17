"""Pydantic shapes for every knowledge-graph reply.

Live client validates each reply against these. Anything that does not fit is a
protocol error, never silently accepted. Kept here (not imported from another
component) so shapes can be shared by copying, per project rules.
"""
from pydantic import BaseModel, Field

from app.schemas.findings import Category, Severity


class RuleResponse(BaseModel):
    """A policy rule with a numeric limit (get_rules)."""

    rule_id: str
    text: str
    limit: float


class CheckRuleResponse(BaseModel):
    """A data-driven check rule (get_check_rules)."""

    rule_id: str
    name: str = ""
    expression: str
    inputs: list[str] = Field(default_factory=list)
    tolerance: float = 0.01
    severity: Severity = "medium"
    category: Category = "format"


class PostingResponse(BaseModel):
    """One ledger posting (get_postings)."""

    posting_id: str
    doc_id: str
    account: str
    account_type: str
    debit: float = 0.0
    credit: float = 0.0


class PeriodTotalsResponse(BaseModel):
    """Period totals for the equation check (get_period_totals)."""

    year: int
    assets: float = 0.0
    liabilities: float = 0.0
    capital: float = 0.0


class EvidenceChainResponse(BaseModel):
    """Policy -> control -> transaction -> evidence chain (get_evidence_chain)."""

    doc_id: str
    chain: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    control_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
