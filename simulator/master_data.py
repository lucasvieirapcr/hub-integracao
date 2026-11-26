"""Dados mestres compartilhados pelos sistemas simulados (clientes, produtos, CDs, lotes e preços em centavos)."""

from __future__ import annotations

import itertools
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from simulator import catalog
from simulator.documents import generate_cnpj
from simulator.rng import rng_for
from simulator.settings import SimulatorConfig

# Reajuste anual de medicamentos (a CMED autoriza reajuste em abril). Mesmo fator para tudo.
ANNUAL_PRICE_ADJUSTMENT = 1.045
# Mesma regra do pkg_stock: lote com menos de 30 dias de validade não é vendido.
MIN_SHELF_LIFE_DAYS = 30
# Desconto do preço online da loja B2B sobre o preço de lista.
B2B_DISCOUNT = 0.03


@dataclass(frozen=True, slots=True)
class PriceTable:
    price_table_id: int
    name: str
    discount_pct: int


@dataclass(frozen=True, slots=True)
class Warehouse:
    warehouse_id: int
    warehouse_code: str
    name: str
    city_ibge_code: int
    state: str


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: int
    customer_code: str
    legal_name: str
    trade_name: str
    cnpj: str
    customer_type: str  # PHARMACY, CLINIC ou HOSPITAL
    city_ibge_code: int
    city_name: str
    state: str
    price_table_id: int
    warehouse_id: int
    credit_limit_cents: int
    contact_name: str
    email: str
    phone: str
    segment: str
    created_on: date


@dataclass(frozen=True, slots=True)
class Product:
    product_id: int
    product_code: str
    description: str
    category: str
    active_ingredient: str
    manufacturer: str
    pack_size: int
    requires_prescription: bool
    list_price_cents: int  # preço de lista vigente no fim do histórico


@dataclass(frozen=True, slots=True)
class Lot:
    lot_id: int
    product_id: int
    lot_number: str
    manufactured_on: date
    expires_on: date


@dataclass(frozen=True, slots=True)
class PriceTableItem:
    price_table_id: int
    product_id: int
    unit_price_cents: int
    valid_from: date
    valid_to: date | None


@dataclass(frozen=True, slots=True)
class StockPosition:
    warehouse_id: int
    lot_id: int
    qty_on_hand: int


@dataclass(slots=True)
class MasterData:
    config: SimulatorConfig
    price_tables: list[PriceTable]
    warehouses: list[Warehouse]
    customers: list[Customer]
    products: list[Product]
    lots: list[Lot]
    customer_weights: list[float]
    product_weights: list[float]
    price_adjustment_dates: list[date]
    lots_by_product: dict[int, list[Lot]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for lot in self.lots:
            self.lots_by_product.setdefault(lot.product_id, []).append(lot)
        for lots in self.lots_by_product.values():
            lots.sort(key=lambda lot: (lot.expires_on, lot.lot_id))

    def list_price_on(self, product: Product, on_date: date) -> int:
        """Preço de lista numa data: desfaz os reajustes que aconteceram depois dela."""
        later_adjustments = sum(1 for d in self.price_adjustment_dates if d > on_date)
        return round(product.list_price_cents / ANNUAL_PRICE_ADJUSTMENT**later_adjustments)

    def table_price_on(self, product: Product, price_table_id: int, on_date: date) -> int:
        """Mesmo cálculo que o ERP faz em pkg_pricing (via price_table_items)."""
        discount = self.price_tables[price_table_id - 1].discount_pct
        return round(self.list_price_on(product, on_date) * (100 - discount) / 100)

    def b2b_price_on(self, product: Product, on_date: date) -> int:
        return round(self.list_price_on(product, on_date) * (1 - B2B_DISCOUNT))

    def price_table_items(self) -> list[PriceTableItem]:
        """Uma linha por combinação de tabela, produto e período entre reajustes."""
        boundaries = [self.config.history_start, *self.price_adjustment_dates]
        items: list[PriceTableItem] = []
        for table in self.price_tables:
            for product in self.products:
                for i, valid_from in enumerate(boundaries):
                    valid_to = (
                        boundaries[i + 1] - timedelta(days=1) if i + 1 < len(boundaries) else None
                    )
                    price = self.table_price_on(product, table.price_table_id, valid_from)
                    items.append(
                        PriceTableItem(
                            table.price_table_id, product.product_id, price, valid_from, valid_to
                        )
                    )
        return items

    def pick_lot(self, product_id: int, on_date: date) -> Lot:
        """Lote que o FEFO escolheria: o que vence primeiro entre os vendáveis na data."""
        lots = self.lots_by_product[product_id]
        min_expiry = on_date + timedelta(days=MIN_SHELF_LIFE_DAYS)
        for lot in lots:
            if lot.manufactured_on <= on_date and lot.expires_on > min_expiry:
                return lot
        # Sem lote vendável (borda do histórico): usa o mais novo já fabricado.
        made = [lot for lot in lots if lot.manufactured_on <= on_date]
        return max(made or lots, key=lambda lot: lot.manufactured_on)

    def stock_snapshot(self) -> list[StockPosition]:
        """Estoque no fim do histórico: todo lote ainda válido, em todos os CDs."""
        rng = rng_for(self.config.seed, "stock_snapshot")
        positions: list[StockPosition] = []
        for warehouse in self.warehouses:
            for lot in self.lots:
                if (
                    lot.expires_on <= self.config.history_end
                    or lot.manufactured_on > self.config.history_end
                ):
                    continue
                qty = 0 if rng.random() < 0.05 else rng.randint(200, 2000)
                positions.append(StockPosition(warehouse.warehouse_id, lot.lot_id, qty))
        return positions

    def warehouse_for(self, customer: Customer) -> Warehouse:
        return self.warehouses[customer.warehouse_id - 1]


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in ascii_text.lower() if ch.isalnum())


def _adjustment_dates(start: date, end: date) -> list[date]:
    return [
        date(year, 4, 1)
        for year in range(start.year, end.year + 1)
        if start < date(year, 4, 1) <= end
    ]


def _build_price_tables() -> list[PriceTable]:
    return [
        PriceTable(1, "Padrão", 0),
        PriceTable(2, "Redes de farmácias", 5),
        PriceTable(3, "Hospitais e clínicas", 8),
        PriceTable(4, "Grandes contas", 12),
    ]


def _build_warehouses(count: int) -> list[Warehouse]:
    city_by_code = {c.ibge_code: c for c in catalog.CITIES}
    return [
        Warehouse(i, f"CD{i:02d}", name, code, city_by_code[code].state)
        for i, (name, code) in enumerate(catalog.WAREHOUSES[:count], start=1)
    ]


def _build_customers(
    config: SimulatorConfig, warehouses: list[Warehouse]
) -> tuple[list[Customer], list[float]]:
    rng = rng_for(config.seed, "customers")
    customers: list[Customer] = []
    weights: list[float] = []
    for customer_id in range(1, config.profile.customers + 1):
        city = rng.choices(catalog.CITIES, weights=catalog.CITY_WEIGHTS)[0]
        kind = rng.choices(["PHARMACY", "CLINIC", "HOSPITAL"], weights=[75, 18, 7])[0]
        part = rng.choice(catalog.NAME_PARTS)
        if kind == "PHARMACY":
            trade_name = f"{rng.choice(catalog.PHARMACY_PREFIXES)} {part}"
            legal_suffix = "Comércio de Medicamentos Ltda"
        elif kind == "CLINIC":
            trade_name = f"{rng.choice(catalog.CLINIC_PREFIXES)} {part}"
            legal_suffix = "Serviços Médicos Ltda"
        else:
            trade_name = f"{rng.choice(catalog.HOSPITAL_PREFIXES)} {part}"
            legal_suffix = "Serviços Hospitalares S.A."
        # Pareto: poucos clientes concentram o volume
        weight = rng.paretovariate(1.4) * (3 if kind == "HOSPITAL" else 1)
        weights.append(weight)
        if weight > 6:
            price_table_id = 4
        elif kind == "PHARMACY":
            price_table_id = rng.choice([1, 1, 2])
        else:
            price_table_id = 3
        wh_index = catalog.STATE_TO_WAREHOUSE.get(city.state, 0)
        warehouse_id = wh_index + 1 if wh_index < len(warehouses) else 1
        contact = f"{rng.choice(catalog.FIRST_NAMES)} {rng.choice(catalog.LAST_NAMES)}"
        code = f"CLI{customer_id:06d}"
        customers.append(
            Customer(
                customer_id=customer_id,
                customer_code=code,
                legal_name=f"{trade_name} {city.name} {legal_suffix}",
                trade_name=trade_name,
                cnpj=generate_cnpj(rng),
                customer_type=kind,
                city_ibge_code=city.ibge_code,
                city_name=city.name,
                state=city.state,
                price_table_id=price_table_id,
                warehouse_id=warehouse_id,
                credit_limit_cents=rng.choice([5_000_00, 20_000_00, 50_000_00, 200_000_00]),
                contact_name=contact,
                email=f"compras.{code.lower()}@{slugify(trade_name)}.example",
                phone=f"+55 {city.area_code} 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                segment=rng.choice(["A", "B", "B", "C", "C", "C"]),
                created_on=config.history_start - timedelta(days=rng.randint(30, 3000)),
            )
        )
    return customers, weights


def _build_products(config: SimulatorConfig) -> tuple[list[Product], list[float]]:
    rng = rng_for(config.seed, "products")
    combos: list[tuple[catalog.Ingredient, str, str, int, tuple[str, float]]] = []
    for ingredient in catalog.MEDICINES + catalog.SUPPLIES:
        packs = (
            catalog.SUPPLY_PACK_SIZES
            if ingredient in catalog.SUPPLIES
            else catalog.MEDICINE_PACK_SIZES
        )
        combos.extend(
            itertools.product(
                [ingredient], ingredient.dosages, ingredient.forms, packs, catalog.MANUFACTURERS
            )
        )
    if config.profile.products > len(combos):
        raise ValueError(f"O catálogo comporta no máximo {len(combos)} produtos")
    rng.shuffle(combos)
    products: list[Product] = []
    weights: list[float] = []
    for product_id, (ing, dosage, form, pack, (maker, factor)) in enumerate(
        combos[: config.profile.products], start=1
    ):
        dosage_factor = 1 + 0.25 * ing.dosages.index(dosage)
        price = (
            ing.base_price_cents
            * (pack / 10) ** 0.85
            * dosage_factor
            * factor
            * rng.uniform(0.9, 1.1)
        )
        products.append(
            Product(
                product_id=product_id,
                product_code=f"PRD{product_id:05d}",
                description=f"{ing.name} {dosage} {form} cx c/ {pack} un - {maker}",
                category=ing.category,
                active_ingredient=ing.name,
                manufacturer=maker,
                pack_size=pack,
                requires_prescription=ing.requires_prescription,
                list_price_cents=max(100, round(price)),
            )
        )
        weights.append(rng.paretovariate(1.2))
    return products, weights


def _build_lots(config: SimulatorConfig, products: list[Product]) -> list[Lot]:
    """Lotes fabricados a cada 2 a 5 meses, com validade de 18 a 30 meses."""
    rng = rng_for(config.seed, "lots")
    lots: list[Lot] = []
    first_batch = config.history_start - timedelta(days=720)
    for product in products:
        made_on = first_batch + timedelta(days=rng.randint(0, 90))
        sequence = 1
        while made_on <= config.history_end:
            lots.append(
                Lot(
                    lot_id=len(lots) + 1,
                    product_id=product.product_id,
                    lot_number=f"L{made_on:%y%m}{product.product_id:05d}{sequence:02d}",
                    manufactured_on=made_on,
                    expires_on=made_on + timedelta(days=rng.randint(540, 900)),
                )
            )
            made_on += timedelta(days=rng.randint(60, 150))
            sequence += 1
    return lots


def build_master_data(config: SimulatorConfig) -> MasterData:
    warehouses = _build_warehouses(config.profile.warehouses)
    customers, customer_weights = _build_customers(config, warehouses)
    products, product_weights = _build_products(config)
    return MasterData(
        config=config,
        price_tables=_build_price_tables(),
        warehouses=warehouses,
        customers=customers,
        products=products,
        lots=_build_lots(config, products),
        customer_weights=customer_weights,
        product_weights=product_weights,
        price_adjustment_dates=_adjustment_dates(config.history_start, config.history_end),
    )
