import json
import secrets
from datetime import datetime
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"


def new_run_id() -> str:
    # real clock on purpose: traces record when things REALLY happened
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def block_to_dict(block) -> dict:
    """Turn one block of a model reply into plain data that can be saved as JSON."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": block.type}


class Tracer:
    """Appends one JSON object per line (JSONL) to traces/<run_id>.jsonl."""

    def __init__(self, run_id=None, directory=None, enabled=True):
        self.run_id = run_id or new_run_id()
        self.enabled = enabled
        folder = Path(directory) if directory else TRACE_DIR
        self.path = folder / f"{self.run_id}.jsonl"
        self._warned = False
        if enabled:
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._disable(exc)

    def _disable(self, exc):
        if not self._warned:
            print(f"[tracing turned off: {exc}]")
            self._warned = True
        self.enabled = False

    def event(self, kind: str, **fields):
        """Write one event. Tracing must NEVER crash the agent, so errors are swallowed."""
        if not self.enabled:
            return
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "event": kind,
            **fields,
        }
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            self._disable(exc)