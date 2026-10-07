import json
import time
from dataclasses import dataclass, field

from shopdesk.agent.prompts import build_system_prompt
from shopdesk.llm import MODEL, chat
from shopdesk.pricing import estimate_cost
from shopdesk.tools.common import err
from shopdesk.tools.registry import TOOL_SPECS, run_tool
from shopdesk.tracing import Tracer, block_to_dict

MAX_STEPS = 8               # at most this many model calls per customer message
MAX_IDENTICAL_CALLS = 3     # the 3rd identical tool call in one run is blocked
MAX_COST_USD = 0.10         # stop a run that has cost more than this


@dataclass
class AgentResult:
    text: str                  # what to show the customer
    messages: list = field(default_factory=list)   # the whole conversation so far
    steps: int = 0             # how many times we called the model
    stop_reason: str = ""      # why we stopped: "end_turn", "max_steps", "model_error", ...
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    run_id: str = ""
    trace_path: str = ""       # where the trace file is ("" if tracing was off)


def _text_of(response) -> str:
    """Join all the text blocks of a model reply into one string."""
    return "".join(block.text for block in response.content if block.type == "text")


def run_agent(user_message, history=None, customer_id=None, max_steps=MAX_STEPS,
              conn=None, verbose=False, tracer=None, max_cost_usd=MAX_COST_USD) -> AgentResult:
    tracer = tracer or Tracer(enabled=False)         # no tracer given = no trace file
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    system = build_system_prompt(customer_id)

    run_started = time.time()
    total_in = total_out = 0
    total_cost = 0.0
    call_counts = {}          # (tool name, arguments) -> how many times we have seen it
    blocked_calls = 0

    tracer.event("run_start", model=MODEL, customer_id=customer_id, max_steps=max_steps,
                 max_cost_usd=max_cost_usd, tools=[spec["name"] for spec in TOOL_SPECS],
                 system_prompt=system, user_message=user_message)

    def finish(text, stop_reason, steps):
        tracer.event("run_end", stop_reason=stop_reason, steps=steps,
                     input_tokens=total_in, output_tokens=total_out, cost_usd=round(total_cost, 6),
                     duration_ms=round((time.time() - run_started) * 1000), final_text=text)
        return AgentResult(text, messages, steps, stop_reason, total_in, total_out, total_cost,
                           tracer.run_id, str(tracer.path) if tracer.enabled else "")

    for step in range(1, max_steps + 1):
        # 0. Too expensive already? Stop BEFORE spending more. (Checked here, not mid-step,
        #    so the conversation is always left in a valid state.)
        if step > 1 and total_cost > max_cost_usd:
            tracer.event("budget_exceeded", step=step, cost_usd=round(total_cost, 6))
            return finish("Sorry, I couldn't finish that request. A human agent will follow up.",
                          "budget_exceeded", step - 1)

        # 1. Ask the model what to do next (temporary API errors are retried inside chat())
        retries = []

        def on_retry(info, step=step):
            retries.append(info)
            tracer.event("retry", step=step, **info)
            if verbose:
                print(f"  [retry] {info['error']}, waiting {info['wait_s']}s (attempt {info['attempt']})")

        call_started = time.time()
        try:
            response = chat(messages, tools=TOOL_SPECS, system=system, on_retry=on_retry)
        except Exception as exc:        # retries used up, or an error that retrying cannot fix
            tracer.event("model_error", step=step, error=type(exc).__name__, message=str(exc)[:300])
            if verbose:
                print(f"\n[step {step}] model call FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            return finish("Sorry, I'm having trouble right now. A human agent will follow up.",
                          "model_error", step)
        latency_ms = round((time.time() - call_started) * 1000)

        # 2. Count tokens and cost
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        cost = estimate_cost(getattr(response, "model", None) or MODEL, in_tok, out_tok)
        total_in += in_tok
        total_out += out_tok
        total_cost += cost or 0.0

        messages.append({"role": "assistant", "content": response.content})
        tracer.event("model_call", step=step, latency_ms=latency_ms, attempts=len(retries) + 1,
                     stop_reason=response.stop_reason, input_tokens=in_tok, output_tokens=out_tok,
                     cost_usd=cost, content=[block_to_dict(b) for b in response.content])

        if verbose:
            cost_text = f"${cost:.4f}" if cost is not None else "unknown"
            print(f"\n[step {step}] model stop_reason = {response.stop_reason}  "
                  f"({in_tok} in / {out_tok} out tokens, {cost_text}, {latency_ms} ms)")
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"  model says: {block.text.strip()}")

        # 3. Not asking for a tool? Then it is finished.
        if response.stop_reason != "tool_use":
            return finish(_text_of(response), response.stop_reason, step)

        # 4. Run EVERY tool the model asked for (unless it is stuck repeating itself)
        tool_results = []
        stop_run = False
        for block in response.content:
            if block.type != "tool_use":
                continue

            key = (block.name, json.dumps(block.input, sort_keys=True, default=str))
            call_counts[key] = call_counts.get(key, 0) + 1
            tool_started = time.time()

            if call_counts[key] >= MAX_IDENTICAL_CALLS:
                blocked_calls += 1
                result = err(
                    "REPEATED_CALL",
                    f"You have already made this exact call {call_counts[key] - 1} times.",
                    "Do not make this call again. Use the results you already have, or call "
                    "escalate_to_human if you cannot solve the problem.",
                )
                tracer.event("loop_warning", step=step, tool=block.name, args=block.input,
                             count=call_counts[key], blocked_calls=blocked_calls)
                if blocked_calls >= 2:      # told once, and it still repeats: give up
                    stop_run = True
            else:
                result = run_tool(block.name, block.input, conn=conn)

            tracer.event("tool_call", step=step, tool_use_id=block.id, name=block.name,
                         args=block.input, result=result, ok=result["ok"],
                         blocked=result.get("error", {}).get("code") == "REPEATED_CALL",
                         latency_ms=round((time.time() - tool_started) * 1000))
            if verbose:
                print(f"  tool call: {block.name}({json.dumps(block.input)})")
                print(f"  tool result: {json.dumps(result)[:200]}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,           # must match the request's id
                "content": json.dumps(result),
                "is_error": not result["ok"],
            })

        # 5. Send all the results back in ONE user message (every request gets an answer,
        #    even blocked ones, so the conversation stays valid)
        messages.append({"role": "user", "content": tool_results})

        if stop_run:
            return finish("Sorry, I got stuck on that request. A human agent will follow up.",
                          "repeated_calls", step)

    # Ran out of steps: stop instead of looping forever
    return finish("Sorry, I couldn't finish that request. A human agent will follow up.",
                  "max_steps", max_steps)