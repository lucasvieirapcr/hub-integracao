"""Loja B2B: autenticação, paginação por cursor, limite de requisições e idempotência."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from simulator import payloads
from simulator.activity import ActivityGenerator
from simulator.chaos import ChaosLedger, ChaosRule
from simulator.master_data import MasterData
from source_systems.b2b_store.app import create_app
from source_systems.common.settings import B2bSettings
from tests.conftest import ADMIN_TOKEN, FakeClock, auth


def _orders(generator: ActivityGenerator, *days: date) -> list[dict[str, Any]]:
    return [payloads.b2b_order_payload(o) for d in days for o in generator.day(d).b2b_orders]


@pytest.fixture
def client(api_settings_kwargs: dict[str, Any], clock: FakeClock) -> TestClient:
    settings = B2bSettings(**api_settings_kwargs)
    return TestClient(create_app(settings, monotonic=clock.monotonic, sleep=lambda _: None))


def _read_all(client: TestClient, path: str, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = client.get(path, params=params, headers=auth())
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_valid_token(client: TestClient) -> None:
    assert client.get("/v1/orders").status_code == 401
    assert client.get("/v1/orders", headers=auth("errado")).status_code == 401
    # O token de cliente não abre as rotas de administração.
    assert client.post("/admin/orders", json={"orders": []}, headers=auth()).status_code == 401


def test_cursor_pagination_reads_every_order_once(
    client: TestClient, generator: ActivityGenerator
) -> None:
    orders = _orders(generator, date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15))
    response = client.post("/admin/orders", json={"orders": orders}, headers=auth(ADMIN_TOKEN))
    assert response.status_code == 200

    read = _read_all(client, "/v1/orders", limit=3)
    assert sorted(o["order_id"] for o in read) == sorted(o["order_id"] for o in orders)
    assert [(o["updated_at"], o["order_id"]) for o in read] == sorted(
        (o["updated_at"], o["order_id"]) for o in read
    )


def test_new_data_during_pagination_does_not_shift_pages(
    client: TestClient, generator: ActivityGenerator
) -> None:
    first_day = _orders(generator, date(2026, 10, 13))
    client.post("/admin/orders", json={"orders": first_day}, headers=auth(ADMIN_TOKEN))
    page1 = client.get("/v1/orders", params={"limit": 2}, headers=auth()).json()

    # Chega um dia novo no meio da leitura: com cursor, o cliente continua de onde parou.
    client.post(
        "/admin/orders",
        json={"orders": _orders(generator, date(2026, 10, 14))},
        headers=auth(ADMIN_TOKEN),
    )
    rest: list[dict[str, Any]] = []
    cursor = page1["next_cursor"]
    while cursor:
        body = client.get(
            "/v1/orders", params={"limit": 2, "cursor": cursor}, headers=auth()
        ).json()
        rest.extend(body["data"])
        cursor = body["next_cursor"]
    seen = [o["order_id"] for o in page1["data"] + rest]
    assert len(seen) == len(set(seen))
    assert {o["order_id"] for o in first_day} <= set(seen)


def test_updated_since_filters_incrementally(
    client: TestClient, generator: ActivityGenerator
) -> None:
    orders = _orders(generator, date(2026, 10, 13), date(2026, 10, 14))
    client.post("/admin/orders", json={"orders": orders}, headers=auth(ADMIN_TOKEN))
    since = "2026-10-14T00:00:00Z"
    body = client.get(
        "/v1/orders", params={"updated_since": since, "limit": 1000}, headers=auth()
    ).json()
    expected = {o["order_id"] for o in orders if o["updated_at"] >= "2026-10-14T00:00:00+00:00"}
    assert {o["order_id"] for o in body["data"]} == expected


def test_reposting_orders_does_not_duplicate(
    client: TestClient, generator: ActivityGenerator
) -> None:
    orders = _orders(generator, date(2026, 10, 14))
    for _ in range(2):
        client.post("/admin/orders", json={"orders": orders}, headers=auth(ADMIN_TOKEN))
    read = _read_all(client, "/v1/orders", limit=100)
    assert len(read) == len(orders)
    original = next(o for o in orders if o["order_id"] == read[0]["order_id"])
    assert read[0]["items"] == original["items"]
    assert read[0]["total_amount_cents"] == sum(
        i["quantity"] * i["unit_price_cents"] for i in original["items"]
    )


def test_rate_limit_returns_429_with_retry_after(
    api_settings_kwargs: dict[str, Any], clock: FakeClock
) -> None:
    settings = B2bSettings(
        **{**api_settings_kwargs, "rate_limit_per_minute": 30, "rate_limit_burst": 2}
    )
    client = TestClient(create_app(settings, monotonic=clock.monotonic))
    statuses = [client.get("/v1/orders", headers=auth()).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    blocked = client.get("/v1/orders", headers=auth())
    assert blocked.headers["Retry-After"] == "2"  # 30/min = uma ficha a cada 2 s
    clock.advance(2)
    assert client.get("/v1/orders", headers=auth()).status_code == 200


def test_invalid_cursor_and_unknown_order(client: TestClient) -> None:
    assert client.get("/v1/orders", params={"cursor": "lixo"}, headers=auth()).status_code == 400
    assert client.get("/v1/orders/NAO-EXISTE", headers=auth()).status_code == 404


def test_catalog_endpoint(client: TestClient, master: MasterData) -> None:
    products = [payloads.product_payload(master, p, date(2026, 10, 31)) for p in master.products]
    client.post("/admin/products", json={"products": products}, headers=auth(ADMIN_TOKEN))
    read = _read_all(client, "/v1/products", limit=7)
    assert {p["product_code"] for p in read} == {p.product_code for p in master.products}


def test_outage_chaos_returns_503_and_is_recorded(
    api_settings_kwargs: dict[str, Any], tmp_path: Path, clock: FakeClock
) -> None:
    from simulator.chaos import ApiChaos
    from source_systems.common.guard import ApiGuard

    settings = B2bSettings(**api_settings_kwargs)
    guard = ApiGuard(
        settings,
        ApiChaos(outage=ChaosRule(enabled=True, probability=1.0)),
        ChaosLedger(tmp_path / "chaos", "b2b_store"),
        monotonic=clock.monotonic,
    )
    with pytest.raises(Exception) as error:
        guard.client(authorization=f"Bearer {settings.api_token.get_secret_value()}")
    assert getattr(error.value, "status_code", None) == 503
    assert "outage" in (tmp_path / "chaos" / "b2b_store.jsonl").read_text("utf-8")
