from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from nimbus.backend.seed import BASE_TIME
from nimbus.rag.chunking import Chunk
from nimbus.rag.retrieval import Retriever

KS = (1, 3, 5)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: str
    sections: list[str] = Field(min_length=1)
    version: int | None = None


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    answers: list[Answer] = Field(min_length=1)
    as_of: date = BASE_TIME.date()
    language: Literal["en", "pt"] = "en"


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = [RetrievalCase.model_validate(item) for item in raw["cases"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate retrieval case ids")
    return cases


def _found(chunks: list[Chunk], answer: Answer) -> set[str]:
    return {
        section
        for chunk in chunks
        if chunk.policy_id == answer.policy and answer.version in (None, chunk.version)
        for section in chunk.sections
        if section in answer.sections
    }


def recall_at_k(ranked: list[Chunk], case: RetrievalCase, k: int) -> float:
    return max(len(_found(ranked[:k], answer)) / len(answer.sections) for answer in case.answers)


def reciprocal_rank(ranked: list[Chunk], case: RetrievalCase) -> float:
    for rank, chunk in enumerate(ranked, start=1):
        if any(_found([chunk], answer) for answer in case.answers):
            return 1 / rank
    return 0.0


def score_case(ranked: list[Chunk], case: RetrievalCase) -> dict[str, float]:
    scores = {f"recall@{k}": recall_at_k(ranked, case, k) for k in KS}
    scores["mrr"] = reciprocal_rank(ranked, case)
    return scores


def search_all(retriever: Retriever, cases: list[RetrievalCase]) -> list[list[Chunk]]:
    return [retriever.search(case.question, max(KS), case.as_of) for case in cases]


def evaluate(retriever: Retriever, cases: list[RetrievalCase]) -> dict[str, float]:
    return [
        score_case(ranked, case)
        for ranked, case in zip(search_all(retriever, cases), cases, strict=True)
    ]


def average(scores: list[dict[str, float]]) -> dict[str, float]:
    return {name: sum(score[name] for score in scores) / len(scores) for name in scores[0]}
