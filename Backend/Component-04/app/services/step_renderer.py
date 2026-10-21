"""Deterministic wording for C03's granular XAI steps.

C03 sends facts (rule, values, outcome); this module owns how they read in
the Thinking timeline. Every row is "<verb> <target>" plus a short detail
and an expandable list of facts, e.g.

    Failed   CHK-001 on BS-2024
             Accounting equation: Assets 152,000,000 ≠ Liabilities + Capital 152,600,000

No LLM is involved: the text is a faithful rendering of what the agents
actually did, so it can be shown to an auditor as an explanation.
"""

from __future__ import annotations

import re
from typing import Any

# ── Stages ─────────────────────────────────────────────────────────────

STAGE_LABELS: dict[str, str] = {
    "data_quality": "Data quality",
    "compliance": "Compliance",
    "anomaly": "Anomaly detection",
    "reasoning": "Reasoning",
    "evidence_validation": "Evidence validation",
    "copilot_nlu": "Understanding the request",
    "copilot": "Preparing the answer",
}


def stage_label(agent: str | None) -> str:
    if not agent:
        return "Pipeline"
    return STAGE_LABELS.get(agent, humanize(agent))


# Passing steps of these kinds are summarised as "N checks passed" in the UI.
CHECK_KINDS = frozenset({"dq_check", "rule_check", "policy_check", "citation_check",
                         "standard_check", "evidence_link"})

_TONES = {"failed": "danger", "error": "danger", "review": "warning", "skipped": "muted",
          "passed": "success"}

_OP_HOLDS = {"==": "=", "!=": "≠", "<": "<", "<=": "≤", ">": ">", ">=": "≥"}
_OP_FAILS = {"==": "≠", "!=": "=", "<": "≥", "<=": ">", ">": "≤", ">=": "<"}

_DOC_TYPES = {"balance_sheet": "balance sheet", "income_statement": "income statement",
              "purchase_order": "purchase order", "goods_received_note": "goods received note"}


# ── Formatting helpers ─────────────────────────────────────────────────

def fmt_value(value: Any) -> str:
    """152000000.0 -> "152,000,000"; 0.5 -> "0.50"; text stays text."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    if value is None:
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(fmt_value(v) for v in value) or "—"
    return str(value)


def humanize(name: str) -> str:
    """"liabilities + capital" -> "Liabilities + Capital"; "child.amount" -> "Child amount"."""
    text = str(name).replace("_", " ").replace(".", " ").strip()
    if any(op in text for op in "+-*/"):
        return " ".join(w[:1].upper() + w[1:] if w.isalpha() else w for w in text.split())
    return text[:1].upper() + text[1:]


def doc_type_label(doc_type: str | None) -> str:
    if not doc_type or doc_type == "unknown":
        return "document of unknown type"
    return _DOC_TYPES.get(doc_type, doc_type.replace("_", " "))


def kg_source_label(source: str | None) -> str:
    """Never surfaces internal source names; the offline copy is named as such."""
    if source == "live":
        return "Knowledge Graph (C02)"
    return "Knowledge Graph (C02, offline rule set)"


def _fact(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": fmt_value(value)}


def _facts(*pairs: tuple[str, Any]) -> list[dict[str, str]]:
    return [_fact(label, value) for label, value in pairs
            if value not in (None, "", [], {})]


def _row(verb: str, target: str, detail: str = "", facts: list | None = None) -> dict:
    return {"verb": verb, "target": target, "detail": detail, "facts": facts or []}


# ── Per-kind templates ────────────────────────────────────────────────

def _evidence_read(f: dict, status: str) -> dict:
    src = f.get("source")
    if src is None:
        origin = "values supplied directly"
    elif f.get("verified_version") is not None:
        who = f" by {f['confirmed_by']}" if f.get("confirmed_by") else ""
        origin = f"{src.upper()} verified record v{f['verified_version']}{who}"
    else:
        origin = f"{src.upper()} extraction, not yet verified by a person"
    fields = f.get("fields") or {}
    count = f.get("field_count", len(fields))
    detail = f"{doc_type_label(f.get('doc_type'))} · {count} field{'s' if count != 1 else ''} · {origin}"
    return _row("Read", f.get("doc_id", "document"), detail, _facts(
        ("Document type", doc_type_label(f.get("doc_type"))),
        ("Period", f.get("period_year")),
        ("Supports", f.get("parent_doc_id")),
        ("Source", origin),
        ("Lowest confidence", f.get("min_confidence")),
        ("Read by", f.get("methods")),
        *[(humanize(k), v) for k, v in list(fields.items())[:8]]))


def _dq_check(f: dict, status: str) -> dict:
    if status == "passed":
        return _row("Checked", f.get("doc_id", "document"), f.get("check", "data quality"),
                    _facts(("Document type", doc_type_label(f.get("doc_type")))))
    verb = "Needs review" if status == "review" else "Flagged"
    return _row(verb, f"{f.get('rule_id', '')} on {f.get('doc_id', '')}".strip(),
                f.get("reason", ""), _facts(("Rule", f.get("rule_id")),
                                            ("Severity", f.get("severity")),
                                            ("Finding", f.get("reason"))))


_KG_TARGETS = {
    "get_check_rules": "check rules", "get_rules": "policy rules",
    "get_evidence_chain": "evidence chain", "explain_rule": "rule basis",
    "get_standard": "standard", "get_section": "section", "get_definitions": "definitions",
    "get_line_item": "line item", "get_field_map": "field names", "search": "standards search",
}


def _kg_fetch(f: dict, status: str) -> dict:
    method, arg = f.get("method", ""), f.get("arg", "")
    result = f.get("result") or {}
    source = kg_source_label(f.get("source"))
    base = _facts(("Source", source), ("Query", arg))
    if status == "error":
        return _row("Could not fetch", _KG_TARGETS.get(method, method),
                    f"{arg} · {f.get('error', 'no answer')}", base)
    if method in ("get_check_rules", "get_rules"):
        n = result.get("count", 0)
        noun = "check rule" if method == "get_check_rules" else "policy rule"
        return _row("Fetched", f"{n} {noun}{'s' if n != 1 else ''}",
                    f"for {doc_type_label(arg)} from the Knowledge Graph",
                    base + _facts(("Rules", result.get("ids"))))
    if method == "explain_rule":
        stds = result.get("standards") or []
        detail = f"cites {', '.join(stds)}" if stds else "no standard cited"
        return _row("Looked up", f"basis of {arg}", detail,
                    base + _facts(("Standards", stds), ("Assertions", result.get("assertions"))))
    if method == "get_evidence_chain":
        ids = [i for i in (result.get("ids") or []) if i != arg]
        detail = f"linked to {', '.join(ids)}" if ids else "no linked documents"
        return _row("Traced", f"evidence chain of {arg}", detail, base + _facts(("Linked", ids)))
    if method == "get_standard":
        if not result.get("found", True):
            return _row("Looked up", f"standard {arg}", "not found in the Knowledge Graph", base)
        return _row("Looked up", f"standard {result.get('code', arg)}",
                    f"{result.get('title') or ''} · {result.get('status', '')}".strip(" ·"),
                    base + _facts(("Title", result.get("title")), ("Status", result.get("status"))))
    if method == "search":
        return _row("Searched", "standards", f"“{arg}” · {result.get('count', 0)} result(s)", base)
    target = _KG_TARGETS.get(method, humanize(method))
    return _row("Looked up", f"{target} {arg}".strip(), "from the Knowledge Graph", base)


def _side_text(sides: dict, op_map: dict[str, str]) -> str:
    op = op_map.get(sides.get("op", ""), sides.get("op", ""))
    return (f"{humanize(sides['left'])} {fmt_value(sides.get('left_value'))} {op} "
            f"{humanize(sides['right'])} {fmt_value(sides.get('right_value'))}")


def _plain_reason(reason: str) -> str:
    """"missing current_liabilities" -> "missing current liabilities";
    "missing prior.amount" -> "missing prior amount"."""
    return re.sub(r"[a-z]+(?:[._][a-z0-9]+)+", lambda m: m.group(0).replace("_", " ").replace(".", " "),
                  reason)


def _rule_check(f: dict, status: str) -> dict:
    rule_id, doc_id = f.get("rule_id", "rule"), f.get("doc_id", "")
    name = f.get("rule_name") or rule_id
    sides = f.get("sides") or None
    values = f.get("values") or {}
    others = f.get("compared_with") or {}
    facts = _facts(("Rule", f"{rule_id} · {name}" if name != rule_id else rule_id),
                   ("Expression", f.get("expression")),
                   ("Document", doc_id))
    facts += _facts(*[(f"{humanize(scope)} document", d) for scope, d in others.items()
                      if d != doc_id])
    facts += _facts(*[(humanize(k), v) for k, v in values.items()])
    if sides:
        facts += _facts((humanize(sides["left"]), sides.get("left_value")),
                        (humanize(sides["right"]), sides.get("right_value")))
        lv, rv = sides.get("left_value"), sides.get("right_value")
        if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
            facts += _facts(("Difference", abs(lv - rv)))
        # the sides already show these values; drop duplicate labels
        seen: set[str] = set()
        facts = [x for x in facts if not (x["label"] in seen or seen.add(x["label"]))]
    target = f"{rule_id} on {doc_id}" if doc_id else rule_id
    if status == "passed":
        detail = f"{name}: {_side_text(sides, _OP_HOLDS)}" if sides else f"{name} holds"
        return _row("Checked", target, detail, facts)
    if status == "failed":
        detail = f"{name}: {_side_text(sides, _OP_FAILS)}" if sides else f"{name} does not hold"
        facts += _facts(("Severity", f.get("severity")))
        if f.get("below_materiality"):
            facts += _facts(("Materiality", ("difference is below the case materiality; "
                                             "kept at low severity")))
        return _row("Failed", target, detail, facts)
    if status == "skipped":
        why = _plain_reason(f.get("reason") or "not applicable")
        return _row("Skipped", target, f"{name}: {why}", facts + _facts(("Reason", why)))
    return _row("Could not evaluate", target, f.get("reason") or name,
                facts + _facts(("Reason", f.get("reason"))))


def _policy_check(f: dict, status: str) -> dict:
    target = f"{f.get('rule_id', 'policy')} on {f.get('doc_id', '')}".strip()
    field, amount, limit = humanize(f.get("field", "amount")), f.get("amount"), f.get("limit")
    need, signed = f.get("approvals_required"), f.get("approvals_signed")
    facts = _facts(("Policy", f.get("text")), (field, amount), ("Limit", limit),
                   ("Approvals required", need), ("Approvals signed", signed))
    over = (f"{field} {fmt_value(amount)} > limit {fmt_value(limit)}"
            if isinstance(amount, (int, float)) and isinstance(limit, (int, float)) and amount > limit
            else None)
    if over:
        facts += _facts(("Above limit by", amount - limit))
    if status == "failed":
        if signed is not None and need is not None:
            return _row("Failed", target, f"{over} · only {fmt_value(signed)} of {fmt_value(need)} "
                                          f"required approvals signed", facts)
        return _row("Failed", target, f"{over or field} · required approval must be confirmed", facts)
    if status == "review":
        return _row("Needs review", target, f"{over or field} · confirm the required approval "
                                                f"(approval stamp not read)", facts)
    if over:
        return _row("Checked", target, f"{over} · {fmt_value(signed)} of {fmt_value(need)} "
                                       f"required approvals signed", facts)
    return _row("Checked", target, f"{field} {fmt_value(amount)} ≤ limit {fmt_value(limit)}", facts)


def _standard_check(f: dict, status: str) -> dict:
    code = f.get("standard", "standard")
    facts = _facts(("Title", f.get("title")), ("Status", f.get("standard_status")),
                   ("Superseded by", f.get("superseded_by")), ("Cited by", f.get("rule_ids")))
    if status == "failed":
        later = f", superseded by {', '.join(f['superseded_by'])}" if f.get("superseded_by") else ""
        return _row("Compared with", f"standard {code}",
                    f"{f.get('standard_status', 'not current')}{later} · basis must be rechecked",
                    facts)
    detail = f"{f.get('title') or code} · current" if f.get("standard_status") != "unknown" \
        else "not found in the Knowledge Graph"
    return _row("Compared with", f"standard {code}", detail, facts)


def _evidence_link(f: dict, status: str) -> dict:
    doc_id = f.get("doc_id", "document")
    linked, missing = f.get("linked") or [], f.get("missing") or []
    facts = _facts(("Linked documents", linked), ("Missing from case", missing))
    if status == "failed":
        return _row("Missing evidence", f"for {doc_id}",
                    f"linked to {', '.join(missing)}, not in this case", facts)
    detail = "all linked documents are in the case" if linked else "no linked documents"
    return _row("Traced", f"evidence of {doc_id}", detail, facts)


def _citation_check(f: dict, status: str) -> dict:
    target = f"citations of {f.get('finding_id', f.get('rule_id', 'finding'))}"
    facts = _facts(("Rule", f.get("rule_id")), ("Cited", f.get("evidence_ids")))
    for c in f.get("claims") or []:
        label = f"{c.get('doc_id')}.{c.get('field')}"
        facts.append(_fact(label, f"claimed {fmt_value(c.get('claimed'))} · "
                                  f"document holds {fmt_value(c.get('actual'))}"))
    if status == "failed":
        return _row("Citation mismatch", target, "; ".join(f.get("problems") or []), facts)
    if status == "info":
        return _row("Confirmed", target, "cited documents exist (no values to compare)", facts)
    return _row("Verified", target, "claimed values match the documents", facts)


def _llm_purpose(purpose: str) -> str:
    """What the model was asked to do, in the reader's words."""
    p = purpose.lower()
    if "intent" in p or "understanding" in p:
        return "read the request"
    if "summary" in p:
        return "write the summary line"
    if p.startswith("structured"):
        return "read the request"
    return purpose or "help"


def _llm_problem(reason: str) -> str:
    """A short, human reason for a failed call; the raw error stays in the facts."""
    r = reason.lower()
    if any(code in r for code in ("530", "502", "503", "504", "connection", "refused", "unreachable",
                                  "name or service", "getaddrinfo")):
        return "the model server could not be reached"
    if "timed out" in r or "timeout" in r:
        return "the model took too long to answer"
    if "schema" in r or "json" in r:
        return "the model's answer could not be used"
    if "recent failure" in r:
        return "it failed a moment ago, so it is paused briefly"
    if "turned off" in r:
        return "it is turned off"
    return "it did not answer"


def _llm_call(f: dict, status: str) -> dict:
    task = _llm_purpose(f.get("purpose") or "")
    model = f.get("model")
    facts = _facts(("Task", task), ("Model", model), ("Prompt", f.get("prompt")),
                   ("Reply", f.get("reply")), ("Technical detail", f.get("reason")))
    if status == "ok":
        return _row("Asked", "the language model", f"to {task}{f' · {model}' if model else ''}", facts)
    fallback = ("keyword rules were used instead" if task == "read the request"
                else "a fixed wording was used instead")
    if status == "error":
        return _row("Couldn't use", "the language model",
                    f"{_llm_problem(f.get('reason') or '')} · {fallback}", facts)
    return _row("Used", "keyword rules" if task == "read the request" else "fixed wording",
                f"language model not used: {_llm_problem(f.get('reason') or '')}", facts)


def _entities(f: dict, status: str) -> dict:
    found = f.get("found") or {}
    parts = []
    if f.get("case_id"):
        parts.append(f"case {f['case_id']}")
    for key, noun in (("rule_ids", "rule"), ("doc_ids", "document"), ("doc_types", "type"),
                      ("standards", "standard")):
        vals = found.get(key) or []
        if vals:
            parts.append(f"{noun}{'s' if len(vals) > 1 else ''} {', '.join(map(str, vals))}")
    target = ", ".join(parts) if parts else "no specific case or rule"
    detail = "from the conversation" if f.get("from_memory") else "from the question"
    return _row("Recognised", target, detail,
                _facts(*[(humanize(k), v) for k, v in found.items()]))


def _decision(f: dict, status: str) -> dict:
    verb = "Decided" if status not in ("failed", "skipped") else (
        "Stopped" if f.get("decision") == "audit stopped" else "Excluded"
        if "excluded" in (f.get("decision") or "") else "Needs input")
    target = f.get("doc_id") or f.get("decision") or "decision"
    detail = f.get("reason") or f.get("decision") or ""
    if f.get("doc_id") and f.get("decision"):
        detail = f"{f['decision']} · {detail}"
    return _row(verb, target, detail, _facts(("Decision", f.get("decision")),
                                             ("Reason", f.get("reason"))))


_RENDERERS = {
    "evidence_read": _evidence_read, "dq_check": _dq_check, "kg_fetch": _kg_fetch,
    "rule_check": _rule_check, "policy_check": _policy_check,
    "standard_check": _standard_check, "evidence_link": _evidence_link,
    "citation_check": _citation_check, "llm_call": _llm_call, "entities": _entities,
    "decision": _decision,
}


def render_step(kind: str, status: str, facts: dict | None) -> dict:
    """Readable row for one step: verb, target, detail, tone, facts, check."""
    facts = facts or {}
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        row = _row(humanize(kind), "", str(facts.get("reason") or ""), _facts(
            *[(humanize(k), v) for k, v in facts.items() if not isinstance(v, (dict, list))]))
    else:
        try:
            row = renderer(facts, status)
        except Exception:  # noqa: BLE001 - a malformed step must never break the stream
            row = _row(humanize(kind), "", "", [])
    tone = _TONES.get(status, "neutral")
    if kind == "llm_call" and status in ("error", "skipped"):
        tone = "warning" if status == "error" else "muted"  # a fallback, not a failed check
    row.update(kind=kind, status=status, tone=tone, check=kind in CHECK_KINDS)
    return row


_INTENTS = {
    "whatif_check": "check a described transaction against the rules",
    "evidence_append": "add documents to the case and re-run it",
    "fresh_audit": "audit the attached documents",
    "rerun_audit": "re-run the case's audit",
    "explain_finding": "explain why a finding was raised",
    "list_findings": "list the case's findings",
    "evidence_gaps": "find missing or unverified evidence",
    "compare_versions": "compare two audit versions",
    "list_versions": "show the case's audit history",
    "case_status": "summarise the case's latest audit",
    "search_cases": "find cases matching a condition",
    "rule_explain": "explain a rule and its standard",
    "rule_lookup": "look up the rules for a document type",
    "standard_search": "look up an accounting or auditing standard",
    "help": "know what the assistant can do",
}


def render_intent(intent: str | None, method: str | None) -> dict:
    """The Copilot's reading of the request, as a step row."""
    how = {"llm": "the language model", "rules": "keyword rules",
           "rules_fallback": "keyword rules (language model unavailable)"}.get(
        method or "", humanize(method or "").lower())
    goal = _INTENTS.get(intent or "", humanize(intent or "request").lower())
    row = _row("Understood", "the request", f"you want to {goal}" + (f" · read by {how}" if how else ""),
               _facts(("Request type", humanize(intent or "")), ("Read by", how)))
    row.update(kind="intent", status="ok", tone="neutral", check=False)
    return row
