"""Understanding a request: which intent it is. Confidence-gated, like C1's
OCR -> VLM routing:

1. The rules classifier (patterns + entity signals from the registry) always
   runs. When it is confident (clear top score and margin) its answer is used.
2. Otherwise the LLM (any self-hosted model, see app.services.llm) picks one
   intent name from the registry, constrained by a JSON schema.
3. If the LLM is off, slow or replies outside the registry, the rules answer
   is used and the reason is recorded.

Modes (C03_COPILOT_NLU): auto (the above), rules (never the LLM), llm (always
ask the LLM). Entities are never taken from the LLM (see entities.py).
"""
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, create_model

from app import config
from app.services import llm
from app.services.copilot.entities import Entities
from app.services.copilot.registry import FALLBACK_INTENT, REGISTRY

MIN_RULE_SCORE = 1.0


@dataclass
class Understanding:
    intent: str
    # rules: rules were confident (or mode=rules); llm: the LLM decided;
    # rules_fallback: rules were unsure but the LLM could not answer
    method: Literal["rules", "llm", "rules_fallback"]
    rules_intent: str
    rules_confident: bool
    rules_scores: dict[str, float] = field(default_factory=dict)
    llm_intent: str | None = None
    llm_error: str | None = None

    def as_dict(self) -> dict:
        return {"method": self.method, "rules_intent": self.rules_intent,
                "rules_confident": self.rules_confident, "llm_intent": self.llm_intent,
                "llm_error": self.llm_error,
                "rules_scores": {k: v for k, v in self.rules_scores.items() if v}}


def is_confident(scores: dict[str, float]) -> bool:
    top = sorted(scores.values(), reverse=True)[:2] + [0.0, 0.0]
    return (top[0] >= config.COPILOT_RULES_CONFIDENT_SCORE
            and top[0] - top[1] >= config.COPILOT_RULES_MARGIN)


@dataclass(frozen=True)
class RequestContext:
    """What the request carries besides its text."""
    has_docs: bool = False
    case_id: str | None = None
    case_audited: bool = False  # the case already has a saved audit

    def describe(self) -> str:
        return (f"Documents attached: {'yes' if self.has_docs else 'no'}. "
                f"Current case: {self.case_id or 'none'}"
                f"{' (already audited)' if self.case_audited else ''}.")


def _flags(entities: Entities, ctx: RequestContext) -> dict[str, bool]:
    """Entity flags plus context flags the registry signals can use."""
    flags = {k: bool(v) for k, v in entities.__dict__.items()}
    flags.update(docs=ctx.has_docs, case=bool(ctx.case_id or entities.case_ids),
                 docs_for_audited_case=ctx.has_docs and ctx.case_audited)
    return flags


def rules_classify(text: str, entities: Entities,
                   ctx: RequestContext) -> tuple[str, dict[str, float]]:
    """Highest score wins; ties go to the intent registered first."""
    flags = _flags(entities, ctx)
    scores: dict[str, float] = {}
    for name, spec in REGISTRY.items():
        s = sum(w for p, w in spec.patterns.items() if re.search(p, text, re.IGNORECASE))
        s += sum(w for k, w in spec.signals.items() if flags.get(k))
        scores[name] = round(s, 3)
    best = max(scores, key=lambda n: scores[n]) if scores else FALLBACK_INTENT
    return (best if scores.get(best, 0) >= MIN_RULE_SCORE else FALLBACK_INTENT), scores


def _choice_model(names: tuple[str, ...]) -> type[BaseModel]:
    return create_model("IntentChoice", intent=(Literal[names], ...))  # type: ignore[valid-type]


def _system_prompt(names: tuple[str, ...]) -> str:
    lines = ["You route an internal auditor's request to exactly one intent.",
             "Reply with JSON {\"intent\": <name>} using one of these names:"]
    for name in names:
        spec = REGISTRY[name]
        ex = " | ".join(f'"{e}"' for e in spec.examples[:2])
        lines.append(f"- {spec.name}: {spec.description} Examples: {ex}")
    return "\n".join(lines)


def candidates(scores: dict[str, float]) -> tuple[str, ...]:
    """The rules' top choices (plus help) when they scored anything; else every
    intent. A small model chooses better among a few close options."""
    ranked = [n for n in sorted(scores, key=lambda n: -scores[n]) if scores[n] > 0]
    if not ranked:
        return tuple(REGISTRY)
    picked = ranked[:config.COPILOT_LLM_CANDIDATES]
    return tuple(dict.fromkeys([*picked, FALLBACK_INTENT]))


def llm_classify(text: str, ctx: RequestContext, names: tuple[str, ...] | None = None) -> str:
    """Raises llm.LLMError when no valid intent comes back."""
    names = names or tuple(REGISTRY)
    return llm.complete_json(_system_prompt(names), f"{ctx.describe()}\nRequest: {text}",
                             _choice_model(names)).intent


def understand(text: str, entities: Entities, ctx: RequestContext) -> Understanding:
    rules_intent, scores = rules_classify(text, entities, ctx)
    confident = is_confident(scores)
    mode = config.COPILOT_NLU

    def by_rules(method, error=None):
        return Understanding(rules_intent, method, rules_intent, confident, scores, llm_error=error)

    if mode == "rules" or (mode == "auto" and confident):
        return by_rules("rules")
    if not llm.available():
        return by_rules("rules_fallback", "LLM unavailable")
    try:
        names = candidates(scores) if mode == "auto" else tuple(REGISTRY)
        chosen = llm_classify(text, ctx, names)
    except llm.LLMError as exc:
        return by_rules("rules_fallback", str(exc))
    return Understanding(chosen, "llm", rules_intent, confident, scores, llm_intent=chosen)
