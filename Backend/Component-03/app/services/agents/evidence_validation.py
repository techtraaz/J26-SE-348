"""Agent 5: Evidence Validation. Every cited ID must exist in the case and every
claim's value must match the document (numbers within tolerance), in code.

A failing finding is KEPT in the main list with citation_unverified=True (a real
issue never vanishes) AND logged in rejected_findings with the reason.
rejected_citations holds only the failing IDs.
"""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, RejectedFinding, TraceEntry
from app.services import rules


def _matches(actual: object, claimed: float | str) -> bool:
    if isinstance(claimed, str):
        return isinstance(actual, str) and actual.strip().lower() == claimed.strip().lower()
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    return abs(float(actual) - claimed) <= config.AMOUNT_TOLERANCE


def run(case: AuditCase, findings: list[Finding]
        ) -> tuple[list[Finding], list[RejectedFinding], list[str], list[TraceEntry]]:
    by_id = {d.doc_id: d for d in case.docs}
    out = [f.model_copy(deep=True) for f in findings]
    rejected: list[RejectedFinding] = []
    bad_ids: list[str] = []
    for f in out:
        cited = list(dict.fromkeys(f.evidence_ids + [c.evidence_id for c in f.claims]))
        problems: list[str] = []
        bad: list[str] = []
        missing = [e for e in cited if e not in by_id]
        if missing:
            problems.append(f"cited IDs not in case: {', '.join(missing)}")
            bad += missing
        for c in f.claims:
            doc = by_id.get(c.evidence_id)
            if doc is None:
                continue
            actual = doc.fields.get(c.field)
            if not _matches(actual, c.claimed_value):
                problems.append(f"{c.evidence_id}.{c.field} claimed "
                                f"{rules.fmt(c.claimed_value)} but holds {actual!r}")
                if c.evidence_id not in bad:
                    bad.append(c.evidence_id)
        if problems:
            f.evidence_validation = "failed"
            f.citation_unverified = True
            rejected.append(RejectedFinding(finding=f.model_copy(deep=True),
                                            reason="; ".join(problems)))
            bad_ids += [b for b in bad if b not in bad_ids]
        elif f.claims:
            f.evidence_validation = "passed"
        elif cited:
            f.evidence_validation = "existence_only"
        else:
            f.evidence_validation = "unverified"
    counts = {s: sum(f.evidence_validation == s for f in out)
              for s in ("passed", "existence_only", "failed", "unverified")}
    trace = [TraceEntry(agent_name="evidence_validation", decision_type="validate",
                        detail=f"Checked {len(out)} finding(s): {counts['passed']} values "
                               f"verified, {counts['existence_only']} citations exist (no values "
                               f"to check), {counts['failed']} flagged, "
                               f"{counts['unverified']} with no evidence.")]
    return out, rejected, bad_ids, trace
