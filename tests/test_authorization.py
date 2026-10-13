"""
Authorization: a customer can only ever see and act on THEIR OWN orders, and only code (never the model) decides who the customer is.
Customer 2 owns order 1001, customer 3 owns 1002, customer 10 owns 1009, customer 1 owns 1010.
"""
import json

from evals.run_evals import load_cases
from shopdesk.agent import loop
from shopdesk.agent.prompts import build_system_prompt
from shopdesk.tools.common import Session
from shopdesk.tools.orders import get_order, list_customer_orders
from shopdesk.tools.refunds import check_refund_eligibility, issue_refund
from shopdesk.tools.registry import TOOLS, run_tool
from shopdesk.tools.tickets import escalate_to_human
from tests.test_agent_loop import text_block, tool_block
from tests.test_agent_reliability import fake_model, reply

ALICE, BOB = Session(2), Session(10)


def refund_args(order_id, key, cents=2000):
    return {"order_id": order_id, "amount_cents": cents, "reason": "changed my mind", "idempotency_key": key}


def tool_result(result, index=2):
    """The JSON the model received for the first tool call of a fake-model run."""
    return json.loads(result.messages[index]["content"][0]["content"])


def test_the_seed_owners_are_what_these_tests_assume(conn):
    owners = dict(conn.execute("SELECT id, customer_id FROM orders WHERE id IN (1001, 1002, 1009, 1010)").fetchall())
    assert owners == {1001: 2, 1002: 3, 1009: 10, 1010: 1}


# ---------- reading ----------

def test_a_customer_can_read_their_own_order(conn):
    assert get_order({"order_id": 1001}, conn=conn, session=ALICE)["ok"] is True


def test_a_customer_cannot_read_someone_elses_order(conn):
    result = get_order({"order_id": 1009}, conn=conn, session=ALICE)
    assert result["ok"] is False and result["error"]["code"] == "ORDER_NOT_FOUND"


def test_not_yours_looks_exactly_like_does_not_exist(conn):
    """If the two errors differed, the agent could be used to discover which order numbers exist."""
    not_yours = get_order({"order_id": 1009}, conn=conn, session=ALICE)["error"]
    missing = get_order({"order_id": 9999}, conn=conn, session=ALICE)["error"]
    blank = lambda e: {**e, "message": e["message"].replace("1009", "N").replace("9999", "N")}
    assert blank(not_yours) == blank(missing)


def test_an_internal_call_without_a_session_is_not_restricted(conn):
    assert get_order({"order_id": 1009}, conn=conn)["ok"] is True          # staff and scripts, never the agent


def test_listing_orders_returns_only_the_signed_in_customers_orders(conn):
    for session in (ALICE, BOB):
        orders = list_customer_orders({"limit": 20}, conn=conn, session=session)["data"]["orders"]
        assert orders
        owners = {r["customer_id"] for r in conn.execute(
            f"SELECT customer_id FROM orders WHERE id IN ({','.join(str(o['order_id']) for o in orders)})")}
        assert owners == {session.customer_id}


def test_the_model_cannot_choose_whose_orders_to_list(conn):
    result = list_customer_orders({"customer_id": 3, "limit": 5}, conn=conn, session=ALICE)
    assert result["ok"] is False and result["error"]["code"] == "INVALID_INPUT"


def test_listing_orders_needs_a_signed_in_customer(conn):
    assert list_customer_orders({}, conn=conn)["error"]["code"] == "NO_SESSION"


# ---------- refunds ----------

def test_eligibility_of_someone_elses_order_is_not_revealed(conn):
    assert check_refund_eligibility({"order_id": 1009}, conn=conn, session=ALICE)["error"]["code"] == "ORDER_NOT_FOUND"
    assert check_refund_eligibility({"order_id": 1001}, conn=conn, session=ALICE)["ok"] is True


def test_a_customer_cannot_refund_someone_elses_order(conn):
    before = conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]
    result = issue_refund(refund_args(1009, "alice-tries-1009"), conn=conn, session=ALICE)
    assert result["ok"] is False and result["error"]["code"] == "ORDER_NOT_FOUND"
    assert conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == before


def test_another_customer_cannot_replay_a_refund_key_to_see_or_repeat_it(conn):
    first = issue_refund(refund_args(1001, "refund-1001-alice01"), conn=conn, session=ALICE)
    assert first["ok"] is True
    replay = issue_refund(refund_args(1001, "refund-1001-alice01"), conn=conn, session=BOB)
    assert replay["ok"] is False and replay["error"]["code"] == "ORDER_NOT_FOUND"
    assert conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = 1001 AND idempotency_key NOT LIKE 'seed-%'"
                        ).fetchone()[0] == 1


def test_the_owner_can_still_retry_safely(conn):
    first = issue_refund(refund_args(1001, "refund-1001-alice02"), conn=conn, session=ALICE)
    again = issue_refund(refund_args(1001, "refund-1001-alice02"), conn=conn, session=ALICE)
    assert first["ok"] and again["ok"] and again["data"]["refund_id"] == first["data"]["refund_id"]


# ---------- tickets ----------

def test_a_ticket_records_who_opened_it(conn):
    args = {"reason": "CUSTOMER_REQUEST", "summary": "Customer asks to speak to a human agent."}
    escalate_to_human(args, conn=conn, session=ALICE)
    escalate_to_human(args, conn=conn)
    owners = [r[0] for r in conn.execute("SELECT customer_id FROM tickets ORDER BY id")]
    assert owners == [2, None]


# ---------- the gate the model goes through ----------

def test_every_tool_that_touches_customer_data_demands_a_session():
    for name, (_func, _spec, needs_session) in TOOLS.items():
        assert needs_session is (name != "search_policy"), name


def test_without_a_session_customer_tools_refuse_and_policy_search_still_works(conn):
    for name, args in [("get_order", {"order_id": 1001}), ("list_customer_orders", {}),
                       ("check_refund_eligibility", {"order_id": 1001}),
                       ("issue_refund", refund_args(1001, "no-session-key")),
                       ("escalate_to_human", {"reason": "OTHER", "summary": "Needs a human to look at this."})]:
        assert run_tool(name, args, conn=conn)["error"]["code"] == "NO_SESSION", name
    assert run_tool("search_policy", {"query": "refund timing"}, conn=conn)["ok"] is True
    assert run_tool("no_such_tool", {}, conn=conn)["error"]["code"] == "UNKNOWN_TOOL"


# ---------- through the agent loop ----------

def test_the_agent_cannot_reach_another_customers_order(monkeypatch, conn):
    fake_model(monkeypatch, [reply([tool_block("t1", "get_order", {"order_id": 1009})], "tool_use"),
                             reply([text_block("I could not find that order.")], "end_turn")])
    result = loop.run_agent("Where is order 1009?", customer_id=2, conn=conn)
    assert tool_result(result)["error"]["code"] == "ORDER_NOT_FOUND"


def test_the_model_cannot_slip_in_a_different_customer_id(monkeypatch, conn):
    fake_model(monkeypatch, [reply([tool_block("t1", "get_order", {"order_id": 1009, "customer_id": 10})], "tool_use"),
                             reply([text_block("Sorry.")], "end_turn")])
    result = loop.run_agent("Where is order 1009?", customer_id=2, conn=conn)
    assert tool_result(result)["error"]["code"] == "INVALID_INPUT"


def test_with_nobody_signed_in_the_agent_gets_refusals_and_still_finishes(monkeypatch, conn):
    fake_model(monkeypatch, [reply([tool_block("t1", "get_order", {"order_id": 1001})], "tool_use"),
                             reply([text_block("I cannot look at orders until you are signed in.")], "end_turn")])
    result = loop.run_agent("Where is order 1001?", conn=conn)
    assert tool_result(result)["error"]["code"] == "NO_SESSION"
    assert result.stop_reason == "end_turn"


def test_the_prompt_never_hands_the_model_an_id_to_pass_around():
    assert "customer #" not in build_system_prompt(2)
    assert "already signed in" in build_system_prompt(2)
    assert "No customer is signed in" in build_system_prompt(None)


# ---------- the exam ----------

def test_the_ownership_cases_are_part_of_the_scored_exam():
    cases = {c["id"]: c for c in load_cases()}
    for case_id in ("known_other_customers_order_info", "known_other_customers_order_refund",
                    "authz_list_other_customers_orders", "authz_eligibility_of_other_customers_order",
                    "authz_claimed_identity"):
        assert cases[case_id]["category"] == "authorization", case_id
        assert "known_issue" not in cases[case_id], case_id


def test_the_leak_signals_never_collide_with_the_asking_customers_own_data(conn):
    """A check that forbids '50.00' would fail an agent that honestly mentions the customer's own $50.00 order."""
    for case in load_cases():
        if case["category"] != "authorization":
            continue
        rows = conn.execute(
            "SELECT o.id, o.total_cents, o.placed_at, o.delivered_at, oi.name FROM orders o "
            "JOIN order_items oi ON oi.order_id = o.id WHERE o.customer_id = ?", (case["customer_id"],)).fetchall()
        own_text = " ".join(f"{r['id']} ${r['total_cents'] / 100:.2f} {r['name']} {r['placed_at']} {r['delivered_at']}"
                            for r in rows).lower()
        for signal in case.get("answer_must_not_contain", []):
            assert signal.lower() not in own_text, f"{case['id']}: '{signal}' appears in the customer's own orders"
