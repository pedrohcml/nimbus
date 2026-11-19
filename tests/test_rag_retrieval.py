from datetime import date

from nimbus.rag.chunking import Chunk
from nimbus.rag.retrieval import BM25Retriever, HybridRetriever, tokenize

TODAY = date(2026, 1, 15)


def chunk(chunk_id, policy, section, text, version=1, effective_from=date(2025, 3, 1)):
    return Chunk(
        id=chunk_id,
        policy_id=policy,
        version=version,
        effective_from=effective_from,
        sections=(section,),
        text=text,
    )


CHUNKS = [
    chunk("fees#card", "fees", "card-fees", "The card issuance fee is R$ 15.00"),
    chunk(
        "withdrawals#delays", "withdrawals", "delays", "Confirming for more than 2 hours is delayed"
    ),
    chunk("refunds@v1#approval", "refunds", "approval", "Approved automatically up to R$ 300.00"),
    chunk(
        "refunds@v2#approval",
        "refunds",
        "approval",
        "Approved automatically up to R$ 500.00",
        version=2,
        effective_from=date(2025, 11, 1),
    ),
]


class FixedRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.asked_k = None

    def search(self, query, k, on):
        self.asked_k = k
        return self.chunks[:k]


A, B, C = (chunk(f"x#{name}", "x", name, name) for name in "abc")


def test_tokenize_lowercases_and_splits_on_symbols():
    assert tokenize("Não, R$ 500.00!") == ["não", "r", "500", "00"]


def test_bm25_finds_the_matching_chunk():
    top = BM25Retriever(CHUNKS).search("card issuance fee", k=1, on=TODAY)
    assert [c.id for c in top] == ["fees#card"]


def test_search_uses_version_in_effect():
    retriever = BM25Retriever(CHUNKS)

    def ids(on):
        return [c.id for c in retriever.search("approved 300 500", k=4, on=on)]

    assert "refunds@v2#approval" in ids(TODAY)
    assert "refunds@v1#approval" not in ids(TODAY)
    assert "refunds@v1#approval" in ids(date(2025, 6, 1))
    assert "refunds@v2#approval" not in ids(date(2025, 6, 1))


def test_search_returns_at_most_k():
    assert len(BM25Retriever(CHUNKS).search("card fee hours delayed", k=1, on=TODAY)) == 1


def test_tokenize_drops_stopwords():
    assert tokenize("How long does my refund take?") == ["long", "refund"]
    tokens = tokenize("Quanto custa o cartão?")
    assert "o" not in tokens
    assert "cartão" in tokens


def test_tokenize_keeps_negations():
    assert "não" in tokenize("Não recebi o cartão")
    assert "not" in tokenize("I did not get it")


def test_no_shared_word_means_no_result():
    assert BM25Retriever(CHUNKS).search("adasd", k=3, on=TODAY) == []


def test_rrf_rewards_chunks_found_by_both():
    hybrid = HybridRetriever([FixedRetriever([A, B]), FixedRetriever([C, B])])
    assert [c.id for c in hybrid.search("q", k=3, on=TODAY)] == ["x#b", "x#a", "x#c"]


def test_empty_list_keeps_other_order():
    hybrid = HybridRetriever([FixedRetriever([]), FixedRetriever([A, B])])
    assert [c.id for c in hybrid.search("q", k=3, on=TODAY)] == ["x#a", "x#b"]


def test_hybrid_returns_at_most_k():
    hybrid = HybridRetriever([FixedRetriever([A, B]), FixedRetriever([C])])
    assert len(hybrid.search("q", k=1, on=TODAY)) == 1


def test_hybrid_asks_each_retriever_for_its_depth():
    first, second = FixedRetriever([A]), FixedRetriever([B])
    HybridRetriever([first, second], depth=20).search("q", k=5, on=TODAY)
    assert first.asked_k == second.asked_k == 20
