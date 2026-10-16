"""Agent 5: Evidence Validation — existence + value match, in code.
For every claim {evidence_id, field, claimed_value}: the document must exist
(claim IDs count the same as evidence_ids) and its field must equal the
claimed value (numbers within tolerance).
A failing finding is KEPT in the main list marked citation_unverified=True
(so a real issue never vanishes from what the auditor sees) AND logged in
rejected_findings with the reason. rejected_citations holds ONLY failing IDs."""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, RejectedFinding, TraceEntry


def _value_matches(actual: object, claimed: float | str) -> bool:
    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(claimed)) <= config.AMOUNT_TOLERANCE
    return actual == claimed


def run(case: AuditCase, findings: list[Finding]
        ) -> tuple[list[Finding], list[RejectedFinding], list[str], list[TraceEntry]]:
    by_id = {d.doc_id: d for d in case.docs}
    kept: list[Finding] = []
    rejected: list[RejectedFinding] = []
    bad_ids: list[str] = []
    for f in findings:
        claim_ids = [c.evidence_id for c in f.claims]
        missing = [e for e in list(f.evidence_ids) + claim_ids if e not in by_id]
        mismatched: list[str] = []
        for c in f.claims:
            doc = by_id.get(c.evidence_id)
            if doc is None:
                continue  # already counted in missing
            actual = doc.fields.get(c.field, None)
            if actual is None or not _value_matches(actual, c.claimed_value):
                if c.evidence_id not in mismatched:
                    mismatched.append(c.evidence_id)
        bad = sorted(set(missing) | set(mismatched))
        if bad:
            f.evidence_validation = "failed"
            f.citation_unverified = True
            problems = []
            if missing:
                problems.append(f"cited IDs not in case: {', '.join(sorted(set(missing)))}")
            value_bad = [c for c in f.claims
                         if c.evidence_id in by_id
                         and not _value_matches(by_id[c.evidence_id].fields.get(c.field, None),
                                                c.claimed_value)]
            for c in value_bad:
                actual = by_id[c.evidence_id].fields.get(c.field, None)
                problems.append(f"{c.evidence_id}.{c.field} claimed {c.claimed_value} but holds {actual}")
            rejected.append(RejectedFinding(finding=f, reason="; ".join(problems)))
            for b in bad:
                if b not in bad_ids:
                    bad_ids.append(b)
            kept.append(f)  # kept but flagged — auditor still sees the issue
            continue
        f.evidence_validation = "passed"
        kept.append(f)
    trace = [TraceEntry(agent_name="evidence_validation", decision_type="validate",
                        detail=f"Checked {len(findings)} finding(s), passed {len(kept) - len(rejected)}, flagged {len(rejected)}.")]
    return kept, rejected, bad_ids, trace
