"""Testes contra os containers. Zeram o ERP (perfil test); rodam com --integration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import paramiko
import pytest

from simulator.activity import ActivityGenerator
from simulator.chaos import ChaosLedger, ErpChaos
from simulator.erp_loader import connect, seed_erp
from simulator.erp_simulation import next_simulation_day, simulate_erp_day
from simulator.host_settings import HostSettings
from simulator.master_data import MasterData
from simulator.supplier_file import file_name_for

pytestmark = pytest.mark.integration

# Contagens e somas que precisam ser idênticas após reexecutar uma carga.
FINGERPRINT_SQL = """
select (select count(*) from orders),
       (select nvl(sum(total_amount), 0) from orders),
       (select count(*) from order_items),
       (select count(*) from invoices),
       (select nvl(sum(total_amount), 0) from invoices),
       (select count(*) from invoice_items),
       (select nvl(sum(qty_on_hand), 0) from stock),
       (select nvl(sum(qty_reserved), 0) from stock),
       (select count(*) from stock_movements)
  from dual
"""


@pytest.fixture(scope="module")
def settings() -> HostSettings:
    return HostSettings()


@pytest.fixture(scope="module")
def connection(settings: HostSettings) -> Iterator[Any]:
    conn = connect(
        settings.erp_db_user, settings.erp_db_password.get_secret_value(), settings.oracle_dsn
    )
    yield conn
    conn.close()


def _fingerprint(conn: Any) -> tuple[Any, ...]:
    with conn.cursor() as cursor:
        cursor.execute(FINGERPRINT_SQL)
        row: tuple[Any, ...] = cursor.fetchone()
        return row


def test_erp_seed_is_idempotent(
    connection: Any, master: MasterData, generator: ActivityGenerator
) -> None:
    seed_erp(connection, master, generator, progress=lambda _: None)
    first = _fingerprint(connection)
    seed_erp(connection, master, generator, progress=lambda _: None)
    assert _fingerprint(connection) == first
    assert first[0] > 0 and first[3] > 0


def test_simulated_day_is_idempotent_and_follows_rules(
    connection: Any, master: MasterData, generator: ActivityGenerator, tmp_path: Any
) -> None:
    seed_erp(connection, master, generator, progress=lambda _: None)
    day = next_simulation_day(connection, master.config.history_end)
    activity = generator.day(day)
    ledger = ChaosLedger(tmp_path, "erp")

    first = simulate_erp_day(connection, master, activity, ErpChaos(), 0, ledger)
    after_first = _fingerprint(connection)
    second = simulate_erp_day(connection, master, activity, ErpChaos(), 0, ledger)

    assert not first.skipped and first.created > 0
    assert second.skipped
    assert _fingerprint(connection) == after_first

    with connection.cursor() as cursor:
        # Toda nota bate com o total do pedido (pedido de um lote só ou dividido em vários).
        cursor.execute(
            """
            select count(*) from orders o join invoices i on i.order_id = o.order_id
             where o.order_date = :1 and o.total_amount != i.total_amount
            """,
            [day],
        )
        assert cursor.fetchone()[0] == 0
        # FEFO respeitou a validade mínima de 30 dias em toda nota do dia.
        cursor.execute(
            """
            select count(*) from invoice_items ii
              join invoices i on i.invoice_id = ii.invoice_id
              join orders o on o.order_id = i.order_id
              join lots l on l.lot_id = ii.lot_id
             where o.order_date = :1 and l.expires_on <= o.order_date + 30
            """,
            [day],
        )
        assert cursor.fetchone()[0] == 0
        # Nenhum saldo reservado ficou pendurado: tudo foi faturado ou cancelado.
        cursor.execute("select nvl(sum(qty_reserved), 0) from stock")
        assert cursor.fetchone()[0] == 0
    assert day == master.config.history_end + timedelta(days=1)


@pytest.mark.parametrize(
    ("base_attr", "token_attr", "path"),
    [
        ("b2b_base_url", "b2b_api_token", "/v1/orders"),
        ("crm_base_url", "crm_api_token", "/v1/customers"),
        ("payments_base_url", "payments_api_token", "/v1/payments"),
    ],
)
def test_apis_paginate_and_rate_limit(
    settings: HostSettings, base_attr: str, token_attr: str, path: str
) -> None:
    base_url: str = getattr(settings, base_attr)
    token: str = getattr(settings, token_attr).get_secret_value()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/health").status_code == 200
        assert client.get(path).status_code == 401
        page = client.get(path, params={"limit": 5}, headers=headers)
        assert page.status_code == 200
        assert set(page.json()) == {"data", "next_cursor"}
        statuses = [
            client.get(path, params={"limit": 1}, headers=headers).status_code for _ in range(40)
        ]
    assert 429 in statuses, "o limite de requisições deveria ter sido atingido"


def test_supplier_file_is_on_sftp(settings: HostSettings, master: MasterData) -> None:
    transport = paramiko.Transport((settings.sftp_host, settings.sftp_port))
    try:
        transport.connect(
            username=settings.sftp_user, password=settings.sftp_password.get_secret_value()
        )
        sftp = paramiko.SFTPClient.from_transport(transport)
        assert sftp is not None
        names = sftp.listdir("inbox")
    finally:
        transport.close()
    # `make seed` envia o arquivo do último dia do histórico (igual em todos os perfis).
    assert file_name_for(master.config.history_end) in names
    assert not any(name.endswith(".part") for name in names), "sobrou arquivo temporário"
