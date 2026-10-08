"""
Compare two evaluation result files and show what changed.

    python -m evals.compare evals/results/<before>.json evals/results/<after>.json
"""
import json
import sys
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pass_counts(data):
    counts = {}
    for r in data["results"]:
        entry = counts.setdefault(r["case_id"], [0, 0])
        entry[0] += r["passed"]
        entry[1] += 1
    return counts


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    before, after = load(sys.argv[1]), load(sys.argv[2])
    a, b = pass_counts(before), pass_counts(after)

    print(f"before: {before['tag']}   after: {after['tag']}\n")
    changed = 0
    for case_id in sorted(set(a) | set(b)):
        x, y = a.get(case_id, [0, 0]), b.get(case_id, [0, 0])
        if x[0] / max(x[1], 1) != y[0] / max(y[1], 1):
            arrow = "BETTER" if y[0] / max(y[1], 1) > x[0] / max(x[1], 1) else "WORSE "
            print(f"  {arrow}  {case_id:<38}{x[0]}/{x[1]}  ->  {y[0]}/{y[1]}")
            changed += 1
    if not changed:
        print("  no case changed")

    sb, sa = before["summary"], after["summary"]
    print(f"\n  pass rate:     {sb['pass_rate']:.1%}  ->  {sa['pass_rate']:.1%}")
    print(f"  wrong actions: {sb['wrong_actions']}  ->  {sa['wrong_actions']}")
    print(f"  avg cost/run:  ${sb['avg_cost_usd']:.4f}  ->  ${sa['avg_cost_usd']:.4f}")
    print(f"  avg steps/run: {sb['avg_steps']:.1f}  ->  {sa['avg_steps']:.1f}")


if __name__ == "__main__":
    main()