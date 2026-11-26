"""API do CRM. Alterações de cliente geram webhooks customer.created/customer.updated.

uvicorn --factory source_systems.crm.app:create_app
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field, field_validator

from simulator.chaos import ChaosLedger, load_chaos_config
from source_systems.common.app import PageOut, UpsertResult, create_base_app
from source_systems.common.db import Database, to_iso
from source_systems.common.guard import ApiGuard
from source_systems.common.pagination import fetch_page
from source_systems.common.settings import CrmSettings
from source_systems.common.webhooks import OUTBOX_SCHEMA, WebhookDispatcher, enqueue

SCHEMA = (
    """
create table if not exists customers (
    customer_code   text primary key,
    legal_name      text not null,
    trade_name      text not null,
    cnpj            text not null,
    customer_type   text not null,
    city_ibge_code  integer not null,
    state           text not null,
    contact_name    text,
    email           text,
    phone           text,
    segment         text,
    version         integer not null default 1,
    updated_at      text not null
);
create index if not exists ix_customers_updated on customers (updated_at, customer_code);

-- Histórico de alterações recebidas: garante que o mesmo event_id não é aplicado duas vezes.
create table if not exists customer_events (
    event_id       text primary key,
    customer_code  text not null,
    event_type     text not null,
    occurred_at    text not null,
    changes        text not null
);
"""
    + OUTBOX_SCHEMA
)

# Campos alteráveis; também limitam as colunas do UPDATE dinâmico.
MUTABLE_FIELDS = frozenset(
    {"legal_name", "trade_name", "contact_name", "email", "phone", "segment"}
)
CREATE_FIELDS = frozenset(
    {
        "legal_name",
        "trade_name",
        "cnpj",
        "customer_type",
        "city_ibge_code",
        "state",
        "contact_name",
        "email",
        "phone",
        "segment",
    }
)
REQUIRED_ON_CREATE = frozenset(
    {"legal_name", "trade_name", "cnpj", "customer_type", "city_ibge_code", "state"}
)


class Customer(BaseModel):
    customer_code: str
    legal_name: str
    trade_name: str
    cnpj: str = Field(pattern=r"^\d{14}$")
    customer_type: Literal["PHARMACY", "CLINIC", "HOSPITAL"]
    city_ibge_code: int
    state: str = Field(min_length=2, max_length=2)
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    segment: str | None = None
    updated_at: AwareDatetime


class CustomerOut(Customer):
    version: int


class CustomerChange(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: Literal["customer.created", "customer.updated"]
    customer_code: str
    occurred_at: AwareDatetime
    changes: dict[str, str | int]

    @field_validator("changes")
    @classmethod
    def _known_fields(cls, value: dict[str, str | int]) -> dict[str, str | int]:
        unknown = set(value) - CREATE_FIELDS
        if unknown:
            raise ValueError(f"campos desconhecidos: {sorted(unknown)}")
        return value


class CustomerBatch(BaseModel):
    customers: list[Customer]


class ChangeBatch(BaseModel):
    events: list[CustomerChange]
    enqueue_webhooks: bool = True


def _apply_change(conn: sqlite3.Connection, change: CustomerChange) -> dict[str, Any]:
    """Aplica a alteração ao cadastro e devolve o retrato do cliente depois dela."""
    current = conn.execute(
        "select * from customers where customer_code = ?", (change.customer_code,)
    ).fetchone()
    occurred = to_iso(change.occurred_at)
    if change.event_type == "customer.created":
        if current is not None:
            raise HTTPException(409, f"Cliente {change.customer_code} já existe")
        missing = REQUIRED_ON_CREATE - set(change.changes)
        if missing:
            raise HTTPException(422, f"customer.created sem os campos {sorted(missing)}")
        columns = ["customer_code", *sorted(change.changes), "version", "updated_at"]
        values = [
            change.customer_code,
            *(change.changes[c] for c in sorted(change.changes)),
            1,
            occurred,
        ]
        conn.execute(
            f"insert into customers ({', '.join(columns)}) values ({', '.join('?' * len(columns))})",  # noqa: S608
            values,
        )
    else:
        if current is None:
            raise HTTPException(404, f"Cliente {change.customer_code} não existe")
        invalid = set(change.changes) - MUTABLE_FIELDS
        if invalid:
            raise HTTPException(422, f"Campos não alteráveis: {sorted(invalid)}")
        fields = sorted(change.changes)
        assignments = ", ".join(f"{f} = ?" for f in fields)
        conn.execute(
            f"update customers set {assignments}, version = version + 1,"  # noqa: S608
            " updated_at = max(updated_at, ?) where customer_code = ?",
            [*(change.changes[f] for f in fields), occurred, change.customer_code],
        )
    row = conn.execute(
        "select * from customers where customer_code = ?", (change.customer_code,)
    ).fetchone()
    return CustomerOut.model_validate(dict(row)).model_dump(mode="json") | {
        "changed_fields": sorted(change.changes)
    }


def create_app(
    settings: CrmSettings | None = None,
    *,
    http_client: httpx.Client | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    settings = settings or CrmSettings()  # valores vêm do ambiente
    chaos_config = load_chaos_config(settings.chaos_config_path)
    ledger = ChaosLedger(settings.chaos_ledger_dir, "crm")
    guard = ApiGuard(settings, chaos_config.crm, ledger, chaos_config.seed, monotonic, sleep)
    db = Database(settings.db_path, SCHEMA)
    dispatcher = WebhookDispatcher(
        db,
        system="crm",
        url=settings.webhook_url,
        secret=settings.webhook_secret.get_secret_value(),
        max_attempts=settings.webhook_max_attempts,
        http=http_client or httpx.Client(),
        chaos=chaos_config.crm,
        ledger=ledger,
        chaos_seed=chaos_config.seed,
        clock=clock,
    )
    app = create_base_app(
        title="CRM - Distribuidora Exemplo",
        description="Sistema simulado. Dados fictícios.",
        guard=guard,
        dispatcher=dispatcher,
        delivery_interval_seconds=settings.webhook_interval_seconds,
    )
    # Rotas /v1 exigem token de cliente válido e respeitam o limite de requisições.
    client_only = [Depends(guard.client)]

    @app.get("/v1/customers", tags=["clientes"], dependencies=client_only)
    def list_customers(
        cursor: str | None = None,
        updated_since: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> PageOut[CustomerOut]:
        with db.connect() as conn:
            page = fetch_page(
                conn,
                table="customers",
                key_column="customer_code",
                limit=min(limit, settings.max_page_size),
                cursor=cursor,
                updated_since=updated_since,
            )
        data = [CustomerOut.model_validate(dict(r)) for r in page.rows]
        return PageOut[CustomerOut](data=data, next_cursor=page.next_cursor)

    @app.get("/v1/customers/{customer_code}", tags=["clientes"], dependencies=client_only)
    def get_customer(customer_code: str) -> CustomerOut:
        with db.connect() as conn:
            row = conn.execute(
                "select * from customers where customer_code = ?", (customer_code,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Cliente não encontrado")
        return CustomerOut.model_validate(dict(row))

    @app.post("/admin/customers", tags=["admin"], dependencies=[Depends(guard.admin)])
    def load_customers(batch: CustomerBatch) -> UpsertResult:
        """Carga inicial do cadastro (sem gerar eventos)."""
        with db.connect() as conn:
            conn.executemany(
                """
                insert into customers (customer_code, legal_name, trade_name, cnpj, customer_type, city_ibge_code,
                                       state, contact_name, email, phone, segment, version, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                on conflict (customer_code) do update set
                    legal_name = excluded.legal_name, trade_name = excluded.trade_name, cnpj = excluded.cnpj,
                    customer_type = excluded.customer_type, city_ibge_code = excluded.city_ibge_code,
                    state = excluded.state, contact_name = excluded.contact_name, email = excluded.email,
                    phone = excluded.phone, segment = excluded.segment, updated_at = excluded.updated_at
                """,
                [
                    (
                        c.customer_code,
                        c.legal_name,
                        c.trade_name,
                        c.cnpj,
                        c.customer_type,
                        c.city_ibge_code,
                        c.state,
                        c.contact_name,
                        c.email,
                        c.phone,
                        c.segment,
                        to_iso(c.updated_at),
                    )
                    for c in batch.customers
                ],
            )
        return UpsertResult(received=len(batch.customers), applied=len(batch.customers))

    @app.post("/admin/events", tags=["admin"], dependencies=[Depends(guard.admin)])
    def apply_changes(batch: ChangeBatch) -> UpsertResult:
        """Aplica alterações em ordem de ocorrência. Event_id repetido é ignorado."""
        result = UpsertResult(received=len(batch.events), applied=0)
        with db.connect() as conn:
            for change in sorted(batch.events, key=lambda e: (e.occurred_at, e.event_id)):
                inserted = conn.execute(
                    "insert into customer_events (event_id, customer_code, event_type, occurred_at, changes)"
                    " values (?, ?, ?, ?, ?) on conflict (event_id) do nothing",
                    (
                        change.event_id,
                        change.customer_code,
                        change.event_type,
                        to_iso(change.occurred_at),
                        json.dumps(change.changes, ensure_ascii=False),
                    ),
                ).rowcount
                if not inserted:
                    result.ignored_duplicates += 1
                    continue
                snapshot = _apply_change(conn, change)
                result.applied += 1
                if batch.enqueue_webhooks and enqueue(
                    conn, change.event_id, change.event_type, change.occurred_at, snapshot, clock()
                ):
                    result.enqueued += 1
        return result

    return app
