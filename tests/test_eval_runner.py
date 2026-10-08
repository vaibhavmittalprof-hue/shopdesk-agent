from evals import run_evals
from evals.run_evals import load_cases, run_case, summarize
from tests.test_agent_reliability import fake_model, reply
from tests.test_agent_loop import text_block, tool_block

CASES = {c["id"]: c for c in load_cases()}


def refund_script(order_id, amount, key):
    """The replies of an agent that checks eligibility, asks to confirm, then refunds."""
    return [
        reply([tool_block("t1", "check_refund_eligibility", {"order_id": order_id})], "tool_use"),
        reply([text_block("You are eligible. Shall I go ahead?")], "end_turn"),
        reply([tool_block("t2", "issue_refund", {"order_id": order_id, "amount_cents": amount,
                                                 "reason": "customer request", "idempotency_key": key})], "tool_use"),
        reply([text_block("Your refund has been issued.")], "end_turn"),
    ]


def test_a_correct_agent_passes_a_refund_case(monkeypatch, tmp_path):
    fake_model(monkeypatch, refund_script(1001, 5000, "refund-1001-evalrun1"))
    result = run_case(CASES["refund_ok_clothing"], 1, tmp_path, tmp_path / "traces")
    assert result["passed"] is True, result["failures"]
    assert result["new_refunds"] == [(1001, 5000)]
    assert result["steps"] == 4 and result["cost_usd"] > 0
    assert len(result["traces"]) == 2                          # one trace file per customer message


def test_every_run_starts_from_a_fresh_shop(monkeypatch, tmp_path):
    for run_number in (1, 2):
        fake_model(monkeypatch, refund_script(1001, 5000, f"refund-1001-evalrun{run_number}"))
        result = run_case(CASES["refund_ok_clothing"], run_number, tmp_path, tmp_path / "traces")
        assert result["passed"] is True, f"run {run_number}: {result['failures']}"   # run 2 isn't 'already refunded'


def test_a_wrong_action_is_caught(monkeypatch, tmp_path):
    # An agent that refunds ANOTHER customer's order (the ownership gap). Customer 2 asks for 1009.
    fake_model(monkeypatch, refund_script(1009, 5000, "refund-1009-evalrun1"))
    result = run_case(CASES["known_other_customers_order_refund"], 1, tmp_path, tmp_path / "traces")
    assert result["passed"] is False and result["wrong_action"] is True


def test_an_agent_that_does_nothing_fails_the_refund_case(monkeypatch, tmp_path):
    fake_model(monkeypatch, [reply([text_block("Sorry, I cannot help with that.")], "end_turn")] * 2)
    result = run_case(CASES["refund_ok_clothing"], 1, tmp_path, tmp_path / "traces")
    assert result["passed"] is False and result["wrong_action"] is False


def test_a_crash_inside_a_run_is_recorded_not_raised(monkeypatch, tmp_path):
    def explode(*args, **kwargs):
        raise RuntimeError("bug")
    monkeypatch.setattr(run_evals, "run_agent", explode)
    result = run_case(CASES["info_shipped_status"], 1, tmp_path, tmp_path / "traces")
    assert result["passed"] is False and "crashed" in result["failures"][0]


def test_summary_excludes_known_issues_and_finds_flaky_cases():
    cases = [{"id": "a", "category": "info"}, {"id": "b", "category": "info"},
             {"id": "k", "category": "known_issue", "known_issue": "later"}]

    def result(case_id, passed, wrong=False):
        return {"case_id": case_id, "passed": passed, "wrong_action": wrong, "steps": 2,
                "cost_usd": 0.01, "duration_s": 1.0}

    results = [result("a", True), result("a", True), result("b", True), result("b", False),
               result("k", False, wrong=True), result("k", False, wrong=True)]
    s = summarize(cases, results)
    assert s["scored_runs"] == 4 and s["passed"] == 3
    assert s["wrong_actions"] == 0                         # the known issue's wrong actions are separate
    assert s["known_issue_wrong_actions"] == 2
    assert s["flaky_cases"] == ["b"]
    assert s["by_category"] == {"info": {"passed": 3, "runs": 4}}
