"""
Re-grade a SAVED evaluation with the CURRENT cases. No new model calls, so it costs nothing.

    python -m evals.regrade evals/results/<file>.json

Use it after you tighten the checks: it shows how the OLD answers score under the NEW rules.
(The saved file does not record how each run ended, so every run is treated as having ended normally.)
"""
import json
import sys
from pathlib import Path

from evals.grading import grade
from evals.run_evals import load_cases


def regrade(data, cases):
    by_id = {c["id"]: c for c in cases}
    rows, not_run = [], set(by_id) - {r["case_id"] for r in data["results"]}
    for r in data["results"]:
        case = by_id.get(r["case_id"])
        if case is None:
            continue
        verdict = grade(case, final_text=r["final_text"], stop_reason="end_turn", tools=r["tools"],
                        new_refunds=[tuple(x) for x in r["new_refunds"]], tickets=r["tickets"])
        rows.append({"case_id": r["case_id"], "run": r["run"], "was": r["passed"],
                     "now": verdict["passed"], "failures": verdict["failures"]})
    return rows, sorted(not_run)


def main():
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cases = load_cases()
    known = {c["id"] for c in cases if c.get("known_issue")}
    rows, not_run = regrade(data, cases)
    rows = [r for r in rows if r["case_id"] not in known]

    print(f"Re-grading '{data['tag']}' ({len(rows)} scored runs) with the current cases\n")
    print(f"{'case':<38}{'was':<8}{'now':<8}")
    changed = []
    for case_id in dict.fromkeys(r["case_id"] for r in rows):
        mine = [r for r in rows if r["case_id"] == case_id]
        was, now = sum(r["was"] for r in mine), sum(r["now"] for r in mine)
        if was != now:
            print(f"{case_id:<38}{was}/{len(mine):<6}{now}/{len(mine)}")
            changed.append((case_id, [r for r in mine if not r["now"]]))

    total_was, total_now = sum(r["was"] for r in rows), sum(r["now"] for r in rows)
    print(f"\nOVERALL: {total_was}/{len(rows)} passed before, {total_now}/{len(rows)} pass under the stricter checks")

    print("\nWHY (first failing run of each changed case)")
    for case_id, failing in changed:
        print(f"  {case_id} run {failing[0]['run']}")
        for reason in failing[0]["failures"]:
            print(f"    - {reason}")
    if not_run:
        print(f"\nNew cases with no saved runs yet: {', '.join(not_run)}")


if __name__ == "__main__":
    main()