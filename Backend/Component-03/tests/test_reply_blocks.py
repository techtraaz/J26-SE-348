"""Copilot replies as typed blocks, and the one Markdown renderer for them."""
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.copilot import (
    CopilotQuery,
    FindingsBlock,
    ListBlock,
    ListItem,
    QuestionBlock,
    TableBlock,
    TextBlock,
    VerdictBlock,
)
from app.services import copilot, intake, orchestrator
from app.services.copilot.render import to_markdown
from tests.conftest import doc

SFP = doc("SFP-42", "balance_sheet", {"total_assets": 164673550, "total_liabilities": 67832630,
                                      "total_equity": 84778770}, name="02_SFP_Wk42.pdf")
INV = doc("INV-04", "invoice", {"amount": 636256, "approvals": 1}, name="04_Tax_Invoice.pdf")


def _audit(kg, store, case_id="BLK-1"):
    orchestrator.run_case(intake.normalize_case({"case_id": case_id, "docs": [SFP, INV]}), kg,
                          store=store, narrate=False)


def ask(kg, store, text, case_id=None):
    return copilot.answer(CopilotQuery(text=text, case_id=case_id), kg, store)


# --- the renderer -----------------------------------------------------------------------

def test_every_block_type_renders_as_markdown():
    text = to_markdown([
        VerdictBlock(case_id="C-1", version=2, verdict="issues_found", score=75, summary="1 rule finding."),
        ListBlock(title="Rules", items=[ListItem(label="CHK-001", text="checks `a == b`", tone="high",
                                                 details=["cites CF:4.4"])], more=2),
        TableBlock(columns=["Case", "Note"], rows=[["C-1", "a | b"]]),
        FindingsBlock(title="High", finding_ids=["f1"], lines=["CHK-001 · high: off by 5"]),
        QuestionBlock(text="Which one?", choices=["Explain CHK-001"]),
        TextBlock(text="Done."),
    ])
    assert text.startswith("**Issues found** · score 75/100 · case C-1, version 2\n1 rule finding.")
    assert "- **CHK-001** (high): checks `a == b`\n  - cites CF:4.4\n- …and 2 more" in text
    assert "| Case | Note |\n| --- | --- |\n| C-1 | a \\| b |" in text  # a pipe in a cell is escaped
    assert "**High**\n- CHK-001 · high: off by 5" in text
    assert "Which one?\n- Explain CHK-001" in text and text.endswith("Done.")


def test_plain_text_replies_become_one_text_block(kg, store):
    r = ask(kg, store, "thanks")
    assert [b.type for b in r.blocks] == ["text"] and r.blocks[0].text == r.reply


# --- rule questions -----------------------------------------------------------------------

def test_rules_for_a_document_type_are_one_item_each(kg, store):
    r = ask(kg, store, "List the rules for invoices in general")
    rules = r.blocks[0]
    assert rules.type == "list" and rules.title == "4 rule(s) apply to an invoice"
    assert [i.label for i in rules.items] == ["CHK-003 Child amount matches parent",
                                              "CHK-005 Cash out without asset in",
                                              "CHK-006 Required fields present", "POL-07"]
    assert rules.items[3].text == ("Purchases above Rs. 100,000 need dual approval "
                                   "(limit Rs 100,000.00, needs 2 approvals)")
    assert r.reply.count("\n- **") == 4  # one bullet per rule


def test_rule_explanation_has_its_facts_and_no_repeated_id(kg, store):
    r = ask(kg, store, "Explain POL-07")
    head, facts = r.blocks
    assert head.text.startswith("**POL-07**") and "POL-07: POL-07" not in r.reply
    labels = {i.label: i.text for i in facts.items}
    assert labels["Limit"] == "Rs 100,000.00" and labels["Approvals needed"] == "2"
    assert labels["Applies to"] == "invoice"
    chk = {i.label: i.text for i in ask(kg, store, "explain CHK-001").blocks[1].items}
    assert chk["Checks"] == "`assets == liabilities + capital`" and chk["Based on"] == "CF:4.4"


def test_a_document_without_rules_says_so(kg, store):
    r = ask(kg, store, "which rules apply to a purchase order?")
    assert "no rules for a purchase order yet" in r.reply


# --- case questions -----------------------------------------------------------------------

def test_naming_the_document_type_picks_the_finding(kg, store):
    _audit(kg, store)
    r = ask(kg, store, "why did the balance sheet fail?", "BLK-1")
    assert r.intent == "explain_finding"
    assert r.blocks[0].text.startswith("**CHK-001** on 02_SFP_Wk42.pdf · high")
    why = {i.label: i.text for i in r.blocks[1].items}
    assert why["Basis"].startswith("CHK-001 Accounting equation")
    assert why["Value checked"].startswith("02_SFP_Wk42.pdf · total_")  # names, not ids
    assert why["Evidence"] == "02_SFP_Wk42.pdf"


def test_an_unclear_finding_question_asks_with_choices(kg, store):
    _audit(kg, store)
    r = ask(kg, store, "why was this flagged?", "BLK-1")
    q = r.blocks[0]
    assert q.type == "question" and q.text == "Case BLK-1 has 2 findings. Which one should I explain?"
    assert q.choices == ["Why was CHK-001 raised on 02_SFP_Wk42.pdf?", "Why was POL-07 raised on 04_Tax_Invoice.pdf?"]
    picked = ask(kg, store, q.choices[1], "BLK-1")  # sending a choice answers it
    assert picked.blocks[0].text.startswith("**POL-07** on 04_Tax_Invoice.pdf")


def test_case_status_leads_with_the_verdict(kg, store):
    _audit(kg, store)
    r = ask(kg, store, "summarise this case", "BLK-1")
    assert [b.type for b in r.blocks] == ["verdict", "list", "findings"]
    assert (r.blocks[0].verdict, r.blocks[0].score) == ("issues_found", 50)
    assert len(r.blocks[2].finding_ids) == 2


def test_history_and_case_search_are_tables(kg, store):
    _audit(kg, store)
    _audit(kg, store)
    hist = ask(kg, store, "show the audit history", "BLK-1").blocks[1]
    assert hist.type == "table" and [r[0] for r in hist.rows] == ["v1", "v2"]
    assert hist.columns[2] == "Verdict" and hist.rows[0][2] == "issues found"
    cases = ask(kg, store, "which cases have high severity findings?")
    assert cases.blocks[1].type == "table" and cases.blocks[1].rows[0][0] == "BLK-1"


def test_saved_chat_keeps_the_blocks():
    client = TestClient(app)
    client.post("/copilot/query", json={"text": "Explain POL-07", "session_id": "S-BLK"})
    msgs = client.get("/chat/S-BLK/messages").json()["messages"]
    reply = next(m for m in msgs if m["role"] == "copilot")
    assert [b["type"] for b in reply["blocks"]] == ["text", "list"]
    assert reply["text"].startswith("**POL-07**")
