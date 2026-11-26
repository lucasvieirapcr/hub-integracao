"""CRM e gateway de pagamento: idempotência por event_id, outbox, assinatura, retry e caos."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from simulator import payloads
from simulator.activity import ActivityGenerator
from simulator.master_data import MasterData
from source_systems.common.settings import CrmSettings, PaymentsSettings
from source_systems.common.webhooks import verify_signature
from source_systems.crm.app import create_app as create_crm
from source_systems.payments.app import create_app as create_payments
from tests.conftest import ADMIN_TOKEN, WEBHOOK_SECRET, FakeClock, auth

RECEIVER_URL = "http://receptor.teste/webhooks"
DAY = date(2026, 10, 14)


class FakeReceiver:
    """Receptor de webhooks em memória (httpx.MockTransport). Pode simular falhas."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_times > 0:
            self.fail_times -= 1
            return httpx.Response(500)
        return httpx.Response(200)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def event_ids(self) -> list[str]:
        return [r.headers["X-Event-Id"] for r in self.requests]


def _webhook_kwargs(api_settings_kwargs: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        **api_settings_kwargs,
        "webhook_secret": WEBHOOK_SECRET,
        "webhook_url": RECEIVER_URL,
        **extra,
    }


@pytest.fixture
def receiver() -> FakeReceiver:
    return FakeReceiver()


@pytest.fixture
def crm(
    api_settings_kwargs: dict[str, Any],
    clock: FakeClock,
    receiver: FakeReceiver,
    master: MasterData,
) -> TestClient:
    settings = CrmSettings(**_webhook_kwargs(api_settings_kwargs))
    client = TestClient(create_crm(settings, http_client=receiver.client(), clock=clock))
    customers = [payloads.crm_customer_payload(c) for c in master.customers]
    response = client.post(
        "/admin/customers", json={"customers": customers}, headers=auth(ADMIN_TOKEN)
    )
    assert response.status_code == 200
    return client


def _crm_events(generator: ActivityGenerator) -> list[dict[str, Any]]:
    return [payloads.crm_change_payload(c) for c in generator.day(DAY).crm_changes]


def test_crm_applies_changes_and_ignores_duplicates(
    crm: TestClient, generator: ActivityGenerator
) -> None:
    events = _crm_events(generator)
    first = crm.post("/admin/events", json={"events": events}, headers=auth(ADMIN_TOKEN)).json()
    second = crm.post("/admin/events", json={"events": events}, headers=auth(ADMIN_TOKEN)).json()
    assert first["applied"] == first["enqueued"] == len(events)
    assert second == {
        "received": len(events),
        "applied": 0,
        "ignored_duplicates": len(events),
        "enqueued": 0,
    }

    updated = next(e for e in events if e["event_type"] == "customer.updated")
    customer = crm.get(f"/v1/customers/{updated['customer_code']}", headers=auth()).json()
    field, value = next(iter(updated["changes"].items()))
    assert customer[field] == value
    assert customer["version"] >= 2


def test_crm_delivers_signed_webhooks(
    crm: TestClient, generator: ActivityGenerator, receiver: FakeReceiver, clock: FakeClock
) -> None:
    events = _crm_events(generator)
    crm.post("/admin/events", json={"events": events}, headers=auth(ADMIN_TOKEN))
    report = crm.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()

    assert report["delivered"] == len(events)
    assert sorted(receiver.event_ids()) == sorted(e["event_id"] for e in events)
    for request in receiver.requests:
        assert verify_signature(
            WEBHOOK_SECRET,
            request.headers["X-Signature"],
            request.content,
            now=int(clock().timestamp()),
        )
        body = json.loads(request.content)
        assert body["event_id"] == request.headers["X-Event-Id"]
        assert "version" in body["data"] and "changed_fields" in body["data"]
    # Entregue não é reenviado.
    assert crm.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()["delivered"] == 0


def test_failed_delivery_is_retried_with_backoff(
    api_settings_kwargs: dict[str, Any],
    clock: FakeClock,
    master: MasterData,
    generator: ActivityGenerator,
) -> None:
    receiver = FakeReceiver(fail_times=1)
    settings = CrmSettings(**_webhook_kwargs(api_settings_kwargs, webhook_max_attempts=3))
    client = TestClient(create_crm(settings, http_client=receiver.client(), clock=clock))
    client.post(
        "/admin/customers",
        json={"customers": [payloads.crm_customer_payload(c) for c in master.customers]},
        headers=auth(ADMIN_TOKEN),
    )
    event = _crm_events(generator)[:1]
    client.post("/admin/events", json={"events": event}, headers=auth(ADMIN_TOKEN))

    first = client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()
    assert first["retried"] == 1
    # Antes do intervalo de espera, nada é reenviado.
    assert (
        client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()["delivered"] == 0
    )
    clock.advance(10)  # 1ª espera: 5 s x jitter (0,5 a 1,0)
    assert (
        client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()["delivered"] == 1
    )
    stats = client.get("/admin/webhooks/stats", headers=auth(ADMIN_TOKEN)).json()
    assert stats == {"PENDING": 0, "DELIVERED": 1, "FAILED": 0}


def test_delivery_gives_up_after_max_attempts(
    api_settings_kwargs: dict[str, Any],
    clock: FakeClock,
    master: MasterData,
    generator: ActivityGenerator,
) -> None:
    receiver = FakeReceiver(fail_times=99)
    settings = CrmSettings(**_webhook_kwargs(api_settings_kwargs, webhook_max_attempts=2))
    client = TestClient(create_crm(settings, http_client=receiver.client(), clock=clock))
    client.post(
        "/admin/customers",
        json={"customers": [payloads.crm_customer_payload(c) for c in master.customers]},
        headers=auth(ADMIN_TOKEN),
    )
    client.post(
        "/admin/events", json={"events": _crm_events(generator)[:1]}, headers=auth(ADMIN_TOKEN)
    )
    client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN))
    clock.advance(3600)
    client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN))
    stats = client.get("/admin/webhooks/stats", headers=auth(ADMIN_TOKEN)).json()
    assert stats["FAILED"] == 1


def test_invalid_create_event_rolls_back_the_whole_batch(crm: TestClient) -> None:
    bad = {
        "event_id": "evt-1",
        "event_type": "customer.created",
        "customer_code": "CRM-NOVO",
        "occurred_at": "2026-10-14T12:00:00Z",
        "changes": {"trade_name": "Sem os campos obrigatórios"},
    }
    response = crm.post("/admin/events", json={"events": [bad]}, headers=auth(ADMIN_TOKEN))
    assert response.status_code == 422
    assert crm.get("/v1/customers/CRM-NOVO", headers=auth()).status_code == 404


def test_duplicate_chaos_sends_event_twice_and_records_it(
    api_settings_kwargs: dict[str, Any],
    tmp_path: Path,
    clock: FakeClock,
    master: MasterData,
    generator: ActivityGenerator,
) -> None:
    chaos_file = tmp_path / "chaos.yaml"
    chaos_file.write_text(
        yaml.safe_dump({"crm": {"duplicate_events": {"enabled": True, "probability": 1.0}}}),
        encoding="utf-8",
    )
    receiver = FakeReceiver()
    settings = CrmSettings(**_webhook_kwargs(api_settings_kwargs, chaos_config_path=chaos_file))
    client = TestClient(create_crm(settings, http_client=receiver.client(), clock=clock))
    client.post(
        "/admin/customers",
        json={"customers": [payloads.crm_customer_payload(c) for c in master.customers]},
        headers=auth(ADMIN_TOKEN),
    )
    events = _crm_events(generator)[:2]
    client.post("/admin/events", json={"events": events}, headers=auth(ADMIN_TOKEN))
    report = client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()

    assert report["duplicates_sent"] == 2
    assert sorted(receiver.event_ids()) == sorted([e["event_id"] for e in events] * 2)
    ledger = (tmp_path / "chaos" / "crm.jsonl").read_text("utf-8")
    assert ledger.count("duplicate_event") == 2


def test_without_webhook_url_events_wait_in_outbox(
    api_settings_kwargs: dict[str, Any],
    clock: FakeClock,
    master: MasterData,
    generator: ActivityGenerator,
) -> None:
    settings = CrmSettings(**_webhook_kwargs(api_settings_kwargs, webhook_url=""))
    client = TestClient(create_crm(settings, clock=clock))
    client.post(
        "/admin/customers",
        json={"customers": [payloads.crm_customer_payload(c) for c in master.customers]},
        headers=auth(ADMIN_TOKEN),
    )
    events = _crm_events(generator)
    client.post("/admin/events", json={"events": events}, headers=auth(ADMIN_TOKEN))
    assert (
        client.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN)).json()["delivered"] == 0
    )
    stats = client.get("/admin/webhooks/stats", headers=auth(ADMIN_TOKEN)).json()
    assert stats["PENDING"] == len(events)


@pytest.fixture
def gateway(
    api_settings_kwargs: dict[str, Any], clock: FakeClock, receiver: FakeReceiver
) -> TestClient:
    settings = PaymentsSettings(**_webhook_kwargs(api_settings_kwargs))
    return TestClient(create_payments(settings, http_client=receiver.client(), clock=clock))


def test_payments_are_queryable_and_events_idempotent(
    gateway: TestClient, generator: ActivityGenerator, receiver: FakeReceiver
) -> None:
    payments = [payloads.payment_payload(p) for p in generator.day(DAY).payments]
    total_events = sum(len(p["events"]) for p in payments)
    batch = {"payments": payments, "enqueue_webhooks": True}

    first = gateway.post("/admin/payments", json=batch, headers=auth(ADMIN_TOKEN)).json()
    second = gateway.post("/admin/payments", json=batch, headers=auth(ADMIN_TOKEN)).json()
    assert first["enqueued"] == total_events
    assert second["enqueued"] == 0 and second["ignored_duplicates"] == total_events

    sample = payments[0]
    stored = gateway.get(f"/v1/payments/{sample['payment_id']}", headers=auth()).json()
    assert stored["status"] == sample["status"]
    assert [e["event_id"] for e in stored["events"]] == [e["event_id"] for e in sample["events"]]

    gateway.post("/admin/webhooks/deliver", headers=auth(ADMIN_TOKEN))
    statuses = {json.loads(r.content)["data"]["status"] for r in receiver.requests}
    assert statuses <= {"approved", "declined", "refunded"}
    assert len(receiver.requests) == total_events


def test_older_payment_update_does_not_overwrite_newer(gateway: TestClient) -> None:
    newer = {
        "payment_id": "pay_1",
        "order_ref": "B2B-1",
        "amount_cents": 1000,
        "method": "PIX",
        "status": "refunded",
        "created_at": "2026-10-14T10:00:00Z",
        "updated_at": "2026-10-14T15:00:00Z",
        "events": [
            {
                "event_id": "e2",
                "event_type": "payment.refunded",
                "occurred_at": "2026-10-14T15:00:00Z",
            }
        ],
    }
    older = {
        **newer,
        "status": "approved",
        "updated_at": "2026-10-14T10:01:00Z",
        "events": [
            {
                "event_id": "e1",
                "event_type": "payment.approved",
                "occurred_at": "2026-10-14T10:01:00Z",
            }
        ],
    }
    for payment in (newer, older):
        gateway.post(
            "/admin/payments",
            json={"payments": [payment], "enqueue_webhooks": False},
            headers=auth(ADMIN_TOKEN),
        )
    stored = gateway.get("/v1/payments/pay_1", headers=auth()).json()
    assert stored["status"] == "refunded"
    assert [e["event_id"] for e in stored["events"]] == ["e1", "e2"]
