from shopdesk.tools.common import err
from shopdesk.tools.orders import (
    GET_ORDER_SPEC,
    LIST_CUSTOMER_ORDERS_SPEC,
    get_order,
    list_customer_orders,
)
from shopdesk.tools.refunds import (
    CHECK_REFUND_ELIGIBILITY_SPEC,
    ISSUE_REFUND_SPEC,
    check_refund_eligibility,
    issue_refund,
)
from shopdesk.tools.tickets import ESCALATE_TO_HUMAN_SPEC, escalate_to_human

# name -> (the real function, the description shown to the model)
TOOLS = {
    "get_order": (get_order, GET_ORDER_SPEC),
    "list_customer_orders": (list_customer_orders, LIST_CUSTOMER_ORDERS_SPEC),
    "check_refund_eligibility": (check_refund_eligibility, CHECK_REFUND_ELIGIBILITY_SPEC),
    "issue_refund": (issue_refund, ISSUE_REFUND_SPEC),
    "escalate_to_human": (escalate_to_human, ESCALATE_TO_HUMAN_SPEC),
}

# The "menu" sent to the model on every call
TOOL_SPECS = [spec for _, spec in TOOLS.values()]


def run_tool(name: str, raw_args: dict, conn=None) -> dict:
    """
    Run one tool by name. ALWAYS returns a result dict; it never raises,
    so one bad tool call can't crash the whole agent.
    """
    if name not in TOOLS:
        return err(
            "UNKNOWN_TOOL",
            f"There is no tool named '{name}'.",
            f"Available tools: {', '.join(TOOLS)}.",
        )

    func, _spec = TOOLS[name]
    try:
        return func(raw_args, conn=conn)
    except Exception as exc:  # safety net for bugs inside a tool
        return err(
            "TOOL_CRASHED",
            f"The tool '{name}' failed unexpectedly ({type(exc).__name__}).",
            "This is a system problem, not the customer's fault. Do not retry; tell the customer you could not complete the lookup.",
        )