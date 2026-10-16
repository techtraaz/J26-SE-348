"""Agent 5: Evidence Validation — every cited ID must exist.
Drops whole finding but logs it with reason; rejected_citations holds ONLY failing IDs."""
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, RejectedFinding, TraceEntry


def run(case: AuditCase, findings: list[Finding]
        ) -> tuple[list[Finding], list[RejectedFinding], list[str], list[TraceEntry]]:
    doc_ids = {d.doc_id for d in case.docs}
    kept: list[Finding] = []
    rejected: list[RejectedFinding] = []
    bad_ids: list[str] = []
    for f in findings:
        bad = [e for e in f.evidence_ids if e not in doc_ids]
        if bad:
            f.evidence_validation = "failed"
            rejected.append(RejectedFinding(
                finding=f,
                reason=f"cited IDs not in case: {', '.join(bad)}"))
            for b in bad:
                if b not in bad_ids:
                    bad_ids.append(b)
            continue
        f.evidence_validation = "passed"
        kept.append(f)
    trace = [TraceEntry(agent_name="evidence_validation", decision_type="validate",
                        detail=f"Checked {len(findings)} finding(s), kept {len(kept)}, rejected {len(rejected)}.")]
    return kept, rejected, bad_ids, trace
