"""Check a running Component-02 against what C3 needs, before relying on it.

    .venv\\Scripts\\python.exe -m scripts.check_kg_contract                       # KG_URL from .env
    .venv\\Scripts\\python.exe -m scripts.check_kg_contract --url http://localhost:8002

Uses C3's own live client (same validation as the agents), so a reply that
would break an audit shows up here first. Reports, per document type, which
rules exist, whether C3 can evaluate each one and which agent runs it; then the
rule explanations, the status of every cited standard, and the lookups the
Copilot uses. Exit code: 0 all fine, 1 contract problems, 2 C2 not reachable.
"""
import argparse
import sys

from app import config
from app.services import rules as rule_logic
from app.services.kg_client import (
    KGClient,
    KGError,
    KGProtocolError,
    KGUnavailable,
    LiveKGClient,
)

SAMPLES = {"section": "LKAS 2:9", "term": "net realisable value", "line_item": "capital",
           "search": "how should inventories be measured"}


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.problems: list[str] = []
        self.warnings: list[str] = []

    def say(self, text: str = "") -> None:
        self.lines.append(text)

    def problem(self, text: str) -> None:
        self.problems.append(text)
        self.lines.append(f"  PROBLEM: {text}")

    def warn(self, text: str) -> None:
        if text in self.warnings:
            return  # a rule shared by several document types is reported once
        self.warnings.append(text)
        self.lines.append(f"  warning: {text}")


def _try(report: Report, what: str, call):
    try:
        return call()
    except KGUnavailable:
        raise
    except (KGProtocolError, ValueError, KGError) as exc:
        report.problem(f"{what}: {exc}")
        return None


def _describe_rule(rule, field_map: dict[str, str]) -> tuple[str, list[str]]:
    if rule.rule_id in config.CODE_CHECKED_RULES:
        return "checked in C3 code (Data Quality)", []
    names = rule_logic.rule_names(rule)
    if names is None:
        return "NOT evaluable: expression cannot be parsed (would raise REV-006)", []
    agent = "Anomaly" if rule_logic.is_anomaly_rule(rule) else "Compliance"
    category = config.RULE_CATEGORY.get(rule.rule_id)
    note = f"{agent}, category {category or config.DEFAULT_RULE_CATEGORY + ' (default)'}"
    known = set(field_map) | set(field_map.values()) | set(config.NUMERIC_FIELDS) | {"purchase_basis"}
    unknown = [n for n in names if n.rpartition(".")[2] not in known
               and not any(v.name == n.rpartition(".")[2] for v in rule.variables)]
    return note, unknown


def run_checks(kg: KGClient, health: dict | None) -> Report:
    r = Report()
    r.say(f"Health: {health}")
    if health and health.get("neo4j") not in (None, "up"):
        r.problem(f"C2 reports Neo4j {health.get('neo4j')}")

    field_map = _try(r, "field map", kg.get_field_map) or {}
    r.say(f"Field names and aliases: {len(field_map)}")
    for alias in ("assets", "capital", "debit_total"):
        if alias not in field_map:
            r.warn(f"alias {alias!r} missing from /query/fields; documents using it will not match rules")

    rule_ids: set[str] = set()
    r.say("\nRules per document type (what each agent will run):")
    for doc_type in sorted(config.ALLOWED_DOC_TYPES - {"unknown"}):
        checks = _try(r, f"check-rules/{doc_type}", lambda t=doc_type: kg.get_check_rules(t)) or []
        policy = _try(r, f"rules/{doc_type}", lambda t=doc_type: kg.get_rules(t)) or []
        if not checks and not policy:
            r.say(f"- {doc_type}: no rules (only Data Quality checks run)")
            continue
        r.say(f"- {doc_type}:")
        for rule in checks:
            rule_ids.add(rule.rule_id)
            note, unknown = _describe_rule(rule, field_map)
            r.say(f"    {rule.rule_id} {rule.name} [{rule.severity}] {rule.expression!r} -> {note}")
            if note.startswith("NOT"):
                r.problem(f"{rule.rule_id} on {doc_type}: expression cannot be evaluated by C3")
            if unknown:
                r.warn(f"{rule.rule_id}: names {unknown} are not known field names or aliases")
            if rule.rule_id not in config.RULE_CATEGORY and rule.rule_id not in config.CODE_CHECKED_RULES:
                r.warn(f"{rule.rule_id}: no category from C2; C3 labels it "
                       f"'{config.DEFAULT_RULE_CATEGORY}'")
        for p in policy:
            rule_ids.add(p.rule_id)
            if p.limit is None:
                r.warn(f"{p.rule_id} on {doc_type}: no limit, C3 cannot apply it")
            r.say(f"    {p.rule_id} limit {p.limit} -> Compliance: C3 checks "
                  f"'{config.POLICY_LIMIT_FIELD} > limit' ({p.text})")

    r.say("\nRule explanations and cited standards:")
    cited: set[str] = set()
    for rule_id in sorted(rule_ids):
        exp = _try(r, f"explain {rule_id}", lambda i=rule_id: kg.explain_rule(i))
        if exp is None:
            r.warn(f"{rule_id}: no explanation; findings will have no standard basis")
            continue
        refs = [c.ref for c in exp.citations if c.ref]
        cited |= {c.standard for c in exp.citations if c.standard}
        r.say(f"- {rule_id}: cites {refs or 'nothing'}; tests {exp.assertions or '-'}; risk {exp.risks or '-'}")
    for code in sorted(cited):
        std = _try(r, f"standard {code}", lambda c=code: kg.get_standard(c))
        if std is None:
            r.warn(f"standard {code} not found")
        elif not std.current:
            r.warn(f"{code} is {std.status}{' (superseded by ' + ', '.join(std.superseded_by) + ')' if std.superseded_by else ''}; "
                   f"findings citing it will carry a caution")
        else:
            r.say(f"  {code}: {std.status}")

    r.say("\nLookups used by the Reasoning agent and the Copilot:")
    chain = _try(r, "evidence-chain", lambda: kg.get_evidence_chain("C3-CONTRACT-CHECK"))
    r.say(f"- evidence chain of an unknown doc: {chain} (only the doc itself until C2's ledger exists)")
    sec = _try(r, "section", lambda: kg.get_section(SAMPLES["section"]))
    r.say(f"- section {SAMPLES['section']}: {'found: ' + sec.heading if sec else 'not found'}")
    defs = _try(r, "definitions", lambda: kg.get_definitions(SAMPLES["term"])) or []
    r.say(f"- definition '{SAMPLES['term']}': {len(defs)} found")
    item = _try(r, "line item", lambda: kg.get_line_item(SAMPLES["line_item"]))
    r.say(f"- line item '{SAMPLES['line_item']}': {item.code if item else 'not found'}")
    hits = _try(r, "search", lambda: kg.search(SAMPLES["search"])) or []
    r.say(f"- search ({config.KG_SEARCH_MODE}): {len(hits)} result(s)"
          + (f", top {hits[0].get('section')} via {hits[0].get('via', '?')}" if hits else ""))
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=config.KG_URL, help="C2 base URL (default: KG_URL)")
    args = ap.parse_args()
    if not args.url:
        print("No C2 address: set KG_URL in .env or pass --url http://localhost:8002")
        return 2
    kg = LiveKGClient(args.url)
    try:
        health = kg._get("/health", {})
        report = run_checks(kg, health if isinstance(health, dict) else None)
    except KGUnavailable as exc:
        print(f"C2 is not reachable at {args.url}: {exc}\n"
              "Start C2 (port 8002) and make sure its Neo4j database is running.")
        return 2
    print(f"Component-02 at {args.url}\n" + "\n".join(report.lines))
    print(f"\n{len(report.problems)} problem(s), {len(report.warnings)} warning(s).")
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
