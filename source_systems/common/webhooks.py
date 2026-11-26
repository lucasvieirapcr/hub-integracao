"""Outbox de webhooks com assinatura HMAC (X-Signature: t=...,v1=...) e reenvio com backoff."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from simulator.chaos import ApiChaos, ChaosLedger
from source_systems.common.db import Database, to_iso

OUTBOX_SCHEMA = """
create table if not exists webhook_outbox (
    event_id         text primary key,
    event_type       text not null,
    occurred_at      text not null,
    body             text not null,
    status           text not null default 'PENDING',  -- PENDING, DELIVERED, FAILED
    attempts         integer not null default 0,
    next_attempt_at  text not null,
    last_error       text,
    delivered_at     text
);
create index if not exists ix_webhook_outbox_due on webhook_outbox (status, next_attempt_at);
"""

BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 3600


def build_body(event_id: str, event_type: str, occurred_at: datetime, data: dict[str, Any]) -> str:
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": to_iso(occurred_at),
        "data": data,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def enqueue(
    conn: sqlite3.Connection,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    data: dict[str, Any],
    now: datetime,
) -> bool:
    """Grava o evento na outbox. Mesmo event_id duas vezes = ignorado (idempotente)."""
    cursor = conn.execute(
        """
        insert into webhook_outbox (event_id, event_type, occurred_at, body, next_attempt_at)
        values (?, ?, ?, ?, ?)
        on conflict (event_id) do nothing
        """,
        (
            event_id,
            event_type,
            to_iso(occurred_at),
            build_body(event_id, event_type, occurred_at, data),
            to_iso(now),
        ),
    )
    return cursor.rowcount == 1


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={sign(secret, timestamp, body)}"


def verify_signature(
    secret: str, header: str, body: bytes, now: int, tolerance_seconds: int = 300
) -> bool:
    """Valida o cabeçalho X-Signature e a janela de tempo."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(now - timestamp) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), parts.get("v1", ""))


@dataclass(slots=True)
class DeliveryReport:
    delivered: int = 0
    retried: int = 0
    failed: int = 0
    duplicates_sent: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class WebhookDispatcher:
    def __init__(
        self,
        db: Database,
        *,
        system: str,
        url: str,
        secret: str,
        max_attempts: int,
        http: httpx.Client,
        chaos: ApiChaos,
        ledger: ChaosLedger,
        chaos_seed: int = 0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db = db
        self.system = system
        self.url = url
        self.secret = secret
        self.max_attempts = max_attempts
        self.http = http
        self.chaos = chaos
        self.ledger = ledger
        self.clock = clock
        self._rng = random.Random(chaos_seed)
        self._lock = threading.Lock()  # serializa o loop de fundo e o /admin

    def _send(self, event_id: str, event_type: str, body: str) -> str | None:
        """Envia uma vez. Devolve None se o destino aceitou (2xx) ou a descrição do erro."""
        raw = body.encode()
        timestamp = int(self.clock().timestamp())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"distribuidora-exemplo-{self.system}/1.0",
            "X-Event-Id": event_id,
            "X-Event-Type": event_type,
            "X-Signature": signature_header(self.secret, timestamp, raw),
        }
        try:
            response = self.http.post(self.url, content=raw, headers=headers, timeout=10)
        except httpx.HTTPError as error:
            return f"{type(error).__name__}: {error}"
        if 200 <= response.status_code < 300:
            return None
        return f"HTTP {response.status_code}"

    def _backoff(self, attempts: int) -> timedelta:
        # backoff exponencial (5s até 1h) com jitter
        base = min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_MAX_SECONDS)
        return timedelta(seconds=base * self._rng.uniform(0.5, 1.0))

    def deliver_due(self, limit: int = 200) -> DeliveryReport:
        report = DeliveryReport()
        if not self.url:
            return report
        with self._lock:
            now = self.clock()
            with self.db.connect() as conn:
                rows = conn.execute(
                    """
                    select event_id, event_type, body, attempts from webhook_outbox
                     where status = 'PENDING' and next_attempt_at <= ?
                     order by occurred_at, event_id
                     limit ?
                    """,
                    (to_iso(now), limit),
                ).fetchall()
            batch = list(rows)
            if len(batch) > 1 and self.chaos.out_of_order.fires(self._rng):
                self._rng.shuffle(batch)
                self.ledger.record("out_of_order_batch", event_ids=[r["event_id"] for r in batch])

            for row in batch:
                error = self._send(row["event_id"], row["event_type"], row["body"])
                attempts = row["attempts"] + 1
                with self.db.connect() as conn:
                    if error is None:
                        conn.execute(
                            "update webhook_outbox set status = 'DELIVERED', attempts = ?, delivered_at = ?,"
                            " last_error = null where event_id = ?",
                            (attempts, to_iso(self.clock()), row["event_id"]),
                        )
                        report.delivered += 1
                    elif attempts >= self.max_attempts:
                        conn.execute(
                            "update webhook_outbox set status = 'FAILED', attempts = ?, last_error = ? where event_id = ?",
                            (attempts, error, row["event_id"]),
                        )
                        report.failed += 1
                    else:
                        conn.execute(
                            "update webhook_outbox set attempts = ?, last_error = ?, next_attempt_at = ? where event_id = ?",
                            (
                                attempts,
                                error,
                                to_iso(self.clock() + self._backoff(attempts)),
                                row["event_id"],
                            ),
                        )
                        report.retried += 1
                if error is None and self.chaos.duplicate_events.fires(self._rng):
                    self._send(row["event_id"], row["event_type"], row["body"])
                    self.ledger.record("duplicate_event", event_id=row["event_id"])
                    report.duplicates_sent += 1
        return report

    def stats(self) -> dict[str, int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "select status, count(*) as total from webhook_outbox group by status"
            ).fetchall()
        counts = {"PENDING": 0, "DELIVERED": 0, "FAILED": 0}
        counts.update({row["status"]: row["total"] for row in rows})
        return counts
