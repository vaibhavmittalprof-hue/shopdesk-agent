from evals.regrade import regrade


def saved(case_id, run, text, tools=(), refunds=(), tickets=()):
    return {"case_id": case_id, "run": run, "passed": True, "final_text": text,
            "tools": list(tools), "new_refunds": [list(r) for r in refunds], "tickets": list(tickets)}


CASES = [
    {"id": "timing", "category": "x", "answer_must_not_contain": ["3-5"]},
    {"id": "plain", "category": "x"},
    {"id": "brand_new", "category": "x"},
]


def test_old_answers_are_graded_by_the_new_checks():
    data = {"results": [saved("timing", 1, "Back in 3\u20135 business days."),
                        saved("timing", 2, "Back in 5 to 7 business days."),
                        saved("plain", 1, "Anything.")]}
    rows, _ = regrade(data, CASES)
    assert [(r["case_id"], r["run"], r["now"]) for r in rows] == [
        ("timing", 1, False), ("timing", 2, True), ("plain", 1, True)]
    assert all(r["was"] is True for r in rows)             # they all passed under the old checks


def test_cases_that_were_never_run_are_reported_not_graded():
    rows, not_run = regrade({"results": [saved("plain", 1, "Anything.")]}, CASES)
    assert not_run == ["brand_new", "timing"]
    assert [r["case_id"] for r in rows] == ["plain"]


def test_results_for_cases_that_no_longer_exist_are_skipped():
    rows, _ = regrade({"results": [saved("deleted_case", 1, "x")]}, CASES)
    assert rows == []
