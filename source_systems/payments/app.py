"""API do gateway de pagamento. Eventos approved/declined/refunded são enviados por webhook.

uvicorn --factory source_systems.payments.app:create_app
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field

from simulator.chaos import ChaosLedger, load_chaos_config
from source_systems.common.app import PageOut, UpsertResult, create_base_app
from source_systems.common.db import Database, to_iso
from source_systems.common.guard import ApiGuard
from source_systems.common.pagination import fetch_page
from source_systems.common.settings import PaymentsSettings
from source_systems.common.webhooks import OUTBOX_SCHEMA, WebhookDispatcher, enqueue

SCHEMA = (
    """
create table if not exists payments (
    payment_id    text primary key,
    order_ref     text not null,
    amount_cents  integer not null,
    method        text not null,
    status        text not null,
    created_at    text not null,
    updated_at    text not null
);
create index if not exists ix_payments_updated on payments (updated_at, payment_id);
create index if not exists ix_payments_order_ref on payments (order_ref);

create table if not exists payment_events (
    event_id     text primary key,
    payment_id   text not null references payments (payment_id),
    event_type   text not null,
    occurred_at  text not null
);
create index if not exists ix_payment_events_payment on payment_events (payment_id);
"""
    + OUTBOX_SCHEMA
)

EventType = Literal["payment.approved", "payment.declined", "payment.refunded"]
PaymentStatus = Literal["approved", "declined", "refunded"]
STATUS_BY_EVENT: dict[str, PaymentStatus] = {
    "payment.approved": "approved",
    "payment.declined": "declined",
    "payment.refunded": "refunded",
}


class PaymentEvent(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: AwareDatetime


class PaymentBase(BaseModel):
    payment_id: str
    order_ref: str
    amount_cents: int = Field(ge=0)
    method: Literal["PIX", "CARD", "BOLETO"]
    status: PaymentStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime


class PaymentIn(PaymentBase):
    events: list[PaymentEvent] = Field(min_length=1)


class PaymentOut(PaymentBase):
    events: list[PaymentEvent]


class PaymentBatch(BaseModel):
    payments: list[PaymentIn]
    enqueue_webhooks: bool = True


def create_app(
    settings: PaymentsSettings | None = None,
    *,
    http_client: httpx.Client | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    settings = settings or PaymentsSettings()  # valores vêm do ambiente
    chaos_config = load_chaos_config(settings.chaos_config_path)
    ledger = ChaosLedger(settings.chaos_ledger_dir, "payments")
    guard = ApiGuard(settings, chaos_config.payments, ledger, chaos_config.seed, monotonic, sleep)
    db = Database(settings.db_path, SCHEMA)
    dispatcher = WebhookDispatcher(
        db,
        system="payments",
        url=settings.webhook_url,
        secret=settings.webhook_secret.get_secret_value(),
        max_attempts=settings.webhook_max_attempts,
        http=http_client or httpx.Client(),
        chaos=chaos_config.payments,
        ledger=ledger,
        chaos_seed=chaos_config.seed,
        clock=clock,
    )
    app = create_base_app(
        title="Gateway de pagamento - Distribuidora Exemplo",
        description="Sistema simulado. Dados fictícios.",
        guard=guard,
        dispatcher=dispatcher,
        delivery_interval_seconds=settings.webhook_interval_seconds,
    )
    # Rotas /v1 exigem token de cliente válido e respeitam o limite de requisições.
    client_only = [Depends(guard.client)]

    def events_for(
        conn: sqlite3.Connection, payment_ids: list[str]
    ) -> dict[str, list[PaymentEvent]]:
        result: dict[str, list[PaymentEvent]] = {pid: [] for pid in payment_ids}
        if not payment_ids:
            return result
        marks = ",".join("?" * len(payment_ids))
        rows = conn.execute(
            f"select * from payment_events where payment_id in ({marks}) order by occurred_at, event_id",  # noqa: S608
            payment_ids,
        )
        for row in rows:
            result[row["payment_id"]].append(PaymentEvent.model_validate(dict(row)))
        return result

    @app.get("/v1/payments", tags=["pagamentos"], dependencies=client_only)
    def list_payments(
        cursor: str | None = None,
        updated_since: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> PageOut[PaymentOut]:
        with db.connect() as conn:
            page = fetch_page(
                conn,
                table="payments",
                key_column="payment_id",
                limit=min(limit, settings.max_page_size),
                cursor=cursor,
                updated_since=updated_since,
            )
            events = events_for(conn, [r["payment_id"] for r in page.rows])
        data = [
            PaymentOut.model_validate({**dict(r), "events": events[r["payment_id"]]})
            for r in page.rows
        ]
        return PageOut[PaymentOut](data=data, next_cursor=page.next_cursor)

    @app.get("/v1/payments/{payment_id}", tags=["pagamentos"], dependencies=client_only)
    def get_payment(payment_id: str) -> PaymentOut:
        with db.connect() as conn:
            row = conn.execute(
                "select * from payments where payment_id = ?", (payment_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Pagamento não encontrado")
            events = events_for(conn, [payment_id])
        return PaymentOut.model_validate({**dict(row), "events": events[payment_id]})

    @app.post("/admin/payments", tags=["admin"], dependencies=[Depends(guard.admin)])
    def load_payments(batch: PaymentBatch) -> UpsertResult:
        """Grava pagamentos e eventos. Evento já conhecido (mesmo event_id) é ignorado."""
        result = UpsertResult(received=len(batch.payments), applied=0)
        with db.connect() as conn:
            for payment in batch.payments:
                conn.execute(
                    """
                    insert into payments (payment_id, order_ref, amount_cents, method, status, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict (payment_id) do update set
                        status = excluded.status, updated_at = excluded.updated_at
                    where excluded.updated_at >= payments.updated_at
                    """,
                    (
                        payment.payment_id,
                        payment.order_ref,
                        payment.amount_cents,
                        payment.method,
                        payment.status,
                        to_iso(payment.created_at),
                        to_iso(payment.updated_at),
                    ),
                )
                result.applied += 1
                for event in sorted(payment.events, key=lambda e: e.occurred_at):
                    inserted = conn.execute(
                        "insert into payment_events (event_id, payment_id, event_type, occurred_at)"
                        " values (?, ?, ?, ?) on conflict (event_id) do nothing",
                        (
                            event.event_id,
                            payment.payment_id,
                            event.event_type,
                            to_iso(event.occurred_at),
                        ),
                    ).rowcount
                    if not inserted:
                        result.ignored_duplicates += 1
                        continue
                    data = {
                        "payment_id": payment.payment_id,
                        "order_ref": payment.order_ref,
                        "amount_cents": payment.amount_cents,
                        "method": payment.method,
                        "status": STATUS_BY_EVENT[event.event_type],
                    }
                    if batch.enqueue_webhooks and enqueue(
                        conn, event.event_id, event.event_type, event.occurred_at, data, clock()
                    ):
                        result.enqueued += 1
        return result

    return app
