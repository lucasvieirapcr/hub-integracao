"""Movimento diário simulado: pedidos do ERP e da loja B2B, pagamentos e eventos do CRM."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from simulator import catalog
from simulator.documents import generate_cnpj
from simulator.master_data import Customer, MasterData, Product, slugify
from simulator.rng import rng_for, uuid_from

# Fator de volume por dia da semana (segunda = 0). O ERP quase para no fim de semana.
ERP_WEEKDAY_FACTORS = (1.10, 1.00, 1.00, 1.00, 1.05, 0.30, 0.05)
ONLINE_WEEKDAY_FACTORS = (1.00, 1.00, 1.00, 1.00, 1.00, 0.60, 0.50)

CANCELLATION_RATE = 0.03
DECLINE_RATE = 0.08
REFUND_RATE = 0.02


@dataclass(frozen=True, slots=True)
class OrderLine:
    line_number: int
    product_id: int
    product_code: str
    quantity: int
    unit_price_cents: int
    lot_id: int  # lote que o FEFO escolheria; usado na carga histórica do ERP

    @property
    def amount_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(frozen=True, slots=True)
class ErpOrder:
    customer_id: int
    warehouse_id: int
    channel: str  # PHONE, SALES_REP ou B2B
    order_date: date
    created_at: datetime
    lines: tuple[OrderLine, ...]
    external_order_ref: str | None
    price_from_source: bool  # True: o preço vem da loja, não da tabela do ERP
    cancelled: bool
    invoiced_at: datetime | None

    @property
    def total_cents(self) -> int:
        return sum(line.amount_cents for line in self.lines)


@dataclass(frozen=True, slots=True)
class B2bOrder:
    order_id: str
    customer_code: str
    status: str  # SHIPPED, CANCELLED ou REFUNDED (estado final do dia)
    payment_method: str
    created_at: datetime
    updated_at: datetime
    lines: tuple[OrderLine, ...]

    @property
    def total_cents(self) -> int:
        return sum(line.amount_cents for line in self.lines)


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    event_id: str
    event_type: str  # payment.approved, payment.declined, payment.refunded
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Payment:
    payment_id: str
    order_ref: str
    amount_cents: int
    method: str
    status: str  # approved, declined ou refunded
    created_at: datetime
    updated_at: datetime
    events: tuple[PaymentEvent, ...]


@dataclass(frozen=True, slots=True)
class CrmChange:
    event_id: str
    event_type: str  # customer.created ou customer.updated
    customer_code: str
    occurred_at: datetime
    changes: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class DayActivity:
    day: date
    erp_orders: list[ErpOrder]  # pedidos diretos + pedidos B2B replicados, em ordem de criação
    b2b_orders: list[B2bOrder]
    payments: list[Payment]
    crm_changes: list[CrmChange]


def _at(day: date, hour: int, rng: random.Random, window_hours: int) -> datetime:
    start = datetime.combine(day, time(hour), tzinfo=UTC)
    return start + timedelta(seconds=rng.randint(0, window_hours * 3600 - 1))


class ActivityGenerator:
    def __init__(self, master: MasterData) -> None:
        self.master = master
        self.seed = master.config.seed
        self.profile = master.config.profile
        self._customer_cum = list(itertools.accumulate(master.customer_weights))
        self._product_cum = list(itertools.accumulate(master.product_weights))
        # O portal B2B é usado por farmácias e clínicas; hospitais compram pelo comercial.
        online = [
            (c, w)
            for c, w in zip(master.customers, master.customer_weights, strict=True)
            if c.customer_type != "HOSPITAL"
        ] or list(zip(master.customers, master.customer_weights, strict=True))
        self._online_customers = [c for c, _ in online]
        self._online_cum = list(itertools.accumulate(w for _, w in online))
        self._area_codes = {c.ibge_code: c.area_code for c in catalog.CITIES}

    def day(self, day: date) -> DayActivity:
        direct = self._erp_direct_orders(day)
        b2b_orders, payments, replicated = self._b2b_orders(day)
        erp_orders = sorted(direct + replicated, key=lambda o: o.created_at)
        return DayActivity(day, erp_orders, b2b_orders, payments, self._crm_changes(day))

    @staticmethod
    def _daily_count(rng: random.Random, base: int, factor: float) -> int:
        return max(0, round(base * factor * rng.uniform(0.85, 1.15)))

    def _price(self, product: Product, customer: Customer, day: date, online: bool) -> int:
        if online:
            return self.master.b2b_price_on(product, day)
        return self.master.table_price_on(product, customer.price_table_id, day)

    def _lines(
        self, rng: random.Random, customer: Customer, day: date, *, online: bool
    ) -> tuple[OrderLine, ...]:
        low, high = self.profile.items_per_order
        wanted = rng.randint(low, high)
        chosen: dict[int, Product] = {}
        for _ in range(wanted * 5):
            if len(chosen) == wanted:
                break
            product = rng.choices(self.master.products, cum_weights=self._product_cum)[0]
            chosen.setdefault(product.product_id, product)
        max_qty = 60 if customer.customer_type == "HOSPITAL" else 24
        return tuple(
            OrderLine(
                line_number=i,
                product_id=p.product_id,
                product_code=p.product_code,
                quantity=rng.randint(1, max_qty),
                unit_price_cents=self._price(p, customer, day, online),
                lot_id=self.master.pick_lot(p.product_id, day).lot_id,
            )
            for i, p in enumerate(chosen.values(), start=1)
        )

    def _erp_direct_orders(self, day: date) -> list[ErpOrder]:
        rng = rng_for(self.seed, "erp_orders", day.isoformat())
        count = self._daily_count(
            rng, self.profile.erp_orders_per_day, ERP_WEEKDAY_FACTORS[day.weekday()]
        )
        orders: list[ErpOrder] = []
        for _ in range(count):
            customer = rng.choices(self.master.customers, cum_weights=self._customer_cum)[0]
            created_at = _at(day, 11, rng, 10)  # 8h às 18h no horário de Brasília (UTC-3)
            lines = self._lines(rng, customer, day, online=False)
            cancelled = rng.random() < CANCELLATION_RATE
            invoiced_at = (
                None if cancelled else created_at + timedelta(minutes=rng.randint(60, 1200))
            )
            orders.append(
                ErpOrder(
                    customer_id=customer.customer_id,
                    warehouse_id=customer.warehouse_id,
                    channel=rng.choices(["PHONE", "SALES_REP"], weights=[55, 45])[0],
                    order_date=day,
                    created_at=created_at,
                    lines=lines,
                    external_order_ref=None,
                    price_from_source=False,
                    cancelled=cancelled,
                    invoiced_at=invoiced_at,
                )
            )
        return orders

    def _b2b_orders(self, day: date) -> tuple[list[B2bOrder], list[Payment], list[ErpOrder]]:
        rng = rng_for(self.seed, "b2b_orders", day.isoformat())
        count = self._daily_count(
            rng, self.profile.b2b_orders_per_day, ONLINE_WEEKDAY_FACTORS[day.weekday()]
        )
        b2b_orders: list[B2bOrder] = []
        payments: list[Payment] = []
        replicated: list[ErpOrder] = []
        for seq in range(1, count + 1):
            customer = rng.choices(self._online_customers, cum_weights=self._online_cum)[0]
            order_id = f"B2B-{day:%Y%m%d}-{seq:05d}"
            created_at = _at(day, 9, rng, 15)
            lines = self._lines(rng, customer, day, online=True)
            total = sum(line.amount_cents for line in lines)
            method = rng.choices(["PIX", "CARD", "BOLETO"], weights=[50, 40, 10])[0]
            roll = rng.random()
            outcome = (
                "declined"
                if roll < DECLINE_RATE
                else "refunded"
                if roll < DECLINE_RATE + REFUND_RATE
                else "approved"
            )

            decided_at = created_at + timedelta(seconds=rng.randint(5, 600))
            events = [
                PaymentEvent(
                    str(uuid_from(rng)),
                    "payment.declined" if outcome == "declined" else "payment.approved",
                    decided_at,
                )
            ]
            if outcome == "refunded":
                refunded_at = decided_at + timedelta(minutes=rng.randint(120, 1200))
                events.append(PaymentEvent(str(uuid_from(rng)), "payment.refunded", refunded_at))
            payments.append(
                Payment(
                    payment_id=f"pay_{day:%Y%m%d}{seq:05d}",
                    order_ref=order_id,
                    amount_cents=total,
                    method=method,
                    status=outcome,
                    created_at=created_at + timedelta(seconds=2),
                    updated_at=events[-1].occurred_at,
                    events=tuple(events),
                )
            )

            if outcome == "declined":
                b2b_orders.append(
                    B2bOrder(
                        order_id,
                        customer.customer_code,
                        "CANCELLED",
                        method,
                        created_at,
                        decided_at,
                        lines,
                    )
                )
                continue
            # Pago: o pedido segue para o ERP, que reserva estoque e fatura.
            invoiced_at = decided_at + timedelta(minutes=rng.randint(30, 600))
            replicated.append(
                ErpOrder(
                    customer_id=customer.customer_id,
                    warehouse_id=customer.warehouse_id,
                    channel="B2B",
                    order_date=day,
                    created_at=decided_at,
                    lines=lines,
                    external_order_ref=order_id,
                    price_from_source=True,
                    cancelled=False,
                    invoiced_at=invoiced_at,
                )
            )
            status = "REFUNDED" if outcome == "refunded" else "SHIPPED"
            updated_at = max(invoiced_at, events[-1].occurred_at)
            b2b_orders.append(
                B2bOrder(
                    order_id, customer.customer_code, status, method, created_at, updated_at, lines
                )
            )
        return b2b_orders, payments, replicated

    def _crm_changes(self, day: date) -> list[CrmChange]:
        rng = rng_for(self.seed, "crm", day.isoformat())
        count = self._daily_count(
            rng, self.profile.crm_events_per_day, ONLINE_WEEKDAY_FACTORS[day.weekday()]
        )
        changes: list[CrmChange] = []
        for _ in range(count):
            customer = rng.choice(self.master.customers)
            field = rng.choice(["email", "phone", "contact_name", "segment"])
            changes.append(
                CrmChange(
                    event_id=str(uuid_from(rng)),
                    event_type="customer.updated",
                    customer_code=customer.customer_code,
                    occurred_at=_at(day, 11, rng, 11),
                    changes={
                        field: self._new_value(
                            rng, field, customer.trade_name, customer.city_ibge_code
                        )
                    },
                )
            )
        # Alguns clientes novos nascem no CRM (prospecção) antes de existirem no ERP.
        for seq in range(1, rng.randint(0, 2) + 1):
            city = rng.choices(catalog.CITIES, weights=catalog.CITY_WEIGHTS)[0]
            trade_name = f"{rng.choice(catalog.PHARMACY_PREFIXES)} {rng.choice(catalog.NAME_PARTS)}"
            changes.append(
                CrmChange(
                    event_id=str(uuid_from(rng)),
                    event_type="customer.created",
                    customer_code=f"CRM{day:%Y%m%d}{seq:02d}",
                    occurred_at=_at(day, 11, rng, 11),
                    changes={
                        "legal_name": f"{trade_name} {city.name} Comércio de Medicamentos Ltda",
                        "trade_name": trade_name,
                        "cnpj": generate_cnpj(rng),
                        "customer_type": "PHARMACY",
                        "city_ibge_code": city.ibge_code,
                        "state": city.state,
                        "contact_name": self._new_value(
                            rng, "contact_name", trade_name, city.ibge_code
                        ),
                        "email": self._new_value(rng, "email", trade_name, city.ibge_code),
                        "phone": self._new_value(rng, "phone", trade_name, city.ibge_code),
                        "segment": "C",
                    },
                )
            )
        return sorted(changes, key=lambda c: c.occurred_at)

    def _new_value(self, rng: random.Random, field: str, trade_name: str, ibge_code: int) -> str:
        first, last = rng.choice(catalog.FIRST_NAMES), rng.choice(catalog.LAST_NAMES)
        if field == "email":
            return f"{slugify(first)}.{slugify(last)}@{slugify(trade_name)}.example"
        if field == "phone":
            return f"+55 {self._area_codes[ibge_code]} 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
        if field == "segment":
            return rng.choice(["A", "B", "C"])
        return f"{first} {last}"
