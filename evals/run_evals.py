"""
Run the evaluation: every case in evals/cases.jsonl, several times each, against the REAL model.

    python -m evals.run_evals                       # all cases, 3 runs each
    python -m evals.run_evals --runs 1              # a quick, cheaper first pass
    python -m evals.run_evals --case refund_ok      # only cases whose id contains this text
    python -m evals.run_evals --tag after-prompt-fix
"""
import argparse
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

from data.seed import main as seed_db
from evals.grading import grade, tool_names, wilson_interval
from shopdesk.agent.loop import run_agent
from shopdesk.db import get_connection
from shopdesk.llm import MODEL
from shopdesk.tracing import TRACE_DIR, Tracer

CASES_PATH = Path(__file__).parent / "cases.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"


def load_cases(path=CASES_PATH):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def run_case(case, run_number, work_dir, trace_dir):
    """Run ONE case ONCE: a fresh shop, the scripted customer messages, then grade the outcome."""
    db_path = Path(work_dir) / f"{case['id']}-{run_number}.db"
    seed_db(db_path, verbose=False)               # a fresh, identical shop for EVERY run
    conn = get_connection(db_path)

    history, steps, in_tokens, out_tokens, cost = [], 0, 0, 0, 0.0
    traces, result, crashed = [], None, ""
    started = time.time()
    try:
        for turn, text in enumerate(case["turns"], start=1):
            tracer = Tracer(run_id=f"{case['id']}-run{run_number}-turn{turn}", directory=trace_dir)
            result = run_agent(text, history=history, customer_id=case["customer_id"],
                               conn=conn, tracer=tracer)
            history = result.messages
            steps += result.steps
            in_tokens += result.input_tokens
            out_tokens += result.output_tokens
            cost += result.cost_usd
            traces.append(result.trace_path)
            if result.stop_reason != "end_turn":      # a broken turn: don't play the rest
                break
    except Exception as exc:                          # a bug must not stop the whole evaluation
        crashed = f"{type(exc).__name__}: {exc}"
    duration = time.time() - started

    # Read the OUTCOME from the database: what really happened, not what the agent said
    new_refunds = [(r["order_id"], r["amount_cents"]) for r in conn.execute(
        "SELECT order_id, amount_cents FROM refunds WHERE idempotency_key NOT LIKE 'seed-refund-%'")]
    tickets = [r["summary"] for r in conn.execute("SELECT summary FROM tickets")]
    conn.close()

    if crashed or result is None:
        graded = {"passed": False, "wrong_action": False, "failures": [f"the run crashed: {crashed}"]}
    else:
        graded = grade(case, final_text=result.text, stop_reason=result.stop_reason,
                       tools=tool_names(history), new_refunds=new_refunds, tickets=tickets)

    return {
        "case_id": case["id"], "run": run_number, **graded,
        "steps": steps, "input_tokens": in_tokens, "output_tokens": out_tokens,
        "cost_usd": cost, "duration_s": round(duration, 2),
        "final_text": result.text if result else "", "tools": tool_names(history),
        "new_refunds": new_refunds, "tickets": tickets, "traces": traces,
    }


def summarize(cases, results):
    by_id = {c["id"]: c for c in cases}
    scored = [r for r in results if not by_id[r["case_id"]].get("known_issue")]
    known = [r for r in results if by_id[r["case_id"]].get("known_issue")]

    passed = sum(r["passed"] for r in scored)
    low, high = wilson_interval(passed, len(scored))

    per_case = {}
    for r in results:
        per_case.setdefault(r["case_id"], []).append(r["passed"])
    flaky = [cid for cid, p in per_case.items()
             if 0 < sum(p) < len(p) and not by_id[cid].get("known_issue")]

    categories = {}
    for r in scored:
        entry = categories.setdefault(by_id[r["case_id"]]["category"], [0, 0])
        entry[0] += r["passed"]
        entry[1] += 1

    n = max(len(results), 1)
    return {
        "scored_runs": len(scored), "passed": passed,
        "pass_rate": passed / len(scored) if scored else 0.0,
        "ci_low": low, "ci_high": high,
        "wrong_actions": sum(r["wrong_action"] for r in scored),
        "known_issue_runs": len(known), "known_issue_passed": sum(r["passed"] for r in known),
        "known_issue_wrong_actions": sum(r["wrong_action"] for r in known),
        "flaky_cases": flaky,
        "by_category": {k: {"passed": v[0], "runs": v[1]} for k, v in sorted(categories.items())},
        "avg_steps": sum(r["steps"] for r in results) / n,
        "avg_cost_usd": sum(r["cost_usd"] for r in results) / n,
        "avg_duration_s": sum(r["duration_s"] for r in results) / n,
        "total_cost_usd": sum(r["cost_usd"] for r in results),
    }


def print_report(cases, results, summary, tag, runs):
    by_id = {c["id"]: c for c in cases}
    print(f"\nEVAL '{tag}': {len(cases)} cases x {runs} runs, model {MODEL}\n")

    print(f"{'case':<38}{'runs':<14}result")
    for case in cases:
        marks = [r for r in results if r["case_id"] == case["id"]]
        label = " ".join("PASS" if r["passed"] else "FAIL" for r in marks)
        note = "  (known issue)" if case.get("known_issue") else ""
        print(f"{case['id']:<38}{label:<14}{sum(r['passed'] for r in marks)}/{len(marks)}{note}")

    s = summary
    print("\nSUMMARY (known issues excluded)")
    print(f"  pass rate:     {s['passed']}/{s['scored_runs']} = {s['pass_rate']:.1%}   "
          f"(95% CI {s['ci_low']:.1%} to {s['ci_high']:.1%})")
    print(f"  WRONG ACTIONS: {s['wrong_actions']}   <- this must be 0")
    print(f"  flaky cases:   {', '.join(s['flaky_cases']) or 'none'}")
    print(f"  per run:       {s['avg_steps']:.1f} steps, ${s['avg_cost_usd']:.4f}, {s['avg_duration_s']:.1f} s"
          f"   (total ${s['total_cost_usd']:.2f})")
    print("  by category:   " + ", ".join(
        f"{name} {v['passed']}/{v['runs']}" for name, v in s["by_category"].items()))
    if s["known_issue_runs"]:
        print(f"\nKNOWN ISSUES (not counted): passed {s['known_issue_passed']}/{s['known_issue_runs']} runs, "
              f"wrong actions {s['known_issue_wrong_actions']}")

    failures = [r for r in results if not r["passed"] and not by_id[r["case_id"]].get("known_issue")]
    if failures:
        print(f"\nFAILURES ({len(failures)}): read these first")
        for r in failures:
            print(f"\n  {r['case_id']} (run {r['run']})")
            for reason in r["failures"]:
                print(f"    - {reason}")
            if r["final_text"]:
                print(f"    agent said: {r['final_text'][:200]}")
            if r["traces"]:
                print(f"    trace: {r['traces'][-1]}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate the ShopDesk agent.")
    parser.add_argument("--runs", type=int, default=3, help="runs per case (default 3)")
    parser.add_argument("--case", help="only cases whose id contains this text")
    parser.add_argument("--tag", default="baseline", help="a label for this evaluation")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if args.case in c["id"]]
    if not cases:
        raise SystemExit("No cases match.")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trace_dir = TRACE_DIR / "evals" / f"{stamp}-{args.tag}"
    results = []
    with tempfile.TemporaryDirectory() as work_dir:
        for case in cases:
            for run_number in range(1, args.runs + 1):
                outcome = run_case(case, run_number, work_dir, trace_dir)
                results.append(outcome)
                print(f"{case['id']:<38} run {run_number}: {'PASS' if outcome['passed'] else 'FAIL'}", flush=True)

    summary = summarize(cases, results)
    print_report(cases, results, summary, args.tag, args.runs)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{stamp}-{args.tag}.json"
    out.write_text(json.dumps({"tag": args.tag, "model": MODEL, "runs_per_case": args.runs,
                               "summary": summary, "results": results}, indent=2, default=str),
                   encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()