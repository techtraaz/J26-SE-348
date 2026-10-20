"""Snapshots of the live KG: taken from a fake C2, then used as mock data."""
import json

import pytest

from app import config
from app.services import intake, orchestrator
from app.services.kg_client import (
    FallbackKGClient,
    LiveKGClient,
    MockKGClient,
    default_kg,
)
from scripts import snapshot_kg
from scripts.check_kg_contract import run_checks
from tests.conftest import doc
from tests.test_kg_live_contract import MOCK, fake_c2


@pytest.fixture
def snapshot(tmp_path):
    out = tmp_path / "kg_snapshot.json"
    kg = LiveKGClient("http://c2", transport=fake_c2())
    path, problems, contract = snapshot_kg.take_snapshot("http://c2", out, kg)
    assert problems == [] and contract == []
    return path


def _case():
    return intake.normalize_case({"case_id": "SNAP-1", "docs": [
        doc("BS", "balance_sheet", {"total_assets": 100, "total_liabilities": 30, "total_equity": 20}),
        doc("INV", "invoice", {"amount": 150000, "approvals": 1})]})


def test_snapshot_holds_every_rule_and_what_it_cites(snapshot):
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert data["_snapshot"]["kg_url"] == "http://c2" and data["_snapshot"]["format"] == 1
    assert data["check_rules"] == MOCK["check_rules"] and data["rules"] == MOCK["rules"]
    assert set(data["explanations"]) == set(MOCK["explanations"])
    assert "LKAS 2:9" in data["sections"] and "CF:4.4" in data["sections"]  # found from citations
    assert "LKAS 2" in data["standards"] and data["search"]


def test_snapshot_matching_the_mock_shows_no_rule_differences(snapshot):
    lines = snapshot_kg.compare(MOCK, json.loads(snapshot.read_text(encoding="utf-8")))
    assert [x for x in lines if not x.split(":")[0] in ("standards", "sections", "definitions",
                                                        "line_items", "search")] == []


def test_compare_reports_a_changed_rule():
    live = json.loads(json.dumps(MOCK))
    live["check_rules"]["balance_sheet"][0]["severity"] = "medium"
    live["rules"]["invoice"][0]["required_approvals"] = 2
    lines = snapshot_kg.compare(MOCK, live)
    assert "CHK-001 severity: mock 'high', live 'medium'" in lines
    assert "POL-07 required_approvals: mock None, live 2" in lines


def test_audit_on_a_snapshot_matches_the_mock_and_says_where_rules_came_from(snapshot, store):
    on_mock = orchestrator.run_case(_case(), FallbackKGClient(mode="mock", mock=MockKGClient()), store=store)
    on_snap = orchestrator.run_case(_case(), FallbackKGClient(mode="mock", mock=MockKGClient(snapshot)),
                                    store=store)
    shape = lambda r: sorted((f.rule_id, f.severity, f.message) for f in r.findings)
    assert shape(on_snap) == shape(on_mock)
    note = next(t.detail for t in on_snap.trace if t.agent_name == "kg")
    assert "Mock data: KG snapshot taken" in note and "http://c2" in note
    assert "committed mock data" in next(t.detail for t in on_mock.trace if t.agent_name == "kg")


def test_kg_mock_file_points_the_app_at_a_snapshot(snapshot, monkeypatch):
    monkeypatch.setattr(config, "KG_MOCK_FILE", str(snapshot))
    assert "KG snapshot taken" in default_kg().mock_note
    monkeypatch.setattr(config, "KG_MOCK_FILE", "")
    assert default_kg().mock_note == "committed mock data"


def test_c2_down_saves_nothing(tmp_path):
    from app.services.kg_client import KGUnavailable

    def down(path, params):
        raise KGUnavailable("refused")
    with pytest.raises(KGUnavailable):
        snapshot_kg.take_snapshot("http://c2", tmp_path / "s.json", LiveKGClient("http://c2", transport=down))
    assert not (tmp_path / "s.json").exists()


LOCAL = config.COMPONENT_ROOT / "data" / "kg_snapshot.json"


@pytest.mark.skipif(not LOCAL.exists(), reason="no local KG snapshot (scripts/snapshot_kg.py)")
def test_local_snapshot_still_fits_c3():
    """Runs only on a machine with a snapshot: C3 can still read the real KG data."""
    report = run_checks(MockKGClient(LOCAL), None)
    assert report.problems == [], report.problems
