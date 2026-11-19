import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nimbus.backend.seed import CUSTOMER_MAIN, SCENARIO_IDS

_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

Category = Literal["lookup", "actions", "security", "scope", "escalation", "language", "policy"]


class _Strict(BaseModel):
    """Unknown keys are errors, so a typo in the yaml never disables a check silently"""

    model_config = ConfigDict(extra="forbid")


class TurnExpect(_Strict):
    tools_called: list[str] = Field(default_factory=list)
    tools_not_called: list[str] = Field(default_factory=list)
    tool_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    answer_matches_any: list[str] = Field(default_factory=list)
    answer_matches_none: list[str] = Field(default_factory=list)


class Turn(_Strict):
    model_config = ConfigDict(extra="forbid")

    user: str
    expect: TurnExpect = Field(default_factory=TurnExpect)
    language: Literal["en", "pt"] | None = None


class DbCheck(_Strict):
    query: str
    equals: int

    @field_validator("query")
    @classmethod
    def must_be_read_only(cls, value: str) -> str:
        if not value.strip().lower().startswith("select"):
            raise ValueError("db checks must be read-only select queries")
        return value


class EvalCase(_Strict):
    id: str
    category: Category
    description: str = ""
    customer: str = CUSTOMER_MAIN
    approval_threshold_minor: int | None = None
    turns: list[Turn] = Field(min_length=1)
    db: list[DbCheck] = Field(default_factory=list)
    language: Literal["en", "pt"] = "en"


def resolve_placeholders(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(f"unknown placeholder {{{name}}}")
        return values[name]

    return _PLACEHOLDER.sub(replace, text)


def load_dataset(path: str | Path, values: dict[str, str] = SCENARIO_IDS) -> list[EvalCase]:
    text = resolve_placeholders(Path(path).read_text(encoding="utf-8"), values)
    raw = yaml.safe_load(text)
    cases = [EvalCase.model_validate(item) for item in raw["cases"]]

    ids = [case.id for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids: {duplicates}")
    return cases
