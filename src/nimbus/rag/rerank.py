import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from nimbus.rag.chunking import Chunk
from nimbus.rag.retrieval import Retriever

RERANK_MODEL = "bge-reranker-v2-m3"
RERANK_DEPTH = 20
CACHE_PATH = Path(".cache/rerank.json")


class Reranker(Protocol):
    def rank(self, query: str, texts: list[str]) -> list[int]: ...


class PineconeReranker:
    def __init__(self, client: Any, model: str = RERANK_MODEL) -> None:
        self.client = client
        self.model = model

    def rank(self, query: str, texts: list[str]) -> list[int]:
        result = self.client.inference.rerank(
            model=self.model,
            query=query,
            documents=texts,
            top_n=len(texts),
            return_documents=False,
        )
        return [item.index for item in result.data]


class CachedReranker:
    def __init__(self, inner: Reranker, path: Path = CACHE_PATH, model: str = RERANK_MODEL) -> None:
        self.inner = inner
        self.path = path
        self.model = model
        self.cache: dict[str, list[int]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def rank(self, query: str, texts: list[str]) -> list[int]:
        key = hashlib.sha256(json.dumps([self.model, query, texts]).encode("utf-8")).hexdigest()
        if key not in self.cache:
            self.cache[key] = self.inner.rank(query, texts)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache), encoding="utf-8")
        return self.cache[key]


class RerankingRetriever:
    def __init__(self, base: Retriever, reranker: Reranker, depth: int = RERANK_DEPTH) -> None:
        self.base = base
        self.reranker = reranker
        self.depth = depth

    def search(self, query: str, k: int, on: date) -> list[Chunk]:
        candidates = self.base.search(query, self.depth, on)
        if not candidates:
            return []
        order = self.reranker.rank(query, [chunk.text for chunk in candidates])
        return [candidates[i] for i in order[:k]]
