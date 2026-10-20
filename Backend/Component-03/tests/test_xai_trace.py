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
