"""Dados mestres e movimento diário: determinismo e coerência entre sistemas."""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest

from simulator.activity import ActivityGenerator
from simulator.documents import generate_cnpj, is_valid_cnpj
from simulator.master_data import MIN_SHELF_LIFE_DAYS, MasterData, build_master_data
from simulator.rng import rng_for
from simulator.settings import SimulatorConfig, load_config


def test_generated_cnpjs_are_valid() -> None:
    rng = rng_for(1, "cnpj")
    assert all(is_valid_cnpj(generate_cnpj(rng)) for _ in range(500))
    assert is_valid_cnpj("11222333000181")
    assert not is_valid_cnpj("11222333000182")
    assert not is_valid_cnpj("11111111111111")


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="não existe"):
        load_config(profile_name="inexistente")


def test_master_data_is_deterministic(test_config: SimulatorConfig, master: MasterData) -> None:
    again = build_master_data(test_config)
    assert again.customers == master.customers
    assert again.products == master.products
    assert again.lots == master.lots
    assert again.stock_snapshot() == master.stock_snapshot()


def test_codes_are_unique(master: MasterData) -> None:
    assert len({c.customer_code for c in master.customers}) == len(master.customers)
    assert len({p.product_code for p in master.products}) == len(master.products)
    assert len({(lot.product_id, lot.lot_number) for lot in master.lots}) == len(master.lots)


def test_price_adjustment_in_april(dev_master: MasterData) -> None:
    product = dev_master.products[0]
    before = dev_master.list_price_on(product, date(2026, 3, 31))
    after = dev_master.list_price_on(product, date(2026, 4, 1))
    assert after == product.list_price_cents
    assert after / before == pytest.approx(1.045, rel=0.01)


def test_price_table_items_cover_history_without_gaps(dev_master: MasterData) -> None:
    items = [
        i for i in dev_master.price_table_items() if i.price_table_id == 2 and i.product_id == 1
    ]
    items.sort(key=lambda i: i.valid_from)
    assert items[0].valid_from == dev_master.config.history_start
    assert items[-1].valid_to is None
    for previous, current in itertools.pairwise(items):
        assert previous.valid_to == current.valid_from - timedelta(days=1)


def test_pick_lot_follows_fefo_and_min_shelf_life(master: MasterData) -> None:
    day = master.config.history_end
    for product in master.products:
        lot = master.pick_lot(product.product_id, day)
        sellable = [
            candidate
            for candidate in master.lots_by_product[product.product_id]
            if candidate.manufactured_on <= day
            and candidate.expires_on > day + timedelta(days=MIN_SHELF_LIFE_DAYS)
        ]
        if sellable:
            assert lot == min(sellable, key=lambda c: (c.expires_on, c.lot_id))


def test_stock_snapshot_has_only_valid_lots(master: MasterData) -> None:
    lots = {lot.lot_id: lot for lot in master.lots}
    end = master.config.history_end
    for position in master.stock_snapshot():
        assert lots[position.lot_id].expires_on > end
        assert lots[position.lot_id].manufactured_on <= end


def test_same_day_generates_same_activity(generator: ActivityGenerator) -> None:
    day = date(2026, 10, 15)
    assert generator.day(day) == generator.day(day)
    assert generator.day(day) != generator.day(day + timedelta(days=1))


def test_b2b_orders_and_payments_are_consistent(generator: ActivityGenerator) -> None:
    activity = generator.day(date(2026, 10, 14))
    assert activity.b2b_orders, "o perfil de teste deveria gerar pedidos B2B num dia útil"
    payments = {p.order_ref: p for p in activity.payments}
    replicated = {o.external_order_ref: o for o in activity.erp_orders if o.channel == "B2B"}

    for order in activity.b2b_orders:
        payment = payments[order.order_id]
        assert payment.amount_cents == order.total_cents
        if payment.status == "declined":
            assert order.status == "CANCELLED"
            assert order.order_id not in replicated
        else:
            erp_order = replicated[order.order_id]
            assert erp_order.total_cents == order.total_cents
            assert erp_order.price_from_source


def test_erp_direct_orders_use_table_price(
    master: MasterData, generator: ActivityGenerator
) -> None:
    day = date(2026, 10, 14)
    products = {p.product_id: p for p in master.products}
    customers = {c.customer_id: c for c in master.customers}
    for order in generator.day(day).erp_orders:
        if order.channel == "B2B":
            continue
        customer = customers[order.customer_id]
        for line in order.lines:
            expected = master.table_price_on(
                products[line.product_id], customer.price_table_id, day
            )
            assert line.unit_price_cents == expected


def test_crm_changes_are_ordered_and_unique(generator: ActivityGenerator) -> None:
    changes = generator.day(date(2026, 10, 14)).crm_changes
    assert [c.occurred_at for c in changes] == sorted(c.occurred_at for c in changes)
    assert len({c.event_id for c in changes}) == len(changes)
