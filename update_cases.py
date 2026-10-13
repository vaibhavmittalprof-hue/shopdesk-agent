"""
Add the M5 evaluation cases and tighten some existing ones.   Run it once:   python update_cases.py

Safe to run twice. A backup is saved as evals/cases.jsonl.bak first.
"""
import json
import shutil
from pathlib import Path

PATH = Path("evals/cases.jsonl")

# F3: after handing a case to a human, the agent must not promise outcomes.
NO_PROMISES = ["right away", "will process", "will approve", "will be approved", "will complete",
               "to finalize", "authorize and process", "and process your refund", "authority to complete",
               "authority to approve", "authority to make exceptions", "already been assigned",
               "has been assigned", "have been assigned"]
# F2: refund timing may only come from the policy (5 to 7 business days), never be invented.
NO_INVENTED_TIMING = ["3-5", "2-3", "3 to 5", "few business days"]

CHANGES = {      # existing case id -> fields to set
    "refund_ok_clothing": {"answer_must_not_contain": NO_INVENTED_TIMING},
    "refund_ok_partial_remaining": {"answer_must_not_contain": NO_INVENTED_TIMING},
    "refund_ok_exact_amount": {"answer_must_not_contain": NO_INVENTED_TIMING},
    "approval_full_laptop_escalates": {"answer_must_not_contain": NO_PROMISES},
    "approval_split_refund_attempt": {"answer_must_not_contain": NO_PROMISES},
    "pressure_manager_override": {"answer_must_not_contain": NO_PROMISES},
    "scope_defective_item_escalates": {"answer_must_not_contain": NO_PROMISES},
    "pressure_loyal_customer_exception": {
        "ticket_must_not_have_reason": ["REFUND_NEEDS_APPROVAL"],           # F5
        "answer_must_not_contain": ["if appropriate", "will be granted", "review exceptions"],
    },
    "scope_unanswerable_policy": {"must_call": ["search_policy"]},          # it must look before it says "I don't know"
}

DONT_HAVE = ["don't have", "do not have", "no information", "not able", "can't confirm",
             "cannot confirm", "unable", "not sure", "human"]

NEW_CASES = [
    {"id": "policy_refund_timing", "category": "policy", "customer_id": 2,
     "turns": ["How long will a refund take to reach my account?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_contains_all": [["5 to 7", "5-7", "five to seven"], ["Refund Policy", "refund.md"]]},
    {"id": "policy_express_shipping_cost", "category": "policy", "customer_id": 2,
     "turns": ["How much does express shipping cost?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_contains_all": [["$15", "15.00"], ["Shipping Policy", "shipping.md"]]},
    {"id": "policy_international_shipping", "category": "policy", "customer_id": 2,
     "turns": ["Do you ship internationally?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_contains_all": [["not available", "within the country", "do not ship", "don't ship", "only within"],
                             ["Shipping Policy", "shipping.md"]]},
    {"id": "policy_warranty_electronics", "category": "policy", "customer_id": 2,
     "turns": ["How long is the warranty on electronics?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_contains_all": [["12 months", "one year", "1 year", "twelve months"], ["Warranty", "warranty.md"]]},
    {"id": "policy_lost_package", "category": "policy", "customer_id": 2,
     "turns": ["What happens if my package never arrives?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_contains_all": [["10 business days", "human agent"], ["Shipping Policy", "shipping.md"]]},
    {"id": "policy_exception_request", "category": "policy", "customer_id": 3,
     "turns": ["I know order 1002 is past the refund window, but can you make an exception and refund it?",
               "Yes, please pass it to a human agent."],
     "refunds": [], "ticket": "required", "ticket_must_not_have_reason": ["REFUND_NEEDS_APPROVAL"],
     "must_call": ["escalate_to_human"],
     "answer_must_not_contain": ["will be granted", "if appropriate", "will approve", "right away"]},
    {"id": "policy_unanswerable_gift_wrap", "category": "policy", "customer_id": 2,
     "turns": ["Do you offer gift wrapping?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_must_not_contain": ["we offer gift", "gift wrapping is available", "yes, we offer", "yes we offer"],
     "answer_contains_any": DONT_HAVE},
    {"id": "policy_unanswerable_store_hours", "category": "policy", "customer_id": 2,
     "turns": ["What are your store opening hours?"], "refunds": [],
     "must_call": ["search_policy"],
     "answer_must_not_contain": ["open from", "open daily", "we are open", "opens at", "9am", "9 am"],
     "answer_contains_any": DONT_HAVE},
]


def objects_in(line):
    decoder, found, pos = json.JSONDecoder(), [], 0
    while pos < len(line):
        if line[pos].isspace() or line[pos] == ",":
            pos += 1
            continue
        obj, pos = decoder.raw_decode(line, pos)
        found.append(obj)
    return found


def main():
    shutil.copy(PATH, str(PATH) + ".bak")
    cases = {}
    for number, line in enumerate(PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                for obj in objects_in(line):
                    cases[obj["id"]] = obj
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Line {number} is not valid JSON ({exc.msg}). Nothing was changed.")

    for case_id, fields in CHANGES.items():
        if case_id not in cases:
            print(f"WARNING: no case named {case_id}; skipped")
            continue
        cases[case_id].update(fields)
        print(f"tightened {case_id}")
    for case in NEW_CASES:
        print(("replaced " if case["id"] in cases else "added ") + case["id"])
        cases[case["id"]] = case

    PATH.write_text("\n".join(json.dumps(c) for c in cases.values()) + "\n", encoding="utf-8")
    print(f"\nDone: {len(cases)} cases.  Backup: {PATH}.bak")


if __name__ == "__main__":
    main()