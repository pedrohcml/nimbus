from pathlib import Path

import pytest

from nimbus.router.intents import (
    Intent,
    IntentExample,
    fingerprint,
    load_examples,
    overlap,
)


def write_lines(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def example(text: str, intent: Intent = Intent.REFUND) -> IntentExample:
    return IntentExample(text=text, intent=intent, language="en", source="handwritten")


def test_loads_examples_from_jsonl(tmp_path):
    path = write_lines(
        tmp_path / "test.jsonl",
        '{"text": "I want my money back", "intent": "refund", '
        '"language": "en", "source": "handwritten"}',
        '{"text": "cadê meu saque?", "intent": "transaction_status", '
        '"language": "pt", "source": "handwritten"}',
    )

    examples = load_examples(path)

    assert [e.intent for e in examples] == [Intent.REFUND, Intent.TRANSACTION_STATUS]
    assert examples[1].language == "pt"


def test_skips_blank_lines(tmp_path):
    path = write_lines(
        tmp_path / "test.jsonl",
        '{"text": "hi", "intent": "smalltalk", "language": "en", "source": "handwritten"}',
        '{"text": "hi", "intent": "greeting", "language": "en", "source": "handwritten"}',
    )

    with pytest.raises(ValueError, match="test.jsonl, line 2"):
        load_examples(path)


def test_rejects_unknown_fields(tmp_path):
    path = write_lines(
        tmp_path / "test.jsonl",
        '{"text": "hi", "intent": "smalltalk", "language": "en", '
        '"source": "handwritten", "label": "x"}',
    )

    with pytest.raises(ValueError):
        load_examples(path)


def test_fingerprint_ignores_case_punctuation_and_spaces():
    assert fingerprint("Cadê  meu SAQUE?!") == fingerprint("cadê meu saque")


def test_overlap_finds_same_text_in_two_splits():
    train = [example("I want my money back"), example("refund please")]
    test = [example("I want my money back!"), example("where is my withdrawal")]

    assert overlap(train, test) == {"i want my money back"}
