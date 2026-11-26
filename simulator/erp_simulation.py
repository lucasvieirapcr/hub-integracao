"""Simulação de um dia do ERP pelos packages. O dia é gravado em sim_runs na mesma transação."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import oracledb

from simulator.activity import DayActivity, ErpOrder
from simulator.chaos import ChaosLedger, ErpChaos
from simulator.erp_loader import money, utc_naive
from simulator.master_data import MasterData
from simulator.rng import rng_for

INSUFFICIENT_STOCK = 20101  # pkg_stock.e_insufficient_stock


@dataclass(slots=True)
class ErpDaySummary:
    day: date
    skipped: bool = False
    created: int = 0
    invoiced: int = 0
    cancelled: int = 0
    out_of_stock: int = 0
    replication_gaps: int = 0
    replenishments: int = 0


def next_simulation_day(connection: Any, history_end: date) -> date:
    with connection.cursor() as cursor:
        cursor.execute("select max(sim_date) from sim_runs")
        (last,) = cursor.fetchone()
    last_day = last.date() if isinstance(last, datetime) else (last or history_end)
    return max(last_day, history_end) + timedelta(days=1)


def _ora_code(error: oracledb.DatabaseError) -> int:
    code: int = getattr(error.args[0], "code", 0)
    return code


def _run_order(cursor: Any, order: ErpOrder, summary: ErpDaySummary) -> None:
    created_at = utc_naive(order.created_at)
    order_id = cursor.callfunc(
        "pkg_order.create_order",
        int,
        [
            order.customer_id,
            order.warehouse_id,
            order.channel,
            order.order_date,
            order.external_order_ref,
            created_at,
        ],
    )
    summary.created += 1
    for line in order.lines:
        unit_price = money(line.unit_price_cents) if order.price_from_source else None
        cursor.callproc(
            "pkg_order.add_item", [order_id, line.product_id, line.quantity, unit_price, created_at]
        )

    if order.cancelled or order.invoiced_at is None:
        cursor.callproc("pkg_order.cancel_order", [order_id, created_at + timedelta(minutes=30)])
        summary.cancelled += 1
        return
    try:
        cursor.callproc("pkg_order.confirm_order", [order_id, created_at + timedelta(minutes=5)])
    except oracledb.DatabaseError as error:
        if _ora_code(error) != INSUFFICIENT_STOCK:
            raise
        # Sem estoque: o pedido continua OPEN (o package desfez a reserva) e é cancelado.
        cursor.callproc("pkg_order.cancel_order", [order_id, created_at + timedelta(minutes=10)])
        summary.out_of_stock += 1
        return
    cursor.callfunc("pkg_order.invoice_order", int, [order_id, utc_naive(order.invoiced_at)])
    summary.invoiced += 1


def _replenish(cursor: Any, master: MasterData, day: date, summary: ErpDaySummary) -> None:
    """Chegada diária de mercadoria: ~2% dos produtos recebem estoque no lote mais novo."""
    rng = rng_for(master.config.seed, "replenish", day.isoformat())
    event_at = datetime.combine(day, time(12))
    min_expiry = day + timedelta(days=180)
    for warehouse in master.warehouses:
        for product in master.products:
            if rng.random() >= 0.02:
                continue
            lots = [
                lot
                for lot in master.lots_by_product[product.product_id]
                if lot.expires_on > min_expiry
            ]
            if not lots:
                continue
            newest = lots[-1]
            cursor.callproc(
                "pkg_stock.receive_stock",
                [warehouse.warehouse_id, newest.lot_id, rng.randint(100, 1000), event_at],
            )
            summary.replenishments += 1


def simulate_erp_day(
    connection: Any,
    master: MasterData,
    activity: DayActivity,
    chaos: ErpChaos,
    chaos_seed: int,
    ledger: ChaosLedger,
) -> ErpDaySummary:
    summary = ErpDaySummary(activity.day)
    with connection.cursor() as cursor:
        cursor.execute("select count(*) from sim_runs where sim_date = :1", [activity.day])
        (already,) = cursor.fetchone()
        if already:
            summary.skipped = True
            return summary

        chaos_rng = rng_for(chaos_seed, "erp", activity.day.isoformat())
        for order in activity.erp_orders:
            if order.channel == "B2B" and chaos.b2b_replication_gap.fires(chaos_rng):
                ledger.record(
                    "b2b_replication_gap", order_ref=order.external_order_ref, day=activity.day
                )
                summary.replication_gaps += 1
                continue
            _run_order(cursor, order, summary)

        _replenish(cursor, master, activity.day, summary)
        cursor.execute(
            "insert into sim_runs (sim_date, orders_created, orders_cancelled) values (:1, :2, :3)",
            [activity.day, summary.created, summary.cancelled + summary.out_of_stock],
        )
    connection.commit()
    return summary
