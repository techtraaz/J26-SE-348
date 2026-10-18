from app.schemas.findings import EvidenceClaim, Finding
from app.services import intake
from app.services.agents import (
    anomaly,
    compliance,
    data_quality,
    evidence_validation,
    reasoning,
)
from app.services.kg_client import FallbackKGClient, KGUnavailable, LiveKGClient
from tests.conftest import doc


def case(*docs):
    return intake.normalize_case({"case_id": "C", "docs": list(docs)})


def ids(findings):
    return sorted(f.rule_id for f in findings)


# --- Data Quality ------------------------------------------------------------

def test_dq_rejects_missing_required_and_unsupported():
    c = case(doc("BS", "balance_sheet", {"assets": 10}), doc("X", "selfie", {"a": 1}),
             doc("I", "invoice", {"amount": 5}, confidences={"amount": 0.3}))
    f, rejected, stop, _ = data_quality.run(c)
    assert rejected == ["BS", "X"] and stop is False
    assert ids(f) == ["CHK-006", "CHK-006", "REV-001", "REV-002"]
    low = next(x for x in f if x.rule_id == "REV-001")
    assert low.review_status == "needs_more_evidence" and low.confidence == 0.3


def test_dq_flags_unreadable_conflicting_and_intake_issues():
    c = case(doc("I", "invoice", {"amount": "12,34"}, parent_doc_id="GONE",
                 confidences={"amount": 1.7}),
             doc("R", "receipt", {"amount": ["100", "700"]}), doc("E", "receipt", {}))
    f, *_ = data_quality.run(c)
    assert ids(f) == ["REV-003", "REV-003", "REV-004", "REV-004", "REV-004"]


def test_dq_stops_when_nothing_is_checkable_and_says_why():
    f, _, stop, _ = data_quality.run(case(doc("X", "unknown", {"a": 1})))
    assert stop and f and f[0].rule_id == "REV-002"
    f, _, stop, _ = data_quality.run(case())
    assert stop and f[0].rule_id == "CHK-006" and f[0].severity == "high"


# --- Compliance -----------------------------------------------------------------

def test_compliance_resolves_c2_aliases_and_claims_actual_field(kg):
    c = case(doc("BS", "balance_sheet", {"total_assets": 100, "liabilities": 30, "equity": 20},
                 confidences={"total_assets": 0.8, "equity": 0.6}))
    f, trace = compliance.run(c, kg)
    chk = next(x for x in f if x.rule_id == "CHK-001")
    assert chk.category == "ledger" and chk.severity == "high"
    assert {c.field for c in chk.claims} == {"total_assets", "liabilities", "equity"}
    assert chk.confidence == 0.6  # min of the source fields
    assert any(t.decision_type == "skip" for t in trace)  # CHK-007 etc. not applicable


def test_policy_limit_carries_confidence_and_claim(kg):
    f, _ = compliance.run(case(doc("I", "invoice", {"amount": 150000}, confidences={"amount": 0.4})), kg)
    pol = next(x for x in f if x.rule_id == "POL-07")
    assert pol.confidence == 0.4 and pol.claims[0].claimed_value == 150000.0


def test_kg_outage_in_live_mode_is_visible_not_clean():
    def down(path, params):
        raise KGUnavailable("refused")
    kg = FallbackKGClient(mode="live", live=LiveKGClient("http://c2", transport=down))
    f, _ = compliance.run(case(doc("I", "invoice", {"amount": 5})), kg)
    assert ids(f) == ["REV-007"] and f[0].severity == "medium"


# --- Anomaly ------------------------------------------------------------------------

def test_year_change_uses_prior_year(kg):
    c = case(doc("B25", "balance_sheet", {"assets": 100}, year=2025),
             doc("B26", "balance_sheet", {"assets": 200}))
    f, _ = anomaly.run(c, kg)
    yoy = next(x for x in f if x.rule_id == "CHK-004")
    assert yoy.evidence_ids == ["B26", "B25"] and len(yoy.claims) == 2


def test_ambiguous_prior_year_is_skipped_visibly(kg):
    c = case(doc("A25", "balance_sheet", {"assets": 1}, year=2025),
             doc("B25", "balance_sheet", {"assets": 2}, year=2025),
             doc("B26", "balance_sheet", {"assets": 200}))
    f, trace = anomaly.run(c, kg)
    assert "CHK-004" not in ids(f)
    assert any("several balance_sheet" in t.detail for t in trace)


def test_child_parent_and_fraud_pattern(kg):
    c = case(doc("INV", "invoice", {"amount": 100, "cash_out": 100, "purchase_basis": "credit",
                                    "asset_in": 0}),
             doc("RC", "receipt", {"amount": 90}, parent_doc_id="INV"))
    f, _ = anomaly.run(c, kg)
    assert ids(f) == ["CHK-003", "CHK-005"]
    assert next(x for x in f if x.rule_id == "CHK-005").category == "possible_fraud"


# --- Reasoning ----------------------------------------------------------------------

def test_reasoning_adds_kg_basis_links_and_review(kg, monkeypatch):
    c = case(doc("BS", "balance_sheet", {"assets": 1, "liabilities": 1, "capital": 1}))
    f = Finding(finding_id="BS-CHK-001", rule_id="CHK-001", category="ledger", severity="high",
                message="m", evidence_ids=["BS"], confidence=0.2)
    monkeypatch.setattr(kg, "get_evidence_chain", lambda d: [d, "GL-9"])
    out, _ = reasoning.run(c, [f], kg)
    chk = out[0]
    assert "CF:4.4" in chk.policy_ids and chk.review_status == "needs_more_evidence"
    assert any(s.startswith("basis:") for s in chk.reasoning_chain)
    assert any("kg links BS -> GL-9" in s for s in chk.reasoning_chain)
    assert ids(out) == ["CHK-001", "REV-005"]
    assert f.reasoning_chain == []  # input not mutated


# --- Evidence Validation --------------------------------------------------------------

def _f(fid, claims=(), evidence=("I",)):
    return Finding(finding_id=fid, rule_id="CHK-001", category="ledger", severity="high",
                   message="m", evidence_ids=list(evidence), claims=list(claims))


def test_validation_statuses_and_failures_are_kept():
    c = case(doc("I", "invoice", {"amount": 100, "purchase_basis": "Credit"}))
    good = _f("ok", [EvidenceClaim(evidence_id="I", field="amount", claimed_value=100.0),
                     EvidenceClaim(evidence_id="I", field="purchase_basis", claimed_value="credit")])
    wrong = _f("wrong", [EvidenceClaim(evidence_id="I", field="amount", claimed_value=999.0)])
    ghost = _f("ghost", evidence=("NOPE",))
    plain = _f("plain")
    kept, rejected, bad, _ = evidence_validation.run(c, [good, wrong, ghost, plain])
    status = {f.finding_id: f.evidence_validation for f in kept}
    assert status == {"ok": "passed", "wrong": "failed", "ghost": "failed", "plain": "existence_only"}
    assert len(kept) == 4  # a real issue never vanishes
    assert {r.finding.finding_id for r in rejected} == {"wrong", "ghost"}
    assert all(f.citation_unverified for f in kept if f.evidence_validation == "failed")
    assert bad == ["I", "NOPE"]
