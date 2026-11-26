"""API da loja B2B (catálogo e pedidos).

uvicorn --factory source_systems.b2b_store.app:create_app
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field

from simulator.chaos import ChaosLedger, load_chaos_config
from source_systems.common.app import PageOut, UpsertResult, create_base_app
from source_systems.common.db import Database, to_iso
from source_systems.common.guard import ApiGuard
from source_systems.common.pagination import fetch_page
from source_systems.common.settings import B2bSettings

SCHEMA = """
create table if not exists products (
    product_code      text primary key,
    description       text not null,
    category          text not null,
    unit_price_cents  integer not null,
    is_active         integer not null default 1,
    updated_at        text not null
);
create index if not exists ix_products_updated on products (updated_at, product_code);

create table if not exists orders (
    order_id            text primary key,
    customer_code       text not null,
    status              text not null,
    payment_method      text not null,
    total_amount_cents  integer not null,
    created_at          text not null,
    updated_at          text not null
);
create index if not exists ix_orders_updated on orders (updated_at, order_id);

create table if not exists order_items (
    order_id          text not null references orders (order_id) on delete cascade,
    line_number       integer not null,
    product_code      text not null,
    quantity          integer not null,
    unit_price_cents  integer not null,
    primary key (order_id, line_number)
);
"""

OrderStatus = Literal["PLACED", "PAID", "SHIPPED", "CANCELLED", "REFUNDED"]
PaymentMethod = Literal["PIX", "CARD", "BOLETO"]


class Product(BaseModel):
    product_code: str
    description: str
    category: str
    unit_price_cents: int = Field(ge=0)
    is_active: bool = True
    updated_at: AwareDatetime


class OrderItem(BaseModel):
    line_number: int = Field(ge=1)
    product_code: str
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class OrderIn(BaseModel):
    order_id: str
    customer_code: str
    status: OrderStatus
    payment_method: PaymentMethod
    created_at: AwareDatetime
    updated_at: AwareDatetime
    items: list[OrderItem] = Field(min_length=1)


class OrderOut(OrderIn):
    total_amount_cents: int


class ProductBatch(BaseModel):
    products: list[Product]


class OrderBatch(BaseModel):
    orders: list[OrderIn]


def create_app(
    settings: B2bSettings | None = None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> FastAPI:
    settings = settings or B2bSettings()  # valores vêm do ambiente
    chaos_config = load_chaos_config(settings.chaos_config_path)
    ledger = ChaosLedger(settings.chaos_ledger_dir, "b2b_store")
    guard = ApiGuard(settings, chaos_config.b2b_store, ledger, chaos_config.seed, monotonic, sleep)
    db = Database(settings.db_path, SCHEMA)
    app = create_base_app(
        title="Loja B2B - Distribuidora Exemplo",
        description="Sistema simulado. Dados fictícios.",
        guard=guard,
    )
    # Rotas /v1 exigem token de cliente válido e respeitam o limite de requisições.
    client_only = [Depends(guard.client)]

    def page_limit(limit: int) -> int:
        return min(limit, settings.max_page_size)

    def to_order(row: sqlite3.Row, items: list[OrderItem]) -> OrderOut:
        return OrderOut.model_validate({**dict(row), "items": items})

    @app.get("/v1/products", tags=["catálogo"], dependencies=client_only)
    def list_products(
        cursor: str | None = None,
        updated_since: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> PageOut[Product]:
        with db.connect() as conn:
            page = fetch_page(
                conn,
                table="products",
                key_column="product_code",
                limit=page_limit(limit),
                cursor=cursor,
                updated_since=updated_since,
            )
        data = [Product.model_validate(dict(r)) for r in page.rows]
        return PageOut[Product](data=data, next_cursor=page.next_cursor)

    @app.get("/v1/orders", tags=["pedidos"], dependencies=client_only)
    def list_orders(
        cursor: str | None = None,
        updated_since: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> PageOut[OrderOut]:
        with db.connect() as conn:
            page = fetch_page(
                conn,
                table="orders",
                key_column="order_id",
                limit=page_limit(limit),
                cursor=cursor,
                updated_since=updated_since,
            )
            ids = [r["order_id"] for r in page.rows]
            items_by_order: dict[str, list[OrderItem]] = {order_id: [] for order_id in ids}
            if ids:
                marks = ",".join("?" * len(ids))
                for item in conn.execute(
                    f"select * from order_items where order_id in ({marks}) order by order_id, line_number",  # noqa: S608
                    ids,
                ):
                    items_by_order[item["order_id"]].append(OrderItem.model_validate(dict(item)))
        data = [to_order(r, items_by_order[r["order_id"]]) for r in page.rows]
        return PageOut[OrderOut](data=data, next_cursor=page.next_cursor)

    @app.get("/v1/orders/{order_id}", tags=["pedidos"], dependencies=client_only)
    def get_order(order_id: str) -> OrderOut:
        with db.connect() as conn:
            row = conn.execute("select * from orders where order_id = ?", (order_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Pedido não encontrado")
            items = [
                OrderItem.model_validate(dict(i))
                for i in conn.execute(
                    "select * from order_items where order_id = ? order by line_number", (order_id,)
                )
            ]
        return to_order(row, items)

    @app.post("/admin/products", tags=["admin"], dependencies=[Depends(guard.admin)])
    def upsert_products(batch: ProductBatch) -> UpsertResult:
        with db.connect() as conn:
            conn.executemany(
                """
                insert into products (product_code, description, category, unit_price_cents, is_active, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict (product_code) do update set
                    description = excluded.description, category = excluded.category,
                    unit_price_cents = excluded.unit_price_cents, is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        p.product_code,
                        p.description,
                        p.category,
                        p.unit_price_cents,
                        int(p.is_active),
                        to_iso(p.updated_at),
                    )
                    for p in batch.products
                ],
            )
        return UpsertResult(received=len(batch.products), applied=len(batch.products))

    @app.post("/admin/orders", tags=["admin"], dependencies=[Depends(guard.admin)])
    def upsert_orders(batch: OrderBatch) -> UpsertResult:
        """Grava pedidos; reenviar o mesmo pedido substitui o anterior (sem duplicar)."""
        with db.connect() as conn:
            for order in batch.orders:
                total = sum(i.quantity * i.unit_price_cents for i in order.items)
                conn.execute(
                    """
                    insert into orders (order_id, customer_code, status, payment_method,
                                        total_amount_cents, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    on conflict (order_id) do update set
                        customer_code = excluded.customer_code, status = excluded.status,
                        payment_method = excluded.payment_method,
                        total_amount_cents = excluded.total_amount_cents,
                        created_at = excluded.created_at, updated_at = excluded.updated_at
                    """,
                    (
                        order.order_id,
                        order.customer_code,
                        order.status,
                        order.payment_method,
                        total,
                        to_iso(order.created_at),
                        to_iso(order.updated_at),
                    ),
                )
                conn.execute("delete from order_items where order_id = ?", (order.order_id,))
                conn.executemany(
                    "insert into order_items (order_id, line_number, product_code, quantity, unit_price_cents)"
                    " values (?, ?, ?, ?, ?)",
                    [
                        (
                            order.order_id,
                            i.line_number,
                            i.product_code,
                            i.quantity,
                            i.unit_price_cents,
                        )
                        for i in order.items
                    ],
                )
        return UpsertResult(received=len(batch.orders), applied=len(batch.orders))

    return app
