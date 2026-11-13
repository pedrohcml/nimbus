import json
from pathlib import Path
from typing import Any


def write_trace(path: str | Path, events: list[dict[str, Any]]) -> None:
    """Append events to a JSON lines file as one event per line"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for event in events:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]
