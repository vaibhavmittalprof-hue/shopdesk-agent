from shopdesk.agent.loop import run_agent
from shopdesk.tracing import Tracer


def main():
    raw = input("Which customer are you? (customer id, or press Enter to skip): ").strip()
    customer_id = int(raw) if raw.isdigit() else None
    print("Type your message. Type 'quit' to exit.\n")

    history = []   # the conversation so far: this IS the agent's memory
    while True:
        user = input("You: ").strip()
        if user.lower() in {"quit", "exit"}:
            break
        if not user:
            continue
        result = run_agent(user, history=history, customer_id=customer_id,
                           verbose=True, tracer=Tracer())     # a new trace file for every message
        history = result.messages
        print(f"\nAgent: {result.text}")
        print(f"[{result.steps} steps, {result.input_tokens} in / {result.output_tokens} out tokens, "
              f"${result.cost_usd:.4f}, stopped: {result.stop_reason}]")
        print(f"[trace: {result.trace_path}]\n")


if __name__ == "__main__":
    main()