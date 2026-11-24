import re
import unicodedata
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

INTENTS_DIR = Path(__file__).resolve().parents[3] / "data" / "intents"


class Intent(StrEnum):
    TRANSACTION_STATUS = "transaction_status"
    DISPUTE = "dispute"
    REFUND = "refund"
    POLICY_QUESTION = "policy_question"
    HUMAN = "human"
    SMALLTALK = "smalltalk"
    OUT_OF_SCOPE = "out_of_scope"


class IntentExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=500)
    intent: Intent
    language: Literal["en", "pt"]
    source: Literal["handwritten", "eval_v0", "generated"]


def load_examples(path: Path) -> list[IntentExample]:
    examples = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            examples.append(IntentExample.model_validate_json(line))
        except ValidationError as error:
            raise ValueError(f"{path.name}, line {number}: {error}") from error
    return examples


def fingerprint(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"\w+", text))


def overlap(a: Iterable[IntentExample], b: Iterable[IntentExample]) -> set[str]:
    return {fingerprint(e.text) for e in a} & {fingerprint(e.text) for e in b}
