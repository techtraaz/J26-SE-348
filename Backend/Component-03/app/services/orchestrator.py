"""Hybrid flow: DQ -> (Compliance + Anomaly) -> Reasoning -> Validation."""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient
from app.services import telemetry

VERSION_STORE: dict[str, int] = {}  # case_id -> version, old versions kept by caller/DB


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    kg = kg or KGClient()
    trace_all = []
    all_findings = []

    telemetry.emit_pipeline_start(case.case_id, len(case.documents))

    dq_f, dq_t = data_quality.run(case)
    trace_all += dq_t
    telemetry.emit_agent_end(case.case_id, "data_quality", len(dq_f), dq_t[0].model_dump() if dq_t else {})
    # gate: still continue but mark low quality in trace (never silently drop)
    if dq_f:
        all_findings += dq_f

    comp_f, comp_t = compliance.run(case, kg)
    anom_f, anom_t = anomaly.run(case)  # parallel in design, sequential in code for now
    trace_all += comp_t + anom_t
    all_findings += comp_f + anom_f
    telemetry.emit_agent_end(case.case_id, "compliance", len(comp_f), comp_t[0].model_dump() if comp_t else {})
    telemetry.emit_agent_end(case.case_id, "anomaly", len(anom_f), anom_t[0].model_dump() if anom_t else {})

    merged, reas_t = reasoning.run(case, all_findings)
    trace_all += reas_t
    telemetry.emit_agent_end(case.case_id, "reasoning", len(merged), reas_t[0].model_dump() if reas_t else {})

    final_findings, val_t = evidence_validation.run(case, merged)
    trace_all += val_t
    telemetry.emit_agent_end(case.case_id, "evidence_validation", len(final_findings), val_t[0].model_dump() if val_t else {})

    telemetry.emit_pipeline_end(case.case_id, len(final_findings))

    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=final_findings, trace=trace_all)

