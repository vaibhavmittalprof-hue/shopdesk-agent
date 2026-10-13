"""
Corrections to evals/cases.jsonl after reading the m5-after and m5-fixes answers.   Run once:   python fix_cases_m5.py

Safe to run twice. A backup is saved as evals/cases.jsonl.bak first.
"""
import json
import shutil
from pathlib import Path

PATH = Path("evals/cases.jsonl")
WARRANTY_OPTIONS = ["12 months", "12-month", "12 month", "one year", "1 year", "twelve months", "twelve-month"]
REFUND_CASES = ["refund_ok_clothing", "refund_ok_partial_remaining", "refund_ok_exact_amount"]


def main():
    shutil.copy(PATH, str(PATH) + ".bak")
    try:
        cases = [json.loads(line) for line in PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise SystemExit(f"cases.jsonl is not valid JSON ({exc.msg}). Run update_cases.py or fix_cases.py first.")

    for case in cases:
        if case["id"] == "policy_warranty_electronics":
            case["answer_contains_all"][0] = WARRANTY_OPTIONS
            print("policy_warranty_electronics: the check now accepts '12-month' (the agent's correct wording)")
        if case["id"] == "policy_unanswerable_store_hours":
            case.pop("must_call", None)
            print("policy_unanswerable_store_hours: no longer REQUIRES a search (declining correctly is the point)")
        if case["id"] in REFUND_CASES:
            banned = case.setdefault("answer_must_not_contain", [])
            if "charged" not in banned:
                banned.append("charged")
            print(f"{case['id']}: the answer must not talk about money being 'charged' (F9)")

    PATH.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")
    print(f"\nDone: {len(cases)} cases.  Backup: {PATH}.bak")


if __name__ == "__main__":
    main()