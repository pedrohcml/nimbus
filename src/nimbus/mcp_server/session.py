import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Session:
    """Who is being served. Set by the server and never by the model."""

    conn: sqlite3.Connection
    customer_id: str
    conversation_id: str
    clock: Callable[[], datetime]
