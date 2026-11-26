"""CSV diário do fornecedor: separador ';', vírgula decimal, datas dd/mm/aaaa e CRLF."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from simulator.chaos import SupplierFileChaos
from simulator.master_data import MasterData, Product
from simulator.rng import rng_for

COLUMNS = (
    "codigo_fornecedor",
    "codigo_produto",
    "descricao",
    "preco_unitario",
    "quantidade_disponivel",
    "lote",
    "validade",
    "data_referencia",
)
RENAMED_COLUMNS = {"preco_unitario": "vl_unitario", "quantidade_disponivel": "qtd_disp"}
SUPPLIER_COVERAGE = 0.30  # o fornecedor trabalha com 30% do catálogo


@dataclass(slots=True)
class SupplierFile:
    file_name: str
    content: bytes
    encoding: str
    row_count: int
    late: bool = False
    injected: list[dict[str, Any]] = field(default_factory=list)


def file_name_for(day: date) -> str:
    return f"fornecedor_{day:%Y%m%d}.csv"


def supplier_products(master: MasterData) -> list[Product]:
    rng = rng_for(master.config.seed, "supplier_catalog")
    count = max(1, round(len(master.products) * SUPPLIER_COVERAGE))
    return sorted(rng.sample(master.products, count), key=lambda p: p.product_id)


def _money(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def build_supplier_file(
    master: MasterData, day: date, chaos: SupplierFileChaos, chaos_seed: int = 0
) -> SupplierFile:
    rng = rng_for(master.config.seed, "supplier_file", day.isoformat())
    rows: list[list[str]] = []
    for product in supplier_products(master):
        cost = round(master.list_price_on(product, day) * rng.uniform(0.55, 0.75))
        expires_on = day + timedelta(days=rng.randint(300, 800))
        rows.append(
            [
                f"FOR-{product.product_id:05d}",
                product.product_code,
                product.description,
                _money(cost),
                str(rng.randint(0, 5000)),
                f"F{day:%y%m}{product.product_id:05d}",
                f"{expires_on:%d/%m/%Y}",
                f"{day:%d/%m/%Y}",
            ]
        )

    chaos_rng = rng_for(chaos_seed, "supplier_file", day.isoformat())
    injected: list[dict[str, Any]] = []
    header = list(COLUMNS)

    if chaos.renamed_column.fires(chaos_rng):
        original = chaos_rng.choice(sorted(RENAMED_COLUMNS))
        header[header.index(original)] = RENAMED_COLUMNS[original]
        injected.append(
            {"kind": "renamed_column", "column": original, "renamed_to": RENAMED_COLUMNS[original]}
        )

    if chaos.invalid_rows.fires(chaos_rng) and rows:
        how_many = chaos_rng.randint(1, min(chaos.invalid_rows.max_rows, len(rows)))
        for index in sorted(chaos_rng.sample(range(len(rows)), how_many)):
            problem = chaos_rng.choice(
                ["empty_product_code", "negative_price", "invalid_date", "bad_quantity"]
            )
            row = rows[index]
            if problem == "empty_product_code":
                row[1] = ""
            elif problem == "negative_price":
                row[3] = "-" + row[3]
            elif problem == "invalid_date":
                row[6] = "31/02/" + row[6][-4:]
            else:
                row[4] = "N/D"
            # Linha 1 é o cabeçalho; a primeira linha de dados é a 2.
            injected.append({"kind": "invalid_row", "line": index + 2, "problem": problem})

    encoding = "utf-8"
    if chaos.wrong_encoding.fires(chaos_rng):
        encoding = "cp1252"
        injected.append({"kind": "wrong_encoding", "encoding": encoding})

    late = chaos.late.fires(chaos_rng)
    if late:
        injected.append({"kind": "late_file"})

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return SupplierFile(
        file_name=file_name_for(day),
        content=buffer.getvalue().encode(encoding),
        encoding=encoding,
        row_count=len(rows),
        late=late,
        injected=injected,
    )
