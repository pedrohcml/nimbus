from datetime import date
from types import SimpleNamespace

from nimbus.rag.chunking import Chunk
from nimbus.rag.rerank import CachedReranker, PineconeReranker, RerankingRetriever

TODAY = date(2026, 1, 15)


def chunk(name):
    return Chunk(
        id=f"x#{name}",
        policy_id="x",
        version=1,
        effective_from=date(2025, 3, 1),
        sections=(name,),
        text=f"text {name}",
    )


A, B, C = chunk("a"), chunk("b"), chunk("c")


class FixedRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.asked_k = None

    def search(self, query, k, on):
        self.asked_k = k
        return self.chunks[:k]


class FixedReranker:
    def __init__(self, order):
        self.order = order
        self.calls = []

    def rank(self, query, texts):
        self.calls.append((query, texts))
        return self.order


def test_reranking_reorders_candidates():
    retriever = RerankingRetriever(FixedRetriever([A, B, C]), FixedReranker([2, 0, 1]))
    assert [c.id for c in retriever.search("q", k=3, on=TODAY)] == ["x#c", "x#a", "x#b"]
    assert [c.id for c in retriever.search("q", k=2, on=TODAY)] == ["x#c", "x#a"]


def test_reranking_asks_base_for_depth():
    base = FixedRetriever([A])
    RerankingRetriever(base, FixedReranker([0]), depth=20).search("q", k=5, on=TODAY)
    assert base.asked_k == 20


def test_no_candidates_means_no_rerank_call():
    reranker = FixedReranker([])
    assert RerankingRetriever(FixedRetriever([]), reranker).search("q", k=5, on=TODAY) == []
    assert reranker.calls == []


def test_pinecone_reranker_returns_indexed_ranked_order():
    calls = []

    def rerank(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(index=1, score=0.9), SimpleNamespace(index=0, score=0.1)]
        )

    client = SimpleNamespace(inference=SimpleNamespace(rerank=rerank))
    assert PineconeReranker(client).rank("q", ["first", "second"]) == [1, 0]
    assert calls[0]["model"] == "bge-reranker-v2-m3"
    assert calls[0]["documents"] == ["first", "second"]


def test_cache_calls_reranker_once_and_survives_restarts(tmp_path):
    inner = FixedReranker([1, 0])
    path = tmp_path / "rerank.json"
    first = CachedReranker(inner, path)
    assert first.rank("q", ["a", "b"]) == [1, 0]
    assert first.rank("q", ["a", "b"]) == [1, 0]
    assert len(inner.calls) == 1

    second = CachedReranker(inner, path)
    assert second.rank("q", ["a", "b"]) == [1, 0]
    assert len(inner.calls) == 1

    second.rank("other question", ["a", "b"])
    assert len(inner.calls) == 2
