from app.construction.documents import Chunk
from app.construction.schema import ExtractionContext

LOW_CONFIDENCE = 0.6

SYSTEM = """You extract structured knowledge from Sri Lanka Accounting Standards (SLFRS, LKAS)
and Sri Lanka Auditing Standards (SLAuS) for an audit knowledge graph.

Rules:
- Use only what the paragraph states. Do not add knowledge from outside the text.
- A requirement is a rule an entity or auditor must or may follow.
  obligation: "shall" for shall or must, "should" for should, "may" for may or is permitted.
- Requirement type is one of: recognition, measurement, presentation, classification,
  disclosure, transition.
- applies_to uses only codes from the allowed lists. Leave it empty if none fit.
- definitions only for terms the paragraph defines.
- references are other standards or paragraphs named in the text.
- equations only when the text states a relationship between amounts, written with
  allowed line item codes.
- If the paragraph describes something important for auditing that no list covers,
  add it to proposals with a short reason.
- Background, examples and [Deleted] paragraphs: is_normative false and empty lists.

Return JSON only."""


def _codes(name: str, codes: list[str]) -> str:
    return f"{name}: {', '.join(codes) if codes else '(none)'}"


def build_user_prompt(chunk: Chunk, code: str | None, ctx: ExtractionContext) -> str:
    parts = [
        f"Standard: {code or chunk.file}",
        f"Paragraph: {chunk.number or 'unnumbered'}",
        f"Heading: {chunk.heading or '-'}",
        "",
        _codes("Allowed line items", ctx.line_items),
        _codes("Allowed account classes", ctx.account_classes),
        _codes("Allowed document types", ctx.document_types),
    ]
    if ctx.known:
        parts += ["", "Already in the graph for this standard:", *[f"- {k}" for k in ctx.known]]
    if chunk.confidence is not None and chunk.confidence < LOW_CONFIDENCE:
        parts += ["", "The text came from OCR with low confidence. Skip words you cannot read."]
    parts += ["", "Text:", '"""', chunk.text, '"""']
    return "\n".join(parts)
