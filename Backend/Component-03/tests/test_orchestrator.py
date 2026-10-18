import json
import threading

import pytest

from app.schemas.trace_events import parse_trace_event
from app.services import intake, orchestrator
from app.services.events import EventPublisher
from app.services.store import MemoryStore, StoreError
from tests.conftest import FakeRedis, doc

DOCS = [doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20}),
        doc("INV", "invoice", {"amount": 150000}),
        doc("RC", "receipt", {"amount": 140000}, parent_doc_id="INV")]


def case(docs=DOCS, case_id="C"):
    return intake.normalize_case({"case_id": case_id, "docs": docs})


def test_full_run_order_and_result(kg, store):
    r = orchestrator.run_case(case(), kg, store=store)
    assert r.status == "pending_auditor_review" and r.version == 1 and r.kg_source == "mock"
    assert {"CHK-001", "CHK-003", "POL-07"} <= {f.rule_id for f in r.findings}
    agents = [t.agent_name for t in sorted((t for t in r.trace if t.seq), key=lambda t: t.seq)]
    first = {a: agents.index(a) for a in dict.fromkeys(agents)}
    assert first["data_quality"] == 0
    assert max(first["compliance"], first["anomaly"]) < first["reasoning"] < first["evidence_validation"]
    assert all(f.reasoning_chain and f.evidence_validation != "unverified" for f in r.findings)


def test_rejected_docs_are_logged_and_not_checked(kg, store):
    r = orchestrator.run_case(case([doc("BS", "balance_sheet", {"assets": 1}),
                                    doc("INV", "invoice", {"amount": 150000})]), kg, store=store)
    assert r.rejected_records == ["BS"]
    assert not any(f.rule_id == "CHK-001" for f in r.findings)
    assert any(f.rule_id == "CHK-006" for f in r.findings)


@pytest.mark.parametrize("docs", [[], [doc("X", "unknown", {"a": 1})],
                                  [doc("BS", "balance_sheet", {"assets": 1})]])
def test_not_auditable_never_looks_clean(kg, store, docs):
    r = orchestrator.run_case(case(docs), kg, store=store)
    assert r.status == "not_auditable" and r.findings
    assert not any(t.agent_name == "compliance" for t in r.trace)


def test_versions_are_kept_and_supersedes_set(kg, store):
    first = orchestrator.run_case(case(), kg, store=store)
    second = orchestrator.run_case(case(), kg, store=store)
    assert (first.version, second.version) == (1, 2)
    assert all(f.supersedes == 1 for f in second.findings)
    assert [v["version"] for v in store.versions("C")] == [1, 2]
    assert store.get("C", 1)["findings"][0]["supersedes"] is None  # v1 untouched


def test_append_evidence_builds_on_latest_version(kg, store):
    orchestrator.run_case(case(DOCS[:2]), kg, store=store)
    r = orchestrator.append_evidence("C", [DOCS[2]], kg, store=store)
    assert r.version == 2 and any(f.rule_id == "CHK-003" for f in r.findings)
    assert len(store.latest("C")["case"]["docs"]) == 3
    with pytest.raises(LookupError):
        orchestrator.append_evidence("NEW", [DOCS[0]], kg, store=store)
    with pytest.raises(intake.IntakeError):  # same doc_id again
        orchestrator.append_evidence("C", [DOCS[0]], kg, store=store)


def test_concurrent_runs_get_distinct_versions(kg):
    store = MemoryStore()
    out = []
    threads = [threading.Thread(target=lambda: out.append(
        orchestrator.run_case(case(), kg, store=store).version)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == [1, 2, 3, 4, 5, 6]


def test_store_failure_is_loud(kg):
    class Broken(MemoryStore):
        def save(self, case, result):
            raise StoreError("down")
    with pytest.raises(StoreError):
        orchestrator.run_case(case(), kg, store=Broken())


def test_events_match_c4_contract_and_end_after_save(kg, store):
    redis = FakeRedis()
    seen_saved = []

    class Spy(FakeRedis):
        def publish(self, channel, text):
            if json.loads(text)["event"] == "pipeline_end":
                seen_saved.append(store.get("C", 1) is not None)
            redis.publish(channel, text)
    r = orchestrator.run_case(case(), kg, publisher=EventPublisher(client=Spy()), store=store)
    events = [json.loads(t) for _, t in redis.sent]
    assert events[0]["event"] == "pipeline_start"
    assert events[-1]["event"] == "pipeline_end"
    assert sum(e["event"] == "agent_end" for e in events) == 5
    for e in events:
        parse_trace_event(e)
    assert seen_saved == [True] and r.events_published
    assert store.get("C", 1)["events_published"] is True


def test_event_failure_never_breaks_audit(kg, store):
    r = orchestrator.run_case(case(), kg, publisher=EventPublisher(client=FakeRedis(fail=True)),
                              store=store)
    assert r.status == "pending_auditor_review" and not r.events_published
    assert any(t.agent_name == "events" for t in r.trace)
    assert any(t["agent_name"] == "events" for t in store.get("C", 1)["trace"])


def test_stream_yields_updates_then_one_saved_result(kg, store):
    chunks = list(orchestrator.stream_case(case(), kg, store=store))
    assert [c["event"] for c in chunks][-1] == "result"
    assert {n for c in chunks[:-1] for n in c["data"]} == {
        "data_quality", "compliance", "anomaly", "reasoning", "evidence_validation"}
    json.dumps(chunks)
    assert [v["version"] for v in store.versions("C")] == [1]
