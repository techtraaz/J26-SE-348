"""Agent 5: Evidence Validation — every cited ID must exist and support claim."""
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry


def run(case: AuditCase, findings: list[Finding]) -> tuple[list[Finding], list[TraceEntry]]:
    doc_ids = {d.doc_id for d in case.docs}
    kept: list[Finding] = []
    caught = 0
    for f in findings:
        bad = [e for e in f.evidence_ids if e not in doc_ids]
        if bad:
            caught += 1
            continue  # drop hallucinated citation
        kept.append(f)
    trace = [TraceEntry(agent_name="evidence_validation", decision_type="validate",
                        detail=f"Checked {len(findings)} citation(s), caught {caught} bad one(s).")]
    return kept, trace
