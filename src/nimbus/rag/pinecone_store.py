import time
from datetime import date
from typing import Any

from pinecone import Pinecone, SchemaBuilder

from nimbus.agent.settings import pinecone_api_key
from nimbus.rag.chunking import Chunk, chunk_all, chunk_by_section
from nimbus.rag.corpus import load_policies
from nimbus.rag.retrieval import current_versions

INDEX_NAME = "nimbus-policies"
TEXT_FIELD = "chunk_text"
EMBED_MODEL = "multilingual-e5-large"
UPSERT_BATCH = 90
INDEXING_WAIT_S = 10


def version_key(policy_id: str, version: int) -> str:
    return f"{policy_id}@v{version}"


def to_document(chunk: Chunk) -> dict[str, Any]:
    return {
        "_id": chunk.id,
        TEXT_FIELD: chunk.text,
        "policy_version": version_key(chunk.policy_id, chunk.version),
    }


def open_client() -> Any:
    return Pinecone(api_key=pinecone_api_key())


def open_index(name: str = INDEX_NAME) -> Any:
    return open_client().index(name=name)


def ensure_index(name: str = INDEX_NAME) -> None:
    pc = Pinecone(api_key=pinecone_api_key())
    if pc.indexes.exists(name=name):
        return
    schema = SchemaBuilder().add_string_field(name=TEXT_FIELD, embed={"model": EMBED_MODEL}).build()
    pc.indexes.create(name=name, schema=schema)
    while not pc.indexes.describe(name=name).status.ready:
        time.sleep(2)


def ingest(index: Any, namespace: str, chunks: list[Chunk]) -> None:
    documents = [to_document(chunk) for chunk in chunks]
    for start in range(0, len(documents), UPSERT_BATCH):
        index.documents.upsert(
            namespace=namespace, documents=documents[start : start + UPSERT_BATCH]
        )


class PineconeRetriever:
    def __init__(self, index: Any, namespace: str, chunks: list[Chunk]) -> None:
        self.index = index
        self.namespace = namespace
        self.chunks = chunks
        self.by_id = {chunk.id: chunk for chunk in chunks}

    def search(self, query: str, k: int, on: date) -> list[Chunk]:
        allowed = current_versions(self.chunks, on)
        if not allowed:
            return []
        response = self.index.documents.search(
            namespace=self.namespace,
            top_k=k,
            score_by=[{"type": "embed", "fields": [TEXT_FIELD], "query": query}],
            filter={"policy_version": {"$in": sorted(version_key(p, v) for p, v in allowed)}},
        )
        return [self.by_id[match.id] for match in response.matches if match.id in self.by_id]


def policy_retriever() -> PineconeRetriever:
    chunks = chunk_all(load_policies(), chunk_by_section)
    return PineconeRetriever(open_index(), "section", chunks)
