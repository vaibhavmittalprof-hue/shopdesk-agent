import json
from types import SimpleNamespace

from shopdesk.agent import loop
from shopdesk.tracing import Tracer
from tests.test_agent_loop import text_block, tool_block

MODEL = "claude-haiku-4-5-20251001"


def reply(blocks, stop_reason, in_tok=1000, out_tok=100):
    """A fake model reply that also reports token usage."""
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, model=MODEL,
                           usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok))


def fake_model(monkeypatch, replies):
    """Plays the replies in order; counts calls."""
    state = {"calls": 0, "replies": list(replies)}

    def fake(messages, tools=None, system=None, **kwargs):
        state["calls"] += 1
        return state["replies"].pop(0)

    monkeypatch.setattr(loop, "chat", fake)
    return state


def read_trace(tracer):
    return [json.loads(line) for line in tracer.path.read_text(encoding="utf-8").splitlines()]


def conversation_is_valid(messages):
    """Every tool_use the model made must be answered by a tool_result in the next message."""
    for i, message in enumerate(messages):
        if message["role"] != "assistant" or isinstance(message["content"], str):
            continue
        asked = {b.id for b in message["content"] if b.type == "tool_use"}
        if not asked:
            continue
        if i + 1 >= len(messages):
            return False
        answered = {b["tool_use_id"] for b in messages[i + 1]["content"]}
        if asked != answered:
            return False
    return True


# ---------- tokens, cost and the trace file ----------

def test_trace_records_the_whole_run(monkeypatch, conn, tmp_path):
    fake_model(monkeypatch, [
        reply([tool_block("t1", "get_order", {"order_id": 1001})], "tool_use"),
        reply([text_block("Order 1001 was delivered.")], "end_turn"),
    ])
    tracer = Tracer(run_id="r1", directory=tmp_path)
    result = loop.run_agent("Where is order 1001?", conn=conn, tracer=tracer)

    events = [e["event"] for e in read_trace(tracer)]
    assert events == ["run_start", "model_call", "tool_call", "model_call", "run_end"]
    assert result.run_id == "r1" and result.trace_path.endswith("r1.jsonl")

    trace = read_trace(tracer)
    assert trace[0]["user_message"] == "Where is order 1001?"
    assert "ShopDesk" in trace[0]["system_prompt"]
    tool_event = trace[2]
    assert tool_event["name"] == "get_order" and tool_event["args"] == {"order_id": 1001}
    assert tool_event["ok"] is True and tool_event["result"]["data"]["order_id"] == 1001
    assert trace[-1]["stop_reason"] == "end_turn" and trace[-1]["final_text"] == "Order 1001 was delivered."


def test_tokens_and_cost_are_added_up(monkeypatch, conn):
    fake_model(monkeypatch, [
        reply([tool_block("t1", "get_order", {"order_id": 1001})], "tool_use", in_tok=1000, out_tok=100),
        reply([text_block("Done.")], "end_turn", in_tok=1500, out_tok=50),
    ])
    result = loop.run_agent("Where is order 1001?", conn=conn)
    assert result.input_tokens == 2500 and result.output_tokens == 150
    # (2500 * $1 + 150 * $5) / 1,000,000
    assert round(result.cost_usd, 6) == 0.00325


def test_unknown_model_price_does_not_break_the_run(monkeypatch, conn):
    odd = reply([text_block("Hi.")], "end_turn")
    odd.model = "some-future-model"
    fake_model(monkeypatch, [odd])
    result = loop.run_agent("Hi", conn=conn)
    assert result.stop_reason == "end_turn" and result.cost_usd == 0.0


def test_runs_without_a_tracer_leave_no_files(monkeypatch, conn, tmp_path):
    from shopdesk import tracing
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path / "traces")
    fake_model(monkeypatch, [reply([text_block("Hi.")], "end_turn")])
    result = loop.run_agent("Hi", conn=conn)
    assert result.trace_path == ""
    assert not (tmp_path / "traces").exists()


# ---------- model failures and retries ----------

def test_a_failing_model_gives_a_polite_result_not_a_crash(monkeypatch, conn, tmp_path):
    def always_fails(messages, tools=None, system=None, **kwargs):
        raise TimeoutError("the API is down")

    monkeypatch.setattr(loop, "chat", always_fails)
    tracer = Tracer(run_id="r2", directory=tmp_path)
    result = loop.run_agent("Hello", conn=conn, tracer=tracer)

    assert result.stop_reason == "model_error"
    assert "human agent" in result.text
    failure = [e for e in read_trace(tracer) if e["event"] == "model_error"][0]
    assert failure["error"] == "TimeoutError"


def test_retries_are_recorded_in_the_trace(monkeypatch, conn, tmp_path):
    def flaky(messages, tools=None, system=None, on_retry=None, **kwargs):
        on_retry({"attempt": 1, "error": "RateLimitError", "wait_s": 1.5})   # as chat() would
        return reply([text_block("Hi there.")], "end_turn")

    monkeypatch.setattr(loop, "chat", flaky)
    tracer = Tracer(run_id="r3", directory=tmp_path)
    loop.run_agent("Hi", conn=conn, tracer=tracer)

    trace = read_trace(tracer)
    retry = [e for e in trace if e["event"] == "retry"][0]
    assert retry["error"] == "RateLimitError" and retry["wait_s"] == 1.5
    assert [e for e in trace if e["event"] == "model_call"][0]["attempts"] == 2


# ---------- loop detection ----------

def test_a_stuck_model_is_warned_once_then_stopped(monkeypatch, conn, tmp_path):
    same_call = lambda: reply([tool_block("t", "get_order", {"order_id": 1001})], "tool_use")
    state = fake_model(monkeypatch, [same_call() for _ in range(10)])
    tracer = Tracer(run_id="r4", directory=tmp_path)

    result = loop.run_agent("Loop", conn=conn, tracer=tracer)

    assert result.stop_reason == "repeated_calls"
    assert state["calls"] == 4                       # run, run, blocked (warned), blocked (stopped)
    tools = [e for e in read_trace(tracer) if e["event"] == "tool_call"]
    assert [t["blocked"] for t in tools] == [False, False, True, True]
    blocked_message = result.messages[6]["content"][0]       # the 3rd tool result
    assert json.loads(blocked_message["content"])["error"]["code"] == "REPEATED_CALL"
    assert conversation_is_valid(result.messages)


def test_a_model_that_listens_to_the_warning_can_finish(monkeypatch, conn, tmp_path):
    same_call = lambda: reply([tool_block("t", "get_order", {"order_id": 1001})], "tool_use")
    fake_model(monkeypatch, [same_call(), same_call(), same_call(),
                             reply([text_block("Order 1001 was delivered.")], "end_turn")])
    result = loop.run_agent("Where is 1001?", conn=conn, tracer=Tracer(run_id="r5", directory=tmp_path))
    assert result.stop_reason == "end_turn"
    assert conversation_is_valid(result.messages)


def test_different_arguments_are_not_repeats(monkeypatch, conn):
    calls = [reply([tool_block(f"t{i}", "get_order", {"order_id": 1001 + i})], "tool_use") for i in range(5)]
    fake_model(monkeypatch, calls + [reply([text_block("Checked five orders.")], "end_turn")])
    result = loop.run_agent("Check some orders", conn=conn, max_steps=8)
    assert result.stop_reason == "end_turn"


def test_argument_order_does_not_hide_a_repeat(monkeypatch, conn):
    args_a = {"reason": "OTHER", "summary": "A long enough summary text."}
    args_b = {"summary": "A long enough summary text.", "reason": "OTHER"}    # same, different order
    fake_model(monkeypatch, [
        reply([tool_block("a", "escalate_to_human", args_a)], "tool_use"),
        reply([tool_block("b", "escalate_to_human", args_b)], "tool_use"),
        reply([tool_block("c", "escalate_to_human", args_a)], "tool_use"),       # 3rd identical
        reply([text_block("Done.")], "end_turn"),
    ])
    result = loop.run_agent("Help", conn=conn)
    tickets = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    assert tickets == 2                              # the 3rd was blocked, not executed


# ---------- cost control ----------

def test_a_run_over_budget_is_stopped_with_a_valid_conversation(monkeypatch, conn, tmp_path):
    expensive = reply([tool_block("t1", "get_order", {"order_id": 1001})], "tool_use",
                      in_tok=1_000_000, out_tok=0)                    # $1.00 for one call
    state = fake_model(monkeypatch, [expensive, reply([text_block("never reached")], "end_turn")])
    tracer = Tracer(run_id="r6", directory=tmp_path)

    result = loop.run_agent("Costly", conn=conn, tracer=tracer, max_cost_usd=0.10)

    assert result.stop_reason == "budget_exceeded"
    assert state["calls"] == 1                       # it did not make the second, extra call
    assert result.cost_usd == 1.0
    assert conversation_is_valid(result.messages)
    assert any(e["event"] == "budget_exceeded" for e in read_trace(tracer))
