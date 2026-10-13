import json

from shopdesk.agent import loop
from evals.run_evals import load_cases, run_case
from tests.test_agent_loop import text_block, tool_block
from tests.test_agent_reliability import fake_model, reply

CASES = {c["id"]: c for c in load_cases()}


def policy_script(final_text, query="how long do refunds take"):
    return [reply([tool_block("t1", "search_policy", {"query": query})], "tool_use"),
            reply([text_block(final_text)], "end_turn")]


def run(case_id, tmp_path):
    return run_case(CASES[case_id], 1, tmp_path, tmp_path / "traces")


def test_a_cited_answer_taken_from_the_policy_passes(monkeypatch, tmp_path):
    fake_model(monkeypatch, policy_script("Refunds take 5 to 7 business days (Refund Policy, Refund timing)."))
    result = run("policy_refund_timing", tmp_path)
    assert result["passed"] is True, result["failures"]


def test_an_answer_without_a_citation_fails(monkeypatch, tmp_path):
    fake_model(monkeypatch, policy_script("Refunds take 5 to 7 business days."))
    result = run("policy_refund_timing", tmp_path)
    assert result["passed"] is False and "Refund Policy" in " ".join(result["failures"])


def test_answering_from_memory_without_searching_fails(monkeypatch, tmp_path):
    fake_model(monkeypatch, [reply([text_block("Usually about 3-5 business days.")], "end_turn")])
    result = run("policy_refund_timing", tmp_path)
    assert result["passed"] is False
    assert any("never called search_policy" in f for f in result["failures"])


def test_the_model_really_receives_the_policy_text(monkeypatch, conn):
    fake_model(monkeypatch, policy_script("Refunds take 5 to 7 business days (Refund Policy, Refund timing)."))
    result = loop.run_agent("How long does a refund take?", customer_id=2, conn=conn)
    tool_result = json.loads(result.messages[2]["content"][0]["content"])
    assert tool_result["ok"] is True
    assert "5 to 7 business days" in tool_result["data"]["passages"][0]["text"]


def test_declining_when_the_policy_has_no_answer_passes(monkeypatch, tmp_path):
    fake_model(monkeypatch, policy_script("I don't have information about gift wrapping. I can pass you to a human agent.",
                                          query="gift wrapping"))
    result = run("policy_unanswerable_gift_wrap", tmp_path)
    assert result["passed"] is True, result["failures"]


def test_inventing_an_answer_when_the_policy_has_none_fails(monkeypatch, tmp_path):
    fake_model(monkeypatch, policy_script("Yes, we offer gift wrapping for $3 per item.", query="gift wrapping"))
    result = run("policy_unanswerable_gift_wrap", tmp_path)
    assert result["passed"] is False


def test_inventing_refund_timing_after_a_refund_now_fails(monkeypatch, tmp_path):
    key = "refund-1001-evalrun1"
    fake_model(monkeypatch, [
        reply([tool_block("t1", "check_refund_eligibility", {"order_id": 1001})], "tool_use"),
        reply([text_block("You are eligible. Shall I go ahead?")], "end_turn"),
        reply([tool_block("t2", "issue_refund", {"order_id": 1001, "amount_cents": 5000,
                                                 "reason": "wrong size", "idempotency_key": key})], "tool_use"),
        reply([text_block("Done! The money should be back in 3-5 business days.")], "end_turn"),
    ])
    result = run("refund_ok_clothing", tmp_path)
    assert result["new_refunds"] == [(1001, 5000)]            # the refund itself was right...
    assert result["passed"] is False                           # ...but the invented timing is caught
    assert any("3-5" in f for f in result["failures"])


def test_promising_an_outcome_after_escalating_now_fails(monkeypatch, tmp_path):
    fake_model(monkeypatch, [
        reply([tool_block("t1", "check_refund_eligibility", {"order_id": 1010})], "tool_use"),
        reply([text_block("Eligible for $2,500.00. Shall I go ahead?")], "end_turn"),
        reply([tool_block("t2", "escalate_to_human", {"reason": "REFUND_NEEDS_APPROVAL",
                                                      "summary": "Customer wants a full refund of order 1010."})], "tool_use"),
        reply([text_block("A human agent will process the full refund right away.")], "end_turn"),
    ])
    result = run("approval_full_laptop_escalates", tmp_path)
    assert result["passed"] is False and any("right away" in f for f in result["failures"])
