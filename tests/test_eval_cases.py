import json

import pytest

from evals.grading import grade
from evals.run_evals import CASES_PATH, load_cases
from shopdesk.policy import APPROVAL_LIMIT_CENTS
from shopdesk.tools.refunds import check_refund_eligibility
from shopdesk.tools.registry import TOOLS

ALLOWED_KEYS = {"id", "category", "customer_id", "turns", "refunds", "ticket", "ticket_reason",
                "must_call", "must_not_call", "answer_contains_any", "answer_must_not_contain",
                "known_issue"}
CASES = load_cases()


def test_the_file_is_clean_json_lines():
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line)


def test_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_each_case_is_well_formed(case, conn):
    assert set(case) <= ALLOWED_KEYS, f"unknown keys: {set(case) - ALLOWED_KEYS}"
    assert case["turns"] and all(isinstance(t, str) and t.strip() for t in case["turns"])
    assert conn.execute("SELECT 1 FROM customers WHERE id = ?", (case["customer_id"],)).fetchone()
    for name in case.get("must_call", []) + case.get("must_not_call", []):
        assert name in TOOLS, f"unknown tool {name}"
    assert case.get("ticket", "required") in ("required", "none")
    if "ticket_reason" in case:
        assert case["ticket"] == "required"
    if case["category"] == "known_issue":
        assert case["known_issue"].strip()


def test_every_expected_refund_is_actually_allowed_by_the_rules(conn):
    """The answer key is checked against the real rule engine, so a typo in a case is caught."""
    for case in CASES:
        per_order = {}
        for refund in case.get("refunds", []):
            per_order[refund["order_id"]] = per_order.get(refund["order_id"], 0) + refund["amount_cents"]
            facts = check_refund_eligibility({"order_id": refund["order_id"]}, conn=conn)["data"]
            assert facts["eligible"], case["id"]
            assert refund["amount_cents"] <= facts["refundable_cents"], case["id"]
        for order_id, total in per_order.items():
            assert total <= APPROVAL_LIMIT_CENTS, f"{case['id']}: needs approval, so it cannot be an expected refund"


@pytest.mark.parametrize("case_id, order_id", [
    ("refund_denied_electronics_window", 1002), ("refund_denied_clothing_window", 1003),
    ("refund_denied_old_home_item", 1004), ("refund_denied_cancelled", 1005),
    ("refund_denied_not_delivered", 1006), ("refund_denied_gift_card", 1007),
    ("refund_denied_already_refunded", 1008),
])
def test_the_denied_cases_really_are_ineligible(conn, case_id, order_id):
    assert check_refund_eligibility({"order_id": order_id}, conn=conn)["data"]["eligible"] is False


def test_a_do_nothing_agent_fails_every_case_that_needs_action():
    """If an agent that does NOTHING can pass a case, the case is not testing anything."""
    for case in CASES:
        needs_action = bool(case.get("refunds")) or case.get("ticket") == "required" or case.get("must_call")
        if needs_action:
            result = grade(case, final_text="Sorry, I can't help.", stop_reason="end_turn",
                           tools=[], new_refunds=[], tickets=[])
            assert result["passed"] is False, f"{case['id']} can be passed by doing nothing"
