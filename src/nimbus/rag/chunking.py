import re
from collections.abc import Callable
from datetime import date

from pydantic import BaseModel, ConfigDict

from nimbus.rag.corpus import PolicyDoc

WINDOW_SIZE = 60
WINDOW_OVERLAP = 15


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    policy_id: str
    version: int
    effective_from: date
    sections: tuple[str, ...]
    text: str


Chunker = Callable[[PolicyDoc], list[Chunk]]


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def split_sections(doc: PolicyDoc) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    for line in doc.text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif line.startswith("# "):
            continue
        elif sections:
            sections[-1][1].append(line)
        elif line.strip():
            raise ValueError(f"{doc.source}: text before the first section")
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections]


def _chunk(doc: PolicyDoc, suffix: str, sections: tuple[str, ...], text: str) -> Chunk:
    return Chunk(
        id=f"{doc.id}@v{doc.version}#{suffix}",
        policy_id=doc.id,
        version=doc.version,
        effective_from=doc.effective_from,
        sections=sections,
        text=text,
    )


def chunk_by_section(doc: PolicyDoc) -> list[Chunk]:
    return [
        _chunk(doc, slug(heading), (slug(heading),), f"{doc.title} - {heading}\n\n{body}")
        for heading, body in split_sections(doc)
    ]


def chunk_by_window(
    doc: PolicyDoc, size: int = WINDOW_SIZE, overlap: int = WINDOW_OVERLAP
) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("overlap must be at least 0 and smaller than size")
    words: list[tuple[str, str]] = []
    for heading, body in split_sections(doc):
        words += [(word, slug(heading)) for word in f"{heading}. {body}".split()]

    chunks = []
    step = size - overlap
    for n, start in enumerate(range(0, len(words), step)):
        window = words[start : start + size]
        sections = tuple(dict.fromkeys(section for _, section in window))
        text = f"{doc.title}\n\n" + " ".join(word for word, _ in window)
        chunks.append(_chunk(doc, f"w{n}", sections, text))
        if start + size >= len(words):
            break
    return chunks


def chunk_all(docs: list[PolicyDoc], chunker: Chunker) -> list[Chunk]:
    chunks = [chunk for doc in docs for chunk in chunker(doc)]
    ids = [chunk.id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate chunk ids")
    return chunks
