from datetime import date
from pathlib import Path

from nimbus.rag.chunking import Chunk, chunk_all, chunk_by_section
from nimbus.rag.corpus import load_policies
from nimbus.rag.evaluation import (
    Answer,
    RetrievalCase,
    average,
    evaluate,
    load_retrieval_cases,
    recall_at_k,
    reciprocal_rank,
)

CASE = RetrievalCase(
    id="q",
    question="?",
    answers=[Answer(policy="refunds", sections=["approval", "partial-refunds"])],
)


class FixedRetriever:
    def __init__(self, ranked):
        self.ranked = ranked
        self.calls = 0

    def search(self, query, k, on):
        self.calls += 1
        return self.ranked


def chunk(policy, *sections, version=2):
    return Chunk(
        id="x",
        policy_id=policy,
        version=version,
        effective_from=date(2025, 11, 1),
        sections=sections,
        text="",
    )


def text_recall_counts_expected_sections_found():
    ranked = [
        chunk("fees", "card-fees"),
        chunk("refunds", "approval"),
        chunk("refunds", "partial-refunds"),
    ]
    assert recall_at_k(ranked, CASE, 1) == 0
    assert recall_at_k(ranked, CASE, 2) == 0.5
    assert recall_at_k(ranked, CASE, 3) == 1


def test_reciprocal_rank_uses_first_hit():
    ranked = [chunk("fees", "card-fees"), chunk("refunds", "approval")]
    assert reciprocal_rank(ranked, CASE) == 0.5
    assert reciprocal_rank(ranked[:1], CASE) == 0


def test_same_action_another_policy_doesnt_count():
    assert recall_at_k([chunk("disputes", "approval")], CASE, 1) == 0


def test_wrong_version_doesnt_count():
    case = RetrievalCase(
        id="q", question="?", answers=[Answer(policy="refunds", sections=["approval"], version=1)]
    )
    assert recall_at_k([chunk("refunds", "approval", version=2)], case, 1) == 0


def test_shipped_cases_point_real_sections():
    cases = load_retrieval_cases(Path("evals/retrieval/v1.yaml"))
    chunks = chunk_all(load_policies(), chunk_by_section)
    known = {(c.policy_id, section) for c in chunks for section in c.sections}
    for case in cases:
        for answer in case.answers:
            for section in answer.sections:
                assert (answer.policy, section) in known, f"{case.id}: {answer.policy}/{section}"


def test_evaluate_searches_once_per_case():
    retriever = FixedRetriever([chunk("refunds", "approval")])
    scores = evaluate(retriever, [CASE, CASE])
    assert retriever.calls == 2
    assert scores[0]["recall@1"] == 0.5


def test_average_over_cases():
    assert average([{"mrr": 1.0}, {"mrr": 0.0}]) == {"mrr": 0.5}


def test_any_accepted_answer_counts():
    case = RetrievalCase(
        id="q",
        question="?",
        answers=[
            Answer(policy="refunds", sections=["approval"]),
            Answer(policy="faq", sections=["why-is-my-refund-under-review"]),
        ],
    )
    ranked = [chunk("fees", "card-fees"), chunk("faq", "why-is-my-refund-under-review")]
    assert recall_at_k(ranked, case, 1) == 0
    assert recall_at_k(ranked, case, 2) == 1
    assert reciprocal_rank(ranked, case) == 0.5
