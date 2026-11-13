from nimbus.agent.trace import read_trace, write_trace


def test_write_trace_appends_json_lines(tmp_path):
    events = [{"type": "turn_start", "user_text": "hello"}, {"type": "turn_end", "answer": "ok"}]
    path = tmp_path / "traces" / "conv-1.jsonl"
    write_trace(path, events)
    write_trace(path, events)
    assert read_trace(path) == events + events


def test_write_trace_keeps_accents_readable(tmp_path):
    path = tmp_path / "conv-1.jsonl"
    write_trace(path, [{"text": "this café is nice"}])
    assert "café" in path.read_text(encoding="utf-8")
