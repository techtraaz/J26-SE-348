from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

# same values as the comments on Requirement in app/ontology/schema.yaml
RequirementType = Literal[
    "recognition", "measurement", "presentation", "classification", "disclosure", "transition"]
Obligation = Literal["shall", "should", "may"]


class ExtractedRequirement(BaseModel):
    text: str = Field(description="The rule in one sentence, close to the paragraph wording")
    type: RequirementType
    obligation: Obligation
    applies_to: list[str] = Field(
        default_factory=list,
        description="Codes from the allowed line items, account classes or document types")


class ExtractedDefinition(BaseModel):
    term: str
    text: str = Field(description="The definition as stated in the paragraph")


class ExtractedReference(BaseModel):
    target: str = Field(description="Standard or paragraph named in the text, e.g. 'LKAS 37' or 'LKAS 1.25'")


class ExtractedEquation(BaseModel):
    name: str
    expression: str = Field(
        description="Python style using allowed line item codes, e.g. 'inventories == min(inventory_cost, inventory_nrv)'")


class ProposedConcept(BaseModel):
    label: str = Field(description="Kind of node that seems to be missing from the ontology")
    name: str
    reason: str


class ChunkExtraction(BaseModel):
    is_normative: bool = Field(
        default=False, description="True if the paragraph states a requirement or definition")
    requirements: list[ExtractedRequirement] = Field(default_factory=list)
    definitions: list[ExtractedDefinition] = Field(default_factory=list)
    references: list[ExtractedReference] = Field(default_factory=list)
    equations: list[ExtractedEquation] = Field(default_factory=list)
    proposals: list[ProposedConcept] = Field(default_factory=list)


@dataclass
class ExtractionContext:
    """Ontology codes the model may use, plus what the graph already knows."""
    line_items: list[str] = field(default_factory=list)
    account_classes: list[str] = field(default_factory=list)
    document_types: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
