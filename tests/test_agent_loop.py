import json
from types import SimpleNamespace

from shopdesk.agent import loop


# ---- helpers that build fake model replies ----

def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(tool_id, name, tool_input):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def reply(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class FakeModel:
    """Plays back a scripted list of replies, one per call, and records the calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, messages, tools=None, system=None, **kwargs):
        self.calls += 1
        return self.replies.pop(0)


def use_fake(monkeypatch, replies):
    fake = FakeModel(replies)
    monkeypatch.setattr(loop, "chat", fake)   # the loop now talks to the fake, not Anthropic
    return fake


# ---- tests ----

def test_direct_answer_without_tools(monkeypatch, conn):
    use_fake(monkeypatch, [reply([text_block("Hello! How can I help?")], "end_turn")])
    result = loop.run_agent("Hi", conn=conn)
    assert result.text == "Hello! How can I help?"
    assert result.steps == 1
    assert result.stop_reason == "end_turn"


def test_tool_call_then_final_answer(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([tool_block("toolu_1", "get_order", {"order_id": 1001})], "tool_use"),
        reply([text_block("Order 1001 was delivered.")], "end_turn"),
    ])
    result = loop.run_agent("Where is order 1001?", conn=conn)

    assert result.text == "Order 1001 was delivered."
    assert result.steps == 2
    roles = [m["role"] for m in result.messages]
    assert roles == ["user", "assistant", "user", "assistant"]

    tool_result = result.messages[2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"     # matched to the request
    assert tool_result["is_error"] is False
    payload = json.loads(tool_result["content"])
    assert payload["ok"] is True
    assert payload["data"]["order_id"] == 1001


def test_tool_error_is_sent_back_and_marked_as_error(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([tool_block("toolu_1", "get_order", {"order_id": 9999})], "tool_use"),
        reply([text_block("I couldn't find that order.")], "end_turn"),
    ])
    result = loop.run_agent("Where is order 9999?", conn=conn)

    tool_result = result.messages[2]["content"][0]
    assert tool_result["is_error"] is True
    assert json.loads(tool_result["content"])["error"]["code"] == "ORDER_NOT_FOUND"
    assert result.stop_reason == "end_turn"      # the loop carried on and finished


def test_unknown_tool_does_not_crash_the_loop(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([tool_block("toolu_1", "delete_everything", {})], "tool_use"),
        reply([text_block("Sorry, I can't do that.")], "end_turn"),
    ])
    result = loop.run_agent("Delete everything", conn=conn)

    tool_result = result.messages[2]["content"][0]
    assert tool_result["is_error"] is True
    assert json.loads(tool_result["content"])["error"]["code"] == "UNKNOWN_TOOL"


def test_two_tool_calls_in_one_reply_get_one_result_message(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([
            tool_block("toolu_a", "get_order", {"order_id": 1001}),
            tool_block("toolu_b", "get_order", {"order_id": 1002}),
        ], "tool_use"),
        reply([text_block("Both delivered.")], "end_turn"),
    ])
    result = loop.run_agent("Check 1001 and 1002", conn=conn)

    results_message = result.messages[2]
    assert results_message["role"] == "user"
    ids = [block["tool_use_id"] for block in results_message["content"]]
    assert ids == ["toolu_a", "toolu_b"]


def test_step_cap_stops_a_runaway_loop(monkeypatch, conn):
    def always_wants_a_tool(messages, tools=None, system=None, **kwargs):
        always_wants_a_tool.calls += 1
        return reply([tool_block("toolu_x", "get_order", {"order_id": 1001})], "tool_use")
    always_wants_a_tool.calls = 0
    monkeypatch.setattr(loop, "chat", always_wants_a_tool)

    result = loop.run_agent("Loop forever", max_steps=3, conn=conn)

    assert result.stop_reason == "max_steps"
    assert result.steps == 3
    assert always_wants_a_tool.calls == 3      # it really did stop


def test_history_is_carried_into_the_next_turn(monkeypatch, conn):
    use_fake(monkeypatch, [
        reply([text_block("First answer.")], "end_turn"),
        reply([text_block("Second answer.")], "end_turn"),
    ])
    first = loop.run_agent("First question", conn=conn)
    second = loop.run_agent("Second question", history=first.messages, conn=conn)

    roles = [m["role"] for m in second.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert second.messages[0]["content"] == "First question"