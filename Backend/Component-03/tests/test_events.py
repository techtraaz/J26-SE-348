"""Step 6: C03 publishes C4's contract events, best-effort, never blocking."""
import json

from app.schemas.case import AuditCase, AuditDocument
from app.services import orchestrator
from app.services.events import EventPublisher
from app.services.kg_client import KGClient


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.messages: list[tuple[str, str]] = []
        self.fail = fail

    def publish(self, channel: str, message: str) -> int:
        if self.fail:
            raise RuntimeError("redis down")
        self.messages.append((channel, message))
        return 1


def _events(client: FakeRedis) -> list[dict]:
    return [json.loads(m) for _, m in client.messages]


def _tv_case(case_id: str) -> AuditCase:
    return AuditCase(case_id=case_id, docs=[
        AuditDocument(doc_id="BS26", case_id=case_id, doc_type="balance_sheet",
                      period_year=2026,
                      fields={"assets": 40000, "liabilities": 30000, "capital": 20000}),
        AuditDocument(doc_id="INV1", case_id=case_id, doc_type="invoice",
                      period_year=2026, parent_doc_id="BS26",
                      fields={"amount": 250000}),
    ])


def test_full_run_emits_contract_event_sequence():
    client = FakeRedis()
    pub = EventPublisher(client=client, channel="nomos:trace_events")
    res = orchestrator.run_case(_tv_case("CASE-EVT"), KGClient(), pub)

    evs = _events(client)
    assert [c for c, _ in client.messages] == ["nomos:trace_events"] * len(evs)
    assert evs[0]["event"] == "pipeline_start"
    assert evs[0]["case_id"] == "CASE-EVT"
    assert evs[0]["doc_count"] == 2
    assert evs[-1]["event"] == "pipeline_end"
    assert evs[-1]["total_findings"] == len(res.findings)

    agents = [e["agent"] for e in evs if e["event"] == "agent_end"]
    assert agents[0] == "data_quality"
    assert set(agents[1:3]) == {"compliance", "anomaly"}
    assert agents[-2:] == ["reasoning", "evidence_validation"]


def test_agent_end_trace_has_contract_fields():
    client = FakeRedis()
    orchestrator.run_case(_tv_case("CASE-EVT2"), KGClient(),
                          EventPublisher(client=client))
    for e in _events(client):
        assert e["event"] == "agent_end" or "ts" in e
        if e["event"] == "agent_end":
            assert e["case_id"] == "CASE-EVT2"
            assert {"agent_name", "decision_type", "detail"} <= set(e["trace"])


def test_publish_failure_does_not_break_audit():
    pub = EventPublisher(client=FakeRedis(fail=True))
    res = orchestrator.run_case(_tv_case("CASE-EVTERR"), KGClient(), pub)
    assert res.status == "pending_auditor_review"
    assert res.findings


def test_early_stop_still_emits_events():
    client = FakeRedis()
    res = orchestrator.run_case(AuditCase(case_id="CASE-EVTBAD", docs=[]),
                                KGClient(), EventPublisher(client=client))
    assert res.status == "not_auditable"
    evs = _events(client)
    assert evs[0]["event"] == "pipeline_start"
    assert any(e["event"] == "agent_end" and e["agent"] == "data_quality"
               for e in evs)
    assert evs[-1]["event"] == "pipeline_end"


def test_stream_emits_start_and_end():
    client = FakeRedis()
    list(orchestrator.stream_case(_tv_case("CASE-EVTSTR"), KGClient(),
                                  EventPublisher(client=client)))
    evs = _events(client)
    assert evs[0]["event"] == "pipeline_start"
    assert evs[-1]["event"] == "pipeline_end"


def test_version_bumps_once_per_run():
    orchestrator.VERSION_STORE.pop("CASE-VER", None)
    r1 = orchestrator.run_case(_tv_case("CASE-VER"), KGClient(),
                               EventPublisher(client=FakeRedis()))
    r2 = orchestrator.run_case(_tv_case("CASE-VER"), KGClient(),
                               EventPublisher(client=FakeRedis()))
    assert (r1.version, r2.version) == (1, 2)
