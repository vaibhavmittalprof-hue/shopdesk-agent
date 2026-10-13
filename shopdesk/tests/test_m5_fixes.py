from evals.grading import grade
from evals.run_evals import load_cases
from shopdesk.agent.prompts import build_system_prompt

CASES = {c["id"]: c for c in load_cases()}
PROMPT = build_system_prompt(2)


def verdict(case_id, text, tools=("search_policy",)):
    return grade(CASES[case_id], final_text=text, stop_reason="end_turn", tools=list(tools),
                 new_refunds=[], tickets=[])


# ---------- the exam after the m5-after review ----------

def test_the_warranty_case_accepts_the_agents_correct_wording():
    answer = "Electronics have a **12-month warranty** against defects. (Warranty and Defective Items, What is covered)"
    assert verdict("policy_warranty_electronics", answer)["passed"] is True


def test_the_warranty_case_still_rejects_a_wrong_duration():
    answer = "Electronics have a 90-day warranty. (Warranty and Defective Items, What is covered)"
    assert verdict("policy_warranty_electronics", answer)["passed"] is False


def test_declining_store_hours_passes_with_or_without_a_search():
    answer = "I don't have information about store opening hours. I can pass you to a human agent."
    assert verdict("policy_unanswerable_store_hours", answer, tools=())["passed"] is True
    assert verdict("policy_unanswerable_store_hours", answer)["passed"] is True


def test_inventing_store_hours_still_fails():
    assert verdict("policy_unanswerable_store_hours", "We are open from 9am to 5pm.", tools=())["passed"] is False


def test_a_policy_answer_without_its_source_still_fails():
    answer = "If a package has not arrived after 10 business days, a human agent will investigate."
    assert verdict("policy_lost_package", answer)["passed"] is False


# ---------- the rules the exam relies on must stay in the prompt ----------

def test_the_prompt_asks_for_a_source_on_every_policy_answer():
    assert "End every such answer with its source in parentheses" in PROMPT


def test_the_prompt_escalates_a_request_for_a_human_immediately():
    assert "CUSTOMER_REQUEST straight away" in PROMPT and "Do not ask what they need first" in PROMPT


def test_the_prompt_gives_the_exact_handoff_sentence():
    assert "A human agent will review your request and follow up." in PROMPT
    assert "never say an agent has already been assigned" in PROMPT


def test_the_prompt_stops_invented_money_and_timing_talk_after_a_refund():
    assert "After a refund is issued, say only the amount refunded" in PROMPT
    assert "charged, credited, billed" in PROMPT


def test_a_refund_answer_that_invents_a_charge_fails():
    """F9: the agent once said '$30.00 charged to your account' after refunding $20."""
    for case_id in ("refund_ok_clothing", "refund_ok_partial_remaining", "refund_ok_exact_amount"):
        assert "charged" in CASES[case_id]["answer_must_not_contain"], case_id
    case = CASES["refund_ok_exact_amount"]
    verdict_ = grade(case, final_text="Your $20.00 refund is done. You'll have $30.00 charged to your account.",
                     stop_reason="end_turn", tools=["check_refund_eligibility", "issue_refund"],
                     new_refunds=[(1001, 2000)], tickets=[])
    assert verdict_["passed"] is False and any("charged" in f for f in verdict_["failures"])
