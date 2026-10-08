import json

from shopdesk.pricing import estimate_cost
from shopdesk.tracing import Tracer


def test_cost_of_one_million_tokens():
    assert estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 0) == 1.00
    assert estimate_cost("claude-haiku-4-5-20251001", 0, 1_000_000) == 5.00


def test_cost_of_a_typical_call():
    # 1,000 tokens in, 500 out = $0.001 + $0.0025
    assert round(estimate_cost("claude-haiku-4-5-20251001", 1000, 500), 6) == 0.0035


def test_unknown_model_cost_is_unknown_not_zero():
    assert estimate_cost("some-future-model", 1000, 500) is None


def test_tracer_writes_one_json_object_per_line(tmp_path):
    tracer = Tracer(run_id="run1", directory=tmp_path)
    tracer.event("run_start", user_message="hello")
    tracer.event("run_end", stop_reason="end_turn")
    lines = (tmp_path / "run1.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["event"] for r in records] == ["run_start", "run_end"]
    assert records[0]["run_id"] == "run1" and records[0]["user_message"] == "hello"
    assert "ts" in records[0]


def test_disabled_tracer_writes_nothing(tmp_path):
    tracer = Tracer(run_id="run2", directory=tmp_path, enabled=False)
    tracer.event("run_start")
    assert list(tmp_path.iterdir()) == []


def test_tracer_survives_a_location_it_cannot_write_to(tmp_path):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("I am a file, so nothing can be created inside me")
    tracer = Tracer(run_id="run3", directory=blocker)      # must not raise
    tracer.event("run_start")                              # must not raise either


def test_tracer_can_save_values_json_does_not_know(tmp_path):
    from datetime import datetime
    tracer = Tracer(run_id="run4", directory=tmp_path)
    tracer.event("odd", when=datetime(2026, 10, 1), things={1, 2})
    assert (tmp_path / "run4.jsonl").read_text(encoding="utf-8").strip() != ""
