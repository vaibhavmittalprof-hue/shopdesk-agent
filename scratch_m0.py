from datetime import datetime

from shopdesk.llm import chat


# 1. The REAL function. Plain Python. The model can't run this itself.
def get_time() -> str:
    return datetime.now().isoformat(timespec="seconds")


# 2. The tool "menu entry" the model gets to see.
get_time_tool = {
    "name": "get_time",
    "description": (
        "Returns the current local date and time as an ISO 8601 string, "
        "for example 2026-10-04T14:30:00. Use this when the user asks "
        "what time or date it is. Takes no arguments."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

# 3. Start the conversation.
messages = [{"role": "user", "content": "What time is it?"}]

# 4. First call: the model sees the question and the tool menu.
response = chat(messages, tools=[get_time_tool])

print("=== FIRST RESPONSE (raw) ===")
print(response.model_dump_json(indent=2))
print("stop_reason:", response.stop_reason)

# 5. If the model asked for a tool, run it and report back.
if response.stop_reason == "tool_use":
    # Find the block in the reply that is the tool request
    tool_block = next(b for b in response.content if b.type == "tool_use")
    print("\nTool requested:", tool_block.name)
    print("Arguments:", tool_block.input)
    print("Call id:", tool_block.id)

    # Run the real function ourselves
    result = get_time()
    print("Our function returned:", result)

    # Add the model's turn, then our result, to the conversation
    messages.append({"role": "assistant", "content": response.content})
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                }
            ],
        }
    )

    # Second call: now the model can write the final answer
    final = chat(messages, tools=[get_time_tool])

    print("\n=== FINAL RESPONSE (raw) ===")
    print(final.model_dump_json(indent=2))
    print("stop_reason:", final.stop_reason)

    final_text = next(b.text for b in final.content if b.type == "text")
    print("\nModel says:", final_text)