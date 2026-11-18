from datetime import date

from nimbus.rag.chunking import Chunk
from nimbus.rag.retrieval import BM25Retriever, tokenize

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


def test_tokenize_lowercases_and_splits_on_symbols():
    assert tokenize("Não, R$ 500.00!") == ["não", "r", "500", "00"]


def test_bm25_finds_the_matching_chunk():
    top = BM25Retriever(CHUNKS).search("card issuance fee", k=1, on=TODAY)
    assert [c.id for c in top] == ["fees#card"]


def test_search_uses_the_version_in_effect():
    retriever = BM25Retriever(CHUNKS)

    def ids(on):
        return [c.id for c in retriever.search("approved automatically", k=4, on=on)]

    assert "refunds@v2#approval" in ids(TODAY)
    assert "refunds@v1#approval" not in ids(TODAY)
    assert "refunds@v1#approval" in ids(date(2025, 6, 1))
    assert "refunds@v2#approval" not in ids(date(2025, 6, 1))


def test_search_returns_at_most_k():
    assert len(BM25Retriever(CHUNKS).search("fee", k=2, on=TODAY)) == 2
