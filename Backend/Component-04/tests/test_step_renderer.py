"""Tests for the deterministic wording of C03's granular XAI steps."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services import step_renderer as sr

FIXTURE = Path(__file__).parent / "fixtures" / "c03_trace_events.json"
BANNED = re.compile(r"\b(sample|fake|mock|test)\b", re.IGNORECASE)


def _texts(row: dict) -> list[str]:
    out = [row["verb"], row["target"], row["detail"]]
    for f in row["facts"]:
        out += [f["label"], f["value"]]
    return out


def test_failed_rule_shows_both_sides_of_the_comparison():
    row = sr.render_step("rule_check", "failed", {
        "rule_id": "CHK-001", "rule_name": "Accounting equation",
        "expression": "assets == liabilities + capital", "doc_id": "BS-2024",
        "values": {"assets": 152_000_000.0, "liabilities": 100_000_000.0, "capital": 52_600_000.0},
        "sides": {"left": "assets", "op": "==", "right": "liabilities + capital",
                  "left_value": 152_000_000.0, "right_value": 152_600_000.0},
        "severity": "high"})
    assert (row["verb"], row["target"], row["tone"]) == ("Failed", "CHK-001 on BS-2024", "danger")
    assert row["detail"] == ("Accounting equation: Assets 152,000,000 ≠ "
                             "Liabilities + Capital 152,600,000")
    facts = {f["label"]: f["value"] for f in row["facts"]}
    assert facts["Difference"] == "600,000"
    assert facts["Expression"] == "assets == liabilities + capital"
    assert row["check"] is True


def test_passed_rule_is_a_summarisable_check():
    row = sr.render_step("rule_check", "passed", {
        "rule_id": "CHK-002", "rule_name": "Debits equal credits", "doc_id": "TB",
        "sides": {"left": "debits", "op": "==", "right": "credits",
                  "left_value": 10.0, "right_value": 10.0}})
    assert row["verb"] == "Checked" and row["tone"] == "success" and row["check"]
    assert row["detail"] == "Debits equal credits: Debits 10 = Credits 10"


def test_skipped_rule_says_why():
    row = sr.render_step("rule_check", "skipped", {
        "rule_id": "CHK-007", "rule_name": "Current ratio", "doc_id": "BS",
        "reason": "missing current_liabilities"})
    assert row["verb"] == "Skipped" and row["tone"] == "muted"
    assert "missing current_liabilities" in row["detail"]


def test_policy_limit_breach():
    row = sr.render_step("policy_check", "failed", {
        "rule_id": "POL-07", "text": "Purchases above Rs. 100,000 need dual approval.",
        "doc_id": "INV", "field": "amount", "amount": 150000.0, "limit": 100000.0})
    assert row["verb"] == "Failed"
    assert row["detail"].startswith("Amount 150,000 > limit 100,000")
    assert {"label": "Above limit by", "value": "50,000"} in row["facts"]


def test_policy_outcomes_follow_the_approval_stamp():
    base = {"rule_id": "POL-07", "doc_id": "INV", "field": "amount", "amount": 150000.0,
            "limit": 100000.0}
    approved = sr.render_step("policy_check", "passed",
                              {**base, "approvals_required": 2, "approvals_signed": 2.0})
    assert (approved["verb"], approved["tone"]) == ("Checked", "success")
    assert approved["detail"] == "Amount 150,000 > limit 100,000 · 2 of 2 required approvals signed"
    short = sr.render_step("policy_check", "failed",
                           {**base, "approvals_required": 2, "approvals_signed": 1.0})
    assert short["detail"].endswith("only 1 of 2 required approvals signed")
    unread = sr.render_step("policy_check", "review", base)
    assert (unread["verb"], unread["tone"]) == ("Needs review", "warning")


def test_kg_source_never_shows_internal_names():
    row = sr.render_step("kg_fetch", "ok", {
        "method": "get_check_rules", "arg": "balance_sheet", "source": "mock",
        "result": {"count": 3, "ids": ["CHK-001", "CHK-002", "CHK-007"]}})
    assert (row["verb"], row["target"]) == ("Fetched", "3 check rules")
    assert row["detail"] == "for balance sheet from the Knowledge Graph"
    assert not any(BANNED.search(t) for t in _texts(row))
    assert sr.kg_source_label("live") == "Knowledge Graph (C02)"


def test_evidence_read_names_its_source():
    row = sr.render_step("evidence_read", "ok", {
        "doc_id": "INV-001", "doc_type": "invoice", "field_count": 2,
        "fields": {"amount": 150000}, "source": "c1", "verified_version": 2,
        "confirmed_by": "auditor1"})
    assert (row["verb"], row["target"]) == ("Read", "INV-001")
    assert row["detail"] == "invoice · 2 fields · C1 verified record v2 by auditor1"


def test_unknown_or_malformed_steps_never_raise():
    assert sr.render_step("something_new", "ok", {"reason": "x"})["verb"] == "Something new"
    row = sr.render_step("rule_check", "failed", {"sides": {"op": "=="}})  # missing keys
    assert row["tone"] == "danger"


def test_every_real_c03_step_renders_professionally():
    events = json.loads(FIXTURE.read_text(encoding="utf-8"))
    steps = [e for e in events if e["event_type"] == "step"]
    assert len(steps) > 40
    for e in steps:
        row = sr.render_step(e["kind"], e["status"], e["facts"])
        assert row["verb"], e
        for text in _texts(row):
            assert not BANNED.search(text), (text, e)
