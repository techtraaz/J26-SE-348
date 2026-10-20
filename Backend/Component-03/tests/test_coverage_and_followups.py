"""Coverage-aware verdicts, open questions, and the follow-up intents built on them."""
import pytest

from app.schemas.copilot import CopilotQuery
from app.services import audit_reply, copilot, intake, orchestrator
from tests.conftest import doc

SFP = doc("SFP-42", "balance_sheet", {"total_assets": 164673550, "total_liabilities": 67832630,
                                      "total_equity": 84778770}, name="02_SFP_Wk42.pdf")
INV = doc("INV-04", "invoice", {"amount": 636256, "approvals": 1}, name="04_Tax_Invoice.pdf")
INCOME = doc("IS-26", "income_statement", {"revenue": 1000000, "gross_profit": 450000}, name="income.pdf")


def audit(kg, store, docs, case_id="COV-1"):
    return orchestrator.run_case(intake.normalize_case({"case_id": case_id, "docs": docs}), kg,
                                 store=store, narrate=False)


def ask(kg, store, text, case_id=None):
    return copilot.answer(CopilotQuery(text=text, case_id=case_id), kg, store)


# --- coverage and open questions in the saved result ---------------------------------------

def test_a_skipped_rule_lists_every_missing_input(kg, store):
    r = audit(kg, store, [INV])
    chk5 = next(a for a in r.rules_applied if a.rule_id == "CHK-005")
    assert chk5.outcome == "skipped" and chk5.missing_inputs == ["cash_out", "purchase_basis", "asset_in"]


def test_coverage_counts_what_could_and_could_not_run(kg, store):
    cov = audit(kg, store, [SFP, INV]).coverage
    assert (cov.rules_run, cov.failed, cov.not_run, cov.complete) == (2, 2, 5, False)


def test_open_questions_ask_for_the_missing_values(kg, store):
    q = next(q for q in audit(kg, store, [INCOME]).open_questions if q.rule_id == "CHK-008")
    assert (q.doc_name, q.missing) == ("income.pdf", ["cost_of_sales"])
    assert q.question == ("CHK-008 Gross profit could not run on income.pdf: it needs the cost of sales. "
                          "What is the cost of sales on this document?")


def test_nothing_checked_is_never_clean(kg, store):
    r = audit(kg, store, [INCOME])
    assert r.findings == [] and (r.verdict, r.score) == ("needs_review", None)


def test_audit_reply_says_the_check_was_limited_and_asks(kg, store):
    r = audit(kg, store, [INCOME])
    text = audit_reply.describe_saved(r, store)
    assert "**Limited check:** 1 of 1 rules could not run" in text
    assert "**To complete the audit, tell me**" in text and "cost of sales on income.pdf is" in text


# --- giving a missing value in the chat (confirmed before a new version) --------------------

def test_a_missing_value_is_confirmed_then_rerun(kg, store):
    audit(kg, store, [INCOME], "COV-2")
    asked = ask(kg, store, "the cost of sales is 550,000", "COV-2")
    assert asked.intent == "provide_value" and asked.blocks[0].type == "question"
    assert store.latest("COV-2")["version"] == 1  # nothing saved yet
    yes, no = asked.blocks[0].choices
    assert yes == "Yes, set cost of sales on income.pdf to 550,000.00" and no == "No, keep the current version"
    done = ask(kg, store, yes, "COV-2")
    saved = store.latest("COV-2")
    assert saved["version"] == 2 and saved["verdict"] == "clean"
    d = saved["case"]["docs"][0]
    assert d["fields"]["cost_of_sales"] == 550000.0 and d["methods"]["cost_of_sales"] == "c3:entered-by-auditor-in-chat"
    assert next(a for a in saved["rules_applied"] if a["rule_id"] == "CHK-008")["outcome"] == "passed"
    assert done.blocks[0].text.startswith("Set the cost of sales on income.pdf to 550,000.00")


def test_declining_changes_nothing(kg, store):
    audit(kg, store, [INCOME], "COV-3")
    r = ask(kg, store, "No, keep the current version", "COV-3")
    assert r.intent == "cancel" and store.latest("COV-3")["version"] == 1


def test_a_value_for_no_open_question_says_so(kg, store):
    audit(kg, store, [SFP], "COV-4")
    r = ask(kg, store, "the cost of sales is 10", "COV-4")
    assert r.intent == "provide_value" and "couldn't tell which missing value" in r.reply


# --- follow-up intents ------------------------------------------------------------------

@pytest.mark.parametrize("text,intent", [
    ("can you give a verdict for this case?", "case_verdict"),
    ("how confident are you?", "case_verdict"),
    ("which rules passed?", "rule_results"),
    ("why wasn't the gross profit checked?", "rule_results"),
    ("is this invoice ok?", "document_status"),
    ("what should I do next?", "next_steps"),
    ("is the company committing fraud?", "fraud_check"),
    ("check case COV-5", "case_status"),
])
def test_follow_up_questions_route(kg, store, text, intent):
    audit(kg, store, [SFP, INV, INCOME], "COV-5")
    assert ask(kg, store, text, "COV-5").intent == intent


def test_verdict_explains_its_limits(kg, store):
    audit(kg, store, [SFP, INV], "COV-6")
    r = ask(kg, store, "can you give a verdict for this case?", "COV-6")
    assert [b.type for b in r.blocks][:3] == ["verdict", "list", "text"]
    limits = {i.label: i.text for i in r.blocks[1].items}
    assert limits["Rules checked"] == "2 of 7 (0 passed, 2 failed)"
    assert "This verdict is **limited**" in r.reply


def test_why_a_rule_did_not_run(kg, store):
    audit(kg, store, [INCOME], "COV-7")
    r = ask(kg, store, "why wasn't the gross profit checked?", "COV-7")
    assert r.blocks[0].text == "**CHK-008 Gross profit** did not run on income.pdf: it needs the cost of sales."


def test_rule_results_with_none_matching_gives_the_counts(kg, store):
    audit(kg, store, [SFP, INV], "COV-8")
    r = ask(kg, store, "which rules passed?", "COV-8")
    assert r.reply == "No rule passed in case COV-8 (version 1). Of its rules: 5 not checked, 2 failed."


def test_document_status_answers_for_the_document_asked_about(kg, store):
    audit(kg, store, [SFP, INV], "COV-9")
    r = ask(kg, store, "is this invoice ok?", "COV-9")
    assert r.blocks[0].text == "**04_Tax_Invoice.pdf** (invoice): 1 rule finding(s)."
    by_name = ask(kg, store, "is 02_SFP_Wk42 ok?", "COV-9")  # a file name, without the extension
    assert by_name.blocks[0].text.startswith("**02_SFP_Wk42.pdf** (balance sheet)")


def test_fraud_question_never_says_no_fraud_when_nothing_ran(kg, store):
    audit(kg, store, [INV], "COV-10")
    r = ask(kg, store, "is the company committing fraud?", "COV-10")
    assert r.blocks[0].text.startswith("**I can't conclude.**")
    assert "cash out, purchase basis and asset in" in r.reply


def test_next_steps_lists_recommendations_and_open_questions(kg, store):
    audit(kg, store, [SFP, INV], "COV-11")
    r = ask(kg, store, "what should I do next?", "COV-11")
    assert r.blocks[0].title == "What to do next" and r.blocks[0].items[0].label == "CHK-001"
    assert any(b.type == "list" and b.title == "To complete the audit, tell me" for b in r.blocks)


def test_concept_uses_the_rules_when_the_kg_has_no_definition(kg, store):
    r = ask(kg, store, "what is dual approval?")
    assert r.intent == "concept" and "POL-07" in r.reply
    off = ask(kg, store, "what's the weather today?")
    assert "I answer questions about this audit" in off.reply  # nothing made up from a search hit


def test_unsure_requests_ask_with_choices(kg, store):
    audit(kg, store, [SFP, INV], "COV-12")
    r = ask(kg, store, "the latest one", "COV-12")  # matches a little, decides nothing
    assert r.blocks[0].type == "question" and r.blocks[0].choices


# --- materiality: asked for only when it would change something ------------------------------

def test_materiality_is_offered_only_after_an_amount_check_fails(kg, store):
    failed = audit_reply.describe_saved(audit(kg, store, [SFP], "MAT-1"), store)
    assert "is off by **12,062,150.00**" in failed and "ignore differences below 50,000" in failed
    policy_only = audit_reply.describe_saved(audit(kg, store, [INV], "MAT-2"), store)
    assert "materiality" not in policy_only.lower()  # a policy limit has no amount difference


def test_materiality_is_confirmed_then_rerun_and_not_offered_again(kg, store):
    audit(kg, store, [SFP], "MAT-3")
    r = ask(kg, store, "ignore differences below 20,000,000", "MAT-3")
    assert r.intent == "set_materiality" and store.latest("MAT-3")["version"] == 1  # nothing saved yet
    choice = r.blocks[0].choices[0]
    assert choice == "Yes, mark differences below 20,000,000.00 as minor"
    done = ask(kg, store, choice, "MAT-3")
    rec = store.latest("MAT-3")
    assert rec["version"] == 2 and rec["case"]["materiality"] == 20000000
    chk = next(f for f in rec["findings"] if f["rule_id"] == "CHK-001")
    assert chk["severity"] == "low"  # kept, not dropped
    assert "ignore differences below" not in done.reply  # already set: no second offer


@pytest.mark.parametrize("text", ["set the materiality to 5,000,000", "materiality is 1,000,000",
                                  "don't flag differences under 100,000"])
def test_materiality_wordings_route(kg, store, text):
    audit(kg, store, [SFP], "MAT-4")
    assert ask(kg, store, text, "MAT-4").intent == "set_materiality"


def test_materiality_question_without_amount_asks_for_one(kg, store):
    audit(kg, store, [SFP], "MAT-5")
    r = ask(kg, store, "set the materiality", "MAT-5")
    assert r.intent == "set_materiality" and "Below which amount" in r.reply
    assert ask(kg, store, "what is materiality?", "MAT-5").intent == "concept"


@pytest.mark.parametrize("text", ["what is materiality?", "what does materiality mean?"])
def test_materiality_is_explained_in_plain_words_first(kg, store, text):
    r = ask(kg, store, text)
    assert r.intent == "concept"
    assert r.blocks[0].type == "text" and r.blocks[0].text.startswith("**In plain words:** some differences")
    assert "ignore differences below 50,000" in r.blocks[0].text  # and how to use it here


def test_the_materiality_offer_uses_plain_words_and_explains_on_click(kg, store):
    offer = next(b for b in audit_reply.describe_saved_blocks(audit(kg, store, [SFP], "MAT-6"), store)
                 if b.type == "question")
    assert offer.text.startswith("**CHK-001**") and "too small to matter" in offer.text
    assert ask(kg, store, offer.choices[0], "MAT-6").blocks[0].text.startswith("**In plain words:**")
