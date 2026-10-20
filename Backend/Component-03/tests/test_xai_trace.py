"""XAI tracing must never slow down or break the audit (fire-and-forget)."""
import threading
import time

import mongomock

from app.services import orchestrator, xai_trace
from app.services.store import MongoStore
from app.services.xai_trace import RunTracer, TraceExporter
from tests.conftest import doc


class SlowCollection:
    """A collection whose every write takes `delay` seconds."""

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay, self.fail = delay, fail
        self.docs: list[dict] = []
        self.batches = 0
        self.lock = threading.Lock()

    def insert_many(self, docs, ordered=True):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("server down")
        with self.lock:
            self.docs.extend(docs)
            self.batches += 1


def test_submit_never_waits_on_a_slow_database():
    col = SlowCollection(delay=0.3)
    exporter = TraceExporter(lambda: col)
    start = time.perf_counter()
    for i in range(500):
        exporter.submit({"i": i})
    assert time.perf_counter() - start < 0.2
    assert exporter.flush(timeout=5)
    assert [d["i"] for d in col.docs] == list(range(500))  # order kept
    assert col.batches < 500  # written in batches, not one by one


def test_database_down_drops_events_without_raising():
    col = SlowCollection(fail=True)
    exporter = TraceExporter(lambda: col, retry_after=60)
    for i in range(50):
        assert exporter.submit({"i": i}) is True
    assert exporter.flush(timeout=5)
    assert exporter.written == 0 and exporter.dropped == 50


def test_unreachable_collection_counts_as_down_then_recovers():
    state = {"up": False}
    col = SlowCollection()
    exporter = TraceExporter(lambda: col if state["up"] else None, retry_after=0.05)
    exporter.submit({"i": 1})
    assert exporter.flush(timeout=5)
    assert exporter.dropped == 1
    state["up"] = True
    time.sleep(0.06)
    exporter.submit({"i": 2})
    assert exporter.flush(timeout=5)
    assert [d["i"] for d in col.docs] == [2]


def test_full_queue_drops_instead_of_blocking():
    col = SlowCollection(delay=0.5)
    exporter = TraceExporter(lambda: col, max_queue=5, batch_size=1)
    results = [exporter.submit({"i": i}) for i in range(50)]
    assert results.count(False) > 0
    assert exporter.dropped >= results.count(False)


def test_tracer_stamps_run_identity_and_ordered_seq():
    col = SlowCollection()
    tracer = RunTracer("C-1", 3, TraceExporter(lambda: col))
    tracer.emit({"event_type": "pipeline_start"})
    tracer.emit({"event_type": "pipeline_end"})
    tracer._exporter.flush()
    assert [d["seq"] for d in col.docs] == [1, 2]
    assert {(d["case_id"], d["version"], d["trace_id"], d["run_kind"]) for d in col.docs} == {
        ("C-1", 3, tracer.trace_id, "audit")}


def test_steps_only_record_inside_a_scope_and_are_bson_safe():
    col = SlowCollection()
    tracer = RunTracer("C-1", 1, TraceExporter(lambda: col))
    xai_trace.step("rule_check", "passed", rule_id="CHK-001")  # no scope: ignored
    with xai_trace.scope(tracer, "compliance"):
        xai_trace.step("rule_check", "failed", rule_id="CHK-001", values={"assets": 1.0},
                       odd=object())
    tracer._exporter.flush()
    assert len(col.docs) == 1
    s = col.docs[0]
    assert (s["event_type"], s["agent"], s["kind"], s["status"]) == (
        "step", "compliance", "rule_check", "failed")
    assert s["facts"]["values"] == {"assets": 1.0}
    assert isinstance(s["facts"]["odd"], str)


def test_disabled_tracer_is_a_no_op():
    tracer = RunTracer("C-1", 1, None)
    tracer.emit({"event_type": "x"})
    with xai_trace.scope(tracer, "compliance"):
        xai_trace.step("rule_check", "passed")
    assert xai_trace.traced_kg("kg", tracer, "compliance") == "kg"


def _audit_events(kg):
    store = MongoStore(uri="mongodb://fake", db_name="xai", client=mongomock.MongoClient())
    case = orchestrator.intake.normalize_case({"case_id": "X", "docs": [
        doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20})]})
    orchestrator.run_case(case, kg, store=store)
    assert store.trace_exporter().flush(timeout=5)
    return list(store.traces_collection().find({}, sort=[("seq", 1)]))


def test_audit_reports_agent_nodes_only(kg):
    events = _audit_events(kg)
    starts = [e["agent"] for e in events if e["event_type"] == "chain_start"]
    assert sorted(starts) == ["anomaly", "compliance", "data_quality",
                              "evidence_validation", "reasoning"]
    ends = [e for e in events if e["event_type"] == "chain_end"]
    assert len(ends) == 5 and all(e["agent"] for e in ends)
    assert events[0]["event_type"] == "pipeline_start"
    assert events[-1]["event_type"] == "pipeline_end"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


# --- granular steps ---------------------------------------------------------------

def _mongo_store():
    return MongoStore(uri="mongodb://fake", db_name="xai", client=mongomock.MongoClient())


def _events(store):
    assert store.trace_exporter().flush(timeout=5)
    return list(store.traces_collection().find({}, {"_id": 0}, sort=[("seq", 1)]))


def test_audit_steps_explain_what_each_agent_did(kg):
    from tests.test_orchestrator import DOCS
    store = _mongo_store()
    orchestrator.run_case(orchestrator.intake.normalize_case({"case_id": "S", "docs": DOCS}),
                          kg, store=store)
    steps = [e for e in _events(store) if e["event_type"] == "step"]
    by = {(s["agent"], s["kind"]) for s in steps}
    assert {("data_quality", "evidence_read"), ("compliance", "kg_fetch"),
            ("compliance", "rule_check"), ("compliance", "policy_check"),
            ("anomaly", "rule_check"), ("reasoning", "standard_check"),
            ("reasoning", "evidence_link"), ("evidence_validation", "citation_check")} <= by
    reads = [s["facts"]["doc_id"] for s in steps if s["kind"] == "evidence_read"]
    assert reads == [d["doc_id"] for d in DOCS]
    chk1 = next(s for s in steps if s["kind"] == "rule_check" and s["facts"]["rule_id"] == "CHK-001")
    assert chk1["status"] == "failed"
    assert chk1["facts"]["sides"] == {"left": "assets", "op": "==", "right": "liabilities + capital",
                                      "left_value": 100.0, "right_value": 50.0}
    policy = next(s for s in steps if s["kind"] == "policy_check")
    assert (policy["status"], policy["facts"]["amount"], policy["facts"]["limit"]) == (
        "failed", 150000.0, 100000.0)


def test_copilot_turn_streams_on_its_chat_session(kg):
    from app.schemas.copilot import CopilotQuery
    from app.services import copilot
    store = _mongo_store()
    docs = [doc("INV", "invoice", {"amount": 5})]
    copilot.answer(CopilotQuery(text="audit these documents", case_id="NEW-1",
                                session_id="GEN-20261020-AB12", docs=docs), kg, store)
    events = _events(store)
    turn = [e for e in events if e["run_kind"] == "copilot"]
    audit = [e for e in events if e["run_kind"] == "audit"]
    assert [e["event_type"] for e in turn if e["event_type"] != "step"] == [
        "copilot_start", "copilot_nlu", "copilot_end"]
    assert {e["case_id"] for e in turn} == {"GEN-20261020-AB12"}
    assert any(e["kind"] == "entities" for e in turn if e["event_type"] == "step")
    # the audit it started is its own run of case NEW-1, also shown on the chat's stream
    assert {(e["case_id"], e.get("stream_id")) for e in audit} == {("NEW-1", "GEN-20261020-AB12")}
    assert any(e.get("kind") == "rule_check" or e.get("kind") == "evidence_read" for e in audit)
    assert all(e["agent"] != "copilot" for e in audit if e["event_type"] == "step")
