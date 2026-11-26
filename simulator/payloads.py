"""Conversão dos objetos do simulador para o JSON das rotas /admin das APIs simuladas."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from simulator.activity import B2bOrder, CrmChange, Payment
from simulator.master_data import Customer, MasterData, Product


def product_payload(master: MasterData, product: Product, on_date: date) -> dict[str, Any]:
    return {
        "product_code": product.product_code,
        "description": product.description,
        "category": product.category,
        "unit_price_cents": master.b2b_price_on(product, on_date),
        "is_active": True,
        "updated_at": datetime.combine(on_date, time(3), tzinfo=UTC).isoformat(),
    }


def b2b_order_payload(order: B2bOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "customer_code": order.customer_code,
        "status": order.status,
        "payment_method": order.payment_method,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "items": [
            {
                "line_number": line.line_number,
                "product_code": line.product_code,
                "quantity": line.quantity,
                "unit_price_cents": line.unit_price_cents,
            }
            for line in order.lines
        ],
    }


def payment_payload(payment: Payment) -> dict[str, Any]:
    return {
        "payment_id": payment.payment_id,
        "order_ref": payment.order_ref,
        "amount_cents": payment.amount_cents,
        "method": payment.method,
        "status": payment.status,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
        "events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at.isoformat(),
            }
            for e in payment.events
        ],
    }


def crm_customer_payload(customer: Customer) -> dict[str, Any]:
    return {
        "customer_code": customer.customer_code,
        "legal_name": customer.legal_name,
        "trade_name": customer.trade_name,
        "cnpj": customer.cnpj,
        "customer_type": customer.customer_type,
        "city_ibge_code": customer.city_ibge_code,
        "state": customer.state,
        "contact_name": customer.contact_name,
        "email": customer.email,
        "phone": customer.phone,
        "segment": customer.segment,
        "updated_at": datetime.combine(customer.created_on, time(12), tzinfo=UTC).isoformat(),
    }


def crm_change_payload(change: CrmChange) -> dict[str, Any]:
    return {
        "event_id": change.event_id,
        "event_type": change.event_type,
        "customer_code": change.customer_code,
        "occurred_at": change.occurred_at.isoformat(),
        "changes": change.changes,
    }
