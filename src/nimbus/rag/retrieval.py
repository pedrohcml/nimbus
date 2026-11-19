import re
from datetime import date
from typing import Protocol

from rank_bm25 import BM25Okapi
from spacy.lang.en.stop_words import STOP_WORDS as EN_STOP_WORDS
from spacy.lang.pt.stop_words import STOP_WORDS as PT_STOP_WORDS

from nimbus.rag.chunking import Chunk

KEEP = {"not", "no", "nor", "never", "não", "nunca"}
STOP_WORDS = frozenset(EN_STOP_WORDS | PT_STOP_WORDS) - KEEP


class Retriever(Protocol):
    def search(self, query: str, k: int, on: date) -> list[Chunk]: ...


def tokenize(text: str) -> list[str]:
    return [word for word in re.findall(r"\w+", text.lower()) if word not in STOP_WORDS]


def current_versions(chunks: list[Chunk], on: date) -> set[tuple[str, int]]:
    best: dict[str, Chunk] = {}
    for chunk in chunks:
        if chunk.effective_from > on:
            continue
        if (
            chunk.policy_id not in best
            or chunk.effective_from > best[chunk.policy_id].effective_from
        ):
            best[chunk.policy_id] = chunk
    return {(chunk.policy_id, chunk.version) for chunk in best.values()}


class BM25Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.index = BM25Okapi([tokenize(chunk.text) for chunk in chunks])

    def search(self, query: str, k: int, on: date) -> list[Chunk]:
        scores = self.index.get_scores(tokenize(query))
        allowed = current_versions(self.chunks, on)
        candidates = [
            i
            for i, chunk in enumerate(self.chunks)
            if (chunk.policy_id, chunk.version) in allowed and scores[i] > 0
        ]
        candidates.sort(key=lambda i: scores[i], reverse=True)
        return [self.chunks[i] for i in candidates[:k]]
