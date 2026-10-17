from app.graph.neo4j_client import run_read

TEXT_PREVIEW = 600

_CITE = ("{standard: st.code, title: st.title, paragraph: s.number, section: s.id, "
         "heading: s.heading, text: s.text}")


def _first(rows: list[dict]) -> dict | None:
    return rows[0] if rows else None


def _dedupe(citations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in citations:
        key = c.get("section") or c.get("standard")
        if key not in seen:
            seen.add(key)
            text = c.get("text")
            out.append({**c, "text": text[:TEXT_PREVIEW] if text else None})
    return out


def _sentence(row: dict) -> str:
    rule = row["rule"]
    if rule.get("expression"):
        parts = [f"{rule['rule_id']} {rule.get('name') or ''}".strip()
                 + f" checks `{rule['expression']}`."]
    else:
        limit = f" Limit {rule['limit']:,.0f}." if rule.get("limit") is not None else ""
        parts = [f"{rule['rule_id']}: {rule.get('text', '')}{limit}"]
    if row.get("doc_types"):
        parts.append("Applies to " + ", ".join(row["doc_types"]) + ".")
    for eq in row["equations"]:
        parts.append(f"It implements {eq['code']} {eq['name']} (`{eq['expression']}`).")
    cites = [f"{c['standard']} para {c['paragraph']} ({c['title']}, {c['heading']})"
             if c.get("paragraph") else f"{c['standard']} ({c['title']})"
             for c in row["citations"]]
    if cites:
        parts.append("Source: " + "; ".join(cites) + ".")
    if row["assertions"]:
        parts.append("Tests the " + ", ".join(row["assertions"]) + " assertion(s).")
    if row["risks"]:
        parts.append("Addresses: " + ", ".join(row["risks"]) + ".")
    return " ".join(parts)


def explain_rule(rule_id: str, run=run_read) -> dict | None:
    """Why a rule exists: rule -> equation/requirement -> paragraph -> standard."""
    row = _first(run(
        "MATCH (r) WHERE (r:CheckRule OR r:PolicyRule) AND r.rule_id = $id "
        "RETURN properties(r) AS rule, "
        "[(r)-[:IMPLEMENTS]->(e:Equation) | e {.code, .name, .expression, .kind}] AS equations, "
        "[(r)-[:IMPLEMENTS]->(q:Requirement) | q {.id, .text, .obligation}] AS requirements, "
        "[(r)-[:TESTS]->(a:AuditAssertion) | a.name] AS assertions, "
        "[(r)-[:ADDRESSES]->(k:Risk) | k.name] AS risks, "
        "[(r)-[:CHECKS_DOC_TYPE]->(d:DocumentType) | d.code] AS doc_types, "
        f"[(r)-[:DERIVED_FROM]->(s:Section)<-[:HAS_SECTION]-(st:Standard) | {_CITE}] + "
        f"[(r)-[:IMPLEMENTS]->()-[:DERIVED_FROM]->(s:Section)<-[:HAS_SECTION]-(st:Standard) | {_CITE}] + "
        f"[(r)-[:IMPLEMENTS]->(:Requirement)<-[:HAS_REQUIREMENT]-(s:Section)<-[:HAS_SECTION]-(st:Standard) | {_CITE}] "
        "AS section_citations, "
        "[(r)-[:DERIVED_FROM]->(st:Standard) | {standard: st.code, title: st.title}] AS standard_citations",
        id=rule_id))
    if not row:
        return None
    row["citations"] = _dedupe(row.pop("section_citations") + row.pop("standard_citations"))
    row["explanation"] = _sentence(row)
    return row


def get_standard(code: str, run=run_read) -> dict | None:
    return _first(run(
        "MATCH (st:Standard {code: $code}) "
        "RETURN properties(st) AS standard, "
        "[(st)-[:BELONGS_TO]->(f:Framework) | f.code] AS frameworks, "
        "[(st)-[:ISSUED_BY]->(b:RegulatoryBody) | b.name] AS issued_by, "
        "[(st)-[:SUPERSEDES]->(o:Standard) | o.code] AS supersedes, "
        "[(n:Standard)-[:SUPERSEDES]->(st) | n.code] AS superseded_by, "
        "[(a:Amendment)-[:AMENDS]->(st) | a {.id, .title, .effective_from}] AS amendments, "
        "[(st)-[:GOVERNS]->(x) | {label: labels(x)[0], code: x.code}] AS governs, "
        "COUNT { (st)-[:HAS_SECTION]->() } AS sections, "
        "COUNT { (st)-[:HAS_SECTION]->()-[:HAS_REQUIREMENT]->() } AS requirements",
        code=code))


def get_section(section_id: str, run=run_read) -> dict | None:
    return _first(run(
        "MATCH (s:Section {id: $id}) "
        "RETURN properties(s) AS section, "
        "[(st:Standard)-[:HAS_SECTION]->(s) | st {.code, .title, .status}][0] AS standard, "
        "[(s)-[:HAS_REQUIREMENT]->(q:Requirement) | q {.id, .type, .obligation, .text, .confidence, "
        "applies_to: [(q)-[:APPLIES_TO]->(x) | x.code]}] AS requirements, "
        "[(s)-[:DEFINES]->(d:Definition) | d {.id, .term, .text}] AS definitions, "
        "[(s)-[:REFERS_TO]->(x) | coalesce(x.id, x.code)] AS refers_to, "
        "[(x:Section)-[:REFERS_TO]->(s) | x.id] AS referred_by, "
        "[(a:Amendment)-[:AMENDS]->(s) | a {.id, .title, .effective_from}] AS amendments, "
        "[(s)-[:EXTRACTED_FROM]->(c:SourceChunk) | c {.id, .file, .page}] AS chunks",
        id=section_id))


def get_line_item(code: str, run=run_read) -> dict | None:
    return _first(run(
        "MATCH (li:LineItem) WHERE li.code = $code OR $code IN coalesce(li.aliases, []) "
        "RETURN properties(li) AS line_item, "
        "[(li)-[p:PRESENTED_IN]->(f:FinancialStatement) | {statement: f.code, name: f.name, "
        "section: p.section, order: p.order}] AS presented_in, "
        "[(li)-[:CLASSIFIED_AS]->(c:AccountClass) | c {.code, .name, .normal_balance}] AS classes, "
        "[(st:Standard)-[:GOVERNS]->(li) | st {.code, .title, .status}] AS governed_by, "
        "[(e:Equation)-[u:USES]->(li) | {code: e.code, name: e.name, expression: e.expression, "
        "role: u.role, sign: u.sign}] AS equations, "
        "[(li)-[m:MEASURED_AT]->(b:MeasurementBasis) | {basis: b.name, condition: m.condition}] "
        "AS measured_at, "
        "[(li)-[:DEFINED_BY]->(d:Definition) | d {.term, .text}] AS definitions",
        code=code))


def list_equations(statement: str | None = None, kind: str | None = None,
                   run=run_read) -> list[dict]:
    return run(
        "MATCH (e:Equation) "
        "WHERE ($kind IS NULL OR e.kind = $kind) "
        "AND ($statement IS NULL OR EXISTS { (e)-[:HOLDS_IN]->(:FinancialStatement {code: $statement}) }) "
        "RETURN e.code AS code, e.name AS name, e.expression AS expression, e.kind AS kind, "
        "[(e)-[:HOLDS_IN]->(f) | f.code] AS statements, "
        "[(e)-[:DERIVED_FROM]->(s:Section) | s.id] AS sources, "
        "[(r:CheckRule)-[:IMPLEMENTS]->(e) | r.rule_id] AS check_rules "
        "ORDER BY code",
        statement=statement, kind=kind)


def get_definition(term: str, run=run_read) -> list[dict]:
    return run(
        "MATCH (d:Definition) WHERE toLower(d.term) = toLower($term) OR d.id = $term "
        "RETURN d.id AS id, d.term AS term, d.text AS text, d.source AS source, "
        "[(s:Section)-[:DEFINES]->(d) | s.id] AS defined_in, "
        "[(x)-[:DEFINED_BY]->(d) | x.code] AS used_by",
        term=term)
