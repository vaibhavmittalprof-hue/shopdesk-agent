"""
Print a saved trace as a readable timeline.

    python show_trace.py                      # the newest trace in traces/
    python show_trace.py traces/<file>.jsonl  # a specific one
"""
import json
import sys
from pathlib import Path

from shopdesk.tracing import TRACE_DIR


def load(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def short(value, limit=170):
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[:limit] + "..."


def show(events):
    for e in events:
        kind, time = e["event"], e["ts"][11:23]

        if kind == "run_start":
            print(f"{time}  RUN START    model={e['model']}  customer={e['customer_id']}  max_steps={e['max_steps']}")
            print(f"             customer says: {e['user_message']}")

        elif kind == "model_call":
            cost = f"${e['cost_usd']:.4f}" if e["cost_usd"] is not None else "unknown"
            print(f"{time}  [step {e['step']}] MODEL   {e['latency_ms']} ms | {e['input_tokens']} in / "
                  f"{e['output_tokens']} out | {cost} | attempts={e['attempts']} | stop={e['stop_reason']}")
            for block in e["content"]:
                if block["type"] == "text" and block["text"].strip():
                    print(f"             says: {short(block['text'])}")
                elif block["type"] == "tool_use":
                    print(f"             asks for: {block['name']}({short(block['input'])})")

        elif kind == "tool_call":
            status = "OK" if e["ok"] else "ERROR"
            note = "  (BLOCKED: repeated call)" if e.get("blocked") else ""
            print(f"{time}  [step {e['step']}] TOOL    {e['name']} -> {status}, {e['latency_ms']} ms{note}")
            print(f"             result: {short(e['result'])}")

        elif kind == "retry":
            print(f"{time}  [step {e['step']}] RETRY   {e['error']}, waited {e['wait_s']}s (attempt {e['attempt']})")

        elif kind in ("loop_warning", "budget_exceeded", "model_error"):
            detail = {k: v for k, v in e.items() if k not in ("ts", "run_id", "event")}
            print(f"{time}  !! {kind.upper()}: {short(detail)}")

        elif kind == "run_end":
            print(f"{time}  RUN END      stop={e['stop_reason']} | {e['steps']} steps | "
                  f"{e['input_tokens']} in / {e['output_tokens']} out | ${e['cost_usd']:.4f} | {e['duration_ms']} ms")
            print(f"             final answer: {short(e['final_text'])}")


def main():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        traces = sorted(TRACE_DIR.glob("*.jsonl"))
        if not traces:
            sys.exit("No traces yet. Run chat_cli.py and send a message first.")
        path = traces[-1]
    print(f"Trace: {path}\n")
    show(load(path))


if __name__ == "__main__":
    main()