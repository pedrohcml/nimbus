from collections import Counter

import pytest

from nimbus.router.intents import INTENTS_DIR, Intent, fingerprint, load_examples

MIN_PER_GROUP = 5


@pytest.fixture(scope="module")
def examples():
    return load_examples(INTENTS_DIR / "test.jsonl")


def test_every_intent_has_examples_in_both_languages(examples):
    counts = Counter((e.intent, e.language) for e in examples)
    missing = [
        (intent.value, language, counts[(intent, language)])
        for intent in Intent
        for language in ("en", "pt")
        if counts[(intent, language)] < MIN_PER_GROUP
    ]
    assert missing == []


def test_no_duplicate_texts(examples):
    counts = Counter(fingerprint(e.text) for e in examples)
    assert [text for text, n in counts.items() if n > 1] == []
