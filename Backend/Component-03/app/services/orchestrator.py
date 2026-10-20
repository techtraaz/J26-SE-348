"""LangGraph hybrid parallel-sequential pipeline.

    data_quality -> (compliance || anomaly) -> reasoning -> evidence_validation

- data_quality can stop the run early (explicit early_stop flag); the result is
  then not_auditable and carries the DQ findings as reasons.
- Rejected documents are excluded from compliance and anomaly.
- Per-run objects (KG client, seq counter) travel in the run config, so
  concurrent runs never share state.
- An XAITracerCallback is injected into every graph run.  It writes granular
  trace events to MongoDB (fire-and-forget) for Component-04 to observe.
"""
import itertools
import operator
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app import config as settings
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult, Finding, TraceEntry, now_iso
from app.services import intake
from app.services.agents import (
    anomaly,
    compliance,
    data_quality,
    evidence_validation,
    reasoning,
)
from app.services.kg_client import KGClient, default_kg
from app.services.store import ResultStore, default_store
from app.services.xai_callback import XAITracerCallback


class OrchestratorConfigError(RuntimeError):
    """A graph node ran without its per-run context."""


@dataclass
class RunContext:
    case_id: str
    kg: KGClient
    narrate: bool = True  # one LLM trace line from Reasoning; off for what-if checks
    seq: Iterator[int] = field(default_factory=lambda: itertools.count(1))


class AuditState(TypedDict):
    case: AuditCase
    findings: Annotated[list, operator.add]  # DQ + compliance + anomaly
    trace: Annotated[list, operator.add]
    rejected_records: list
    early_stop: bool
    reasoned: list
    final_findings: list
    rejected_citations: list
    rejected_findings: list


def _ctx(run_config: RunnableConfig | None) -> RunContext:
    ctx = ((run_config or {}).get("configurable") or {}).get("ctx")
    if not isinstance(ctx, RunContext):
        raise OrchestratorConfigError("Graph node ran without a RunContext; use run_case().")
    return ctx


def _checkable(state: AuditState) -> AuditCase:
    case = state["case"]
    bad = set(state.get("rejected_records") or [])
    # a copy, so case-level settings such as materiality travel with the documents
    return case.model_copy(update={"docs": [d for d in case.docs if d.doc_id not in bad]})


def _finish(ctx: RunContext, agent: str, findings: list, update: dict) -> dict:
    """Stamp completion order on the agent's trace."""
    for t in update["trace"]:
        t.seq = next(ctx.seq)
    return update


def n_data_quality(state: AuditState, config: RunnableConfig) -> dict:
    ctx = _ctx(config)
    f, rejected, stop, t = data_quality.run(state["case"])
    return _finish(ctx, "data_quality", f, {"findings": f, "trace": t,
                                            "rejected_records": rejected, "early_stop": stop})


def route_after_dq(state: AuditState):
    return END if state["early_stop"] else ["compliance", "anomaly"]


def n_compliance(state: AuditState, config: RunnableConfig) -> dict:
    ctx = _ctx(config)
    f, t = compliance.run(_checkable(state), ctx.kg)
    return _finish(ctx, "compliance", f, {"findings": f, "trace": t})


def n_anomaly(state: AuditState, config: RunnableConfig) -> dict:
    ctx = _ctx(config)
    f, t = anomaly.run(_checkable(state), ctx.kg)
    return _finish(ctx, "anomaly", f, {"findings": f, "trace": t})


def n_reasoning(state: AuditState, config: RunnableConfig) -> dict:
    ctx = _ctx(config)
    merged, t = reasoning.run(state["case"], list(state["findings"]), ctx.kg, ctx.narrate)
    return _finish(ctx, "reasoning", merged, {"reasoned": merged, "trace": t})


def n_evidence_validation(state: AuditState, config: RunnableConfig) -> dict:
    ctx = _ctx(config)
    kept, rejected, bad_ids, t = evidence_validation.run(state["case"], list(state["reasoned"]))
    return _finish(ctx, "evidence_validation", kept, {
        "final_findings": kept, "rejected_findings": rejected,
        "rejected_citations": bad_ids, "trace": t})


def build_graph():
    g = StateGraph(AuditState)
    g.add_node("data_quality", n_data_quality)
    g.add_node("compliance", n_compliance)
    g.add_node("anomaly", n_anomaly)
    g.add_node("reasoning", n_reasoning)
    g.add_node("evidence_validation", n_evidence_validation)
    g.add_edge(START, "data_quality")
    g.add_conditional_edges("data_quality", route_after_dq)
    g.add_edge(["compliance", "anomaly"], "reasoning")  # waits for both branches
    g.add_edge("reasoning", "evidence_validation")
    g.add_edge("evidence_validation", END)
    return g.compile()


GRAPH = build_graph()


def _initial(case: AuditCase) -> dict:
    return {"case": case, "findings": [], "trace": [], "rejected_records": [],
            "early_stop": False, "reasoned": [], "final_findings": [],
            "rejected_citations": [], "rejected_findings": []}


def _result(case: AuditCase, final: dict, version: int, previous: dict | None,
            kg: KGClient, latency_ms: float) -> AuditResult:
    early = final["early_stop"]
    findings: list[Finding] = list(final["findings"] if early else final["final_findings"])
    if previous:
        seen = {f["finding_id"] for f in previous.get("findings", [])}
        for f in findings:
            if f.finding_id in seen:
                f.supersedes = previous["version"]
    kg_note = f"Knowledge graph source: {kg.source}."
    if getattr(kg, "fallback_reason", None):
        kg_note += f" Live KG unavailable ({kg.fallback_reason}); mock rules used."
    return AuditResult(
        case_id=case.case_id, version=version, kg_source=kg.source, latency_ms=latency_ms,
        status="not_auditable" if early else settings.FINDINGS_STATUS_DEFAULT,
        findings=findings,
        trace=list(final["trace"]) + [TraceEntry(agent_name="kg", decision_type="source",
                                                 detail=kg_note)],
        rejected_records=list(final["rejected_records"]),
        rejected_citations=[] if early else list(final["rejected_citations"]),
        rejected_findings=[] if early else list(final["rejected_findings"]))


def _execute(case: AuditCase, kg: KGClient | None,
             store: ResultStore | None, narrate: bool = True) -> Iterator[tuple[str, Any]]:
    """Run the graph once. Yields ("update", per-node update) then ("result", AuditResult)."""
    kg = kg or default_kg()
    store = store or default_store()
    previous = store.latest(case.case_id)
    version = store.next_version(case.case_id)
    ctx = RunContext(case_id=case.case_id, kg=kg, narrate=narrate)

    # Fire-and-forget XAI callback — writes to MongoDB for C04 to observe.
    xai_cb = XAITracerCallback(case.case_id, version, store.traces_collection())
    xai_cb._emit({"event_type": "pipeline_start",
                  "doc_count": len(case.docs), "ts": now_iso()})

    start = time.perf_counter()
    final: dict | None = None
    for mode, chunk in GRAPH.stream(
        _initial(case),
        config={"configurable": {"ctx": ctx}, "callbacks": [xai_cb]},
        stream_mode=["updates", "values"],
    ):
        if mode == "updates":
            yield "update", chunk
        else:
            final = chunk
    if final is None:
        raise OrchestratorConfigError("Graph produced no final state.")
    result = _result(case, final, version, previous,
                     kg, round((time.perf_counter() - start) * 1000, 3))
    store.save(case, result)

    xai_cb._emit({"event_type": "pipeline_end",
                  "total_findings": len(result.findings),
                  "status": result.status, "ts": now_iso()})
    yield "result", result


def run_case(case: AuditCase, kg: KGClient | None = None,
             store: ResultStore | None = None, narrate: bool = True) -> AuditResult:
    for kind, data in _execute(case, kg, store, narrate):
        if kind == "result":
            return data
    raise OrchestratorConfigError("Run ended without a result.")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def stream_case(case: AuditCase, kg: KGClient | None = None,
                store: ResultStore | None = None) -> Iterator[dict]:
    """One graph run: one JSON-safe event per finished node, then the result."""
    for kind, data in _execute(case, kg, store):
        if kind == "update":
            yield {"event": "update",
                   "data": {node: {k: v for k, v in _jsonable(upd).items() if k != "case"}
                            for node, upd in data.items()}}
        else:
            yield {"event": "result", "data": data.model_dump()}


def append_evidence(case_id: str, docs: list[dict], kg: KGClient | None = None,
                    store: ResultStore | None = None,
                    materiality: float | None = None) -> AuditResult:
    """FR5/FR6: add documents to the latest saved version of a case and re-run.
    The earlier version stays saved; the new run gets the next version. The case's
    materiality carries over unless a new one is given."""
    store = store or default_store()
    previous = store.latest(case_id)
    if previous is None:
        raise LookupError(f"No saved audit for case {case_id!r}; run a fresh audit first.")
    merged = intake.normalize_case({
        "case_id": case_id, "docs": list(previous["case"]["docs"]) + list(docs),
        "materiality": materiality if materiality is not None else previous["case"].get("materiality")})
    return run_case(merged, kg, store)
