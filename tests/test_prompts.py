from datetime import UTC, datetime

from nimbus.agent.prompts import build_system_prompt


def test_system_prompt_includes_current_date():
    prompt = build_system_prompt(datetime(2026, 1, 15, 12, 0, tzinfo=UTC))
    assert "2026-01-15" in prompt


def test_system_prompt_has_no_unfilled_placeholders():
    prompt = build_system_prompt(datetime(2026, 1, 15, 12, 0, tzinfo=UTC))
    assert "{" not in prompt and "}" not in prompt
