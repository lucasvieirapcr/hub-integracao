"""Persistência SQLite das APIs simuladas (um arquivo por sistema)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def to_iso(moment: datetime) -> str:
    """UTC com tamanho fixo, para a ordenação textual ser cronológica."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def from_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


class Database:
    def __init__(self, path: Path, schema: str) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(schema)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Uma conexão por uso; commit no fim do bloco, rollback se der erro."""
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL: leitura concorrente com escrita
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        try:
            with conn:
                yield conn
        finally:
            conn.close()
