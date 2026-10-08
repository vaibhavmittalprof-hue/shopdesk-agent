import math
from collections import Counter


def tool_names(messages):
    """Names of every tool the model called, in order, across the whole conversation."""
    names = []
    for message in messages:
        if message["role"] == "assistant" and not isinstance(message["content"], str):
            names += [block.name for block in message["content"] if block.type == "tool_use"]
    return names


def wilson_interval(passed, total, z=1.96):
    """95% confidence interval for a pass rate. Few runs give a wide interval."""
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def grade(case, *, final_text, stop_reason, tools, new_refunds, tickets):
    """
    Judge ONE run of ONE case, using only facts we can check (no opinions).

    case         a dict from cases.jsonl
    final_text   the agent's last answer
    stop_reason  how the last turn ended
    tools        names of the tools the agent called (whole conversation)
    new_refunds  list of (order_id, amount_cents) that now exist because of this run
    tickets      list of ticket summaries created during this run

    Returns {"passed": bool, "wrong_action": bool, "failures": [str]}
    """
    failures = []
    wrong_action = False

    if stop_reason != "end_turn":
        failures.append(f"the run ended with '{stop_reason}' instead of finishing normally")

    # --- Money: the refunds must match EXACTLY. Anything extra is a WRONG ACTION. ---
    expected = Counter((r["order_id"], r["amount_cents"]) for r in case.get("refunds", []))
    actual = Counter(tuple(r) for r in new_refunds)
    for (order_id, cents), _ in (expected - actual).items():
        failures.append(f"expected a refund of {cents} cents on order {order_id}, but it was not made")
    for (order_id, cents), _ in (actual - expected).items():
        failures.append(f"UNEXPECTED refund of {cents} cents on order {order_id}")
        wrong_action = True

    # --- Tickets ---
    wanted = case.get("ticket")
    if wanted == "required":
        reason = case.get("ticket_reason")
        if not [t for t in tickets if reason is None or t.startswith(f"[{reason}]")]:
            failures.append("expected a ticket" + (f" with reason {reason}" if reason else "") + ", but none was created")
    elif wanted == "none" and tickets:
        failures.append(f"expected no ticket, but {len(tickets)} were created")

    # --- Which tools it used (the path it took) ---
    for name in case.get("must_call", []):
        if name not in tools:
            failures.append(f"never called {name}")
    for name in case.get("must_not_call", []):
        if name in tools:
            failures.append(f"called {name}, which it should not have")

    # --- What it said ---
    text = final_text.lower()
    options = case.get("answer_contains_any")
    if options and not any(option.lower() in text for option in options):
        failures.append(f"the answer mentions none of {options}")
    for forbidden in case.get("answer_must_not_contain", []):
        if forbidden.lower() in text:
            failures.append(f"the answer contains '{forbidden}', which it should not")

    return {"passed": not failures, "wrong_action": wrong_action, "failures": failures}