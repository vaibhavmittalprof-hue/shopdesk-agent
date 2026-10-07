import json

from shopdesk.agent import loop
from tests.test_agent_loop import reply, text_block, tool_block, use_fake


def tool_json(result_message, index=0):
    return json.loads(result_message["content"][index]["content"])


def test_agent_refunds_through_the_loop_and_a_retry_is_safe(monkeypatch, conn):
    key = "refund-1001-abc12345"
    use_fake(monkeypatch, [
        reply([tool_block("t1", "check_refund_eligibility", {"order_id": 1001})], "tool_use"),
        reply([tool_block("t2", "issue_refund", {"order_id": 1001, "amount_cents": 5000,
                                                 "reason": "Wrong size", "idempotency_key": key})], "tool_use"),
        # the model "retries" with the SAME key, as if the first answer got lost
        reply([tool_block("t3", "issue_refund", {"order_id": 1001, "amount_cents": 5000,
                                                 "reason": "Wrong size", "idempotency_key": key})], "tool_use"),
        reply([text_block("Your $50.00 refund has been issued.")], "end_turn"),
    ])
    result = loop.run_agent("Please refund order 1001", conn=conn)

    assert result.stop_reason == "end_turn"
    assert tool_json(result.messages[2])["data"]["eligible"] is True
    assert tool_json(result.messages[4])["data"]["already_processed"] is False
    assert tool_json(result.messages[6])["data"]["already_processed"] is True
    rows = conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = 1001").fetchone()[0]
    assert rows == 1                                       # refunded once, not twice


def test_over_limit_refund_is_refused_and_agent_escalates(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([tool_block("t1", "issue_refund", {"order_id": 1010, "amount_cents": 250000,
                                                 "reason": "Not needed", "idempotency_key": "refund-1010-big00001"})], "tool_use"),
        reply([tool_block("t2", "escalate_to_human", {"reason": "REFUND_NEEDS_APPROVAL",
                                                      "summary": "Customer wants $2,500 refunded on order 1010."})], "tool_use"),
        reply([text_block("A human agent will follow up.")], "end_turn"),
    ])
    result = loop.run_agent("Refund my laptop, order 1010", conn=conn)

    refused = result.messages[2]["content"][0]
    assert refused["is_error"] is True
    assert json.loads(refused["content"])["error"]["code"] == "APPROVAL_REQUIRED"
    assert conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = 1010").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1