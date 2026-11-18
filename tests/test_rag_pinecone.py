from datetime import date
from types import SimpleNamespace

from nimbus.rag.chunking import Chunk
from nimbus.rag.pinecone_store import PineconeRetriever, to_document

TODAY = date(2026, 1, 15)


def chunk(chunk_id, policy, version=1, effective_from=date(2025, 3, 1)):
    return Chunk(
        id=chunk_id,
        policy_id=policy,
        version=version,
        effective_from=effective_from,
        sections=("s",),
        text=f"text of {chunk_id}",
    )


CHUNKS = [
    chunk("fees@v1#card-fees", "fees"),
    chunk("refunds@v1#approval", "refunds"),
    chunk("refunds@v2#approval", "refunds", version=2, effective_from=date(2025, 11, 1)),
]


class FakeIndex:
    def __init__(self, ids):
        self.calls = []
        self.documents = SimpleNamespace(search=self._search)
        self._ids = ids

    def _search(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(matches=[SimpleNamespace(id=i, score=1.0) for i in self._ids])


def test_document_carries_text_and_version_key():
    document = to_document(CHUNKS[2])
    assert document["_id"] == "refunds@v2#approval"
    assert document["chunk_text"] == "text of refunds@v2#approval"
    assert document["policy_version"] == "refunds@v2"


def test_search_filters_by_versions_in_effect():
    index = FakeIndex([])
    PineconeRetriever(index, "section", CHUNKS).search("limit?", k=3, on=TODAY)
    call = index.calls[0]
    assert call["namespace"] == "section"
    assert call["top_k"] == 3
    assert call["filter"] == {"policy_version": {"$in": ["fees@v1", "refunds@v2"]}}


def test_search_returns_chunks_pinecone_order():
    index = FakeIndex(["refunds@v2#approval", "fees@v1#card-fees"])
    result = PineconeRetriever(index, "section", CHUNKS).search("q", k=2, on=TODAY)
    assert [c.id for c in result] == ["refunds@v2#approval", "fees@v1#card-fees"]


def test_unknown_id_igonred():
    index = FakeIndex(["old@v9#gone", "fees@v1#card-fees"])
    result = PineconeRetriever(index, "section", CHUNKS).search("q", k=2, on=TODAY)
    assert [c.id for c in result] == ["fees@v1#card-fees"]


def test_no_policy_in_effect_means_no_call():
    index = FakeIndex(["fees@v1#card-fees"])
    result = PineconeRetriever(index, "section", CHUNKS).search("q", k=2, on=date(2024, 1, 1))
    assert result == []
    assert index.calls == []
