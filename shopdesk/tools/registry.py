from shopdesk.tools.common import err
from shopdesk.tools.orders import (
    GET_ORDER_SPEC,
    LIST_CUSTOMER_ORDERS_SPEC,
    get_order,
    list_customer_orders,
)
from shopdesk.tools.policy import SEARCH_POLICY_SPEC, search_policy
from shopdesk.tools.refunds import (
    CHECK_REFUND_ELIGIBILITY_SPEC,
    ISSUE_REFUND_SPEC,
    check_refund_eligibility,
    issue_refund,
)
from shopdesk.tools.tickets import ESCALATE_TO_HUMAN_SPEC, escalate_to_human

# name -> (the real function, the description shown to the model, does it touch a customer's data?)
# A tool that touches customer data REFUSES to run unless a signed-in customer (a Session) is supplied.
TOOLS = {
    "get_order": (get_order, GET_ORDER_SPEC, True),
    "list_customer_orders": (list_customer_orders, LIST_CUSTOMER_ORDERS_SPEC, True),
    "check_refund_eligibility": (check_refund_eligibility, CHECK_REFUND_ELIGIBILITY_SPEC, True),
    "issue_refund": (issue_refund, ISSUE_REFUND_SPEC, True),
    "escalate_to_human": (escalate_to_human, ESCALATE_TO_HUMAN_SPEC, True),
    "search_policy": (search_policy, SEARCH_POLICY_SPEC, False),     # public policy text only
}

# The "menu" sent to the model on every call
TOOL_SPECS = [spec for _, spec, _ in TOOLS.values()]


def run_tool(name: str, raw_args: dict, conn=None, session=None) -> dict:
    """
    Run one tool by name. ALWAYS returns a result dict; it never raises,
    so one bad tool call can't crash the whole agent.

    `session` says who the signed-in customer is. It comes from the agent loop, never from the model.
    """
    if name not in TOOLS:
        return err(
            "UNKNOWN_TOOL",
            f"There is no tool named '{name}'.",
            f"Available tools: {', '.join(TOOLS)}.",
        )

    func, _spec, needs_session = TOOLS[name]
    if needs_session and session is None:
        return err(
            "NO_SESSION",
            "No customer is signed in, so this tool cannot be used.",
            "Tell the customer you cannot look at orders or tickets until they are signed in.",
        )
    try:
        return func(raw_args, conn=conn, session=session)
    except Exception as exc:  # safety net for bugs inside a tool
        return err(
            "TOOL_CRASHED",
            f"The tool '{name}' failed unexpectedly ({type(exc).__name__}).",
            "This is a system problem, not the customer's fault. Do not retry; tell the customer you could not complete the lookup.",
        )
