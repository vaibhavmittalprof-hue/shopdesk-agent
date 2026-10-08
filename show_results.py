"""
Show what happened in every run of a saved evaluation.

    python show_results.py evals/results/<file>.json
    python show_results.py evals/results/<file>.json known_other     # only cases whose id contains this
"""
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
only = sys.argv[2] if len(sys.argv) > 2 else ""

for r in data["results"]:
    if only not in r["case_id"]:
        continue
    print(f"\n{r['case_id']}  run {r['run']}: {'PASS' if r['passed'] else 'FAIL'}"
          f"{'   <-- WRONG ACTION' if r['wrong_action'] else ''}")
    print(f"  tools called:   {', '.join(r['tools']) or '(none)'}")
    print(f"  refunds made:   {r['new_refunds'] or '(none)'}")
    print(f"  tickets made:   {len(r['tickets'])}")
    for reason in r["failures"]:
        print(f"  failed because: {reason}")
    print(f"  agent said:     {r['final_text'][:220].replace(chr(10), ' ')}")