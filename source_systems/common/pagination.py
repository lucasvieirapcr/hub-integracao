"""Paginação por cursor ordenada por (updated_at, chave)."""

from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from source_systems.common.db import to_iso


class InvalidCursorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Cursor:
    updated_at: str
    key: str


def encode_cursor(cursor: Cursor) -> str:
    raw = json.dumps({"u": cursor.updated_at, "k": cursor.key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(text: str) -> Cursor:
    try:
        padded = text + "=" * (-len(text) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return Cursor(updated_at=str(data["u"]), key=str(data["k"]))
    except (binascii.Error, ValueError, KeyError, TypeError) as error:
        raise InvalidCursorError("cursor inválido") from error


@dataclass(frozen=True, slots=True)
class Page:
    rows: list[sqlite3.Row]
    next_cursor: str | None


def fetch_page(
    conn: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    limit: int,
    cursor: str | None,
    updated_since: datetime | None,
) -> Page:
    """Lê uma página ordenada por (updated_at, chave). `table` e `key_column` são constantes."""
    where: list[str] = []
    params: list[Any] = []
    if updated_since is not None:
        where.append("updated_at >= ?")
        params.append(to_iso(updated_since))
    if cursor:
        position = decode_cursor(cursor)
        where.append(f"(updated_at > ? or (updated_at = ? and {key_column} > ?))")
        params.extend([position.updated_at, position.updated_at, position.key])
    sql = f"select * from {table}"  # noqa: S608 (nomes fixos no código)
    if where:
        sql += " where " + " and ".join(where)
    sql += f" order by updated_at, {key_column} limit ?"
    params.append(limit + 1)  # um a mais para saber se existe próxima página

    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more:
        last = rows[-1]
        next_cursor = encode_cursor(Cursor(last["updated_at"], str(last[key_column])))
    return Page(rows, next_cursor)
