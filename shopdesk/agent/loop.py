import json
from dataclasses import dataclass, field

from shopdesk.agent.prompts import build_system_prompt
from shopdesk.llm import chat
from shopdesk.tools.registry import TOOL_SPECS, run_tool

MAX_STEPS = 8   # at most this many model calls per customer message


@dataclass
class AgentResult:
    text: str                  # what to show the customer
    messages: list = field(default_factory=list)   # the whole conversation so far
    steps: int = 0             # how many times we called the model
    stop_reason: str = ""      # why we stopped: "end_turn", "max_steps", ...


def _text_of(response) -> str:
    """Join all the text blocks of a model reply into one string."""
    return "".join(block.text for block in response.content if block.type == "text")


def run_agent(user_message, history=None, customer_id=None,
              max_steps=MAX_STEPS, conn=None, verbose=False) -> AgentResult:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    system = build_system_prompt(customer_id)

    for step in range(1, max_steps + 1):
        # 1. Ask the model what to do next
        response = chat(messages, tools=TOOL_SPECS, system=system)
        messages.append({"role": "assistant", "content": response.content})

        if verbose:
            print(f"\n[step {step}] model stop_reason = {response.stop_reason}")
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"  model says: {block.text.strip()}")

        # 2. Not asking for a tool? Then it is finished.
        if response.stop_reason != "tool_use":
            return AgentResult(_text_of(response), messages, step, response.stop_reason)

        # 3. Run EVERY tool the model asked for, collect the results
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = run_tool(block.name, block.input, conn=conn)
            if verbose:
                print(f"  tool call: {block.name}({json.dumps(block.input)})")
                print(f"  tool result: {json.dumps(result)[:200]}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,           # must match the request's id
                "content": json.dumps(result),
                "is_error": not result["ok"],
            })

        # 4. Send all the results back in ONE user message, then loop again
        messages.append({"role": "user", "content": tool_results})

    # Ran out of steps: stop instead of looping forever
    return AgentResult(
        "Sorry, I couldn't finish that request. A human agent will follow up.",
        messages, max_steps, "max_steps",
    )