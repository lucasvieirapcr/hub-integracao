"""Carga histórica do ERP com executemany. Começa por pkg_admin.reset_data, então pode ser reexecutada."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import oracledb

from simulator.activity import ActivityGenerator, ErpOrder
from simulator.master_data import MasterData

BATCH_ORDERS = 5_000


def money(cents: int) -> Decimal:
    return Decimal(cents) / 100


def utc_naive(moment: datetime) -> datetime:
    """TIMESTAMP sem fuso, em UTC."""
    return moment.astimezone(UTC).replace(tzinfo=None)


def days(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def insert_rows(
    cursor: Any,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    input_sizes: Sequence[Any] | None = None,
) -> int:
    """INSERT em lote. `table` e `columns` são constantes do código, nunca entrada externa."""
    if not rows:
        return 0
    binds = ", ".join(f":{i}" for i in range(1, len(columns) + 1))
    sql = f"insert into {table} ({', '.join(columns)}) values ({binds})"  # noqa: S608
    if input_sizes:
        # tipo explícito para colunas que aceitam nulo
        cursor.setinputsizes(*input_sizes)
    cursor.executemany(sql, rows)
    return len(rows)


ORDER_COLUMNS = (
    "order_id",
    "customer_id",
    "warehouse_id",
    "channel",
    "external_order_ref",
    "order_date",
    "status",
    "total_amount",
    "created_at",
    "updated_at",
)
ITEM_COLUMNS = ("order_id", "line_number", "product_id", "quantity", "unit_price")
ALLOCATION_COLUMNS = ("order_id", "line_number", "lot_id", "warehouse_id", "quantity")
INVOICE_COLUMNS = (
    "invoice_id",
    "invoice_number",
    "order_id",
    "issued_at",
    "total_amount",
    "status",
    "created_at",
    "updated_at",
)
INVOICE_ITEM_COLUMNS = (
    "invoice_id",
    "line_number",
    "product_id",
    "lot_id",
    "quantity",
    "unit_price",
)


@dataclass(slots=True)
class _HistoryBuffers:
    orders: list[tuple[Any, ...]] = field(default_factory=list)
    items: list[tuple[Any, ...]] = field(default_factory=list)
    allocations: list[tuple[Any, ...]] = field(default_factory=list)
    invoices: list[tuple[Any, ...]] = field(default_factory=list)
    invoice_items: list[tuple[Any, ...]] = field(default_factory=list)

    def flush(self, cursor: Any, counts: dict[str, int]) -> None:
        # ordem das FKs: pais antes dos filhos
        orders_sizes = [None] * 4 + [oracledb.DB_TYPE_VARCHAR] + [None] * 5
        counts["orders"] += insert_rows(cursor, "orders", ORDER_COLUMNS, self.orders, orders_sizes)
        counts["order_items"] += insert_rows(cursor, "order_items", ITEM_COLUMNS, self.items)
        counts["order_item_allocations"] += insert_rows(
            cursor, "order_item_allocations", ALLOCATION_COLUMNS, self.allocations
        )
        counts["invoices"] += insert_rows(cursor, "invoices", INVOICE_COLUMNS, self.invoices)
        counts["invoice_items"] += insert_rows(
            cursor, "invoice_items", INVOICE_ITEM_COLUMNS, self.invoice_items
        )
        for buffer in (
            self.orders,
            self.items,
            self.allocations,
            self.invoices,
            self.invoice_items,
        ):
            buffer.clear()


def _load_master_data(cursor: Any, master: MasterData, counts: dict[str, int]) -> None:
    cfg = master.config
    master_created = datetime.combine(cfg.history_start - timedelta(days=800), time(12))
    snapshot_at = datetime.combine(cfg.history_end, time(23, 59))

    counts["price_tables"] = insert_rows(
        cursor,
        "price_tables",
        ("price_table_id", "name", "discount_pct", "created_at", "updated_at"),
        [
            (t.price_table_id, t.name, t.discount_pct, master_created, master_created)
            for t in master.price_tables
        ],
    )
    counts["warehouses"] = insert_rows(
        cursor,
        "warehouses",
        (
            "warehouse_id",
            "warehouse_code",
            "name",
            "city_ibge_code",
            "state",
            "created_at",
            "updated_at",
        ),
        [
            (
                w.warehouse_id,
                w.warehouse_code,
                w.name,
                w.city_ibge_code,
                w.state,
                master_created,
                master_created,
            )
            for w in master.warehouses
        ],
    )
    counts["customers"] = insert_rows(
        cursor,
        "customers",
        (
            "customer_id",
            "customer_code",
            "legal_name",
            "trade_name",
            "cnpj",
            "customer_type",
            "city_ibge_code",
            "state",
            "price_table_id",
            "warehouse_id",
            "credit_limit",
            "is_active",
            "created_at",
            "updated_at",
        ),
        [
            (
                c.customer_id,
                c.customer_code,
                c.legal_name,
                c.trade_name,
                c.cnpj,
                c.customer_type,
                c.city_ibge_code,
                c.state,
                c.price_table_id,
                c.warehouse_id,
                money(c.credit_limit_cents),
                "Y",
                datetime.combine(c.created_on, time(12)),
                datetime.combine(c.created_on, time(12)),
            )
            for c in master.customers
        ],
    )
    counts["products"] = insert_rows(
        cursor,
        "products",
        (
            "product_id",
            "product_code",
            "description",
            "category",
            "active_ingredient",
            "manufacturer",
            "pack_size",
            "requires_prescription",
            "list_price",
            "is_active",
            "created_at",
            "updated_at",
        ),
        [
            (
                p.product_id,
                p.product_code,
                p.description,
                p.category,
                p.active_ingredient,
                p.manufacturer,
                p.pack_size,
                "Y" if p.requires_prescription else "N",
                money(p.list_price_cents),
                "Y",
                master_created,
                master_created,
            )
            for p in master.products
        ],
    )
    counts["price_table_items"] = insert_rows(
        cursor,
        "price_table_items",
        ("price_table_id", "product_id", "valid_from", "valid_to", "unit_price"),
        [
            (i.price_table_id, i.product_id, i.valid_from, i.valid_to, money(i.unit_price_cents))
            for i in master.price_table_items()
        ],
        input_sizes=[None, None, None, oracledb.DB_TYPE_DATE, None],
    )
    counts["lots"] = insert_rows(
        cursor,
        "lots",
        ("lot_id", "product_id", "lot_number", "manufactured_on", "expires_on"),
        [
            (lot.lot_id, lot.product_id, lot.lot_number, lot.manufactured_on, lot.expires_on)
            for lot in master.lots
        ],
    )
    counts["stock"] = insert_rows(
        cursor,
        "stock",
        ("warehouse_id", "lot_id", "qty_on_hand", "qty_reserved", "updated_at"),
        [
            (s.warehouse_id, s.lot_id, s.qty_on_hand, 0, snapshot_at)
            for s in master.stock_snapshot()
        ],
    )


def _add_order(
    buffers: _HistoryBuffers, order: ErpOrder, order_id: int, invoice_id: int | None
) -> None:
    created_at = utc_naive(order.created_at)
    if order.cancelled or order.invoiced_at is None:
        status, updated_at = "CANCELLED", created_at + timedelta(minutes=30)
    else:
        status, updated_at = "INVOICED", utc_naive(order.invoiced_at)
    buffers.orders.append(
        (
            order_id,
            order.customer_id,
            order.warehouse_id,
            order.channel,
            order.external_order_ref,
            order.order_date,
            status,
            money(order.total_cents),
            created_at,
            updated_at,
        )
    )
    for line in order.lines:
        buffers.items.append(
            (
                order_id,
                line.line_number,
                line.product_id,
                line.quantity,
                money(line.unit_price_cents),
            )
        )
    if invoice_id is None:
        return
    for line in order.lines:
        buffers.allocations.append(
            (order_id, line.line_number, line.lot_id, order.warehouse_id, line.quantity)
        )
        buffers.invoice_items.append(
            (
                invoice_id,
                line.line_number,
                line.product_id,
                line.lot_id,
                line.quantity,
                money(line.unit_price_cents),
            )
        )
    buffers.invoices.append(
        (
            invoice_id,
            invoice_id,
            order_id,
            updated_at,
            money(order.total_cents),
            "ISSUED",
            updated_at,
            updated_at,
        )
    )


def seed_erp(
    connection: Any,
    master: MasterData,
    generator: ActivityGenerator,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Zera o ERP e carrega cadastros, estoque e o histórico de pedidos e notas."""
    counts: dict[str, int] = dict.fromkeys(
        ("orders", "order_items", "order_item_allocations", "invoices", "invoice_items"), 0
    )
    cfg = master.config
    with connection.cursor() as cursor:
        progress("ERP: limpando dados anteriores (pkg_admin.reset_data)")
        cursor.callproc("pkg_admin.reset_data")
        _load_master_data(cursor, master, counts)
        connection.commit()
        progress(
            f"ERP: cadastros carregados ({counts['customers']} clientes, {counts['products']} produtos)"
        )

        buffers = _HistoryBuffers()
        order_id = invoice_id = 0
        for day in days(cfg.history_start, cfg.history_end):
            for order in generator.day(day).erp_orders:
                order_id += 1
                invoice: int | None = None
                if not order.cancelled:
                    invoice_id += 1
                    invoice = invoice_id
                _add_order(buffers, order, order_id, invoice)
            if len(buffers.orders) >= BATCH_ORDERS:
                buffers.flush(cursor, counts)
                connection.commit()
                progress(f"ERP: histórico até {day} ({counts['orders']} pedidos)")
        buffers.flush(cursor, counts)

        cursor.callproc("pkg_admin.sync_identities")
        connection.commit()
    progress(f"ERP: carga concluída ({counts['orders']} pedidos, {counts['invoices']} notas)")
    return counts


def connect(user: str, password: str, dsn: str) -> Any:
    """Conexão em modo thin (sem Oracle Client)."""
    return oracledb.connect(user=user, password=password, dsn=dsn)
