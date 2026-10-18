"""Intent registry. Each Copilot intent is declared once, next to its handler:

    @intent("list_findings", group="case_query", description=..., examples=(...),
            patterns={r"\\bfindings?\\b": 1.0}, signals={"severities": 1.0}, needs=("saved_case",))
    def list_findings(turn): ...

From these declarations the NLU builds the LLM prompt (descriptions, examples),
the rules fallback (patterns + entity signals), slot checks (needs) and the help
text. Adding an intent = adding one decorated handler; nothing else changes.
"""
from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.copilot import Group

# What a handler may need before it can run, and how to ask for it.
NEEDS: dict[str, str] = {
    "case": "Which case? Give the case id (e.g. 'case CASE-12').",
    "saved_case": "Which case? Give the id of an audited case (e.g. 'case CASE-12').",
    "docs": "Send the documents in `docs` (same shape as POST /audit/run).",
    "rule": "Which rule? Give a rule id such as CHK-001 or POL-07.",
    "doc_type": "Which document type? e.g. invoice, balance sheet, trial balance.",
    "text_values": "Describe the transaction with its amounts, e.g. 'paid Rs 150,000 cash, "
                   "booked on credit, no asset recorded'.",
}


@dataclass(frozen=True)
class IntentSpec:
    name: str
    group: Group
    description: str
    examples: tuple[str, ...]
    handler: Callable
    patterns: dict[str, float] = field(default_factory=dict)  # regex -> weight
    signals: dict[str, float] = field(default_factory=dict)  # entity/flag -> weight
    needs: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()  # next questions offered to the user


REGISTRY: dict[str, IntentSpec] = {}
FALLBACK_INTENT = "help"


def intent(name: str, *, group: Group, description: str, examples: tuple[str, ...],
           patterns: dict[str, float] | None = None, signals: dict[str, float] | None = None,
           needs: tuple[str, ...] = (), follow_ups: tuple[str, ...] = ()):
    unknown = set(needs) - set(NEEDS)
    if unknown:
        raise ValueError(f"intent {name}: unknown needs {sorted(unknown)}")

    def register(fn: Callable) -> Callable:
        if name in REGISTRY:
            raise ValueError(f"intent {name!r} registered twice")
        REGISTRY[name] = IntentSpec(name=name, group=group, description=description,
                                    examples=examples, handler=fn, patterns=patterns or {},
                                    signals=signals or {}, needs=needs,
                                    follow_ups=follow_ups)
        return fn
    return register
