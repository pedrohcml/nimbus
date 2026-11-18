from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

POLICIES_DIR = Path("policies")


class PolicyDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    version: int
    effective_from: date
    text: str
    source: str


def parse_policy(raw: str, source: str) -> PolicyDoc:
    pieces = raw.split("---\n", 2)
    if len(pieces) != 3 or pieces[0] != "":
        raise ValueError(f"{source}: missing header")
    header = yaml.safe_load(pieces[1]) or {}
    return PolicyDoc(**header, text=pieces[2].strip(), source=source)


def load_policies(folder: Path = POLICIES_DIR) -> list[PolicyDoc]:
    docs = [
        parse_policy(p.read_text(encoding="utf-8"), p.name) for p in sorted(folder.glob("*.md"))
    ]
    seen: set[tuple[str, int]] = set()
    for doc in docs:
        key = (doc.id, doc.version)
        if key in seen:
            raise ValueError(f"duplicate policy {doc.id} version {doc.version}")
        seen.add(key)
    return docs


def in_effect(docs: list[PolicyDoc], on: date) -> list[PolicyDoc]:
    current: dict[str, PolicyDoc] = {}
    for doc in docs:
        if doc.effective_from > on:
            continue
        if doc.id not in current or doc.effective_from > current[doc.id].effective_from:
            current[doc.id] = doc
    return sorted(current.values(), key=lambda d: d.id)
