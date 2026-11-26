"""Cliente das rotas /admin das APIs simuladas."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

import httpx

from simulator import payloads
from simulator.activity import ActivityGenerator, B2bOrder, CrmChange, Payment
from simulator.erp_loader import days
from simulator.host_settings import HostSettings
from simulator.master_data import MasterData

CHUNK_SIZE = 500


def chunks[T](items: Sequence[T], size: int = CHUNK_SIZE) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SourceSystemsClient:
    def __init__(self, settings: HostSettings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=120)
        self._headers = {"Authorization": f"Bearer {settings.sim_admin_token.get_secret_value()}"}

    def _post(self, base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(f"{base_url}{path}", json=payload, headers=self._headers)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def push_products(self, products: list[dict[str, Any]]) -> None:
        for part in chunks(products):
            self._post(self.settings.b2b_base_url, "/admin/products", {"products": list(part)})

    def push_b2b_orders(self, orders: Sequence[B2bOrder]) -> None:
        for part in chunks(orders):
            self._post(
                self.settings.b2b_base_url,
                "/admin/orders",
                {"orders": [payloads.b2b_order_payload(o) for o in part]},
            )

    def push_payments(self, payments: Sequence[Payment], *, enqueue_webhooks: bool) -> int:
        enqueued = 0
        for part in chunks(payments):
            result = self._post(
                self.settings.payments_base_url,
                "/admin/payments",
                {
                    "payments": [payloads.payment_payload(p) for p in part],
                    "enqueue_webhooks": enqueue_webhooks,
                },
            )
            enqueued += int(result["enqueued"])
        return enqueued

    def push_crm_customers(self, customers: list[dict[str, Any]]) -> None:
        for part in chunks(customers):
            self._post(self.settings.crm_base_url, "/admin/customers", {"customers": list(part)})

    def push_crm_changes(self, changes: Sequence[CrmChange], *, enqueue_webhooks: bool) -> int:
        enqueued = 0
        for part in chunks(changes):
            result = self._post(
                self.settings.crm_base_url,
                "/admin/events",
                {
                    "events": [payloads.crm_change_payload(c) for c in part],
                    "enqueue_webhooks": enqueue_webhooks,
                },
            )
            enqueued += int(result["enqueued"])
        return enqueued

    def deliver_webhooks(self) -> dict[str, dict[str, Any]]:
        return {
            "crm": self._post(self.settings.crm_base_url, "/admin/webhooks/deliver", {}),
            "payments": self._post(self.settings.payments_base_url, "/admin/webhooks/deliver", {}),
        }


def seed_source_systems(
    client: SourceSystemsClient,
    master: MasterData,
    generator: ActivityGenerator,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Carga histórica das APIs. Eventos do histórico não geram webhook."""
    cfg = master.config
    client.push_products(
        [payloads.product_payload(master, p, cfg.history_end) for p in master.products]
    )
    client.push_crm_customers([payloads.crm_customer_payload(c) for c in master.customers])
    progress(
        f"APIs: catálogo ({len(master.products)}) e clientes do CRM ({len(master.customers)}) carregados"
    )

    counts = {"b2b_orders": 0, "payments": 0, "crm_changes": 0}
    orders: list[B2bOrder] = []
    payments: list[Payment] = []
    changes: list[CrmChange] = []

    def flush() -> None:
        client.push_b2b_orders(orders)
        client.push_payments(payments, enqueue_webhooks=False)
        client.push_crm_changes(changes, enqueue_webhooks=False)
        counts["b2b_orders"] += len(orders)
        counts["payments"] += len(payments)
        counts["crm_changes"] += len(changes)
        orders.clear()
        payments.clear()
        changes.clear()

    for day in days(cfg.history_start, cfg.history_end):
        activity = generator.day(day)
        orders.extend(activity.b2b_orders)
        payments.extend(activity.payments)
        changes.extend(activity.crm_changes)
        if len(orders) >= 5 * CHUNK_SIZE:
            flush()
            progress(f"APIs: histórico até {day} ({counts['b2b_orders']} pedidos B2B)")
    flush()
    progress(
        f"APIs: carga concluída ({counts['b2b_orders']} pedidos B2B, {counts['payments']} pagamentos, "
        f"{counts['crm_changes']} alterações no CRM)"
    )
    return counts
