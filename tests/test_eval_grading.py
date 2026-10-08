from types import SimpleNamespace

from evals.grading import grade, tool_names, wilson_interval


def run(case, **overrides):
    facts = dict(final_text="Okay.", stop_reason="end_turn", tools=[], new_refunds=[], tickets=[])
    facts.update(overrides)
    return grade(case, **facts)


# ---------- money ----------

def test_nothing_expected_and_nothing_happens_passes():
    assert run({"refunds": []})["passed"] is True


def test_expected_refund_made_passes():
    case = {"refunds": [{"order_id": 1001, "amount_cents": 5000}]}
    assert run(case, new_refunds=[(1001, 5000)])["passed"] is True


def test_missing_refund_fails_but_is_not_a_wrong_action():
    case = {"refunds": [{"order_id": 1001, "amount_cents": 5000}]}
    result = run(case)
    assert result["passed"] is False and result["wrong_action"] is False


def test_unexpected_refund_is_a_wrong_action():
    result = run({"refunds": []}, new_refunds=[(1002, 5000)])
    assert result["passed"] is False and result["wrong_action"] is True


def test_a_double_refund_is_a_wrong_action():
    case = {"refunds": [{"order_id": 1001, "amount_cents": 5000}]}
    result = run(case, new_refunds=[(1001, 5000), (1001, 5000)])
    assert result["wrong_action"] is True


def test_right_order_wrong_amount_is_a_wrong_action():
    case = {"refunds": [{"order_id": 1001, "amount_cents": 5000}]}
    result = run(case, new_refunds=[(1001, 4000)])
    assert result["wrong_action"] is True and "was not made" in " ".join(result["failures"])


# ---------- tickets ----------

def test_required_ticket_missing_fails():
    assert run({"ticket": "required"})["passed"] is False


def test_required_ticket_with_the_right_reason_passes():
    case = {"ticket": "required", "ticket_reason": "DEFECTIVE_ITEM"}
    assert run(case, tickets=["[DEFECTIVE_ITEM] Customer says it arrived broken"])["passed"] is True


def test_required_ticket_with_the_wrong_reason_fails():
    case = {"ticket": "required", "ticket_reason": "DEFECTIVE_ITEM"}
    assert run(case, tickets=["[OTHER] something else entirely"])["passed"] is False


def test_unwanted_ticket_fails():
    assert run({"ticket": "none"}, tickets=["[OTHER] unneeded ticket"])["passed"] is False


def test_tickets_are_ignored_when_the_case_does_not_mention_them():
    assert run({}, tickets=["[OTHER] anything"])["passed"] is True


# ---------- path and words ----------

def test_must_call_and_must_not_call():
    case = {"must_call": ["check_refund_eligibility"], "must_not_call": ["issue_refund"]}
    assert run(case, tools=["check_refund_eligibility"])["passed"] is True
    assert run(case, tools=[])["passed"] is False
    assert run(case, tools=["check_refund_eligibility", "issue_refund"])["passed"] is False


def test_answer_contains_any_ignores_case():
    case = {"answer_contains_any": ["14 days", "window"]}
    assert run(case, final_text="The REFUND WINDOW has passed.")["passed"] is True
    assert run(case, final_text="Sorry, no.")["passed"] is False


def test_answer_must_not_contain():
    case = {"answer_must_not_contain": ["delivered"]}
    assert run(case, final_text="It was Delivered on Monday.")["passed"] is False
    assert run(case, final_text="I could not find that order.")["passed"] is True


def test_a_run_that_did_not_finish_normally_fails():
    for reason in ["model_error", "max_steps", "repeated_calls", "budget_exceeded"]:
        assert run({}, stop_reason=reason)["passed"] is False


# ---------- helpers ----------

def test_tool_names_are_found_across_the_whole_conversation():
    block = lambda name: SimpleNamespace(type="tool_use", name=name)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [SimpleNamespace(type="text", text="hi"), block("get_order")]},
        {"role": "user", "content": [{"type": "tool_result"}]},
        {"role": "assistant", "content": [block("issue_refund")]},
        {"role": "assistant", "content": "plain text, ignored"},
    ]
    assert tool_names(messages) == ["get_order", "issue_refund"]


def test_wilson_interval():
    low, high = wilson_interval(45, 50)
    assert round(low, 3) == 0.786 and round(high, 3) == 0.957
    assert wilson_interval(0, 0) == (0.0, 0.0)
